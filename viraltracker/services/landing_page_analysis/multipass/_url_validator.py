"""Shared URL validation for multipass pipeline.

Extracted from MockupService to avoid circular imports between
html_extractor.py and mockup_service.py.
"""

import logging
import re
from typing import Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Known tracking pixel domains
_TRACKING_DOMAINS = frozenset([
    'doubleclick.net', 'facebook.com', 'google-analytics.com',
    'googleadservices.com', 'googlesyndication.com',
])
_TRACKING_PREFIXES = ('pixel.', 'beacon.', 'track.')

# Safe data URI image types (NO svg — script risk)
_SAFE_DATA_IMAGE_TYPES = frozenset([
    'image/png', 'image/jpeg', 'image/gif', 'image/webp',
])
_DATA_URI_MAX_SIZE = 500_000  # 500KB

# Markdown image pattern
_MARKDOWN_IMAGE_RE = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')


def validate_image_url(url: str) -> Tuple[bool, str, str]:
    """Validate an image URL for safety.

    Returns (is_safe, url, reason).
    """
    if not url:
        return False, "", "empty URL"

    # Handle data: URIs
    if url.startswith('data:'):
        return _validate_data_uri(url)

    # Parse URL
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "", "invalid URL format"

    # HTTPS only
    if parsed.scheme not in ('https',):
        return False, "", f"non-HTTPS scheme: {parsed.scheme}"

    hostname = (parsed.hostname or "").lower()

    # Block private/internal IPs
    if hostname in ('localhost', '127.0.0.1', '0.0.0.0', '::1'):
        return False, "", "private IP: localhost"
    if hostname.startswith(('192.168.', '10.', '169.254.')):
        return False, "", f"private IP: {hostname}"
    # 172.16.0.0 - 172.31.255.255
    if hostname.startswith('172.'):
        parts = hostname.split('.')
        if len(parts) >= 2:
            try:
                second = int(parts[1])
                if 16 <= second <= 31:
                    return False, "", f"private IP: {hostname}"
            except ValueError:
                pass

    # Block tracking pixels
    for domain in _TRACKING_DOMAINS:
        if hostname == domain or hostname.endswith('.' + domain):
            return False, "", f"tracking domain: {hostname}"
    for prefix in _TRACKING_PREFIXES:
        if hostname.startswith(prefix):
            return False, "", f"tracking prefix: {hostname}"

    return True, url, "OK"


def _validate_data_uri(uri: str) -> Tuple[bool, str, str]:
    """Validate a data: URI for safe image content."""
    if not uri.startswith('data:'):
        return False, "", "not a data URI"

    # Extract media type
    header_end = uri.find(',')
    if header_end < 0:
        return False, "", "malformed data URI (no comma)"

    header = uri[5:header_end].lower()  # Strip "data:" prefix

    # Check media type against safe list
    media_type = header.split(';')[0].strip()
    if media_type not in _SAFE_DATA_IMAGE_TYPES:
        return False, "", f"unsafe data URI type: {media_type}"

    # Size check (approximate: base64 is ~4/3 of binary)
    data_part = uri[header_end + 1:]
    if len(data_part) > _DATA_URI_MAX_SIZE:
        return False, "", f"data URI too large: {len(data_part)} bytes"

    return True, uri, "OK"
