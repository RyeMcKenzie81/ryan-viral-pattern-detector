# Checkpoint: Chunked Blueprint Generation Fix

**Date:** 2026-02-10
**Status:** Complete
**Commits:** `7ff4b7f`, `0c960dd`, `64c7ba1`, `a05e043`

## Problem

Skill 5 reconstruction blueprint generation was failing consistently. The single LLM call generates ~20-25K output tokens (37 sections × ~450 tokens each), which caused two compounding failures:

1. **Token truncation:** `max_tokens` set too low → JSON cut off mid-string → `parse_llm_json()` fails with "Could not parse JSON from LLM response"
2. **Request timeout:** `max_tokens` set high enough → Anthropic's 10-minute hard limit for non-streaming requests → "Request timed out or interrupted" or "Streaming is required for operations >10 minutes"

These were confirmed via Logfire:
- `output_tokens=16384` exactly matching the cap (truncation)
- Anthropic timeout errors at 03:14 and 03:47 UTC on 2026-02-10

## Solution: 2-Call Chunked Streaming

### Architecture

Split generation into 2 sequential streaming LLM calls by page section:

| Call | Sections | Generates |
|------|----------|-----------|
| **Chunk 1** (top-of-funnel) | `above_the_fold`, `education_and_persuasion`, `product_reveal_and_features` | `strategy_summary` + sections for these elements |
| **Chunk 2** (bottom-of-funnel) | `social_proof`, `conversion_and_offer`, `closing_and_trust` | Remaining sections + `bonus_sections` + `content_needed_summary` + `metadata` |

Chunk 2 receives Chunk 1's `strategy_summary` as context for tone consistency. Results are merged into the final blueprint structure.

### Streaming

Each chunk uses `agent.run_stream()` (via new `run_agent_stream_with_tracking()`) instead of `agent.run()`. This keeps the HTTP connection alive via SSE, avoiding Anthropic's non-streaming timeout. Only blueprint generation uses streaming — all other agents remain non-streaming.

### Token Budget

Each chunk uses `max_tokens=32768` with `timeout=600`. Confirmed working: the successful generation produced 37 sections, 12 mapped, 2 need content in 727.6s.

## Files Changed

| File | Changes |
|------|---------|
| `viraltracker/services/landing_page_analysis/blueprint_service.py` | Added `_split_elements_into_chunks()`, `_build_chunk_user_prompt()`, `_run_blueprint_chunk()`, `_merge_blueprint_chunks()`. Rewrote `_run_reconstruction()` to orchestrate 2-call flow. Updated `generate_blueprint()` for 5-step progress and partial status support. |
| `viraltracker/services/agent_tracking.py` | Added `run_agent_stream_with_tracking()` (streaming variant), `_StreamResultCompat` wrapper class, `_track_stream_usage()` helper. |
| `viraltracker/ui/pages/33_🏗️_Landing_Page_Analyzer.py` | Updated progress from 4→5 steps. Added "partial" status icon to blueprint history. |

No changes to `prompts/reconstruction.py` — chunking instructions are in the user prompt only.

## Key Design Decisions

1. **Streaming only for blueprints:** `run_agent_stream_with_tracking()` is a separate function, not a modification of the existing `run_agent_with_tracking()`. This avoids affecting the chat app which had issues with streaming.

2. **`_StreamResultCompat` wrapper:** PydanticAI 1.18's `StreamedRunResult` has `await get_output()`, not `.output` like `AgentRunResult`. The wrapper captures output inside the `async with` block and exposes `.output` / `.usage()` matching the non-streaming interface.

3. **Metadata recomputed:** `_merge_blueprint_chunks()` recomputes all counts (total_sections, populated, partial, content_needed) from actual merged data rather than trusting the LLM's self-reported counts.

4. **Graceful degradation:** If chunk 2 fails, chunk 1's result is returned as a partial blueprint with `metadata.partial=True`. The UI marks this with "partial" status.

5. **Unknown sections balanced:** `_split_elements_into_chunks()` assigns unrecognized section names to whichever chunk is smaller, ensuring even distribution.

## Error Handling

- **Chunk 1 fails:** Exception propagates → blueprint marked "failed" (existing behavior)
- **Chunk 2 fails:** Returns partial from chunk 1 → blueprint marked "partial" with error in metadata
- **Usage tracking:** Fire-and-forget, non-fatal on failure (same as existing pattern)

## Observability (Logfire)

- Each chunk logged as `reconstruction_blueprint_chunk_1` / `reconstruction_blueprint_chunk_2` in usage tracking
- Diagnostic `logger.info` per chunk: char count, token usage, first/last 100 chars
- Chunking split logged: "Blueprint chunking: X elements in chunk 1, Y elements in chunk 2"
- Merge logged: "Blueprint merged: X sections + Y bonus, Z populated, W partial, V need content"

## Debugging Timeline

| Attempt | Error | Root Cause | Fix |
|---------|-------|------------|-----|
| Pre-chunking | Timeout / truncation | Single call too large | Split into 2 chunks |
| Commit `7ff4b7f` | Timeout at chunk 1 | Non-streaming 10min limit | Switch to `agent.run_stream()` |
| Commit `0c960dd` | `'StreamedRunResult' has no attribute 'output'` | PydanticAI 1.18 API difference | Use `await get_output()` + wrapper |
| Commit `64c7ba1` | JSON truncation again | `max_tokens=16384` too low for 3-section chunks | Increase to 32768 |
| Commit `a05e043` | **Success** | — | — |
