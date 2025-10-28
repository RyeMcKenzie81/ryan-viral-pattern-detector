"""
Comment Opportunity Finder - Scoring System

Implements the scoring logic for identifying high-value comment opportunities:
- Velocity: Engagement rate normalized by audience size
- Relevance: Taxonomy matching via embeddings
- Openness: Question/hedge detection via regex
- Author Quality: Whitelist/blacklist lookup

V1 Scope: Simplified scoring without expensive LLM checks
"""

import re
import math
import logging
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass
from datetime import datetime, timezone

from viraltracker.core.embeddings import cosine_similarity

logger = logging.getLogger(__name__)


@dataclass
class TweetMetrics:
    """Tweet engagement metrics for scoring"""
    tweet_id: str
    text: str
    author_handle: str
    author_followers: int
    tweeted_at: datetime
    likes: int
    replies: int
    retweets: int
    views: int = 0  # Twitter impressions/views
    lang: str = 'en'


@dataclass
class ScoringResult:
    """Complete scoring result for a tweet"""
    tweet_id: str
    velocity: float
    relevance: float
    openness: float
    author_quality: float
    total_score: float
    label: str
    best_topic: str
    best_topic_similarity: float
    passed_gate: bool
    gate_reason: Optional[str] = None


# Velocity Scoring

def compute_velocity(
    likes: int,
    replies: int,
    retweets: int,
    minutes_since: float,
    followers: int
) -> float:
    """
    Calculate velocity score (0..1) based on engagement rate.

    Formula:
    - Engagement per minute = (likes + 2*replies + 1.5*rts) / minutes
    - Audience normalization = log10(max(100, followers))
    - Velocity = sigmoid(6.0 * eng_per_min / aud_norm)

    Args:
        likes: Like count
        replies: Reply count
        retweets: Retweet count
        minutes_since: Minutes since tweet posted
        followers: Author follower count

    Returns:
        Velocity score (0..1)
    """
    # Weighted engagement (replies > retweets > likes)
    weighted_engagement = likes + (2 * replies) + (1.5 * retweets)

    # Engagement per minute
    eng_per_min = weighted_engagement / max(1.0, minutes_since)

    # Audience normalization (log scale)
    aud_norm = math.log10(max(100, followers))

    # Sigmoid scaling
    k = 6.0  # Sensitivity parameter
    x = eng_per_min / aud_norm
    velocity = 1.0 / (1.0 + math.exp(-k * x))

    return velocity


# Taxonomy Relevance Scoring

def relevance_from_taxonomy(
    tweet_embedding: List[float],
    taxonomy_embeddings: Dict[str, List[float]]
) -> Tuple[float, str, float]:
    """
    Calculate relevance score based on taxonomy matching.

    Formula:
    - Compute cosine similarity with each taxonomy node
    - relevance = 0.8 * best_sim + 0.2 * margin
    - margin = max(0, best_sim - second_best_sim)

    Args:
        tweet_embedding: Tweet embedding vector (768 dims)
        taxonomy_embeddings: Dict of {label: embedding_vector}

    Returns:
        Tuple of (relevance_score, best_topic_label, best_similarity)
    """
    if not taxonomy_embeddings:
        logger.warning("No taxonomy embeddings provided")
        return 0.0, "unknown", 0.0

    # Compute similarities
    similarities = []
    for label, node_embedding in taxonomy_embeddings.items():
        sim = cosine_similarity(tweet_embedding, node_embedding)
        similarities.append((label, sim))

    # Sort by similarity
    similarities.sort(key=lambda x: x[1], reverse=True)

    # Get best and second-best
    best_label, best_sim = similarities[0]
    second_best_sim = similarities[1][1] if len(similarities) > 1 else 0.0

    # Calculate margin
    margin = max(0.0, best_sim - second_best_sim)

    # Relevance score
    relevance = 0.8 * best_sim + 0.2 * margin

    return relevance, best_label, best_sim


# Openness Scoring (Regex-based for V1)

# Regex patterns for openness detection
QUESTION_PATTERN = re.compile(r'\?$')
WH_QUESTION_PATTERN = re.compile(r'^(what|why|how|when|where|who|which|whose)\b', re.IGNORECASE)
HEDGE_WORDS = re.compile(
    r'\b(maybe|perhaps|possibly|might|could|seems?|appears?|probably|wonder|think|feel|believe)\b',
    re.IGNORECASE
)


def openness_score(text: str, author_reply_rate: Optional[float] = None) -> float:
    """
    Calculate openness score (0..1) based on question/hedge patterns.

    V1 uses regex patterns only (no LLM).
    V1.1 will incorporate author reply rate from historical data.

    Scoring:
    - Ends with question mark: +0.25
    - Starts with WH-question: +0.25
    - Contains hedge words: +0.15
    - Author reply rate < 0.15: +0.10 (V1.1)
    - Baseline: +0.05

    Args:
        text: Tweet text
        author_reply_rate: Optional author reply rate (V1.1)

    Returns:
        Openness score (0..1)
    """
    score = 0.05  # Neutral baseline

    # Check for question mark at end
    if QUESTION_PATTERN.search(text.strip()):
        score += 0.25

    # Check for WH-question at start
    if WH_QUESTION_PATTERN.search(text.strip()):
        score += 0.25

    # Check for hedge words
    if HEDGE_WORDS.search(text):
        score += 0.15

    # Author reply rate (optional for V1)
    if author_reply_rate is not None:
        if author_reply_rate < 0.15:
            score += 0.10

    # Cap at 1.0
    return min(1.0, score)


# Author Quality Scoring

def author_quality_score(handle: str, whitelist: List[str], blacklist: List[str]) -> float:
    """
    Calculate author quality score based on whitelist/blacklist.

    Scoring:
    - Whitelist: 0.9
    - Unknown: 0.6
    - Blacklist: 0.0

    Args:
        handle: Author Twitter handle
        whitelist: List of whitelisted handles
        blacklist: List of blacklisted handles

    Returns:
        Author quality score (0..1)
    """
    handle_lower = handle.lower().lstrip('@')

    # Check blacklist first
    if any(handle_lower == b.lower().lstrip('@') for b in blacklist):
        return 0.0

    # Check whitelist
    if any(handle_lower == w.lower().lstrip('@') for w in whitelist):
        return 0.9

    # Unknown author
    return 0.6


# Total Score & Labeling

def total_score(
    velocity: float,
    relevance: float,
    openness: float,
    author_quality: float,
    weights: Dict[str, float]
) -> float:
    """
    Calculate weighted total score.

    Default weights:
    - velocity: 0.35
    - relevance: 0.35
    - openness: 0.20
    - author_quality: 0.10

    Args:
        velocity: Velocity score (0..1)
        relevance: Relevance score (0..1)
        openness: Openness score (0..1)
        author_quality: Author quality score (0..1)
        weights: Weight dict

    Returns:
        Total score (0..1)
    """
    return (
        weights.get('velocity', 0.35) * velocity +
        weights.get('relevance', 0.35) * relevance +
        weights.get('openness', 0.20) * openness +
        weights.get('author_quality', 0.10) * author_quality
    )


def label_from_score(score: float, thresholds: Dict[str, float]) -> str:
    """
    Assign label based on total score.

    Default thresholds:
    - green: >= 0.72
    - yellow: >= 0.55
    - red: < 0.55

    Args:
        score: Total score (0..1)
        thresholds: Threshold dict

    Returns:
        Label: 'green', 'yellow', or 'red'
    """
    green_min = thresholds.get('green_min', 0.72)
    yellow_min = thresholds.get('yellow_min', 0.55)

    if score >= green_min:
        return 'green'
    elif score >= yellow_min:
        return 'yellow'
    else:
        return 'red'


# Gate Filtering

def gate_tweet(
    tweet_text: str,
    author_handle: str,
    lang: str,
    blacklist_keywords: List[str],
    blacklist_handles: List[str],
    require_english: bool = True,
    replies: int = 0
) -> Tuple[bool, Optional[str]]:
    """
    Gate filtering for tweet acceptance.

    Checks:
    - Language (default: English only)
    - Blacklist keywords in text
    - Blacklist handles
    - Link spam detection (short text + link + no engagement)

    Args:
        tweet_text: Tweet text
        author_handle: Author handle
        lang: Language code
        blacklist_keywords: List of blacklist keywords
        blacklist_handles: List of blacklist handles
        require_english: Require English language
        replies: Number of replies/comments on tweet

    Returns:
        Tuple of (passed, reason_if_failed)
    """
    # Language check
    if require_english and lang != 'en':
        return False, f"non-english language: {lang}"

    # Blacklist keyword check
    text_lower = tweet_text.lower()
    for keyword in blacklist_keywords:
        if keyword.lower() in text_lower:
            return False, f"blacklist keyword: {keyword}"

    # Blacklist handle check
    handle_lower = author_handle.lower().lstrip('@')
    for handle in blacklist_handles:
        if handle_lower == handle.lower().lstrip('@'):
            return False, f"blacklist author: {author_handle}"

    # Link spam detection: short text + URL + no comments = likely spam
    # Check if tweet contains a URL
    has_link = 'http://' in tweet_text or 'https://' in tweet_text or 't.co/' in tweet_text

    if has_link:
        # Remove URLs to get actual text content
        import re
        text_without_urls = re.sub(r'https?://\S+|t\.co/\S+', '', tweet_text)
        # Remove mentions and hashtags for better length assessment
        text_without_urls = re.sub(r'@\S+|#\S+', '', text_without_urls)
        # Count meaningful characters (letters, numbers)
        meaningful_text = re.sub(r'[^a-zA-Z0-9\s]', '', text_without_urls)
        text_length = len(meaningful_text.strip())

        # If less than 50 characters of actual text AND no replies, likely spam
        if text_length < 50 and replies == 0:
            return False, f"link spam: short text ({text_length} chars) + link + no engagement"

    return True, None


# Main Scoring Function

def score_tweet(
    tweet: TweetMetrics,
    tweet_embedding: List[float],
    taxonomy_embeddings: Dict[str, List[float]],
    config: Any,  # FinderConfig from config.py
    use_gate: bool = True
) -> ScoringResult:
    """
    Score a single tweet with all components.

    Args:
        tweet: Tweet metrics
        tweet_embedding: Tweet embedding vector
        taxonomy_embeddings: Taxonomy embeddings dict
        config: FinderConfig instance
        use_gate: Apply gate filtering

    Returns:
        ScoringResult with all scores and label
    """
    # Calculate minutes since tweet
    now = datetime.now(timezone.utc)
    if tweet.tweeted_at.tzinfo is None:
        tweeted_at = tweet.tweeted_at.replace(tzinfo=timezone.utc)
    else:
        tweeted_at = tweet.tweeted_at
    minutes_since = (now - tweeted_at).total_seconds() / 60.0

    # Gate filtering
    passed_gate = True
    gate_reason = None

    if use_gate:
        passed_gate, gate_reason = gate_tweet(
            tweet_text=tweet.text,
            author_handle=tweet.author_handle,
            lang=tweet.lang,
            blacklist_keywords=config.sources.blacklist_keywords,
            blacklist_handles=config.sources.whitelist_handles,  # Note: using as blacklist for gate
            require_english=True,
            replies=tweet.replies
        )

    # Velocity
    velocity = compute_velocity(
        likes=tweet.likes,
        replies=tweet.replies,
        retweets=tweet.retweets,
        minutes_since=minutes_since,
        followers=tweet.author_followers
    )

    # Relevance
    relevance, best_topic, best_sim = relevance_from_taxonomy(
        tweet_embedding=tweet_embedding,
        taxonomy_embeddings=taxonomy_embeddings
    )

    # Openness
    openness = openness_score(tweet.text)

    # Author quality
    author_quality = author_quality_score(
        handle=tweet.author_handle,
        whitelist=config.sources.whitelist_handles,
        blacklist=config.sources.blacklist_keywords  # Note: may want separate author blacklist
    )

    # Total score
    total = total_score(
        velocity=velocity,
        relevance=relevance,
        openness=openness,
        author_quality=author_quality,
        weights=config.weights
    )

    # Label
    label = label_from_score(total, config.thresholds)

    return ScoringResult(
        tweet_id=tweet.tweet_id,
        velocity=velocity,
        relevance=relevance,
        openness=openness,
        author_quality=author_quality,
        total_score=total,
        label=label,
        best_topic=best_topic,
        best_topic_similarity=best_sim,
        passed_gate=passed_gate,
        gate_reason=gate_reason
    )
