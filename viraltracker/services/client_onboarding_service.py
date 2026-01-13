"""
ClientOnboardingService - Service for managing client onboarding sessions.

This service handles:
- Creating and managing onboarding sessions
- Calculating completeness scores
- Tracking scraping operations
- Generating interview questions
- Importing data to production tables (brands, products, competitors)

Architecture:
    UI Form → client_onboarding_sessions → Import → brands, products, competitors

Part of the Service Layer - contains business logic, no UI or agent code.
"""

import logging
import re
from datetime import datetime
from dataclasses import dataclass
from typing import Dict, List, Optional, Any
from urllib.parse import urlparse
from uuid import UUID

import requests
from supabase import Client

from ..core.database import get_supabase_client

logger = logging.getLogger(__name__)


# ============================================
# FIELD CONFIGURATION
# ============================================

REQUIRED_FIELDS = {
    "brand_basics": ["name", "website_url"],
    "facebook_meta": ["page_url", "ad_library_url"],
    "products": [],  # Special handling: at least 1 product with name + offer variant
    "competitors": [],
}

NICE_TO_HAVE_FIELDS = {
    "brand_basics": ["logo_storage_path", "brand_voice", "disallowed_claims"],
    "facebook_meta": ["ad_account_id"],
    "products": [],  # Special handling: product details (amazon, dimensions, etc.)
    "competitors": ["competitors"],
}

VALID_STATUSES = [
    "in_progress",
    "awaiting_info",
    "ready_for_import",
    "imported",
    "archived",
]

VALID_SECTIONS = [
    "brand_basics",
    "facebook_meta",
    "products",  # New: per-product data (replaces amazon_data and product_assets)
    "amazon_data",  # Legacy: kept for backward compatibility
    "product_assets",  # Legacy: kept for backward compatibility
    "competitors",
    "target_audience",
    "notes",
    "call_transcript",
]


# ============================================
# DATA CLASSES
# ============================================


@dataclass
class CompletenessReport:
    """Report on onboarding session completeness."""

    score: float  # 0-100
    required_filled: int
    required_total: int
    nice_to_have_filled: int
    nice_to_have_total: int
    missing_required: List[str]
    missing_nice_to_have: List[str]


# ============================================
# SERVICE CLASS
# ============================================


class ClientOnboardingService:
    """
    Service for managing client onboarding sessions.

    Provides methods for:
    - Session CRUD operations
    - Completeness calculation
    - Scrape status tracking
    - Interview question generation
    - Import to production tables
    """

    def __init__(self):
        """Initialize ClientOnboardingService."""
        self.supabase: Client = get_supabase_client()
        logger.info("ClientOnboardingService initialized")

    # ============================================
    # SESSION CRUD
    # ============================================

    def create_session(
        self,
        session_name: str,
        client_name: Optional[str] = None,
    ) -> UUID:
        """
        Create a new onboarding session.

        Args:
            session_name: Name for the session (e.g., "Acme Corp Onboarding")
            client_name: Optional prospective client name

        Returns:
            UUID of created session
        """
        data = {
            "session_name": session_name,
            "status": "in_progress",
        }

        if client_name:
            data["client_name"] = client_name

        result = self.supabase.table("client_onboarding_sessions").insert(data).execute()
        session_id = UUID(result.data[0]["id"])
        logger.info(f"Created onboarding session: {session_id} - {session_name}")
        return session_id

    def get_session(self, session_id: UUID) -> Optional[Dict[str, Any]]:
        """
        Get a session by ID.

        Also updates last_accessed_at timestamp.

        Args:
            session_id: Session UUID

        Returns:
            Session dict or None if not found
        """
        result = (
            self.supabase.table("client_onboarding_sessions")
            .select("*")
            .eq("id", str(session_id))
            .execute()
        )

        if not result.data:
            return None

        # Update last_accessed_at
        self.supabase.table("client_onboarding_sessions").update(
            {"last_accessed_at": datetime.utcnow().isoformat()}
        ).eq("id", str(session_id)).execute()

        return result.data[0]

    def list_sessions(
        self,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        List onboarding sessions.

        Args:
            status: Optional status filter
            limit: Maximum sessions to return (default: 50)

        Returns:
            List of session dicts with summary fields
        """
        query = (
            self.supabase.table("client_onboarding_sessions")
            .select(
                "id, session_name, client_name, status, completeness_score, "
                "brand_id, created_at, updated_at"
            )
            .order("updated_at", desc=True)
            .limit(limit)
        )

        if status:
            if status not in VALID_STATUSES:
                raise ValueError(f"Invalid status: {status}. Must be one of {VALID_STATUSES}")
            query = query.eq("status", status)

        result = query.execute()
        return result.data or []

    def update_section(
        self,
        session_id: UUID,
        section: str,
        data: Dict[str, Any],
    ) -> bool:
        """
        Update a specific section of the session.

        Also recalculates completeness score.

        Args:
            session_id: Session UUID
            section: Section name (brand_basics, facebook_meta, etc.)
            data: Section data dict

        Returns:
            True if successful

        Raises:
            ValueError: If section name is invalid
        """
        if section not in VALID_SECTIONS:
            raise ValueError(f"Invalid section: {section}. Must be one of {VALID_SECTIONS}")

        update_data = {section: data}

        # Recalculate completeness
        session = self.get_session(session_id)
        if session:
            session[section] = data
            report = self._calculate_completeness(session)
            update_data["completeness_score"] = report.score
            update_data["missing_fields"] = report.missing_required + report.missing_nice_to_have

        self.supabase.table("client_onboarding_sessions").update(update_data).eq(
            "id", str(session_id)
        ).execute()

        logger.info(f"Updated section {section} for session {session_id}")
        return True

    def update_status(self, session_id: UUID, status: str) -> bool:
        """
        Update session status.

        Args:
            session_id: Session UUID
            status: New status

        Returns:
            True if successful

        Raises:
            ValueError: If status is invalid
        """
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {status}. Must be one of {VALID_STATUSES}")

        self.supabase.table("client_onboarding_sessions").update({"status": status}).eq(
            "id", str(session_id)
        ).execute()

        logger.info(f"Updated status to {status} for session {session_id}")
        return True

    def delete_session(self, session_id: UUID) -> bool:
        """
        Delete an onboarding session.

        Args:
            session_id: Session UUID

        Returns:
            True if successful
        """
        self.supabase.table("client_onboarding_sessions").delete().eq(
            "id", str(session_id)
        ).execute()

        logger.info(f"Deleted session {session_id}")
        return True

    # ============================================
    # COMPLETENESS CALCULATION
    # ============================================

    def _field_has_value(self, data: Dict[str, Any], field: str) -> bool:
        """
        Check if a field has a non-empty value.

        Args:
            data: Section data dict
            field: Field name

        Returns:
            True if field has a meaningful value
        """
        value = data.get(field)
        if value is None:
            return False
        if isinstance(value, str) and not value.strip():
            return False
        if isinstance(value, (list, dict)) and not value:
            return False
        return True

    def _calculate_completeness(self, session: Dict[str, Any]) -> CompletenessReport:
        """
        Calculate completeness score for a session.

        Scoring: 70% weight on required fields, 30% on nice-to-have.

        Special handling:
        - products: At least 1 product with name = required
        - products: Product details (amazon_url, dimensions) = nice-to-have
        - competitors: Having any = nice-to-have

        Args:
            session: Full session dict

        Returns:
            CompletenessReport with score and missing fields
        """
        required_filled = 0
        required_total = 0
        nice_to_have_filled = 0
        nice_to_have_total = 0
        missing_required = []
        missing_nice_to_have = []

        # Check required fields (skip products - handled specially below)
        for section, fields in REQUIRED_FIELDS.items():
            if section == "products":
                continue  # Handle products specially
            section_data = session.get(section) or {}
            for field in fields:
                required_total += 1
                if self._field_has_value(section_data, field):
                    required_filled += 1
                else:
                    missing_required.append(f"{section}.{field}")

        # Check nice-to-have fields (skip products and competitors - handled specially below)
        for section, fields in NICE_TO_HAVE_FIELDS.items():
            if section in ("products", "competitors"):
                continue  # Handle these specially below
            section_data = session.get(section) or {}
            for field in fields:
                nice_to_have_total += 1
                if self._field_has_value(section_data, field):
                    nice_to_have_filled += 1
                else:
                    missing_nice_to_have.append(f"{section}.{field}")

        # Special handling for competitors (array field)
        competitors = session.get("competitors") or []
        if competitors:
            # Remove from missing if we have competitors
            if "competitors.competitors" in missing_nice_to_have:
                missing_nice_to_have.remove("competitors.competitors")
                nice_to_have_filled += 1

        # Special handling for products (new Phase 10)
        # Required: At least 1 product with name
        # Nice-to-have: Product details (amazon_url, dimensions, weight, target_audience)
        products = session.get("products") or []
        required_total += 1  # At least 1 product
        nice_to_have_total += 4  # amazon_url, dimensions, weight, target_audience per product

        products_with_name = [p for p in products if p.get("name")]
        if products_with_name:
            required_filled += 1

            # Check nice-to-have product details (use first product as indicator)
            first_product = products_with_name[0]
            if first_product.get("amazon_url") or first_product.get("asin"):
                nice_to_have_filled += 1
            else:
                missing_nice_to_have.append("products.amazon_url")

            if first_product.get("dimensions"):
                nice_to_have_filled += 1
            else:
                missing_nice_to_have.append("products.dimensions")

            if first_product.get("weight"):
                nice_to_have_filled += 1
            else:
                missing_nice_to_have.append("products.weight")

            if first_product.get("target_audience"):
                nice_to_have_filled += 1
            else:
                missing_nice_to_have.append("products.target_audience")
        else:
            missing_required.append("products.name")
            missing_nice_to_have.extend([
                "products.amazon_url",
                "products.dimensions",
                "products.weight",
                "products.target_audience",
            ])

        # Calculate weighted score
        required_pct = (required_filled / required_total * 100) if required_total > 0 else 0
        nice_pct = (
            (nice_to_have_filled / nice_to_have_total * 100) if nice_to_have_total > 0 else 0
        )
        score = (required_pct * 0.7) + (nice_pct * 0.3)

        return CompletenessReport(
            score=round(score, 2),
            required_filled=required_filled,
            required_total=required_total,
            nice_to_have_filled=nice_to_have_filled,
            nice_to_have_total=nice_to_have_total,
            missing_required=missing_required,
            missing_nice_to_have=missing_nice_to_have,
        )

    def get_completeness_report(self, session_id: UUID) -> CompletenessReport:
        """
        Get completeness report for a session.

        Args:
            session_id: Session UUID

        Returns:
            CompletenessReport

        Raises:
            ValueError: If session not found
        """
        session = self.get_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        return self._calculate_completeness(session)

    # ============================================
    # SCRAPE STATUS TRACKING
    # ============================================

    def update_scrape_status(
        self,
        session_id: UUID,
        scrape_type: str,
        status: str,
        error: Optional[str] = None,
        result_data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Update scraping job status.

        Args:
            session_id: Session UUID
            scrape_type: Type of scrape (website, facebook_ads, amazon_reviews, competitors)
            status: Status (pending, running, complete, failed)
            error: Optional error message
            result_data: Optional result data to store

        Returns:
            True if successful
        """
        session = self.get_session(session_id)
        if not session:
            logger.warning(f"Session not found for scrape update: {session_id}")
            return False

        scrape_jobs = session.get("scrape_jobs") or {}
        scrape_jobs[scrape_type] = {
            "status": status,
            "updated_at": datetime.utcnow().isoformat(),
        }

        if error:
            scrape_jobs[scrape_type]["error"] = error

        update_data = {"scrape_jobs": scrape_jobs}

        # If scrape completed, update the relevant section with results
        if status == "complete" and result_data:
            if scrape_type == "website":
                brand_basics = session.get("brand_basics") or {}
                brand_basics["scraped_website_data"] = result_data
                update_data["brand_basics"] = brand_basics
            elif scrape_type == "facebook_ads":
                facebook_meta = session.get("facebook_meta") or {}
                facebook_meta["scraped_ads_count"] = result_data.get("count", 0)
                facebook_meta["scraped_at"] = datetime.utcnow().isoformat()
                update_data["facebook_meta"] = facebook_meta

        self.supabase.table("client_onboarding_sessions").update(update_data).eq(
            "id", str(session_id)
        ).execute()

        logger.info(f"Updated scrape status: {scrape_type}={status} for session {session_id}")
        return True

    # ============================================
    # SUMMARY GENERATION
    # ============================================

    def _summarize_section(
        self,
        data: Dict[str, Any],
        fields: List[str],
    ) -> Dict[str, bool]:
        """
        Summarize which fields in a section are filled.

        Args:
            data: Section data dict
            fields: List of fields to check

        Returns:
            Dict mapping field names to filled status
        """
        return {field: self._field_has_value(data, field) for field in fields}

    def get_onboarding_summary(self, session_id: UUID) -> Dict[str, Any]:
        """
        Generate onboarding summary for UI display.

        Args:
            session_id: Session UUID

        Returns:
            Structured summary dict

        Raises:
            ValueError: If session not found
        """
        session = self.get_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")

        report = self._calculate_completeness(session)

        # Summarize products
        products = session.get("products") or []
        products_with_name = [p for p in products if p.get("name")]

        return {
            "session_id": str(session_id),
            "session_name": session.get("session_name"),
            "client_name": session.get("client_name"),
            "status": session.get("status"),
            "brand_id": session.get("brand_id"),
            "completeness": {
                "score": report.score,
                "required": f"{report.required_filled}/{report.required_total}",
                "nice_to_have": f"{report.nice_to_have_filled}/{report.nice_to_have_total}",
            },
            "sections": {
                "brand_basics": self._summarize_section(
                    session.get("brand_basics") or {},
                    ["name", "website_url", "logo_storage_path", "brand_voice"],
                ),
                "facebook_meta": self._summarize_section(
                    session.get("facebook_meta") or {},
                    ["page_url", "ad_library_url", "ad_account_id"],
                ),
                "products": {
                    "filled": bool(products_with_name),
                    "count": len(products_with_name),
                    "has_amazon": any(p.get("amazon_url") or p.get("asin") for p in products),
                    "has_dimensions": any(p.get("dimensions") for p in products),
                },
                "competitors": {
                    "filled": bool(session.get("competitors")),
                    "count": len(session.get("competitors") or []),
                },
                "target_audience": self._summarize_section(
                    session.get("target_audience") or {},
                    ["demographics", "pain_points", "desires_goals"],
                ),
            },
            "missing_required": report.missing_required,
            "missing_nice_to_have": report.missing_nice_to_have,
            "interview_questions": session.get("interview_questions") or [],
            "scrape_jobs": session.get("scrape_jobs") or {},
        }

    # ============================================
    # INTERVIEW QUESTION GENERATION
    # ============================================

    def _build_question_context(
        self,
        session: Dict[str, Any],
        report: CompletenessReport,
    ) -> str:
        """
        Build context string for interview question generation.

        Args:
            session: Full session dict
            report: Completeness report

        Returns:
            Context string for AI prompt
        """
        parts = []

        brand = session.get("brand_basics") or {}
        if brand.get("name"):
            parts.append(f"Client: {brand['name']}")
        if brand.get("website_url"):
            parts.append(f"Website: {brand['website_url']}")

        audience = session.get("target_audience") or {}
        if audience.get("pain_points"):
            parts.append(f"Known pain points: {', '.join(audience['pain_points'][:5])}")
        if audience.get("desires_goals"):
            parts.append(f"Known desires: {', '.join(audience['desires_goals'][:5])}")

        competitors = session.get("competitors") or []
        if competitors:
            names = [c.get("name") for c in competitors if c.get("name")]
            if names:
                parts.append(f"Known competitors: {', '.join(names[:5])}")

        parts.append(f"Completeness: {report.score:.0f}%")

        return "\n".join(parts)

    async def generate_interview_questions(
        self,
        session_id: UUID,
    ) -> List[str]:
        """
        Generate interview questions based on missing data.

        Uses Claude to generate conversational questions for filling gaps.

        Args:
            session_id: Session UUID

        Returns:
            List of generated question strings

        Raises:
            ValueError: If session not found
        """
        import json

        from pydantic_ai import Agent

        from ..core.config import Config

        session = self.get_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")

        report = self._calculate_completeness(session)
        context = self._build_question_context(session, report)

        agent = Agent(
            model=Config.get_model("creative"),
            system_prompt="""You are an expert at onboarding new clients for a digital marketing agency.
Generate insightful interview questions to fill gaps in client information.
Questions should be conversational, open-ended, and help gather actionable data.
Return ONLY a JSON array of question strings, no other text.""",
        )

        prompt = f"""Based on this client onboarding context, generate 5-10 interview questions
to ask during a phone call to gather missing information.

CONTEXT:
{context}

MISSING REQUIRED:
{', '.join(report.missing_required) if report.missing_required else 'None'}

MISSING NICE-TO-HAVE:
{', '.join(report.missing_nice_to_have) if report.missing_nice_to_have else 'None'}

Generate questions that:
1. Flow naturally in conversation
2. Prioritize required fields first
3. Help understand the client's business and customers
4. Gather specific, actionable information

Return ONLY a JSON array of question strings."""

        result = await agent.run(prompt)

        # Parse questions from response
        try:
            json_match = re.search(r"\[[\s\S]*\]", result.output)
            if json_match:
                questions = json.loads(json_match.group())
            else:
                questions = []
        except json.JSONDecodeError:
            logger.warning("Failed to parse questions JSON, returning empty list")
            questions = []

        # Save to session
        self.supabase.table("client_onboarding_sessions").update(
            {
                "interview_questions": questions,
                "interview_questions_generated_at": datetime.utcnow().isoformat(),
            }
        ).eq("id", str(session_id)).execute()

        logger.info(f"Generated {len(questions)} interview questions for session {session_id}")
        return questions

    # ============================================
    # IMPORT TO PRODUCTION
    # ============================================

    def _slugify(self, text: str) -> str:
        """
        Convert text to URL-safe slug.

        Args:
            text: Text to slugify

        Returns:
            URL-safe slug string
        """
        slug = text.lower().strip()
        slug = re.sub(r"[^a-z0-9]+", "-", slug)
        slug = slug.strip("-")
        return slug

    def _extract_facebook_page_id(self, url: str) -> Optional[str]:
        """
        Extract Facebook page ID from URL.

        Args:
            url: Facebook page or ad library URL

        Returns:
            Page ID if found, None otherwise
        """
        if not url:
            return None
        match = re.search(r"view_all_page_id=(\d+)", url)
        if match:
            return match.group(1)
        return None

    def backfill_product_images(self, session_id: UUID) -> Dict[str, Any]:
        """
        Backfill product images from an already-imported session.

        Use this to add images to products that were imported before
        the image import feature was added.

        Args:
            session_id: Session UUID that was already imported

        Returns:
            Dict with results: {"products_processed": int, "images_saved": int, "errors": [...]}
        """
        session = self.get_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")

        brand_id = session.get("brand_id")
        if not brand_id:
            raise ValueError("Session has not been imported (no brand_id linked)")

        # Get products from session
        session_products = session.get("products") or []
        if not session_products:
            return {"products_processed": 0, "images_saved": 0, "errors": ["No products in session"]}

        # Get production products for this brand
        prod_result = self.supabase.table("products").select("id, name").eq(
            "brand_id", brand_id
        ).execute()
        production_products = {p["name"]: p["id"] for p in prod_result.data}

        results = {
            "products_processed": 0,
            "images_saved": 0,
            "errors": []
        }

        for session_prod in session_products:
            prod_name = session_prod.get("name")
            image_urls = session_prod.get("images") or []

            if not prod_name:
                continue

            if prod_name not in production_products:
                results["errors"].append(f"Product '{prod_name}' not found in production")
                continue

            if not image_urls:
                logger.info(f"No images for product '{prod_name}'")
                continue

            product_id = UUID(production_products[prod_name])
            logger.info(f"Backfilling {len(image_urls)} images for '{prod_name}'")

            saved = self._save_product_images(
                product_id=product_id,
                image_urls=image_urls
            )

            results["products_processed"] += 1
            results["images_saved"] += saved

        logger.info(f"Backfill complete: {results}")
        return results

    def backfill_product_data(self, session_id: UUID) -> Dict[str, Any]:
        """
        Backfill synthesized product data (benefits, USPs) from an already-imported session.

        Use this to populate benefits/USPs for products that were imported before
        the synthesis feature was added.

        Args:
            session_id: Session UUID that was already imported

        Returns:
            Dict with results: {"products_processed": int, "benefits_added": int, "errors": [...]}
        """
        session = self.get_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")

        brand_id = session.get("brand_id")
        if not brand_id:
            raise ValueError("Session has not been imported (no brand_id linked)")

        session_products = session.get("products") or []
        if not session_products:
            return {"products_processed": 0, "benefits_added": 0, "errors": ["No products in session"]}

        # Get production products for this brand
        prod_result = self.supabase.table("products").select("id, name").eq(
            "brand_id", brand_id
        ).execute()
        production_products = {p["name"]: p["id"] for p in prod_result.data}

        results = {
            "products_processed": 0,
            "benefits_added": 0,
            "errors": []
        }

        for session_prod in session_products:
            prod_name = session_prod.get("name")
            if not prod_name or prod_name not in production_products:
                if prod_name:
                    results["errors"].append(f"Product '{prod_name}' not found in production")
                continue

            product_id = UUID(production_products[prod_name])
            offer_variants = session_prod.get("offer_variants") or []
            amazon_analysis = session_prod.get("amazon_analysis") or {}

            logger.info(f"Backfilling product data for '{prod_name}'")

            self._synthesize_product_data(
                product_id=product_id,
                offer_variants=offer_variants,
                amazon_analysis=amazon_analysis
            )

            # Count benefits added
            all_benefits = []
            for ov in offer_variants:
                all_benefits.extend(ov.get("benefits") or [])
            if amazon_analysis:
                messaging = amazon_analysis.get("messaging") or {}
                all_benefits.extend(messaging.get("benefits") or [])

            results["products_processed"] += 1
            results["benefits_added"] += len(set(all_benefits))

        logger.info(f"Product data backfill complete: {results}")
        return results

    def import_to_production(self, session_id: UUID) -> Dict[str, Any]:
        """
        Import session data to production tables (brands, products, competitors).

        Creates:
        - Brand record from brand_basics
        - Product records from products array
        - Competitor records from competitors array

        Args:
            session_id: Session UUID

        Returns:
            Dict with created IDs: {"brand_id": UUID, "product_ids": [...], "competitor_ids": [...]}

        Raises:
            ValueError: If session not found or requirements not met
        """
        session = self.get_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")

        report = self._calculate_completeness(session)
        if report.score < 50:
            raise ValueError(
                f"Completeness score ({report.score}%) must be at least 50% to import"
            )

        created: Dict[str, Any] = {}

        # Create brand
        brand_basics = session.get("brand_basics") or {}
        facebook_meta = session.get("facebook_meta") or {}
        if brand_basics.get("name"):
            brand_data = {
                "name": brand_basics["name"],
                "slug": self._slugify(brand_basics["name"]),
            }

            if brand_basics.get("website_url"):
                brand_data["website"] = brand_basics["website_url"]
            if brand_basics.get("brand_voice"):
                brand_data["brand_guidelines"] = brand_basics["brand_voice"]
            if brand_basics.get("disallowed_claims"):
                brand_data["disallowed_claims"] = brand_basics["disallowed_claims"]

            # Add Facebook fields from facebook_meta section
            if facebook_meta.get("ad_library_url"):
                brand_data["ad_library_url"] = facebook_meta["ad_library_url"]
            if facebook_meta.get("page_id"):
                brand_data["facebook_page_id"] = facebook_meta["page_id"]
            elif facebook_meta.get("ad_library_url"):
                # Try to extract page_id from ad_library_url if not explicitly set
                page_id = self._extract_facebook_page_id(facebook_meta["ad_library_url"])
                if page_id:
                    brand_data["facebook_page_id"] = page_id

            brand_result = self.supabase.table("brands").insert(brand_data).execute()
            brand_id = UUID(brand_result.data[0]["id"])
            created["brand_id"] = str(brand_id)

            logger.info(f"Created brand: {brand_basics['name']} ({brand_id})")

            # Link session to brand
            self.supabase.table("client_onboarding_sessions").update(
                {
                    "brand_id": str(brand_id),
                    "status": "imported",
                }
            ).eq("id", str(session_id)).execute()

            # Import scraped Facebook ads
            if facebook_meta.get("url_groups"):
                ads_imported = self._import_brand_facebook_ads(brand_id, facebook_meta)
                if ads_imported > 0:
                    created["facebook_ads_imported"] = ads_imported

            # Create products
            products = session.get("products") or []
            product_ids = []
            for prod in products:
                if prod.get("name"):
                    prod_data = {
                        "brand_id": str(brand_id),
                        "name": prod["name"],
                        "slug": self._slugify(prod["name"]),
                    }

                    if prod.get("description"):
                        prod_data["description"] = prod["description"]
                    if prod.get("product_url"):
                        prod_data["product_url"] = prod["product_url"]

                    # Format dimensions as text (matches products table format)
                    dimensions = prod.get("dimensions")
                    if dimensions:
                        dim_parts = []
                        if dimensions.get("width"):
                            dim_parts.append(f"W: {dimensions['width']}")
                        if dimensions.get("height"):
                            dim_parts.append(f"H: {dimensions['height']}")
                        if dimensions.get("depth"):
                            dim_parts.append(f"D: {dimensions['depth']}")
                        if dim_parts:
                            unit = dimensions.get("unit", "inches")
                            prod_data["product_dimensions"] = f"{' x '.join(dim_parts)} ({unit})"

                    # Format target audience as text
                    target_audience = prod.get("target_audience")
                    if target_audience:
                        ta_parts = []
                        demographics = target_audience.get("demographics")
                        if demographics:
                            demo_str = ", ".join(
                                f"{k}: {v}" for k, v in demographics.items() if v
                            )
                            if demo_str:
                                ta_parts.append(f"Demographics: {demo_str}")
                        pain_points = target_audience.get("pain_points")
                        if pain_points:
                            ta_parts.append(f"Pain Points: {', '.join(pain_points)}")
                        desires = target_audience.get("desires_goals")
                        if desires:
                            ta_parts.append(f"Desires/Goals: {', '.join(desires)}")
                        if ta_parts:
                            prod_data["target_audience"] = "\n".join(ta_parts)

                    prod_result = self.supabase.table("products").insert(prod_data).execute()
                    created_product_id = prod_result.data[0]["id"]
                    product_ids.append(str(created_product_id))
                    logger.info(f"Created product: {prod['name']} ({created_product_id})")

                    # Save Amazon data if present (URL, reviews, analysis)
                    amazon_url = prod.get("amazon_url")
                    amazon_analysis = prod.get("amazon_analysis") or {}
                    if amazon_url:
                        self._save_amazon_data(
                            brand_id=brand_id,
                            product_id=UUID(created_product_id),
                            amazon_url=amazon_url,
                            amazon_analysis=amazon_analysis
                        )

                    # Save product images if present (from Amazon or landing page scraping)
                    product_images = prod.get("images") or []
                    if product_images:
                        self._save_product_images(
                            product_id=UUID(created_product_id),
                            image_urls=product_images
                        )

                    # Create offer variants for this product
                    offer_variants = prod.get("offer_variants") or []
                    if offer_variants:
                        for ov in offer_variants:
                            if ov.get("name") and ov.get("landing_page_url"):
                                ov_data = {
                                    "product_id": str(created_product_id),
                                    "name": ov["name"],
                                    "slug": self._slugify(ov["name"]),
                                    "landing_page_url": ov["landing_page_url"],
                                    "pain_points": ov.get("pain_points") or [],
                                    "desires_goals": ov.get("desires_goals") or [],
                                    "benefits": ov.get("benefits") or [],
                                    "disallowed_claims": ov.get("disallowed_claims") or [],
                                    "is_default": ov.get("is_default", False),
                                    "is_active": True,
                                }
                                if ov.get("target_audience"):
                                    ov_data["target_audience"] = ov["target_audience"]
                                if ov.get("required_disclaimers"):
                                    ov_data["required_disclaimers"] = ov["required_disclaimers"]

                                # Mechanism fields (UM/UMP/UMS) from ad/Amazon analysis
                                if ov.get("mechanism_name"):
                                    ov_data["mechanism_name"] = ov["mechanism_name"]
                                if ov.get("mechanism_problem"):
                                    ov_data["mechanism_problem"] = ov["mechanism_problem"]
                                if ov.get("mechanism_solution"):
                                    ov_data["mechanism_solution"] = ov["mechanism_solution"]
                                if ov.get("sample_hooks"):
                                    ov_data["sample_hooks"] = ov["sample_hooks"]

                                # Source tracking (ad_analysis, amazon_analysis, etc.)
                                if ov.get("source"):
                                    ov_data["source"] = ov["source"]
                                    source_meta = {}
                                    if ov.get("source_ad_count"):
                                        source_meta["ad_count"] = ov["source_ad_count"]
                                    if ov.get("source_review_count"):
                                        source_meta["review_count"] = ov["source_review_count"]
                                    if source_meta:
                                        ov_data["source_metadata"] = source_meta

                                self.supabase.table("product_offer_variants").insert(ov_data).execute()
                                logger.info(f"Created offer variant: {ov['name']} for product {prod['name']}")

                    # Synthesize benefits and pain points from all sources into product
                    self._synthesize_product_data(
                        product_id=UUID(created_product_id),
                        offer_variants=offer_variants,
                        amazon_analysis=amazon_analysis
                    )

            if product_ids:
                created["product_ids"] = product_ids

            # Create competitors
            competitors = session.get("competitors") or []
            competitor_ids = []
            for comp in competitors:
                if comp.get("name"):
                    comp_data = {
                        "brand_id": str(brand_id),
                        "name": comp["name"],
                    }

                    if comp.get("website_url"):
                        comp_data["website_url"] = comp["website_url"]
                    if comp.get("amazon_url"):
                        comp_data["amazon_url"] = comp["amazon_url"]
                    if comp.get("ad_library_url"):
                        comp_data["ad_library_url"] = comp["ad_library_url"]
                    if comp.get("facebook_page_url"):
                        page_id = self._extract_facebook_page_id(comp["facebook_page_url"])
                        if page_id:
                            comp_data["facebook_page_id"] = page_id

                    comp_result = self.supabase.table("competitors").insert(comp_data).execute()
                    created_competitor_id = UUID(comp_result.data[0]["id"])
                    competitor_ids.append(str(created_competitor_id))
                    logger.info(f"Created competitor: {comp['name']} ({created_competitor_id})")

                    # Save competitor Amazon data if present
                    if comp.get("amazon_url") and comp.get("amazon_analysis"):
                        self._save_competitor_amazon_data(
                            competitor_id=created_competitor_id,
                            brand_id=brand_id,
                            amazon_url=comp["amazon_url"],
                            amazon_analysis=comp["amazon_analysis"]
                        )

                    # Save competitor landing pages and ad messaging if present
                    url_groups = comp.get("url_groups") or []
                    ad_messaging = comp.get("ad_messaging") or {}
                    if url_groups:
                        self._save_competitor_landing_pages(
                            competitor_id=created_competitor_id,
                            brand_id=brand_id,
                            url_groups=url_groups,
                            ad_messaging=ad_messaging
                        )

                        # Import competitor Facebook ads
                        ads_imported = self._import_competitor_ads(
                            competitor_id=created_competitor_id,
                            brand_id=brand_id,
                            competitor_data=comp
                        )
                        if ads_imported > 0:
                            if "competitor_ads_imported" not in created:
                                created["competitor_ads_imported"] = 0
                            created["competitor_ads_imported"] += ads_imported

            if competitor_ids:
                created["competitor_ids"] = competitor_ids

        logger.info(f"Imported session {session_id} to production: {created}")
        return created

    def _save_amazon_data(
        self,
        brand_id: UUID,
        product_id: UUID,
        amazon_url: str,
        amazon_analysis: Dict[str, Any]
    ) -> None:
        """
        Save Amazon URL, reviews, and analysis to production tables.

        Creates:
        - amazon_product_urls entry linking product to Amazon
        - amazon_reviews entries for raw review data
        - amazon_review_analysis entry for AI analysis

        Args:
            brand_id: Brand UUID
            product_id: Product UUID
            amazon_url: Amazon product URL
            amazon_analysis: Analysis result from analyze_listing_for_onboarding
        """
        # Parse ASIN and domain from URL
        asin = None
        domain = "com"
        # Extract ASIN (10 char alphanumeric)
        import re
        asin_match = re.search(r'/(?:dp|product|gp/product)/([A-Z0-9]{10})', amazon_url, re.IGNORECASE)
        if asin_match:
            asin = asin_match.group(1).upper()

        # Extract domain
        domain_match = re.search(r'amazon\.([a-z.]+)/', amazon_url, re.IGNORECASE)
        if domain_match:
            domain = domain_match.group(1)

        if not asin:
            logger.warning(f"Could not extract ASIN from URL: {amazon_url}")
            return

        try:
            # Create amazon_product_urls entry
            url_data = {
                "product_id": str(product_id),
                "brand_id": str(brand_id),
                "amazon_url": amazon_url,
                "asin": asin,
                "domain_code": domain,
                "total_reviews_scraped": len(amazon_analysis.get("raw_reviews", [])),
            }
            url_result = self.supabase.table("amazon_product_urls").insert(url_data).execute()
            amazon_url_id = url_result.data[0]["id"]
            logger.info(f"Created amazon_product_urls entry for ASIN {asin}")

            # Save raw reviews
            raw_reviews = amazon_analysis.get("raw_reviews", [])
            if raw_reviews:
                reviews_saved = 0
                for review in raw_reviews:
                    # Get review_id - Axesso returns as 'id' or 'reviewId'
                    review_id = review.get("id") or review.get("reviewId") or review.get("review_id")
                    if not review_id:
                        continue

                    review_data = {
                        "amazon_product_url_id": str(amazon_url_id),
                        "product_id": str(product_id),
                        "brand_id": str(brand_id),
                        "review_id": str(review_id),
                        "asin": asin,
                        "rating": review.get("rating"),
                        "title": review.get("title", "")[:500] if review.get("title") else None,
                        "body": review.get("text") or review.get("body"),
                        "author": review.get("author", "Anonymous"),
                        "verified_purchase": review.get("verifiedPurchase") or review.get("verified_purchase", False),
                        "helpful_votes": review.get("helpfulVotes") or review.get("helpful_votes") or 0,
                        "scrape_source": "onboarding",
                    }

                    # Parse review date if present
                    date_str = review.get("date") or review.get("reviewDate")
                    if date_str:
                        try:
                            from dateutil import parser
                            review_data["review_date"] = parser.parse(date_str).date()
                        except Exception:
                            pass

                    try:
                        self.supabase.table("amazon_reviews").upsert(
                            review_data,
                            on_conflict="review_id,asin"
                        ).execute()
                        reviews_saved += 1
                    except Exception as e:
                        # Skip duplicates or errors
                        logger.debug(f"Could not save review {review_id}: {e}")

                logger.info(f"Saved {reviews_saved}/{len(raw_reviews)} reviews to amazon_reviews")

            # Save rich analysis if present
            rich_analysis = amazon_analysis.get("rich_analysis")
            messaging = amazon_analysis.get("messaging", {})
            if rich_analysis or messaging:
                analysis_data = {
                    "product_id": str(product_id),
                    "brand_id": str(brand_id),
                    "total_reviews_analyzed": len(raw_reviews),
                    "model_used": "claude-sonnet-4-20250514",  # Default model used
                }

                # Store pain points in the structured format expected by Brand Research UI
                # Format: {"themes": [...], "jobs_to_be_done": [...], "product_issues": [...]}
                pain_themes = []
                if rich_analysis and rich_analysis.get("pain_points"):
                    pain_themes = rich_analysis["pain_points"]
                elif messaging.get("pain_points"):
                    pain_themes = [
                        {"theme": p, "score": 5.0, "quotes": []}
                        for p in messaging["pain_points"]
                    ]

                jobs_to_be_done = rich_analysis.get("jobs_to_be_done", []) if rich_analysis else []
                product_issues = rich_analysis.get("product_issues", []) if rich_analysis else []

                if pain_themes or jobs_to_be_done or product_issues:
                    analysis_data["pain_points"] = {
                        "themes": pain_themes,
                        "jobs_to_be_done": jobs_to_be_done,
                        "product_issues": product_issues
                    }

                # Store desires in structured format
                desire_themes = []
                if rich_analysis and rich_analysis.get("desired_outcomes"):
                    desire_themes = rich_analysis["desired_outcomes"]
                elif messaging.get("desires_goals"):
                    desire_themes = [
                        {"theme": d, "score": 5.0, "quotes": []}
                        for d in messaging["desires_goals"]
                    ]

                if desire_themes:
                    analysis_data["desires"] = {"themes": desire_themes}

                # Store objections in structured format
                if rich_analysis and rich_analysis.get("buying_objections"):
                    analysis_data["objections"] = {"themes": rich_analysis["buying_objections"]}

                # Store customer language/quotes
                if messaging.get("customer_language"):
                    analysis_data["top_positive_quotes"] = [
                        q["quote"] for q in messaging["customer_language"]
                        if q.get("rating", 0) >= 4
                    ][:10]
                    analysis_data["top_negative_quotes"] = [
                        q["quote"] for q in messaging["customer_language"]
                        if q.get("rating", 0) <= 2
                    ][:10]

                try:
                    self.supabase.table("amazon_review_analysis").upsert(
                        analysis_data,
                        on_conflict="product_id"
                    ).execute()
                    logger.info(f"Saved amazon_review_analysis for product {product_id}")
                except Exception as e:
                    logger.warning(f"Could not save amazon_review_analysis: {e}")

        except Exception as e:
            logger.error(f"Failed to save Amazon data: {e}")
            import traceback
            logger.error(traceback.format_exc())

    def _save_product_images(
        self,
        product_id: UUID,
        image_urls: List[str]
    ) -> int:
        """
        Download product images from URLs and save to Supabase Storage.

        Downloads images from Amazon CDN (or other URLs), uploads to the
        product-images bucket in Supabase Storage, and creates product_images
        records in the database.

        Args:
            product_id: Product UUID to associate images with
            image_urls: List of image URLs to download

        Returns:
            Number of images successfully saved
        """
        if not image_urls:
            return 0

        BUCKET = "product-images"
        saved_count = 0

        for idx, url in enumerate(image_urls):
            try:
                # Download image from URL
                response = requests.get(url, timeout=30, headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
                })
                response.raise_for_status()

                # Determine content type and extension
                content_type = response.headers.get("Content-Type", "image/jpeg")
                if "jpeg" in content_type or "jpg" in content_type:
                    ext = "jpg"
                elif "png" in content_type:
                    ext = "png"
                elif "webp" in content_type:
                    ext = "webp"
                elif "gif" in content_type:
                    ext = "gif"
                else:
                    # Try to extract from URL
                    parsed = urlparse(url)
                    path_ext = parsed.path.split(".")[-1].lower()
                    ext = path_ext if path_ext in ["jpg", "jpeg", "png", "webp", "gif"] else "jpg"
                    if ext == "jpeg":
                        ext = "jpg"

                # Generate storage path
                filename = f"image_{idx + 1:02d}.{ext}"
                storage_path = f"{product_id}/{filename}"
                full_storage_path = f"{BUCKET}/{storage_path}"

                # Upload to Supabase Storage
                self.supabase.storage.from_(BUCKET).upload(
                    storage_path,
                    response.content,
                    {"content-type": content_type, "upsert": "true"}
                )

                # Create product_images record
                image_record = {
                    "product_id": str(product_id),
                    "storage_path": full_storage_path,
                    "filename": filename,
                    "is_main": idx == 0,  # First image is main
                    "sort_order": idx + 1,
                    "notes": f"Imported from Amazon (original URL: {url[:100]}...)" if len(url) > 100 else f"Imported from Amazon (original URL: {url})"
                }

                # Check if record already exists
                existing = self.supabase.table("product_images").select("id").eq(
                    "product_id", str(product_id)
                ).eq("storage_path", full_storage_path).execute()

                if existing.data:
                    self.supabase.table("product_images").update(image_record).eq(
                        "id", existing.data[0]["id"]
                    ).execute()
                else:
                    self.supabase.table("product_images").insert(image_record).execute()

                saved_count += 1
                logger.info(f"Saved product image {idx + 1}/{len(image_urls)}: {full_storage_path}")

            except requests.RequestException as e:
                logger.warning(f"Failed to download image {idx + 1} from {url[:50]}...: {e}")
            except Exception as e:
                logger.warning(f"Failed to save product image {idx + 1}: {e}")

        logger.info(f"Saved {saved_count}/{len(image_urls)} product images for product {product_id}")
        return saved_count

    def _synthesize_product_data(
        self,
        product_id: UUID,
        offer_variants: List[Dict[str, Any]],
        amazon_analysis: Dict[str, Any]
    ) -> None:
        """
        Synthesize benefits, USPs, and pain points from all sources into the product record.

        Aggregates data from:
        - Offer variants (landing page analysis)
        - Amazon review analysis (customer voice)

        Updates the products table with synthesized data for ad creation.

        Args:
            product_id: Product UUID to update
            offer_variants: List of offer variant dicts with benefits, pain_points
            amazon_analysis: Amazon analysis dict with messaging, rich_analysis
        """
        all_benefits = []
        all_pain_points = []

        # Collect from offer variants
        for ov in offer_variants:
            benefits = ov.get("benefits") or []
            all_benefits.extend(benefits)
            pain_points = ov.get("pain_points") or []
            all_pain_points.extend(pain_points)

        # Collect from Amazon analysis
        if amazon_analysis:
            # From messaging (direct extraction)
            messaging = amazon_analysis.get("messaging") or {}
            all_benefits.extend(messaging.get("benefits") or [])
            all_pain_points.extend(messaging.get("pain_points") or [])

            # From rich_analysis (deeper analysis)
            rich = amazon_analysis.get("rich_analysis") or {}
            # desired_outcomes can be treated as benefits
            all_benefits.extend(rich.get("desired_outcomes") or [])
            all_pain_points.extend(rich.get("pain_points") or [])

        # Deduplicate while preserving order (first occurrence wins)
        # Handle both string and dict formats (some sources store as dicts)
        seen_benefits = set()
        unique_benefits = []
        for b in all_benefits:
            # Extract string from dict if needed
            if isinstance(b, dict):
                b = b.get("text") or b.get("benefit") or b.get("description") or str(b)
            if not isinstance(b, str):
                continue
            b_lower = b.lower().strip()
            if b_lower not in seen_benefits and len(b.strip()) > 5:
                seen_benefits.add(b_lower)
                unique_benefits.append(b.strip())

        seen_pain = set()
        unique_pain_points = []
        for p in all_pain_points:
            # Extract string from dict if needed
            if isinstance(p, dict):
                p = p.get("text") or p.get("pain_point") or p.get("description") or str(p)
            if not isinstance(p, str):
                continue
            p_lower = p.lower().strip()
            if p_lower not in seen_pain and len(p.strip()) > 5:
                seen_pain.add(p_lower)
                unique_pain_points.append(p.strip())

        # Update product if we have data
        update_data = {}
        if unique_benefits:
            # Take top 10 benefits for the product record
            update_data["benefits"] = unique_benefits[:10]
            # Use first few benefits as USPs if none exist
            update_data["unique_selling_points"] = unique_benefits[:5]

        # Store pain points in target_audience field (append to existing)
        if unique_pain_points:
            # Get existing target_audience
            existing = self.supabase.table("products").select("target_audience").eq(
                "id", str(product_id)
            ).execute()
            existing_ta = existing.data[0].get("target_audience") or "" if existing.data else ""

            # Append pain points if not already present
            pain_section = f"\n\nPain Points (from research):\n• " + "\n• ".join(unique_pain_points[:10])
            if "Pain Points (from research)" not in existing_ta:
                update_data["target_audience"] = existing_ta + pain_section

        if update_data:
            self.supabase.table("products").update(update_data).eq(
                "id", str(product_id)
            ).execute()
            logger.info(
                f"Synthesized product data: {len(unique_benefits)} benefits, "
                f"{len(unique_pain_points)} pain points for product {product_id}"
            )

    def _save_competitor_amazon_data(
        self,
        competitor_id: UUID,
        brand_id: UUID,
        amazon_url: str,
        amazon_analysis: Dict[str, Any]
    ) -> None:
        """
        Save competitor Amazon URL, reviews, and analysis to production tables.

        Creates:
        - competitor_amazon_urls entry
        - competitor_amazon_reviews entries
        - competitor_amazon_review_analysis entry

        Args:
            competitor_id: Competitor UUID
            brand_id: Brand UUID
            amazon_url: Amazon product URL
            amazon_analysis: Analysis result from analyze_listing_for_onboarding
        """
        import re

        # Parse ASIN and domain from URL
        asin = None
        domain = "com"
        asin_match = re.search(r'/(?:dp|product|gp/product)/([A-Z0-9]{10})', amazon_url, re.IGNORECASE)
        if asin_match:
            asin = asin_match.group(1).upper()

        domain_match = re.search(r'amazon\.([a-z.]+)/', amazon_url, re.IGNORECASE)
        if domain_match:
            domain = domain_match.group(1)

        if not asin:
            logger.warning(f"Could not extract ASIN from competitor URL: {amazon_url}")
            return

        try:
            # Create competitor_amazon_urls entry
            url_data = {
                "competitor_id": str(competitor_id),
                "brand_id": str(brand_id),
                "amazon_url": amazon_url,
                "asin": asin,
                "domain_code": domain,
                "total_reviews_scraped": len(amazon_analysis.get("raw_reviews", [])),
            }
            url_result = self.supabase.table("competitor_amazon_urls").insert(url_data).execute()
            amazon_url_id = url_result.data[0]["id"]
            logger.info(f"Created competitor_amazon_urls entry for ASIN {asin}")

            # Save raw reviews
            raw_reviews = amazon_analysis.get("raw_reviews", [])
            if raw_reviews:
                reviews_saved = 0
                for review in raw_reviews:
                    review_id = review.get("id") or review.get("reviewId") or review.get("review_id")
                    if not review_id:
                        continue

                    review_data = {
                        "competitor_amazon_url_id": str(amazon_url_id),
                        "competitor_id": str(competitor_id),
                        "brand_id": str(brand_id),
                        "review_id": str(review_id),
                        "asin": asin,
                        "rating": review.get("rating"),
                        "title": review.get("title", "")[:500] if review.get("title") else None,
                        "body": review.get("text") or review.get("body"),
                        "author": review.get("author", "Anonymous"),
                        "verified_purchase": review.get("verifiedPurchase") or review.get("verified_purchase", False),
                        "helpful_votes": review.get("helpfulVotes") or review.get("helpful_votes") or 0,
                    }

                    # Parse review date if present
                    date_str = review.get("date") or review.get("reviewDate")
                    if date_str:
                        try:
                            from dateutil import parser
                            review_data["review_date"] = parser.parse(date_str).date()
                        except Exception:
                            pass

                    try:
                        self.supabase.table("competitor_amazon_reviews").upsert(
                            review_data,
                            on_conflict="review_id,asin"
                        ).execute()
                        reviews_saved += 1
                    except Exception as e:
                        logger.debug(f"Could not save competitor review {review_id}: {e}")

                logger.info(f"Saved {reviews_saved}/{len(raw_reviews)} competitor reviews")

            # Save analysis
            messaging = amazon_analysis.get("messaging", {})
            rich_analysis = amazon_analysis.get("rich_analysis")
            if messaging or rich_analysis:
                analysis_data = {
                    "competitor_id": str(competitor_id),
                    "brand_id": str(brand_id),
                    "total_reviews_analyzed": len(raw_reviews),
                    "model_used": "claude-sonnet-4-20250514",
                }

                # Store pain points in structured format
                pain_themes = []
                if rich_analysis and rich_analysis.get("pain_points"):
                    pain_themes = rich_analysis["pain_points"]
                elif messaging.get("pain_points"):
                    pain_themes = [
                        {"theme": p, "score": 5.0, "quotes": []}
                        for p in messaging["pain_points"]
                    ]

                jobs_to_be_done = rich_analysis.get("jobs_to_be_done", []) if rich_analysis else []
                product_issues = rich_analysis.get("product_issues", []) if rich_analysis else []

                if pain_themes or jobs_to_be_done or product_issues:
                    analysis_data["pain_points"] = {
                        "themes": pain_themes,
                        "jobs_to_be_done": jobs_to_be_done,
                        "product_issues": product_issues
                    }

                # Store desires in structured format
                desire_themes = []
                if rich_analysis and rich_analysis.get("desired_outcomes"):
                    desire_themes = rich_analysis["desired_outcomes"]
                elif messaging.get("desires_goals"):
                    desire_themes = [
                        {"theme": d, "score": 5.0, "quotes": []}
                        for d in messaging["desires_goals"]
                    ]

                if desire_themes:
                    analysis_data["desires"] = {"themes": desire_themes}

                if messaging.get("customer_language"):
                    analysis_data["top_positive_quotes"] = [
                        q["quote"] for q in messaging["customer_language"]
                        if q.get("rating", 0) >= 4
                    ][:10]
                    analysis_data["top_negative_quotes"] = [
                        q["quote"] for q in messaging["customer_language"]
                        if q.get("rating", 0) <= 2
                    ][:10]

                try:
                    self.supabase.table("competitor_amazon_review_analysis").upsert(
                        analysis_data,
                        on_conflict="competitor_id"
                    ).execute()
                    logger.info(f"Saved competitor_amazon_review_analysis for {competitor_id}")
                except Exception as e:
                    logger.warning(f"Could not save competitor analysis: {e}")

        except Exception as e:
            logger.error(f"Failed to save competitor Amazon data: {e}")
            import traceback
            logger.error(traceback.format_exc())

    def _save_competitor_landing_pages(
        self,
        competitor_id: UUID,
        brand_id: UUID,
        url_groups: List[Dict[str, Any]],
        ad_messaging: Dict[str, Any]
    ) -> None:
        """
        Save competitor landing pages and ad messaging to production tables.

        Creates:
        - competitor_landing_pages entries for each URL group
        - Stores ad_messaging analysis on the landing pages

        Args:
            competitor_id: Competitor UUID
            brand_id: Brand UUID
            url_groups: List of URL groups from ad scraping
            ad_messaging: Synthesized messaging from ad analysis
        """
        try:
            for group in url_groups:
                landing_page_url = group.get("display_url") or group.get("normalized_url")
                if not landing_page_url:
                    continue

                page_data = {
                    "competitor_id": str(competitor_id),
                    "brand_id": str(brand_id),
                    "url": landing_page_url,
                    "ad_count": group.get("ad_count", 0),
                }

                # If this is the primary landing page, attach the ad_messaging
                if ad_messaging and group.get("ad_count", 0) == max(
                    g.get("ad_count", 0) for g in url_groups
                ):
                    page_data["analysis_data"] = {
                        "source": "ad_analysis",
                        "pain_points": ad_messaging.get("pain_points", []),
                        "desires": ad_messaging.get("desires", []),
                        "benefits": ad_messaging.get("benefits", []),
                        "hooks": ad_messaging.get("hooks", []),
                        "claims": ad_messaging.get("claims", []),
                    }
                    page_data["analyzed_at"] = datetime.utcnow().isoformat()

                try:
                    self.supabase.table("competitor_landing_pages").upsert(
                        page_data,
                        on_conflict="competitor_id,url"
                    ).execute()
                except Exception as e:
                    # Try insert if upsert fails (constraint might not exist)
                    try:
                        self.supabase.table("competitor_landing_pages").insert(page_data).execute()
                    except Exception as e2:
                        logger.debug(f"Could not save landing page {landing_page_url}: {e2}")

            logger.info(f"Saved {len(url_groups)} competitor landing pages")

        except Exception as e:
            logger.error(f"Failed to save competitor landing pages: {e}")
            import traceback
            logger.error(traceback.format_exc())

    def _import_brand_facebook_ads(
        self,
        brand_id: UUID,
        facebook_meta: Dict[str, Any]
    ) -> int:
        """
        Import scraped Facebook ads from onboarding session to production tables.

        Creates:
        - facebook_ads entries for each ad
        - brand_facebook_ads linking records

        Args:
            brand_id: Brand UUID
            facebook_meta: facebook_meta section from session containing url_groups with ads

        Returns:
            Number of ads imported
        """
        url_groups = facebook_meta.get("url_groups") or []
        if not url_groups:
            logger.info("No URL groups found in facebook_meta, skipping ad import")
            return 0

        # Get Facebook platform ID
        platform_result = self.supabase.table("platforms").select("id").eq(
            "slug", "facebook"
        ).single().execute()
        if not platform_result.data:
            logger.warning("Facebook platform not found, skipping ad import")
            return 0
        platform_id = platform_result.data["id"]

        # Extract page_id from facebook_meta
        page_id = facebook_meta.get("page_id")
        if not page_id and facebook_meta.get("ad_library_url"):
            page_id = self._extract_facebook_page_id(facebook_meta["ad_library_url"])

        imported_count = 0

        for group in url_groups:
            ads = group.get("ads") or []
            for ad in ads:
                try:
                    ad_archive_id = ad.get("ad_archive_id") or ad.get("adArchiveID")
                    if not ad_archive_id:
                        continue

                    # Check if ad already exists
                    existing = self.supabase.table("facebook_ads").select("id").eq(
                        "ad_archive_id", str(ad_archive_id)
                    ).execute()

                    if existing.data:
                        # Ad exists, just create linking record
                        ad_uuid = existing.data[0]["id"]
                    else:
                        # Create new facebook_ads record
                        import json

                        ad_data = {
                            "ad_archive_id": str(ad_archive_id),
                            "platform_id": platform_id,
                            "brand_id": str(brand_id),
                            "page_id": str(ad.get("page_id") or page_id or ""),
                            "page_name": ad.get("page_name") or "",
                            "ad_id": str(ad.get("ad_id") or ""),
                            "is_active": ad.get("is_active", False),
                            "scraped_at": datetime.utcnow().isoformat(),
                            "import_source": "client_onboarding",
                        }

                        # Handle snapshot - could be string or dict
                        snapshot = ad.get("snapshot")
                        if snapshot:
                            if isinstance(snapshot, str):
                                try:
                                    ad_data["snapshot"] = json.loads(snapshot)
                                except json.JSONDecodeError:
                                    ad_data["snapshot"] = {"raw": snapshot}
                            else:
                                ad_data["snapshot"] = snapshot

                        # Add date fields
                        if ad.get("start_date"):
                            ad_data["start_date"] = ad["start_date"]
                        if ad.get("end_date"):
                            ad_data["end_date"] = ad["end_date"]

                        # Insert the ad
                        ad_result = self.supabase.table("facebook_ads").insert(ad_data).execute()
                        ad_uuid = ad_result.data[0]["id"]

                    # Create brand_facebook_ads linking record
                    try:
                        self.supabase.table("brand_facebook_ads").upsert(
                            {
                                "brand_id": str(brand_id),
                                "ad_id": str(ad_uuid),
                                "import_method": "client_onboarding",
                                "notes": f"Imported from onboarding session",
                            },
                            on_conflict="brand_id,ad_id"
                        ).execute()
                    except Exception as e:
                        logger.debug(f"Could not create brand_facebook_ads link: {e}")

                    imported_count += 1

                except Exception as e:
                    logger.warning(f"Failed to import ad {ad.get('ad_archive_id')}: {e}")

        logger.info(f"Imported {imported_count} Facebook ads for brand {brand_id}")
        return imported_count

    def _import_competitor_ads(
        self,
        competitor_id: UUID,
        brand_id: UUID,
        competitor_data: Dict[str, Any]
    ) -> int:
        """
        Import scraped Facebook ads from competitor data to production tables.

        Creates:
        - competitor_ads entries for each ad
        - competitor_ad_assets entries for media

        Args:
            competitor_id: Competitor UUID
            brand_id: Brand UUID
            competitor_data: Competitor dict from session containing url_groups with ads

        Returns:
            Number of ads imported
        """
        url_groups = competitor_data.get("url_groups") or []
        if not url_groups:
            return 0

        imported_count = 0

        for group in url_groups:
            ads = group.get("ads") or []
            landing_page_url = group.get("display_url") or group.get("normalized_url")

            for ad in ads:
                try:
                    ad_archive_id = ad.get("ad_archive_id") or ad.get("adArchiveID")
                    if not ad_archive_id:
                        continue

                    # Check if ad already exists
                    existing = self.supabase.table("competitor_ads").select("id").eq(
                        "competitor_id", str(competitor_id)
                    ).eq("ad_archive_id", str(ad_archive_id)).execute()

                    if existing.data:
                        # Ad already exists
                        imported_count += 1
                        continue

                    # Parse snapshot for copy/creative data
                    import json
                    snapshot = ad.get("snapshot") or {}
                    if isinstance(snapshot, str):
                        try:
                            snapshot = json.loads(snapshot)
                        except json.JSONDecodeError:
                            snapshot = {}

                    # Extract copy from snapshot
                    ad_body = None
                    ad_title = None
                    cta_text = None
                    if snapshot:
                        cards = snapshot.get("cards") or []
                        if cards:
                            first_card = cards[0]
                            ad_body = first_card.get("body")
                            ad_title = first_card.get("title")
                            cta_text = first_card.get("cta_text")
                        if not ad_body:
                            ad_body = snapshot.get("body_markup") or snapshot.get("body")
                        if not ad_title:
                            ad_title = snapshot.get("title")

                    # Create competitor_ads record
                    ad_data = {
                        "competitor_id": str(competitor_id),
                        "ad_archive_id": str(ad_archive_id),
                        "page_name": ad.get("page_name") or competitor_data.get("name", ""),
                        "ad_body": ad_body,
                        "ad_title": ad_title,
                        "link_url": landing_page_url,
                        "cta_text": cta_text,
                        "is_active": ad.get("is_active", False),
                        "snapshot_data": snapshot,
                    }

                    # Add dates
                    if ad.get("start_date"):
                        ad_data["started_running"] = ad["start_date"]

                    # Add platforms
                    platforms = ad.get("publisher_platform")
                    if platforms:
                        if isinstance(platforms, str):
                            try:
                                platforms = json.loads(platforms)
                            except json.JSONDecodeError:
                                platforms = [platforms]
                        ad_data["platforms"] = platforms

                    self.supabase.table("competitor_ads").insert(ad_data).execute()
                    imported_count += 1

                except Exception as e:
                    logger.warning(f"Failed to import competitor ad {ad.get('ad_archive_id')}: {e}")

        # Update competitor ads_count
        if imported_count > 0:
            try:
                self.supabase.table("competitors").update(
                    {"ads_count": imported_count}
                ).eq("id", str(competitor_id)).execute()
            except Exception as e:
                logger.debug(f"Could not update competitor ads_count: {e}")

        logger.info(f"Imported {imported_count} competitor ads for {competitor_id}")
        return imported_count
