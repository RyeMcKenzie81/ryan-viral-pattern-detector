"""
Embedding Infrastructure for Comment Finder

Provides text embedding generation using Gemini with caching support.
Used for taxonomy matching and semantic similarity.
"""

import os
import json
import time
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional, Dict
import hashlib

import google.generativeai as genai

logger = logging.getLogger(__name__)

# Gemini embedding model and dimensions
EMBED_MODEL = "models/text-embedding-004"
EMBED_DIM = 768  # Gemini text-embedding-004 output dimension


@dataclass
class Embedder:
    """
    Text embedding generator using Gemini API with JSON caching.

    Attributes:
        provider: Embedding provider (default: "gemini")
        api_key: API key for the provider
        cache_dir: Directory for caching embeddings (default: ./cache)
    """
    provider: str = "gemini"
    api_key: Optional[str] = None
    cache_dir: str = "cache"

    def __post_init__(self):
        """Initialize API client"""
        if self.api_key is None:
            self.api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_GEMINI_API_KEY")

        if not self.api_key:
            raise ValueError("GEMINI_API_KEY environment variable not set")

        # Configure Gemini
        genai.configure(api_key=self.api_key)

        # Ensure cache directory exists
        Path(self.cache_dir).mkdir(parents=True, exist_ok=True)

    def embed_texts(self, texts: List[str], task_type: str = "RETRIEVAL_DOCUMENT") -> List[List[float]]:
        """
        Embed multiple texts in a batch.

        Args:
            texts: List of text strings to embed
            task_type: Task type for embedding (RETRIEVAL_DOCUMENT or RETRIEVAL_QUERY)

        Returns:
            List of embedding vectors (each vector is list of 768 floats)
        """
        if not texts:
            return []

        try:
            # Batch embed with retry
            embeddings = []
            batch_size = 100  # Gemini allows up to 100 texts per request

            for i in range(0, len(texts), batch_size):
                batch = texts[i:i+batch_size]

                # Retry logic
                for attempt in range(3):
                    try:
                        result = genai.embed_content(
                            model=EMBED_MODEL,
                            content=batch,
                            task_type=task_type
                        )

                        # Extract embeddings
                        if hasattr(result, 'embedding'):
                            # Single text response
                            embeddings.append(result['embedding'])
                        else:
                            # Batch response
                            embeddings.extend([e for e in result['embedding']])

                        break  # Success, exit retry loop

                    except Exception as e:
                        if attempt == 2:  # Last attempt
                            logger.error(f"Failed to embed batch after 3 attempts: {e}")
                            raise
                        logger.warning(f"Embedding attempt {attempt + 1} failed, retrying...")
                        time.sleep(2 ** attempt)  # Exponential backoff

                # Rate limiting pause between batches
                if i + batch_size < len(texts):
                    time.sleep(0.1)

            return embeddings

        except Exception as e:
            logger.error(f"Error embedding texts: {e}")
            raise

    def embed_text(self, text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> List[float]:
        """
        Embed a single text string.

        Args:
            text: Text to embed
            task_type: Task type for embedding

        Returns:
            Embedding vector (list of 768 floats)
        """
        return self.embed_texts([text], task_type=task_type)[0]

    def embed_query(self, query: str) -> List[float]:
        """
        Embed a search query (uses RETRIEVAL_QUERY task type).

        Args:
            query: Query text to embed

        Returns:
            Embedding vector optimized for retrieval
        """
        return self.embed_text(query, task_type="RETRIEVAL_QUERY")


# Cache helpers for JSON storage

def _cache_key(text: str) -> str:
    """Generate cache key from text (SHA256 hash)"""
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]


def cache_get(path: str) -> Optional[Dict]:
    """
    Load cached data from JSON file.

    Args:
        path: Path to cache file

    Returns:
        Cached data dict or None if not found
    """
    if not os.path.exists(path):
        return None

    try:
        with open(path, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load cache from {path}: {e}")
        return None


def cache_set(path: str, obj: Dict):
    """
    Save data to JSON cache file.

    Args:
        path: Path to cache file
        obj: Data to cache (must be JSON serializable)
    """
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            json.dump(obj, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to write cache to {path}: {e}")


def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """
    Compute cosine similarity between two vectors.

    Args:
        vec1: First vector
        vec2: Second vector

    Returns:
        Cosine similarity (0..1)
    """
    import math

    if len(vec1) != len(vec2):
        raise ValueError(f"Vector dimension mismatch: {len(vec1)} vs {len(vec2)}")

    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    magnitude1 = math.sqrt(sum(a * a for a in vec1))
    magnitude2 = math.sqrt(sum(b * b for b in vec2))

    if magnitude1 == 0 or magnitude2 == 0:
        return 0.0

    return dot_product / (magnitude1 * magnitude2)


# Tweet embedding cache

def cache_tweet_embeddings(embeddings: Dict[str, List[float]], date_str: str, cache_dir: str = "cache"):
    """
    Cache tweet embeddings by date.

    Args:
        embeddings: Dict of tweet_id -> embedding vector
        date_str: Date string (YYYYMMDD)
        cache_dir: Cache directory path
    """
    path = os.path.join(cache_dir, f"tweet_embeds_{date_str}.json")
    cache_set(path, embeddings)


def load_tweet_embeddings(date_str: str, cache_dir: str = "cache") -> Optional[Dict[str, List[float]]]:
    """
    Load cached tweet embeddings for a date.

    Args:
        date_str: Date string (YYYYMMDD)
        cache_dir: Cache directory path

    Returns:
        Dict of tweet_id -> embedding vector, or None
    """
    path = os.path.join(cache_dir, f"tweet_embeds_{date_str}.json")
    return cache_get(path)


# Taxonomy embedding cache

def cache_taxonomy_embeddings(project_id: str, taxonomy_vectors: Dict, cache_dir: str = "cache"):
    """
    Cache taxonomy node embeddings for a project.

    Args:
        project_id: Project identifier
        taxonomy_vectors: Dict with taxonomy node data
        cache_dir: Cache directory path
    """
    path = os.path.join(cache_dir, f"taxonomy_{project_id}.json")
    cache_set(path, taxonomy_vectors)


def load_taxonomy_embeddings(project_id: str, cache_dir: str = "cache") -> Optional[Dict]:
    """
    Load cached taxonomy embeddings for a project.

    Args:
        project_id: Project identifier
        cache_dir: Cache directory path

    Returns:
        Taxonomy vectors dict or None
    """
    path = os.path.join(cache_dir, f"taxonomy_{project_id}.json")
    return cache_get(path)
