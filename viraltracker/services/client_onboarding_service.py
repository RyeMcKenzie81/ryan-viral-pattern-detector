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
from uuid import UUID

from supabase import Client

from ..core.database import get_supabase_client

logger = logging.getLogger(__name__)


# ============================================
# FIELD CONFIGURATION
# ============================================

REQUIRED_FIELDS = {
    "brand_basics": ["name", "website_url"],
    "facebook_meta": ["page_url", "ad_library_url"],
    "products": [],  # Special handling: at least 1 product with name
    "competitors": [],
    "target_audience": ["pain_points", "desires_goals"],
}

NICE_TO_HAVE_FIELDS = {
    "brand_basics": ["logo_storage_path", "brand_voice"],
    "facebook_meta": ["ad_account_id"],
    "products": [],  # Special handling: product details (amazon, dimensions, etc.)
    "competitors": ["competitors"],
    "target_audience": ["demographics"],
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
                    competitor_ids.append(str(comp_result.data[0]["id"]))
                    logger.info(f"Created competitor: {comp['name']}")

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

                # Store pain points from rich analysis
                if rich_analysis and rich_analysis.get("pain_points"):
                    analysis_data["pain_points"] = rich_analysis["pain_points"]
                elif messaging.get("pain_points"):
                    analysis_data["pain_points"] = [
                        {"theme": p, "score": 5.0, "quotes": []}
                        for p in messaging["pain_points"]
                    ]

                # Store desires
                if rich_analysis and rich_analysis.get("desired_outcomes"):
                    analysis_data["desires"] = rich_analysis["desired_outcomes"]
                elif messaging.get("desires_goals"):
                    analysis_data["desires"] = [
                        {"theme": d, "score": 5.0, "quotes": []}
                        for d in messaging["desires_goals"]
                    ]

                # Store objections
                if rich_analysis and rich_analysis.get("buying_objections"):
                    analysis_data["objections"] = rich_analysis["buying_objections"]

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
