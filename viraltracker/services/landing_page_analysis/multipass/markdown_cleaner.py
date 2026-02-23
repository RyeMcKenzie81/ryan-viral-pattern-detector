"""Markdown pre-segmentation classifier and cleaner.

Classifies raw FireCrawl markdown lines into zones (pre_heading, body,
post_heading) and content types (nav, footer, artifact, persuasive, body).

Two modes:
  - "label": classify only, return markdown unchanged (safe default)
  - "extract": remove nav/footer/artifact lines from pre/post zones

Body zone (between first and last heading) is sacred — never modified.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pattern constants
# ---------------------------------------------------------------------------

# Scraping artifacts — encoding glitches, web-vital metrics, empty links
_ARTIFACT_PATTERNS = [
    re.compile(r"^[ΓÃ¢â€™Â]+$"),           # Unicode mojibake / Greek Gamma
    re.compile(r"^LCP$", re.IGNORECASE),    # Largest Contentful Paint metric
    re.compile(r"^\[\s*\]\(https?://"),      # Empty-text markdown links [ ](http://...)
    re.compile(r"^!\[\]\(https?://"),        # Empty-alt images ![](http://...)
    re.compile(r"^(FCP|CLS|TTFB|INP|FID|TBT)$", re.IGNORECASE),  # Web vital metrics
]

# Navigation chrome — menus, skip links, login, cart
_NAV_PATTERNS = [
    re.compile(r"skip\s+to\s+(content|main)", re.IGNORECASE),
    re.compile(r"^\[?(log\s*in|sign\s*in|sign\s*up|create\s+account|my\s+account)\]?", re.IGNORECASE),
    re.compile(r"^\[?(cart|bag|checkout)\s*(\(\d+\))?\]?$", re.IGNORECASE),
    re.compile(r"^\[?search\]?$", re.IGNORECASE),
    re.compile(r"^(menu|navigation|nav)$", re.IGNORECASE),
    re.compile(r"^\[.*\]\(.*#MainContent\)", re.IGNORECASE),
]

# Footer chrome — legal, copyright, policies
_FOOTER_PATTERNS = [
    re.compile(r"©\s*\d{4}", re.IGNORECASE),                        # © 2024
    re.compile(r"^\[?(terms\s+(of\s+)?(service|use)|privacy\s+policy|refund\s+policy)\]?", re.IGNORECASE),
    re.compile(r"^\[?(cookie\s+policy|do\s+not\s+sell|accessibility)\]?", re.IGNORECASE),
    re.compile(r"all\s+rights\s+reserved", re.IGNORECASE),
    re.compile(r"^\*these\s+statements\s+have\s+not\s+been\s+evaluated", re.IGNORECASE),  # FDA disclaimer
    re.compile(r"^\*?this\s+product\s+is\s+not\s+intended\s+to\s+diagnose", re.IGNORECASE),
    re.compile(r"food\s+and\s+drug\s+administration", re.IGNORECASE),
]

# Persuasive elements — NEVER classified as nav/footer (allowlist)
_PERSUASIVE_PATTERNS = [
    re.compile(r"free\s+shipping", re.IGNORECASE),
    re.compile(r"money[\s-]+back\s+guarantee", re.IGNORECASE),
    re.compile(r"limited[\s-]+time\s+offer", re.IGNORECASE),
    re.compile(r"^\**(NEW|SALE|BESTSELLER|HOT|POPULAR)\**$", re.IGNORECASE),
    re.compile(r"(countdown|timer|expires|hurry)", re.IGNORECASE),
    re.compile(r"\d+%\s+off", re.IGNORECASE),
    re.compile(r"(buy\s+now|shop\s+now|add\s+to\s+cart|order\s+now)", re.IGNORECASE),
    re.compile(r"(subscribe\s+&?\s*save|save\s+\d+%)", re.IGNORECASE),
]

# Heading pattern for zone detection
_HEADING_RE = re.compile(r"^#{1,6}\s+")

# Sentence heuristic: line with subject + verb + 5+ words → likely real copy
_SENTENCE_RE = re.compile(r"\b[A-Z][a-z]+\b.*\b(is|are|was|were|has|have|can|will|do|does|offer|provide|help|make|give|get|use)\b", re.IGNORECASE)
_MIN_SENTENCE_WORDS = 5

# Maximum removal ratio before bailing out in extract mode
_MAX_REMOVAL_RATIO = 0.80


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ClassifiedLine:
    """A single line with classification metadata."""
    text: str
    label: str          # "body" | "nav" | "footer" | "artifact" | "persuasive"
    confidence: float   # 0.0-1.0
    zone: str           # "pre_heading" | "body" | "post_heading"


@dataclass
class MarkdownCleanResult:
    """Result of markdown classification/cleaning."""
    cleaned_markdown: str
    classified_lines: List[ClassifiedLine]
    nav_content: Optional[str]
    footer_content: Optional[str]
    stats: Dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify_markdown(
    markdown: str,
    mode: str = "label",
) -> MarkdownCleanResult:
    """Classify and optionally clean raw FireCrawl markdown.

    Args:
        markdown: Raw markdown text from FireCrawl.
        mode: "label" (classify only, return unchanged) or "extract" (remove
              nav/footer/artifact from pre/post zones).

    Returns:
        MarkdownCleanResult with classification data and optionally cleaned markdown.
    """
    if not markdown or not markdown.strip():
        return MarkdownCleanResult(
            cleaned_markdown=markdown or "",
            classified_lines=[],
            nav_content=None,
            footer_content=None,
            stats={"body": 0, "nav": 0, "footer": 0, "artifact": 0, "persuasive": 0},
        )

    lines = markdown.split("\n")

    # ---- Step 1: Find zone boundaries ----
    first_heading_idx, last_heading_idx = _find_heading_boundaries(lines)

    # ---- Step 2: Classify each line ----
    classified: List[ClassifiedLine] = []
    for i, line in enumerate(lines):
        zone = _get_zone(i, first_heading_idx, last_heading_idx)
        label, confidence = _classify_line(line, zone)
        classified.append(ClassifiedLine(
            text=line,
            label=label,
            confidence=confidence,
            zone=zone,
        ))

    # ---- Step 3: Compute stats ----
    stats: Dict[str, int] = {"body": 0, "nav": 0, "footer": 0, "artifact": 0, "persuasive": 0}
    for cl in classified:
        stats[cl.label] = stats.get(cl.label, 0) + 1

    # ---- Step 4: Build output based on mode ----
    if mode == "label":
        # Label mode: return markdown unchanged
        return MarkdownCleanResult(
            cleaned_markdown=markdown,
            classified_lines=classified,
            nav_content=None,
            footer_content=None,
            stats=stats,
        )

    # Extract mode: remove non-body lines from pre/post zones
    removable_labels = {"nav", "footer", "artifact"}
    removable_count = sum(
        1 for cl in classified
        if cl.label in removable_labels and cl.zone != "body"
    )
    total_non_blank = sum(1 for cl in classified if cl.text.strip())

    # Safety: bail if > 80% would be removed
    if total_non_blank > 0 and removable_count / total_non_blank > _MAX_REMOVAL_RATIO:
        logger.warning(
            "Markdown cleaner bail-out: %.0f%% of lines classified as removable "
            "(threshold %.0f%%). Returning unchanged.",
            removable_count / total_non_blank * 100,
            _MAX_REMOVAL_RATIO * 100,
        )
        return MarkdownCleanResult(
            cleaned_markdown=markdown,
            classified_lines=classified,
            nav_content=None,
            footer_content=None,
            stats=stats,
        )

    kept_lines: List[str] = []
    nav_lines: List[str] = []
    footer_lines: List[str] = []

    for cl in classified:
        if cl.zone == "body":
            # Body zone is sacred — always kept
            kept_lines.append(cl.text)
        elif cl.label in removable_labels:
            if cl.label == "nav" or (cl.label == "artifact" and cl.zone == "pre_heading"):
                nav_lines.append(cl.text)
            else:
                footer_lines.append(cl.text)
        else:
            kept_lines.append(cl.text)

    return MarkdownCleanResult(
        cleaned_markdown="\n".join(kept_lines),
        classified_lines=classified,
        nav_content="\n".join(nav_lines) if nav_lines else None,
        footer_content="\n".join(footer_lines) if footer_lines else None,
        stats=stats,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_heading_boundaries(lines: List[str]) -> tuple:
    """Find the indices of the first and last heading lines.

    Returns:
        (first_heading_idx, last_heading_idx). If no headings found,
        returns (-1, -1) meaning everything is in the pre_heading zone.
    """
    first = -1
    last = -1
    for i, line in enumerate(lines):
        if _HEADING_RE.match(line.strip()):
            if first == -1:
                first = i
            last = i
    return first, last


def _get_zone(idx: int, first_heading: int, last_heading: int) -> str:
    """Determine which zone a line belongs to."""
    if first_heading == -1:
        # No headings at all — everything is pre_heading
        return "pre_heading"
    if idx < first_heading:
        return "pre_heading"
    if idx > last_heading:
        return "post_heading"
    return "body"


def _classify_line(line: str, zone: str) -> tuple:
    """Classify a single line of markdown.

    Args:
        line: The raw line text.
        zone: The zone this line belongs to ("pre_heading", "body", "post_heading").

    Returns:
        (label, confidence) tuple.
    """
    stripped = line.strip()

    # Body zone is always labeled "body" — sacred zone, never touched
    if zone == "body":
        return "body", 1.0

    # Empty lines: label as body (neutral) — they get kept in extract mode
    if not stripped:
        return "body", 1.0

    # Check persuasive patterns FIRST (allowlist — takes priority)
    for pat in _PERSUASIVE_PATTERNS:
        if pat.search(stripped):
            return "persuasive", 0.9

    # Check scraping artifacts
    for pat in _ARTIFACT_PATTERNS:
        if pat.match(stripped):
            return "artifact", 0.95

    # Check navigation patterns
    for pat in _NAV_PATTERNS:
        if pat.search(stripped):
            return "nav", 0.9

    # Check footer patterns
    for pat in _FOOTER_PATTERNS:
        if pat.search(stripped):
            return "footer", 0.9

    # Navigation list heuristic: lines that are just markdown links in pre_heading
    if zone == "pre_heading" and _is_nav_link_line(stripped):
        return "nav", 0.7

    # Footer link heuristic: lines that are just markdown links in post_heading
    if zone == "post_heading" and _is_nav_link_line(stripped):
        return "footer", 0.7

    # Sentence heuristic: lines with real sentences default to body
    words = stripped.split()
    if len(words) >= _MIN_SENTENCE_WORDS and _SENTENCE_RE.search(stripped):
        return "body", 0.8

    # Default: body (conservative — don't remove things we're unsure about)
    return "body", 0.6


def _is_nav_link_line(line: str) -> bool:
    """Check if a line is a navigation-style markdown link list item.

    Matches patterns like:
      - [Energy](https://example.com/energy)
      - [Link text](url)
      [Link text](url)
    """
    # Strip list marker
    cleaned = re.sub(r"^[-*+]\s+", "", line)
    # Check if entire line is a single markdown link
    if re.match(r"^\[.{1,50}\]\(https?://[^\)]+\)$", cleaned):
        return True
    return False
