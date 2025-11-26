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
from uuid import UUID


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

    @field_validator('benefits', 'key_ingredients', 'reference_image_storage_paths', 'prohibited_claims', 'unique_selling_points', mode='before')
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
    prompt_index: int = Field(ge=1, le=5, description="Index 1-5 for this variation")
    hook: SelectedHook
    instruction_text: str = Field(..., description="Human-readable instructions for image generation")
    spec: Dict[str, Any] = Field(..., description="JSON spec with canvas, product, text_elements")
    full_prompt: str = Field(..., description="Complete prompt sent to Nano Banana API")
    template_reference_path: str = Field(..., description="Storage path to reference ad image")
    product_image_path: str = Field(..., description="Storage path to product image")


class GeneratedAd(BaseModel):
    """Generated ad image with metadata"""
    prompt_index: int = Field(ge=1, le=5)
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
