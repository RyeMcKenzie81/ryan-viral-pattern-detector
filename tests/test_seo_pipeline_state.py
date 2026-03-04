"""
Unit tests for SEOPipelineState dataclass.

Covers:
- Construction with required and optional fields
- to_dict() serialization (UUIDs become strings, enums become values)
- from_dict() deserialization (strings become UUIDs, strings become enums)
- Roundtrip fidelity
- mark_step_complete() tracking
- SEOHumanCheckpoint enum

Run with: pytest tests/test_seo_pipeline_state.py -v
"""

import pytest
from uuid import UUID, uuid4

from viraltracker.services.seo_pipeline.state import (
    SEOPipelineState,
    SEOHumanCheckpoint,
)


# ---------------------------------------------------------------------------
# SEOHumanCheckpoint
# ---------------------------------------------------------------------------


class TestSEOHumanCheckpoint:
    def test_all_values(self):
        expected = {"keyword_selection", "outline_review", "article_review", "qa_approval"}
        actual = {c.value for c in SEOHumanCheckpoint}
        assert actual == expected

    def test_string_construction(self):
        assert SEOHumanCheckpoint("keyword_selection") == SEOHumanCheckpoint.KEYWORD_SELECTION

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            SEOHumanCheckpoint("invalid_checkpoint")


# ---------------------------------------------------------------------------
# SEOPipelineState — construction
# ---------------------------------------------------------------------------


class TestStateConstruction:
    def test_minimal_required_fields(self):
        pid = uuid4()
        bid = uuid4()
        oid = uuid4()
        state = SEOPipelineState(
            project_id=pid,
            brand_id=bid,
            organization_id=oid,
        )
        assert state.project_id == pid
        assert state.brand_id == bid
        assert state.organization_id == oid
        assert state.current_step == "pending"
        assert state.awaiting_human is False
        assert state.error is None
        assert state.steps_completed == []
        assert state.generation_mode == "api"

    def test_string_uuid_accepted(self):
        """UUIDs can be passed as strings (dataclass doesn't enforce types)."""
        state = SEOPipelineState(
            project_id="00000000-0000-0000-0000-000000000001",
            brand_id="00000000-0000-0000-0000-000000000002",
            organization_id="00000000-0000-0000-0000-000000000003",
        )
        assert str(state.project_id) == "00000000-0000-0000-0000-000000000001"

    def test_defaults_for_optional_fields(self):
        state = SEOPipelineState(
            project_id=uuid4(),
            brand_id=uuid4(),
            organization_id=uuid4(),
        )
        assert state.seed_keywords == []
        assert state.min_word_count == 3
        assert state.max_word_count == 10
        assert state.discovered_keywords == []
        assert state.selected_keyword_id is None
        assert state.competitor_urls == []
        assert state.competitor_results == []
        assert state.winning_formula is None
        assert state.author_id is None
        assert state.article_id is None
        assert state.phase_a_output is None
        assert state.phase_b_output is None
        assert state.phase_c_output is None
        assert state.qa_result is None
        assert state.published_url is None
        assert state.current_checkpoint is None
        assert state.human_input is None
        assert state.error_step is None
        assert state.retry_count == 0
        assert state.max_retries == 3

    def test_all_fields_set(self):
        kw_id = uuid4()
        author_id = uuid4()
        article_id = uuid4()
        state = SEOPipelineState(
            project_id=uuid4(),
            brand_id=uuid4(),
            organization_id=uuid4(),
            generation_mode="cli",
            seed_keywords=["minecraft parenting"],
            min_word_count=4,
            max_word_count=8,
            discovered_keywords=[{"keyword": "test", "word_count": 1}],
            selected_keyword_id=kw_id,
            selected_keyword="minecraft parenting tips",
            competitor_urls=["https://example.com"],
            competitor_results=[{"url": "https://example.com", "word_count": 2000}],
            winning_formula={"avg_word_count": 2000},
            author_id=author_id,
            article_id=article_id,
            phase_a_output="Outline here",
            phase_b_output="Article draft",
            phase_c_output="Optimized article",
            qa_result={"passed": True},
            published_url="https://example.com/blog/test",
            cms_article_id="shopify-123",
            current_step="qa_validation",
            current_checkpoint=SEOHumanCheckpoint.QA_APPROVAL,
            awaiting_human=True,
            human_input={"action": "approve"},
            error=None,
            error_step=None,
            retry_count=1,
            max_retries=5,
            steps_completed=["keyword_discovery", "competitor_analysis"],
        )
        assert state.generation_mode == "cli"
        assert state.selected_keyword_id == kw_id
        assert state.current_checkpoint == SEOHumanCheckpoint.QA_APPROVAL
        assert state.awaiting_human is True
        assert len(state.steps_completed) == 2


# ---------------------------------------------------------------------------
# to_dict()
# ---------------------------------------------------------------------------


class TestStateToDict:
    def test_uuids_become_strings(self):
        pid = uuid4()
        bid = uuid4()
        oid = uuid4()
        state = SEOPipelineState(project_id=pid, brand_id=bid, organization_id=oid)
        d = state.to_dict()
        assert isinstance(d["project_id"], str)
        assert isinstance(d["brand_id"], str)
        assert isinstance(d["organization_id"], str)
        assert d["project_id"] == str(pid)

    def test_enum_becomes_value(self):
        state = SEOPipelineState(
            project_id=uuid4(),
            brand_id=uuid4(),
            organization_id=uuid4(),
            current_checkpoint=SEOHumanCheckpoint.KEYWORD_SELECTION,
        )
        d = state.to_dict()
        assert d["current_checkpoint"] == "keyword_selection"

    def test_none_stays_none(self):
        state = SEOPipelineState(
            project_id=uuid4(), brand_id=uuid4(), organization_id=uuid4()
        )
        d = state.to_dict()
        assert d["selected_keyword_id"] is None
        assert d["error"] is None

    def test_lists_preserved(self):
        state = SEOPipelineState(
            project_id=uuid4(),
            brand_id=uuid4(),
            organization_id=uuid4(),
            seed_keywords=["kw1", "kw2"],
            steps_completed=["step1"],
        )
        d = state.to_dict()
        assert d["seed_keywords"] == ["kw1", "kw2"]
        assert d["steps_completed"] == ["step1"]

    def test_dict_is_json_serializable(self):
        """Ensure to_dict() output can be JSON-encoded."""
        import json
        state = SEOPipelineState(
            project_id=uuid4(),
            brand_id=uuid4(),
            organization_id=uuid4(),
            current_checkpoint=SEOHumanCheckpoint.OUTLINE_REVIEW,
            discovered_keywords=[{"keyword": "test"}],
        )
        d = state.to_dict()
        json_str = json.dumps(d)
        assert isinstance(json_str, str)
        parsed = json.loads(json_str)
        assert parsed["current_checkpoint"] == "outline_review"


# ---------------------------------------------------------------------------
# from_dict()
# ---------------------------------------------------------------------------


class TestStateFromDict:
    def test_strings_become_uuids(self):
        pid = "00000000-0000-0000-0000-000000000001"
        bid = "00000000-0000-0000-0000-000000000002"
        oid = "00000000-0000-0000-0000-000000000003"
        state = SEOPipelineState.from_dict({
            "project_id": pid,
            "brand_id": bid,
            "organization_id": oid,
        })
        assert isinstance(state.project_id, UUID)
        assert str(state.project_id) == pid

    def test_string_becomes_enum(self):
        state = SEOPipelineState.from_dict({
            "project_id": str(uuid4()),
            "brand_id": str(uuid4()),
            "organization_id": str(uuid4()),
            "current_checkpoint": "qa_approval",
        })
        assert state.current_checkpoint == SEOHumanCheckpoint.QA_APPROVAL

    def test_none_checkpoint_stays_none(self):
        state = SEOPipelineState.from_dict({
            "project_id": str(uuid4()),
            "brand_id": str(uuid4()),
            "organization_id": str(uuid4()),
            "current_checkpoint": None,
        })
        assert state.current_checkpoint is None

    def test_optional_uuid_fields(self):
        kw_id = str(uuid4())
        state = SEOPipelineState.from_dict({
            "project_id": str(uuid4()),
            "brand_id": str(uuid4()),
            "organization_id": str(uuid4()),
            "selected_keyword_id": kw_id,
            "author_id": None,
            "article_id": str(uuid4()),
        })
        assert isinstance(state.selected_keyword_id, UUID)
        assert state.author_id is None
        assert isinstance(state.article_id, UUID)


# ---------------------------------------------------------------------------
# Roundtrip: to_dict → from_dict
# ---------------------------------------------------------------------------


class TestStateRoundtrip:
    def test_minimal_roundtrip(self):
        original = SEOPipelineState(
            project_id=uuid4(),
            brand_id=uuid4(),
            organization_id=uuid4(),
        )
        d = original.to_dict()
        restored = SEOPipelineState.from_dict(d)
        assert str(restored.project_id) == str(original.project_id)
        assert str(restored.brand_id) == str(original.brand_id)
        assert restored.current_step == original.current_step
        assert restored.seed_keywords == original.seed_keywords

    def test_full_roundtrip(self):
        original = SEOPipelineState(
            project_id=uuid4(),
            brand_id=uuid4(),
            organization_id=uuid4(),
            generation_mode="cli",
            seed_keywords=["kw1", "kw2"],
            discovered_keywords=[{"keyword": "test", "word_count": 1}],
            selected_keyword_id=uuid4(),
            selected_keyword="test keyword",
            competitor_urls=["https://example.com"],
            winning_formula={"avg_word_count": 2000},
            author_id=uuid4(),
            article_id=uuid4(),
            phase_a_output="outline",
            current_step="content_generation",
            current_checkpoint=SEOHumanCheckpoint.ARTICLE_REVIEW,
            awaiting_human=True,
            steps_completed=["keyword_discovery", "competitor_analysis"],
            retry_count=2,
        )
        d = original.to_dict()
        restored = SEOPipelineState.from_dict(d)

        assert str(restored.project_id) == str(original.project_id)
        assert str(restored.selected_keyword_id) == str(original.selected_keyword_id)
        assert str(restored.author_id) == str(original.author_id)
        assert str(restored.article_id) == str(original.article_id)
        assert restored.generation_mode == "cli"
        assert restored.seed_keywords == ["kw1", "kw2"]
        assert restored.discovered_keywords == [{"keyword": "test", "word_count": 1}]
        assert restored.selected_keyword == "test keyword"
        assert restored.winning_formula == {"avg_word_count": 2000}
        assert restored.phase_a_output == "outline"
        assert restored.current_step == "content_generation"
        assert restored.current_checkpoint == SEOHumanCheckpoint.ARTICLE_REVIEW
        assert restored.awaiting_human is True
        assert restored.steps_completed == ["keyword_discovery", "competitor_analysis"]
        assert restored.retry_count == 2


# ---------------------------------------------------------------------------
# mark_step_complete()
# ---------------------------------------------------------------------------


class TestMarkStepComplete:
    def test_adds_step(self):
        state = SEOPipelineState(
            project_id=uuid4(), brand_id=uuid4(), organization_id=uuid4()
        )
        assert state.steps_completed == []
        state.mark_step_complete("keyword_discovery")
        assert state.steps_completed == ["keyword_discovery"]

    def test_no_duplicates(self):
        state = SEOPipelineState(
            project_id=uuid4(), brand_id=uuid4(), organization_id=uuid4()
        )
        state.mark_step_complete("keyword_discovery")
        state.mark_step_complete("keyword_discovery")
        assert state.steps_completed == ["keyword_discovery"]

    def test_multiple_steps(self):
        state = SEOPipelineState(
            project_id=uuid4(), brand_id=uuid4(), organization_id=uuid4()
        )
        state.mark_step_complete("keyword_discovery")
        state.mark_step_complete("competitor_analysis")
        state.mark_step_complete("content_generation")
        assert len(state.steps_completed) == 3
        assert state.steps_completed[0] == "keyword_discovery"
        assert state.steps_completed[2] == "content_generation"
