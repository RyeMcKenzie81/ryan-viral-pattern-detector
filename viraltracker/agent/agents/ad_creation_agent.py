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
from typing import List, Dict, Optional
from uuid import UUID
from pydantic_ai import Agent, RunContext
from ..dependencies import AgentDependencies

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
# DATA RETRIEVAL TOOLS (1-4)
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
        return product.dict()

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
        return [hook.dict() for hook in hooks]

    except ValueError as e:
        logger.error(f"Invalid product_id: {product_id}")
        raise ValueError(f"Invalid product_id: {product_id}")
    except Exception as e:
        logger.error(f"Failed to fetch hooks: {str(e)}")
        raise Exception(f"Failed to fetch hooks: {str(e)}")


@ad_creation_agent.tool(
    metadata={
        'category': 'Ingestion',
        'platform': 'Facebook',
        'rate_limit': '30/minute',
        'use_cases': [
            'Get ad brief template for brand',
            'Load global ad creation instructions',
            'Retrieve brand-specific guidelines'
        ],
        'examples': [
            'Get ad brief template for brand',
            'Load global ad creation instructions'
        ]
    }
)
async def get_ad_brief_template(
    ctx: RunContext[AgentDependencies],
    brand_id: Optional[str] = None
) -> Dict:
    """
    Fetch ad brief template for brand (or global).

    This tool retrieves the ad creation instructions template that contains
    guidelines for image generation, brand voice, and creative requirements.
    Falls back to global template if brand-specific template not found.

    Args:
        ctx: Run context with AgentDependencies
        brand_id: UUID of brand as string (None = use global template)

    Returns:
        Dictionary with ad brief template:
        {
            "id": "uuid",
            "brand_id": "uuid" or null,
            "name": "Template Name",
            "instructions": "Detailed instructions for ad generation...",
            "active": true
        }

    Raises:
        ValueError: If no template found for brand or globally
    """
    try:
        logger.info(f"Fetching ad brief template (brand_id: {brand_id})")

        # Convert string to UUID if provided
        brand_uuid = UUID(brand_id) if brand_id else None

        # Fetch template via service
        template = await ctx.deps.ad_creation.get_ad_brief_template(brand_id=brand_uuid)

        logger.info(f"Ad brief template fetched: {template.name}")
        return template.dict()

    except ValueError as e:
        logger.error(f"No ad brief template found")
        raise ValueError("No ad brief template found")
    except Exception as e:
        logger.error(f"Failed to fetch ad brief template: {str(e)}")
        raise Exception(f"Failed to fetch ad brief template: {str(e)}")


@ad_creation_agent.tool(
    metadata={
        'category': 'Ingestion',
        'platform': 'Facebook',
        'rate_limit': '10/minute',
        'use_cases': [
            'Upload reference ad image to storage',
            'Save user-provided reference ad',
            'Store reference image for analysis'
        ],
        'examples': [
            'Upload reference ad for analysis',
            'Save reference image to storage'
        ]
    }
)
async def upload_reference_ad(
    ctx: RunContext[AgentDependencies],
    ad_run_id: str,
    image_base64: str,
    filename: str = "reference.png"
) -> str:
    """
    Upload reference ad image to Supabase Storage.

    This tool uploads the user-provided reference ad image to storage
    so it can be analyzed by the vision AI to understand the desired
    ad format and style.

    Args:
        ctx: Run context with AgentDependencies
        ad_run_id: UUID of ad run as string
        image_base64: Base64-encoded image data
        filename: Filename for storage (default: reference.png)

    Returns:
        Storage path string: "reference-ads/{ad_run_id}_{filename}"

    Raises:
        ValueError: If image_base64 is invalid or empty
    """
    try:
        import base64

        logger.info(f"Uploading reference ad for run: {ad_run_id}")

        # Validate inputs
        if not image_base64:
            raise ValueError("image_base64 cannot be empty")

        # Convert string to UUID
        ad_run_uuid = UUID(ad_run_id)

        # Decode base64 to bytes
        try:
            image_data = base64.b64decode(image_base64)
        except Exception as e:
            raise ValueError(f"Invalid base64 image data: {str(e)}")

        # Upload via service
        storage_path = await ctx.deps.ad_creation.upload_reference_ad(
            ad_run_id=ad_run_uuid,
            image_data=image_data,
            filename=filename
        )

        logger.info(f"Reference ad uploaded: {storage_path}")
        return storage_path

    except ValueError as e:
        logger.error(f"Upload failed: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Failed to upload reference ad: {str(e)}")
        raise Exception(f"Failed to upload reference ad: {str(e)}")


# ============================================================================
# Tool count and initialization
# ============================================================================

logger.info("Ad Creation Agent initialized with 4 tools (Data Retrieval)")
