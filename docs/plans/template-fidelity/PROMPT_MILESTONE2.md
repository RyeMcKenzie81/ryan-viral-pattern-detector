# Milestone 2: Fix Input Quality — Markdown Classifier

## Context

You're continuing work on the landing page analysis multipass pipeline quality roadmap. Read these files first:

1. `docs/plans/template-fidelity/CHECKPOINT_MILESTONE1_EVAL_INFRA.md` — What was done in Milestone 1
2. `docs/plans/template-fidelity/CHECKPOINT_PHASE2_FIX.md` — Earlier content assembly fixes (overflow, smart fallback)

### Current State

**Branch**: `feat/ad-creator-v2-phase0`
**Tests**: 237 passing in `tests/test_multipass_v4.py`
**Uncommitted work**: Milestone 1 eval infrastructure + earlier Phase 2 fixes. Commit all before starting new work.

### Baseline SSIM Scores (from Milestone 1)

| Phase | Boba (simple) | InfiniteAge (complex) |
|-------|--------------|----------------------|
| Phase 1 | 0.5774 | 0.5765 |
| Phase 2 | 0.5869 | 0.5973 |
| Phase 3 | 0.6253 | 0.6068 |
| Phase 4 | 0.6035 | 0.6078 |

Text fidelity: Boba 0.25, InfiniteAge 0.56 (threshold 0.85). This is the primary metric Milestone 2 should improve.

---

## The Problem

Raw FireCrawl markdown contains navigation links, encoding artifacts (Γ, LCP, empty links), and footer text (Terms of Service, © 2024, FDA disclaimers) that get bundled into sec_0 before classification. This causes:

1. **Inflated text fidelity denominator** — source markdown has nav/footer chrome that never appears in output, so fidelity score = (matched text / total source text) is artificially low
2. **sec_0 pollution** — nav chrome pushed into first section confuses layout classification and content assembly
3. **Unfilled placeholders** — template patterns can't match mixed nav + real content

### Evidence from baselines
- Boba: text fidelity 0.25 but "all 86 text chunks matched reference" — the text that IS in the output is correct, the denominator is the problem
- InfiniteAge: text fidelity 0.56, "all 541 text chunks matched reference" — same pattern
- Both have 6-12 unfilled placeholders, correlating with sec_0 being polluted

---

## Implementation Plan

### Approach: Label-Only Mode First (P0 Safety Constraint)

Heuristic pattern matching can accidentally delete real copy. Start with **label-only mode** — lines are classified and labeled but NOT removed from the markdown. This lets us:
1. Measure classification precision/recall on real pages
2. Verify no false positives on persuasive elements
3. Graduate to extraction mode only after precision > 95%

### New File: `viraltracker/services/landing_page_analysis/multipass/markdown_cleaner.py` (~200 lines)

```python
@dataclass
class ClassifiedLine:
    text: str
    label: str          # "body" | "nav" | "footer" | "artifact" | "persuasive"
    confidence: float   # 0.0-1.0
    zone: str           # "pre_heading" | "body" | "post_heading"

@dataclass
class MarkdownCleanResult:
    cleaned_markdown: str                      # In label mode: unchanged. In extract mode: nav/footer removed.
    classified_lines: List[ClassifiedLine]      # Full classification for every line
    nav_content: Optional[str]                 # Extracted nav (None in label mode)
    footer_content: Optional[str]              # Extracted footer (None in label mode)
    stats: Dict[str, int]                      # Counts per label

def classify_markdown(
    markdown: str,
    mode: str = "label",                       # "label" (safe) or "extract"
) -> MarkdownCleanResult:
```

### Zone-Based Architecture

- **Pre-heading zone**: Lines before first `#` heading → classify as artifact/nav/content
- **Body zone**: Between first and last heading → always labeled `body`, **never touched**
- **Post-heading zone**: Lines after last heading → classify as artifact/footer/content

### Content Type Classification

| Content Type | Example | Label |
|-------------|---------|-------|
| Scraping artifacts | "Γ", "LCP", `[ ](http://...)` | `artifact` |
| Navigation chrome | "Skip to content", "Log in", "Cart" | `nav` |
| Footer chrome | "Terms of Service", "© 2024", FDA disclaimers | `footer` |
| Persuasive elements | Countdown timers, "Free shipping", "NEW", "SALE" | `persuasive` |
| Body content | Everything between first and last heading | `body` |

### Safety Rules
- Body zone is sacred — never modified regardless of mode
- Persuasive elements have explicit allowlist and are never classified as nav/footer
- 80% removal cap in extract mode (if > 80% classified as non-body, something is wrong → bail)
- Lines containing sentences (subject + verb + 5+ words) default to `body` unless high-confidence nav/footer pattern

### Pipeline Integration

In `pipeline.py` (around line 1037, before `segment_markdown()`):
```python
clean_result = classify_markdown(page_markdown, mode="label")  # Start safe
self.phase_snapshots["pre_segmentation_cleanup"] = _wrap_json_as_html({
    "mode": "label",
    "stats": clean_result.stats,
    "classified_lines_sample": [...first 20 classified lines...],
})
sections = segment_markdown(clean_result.cleaned_markdown, element_detection)
```

### Verification Strategy (Using Milestone 1 Eval Infrastructure)

1. Run `test_multipass_local.py --url boba --visual` BEFORE any code changes → record baseline
2. Apply markdown cleaner in **label mode** → verify ZERO behavior change (SSIM identical, same diagnostic scores)
3. Review `pre_segmentation_cleanup` snapshot → manually check classification accuracy on both pages
4. If classification precision > 95%: switch to **extract mode**
5. Re-run both pages with `--visual` → compare SSIM and text fidelity vs baseline
6. **Expected improvement** (extract mode): text fidelity improves 0.10-0.25, Phase 2 SSIM improves 0.05-0.15

### Tests: ~20 tests in `TestMarkdownCleaner` class

Test cases:
- Pure nav content classified correctly
- Pure footer content classified correctly
- Scraping artifacts (Γ, empty links) classified as artifact
- Body zone never modified regardless of content
- Persuasive elements ("Free shipping", "SALE") never classified as nav/footer
- Label mode returns unchanged markdown
- Extract mode removes nav/footer, preserves body
- 80% removal cap triggers bail-out
- Sentence heuristic protects real copy
- Mixed page (nav + body + footer) zones detected correctly
- Empty markdown handled gracefully
- Markdown with no headings handled (everything = pre_heading zone)

### Key Files to Read Before Starting
| File | Why |
|------|-----|
| `viraltracker/services/landing_page_analysis/multipass/pipeline.py:1020-1050` | Where `segment_markdown()` is called — insertion point |
| `viraltracker/services/landing_page_analysis/multipass/segmenter.py` | How markdown is split into sections |
| `scripts/test_multipass_local.py` | Run test with `--visual` flag |
| `test_multipass_snapshots/run_20260223_204328_19fc8c/phase_2_content.html` | Boba Phase 2 output to inspect |
| `test_multipass_snapshots/run_20260223_204744_e3d233/phase_2_content.html` | InfiniteAge Phase 2 output |

### What Success Looks Like
- Text fidelity on Boba: 0.25 → 0.45+ (label mode should be same, extract mode improves)
- Text fidelity on InfiniteAge: 0.56 → 0.70+
- Zero false positives on persuasive content
- `pre_segmentation_cleanup` snapshot shows accurate classification
- SSIM trajectory still improving
- All existing 237 tests still pass + 20 new tests for markdown_cleaner
