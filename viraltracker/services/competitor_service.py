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

import json
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

            # Use delete+insert pattern (more reliable than upsert)
            self.supabase.table("competitor_landing_pages").delete().eq(
                "competitor_id", str(competitor_id)
            ).eq("url", url).execute()

            db_result = self.supabase.table("competitor_landing_pages").insert(
                record
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
                # Use Basic model for filtering/analysis
                model=Config.get_model("basic"),
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

    def get_landing_page_stats(
        self,
        competitor_id: UUID,
        competitor_product_id: Optional[UUID] = None
    ) -> Dict[str, int]:
        """
        Get landing page statistics for a competitor.

        Returns:
            Dict with counts:
            - available: Total unique URLs from competitor ads
            - total: Landing pages in database
            - scraped: Successfully scraped pages (have scraped_at)
            - analyzed: Pages with analysis complete (have analyzed_at)
            - to_scrape: URLs from ads not yet in landing_pages table
            - to_analyze: Scraped pages not yet analyzed
        """
        try:
            competitor_id_str = str(competitor_id)

            # Get unique URLs from competitor ads
            ads_query = self.supabase.table("competitor_ads").select(
                "link_url"
            ).eq("competitor_id", competitor_id_str).not_.is_("link_url", "null")

            if competitor_product_id:
                ads_query = ads_query.eq("competitor_product_id", str(competitor_product_id))

            ads_result = ads_query.execute()

            # Extract unique URLs
            ad_urls = set()
            for ad in ads_result.data or []:
                url = ad.get("link_url")
                if url and url.strip():
                    ad_urls.add(url.strip())

            available = len(ad_urls)

            # Get existing landing pages
            lp_query = self.supabase.table("competitor_landing_pages").select(
                "url, scraped_at, analyzed_at"
            ).eq("competitor_id", competitor_id_str)

            if competitor_product_id:
                lp_query = lp_query.eq("competitor_product_id", str(competitor_product_id))

            lp_result = lp_query.execute()

            existing_urls = set()
            scraped = 0
            analyzed = 0

            for page in lp_result.data or []:
                url = page.get("url")
                if url:
                    existing_urls.add(url)
                if page.get("scraped_at"):
                    scraped += 1
                if page.get("analyzed_at"):
                    analyzed += 1

            total = len(existing_urls)
            to_scrape = len(ad_urls - existing_urls)
            to_analyze = scraped - analyzed

            return {
                "available": available,
                "total": total,
                "scraped": scraped,
                "analyzed": analyzed,
                "to_scrape": to_scrape,
                "to_analyze": max(0, to_analyze)
            }

        except Exception as e:
            logger.error(f"Failed to get landing page stats: {e}")
            return {
                "available": 0, "total": 0, "scraped": 0,
                "analyzed": 0, "to_scrape": 0, "to_analyze": 0
            }

    async def scrape_landing_pages_for_competitor(
        self,
        competitor_id: UUID,
        brand_id: UUID,
        limit: int = 20,
        competitor_product_id: Optional[UUID] = None
    ) -> Dict[str, Any]:
        """
        Discover and scrape landing pages from competitor ads.

        Finds unique URLs from competitor_ads.link_url that aren't yet
        in competitor_landing_pages, then scrapes them.

        Args:
            competitor_id: Competitor UUID
            brand_id: Brand UUID (for record keeping)
            limit: Maximum pages to scrape
            competitor_product_id: Optional filter by product

        Returns:
            Dict with results: urls_found, pages_scraped, pages_failed, already_scraped
        """
        from datetime import datetime
        from .web_scraping_service import WebScrapingService

        competitor_id_str = str(competitor_id)

        # Get unique URLs from competitor ads
        ads_query = self.supabase.table("competitor_ads").select(
            "link_url, competitor_product_id"
        ).eq("competitor_id", competitor_id_str).not_.is_("link_url", "null")

        if competitor_product_id:
            ads_query = ads_query.eq("competitor_product_id", str(competitor_product_id))

        ads_result = ads_query.execute()

        # Build URL -> product mapping (use first product seen for each URL)
        url_to_product: Dict[str, Optional[str]] = {}
        for ad in ads_result.data or []:
            url = ad.get("link_url")
            if url and url.strip() and url not in url_to_product:
                url_to_product[url.strip()] = ad.get("competitor_product_id")

        urls_found = len(url_to_product)
        logger.info(f"Found {urls_found} unique URLs from competitor ads")

        if not url_to_product:
            return {
                "urls_found": 0,
                "pages_scraped": 0,
                "pages_failed": 0,
                "already_scraped": 0
            }

        # Get existing landing page URLs
        existing_result = self.supabase.table("competitor_landing_pages").select(
            "url"
        ).eq("competitor_id", competitor_id_str).execute()

        existing_urls = {p["url"] for p in existing_result.data or []}
        already_scraped = len(existing_urls)

        # Filter to URLs not yet scraped
        new_urls = [(url, prod_id) for url, prod_id in url_to_product.items()
                    if url not in existing_urls]

        if not new_urls:
            logger.info("All URLs already scraped")
            return {
                "urls_found": urls_found,
                "pages_scraped": 0,
                "pages_failed": 0,
                "already_scraped": already_scraped
            }

        # Scrape new URLs (up to limit)
        scraper = WebScrapingService()
        pages_scraped = 0
        pages_failed = 0

        for url, prod_id in new_urls[:limit]:
            try:
                result = await scraper.scrape_url_async(
                    url=url,
                    formats=["markdown", "html"],
                    only_main_content=True
                )

                if result.success:
                    record = {
                        "competitor_id": competitor_id_str,
                        "brand_id": str(brand_id),
                        "url": url,
                        "is_manual": False,
                        "scraped_content": result.markdown,
                        "scraped_html": result.html,
                        "scraped_at": datetime.utcnow().isoformat()
                    }

                    if prod_id:
                        record["competitor_product_id"] = prod_id

                    # Use delete+insert pattern (more reliable than upsert)
                    self.supabase.table("competitor_landing_pages").delete().eq(
                        "competitor_id", competitor_id_str
                    ).eq("url", url).execute()

                    self.supabase.table("competitor_landing_pages").insert(
                        record
                    ).execute()

                    pages_scraped += 1
                    logger.info(f"Scraped landing page: {url}")
                else:
                    pages_failed += 1
                    logger.warning(f"Failed to scrape {url}: {result.error}")

            except Exception as e:
                pages_failed += 1
                logger.error(f"Error scraping {url}: {e}")

        return {
            "urls_found": urls_found,
            "pages_scraped": pages_scraped,
            "pages_failed": pages_failed,
            "already_scraped": already_scraped
        }

    async def analyze_landing_pages_for_competitor(
        self,
        competitor_id: UUID,
        limit: int = 20,
        competitor_product_id: Optional[UUID] = None
    ) -> List[Dict[str, Any]]:
        """
        Analyze scraped landing pages that haven't been analyzed yet.

        Args:
            competitor_id: Competitor UUID
            limit: Maximum pages to analyze
            competitor_product_id: Optional filter by product

        Returns:
            List of analysis results
        """
        competitor_id_str = str(competitor_id)

        # Get scraped but not analyzed pages
        query = self.supabase.table("competitor_landing_pages").select(
            "id, url"
        ).eq("competitor_id", competitor_id_str).not_.is_(
            "scraped_at", "null"
        ).is_("analyzed_at", "null")

        if competitor_product_id:
            query = query.eq("competitor_product_id", str(competitor_product_id))

        result = query.limit(limit).execute()

        if not result.data:
            logger.info("No landing pages to analyze")
            return []

        results = []
        for page in result.data:
            page_id = UUID(page["id"])
            analysis = await self.analyze_landing_page(page_id)

            if analysis:
                results.append({
                    "landing_page_id": str(page_id),
                    "url": page["url"],
                    "analysis": analysis
                })

        return results

    def get_landing_pages_for_competitor(
        self,
        competitor_id: UUID,
        competitor_product_id: Optional[UUID] = None
    ) -> List[Dict[str, Any]]:
        """
        Get all landing pages for a competitor.

        Args:
            competitor_id: Competitor UUID
            competitor_product_id: Optional filter by product

        Returns:
            List of landing page records
        """
        query = self.supabase.table("competitor_landing_pages").select(
            "id, url, scraped_at, analyzed_at, analysis_data, competitor_product_id"
        ).eq("competitor_id", str(competitor_id))

        if competitor_product_id:
            query = query.eq("competitor_product_id", str(competitor_product_id))

        result = query.order("scraped_at", desc=True).execute()
        return result.data or []

    # ================================================================
    # BELIEF-FIRST LANDING PAGE ANALYSIS
    # Deep strategic analysis using the 13-layer evaluation canvas
    # ================================================================

    async def analyze_landing_page_belief_first(
        self,
        landing_page_id: UUID,
        force_reanalyze: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Analyze a single competitor landing page using the 13-layer belief-first canvas.

        Uses Claude Opus 4.5 for deep strategic analysis.

        Args:
            landing_page_id: UUID of the competitor_landing_pages record
            force_reanalyze: If True, re-analyze even if already analyzed

        Returns:
            13-layer analysis dict or None if failed
        """
        import re
        from anthropic import Anthropic

        # Import the prompt from brand_research_service
        from .brand_research_service import BELIEF_FIRST_ANALYSIS_PROMPT

        try:
            # Get the landing page
            result = self.supabase.table("competitor_landing_pages").select(
                "id, url, scraped_content, belief_first_analyzed_at"
            ).eq("id", str(landing_page_id)).single().execute()

            if not result.data:
                logger.error(f"Competitor landing page not found: {landing_page_id}")
                return None

            page = result.data

            # Skip if already analyzed (unless force)
            if page.get("belief_first_analyzed_at") and not force_reanalyze:
                logger.info(f"Page {landing_page_id} already has belief-first analysis, skipping")
                return None

            # Need scraped content
            content = page.get("scraped_content", "")
            if not content:
                logger.warning(f"No content for page {landing_page_id}, skipping")
                return None

            # Truncate content if too long
            max_content_length = 50000
            if len(content) > max_content_length:
                content = content[:max_content_length] + "\n\n[Content truncated...]"

            # Build prompt
            prompt = BELIEF_FIRST_ANALYSIS_PROMPT.format(
                page_title="Competitor Landing Page",
                url=page.get("url", ""),
                content=content
            )

            # Call Claude Opus 4.5
            client = Anthropic()
            response = client.messages.create(
                model="claude-opus-4-5-20251101",
                max_tokens=8000,
                messages=[{"role": "user", "content": prompt}]
            )

            response_text = response.content[0].text

            # Parse JSON response
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                analysis = json.loads(json_match.group())
            else:
                logger.error(f"No JSON found in belief-first analysis response for {landing_page_id}")
                return None

            # Add metadata
            analysis["page_id"] = str(landing_page_id)
            analysis["url"] = page.get("url", "")
            analysis["model_used"] = "claude-opus-4-5-20251101"
            analysis["analyzed_at"] = datetime.utcnow().isoformat()

            # Save to database
            self.supabase.table("competitor_landing_pages").update({
                "belief_first_analysis": analysis,
                "belief_first_analyzed_at": datetime.utcnow().isoformat()
            }).eq("id", str(landing_page_id)).execute()

            logger.info(f"Completed belief-first analysis for competitor page {landing_page_id}")
            return analysis

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse belief-first analysis JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed belief-first analysis for competitor page {landing_page_id}: {e}")
            return None

    async def analyze_landing_pages_belief_first_for_competitor(
        self,
        competitor_id: UUID,
        limit: int = 20,
        delay_between: float = 3.0,
        competitor_product_id: Optional[UUID] = None,
        force_reanalyze: bool = False
    ) -> List[Dict]:
        """
        Batch analyze competitor landing pages using belief-first canvas.

        Args:
            competitor_id: Competitor UUID
            limit: Maximum pages to analyze
            delay_between: Delay between API calls
            competitor_product_id: Optional product filter
            force_reanalyze: Re-analyze existing

        Returns:
            List of analysis results
        """
        import asyncio

        try:
            # Build query for pages to analyze
            query = self.supabase.table("competitor_landing_pages").select(
                "id"
            ).eq("competitor_id", str(competitor_id))

            # Filter by product if specified
            if competitor_product_id:
                query = query.eq("competitor_product_id", str(competitor_product_id))

            # Filter to pages that need analysis
            if not force_reanalyze:
                query = query.is_("belief_first_analyzed_at", "null")

            # Only analyze pages that have content
            query = query.not_.is_("scraped_content", "null")

            result = query.limit(limit).execute()

            if not result.data:
                logger.info(f"No pages to analyze for competitor {competitor_id}")
                return []

            page_ids = [UUID(p["id"]) for p in result.data]
            logger.info(f"Analyzing {len(page_ids)} competitor pages with belief-first canvas")

            results = []
            for i, page_id in enumerate(page_ids):
                try:
                    analysis = await self.analyze_landing_page_belief_first(
                        landing_page_id=page_id,
                        force_reanalyze=force_reanalyze
                    )
                    if analysis:
                        results.append(analysis)

                    # Delay between calls
                    if i < len(page_ids) - 1:
                        await asyncio.sleep(delay_between)

                except Exception as e:
                    logger.error(f"Error analyzing competitor page {page_id}: {e}")
                    continue

            logger.info(f"Completed belief-first analysis for {len(results)}/{len(page_ids)} competitor pages")
            return results

        except Exception as e:
            logger.error(f"Failed batch belief-first analysis for competitor: {e}")
            return []

    def aggregate_belief_first_analysis_for_competitor(
        self,
        competitor_id: UUID,
        competitor_product_id: Optional[UUID] = None
    ) -> Dict[str, Any]:
        """
        Aggregate belief-first analysis across all landing pages for a competitor.

        Args:
            competitor_id: Competitor UUID
            competitor_product_id: Optional product filter

        Returns:
            Dict with layer_summary, problem_pages, and overall stats
        """
        try:
            # Get all pages with belief-first analysis
            query = self.supabase.table("competitor_landing_pages").select(
                "id, url, belief_first_analysis"
            ).eq("competitor_id", str(competitor_id)).not_.is_("belief_first_analysis", "null")

            if competitor_product_id:
                query = query.eq("competitor_product_id", str(competitor_product_id))

            result = query.execute()

            if not result.data:
                return {
                    "layer_summary": {},
                    "problem_pages": [],
                    "overall": {"total_pages": 0, "average_score": 0}
                }

            # Layer names
            layer_names = [
                "market_context", "brand", "product_offer", "persona",
                "jobs_to_be_done", "persona_sublayers", "angle", "unique_mechanism",
                "problem_pain_symptoms", "benefits", "features",
                "proof_risk_reversal", "expression"
            ]

            # Initialize counters
            layer_summary = {
                layer: {"clear": 0, "weak": 0, "missing": 0, "conflicting": 0}
                for layer in layer_names
            }

            problem_pages = []
            total_scores = []

            for page in result.data:
                analysis = page.get("belief_first_analysis", {})
                layers = analysis.get("layers", {})
                summary = analysis.get("summary", {})

                # Count statuses per layer
                for layer_name in layer_names:
                    layer_data = layers.get(layer_name, {})
                    status = layer_data.get("status", "missing")
                    if status in layer_summary[layer_name]:
                        layer_summary[layer_name][status] += 1

                # Track scores
                score = summary.get("overall_score", 5)
                if isinstance(score, (int, float)):
                    total_scores.append(score)

                # Identify problem pages (3+ issues)
                issue_count = (
                    summary.get("weak", 0) +
                    summary.get("missing", 0) +
                    summary.get("conflicting", 0)
                )
                if issue_count >= 3:
                    problem_pages.append({
                        "page_id": page.get("id"),
                        "url": page.get("url", ""),
                        "issue_count": issue_count,
                        "score": score,
                        "top_issues": summary.get("top_issues", [])[:3]
                    })

            # Sort problem pages by issue count
            problem_pages.sort(key=lambda x: x["issue_count"], reverse=True)

            # Find most common issues and strongest layers
            issue_counts = {}
            for layer_name, counts in layer_summary.items():
                issues = counts["weak"] + counts["missing"] + counts["conflicting"]
                issue_counts[layer_name] = issues

            sorted_issues = sorted(issue_counts.items(), key=lambda x: x[1], reverse=True)
            most_common_issues = [layer for layer, count in sorted_issues[:3] if count > 0]

            clear_counts = {layer: counts["clear"] for layer, counts in layer_summary.items()}
            sorted_clear = sorted(clear_counts.items(), key=lambda x: x[1], reverse=True)
            strongest_layers = [layer for layer, count in sorted_clear[:3] if count > 0]

            return {
                "layer_summary": layer_summary,
                "problem_pages": problem_pages[:20],
                "overall": {
                    "total_pages": len(result.data),
                    "average_score": round(sum(total_scores) / len(total_scores), 1) if total_scores else 0,
                    "most_common_issues": most_common_issues,
                    "strongest_layers": strongest_layers
                }
            }

        except Exception as e:
            logger.error(f"Failed to aggregate belief-first analysis for competitor: {e}")
            return {
                "layer_summary": {},
                "problem_pages": [],
                "overall": {"total_pages": 0, "average_score": 0}
            }

    def get_belief_first_analysis_stats_for_competitor(
        self,
        competitor_id: UUID,
        competitor_product_id: Optional[UUID] = None
    ) -> Dict[str, int]:
        """
        Get belief-first analysis statistics for a competitor.

        Returns:
            Dict with counts: total, analyzed, pending
        """
        try:
            # Get all scraped pages
            query = self.supabase.table("competitor_landing_pages").select(
                "id, belief_first_analyzed_at"
            ).eq("competitor_id", str(competitor_id)).not_.is_("scraped_content", "null")

            if competitor_product_id:
                query = query.eq("competitor_product_id", str(competitor_product_id))

            result = query.execute()

            total = len(result.data) if result.data else 0
            analyzed = sum(1 for p in (result.data or []) if p.get("belief_first_analyzed_at"))
            pending = total - analyzed

            return {
                "total": total,
                "analyzed": analyzed,
                "pending": pending
            }

        except Exception as e:
            logger.error(f"Failed to get belief-first stats for competitor: {e}")
            return {"total": 0, "analyzed": 0, "pending": 0}

    # ================================================================
    # Product-Level Analysis Methods (for Competitive Comparison)
    # ================================================================

    def get_competitor_analyses_by_product(
        self,
        competitor_product_id: UUID,
        analysis_types: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Get all ad analyses for a specific competitor product.

        Args:
            competitor_product_id: UUID of the competitor product
            analysis_types: Optional list to filter by type (e.g., ['video_vision', 'image_vision', 'copy_analysis'])

        Returns:
            List of analysis records with raw_response data
        """
        try:
            product_id_str = str(competitor_product_id)

            # Get ads for this product
            ads_result = self.supabase.table("competitor_ads").select(
                "id"
            ).eq("competitor_product_id", product_id_str).execute()

            if not ads_result.data:
                logger.info(f"No ads found for competitor product: {competitor_product_id}")
                return []

            ad_ids = [str(ad["id"]) for ad in ads_result.data]

            # Get analyses for those ads
            query = self.supabase.table("competitor_ad_analysis").select(
                "id, competitor_ad_id, analysis_type, raw_response, created_at"
            ).in_("competitor_ad_id", ad_ids)

            if analysis_types:
                query = query.in_("analysis_type", analysis_types)

            result = query.execute()

            logger.info(
                f"Found {len(result.data or [])} analyses for competitor product {competitor_product_id}"
            )
            return result.data or []

        except Exception as e:
            logger.error(f"Failed to get competitor analyses by product: {e}")
            return []

    def get_brand_analyses_by_product(
        self,
        product_id: UUID,
        analysis_types: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Get all ad analyses for a specific brand product.

        Args:
            product_id: UUID of the brand product
            analysis_types: Optional list to filter by type (e.g., ['video_vision', 'image_vision', 'copy_analysis'])

        Returns:
            List of analysis records with raw_response data
        """
        try:
            product_id_str = str(product_id)

            # Get facebook_ads for this product
            ads_result = self.supabase.table("facebook_ads").select(
                "id"
            ).eq("product_id", product_id_str).execute()

            if not ads_result.data:
                logger.info(f"No ads found for brand product: {product_id}")
                return []

            ad_ids = [str(ad["id"]) for ad in ads_result.data]

            # Get analyses for those ads
            query = self.supabase.table("brand_ad_analysis").select(
                "id, facebook_ad_id, analysis_type, raw_response, created_at"
            ).in_("facebook_ad_id", ad_ids)

            if analysis_types:
                query = query.in_("analysis_type", analysis_types)

            result = query.execute()

            logger.info(
                f"Found {len(result.data or [])} analyses for brand product {product_id}"
            )
            return result.data or []

        except Exception as e:
            logger.error(f"Failed to get brand analyses by product: {e}")
            return []

    # =========================================================================
    # AMAZON REVIEW SCRAPING & ANALYSIS
    # =========================================================================

    def scrape_amazon_reviews_for_competitor(
        self,
        competitor_amazon_url_id: UUID,
        include_keywords: bool = True,
        include_helpful: bool = True,
        timeout: int = 900
    ) -> Dict[str, Any]:
        """
        Scrape Amazon reviews for a competitor product.

        Args:
            competitor_amazon_url_id: UUID of the competitor_amazon_urls record
            include_keywords: Include keyword filter configs for broader coverage
            include_helpful: Include helpful-sort configs
            timeout: Apify run timeout in seconds

        Returns:
            Dict with scrape results:
            - raw_reviews_count: Total reviews fetched
            - unique_reviews_count: After deduplication
            - reviews_saved: Successfully saved to DB
            - cost_estimate: Estimated Apify cost
            - errors: List of error messages
        """
        from .apify_service import ApifyService
        from .amazon_review_service import AmazonReviewService

        errors = []
        amazon_service = AmazonReviewService()
        apify = ApifyService()

        # Get the competitor_amazon_urls record
        url_record = self.supabase.table("competitor_amazon_urls").select(
            "id, competitor_id, brand_id, amazon_url, asin, domain_code, competitor_product_id"
        ).eq("id", str(competitor_amazon_url_id)).single().execute()

        if not url_record.data:
            return {
                "raw_reviews_count": 0,
                "unique_reviews_count": 0,
                "reviews_saved": 0,
                "cost_estimate": 0.0,
                "errors": ["Amazon URL record not found"]
            }

        record = url_record.data
        asin = record["asin"]
        domain = record.get("domain_code", "com")
        competitor_id = record["competitor_id"]
        brand_id = record["brand_id"]
        competitor_product_id = record.get("competitor_product_id")

        logger.info(f"Scraping reviews for competitor ASIN {asin} (domain: {domain})")

        # Build scrape configs using AmazonReviewService
        configs = amazon_service.build_scrape_configs(
            asin=asin,
            domain=domain,
            include_keywords=include_keywords,
            include_helpful=include_helpful
        )

        # Run Apify actor
        logger.info(f"Running Apify with {len(configs)} configs for competitor ASIN {asin}")
        try:
            result = apify.run_actor_batch(
                actor_id="axesso_data/amazon-reviews-scraper",
                batch_inputs=configs,
                timeout=timeout,
                memory_mbytes=2048
            )
            raw_reviews = result.items
            raw_count = len(raw_reviews)
            logger.info(f"Got {raw_count} raw reviews from Apify")

        except Exception as e:
            logger.error(f"Apify scrape failed: {e}")
            return {
                "raw_reviews_count": 0,
                "unique_reviews_count": 0,
                "reviews_saved": 0,
                "cost_estimate": 0.0,
                "errors": [str(e)]
            }

        # Deduplicate
        unique_reviews = amazon_service._deduplicate_reviews(raw_reviews)
        unique_count = len(unique_reviews)
        logger.info(f"Deduplicated to {unique_count} unique reviews")

        # Save to competitor_amazon_reviews table
        saved_count = self._save_competitor_reviews(
            reviews=unique_reviews,
            competitor_amazon_url_id=competitor_amazon_url_id,
            competitor_id=UUID(competitor_id),
            brand_id=UUID(brand_id),
            asin=asin,
            competitor_product_id=UUID(competitor_product_id) if competitor_product_id else None
        )

        # Update scrape stats
        cost_estimate = apify.estimate_cost(raw_count)
        self.supabase.table("competitor_amazon_urls").update({
            "last_scraped_at": datetime.utcnow().isoformat(),
            "total_reviews_scraped": saved_count,
            "scrape_cost_estimate": cost_estimate
        }).eq("id", str(competitor_amazon_url_id)).execute()

        return {
            "raw_reviews_count": raw_count,
            "unique_reviews_count": unique_count,
            "reviews_saved": saved_count,
            "cost_estimate": cost_estimate,
            "errors": errors
        }

    def _save_competitor_reviews(
        self,
        reviews: List[Dict],
        competitor_amazon_url_id: UUID,
        competitor_id: UUID,
        brand_id: UUID,
        asin: str,
        competitor_product_id: Optional[UUID] = None
    ) -> int:
        """
        Save scraped reviews to competitor_amazon_reviews table.

        Args:
            reviews: List of review dicts from Apify
            competitor_amazon_url_id: UUID of competitor_amazon_urls record
            competitor_id: Competitor UUID
            brand_id: Brand UUID
            asin: Amazon ASIN
            competitor_product_id: Optional competitor product UUID

        Returns:
            Number of reviews saved
        """
        from .amazon_review_service import AmazonReviewService
        amazon_service = AmazonReviewService()

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
                        review_date = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
                    except (ValueError, TypeError):
                        pass

                # Parse rating
                rating = amazon_service._parse_rating(review.get("rating"))

                record = {
                    "competitor_amazon_url_id": str(competitor_amazon_url_id),
                    "competitor_id": str(competitor_id),
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
                }
                # Note: competitor_product_id column doesn't exist in table yet
                # TODO: Add migration for competitor_product_id column

                records.append(record)

            try:
                result = self.supabase.table("competitor_amazon_reviews").upsert(
                    records,
                    on_conflict="review_id,asin"
                ).execute()
                saved_count += len(result.data)
            except Exception as e:
                logger.error(f"Error saving competitor review batch: {e}")

        logger.info(f"Saved {saved_count} competitor reviews to database")
        return saved_count

    async def analyze_amazon_reviews_for_competitor(
        self,
        competitor_id: UUID,
        competitor_product_id: Optional[UUID] = None
    ) -> Dict[str, Any]:
        """
        Analyze Amazon reviews for a competitor with rich themed output.

        Generates themed clusters with scores and contextual quotes for:
        - Pain Points
        - Desired Outcomes
        - Buying Objections
        - Desired Features
        - Failed Solutions

        Args:
            competitor_id: Competitor UUID
            competitor_product_id: Optional product UUID to filter reviews

        Returns:
            Dict with analysis results including themed testimonials
        """
        import anthropic
        import json

        # Get reviews
        query = self.supabase.table("competitor_amazon_reviews").select(
            "rating, title, body, author, verified_purchase, helpful_votes"
        ).eq("competitor_id", str(competitor_id))

        if competitor_product_id:
            query = query.eq("competitor_product_id", str(competitor_product_id))

        result = query.order("helpful_votes", desc=True).limit(500).execute()
        reviews = result.data or []

        if not reviews:
            return {"error": "No reviews found to analyze"}

        logger.info(f"Analyzing {len(reviews)} competitor reviews")

        # Format reviews for prompt
        reviews_text = self._format_reviews_for_analysis(reviews)

        # Get competitor info for context
        competitor = self.supabase.table("competitors").select(
            "name, website_url, industry"
        ).eq("id", str(competitor_id)).single().execute()
        competitor_info = competitor.data if competitor.data else {}

        product_info = None
        if competitor_product_id:
            product = self.supabase.table("competitor_products").select(
                "name, description"
            ).eq("id", str(competitor_product_id)).single().execute()
            product_info = product.data

        # Build analysis prompt
        prompt = self._build_rich_analysis_prompt(
            reviews_text=reviews_text,
            competitor_name=competitor_info.get("name", "Unknown"),
            product_name=product_info.get("name") if product_info else None,
            review_count=len(reviews)
        )

        # Call Claude
        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=8000,
            messages=[{"role": "user", "content": prompt}]
        )

        response_text = response.content[0].text

        # Parse JSON response
        try:
            # Extract JSON from response
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                analysis = json.loads(json_match.group())
            else:
                raise ValueError("No JSON found in response")
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Failed to parse analysis response: {e}")
            return {"error": f"Failed to parse analysis: {e}"}

        # Save analysis to database
        self._save_competitor_amazon_analysis(
            competitor_id=competitor_id,
            competitor_product_id=competitor_product_id,
            analysis=analysis,
            reviews_count=len(reviews)
        )

        return analysis

    def _format_reviews_for_analysis(self, reviews: List[Dict]) -> str:
        """Format reviews into text for analysis prompt."""
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

    def _build_rich_analysis_prompt(
        self,
        reviews_text: str,
        competitor_name: str,
        product_name: Optional[str],
        review_count: int
    ) -> str:
        """Build the prompt for rich themed analysis."""
        product_context = f" for their product '{product_name}'" if product_name else ""

        return f"""You are an expert at extracting deep customer insights from Amazon reviews.

Analyze these {review_count} reviews for {competitor_name}{product_context}.

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

    def _save_competitor_amazon_analysis(
        self,
        competitor_id: UUID,
        competitor_product_id: Optional[UUID],
        analysis: Dict[str, Any],
        reviews_count: int
    ) -> None:
        """Save the rich analysis to competitor_amazon_review_analysis table."""
        try:
            # Get brand_id from competitor
            competitor = self.supabase.table("competitors").select(
                "brand_id"
            ).eq("id", str(competitor_id)).single().execute()
            brand_id = competitor.data["brand_id"]

            # Extract summary stats
            summary = analysis.get("summary", {})
            sentiment = summary.get("sentiment_distribution", {})

            # Map analysis fields to DB columns
            # Note: We store the full analysis structure in each JSONB column
            # jobs_to_be_done and product_issues are new, stored alongside existing fields
            record = {
                "competitor_id": str(competitor_id),
                "brand_id": str(brand_id),
                "total_reviews_analyzed": reviews_count,
                "sentiment_distribution": sentiment,
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

            if competitor_product_id:
                record["competitor_product_id"] = str(competitor_product_id)

            # Delete existing analysis for this competitor, then insert new one
            self.supabase.table("competitor_amazon_review_analysis").delete().eq(
                "competitor_id", str(competitor_id)
            ).execute()

            self.supabase.table("competitor_amazon_review_analysis").insert(
                record
            ).execute()

            logger.info(f"Saved Amazon analysis for competitor {competitor_id}")

        except Exception as e:
            logger.error(f"Failed to save competitor Amazon analysis: {e}")
