"""
CompetitorService - Competitor tracking and analysis.

This service handles:
- Competitor CRUD operations
- Competitor product management (mirroring brand products)
- Competitor product variants (flavors, sizes, colors)
- URL pattern matching for linking ads to products
- Integration with Amazon review scraping and analysis
- Persona synthesis at competitor or product level
"""

import logging
import re
from typing import List, Dict, Optional, Any, Tuple
from uuid import UUID
from datetime import datetime

from supabase import Client
from ..core.database import get_supabase_client

logger = logging.getLogger(__name__)


def _generate_slug(name: str) -> str:
    """
    Generate URL-safe slug from name.

    Args:
        name: Product or variant name

    Returns:
        URL-safe slug (lowercase, hyphens instead of spaces)
    """
    slug = name.lower().strip()
    slug = re.sub(r'[^\w\s-]', '', slug)  # Remove special chars
    slug = re.sub(r'[-\s]+', '-', slug)    # Replace spaces/multiple hyphens with single hyphen
    slug = slug.strip('-')                  # Remove leading/trailing hyphens
    return slug


class CompetitorService:
    """Service for competitor tracking and analysis."""

    def __init__(self, supabase: Optional[Client] = None):
        """
        Initialize CompetitorService.

        Args:
            supabase: Optional Supabase client. If not provided, creates one.
        """
        self.supabase = supabase or get_supabase_client()
        logger.info("CompetitorService initialized")

    # =========================================================================
    # COMPETITOR CRUD (existing entity)
    # =========================================================================

    def create_competitor(
        self,
        brand_id: UUID,
        name: str,
        website_url: Optional[str] = None,
        facebook_page_id: Optional[str] = None,
        ad_library_url: Optional[str] = None,
        industry: Optional[str] = None,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a new competitor for a brand.

        Args:
            brand_id: UUID of the brand tracking this competitor
            name: Competitor name
            website_url: Competitor's website URL
            facebook_page_id: Facebook Page ID for Ad Library scraping
            ad_library_url: Direct Ad Library URL
            industry: Industry classification
            notes: Additional notes

        Returns:
            Created competitor record
        """
        data = {
            "brand_id": str(brand_id),
            "name": name,
            "website_url": website_url,
            "facebook_page_id": facebook_page_id,
            "ad_library_url": ad_library_url,
            "industry": industry,
            "notes": notes
        }

        result = self.supabase.table("competitors").insert(data).execute()
        logger.info(f"Created competitor: {name} for brand {brand_id}")
        return result.data[0] if result.data else {}

    def get_competitor(self, competitor_id: UUID) -> Optional[Dict[str, Any]]:
        """
        Get a single competitor by ID.

        Args:
            competitor_id: UUID of the competitor

        Returns:
            Competitor record or None if not found
        """
        result = self.supabase.table("competitors").select("*").eq(
            "id", str(competitor_id)
        ).execute()
        return result.data[0] if result.data else None

    def get_competitors_for_brand(self, brand_id: UUID) -> List[Dict[str, Any]]:
        """
        Get all competitors for a brand.

        Args:
            brand_id: UUID of the brand

        Returns:
            List of competitor records ordered by name
        """
        result = self.supabase.table("competitors").select("*").eq(
            "brand_id", str(brand_id)
        ).order("name").execute()
        return result.data or []

    def update_competitor(
        self,
        competitor_id: UUID,
        updates: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Update a competitor.

        Args:
            competitor_id: UUID of the competitor
            updates: Dictionary of fields to update

        Returns:
            Updated competitor record or None
        """
        result = self.supabase.table("competitors").update(updates).eq(
            "id", str(competitor_id)
        ).execute()
        if result.data:
            logger.info(f"Updated competitor: {competitor_id}")
        return result.data[0] if result.data else None

    def delete_competitor(self, competitor_id: UUID) -> bool:
        """
        Delete a competitor (cascades to products, ads, etc.).

        Args:
            competitor_id: UUID of the competitor

        Returns:
            True if deleted successfully
        """
        result = self.supabase.table("competitors").delete().eq(
            "id", str(competitor_id)
        ).execute()
        if result.data:
            logger.info(f"Deleted competitor: {competitor_id}")
            return True
        return False

    # =========================================================================
    # COMPETITOR PRODUCT CRUD
    # =========================================================================

    def create_competitor_product(
        self,
        competitor_id: UUID,
        brand_id: UUID,
        name: str,
        description: Optional[str] = None,
        product_code: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a new product for a competitor.

        Args:
            competitor_id: UUID of the competitor
            brand_id: UUID of the brand tracking this competitor
            name: Product name
            description: Product description
            product_code: Short reference code (e.g., "WL1")

        Returns:
            Created competitor product record
        """
        slug = _generate_slug(name)

        data = {
            "competitor_id": str(competitor_id),
            "brand_id": str(brand_id),
            "name": name,
            "slug": slug,
            "description": description,
            "product_code": product_code,
            "is_active": True
        }

        result = self.supabase.table("competitor_products").insert(data).execute()
        logger.info(f"Created competitor product: {name} for competitor {competitor_id}")
        return result.data[0] if result.data else {}

    def get_competitor_product(
        self,
        product_id: UUID,
        include_variants: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        Get a single competitor product by ID.

        Args:
            product_id: UUID of the competitor product
            include_variants: Whether to include variants in response

        Returns:
            Competitor product record with optional variants
        """
        if include_variants:
            result = self.supabase.table("competitor_products").select(
                "*, competitor_product_variants(*)"
            ).eq("id", str(product_id)).execute()
        else:
            result = self.supabase.table("competitor_products").select("*").eq(
                "id", str(product_id)
            ).execute()

        if not result.data:
            return None

        product = result.data[0]

        # Sort variants by display_order if present
        if include_variants and product.get("competitor_product_variants"):
            product["competitor_product_variants"] = sorted(
                product["competitor_product_variants"],
                key=lambda v: (v.get("display_order", 0), v.get("name", ""))
            )

        return product

    def get_competitor_products(
        self,
        competitor_id: UUID,
        include_variants: bool = True,
        active_only: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Get all products for a competitor.

        Args:
            competitor_id: UUID of the competitor
            include_variants: Whether to include variants
            active_only: Whether to filter to active products only

        Returns:
            List of competitor products with optional variants
        """
        query = self.supabase.table("competitor_products")

        if include_variants:
            query = query.select("*, competitor_product_variants(*)")
        else:
            query = query.select("*")

        query = query.eq("competitor_id", str(competitor_id))

        if active_only:
            query = query.eq("is_active", True)

        query = query.order("name")

        result = query.execute()
        products = result.data or []

        # Sort variants by display_order if present
        if include_variants:
            for product in products:
                if product.get("competitor_product_variants"):
                    product["competitor_product_variants"] = sorted(
                        product["competitor_product_variants"],
                        key=lambda v: (v.get("display_order", 0), v.get("name", ""))
                    )

        return products

    def update_competitor_product(
        self,
        product_id: UUID,
        updates: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Update a competitor product.

        Args:
            product_id: UUID of the competitor product
            updates: Dictionary of fields to update

        Returns:
            Updated product record or None
        """
        # Regenerate slug if name is being updated
        if "name" in updates and "slug" not in updates:
            updates["slug"] = _generate_slug(updates["name"])

        result = self.supabase.table("competitor_products").update(updates).eq(
            "id", str(product_id)
        ).execute()

        if result.data:
            logger.info(f"Updated competitor product: {product_id}")
        return result.data[0] if result.data else None

    def delete_competitor_product(self, product_id: UUID) -> bool:
        """
        Delete a competitor product (cascades to variants, URLs, etc.).

        Args:
            product_id: UUID of the competitor product

        Returns:
            True if deleted successfully
        """
        result = self.supabase.table("competitor_products").delete().eq(
            "id", str(product_id)
        ).execute()

        if result.data:
            logger.info(f"Deleted competitor product: {product_id}")
            return True
        return False

    # =========================================================================
    # COMPETITOR PRODUCT VARIANT CRUD
    # =========================================================================

    def create_competitor_product_variant(
        self,
        competitor_product_id: UUID,
        name: str,
        variant_type: str = "flavor",
        description: Optional[str] = None,
        sku: Optional[str] = None,
        differentiators: Optional[Dict[str, Any]] = None,
        price: Optional[float] = None,
        compare_at_price: Optional[float] = None,
        is_default: bool = False,
        display_order: int = 0
    ) -> Dict[str, Any]:
        """
        Create a new variant for a competitor product.

        Args:
            competitor_product_id: UUID of the competitor product
            name: Variant name (e.g., "Strawberry", "Large")
            variant_type: Type of variant (flavor, size, color, bundle, other)
            description: Variant description
            sku: Optional SKU/product code
            differentiators: JSON object with variant-specific attributes
            price: Price if known
            compare_at_price: Original price for comparison
            is_default: Whether this is the default/hero variant
            display_order: Sort order for display

        Returns:
            Created variant record
        """
        slug = _generate_slug(name)

        data = {
            "competitor_product_id": str(competitor_product_id),
            "name": name,
            "slug": slug,
            "variant_type": variant_type,
            "description": description,
            "sku": sku,
            "differentiators": differentiators or {},
            "price": price,
            "compare_at_price": compare_at_price,
            "is_active": True,
            "is_default": is_default,
            "display_order": display_order
        }

        result = self.supabase.table("competitor_product_variants").insert(data).execute()
        logger.info(f"Created variant: {name} for product {competitor_product_id}")
        return result.data[0] if result.data else {}

    def get_competitor_product_variants(
        self,
        competitor_product_id: UUID,
        active_only: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Get all variants for a competitor product.

        Args:
            competitor_product_id: UUID of the competitor product
            active_only: Whether to filter to active variants only

        Returns:
            List of variants ordered by display_order then name
        """
        query = self.supabase.table("competitor_product_variants").select("*").eq(
            "competitor_product_id", str(competitor_product_id)
        )

        if active_only:
            query = query.eq("is_active", True)

        result = query.execute()
        variants = result.data or []

        # Sort by display_order, then name
        variants.sort(key=lambda v: (v.get("display_order", 0), v.get("name", "")))

        return variants

    def update_competitor_product_variant(
        self,
        variant_id: UUID,
        updates: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Update a competitor product variant.

        Args:
            variant_id: UUID of the variant
            updates: Dictionary of fields to update

        Returns:
            Updated variant record or None
        """
        # Regenerate slug if name is being updated
        if "name" in updates and "slug" not in updates:
            updates["slug"] = _generate_slug(updates["name"])

        result = self.supabase.table("competitor_product_variants").update(updates).eq(
            "id", str(variant_id)
        ).execute()

        if result.data:
            logger.info(f"Updated variant: {variant_id}")
        return result.data[0] if result.data else None

    def delete_competitor_product_variant(self, variant_id: UUID) -> bool:
        """
        Delete a competitor product variant.

        Args:
            variant_id: UUID of the variant

        Returns:
            True if deleted successfully
        """
        result = self.supabase.table("competitor_product_variants").delete().eq(
            "id", str(variant_id)
        ).execute()

        if result.data:
            logger.info(f"Deleted variant: {variant_id}")
            return True
        return False

    def set_default_variant(
        self,
        competitor_product_id: UUID,
        variant_id: UUID
    ) -> bool:
        """
        Set a variant as the default for a product (unsets others).

        Args:
            competitor_product_id: UUID of the product
            variant_id: UUID of the variant to set as default

        Returns:
            True if successful
        """
        # Unset all defaults for this product
        self.supabase.table("competitor_product_variants").update(
            {"is_default": False}
        ).eq("competitor_product_id", str(competitor_product_id)).execute()

        # Set the new default
        result = self.supabase.table("competitor_product_variants").update(
            {"is_default": True}
        ).eq("id", str(variant_id)).execute()

        if result.data:
            logger.info(f"Set default variant: {variant_id} for product {competitor_product_id}")
            return True
        return False

    # =========================================================================
    # COMPETITOR PRODUCT URL PATTERN METHODS
    # =========================================================================

    def add_competitor_product_url(
        self,
        competitor_product_id: UUID,
        url_pattern: str,
        match_type: str = "contains",
        is_primary: bool = False,
        is_fallback: bool = False,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Add a URL pattern for a competitor product.

        Args:
            competitor_product_id: UUID of the competitor product
            url_pattern: URL pattern to match
            match_type: How to match (exact, prefix, contains, regex)
            is_primary: Whether this is the primary landing page
            is_fallback: Whether this is a fallback for research
            notes: Additional notes

        Returns:
            Created URL pattern record
        """
        # Normalize the URL pattern
        normalized = self._normalize_url(url_pattern)

        data = {
            "competitor_product_id": str(competitor_product_id),
            "url_pattern": normalized,
            "match_type": match_type,
            "is_primary": is_primary,
            "is_fallback": is_fallback,
            "notes": notes
        }

        result = self.supabase.table("competitor_product_urls").upsert(
            data, on_conflict="competitor_product_id,url_pattern"
        ).execute()

        logger.info(f"Added URL pattern for product {competitor_product_id}: {normalized}")
        return result.data[0] if result.data else {}

    def get_competitor_product_urls(
        self,
        competitor_product_id: UUID
    ) -> List[Dict[str, Any]]:
        """
        Get all URL patterns for a competitor product.

        Args:
            competitor_product_id: UUID of the competitor product

        Returns:
            List of URL pattern records
        """
        result = self.supabase.table("competitor_product_urls").select("*").eq(
            "competitor_product_id", str(competitor_product_id)
        ).order("is_primary", desc=True).execute()
        return result.data or []

    def delete_competitor_product_url(self, url_id: UUID) -> bool:
        """
        Delete a competitor product URL pattern.

        Args:
            url_id: UUID of the URL pattern record

        Returns:
            True if deleted successfully
        """
        result = self.supabase.table("competitor_product_urls").delete().eq(
            "id", str(url_id)
        ).execute()

        if result.data:
            logger.info(f"Deleted URL pattern: {url_id}")
            return True
        return False

    def match_url_to_competitor_product(
        self,
        url: str,
        competitor_id: UUID
    ) -> Optional[Tuple[UUID, float, str]]:
        """
        Match a URL to a competitor product using configured patterns.

        Args:
            url: URL to match
            competitor_id: UUID of the competitor to search within

        Returns:
            Tuple of (product_id, confidence_score, match_type) or None
        """
        # Normalize the input URL
        normalized_url = self._normalize_url(url)

        # Get all products for this competitor
        products = self.get_competitor_products(competitor_id, include_variants=False)

        best_match: Optional[Tuple[UUID, float, str]] = None
        best_confidence = 0.0

        for product in products:
            product_id = UUID(product["id"])

            # Get URL patterns for this product
            patterns = self.get_competitor_product_urls(product_id)

            for pattern in patterns:
                confidence = self._check_pattern_match(
                    normalized_url,
                    pattern["url_pattern"],
                    pattern["match_type"]
                )

                if confidence > best_confidence:
                    best_confidence = confidence
                    best_match = (product_id, confidence, pattern["match_type"])

        if best_match and best_confidence >= 0.5:
            logger.debug(f"Matched URL to product: {best_match[0]} (confidence: {best_match[1]:.2f})")
            return best_match

        return None

    def _normalize_url(self, url: str) -> str:
        """
        Normalize URL for matching.

        Removes:
        - Protocol (http/https)
        - www. prefix
        - Trailing slashes
        - Tracking parameters (utm_*, fbclid, gclid, ref, source)

        Args:
            url: URL to normalize

        Returns:
            Normalized URL
        """
        from urllib.parse import urlparse, parse_qs, urlencode

        # Handle empty input
        if not url:
            return ""

        # Add protocol if missing for parsing
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url

        try:
            parsed = urlparse(url)

            # Remove www. prefix
            netloc = parsed.netloc.lower()
            if netloc.startswith('www.'):
                netloc = netloc[4:]

            # Remove tracking params
            tracking_params = {'utm_source', 'utm_medium', 'utm_campaign', 'utm_term',
                             'utm_content', 'fbclid', 'gclid', 'ref', 'source', 'mc_cid',
                             'mc_eid', '_ga', '_gid'}

            if parsed.query:
                params = parse_qs(parsed.query, keep_blank_values=True)
                filtered_params = {k: v for k, v in params.items()
                                 if k.lower() not in tracking_params}
                query = urlencode(filtered_params, doseq=True) if filtered_params else ""
            else:
                query = ""

            # Reconstruct URL without protocol
            path = parsed.path.rstrip('/')
            result = netloc + path
            if query:
                result += '?' + query

            return result

        except Exception:
            return url.lower().strip('/')

    def _check_pattern_match(
        self,
        url: str,
        pattern: str,
        match_type: str
    ) -> float:
        """
        Check if URL matches pattern and return confidence score.

        Args:
            url: Normalized URL to check
            pattern: Pattern to match against
            match_type: Type of match (exact, prefix, contains, regex)

        Returns:
            Confidence score 0.0-1.0
        """
        if match_type == "exact":
            return 1.0 if url == pattern else 0.0

        elif match_type == "prefix":
            if url.startswith(pattern):
                return 0.95
            return 0.0

        elif match_type == "contains":
            if pattern in url:
                # Higher confidence for longer patterns (more specific)
                confidence = 0.5 + (len(pattern) / len(url)) * 0.4
                return min(confidence, 0.9)
            return 0.0

        elif match_type == "regex":
            try:
                if re.search(pattern, url):
                    return 0.85
            except re.error:
                logger.warning(f"Invalid regex pattern: {pattern}")
            return 0.0

        return 0.0

    # =========================================================================
    # COMPETITOR AD MATCHING METHODS
    # =========================================================================

    def bulk_match_competitor_ads(
        self,
        competitor_id: UUID,
        limit: int = 500,
        only_unmatched: bool = True
    ) -> Dict[str, int]:
        """
        Match competitor ads to products via URL patterns.

        Args:
            competitor_id: UUID of the competitor
            limit: Maximum ads to process
            only_unmatched: Only process ads without product assignments

        Returns:
            Stats dict: {matched, unmatched, failed, total}
        """
        # Get competitor ads
        query = self.supabase.table("competitor_ads").select(
            "id, link_url, snapshot_data"
        ).eq("competitor_id", str(competitor_id))

        if only_unmatched:
            query = query.is_("competitor_product_id", "null")

        query = query.limit(limit)
        result = query.execute()
        ads = result.data or []

        stats = {"matched": 0, "unmatched": 0, "failed": 0, "total": len(ads)}

        for ad in ads:
            try:
                # Extract URL from ad
                url = self._extract_url_from_ad(ad)
                if not url:
                    stats["unmatched"] += 1
                    continue

                # Try to match to product
                match = self.match_url_to_competitor_product(url, competitor_id)

                if match:
                    product_id, confidence, match_method = match

                    # Update ad with product assignment
                    self.supabase.table("competitor_ads").update({
                        "competitor_product_id": str(product_id),
                        "product_match_confidence": confidence,
                        "product_match_method": "url"
                    }).eq("id", ad["id"]).execute()

                    stats["matched"] += 1
                else:
                    stats["unmatched"] += 1

            except Exception as e:
                logger.error(f"Failed to match ad {ad['id']}: {e}")
                stats["failed"] += 1

        logger.info(f"Bulk match complete for competitor {competitor_id}: {stats}")
        return stats

    def manually_assign_ad_to_product(
        self,
        ad_id: UUID,
        competitor_product_id: UUID
    ) -> bool:
        """
        Manually assign a competitor ad to a product.

        Args:
            ad_id: UUID of the competitor ad
            competitor_product_id: UUID of the competitor product

        Returns:
            True if successful
        """
        result = self.supabase.table("competitor_ads").update({
            "competitor_product_id": str(competitor_product_id),
            "product_match_confidence": 1.0,
            "product_match_method": "manual"
        }).eq("id", str(ad_id)).execute()

        if result.data:
            logger.info(f"Manually assigned ad {ad_id} to product {competitor_product_id}")
            return True
        return False

    def get_competitor_ads_by_product(
        self,
        competitor_product_id: UUID,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get competitor ads for a specific product.

        Args:
            competitor_product_id: UUID of the competitor product
            limit: Maximum ads to return

        Returns:
            List of competitor ad records
        """
        result = self.supabase.table("competitor_ads").select("*").eq(
            "competitor_product_id", str(competitor_product_id)
        ).order("started_running", desc=True).limit(limit).execute()
        return result.data or []

    def _extract_url_from_ad(self, ad: Dict[str, Any]) -> Optional[str]:
        """
        Extract landing page URL from competitor ad.

        Args:
            ad: Competitor ad record with link_url and/or snapshot_data

        Returns:
            Extracted URL or None
        """
        import json

        # First try direct link_url
        if ad.get("link_url"):
            return ad["link_url"]

        # Try snapshot_data
        snapshot = ad.get("snapshot_data")
        if not snapshot:
            return None

        if isinstance(snapshot, str):
            try:
                snapshot = json.loads(snapshot)
            except json.JSONDecodeError:
                return None

        # Try various fields
        url = snapshot.get("link_url")
        if url:
            return url

        # Try cards (carousel ads)
        cards = snapshot.get("cards", [])
        if cards and isinstance(cards, list):
            for card in cards:
                if card.get("link_url"):
                    return card["link_url"]

        # Try cta_link
        url = snapshot.get("cta_link")
        if url:
            return url

        return None

    # =========================================================================
    # STATISTICS METHODS
    # =========================================================================

    def get_competitor_stats(self, competitor_id: UUID) -> Dict[str, Any]:
        """
        Get statistics for a competitor.

        Args:
            competitor_id: UUID of the competitor

        Returns:
            Dict with counts for ads, products, analyses, etc.
        """
        competitor_id_str = str(competitor_id)

        # Get counts from various tables
        ads_result = self.supabase.table("competitor_ads").select(
            "id", count="exact"
        ).eq("competitor_id", competitor_id_str).execute()

        products_result = self.supabase.table("competitor_products").select(
            "id", count="exact"
        ).eq("competitor_id", competitor_id_str).eq("is_active", True).execute()

        landing_pages_result = self.supabase.table("competitor_landing_pages").select(
            "id", count="exact"
        ).eq("competitor_id", competitor_id_str).execute()

        amazon_urls_result = self.supabase.table("competitor_amazon_urls").select(
            "id", count="exact"
        ).eq("competitor_id", competitor_id_str).execute()

        return {
            "ads": ads_result.count or 0,
            "products": products_result.count or 0,
            "landing_pages": landing_pages_result.count or 0,
            "amazon_urls": amazon_urls_result.count or 0
        }

    def get_competitor_product_stats(self, product_id: UUID) -> Dict[str, Any]:
        """
        Get statistics for a competitor product.

        Args:
            product_id: UUID of the competitor product

        Returns:
            Dict with counts for ads, URLs, landing pages linked to this product
        """
        product_id_str = str(product_id)

        # Get counts
        ads_result = self.supabase.table("competitor_ads").select(
            "id", count="exact"
        ).eq("competitor_product_id", product_id_str).execute()

        urls_result = self.supabase.table("competitor_product_urls").select(
            "id", count="exact"
        ).eq("competitor_product_id", product_id_str).execute()

        variants_result = self.supabase.table("competitor_product_variants").select(
            "id", count="exact"
        ).eq("competitor_product_id", product_id_str).eq("is_active", True).execute()

        amazon_result = self.supabase.table("competitor_amazon_urls").select(
            "id", count="exact"
        ).eq("competitor_product_id", product_id_str).execute()

        landing_pages_result = self.supabase.table("competitor_landing_pages").select(
            "id", count="exact"
        ).eq("competitor_product_id", product_id_str).execute()

        return {
            "ads": ads_result.count or 0,
            "url_patterns": urls_result.count or 0,
            "variants": variants_result.count or 0,
            "amazon_urls": amazon_result.count or 0,
            "landing_pages": landing_pages_result.count or 0
        }

    def get_competitor_matching_stats(self, competitor_id: UUID) -> Dict[str, Any]:
        """
        Get URL matching statistics for a competitor (similar to brand ProductURLService).

        Args:
            competitor_id: UUID of the competitor

        Returns:
            Dict with total_ads, matched_ads, unmatched_ads, match_percentage, configured_patterns
        """
        competitor_id_str = str(competitor_id)

        # Total ads for this competitor
        total_result = self.supabase.table("competitor_ads").select(
            "id", count="exact"
        ).eq("competitor_id", competitor_id_str).execute()
        total_ads = total_result.count or 0

        # Matched ads (have competitor_product_id)
        matched_result = self.supabase.table("competitor_ads").select(
            "id", count="exact"
        ).eq("competitor_id", competitor_id_str).not_.is_(
            "competitor_product_id", "null"
        ).execute()
        matched_ads = matched_result.count or 0

        # Unmatched ads
        unmatched_ads = total_ads - matched_ads

        # Match percentage
        match_percentage = round((matched_ads / total_ads * 100), 1) if total_ads > 0 else 0

        # Configured URL patterns (across all products for this competitor)
        products = self.get_competitor_products(competitor_id, include_variants=False)
        configured_patterns = 0
        for product in products:
            urls = self.get_competitor_product_urls(UUID(product["id"]))
            configured_patterns += len(urls)

        return {
            "total_ads": total_ads,
            "matched_ads": matched_ads,
            "unmatched_ads": unmatched_ads,
            "match_percentage": match_percentage,
            "configured_patterns": configured_patterns
        }

    def get_competitor_amazon_stats(self, competitor_id: UUID) -> Dict[str, Any]:
        """
        Get Amazon review analysis statistics for a competitor.

        Args:
            competitor_id: UUID of the competitor

        Returns:
            Dict with has_analysis, review_count, url_count
        """
        competitor_id_str = str(competitor_id)

        # Check if analysis exists
        analysis_result = self.supabase.table("competitor_amazon_review_analysis").select(
            "id"
        ).eq("competitor_id", competitor_id_str).execute()
        has_analysis = bool(analysis_result.data)

        # Count reviews
        reviews_result = self.supabase.table("competitor_amazon_reviews").select(
            "id", count="exact"
        ).eq("competitor_id", competitor_id_str).execute()
        review_count = reviews_result.count or 0

        # Count Amazon URLs
        urls_result = self.supabase.table("competitor_amazon_urls").select(
            "id", count="exact"
        ).eq("competitor_id", competitor_id_str).execute()
        url_count = urls_result.count or 0

        return {
            "has_analysis": has_analysis,
            "review_count": review_count,
            "url_count": url_count
        }

    def get_competitor_amazon_analysis(self, competitor_id: UUID) -> Optional[Dict[str, Any]]:
        """
        Get the Amazon review analysis for a competitor.

        Args:
            competitor_id: UUID of the competitor

        Returns:
            Analysis dict if exists, None otherwise
        """
        try:
            result = self.supabase.table("competitor_amazon_review_analysis").select(
                "*"
            ).eq("competitor_id", str(competitor_id)).execute()

            if result.data and len(result.data) > 0:
                return result.data[0]
            return None

        except Exception as e:
            logger.error(f"Failed to get competitor Amazon analysis: {e}")
            return None

    def get_unmatched_competitor_ad_urls(
        self,
        competitor_id: UUID,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Get unique URLs from competitor ads that aren't matched to a product.

        Args:
            competitor_id: UUID of the competitor
            limit: Max URLs to return

        Returns:
            List of dicts with url, ad_count, sample_ad_ids
        """
        competitor_id_str = str(competitor_id)

        try:
            # Get all unmatched ads with their link_url
            result = self.supabase.table("competitor_ads").select(
                "id, link_url"
            ).eq(
                "competitor_id", competitor_id_str
            ).is_(
                "competitor_product_id", "null"
            ).not_.is_(
                "link_url", "null"
            ).execute()

            if not result.data:
                return []

            # Group by URL
            url_groups = {}
            for ad in result.data:
                url = ad.get('link_url', '').strip()
                if not url:
                    continue
                # Normalize URL (remove trailing slash, lowercase domain)
                if url not in url_groups:
                    url_groups[url] = {'url': url, 'ad_ids': []}
                url_groups[url]['ad_ids'].append(ad['id'])

            # Convert to list and sort by occurrence count
            url_list = []
            for url, data in url_groups.items():
                url_list.append({
                    'url': url,
                    'ad_count': len(data['ad_ids']),
                    'sample_ad_ids': data['ad_ids'][:3]
                })

            # Sort by ad_count descending
            url_list.sort(key=lambda x: x['ad_count'], reverse=True)

            return url_list[:limit]

        except Exception as e:
            logger.error(f"Failed to get unmatched competitor ad URLs: {e}")
            return []

    def assign_competitor_ads_to_product(
        self,
        competitor_id: UUID,
        url_pattern: str,
        competitor_product_id: UUID,
        match_type: str = "contains"
    ) -> Dict[str, int]:
        """
        Assign all competitor ads with a matching URL to a product.

        Args:
            competitor_id: UUID of the competitor
            url_pattern: URL pattern to match
            competitor_product_id: UUID of the product to assign
            match_type: How to match (contains, exact, prefix)

        Returns:
            Dict with matched count
        """
        competitor_id_str = str(competitor_id)
        product_id_str = str(competitor_product_id)

        try:
            # Get all unmatched ads for this competitor
            result = self.supabase.table("competitor_ads").select(
                "id, link_url"
            ).eq(
                "competitor_id", competitor_id_str
            ).is_(
                "competitor_product_id", "null"
            ).execute()

            if not result.data:
                return {"matched": 0}

            # Find matching ads
            matching_ids = []
            for ad in result.data:
                link_url = ad.get('link_url', '') or ''
                matched = False

                if match_type == "exact":
                    matched = link_url == url_pattern
                elif match_type == "prefix":
                    matched = link_url.startswith(url_pattern)
                else:  # contains (default)
                    matched = url_pattern in link_url

                if matched:
                    matching_ids.append(ad['id'])

            # Update matching ads
            if matching_ids:
                self.supabase.table("competitor_ads").update({
                    "competitor_product_id": product_id_str,
                    "product_match_method": "manual"
                }).in_("id", matching_ids).execute()

            # Also add the URL pattern to product_urls for future matching
            self.add_competitor_product_url(
                competitor_product_id=competitor_product_id,
                url_pattern=url_pattern,
                match_type=match_type,
                is_primary=True
            )

            logger.info(f"Assigned {len(matching_ids)} ads to product {product_id_str}")
            return {"matched": len(matching_ids)}

        except Exception as e:
            logger.error(f"Failed to assign competitor ads to product: {e}")
            return {"matched": 0, "error": str(e)}

    # =========================================================================
    # AD SCRAPING INTEGRATION
    # =========================================================================

    def save_competitor_ad(
        self,
        competitor_id: UUID,
        brand_id: UUID,
        ad_data: Dict[str, Any],
        scrape_source: str = "ad_library_search"
    ) -> Optional[UUID]:
        """
        Save a scraped Facebook ad to the competitor_ads table.

        Args:
            competitor_id: UUID of the competitor
            brand_id: UUID of the brand tracking this competitor
            ad_data: Ad data dict (from FacebookService or similar)
            scrape_source: Source identifier

        Returns:
            UUID of saved record or None if failed
        """
        import json
        from datetime import datetime
        import pandas as pd

        def serialize_value(val):
            """Convert non-serializable types to strings."""
            if val is None or (isinstance(val, float) and pd.isna(val)):
                return None
            if isinstance(val, pd.Timestamp):
                return val.isoformat()
            if isinstance(val, datetime):
                return val.isoformat()
            return val

        try:
            # Parse snapshot to extract additional fields
            snapshot_raw = ad_data.get("snapshot")
            snapshot = {}
            if snapshot_raw:
                if isinstance(snapshot_raw, str):
                    try:
                        snapshot = json.loads(snapshot_raw)
                    except json.JSONDecodeError:
                        pass
                elif isinstance(snapshot_raw, dict):
                    snapshot = snapshot_raw

            record = {
                "competitor_id": str(competitor_id),
                "brand_id": str(brand_id),
                "ad_archive_id": ad_data.get("ad_archive_id"),
                "page_id": ad_data.get("page_id"),
                "page_name": ad_data.get("page_name"),
                "is_active": bool(ad_data.get("is_active", False)),
                "started_running": serialize_value(ad_data.get("start_date")),
                "stopped_running": serialize_value(ad_data.get("end_date")),
                "ad_creative_body": snapshot.get("body", {}).get("text") if isinstance(snapshot.get("body"), dict) else None,
                "link_url": snapshot.get("link_url"),
                "cta_text": snapshot.get("cta_text"),
                "snapshot_data": snapshot_raw,
                "scrape_source": scrape_source,
                "scraped_at": datetime.utcnow().isoformat()
            }

            # Upsert based on ad_archive_id
            result = self.supabase.table("competitor_ads").upsert(
                record,
                on_conflict="competitor_id,ad_archive_id"
            ).execute()

            if result.data:
                ad_id = result.data[0]["id"]
                logger.info(f"Saved competitor ad: {ad_id}")
                return UUID(ad_id)

            return None

        except Exception as e:
            logger.error(f"Failed to save competitor ad: {e}")
            return None

    def save_competitor_ads_batch(
        self,
        competitor_id: UUID,
        brand_id: UUID,
        ads: List[Dict[str, Any]],
        scrape_source: str = "ad_library_search"
    ) -> Dict[str, int]:
        """
        Save multiple competitor ads in batch.

        Args:
            competitor_id: UUID of the competitor
            brand_id: UUID of the brand
            ads: List of ad data dicts
            scrape_source: Source identifier

        Returns:
            Stats dict: {saved, failed, total}
        """
        stats = {"saved": 0, "failed": 0, "total": len(ads)}

        for ad_data in ads:
            result = self.save_competitor_ad(
                competitor_id=competitor_id,
                brand_id=brand_id,
                ad_data=ad_data,
                scrape_source=scrape_source
            )
            if result:
                stats["saved"] += 1
            else:
                stats["failed"] += 1

        logger.info(f"Batch save complete: {stats}")
        return stats

    # =========================================================================
    # LANDING PAGE SCRAPING
    # =========================================================================

    async def scrape_and_save_landing_page(
        self,
        url: str,
        competitor_id: UUID,
        brand_id: UUID,
        competitor_product_id: Optional[UUID] = None
    ) -> Optional[UUID]:
        """
        Scrape a landing page and save to competitor_landing_pages.

        Args:
            url: URL to scrape
            competitor_id: UUID of the competitor
            brand_id: UUID of the brand
            competitor_product_id: Optional product to associate

        Returns:
            UUID of saved record or None if failed
        """
        from datetime import datetime

        try:
            # Import web scraping service
            from .web_scraping_service import WebScrapingService

            scraper = WebScrapingService()
            result = await scraper.scrape_url_async(
                url=url,
                formats=["markdown", "html"],
                only_main_content=True
            )

            if not result.success:
                logger.error(f"Failed to scrape {url}: {result.error}")
                return None

            # Save to database
            record = {
                "competitor_id": str(competitor_id),
                "brand_id": str(brand_id),
                "url": url,
                "is_manual": False,
                "scraped_content": result.markdown,
                "scraped_html": result.html,
                "scraped_at": datetime.utcnow().isoformat()
            }

            if competitor_product_id:
                record["competitor_product_id"] = str(competitor_product_id)

            db_result = self.supabase.table("competitor_landing_pages").upsert(
                record,
                on_conflict="competitor_id,url"
            ).execute()

            if db_result.data:
                page_id = db_result.data[0]["id"]
                logger.info(f"Saved landing page: {page_id}")
                return UUID(page_id)

            return None

        except Exception as e:
            logger.error(f"Failed to scrape landing page {url}: {e}")
            return None

    async def analyze_landing_page(
        self,
        landing_page_id: UUID
    ) -> Optional[Dict[str, Any]]:
        """
        Analyze a scraped landing page using AI.

        Args:
            landing_page_id: UUID of the landing page record

        Returns:
            Analysis data dict or None if failed
        """
        from datetime import datetime
        from anthropic import Anthropic

        try:
            # Get landing page content
            result = self.supabase.table("competitor_landing_pages").select(
                "id, url, scraped_content"
            ).eq("id", str(landing_page_id)).execute()

            if not result.data or not result.data[0].get("scraped_content"):
                logger.error(f"Landing page {landing_page_id} has no scraped content")
                return None

            page = result.data[0]
            content = page["scraped_content"]

            # Analyze with Claude
            anthropic = Anthropic()
            prompt = f"""Analyze this competitor landing page content and extract key marketing elements.

URL: {page['url']}

CONTENT:
{content[:8000]}

Extract and return JSON with:
{{
  "headline": "Main headline/hero text",
  "value_proposition": "Core value proposition",
  "target_audience": "Who the page targets",
  "key_benefits": ["Benefit 1", "Benefit 2", ...],
  "features": ["Feature 1", "Feature 2", ...],
  "social_proof": ["Testimonial/stat 1", ...],
  "objection_handling": ["FAQ/objection 1", ...],
  "call_to_action": "Primary CTA text",
  "urgency_elements": ["Urgency element 1", ...],
  "pricing_info": "Price or pricing model if visible",
  "trust_signals": ["Trust signal 1", ...],
  "pain_points_addressed": ["Pain point 1", ...],
  "emotional_triggers": ["Emotional trigger 1", ...]
}}

Return ONLY valid JSON."""

            message = anthropic.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}]
            )

            response_text = message.content[0].text

            # Parse response
            import json
            clean_response = response_text.strip()
            if clean_response.startswith("```"):
                lines = clean_response.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines[-1].strip() == "```":
                    lines = lines[:-1]
                clean_response = "\n".join(lines)

            analysis_data = json.loads(clean_response)

            # Update database
            self.supabase.table("competitor_landing_pages").update({
                "analysis_data": analysis_data,
                "analyzed_at": datetime.utcnow().isoformat()
            }).eq("id", str(landing_page_id)).execute()

            logger.info(f"Analyzed landing page: {landing_page_id}")
            return analysis_data

        except Exception as e:
            logger.error(f"Failed to analyze landing page {landing_page_id}: {e}")
            return None
