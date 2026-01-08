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
from ..core.config import Config
from pydantic_ai import Agent
import asyncio


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
        logger.info(f"Running Apify with {len(configs)} configs for ASIN {asin}")
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
        missing_id_count = 0

        for review in reviews:
            review_id = review.get("reviewId")
            if not review_id:
                missing_id_count += 1
                continue
            if review_id not in seen_ids:
                seen_ids.add(review_id)
                unique.append(review)

        duplicates = len(reviews) - len(unique) - missing_id_count
        logger.info(f"Deduplication: {len(reviews)} raw → {len(unique)} unique "
                   f"({duplicates} duplicates, {missing_id_count} missing reviewId)")

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

    def _parse_rating(self, rating_value: Any) -> Optional[int]:
        """
        Parse rating from various formats returned by Apify.

        Handles:
        - Integer: 5
        - Float: 5.0
        - String: "5.0 out of 5 stars", "3.0", "5"

        Args:
            rating_value: Raw rating value from Apify

        Returns:
            Integer rating 1-5, or None if unparseable
        """
        if rating_value is None:
            return None

        # Already an int
        if isinstance(rating_value, int):
            return rating_value if 1 <= rating_value <= 5 else None

        # Float
        if isinstance(rating_value, float):
            return int(rating_value) if 1 <= rating_value <= 5 else None

        # String - try to extract number
        if isinstance(rating_value, str):
            # Match patterns like "3.0 out of 5 stars", "5.0", "5"
            match = re.search(r'(\d+(?:\.\d+)?)', rating_value)
            if match:
                try:
                    rating = float(match.group(1))
                    return int(rating) if 1 <= rating <= 5 else None
                except ValueError:
                    pass

        logger.debug(f"Could not parse rating: {rating_value}")
        return None

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

                # Parse rating - can be int, float, or string like "3.0 out of 5 stars"
                rating = self._parse_rating(review.get("rating"))

                records.append({
                    "amazon_product_url_id": str(amazon_url_id),
                    "product_id": str(product_id),
                    "brand_id": str(brand_id),
                    "review_id": review.get("reviewId"),
                    "asin": asin,
                    "rating": rating,
                    "title": review.get("title"),
                    "body": review.get("text"),
                    "author": review.get("author"),
                    "review_date": review_date.isoformat() if review_date else None,
                    "verified_purchase": review.get("verified", False),
                    "helpful_votes": review.get("numberOfHelpful", 0) or 0,
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
        Analyze stored reviews with Claude to extract rich themed persona signals.

        Generates themed clusters with scores and contextual quotes for:
        - Pain Points (life frustrations BEFORE the product)
        - Jobs to Be Done (what they're trying to accomplish)
        - Product Issues (problems WITH this product)
        - Desired Outcomes
        - Buying Objections
        - Desired Features
        - Failed Solutions (past products that didn't work)

        Args:
            product_id: Product UUID
            limit: Maximum reviews to analyze
            delay_between: Delay between API calls

        Returns:
            Analysis results dictionary or None if no reviews
        """
        import json


        # Fetch reviews with all fields needed for rich formatting
        result = self.supabase.table("amazon_reviews").select(
            "rating, title, body, author, verified_purchase, helpful_votes"
        ).eq("product_id", str(product_id)).order(
            "helpful_votes", desc=True
        ).limit(limit).execute()

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

        # Pydantic AI Agent (Creative)
        agent = Agent(
            model=Config.get_model("creative"),
            system_prompt="You are an expert at customer insights. Return ONLY valid JSON."
        )

        try:
            result = await agent.run(
                REVIEW_ANALYSIS_PROMPT.format(
                    reviews_text=reviews_text,
                    review_count=len(reviews)
                )
            )

            # Parse response
            analysis_text = result.output

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
        """Format reviews for Claude prompt with rich context."""
        lines = []
        for i, review in enumerate(reviews[:200], 1):  # Limit to 200 for token efficiency
            rating = review.get("rating", "?")
            title = review.get("title", "").strip()
            body = review.get("body", "").strip()
            author = review.get("author", "Anonymous")
            verified = "✓" if review.get("verified_purchase") else ""
            helpful = review.get("helpful_votes", 0)

            lines.append(f"[Review {i}] ⭐{rating} {verified}")
            if title:
                lines.append(f"Title: {title}")
            if body:
                # Truncate very long reviews
                body_truncated = body[:1500] + "..." if len(body) > 1500 else body
                lines.append(f"Body: {body_truncated}")
            lines.append(f"Author: {author} | Helpful votes: {helpful}")
            lines.append("")

        return "\n".join(lines)

    def _format_author_name(self, author: str) -> str:
        """Format author name as 'First L.' for attribution."""
        if not author or author.lower() in ["anonymous", "a customer", "amazon customer"]:
            return "Verified Buyer"

        # Clean up the name
        author = author.strip()

        # If already short enough, return as-is
        if len(author) <= 15:
            return author

        # Try to extract first name and last initial
        parts = author.split()
        if len(parts) >= 2:
            first = parts[0]
            last_initial = parts[-1][0].upper() + "."
            return f"{first} {last_initial}"

        return author[:15]

    def _save_analysis(
        self,
        product_id: UUID,
        brand_id: UUID,
        reviews_count: int,
        analysis: Dict[str, Any]
    ):
        """Save rich themed review analysis to database.

        Maps analysis structure to database columns (matching competitor format):
        - pain_points stores themes + jobs_to_be_done + product_issues
        - desires stores desired_outcomes themes
        - objections stores buying_objections themes
        - language_patterns stores desired_features themes
        - transformation stores failed_solutions themes
        """
        try:
            # Extract summary stats
            summary = analysis.get("summary", {})
            sentiment = summary.get("sentiment_distribution", {})

            # Map analysis fields to DB columns in competitor-compatible format
            # Note: We store jobs_to_be_done and product_issues inside pain_points JSONB
            record = {
                "product_id": str(product_id),
                "brand_id": str(brand_id),
                "total_reviews_analyzed": reviews_count,
                "sentiment_distribution": sentiment,
                # Store the full structure in each JSONB column
                "pain_points": {
                    "themes": analysis.get("pain_points", []),
                    "jobs_to_be_done": analysis.get("jobs_to_be_done", []),
                    "product_issues": analysis.get("product_issues", [])
                },
                "desires": {"themes": analysis.get("desired_outcomes", [])},
                "objections": {"themes": analysis.get("buying_objections", [])},
                "language_patterns": {"themes": analysis.get("desired_features", [])},
                "transformation": {"themes": analysis.get("failed_solutions", [])},
                "model_used": "claude-sonnet-4-20250514",
                "analyzed_at": datetime.utcnow().isoformat()
            }

            # Delete existing analysis for this product, then insert new one
            self.supabase.table("amazon_review_analysis").delete().eq(
                "product_id", str(product_id)
            ).execute()

            self.supabase.table("amazon_review_analysis").insert(
                record
            ).execute()

            logger.info(f"Saved Amazon analysis for product {product_id}")

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


    # =========================================================================
    # Onboarding Analysis
    # =========================================================================

    def analyze_listing_for_onboarding(
        self,
        amazon_url: str,
        include_reviews: bool = True,
        max_reviews: int = 100,
        timeout: int = 300
    ) -> Dict[str, Any]:
        """
        Full Amazon listing analysis for client onboarding.

        Scrapes product info (title, bullets, images, dimensions) and optionally
        reviews to extract messaging data for pre-populating product and offer
        variant fields.

        Uses axesso_data/amazon-product-details-scraper for product info.

        Args:
            amazon_url: Amazon product URL
            include_reviews: Whether to also scrape and analyze reviews
            max_reviews: Maximum reviews to analyze if include_reviews=True
            timeout: Apify actor timeout in seconds

        Returns:
            Dict with product_info, messaging, review_summary
        """
        result = {
            "success": False,
            "error": None,
            "product_info": {
                "title": "",
                "bullets": [],
                "description": "",
                "dimensions": {},
                "weight": {},
                "images": [],
                "asin": "",
                "price": "",
                "rating": None,
                "review_count": 0
            },
            "messaging": {
                "pain_points": [],
                "desires_goals": [],
                "benefits": [],
                "customer_language": []
            },
            "review_summary": {
                "positive_themes": [],
                "negative_themes": [],
                "common_use_cases": []
            }
        }

        # Parse URL
        asin, domain = self.parse_amazon_url(amazon_url)
        if not asin:
            result["error"] = "Could not extract ASIN from URL"
            return result

        result["product_info"]["asin"] = asin
        logger.info(f"Analyzing Amazon listing for ASIN {asin}")

        # Step 1: Get product details using Axesso actor
        try:
            product_data = self._scrape_product_details(asin, domain, timeout)
            if product_data:
                self._populate_product_info(result["product_info"], product_data)
                self._extract_benefits_from_bullets(result, product_data)
        except Exception as e:
            logger.warning(f"Product details scrape failed: {e}")
            # Continue - we might still get reviews

        # Step 2: Optionally scrape and analyze reviews
        if include_reviews:
            try:
                review_data = self._scrape_reviews_quick(asin, domain, max_reviews)
                if review_data:
                    self._extract_messaging_from_reviews(result, review_data)
            except Exception as e:
                logger.warning(f"Review analysis failed: {e}")

        result["success"] = bool(result["product_info"]["title"])
        if not result["success"] and not result["error"]:
            result["error"] = "Could not retrieve product details from Amazon. The product may be unavailable or the URL may be incorrect."
        return result

    def _scrape_product_details(
        self,
        asin: str,
        domain: str,
        timeout: int
    ) -> Optional[Dict]:
        """Scrape product details using Axesso actor."""
        PRODUCT_DETAILS_ACTOR = "axesso_data/amazon-product-details-scraper"

        try:
            apify_result = self.apify.run_actor(
                actor_id=PRODUCT_DETAILS_ACTOR,
                run_input={
                    "urls": [f"https://www.amazon.{domain}/dp/{asin}"]
                },
                timeout=timeout,
                memory_mbytes=1024
            )

            if apify_result.items:
                return apify_result.items[0]
            return None

        except Exception as e:
            logger.error(f"Product details scrape error: {e}")
            return None

    def _populate_product_info(
        self,
        product_info: Dict,
        data: Dict
    ) -> None:
        """Populate product_info from Axesso product details response."""
        # Title
        product_info["title"] = data.get("productTitle", "") or data.get("title", "")

        # Bullets/features
        bullets = data.get("productFeatures", []) or data.get("featureBullets", [])
        if isinstance(bullets, list):
            product_info["bullets"] = bullets

        # Description
        product_info["description"] = data.get("productDescription", "") or data.get("description", "")

        # Images
        images = data.get("images", []) or data.get("imageUrls", [])
        if isinstance(images, list):
            product_info["images"] = images[:5]  # Limit to 5 images

        # Price
        price = data.get("price") or data.get("currentPrice")
        if price:
            product_info["price"] = str(price)

        # Rating
        rating = data.get("averageRating") or data.get("rating")
        if rating:
            try:
                product_info["rating"] = float(rating)
            except (ValueError, TypeError):
                pass

        # Review count
        review_count = data.get("reviewCount") or data.get("totalReviews")
        if review_count:
            try:
                product_info["review_count"] = int(str(review_count).replace(",", ""))
            except (ValueError, TypeError):
                pass

        # Dimensions (varies by actor response format)
        dimensions = data.get("dimensions") or data.get("productDimensions")
        if dimensions:
            if isinstance(dimensions, dict):
                product_info["dimensions"] = dimensions
            elif isinstance(dimensions, str):
                product_info["dimensions"] = {"raw": dimensions}

        # Weight
        weight = data.get("weight") or data.get("itemWeight")
        if weight:
            if isinstance(weight, dict):
                product_info["weight"] = weight
            elif isinstance(weight, str):
                product_info["weight"] = {"raw": weight}

    def _extract_benefits_from_bullets(
        self,
        result: Dict,
        data: Dict
    ) -> None:
        """Extract benefits from product bullets for messaging."""
        bullets = data.get("productFeatures", []) or data.get("featureBullets", [])
        if not bullets:
            return

        # Clean bullets and add to benefits
        benefits = []
        for bullet in bullets[:7]:  # Limit to 7 bullets
            if isinstance(bullet, str) and bullet.strip():
                # Clean up bullet text
                clean = bullet.strip()
                if len(clean) > 10:  # Skip very short bullets
                    benefits.append(clean)

        result["messaging"]["benefits"] = benefits

    def _scrape_reviews_quick(
        self,
        asin: str,
        domain: str,
        max_reviews: int
    ) -> List[Dict]:
        """Quick review scrape for onboarding (limited configs)."""
        # Use a simplified config set for speed
        configs = [
            # All stars, recent
            {
                "asin": asin,
                "domainCode": domain,
                "maxPages": min(5, max_reviews // 10),
                "sortBy": "recent"
            },
            # Most helpful
            {
                "asin": asin,
                "domainCode": domain,
                "maxPages": 3,
                "sortBy": "helpful"
            }
        ]

        try:
            result = self.apify.run_actor_batch(
                actor_id=AXESSO_ACTOR_ID,
                batch_inputs=configs,
                timeout=300,
                memory_mbytes=1024
            )

            # Deduplicate
            unique = self._deduplicate_reviews(result.items)
            return unique[:max_reviews]

        except Exception as e:
            logger.error(f"Quick review scrape error: {e}")
            return []

    def _extract_messaging_from_reviews(
        self,
        result: Dict,
        reviews: List[Dict]
    ) -> None:
        """Extract messaging data from reviews for onboarding."""
        if not reviews:
            return

        pain_points = []
        desires = []
        positive_themes = []
        negative_themes = []
        use_cases = []
        customer_quotes = []

        for review in reviews[:50]:  # Process top 50 for efficiency
            rating = self._parse_rating(review.get("rating"))
            text = review.get("text", "") or review.get("body", "")
            title = review.get("title", "")

            if not text:
                continue

            # Store as customer language quote
            if len(text) > 50 and len(customer_quotes) < 10:
                customer_quotes.append({
                    "quote": text[:300],
                    "rating": rating,
                    "title": title
                })

            # Classify by rating
            if rating and rating >= 4:
                # Look for positive patterns
                positive_keywords = ["love", "great", "amazing", "excellent", "works", "helps"]
                for kw in positive_keywords:
                    if kw in text.lower():
                        positive_themes.append(kw)
                        break

                # Extract use cases from positive reviews
                if "for" in text.lower() or "to" in text.lower():
                    use_cases.append(text[:100])

            elif rating and rating <= 2:
                # Look for pain points and negative patterns
                negative_keywords = ["didn't work", "waste", "disappointed", "broke", "problem"]
                for kw in negative_keywords:
                    if kw in text.lower():
                        negative_themes.append(kw)
                        break

            # Extract pain patterns (mentions of struggles/problems)
            pain_patterns = ["struggle", "tired of", "frustrated", "couldn't", "didn't help",
                           "problem with", "issues with", "before"]
            for pattern in pain_patterns:
                if pattern in text.lower():
                    # Extract sentence containing pattern
                    sentences = text.split(".")
                    for s in sentences:
                        if pattern in s.lower():
                            pain_points.append(s.strip()[:150])
                            break
                    break

            # Extract desire patterns
            desire_patterns = ["wanted to", "looking for", "needed", "hoping", "tried to",
                             "goal was", "wanted a"]
            for pattern in desire_patterns:
                if pattern in text.lower():
                    sentences = text.split(".")
                    for s in sentences:
                        if pattern in s.lower():
                            desires.append(s.strip()[:150])
                            break
                    break

        # Deduplicate and limit
        result["messaging"]["pain_points"] = list(set(pain_points))[:10]
        result["messaging"]["desires_goals"] = list(set(desires))[:10]
        result["messaging"]["customer_language"] = customer_quotes[:5]
        result["review_summary"]["positive_themes"] = list(set(positive_themes))[:5]
        result["review_summary"]["negative_themes"] = list(set(negative_themes))[:5]
        result["review_summary"]["common_use_cases"] = use_cases[:5]


# Rich themed analysis prompt for extracting persona signals from reviews
# Matches the format used for competitor analysis with 7 categories
REVIEW_ANALYSIS_PROMPT = """You are an expert at extracting deep customer insights from Amazon reviews.

Analyze these {review_count} reviews for the product.

Your task is to identify patterns and extract VERBATIM quotes with context. Organize findings into 7 categories, each with numbered themes ranked by importance (score 1-10).

IMPORTANT DISTINCTIONS:
- "pain_points" = Life frustrations BEFORE using this product (the symptoms driving them to seek a solution)
- "product_issues" = Problems WITH this specific product (complaints, defects, disappointments)
- "jobs_to_be_done" = What customers are trying to accomplish (functional, emotional, social goals)

For each theme:
1. Give it a descriptive name and score (based on frequency and intensity)
2. Include 3-5 direct quotes that exemplify this theme
3. For each quote, add context explaining what it reveals about the customer

REVIEWS:
{reviews_text}

Return a JSON object with this exact structure:
{{
  "pain_points": [
    {{
      "theme": "Life Frustration Before Product",
      "score": 9.0,
      "quotes": [
        {{
          "quote": "Exact verbatim quote describing life pain/frustration BEFORE trying product",
          "author": "Author name if available",
          "rating": 3,
          "context": "What this reveals about their life situation, frustrations, or unmet needs before this product"
        }}
      ]
    }}
  ],
  "jobs_to_be_done": [
    {{
      "theme": "What They're Trying to Accomplish",
      "score": 9.0,
      "quotes": [
        {{
          "quote": "Exact verbatim quote showing what job/goal they hired this product for",
          "author": "Author name",
          "rating": 5,
          "context": "The functional, emotional, or social job they're trying to get done"
        }}
      ]
    }}
  ],
  "product_issues": [
    {{
      "theme": "Specific Problem With This Product",
      "score": 8.0,
      "quotes": [
        {{
          "quote": "Exact verbatim quote about a problem with THIS product",
          "author": "Author name",
          "rating": 2,
          "context": "What product defect, disappointment, or issue this represents"
        }}
      ]
    }}
  ],
  "desired_outcomes": [
    {{
      "theme": "What Customers Want to Achieve",
      "score": 9.0,
      "quotes": [
        {{
          "quote": "Exact verbatim quote",
          "author": "Author name",
          "rating": 5,
          "context": "What this reveals about their ideal end state"
        }}
      ]
    }}
  ],
  "buying_objections": [
    {{
      "theme": "Reasons for Hesitation Before Purchase",
      "score": 8.0,
      "quotes": [
        {{
          "quote": "Exact verbatim quote about pre-purchase concerns or hesitations",
          "author": "Author name",
          "rating": 4,
          "context": "What barrier or concern almost stopped them from buying"
        }}
      ]
    }}
  ],
  "desired_features": [
    {{
      "theme": "Features/Attributes Customers Value",
      "score": 8.5,
      "quotes": [
        {{
          "quote": "Exact verbatim quote",
          "author": "Author name",
          "rating": 5,
          "context": "Why this feature matters to them"
        }}
      ]
    }}
  ],
  "failed_solutions": [
    {{
      "theme": "Past Products/Approaches That Didn't Work",
      "score": 7.5,
      "quotes": [
        {{
          "quote": "Exact verbatim quote mentioning other products they tried",
          "author": "Author name",
          "rating": 4,
          "context": "Why the previous solution failed them"
        }}
      ]
    }}
  ],
  "summary": {{
    "total_reviews_analyzed": {review_count},
    "sentiment_distribution": {{
      "positive": 0,
      "neutral": 0,
      "negative": 0
    }},
    "key_insight": "One sentence summary of the most important finding"
  }}
}}

Guidelines:
- Use EXACT verbatim quotes - do not paraphrase or clean up language
- Include profanity, typos, emphasis (caps, multiple punctuation) as written
- Score themes 1-10 based on how frequently and intensely they appear
- Context should explain the psychological insight, not just summarize the quote
- Aim for 4-6 themes per category, 3-5 quotes per theme
- CRITICAL: Separate "pain_points" (life before product) from "product_issues" (problems with this product)
- Focus on actionable insights that could inform marketing and product positioning

Return ONLY the JSON object, no other text."""
