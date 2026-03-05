"""
Unit tests for SEO pipeline models (enums and Pydantic models).

Covers:
- Enum membership and string values
- Pydantic model defaults and validation
- Model serialization/deserialization

Run with: pytest tests/test_seo_pipeline_models.py -v
"""

import pytest
from uuid import uuid4

from viraltracker.services.seo_pipeline.models import (
    KeywordStatus,
    ArticleStatus,
    ArticlePhase,
    ProjectStatus,
    SearchIntent,
    LinkType,
    LinkStatus,
    LinkPriority,
    LinkPlacement,
    SEOKeyword,
    SEOAuthor,
    CompetitorMetrics,
    WinningFormula,
    QACheck,
    QAResult,
    LinkSuggestion,
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TestKeywordStatus:
    def test_all_values(self):
        expected = {"discovered", "analyzed", "selected", "in_progress", "published", "rejected"}
        actual = {s.value for s in KeywordStatus}
        assert actual == expected

    def test_string_coercion(self):
        assert KeywordStatus("discovered") == KeywordStatus.DISCOVERED
        assert str(KeywordStatus.DISCOVERED) == "KeywordStatus.DISCOVERED"
        assert KeywordStatus.DISCOVERED.value == "discovered"

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            KeywordStatus("nonexistent")


class TestArticleStatus:
    def test_all_values(self):
        expected = {
            "draft", "outline_complete", "draft_complete", "optimized",
            "qa_pending", "qa_passed", "qa_failed",
            "publishing", "published", "archived", "discovered",
        }
        actual = {s.value for s in ArticleStatus}
        assert actual == expected

    def test_lifecycle_order(self):
        """Verify the typical lifecycle statuses exist."""
        lifecycle = [
            ArticleStatus.DRAFT,
            ArticleStatus.OUTLINE_COMPLETE,
            ArticleStatus.DRAFT_COMPLETE,
            ArticleStatus.OPTIMIZED,
            ArticleStatus.QA_PENDING,
            ArticleStatus.QA_PASSED,
            ArticleStatus.PUBLISHED,
        ]
        assert len(lifecycle) == 7


class TestProjectStatus:
    def test_all_values(self):
        expected = {"active", "paused", "completed", "archived"}
        actual = {s.value for s in ProjectStatus}
        assert actual == expected


class TestArticlePhase:
    def test_values(self):
        assert ArticlePhase.PHASE_A.value == "a"
        assert ArticlePhase.PHASE_B.value == "b"
        assert ArticlePhase.PHASE_C.value == "c"
        assert len(ArticlePhase) == 3


class TestSearchIntent:
    def test_values(self):
        expected = {"informational", "navigational", "commercial", "transactional"}
        actual = {i.value for i in SearchIntent}
        assert actual == expected


class TestLinkEnums:
    def test_link_type_values(self):
        expected = {"suggested", "auto", "bidirectional", "manual"}
        assert {t.value for t in LinkType} == expected

    def test_link_status_values(self):
        expected = {"pending", "implemented", "rejected"}
        assert {s.value for s in LinkStatus} == expected

    def test_link_priority_values(self):
        expected = {"high", "medium", "low"}
        assert {p.value for p in LinkPriority} == expected

    def test_link_placement_values(self):
        expected = {"middle", "end"}
        assert {p.value for p in LinkPlacement} == expected


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------


class TestSEOKeyword:
    def test_defaults(self):
        kw = SEOKeyword(keyword="test keyword", word_count=2, seed_keyword="test")
        assert kw.status == KeywordStatus.DISCOVERED
        assert kw.search_volume is None
        assert kw.keyword_difficulty is None
        assert kw.search_intent is None
        assert kw.cluster_id is None
        assert kw.found_in_seeds == 1

    def test_full_construction(self):
        uid = uuid4()
        kw = SEOKeyword(
            keyword="minecraft parenting tips",
            word_count=3,
            seed_keyword="minecraft parenting",
            search_volume=500,
            keyword_difficulty=35.2,
            search_intent=SearchIntent.INFORMATIONAL,
            status=KeywordStatus.ANALYZED,
            cluster_id=uid,
            found_in_seeds=3,
        )
        assert kw.word_count == 3
        assert kw.search_volume == 500
        assert kw.cluster_id == uid


class TestSEOAuthor:
    def test_minimal(self):
        author = SEOAuthor(
            brand_id=uuid4(),
            organization_id=uuid4(),
            name="Kevin Hinton",
        )
        assert author.name == "Kevin Hinton"
        assert author.bio is None
        assert author.is_default is False
        assert author.persona_id is None

    def test_full(self):
        brand_id = uuid4()
        org_id = uuid4()
        persona_id = uuid4()
        author = SEOAuthor(
            id=uuid4(),
            brand_id=brand_id,
            organization_id=org_id,
            name="Kevin Hinton",
            bio="Dad and co-founder",
            image_url="https://example.com/kevin.jpg",
            job_title="Co-Founder",
            author_url="https://example.com/about",
            persona_id=persona_id,
            schema_data={"@type": "Person", "name": "Kevin Hinton"},
            is_default=True,
        )
        assert author.is_default is True
        assert author.persona_id == persona_id
        assert author.schema_data["@type"] == "Person"


class TestCompetitorMetrics:
    def test_defaults(self):
        cm = CompetitorMetrics(url="https://example.com")
        assert cm.word_count == 0
        assert cm.h2_count == 0
        assert cm.has_faq is False
        assert cm.has_schema is False
        assert cm.schema_types == []
        assert cm.raw_analysis is None

    def test_with_data(self):
        cm = CompetitorMetrics(
            url="https://example.com/article",
            position=3,
            title="Test Article",
            word_count=2500,
            h2_count=8,
            flesch_reading_ease=65.0,
            has_faq=True,
            has_schema=True,
            schema_types=["Article", "FAQPage"],
        )
        assert cm.position == 3
        assert cm.flesch_reading_ease == 65.0
        assert "Article" in cm.schema_types


class TestWinningFormula:
    def test_defaults(self):
        wf = WinningFormula()
        assert wf.avg_word_count == 0
        assert wf.target_flesch == 65.0
        assert wf.opportunities == []

    def test_target_word_count(self):
        wf = WinningFormula(avg_word_count=2000, target_word_count=2240)
        assert wf.target_word_count == 2240


class TestQAResult:
    def test_passed(self):
        check = QACheck(name="em_dash_check", passed=True, message="No em dashes")
        result = QAResult(
            article_id=uuid4(),
            passed=True,
            total_checks=1,
            passed_checks=1,
            checks=[check],
        )
        assert result.passed is True
        assert result.failures == []

    def test_failed(self):
        failure = QACheck(
            name="em_dash_check",
            passed=False,
            severity="error",
            message="Found 3 em dashes",
        )
        result = QAResult(
            article_id=uuid4(),
            passed=False,
            total_checks=1,
            passed_checks=0,
            checks=[failure],
            failures=[failure],
        )
        assert result.passed is False
        assert len(result.failures) == 1


class TestLinkSuggestion:
    def test_defaults(self):
        ls = LinkSuggestion(
            source_article_id=uuid4(),
            target_article_id=uuid4(),
            anchor_text="minecraft parenting tips",
            similarity_score=0.35,
        )
        assert ls.link_type == LinkType.SUGGESTED
        assert ls.status == LinkStatus.PENDING
        assert ls.placement == LinkPlacement.END
        assert ls.priority == LinkPriority.MEDIUM
        assert ls.anchor_variations == []

    def test_high_priority(self):
        ls = LinkSuggestion(
            source_article_id=uuid4(),
            target_article_id=uuid4(),
            anchor_text="test",
            similarity_score=0.55,
            priority=LinkPriority.HIGH,
            placement=LinkPlacement.MIDDLE,
            anchor_variations=["test link", "learn about test"],
        )
        assert ls.priority == LinkPriority.HIGH
        assert len(ls.anchor_variations) == 2


class TestModelSerialization:
    def test_keyword_dict_roundtrip(self):
        kw = SEOKeyword(keyword="test", word_count=1, seed_keyword="t")
        d = kw.model_dump()
        kw2 = SEOKeyword(**d)
        assert kw == kw2

    def test_competitor_metrics_json_roundtrip(self):
        cm = CompetitorMetrics(
            url="https://example.com",
            word_count=1500,
            has_faq=True,
            schema_types=["Article"],
        )
        json_str = cm.model_dump_json()
        cm2 = CompetitorMetrics.model_validate_json(json_str)
        assert cm2.word_count == 1500
        assert cm2.has_faq is True
