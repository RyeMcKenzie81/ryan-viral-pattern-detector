from dataclasses import dataclass

@dataclass
class AnalysisConfig:
    # normalization hyperparam
    time_decay_beta: float = 0.20    # y = log(views+1) - log(followers+1) - beta*log(hours+1)

    # feature columns expected in the CSV (after mapping)
    hook_prob_cols = [
        "hook_prob_result_first",
        "hook_prob_shock_violation",
        "hook_prob_reveal_transform",
        "hook_prob_relatable_slice",
        "hook_prob_humor_gag",
        "hook_prob_tension_wait",
    ]
    cont_hook_cols = [
        "payoff_time_sec",
        "face_pct_1s",               # 0..1 or 0..100? (we'll auto-scale if >1)
        "cuts_in_2s",
        "overlay_chars_per_sec_2s",
    ]

    # interaction tests we'll compute
    interactions = {
        "shock_x_earlyproof": ("hook_prob_shock_violation", "payoff_time_sec", "<=1.0"),
        "relatable_x_humor": ("hook_prob_relatable_slice", "hook_prob_humor_gag", None),
    }

    # bucket rules for playbook (name -> boolean expression string using df columns)
    bucket_rules = {
        "Result-first ≥ 0.6": "hook_prob_result_first >= 0.6",
        "Payoff ≤ 1.0s": "payoff_time_sec <= 1.0",
        "Relatable ≥ 0.6 & Humor ≥ 0.4": "(hook_prob_relatable_slice >= 0.6) & (hook_prob_humor_gag >= 0.4)",
        "Shock ≥ 0.6 WITH early proof": "(hook_prob_shock_violation >= 0.6) & (payoff_time_sec <= 1.0)",
        "Overlay ≤ 80 chars/s": "overlay_chars_per_sec_2s <= 80",
    }

    # final feature list for pairwise ranking
    pairwise_features = hook_prob_cols + cont_hook_cols
