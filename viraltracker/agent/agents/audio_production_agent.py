"""
Audio Production Agent - Specialized agent for ElevenLabs audio generation.

This agent orchestrates the audio production workflow:
1. Validate and parse ELS scripts
2. Create production sessions
3. Generate audio for each beat
4. Manage takes and selection
5. Export final audio

Tools follow Pydantic AI best practices with @agent.tool() decorator.
"""

import logging
import asyncio
from typing import Dict, List, Optional, Any
from pathlib import Path
from pydantic_ai import Agent, RunContext
from ..dependencies import AgentDependencies

logger = logging.getLogger(__name__)

from ...core.config import Config

# Create Audio Production Agent
audio_production_agent = Agent(
    model=Config.get_model("audio_production"),
    deps_type=AgentDependencies,
    system_prompt="""You are the Audio Production specialist agent.

Your ONLY responsibility is generating voice audio from ELS scripts:
- Validating ElevenLabs Script (ELS) format
- Parsing scripts into structured beats
- Managing production sessions
- Generating audio via ElevenLabs API
- Adding pauses via FFmpeg post-processing
- Managing takes and selection
- Exporting final audio files

CRITICAL RULES:
1. Direction tags are NOT sent to ElevenLabs (they inform settings only)
2. Pauses are added via FFmpeg, not SSML (more reliable)
3. Generate beats ONE AT A TIME for resilience
4. Each character has voice settings in database - look them up
5. Speed must be between 0.7 and 1.2 (ElevenLabs API limit)

You have access to 11 specialized tools for this workflow.
"""
)


# ============================================================================
# VALIDATION & PARSING TOOLS
# ============================================================================

@audio_production_agent.tool(
    metadata={
        'category': 'Filtration',
        'platform': 'All',
        'rate_limit': '60/minute',
        'use_cases': [
            'Validate ELS script format before processing',
            'Check for syntax errors in script',
            'Get beat and character counts'
        ],
        'examples': [
            'Validate my ELS script',
            'Check if this script is valid'
        ]
    }
)
async def validate_els_script(
    ctx: RunContext[AgentDependencies],
    els_content: str
) -> Dict:
    """
    Validate ELS script format without parsing.

    Checks for:
    - Required [META] block
    - Matching [BEAT:] and [END_BEAT] tags
    - Valid character names
    - Valid pace values
    - Line length limits (500 chars max)

    Args:
        ctx: Run context with AgentDependencies
        els_content: The ELS script content to validate

    Returns:
        Dictionary with validation results:
        {
            "is_valid": true/false,
            "errors": ["error1", ...],
            "warnings": ["warning1", ...],
            "beat_count": 8,
            "character_count": {"every-coon": 6, "boomer": 2}
        }
    """
    from viraltracker.services.els_parser_service import validate_els

    logger.info("Validating ELS script")
    result = validate_els(els_content)

    return {
        "is_valid": result.is_valid,
        "errors": result.errors,
        "warnings": result.warnings,
        "beat_count": result.beat_count,
        "character_count": result.character_count
    }


@audio_production_agent.tool(
    metadata={
        'category': 'Filtration',
        'platform': 'All',
        'rate_limit': '30/minute',
        'use_cases': [
            'Parse ELS script into structured beats',
            'Extract metadata from script',
            'Prepare script for audio generation'
        ],
        'examples': [
            'Parse this ELS script',
            'Extract beats from script'
        ]
    }
)
async def parse_els_script(
    ctx: RunContext[AgentDependencies],
    els_content: str
) -> Dict:
    """
    Parse ELS script into structured beat data.

    Extracts:
    - Video title and project from [META]
    - Each beat with character, direction, pace
    - Individual lines with pause values
    - Combined script text for generation

    Args:
        ctx: Run context with AgentDependencies
        els_content: The ELS script content to parse

    Returns:
        Dictionary with parsed data including video_title, project, and beats array

    Raises:
        ValueError: If script is invalid
    """
    from viraltracker.services.els_parser_service import parse_els

    logger.info("Parsing ELS script")
    result = parse_els(els_content)

    return {
        "video_title": result.video_title,
        "project": result.project,
        "default_character": result.default_character.value,
        "default_pace": result.default_pace.value,
        "beats": [beat.model_dump(mode='json') for beat in result.beats]
    }


# ============================================================================
# SESSION MANAGEMENT TOOLS
# ============================================================================

@audio_production_agent.tool(
    metadata={
        'category': 'Ingestion',
        'platform': 'All',
        'rate_limit': '10/minute',
        'use_cases': [
            'Create new audio production session',
            'Initialize session from parsed script',
            'Start new audio project'
        ],
        'examples': [
            'Create session for my script',
            'Start new audio production'
        ]
    }
)
async def create_production_session(
    ctx: RunContext[AgentDependencies],
    video_title: str,
    project_name: str,
    beats_json: List[Dict],
    source_els: Optional[str] = None
) -> Dict:
    """
    Create a new production session in database.

    Args:
        ctx: Run context with AgentDependencies
        video_title: Title of the video
        project_name: Project name (e.g., "trash-panda")
        beats_json: List of beat dictionaries from parse_els_script
        source_els: Optional original ELS content

    Returns:
        Dictionary with session_id and status
    """
    from viraltracker.services.audio_models import ScriptBeat

    logger.info(f"Creating production session: {video_title}")

    # Convert beat dicts back to ScriptBeat objects
    beats = [ScriptBeat(**b) for b in beats_json]

    session = await ctx.deps.audio_production.create_session(
        video_title=video_title,
        project_name=project_name,
        beats=beats,
        source_els=source_els
    )

    return {
        "session_id": session.session_id,
        "status": session.status,
        "beat_count": len(session.beats)
    }


@audio_production_agent.tool(
    metadata={
        'category': 'Ingestion',
        'platform': 'All',
        'rate_limit': '30/minute',
        'use_cases': [
            'Load existing production session',
            'Get session with all takes',
            'Resume previous session'
        ],
        'examples': [
            'Load session abc123',
            'Get my previous session'
        ]
    }
)
async def get_production_session(
    ctx: RunContext[AgentDependencies],
    session_id: str
) -> Dict:
    """
    Load a production session with all beats and takes.

    Args:
        ctx: Run context with AgentDependencies
        session_id: UUID of the session

    Returns:
        Full session data including beats, takes, and status
    """
    logger.info(f"Loading session: {session_id}")

    session = await ctx.deps.audio_production.get_session(session_id)

    return {
        "session_id": session.session_id,
        "video_title": session.video_title,
        "project_name": session.project_name,
        "status": session.status,
        "beats": [
            {
                "beat_id": bwt.beat.beat_id,
                "beat_name": bwt.beat.beat_name,
                "character": bwt.beat.character.value,
                "combined_script": bwt.beat.combined_script,
                "primary_direction": bwt.beat.primary_direction,
                "takes": [
                    {
                        "take_id": t.take_id,
                        "audio_path": t.audio_path,
                        "audio_duration_ms": t.audio_duration_ms,
                        "is_selected": t.is_selected
                    }
                    for t in bwt.takes
                ],
                "selected_take_id": bwt.selected_take_id
            }
            for bwt in session.beats
        ],
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat()
    }


# ============================================================================
# VOICE PROFILE TOOLS
# ============================================================================

@audio_production_agent.tool(
    metadata={
        'category': 'Ingestion',
        'platform': 'All',
        'rate_limit': '30/minute',
        'use_cases': [
            'Get voice settings for a character',
            'Look up voice ID and settings',
            'Check character configuration'
        ],
        'examples': [
            'Get voice profile for every-coon',
            'What are boomers voice settings'
        ]
    }
)
async def get_voice_profile(
    ctx: RunContext[AgentDependencies],
    character_name: str
) -> Dict:
    """
    Get voice profile for a character from database.

    Args:
        ctx: Run context with AgentDependencies
        character_name: Character name (e.g., "every-coon", "boomer")

    Returns:
        Voice profile with voice_id and settings
    """
    from viraltracker.services.audio_models import Character

    logger.info(f"Getting voice profile for: {character_name}")

    char = Character(character_name.lower())
    profile = await ctx.deps.elevenlabs.get_voice_profile(char)

    return {
        "character": profile.character.value,
        "voice_id": profile.voice_id,
        "display_name": profile.display_name,
        "description": profile.description,
        "stability": profile.stability,
        "similarity_boost": profile.similarity_boost,
        "style": profile.style,
        "speed": profile.speed
    }


@audio_production_agent.tool(
    metadata={
        'category': 'Ingestion',
        'platform': 'All',
        'rate_limit': '30/minute',
        'use_cases': [
            'List all character voice profiles',
            'See available characters',
            'Check voice configurations'
        ],
        'examples': [
            'List all voice profiles',
            'Show me all characters'
        ]
    }
)
async def list_voice_profiles(
    ctx: RunContext[AgentDependencies]
) -> List[Dict]:
    """
    Get all voice profiles from database.

    Args:
        ctx: Run context with AgentDependencies

    Returns:
        List of all character voice profiles
    """
    logger.info("Listing all voice profiles")

    profiles = await ctx.deps.audio_production.get_all_voice_profiles()

    return [
        {
            "character": p.character.value,
            "display_name": p.display_name,
            "voice_id": p.voice_id,
            "stability": p.stability,
            "style": p.style,
            "speed": p.speed
        }
        for p in profiles
    ]


# ============================================================================
# AUDIO GENERATION TOOLS
# ============================================================================

@audio_production_agent.tool(
    metadata={
        'category': 'Generation',
        'platform': 'All',
        'rate_limit': '5/minute',
        'use_cases': [
            'Generate audio for a single beat',
            'Create voice audio from script',
            'Generate with specific settings'
        ],
        'examples': [
            'Generate audio for beat 01_hook',
            'Create audio for the first beat'
        ]
    }
)
async def generate_beat_audio(
    ctx: RunContext[AgentDependencies],
    session_id: str,
    beat_json: Dict
) -> Dict:
    """
    Generate audio for a single beat.

    Process:
    1. Load character voice profile from database
    2. Merge beat settings with character defaults
    3. Generate audio via ElevenLabs (clean text, no SSML)
    4. Add pauses via FFmpeg post-processing
    5. Get duration and save take to database

    Args:
        ctx: Run context with AgentDependencies
        session_id: Production session ID
        beat_json: Beat data dictionary

    Returns:
        Take data with audio path and duration
    """
    from viraltracker.services.audio_models import ScriptBeat

    beat = ScriptBeat(**beat_json)
    logger.info(f"Generating audio for beat: {beat.beat_id}")

    # Output directory
    output_dir = Path("audio_production") / session_id
    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate via ElevenLabs
    take = await ctx.deps.elevenlabs.generate_beat_audio(
        beat=beat,
        output_dir=output_dir,
        session_id=session_id
    )

    # Add pause after beat via FFmpeg (sync calls wrapped for async)
    if beat.pause_after_ms > 0:
        audio_path = Path(take.audio_path)
        temp_path = audio_path.with_suffix('.temp.mp3')

        success = await asyncio.to_thread(
            ctx.deps.ffmpeg.add_silence_after,
            audio_path,
            temp_path,
            beat.pause_after_ms
        )

        if success and temp_path.exists():
            temp_path.rename(audio_path)

    # Get final duration (sync call wrapped for async)
    audio_path = Path(take.audio_path)
    take.audio_duration_ms = await asyncio.to_thread(
        ctx.deps.ffmpeg.get_duration_ms, audio_path
    )

    # Save to database
    await ctx.deps.audio_production.save_take(session_id, take)

    # Auto-select first take
    await ctx.deps.audio_production.select_take(session_id, beat.beat_id, take.take_id)

    return {
        "take_id": take.take_id,
        "beat_id": take.beat_id,
        "audio_path": take.audio_path,
        "audio_duration_ms": take.audio_duration_ms,
        "settings_used": take.generation_settings.model_dump()
    }


@audio_production_agent.tool(
    metadata={
        'category': 'Generation',
        'platform': 'All',
        'rate_limit': '5/minute',
        'use_cases': [
            'Regenerate audio with different settings',
            'Create alternative take for beat',
            'Adjust voice and try again'
        ],
        'examples': [
            'Regenerate beat 01_hook with slower pace',
            'Create new take with more stability'
        ]
    }
)
async def regenerate_beat_audio(
    ctx: RunContext[AgentDependencies],
    session_id: str,
    beat_id: str,
    new_direction: Optional[str] = None,
    new_pace: Optional[str] = None,
    stability: Optional[float] = None,
    style: Optional[float] = None
) -> Dict:
    """
    Generate a new take for a beat with modified settings.

    Preserves existing takes - adds a new one with the specified overrides.

    Args:
        ctx: Run context with AgentDependencies
        session_id: Production session ID
        beat_id: ID of beat to regenerate
        new_direction: Optional new direction text
        new_pace: Optional new pace (slow, normal, fast, etc.)
        stability: Optional stability override (0-1)
        style: Optional style override (0-1)

    Returns:
        New take data
    """
    from viraltracker.services.audio_models import ScriptBeat, VoiceSettings, Pace

    logger.info(f"Regenerating beat: {beat_id}")

    # Load session to get beat
    session = await ctx.deps.audio_production.get_session(session_id)

    # Find the beat
    bwt = next((b for b in session.beats if b.beat.beat_id == beat_id), None)
    if not bwt:
        raise ValueError(f"Beat not found: {beat_id}")

    # Create modified beat
    beat = bwt.beat.model_copy(deep=True)

    if new_direction:
        beat.primary_direction = new_direction

    # Apply setting overrides
    if any([stability is not None, style is not None, new_pace]):
        current = beat.settings_override or VoiceSettings()
        beat.settings_override = VoiceSettings(
            stability=stability if stability is not None else current.stability,
            style=style if style is not None else current.style,
            speed=Pace(new_pace).to_speed() if new_pace else current.speed
        )

    # Generate new take
    output_dir = Path("audio_production") / session_id
    take = await ctx.deps.elevenlabs.generate_beat_audio(
        beat=beat,
        output_dir=output_dir,
        session_id=session_id
    )

    # Add pause after (sync FFmpeg calls wrapped for async)
    if beat.pause_after_ms > 0:
        audio_path = Path(take.audio_path)
        temp_path = audio_path.with_suffix('.temp.mp3')

        success = await asyncio.to_thread(
            ctx.deps.ffmpeg.add_silence_after,
            audio_path,
            temp_path,
            beat.pause_after_ms
        )

        if success and temp_path.exists():
            temp_path.rename(audio_path)

    # Get duration (sync call wrapped for async)
    take.audio_duration_ms = await asyncio.to_thread(
        ctx.deps.ffmpeg.get_duration_ms, Path(take.audio_path)
    )

    # Save to database
    await ctx.deps.audio_production.save_take(session_id, take)

    return {
        "take_id": take.take_id,
        "beat_id": take.beat_id,
        "audio_path": take.audio_path,
        "audio_duration_ms": take.audio_duration_ms,
        "settings_used": take.generation_settings.model_dump()
    }


# ============================================================================
# SELECTION & EXPORT TOOLS
# ============================================================================

@audio_production_agent.tool(
    metadata={
        'category': 'Filtration',
        'platform': 'All',
        'rate_limit': '30/minute',
        'use_cases': [
            'Select which take to use for a beat',
            'Choose best audio take',
            'Set active take'
        ],
        'examples': [
            'Select take abc123 for beat 01_hook',
            'Use this take for the hook'
        ]
    }
)
async def select_take(
    ctx: RunContext[AgentDependencies],
    session_id: str,
    beat_id: str,
    take_id: str
) -> Dict:
    """
    Select which take to use for a beat.

    Args:
        ctx: Run context with AgentDependencies
        session_id: Production session ID
        beat_id: Beat ID
        take_id: Take ID to select

    Returns:
        Confirmation
    """
    logger.info(f"Selecting take {take_id} for beat {beat_id}")

    await ctx.deps.audio_production.select_take(session_id, beat_id, take_id)

    return {
        "success": True,
        "beat_id": beat_id,
        "selected_take_id": take_id
    }


@audio_production_agent.tool(
    metadata={
        'category': 'Export',
        'platform': 'All',
        'rate_limit': '10/minute',
        'use_cases': [
            'Export all selected takes',
            'Save final audio files',
            'Complete production'
        ],
        'examples': [
            'Export selected takes',
            'Save final audio'
        ]
    }
)
async def export_selected_takes(
    ctx: RunContext[AgentDependencies],
    session_id: str,
    output_path: Optional[str] = None
) -> Dict:
    """
    Export all selected takes with clean filenames.

    Output: 01_hook.mp3, 02_setup.mp3, etc.

    Args:
        ctx: Run context with AgentDependencies
        session_id: Production session ID
        output_path: Optional custom output directory

    Returns:
        List of exported files
    """
    logger.info(f"Exporting selected takes for session {session_id}")

    out_dir = Path(output_path) if output_path else None

    exported = await ctx.deps.audio_production.export_selected_takes(
        session_id=session_id,
        output_dir=out_dir
    )

    return {
        "exported_files": [str(f) for f in exported],
        "count": len(exported),
        "export_path": str(exported[0].parent) if exported else None
    }


@audio_production_agent.tool(
    metadata={
        'category': 'Ingestion',
        'platform': 'All',
        'rate_limit': '30/minute',
        'use_cases': [
            'Update session status',
            'Mark session as complete',
            'Change session state'
        ],
        'examples': [
            'Mark session as completed',
            'Update status to in_progress'
        ]
    }
)
async def update_session_status(
    ctx: RunContext[AgentDependencies],
    session_id: str,
    status: str
) -> Dict:
    """
    Update session status.

    Valid statuses: draft, generating, in_progress, completed, exported

    Args:
        ctx: Run context with AgentDependencies
        session_id: Production session ID
        status: New status

    Returns:
        Confirmation
    """
    valid_statuses = ["draft", "generating", "in_progress", "completed", "exported"]
    if status not in valid_statuses:
        raise ValueError(f"Invalid status. Must be one of: {valid_statuses}")

    await ctx.deps.audio_production.update_session_status(session_id, status)

    return {"success": True, "status": status}


# ============================================================================
# COMPLETE WORKFLOW ORCHESTRATION
# ============================================================================

async def complete_audio_workflow(
    ctx: RunContext[AgentDependencies],
    els_content: str,
    project_name: str = "trash-panda"
) -> Dict:
    """
    Execute complete audio production workflow from start to finish.

    This orchestration function:
    1. Validates ELS script
    2. Parses into structured beats
    3. Creates production session
    4. Generates audio for each beat (ONE AT A TIME)
    5. Adds pauses via FFmpeg
    6. Auto-selects first take per beat
    7. Returns complete session with all takes

    Called directly by Streamlit UI, similar to complete_ad_workflow.

    Args:
        ctx: Run context with AgentDependencies
        els_content: The ELS script content
        project_name: Project name override (default: from script)

    Returns:
        Complete session data with all beats and takes
    """
    from datetime import datetime
    from viraltracker.services.els_parser_service import validate_els, parse_els
    from viraltracker.services.audio_models import ScriptBeat

    logger.info("=== STARTING COMPLETE AUDIO WORKFLOW ===")

    # Step 1: Validate
    logger.info("Step 1: Validating ELS script")
    validation = validate_els(els_content)

    if not validation.is_valid:
        raise ValueError(f"Invalid ELS script: {'; '.join(validation.errors)}")

    logger.info(
        f"Validation passed: {validation.beat_count} beats, "
        f"characters: {validation.character_count}"
    )

    # Step 2: Parse
    logger.info("Step 2: Parsing ELS script")
    parsed = parse_els(els_content)

    video_title = parsed.video_title or "Untitled"
    project = project_name or parsed.project or "trash-panda"

    logger.info(f"Parsed: '{video_title}' with {len(parsed.beats)} beats")

    # Step 3: Create session
    logger.info("Step 3: Creating production session")
    session = await ctx.deps.audio_production.create_session(
        video_title=video_title,
        project_name=project,
        beats=parsed.beats,
        source_els=els_content
    )

    session_id = session.session_id
    logger.info(f"Created session: {session_id}")

    # Step 4: Update status to generating
    await ctx.deps.audio_production.update_session_status(session_id, "generating")

    # Step 5: Generate audio for each beat (ONE AT A TIME for resilience)
    logger.info("Step 5: Generating audio for all beats")
    output_dir = Path("audio_production") / session_id

    generated_takes = []
    total_duration_ms = 0

    for i, beat in enumerate(parsed.beats):
        logger.info(f"Generating beat {i+1}/{len(parsed.beats)}: {beat.beat_id}")

        try:
            # Generate via ElevenLabs
            take = await ctx.deps.elevenlabs.generate_beat_audio(
                beat=beat,
                output_dir=output_dir,
                session_id=session_id
            )

            # Add pause after beat via FFmpeg (sync calls wrapped for async)
            if beat.pause_after_ms > 0:
                audio_path = Path(take.audio_path)
                temp_path = audio_path.with_suffix('.temp.mp3')

                success = await asyncio.to_thread(
                    ctx.deps.ffmpeg.add_silence_after,
                    audio_path,
                    temp_path,
                    beat.pause_after_ms
                )

                if success and temp_path.exists():
                    temp_path.rename(audio_path)

            # Get final duration (sync call wrapped for async)
            audio_path = Path(take.audio_path)
            take.audio_duration_ms = await asyncio.to_thread(
                ctx.deps.ffmpeg.get_duration_ms, audio_path
            )
            total_duration_ms += take.audio_duration_ms

            # Upload to Supabase Storage for persistence
            if audio_path.exists():
                audio_data = audio_path.read_bytes()
                storage_path = await ctx.deps.audio_production.upload_audio(
                    session_id=session_id,
                    filename=audio_path.name,
                    audio_data=audio_data
                )
                take.audio_path = storage_path  # Update to storage path
                logger.info(f"Uploaded to storage: {storage_path}")

            # Save to database
            await ctx.deps.audio_production.save_take(session_id, take)

            # Auto-select first take
            await ctx.deps.audio_production.select_take(
                session_id, beat.beat_id, take.take_id
            )

            generated_takes.append({
                "beat_id": beat.beat_id,
                "beat_name": beat.beat_name,
                "take_id": take.take_id,
                "audio_path": take.audio_path,
                "audio_duration_ms": take.audio_duration_ms,
                "character": beat.character.value
            })

            logger.info(f"Generated {beat.beat_id}: {take.audio_duration_ms}ms")

        except Exception as e:
            logger.error(f"Failed to generate beat {beat.beat_id}: {str(e)}")
            # Continue with other beats
            generated_takes.append({
                "beat_id": beat.beat_id,
                "beat_name": beat.beat_name,
                "error": str(e)
            })

    # Step 6: Update status to in_progress
    await ctx.deps.audio_production.update_session_status(session_id, "in_progress")

    # Build summary
    successful = len([t for t in generated_takes if "take_id" in t])
    failed = len([t for t in generated_takes if "error" in t])
    total_sec = total_duration_ms / 1000

    summary = f"Generated {successful}/{len(parsed.beats)} beats, {total_sec:.1f} seconds total"
    if failed > 0:
        summary += f" ({failed} failed)"

    logger.info(f"=== WORKFLOW COMPLETE: {summary} ===")

    return {
        "session_id": session_id,
        "video_title": video_title,
        "project_name": project,
        "status": "in_progress",
        "beats": generated_takes,
        "total_duration_ms": total_duration_ms,
        "summary": summary,
        "created_at": datetime.utcnow().isoformat()
    }


logger.info("Audio Production Agent initialized with 11 tools")
