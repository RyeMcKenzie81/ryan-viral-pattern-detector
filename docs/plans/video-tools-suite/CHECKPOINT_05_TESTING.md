# Video Tools Suite - Testing Checkpoint

**Date:** 2026-02-26
**Branch:** `feat/ad-creator-v2-phase0` (merged from `feat/chainlit-agent-chat`)
**Previous Checkpoint:** `CHECKPOINT_04_RECREATION_PIPELINE.md`

---

## Status: All 5 Phases Implemented, Testing In Progress

### Merged to `feat/ad-creator-v2-phase0`
- All Video Tools Suite code (Phases 1-5) merged cleanly — no conflicts
- 238 unit tests passing
- Both migrations run in Supabase

### Bugs Found During Testing

#### Bug 1: Superuser "all" org_id passed as UUID (FIXED)
- **Error:** `invalid input syntax for type uuid: "all"` (Postgres 22P02)
- **Location:** `instagram_analysis_service.py` lines 1115, 1170
- **Root cause:** `get_analyses_for_brand()` and `_get_brand_id_for_post()` passed `organization_id="all"` directly to `.eq()` without superuser check
- **Fix:** Added `if organization_id != "all"` guard before `.eq("organization_id", ...)`, matching pattern already used in `instagram_content_service.py`
- **Commit:** `545cf4c` on `feat/ad-creator-v2-phase0`

#### Bug 2: NULL handle when adding watched account (OPEN)
- **Error:** `null value in column "handle" of relation "accounts" violates not-null constraint` (Postgres 23502)
- **Location:** `instagram_content_service.py` — `add_watched_account()` method
- **Root cause:** When creating a new account record in the `accounts` table, the `handle` column is not being populated. The failing row shows `handle=null` but `platform_username=thepetguide0`.
- **Fix needed:** Set `handle` to the username when inserting into `accounts` table. Find the insert into `accounts` in `add_watched_account()` and ensure `handle` is set (likely should be same as `platform_username`).
- **File:** `viraltracker/services/instagram_content_service.py` — search for `add_watched_account` method, find the accounts table insert

### Tech Debt Added
- Item #40: Replace audio-first workflow with ElevenLabs Voice Changer post-processing (in `docs/TECH_DEBT.md`)

### Files on `feat/ad-creator-v2-phase0`
- All Video Tools Suite files from `feat/chainlit-agent-chat` (28 files, 12,831 lines)
- `scripts/test_video_recreation.py` — integration test script (on worktree only, not yet merged)
- `docs/TECH_DEBT.md` — updated with item #40 (on main repo)

### Testing Script
```bash
# Smoke test (score + adapt, cheap)
python scripts/test_video_recreation.py --step adapt

# Full pipeline with VEO (costs money)
python scripts/test_video_recreation.py --generate --voice-id YOUR_VOICE_ID
```

### Environment
- Push: `git push origin feat/ad-creator-v2-phase0`
- Worktree push: `git push origin worktree-feat/chainlit-agent-chat:feat/chainlit-agent-chat`
- All 238 unit tests passing
- Both migrations executed in Supabase
- Wonder Paws brand ID: `bc8461a8-232d-4765-8775-c75eaafc5503`

### Next Steps
1. Fix Bug 2 (NULL handle on account insert)
2. Add a watched account successfully
3. Run scrape + outlier detection + analysis
4. Test the Video Studio scoring pipeline
5. Test storyboard adaptation
6. (Optional) Test VEO clip generation
