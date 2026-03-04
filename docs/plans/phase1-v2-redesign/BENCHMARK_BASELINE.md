# Phase 1 v2 Benchmark Baseline

> Captured: 2026-02-23
> Commit: feat/ad-creator-v2-phase0 branch (pre-commit)
> Runner: `scripts/test_multipass_local.py --visual`

## Test Pages

| Page | URL | Analysis ID |
|------|-----|-------------|
| InfiniteAge | http://infiniteage.com/pages/sea-moss-for-hair-growth | f18289a5 |
| Boba | https://bobanutrition.co/pages/7reabreakfast | 175a1017 |

---

## InfiniteAge — Template vs v2

| Metric | Template | v2 | Delta |
|--------|----------|-----|-------|
| Phase 1 Skeleton SSIM | 0.5851 | **0.7152** | +0.1301 |
| Final Output SSIM | **0.7596** | 0.5903 | -0.1693 |
| Skeleton size (chars) | 5,342 | 9,380 | +4,038 |
| CSS size (chars) | 3,311 | 7,380 | +4,069 |
| Placeholder count | 14/8 | 14/8 | same |
| Section count | 8 | 8 | same |
| Slots (Phase 2) | 1,267 | 841 | -426 |
| Text fidelity | 0.46 | 0.60 | +0.14 |
| API calls | 4 | 5 | +1 |
| Total latency | 200.7s | 187.7s | -13.0s |
| SSIM trajectory | improving | regressing | — |
| Phase 1 verdict | PASS | PASS | — |
| v2 fallback level | — | 0 | first try |

### Template SSIM by phase
- Phase 1 skeleton: 0.5851
- Phase 2 content: 0.7562 (+0.1711)
- Phase 3 refined: 0.7591 (+0.0028)
- Phase 4 final: 0.7596 (+0.0006)

### v2 SSIM by phase
- Phase 1 skeleton: 0.7152
- Phase 2 content: 0.5933 (-0.1219)
- Phase 3 refined: 0.5929 (-0.0004)
- Phase 4 final: 0.5903 (-0.0026)

### v2 sub-step timings
- 1A visual audit (Gemini): 30.2s
- 1B layout fusion (deterministic): 0.01s
- 1C skeleton codegen (Claude): 23.8s

---

## Boba — v2 only (no template baseline captured)

| Metric | v2 |
|--------|-----|
| Phase 1 Skeleton SSIM | 0.6133 |
| Final Output SSIM | 0.4787 |
| Skeleton size (chars) | 40,123 |
| Placeholder count | 16/8 |
| Section count | 8 |
| Slots (Phase 2) | 259 |
| Text fidelity | 0.83 |
| API calls | 5 |
| Total latency | 289.2s |
| SSIM trajectory | regressing |
| v2 fallback level | 0 |

### v2 SSIM by phase
- Phase 1 skeleton: 0.6133
- Phase 2 content: 0.5239 (-0.0893)
- Phase 3 refined: 0.4787 (-0.0453)
- Phase 4 final: 0.4787 (+0.0000)

### v2 sub-step timings
- 1A visual audit (Gemini): 26.2s
- 1B layout fusion (deterministic): 0.01s
- 1C skeleton codegen (Claude): 21.5s

---

## Key Findings

1. **Phase 1 skeleton quality improved** — v2 SSIM is +0.13 higher than template
2. **Final output regressed** — v2 final SSIM is -0.17 lower because Phases 2-4 are tuned for template skeletons
3. **Claude codegen is reliable** — fallback_level=0 on both pages (passed validation first try)
4. **Gemini visual audit works** — correctly classified hero_split, logo_bar, feature_grid, testimonial_cards, pricing_table, content_block
5. **Phase 1 latency increased** — ~54s total (1A: 26-30s, 1C: 21-24s) vs plan estimate of 13-15s. The Gemini vision call takes 26-30s, not the estimated 5s.
6. **SSIM regresses through phases** — v2 needs Phase 2 content assembly adapted to Claude's skeleton structure

## Regression Thresholds

When making future changes, these scores should NOT regress:

| Metric | Minimum Acceptable |
|--------|-------------------|
| v2 Phase 1 Skeleton SSIM (InfiniteAge) | >= 0.68 (allow -0.03) |
| v2 Phase 1 Skeleton SSIM (Boba) | >= 0.58 (allow -0.03) |
| v2 Fallback level | <= 1 (retry OK, template fallback = problem) |
| Template Final SSIM (InfiniteAge) | >= 0.72 (no regression on existing path) |
| Unit tests | 304 pass, 0 fail |
