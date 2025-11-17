"""
Pydantic models for Viraltracker agent services.

These models provide type-safe, validated data structures for:
- Twitter/social media data (Tweet)
- AI-powered hook analysis (HookAnalysis)
- Statistical outlier detection (OutlierTweet)
- Comment opportunity identification (CommentCandidate)
- Aggregated results (OutlierResult, HookAnalysisResult)

All models use Pydantic v2 for validation, serialization, and JSON schema generation.
"""

from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from typing import List, Optional, Dict, Any
from collections import Counter


# ============================================================================
# Core Data Models
# ============================================================================

class Tweet(BaseModel):
    """
    Tweet data model.

    Represents a single tweet with engagement metrics and metadata.
    Compatible with both Twitter API and Supabase storage.
    """
    id: str = Field(..., description="Tweet ID (e.g., '1234567890')")
    text: str = Field(..., description="Tweet content/caption")

    # Engagement metrics
    view_count: int = Field(default=0, ge=0, description="Total views")
    like_count: int = Field(default=0, ge=0, description="Total likes")
    reply_count: int = Field(default=0, ge=0, description="Total replies/comments")
    retweet_count: int = Field(default=0, ge=0, description="Total retweets/shares")

    # Temporal data
    created_at: datetime = Field(..., description="When tweet was posted")

    # Author metadata
    author_username: str = Field(..., description="Author handle (without @)")
    author_followers: int = Field(default=0, ge=0, description="Author follower count")

    # URLs
    url: str = Field(..., description="Full URL to tweet")

    # Optional fields
    media_type: Optional[str] = Field(None, description="Media type: text, image, video")
    is_verified: bool = Field(default=False, description="Is author verified")

    # Computed properties
    @property
    def engagement_rate(self) -> float:
        """Engagement rate: (likes + replies + retweets) / views"""
        if self.view_count == 0:
            return 0.0
        total_engagement = self.like_count + self.reply_count + self.retweet_count
        return total_engagement / self.view_count

    @property
    def engagement_score(self) -> float:
        """Weighted engagement score (likes > retweets > replies)"""
        return (
            self.like_count * 1.0 +
            self.retweet_count * 0.8 +
            self.reply_count * 0.5
        )

    class Config:
        json_schema_extra = {
            "example": {
                "id": "1234567890",
                "text": "This is a viral tweet about parenting! 🔥",
                "view_count": 50000,
                "like_count": 2500,
                "reply_count": 150,
                "retweet_count": 800,
                "created_at": "2024-01-15T10:30:00Z",
                "author_username": "parentingtips",
                "author_followers": 45000,
                "url": "https://twitter.com/parentingtips/status/1234567890",
                "media_type": "text",
                "is_verified": False
            }
        }


class HookAnalysis(BaseModel):
    """
    Hook analysis result from AI classification.

    Analyzes what makes a tweet viral using:
    - Hook type (14 types from Hook Intelligence framework)
    - Emotional trigger (10 primary emotions)
    - Content pattern (8 structural patterns)
    """
    tweet_id: str = Field(..., description="Tweet ID being analyzed")
    tweet_text: str = Field(..., description="Original tweet text")

    # Classification results
    hook_type: str = Field(..., description="Hook type (e.g., 'hot_take', 'relatable_slice')")
    hook_type_confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score 0-1")

    emotional_trigger: str = Field(..., description="Primary emotional trigger (e.g., 'humor', 'validation')")
    emotional_trigger_confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score 0-1")

    content_pattern: str = Field(default="statement", description="Content structure (e.g., 'question', 'story')")
    content_pattern_confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="Confidence score 0-1")

    # Explanations
    hook_explanation: str = Field(..., description="Why this hook works (2-3 sentences)")
    adaptation_notes: str = Field(..., description="How to adapt for long-form (2-3 sentences)")

    # Metadata
    has_emoji: bool = Field(default=False, description="Contains emoji")
    has_hashtags: bool = Field(default=False, description="Contains hashtags")
    has_question_mark: bool = Field(default=False, description="Contains question mark")
    word_count: int = Field(default=0, ge=0, description="Word count")

    analyzed_at: datetime = Field(default_factory=datetime.now, description="When analysis was performed")

    @field_validator('hook_type')
    @classmethod
    def validate_hook_type(cls, v: str) -> str:
        """Validate hook_type is from known types"""
        valid_types = {
            "relatable_slice", "shock_violation", "listicle_howto", "hot_take",
            "question_curiosity", "story_narrative", "data_statistic",
            "personal_confession", "before_after", "mistake_lesson",
            "validation_permission", "call_out", "trend_react", "authority_credibility",
            "unknown"
        }
        if v not in valid_types:
            return "unknown"
        return v

    @field_validator('emotional_trigger')
    @classmethod
    def validate_emotional_trigger(cls, v: str) -> str:
        """Validate emotional_trigger is from known triggers"""
        valid_triggers = {
            "humor", "validation", "curiosity", "surprise", "anger",
            "fear", "joy", "sadness", "nostalgia", "pride", "unknown"
        }
        if v not in valid_triggers:
            return "unknown"
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "tweet_id": "1234567890",
                "tweet_text": "Hot take: screen time isn't the enemy, boring parenting is",
                "hook_type": "hot_take",
                "hook_type_confidence": 0.95,
                "emotional_trigger": "validation",
                "emotional_trigger_confidence": 0.88,
                "content_pattern": "statement",
                "content_pattern_confidence": 0.92,
                "hook_explanation": "This controversial opinion challenges conventional wisdom, making parents feel validated for not being perfect.",
                "adaptation_notes": "Could expand into a long-form piece exploring the nuances of screen time debates and parent guilt.",
                "has_emoji": False,
                "has_hashtags": False,
                "has_question_mark": False,
                "word_count": 12,
                "analyzed_at": "2024-01-15T11:00:00Z"
            }
        }


class OutlierTweet(BaseModel):
    """
    Statistical outlier tweet result.

    Combines tweet data with statistical significance metrics.
    """
    tweet: Tweet = Field(..., description="The viral tweet")
    zscore: float = Field(..., description="Z-score (standard deviations above mean)")
    percentile: float = Field(..., ge=0.0, le=100.0, description="Percentile rank (0-100)")
    rank: int = Field(default=0, ge=0, description="Rank by engagement (1 = highest)")

    class Config:
        json_schema_extra = {
            "example": {
                "tweet": {
                    "id": "1234567890",
                    "text": "Viral tweet example",
                    "view_count": 100000,
                    "like_count": 5000,
                    "reply_count": 200,
                    "retweet_count": 1500,
                    "created_at": "2024-01-15T10:30:00Z",
                    "author_username": "user",
                    "author_followers": 10000,
                    "url": "https://twitter.com/user/status/1234567890"
                },
                "zscore": 3.5,
                "percentile": 99.2,
                "rank": 1
            }
        }


class CommentCandidate(BaseModel):
    """
    Comment opportunity candidate.

    Tweet identified as a good opportunity for commenting to drive traffic.
    """
    tweet: Tweet = Field(..., description="The candidate tweet")
    green_flag_score: float = Field(..., ge=0.0, le=1.0, description="Green flag probability (0-1)")
    engagement_score: float = Field(..., ge=0.0, description="Weighted engagement score")
    reasoning: str = Field(..., description="Why this is a good opportunity")

    # Optional AI-generated comment
    suggested_comment: Optional[str] = Field(None, description="AI-generated comment draft")

    class Config:
        json_schema_extra = {
            "example": {
                "tweet": {
                    "id": "1234567890",
                    "text": "Looking for advice on sleep training",
                    "view_count": 5000,
                    "like_count": 50,
                    "reply_count": 20,
                    "retweet_count": 5,
                    "created_at": "2024-01-15T08:00:00Z",
                    "author_username": "newparent",
                    "author_followers": 500,
                    "url": "https://twitter.com/newparent/status/1234567890"
                },
                "green_flag_score": 0.85,
                "engagement_score": 67.5,
                "reasoning": "Question format, engaged audience, topic matches expertise",
                "suggested_comment": "Great question! Here's what worked for us..."
            }
        }


# ============================================================================
# Aggregated Result Models
# ============================================================================

class OutlierResult(BaseModel):
    """
    Aggregated result from outlier detection.

    Contains summary statistics and list of outlier tweets.
    """
    total_tweets: int = Field(..., ge=0, description="Total tweets analyzed")
    outlier_count: int = Field(..., ge=0, description="Number of outliers found")
    threshold: float = Field(..., description="Z-score or percentile threshold used")
    method: str = Field(..., description="Detection method: 'zscore' or 'percentile'")

    outliers: List[OutlierTweet] = Field(default_factory=list, description="List of outlier tweets")

    # Summary statistics
    mean_engagement: Optional[float] = Field(None, description="Mean engagement score")
    median_engagement: Optional[float] = Field(None, description="Median engagement score")
    std_engagement: Optional[float] = Field(None, description="Standard deviation of engagement")

    generated_at: datetime = Field(default_factory=datetime.now, description="When analysis was run")

    @property
    def success_rate(self) -> float:
        """Percentage of tweets that are outliers"""
        if self.total_tweets == 0:
            return 0.0
        return (self.outlier_count / self.total_tweets) * 100

    def to_markdown(self) -> str:
        """Export results as markdown report"""
        md = f"# Outlier Detection Report\n\n"
        md += f"**Generated:** {self.generated_at.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        md += f"## Summary\n\n"
        md += f"- **Total Tweets:** {self.total_tweets:,}\n"
        md += f"- **Outliers Found:** {self.outlier_count:,} ({self.success_rate:.1f}%)\n"
        md += f"- **Method:** {self.method}\n"
        md += f"- **Threshold:** {self.threshold}\n\n"

        if self.mean_engagement is not None:
            md += f"## Engagement Statistics\n\n"
            md += f"- **Mean:** {self.mean_engagement:.1f}\n"
            md += f"- **Median:** {self.median_engagement:.1f}\n"
            md += f"- **Std Dev:** {self.std_engagement:.1f}\n\n"

        if self.outliers:
            md += f"## Top Outliers\n\n"
            for i, outlier in enumerate(self.outliers[:10], 1):
                t = outlier.tweet
                md += f"### {i}. @{t.author_username} (Z-score: {outlier.zscore:.2f})\n\n"
                md += f"**Views:** {t.view_count:,} | **Likes:** {t.like_count:,} | **Percentile:** {outlier.percentile:.1f}%\n\n"
                md += f"> {t.text}\n\n"
                md += f"[View Tweet]({t.url})\n\n"

        return md

    class Config:
        json_schema_extra = {
            "example": {
                "total_tweets": 500,
                "outlier_count": 15,
                "threshold": 2.0,
                "method": "zscore",
                "outliers": [],
                "mean_engagement": 150.5,
                "median_engagement": 85.0,
                "std_engagement": 220.3,
                "generated_at": "2024-01-15T12:00:00Z"
            }
        }


class HookAnalysisResult(BaseModel):
    """
    Aggregated result from hook analysis.

    Contains summary statistics and patterns from analyzed hooks.
    """
    total_analyzed: int = Field(..., ge=0, description="Total tweets analyzed")
    successful_analyses: int = Field(..., ge=0, description="Successfully analyzed tweets")
    failed_analyses: int = Field(default=0, ge=0, description="Failed analyses")

    analyses: List[HookAnalysis] = Field(default_factory=list, description="Individual hook analyses")

    # Pattern summaries
    top_hook_types: Dict[str, int] = Field(default_factory=dict, description="Hook type frequency")
    top_emotional_triggers: Dict[str, int] = Field(default_factory=dict, description="Emotional trigger frequency")
    avg_confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Average confidence score")

    generated_at: datetime = Field(default_factory=datetime.now, description="When analysis was run")

    @property
    def success_rate(self) -> float:
        """Percentage of successful analyses"""
        if self.total_analyzed == 0:
            return 0.0
        return (self.successful_analyses / self.total_analyzed) * 100

    def compute_patterns(self) -> None:
        """Compute pattern summaries from analyses"""
        if not self.analyses:
            return

        # Count hook types
        hook_types = Counter(a.hook_type for a in self.analyses if a.hook_type != "unknown")
        self.top_hook_types = dict(hook_types.most_common(5))

        # Count emotional triggers
        triggers = Counter(a.emotional_trigger for a in self.analyses if a.emotional_trigger != "unknown")
        self.top_emotional_triggers = dict(triggers.most_common(5))

        # Average confidence
        valid_analyses = [a for a in self.analyses if a.hook_type != "unknown"]
        if valid_analyses:
            self.avg_confidence = sum(a.hook_type_confidence for a in valid_analyses) / len(valid_analyses)

    def to_markdown(self) -> str:
        """Export results as markdown report"""
        md = f"# Hook Analysis Report\n\n"
        md += f"**Generated:** {self.generated_at.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        md += f"## Summary\n\n"
        md += f"- **Total Analyzed:** {self.total_analyzed:,}\n"
        md += f"- **Successful:** {self.successful_analyses:,} ({self.success_rate:.1f}%)\n"
        md += f"- **Average Confidence:** {self.avg_confidence:.1%}\n\n"

        if self.top_hook_types:
            md += f"## Top Hook Types\n\n"
            for hook_type, count in self.top_hook_types.items():
                pct = (count / self.successful_analyses) * 100 if self.successful_analyses > 0 else 0
                md += f"- **{hook_type}:** {count} ({pct:.0f}%)\n"
            md += "\n"

        if self.top_emotional_triggers:
            md += f"## Top Emotional Triggers\n\n"
            for trigger, count in self.top_emotional_triggers.items():
                pct = (count / self.successful_analyses) * 100 if self.successful_analyses > 0 else 0
                md += f"- **{trigger}:** {count} ({pct:.0f}%)\n"
            md += "\n"

        if self.analyses:
            md += f"## Top Analyses\n\n"
            for i, analysis in enumerate(self.analyses[:5], 1):
                md += f"### {i}. {analysis.hook_type} ({analysis.hook_type_confidence:.0%} confidence)\n\n"
                md += f"> {analysis.tweet_text}\n\n"
                md += f"**Explanation:** {analysis.hook_explanation}\n\n"
                md += f"**Adaptation:** {analysis.adaptation_notes}\n\n"

        return md

    class Config:
        json_schema_extra = {
            "example": {
                "total_analyzed": 20,
                "successful_analyses": 18,
                "failed_analyses": 2,
                "analyses": [],
                "top_hook_types": {
                    "hot_take": 6,
                    "relatable_slice": 5,
                    "validation_permission": 4
                },
                "top_emotional_triggers": {
                    "validation": 8,
                    "humor": 5,
                    "curiosity": 3
                },
                "avg_confidence": 0.87,
                "generated_at": "2024-01-15T12:30:00Z"
            }
        }
