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
    chunks.append(_awareness_table(p.get("awareness") or []))
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
.topbar{display:flex;align-items:center;gap:18px;background:var(--blue);color:#fff;
 border:2px solid var(--ink);border-radius:18px;padding:22px 24px;margin:24px 0 22px;
 box-shadow:6px 6px 0 rgba(14,19,48,.14)}
.topbar .logo{height:44px;width:auto;flex:0 0 auto}
.kicker{font:700 12px/1 'Space Grotesk',sans-serif;letter-spacing:.14em;text-transform:uppercase;opacity:.85}
.topbar h1{font:700 30px/1.1 'Space Grotesk',sans-serif;margin:6px 0 4px}
.topbar .sub{font-size:13px;opacity:.92}
.product{background:#fff;border:2px solid var(--ink);border-radius:16px;padding:18px 20px;
 margin:0 0 18px;box-shadow:5px 5px 0 rgba(14,19,48,.12)}
.product h2{font:700 19px/1.2 'Space Grotesk',sans-serif;margin:0 0 2px}
.product .meta{color:var(--ink-2);font-size:13px;margin:0 0 14px}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
th,td{padding:8px 8px;text-align:right;border-bottom:1px solid var(--paper-2);white-space:nowrap}
thead th{font:700 11px/1 'Space Grotesk',sans-serif;text-transform:uppercase;letter-spacing:.04em;
 color:var(--ink-2);border-bottom:2px solid var(--ink)}
thead tr:first-child th{border-bottom:1px solid var(--paper-2)}
td.lvl,th.lvl{text-align:left}
td.lvl{font-weight:700;text-transform:capitalize}
.grp{border-left:1px solid var(--paper-2)}
.tgt{color:var(--pink-deep);font-weight:700}
.roas-low{color:var(--pink-deep);font-weight:700}
.roas-good{color:var(--blue-deep);font-weight:700}
.muted{color:#a7adba}
.insight{margin:14px 0 0;padding:11px 14px;background:var(--pink-soft);border:2px solid var(--ink);
 border-radius:12px;font-size:13px;font-weight:600}
.dark{color:var(--ink-2);font-style:italic;margin:6px 0 0}
.footer{background:#fff;border:2px solid var(--ink);border-radius:16px;padding:16px 20px;
 box-shadow:5px 5px 0 rgba(14,19,48,.12)}
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

    rows = p.get("awareness") or []
    body = ""
    for r in rows:
        lvl = _h(str(r.get("level", "")).replace("_", " "))
        spend_s = f"${r['spend']:,.0f}" if r.get("spend") is not None else "—"
        body += (
            f"<tr><td class='lvl'>{lvl}</td><td>{r.get('ads', 0)}</td><td>{spend_s}</td>"
            f"{_roas_cell(r)}<td>{_pct(r.get('cvr'))}</td>"
            f"{_c(r.get('agg_cpa'), 'grp')}{_c(r.get('prod_med_cpa'))}{_c(r.get('prod_p25_cpa'), 'tgt')}"
            f"{_c(r.get('agg_catc'), 'grp')}{_c(r.get('prod_med_catc'))}{_c(r.get('prod_p25_catc'), 'tgt')}"
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
    insight = f'<div class="insight">💡 {_h(p["insight"])}</div>' if p.get("insight") else ""
    return f'<section class="product"><h2>{name}</h2><p class="meta">{meta}</p>{table}{insight}</section>'


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

    sections = "".join(_html_product(p, data.get("currency", "USD")) for p in products)

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
    logo_html = f"<img class='logo' src='{_h(logo_url)}' alt='{brand} logo'>" if logo_url else ""
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
        f"<header class='topbar'>{logo_html}<div>"
        "<div class='kicker'>Weekly Performance Digest</div>"
        f"<h1>{brand}</h1>"
        f"<div class='sub'>{date_range} · all spend in {currency} · {len(products)} product(s)</div>"
        "</div></header>"
        f"{sections}"
        f"<div class='footer'>{cov}</div>"
        f"<p class='fineprint'>{fineprint}</p>"
        "</div></body></html>"
    )
