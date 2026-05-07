# Quick URL Competitor Intel — Engineering Plan

**Status:** Ready to execute (deferred until current ad creation run completes)
**Branch:** `RyeMcKenzie81/quick-competitor-intel`
**Date:** 2026-05-06
**Last reviewed:** 2026-05-06 (`/plan-eng-review` + Codex outside voice)

## Goal

Add a "Quick URL" mode to the Competitor Intel tool that takes a single public Facebook video URL (post, reel, watch, or ad library link), runs the existing ingredient extraction + remix flow against it, and saves to the angle pipeline — all without requiring a configured competitor or pre-scraped ads.

## Non-Goals

- Bulk URL input (single video per run, MVP).
- Private/login-gated videos.
- Replacing the existing competitor flow (this is purely additive).
- Saving extracted videos into `competitor_ads` / `competitor_ad_assets` (those tables stay competitor-only).
- Auto-expiring quick packs (decision: keep them forever, same as competitor packs).
- Per-org cost guardrails in MVP (decision: trust the operator; add if abuse appears).

## What's Already In Our Favor

The downstream pipeline is competitor-agnostic at the right layers:

- `analyze_single_video(asset_id, storage_path)` — only needs a storage path. No FK to `competitor_ad_assets`.
- `aggregate_extractions()` — handles `n=1` gracefully.
- `remix_video(video_extraction, brand_context, ...)` — takes a dict, no `competitor_id`.
- `save_to_angle_pipeline(pack_id, product_id, organization_id, brand_id?)` — already competitor-free in its writes.

So the surface area is: **acquire video → store → mint a pack record → reuse the rest unchanged.**

## Deployment Prerequisites

Verify before merging the migration:

1. **ffmpeg available in deploy image** (Railway). Many FB videos served by yt-dlp require ffmpeg for stream merge (DASH/HLS → mp4). Check: `ffmpeg -version` runs in the deployed container. If absent, add via apt buildpack OR use `yt_dlp.YoutubeDL({'format': 'best[ext=mp4]'})` to prefer single-file formats and accept lower quality on some videos.
2. **Supabase Storage upload limit.** Check current tier — Free tier caps uploads at 50MB; Pro is configurable. Set our application cap to `min(100MB, supabase_tier_cap)`. If on Free, the plan's 100MB upload limit must drop to 50MB.
3. **`angle_candidates.source_type` column type.** Check whether it's a Postgres `ENUM` or `TEXT` with a CHECK constraint:
   ```sql
   SELECT data_type, udt_name FROM information_schema.columns
   WHERE table_name='angle_candidates' AND column_name='source_type';
   ```
   - If `udt_name` is a custom type → migration needs `ALTER TYPE <enum_name> ADD VALUE 'quick_intel';` (must run before the new code deploys).
   - If TEXT + CHECK → migration needs `ALTER TABLE ... DROP CONSTRAINT ... ADD CONSTRAINT ... CHECK (source_type IN (..., 'quick_intel'));`.
4. **Streamlit memory ceiling.** Two concurrent 100MB resolves can spike memory. Internal-team scale makes this acceptable, but document the constraint: deploy with at least 2GB RAM.

## Rollout Sequencing

Strict order — do NOT compress these:

1. **Apply migration** (`migrations/2026-05-XX_quick_intel_packs.sql`) to the DB. This includes:
   - `competitor_intel_packs` schema changes (new columns + nullable competitor_id).
   - `angle_candidates.source_type` enum/CHECK update (whichever applies — see Prereq #3).
2. **Deploy app code** (Streamlit UI + scheduler worker together). Both read the new column. They must deploy in the same release.
3. **Smoke test:**
   - Existing competitor pack still loads (regression).
   - Existing `competitor_intel_analysis` job still runs.
   - Quick URL submission produces a pack and worker analyses it.

Backwards compat: the `source_type DEFAULT 'competitor'` and `competitor_id DROP NOT NULL` mean migration can run before code deploys without breaking existing INSERTs. But **new code reading `source_type` should not deploy before migration** — deploy order is migration-first.

## Data Flow (ASCII)

```
USER (Streamlit Tab 1, Quick URL mode)
  │
  │ pastes FB URL (or drops video file)
  ▼
┌────────────────────────────────────────────────────────────┐
│ UI: viraltracker/ui/pages/14_🔎_Competitor_Intel.py        │
│                                                             │
│  1. Validate URL pattern (or accept upload)                 │
│  2. Check duplicate (source_url, organization_id)           │
│     │                                                       │
│     ├─ HIT: offer "view existing" OR "re-pack from cache"   │
│     │      (re-pack copies extraction → free re-analysis)   │
│     │                                                       │
│     └─ MISS: spinner "Resolving video…" (90s timeout)       │
│              │                                              │
│              ▼                                              │
│      fb_video_resolver.resolve_fb_video(url)                │
│              │                                              │
│              ├─ FAIL → surface error, pivot to upload UI    │
│              └─ OK   → (bytes, mime_type)                   │
│                                                             │
│  3. CompetitorIntelService.create_quick_pack(...)           │
└────────────────────────────────────────────────────────────┘
  │
  ▼
┌────────────────────────────────────────────────────────────┐
│ SERVICE: _create_quick_pack(bytes, mime, source_type, url)  │
│                                                             │
│  a. Resolve org_id ("all" → real UUID via brand)            │
│  b. Generate pack_uuid client-side                          │
│  c. Upload bytes → quick-intel/{org}/{pack_uuid}/video.mp4  │
│     │   (FAIL → raise; no DB row written)                   │
│  d. INSERT pack row with status='pending'                   │
│     │   (FAIL → orphaned blob; logged for cleanup sweep)    │
│  e. Enqueue quick_intel_analysis job (next_run_at = +1 min) │
│     │   (FAIL → UPDATE pack status='failed'; surface error) │
│  f. Return pack_id                                          │
└────────────────────────────────────────────────────────────┘
  │
  ▼ (≤ 1 minute later, on worker tick)
┌────────────────────────────────────────────────────────────┐
│ WORKER: execute_quick_intel_analysis_job(job)               │
│                                                             │
│  1. Load pack → get source_video_storage_path               │
│  2. extraction = analyze_single_video(synth_uuid, path)     │
│  3. pack_data  = aggregate_extractions([extraction], [1.0]) │
│  4. UPDATE pack: video_analyses, pack_data, status='complete'│
│     │   (FAIL → _reschedule_after_failure; max 3 retries,   │
│     │           then status='failed' + activity event)      │
└────────────────────────────────────────────────────────────┘
  │
  ▼
EXISTING UI (unchanged): Tab 2 Video Details, Tab 3 Remix & Save
  │
  ▼
save_to_angle_pipeline → angle_candidates (source_type=QUICK_INTEL)
```

## The Hard Problem: FB Post URL → Video File

The current Apify actor (`curious_coder/facebook-ads-library-scraper`) takes only page URLs / ad library searches. It does **not** accept post URLs. Three viable paths, ranked:

| Option | Pros | Cons | Decision |
|---|---|---|---|
| **A. yt-dlp** (Python lib) | Free, fast, supports public FB posts/reels/ad library, no API key | Brittle to FB HTML changes; ToS gray area (we're already in competitor intel) | **Primary path** |
| **B. File upload fallback** | Bulletproof; user already has the .mp4 | Manual; loses URL→video automation | **Always-available fallback** |
| **C. Apify FB-posts actor** | Managed, more robust | Adds cost per run; another vendor dep | Defer to v2 if yt-dlp proves unreliable |

**Decision:** Ship A + B together. URL field auto-tries yt-dlp; on failure, UI prompts user to drag-drop the file. Same downstream code path either way (both produce a Supabase storage path).

### Supported URL Patterns (resolver should accept all)

- `facebook.com/{page_id}/posts/{post_id}/` (the user's example)
- `facebook.com/reel/{reel_id}`
- `facebook.com/watch/?v={video_id}`
- `facebook.com/ads/library/?id={archive_id}`
- `facebook.com/{page_name}/videos/{video_id}/`

yt-dlp handles all of these natively.

### Resolver Location & Threading

- Resolver lives in the **service layer** (`fb_video_resolver.resolve_fb_video`), called from `create_quick_pack_from_url`. UI never imports yt-dlp directly.
- The UI calls the service method synchronously inside `st.spinner("Resolving video…")`. The service method blocks until either the resolver returns bytes or the wall-clock timeout fires.
- **True wall-clock timeout** via `concurrent.futures.ThreadPoolExecutor`:
  ```python
  with ThreadPoolExecutor(max_workers=1) as ex:
      future = ex.submit(_extract_with_ytdlp, url)
      try:
          return future.result(timeout=90)
      except FuturesTimeout:
          # best-effort cancel; future may still finish in background but caller raises
          raise ResolverError("timeout")
  ```
  yt-dlp's own `socket_timeout` setting is per-socket and does NOT cap total wall-clock — many sequential requests can blow past it. The ThreadPoolExecutor wrapper gives a real cap.
- On any error (timeout, ResolverError, network) → surface message and auto-pivot to upload form with the URL preserved as a hint.
- **Why not worker-side:** ViralTracker is internal-team scale; concurrent sessions are low single-digits. Streamlit's per-session threading + yt-dlp being network-bound (not CPU-bound) means cross-session contention is minimal in practice. The "instant failure feedback" is genuinely valuable UX since most yt-dlp failures (invalid URL, private video) surface in the first 1-2 seconds. If concurrency becomes a problem, moving to worker-side is a localized refactor.

### Kill switch (defensive)

Add an env var `QUICK_URL_RESOLVER_ENABLED` (default `true`). The UI checks it before showing the URL field. If FB breaks yt-dlp at 2am and we need to stop the bleeding, flip the env var → users see only the upload form. No code rollback needed. ~5 LOC.

## DB Changes

Single migration. No new tables — extend `competitor_intel_packs`:

```sql
-- migrations/2026-05-XX_quick_intel_packs.sql

ALTER TABLE competitor_intel_packs
  ALTER COLUMN competitor_id DROP NOT NULL,
  ADD COLUMN source_type TEXT NOT NULL DEFAULT 'competitor'
    CHECK (source_type IN ('competitor', 'quick_url', 'quick_upload')),
  ADD COLUMN source_url TEXT,
  ADD COLUMN source_video_storage_path TEXT;

CREATE INDEX idx_competitor_intel_packs_source_type
  ON competitor_intel_packs(organization_id, source_type, created_at DESC);

-- For duplicate-URL detection (canonicalized URL stored in source_url)
CREATE INDEX idx_competitor_intel_packs_source_url
  ON competitor_intel_packs(organization_id, source_url)
  WHERE source_url IS NOT NULL;

-- Concurrency guard: prevent two simultaneous resolves of the same URL.
-- Allows multiple complete rows over time (re-runs are intentional);
-- only blocks two pack rows being 'pending' on the same URL at once.
CREATE UNIQUE INDEX idx_competitor_intel_packs_pending_url
  ON competitor_intel_packs(organization_id, source_url)
  WHERE source_url IS NOT NULL AND status = 'pending';

COMMENT ON COLUMN competitor_intel_packs.source_type IS
  'Pack provenance: competitor (existing flow), quick_url (yt-dlp from FB URL), quick_upload (user-uploaded file)';
COMMENT ON COLUMN competitor_intel_packs.source_url IS
  'Original FB URL for quick_url packs; null otherwise';
COMMENT ON COLUMN competitor_intel_packs.source_video_storage_path IS
  'Supabase storage path for the single video in quick packs; null for competitor packs (which reference competitor_ad_assets)';
```

**Why extend vs. parallel table:** `aggregate_extractions()`, `remix_video()`, the Video Details tab, and `save_to_angle_pipeline()` all read from the pack record. Forking into a `quick_intel_packs` table doubles the read paths in the UI for no benefit.

### Duplicate URL handling

Decision (Issue 2 = 2D): we do **not** wire quick packs into `competitor_intel_video_cache`. Instead, dedupe at the pack level using canonicalized URLs:

- On Analyze, before resolver runs: query for existing pack with same `canonical_source_url + organization_id`.
- **If found** and the existing pack has `status='complete'`: show modal with **three** explicit options:
  1. **View existing pack** — link to the pack page (no new pack created, no work done).
  2. **Use existing extraction (free)** — create a new pack row pointing at the same `source_video_storage_path`, with `video_analyses` and `pack_data` copied from the existing pack, `status='complete'`. **No yt-dlp, no Gemini call, no worker job.** Useful when the user wants the pack tied to a different brand/product without re-analyzing.
  3. **Re-run extraction** — create a new pack row pointing at the same `source_video_storage_path`, `status='pending'`, enqueue a fresh `quick_intel_analysis` job. Skips the yt-dlp download (we already have the file) but DOES re-run Gemini. Use when the underlying pipeline has improved and you want a fresh extraction.
- **If found but `status='pending'`**: warn "this URL is currently being analyzed — wait for that pack to complete" and link to it. Don't allow a parallel resolve (the pending-only unique index would block it anyway).
- **If found but `status='failed'`**: allow proceed (creates a fresh pack via normal resolver path).

URL canonicalization (must be applied on both insert and lookup):

```python
def canonicalize_fb_url(url: str) -> str:
    """Normalize FB URL for dedupe.

    Strips: www. and m. subdomains, query params (except v= for /watch and id= for /ads/library),
    trailing slash, fragment. Lowercases host.
    """
    # Implementation: urlparse + manual rebuild.
    # Examples:
    #   m.facebook.com/61586/posts/12345/?ref=share  → facebook.com/61586/posts/12345
    #   www.facebook.com/watch/?v=99&ref=copy        → facebook.com/watch/?v=99
    #   facebook.com/61586/posts/12345#comment       → facebook.com/61586/posts/12345
```

### Migration Audit (must do before merging migration)

This is a **pre-merge gating step**, not optional. The migration changes `competitor_id NOT NULL → NULL` on a shared table.

```bash
grep -rn "competitor_intel_packs" viraltracker/ --include="*.py"
grep -rn "\.competitor\b" viraltracker/ui/pages/14_*.py viraltracker/services/competitor_intel_service.py
```

For every match, confirm:
1. No `INNER JOIN competitors ON ...` that would silently drop quick packs from listings (LEFT JOIN is fine).
2. No `pack.competitor.name` access without a None guard (will KeyError on quick packs).
3. Any `.filter(competitor_id=...)` either keeps working or explicitly filters by `source_type='competitor'`.

## New Service Methods

### `viraltracker/services/competitor_intel_service.py`

Four explicit public methods (UI picks which to call after the dup-check). All return a fresh `pack_id` — there is no "returns existing pack" overload.

```python
async def create_quick_pack_from_url(
    self,
    url: str,
    brand_id: str,
    product_id: str,
    organization_id: str,
) -> str:
    """Run resolver + full pipeline. Returns NEW pack_id.

    Caller must have already checked for duplicates and decided that fresh
    extraction is wanted. This method always runs yt-dlp.

    Raises:
        ResolverError: yt-dlp could not extract the video.
        ValueError: URL not a recognised FB pattern.
    """

async def create_quick_pack_from_upload(
    self,
    file_bytes: bytes,
    filename: str,
    brand_id: str,
    product_id: str,
    organization_id: str,
) -> str:
    """Upload + full pipeline. Returns NEW pack_id."""

async def copy_existing_pack(
    self,
    source_pack_id: str,
    brand_id: str,
    product_id: str,
    organization_id: str,
) -> str:
    """For 'Use existing extraction' modal action.
    Creates a NEW pack pointing at source_pack's storage_path,
    copying video_analyses + pack_data, status='complete'.
    No resolver, no Gemini, no worker job.
    Returns NEW pack_id.
    """

async def re_run_extraction(
    self,
    source_pack_id: str,
    brand_id: str,
    product_id: str,
    organization_id: str,
) -> str:
    """For 'Re-run extraction' modal action.
    Creates a NEW pack pointing at source_pack's storage_path, status='pending',
    enqueues quick_intel_analysis job. Skips yt-dlp (file already in storage)
    but runs fresh Gemini extraction.
    Returns NEW pack_id.
    """

async def _create_quick_pack(
    self,
    video_bytes: bytes,
    mime_type: str,
    source_type: str,                # 'quick_url' | 'quick_upload'
    source_url: Optional[str],       # canonicalized
    brand_id: str,
    product_id: str,
    organization_id: str,
) -> str:
    """Shared private helper for the two resolver-using paths.
    Order: resolve org → upload → insert → enqueue.
    """
```

`_create_quick_pack` execution order (safety-first):

1. **Resolve `organization_id`** if it's `"all"` (superuser) using the `_resolve_org_id(organization_id, brand_id)` pattern from CLAUDE.md. **Required** before any insert.
2. **Generate `pack_uuid` client-side** (`uuid4()`). Lets us write the storage path before we have a DB row.
3. **Upload to Supabase**: `quick-intel/{organization_id}/{pack_uuid}/video.mp4`. If this fails, abort — no DB row exists yet.
4. **Insert pack row** with the known `pack_uuid`, `status='pending'`, all source fields, `competitor_id=NULL`. If this fails, the blob is orphaned in storage; log for a periodic cleanup sweep.
5. **Enqueue `quick_intel_analysis` job** with `parameters: {pack_id, brand_id, product_id, organization_id}` and `next_run_at = NOW() + 1 minute`. If enqueue fails, `UPDATE pack SET status='failed', error='enqueue failed'` so the UI doesn't show a perma-pending pack.
6. **Return `pack_id`** to the caller.

### Dup-check happens in the UI

The UI (`14_🔎_Competitor_Intel.py`) calls `_find_existing_quick_pack(canonicalized_url, organization_id)` before any service method. Based on the result, the UI shows the modal and calls one of:

- `create_quick_pack_from_url(url, ...)` (no existing OR existing failed)
- `copy_existing_pack(source_pack_id, ...)` (user chose "Use existing extraction")
- `re_run_extraction(source_pack_id, ...)` (user chose "Re-run extraction")

The service methods are unaware of the dup-check; they each do exactly one thing. This keeps the API contract clean: every method returns a NEW `pack_id`, no overloads.

### New module `viraltracker/services/fb_video_resolver.py`

```python
class ResolverError(Exception):
    """yt-dlp could not extract the video."""

# UX guard only — "looks like a Facebook URL". NOT a guarantee yt-dlp will succeed.
# yt-dlp explicitly states URL support cannot be reliably pre-detected; the resolver
# itself is the source of truth. This regex just catches obvious typos before the
# user waits for a yt-dlp round-trip.
LOOKS_LIKE_FB = re.compile(r'(?:^|//)(?:[a-z0-9-]+\.)?facebook\.com/', re.I)

def looks_like_fb_url(url: str) -> bool:
    """UX guard. Returns True if URL plausibly points at FB.
    Does NOT guarantee yt-dlp will extract it.
    """
    return bool(LOOKS_LIKE_FB.search(url))

def canonicalize_fb_url(url: str) -> str:
    """Normalize for dedupe. Strips m./www. subdomains, fragment,
    and tracking query params. See doc above for examples.
    """

def resolve_fb_video(
    url: str,
    timeout: float = 90.0,
    size_cap_mb: int = 100,
) -> tuple[bytes, str]:
    """Return (video_bytes, mime_type). Raises ResolverError on failure.

    Wall-clock timeout enforced via concurrent.futures.ThreadPoolExecutor
    (yt-dlp's own socket_timeout is per-socket, not end-to-end).
    Validates output is video (rejects photo/story content).
    Raises ResolverError on: timeout, private video, non-video content,
    404, geoblock, size > size_cap_mb.
    """
```

Self-contained module. No DB or service dependencies. Easy to unit-test with VCR-style fixtures.

## Worker

New job type `quick_intel_analysis` in `scheduler_worker.py`:

```python
def execute_quick_intel_analysis_job(job, ...):
    # parameters: { pack_id, brand_id, product_id, organization_id }
    # 1. Load pack — already has source_video_storage_path set by UI.
    # 2. Generate synthetic asset_id (UUID4) for analyze_single_video signature.
    #    (Not used as a cache key — quick packs cache via storage_path reuse.)
    # 3. extraction = analyze_single_video(synthetic_asset_id, storage_path)
    # 4. pack_data = aggregate_extractions([extraction], [1.0])
    # 5. Update pack: video_analyses=[extraction], pack_data, status='complete'.
    # 6. Use _reschedule_after_failure() pattern on exception.
    #    Max 3 retries; on final failure set status='failed' and write activity event.
```

Add routing entry in the job dispatch table around line 1004 (alongside `competitor_intel_analysis`).

**Why a separate job type instead of branching `competitor_intel_analysis`:** the existing job spends most of its work on `score_competitor_ads()` (top-N selection over many ads) which is irrelevant here. Cleaner to have a small dedicated handler than guard every step with `if mode == 'quick'`.

## UI Changes

### `viraltracker/ui/pages/14_🔎_Competitor_Intel.py` — Tab 1 mode toggle

```
[ Mode: ( ) Competitor   (•) Quick URL ]

If Quick URL:
  Brand:      [render_brand_selector(include_product=True)]
  FB Video URL:  [text input]   [Analyze]
  -- OR --
  Upload video: [drag-drop .mp4, ≤ 100MB]   [Analyze]
  ⓘ Supports posts, reels, watch, and ad library URLs.

If Competitor:  (existing UI unchanged)
```

Flow on Analyze click (URL path):

1. Sanity check: `fb_video_resolver.looks_like_fb_url(url)`. If not → inline error "doesn't look like a Facebook URL". This is just a typo guard.
2. Canonicalize: `canonical = canonicalize_fb_url(url)`.
3. Dup-check: query for an existing pack with `source_url = canonical AND organization_id = ?`.
   - **status='complete'** → show modal with three buttons:
     - **View existing pack** → redirect, no service call.
     - **Use existing extraction (free)** → call `copy_existing_pack(source_pack_id)`.
     - **Re-run extraction** → call `re_run_extraction(source_pack_id)`.
   - **status='pending'** → toast "this URL is currently being analyzed" + link to that pack. No new pack.
   - **status='failed'** → fall through to step 4 (proceed with fresh resolve).
   - **no match** → fall through to step 4.
4. Show `st.spinner("Resolving video…")`. Call `create_quick_pack_from_url(canonical, ...)` — service method runs the resolver internally with 90s wall-clock cap.
5. On `ResolverError` (any cause: timeout, private, geoblock, etc.): show error message, render upload form below with URL preserved as a hint *("Couldn't fetch from URL — drop the .mp4 here.")*.
6. On success: redirect to pack page (status='pending' until worker completes). UI auto-refreshes (via `time.sleep` + `st.rerun()` pattern already used for competitor packs).
7. **Kill switch:** if `os.getenv("QUICK_URL_RESOLVER_ENABLED", "true") != "true"`, hide the URL field and show only the upload form with a notice "URL resolver is temporarily disabled."

### Sidebar pack history

Currently labels packs by competitor name. Update to handle source types:

```python
if pack.source_type == 'competitor':
    label = competitor_name
elif pack.source_type == 'quick_url':
    label = f"Quick: {urlparse(pack.source_url).path[:40]}…"
else:  # quick_upload
    label = "Quick: uploaded video"
```

### Tabs 2 & 3 — no changes

Video Details and Remix & Save already render off `pack.video_analyses` and `pack.pack_data`. They work unchanged.

## Candidate Source Tracking

`save_to_angle_pipeline()` currently writes `source_type=COMPETITOR_INTEL` on candidates. Add a new enum value `QUICK_INTEL` so candidate provenance is honest.

**Implementation note:** Do NOT change `save_to_angle_pipeline()`'s public signature. Read `pack.source_type` internally and pick the candidate `source_type` enum based on it:

```python
def save_to_angle_pipeline(self, pack_id, product_id, organization_id, brand_id=None):
    pack = self.get_pack(pack_id)
    candidate_source = (
        CandidateSourceType.QUICK_INTEL
        if pack.source_type in ('quick_url', 'quick_upload')
        else CandidateSourceType.COMPETITOR_INTEL
    )
    # ... rest unchanged
```

Steps:

- Find the enum (likely in `viraltracker/services/angle_candidate_service.py` or `viraltracker/services/models.py`).
- Add `QUICK_INTEL = "quick_intel"`.
- Update `save_to_angle_pipeline()` body (not signature) to derive enum from pack.
- **Validation consistency check** (per CLAUDE.md): grep for `COMPETITOR_INTEL` and audit every layer (API models, service models, agent code, UI dropdowns) — anywhere the enum is whitelisted, add `QUICK_INTEL`.

```bash
grep -rn "COMPETITOR_INTEL" viraltracker/ --include="*.py"
```

## Edge Cases & Risks

1. **yt-dlp fails** (FB changed selectors, video private, regional block, photo post) → catch in resolver, surface error in UI, prompt for upload with URL preserved as hint.
2. **yt-dlp timeout (90s hard cap)** → same fallback path as #1.
3. **Resolver returns non-video content** (photo post URL) → `is_supported_fb_url` should not match, but if it does, resolver validates the downloaded mime and rejects with `ResolverError`.
4. **Audio-stripped FB video** (some posts serve video without audio to anonymous viewers) → resolver succeeds; analyze proceeds; surface a warning on the pack page *"Audio missing — extraction quality may be reduced."*
5. **Video > 100MB** — Gemini limits + storage cost. Reject upload with clear message; for URL flow, resolver checks size before returning bytes.
6. **Duplicate URL in same org** — see Cache strategy above. Soft modal with view-or-re-pack choice. Re-pack is free (no Gemini call).
7. **`competitor_id` nullable migration** — see Migration Audit (pre-merge gating step).
8. **Org resolution** — `"all"` superuser case must be handled (see CLAUDE.md `_resolve_org_id` pattern). `_create_quick_pack` MUST call it before any insert.
9. **yt-dlp dependency** — adds ~20MB; pure Python core but ffmpeg required at runtime for many FB videos (see Deployment Prerequisites). **Pin to current major release with no upper bound** in `pyproject.toml` (e.g., `yt-dlp>=2026.4.0`). FB selectors break frequently; we WANT to pull updates eagerly. Plan to bump on every dependabot PR rather than quarterly.
10. **Activity feed** — mirror competitor pack events for quick packs (same `activity_events` writes; differ only in `source_type` field).
11. **Streamlit upload size limit** — default Streamlit max is 200MB; we cap at 100MB. Configure `[server] maxUploadSize = 100` in `.streamlit/config.toml` if not already set.
12. **Storage cleanup** — quick packs accumulate forever (per decision). Each video ≈ 5-50MB. Track storage usage; revisit if it becomes a cost issue.
13. **Storage upload → DB insert ordering** — see `_create_quick_pack` order. Upload-then-insert means DB never references missing storage; orphan blobs from rare insert failures are logged and cleaned by a periodic sweep.
14. **Pack stuck in 'pending'** — worker uses `_reschedule_after_failure` with max 3 retries. After 3 failures, set `status='failed'` with the error message. UI shows "Failed: {msg}" with a "Retry" button on the pack page.
15. **ffmpeg dependency** — promoted to Deployment Prerequisites (top of plan). Not optional.

## Failure Modes Coverage

For each new codepath:

| Failure | Test? | Error handling? | User sees clear message? |
|---|---|---|---|
| yt-dlp returns invalid URL | YES (unit) | YES — fallback to upload | YES |
| yt-dlp timeout (90s) | YES (unit, mocked) | YES — fallback to upload | YES |
| Photo post URL (not video) | YES (unit) | YES — ResolverError | YES |
| Video > 100MB | YES (unit) | YES — ResolverError | YES |
| Supabase upload fails | YES (service test) | YES — abort, no DB row | YES |
| DB insert fails after upload | NO — needs add | YES — logged + cleanup sweep | NO — silent (orphan blob); flag |
| Job enqueue fails after insert | YES (service test) | YES — pack marked failed | YES |
| Worker job exception | YES (worker test) | YES — _reschedule_after_failure, 3 retries, then status='failed' | YES |
| Audio-stripped FB video | NO — needs add | YES — warning shown | YES |
| Concurrent dup URL submissions | NO — needs add (race) | NEEDS DECISION | partial |

**Critical gap flag:** "DB insert fails after upload" → silent orphan in storage. Mitigation: log structured event for a daily cleanup script. Track as a TODO if not built in MVP. **Recommend:** add to MVP since it's ~10 LOC.

**Critical gap flag:** "Concurrent dup URL submissions" — two users in same org submit same URL within 5s. Both miss the dup-check, both run resolver, both insert a pack. Race. Mitigation: unique partial index on `(organization_id, source_url) WHERE status IN ('pending','complete')` would force one to fail; UI catches the constraint violation and re-runs the dup-detect. **Recommend:** include the unique index in the migration.

## Test Plan

### Unit tests

- `fb_video_resolver.is_supported_fb_url()` — table-driven test with all five URL patterns + invalid patterns.
- `fb_video_resolver.resolve_fb_video()` — VCR fixtures for: post URL (success), reel URL (success), private video (ResolverError), photo post (ResolverError), oversized video (ResolverError), timeout (mocked, ResolverError).

### Service tests

- `_create_quick_pack` happy path — mocked storage + DB; verify upload→insert→enqueue order; verify pack_id returned.
- `_create_quick_pack` upload failure — verify no DB row written.
- `_create_quick_pack` insert failure — verify orphan blob is logged.
- `_create_quick_pack` enqueue failure — verify pack updated to status='failed'.
- `_create_quick_pack` with `organization_id="all"` — verify `_resolve_org_id` called and replaces `"all"` with real UUID.
- `create_quick_pack_from_url` duplicate URL hit — verify `_copy_pack` called, no resolver invocation, no worker job enqueued.
- `_copy_pack` — verify new pack row references same storage path, status='complete', extraction copied.

### Worker test

- `execute_quick_intel_analysis_job` happy path — seeded pack with real video file in test storage; assert `pack_data` populated, status='complete'.
- `execute_quick_intel_analysis_job` failure path — Gemini mock raises; verify reschedule + retry counter; on 4th attempt, status='failed'.

### Migration tests (CRITICAL — regression risk)

- **REGRESSION:** existing competitor packs continue to load and render after the migration applies. Seed a competitor pack pre-migration, apply migration, verify pack still appears in list view and Tab 2/3 render correctly.
- **REGRESSION:** existing `competitor_intel_analysis` worker job still runs end-to-end after migration.
- **NEW:** quick_url and quick_upload packs insert successfully with `competitor_id=NULL`.
- **NEW:** unique partial index prevents concurrent duplicate inserts (force two transactions, second errors).

### UI / Integration

- Mode toggle renders both forms.
- Bad URL → inline error, no spinner triggered.
- Resolver error → upload fallback form rendered with URL preserved.
- Duplicate URL → modal renders with view/re-pack choice; re-pack creates new pack with status='complete' immediately.
- Quick URL → analysis → video details visible → remix produces a script → save to angle pipeline produces candidates with `source_type=QUICK_INTEL`.
- Competitor mode still works (full regression check on Tab 1, Tab 2, Tab 3).
- Superuser with `org="all"` selected can run quick mode end-to-end.

### Manual QA checklist

- [ ] Paste user's example URL `https://www.facebook.com/61586899633782/posts/122123859525229987/` → completes successfully.
- [ ] Paste a private video URL → falls back to upload cleanly.
- [ ] Upload a 50MB .mp4 → completes successfully.
- [ ] Re-paste same URL within an hour → modal offers view/re-pack; re-pack completes in <5s.
- [ ] Tab 2 shows transcription/hook/persona/etc.
- [ ] Tab 3 remix → script generated.
- [ ] Save to angle pipeline → candidates appear in Research Insights with `QUICK_INTEL` provenance.

## NOT in Scope

| Item | Why deferred |
|---|---|
| Apify FB-posts actor as second fallback | yt-dlp is reliable enough for MVP; revisit if it breaks |
| Bulk URL input | MVP focuses on single-video flow; bulk is a separate UX |
| Cross-pack remix (compare two quick videos) | Requires UI redesign; defer to v2 |
| TikTok / Instagram URL support | yt-dlp handles them but expanding to other platforms is a product decision, not an eng decision |
| Per-org cost guardrails (UsageTracker integration) | Trust the operator in MVP; add if abuse appears |
| `competitor_intel_video_cache` integration for quick packs | Cache strategy 2D (storage+extraction reuse on dup URL) is simpler |
| Audio-missing detection automation | Manual "warning" via existing extraction's audio fields is good enough for MVP |

## What Already Exists (Reused, Not Rebuilt)

| Concern | Reused asset |
|---|---|
| Per-video extraction | `analyze_single_video()` |
| Pack aggregation | `aggregate_extractions()` (handles `n=1`) |
| Remix script generation | `remix_video()` (no `competitor_id` needed) |
| Save to angle pipeline | `save_to_angle_pipeline()` (already competitor-free in writes) |
| Pack table | Extended (not duplicated) |
| Storage upload | Existing Supabase pattern |
| Worker job pattern | "Run Now" with `next_run_at = now() + 1m` (existing) |
| Org resolution | `_resolve_org_id` pattern from CLAUDE.md |
| Job retry/failure | `_reschedule_after_failure()` |

## Files Touched

| File | Change |
|---|---|
| `migrations/2026-05-XX_quick_intel_packs.sql` | NEW |
| `viraltracker/services/fb_video_resolver.py` | NEW |
| `viraltracker/services/competitor_intel_service.py` | +3 methods (`_create_quick_pack`, `create_quick_pack_from_url`, `create_quick_pack_from_upload`, `_find_existing_quick_pack`, `_copy_pack`); update `save_to_angle_pipeline` body (not signature) |
| `viraltracker/services/angle_candidate_service.py` (or wherever enum lives) | +1 enum value `QUICK_INTEL` |
| `viraltracker/worker/scheduler_worker.py` | +1 job handler `execute_quick_intel_analysis_job`, +1 routing entry |
| `viraltracker/ui/pages/14_🔎_Competitor_Intel.py` | Tab 1 mode toggle, sidebar label tweak, dup-URL modal |
| `pyproject.toml` | +`yt-dlp>=2026.4.0` (no upper bound — track latest) |
| `.streamlit/config.toml` | `maxUploadSize = 100` if not already set |

## Scope Split

### MVP (single PR, ~1.5 days)

- yt-dlp resolver + upload fallback (with 90s timeout)
- DB migration (with unique partial index on `source_url`)
- Two public service methods + shared `_create_quick_pack` helper
- Duplicate-URL detection + view/re-pack modal
- Worker handler with retry + failure status
- UI mode toggle on Tab 1
- New `QUICK_INTEL` candidate source enum
- Pack history label fix
- Orphan blob logging for periodic cleanup

### Follow-ups (defer)

- Apify actor as second fallback after yt-dlp
- Bulk URL input (queue N URLs → N packs)
- Cross-pack remix ("compare these two quick videos")
- TikTok / Instagram URL support
- Per-org Gemini cost guardrails (UsageTracker)
- Periodic orphan-blob cleanup script

## Decisions Locked

1. **URL patterns:** support posts, reels, watch, and ad library URLs (yt-dlp handles all).
2. **Pack persistence:** keep forever (same as competitor packs).
3. **Naming:** "Quick URL" mode.
4. **Resolver location:** UI-side, synchronous, 90s hard timeout, spinner, fallback to upload on any error.
5. **Cache strategy:** No new cache table use. On duplicate URL: offer view-existing or re-pack (which copies storage_path + extraction = free re-analysis).
6. **Cost guardrail:** None in MVP. Trust the operator. Add if abuse appears.
7. **Concurrency safety:** Unique partial index on `(organization_id, source_url) WHERE source_url IS NOT NULL AND status IN ('pending','complete')` to prevent dup-URL races.
8. **Transaction order in `_create_quick_pack`:** resolve org → upload → insert → enqueue. Orphan blobs on rare insert failure are logged for cleanup sweep.
9. **`save_to_angle_pipeline` modification:** body-only, no signature change. Read `pack.source_type` internally.
10. **DRY:** Shared `_create_quick_pack` private helper for both URL and upload paths.
11. **Re-pack semantics (post-codex fix):** Modal offers three actions, not two — View / Use existing extraction / Re-run extraction. Each maps to a distinct service method. No method has overloaded "returns existing or new" semantics.
12. **Wall-clock timeout:** `concurrent.futures` wrapper around yt-dlp call (yt-dlp's `socket_timeout` is per-socket, not end-to-end).
13. **URL canonicalization:** `canonicalize_fb_url()` strips `m./www.` subdomains, fragments, and tracking query params before insert/lookup. Required for dedupe to work.
14. **Pre-validation regex** is a UX typo guard only ("looks like FB?"), not a "this will work" predictor. yt-dlp itself is the authority.
15. **Concurrency index changed:** unique partial index is on `WHERE status = 'pending'` only (not 'pending' + 'complete'). Allows multiple complete rows for the same URL (re-runs) but blocks two simultaneous resolves.
16. **Kill switch:** `QUICK_URL_RESOLVER_ENABLED` env var lets ops disable the URL field without code rollback if FB breaks yt-dlp.
17. **yt-dlp pin:** `>=2026.4.0` with no upper bound. Updates pulled eagerly via Dependabot, not quarterly.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | not run (feature increment, not strategic shift) |
| Codex Outside Voice | `codex exec` | Independent plan challenge | 1 | CLEAR | 15 issues raised; 7 must-fix bugs caught + folded in; 4 verifications added; 2 strategic-call resolved with user; 2 reframed as defensible |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR (PLAN) | 12 issues raised, all resolved; 0 unresolved, 0 critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | not needed (UI change is a mode toggle + dup-URL modal on existing tab) |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | not applicable (internal feature, no external API surface) |

**CODEX:** Caught 7 real bugs the eng review missed — most importantly: unique-index conflicting with re-pack semantics, the API contract self-contradicting, "re-pack" being false advertising for cache replay, and `socket_timeout` not being a wall-clock timeout. All folded in.

**CROSS-MODEL:** Both reviews agreed on architecture (UI-side resolver, extend pack table, separate worker job). Codex pushed harder on the cache/dup-URL implementation details and was right.

**UNRESOLVED:** 0
**VERDICT:** ENG + OUTSIDE VOICE CLEARED — ready to implement when ad creation run completes.
