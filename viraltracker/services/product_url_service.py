"""
ProductURLService - URL-to-product mapping for ad identification.

This service handles:
- Managing product landing page URLs and patterns
- Matching ad URLs to products
- Managing the URL review queue for unmatched URLs
- Bulk matching operations for ad libraries

Part of the Product Isolation system (Sprint 1).
"""

import logging
import re
from typing import List, Dict, Optional, Tuple, Any
from uuid import UUID
from datetime import datetime
from urllib.parse import urlparse, urlunparse, parse_qs

from supabase import Client
from ..core.database import get_supabase_client

logger = logging.getLogger(__name__)


class ProductURLService:
    """
    Service for URL-based product identification.

    Manages the mapping between landing page URLs and products,
    enabling product-level isolation of ad insights and personas.
    """

    def __init__(self, supabase: Optional[Client] = None):
        """
        Initialize ProductURLService.

        Args:
            supabase: Supabase client (optional, will create if not provided)
        """
        self.supabase = supabase or get_supabase_client()

    # ============================================================
    # Product Management
    # ============================================================

    def create_product(
        self,
        brand_id: UUID,
        name: str,
        description: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a new product for a brand.

        Args:
            brand_id: Brand UUID
            name: Product name
            description: Optional product description

        Returns:
            Created product record
        """
        record = {
            "brand_id": str(brand_id),
            "name": name,
            "description": description
        }

        result = self.supabase.table("products").insert(record).execute()

        if result.data:
            logger.info(f"Created product '{name}' for brand {brand_id}")
            return result.data[0]
        else:
            raise ValueError(f"Failed to create product: {name}")

    # ============================================================
    # Product URL Management
    # ============================================================

    def add_product_url(
        self,
        product_id: UUID,
        url_pattern: str,
        match_type: str = 'contains',
        is_primary: bool = False,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Add a URL pattern for a product.

        Args:
            product_id: Product UUID
            url_pattern: URL or pattern to match
            match_type: How to match - 'exact', 'prefix', 'contains', 'regex'
            is_primary: Whether this is the primary landing page
            notes: Optional notes about this URL

        Returns:
            Created product_url record
        """
        # Normalize the URL pattern
        normalized = self._normalize_url(url_pattern)

        record = {
            "product_id": str(product_id),
            "url_pattern": normalized,
            "match_type": match_type,
            "is_primary": is_primary,
            "notes": notes
        }

        result = self.supabase.table("product_urls").upsert(
            record,
            on_conflict="product_id,url_pattern"
        ).execute()

        logger.info(f"Added URL pattern for product {product_id}: {normalized}")
        return result.data[0] if result.data else {}

    def get_product_urls(self, product_id: UUID) -> List[Dict[str, Any]]:
        """
        Get all URL patterns for a product.

        Args:
            product_id: Product UUID

        Returns:
            List of product_url records
        """
        result = self.supabase.table("product_urls")\
            .select("*")\
            .eq("product_id", str(product_id))\
            .execute()
        return result.data or []

    def get_all_product_urls_for_brand(self, brand_id: UUID) -> List[Dict[str, Any]]:
        """
        Get all URL patterns for all products of a brand.

        Args:
            brand_id: Brand UUID

        Returns:
            List of product_url records with product info
        """
        result = self.supabase.table("product_urls")\
            .select("*, products!inner(id, name, brand_id)")\
            .eq("products.brand_id", str(brand_id))\
            .execute()
        return result.data or []

    def delete_product_url(self, url_id: UUID) -> bool:
        """
        Delete a product URL pattern.

        Args:
            url_id: Product URL record UUID

        Returns:
            True if deleted
        """
        self.supabase.table("product_urls")\
            .delete()\
            .eq("id", str(url_id))\
            .execute()
        logger.info(f"Deleted product URL: {url_id}")
        return True

    # ============================================================
    # URL Matching
    # ============================================================

    def match_url_to_product(
        self,
        url: str,
        brand_id: UUID
    ) -> Optional[Tuple[UUID, float, str]]:
        """
        Match a URL to a product using configured patterns.

        Args:
            url: URL to match
            brand_id: Brand UUID (to scope the search)

        Returns:
            Tuple of (product_id, confidence, match_type) or None if no match
        """
        normalized = self._normalize_url(url)

        # Get all URL patterns for this brand
        patterns = self.get_all_product_urls_for_brand(brand_id)

        best_match = None
        best_confidence = 0.0

        for pattern in patterns:
            confidence = self._check_pattern_match(
                normalized,
                pattern['url_pattern'],
                pattern['match_type']
            )

            if confidence > best_confidence:
                best_confidence = confidence
                best_match = (
                    UUID(pattern['product_id']),
                    confidence,
                    pattern['match_type']
                )

        return best_match

    def _check_pattern_match(
        self,
        url: str,
        pattern: str,
        match_type: str
    ) -> float:
        """
        Check if a URL matches a pattern.

        Args:
            url: Normalized URL to check
            pattern: Pattern to match against
            match_type: Type of matching to use

        Returns:
            Confidence score (0.0-1.0)
        """
        url_lower = url.lower()
        pattern_lower = pattern.lower()

        if match_type == 'exact':
            return 1.0 if url_lower == pattern_lower else 0.0

        elif match_type == 'prefix':
            return 0.95 if url_lower.startswith(pattern_lower) else 0.0

        elif match_type == 'contains':
            if pattern_lower in url_lower:
                # Higher confidence for longer pattern matches
                ratio = len(pattern_lower) / len(url_lower)
                return min(0.9, 0.5 + ratio * 0.4)
            return 0.0

        elif match_type == 'regex':
            try:
                if re.search(pattern, url, re.IGNORECASE):
                    return 0.85
            except re.error:
                logger.warning(f"Invalid regex pattern: {pattern}")
            return 0.0

        return 0.0

    def _normalize_url(self, url: str) -> str:
        """
        Normalize a URL for consistent matching.

        Removes:
        - Protocol (http/https)
        - www. prefix
        - Trailing slashes
        - Common tracking parameters

        Args:
            url: URL to normalize

        Returns:
            Normalized URL string
        """
        if not url:
            return ""

        # Parse the URL
        parsed = urlparse(url.lower())

        # Remove www. prefix
        netloc = parsed.netloc
        if netloc.startswith('www.'):
            netloc = netloc[4:]

        # Remove tracking parameters
        tracking_params = {'utm_source', 'utm_medium', 'utm_campaign', 'utm_content',
                         'utm_term', 'fbclid', 'gclid', 'ref', 'source'}

        if parsed.query:
            params = parse_qs(parsed.query)
            filtered_params = {k: v for k, v in params.items()
                            if k.lower() not in tracking_params}
            query = '&'.join(f"{k}={v[0]}" for k, v in filtered_params.items())
        else:
            query = ''

        # Reconstruct without protocol
        path = parsed.path.rstrip('/')

        if query:
            return f"{netloc}{path}?{query}"
        else:
            return f"{netloc}{path}"

    # ============================================================
    # Bulk Operations
    # ============================================================

    def extract_url_from_ad(self, ad: Dict[str, Any]) -> Optional[str]:
        """
        Extract the landing page URL from a Facebook ad's snapshot.

        Args:
            ad: Facebook ad record

        Returns:
            Landing page URL or None
        """
        import json

        snapshot = ad.get('snapshot', {})

        # Handle snapshot as string
        if isinstance(snapshot, str):
            try:
                snapshot = json.loads(snapshot)
            except json.JSONDecodeError:
                return None

        if not snapshot or not isinstance(snapshot, dict):
            return None

        # Try different fields where URL might be stored
        url = None

        # Direct link_url field
        if 'link_url' in snapshot:
            url = snapshot['link_url']

        # Check cards for carousel ads
        elif 'cards' in snapshot and snapshot['cards']:
            for card in snapshot['cards']:
                if 'link_url' in card:
                    url = card['link_url']
                    break

        # Check cta_link
        elif 'cta_link' in snapshot:
            url = snapshot['cta_link']

        return url

    def bulk_match_ads(
        self,
        brand_id: UUID,
        limit: int = 500,
        only_unmatched: bool = True
    ) -> Dict[str, int]:
        """
        Match ads to products in bulk.

        Args:
            brand_id: Brand UUID
            limit: Maximum ads to process
            only_unmatched: Only process ads without product_id

        Returns:
            Stats dict with matched, unmatched, failed counts
        """
        # Fetch ad IDs linked to this brand via junction table
        link_result = self.supabase.table("brand_facebook_ads")\
            .select("ad_id")\
            .eq("brand_id", str(brand_id))\
            .limit(limit)\
            .execute()

        ad_ids = [r['ad_id'] for r in (link_result.data or [])]

        if not ad_ids:
            return {"matched": 0, "unmatched": 0, "failed": 0, "total": 0}

        # Fetch the actual ad data
        query = self.supabase.table("facebook_ads")\
            .select("id, snapshot")\
            .in_("id", ad_ids)

        if only_unmatched:
            query = query.is_("product_id", "null")

        result = query.execute()
        ads = result.data or []

        stats = {"matched": 0, "unmatched": 0, "failed": 0, "total": len(ads)}
        unmatched_urls = {}  # Track unique unmatched URLs

        for ad in ads:
            try:
                url = self.extract_url_from_ad(ad)

                if not url:
                    stats["failed"] += 1
                    continue

                match = self.match_url_to_product(url, brand_id)

                if match:
                    product_id, confidence, method = match

                    # Update the ad with product info
                    self.supabase.table("facebook_ads")\
                        .update({
                            "product_id": str(product_id),
                            "product_match_confidence": confidence,
                            "product_match_method": "url",
                            "product_matched_at": datetime.utcnow().isoformat()
                        })\
                        .eq("id", ad['id'])\
                        .execute()

                    stats["matched"] += 1
                else:
                    # Track unmatched URL
                    normalized = self._normalize_url(url)
                    if normalized not in unmatched_urls:
                        unmatched_urls[normalized] = {
                            "url": url,
                            "ad_ids": []
                        }
                    if len(unmatched_urls[normalized]["ad_ids"]) < 5:
                        unmatched_urls[normalized]["ad_ids"].append(ad['id'])

                    stats["unmatched"] += 1

            except Exception as e:
                logger.error(f"Error processing ad {ad.get('id')}: {e}")
                stats["failed"] += 1

        # Add unmatched URLs to review queue
        for normalized, data in unmatched_urls.items():
            self._add_to_review_queue(
                brand_id=brand_id,
                url=data["url"],
                normalized_url=normalized,
                ad_ids=data["ad_ids"]
            )

        logger.info(f"Bulk match complete for brand {brand_id}: {stats}")
        return stats

    # ============================================================
    # URL Review Queue
    # ============================================================

    def _add_to_review_queue(
        self,
        brand_id: UUID,
        url: str,
        normalized_url: str,
        ad_ids: List[str]
    ) -> None:
        """
        Add or update an unmatched URL in the review queue.

        Args:
            brand_id: Brand UUID
            url: Original URL
            normalized_url: Normalized URL for deduplication
            ad_ids: Sample ad IDs using this URL
        """
        # Check if already exists
        existing = self.supabase.table("url_review_queue")\
            .select("id, occurrence_count, sample_ad_ids")\
            .eq("brand_id", str(brand_id))\
            .eq("normalized_url", normalized_url)\
            .execute()

        if existing.data:
            # Update existing
            record = existing.data[0]
            new_count = record['occurrence_count'] + 1
            existing_ids = record['sample_ad_ids'] or []

            # Merge ad IDs (keep max 5)
            merged_ids = list(set(existing_ids + ad_ids))[:5]

            self.supabase.table("url_review_queue")\
                .update({
                    "occurrence_count": new_count,
                    "sample_ad_ids": merged_ids
                })\
                .eq("id", record['id'])\
                .execute()
        else:
            # Insert new
            self.supabase.table("url_review_queue")\
                .insert({
                    "brand_id": str(brand_id),
                    "url": url,
                    "normalized_url": normalized_url,
                    "sample_ad_ids": ad_ids,
                    "occurrence_count": 1
                })\
                .execute()

    def get_review_queue(
        self,
        brand_id: UUID,
        status: str = 'pending',
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Get URLs in the review queue.

        Args:
            brand_id: Brand UUID
            status: Filter by status ('pending', 'assigned', 'new_product', 'ignored')
            limit: Maximum results

        Returns:
            List of review queue records
        """
        result = self.supabase.table("url_review_queue")\
            .select("*")\
            .eq("brand_id", str(brand_id))\
            .eq("status", status)\
            .order("occurrence_count", desc=True)\
            .limit(limit)\
            .execute()
        return result.data or []

    def assign_url_to_product(
        self,
        queue_id: UUID,
        product_id: UUID,
        add_as_pattern: bool = True,
        match_type: str = 'contains'
    ) -> Dict[str, Any]:
        """
        Assign a queued URL to a product.

        Args:
            queue_id: Review queue record UUID
            product_id: Product to assign to
            add_as_pattern: Also add URL as a product pattern
            match_type: Match type if adding as pattern

        Returns:
            Updated review queue record
        """
        # Get the queue record
        queue_result = self.supabase.table("url_review_queue")\
            .select("*")\
            .eq("id", str(queue_id))\
            .execute()

        if not queue_result.data:
            raise ValueError(f"Queue record not found: {queue_id}")

        queue_record = queue_result.data[0]

        # Add as product pattern if requested
        if add_as_pattern:
            self.add_product_url(
                product_id=product_id,
                url_pattern=queue_record['normalized_url'],
                match_type=match_type
            )

        # Update queue status
        result = self.supabase.table("url_review_queue")\
            .update({
                "status": "assigned",
                "suggested_product_id": str(product_id),
                "reviewed_at": datetime.utcnow().isoformat()
            })\
            .eq("id", str(queue_id))\
            .execute()

        # Re-match ads using this URL
        self._rematch_ads_for_url(
            queue_record['brand_id'],
            queue_record['normalized_url'],
            product_id
        )

        logger.info(f"Assigned URL {queue_record['url']} to product {product_id}")
        return result.data[0] if result.data else {}

    def ignore_url(
        self,
        queue_id: UUID,
        ignore_reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Mark a queued URL as ignored (not a product page).

        Args:
            queue_id: Review queue record UUID
            ignore_reason: Optional reason/category (e.g., 'homepage', 'social', 'collection', 'other')

        Returns:
            Updated review queue record
        """
        update_data = {
            "status": "ignored",
            "reviewed_at": datetime.utcnow().isoformat()
        }

        # Store reason in notes field if provided
        if ignore_reason:
            update_data["notes"] = f"Ignored: {ignore_reason}"

        result = self.supabase.table("url_review_queue")\
            .update(update_data)\
            .eq("id", str(queue_id))\
            .execute()

        logger.info(f"Ignored URL in queue: {queue_id} (reason: {ignore_reason})")
        return result.data[0] if result.data else {}

    def mark_as_brand_level(self, queue_id: UUID) -> Dict[str, Any]:
        """
        Mark a URL as brand-level (applies to whole brand, not specific product).

        Useful for homepages that should be included in brand-level persona
        analysis but not product-specific analysis.

        Args:
            queue_id: Review queue record UUID

        Returns:
            Updated review queue record
        """
        result = self.supabase.table("url_review_queue")\
            .update({
                "status": "brand_level",
                "reviewed_at": datetime.utcnow().isoformat(),
                "notes": "Brand-level URL (homepage, about, etc.)"
            })\
            .eq("id", str(queue_id))\
            .execute()

        logger.info(f"Marked URL as brand-level: {queue_id}")
        return result.data[0] if result.data else {}

    def mark_as_collection(self, queue_id: UUID) -> Dict[str, Any]:
        """
        Mark a URL as a collection page.

        Collection pages showcase multiple products. Useful for brands that
        run ads to collection pages rather than individual product pages.

        Args:
            queue_id: Review queue record UUID

        Returns:
            Updated review queue record
        """
        result = self.supabase.table("url_review_queue")\
            .update({
                "status": "collection",
                "reviewed_at": datetime.utcnow().isoformat(),
                "notes": "Collection page (multiple products)"
            })\
            .eq("id", str(queue_id))\
            .execute()

        logger.info(f"Marked URL as collection: {queue_id}")
        return result.data[0] if result.data else {}

    def mark_as_social(self, queue_id: UUID) -> Dict[str, Any]:
        """
        Mark a URL as a social media link.

        Social media links (Instagram, TikTok, YouTube, Facebook) that ads
        direct to instead of product pages.

        Args:
            queue_id: Review queue record UUID

        Returns:
            Updated review queue record
        """
        result = self.supabase.table("url_review_queue")\
            .update({
                "status": "social",
                "reviewed_at": datetime.utcnow().isoformat(),
                "notes": "Social media link"
            })\
            .eq("id", str(queue_id))\
            .execute()

        logger.info(f"Marked URL as social: {queue_id}")
        return result.data[0] if result.data else {}

    def _rematch_ads_for_url(
        self,
        brand_id: str,
        normalized_url: str,
        product_id: UUID
    ) -> int:
        """
        Re-match all ads that have a specific URL.

        Args:
            brand_id: Brand UUID string
            normalized_url: Normalized URL to search for
            product_id: Product to assign

        Returns:
            Number of ads updated
        """
        # Get ad IDs linked to this brand via junction table
        link_result = self.supabase.table("brand_facebook_ads")\
            .select("ad_id")\
            .eq("brand_id", brand_id)\
            .limit(500)\
            .execute()

        ad_ids = [r['ad_id'] for r in (link_result.data or [])]

        if not ad_ids:
            return 0

        # Fetch ads that don't have a product yet
        ads_result = self.supabase.table("facebook_ads")\
            .select("id, snapshot")\
            .in_("id", ad_ids)\
            .is_("product_id", "null")\
            .execute()

        updated = 0
        for ad in (ads_result.data or []):
            url = self.extract_url_from_ad(ad)
            if url and self._normalize_url(url) == normalized_url:
                self.supabase.table("facebook_ads")\
                    .update({
                        "product_id": str(product_id),
                        "product_match_confidence": 1.0,
                        "product_match_method": "manual",
                        "product_matched_at": datetime.utcnow().isoformat()
                    })\
                    .eq("id", ad['id'])\
                    .execute()
                updated += 1

        logger.info(f"Re-matched {updated} ads for URL {normalized_url}")
        return updated

    # ============================================================
    # URL Discovery
    # ============================================================

    def discover_urls_from_ads(
        self,
        brand_id: UUID,
        limit: int = 1000
    ) -> Dict[str, Any]:
        """
        Discover all unique URLs from scraped ads and add to review queue.

        This is the recommended first step - discover what URLs exist,
        then assign them to products.

        Args:
            brand_id: Brand UUID
            limit: Maximum ads to scan

        Returns:
            Stats dict with discovered, new, existing counts
        """
        # Fetch ads linked to this brand via junction table
        # Note: brand_facebook_ads stores the brand-ad relationship
        link_result = self.supabase.table("brand_facebook_ads")\
            .select("ad_id")\
            .eq("brand_id", str(brand_id))\
            .limit(limit)\
            .execute()

        ad_ids = [r['ad_id'] for r in (link_result.data or [])]

        if not ad_ids:
            logger.info(f"No ads found for brand {brand_id}")
            return {"discovered": 0, "new": 0, "existing": 0}

        # Fetch the actual ad data
        result = self.supabase.table("facebook_ads")\
            .select("id, snapshot")\
            .in_("id", ad_ids)\
            .execute()

        ads = result.data or []
        discovered_urls = {}  # normalized_url -> {url, ad_ids}

        for ad in ads:
            url = self.extract_url_from_ad(ad)
            if not url:
                continue

            normalized = self._normalize_url(url)
            if not normalized:
                continue

            if normalized not in discovered_urls:
                discovered_urls[normalized] = {
                    "url": url,
                    "ad_ids": []
                }

            if len(discovered_urls[normalized]["ad_ids"]) < 5:
                discovered_urls[normalized]["ad_ids"].append(ad['id'])

        # Add all discovered URLs to review queue
        stats = {"discovered": len(discovered_urls), "new": 0, "existing": 0}

        for normalized, data in discovered_urls.items():
            # Check if already in queue or already matched to a product
            existing = self.supabase.table("url_review_queue")\
                .select("id")\
                .eq("brand_id", str(brand_id))\
                .eq("normalized_url", normalized)\
                .execute()

            if existing.data:
                # Update occurrence count
                stats["existing"] += 1
                self.supabase.table("url_review_queue")\
                    .update({
                        "occurrence_count": len([a for a in ads if self._normalize_url(self.extract_url_from_ad(a) or "") == normalized]),
                        "sample_ad_ids": data["ad_ids"]
                    })\
                    .eq("brand_id", str(brand_id))\
                    .eq("normalized_url", normalized)\
                    .execute()
            else:
                # Check if URL matches an existing product pattern
                match = self.match_url_to_product(data["url"], brand_id)

                if match:
                    # Already has a pattern - mark as assigned
                    product_id, confidence, _ = match
                    self.supabase.table("url_review_queue")\
                        .insert({
                            "brand_id": str(brand_id),
                            "url": data["url"],
                            "normalized_url": normalized,
                            "sample_ad_ids": data["ad_ids"],
                            "occurrence_count": 1,
                            "status": "assigned",
                            "suggested_product_id": str(product_id),
                            "suggestion_confidence": confidence
                        })\
                        .execute()
                else:
                    # New URL - add to pending queue
                    self.supabase.table("url_review_queue")\
                        .insert({
                            "brand_id": str(brand_id),
                            "url": data["url"],
                            "normalized_url": normalized,
                            "sample_ad_ids": data["ad_ids"],
                            "occurrence_count": 1,
                            "status": "pending"
                        })\
                        .execute()
                    stats["new"] += 1

        logger.info(f"URL discovery for brand {brand_id}: {stats}")
        return stats

    # ============================================================
    # Statistics
    # ============================================================

    def get_matching_stats(self, brand_id: UUID) -> Dict[str, Any]:
        """
        Get product matching statistics for a brand.

        Args:
            brand_id: Brand UUID

        Returns:
            Stats dict with counts and percentages
        """
        # Total ads linked to brand via junction table
        total_result = self.supabase.table("brand_facebook_ads")\
            .select("ad_id", count="exact")\
            .eq("brand_id", str(brand_id))\
            .execute()
        total = total_result.count or 0

        # Get ad IDs to check matched status
        if total > 0:
            link_result = self.supabase.table("brand_facebook_ads")\
                .select("ad_id")\
                .eq("brand_id", str(brand_id))\
                .execute()
            ad_ids = [r['ad_id'] for r in (link_result.data or [])]

            # Matched ads (have product_id set)
            matched_result = self.supabase.table("facebook_ads")\
                .select("id", count="exact")\
                .in_("id", ad_ids)\
                .not_.is_("product_id", "null")\
                .execute()
            matched = matched_result.count or 0
        else:
            matched = 0

        # Pending review URLs
        pending_result = self.supabase.table("url_review_queue")\
            .select("id", count="exact")\
            .eq("brand_id", str(brand_id))\
            .eq("status", "pending")\
            .execute()
        pending = pending_result.count or 0

        # Product URL patterns
        patterns_result = self.supabase.table("product_urls")\
            .select("id, products!inner(brand_id)", count="exact")\
            .eq("products.brand_id", str(brand_id))\
            .execute()
        patterns = patterns_result.count or 0

        return {
            "total_ads": total,
            "matched_ads": matched,
            "unmatched_ads": total - matched,
            "match_percentage": round(matched / total * 100, 1) if total > 0 else 0,
            "pending_review_urls": pending,
            "configured_patterns": patterns
        }


# Convenience function
def get_product_url_service() -> ProductURLService:
    """Get a ProductURLService instance."""
    return ProductURLService()
