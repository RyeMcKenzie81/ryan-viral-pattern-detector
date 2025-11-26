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
        return template.model_dump(mode='json')

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
# ANALYSIS & GENERATION TOOLS (5-10)
# ============================================================================

@ad_creation_agent.tool(
    metadata={
        'category': 'Analysis',
        'platform': 'Facebook',
        'rate_limit': '5/minute',
        'use_cases': [
            'Analyze reference ad format and structure using Vision AI',
            'Extract layout patterns from reference ad',
            'Identify visual elements to replicate'
        ],
        'examples': [
            'Analyze reference ad for Wonder Paws campaign',
            'Extract ad format from reference image'
        ]
    }
)
async def analyze_reference_ad(
    ctx: RunContext[AgentDependencies],
    reference_ad_storage_path: str
) -> Dict:
    """
    Analyze reference ad using Vision AI to understand format and style.

    This tool uses Gemini Vision AI to analyze the user-provided reference ad
    and extract:
    - Format type (testimonial, quote-style, before/after, product showcase)
    - Layout structure (single image, two-panel, carousel)
    - Fixed vs variable elements
    - Text placement guidelines
    - Color palette (hex codes)
    - Authenticity markers (timestamps, usernames, emojis)
    - Canvas dimensions

    The analysis is used to create 5 variations that match the reference style.

    Args:
        ctx: Run context with AgentDependencies
        reference_ad_storage_path: Storage path to reference ad image
            (e.g., "reference-ads/{ad_run_id}_reference.png")

    Returns:
        Dictionary with ad analysis including format, layout, colors, and
        detailed description for prompt engineering:
        {
            "format_type": "testimonial",
            "layout_structure": "single_image",
            "fixed_elements": ["product_bottle", "offer_bar"],
            "variable_elements": ["hook_text", "background_color"],
            "text_placement": {"headline": "top_center", ...},
            "color_palette": ["#F5F0E8", "#2A5434", "#555555"],
            "authenticity_markers": ["screenshot_style", "quote_marks"],
            "canvas_size": "1080x1080px",
            "detailed_description": "Full description for prompt..."
        }

    Raises:
        ValueError: If reference ad path is invalid or empty
        Exception: If Gemini Vision AI analysis fails
    """
    try:
        import json

        logger.info(f"Analyzing reference ad: {reference_ad_storage_path}")

        # Validate input
        if not reference_ad_storage_path:
            raise ValueError("reference_ad_storage_path cannot be empty")

        # Download reference ad image from storage as base64
        image_data = await ctx.deps.ad_creation.get_image_as_base64(reference_ad_storage_path)

        # Analyze using Gemini Vision AI
        analysis_prompt = """
        Analyze this Facebook ad reference image and extract the following:

        1. **Format Type**: What type of ad is this?
           - testimonial (customer quote/review)
           - quote_style (text overlay on product)
           - before_after (transformation showcase)
           - product_showcase (product-focused with benefits)

        2. **Layout Structure**: How is the ad laid out?
           - single_image (one cohesive design)
           - two_panel (split screen/side-by-side)
           - carousel (multiple frames)

        3. **Fixed Elements**: What elements should stay the same across all 5 variations?
           (e.g., product bottle, logo, offer bar, benefit icons)

        4. **Variable Elements**: What elements should change per variation?
           (e.g., hook text, background color, testimonial name)

        5. **Text Placement**: Where is text positioned?
           Provide a mapping of text type → position
           (e.g., headline: top_center, subheadline: below_headline, benefits: corners)

        6. **Color Palette**: Extract main colors as hex codes
           (background, text, accent colors)

        7. **Authenticity Markers**: What makes this feel authentic?
           (e.g., screenshot style, quote marks, timestamps, usernames, emojis, casual font)

        8. **Canvas Size**: What are the dimensions? (e.g., 1080x1080px, 1200x628px)

        9. **Detailed Description**: Provide a comprehensive description of the ad
           that could be used for prompt engineering. Include layout, visual style,
           typography, spacing, and any notable design elements.

        Return the analysis as structured JSON matching this schema:
        {
            "format_type": "string",
            "layout_structure": "string",
            "fixed_elements": ["string"],
            "variable_elements": ["string"],
            "text_placement": {"key": "value"},
            "color_palette": ["#HEX"],
            "authenticity_markers": ["string"],
            "canvas_size": "WIDTHxHEIGHTpx",
            "detailed_description": "comprehensive description..."
        }
        """

        # Call Gemini Vision API
        analysis_result = await ctx.deps.gemini.analyze_image(
            image_data=image_data,
            prompt=analysis_prompt
        )

        # Strip markdown code fences if present (Gemini often wraps JSON in ```json...```)
        analysis_result_clean = analysis_result.strip()
        if analysis_result_clean.startswith('```'):
            # Find the first newline after the opening fence
            first_newline = analysis_result_clean.find('\n')
            # Find the closing fence
            last_fence = analysis_result_clean.rfind('```')
            if first_newline != -1 and last_fence > first_newline:
                analysis_result_clean = analysis_result_clean[first_newline + 1:last_fence].strip()

        # Parse JSON response
        analysis_dict = json.loads(analysis_result_clean)

        logger.info(f"Reference ad analyzed: format={analysis_dict.get('format_type')}, "
                   f"layout={analysis_dict.get('layout_structure')}")

        return analysis_dict

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Gemini analysis response: {str(e)}")
        raise Exception(f"Failed to parse analysis result: {str(e)}")
    except ValueError as e:
        logger.error(f"Invalid reference ad path: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Failed to analyze reference ad: {str(e)}")
        raise Exception(f"Failed to analyze reference ad: {str(e)}")


@ad_creation_agent.tool(
    metadata={
        'category': 'Analysis',
        'platform': 'Facebook',
        'rate_limit': '5/minute',
        'use_cases': [
            'Select 5 diverse hooks from database using AI',
            'Ensure hook diversity across categories',
            'Adapt hooks to reference ad style'
        ],
        'examples': [
            'Select 5 diverse hooks for Wonder Paws ad campaign',
            'Choose hooks with different persuasive principles'
        ]
    }
)
async def select_hooks(
    ctx: RunContext[AgentDependencies],
    hooks: List[Dict],
    ad_analysis: Dict,
    count: int = 5
) -> List[Dict]:
    """
    Select diverse hooks using AI to maximize persuasive variety.

    This tool uses Gemini AI to select 5 hooks that:
    - Cover different persuasive categories (avoid repetition)
    - Have high impact scores
    - Match the reference ad style and tone
    - Provide maximum coverage of persuasive principles

    The AI adapts each hook's text to match the reference ad's style.

    Args:
        ctx: Run context with AgentDependencies
        hooks: List of hook dictionaries from database (with id, text,
            category, framework, impact_score, emotional_score)
        ad_analysis: Ad analysis dictionary with format_type, authenticity_markers
        count: Number of hooks to select (default: 5)

    Returns:
        List of selected hook dictionaries with adaptation:
        [
            {
                "hook_id": "uuid",
                "text": "Original hook text",
                "category": "skepticism_overcome",
                "framework": "Skepticism Overcome",
                "impact_score": 21,
                "reasoning": "Why this hook was selected...",
                "adapted_text": "Hook text adapted to reference ad style"
            },
            ...
        ]

    Raises:
        ValueError: If hooks list is empty or count invalid
        Exception: If Gemini AI selection fails
    """
    import json

    try:
        logger.info(f"Selecting {count} diverse hooks from {len(hooks)} candidates")

        # Validate inputs
        if not hooks:
            raise ValueError("hooks list cannot be empty")
        if count < 1 or count > 10:
            raise ValueError("count must be between 1 and 10")

        # Build selection prompt
        selection_prompt = f"""
        You are selecting hooks for Facebook ad variations.

        **Reference Ad Style:**
        - Format: {ad_analysis.get('format_type')}
        - Authenticity markers: {', '.join(ad_analysis.get('authenticity_markers', []))}

        **Available Hooks** ({len(hooks)} total):
        {json.dumps(hooks, indent=2)}

        **Task:** Select exactly {count} hooks that:
        1. Maximize diversity across persuasive categories
        2. Prioritize high impact scores (15-21 preferred)
        3. Avoid repetition of the same category
        4. Cover different persuasive principles

        For each selected hook:
        1. Provide reasoning for why it was chosen
        2. Adapt the text to match the reference ad style/tone
           - Maintain the core message
           - Match authenticity markers (e.g., casual tone, emojis, timestamps)

        Return JSON array with this structure:
        [
            {{
                "hook_id": "uuid from input",
                "text": "original text",
                "category": "category from input",
                "framework": "framework from input",
                "impact_score": score from input,
                "reasoning": "Brief explanation of why selected",
                "adapted_text": "Hook text adapted to reference ad style"
            }},
            ...
        ]
        """

        # Bug #20: Add retry logic for malformed JSON responses
        max_retries = 3
        last_error = None

        for attempt in range(max_retries):
            try:
                # Call Gemini AI
                selection_result = await ctx.deps.gemini.analyze_text(
                    text=selection_prompt,
                    prompt="Select diverse hooks with reasoning and adaptations. IMPORTANT: Return ONLY valid JSON array, no markdown fences."
                )

                # Strip markdown code fences if present (Bug #10 fix)
                result_text = selection_result.strip()
                if result_text.startswith("```"):
                    # Remove opening fence (e.g., "```json\n")
                    result_text = result_text.split("\n", 1)[1] if "\n" in result_text else result_text[3:]
                    # Remove closing fence (e.g., "\n```")
                    if result_text.endswith("```"):
                        result_text = result_text.rsplit("\n```", 1)[0]

                # Additional JSON cleaning
                result_text = result_text.strip()

                # Parse JSON response
                selected_hooks = json.loads(result_text)

                logger.info(f"Selected {len(selected_hooks)} hooks with categories: "
                           f"{[h.get('category') for h in selected_hooks]}")

                return selected_hooks

            except json.JSONDecodeError as e:
                last_error = e
                logger.warning(f"Attempt {attempt + 1}/{max_retries} - JSON parse error: {str(e)}")
                logger.warning(f"Problematic JSON (first 500 chars): {result_text[:500]}...")

                if attempt < max_retries - 1:
                    logger.info(f"Retrying with more explicit JSON instructions...")
                    # Add more explicit instruction for next attempt
                    selection_prompt += "\n\nIMPORTANT: Ensure all JSON strings are properly escaped, no trailing commas, and valid JSON syntax."
                    continue
                else:
                    # Final attempt failed
                    logger.error(f"All {max_retries} attempts failed. Last error: {str(e)}")
                    logger.error(f"Failed JSON text: {result_text}")
                    raise Exception(f"Failed to parse selection result after {max_retries} attempts: {str(e)}")
    except ValueError as e:
        logger.error(f"Invalid input: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Failed to select hooks: {str(e)}")
        raise Exception(f"Failed to select hooks: {str(e)}")


@ad_creation_agent.tool(
    metadata={
        'category': 'Analysis',
        'platform': 'Facebook',
        'rate_limit': '10/minute',
        'use_cases': [
            'Select best product images for ad generation',
            'Rank product images by quality and relevance',
            'Choose images matching reference ad format'
        ],
        'examples': [
            'Select product images for Wonder Paws bottle',
            'Choose best product images for ad'
        ]
    }
)
async def select_product_images(
    ctx: RunContext[AgentDependencies],
    product_image_paths: List[str],
    ad_analysis: Dict,
    count: int = 1
) -> List[str]:
    """
    Select best product images matching reference ad format.

    This tool selects the most appropriate product images based on:
    - Image quality and clarity
    - Compatibility with reference ad layout
    - Product visibility and presentation

    Args:
        ctx: Run context with AgentDependencies
        product_image_paths: List of storage paths to product images
        ad_analysis: Ad analysis dictionary with format_type, layout_structure
        count: Number of images to select (default: 1)

    Returns:
        List of selected storage paths (ordered by preference):
        ["products/{id}/main.png", ...]

    Raises:
        ValueError: If product_image_paths is empty or count invalid
    """
    try:
        logger.info(f"Selecting {count} product images from {len(product_image_paths)} candidates")

        # Validate inputs
        if not product_image_paths:
            raise ValueError("product_image_paths cannot be empty")
        if count < 1 or count > len(product_image_paths):
            raise ValueError(f"count must be between 1 and {len(product_image_paths)}")

        # For now, implement simple selection logic
        # In production, this could use Vision AI to rank images
        # Priority: main image first, then reference images
        selected_paths = []

        # Prefer main images first
        for path in product_image_paths:
            if "main" in path:
                selected_paths.append(path)
                if len(selected_paths) >= count:
                    break

        # Fill remaining slots with other images
        if len(selected_paths) < count:
            for path in product_image_paths:
                if path not in selected_paths:
                    selected_paths.append(path)
                    if len(selected_paths) >= count:
                        break

        logger.info(f"Selected images: {selected_paths}")
        return selected_paths

    except ValueError as e:
        logger.error(f"Invalid input: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Failed to select product images: {str(e)}")
        raise Exception(f"Failed to select product images: {str(e)}")


# Phase 6: Hook-to-Benefit Matching Helper Function
def match_benefit_to_hook(hook: Dict, benefits: List[str]) -> str:
    """
    Select the most relevant product benefit for a given hook.

    Strategy:
    1. Extract keywords from hook text and category
    2. Score each benefit by keyword overlap
    3. Return highest scoring benefit
    4. Fallback to first benefit if no match or empty list

    Example:
        Hook: "My dog went from limping to running in 2 weeks!"
        Category: "before_after"
        Keywords: ["limping", "running", "mobility", "movement", "pain"]

        Benefits:
            - "Supports hip & joint mobility" → HIGH SCORE (mobility match)
            - "Promotes shiny coat" → LOW SCORE (no match)

        Result: "Supports hip & joint mobility"
    """
    if not benefits:
        return ""

    if len(benefits) == 1:
        return benefits[0]

    # Extract hook keywords (text + category)
    hook_text = str(hook.get('adapted_text', '') or hook.get('text', '')).lower()
    hook_category = str(hook.get('category', '')).lower()

    # Common keyword associations for different hook categories
    category_keywords = {
        'before_after': ['transform', 'change', 'improve', 'better', 'result', 'difference'],
        'social_proof': ['trust', 'proven', 'recommend', 'love', 'works', 'effective'],
        'authority': ['expert', 'professional', 'quality', 'premium', 'science', 'research'],
        'scarcity': ['limited', 'exclusive', 'special', 'unique', 'rare'],
        'urgency': ['now', 'today', 'fast', 'quick', 'immediate', 'soon'],
        'pain_point': ['problem', 'issue', 'struggle', 'pain', 'suffering', 'discomfort'],
        'aspiration': ['goal', 'dream', 'want', 'desire', 'wish', 'achieve']
    }

    # Combine hook text words and category keywords
    hook_words = set(hook_text.split())
    if hook_category in category_keywords:
        hook_words.update(category_keywords[hook_category])

    # Score each benefit
    best_benefit = benefits[0]
    best_score = 0

    for benefit in benefits:
        benefit_lower = benefit.lower()
        benefit_words = set(benefit_lower.split())

        # Calculate overlap score
        overlap = len(hook_words & benefit_words)

        # Bonus points for partial word matches (e.g., "mobility" contains "mobile")
        partial_matches = sum(
            1 for hook_word in hook_words
            for benefit_word in benefit_words
            if len(hook_word) > 3 and len(benefit_word) > 3 and
            (hook_word in benefit_word or benefit_word in hook_word)
        )

        score = overlap + (partial_matches * 0.5)

        if score > best_score:
            best_score = score
            best_benefit = benefit

    return best_benefit


@ad_creation_agent.tool(
    metadata={
        'category': 'Generation',
        'platform': 'Facebook',
        'rate_limit': '10/minute',
        'use_cases': [
            'Generate Nano Banana prompt for image generation',
            'Construct detailed prompt with specifications',
            'Combine hook, product, and reference ad into prompt'
        ],
        'examples': [
            'Generate prompt for Wonder Paws ad variation 1',
            'Create Nano Banana prompt with hook and product'
        ]
    }
)
async def generate_nano_banana_prompt(
    ctx: RunContext[AgentDependencies],
    prompt_index: int,
    selected_hook: Dict,
    product: Dict,
    ad_analysis: Dict,
    ad_brief_instructions: str,
    reference_ad_path: str,
    product_image_path: str
) -> Dict:
    """
    Generate Nano Banana Pro 3 prompt for ad image generation.

    This tool constructs a detailed prompt that combines:
    - Reference ad analysis (format, layout, colors)
    - Selected hook (adapted text)
    - Product information (benefits, target audience)
    - Ad brief instructions (brand guidelines)
    - Technical specifications (canvas size, image paths)

    Args:
        ctx: Run context with AgentDependencies
        prompt_index: Index 1-5 for this variation
        selected_hook: Selected hook dictionary with adapted_text
        product: Product dictionary with name, benefits
        ad_analysis: Ad analysis dictionary with all format details
        ad_brief_instructions: Instructions from ad brief template
        reference_ad_path: Storage path to reference ad
        product_image_path: Storage path to product image

    Returns:
        Dictionary with Nano Banana prompt:
        {
            "prompt_index": 1,
            "hook": {...selected_hook...},
            "instruction_text": "Human-readable instructions",
            "spec": {
                "canvas": "1080x1080px, background #F5F0E8",
                "bottle": "Use uploaded bottle EXACTLY...",
                "text_elements": {...}
            },
            "full_prompt": "Complete prompt text...",
            "template_reference_path": "reference-ads/...",
            "product_image_path": "products/..."
        }

    Raises:
        ValueError: If required parameters are missing
    """
    try:
        logger.info(f"Generating Nano Banana prompt for variation {prompt_index}")

        # Validate inputs
        if prompt_index < 1 or prompt_index > 5:
            raise ValueError("prompt_index must be between 1 and 5")

        # Phase 6: Match benefit to hook for relevant subheadline
        matched_benefit = match_benefit_to_hook(selected_hook, product.get('benefits', []))

        # Build specification object
        spec = {
            "canvas": f"{ad_analysis.get('canvas_size', '1080x1080px')}, "
                     f"background {ad_analysis.get('color_palette', ['#F5F0E8'])[0]}",
            "product_image": "Use uploaded product image EXACTLY - no modifications to product appearance",
            "text_elements": {
                "headline": selected_hook.get('adapted_text'),
                "subheadline": matched_benefit,  # Phase 6: Use matched benefit instead of first benefit
                "layout": ad_analysis.get('text_placement', {})
            },
            "colors": ad_analysis.get('color_palette', []),
            "authenticity_markers": ad_analysis.get('authenticity_markers', [])
        }

        # Phase 6: Build offer and constraints sections
        offer_section = ""
        if product.get('current_offer'):
            offer_section = f"""
        **Current Offer (USE EXACTLY AS WRITTEN):**
        "{product.get('current_offer')}"
        """

        prohibited_section = ""
        if product.get('prohibited_claims'):
            prohibited_section = f"""
        **PROHIBITED CLAIMS (DO NOT USE):**
        {', '.join(product.get('prohibited_claims', []))}
        """

        brand_voice_section = ""
        if product.get('brand_voice_notes'):
            brand_voice_section = f"""
        **Brand Voice & Tone:**
        {product.get('brand_voice_notes')}
        """

        usp_section = ""
        if product.get('unique_selling_points'):
            usp_section = f"""
        **Unique Selling Points:**
        {', '.join(product.get('unique_selling_points', []))}
        """

        disclaimer_section = ""
        if product.get('required_disclaimers'):
            disclaimer_section = f"""
        **Required Disclaimer (MUST INCLUDE):**
        {product.get('required_disclaimers')}
        """

        # Build instruction text
        instruction_text = f"""
        Create Facebook ad variation {prompt_index} for {product.get('name')}.

        **Style Guide:**
        - Format: {ad_analysis.get('format_type')}
        - Layout: {ad_analysis.get('layout_structure')}
        - Colors: {', '.join(ad_analysis.get('color_palette', []))}
        - Authenticity: {', '.join(ad_analysis.get('authenticity_markers', []))}

        **Hook (Main Headline):**
        "{selected_hook.get('adapted_text')}"

        **Product:**
        - Name: {product.get('name')}
        - Primary Benefit (matched to hook): {matched_benefit}
        - Target: {product.get('target_audience', 'general audience')}
        {offer_section}{usp_section}{brand_voice_section}{prohibited_section}{disclaimer_section}
        **Critical Requirements:**
        - Use product image EXACTLY as provided (no hallucination)
        - Match reference ad layout and style
        - Maintain brand voice from ad brief
        - If offer is provided, use EXACT wording (no hallucination of discounts)
        - Do NOT use any prohibited claims listed above
        """

        # Build full prompt
        full_prompt = f"""
        {ad_brief_instructions}

        {instruction_text}

        **Technical Specifications:**
        {spec}

        **Reference Images:**
        - Template: {reference_ad_path}
        - Product: {product_image_path}

        {ad_analysis.get('detailed_description', '')}
        """

        prompt_dict = {
            "prompt_index": prompt_index,
            "hook": selected_hook,
            "instruction_text": instruction_text,
            "spec": spec,
            "full_prompt": full_prompt,
            "template_reference_path": reference_ad_path,
            "product_image_path": product_image_path
        }

        logger.info(f"Generated prompt for variation {prompt_index}")
        return prompt_dict

    except ValueError as e:
        logger.error(f"Invalid input: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Failed to generate Nano Banana prompt: {str(e)}")
        raise Exception(f"Failed to generate prompt: {str(e)}")


@ad_creation_agent.tool(
    metadata={
        'category': 'Generation',
        'platform': 'Facebook',
        'rate_limit': '2/minute',
        'use_cases': [
            'Generate ad image using Gemini Nano Banana Pro 3',
            'Execute image generation with prompt',
            'Create ad variation from prompt'
        ],
        'examples': [
            'Generate ad image for variation 1',
            'Execute Nano Banana image generation'
        ]
    }
)
async def execute_nano_banana(
    ctx: RunContext[AgentDependencies],
    nano_banana_prompt: Dict
) -> Dict:
    """
    Execute Gemini Nano Banana Pro 3 image generation.

    This tool calls the Gemini Nano Banana API to generate the ad image
    based on the constructed prompt. Images are generated ONE AT A TIME
    (not batched) for resilience.

    Args:
        ctx: Run context with AgentDependencies
        nano_banana_prompt: Prompt dictionary from generate_nano_banana_prompt

    Returns:
        Dictionary with generated ad:
        {
            "prompt_index": 1,
            "image_base64": "base64-encoded-image-data",
            "storage_path": null  # Set by save_generated_ad tool
        }

    Raises:
        Exception: If image generation fails
    """
    try:
        prompt_index = nano_banana_prompt.get('prompt_index')
        logger.info(f"Executing Nano Banana generation for variation {prompt_index}")

        # Download reference images
        template_data = await ctx.deps.ad_creation.download_image(
            nano_banana_prompt['template_reference_path']
        )
        product_data = await ctx.deps.ad_creation.download_image(
            nano_banana_prompt['product_image_path']
        )

        # Call Gemini Nano Banana API
        # Note: Actual implementation depends on Gemini service interface
        image_base64 = await ctx.deps.gemini.generate_image(
            prompt=nano_banana_prompt['full_prompt'],
            reference_images=[template_data, product_data]
        )

        generated_ad = {
            "prompt_index": prompt_index,
            "image_base64": image_base64,
            "storage_path": None  # Will be set by save_generated_ad
        }

        logger.info(f"Generated ad image for variation {prompt_index}")
        return generated_ad

    except Exception as e:
        logger.error(f"Failed to execute Nano Banana generation: {str(e)}")
        raise Exception(f"Failed to generate image: {str(e)}")


@ad_creation_agent.tool(
    metadata={
        'category': 'Generation',
        'platform': 'Facebook',
        'rate_limit': '10/minute',
        'use_cases': [
            'Save generated ad to Supabase Storage',
            'Store ad metadata in database',
            'Record generation details for tracking'
        ],
        'examples': [
            'Save generated ad for variation 1',
            'Store ad image and metadata'
        ]
    }
)
async def save_generated_ad(
    ctx: RunContext[AgentDependencies],
    ad_run_id: str,
    generated_ad: Dict,
    nano_banana_prompt: Dict,
    hook: Dict
) -> str:
    """
    Save generated ad image to storage and database.

    This tool:
    1. Uploads generated image to Supabase Storage
    2. Saves metadata to generated_ads table
    3. Returns storage path for future reference

    Each ad is saved IMMEDIATELY after generation (not batched).

    Args:
        ctx: Run context with AgentDependencies
        ad_run_id: UUID of ad run as string
        generated_ad: Generated ad dictionary with image_base64
        nano_banana_prompt: Prompt dictionary used for generation
        hook: Hook dictionary with id and text

    Returns:
        Storage path string: "generated-ads/{ad_run_id}/{prompt_index}.png"

    Raises:
        ValueError: If image_base64 is missing
        Exception: If save operation fails
    """
    try:
        from uuid import UUID

        prompt_index = generated_ad['prompt_index']
        logger.info(f"Saving generated ad {prompt_index} for run {ad_run_id}")

        # Validate inputs
        if not generated_ad.get('image_base64'):
            raise ValueError("image_base64 is required")

        # Convert string to UUID
        ad_run_uuid = UUID(ad_run_id)
        hook_uuid = UUID(hook['hook_id'])

        # Upload to storage
        storage_path = await ctx.deps.ad_creation.upload_generated_ad(
            ad_run_id=ad_run_uuid,
            prompt_index=prompt_index,
            image_base64=generated_ad['image_base64']
        )

        # Save to database
        generated_ad_id = await ctx.deps.ad_creation.save_generated_ad(
            ad_run_id=ad_run_uuid,
            prompt_index=prompt_index,
            prompt_text=nano_banana_prompt['full_prompt'],
            prompt_spec=nano_banana_prompt['spec'],
            hook_id=hook_uuid,
            hook_text=hook['adapted_text'],
            storage_path=storage_path,
            final_status="pending"  # Will be updated after reviews
        )

        logger.info(f"Saved generated ad {prompt_index}: {storage_path}")
        return storage_path

    except ValueError as e:
        logger.error(f"Invalid input: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Failed to save generated ad: {str(e)}")
        raise Exception(f"Failed to save ad: {str(e)}")


# ============================================================================
# REVIEW & ORCHESTRATION TOOLS (11-14)
# ============================================================================

@ad_creation_agent.tool(
    metadata={
        'category': 'Analysis',
        'platform': 'Facebook',
        'rate_limit': '5/minute',
        'use_cases': [
            'Review generated ad using Claude Vision API',
            'Check product image accuracy and fidelity',
            'Validate text readability and layout adherence'
        ],
        'examples': [
            'Review generated ad variation 1',
            'Check ad quality with Claude vision'
        ]
    }
)
async def review_ad_claude(
    ctx: RunContext[AgentDependencies],
    storage_path: str,
    product_name: str,
    hook_text: str,
    ad_analysis: Dict
) -> Dict:
    """
    Review generated ad using Claude Vision API.

    This tool downloads the generated ad image and uses Claude's vision
    capabilities to analyze:
    - Product accuracy: Is the product reproduced correctly?
    - Text accuracy: Is text readable and correct?
    - Layout accuracy: Does it match the reference ad format?
    - Overall quality: Is it production-ready?

    Minimum threshold: 0.8 for product/text accuracy to approve.

    Args:
        ctx: Run context with AgentDependencies
        storage_path: Storage path to generated ad image
        product_name: Name of product for context
        hook_text: Hook text used in ad
        ad_analysis: Ad analysis dictionary with format details

    Returns:
        Dictionary with ReviewResult structure:
        {
            "reviewer": "claude",
            "product_accuracy": 0.0-1.0,
            "text_accuracy": 0.0-1.0,
            "layout_accuracy": 0.0-1.0,
            "overall_quality": 0.0-1.0,
            "product_issues": ["issue1", ...],
            "text_issues": ["issue1", ...],
            "ai_artifacts": ["artifact1", ...],
            "status": "approved" | "needs_revision" | "rejected",
            "notes": "Review notes..."
        }

    Raises:
        ValueError: If storage_path is invalid
        Exception: If Claude Vision API fails
    """
    # Import json at function scope (Bug #18 fix)
    import json

    try:
        logger.info(f"Claude reviewing ad: {storage_path}")

        # Validate input
        if not storage_path:
            raise ValueError("storage_path cannot be empty")

        # Download ad image
        image_data = await ctx.deps.ad_creation.download_image(storage_path)

        # Build review prompt
        review_prompt = f"""
        You are reviewing a generated Facebook ad image for production readiness.

        **Context:**
        - Product: {product_name}
        - Hook/Headline: "{hook_text}"
        - Expected Format: {ad_analysis.get('format_type')}
        - Expected Layout: {ad_analysis.get('layout_structure')}

        **Review Criteria:**

        1. **Product Accuracy** (0.0-1.0 score):
           - Is the product image reproduced EXACTLY as provided?
           - No hallucinations or modifications to product appearance?
           - Product visible and clearly identifiable?
           - Score 1.0 = perfect reproduction, 0.0 = completely wrong

        2. **Text Accuracy** (0.0-1.0 score):
           - Is all text readable and correct?
           - No gibberish, misspellings, or garbled text?
           - Hook text matches what was requested?
           - Score 1.0 = all text perfect, 0.0 = unreadable

        3. **Layout Accuracy** (0.0-1.0 score):
           - Does layout match reference ad format?
           - Elements positioned correctly?
           - Colors and spacing appropriate?
           - Score 1.0 = matches reference, 0.0 = completely different

        4. **Overall Quality** (0.0-1.0 score):
           - Production-ready quality?
           - No AI artifacts (distortions, glitches)?
           - Professional appearance?
           - Score 1.0 = ready to publish, 0.0 = not usable

        **Approval Logic:**
        - APPROVED: product_accuracy >= 0.8 AND text_accuracy >= 0.8
        - NEEDS_REVISION: One score between 0.5-0.79
        - REJECTED: Any score < 0.5

        Return JSON with this structure:
        {{
            "reviewer": "claude",
            "product_accuracy": 0.0-1.0,
            "text_accuracy": 0.0-1.0,
            "layout_accuracy": 0.0-1.0,
            "overall_quality": 0.0-1.0,
            "product_issues": ["list of specific issues with product image"],
            "text_issues": ["list of text problems found"],
            "ai_artifacts": ["list of AI generation artifacts detected"],
            "status": "approved" | "needs_revision" | "rejected",
            "notes": "Brief summary of review findings"
        }}
        """

        # Call Claude Vision API via Anthropic client
        # Note: We use the Anthropic API directly for vision review
        from anthropic import Anthropic
        import base64

        anthropic_client = Anthropic()

        # Detect actual image format from magic bytes (Bug #12 fix)
        media_type = "image/png"  # Default fallback
        if image_data[:4] == b'RIFF' and image_data[8:12] == b'WEBP':
            media_type = "image/webp"
        elif image_data[:3] == b'\xff\xd8\xff':
            media_type = "image/jpeg"
        elif image_data[:8] == b'\x89PNG\r\n\x1a\n':
            media_type = "image/png"
        elif image_data[:6] in (b'GIF87a', b'GIF89a'):
            media_type = "image/gif"

        # Encode image as base64
        image_base64 = base64.b64encode(image_data).decode('utf-8')

        # Call Claude with vision
        message = anthropic_client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=2000,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_base64
                        }
                    },
                    {
                        "type": "text",
                        "text": review_prompt
                    }
                ]
            }]
        )

        # Parse response
        review_text = message.content[0].text

        # Strip markdown code fences if present (Bug #13 fix)
        # Claude sometimes wraps JSON in ```json ... ```
        review_text_clean = review_text.strip()
        if review_text_clean.startswith('```'):
            # Remove opening fence (```json or ```)
            lines = review_text_clean.split('\n')
            if lines[0].startswith('```'):
                lines = lines[1:]
            # Remove closing fence
            if lines and lines[-1].strip() == '```':
                lines = lines[:-1]
            review_text_clean = '\n'.join(lines)

        review_dict = json.loads(review_text_clean)

        logger.info(f"Claude review complete: status={review_dict.get('status')}, "
                   f"product_acc={review_dict.get('product_accuracy')}, "
                   f"text_acc={review_dict.get('text_accuracy')}")

        return review_dict

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Claude review response: {str(e)}")
        raise Exception(f"Failed to parse review result: {str(e)}")
    except ValueError as e:
        logger.error(f"Invalid storage path: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Failed to review ad with Claude: {str(e)}")
        raise Exception(f"Failed to review ad: {str(e)}")


@ad_creation_agent.tool(
    metadata={
        'category': 'Analysis',
        'platform': 'Facebook',
        'rate_limit': '5/minute',
        'use_cases': [
            'Review generated ad using Gemini Vision API',
            'Provide second opinion for dual review system',
            'Cross-validate Claude review results'
        ],
        'examples': [
            'Review generated ad variation 1 with Gemini',
            'Get Gemini vision review for ad quality'
        ]
    }
)
async def review_ad_gemini(
    ctx: RunContext[AgentDependencies],
    storage_path: str,
    product_name: str,
    hook_text: str,
    ad_analysis: Dict
) -> Dict:
    """
    Review generated ad using Gemini Vision API.

    This tool provides a second review opinion using Gemini's vision
    capabilities. Combined with Claude review, it enables:
    - Dual review system with OR logic (either approves = approved)
    - Flagging disagreements for human review
    - Cross-validation of quality scores

    Same scoring criteria as Claude review:
    - Product accuracy, text accuracy, layout accuracy, overall quality
    - Minimum threshold: 0.8 for product/text accuracy to approve

    Args:
        ctx: Run context with AgentDependencies
        storage_path: Storage path to generated ad image
        product_name: Name of product for context
        hook_text: Hook text used in ad
        ad_analysis: Ad analysis dictionary with format details

    Returns:
        Dictionary with ReviewResult structure:
        {
            "reviewer": "gemini",
            "product_accuracy": 0.0-1.0,
            "text_accuracy": 0.0-1.0,
            "layout_accuracy": 0.0-1.0,
            "overall_quality": 0.0-1.0,
            "product_issues": ["issue1", ...],
            "text_issues": ["issue1", ...],
            "ai_artifacts": ["artifact1", ...],
            "status": "approved" | "needs_revision" | "rejected",
            "notes": "Review notes..."
        }

    Raises:
        ValueError: If storage_path is invalid
        Exception: If Gemini Vision API fails
    """
    try:
        logger.info(f"Gemini reviewing ad: {storage_path}")

        # Validate input
        if not storage_path:
            raise ValueError("storage_path cannot be empty")

        # Download ad image
        image_data = await ctx.deps.ad_creation.download_image(storage_path)

        # Build review prompt (same criteria as Claude)
        import json
        review_prompt = f"""
        You are reviewing a generated Facebook ad image for production readiness.

        **Context:**
        - Product: {product_name}
        - Hook/Headline: "{hook_text}"
        - Expected Format: {ad_analysis.get('format_type')}
        - Expected Layout: {ad_analysis.get('layout_structure')}

        **Review Criteria:**

        1. **Product Accuracy** (0.0-1.0 score):
           - Is the product image reproduced EXACTLY as provided?
           - No hallucinations or modifications to product appearance?
           - Product visible and clearly identifiable?
           - Score 1.0 = perfect reproduction, 0.0 = completely wrong

        2. **Text Accuracy** (0.0-1.0 score):
           - Is all text readable and correct?
           - No gibberish, misspellings, or garbled text?
           - Hook text matches what was requested?
           - Score 1.0 = all text perfect, 0.0 = unreadable

        3. **Layout Accuracy** (0.0-1.0 score):
           - Does layout match reference ad format?
           - Elements positioned correctly?
           - Colors and spacing appropriate?
           - Score 1.0 = matches reference, 0.0 = completely different

        4. **Overall Quality** (0.0-1.0 score):
           - Production-ready quality?
           - No AI artifacts (distortions, glitches)?
           - Professional appearance?
           - Score 1.0 = ready to publish, 0.0 = not usable

        **Approval Logic:**
        - APPROVED: product_accuracy >= 0.8 AND text_accuracy >= 0.8
        - NEEDS_REVISION: One score between 0.5-0.79
        - REJECTED: Any score < 0.5

        Return JSON with this structure:
        {{
            "reviewer": "gemini",
            "product_accuracy": 0.0-1.0,
            "text_accuracy": 0.0-1.0,
            "layout_accuracy": 0.0-1.0,
            "overall_quality": 0.0-1.0,
            "product_issues": ["list of specific issues with product image"],
            "text_issues": ["list of text problems found"],
            "ai_artifacts": ["list of AI generation artifacts detected"],
            "status": "approved" | "needs_revision" | "rejected",
            "notes": "Brief summary of review findings"
        }}
        """

        # Call Gemini Vision API via service
        review_result = await ctx.deps.gemini.review_image(
            image_data=image_data,
            prompt=review_prompt
        )

        # Strip markdown code fences if present (Bug #15 fix)
        # Gemini sometimes wraps JSON in ```json ... ```
        review_text_clean = review_result.strip()
        if review_text_clean.startswith('```'):
            # Remove opening fence (```json or ```)
            lines = review_text_clean.split('\n')
            if lines[0].startswith('```'):
                lines = lines[1:]
            # Remove closing fence
            if lines and lines[-1].strip() == '```':
                lines = lines[:-1]
            review_text_clean = '\n'.join(lines)

        # Parse JSON response
        review_dict = json.loads(review_text_clean)

        logger.info(f"Gemini review complete: status={review_dict.get('status')}, "
                   f"product_acc={review_dict.get('product_accuracy')}, "
                   f"text_acc={review_dict.get('text_accuracy')}")

        return review_dict

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Gemini review response: {str(e)}")
        raise Exception(f"Failed to parse review result: {str(e)}")
    except ValueError as e:
        logger.error(f"Invalid storage path: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Failed to review ad with Gemini: {str(e)}")
        raise Exception(f"Failed to review ad: {str(e)}")


@ad_creation_agent.tool(
    metadata={
        'category': 'Generation',
        'platform': 'Facebook',
        'rate_limit': '10/minute',
        'use_cases': [
            'Initialize ad run workflow in database',
            'Create database record for tracking ad generation',
            'Set up ad run with reference ad path and product'
        ],
        'examples': [
            'Create ad run for product abc123',
            'Initialize ad generation workflow'
        ]
    }
)
async def create_ad_run(
    ctx: RunContext[AgentDependencies],
    product_id: str,
    reference_ad_storage_path: str,
    project_id: Optional[str] = None
) -> str:
    """
    Create new ad run record in database to track workflow.

    This tool initializes the ad creation workflow by:
    1. Creating a record in the ad_runs table
    2. Linking to product and reference ad
    3. Setting initial status to "pending"
    4. Returning ad_run_id for subsequent operations

    Args:
        ctx: Run context with AgentDependencies
        product_id: UUID of product as string
        reference_ad_storage_path: Storage path to uploaded reference ad
        project_id: Optional UUID of project as string

    Returns:
        ad_run_id as string (UUID format)

    Raises:
        ValueError: If product_id or reference_ad_storage_path is invalid
        Exception: If database insert fails
    """
    try:
        logger.info(f"Creating ad run for product: {product_id}")

        # Validate inputs
        if not product_id:
            raise ValueError("product_id cannot be empty")
        if not reference_ad_storage_path:
            raise ValueError("reference_ad_storage_path cannot be empty")

        # Convert strings to UUIDs
        product_uuid = UUID(product_id)
        project_uuid = UUID(project_id) if project_id else None

        # Create ad run via service
        ad_run_id = await ctx.deps.ad_creation.create_ad_run(
            product_id=product_uuid,
            reference_ad_storage_path=reference_ad_storage_path,
            project_id=project_uuid
        )

        logger.info(f"Ad run created: {ad_run_id}")
        return str(ad_run_id)

    except ValueError as e:
        logger.error(f"Invalid input: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Failed to create ad run: {str(e)}")
        raise Exception(f"Failed to create ad run: {str(e)}")


@ad_creation_agent.tool(
    metadata={
        'category': 'Generation',
        'platform': 'Facebook',
        'rate_limit': '1/minute',
        'use_cases': [
            'Execute complete ad creation workflow end-to-end',
            'Orchestrate all 13 tools in sequence',
            'Generate 5 ad variations with dual AI review'
        ],
        'examples': [
            'Create complete ad campaign for Wonder Paws',
            'Generate 5 Facebook ads with full workflow'
        ]
    }
)
async def complete_ad_workflow(
    ctx: RunContext[AgentDependencies],
    product_id: str,
    reference_ad_base64: str,
    reference_ad_filename: str = "reference.png",
    project_id: Optional[str] = None
) -> Dict:
    """
    Execute complete ad creation workflow from start to finish.

    This orchestration tool:
    1. Creates ad run in database
    2. Uploads reference ad to storage
    3. Fetches product data and hooks
    4. Analyzes reference ad (Vision AI)
    5. Selects 5 diverse hooks
    6. Generates 5 ad variations (ONE AT A TIME)
    7. Dual AI review (Claude + Gemini) for each ad
    8. Applies OR logic: either reviewer approving = approved
    9. Returns complete AdCreationResult

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

    Returns:
        Dictionary with AdCreationResult structure:
        {
            "ad_run_id": "uuid",
            "product": {...},
            "reference_ad_path": "storage path",
            "ad_analysis": {...},
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
    """
    try:
        from datetime import datetime
        from uuid import UUID
        import json

        logger.info(f"=== STARTING COMPLETE AD WORKFLOW for product {product_id} ===")

        # STAGE 1: Initialize ad run and upload reference ad
        logger.info("Stage 1: Creating ad run...")

        # Create temporary ad run to get ID (we'll update status later)
        ad_run_id_str = await create_ad_run(
            ctx=ctx,
            product_id=product_id,
            reference_ad_storage_path="temp",  # Will update after upload
            project_id=project_id
        )

        # Upload reference ad
        reference_ad_path = await upload_reference_ad(
            ctx=ctx,
            ad_run_id=ad_run_id_str,
            image_base64=reference_ad_base64,
            filename=reference_ad_filename
        )

        # Update ad run with correct reference path
        await ctx.deps.ad_creation.update_ad_run(
            ad_run_id=UUID(ad_run_id_str),
            status="analyzing"
        )

        logger.info(f"Ad run created: {ad_run_id_str}")

        # STAGE 2: Fetch product data
        logger.info("Stage 2: Fetching product data...")
        product_dict = await get_product_with_images(ctx=ctx, product_id=product_id)

        # STAGE 3: Fetch hooks
        logger.info("Stage 3: Fetching hooks...")
        hooks_list = await get_hooks_for_product(
            ctx=ctx,
            product_id=product_id,
            limit=50,
            active_only=True
        )

        # STAGE 4: Get ad brief template
        logger.info("Stage 4: Fetching ad brief template...")
        ad_brief_dict = await get_ad_brief_template(
            ctx=ctx,
            brand_id=product_dict.get('brand_id')
        )
        ad_brief_instructions = ad_brief_dict.get('instructions', '')

        # STAGE 5: Analyze reference ad
        logger.info("Stage 5: Analyzing reference ad with Vision AI...")
        ad_analysis = await analyze_reference_ad(
            ctx=ctx,
            reference_ad_storage_path=reference_ad_path
        )

        # Save analysis to database
        await ctx.deps.ad_creation.update_ad_run(
            ad_run_id=UUID(ad_run_id_str),
            ad_analysis=ad_analysis
        )

        # STAGE 6: Select 5 diverse hooks
        logger.info("Stage 6: Selecting 5 diverse hooks with AI...")
        selected_hooks = await select_hooks(
            ctx=ctx,
            hooks=hooks_list,
            ad_analysis=ad_analysis,
            count=5
        )

        # Save selected hooks to database
        await ctx.deps.ad_creation.update_ad_run(
            ad_run_id=UUID(ad_run_id_str),
            selected_hooks=selected_hooks
        )

        # STAGE 7: Select product images
        logger.info("Stage 7: Selecting product images...")
        product_image_paths = [product_dict.get('main_image_storage_path')] + \
                              product_dict.get('reference_image_storage_paths', [])
        product_image_paths = [p for p in product_image_paths if p]  # Remove None values

        selected_product_images = await select_product_images(
            ctx=ctx,
            product_image_paths=product_image_paths,
            ad_analysis=ad_analysis,
            count=1
        )

        product_image_path = selected_product_images[0]

        # Update status
        await ctx.deps.ad_creation.update_ad_run(
            ad_run_id=UUID(ad_run_id_str),
            status="generating"
        )

        # STAGE 8-10: Generate 5 ad variations (ONE AT A TIME)
        logger.info("Stage 8-10: Generating 5 ad variations...")
        generated_ads_with_reviews = []

        for i, selected_hook in enumerate(selected_hooks, start=1):
            logger.info(f"  → Generating variation {i}/5...")

            # Generate prompt
            nano_banana_prompt = await generate_nano_banana_prompt(
                ctx=ctx,
                prompt_index=i,
                selected_hook=selected_hook,
                product=product_dict,
                ad_analysis=ad_analysis,
                ad_brief_instructions=ad_brief_instructions,
                reference_ad_path=reference_ad_path,
                product_image_path=product_image_path
            )

            # Execute generation
            generated_ad = await execute_nano_banana(
                ctx=ctx,
                nano_banana_prompt=nano_banana_prompt
            )

            # Upload image to storage to get path (Bug #17 fix)
            # Don't save to database yet - will save with reviews later
            storage_path = await ctx.deps.ad_creation.upload_generated_ad(
                ad_run_id=UUID(ad_run_id_str),
                prompt_index=i,
                image_base64=generated_ad['image_base64']
            )

            logger.info(f"  ✓ Variation {i} generated and uploaded: {storage_path}")

            # STAGE 11-12: Dual AI Review
            logger.info(f"  → Reviewing variation {i} with Claude + Gemini...")

            # Claude review
            claude_review = await review_ad_claude(
                ctx=ctx,
                storage_path=storage_path,
                product_name=product_dict.get('name'),
                hook_text=selected_hook.get('adapted_text'),
                ad_analysis=ad_analysis
            )

            # Gemini review
            gemini_review = await review_ad_gemini(
                ctx=ctx,
                storage_path=storage_path,
                product_name=product_dict.get('name'),
                hook_text=selected_hook.get('adapted_text'),
                ad_analysis=ad_analysis
            )

            # CRITICAL: Dual review logic with OR logic
            claude_approved = claude_review.get('status') == 'approved'
            gemini_approved = gemini_review.get('status') == 'approved'

            # OR logic: either approving = approved
            if claude_approved or gemini_approved:
                final_status = 'approved'
            elif not claude_approved and not gemini_approved:
                final_status = 'rejected'  # Both rejected
            else:
                final_status = 'flagged'  # Disagreement

            # Check if reviewers agree
            reviewers_agree = (claude_approved == gemini_approved)

            logger.info(f"  ✓ Reviews complete: Claude={claude_review.get('status')}, "
                       f"Gemini={gemini_review.get('status')}, Final={final_status}")

            # Update database with reviews
            await ctx.deps.ad_creation.save_generated_ad(
                ad_run_id=UUID(ad_run_id_str),
                prompt_index=i,
                prompt_text=nano_banana_prompt['full_prompt'],
                prompt_spec=nano_banana_prompt['spec'],
                hook_id=UUID(selected_hook['hook_id']),
                hook_text=selected_hook['adapted_text'],
                storage_path=storage_path,
                claude_review=claude_review,
                gemini_review=gemini_review,
                final_status=final_status
            )

            # Add to results
            generated_ads_with_reviews.append({
                "prompt_index": i,
                "prompt": nano_banana_prompt,
                "storage_path": storage_path,
                "claude_review": claude_review,
                "gemini_review": gemini_review,
                "reviewers_agree": reviewers_agree,
                "final_status": final_status
            })

        # STAGE 13: Compile results
        logger.info("Stage 13: Compiling final results...")

        # Count statuses
        approved_count = sum(1 for ad in generated_ads_with_reviews if ad['final_status'] == 'approved')
        rejected_count = sum(1 for ad in generated_ads_with_reviews if ad['final_status'] == 'rejected')
        flagged_count = sum(1 for ad in generated_ads_with_reviews if ad['final_status'] == 'flagged')

        # Build summary
        summary = f"""
Ad creation workflow completed for {product_dict.get('name')}.

**Results:**
- Total ads generated: 5
- Approved (production-ready): {approved_count}
- Rejected (both reviewers): {rejected_count}
- Flagged (reviewer disagreement): {flagged_count}

**Next Steps:**
{f"- {approved_count} ads ready for immediate use" if approved_count > 0 else ""}
{f"- {flagged_count} ads require human review" if flagged_count > 0 else ""}
{f"- {rejected_count} ads should be regenerated" if rejected_count > 0 else ""}
        """.strip()

        # Mark workflow complete
        await ctx.deps.ad_creation.update_ad_run(
            ad_run_id=UUID(ad_run_id_str),
            status="complete"
        )

        # Build final result
        result = {
            "ad_run_id": ad_run_id_str,
            "product": product_dict,
            "reference_ad_path": reference_ad_path,
            "ad_analysis": ad_analysis,
            "selected_hooks": selected_hooks,
            "generated_ads": generated_ads_with_reviews,
            "approved_count": approved_count,
            "rejected_count": rejected_count,
            "flagged_count": flagged_count,
            "summary": summary,
            "created_at": datetime.now().isoformat()
        }

        logger.info(f"=== WORKFLOW COMPLETE: {approved_count} approved, "
                   f"{rejected_count} rejected, {flagged_count} flagged ===")

        return result

    except Exception as e:
        logger.error(f"Workflow failed: {str(e)}")

        # Mark workflow as failed in database
        if 'ad_run_id_str' in locals():
            await ctx.deps.ad_creation.update_ad_run(
                ad_run_id=UUID(ad_run_id_str),
                status="failed",
                error_message=str(e)
            )

        raise Exception(f"Ad workflow failed: {str(e)}")


# ============================================================================
# Tool count and initialization
# ============================================================================

logger.info("Ad Creation Agent initialized with 14 tools (ALL PHASES COMPLETE)")
