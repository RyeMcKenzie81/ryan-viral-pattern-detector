"""Whole-word keyword matching (B13).

Substring matching (`keyword.lower() in text.lower()`) false-matches across
word boundaries: "key" matches "keys"/"monkey", "game" matches "games". For
keyword-placement and keyword-presence checks that misreports a keyword as
present when only an inflection appears. This module is the one shared,
word-boundary-correct matcher.
"""

import re
from functools import lru_cache


@lru_cache(maxsize=512)
def _compiled(keyword: str) -> "re.Pattern":
    # Lookarounds (not \b) so a keyword that begins/ends with a non-word char
    # (e.g. "(beta)", "kids'") still anchors correctly — \b would misbehave at
    # those edges. (?<!\w)...(?!\w) = not flanked by a word char on either side.
    return re.compile(rf"(?<!\w){re.escape(keyword)}(?!\w)", re.IGNORECASE)


def keyword_in_text(keyword: str, text: str) -> bool:
    """True if `keyword` appears in `text` as a whole word/phrase (case-insensitive).

    >>> keyword_in_text("key", "the keys are here")
    False
    >>> keyword_in_text("key", "where is the key?")
    True
    >>> keyword_in_text("online gaming", "best ONLINE GAMING tips")
    True
    """
    if not keyword or not text:
        return False
    return bool(_compiled(keyword.strip().lower()).search(text.lower()))
