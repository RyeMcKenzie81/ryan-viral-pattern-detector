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

    # Email (Resend)
    RESEND_API_KEY: str = os.getenv('RESEND_API_KEY', '')
    EMAIL_FROM: str = os.getenv('EMAIL_FROM', 'noreply@viraltracker.io')

    # Slack
    SLACK_WEBHOOK_URL: str = os.getenv('SLACK_WEBHOOK_URL', '')

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
    import google.generativeai as genai

    # Configure Gemini if not already done
    api_key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_GEMINI_API_KEY')
    if not api_key:
        print("Warning: GEMINI_API_KEY not set, skipping exemplar auto-generation")
        return []

    genai.configure(api_key=api_key)

    prompt = f"""Generate {count} tweet-length exemplars (15-25 words each) that discuss: {description}

Requirements:
- Keep them specific and jargon-accurate
- No emojis
- No hashtags
- Each should be a realistic statement someone might tweet
- Return only the exemplars, one per line"""

    try:
        model = genai.GenerativeModel('models/gemini-flash-latest')
        response = model.generate_content(
            prompt,
            generation_config={
                'temperature': 0.7,
                'max_output_tokens': 300
            }
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
