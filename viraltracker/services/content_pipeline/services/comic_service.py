"""
Comic Service - Business logic for comic condensation, evaluation, and generation.

Uses Claude Opus 4.5 to:
1. Condense full video scripts to 4-12 panel comic format
2. Evaluate comic scripts for clarity, humor, and flow
3. Generate revision suggestions based on KB patterns

Uses comic-production KB for:
- Planning: blueprint, 4-panel structure, patterns
- Evaluation: checklist, troubleshooting, dialogue rules
- Revision: repair patterns, before/after examples

Part of the Trash Panda Content Pipeline (Phase 8).
"""

import os
import re
import logging
import json
from typing import List, Dict, Any, Optional, Tuple
from uuid import UUID, uuid4
from datetime import datetime
from enum import Enum
from dataclasses import dataclass, field

from viraltracker.core.config import Config
from pydantic_ai import Agent
import asyncio

from viraltracker.services.agent_tracking import run_agent_with_tracking
from viraltracker.services.usage_tracker import UsageTracker

logger = logging.getLogger(__name__)


# =============================================================================
# Enums and Configuration
# =============================================================================

class AspectRatio(str, Enum):
    """Supported comic aspect ratios."""
    VERTICAL_9_16 = "9:16"      # TikTok, Reels, Shorts
    LANDSCAPE_16_9 = "16:9"     # YouTube, Twitter
    SQUARE_1_1 = "1:1"          # Instagram feed
    PORTRAIT_4_5 = "4:5"        # Instagram portrait


class EmotionalPayoff(str, Enum):
    """Comic emotional payoff types from KB."""
    AHA = "AHA"    # Cognitive insight
    HA = "HA!"     # Humor
    OOF = "OOF"    # Relatable sting


@dataclass
class GridLayout:
    """Comic grid layout configuration."""
    cols: int
    rows: int
    aspect_ratio: AspectRatio

    @property
    def max_panels(self) -> int:
        return self.cols * self.rows

    @classmethod
    def for_aspect_ratio(cls, aspect_ratio: AspectRatio, panel_count: int) -> "GridLayout":
        """
        Get optimal grid layout for aspect ratio and panel count.

        Args:
            aspect_ratio: Target aspect ratio
            panel_count: Number of panels (1-12)

        Returns:
            GridLayout with optimal cols/rows
        """
        layouts = {
            AspectRatio.VERTICAL_9_16: [
                (1, 4), (1, 6), (2, 4), (2, 6), (3, 4)  # Vertical stacking
            ],
            AspectRatio.LANDSCAPE_16_9: [
                (4, 1), (4, 2), (4, 3), (3, 2), (3, 3)  # Horizontal flow
            ],
            AspectRatio.SQUARE_1_1: [
                (2, 2), (3, 3), (4, 3), (3, 4), (2, 3)
            ],
            AspectRatio.PORTRAIT_4_5: [
                (2, 3), (2, 4), (3, 4), (2, 5), (3, 3)
            ]
        }

        # Find best fit for panel count
        options = layouts.get(aspect_ratio, [(2, 2)])
        for cols, rows in options:
            if cols * rows >= panel_count:
                return cls(cols=cols, rows=rows, aspect_ratio=aspect_ratio)

        # Fallback to last option
        cols, rows = options[-1]
        return cls(cols=cols, rows=rows, aspect_ratio=aspect_ratio)


@dataclass
class ComicConfig:
    """Configuration for comic condensation."""
    panel_count: Optional[int] = None  # None = AI suggests
    aspect_ratio: AspectRatio = AspectRatio.VERTICAL_9_16
    target_platform: str = "instagram"
    emotional_payoff: Optional[EmotionalPayoff] = None  # None = AI picks


@dataclass
class ComicPanel:
    """Single comic panel data."""
    panel_number: int
    panel_type: str  # HOOK, BUILD, TWIST, PUNCHLINE
    dialogue: str
    visual_description: str
    character: str
    expression: str
    background: Optional[str] = None
    props: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "panel_number": self.panel_number,
            "panel_type": self.panel_type,
            "dialogue": self.dialogue,
            "visual_description": self.visual_description,
            "character": self.character,
            "expression": self.expression,
            "background": self.background,
            "props": self.props
        }


@dataclass
class ComicScript:
    """Complete comic script data."""
    id: str
    project_id: str
    version_number: int

    # Content
    title: str
    premise: str
    emotional_payoff: EmotionalPayoff
    panels: List[ComicPanel]

    # Layout
    grid_layout: GridLayout

    # Metadata
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    status: str = "draft"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "version_number": self.version_number,
            "title": self.title,
            "premise": self.premise,
            "emotional_payoff": self.emotional_payoff.value,
            "panels": [p.to_dict() for p in self.panels],
            "grid_layout": {
                "cols": self.grid_layout.cols,
                "rows": self.grid_layout.rows,
                "aspect_ratio": self.grid_layout.aspect_ratio.value
            },
            "created_at": self.created_at,
            "status": self.status
        }


@dataclass
class ComicEvaluation:
    """Comic script evaluation results."""
    clarity_score: int  # 0-100
    humor_score: int    # 0-100
    flow_score: int     # 0-100
    overall_score: int  # 0-100

    clarity_notes: str
    humor_notes: str
    flow_notes: str

    issues: List[Dict[str, str]]
    suggestions: List[str]

    ready_for_approval: bool
    quick_approve_eligible: bool  # All scores > 85

    def to_dict(self) -> Dict[str, Any]:
        return {
            "clarity_score": self.clarity_score,
            "humor_score": self.humor_score,
            "flow_score": self.flow_score,
            "overall_score": self.overall_score,
            "clarity_notes": self.clarity_notes,
            "humor_notes": self.humor_notes,
            "flow_notes": self.flow_notes,
            "issues": self.issues,
            "suggestions": self.suggestions,
            "ready_for_approval": self.ready_for_approval,
            "quick_approve_eligible": self.quick_approve_eligible
        }


@dataclass
class ComicImageEvaluation:
    """Comic image evaluation results."""
    overall_score: int  # 0-100

    # Dimension scores
    visual_clarity_score: int
    character_accuracy_score: int
    text_readability_score: int
    composition_score: int
    style_consistency_score: int

    # Notes
    visual_clarity_notes: str
    character_accuracy_notes: str
    text_readability_notes: str
    composition_notes: str
    style_consistency_notes: str

    issues: List[Dict[str, str]]
    suggestions: List[str]

    passes_threshold: bool  # >= 90%
    ready_for_review: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_score": self.overall_score,
            "visual_clarity_score": self.visual_clarity_score,
            "character_accuracy_score": self.character_accuracy_score,
            "text_readability_score": self.text_readability_score,
            "composition_score": self.composition_score,
            "style_consistency_score": self.style_consistency_score,
            "visual_clarity_notes": self.visual_clarity_notes,
            "character_accuracy_notes": self.character_accuracy_notes,
            "text_readability_notes": self.text_readability_notes,
            "composition_notes": self.composition_notes,
            "style_consistency_notes": self.style_consistency_notes,
            "issues": self.issues,
            "suggestions": self.suggestions,
            "passes_threshold": self.passes_threshold,
            "ready_for_review": self.ready_for_review
        }


# =============================================================================
# Comic Service
# =============================================================================

class ComicService:
    """
    Service for comic condensation, evaluation, and generation.

    Takes approved video scripts and condenses them to shareable comic format.
    Uses comic-production KB for best practices and quality assessment.
    """

    # Claude Opus 4.5 model ID
    DEFAULT_MODEL = "claude-opus-4-5-20251101"

    # KB document tags for targeted retrieval
    KB_PLANNING_TAGS = [
        "overview", "planning", "4-panel", "fundamentals",
        "emotional-patterns", "gag-patterns"
    ]
    KB_EVALUATION_TAGS = [
        "evaluation", "scoring", "troubleshooting", "dialogue", "clarity"
    ]
    KB_REVISION_TAGS = [
        "repair", "revision", "improvement", "critique", "rewriting"
    ]

    # Condensation prompt
    CONDENSATION_PROMPT = """You are condensing a full video script into a shareable comic format for "Trash Panda Economics".

<comic_best_practices>
{kb_context}
</comic_best_practices>

<full_script>
{script_content}
</full_script>

<storyboard>
{storyboard_json}
</storyboard>

<config>
Target Platform: {target_platform}
Aspect Ratio: {aspect_ratio}
Panel Count: {panel_count_instruction}
Emotional Payoff Goal: {emotional_payoff_instruction}
</config>

<character_mapping>
VALID CHARACTERS (you MUST use these exact names):
{script_characters}

These are the ONLY valid character names. Do NOT create variations or creative names.
Map any character references to these exact names.
</character_mapping>

<available_assets>
Characters: {available_characters}
Backgrounds: {available_backgrounds}
Props: {available_props}
</available_assets>

TASK: Condense this video script into a {panel_count_instruction}-panel comic that:
1. Captures the core message in a single "screenshot-worthy" format
2. Follows the 4-panel structure: HOOK → BUILD → TWIST → PUNCHLINE
3. Uses minimal dialogue (one-breath test: readable in one breath)
4. Prioritizes relatability over cleverness
5. Delivers a clear {emotional_payoff_instruction} payoff

OUTPUT FORMAT (JSON):
{{
    "suggested_panel_count": 4,
    "panel_count_reasoning": "Why this count works best",
    "title": "Comic title",
    "premise": "One-sentence premise",
    "emotional_payoff": "AHA|HA!|OOF",
    "panels": [
        {{
            "panel_number": 1,
            "panel_type": "HOOK|BUILD|TWIST|PUNCHLINE",
            "dialogue": "Short dialogue (max 15 words)",
            "visual_description": "What we see",
            "character": "MUST be one of: {script_characters}",
            "expression": "emotion/expression",
            "background": "background name from available_assets or null",
            "props": ["prop names from available_assets"]
        }}
    ],
    "grid_layout": {{
        "cols": 2,
        "rows": 2,
        "reasoning": "Why this layout works for the platform"
    }}
}}

CRITICAL RULES:
- Each panel MUST add new information or emotion
- Final panel MUST be the strongest beat
- Dialogue must pass the one-breath test
- CHARACTER NAMES MUST BE EXACT: Only use "{script_characters}" - no variations, no creative names
- For {aspect_ratio}, optimize panel flow (vertical for 9:16, horizontal for 16:9)"""

    # Evaluation prompt
    EVALUATION_PROMPT = """You are evaluating a comic script for "Trash Panda Economics".

<evaluation_guidelines>
{kb_context}
</evaluation_guidelines>

<comic_script>
{comic_script}
</comic_script>

Evaluate this comic against the quality checklist.

SCORING DIMENSIONS (0-100):

1. CLARITY (3-Second Test)
   - Is the premise instantly understood?
   - Does each panel add new information?
   - Is the text readable at a glance?

2. HUMOR (Emotional Payoff)
   - Does it deliver a clear AHA/HA!/OOF moment?
   - Is there a strong twist or punchline?
   - Is it relatable and shareable?

3. FLOW (Structure)
   - Does it follow HOOK → BUILD → TWIST → PUNCHLINE?
   - Is the final panel the strongest?
   - Is pacing appropriate?

OUTPUT FORMAT (JSON):
{{
    "clarity_score": 85,
    "clarity_notes": "Assessment of clarity",
    "humor_score": 80,
    "humor_notes": "Assessment of humor/payoff",
    "flow_score": 90,
    "flow_notes": "Assessment of structure/flow",
    "overall_score": 85,
    "issues": [
        {{
            "severity": "high|medium|low",
            "category": "clarity|humor|flow",
            "issue": "Description",
            "panel": 2,
            "suggestion": "How to fix"
        }}
    ],
    "suggestions": [
        "General improvement 1",
        "General improvement 2"
    ],
    "ready_for_approval": true
}}

THRESHOLDS:
- Quick Approve: ALL scores > 85
- Ready for Approval: Overall > 70, no high-severity issues
- Needs Revision: Any score < 60 or high-severity issues"""

    def __init__(
        self,
        # Kept for backward compatibility but unused
        anthropic_api_key: Optional[str] = None,
        model: Optional[str] = None,
        supabase_client: Optional[Any] = None,
        docs_service: Optional[Any] = None
    ):
        """
        Initialize the ComicService.
        """
        self.supabase = supabase_client
        self.docs = docs_service
        # Usage tracking context
        self._tracker: Optional[UsageTracker] = None
        self._user_id: Optional[str] = None
        self._org_id: Optional[str] = None
        logger.info("ComicService initialized")

    def set_tracking_context(
        self,
        tracker: UsageTracker,
        user_id: Optional[str],
        org_id: str
    ) -> None:
        """
        Set the tracking context for usage billing.

        Args:
            tracker: UsageTracker instance
            user_id: User ID for billing
            org_id: Organization ID for billing
        """
        self._tracker = tracker
        self._user_id = user_id
        self._org_id = org_id
        # Set up limit enforcement
        self._limit_service = None
        if org_id and org_id != "all":
            try:
                from viraltracker.services.usage_limit_service import UsageLimitService
                from viraltracker.core.database import get_supabase_client
                self._limit_service = UsageLimitService(get_supabase_client())
            except Exception:
                pass

    def _check_usage_limit(self) -> None:
        """Check usage limit before an expensive operation."""
        if self._limit_service and self._org_id:
            self._limit_service.enforce_limit(self._org_id, "monthly_cost")

    def _ensure_client(self) -> None:
        """Deprecated: Pydantic AI Agent is always available via Config."""
        pass

    # =========================================================================
    # Knowledge Base Helpers
    # =========================================================================

    async def _get_kb_context(self, tags: List[str]) -> str:
        """
        Fetch KB documents by tags for targeted context.

        Args:
            tags: List of tags to search for

        Returns:
            Combined content from matching documents
        """
        if not self.docs:
            logger.warning("DocService not configured - using minimal KB context")
            return self._get_minimal_kb_context()

        try:
            # Search for documents with comic-production collection tag
            results = self.docs.search(
                query=" ".join(tags),
                limit=5,
                tags=["comic-production"]
            )

            if not results:
                logger.warning("No KB documents found - using minimal context")
                return self._get_minimal_kb_context()

            # Combine chunk content
            context_parts = []
            for r in results:
                context_parts.append(f"## {r.title}\n{r.chunk_content}")

            combined = "\n\n".join(context_parts)
            logger.info(f"Retrieved {len(results)} KB chunks for context ({len(combined)} chars)")
            return combined

        except Exception as e:
            logger.error(f"Failed to fetch KB context: {e}")
            return self._get_minimal_kb_context()

    async def _get_planning_context(self) -> str:
        """Get KB context for comic planning/condensation."""
        return await self._get_kb_context(self.KB_PLANNING_TAGS)

    async def _get_evaluation_context(self) -> str:
        """Get KB context for comic evaluation."""
        return await self._get_kb_context(self.KB_EVALUATION_TAGS)

    async def _get_revision_context(self) -> str:
        """Get KB context for comic revision."""
        return await self._get_kb_context(self.KB_REVISION_TAGS)

    def _get_minimal_kb_context(self) -> str:
        """Minimal fallback KB context for testing."""
        return """# Comic Best Practices (Minimal)

## 4-Panel Structure
- HOOK: Introduce premise instantly
- BUILD: Escalate conflict/emotion
- TWIST: Subvert expectations
- PUNCHLINE: Deliver emotional payoff

## Key Rules
- One emotional payoff per comic (AHA/HA!/OOF)
- 3-second clarity - premise understood instantly
- One-breath test - dialogue readable in one breath
- Final panel is strongest beat
- Prioritize relatability over cleverness

## Emotional Types
- AHA = Cognitive insight
- HA! = Humor/comedy
- OOF = Relatable sting/self-own"""

    # =========================================================================
    # Character & Asset Helpers
    # =========================================================================

    def _extract_script_characters(self, script_data: Dict[str, Any]) -> List[str]:
        """
        Extract unique character names from the original script beats.

        Args:
            script_data: Script dictionary with beats

        Returns:
            List of unique character names from the script
        """
        characters = set()

        # Get beats from either script_data directly or nested storyboard_json
        beats = script_data.get("beats", [])
        if not beats and script_data.get("storyboard_json"):
            beats = script_data["storyboard_json"].get("beats", [])

        for beat in beats:
            character = beat.get("character", "")
            if character:
                # Normalize the character name
                char_lower = character.strip().lower()
                if char_lower:
                    characters.add(char_lower)

        # Ensure we always have at least the default character
        if not characters:
            characters.add("every-coon")

        return list(characters)

    def _normalize_character_name(self, character: str, valid_characters: List[str]) -> str:
        """
        Normalize a character name to match a valid character from the script.

        Args:
            character: Character name to normalize
            valid_characters: List of valid character names from the script

        Returns:
            Normalized character name
        """
        char_lower = character.strip().lower()

        # Direct match
        if char_lower in valid_characters:
            return char_lower

        # Check for partial matches
        for valid in valid_characters:
            # Check if valid name is contained in the character
            if valid in char_lower:
                return valid
            # Check if character is contained in valid name
            if char_lower in valid:
                return valid

        # Raccoon/coon variations -> every-coon
        if "raccoon" in char_lower or "coon" in char_lower:
            if "every-coon" in valid_characters:
                return "every-coon"
            # Return first raccoon-related valid character
            for valid in valid_characters:
                if "coon" in valid or "raccoon" in valid:
                    return valid

        # Default to first valid character (usually every-coon)
        if valid_characters:
            logger.warning(f"Could not match character '{character}' to valid characters, using '{valid_characters[0]}'")
            return valid_characters[0]

        return "every-coon"

    async def _get_available_assets(self, project_id: UUID) -> Dict[str, List[str]]:
        """
        Get available assets for a project (from video path).

        Args:
            project_id: Content project UUID

        Returns:
            Dict with characters, backgrounds, props lists
        """
        if not self.supabase:
            return {
                "characters": ["every-coon", "boomer", "fed", "whale", "wojak", "chad"],
                "backgrounds": ["simple office", "trading floor", "home kitchen"],
                "props": []
            }

        try:
            # Get approved assets from project_asset_requirements
            result = self.supabase.table("project_asset_requirements").select(
                "asset_name, asset_id, comic_assets(name, asset_type)"
            ).eq("project_id", str(project_id)).eq("status", "approved").execute()

            characters = []
            backgrounds = []
            props = []

            for req in result.data or []:
                asset_type = None
                name = req.get("asset_name")

                if req.get("comic_assets"):
                    asset_type = req["comic_assets"].get("asset_type")
                    name = req["comic_assets"].get("name") or name

                if asset_type == "character" or "coon" in (name or "").lower():
                    characters.append(name)
                elif asset_type == "background":
                    backgrounds.append(name)
                elif asset_type == "prop":
                    props.append(name)

            # Add default characters if none found
            if not characters:
                characters = ["every-coon", "boomer", "fed", "whale", "wojak", "chad"]

            return {
                "characters": list(set(characters)),
                "backgrounds": list(set(backgrounds)),
                "props": list(set(props))
            }

        except Exception as e:
            logger.error(f"Failed to fetch assets: {e}")
            return {
                "characters": ["every-coon", "boomer", "fed", "whale", "wojak", "chad"],
                "backgrounds": [],
                "props": []
            }

    # =========================================================================
    # Core Methods
    # =========================================================================

    async def condense_to_comic(
        self,
        project_id: UUID,
        script_data: Dict[str, Any],
        config: Optional[ComicConfig] = None
    ) -> ComicScript:
        """
        Condense a full video script to comic format.

        Uses comic-production KB for planning best practices.

        Args:
            project_id: Content project UUID
            script_data: Full script dictionary with beats
            config: Optional comic configuration

        Returns:
            ComicScript with condensed panels
        """
        self._ensure_client()

        config = config or ComicConfig()
        logger.info(f"Condensing script to {config.panel_count or 'AI-suggested'}-panel comic")

        # Get KB context for planning
        kb_context = await self._get_planning_context()

        # Get available assets
        assets = await self._get_available_assets(project_id)

        # Extract character names from original script (primary source of truth)
        script_characters = self._extract_script_characters(script_data)
        logger.info(f"Extracted script characters: {script_characters}")

        # Prepare script content
        script_content = self._format_script_for_condensation(script_data)
        storyboard_json = json.dumps(script_data.get("storyboard_json", {}), indent=2)

        # Build panel count instruction
        if config.panel_count:
            panel_count_instruction = str(config.panel_count)
        else:
            panel_count_instruction = "4-8 (suggest optimal based on content)"

        # Build emotional payoff instruction
        if config.emotional_payoff:
            emotional_payoff_instruction = config.emotional_payoff.value
        else:
            emotional_payoff_instruction = "best fit (AHA for insight, HA! for humor, OOF for relatable sting)"

        # Format script characters for prompt
        script_chars_str = ", ".join(script_characters)

        # Build prompt
        prompt = self.CONDENSATION_PROMPT.format(
            kb_context=kb_context,
            script_content=script_content,
            storyboard_json=storyboard_json,
            target_platform=config.target_platform,
            aspect_ratio=config.aspect_ratio.value,
            panel_count_instruction=panel_count_instruction,
            emotional_payoff_instruction=emotional_payoff_instruction,
            script_characters=script_chars_str,
            available_characters=", ".join(assets["characters"]),
            available_backgrounds=", ".join(assets["backgrounds"]) or "none specified",
            available_props=", ".join(assets["props"]) or "none specified"
        )

        # Pydantic AI Agent (Comic/Creative)
        agent = Agent(
            model=Config.get_model("comic"),
            system_prompt="You are a comic artist. Return ONLY valid JSON."
        )

        self._check_usage_limit()

        try:
            # Call Agent with tracking
            result = await run_agent_with_tracking(
                agent,
                prompt,
                tracker=self._tracker,
                user_id=self._user_id,
                organization_id=self._org_id,
                tool_name="comic_service",
                operation="condense_to_comic"
            )
            content = result.output

            # Parse response
            comic_data = self._parse_json_response(content)

            # Build ComicScript with character name normalization
            panels = []
            for p in comic_data.get("panels", []):
                # Normalize character name to match script characters
                raw_character = p.get("character", "every-coon")
                normalized_character = self._normalize_character_name(raw_character, script_characters)
                if raw_character.lower() != normalized_character:
                    logger.info(f"Normalized character '{raw_character}' -> '{normalized_character}'")

                panels.append(ComicPanel(
                    panel_number=p.get("panel_number", len(panels) + 1),
                    panel_type=p.get("panel_type", "BUILD"),
                    dialogue=p.get("dialogue", ""),
                    visual_description=p.get("visual_description", ""),
                    character=normalized_character,
                    expression=p.get("expression", "neutral"),
                    background=p.get("background"),
                    props=p.get("props", [])
                ))

            # Determine grid layout
            actual_panel_count = len(panels) or comic_data.get("suggested_panel_count", 4)
            grid_data = comic_data.get("grid_layout", {})
            if grid_data.get("cols") and grid_data.get("rows"):
                grid_layout = GridLayout(
                    cols=grid_data["cols"],
                    rows=grid_data["rows"],
                    aspect_ratio=config.aspect_ratio
                )
            else:
                grid_layout = GridLayout.for_aspect_ratio(config.aspect_ratio, actual_panel_count)

            # Parse emotional payoff
            payoff_str = comic_data.get("emotional_payoff", "HA!").upper()
            if payoff_str == "AHA":
                emotional_payoff = EmotionalPayoff.AHA
            elif payoff_str == "OOF":
                emotional_payoff = EmotionalPayoff.OOF
            else:
                emotional_payoff = EmotionalPayoff.HA

            comic_script = ComicScript(
                id=str(uuid4()),
                project_id=str(project_id),
                version_number=1,
                title=comic_data.get("title", "Untitled Comic"),
                premise=comic_data.get("premise", ""),
                emotional_payoff=emotional_payoff,
                panels=panels,
                grid_layout=grid_layout
            )

            logger.info(f"Condensed script to {len(panels)}-panel comic: {comic_script.title}")
            return comic_script

        except Exception as e:
            logger.error(f"Comic condensation failed: {e}")
            raise

    async def evaluate_comic_script(
        self,
        comic_script: ComicScript
    ) -> ComicEvaluation:
        """
        Evaluate a comic script for clarity, humor, and flow.

        Uses comic-production KB evaluation checklist.

        Args:
            comic_script: ComicScript to evaluate

        Returns:
            ComicEvaluation with scores and suggestions
        """
        self._ensure_client()

        logger.info(f"Evaluating comic: {comic_script.title}")

        # Get KB context for evaluation
        kb_context = await self._get_evaluation_context()

        # Build prompt
        prompt = self.EVALUATION_PROMPT.format(
            kb_context=kb_context,
            comic_script=json.dumps(comic_script.to_dict(), indent=2)
        )

        # Pydantic AI Agent (Comic/Creative)
        agent = Agent(
            model=Config.get_model("comic"),
            system_prompt="You are an expert comic critic. Return ONLY valid JSON."
        )

        self._check_usage_limit()

        try:
            # Call Agent with tracking
            result = await run_agent_with_tracking(
                agent,
                prompt,
                tracker=self._tracker,
                user_id=self._user_id,
                organization_id=self._org_id,
                tool_name="comic_service",
                operation="evaluate_comic_script"
            )
            content = result.output

            # Parse response
            eval_data = self._parse_json_response(content)

            clarity_score = eval_data.get("clarity_score", 0)
            humor_score = eval_data.get("humor_score", 0)
            flow_score = eval_data.get("flow_score", 0)
            overall_score = eval_data.get("overall_score", 0)

            # Determine quick approve eligibility
            quick_approve_eligible = all(s > 85 for s in [clarity_score, humor_score, flow_score])

            evaluation = ComicEvaluation(
                clarity_score=clarity_score,
                humor_score=humor_score,
                flow_score=flow_score,
                overall_score=overall_score,
                clarity_notes=eval_data.get("clarity_notes", ""),
                humor_notes=eval_data.get("humor_notes", ""),
                flow_notes=eval_data.get("flow_notes", ""),
                issues=eval_data.get("issues", []),
                suggestions=eval_data.get("suggestions", []),
                ready_for_approval=eval_data.get("ready_for_approval", False),
                quick_approve_eligible=quick_approve_eligible
            )

            logger.info(
                f"Evaluation complete: clarity={clarity_score}, humor={humor_score}, "
                f"flow={flow_score}, overall={overall_score}, quick_approve={quick_approve_eligible}"
            )
            return evaluation

        except Exception as e:
            logger.error(f"Comic evaluation failed: {e}")
            raise

    async def revise_comic(
        self,
        comic_script: ComicScript,
        evaluation: ComicEvaluation,
        revision_notes: Optional[str] = None
    ) -> ComicScript:
        """
        Revise a comic script based on evaluation feedback.

        Uses KB revision context (repair_patterns, examples_before_after) to
        generate an improved version addressing the issues identified.

        Args:
            comic_script: The current comic script to revise
            evaluation: The evaluation with issues and suggestions
            revision_notes: Optional human notes for specific changes

        Returns:
            Revised ComicScript with improvements
        """
        self._ensure_client()

        # Get revision context from KB
        revision_context = await self._get_revision_context()

        # Format issues and suggestions for the prompt
        issues_text = ""
        if evaluation.issues:
            issues_text = "ISSUES TO ADDRESS:\n"
            for issue in evaluation.issues:
                severity = issue.get('severity', 'medium')
                issues_text += f"- [{severity.upper()}] {issue.get('issue', '')}\n"
                if issue.get('suggestion'):
                    issues_text += f"  Suggestion: {issue.get('suggestion')}\n"

        suggestions_text = ""
        if evaluation.suggestions:
            suggestions_text = "ADDITIONAL SUGGESTIONS:\n"
            for s in evaluation.suggestions:
                suggestions_text += f"- {s}\n"

        scores_text = f"""CURRENT SCORES:
- Clarity: {evaluation.clarity_score}/100 ({evaluation.clarity_notes})
- Humor: {evaluation.humor_score}/100 ({evaluation.humor_notes})
- Flow: {evaluation.flow_score}/100 ({evaluation.flow_notes})
- Overall: {evaluation.overall_score}/100"""

        # Format current comic for reference
        current_panels_text = ""
        for panel in comic_script.panels:
            current_panels_text += f"""
Panel {panel.panel_number} ({panel.panel_type}):
  Character: {panel.character} ({panel.expression})
  Dialogue: "{panel.dialogue}"
  Visual: {panel.visual_description}
"""

        human_notes_text = ""
        if revision_notes:
            human_notes_text = f"\nHUMAN REVISION NOTES:\n{revision_notes}\n"

        prompt = f"""You are a comic script revision expert. Revise this comic script to address the evaluation feedback.

{revision_context}

---

CURRENT COMIC:
Title: {comic_script.title}
Premise: {comic_script.premise}
Emotional Payoff: {comic_script.emotional_payoff.value}
Panel Count: {len(comic_script.panels)}
Grid: {comic_script.grid_layout.cols}x{comic_script.grid_layout.rows}

PANELS:
{current_panels_text}

---

{scores_text}

{issues_text}

{suggestions_text}
{human_notes_text}

---

REVISION INSTRUCTIONS:
1. Address ALL high-severity issues first
2. Improve the weakest scoring dimension
3. Maintain the same panel count and grid layout
4. Keep the same emotional payoff type
5. Preserve what's already working well
6. Make dialogue punchier and more natural
7. Strengthen the HOOK → BUILD → TWIST → PUNCHLINE flow

Return the REVISED comic in this exact JSON format:
{{
  "title": "Comic title (can update if needed)",
  "premise": "One-line premise",
  "panels": [
    {{
      "panel_number": 1,
      "panel_type": "HOOK|BUILD|TWIST|PUNCHLINE",
      "dialogue": "Character dialogue",
      "visual_description": "What we see in the panel",
      "character": "character-id",
      "expression": "expression name",
      "background": "background description or null",
      "props": ["prop1", "prop2"]
    }}
  ],
  "revision_summary": "Brief explanation of what was changed and why"
}}

Return ONLY the JSON, no other text."""

        # Pydantic AI Agent (Comic/Creative)
        agent = Agent(
            model=Config.get_model("comic"),
            system_prompt="You are a comic script editor. Return ONLY valid JSON."
        )

        self._check_usage_limit()

        try:
            # Call Agent with tracking
            result = await run_agent_with_tracking(
                agent,
                prompt,
                tracker=self._tracker,
                user_id=self._user_id,
                organization_id=self._org_id,
                tool_name="comic_service",
                operation="revise_comic"
            )
            response_text = result.output.strip()

            # Parse JSON response
            if response_text.startswith("```"):
                lines = response_text.split("\n")
                json_lines = []
                in_json = False
                for line in lines:
                    if line.startswith("```json"):
                        in_json = True
                        continue
                    elif line.startswith("```"):
                        break
                    elif in_json:
                        json_lines.append(line)
                response_text = "\n".join(json_lines)

            revised_data = json.loads(response_text)

            # Extract valid characters from original comic script for normalization
            valid_characters = list(set(
                panel.character.lower() for panel in comic_script.panels if panel.character
            ))
            if not valid_characters:
                valid_characters = ["every-coon"]

            # Build revised ComicScript with character normalization
            revised_panels = []
            for p in revised_data.get("panels", []):
                # Normalize character name
                raw_character = p.get("character", "every-coon")
                normalized_character = self._normalize_character_name(raw_character, valid_characters)
                if raw_character.lower() != normalized_character:
                    logger.info(f"Revision: Normalized character '{raw_character}' -> '{normalized_character}'")

                revised_panels.append(ComicPanel(
                    panel_number=p.get("panel_number", len(revised_panels) + 1),
                    panel_type=p.get("panel_type", "BUILD"),
                    dialogue=p.get("dialogue", ""),
                    visual_description=p.get("visual_description", ""),
                    character=normalized_character,
                    expression=p.get("expression", "neutral"),
                    background=p.get("background"),
                    props=p.get("props", [])
                ))

            # Create new version number
            new_version = comic_script.version_number + 1

            revised_script = ComicScript(
                id=str(uuid4()),
                project_id=comic_script.project_id,
                version_number=new_version,
                title=revised_data.get("title", comic_script.title),
                premise=revised_data.get("premise", comic_script.premise),
                emotional_payoff=comic_script.emotional_payoff,
                panels=revised_panels,
                grid_layout=comic_script.grid_layout
            )

            revision_summary = revised_data.get("revision_summary", "")
            logger.info(f"Revised comic to v{new_version}: {revision_summary}")

            return revised_script

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse revision response: {e}")
            logger.error(f"Response was: {response_text[:500]}")
            raise ValueError(f"Invalid revision response format: {e}")
        except Exception as e:
            logger.error(f"Comic revision failed: {e}")
            raise

    async def suggest_panel_count(
        self,
        script_data: Dict[str, Any],
        aspect_ratio: AspectRatio = AspectRatio.VERTICAL_9_16
    ) -> Tuple[int, str]:
        """
        Suggest optimal panel count based on script content.

        Args:
            script_data: Full script dictionary
            aspect_ratio: Target aspect ratio

        Returns:
            Tuple of (suggested_count, reasoning)
        """
        # Simple heuristic based on beat count
        beats = script_data.get("beats", [])
        beat_count = len(beats)

        if beat_count <= 4:
            suggested = 4
            reasoning = "Short script with few beats - 4 panels captures essence"
        elif beat_count <= 8:
            suggested = 6
            reasoning = "Medium script - 6 panels allows for better flow"
        elif beat_count <= 12:
            suggested = 8
            reasoning = "Longer script - 8 panels needed for proper condensation"
        else:
            suggested = 12
            reasoning = "Complex script - 12 panels (max) for full coverage"

        # Adjust for aspect ratio
        if aspect_ratio == AspectRatio.LANDSCAPE_16_9:
            # Landscape prefers horizontal layouts (fewer rows)
            suggested = min(suggested, 8)
            reasoning += f" (adjusted for {aspect_ratio.value} layout)"

        return suggested, reasoning

    def _format_script_for_condensation(self, script_data: Dict[str, Any]) -> str:
        """
        Format script data for condensation prompt.

        Args:
            script_data: Script dictionary with beats

        Returns:
            Formatted string for LLM
        """
        parts = []

        # Title and overview
        title = script_data.get("title") or script_data.get("topic_title", "Untitled")
        parts.append(f"# {title}\n")

        # Get beats from either script_data directly or nested storyboard_json
        beats = script_data.get("beats", [])
        if not beats and script_data.get("storyboard_json"):
            beats = script_data["storyboard_json"].get("beats", [])

        # Format each beat
        for beat in beats:
            beat_name = beat.get("beat_name", "Unnamed")
            script = beat.get("script", "")
            visual = beat.get("visual_notes", "")
            character = beat.get("character", "")

            parts.append(f"## {beat_name}")
            if character:
                parts.append(f"Character: {character}")
            parts.append(f"Script: {script}")
            if visual:
                parts.append(f"Visual: {visual}")
            parts.append("")

        return "\n".join(parts)

    def _parse_json_response(self, content: str, fallback: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Parse JSON from LLM response, handling common formatting issues.

        Args:
            content: Raw response content
            fallback: Optional fallback dict if parsing fails

        Returns:
            Parsed JSON as dict
        """
        original_content = content
        content = content.strip()

        # Remove markdown code blocks if present
        if "```" in content:
            # Try to extract JSON from ```json ... ``` or ``` ... ```
            json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', content, re.DOTALL)
            if json_match:
                content = json_match.group(1).strip()
            else:
                # Fallback: remove first and last lines if they're code fences
                lines = content.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                content = "\n".join(lines)

        # Try to find JSON object in the content
        content = content.strip()
        if not content.startswith("{"):
            # Look for first { and last }
            start = content.find("{")
            end = content.rfind("}")
            if start != -1 and end != -1 and end > start:
                content = content[start:end + 1]

        # First attempt: parse as-is
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        # Second attempt: try fixing single quotes to double quotes
        try:
            # Replace single quotes with double quotes (common LLM issue)
            fixed = content.replace("'", '"')
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass

        # Third attempt: try to extract using a more aggressive regex
        try:
            # Find anything that looks like a JSON object
            json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', content, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass

        # Log the failure
        logger.error(f"JSON parse error after all attempts")
        logger.error(f"Original content (first 500 chars): {original_content[:500]}")
        logger.error(f"Processed content (first 500 chars): {content[:500]}")

        # Return fallback if provided
        if fallback is not None:
            logger.warning("Using fallback response due to JSON parse failure")
            return fallback

        raise ValueError(f"Failed to parse LLM response as JSON")

    # =========================================================================
    # Database Operations
    # =========================================================================

    async def save_comic_to_db(
        self,
        project_id: UUID,
        comic_script: ComicScript,
        script_version_id: Optional[UUID] = None
    ) -> UUID:
        """
        Save a comic version to the database.

        Args:
            project_id: Content project UUID
            comic_script: ComicScript to save
            script_version_id: Source script version UUID

        Returns:
            Created comic_version UUID
        """
        if not self.supabase:
            logger.warning("Supabase not configured - comic not saved")
            return UUID(comic_script.id)

        try:
            # Get next version number
            existing = self.supabase.table("comic_versions").select("version_number").eq(
                "project_id", str(project_id)
            ).order("version_number", desc=True).limit(1).execute()

            next_version = (existing.data[0]["version_number"] + 1) if existing.data else 1

            logger.info(f"Saving comic version {next_version} for project {project_id}")

            result = self.supabase.table("comic_versions").insert({
                "project_id": str(project_id),
                "script_version_id": str(script_version_id) if script_version_id else None,
                "version_number": next_version,
                "comic_script": json.dumps(comic_script.to_dict()),
                "panel_count": len(comic_script.panels),
                "status": "draft"
            }).execute()

            if result.data:
                comic_id = UUID(result.data[0]["id"])
                logger.info(f"Saved comic version {comic_id}")

                # Update project with current comic version
                self.supabase.table("content_projects").update({
                    "current_comic_version_id": str(comic_id),
                    "workflow_state": "comic_evaluation"
                }).eq("id", str(project_id)).execute()

                return comic_id

            return UUID(comic_script.id)

        except Exception as e:
            logger.error(f"Failed to save comic: {e}")
            raise

    async def save_evaluation_to_db(
        self,
        comic_version_id: UUID,
        evaluation: ComicEvaluation
    ) -> None:
        """
        Save evaluation results to the comic version.

        Args:
            comic_version_id: Comic version UUID
            evaluation: ComicEvaluation results
        """
        if not self.supabase:
            logger.warning("Supabase not configured - evaluation not saved")
            return

        try:
            self.supabase.table("comic_versions").update({
                "evaluation_results": evaluation.to_dict(),
                "evaluation_notes": json.dumps({
                    "clarity": evaluation.clarity_notes,
                    "humor": evaluation.humor_notes,
                    "flow": evaluation.flow_notes
                })
            }).eq("id", str(comic_version_id)).execute()

            logger.info(f"Saved evaluation for comic {comic_version_id}")

        except Exception as e:
            logger.error(f"Failed to save evaluation: {e}")

    async def get_comic_version(
        self,
        comic_version_id: UUID
    ) -> Optional[Dict[str, Any]]:
        """
        Get a comic version by ID.

        Args:
            comic_version_id: Comic version UUID

        Returns:
            Comic version dictionary or None
        """
        if not self.supabase:
            return None

        try:
            result = self.supabase.table("comic_versions").select("*").eq(
                "id", str(comic_version_id)
            ).execute()

            if result.data:
                return result.data[0]
            return None

        except Exception as e:
            logger.error(f"Failed to fetch comic: {e}")
            return None

    async def approve_comic(
        self,
        comic_version_id: UUID,
        project_id: UUID,
        human_notes: Optional[str] = None
    ) -> None:
        """
        Approve a comic version.

        Args:
            comic_version_id: Comic version UUID to approve
            project_id: Content project UUID
            human_notes: Optional approval notes
        """
        if not self.supabase:
            logger.warning("Supabase not configured")
            return

        try:
            self.supabase.table("comic_versions").update({
                "status": "approved",
                "human_notes": human_notes,
                "approved_at": datetime.utcnow().isoformat()
            }).eq("id", str(comic_version_id)).execute()

            self.supabase.table("content_projects").update({
                "workflow_state": "comic_approved"
            }).eq("id", str(project_id)).execute()

            logger.info(f"Approved comic {comic_version_id}")

        except Exception as e:
            logger.error(f"Failed to approve comic: {e}")
            raise

    # =========================================================================
    # Phase 9: Image Generation & JSON Conversion
    # =========================================================================

    # Image generation prompt template
    IMAGE_GENERATION_PROMPT = """Create a {cols}x{rows} comic grid image for "{title}".

STYLE: Flat vector cartoon art, minimal design, thick black outlines, simple geometric shapes,
style of Cyanide and Happiness, 2D, high contrast, clean white backgrounds between panels.

LAYOUT:
- Grid: {cols} columns × {rows} rows
- Panel borders: Thick black lines (4px)
- Gutter: White space between panels
- Aspect ratio: {aspect_ratio}

PANELS:
{panel_descriptions}

REQUIREMENTS:
1. Each panel clearly separated by thick black borders
2. Characters should be simple, expressive, easily readable at small sizes
3. Text bubbles with clear, readable dialogue
4. Consistent character design across all panels
5. Visual progression tells the story even without text
6. Final panel should have the strongest visual impact

Generate a single cohesive comic image with all {panel_count} panels in the grid layout."""

    # Image evaluation prompt (for Gemini) - will be combined with KB context
    IMAGE_EVALUATION_PROMPT = """You are a comic art director evaluating a comic image using professional standards.

{kb_context}

EVALUATION CRITERIA (score 0-100 each):

1. VISUAL CLARITY
   - Are panels clearly separated with proper borders?
   - Can each panel be understood in under 3 seconds?
   - Is the visual hierarchy guiding the eye correctly?

2. CHARACTER ACCURACY
   - Are characters consistent across all panels?
   - Are expressions clear and readable at small sizes?
   - Do poses convey the intended emotion?

3. TEXT READABILITY
   - Are speech bubbles properly sized and positioned?
   - Is text large enough to read on mobile?
   - Does text placement avoid covering important visuals?

4. COMPOSITION
   - Does the grid layout match the intended structure?
   - Is there proper white space (gutters) between panels?
   - Does the eye flow naturally from panel to panel?

5. STYLE CONSISTENCY
   - Is the art style uniform across all panels?
   - Are line weights consistent?
   - Is the color palette cohesive?

IMPORTANT: Provide SPECIFIC, ACTIONABLE suggestions based on comic best practices.
For any score below 85, give concrete advice on how to fix it.

Return ONLY this JSON (no other text):
{{"overall_score": 75, "visual_clarity_score": 80, "visual_clarity_notes": "specific observation", "character_accuracy_score": 70, "character_accuracy_notes": "specific observation", "text_readability_score": 75, "text_readability_notes": "specific observation", "composition_score": 80, "composition_notes": "specific observation", "style_consistency_score": 70, "style_consistency_notes": "specific observation", "issues": [{{"severity": "high", "issue": "specific problem", "suggestion": "how to fix it"}}], "suggestions": ["actionable suggestion 1", "actionable suggestion 2"]}}"""

    async def generate_comic_image(
        self,
        comic_script: ComicScript,
        gemini_service: Any,
        reference_images: Optional[List[str]] = None,
        improvement_notes: Optional[str] = None
    ) -> str:
        """
        Generate a 4K comic grid image using Gemini Image.

        Args:
            comic_script: ComicScript with panels to render
            gemini_service: GeminiService instance for image generation
            reference_images: Optional base64 reference images (character sheets)
            improvement_notes: Optional notes for improving previous generation

        Returns:
            Base64-encoded generated comic image
        """
        logger.info(f"Generating comic image for: {comic_script.title}")
        if improvement_notes:
            logger.info(f"With improvement notes: {improvement_notes[:100]}...")

        # Build panel descriptions
        panel_descriptions = []
        for panel in comic_script.panels:
            desc = f"""Panel {panel.panel_number} ({panel.panel_type}):
- Character: {panel.character} with {panel.expression} expression
- Dialogue: "{panel.dialogue}"
- Visual: {panel.visual_description}
- Background: {panel.background or 'simple/minimal'}"""
            panel_descriptions.append(desc)

        # Build prompt
        prompt = self.IMAGE_GENERATION_PROMPT.format(
            cols=comic_script.grid_layout.cols,
            rows=comic_script.grid_layout.rows,
            title=comic_script.title,
            aspect_ratio=comic_script.grid_layout.aspect_ratio.value,
            panel_descriptions="\n\n".join(panel_descriptions),
            panel_count=len(comic_script.panels)
        )

        # Add improvement notes if this is a regeneration
        if improvement_notes:
            prompt += f"""

IMPORTANT - IMPROVEMENTS NEEDED:
This is a regeneration. The previous image had issues. Please specifically address:
{improvement_notes}

Make sure to improve these specific aspects while maintaining everything else."""

        try:
            # Generate image using Gemini
            result = await gemini_service.generate_image(
                prompt=prompt,
                reference_images=reference_images,
                return_metadata=True
            )

            if isinstance(result, dict):
                image_base64 = result.get("image_base64", "")
                logger.info(f"Generated comic image in {result.get('generation_time_ms', 0)}ms")
            else:
                image_base64 = result
                logger.info("Generated comic image")

            return image_base64

        except Exception as e:
            logger.error(f"Comic image generation failed: {e}")
            raise

    async def evaluate_comic_image(
        self,
        image_base64: str,
        comic_script: ComicScript,
        gemini_service: Any
    ) -> ComicImageEvaluation:
        """
        Evaluate a generated comic image against quality checklist.

        Must pass 90%+ to proceed to human review.

        Args:
            image_base64: Base64-encoded comic image
            comic_script: ComicScript for reference
            gemini_service: GeminiService for evaluation

        Returns:
            ComicImageEvaluation with scores and feedback
        """
        logger.info(f"Evaluating comic image for: {comic_script.title}")

        # Use Gemini to analyze the image
        try:
            # Fetch KB context for evaluation
            kb_context = await self._get_evaluation_context()
            if not kb_context or len(kb_context) < 100:
                kb_context = """COMIC EVALUATION BEST PRACTICES:
- 3-second clarity: Each panel must be understood instantly
- HOOK → BUILD → TWIST → PUNCHLINE flow
- Character expressions must be readable at thumbnail size
- Text bubbles should not exceed 15 words
- Final panel needs strongest visual/emotional impact"""

            # Build comic context
            comic_context = f"""
COMIC BEING EVALUATED:
- Title: {comic_script.title}
- Premise: {comic_script.premise}
- Panel Count: {len(comic_script.panels)}
- Grid Layout: {comic_script.grid_layout.cols}x{comic_script.grid_layout.rows}

EXPECTED PANELS:
"""
            for p in comic_script.panels:
                comic_context += f"- Panel {p.panel_number} ({p.panel_type}): {p.character} says '{p.dialogue}'\n"

            # Build full prompt with KB context
            full_prompt = self.IMAGE_EVALUATION_PROMPT.format(kb_context=kb_context) + comic_context

            # Call Gemini with image
            response = await gemini_service.analyze_image(
                image_data=image_base64,
                prompt=full_prompt
            )

            # Log raw response for debugging
            logger.info(f"Gemini raw response (first 500 chars): {str(response)[:500]}")

            # Parse response with fallback for resilience
            fallback_eval = {
                "overall_score": 70,
                "visual_clarity_score": 70,
                "character_accuracy_score": 70,
                "text_readability_score": 70,
                "composition_score": 70,
                "style_consistency_score": 70,
                "visual_clarity_notes": "Unable to parse detailed evaluation",
                "character_accuracy_notes": "Unable to parse detailed evaluation",
                "text_readability_notes": "Unable to parse detailed evaluation",
                "composition_notes": "Unable to parse detailed evaluation",
                "style_consistency_notes": "Unable to parse detailed evaluation",
                "issues": [{"severity": "medium", "issue": "Evaluation parsing failed - manual review recommended"}],
                "suggestions": ["Please manually review the generated comic image"]
            }
            eval_data = self._parse_json_response(response, fallback=fallback_eval)

            overall_score = eval_data.get("overall_score", 0)
            passes_threshold = overall_score >= 90

            evaluation = ComicImageEvaluation(
                overall_score=overall_score,
                visual_clarity_score=eval_data.get("visual_clarity_score", 0),
                character_accuracy_score=eval_data.get("character_accuracy_score", 0),
                text_readability_score=eval_data.get("text_readability_score", 0),
                composition_score=eval_data.get("composition_score", 0),
                style_consistency_score=eval_data.get("style_consistency_score", 0),
                visual_clarity_notes=eval_data.get("visual_clarity_notes", ""),
                character_accuracy_notes=eval_data.get("character_accuracy_notes", ""),
                text_readability_notes=eval_data.get("text_readability_notes", ""),
                composition_notes=eval_data.get("composition_notes", ""),
                style_consistency_notes=eval_data.get("style_consistency_notes", ""),
                issues=eval_data.get("issues", []),
                suggestions=eval_data.get("suggestions", []),
                passes_threshold=passes_threshold,
                ready_for_review=passes_threshold
            )

            logger.info(
                f"Image evaluation: {overall_score}% overall, "
                f"passes_threshold={passes_threshold}"
            )
            return evaluation

        except Exception as e:
            logger.error(f"Comic image evaluation failed: {e}")
            raise

    def generate_comic_json(
        self,
        comic_script: ComicScript,
        image_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate JSON for the comic video tool.

        Converts ComicScript to the format expected by the existing
        comic video generation system.

        Args:
            comic_script: ComicScript to convert
            image_url: Optional URL of generated comic image

        Returns:
            Dict in comic video JSON format
        """
        logger.info(f"Generating comic JSON for: {comic_script.title}")

        # Map panel types to video tool types
        panel_type_map = {
            "HOOK": "TITLE",
            "BUILD": "ACT 1 - CONTENT",
            "TWIST": "ACT 2 - CONTENT",
            "PUNCHLINE": "OUTRO"
        }

        # Map emotional payoff to mood
        payoff_mood_map = {
            EmotionalPayoff.AHA: "positive",
            EmotionalPayoff.HA: "celebration",
            EmotionalPayoff.OOF: "dramatic"
        }

        # Build structure description
        structure = {
            "title": f"Panel 1",
            "total_panels": len(comic_script.panels)
        }

        # Group panels into acts
        panels_per_act = max(1, len(comic_script.panels) // 3)
        act_num = 1
        for i, panel in enumerate(comic_script.panels):
            if i == 0:
                continue  # Title panel
            if i == len(comic_script.panels) - 1:
                structure["outro"] = f"Panel {panel.panel_number}"
            elif (i - 1) % panels_per_act == 0 and act_num <= 3:
                end_panel = min(i + panels_per_act, len(comic_script.panels) - 1)
                structure[f"act_{act_num}"] = f"Panels {i + 1}-{end_panel}"
                act_num += 1

        # Build panels array
        panels = []
        for panel in comic_script.panels:
            panel_json = {
                "panel_number": panel.panel_number,
                "panel_type": panel_type_map.get(panel.panel_type, "ACT 1 - CONTENT"),
                "header_text": comic_script.title if panel.panel_number == 1 else "",
                "dialogue": panel.dialogue,
                "character": panel.character,  # For audio voice lookup
                "expression": panel.expression,
                "mood": self._infer_mood_from_panel(panel, comic_script.emotional_payoff),
                "characters_needed": [f"{panel.character} ({panel.expression})"],
                "prompt": panel.visual_description
            }
            panels.append(panel_json)

        # Build layout recommendation with grid_structure (preferred by Comic Video service)
        grid_structure = self._build_grid_structure(comic_script)
        layout = {
            "format": f"{comic_script.grid_layout.cols} columns x {comic_script.grid_layout.rows} rows",
            "grid_structure": grid_structure,
            "panel_arrangement": self._build_panel_arrangement(comic_script)
        }

        # Assemble final JSON
        comic_json = {
            "total_panels": len(comic_script.panels),
            "structure": structure,
            "panels": panels,
            "layout_recommendation": layout,
            "canvas_width": comic_script.grid_layout.cols * 1000,
            "canvas_height": comic_script.grid_layout.rows * 1000,
            "metadata": {
                "title": comic_script.title,
                "premise": comic_script.premise,
                "emotional_payoff": comic_script.emotional_payoff.value,
                "aspect_ratio": comic_script.grid_layout.aspect_ratio.value,
                "grid_cols": comic_script.grid_layout.cols,
                "grid_rows": comic_script.grid_layout.rows
            }
        }

        if image_url:
            comic_json["comic_image_url"] = image_url

        logger.info(f"Generated comic JSON with {len(panels)} panels")
        return comic_json

    def _infer_mood_from_panel(
        self,
        panel: ComicPanel,
        default_payoff: EmotionalPayoff
    ) -> str:
        """
        Infer mood from panel content for video effects.

        Args:
            panel: Comic panel
            default_payoff: Default emotional payoff

        Returns:
            Mood string for video effects
        """
        dialogue_lower = panel.dialogue.lower()
        expression_lower = panel.expression.lower()
        visual_lower = panel.visual_description.lower()

        # Check for explicit mood indicators
        if any(w in dialogue_lower for w in ["panic", "crash", "disaster", "chaos"]):
            return "chaos"
        if any(w in dialogue_lower for w in ["danger", "warning", "alert"]):
            return "danger"
        if any(w in dialogue_lower for w in ["win", "success", "celebrate"]):
            return "celebration"
        if any(w in expression_lower for w in ["shocked", "scared", "panic"]):
            return "danger"
        if any(w in expression_lower for w in ["happy", "excited", "proud"]):
            return "positive"
        if any(w in visual_lower for w in ["chaos", "explosion", "crash"]):
            return "chaos"

        # Default based on panel type
        if panel.panel_type == "PUNCHLINE":
            if default_payoff == EmotionalPayoff.HA:
                return "celebration"
            elif default_payoff == EmotionalPayoff.OOF:
                return "dramatic"
            else:
                return "positive"

        return "neutral"

    def _build_grid_structure(self, comic_script: ComicScript) -> List[Dict[str, Any]]:
        """
        Build grid_structure for Comic Video service layout parsing.

        This format explicitly maps each panel to its grid position,
        which the Comic Video service prefers over panel_arrangement.

        Args:
            comic_script: Comic script with panels and grid layout

        Returns:
            List of row definitions with panel mappings
        """
        cols = comic_script.grid_layout.cols
        rows = comic_script.grid_layout.rows
        panels = comic_script.panels
        total_panels = len(panels)

        grid_structure = []
        panel_idx = 0

        for row in range(rows):
            # Calculate how many panels fit in this row
            remaining_panels = total_panels - panel_idx
            remaining_rows = rows - row
            panels_this_row = min(cols, remaining_panels)

            # If this is the last row and we have fewer panels, adjust
            if remaining_rows == 1:
                panels_this_row = remaining_panels

            # Build list of panel numbers for this row
            row_panels = []
            for _ in range(panels_this_row):
                if panel_idx < total_panels:
                    row_panels.append(panels[panel_idx].panel_number)
                    panel_idx += 1

            grid_structure.append({
                "row": row + 1,  # 1-indexed for Comic Video service
                "columns": len(row_panels),
                "panels": row_panels
            })

        return grid_structure

    def _build_panel_arrangement(self, comic_script: ComicScript) -> List[List[str]]:
        """
        Build panel arrangement for layout recommendation.

        Args:
            comic_script: Comic script with grid layout

        Returns:
            2D array of panel positions
        """
        cols = comic_script.grid_layout.cols
        rows = comic_script.grid_layout.rows
        panels = comic_script.panels

        arrangement = []
        panel_idx = 0

        for row in range(rows):
            row_panels = []
            for col in range(cols):
                if panel_idx < len(panels):
                    panel = panels[panel_idx]
                    # First panel (title) might span multiple columns
                    if panel_idx == 0 and cols > 1:
                        row_panels.append(f"TITLE (wide, spans {cols} columns)")
                        panel_idx += 1
                        break
                    else:
                        row_panels.append(f"Panel {panel.panel_number}")
                        panel_idx += 1
            if row_panels:
                arrangement.append(row_panels)

        return arrangement

    # Storage bucket for comic images
    COMIC_IMAGES_BUCKET = "comic-assets"

    def upload_comic_image_to_storage(
        self,
        image_base64: str,
        comic_id: str,
        project_id: str
    ) -> str:
        """
        Upload comic image to Supabase Storage and return public URL.

        Args:
            image_base64: Base64-encoded image data (with or without data URL prefix)
            comic_id: Comic version ID for filename
            project_id: Project ID for folder organization

        Returns:
            Public URL of uploaded image
        """
        if not self.supabase:
            raise ValueError("Supabase client not configured")

        import base64

        # Strip data URL prefix if present
        if image_base64.startswith("data:"):
            # Format: data:image/png;base64,XXXX
            header, image_base64 = image_base64.split(",", 1)
            # Extract mime type
            mime_type = header.split(";")[0].split(":")[1]
            extension = mime_type.split("/")[1]  # png, jpeg, etc.
        else:
            extension = "png"
            mime_type = "image/png"

        # Decode base64 to bytes
        try:
            image_bytes = base64.b64decode(image_base64)
        except Exception as e:
            logger.error(f"Failed to decode base64 image: {e}")
            raise ValueError(f"Invalid base64 image data: {e}")

        # Generate storage path
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        storage_path = f"comics/{project_id}/{comic_id}_{timestamp}.{extension}"

        try:
            # Upload to Supabase Storage
            self.supabase.storage.from_(self.COMIC_IMAGES_BUCKET).upload(
                path=storage_path,
                file=image_bytes,
                file_options={"content-type": mime_type}
            )

            # Get public URL
            public_url = self.supabase.storage.from_(
                self.COMIC_IMAGES_BUCKET
            ).get_public_url(storage_path)

            logger.info(f"Uploaded comic image to {storage_path}")
            return public_url

        except Exception as e:
            logger.error(f"Failed to upload comic image: {e}")
            raise

    async def save_comic_image_to_db(
        self,
        comic_version_id: UUID,
        image_url: str,
        evaluation: Optional[ComicImageEvaluation] = None
    ) -> None:
        """
        Save generated comic image URL and evaluation to database.

        Args:
            comic_version_id: Comic version UUID
            image_url: URL of generated image
            evaluation: Optional image evaluation results
        """
        if not self.supabase:
            logger.warning("Supabase not configured - image not saved")
            return

        try:
            update_data = {
                "generated_image_url": image_url
            }

            if evaluation:
                update_data["image_evaluation"] = evaluation.to_dict()

            self.supabase.table("comic_versions").update(update_data).eq(
                "id", str(comic_version_id)
            ).execute()

            logger.info(f"Saved comic image for version {comic_version_id}")

        except Exception as e:
            logger.error(f"Failed to save comic image: {e}")
            raise
