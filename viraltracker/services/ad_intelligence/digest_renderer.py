"""DigestRenderer — render the weekly per-product digest as Slack Block Kit.

Pure formatting: takes the assembled digest data (from WeeklyDigestService) and
returns ``(fallback_text, blocks)`` for SlackService.send_message. Awareness
breakdowns are rendered in a code block (monospace) because Slack does not render
markdown tables. All money is labeled in the account currency (e.g. CAD).
"""
from __future__ import annotations

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
