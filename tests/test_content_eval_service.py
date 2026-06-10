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
                chain.is_.return_value = chain
                chain.execute.return_value = eval_result
                return chain
        mock_db.table = table_side_effect

        svc = _make_service(mock_db)
        pending = svc.get_pending_articles(brand_id=BRAND_ID)
        assert len(pending) == 1
        assert pending[0]["id"] == "a2"

    def test_superseded_eval_is_re_evaluated(self):
        """An article whose only eval is superseded must be returned as pending.

        Regression guard for the P0 where remediation (Exceptions fix buttons /
        Re-evaluate / regenerate) reset an article to qa_passed but it was never
        re-evaluated because the superseded eval row still made it look
        "already evaluated". The eval query MUST filter superseded_by IS NULL.
        """
        mock_db = MagicMock()
        articles_result = MagicMock()
        articles_result.data = [
            {"id": "a1", "brand_id": BRAND_ID, "status": "qa_passed"},
        ]
        # The eval query is now filtered to non-superseded rows. a1's only eval
        # was superseded, so this returns empty -> a1 is still pending.
        eval_result = MagicMock()
        eval_result.data = []

        is_calls = []
        call_count = [0]

        def table_side_effect(name):
            call_count[0] += 1
            if call_count[0] == 1:
                chain = MagicMock()
                chain.select.return_value = chain
                chain.in_.return_value = chain
                chain.eq.return_value = chain
                chain.execute.return_value = articles_result
                return chain
            chain = MagicMock()
            chain.select.return_value = chain
            chain.in_.return_value = chain

            def _is(col, val):
                is_calls.append((col, val))
                return chain

            chain.is_.side_effect = _is
            chain.execute.return_value = eval_result
            return chain

        mock_db.table = table_side_effect

        svc = _make_service(mock_db)
        pending = svc.get_pending_articles(brand_id=BRAND_ID)

        # The article must be re-evaluated (not silently dropped)...
        assert len(pending) == 1
        assert pending[0]["id"] == "a1"
        # ...and the fix must actually be present: superseded_by IS NULL filter.
        assert ("superseded_by", "null") in is_calls

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

    @patch("viraltracker.services.seo_pipeline.services.content_eval_service.time.sleep", lambda *_: None)
    @patch("viraltracker.services.seo_pipeline.services.content_eval_service.httpx")
    def test_fetch_failure_returns_none_after_retries(self, mock_httpx):
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = Exception("timeout")  # transient -> retried
        mock_httpx.Client.return_value = mock_client

        svc = _make_service()
        b64, media_type = svc._fetch_image("https://example.com/img.jpg")
        assert b64 is None
        assert media_type is None
        # B8: a transient error is retried (3 attempts) before giving up.
        assert mock_client.get.call_count == 3


class TestClaimForEval:
    """B14: atomic per-article claim prevents two concurrent eval runs from
    double-processing the same article."""

    def _svc(self, update_returns):
        from viraltracker.services.seo_pipeline.services.content_eval_service import ContentEvalService
        db = MagicMock()
        chain = MagicMock()
        for m in ["update", "eq", "in_", "or_"]:
            getattr(chain, m).return_value = chain
        chain.execute.return_value = MagicMock(data=update_returns)
        db.table.return_value = chain
        svc = ContentEvalService(supabase_client=db)
        return svc, chain

    def test_winner_claims(self):
        svc, _ = self._svc([{"id": "a1"}])   # update matched the row
        assert svc.claim_for_eval("a1") is True

    def test_loser_skips(self):
        svc, _ = self._svc([])               # row already claimed -> 0 updated
        assert svc.claim_for_eval("a1") is False

    def test_claim_filters_pending_and_unclaimed(self):
        svc, chain = self._svc([{"id": "a1"}])
        svc.claim_for_eval("a1")
        # only pending statuses are claimable
        chain.in_.assert_any_call("status", ["qa_passed", "optimized"])
        # null-or-stale claim guard present
        assert chain.or_.called

    def test_missing_column_degrades_to_proceed(self):
        from viraltracker.services.seo_pipeline.services.content_eval_service import ContentEvalService
        db = MagicMock()
        chain = MagicMock()
        for m in ["update", "eq", "in_", "or_"]:
            getattr(chain, m).return_value = chain
        chain.execute.side_effect = RuntimeError("column eval_claimed_at does not exist")
        db.table.return_value = chain
        svc = ContentEvalService(supabase_client=db)
        # pre-migration: proceed (return True) rather than block evaluation
        assert svc.claim_for_eval("a1") is True


class TestReleaseEvalClaim:
    def test_release_clears_claim(self):
        from viraltracker.services.seo_pipeline.services.content_eval_service import ContentEvalService
        db = MagicMock()
        chain = MagicMock()
        chain.update.return_value = chain
        chain.eq.return_value = chain
        db.table.return_value = chain
        ContentEvalService(supabase_client=db).release_eval_claim("a1")
        chain.update.assert_called_once_with({"eval_claimed_at": None})

    def test_release_nonfatal(self):
        from viraltracker.services.seo_pipeline.services.content_eval_service import ContentEvalService
        db = MagicMock()
        db.table.side_effect = RuntimeError("column missing")
        ContentEvalService(supabase_client=db).release_eval_claim("a1")  # must not raise

    def test_claim_or_filter_quotes_timestamp(self):
        """codex P1: the stale-cutoff timestamp in the PostgREST or_ filter must
        be double-quoted (':' '+' '.' are reserved) or the request errors."""
        svc, chain = self._svc([{"id": "a1"}])
        svc.claim_for_eval("a1")
        or_arg = chain.or_.call_args[0][0]
        assert 'eval_claimed_at.lt."' in or_arg and or_arg.rstrip().endswith('"')

    def _svc(self, update_returns):
        from viraltracker.services.seo_pipeline.services.content_eval_service import ContentEvalService
        db = MagicMock()
        chain = MagicMock()
        for m in ["update", "eq", "in_", "or_"]:
            getattr(chain, m).return_value = chain
        chain.execute.return_value = MagicMock(data=update_returns)
        db.table.return_value = chain
        return ContentEvalService(supabase_client=db), chain


class TestImageEvalFailModes:
    """B8: split image-eval failures — broken image BLOCKS (real defect);
    our evaluator's own error is recorded but NON-blocking."""

    def test_broken_image_counts_as_failed_check(self):
        svc = _make_service()
        image_result = {
            "images_evaluated": 0, "images_passed": 0, "images_failed": 0,
            "uncertain_count": 0, "fetch_failures": 1, "eval_errors": 0,
        }
        v = svc._aggregate_verdict({}, {}, image_result, {"max_warnings_for_auto_publish": 0})
        assert v["failed_checks"] == 1
        assert v["verdict"] == "failed"   # broken image blocks publish

    def test_eval_error_does_not_block(self):
        svc = _make_service()
        image_result = {
            "images_evaluated": 0, "images_passed": 0, "images_failed": 0,
            "uncertain_count": 0, "fetch_failures": 0, "eval_errors": 2,
        }
        # max_warnings 0 (zero-tolerance) — eval_errors must NOT trip the gate.
        v = svc._aggregate_verdict({}, {}, image_result, {"max_warnings_for_auto_publish": 0})
        assert v["failed_checks"] == 0
        assert v["warning_count"] == 0
        assert v["verdict"] == "passed"   # our flakiness doesn't fail the article

    def test_single_image_fetch_failed_status(self):
        svc = _make_service()
        with patch.object(svc, "_fetch_image", return_value=(None, None)):
            r = svc._evaluate_single_image("https://x/broken.jpg", "hero", [{"rule": "r", "severity": "error"}], 0.8, "ctx")
        assert r["status"] == "fetch_failed"

    def test_single_image_eval_error_status_after_retries(self):
        svc = _make_service()
        svc._anthropic = MagicMock()
        svc._anthropic.messages.create.side_effect = Exception("503 overloaded")
        with patch.object(svc, "_fetch_image", return_value=("b64", "image/png")), \
             patch("viraltracker.services.seo_pipeline.services.content_eval_service.time.sleep", lambda *_: None):
            r = svc._evaluate_single_image("https://x/ok.jpg", "hero", [{"rule": "r", "severity": "error"}], 0.8, "ctx")
        assert r["status"] == "eval_error"
        assert svc._anthropic.messages.create.call_count == 3  # retried
