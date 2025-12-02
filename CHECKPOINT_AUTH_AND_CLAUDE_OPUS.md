# Checkpoint: Authentication & Claude Opus Hook Selection

**Date:** 2025-12-02
**Branch:** main
**Status:** Ready for testing

## Summary

Two major changes in this checkpoint:
1. Added password protection to Streamlit UI with 90-day persistent sessions
2. Switched hook selection/adaptation from Gemini to Claude Opus 4.5

---

## 1. Streamlit Authentication

### Features
- Password-only login (no username)
- 90-day persistent sessions via signed cookies in localStorage
- Logout button in sidebar
- All 12 pages protected by default
- Easy to create public pages for clients

### Configuration

Add to Railway environment variables:
```
STREAMLIT_PASSWORD=your-secure-password
```

Optional:
```
STREAMLIT_COOKIE_KEY=custom-signing-key
STREAMLIT_COOKIE_EXPIRY_DAYS=90
```

### Files Added/Modified
- `viraltracker/ui/auth.py` (new) - Authentication module
- `viraltracker/ui/app.py` - Added auth check
- `viraltracker/ui/pages/*.py` - Added auth check to all 11 pages
- `requirements.txt` - Added streamlit-authenticator, extra-streamlit-components
- `docs/DEVELOPER_GUIDE.md` - Added authentication documentation

### Creating Public Pages

**Option 1:** Use the `public` parameter
```python
from viraltracker.ui.auth import require_auth
require_auth(public=True)
```

**Option 2:** Add to whitelist in `viraltracker/ui/auth.py`:
```python
PUBLIC_PAGES = ["Client_Gallery.py", "Public_Report.py"]
```

---

## 2. Claude Opus for Hook Selection

### Change
Switched `select_hooks()` function from Gemini 2.0 Flash to Claude Opus 4.5 for better ad copy quality.

### Updated Ad Creation Workflow

| Step | Model |
|------|-------|
| Hook Selection & Adaptation | **Claude Opus 4.5** (changed) |
| Reference Ad Analysis | Claude Opus 4.5 |
| Image Generation | Gemini 3 Pro Image Preview |
| Ad Review (dual) | Claude Sonnet 4.5 + Gemini 2.0 Flash |

### File Modified
- `viraltracker/agent/agents/ad_creation_agent.py` - Lines 730-770

---

## Testing Checklist

### Authentication
- [ ] Set `STREAMLIT_PASSWORD` in Railway
- [ ] Visit any page - should see login form
- [ ] Enter password - should authenticate
- [ ] Check "Remember me" - should persist after browser close
- [ ] Logout button in sidebar works
- [ ] Session persists for 90 days

### Ad Creation with Claude Opus
- [ ] Create new ad run
- [ ] Check logs for "model: claude-opus-4-5" in hook selection
- [ ] Verify hook adaptations are higher quality
- [ ] Review generated ad copy

---

## Rollback

If issues arise:

**Authentication:** Remove `STREAMLIT_PASSWORD` env var to disable auth

**Hook Selection:** Revert to Gemini by changing line 740 in ad_creation_agent.py:
```python
# Change from:
model="claude-opus-4-5-20251101"
# To:
# Use ctx.deps.gemini.analyze_text() instead
```
