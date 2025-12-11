# Checkpoint 001: Pre-Implementation

**Date**: 2025-12-10
**Context**: Ready to start MVP 1 implementation
**Branch**: `feature/trash-panda-content-pipeline`
**Working Directory**: `/Users/ryemckenzie/projects/viraltracker/viraltracker-planning`

---

## What's Been Done

### 1. Planning Documents Created
- `PLAN.md` - Complete 29-step workflow with database schema, services, implementation phases
- `WORKFLOW_VISUALIZATION.md` - Detailed step-by-step UI mockups for all 29 steps

### 2. Key Decisions Made

**Architecture:**
- Use **pydantic-graph** for workflow orchestration (existing pattern in codebase)
- Follow existing pattern in `viraltracker-planning/viraltracker/pipelines/`
- State stored in JSONB in `content_projects.workflow_data`
- Modular file structure (not giant singletons)

**File Structure:**
```
viraltracker/services/content_pipeline/
├── __init__.py
├── orchestrator.py          # Graph definition (~100 lines)
├── state.py                 # ContentPipelineState model
├── nodes/
│   ├── topic_discovery.py
│   ├── topic_evaluation.py
│   └── ...
└── services/
    ├── topic_service.py     # Business logic
    ├── script_service.py
    └── ...
```

**Models & AI:**
- ChatGPT 5.1 (extended thinking) for topic discovery
- Claude Opus 4.5 for scripts, SEO, comic audio
- Gemini 3 Pro Image Preview for images/comics
- Gemini for evaluations

**Workflow (29 steps):**
- Steps 1-6: Shared (Topic Discovery → Script Approval)
- Steps 7-15: Video Path (ELS → Audio → Assets → SEO/Thumbnails → Editor Handoff)
- Steps 16-29: Comic Path (Condense → Image → Audio → Video → SEO/Thumbnails)

**Human Checkpoints (9 total):**
1. Topic Selection (Step 3) - Quick Approve if score > 90
2. Script Approval (Step 6) - Quick Approve if 100% checklist
3. Audio Production (Step 8)
4. Asset Review (Step 12)
5. Metadata Selection (Step 14) - Quick Approve if rank 1 > 90
6. Comic Script Approval (Step 18) - Quick Approve if all > 85
7. Comic Image Review (Step 21) - Quick Approve if eval > 90%
8. Comic Video (Step 25)
9. Comic Thumbnail Selection (Step 29)

**Knowledge Base Collections:**
1. `trash-panda-bible` - Bible + 6 YouTube docs (~3,530 lines total)
2. `comic-production` - 20 specialized comic docs

**Database Tables (9 new):**
1. content_projects
2. topic_suggestions
3. script_versions
4. els_versions
5. comic_versions
6. comic_assets
7. project_asset_requirements
8. character_voices
9. project_metadata

**Services (8 new):**
1. TopicDiscoveryService
2. ScriptGenerationService
3. ComicService
4. SEOMetadataService
5. ThumbnailService
6. AssetManagementService
7. EditorHandoffService
8. ContentPipelineService (orchestrator)

### 3. User Preferences Confirmed
- MVP approach: Build each piece testable, then wire together
- Checkpoints every 40K tokens
- Test and QA as we go
- Cleanup files as we go
- Efficient patterns, avoid giant files
- Ask questions instead of assuming
- Make services reusable
- JSON prompts for image generation
- Derral Eves docs: Use RAG with tagged chunks (~3,530 lines = too big to inject)
- Thumbnail sizes: 16:9 (1280x720) and 9:16 (720x1280)

---

## Next Steps (MVP 1: Topic Discovery)

### To Do:
1. **Create database migration** for content pipeline tables
2. **Create state model** (`ContentPipelineState` dataclass)
3. **Create TopicDiscoveryService** (business logic)
4. **Create TopicDiscoveryNode** (thin wrapper)
5. **Create Streamlit UI page** for testing
6. **Test and QA**

### Files to Create:
```
migrations/2025-12-10_content_pipeline_tables.sql
viraltracker/services/content_pipeline/__init__.py
viraltracker/services/content_pipeline/state.py
viraltracker/services/content_pipeline/services/topic_service.py
viraltracker/services/content_pipeline/nodes/topic_discovery.py
viraltracker/ui/pages/22_📝_Content_Pipeline.py
```

### User Needs to Provide (for MVP 1):
- Trash Panda Bible (Google Doc export)
- Confirmation to proceed in viraltracker-planning worktree

---

## Reference: Existing Pydantic-Graph Pattern

From `viraltracker-planning/viraltracker/pipelines/brand_onboarding.py`:

```python
from pydantic_graph import BaseNode, End, Graph, GraphRunContext

@dataclass
class MyNode(BaseNode[MyState]):
    async def run(
        self,
        ctx: GraphRunContext[MyState, AgentDependencies]
    ) -> "NextNode":
        # Access services via ctx.deps
        result = await ctx.deps.my_service.do_something()
        # Update state
        ctx.state.some_field = result
        # Return next node
        return NextNode()

# Build graph
my_graph = Graph(nodes=(Node1, Node2, ...), name="my_pipeline")
```

---

## Commands to Resume

```bash
# Switch to worktree
cd /Users/ryemckenzie/projects/viraltracker/viraltracker-planning

# Check branch
git branch  # Should show: feature/trash-panda-content-pipeline

# Read plan
cat docs/plans/trash-panda-content-pipeline/PLAN.md
```

---

**Status**: Ready to implement MVP 1
