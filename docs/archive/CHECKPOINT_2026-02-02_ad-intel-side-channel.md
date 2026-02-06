# Checkpoint: Ad Intelligence Side-Channel Bypass

**Date**: 2026-02-02
**Branch**: `feat/veo-avatar-tool`
**Commits**: `8f4ff5b`, `9cf0d17`

## Problem Solved

Two LLM layers (sub-agent + orchestrator) were paraphrasing the ChatRenderer's structured markdown before reaching the user. This caused:

1. **Data corruption** — LLM said "6 ads with CPC over $79.58" when $79.58 is the baseline, not actual CPC (~$2)
2. **Stripped details** — ad IDs, recommendation IDs, `/rec_done` commands got removed
3. **System prompt unreliable** — "output verbatim" instructions didn't work consistently

## Solution: result_cache Side-Channel

Tools store ChatRenderer markdown in `result_cache.custom["ad_intelligence_result"]`, bypassing both LLM layers. The UI reads the side-channel directly.

```
Tool stores markdown in result_cache.custom ──→ UI reads it directly
         │                                          ↑
         ↓                                          │
   Sub-agent LLM paraphrases (ignored)              │
         ↓                                          │
   Orchestrator LLM paraphrases (ignored) ──────────┘
```

### Files Modified

| File | Change |
|------|--------|
| `viraltracker/agent/agents/ad_intelligence_agent.py` | All 8 tools store rendered markdown in side-channel before returning |
| `viraltracker/agent/orchestrator.py` | `route_to_ad_intelligence_agent` clears stale side-channel, returns cached markdown |
| `viraltracker/ui/pages/00_🎯_Agent_Chat.py` | Checks side-channel after agent.run(), replaces LLM output if present |
| `docs/TECH_DEBT.md` | Added #8: CPC baseline per-row daily value issue |

### Pattern Used

Each ad intelligence tool:
```python
rendered = ChatRenderer.render_xxx(result)
ctx.deps.result_cache.custom["ad_intelligence_result"] = {
    "tool_name": "xxx",
    "rendered_markdown": rendered,
}
return rendered  # Still returned to LLM for follow-up context
```

Orchestrator returns cached markdown to bypass sub-agent paraphrase:
```python
ctx.deps.result_cache.custom.pop("ad_intelligence_result", None)
result = await ad_intelligence_agent.run(query, deps=ctx.deps)
cached = ctx.deps.result_cache.custom.get("ad_intelligence_result")
if cached and "rendered_markdown" in cached:
    return cached["rendered_markdown"]
return result.output
```

UI replaces orchestrator paraphrase with side-channel:
```python
ad_intel = st.session_state.deps.result_cache.custom.get("ad_intelligence_result")
if ad_intel and ad_intel.get("rendered_markdown"):
    display_content = ad_intel["rendered_markdown"]
else:
    display_content = full_response
```

## Streaming Attempted and Reverted

`agent.run_stream()` was implemented but broke tool execution. The pydantic-ai streaming API treats the first text output as the final result — when the orchestrator generates text ("I'll route this...") AND a tool call, the text is captured as "done" and the tool call result is never surfaced. Confirmed via logfire: the analysis pipeline ran successfully in the background but the UI only showed the streamed introductory text.

**Reverted to `agent.run()`** (blocking with `st.spinner()`). Streaming is incompatible with the orchestrator's tool-calling pattern in pydantic-ai 1.18.0.

## Known Remaining Issues

### 1. Healthy Ad IDs Not Shown
ChatRenderer renders healthy ads as a **count** only ("Healthy: 11 ads"), not listing their IDs. Follow-up questions like "show me the healthy ad IDs" get placeholder responses from the LLM because the data isn't in the context.

**Fix needed**: ChatRenderer should include healthy ad IDs in the rendered output.

### 2. Ad ID Truncation
ChatRenderer truncates ad ID lists to 5 items with "+X more". For follow-up questions about specific ads, the LLM can't reference truncated IDs.

### 3. CPC Baseline Inflated (Tech Debt #8)
Baseline service uses per-row daily `link_cpc` from Meta. Low-volume days inflate p75 (e.g., $79.58). Diagnostic engine uses correct aggregate CPC. Tracked in `docs/TECH_DEBT.md`.

## Test Results

- Side-channel: Working — initial analysis shows exact ChatRenderer markdown with ad IDs, rec IDs, `/rec_done` commands
- Brand context persistence: Working — follow-up queries use cached brand context
- Non-ad-intelligence queries: Unaffected — normal path works as before
- Streaming: Reverted — incompatible with tool-calling orchestrator pattern
