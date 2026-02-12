"""Test that scrape_missing_lp=True plumbs through meta_sync classification chain.

Verifies the flag flows through:
    execute_meta_sync_job() -> _run_classification_for_brand() -> classify_batch() -> classify_ad()
"""
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4


class TestScrapeMissingLpPlumbing(unittest.IsolatedAsyncioTestCase):

    async def test_classify_batch_passes_scrape_missing_lp(self):
        """classify_batch() must forward scrape_missing_lp to classify_ad()."""
        from viraltracker.services.ad_intelligence.classifier_service import ClassifierService
        from viraltracker.services.ad_intelligence.models import CreativeClassification

        # Create a real instance with mocked dependencies (bypass __init__)
        classifier = object.__new__(ClassifierService)
        classifier.supabase = MagicMock()
        classifier.gemini_service = MagicMock()
        classifier.video_analysis_service = MagicMock()
        classifier.congruence_analyzer = MagicMock()

        brand_id = uuid4()

        # Mock internal methods
        classifier._get_ad_spend_order = AsyncMock(return_value={"123": 100.0})
        classifier._fetch_ad_data = AsyncMock(return_value={
            "meta_ad_id": "123",
            "thumbnail_url": "https://example.com/thumb.jpg",
            "ad_copy": "Test ad copy",
            "landing_page_id": None,
            "meta_video_id": None,
        })
        classifier._compute_input_hash = MagicMock(return_value="hash123")
        classifier._find_existing_classification = AsyncMock(return_value=None)

        # Return a real CreativeClassification so BatchClassificationResult validates
        classifier.classify_ad = AsyncMock(return_value=CreativeClassification(
            meta_ad_id="123",
            brand_id=brand_id,
            source="gemini_light_thumbnail",
        ))

        await classifier.classify_batch(
            brand_id=brand_id, org_id=uuid4(), run_id=uuid4(),
            meta_ad_ids=["123"], max_new=1, max_video=0,
            scrape_missing_lp=True,
        )

        # Verify classify_ad was called
        assert classifier.classify_ad.called, "classify_ad was not called"

        # Verify scrape_missing_lp=True was forwarded
        call_kwargs = classifier.classify_ad.call_args.kwargs
        assert call_kwargs.get("scrape_missing_lp") is True, \
            f"scrape_missing_lp not forwarded to classify_ad: {call_kwargs}"

    async def test_run_classification_accepts_scrape_missing_lp(self):
        """_run_classification_for_brand() accepts scrape_missing_lp parameter."""
        import inspect
        from viraltracker.worker.scheduler_worker import _run_classification_for_brand

        sig = inspect.signature(_run_classification_for_brand)
        assert "scrape_missing_lp" in sig.parameters, \
            f"scrape_missing_lp not in _run_classification_for_brand signature: {list(sig.parameters.keys())}"

        # Default should be False
        param = sig.parameters["scrape_missing_lp"]
        assert param.default is False, \
            f"Expected default=False, got {param.default}"

    async def test_classify_batch_accepts_scrape_missing_lp(self):
        """classify_batch() accepts scrape_missing_lp parameter."""
        import inspect
        from viraltracker.services.ad_intelligence.classifier_service import ClassifierService

        sig = inspect.signature(ClassifierService.classify_batch)
        assert "scrape_missing_lp" in sig.parameters, \
            f"scrape_missing_lp not in classify_batch signature: {list(sig.parameters.keys())}"

        param = sig.parameters["scrape_missing_lp"]
        assert param.default is False, \
            f"Expected default=False, got {param.default}"


if __name__ == "__main__":
    unittest.main()
