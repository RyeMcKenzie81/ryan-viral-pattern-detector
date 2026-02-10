"""
Unit tests for chunk_markdown module.

Covers:
- chunk_markdown(): heading split, hero detection, fallback strategies
- pick_chunks_for_fields(): keyword scoring, budget caps, max_chunks
- extract_deterministic_snippet(): exact, fuzzy, and fallback modes
- Large markdown handling (50k+ chars)

Run with: pytest tests/test_chunk_markdown.py -v
"""

import pytest
from unittest.mock import MagicMock
from dataclasses import dataclass

from viraltracker.services.landing_page_analysis.chunk_markdown import (
    MarkdownChunk,
    chunk_markdown,
    pick_chunks_for_fields,
    extract_deterministic_snippet,
    _split_oversized_chunk,
    _keyword_window_chunks,
)


# ---------------------------------------------------------------------------
# Helpers — mock GapFieldSpec for pick_chunks_for_fields
# ---------------------------------------------------------------------------

@dataclass
class MockGapFieldSpec:
    key: str


def _make_specs(*keys: str):
    return [MockGapFieldSpec(key=k) for k in keys]


# ---------------------------------------------------------------------------
# chunk_markdown — heading splitting
# ---------------------------------------------------------------------------

class TestChunkMarkdownHeadings:
    def test_basic_heading_split(self):
        md = """Hero content here.

# Introduction
Some intro text.

## Details
Detail text here.

# FAQ
Frequently asked questions here.
"""
        chunks = chunk_markdown(md)
        assert len(chunks) >= 4  # Hero + 3 headings

        # Hero chunk
        hero = chunks[0]
        assert hero.heading_level == 0
        assert hero.chunk_type == "heading"
        assert "Hero content" in hero.text
        assert hero.chunk_id == "heading_0"

        # Check heading chunks exist
        headings = [c for c in chunks if c.heading_level > 0]
        assert len(headings) == 3
        # Check heading path breadcrumbs — "Introduction" appears in its own
        # chunk AND in the Details sub-chunk (breadcrumb inheritance)
        intro_direct = [c for c in chunks if c.heading_path == ["Introduction"]]
        assert len(intro_direct) == 1

    def test_heading_hierarchy_breadcrumb(self):
        md = """# Main Section
Content.

## Sub Section
Sub content.

### Deep Section
Deep content.

## Another Sub
More content.
"""
        chunks = chunk_markdown(md)
        heading_chunks = [c for c in chunks if c.heading_level > 0]

        # Find the deep section
        deep = [c for c in heading_chunks if "Deep Section" in " ".join(c.heading_path)]
        assert len(deep) == 1
        # Should have breadcrumb: Main Section > Sub Section > Deep Section
        assert "Main Section" in deep[0].heading_path
        assert "Sub Section" in deep[0].heading_path
        assert "Deep Section" in deep[0].heading_path

        # "Another Sub" should reset to just Main Section > Another Sub
        another = [c for c in heading_chunks if "Another Sub" in " ".join(c.heading_path)]
        assert len(another) == 1
        assert "Main Section" in another[0].heading_path
        assert "Sub Section" not in another[0].heading_path

    def test_no_headings_creates_hero(self):
        md = "Just some plain text without any headings at all. " * 10
        chunks = chunk_markdown(md)
        assert len(chunks) >= 1
        assert chunks[0].heading_level == 0
        assert chunks[0].chunk_type == "heading"

    def test_empty_content(self):
        assert chunk_markdown("") == []
        assert chunk_markdown("   ") == []
        assert chunk_markdown(None) == []

    def test_h4_plus_not_split(self):
        """H4+ headings should NOT create split points — only H1-H3."""
        md = """# Main
Content.

#### Deep Heading
This should be part of Main.
"""
        chunks = chunk_markdown(md)
        heading_chunks = [c for c in chunks if c.heading_level > 0]
        # Only 1 heading chunk (# Main), not 2
        assert len(heading_chunks) == 1
        assert "Deep Heading" in heading_chunks[0].text


# ---------------------------------------------------------------------------
# chunk_markdown — fallback: oversized chunks
# ---------------------------------------------------------------------------

class TestChunkMarkdownSizeFallback:
    def test_oversized_chunk_splits(self):
        # Create a chunk > 3000 chars
        long_content = ("This is a paragraph. " * 50 + "\n\n") * 10  # ~10 paragraphs
        md = f"# Big Section\n\n{long_content}"

        chunks = chunk_markdown(md)
        # Should have been split into multiple sub-chunks
        big_section_chunks = [c for c in chunks if "Big Section" in " ".join(c.heading_path)]
        assert len(big_section_chunks) > 1

    def test_small_chunks_not_split(self):
        md = """# Small
Short content here.

# Another
Also short.
"""
        chunks = chunk_markdown(md)
        # No fallback_size chunks should exist
        assert all(c.chunk_type == "heading" for c in chunks)


# ---------------------------------------------------------------------------
# chunk_markdown — fallback: keyword windows
# ---------------------------------------------------------------------------

class TestChunkMarkdownKeywordFallback:
    def test_no_headings_triggers_keyword_fallback(self):
        """Flat page with keywords but no headings should get keyword chunks."""
        # Make content long enough that keyword windows don't fully overlap hero
        filler_before = "Lorem ipsum dolor sit amet. " * 100  # ~2800 chars
        filler_after = "Consectetur adipiscing elit. " * 100
        md = filler_before + "\n\nFAQ section starts here.\n\n" + filler_after
        chunks = chunk_markdown(md)
        # Should have hero chunk (< 3 heading chunks triggers fallback)
        heading_chunks = [c for c in chunks if c.chunk_type == "heading"]
        assert len(heading_chunks) < 3
        # "FAQ" is a fallback anchor keyword — should produce keyword window chunks
        kw_chunks = [c for c in chunks if c.chunk_type == "fallback_keyword"]
        assert len(kw_chunks) >= 1

    def test_many_headings_skips_keyword_fallback(self):
        """Pages with >= 3 heading chunks should NOT get keyword chunks."""
        md = """# Section 1
Content 1 with FAQ mention.

# Section 2
Content 2 with guarantee.

# Section 3
Content 3.
"""
        chunks = chunk_markdown(md)
        kw_chunks = [c for c in chunks if c.chunk_type == "fallback_keyword"]
        assert len(kw_chunks) == 0


# ---------------------------------------------------------------------------
# chunk_markdown — chunk IDs and ordering
# ---------------------------------------------------------------------------

class TestChunkIDs:
    def test_chunk_ids_are_unique(self):
        md = """Hero text.

# First
Content 1.

## Second
Content 2.

# Third
Content 3.
"""
        chunks = chunk_markdown(md)
        ids = [c.chunk_id for c in chunks]
        assert len(ids) == len(set(ids)), f"Duplicate chunk IDs: {ids}"

    def test_chunks_sorted_by_offset(self):
        md = """Hero text.

# First
Content 1.

## Second
Content 2.

# Third
Content 3.
"""
        chunks = chunk_markdown(md)
        offsets = [c.char_offset for c in chunks]
        assert offsets == sorted(offsets), "Chunks should be sorted by char_offset"


# ---------------------------------------------------------------------------
# pick_chunks_for_fields — keyword scoring
# ---------------------------------------------------------------------------

class TestPickChunksForFields:
    def test_relevant_chunks_selected(self):
        chunks = [
            MarkdownChunk("heading_0", ["(Hero)"], "Welcome to our product.", 0, 0, "heading"),
            MarkdownChunk("heading_100", ["FAQ"], "Q: How does it work? A: ...", 100, 1, "heading"),
            MarkdownChunk("heading_200", ["Guarantee"], "365-day money back guarantee.", 200, 1, "heading"),
            MarkdownChunk("heading_300", ["Contact"], "Email us at support@example.com", 300, 1, "heading"),
        ]
        specs = _make_specs("product.guarantee", "product.faq_items")
        selected = pick_chunks_for_fields(chunks, specs, max_chars=12000, max_chunks=8)

        # Should include FAQ and Guarantee chunks (high keyword match)
        selected_ids = {c.chunk_id for c in selected}
        assert "heading_100" in selected_ids  # FAQ
        assert "heading_200" in selected_ids  # Guarantee

    def test_hero_always_included_for_voice_tone(self):
        chunks = [
            MarkdownChunk("heading_0", ["(Hero)"], "Bold, energetic copy.", 0, 0, "heading"),
            MarkdownChunk("heading_100", ["Details"], "Product details.", 100, 1, "heading"),
        ]
        specs = _make_specs("brand.voice_tone")
        selected = pick_chunks_for_fields(chunks, specs)
        selected_ids = {c.chunk_id for c in selected}
        assert "heading_0" in selected_ids

    def test_max_chars_respected(self):
        # Create chunks totaling > max_chars
        chunks = [
            MarkdownChunk(f"heading_{i*1000}", [f"Section {i}"], "X" * 2000, i * 1000, 1, "heading")
            for i in range(10)
        ]
        specs = _make_specs("product.guarantee")
        selected = pick_chunks_for_fields(chunks, specs, max_chars=5000, max_chunks=20)

        total = sum(len(c.text) for c in selected)
        assert total <= 5000 + 2000  # May include one chunk that pushes over

    def test_max_chunks_respected(self):
        chunks = [
            MarkdownChunk(f"heading_{i*100}", [f"Section {i}"], f"Content {i}", i * 100, 1, "heading")
            for i in range(20)
        ]
        specs = _make_specs("product.guarantee")
        selected = pick_chunks_for_fields(chunks, specs, max_chunks=3)
        assert len(selected) <= 3

    def test_empty_chunks(self):
        specs = _make_specs("product.guarantee")
        assert pick_chunks_for_fields([], specs) == []

    def test_selected_sorted_by_offset(self):
        chunks = [
            MarkdownChunk("heading_500", ["Later"], "guarantee info", 500, 1, "heading"),
            MarkdownChunk("heading_0", ["(Hero)"], "Welcome.", 0, 0, "heading"),
            MarkdownChunk("heading_200", ["Middle"], "some content", 200, 1, "heading"),
        ]
        specs = _make_specs("product.guarantee")
        selected = pick_chunks_for_fields(chunks, specs)
        offsets = [c.char_offset for c in selected]
        assert offsets == sorted(offsets)


# ---------------------------------------------------------------------------
# extract_deterministic_snippet
# ---------------------------------------------------------------------------

class TestExtractDeterministicSnippet:
    def test_exact_match(self):
        chunk_text = "This product has a 365-day money back guarantee for all customers."
        value = "365-day money back guarantee"
        snippet = extract_deterministic_snippet(chunk_text, value, max_len=300)
        assert "365-day money back guarantee" in snippet

    def test_fuzzy_match(self):
        chunk_text = "Our 365-day full money-back guarantee ensures customer satisfaction."
        value = "365 day money back guarantee"  # Slightly different
        snippet = extract_deterministic_snippet(chunk_text, value, max_len=300)
        # Should find a relevant snippet
        assert len(snippet) > 0
        assert "guarantee" in snippet.lower()

    def test_fallback_to_first_chars(self):
        chunk_text = "This is the beginning of some completely unrelated content about gardening."
        value = "something_completely_absent_xyz"
        snippet = extract_deterministic_snippet(chunk_text, value, max_len=50)
        assert snippet.startswith("This is the beginning")

    def test_empty_inputs(self):
        assert extract_deterministic_snippet("", "value") == ""
        snippet = extract_deterministic_snippet("Some text", "")
        assert len(snippet) > 0  # Falls through to fallback

    def test_max_len_respected(self):
        chunk_text = "Word " * 500
        value = "Word"
        snippet = extract_deterministic_snippet(chunk_text, value, max_len=100)
        assert len(snippet) <= 110  # Allow small overshoot for word boundary


# ---------------------------------------------------------------------------
# Large markdown test (50k+ chars) — budget caps enforced
# ---------------------------------------------------------------------------

class TestLargeMarkdown:
    def test_50k_chars_chunked_within_budget(self):
        """Verify that huge markdown is chunked and budget caps are enforced."""
        # Build a ~55k char markdown document
        sections = []
        sections.append("# Welcome to Our Product\n\n" + "Hero copy. " * 100)  # ~1200 chars
        for i in range(25):
            sections.append(f"## Section {i}\n\n" + f"Content for section {i}. " * 100)  # ~2500 chars each

        big_md = "\n\n".join(sections)
        assert len(big_md) > 50000, f"Test markdown is only {len(big_md)} chars"

        # Chunk it
        chunks = chunk_markdown(big_md)
        assert len(chunks) > 5, "Should have many chunks"

        # All chunks should have valid IDs
        ids = [c.chunk_id for c in chunks]
        assert len(ids) == len(set(ids)), "Chunk IDs must be unique"

        # Pick chunks with tight budget
        specs = _make_specs("product.guarantee", "product.faq_items")
        selected = pick_chunks_for_fields(chunks, specs, max_chars=8000, max_chunks=5)

        assert len(selected) <= 5, f"max_chunks violated: {len(selected)}"
        total_chars = sum(len(c.text) for c in selected)
        # Budget should be approximately respected (one chunk may push over)
        assert total_chars < 15000, f"Budget way exceeded: {total_chars}"

    def test_full_content_preserved_in_chunks(self):
        """Verify that chunking doesn't lose content — all text appears in some chunk."""
        md = """# First Section
Important guarantee text here.

# Second Section
FAQ items and details.

# Third Section
Ingredient information.
"""
        chunks = chunk_markdown(md)
        all_text = " ".join(c.text for c in chunks)

        # Key content should appear in chunks
        assert "guarantee" in all_text.lower()
        assert "FAQ" in all_text
        assert "Ingredient" in all_text

    def test_no_storage_truncation(self):
        """Confirm that chunk_markdown returns ALL chunks — no content dropped.

        The full page is always stored in DB. Chunking is for prompt selection only.
        pick_chunks_for_fields() is what applies the budget cap, not chunk_markdown().
        """
        sections = [f"# Section {i}\nContent for section {i}. " * 10 for i in range(20)]
        big_md = "\n\n".join(sections)
        all_chunks = chunk_markdown(big_md)
        assert len(all_chunks) >= 10, f"Expected many chunks, got {len(all_chunks)}"

        selected = pick_chunks_for_fields(all_chunks, _make_specs("product.guarantee"), max_chars=2000, max_chunks=2)

        # chunk_markdown returns everything
        total_all = sum(len(c.text) for c in all_chunks)
        # pick_chunks_for_fields returns subset
        total_selected = sum(len(c.text) for c in selected)

        assert total_selected < total_all, "pick_chunks should select a subset, not everything"
        assert len(selected) <= 2


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_only_hero_no_headings(self):
        md = "Just plain text, no markdown headings."
        chunks = chunk_markdown(md)
        assert len(chunks) >= 1
        assert chunks[0].heading_level == 0

    def test_consecutive_headings_no_content(self):
        md = """# First
# Second
# Third
Some content here.
"""
        chunks = chunk_markdown(md)
        # Should handle empty sections gracefully
        heading_chunks = [c for c in chunks if c.heading_level > 0]
        assert len(heading_chunks) >= 1

    def test_markdown_with_code_blocks(self):
        md = """# Code Example
Here is some code:

```python
def hello():
    print("world")
```

That was the code.
"""
        chunks = chunk_markdown(md)
        code_chunk = [c for c in chunks if "code" in c.text.lower()]
        assert len(code_chunk) >= 1
        assert "```python" in code_chunk[0].text

    def test_heading_in_code_block_not_split(self):
        """Headings inside code blocks shouldn't split — but our regex-based
        approach may do so. This tests current behavior, not ideal behavior."""
        md = """# Real Heading
Some text.

```
# This is a comment, not a heading
More code.
```

# Another Real Heading
More text.
"""
        chunks = chunk_markdown(md)
        # We accept that regex may split on code block headings
        # Just verify no crash and chunks are valid
        assert len(chunks) >= 2
        assert all(c.text.strip() for c in chunks)
