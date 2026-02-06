"""
URL Canonicalizer - Normalize URLs for landing page matching.

Converts ad destination URLs into canonical form for matching to brand_landing_pages.

Canonicalization rules:
1. Lowercase the host
2. Remove www. prefix
3. Remove query params (UTMs, tracking, Shopify variant)
4. Normalize trailing slash (remove)

Example:
    Input:  https://WWW.WonderPaws.com/products/chews?utm_source=fb&variant=12345
    Output: https://wonderpaws.com/products/chews
"""

import logging
from typing import Optional, Set
from urllib.parse import parse_qs, urlencode, urlparse

logger = logging.getLogger(__name__)

# Query params to always remove (tracking, UTMs, variants)
PARAMS_TO_REMOVE: Set[str] = {
    # UTM parameters
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
    "utm_term",
    # Facebook tracking
    "fbclid",
    "fb_action_ids",
    "fb_action_types",
    "fb_source",
    "fb_ref",
    # Google tracking
    "gclid",
    "gclsrc",
    "dclid",
    # Shopify
    "variant",
    "selling_plan",
    # TikTok
    "ttclid",
    # Twitter
    "twclid",
    # General tracking
    "ref",
    "ref_",
    "source",
    "mc_cid",
    "mc_eid",
    "_ga",
    "_gl",
    # Session/cache busting
    "s",
    "t",
    "ts",
    "timestamp",
    "cache",
    "_t",
}

# Query params to always keep (functional, not tracking)
# Currently empty - we drop all params by default
PARAMS_TO_KEEP: Set[str] = set()


def canonicalize_url(url: str, keep_params: Optional[Set[str]] = None) -> str:
    """Normalize URL for matching.

    Applies canonicalization rules:
    1. Lowercase host
    2. Remove www. prefix
    3. Remove query params (drop all except whitelist)
    4. Normalize trailing slash (remove)

    Args:
        url: Original URL from Meta API.
        keep_params: Optional set of param names to preserve (overrides default).

    Returns:
        Canonicalized URL string.

    Examples:
        >>> canonicalize_url("https://WWW.WonderPaws.com/products/chews?utm_source=fb")
        'https://wonderpaws.com/products/chews'

        >>> canonicalize_url("https://example.com/page/?variant=123&ref=facebook")
        'https://example.com/page'

        >>> canonicalize_url("http://EXAMPLE.COM")
        'http://example.com'
    """
    if not url:
        return ""

    try:
        parsed = urlparse(url)

        # 1. Lowercase host
        host = parsed.netloc.lower()

        # 2. Remove www. prefix
        if host.startswith("www."):
            host = host[4:]

        # 3. Handle query params
        params = parse_qs(parsed.query, keep_blank_values=False)
        whitelist = keep_params if keep_params is not None else PARAMS_TO_KEEP

        # Only keep whitelisted params
        kept_params = {}
        for key, values in params.items():
            # Check if param should be kept
            if key.lower() in whitelist:
                kept_params[key] = values

        query = urlencode(kept_params, doseq=True) if kept_params else ""

        # 4. Normalize path (remove trailing slash, but keep "/" for root)
        path = parsed.path.rstrip("/") or "/"

        # 5. Rebuild URL
        scheme = parsed.scheme or "https"
        canonical = f"{scheme}://{host}{path}"
        if query:
            canonical += f"?{query}"

        return canonical

    except Exception as e:
        logger.warning(f"Failed to canonicalize URL '{url}': {e}")
        # Return lowercase version as fallback
        return url.lower()


def extract_base_domain(url: str) -> str:
    """Extract base domain from URL (without www or subdomains).

    Args:
        url: URL string.

    Returns:
        Base domain (e.g., "wonderpaws.com").
    """
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()

        # Remove www.
        if host.startswith("www."):
            host = host[4:]

        # For simple cases, return as-is
        # Note: This doesn't handle complex subdomains (e.g., shop.brand.co.uk)
        return host

    except Exception:
        return ""


def urls_match(url1: str, url2: str) -> bool:
    """Check if two URLs match after canonicalization.

    Args:
        url1: First URL.
        url2: Second URL.

    Returns:
        True if canonical forms match.
    """
    return canonicalize_url(url1) == canonicalize_url(url2)
