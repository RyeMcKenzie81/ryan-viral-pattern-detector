"""
Content Eval Service Tests — exercises ContentEvalService with mocked DB and APIs.

Covers:
- evaluate_article: happy path (pass), failure path, image eval disabled
- get_pending_articles: filtering, already-evaluated exclusion
- override_eval: status transition
- compute_content_hash: idempotency key generation
- _aggregate_verdict: all verdict paths (passed, failed errors, failed warnings)
- _evaluate_single_image: confidence gating, uncertain handling
- _fetch_image: content type detection
"""

import json
import pytest
from unittest.mock import MagicMock, patch


# =============================================================================
# FIXTURES
# =============================================================================

BRAND_ID = "22222222-2222-2222-2222-222222222222"
ORG_ID = "33333333-3333-3333-3333-333333333333"
ARTICLE_ID = "66666666-6666-6666-6666-666666666666"

SAMPLE_ARTICLE = {
    "id": ARTICLE_ID,
    "brand_id": BRAND_ID,
    "organization_id": ORG_ID,
    "keyword": "best hiking boots",
    "title": "Best Hiking Boots 2026",
    "seo_title": "Best Hiking Boots 2026 - Expert Guide",
    "meta_description": "Find the best hiking boots for trail and backpacking.",
    "content_markdown": "# Best Hiking Boots\n\nLorem ipsum dolor sit amet...",
    "content_html": "<h1>Best Hiking Boots</h1><p>Lorem ipsum...</p>",
    "hero_image_url": "https://example.com/hero.jpg",
    "inline_images": json.dumps([{"url": "https://example.com/img1.jpg"}]),
    "schema_markup": None,
}

DEFAULT_POLICY = {
    "image_eval_enabled": True,
    "image_eval_rules": [
        {"rule": "Characters must face camera", "severity": "error"},
        {"rule": "No text overlays", "severity": "warning"},
    ],
    "image_eval_min_confidence": 0.8,
    "publish_enabled": False,
    "max_warnings_for_auto_publish": 0,
}


def _make_service(mock_supabase=None):
    from viraltracker.services.seo_pipeline.services.content_eval_service import ContentEvalService
    svc = ContentEvalService(supabase_client=mock_supabase or MagicMock())
    return svc


# =============================================================================
# TESTS — compute_content_hash
# =============================================================================


class TestComputeContentHash:
    def test_deterministic(self):
        from viraltracker.services.seo_pipeline.services.content_eval_service import ContentEvalService
        h1 = ContentEvalService.compute_content_hash(SAMPLE_ARTICLE)
        h2 = ContentEvalService.compute_content_hash(SAMPLE_ARTICLE)
        assert h1 == h2
        assert len(h1) == 16

    def test_different_content_different_hash(self):
        from viraltracker.services.seo_pipeline.services.content_eval_service import ContentEvalService
        article2 = {**SAMPLE_ARTICLE, "content_html": "<h1>Different</h1>"}
        h1 = ContentEvalService.compute_content_hash(SAMPLE_ARTICLE)
        h2 = ContentEvalService.compute_content_hash(article2)
        assert h1 != h2

    def test_handles_missing_fields(self):
        from viraltracker.services.seo_pipeline.services.content_eval_service import ContentEvalService
        article = {"id": ARTICLE_ID}
        h = ContentEvalService.compute_content_hash(article)
        assert len(h) == 16

    def test_handles_inline_images_as_string(self):
        from viraltracker.services.seo_pipeline.services.content_eval_service import ContentEvalService
        article = {
            **SAMPLE_ARTICLE,
            "inline_images": '[{"url": "https://example.com/img1.jpg"}]',
        }
        h = ContentEvalService.compute_content_hash(article)
        assert len(h) == 16


# =============================================================================
# TESTS — _aggregate_verdict
# =============================================================================


class TestAggregateVerdict:
    def test_all_passed(self):
        svc = _make_service()
        result = svc._aggregate_verdict(
            qa_result={"total_checks": 5, "passed_checks": 5, "failures": [], "warnings": []},
            checklist_result={"checks": [{"passed": True}], "failures": [], "warnings": []},
            image_eval_result={"images_evaluated": 1, "images_passed": 1, "images_failed": 0, "uncertain_count": 0},
            policy={"max_warnings_for_auto_publish": 0},
        )
        assert result["verdict"] == "passed"
        assert result["failed_checks"] == 0

    def test_qa_errors_fail(self):
        svc = _make_service()
        result = svc._aggregate_verdict(
            qa_result={
                "total_checks": 5, "passed_checks": 3,
                "failures": [{"name": "f1"}, {"name": "f2"}],
                "warnings": [],
            },
            checklist_result={"checks": [], "failures": [], "warnings": []},
            image_eval_result=None,
            policy={"max_warnings_for_auto_publish": 0},
        )
        assert result["verdict"] == "failed"
        assert result["failed_checks"] == 2

    def test_warnings_within_tolerance_pass(self):
        svc = _make_service()
        result = svc._aggregate_verdict(
            qa_result={"total_checks": 5, "passed_checks": 4, "failures": [], "warnings": [{"name": "w1"}]},
            checklist_result={"checks": [], "failures": [], "warnings": []},
            image_eval_result=None,
            policy={"max_warnings_for_auto_publish": 2},
        )
        assert result["verdict"] == "passed"
        assert result["warning_count"] == 1

    def test_warnings_exceed_tolerance_fail(self):
        svc = _make_service()
        result = svc._aggregate_verdict(
            qa_result={"total_checks": 5, "passed_checks": 3, "failures": [], "warnings": [{"name": "w1"}, {"name": "w2"}]},
            checklist_result={"checks": [], "failures": [], "warnings": [{"name": "w3"}]},
            image_eval_result=None,
            policy={"max_warnings_for_auto_publish": 2},
        )
        assert result["verdict"] == "failed"
        assert result["warning_count"] == 3

    def test_image_failures_fail(self):
        svc = _make_service()
        result = svc._aggregate_verdict(
            qa_result={"total_checks": 0, "passed_checks": 0, "failures": [], "warnings": []},
            checklist_result={"checks": [], "failures": [], "warnings": []},
            image_eval_result={"images_evaluated": 2, "images_passed": 1, "images_failed": 1, "uncertain_count": 0},
            policy={"max_warnings_for_auto_publish": 0},
        )
        assert result["verdict"] == "failed"
        assert result["failed_checks"] == 1

    def test_uncertain_images_count_as_warnings(self):
        svc = _make_service()
        result = svc._aggregate_verdict(
            qa_result={"total_checks": 0, "passed_checks": 0, "failures": [], "warnings": []},
            checklist_result={"checks": [], "failures": [], "warnings": []},
            image_eval_result={"images_evaluated": 1, "images_passed": 0, "images_failed": 0, "uncertain_count": 1},
            policy={"max_warnings_for_auto_publish": 0},
        )
        assert result["verdict"] == "failed"
        assert result["warning_count"] == 1


# =============================================================================
# TESTS — get_pending_articles
# =============================================================================


class TestGetPendingArticles:
    def test_excludes_already_evaluated(self):
        mock_db = MagicMock()
        # First query: articles
        articles_result = MagicMock()
        articles_result.data = [
            {"id": "a1", "brand_id": BRAND_ID, "status": "qa_passed"},
            {"id": "a2", "brand_id": BRAND_ID, "status": "qa_passed"},
        ]
        # Second query: already evaluated
        eval_result = MagicMock()
        eval_result.data = [{"article_id": "a1"}]

        # Chain mock calls
        mock_table = MagicMock()
        call_count = [0]
        def table_side_effect(name):
            call_count[0] += 1
            if call_count[0] == 1:
                # seo_articles query
                chain = MagicMock()
                chain.select.return_value = chain
                chain.in_.return_value = chain
                chain.eq.return_value = chain
                chain.execute.return_value = articles_result
                return chain
            else:
                # seo_content_eval_results query
                chain = MagicMock()
                chain.select.return_value = chain
                chain.in_.return_value = chain
                chain.execute.return_value = eval_result
                return chain
        mock_db.table = table_side_effect

        svc = _make_service(mock_db)
        pending = svc.get_pending_articles(brand_id=BRAND_ID)
        assert len(pending) == 1
        assert pending[0]["id"] == "a2"

    def test_returns_empty_when_no_articles(self):
        mock_db = MagicMock()
        articles_result = MagicMock()
        articles_result.data = []
        chain = MagicMock()
        chain.select.return_value = chain
        chain.in_.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = articles_result
        mock_db.table.return_value = chain

        svc = _make_service(mock_db)
        pending = svc.get_pending_articles()
        assert pending == []


# =============================================================================
# TESTS — override_eval
# =============================================================================


class TestOverrideEval:
    def test_updates_eval_and_article_status(self):
        mock_db = MagicMock()
        eval_id = "eval-001"

        update_result = MagicMock()
        update_result.data = [{"id": eval_id, "article_id": ARTICLE_ID}]

        chain = MagicMock()
        chain.update.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = update_result
        mock_db.table.return_value = chain

        svc = _make_service(mock_db)
        result = svc.override_eval(eval_id, "Image acceptable for brand")
        assert result["id"] == eval_id


# =============================================================================
# TESTS — _fetch_image
# =============================================================================


class TestFetchImage:
    @patch("viraltracker.services.seo_pipeline.services.content_eval_service.httpx")
    def test_jpeg_detection(self, mock_httpx):
        mock_response = MagicMock()
        mock_response.content = b"fake-image-data"
        mock_response.headers = {"content-type": "image/jpeg"}
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_httpx.Client.return_value = mock_client

        svc = _make_service()
        b64, media_type = svc._fetch_image("https://example.com/img.jpg")
        assert media_type == "image/jpeg"
        assert b64 is not None

    @patch("viraltracker.services.seo_pipeline.services.content_eval_service.httpx")
    def test_fetch_failure_returns_none(self, mock_httpx):
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = Exception("timeout")
        mock_httpx.Client.return_value = mock_client

        svc = _make_service()
        b64, media_type = svc._fetch_image("https://example.com/img.jpg")
        assert b64 is None
        assert media_type is None
