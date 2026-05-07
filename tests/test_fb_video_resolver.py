"""Unit tests for fb_video_resolver.

Covers pure-function helpers (looks_like_fb_url, canonicalize_fb_url),
the Apify-backed extraction path (mocked), ResolverError shape.

Run with: pytest tests/test_fb_video_resolver.py -v
"""

from unittest.mock import MagicMock, patch

import pytest

from viraltracker.services.fb_video_resolver import (
    ResolverError,
    canonicalize_fb_url,
    looks_like_fb_url,
    resolve_fb_video,
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
    # Trailing slash stripped, www preserved
    (
        "https://www.facebook.com/61586/posts/12345/",
        "https://www.facebook.com/61586/posts/12345",
    ),
    # m. → www. normalization
    (
        "https://m.facebook.com/61586/posts/12345/",
        "https://www.facebook.com/61586/posts/12345",
    ),
    # Bare facebook.com gets www. prefix added
    (
        "https://facebook.com/61586/posts/12345",
        "https://www.facebook.com/61586/posts/12345",
    ),
    # Tracking query params stripped, v= preserved
    (
        "https://www.facebook.com/watch/?v=99&ref=copy&fbclid=abc",
        "https://www.facebook.com/watch?v=99",
    ),
    # id= preserved on ad library URLs
    (
        "https://www.facebook.com/ads/library/?id=12345&active=true",
        "https://www.facebook.com/ads/library?id=12345",
    ),
    # Fragment stripped
    (
        "https://www.facebook.com/61586/posts/12345#comment-1",
        "https://www.facebook.com/61586/posts/12345",
    ),
    # Mixed case host normalized
    (
        "https://WWW.Facebook.COM/61586/posts/12345",
        "https://www.facebook.com/61586/posts/12345",
    ),
])
def test_canonicalize_fb_url_normalizes(input_url, expected):
    assert canonicalize_fb_url(input_url) == expected


def test_canonicalize_idempotent():
    """Canonicalizing an already-canonical URL is a no-op."""
    canonical = "https://www.facebook.com/61586/posts/12345"
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


# ---------------------------------------------------------------------------
# resolve_fb_video — Apify-backed extraction path (mocked)
# ---------------------------------------------------------------------------


def _build_mock_apify_client(
    items=None,
    run_status="SUCCEEDED",
    run_dataset_id="test-dataset",
    call_raises=None,
):
    """Helper: produce a MagicMock ApifyClient with controllable behavior."""
    client = MagicMock()
    actor = MagicMock()

    if call_raises is not None:
        actor.call.side_effect = call_raises
    else:
        actor.call.return_value = {
            "defaultDatasetId": run_dataset_id,
            "status": run_status,
        }
    client.actor.return_value = actor

    dataset = MagicMock()
    dataset.iterate_items.return_value = iter(items or [])
    client.dataset.return_value = dataset

    return client


def _build_mock_httpx(content=b"video-bytes", content_type="video/mp4", content_length=None):
    """Helper: produce a MagicMock httpx.Client context manager."""
    if content_length is None:
        content_length = len(content)

    head_response = MagicMock()
    head_response.headers = {"content-length": str(content_length)}

    get_response = MagicMock()
    get_response.headers = {"content-type": content_type}
    get_response.content = content
    get_response.raise_for_status = MagicMock()

    http = MagicMock()
    http.head.return_value = head_response
    http.get.return_value = get_response
    http.__enter__ = MagicMock(return_value=http)
    http.__exit__ = MagicMock(return_value=False)
    return http


def test_resolve_fb_video_happy_path(monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "test-token")
    client = _build_mock_apify_client(
        items=[{"videoUrl": "https://api.apify.com/v2/key-value-stores/abc/records/video"}]
    )
    http = _build_mock_httpx(content=b"x" * 1024, content_type="video/mp4")

    with patch("apify_client.ApifyClient", return_value=client), \
         patch("httpx.Client", return_value=http):
        bytes_out, mime = resolve_fb_video(
            "https://www.facebook.com/61586/posts/123/", timeout=30, size_cap_mb=10
        )

    assert bytes_out == b"x" * 1024
    assert mime == "video/mp4"
    client.actor.assert_called_once()
    actor_call = client.actor.return_value.call
    actor_call.assert_called_once()
    # Verify URL passed via urls field (matches actor's expected input schema)
    assert actor_call.call_args.kwargs["run_input"] == {
        "urls": [{"url": "https://www.facebook.com/61586/posts/123/"}]
    }


def test_resolve_fb_video_rejects_non_fb_url(monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "test-token")
    with pytest.raises(ResolverError, match="does not look like a Facebook URL"):
        resolve_fb_video("https://www.youtube.com/watch?v=abc")


def test_resolve_fb_video_missing_token(monkeypatch):
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    client = _build_mock_apify_client(items=[{"videoUrl": "x"}])
    with patch("apify_client.ApifyClient", return_value=client):
        with pytest.raises(ResolverError, match="APIFY_TOKEN"):
            resolve_fb_video("https://www.facebook.com/x/posts/1", timeout=10)


def test_resolve_fb_video_actor_call_raises(monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "test-token")
    client = _build_mock_apify_client(call_raises=RuntimeError("apify down"))
    with patch("apify_client.ApifyClient", return_value=client):
        with pytest.raises(ResolverError, match="Apify actor call failed"):
            resolve_fb_video("https://www.facebook.com/x/posts/1", timeout=10)


def test_resolve_fb_video_actor_failed_status(monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "test-token")
    client = _build_mock_apify_client(run_status="FAILED", items=[])
    with patch("apify_client.ApifyClient", return_value=client):
        with pytest.raises(ResolverError, match="finished with status: FAILED"):
            resolve_fb_video("https://www.facebook.com/x/posts/1", timeout=10)


def test_resolve_fb_video_no_items(monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "test-token")
    client = _build_mock_apify_client(items=[])
    with patch("apify_client.ApifyClient", return_value=client):
        with pytest.raises(ResolverError, match="returned no items"):
            resolve_fb_video("https://www.facebook.com/x/posts/1", timeout=10)


def test_resolve_fb_video_missing_video_url(monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "test-token")
    client = _build_mock_apify_client(items=[{"otherField": "abc"}])
    with patch("apify_client.ApifyClient", return_value=client):
        with pytest.raises(ResolverError, match="no video URL"):
            resolve_fb_video("https://www.facebook.com/x/posts/1", timeout=10)


def test_resolve_fb_video_size_cap_via_head(monkeypatch):
    """HEAD response says video is 200MB; should reject before downloading body."""
    monkeypatch.setenv("APIFY_TOKEN", "test-token")
    client = _build_mock_apify_client(items=[{"videoUrl": "https://x"}])
    huge = 200 * 1024 * 1024
    http = _build_mock_httpx(content=b"shouldnt-matter", content_length=huge)
    with patch("apify_client.ApifyClient", return_value=client), \
         patch("httpx.Client", return_value=http):
        with pytest.raises(ResolverError, match="exceeds 100MB cap"):
            resolve_fb_video("https://www.facebook.com/x/posts/1", timeout=10, size_cap_mb=100)


def test_resolve_fb_video_alternate_url_field_keys(monkeypatch):
    """Defensive: actor sometimes returns 'downloadUrl' or 'url' instead of 'videoUrl'."""
    monkeypatch.setenv("APIFY_TOKEN", "test-token")
    for key in ("downloadUrl", "download_url", "url"):
        client = _build_mock_apify_client(items=[{key: "https://x"}])
        http = _build_mock_httpx(content=b"x" * 100)
        with patch("apify_client.ApifyClient", return_value=client), \
             patch("httpx.Client", return_value=http):
            bytes_out, _ = resolve_fb_video(
                "https://www.facebook.com/x/posts/1", timeout=10
            )
            assert bytes_out == b"x" * 100
