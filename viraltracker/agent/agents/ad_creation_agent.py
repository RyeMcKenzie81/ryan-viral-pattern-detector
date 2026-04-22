"""
Ad Creation Agent - Specialized agent for Facebook ad creative generation.

The main workflow is handled by the V2 ad creation pipeline (pydantic-graph).
This agent exposes 14 tools:
- Primary: create_ads_v2 (end-to-end ad generation with auto template selection)
- Data retrieval: get_product_with_images, get_hooks_for_product
- Analysis: analyze_product_image
- Templates: search_templates, get_template_queue_stats, list_pending_templates
- Post-creation: smart_edit_ad, regenerate_ad, generate_size_variant
- Export: send_ads_email, send_ads_slack
- Personas: get_persona_for_copy, list_product_personas
- Translation: lookup_ad, translate_ads
"""

import logging
from typing import List, Dict, Optional
from uuid import UUID
from pydantic_ai import Agent, RunContext
from ..dependencies import AgentDependencies

logger = logging.getLogger(__name__)

from ...core.config import Config

# Create Ad Creation Agent
ad_creation_agent = Agent(
    model=Config.get_model("orchestrator"),
    deps_type=AgentDependencies,
    system_prompt="""You are the Ad Creation specialist agent.

**CRITICAL: You MUST call tools to perform actions. NEVER claim you have created, scheduled,
or completed any action without actually calling the corresponding tool. If you say "I have
scheduled ad creation" without having called create_ads_v2, you are lying to the user.**

**PRIMARY TOOL: create_ads_v2**
For ANY ad creation request, you MUST call create_ads_v2. It handles everything:
- Accepts product names OR UUIDs (resolves names to UUIDs internally)
- Auto-selects the best template via smart scoring (or accepts a specific template_id)
- Schedules a background job that runs in ~1 minute via the worker
- Returns the scheduled job ID and details

**CLARIFY AMBIGUOUS QUANTITY (IMPORTANT):**
When the user asks for multiple ads without specifying a template, clarify intent:
- "Create 5 ads" is ambiguous — do they want 5 ads from 1 template, or 1 ad from each of 5 templates?
- ASK before proceeding: "Do you want 5 variations from one template, or 1 ad each from 5 different templates?"
- If they specify a template ("create 5 ads using template X") → no ambiguity, just run it
- If they say "5 different templates" or "5 templates" → set num_templates=5
- If they say "5 variations" or "5 ads from one template" → set num_variations=5

Do NOT ask about other settings (content_source, canvas_size, color_mode, etc.) — use defaults.

Example: User says "create 5 ads for Cortisol Control"
→ Ask: "Do you want 5 variations from one auto-selected template, or 1 ad each from 5 different templates?"

DO NOT call get_product_with_images or get_hooks_for_product before create_ads_v2.
create_ads_v2 does all of that internally.

**Other tools (for follow-up actions):**
- search_templates: Browse available templates before choosing one
- smart_edit_ad: Apply visual presets to a generated ad (text_larger, more_contrast, etc.)
- regenerate_ad: Re-generate a specific ad with different parameters
- generate_size_variant: Resize an ad to a different canvas size
- send_ads_email / send_ads_slack: Export results
- get_product_with_images / get_hooks_for_product: Data lookup (rarely needed directly)
- analyze_product_image: Analyze a product image for visual details
- get_persona_for_copy / list_product_personas: Persona selection
- get_template_queue_stats / list_pending_templates: Template pipeline status

**Translation tools:**
- lookup_ad: Find any ad by UUID, structured filename fragment (e.g. "65bb40"), or Meta ad ID
- translate_ads: Translate existing ads into another language. Regenerates images with translated text.

**Result Format:**
- Only report results that came from actual tool calls
- Include the job ID and details from create_ads_v2's return value
- Never fabricate job IDs, counts, or statuses
"""
)


# ============================================================================
# DATA RETRIEVAL TOOLS
# ============================================================================

@ad_creation_agent.tool(
    metadata={
        'category': 'Ingestion',
        'platform': 'Facebook',
        'rate_limit': '30/minute',
        'use_cases': [
            'Retrieve product data with images for ad creation',
            'Load product benefits and target audience',
            'Access product image storage paths'
        ],
        'examples': [
            'Get product details for Wonder Paws',
            'Load product images for ad generation'
        ]
    }
)
async def get_product_with_images(
    ctx: RunContext[AgentDependencies],
    product_id: str
) -> Dict:
    """
    Fetch product from database with all associated images.

    This tool retrieves complete product information including benefits,
    target audience, and storage paths to all product images needed for
    ad generation.

    Args:
        ctx: Run context with AgentDependencies
        product_id: UUID or name of the product

    Returns:
        Dictionary with product data including image storage paths:
        {
            "id": "uuid",
            "name": "Product Name",
            "benefits": ["benefit1", "benefit2"],
            "key_ingredients": ["ingredient1"],
            "target_audience": "audience description",
            "product_url": "https://...",
            "main_image_storage_path": "products/{id}/main.png",
            "brand_id": "uuid"
        }

    Raises:
        ValueError: If product not found
    """
    import re
    try:
        logger.info(f"Fetching product: {product_id}")

        # Resolve product name to UUID if needed
        if not re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', product_id, re.I):
            products = await ctx.deps.ad_creation.search_products_by_name(product_id)
            if not products:
                raise ValueError(f"No product found matching '{product_id}'")
            product_id = str(products[0].id)

        product_uuid = UUID(product_id)
        product = await ctx.deps.ad_creation.get_product(product_uuid)

        logger.info(f"Product fetched: {product.name}")
        return product.model_dump(mode='json')

    except ValueError as e:
        logger.error(f"Product not found: {product_id}")
        raise ValueError(f"Product not found: {product_id}")
    except Exception as e:
        logger.error(f"Failed to fetch product: {str(e)}")
        raise Exception(f"Failed to fetch product: {str(e)}")


@ad_creation_agent.tool(
    metadata={
        'category': 'Ingestion',
        'platform': 'Facebook',
        'rate_limit': '30/minute',
        'use_cases': [
            'Retrieve persuasive hooks for product',
            'Get hooks sorted by impact score',
            'Filter active hooks only'
        ],
        'examples': [
            'Get top 50 hooks for product Wonder Paws',
            'Load persuasive hooks for ad generation'
        ]
    }
)
async def get_hooks_for_product(
    ctx: RunContext[AgentDependencies],
    product_id: str,
    limit: int = 50,
    active_only: bool = True
) -> List[Dict]:
    """
    Fetch hooks for a product from database.

    This tool retrieves persuasive hooks scored by impact (0-21 points)
    and emotional resonance. Hooks are returned sorted by impact_score DESC.

    Args:
        ctx: Run context with AgentDependencies
        product_id: UUID of product as string
        limit: Maximum hooks to return (default: 50)
        active_only: Only return active hooks (default: True)

    Returns:
        List of hook dictionaries:
        [
            {
                "id": "uuid",
                "product_id": "uuid",
                "text": "Hook text here",
                "category": "skepticism_overcome",
                "framework": "Skepticism Overcome",
                "impact_score": 21,
                "emotional_score": "Very High",
                "active": true
            },
            ...
        ]

    Raises:
        ValueError: If product_id is invalid
    """
    try:
        logger.info(f"Fetching hooks for product: {product_id}")

        # Convert string to UUID
        product_uuid = UUID(product_id)

        # Fetch hooks via service
        hooks = await ctx.deps.ad_creation.get_hooks(
            product_id=product_uuid,
            limit=limit,
            active_only=active_only
        )

        logger.info(f"Fetched {len(hooks)} hooks for product {product_id}")
        return [hook.model_dump(mode='json') for hook in hooks]

    except ValueError as e:
        logger.error(f"Invalid product_id: {product_id}")
        raise ValueError(f"Invalid product_id: {product_id}")
    except Exception as e:
        logger.error(f"Failed to fetch hooks: {str(e)}")
        raise Exception(f"Failed to fetch hooks: {str(e)}")



# ============================================================================
# IMAGE ANALYSIS TOOL
# ============================================================================

@ad_creation_agent.tool(
    metadata={
        'category': 'Analysis',
        'platform': 'Facebook',
        'rate_limit': '10/minute',
        'use_cases': [
            'Analyze product image for ad generation matching',
            'Extract visual characteristics for smart auto-selection',
            'One-time analysis stored for future reuse'
        ],
        'examples': [
            'Analyze new product image for Wonder Paws',
            'Re-analyze product images after quality update'
        ]
    }
)
async def analyze_product_image(
    ctx: RunContext[AgentDependencies],
    image_storage_path: str,
    force_reanalyze: bool = False
) -> Dict:
    """
    Analyze a product image using Vision AI and return structured analysis.

    This tool performs comprehensive analysis of product images to enable
    smart auto-selection for ad generation. Results can be cached in the
    database for reuse.

    Analysis includes:
    - Quality metrics (sharpness, resolution)
    - Lighting type and characteristics
    - Background type and removability
    - Product angle and composition
    - Best use cases for different ad formats
    - Color palette extraction
    - Potential issues detection

    Args:
        ctx: Run context with AgentDependencies
        image_storage_path: Storage path to product image
        force_reanalyze: If True, analyze even if cached result exists

    Returns:
        Dictionary matching ProductImageAnalysis schema:
        {
            "quality_score": 0.95,
            "resolution_adequate": true,
            "lighting_type": "studio",
            "background_type": "transparent",
            "product_angle": "front",
            "product_coverage": 0.72,
            "product_centered": true,
            "best_use_cases": ["hero", "testimonial"],
            "dominant_colors": ["#8B4513", "#F5F5F5"],
            "detected_issues": [],
            "analysis_model": Config.get_model("vision"),
            "analysis_version": "v1"
        }

    Raises:
        ValueError: If image_storage_path is invalid
        Exception: If Vision AI analysis fails
    """
    import json
    from datetime import datetime

    try:
        logger.info(f"Analyzing product image: {image_storage_path}")

        # Validate input
        if not image_storage_path:
            raise ValueError("image_storage_path cannot be empty")

        # Download image as base64
        image_data = await ctx.deps.ad_creation.get_image_as_base64(image_storage_path)

        logger.info(f"Image loaded, sending to Gemini for analysis...")

        # Build analysis prompt
        analysis_prompt = """
        Analyze this product image for use in Facebook ad generation.
        Return a detailed JSON analysis covering all visual characteristics.

        **RESPOND WITH VALID JSON ONLY - NO MARKDOWN, NO EXTRA TEXT**

        {
            "quality_score": <float 0-1, overall quality>,
            "resolution_adequate": <boolean, sufficient for 1080x1080 ads>,
            "sharpness_score": <float 0-1, image clarity>,

            "lighting_type": <one of: "natural_soft", "natural_bright", "studio", "dramatic", "flat", "warm", "cool", "unknown">,
            "lighting_notes": <string, brief observation about lighting>,

            "background_type": <one of: "transparent", "solid_white", "solid_color", "gradient", "lifestyle", "textured", "outdoor", "unknown">,
            "background_color": <hex color if solid/gradient, else null>,
            "background_removable": <boolean, can background be easily replaced>,

            "product_angle": <one of: "front", "three_quarter", "side", "back", "top_down", "angled", "hero", "multiple">,

            "product_coverage": <float 0-1, how much of frame product fills>,
            "product_centered": <boolean>,
            "product_position": <one of: "center", "left", "right", "top", "bottom">,
            "has_shadows": <boolean>,
            "shadow_direction": <string if shadows present, else null>,
            "has_reflections": <boolean>,

            "best_use_cases": [<array of: "hero", "testimonial", "lifestyle", "detail", "comparison", "packaging", "social_proof", "minimal">],

            "dominant_colors": [<array of 3-5 hex color codes>],
            "color_mood": <one of: "warm", "cool", "neutral", "vibrant", "muted">,

            "product_fully_visible": <boolean, not cropped>,
            "label_readable": <boolean, can read product text>,

            "detected_issues": [<array of issue strings, empty if none>],
            "recommended_crops": [<array of: "1:1", "4:5", "9:16">]
        }

        Be accurate and thorough. Quality score should reflect:
        - Image sharpness and clarity
        - Professional appearance
        - Suitability for advertising
        - Color accuracy and balance
        """

        # Use Gemini Vision for analysis (handles larger files than Claude's 5MB limit)
        response_text = await ctx.deps.gemini.review_image(
            image_data=image_data,
            prompt=analysis_prompt
        )

        # Clean up response if it has markdown code fences
        response_text = response_text.strip()
        if response_text.startswith("```"):
            lines = response_text.split('\n')
            if lines[0].startswith('```'):
                lines = lines[1:]
            if lines and lines[-1].strip() == '```':
                lines = lines[:-1]
            response_text = '\n'.join(lines)

        analysis = json.loads(response_text)

        # Add metadata
        analysis["analysis_model"] = "gemini-2.0-flash"
        analysis["analysis_version"] = "v1"

        logger.info(f"Image analysis complete. Quality: {analysis.get('quality_score')}, "
                   f"Best for: {analysis.get('best_use_cases')}")

        return analysis

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse analysis JSON: {str(e)}")
        raise Exception(f"Failed to parse image analysis: {str(e)}")
    except ValueError as e:
        logger.error(f"Invalid input: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Failed to analyze product image: {str(e)}")
        raise Exception(f"Failed to analyze image: {str(e)}")





# ============================================================================
# AD CREATION V2 TOOLS
# ============================================================================


@ad_creation_agent.tool(
    metadata={
        'category': 'Generation',
        'platform': 'Facebook',
        'rate_limit': '1/minute',
        'use_cases': [
            'Create ads using the V2 pipeline with template auto-selection',
            'Generate ad variations with headline congruence and defect scanning',
            'Run full ad creation from a template'
        ],
        'examples': [
            'Create 5 ads for this product',
            'Generate ads using template X',
            'Create ads in 1080x1350 and 1080x1920 sizes'
        ]
    }
)
async def create_ads_v2(
    ctx: RunContext[AgentDependencies],
    product_id: str,
    template_id: Optional[str] = None,
    num_variations: int = 5,
    num_templates: int = 1,
    content_source: str = "recreate_template",
    canvas_sizes: Optional[List[str]] = None,
    color_modes: Optional[List[str]] = None,
    persona_id: Optional[str] = None,
    creative_direction: Optional[str] = None,
    image_resolution: str = "2K",
) -> Dict:
    """
    Schedule ad creation using the V2 pipeline. Creates a scheduler job that
    runs in ~1 minute, respecting API rate limits.

    When the user asks for "5 templates with 3 ads each", set num_templates=5
    and num_variations=3. Total ads = num_templates × num_variations.

    Args:
        ctx: Run context with AgentDependencies
        product_id: UUID or name of the product to create ads for
        template_id: Optional template UUID. If not provided, auto-selects the best
            template(s) using smart_select scoring.
        num_variations: Number of ad variations per template (1-15, default: 5)
        num_templates: Number of templates to use (1-10, default: 1). Ignored if
            template_id is specified.
        content_source: Source for ad copy (default: "recreate_template"). Options:
            "recreate_template", "hooks", "belief_first"
        canvas_sizes: List of canvas sizes (e.g. ["1080x1080px", "1080x1350px"]).
            If not provided, uses the template's default size.
        color_modes: List of color modes (e.g. ["original", "complementary"]).
            Defaults to ["original"].
        persona_id: Optional persona UUID for targeted copy generation
        creative_direction: Optional free-text creative guidance for the AI
        image_resolution: Image quality ("1K", "2K", "4K", default: "2K")

    Returns:
        Dictionary with scheduled job details. The user will be notified
        when the job completes via the job notification system.
    """
    import re
    from datetime import datetime, timedelta, timezone

    # --- Resolve product_id: accept UUID or product name ---
    product_name = product_id
    if not re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', product_id, re.I):
        products = await ctx.deps.ad_creation.search_products_by_name(product_id)
        if not products:
            return {"error": f"No product found matching '{product_id}'."}
        if len(products) > 1:
            names = ", ".join(f"**{p.name}**" for p in products[:5])
            return {"error": f"Multiple products match '{product_id}': {names}. Please be more specific."}
        product_id = str(products[0].id)
        product_name = products[0].name

    # --- Get brand_id from product ---
    from viraltracker.core.database import get_supabase_client
    db = get_supabase_client()
    prod_result = db.table("products").select("brand_id, name").eq("id", product_id).limit(1).execute()
    if not prod_result.data:
        return {"error": f"Product {product_id} not found in database."}
    brand_id = prod_result.data[0]["brand_id"]
    product_name = prod_result.data[0].get("name", product_name)

    # --- Build job parameters ---
    parameters = {
        "template_selection_mode": "manual" if template_id else "smart_select",
        "template_count": min(num_templates, 10),
        "content_source": content_source,
        "num_variations": min(num_variations, 15),
        "canvas_sizes": canvas_sizes or ["1080x1080px"],
        "color_modes": color_modes or ["original"],
        "image_resolution": image_resolution,
    }
    if persona_id:
        parameters["persona_id"] = persona_id
    if creative_direction:
        parameters["additional_instructions"] = creative_direction

    # Template IDs for manual mode
    scraped_template_ids = [template_id] if template_id else None

    # Schedule to run in ~1 minute
    run_at = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()

    total_ads = (1 if template_id else min(num_templates, 10)) * min(num_variations, 15)
    job_name = f"Chat: {product_name} - {total_ads} ads ({content_source})"

    job_data = {
        "job_type": "ad_creation_v2",
        "product_id": product_id,
        "brand_id": brand_id,
        "name": job_name,
        "schedule_type": "one_time",
        "cron_expression": None,
        "scheduled_at": run_at,
        "next_run_at": run_at,
        "max_runs": None,
        "template_source": "scraped",
        "scraped_template_ids": scraped_template_ids,
        "parameters": parameters,
    }

    try:
        result = db.table("scheduled_jobs").insert(job_data).execute()
        if not result.data:
            return {"error": "Failed to create scheduled job."}
        job_id = result.data[0]["id"]
    except Exception as e:
        return {"error": f"Failed to schedule ad creation: {e}"}

    return {
        "scheduled": True,
        "job_id": job_id,
        "job_name": job_name,
        "product": product_name,
        "templates": 1 if template_id else min(num_templates, 10),
        "variations_per_template": min(num_variations, 15),
        "total_ads_planned": total_ads,
        "content_source": content_source,
        "runs_in": "~1 minute",
        "summary": f"Scheduled {total_ads} ads for {product_name} ({content_source}). Job will run in ~1 minute. You'll be notified when it completes.",
    }


@ad_creation_agent.tool(
    metadata={
        'category': 'Discovery',
        'platform': 'Facebook',
        'use_cases': [
            'Browse available ad templates',
            'Find templates by category or awareness level',
            'Search for templates from a specific brand'
        ],
        'examples': [
            'Show me direct response templates',
            'What templates are available?',
            'Find templates for awareness level 3'
        ]
    }
)
async def search_templates(
    ctx: RunContext[AgentDependencies],
    category: Optional[str] = None,
    awareness_level: Optional[int] = None,
    source_brand: Optional[str] = None,
    limit: int = 10,
) -> str:
    """
    Search approved ad templates that can be used for ad creation.

    Use this to help users discover and choose templates before creating ads.

    Args:
        ctx: Run context with AgentDependencies
        category: Filter by template category (e.g. "direct_response", "social_proof",
            "testimonial", "ugc", "lifestyle", "comparison")
        awareness_level: Filter by awareness level (1-5, where 1=unaware, 5=most_aware)
        source_brand: Filter by brand name that the template was scraped from
        limit: Max results (default: 10, max: 25)

    Returns:
        Formatted markdown table of matching templates with IDs, names, categories,
        and canvas sizes for use with create_ads_v2.
    """
    limit = min(limit, 25)

    templates = ctx.deps.template_queue.get_templates(
        category=category,
        awareness_level=awareness_level,
        source_brand=source_brand,
        limit=limit,
    )

    if not templates:
        return "No templates found matching your criteria."

    lines = [f"**Templates Found** ({len(templates)} results)\n"]
    lines.append("| ID | Name | Category | Size | Awareness |")
    lines.append("|---|---|---|---|---|")

    for t in templates:
        tid = t.get("id", "")
        name = t.get("name", "Unnamed")[:40]
        cat = t.get("category", "-")
        size = t.get("canvas_size", "-")
        awareness = t.get("awareness_level", "-")
        lines.append(f"| `{tid}` | {name} | {cat} | {size} | {awareness} |")

    lines.append(f"\nUse a template ID with `create_ads_v2` to generate ads from it.")
    return "\n".join(lines)


EDIT_PRESETS = [
    "text_larger", "more_contrast", "brighter", "warmer",
    "cooler", "bolder_cta", "cleaner_layout"
]


@ad_creation_agent.tool(
    metadata={
        'category': 'Generation',
        'platform': 'Facebook',
        'use_cases': [
            'Apply a quick edit preset to an approved ad',
            'Make text bigger, bolder CTA, adjust colors',
        ],
        'examples': [
            'Make the text larger on this ad',
            'Apply bolder CTA to ad X',
            'Make this ad warmer'
        ]
    }
)
async def smart_edit_ad(
    ctx: RunContext[AgentDependencies],
    source_ad_id: str,
    preset: str,
) -> Dict:
    """
    Apply a preset edit to an existing approved ad.

    Available presets:
    - text_larger: Make all text 20% larger and more prominent
    - more_contrast: Increase contrast between text and background
    - brighter: Make the overall image 15% brighter
    - warmer: Shift colors to warmer tones (orange/red)
    - cooler: Shift colors to cooler tones (blue/green)
    - bolder_cta: Make the CTA button/text more prominent
    - cleaner_layout: Simplify layout, reduce visual clutter

    Args:
        ctx: Run context with AgentDependencies
        source_ad_id: UUID of the approved ad to edit
        preset: One of the available preset names listed above

    Returns:
        Dictionary with the new edited ad ID, storage path, and review results.
    """
    from uuid import UUID as _UUID

    if preset not in EDIT_PRESETS:
        return {
            "error": f"Invalid preset '{preset}'. Available: {', '.join(EDIT_PRESETS)}"
        }

    try:
        result = await ctx.deps.ad_creation.create_edited_ad(
            source_ad_id=_UUID(source_ad_id),
            edit_prompt=preset,
        )
        return {
            "success": True,
            "new_ad_id": str(result.get("id", "")),
            "storage_path": result.get("storage_path", ""),
            "final_status": result.get("final_status", ""),
            "preset_applied": preset,
            "parent_ad_id": source_ad_id,
        }
    except Exception as e:
        return {"error": f"Failed to edit ad: {e}"}


@ad_creation_agent.tool(
    metadata={
        'category': 'Generation',
        'platform': 'Facebook',
        'use_cases': [
            'Retry a rejected or flagged ad with a fresh attempt',
            'Regenerate an ad that failed review',
        ],
        'examples': [
            'Regenerate this rejected ad',
            'Retry ad X',
        ]
    }
)
async def regenerate_ad(
    ctx: RunContext[AgentDependencies],
    source_ad_id: str,
) -> Dict:
    """
    Regenerate a rejected or flagged ad with a fresh attempt.

    Takes the original ad's parameters and generates a new version,
    which goes through dual AI review (Claude + Gemini).

    Args:
        ctx: Run context with AgentDependencies
        source_ad_id: UUID of the rejected or flagged ad to regenerate

    Returns:
        Dictionary with the new ad ID, status, and review results.
    """
    from uuid import UUID as _UUID

    try:
        result = await ctx.deps.ad_creation.regenerate_ad(
            source_ad_id=_UUID(source_ad_id),
        )
        return {
            "success": True,
            "new_ad_id": str(result.get("id", "")),
            "storage_path": result.get("storage_path", ""),
            "final_status": result.get("final_status", ""),
            "parent_ad_id": source_ad_id,
        }
    except Exception as e:
        return {"error": f"Failed to regenerate ad: {e}"}


# ============================================================================
# EXPORT TOOLS
# ============================================================================

@ad_creation_agent.tool(
    metadata={
        'category': 'Export',
        'platform': 'All',
        'rate_limit': '10/minute',
        'use_cases': [
            'Send generated ads via email',
            'Email ad export with download links',
            'Notify team of completed ad runs'
        ],
        'examples': [
            'Email the generated ads to marketing@company.com',
            'Send ad export to user with download link'
        ]
    }
)
async def send_ads_email(
    ctx: RunContext[AgentDependencies],
    to_email: str,
    product_name: str,
    brand_name: str,
    image_urls: List[str],
    zip_download_url: Optional[str] = None,
    schedule_name: Optional[str] = None
) -> Dict:
    """
    Send an email with generated ad images and download links.

    This tool sends an HTML email containing:
    - Preview thumbnails of generated ads
    - Direct links to view each ad
    - Optional ZIP download link for bulk download
    - Brand and product information

    Args:
        ctx: Run context with AgentDependencies
        to_email: Recipient email address
        product_name: Name of the product for context
        brand_name: Name of the brand for context
        image_urls: List of public URLs for generated ad images
        zip_download_url: Optional URL to download all images as ZIP
        schedule_name: Optional schedule name if from scheduled job

    Returns:
        Dictionary with send result:
        {
            "success": true/false,
            "message_id": "email-id" (if success),
            "error": "error message" (if failed)
        }

    Raises:
        Exception: If email service is disabled or send fails
    """
    from ...services.email_service import AdEmailContent

    try:
        logger.info(f"Sending ad export email to {to_email}")

        if not ctx.deps.email.enabled:
            return {
                "success": False,
                "error": "Email service is disabled - RESEND_API_KEY not configured"
            }

        content = AdEmailContent(
            product_name=product_name,
            brand_name=brand_name,
            image_urls=image_urls,
            zip_download_url=zip_download_url,
            schedule_name=schedule_name
        )

        result = await ctx.deps.email.send_ad_export_email(
            to_email=to_email,
            content=content
        )

        if result.success:
            logger.info(f"Email sent successfully: {result.message_id}")
            return {
                "success": True,
                "message_id": result.message_id
            }
        else:
            logger.error(f"Email send failed: {result.error}")
            return {
                "success": False,
                "error": result.error
            }

    except Exception as e:
        logger.error(f"Failed to send email: {str(e)}")
        raise Exception(f"Failed to send email: {str(e)}")


@ad_creation_agent.tool(
    metadata={
        'category': 'Export',
        'platform': 'All',
        'rate_limit': '10/minute',
        'use_cases': [
            'Post generated ads to Slack channel',
            'Send Slack notification of completed ads',
            'Share ad previews with team on Slack'
        ],
        'examples': [
            'Post the generated ads to Slack',
            'Send ad notification to the marketing channel'
        ]
    }
)
async def send_ads_slack(
    ctx: RunContext[AgentDependencies],
    product_name: str,
    brand_name: str,
    image_urls: List[str],
    zip_download_url: Optional[str] = None,
    schedule_name: Optional[str] = None,
    webhook_url: Optional[str] = None
) -> Dict:
    """
    Send a Slack message with generated ad images and download links.

    This tool posts a rich Block Kit message containing:
    - Header with brand/product info
    - Image previews (first 3 images)
    - Links to view all images
    - Download ZIP button
    - Context about the generation

    Args:
        ctx: Run context with AgentDependencies
        product_name: Name of the product for context
        brand_name: Name of the brand for context
        image_urls: List of public URLs for generated ad images
        zip_download_url: Optional URL to download all images as ZIP
        schedule_name: Optional schedule name if from scheduled job
        webhook_url: Optional override webhook URL (for per-schedule channels)

    Returns:
        Dictionary with send result:
        {
            "success": true/false,
            "error": "error message" (if failed)
        }

    Raises:
        Exception: If Slack service is disabled or send fails
    """
    from ...services.slack_service import AdSlackContent

    try:
        logger.info(f"Sending ad export to Slack")

        if not ctx.deps.slack.enabled and not webhook_url:
            return {
                "success": False,
                "error": "Slack service is disabled - no webhook URL configured"
            }

        content = AdSlackContent(
            product_name=product_name,
            brand_name=brand_name,
            image_urls=image_urls,
            zip_download_url=zip_download_url,
            schedule_name=schedule_name
        )

        result = await ctx.deps.slack.send_ad_export_message(
            content=content,
            webhook_url=webhook_url
        )

        if result.success:
            logger.info("Slack message sent successfully")
            return {"success": True}
        else:
            logger.error(f"Slack send failed: {result.error}")
            return {
                "success": False,
                "error": result.error
            }

    except Exception as e:
        logger.error(f"Failed to send Slack message: {str(e)}")
        raise Exception(f"Failed to send Slack message: {str(e)}")


# ============================================================================
# SIZE VARIANT TOOLS
# ============================================================================

@ad_creation_agent.tool(
    metadata={
        'category': 'Generation',
        'platform': 'Facebook',
        'rate_limit': '1/minute',
        'use_cases': [
            'Create size variant of existing ad',
            'Resize approved ad to different aspect ratio',
            'Generate Facebook/Instagram story version from feed ad'
        ],
        'examples': [
            'Create 1:1 version of this 9:16 story ad',
            'Generate 4:5 feed version from this square ad'
        ]
    }
)
async def generate_size_variant(
    ctx: RunContext[AgentDependencies],
    source_ad_id: str,
    target_size: str
) -> Dict:
    """
    Generate a size variant of an existing ad.

    Takes an approved ad and creates a version at a different aspect ratio,
    keeping all visual elements as similar as possible.

    Args:
        ctx: Run context with AgentDependencies
        source_ad_id: UUID of the source ad to resize
        target_size: Target size ratio ("1:1", "4:5", "9:16", "16:9")

    Returns:
        Dict with variant info including storage_path, variant_id

    Raises:
        ValueError: If target_size is invalid or source ad not found
        Exception: If generation fails
    """
    from uuid import UUID

    try:
        logger.info(f"=== GENERATING SIZE VARIANT: {target_size} for ad {source_ad_id} ===")

        # Call the service layer which handles all the generation logic
        result = await ctx.deps.ad_creation.create_size_variant(
            source_ad_id=UUID(source_ad_id),
            target_size=target_size
        )

        logger.info(f"✅ Created {target_size} variant: {result['variant_id']}")

        return {
            "success": True,
            "variant_id": result["variant_id"],
            "parent_ad_id": source_ad_id,
            "variant_size": result["variant_size"],
            "storage_path": result["storage_path"],
            "generation_time_ms": result["generation_time_ms"]
        }

    except ValueError as e:
        logger.error(f"Invalid input: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Failed to generate size variant: {str(e)}")
        raise Exception(f"Failed to generate size variant: {str(e)}")


# ============================================================================
# PERSONA TOOLS
# ============================================================================

@ad_creation_agent.tool(
    metadata={
        'category': 'Ingestion',
        'platform': 'Facebook',
        'rate_limit': '30/minute',
        'use_cases': [
            'Get persona data for ad copy generation',
            'Retrieve customer insights for messaging',
            'Load persona desires, pain points, and language'
        ],
        'examples': [
            'Get persona for this product to write better copy',
            'What personas are available for this product?',
            'Use the primary persona for ad generation'
        ]
    }
)
async def get_persona_for_copy(
    ctx: RunContext[AgentDependencies],
    product_id: str,
    persona_id: Optional[str] = None
) -> Dict:
    """
    Get persona data formatted for ad copy generation.

    This tool retrieves 4D persona data to inform ad copy generation.
    If persona_id is provided, uses that specific persona.
    Otherwise returns the primary persona for the product.

    The returned copy brief includes:
    - Primary desires to appeal to
    - Pain points to address
    - Language/verbiage to use (their actual words)
    - Objections to handle
    - Activation events for urgency
    - Allergies (messaging turn-offs to avoid)

    Args:
        ctx: Run context with AgentDependencies
        product_id: UUID of the product
        persona_id: Optional specific persona UUID to use

    Returns:
        Dictionary with persona data formatted for copy generation:
        {
            "persona_name": "Worried First-Time Dog Mom",
            "snapshot": "2-3 sentence description",
            "primary_desires": ["I want to give my dog the best"],
            "top_pain_points": ["Worry about making wrong choice"],
            "their_language": ["Because I am a responsible owner..."],
            "transformation": {"before": [...], "after": [...]},
            "objections": ["What if it doesn't work?"],
            "activation_events": ["Vet visit", "Bad breath noticed"],
            "allergies": {"fake urgency": "distrust"}
        }
    """
    from uuid import UUID as UUIDType

    try:
        if persona_id:
            copy_brief = ctx.deps.persona.export_for_copy_brief_dict(UUIDType(persona_id))
        else:
            persona = ctx.deps.persona.get_primary_persona_for_product(UUIDType(product_id))
            if not persona:
                return {
                    "error": "No persona found for product",
                    "suggestion": "Create a persona using the Persona Builder UI or generate one with AI"
                }
            copy_brief = ctx.deps.persona.export_for_copy_brief_dict(persona.id)

        logger.info(f"Retrieved persona copy brief for product {product_id}")
        return copy_brief

    except Exception as e:
        logger.error(f"Failed to get persona: {e}")
        return {"error": str(e)}


@ad_creation_agent.tool(
    metadata={
        'category': 'Ingestion',
        'platform': 'Facebook',
        'rate_limit': '30/minute',
        'use_cases': [
            'List available personas for a product',
            'See what personas are linked to a product'
        ],
        'examples': [
            'What personas are available for this product?',
            'List personas for product X'
        ]
    }
)
async def list_product_personas(
    ctx: RunContext[AgentDependencies],
    product_id: str
) -> Dict:
    """
    List all personas linked to a product.

    This tool returns a list of all personas associated with a product,
    including which one is marked as primary.

    Args:
        ctx: Run context with AgentDependencies
        product_id: UUID of the product

    Returns:
        Dictionary with list of personas:
        {
            "personas": [
                {
                    "id": "uuid",
                    "name": "Worried First-Time Dog Mom",
                    "is_primary": true,
                    "snapshot": "Brief description",
                    "source_type": "ai_generated"
                }
            ],
            "count": 1
        }
    """
    from uuid import UUID as UUIDType

    try:
        personas = ctx.deps.persona.get_personas_for_product(UUIDType(product_id))

        return {
            "personas": [
                {
                    "id": str(p.id),
                    "name": p.name,
                    "is_primary": p.is_primary,
                    "snapshot": p.snapshot,
                    "source_type": p.source_type.value if hasattr(p.source_type, 'value') else p.source_type
                }
                for p in personas
            ],
            "count": len(personas)
        }

    except Exception as e:
        logger.error(f"Failed to list personas: {e}")
        return {"error": str(e), "personas": [], "count": 0}


# ============================================================================
# Template Queue Tools
# ============================================================================


@ad_creation_agent.tool(
    metadata={
        "category": "Query",
        "platform": "Templates",
        "use_cases": [
            "Check template queue status",
            "See how many templates need review",
            "Get template pipeline health",
        ],
        "examples": [
            "How many templates are pending review?",
            "Template queue stats",
            "What's the template queue look like?",
        ],
    }
)
async def get_template_queue_stats(
    ctx: RunContext[AgentDependencies],
) -> str:
    """Get template queue statistics: pending, approved, rejected, archived counts.

    Args:
        ctx: Run context with AgentDependencies.

    Returns:
        Formatted template queue status with counts by status.
    """
    try:
        stats = ctx.deps.template_queue.get_queue_stats()

        if not stats:
            return "No template queue data available."

        total = sum(stats.values())
        lines = [
            "## Template Queue Stats\n",
            f"- **Total:** {total}",
            f"- ⏳ Pending: {stats.get('pending', 0)}",
            f"- ✅ Approved: {stats.get('approved', 0)}",
            f"- ❌ Rejected: {stats.get('rejected', 0)}",
            f"- 📦 Archived: {stats.get('archived', 0)}",
        ]

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"get_template_queue_stats failed: {e}")
        return f"Failed to get template queue stats: {e}"


@ad_creation_agent.tool(
    metadata={
        "category": "Query",
        "platform": "Templates",
        "use_cases": [
            "See pending templates",
            "Review template queue",
            "List templates awaiting approval",
        ],
        "examples": [
            "Show me pending templates",
            "What templates need review?",
            "List the template queue",
        ],
    }
)
async def list_pending_templates(
    ctx: RunContext[AgentDependencies],
    limit: int = 10,
) -> str:
    """List templates pending review in the approval queue.

    Args:
        ctx: Run context with AgentDependencies.
        limit: Max items to return (default: 10, max: 25).

    Returns:
        Formatted list of pending templates with IDs and source info.
    """
    limit = min(limit, 25)

    try:
        pending = ctx.deps.template_queue.get_pending_queue(limit=limit, offset=0)

        if not pending:
            return "No templates pending review."

        lines = [f"**Pending Templates** ({len(pending)} shown)\n"]
        for i, item in enumerate(pending, 1):
            name = item.get("name") or item.get("ad_name") or "Untitled"
            source = item.get("source_brand") or "Unknown source"
            line = f"{i}. **{name}** — from {source}"
            if item.get("id"):
                line += f"\n   ID: `{item['id']}`"
            lines.append(line)

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"list_pending_templates failed: {e}")
        return f"Failed to list pending templates: {e}"


# ============================================================================
# TRANSLATION TOOLS
# ============================================================================

@ad_creation_agent.tool(
    metadata={
        'category': 'Translation',
        'rate_limit': '30/minute',
        'use_cases': [
            'Look up any ad by its UUID, structured filename, or Meta ad ID',
            'Get ad details including copy, image URL, performance data, and lineage',
        ],
        'examples': [
            'Find the ad with ID 65bb40',
            'Look up ad SAV-FTS-65bb40-04161b-SQ',
            'Show me ad details for Meta ad 23851234567890',
        ]
    }
)
async def lookup_ad(
    ctx: RunContext[AgentDependencies],
    query: str,
) -> Dict:
    """Look up an ad by ID. Accepts any format:
    - Full UUID (e.g. 65bb40a1-...)
    - Structured filename or fragment (e.g. SAV-FTS-65bb40-04161b-SQ or just 65bb40)
    - Meta ad ID (numeric, e.g. 23851234567890)

    Returns ad details including copy, image URL, performance data, and translation lineage.

    IMPORTANT: When displaying results, embed the ad image inline using markdown image syntax:
    ![Ad Preview](image_url_value)
    Do NOT use a text link. The user wants to SEE the ad image in the chat.
    Also include a "View Full Size" link below the image: [View Full Size](image_url_value)

    Args:
        ctx: Run context with AgentDependencies.
        query: Ad identifier in any supported format.

    Returns:
        Ad details dict or error message. image_url contains a signed URL for the ad image.
    """
    try:
        result = await ctx.deps.ad_translation.lookup_ad(query)
        if result is None:
            return {"error": f"No ad found matching '{query}'"}
        # Strip large fields that clutter the LLM response
        result.pop("prompt_spec", None)
        result.pop("prompt_text", None)
        return result
    except Exception as e:
        logger.error(f"lookup_ad failed: {e}")
        return {"error": f"Failed to look up ad: {e}"}


@ad_creation_agent.tool(
    metadata={
        'category': 'Translation',
        'rate_limit': '5/minute',
        'use_cases': [
            'Translate existing winning ads into Spanish, Portuguese, or any language',
            'Batch translate top-performing ads by ROAS',
            'Create translated versions of specific ads',
        ],
        'examples': [
            'Translate ad 65bb40 into Spanish',
            'Translate my top 5 ads for Cortisol Control into Mexican Spanish',
            'Translate these ads into Portuguese: ad1, ad2, ad3',
        ]
    }
)
async def translate_ads(
    ctx: RunContext[AgentDependencies],
    target_language: str,
    ad_ids: Optional[List[str]] = None,
    product_id: Optional[str] = None,
    top_n_by_roas: Optional[int] = None,
) -> Dict:
    """Translate existing ads into a target language. Regenerates images with translated text.
    Use this tool (NOT lookup_ad) when the user asks to translate an ad.
    Provide specific ad IDs, or use product_id + top_n_by_roas to auto-select winners.

    ad_ids accepts ANY format: full UUIDs, filename fragments (e.g. "65bb40"),
    or structured filenames (e.g. "SAV-FTS-65bb40-04161b-SQ"). They will be
    resolved to UUIDs automatically.

    Args:
        ctx: Run context with AgentDependencies.
        target_language: Target language as IETF tag (es-MX, pt-BR, fr-FR) or name (Spanish, Portuguese, American Spanish).
        ad_ids: Optional list of ad identifiers to translate (UUIDs, filename fragments, or structured filenames).
        product_id: Optional product UUID for performance-filtered batch selection.
        top_n_by_roas: Optional number of top ads by ROAS to translate (requires product_id).

    Returns:
        Translation results with counts, ad_run_id, and per-ad success/failure details.
    """
    try:
        # Resolve ad identifiers to UUIDs (supports fragments, filenames, etc.)
        resolved_ids = None
        if ad_ids:
            resolved_ids = []
            for aid in ad_ids:
                # Try direct UUID parse first
                try:
                    resolved_ids.append(UUID(aid))
                    continue
                except ValueError:
                    pass
                # Fall back to lookup
                result = await ctx.deps.ad_translation.lookup_ad(aid)
                if result and not result.get("multiple_matches") and result.get("id"):
                    resolved_ids.append(UUID(result["id"]))
                elif result and result.get("multiple_matches"):
                    return {"error": f"Ambiguous ad identifier '{aid}' matched {result['count']} ads. Use a more specific ID."}
                else:
                    return {"error": f"Could not find ad matching '{aid}'"}

        parsed_product = UUID(product_id) if product_id else None

        result = await ctx.deps.ad_translation.translate_batch(
            ad_ids=[str(aid) for aid in resolved_ids] if resolved_ids else None,
            product_id=str(parsed_product) if parsed_product else None,
            top_n_by_roas=top_n_by_roas,
            target_language=target_language,
        )
        return result
    except ValueError as e:
        return {"error": f"Invalid ID format: {e}"}
    except Exception as e:
        logger.error(f"translate_ads failed: {e}")
        return {"error": f"Failed to translate ads: {e}"}


# ============================================================================
# Tool count and initialization
# ============================================================================

logger.info("Ad Creation Agent initialized with 16 tools")
