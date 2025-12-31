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
from typing import List, Dict, Optional, Any
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

        8. **Social Proof Elements**: Does this ad include trust signals or social proof?
           Look for:
           - Statistical badges (e.g., "100,000+ Sold", "5-Star Rating", "#1 Best Seller")
           - Numerical claims displayed as graphics/badges
           - Award badges or certification marks
           - Customer count indicators
           - Sales volume displays

           Return:
           - "has_social_proof": true/false (whether social proof elements are present)
           - "social_proof_style": description of how social proof is displayed (e.g., "corner badge", "banner across top", "circular seal")
           - "social_proof_placement": where it's positioned (e.g., "top_right", "bottom_left", "center_top")

        9. **Founder/Personal Elements**: Does this ad include founder-related content?

           Look for TWO types:

           A) **Founder Signature** - A sign-off at the end:
              - Personal signatures (e.g., "Love, The Smith Family", "- John & Sarah")
              - Founder names at the bottom
              - Personal sign-offs (e.g., "From our family to yours", "With love,")
              - Handwritten-style signatures

           B) **Founder Mention** - References to founders in the body text:
              - First-person plural ("We created this...", "Our family...")
              - Founder story references ("As parents ourselves...")
              - Personal pronouns indicating the brand team speaking directly

           Return:
           - "has_founder_signature": true/false (sign-off at end)
           - "founder_signature_style": how signature appears (e.g., "handwritten at bottom", "names after dash") or null
           - "founder_signature_placement": position (e.g., "bottom_center") or null
           - "has_founder_mention": true/false (founders referenced in body text)
           - "founder_mention_style": how founders are mentioned (e.g., "first-person narrative", "founder story") or null

        10. **Canvas Size**: What are the dimensions? (e.g., 1080x1080px, 1200x628px)

        11. **Detailed Description**: Provide a comprehensive description of the ad
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
            "has_social_proof": boolean,
            "social_proof_style": "string or null",
            "social_proof_placement": "string or null",
            "has_founder_signature": boolean,
            "founder_signature_style": "string or null",
            "founder_signature_placement": "string or null",
            "has_founder_mention": boolean,
            "founder_mention_style": "string or null",
            "canvas_size": "WIDTHxHEIGHTpx",
            "detailed_description": "comprehensive description..."
        }
        """

        # Call Vision AI using Pydantic AI Agent
        from pydantic_ai import Agent
        import base64

        # Detect image format from base64 header or assume PNG
        media_type = "image/png"
        try:
            # Simple header check
            if image_base64.startswith('/9j/'):
                media_type = "image/jpeg"
            elif image_base64.startswith('iVBORw0KGgo'):
                 media_type = "image/png"
            elif image_base64.startswith('R0lGOD'):
                media_type = "image/gif"
            elif image_base64.startswith('UklGR'):
                media_type = "image/webp"
        except Exception:
            pass 

        # Create temporary agent for this specific vision task
        vision_agent = Agent(
            model=Config.get_model("vision"),
            system_prompt="You are a simplified vision analysis expert. Return ONLY valid JSON."
        )

        logger.info(f"Running vision analysis with model: {vision_agent.model}")

        # Construct Prompt content with Image
        # Note: Pydantic AI 0.0.18+ supports list of content parts including images
        # We need to construct the message properly based on how Pydantic AI expects it
        # For now, we'll try the standard run() with user_content list if supported, 
        # or separate system prompt instruction if image input is complex.
        # But `agent.run()` typically takes a string or list of messages.
        # Let's try passing the image as a BinaryContent or similar if the library supports it,
        # OR just rely on the model adapter if it handles image URLs/base64 in text.
        # 
        # Wait, Pydantic AI's `run` method usually takes `user_prompt` (str) or `message_history`.
        # To send an image, we usually need to use a model-specific structure OR 
        # the `BinaryContent` if using standard Pydantic models.
        # 
        # Let's look at how we were passing it to Anthropic: 
        # {"type": "image", "source": {"type": "base64", ...}}
        # 
        # Update: Pydantic AI recently added proper support for multi-modal via `BinaryContent`.
        # from pydantic_ai.messages import BinaryContent, ModelRequest, UserPromptPart
        
        from pydantic_ai.messages import BinaryContent
        
        # Decode base64 to bytes if it's a string, because BinaryContent takes bytes
        if isinstance(image_data, str):
             image_bytes = base64.b64decode(image_data)
        else:
             image_bytes = image_data
             
        # Run agent
        # We pass a list containing the image and the prompt
        # Note: If Pydantic AI version in env doesn't support list for `user_prompt`, 
        # we might need to use `deps` or a specific model approach. 
        # Assuming modern Pydantic AI:
        
        result = await vision_agent.run(
            [
                analysis_prompt + "\n\nReturn ONLY valid JSON, no other text.",
                BinaryContent(data=image_bytes, media_type=media_type)
            ]
        )
        
        analysis_result = result.output

        # Strip markdown code fences if present (Gemini/Claude sometimes wraps JSON in ```json...```)
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
    product_name: str = "",
    target_audience: str = "",
    count: int = 10,
    persona_data: Optional[Dict] = None
) -> List[Dict]:
    """
    Select diverse hooks using AI to maximize persuasive variety.

    This tool uses Claude Opus 4.5 to select hooks that:
    - Cover different persuasive categories (avoid repetition)
    - Have high impact scores
    - Match the reference ad style and tone
    - Provide maximum coverage of persuasive principles
    - Are clear, understandable, and mention product context
    - When persona_data is provided, prioritize hooks matching persona's emotional triggers

    The AI adapts each hook's text to match the reference ad's style and ensures
    the adapted text makes sense and mentions the product category.

    NOTE: Hooks are shuffled before sending to Claude to ensure variety across
    multiple runs. This prevents the same hooks from being selected repeatedly.

    Args:
        ctx: Run context with AgentDependencies
        hooks: List of hook dictionaries from database (with id, text,
            category, framework, impact_score, emotional_score)
        ad_analysis: Ad analysis dictionary with format_type, authenticity_markers
        product_name: Name of the product (for context)
        target_audience: Product's target audience (e.g., "pet owners", "dog owners")
        count: Number of hooks to select (default: 10)
        persona_data: Optional 4D persona data with pain_points, desires, their_language,
            objections, and amazon_testimonials for targeted hook selection

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
    import random

    try:
        logger.info(f"Selecting {count} diverse hooks from {len(hooks)} candidates")

        # Validate inputs
        if not hooks:
            raise ValueError("hooks list cannot be empty")
        if count < 1 or count > 15:
            raise ValueError("count must be between 1 and 15")

        # Shuffle hooks to ensure variety across runs
        # This prevents Gemini from always selecting the same hooks
        # when presented with the same ordered list
        shuffled_hooks = hooks.copy()
        random.shuffle(shuffled_hooks)
        logger.info(f"Shuffled {len(shuffled_hooks)} hooks for diversity")

        # Query knowledge base for copywriting best practices
        knowledge_context = ""
        if hasattr(ctx.deps, 'docs') and ctx.deps.docs is not None:
            try:
                # Search for relevant hook and copywriting knowledge
                knowledge_results = ctx.deps.docs.search(
                    f"hook writing techniques {target_audience} advertising",
                    limit=3,
                    tags=["hooks", "copywriting"]
                )
                if knowledge_results:
                    knowledge_sections = []
                    for r in knowledge_results:
                        knowledge_sections.append(f"### {r.title}\n{r.chunk_content}")
                    knowledge_context = "\n\n".join(knowledge_sections)
                    logger.info(f"Retrieved {len(knowledge_results)} knowledge base sections for hook selection")
            except Exception as e:
                logger.warning(f"Knowledge base query failed (continuing without): {e}")

        # Build selection prompt
        knowledge_section = ""
        if knowledge_context:
            knowledge_section = f"""
        **Copywriting Best Practices (from knowledge base):**
        {knowledge_context}

        Use these best practices to guide your hook selection and adaptation.
        """

        # Build persona section if persona_data is provided
        persona_section = ""
        if persona_data:
            persona_section = f"""
        **TARGET PERSONA: {persona_data.get('persona_name', 'Unknown')}**
        {persona_data.get('snapshot', '')}

        **Pain Points (prioritize hooks addressing these):**
        {json.dumps(persona_data.get('pain_points', [])[:5], indent=2)}

        **Desires (what they want to achieve):**
        {json.dumps(persona_data.get('desires', [])[:5], indent=2)}

        **Their Language (how they talk - adapt hooks to match):**
        {json.dumps(persona_data.get('their_language', [])[:3], indent=2)}

        **Objections to Address:**
        {json.dumps(persona_data.get('objections', [])[:3], indent=2)}

        **Amazon Testimonials (real customer voice - use similar language):**
        {json.dumps(persona_data.get('amazon_testimonials', {}), indent=2) if persona_data.get('amazon_testimonials') else 'None available'}

        IMPORTANT: Use this persona data to:
        1. Prioritize hooks that directly address the persona's pain points
        2. Adapt hook language to match how this persona talks (their_language)
        3. Select hooks that resonate with their emotional triggers
        4. Use phrases from Amazon testimonials when adapting hooks
        """

        selection_prompt = f"""
        You are selecting hooks for Facebook ad variations.

        **Product Context:**
        - Product: {product_name}
        - Target Audience: {target_audience}

        **Reference Ad Style:**
        - Format: {ad_analysis.get('format_type')}
        - Authenticity markers: {', '.join(ad_analysis.get('authenticity_markers', []))}
        {knowledge_section}
        {persona_section}

        **Available Hooks** ({len(shuffled_hooks)} total):
        {json.dumps(shuffled_hooks, indent=2)}

        **Task:** Select exactly {count} hooks that:
        1. Maximize diversity across persuasive categories
        2. Prioritize high impact scores (15-21 preferred)
        3. Avoid repetition of the same category
        4. Cover different persuasive principles

        For each selected hook:
        1. Provide reasoning for why it was chosen
        2. Adapt the text to match the reference ad style/tone AND ensure clarity:
           - Maintain the core message
           - Match authenticity markers (e.g., casual tone, emojis, timestamps)
           - **CRITICAL: Fix any typos, nonsense words, or unclear phrasing**
           - **CRITICAL: Ensure the adapted text mentions or implies the product category/target audience**
           - Example: If target audience is "dog owners" or "pet owners", the hook should mention "my dog", "my pet", or similar context
           - **CRITICAL: The adapted text must make sense on its own - someone reading it should understand what product category it's about**

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

        # Use configured creative model for hook selection and adaptation
        # Use Pydantic AI Agent
        from pydantic_ai import Agent
        from ...core.config import Config
        import asyncio

        # Create temporary agent
        hook_agent = Agent(
            model=Config.get_model("creative"),
            system_prompt="You are a persuasive copywriting expert. Return ONLY valid JSON."
        )

        for attempt in range(max_retries):
            try:
                # Run agent
                result = await hook_agent.run(
                    selection_prompt + "\n\nReturn ONLY valid JSON array, no markdown fences, no other text."
                )
                
                selection_result = result.output

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
                           f"{[h.get('category') for h in selected_hooks]} (model: {Config.get_model('creative')})")

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
    count: int = 1,
    selection_mode: str = "auto",
    image_analyses: Optional[Dict[str, Dict]] = None,
    manual_selection: Optional[List[str]] = None
) -> List[Dict]:
    """
    Select best product images matching reference ad format.

    Supports two modes:
    - auto: Uses stored image analysis to match against reference ad style
    - manual: Returns user-selected images with their analysis

    Args:
        ctx: Run context with AgentDependencies
        product_image_paths: List of storage paths to product images
        ad_analysis: Ad analysis dictionary with format_type, layout_structure
        count: Number of images to select (default: 1)
        selection_mode: "auto" for smart selection, "manual" for user choice
        image_analyses: Dict mapping storage_path -> ProductImageAnalysis dict
        manual_selection: List of paths if manual mode

    Returns:
        List of selection results with match scores:
        [
            {
                "storage_path": "products/xxx/main.png",
                "match_score": 0.85,
                "match_reasons": ["Good lighting match", "High quality"],
                "analysis": {...}
            }
        ]

    Raises:
        ValueError: If product_image_paths is empty or count invalid
    """
    try:
        logger.info(f"Selecting {count} product images ({selection_mode} mode)")

        # Validate inputs
        if not product_image_paths:
            raise ValueError("product_image_paths cannot be empty")
        if count < 1:
            raise ValueError("count must be at least 1")

        # Manual mode - return user selections
        if selection_mode == "manual" and manual_selection:
            results = []
            for path in manual_selection[:count]:
                analysis = (image_analyses or {}).get(path, {})
                results.append({
                    "storage_path": path,
                    "match_score": 1.0,  # User choice = perfect match
                    "match_reasons": ["User selected"],
                    "analysis": analysis
                })
            return results

        # Auto mode - score and rank images
        scored_images = []
        image_analyses = image_analyses or {}

        for path in product_image_paths:
            analysis = image_analyses.get(path, {})
            score, reasons = _calculate_image_match_score(analysis, ad_analysis)

            # Fallback bonus for "main" in path if no analysis
            if not analysis and "main" in path.lower():
                score = max(score, 0.6)
                reasons.append("Main product image (fallback)")

            scored_images.append({
                "storage_path": path,
                "match_score": score,
                "match_reasons": reasons,
                "analysis": analysis
            })

        # Sort by score descending
        scored_images.sort(key=lambda x: x["match_score"], reverse=True)

        # Return top N
        selected = scored_images[:count]
        logger.info(f"Selected {len(selected)} images. Top score: {selected[0]['match_score']:.2f}")

        return selected

    except ValueError as e:
        logger.error(f"Invalid input: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Failed to select product images: {str(e)}")
        raise Exception(f"Failed to select product images: {str(e)}")


def _calculate_image_match_score(image_analysis: Dict, ad_analysis: Dict) -> tuple:
    """
    Calculate how well a product image matches reference ad style.

    Returns (score, reasons) tuple.
    """
    if not image_analysis:
        return 0.5, ["No analysis available - using default score"]

    score = 0.0
    reasons = []

    # Quality score (20% weight)
    quality = image_analysis.get("quality_score", 0.5)
    score += quality * 0.2
    if quality >= 0.8:
        reasons.append(f"High quality ({quality:.2f})")

    # Background compatibility (25% weight)
    bg_type = image_analysis.get("background_type", "unknown")
    ref_format = ad_analysis.get("format_type", "")

    if bg_type in ["transparent", "solid_white"]:
        score += 0.25
        reasons.append("Clean background - versatile")
    elif bg_type == "lifestyle" and "lifestyle" in ref_format.lower():
        score += 0.25
        reasons.append("Lifestyle background matches format")
    elif bg_type != "unknown":
        score += 0.15

    # Lighting compatibility (20% weight)
    lighting = image_analysis.get("lighting_type", "unknown")
    if lighting in ["studio", "natural_soft"]:
        score += 0.2
        reasons.append(f"Good lighting ({lighting})")
    elif lighting != "unknown":
        score += 0.1

    # Use case match (25% weight)
    best_uses = image_analysis.get("best_use_cases", [])
    ref_format_lower = ref_format.lower()

    use_case_map = {
        "testimonial": "testimonial",
        "product_showcase": "hero",
        "quote_style": "testimonial",
        "before_after": "comparison"
    }

    target_use = use_case_map.get(ref_format_lower, "hero")
    if target_use in best_uses:
        score += 0.25
        reasons.append(f"Good for {target_use} ads")
    elif best_uses:
        score += 0.1

    # Composition bonus (10% weight)
    if image_analysis.get("product_centered", False):
        score += 0.05
        reasons.append("Product centered")
    if image_analysis.get("product_fully_visible", True):
        score += 0.05

    return min(score, 1.0), reasons


# Phase 6: Hook-to-Benefit Matching Helper Function
def match_benefit_to_hook(hook: Dict, benefits: List[str], unique_selling_points: List[str] = None) -> str:
    """
    Select the most relevant product benefit/USP for a given hook.

    Combines both benefits and unique_selling_points to find the best match.
    USPs are typically more specific, so they're added first for prioritization.

    Strategy:
    1. Combine unique_selling_points + benefits into one list
    2. Extract keywords from hook text and category
    3. Score each item by keyword overlap
    4. Return highest scoring item
    5. Fallback to first item if no match or empty list

    Example:
        Hook: "My dog went from limping to running in 2 weeks!"
        Category: "before_after"
        Keywords: ["limping", "running", "mobility", "movement", "pain"]

        Combined list:
            - "Enhanced with hyaluronic acid for joint lubrication" → HIGH SCORE
            - "Supports hip & joint mobility" → HIGH SCORE (mobility match)
            - "Promotes shiny coat" → LOW SCORE (no match)

        Result: "Enhanced with hyaluronic acid for joint lubrication"
    """
    # Combine USPs and benefits (USPs first for priority when scores are equal)
    combined_items = []
    if unique_selling_points:
        combined_items.extend(unique_selling_points)
    if benefits:
        combined_items.extend(benefits)

    if not combined_items:
        return ""

    if len(combined_items) == 1:
        return combined_items[0]

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

    # Score each item (USP or benefit)
    best_item = combined_items[0]
    best_score = 0

    for item in combined_items:
        item_lower = item.lower()
        item_words = set(item_lower.split())

        # Calculate overlap score
        overlap = len(hook_words & item_words)

        # Bonus points for partial word matches (e.g., "mobility" contains "mobile")
        partial_matches = sum(
            1 for hook_word in hook_words
            for item_word in item_words
            if len(hook_word) > 3 and len(item_word) > 3 and
            (hook_word in item_word or item_word in hook_word)
        )

        score = overlap + (partial_matches * 0.5)

        if score > best_score:
            best_score = score
            best_item = item

    return best_item


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
    product_image_paths: List[str],
    color_mode: str = "original",
    brand_colors: Optional[Dict] = None,
    brand_fonts: Optional[Dict] = None,
    num_variations: int = 5
) -> Dict:
    """
    Generate Nano Banana Pro 3 prompt for ad image generation using JSON format.

    This tool constructs a structured JSON prompt that combines:
    - Reference ad analysis (format, layout, colors)
    - Selected hook (adapted text)
    - Product information (benefits, target audience)
    - Ad brief instructions (brand guidelines)
    - Technical specifications (canvas size, image paths)
    - Brand fonts (heading, body)

    Supports 1-2 product images:
    - Single image: Standard behavior, product image used as-is
    - Two images: Primary (hero/packaging) + Secondary (contents/lifestyle)
      with conditional prompting to guide AI on how to use both

    Args:
        ctx: Run context with AgentDependencies
        prompt_index: Index 1-5 for this variation
        selected_hook: Selected hook dictionary with adapted_text
        product: Product dictionary with name, benefits
        ad_analysis: Ad analysis dictionary with all format details
        ad_brief_instructions: Instructions from ad brief template
        reference_ad_path: Storage path to reference ad
        product_image_paths: List of storage paths to product images (1-2 images)
        color_mode: "original" (use template colors), "complementary" (AI generates fresh colors), or "brand" (use brand colors)
        brand_colors: Brand color data when color_mode is "brand" (dict with primary, secondary, background, all)
        brand_fonts: Brand font data (dict with primary, secondary, primary_weights)
        num_variations: Total number of variations being generated

    Returns:
        Dictionary with Nano Banana prompt in JSON format:
        {
            "prompt_index": 1,
            "hook": {...selected_hook...},
            "json_prompt": {...structured JSON prompt...},
            "full_prompt": "JSON stringified prompt",
            "template_reference_path": "reference-ads/...",
            "product_image_paths": ["products/...", "products/..."]
        }

    Raises:
        ValueError: If required parameters are missing or product_image_paths is empty
    """
    import json

    try:
        logger.info(f"Generating JSON prompt for variation {prompt_index}")

        # Validate inputs
        if prompt_index < 1 or prompt_index > 15:
            raise ValueError("prompt_index must be between 1 and 15")

        if not product_image_paths or len(product_image_paths) == 0:
            raise ValueError("product_image_paths cannot be empty")

        num_product_images = len(product_image_paths)
        logger.info(f"Using {num_product_images} product image(s) for generation")

        # Match benefit/USP to hook for relevant subheadline
        matched_benefit = match_benefit_to_hook(
            selected_hook,
            product.get('benefits', []),
            product.get('unique_selling_points')
        )

        # Build color configuration
        template_colors = ad_analysis.get('color_palette', ['#F5F0E8'])
        if color_mode == "brand" and brand_colors:
            colors_config = {
                "mode": "brand",
                "palette": brand_colors.get('all', [brand_colors.get('primary'), brand_colors.get('secondary'), brand_colors.get('background')]),
                "primary": {"hex": brand_colors.get('primary', '#4747C9'), "name": brand_colors.get('primary_name', 'Primary')},
                "secondary": {"hex": brand_colors.get('secondary', '#FDBE2D'), "name": brand_colors.get('secondary_name', 'Secondary')},
                "background": {"hex": brand_colors.get('background', '#F5F5F5'), "name": brand_colors.get('background_name', 'Background')},
                "instruction": "Use official brand colors consistently throughout the ad"
            }
        elif color_mode == "complementary":
            colors_config = {
                "mode": "complementary",
                "palette": None,
                "instruction": "Generate a fresh, eye-catching complementary color scheme for Facebook ads"
            }
        else:
            colors_config = {
                "mode": "original",
                "palette": template_colors,
                "instruction": "Use the exact colors from the reference template"
            }

        # Build fonts configuration
        fonts_config = None
        if brand_fonts:
            fonts_config = {
                "heading": {
                    "family": brand_fonts.get('primary', 'System default'),
                    "weights": brand_fonts.get('primary_weights', []),
                    "style_notes": brand_fonts.get('primary_style_notes')
                },
                "body": {
                    "family": brand_fonts.get('secondary', 'System default'),
                    "weights": brand_fonts.get('secondary_weights', []),
                    "style_notes": brand_fonts.get('secondary_style_notes')
                }
            }

        # Build founders configuration
        has_founder_signature = ad_analysis.get('has_founder_signature', False)
        has_founder_mention = ad_analysis.get('has_founder_mention', False)
        founders_config = {
            "template_has_signature": has_founder_signature,
            "template_has_mention": has_founder_mention,
            "product_founders": product.get('founders'),
            "action": "omit"  # default
        }
        if (has_founder_signature or has_founder_mention) and product.get('founders'):
            founders_config["action"] = "include"
            founders_config["signature_style"] = ad_analysis.get('founder_signature_style', 'personal sign-off')
            founders_config["signature_placement"] = ad_analysis.get('founder_signature_placement', 'bottom')
        elif (has_founder_signature or has_founder_mention) and not product.get('founders'):
            founders_config["action"] = "omit_with_warning"

        # Build image configurations
        product_images_config = []
        for i, path in enumerate(product_image_paths):
            product_images_config.append({
                "path": path,
                "role": "primary" if i == 0 else "secondary",
                "description": "Main product packaging" if i == 0 else "Product contents or alternate view"
            })

        # Build the complete JSON prompt
        json_prompt = {
            "task": {
                "action": "create_facebook_ad",
                "variation_index": prompt_index,
                "total_variations": num_variations,
                "product_name": product.get('display_name', product.get('name'))
            },

            "special_instructions": {
                "priority": "HIGHEST",
                "text": product.get('combined_instructions'),
                "note": "These instructions override all other guidelines when there is a conflict"
            } if product.get('combined_instructions') else None,

            "product": {
                "id": product.get('id'),
                "name": product.get('name'),
                "display_name": product.get('display_name', product.get('name')),
                "target_audience": product.get('target_audience', 'general audience'),
                "benefits": product.get('benefits', []),
                "unique_selling_points": product.get('unique_selling_points', []),
                "current_offer": product.get('current_offer'),
                "brand_voice_notes": product.get('brand_voice_notes'),
                "prohibited_claims": product.get('prohibited_claims', []),
                "required_disclaimers": product.get('required_disclaimers'),
                "founders": product.get('founders'),
                "product_dimensions": product.get('product_dimensions'),
                "variant": product.get('variant')
            },

            "content": {
                "headline": {
                    "text": selected_hook.get('adapted_text'),
                    "source": "hook",
                    "hook_id": selected_hook.get('id'),
                    "persuasion_type": selected_hook.get('persuasion_type')
                },
                "subheadline": {
                    "text": matched_benefit,
                    "source": "matched_benefit"
                }
            },

            "style": {
                "format_type": ad_analysis.get('format_type'),
                "layout_structure": ad_analysis.get('layout_structure'),
                "canvas_size": ad_analysis.get('canvas_size', '1080x1080px'),
                "text_placement": ad_analysis.get('text_placement', {}),
                "colors": colors_config,
                "fonts": fonts_config,
                "authenticity_markers": ad_analysis.get('authenticity_markers', [])
            },

            "images": {
                "template": {
                    "path": reference_ad_path,
                    "role": "style_reference"
                },
                "product": product_images_config
            },

            "template_analysis": {
                "format_type": ad_analysis.get('format_type'),
                "layout_structure": ad_analysis.get('layout_structure'),
                "has_founder_signature": has_founder_signature,
                "has_founder_mention": has_founder_mention,
                "detailed_description": ad_analysis.get('detailed_description', '')
            },

            "rules": {
                "product_image": {
                    "preserve_exactly": True,
                    "no_modifications": True,
                    "text_preservation": {
                        "critical": True,
                        "requirement": "ALL text on packaging MUST be pixel-perfect legible",
                        "method": "composite_not_regenerate",
                        "rejection_condition": "blurry or illegible text"
                    },
                    "multi_image_handling": {
                        "primary_dominant": True,
                        "secondary_optional": num_product_images > 1,
                        "secondary_usage": "contents, inset view, or background element"
                    } if num_product_images > 1 else None
                },
                "offers": {
                    "use_only_provided": True,
                    "provided_offer": product.get('current_offer'),
                    "do_not_copy_from_template": True,
                    "max_count": 1,
                    "prohibited_template_offers": ["Free gift", "Buy 1 Get 1", "Bundle and save", "Autoship", "BOGO"]
                },
                "lighting": {
                    "match_scene": True,
                    "shadow_direction": "match_scene_elements",
                    "color_temperature": "match_scene",
                    "ambient_occlusion": True,
                    "requirement": "Product must look naturally IN the scene, not pasted on"
                },
                "scale": {
                    "realistic_sizing": True,
                    "relative_to": ["hands", "countertops", "furniture", "pets"],
                    "product_dimensions": product.get('product_dimensions'),
                    "requirement": "Product must appear proportionally correct"
                },
                "founders": founders_config,
                "prohibited_claims": product.get('prohibited_claims', []),
                "required_disclaimers": product.get('required_disclaimers')
            },

            "ad_brief": {
                "instructions": ad_brief_instructions
            }
        }

        # Remove None values for cleaner JSON
        def remove_none(d):
            if isinstance(d, dict):
                return {k: remove_none(v) for k, v in d.items() if v is not None}
            elif isinstance(d, list):
                return [remove_none(i) for i in d if i is not None]
            return d

        json_prompt = remove_none(json_prompt)

        # Create full prompt as JSON string
        full_prompt = json.dumps(json_prompt, indent=2)

        prompt_dict = {
            "prompt_index": prompt_index,
            "hook": selected_hook,
            "json_prompt": json_prompt,
            "full_prompt": full_prompt,
            "template_reference_path": reference_ad_path,
            "product_image_paths": product_image_paths
        }

        logger.info(f"Generated JSON prompt for variation {prompt_index} ({len(full_prompt)} chars)")
        return prompt_dict

    except ValueError as e:
        logger.error(f"Invalid input: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Failed to generate JSON prompt: {str(e)}")
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

    Supports 1-2 product images:
    - Single image: Template + 1 product image = 2 reference images
    - Two images: Template + 2 product images = 3 reference images

    Args:
        ctx: Run context with AgentDependencies
        nano_banana_prompt: Prompt dictionary from generate_nano_banana_prompt
            Must contain 'product_image_paths' (list of 1-2 paths)

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

        # Download template reference image
        template_data = await ctx.deps.ad_creation.download_image(
            nano_banana_prompt['template_reference_path']
        )

        # Download all product images (1-2 images)
        product_image_paths = nano_banana_prompt.get('product_image_paths', [])
        product_images_data = []
        for path in product_image_paths:
            img_data = await ctx.deps.ad_creation.download_image(path)
            product_images_data.append(img_data)

        # Build reference images list: template + all product images
        reference_images = [template_data] + product_images_data

        # Log for verification
        num_product_images = len(product_images_data)
        logger.info(f"Reference images for Nano Banana: {len(reference_images)} total")
        logger.info(f"  - 1 template image")
        logger.info(f"  - {num_product_images} product image(s)")

        # Log whether secondary image instructions are present
        if "SECONDARY" in nano_banana_prompt.get('full_prompt', ''):
            logger.info("Prompt includes SECONDARY image instructions ✓")
        else:
            logger.info("Prompt uses single image mode (no SECONDARY)")

        # Call Gemini Nano Banana API with metadata tracking
        generation_result = await ctx.deps.gemini.generate_image(
            prompt=nano_banana_prompt['full_prompt'],
            reference_images=reference_images,
            return_metadata=True
        )

        generated_ad = {
            "prompt_index": prompt_index,
            "image_base64": generation_result["image_base64"],
            "storage_path": None,  # Will be set by save_generated_ad
            # Generation metadata for logging
            "model_requested": generation_result.get("model_requested"),
            "model_used": generation_result.get("model_used"),
            "generation_time_ms": generation_result.get("generation_time_ms"),
            "generation_retries": generation_result.get("retries", 0),
            "num_reference_images": len(reference_images)
        }

        logger.info(f"Generated ad image for variation {prompt_index} "
                   f"(model={generation_result.get('model_used')}, "
                   f"time={generation_result.get('generation_time_ms')}ms, "
                   f"ref_images={len(reference_images)})")
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
        import uuid as uuid_module

        prompt_index = generated_ad['prompt_index']
        logger.info(f"Saving generated ad {prompt_index} for run {ad_run_id}")

        # Validate inputs
        if not generated_ad.get('image_base64'):
            raise ValueError("image_base64 is required")

        # Convert string to UUID
        ad_run_uuid = UUID(ad_run_id)
        hook_uuid = UUID(hook['hook_id'])

        # Generate ad_id upfront for structured naming
        ad_uuid = uuid_module.uuid4()

        # Get product_id for structured naming
        product_id = await ctx.deps.ad_creation.get_product_id_for_run(ad_run_uuid)

        # Get canvas size from JSON prompt
        canvas_size = None
        json_prompt = nano_banana_prompt.get('json_prompt', {})
        if isinstance(json_prompt, dict):
            style = json_prompt.get('style', {})
            canvas_size = style.get('canvas_size', '1080x1080px')

        # Upload to storage with structured naming params
        storage_path, _ = await ctx.deps.ad_creation.upload_generated_ad(
            ad_run_id=ad_run_uuid,
            prompt_index=prompt_index,
            image_base64=generated_ad['image_base64'],
            product_id=product_id,
            ad_id=ad_uuid,
            canvas_size=canvas_size
        )

        # Save to database with same ad_id for consistency
        generated_ad_id = await ctx.deps.ad_creation.save_generated_ad(
            ad_run_id=ad_run_uuid,
            prompt_index=prompt_index,
            prompt_text=nano_banana_prompt['full_prompt'],
            prompt_spec=json_prompt,  # Now using json_prompt instead of spec
            hook_id=hook_uuid,
            hook_text=hook['adapted_text'],
            storage_path=storage_path,
            final_status="pending",  # Will be updated after reviews
            # Model tracking metadata
            model_requested=generated_ad.get('model_requested'),
            model_used=generated_ad.get('model_used'),
            generation_time_ms=generated_ad.get('generation_time_ms'),
            generation_retries=generated_ad.get('generation_retries', 0),
            ad_id=ad_uuid  # Use same ID as upload for consistency
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

        # Call Vision AI using Pydantic AI Agent
        from pydantic_ai import Agent
        from pydantic_ai.messages import BinaryContent
        import base64

        # Create temporary agent
        vision_agent = Agent(
            model=Config.get_model("vision"),
            system_prompt="You are an expert creative director. Return ONLY valid JSON."
        )

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

        # Run agent
        result = await vision_agent.run(
            [
                review_prompt + "\n\nReturn ONLY valid JSON, no other text.",
                BinaryContent(data=image_data, media_type=media_type)
            ]
        )
        
        review_text = result.output

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
    project_id: Optional[str] = None,
    parameters: Optional[Dict] = None
) -> str:
    """
    Create new ad run record in database to track workflow.

    This tool initializes the ad creation workflow by:
    1. Creating a record in the ad_runs table
    2. Linking to product and reference ad
    3. Setting initial status to "pending"
    4. Storing generation parameters for tracking
    5. Returning ad_run_id for subsequent operations

    Args:
        ctx: Run context with AgentDependencies
        product_id: UUID of product as string
        reference_ad_storage_path: Storage path to uploaded reference ad
        project_id: Optional UUID of project as string
        parameters: Optional dict of generation parameters (num_variations, content_source, etc.)

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
            project_id=project_uuid,
            parameters=parameters
        )

        logger.info(f"Ad run created: {ad_run_id}")
        return str(ad_run_id)

    except ValueError as e:
        logger.error(f"Invalid input: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Failed to create ad run: {str(e)}")
        raise Exception(f"Failed to create ad run: {str(e)}")


# ============================================================================
# RECREATE TEMPLATE TOOLS (Alternative to Hooks)
# ============================================================================

@ad_creation_agent.tool(
    metadata={
        'category': 'Analysis',
        'platform': 'Facebook',
        'rate_limit': '5/minute',
        'use_cases': [
            'Extract the persuasive angle from a reference ad template',
            'Identify the messaging structure and emotional appeal',
            'Prepare for benefit-based variations'
        ],
        'examples': [
            'Extract angle from testimonial template',
            'Analyze persuasive structure of reference ad'
        ]
    }
)
async def extract_template_angle(
    ctx: RunContext[AgentDependencies],
    reference_ad_storage_path: str,
    ad_analysis: Dict
) -> Dict:
    """
    Extract the persuasive angle and messaging structure from a reference ad.

    This tool uses Vision AI to analyze the reference ad and extract:
    - The main persuasive angle (before/after, testimonial, benefit-focused, etc.)
    - The messaging structure/template
    - Key phrases and patterns that can be adapted
    - Emotional tone and style

    This is used for "Recreate Template" mode where we keep the template's
    angle structure but swap in different product benefits.

    Args:
        ctx: Run context with AgentDependencies
        reference_ad_storage_path: Storage path to reference ad image
        ad_analysis: Ad analysis dictionary with format details

    Returns:
        Dictionary with extracted angle:
        {
            "angle_type": "before_after" | "testimonial" | "benefit_statement" | "social_proof" | "question_hook",
            "messaging_template": "Template structure with {placeholders}",
            "original_text": "The exact text from the reference ad",
            "tone": "casual" | "professional" | "urgent" | "emotional",
            "key_elements": ["transformation", "timeframe", "specific_result"],
            "adaptation_guidance": "How to adapt this angle for different benefits"
        }

    Raises:
        ValueError: If reference ad path is invalid
        Exception: If Vision AI analysis fails
    """
    import json

    try:
        logger.info(f"Extracting template angle from: {reference_ad_storage_path}")

        # Validate input
        if not reference_ad_storage_path:
            raise ValueError("reference_ad_storage_path cannot be empty")

        # Download reference ad image from storage as base64
        image_data = await ctx.deps.ad_creation.get_image_as_base64(reference_ad_storage_path)

        # Build extraction prompt
        extraction_prompt = f"""
        Analyze this Facebook ad and extract its persuasive angle and messaging structure.

        **Context from previous analysis:**
        - Format: {ad_analysis.get('format_type')}
        - Layout: {ad_analysis.get('layout_structure')}
        - Authenticity markers: {', '.join(ad_analysis.get('authenticity_markers', []))}

        **Task:** Extract the core persuasive angle so it can be recreated with different product benefits.

        Analyze:

        1. **Angle Type**: What is the primary persuasive approach?
           - before_after: Shows transformation (e.g., "went from X to Y")
           - testimonial: Personal experience/quote format
           - benefit_statement: Direct benefit claim
           - social_proof: Uses numbers/authority (e.g., "100,000+ customers")
           - question_hook: Poses a question to the reader
           - problem_solution: Presents problem then solution

        2. **Original Text**: Extract the EXACT main headline/hook text from the ad.

        3. **Messaging Template**: Create a template version with {{placeholders}}:
           - Replace the specific benefit/result with {{benefit}}
           - Replace specific product name with {{product}}
           - Replace specific timeframe with {{timeframe}} if present
           - Keep the structure and tone intact
           Example: "My dog went from limping to running in 2 weeks!"
           → "My {{subject}} went from {{problem}} to {{result}} in {{timeframe}}!"

        4. **Tone**: What's the emotional tone?
           - casual: Friendly, conversational, relatable
           - professional: Expert, authoritative, clinical
           - urgent: Time-sensitive, action-oriented
           - emotional: Heart-tugging, personal, vulnerable

        5. **Key Elements**: What structural elements are critical?
           (e.g., transformation, timeframe, specific_result, personal_pronoun, exclamation)

        6. **Adaptation Guidance**: Brief notes on how to adapt this template
           for different benefits while maintaining effectiveness.

        Return JSON with this structure:
        {{
            "angle_type": "string",
            "original_text": "exact text from ad",
            "messaging_template": "template with {{placeholders}}",
            "tone": "string",
            "key_elements": ["element1", "element2"],
            "adaptation_guidance": "guidance text"
        }}
        """

        # Call Vision AI using Pydantic AI Agent
        from pydantic_ai import Agent
        from pydantic_ai.messages import BinaryContent
        import base64

        # Detect image format
        media_type = "image/png"
        try:
            if image_base64.startswith('/9j/'):
                media_type = "image/jpeg"
            elif image_base64.startswith('iVBORw0KGgo'):
                 media_type = "image/png"
            elif image_base64.startswith('R0lGOD'):
                media_type = "image/gif"
            elif image_base64.startswith('UklGR'):
                media_type = "image/webp"
        except Exception:
            pass 

        # Create temporary agent
        vision_agent = Agent(
            model=Config.get_model("vision"),
            system_prompt="You are a marketing analysis expert. Return ONLY valid JSON."
        )

        # Decode base64
        if isinstance(image_data, str):
             image_bytes = base64.b64decode(image_data)
        else:
             image_bytes = image_data

        result = await vision_agent.run(
            [
                extraction_prompt + "\n\nReturn ONLY valid JSON, no other text.",
                BinaryContent(data=image_bytes, media_type=media_type)
            ]
        )
        


        result_text = result.output
        
        # Strip markdown code fences if present
        result_clean = result_text.strip()
        if result_clean.startswith('```'):
            first_newline = result_clean.find('\n')
            last_fence = result_clean.rfind('```')
            if first_newline != -1 and last_fence > first_newline:
                result_clean = result_clean[first_newline + 1:last_fence].strip()

        angle_dict = json.loads(result_clean)

        logger.info(f"Extracted template angle: type={angle_dict.get('angle_type')}, "
                   f"tone={angle_dict.get('tone')}")

        return angle_dict

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse angle extraction response: {str(e)}")
        raise Exception(f"Failed to parse angle extraction: {str(e)}")
    except ValueError as e:
        logger.error(f"Invalid reference ad path: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Failed to extract template angle: {str(e)}")
        raise Exception(f"Failed to extract template angle: {str(e)}")


@ad_creation_agent.tool(
    metadata={
        'category': 'Analysis',
        'platform': 'Facebook',
        'rate_limit': '5/minute',
        'use_cases': [
            'Generate hook-like variations from product benefits',
            'Create messaging variations based on template angle',
            'Produce content for recreate template mode'
        ],
        'examples': [
            'Generate 5 benefit variations for joint supplement',
            'Create messaging from USPs using testimonial template'
        ]
    }
)
async def generate_benefit_variations(
    ctx: RunContext[AgentDependencies],
    product: Dict,
    template_angle: Dict,
    ad_analysis: Dict,
    count: int = 5,
    persona_data: Optional[Dict] = None
) -> List[Dict]:
    """
    Generate hook-like variations by applying the template angle to product benefits.

    This tool takes the extracted template angle and applies it to different
    product benefits and USPs, creating variations that maintain the template's
    persuasive structure while highlighting different aspects of the product.

    When persona_data is provided, the variations are tailored to resonate with
    the persona's pain points, desires, and language patterns.

    Args:
        ctx: Run context with AgentDependencies
        product: Product dictionary with benefits, unique_selling_points, etc.
        template_angle: Extracted angle from extract_template_angle()
        ad_analysis: Ad analysis dictionary with format details
        count: Number of variations to generate (1-15)
        persona_data: Optional 4D persona data with pain_points, desires, their_language,
            transformation, objections, and amazon_testimonials for targeted copy

    Returns:
        List of hook-like dictionaries (same structure as select_hooks output):
        [
            {
                "hook_id": "benefit_1",  # Synthetic ID for benefit-based hooks
                "text": "Original benefit text",
                "category": "benefit_variation",
                "framework": "Recreate Template",
                "impact_score": 15,  # Default score
                "reasoning": "Why this benefit was chosen...",
                "adapted_text": "Benefit applied to template structure"
            },
            ...
        ]

    Raises:
        ValueError: If product has no benefits/USPs or count is invalid
        Exception: If Gemini AI generation fails
    """
    import json
    import random
    from uuid import uuid4

    try:
        logger.info(f"Generating {count} benefit variations using template angle")

        # Validate inputs
        if count < 1 or count > 15:
            raise ValueError("count must be between 1 and 15")

        # Combine benefits and USPs
        benefits = product.get('benefits', []) or []
        usps = product.get('unique_selling_points', []) or []
        key_ingredients = product.get('key_ingredients', []) or []

        all_content = benefits + usps + key_ingredients
        if not all_content:
            raise ValueError("Product has no benefits, USPs, or key ingredients to use")

        # Shuffle for variety
        shuffled_content = all_content.copy()
        random.shuffle(shuffled_content)

        # Query knowledge base for copywriting best practices
        knowledge_context = ""
        if hasattr(ctx.deps, 'docs') and ctx.deps.docs is not None:
            try:
                target_audience = product.get('target_audience', 'general audience')
                angle_type = template_angle.get('angle_type', 'benefit')
                knowledge_results = ctx.deps.docs.search(
                    f"hook writing {angle_type} {target_audience} direct response advertising",
                    limit=3,
                    tags=["hooks", "copywriting"]
                )
                if knowledge_results:
                    knowledge_sections = []
                    for r in knowledge_results:
                        knowledge_sections.append(f"### {r.title}\n{r.chunk_content}")
                    knowledge_context = "\n\n".join(knowledge_sections)
                    logger.info(f"Retrieved {len(knowledge_results)} knowledge base sections for benefit variations")
            except Exception as e:
                logger.warning(f"Knowledge base query failed (continuing without): {e}")

        # Get product offer and prohibited claims
        current_offer = product.get('current_offer', '')
        prohibited_claims = product.get('prohibited_claims', []) or []
        social_proof = product.get('social_proof', '')
        brand_name = product.get('brand_name', '')
        banned_terms = product.get('banned_terms', []) or []

        # Get VERIFIED social proof (new structured fields)
        review_platforms = product.get('review_platforms', {}) or {}
        media_features = product.get('media_features', []) or []
        awards_certifications = product.get('awards_certifications', []) or []

        # Separate emotional benefits (good for headlines) from technical specs (not for headlines)
        # Benefits are typically emotional/outcome-focused, USPs may include specs
        emotional_benefits = benefits.copy() if benefits else []

        # Filter USPs to only include emotional/outcome-focused ones, not technical specs
        emotional_usps = []
        technical_specs = []
        for usp in (usps or []):
            usp_lower = usp.lower()
            # Technical specs often contain numbers, measurements, or product features
            if any(term in usp_lower for term in ['cards', 'pages', 'included', 'app', 'guide', 'dictionary', 'guarantee', 'money-back']):
                technical_specs.append(usp)
            else:
                emotional_usps.append(usp)

        # Combine emotional content for headline generation
        headline_content = emotional_benefits + emotional_usps
        if not headline_content:
            # Fallback to all content if filtering removed everything
            headline_content = benefits + usps

        # Build generation prompt
        generation_prompt = f"""
        You are a world-class direct response copywriter - the kind who has generated millions in sales through Facebook ads. Your copy is:
        - Crystal clear: The reader knows EXACTLY what this is and who it's for within 2 seconds
        - Emotionally resonant: You tap into real pain points and desires
        - Punchy and concise: Every word earns its place, no fluff
        - Action-oriented: The reader feels compelled to learn more
        - Authentic: It sounds like a real person, not a corporation

        You're writing headline variations for a Facebook ad campaign.

        **Product:** {product.get('name', 'Product')}
        **Target Audience:** {product.get('target_audience', 'General audience')}

        **PRODUCT'S ACTUAL OFFER (USE THIS EXACTLY):**
        {current_offer if current_offer else "No specific offer - do not mention discounts or percentages"}

        **VERIFIED SOCIAL PROOF - USE ONLY THESE (CRITICAL - DO NOT INVENT):**

        Review Platforms (ONLY use these exact ratings/counts):
        {json.dumps(review_platforms, indent=2) if review_platforms else "NONE - Do not mention Trustpilot, Amazon reviews, or any review platform"}

        Media Features ("As Seen On" / "Featured In" - ONLY use these):
        {json.dumps(media_features) if media_features else "NONE - Do not mention any media outlets, TV shows, or publications"}

        Awards & Certifications (ONLY use these):
        {json.dumps(awards_certifications) if awards_certifications else "NONE - Do not mention any awards or certifications"}

        Legacy Social Proof Text:
        {social_proof if social_proof else "None"}

        **SOCIAL PROOF RULES (VERY IMPORTANT):**
        - ONLY use review platforms, ratings, and counts listed above - NEVER invent them
        - If template shows Trustpilot but we have NO Trustpilot data → OMIT the Trustpilot badge entirely
        - If template shows "As Seen On Forbes" but Forbes is NOT in our media_features → OMIT it
        - You may substitute: if template shows Trustpilot but we have Amazon reviews, use Amazon instead
        - NEVER invent: star ratings, review counts, media logos, "100,000+ sold", "#1 Best Seller" unless verified above
        - When in doubt, OMIT the social proof element rather than making something up

        **PROHIBITED CLAIMS (NEVER USE THESE):**
        {json.dumps(prohibited_claims) if prohibited_claims else "None specified"}

        **BANNED COMPETITOR NAMES (NEVER USE - use "{brand_name}" instead):**
        {json.dumps(banned_terms) if banned_terms else "None specified"}

        **FORMATTING RULES:**
        - Do NOT use markdown formatting (no asterisks for bold like *word*)
        - Write plain text only - the rendering system will handle formatting

        **Template Angle (from successful reference ad):**
        - Type: {template_angle.get('angle_type')}
        - Original text: "{template_angle.get('original_text', '')}"
        - Original word count: {len(template_angle.get('original_text', '').split())} words
        - Original character count: {len(template_angle.get('original_text', ''))} characters
        - Template structure: "{template_angle.get('messaging_template', '')}"
        - Tone: {template_angle.get('tone')}
        - Key elements: {', '.join(template_angle.get('key_elements', []))}
        - Adaptation guidance: {template_angle.get('adaptation_guidance', '')}

        **Reference Ad Style:**
        - Format: {ad_analysis.get('format_type')}
        - Authenticity markers: {', '.join(ad_analysis.get('authenticity_markers', []))}

        {f'''**COPYWRITING BEST PRACTICES FROM KNOWLEDGE BASE:**
        Use these proven techniques to write more compelling headlines:

        {knowledge_context}

        Apply these principles when crafting your adapted headlines.
        ''' if knowledge_context else ''}

        {f'''**TARGET PERSONA: {persona_data.get('persona_name', 'Unknown')}**
        {persona_data.get('snapshot', '')}

        **Persona Pain Points (address these in headlines):**
        {json.dumps(persona_data.get('pain_points', [])[:5], indent=2)}

        **Persona Desires (what they want to achieve):**
        {json.dumps(persona_data.get('desires', [])[:5], indent=2)}

        **Transformation (before → after):**
        Before: {json.dumps(persona_data.get('transformation', {}).get('before', [])[:3])}
        After: {json.dumps(persona_data.get('transformation', {}).get('after', [])[:3])}

        **Their Language (how the persona talks - match this style):**
        {json.dumps(persona_data.get('their_language', [])[:3], indent=2)}

        **Amazon Testimonials (real customer voice - use similar language):**
        {json.dumps(persona_data.get('amazon_testimonials', {}), indent=2) if persona_data.get('amazon_testimonials') else 'None available'}

        PERSONA INTEGRATION RULES:
        1. Frame headlines around the persona's specific pain points
        2. Use the transformation language (before → after) for emotional impact
        3. Match the persona's speaking style from "Their Language"
        4. If Amazon testimonials are available, borrow phrases for authenticity
        5. Address their objections implicitly in the headline when possible
        ''' if persona_data else ''}

        **EMOTIONAL BENEFITS (Use these for headlines - they connect with the audience):**
        {json.dumps(headline_content, indent=2)}

        **TECHNICAL SPECS (Do NOT use these in headlines - too feature-focused):**
        {json.dumps(technical_specs, indent=2) if technical_specs else "None"}

        **Task:** Select exactly {count} different EMOTIONAL BENEFITS and create adapted headlines.

        For each:
        1. Pick an EMOTIONAL BENEFIT that would work well with the template structure
        2. Apply the template pattern to create a new headline
        3. Maintain the same tone and key elements as the original
        4. Make it sound natural and authentic (not templated)

        **CRITICAL LENGTH RULES (VERY IMPORTANT):**
        - The original template headline is {len(template_angle.get('original_text', '').split())} words / {len(template_angle.get('original_text', ''))} characters
        - Your adapted headlines MUST be similar length: aim for {len(template_angle.get('original_text', '').split())} words (±3 words max)
        - DO NOT write paragraphs - write PUNCHY headlines
        - Shorter is better - if you can say it in fewer words, do it
        - Long headlines = worse ad performance AND harder for AI to render text cleanly
        - If the original is 8 words, yours should be 5-11 words, NOT 20 words

        **CRITICAL CLARITY RULES:**
        - The headline MUST be immediately clear about WHO this is for
        - NEVER use pronouns like "their", "them", "they" without first establishing who you're talking about
        - If the product is for parents of children, SAY "your child", "your kids", "your son/daughter"
        - The reader should understand within 2 seconds what this product helps them with
        - Avoid vague language - be specific about the transformation or benefit
        - Example BAD: "Finally understand their world" (who is 'their'?)
        - Example GOOD: "Finally understand your child's gaming world"

        **CRITICAL OFFER RULES (DO NOT HALLUCINATE):**
        - The product's ACTUAL offer is: "{current_offer if current_offer else 'NO OFFER - do not mention any discounts or gifts'}"
        - ONLY use the EXACT offer text above - nothing else
        - DO NOT copy offers from the reference template (it's for a different product!)
        - DO NOT invent: free gifts, bonus items, limited quantities ("50 owners"), time limits ("this weekend", "until midnight"), dollar amounts, or bundle deals
        - If the template says "4 FREE gifts" but our product offer doesn't mention gifts, DO NOT include gifts
        - If our offer is just "Up to 35% off", that's ALL you can say about the offer - no additions

        **CRITICAL ACCURACY RULES:**
        - Each variation MUST use a DIFFERENT benefit
        - DO NOT use technical specs like "linen-finish cards", "86 cards", etc. in headlines
        - Match the tone (casual, professional, etc.)
        - The adapted text must make sense on its own
        - You may include the social proof if it fits naturally
        - NEVER use any prohibited claims listed above

        Return JSON array:
        [
            {{
                "original_benefit": "the benefit text you're using",
                "reasoning": "Why this benefit works well with the template",
                "adapted_text": "The new headline applying the template to this benefit"
            }},
            ...
        ]
        """

        # Call Pydantic AI Agent for high-quality copy generation
        from pydantic_ai import Agent
        from ...core.config import Config
        import asyncio

        variation_agent = Agent(
            model=Config.get_model("creative"),
            system_prompt="You are a persuasive copywriting expert. Return ONLY valid JSON."
        )

        max_retries = 3
        last_error = None

        for attempt in range(max_retries):
            try:
                # Use configured creative model
                result = await variation_agent.run(
                    generation_prompt + "\n\nReturn ONLY valid JSON array, no other text."
                )
                result_text = result.output

                # Strip markdown code fences if present
                result_text = result_text.strip()
                if result_text.startswith("```"):
                    result_text = result_text.split("\n", 1)[1] if "\n" in result_text else result_text[3:]
                    if result_text.endswith("```"):
                        result_text = result_text.rsplit("\n```", 1)[0]

                result_text = result_text.strip()
                variations_raw = json.loads(result_text)

                # Helper function to strip markdown formatting from text
                def strip_markdown(text: str) -> str:
                    """Remove markdown formatting like *bold* and _italic_ from text."""
                    import re
                    # Remove bold (**text** or __text__)
                    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
                    text = re.sub(r'__(.+?)__', r'\1', text)
                    # Remove italic (*text* or _text_)
                    text = re.sub(r'\*(.+?)\*', r'\1', text)
                    text = re.sub(r'(?<!\w)_(.+?)_(?!\w)', r'\1', text)
                    return text

                # Helper function to replace banned terms with brand name
                def replace_banned_terms(text: str, banned: List[str], brand: str) -> str:
                    """Replace banned competitor names with brand name (case-insensitive)."""
                    import re
                    result = text
                    for term in banned:
                        if term and brand:
                            # Case-insensitive replacement
                            pattern = re.compile(re.escape(term), re.IGNORECASE)
                            result = pattern.sub(brand, result)
                    return result

                # Convert to hook-like format for compatibility with rest of workflow
                variations = []
                for i, var in enumerate(variations_raw, start=1):
                    adapted_text = var.get('adapted_text', '')
                    # Strip markdown formatting (e.g., *bold* → bold)
                    adapted_text = strip_markdown(adapted_text)
                    # Replace banned competitor terms with brand name
                    if banned_terms and brand_name:
                        adapted_text = replace_banned_terms(adapted_text, banned_terms, brand_name)

                    variations.append({
                        "hook_id": str(uuid4()),  # Generate unique ID
                        "text": var.get('original_benefit', ''),
                        "category": "benefit_variation",
                        "framework": f"Recreate Template ({template_angle.get('angle_type', 'unknown')})",
                        "impact_score": 15,  # Default score for benefit-based
                        "reasoning": var.get('reasoning', ''),
                        "adapted_text": adapted_text
                    })

                # Validate each variation for hallucinated content
                validation_issues = []
                original_word_count = len(template_angle.get('original_text', '').split())

                for i, var in enumerate(variations):
                    adapted = var.get('adapted_text', '').lower()
                    issues = []

                    # Check for hallucinated offer elements not in product offer
                    offer_lower = (current_offer or '').lower()

                    # Check for free gifts if not in actual offer
                    if 'free gift' in adapted or 'free bonus' in adapted or 'free ' in adapted:
                        if 'free' not in offer_lower:
                            issues.append("mentions 'free gifts/bonus' but product offer doesn't include free items")

                    # Check for invented scarcity numbers
                    import re
                    scarcity_patterns = re.findall(r'\b(\d+)\s*(owners?|customers?|people|buyers?|spots?)\b', adapted)
                    if scarcity_patterns:
                        issues.append(f"contains invented scarcity numbers: {scarcity_patterns}")

                    # Check for invented time limits
                    time_limits = ['this week', 'this weekend', 'today only', 'until midnight', 'next 24 hours',
                                   'limited time', 'ends soon', 'last chance', 'hurry', 'act now', 'for black friday']
                    for limit in time_limits:
                        if limit in adapted and limit not in offer_lower:
                            issues.append(f"contains invented time limit: '{limit}'")
                            break

                    # Check for dollar amounts not in offer
                    dollar_amounts = re.findall(r'\$\d+', adapted)
                    for amount in dollar_amounts:
                        if amount not in (current_offer or ''):
                            issues.append(f"contains invented dollar amount: {amount}")
                            break

                    # Check word count (allow ±5 words from original)
                    adapted_word_count = len(var.get('adapted_text', '').split())
                    if original_word_count > 0 and abs(adapted_word_count - original_word_count) > 8:
                        issues.append(f"too long: {adapted_word_count} words vs original {original_word_count} words")

                    if issues:
                        validation_issues.append({
                            "index": i,
                            "adapted_text": var.get('adapted_text', ''),
                            "issues": issues
                        })

                # If we have validation issues, regenerate with feedback
                if validation_issues and attempt < max_retries - 1:
                    issues_summary = "\n".join([
                        f"- Variation {v['index']+1}: {'; '.join(v['issues'])}"
                        for v in validation_issues
                    ])
                    logger.warning(f"Validation failed for {len(validation_issues)} variations:\n{issues_summary}")

                    # Add feedback to prompt for retry
                    generation_prompt += f"""

        **⚠️ YOUR PREVIOUS ATTEMPT HAD THESE ISSUES - FIX THEM:**
        {issues_summary}

        Remember:
        - Only use the EXACT offer: "{current_offer if current_offer else 'NO OFFER'}"
        - Do NOT invent free gifts, scarcity numbers, time limits, or dollar amounts
        - Keep headlines around {original_word_count} words (±5 max)
        - Write like a top direct response copywriter - clear, punchy, persuasive
                    """
                    continue  # Retry with feedback

                logger.info(f"Generated {len(variations)} benefit variations (validated)")
                return variations

            except json.JSONDecodeError as e:
                last_error = e
                logger.warning(f"Attempt {attempt + 1}/{max_retries} - JSON parse error: {str(e)}")
                if attempt < max_retries - 1:
                    continue
                else:
                    raise Exception(f"Failed to parse variations after {max_retries} attempts: {str(e)}")

    except ValueError as e:
        logger.error(f"Invalid input: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Failed to generate benefit variations: {str(e)}")
        raise Exception(f"Failed to generate benefit variations: {str(e)}")


async def adapt_belief_to_template(
    belief_statement: str,
    template_angle: Dict[str, Any],
    product: Dict[str, Any],
    variation_number: int = 1
) -> str:
    """
    Adapt a belief statement to match a template's structure/tone.

    This helper function takes a belief statement (from the belief-first planning
    framework) and rewrites it to match the structure of an extracted template
    angle from a reference ad.

    Args:
        belief_statement: The core belief to communicate
        template_angle: Extracted template structure from reference ad
            (from extract_template_angle)
        product: Product data for context
        variation_number: Which variation (for diversity in output)

    Returns:
        Headline text that communicates the belief in the template's style
    """
    from pydantic_ai import Agent
    from viraltracker.core.config import Config

    prompt = f"""You are a direct response copywriter. Your task is to rewrite a belief statement
to match a specific headline template structure.

BELIEF TO COMMUNICATE:
{belief_statement}

TEMPLATE STRUCTURE:
- Type: {template_angle.get('angle_type', 'unknown')}
- Pattern: {template_angle.get('messaging_template', '')}
- Tone: {template_angle.get('tone', 'casual')}
- Key Elements: {', '.join(template_angle.get('key_elements', []))}
- Guidance: {template_angle.get('adaptation_guidance', '')}

PRODUCT: {product.get('name', '')}

RULES:
1. Keep the CORE BELIEF intact - the meaning must be preserved
2. Apply the template's STRUCTURE and TONE
3. Match approximate word count of template pattern
4. Use first-person if template uses it ("I", "My")
5. This is variation #{variation_number} - make it unique but on-message
6. Do NOT invent claims, offers, or timeframes not in the belief
7. Output ONLY the headline text, nothing else

Write the adapted headline:"""

    agent = Agent(
        model=Config.get_model("CREATIVE"),
        system_prompt="You are a direct response copywriter. Output only the headline text."
    )

    result = await agent.run(prompt)
    return result.output.strip().strip('"').strip("'")


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
    match_template_structure: bool = False
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
    try:
        from datetime import datetime
        from uuid import UUID
        import json

        # Validate num_variations
        if num_variations < 1 or num_variations > 15:
            raise ValueError(f"num_variations must be between 1 and 15, got {num_variations}")

        # Validate content_source
        valid_content_sources = ["hooks", "recreate_template", "belief_first"]
        if content_source not in valid_content_sources:
            raise ValueError(f"content_source must be one of {valid_content_sources}, got {content_source}")

        logger.info(f"=== STARTING COMPLETE AD WORKFLOW for product {product_id} ===")
        logger.info(f"Generating {num_variations} ad variations using content_source='{content_source}'")
        if persona_id:
            logger.info(f"Using persona: {persona_id}")
        if variant_id:
            logger.info(f"Using variant: {variant_id}")
        if additional_instructions:
            logger.info(f"Additional instructions provided: {additional_instructions[:50]}...")

        # Build parameters dict for tracking
        run_parameters = {
            "num_variations": num_variations,
            "content_source": content_source,
            "color_mode": color_mode,
            "image_selection_mode": image_selection_mode,
            "selected_image_paths": selected_image_paths,
            "brand_colors": brand_colors,
            "persona_id": persona_id,
            "variant_id": variant_id,
            "additional_instructions": additional_instructions
        }

        # STAGE 1: Initialize ad run and upload reference ad
        logger.info("Stage 1: Creating ad run...")

        # Create temporary ad run to get ID (we'll update status later)
        ad_run_id_str = await create_ad_run(
            ctx=ctx,
            product_id=product_id,
            reference_ad_storage_path="temp",  # Will update after upload
            project_id=project_id,
            parameters=run_parameters
        )

        # Upload reference ad
        reference_ad_path = await upload_reference_ad(
            ctx=ctx,
            ad_run_id=ad_run_id_str,
            image_base64=reference_ad_base64,
            filename=reference_ad_filename
        )

        # Update ad run with correct reference path and status
        await ctx.deps.ad_creation.update_ad_run(
            ad_run_id=UUID(ad_run_id_str),
            status="analyzing",
            reference_ad_storage_path=reference_ad_path
        )

        logger.info(f"Ad run created: {ad_run_id_str}")

        # STAGE 2: Fetch product data
        logger.info("Stage 2: Fetching product data...")
        product_dict = await get_product_with_images(ctx=ctx, product_id=product_id)

        # STAGE 2b: Fetch persona data (if persona_id provided)
        persona_data = None
        if persona_id:
            logger.info(f"Stage 2b: Fetching persona data for {persona_id}...")
            try:
                persona_data = ctx.deps.ad_creation.get_persona_for_ad_generation(UUID(persona_id))
                if persona_data:
                    logger.info(f"Loaded persona: {persona_data.get('persona_name', 'Unknown')}")
                    logger.info(f"  - Pain points: {len(persona_data.get('pain_points', []))}")
                    logger.info(f"  - Desires: {len(persona_data.get('desires', []))}")
                    logger.info(f"  - Amazon testimonials: {len(persona_data.get('amazon_testimonials', {}))}")
                else:
                    logger.warning(f"Persona not found: {persona_id} - continuing without persona targeting")
            except Exception as e:
                logger.warning(f"Failed to load persona {persona_id}: {e} - continuing without persona targeting")

        # STAGE 2c: Fetch variant data (if variant_id provided)
        variant_data = None
        if variant_id:
            logger.info(f"Stage 2c: Fetching variant data for {variant_id}...")
            try:
                from viraltracker.core.database import get_supabase_client
                db = get_supabase_client()
                result = db.table("product_variants").select(
                    "id, name, slug, variant_type, description, differentiators"
                ).eq("id", variant_id).single().execute()
                if result.data:
                    variant_data = result.data
                    logger.info(f"Loaded variant: {variant_data.get('name', 'Unknown')}")
                    logger.info(f"  - Type: {variant_data.get('variant_type', 'unknown')}")
                    if variant_data.get('description'):
                        logger.info(f"  - Description: {variant_data['description'][:50]}...")
                else:
                    logger.warning(f"Variant not found: {variant_id} - continuing without variant targeting")
            except Exception as e:
                logger.warning(f"Failed to load variant {variant_id}: {e} - continuing without variant targeting")

        # Enhance product_dict with variant data if available
        if variant_data:
            product_dict['variant'] = variant_data
            # Append variant name to product name for ad copy (e.g., "All-in-One Superfood Shake - Brown Sugar")
            original_name = product_dict.get('name', 'Product')
            variant_name = variant_data.get('name', '')
            product_dict['display_name'] = f"{original_name} - {variant_name}" if variant_name else original_name
            logger.info(f"Enhanced product with variant: {product_dict['display_name']}")
        else:
            product_dict['variant'] = None
            product_dict['display_name'] = product_dict.get('name', 'Product')

        # STAGE 2d: Fetch brand fonts (ad_creation_notes column may not exist yet)
        combined_instructions = ""
        brand_id = product_dict.get('brand_id')
        brand_fonts = None  # Will be fetched below
        if brand_id:
            try:
                from viraltracker.core.database import get_supabase_client
                db = get_supabase_client()
                brand_result = db.table("brands").select("brand_fonts").eq("id", brand_id).single().execute()
                if brand_result.data:
                    if brand_result.data.get('brand_fonts'):
                        brand_fonts = brand_result.data['brand_fonts']
                        logger.info(f"Stage 2d: Loaded brand fonts: {brand_fonts.get('primary', 'N/A')}")
            except Exception as e:
                logger.warning(f"Failed to load brand data: {e}")

        # Append run-specific additional instructions
        if additional_instructions:
            if combined_instructions:
                combined_instructions = f"{combined_instructions}\n\n**Run-specific instructions:**\n{additional_instructions}"
            else:
                combined_instructions = additional_instructions
            logger.info(f"Combined instructions ready ({len(combined_instructions)} chars)")

        # Store combined instructions in product_dict for use in prompt generation
        product_dict['combined_instructions'] = combined_instructions if combined_instructions else None

        # STAGE 3: Fetch hooks (only if using hooks content source)
        hooks_list = []
        if content_source == "hooks":
            logger.info("Stage 3: Fetching hooks...")
            hooks_list = await get_hooks_for_product(
                ctx=ctx,
                product_id=product_id,
                limit=50,
                active_only=True
            )
        else:
            logger.info(f"Stage 3: Skipping hooks (using {content_source} mode)")

        # STAGE 4: Get ad brief template
        logger.info("Stage 4: Fetching ad brief template...")
        ad_brief_dict = await get_ad_brief_template(
            ctx=ctx,
            brand_id=product_dict.get('brand_id')
        )
        ad_brief_instructions = ad_brief_dict.get('instructions', '')

        # STAGE 5 & 6a: Check for cached template analysis (saves 4-8 minutes!)
        template_angle = None  # Will be set if using recreate_template
        used_cache = False

        if content_source == "recreate_template":
            # Check for cached analysis first
            logger.info("Stage 5: Checking for cached template analysis...")
            cached = await ctx.deps.ad_creation.get_cached_template_analysis(reference_ad_path)

            if cached:
                logger.info("✓ CACHE HIT! Using cached analysis (skipping 4-8 min of Opus 4.5 calls)")
                ad_analysis = cached["ad_analysis"]
                template_angle = cached["template_angle"]
                used_cache = True
            else:
                logger.info("✗ Cache miss - running full analysis...")

        if not used_cache:
            # STAGE 5: Analyze reference ad (expensive Opus 4.5 call)
            logger.info("Stage 5: Analyzing reference ad with Vision AI...")
            ad_analysis = await analyze_reference_ad(
                ctx=ctx,
                reference_ad_storage_path=reference_ad_path
            )

        # Save analysis to database (for this ad run)
        await ctx.deps.ad_creation.update_ad_run(
            ad_run_id=UUID(ad_run_id_str),
            ad_analysis=ad_analysis
        )

        # STAGE 6: Get content variations based on content_source
        if content_source == "hooks":
            # Original hooks-based flow
            logger.info(f"Stage 6: Selecting {num_variations} diverse hooks with AI...")
            if persona_data:
                logger.info(f"  Using persona '{persona_data.get('persona_name')}' for hook selection")
            selected_hooks = await select_hooks(
                ctx=ctx,
                hooks=hooks_list,
                ad_analysis=ad_analysis,
                product_name=product_dict.get('name', ''),
                target_audience=product_dict.get('target_audience', ''),
                count=num_variations,
                persona_data=persona_data
            )
        elif content_source == "recreate_template":
            # Recreate template flow
            if not used_cache:
                # Stage 6a only needed if we didn't get from cache
                logger.info("Stage 6a: Extracting template angle...")
                template_angle = await extract_template_angle(
                    ctx=ctx,
                    reference_ad_storage_path=reference_ad_path,
                    ad_analysis=ad_analysis
                )

                # Save to cache for future runs (async, don't wait)
                logger.info("Saving template analysis to cache for future use...")
                await ctx.deps.ad_creation.save_template_analysis(
                    storage_path=reference_ad_path,
                    ad_analysis=ad_analysis,
                    template_angle=template_angle
                )

            # Stage 6b: Generate benefit variations (always needed - product-specific)
            logger.info(f"Stage 6b: Generating {num_variations} benefit variations...")
            if persona_data:
                logger.info(f"  Using persona '{persona_data.get('persona_name')}' for benefit variations")
            selected_hooks = await generate_benefit_variations(
                ctx=ctx,
                product=product_dict,
                template_angle=template_angle,
                ad_analysis=ad_analysis,
                count=num_variations,
                persona_data=persona_data
            )

        elif content_source == "belief_first":
            # Belief-first mode: use provided angle's belief statement
            if not angle_data:
                raise ValueError("angle_data is required for belief_first content source")

            logger.info(f"Stage 6: Using belief-first mode with angle: {angle_data.get('name', 'Unknown')}")
            logger.info(f"  Belief: {angle_data.get('belief_statement', '')[:100]}...")

            # If match_template_structure is True, extract template and adapt beliefs
            template_angle = None
            if match_template_structure:
                logger.info("  → Match template structure enabled - extracting template...")
                template_angle = await extract_template_angle(
                    ctx=ctx,
                    reference_ad_storage_path=reference_ad_path,
                    ad_analysis=ad_analysis
                )
                logger.info(f"  Template type: {template_angle.get('angle_type', 'unknown')}")
                logger.info(f"  Template pattern: {template_angle.get('messaging_template', '')[:80]}...")

            # Generate variations using the angle's belief statement
            # Create hook-like structures from the angle data for each variation
            selected_hooks = []
            belief_text = angle_data.get("belief_statement", "")

            for i in range(num_variations):
                # If we have a template, adapt the belief to fit it
                if template_angle and match_template_structure:
                    logger.info(f"  Adapting belief to template (variation {i + 1})...")
                    adapted_text = await adapt_belief_to_template(
                        belief_statement=belief_text,
                        template_angle=template_angle,
                        product=product_dict,
                        variation_number=i + 1
                    )
                    logger.info(f"    → {adapted_text[:60]}...")
                    content_type = "belief_angle_templated"
                else:
                    adapted_text = belief_text
                    content_type = "belief_angle"

                selected_hooks.append({
                    "hook_id": angle_data.get("id", ""),
                    "hook_text": belief_text,
                    "adapted_text": adapted_text,
                    "angle_name": angle_data.get("name", ""),
                    "explanation": angle_data.get("explanation", ""),
                    "variation_number": i + 1,
                    "content_type": content_type
                })

            logger.info(f"Created {len(selected_hooks)} belief-based variations")

        # Save selected hooks/variations to database
        await ctx.deps.ad_creation.update_ad_run(
            ad_run_id=UUID(ad_run_id_str),
            selected_hooks=selected_hooks
        )

        # STAGE 7: Select product images
        logger.info(f"Stage 7: Selecting product images (mode: {image_selection_mode})...")
        logger.info(f"Fetching images for product_id: {product_id}")

        # Fetch product images from product_images table
        image_extensions = ('.jpg', '.jpeg', '.png', '.webp', '.gif')
        product_image_paths = []
        image_analyses = {}
        try:
            db = ctx.deps.ad_creation.supabase
            images_result = db.table("product_images").select(
                "storage_path, image_analysis, is_main"
            ).eq("product_id", product_id).order("is_main", desc=True).execute()

            logger.info(f"Query returned {len(images_result.data or [])} rows from product_images")

            for img in images_result.data or []:
                path = img.get('storage_path', '')
                # Only include actual image files (skip PDFs)
                if path.lower().endswith(image_extensions):
                    product_image_paths.append(path)
                    if img.get('image_analysis'):
                        image_analyses[path] = img['image_analysis']

            logger.info(f"Found {len(product_image_paths)} images, {len(image_analyses)} with analysis")
        except Exception as e:
            logger.error(f"Failed to fetch product images: {e}")
            raise ValueError(f"Could not fetch product images: {e}")

        # Validate we have images
        if not product_image_paths:
            raise ValueError(
                f"No images found for product {product_id}. "
                f"Please add images in Brand Manager before creating ads."
            )

        # Prepare manual selection if applicable
        manual_selection = None
        if image_selection_mode == "manual" and selected_image_paths:
            manual_selection = selected_image_paths[:2]  # Max 2 images
            logger.info(f"Using manually selected images: {manual_selection}")

        # Determine how many images to select
        # Auto mode: select up to 2 if available, manual mode: use what user selected
        if image_selection_mode == "auto":
            # Select up to 2 images in auto mode (if 2+ available)
            auto_count = min(2, len(product_image_paths))
            logger.info(f"Auto-select mode: will select {auto_count} image(s)")
        else:
            # Manual mode: use count from user selection
            auto_count = len(manual_selection) if manual_selection else 1

        selected_product_images = await select_product_images(
            ctx=ctx,
            product_image_paths=product_image_paths,
            ad_analysis=ad_analysis,
            count=auto_count,
            selection_mode=image_selection_mode,
            image_analyses=image_analyses,
            manual_selection=manual_selection
        )

        # Extract paths from selection results (1-2 images)
        selected_image_paths_final = [img["storage_path"] for img in selected_product_images]
        logger.info(f"Selected {len(selected_image_paths_final)} image(s):")
        for idx, img in enumerate(selected_product_images):
            logger.info(f"  Image {idx+1}: {img['storage_path']} (score: {img['match_score']:.2f})")

        # Update status
        await ctx.deps.ad_creation.update_ad_run(
            ad_run_id=UUID(ad_run_id_str),
            status="generating"
        )

        # STAGE 8-10: Generate ad variations (ONE AT A TIME)
        total_variations = len(selected_hooks)
        logger.info(f"Stage 8-10: Generating {total_variations} ad variations...")
        generated_ads_with_reviews = []

        # Get product_id once for structured naming (used for all variations)
        import uuid as uuid_module
        product_id_for_naming = await ctx.deps.ad_creation.get_product_id_for_run(UUID(ad_run_id_str))

        for i, selected_hook in enumerate(selected_hooks, start=1):
            logger.info(f"  → Generating variation {i}/{total_variations}...")

            try:
                # Generate prompt
                nano_banana_prompt = await generate_nano_banana_prompt(
                    ctx=ctx,
                    prompt_index=i,
                    selected_hook=selected_hook,
                    product=product_dict,
                    ad_analysis=ad_analysis,
                    ad_brief_instructions=ad_brief_instructions,
                    reference_ad_path=reference_ad_path,
                    product_image_paths=selected_image_paths_final,
                    color_mode=color_mode,
                    brand_colors=brand_colors,
                    brand_fonts=brand_fonts,
                    num_variations=num_variations
                )

                # Execute generation
                generated_ad = await execute_nano_banana(
                    ctx=ctx,
                    nano_banana_prompt=nano_banana_prompt
                )

                # Generate ad_id upfront for structured naming
                ad_uuid = uuid_module.uuid4()

                # Get canvas size from JSON prompt
                canvas_size = None
                json_prompt = nano_banana_prompt.get('json_prompt', {})
                if isinstance(json_prompt, dict):
                    style = json_prompt.get('style', {})
                    canvas_size = style.get('canvas_size', '1080x1080px')

                # Upload image to storage with structured naming
                storage_path, _ = await ctx.deps.ad_creation.upload_generated_ad(
                    ad_run_id=UUID(ad_run_id_str),
                    prompt_index=i,
                    image_base64=generated_ad['image_base64'],
                    product_id=product_id_for_naming,
                    ad_id=ad_uuid,
                    canvas_size=canvas_size
                )

                logger.info(f"  ✓ Variation {i} generated and uploaded: {storage_path}")

            except Exception as gen_error:
                # Generation failed for this variation - log and continue with others
                logger.error(f"  ✗ Generation failed for variation {i}: {str(gen_error)}")

                # Record the failure in results
                generated_ads_with_reviews.append({
                    "prompt_index": i,
                    "prompt": None,
                    "storage_path": None,
                    "claude_review": None,
                    "gemini_review": None,
                    "reviewers_agree": None,
                    "final_status": "generation_failed",
                    "error": str(gen_error)
                })
                continue  # Skip to next variation

            # STAGE 11-12: Dual AI Review
            logger.info(f"  → Reviewing variation {i} with Claude + Gemini...")

            # Claude review - with error handling
            claude_review = None
            claude_error = None
            try:
                claude_review = await review_ad_claude(
                    ctx=ctx,
                    storage_path=storage_path,
                    product_name=product_dict.get('name'),
                    hook_text=selected_hook.get('adapted_text'),
                    ad_analysis=ad_analysis
                )
            except Exception as e:
                claude_error = str(e)
                logger.warning(f"  ⚠️ Claude review failed for variation {i}: {claude_error}")
                claude_review = {
                    "reviewer": "claude",
                    "status": "review_failed",
                    "error": claude_error,
                    "product_accuracy": 0,
                    "text_accuracy": 0,
                    "layout_accuracy": 0,
                    "overall_quality": 0,
                    "notes": f"Review failed: {claude_error}"
                }

            # Gemini review - with error handling
            gemini_review = None
            gemini_error = None
            try:
                gemini_review = await review_ad_gemini(
                    ctx=ctx,
                    storage_path=storage_path,
                    product_name=product_dict.get('name'),
                    hook_text=selected_hook.get('adapted_text'),
                    ad_analysis=ad_analysis
                )
            except Exception as e:
                gemini_error = str(e)
                logger.warning(f"  ⚠️ Gemini review failed for variation {i}: {gemini_error}")
                gemini_review = {
                    "reviewer": "gemini",
                    "status": "review_failed",
                    "error": gemini_error,
                    "product_accuracy": 0,
                    "text_accuracy": 0,
                    "layout_accuracy": 0,
                    "overall_quality": 0,
                    "notes": f"Review failed: {gemini_error}"
                }

            # CRITICAL: Dual review logic with OR logic
            claude_status = claude_review.get('status', 'review_failed')
            gemini_status = gemini_review.get('status', 'review_failed')
            claude_approved = claude_status == 'approved'
            gemini_approved = gemini_status == 'approved'

            # Handle review failures gracefully
            if claude_status == 'review_failed' and gemini_status == 'review_failed':
                # Both reviews failed - flag for human review
                final_status = 'review_failed'
            elif claude_status == 'review_failed':
                # Only Claude failed - use Gemini's decision
                final_status = 'approved' if gemini_approved else gemini_status
            elif gemini_status == 'review_failed':
                # Only Gemini failed - use Claude's decision
                final_status = 'approved' if claude_approved else claude_status
            elif claude_approved or gemini_approved:
                # OR logic: either approving = approved
                final_status = 'approved'
            elif not claude_approved and not gemini_approved:
                final_status = 'rejected'  # Both rejected
            else:
                final_status = 'flagged'  # Disagreement

            # Check if reviewers agree (only if both succeeded)
            if claude_status != 'review_failed' and gemini_status != 'review_failed':
                reviewers_agree = (claude_approved == gemini_approved)
            else:
                reviewers_agree = None  # Can't compare if one failed

            logger.info(f"  ✓ Reviews complete: Claude={claude_review.get('status')}, "
                       f"Gemini={gemini_review.get('status')}, Final={final_status}")

            # Determine hook_id - None for benefit variations (recreate_template mode)
            # and for belief_first mode because they don't reference actual hooks in the database
            if content_source == "hooks":
                hook_id = UUID(selected_hook['hook_id'])
            else:
                hook_id = None  # Benefit-based and belief-first variations don't have real hook_ids

            # Update database with reviews and model metadata
            await ctx.deps.ad_creation.save_generated_ad(
                ad_run_id=UUID(ad_run_id_str),
                prompt_index=i,
                prompt_text=nano_banana_prompt['full_prompt'],
                prompt_spec=nano_banana_prompt.get('json_prompt', {}),
                hook_id=hook_id,
                hook_text=selected_hook['adapted_text'],
                storage_path=storage_path,
                claude_review=claude_review,
                gemini_review=gemini_review,
                final_status=final_status,
                # Model tracking metadata from generation
                model_requested=generated_ad.get('model_requested'),
                model_used=generated_ad.get('model_used'),
                generation_time_ms=generated_ad.get('generation_time_ms'),
                generation_retries=generated_ad.get('generation_retries', 0),
                ad_id=ad_uuid  # Use same ID as upload for consistency
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
        generation_failed_count = sum(1 for ad in generated_ads_with_reviews if ad['final_status'] == 'generation_failed')
        review_failed_count = sum(1 for ad in generated_ads_with_reviews if ad['final_status'] == 'review_failed')

        # Build summary
        content_source_labels = {
            "hooks": "hooks",
            "recreate_template": "template recreation (benefits/USPs)",
            "belief_first": f"belief-first angle: {angle_data.get('name', 'Unknown') if angle_data else 'Unknown'}"
        }
        content_source_label = content_source_labels.get(content_source, content_source)
        summary = f"""
Ad creation workflow completed for {product_dict.get('name')}.

**Content Source:** {content_source_label}

**Results:**
- Total ads requested: {num_variations}
- Approved (production-ready): {approved_count}
- Rejected (both reviewers): {rejected_count}
- Flagged (reviewer disagreement): {flagged_count}
- Generation failed: {generation_failed_count}
- Review failed: {review_failed_count}

**Next Steps:**
{f"- {approved_count} ads ready for immediate use" if approved_count > 0 else ""}
{f"- {flagged_count + review_failed_count} ads require human review" if (flagged_count + review_failed_count) > 0 else ""}
{f"- {rejected_count + generation_failed_count} ads should be regenerated" if (rejected_count + generation_failed_count) > 0 else ""}
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
            "content_source": content_source,
            "template_angle": template_angle,  # None if using hooks
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
# EXPORT TOOLS (17-18)
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
# PERSONA TOOLS (20)
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

logger.info("Ad Creation Agent initialized with 21 tools (includes email/slack export, size variants, persona tools)")
