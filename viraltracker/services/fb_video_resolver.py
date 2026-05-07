"""Facebook video URL resolver.

Resolves a public Facebook video URL (post / reel / watch / ad library) to
a video file via the Apify `bytepulselabs/facebook-video-downloader` actor,
with a true wall-clock timeout, size cap, and clean error handling.

Why Apify (not yt-dlp): Facebook progressively gates video content to
logged-in users even on public Pages. yt-dlp without cookies fails on most
real-world Page URLs. Apify handles the auth/headers/proxy complexity on
their side; we pay ~$0.07-0.30 per video at typical sizes.
"""

from __future__ import annotations

import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Tuple
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 180.0
DEFAULT_SIZE_CAP_MB = 100
DEFAULT_ACTOR_ID = "igview-owner/facebook-media-downloader"
DOWNLOAD_TIMEOUT_SECONDS = 60.0

# UX guard only — "looks like a Facebook URL". NOT a guarantee Apify will
# extract it. The actor itself is the source of truth.
_LOOKS_LIKE_FB = re.compile(r"(?:^|//)(?:[a-z0-9-]+\.)?facebook\.com/", re.I)

# Query params we keep when canonicalizing — these identify the video.
_KEEP_QUERY_KEYS = {"v", "id"}


class ResolverError(Exception):
    """Apify actor could not extract the video, or the result violated a constraint."""


def looks_like_fb_url(url: str) -> bool:
    """UX typo guard. Returns True if the URL plausibly points at Facebook."""
    if not url or not isinstance(url, str):
        return False
    return bool(_LOOKS_LIKE_FB.search(url.strip()))


def canonicalize_fb_url(url: str) -> str:
    """Normalize an FB URL for dedupe.

    Always normalizes to `www.facebook.com` (the Apify actor's URL validator
    rejects bare `facebook.com`). Strips: m. subdomain (mobile → www),
    fragments, tracking query params (keeps only v= and id=), trailing slash.

    Examples:
        m.facebook.com/61586/posts/12345/?ref=share  → www.facebook.com/61586/posts/12345
        www.facebook.com/watch/?v=99&ref=copy        → www.facebook.com/watch?v=99
        facebook.com/61586/posts/12345#comment       → www.facebook.com/61586/posts/12345
    """
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    # Strip mobile / www subdomain, then re-prefix www. so dedup is stable
    # and the Apify actor's URL validator is happy.
    if host.startswith("m."):
        host = host[2:]
    if host.startswith("www."):
        host = host[4:]
    if host:
        host = "www." + host

    path = parsed.path.rstrip("/")

    kept = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=False) if k in _KEEP_QUERY_KEYS]
    query = urlencode(kept)

    return urlunparse(("https", host, path, "", query, ""))


def resolve_fb_video(
    url: str,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    size_cap_mb: int = DEFAULT_SIZE_CAP_MB,
) -> Tuple[bytes, str]:
    """Download a public Facebook video. Returns (video_bytes, mime_type).

    Wall-clock timeout enforced via concurrent.futures.ThreadPoolExecutor.
    Defaults to 180s since Apify actor cold-start + scrape + download can
    easily take 30-90s for a single video.

    Raises ResolverError on: timeout, actor failure, no video found in
    response, missing download URL, oversized video, or download failure.
    """
    if not looks_like_fb_url(url):
        raise ResolverError("URL does not look like a Facebook URL")

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_extract_with_apify, url, size_cap_mb)
        try:
            return future.result(timeout=timeout)
        except FuturesTimeout:
            future.cancel()
            raise ResolverError(f"timed out after {timeout:.0f}s")


def _extract_with_apify(url: str, size_cap_mb: int) -> Tuple[bytes, str]:
    """Run the Apify actor synchronously and return (bytes, mime_type)."""
    try:
        from apify_client import ApifyClient
    except ImportError as exc:
        raise ResolverError(f"apify-client not installed: {exc}") from exc

    try:
        import httpx
    except ImportError as exc:
        raise ResolverError(f"httpx not installed: {exc}") from exc

    token = os.environ.get("APIFY_TOKEN")
    if not token:
        raise ResolverError("APIFY_TOKEN environment variable is not set")

    actor_id = os.environ.get("APIFY_FB_VIDEO_ACTOR", DEFAULT_ACTOR_ID)
    client = ApifyClient(token)

    # igview-owner/facebook-media-downloader uses an array of strings (not objects).
    # Other actors using {"url": "..."} object form fall through to the legacy path.
    if actor_id == DEFAULT_ACTOR_ID:
        actor_input = {"urls": [url]}
    else:
        actor_input = {"urls": [{"url": url}]}
    logger.info(f"Calling Apify actor {actor_id} with URL: {url}")

    try:
        run = client.actor(actor_id).call(run_input=actor_input)
    except Exception as exc:
        raise ResolverError(f"Apify actor call failed: {exc}") from exc

    if not run or not run.get("defaultDatasetId"):
        raise ResolverError("Apify run returned no dataset id")

    if run.get("status") != "SUCCEEDED":
        raise ResolverError(
            f"Apify actor finished with status: {run.get('status', 'unknown')}"
        )

    items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    if not items:
        raise ResolverError(
            "Apify actor returned no items (video not found, private, or geoblocked)"
        )

    item = items[0]
    # Different actors use different field names for the resulting MP4 URL.
    # Try common variants in order of likelihood.
    video_url = (
        item.get("downloadUrl")          # igview-owner/facebook-media-downloader
        or item.get("videoUrl")          # bytepulselabs and others
        or item.get("download_url")
        or item.get("url")
    )
    # Some actors return downloadLinks: [{quality, url}, ...] — pick the first.
    if not video_url:
        download_links = item.get("downloadLinks") or item.get("download_links") or []
        if download_links and isinstance(download_links, list):
            first = download_links[0]
            if isinstance(first, dict):
                video_url = first.get("url") or first.get("downloadUrl")
            elif isinstance(first, str):
                video_url = first

    if not video_url:
        raise ResolverError(
            f"Apify result has no video URL. Available keys: {list(item.keys())}"
        )

    size_cap_bytes = size_cap_mb * 1024 * 1024

    try:
        with httpx.Client(timeout=DOWNLOAD_TIMEOUT_SECONDS, follow_redirects=True) as http:
            head = http.head(video_url)
            head_content_length = int(head.headers.get("content-length", 0) or 0)
            if head_content_length and head_content_length > size_cap_bytes:
                raise ResolverError(
                    f"video is {head_content_length / 1024 / 1024:.0f}MB, "
                    f"exceeds {size_cap_mb}MB cap"
                )

            response = http.get(video_url)
            response.raise_for_status()
            video_bytes = response.content
            mime_type = (
                response.headers.get("content-type", "video/mp4").split(";")[0].strip()
            )
    except ResolverError:
        raise
    except Exception as exc:
        raise ResolverError(f"failed to download video: {exc}") from exc

    if len(video_bytes) == 0:
        raise ResolverError("downloaded video is empty")

    if len(video_bytes) > size_cap_bytes:
        raise ResolverError(
            f"video is {len(video_bytes) / 1024 / 1024:.0f}MB, exceeds {size_cap_mb}MB cap"
        )

    if not mime_type.startswith("video/"):
        mime_type = "video/mp4"

    logger.info(
        f"Apify resolved {url} → {len(video_bytes)} bytes ({mime_type})"
    )
    return video_bytes, mime_type
