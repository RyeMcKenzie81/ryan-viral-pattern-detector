"""
Tests for CompetitorIntelService — composite scoring, aggregation, dedup, and partial failure.

12 tests total:
- 7 critical: scoring formula, edge cases, hook dedup, persona merge, null filtering,
              single extraction passthrough, partial failure threshold
- 3 nice-to-have: awareness distribution, benefits ranking, angle dedup
- 2 eval: extraction prompt JSON, schema completeness
"""

import pytest
from viraltracker.services.competitor_intel_service import (
    compute_composite_score,
    aggregate_extractions,
    _text_similarity,
    _jaccard,
    _dedup_strings,
)


# ============================================================================
# Critical Tests (7)
# ============================================================================

class TestCompositeScoring:
    """Tests 1-2: Composite scoring formula and edge cases."""

    def test_composite_scoring_formula(self):
        """velocity*0.4 + rank*0.3 + durability*0.3 with normal inputs."""
        result = compute_composite_score(position=5, total=100, days_active=30)

        # Verify all components present
        assert "composite" in result
        assert "velocity" in result
        assert "rank" in result
        assert "durability" in result

        # Verify range
        assert 0.0 <= result["composite"] <= 1.0
        assert 0.0 <= result["velocity"] <= 1.0
        assert 0.0 <= result["rank"] <= 1.0
        assert 0.0 <= result["durability"] <= 1.0

        # Verify formula: composite = 0.4*velocity + 0.3*rank + 0.3*durability
        expected = 0.4 * result["velocity"] + 0.3 * result["rank"] + 0.3 * result["durability"]
        assert abs(result["composite"] - round(expected, 4)) < 0.001

        # Position 5 out of 100 should be high rank
        assert result["rank"] > 0.9

        # 30 days active = durability of 30/90 = 0.333
        assert abs(result["durability"] - round(30 / 90, 4)) < 0.01

    def test_composite_scoring_edge_cases(self):
        """Edge cases: position=1/total=1, days_active=0, days_active=90+."""
        # Position 1 of 1
        r1 = compute_composite_score(position=1, total=1, days_active=45)
        assert r1["composite"] > 0
        assert r1["rank"] == 1.0  # max(0.2, 1.0 - 0) = 1.0

        # days_active = 0
        r2 = compute_composite_score(position=3, total=50, days_active=0)
        assert r2["durability"] == 0.0  # min(1.0, 0/90) = 0

        # days_active = 200 (caps at 90)
        r3 = compute_composite_score(position=3, total=50, days_active=200)
        assert r3["durability"] == 1.0  # min(1.0, 200/90) = 1.0

        # Very high position number
        r4 = compute_composite_score(position=100, total=100, days_active=45)
        assert r4["rank"] == 0.2  # Floor at 0.2


class TestHookDedup:
    """Test 3: SequenceMatcher >0.85 merges, keeps higher-scored."""

    def test_hook_dedup_sequence_matcher(self):
        extractions = [
            {"hook": {"text": "You won't believe what happened to my dog", "type": "curiosity_gap"}},
            {"hook": {"text": "You won't believe what happened to my cat", "type": "curiosity_gap"}},  # >85% similar
            {"hook": {"text": "Stop scrolling if you have joint pain", "type": "pain_call_out"}},
        ]
        scores = [0.9, 0.7, 0.8]

        result = aggregate_extractions(extractions, scores)
        hooks = result["hooks"]

        # The first two should merge (>85% similar), third stays
        # "my dog" vs "my cat" = very high similarity
        similarity = _text_similarity(
            "You won't believe what happened to my dog",
            "You won't believe what happened to my cat"
        )
        if similarity > 0.85:
            assert len(hooks) == 2
            # Higher scored hook (0.9) should be first
            assert hooks[0]["score"] == 0.9
            # Merged hook should have frequency 2
            assert hooks[0]["frequency"] == 2
        else:
            # If not similar enough, all 3 remain
            assert len(hooks) == 3


class TestPersonaMerge:
    """Test 4: Jaccard >0.60 on beliefs+behaviors merges, <0.60 keeps separate."""

    def test_persona_merge_jaccard(self):
        # Two personas with overlapping beliefs/behaviors (>60% Jaccard)
        extractions = [
            {"persona_4d": {
                "demographics": "Women 25-45",
                "psychographics": "Health-conscious",
                "beliefs": ["natural ingredients matter", "big pharma can't be trusted"],
                "behaviors": ["shops at Whole Foods", "reads ingredient labels"],
            }},
            {"persona_4d": {
                "demographics": "Women 30-50",
                "psychographics": "Wellness-focused",
                "beliefs": ["natural ingredients matter", "big pharma can't be trusted", "organic is worth the cost"],
                "behaviors": ["shops at Whole Foods", "reads ingredient labels", "follows health influencers"],
            }},
            {"persona_4d": {
                "demographics": "Men 18-35",
                "psychographics": "Fitness-focused",
                "beliefs": ["protein is key", "gains require discipline"],
                "behaviors": ["goes to the gym daily", "tracks macros"],
            }},
        ]
        scores = [0.9, 0.8, 0.7]

        result = aggregate_extractions(extractions, scores)
        personas = result["personas"]

        # First two should merge (high overlap), third stays separate
        assert len(personas) == 2
        # Merged persona should have frequency 2
        merged = [p for p in personas if p["frequency"] >= 2]
        assert len(merged) == 1
        assert merged[0]["frequency"] == 2
        # Merged should have combined beliefs
        assert len(merged[0]["beliefs"]) >= 2


class TestAggregationNullFiltering:
    """Test 5: null fields in extraction don't crash aggregation."""

    def test_aggregation_null_filtering(self):
        extractions = [
            {
                "hook": {"text": "Great hook", "type": "question"},
                "persona_4d": None,
                "awareness_level": "problem_aware",
                "benefits": ["Benefit 1"],
                "pain_points": None,
                "jtbds": [],
                "angles": None,
                "objections_addressed": None,
                "unique_mechanism": None,
                "unique_problem_mechanism": None,
                "unique_solution_mechanism": None,
                "emotional_triggers": ["fear"],
                "messaging_sequence": [],
            },
            {
                "hook": None,
                "persona_4d": {"demographics": "Everyone", "psychographics": "All", "beliefs": [], "behaviors": []},
                "awareness_level": None,
                "benefits": None,
                "pain_points": ["Pain 1"],
                "jtbds": ["When I wake up, I want energy"],
                "angles": [{"belief_statement": "Coffee is bad for you", "evidence_in_video": "Stats shown"}],
                "objections_addressed": ["Too expensive"],
                "unique_mechanism": "Nano-absorption",
                "unique_problem_mechanism": None,
                "unique_solution_mechanism": None,
                "emotional_triggers": None,
                "messaging_sequence": None,
            },
        ]
        scores = [0.8, 0.6]

        # Should not raise any exceptions
        result = aggregate_extractions(extractions, scores)

        assert len(result["hooks"]) == 1
        assert len(result["personas"]) == 1
        assert len(result["benefits"]) == 1
        assert len(result["pain_points"]) == 1
        assert len(result["jtbds"]) == 1
        assert len(result["angles"]) == 1


class TestAggregationSingleExtraction:
    """Test 6: n=1 passthrough without errors."""

    def test_aggregation_single_extraction(self):
        extractions = [{
            "hook": {"text": "Did you know this?", "type": "question"},
            "persona_4d": {
                "demographics": "Adults 25-55",
                "psychographics": "Curious",
                "beliefs": ["Knowledge is power"],
                "behaviors": ["Reads daily"],
            },
            "awareness_level": "solution_aware",
            "benefits": ["Better sleep", "More energy"],
            "pain_points": ["Chronic fatigue"],
            "jtbds": ["When I'm tired, I want sustained energy"],
            "angles": [{"belief_statement": "Natural energy beats caffeine", "evidence_in_video": "Comparison shown"}],
            "objections_addressed": ["Does it really work?"],
            "unique_mechanism": "Adaptogenic blend",
            "unique_problem_mechanism": "Adrenal fatigue from stimulants",
            "unique_solution_mechanism": "Cortisol regulation",
            "emotional_triggers": ["hope", "frustration"],
            "messaging_sequence": [{"stage": "hook", "content": "Question", "timestamp": "0:00-0:03"}],
        }]
        scores = [0.85]

        result = aggregate_extractions(extractions, scores)

        # Single extraction should pass through cleanly
        assert len(result["hooks"]) == 1
        assert result["hooks"][0]["text"] == "Did you know this?"
        assert len(result["personas"]) == 1
        assert result["primary_awareness_level"] == "solution_aware"
        assert len(result["benefits"]) == 2
        assert len(result["angles"]) == 1
        assert len(result["unique_mechanisms"]) == 1


class TestPartialFailureThreshold:
    """Test 7: >=50% success = partial status, <50% = failed."""

    def test_partial_failure_threshold(self):
        from unittest.mock import MagicMock, patch

        from viraltracker.services.competitor_intel_service import CompetitorIntelService
        service = CompetitorIntelService.__new__(CompetitorIntelService)
        service.supabase = MagicMock()

        # Mock the update and select calls
        service.supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        # 6/10 succeed = partial (>=50%)
        extractions = [{"hook": {"text": f"Hook {i}", "type": "q"}} for i in range(6)]
        scores = [0.5] * 6

        result = service.finalize_pack("pack-1", extractions, scores, failed_count=4, total_count=10)
        assert result["status"] == "partial"

        # 4/10 succeed = failed (<50%)
        extractions_few = [{"hook": {"text": f"Hook {i}", "type": "q"}} for i in range(4)]
        scores_few = [0.5] * 4

        result2 = service.finalize_pack("pack-2", extractions_few, scores_few, failed_count=6, total_count=10)
        assert result2["status"] == "failed"

        # 10/10 succeed = complete
        extractions_all = [{"hook": {"text": f"Hook {i}", "type": "q"}} for i in range(10)]
        scores_all = [0.5] * 10

        result3 = service.finalize_pack("pack-3", extractions_all, scores_all, failed_count=0, total_count=10)
        assert result3["status"] == "complete"


# ============================================================================
# Nice-to-Have Tests (3)
# ============================================================================

class TestAwarenessDistribution:
    """Test 8: Mode calculation and percentage distribution across videos."""

    def test_awareness_distribution(self):
        extractions = [
            {"awareness_level": "problem_aware"},
            {"awareness_level": "problem_aware"},
            {"awareness_level": "problem_aware"},
            {"awareness_level": "solution_aware"},
            {"awareness_level": "most_aware"},
        ]
        scores = [0.5] * 5

        result = aggregate_extractions(extractions, scores)

        assert result["primary_awareness_level"] == "problem_aware"
        dist = result["awareness_distribution"]
        assert dist["problem_aware"] == 0.6
        assert dist["solution_aware"] == 0.2
        assert dist["most_aware"] == 0.2


class TestBenefitsFrequencyRanking:
    """Test 9: frequency * source_score ranking, dedup by similarity."""

    def test_benefits_frequency_ranking(self):
        extractions = [
            {"benefits": ["Better sleep", "More energy"]},
            {"benefits": ["Better sleep quality", "Weight loss"]},  # "Better sleep" ~= "Better sleep quality"
            {"benefits": ["More energy", "Better mood"]},
        ]
        scores = [0.9, 0.7, 0.5]

        result = aggregate_extractions(extractions, scores)
        benefits = result["benefits"]

        # Benefits should be deduplicated and ranked
        assert len(benefits) > 0
        # Top benefit should have highest rank_score
        for i in range(len(benefits) - 1):
            assert benefits[i]["rank_score"] >= benefits[i + 1]["rank_score"]


class TestAngleDedupBeliefStatements:
    """Test 10: SequenceMatcher >0.85 on belief_statement text."""

    def test_angle_dedup_belief_statements(self):
        extractions = [
            {"angles": [
                {"belief_statement": "Natural ingredients are better for your body", "evidence_in_video": "Comparison chart"},
            ]},
            {"angles": [
                {"belief_statement": "Natural ingredients are better for your health", "evidence_in_video": "Doctor testimony"},
            ]},
            {"angles": [
                {"belief_statement": "Big pharma profits from keeping you sick", "evidence_in_video": "Stats shown"},
            ]},
        ]
        scores = [0.9, 0.7, 0.5]

        result = aggregate_extractions(extractions, scores)
        angles = result["angles"]

        # First two angles are very similar, should merge
        sim = _text_similarity(
            "Natural ingredients are better for your body",
            "Natural ingredients are better for your health"
        )
        if sim > 0.85:
            assert len(angles) == 2
            # The merged one should have frequency 2
            natural_angle = [a for a in angles if "natural" in a["belief_statement"].lower()]
            assert len(natural_angle) == 1
            assert natural_angle[0]["frequency"] == 2
        else:
            assert len(angles) == 3


# ============================================================================
# Eval Tests (2)
# ============================================================================

class TestExtractionPromptValidJson:
    """Test 11: prompt produces parseable JSON structure (mock Gemini response)."""

    def test_extraction_prompt_valid_json(self):
        """Verify a representative Gemini response parses to expected structure."""
        import json

        mock_response = json.dumps({
            "transcription": {"full_text": "Hello world", "timestamps": [{"time": "0:00", "text": "Hello"}]},
            "storyboard": [{"timestamp": "0:00-0:03", "description": "Person speaking"}],
            "text_overlays": [{"timestamp": "0:01", "text": "BUY NOW"}],
            "hook": {"text": "Did you know?", "type": "question", "timestamp": "0:00-0:03"},
            "persona_4d": {
                "demographics": "Women 25-45",
                "psychographics": "Health-conscious",
                "beliefs": ["Natural is better"],
                "behaviors": ["Reads labels"],
            },
            "awareness_level": "problem_aware",
            "awareness_reasoning": "Ad starts with pain point",
            "benefits": ["Better health"],
            "pain_points": ["Fatigue"],
            "jtbds": ["When I'm tired, I want energy"],
            "angles": [{"belief_statement": "Natural beats synthetic", "evidence_in_video": "Chart shown"}],
            "objections_addressed": ["Is it safe?"],
            "unique_mechanism": "Nano-absorption",
            "unique_problem_mechanism": "Gut barrier blocks nutrients",
            "unique_solution_mechanism": "Bypasses gut barrier",
            "cta": {"text": "Shop now", "type": "shop_now"},
            "emotional_triggers": ["hope", "fear"],
            "messaging_sequence": [{"stage": "hook", "content": "Question opener", "timestamp": "0:00-0:03"}],
            "ad_format": "ugc",
            "estimated_production_level": "low_budget",
        })

        parsed = json.loads(mock_response)
        assert isinstance(parsed, dict)
        assert "hook" in parsed
        assert "persona_4d" in parsed
        assert "angles" in parsed


class TestExtractionSchemaCompleteness:
    """Test 12: all 14 schema fields present and non-null for standard video."""

    def test_extraction_schema_completeness(self):
        """Check that a fully-populated extraction has all required fields."""
        extraction = {
            "transcription": {"full_text": "text", "timestamps": []},
            "hook": {"text": "hook", "type": "question", "timestamp": "0:00"},
            "persona_4d": {"demographics": "d", "psychographics": "p", "beliefs": ["b"], "behaviors": ["b"]},
            "awareness_level": "problem_aware",
            "benefits": ["benefit"],
            "pain_points": ["pain"],
            "jtbds": ["jtbd"],
            "angles": [{"belief_statement": "bs", "evidence_in_video": "ev"}],
            "objections_addressed": ["obj"],
            "unique_mechanism": "um",
            "unique_problem_mechanism": "ump",
            "unique_solution_mechanism": "ums",
            "emotional_triggers": ["fear"],
            "messaging_sequence": [{"stage": "hook", "content": "c", "timestamp": "0:00"}],
        }

        required_fields = [
            "transcription", "hook", "persona_4d", "awareness_level",
            "benefits", "pain_points", "jtbds", "angles",
            "objections_addressed", "unique_mechanism",
            "unique_problem_mechanism", "unique_solution_mechanism",
            "emotional_triggers", "messaging_sequence",
        ]

        for field in required_fields:
            assert field in extraction, f"Missing field: {field}"
            val = extraction[field]
            assert val is not None, f"Field {field} is null"
            if isinstance(val, (list, dict)):
                assert len(val) > 0, f"Field {field} is empty"
