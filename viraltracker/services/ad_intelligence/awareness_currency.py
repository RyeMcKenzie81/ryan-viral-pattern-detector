"""Shared awareness-currency rule.

ONE definition of "is this ad's awareness current?" used by BOTH the classifier
staleness gate (classify-once) AND the weekly digest completeness gate, so the two can
never drift. If the rule that decides "current" and the rule that reports "this much
spend is current" diverged, the digest would silently stop matching how we classify --
the exact failure this module exists to prevent.

States:
  current      - latest classification links a CURRENT-version deep analysis (image OR video)
  low_res      - image too small to classify (has a current-version low_res marker in
                 ad_image_analysis); shown on the digest's "cannot classify" line and
                 EXCLUDED from the completeness gate denominator
  stale        - has an awareness value but NOT from a current deep analysis (old light /
                 unlinked / old-version link); upgrades on the next classify run
  unclassified - no classification row, or a row with no usable awareness

Note: low_res state is keyed on the ad_image_analysis MARKER (read separately), never on a
classification row -- the marker-only design keeps skip state out of
ad_creative_classifications so latest-classification consumers (baselines, congruence,
winner_dna, get_latest_classification) are never poisoned.
"""

CURRENT = "current"
STALE = "stale"
LOW_RES = "low_res"
UNCLASSIFIED = "unclassified"


def image_link_is_current(row, current_image_ids) -> bool:
    """True if this classification row links a CURRENT-version deep image analysis.

    ``current_image_ids`` is any container whose membership test means "this
    image_analysis_id is at the current image-analysis prompt version" -- a set of ids,
    or the prefetch's {id: prompt_version} dict (membership tests its keys). Both work
    because the prefetch only ever loads current-version ids.
    """
    ia = row.get("image_analysis_id")
    return bool(ia) and str(ia) in current_image_ids


def video_link_is_current(row, current_video_ids) -> bool:
    """True if this classification row links a CURRENT-version deep video analysis."""
    va = row.get("video_analysis_id")
    return bool(va) and str(va) in current_video_ids


def awareness_state(meta_ad_id, row, current_image_ids, current_video_ids, low_res_ids) -> str:
    """Classify one ad's awareness state.

    Args:
        meta_ad_id: the ad id (needed for the low_res check even when row is None).
        row: the GENUINE latest ad_creative_classifications row (dict) for the ad, or
            None. Must be the literally-latest row, NOT the latest-with-awareness -- an
            older stale row must never win over a newer (e.g. NULL-awareness) row.
        current_image_ids / current_video_ids: current-version analysis-id containers.
        low_res_ids: set of meta_ad_ids that have a current-version low_res marker.

    Returns: one of CURRENT / LOW_RES / STALE / UNCLASSIFIED.
    """
    # CURRENT requires BOTH a current-version deep link AND a usable awareness label.
    # (A current link with a NULL label is not usable -> falls through to unclassified.)
    if row is not None and row.get("creative_awareness_level"):
        cf = str(row.get("creative_format") or "")
        if cf.startswith("video"):
            if video_link_is_current(row, current_video_ids):
                return CURRENT
        elif image_link_is_current(row, current_image_ids):
            return CURRENT
    if meta_ad_id in low_res_ids:
        return LOW_RES
    if row is not None and row.get("creative_awareness_level"):
        return STALE
    return UNCLASSIFIED
