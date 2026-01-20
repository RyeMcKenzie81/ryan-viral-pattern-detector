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

from pydantic import BaseModel, Field, field_validator, model_validator
from datetime import datetime
from typing import List, Optional, Dict, Any
from collections import Counter
from uuid import UUID
from enum import Enum


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


class TikTokVideo(BaseModel):
    """
    TikTok video data model.

    Represents a single TikTok video with engagement metrics and metadata.
    Compatible with TikTokScraper output and Supabase storage.
    """
    id: str = Field(..., description="TikTok video ID (post_id)")
    url: str = Field(..., description="Full URL to TikTok video")
    caption: str = Field(default="", description="Video caption/description")

    # Engagement metrics
    views: int = Field(default=0, ge=0, description="Total views/play count")
    likes: int = Field(default=0, ge=0, description="Total likes")
    comments: int = Field(default=0, ge=0, description="Total comments")
    shares: int = Field(default=0, ge=0, description="Total shares")

    # Video metadata
    length_sec: int = Field(default=0, ge=0, description="Video duration in seconds")
    posted_at: Optional[datetime] = Field(None, description="When video was posted")

    # Creator metadata
    username: str = Field(..., description="Creator username (without @)")
    display_name: str = Field(default="", description="Creator display name")
    follower_count: int = Field(default=0, ge=0, description="Creator follower count")
    is_verified: bool = Field(default=False, description="Is creator verified")

    # Optional fields
    download_url: Optional[str] = Field(None, description="Video download URL (watermark-free)")

    # Computed properties
    @property
    def engagement_rate(self) -> float:
        """Engagement rate: (likes + comments + shares) / views"""
        if self.views == 0:
            return 0.0
        total_engagement = self.likes + self.comments + self.shares
        return total_engagement / self.views

    @property
    def engagement_score(self) -> float:
        """Weighted engagement score (likes > shares > comments)"""
        return (
            self.likes * 1.0 +
            self.shares * 0.8 +
            self.comments * 0.5
        )

    class Config:
        json_schema_extra = {
            "example": {
                "id": "7559660839335202079",
                "url": "https://www.tiktok.com/@user/video/7559660839335202079",
                "caption": "How I organize my day with this productivity app",
                "views": 150000,
                "likes": 8500,
                "comments": 320,
                "shares": 1200,
                "length_sec": 45,
                "posted_at": "2024-01-15T14:30:00Z",
                "username": "productivitypro",
                "display_name": "Productivity Pro",
                "follower_count": 35000,
                "is_verified": False,
                "download_url": "https://..."
            }
        }


class YouTubeVideo(BaseModel):
    """YouTube video data model with engagement metrics."""

    # Identifiers
    id: str = Field(..., description="YouTube video ID (post_id)")
    url: str = Field(..., description="Full URL to YouTube video")
    title: str = Field(default="", description="Video title")
    caption: str = Field(default="", description="Video description/caption")

    # Engagement metrics
    views: int = Field(default=0, ge=0, description="Total view count")
    likes: int = Field(default=0, ge=0, description="Total likes")
    comments: int = Field(default=0, ge=0, description="Total comments")

    # Video metadata
    length_sec: int = Field(default=0, ge=0, description="Video duration in seconds")
    video_type: str = Field(default="video", description="Video type: short, video, or stream")
    posted_at: Optional[datetime] = Field(None, description="When video was published")

    # Channel metadata
    channel: str = Field(..., description="YouTube channel name")
    subscriber_count: int = Field(default=0, ge=0, description="Channel subscriber count")
    search_query: Optional[str] = Field(None, description="Search query that found this video")

    @property
    def engagement_rate(self) -> float:
        """Engagement rate: (likes + comments) / views"""
        if self.views == 0:
            return 0.0
        return (self.likes + self.comments) / self.views

    @property
    def engagement_score(self) -> float:
        """Weighted engagement score (likes > comments)"""
        return self.likes * 1.0 + self.comments * 0.5

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": "dQw4w9WgXcQ",
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "title": "10 Productivity Tips That Changed My Life",
                "caption": "In this video I share my top 10 productivity tips...",
                "views": 125000,
                "likes": 8500,
                "comments": 350,
                "length_sec": 612,
                "video_type": "video",
                "posted_at": "2024-01-10T09:00:00Z",
                "channel": "ProductivityMaster",
                "subscriber_count": 45000,
                "search_query": "productivity tips"
            }
        }
    }


class FacebookAd(BaseModel):
    """Facebook ad data model with spend and reach metrics."""

    # Identifiers
    id: str = Field(..., description="Facebook ad ID (ad_id)")
    ad_archive_id: str = Field(..., description="Ad archive ID (used for deduplication)")
    url: Optional[str] = Field(None, description="Full URL to Facebook ad (if available)")

    # Page metadata
    page_id: Optional[str] = Field(None, description="Facebook page ID")
    page_name: str = Field(..., description="Facebook page name running the ad")

    # Ad metadata
    is_active: bool = Field(default=False, description="Whether ad is currently active")
    start_date: Optional[datetime] = Field(None, description="When ad started running")
    end_date: Optional[datetime] = Field(None, description="When ad stopped running (if ended)")

    # Performance metrics
    currency: Optional[str] = Field(None, description="Currency of spend (e.g., USD)")
    spend: Optional[float] = Field(None, ge=0, description="Total ad spend amount")
    impressions: Optional[int] = Field(None, ge=0, description="Number of impressions")
    reach_estimate: Optional[int] = Field(None, ge=0, description="Estimated reach")

    # Creative data (stored as JSON strings in DB)
    snapshot: Optional[str] = Field(None, description="Creative/visual snapshot data (JSON)")
    categories: Optional[str] = Field(None, description="Ad categories (JSON array)")
    publisher_platform: Optional[str] = Field(None, description="Platforms where ad published (JSON array)")

    # Political/transparency
    political_countries: Optional[str] = Field(None, description="Countries for political ads (JSON array)")
    entity_type: Optional[str] = Field(None, description="Type of entity running ad")

    @property
    def engagement_score(self) -> float:
        """Simple engagement score based on impressions and reach"""
        if self.impressions and self.reach_estimate:
            return (self.impressions + self.reach_estimate) / 2
        elif self.impressions:
            return float(self.impressions)
        elif self.reach_estimate:
            return float(self.reach_estimate)
        return 0.0

    @property
    def days_active(self) -> Optional[int]:
        """Number of days ad has been/was active"""
        if not self.start_date:
            return None
        end = self.end_date or datetime.now()
        return (end - self.start_date).days

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": "123456789",
                "ad_archive_id": "987654321",
                "url": "https://www.facebook.com/ads/library/?id=123456789",
                "page_id": "456789123",
                "page_name": "Nike",
                "is_active": True,
                "start_date": "2024-01-01T00:00:00Z",
                "end_date": None,
                "currency": "USD",
                "spend": 5000.00,
                "impressions": 150000,
                "reach_estimate": 100000,
                "snapshot": '{"link_url": "https://nike.com", "body": "Just Do It"}',
                "categories": '["Sportswear", "Athletic Shoes"]',
                "publisher_platform": '["facebook", "instagram"]',
                "political_countries": None,
                "entity_type": "page"
            }
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

    def __str__(self) -> str:
        """String representation using markdown format"""
        return self.to_markdown()

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

    def __str__(self) -> str:
        """String representation using markdown format"""
        return self.to_markdown()

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


class TweetExportResult(BaseModel):
    """
    Aggregated result from tweet export.

    Contains summary statistics and list of exported tweets.
    Supports multi-format downloads (CSV, JSON, Markdown).
    """
    total_tweets: int = Field(..., ge=0, description="Total tweets exported")
    keyword_filter: Optional[str] = Field(None, description="Keyword filter applied")
    hours_back: int = Field(..., ge=0, description="Hours back queried")
    sort_by: str = Field(..., description="Sort metric used (views, likes, engagement)")

    tweets: List[Tweet] = Field(default_factory=list, description="List of exported tweets")

    # Summary statistics
    total_views: int = Field(default=0, ge=0, description="Total views across all tweets")
    total_likes: int = Field(default=0, ge=0, description="Total likes across all tweets")
    total_engagement: int = Field(default=0, ge=0, description="Total engagement (likes+replies+retweets)")
    avg_engagement_rate: float = Field(default=0.0, ge=0.0, description="Average engagement rate")

    generated_at: datetime = Field(default_factory=datetime.now, description="When export was generated")

    @property
    def avg_views(self) -> float:
        """Average views per tweet"""
        if self.total_tweets == 0:
            return 0.0
        return self.total_views / self.total_tweets

    @property
    def avg_likes(self) -> float:
        """Average likes per tweet"""
        if self.total_tweets == 0:
            return 0.0
        return self.total_likes / self.total_tweets

    def to_markdown(self) -> str:
        """Export results as markdown report"""
        md = f"# Tweet Export Report\n\n"
        md += f"**Generated:** {self.generated_at.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        md += f"## Export Parameters\n\n"
        md += f"- **Time Range:** Last {self.hours_back} hours\n"
        md += f"- **Sort By:** {self.sort_by}\n"
        if self.keyword_filter:
            md += f"- **Keyword Filter:** {self.keyword_filter}\n"
        md += f"- **Total Tweets:** {self.total_tweets:,}\n\n"

        md += f"## Summary Statistics\n\n"
        md += f"- **Total Views:** {self.total_views:,}\n"
        md += f"- **Total Likes:** {self.total_likes:,}\n"
        md += f"- **Total Engagement:** {self.total_engagement:,}\n"
        md += f"- **Avg Engagement Rate:** {self.avg_engagement_rate:.2%}\n"
        md += f"- **Avg Views per Tweet:** {self.avg_views:,.0f}\n"
        md += f"- **Avg Likes per Tweet:** {self.avg_likes:,.0f}\n\n"

        if self.tweets:
            md += f"## Tweets\n\n"
            for i, tweet in enumerate(self.tweets, 1):
                md += f"### {i}. @{tweet.author_username}\n\n"
                md += f"**Followers:** {tweet.author_followers:,}  \n"
                md += f"**Views:** {tweet.view_count:,} | **Likes:** {tweet.like_count:,} | **Replies:** {tweet.reply_count} | **Retweets:** {tweet.retweet_count}  \n"
                md += f"**Engagement Rate:** {tweet.engagement_rate:.2%}  \n"
                md += f"**Engagement Score:** {tweet.engagement_score:.2f}  \n\n"
                md += f"> {tweet.text}\n\n"
                md += f"[View Tweet]({tweet.url})\n\n"
                md += "---\n\n"

        return md

    def __str__(self) -> str:
        """String representation using markdown format"""
        return self.to_markdown()

    class Config:
        json_schema_extra = {
            "example": {
                "total_tweets": 20,
                "keyword_filter": "bitcoin,btc",
                "hours_back": 24,
                "sort_by": "views",
                "tweets": [],
                "total_views": 125000,
                "total_likes": 5500,
                "total_engagement": 7200,
                "avg_engagement_rate": 0.0576,
                "generated_at": "2024-01-15T14:00:00Z"
            }
        }


# ============================================================================
# Ad Creation Models (Facebook Ad Creation Agent)
# ============================================================================

class Product(BaseModel):
    """Product information with images and metadata"""
    id: UUID
    brand_id: UUID
    name: str
    benefits: Optional[List[str]] = Field(None, description="Product benefits for ad copy")
    key_ingredients: Optional[List[str]] = Field(None, description="Key ingredients to highlight")
    target_audience: Optional[str] = Field(None, description="Target demographic")
    product_url: Optional[str] = Field(None, description="Product landing page URL")
    main_image_storage_path: Optional[str] = Field(None, description="Storage path to main product image")
    reference_image_storage_paths: Optional[List[str]] = Field(None, description="Additional product images")

    # Phase 6: Product Constraints & Offer Controls
    current_offer: Optional[str] = Field(None, description="Active promotional offer text to prevent hallucinated discount claims")
    prohibited_claims: Optional[List[str]] = Field(None, description="Claims that must not appear in ads for legal compliance")
    required_disclaimers: Optional[str] = Field(None, description="Legal disclaimers that must appear in ads")
    brand_voice_notes: Optional[str] = Field(None, description="Tone and style guidelines for ad copy generation")
    unique_selling_points: Optional[List[str]] = Field(None, description="Key differentiators vs competitors to highlight")
    product_dimensions: Optional[str] = Field(None, description="Physical size/dimensions to ensure realistic product scaling in generated images (e.g., '3 fl oz bottle, 5 inches tall, palm-sized')")
    social_proof: Optional[str] = Field(None, description="Social proof statement to include when template has social proof elements (e.g., '100,000+ Bottles Sold', '50,000+ Happy Customers')")
    founders: Optional[str] = Field(None, description="Founder names for personal signatures in ads (e.g., 'Chris, Kevin, D'Arcy, and Ryan')")
    brand_name: Optional[str] = Field(None, description="Brand name to use in ad copy (e.g., 'Wonder Paws')")
    banned_terms: Optional[List[str]] = Field(None, description="Competitor names and terms that must never appear in ads (e.g., ['Wuffes', 'PupVitality'])")

    @field_validator('benefits', 'key_ingredients', 'reference_image_storage_paths', 'prohibited_claims', 'unique_selling_points', 'banned_terms', mode='before')
    @classmethod
    def convert_none_to_empty_list(cls, v):
        """Convert None to empty list for list fields"""
        return v if v is not None else []


class Hook(BaseModel):
    """Persuasive hook for ad copywriting"""
    id: UUID
    product_id: UUID
    text: str = Field(..., description="Hook text derived from reviews or created manually")
    category: str = Field(..., description="Universal persuasive principle category")
    framework: Optional[str] = Field(None, description="Original framework name")
    impact_score: int = Field(ge=0, le=21, description="Impact score 0-21 based on persuasive framework")
    emotional_score: Optional[str] = Field(None, description="Emotional intensity: Very High, High, Medium, Low")
    active: bool = True


class AdBriefTemplate(BaseModel):
    """Template for ad creation instructions"""
    id: UUID
    brand_id: Optional[UUID] = Field(None, description="NULL = global template")
    name: str
    instructions: str = Field(..., description="Markdown instructions for ad creation workflow")
    active: bool = True


class AdAnalysis(BaseModel):
    """Result of analyzing a reference ad using Vision AI"""
    format_type: str = Field(..., description="Ad format: testimonial, quote_style, before_after, product_showcase")
    layout_structure: str = Field(..., description="Layout: single_image, two_panel, carousel")
    fixed_elements: List[str] = Field(default_factory=list, description="Elements to reuse across all 5 ads")
    variable_elements: List[str] = Field(default_factory=list, description="Elements that change per variation")
    text_placement: Dict[str, Any] = Field(default_factory=dict, description="Text positioning details")
    color_palette: List[str] = Field(default_factory=list, description="Hex color codes")
    authenticity_markers: List[str] = Field(default_factory=list, description="Timestamps, usernames, emojis")
    canvas_size: str = Field(..., description="Image dimensions e.g. 1080x1080px")
    detailed_description: str = Field(..., description="Comprehensive description for prompt engineering")


class SelectedHook(BaseModel):
    """Hook selected for ad generation with style adaptations"""
    hook_id: UUID
    text: str = Field(..., description="Original hook text")
    category: str = Field(..., description="Persuasive category")
    framework: Optional[str] = None
    impact_score: int
    reasoning: str = Field(..., description="Why this hook was selected (diversity, impact, etc.)")
    adapted_text: str = Field(..., description="Hook text adapted to match reference ad style/tone")


class NanoBananaPrompt(BaseModel):
    """Prompt for Gemini Nano Banana image generation"""
    prompt_index: int = Field(ge=1, le=15, description="Index 1-15 for this variation")
    hook: SelectedHook
    instruction_text: str = Field(..., description="Human-readable instructions for image generation")
    spec: Dict[str, Any] = Field(..., description="JSON spec with canvas, product, text_elements")
    full_prompt: str = Field(..., description="Complete prompt sent to Nano Banana API")
    template_reference_path: str = Field(..., description="Storage path to reference ad image")
    product_image_path: str = Field(..., description="Storage path to product image")


class GeneratedAd(BaseModel):
    """Generated ad image with metadata"""
    prompt_index: int = Field(ge=1, le=15)
    image_base64: Optional[str] = Field(None, description="Temporary base64 before saving to storage")
    storage_path: Optional[str] = Field(None, description="Set after saving to Supabase Storage")


class ReviewResult(BaseModel):
    """AI review of generated ad quality"""
    reviewer: str = Field(..., description="Reviewer name: 'claude' or 'gemini'")
    product_accuracy: float = Field(ge=0.0, le=1.0, description="Product image fidelity score")
    text_accuracy: float = Field(ge=0.0, le=1.0, description="Text readability and correctness score")
    layout_accuracy: float = Field(ge=0.0, le=1.0, description="Layout adherence to template score")
    overall_quality: float = Field(ge=0.0, le=1.0, description="Overall production-ready quality score")
    product_issues: List[str] = Field(default_factory=list, description="Product image issues found")
    text_issues: List[str] = Field(default_factory=list, description="Text issues (gibberish, spelling, etc.)")
    ai_artifacts: List[str] = Field(default_factory=list, description="AI generation artifacts detected")
    status: str = Field(..., description="Review status: approved, needs_revision, rejected")
    notes: str = Field(..., description="Additional review notes")


class GeneratedAdWithReviews(BaseModel):
    """Generated ad with dual AI reviews and final decision"""
    prompt_index: int
    prompt: NanoBananaPrompt
    storage_path: str
    claude_review: Optional[ReviewResult] = None
    gemini_review: Optional[ReviewResult] = None
    reviewers_agree: bool = Field(..., description="True if both reviewers gave same status")
    final_status: str = Field(..., description="approved, rejected, or flagged (disagreement)")


class AdCreationResult(BaseModel):
    """Complete result of ad creation workflow"""
    ad_run_id: UUID
    product: Product
    reference_ad_path: str
    ad_analysis: AdAnalysis
    selected_hooks: List[SelectedHook]
    generated_ads: List[GeneratedAdWithReviews]
    approved_count: int = Field(..., description="Number of ads approved by AI reviewers")
    rejected_count: int = Field(..., description="Number of ads rejected by both reviewers")
    flagged_count: int = Field(..., description="Number of ads with reviewer disagreement")
    summary: str = Field(..., description="Human-readable summary of workflow results")
    created_at: datetime = Field(default_factory=datetime.now)


# ============================================================================
# 4D Persona Models
# ============================================================================

from enum import Enum


class PersonaType(str, Enum):
    """Type of persona based on ownership."""
    OWN_BRAND = "own_brand"
    PRODUCT_SPECIFIC = "product_specific"
    COMPETITOR = "competitor"


class SourceType(str, Enum):
    """How the persona was created."""
    MANUAL = "manual"
    AI_GENERATED = "ai_generated"
    COMPETITOR_ANALYSIS = "competitor_analysis"
    HYBRID = "hybrid"


class DesireCategory(str, Enum):
    """The 10 core human desires (Eugene Schwartz framework)."""
    SURVIVAL_LIFE_EXTENSION = "survival_life_extension"
    FOOD_BEVERAGES = "food_beverages"
    FREEDOM_FROM_FEAR = "freedom_from_fear"
    SEXUAL_COMPANIONSHIP = "sexual_companionship"
    COMFORTABLE_LIVING = "comfortable_living"
    SUPERIORITY_STATUS = "superiority_status"
    CARE_PROTECTION = "care_protection"
    SOCIAL_APPROVAL = "social_approval"
    JUSTICE_FAIRNESS = "justice_fairness"
    SELF_ACTUALIZATION = "self_actualization"


class DesireInstance(BaseModel):
    """A specific instance of a desire with captured verbiage."""
    text: str = Field(..., description="The actual language/verbiage capturing this desire")
    source: str = Field(default="manual", description="Where this came from: ad, review, manual, competitor_ad")
    source_id: Optional[str] = Field(None, description="ID of source item if from DB")


class Demographics(BaseModel):
    """Demographic profile for persona basics."""
    age_range: Optional[str] = Field(None, description="e.g., '28-45'")
    gender: Optional[str] = Field(None, description="male, female, any")
    location: Optional[str] = Field(None, description="e.g., 'Suburban USA'")
    income_level: Optional[str] = Field(None, description="e.g., 'Middle to upper-middle class'")
    education: Optional[str] = Field(None, description="e.g., 'College educated'")
    occupation: Optional[str] = Field(None, description="e.g., 'Professional, works from home'")
    family_status: Optional[str] = Field(None, description="e.g., 'Married with young children'")


class TransformationMap(BaseModel):
    """Before/after transformation - the journey from current to desired state."""
    before: List[str] = Field(default_factory=list, description="Current frustrations, limitations, identity")
    after: List[str] = Field(default_factory=list, description="Desired outcomes, states, identity")


class SocialRelations(BaseModel):
    """Social dynamics mapping - the 10 relationship types that influence behavior."""
    admire: List[str] = Field(default_factory=list, description="People they look up to, role models")
    envy: List[str] = Field(default_factory=list, description="People they secretly want to be like")
    want_to_impress: List[str] = Field(default_factory=list, description="People they want approval from")
    love_loyalty: List[str] = Field(default_factory=list, description="People they feel protective of")
    dislike_animosity: List[str] = Field(default_factory=list, description="People they oppose/dislike")
    compared_to: List[str] = Field(default_factory=list, description="People they measure themselves against")
    influence_decisions: List[str] = Field(default_factory=list, description="People who affect their choices")
    fear_judged_by: List[str] = Field(default_factory=list, description="People whose judgment they fear")
    want_to_belong: List[str] = Field(default_factory=list, description="Groups they aspire to join")
    distance_from: List[str] = Field(default_factory=list, description="Groups they want to separate from")


class DomainSentiment(BaseModel):
    """Product-specific outcomes, pain points, or objections organized by type."""
    emotional: List[str] = Field(default_factory=list, description="Emotional aspects")
    social: List[str] = Field(default_factory=list, description="Social aspects")
    functional: List[str] = Field(default_factory=list, description="Functional/practical aspects")


class Persona4D(BaseModel):
    """
    Complete 4D Persona model.

    The 4 dimensions:
    1. Demographics & Behavior - Who they are externally
    2. Psychographics & Desires - What they want internally
    3. Identity & Social - How they see themselves and relate to others
    4. Worldview & Domain - How they interpret reality and your product category
    """
    id: Optional[UUID] = None
    name: str = Field(..., description="Descriptive persona name e.g., 'Worried First-Time Dog Mom'")
    persona_type: PersonaType = Field(..., description="own_brand, product_specific, or competitor")
    is_primary: bool = Field(default=False, description="Primary persona for this product/brand")

    # Ownership (one of these will typically be set)
    brand_id: Optional[UUID] = None
    product_id: Optional[UUID] = None
    competitor_id: Optional[UUID] = None
    competitor_product_id: Optional[UUID] = Field(None, description="For product-level competitor personas")

    # ========================================
    # DIMENSION 1: BASICS
    # ========================================
    snapshot: Optional[str] = Field(None, description="2-3 sentence big picture description")
    demographics: Demographics = Field(default_factory=Demographics)
    behavior_habits: Dict[str, Any] = Field(default_factory=dict, description="Daily routines, media consumption, etc.")
    digital_presence: Dict[str, Any] = Field(default_factory=dict, description="Platforms, online behavior")
    purchase_drivers: Dict[str, Any] = Field(default_factory=dict, description="What triggers purchases")
    cultural_context: Dict[str, Any] = Field(default_factory=dict, description="Cultural background, values")
    typology_profile: Dict[str, Any] = Field(default_factory=dict, description="MBTI, Enneagram, etc.")

    # ========================================
    # DIMENSION 2: PSYCHOGRAPHIC MAPPING
    # ========================================
    transformation_map: TransformationMap = Field(default_factory=TransformationMap)
    desires: Dict[str, List[DesireInstance]] = Field(
        default_factory=dict,
        description="Core desires by category with verbiage instances"
    )

    # ========================================
    # DIMENSION 3: IDENTITY
    # ========================================
    self_narratives: List[str] = Field(default_factory=list, description="'Because I am X, therefore I Y'")
    current_self_image: Optional[str] = Field(None, description="How they see themselves now")
    past_failures: Dict[str, Any] = Field(default_factory=dict, description="Failed attempts and who they blame")
    desired_self_image: Optional[str] = Field(None, description="Who they want to become")
    identity_artifacts: List[str] = Field(default_factory=list, description="Brands/objects tied to desired identity")

    # ========================================
    # DIMENSION 4: SOCIAL DYNAMICS
    # ========================================
    social_relations: SocialRelations = Field(default_factory=SocialRelations)

    # ========================================
    # DIMENSION 5: WORLDVIEW
    # ========================================
    worldview: Optional[str] = Field(None, description="General interpretation of reality")
    world_stories: Optional[str] = Field(None, description="Heroes/villains, cause/effect narratives")
    core_values: List[str] = Field(default_factory=list)
    forces_of_good: List[str] = Field(default_factory=list)
    forces_of_evil: List[str] = Field(default_factory=list)
    cultural_zeitgeist: Optional[str] = Field(None, description="The era/moment they believe they're in")
    allergies: Dict[str, str] = Field(default_factory=dict, description="{trigger: reaction} - messaging turn-offs")

    # ========================================
    # DIMENSION 6: DOMAIN SENTIMENT (Product-Specific)
    # ========================================
    outcomes_jtbd: DomainSentiment = Field(default_factory=DomainSentiment, description="Jobs to be done")
    pain_points: DomainSentiment = Field(default_factory=DomainSentiment)
    desired_features: List[str] = Field(default_factory=list)
    failed_solutions: List[str] = Field(default_factory=list, description="What they've tried that didn't work")
    buying_objections: DomainSentiment = Field(default_factory=DomainSentiment)
    familiar_promises: List[str] = Field(default_factory=list, description="Claims they've heard and are skeptical of")

    # ========================================
    # DIMENSION 7: PURCHASE BEHAVIOR
    # ========================================
    pain_symptoms: List[str] = Field(default_factory=list, description="Observable signs of pain points")
    activation_events: List[str] = Field(default_factory=list, description="What triggers purchase NOW")
    purchasing_habits: Optional[str] = Field(None, description="How they typically buy")
    decision_process: Optional[str] = Field(None, description="Steps they go through")
    current_workarounds: List[str] = Field(default_factory=list, description="Hacks they use instead of buying")

    # ========================================
    # DIMENSION 8: 3D OBJECTIONS
    # ========================================
    emotional_risks: List[str] = Field(default_factory=list, description="What they're afraid of feeling")
    barriers_to_behavior: List[str] = Field(default_factory=list, description="What stops them from acting")

    # ========================================
    # META
    # ========================================
    source_type: SourceType = Field(default=SourceType.MANUAL)
    source_data: Dict[str, Any] = Field(default_factory=dict, description="Raw analysis data that generated this")
    confidence_score: Optional[float] = Field(None, ge=0.0, le=1.0)

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "Worried First-Time Dog Mom",
                "persona_type": "product_specific",
                "snapshot": "First-time dog owner, 28-40, treats her dog like family. Constantly researches products and worries about making the wrong choice.",
                "demographics": {
                    "age_range": "28-40",
                    "gender": "female",
                    "income_level": "Middle to upper-middle class"
                },
                "desires": {
                    "care_protection": [
                        {"text": "I want to give my dog the absolute best", "source": "review"}
                    ],
                    "social_approval": [
                        {"text": "I want the vet to say I'm doing a great job", "source": "manual"}
                    ]
                },
                "pain_points": {
                    "emotional": ["Worry about making wrong choice", "Guilt when can't afford premium"],
                    "functional": ["Hard to find products that actually work"]
                }
            }
        }
    }


class PersonaSummary(BaseModel):
    """Lightweight persona for lists and selections."""
    id: UUID
    name: str
    persona_type: PersonaType
    is_primary: bool
    snapshot: Optional[str] = None
    source_type: SourceType


class ProductPersonaLink(BaseModel):
    """Link between a product and a persona with weight/priority."""
    id: Optional[UUID] = None
    product_id: UUID
    persona_id: UUID
    is_primary: bool = False
    weight: float = Field(default=1.0, ge=0.0, le=1.0, description="Weight for multi-persona targeting")
    notes: Optional[str] = None


class CompetitorSummary(BaseModel):
    """Competitor summary for lists."""
    id: UUID
    name: str
    website_url: Optional[str] = None
    ads_count: int = 0
    last_analyzed_at: Optional[datetime] = None


class CompetitorAdAnalysisResult(BaseModel):
    """Result from analyzing a competitor ad."""
    products_mentioned: List[str] = Field(default_factory=list)
    benefits_mentioned: List[str] = Field(default_factory=list)
    pain_points_addressed: List[str] = Field(default_factory=list)
    desires_appealed: Dict[str, List[str]] = Field(default_factory=dict, description="{desire_category: [instances]}")
    hooks_extracted: List[Dict[str, Any]] = Field(default_factory=list, description="[{text, type, notes}]")
    messaging_patterns: List[str] = Field(default_factory=list)
    awareness_level: Optional[int] = Field(None, ge=1, le=5, description="Eugene Schwartz awareness level 1-5")
    awareness_level_reasoning: Optional[str] = None


class CopyBrief(BaseModel):
    """Persona data formatted for ad copy generation."""
    persona_name: str
    snapshot: Optional[str] = None
    target_demo: Dict[str, Any] = Field(default_factory=dict)

    # For hooks
    primary_desires: List[str] = Field(default_factory=list, description="Top desires to appeal to")
    top_pain_points: List[str] = Field(default_factory=list, description="Key pain points to address")

    # For copy
    their_language: List[str] = Field(default_factory=list, description="Self-narratives to mirror")
    transformation: Dict[str, List[str]] = Field(default_factory=dict, description="{before: [], after: []}")

    # For objection handling
    objections: List[str] = Field(default_factory=list)
    failed_solutions: List[str] = Field(default_factory=list)

    # For urgency
    activation_events: List[str] = Field(default_factory=list)

    # Avoid these
    allergies: Dict[str, str] = Field(default_factory=dict, description="Messaging turn-offs to avoid")


# ============================================================================
# Belief-First Planning Models
# ============================================================================

class BeliefOffer(BaseModel):
    """Versioned offer for a product."""
    id: Optional[UUID] = None
    product_id: UUID
    name: str
    description: Optional[str] = None
    urgency_drivers: List[str] = Field(default_factory=list, description="Urgency/incentive drivers")
    active: bool = True
    created_by: Optional[UUID] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SubLayerType(str):
    """Enum for the 6 canonical sub-layer types."""
    GEOGRAPHY_LOCALE = "geography_locale"
    ASSET_SPECIFIC = "asset_specific"
    ENVIRONMENT_CONTEXT = "environment_context"
    LIFESTYLE_USAGE = "lifestyle_usage"
    PURCHASE_CONSTRAINTS = "purchase_constraints"
    VALUES_IDENTITY = "values_identity"


class BeliefSubLayer(BaseModel):
    """Persona relevance modifier (6 canonical types only)."""
    id: Optional[UUID] = None
    persona_id: UUID
    sublayer_type: str = Field(..., description="One of: geography_locale, asset_specific, environment_context, lifestyle_usage, purchase_constraints, values_identity")
    name: str
    values: List[str] = Field(default_factory=list, description="Array of values for this sublayer")
    notes: Optional[str] = None
    created_by: Optional[UUID] = None
    created_at: Optional[datetime] = None


class BeliefJTBDFramed(BaseModel):
    """Persona-framed JTBD for advertising."""
    id: Optional[UUID] = None
    persona_id: UUID
    product_id: UUID
    name: str
    description: Optional[str] = None
    progress_statement: Optional[str] = Field(None, description="When I..., I want to..., so I can...")
    source: str = Field(default="manual", description="manual, extracted_from_persona, or ai_generated")
    created_by: Optional[UUID] = None
    created_at: Optional[datetime] = None


class AngleStatus(str):
    """Status for angle testing."""
    UNTESTED = "untested"
    TESTING = "testing"
    WINNER = "winner"
    LOSER = "loser"


class BeliefAngle(BaseModel):
    """Angle belief that explains why the JTBD exists and why this solution works."""
    id: Optional[UUID] = None
    jtbd_framed_id: UUID
    name: str
    belief_statement: str = Field(..., description="The core belief/explanation")
    explanation: Optional[str] = Field(None, description="Why this angle works")
    status: str = Field(default="untested", description="untested, testing, winner, or loser")
    created_by: Optional[UUID] = None
    created_at: Optional[datetime] = None


# ============================================================================
# Angle Pipeline Models
# ============================================================================

class CandidateType(str, Enum):
    """Types of angle candidates."""
    PAIN_SIGNAL = "pain_signal"
    PATTERN = "pattern"
    JTBD = "jtbd"
    AD_HYPOTHESIS = "ad_hypothesis"
    QUOTE = "quote"
    UMP = "ump"  # Unique Mechanism Problem
    UMS = "ums"  # Unique Mechanism Solution


class CandidateSourceType(str, Enum):
    """Sources for angle candidates."""
    BELIEF_REVERSE_ENGINEER = "belief_reverse_engineer"
    REDDIT_RESEARCH = "reddit_research"
    AD_PERFORMANCE = "ad_performance"
    COMPETITOR_RESEARCH = "competitor_research"
    BRAND_RESEARCH = "brand_research"


class CandidateStatus(str, Enum):
    """Workflow status for candidates."""
    CANDIDATE = "candidate"
    APPROVED = "approved"
    REJECTED = "rejected"
    MERGED = "merged"


class CandidateConfidence(str, Enum):
    """Confidence levels based on evidence count."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class EvidenceType(str, Enum):
    """Types of evidence supporting candidates."""
    PAIN_SIGNAL = "pain_signal"
    QUOTE = "quote"
    PATTERN = "pattern"
    SOLUTION = "solution"
    HYPOTHESIS = "hypothesis"


class AngleCandidateEvidence(BaseModel):
    """Evidence supporting an angle candidate."""
    id: Optional[UUID] = None
    candidate_id: UUID

    # Evidence content
    evidence_type: str = Field(..., description="Type: pain_signal, quote, pattern, solution, hypothesis")
    evidence_text: str = Field(..., description="The actual evidence text")

    # Source details
    source_type: str = Field(..., description="Source system that provided this evidence")
    source_run_id: Optional[UUID] = Field(None, description="Run ID from source system")
    source_post_id: Optional[str] = Field(None, description="Original post ID (e.g., Reddit post ID)")
    source_url: Optional[str] = Field(None, description="URL to original source")

    # Quality indicators
    engagement_score: Optional[int] = Field(None, description="Engagement from source (upvotes, etc.)")
    confidence_score: Optional[float] = Field(None, ge=0, le=1, description="LLM confidence 0-1")

    created_at: Optional[datetime] = None


class AngleCandidate(BaseModel):
    """
    Unified staging model for research insights before promotion to belief_angles.

    Candidates come from 5 sources:
    - Belief Reverse Engineer pipeline
    - Reddit Research
    - Ad Performance Analysis
    - Competitor Research
    - Brand/Consumer Research

    Candidates are ranked by frequency_score (how many evidence items support them)
    and can be promoted to belief_angles via the Research Insights UI.
    """
    id: Optional[UUID] = None
    product_id: UUID
    brand_id: Optional[UUID] = None

    # Core content
    name: str = Field(..., description="Short descriptive name for the candidate")
    belief_statement: str = Field(..., description="The core belief/insight this candidate represents")
    explanation: Optional[str] = Field(None, description="Additional context or explanation")
    candidate_type: str = Field(..., description="Type: pain_signal, pattern, jtbd, ad_hypothesis, quote, ump, ums")

    # Source tracking
    source_type: str = Field(..., description="Source: belief_reverse_engineer, reddit_research, ad_performance, competitor_research, brand_research")
    source_run_id: Optional[UUID] = Field(None, description="Run ID from source system")
    competitor_id: Optional[UUID] = Field(None, description="Competitor ID if from competitor research")

    # Frequency/confidence scoring
    frequency_score: int = Field(default=1, ge=1, description="Number of evidence items")
    confidence: str = Field(default="LOW", description="Confidence: LOW (1), MEDIUM (2-4), HIGH (5+)")

    # Workflow status
    status: str = Field(default="candidate", description="Status: candidate, approved, rejected, merged")
    promoted_angle_id: Optional[UUID] = Field(None, description="Reference to belief_angles if promoted")

    # Metadata
    tags: Optional[List[str]] = Field(default=None, description="Optional tags for categorization")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    reviewed_at: Optional[datetime] = None
    reviewed_by: Optional[UUID] = None

    # Related data (populated when fetching full candidate)
    evidence: List[AngleCandidateEvidence] = Field(default_factory=list, description="Supporting evidence")

    @classmethod
    def calculate_confidence(cls, evidence_count: int) -> str:
        """Calculate confidence level based on evidence count."""
        if evidence_count >= 5:
            return CandidateConfidence.HIGH.value
        elif evidence_count >= 2:
            return CandidateConfidence.MEDIUM.value
        return CandidateConfidence.LOW.value


class PlanStatus(str):
    """Status for plans."""
    DRAFT = "draft"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"


class TemplateStrategy(str):
    """Strategy for template assignment."""
    FIXED = "fixed"
    RANDOM = "random"


class BeliefPlan(BaseModel):
    """Ad testing plan with compiled payload."""
    id: Optional[UUID] = None
    name: str
    brand_id: UUID
    product_id: UUID
    offer_id: Optional[UUID] = None
    persona_id: UUID
    jtbd_framed_id: UUID
    phase_id: int = Field(default=1, ge=1, le=6, description="Testing phase 1-6")
    template_strategy: str = Field(default="fixed", description="fixed or random")
    ads_per_angle: int = Field(default=3, ge=1)
    status: str = Field(default="draft", description="draft, ready, running, completed")
    compiled_payload: Optional[Dict[str, Any]] = Field(None, description="Generator-ready deterministic payload")
    created_by: Optional[UUID] = None
    created_at: Optional[datetime] = None
    compiled_at: Optional[datetime] = None

    # Populated when fetching full plan
    angles: List[BeliefAngle] = Field(default_factory=list)
    templates: List[Dict[str, Any]] = Field(default_factory=list)


class BeliefPlanRun(BaseModel):
    """Phase run tracking for a plan."""
    id: Optional[UUID] = None
    plan_id: UUID
    phase_id: int = Field(..., ge=1, le=6)
    status: str = Field(default="pending", description="pending, running, completed, failed")
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    results: Optional[Dict[str, Any]] = Field(None, description="Performance data, winner angles, etc.")
    created_at: Optional[datetime] = None


class CompiledPlanPayload(BaseModel):
    """The compiled, generator-ready payload for ad creator consumption."""
    plan_id: UUID
    brand_id: UUID
    product_id: UUID
    offer_id: Optional[UUID] = None
    persona_id: UUID
    jtbd_framed_id: UUID
    phase_id: int
    angles: List[Dict[str, Any]] = Field(..., description="[{angle_id, name, belief_statement, headline_variants?, primary_text_variants?}]")
    templates: List[Dict[str, Any]] = Field(..., description="[{template_id, name}]")
    template_strategy: str
    ads_per_angle: int
    locked_fields: List[str] = Field(default_factory=list)
    allowed_variations: List[str] = Field(default_factory=list)
    compiled_at: datetime
    status: str


# ============================================================================
# Copy Scaffolds & Template Evaluation Models
# ============================================================================

class CopyScaffold(BaseModel):
    """
    Tokenized copy template for belief-safe ad generation.

    Scaffolds contain placeholder tokens like {SYMPTOM_1}, {ANGLE_CLAIM}, etc.
    that are filled at generation time with context from the plan.
    """
    id: Optional[UUID] = None
    scope: str = Field(..., description="headline or primary_text")
    name: str = Field(..., description="Scaffold identifier (e.g., H1-Observation-1)")
    template_text: str = Field(..., description="Template with {TOKEN} placeholders")
    phase_min: int = Field(default=1, ge=1, le=6, description="Minimum phase this scaffold applies to")
    phase_max: int = Field(default=6, ge=1, le=6, description="Maximum phase this scaffold applies to")
    awareness_targets: List[str] = Field(
        default_factory=lambda: ["problem-aware", "early-solution-aware"],
        description="Target awareness levels"
    )
    max_chars: Optional[int] = Field(None, description="Max character limit (40 for headlines)")
    guardrails: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Validation rules")
    template_requirements: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Required tokens")
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class AngleCopySet(BaseModel):
    """
    Generated copy variants for a specific angle.

    Copy is generated per-angle (not per-ad) to ensure consistent belief expression
    across all ads testing that angle.
    """
    id: Optional[UUID] = None
    brand_id: Optional[UUID] = None
    product_id: Optional[UUID] = None
    offer_id: Optional[UUID] = None
    persona_id: Optional[UUID] = None
    jtbd_framed_id: Optional[UUID] = None
    angle_id: UUID = Field(..., description="The angle this copy set belongs to")
    phase_id: int = Field(default=1, ge=1, le=6)
    headline_variants: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="[{text, scaffold_id, tokens_used}]"
    )
    primary_text_variants: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="[{text, scaffold_id, tokens_used}]"
    )
    token_context: Optional[Dict[str, str]] = Field(
        default_factory=dict,
        description="Token values used for generation"
    )
    guardrails_validated: bool = Field(default=False, description="Whether guardrails have been checked")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TemplateEvaluation(BaseModel):
    """
    Evaluation scores for template phase eligibility.

    Uses a 6-dimension rubric (D1-D6) to determine if a template
    is suitable for Phase 1-2 belief testing.
    """
    id: Optional[UUID] = None
    template_id: UUID = Field(..., description="The template being evaluated")
    template_source: str = Field(..., description="ad_brief_templates or scraped_templates")
    phase_id: int = Field(..., ge=1, le=6, description="Phase being evaluated for")

    # D1-D5: Scored 0-3
    d1_belief_clarity: int = Field(..., ge=0, le=3, description="Can template clearly express a single belief?")
    d2_neutrality: int = Field(..., ge=0, le=3, description="Free of sales bias, offers, urgency?")
    d3_reusability: int = Field(..., ge=0, le=3, description="Can work across different angles?")
    d4_problem_aware_entry: int = Field(..., ge=0, le=3, description="Supports problem-aware audiences?")
    d5_slot_availability: int = Field(..., ge=0, le=3, description="Has clear text slots?")

    # D6: Pass/fail
    d6_compliance_pass: bool = Field(..., description="No before/after, medical claims, guarantees?")

    # Computed (optional - computed in DB)
    total_score: Optional[int] = Field(None, description="Sum of D1-D5 (0-15)")
    eligible: Optional[bool] = Field(None, description="Phase 1-2 eligible: D6 pass AND total>=12 AND D2>=2")

    evaluation_notes: Optional[str] = None
    evaluated_by: str = Field(default="ai", description="ai or human")
    evaluated_at: Optional[datetime] = None

    @property
    def computed_total_score(self) -> int:
        """Calculate total score from D1-D5."""
        return self.d1_belief_clarity + self.d2_neutrality + self.d3_reusability + self.d4_problem_aware_entry + self.d5_slot_availability

    @property
    def computed_eligible(self) -> bool:
        """Determine Phase 1-2 eligibility."""
        return self.d6_compliance_pass and self.computed_total_score >= 12 and self.d2_neutrality >= 2


# ============================================================================
# Reddit Sentiment Analysis Models
# ============================================================================

class SentimentCategory(str, Enum):
    """
    The 6 sentiment buckets that map to belief-first planning fields.

    Mapping to persona fields:
    - PAIN_POINT -> pain_points (DomainSentiment)
    - DESIRED_OUTCOME -> outcomes_jtbd (DomainSentiment)
    - BUYING_OBJECTION -> buying_objections (DomainSentiment)
    - FAILED_SOLUTION -> failed_solutions (List)
    - DESIRED_FEATURE -> desired_features (List)
    - FAMILIAR_SOLUTION -> familiar_promises (List)
    """
    PAIN_POINT = "PAIN_POINT"
    DESIRED_OUTCOME = "DESIRED_OUTCOME"
    BUYING_OBJECTION = "BUYING_OBJECTION"
    FAILED_SOLUTION = "FAILED_SOLUTION"
    DESIRED_FEATURE = "DESIRED_FEATURE"
    FAMILIAR_SOLUTION = "FAMILIAR_SOLUTION"


class RedditPost(BaseModel):
    """
    A scraped Reddit post with engagement metrics and LLM scoring.

    Used during pipeline processing before database persistence.
    """
    id: Optional[UUID] = None
    reddit_id: str = Field(..., description="Reddit post ID (e.g., 't3_abc123')")
    subreddit: str = Field(..., description="Subreddit name without r/")
    title: str = Field(..., description="Post title")
    body: Optional[str] = Field(None, description="Post body/selftext")
    author: Optional[str] = Field(None, description="Reddit username")
    url: Optional[str] = Field(None, description="Full URL to post")

    # Engagement metrics from Reddit
    score: int = Field(default=0, description="Upvotes (net score)")
    upvote_ratio: float = Field(default=0.0, ge=0.0, le=1.0, description="Upvote ratio")
    num_comments: int = Field(default=0, ge=0, description="Number of comments")
    created_utc: Optional[datetime] = Field(None, description="When post was created")

    # Pipeline scoring (populated by LLM nodes)
    relevance_score: Optional[float] = Field(None, ge=0.0, le=1.0, description="Relevance to persona/topic")
    relevance_reasoning: Optional[str] = Field(None, description="LLM reasoning for relevance score")
    signal_score: Optional[float] = Field(None, ge=0.0, le=1.0, description="Signal vs noise score")
    signal_reasoning: Optional[str] = Field(None, description="LLM reasoning for signal score")
    intent_score: Optional[float] = Field(None, ge=0.0, le=1.0, description="Buyer intent/sophistication")
    intent_reasoning: Optional[str] = Field(None, description="LLM reasoning for intent score")
    combined_score: Optional[float] = Field(None, ge=0.0, le=1.0, description="Combined weighted score")

    @property
    def content_for_analysis(self) -> str:
        """Combine title and body for LLM analysis."""
        if self.body:
            return f"{self.title}\n\n{self.body}"
        return self.title


class RedditComment(BaseModel):
    """
    A Reddit comment from a scraped post.

    Optional enrichment for deeper analysis.
    """
    id: Optional[UUID] = None
    reddit_id: str = Field(..., description="Reddit comment ID")
    post_id: Optional[UUID] = Field(None, description="Parent post UUID")
    parent_id: Optional[str] = Field(None, description="Parent comment ID for threading")
    body: str = Field(..., description="Comment text")
    author: Optional[str] = Field(None, description="Reddit username")
    score: int = Field(default=0, description="Upvotes")
    created_utc: Optional[datetime] = Field(None, description="When comment was posted")


class RedditSentimentQuote(BaseModel):
    """
    An extracted quote categorized into sentiment buckets.

    These quotes are extracted by Claude Opus 4.5 and can be
    synced to persona fields for belief-first planning.
    """
    id: Optional[UUID] = None
    post_id: Optional[UUID] = Field(None, description="Source post UUID")
    comment_id: Optional[UUID] = Field(None, description="Source comment UUID if from comment")

    quote_text: str = Field(..., description="Exact verbatim quote from post/comment")
    source_type: str = Field(..., description="post_title, post_body, or comment")

    # Categorization
    sentiment_category: SentimentCategory = Field(..., description="Primary sentiment bucket")
    sentiment_subtype: Optional[str] = Field(
        None,
        description="For DomainSentiment fields: emotional, social, or functional"
    )

    # AI extraction metadata
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0, description="Extraction confidence")
    extraction_reasoning: Optional[str] = Field(None, description="Why this quote fits the category")

    # Sync tracking
    synced_to_persona: bool = Field(default=False, description="Whether synced to persona fields")
    synced_at: Optional[datetime] = Field(None, description="When synced to persona")


class RedditScrapeConfig(BaseModel):
    """
    Configuration for a Reddit scraping run.

    Passed to the pipeline to control scraping and filtering behavior.
    At least one of search_queries or subreddits must be provided.
    """
    search_queries: List[str] = Field(default_factory=list, description="Search queries (optional if subreddits provided)")
    subreddits: Optional[List[str]] = Field(None, description="Subreddits to scrape (optional if search_queries provided)")

    @model_validator(mode="after")
    def require_queries_or_subreddits(self) -> "RedditScrapeConfig":
        """Ensure at least one of search_queries or subreddits is provided."""
        if not self.search_queries and not self.subreddits:
            raise ValueError("At least one of search_queries or subreddits must be provided")
        return self
    timeframe: str = Field(
        default="month",
        description="Time range: hour, day, week, month, year, all"
    )
    sort_by: str = Field(
        default="relevance",
        description="Sort order: relevance, hot, top, new, comments"
    )
    max_posts: int = Field(default=500, ge=10, le=5000, description="Maximum posts to scrape")
    include_nsfw: bool = Field(default=False, description="Include NSFW content")
    scrape_comments: bool = Field(default=True, description="Also scrape comments")
    max_comments_per_post: int = Field(default=50, ge=0, le=500, description="Max comments per post")

    # Filtering thresholds
    min_upvotes: int = Field(default=20, ge=0, description="Minimum post upvotes")
    min_comments: int = Field(default=5, ge=0, description="Minimum comment count")
    relevance_threshold: float = Field(default=0.6, ge=0.0, le=1.0, description="Min relevance score")
    signal_threshold: float = Field(default=0.5, ge=0.0, le=1.0, description="Min signal score")
    top_percentile: float = Field(default=0.20, ge=0.01, le=1.0, description="Top X% to keep")


class RedditScrapeRunResult(BaseModel):
    """
    Summary result from a Reddit sentiment analysis run.

    Returned by the pipeline after completion.
    """
    run_id: UUID = Field(..., description="Pipeline run UUID")
    status: str = Field(..., description="completed, failed, etc.")

    # Counts at each stage
    posts_scraped: int = Field(default=0, description="Total posts from Apify")
    posts_after_engagement: int = Field(default=0, description="After engagement filter")
    posts_after_relevance: int = Field(default=0, description="After relevance filter")
    posts_after_signal: int = Field(default=0, description="After signal filter")
    posts_top_selected: int = Field(default=0, description="Top percentile selected")

    # Quote extraction
    quotes_extracted: int = Field(default=0, description="Total quotes extracted")
    quotes_by_category: Dict[str, int] = Field(
        default_factory=dict,
        description="Count per sentiment category"
    )
    quotes_synced: int = Field(default=0, description="Quotes synced to persona")

    # Cost tracking
    apify_cost: float = Field(default=0.0, description="Estimated Apify cost")
    llm_cost_estimate: float = Field(default=0.0, description="Estimated LLM cost")

    # Timing
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None


# ============================================================================
# Meta Ads Performance Models
# ============================================================================

class MetaAdPerformance(BaseModel):
    """
    Daily performance snapshot for a Meta (Facebook/Instagram) ad.

    Stores all key metrics for the feedback loop including spend, ROAS, CTR,
    and conversion metrics. Video metrics are optional.
    """
    id: Optional[UUID] = Field(None, description="Internal UUID")
    meta_ad_account_id: str = Field(..., description="Meta ad account ID (e.g., act_123456789)")
    meta_ad_id: str = Field(..., description="Meta ad ID")
    meta_campaign_id: str = Field(..., description="Meta campaign ID")
    meta_adset_id: Optional[str] = Field(None, description="Meta ad set ID")
    ad_name: Optional[str] = Field(None, description="Ad name (for matching)")
    adset_name: Optional[str] = Field(None, description="Ad set name")
    ad_status: Optional[str] = Field(None, description="Ad status: ACTIVE, PAUSED, DELETED, etc.")
    date: datetime = Field(..., description="Date of this performance snapshot")

    # Core metrics
    spend: Optional[float] = Field(None, ge=0, description="Total spend in currency")
    impressions: Optional[int] = Field(None, ge=0, description="Total impressions")
    reach: Optional[int] = Field(None, ge=0, description="Unique people reached")
    frequency: Optional[float] = Field(None, ge=0, description="Average times shown per person")
    cpm: Optional[float] = Field(None, ge=0, description="Cost per 1000 impressions")

    # Link metrics
    link_clicks: Optional[int] = Field(None, ge=0, description="Clicks on links")
    link_ctr: Optional[float] = Field(None, ge=0, description="Link CTR (outbound_clicks_ctr)")
    link_cpc: Optional[float] = Field(None, ge=0, description="Cost per link click")

    # Conversion metrics
    add_to_carts: Optional[int] = Field(None, ge=0, description="Add to cart events")
    cost_per_add_to_cart: Optional[float] = Field(None, ge=0, description="Cost per add to cart")
    purchases: Optional[int] = Field(None, ge=0, description="Purchase events")
    purchase_value: Optional[float] = Field(None, ge=0, description="Total purchase value")
    roas: Optional[float] = Field(None, ge=0, description="Return on ad spend")
    conversion_rate: Optional[float] = Field(None, ge=0, description="Purchases / link clicks * 100")

    # Video metrics (nullable)
    video_views: Optional[int] = Field(None, ge=0, description="3-second video views")
    video_avg_watch_time: Optional[float] = Field(None, ge=0, description="Average watch time in seconds")
    video_p25_watched: Optional[int] = Field(None, ge=0, description="Videos watched to 25%")
    video_p50_watched: Optional[int] = Field(None, ge=0, description="Videos watched to 50%")
    video_p75_watched: Optional[int] = Field(None, ge=0, description="Videos watched to 75%")
    video_p100_watched: Optional[int] = Field(None, ge=0, description="Videos watched to 100%")

    # Raw data for extensibility
    raw_actions: Optional[Dict[str, Any]] = Field(None, description="Full actions array from Meta")
    raw_costs: Optional[Dict[str, Any]] = Field(None, description="Full cost_per_action_type array")

    # Tracking
    brand_id: Optional[UUID] = Field(None, description="Associated brand ID")
    fetched_at: Optional[datetime] = Field(None, description="When this data was fetched")


class MetaAdSet(BaseModel):
    """
    Cached ad set metadata from Meta Ads API.

    Ad sets sit between campaigns and ads in Meta's hierarchy.
    """
    id: Optional[UUID] = Field(None, description="Internal UUID")
    meta_ad_account_id: str = Field(..., description="Meta ad account ID")
    meta_adset_id: str = Field(..., description="Meta ad set ID")
    meta_campaign_id: str = Field(..., description="Parent campaign ID")
    name: Optional[str] = Field(None, description="Ad set name")
    status: Optional[str] = Field(None, description="ACTIVE, PAUSED, DELETED, ARCHIVED")
    optimization_goal: Optional[str] = Field(None, description="CONVERSIONS, LINK_CLICKS, etc.")
    billing_event: Optional[str] = Field(None, description="IMPRESSIONS, LINK_CLICKS, etc.")
    daily_budget: Optional[float] = Field(None, ge=0, description="Daily budget")
    lifetime_budget: Optional[float] = Field(None, ge=0, description="Lifetime budget")
    brand_id: Optional[UUID] = Field(None, description="Associated brand ID")
    synced_at: Optional[datetime] = Field(None, description="When this data was synced")


class MetaAdMapping(BaseModel):
    """
    Links a ViralTracker generated ad to a Meta ad for performance tracking.

    The link can be created automatically (by matching the 8-char ID in ad name)
    or manually by the user.
    """
    id: Optional[UUID] = Field(None, description="Internal UUID")
    generated_ad_id: UUID = Field(..., description="ViralTracker generated_ads.id")
    meta_ad_id: str = Field(..., description="Meta ad ID")
    meta_ad_account_id: str = Field(..., description="Meta ad account ID")
    meta_campaign_id: str = Field(..., description="Meta campaign ID")
    creative_hash: Optional[str] = Field(None, description="Meta image_hash (for future use)")
    linked_at: Optional[datetime] = Field(None, description="When the link was created")
    linked_by: str = Field(default="manual", description="'auto' or 'manual'")


class MetaCampaign(BaseModel):
    """
    Cached campaign metadata from Meta Ads API.

    Used for display and filtering in the performance dashboard.
    """
    id: Optional[UUID] = Field(None, description="Internal UUID")
    meta_ad_account_id: str = Field(..., description="Meta ad account ID")
    meta_campaign_id: str = Field(..., description="Meta campaign ID")
    name: Optional[str] = Field(None, description="Campaign name")
    status: Optional[str] = Field(None, description="ACTIVE, PAUSED, DELETED, ARCHIVED")
    objective: Optional[str] = Field(None, description="Campaign objective (CONVERSIONS, etc.)")
    daily_budget: Optional[float] = Field(None, ge=0, description="Daily budget in currency")
    lifetime_budget: Optional[float] = Field(None, ge=0, description="Lifetime budget in currency")
    brand_id: Optional[UUID] = Field(None, description="Associated brand ID")
    synced_at: Optional[datetime] = Field(None, description="When this data was synced")


class BrandAdAccount(BaseModel):
    """
    Links a brand to a Meta ad account.

    Supports multiple accounts per brand for future expansion.
    """
    id: Optional[UUID] = Field(None, description="Internal UUID")
    brand_id: UUID = Field(..., description="Brand ID")
    meta_ad_account_id: str = Field(..., description="Meta ad account ID (e.g., act_123456789)")
    account_name: Optional[str] = Field(None, description="Display name for the account")
    is_primary: bool = Field(default=True, description="Primary account for this brand")
    created_at: Optional[datetime] = Field(None, description="When this link was created")


# ============================================================================
# Belief-First Reverse Engineer Models
# ============================================================================

class EvidenceStatus(str, Enum):
    """
    Tracks the provenance of each field in the belief canvas.

    - OBSERVED: From database or research (factual)
    - INFERRED: Derived from message analysis (educated guess)
    - HYPOTHESIS: Needs validation before use
    """
    OBSERVED = "observed"
    INFERRED = "inferred"
    HYPOTHESIS = "hypothesis"


class ProofType(str, Enum):
    """
    Comprehensive proof type taxonomy for belief-first messaging.

    Organized by proof category:
    - Problem Reality Proof (for UMP)
    - Mechanism Validity Proof (for UMS)
    - Solution Efficacy Proof
    - Identity & Social Proof
    - Risk & Commitment Proof
    """
    # Problem Reality Proof (for UMP)
    OBSERVATIONAL = "observational"
    PATTERN = "pattern"
    HISTORICAL = "historical"
    RELATABILITY = "relatability"
    ANALOGY_METAPHOR = "analogy_metaphor"
    LOGICAL_INEVITABILITY = "logical_inevitability"

    # Mechanism Validity Proof (for UMS)
    SCIENTIFIC = "scientific"
    DATA_DRIVEN = "data_driven"
    AUTHORITY = "authority"
    VISUAL = "visual"

    # Solution Efficacy Proof
    TANGIBLE_OUTCOMES = "tangible_outcomes"
    COMPARATIVE = "comparative"
    CONSISTENCY = "consistency"
    OUTCOME_DATA = "outcome_data"

    # Identity & Social Proof
    PERSONA_TESTIMONIALS = "persona_testimonials"
    ANECDOTES = "anecdotes"
    CULTURAL = "cultural"
    EMOTIONAL = "emotional"

    # Risk & Commitment Proof
    GUARANTEE = "guarantee"
    TRIAL = "trial"
    ETHICAL = "ethical"
    SCARCITY = "scarcity"


class ConstraintType(str, Enum):
    """
    The 6 canonical constraint types that limit action BEFORE belief.

    These are persona-level inputs, not commitment-stage risks.
    """
    TIME = "time"
    MONEY = "money"
    ENERGY = "energy"
    IDENTITY = "identity"
    REPUTATION_SOCIAL = "reputation_social"
    COGNITIVE_LOAD = "cognitive_load"


class AwarenessLevel(str, Enum):
    """
    Eugene Schwartz awareness levels for market sophistication.
    """
    UNAWARE = "unaware"
    PROBLEM_AWARE = "problem_aware"
    SOLUTION_AWARE = "solution_aware"
    PRODUCT_AWARE = "product_aware"
    MOST_AWARE = "most_aware"


class BeliefLayer(str, Enum):
    """
    Classification of which belief-first layer a message maps to.
    """
    EXPRESSION = "expression"
    UMP_SEED = "ump_seed"
    UMS_SEED = "ums_seed"
    PERSONA_FILTER = "persona_filter"
    BENEFIT = "benefit"
    PROOF = "proof"
    OTHER = "other"


class RiskFlagType(str, Enum):
    """
    Types of compliance and messaging risks to flag.
    """
    MEDICAL_CLAIM = "medical_claim"
    DRUG_REFERENCE = "drug_reference"
    OVERPROMISE = "overpromise"
    AMBIGUITY = "ambiguity"
    CONTRADICTION = "contradiction"
    PROMISE_BOUNDARY = "promise_boundary"


class RiskSeverity(str, Enum):
    """
    Severity levels for risk flags.
    """
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ProductContext(BaseModel):
    """
    Product truth pulled from the database for belief canvas assembly.

    Used to fill canvas with OBSERVED (factual) data rather than inferred.
    """
    product_id: UUID
    name: str
    category: str
    format: Optional[str] = None

    # Nutrition (if applicable)
    macros: Optional[Dict[str, Any]] = Field(
        None,
        description="Nutrition data: protein_g, fiber_g, sugar_g, calories"
    )

    # Product details
    ingredients: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of {name, purpose, notes}"
    )
    allowed_claims: List[str] = Field(
        default_factory=list,
        description="Claims that are allowed for this product"
    )
    disallowed_claims: List[str] = Field(
        default_factory=list,
        description="Claims that must NOT be made"
    )
    promise_boundary_default: Optional[str] = Field(
        None,
        description="Default promise boundary text"
    )

    # Pre-built assets
    mechanisms: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Mechanism library entries if available"
    )
    proof_assets: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Existing proof assets with tags"
    )
    contraindications: List[str] = Field(
        default_factory=list,
        description="Warnings or contraindications"
    )


class MessageClassification(BaseModel):
    """
    Classification of a single message into belief-first layers.

    Output from the LayerClassifierNode.
    """
    message: str = Field(..., description="The original message text")
    primary_layer: BeliefLayer = Field(..., description="Primary belief layer")
    secondary_layers: List[BeliefLayer] = Field(
        default_factory=list,
        description="Additional layers touched by this message"
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Classification confidence"
    )
    detected_topics: List[str] = Field(
        default_factory=list,
        description="Detected topics: sugar, boba, GLP-1, bloating, etc."
    )
    triggers_compliance_mode: bool = Field(
        default=False,
        description="Whether this message triggers compliance checks"
    )


class ResearchEvidenceItem(BaseModel):
    """
    A single piece of evidence extracted from research (Reddit, literature, etc.).
    """
    source_type: str = Field(..., description="reddit, literature, competitor")
    source_url: Optional[str] = None
    source_subreddit: Optional[str] = None
    raw_content: str = Field(..., description="Original text")
    extracted_signal: str = Field(..., description="What was extracted")
    signal_type: str = Field(
        ...,
        description="pain, solution_attempted, pattern, language, alternative"
    )
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    extracted_at: Optional[datetime] = None


class RedditResearchBundle(BaseModel):
    """
    Complete bundle of research extracted from Reddit scraping.

    Populates sections 1-9 of the Research Canvas.
    """
    queries_run: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of {subreddit, search_term}"
    )
    posts_analyzed_count: int = 0
    comments_analyzed_count: int = 0

    # Extracted signals
    extracted_pain: List[ResearchEvidenceItem] = Field(
        default_factory=list,
        description="Pain points and symptoms"
    )
    extracted_solutions_attempted: List[ResearchEvidenceItem] = Field(
        default_factory=list,
        description="Solutions tried and their outcomes"
    )
    extracted_language_bank: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="Symptom -> phrases mapping"
    )

    # Pattern detection
    pattern_detection: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="triggers, worsens, improves, helps, fails"
    )

    # JTBD candidates
    jtbd_candidates: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="functional, emotional, identity"
    )

    # Hypothesis support
    hypothesis_support_scores: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of {hypothesis, score, evidence_samples}"
    )


class ResearchCanvas(BaseModel):
    """
    Research/Discovery Canvas (Sections 1-9).

    Populated primarily by Reddit research in research_mode.
    """
    # Section 1-2: Market & Persona Context
    market_context: Dict[str, Any] = Field(
        default_factory=lambda: {
            "category": None,
            "market_sophistication": None,
            "awareness_levels_present": [],
            "dominant_problem_explanations": [],
            "common_solution_types": [],
            "cultural_historical_narratives": [],
        }
    )
    persona_context: Dict[str, Any] = Field(
        default_factory=lambda: {
            "primary_persona": None,
            "life_stage_role": None,
            "trigger_events": [],
            "environment_exposure_factors": [],
        }
    )

    # Section 3: Observed Pain & Friction
    observed_pain: Dict[str, Any] = Field(
        default_factory=lambda: {
            "symptoms_physical": [],
            "symptoms_emotional": [],
            "behavioral_workarounds": [],
            "avoidance_behaviors": [],
            "stated_problems": [],
            "language_used": [],
            "blame_targets": [],
        }
    )

    # Section 4: Pattern Detection
    pattern_detection: Dict[str, Any] = Field(
        default_factory=lambda: {
            "when_appears": [],
            "where_localizes": [],
            "when_improves": [],
            "when_worsens": [],
            "what_temporarily_helps": [],
            "what_reliably_fails": [],
        }
    )

    # Section 5: Historical Comparison
    historical_comparison: Dict[str, Any] = Field(
        default_factory=lambda: {
            "existed_historically": None,
            "when_increased": None,
            "what_changed_environmentally": [],
            "what_stayed_biologically_same": [],
        }
    )

    # Section 6: Solutions Attempted
    solutions_attempted: Dict[str, Any] = Field(
        default_factory=lambda: {
            "worked_briefly": [],
            "stopped_working": [],
            "never_worked": [],
            "why_they_think_it_failed": [],
        }
    )

    # Section 7: Desired Progress (JTBD)
    desired_progress: Dict[str, Any] = Field(
        default_factory=lambda: {
            "functional": [],
            "emotional": [],
            "identity": [],
        }
    )

    # Section 8: Knowledge Gaps
    knowledge_gaps: Dict[str, Any] = Field(
        default_factory=lambda: {
            "tension_progress_vs_failures": [],
            "missing_variables": [],
        }
    )

    # Section 9: Candidate Root Causes
    candidate_root_causes: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of {hypothesis, evidence_status, supporting_evidence}"
    )


class BeliefCanvas(BaseModel):
    """
    Belief/Messaging Canvas (Sections 10-15).

    Populated from message inference + product DB.
    """
    # Section 10: Belief Context
    belief_context: Dict[str, Any] = Field(
        default_factory=lambda: {
            "current_awareness_state": None,
            "brand_credibility": None,
            "why_now": None,
            "promise_boundary": None,
        }
    )

    # Section 11: Persona Filter
    persona_filter: Dict[str, Any] = Field(
        default_factory=lambda: {
            "jtbd": {
                "functional": None,
                "emotional": None,
                "identity": None,
            },
            "persona_sublayers": {
                "awareness_sophistication": None,
                "prior_failures": [],
                "skepticism_level": None,
            },
            "constraints": {
                "time": False,
                "money": False,
                "energy": False,
                "identity": False,
                "reputation_social": False,
                "cognitive_load": False,
            },
            "dominant_constraint": None,
            "constraint_to_avoid_triggering": None,
        }
    )

    # Section 12: Unique Mechanism
    unique_mechanism: Dict[str, Any] = Field(
        default_factory=lambda: {
            "ump": {
                "old_accepted_explanation": None,
                "reframed_root_cause": None,
                "why_past_solutions_failed": None,
                "externalized_blame": None,
                "missing_1_percent": None,
                "differentiation_check": {
                    "new_but_familiar": False,
                    "plausible_without_trust": False,
                    "uses_customer_language": False,
                },
                "problem_reality_proof_present": [],
                "problem_reality_proof_missing": [],
            },
            "ums": {
                "macro_solution_logic": None,
                "micro_mechanism": None,
                "mechanism_validity_proof_present": [],
                "mechanism_validity_proof_missing": [],
            },
            "reinterpreted_pain": {
                "problem_pain_symptoms": None,
                "how_mechanism_explains_past_pain": None,
            },
        }
    )

    # Section 13: Progress & Justification
    progress_justification: Dict[str, Any] = Field(
        default_factory=lambda: {
            "benefits": {
                "immediate": None,
                "short_term": None,
                "long_term": None,
            },
            "features": [],
        }
    )

    # Section 14: Proof Stack
    proof_stack: Dict[str, Any] = Field(
        default_factory=lambda: {
            "solution_efficacy": {
                "present": [],
                "missing": [],
            },
            "identity_social": {
                "present": [],
                "missing": [],
            },
            "risk_commitment": {
                "present": [],
                "missing": [],
            },
        }
    )

    # Section 15: Expression
    expression: Dict[str, Any] = Field(
        default_factory=lambda: {
            "primary_angle": None,
            "core_hook": None,
            "visual_mechanism_metaphor": None,
            "formats": [],
        }
    )


class IntegrityCheckResult(BaseModel):
    """
    Result of a single integrity check.
    """
    check_name: str
    passed: bool
    notes: Optional[str] = None
    severity: Optional[str] = None  # warning, error


class BeliefFirstMasterCanvas(BaseModel):
    """
    Complete Belief-First Master Canvas (Sections 1-15).

    Combines Research Canvas (1-9) and Belief Canvas (10-15).
    """
    # Research sections (1-9) - populated by Reddit research
    research_canvas: ResearchCanvas = Field(default_factory=ResearchCanvas)

    # Belief sections (10-15) - populated by message + DB
    belief_canvas: BeliefCanvas = Field(default_factory=BeliefCanvas)

    # Integrity checks
    integrity_checks: List[IntegrityCheckResult] = Field(
        default_factory=list,
        description="Results of integrity validation"
    )


class RiskFlag(BaseModel):
    """
    A compliance or messaging risk identified in the canvas.
    """
    type: RiskFlagType
    severity: RiskSeverity
    reason: str
    suggested_fix: str
    affected_fields: List[str] = Field(
        default_factory=list,
        description="Field paths that are affected"
    )


class TraceItem(BaseModel):
    """
    Tracks where each canvas field value came from.

    Essential for audit trail and debugging.
    """
    field_path: str = Field(
        ...,
        description="Dot-path to field, e.g., 'belief_canvas.unique_mechanism.ump.reframed_root_cause'"
    )
    source: str = Field(
        ...,
        description="message, product_db, reddit_research, inferred"
    )
    source_detail: str = Field(
        ...,
        description="Which message, which DB field, which Reddit query"
    )
    evidence_status: EvidenceStatus


class GapReport(BaseModel):
    """
    Report of gaps and missing elements in the canvas.
    """
    research_needed: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Research questions that need answers"
    )
    proof_needed: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Proof types that are missing"
    )


# =============================================================================
# Template Recommendation Models
# =============================================================================


class RecommendationMethodology(str, Enum):
    """Available recommendation methodologies."""
    AI_MATCH = "ai_match"
    PERFORMANCE = "performance"  # Future: based on ad performance data
    DIVERSITY = "diversity"       # Ensure variety in formats


class ScoreBreakdown(BaseModel):
    """Breakdown of recommendation score components."""
    niche_match: float = Field(default=0.0, ge=0.0, le=1.0, description="Industry/niche alignment")
    awareness_match: float = Field(default=0.0, ge=0.0, le=1.0, description="Awareness level fit")
    audience_match: float = Field(default=0.0, ge=0.0, le=1.0, description="Target audience alignment")
    format_fit: float = Field(default=0.0, ge=0.0, le=1.0, description="Format suitability")

    model_config = {"extra": "allow"}  # Allow additional score components


class TemplateRecommendation(BaseModel):
    """A single template recommendation for a product."""
    id: UUID = Field(..., description="Recommendation record ID")
    product_id: UUID = Field(..., description="Product this recommendation is for")
    template_id: UUID = Field(..., description="Recommended template ID")
    offer_variant_id: Optional[UUID] = Field(None, description="Optional offer variant context")

    # Recommendation details
    methodology: RecommendationMethodology = Field(..., description="How this was recommended")
    score: float = Field(..., ge=0.0, le=1.0, description="Overall recommendation score")
    score_breakdown: ScoreBreakdown = Field(default_factory=ScoreBreakdown)
    reasoning: Optional[str] = Field(None, description="AI explanation for recommendation")

    # Usage tracking
    used: bool = Field(default=False, description="Has been used in ad run")
    times_used: int = Field(default=0, ge=0, description="Number of times used")
    last_used_at: Optional[datetime] = Field(None, description="When last used")

    # Lifecycle
    recommended_at: datetime = Field(..., description="When recommendation was created")
    recommended_by: str = Field(default="system", description="Who created recommendation")

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "product_id": "123e4567-e89b-12d3-a456-426614174000",
                "template_id": "789e0123-e89b-12d3-a456-426614174000",
                "methodology": "ai_match",
                "score": 0.85,
                "score_breakdown": {"niche_match": 0.9, "awareness_match": 0.8},
                "reasoning": "Template targets health supplements with awareness level 3...",
                "used": False,
                "recommended_at": "2026-01-19T10:30:00Z"
            }
        }
    }


class TemplateRecommendationCandidate(BaseModel):
    """A candidate template with recommendation score (before saving)."""
    template_id: UUID = Field(..., description="Template UUID")
    template_name: str = Field(..., description="Template display name")
    template_category: str = Field(..., description="Template category (testimonial, quote_card, etc.)")
    storage_path: str = Field(..., description="Supabase storage path for preview")

    # Matching scores
    score: float = Field(..., ge=0.0, le=1.0, description="Overall recommendation score")
    score_breakdown: ScoreBreakdown = Field(..., description="Score component breakdown")
    reasoning: str = Field(..., description="AI explanation for this score")

    # Template metadata for display
    industry_niche: Optional[str] = Field(None, description="Template industry niche")
    awareness_level: Optional[int] = Field(None, ge=1, le=5, description="Awareness level 1-5")
    target_sex: Optional[str] = Field(None, description="Target audience sex")


class GenerateRecommendationsRequest(BaseModel):
    """Request to generate template recommendations."""
    product_id: UUID = Field(..., description="Product to recommend templates for")
    offer_variant_id: Optional[UUID] = Field(None, description="Optional offer variant for context")
    methodology: RecommendationMethodology = Field(
        default=RecommendationMethodology.AI_MATCH,
        description="Recommendation methodology"
    )
    limit: int = Field(default=20, ge=1, le=50, description="Max recommendations to generate")

    @field_validator('methodology')
    @classmethod
    def validate_methodology(cls, v):
        if v == RecommendationMethodology.PERFORMANCE:
            # Performance-based not yet implemented
            raise ValueError("Performance-based recommendations not yet available")
        return v


class GenerateRecommendationsResult(BaseModel):
    """Result of generating recommendations."""
    product_id: UUID = Field(..., description="Product recommendations were generated for")
    product_name: str = Field(..., description="Product display name")
    methodology: RecommendationMethodology = Field(..., description="Methodology used")
    candidates: List[TemplateRecommendationCandidate] = Field(
        ..., description="Ranked list of candidate templates"
    )
    total_templates_analyzed: int = Field(..., ge=0, description="Total templates considered")
    generation_time_ms: int = Field(..., ge=0, description="Time taken in milliseconds")
