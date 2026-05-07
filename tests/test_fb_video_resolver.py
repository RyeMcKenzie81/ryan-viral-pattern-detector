"""Unit tests for fb_video_resolver.

Covers pure-function helpers (looks_like_fb_url, canonicalize_fb_url) plus
ResolverError shape. The actual yt-dlp call is exercised via manual QA only,
since fixturing yt-dlp's internal behavior against live FB is fragile.

Run with: pytest tests/test_fb_video_resolver.py -v
"""

import pytest

from viraltracker.services.fb_video_resolver import (
    ResolverError,
    canonicalize_fb_url,
    looks_like_fb_url,
)


# ---------------------------------------------------------------------------
# looks_like_fb_url
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("url", [
    "https://www.facebook.com/61586899633782/posts/122123859525229987/",
    "https://facebook.com/some.page/posts/12345",
    "https://m.facebook.com/some.page/posts/12345",
    "https://www.facebook.com/reel/9876543210",
    "https://www.facebook.com/watch/?v=99999",
    "https://www.facebook.com/ads/library/?id=12345",
    "https://www.facebook.com/page-name/videos/12345",
    "//facebook.com/page/posts/1",
])
def test_looks_like_fb_url_accepts_known_patterns(url):
    assert looks_like_fb_url(url) is True


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=12345",
    "https://www.tiktok.com/@user/video/12345",
    "https://example.com/facebook.com/oops",
    "facebook.com",  # no path
    "",
    None,
    "not-even-a-url",
    "https://instagram.com/reel/12345",
])
def test_looks_like_fb_url_rejects_non_fb(url):
    assert looks_like_fb_url(url) is False


# ---------------------------------------------------------------------------
# canonicalize_fb_url
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("input_url,expected", [
    # Trailing slash stripped
    (
        "https://www.facebook.com/61586/posts/12345/",
        "https://facebook.com/61586/posts/12345",
    ),
    # m. subdomain stripped
    (
        "https://m.facebook.com/61586/posts/12345/",
        "https://facebook.com/61586/posts/12345",
    ),
    # www. stripped
    (
        "https://www.facebook.com/61586/posts/12345",
        "https://facebook.com/61586/posts/12345",
    ),
    # Tracking query params stripped, v= preserved
    (
        "https://www.facebook.com/watch/?v=99&ref=copy&fbclid=abc",
        "https://facebook.com/watch?v=99",
    ),
    # id= preserved on ad library URLs
    (
        "https://www.facebook.com/ads/library/?id=12345&active=true",
        "https://facebook.com/ads/library?id=12345",
    ),
    # Fragment stripped
    (
        "https://www.facebook.com/61586/posts/12345#comment-1",
        "https://facebook.com/61586/posts/12345",
    ),
    # Mixed case host normalized
    (
        "https://WWW.Facebook.COM/61586/posts/12345",
        "https://facebook.com/61586/posts/12345",
    ),
])
def test_canonicalize_fb_url_normalizes(input_url, expected):
    assert canonicalize_fb_url(input_url) == expected


def test_canonicalize_idempotent():
    """Canonicalizing an already-canonical URL is a no-op."""
    canonical = "https://facebook.com/61586/posts/12345"
    assert canonicalize_fb_url(canonical) == canonical


def test_canonicalize_two_variants_match():
    """Two semantically equivalent URLs canonicalize to the same string."""
    a = "https://m.facebook.com/61586/posts/12345/?ref=share&utm_source=foo"
    b = "https://www.facebook.com/61586/posts/12345#comment"
    assert canonicalize_fb_url(a) == canonicalize_fb_url(b)


# ---------------------------------------------------------------------------
# ResolverError
# ---------------------------------------------------------------------------


def test_resolver_error_is_exception():
    err = ResolverError("test message")
    assert isinstance(err, Exception)
    assert "test message" in str(err)
