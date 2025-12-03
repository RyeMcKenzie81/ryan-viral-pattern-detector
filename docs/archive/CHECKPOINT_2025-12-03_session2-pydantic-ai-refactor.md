# CHECKPOINT: December 3, 2025 - Session 2

**Date**: December 3, 2025
**Status**: Complete

---

## Summary

This session focused on pydantic-ai best practices refactoring and attempting to fix Trustpilot badge issues in generated ads. The Trustpilot fix was ultimately reverted as the approach wasn't working well with Gemini's image generation.

---

## Commits This Session

| Commit | Description |
|--------|-------------|
| `a1f191d` | fix: Sanitize ad_analysis to remove unverified platform names from prompts |
| `cdb45f1` | refactor: Move sanitize_social_proof_mentions to service layer |
| `e866e01` | fix: Remove literal 'OMIT' text from social proof prompts |
| `b8c4aee` | docs: Add CLAUDE.md for Claude Code development guidelines |
| `22b7b2f` | fix: Simplify review badge prompt to single exact string |
| `1970614` | revert: Remove Trustpilot/social proof handling complexity |

---

## Key Changes

### 1. Pydantic-AI Best Practices Documentation

**Added "Thin Tools" pattern** to documentation based on ChatGPT deep research of pydantic-ai docs:

- **Tools** = LLM-decided orchestration (thin wrappers)
- **Services** = Business logic, deterministic preprocessing
- **deps_type** = Service container pattern

**Files updated:**
- `/docs/claude_code_guide.md` - Added "Service Layer Pattern (Thin Tools)" section
- `/docs/architecture.md` - Added "Thin Tools Principle" note

### 2. CLAUDE.md Created

Created `/CLAUDE.md` - automatically read by Claude Code at session start.

**Includes:**
- Development workflow (Plan → Implement → Document → Test → QA → Update Docs)
- Core architecture overview
- Pydantic-AI best practices
- Python workflow examples (services, tools, UI, migrations)
- Commit message format
- Task completion checklist

### 3. Trustpilot Handling (REVERTED)

**Problem:** Gemini was copying Trustpilot badges from reference templates even when instructed not to.

**Attempted solutions:**
1. Sanitize platform names from ad_analysis before sending to Gemini
2. Use "replacement" instructions instead of "prohibition"
3. Remove literal "OMIT" text that Gemini was writing
4. Simplify to single exact display string

**Outcome:** None of the approaches worked reliably. Gemini's image generation is too literal with reference images.

**Resolution:** Reverted all Trustpilot handling. User will avoid templates with Trustpilot/review badges for now.

---

## Technical Learnings

### Pydantic-AI Architecture

```
Tool vs Service Decision:
┌─────────────────────────────────────┬──────────┬─────────────┐
│ Question                            │ Yes →    │ No →        │
├─────────────────────────────────────┼──────────┼─────────────┤
│ Does LLM decide when to call this?  │ Tool     │ Service     │
│ Must always run (deterministic)?    │ Service  │ Could be OK │
│ Reusable across agents/interfaces?  │ Service  │ Tool OK     │
└─────────────────────────────────────┴──────────┴─────────────┘
```

### Image Generation Limitations

- Gemini tends to reproduce text/elements from reference images literally
- Text-based instructions ("don't do X") are often ignored for visual elements
- Sanitizing prompt text doesn't prevent visual copying from reference images
- Future solution may require image preprocessing (masking/editing templates)

---

## Files Modified

| File | Changes |
|------|---------|
| `CLAUDE.md` | Created - development guidelines for Claude Code |
| `docs/architecture.md` | Added Thin Tools Principle |
| `docs/claude_code_guide.md` | Added Service Layer Pattern section |
| `viraltracker/services/ad_creation_service.py` | Added then removed sanitize method |
| `viraltracker/agent/agents/ad_creation_agent.py` | Multiple social proof prompt changes (reverted) |

---

## Current State

- Social proof section is now empty (`social_proof_section = ""`)
- Avoid using templates with Trustpilot/review badges
- CLAUDE.md provides baseline context for all Claude Code sessions
- Documentation updated with pydantic-ai best practices

---

## Future Considerations

1. **Template Tagging System** - Automatically tag templates by product category, sales event, brand
2. **Ad File Naming Convention** - Structured naming like `WP-C3-A1-V1-story.jpg`
3. **Review Badge Solution** - May need image preprocessing to mask/edit templates before generation

