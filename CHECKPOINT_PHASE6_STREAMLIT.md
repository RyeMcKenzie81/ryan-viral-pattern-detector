# Facebook Ad Creation Agent - Phase 6 Checkpoint (IN PROGRESS)

**Status**: Phase 6 STARTED - Foundational changes complete, orchestrator integration in progress

**Last Updated**: 2025-11-25
**Branch**: `feature/ad-creation-api`
**Working Directory**: `/Users/ryemckenzie/projects/viraltracker`

---

## What Has Been Completed

### Phases 1-5 (COMPLETE ✅)
- **Phase 1**: Database & Models (MERGED to main)
- **Phase 2**: All 14 Agent Tools (MERGED to main)
- **Phase 3**: CLI Integration (MERGED to main)
- **Phase 4**: API Endpoint Integration (MERGED to main via PR #4)
- **Phase 5**: Integration Tests (COMPLETE)

### Phase 6 - Streamlit Chat Integration (IN PROGRESS ⏳)

#### Completed This Session:
1. ✅ **Analyzed existing architecture**
   - Read orchestrator pattern implementation
   - Read Streamlit UI app.py structure
   - Read ad_creation_agent.py (all 14 tools exist)
   - Understood orchestrator routing logic

2. ✅ **Made foundational code changes**
   - File: `viraltracker/agent/agents/__init__.py`
     - Added `ad_creation_agent` to exports
     - Updated documentation to show 6 agents, 33 total tools

   - File: `viraltracker/agent/orchestrator.py`
     - Added import: `from .agents import ad_creation_agent`
     - Import is complete, ready for routing tool

---

## Current Git State

**Branch**: `feature/ad-creation-api`
**Main Branch**: `main`
**Repository**: https://github.com/RyeMcKenzie81/ryan-viral-pattern-detector.git

**Modified Files (Uncommitted)**:
- `viraltracker/agent/agents/__init__.py` - Added ad_creation_agent export
- `viraltracker/agent/orchestrator.py` - Added ad_creation_agent import

**Status**: Changes ready to commit to feature branch

---

## Architecture Overview

### Current Orchestrator Pattern
```
Streamlit Chat UI
    ↓
orchestrator (OpenAI model)
    ↓
6 Specialized Agents (via routing tools):
├── Twitter Agent (8 tools)
├── TikTok Agent (5 tools)
├── YouTube Agent (1 tool)
├── Facebook Agent (2 tools - analysis only)
├── Analysis Agent (3 tools)
└── Ad Creation Agent (14 tools) ← NEW, partially integrated
```

### Ad Creation Agent (Already Exists!)
**Location**: `viraltracker/agent/agents/ad_creation_agent.py`

**14 Tools Organized by Phase**:

**Data Retrieval (1-4)**:
1. `get_product_with_images` - Fetch product from database
2. `get_hooks_for_product` - Retrieve viral hooks
3. `get_ad_brief_template` - Get brand guidelines
4. `upload_reference_ad` - Upload reference image to storage

**Analysis & Generation (5-10)**:
5. `analyze_reference_ad` - Claude vision analysis
6. `select_hooks` - AI hook selection (5 diverse)
7. `select_product_images` - Choose best product images
8. `generate_nano_banana_prompt` - Create Gemini prompt
9. `execute_nano_banana` - Generate ad via Gemini
10. `save_generated_ad` - Save to database & storage

**Review & Orchestration (11-14)**:
11. `review_ad_claude` - Claude quality review
12. `review_ad_gemini` - Gemini quality review
13. `create_ad_run` - Database run tracking
14. `complete_ad_workflow` - Master orchestrator (calls all 13 others)

**Key Features**:
- Sequential generation (one ad at a time for resilience)
- Dual AI review with OR logic (either approves = approved)
- Complete workflow: reference ad → 5 variations → dual review → storage

---

## What's Next: Remaining Phase 6 Tasks

### 1. Complete Orchestrator Integration

#### File: `viraltracker/agent/orchestrator.py`

**A. Update System Prompt** (line 32)
Add ad creation agent to the available agents list:

```python
system_prompt="""You are the Orchestrator Agent for the ViralTracker system.

**Available Specialized Agents:**

1. **Twitter Agent** - For Twitter/X operations
2. **TikTok Agent** - For TikTok operations
3. **YouTube Agent** - For YouTube operations
4. **Facebook Agent** - For Facebook Ad Library operations
5. **Analysis Agent** - For advanced analytics
6. **Ad Creation Agent** - For Facebook ad creative generation:  ← ADD THIS
   - Generate 5 ad variations from reference image
   - Analyze reference ad format with Vision AI
   - Select persuasive hooks from database
   - Execute image generation via Gemini Nano Banana
   - Dual AI review (Claude + Gemini OR logic)
   - Return production-ready ads with approval status

**Your Responsibilities:**
- Understand the user's intent
- Route to the most appropriate specialized agent
- Pass relevant context and parameters
- Coordinate multi-step workflows if needed
- Extract product names and resolve to product IDs for ad creation

**Important:**
- ALWAYS route to a specialized agent
- Use the routing tools to delegate work
- For ad creation requests, use resolve_product_name first to get product_id
- Provide clear summaries of results
"""
```

**B. Add Routing Tool** (after line 125)

```python
@orchestrator.tool
async def route_to_ad_creation_agent(
    ctx: RunContext[AgentDependencies],
    query: str,
    product_id: str,
    reference_ad_base64: str,
    reference_ad_filename: str = "reference.png"
) -> str:
    """
    Route request to Ad Creation Agent for Facebook ad generation.

    Args:
        ctx: Run context with AgentDependencies
        query: User query/instructions
        product_id: UUID of product (use resolve_product_name first)
        reference_ad_base64: Base64-encoded reference ad image
        reference_ad_filename: Filename for reference ad

    Returns:
        Agent response with generated ads and approval status
    """
    logger.info(f"Routing to Ad Creation Agent: {query}")

    # Create specialized dependencies for ad creation
    # The ad creation agent needs product_id and reference ad
    # We'll pass these via the query context
    full_query = f"""
{query}

Product ID: {product_id}
Reference Ad: [base64 image provided]
Filename: {reference_ad_filename}

Execute the complete ad creation workflow:
1. Upload reference ad
2. Analyze reference ad format
3. Fetch product data and hooks
4. Select 5 diverse hooks
5. Generate 5 ad variations
6. Dual AI review each ad
7. Return complete results with approval status
"""

    result = await ad_creation_agent.run(full_query, deps=ctx.deps)
    return result.output
```

**C. Add Product Name Resolver Tool** (after routing tools)

```python
@orchestrator.tool
async def resolve_product_name(
    ctx: RunContext[AgentDependencies],
    product_name: str
) -> dict:
    """
    Look up product_id from product name in database.

    This tool enables natural language ad creation by resolving
    product names (e.g., "Wonder Paws Collagen 3x") to database UUIDs.

    Args:
        ctx: Run context with AgentDependencies
        product_name: Product name or partial name to search

    Returns:
        Dictionary with product_id, name, and metadata:
        {
            "product_id": "uuid",
            "name": "Full Product Name",
            "brand": "Brand Name",
            "found": true
        }

    Raises:
        ValueError: If no matching product found
    """
    logger.info(f"Resolving product name: {product_name}")

    try:
        # Query Supabase products table
        supabase = ctx.deps.ad_creation.supabase

        # Search by name (case-insensitive, partial match)
        response = supabase.table('products') \
            .select('id, name, brand_id') \
            .ilike('name', f'%{product_name}%') \
            .limit(1) \
            .execute()

        if not response.data or len(response.data) == 0:
            raise ValueError(f"No product found matching: {product_name}")

        product = response.data[0]

        # Get brand name
        brand_response = supabase.table('brands') \
            .select('name') \
            .eq('id', product['brand_id']) \
            .single() \
            .execute()

        brand_name = brand_response.data['name'] if brand_response.data else 'Unknown'

        result = {
            "product_id": str(product['id']),
            "name": product['name'],
            "brand": brand_name,
            "found": True
        }

        logger.info(f"Product resolved: {result['name']} (ID: {result['product_id']})")
        return result

    except ValueError as e:
        logger.error(f"Product not found: {product_name}")
        return {
            "product_id": None,
            "name": product_name,
            "brand": None,
            "found": False,
            "error": str(e)
        }
    except Exception as e:
        logger.error(f"Failed to resolve product: {str(e)}")
        raise Exception(f"Failed to resolve product name: {str(e)}")
```

**D. Update Logger Message** (line 127)
```python
logger.info("Orchestrator Agent initialized with 7 routing tools (including ad creation)")
```

---

### 2. Add File Upload to Streamlit Chat

#### File: `viraltracker/ui/app.py`

**Current Limitation**: Chat interface only supports text input.

**Required Changes**:

**A. Add Upload Widget** (around line 505, before chat input)

```python
def render_chat_interface():
    """Render main chat interface."""

    st.title("🎯 Viraltracker Agent")
    st.caption("AI-powered viral content analysis assistant")

    # ... (existing error handling) ...

    # NEW: Add file uploader for ad creation
    uploaded_file = st.file_uploader(
        "📎 Upload Reference Ad (Optional - for ad creation)",
        type=['png', 'jpg', 'jpeg', 'webp'],
        help="Upload a reference ad image to generate similar Facebook ads",
        key="reference_ad_uploader"
    )

    # Store uploaded file in session state
    if uploaded_file is not None:
        import base64
        file_bytes = uploaded_file.read()
        file_base64 = base64.b64encode(file_bytes).decode('utf-8')

        st.session_state.reference_ad_base64 = file_base64
        st.session_state.reference_ad_filename = uploaded_file.name

        # Show preview
        st.image(file_bytes, caption=f"Reference Ad: {uploaded_file.name}", width=200)
        st.success(f"✅ Reference ad uploaded: {uploaded_file.name}")

    # ... (rest of existing code) ...
```

**B. Pass File to Agent** (in chat input handler, around line 560)

```python
# Get agent response with streaming
with st.chat_message('assistant'):
    message_placeholder = st.empty()
    full_response = ""

    try:
        # Build context from recent results
        context = build_conversation_context()

        # Check if reference ad is uploaded (for ad creation)
        if 'reference_ad_base64' in st.session_state:
            # Add reference ad context to prompt
            ad_context = f"""

**Reference Ad Uploaded**: {st.session_state.reference_ad_filename}
[Base64 image data available in session state]

If the user wants to create ads, use this reference image.
"""
            full_prompt = f"{context}{ad_context}## Current Query:\n{prompt}"
        else:
            full_prompt = f"{context}## Current Query:\n{prompt}"

        # Get agent response
        with st.spinner("Agent is thinking..."):
            result = asyncio.run(agent.run(full_prompt, deps=st.session_state.deps))
            full_response = result.output

        # ... (rest of existing code) ...
```

---

### 3. Implement Rich Result Display for Generated Ads

#### File: `viraltracker/ui/app.py`

**Goal**: Display generated ads as image cards with status badges.

**A. Add to Imports** (top of file)

```python
from viraltracker.services.models import (
    OutlierResult,
    HookAnalysisResult,
    TweetExportResult,
    AdCreationResult  # NEW
)
```

**B. Create AdCreationResult Model** (if not exists)

File: `viraltracker/services/models.py`

```python
class AdCreationResult(BaseModel):
    """Result from ad creation workflow."""
    ad_run_id: str
    product: Dict[str, Any]
    reference_ad_path: str
    generated_ads: List[Dict[str, Any]]
    approved_count: int
    rejected_count: int
    flagged_count: int
    summary: str
    created_at: str

    def to_markdown(self) -> str:
        """Format as markdown for display."""
        md = f"# Ad Creation Results\n\n"
        md += f"**Product**: {self.product.get('name', 'Unknown')}\n"
        md += f"**Run ID**: `{self.ad_run_id}`\n\n"
        md += f"## Summary\n"
        md += f"- ✅ Approved: {self.approved_count}\n"
        md += f"- ❌ Rejected: {self.rejected_count}\n"
        md += f"- ⚠️ Flagged: {self.flagged_count}\n\n"

        for i, ad in enumerate(self.generated_ads, 1):
            status_emoji = {
                'approved': '✅',
                'rejected': '❌',
                'flagged': '⚠️'
            }.get(ad['final_status'], '❓')

            md += f"### {status_emoji} Variation {i} - {ad['final_status'].upper()}\n"
            md += f"**Hook**: {ad['prompt']['hook']['adapted_text']}\n"
            md += f"**Storage**: `{ad['storage_path']}`\n"
            md += f"**Claude Review**: {ad['claude_review']['status']}\n"
            md += f"**Gemini Review**: {ad['gemini_review']['status']}\n\n"

        return md
```

**C. Add Rich Display Function** (around line 194)

```python
def render_ad_creation_results(result: AdCreationResult, message_index: int):
    """
    Render ad creation results as rich image cards.

    Args:
        result: AdCreationResult with generated ads
        message_index: Index for unique keys
    """
    st.subheader(f"🎨 Generated Ads for {result.product.get('name')}")

    # Summary metrics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Ads", len(result.generated_ads))
    with col2:
        st.metric("✅ Approved", result.approved_count)
    with col3:
        st.metric("❌ Rejected", result.rejected_count)
    with col4:
        st.metric("⚠️ Flagged", result.flagged_count)

    st.divider()

    # Display each ad as a card
    for i, ad in enumerate(result.generated_ads):
        status_emoji = {
            'approved': '✅',
            'rejected': '❌',
            'flagged': '⚠️'
        }.get(ad['final_status'], '❓')

        with st.expander(f"{status_emoji} Variation {ad['prompt_index']} - {ad['final_status'].upper()}", expanded=(ad['final_status'] == 'approved')):
            # Two columns: image and details
            img_col, details_col = st.columns([1, 1])

            with img_col:
                # Download and display image
                try:
                    image_url = f"supabase-storage-url/{ad['storage_path']}"  # TODO: Get actual URL
                    st.image(image_url, caption=f"Variation {ad['prompt_index']}", use_column_width=True)
                except Exception as e:
                    st.error(f"Failed to load image: {str(e)}")
                    st.code(ad['storage_path'])

            with details_col:
                st.markdown(f"**Hook**: {ad['prompt']['hook']['adapted_text']}")
                st.markdown(f"**Category**: {ad['prompt']['hook']['category']}")

                # Review scores
                st.markdown("**Reviews**:")
                claude_score = ad['claude_review']['overall_quality']
                gemini_score = ad['gemini_review']['overall_quality']

                st.progress(claude_score, text=f"Claude: {claude_score:.2f}")
                st.progress(gemini_score, text=f"Gemini: {gemini_score:.2f}")

                # Issues
                if ad['claude_review'].get('product_issues'):
                    st.warning(f"Claude Issues: {', '.join(ad['claude_review']['product_issues'])}")
                if ad['gemini_review'].get('product_issues'):
                    st.warning(f"Gemini Issues: {', '.join(ad['gemini_review']['product_issues'])}")

                # Download button for approved ads
                if ad['final_status'] == 'approved':
                    st.download_button(
                        label="⬇️ Download Ad",
                        data="TODO: image bytes",  # TODO: Get actual image data
                        file_name=f"ad_variation_{ad['prompt_index']}.png",
                        mime="image/png",
                        key=f"download_ad_{message_index}_{i}"
                    )
```

**D. Update Result Extraction** (in render_chat_interface, around line 590)

```python
# Extract structured results from tool returns
if hasattr(result, 'all_messages'):
    for msg in result.all_messages():
        if hasattr(msg, 'parts'):
            for part in msg.parts:
                if part.__class__.__name__ == 'ToolReturnPart' and hasattr(part, 'content'):
                    # Check for multiple result types
                    if isinstance(part.content, (OutlierResult, HookAnalysisResult, TweetExportResult)):
                        structured_result = part.content
                        break
                    elif isinstance(part.content, AdCreationResult):  # NEW
                        structured_result = part.content
                        break
        if structured_result:
            break

# Store and display if we found a structured result
if structured_result:
    st.session_state.structured_results[message_idx] = structured_result
    st.divider()

    # Display based on type
    if isinstance(structured_result, AdCreationResult):
        render_ad_creation_results(structured_result, message_idx)
    else:
        render_download_buttons(structured_result, message_idx)
```

---

## Testing Plan

### End-to-End Natural Language Workflow

**Goal**: User says "Create 5 ads for Wonder Paws Collagen 3x" with uploaded image → Gets 5 generated ads

**Test Steps**:
1. Start Streamlit: `streamlit run viraltracker/ui/app.py --server.port=8501`
2. Upload reference ad image (PNG/JPG)
3. Enter query: "Create 5 ads for Wonder Paws Collagen 3x using this reference image"
4. Verify orchestrator:
   - Calls `resolve_product_name` with "Wonder Paws Collagen 3x"
   - Gets product_id from database
   - Routes to ad creation agent with product_id + reference_ad_base64
5. Verify ad creation agent:
   - Executes complete workflow (14 tools)
   - Generates 5 variations
   - Dual AI review
   - Returns AdCreationResult
6. Verify UI display:
   - Shows summary metrics (approved/rejected/flagged counts)
   - Displays each ad as image card
   - Shows review scores
   - Provides download buttons for approved ads

---

## Known Issues / TODOs

1. ⚠️ **Orchestrator routing logic incomplete** - Need to add routing tool and update system prompt
2. ⚠️ **Product name resolver not implemented** - Required for natural language
3. ⚠️ **File upload not added to Streamlit** - Chat is text-only currently
4. ⚠️ **Rich ad display not implemented** - Need image cards with status badges
5. ⚠️ **Image download from Supabase** - Need to fetch public URLs for display
6. ⚠️ **AdCreationResult model** - May need to add to services/models.py
7. ⚠️ **Error handling** - Need graceful handling of missing products, upload errors

---

## File Modification Summary

### Modified (Uncommitted):
- `viraltracker/agent/agents/__init__.py` - Added ad_creation_agent export
- `viraltracker/agent/orchestrator.py` - Added ad_creation_agent import

### To Modify Next:
- `viraltracker/agent/orchestrator.py` - Add routing tool, system prompt update, product resolver
- `viraltracker/ui/app.py` - Add file upload, rich ad display
- `viraltracker/services/models.py` - Add AdCreationResult (if not exists)

---

## Quick Reference Commands

```bash
# Current branch
git branch
# Should show: * feature/ad-creation-api

# Commit current changes
git add viraltracker/agent/agents/__init__.py viraltracker/agent/orchestrator.py
git commit -m "feat(phase6): Begin Streamlit integration - export ad_creation_agent"

# Start Streamlit UI (for testing)
streamlit run viraltracker/ui/app.py --server.port=8501

# Start API server (if needed)
uvicorn viraltracker.api.app:app --reload --port 8000

# Run tests
pytest tests/test_ad_creation_integration.py -v

# View git status
git status
```

---

## Continuation Prompt

Use this prompt to continue Phase 6 in a new context window:

```
I'm continuing work on the Facebook Ad Creation Agent - Phase 6: Streamlit Chat Integration.

**Read the checkpoint file first**:
/Users/ryemckenzie/projects/viraltracker/CHECKPOINT_PHASE6_STREAMLIT.md

**Current Status**:
- Phases 1-5 are COMPLETE ✅
- Phase 6 is IN PROGRESS ⏳
- Foundational changes complete (ad_creation_agent exported and imported)
- Next: Complete orchestrator integration and Streamlit UI modifications

**Goal**:
Enable natural language ad creation in Streamlit:
"Create 5 ads for Wonder Paws Collagen 3x using this reference image [upload]"

**What to do next**:
1. Update orchestrator system prompt to include ad creation agent
2. Add route_to_ad_creation_agent routing tool
3. Add resolve_product_name tool for natural language product lookup
4. Add file upload capability to Streamlit chat interface
5. Implement rich result display for generated ads (image cards)
6. Test end-to-end natural language workflow

**Tech Stack**: Python 3.11+, Pydantic-AI, Streamlit, FastAPI, Supabase, Claude, Gemini

**Repository**: https://github.com/RyeMcKenzie81/ryan-viral-pattern-detector.git
**Branch**: feature/ad-creation-api
**Working Directory**: /Users/ryemckenzie/projects/viraltracker

Let me know when you're ready to continue implementing Phase 6!
```

---

**Last Updated**: 2025-11-25
**Context Used at Checkpoint**: ~50%
**Next Phase**: Complete Phase 6 orchestrator integration and Streamlit UI
**Status**: Ready to continue in new context window ✅
