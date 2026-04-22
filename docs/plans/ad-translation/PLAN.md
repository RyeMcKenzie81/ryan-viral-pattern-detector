# Ad Translation & Multi-Language Support

**Feature**: Multi-language ad creation — translate existing winning ads and create new ads directly in any language.
**Date**: 2026-04-22
**Branch**: `RyeMcKenzie81/translate-ads-spanish`

---

## Phase 1: Requirements (APPROVED)

### Problem
The user has winning ads on Savage generating sales. They want to translate them into Spanish (and potentially other languages) to reach new audiences. There is currently no translation, localization, or multi-language support anywhere in the ad creation system.

### Requirements Gathered

| # | Question | Answer |
|---|----------|--------|
| 1 | Image handling | **Regenerate** — the ad creation tool generates images with text baked in, and isn't aware of Facebook ad copy. We regenerate the image with translated text. |
| 2 | Ad ID format for lookup | User's visible ID format: `SAV-FTS-65bb40-04161b-SQ` (from `export_utils.generate_structured_filename`). Also support Meta ad ID. Need both. |
| 3 | Single vs batch | **Both** — single ad for quick use, batch with performance filter for scaling |
| 4 | Languages | **Open** — any language, user specifies in prompt |
| 5 | New ad language threading | **Generate directly** in target language (hooks adapted in Spanish, copy written in Spanish) |
| 6 | Interface | **Both** — chat-routable agent tool + UI button on Ad Gallery/History |
| 7 | Image regen | Regenerate the full ad image with translated text overlays via the existing Gemini pipeline |

### Desired End Result

Three capabilities:
1. **`lookup_ad` tool** — Find any ad by generated ad UUID, structured filename fragment (e.g., `65bb40` or `SAV-FTS-65bb40-04161b-SQ`), or Meta ad ID. Returns ad details, copy, image URL, performance data, lineage.
2. **`translate_ads` tool** — Takes ad ID(s) or a performance filter + target language. Translates hook_text, meta_headline, meta_primary_text via Claude. Regenerates image with translated text. Creates new `generated_ads` rows with `language` and `translation_parent_id`.
3. **`language` parameter on `create_ads_v2()`** — New ads created directly in target language. Hooks adapted in that language. Copy scaffolding generates in that language.

### Out of Scope (for now)
- UI page for browsing ads filtered by language (can add later)
- Automatic detection of which ads to translate based on performance thresholds
- RTL language support (Arabic, Hebrew) — needs layout changes
- **Capability B: Pipeline language threading** — thread `language` into `create_ads_v2()` for direct non-English ad creation (deferred, see TODOS.md)
- **Copy guardrail localization** — English regex patterns won't catch Spanish prohibited claims (deferred, see TODOS.md)
- **UI "Translate" button** — deferred to follow-up after chat tools work

---

## Phase 2: Architecture Decision

### Pattern: Python workflow (NOT pydantic-graph)

**Reasoning:**
- The user decides which ads to translate and which language → **user-driven flow**
- Translation is a short synchronous operation (Claude call + Gemini re-generation)
- No complex branching or AI decision-making about next steps
- The translate tool delegates to a service method — fits the thin-tools pattern

### Key Architecture Decisions (from eng review)

1. **Image regeneration**: Direct `prompt_spec` modification — swap text fields in stored JSON, re-run `gemini_service.generate_image()`. NOT full pipeline re-run.
2. **Service dependencies**: Constructor injection (Supabase, GeminiService, Anthropic client). Consistent with codebase pattern.
3. **Ad run ownership**: New 'translation' ad_run per batch. Clean grouping in Ad History.
4. **Filename convention**: Language suffix on structured filenames (`SAV-FTS-65bb40-04161b-SQ-ES`). No suffix = English.
5. **Idempotency**: UNIQUE constraint on `(translation_parent_id, language)`. Check-before-insert in service.
6. **Locale model**: IETF language tags (`es-MX`, `pt-BR`), not just ISO 639-1 codes.
7. **Schema resilience**: Defensive prompt_spec path extraction with fallback + warning for schema drift.
8. **Translation provenance**: Store translator model, prompt version, timestamp in ad_run parameters JSONB.
9. **Performance filter**: Batch "top N by ROAS" should respect existing winner criteria (7+ days, 1000+ impressions).

### Component Architecture

```
Agent Tool Layer (thin)
├── lookup_ad()           → AdTranslationService.lookup_ad()
└── translate_ads()       → AdTranslationService.translate_batch()

Service Layer (business logic)
├── AdTranslationService  → NEW: translation logic, batch ops, lookup
└── AdCreationService     → EXTEND: language column in save_generated_ad()
```

---

## Phase 3: Inventory & Gap Analysis

### Existing Components to Reuse

| Component | Location | Reuse |
|-----------|----------|-------|
| `AdCreationService.save_generated_ad()` | `services/ad_creation_service.py` | Extend with `language`, `translation_parent_id` params |
| `AdCreationService.get_ad_for_variant()` | `services/ad_creation_service.py:753` | Reuse to fetch source ad for translation |
| `AdCreationService.get_image_as_base64()` | `services/ad_creation_service.py` | Reuse to get source image for re-generation |
| `AdCreationService.generate_ad_filename()` | `services/ad_creation_service.py:336` | Reuse (filename already has format code) |
| `export_utils.generate_structured_filename()` | `ui/export_utils.py:83` | Reference for parsing user-provided ad IDs |
| `MetaAdsService.find_matching_generated_ad_id()` | `services/meta_ads_service.py:1171` | Reuse pattern-matching logic for ad lookup |
| `CopyScaffoldService` | `services/copy_scaffold_service.py` | Extend with `language` param for direct generation |
| `ContentService` (ad creation v2) | `pipelines/ad_creation/services/content_service.py` | Extend hook adaptation with `language` param |
| `GenerationService` (ad creation v2) | `pipelines/ad_creation_v2/services/generation_service.py` | Extend prompt building with `language` param |
| `AgentDependencies` | `agent/dependencies.py` | Add `ad_translation` service |
| `ad_creation_agent.py` | `agent/agents/ad_creation_agent.py` | Add 2 new tools |
| `AdPerformanceQueryService` | `services/ad_performance_query_service.py` | Reuse for performance-filtered batch selection |

### New Components to Build

| Component | Type | Location |
|-----------|------|----------|
| `AdTranslationService` | Service | `services/ad_translation_service.py` |
| `lookup_ad` | Tool | `agent/agents/ad_creation_agent.py` |
| `translate_ads` | Tool | `agent/agents/ad_creation_agent.py` |
| DB migration | SQL | `migrations/2026-04-22_ad_translation_support.sql` |

### Database Changes

**Extend `generated_ads` table** (no new tables needed):

```sql
-- Language and translation lineage
ALTER TABLE generated_ads
ADD COLUMN IF NOT EXISTS language TEXT DEFAULT 'en',
ADD COLUMN IF NOT EXISTS translation_parent_id UUID REFERENCES generated_ads(id);

-- Fast fragment lookup (first 8 chars of UUID, text-indexed)
ALTER TABLE generated_ads
ADD COLUMN IF NOT EXISTS id_prefix TEXT GENERATED ALWAYS AS (LEFT(id::text, 8)) STORED;

COMMENT ON COLUMN generated_ads.language IS 'IETF language tag (en, es-MX, pt-BR, etc.)';
COMMENT ON COLUMN generated_ads.translation_parent_id IS 'FK to original ad this was translated from';
COMMENT ON COLUMN generated_ads.id_prefix IS 'First 8 chars of UUID for fast fragment lookup';

CREATE INDEX IF NOT EXISTS idx_generated_ads_language ON generated_ads(language);
CREATE INDEX IF NOT EXISTS idx_generated_ads_translation_parent ON generated_ads(translation_parent_id);
CREATE INDEX IF NOT EXISTS idx_generated_ads_id_prefix ON generated_ads(id_prefix);

-- Idempotency: prevent duplicate translations of same ad into same language
CREATE UNIQUE INDEX IF NOT EXISTS idx_generated_ads_translation_unique
ON generated_ads(translation_parent_id, language)
WHERE translation_parent_id IS NOT NULL;
```

---

## Phase 4: Build Plan (Scope A Only)

### Step 1: Database Migration
- `migrations/2026-04-22_ad_translation_support.sql`
- Add `language` (TEXT, default 'en'), `translation_parent_id` (UUID FK), `id_prefix` (GENERATED) to `generated_ads`
- Add indexes + unique constraint on `(translation_parent_id, language)`

### Step 2: AdTranslationService (`services/ad_translation_service.py`)

Constructor injection: `__init__(self, supabase, gemini_service, ad_creation_service)`

**Methods:**

```python
class AdTranslationService:
    def __init__(self, supabase: Client, gemini_service: GeminiService,
                 ad_creation_service: AdCreationService):
        self.supabase = supabase
        self.gemini = gemini_service
        self.ad_creation = ad_creation_service

    async def lookup_ad(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Find an ad by any identifier format:
        - Full UUID: direct lookup on generated_ads.id
        - Structured filename fragment (e.g., "65bb40", "SAV-FTS-65bb40-04161b-SQ"):
          parse and match against id_prefix column
        - Meta ad ID: lookup via meta_ad_mapping table
        Returns ad with copy fields, storage_path, performance data, lineage.
        """

    async def translate_ad_copy(
        self, hook_text: str, meta_headline: Optional[str],
        meta_primary_text: Optional[str], target_language: str,
        brand_voice_context: Optional[str] = None,
    ) -> Dict[str, str]:
        """
        Marketing-aware translation via Claude.
        Preserves persuasive intent, not literal.
        Returns dict with translated hook_text, meta_headline, meta_primary_text.
        """

    async def translate_single_ad(
        self, source_ad_id: UUID, target_language: str,
    ) -> Dict[str, Any]:
        """
        Full translation workflow for one ad:
        1. Check idempotency (translation_parent_id + language unique constraint)
        2. Fetch source ad via get_ad_for_variant()
        3. Translate copy via translate_ad_copy()
        4. Modify stored prompt_spec: swap content.headline.text and
           content.subheadline.text with defensive path extraction + fallback
        5. Re-run gemini.generate_image() with modified prompt + original refs
        6. Save new generated_ad with language + translation_parent_id
        """

    async def translate_batch(
        self, ad_ids: Optional[List[UUID]] = None,
        product_id: Optional[UUID] = None,
        top_n_by_roas: Optional[int] = None,
        target_language: str = "es-MX",
    ) -> Dict[str, Any]:
        """
        Batch translation with ad_run tracking.
        1. Create translation ad_run (parameters: content_source="translation",
           target_language, source_ad_ids, translator model/version)
        2. Resolve ad list: explicit IDs or performance filter (respects winner criteria)
        3. Translate each, tracking per-ad success/failure
        4. Return summary with counts + ad_run_id
        """

    def _parse_ad_identifier(self, query: str) -> Dict[str, str]:
        """Parse user input into lookup strategy.
        Returns {"type": "uuid"|"filename_fragment"|"meta_ad_id", "value": ...}
        Reuses regex patterns from MetaAdsService.find_matching_generated_ad_id()"""

    def _normalize_language(self, language: str) -> str:
        """Normalize to IETF tag: "Spanish" → "es", "Mexican Spanish" → "es-MX",
        "es" → "es", "pt-BR" → "pt-BR". Case-insensitive."""

    def _swap_prompt_spec_text(self, prompt_spec: Dict, translated_hook: str,
                                translated_benefit: Optional[str]) -> Dict:
        """Defensive prompt_spec text replacement.
        Tries content.headline.text and content.subheadline.text.
        Falls back to searching JSON for text fields if schema changed.
        Logs warning on fallback."""
```

### Step 3: Extend AdCreationService

- Add `language: Optional[str] = None` and `translation_parent_id: Optional[UUID] = None` params to `save_generated_ad()`
- These get written to the new columns following the existing "if not None, add to dict" pattern

### Step 4: Filename Language Suffix

- `ad_creation_service.py:generate_ad_filename()` — append `-{lang.upper()}` when language != 'en' and language is not None
- `ui/export_utils.py:generate_structured_filename()` — same suffix logic

### Step 5: New Agent Tools

**`lookup_ad` tool** on `ad_creation_agent`:
```python
@ad_creation_agent.tool(metadata={...})
async def lookup_ad(
    ctx: RunContext[AgentDependencies],
    query: str,
) -> Dict:
    """Look up an ad by ID (UUID, filename like SAV-FTS-65bb40, or Meta ad ID).
    Returns ad details including copy, image URL, performance, and lineage."""
    return await ctx.deps.ad_translation.lookup_ad(query)
```

**`translate_ads` tool** on `ad_creation_agent`:
```python
@ad_creation_agent.tool(metadata={...})
async def translate_ads(
    ctx: RunContext[AgentDependencies],
    ad_ids: Optional[List[str]] = None,
    product_id: Optional[str] = None,
    top_n_by_roas: Optional[int] = None,
    target_language: str = "es-MX",
) -> Dict:
    """Translate existing ads into a target language. Regenerates images with
    translated text. Provide specific ad IDs or use performance filters.
    Language should be an IETF tag like es-MX, pt-BR, fr-FR."""
    return await ctx.deps.ad_translation.translate_batch(...)
```

### Step 6: Wire into AgentDependencies + Orchestrator Routing

- Import `AdTranslationService` in `dependencies.py`
- Add `ad_translation: AdTranslationService` field, init in `create()`
- Update orchestrator routing description to include translation

### Step 7: Tests

- `tests/test_ad_translation_service.py` — ~20+ test cases covering all paths
- Covers: identifier parsing, language normalization, copy translation, single ad translation, batch translation, prompt_spec schema drift, idempotency, filename suffix

---

## Build Order & Dependencies

```
Migration (Step 1)
    ↓
AdTranslationService (Step 2) + Extend AdCreationService (Step 3) + Filename suffix (Step 4)
    ↓
Agent tools (Step 5)
    ↓
AgentDependencies + Routing (Step 6)
    ↓
Tests (Step 7)
```

Sequential implementation. Steps 2-4 share the services/ directory.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Codex Review | `/codex review` | Independent 2nd opinion | 1 | ISSUES_FOUND | 14 findings (5 critical, 5 high, 4 medium). 4 actioned: idempotency guard, locale model, schema resilience, provenance tracking. |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR (PLAN) | 5 issues, 0 critical gaps. Scope reduced from 11 to 6 files. |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | — |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | — |

**UNRESOLVED:** 0
**VERDICT:** ENG CLEARED — ready to implement.
