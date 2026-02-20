"""Per-section and global invariant checks for the multipass pipeline.

Captures baselines after Phase 2 and checks for drift/loss after Phase 3
section refinements and Phase 4 patch application.
"""

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Dict, FrozenSet, List, Optional, Tuple

logger = logging.getLogger(__name__)

TEXT_SIMILARITY_THRESHOLD = 0.85
SHORT_TEXT_TOKEN_LIMIT = 10


@dataclass
class SectionInvariant:
    """Invariant baseline for a single section."""
    section_id: str
    slot_set: FrozenSet[str]
    normalized_tokens: List[str]
    char_count: int


@dataclass
class PipelineInvariants:
    """Full baseline captured after Phase 2."""
    global_slot_set: FrozenSet[str]
    global_tokens: List[str]
    section_count: int
    sections: Dict[str, SectionInvariant] = field(default_factory=dict)


@dataclass
class InvariantReport:
    """Result of an invariant check."""
    passed: bool
    slot_loss: List[str] = field(default_factory=list)
    text_similarity: float = 1.0
    issues: List[str] = field(default_factory=list)


class _TextExtractor(HTMLParser):
    """Extract visible text from HTML, ignoring tags."""

    def __init__(self):
        super().__init__()
        self._text_parts: List[str] = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript'):
            self._skip = True

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript'):
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            self._text_parts.append(data)

    def get_text(self) -> str:
        return ' '.join(self._text_parts)


class _SlotExtractor(HTMLParser):
    """Extract data-slot attribute values from HTML."""

    def __init__(self):
        super().__init__()
        self.slots: List[str] = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name == 'data-slot' and value:
                self.slots.append(value)


class _SectionParser(HTMLParser):
    """Parse HTML to extract per-section content."""

    def __init__(self):
        super().__init__()
        self.sections: Dict[str, str] = {}  # section_id -> inner HTML
        self._current_section: Optional[str] = None
        self._depth = 0
        self._parts: List[str] = []
        self._raw_parts: List[str] = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        section_id = attrs_dict.get('data-section')

        if section_id and tag == 'section':
            self._current_section = section_id
            self._depth = 1
            self._raw_parts = []
            return

        if self._current_section:
            self._depth += 1
            # Reconstruct the tag
            attr_str = ''
            for name, value in attrs:
                if value is not None:
                    attr_str += f' {name}="{value}"'
                else:
                    attr_str += f' {name}'
            self._raw_parts.append(f'<{tag}{attr_str}>')

    def handle_endtag(self, tag):
        if self._current_section:
            if tag == 'section' and self._depth == 1:
                self.sections[self._current_section] = ''.join(self._raw_parts)
                self._current_section = None
                self._depth = 0
                return
            self._depth -= 1
            self._raw_parts.append(f'</{tag}>')

    def handle_data(self, data):
        if self._current_section:
            self._raw_parts.append(data)


def _tokenize_visible_text(html: str) -> List[str]:
    """Extract visible text, lowercase, collapse whitespace, return word tokens."""
    extractor = _TextExtractor()
    try:
        extractor.feed(html)
    except Exception:
        pass
    text = extractor.get_text()
    # Lowercase, collapse whitespace, split into words
    words = re.split(r'\s+', text.lower().strip())
    return [w for w in words if w]


def _extract_slots(html: str) -> FrozenSet[str]:
    """Extract all data-slot values from HTML."""
    extractor = _SlotExtractor()
    try:
        extractor.feed(html)
    except Exception:
        pass
    return frozenset(extractor.slots)


def _text_similarity(tokens_a: List[str], tokens_b: List[str]) -> float:
    """Multiset Jaccard similarity between two token lists.

    Short-text guardrail: If BOTH token lists have < 10 tokens,
    fall back to normalized string equality to avoid Jaccard instability.

    Returns 0.0-1.0.
    """
    # Short-text guardrail
    if len(tokens_a) < SHORT_TEXT_TOKEN_LIMIT and len(tokens_b) < SHORT_TEXT_TOKEN_LIMIT:
        str_a = ' '.join(tokens_a)
        str_b = ' '.join(tokens_b)
        return 1.0 if str_a == str_b else 0.0

    counter_a = Counter(tokens_a)
    counter_b = Counter(tokens_b)

    intersection = sum((counter_a & counter_b).values())
    union = sum((counter_a | counter_b).values())

    return intersection / union if union > 0 else 1.0


def _parse_sections(html: str) -> Dict[str, str]:
    """Parse HTML and extract per-section inner HTML."""
    parser = _SectionParser()
    try:
        parser.feed(html)
    except Exception:
        pass
    return parser.sections


def capture_pipeline_invariants(html: str) -> PipelineInvariants:
    """Extract per-section + global invariants from Phase 2 output.

    Args:
        html: Complete HTML output from Phase 2.

    Returns:
        PipelineInvariants with per-section baselines and global aggregates.
    """
    global_slots = _extract_slots(html)
    global_tokens = _tokenize_visible_text(html)

    # Parse per-section content
    section_htmls = _parse_sections(html)

    sections = {}
    for section_id, section_html in section_htmls.items():
        slots = _extract_slots(section_html)
        tokens = _tokenize_visible_text(section_html)
        sections[section_id] = SectionInvariant(
            section_id=section_id,
            slot_set=slots,
            normalized_tokens=tokens,
            char_count=len(section_html),
        )

    return PipelineInvariants(
        global_slot_set=global_slots,
        global_tokens=global_tokens,
        section_count=len(section_htmls),
        sections=sections,
    )


def check_section_invariant(
    section_html: str,
    section_id: str,
    baseline: PipelineInvariants,
) -> InvariantReport:
    """Check a single refined section against its Phase 2 baseline.

    Args:
        section_html: Refined HTML for this section.
        section_id: Section ID to check against.
        baseline: Full pipeline invariants from Phase 2.

    Returns:
        InvariantReport with pass/fail and details.
    """
    if section_id not in baseline.sections:
        return InvariantReport(
            passed=True,
            issues=[f"No baseline for {section_id}, skipping check"],
        )

    expected = baseline.sections[section_id]
    new_slots = _extract_slots(section_html)
    new_tokens = _tokenize_visible_text(section_html)

    issues = []
    slot_loss = []

    # Check slot loss
    lost_slots = expected.slot_set - new_slots
    if lost_slots:
        slot_loss = list(lost_slots)
        issues.append(f"Lost slots: {slot_loss}")

    # Check text drift
    similarity = _text_similarity(expected.normalized_tokens, new_tokens)
    if similarity < TEXT_SIMILARITY_THRESHOLD:
        issues.append(
            f"Text drift: similarity={similarity:.3f} < {TEXT_SIMILARITY_THRESHOLD}"
        )

    passed = not slot_loss and similarity >= TEXT_SIMILARITY_THRESHOLD

    if not passed:
        logger.warning(
            f"Section {section_id} invariant FAILED: {issues}"
        )

    return InvariantReport(
        passed=passed,
        slot_loss=slot_loss,
        text_similarity=similarity,
        issues=issues,
    )


def check_global_invariants(
    html: str,
    baseline: PipelineInvariants,
) -> InvariantReport:
    """Check assembled HTML against full Phase 2 baseline.

    Args:
        html: Complete assembled HTML after Phase 3/4.
        baseline: Full pipeline invariants from Phase 2.

    Returns:
        InvariantReport with pass/fail and details.
    """
    new_slots = _extract_slots(html)
    new_tokens = _tokenize_visible_text(html)
    section_htmls = _parse_sections(html)

    issues = []
    slot_loss = []

    # Global slot set: reject if any slot lost
    lost_slots = baseline.global_slot_set - new_slots
    if lost_slots:
        slot_loss = list(lost_slots)
        issues.append(f"Global slot loss: {slot_loss}")

    # Global text similarity
    similarity = _text_similarity(baseline.global_tokens, new_tokens)
    if similarity < TEXT_SIMILARITY_THRESHOLD:
        issues.append(
            f"Global text drift: similarity={similarity:.3f} < {TEXT_SIMILARITY_THRESHOLD}"
        )

    # Section count
    if len(section_htmls) != baseline.section_count:
        issues.append(
            f"Section count changed: {baseline.section_count} -> {len(section_htmls)}"
        )

    passed = not slot_loss and similarity >= TEXT_SIMILARITY_THRESHOLD

    if not passed:
        logger.warning(f"Global invariant FAILED: {issues}")

    return InvariantReport(
        passed=passed,
        slot_loss=slot_loss,
        text_similarity=similarity,
        issues=issues,
    )
