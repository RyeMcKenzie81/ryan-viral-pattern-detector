"""
Markdown chunking for LLM prompt construction.

Splits landing page markdown into semantic chunks by headings, then selects
the most relevant chunks for target extraction fields using keyword scoring.

IMPORTANT: This module handles LLM prompt budgets, NOT storage limits.
The full page content is always stored in the DB — these functions only
select what the LLM sees.
"""

import hashlib
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple


@dataclass
class MarkdownChunk:
    """A semantic chunk of markdown content."""
    chunk_id: str             # Stable ID: "{chunk_type}_{char_offset}"
    heading_path: List[str]   # Breadcrumb from H1 down: ["How It Works", "The Science"]
    text: str                 # Chunk content
    char_offset: int          # Offset in original markdown
    heading_level: int        # 0=hero (before first heading), 1=H1, 2=H2, etc.
    chunk_type: str           # "heading" | "fallback_size" | "fallback_keyword"


# ---------------------------------------------------------------------------
# Keyword config for field-to-chunk matching
# ---------------------------------------------------------------------------

FIELD_KEYWORDS: Dict[str, List[str]] = {
    "product.guarantee": [
        "guarantee", "refund", "money back", "risk free", "risk-free",
        "return policy", "day money", "satisfaction",
    ],
    "product.faq_items": [
        "faq", "frequently asked", "questions", "q&a", "q & a",
        "common questions",
    ],
    "product.ingredients": [
        "ingredients", "formula", "contains", "active", "supplement facts",
        "key ingredients", "what's inside", "formulated",
    ],
    "offer_variant.mechanism.name": [
        "how it works", "science", "mechanism", "why it works",
        "the process", "technology", "method",
    ],
    "offer_variant.mechanism.root_cause": [
        "how it works", "science", "mechanism", "why it works",
        "root cause", "problem", "the real reason",
    ],
    "product.results_timeline": [
        "results", "expect", "timeline", "day", "week", "month",
        "before and after", "how long", "when will",
    ],
    "offer_variant.pain_points": [
        "problem", "struggle", "suffer", "tired of", "frustrated",
        "pain", "challenge", "difficulty", "symptom",
    ],
    "brand.voice_tone": [],  # Uses hero + opening chunks — no keyword match needed
}

# Keywords used for fallback window chunking when headings are sparse
_FALLBACK_ANCHOR_KEYWORDS = [
    "faq", "frequently asked", "guarantee", "refund", "money back",
    "ingredients", "supplement facts", "how it works", "results",
    "testimonial", "review", "pricing", "order now", "buy now",
]

# Always-include keywords for hero/offer chunks
_ALWAYS_INCLUDE_KEYWORDS = [
    "pricing", "offer", "buy now", "order now", "add to cart",
    "special offer", "limited time",
]


def chunk_markdown(raw_content: str) -> List[MarkdownChunk]:
    """Split markdown by headings into semantic chunks.

    Primary strategy: Split on H1-H3 headings. Preserves heading hierarchy
    as breadcrumb. Hero content (before first heading) gets its own chunk.

    Fallback strategies (applied to any chunk > 3000 chars or when headings
    are sparse):
    1. Size-based splitting: Break oversized chunks at paragraph boundaries
       (~1500 chars) with 200-char overlap to avoid splitting mid-thought.
    2. Keyword-window chunks: If the entire page has < 3 heading chunks,
       also scan for keyword anchors and create window chunks (500 chars
       before + 1000 chars after the keyword match).

    Args:
        raw_content: Full markdown text of the page.

    Returns:
        List of MarkdownChunk objects, ordered by char_offset.
    """
    if not raw_content or not raw_content.strip():
        return []

    # --- Primary: split on headings ---
    heading_pattern = re.compile(r'^(#{1,3})\s+(.+)$', re.MULTILINE)
    matches = list(heading_pattern.finditer(raw_content))

    chunks: List[MarkdownChunk] = []
    heading_stack: List[Tuple[int, str]] = []  # (level, text)

    if not matches:
        # No headings at all — entire content is hero
        hero_text = raw_content.strip()
        if hero_text:
            chunks.append(MarkdownChunk(
                chunk_id="heading_0",
                heading_path=["(Hero)"],
                text=hero_text,
                char_offset=0,
                heading_level=0,
                chunk_type="heading",
            ))
    else:
        # Hero content before first heading
        first_heading_pos = matches[0].start()
        hero_text = raw_content[:first_heading_pos].strip()
        if hero_text:
            chunks.append(MarkdownChunk(
                chunk_id="heading_0",
                heading_path=["(Hero)"],
                text=hero_text,
                char_offset=0,
                heading_level=0,
                chunk_type="heading",
            ))

        # Split by headings
        for i, match in enumerate(matches):
            level = len(match.group(1))  # Number of # chars
            heading_text = match.group(2).strip()
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(raw_content)

            # Update heading stack for breadcrumb
            # Pop any headings at same or lower level
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, heading_text))

            heading_path = [h[1] for h in heading_stack]
            chunk_text = raw_content[start:end].strip()

            if chunk_text:
                chunks.append(MarkdownChunk(
                    chunk_id=f"heading_{start}",
                    heading_path=heading_path,
                    text=chunk_text,
                    char_offset=start,
                    heading_level=level,
                    chunk_type="heading",
                ))

    # --- Fallback 1: Size-based splitting for oversized chunks ---
    split_chunks: List[MarkdownChunk] = []
    for chunk in chunks:
        if len(chunk.text) > 3000:
            sub_chunks = _split_oversized_chunk(chunk)
            split_chunks.extend(sub_chunks)
        else:
            split_chunks.append(chunk)

    # --- Fallback 2: Keyword-window chunks if headings are sparse ---
    heading_chunks = [c for c in split_chunks if c.chunk_type == "heading"]
    if len(heading_chunks) < 3:
        kw_chunks = _keyword_window_chunks(raw_content, split_chunks)
        split_chunks.extend(kw_chunks)

    # Sort by char_offset for consistent ordering
    split_chunks.sort(key=lambda c: c.char_offset)

    return split_chunks


def _split_oversized_chunk(chunk: MarkdownChunk) -> List[MarkdownChunk]:
    """Split a chunk > 3000 chars at paragraph boundaries with overlap."""
    text = chunk.text
    target_size = 1500
    overlap = 200

    # Split on double newlines (paragraph boundaries)
    paragraphs = re.split(r'\n\n+', text)

    sub_chunks: List[MarkdownChunk] = []
    current_text = ""
    current_start = chunk.char_offset

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        if current_text and len(current_text) + len(para) + 2 > target_size:
            # Emit current chunk
            sub_chunks.append(MarkdownChunk(
                chunk_id=f"fallback_size_{current_start}",
                heading_path=chunk.heading_path,
                text=current_text,
                char_offset=current_start,
                heading_level=chunk.heading_level,
                chunk_type="fallback_size",
            ))
            # Start new chunk with overlap
            overlap_text = current_text[-overlap:] if len(current_text) > overlap else current_text
            current_text = overlap_text + "\n\n" + para
            # Approximate offset
            current_start = chunk.char_offset + text.find(para, current_start - chunk.char_offset)
        else:
            if current_text:
                current_text += "\n\n" + para
            else:
                current_text = para

    # Emit remaining
    if current_text.strip():
        sub_chunks.append(MarkdownChunk(
            chunk_id=f"fallback_size_{current_start}",
            heading_path=chunk.heading_path,
            text=current_text,
            char_offset=current_start,
            heading_level=chunk.heading_level,
            chunk_type="fallback_size",
        ))

    return sub_chunks if sub_chunks else [chunk]


def _keyword_window_chunks(
    full_text: str,
    existing_chunks: List[MarkdownChunk],
) -> List[MarkdownChunk]:
    """Create window chunks around keyword anchors for flat/headingless pages."""
    kw_chunks: List[MarkdownChunk] = []
    text_lower = full_text.lower()

    # Track existing chunk coverage to avoid heavy overlap
    covered_ranges = [(c.char_offset, c.char_offset + len(c.text)) for c in existing_chunks]

    for keyword in _FALLBACK_ANCHOR_KEYWORDS:
        idx = 0
        while True:
            pos = text_lower.find(keyword, idx)
            if pos == -1:
                break

            window_start = max(0, pos - 500)
            window_end = min(len(full_text), pos + 1000)

            # Skip if heavily overlapping with existing chunk
            overlaps = False
            for (cs, ce) in covered_ranges:
                overlap = min(window_end, ce) - max(window_start, cs)
                if overlap > 0.7 * (window_end - window_start):
                    overlaps = True
                    break

            if not overlaps:
                window_text = full_text[window_start:window_end].strip()
                if window_text:
                    kw_chunks.append(MarkdownChunk(
                        chunk_id=f"kw_{window_start}",
                        heading_path=[f"(Keyword: {keyword})"],
                        text=window_text,
                        char_offset=window_start,
                        heading_level=0,
                        chunk_type="fallback_keyword",
                    ))
                    covered_ranges.append((window_start, window_end))

            idx = pos + len(keyword)

    return kw_chunks


def pick_chunks_for_fields(
    chunks: List[MarkdownChunk],
    field_specs: List["GapFieldSpec"],
    max_chars: int = 12000,
    max_chunks: int = 8,
) -> List[MarkdownChunk]:
    """Select the most relevant chunks for the target fields.

    Scores each chunk against target fields using keyword matching, then
    returns top chunks up to BOTH max_chars total AND max_chunks count
    (whichever limit hits first).

    Always includes: hero chunk, pricing/offer chunks.

    Args:
        chunks: All chunks from chunk_markdown().
        field_specs: Target fields to extract (GapFieldSpec objects).
        max_chars: Maximum total characters across selected chunks.
        max_chunks: Maximum number of chunks to select.

    Returns:
        Selected chunks ordered by char_offset.
    """
    if not chunks:
        return []

    # Gather all keywords for the target fields
    target_keys = {spec.key for spec in field_specs}
    all_keywords: List[str] = []
    for key in target_keys:
        all_keywords.extend(FIELD_KEYWORDS.get(key, []))
    # Add always-include keywords
    all_keywords.extend(_ALWAYS_INCLUDE_KEYWORDS)

    # Score each chunk
    scored: List[Tuple[float, int, MarkdownChunk]] = []
    for i, chunk in enumerate(chunks):
        score = _score_chunk(chunk, all_keywords, target_keys)
        scored.append((score, i, chunk))

    # Sort by score descending, break ties by original order
    scored.sort(key=lambda x: (-x[0], x[1]))

    # Select top chunks within budget
    selected: List[MarkdownChunk] = []
    total_chars = 0

    for score, _idx, chunk in scored:
        if len(selected) >= max_chunks:
            break
        chunk_len = len(chunk.text)
        if total_chars + chunk_len > max_chars and selected:
            # Already have some chunks and this would exceed budget
            continue
        selected.append(chunk)
        total_chars += chunk_len

    # Sort selected by char_offset for document order
    selected.sort(key=lambda c: c.char_offset)

    return selected


def _score_chunk(
    chunk: MarkdownChunk,
    keywords: List[str],
    target_keys: set,
) -> float:
    """Score a chunk's relevance to the target fields."""
    score = 0.0
    text_lower = chunk.text.lower()
    heading_lower = " ".join(chunk.heading_path).lower()

    # Hero chunk bonus (voice/tone lives here)
    if chunk.heading_level == 0 and chunk.chunk_type == "heading":
        score += 3.0
        # Extra bonus if voice_tone is a target
        if "brand.voice_tone" in target_keys:
            score += 2.0

    # Keyword matches in heading (high signal)
    for kw in keywords:
        if kw in heading_lower:
            score += 5.0

    # Keyword matches in text body
    for kw in keywords:
        count = text_lower.count(kw)
        if count > 0:
            # Diminishing returns for repeated keywords
            score += min(count, 3) * 1.0

    # Penalize very short chunks (< 100 chars) — likely nav or footer
    if len(chunk.text) < 100:
        score *= 0.3

    # Penalize very long chunks slightly (prefer focused content)
    if len(chunk.text) > 2500:
        score *= 0.9

    return score


def extract_deterministic_snippet(
    chunk_text: str,
    extracted_value: str,
    max_len: int = 300,
) -> str:
    """Extract a deterministic snippet from chunk text near the extracted value.

    Fallback chain:
    1. Exact match: Find value verbatim → extract surrounding window
    2. Fuzzy match: Use SequenceMatcher to find best-matching window (ratio > 0.5)
    3. Fallback: First max_len chars of the chunk

    Args:
        chunk_text: Full text of the chunk.
        extracted_value: The value extracted by the LLM.
        max_len: Maximum snippet length.

    Returns:
        A deterministic excerpt from the chunk text.
    """
    if not chunk_text:
        return ""

    value_str = str(extracted_value) if extracted_value else ""

    # 1. Exact match
    if value_str and value_str in chunk_text:
        pos = chunk_text.find(value_str)
        window_start = max(0, pos - max_len // 4)
        window_end = min(len(chunk_text), pos + len(value_str) + max_len * 3 // 4)
        snippet = chunk_text[window_start:window_end].strip()
        if len(snippet) > max_len:
            snippet = snippet[:max_len].rsplit(" ", 1)[0] + "..."
        return snippet

    # 2. Fuzzy match — slide a window across chunk_text
    if value_str and len(value_str) > 10:
        best_ratio = 0.0
        best_pos = 0
        window_size = min(len(value_str) * 2, len(chunk_text))
        step = max(1, window_size // 4)

        for start in range(0, max(1, len(chunk_text) - window_size + 1), step):
            window = chunk_text[start:start + window_size]
            ratio = SequenceMatcher(None, value_str.lower(), window.lower()).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_pos = start

        if best_ratio > 0.5:
            window_start = max(0, best_pos - max_len // 4)
            window_end = min(len(chunk_text), best_pos + window_size + max_len // 4)
            snippet = chunk_text[window_start:window_end].strip()
            if len(snippet) > max_len:
                snippet = snippet[:max_len].rsplit(" ", 1)[0] + "..."
            return snippet

    # 3. Fallback: first max_len chars
    snippet = chunk_text[:max_len].strip()
    if len(chunk_text) > max_len:
        snippet = snippet.rsplit(" ", 1)[0] + "..." if " " in snippet else snippet + "..."
    return snippet
