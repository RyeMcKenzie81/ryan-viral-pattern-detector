"""
ImageStrategyService — 2-step Image Strategy Pipeline for blueprint images.

Replaces the single-shot Scene Director with:
  Step 1: Visual Playbook (Sonnet, cached per product) — product visual language
  Step 2: Page Narrative Director (Opus, per blueprint) — per-slot briefs with self-QA

Deterministic QA validation runs after Step 2 to catch rule violations.
"""

import hashlib
import json
import logging
from collections import Counter
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class ImageStrategyService:
    """2-step Image Strategy Pipeline for blueprint images."""

    def __init__(self, supabase=None, org_id=None):
        if supabase is None:
            from viraltracker.core.database import get_supabase_client
            supabase = get_supabase_client()
        self._supabase = supabase
        self._org_id = org_id
        self._tracker = None
        self._user_id: Optional[str] = None

    def set_tracking_context(self, tracker, user_id: Optional[str], org_id: str):
        """Set usage tracking context for billing."""
        self._tracker = tracker
        self._user_id = user_id
        self._org_id = org_id

    # ------------------------------------------------------------------
    # Step 1: Visual Playbook (cached per product)
    # ------------------------------------------------------------------

    async def get_or_create_visual_playbook(
        self, product_id: str, brand_profile: dict
    ) -> dict:
        """Load cached playbook or generate a new one (Sonnet).

        Returns the playbook dict. Caches in product_visual_playbooks table.
        """
        cached = self._load_visual_playbook(product_id)
        current_hash = self._hash_brand_profile(brand_profile)

        if cached and cached.get("brand_profile_hash") == current_hash:
            logger.info(f"Using cached visual playbook for product {product_id}")
            return cached["playbook"]

        logger.info(f"Generating new visual playbook for product {product_id}")
        try:
            playbook = await self._generate_visual_playbook(brand_profile)
            self._save_visual_playbook(product_id, playbook, current_hash)
            return playbook
        except Exception as e:
            logger.error(f"Failed to generate visual playbook: {e}")
            # Build a minimal default playbook from brand profile
            return self._build_default_playbook(brand_profile)

    def _load_visual_playbook(self, product_id: str) -> Optional[dict]:
        """Load cached playbook from DB."""
        try:
            result = (
                self._supabase.table("product_visual_playbooks")
                .select("playbook, brand_profile_hash")
                .eq("product_id", str(product_id))
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as e:
            logger.warning(f"Failed to load cached playbook: {e}")
            return None

    def _save_visual_playbook(
        self, product_id: str, playbook: dict, profile_hash: str
    ):
        """Upsert playbook to DB."""
        try:
            self._supabase.table("product_visual_playbooks").upsert(
                {
                    "product_id": str(product_id),
                    "organization_id": str(self._org_id),
                    "playbook": playbook,
                    "brand_profile_hash": profile_hash,
                    "model_used": "sonnet",
                },
                on_conflict="product_id",
            ).execute()
        except Exception as e:
            logger.warning(f"Failed to save visual playbook: {e}")

    async def _generate_visual_playbook(self, brand_profile: dict) -> dict:
        """Generate playbook via Sonnet."""
        from pydantic_ai import Agent
        from pydantic_ai.settings import ModelSettings
        from viraltracker.core.config import Config
        from viraltracker.services.agent_tracking import run_agent_with_tracking
        from viraltracker.services.landing_page_analysis.prompts.image_strategy import (
            VISUAL_PLAYBOOK_SYSTEM_PROMPT,
        )

        compact_profile = self._compact_brand_profile(brand_profile)
        user_content = (
            "## Brand Profile\n\n"
            f"```json\n{json.dumps(compact_profile, indent=2, default=str)}\n```"
        )

        model = Config.get_model("default")  # Sonnet
        agent = Agent(
            model=model,
            system_prompt=VISUAL_PLAYBOOK_SYSTEM_PROMPT,
            model_settings=ModelSettings(max_tokens=4096, temperature=0.3),
        )

        result = await run_agent_with_tracking(
            agent,
            user_content,
            tracker=self._tracker,
            user_id=self._user_id,
            organization_id=self._org_id,
            tool_name="image_strategy",
            operation="visual_playbook",
        )

        return self._parse_json(result.output)

    def _build_default_playbook(self, brand_profile: dict) -> dict:
        """Build a minimal playbook deterministically from brand profile fields."""
        product = brand_profile.get("product", {})
        personas = brand_profile.get("personas", [])
        persona = personas[0] if personas else {}

        return {
            "visual_archetype": "transformation",
            "product_physical_form": {
                "description": product.get("description", ""),
                "visual_cues": [],
                "packaging_style": "standard",
            },
            "customer_world": {
                "before_state": {
                    "settings": ["dimly-lit room", "cluttered desk"],
                    "body_language": ["hunched shoulders", "tired expression"],
                    "color_palette": "desaturated, cool tones",
                },
                "after_state": {
                    "settings": ["sunlit room", "outdoor setting"],
                    "body_language": ["upright posture", "natural smile"],
                    "color_palette": "warm, vibrant tones",
                },
            },
            "transformation_visuals": {
                "key_moments": [],
                "visual_metaphors": [],
            },
            "trust_visual_language": {
                "authority_signals": [],
                "certifications": [],
                "style": "clean, professional",
            },
            "settings_that_resonate": [
                "Modern home",
                "Outdoor nature setting",
                "Kitchen",
                "Office",
            ],
            "never_show": ["Competitor products", "Clinical hospital settings"],
            "demographic_guide": {
                "primary": persona.get("demographics", {}).get("age_range", "Adults"),
                "diversity_notes": "Mix of ethnicities, relatable",
            },
            "brand_visual_identity": {
                "color_palette": [],
                "photography_style": "Natural lifestyle photography",
                "lighting_preference": "Natural daylight, soft diffused",
                "mood_spectrum": ["confident", "hopeful", "relieved"],
            },
        }

    # ------------------------------------------------------------------
    # Step 2: Page Narrative Director + Deterministic QA
    # ------------------------------------------------------------------

    async def run_narrative_and_validate(
        self,
        slots: list,
        playbook: dict,
        brand_profile: dict,
        persona: Optional[dict],
        blueprint_sections: Optional[list],
        progress_cb: Optional[Callable] = None,
    ) -> None:
        """Step 2 + deterministic QA. Mutates slots in-place."""
        if progress_cb:
            progress_cb(0, 1, "Directing page narrative...")

        try:
            briefs = await self._direct_page_narrative(
                slots, playbook, brand_profile, persona, blueprint_sections
            )
        except Exception as e:
            logger.error(f"Narrative director failed: {e}", exc_info=True)
            return

        passed, violations = self._validate_briefs(briefs, playbook)
        if not passed:
            logger.warning(f"QA violations ({len(violations)}): {violations}")
            if progress_cb:
                progress_cb(0, 1, "Refining narrative (QA retry)...")
            briefs = await self._direct_page_narrative(
                slots,
                playbook,
                brand_profile,
                persona,
                blueprint_sections,
                qa_feedback="\n".join(violations),
            )
            # Run QA again for logging but accept result regardless
            passed2, violations2 = self._validate_briefs(briefs, playbook)
            if not passed2:
                logger.warning(f"Post-retry QA violations: {violations2}")

        # Apply briefs to slots
        index_map = {s.index: s for s in slots}
        applied = 0
        for brief in briefs:
            idx = brief.get("slot_index")
            # Coerce string indices to int (LLMs sometimes return "0" instead of 0)
            if isinstance(idx, str):
                try:
                    idx = int(idx)
                except (ValueError, TypeError):
                    continue
            if idx is not None and idx in index_map:
                if brief.get("action") != "skip":
                    index_map[idx].scene_direction = brief
                    applied += 1
        logger.info(
            f"Applied {applied}/{len(briefs)} briefs to {len(slots)} slots"
        )

    async def _direct_page_narrative(
        self,
        slots: list,
        playbook: dict,
        brand_profile: dict,
        persona: Optional[dict],
        blueprint_sections: Optional[list],
        qa_feedback: Optional[str] = None,
    ) -> list:
        """Run the Opus narrative director."""
        from pydantic_ai import Agent
        from pydantic_ai.settings import ModelSettings
        from viraltracker.core.config import Config
        from viraltracker.services.agent_tracking import run_agent_with_tracking
        from viraltracker.services.landing_page_analysis.prompts.image_strategy import (
            PAGE_NARRATIVE_SYSTEM_PROMPT,
        )

        # Build system prompt with optional QA feedback
        qa_section = ""
        if qa_feedback:
            qa_section = (
                "## IMPORTANT: Previous QA Violations\n\n"
                "Your previous attempt had these violations. Fix ALL of them:\n"
                f"{qa_feedback}\n\n"
                "Revise your assignments to resolve every violation listed above."
            )
        system_prompt = PAGE_NARRATIVE_SYSTEM_PROMPT.replace(
            "{qa_feedback_section}", qa_section
        )

        # Build user content
        user_parts = []

        # Playbook summary
        user_parts.append("## Visual Playbook\n")
        user_parts.append(f"```json\n{json.dumps(playbook, indent=2, default=str)}\n```\n")

        # Blueprint sections (compact)
        if blueprint_sections:
            compact = self._compact_sections(blueprint_sections)
            user_parts.append("## Page Sections (conversion flow order)\n")
            user_parts.append(
                f"```json\n{json.dumps(compact, indent=2, default=str)}\n```\n"
            )

        # Persona demographics
        if persona:
            demographics = persona.get("demographics", {})
            pain_points = persona.get("pain_points", [])[:5]
            persona_summary = {
                "name": persona.get("name", ""),
                "age_range": demographics.get("age_range", ""),
                "gender": demographics.get("gender", ""),
                "pain_points": pain_points,
            }
            user_parts.append("## Target Persona\n")
            user_parts.append(
                f"```json\n{json.dumps(persona_summary, indent=2, default=str)}\n```\n"
            )

        # Slot details
        user_parts.append("## Image Slots to Direct\n")
        for slot in slots:
            analysis = slot.image_analysis or {}
            slot_info = {
                "slot_index": slot.index,
                "section_heading": slot.section_heading or "",
                "surrounding_text": (slot.surrounding_text or "")[:300],
                "alt_text": slot.alt_text or "",
                "aspect_ratio": slot.aspect_ratio or analysis.get("aspect_ratio", ""),
                "has_people": analysis.get("has_people", False),
                "image_type": analysis.get("image_type", ""),
            }
            user_parts.append(
                f"### Slot {slot.index}\n"
                f"```json\n{json.dumps(slot_info, indent=2, default=str)}\n```\n"
            )

        user_content = "\n".join(user_parts)

        model = Config.get_model("complex")  # Opus
        agent = Agent(
            model=model,
            system_prompt=system_prompt,
            model_settings=ModelSettings(max_tokens=8192, temperature=0.4),
        )

        result = await run_agent_with_tracking(
            agent,
            user_content,
            tracker=self._tracker,
            user_id=self._user_id,
            organization_id=self._org_id,
            tool_name="image_strategy",
            operation="narrative_director",
        )

        logger.info(
            f"Narrative director response length: {len(result.output)} chars"
        )
        parsed = self._parse_json(result.output)
        logger.info(
            f"Parsed narrative briefs: type={type(parsed).__name__}, "
            f"count={len(parsed) if isinstance(parsed, list) else 'N/A'}"
        )
        # Ensure it's a list
        if isinstance(parsed, dict):
            # Might be wrapped in a key
            for key in ("briefs", "slots", "images", "results"):
                if key in parsed and isinstance(parsed[key], list):
                    return parsed[key]
            return [parsed]
        return parsed if isinstance(parsed, list) else []

    # ------------------------------------------------------------------
    # Deterministic QA Validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_briefs(briefs: list, playbook: dict) -> Tuple[bool, List[str]]:
        """Validate briefs against deterministic rules.

        Returns (passed, violations).
        """
        violations = []
        generate_briefs = [b for b in briefs if b.get("action") != "skip"]

        if not generate_briefs:
            return (True, [])

        # 1. Setting redundancy
        settings = [b.get("setting", "") for b in generate_briefs if b.get("setting")]
        setting_dupes = {s for s in settings if settings.count(s) > 1}
        if setting_dupes:
            violations.append(f"Duplicate settings found: {setting_dupes}")

        # 2. Activity redundancy
        activities = [
            b.get("activity", "") for b in generate_briefs if b.get("activity")
        ]
        activity_dupes = {a for a in activities if activities.count(a) > 1}
        if activity_dupes:
            violations.append(f"Duplicate activities found: {activity_dupes}")

        # 3. Role distribution — need at least 3 distinct roles (or all if fewer slots)
        roles = [b.get("narrative_role", "") for b in generate_briefs]
        min_roles = min(3, len(generate_briefs))
        if len(set(roles)) < min_roles:
            role_counts = Counter(roles).most_common(3)
            violations.append(
                f"Poor role distribution — only {len(set(roles))} distinct roles "
                f"(need {min_roles}): {role_counts}"
            )

        # 4. Product visibility balance — should be 30-70%
        show_count = sum(1 for b in generate_briefs if b.get("show_product"))
        total = len(generate_briefs)
        if total > 2:
            ratio = show_count / total
            if ratio > 0.7:
                violations.append(
                    f"Too many show_product=true ({show_count}/{total} = {ratio:.0%}). "
                    f"Target: 30-50%."
                )

        # 5. Never-show compliance
        never_show = playbook.get("never_show", [])
        for b in generate_briefs:
            combined = (
                b.get("scene_description", "") + " " + b.get("setting", "")
            ).lower()
            for term in never_show:
                if term.lower() in combined:
                    violations.append(
                        f"Slot {b.get('slot_index')}: contains '{term}' "
                        f"which is in the never_show list"
                    )

        return (len(violations) == 0, violations)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compact_sections(sections: list) -> list:
        """Truncate blueprint sections to fit token budget.

        Extracts nested brand_mapping fields, drops heavy analysis fields.
        """
        compact = []
        for s in sections or []:
            bm = s.get("brand_mapping", {})
            compact.append(
                {
                    "flow_order": s.get("flow_order"),
                    "section_name": s.get("section_name"),
                    "emotional_hook": bm.get("emotional_hook", ""),
                    "primary_content": bm.get("primary_content", "")[:200],
                    "copy_direction": s.get("copy_direction", "")[:200],
                }
            )
        return compact

    @staticmethod
    def _compact_brand_profile(brand_profile: dict) -> dict:
        """Truncate brand profile for Step 1 input (~8K tokens)."""
        compact = {}

        # Product — include fully
        compact["product"] = brand_profile.get("product", {})

        # Mechanism — include fully
        compact["mechanism"] = brand_profile.get("mechanism", {})

        # Personas — first 3, trim to essentials
        personas = brand_profile.get("personas", [])[:3]
        compact["personas"] = []
        for p in personas:
            compact["personas"].append(
                {
                    "name": p.get("name", ""),
                    "demographics": p.get("demographics", {}),
                    "pain_points": p.get("pain_points", [])[:5],
                    "desired_self_image": p.get("desired_self_image", ""),
                }
            )

        # Social proof — truncated
        social_proof = brand_profile.get("social_proof", {})
        compact["social_proof"] = {
            "quotes": social_proof.get("quotes", [])[:10],
            "stats": social_proof.get("stats", [])[:5],
        }

        # Competitors — max 5, truncated
        competitors = brand_profile.get("competitors", [])[:5]
        compact["competitors"] = []
        for c in competitors:
            compact["competitors"].append(
                {
                    "name": c.get("name", ""),
                    "ump": str(c.get("ump", ""))[:200],
                    "ums": str(c.get("ums", ""))[:200],
                }
            )

        # Brand colors if present
        if brand_profile.get("brand_colors"):
            compact["brand_colors"] = brand_profile["brand_colors"]

        return compact

    @staticmethod
    def _hash_brand_profile(brand_profile: dict) -> str:
        """Hash only visually-relevant subset for cache invalidation."""
        relevant = {
            "product": brand_profile.get("product", {}),
            "mechanism": brand_profile.get("mechanism", {}),
            "personas": brand_profile.get("personas", [])[:5],
            "social_proof": brand_profile.get("social_proof", {}),
        }
        return hashlib.sha256(
            json.dumps(relevant, sort_keys=True, default=str).encode()
        ).hexdigest()

    @staticmethod
    def _parse_json(text: str) -> Any:
        """Parse JSON from LLM response, handling markdown fences and arrays."""
        clean = text.strip()
        # Strip markdown code fences
        if clean.startswith("```"):
            lines = clean.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            clean = "\n".join(lines).strip()

        try:
            return json.loads(clean)
        except json.JSONDecodeError:
            pass

        # Try extracting JSON array
        start_arr = clean.find("[")
        end_arr = clean.rfind("]")
        if start_arr != -1 and end_arr != -1 and end_arr > start_arr:
            try:
                return json.loads(clean[start_arr : end_arr + 1])
            except json.JSONDecodeError:
                pass

        # Try extracting JSON object
        start_obj = clean.find("{")
        end_obj = clean.rfind("}")
        if start_obj != -1 and end_obj != -1 and end_obj > start_obj:
            try:
                return json.loads(clean[start_obj : end_obj + 1])
            except json.JSONDecodeError:
                pass

        raise ValueError(f"Could not parse JSON from LLM response: {clean[:200]}...")
