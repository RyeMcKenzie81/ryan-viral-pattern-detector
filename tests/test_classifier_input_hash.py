"""Tests for the stable classification input_hash (no thumbnail-URL churn).

The cache key must be immune to Meta CDN signed-URL rotation (host + query
params change constantly) but still change when the actual image changes — so
the daily classification budget stops re-classifying unchanged ads.

Run with: pytest tests/test_classifier_input_hash.py -v
"""
from __future__ import annotations

from unittest.mock import MagicMock

from viraltracker.services.ad_intelligence.classifier_service import ClassifierService


def _svc():
    return ClassifierService(MagicMock())


# Same image (same path/filename), different CDN node + different signed query.
URL_A1 = "https://scontent-sjc3-1.xx.fbcdn.net/v/t45.1600-4/567_25_270_n.png?stp=dst-jpg_tt6&_nc_ohc=AAA&_nc_oc=XXX&oe=1"
URL_A2 = "https://scontent-lax3-2.xx.fbcdn.net/v/t45.1600-4/567_25_270_n.png?stp=dst-jpg_tt6&_nc_ohc=BBB&_nc_oc=YYY&oe=2"
# A genuinely different image (different filename).
URL_B = "https://scontent-sjc3-1.xx.fbcdn.net/v/t45.1600-4/999_88_111_n.png?stp=dst-jpg_tt6&_nc_ohc=AAA"


class TestStableInputHash:
    def test_same_image_different_signed_url_same_hash(self):
        s = _svc()
        assert s._compute_input_hash(URL_A1, "copy", "lp1") == s._compute_input_hash(URL_A2, "copy", "lp1")

    def test_different_image_different_hash(self):
        s = _svc()
        assert s._compute_input_hash(URL_A1, "copy", "lp1") != s._compute_input_hash(URL_B, "copy", "lp1")

    def test_copy_change_changes_hash(self):
        s = _svc()
        assert s._compute_input_hash(URL_A1, "copy1", "lp1") != s._compute_input_hash(URL_A1, "copy2", "lp1")

    def test_lp_and_video_still_part_of_hash(self):
        s = _svc()
        assert s._compute_input_hash(URL_A1, "c", "lp1") != s._compute_input_hash(URL_A1, "c", "lp2")
        assert s._compute_input_hash(URL_A1, "c", "lp1", video_id="v1") != s._compute_input_hash(URL_A1, "c", "lp1", video_id="v2")

    def test_stable_key_is_path_only(self):
        assert ClassifierService._stable_image_key(URL_A1) == "/v/t45.1600-4/567_25_270_n.png"
        assert ClassifierService._stable_image_key("") == ""
        assert ClassifierService._stable_image_key(None) == ""


class TestClassifiedOnceCacheHit:
    """Batch path is classified-once: a current-version classification is reused
    regardless of input_hash drift (the prefetch already filters prompt/schema),
    so already-classified ads stop burning the max_new budget. Only force re-runs.
    """

    def test_reuses_most_recent_regardless_of_input_hash(self):
        s = _svc()
        rows = [  # prefetch order = classified_at desc; input_hash deliberately drifted
            {"id": "newest", "input_hash": "DRIFTED", "classified_at": "2026-06-04"},
            {"id": "older", "input_hash": "orig", "classified_at": "2026-05-01"},
        ]
        match = s._match_prefetched_classification(rows, force=False)
        assert match is not None and match["id"] == "newest"

    def test_force_never_reuses(self):
        s = _svc()
        rows = [{"id": "x", "input_hash": "h", "classified_at": "2026-06-04"}]
        assert s._match_prefetched_classification(rows, force=True) is None

    def test_no_existing_rows_returns_none(self):
        s = _svc()
        assert s._match_prefetched_classification([], force=False) is None
