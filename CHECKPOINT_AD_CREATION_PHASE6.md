# Facebook Ad Creation Agent - Phase 6 Checkpoint

**Status**: Phases 1-5 COMPLETE ✅ | Ready for Phase 6: Streamlit Chat Integration

---

## What Has Been Completed

### Phase 1: Database & Models ✅ (MERGED to main)
- Database schema for ad creation workflow
- Pydantic models for requests/responses
- Service layer (AdCreationService)

### Phase 2: All 14 Agent Tools ✅ (MERGED to main)
**Data Retrieval Tools (1-4)**:
1. `get_product_with_images` - Fetch product data from Supabase
2. `get_hooks_for_product` - Retrieve viral hooks from database
3. `get_ad_brief_template` - Get ad brief structure
4. `upload_reference_ad` - Upload reference ad to Supabase Storage

**Analysis & Generation Tools (5-10)**:
5. `analyze_reference_ad` - Claude vision analysis
6. `select_hooks` - Smart hook selection
7. `select_product_images` - Choose best product images
8. `generate_nano_banana_prompt` - Create Gemini prompt
9. `execute_nano_banana` - Generate ad via Gemini
10. `save_generated_ad` - Save to database & storage

**Review & Orchestration Tools (11-14)**:
11. `review_ad_claude` - Claude quality review
12. `review_ad_gemini` - Gemini quality review
13. `create_ad_run` - Database run tracking
14. `complete_ad_workflow` - Master orchestrator (calls all 13 others)

### Phase 3: CLI Integration ✅ (PR #3 MERGED)
- `viraltracker ad-creation create` - Generate ads from CLI
- `viraltracker ad-creation list-runs` - List workflow runs
- `viraltracker ad-creation show-run` - View run details
- File: `viraltracker/cli/ad_creation.py`

### Phase 4: API Endpoint ✅ (PR #4 CREATED)
- Endpoint: `POST /api/ad-creation/create`
- Rate limiting: 5 requests/hour
- Swagger docs at `/docs`
- File: `viraltracker/api/app.py` (updated)
- PR: https://github.com/RyeMcKenzie81/ryan-viral-pattern-detector/pull/4

### Phase 5: Integration Tests ✅ (COMPLETE)
- File: `tests/test_ad_creation_integration.py`
- 5 test suites covering:
  - End-to-end workflow
  - CLI commands
  - API endpoints
  - Database operations
  - Dual review logic (Claude + Gemini OR logic)
- Uses test instances (no mocking)

---

## Current Git State

**Branch**: `feature/ad-creation-api`
**Main Branch**: `main`
**Repository**: https://github.com/RyeMcKenzie81/ryan-viral-pattern-detector.git

**Recent Commits**:
- ✅ Phase 1-2 merged to main
- ✅ Phase 3 merged to main (PR #3)
- ⏳ Phase 4 in PR #4 (needs merge)

---

## Architecture Overview

### Agent Structure
```
ad_creation_agent (Pydantic AI)
├── Dependencies: AdCreationDependencies
│   ├── product_id: UUID
│   ├── reference_ad_base64: str
│   ├── reference_ad_filename: str
│   └── project_id: Optional[UUID]
│
└── Tools (14 total)
    ├── Data Retrieval (4)
    ├── Analysis & Generation (6)
    └── Review & Orchestration (4)
```

### Dual Review Logic (OR Logic)
- **Claude approves OR Gemini approves** = APPROVED ✅
- **Both reject** = REJECTED ❌
- **Disagreement** = FLAGGED ⚠️ (for human review)
- Minimum threshold: 0.8 for product/text accuracy

### Sequential Generation
- Generates **ONE ad at a time** (not batched)
- 5 total variations per workflow run
- Each ad saved immediately after generation

---

## Tech Stack

- **Python 3.11+**
- **Pydantic-AI** - Agent framework
- **FastAPI** - REST API
- **Click** - CLI
- **Streamlit** - UI (not yet integrated)
- **Supabase** - Database & storage
- **Claude (Anthropic)** - Vision analysis & review
- **Gemini (Google)** - Image generation (Nano Banana) & review
- **pytest** - Testing

---

## File Structure

```
viraltracker/
├── agent/
│   └── ad_creation/
│       ├── agent.py              # Main agent definition
│       ├── dependencies.py       # AgentDependencies class
│       ├── tools.py              # All 14 tools
│       └── prompts.py            # System prompts
│
├── services/
│   └── ad_creation_service.py    # Database & Supabase operations
│
├── cli/
│   └── ad_creation.py            # CLI commands
│
├── api/
│   ├── app.py                    # FastAPI app (ad creation endpoint added)
│   └── models.py                 # Pydantic request/response models
│
├── ui/
│   ├── app.py                    # Streamlit main app (NOT YET INTEGRATED)
│   └── pages/                    # Streamlit pages
│       ├── 0_🤖_Agent_Catalog.py
│       ├── 1_📚_Tools_Catalog.py
│       └── ... (5_🎨_Ad_Creator.py NOT YET CREATED)
│
└── tests/
    └── test_ad_creation_integration.py  # Integration tests
```

---

## What's Next: Phase 6 - Streamlit Chat Integration

### Goal
Enable natural language ad creation in Streamlit chat:
> "Create 5 ads for Wonder Paws Collagen 3x using this reference image"

### Current Streamlit Architecture
- **Orchestrator pattern** with 5 specialized agents:
  - Twitter Agent (8 tools)
  - TikTok Agent (5 tools)
  - YouTube Agent (1 tool)
  - Facebook Agent (2 tools - **analysis only, not creation**)
  - Analysis Agent (3 tools)
- Total: 19 tools via intelligent routing
- File: `viraltracker/ui/app.py`

### Required Changes for Phase 6

#### 1. Add Ad Creation Agent to Orchestrator
**File**: `viraltracker/agent/agent.py` (orchestrator)

Add ad creation agent as 6th specialized agent:
```python
from viraltracker.agent.ad_creation.agent import ad_creation_agent

# In orchestrator routing logic:
if "create ad" in query or "generate ad" in query:
    # Extract product name from query
    # Look up product_id in database
    # Route to ad_creation_agent
```

#### 2. Add File Upload to Streamlit Chat
**File**: `viraltracker/ui/app.py`

Current chat only supports text. Add:
```python
uploaded_file = st.file_uploader("Upload Reference Ad", type=['png', 'jpg', 'jpeg', 'webp'])
if uploaded_file:
    # Convert to base64
    # Pass to ad creation agent
```

#### 3. Create Product Name → Product ID Resolver
**New Tool Needed**: `resolve_product_name_tool`
```python
@orchestrator_agent.tool
async def resolve_product_name(ctx: RunContext, product_name: str) -> dict:
    """Look up product_id from product name in database"""
    # Query Supabase products table
    # Return product_id, name, and metadata
```

#### 4. Rich Result Display in Chat
Display generated ads as:
- Image cards with thumbnails
- Status badges (✅ APPROVED, ❌ REJECTED, ⚠️ FLAGGED)
- Ad copy text
- Download buttons

#### 5. Update Streamlit Session State
Store ad creation results in `st.session_state` for:
- History tracking
- Re-generation
- Editing/refinement

---

## Implementation Approach

### Option A: Dedicated Page (Simpler)
Create `viraltracker/ui/pages/5_🎨_Ad_Creator.py`:
- Form-based UI with dropdowns and file upload
- Traditional workflow
- Easier to implement (~200 lines)

### Option B: Chat Integration (Recommended)
Integrate into existing chat interface:
- Natural language commands
- File upload in chat
- More elegant UX
- Aligns with existing orchestrator pattern
- More complex (~500 lines across multiple files)

**User requested: Option B** ✅

---

## Key Technical Details

### Database Tables
- `products` - Product catalog with images
- `hooks` - Viral hook patterns (from Twitter analysis)
- `ad_runs` - Workflow run tracking
- `generated_ads` - Generated ad storage with reviews

### Supabase Storage
- `reference_ads/` - Uploaded reference images
- `generated_ads/` - Generated ad images (from Gemini Nano Banana)

### Environment Variables Required
```bash
ANTHROPIC_API_KEY=...      # Claude for vision & review
GEMINI_API_KEY=...         # Gemini for generation & review
SUPABASE_URL=...           # Database
SUPABASE_KEY=...           # Database auth
OPENAI_API_KEY=...         # OpenAI for orchestrator (Streamlit)
```

### Test Product Setup
Before running tests, set:
```bash
export TEST_PRODUCT_ID="your-actual-product-uuid-from-supabase"
```

Query Supabase to get a valid product ID:
```sql
SELECT id, name FROM products LIMIT 1;
```

---

## Testing Commands

```bash
# Run integration tests
pytest tests/test_ad_creation_integration.py -v

# Run without slow tests
pytest tests/test_ad_creation_integration.py -v -m "not slow"

# Run specific test suite
pytest tests/test_ad_creation_integration.py::TestDualReviewLogic -v

# Test CLI
viraltracker ad-creation create \
  --product-id UUID \
  --reference-ad path/to/image.png

# Test API (requires server running)
curl -X POST "http://localhost:8000/api/ad-creation/create" \
  -H "Content-Type: application/json" \
  -d '{"product_id": "...", "reference_ad_base64": "...", "reference_ad_filename": "test.png"}'
```

---

## Known Issues / TODO

1. ⚠️ **PR #4 needs to be merged** before Phase 6
2. ⚠️ **Product name resolver not yet implemented** (needed for natural language)
3. ⚠️ **File upload in Streamlit chat** needs implementation
4. ⚠️ **Orchestrator routing** needs ad creation agent integration
5. ⚠️ **Rich result display** for ads in chat needs design

---

## Success Criteria for Phase 6

- [ ] User can upload reference image in Streamlit chat
- [ ] User can say: "Create 5 ads for Wonder Paws Collagen 3x"
- [ ] Orchestrator extracts product name and looks up product_id
- [ ] Orchestrator routes to ad creation agent
- [ ] Agent generates 5 ads with dual review
- [ ] Results display as rich image cards in chat
- [ ] User can download approved ads
- [ ] All error scenarios handled gracefully

---

## Continuation Prompt

Use this prompt to continue in a new context window:

```
I'm continuing work on the Facebook Ad Creation Agent for the viraltracker project.

**Context**: Read the checkpoint file at `/Users/ryemckenzie/projects/viraltracker/CHECKPOINT_AD_CREATION_PHASE6.md` for full context.

**Current Status**: Phases 1-5 are COMPLETE. The ad creation agent works via CLI and API. Now we need Phase 6: Streamlit chat integration.

**Goal**: Enable natural language ad creation in Streamlit chat interface using the orchestrator pattern.

Example user query:
> "Create 5 ads for Wonder Paws Collagen 3x using this reference image [upload]"

**What to do next**:
1. Review the checkpoint file to understand current state
2. Implement ad creation agent integration into Streamlit orchestrator
3. Add file upload support to chat interface
4. Create product name → product_id resolver tool
5. Implement rich result display for generated ads
6. Test end-to-end workflow

**Tech Stack**: Python 3.11+, Pydantic-AI, Streamlit, FastAPI, Supabase, Claude, Gemini

**Repository**: https://github.com/RyeMcKenzie81/ryan-viral-pattern-detector.git
**Branch**: feature/ad-creation-api
**Working Directory**: /Users/ryemckenzie/projects/viraltracker

Let me know when you're ready to start implementing Phase 6!
```

---

## Quick Reference Commands

```bash
# Start Streamlit UI
streamlit run viraltracker/ui/app.py --server.port=8501

# Start API server
uvicorn viraltracker.api.app:app --reload --port 8000

# Run tests
pytest tests/test_ad_creation_integration.py -v

# View open PRs
gh pr list

# Merge PR #4
gh pr merge 4 --squash --delete-branch

# Create new branch for Phase 6
git checkout -b feature/streamlit-ad-creation

# Push changes
git push -u origin feature/streamlit-ad-creation
```

---

**Last Updated**: 2025-11-25
**Context Used**: 93% (this is the checkpoint before context limit)
**Next Phase**: Phase 6 - Streamlit Chat Integration
**Status**: Ready to continue in new context window ✅
