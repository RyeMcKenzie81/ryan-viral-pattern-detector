"""The creative fetch in _fetch_thumbnails_sync must request FULL-RES thumbnails.

Without thumbnail_width/height params, Meta returns a 64x64 thumbnail_url. For
page-post-backed ads (no inline image anywhere and _fetch_post_image blocked by page
permissions), that 64x64 is what gets captured into meta_ads_performance.thumbnail_url
and downloaded into storage — unreadable by the deep classifier (low_res). The size
params return an up-to-original-res render and need only ads_read (proven live
2026-06-09: 13/13 Martin 64x64 ads recovered via this exact param).

Run with: pytest tests/test_thumbnail_fullres_capture.py -v
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from viraltracker.services.meta_ads_service import MetaAdsService


def _service():
    # Bypass __init__ (it wires config/SDK); we only exercise _fetch_thumbnails_sync.
    return MetaAdsService.__new__(MetaAdsService)


def test_creative_fetch_requests_fullres_thumbnail_and_uses_it_as_fallback():
    svc = _service()

    fake_ad = MagicMock()
    fake_ad.api_get.return_value = {"id": "ad1", "creative": {"id": "cr1"}}

    fake_creative = MagicMock()
    # Page-post-backed ad shape: no image_url / link_data / asset_feed images; only
    # the (now full-res) thumbnail_url survives the fallback chain.
    fake_creative.api_get.return_value = {
        "id": "cr1",
        "thumbnail_url": "https://cdn.example/fullres.jpg",
        "object_story_spec": {},
        "asset_feed_spec": {},
        "effective_object_story_id": "page_post",
    }

    with patch("facebook_business.adobjects.ad.Ad", return_value=fake_ad), \
         patch("facebook_business.adobjects.adcreative.AdCreative", return_value=fake_creative), \
         patch.object(MetaAdsService, "_fetch_post_image", return_value=None):
        out = svc._fetch_thumbnails_sync(["ad1"])

    # The creative fetch must carry the full-res size params.
    _, kwargs = fake_creative.api_get.call_args
    assert kwargs.get("params") == {"thumbnail_width": 1080, "thumbnail_height": 1080}, (
        "creative.api_get must request thumbnail_width/height=1080 — without them Meta "
        "returns a 64x64 thumbnail_url and page-post-backed ads become low_res forever"
    )

    # And the (full-res) thumbnail fallback is what gets captured for this ad.
    assert out["ad1"]["thumbnail_url"] == "https://cdn.example/fullres.jpg"
