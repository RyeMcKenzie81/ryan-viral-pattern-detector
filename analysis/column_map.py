# Map your scraped CSV column names -> analysis column names used in scripts.
# If your CSV already uses these names, you can leave as-is.

COLUMN_MAP = {
    # identifiers & meta
    "post_id": "post_id",
    "account_id": "account_id",
    "posted_at": "posted_at",           # ISO8601 or yyyy-mm-dd HH:MM:SS
    "followers": "followers",
    "views": "views",
    "hours_since_post": "hours_since_post",

    # hook motif probabilities (0..1)
    "hook_prob_result_first": "hook_prob_result_first",
    "hook_prob_shock_violation": "hook_prob_shock_violation",
    "hook_prob_reveal_transform": "hook_prob_reveal_transform",
    "hook_prob_relatable_slice": "hook_prob_relatable_slice",
    "hook_prob_humor_gag": "hook_prob_humor_gag",
    "hook_prob_tension_wait": "hook_prob_tension_wait",

    # continuous hook features
    "payoff_time_sec": "payoff_time_sec",
    "face_pct_1s": "face_pct_1s",                     # if your data is 0..100, script will auto-scale to 0..1
    "cuts_in_2s": "cuts_in_2s",
    "overlay_chars_per_sec_2s": "overlay_chars_per_sec_2s",
}
