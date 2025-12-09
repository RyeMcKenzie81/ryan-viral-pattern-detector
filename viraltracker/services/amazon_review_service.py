"""
AmazonReviewService - Service for scraping and analyzing Amazon reviews.

Uses the Axesso Amazon Review Scraper on Apify with a multi-layer strategy
to capture 80%+ of reviews for any product (~1,300+ from 1,600 total).

Strategy:
1. Star-level sweep (6 configs): All stars + each individual star rating
2. Keyword sweep (15+ configs): Universal positive/negative/experience keywords
3. Helpful-sort sweep (3 configs): Most helpful reviews by star rating

All results are deduplicated by reviewId and stored in the database.

Part of the Service Layer - contains business logic, no UI or agent code.
"""

import logging
import re
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from uuid import UUID
from dataclasses import dataclass

from ..core.database import get_supabase_client
from .apify_service import ApifyService

logger = logging.getLogger(__name__)


# Apify actor for Amazon reviews
AXESSO_ACTOR_ID = "axesso_data/amazon-reviews-scraper"

# Universal keywords that appear across all product categories
POSITIVE_KEYWORDS = [
    "great", "good", "love", "amazing", "excellent",
    "perfect", "works", "helpful", "happy", "recommend"
]
NEGATIVE_KEYWORDS = [
    "bad", "terrible", "awful", "broke", "waste",
    "refund", "disappointed"
]
EXPERIENCE_KEYWORDS = [
    "quality", "price", "value", "smell", "taste"
]

# Star filter values for Axesso actor
STAR_FILTERS = ["five_star", "four_star", "three_star", "two_star", "one_star"]


@dataclass
class ScrapeResult:
    """Result from scraping Amazon reviews."""
    product_id: UUID
    asin: str
    raw_reviews_count: int
    unique_reviews_count: int
    reviews_saved: int
    cost_estimate: float
    errors: List[str]


@dataclass
class AnalysisResult:
    """Result from analyzing Amazon reviews."""
    product_id: UUID
    reviews_analyzed: int
    pain_points: Dict[str, List[str]]
    desires: Dict[str, List[str]]
    language_patterns: Dict[str, List[str]]
    top_quotes: Dict[str, List[str]]


class AmazonReviewService:
    """
    Service for scraping and analyzing Amazon reviews.

    Uses Axesso Amazon Review Scraper on Apify with a multi-layer
    scraping strategy to maximize review coverage.
    """

    def __init__(self, apify_service: Optional[ApifyService] = None):
        """
        Initialize AmazonReviewService.

        Args:
            apify_service: Optional ApifyService instance. Creates one if not provided.
        """
        self.apify = apify_service or ApifyService()
        self.supabase = get_supabase_client()

    # =========================================================================
    # URL Parsing
    # =========================================================================

    def extract_asin_from_url(self, url: str) -> Optional[str]:
        """
        Extract ASIN from an Amazon product URL.

        Handles various URL formats:
        - https://www.amazon.com/dp/B0DJWSV1J3
        - https://www.amazon.com/gp/product/B0DJWSV1J3
        - https://www.amazon.com/Product-Name/dp/B0DJWSV1J3/
        - https://amazon.com/dp/B0DJWSV1J3?ref=...

        Args:
            url: Amazon product URL

        Returns:
            ASIN string or None if not found
        """
        # ASIN pattern: 10 alphanumeric characters starting with B0
        patterns = [
            r'/dp/([A-Z0-9]{10})',
            r'/gp/product/([A-Z0-9]{10})',
            r'/product/([A-Z0-9]{10})',
            r'/ASIN/([A-Z0-9]{10})',
        ]

        for pattern in patterns:
            match = re.search(pattern, url, re.IGNORECASE)
            if match:
                return match.group(1).upper()

        return None

    def extract_domain_from_url(self, url: str) -> str:
        """
        Extract Amazon domain code from URL.

        Args:
            url: Amazon URL

        Returns:
            Domain code (e.g., "com", "ca", "co.uk")
        """
        # Common Amazon domains
        domain_patterns = {
            r'amazon\.com': 'com',
            r'amazon\.ca': 'ca',
            r'amazon\.co\.uk': 'co.uk',
            r'amazon\.de': 'de',
            r'amazon\.fr': 'fr',
            r'amazon\.es': 'es',
            r'amazon\.it': 'it',
            r'amazon\.co\.jp': 'co.jp',
            r'amazon\.com\.au': 'com.au',
            r'amazon\.com\.mx': 'com.mx',
            r'amazon\.in': 'in',
        }

        for pattern, domain_code in domain_patterns.items():
            if re.search(pattern, url, re.IGNORECASE):
                return domain_code

        # Default to .com
        return 'com'

    def parse_amazon_url(self, url: str) -> Tuple[Optional[str], str]:
        """
        Parse Amazon URL to extract ASIN and domain.

        Args:
            url: Amazon product URL

        Returns:
            Tuple of (asin, domain_code)
        """
        asin = self.extract_asin_from_url(url)
        domain = self.extract_domain_from_url(url)
        return asin, domain

    # =========================================================================
    # Config Building
    # =========================================================================

    def build_scrape_configs(
        self,
        asin: str,
        domain: str = "com",
        include_keywords: bool = True,
        include_helpful: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Build the full set of Apify actor configs for maximum review coverage.

        Default generates 31 configs:
        - 6 star-level sweeps (recent sort)
        - 15 positive/negative/experience keyword sweeps
        - 3 helpful-sort sweeps
        - 7 additional negative keywords

        Args:
            asin: Amazon product ASIN
            domain: Amazon domain code (e.g., "com", "ca")
            include_keywords: Include keyword filter configs
            include_helpful: Include helpful-sort configs

        Returns:
            List of config dictionaries for Axesso actor
        """
        configs = []

        # Base config template
        base = {
            "asin": asin,
            "domainCode": domain,
            "maxPages": 10,
            "reviewerType": "all_reviews",
            "mediaType": "all_contents",
            "formatType": "current_format"
        }

        # Layer 1: Star-level sweep (recent sort)
        # All stars, no filter
        configs.append({**base, "sortBy": "recent"})

        # Each star rating
        for star in STAR_FILTERS:
            configs.append({**base, "sortBy": "recent", "filterByStar": star})

        if include_keywords:
            # Layer 2: Keyword sweeps (recent sort)
            all_keywords = POSITIVE_KEYWORDS + NEGATIVE_KEYWORDS + EXPERIENCE_KEYWORDS
            for keyword in all_keywords:
                configs.append({
                    **base,
                    "sortBy": "recent",
                    "filterByKeyword": keyword
                })

        if include_helpful:
            # Layer 3: Helpful-sort sweep
            configs.append({**base, "sortBy": "helpful"})
            configs.append({**base, "sortBy": "helpful", "filterByStar": "five_star"})
            configs.append({**base, "sortBy": "helpful", "filterByStar": "one_star"})

        logger.info(f"Built {len(configs)} scrape configs for ASIN {asin}")
        return configs

    # =========================================================================
    # Scraping
    # =========================================================================

    def scrape_reviews_for_product(
        self,
        product_id: UUID,
        amazon_url: str,
        include_keywords: bool = True,
        include_helpful: bool = True,
        timeout: int = 900
    ) -> ScrapeResult:
        """
        Scrape Amazon reviews for a product.

        Args:
            product_id: Product UUID in database
            amazon_url: Amazon product URL
            include_keywords: Include keyword filter configs
            include_helpful: Include helpful-sort configs
            timeout: Apify run timeout in seconds

        Returns:
            ScrapeResult with counts and status
        """
        errors = []

        # Parse URL
        asin, domain = self.parse_amazon_url(amazon_url)
        if not asin:
            return ScrapeResult(
                product_id=product_id,
                asin="",
                raw_reviews_count=0,
                unique_reviews_count=0,
                reviews_saved=0,
                cost_estimate=0.0,
                errors=["Could not extract ASIN from URL"]
            )

        logger.info(f"Scraping reviews for ASIN {asin} (domain: {domain})")

        # Get or create amazon_product_url record
        amazon_url_id, brand_id = self._get_or_create_amazon_url(
            product_id, amazon_url, asin, domain
        )

        # Build configs
        configs = self.build_scrape_configs(
            asin=asin,
            domain=domain,
            include_keywords=include_keywords,
            include_helpful=include_helpful
        )

        # Run Apify actor with batch input
        try:
            result = self.apify.run_actor_batch(
                actor_id=AXESSO_ACTOR_ID,
                batch_inputs=configs,
                timeout=timeout,
                memory_mbytes=2048
            )
            raw_reviews = result.items
            raw_count = len(raw_reviews)
            logger.info(f"Got {raw_count} raw reviews from Apify")

        except Exception as e:
            logger.error(f"Apify scrape failed: {e}")
            return ScrapeResult(
                product_id=product_id,
                asin=asin,
                raw_reviews_count=0,
                unique_reviews_count=0,
                reviews_saved=0,
                cost_estimate=0.0,
                errors=[str(e)]
            )

        # Deduplicate by reviewId
        unique_reviews = self._deduplicate_reviews(raw_reviews)
        unique_count = len(unique_reviews)
        logger.info(f"Deduplicated to {unique_count} unique reviews")

        # Save to database
        saved_count = self._save_reviews(
            reviews=unique_reviews,
            amazon_url_id=amazon_url_id,
            product_id=product_id,
            brand_id=brand_id,
            asin=asin
        )

        # Update amazon_product_urls record
        self._update_scrape_stats(
            amazon_url_id=amazon_url_id,
            reviews_count=saved_count,
            cost_estimate=self.apify.estimate_cost(raw_count)
        )

        return ScrapeResult(
            product_id=product_id,
            asin=asin,
            raw_reviews_count=raw_count,
            unique_reviews_count=unique_count,
            reviews_saved=saved_count,
            cost_estimate=self.apify.estimate_cost(raw_count),
            errors=errors
        )

    def _deduplicate_reviews(self, reviews: List[Dict]) -> List[Dict]:
        """
        Deduplicate reviews by reviewId.

        Args:
            reviews: List of raw review dictionaries

        Returns:
            List of unique review dictionaries
        """
        seen_ids = set()
        unique = []

        for review in reviews:
            review_id = review.get("reviewId")
            if review_id and review_id not in seen_ids:
                seen_ids.add(review_id)
                unique.append(review)

        return unique

    def _get_or_create_amazon_url(
        self,
        product_id: UUID,
        amazon_url: str,
        asin: str,
        domain: str
    ) -> Tuple[UUID, UUID]:
        """
        Get or create amazon_product_urls record.

        Returns:
            Tuple of (amazon_url_id, brand_id)
        """
        # Get brand_id from product
        product = self.supabase.table("products").select(
            "brand_id"
        ).eq("id", str(product_id)).single().execute()

        brand_id = product.data["brand_id"]

        # Check if URL exists
        existing = self.supabase.table("amazon_product_urls").select(
            "id"
        ).eq("product_id", str(product_id)).eq("asin", asin).execute()

        if existing.data:
            return UUID(existing.data[0]["id"]), UUID(brand_id)

        # Create new record
        result = self.supabase.table("amazon_product_urls").insert({
            "product_id": str(product_id),
            "brand_id": brand_id,
            "amazon_url": amazon_url,
            "asin": asin,
            "domain_code": domain
        }).execute()

        return UUID(result.data[0]["id"]), UUID(brand_id)

    def _save_reviews(
        self,
        reviews: List[Dict],
        amazon_url_id: UUID,
        product_id: UUID,
        brand_id: UUID,
        asin: str
    ) -> int:
        """
        Save reviews to database.

        Args:
            reviews: List of review dictionaries from Apify
            amazon_url_id: UUID of amazon_product_urls record
            product_id: Product UUID
            brand_id: Brand UUID
            asin: Amazon product ASIN

        Returns:
            Number of reviews saved
        """
        if not reviews:
            return 0

        saved_count = 0
        batch_size = 100

        for i in range(0, len(reviews), batch_size):
            batch = reviews[i:i + batch_size]
            records = []

            for review in batch:
                # Parse date
                review_date = None
                date_str = review.get("date")
                if date_str:
                    try:
                        # Axesso returns dates like "2024-01-15"
                        review_date = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
                    except (ValueError, TypeError):
                        pass

                records.append({
                    "amazon_product_url_id": str(amazon_url_id),
                    "product_id": str(product_id),
                    "brand_id": str(brand_id),
                    "review_id": review.get("reviewId"),
                    "asin": asin,
                    "rating": review.get("rating"),
                    "title": review.get("title"),
                    "body": review.get("text"),
                    "author": review.get("author"),
                    "review_date": review_date.isoformat() if review_date else None,
                    "verified_purchase": review.get("verified", False),
                    "helpful_votes": review.get("numberOfHelpful", 0),
                })

            try:
                result = self.supabase.table("amazon_reviews").upsert(
                    records,
                    on_conflict="review_id,asin"
                ).execute()
                saved_count += len(result.data)
            except Exception as e:
                logger.error(f"Error saving review batch: {e}")

        logger.info(f"Saved {saved_count} reviews to database")
        return saved_count

    def _update_scrape_stats(
        self,
        amazon_url_id: UUID,
        reviews_count: int,
        cost_estimate: float
    ):
        """Update amazon_product_urls with scrape statistics."""
        try:
            self.supabase.table("amazon_product_urls").update({
                "last_scraped_at": datetime.utcnow().isoformat(),
                "total_reviews_scraped": reviews_count,
                "scrape_cost_estimate": cost_estimate
            }).eq("id", str(amazon_url_id)).execute()
        except Exception as e:
            logger.error(f"Error updating scrape stats: {e}")

    # =========================================================================
    # Analysis
    # =========================================================================

    async def analyze_reviews_for_product(
        self,
        product_id: UUID,
        limit: int = 500,
        delay_between: float = 2.0
    ) -> Optional[Dict[str, Any]]:
        """
        Analyze stored reviews with Claude to extract persona signals.

        Args:
            product_id: Product UUID
            limit: Maximum reviews to analyze
            delay_between: Delay between API calls

        Returns:
            Analysis results dictionary or None if no reviews
        """
        import asyncio
        from anthropic import Anthropic

        # Fetch reviews
        result = self.supabase.table("amazon_reviews").select(
            "rating, title, body"
        ).eq("product_id", str(product_id)).limit(limit).execute()

        if not result.data:
            logger.info(f"No reviews found for product {product_id}")
            return None

        reviews = result.data
        logger.info(f"Analyzing {len(reviews)} reviews for product {product_id}")

        # Format reviews for prompt
        reviews_text = self._format_reviews_for_prompt(reviews)

        # Get brand_id
        product = self.supabase.table("products").select(
            "brand_id"
        ).eq("id", str(product_id)).single().execute()
        brand_id = product.data["brand_id"]

        # Call Claude for analysis
        client = Anthropic()

        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4096,
                messages=[{
                    "role": "user",
                    "content": REVIEW_ANALYSIS_PROMPT.format(reviews_text=reviews_text)
                }]
            )

            # Parse response
            import json
            analysis_text = response.content[0].text

            # Extract JSON from response
            json_match = re.search(r'\{[\s\S]*\}', analysis_text)
            if json_match:
                analysis = json.loads(json_match.group())
            else:
                logger.error("Could not parse analysis JSON")
                return None

            # Save analysis to database
            self._save_analysis(
                product_id=product_id,
                brand_id=UUID(brand_id),
                reviews_count=len(reviews),
                analysis=analysis
            )

            return analysis

        except Exception as e:
            logger.error(f"Error analyzing reviews: {e}")
            return None

    def _format_reviews_for_prompt(self, reviews: List[Dict]) -> str:
        """Format reviews for Claude prompt."""
        lines = []
        for review in reviews:
            rating = review.get("rating", "?")
            title = review.get("title", "No title")
            body = review.get("body", "No content")
            # Truncate long reviews
            if len(body) > 500:
                body = body[:500] + "..."
            lines.append(f"[{rating}★] {title}\n{body}\n")

        return "\n---\n".join(lines)

    def _save_analysis(
        self,
        product_id: UUID,
        brand_id: UUID,
        reviews_count: int,
        analysis: Dict[str, Any]
    ):
        """Save review analysis to database."""
        try:
            # Calculate sentiment distribution from analysis
            sentiment_dist = analysis.get("sentiment_summary", {})

            self.supabase.table("amazon_review_analysis").upsert({
                "product_id": str(product_id),
                "brand_id": str(brand_id),
                "total_reviews_analyzed": reviews_count,
                "sentiment_distribution": sentiment_dist,
                "pain_points": analysis.get("pain_points"),
                "desires": analysis.get("desires"),
                "language_patterns": analysis.get("language_patterns"),
                "objections": analysis.get("objections"),
                "purchase_triggers": analysis.get("purchase_triggers"),
                "top_positive_quotes": analysis.get("top_quotes", {}).get("positive", []),
                "top_negative_quotes": analysis.get("top_quotes", {}).get("negative", []),
                "transformation_quotes": analysis.get("top_quotes", {}).get("transformation", []),
                "model_used": "claude-sonnet-4-20250514",
                "analyzed_at": datetime.utcnow().isoformat()
            }, on_conflict="product_id").execute()

            logger.info(f"Saved review analysis for product {product_id}")

        except Exception as e:
            logger.error(f"Error saving review analysis: {e}")

    # =========================================================================
    # Stats & Queries
    # =========================================================================

    def get_review_stats(self, product_id: UUID) -> Dict[str, Any]:
        """
        Get review statistics for a product.

        Args:
            product_id: Product UUID

        Returns:
            Dict with review counts and analysis status
        """
        # Get amazon URL info
        url_result = self.supabase.table("amazon_product_urls").select(
            "id, asin, last_scraped_at, total_reviews_scraped, scrape_cost_estimate"
        ).eq("product_id", str(product_id)).execute()

        # Get review count
        review_result = self.supabase.table("amazon_reviews").select(
            "id", count="exact"
        ).eq("product_id", str(product_id)).execute()

        # Check if analysis exists
        analysis_result = self.supabase.table("amazon_review_analysis").select(
            "analyzed_at, total_reviews_analyzed"
        ).eq("product_id", str(product_id)).execute()

        url_data = url_result.data[0] if url_result.data else {}
        analysis_data = analysis_result.data[0] if analysis_result.data else {}

        return {
            "has_amazon_url": bool(url_result.data),
            "asin": url_data.get("asin"),
            "reviews_scraped": url_data.get("total_reviews_scraped", 0),
            "reviews_in_db": review_result.count or 0,
            "last_scraped": url_data.get("last_scraped_at"),
            "cost_estimate": url_data.get("scrape_cost_estimate", 0),
            "has_analysis": bool(analysis_result.data),
            "analyzed_at": analysis_data.get("analyzed_at"),
            "reviews_analyzed": analysis_data.get("total_reviews_analyzed", 0)
        }

    def get_amazon_urls_for_brand(self, brand_id: UUID) -> List[Dict[str, Any]]:
        """Get all Amazon product URLs for a brand."""
        result = self.supabase.table("amazon_product_urls").select(
            "*, products(name)"
        ).eq("brand_id", str(brand_id)).execute()

        return result.data or []

    def get_analysis_for_product(self, product_id: UUID) -> Optional[Dict[str, Any]]:
        """Get the review analysis for a product."""
        result = self.supabase.table("amazon_review_analysis").select(
            "*"
        ).eq("product_id", str(product_id)).execute()

        return result.data[0] if result.data else None


# Analysis prompt for extracting persona signals from reviews
REVIEW_ANALYSIS_PROMPT = """Analyze these Amazon reviews to extract customer insights for building advertising personas.

REVIEWS:
{reviews_text}

Extract the following and return as JSON:

{{
    "pain_points": {{
        "emotional": ["Exact phrases about feelings/frustrations - use their words"],
        "functional": ["Exact phrases about product issues - use their words"],
        "social": ["Exact phrases about embarrassment/judgment - use their words"]
    }},
    "desires": {{
        "emotional": ["What they hoped to feel - use their words"],
        "functional": ["What they wanted the product to do - use their words"],
        "social": ["How they wanted to be perceived - use their words"]
    }},
    "language_patterns": {{
        "positive_phrases": ["Exact phrases customers use when happy"],
        "negative_phrases": ["Exact phrases customers use when upset"],
        "descriptive_words": ["Common adjectives/adverbs they use"]
    }},
    "objections": [
        {{"objection": "The specific concern", "frequency": "common/occasional/rare"}}
    ],
    "purchase_triggers": [
        "What made them finally decide to buy"
    ],
    "transformation_language": {{
        "before": ["How they describe their situation before the product"],
        "after": ["How they describe their situation after the product"]
    }},
    "top_quotes": {{
        "positive": ["5 best verbatim positive quotes for ad copy"],
        "negative": ["5 most important complaints to address"],
        "transformation": ["5 best before/after transformation quotes"]
    }},
    "sentiment_summary": {{
        "overall": "positive/mixed/negative",
        "common_praise": ["Top 3 things people love"],
        "common_complaints": ["Top 3 things people dislike"]
    }}
}}

CRITICAL INSTRUCTIONS:
1. Use EXACT customer language - do not paraphrase
2. These phrases will be used directly in advertising copy
3. Focus on emotional and authentic language
4. Capture the specific words customers use to describe their problems and desires

Return ONLY valid JSON, no other text."""
