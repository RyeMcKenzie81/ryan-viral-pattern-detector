"""Single source of truth for SEO length thresholds (B7).

Before this, four places disagreed: the QA check (ideal 50-60 / 150-160), the
pre-publish checklist (accept 30-70 / 70-200), the auto-fix AI prompt (target
50-60 / 150-160), and the auto-fix output validation (accept 30-70 / 120-200).
An article could warn in one layer and pass in another, and auto-fix would burn
an AI rewrite to satisfy QA's stricter range even when the looser range was
"fine". Every layer now resolves from here.

Semantics per field:
- ideal_min..ideal_max: the optimal range. QA/checklist PASS here; auto-fix
  TARGETS this; below ideal_min is a (non-blocking) warning.
- hard_max: above this is an ERROR that blocks publish — the title truncates in
  the SERP / the meta description gets cut.

Brand-configurable: a brand_content_policies row may carry a `seo_thresholds`
JSONB with any subset of these keys to override the defaults for that brand.
"""

from typing import Any, Dict, Optional

DEFAULT_SEO_THRESHOLDS: Dict[str, int] = {
    "title_ideal_min": 50,
    "title_ideal_max": 60,
    "title_hard_max": 70,
    "meta_ideal_min": 150,
    "meta_ideal_max": 160,
    "meta_hard_max": 200,
}


def resolve_seo_thresholds(policy: Optional[Dict[str, Any]] = None) -> Dict[str, int]:
    """Merge a brand policy's optional `seo_thresholds` override over the
    defaults. Unknown keys and non-numeric values are ignored, so a malformed
    override can never break evaluation — it just falls back to the default."""
    thresholds = dict(DEFAULT_SEO_THRESHOLDS)
    override = (policy or {}).get("seo_thresholds")
    if isinstance(override, dict):
        for key, value in override.items():
            if key in thresholds and isinstance(value, (int, float)) and not isinstance(value, bool):
                thresholds[key] = int(value)
    return thresholds
