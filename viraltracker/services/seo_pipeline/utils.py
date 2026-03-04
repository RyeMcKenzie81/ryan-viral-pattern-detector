"""
SEO Pipeline Utilities — shared helpers for analytics services.
"""

import urllib.parse


def normalize_url_path(url: str) -> str:
    """
    Normalize a URL to just its path for matching across analytics sources.

    - Strips protocol, domain, query params, fragments
    - Strips trailing slashes
    - Lowercases
    - URL-decodes

    Examples:
        "https://example.com/blogs/news/my-article?ref=fb" → "/blogs/news/my-article"
        "https://EXAMPLE.COM/Blogs/News/My-Article/" → "/blogs/news/my-article"
        "/blogs/news/my%20article" → "/blogs/news/my article"
    """
    if not url:
        return ""

    parsed = urllib.parse.urlparse(url)
    path = parsed.path

    # URL-decode
    path = urllib.parse.unquote(path)

    # Lowercase
    path = path.lower()

    # Strip trailing slashes (but keep root "/")
    if path != "/":
        path = path.rstrip("/")

    return path
