# SEO Keyword Intelligence — Gemini Embedding 2 Upgrade

**Status**: Implemented
**Created**: 2026-03-17
**Branch**: `feat/seo-keyword-intelligence` (to be created)

---

## 1. Problem Statement

The SEO pipeline uses **Jaccard word-overlap similarity** for all keyword matching, clustering, link suggestion, and cannibalization detection across 8 methods in 5 services. This produces bad results when keywords are phrased differently but mean the same thing:

- "children's trail footwear" scores **0 similarity** against a "hiking shoes for kids" cluster
- The Cluster Builder's quick mode creates fragmented micro-clusters from synonym-heavy keyword lists
- Pre-write checks miss cannibalization between differently-worded keywords targeting the same intent
- Gap analysis only surfaces keywords that happen to share words with a cluster

---

## 2. Solution

Upgrade to semantic embeddings using **Gemini Embedding 2** (`gemini-embedding-2-preview`), which uses the same `google.genai` SDK already in `core/embeddings.py`.

| Spec | Value |
|------|-------|
| Model ID | `gemini-embedding-2-preview` |
| Dimensions | 768 (Matryoshka, configurable 128-3072) |
| Task types | `CLUSTERING`, `SEMANTIC_SIMILARITY`, `RETRIEVAL_DOCUMENT`, `RETRIEVAL_QUERY` |
| Input limit | 8,192 tokens |
| SDK | `google.genai` (already in use) |

**Dimension choice: 768.** SEO keywords are short (<100 tokens). 768 captures sufficient semantics, keeps pgvector indexes small, and matches existing column sizes in the codebase.

**Critical**: Embedding spaces between `gemini-embedding-001` and `gemini-embedding-2-preview` are incompatible. SEO tables have no existing embeddings, so this is greenfield — no migration risk.

---

## 3. Architecture: No New Service

After adversarial review, the original plan's `SemanticSimilarityService` was killed. The three existing Jaccard implementations are small, self-contained static methods. They need a helper function, not a service abstraction.

**Approach**: Add a cosine-with-fallback helper to `core/embeddings.py`:

```python
def embedding_similarity(kw1: str, kw2: str,
                         emb1: Optional[List[float]] = None,
                         emb2: Optional[List[float]] = None) -> float:
    """Cosine similarity if both embeddings available, else Jaccard fallback."""
    if emb1 is not None and emb2 is not None:
        return cosine_similarity(emb1, emb2)
    return _jaccard_word_similarity(kw1, kw2)
```

Each service calls this helper directly, passing embeddings when available. No coupling, no centralized state, no new dependencies.

**Fallback strategy**: Every method checks for NULL embeddings and falls back to Jaccard. This means:
- System works **before** backfill (pure Jaccard, same as today)
- System works **during** backfill (mix of embedding + Jaccard)
- System works **after** backfill (pure embeddings)

No flag day. No migration downtime. Rollback = drop the columns and everything reverts to Jaccard.

---

## 4. Touchpoint Priority Assessment

Not all 8 Jaccard touchpoints deliver equal value. Prioritized by user-visible impact:

### High Priority (Phase 2 — core upgrade)

| # | Method | File:Line | Why It Matters |
|---|--------|-----------|---------------|
| T1 | `auto_assign_keywords()` | `cluster_management_service.py:780` | Current word-overlap scoring misses all semantic matches. Users see orphaned keywords. |
| T2 | `analyze_gaps()` | `cluster_management_service.py:1062` | Jaccard at 0.2 threshold produces noise. Users miss genuine content gaps. |
| T3 | `pre_write_check()` | `cluster_management_service.py:858` | **Highest value.** Misses cannibalization between synonym keywords. Users waste generation on duplicate topics. |
| T7 | `_quick_cluster()` | `seo_workflow_service.py:867` | Jaccard > 0.3 fragments clusters badly. Users must manually merge. First impression of Cluster Builder. |

### Lower Priority (Phase 3 — follow-up)

| # | Method | File:Line | Why |
|---|--------|-----------|-----|
| T4 | `suggest_links()` | `interlinking_service.py:57` | Marginal improvement — auto-linker already handles text matching. |
| T6 | `get_interlinking_audit()` | `cluster_management_service.py:640` | Only changes numbers displayed in UI, no automated behavior affected. |
| T8 | `_jaccard()` seed dedup | `brand_seed_generator_service.py:730` | Stemming already handles most variation. Small gap for true synonyms. |

### Skip

| # | Method | Why |
|---|--------|-----|
| T5 | `add_related_section()` | Picks 5 from 5-11 cluster siblings. Sorting by similarity vs arbitrary order = near-zero visible difference. |

---

## 5. Implementation Plan (3 Phases)

### Phase 1: Infrastructure

**Complexity: S | ~1 day**

#### 1a. Upgrade `core/embeddings.py`

Add model/dimension parameters to existing `Embedder` class:

```python
EMBED_MODEL_V2 = "gemini-embedding-2-preview"

class Embedder:
    def __init__(self, provider="gemini", api_key=None, cache_dir="cache",
                 model: str = EMBED_MODEL, dimensions: int = EMBED_DIM):
        self.model = model
        self.dimensions = dimensions
```

- Update `embed_texts()` to use `self.model` and `self.dimensions`
- Add L2 normalization for non-3072 dims (required by Gemini Embedding 2):
  ```python
  def _normalize(self, vec: List[float]) -> List[float]:
      norm = math.sqrt(sum(x*x for x in vec))
      return [x / norm for x in vec] if norm > 0 else vec
  ```
- **Apply normalization in ALL embedding retrieval paths**: `embed_texts()`, `embed_text()`, and `embed_query()` must all normalize when `self.dimensions < 3072`. Auto-normalize after API response, before returning to caller.
- Add factory: `create_seo_embedder() -> Embedder` (v2 model, 768 dims)
- **Backward compat**: `Embedder()` with no args still uses `gemini-embedding-001`. Existing callers unaffected.

#### 1b. Add helper functions to `core/embeddings.py`

```python
def embedding_similarity(kw1: str, kw2: str,
                         emb1: Optional[List[float]] = None,
                         emb2: Optional[List[float]] = None) -> float:
    """Cosine similarity with Jaccard fallback for NULL embeddings."""

def _jaccard_word_similarity(kw1: str, kw2: str) -> float:
    """Jaccard similarity on word sets (existing logic, consolidated)."""
```

#### 1c. Database migration

**File**: `migrations/2026-03-17_seo_semantic_embeddings.sql`

```sql
-- Migration: Add semantic embedding columns to SEO tables
-- Date: 2026-03-17
-- Requires: pgvector >= 0.5.0 (HNSW support). Supabase bundles 0.7.0+.

-- Keyword embeddings
ALTER TABLE seo_keywords ADD COLUMN IF NOT EXISTS embedding VECTOR(768);
COMMENT ON COLUMN seo_keywords.embedding
  IS 'Gemini Embedding 2 vector (768d) for semantic similarity';
CREATE INDEX IF NOT EXISTS idx_seo_keywords_embedding
  ON seo_keywords USING hnsw (embedding vector_cosine_ops);

-- Cluster centroid embeddings
ALTER TABLE seo_clusters ADD COLUMN IF NOT EXISTS centroid_embedding VECTOR(768);
COMMENT ON COLUMN seo_clusters.centroid_embedding
  IS 'Mean of spoke keyword embeddings — incrementally updated on spoke changes';
CREATE INDEX IF NOT EXISTS idx_seo_clusters_centroid_embedding
  ON seo_clusters USING hnsw (centroid_embedding vector_cosine_ops);
```

**HNSW** instead of IVFFlat: no training data required, better performance at our scale (<10K keywords), no need to rebuild index after backfill. Requires pgvector >= 0.5.0 (Supabase bundles 0.7.0+).

#### 1d. Verify

- `python3 -m py_compile viraltracker/core/embeddings.py`
- Embed a test keyword with v2 model, verify 768-dim output, verify unit-normalized
- Existing `Embedder()` callers still work (no args = old model)
- Migration runs on Supabase

---

### Phase 2: Core Upgrades (4 High-Value Touchpoints)

**Complexity: M | ~2 days**

#### 2a. Embed keywords on creation (batch, not per-keyword)

**File**: `keyword_discovery_service.py`

In `discover_keywords()`, after the save loop (line 142-153), add a batch embedding step:

```python
# After all keywords saved to DB, batch-embed the new ones
new_keyword_ids = [kw_id for kw_id in saved_ids]  # collect IDs during save loop
if new_keyword_ids:
    self._batch_embed_keywords(new_keyword_ids)
```

New private method:
```python
def _batch_embed_keywords(self, keyword_ids: List[str]) -> int:
    """Batch-embed keywords that have NULL embedding. Non-fatal on failure."""
```

- Fetch keyword texts from DB
- Embed in batches of 100 via `create_seo_embedder().embed_texts()`
- Update `seo_keywords.embedding` for each
- Wrap in try/except — embedding failure does not block keyword creation
- Also call from `create_keyword()` for single keywords

**For `create_keyword()`**: embed single keyword inline (one API call, ~50ms). If it fails, log warning and continue.

#### 2b. Cluster centroid computation

**File**: `cluster_management_service.py`

Add incremental centroid update on `add_spoke()`:

```python
def _update_centroid_incremental(self, cluster_id: str, new_embedding: List[float]):
    """O(1) centroid update: new = (old * n + new) / (n + 1)"""
```

- Count existing spokes with embeddings (n)
- If n == 0: centroid = new_embedding
- If n > 0: centroid = (old_centroid * n + new_embedding) / (n + 1), then normalize
- Also add `_recompute_centroid(cluster_id)` for full recompute (used by backfill and bulk operations)

On `create_cluster()`: if pillar keyword has embedding, set as initial centroid.

#### 2c. Upgrade T1: `auto_assign_keywords()`

**File**: `cluster_management_service.py:780-852`

Replace word-overlap scoring with cosine similarity to cluster centroid:

```python
# Current: score = len(kw_words & name_words) * 3 + len(kw_words & pillar_words) * 2 + ...
# New: score = cosine(keyword_embedding, cluster_centroid_embedding)
```

- If both embeddings available: use cosine similarity
- If either NULL: fall back to existing word-overlap scoring (no behavior change)
- Confidence: HIGH >= 0.70 AND >= 1.3x runner-up, MEDIUM >= 0.55, LOW < 0.55
- **Note**: These thresholds are starting values. Tune after A/B validation.

#### 2d. Upgrade T2: `analyze_gaps()`

**File**: `cluster_management_service.py:1062-1140`

Replace Jaccard word-overlap with cosine to cluster centroid:

```python
# Current: overlap = len(kw_words & cluster_words) / len(kw_words | cluster_words) >= 0.2
# New: similarity = embedding_similarity(kw, cluster_combined, kw_emb, centroid) >= 0.50
```

- Threshold 0.50 (starting value, tune on real data)
- Fallback to existing word-overlap when embeddings unavailable

#### 2e. Upgrade T3: `pre_write_check()`

**File**: `cluster_management_service.py:858-947`

Replace Jaccard on keyword words:

```python
# Current: jaccard > 0.6 = HIGH, 0.3-0.6 = MEDIUM
# New: cosine > 0.75 = HIGH, 0.55-0.75 = MEDIUM
```

- Embed candidate keyword on-the-fly: `embedder.embed_text(keyword, task_type="SEMANTIC_SIMILARITY")`
- Compare against all existing article keyword embeddings
- Thresholds 0.75/0.55 (starting values)
- Fallback to Jaccard when article keywords lack embeddings

#### 2f. Upgrade T7: `_quick_cluster()`

**File**: `seo_workflow_service.py:867-907`

Replace Jaccard > 0.3 grouping with embedding-based clustering:

```python
# Current: for each keyword pair, jaccard > 0.3 → same cluster
# New: batch embed all keywords, pairwise cosine > 0.60 → same cluster
```

- Embed all keywords in one batch call
- Pairwise cosine with numpy (200 keywords = 19,900 comparisons, <1ms)
- Same greedy grouping algorithm, just better similarity scores
- Threshold 0.60 (starting value)
- Fallback: if embedding fails, use existing Jaccard path entirely

#### 2g. Backfill script

One-time utility to embed existing keywords and compute centroids:

```python
# scripts/backfill_seo_embeddings.py
# 1. SELECT id, keyword FROM seo_keywords WHERE embedding IS NULL
# 2. Batch embed in groups of 100
# 3. UPDATE seo_keywords SET embedding = ... WHERE id = ...
# 4. Recompute all cluster centroids
```

#### 2h. A/B Validation

**Before switching any production touchpoint**, run both algorithms on one real project:

1. For T3 (pre-write check): Pick 20 keyword pairs. Run Jaccard and cosine. Compare which catches more real cannibalization.
2. For T7 (quick cluster): Run both on the same keyword list. Compare cluster quality (fewer fragments, better grouping).
3. Document results. Adjust thresholds if needed.

#### 2i. Verify

- `python3 -m py_compile` on all modified files
- Discover keywords for a test project → verify embeddings stored
- Create cluster, add spokes → verify centroid computed
- Run `auto_assign_keywords()` → compare results to Jaccard version
- Run `pre_write_check()` with synonym keywords → verify detection
- Run `_quick_cluster()` → verify fewer fragments
- Delete embeddings from keywords → confirm Jaccard fallback works

---

### Phase 3: Remaining Touchpoints

**Complexity: S | ~1 day**

After Phase 2 is validated on real data:

#### 3a. T4: `suggest_links()` — `interlinking_service.py:57`

Replace `_jaccard_similarity` with `embedding_similarity()`. Min similarity 0.50, HIGH priority at 0.65.

#### 3b. T6: `get_interlinking_audit()` — `cluster_management_service.py:640`

Replace Jaccard in link matrix with cosine similarity. Missing links threshold 0.50.

#### 3c. T8: `brand_seed_generator_service.py:730`

Replace stemmed Jaccard > 0.6 with cosine > 0.82 for seed dedup. On-the-fly embedding since seeds aren't in DB.

#### 3d. Verify

- Run `suggest_links()` on a known article, verify broader link suggestions
- Run interlinking audit, verify matrix reflects semantic relationships
- Run seed generation, verify dedup catches synonyms

---

## 6. Keyword Data Enrichment (DataForSEO)

The `seo_keywords` table already has `search_volume`, `keyword_difficulty`, and `search_intent` columns — but they're **never populated**. The `suggest_next_article()` scoring formula defaults to `volume=10` and `KD=50` when these are NULL, making its recommendations near-random on actual merit.

**Provider: DataForSEO** — one API covering all three use cases (volume/KD, PAA, competitor keywords). Pay-as-you-go, $50 minimum deposit, no subscription. HTTP Basic Auth.

### Phase 4: DataForSEO Service + Volume/KD Enrichment

**Complexity: M | ~2 days**

#### 4a. New service: `dataforseo_service.py`

**New file**: `viraltracker/services/seo_pipeline/services/dataforseo_service.py`

This IS a legitimate new service (external API wrapper, same pattern as `GSCService`). It is NOT an internal abstraction layer.

```python
class DataForSEOService:
    """DataForSEO API wrapper for keyword data, PAA, and competitor analysis."""

    def __init__(self, supabase_client=None):
        self._supabase = supabase_client
        # Auth: DATAFORSEO_LOGIN + DATAFORSEO_PASSWORD env vars
        # HTTP: httpx (already in use)

    def enrich_keywords_bulk(self, keyword_texts: List[str]) -> List[Dict]:
        """
        Fetch volume + difficulty for up to 1,000 keywords.

        Uses:
        - clickstream_data/bulk_search_volume/live → search_volume, monthly_searches
        - dataforseo_labs/google/bulk_keyword_difficulty/live → keyword_difficulty

        Returns: [{keyword, search_volume, keyword_difficulty}, ...]
        Cost: ~$0.12 per 1,000 keywords
        """

    def fetch_people_also_ask(self, keyword: str, depth: int = 2) -> List[str]:
        """
        Extract PAA questions for a keyword from Google SERP.

        Uses: serp/google/organic/live/advanced with people_also_ask_click_depth
        Returns: List of question strings
        Cost: ~$0.001 per keyword
        """

    def get_competitor_keywords(self, domain: str, limit: int = 500) -> List[Dict]:
        """
        Get organic keywords a competitor domain ranks for.

        Uses: dataforseo_labs/google/ranked_keywords/live
        Returns: [{keyword, position, search_volume, etv}, ...]
        Cost: ~$0.011 per request (up to 1,000 results)
        """
```

**Rate limits**: 2,000 req/min, 30 simultaneous. Well within our usage patterns.

#### 4b. Enrich after keyword discovery

**File**: `keyword_discovery_service.py`

After batch embedding (Phase 2a), add enrichment step:

```python
# After embedding, enrich with volume/KD data
if new_keywords:
    self._enrich_keywords_volume(new_keywords)

def _enrich_keywords_volume(self, keyword_texts: List[str]):
    """Non-fatal: fetch volume/KD from DataForSEO, update seo_keywords."""
```

- Batch 1,000 keywords per call
- Update `seo_keywords.search_volume` and `seo_keywords.keyword_difficulty`
- Non-fatal: if DataForSEO fails, keywords still saved with NULL volume/KD (same as today)
- Also callable standalone for backfilling existing keywords

#### 4c. Existing tools that immediately improve

| Tool | How It Improves |
|------|----------------|
| `suggest_next_article()` | Scoring formula uses real volume/KD instead of defaults (10/50). Recommendations become meaningful. |
| `auto_assign_keywords()` | Confidence scoring can factor in KD (easier keywords → higher confidence for assignment) |
| Keyword Research UI table | Volume and Difficulty columns populated, users can sort/filter by actual data |
| Cluster health metrics | Published/planned status now has volume context |

**No new UI elements.** The Keyword Research page already displays `search_volume` and `keyword_difficulty` columns — they're just empty today.

#### 4d. New env vars

```
DATAFORSEO_LOGIN=your_login
DATAFORSEO_PASSWORD=your_password
```

#### 4e. Verify

- `python3 -m py_compile` on new service
- Enrich 10 test keywords → verify volume/KD stored
- Run `suggest_next_article()` → verify scoring uses real data
- Verify graceful failure when DataForSEO credentials missing

---

### Phase 5: People Also Ask Mining

**Complexity: S | ~1 day**

#### 5a. Register PAA as keyword source in `ClusterResearchRegistry`

**File**: `cluster_research_registry.py` — add to `_register_builtins()`:

```python
self.register(
    "people_also_ask",
    self._fetch_paa_questions,
    "People Also Ask questions from Google SERPs",
)
```

New fetcher method:

```python
def _fetch_paa_questions(self, brand_id, organization_id, seeds):
    """Fetch PAA questions for seed keywords via DataForSEO."""
    dataforseo = DataForSEOService(supabase_client=self.supabase)
    questions = []
    for seed in seeds[:10]:  # Limit to 10 seeds (~$0.01 total)
        paa = dataforseo.fetch_people_also_ask(seed, depth=2)
        questions.extend(paa)
    # Dedup
    seen = set()
    unique = []
    for q in questions:
        if q.lower() not in seen:
            seen.add(q.lower())
            unique.append(q)
    return unique
```

**This plugs into the existing `ClusterResearchRegistry.fetch_all()` flow.** The Cluster Builder UI already calls `fetch_all()` and displays results from all registered sources. PAA questions appear automatically as a new keyword source alongside Google Autocomplete and GSC queries.

#### 5b. Embed PAA keywords

PAA questions that get saved as keywords (via the existing Cluster Builder flow) are batch-embedded in Phase 2a's hook. No additional work needed.

#### 5c. Dedup PAA against existing keywords

When PAA questions are added to the keyword pool, the embedding-based dedup from Phase 2 catches duplicates. Example: PAA "how to clean hiking boots" won't create a duplicate if "cleaning hiking boots guide" already exists (cosine > 0.92).

#### 5d. Verify

- Run Cluster Builder with PAA source enabled → verify PAA questions appear
- Verify PAA keywords get embedded
- Verify duplicates are caught

---

### Phase 6: Competitor Keyword Gap Analysis

**Complexity: M | ~1-2 days**

#### 6a. Register as keyword source in `ClusterResearchRegistry`

**File**: `cluster_research_registry.py` — add to `_register_builtins()`:

```python
self.register(
    "competitor_keywords",
    self._fetch_competitor_gap_keywords,
    "Keywords competitors rank for that you don't cover",
)
```

New fetcher method:

```python
def _fetch_competitor_gap_keywords(self, brand_id, organization_id, seeds):
    """
    Find keywords competitors rank for that we don't cover.

    1. Get competitor domains from brand config or seo_competitor_analyses
    2. Fetch their organic keywords via DataForSEO
    3. Filter out keywords we already have (embedding similarity >= 0.85)
    4. Return gap keywords
    """
```

#### 6b. Competitor domain source

Pull competitor domains from:
- `seo_competitor_analyses` table (already populated by existing competitor analysis runs)
- Or manual input in the Cluster Builder UI (seeds parameter)

#### 6c. Gap detection with embeddings

For each competitor keyword:
1. Embed it
2. Compare against all existing `seo_keywords` embeddings in the brand
3. If max similarity < 0.50 → genuine gap (add to results)
4. If max similarity >= 0.50 → already covered (skip)

This is where Phase 2 embeddings directly enable a new capability. Without embeddings, gap detection would use Jaccard and miss synonym matches.

#### 6d. Verify

- Run with 1 known competitor domain → verify gap keywords returned
- Verify already-covered keywords are filtered out
- Verify gap keywords make sense for the brand

---

## 7. What This Plan Does NOT Include

These are **separate features** to be tracked in `docs/TECH_DEBT.md`:

| Feature | Why Separate |
|---------|-------------|
| Article prioritization (diversity + GSC bonus) | New scoring signals, not a keyword research improvement |
| GSC query intelligence (cluster matching) | Independent analytics feature |
| Phase A content context (sibling awareness) | Prompt engineering change |
| Cluster health semantic coverage | Vanity metric without clear user action |
| Keyword deduplication UI | Standalone tool, build after infra is stable |
| Striking distance report | GSC analytics feature, works without embeddings |
| Search intent classification | Better solved by LLM call or separate feature |
| Reddit cross-pollination | Requires angle pipeline changes, separate scope |

---

## 8. Cost & Performance

### Gemini Embedding API

- Standard: ~$0.00025 per 1K tokens
- Batch API: 50% discount
- 300 keywords discovery run: ~$0.00075. Negligible.
- Monthly per brand (2,000 keywords): ~$0.05

### DataForSEO API

| Operation | Cost | Volume |
|-----------|------|--------|
| Volume + KD enrichment (1K keywords) | ~$0.12 | Per discovery run |
| PAA extraction (10 seeds) | ~$0.01 | Per cluster research |
| Competitor keywords (1 domain) | ~$0.011 | Per competitor |
| **Monthly estimate per brand** | **~$1-5** | Depends on discovery frequency |

$50 minimum deposit covers months of typical usage.

### Performance

| Operation | Latency |
|-----------|---------|
| Single keyword embed | ~50ms |
| Batch 100 keywords embed | ~200ms |
| Pairwise cosine (200 keywords, numpy) | <1ms |
| pgvector HNSW search (10K rows) | <5ms |
| DataForSEO bulk volume (1K keywords) | ~2-3s |
| DataForSEO PAA (1 keyword) | ~3-5s |
| DataForSEO competitor keywords (1 domain) | ~5-10s |

### Usage Tracking

Hook into existing `UsageTracker`:
- Embedding: `model="gemini-embedding-2-preview"`, `operation="seo_keyword_embedding"`
- DataForSEO: `model="dataforseo"`, `operation="keyword_enrichment"` / `"paa_extraction"` / `"competitor_keywords"`

---

## 9. Rollback Plan

All changes are additive. Rollback path:

**Embedding rollback:**
1. `ALTER TABLE seo_keywords DROP COLUMN IF EXISTS embedding;`
2. `ALTER TABLE seo_clusters DROP COLUMN IF EXISTS centroid_embedding;`
3. Revert code changes — all methods fall back to Jaccard when embeddings are NULL

**DataForSEO rollback:**
1. Remove env vars
2. Revert `cluster_research_registry.py` — removes PAA and competitor sources
3. Volume/KD columns already exist and can remain populated (no harm)

No data loss. No behavior change on rollback.

---

## 10. New Dependencies & Environment Variables

### Python Packages

None new. `httpx` (already in use for keyword discovery) handles DataForSEO HTTP calls.

### Environment Variables

| Variable | Purpose | Required |
|----------|---------|----------|
| `GEMINI_API_KEY` | Embedding API (already exists) | Yes (Phases 1-3) |
| `DATAFORSEO_LOGIN` | DataForSEO API auth | Yes (Phases 4-6) |
| `DATAFORSEO_PASSWORD` | DataForSEO API auth | Yes (Phases 4-6) |

DataForSEO credentials are optional — Phases 1-3 work without them. If missing, enrichment/PAA/competitor features degrade gracefully (log warning, skip).

---

## 11. Files Modified & Created

| File | Changes | Phase |
|------|---------|-------|
| `viraltracker/core/embeddings.py` | v2 model, factory, normalization, similarity helper | 1 |
| `viraltracker/services/seo_pipeline/services/keyword_discovery_service.py` | Batch embed + enrich after discovery | 2, 4 |
| `viraltracker/services/seo_pipeline/services/cluster_management_service.py` | T1-T3, T6, centroid management | 2, 3 |
| `viraltracker/services/seo_pipeline/services/seo_workflow_service.py` | T7 quick cluster builder | 2 |
| `viraltracker/services/seo_pipeline/services/interlinking_service.py` | T4 suggest links | 3 |
| `viraltracker/services/seo_pipeline/services/brand_seed_generator_service.py` | T8 seed dedup | 3 |
| `viraltracker/services/seo_pipeline/services/cluster_research_registry.py` | Register PAA + competitor sources | 5, 6 |
| `migrations/2026-03-17_seo_semantic_embeddings.sql` | VECTOR columns + HNSW indexes | 1 |
| **New:** `viraltracker/services/seo_pipeline/services/dataforseo_service.py` | External API wrapper | 4 |
| **New:** `scripts/backfill_seo_embeddings.py` | One-time backfill utility | 2 |
| `viraltracker/services/seo_pipeline/services/interlinking_service.py` | T4 suggest links |
| `viraltracker/services/seo_pipeline/services/brand_seed_generator_service.py` | T8 seed dedup |
| `migrations/2026-03-17_seo_semantic_embeddings.sql` | VECTOR(768) columns + HNSW indexes |
| `scripts/backfill_seo_embeddings.py` | One-time backfill utility |

**No new service files.** No new abstractions. No new dependencies.
