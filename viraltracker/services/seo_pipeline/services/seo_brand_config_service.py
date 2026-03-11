"""
SEO Brand Config Service — Per-brand content generation configuration.

Manages:
- Content style guide (voice, tone, GOOD/BAD examples)
- Available tags with selection rules
- Image style for AI image generation
- Product mention rules
- Default author, publisher schema
"""

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# Default empty config returned when no brand config exists
_DEFAULT_CONFIG = {
    "content_style_guide": "",
    "available_tags": [],
    "image_style": "",
    "product_mention_rules": "",
    "max_product_mentions": 2,
    "default_author_id": None,
    "schema_publisher": None,
}


class SEOBrandConfigService:
    """CRUD + helpers for per-brand SEO content configuration."""

    def __init__(self, supabase_client=None):
        self._supabase = supabase_client

    @property
    def supabase(self):
        if self._supabase is None:
            from viraltracker.core.database import get_supabase_client
            self._supabase = get_supabase_client()
        return self._supabase

    def get_config(self, brand_id: str) -> Dict[str, Any]:
        """
        Load brand config, returning empty defaults if none exists.

        Args:
            brand_id: Brand UUID

        Returns:
            Config dict (always has all keys, empty defaults if not configured)
        """
        result = (
            self.supabase.table("seo_brand_config")
            .select("*")
            .eq("brand_id", brand_id)
            .limit(1)
            .execute()
        )
        if result.data:
            row = result.data[0]
            # Merge with defaults so callers always get all keys
            config = {**_DEFAULT_CONFIG, **{k: v for k, v in row.items() if v is not None}}
            config["id"] = row.get("id")
            config["brand_id"] = row.get("brand_id")
            return config

        return {**_DEFAULT_CONFIG, "brand_id": brand_id}

    def upsert_config(
        self,
        brand_id: str,
        organization_id: str,
        **fields,
    ) -> Dict[str, Any]:
        """
        Create or update brand config.

        Args:
            brand_id: Brand UUID
            organization_id: Org UUID
            **fields: Config fields to set

        Returns:
            Updated config dict
        """
        # Filter to valid columns only
        valid_keys = {
            "content_style_guide", "available_tags", "image_style",
            "product_mention_rules", "max_product_mentions",
            "default_author_id", "schema_publisher",
        }
        data = {k: v for k, v in fields.items() if k in valid_keys}
        data["brand_id"] = brand_id
        data["organization_id"] = organization_id

        result = (
            self.supabase.table("seo_brand_config")
            .upsert(data, on_conflict="brand_id")
            .execute()
        )

        logger.info(f"Upserted brand config for {brand_id}: {list(data.keys())}")
        return result.data[0] if result.data else self.get_config(brand_id)

    def get_available_tags(self, brand_id: str) -> List[Dict[str, str]]:
        """Get tag list for brand config."""
        config = self.get_config(brand_id)
        return config.get("available_tags") or []

    def seed_yaketypack_config(self, brand_id: str, organization_id: str) -> Dict[str, Any]:
        """Pre-populate brand config with extracted YaketyPack data."""
        return self.upsert_config(
            brand_id=brand_id,
            organization_id=organization_id,
            content_style_guide=(
                "You are Kevin Hinton, co-founder of Yakety Pack and Tru Earth, "
                "a dad focused on gaming-as-connection.\n\n"
                "Brand positioning:\n"
                "- NOT anti-screen — help parents understand what kids love about gaming\n"
                "- Bridge the culture gap between gaming and parenting\n"
                "- Use gaming as a conversation starter, not something to limit\n"
                "- See gaming as a window into kids' world\n\n"
                "Voice:\n"
                "- Dad who learned to connect with kids THROUGH gaming, not around it\n"
                "- Former skeptic of gaming turned advocate\n"
                "- Straight-talker who admits mistakes and shares real stories\n"
                "- Empathetic but not preachy\n"
                "- Uses real anecdotes and specific examples\n\n"
                "GOOD voice examples:\n"
                '"Look, I tried asking my son \'how was Minecraft today?\' for weeks. Got grunts. '
                "Then I asked 'what's the craziest thing that happened in your world this week?' "
                'and he talked for twenty minutes about accidentally flooding his village. '
                'The question mattered."\n\n'
                "BAD voice examples (NEVER write like this):\n"
                '"In today\'s digital landscape, it\'s important to consider the impact of screen '
                'time on family dynamics."\n'
                '"Moreover, research suggests that gaming can have both positive and negative '
                'effects on child development."'
            ),
            product_mention_rules=(
                "Maximum: 2 mentions per article. Natural and story-driven only.\n\n"
                "GOOD examples:\n"
                '- "We created Yakety Pack after realizing kids want to connect — they just need '
                'questions that meet them where they are"\n'
                '- "One card asks \'What game character would you want as a friend?\' — it\'s not '
                "about getting them off screens, it's about understanding what they love\"\n\n"
                "BAD examples (NEVER):\n"
                '- "Transform your relationship with Yakety Pack today!"\n'
                '- "Use Yakety Pack to reduce screen time"\n'
                "- Any salesy, pushy, or CTA-heavy language"
            ),
            available_tags=[
                {"slug": "screens-and-connection", "name": "Screens & Connection",
                 "description": "How to use screens, games, and digital worlds as tools for connection instead of conflict",
                 "selection_rule": "Primary focus is gaming/digital (80%+ of content)."},
                {"slug": "family-communication", "name": "Family Communication",
                 "description": "Questions, rituals, and conversations that help kids feel safe, seen, and heard",
                 "selection_rule": "Catch-all for conversation/dialogue strategies."},
                {"slug": "creativity-coding-future-skills", "name": "Creativity, Coding & Future Skills",
                 "description": "How games and digital play spark creativity, problem-solving, and future-ready skills",
                 "selection_rule": "Skills development angle."},
                {"slug": "youth-sports-and-coaching", "name": "Youth Sports & Coaching",
                 "description": "Lessons from the rink and field about confidence, resilience, and team culture",
                 "selection_rule": "Sports confidence/resilience content."},
                {"slug": "family-life-and-rituals", "name": "Family Life & Rituals",
                 "description": "Simple, repeatable moments that build connection in the middle of real life",
                 "selection_rule": "Routine/ritual-focused content."},
                {"slug": "yakety-pack-stories", "name": "Yakety Pack Stories",
                 "description": "Founder stories, behind-the-scenes, and the moments that shaped Yakety Pack",
                 "selection_rule": "ONLY for founder/brand stories. Not for general content."},
            ],
            image_style=(
                "Shot on iPhone, natural lighting, casual authentic feel, slightly candid, "
                "warm tones, real family moment, not overly staged or perfect, "
                "realistic everyday photography"
            ),
            max_product_mentions=2,
            schema_publisher={"name": "Yakety Pack", "logo_url": "https://yaketypack.com/logo.png"},
        )
