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
    "amazon_data": [],
    "product_assets": [],
    "competitors": [],
    "target_audience": ["pain_points", "desires_goals"],
}

NICE_TO_HAVE_FIELDS = {
    "brand_basics": ["logo_storage_path", "brand_voice"],
    "facebook_meta": ["ad_account_id"],
    "amazon_data": ["products"],
    "product_assets": ["images", "dimensions", "weight"],
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
    "amazon_data",
    "product_assets",
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

        # Check required fields
        for section, fields in REQUIRED_FIELDS.items():
            section_data = session.get(section) or {}
            for field in fields:
                required_total += 1
                if self._field_has_value(section_data, field):
                    required_filled += 1
                else:
                    missing_required.append(f"{section}.{field}")

        # Check nice-to-have fields
        for section, fields in NICE_TO_HAVE_FIELDS.items():
            section_data = session.get(section) or {}
            for field in fields:
                nice_to_have_total += 1
                if self._field_has_value(section_data, field):
                    nice_to_have_filled += 1
                else:
                    missing_nice_to_have.append(f"{section}.{field}")

        # Special handling for competitors and amazon products (array fields)
        competitors = session.get("competitors") or []
        if competitors:
            # Remove from missing if we have competitors
            if "competitors.competitors" in missing_nice_to_have:
                missing_nice_to_have.remove("competitors.competitors")
                nice_to_have_filled += 1

        amazon_data = session.get("amazon_data") or {}
        if amazon_data.get("products"):
            if "amazon_data.products" in missing_nice_to_have:
                missing_nice_to_have.remove("amazon_data.products")
                nice_to_have_filled += 1

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
                "amazon_data": self._summarize_section(
                    session.get("amazon_data") or {},
                    ["products"],
                ),
                "product_assets": self._summarize_section(
                    session.get("product_assets") or {},
                    ["images", "dimensions", "weight"],
                ),
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
        Import session data to production tables (brands, competitors).

        Creates:
        - Brand record from brand_basics
        - Competitor records from competitors array

        Args:
            session_id: Session UUID

        Returns:
            Dict with created IDs: {"brand_id": UUID, "competitor_ids": [...]}

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
