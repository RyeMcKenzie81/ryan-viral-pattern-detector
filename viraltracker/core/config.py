"""
Configuration management for ViralTracker
"""

import os
from typing import Optional
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
