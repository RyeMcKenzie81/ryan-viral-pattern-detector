"""
Script Generation Service - Business logic for script generation and review.

Uses Claude Opus 4.5 to:
1. Generate full scripts with storyboard based on selected topic
2. Review scripts against the bible checklist
3. Revise scripts based on feedback
4. Convert scripts to ELS format for audio production

Part of the Trash Panda Content Pipeline (MVP 2).
"""

import os
import logging
import json
import re
from typing import List, Dict, Any, Optional
from uuid import UUID, uuid4
from datetime import datetime

import anthropic

logger = logging.getLogger(__name__)


class ScriptGenerationService:
    """
    Service for generating and reviewing video scripts.

    Uses Claude Opus 4.5 for high-quality script generation that follows
    the brand bible guidelines exactly.
    """

    # Claude Opus 4.5 model ID
    DEFAULT_MODEL = "claude-opus-4-5-20251101"

    # Script generation prompt - injects full bible for quality
    GENERATION_PROMPT = """You are a script writer for "Trash Panda Economics" - a YouTube channel that explains complex financial concepts using raccoon characters.

You MUST follow the Production Bible EXACTLY. Every rule matters.

<production_bible>
{bible_content}
</production_bible>

<selected_topic>
Title: {topic_title}
Description: {topic_description}
Hook Options: {hook_options}
Target Emotion: {target_emotion}
</selected_topic>

Write a complete video script (2-5 minutes) for this topic.

OUTPUT FORMAT:
Return a JSON object with this structure:
{{
    "title": "Video title",
    "target_duration_seconds": 180,
    "hook_formula_used": "Heist|Mystery Trash|Rule Break|Countdown|Confession|Split Screen",
    "beats": [
        {{
            "beat_id": "01_hook",
            "beat_name": "Hook",
            "timestamp_start": "0:00",
            "timestamp_end": "0:06",
            "script": "The dialogue/narration text",
            "character": "every-coon",
            "visual_notes": "Description of what's on screen",
            "audio_notes": "Music and SFX cues",
            "editor_notes": "Pacing and style guidance"
        }}
    ],
    "els_script": "Full ELS format script (see Section 19 of bible)",
    "thumbnail_suggestions": [
        {{
            "concept": "Description of thumbnail idea",
            "text": "Max 2 words for thumbnail",
            "character": "which character",
            "expression": "character expression"
        }}
    ],
    "cta_target": "Topic suggestion for CTA video"
}}

REQUIREMENTS:
1. Follow the beat structure from Section 6 (Hook, Re-hooks at 0:20/1:00/1:30/2:00/2:30, Setup, Climax, Summary, Trash Pun, CTA)
2. Use caveman economics tone (2-5 word phrases, no banned words)
3. Include at least one contrast character (Fed, Boomer, Chad, Wojak, or Whale)
4. 1 joke every 4-6 seconds, 1 trash metaphor every 30 seconds
5. End with a trash pun and max 8-second CTA
6. ELS script must use proper tags ([BEAT:], [CHARACTER:], [PACE:], [PAUSE:], etc.)

Generate the complete script now."""

    # Script review prompt - checks against bible checklist
    REVIEW_PROMPT = """You are a script reviewer for "Trash Panda Economics". Review this script against the Production Bible checklist.

<production_bible>
{bible_content}
</production_bible>

<script_to_review>
{script_content}
</script_to_review>

Review the script against the PRE-FLIGHT CHECKLIST from Section 18 of the bible.

OUTPUT FORMAT:
Return a JSON object with this structure:
{{
    "overall_score": 85,
    "checklist_results": {{
        "voice_and_style": {{
            "hook_uses_formula": {{"passed": true, "notes": "Uses Heist formula"}},
            "no_banned_words": {{"passed": true, "notes": "Clean"}},
            "supply_demand_named": {{"passed": true, "notes": "Always names what"}},
            "caveman_cadence": {{"passed": true, "notes": "Good 2-5 word fragments"}},
            "joke_frequency": {{"passed": true, "notes": "Joke every 5 seconds average"}},
            "trash_metaphors": {{"passed": true, "notes": "3 trash metaphors"}},
            "money_not_caps": {{"passed": true, "notes": "Uses money in narration"}}
        }},
        "structure": {{
            "hook_first_6_seconds": {{"passed": true, "notes": ""}},
            "rehooks_at_timestamps": {{"passed": true, "notes": "All 5 present"}},
            "visual_escalation": {{"passed": true, "notes": ""}},
            "climax_has_chaos": {{"passed": true, "notes": ""}},
            "trash_pun_ending": {{"passed": true, "notes": ""}},
            "runtime_2_5_min": {{"passed": true, "notes": "3:15 runtime"}},
            "pacing_150_170_wpm": {{"passed": true, "notes": "~160 WPM"}}
        }},
        "characters": {{
            "everycoon_as_proxy": {{"passed": true, "notes": ""}},
            "contrast_character": {{"passed": true, "notes": "Fed appears"}},
            "characters_deployed_correctly": {{"passed": true, "notes": ""}},
            "no_out_of_character": {{"passed": true, "notes": ""}}
        }},
        "editorial": {{
            "no_investment_advice": {{"passed": true, "notes": ""}},
            "core_claims_accurate": {{"passed": true, "notes": ""}}
        }},
        "technical": {{
            "cta_max_8_seconds": {{"passed": true, "notes": ""}}
        }}
    }},
    "issues_found": [
        {{
            "severity": "high|medium|low",
            "category": "voice_and_style|structure|characters|editorial|technical",
            "issue": "Description of the problem",
            "location": "Beat ID or timestamp",
            "suggestion": "How to fix it"
        }}
    ],
    "improvement_suggestions": [
        "General suggestion 1",
        "General suggestion 2"
    ],
    "ready_for_approval": true
}}

Be thorough but fair. The script should follow the bible closely, but minor stylistic variations are acceptable if they serve the content."""

    # Revision prompt
    REVISION_PROMPT = """You are revising a script for "Trash Panda Economics" based on review feedback.

<production_bible>
{bible_content}
</production_bible>

<original_script>
{original_script}
</original_script>

<review_feedback>
{review_feedback}
</review_feedback>

<human_notes>
{human_notes}
</human_notes>

Create a revised version of the script that addresses all the issues found in the review.

Return the revised script in the same JSON format as the original, with all issues fixed.
Focus especially on:
1. Any "high" severity issues
2. Human notes (prioritize these)
3. Medium severity issues

Keep what's working well and only change what needs to be fixed."""

    def __init__(
        self,
        anthropic_api_key: Optional[str] = None,
        model: Optional[str] = None,
        supabase_client: Optional[Any] = None,
        docs_service: Optional[Any] = None
    ):
        """
        Initialize the ScriptGenerationService.

        Args:
            anthropic_api_key: Anthropic API key (defaults to ANTHROPIC_API_KEY env var)
            model: Model to use (defaults to claude-opus-4-5-20251101)
            supabase_client: Supabase client for database operations
            docs_service: DocService for knowledge base queries
        """
        api_key = anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")

        if not api_key:
            logger.warning("ANTHROPIC_API_KEY not set - script generation will fail")
            self.client = None
        else:
            self.client = anthropic.Anthropic(api_key=api_key)

        self.model = model or self.DEFAULT_MODEL
        self.supabase = supabase_client
        self.docs = docs_service

    def _ensure_client(self) -> None:
        """Raise error if Anthropic client not configured."""
        if not self.client:
            raise ValueError(
                "Anthropic client not configured. Set ANTHROPIC_API_KEY environment variable."
            )

    async def get_full_bible_content(self, brand_id: UUID) -> str:
        """
        Get the FULL bible content for injection into prompts.

        Unlike topic discovery which uses RAG chunks, script generation
        needs the complete bible to ensure all rules are followed.

        Args:
            brand_id: Brand UUID

        Returns:
            Complete bible content string
        """
        if not self.docs:
            logger.warning("DocService not configured - using minimal bible")
            return self._get_minimal_bible()

        try:
            # Get documents tagged with trash-panda-bible
            docs = self.docs.get_by_tags(["trash-panda-bible"])

            if not docs:
                logger.warning("No bible document found - using minimal bible")
                return self._get_minimal_bible()

            # Return the full content of the first (should be only) bible document
            bible_doc = docs[0]
            logger.info(f"Retrieved full bible: {len(bible_doc.content):,} chars")
            return bible_doc.content

        except Exception as e:
            logger.error(f"Failed to fetch bible: {e}")
            return self._get_minimal_bible()

    def _get_minimal_bible(self) -> str:
        """Minimal fallback bible for testing."""
        return """# Trash Panda Economics - Minimal Style Guide

## Voice
- Caveman economics tone (2-5 word phrases)
- No banned words: therefore, essentially, however, basically, actually, technically, instead, average
- 1 joke every 4-6 seconds
- 1 trash metaphor every 30 seconds

## Characters
- Every-Coon: Main narrator, confused but curious
- The Fed: Monotone bureaucrat
- Boomer: Nostalgic, dismissive
- Chad: Overconfident crypto bro
- Wojak: Panicked, always losing
- Whale: Silent, menacing

## Structure
- Hook: 0:00-0:06
- Re-hooks: 0:20, 1:00, 1:30, 2:00, 2:30
- Climax with chaos
- End with trash pun
- CTA max 8 seconds"""

    async def generate_script(
        self,
        project_id: UUID,
        topic: Dict[str, Any],
        brand_id: UUID
    ) -> Dict[str, Any]:
        """
        Generate a full script for the selected topic.

        Args:
            project_id: Content project UUID
            topic: Selected topic dictionary
            brand_id: Brand UUID for bible context

        Returns:
            Script data dictionary with beats, ELS script, thumbnails, etc.
        """
        self._ensure_client()

        logger.info(f"Generating script for topic: {topic.get('title')}")

        # Get full bible content
        bible_content = await self.get_full_bible_content(brand_id)

        # Build prompt
        prompt = self.GENERATION_PROMPT.format(
            bible_content=bible_content,
            topic_title=topic.get("title", ""),
            topic_description=topic.get("description", ""),
            hook_options=json.dumps(topic.get("hook_options", [])),
            target_emotion=topic.get("target_emotion", "curiosity")
        )

        try:
            # Call Claude Opus 4.5
            response = self.client.messages.create(
                model=self.model,
                max_tokens=8000,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            # Parse response
            content = response.content[0].text
            script_data = self._parse_json_response(content)

            # Add metadata
            script_data["id"] = str(uuid4())
            script_data["project_id"] = str(project_id)
            script_data["version_number"] = 1
            script_data["created_at"] = datetime.utcnow().isoformat()
            script_data["status"] = "draft"

            logger.info(f"Generated script with {len(script_data.get('beats', []))} beats")
            return script_data

        except Exception as e:
            logger.error(f"Script generation failed: {e}")
            raise

    async def review_script(
        self,
        script_data: Dict[str, Any],
        brand_id: UUID
    ) -> Dict[str, Any]:
        """
        Review a script against the bible checklist.

        Args:
            script_data: Script dictionary to review
            brand_id: Brand UUID for bible context

        Returns:
            Review result dictionary with checklist results and issues
        """
        self._ensure_client()

        logger.info("Reviewing script against bible checklist")

        # Get full bible content
        bible_content = await self.get_full_bible_content(brand_id)

        # Build prompt
        prompt = self.REVIEW_PROMPT.format(
            bible_content=bible_content,
            script_content=json.dumps(script_data, indent=2)
        )

        try:
            # Call Claude Opus 4.5
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4000,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            # Parse response
            content = response.content[0].text
            review_data = self._parse_json_response(content)

            logger.info(f"Review complete: score={review_data.get('overall_score')}, ready={review_data.get('ready_for_approval')}")
            return review_data

        except Exception as e:
            logger.error(f"Script review failed: {e}")
            raise

    async def revise_script(
        self,
        original_script: Dict[str, Any],
        review_result: Dict[str, Any],
        brand_id: UUID,
        human_notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a revised version of the script.

        Args:
            original_script: Original script dictionary
            review_result: Review result with issues
            brand_id: Brand UUID for bible context
            human_notes: Optional notes from human reviewer

        Returns:
            Revised script dictionary
        """
        self._ensure_client()

        logger.info("Revising script based on feedback")

        # Get full bible content
        bible_content = await self.get_full_bible_content(brand_id)

        # Build prompt
        prompt = self.REVISION_PROMPT.format(
            bible_content=bible_content,
            original_script=json.dumps(original_script, indent=2),
            review_feedback=json.dumps(review_result, indent=2),
            human_notes=human_notes or "No additional notes from human reviewer."
        )

        try:
            # Call Claude Opus 4.5
            response = self.client.messages.create(
                model=self.model,
                max_tokens=8000,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            # Parse response
            content = response.content[0].text
            revised_script = self._parse_json_response(content)

            # Update metadata
            revised_script["id"] = str(uuid4())
            revised_script["project_id"] = original_script.get("project_id")
            revised_script["version_number"] = original_script.get("version_number", 1) + 1
            revised_script["created_at"] = datetime.utcnow().isoformat()
            revised_script["status"] = "draft"
            revised_script["previous_version_id"] = original_script.get("id")

            logger.info(f"Created revision v{revised_script['version_number']}")
            return revised_script

        except Exception as e:
            logger.error(f"Script revision failed: {e}")
            raise

    def _parse_json_response(self, content: str) -> Dict[str, Any]:
        """
        Parse JSON from LLM response, handling common formatting issues.

        Args:
            content: Raw response content

        Returns:
            Parsed JSON as dict
        """
        content = content.strip()

        # Remove markdown code blocks if present
        if content.startswith("```"):
            lines = content.split("\n")
            # Find start and end of code block
            start_idx = 1 if lines[0].startswith("```") else 0
            end_idx = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
            content = "\n".join(lines[start_idx:end_idx])

        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}")
            logger.debug(f"Raw content: {content[:1000]}")
            raise ValueError(f"Failed to parse LLM response as JSON: {e}")

    # =========================================================================
    # ELS Conversion (MVP 3)
    # =========================================================================

    # Valid pace values for ELS format
    VALID_PACES = {"slow", "deliberate", "normal", "quick", "fast", "chaos"}

    # Valid character names for ELS format
    VALID_CHARACTERS = {"every-coon", "boomer", "fed", "whale", "wojak", "chad"}

    def convert_to_els(
        self,
        script_data: Dict[str, Any],
        project_name: str = "trash-panda"
    ) -> str:
        """
        Convert script data to ELS format for audio production.

        This is a deterministic conversion (no LLM needed) that transforms
        the structured script beats into the ELS text format expected by
        the Audio Production system.

        Args:
            script_data: Script dictionary with beats array
            project_name: Project identifier (default: trash-panda)

        Returns:
            ELS-formatted string ready for audio production
        """
        lines = []

        # Build META block
        title = script_data.get("title", "Untitled Video")
        lines.append("[META]")
        lines.append(f"video_title: {title}")
        lines.append(f"project: {project_name}")
        lines.append("default_character: every-coon")
        lines.append("default_pace: normal")
        lines.append("")

        # Process each beat
        beats = script_data.get("beats", [])
        for beat in beats:
            beat_els = self._convert_beat_to_els(beat)
            lines.append(beat_els)
            lines.append("")  # Blank line between beats

        return "\n".join(lines)

    def _convert_beat_to_els(self, beat: Dict[str, Any]) -> str:
        """
        Convert a single beat to ELS format.

        Args:
            beat: Beat dictionary with script, character, etc.

        Returns:
            ELS-formatted string for this beat
        """
        lines = []

        # Beat header
        beat_id = beat.get("beat_id", "unknown")
        beat_name = beat.get("beat_name", "Unnamed Beat")
        lines.append(f"[BEAT: {beat_id}]")
        lines.append(f"name: {beat_name}")
        lines.append("---")

        # Character (validate and default to every-coon)
        character = beat.get("character", "every-coon")
        if character not in self.VALID_CHARACTERS:
            character = "every-coon"
        lines.append(f"[CHARACTER: {character}]")

        # Direction (from visual_notes or audio_notes)
        direction = beat.get("visual_notes") or beat.get("audio_notes") or beat.get("editor_notes")
        if direction:
            # Clean up direction - remove newlines, truncate if too long
            direction = direction.replace("\n", " ").strip()
            if len(direction) > 200:
                direction = direction[:197] + "..."
            lines.append(f"[DIRECTION: {direction}]")

        # Pace (infer from beat context or default to normal)
        pace = self._infer_pace_from_beat(beat)
        lines.append(f"[PACE: {pace}]")

        # Script content
        script = beat.get("script", "")
        if script:
            # Process emphasis markers for ELS
            # *word* = light emphasis (keep as-is)
            # **word** = strong emphasis (keep as-is, will be converted to UPPERCASE by parser)
            # Split long lines to stay under 500 char ELS limit
            script_lines = self._split_long_lines(script, max_length=450)
            lines.extend(script_lines)

        # Pause (default 100ms between beats)
        pause_ms = beat.get("pause_ms", 100)
        lines.append(f"[PAUSE: {pause_ms}ms]")

        lines.append("[END_BEAT]")

        return "\n".join(lines)

    def _infer_pace_from_beat(self, beat: Dict[str, Any]) -> str:
        """
        Infer the appropriate pace for a beat based on its context.

        Args:
            beat: Beat dictionary

        Returns:
            Pace string (slow, deliberate, normal, quick, fast, chaos)
        """
        beat_name = beat.get("beat_name", "").lower()
        beat_id = beat.get("beat_id", "").lower()
        editor_notes = (beat.get("editor_notes") or "").lower()
        audio_notes = (beat.get("audio_notes") or "").lower()
        combined_notes = f"{editor_notes} {audio_notes}"

        # Check for explicit pace hints in notes
        if "chaos" in combined_notes or "frantic" in combined_notes:
            return "chaos"
        if "fast" in combined_notes or "quick" in combined_notes or "rapid" in combined_notes:
            return "fast"
        if "slow" in combined_notes or "deliberate" in combined_notes or "measured" in combined_notes:
            return "slow"

        # Infer from beat type
        if "hook" in beat_name or "hook" in beat_id:
            return "fast"  # Hooks should be punchy
        if "climax" in beat_name or "chaos" in beat_name:
            return "chaos"
        if "setup" in beat_name or "explain" in beat_name:
            return "normal"
        if "summary" in beat_name or "recap" in beat_name:
            return "deliberate"
        if "cta" in beat_name or "cta" in beat_id:
            return "normal"

        # Check character for pace hints
        character = beat.get("character", "")
        if character == "boomer":
            return "slow"  # Boomers speak slower
        if character == "fed":
            return "deliberate"  # Fed is monotone, measured
        if character == "wojak":
            return "fast"  # Wojak is panicked
        if character == "chad":
            return "quick"  # Chad is fast-talking

        return "normal"

    def _split_long_lines(self, text: str, max_length: int = 450) -> List[str]:
        """
        Split text into lines that don't exceed max_length.

        Splits at sentence boundaries (. ! ?) when possible,
        otherwise splits at word boundaries.

        Args:
            text: Text to split
            max_length: Maximum characters per line

        Returns:
            List of lines, each under max_length
        """
        if len(text) <= max_length:
            return [text]

        result = []
        remaining = text.strip()

        while remaining:
            if len(remaining) <= max_length:
                result.append(remaining)
                break

            # Try to split at sentence boundary
            split_pos = -1
            for punct in ['. ', '! ', '? ']:
                pos = remaining.rfind(punct, 0, max_length)
                if pos > split_pos:
                    split_pos = pos + len(punct) - 1  # Include the punctuation

            # If no sentence boundary, split at word boundary
            if split_pos <= 0:
                split_pos = remaining.rfind(' ', 0, max_length)

            # If still no good split point, force split
            if split_pos <= 0:
                split_pos = max_length

            result.append(remaining[:split_pos].strip())
            remaining = remaining[split_pos:].strip()

        return result

    # =========================================================================
    # Database Operations
    # =========================================================================

    async def save_script_to_db(
        self,
        project_id: UUID,
        script_data: Dict[str, Any]
    ) -> UUID:
        """
        Save a script version to the database.

        Args:
            project_id: Content project UUID
            script_data: Script data dictionary

        Returns:
            Created script_version UUID
        """
        if not self.supabase:
            logger.warning("Supabase not configured - script not saved")
            return UUID(script_data.get("id", str(uuid4())))

        try:
            # Query for the next version number (don't trust passed value)
            existing = self.supabase.table("script_versions").select("version_number").eq(
                "project_id", str(project_id)
            ).order("version_number", desc=True).limit(1).execute()

            if existing.data:
                next_version = existing.data[0]["version_number"] + 1
            else:
                next_version = 1

            logger.info(f"Saving script version {next_version} for project {project_id}")

            # Extract content for storage
            script_content = json.dumps({
                "title": script_data.get("title"),
                "beats": script_data.get("beats"),
                "hook_formula_used": script_data.get("hook_formula_used"),
                "target_duration_seconds": script_data.get("target_duration_seconds")
            })

            els_content = script_data.get("els_script", "")

            result = self.supabase.table("script_versions").insert({
                "project_id": str(project_id),
                "version_number": next_version,
                "script_content": script_content,
                "storyboard_json": {
                    "beats": script_data.get("beats", []),
                    "thumbnail_suggestions": script_data.get("thumbnail_suggestions", []),
                    "cta_target": script_data.get("cta_target")
                },
                "status": "draft"
            }).execute()

            if result.data:
                script_id = UUID(result.data[0]["id"])
                logger.info(f"Saved script version {script_id}")

                # Update project with current script version
                self.supabase.table("content_projects").update({
                    "current_script_version_id": str(script_id),
                    "workflow_state": "script_review"
                }).eq("id", str(project_id)).execute()

                return script_id

            return UUID(script_data.get("id", str(uuid4())))

        except Exception as e:
            logger.error(f"Failed to save script: {e}")
            raise

    async def save_review_to_db(
        self,
        script_version_id: UUID,
        review_data: Dict[str, Any]
    ) -> None:
        """
        Save review results to the script version.

        Args:
            script_version_id: Script version UUID
            review_data: Review result dictionary
        """
        if not self.supabase:
            logger.warning("Supabase not configured - review not saved")
            return

        try:
            # Save the full review data (includes overall_score, ready_for_approval, checklist_results)
            self.supabase.table("script_versions").update({
                "checklist_results": review_data,  # Save full review, not just nested checklist
                "reviewer_notes": json.dumps(review_data.get("issues_found", [])),
                "improvement_suggestions": review_data.get("improvement_suggestions")
            }).eq("id", str(script_version_id)).execute()

            logger.info(f"Saved review for script {script_version_id} (score: {review_data.get('overall_score')})")

        except Exception as e:
            logger.error(f"Failed to save review: {e}")

    async def get_script_version(
        self,
        script_version_id: UUID
    ) -> Optional[Dict[str, Any]]:
        """
        Get a script version by ID.

        Args:
            script_version_id: Script version UUID

        Returns:
            Script version dictionary or None
        """
        if not self.supabase:
            return None

        try:
            result = self.supabase.table("script_versions").select("*").eq(
                "id", str(script_version_id)
            ).execute()

            if result.data:
                return result.data[0]
            return None

        except Exception as e:
            logger.error(f"Failed to fetch script: {e}")
            return None

    async def approve_script(
        self,
        script_version_id: UUID,
        project_id: UUID,
        human_notes: Optional[str] = None
    ) -> None:
        """
        Approve a script version.

        Args:
            script_version_id: Script version UUID to approve
            project_id: Content project UUID
            human_notes: Optional approval notes
        """
        if not self.supabase:
            logger.warning("Supabase not configured")
            return

        try:
            # Update script status
            self.supabase.table("script_versions").update({
                "status": "approved",
                "human_notes": human_notes,
                "approved_at": datetime.utcnow().isoformat()
            }).eq("id", str(script_version_id)).execute()

            # Update project workflow state
            self.supabase.table("content_projects").update({
                "workflow_state": "script_approved"
            }).eq("id", str(project_id)).execute()

            logger.info(f"Approved script {script_version_id}")

        except Exception as e:
            logger.error(f"Failed to approve script: {e}")
            raise

    async def save_els_to_db(
        self,
        project_id: UUID,
        script_version_id: UUID,
        els_content: str,
        source_type: str = "video"
    ) -> UUID:
        """
        Save ELS content to the els_versions table.

        Args:
            project_id: Content project UUID
            script_version_id: Source script version UUID
            els_content: ELS-formatted string
            source_type: 'video' for main script, 'comic' for comic audio

        Returns:
            Created els_version UUID
        """
        if not self.supabase:
            logger.warning("Supabase not configured - ELS not saved")
            return uuid4()

        try:
            # Get next version number for this project/source_type
            existing = self.supabase.table("els_versions").select("version_number").eq(
                "project_id", str(project_id)
            ).eq(
                "source_type", source_type
            ).order("version_number", desc=True).limit(1).execute()

            if existing.data:
                next_version = existing.data[0]["version_number"] + 1
            else:
                next_version = 1

            logger.info(f"Saving ELS version {next_version} for project {project_id}")

            result = self.supabase.table("els_versions").insert({
                "project_id": str(project_id),
                "script_version_id": str(script_version_id),
                "version_number": next_version,
                "els_content": els_content,
                "source_type": source_type
            }).execute()

            if result.data:
                els_id = UUID(result.data[0]["id"])
                logger.info(f"Saved ELS version {els_id}")

                # Update project with current ELS version
                self.supabase.table("content_projects").update({
                    "current_els_version_id": str(els_id),
                    "workflow_state": "els_ready"
                }).eq("id", str(project_id)).execute()

                return els_id

            return uuid4()

        except Exception as e:
            logger.error(f"Failed to save ELS: {e}")
            raise

    async def get_els_version(
        self,
        project_id: UUID,
        source_type: str = "video"
    ) -> Optional[Dict[str, Any]]:
        """
        Get the latest ELS version for a project.

        Args:
            project_id: Content project UUID
            source_type: 'video' or 'comic'

        Returns:
            ELS version dictionary or None
        """
        if not self.supabase:
            return None

        try:
            result = self.supabase.table("els_versions").select("*").eq(
                "project_id", str(project_id)
            ).eq(
                "source_type", source_type
            ).order("version_number", desc=True).limit(1).execute()

            if result.data:
                return result.data[0]
            return None

        except Exception as e:
            logger.error(f"Failed to fetch ELS version: {e}")
            return None

    async def link_audio_session(
        self,
        project_id: UUID,
        els_version_id: UUID,
        audio_session_id: UUID
    ) -> None:
        """
        Link an audio production session to the ELS version and project.

        Args:
            project_id: Content project UUID
            els_version_id: ELS version UUID
            audio_session_id: Audio production session UUID
        """
        if not self.supabase:
            logger.warning("Supabase not configured")
            return

        try:
            # Update ELS version with audio session
            self.supabase.table("els_versions").update({
                "audio_session_id": str(audio_session_id)
            }).eq("id", str(els_version_id)).execute()

            # Update project with audio session
            self.supabase.table("content_projects").update({
                "audio_session_id": str(audio_session_id),
                "workflow_state": "audio_production"
            }).eq("id", str(project_id)).execute()

            logger.info(f"Linked audio session {audio_session_id} to project {project_id}")

        except Exception as e:
            logger.error(f"Failed to link audio session: {e}")
            raise
