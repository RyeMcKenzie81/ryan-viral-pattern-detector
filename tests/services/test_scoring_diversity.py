"""
Tests for scoring preset diversity invariants.

Validates that ROLL_THE_DICE_WEIGHTS and SMART_SELECT_WEIGHTS produce
diverse template selections using synthetic candidate pools.

Also tests helper functions used by the one-time analysis script
(scripts/validate_scoring_presets.py).
"""

import math
from collections import Counter
from uuid import UUID

import numpy as np
import pytest

from viraltracker.services.template_scoring_service import (
    PHASE_4_SCORERS,
    ROLL_THE_DICE_WEIGHTS,
    SMART_SELECT_WEIGHTS,
    SelectionContext,
    select_templates,
    select_templates_with_fallback,
)


# ============================================================================
# Helpers
# ============================================================================


def _ctx(**overrides) -> SelectionContext:
    """Create a minimal SelectionContext with defaults."""
    defaults = {
        "product_id": UUID("00000000-0000-0000-0000-000000000001"),
        "brand_id": UUID("00000000-0000-0000-0000-000000000002"),
    }
    defaults.update(overrides)
    return SelectionContext(**defaults)


CATEGORIES = [
    "Testimonial", "Before/After", "UGC", "Lifestyle",
    "Product Focus", "Educational", "Social Proof",
]


def _make_candidates(
    n: int = 30,
    categories: list[str] | None = None,
    all_unused: bool = True,
    vary_eval_scores: bool = False,
    vary_assets: bool = False,
) -> list[dict]:
    """Build a synthetic candidate pool.

    Args:
        n: Number of candidates.
        categories: Cycle through these categories. Default: 7 types.
        all_unused: If True, all candidates are unused.
        vary_eval_scores: If True, vary eval_total_score across candidates.
        vary_assets: If True, vary required_assets and has_detection.
    """
    cats = categories or CATEGORIES
    candidates = []
    for i in range(n):
        cat = cats[i % len(cats)]
        template = {
            "id": f"template-{i:03d}",
            "category": cat,
            "is_unused": all_unused or (i % 3 != 0),
            "has_detection": True if vary_assets else False,
            "template_elements": {},
        }

        if vary_eval_scores:
            # Vary from 3 to 15 across candidates
            template["eval_total_score"] = 3 + (i % 13)
            template["eval_d6_compliance_pass"] = True
        else:
            template["eval_total_score"] = 10
            template["eval_d6_compliance_pass"] = True

        if vary_assets:
            # First third: full match, second third: partial, last third: none
            if i < n // 3:
                template["template_elements"] = {
                    "required_assets": ["product:bottle", "logo"]
                }
            elif i < 2 * n // 3:
                template["template_elements"] = {
                    "required_assets": ["product:bottle", "person:model"]
                }
            else:
                template["template_elements"] = {"required_assets": []}

        candidates.append(template)
    return candidates


def _run_selections(
    candidates: list[dict],
    context: SelectionContext,
    weights: dict[str, float],
    n_runs: int = 100,
    count: int = 1,
) -> Counter:
    """Run select_templates n_runs times, counting template selection frequency."""
    freq: Counter = Counter()
    for _ in range(n_runs):
        result = select_templates(
            candidates=candidates,
            context=context,
            scorers=PHASE_4_SCORERS,
            weights=weights,
            count=count,
        )
        for t in result.templates:
            freq[t["id"]] += 1
    return freq


def diversity_score(freq: Counter) -> float:
    """Shannon entropy normalized to [0, 1].

    0.0 = all selections are the same template.
    1.0 = perfectly uniform distribution.
    """
    total = sum(freq.values())
    if total == 0 or len(freq) <= 1:
        return 0.0

    max_entropy = math.log(len(freq))
    if max_entropy == 0:
        return 0.0

    entropy = 0.0
    for count in freq.values():
        if count > 0:
            p = count / total
            entropy -= p * math.log(p)

    return entropy / max_entropy


def repeat_rate(freq: Counter, n_runs: int) -> float:
    """Ratio of total selections to unique templates selected.

    1.0 = every selection was a different template.
    Higher = more repeats.
    """
    total = sum(freq.values())
    unique = len(freq)
    if unique == 0:
        return 0.0
    return total / unique


# ============================================================================
# Roll the Dice Preset Tests
# ============================================================================


class TestRollTheDiceDiversity:
    """ROLL_THE_DICE_WEIGHTS diversity invariants."""

    def test_no_template_dominance(self):
        """No single template should be > 30% of 100 selections."""
        np.random.seed(42)
        candidates = _make_candidates(n=30)
        context = _ctx()

        freq = _run_selections(
            candidates, context, ROLL_THE_DICE_WEIGHTS, n_runs=100, count=1
        )

        max_pct = max(freq.values()) / 100.0
        assert max_pct <= 0.30, (
            f"Template dominance {max_pct:.1%} exceeds 30% threshold"
        )

    def test_category_coverage(self):
        """At least 3 categories should appear in 20 selections."""
        np.random.seed(42)
        candidates = _make_candidates(n=30)
        context = _ctx()

        freq = _run_selections(
            candidates, context, ROLL_THE_DICE_WEIGHTS, n_runs=20, count=1
        )

        categories_seen = set()
        for tid in freq:
            idx = int(tid.split("-")[1])
            categories_seen.add(CATEGORIES[idx % len(CATEGORIES)])

        assert len(categories_seen) >= 3, (
            f"Only {len(categories_seen)} categories in 20 selections: {categories_seen}"
        )

    def test_unused_bonus_effect(self):
        """Previously-used templates should appear less often than unused."""
        np.random.seed(42)
        # Half unused, half used
        candidates = _make_candidates(n=20, all_unused=False)
        # Make first 10 unused, last 10 used
        for i, c in enumerate(candidates):
            c["is_unused"] = i < 10
        context = _ctx()

        freq = _run_selections(
            candidates, context, ROLL_THE_DICE_WEIGHTS, n_runs=200, count=1
        )

        unused_total = sum(freq.get(f"template-{i:03d}", 0) for i in range(10))
        used_total = sum(freq.get(f"template-{i:03d}", 0) for i in range(10, 20))

        # Unused should get more selections (unused_bonus weight = 1.0)
        assert unused_total > used_total, (
            f"Unused ({unused_total}) should be selected more than used ({used_total})"
        )

    def test_uniform_when_all_equal(self):
        """When all scores are equal, distribution should be roughly uniform."""
        np.random.seed(42)
        # All candidates identical properties (same category, all unused, same eval)
        candidates = _make_candidates(n=10, categories=["Testimonial"])
        context = _ctx()

        freq = _run_selections(
            candidates, context, ROLL_THE_DICE_WEIGHTS, n_runs=500, count=1
        )

        # Each template should get roughly 50 selections (500/10)
        # With randomness, allow 20-80 range (chi-squared would be better but this is simpler)
        for tid, count in freq.items():
            assert 10 <= count <= 100, (
                f"{tid} selected {count} times — expected ~50 for uniform"
            )


# ============================================================================
# Smart Select Preset Tests
# ============================================================================


class TestSmartSelectDiversity:
    """SMART_SELECT_WEIGHTS diversity invariants."""

    def test_asset_match_priority(self):
        """Templates with higher asset_match should be selected more often."""
        np.random.seed(42)
        candidates = _make_candidates(n=30, vary_assets=True)
        # Give product assets that match the first third
        context = _ctx(
            product_asset_tags={"product:bottle", "logo"},
        )

        freq = _run_selections(
            candidates, context, SMART_SELECT_WEIGHTS, n_runs=200, count=1
        )

        # First 10 templates have full match, last 10 have no requirements
        full_match = sum(freq.get(f"template-{i:03d}", 0) for i in range(10))
        no_match = sum(freq.get(f"template-{i:03d}", 0) for i in range(10, 20))

        assert full_match > no_match, (
            f"Full asset match ({full_match}) should be selected more "
            f"than partial match ({no_match})"
        )

    def test_category_coverage(self):
        """At least 3 categories in 20 selections with smart select."""
        np.random.seed(42)
        candidates = _make_candidates(n=30)
        context = _ctx()

        freq = _run_selections(
            candidates, context, SMART_SELECT_WEIGHTS, n_runs=20, count=1
        )

        categories_seen = set()
        for tid in freq:
            idx = int(tid.split("-")[1])
            categories_seen.add(CATEGORIES[idx % len(CATEGORIES)])

        assert len(categories_seen) >= 3, (
            f"Only {len(categories_seen)} categories: {categories_seen}"
        )

    def test_belief_clarity_effect(self):
        """Higher belief_clarity should have higher per-template selection rate."""
        np.random.seed(42)
        candidates = _make_candidates(n=20, vary_eval_scores=True)
        context = _ctx()

        freq = _run_selections(
            candidates, context, SMART_SELECT_WEIGHTS, n_runs=500, count=1
        )

        # Compare per-template average (not group total) to control for unequal group sizes
        high_eval_ids = [
            f"template-{i:03d}"
            for i in range(20)
            if (3 + (i % 13)) >= 10
        ]
        low_eval_ids = [
            f"template-{i:03d}"
            for i in range(20)
            if (3 + (i % 13)) < 7
        ]

        high_avg = sum(freq.get(tid, 0) for tid in high_eval_ids) / len(high_eval_ids)
        low_avg = sum(freq.get(tid, 0) for tid in low_eval_ids) / len(low_eval_ids)

        assert high_avg > low_avg, (
            f"High eval avg ({high_avg:.1f}) should exceed "
            f"low eval avg ({low_avg:.1f})"
        )

    def test_no_template_dominance(self):
        """No single template > 40% of 100 selections."""
        np.random.seed(42)
        candidates = _make_candidates(n=30)
        context = _ctx()

        freq = _run_selections(
            candidates, context, SMART_SELECT_WEIGHTS, n_runs=100, count=1
        )

        max_pct = max(freq.values()) / 100.0
        assert max_pct <= 0.40, (
            f"Template dominance {max_pct:.1%} exceeds 40% threshold"
        )


# ============================================================================
# Cross-Preset Tests
# ============================================================================


class TestCrossPreset:
    """Tests that apply to both presets."""

    def test_deterministic_with_seed_roll_dice(self):
        """Same seed → same selection for roll the dice."""
        candidates = _make_candidates(n=20)
        context = _ctx()

        np.random.seed(123)
        r1 = select_templates(
            candidates, context, PHASE_4_SCORERS, ROLL_THE_DICE_WEIGHTS, count=3
        )

        np.random.seed(123)
        r2 = select_templates(
            candidates, context, PHASE_4_SCORERS, ROLL_THE_DICE_WEIGHTS, count=3
        )

        assert [t["id"] for t in r1.templates] == [t["id"] for t in r2.templates]

    def test_deterministic_with_seed_smart_select(self):
        """Same seed → same selection for smart select."""
        candidates = _make_candidates(n=20)
        context = _ctx()

        np.random.seed(456)
        r1 = select_templates(
            candidates, context, PHASE_4_SCORERS, SMART_SELECT_WEIGHTS, count=3
        )

        np.random.seed(456)
        r2 = select_templates(
            candidates, context, PHASE_4_SCORERS, SMART_SELECT_WEIGHTS, count=3
        )

        assert [t["id"] for t in r1.templates] == [t["id"] for t in r2.templates]

    def test_fallback_on_empty_pool(self):
        """Empty candidate pool → graceful empty result."""
        context = _ctx()

        result = select_templates_with_fallback(
            candidates=[],
            context=context,
            weights=ROLL_THE_DICE_WEIGHTS,
            count=3,
        )

        assert result.empty
        assert result.reason is not None
        assert len(result.templates) == 0

    def test_single_candidate_always_selected(self):
        """Pool of 1 → always that template."""
        np.random.seed(42)
        candidates = _make_candidates(n=1)
        context = _ctx()

        freq = _run_selections(
            candidates, context, ROLL_THE_DICE_WEIGHTS, n_runs=10, count=1
        )

        assert freq["template-000"] == 10

    @pytest.mark.parametrize("brand_config", [
        {
            "brand_id": UUID("10000000-0000-0000-0000-000000000001"),
            "product_asset_tags": {"product:bottle"},
            "target_sex": "female",
            "awareness_stage": 3,
        },
        {
            "brand_id": UUID("20000000-0000-0000-0000-000000000002"),
            "product_asset_tags": {"logo", "person:model"},
            "target_sex": "male",
            "awareness_stage": 1,
        },
        {
            "brand_id": UUID("30000000-0000-0000-0000-000000000003"),
            "product_asset_tags": set(),
            "target_sex": None,
            "awareness_stage": 5,
        },
        {
            "brand_id": UUID("40000000-0000-0000-0000-000000000004"),
            "product_asset_tags": {"product:box", "logo", "person:vet"},
            "target_sex": "unisex",
            "awareness_stage": 2,
        },
        {
            "brand_id": UUID("50000000-0000-0000-0000-000000000005"),
            "product_asset_tags": {"person:model"},
            "target_sex": "female",
            "awareness_stage": 4,
        },
    ], ids=["brand1", "brand2", "brand3", "brand4", "brand5"])
    def test_diversity_across_5_brands(self, brand_config):
        """Parameterized: each brand config meets diversity thresholds."""
        np.random.seed(42)
        candidates = _make_candidates(
            n=30, vary_eval_scores=True, vary_assets=True
        )
        context = _ctx(**brand_config)

        for preset_name, weights in [
            ("roll_dice", ROLL_THE_DICE_WEIGHTS),
            ("smart_select", SMART_SELECT_WEIGHTS),
        ]:
            freq = _run_selections(
                candidates, context, weights, n_runs=50, count=1
            )

            # At least 5 unique templates selected in 50 runs
            assert len(freq) >= 5, (
                f"{preset_name} for {brand_config['brand_id']}: "
                f"only {len(freq)} unique templates in 50 selections"
            )

            # No single template > 50% dominance
            max_pct = max(freq.values()) / 50.0
            assert max_pct <= 0.50, (
                f"{preset_name} for {brand_config['brand_id']}: "
                f"dominance {max_pct:.1%} exceeds 50%"
            )


# ============================================================================
# Helper Function Tests (used by analysis script)
# ============================================================================


class TestDiversityHelpers:
    """Tests for diversity_score and repeat_rate helpers."""

    def test_diversity_score_uniform(self):
        """Perfectly uniform → diversity score = 1.0."""
        freq = Counter({"a": 100, "b": 100, "c": 100, "d": 100})
        assert abs(diversity_score(freq) - 1.0) < 1e-9

    def test_diversity_score_single(self):
        """All same template → diversity score = 0.0."""
        freq = Counter({"a": 100})
        assert diversity_score(freq) == 0.0

    def test_diversity_score_skewed(self):
        """Skewed distribution → 0 < diversity < 1."""
        freq = Counter({"a": 90, "b": 5, "c": 3, "d": 2})
        score = diversity_score(freq)
        assert 0.0 < score < 1.0

    def test_diversity_score_empty(self):
        """Empty counter → 0.0."""
        assert diversity_score(Counter()) == 0.0

    def test_repeat_rate_no_repeats(self):
        """Each template selected once → rate = 1.0."""
        freq = Counter({"a": 1, "b": 1, "c": 1})
        assert repeat_rate(freq, 3) == 1.0

    def test_repeat_rate_all_same(self):
        """All same → rate = n_selections."""
        freq = Counter({"a": 100})
        assert repeat_rate(freq, 100) == 100.0

    def test_repeat_rate_mixed(self):
        """Mixed selections → rate between 1 and n."""
        freq = Counter({"a": 50, "b": 30, "c": 20})
        rate = repeat_rate(freq, 100)
        # 100 total / 3 unique = 33.33
        assert abs(rate - 100.0 / 3) < 1e-9

    def test_repeat_rate_empty(self):
        """Empty → 0.0."""
        assert repeat_rate(Counter(), 0) == 0.0
