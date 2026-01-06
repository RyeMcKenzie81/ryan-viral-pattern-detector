"""
CopyScaffoldService - LLM-powered copy generation with guardrails.

This service manages copy scaffolds (tokenized templates) for belief-first
ad generation. It handles:

- Scaffold retrieval by phase/scope
- LLM-based copy generation with character limits
- 40-character headline validation
- Guardrail enforcement (no discounts, medical claims, etc.)
- Copy set generation for angles

Copy is generated per-angle using Claude Opus 4.5 to ensure quality
and proper character limits. Scaffolds serve as patterns/inspiration.
"""

import os
import re
import json
import logging
from typing import List, Dict, Optional, Any
from uuid import UUID
from datetime import datetime

from ..core.config import Config
from pydantic_ai import Agent
import asyncio
from supabase import Client

from ..core.database import get_supabase_client
from .models import CopyScaffold, AngleCopySet

logger = logging.getLogger(__name__)

# Headline constraints
MAX_HEADLINE_CHARS = 40
MIN_HEADLINE_CHARS = 20

# Guardrail patterns (case-insensitive)
BANNED_PATTERNS = {
    "no_discount": [
        r"\d+%\s*off",
        r"save\s*\$?\d+",
        r"discount",
        r"sale",
        r"deal",
        r"limited\s*time",
        r"today\s*only",
        r"act\s*now",
        r"hurry",
        r"expires",
    ],
    "no_medical_claims": [
        r"cure",
        r"treat",
        r"heal",
        r"diagnose",
        r"prevent",
        r"clinically\s*proven",
        r"doctor\s*recommended",
        r"fda\s*approved",
        r"prescription",
        r"medicine",
        r"drug",
    ],
    "no_guarantees": [
        r"guarantee",
        r"money\s*back",
        r"100%\s*(effective|works|results)",
        r"risk\s*free",
        r"no\s*risk",
    ],
    "no_urgency": [
        r"last\s*chance",
        r"only\s*\d+\s*left",
        r"selling\s*fast",
        r"don't\s*miss",
        r"before\s*it's\s*gone",
    ],
}


class CopyScaffoldService:
    """Service for copy scaffold management and LLM-powered generation."""

    # Claude Opus 4.5 for high-quality copy
    DEFAULT_MODEL = "claude-opus-4-5-20251101"

    def __init__(self):
        """
        Initialize CopyScaffoldService.
        """
        self.supabase: Client = get_supabase_client()
        logger.info("CopyScaffoldService initialized")

    # ============================================
    # SCAFFOLD RETRIEVAL
    # ============================================

    def get_scaffolds_for_phase(
        self,
        phase_id: int,
        scope: Optional[str] = None,
        awareness_target: Optional[str] = None
    ) -> List[CopyScaffold]:
        """
        Get scaffolds eligible for a specific phase.

        Args:
            phase_id: Phase to get scaffolds for (1-6)
            scope: Filter by 'headline' or 'primary_text' (None = both)
            awareness_target: Filter by awareness level (e.g., 'problem-aware')

        Returns:
            List of eligible CopyScaffold objects
        """
        try:
            query = self.supabase.table("copy_scaffolds").select("*").eq(
                "is_active", True
            ).lte("phase_min", phase_id).gte("phase_max", phase_id)

            if scope:
                query = query.eq("scope", scope)

            result = query.execute()

            scaffolds = []
            for row in result.data or []:
                scaffold = CopyScaffold(
                    id=UUID(row["id"]),
                    scope=row["scope"],
                    name=row["name"],
                    template_text=row["template_text"],
                    phase_min=row.get("phase_min", 1),
                    phase_max=row.get("phase_max", 6),
                    awareness_targets=row.get("awareness_targets", []),
                    max_chars=row.get("max_chars"),
                    guardrails=row.get("guardrails"),
                    template_requirements=row.get("template_requirements"),
                    is_active=row.get("is_active", True)
                )

                # Filter by awareness target if specified
                if awareness_target:
                    if awareness_target not in scaffold.awareness_targets:
                        continue

                scaffolds.append(scaffold)

            logger.info(f"Retrieved {len(scaffolds)} scaffolds for phase {phase_id}")
            return scaffolds

        except Exception as e:
            logger.error(f"Failed to get scaffolds: {e}")
            return []

    def get_scaffold_by_id(self, scaffold_id: UUID) -> Optional[CopyScaffold]:
        """Get a specific scaffold by ID."""
        try:
            result = self.supabase.table("copy_scaffolds").select("*").eq(
                "id", str(scaffold_id)
            ).execute()

            if result.data:
                row = result.data[0]
                return CopyScaffold(
                    id=UUID(row["id"]),
                    scope=row["scope"],
                    name=row["name"],
                    template_text=row["template_text"],
                    phase_min=row.get("phase_min", 1),
                    phase_max=row.get("phase_max", 6),
                    awareness_targets=row.get("awareness_targets", []),
                    max_chars=row.get("max_chars"),
                    guardrails=row.get("guardrails"),
                    template_requirements=row.get("template_requirements"),
                    is_active=row.get("is_active", True)
                )
            return None
        except Exception as e:
            logger.error(f"Failed to get scaffold {scaffold_id}: {e}")
            return None

    # ============================================
    # TOKEN FILLING
    # ============================================

    def fill_scaffold_tokens(
        self,
        scaffold: CopyScaffold,
        context: Dict[str, str]
    ) -> Optional[str]:
        """
        Fill scaffold tokens with context values.

        Args:
            scaffold: The scaffold template
            context: Dict of token values, e.g., {"SYMPTOM_1": "joint stiffness"}

        Returns:
            Filled text, or None if required tokens missing
        """
        template_text = scaffold.template_text
        requirements = scaffold.template_requirements or {}
        required_tokens = requirements.get("required_tokens", [])

        # Check for required tokens
        for token in required_tokens:
            if token not in context or not context[token]:
                logger.warning(f"Missing required token: {token}")
                return None

        # Replace all tokens
        filled_text = template_text
        for token, value in context.items():
            placeholder = "{" + token + "}"
            filled_text = filled_text.replace(placeholder, value)

        # Check for unfilled tokens
        unfilled = re.findall(r"\{[A-Z_]+\}", filled_text)
        if unfilled:
            logger.warning(f"Unfilled tokens remaining: {unfilled}")

        return filled_text

    def get_required_tokens(self, scaffold: CopyScaffold) -> List[str]:
        """Get list of required tokens for a scaffold."""
        requirements = scaffold.template_requirements or {}
        return requirements.get("required_tokens", [])

    def extract_tokens_from_template(self, template_text: str) -> List[str]:
        """Extract all token placeholders from template text."""
        return re.findall(r"\{([A-Z_]+)\}", template_text)

    # ============================================
    # VALIDATION
    # ============================================

    def validate_headline_length(self, text: str) -> Dict[str, Any]:
        """
        Validate headline against 40-character limit.

        Args:
            text: Headline text to validate

        Returns:
            Dict with valid, length, message
        """
        length = len(text)
        valid = length <= MAX_HEADLINE_CHARS

        if length > MAX_HEADLINE_CHARS:
            message = f"Headline too long: {length}/{MAX_HEADLINE_CHARS} chars"
        elif length < MIN_HEADLINE_CHARS:
            message = f"Headline may be too short: {length} chars (target: {MIN_HEADLINE_CHARS}-{MAX_HEADLINE_CHARS})"
            valid = True  # Not invalid, just a warning
        else:
            message = f"Headline length OK: {length}/{MAX_HEADLINE_CHARS} chars"

        return {
            "valid": valid,
            "length": length,
            "max_length": MAX_HEADLINE_CHARS,
            "message": message
        }

    def validate_guardrails(
        self,
        text: str,
        guardrails: Dict[str, bool]
    ) -> Dict[str, Any]:
        """
        Validate text against guardrail patterns.

        Args:
            text: Text to validate
            guardrails: Dict of guardrails to check, e.g., {"no_discount": true}

        Returns:
            Dict with valid, violations list
        """
        violations = []
        text_lower = text.lower()

        for guardrail, enabled in guardrails.items():
            if not enabled:
                continue

            patterns = BANNED_PATTERNS.get(guardrail, [])
            for pattern in patterns:
                if re.search(pattern, text_lower):
                    violations.append({
                        "guardrail": guardrail,
                        "pattern": pattern,
                        "text": text
                    })
                    break  # One violation per guardrail is enough

        return {
            "valid": len(violations) == 0,
            "violations": violations
        }

    def validate_copy(
        self,
        text: str,
        scope: str,
        guardrails: Optional[Dict[str, bool]] = None
    ) -> Dict[str, Any]:
        """
        Full validation of generated copy.

        Args:
            text: Text to validate
            scope: 'headline' or 'primary_text'
            guardrails: Guardrail dict (defaults to phase 1-2 rules)

        Returns:
            Dict with valid, issues list
        """
        issues = []

        # Default Phase 1-2 guardrails
        if guardrails is None:
            guardrails = {
                "no_discount": True,
                "no_medical_claims": True,
                "no_guarantees": True
            }

        # Length validation for headlines
        if scope == "headline":
            length_result = self.validate_headline_length(text)
            if not length_result["valid"]:
                issues.append(length_result["message"])

        # Guardrail validation
        guardrail_result = self.validate_guardrails(text, guardrails)
        if not guardrail_result["valid"]:
            for v in guardrail_result["violations"]:
                issues.append(f"Violates {v['guardrail']}: matched '{v['pattern']}'")

        return {
            "valid": len(issues) == 0,
            "issues": issues
        }

    # ============================================
    # COPY SET GENERATION
    # ============================================

    def build_token_context(
        self,
        angle_id: UUID,
        product_id: Optional[UUID] = None,
        persona_id: Optional[UUID] = None,
        jtbd_id: Optional[UUID] = None
    ) -> Dict[str, str]:
        """
        Build token context from angle and related entities.

        Args:
            angle_id: The angle to build context for
            product_id: Optional product for PRODUCT_NAME
            persona_id: Optional persona for PERSONA_LABEL
            jtbd_id: Optional JTBD for JTBD token

        Returns:
            Dict of token values
        """
        context = {}

        try:
            # Get angle data
            # belief_angles columns: name, belief_statement, explanation, status
            angle_result = self.supabase.table("belief_angles").select(
                "name, belief_statement, explanation"
            ).eq("id", str(angle_id)).execute()

            if angle_result.data:
                angle = angle_result.data[0]
                # Full belief statement for LLM context
                context["ANGLE_CLAIM"] = angle.get("belief_statement", "")
                context["ANGLE_NAME"] = angle.get("name", "")

                # Explanation provides mechanism phrase
                explanation = angle.get("explanation", "")
                if explanation:
                    context["MECHANISM_PHRASE"] = explanation
                logger.info(f"Angle tokens: ANGLE_CLAIM='{context.get('ANGLE_CLAIM', '')[:50]}...'")

            # Get product data
            # products columns: name, description, target_audience, key_problems_solved, key_benefits, features
            if product_id:
                product_result = self.supabase.table("products").select(
                    "name, description, target_audience, key_problems_solved, key_benefits"
                ).eq("id", str(product_id)).execute()

                if product_result.data:
                    product = product_result.data[0]
                    context["PRODUCT_NAME"] = product.get("name", "")

                    # key_benefits is JSONB array - full value for LLM
                    key_benefits = product.get("key_benefits", []) or []
                    if key_benefits and len(key_benefits) > 0:
                        first_benefit = key_benefits[0]
                        context["BENEFIT_1"] = first_benefit if isinstance(first_benefit, str) else first_benefit.get("text", str(first_benefit))
                    else:
                        context["BENEFIT_1"] = "better daily comfort"
                        logger.warning(f"Product {product_id} has no key_benefits, using default")

                    # key_problems_solved is JSONB array - full values for LLM
                    problems = product.get("key_problems_solved", []) or []
                    if problems and len(problems) > 0:
                        first_problem = problems[0]
                        context["SYMPTOM_1"] = first_problem if isinstance(first_problem, str) else first_problem.get("text", str(first_problem))
                        if len(problems) > 1:
                            second_problem = problems[1]
                            context["SYMPTOM_2"] = second_problem if isinstance(second_problem, str) else second_problem.get("text", str(second_problem))
                        else:
                            context["SYMPTOM_2"] = context["SYMPTOM_1"]
                    else:
                        # Fallback: derive from target audience
                        target = product.get("target_audience", "") or ""
                        if "joint" in target.lower() or "mobil" in target.lower():
                            context["SYMPTOM_1"] = "joint stiffness"
                            context["SYMPTOM_2"] = "slower movement"
                        elif "dog" in target.lower() or "pet" in target.lower():
                            context["SYMPTOM_1"] = "slower movement"
                            context["SYMPTOM_2"] = "hesitation at stairs"
                        else:
                            context["SYMPTOM_1"] = "early signs of change"
                            context["SYMPTOM_2"] = "subtle shifts"
                        logger.warning(f"Product {product_id} has no key_problems_solved, using defaults")

                    logger.info(f"Product tokens: PRODUCT_NAME='{context.get('PRODUCT_NAME', '')}', SYMPTOM_1='{context.get('SYMPTOM_1', '')[:30]}...'")

            # Get persona data
            # personas_4d columns: name, pain_points (JSONB {emotional:[], social:[], functional:[]}), desires, snapshot
            if persona_id:
                persona_result = self.supabase.table("personas_4d").select(
                    "name, pain_points, snapshot"
                ).eq("id", str(persona_id)).execute()

                if persona_result.data:
                    persona = persona_result.data[0]
                    context["PERSONA_LABEL"] = persona.get("name", "")

                    # Extract common belief from pain_points JSONB - full value for LLM
                    pain_points = persona.get("pain_points", {}) or {}
                    common_belief = None

                    # Try emotional first, then functional, then social
                    for category in ["emotional", "functional", "social"]:
                        points = pain_points.get(category, []) or []
                        if points and len(points) > 0:
                            first_point = points[0]
                            common_belief = first_point if isinstance(first_point, str) else str(first_point)
                            break

                    if common_belief:
                        context["COMMON_BELIEF"] = common_belief
                    else:
                        # Fallback to snapshot or generic
                        snapshot = persona.get("snapshot", "")
                        if snapshot:
                            context["COMMON_BELIEF"] = snapshot.split(".")[0] if "." in snapshot else snapshot
                        else:
                            context["COMMON_BELIEF"] = "it's just part of getting older"
                        logger.warning(f"Persona {persona_id} has no pain_points, using fallback")

                    logger.info(f"Persona tokens: PERSONA_LABEL='{context.get('PERSONA_LABEL', '')}', COMMON_BELIEF='{context.get('COMMON_BELIEF', '')[:30]}...'")

            # Get JTBD data
            # belief_jtbd_framed columns: name, description, progress_statement, source
            if jtbd_id:
                jtbd_result = self.supabase.table("belief_jtbd_framed").select(
                    "name, progress_statement"
                ).eq("id", str(jtbd_id)).execute()

                if jtbd_result.data:
                    jtbd = jtbd_result.data[0]
                    context["JTBD"] = jtbd.get("progress_statement", "") or jtbd.get("name", "")
                    logger.debug(f"JTBD token: '{context.get('JTBD', '')[:30]}...'")

            # Default mechanism phrase if not set
            if "MECHANISM_PHRASE" not in context:
                context["MECHANISM_PHRASE"] = "targeted support"

            # Log all tokens for debugging
            logger.info(f"Built token context with {len(context)} tokens for angle {angle_id}")
            logger.info(f"  Available tokens: {list(context.keys())}")
            for key, value in context.items():
                if value:
                    logger.debug(f"  {key}: '{str(value)[:50]}...'")
                else:
                    logger.warning(f"  {key}: EMPTY/MISSING")

            return context

        except Exception as e:
            logger.error(f"Failed to build token context: {e}")
            return context

    def generate_copy_variants(
        self,
        scaffolds: List[CopyScaffold],
        context: Dict[str, str]
    ) -> List[Dict[str, Any]]:
        """
        Generate copy variants from scaffolds and context.

        Args:
            scaffolds: List of scaffolds to fill
            context: Token context values

        Returns:
            List of variant dicts: [{text, scaffold_id, tokens_used, valid, issues}]
        """
        variants = []

        for scaffold in scaffolds:
            filled_text = self.fill_scaffold_tokens(scaffold, context)

            if filled_text:
                # Validate the filled copy
                validation = self.validate_copy(
                    filled_text,
                    scaffold.scope,
                    scaffold.guardrails
                )

                variants.append({
                    "text": filled_text,
                    "scaffold_id": str(scaffold.id),
                    "scaffold_name": scaffold.name,
                    "tokens_used": {k: v for k, v in context.items() if "{" + k + "}" in scaffold.template_text},
                    "valid": validation["valid"],
                    "issues": validation["issues"]
                })

        return variants

    # ============================================
    # LLM-BASED COPY GENERATION
    # ============================================

    def generate_copy_with_llm(
        self,
        context: Dict[str, str],
        headline_scaffolds: List[CopyScaffold],
        primary_text_scaffolds: List[CopyScaffold],
        phase_id: int = 1
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Generate copy using Claude with explicit character limits.

        This method asks Claude to generate headlines and primary text
        that fit within character constraints while preserving meaning.

        Args:
            context: Token context with full values (angle, product, persona info)
            headline_scaffolds: Scaffold patterns for headline inspiration
            primary_text_scaffolds: Scaffold patterns for primary text inspiration
            phase_id: Phase for guardrail rules

        Returns:
            Dict with "headlines" and "primary_texts" lists
        """


        # Count scaffolds to determine how many variants to generate
        num_headlines = len(headline_scaffolds) if headline_scaffolds else 4
        num_primary_texts = len(primary_text_scaffolds) if primary_text_scaffolds else 2

        # Build scaffold examples for the prompt (include all selected scaffolds)
        headline_examples = "\n".join([
            f"- {s.name}: \"{s.template_text}\""
            for s in headline_scaffolds
        ]) if headline_scaffolds else "- Use observational, curiosity-driven headlines"

        primary_examples = "\n".join([
            f"- {s.name}: \"{s.template_text}\""
            for s in primary_text_scaffolds
        ]) if primary_text_scaffolds else "- Use empathy-led, problem-aware primary text"

        # Build the generation prompt
        prompt = f"""Generate ad copy by filling in the scaffold formulas below.

TOKEN VALUES (use these to fill the scaffolds):
- {{PRODUCT_NAME}}: {context.get('PRODUCT_NAME', 'the product')}
- {{PERSONA_LABEL}}: {context.get('PERSONA_LABEL', 'people')}
- {{ANGLE_CLAIM}}: {context.get('ANGLE_CLAIM', '')}
- {{SYMPTOM_1}}: {context.get('SYMPTOM_1', '')}
- {{SYMPTOM_2}}: {context.get('SYMPTOM_2', '')}
- {{COMMON_BELIEF}}: {context.get('COMMON_BELIEF', '')}
- {{BENEFIT_1}}: {context.get('BENEFIT_1', '')}
- {{JTBD}}: {context.get('JTBD', '')}
- {{MECHANISM_PHRASE}}: {context.get('MECHANISM_PHRASE', '')}

HEADLINE SCAFFOLD FORMULAS (follow these patterns, fill in tokens):
{headline_examples}

PRIMARY TEXT SCAFFOLD FORMULAS (follow these patterns, fill in tokens):
{primary_examples}

INSTRUCTIONS:
1. For each scaffold formula, replace the {{TOKEN}} placeholders with the values above
2. You may shorten/rephrase token values to fit character limits, but preserve the meaning
3. Headlines MUST be 40 characters or less (Meta hard limit) - shorten aggressively if needed
4. Primary text should be 2-3 sentences max
5. Phase {phase_id} rules: NO discounts, NO medical claims, NO guarantees, NO urgency
6. Keep the scaffold's tone and structure - don't invent new formats

Generate exactly {num_headlines} headlines (one per scaffold) and exactly {num_primary_texts} primary texts (one per scaffold).

OUTPUT FORMAT (JSON):
{{
    "headlines": [
        {{"text": "headline text here", "style": "observation|reframe|question|curiosity"}},
        ...
    ],
    "primary_texts": [
        {{"text": "primary text here", "style": "observation-reframe|problem-solution|empathy-lead"}},
        ...
    ]
}}

IMPORTANT: Every headline MUST be 40 characters or less. Count carefully."""

        # Pydantic AI Agent (CopyScaffold/Creative)
        agent = Agent(
            model=Config.get_model("copy_scaffold"),
            system_prompt="You are an expert copywriter. Return ONLY valid JSON."
        )

        try:
            result = agent.run_sync(prompt)
            content = result.output

            # Parse JSON from response
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                result_json = json.loads(json_match.group())

                # Convert to our variant format and validate
                headlines = []
                for i, h in enumerate(result_json.get("headlines", [])):
                    text = h.get("text", "")
                    validation = self.validate_copy(text, "headline")
                    headlines.append({
                        "text": text,
                        "scaffold_id": str(headline_scaffolds[i % len(headline_scaffolds)].id) if headline_scaffolds else None,
                        "scaffold_name": f"LLM-{h.get('style', 'generated')}",
                        "tokens_used": {},
                        "valid": validation["valid"],
                        "issues": validation["issues"],
                        "llm_generated": True
                    })

                primary_texts = []
                for i, p in enumerate(result_json.get("primary_texts", [])):
                    text = p.get("text", "")
                    validation = self.validate_copy(text, "primary_text")
                    primary_texts.append({
                        "text": text,
                        "scaffold_id": str(primary_text_scaffolds[i % len(primary_text_scaffolds)].id) if primary_text_scaffolds else None,
                        "scaffold_name": f"LLM-{p.get('style', 'generated')}",
                        "tokens_used": {},
                        "valid": validation["valid"],
                        "issues": validation["issues"],
                        "llm_generated": True
                    })

                logger.info(f"LLM generated {len(headlines)} headlines, {len(primary_texts)} primary texts")
                return {"headlines": headlines, "primary_texts": primary_texts}

            else:
                logger.error("Could not parse JSON from LLM response")
                return {
                    "headlines": self.generate_copy_variants(headline_scaffolds, context),
                    "primary_texts": self.generate_copy_variants(primary_text_scaffolds, context)
                }

        except Exception as e:
            logger.error(f"LLM copy generation failed: {e}")
            # Fallback to token filling
            return {
                "headlines": self.generate_copy_variants(headline_scaffolds, context),
                "primary_texts": self.generate_copy_variants(primary_text_scaffolds, context)
            }

    def generate_copy_set(
        self,
        angle_id: UUID,
        phase_id: int = 1,
        product_id: Optional[UUID] = None,
        persona_id: Optional[UUID] = None,
        jtbd_id: Optional[UUID] = None,
        offer_id: Optional[UUID] = None,
        brand_id: Optional[UUID] = None,
        headline_scaffold_ids: Optional[List[UUID]] = None,
        primary_text_scaffold_ids: Optional[List[UUID]] = None
    ) -> Optional[AngleCopySet]:
        """
        Generate a complete copy set for an angle.

        Args:
            angle_id: The angle to generate copy for
            phase_id: Phase (affects scaffold selection)
            product_id: Product for token context
            persona_id: Persona for token context
            jtbd_id: JTBD for token context
            offer_id: Offer reference
            brand_id: Brand reference
            headline_scaffold_ids: Specific headline scaffolds (None = use all eligible)
            primary_text_scaffold_ids: Specific primary text scaffolds (None = use all eligible)

        Returns:
            AngleCopySet with generated variants, or None on failure
        """
        try:
            # Build token context
            context = self.build_token_context(angle_id, product_id, persona_id, jtbd_id)

            # Get headline scaffolds
            if headline_scaffold_ids:
                headline_scaffolds = [
                    self.get_scaffold_by_id(sid) for sid in headline_scaffold_ids
                ]
                headline_scaffolds = [s for s in headline_scaffolds if s is not None]
            else:
                headline_scaffolds = self.get_scaffolds_for_phase(phase_id, scope="headline")

            # Get primary text scaffolds
            if primary_text_scaffold_ids:
                pt_scaffolds = [
                    self.get_scaffold_by_id(sid) for sid in primary_text_scaffold_ids
                ]
                pt_scaffolds = [s for s in pt_scaffolds if s is not None]
            else:
                pt_scaffolds = self.get_scaffolds_for_phase(phase_id, scope="primary_text")

            # Generate variants using LLM (falls back to token filling if no client)
            llm_result = self.generate_copy_with_llm(
                context=context,
                headline_scaffolds=headline_scaffolds,
                primary_text_scaffolds=pt_scaffolds,
                phase_id=phase_id
            )
            headline_variants = llm_result["headlines"]
            primary_text_variants = llm_result["primary_texts"]

            # Create copy set
            copy_set = AngleCopySet(
                brand_id=brand_id,
                product_id=product_id,
                offer_id=offer_id,
                persona_id=persona_id,
                jtbd_framed_id=jtbd_id,
                angle_id=angle_id,
                phase_id=phase_id,
                headline_variants=headline_variants,
                primary_text_variants=primary_text_variants,
                token_context=context,
                guardrails_validated=all(v["valid"] for v in headline_variants + primary_text_variants)
            )

            # Save to database
            self._save_copy_set(copy_set)

            logger.info(f"Generated copy set for angle {angle_id}: {len(headline_variants)} headlines, {len(primary_text_variants)} primary texts")
            return copy_set

        except Exception as e:
            logger.error(f"Failed to generate copy set: {e}")
            return None

    def _save_copy_set(self, copy_set: AngleCopySet) -> bool:
        """Save copy set to database."""
        try:
            data = {
                "brand_id": str(copy_set.brand_id) if copy_set.brand_id else None,
                "product_id": str(copy_set.product_id) if copy_set.product_id else None,
                "offer_id": str(copy_set.offer_id) if copy_set.offer_id else None,
                "persona_id": str(copy_set.persona_id) if copy_set.persona_id else None,
                "jtbd_framed_id": str(copy_set.jtbd_framed_id) if copy_set.jtbd_framed_id else None,
                "angle_id": str(copy_set.angle_id),
                "phase_id": copy_set.phase_id,
                "headline_variants": copy_set.headline_variants,
                "primary_text_variants": copy_set.primary_text_variants,
                "token_context": copy_set.token_context,
                "guardrails_validated": copy_set.guardrails_validated
            }

            # Upsert (one copy set per angle per phase)
            self.supabase.table("angle_copy_sets").upsert(
                data,
                on_conflict="angle_id,phase_id"
            ).execute()

            return True
        except Exception as e:
            logger.error(f"Failed to save copy set: {e}")
            return False

    # ============================================
    # RETRIEVAL
    # ============================================

    def get_copy_set_for_angle(
        self,
        angle_id: UUID,
        phase_id: int = 1
    ) -> Optional[AngleCopySet]:
        """
        Get existing copy set for an angle.

        Args:
            angle_id: Angle UUID
            phase_id: Phase to get copy for

        Returns:
            AngleCopySet or None if not generated
        """
        try:
            result = self.supabase.table("angle_copy_sets").select("*").eq(
                "angle_id", str(angle_id)
            ).eq("phase_id", phase_id).execute()

            if result.data:
                row = result.data[0]
                return AngleCopySet(
                    id=UUID(row["id"]),
                    brand_id=UUID(row["brand_id"]) if row.get("brand_id") else None,
                    product_id=UUID(row["product_id"]) if row.get("product_id") else None,
                    offer_id=UUID(row["offer_id"]) if row.get("offer_id") else None,
                    persona_id=UUID(row["persona_id"]) if row.get("persona_id") else None,
                    jtbd_framed_id=UUID(row["jtbd_framed_id"]) if row.get("jtbd_framed_id") else None,
                    angle_id=UUID(row["angle_id"]),
                    phase_id=row["phase_id"],
                    headline_variants=row.get("headline_variants", []),
                    primary_text_variants=row.get("primary_text_variants", []),
                    token_context=row.get("token_context"),
                    guardrails_validated=row.get("guardrails_validated", False)
                )
            return None
        except Exception as e:
            logger.error(f"Failed to get copy set: {e}")
            return None

    def get_copy_sets_for_plan(self, plan_id: UUID) -> List[AngleCopySet]:
        """
        Get all copy sets associated with a plan's angles.

        Args:
            plan_id: Plan UUID

        Returns:
            List of AngleCopySet for all angles in the plan
        """
        try:
            # Get plan's angle IDs
            plan_result = self.supabase.table("belief_plans").select(
                "angle_ids, phase_id"
            ).eq("id", str(plan_id)).execute()

            if not plan_result.data:
                return []

            plan = plan_result.data[0]
            angle_ids = plan.get("angle_ids", [])
            phase_id = plan.get("phase_id", 1)

            copy_sets = []
            for angle_id in angle_ids:
                copy_set = self.get_copy_set_for_angle(UUID(angle_id), phase_id)
                if copy_set:
                    copy_sets.append(copy_set)

            return copy_sets

        except Exception as e:
            logger.error(f"Failed to get copy sets for plan: {e}")
            return []
