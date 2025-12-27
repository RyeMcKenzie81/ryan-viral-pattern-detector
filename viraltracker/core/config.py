"""
Configuration management for ViralTracker
"""

import os
import yaml
from pathlib import Path
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class Config:
    """Application configuration"""

    # Supabase
    SUPABASE_URL: str = os.getenv('SUPABASE_URL', '')
    SUPABASE_SERVICE_KEY: str = os.getenv('SUPABASE_SERVICE_KEY', '')

    # Apify
    APIFY_TOKEN: str = os.getenv('APIFY_TOKEN', '')

    # Gemini
    GEMINI_API_KEY: str = os.getenv('GEMINI_API_KEY', '')
    GEMINI_VIDEO_MODEL: str = 'models/gemini-2.5-pro'  # Gemini 2.5 Pro for video analysis
    GEMINI_IMAGE_MODEL: str = 'models/gemini-3-pro-image-preview'  # Updated to Gemini 3 Pro

    # OpenAI / Sora
    OPENAI_API_KEY: str = os.getenv('OPENAI_API_KEY', '')
    SORA_MODELS: Dict[str, float] = {
        'sora-2-2025-10-06': 0.10,
        'sora-2-pro-2025-10-06': 0.50
    }
    RESEND_API_KEY: str = os.getenv('RESEND_API_KEY', '')
    EMAIL_FROM: str = os.getenv('EMAIL_FROM', 'noreply@viraltracker.io')

    # Slack
    SLACK_WEBHOOK_URL: str = os.getenv('SLACK_WEBHOOK_URL', '')

    # ElevenLabs (Audio Production)
    ELEVENLABS_API_KEY: str = os.getenv('ELEVENLABS_API_KEY', '')

    # Meta Ads API (Facebook/Instagram)
    META_GRAPH_API_TOKEN: str = os.getenv('META_GRAPH_API_TOKEN', '')
    META_AD_ACCOUNT_ID: str = os.getenv('META_AD_ACCOUNT_ID', '')  # e.g., "act_123456789"

    # Scraping defaults
    DEFAULT_DAYS_BACK: int = int(os.getenv('DAYS_BACK', '120'))
    DEFAULT_CONCURRENCY: int = int(os.getenv('CONCURRENCY', '5'))
    DEFAULT_POST_TYPE: str = os.getenv('POST_TYPE', 'reels')

    # Analysis defaults
    DEFAULT_SD_THRESHOLD: float = float(os.getenv('OUTLIER_SD_THRESHOLD', '3.0'))

    # Performance
    MAX_CONCURRENT_DOWNLOADS: int = int(os.getenv('MAX_CONCURRENT_DOWNLOADS', '3'))
    CHUNK_SIZE_FOR_DB_OPS: int = int(os.getenv('CHUNK_SIZE_FOR_DB_OPS', '1000'))

    @classmethod
    def validate(cls) -> bool:
        """Validate required configuration"""
        required = {
            'SUPABASE_URL': cls.SUPABASE_URL,
            'SUPABASE_SERVICE_KEY': cls.SUPABASE_SERVICE_KEY,
        }

        missing = [k for k, v in required.items() if not v]

        if missing:
            raise ValueError(f"Missing required configuration: {', '.join(missing)}")

        return True

    @classmethod
    def get(cls, key: str, default: Optional[str] = None) -> Optional[str]:
        """Get configuration value"""
        return getattr(cls, key, default)

    # ========================================================================
    # Model Configuration
    # ========================================================================
    
    # Model Defaults
    DEFAULT_MODEL = "claude-sonnet-4-5-20250929"
    COMPLEX_MODEL = "claude-opus-4-5-20251101"
    FAST_MODEL = "claude-sonnet-4-20250514"
    ORCHESTRATOR_MODEL = "openai:gpt-4o"  # Target change for orchestrator

    # Future capability-based models (User defined)
    # Pydantic AI requires 'google-gla:' prefix for models/ string format
    # BUT standard google-genai client fails with it.
    CREATIVE_MODEL = "google-gla:models/gemini-3-pro-preview"
    # Using widely available model for vision to fix 404 error
    VISION_MODEL = "models/gemini-3-pro-preview" 
    VISION_BACKUP_MODEL = "openai:gpt-5.2-2025-12-11" 
    BASIC_MODEL = "google-gla:models/gemini-3-flash-preview"

    @classmethod
    def get_model(cls, key: str) -> str:
        """
        Get the configured LLM model for a specific component.
        
        Resolution Order:
        1. Environment Variable: {KEY}_MODEL (e.g. ORCHESTRATOR_MODEL)
        2. Default mapping in this method
        3. Config.DEFAULT_MODEL
        
        Args:
            key: component name (e.g., 'orchestrator', 'twitter', 'content_pipeline')
                 keys are case-insensitive.
        
        Returns:
            Model string identifier (e.g., 'openai:gpt-4o', 'claude-sonnet-...')
        """
        key_upper = key.upper()
        
        # 1. Check Environment Variable
        env_var_name = f"{key_upper}_MODEL"
        env_model = os.getenv(env_var_name)
        if env_model:
            return env_model
            
        # 2. Check Default Mappings
        # This allows us to have different defaults for different components
        # without requiring env vars for everything
        mappings = {
            "ORCHESTRATOR": cls.ORCHESTRATOR_MODEL,
            "COMPLEX": cls.COMPLEX_MODEL,
            "FAST": cls.FAST_MODEL,
            
            # Capability Mappings
            "CREATIVE": cls.CREATIVE_MODEL,
            "VISION": cls.VISION_MODEL,
            "VISION_BACKUP": cls.VISION_BACKUP_MODEL,
            "BASIC": cls.BASIC_MODEL,
            
            # Specific Agent Mappings (inheriting from capabilities where appropriate)
            # We treat these as independent defaults unless we add recursive logic
            # But to ensure AD_CREATION follows CREATIVE dynamically if not set:
            "AD_CREATION": cls.CREATIVE_MODEL, 

            # Service & Pipeline Mappings
            "REDDIT": cls.BASIC_MODEL,        # Basic sentiment analysis
            "COMIC": cls.CREATIVE_MODEL,      # Creative writing
            "SCRIPT": cls.CREATIVE_MODEL,     # Creative writing
            "COPY_SCAFFOLD": cls.CREATIVE_MODEL, # Creative writing
            "PLANNING": cls.COMPLEX_MODEL,    # Complex reasoning
        }
        
        # Special case for inheritance if needed, otherwise it just uses the string value
        if key_upper == "AD_CREATION" and not env_model:
             # Recursively get CREATIVE to pick up its overrides
             return cls.get_model("CREATIVE")

        if key_upper in mappings:
            return mappings[key_upper]
            
        # 3. Fallback to Global Default
        return cls.DEFAULT_MODEL


# Comment Finder Configuration


@dataclass
class TaxonomyNode:
    """Represents a single taxonomy category with embeddings support"""
    label: str
    description: str
    exemplars: List[str] = field(default_factory=list)


@dataclass
class VoiceConfig:
    """Voice and persona configuration for comment generation"""
    persona: str
    constraints: List[str] = field(default_factory=list)
    examples: Dict[str, List[str]] = field(default_factory=dict)


@dataclass
class SourcesConfig:
    """Source filtering configuration"""
    whitelist_handles: List[str] = field(default_factory=list)
    blacklist_keywords: List[str] = field(default_factory=list)


@dataclass
class FinderConfig:
    """Complete configuration for Comment Finder system"""
    taxonomy: List[TaxonomyNode]
    voice: VoiceConfig
    sources: SourcesConfig
    weights: Dict[str, float]
    thresholds: Dict[str, float]
    generation: Dict[str, Any]


def _generate_exemplars(description: str, count: int = 5) -> List[str]:
    """
    Auto-generate taxonomy exemplars using Gemini if missing.

    Args:
        description: Taxonomy node description
        count: Number of exemplars to generate

    Returns:
        List of generated exemplar strings
    """
    from google import genai
    from google.genai import types

    # Get API key
    api_key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_GEMINI_API_KEY')
    if not api_key:
        print("Warning: GEMINI_API_KEY not set, skipping exemplar auto-generation")
        return []

    # Create client
    client = genai.Client(api_key=api_key)

    prompt = f"""Generate {count} tweet-length exemplars (15-25 words each) that discuss: {description}

Requirements:
- Keep them specific and jargon-accurate
- No emojis
- No hashtags
- Each should be a realistic statement someone might tweet
- Return only the exemplars, one per line"""

    try:
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=[prompt],
            config=types.GenerateContentConfig(
                temperature=0.7,
                max_output_tokens=300
            )
        )

        # Parse response into list
        exemplars = [line.strip() for line in response.text.strip().split('\n') if line.strip()]

        # Clean up any numbered prefixes (1. 2. etc.)
        exemplars = [ex.lstrip('0123456789.- ') for ex in exemplars]

        return exemplars[:count]

    except Exception as e:
        print(f"Warning: Failed to auto-generate exemplars: {e}")
        return []


def load_finder_config(project_slug: str) -> FinderConfig:
    """
    Load Comment Finder configuration for a project.

    Loads from: projects/{project_slug}/finder.yml
    Auto-generates missing taxonomy exemplars if needed.

    Args:
        project_slug: Project identifier (e.g., 'yakety-pack-instagram')

    Returns:
        FinderConfig instance

    Raises:
        FileNotFoundError: If finder.yml doesn't exist
        ValueError: If configuration is invalid
    """
    config_path = Path(f"projects/{project_slug}/finder.yml")

    if not config_path.exists():
        raise FileNotFoundError(
            f"Finder configuration not found at {config_path}\n"
            f"Create a finder.yml file in the project directory."
        )

    # Load YAML
    with open(config_path, 'r') as f:
        raw_config = yaml.safe_load(f)

    # Parse taxonomy with auto-generation
    taxonomy_nodes = []
    config_modified = False

    for node_data in raw_config.get('taxonomy', []):
        label = node_data['label']
        description = node_data['description']
        exemplars = node_data.get('exemplars', [])

        # Auto-generate exemplars if missing or empty
        if not exemplars:
            print(f"Auto-generating exemplars for taxonomy: {label}")
            exemplars = _generate_exemplars(description)
            node_data['exemplars'] = exemplars  # Update for saving back
            config_modified = True

        taxonomy_nodes.append(TaxonomyNode(
            label=label,
            description=description,
            exemplars=exemplars
        ))

    # Save back config if we auto-generated exemplars
    if config_modified:
        with open(config_path, 'w') as f:
            yaml.dump(raw_config, f, default_flow_style=False, sort_keys=False)
        print(f"Updated {config_path} with auto-generated exemplars")

    # Parse voice config
    voice_data = raw_config.get('voice', {})
    voice = VoiceConfig(
        persona=voice_data.get('persona', 'helpful and informative'),
        constraints=voice_data.get('constraints', []),
        examples=voice_data.get('examples', {'good': [], 'bad': []})
    )

    # Parse sources config
    sources_data = raw_config.get('sources', {})
    sources = SourcesConfig(
        whitelist_handles=sources_data.get('whitelist_handles', []),
        blacklist_keywords=sources_data.get('blacklist_keywords', [])
    )

    # Parse weights (with defaults)
    weights = raw_config.get('weights', {
        'velocity': 0.35,
        'relevance': 0.35,
        'openness': 0.20,
        'author_quality': 0.10
    })

    # Parse thresholds (with defaults)
    thresholds = raw_config.get('thresholds', {
        'green_min': 0.72,
        'yellow_min': 0.55
    })

    # Parse generation config (with defaults)
    generation = raw_config.get('generation', {
        'temperature': 0.2,
        'max_tokens': 80,
        'model': 'models/gemini-flash-latest'
    })

    return FinderConfig(
        taxonomy=taxonomy_nodes,
        voice=voice,
        sources=sources,
        weights=weights,
        thresholds=thresholds,
        generation=generation
    )
