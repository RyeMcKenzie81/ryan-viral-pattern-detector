"""
V2 Content Service - Hook selection, benefit variation, belief adaptation, image selection.

Extracted from ad_creation_agent.py tools:
- select_hooks (lines 630-875)
- generate_benefit_variations (lines 2514-3027)
- adapt_belief_to_template (lines 3030-3088)
- select_product_images (lines 894-989)
- _calculate_image_match_score (lines 992-1056)
- match_benefit_to_hook (lines 1060-1144)
"""

import json
import logging
import random
import re
from typing import Dict, List, Optional, Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


def _json_dumps(obj: Any, **kwargs) -> str:
    """JSON dumps with UUID serialization support."""
    return json.dumps(obj, default=lambda o: str(o) if isinstance(o, UUID) else TypeError(f"Not serializable: {type(o)}"), **kwargs)


class AdContentService:
    """Handles hook selection, benefit variations, and image selection for ad creation."""

    async def select_hooks(
        self,
        hooks: List[Dict[str, Any]],
        ad_analysis: Dict[str, Any],
        product_name: str = "",
        target_audience: str = "",
        count: int = 10,
        persona_data: Optional[Dict[str, Any]] = None,
        docs_service: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """
        Select diverse hooks using AI to maximize persuasive variety.

        Uses Claude to select hooks covering different persuasive categories,
        adapting each hook's text to match the reference ad style.

        Args:
            hooks: List of hook dicts from database
            ad_analysis: Ad analysis dict with format_type, authenticity_markers
            product_name: Product name for context
            target_audience: Product's target audience
            count: Number of hooks to select
            persona_data: Optional persona data for targeted selection
            docs_service: Optional DocService for knowledge base queries

        Returns:
            List of selected hook dicts with hook_id, text, category,
            framework, impact_score, reasoning, adapted_text
        """
        from pydantic_ai import Agent
        from viraltracker.core.config import Config

        logger.info(f"Selecting {count} diverse hooks from {len(hooks)} candidates")

        if not hooks:
            raise ValueError("hooks list cannot be empty")
        if count < 1 or count > 15:
            raise ValueError("count must be between 1 and 15")

        # Shuffle for variety across runs
        shuffled_hooks = hooks.copy()
        random.shuffle(shuffled_hooks)

        # Query knowledge base
        knowledge_context = ""
        if docs_service is not None:
            try:
                knowledge_results = docs_service.search(
                    f"hook writing techniques {target_audience} advertising",
                    limit=3,
                    tags=["hooks", "copywriting"]
                )
                if knowledge_results:
                    knowledge_sections = [f"### {r.title}\n{r.chunk_content}" for r in knowledge_results]
                    knowledge_context = "\n\n".join(knowledge_sections)
                    logger.info(f"Retrieved {len(knowledge_results)} knowledge base sections for hook selection")
            except Exception as e:
                logger.warning(f"Knowledge base query failed (continuing without): {e}")

        # Build prompt sections
        knowledge_section = ""
        if knowledge_context:
            knowledge_section = f"""
        **Copywriting Best Practices (from knowledge base):**
        {knowledge_context}

        Use these best practices to guide your hook selection and adaptation.
        """

        persona_section = ""
        if persona_data:
            persona_section = f"""
        **TARGET PERSONA: {persona_data.get('persona_name', 'Unknown')}**
        {persona_data.get('snapshot', '')}

        **Pain Points (prioritize hooks addressing these):**
        {_json_dumps(persona_data.get('pain_points', [])[:5], indent=2)}

        **Desires (what they want to achieve):**
        {_json_dumps(persona_data.get('desires', [])[:5], indent=2)}

        **Their Language (how they talk - adapt hooks to match):**
        {_json_dumps(persona_data.get('their_language', [])[:3], indent=2)}

        **Objections to Address:**
        {_json_dumps(persona_data.get('objections', [])[:3], indent=2)}

        **Amazon Testimonials (real customer voice - use similar language):**
        {_json_dumps(persona_data.get('amazon_testimonials', {}), indent=2) if persona_data.get('amazon_testimonials') else 'None available'}

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
        {_json_dumps(shuffled_hooks, indent=2)}

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

        hook_agent = Agent(
            model=Config.get_model("creative"),
            system_prompt="You are a persuasive copywriting expert. Return ONLY valid JSON."
        )

        max_retries = 3
        last_error = None

        for attempt in range(max_retries):
            try:
                result = await hook_agent.run(
                    selection_prompt + "\n\nReturn ONLY valid JSON array, no markdown fences, no other text."
                )
                result_text = result.output.strip()

                # Strip markdown code fences
                if result_text.startswith("```"):
                    result_text = result_text.split("\n", 1)[1] if "\n" in result_text else result_text[3:]
                    if result_text.endswith("```"):
                        result_text = result_text.rsplit("\n```", 1)[0]

                result_text = result_text.strip()
                selected_hooks = json.loads(result_text)

                logger.info(f"Selected {len(selected_hooks)} hooks with categories: "
                            f"{[h.get('category') for h in selected_hooks]}")
                return selected_hooks

            except json.JSONDecodeError as e:
                last_error = e
                logger.warning(f"Attempt {attempt + 1}/{max_retries} - JSON parse error: {e}")
                if attempt < max_retries - 1:
                    selection_prompt += "\n\nIMPORTANT: Ensure all JSON strings are properly escaped, no trailing commas, and valid JSON syntax."
                    continue
                else:
                    raise Exception(f"Failed to parse selection result after {max_retries} attempts: {e}")

    async def generate_benefit_variations(
        self,
        product: Dict[str, Any],
        template_angle: Dict[str, Any],
        ad_analysis: Dict[str, Any],
        count: int = 5,
        persona_data: Optional[Dict[str, Any]] = None,
        docs_service: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """
        Generate hook-like variations by applying the template angle to product benefits.

        Args:
            product: Product dict with benefits, unique_selling_points, etc.
            template_angle: Extracted angle from extract_template_angle()
            ad_analysis: Ad analysis dict
            count: Number of variations to generate (1-15)
            persona_data: Optional persona data for targeted copy
            docs_service: Optional DocService for knowledge base queries

        Returns:
            List of hook-like dicts with hook_id, text, category, framework,
            impact_score, reasoning, adapted_text
        """
        from pydantic_ai import Agent
        from viraltracker.core.config import Config

        logger.info(f"Generating {count} benefit variations using template angle")

        if count < 1 or count > 15:
            raise ValueError("count must be between 1 and 15")

        # Handle offer variant exclusive mode
        using_offer_variant = bool(product.get('offer_variant'))

        if using_offer_variant:
            benefits = product.get('offer_benefits', []) or []
            pain_points = product.get('offer_pain_points', []) or []
            offer_variant = product.get('offer_variant', {})
            mechanism = offer_variant.get('mechanism_of_action', '') or ''
            mechanism_name = offer_variant.get('mechanism_name', '') or ''

            all_content = benefits.copy()
            if mechanism:
                all_content.append(f"Works through: {mechanism}")
            if mechanism_name:
                all_content.append(f"The {mechanism_name}")

            logger.info(f"EXCLUSIVE offer variant mode: {len(benefits)} benefits, {len(pain_points)} pain points")
            if not all_content and not pain_points:
                raise ValueError("Offer variant has no benefits or pain points to use")
            if not all_content and pain_points:
                all_content = [f"Relief from: {pp}" for pp in pain_points[:5]]

            usps = []
            key_ingredients = []
        else:
            benefits = product.get('benefits', []) or []
            usps = product.get('unique_selling_points', []) or []
            key_ingredients = product.get('key_ingredients', []) or []
            all_content = benefits + usps + key_ingredients
            pain_points = product.get('offer_pain_points', [])

            if not all_content:
                raise ValueError("Product has no benefits, USPs, or key ingredients to use")

        # Shuffle for variety
        shuffled_content = all_content.copy()
        random.shuffle(shuffled_content)

        # Query knowledge base
        knowledge_context = ""
        if docs_service is not None:
            try:
                target_audience = product.get('target_audience', 'general audience')
                angle_type = template_angle.get('angle_type', 'benefit')
                knowledge_results = docs_service.search(
                    f"hook writing {angle_type} {target_audience} direct response advertising",
                    limit=3,
                    tags=["hooks", "copywriting"]
                )
                if knowledge_results:
                    knowledge_sections = [f"### {r.title}\n{r.chunk_content}" for r in knowledge_results]
                    knowledge_context = "\n\n".join(knowledge_sections)
                    logger.info(f"Retrieved {len(knowledge_results)} knowledge base sections for benefit variations")
            except Exception as e:
                logger.warning(f"Knowledge base query failed (continuing without): {e}")

        # Extract product metadata
        current_offer = product.get('current_offer', '')
        prohibited_claims = product.get('prohibited_claims', []) or []
        social_proof = product.get('social_proof', '')
        brand_name = product.get('brand_name', '')
        banned_terms = product.get('banned_terms', []) or []
        review_platforms = product.get('review_platforms', {}) or {}
        media_features = product.get('media_features', []) or []
        awards_certifications = product.get('awards_certifications', []) or []

        # Pre-extract offer variant data to avoid nested f-string escaping issues
        offer_variant = product.get('offer_variant') or {}
        offer_variant_name = offer_variant.get('name', '') if isinstance(offer_variant, dict) else ''
        offer_variant_label = offer_variant.get('name', 'Landing Page Angle') if isinstance(offer_variant, dict) else 'Landing Page Angle'
        offer_variant_angle = offer_variant.get('name', 'this specific angle') if isinstance(offer_variant, dict) else 'this specific angle'

        # Separate emotional benefits from technical specs
        emotional_benefits = benefits.copy() if benefits else []
        offer_pain_points = pain_points if using_offer_variant else product.get('offer_pain_points', [])

        emotional_usps = []
        technical_specs = []
        for usp in (usps or []):
            usp_lower = usp.lower()
            if any(term in usp_lower for term in ['cards', 'pages', 'included', 'app', 'guide', 'dictionary', 'guarantee', 'money-back']):
                technical_specs.append(usp)
            else:
                emotional_usps.append(usp)

        headline_content = emotional_benefits + emotional_usps
        if not headline_content:
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
        **Target Audience:** {product.get('offer_target_audience') if product.get('offer_target_audience') else ('General audience - see offer variant pain points below' if using_offer_variant else product.get('target_audience', 'General audience'))}

        **PRODUCT'S ACTUAL OFFER (USE THIS EXACTLY):**
        {current_offer if current_offer else "No specific offer - do not mention discounts or percentages"}

        **VERIFIED SOCIAL PROOF - USE ONLY THESE (CRITICAL - DO NOT INVENT):**

        Review Platforms (ONLY use these exact ratings/counts):
        {_json_dumps(review_platforms, indent=2) if review_platforms else "NONE - Do not mention Trustpilot, Amazon reviews, or any review platform"}

        Media Features ("As Seen On" / "Featured In" - ONLY use these):
        {_json_dumps(media_features) if media_features else "NONE - Do not mention any media outlets, TV shows, or publications"}

        Awards & Certifications (ONLY use these):
        {_json_dumps(awards_certifications) if awards_certifications else "NONE - Do not mention any awards or certifications"}

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
        {_json_dumps(prohibited_claims) if prohibited_claims else "None specified"}

        **BANNED COMPETITOR NAMES (NEVER USE - use "{brand_name}" instead):**
        {_json_dumps(banned_terms) if banned_terms else "None specified"}

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

        {f'''**CRITICAL: OFFER VARIANT OVERRIDE**
        An offer variant "{offer_variant_name}" has been selected.

        YOU MUST COMPLETELY IGNORE the template's TOPIC and SUBJECT MATTER above.
        - Do NOT write about: {template_angle.get('original_text', '')[:50]}...
        - The template's topic is IRRELEVANT - only use its LENGTH, TONE, and FORMAT
        - Your headlines must be 100% about the OFFER VARIANT topic below, NOT the template topic
        - If the template talks about blood pressure but the offer variant is about HAIR, write about HAIR
        - This is NON-NEGOTIABLE - the ad MUST match the landing page topic
        ''' if product.get('offer_variant') else ''}

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
        {_json_dumps(persona_data.get('pain_points', [])[:5], indent=2)}

        **Persona Desires (what they want to achieve):**
        {_json_dumps(persona_data.get('desires', [])[:5], indent=2)}

        **Transformation (before → after):**
        Before: {_json_dumps((persona_data.get('transformation') or {}).get('before', [])[:3])}
        After: {_json_dumps((persona_data.get('transformation') or {}).get('after', [])[:3])}

        **Their Language (how the persona talks - match this style):**
        {_json_dumps(persona_data.get('their_language', [])[:3], indent=2)}

        **Amazon Testimonials (real customer voice - use similar language):**
        {_json_dumps(persona_data.get('amazon_testimonials') or {}, indent=2) if persona_data.get('amazon_testimonials') else 'None available'}

        PERSONA INTEGRATION RULES:
        1. Frame headlines around the persona's specific pain points
        2. Use the transformation language (before → after) for emotional impact
        3. Match the persona's speaking style from "Their Language"
        4. If Amazon testimonials are available, borrow phrases for authenticity
        5. Address their objections implicitly in the headline when possible
        ''' if persona_data else (f'''**OFFER VARIANT: {offer_variant_label}**

        THIS IS THE ONLY TOPIC YOU CAN WRITE ABOUT. Everything else is off-limits.

        **ONLY USE THESE PAIN POINTS (from offer variant - matches landing page):**
        {_json_dumps(offer_pain_points[:8], indent=2) if offer_pain_points else 'None specified'}

        **ONLY USE THESE BENEFITS (from offer variant - matches landing page):**
        {_json_dumps(benefits[:8], indent=2) if benefits else 'None specified'}

        {f"**Target Audience:** {product.get('offer_target_audience', '')}" if product.get('offer_target_audience') else ''}

        **FORBIDDEN - DO NOT MENTION:**
        - Any pain points or benefits NOT listed above
        - Topics from the main product that don't match this offer variant
        - If this is a HAIR angle, do NOT mention: blood pressure, circulation, energy, blood vessels
        - If this is a BLOOD PRESSURE angle, do NOT mention: hair, thinning, shedding, scalp

        **REQUIRED:**
        1. EVERY headline must address pain points or benefits from the lists above
        2. If pain points mention "hair", "thinning", "shedding" → write about HAIR
        3. The landing page is about {offer_variant_angle} - your ad must match
        4. Ignore what the template was originally about - adapt the STRUCTURE only
        ''' if offer_pain_points or product.get('offer_variant') else '')}

        **EMOTIONAL BENEFITS (Use these for headlines - they connect with the audience):**
        {_json_dumps(headline_content, indent=2)}

        **TECHNICAL SPECS (Do NOT use these in headlines - too feature-focused):**
        {_json_dumps(technical_specs, indent=2) if technical_specs else "None"}

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

        variation_agent = Agent(
            model=Config.get_model("creative"),
            system_prompt="You are a persuasive copywriting expert. Return ONLY valid JSON."
        )

        max_retries = 3
        last_error = None

        for attempt in range(max_retries):
            try:
                result = await variation_agent.run(
                    generation_prompt + "\n\nReturn ONLY valid JSON array, no other text."
                )
                result_text = result.output.strip()

                # Strip markdown code fences
                if result_text.startswith("```"):
                    result_text = result_text.split("\n", 1)[1] if "\n" in result_text else result_text[3:]
                    if result_text.endswith("```"):
                        result_text = result_text.rsplit("\n```", 1)[0]

                result_text = result_text.strip()
                variations_raw = json.loads(result_text)

                # Convert to hook-like format
                variations = []
                for i, var in enumerate(variations_raw, start=1):
                    adapted_text = var.get('adapted_text', '')
                    adapted_text = _strip_markdown(adapted_text)
                    if banned_terms and brand_name:
                        adapted_text = _replace_banned_terms(adapted_text, banned_terms, brand_name)

                    variations.append({
                        "hook_id": str(uuid4()),
                        "text": var.get('original_benefit', ''),
                        "category": "benefit_variation",
                        "framework": f"Recreate Template ({template_angle.get('angle_type', 'unknown')})",
                        "impact_score": 15,
                        "reasoning": var.get('reasoning', ''),
                        "adapted_text": adapted_text
                    })

                # Validate for hallucinated content
                validation_issues = _validate_variations(
                    variations, current_offer, template_angle
                )

                if validation_issues and attempt < max_retries - 1:
                    issues_summary = "\n".join([
                        f"- Variation {v['index']+1}: {'; '.join(v['issues'])}"
                        for v in validation_issues
                    ])
                    logger.warning(f"Validation failed for {len(validation_issues)} variations:\n{issues_summary}")
                    generation_prompt += f"""

        **YOUR PREVIOUS ATTEMPT HAD THESE ISSUES - FIX THEM:**
        {issues_summary}

        Remember:
        - Only use the EXACT offer: "{current_offer if current_offer else 'NO OFFER'}"
        - Do NOT invent free gifts, scarcity numbers, time limits, or dollar amounts
        - Keep headlines around {len(template_angle.get('original_text', '').split())} words (±5 max)
        - Write like a top direct response copywriter - clear, punchy, persuasive
                    """
                    continue

                logger.info(f"Generated {len(variations)} benefit variations (validated)")
                return variations

            except json.JSONDecodeError as e:
                last_error = e
                logger.warning(f"Attempt {attempt + 1}/{max_retries} - JSON parse error: {e}")
                if attempt < max_retries - 1:
                    continue
                else:
                    raise Exception(f"Failed to parse variations after {max_retries} attempts: {e}")

        # Should not reach here, but just in case
        raise Exception(f"Failed to generate benefit variations after {max_retries} attempts")

    async def adapt_belief_to_template(
        self,
        belief_statement: str,
        template_angle: Dict[str, Any],
        product: Dict[str, Any],
        variation_number: int = 1,
    ) -> str:
        """
        Adapt a belief statement to match a template's structure/tone.

        Args:
            belief_statement: The core belief to communicate
            template_angle: Extracted template structure
            product: Product data for context
            variation_number: Which variation (for diversity)

        Returns:
            Headline text adapted to the template's style
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

    def select_product_images(
        self,
        product_image_paths: List[str],
        ad_analysis: Dict[str, Any],
        count: int = 1,
        selection_mode: str = "auto",
        image_analyses: Optional[Dict[str, Dict]] = None,
        manual_selection: Optional[List[str]] = None,
        image_asset_tags: Optional[Dict[str, List[str]]] = None,
        template_required_assets: Optional[List[str]] = None,
        template_optional_assets: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Select best product images matching reference ad format.

        Args:
            product_image_paths: List of storage paths to product images
            ad_analysis: Ad analysis dict
            count: Number of images to select
            selection_mode: "auto" or "manual"
            image_analyses: Dict mapping path -> analysis dict
            manual_selection: Paths if manual mode

        Returns:
            List of selection dicts with storage_path, match_score, match_reasons, analysis
        """
        logger.info(f"Selecting {count} product images ({selection_mode} mode)")

        if not product_image_paths:
            raise ValueError("product_image_paths cannot be empty")
        if count < 1:
            raise ValueError("count must be at least 1")

        # Manual mode
        if selection_mode == "manual" and manual_selection:
            results = []
            for path in manual_selection[:count]:
                analysis = (image_analyses or {}).get(path, {})
                results.append({
                    "storage_path": path,
                    "match_score": 1.0,
                    "match_reasons": ["User selected"],
                    "analysis": analysis
                })
            return results

        # Auto mode - score and rank
        scored_images = []
        image_analyses = image_analyses or {}

        for path in product_image_paths:
            analysis = image_analyses.get(path, {})
            score, reasons = _calculate_image_match_score(analysis, ad_analysis)

            if not analysis and "main" in path.lower():
                score = max(score, 0.6)
                reasons.append("Main product image (fallback)")

            # Phase 3: Asset tag matching bonus (when template elements available)
            if image_asset_tags and (template_required_assets or template_optional_assets):
                img_tags = set(image_asset_tags.get(path, []))
                required_set = set(template_required_assets or [])
                optional_set = set(template_optional_assets or [])

                if required_set:
                    required_overlap = len(img_tags & required_set) / len(required_set)
                    score += required_overlap * 0.3
                    if required_overlap > 0:
                        reasons.append(f"Required asset match: {required_overlap:.0%}")

                if optional_set:
                    optional_overlap = len(img_tags & optional_set) / len(optional_set)
                    score += optional_overlap * 0.1
                    if optional_overlap > 0:
                        reasons.append(f"Optional asset match: {optional_overlap:.0%}")

            scored_images.append({
                "storage_path": path,
                "match_score": min(score, 1.0),
                "match_reasons": reasons,
                "analysis": analysis
            })

        scored_images.sort(key=lambda x: x["match_score"], reverse=True)
        selected = scored_images[:count]
        logger.info(f"Selected {len(selected)} images. Top score: {selected[0]['match_score']:.2f}")
        return selected


def match_benefit_to_hook(
    hook: Dict[str, Any],
    benefits: List[str],
    unique_selling_points: Optional[List[str]] = None,
) -> str:
    """
    Select the most relevant product benefit/USP for a given hook.

    Combines both benefits and USPs, then scores by keyword overlap.
    """
    combined_items = []
    if unique_selling_points:
        combined_items.extend(unique_selling_points)
    if benefits:
        combined_items.extend(benefits)

    if not combined_items:
        return ""
    if len(combined_items) == 1:
        return combined_items[0]

    hook_text = str(hook.get('adapted_text', '') or hook.get('text', '')).lower()
    hook_category = str(hook.get('category', '')).lower()

    category_keywords = {
        'before_after': ['transform', 'change', 'improve', 'better', 'result', 'difference'],
        'social_proof': ['trust', 'proven', 'recommend', 'love', 'works', 'effective'],
        'authority': ['expert', 'professional', 'quality', 'premium', 'science', 'research'],
        'scarcity': ['limited', 'exclusive', 'special', 'unique', 'rare'],
        'urgency': ['now', 'today', 'fast', 'quick', 'immediate', 'soon'],
        'pain_point': ['problem', 'issue', 'struggle', 'pain', 'suffering', 'discomfort'],
        'aspiration': ['goal', 'dream', 'want', 'desire', 'wish', 'achieve']
    }

    hook_words = set(hook_text.split())
    if hook_category in category_keywords:
        hook_words.update(category_keywords[hook_category])

    best_item = combined_items[0]
    best_score = 0

    for item in combined_items:
        item_lower = item.lower()
        item_words = set(item_lower.split())
        overlap = len(hook_words & item_words)
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


def _calculate_image_match_score(
    image_analysis: Dict[str, Any], ad_analysis: Dict[str, Any]
) -> tuple:
    """Calculate how well a product image matches reference ad style."""
    if not image_analysis:
        return 0.5, ["No analysis available - using default score"]

    score = 0.0
    reasons = []

    quality = image_analysis.get("quality_score", 0.5)
    score += quality * 0.2
    if quality >= 0.8:
        reasons.append(f"High quality ({quality:.2f})")

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

    lighting = image_analysis.get("lighting_type", "unknown")
    if lighting in ["studio", "natural_soft"]:
        score += 0.2
        reasons.append(f"Good lighting ({lighting})")
    elif lighting != "unknown":
        score += 0.1

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

    if image_analysis.get("product_centered", False):
        score += 0.05
        reasons.append("Product centered")
    if image_analysis.get("product_fully_visible", True):
        score += 0.05

    return min(score, 1.0), reasons


def _strip_markdown(text: str) -> str:
    """Remove markdown formatting like *bold* and _italic_ from text."""
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'__(.+?)__', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'(?<!\w)_(.+?)_(?!\w)', r'\1', text)
    return text


def _replace_banned_terms(text: str, banned: List[str], brand: str) -> str:
    """Replace banned competitor names with brand name (case-insensitive)."""
    result = text
    for term in banned:
        if term and brand:
            pattern = re.compile(re.escape(term), re.IGNORECASE)
            result = pattern.sub(brand, result)
    return result


def _validate_variations(
    variations: List[Dict[str, Any]],
    current_offer: str,
    template_angle: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Validate variations for hallucinated content."""
    validation_issues = []
    original_word_count = len(template_angle.get('original_text', '').split())

    for i, var in enumerate(variations):
        adapted = var.get('adapted_text', '').lower()
        issues = []

        offer_lower = (current_offer or '').lower()

        if 'free gift' in adapted or 'free bonus' in adapted or 'free ' in adapted:
            if 'free' not in offer_lower:
                issues.append("mentions 'free gifts/bonus' but product offer doesn't include free items")

        scarcity_patterns = re.findall(r'\b(\d+)\s*(owners?|customers?|people|buyers?|spots?)\b', adapted)
        if scarcity_patterns:
            issues.append(f"contains invented scarcity numbers: {scarcity_patterns}")

        time_limits = ['this week', 'this weekend', 'today only', 'until midnight', 'next 24 hours',
                       'limited time', 'ends soon', 'last chance', 'hurry', 'act now', 'for black friday']
        for limit in time_limits:
            if limit in adapted and limit not in offer_lower:
                issues.append(f"contains invented time limit: '{limit}'")
                break

        dollar_amounts = re.findall(r'\$\d+', adapted)
        for amount in dollar_amounts:
            if amount not in (current_offer or ''):
                issues.append(f"contains invented dollar amount: {amount}")
                break

        adapted_word_count = len(var.get('adapted_text', '').split())
        if original_word_count > 0 and abs(adapted_word_count - original_word_count) > 8:
            issues.append(f"too long: {adapted_word_count} words vs original {original_word_count} words")

        if issues:
            validation_issues.append({
                "index": i,
                "adapted_text": var.get('adapted_text', ''),
                "issues": issues
            })

    return validation_issues
