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
    image_count: int = 0


@dataclass
class PipelineInvariants:
    """Full baseline captured after Phase 2."""
    global_slot_set: FrozenSet[str]
    global_tokens: List[str]
    section_count: int
    sections: Dict[str, SectionInvariant] = field(default_factory=dict)
    global_image_count: int = 0


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


_VOID_ELEMENTS = frozenset([
    'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
    'link', 'meta', 'param', 'source', 'track', 'wbr',
])


class _SectionParser(HTMLParser):
    """Parse HTML to extract per-section content.

    Tracks ANY tag with a data-section attribute (not just <section>),
    so <footer data-section="sec_7"> is parsed correctly.  Depth tracking
    counts only the *same tag type* that opened the section, so void
    elements (img, br, etc.) don't corrupt boundary detection.
    """

    def __init__(self):
        super().__init__()
        self.sections: Dict[str, str] = {}  # section_id -> inner HTML
        self._current_section: Optional[str] = None
        self._current_tag: Optional[str] = None  # tag type that opened section
        self._depth = 0
        self._parts: List[str] = []
        self._raw_parts: List[str] = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        section_id = attrs_dict.get('data-section')

        # Start tracking a new section on ANY tag with data-section,
        # but only if we're NOT already inside one.
        if section_id and self._current_section is None:
            self._current_section = section_id
            self._current_tag = tag
            self._depth = 1
            self._raw_parts = []
            return

        if self._current_section:
            # Only increment depth for the same tag type that opened
            # the section — void elements never get handle_endtag calls,
            # so counting them would cause depth to grow unbounded.
            if tag == self._current_tag:
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
            if tag == self._current_tag and self._depth == 1:
                self.sections[self._current_section] = ''.join(self._raw_parts)
                self._current_section = None
                self._current_tag = None
                self._depth = 0
                return
            if tag == self._current_tag:
                self._depth -= 1
            # Skip close-tag reconstruction for void elements (they have
            # no close tag in valid HTML; the parser may synthesize one).
            if tag not in _VOID_ELEMENTS:
                self._raw_parts.append(f'</{tag}>')

    def handle_startendtag(self, tag, attrs):
        """Handle self-closing tags like <img/> and <br/>."""
        if self._current_section:
            attr_str = ''
            for name, value in attrs:
                if value is not None:
                    attr_str += f' {name}="{value}"'
                else:
                    attr_str += f' {name}'
            self._raw_parts.append(f'<{tag}{attr_str}/>')

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
        image_count = len(re.findall(r'<img\b', section_html, re.IGNORECASE))
        sections[section_id] = SectionInvariant(
            section_id=section_id,
            slot_set=slots,
            normalized_tokens=tokens,
            char_count=len(section_html),
            image_count=image_count,
        )

    global_image_count = len(re.findall(r'<img\b', html, re.IGNORECASE))

    return PipelineInvariants(
        global_slot_set=global_slots,
        global_tokens=global_tokens,
        section_count=len(section_htmls),
        sections=sections,
        global_image_count=global_image_count,
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

    # Check image count increase (warning only — Phase 3 can legitimately add images)
    new_image_count = len(re.findall(r'<img\b', section_html, re.IGNORECASE))
    if new_image_count > expected.image_count:
        issues.append(
            f"Image count increased: {expected.image_count} -> {new_image_count}"
        )
        logger.warning(
            f"Section {section_id}: {new_image_count - expected.image_count} new images added"
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

    # Global image count (warning only — allow small variance)
    new_image_count = len(re.findall(r'<img\b', html, re.IGNORECASE))
    if new_image_count > baseline.global_image_count + 3:
        issues.append(
            f"Excessive new images: {baseline.global_image_count} -> {new_image_count}"
        )
        logger.warning(
            f"Global image count increased significantly: "
            f"{baseline.global_image_count} -> {new_image_count}"
        )

    section_count_ok = len(section_htmls) == baseline.section_count
    passed = not slot_loss and similarity >= TEXT_SIMILARITY_THRESHOLD and section_count_ok

    if not passed:
        logger.warning(f"Global invariant FAILED: {issues}")

    return InvariantReport(
        passed=passed,
        slot_loss=slot_loss,
        text_similarity=similarity,
        issues=issues,
    )


@dataclass
class SlotNestingViolation:
    """A single slot nesting violation."""
    slot_name: str
    tag: str
    violation_type: str  # SLOT_SPANS_SECTIONS, NESTED_SLOTS, DUPLICATE_SLOT
    severity: str        # ERROR or WARNING
    detail: str


@dataclass
class SlotNestingReport:
    """Result of slot nesting validation."""
    passed: bool
    violations: List[SlotNestingViolation] = field(default_factory=list)
    slots_stripped: List[str] = field(default_factory=list)


class _SlotNestingValidator(HTMLParser):
    """Single-pass O(n) validator for slot nesting invariants.

    Detects:
    - SLOT_SPANS_SECTIONS: a data-slot element contains a data-section child
    - NESTED_SLOTS: a data-slot element contains another data-slot element
    - DUPLICATE_SLOT: the same slot name appears on multiple elements
    """

    def __init__(self):
        super().__init__()
        # Stack of (tag, slot_name, depth) for open data-slot elements
        self._slot_stack: List[Tuple[str, str, int]] = []
        self._depth = 0
        self._seen_slots: Dict[str, int] = {}  # slot_name -> count
        self.violations: List[SlotNestingViolation] = []

    def handle_starttag(self, tag, attrs):
        # Void elements have no closing tag — don't change depth
        if tag in _VOID_ELEMENTS:
            return
        self._depth += 1
        attr_dict = dict(attrs)
        slot_name = attr_dict.get("data-slot")
        has_section = "data-section" in attr_dict

        # Check if we're inside a slot and hit a data-section
        if has_section and self._slot_stack:
            parent_tag, parent_slot, _ = self._slot_stack[-1]
            self.violations.append(SlotNestingViolation(
                slot_name=parent_slot,
                tag=parent_tag,
                violation_type="SLOT_SPANS_SECTIONS",
                severity="ERROR",
                detail=f"Slot '{parent_slot}' on <{parent_tag}> contains "
                       f"<{tag} data-section=\"{attr_dict.get('data-section', '')}\">"
            ))

        # Check for nested slots
        if slot_name and self._slot_stack:
            parent_tag, parent_slot, _ = self._slot_stack[-1]
            self.violations.append(SlotNestingViolation(
                slot_name=parent_slot,
                tag=parent_tag,
                violation_type="NESTED_SLOTS",
                severity="ERROR",
                detail=f"Slot '{parent_slot}' on <{parent_tag}> contains "
                       f"nested slot '{slot_name}' on <{tag}>"
            ))

        # Track slot entry
        if slot_name:
            self._slot_stack.append((tag, slot_name, self._depth))
            count = self._seen_slots.get(slot_name, 0) + 1
            self._seen_slots[slot_name] = count
            if count == 2:
                self.violations.append(SlotNestingViolation(
                    slot_name=slot_name,
                    tag=tag,
                    violation_type="DUPLICATE_SLOT",
                    severity="WARNING",
                    detail=f"Slot name '{slot_name}' appears on multiple elements"
                ))

    def handle_endtag(self, tag):
        if tag in _VOID_ELEMENTS:
            return
        # Pop slot stack if this closes the current slot element
        if self._slot_stack:
            stack_tag, _, stack_depth = self._slot_stack[-1]
            if tag == stack_tag and self._depth == stack_depth:
                self._slot_stack.pop()
        self._depth -= 1

    def handle_startendtag(self, tag, attrs):
        # Self-closing tags with data-slot still count for duplicate tracking
        attr_dict = dict(attrs)
        slot_name = attr_dict.get("data-slot")
        if slot_name:
            count = self._seen_slots.get(slot_name, 0) + 1
            self._seen_slots[slot_name] = count
            if count == 2:
                self.violations.append(SlotNestingViolation(
                    slot_name=slot_name,
                    tag=tag,
                    violation_type="DUPLICATE_SLOT",
                    severity="WARNING",
                    detail=f"Slot name '{slot_name}' appears on multiple elements"
                ))

    def finalize(self):
        """Handle unclosed tags remaining on the stack."""
        for tag, slot_name, _ in self._slot_stack:
            self.violations.append(SlotNestingViolation(
                slot_name=slot_name,
                tag=tag,
                violation_type="SLOT_SPANS_SECTIONS",
                severity="ERROR",
                detail=f"Slot '{slot_name}' on <{tag}> was never closed "
                       f"(likely wraps remaining page content)"
            ))
        self._slot_stack.clear()


def validate_slot_nesting(html: str) -> SlotNestingReport:
    """Validate that no data-slot element spans across data-section boundaries.

    Single-pass O(n) check using HTMLParser. Detects:
    - SLOT_SPANS_SECTIONS: slot wraps one or more sections (ERROR)
    - NESTED_SLOTS: slot inside another slot (ERROR)
    - DUPLICATE_SLOT: same slot name on multiple elements (WARNING)

    Args:
        html: HTML string with data-slot and data-section attributes.

    Returns:
        SlotNestingReport with pass/fail and violation details.
    """
    validator = _SlotNestingValidator()
    try:
        validator.feed(html)
    except Exception:
        pass
    validator.finalize()

    errors = [v for v in validator.violations if v.severity == "ERROR"]
    return SlotNestingReport(
        passed=len(errors) == 0,
        violations=validator.violations,
    )


def strip_violating_slots(html: str, report: SlotNestingReport) -> str:
    """Remove data-slot attributes from elements that have ERROR violations.

    Args:
        html: HTML string with data-slot attributes.
        report: SlotNestingReport from validate_slot_nesting().

    Returns:
        Cleaned HTML with violating data-slot attributes removed.
    """
    slots_to_strip = set()
    for v in report.violations:
        if v.severity == "ERROR":
            slots_to_strip.add(v.slot_name)

    if not slots_to_strip:
        return html

    stripped = []
    for slot_name in slots_to_strip:
        escaped = re.escape(slot_name)
        html = re.sub(
            rf'\s*data-slot="{escaped}"',
            '',
            html,
        )
        stripped.append(slot_name)

    logger.info(f"Stripped {len(stripped)} violating slot attrs: {stripped}")
    report.slots_stripped = stripped
    return html


# Resolve public aliases
tokenize_visible_text = _tokenize_visible_text
text_similarity = _text_similarity
extract_slots = _extract_slots
parse_sections = _parse_sections
