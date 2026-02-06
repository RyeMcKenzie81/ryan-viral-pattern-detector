"""
Ad Creation Agent - Specialized agent for Facebook ad creative generation.

The main workflow is handled by the ad_creation pipeline (pydantic-graph).
This agent exposes 9 tools:
- Data retrieval: get_product_with_images, get_hooks_for_product
- Analysis: analyze_product_image
- Orchestration: complete_ad_workflow (thin wrapper → pipeline)
- Export: send_ads_email, send_ads_slack
- Post-processing: generate_size_variant
- Personas: get_persona_for_copy, list_product_personas
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
    model=Config.get_model("ad_creation"),
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
Use them sequentially, validating output at each step.

**Available Services:**
- AdCreationService: For product/hook/template data and storage operations
- GeminiService: For AI vision analysis, image generation, and reviews

**Result Format:**
- Provide clear, structured responses
- Show generation progress for each ad
- Include review scores and approval status
- Return complete AdCreationResult with all metadata
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
        product_id: UUID of product as string

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
    try:
        logger.info(f"Fetching product: {product_id}")

        # Convert string to UUID
        product_uuid = UUID(product_id)

        # Fetch product via service
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





@ad_creation_agent.tool(
    metadata={
        'category': 'Generation',
        'platform': 'Facebook',
        'rate_limit': '1/minute',
        'use_cases': [
            'Execute complete ad creation workflow end-to-end',
            'Orchestrate all 13 tools in sequence',
            'Generate ad variations with dual AI review'
        ],
        'examples': [
            'Create complete ad campaign for Wonder Paws',
            'Generate 10 Facebook ads with full workflow'
        ]
    }
)
async def complete_ad_workflow(
    ctx: RunContext[AgentDependencies],
    product_id: str,
    reference_ad_base64: str,
    reference_ad_filename: str = "reference.png",
    project_id: Optional[str] = None,
    num_variations: int = 5,
    content_source: str = "hooks",
    color_mode: str = "original",
    brand_colors: Optional[Dict] = None,
    image_selection_mode: str = "auto",
    selected_image_paths: Optional[List[str]] = None,
    persona_id: Optional[str] = None,
    variant_id: Optional[str] = None,
    additional_instructions: Optional[str] = None,
    angle_data: Optional[Dict] = None,
    match_template_structure: bool = False,
    offer_variant_id: Optional[str] = None,
    image_resolution: str = "2K"
) -> Dict:
    """
    Execute complete ad creation workflow from start to finish.

    This orchestration tool:
    1. Creates ad run in database
    2. Uploads reference ad to storage
    3. Fetches product data (and hooks if content_source="hooks")
    4. Fetches persona data if persona_id provided
    5. Analyzes reference ad (Vision AI)
    6. Gets content variations:
       - If content_source="hooks": Selects N diverse hooks from database
       - If content_source="recreate_template": Extracts template angle and
         generates variations from product benefits/USPs
       - If content_source="belief_first": Uses provided angle's belief statement
       - All modes use persona data to inform copy when available
    7. Generates N ad variations (ONE AT A TIME)
    8. Dual AI review (Claude + Gemini) for each ad
    9. Applies OR logic: either reviewer approving = approved
    10. Returns complete AdCreationResult

    **CRITICAL: Dual Review Logic (OR Logic)**
    - If Claude OR Gemini approves → APPROVED
    - If both reject → REJECTED
    - If reviewers disagree on non-approval → FLAGGED for human review

    Args:
        ctx: Run context with AgentDependencies
        product_id: UUID of product as string
        reference_ad_base64: Base64-encoded reference ad image
        reference_ad_filename: Filename for storage (default: reference.png)
        project_id: Optional UUID of project as string
        num_variations: Number of ad variations to generate (default: 5, max: 15)
        content_source: Source for ad content variations:
            - "hooks": Use hooks from database (default)
            - "recreate_template": Extract template angle and use product benefits
            - "belief_first": Use provided angle's belief statement
        color_mode: Color scheme to use ("original", "complementary", "brand")
        brand_colors: Brand color data when color_mode is "brand"
        image_selection_mode: How to select product images:
            - "auto": AI selects best matching 1-2 images (default)
            - "manual": Use user-selected images
        selected_image_paths: List of storage paths when image_selection_mode is "manual" (1-2 images)
        persona_id: Optional UUID of 4D persona to target. When provided, persona's
            pain points, desires, and language inform hook selection and copy generation.
        variant_id: Optional UUID of product variant (flavor, size, color). When provided,
            variant name and description are used to customize ad copy for that specific variant.
        additional_instructions: Optional run-specific instructions for ad generation. Combined
            with brand's ad_creation_notes to guide the AI in creating ads.
        angle_data: Dict with angle info for belief_first mode. Required when
            content_source="belief_first". Structure: {id, name, belief_statement, explanation}
        match_template_structure: If True with belief_first mode, extract the reference ad's
            template structure and adapt the belief statement to match it. Creates headlines
            that follow the template's style while communicating the belief.
        offer_variant_id: Optional UUID of offer variant (landing page angle). When provided,
            the offer variant's pain points, benefits, and target audience are used to ensure
            ad copy is congruent with the destination landing page messaging.

    Returns:
        Dictionary with AdCreationResult structure:
        {
            "ad_run_id": "uuid",
            "product": {...},
            "reference_ad_path": "storage path",
            "ad_analysis": {...},
            "content_source": "hooks" or "recreate_template",
            "template_angle": {...} (only if recreate_template),
            "selected_hooks": [...],
            "generated_ads": [
                {
                    "prompt_index": 1,
                    "prompt": {...},
                    "storage_path": "...",
                    "claude_review": {...},
                    "gemini_review": {...},
                    "reviewers_agree": true/false,
                    "final_status": "approved"/"rejected"/"flagged"
                },
                ...
            ],
            "approved_count": 3,
            "rejected_count": 1,
            "flagged_count": 1,
            "summary": "Human-readable summary",
            "created_at": "ISO timestamp"
        }

    Raises:
        Exception: If workflow fails at any stage
        ValueError: If num_variations is out of range (1-15) or invalid content_source
    """
    from viraltracker.pipelines.ad_creation.orchestrator import run_ad_creation

    return await run_ad_creation(
        product_id=product_id,
        reference_ad_base64=reference_ad_base64,
        reference_ad_filename=reference_ad_filename,
        project_id=project_id,
        num_variations=num_variations,
        content_source=content_source,
        color_mode=color_mode,
        brand_colors=brand_colors,
        image_selection_mode=image_selection_mode,
        selected_image_paths=selected_image_paths,
        persona_id=persona_id,
        variant_id=variant_id,
        offer_variant_id=offer_variant_id,
        additional_instructions=additional_instructions,
        angle_data=angle_data,
        match_template_structure=match_template_structure,
        image_resolution=image_resolution,
        deps=ctx.deps,
    )



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
# Tool count and initialization
# ============================================================================

logger.info("Ad Creation Agent initialized with 9 tools (pipeline handles orchestration)")
