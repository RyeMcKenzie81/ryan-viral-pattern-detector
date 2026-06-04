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


def _awareness_table(rows: List[Dict[str, Any]]) -> str:
    """Monospace table of awareness levels (rendered in a Slack code block)."""
    if not rows:
        return "_no classified ads in scope_"
    header = f"{'Level':<16}{'Ads':>4}  {'Spend':>9}  {'AggCPA':>8}  {'MedCPA':>8}"
    lines = [header]
    for r in rows:
        level = str(r.get("level", "")).replace("_", " ")[:15]
        ads = r.get("ads", 0)
        spend = r.get("spend")
        spend_s = f"${spend:,.0f}" if spend is not None else "-"
        lines.append(
            f"{level:<16}{ads:>4}  {spend_s:>9}  {_cpa(r.get('agg_cpa')):>8}  {_cpa(r.get('med_cpa')):>8}"
        )
    return "```\n" + "\n".join(lines) + "\n```"


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

    # Fine print: how to read the two CPA columns. Both are spend-inclusive over
    # the same ~30d window — the daily baselines job filters meta_ads_performance
    # by brand + date only (no ad_status filter), so paused-but-spent ads are
    # already in the median. AggCPA is THIS product's blended cost for the level;
    # MedCPA is the BRAND-WIDE median for the level. Product-actual vs brand
    # benchmark, by design — not a cohort mismatch.
    blocks.append({"type": "context", "elements": [
        {"type": "mrkdwn", "text": (
            "_AggCPA = this product's spend ÷ purchases for the level. "
            "MedCPA = brand-wide median for the level over the same ~30d window "
            "(both include paused-but-spent ads). AggCPA above MedCPA = this "
            "product runs costlier than the brand norm at that level._"
        )}
    ]})

    fallback = f"{brand} weekly digest — {len(products)} products, {date_range} ({currency})"
    return fallback, blocks
