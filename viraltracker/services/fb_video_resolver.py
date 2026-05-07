"""Facebook video URL resolver.

Self-contained module. No DB or service dependencies.
Resolves a public Facebook video URL (post / reel / watch / ad library) to
a video file via yt-dlp, with a true wall-clock timeout, size cap, and
non-video content rejection.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Optional, Tuple
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 90.0
DEFAULT_SIZE_CAP_MB = 100

# UX guard only — "looks like a Facebook URL". NOT a guarantee yt-dlp will
# succeed. yt-dlp explicitly states URL support cannot be reliably pre-detected;
# the resolver itself is the source of truth. This regex catches obvious typos
# before the user waits for a yt-dlp round-trip.
_LOOKS_LIKE_FB = re.compile(r"(?:^|//)(?:[a-z0-9-]+\.)?facebook\.com/", re.I)

# Query params we keep when canonicalizing — these identify the video.
_KEEP_QUERY_KEYS = {"v", "id"}


class ResolverError(Exception):
    """yt-dlp could not extract the video, or the result violated a constraint."""


def looks_like_fb_url(url: str) -> bool:
    """UX typo guard. Returns True if the URL plausibly points at Facebook.

    Does NOT guarantee yt-dlp will extract it.
    """
    if not url or not isinstance(url, str):
        return False
    return bool(_LOOKS_LIKE_FB.search(url.strip()))


def canonicalize_fb_url(url: str) -> str:
    """Normalize an FB URL for dedupe.

    Strips: m./www. subdomains, fragments, tracking query params (keeps only
    v= and id=), trailing slash. Lowercases the host.

    Examples:
        m.facebook.com/61586/posts/12345/?ref=share  → facebook.com/61586/posts/12345
        www.facebook.com/watch/?v=99&ref=copy        → facebook.com/watch?v=99
        facebook.com/61586/posts/12345#comment       → facebook.com/61586/posts/12345
    """
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    if host.startswith("m."):
        host = host[2:]
    if host.startswith("www."):
        host = host[4:]

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
    yt-dlp's own socket_timeout is per-socket, not end-to-end — many sequential
    requests can blow past it.

    Raises ResolverError on: timeout, private/login-required video, non-video
    content (photo post / story), 404, geoblock, size > size_cap_mb, ffmpeg
    missing if a merge is required.
    """
    if not looks_like_fb_url(url):
        raise ResolverError("URL does not look like a Facebook URL")

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_extract_with_ytdlp, url, size_cap_mb)
        try:
            return future.result(timeout=timeout)
        except FuturesTimeout:
            # Best-effort cancel; the worker thread may continue in the
            # background but we raise immediately to release the caller.
            future.cancel()
            raise ResolverError(f"timed out after {timeout:.0f}s")


def _extract_with_ytdlp(url: str, size_cap_mb: int) -> Tuple[bytes, str]:
    """Run yt-dlp synchronously inside the worker thread."""
    try:
        import yt_dlp
    except ImportError as exc:
        raise ResolverError(f"yt-dlp not installed: {exc}") from exc

    size_cap_bytes = size_cap_mb * 1024 * 1024

    with tempfile.TemporaryDirectory(prefix="quick-intel-") as tmpdir:
        out_template = os.path.join(tmpdir, "%(id)s.%(ext)s")

        ydl_opts = {
            "outtmpl": out_template,
            "format": "best[ext=mp4]/best[filesize<?100M]/best",
            "max_filesize": size_cap_bytes,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "skip_download": False,
            "socket_timeout": 30,
            "retries": 2,
            "fragment_retries": 2,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
        except yt_dlp.utils.DownloadError as exc:
            msg = str(exc).lower()
            if "private" in msg or "login" in msg:
                raise ResolverError("video is private or requires login") from exc
            if "not available" in msg or "removed" in msg:
                raise ResolverError("video is not available (removed or geoblocked)") from exc
            raise ResolverError(f"download failed: {exc}") from exc
        except Exception as exc:
            raise ResolverError(f"unexpected resolver error: {exc}") from exc

        if info is None:
            raise ResolverError("yt-dlp returned no info for this URL")

        if info.get("_type") == "playlist":
            raise ResolverError("URL points to a playlist, not a single video")

        if not _looks_like_video(info):
            raise ResolverError("URL does not point to a video (photo or story?)")

        # Locate the downloaded file. yt-dlp writes one file per requested
        # download; we grab the first non-info-json file in tmpdir.
        downloaded = _find_downloaded_file(tmpdir)
        if downloaded is None:
            raise ResolverError("yt-dlp reported success but no file was downloaded")

        size = os.path.getsize(downloaded)
        if size > size_cap_bytes:
            raise ResolverError(
                f"video is {size / 1024 / 1024:.0f}MB, exceeds {size_cap_mb}MB cap"
            )
        if size == 0:
            raise ResolverError("downloaded file is empty")

        with open(downloaded, "rb") as fh:
            video_bytes = fh.read()

        mime_type = _guess_mime_from_path(downloaded)
        logger.info("Resolved %s → %s bytes (%s)", url, size, mime_type)
        return video_bytes, mime_type


def _looks_like_video(info: dict) -> bool:
    """Heuristic: treat as video if yt-dlp reports a non-zero duration or
    the format list contains a video stream."""
    if info.get("duration") and info["duration"] > 0:
        return True
    formats = info.get("formats") or []
    for fmt in formats:
        if fmt.get("vcodec") and fmt["vcodec"] != "none":
            return True
    # Single-format extractions populate vcodec at the top level
    if info.get("vcodec") and info["vcodec"] != "none":
        return True
    return False


def _find_downloaded_file(directory: str) -> Optional[str]:
    for name in os.listdir(directory):
        if name.endswith((".info.json", ".description", ".part")):
            continue
        full = os.path.join(directory, name)
        if os.path.isfile(full):
            return full
    return None


def _guess_mime_from_path(path: str) -> str:
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    if ext == "mp4":
        return "video/mp4"
    if ext in ("mov", "qt"):
        return "video/quicktime"
    if ext == "webm":
        return "video/webm"
    if ext == "mkv":
        return "video/x-matroska"
    return "application/octet-stream"
