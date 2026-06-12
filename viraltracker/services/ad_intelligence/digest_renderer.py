"""DigestRenderer — render the weekly per-product digest.

Pure formatting: takes the assembled digest data (from WeeklyDigestService).
``render_brand_digest`` returns ``(fallback_text, blocks)`` for Slack (awareness
breakdowns in monospace code blocks, since Slack does not render markdown tables).
``render_brand_digest_html`` returns a standalone, styled HTML document with the
full metric grid — uploaded to storage and linked from the Slack message for a
cleaner view. All money is in the account currency (e.g. CAD).
"""
from __future__ import annotations

import html
from typing import Any, Dict, List, Optional, Tuple


def _money(v: Optional[float], currency: str) -> str:
    if v is None:
        return "-"
    return f"${v:,.0f} {currency}" if abs(v) >= 1000 else f"${v:,.2f} {currency}"


def _cpa(v: Optional[float]) -> str:
    return f"${v:,.2f}" if v is not None else "-"


def _cpa0(v: Optional[float]) -> str:
    """Compact whole-dollar CPA for the multi-column awareness table."""
    return f"${v:,.0f}" if v is not None else "-"


def _roas(v: Optional[float]) -> str:
    """Compact ROAS (revenue ÷ spend) as e.g. 2.3x."""
    return f"{v:.1f}x" if v is not None else "-"


def _pct(v: Optional[float]) -> str:
    """CVR ratio -> percentage, e.g. 0.0152 -> 1.5%."""
    return f"{v * 100:.1f}%" if v is not None else "-"


def _awareness_table(rows: List[Dict[str, Any]]) -> str:
    """Two monospace tables per product (Slack code blocks): an efficiency
    overview (spend, ROAS, CVR, blended CPA + cost-per-ATC) and a cost-target
    breakdown (per-ad median & top-quartile p25 for CPA and ATC, + brand CPA
    benchmark). Two tables because ~11 metrics/level won't fit one Slack row.
    """
    if not rows:
        return "_no classified ads in scope_"

    def _lvl(r):
        return str(r.get("level", "")).replace("_", " ")[:14]

    def _spend(r):
        s = r.get("spend")
        return f"${s:,.0f}" if s is not None else "-"

    # Table 1 — efficiency overview (CPA/ATC here are blended)
    t1 = [f"{'Level':<15}{'Ads':>4} {'Spend':>8} {'ROAS':>5} {'CVR':>6} {'CPA':>6} {'ATC':>6}"]
    for r in rows:
        t1.append(
            f"{_lvl(r):<15}{r.get('ads', 0):>4} {_spend(r):>8} "
            f"{_roas(r.get('roas')):>5} {_pct(r.get('cvr')):>6} "
            f"{_cpa0(r.get('agg_cpa')):>6} {_cpa0(r.get('agg_catc')):>6}"
        )
    # Table 2 — per-ad cost targets (median + top-quartile p25), + brand CPA benchmark
    t2 = [f"{'Level':<15}{'cpaMed':>7} {'cpaP25':>7} {'atcMed':>7} {'atcP25':>7} {'BrMed':>7}"]
    for r in rows:
        t2.append(
            f"{_lvl(r):<15}{_cpa0(r.get('prod_med_cpa')):>7} {_cpa0(r.get('prod_p25_cpa')):>7} "
            f"{_cpa0(r.get('prod_med_catc')):>7} {_cpa0(r.get('prod_p25_catc')):>7} "
            f"{_cpa0(r.get('brand_med_cpa')):>7}"
        )
    return (
        "```\n" + "\n".join(t1) + "\n```\n"
        "_targets — $/purchase (cpa) & $/add-to-cart (atc), per-ad median & p25:_\n"
        "```\n" + "\n".join(t2) + "\n```"
    )


def _market_line(markets: Dict[str, Dict[str, Any]]) -> str:
    """One-line US/CA split: `US $3,719 (CPA $46) · CA $0`."""
    if not markets:
        return ""
    parts = []
    for code in sorted(markets.keys()):
        m = markets[code]
        seg = f"*{code}* ${m.get('spend', 0):,.0f}"
        if m.get("cpa") is not None:
            seg += f" (CPA {_cpa(m['cpa'])})"
        parts.append(seg)
    return "Market: " + "  ·  ".join(parts)


def _completeness_line(p: Dict[str, Any], currency: str) -> Optional[str]:
    """Slack completeness footnote + the 'cannot classify' (low_res) line. Returns None
    when everything is current and there is no low_res to report (a fully-clean product)."""
    c = p.get("completeness") or {}
    stale = c.get("stale_spend", 0.0) or 0.0
    unclass = c.get("unclassified_spend", 0.0) or 0.0
    low_res = c.get("low_res_spend", 0.0) or 0.0
    if stale <= 0 and unclass <= 0 and low_res <= 0:
        return None
    pct = (c.get("current_pct") or 0.0) * 100
    gap = []
    if stale > 0:
        gap.append(f"{_money(stale, currency)} stale")
    if unclass > 0:
        gap.append(f"{_money(unclass, currency)} not yet classified")
    foot = f"_Classified: {pct:.0f}% of classifiable spend"
    if gap:
        foot += " · " + ", ".join(gap)
    foot += "_"
    lines = [foot]
    if low_res > 0:
        # low_res is excluded from the % above (can't be classified without a re-fetch).
        lines.append(f":no_entry_sign: _Cannot classify (needs high-res re-fetch): {_money(low_res, currency)}_")
    return "\n".join(lines)


def _product_block(p: Dict[str, Any], currency: str) -> Dict[str, Any]:
    name = p.get("name", "Unnamed")
    if p.get("error"):
        text = f"*{name}*\n:warning: _Could not analyze this product this run._"
        return {"type": "section", "text": {"type": "mrkdwn", "text": text}}
    if p.get("no_ads"):
        text = f"*{name}*\n_No ads with spend in scope this period._"
        return {"type": "section", "text": {"type": "mrkdwn", "text": text}}

    head = f"*{name}*  —  {_money(p.get('total_spend'), currency)} · {p.get('spending_ads', 0)} ads w/ spend"
    chunks = [head]
    mline = _market_line(p.get("markets") or {})
    if mline:
        chunks.append(mline)
    # Publish gate: below the completeness threshold a partial sample would mislead as the
    # headline mix, so show "pending" instead of the distribution. Everything else (CPA,
    # completeness line, attribution coverage) still publishes.
    if p.get("awareness_pending"):
        c = p.get("completeness") or {}
        if (c.get("classifiable_spend") or 0) <= 0:
            # All spend is low_res — nothing to backfill (needs a high-res re-fetch); the
            # "Cannot classify" line below carries the detail. Do NOT promise a backfill.
            chunks.append(
                ":no_entry_sign: *Awareness not classifiable this period* — all spend is on "
                "images too low-res to read at the current resolution (see below)."
            )
        else:
            pct = (c.get("current_pct") or 0.0) * 100
            chunks.append(
                f":hourglass_flowing_sand: *Awareness mix pending* — only {pct:.0f}% of "
                f"classifiable spend is classified at the current version. The distribution "
                f"appears once the backfill completes."
            )
    else:
        chunks.append(_awareness_table(p.get("awareness") or []))
    cl = _completeness_line(p, currency)
    if cl:
        chunks.append(cl)
    if p.get("insight"):
        chunks.append(f":bulb: {p['insight']}")
    text = "\n".join(chunks)
    # Slack section text caps at 3000 chars; truncate defensively.
    if len(text) > 2900:
        text = text[:2890] + "\n…```"
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def render_brand_digest(data: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]]]:
    """Return (fallback_text, blocks) for the brand's weekly digest."""
    brand = data.get("brand_name", "Brand")
    currency = data.get("currency", "USD")
    date_range = data.get("date_range", "Last 30 days")
    products = data.get("products") or []
    coverage = data.get("coverage") or {}
    unmapped = data.get("unmapped_funnels") or []

    blocks: List[Dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text", "text": f"📊 {brand} — Weekly Digest"}},
        {"type": "context", "elements": [
            {"type": "mrkdwn", "text": f"{date_range} · all spend in *{currency}* · {len(products)} product(s)"}
        ]},
        {"type": "divider"},
    ]

    for p in products:
        if p.get("no_ads"):
            continue  # product had no spend this period — omit it from the report
        blocks.append(_product_block(p, currency))

    # Footer: coverage + unmapped worklist.
    blocks.append({"type": "divider"})
    cov_pct = coverage.get("pct")
    cov_txt = f"*Coverage:* {cov_pct:.0f}% of captured spend attributed" if cov_pct is not None else "*Coverage:* n/a"
    if unmapped:
        top = ", ".join(f"{u['url']} (${u['spend']:,.0f})" for u in unmapped[:5])
        cov_txt += f"\n*Unmapped* (${coverage.get('unmapped', 0):,.0f}): {top}\n_Tag in Brand Manager → Offer Variants to attribute._"
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": cov_txt}})

    # Fine print: how to read the CPA columns. All spend-inclusive over the same
    # ~30d window (the baselines job filters meta_ads_performance by brand + date
    # only, no ad_status filter, so paused-but-spent ads are in BrMed too).
    blocks.append({"type": "context", "elements": [
        {"type": "mrkdwn", "text": (
            "_*ROAS* = revenue ÷ spend. *CVR* = purchases ÷ link-clicks. "
            "*CPA* = $/purchase, *ATC* = $/add-to-cart (overview values are blended; "
            "cpaMed/atcMed & cpaP25/atcP25 are this product's per-ad median & "
            "top-quartile target — P25 beats the median). *BrMed* = brand-wide median CPA. "
            "Cost medians over ads that converted; ~30d window, paused-but-spent included._"
        )}
    ]})

    fallback = f"{brand} weekly digest — {len(products)} products, {date_range} ({currency})"
    return fallback, blocks


# ---------------------------------------------------------------------------
# HTML report (uploaded to storage; linked from the Slack message)
# ---------------------------------------------------------------------------

_HTML_STYLE = """
:root{--pink:#FF3D8B;--pink-soft:#FFD9E6;--pink-deep:#D6266B;
 --blue:#1E5BFF;--blue-soft:#D6E0FF;--blue-deep:#0F3BCC;
 --ink:#0E1330;--ink-2:#3A4060;--paper:#FFF7F2;--paper-2:#FFEDE2}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
 font:15px/1.55 Inter,system-ui,-apple-system,sans-serif}
.wrap{max-width:1040px;margin:0 auto;padding:0 18px 64px}
.logo-top{text-align:center;margin:28px 0 14px}
.logo-top img{height:56px;width:auto}
.topbar{background:var(--blue);color:#fff;text-align:center;
 border:2px solid var(--ink);border-radius:18px;padding:22px 24px;margin:0 0 22px;
 box-shadow:6px 6px 0 var(--ink)}
.kicker{font:700 13px/1 'Space Grotesk',sans-serif;letter-spacing:.08em;text-transform:uppercase;opacity:.9}
.topbar h1{font:700 34px/1.08 'Space Grotesk',sans-serif;margin:6px 0 4px;letter-spacing:-.01em}
.topbar .sub{font-size:14px;opacity:.92}
.product{background:#fff;border:2px solid var(--ink);border-radius:16px;padding:18px 20px;
 margin:0 0 18px;box-shadow:5px 5px 0 var(--ink)}
.product h2{font:700 22px/1.15 'Space Grotesk',sans-serif;margin:0 0 3px;letter-spacing:-.01em}
.product .meta{color:var(--ink-2);font-size:13px;margin:0 0 14px}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
th,td{padding:8px 8px;text-align:right;border-bottom:1px solid var(--paper-2);white-space:nowrap}
thead th{font:700 11px/1 'Space Grotesk',sans-serif;text-transform:uppercase;letter-spacing:.06em;
 color:var(--ink-2);border-bottom:2px solid var(--ink)}
thead tr:first-child th{border-bottom:1px solid var(--paper-2)}
td.lvl,th.lvl{text-align:left}
td.lvl{font-weight:700;text-transform:capitalize}
.grp{border-left:1px solid var(--paper-2)}
.tgt{color:var(--pink-deep);font-weight:700}
.roas-low{color:var(--pink-deep);font-weight:700}
.roas-good{color:var(--blue-deep);font-weight:700}
.muted{color:#a7adba}
.fbar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:0 0 16px;font-size:13px}
.flabel{font:700 12px/1 'Space Grotesk',sans-serif;text-transform:uppercase;letter-spacing:.06em;color:var(--ink-2)}
.fbtn{border:2px solid var(--ink);background:#fff;border-radius:999px;padding:5px 14px;
 font:600 12.5px/1 Inter,sans-serif;cursor:pointer;color:var(--ink);box-shadow:2px 2px 0 var(--ink)}
.fbtn.active{background:var(--blue);color:#fff}
.fnote{color:var(--ink-2);font-size:11.5px;opacity:.8}
td.thin{opacity:.55}
@media print{.fbar{display:none}}
.insight{margin:14px 0 0;padding:11px 14px;background:var(--pink-soft);border:2px solid var(--ink);
 border-radius:12px;font-size:13px;font-weight:600}
.dark{color:var(--ink-2);font-style:italic;margin:6px 0 0}
.footer{background:#fff;border:2px solid var(--ink);border-radius:16px;padding:16px 20px;
 box-shadow:5px 5px 0 var(--ink)}
.footer ul{margin:8px 0 0;padding-left:18px;color:var(--ink-2)}
.fineprint{color:var(--ink-2);font-size:12px;margin-top:18px;opacity:.85}
a{color:var(--blue-deep)}
"""


def _h(v: Any) -> str:
    return html.escape(str(v), quote=True)


def _roas_cell(r: Dict[str, Any]) -> str:
    v = r.get("roas")
    if v is None:
        return '<td class="muted">—</td>'
    cls = "roas-low" if v < 1 else ("roas-good" if v >= 2 else "")
    return f'<td class="{cls}">{_roas(v)}</td>'


def _c(v: Optional[float], cls: str = "") -> str:
    """A right-aligned whole-dollar CPA/ATC cell ('—', muted, when None)."""
    klass = ("muted " + cls).strip() if v is None else cls
    inner = "—" if v is None else _cpa0(v)
    attr = f' class="{klass}"' if klass else ""
    return f"<td{attr}>{inner}</td>"


def _vc(variants: Optional[Dict[str, Dict[str, Any]]], stat: str, cls: str = "") -> str:
    """A filterable Med/P25 cell carrying every threshold variant as data attrs.

    Shows the 1+ (all converters) value by default; the report's filter buttons
    swap in the 5+/10+ values client-side without a server round-trip. ``n`` per
    threshold rides along for the tooltip / low-sample dimming.
    """
    if not variants:
        return _c(None, cls)
    attrs = ""
    for t, v in variants.items():
        if not str(t).isdigit():  # attr-name position: digits only, ever
            continue
        val = v.get(stat)
        attrs += (
            f' data-v{t}="{_cpa0(val) if val is not None else ""}"'
            f' data-n{t}="{int(v.get("n") or 0)}"'
        )
    base = variants.get("1") or {}
    val = base.get(stat)
    n = int(base.get("n") or 0)
    klass = " ".join(x for x in (
        "var", cls,
        "muted" if val is None else "",
        "thin" if val is not None and n < 3 else "",  # match the JS dimming rule
    ) if x)
    inner = _cpa0(val) if val is not None else "—"
    return f'<td class="{klass}"{attrs} title="{n} ad{"" if n == 1 else "s"} in sample">{inner}</td>'


def _med_p25_cells(r: Dict[str, Any], variants_key: str, med_key: str, p25_key: str) -> str:
    """Med + P25 cells: filterable when the row carries threshold variants,
    plain legacy cells otherwise (older persisted digest data)."""
    variants = r.get(variants_key)
    if variants:
        return _vc(variants, "med") + _vc(variants, "p25", "tgt")
    return _c(r.get(med_key)) + _c(r.get(p25_key), "tgt")


def _html_product(p: Dict[str, Any], currency: str) -> str:
    name = _h(p.get("name", "Unnamed"))
    if p.get("error"):
        return f'<section class="product"><h2>{name}</h2><p class="dark">Could not analyze this product this run.</p></section>'
    if p.get("no_ads"):
        return f'<section class="product"><h2>{name}</h2><p class="dark">No ads with spend in scope this period.</p></section>'

    spend = p.get("total_spend")
    meta = f"{_money(spend, currency)} · {p.get('spending_ads', 0)} ads with spend"
    mline = _market_line(p.get("markets") or {})
    if mline:
        meta += " · " + _h(mline.replace("*", ""))

    if p.get("awareness_pending"):
        c = p.get("completeness") or {}
        if (c.get("classifiable_spend") or 0) <= 0:
            table = (
                '<p class="dark">Awareness not classifiable this period — all spend is on '
                'images too low-res to read at the current resolution (see below).</p>'
            )
        else:
            pct = (c.get("current_pct") or 0.0) * 100
            table = (
                f'<p class="dark">Awareness mix pending — only {pct:.0f}% of classifiable '
                f'spend is classified at the current version. The distribution appears once '
                f'the backfill completes.</p>'
            )
    else:
        rows = p.get("awareness") or []
        body = ""
        for r in rows:
            lvl = _h(str(r.get("level", "")).replace("_", " "))
            spend_s = f"${r['spend']:,.0f}" if r.get("spend") is not None else "—"
            body += (
                f"<tr><td class='lvl'>{lvl}</td><td>{r.get('ads', 0)}</td><td>{spend_s}</td>"
                f"{_roas_cell(r)}<td>{_pct(r.get('cvr'))}</td>"
                f"{_c(r.get('agg_cpa'), 'grp')}{_med_p25_cells(r, 'cpa_variants', 'prod_med_cpa', 'prod_p25_cpa')}"
                f"{_c(r.get('agg_catc'), 'grp')}{_med_p25_cells(r, 'catc_variants', 'prod_med_catc', 'prod_p25_catc')}"
                f"{_c(r.get('brand_med_cpa'), 'grp muted')}</tr>"
            )
        table = (
            "<table><thead>"
            "<tr><th class='lvl' rowspan='2'>Level</th><th rowspan='2'>Ads</th><th rowspan='2'>Spend</th>"
            "<th rowspan='2'>ROAS</th><th rowspan='2'>CVR</th>"
            "<th class='grp' colspan='3'>CPA ($/purchase)</th><th class='grp' colspan='3'>Cost / add-to-cart</th>"
            "<th class='grp' rowspan='2'>Brand CPA</th></tr>"
            "<tr><th class='grp'>Agg</th><th>Med</th><th>P25</th>"
            "<th class='grp'>Agg</th><th>Med</th><th>P25</th></tr></thead>"
            f"<tbody>{body}</tbody></table>"
        )
    comp = _completeness_html(p, currency)
    insight = f'<div class="insight">💡 {_h(p["insight"])}</div>' if p.get("insight") else ""
    return f'<section class="product"><h2>{name}</h2><p class="meta">{meta}</p>{table}{comp}{insight}</section>'


def _completeness_html(p: Dict[str, Any], currency: str) -> str:
    """HTML completeness footnote + 'cannot classify' line; '' when fully clean."""
    c = p.get("completeness") or {}
    stale = c.get("stale_spend", 0.0) or 0.0
    unclass = c.get("unclassified_spend", 0.0) or 0.0
    low_res = c.get("low_res_spend", 0.0) or 0.0
    if stale <= 0 and unclass <= 0 and low_res <= 0:
        return ""
    pct = (c.get("current_pct") or 0.0) * 100
    bits = [f"Classified: {pct:.0f}% of classifiable spend"]
    if stale > 0:
        bits.append(f"{_money(stale, currency)} stale")
    if unclass > 0:
        bits.append(f"{_money(unclass, currency)} not yet classified")
    out = f'<p class="dark">{" · ".join(_h(b) for b in bits)}</p>'
    if low_res > 0:
        out += f'<p class="dark">Cannot classify (needs high-res re-fetch): {_h(_money(low_res, currency))}</p>'
    return out


def render_brand_digest_html(data: Dict[str, Any]) -> str:
    """Return a standalone, styled HTML document for the brand's weekly digest.

    Same data as ``render_brand_digest`` but with the full metric grid (no Slack
    width limit) and light styling, so the client can open a clean view from the
    'Open full report' link in the Slack message.
    """
    brand = _h(data.get("brand_name", "Brand"))
    currency = _h(data.get("currency", "USD"))
    date_range = _h(data.get("date_range", "Last 30 days"))
    logo_url = data.get("brand_logo_url")
    products = data.get("products") or []
    coverage = data.get("coverage") or {}
    unmapped = data.get("unmapped_funnels") or []

    sections = "".join(
        _html_product(p, data.get("currency", "USD"))
        for p in products if not p.get("no_ads")
    )

    # Filter buttons only when a row that will actually RENDER its table carries
    # threshold variants (pending/error/no-ads products suppress their tables, so
    # they must not summon dead buttons; older stored digests stay static).
    thresholds = sorted({
        int(t)
        for p in products
        if not (p.get("no_ads") or p.get("error") or p.get("awareness_pending"))
        for r in (p.get("awareness") or [])
        for t in list(r.get("cpa_variants") or {}) + list(r.get("catc_variants") or {})
        if str(t).isdigit()
    })
    has_variants = bool(thresholds)
    buttons = "".join(
        f"<button type='button' class='fbtn{' active' if t == 1 else ''}' data-t='{t}' "
        f"aria-pressed='{'true' if t == 1 else 'false'}' onclick='vtFilter({t})'>"
        f"{'All converters' if t == 1 else f'{t}+ purchases'}</button>"
        for t in thresholds
    )
    filter_bar = (
        "<div class='fbar'>"
        "<span class='flabel'>Med / P25 sample:</span>"
        f"{buttons}"
        "<span class='fnote'>ATC columns filter by add-to-carts · Agg stays blended over all spend "
        "· hover a value for sample size</span>"
        "</div>"
    ) if has_variants else ""
    filter_js = (
        "<script>function vtFilter(t){"
        "document.querySelectorAll('td.var').forEach(function(c){"
        "var v=c.getAttribute('data-v'+t)||'',n=c.getAttribute('data-n'+t)||'0';"
        "c.textContent=v||'\\u2014';c.title=n+(n==='1'?' ad':' ads')+' in sample';"
        "c.classList.toggle('muted',!v);c.classList.toggle('thin',!!v&&+n<3);});"
        "document.querySelectorAll('.fbtn').forEach(function(b){"
        "var on=b.getAttribute('data-t')===String(t);"
        "b.classList.toggle('active',on);b.setAttribute('aria-pressed',on?'true':'false');});}"
        "</script>"
    ) if has_variants else ""

    cov_pct = coverage.get("pct")
    cov = f"<b>Coverage:</b> {cov_pct:.0f}% of captured spend attributed" if cov_pct is not None else "<b>Coverage:</b> n/a"
    if unmapped:
        items = "".join(
            f"<li>{_h(u['url'])} — ${u['spend']:,.0f}</li>" for u in unmapped[:8]
        )
        cov += (
            f'<br><b>Unmapped</b> (${coverage.get("unmapped", 0):,.0f}) — tag in '
            f"Brand Manager → Offer Variants:<ul>{items}</ul>"
        )

    fineprint = (
        "ROAS = revenue ÷ spend. CVR = purchases ÷ link-clicks. CPA = $/purchase, "
        "Cost/ATC = $/add-to-cart (Agg blended; Med & P25 are this product's per-ad "
        "median &amp; top-quartile target — the highlighted P25 beats the median). Brand CPA = "
        "brand-wide median benchmark. Cost figures over ads that converted; ~30-day "
        "window, paused-but-spent ads included."
    )
    if has_variants:
        fineprint += (
            " Med/P25 follow the active sample filter (each ad counts once, "
            "regardless of spend); dimmed values rest on fewer than 3 ads."
        )
    # Logo sits centered ABOVE the blue header band (on the paper background).
    logo_html = (
        f"<div class='logo-top'><img class='logo' src='{_h(logo_url)}' alt='{brand} logo'></div>"
        if logo_url else ""
    )
    fonts = (
        "<link rel='preconnect' href='https://fonts.googleapis.com'>"
        "<link rel='preconnect' href='https://fonts.gstatic.com' crossorigin>"
        "<link rel='stylesheet' href='https://fonts.googleapis.com/css2?"
        "family=Inter:wght@400;600;700&family=Space+Grotesk:wght@500;700&display=swap'>"
    )
    return (
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"{fonts}<title>{brand} — Weekly Digest</title><style>{_HTML_STYLE}</style></head>"
        "<body><div class='wrap'>"
        f"{logo_html}"
        "<header class='topbar'>"
        "<div class='kicker'>Weekly Performance Digest</div>"
        f"<h1>{brand}</h1>"
        f"<div class='sub'>{date_range} · all spend in {currency} · {len(products)} product(s)</div>"
        "</header>"
        f"{filter_bar}"
        f"{sections}"
        f"<div class='footer'>{cov}</div>"
        f"<p class='fineprint'>{fineprint}</p>"
        f"</div>{filter_js}</body></html>"
    )
