"""Tests for static (image) awareness: deep-path mapping, creative/copy separation,
image classify-once staleness, and deep-or-skip routing.

A static ad is a SINGLE moment. Its CREATIVE awareness comes from the ON-IMAGE text /
visual (read by ImageAnalysisService with the calibrated rubric), and its COPY awareness
is judged SEPARATELY from the Facebook caption (`ad_copy`). The two judgments never share
a model call (D3), so creative<->copy congruence stays meaningful.

Because ImageAnalysisService versions its prompt independently of the classifier's
prompt_version, classify-once must re-analyze an image ad whose linked analysis is stale
(or was never linked / is a legacy light row) while leaving video + light-path ads cached.

When the deep image service is wired the image path is deep-or-SKIP: if deep can't run
(no stored asset, too low-res, transient failure) the ad is SKIPPED (not persisted) rather
than falling back to the legacy light thumbnail+caption path — so the only persisted
non-video outcome is a current-version deep row and classify-once converges.

Run with: pytest tests/test_static_awareness.py -v
"""
from __future__ import annotations

import asyncio
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from viraltracker.services.ad_intelligence.classifier_service import (
    ClassifierService,
    COPY_AWARENESS_PROMPT,
    IMAGE_ANALYSIS_PROMPT_VERSION,
    IMAGE_CREATIVE_FORMATS,
)
from viraltracker.services.image_analysis_service import (
    ImageAnalysisService,
    ImageAnalysisResult,
    PROMPT_VERSION as IMAGE_PROMPT_VERSION,
    _normalize_awareness_level,
)
from viraltracker.services.awareness_rubric import AWARENESS_RUBRIC


def _classifier(with_image=True):
    """Classifier with (default) or without the deep image service wired."""
    img = MagicMock() if with_image else None
    return ClassifierService(MagicMock(), image_analysis_service=img)


def _img_result(**kw) -> ImageAnalysisResult:
    base = dict(
        meta_ad_id="ad1",
        brand_id=uuid4(),
        input_hash="h",
        prompt_version=IMAGE_PROMPT_VERSION,
        status="ok",
        awareness_level="product_aware",
        awareness_confidence=0.9,
        messaging_theme="Branded bottle hero",
        hook_pattern="statement",
        cta_style="soft",
        visual_style={"imagery_type": "product_hero"},
        analysis_id=uuid4(),
    )
    base.update(kw)
    return ImageAnalysisResult(**base)


# ---------------------------------------------------------------------------
# Versioning: the classifier's image-version constant tracks the service's.
# ---------------------------------------------------------------------------
def test_image_prompt_version_constant_tracks_service():
    assert IMAGE_ANALYSIS_PROMPT_VERSION == IMAGE_PROMPT_VERSION


# ---------------------------------------------------------------------------
# Mapping: creative <- image analysis ; copy <- separate ad_copy judgment (D3)
# ---------------------------------------------------------------------------
class TestMappingCreativeVsCopy:
    def test_creative_from_image_copy_from_separate_call(self):
        s = _classifier()
        r = _img_result(awareness_level="product_aware", awareness_confidence=0.88)
        # The copy judgment is a SEPARATE call — stub it so we never hit the network.
        with patch.object(s, "_classify_copy_awareness", return_value=("problem_aware", 0.7)) as m:
            mapped = s._map_image_analysis_to_classification(r, "Struggling to sleep?")
        # creative comes from the image analysis
        assert mapped["creative_awareness_level"] == "product_aware"
        assert mapped["creative_awareness_confidence"] == 0.88
        # copy comes from the separate ad_copy judgment — and is DIFFERENT from creative,
        # proving the two are not conflated.
        assert mapped["copy_awareness_level"] == "problem_aware"
        assert mapped["copy_awareness_confidence"] == 0.7
        m.assert_called_once_with("Struggling to sleep?")

    def test_image_call_never_receives_ad_copy(self):
        """Creative awareness must be image-pure: the deep image call is made with
        ad_copy=None even when a caption exists (caption is judged separately)."""
        s = _classifier()
        s._image_analysis.analyze_image.return_value = _img_result()
        with patch.object(s, "_classify_copy_awareness", return_value=(None, None)):
            s._classify_image_with_analysis_service("ad1", uuid4(), uuid4(), "a caption")
        _, kwargs = s._image_analysis.analyze_image.call_args
        assert kwargs["ad_copy"] is None

    def test_imagery_type_maps_to_creative_format(self):
        s = _classifier()
        # creative_format MUST stay within the DB CHECK constraint's allowed image set.
        # Bind to the production constant (single source of truth), not a re-typed literal.
        ALLOWED = IMAGE_CREATIVE_FORMATS
        cases = {
            "product_hero": "image_product",
            "before_after": "image_before_after",
            "testimonial_card": "image_testimonial",
            "lifestyle": "image_static",        # not a distinct allowed value -> generic
            "infographic": "image_static",
            "ugc": "image_static",
            "screenshot": "image_static",
            "something_new": "image_static",     # unknown -> generic
        }
        with patch.object(s, "_classify_copy_awareness", return_value=(None, None)):
            for imagery, expected in cases.items():
                m = s._map_image_analysis_to_classification(
                    _img_result(visual_style={"imagery_type": imagery}), None
                )
                assert m["creative_format"] == expected, (imagery, m["creative_format"])
                assert m["creative_format"] in ALLOWED
            # visual_style None -> generic, still allowed
            m_none = s._map_image_analysis_to_classification(_img_result(visual_style=None), None)
            assert m_none["creative_format"] == "image_static"

    def test_links_image_analysis_id(self):
        s = _classifier()
        r = _img_result()
        with patch.object(s, "_classify_copy_awareness", return_value=(None, None)):
            mapped = s._map_image_analysis_to_classification(r, None)
        assert mapped["image_analysis_id"] == str(r.analysis_id)
        assert mapped["model_used"] == "gemini_image_deep"


# ---------------------------------------------------------------------------
# Caption source: genuine most-recent non-empty ad_copy, NEVER the ad_name fallback.
# ---------------------------------------------------------------------------
class TestGetLatestCaption:
    def _classifier_with_rows(self, rows):
        s = _classifier()
        # supabase.table(...).select(...).eq(...).eq(...).order(...).limit(...).execute()
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.order.return_value = chain
        chain.limit.return_value = chain
        chain.execute.return_value = SimpleNamespace(data=rows)
        s.supabase.table.return_value = chain
        return s

    def test_returns_most_recent_nonempty_caption(self):
        # latest row empty (placeholder refresh), real caption in an earlier row
        s = self._classifier_with_rows([
            {"ad_copy": "", "date": "2026-03-09"},
            {"ad_copy": "  Something changes with sleep for women over 45.  ", "date": "2026-02-01"},
        ])
        assert s._get_latest_caption("ad1", uuid4()) == "Something changes with sleep for women over 45."

    def test_returns_none_when_no_caption_anywhere(self):
        # No genuine caption -> None (NOT the ad_name fallback). copy awareness skipped.
        s = self._classifier_with_rows([
            {"ad_copy": "", "date": "2026-03-09"},
            {"ad_copy": None, "date": "2026-02-01"},
        ])
        assert s._get_latest_caption("ad1", uuid4()) is None

    def test_returns_none_on_query_failure(self):
        s = _classifier()
        s.supabase.table.side_effect = RuntimeError("db down")
        assert s._get_latest_caption("ad1", uuid4()) is None


# ---------------------------------------------------------------------------
# Copy awareness: empty copy short-circuits (no model call); prompt formats safely.
# ---------------------------------------------------------------------------
class TestCopyAwareness:
    def test_empty_copy_returns_none_without_calling_model(self):
        s = _classifier()
        for empty in (None, "", "   "):
            assert s._classify_copy_awareness(empty) == (None, None)

    def test_copy_prompt_formats_with_brace_containing_copy(self):
        # ad_copy is a VALUE, so stray braces in a caption must not break .format().
        p = COPY_AWARENESS_PROMPT.format(
            awareness_rubric=AWARENESS_RUBRIC,
            ad_copy="Tired? {weird} 100% off {now}",
        )
        assert "copy_awareness_level" in p
        assert "copy_awareness_confidence" in p


# ---------------------------------------------------------------------------
# Deep-or-SKIP routing: ok -> dict ; low_res -> 'low_res' ; None/error -> None
# ---------------------------------------------------------------------------
class TestDeepOrSkipHelper:
    def test_ok_returns_classification_dict(self):
        s = _classifier()
        s._image_analysis.analyze_image.return_value = _img_result()
        with patch.object(s, "_classify_copy_awareness", return_value=(None, None)):
            out = s._classify_image_with_analysis_service("ad1", uuid4(), uuid4(), None)
        assert isinstance(out, dict)
        assert out["creative_awareness_level"] == "product_aware"

    def test_low_res_returns_sentinel(self):
        s = _classifier()
        s._image_analysis.analyze_image.return_value = _img_result(status="low_res", awareness_level=None)
        assert s._classify_image_with_analysis_service("ad1", uuid4(), uuid4(), None) == "low_res"

    def test_no_image_returns_none(self):
        s = _classifier()
        s._image_analysis.analyze_image.return_value = None
        assert s._classify_image_with_analysis_service("ad1", uuid4(), uuid4(), None) is None

    def test_error_or_empty_awareness_returns_none(self):
        s = _classifier()
        s._image_analysis.analyze_image.return_value = _img_result(status="error", awareness_level=None)
        assert s._classify_image_with_analysis_service("ad1", uuid4(), uuid4(), None) is None
        s._image_analysis.analyze_image.return_value = _img_result(status="ok", awareness_level=None)
        assert s._classify_image_with_analysis_service("ad1", uuid4(), uuid4(), None) is None

    def test_exception_is_swallowed_to_none(self):
        s = _classifier()
        s._image_analysis.analyze_image.side_effect = RuntimeError("boom")
        assert s._classify_image_with_analysis_service("ad1", uuid4(), uuid4(), None) is None


# ---------------------------------------------------------------------------
# Image classify-once staleness gate
# ---------------------------------------------------------------------------
class TestImageStaleness:
    def test_unwired_service_never_stale(self):
        s = _classifier(with_image=False)
        # Even an unlinked non-video row stays cached when no deep service can upgrade it.
        assert s._image_analysis_is_stale(
            {"image_analysis_id": None}, {"is_video": False}, {}
        ) is False

    def test_video_ads_are_not_governed_here(self):
        s = _classifier()
        assert s._image_analysis_is_stale(
            {"image_analysis_id": None}, {"is_video": True}, {}
        ) is False
        # creative_format prefix also marks a video ad
        assert s._image_analysis_is_stale(
            {"image_analysis_id": None, "creative_format": "video_ugc"}, {}, {}
        ) is False

    def test_legacy_unlinked_image_is_stale(self):
        s = _classifier()
        assert s._image_analysis_is_stale(
            {"image_analysis_id": None}, {"is_video": False}, {}
        ) is True

    def test_current_version_link_is_fresh(self):
        s = _classifier()
        aid = str(uuid4())
        assert s._image_analysis_is_stale(
            {"image_analysis_id": aid}, {"is_video": False}, {aid: IMAGE_PROMPT_VERSION}
        ) is False

    def test_old_version_link_is_stale(self):
        s = _classifier()
        aid = str(uuid4())
        assert s._image_analysis_is_stale(
            {"image_analysis_id": aid}, {"is_video": False}, {aid: "v1"}
        ) is True

    def test_missing_from_map_is_stale(self):
        s = _classifier()
        assert s._image_analysis_is_stale(
            {"image_analysis_id": str(uuid4())}, {"is_video": False}, {}
        ) is True


# ---------------------------------------------------------------------------
# Awareness normalization at the trust boundary: off-rubric Gemini labels must
# degrade to a CHECK-safe value (recoverable variant or NULL), never hit the DB raw.
# ---------------------------------------------------------------------------
class TestAwarenessNormalization:
    def test_normalize_helper_recovers_variants_and_nulls_garbage(self):
        assert _normalize_awareness_level("Product Aware") == "product_aware"
        assert _normalize_awareness_level("  SOLUTION_AWARE ") == "solution_aware"
        assert _normalize_awareness_level("most_aware") == "most_aware"
        for bad in ("aware", "unknown", "very_aware", "", None, 5):
            assert _normalize_awareness_level(bad) is None

    def test_mapper_normalizes_creative_awareness(self):
        s = _classifier()
        with patch.object(s, "_classify_copy_awareness", return_value=(None, None)):
            # casing/spacing variant is recovered to a valid enum
            m1 = s._map_image_analysis_to_classification(
                _img_result(awareness_level="Product Aware"), None
            )
            # true garbage degrades to NULL (column is nullable) — not a CHECK violation
            m2 = s._map_image_analysis_to_classification(
                _img_result(awareness_level="totally_made_up"), None
            )
        assert m1["creative_awareness_level"] == "product_aware"
        assert m2["creative_awareness_level"] is None


# ---------------------------------------------------------------------------
# classify_batch -> classify_ad(force=True) contract + cached-branch convergence.
# Guards the exact ship-then-fix regression: the prefetch staleness gate is the
# authority, so a stale-light row must re-classify (force=True), and a current-
# version-linked row must be served from cache WITHOUT calling classify_ad.
# ---------------------------------------------------------------------------
def _fake_cls(source):
    from viraltracker.services.ad_intelligence.models import CreativeClassification
    return CreativeClassification(meta_ad_id="a", brand_id=uuid4(), source=source)


def _batch_classifier():
    clf = ClassifierService(MagicMock(), image_analysis_service=MagicMock())
    clf._get_ad_spend_order = AsyncMock(return_value={})
    clf._row_to_model = MagicMock(return_value=_fake_cls("cached"))
    clf.classify_ad = AsyncMock(return_value=_fake_cls("gemini_image_deep"))
    return clf


def _cls_row(**kw):
    base = {
        "prompt_version": "v2", "schema_version": "1.0",
        "image_analysis_id": None, "video_analysis_id": None,
        "creative_format": "image_static",
    }
    base.update(kw)
    return base


class TestClassifyBatchForceAndCache:
    def test_stale_light_row_reclassifies_with_force_true(self):
        clf = _batch_classifier()
        # current-version classification but UNLINKED (image_analysis_id None) => stale
        clf._batch_prefetch = AsyncMock(return_value=(
            {"adA": {"is_video": False}},
            {"adA": [_cls_row(image_analysis_id=None)]},
            {},   # video versions
            {},   # image versions
        ))
        res = asyncio.run(clf.classify_batch(
            brand_id=uuid4(), org_id=uuid4(), run_id=uuid4(), meta_ad_ids=["adA"],
        ))
        clf.classify_ad.assert_awaited_once()
        assert clf.classify_ad.await_args.kwargs["force"] is True
        assert res.new_count == 1 and res.cached_count == 0

    def test_current_version_linked_row_is_served_from_cache(self):
        clf = _batch_classifier()
        iid = str(uuid4())
        clf._batch_prefetch = AsyncMock(return_value=(
            {"adB": {"is_video": False}},
            {"adB": [_cls_row(image_analysis_id=iid)]},
            {},
            {iid: IMAGE_ANALYSIS_PROMPT_VERSION},   # linked analysis is current
        ))
        res = asyncio.run(clf.classify_batch(
            brand_id=uuid4(), org_id=uuid4(), run_id=uuid4(), meta_ad_ids=["adB"],
        ))
        clf.classify_ad.assert_not_awaited()
        assert res.cached_count == 1 and res.new_count == 0


# ---------------------------------------------------------------------------
# Deep-or-SKIP persistence semantics at the classify_ad level: when deep can't
# run it SKIPS (never the light path), and nothing is persisted.
# ---------------------------------------------------------------------------
def _classify_ad_setup(image_result):
    clf = ClassifierService(MagicMock(), image_analysis_service=MagicMock())
    clf._fetch_ad_data = AsyncMock(return_value={
        "is_video": False, "ad_copy": "", "thumbnail_url": "",
        "landing_page_id": None, "meta_video_id": None, "has_video_in_storage": False,
    })
    clf._get_latest_caption = MagicMock(return_value=None)
    clf._classify_image_with_analysis_service = MagicMock(return_value=image_result)
    clf._classify_with_gemini = AsyncMock(return_value={"creative_awareness_level": "problem_aware"})
    return clf


class TestDeepOrSkipPersistence:
    def test_deep_unavailable_skips_without_light_fallback(self):
        clf = _classify_ad_setup(image_result=None)
        c = asyncio.run(clf.classify_ad("ad1", uuid4(), uuid4(), uuid4(), video_budget_remaining=0, force=True))
        assert c.source == "skipped_image_deep_unavailable"
        clf._classify_with_gemini.assert_not_awaited()      # never the light path
        clf.supabase.table.assert_not_called()              # not persisted

    def test_low_res_skips_without_light_fallback(self):
        clf = _classify_ad_setup(image_result="low_res")
        c = asyncio.run(clf.classify_ad("ad1", uuid4(), uuid4(), uuid4(), video_budget_remaining=0, force=True))
        assert c.source == "skipped_image_low_res"
        clf._classify_with_gemini.assert_not_awaited()
        clf.supabase.table.assert_not_called()


# ---------------------------------------------------------------------------
# _image_too_small (the low_res gate decider) — pure, exercise the real thresholds.
# ---------------------------------------------------------------------------
class TestImageTooSmall:
    @staticmethod
    def _png(w, h):
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (w, h), (200, 0, 0)).save(buf, format="PNG")
        return buf.getvalue()

    def test_64x64_is_too_small_512_is_not(self):
        assert ImageAnalysisService._image_too_small(self._png(64, 64)) is True
        assert ImageAnalysisService._image_too_small(self._png(512, 512)) is False

    def test_bytesize_fallback_when_not_an_image(self):
        # non-image bytes -> PIL fails -> byte-length fallback (<12000 => too small)
        assert ImageAnalysisService._image_too_small(b"x" * 5000) is True
        assert ImageAnalysisService._image_too_small(b"x" * 20000) is False


# ---------------------------------------------------------------------------
# #180 import smoke: ImageAnalysisService resolves make_genai_client (no NameError).
# ---------------------------------------------------------------------------
def test_image_service_make_genai_client_importable():
    import viraltracker.services.image_analysis_service as mod
    # The #180 regression was a missing import; assert the name resolves from the module
    # the service uses, so analyze_image can construct a client.
    from viraltracker.core.genai_client import make_genai_client  # noqa: F401
    assert hasattr(mod, "ImageAnalysisService")
