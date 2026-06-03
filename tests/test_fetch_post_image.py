"""Tests for SHARE/post-backed ad creative capture (_fetch_post_image).

SHARE ads run an existing organic post — their creative has no inline image, so
the image must be fetched from the post via effective_object_story_id. This is
what gets static "boosted post" ads' creatives into storage for classification.

Run with: pytest tests/test_fetch_post_image.py -v
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from viraltracker.services.meta_ads_service import MetaAdsService


def _resp(payload):
    r = MagicMock()
    r.json.return_value = payload
    return r


class TestFetchPostImage:
    def test_prefers_full_size_attachment_image(self):
        svc = MetaAdsService(access_token="fake")
        api = MagicMock()
        api.call.return_value = _resp({
            "full_picture": "http://low/res.jpg",
            "attachments": {"data": [{"media": {"image": {"src": "http://full/res.jpg"}}}]},
        })
        with patch("facebook_business.api.FacebookAdsApi.get_default_api", return_value=api):
            assert svc._fetch_post_image("123_456") == "http://full/res.jpg"
        # asked for both fields
        assert "full_picture" in api.call.call_args[0][2]["fields"]

    def test_falls_back_to_full_picture(self):
        svc = MetaAdsService(access_token="fake")
        api = MagicMock()
        api.call.return_value = _resp({"full_picture": "http://full_picture.jpg"})
        with patch("facebook_business.api.FacebookAdsApi.get_default_api", return_value=api):
            assert svc._fetch_post_image("123_456") == "http://full_picture.jpg"

    def test_empty_story_id_returns_none(self):
        svc = MetaAdsService(access_token="fake")
        assert svc._fetch_post_image(None) is None
        assert svc._fetch_post_image("") is None

    def test_no_image_anywhere_returns_none(self):
        svc = MetaAdsService(access_token="fake")
        api = MagicMock()
        api.call.return_value = _resp({"id": "123_456"})  # no picture fields
        with patch("facebook_business.api.FacebookAdsApi.get_default_api", return_value=api):
            assert svc._fetch_post_image("123_456") is None

    def test_api_error_returns_none(self):
        svc = MetaAdsService(access_token="fake")
        api = MagicMock()
        api.call.side_effect = RuntimeError("graph error")
        with patch("facebook_business.api.FacebookAdsApi.get_default_api", return_value=api):
            assert svc._fetch_post_image("123_456") is None
