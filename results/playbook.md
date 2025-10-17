# Dog Niche Hook Playbook (Data-Driven)

## TL;DR
- **Relatable ≥ 0.6 & Humor ≥ 0.4** → Δmedian = 0.711 (n_true=71, n_false=226)
- **Payoff ≤ 1.0s** → Δmedian = 0.247 (n_true=57, n_false=240)

## Univariate Signals (Spearman vs normalized views)
                   feature   n       rho            p
 hook_prob_shock_violation 292  0.286319 6.484452e-07
       hook_prob_humor_gag 282  0.255386 1.413083e-05
    hook_prob_tension_wait 282  0.063670 2.866314e-01
    hook_prob_result_first 271  0.038762 5.251689e-01
               face_pct_1s 297  0.024129 6.787682e-01
                cuts_in_2s 297  0.002964 9.594286e-01
           payoff_time_sec 266 -0.084565 1.690752e-01
 hook_prob_relatable_slice 287 -0.119587 4.293374e-02
hook_prob_reveal_transform 273 -0.140877 1.987951e-02
  overlay_chars_per_sec_2s 294 -0.199624 5.753695e-04

## Pairwise Ranking (within account & week)

## Interactions
       interaction   n      rho        p
shock_x_earlyproof 261 0.169281 0.006116
 relatable_x_humor 281 0.150297 0.011651