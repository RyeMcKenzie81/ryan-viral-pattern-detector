"""
AngleGeneratorService - strategy-first angle generation for the
angle-driven ad creator V1.

Takes (persona, offer_variant, landing_page_url) and produces N=5 belief-level
strategic angles via Claude Opus 4.7. Produces in-memory ProposedAngle objects
that the user reviews/edits before save_angles() persists them to belief_angles
+ angle_generation_runs (transactional cleanup on failure).

See docs/plans/angle-driven-ad-creator/PLAN.md for the full design + decisions.
Prompt template: viraltracker/services/prompts/angle_generation_v1.md
Prompt design: docs/plans/angle-driven-ad-creator/PROMPT_DRAFT.md

Architecture:
    Generate Angles UI page
        → AngleGeneratorService.generate_angles()  [LLM call, no DB write]
        → user reviews/edits
        → AngleGeneratorService.save_angles()      [transactional DB write]
        → AC2 selects saved angles
        → existing scheduler content_source='angles' path
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

# Prompt version recorded on every angle_generation_runs row. Bump when the
# prompt file is revised so we can A/B compare prompt revisions later.
PROMPT_VERSION = "angle_generation_v1"
PROMPT_TEMPLATE_PATH = Path(__file__).parent / "prompts" / "angle_generation_v1.md"

# Default N angles per generation
DEFAULT_N_ANGLES = 5

# Max tokens for Opus response. 5 angles × ~200 tokens of structured JSON each
# plus headroom for variation = 2000 is comfortable.
MAX_TOKENS = 2500


class ProposedAngle(BaseModel):
    """
    In-memory model for a generated angle, pre-persistence.

    Maps 1:1 to columns added in migrations/2026-05-25_angle_driven_ads.sql
    on the belief_angles table. Not persisted as-is — the user reviews/edits,
    then save_angles() writes the approved rows.
    """
    name: str = Field(..., description="3-6 word handle for the angle")
    belief_statement: str = Field(..., description="The core belief the angle tests")
    jtbd_text: str = Field(..., description="JTBD in 'When I X, I want to Y, so I can Z' format")
    pain_points: List[str] = Field(default_factory=list, description="Pain points the angle leans on")
    desired_outcome: str = Field(..., description="Felt state the persona enters if the angle works")
    emotional_register: str = Field(..., description="One-word emotional register + brief")
    explanation: str = Field(..., description="Why this angle works for this persona+offer")


class AngleGeneratorService:
    """
    Produces strategic angles from persona + offer + LP via Claude Opus 4.7.

    Two main methods:
      - generate_angles(...)  : LLM call, returns in-memory ProposedAngle list
      - save_angles(...)      : transactional persist to belief_angles + run row
    """

    def __init__(self, anthropic_client=None, supabase_client=None):
        """
        Args:
            anthropic_client: Optional pre-built Anthropic client. Lazy-loaded
                from anthropic.Anthropic() on first use (reads ANTHROPIC_API_KEY).
            supabase_client: Optional pre-built Supabase client. Lazy-loaded via
                get_supabase_client() on first use.
        """
        self._anthropic_client = anthropic_client
        self._supabase_client = supabase_client
        self._prompt_template: Optional[str] = None

    # ------------------------------------------------------------------
    # Lazy-loaded clients
    # ------------------------------------------------------------------

    @property
    def anthropic_client(self):
        if self._anthropic_client is None:
            import anthropic
            self._anthropic_client = anthropic.Anthropic()
        return self._anthropic_client

    @property
    def supabase_client(self):
        if self._supabase_client is None:
            from viraltracker.core.database import get_supabase_client
            self._supabase_client = get_supabase_client()
        return self._supabase_client

    @property
    def prompt_template(self) -> str:
        if self._prompt_template is None:
            self._prompt_template = PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
        return self._prompt_template

    # ------------------------------------------------------------------
    # Model resolution (decision M1)
    # ------------------------------------------------------------------

    @staticmethod
    def get_model() -> str:
        """
        Resolve the LLM model name. Reads viraltracker.core.config.Config.CREATIVE_MODEL
        (claude-opus-4-7 as of 2026-05-25). Decision M1 in PLAN.md — central
        constant, not hardcoded here, so model upgrades are a one-line change.
        """
        from viraltracker.core.config import Config
        return Config.CREATIVE_MODEL

    # ------------------------------------------------------------------
    # Prompt assembly
    # ------------------------------------------------------------------

    NO_LP_PLACEHOLDER = "NO LANDING PAGE PROVIDED — generate without LP grounding"

    def _split_system_user(self, rendered_template: str) -> tuple[str, str]:
        """
        Split the rendered prompt template into (system_prompt, user_prompt).

        The template uses '# SYSTEM PROMPT' and '# USER PROMPT' markdown headers.
        Comments at top (HTML <!-- ... -->) are stripped before splitting.
        """
        # Strip leading HTML comment block(s)
        cleaned = re.sub(r"<!--.*?-->\s*", "", rendered_template, count=1, flags=re.DOTALL)
        # Split on '# USER PROMPT' to separate the two sections
        parts = cleaned.split("# USER PROMPT", 1)
        if len(parts) != 2:
            raise ValueError("Prompt template missing '# USER PROMPT' section")
        system_section = parts[0].replace("# SYSTEM PROMPT", "", 1).strip()
        user_section = parts[1].strip()
        return (system_section, user_section)

    # Match {single_identifier_only} so JSON braces in the template are left alone.
    # str.format()'s brace-escape rules are too fragile for templates containing
    # raw JSON syntax, so we substitute via regex instead.
    _SLOT_PATTERN = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

    def _render_prompt(
        self,
        n_angles: int,
        persona: Dict[str, Any],
        offer_variant: Dict[str, Any],
        landing_page_summary: Optional[str],
        brand_voice: str = "",
    ) -> tuple[str, str]:
        """
        Render the prompt template with the supplied inputs.

        Slot syntax is {word}. JSON braces in the template are NOT substituted,
        so the OUTPUT SCHEMA section is shown verbatim to the LLM.

        Returns:
            (system_prompt, user_prompt)
        """
        lp_text = landing_page_summary if landing_page_summary else self.NO_LP_PLACEHOLDER
        slot_values = {
            "n_angles": str(n_angles),
            "persona_json": json.dumps(persona, indent=2, default=str),
            "offer_variant_json": json.dumps(offer_variant, indent=2, default=str),
            "landing_page_summary": lp_text,
            "brand_voice": brand_voice,
        }
        rendered = self._SLOT_PATTERN.sub(
            lambda m: slot_values.get(m.group(1), m.group(0)),
            self.prompt_template,
        )
        return self._split_system_user(rendered)

    # ------------------------------------------------------------------
    # Input fetching
    # ------------------------------------------------------------------

    def _fetch_persona(self, persona_id: UUID) -> Dict[str, Any]:
        """Pull the personas_4d row for the supplied persona_id."""
        result = (
            self.supabase_client.table("personas_4d")
            .select("*")
            .eq("id", str(persona_id))
            .limit(1)
            .execute()
        )
        if not result.data:
            raise ValueError(f"Persona not found: {persona_id}")
        return result.data[0]

    def _fetch_offer_variant(self, offer_variant_id: UUID) -> Dict[str, Any]:
        """
        Pull the product_offer_variants row. Returns the user-facing strategic
        fields only (name, landing_page_url, pain_points, desires_goals,
        benefits, target_audience) — we don't dump the whole row into the prompt.
        """
        result = (
            self.supabase_client.table("product_offer_variants")
            .select("id, name, landing_page_url, pain_points, desires_goals, benefits, target_audience")
            .eq("id", str(offer_variant_id))
            .limit(1)
            .execute()
        )
        if not result.data:
            raise ValueError(f"Offer variant not found: {offer_variant_id}")
        return result.data[0]

    # ------------------------------------------------------------------
    # LLM call + parsing
    # ------------------------------------------------------------------

    def _parse_llm_response(self, raw_text: str, expected_n: int) -> List[ProposedAngle]:
        """
        Extract the JSON array from the LLM response and validate each angle.

        Tolerant of leading/trailing whitespace and accidental markdown fences
        (despite the prompt explicitly saying not to use them — Opus sometimes
        does anyway).

        Raises ValueError if the response is unparsable. Raises ValidationError
        if any angle fails Pydantic validation.
        """
        text = raw_text.strip()
        # Strip accidental ```json or ``` fences
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"AngleGeneratorService: LLM returned non-JSON response. "
                f"First 200 chars: {text[:200]!r}"
            ) from e

        if not isinstance(parsed, list):
            raise ValueError(
                f"AngleGeneratorService: expected JSON array, got {type(parsed).__name__}"
            )

        if len(parsed) != expected_n:
            logger.warning(
                f"AngleGeneratorService: expected {expected_n} angles, got {len(parsed)}. "
                f"Proceeding with what was returned."
            )

        angles = []
        for i, item in enumerate(parsed):
            try:
                angles.append(ProposedAngle(**item))
            except ValidationError as e:
                raise ValueError(
                    f"AngleGeneratorService: angle #{i+1} failed validation: {e}"
                ) from e

        return angles

    def generate_angles(
        self,
        persona_id: UUID,
        offer_variant_id: UUID,
        landing_page_url: Optional[str] = None,
        landing_page_summary: Optional[str] = None,
        n: int = DEFAULT_N_ANGLES,
        brand_voice: str = "",
    ) -> List[ProposedAngle]:
        """
        Generate N=5 strategic angles for (persona, offer_variant, optional LP).

        Pure LLM call — does NOT persist. The caller (Streamlit page) shows the
        result for review/edit; save_angles() handles persistence after user approval.

        Args:
            persona_id: UUID of personas_4d row.
            offer_variant_id: UUID of product_offer_variants row.
            landing_page_url: Optional LP URL (recorded later in save_angles for
                provenance). Not used by the prompt directly — use landing_page_summary
                for LP content.
            landing_page_summary: Output from the landing page analyzer. If None,
                the prompt is rendered with NO_LP_PLACEHOLDER and the LP-deliverability
                rule is relaxed (angle generator notes the angle is unverified).
            n: Number of angles to generate. Default 5.
            brand_voice: Optional brand voice block, inserted into the prompt.

        Returns:
            List[ProposedAngle] of length n (or close to it if the LLM short-counts).
            Raises ValueError on malformed LLM response, ValidationError on bad fields.
        """
        if n < 1:
            raise ValueError(f"n must be >= 1, got {n}")
        if n > 20:
            raise ValueError(f"n must be <= 20 (LLM context budget), got {n}")

        persona = self._fetch_persona(persona_id)
        offer_variant = self._fetch_offer_variant(offer_variant_id)

        system_prompt, user_prompt = self._render_prompt(
            n_angles=n,
            persona=persona,
            offer_variant=offer_variant,
            landing_page_summary=landing_page_summary,
            brand_voice=brand_voice,
        )

        logger.info(
            f"AngleGeneratorService: generating {n} angles for "
            f"persona_id={persona_id} offer_variant_id={offer_variant_id} "
            f"lp={'yes' if landing_page_summary else 'no'} model={self.get_model()}"
        )

        response = self.anthropic_client.messages.create(
            model=self.get_model(),
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        raw_text = response.content[0].text
        angles = self._parse_llm_response(raw_text, expected_n=n)

        logger.info(
            f"AngleGeneratorService: parsed {len(angles)} angles successfully"
        )
        return angles

    # ------------------------------------------------------------------
    # Persistence (transactional)
    # ------------------------------------------------------------------

    def save_angles(
        self,
        proposed_angles: List[ProposedAngle],
        persona_id: UUID,
        offer_variant_id: UUID,
        landing_page_url: Optional[str] = None,
        n_angles_requested: Optional[int] = None,
        created_by_user_id: Optional[UUID] = None,
        prompt_version: str = PROMPT_VERSION,
    ) -> Dict[str, Any]:
        """
        Persist a list of (possibly user-edited) ProposedAngle rows.

        Transactional pattern (PostgREST doesn't expose multi-statement
        transactions, so we manage rollback manually):
          1. INSERT angle_generation_runs row (no FK back to angles yet).
          2. INSERT belief_angles rows with angle_generation_run_id FK.
          3. UPDATE angle_generation_runs.angle_ids with the persisted IDs.
        If step 2 partially fails, cleanup deletes any inserted belief_angles
        rows and the angle_generation_runs row so we don't leave a half-state.

        Args:
            proposed_angles: The (user-reviewed) angles to persist.
            persona_id, offer_variant_id, landing_page_url, created_by_user_id:
                Snapshotted onto angle_generation_runs for provenance.
            n_angles_requested: What the user asked for at generation time
                (may differ from len(proposed_angles) if they discarded some).
                Defaults to len(proposed_angles).
            prompt_version: Recorded on the run row for A/B comparison.

        Returns:
            {"angle_generation_run_id": UUID-str, "angle_ids": [UUID-str, ...]}
        """
        if not proposed_angles:
            raise ValueError("save_angles requires at least one ProposedAngle")

        run_id = str(uuid4())
        if n_angles_requested is None:
            n_angles_requested = len(proposed_angles)

        # Step 1: insert the run row
        run_row = {
            "id": run_id,
            "created_by_user_id": str(created_by_user_id) if created_by_user_id else None,
            "persona_id": str(persona_id),
            "offer_variant_id": str(offer_variant_id),
            "landing_page_url": landing_page_url,
            "n_angles_requested": n_angles_requested,
            "generator_prompt_version": prompt_version,
            "angle_ids": [],
        }
        self.supabase_client.table("angle_generation_runs").insert(run_row).execute()
        logger.info(f"save_angles: inserted angle_generation_runs id={run_id}")

        # Step 2: insert belief_angles rows
        inserted_angle_ids: List[str] = []
        try:
            for angle in proposed_angles:
                angle_id = str(uuid4())
                row = {
                    "id": angle_id,
                    "name": angle.name,
                    "belief_statement": angle.belief_statement,
                    "explanation": angle.explanation,
                    "jtbd_framed_id": None,                  # nullable per OV-1
                    "jtbd_text": angle.jtbd_text,
                    "pain_points": angle.pain_points,
                    "desired_outcome": angle.desired_outcome,
                    "generation_method": prompt_version,
                    "source_persona_id": str(persona_id),
                    "source_offer_variant_id": str(offer_variant_id),
                    "source_landing_page_url": landing_page_url,
                    "angle_generation_run_id": run_id,
                    "status": "untested",
                }
                self.supabase_client.table("belief_angles").insert(row).execute()
                inserted_angle_ids.append(angle_id)
        except Exception as e:
            logger.error(
                f"save_angles: belief_angles insert failed after "
                f"{len(inserted_angle_ids)} successful inserts; cleaning up. Error: {e}"
            )
            self._rollback_save(run_id, inserted_angle_ids)
            raise

        # Step 3: update run row with the angle_ids array
        self.supabase_client.table("angle_generation_runs").update(
            {"angle_ids": inserted_angle_ids}
        ).eq("id", run_id).execute()
        logger.info(
            f"save_angles: persisted {len(inserted_angle_ids)} angles under run_id={run_id}"
        )

        return {"angle_generation_run_id": run_id, "angle_ids": inserted_angle_ids}

    def _rollback_save(self, run_id: str, angle_ids: List[str]) -> None:
        """
        Best-effort cleanup of a partially-persisted save_angles call.

        Deletes any belief_angles rows we managed to insert, then deletes the
        angle_generation_runs row. Errors during cleanup are logged but not
        raised — the calling exception is what the user needs to see.
        """
        for angle_id in angle_ids:
            try:
                self.supabase_client.table("belief_angles").delete().eq("id", angle_id).execute()
            except Exception as e:
                logger.warning(f"Rollback failed to delete belief_angles id={angle_id}: {e}")
        try:
            self.supabase_client.table("angle_generation_runs").delete().eq("id", run_id).execute()
        except Exception as e:
            logger.warning(f"Rollback failed to delete angle_generation_runs id={run_id}: {e}")
