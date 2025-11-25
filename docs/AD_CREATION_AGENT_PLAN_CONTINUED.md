# Facebook Ad Creation Agent - Implementation Details (Part 2)

**This is a continuation of AD_CREATION_AGENT_PLAN.md**

---

## Service Layer

### Complete AdCreationService Implementation

**File**: `viraltracker/services/ad_creation_service.py`

```python
"""
AdCreationService - Handles Facebook ad creation workflows.

Manages:
- Product and hook data retrieval from Supabase
- Supabase Storage operations (upload/download images)
- Database CRUD for ad runs and generated ads
- Image format conversions (base64 ↔ bytes)
"""

import logging
import base64
import json
from typing import Optional, List, Dict, Any
from uuid import UUID
from datetime import datetime

from supabase import Client
from ..core.config import Config
from .models import (
    Product, Hook, AdBriefTemplate, AdAnalysis, SelectedHook,
    NanoBananaPrompt, GeneratedAd, ReviewResult, GeneratedAdWithReviews,
    AdCreationResult
)

logger = logging.getLogger(__name__)


class AdCreationService:
    """Service for Facebook ad creation operations"""

    def __init__(self):
        """Initialize with Supabase client"""
        self.supabase: Client = Config.get_supabase_client()
        logger.info("AdCreationService initialized")

    # ============================================
    # PRODUCT & HOOK RETRIEVAL
    # ============================================

    async def get_product(self, product_id: UUID) -> Product:
        """
        Fetch product by ID with all metadata.

        Args:
            product_id: UUID of product

        Returns:
            Product model with all fields

        Raises:
            ValueError: If product not found
        """
        result = self.supabase.table("products").select("*").eq("id", str(product_id)).execute()

        if not result.data:
            raise ValueError(f"Product not found: {product_id}")

        return Product(**result.data[0])

    async def get_hooks(
        self,
        product_id: UUID,
        limit: int = 50,
        active_only: bool = True
    ) -> List[Hook]:
        """
        Fetch hooks for a product.

        Args:
            product_id: UUID of product
            limit: Maximum hooks to return
            active_only: Only return active hooks

        Returns:
            List of Hook models, sorted by impact_score DESC
        """
        query = self.supabase.table("hooks").select("*").eq("product_id", str(product_id))

        if active_only:
            query = query.eq("active", True)

        query = query.order("impact_score", desc=True).limit(limit)
        result = query.execute()

        return [Hook(**row) for row in result.data]

    async def get_ad_brief_template(
        self,
        brand_id: Optional[UUID] = None
    ) -> AdBriefTemplate:
        """
        Fetch ad brief template for brand (or global).

        Args:
            brand_id: UUID of brand (None = global)

        Returns:
            AdBriefTemplate model

        Raises:
            ValueError: If no template found
        """
        # Try brand-specific first
        if brand_id:
            result = self.supabase.table("ad_brief_templates")\
                .select("*")\
                .eq("brand_id", str(brand_id))\
                .eq("active", True)\
                .execute()

            if result.data:
                return AdBriefTemplate(**result.data[0])

        # Fall back to global
        result = self.supabase.table("ad_brief_templates")\
            .select("*")\
            .is_("brand_id", "null")\
            .eq("active", True)\
            .execute()

        if not result.data:
            raise ValueError("No ad brief template found")

        return AdBriefTemplate(**result.data[0])

    # ============================================
    # SUPABASE STORAGE OPERATIONS
    # ============================================

    async def upload_reference_ad(
        self,
        ad_run_id: UUID,
        image_data: bytes,
        filename: str = "reference.png"
    ) -> str:
        """
        Upload reference ad image to Supabase Storage.

        Args:
            ad_run_id: UUID of ad run
            image_data: Binary image data
            filename: Filename (default: reference.png)

        Returns:
            Storage path: "reference-ads/{ad_run_id}_{filename}"
        """
        storage_path = f"{ad_run_id}_{filename}"

        self.supabase.storage.from_("reference-ads").upload(
            storage_path,
            image_data,
            {"content-type": "image/png"}
        )

        logger.info(f"Uploaded reference ad: {storage_path}")
        return f"reference-ads/{storage_path}"

    async def upload_generated_ad(
        self,
        ad_run_id: UUID,
        prompt_index: int,
        image_base64: str
    ) -> str:
        """
        Upload generated ad image to Supabase Storage.

        Args:
            ad_run_id: UUID of ad run
            prompt_index: Index (1-5)
            image_base64: Base64-encoded image

        Returns:
            Storage path: "generated-ads/{ad_run_id}/{prompt_index}.png"
        """
        image_data = base64.b64decode(image_base64)
        storage_path = f"{ad_run_id}/{prompt_index}.png"

        self.supabase.storage.from_("generated-ads").upload(
            storage_path,
            image_data,
            {"content-type": "image/png"}
        )

        logger.info(f"Uploaded generated ad: {storage_path}")
        return f"generated-ads/{storage_path}"

    async def download_image(self, storage_path: str) -> bytes:
        """
        Download image from Supabase Storage.

        Args:
            storage_path: Full storage path (e.g., "products/{id}/main.png")

        Returns:
            Binary image data
        """
        # Parse bucket and path
        parts = storage_path.split("/", 1)
        bucket = parts[0]
        path = parts[1] if len(parts) > 1 else storage_path

        data = self.supabase.storage.from_(bucket).download(path)
        return data

    async def get_image_as_base64(self, storage_path: str) -> str:
        """
        Download image and convert to base64 string.

        Args:
            storage_path: Full storage path

        Returns:
            Base64-encoded image string
        """
        image_data = await self.download_image(storage_path)
        return base64.b64encode(image_data).decode('utf-8')

    # ============================================
    # AD RUN CRUD
    # ============================================

    async def create_ad_run(
        self,
        product_id: UUID,
        reference_ad_storage_path: str,
        project_id: Optional[UUID] = None
    ) -> UUID:
        """
        Create new ad run record.

        Args:
            product_id: UUID of product
            reference_ad_storage_path: Storage path to reference ad
            project_id: Optional project UUID

        Returns:
            UUID of created ad run
        """
        data = {
            "product_id": str(product_id),
            "reference_ad_storage_path": reference_ad_storage_path,
            "status": "pending"
        }

        if project_id:
            data["project_id"] = str(project_id)

        result = self.supabase.table("ad_runs").insert(data).execute()
        ad_run_id = UUID(result.data[0]["id"])

        logger.info(f"Created ad run: {ad_run_id}")
        return ad_run_id

    async def update_ad_run(
        self,
        ad_run_id: UUID,
        status: Optional[str] = None,
        ad_analysis: Optional[Dict] = None,
        selected_hooks: Optional[List[Dict]] = None,
        selected_product_images: Optional[List[str]] = None,
        error_message: Optional[str] = None
    ) -> None:
        """
        Update ad run with stage outputs.

        Args:
            ad_run_id: UUID of ad run
            status: New status
            ad_analysis: Ad analysis JSON
            selected_hooks: Selected hooks JSON array
            selected_product_images: Storage paths to product images
            error_message: Error message if failed
        """
        updates = {}

        if status:
            updates["status"] = status
        if ad_analysis:
            updates["ad_analysis"] = ad_analysis
        if selected_hooks:
            updates["selected_hooks"] = selected_hooks
        if selected_product_images:
            updates["selected_product_images"] = selected_product_images
        if error_message:
            updates["error_message"] = error_message

        if status == "complete":
            updates["completed_at"] = datetime.now().isoformat()

        self.supabase.table("ad_runs").update(updates).eq("id", str(ad_run_id)).execute()
        logger.info(f"Updated ad run {ad_run_id}: {list(updates.keys())}")

    # ============================================
    # GENERATED AD CRUD
    # ============================================

    async def save_generated_ad(
        self,
        ad_run_id: UUID,
        prompt_index: int,
        prompt_text: str,
        prompt_spec: Dict,
        hook_id: UUID,
        hook_text: str,
        storage_path: str,
        claude_review: Optional[Dict] = None,
        gemini_review: Optional[Dict] = None,
        final_status: str = "pending"
    ) -> UUID:
        """
        Save generated ad metadata to database.

        Args:
            ad_run_id: UUID of ad run
            prompt_index: Index (1-5)
            prompt_text: Full prompt sent to Nano Banana
            prompt_spec: JSON spec for image
            hook_id: UUID of hook used
            hook_text: Adapted hook text
            storage_path: Storage path to generated image
            claude_review: Claude review JSON (optional)
            gemini_review: Gemini review JSON (optional)
            final_status: Status (pending/approved/rejected/flagged)

        Returns:
            UUID of generated ad record
        """
        # Determine if reviewers agree
        reviewers_agree = None
        if claude_review and gemini_review:
            claude_approved = claude_review.get("status") == "approved"
            gemini_approved = gemini_review.get("status") == "approved"
            reviewers_agree = (claude_approved == gemini_approved)

        data = {
            "ad_run_id": str(ad_run_id),
            "prompt_index": prompt_index,
            "prompt_text": prompt_text,
            "prompt_spec": prompt_spec,
            "hook_id": str(hook_id),
            "hook_text": hook_text,
            "storage_path": storage_path,
            "claude_review": claude_review,
            "gemini_review": gemini_review,
            "reviewers_agree": reviewers_agree,
            "final_status": final_status
        }

        result = self.supabase.table("generated_ads").insert(data).execute()
        generated_ad_id = UUID(result.data[0]["id"])

        logger.info(f"Saved generated ad: {generated_ad_id} (status: {final_status})")
        return generated_ad_id
```

---

## Agent & Tools

### Agent Definition

**File**: `viraltracker/agent/agents/ad_creation_agent.py`

```python
"""
Ad Creation Agent - Specialized agent for Facebook ad creative generation.

This agent orchestrates the complete workflow:
1. Analyze reference ad (vision AI)
2. Select diverse hooks from database
3. Generate 5 ad variations using Gemini Nano Banana
4. Dual AI review (Claude + Gemini)
5. Return results with approval status
"""

import logging
from pydantic_ai import Agent, RunContext
from ..dependencies import AgentDependencies
from ..tool_metadata import ToolMetadata

logger = logging.getLogger(__name__)

# Create Ad Creation Agent
ad_creation_agent = Agent(
    model="claude-sonnet-4-5-20250929",
    deps_type=AgentDependencies,
    system_prompt="""You are the Ad Creation specialist agent.

Your ONLY responsibility is generating Facebook ad creative:
- Analyzing reference ads to understand format and style
- Selecting diverse persuasive hooks from database
- Generating image prompts for Nano Banana Pro 3
- Executing sequential image generation
- Coordinating dual AI review (Claude + Gemini)
- Compiling results with approval status

CRITICAL RULES:
1. Product images must be reproduced EXACTLY (no hallucination)
2. Execute generation ONE AT A TIME (not batched) - resilience
3. Save each image IMMEDIATELY after generation
4. Either reviewer approving = approved (OR logic)
5. Flag disagreements for human review
6. Minimum quality threshold: 0.8 for product/text accuracy

You have access to 14 specialized tools for this workflow.
Use them sequentially, validating output at each step."""
)

# ============================================
# TOOL 1: GET PRODUCT WITH IMAGES
# ============================================

@ad_creation_agent.tool(
    metadata=ToolMetadata(
        category='Ingestion',
        platform='Facebook',
        rate_limit='30/minute',
        use_cases=[
            'Retrieve product data with images for ad creation',
            'Load product benefits and target audience',
            'Access product image storage paths'
        ],
        examples=[
            'Get product details for Wonder Paws',
            'Load product images for ad generation'
        ]
    )
)
async def get_product_with_images(
    ctx: RunContext[AgentDependencies],
    product_id: str
) -> dict:
    """
    Fetch product from database with all associated images.

    This tool retrieves complete product information including benefits,
    target audience, and storage paths to all product images needed for
    ad generation.

    Args:
        ctx: Run context with AgentDependencies
        product_id: UUID of product as string

    Returns:
        Dictionary with product data including image storage paths

    Raises:
        ValueError: If product not found
    """
    from uuid import UUID

    product = await ctx.deps.ad_creation.get_product(UUID(product_id))
    return product.dict()


# Continue with remaining 13 tools...
# (Tool implementations follow the same pattern)

logger.info("Ad Creation Agent initialized with 14 tools")
```

---

## Implementation Phases

### Phase-by-Phase Build Order

The implementation is divided into 5 phases, with each phase building on the previous. **Test each phase completely** before moving to the next.

### Phase 1: Foundation (Database + Models)

**Goal**: Set up database schema and Pydantic models

**Tasks**:
1. Run SQL migration (`sql/migration_ad_creation.sql`)
2. Create Supabase Storage buckets
3. Add Pydantic models to `viraltracker/services/models.py`
4. Update `viraltracker/agent/dependencies.py` to include AdCreationService

**Validation**:
```bash
# Test database schema
psql $DATABASE_URL -c "\d hooks"
psql $DATABASE_URL -c "\d ad_runs"
psql $DATABASE_URL -c "\d generated_ads"

# Test Supabase buckets
# Check in Supabase Dashboard → Storage
```

**Success Criteria**:
- All tables created successfully
- Storage buckets exist with correct policies
- Pydantic models import without errors

---

### Phase 2: Service Layer

**Goal**: Build AdCreationService with complete CRUD operations

**Tasks**:
1. Create `viraltracker/services/ad_creation_service.py`
2. Implement all service methods (product retrieval, storage ops, CRUD)
3. Add AdCreationService to AgentDependencies.create()

**Validation**:
```python
# Test service methods individually
from viraltracker.services.ad_creation_service import AdCreationService
from uuid import UUID

service = AdCreationService()

# Test get_product
product = await service.get_product(UUID("your-product-id"))
print(product)

# Test get_hooks
hooks = await service.get_hooks(UUID("your-product-id"), limit=10)
print(f"Found {len(hooks)} hooks")

# Test storage operations
test_data = b"fake image data"
path = await service.upload_reference_ad(UUID("test-run-id"), test_data)
print(f"Uploaded to: {path}")
```

**Success Criteria**:
- All service methods work independently
- Storage upload/download working
- Database queries returning correct data

---

### Phase 3: Core Tools (Data Retrieval)

**Goal**: Build first 4 tools for data fetching

**Tools to Build**:
1. `get_product_with_images` - Fetch product data
2. `get_hooks_for_product` - Fetch hooks from database
3. `get_ad_brief_template` - Fetch instructions template
4. `upload_reference_ad` - Upload reference ad to storage

**Validation**:
```python
# Test tools via agent
from viraltracker.agent.agents.ad_creation_agent import ad_creation_agent
from viraltracker.agent.dependencies import AgentDependencies

deps = AgentDependencies.create(project_name="test")

# Test get_product_with_images
result = await ad_creation_agent.run(
    "Get product details for product ID abc123",
    deps=deps
)
print(result.output)
```

**Success Criteria**:
- All 4 tools registered with agent
- Tools execute without errors
- Correct data returned from database

---

### Phase 4: Analysis & Generation Tools

**Goal**: Build vision analysis and image generation tools

**Tools to Build**:
5. `analyze_reference_ad` - Vision AI analysis
6. `select_hooks` - AI-powered hook selection
7. `select_product_images` - Image ranking
8. `generate_nano_banana_prompt` - Prompt construction
9. `execute_nano_banana` - Image generation via Gemini
10. `save_generated_ad` - Save to storage + DB

**Validation**:
```python
# Test analyze_reference_ad
result = await ad_creation_agent.run(
    "Analyze the reference ad at path reference-ads/test.png",
    deps=deps
)

# Test nano banana generation (ONE test image)
result = await ad_creation_agent.run(
    "Generate a single test ad using hook ID xyz789",
    deps=deps
)
```

**Success Criteria**:
- Vision analysis returns structured JSON
- Hook selection shows diversity reasoning
- Nano Banana generates valid images
- Images save to correct storage paths

---

### Phase 5: Review & Orchestration

**Goal**: Build dual review system and complete workflow

**Tools to Build**:
11. `review_ad_claude` - Claude vision review
12. `review_ad_gemini` - Gemini vision review
13. `create_ad_run` - Initialize workflow
14. `complete_ad_workflow` - Full end-to-end orchestration

**Validation**:
```bash
# Test complete workflow
python -m viraltracker.cli.main ad-creation create \
  --product-id "abc123" \
  --reference-ad "./test_ad.png"
```

**Success Criteria**:
- Dual review working with OR logic
- Complete workflow executes end-to-end
- Results saved to database
- AdCreationResult returned with all data

---

## Testing Strategy

### Tool-by-Tool Testing

**Critical**: Test each tool individually before combining them.

**Testing Template** (for each tool):

```python
# File: tests/test_ad_creation_tools.py

import pytest
from uuid import UUID
from viraltracker.agent.agents.ad_creation_agent import ad_creation_agent
from viraltracker.agent.dependencies import AgentDependencies

@pytest.fixture
def deps():
    return AgentDependencies.create(project_name="test-ad-creation")

@pytest.mark.asyncio
async def test_get_product_with_images(deps):
    """Test product retrieval tool"""
    # Setup
    product_id = "your-test-product-id"

    # Execute
    result = await ad_creation_agent.run(
        f"Get product details for product ID {product_id}",
        deps=deps
    )

    # Assert
    assert "id" in result.output
    assert "name" in result.output
    assert "benefits" in result.output

@pytest.mark.asyncio
async def test_analyze_reference_ad(deps):
    """Test vision analysis tool"""
    # Setup: Upload test reference ad first
    test_image_path = "tests/fixtures/test_ad.png"

    # Execute
    result = await ad_creation_agent.run(
        f"Analyze the ad at {test_image_path}",
        deps=deps
    )

    # Assert
    assert "format_type" in result.output
    assert "layout_structure" in result.output
    assert "color_palette" in result.output

# Repeat for all 14 tools...
```

### Integration Testing

**After all tools work individually**, test workflow combinations:

```python
@pytest.mark.asyncio
async def test_complete_ad_workflow(deps):
    """Test full end-to-end workflow"""
    result = await ad_creation_agent.run(
        "Create 5 Facebook ads for product abc123 using reference ad test.png",
        deps=deps
    )

    # Assert workflow completed
    assert result.output["approved_count"] >= 0
    assert result.output["rejected_count"] >= 0
    assert result.output["generated_ads"]
    assert len(result.output["generated_ads"]) == 5
```

### Manual Testing Checklist

Before production deployment:

- [ ] Upload real reference ad to storage
- [ ] Run complete workflow with real product
- [ ] Verify all 5 images generated
- [ ] Check dual review scores make sense
- [ ] Review approved ads manually
- [ ] Check flagged ads for reviewer disagreement
- [ ] Verify database records created correctly
- [ ] Test error handling (bad product ID, missing images, etc.)

---

## Hook Categories Reference

### Universal Persuasive Principles

These categories apply across all products, not just pet products. Each hook in the database should be tagged with one of these universal principles.

| Category | Principle | Description | Examples Across Verticals |
|----------|-----------|-------------|---------------------------|
| **skepticism_overcome** | Objection Reversal | Skeptic converts after proof | **Dog**: "I don't believe in miracle products. But my dog stopped scratching in 2 weeks."<br>**Health**: "Never trust supplements. But my energy doubled."<br>**Software**: "Thought it was a gimmick. Now I can't work without it." |
| **timeline** | Specific Proof | Week/day progression | **Dog**: "Week 1: Less shedding. Week 2: Softer coat."<br>**Fitness**: "Day 3: Less bloating. Week 2: Down 5 lbs."<br>**Business**: "Month 1: 10 leads. Month 2: 50 leads." |
| **authority_validation** | Expert Endorsement | Professional noticed | **Dog**: "My vet asked what I'm doing differently"<br>**Health**: "My doctor asked about my routine"<br>**Auto**: "The mechanic wanted to know my secret" |
| **value_contrast** | Price Anchoring | Saves vs. expensive alternative | **Dog**: "My vet wanted $150/month. Then I discovered this."<br>**Medical**: "Was about to spend $2000. This was $49."<br>**Fitness**: "Gym: $100/mo. This: $20." |
| **bonus_discovery** | Unexpected Value | Bought for X, got Y too | **Dog**: "Bought for joints. Now her coat shines."<br>**Health**: "Got it for focus. Lost 10 lbs too."<br>**Marketing**: "Bought for SEO. Tripled email list." |
| **specificity** | Personalization | Specific details create identification | **Dog**: "7-year-old Italian Greyhound. Zero shedding in 2 months."<br>**Fitness**: "35-year-old mom of 3. Down 2 dress sizes."<br>**SaaS**: "B2B founder. 5X'd MRR." |
| **transformation** | Dramatic Reversal | Old/bad → young/good | **Dog**: "She's 12 and runs like she's 5."<br>**Health**: "Felt 60, now feel 40"<br>**Business**: "Dead business, now thriving" |
| **failed_alternatives** | Last Resort | Everything else failed | **Dog**: "Oatmeal baths failed. This worked."<br>**Health**: "Tried 5 diets. Only this worked."<br>**Agency**: "3 agencies failed. These guys delivered." |

### Hook Scoring System

**Impact Score** (0-21 points):
- Specificity: +3 (concrete details, numbers)
- Timeline: +3 (specific timeframe mentioned)
- Authority: +3 (professional validation)
- Transformation: +3 (before/after implication)
- Skepticism overcome: +3 (objection → conversion)
- Value contrast: +3 (price comparison)
- Unexpected benefit: +3 (bonus discovery)

**Emotional Score** (qualitative):
- **Very High**: Multiple high-impact elements + strong emotional trigger
- **High**: 2-3 high-impact elements
- **Medium**: 1-2 impact elements
- **Low**: Generic or minimal emotional resonance

**Example Scoring**:
```
Hook: "I don't believe in miracle products. But my dog stopped scratching in 2 weeks."

Points:
- Skepticism overcome: +3
- Timeline: +3 (2 weeks)
- Specificity: +3 (scratching → stopped)
Total: 9 points
Emotional Score: High
Category: skepticism_overcome
```

---

## Sample Hooks Data (Wonder Paws Example)

Insert these into your `hooks` table for testing:

```sql
INSERT INTO hooks (product_id, text, category, framework, impact_score, emotional_score, active)
VALUES
  ('your-product-id', 'I don''t believe in miracle products. But my dog stopped scratching in 2 weeks.', 'skepticism_overcome', 'Skepticism Overcome', 21, 'Very High', true),
  ('your-product-id', 'Week 1: Less shedding. Week 2: Softer coat. Week 3: My groomer was shocked.', 'timeline', 'Progressive Timeline', 19, 'Very High', true),
  ('your-product-id', 'My vet wanted $150/month for joint supplements. Then I discovered this liquid collagen.', 'value_contrast', 'Cost Comparison', 15, 'High', true),
  ('your-product-id', 'My dog scratched for 4 years straight. Day 10 on this: silence.', 'failed_alternatives', 'Chronic Problem Solved', 15, 'High', true),
  ('your-product-id', '7-year-old Italian Greyhound. Zero shedding in under 2 months.', 'specificity', 'Breed-Specific Results', 14, 'High', true),
  ('your-product-id', 'These drops saved my dog''s mobility. (She''s 12 and runs like she''s 5.)', 'transformation', 'Dramatic Save', 11, 'High', true),
  ('your-product-id', 'I bought this for my dog''s joints. Now her coat shines and nails are stronger.', 'bonus_discovery', 'Unexpected Benefits', 10, 'Medium', true),
  ('your-product-id', 'The vet asked what I''m doing differently', 'authority_validation', 'Direct Customer Quote', 7, 'Medium', true);
```

---

## Next Steps for Implementation

1. **Start with Phase 1** (Foundation)
   - Run SQL migration
   - Create storage buckets
   - Add Pydantic models

2. **Build AdCreationService** (Phase 2)
   - Test each method individually
   - Validate storage operations

3. **Implement Tools Incrementally** (Phases 3-5)
   - Build 4 tools at a time
   - Test each tool before moving on
   - Use pytest for automated testing

4. **Complete Workflow** (Phase 5)
   - Test end-to-end with real data
   - Validate dual review logic
   - Measure performance and costs

---

## Cost Estimates

**Gemini API Costs** (approximate):
- Vision Analysis: $0.00025/image
- Hook Selection (text): $0.00001/request
- Nano Banana Generation: $0.04/image
- Review (vision): $0.00025/image

**Per Workflow**:
- 1 reference ad analysis: $0.00025
- 5 image generations: $0.20
- 10 reviews (5 ads × 2 reviewers): $0.0025
- **Total per run**: ~$0.20

**Monthly** (100 runs): ~$20

---

## Appendix: Nano Banana Prompt Example

```
I am providing you with TWO reference images:
1. A template ad showing the layout structure
2. The EXACT product bottle image to use (amber liquid with BLACK dropper cap)

CRITICAL FOR THIS VERSION:
The Wonder Paws bottle has a BLACK cap with built-in dropper.
- The cap is BLACK (not green, not white - BLACK)
- It's a dropper-style cap (the kind you squeeze to draw liquid)
- Despite the veterinary theme, the cap stays BLACK
- Do NOT change the cap to green to match the vet theme
- The BLACK dropper cap is part of the product identity

Task: Create product advertisement using provided bottle image

Specifications:
{
  "canvas": "1080x1080px, background #F5F0E8",
  "bottle": "Use uploaded bottle EXACTLY - BLACK dropper cap, amber liquid",
  "text_elements": {
    "headline": "\"The vet asked what changed\"" (entire text in green #2A5434),
    "subheadline": "Professional results you can see" (gray #555555),
    "benefits": [
      "Top-left: Clinically proven",
      "Top-right: Types I, II & III collagen",
      "Bottom-left: No fillers or GMOs",
      "Bottom-right": "Trusted by vets"
    ],
    "offer_bar": "Green bar with white text: Up to 35% OFF + Free Shipping"
  },
  "CRITICAL": "The dropper cap is BLACK, not green. Veterinary theme is text-only."
}
```

---

**END OF PLAN**

**Status**: Ready for implementation
**Estimated Time**: 2-3 weeks (tool-by-tool approach)
**Next Action**: Run Phase 1 (Foundation) to set up database schema

---
