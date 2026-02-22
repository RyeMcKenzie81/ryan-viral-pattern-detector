"""Multi-signal layout analysis for multipass pipeline.

Parses original page HTML using multiple signal sources to detect
layout patterns per section. No LLM — all deterministic heuristics.

Signal sources (in priority order, each adds confidence):
1. JSON-LD / Schema.org metadata
2. Semantic HTML tags
3. ARIA landmarks
4. CSS layout from inlined styles (via css-inline)
5. CSS framework class patterns (Bootstrap, Tailwind, Foundation)
6. Class name keyword matching
7. Heading text heuristics
8. Structural repetition
"""

import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

LAYOUT_TYPES = [
    "nav_bar", "hero_centered", "hero_split", "feature_grid", "testimonial_cards",
    "cta_banner", "faq_list", "pricing_table", "logo_bar",
    "stats_row", "content_block", "footer_columns", "generic",
]


@dataclass
class LayoutHint:
    """Layout classification for a section."""
    layout_type: str = "generic"
    column_count: int = 1
    text_position: str = "left"
    has_image: bool = False
    has_background_image: bool = False
    card_count: int = 0
    confidence: float = 0.0
    css_overrides: Dict[str, str] = field(default_factory=dict)
    detection_signals: List[str] = field(default_factory=list)


def analyze_html_layout(
    inlined_html: str,
    original_html: str,
    sections: list,
    css_rules: Optional[Any] = None,
    page_url: str = "",
) -> Dict[str, LayoutHint]:
    """Analyze page HTML to detect layout patterns per section.

    Args:
        inlined_html: HTML with all CSS resolved to inline styles (from css-inline).
        original_html: Original page HTML (for class names, ARIA, JSON-LD).
        sections: List of SegmenterSection objects.
        css_rules: Optional ExtractedCSS for additional layout rules.
        page_url: Original page URL (for reference).

    Returns:
        Dict of section_id → LayoutHint.
    """
    if not original_html and not inlined_html:
        return {s.section_id: LayoutHint() for s in sections}

    html = inlined_html or original_html

    # Step 1: Extract global signals
    json_ld_types = _extract_json_ld_types(original_html)
    global_classes = _extract_all_classes(original_html)
    framework = _detect_css_framework(global_classes)

    # Step 2: Match sections to HTML regions
    section_regions = _match_sections_to_html(html, sections)

    # Step 3: Analyze each section
    result: Dict[str, LayoutHint] = {}
    for section in sections:
        sec_id = section.section_id
        region_html = section_regions.get(sec_id, "")

        if not region_html:
            result[sec_id] = LayoutHint()
            continue

        # Collect candidates with confidence scores
        candidates: Dict[str, float] = {}
        signals: Dict[str, List[str]] = {}

        # Signal 1: JSON-LD metadata
        _check_json_ld(json_ld_types, candidates, signals)

        # Signal 2: Semantic HTML tags
        _check_semantic_tags(region_html, candidates, signals)

        # Signal 3: ARIA landmarks
        _check_aria(region_html, candidates, signals)

        # Signal 4: CSS layout from inlined styles
        col_count = _check_inline_css(region_html, candidates, signals)

        # Signal 5: CSS framework classes
        _check_framework_classes(region_html, framework, candidates, signals)

        # Signal 6: Class name keywords
        _check_class_keywords(region_html, candidates, signals)

        # Signal 7: Heading text
        _check_heading_text(section.markdown, candidates, signals)

        # Signal 8: Structural repetition
        card_count = _check_structural_repetition(region_html, candidates, signals)

        # Select winner
        if candidates:
            best_type = max(candidates, key=candidates.get)
            best_conf = candidates[best_type]
        else:
            best_type = "generic"
            best_conf = 0.0

        if best_conf < 0.3:
            best_type = "generic"

        hint = LayoutHint(
            layout_type=best_type,
            column_count=col_count if col_count > 1 else _infer_column_count(best_type, card_count),
            confidence=min(best_conf, 1.0),
            card_count=card_count,
            has_image=bool(re.search(r'<img\b', region_html, re.IGNORECASE)),
            detection_signals=signals.get(best_type, []),
        )

        # Detect hero_split: image + text side by side
        if best_type in ("hero_centered", "content_block"):
            if hint.has_image and col_count >= 2:
                hint.layout_type = "hero_split"
                hint.column_count = 2

        result[sec_id] = hint

    return result


# ---------------------------------------------------------------------------
# Signal detectors
# ---------------------------------------------------------------------------


def _extract_json_ld_types(html: str) -> List[str]:
    """Extract @type values from JSON-LD blocks (regex, no external deps)."""
    types: List[str] = []
    if not html:
        return types

    for match in re.finditer(
        r'<script\s+type=["\']application/ld\+json["\']\s*>(.*?)</script>',
        html, re.DOTALL | re.IGNORECASE
    ):
        try:
            data = json.loads(match.group(1))
            if isinstance(data, dict):
                t = data.get("@type", "")
                if isinstance(t, list):
                    types.extend(t)
                elif t:
                    types.append(t)
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        t = item.get("@type", "")
                        if isinstance(t, list):
                            types.extend(t)
                        elif t:
                            types.append(t)
        except (json.JSONDecodeError, ValueError):
            continue

    return types


def _check_json_ld(
    types: List[str],
    candidates: Dict[str, float],
    signals: Dict[str, List[str]],
) -> None:
    """Map JSON-LD @type to layout types."""
    type_map = {
        "FAQPage": "faq_list",
        "Product": "pricing_table",
        "Review": "testimonial_cards",
        "Testimonial": "testimonial_cards",
        "Organization": "content_block",
    }
    for t in types:
        layout = type_map.get(t)
        if layout:
            candidates[layout] = candidates.get(layout, 0) + 0.4
            signals.setdefault(layout, []).append(f"json-ld:{t}")


def _check_semantic_tags(
    html: str,
    candidates: Dict[str, float],
    signals: Dict[str, List[str]],
) -> None:
    """Check for semantic HTML tags."""
    html_lower = html.lower()

    if '<nav' in html_lower:
        candidates["nav_bar"] = candidates.get("nav_bar", 0) + 0.3
        signals.setdefault("nav_bar", []).append("semantic:<nav>")
    if '<footer' in html_lower:
        candidates["footer_columns"] = candidates.get("footer_columns", 0) + 0.3
        signals.setdefault("footer_columns", []).append("semantic:<footer>")
    if '<article' in html_lower:
        candidates["content_block"] = candidates.get("content_block", 0) + 0.2
        signals.setdefault("content_block", []).append("semantic:<article>")


def _check_aria(
    html: str,
    candidates: Dict[str, float],
    signals: Dict[str, List[str]],
) -> None:
    """Check ARIA landmark roles."""
    aria_map = {
        'role="banner"': ("hero_centered", "aria:banner"),
        'role="navigation"': ("nav_bar", "aria:navigation"),
        'role="contentinfo"': ("footer_columns", "aria:contentinfo"),
        'role="main"': ("content_block", "aria:main"),
        'role="complementary"': ("content_block", "aria:complementary"),
    }
    for attr, (layout, signal) in aria_map.items():
        if attr in html:
            candidates[layout] = candidates.get(layout, 0) + 0.2
            signals.setdefault(layout, []).append(signal)


def _check_inline_css(
    html: str,
    candidates: Dict[str, float],
    signals: Dict[str, List[str]],
) -> int:
    """Check inlined CSS for layout properties. Returns detected column count."""
    col_count = 1

    # Grid detection
    grid_match = re.search(
        r'style="[^"]*display:\s*grid[^"]*grid-template-columns:\s*repeat\((\d+)',
        html, re.IGNORECASE
    )
    if grid_match:
        col_count = int(grid_match.group(1))
        candidates["feature_grid"] = candidates.get("feature_grid", 0) + 0.3
        signals.setdefault("feature_grid", []).append(f"css:grid-cols-{col_count}")
    elif re.search(r'style="[^"]*display:\s*grid', html, re.IGNORECASE):
        # Grid without explicit repeat — check for multiple column values
        col_match = re.search(
            r'grid-template-columns:\s*([^;"]+)',
            html, re.IGNORECASE
        )
        if col_match:
            cols_value = col_match.group(1)
            # Count space-separated values (e.g., "1fr 1fr 1fr")
            col_count = max(len(cols_value.split()), 1)
            if col_count > 1:
                candidates["feature_grid"] = candidates.get("feature_grid", 0) + 0.3
                signals.setdefault("feature_grid", []).append(f"css:grid-cols-{col_count}")

    # Flex detection
    if re.search(r'style="[^"]*display:\s*flex', html, re.IGNORECASE):
        # Check if it has image + text children pattern (hero_split)
        if re.search(r'<img\b', html, re.IGNORECASE):
            candidates["hero_split"] = candidates.get("hero_split", 0) + 0.2
            signals.setdefault("hero_split", []).append("css:flex+img")

    # Centered text detection
    if re.search(r'style="[^"]*text-align:\s*center', html, re.IGNORECASE):
        if re.search(r'<h1\b', html, re.IGNORECASE):
            candidates["hero_centered"] = candidates.get("hero_centered", 0) + 0.2
            signals.setdefault("hero_centered", []).append("css:center+h1")

    return col_count


def _detect_css_framework(classes: List[str]) -> str:
    """Detect CSS framework from class names."""
    class_str = " ".join(classes)
    if re.search(r'col-(?:xs|sm|md|lg|xl)-\d', class_str):
        return "bootstrap"
    if re.search(r'grid-cols-\d|flex-row|px-\d|py-\d', class_str):
        return "tailwind"
    if re.search(r'\bcell\b.*\bgrid-x\b|\bcolumns\b.*\brow\b', class_str):
        return "foundation"
    return ""


def _check_framework_classes(
    html: str,
    framework: str,
    candidates: Dict[str, float],
    signals: Dict[str, List[str]],
) -> None:
    """Check for CSS framework-specific layout classes."""
    if framework == "bootstrap":
        # Bootstrap grid: col-md-4 = 3 columns
        col_match = re.search(r'col-(?:xs|sm|md|lg|xl)-(\d+)', html)
        if col_match:
            col_size = int(col_match.group(1))
            if col_size <= 6:
                candidates["feature_grid"] = candidates.get("feature_grid", 0) + 0.25
                signals.setdefault("feature_grid", []).append(f"bootstrap:col-{col_size}")
        if 'class="card' in html or "class='card" in html:
            candidates["feature_grid"] = candidates.get("feature_grid", 0) + 0.2
            signals.setdefault("feature_grid", []).append("bootstrap:card")

    elif framework == "tailwind":
        col_match = re.search(r'grid-cols-(\d+)', html)
        if col_match:
            candidates["feature_grid"] = candidates.get("feature_grid", 0) + 0.25
            signals.setdefault("feature_grid", []).append(f"tailwind:grid-cols-{col_match.group(1)}")


def _check_class_keywords(
    html: str,
    candidates: Dict[str, float],
    signals: Dict[str, List[str]],
) -> None:
    """Check class names for layout-related keywords."""
    class_re = re.compile(r'class="([^"]*)"', re.IGNORECASE)
    all_classes = " ".join(m.group(1) for m in class_re.finditer(html)).lower()

    keyword_map = {
        "hero": ("hero_centered", 0.2),
        "feature": ("feature_grid", 0.2),
        "testimonial": ("testimonial_cards", 0.2),
        "review": ("testimonial_cards", 0.15),
        "pricing": ("pricing_table", 0.2),
        "faq": ("faq_list", 0.2),
        "footer": ("footer_columns", 0.2),
        "cta": ("cta_banner", 0.2),
        "call-to-action": ("cta_banner", 0.2),
        "logo": ("logo_bar", 0.2),
        "partner": ("logo_bar", 0.15),
        "stat": ("stats_row", 0.2),
        "metric": ("stats_row", 0.15),
        "counter": ("stats_row", 0.15),
        "nav": ("nav_bar", 0.2),
    }

    for keyword, (layout, weight) in keyword_map.items():
        if keyword in all_classes:
            candidates[layout] = candidates.get(layout, 0) + weight
            signals.setdefault(layout, []).append(f"class:{keyword}")


def _check_heading_text(
    markdown: str,
    candidates: Dict[str, float],
    signals: Dict[str, List[str]],
) -> None:
    """Check section heading text for layout hints."""
    heading_match = re.match(r'^#{1,3}\s+(.+)', markdown.strip())
    if not heading_match:
        return

    heading = heading_match.group(1).lower()

    text_map = {
        "faq": ("faq_list", 0.15),
        "frequently asked": ("faq_list", 0.15),
        "pricing": ("pricing_table", 0.15),
        "plan": ("pricing_table", 0.1),
        "testimonial": ("testimonial_cards", 0.15),
        "what our": ("testimonial_cards", 0.15),
        "customer": ("testimonial_cards", 0.1),
        "feature": ("feature_grid", 0.1),
        "why choose": ("feature_grid", 0.1),
        "how it works": ("feature_grid", 0.1),
        "trusted by": ("logo_bar", 0.15),
        "partners": ("logo_bar", 0.1),
        "our numbers": ("stats_row", 0.15),
        "by the numbers": ("stats_row", 0.15),
    }

    for phrase, (layout, weight) in text_map.items():
        if phrase in heading:
            candidates[layout] = candidates.get(layout, 0) + weight
            signals.setdefault(layout, []).append(f"heading:{phrase}")


def _check_structural_repetition(
    html: str,
    candidates: Dict[str, float],
    signals: Dict[str, List[str]],
) -> int:
    """Check for repeated similar siblings. Returns card count."""
    # Count repeated <div> blocks with similar structure
    parser = _RepetitionParser()
    try:
        parser.feed(html)
    except Exception as e:
        logger.debug(f"Repetition parser failed: {e}")
        return 0

    max_repeat = parser.max_repeated_children
    if max_repeat >= 3:
        candidates["feature_grid"] = candidates.get("feature_grid", 0) + 0.2
        signals.setdefault("feature_grid", []).append(f"repetition:{max_repeat}")
        return max_repeat
    return 0


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _extract_all_classes(html: str) -> List[str]:
    """Extract all CSS class values from HTML."""
    classes: List[str] = []
    for match in re.finditer(r'class="([^"]*)"', html, re.IGNORECASE):
        classes.extend(match.group(1).split())
    return classes


def _match_sections_to_html(
    html: str,
    sections: list,
) -> Dict[str, str]:
    """Match segmenter sections to regions of HTML using heading text proximity.

    Uses the same text-proximity approach as _proximity_map_image in html_extractor.py.
    """
    result: Dict[str, str] = {}

    # Find all heading positions in HTML
    heading_positions: List[Tuple[int, str]] = []
    for match in re.finditer(
        r'<h[1-6][^>]*>(.*?)</h[1-6]>',
        html, re.IGNORECASE | re.DOTALL
    ):
        text = re.sub(r'<[^>]+>', '', match.group(1)).strip().lower()
        if text:
            heading_positions.append((match.start(), text))

    if not heading_positions:
        # No headings — give entire HTML to first section, rest get nothing
        if sections:
            result[sections[0].section_id] = html
        return result

    # Match each section to the nearest heading
    for section in sections:
        section_headings = re.findall(r'^#{1,6}\s+(.+)$', section.markdown, re.MULTILINE)
        if not section_headings:
            continue

        first_heading = section_headings[0].strip().lower()

        # Find best matching heading in HTML
        best_pos = -1
        best_score = 0.0
        for pos, heading_text in heading_positions:
            score = _word_overlap(first_heading, heading_text)
            if score > best_score:
                best_score = score
                best_pos = pos

        if best_pos >= 0 and best_score > 0.3:
            # Extract region: from this heading to the next heading or end
            next_heading_pos = len(html)
            for pos, _ in heading_positions:
                if pos > best_pos:
                    next_heading_pos = pos
                    break
            result[section.section_id] = html[best_pos:next_heading_pos]

    return result


def _word_overlap(a: str, b: str) -> float:
    """Word-level overlap score."""
    words_a = set(a.split())
    words_b = set(b.split())
    if not words_a or not words_b:
        return 0.0
    intersection = len(words_a & words_b)
    union = len(words_a | words_b)
    return intersection / union if union else 0.0


def _infer_column_count(layout_type: str, card_count: int) -> int:
    """Infer column count from layout type and card count."""
    defaults = {
        "feature_grid": 3,
        "testimonial_cards": 3,
        "pricing_table": 3,
        "stats_row": 4,
        "logo_bar": 1,
        "footer_columns": 4,
    }
    if card_count >= 4:
        return min(card_count, 4)
    if card_count >= 2:
        return card_count
    return defaults.get(layout_type, 1)


class _RepetitionParser(HTMLParser):
    """Count repeated similar child elements."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._depth = 0
        self._children_at_depth: Dict[int, List[str]] = {}
        self.max_repeated_children = 0

    def handle_starttag(self, tag: str, attrs: list):
        # Record as child of PARENT depth (before incrementing)
        parent_depth = self._depth
        self._depth += 1
        self._children_at_depth.setdefault(parent_depth, [])
        # Track tag signature: tag + list of attr names (not values)
        attr_names = sorted(name for name, _ in attrs)
        sig = f"{tag}:{','.join(attr_names[:3])}"
        self._children_at_depth[parent_depth].append(sig)

    def handle_endtag(self, tag: str):
        # Check children recorded AT this depth (they are children of this element)
        if self._depth in self._children_at_depth:
            children = self._children_at_depth[self._depth]
            # Count most common child signature
            if children:
                counts = Counter(children)
                most_common_count = counts.most_common(1)[0][1]
                self.max_repeated_children = max(
                    self.max_repeated_children, most_common_count
                )
            del self._children_at_depth[self._depth]
        self._depth = max(0, self._depth - 1)
