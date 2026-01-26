# Checkpoint 04: Phase 4 Usage Tracking Rollout

**Date**: 2026-01-26
**Status**: Core services instrumented

---

## Summary

Rolled out usage tracking to all major AI services that use GeminiService, VeoService, or OpenAI embeddings.

## Services Instrumented

| Service | Provider | Operations Tracked | Status |
|---------|----------|-------------------|--------|
| GeminiService | Google | generate_image, analyze_image, analyze_text, analyze_hook | ✅ |
| VeoService | Google | generate_video (seconds + cost) | ✅ |
| AvatarService | Google (via Gemini) | generate_avatar_image | ✅ |
| DocService | OpenAI | embed, embed_batch | ✅ |

## Pages Updated with Tracking Context

| Page | Services Used |
|------|---------------|
| Ad Creator | GeminiService |
| VEO Avatars | VeoService, AvatarService |
| Content Pipeline | GeminiService, DocService |
| Knowledge Base | DocService |

## Integration Points

- `AgentDependencies.create()` accepts `user_id` and `organization_id`
- Tracking context propagated to: GeminiService, DocService, ContentPipelineService
- UI pages call `get_current_organization_id()` and `get_current_user_id()`

## Not Yet Instrumented

| Service | Reason |
|---------|--------|
| BrandResearchService | Uses PydanticAI Agents (requires different approach) |
| ScriptGenerationService | Uses PydanticAI Agents |
| ComicService | Uses PydanticAI Agents |
| Other PydanticAI agents | Need to instrument agent calls, not just service calls |

### PydanticAI Tracking (Future Work)

PydanticAI has its own usage tracking mechanism. To track agent calls:
1. Use `result.usage()` after agent runs to get token counts
2. Or wrap agent runs with tracking middleware
3. This is a larger refactor - track as tech debt

---

## Org Filtering Added

The Ad Creator page also got org-based product filtering:
- Products now filtered by current user's organization
- No org = no products (security fix)
- Superuser "all" mode sees everything

---

## Files Changed

```
viraltracker/services/gemini_service.py      (tracking methods)
viraltracker/services/veo_service.py         (tracking methods)
viraltracker/services/avatar_service.py      (pass-through tracking)
viraltracker/services/knowledge_base/service.py (tracking methods)
viraltracker/services/usage_tracker.py       (core tracker)
viraltracker/agent/dependencies.py           (tracking context)
viraltracker/ui/pages/21_🎨_Ad_Creator.py    (org selector + filtering)
viraltracker/ui/pages/41_📝_Content_Pipeline.py (tracking context)
viraltracker/ui/pages/46_📚_Knowledge_Base.py (tracking context)
viraltracker/ui/pages/47_🎬_Veo_Avatars.py   (tracking context)
```

---

## Verification

Test by generating an ad or video, then run:

```sql
SELECT
    created_at,
    provider,
    model,
    tool_name,
    operation,
    input_tokens,
    output_tokens,
    units,
    unit_type,
    cost_usd
FROM token_usage
ORDER BY created_at DESC
LIMIT 20;
```

Expected records:
- `provider = 'google'`, `operation = 'generate_image'` (Ad Creator)
- `provider = 'google'`, `operation = 'generate_video'` (VEO)
- `provider = 'openai'`, `operation = 'embed'` or `'embed_batch'` (Knowledge Base)

---

## Next Steps

1. **Test all instrumented services** to verify tracking works
2. **Add org filtering to other pages** (Competitors, Brand Research, etc.)
3. **Instrument PydanticAI agents** (larger refactor, track as tech debt)
4. **Build usage dashboard** (Phase 4 Step 2)
