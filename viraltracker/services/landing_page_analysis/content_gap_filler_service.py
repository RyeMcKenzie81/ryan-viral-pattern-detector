"""
ContentGapFillerService — Fill brand profile gaps detected during blueprint generation.

Provides three fill modes:
1. Manual entry: User types a value directly
2. From sources: Pre-extracted candidates from cached data (Amazon reviews, brand LPs, etc.)
3. AI suggestion: LLM-powered extraction with evidence and confidence

Every save records provenance in content_field_events for audit trail.

GapKey convention: <entity>.<field_path> — e.g. "product.guarantee", "offer_variant.mechanism.name"
"""

import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

from viraltracker.services.landing_page_analysis.chunk_markdown import (
    chunk_markdown,
    pick_chunks_for_fields,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class GapFieldSpec:
    """Specification for a single gap field in the registry."""
    key: str                    # e.g. "product.guarantee" — <entity>.<field_path>
    table: str                  # e.g. "products"
    column: Optional[str]       # e.g. "guarantee" (None for complex / needs_setup)
    entity: str                 # "brand" | "product" | "offer_variant"
    value_type: str             # "text" | "text_list" | "qa_list" | "timeline_list" | "json_array" | "json" | "quote_list" | "complex"
    auto_fillable: bool         # True = included in Fix All; False = manual or needs_setup
    needs_setup: bool           # True = complex field, show badge + deep link only
    sources: List[str]          # ["brand_landing_pages", "fresh_scrape"]
    write_policy: str           # "allow_if_empty" | "confirm_overwrite" | "append"
    display_name: str           # "Guarantee Text"
    manual_entry_link: str      # "/Brand_Manager#guarantee" deep link


@dataclass
class SourceCandidate:
    """A pre-extracted candidate value from a data source."""
    source_type: str          # "brand_landing_pages", "amazon_review_analysis", etc.
    source_table: str         # table name for provenance
    source_id: Optional[str]  # row ID in source table (nullable for fresh scrape)
    extracted_value: Any      # pre-extracted value ready to save
    snippets: List[str]       # 1-3 supporting snippets with context
    url: Optional[str]        # source URL if available
    scraped_at: Optional[str] # when source data was last refreshed
    confidence: str           # "high" | "medium" | "low"


@dataclass
class ApplyResult:
    """Result of applying a value to a gap field."""
    success: bool
    action: str               # "set" | "overwrite" | "append" | "no_change"
    old_value: Any
    new_value: Any
    needs_confirmation: bool  # True if write policy requires user confirmation


# ---------------------------------------------------------------------------
# Gap Field Registry
# ---------------------------------------------------------------------------

GAP_FIELD_REGISTRY: Dict[str, GapFieldSpec] = {
    "brand.voice_tone": GapFieldSpec(
        key="brand.voice_tone", table="brands", column="brand_voice_tone",
        entity="brand", value_type="text", auto_fillable=True, needs_setup=False,
        sources=["brand_landing_pages", "fresh_scrape"],
        write_policy="confirm_overwrite", display_name="Brand Voice/Tone",
        manual_entry_link="/Brand_Manager#voice-tone",
    ),
    "product.guarantee": GapFieldSpec(
        key="product.guarantee", table="products", column="guarantee",
        entity="product", value_type="text", auto_fillable=True, needs_setup=False,
        sources=["brand_landing_pages", "fresh_scrape"],
        write_policy="allow_if_empty", display_name="Guarantee Text",
        manual_entry_link="/Brand_Manager#guarantee",
    ),
    "product.ingredients": GapFieldSpec(
        key="product.ingredients", table="products", column="ingredients",
        entity="product", value_type="json_array",
        auto_fillable=True, needs_setup=False,
        sources=["brand_landing_pages", "fresh_scrape"],
        write_policy="allow_if_empty", display_name="Ingredients",
        manual_entry_link="/Brand_Manager#ingredients",
    ),
    "product.results_timeline": GapFieldSpec(
        key="product.results_timeline", table="products", column="results_timeline",
        entity="product", value_type="timeline_list",
        auto_fillable=True, needs_setup=False,
        sources=["amazon_review_analysis", "fresh_scrape"],
        write_policy="allow_if_empty", display_name="Results Timeline",
        manual_entry_link="/Brand_Manager#results-timeline",
    ),
    "product.faq_items": GapFieldSpec(
        key="product.faq_items", table="products", column="faq_items",
        entity="product", value_type="qa_list",
        auto_fillable=True, needs_setup=False,
        sources=["brand_landing_pages", "fresh_scrape"],
        write_policy="allow_if_empty", display_name="FAQ Items",
        manual_entry_link="/Brand_Manager#faq",
    ),
    "offer_variant.mechanism.name": GapFieldSpec(
        key="offer_variant.mechanism.name", table="product_offer_variants",
        column="mechanism_name",
        entity="offer_variant", value_type="text", auto_fillable=True, needs_setup=False,
        sources=["brand_landing_pages", "fresh_scrape"],
        write_policy="confirm_overwrite", display_name="Mechanism Name",
        manual_entry_link="/Brand_Manager#mechanism",
    ),
    "offer_variant.mechanism.root_cause": GapFieldSpec(
        key="offer_variant.mechanism.root_cause", table="product_offer_variants",
        column="mechanism_problem",
        entity="offer_variant", value_type="text", auto_fillable=True, needs_setup=False,
        sources=["brand_landing_pages", "fresh_scrape", "amazon_review_analysis"],
        write_policy="confirm_overwrite", display_name="Mechanism Root Cause",
        manual_entry_link="/Brand_Manager#mechanism",
    ),
    "offer_variant.pain_points": GapFieldSpec(
        key="offer_variant.pain_points", table="product_offer_variants",
        column="pain_points",
        entity="offer_variant", value_type="text_list",
        auto_fillable=True, needs_setup=False,
        sources=["amazon_review_analysis", "reddit_sentiment_quotes", "brand_landing_pages"],
        write_policy="append", display_name="Pain Points",
        manual_entry_link="/Brand_Manager#pain-points",
    ),
    "product.top_positive_quotes": GapFieldSpec(
        key="product.top_positive_quotes", table="amazon_review_analysis",
        column="top_positive_quotes",
        entity="product", value_type="quote_list",
        auto_fillable=False, needs_setup=False,
        sources=["amazon_review_analysis"],
        write_policy="allow_if_empty", display_name="Customer Testimonials",
        manual_entry_link="/Brand_Manager#amazon-reviews",
    ),
    "product.review_platforms": GapFieldSpec(
        key="product.review_platforms", table="products", column="review_platforms",
        entity="product", value_type="json",
        auto_fillable=False, needs_setup=False, sources=[],
        write_policy="confirm_overwrite", display_name="Review Platform Ratings",
        manual_entry_link="/Brand_Manager#social-proof",
    ),
    # --- "Needs Setup" fields ---
    "product.pricing": GapFieldSpec(
        key="product.pricing", table="product_variants", column=None,
        entity="product", value_type="complex",
        auto_fillable=False, needs_setup=True, sources=[],
        write_policy="confirm_overwrite", display_name="Product Pricing",
        manual_entry_link="/Brand_Manager#variants",
    ),
    "product.personas": GapFieldSpec(
        key="product.personas", table="personas_4d", column=None,
        entity="product", value_type="complex",
        auto_fillable=False, needs_setup=True, sources=[],
        write_policy="confirm_overwrite", display_name="Customer Personas",
        manual_entry_link="/Personas",
    ),
    "product.name": GapFieldSpec(
        key="product.name", table="products", column="name",
        entity="product", value_type="text",
        auto_fillable=False, needs_setup=True, sources=[],
        write_policy="confirm_overwrite", display_name="Product Name",
        manual_entry_link="/Brand_Manager#product",
    ),
}

# Map from brand_profile gap field names to gap keys
_GAP_FIELD_TO_KEY = {
    "voice_tone": "brand.voice_tone",
    "name": "product.name",
    "guarantee": "product.guarantee",
    "text": "product.guarantee",  # gap section = "guarantee", field = "text"
    "ingredients": "product.ingredients",
    "results_timeline": "product.results_timeline",
    "faq_items": "product.faq_items",
    "review_platforms": "product.review_platforms",
    "top_positive_quotes": "product.top_positive_quotes",
    "pricing": "product.pricing",
    "personas": "product.personas",
    "pain_points": "offer_variant.pain_points",
}

# More specific mapping using (section, field) tuples for disambiguation
_GAP_SECTION_FIELD_TO_KEY = {
    ("brand_basics", "voice_tone"): "brand.voice_tone",
    ("product", "name"): "product.name",
    ("guarantee", "text"): "product.guarantee",
    ("ingredients", "ingredients"): "product.ingredients",
    ("results_timeline", "results_timeline"): "product.results_timeline",
    ("faq_items", "faq_items"): "product.faq_items",
    ("social_proof", "review_platforms"): "product.review_platforms",
    ("social_proof", "top_positive_quotes"): "product.top_positive_quotes",
    ("pricing", "pricing"): "product.pricing",
    ("personas", "personas"): "product.personas",
    ("pain_points", "pain_points"): "offer_variant.pain_points",
    ("mechanism", "name"): "offer_variant.mechanism.name",
    ("mechanism", "root_cause"): "offer_variant.mechanism.root_cause",
}


def resolve_gap_key(gap: Dict[str, str]) -> Optional[str]:
    """Resolve a brand profile gap dict to a GapFieldSpec key.

    Args:
        gap: Dict with 'field' and 'section' keys from BrandProfileService._identify_gaps()

    Returns:
        Gap key string or None if no mapping exists
    """
    section = gap.get("section", "")
    field_name = gap.get("field", "")

    # Try specific (section, field) mapping first
    key = _GAP_SECTION_FIELD_TO_KEY.get((section, field_name))
    if key:
        return key

    # Fallback to field-only mapping
    return _GAP_FIELD_TO_KEY.get(field_name)


# ---------------------------------------------------------------------------
# Normalization helpers (module-level for use in append merge)
# ---------------------------------------------------------------------------

_STOPWORDS = {"the", "a", "an", "my", "your", "their", "our", "his", "her", "its"}


def _normalize_for_comparison(text: str) -> str:
    """Normalize text for near-duplicate comparison."""
    t = text.lower().strip()
    t = re.sub(r"[^\w\s]", "", t)  # remove punctuation
    t = re.sub(r"\s+", " ", t)     # collapse whitespace
    words = [w for w in t.split() if w not in _STOPWORDS]
    return " ".join(words)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class ContentGapFillerService:
    """Service for filling brand profile gaps detected during blueprint generation.

    Handles three fill modes:
    1. Manual entry — user types a value
    2. From sources — pre-extracted candidates from cached data
    3. AI suggestion — LLM-powered extraction (Phase 3)

    All saves record provenance in content_field_events.
    """

    def __init__(self, supabase=None):
        from viraltracker.core.database import get_supabase_client
        self.supabase = supabase or get_supabase_client()
        self._tracker = None
        self._user_id = None
        self._org_id = None

    def set_tracking_context(self, tracker, user_id, org_id):
        """Wire up UsageTracker for AI calls."""
        self._tracker = tracker
        self._user_id = user_id
        self._org_id = org_id

    # ------------------------------------------------------------------
    # Source availability
    # ------------------------------------------------------------------

    def check_available_sources(
        self,
        gaps: List[Dict],
        brand_id: str,
        product_id: str,
        offer_variant_id: Optional[str] = None,
    ) -> Dict[str, List[SourceCandidate]]:
        """Check which data sources can fill each gap.

        Returns:
            Dict keyed by gap_key, value is list of SourceCandidate objects.
        """
        # Pre-fetch all source data once
        amazon_data = self._fetch_amazon_review_data(product_id)
        brand_lp_data = self._fetch_brand_lp_data(brand_id, product_id)
        reddit_data = self._fetch_reddit_quote_data(product_id)

        results: Dict[str, List[SourceCandidate]] = {}

        for gap in gaps:
            gap_key = resolve_gap_key(gap)
            if not gap_key or gap_key not in GAP_FIELD_REGISTRY:
                continue

            spec = GAP_FIELD_REGISTRY[gap_key]
            if spec.needs_setup:
                continue

            candidates: List[SourceCandidate] = []

            for source in spec.sources:
                if source == "amazon_review_analysis" and amazon_data:
                    cands = self._extract_from_amazon(spec, amazon_data)
                    candidates.extend(cands)
                elif source == "brand_landing_pages" and brand_lp_data:
                    cands = self._extract_from_brand_lps(spec, brand_lp_data)
                    candidates.extend(cands)
                elif source == "reddit_sentiment_quotes" and reddit_data:
                    cands = self._extract_from_reddit(spec, reddit_data)
                    candidates.extend(cands)
                # "fresh_scrape" is Phase 4

            if candidates:
                results[gap_key] = candidates

        return results

    def _fetch_amazon_review_data(self, product_id: str) -> Optional[Dict]:
        """Fetch cached Amazon review analysis data."""
        try:
            result = self.supabase.table("amazon_review_analysis").select(
                "id, pain_points, desires, language_patterns, objections, "
                "purchase_triggers, top_positive_quotes, top_negative_quotes, "
                "transformation_quotes, analyzed_at"
            ).eq("product_id", product_id).order(
                "analyzed_at", desc=True
            ).limit(1).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.debug(f"No Amazon review data for product {product_id}: {e}")
            return None

    def _fetch_brand_lp_data(self, brand_id: str, product_id: str) -> List[Dict]:
        """Fetch cached brand landing page data."""
        try:
            result = self.supabase.table("brand_landing_pages").select(
                "id, url, product_name, guarantee, benefits, features, "
                "testimonials, social_proof, raw_markdown, extracted_data, "
                "scrape_status, created_at"
            ).eq("brand_id", brand_id).in_(
                "scrape_status", ["scraped", "analyzed"]
            ).order("created_at", desc=True).limit(10).execute()
            return result.data or []
        except Exception as e:
            logger.debug(f"No brand LP data for brand {brand_id}: {e}")
            return []

    def _fetch_reddit_quote_data(self, product_id: str) -> List[Dict]:
        """Fetch cached Reddit sentiment quotes for the product."""
        try:
            # Get quotes via reddit_scrape_runs for this product
            runs_result = self.supabase.table("reddit_scrape_runs").select(
                "id"
            ).eq("product_id", product_id).execute()

            run_ids = [r["id"] for r in (runs_result.data or [])]
            if not run_ids:
                return []

            result = self.supabase.table("reddit_sentiment_quotes").select(
                "id, quote_text, sentiment_category, sentiment_subtype, "
                "confidence_score, source_type, extraction_reasoning"
            ).in_("run_id", run_ids).order(
                "confidence_score", desc=True
            ).limit(50).execute()
            return result.data or []
        except Exception as e:
            logger.debug(f"No Reddit quote data for product {product_id}: {e}")
            return []

    def _extract_from_amazon(
        self, spec: GapFieldSpec, data: Dict,
    ) -> List[SourceCandidate]:
        """Extract SourceCandidate values from Amazon review analysis data."""
        candidates = []
        source_id = data.get("id")
        analyzed_at = data.get("analyzed_at")

        if spec.key == "offer_variant.pain_points":
            pain_data = data.get("pain_points") or {}
            themes = pain_data.get("themes", [])
            if themes:
                pain_texts = []
                snippets = []
                for theme in themes[:10]:
                    theme_name = theme.get("theme", "")
                    if theme_name:
                        pain_texts.append(theme_name)
                    quotes = theme.get("quotes", [])
                    for q in quotes[:2]:
                        quote_text = q.get("quote", "")
                        if quote_text:
                            snippets.append(quote_text)

                if pain_texts:
                    candidates.append(SourceCandidate(
                        source_type="amazon_review_analysis",
                        source_table="amazon_review_analysis",
                        source_id=source_id,
                        extracted_value=pain_texts,
                        snippets=snippets[:3],
                        url=None,
                        scraped_at=analyzed_at,
                        confidence="high" if len(themes) >= 3 else "medium",
                    ))

        elif spec.key == "offer_variant.mechanism.root_cause":
            pain_data = data.get("pain_points") or {}
            themes = pain_data.get("themes", [])
            if themes:
                # Use top pain point theme as root cause signal
                top_theme = themes[0]
                theme_name = top_theme.get("theme", "")
                quotes = top_theme.get("quotes", [])
                snippets = [q.get("quote", "") for q in quotes[:3] if q.get("quote")]

                if theme_name:
                    candidates.append(SourceCandidate(
                        source_type="amazon_review_analysis",
                        source_table="amazon_review_analysis",
                        source_id=source_id,
                        extracted_value=theme_name,
                        snippets=snippets,
                        url=None,
                        scraped_at=analyzed_at,
                        confidence="medium",
                    ))

        elif spec.key == "product.results_timeline":
            # Look in transformation_quotes for timeline signals
            trans_quotes = data.get("transformation_quotes") or []
            if trans_quotes:
                snippets = trans_quotes[:3]
                candidates.append(SourceCandidate(
                    source_type="amazon_review_analysis",
                    source_table="amazon_review_analysis",
                    source_id=source_id,
                    extracted_value=trans_quotes[:5],
                    snippets=snippets,
                    url=None,
                    scraped_at=analyzed_at,
                    confidence="low",  # Quotes, not structured timeline
                ))

        elif spec.key == "product.top_positive_quotes":
            quotes = data.get("top_positive_quotes") or []
            if quotes:
                candidates.append(SourceCandidate(
                    source_type="amazon_review_analysis",
                    source_table="amazon_review_analysis",
                    source_id=source_id,
                    extracted_value=quotes,
                    snippets=quotes[:3],
                    url=None,
                    scraped_at=analyzed_at,
                    confidence="high",
                ))

        return candidates

    def _extract_from_brand_lps(
        self, spec: GapFieldSpec, lp_data: List[Dict],
    ) -> List[SourceCandidate]:
        """Extract SourceCandidate values from brand landing page data."""
        candidates = []

        for lp in lp_data:
            source_id = lp.get("id")
            url = lp.get("url")
            created_at = lp.get("created_at")

            if spec.key == "product.guarantee":
                guarantee = lp.get("guarantee")
                if guarantee and str(guarantee).strip():
                    candidates.append(SourceCandidate(
                        source_type="brand_landing_pages",
                        source_table="brand_landing_pages",
                        source_id=source_id,
                        extracted_value=str(guarantee).strip(),
                        snippets=[str(guarantee)[:300]],
                        url=url,
                        scraped_at=created_at,
                        confidence="high",
                    ))

            elif spec.key == "product.ingredients":
                extracted = lp.get("extracted_data") or {}
                ingredients = extracted.get("ingredients")
                if ingredients:
                    candidates.append(SourceCandidate(
                        source_type="brand_landing_pages",
                        source_table="brand_landing_pages",
                        source_id=source_id,
                        extracted_value=ingredients,
                        snippets=[str(ingredients)[:300]],
                        url=url,
                        scraped_at=created_at,
                        confidence="medium",
                    ))

            elif spec.key == "product.faq_items":
                extracted = lp.get("extracted_data") or {}
                faq = extracted.get("faq") or extracted.get("faq_items")
                if faq:
                    candidates.append(SourceCandidate(
                        source_type="brand_landing_pages",
                        source_table="brand_landing_pages",
                        source_id=source_id,
                        extracted_value=faq,
                        snippets=[str(faq)[:300]],
                        url=url,
                        scraped_at=created_at,
                        confidence="medium",
                    ))

            elif spec.key == "brand.voice_tone":
                # Voice/tone is harder to extract from LP; look in raw markdown
                raw = lp.get("raw_markdown", "")
                if raw and len(raw) > 100:
                    # Provide the raw markdown as snippet for AI to extract
                    snippet = raw[:500]
                    candidates.append(SourceCandidate(
                        source_type="brand_landing_pages",
                        source_table="brand_landing_pages",
                        source_id=source_id,
                        extracted_value=None,  # Needs AI extraction
                        snippets=[snippet],
                        url=url,
                        scraped_at=created_at,
                        confidence="low",
                    ))

            elif spec.key == "offer_variant.mechanism.name":
                extracted = lp.get("extracted_data") or {}
                mechanism = extracted.get("mechanism") or extracted.get("mechanism_name")
                if mechanism:
                    val = mechanism if isinstance(mechanism, str) else str(mechanism)
                    candidates.append(SourceCandidate(
                        source_type="brand_landing_pages",
                        source_table="brand_landing_pages",
                        source_id=source_id,
                        extracted_value=val,
                        snippets=[val[:300]],
                        url=url,
                        scraped_at=created_at,
                        confidence="medium",
                    ))

            elif spec.key == "offer_variant.mechanism.root_cause":
                extracted = lp.get("extracted_data") or {}
                root_cause = extracted.get("root_cause") or extracted.get("problem")
                if root_cause:
                    val = root_cause if isinstance(root_cause, str) else str(root_cause)
                    candidates.append(SourceCandidate(
                        source_type="brand_landing_pages",
                        source_table="brand_landing_pages",
                        source_id=source_id,
                        extracted_value=val,
                        snippets=[val[:300]],
                        url=url,
                        scraped_at=created_at,
                        confidence="medium",
                    ))

            elif spec.key == "offer_variant.pain_points":
                benefits = lp.get("benefits") or []
                # Pain points can sometimes be inferred from benefits (inverse)
                # But direct pain points from LP are in objection_handling or extracted_data
                extracted = lp.get("extracted_data") or {}
                pain_points = extracted.get("pain_points") or extracted.get("problems")
                if pain_points and isinstance(pain_points, list):
                    candidates.append(SourceCandidate(
                        source_type="brand_landing_pages",
                        source_table="brand_landing_pages",
                        source_id=source_id,
                        extracted_value=pain_points,
                        snippets=[str(p)[:200] for p in pain_points[:3]],
                        url=url,
                        scraped_at=created_at,
                        confidence="medium",
                    ))

        return candidates

    def _extract_from_reddit(
        self, spec: GapFieldSpec, quotes: List[Dict],
    ) -> List[SourceCandidate]:
        """Extract SourceCandidate values from Reddit sentiment quotes."""
        candidates = []

        if spec.key == "offer_variant.pain_points":
            pain_quotes = [
                q for q in quotes
                if q.get("sentiment_category") == "PAIN_POINT"
                and q.get("confidence_score", 0) >= 0.6
            ]
            if pain_quotes:
                pain_texts = [q["quote_text"] for q in pain_quotes[:10]]
                snippets = [q["quote_text"] for q in pain_quotes[:3]]
                candidates.append(SourceCandidate(
                    source_type="reddit_sentiment_quotes",
                    source_table="reddit_sentiment_quotes",
                    source_id=pain_quotes[0].get("id"),
                    extracted_value=pain_texts,
                    snippets=snippets,
                    url=None,
                    scraped_at=None,
                    confidence="high" if len(pain_quotes) >= 5 else "medium",
                ))

        return candidates

    # ------------------------------------------------------------------
    # Current value retrieval
    # ------------------------------------------------------------------

    def _get_current_value(
        self,
        spec: GapFieldSpec,
        brand_id: str,
        product_id: str,
        offer_variant_id: Optional[str] = None,
    ) -> Any:
        """Get the current value of a gap field from the database."""
        try:
            entity_id = self._resolve_entity_id(spec, brand_id, product_id, offer_variant_id)
            if not entity_id or not spec.column:
                return None

            result = self.supabase.table(spec.table).select(
                spec.column
            ).eq("id", entity_id).single().execute()

            if result.data:
                return result.data.get(spec.column)
            return None
        except Exception as e:
            logger.debug(f"Could not get current value for {spec.key}: {e}")
            return None

    def _resolve_entity_id(
        self,
        spec: GapFieldSpec,
        brand_id: str,
        product_id: str,
        offer_variant_id: Optional[str] = None,
    ) -> Optional[str]:
        """Resolve the target entity ID based on the spec's entity type."""
        if spec.entity == "brand":
            return brand_id
        elif spec.entity == "product":
            # Special case: amazon_review_analysis uses product_id but isn't the products table
            if spec.table == "amazon_review_analysis":
                try:
                    result = self.supabase.table("amazon_review_analysis").select(
                        "id"
                    ).eq("product_id", product_id).order(
                        "analyzed_at", desc=True
                    ).limit(1).execute()
                    return result.data[0]["id"] if result.data else None
                except Exception:
                    return None
            return product_id
        elif spec.entity == "offer_variant":
            if offer_variant_id:
                return offer_variant_id
            # Fallback to default variant
            try:
                result = self.supabase.table("product_offer_variants").select(
                    "id"
                ).eq("product_id", product_id).eq("is_default", True).limit(1).execute()
                if result.data:
                    return result.data[0]["id"]
                # Fallback to first active
                result = self.supabase.table("product_offer_variants").select(
                    "id"
                ).eq("product_id", product_id).eq("is_active", True).limit(1).execute()
                return result.data[0]["id"] if result.data else None
            except Exception:
                return None
        return None

    # ------------------------------------------------------------------
    # Validation & normalization
    # ------------------------------------------------------------------

    def _normalize_and_validate(self, spec: GapFieldSpec, value: Any) -> Any:
        """Normalize and validate a value before saving.

        Args:
            spec: The gap field specification
            value: The raw value to normalize

        Returns:
            Normalized value ready for DB save

        Raises:
            ValueError: If validation fails
        """
        if spec.value_type == "text":
            return self._validate_text(value)
        elif spec.value_type == "text_list":
            return self._validate_text_list(value)
        elif spec.value_type == "qa_list":
            return self._validate_qa_list(value)
        elif spec.value_type == "timeline_list":
            return self._validate_timeline_list(value)
        elif spec.value_type == "json_array":
            return self._validate_json_array(value)
        elif spec.value_type == "json":
            return self._validate_json(value)
        elif spec.value_type in ("quote_list", "complex"):
            raise ValueError(f"Cannot validate value_type '{spec.value_type}' — requires special handling")
        else:
            raise ValueError(f"Unknown value_type: {spec.value_type}")

    def _validate_text(self, value: Any) -> str:
        """Validate text field: strip, collapse whitespace, non-empty."""
        if not isinstance(value, str):
            value = str(value)
        value = value.strip()
        value = re.sub(r"\s+", " ", value)
        if not value:
            raise ValueError("Text field cannot be empty")
        return value

    def _validate_text_list(self, value: Any) -> List[str]:
        """Validate text list: strip each, remove empties, deduplicate."""
        if isinstance(value, str):
            # Split by newlines or semicolons
            items = re.split(r"[\n;]+", value)
        elif isinstance(value, list):
            items = value
        else:
            raise ValueError("Expected a list of strings")

        cleaned = []
        seen = set()
        for item in items:
            text = str(item).strip()
            if text and text.lower() not in seen:
                cleaned.append(text)
                seen.add(text.lower())

        if not cleaned:
            raise ValueError("List must have at least 1 item")
        return cleaned

    def _validate_qa_list(self, value: Any) -> List[Dict[str, str]]:
        """Validate QA list: each item has {question, answer}, strip both."""
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                raise ValueError("Invalid JSON for QA list")

        if not isinstance(value, list):
            raise ValueError("Expected a list of {question, answer} objects")

        cleaned = []
        for item in value:
            if not isinstance(item, dict):
                raise ValueError("Each QA item must be an object with 'question' and 'answer'")
            q = str(item.get("question", "")).strip()
            a = str(item.get("answer", "")).strip()
            if q and a:
                cleaned.append({"question": q, "answer": a})

        if not cleaned:
            raise ValueError("QA list must have at least 1 item with question and answer")
        return cleaned

    def _validate_timeline_list(self, value: Any) -> List[Dict[str, str]]:
        """Validate timeline list: each item has {timeframe, expected_result}."""
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                raise ValueError("Invalid JSON for timeline list")

        if not isinstance(value, list):
            raise ValueError("Expected a list of {timeframe, expected_result} objects")

        cleaned = []
        for item in value:
            if not isinstance(item, dict):
                raise ValueError("Each timeline item must be an object with 'timeframe' and 'expected_result'")
            t = str(item.get("timeframe", "")).strip()
            r = str(item.get("expected_result", "")).strip()
            if t and r:
                cleaned.append({"timeframe": t, "expected_result": r})

        if not cleaned:
            raise ValueError("Timeline must have at least 1 item")
        return cleaned

    def _validate_json_array(self, value: Any) -> List[Dict]:
        """Validate JSON array (e.g. ingredients): valid JSON, non-empty."""
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                raise ValueError("Invalid JSON")

        if not isinstance(value, list):
            raise ValueError("Expected a JSON array")
        if not value:
            raise ValueError("JSON array must not be empty")

        return value

    def _validate_json(self, value: Any) -> Any:
        """Validate JSON value: valid structure."""
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                raise ValueError("Invalid JSON")
        if value is None:
            raise ValueError("JSON value cannot be null")
        return value

    # ------------------------------------------------------------------
    # Apply value (save with provenance)
    # ------------------------------------------------------------------

    def apply_value(
        self,
        gap_key: str,
        value: Any,
        brand_id: str,
        product_id: str,
        offer_variant_id: Optional[str] = None,
        source_type: str = "manual",
        source_detail: Optional[Dict] = None,
        blueprint_id: Optional[str] = None,
        force_overwrite: bool = False,
        request_id: Optional[str] = None,
        source_hash: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> ApplyResult:
        """Apply a value to a gap field with provenance tracking.

        Args:
            gap_key: Key from GAP_FIELD_REGISTRY
            value: Value to save (will be normalized and validated)
            brand_id: Brand UUID
            product_id: Product UUID
            offer_variant_id: Optional offer variant UUID
            source_type: "manual", "cached_source", "ai_suggestion", "fresh_scrape"
            source_detail: Provenance metadata dict
            blueprint_id: Blueprint that triggered this fill
            force_overwrite: Skip confirmation for confirm_overwrite policy
            request_id: Groups events from a single action (e.g. Fix All)
            source_hash: SHA-256 of evidence for staleness detection
            org_id: Organization UUID for provenance

        Returns:
            ApplyResult with success status and action taken
        """
        spec = GAP_FIELD_REGISTRY.get(gap_key)
        if not spec:
            return ApplyResult(success=False, action="error", old_value=None, new_value=None, needs_confirmation=False)

        if spec.needs_setup:
            return ApplyResult(success=False, action="error", old_value=None, new_value=None, needs_confirmation=False)

        # Normalize and validate
        try:
            normalized = self._normalize_and_validate(spec, value)
        except ValueError as e:
            logger.warning(f"Validation failed for {gap_key}: {e}")
            return ApplyResult(success=False, action="error", old_value=None, new_value=str(e), needs_confirmation=False)

        entity_id = self._resolve_entity_id(spec, brand_id, product_id, offer_variant_id)
        if not entity_id:
            return ApplyResult(
                success=False, action="error", old_value=None,
                new_value="Could not resolve target entity", needs_confirmation=False,
            )

        old_value = self._get_current_value(spec, brand_id, product_id, offer_variant_id)
        request_id = request_id or str(uuid.uuid4())
        use_org_id = org_id or self._org_id

        # No-op guard: if normalized value equals current value, skip
        if self._values_equal(old_value, normalized):
            return ApplyResult(
                success=True, action="no_change", old_value=old_value,
                new_value=normalized, needs_confirmation=False,
            )

        is_empty = self._is_empty(old_value)

        # Write policy check
        if spec.write_policy == "allow_if_empty" and not is_empty and not force_overwrite:
            return ApplyResult(
                success=False, action="needs_confirmation", old_value=old_value,
                new_value=normalized, needs_confirmation=True,
            )
        elif spec.write_policy == "confirm_overwrite" and not is_empty and not force_overwrite:
            return ApplyResult(
                success=False, action="needs_confirmation", old_value=old_value,
                new_value=normalized, needs_confirmation=True,
            )
        elif spec.write_policy == "append" and not is_empty:
            # Merge lists
            normalized = self._merge_append(old_value, normalized, source_type)

        # Determine action
        action = "set" if is_empty else ("append" if spec.write_policy == "append" else "overwrite")

        # Save to canonical table
        saved = self._save_to_table(spec, entity_id, normalized)
        if not saved:
            return ApplyResult(
                success=False, action="error", old_value=old_value,
                new_value=normalized, needs_confirmation=False,
            )

        # Record provenance event
        self._record_event(
            spec=spec,
            entity_id=entity_id,
            action=action,
            old_value=old_value,
            new_value=normalized,
            source_type=source_type,
            source_detail=source_detail or {},
            blueprint_id=blueprint_id,
            request_id=request_id,
            source_hash=source_hash,
            org_id=use_org_id,
        )

        return ApplyResult(
            success=True, action=action, old_value=old_value,
            new_value=normalized, needs_confirmation=False,
        )

    def _merge_append(
        self,
        existing: Any,
        new_items: List[str],
        source_type: str,
    ) -> List[str]:
        """Merge new items into existing list with near-duplicate detection.

        Uses SequenceMatcher with ratio > 0.87 on normalized forms.
        Caps at 15 items total.
        """
        if not existing:
            existing = []
        if isinstance(existing, str):
            existing = [existing]

        existing_normalized = [_normalize_for_comparison(item) for item in existing]

        merged = list(existing)
        for new_item in new_items:
            new_norm = _normalize_for_comparison(new_item)
            is_dup = False
            for existing_norm in existing_normalized:
                if SequenceMatcher(None, new_norm, existing_norm).ratio() > 0.87:
                    is_dup = True
                    break
            if not is_dup:
                merged.append(new_item)
                existing_normalized.append(new_norm)

        # Cap at 15
        if len(merged) > 15:
            merged = merged[:15]

        return merged

    def _values_equal(self, old: Any, new: Any) -> bool:
        """Check if two values are equal (for no-op guard)."""
        if old is None and new is None:
            return True
        if old is None or new is None:
            return False
        # Normalize for comparison
        try:
            return json.dumps(old, sort_keys=True) == json.dumps(new, sort_keys=True)
        except (TypeError, ValueError):
            return str(old) == str(new)

    def _is_empty(self, value: Any) -> bool:
        """Check if a value is empty."""
        if value is None:
            return True
        if isinstance(value, str) and not value.strip():
            return True
        if isinstance(value, (list, dict)) and len(value) == 0:
            return True
        return False

    # ------------------------------------------------------------------
    # Not Applicable (dismiss gap without touching canonical data)
    # ------------------------------------------------------------------

    def mark_not_applicable(
        self,
        gap_key: str,
        brand_id: str,
        product_id: str,
        offer_variant_id: Optional[str] = None,
        blueprint_id: Optional[str] = None,
        request_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> None:
        """Mark a gap as not applicable for this blueprint.

        Records a skip_not_applicable event. Does NOT write null to canonical table.
        Scope: per blueprint_id + target_id + gap_key.
        """
        spec = GAP_FIELD_REGISTRY.get(gap_key)
        if not spec:
            return

        entity_id = self._resolve_entity_id(spec, brand_id, product_id, offer_variant_id)
        if not entity_id:
            return

        request_id = request_id or str(uuid.uuid4())
        use_org_id = org_id or self._org_id

        self._record_event(
            spec=spec,
            entity_id=entity_id,
            action="skip_not_applicable",
            old_value=None,
            new_value=None,
            source_type="system",
            source_detail={},
            blueprint_id=blueprint_id,
            request_id=request_id,
            source_hash=None,
            org_id=use_org_id,
        )

    def undo_not_applicable(
        self,
        gap_key: str,
        brand_id: str,
        product_id: str,
        offer_variant_id: Optional[str] = None,
        blueprint_id: Optional[str] = None,
        request_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> None:
        """Undo a not-applicable dismissal. Records an undo_skip event."""
        spec = GAP_FIELD_REGISTRY.get(gap_key)
        if not spec:
            return

        entity_id = self._resolve_entity_id(spec, brand_id, product_id, offer_variant_id)
        if not entity_id:
            return

        request_id = request_id or str(uuid.uuid4())
        use_org_id = org_id or self._org_id

        self._record_event(
            spec=spec,
            entity_id=entity_id,
            action="undo_skip",
            old_value=None,
            new_value=None,
            source_type="system",
            source_detail={},
            blueprint_id=blueprint_id,
            request_id=request_id,
            source_hash=None,
            org_id=use_org_id,
        )

    def is_gap_dismissed(
        self,
        gap_key: str,
        blueprint_id: Optional[str],
        target_id: str,
    ) -> bool:
        """Check if a gap has been dismissed for this blueprint.

        Queries the most recent event for (blueprint_id, target_id, gap_key).
        Returns True if last action is skip_not_applicable.
        """
        if not blueprint_id:
            return False

        try:
            result = self.supabase.table("content_field_events").select(
                "action"
            ).eq("blueprint_id", blueprint_id).eq(
                "target_id", target_id
            ).eq("gap_key", gap_key).order(
                "created_at", desc=True
            ).limit(1).execute()

            if result.data:
                return result.data[0]["action"] == "skip_not_applicable"
            return False
        except Exception as e:
            logger.debug(f"Could not check dismiss status for {gap_key}: {e}")
            return False

    # ------------------------------------------------------------------
    # Save and provenance
    # ------------------------------------------------------------------

    def _save_to_table(self, spec: GapFieldSpec, entity_id: str, value: Any) -> bool:
        """Save a value to the canonical database table."""
        if not spec.column:
            logger.error(f"Cannot save to {spec.key} — no column defined")
            return False

        try:
            # Convert lists/dicts to JSON-compatible format for Supabase
            save_value = value
            if spec.value_type in ("qa_list", "timeline_list", "json_array", "json"):
                # These are stored as JSONB in Supabase, pass as-is
                save_value = value
            elif spec.value_type == "text_list":
                # text_list maps to TEXT[] (PostgreSQL array)
                save_value = value

            self.supabase.table(spec.table).update(
                {spec.column: save_value}
            ).eq("id", entity_id).execute()
            return True
        except Exception as e:
            logger.error(f"Failed to save {spec.key} to {spec.table}.{spec.column}: {e}")
            return False

    def _record_event(
        self,
        spec: GapFieldSpec,
        entity_id: str,
        action: str,
        old_value: Any,
        new_value: Any,
        source_type: str,
        source_detail: Dict,
        blueprint_id: Optional[str],
        request_id: str,
        source_hash: Optional[str],
        org_id: Optional[str] = None,
    ) -> None:
        """Record a provenance event in content_field_events."""
        try:
            event = {
                "organization_id": org_id or self._org_id,
                "target_table": spec.table,
                "target_id": entity_id,
                "target_column": spec.column or spec.key,
                "gap_key": spec.key,
                "user_id": self._user_id,
                "blueprint_id": blueprint_id,
                "request_id": request_id,
                "action": action,
                "old_value": json.dumps(old_value) if old_value is not None else None,
                "new_value": json.dumps(new_value) if new_value is not None else None,
                "source_type": source_type,
                "source_detail": source_detail,
                "source_hash": source_hash,
            }
            # Remove None values for fields that shouldn't be null in insert
            event = {k: v for k, v in event.items() if v is not None or k in ("old_value", "new_value", "source_hash", "blueprint_id", "user_id")}

            self.supabase.table("content_field_events").insert(event).execute()
        except Exception as e:
            # Don't fail the save if provenance recording fails
            logger.error(f"Failed to record event for {spec.key}: {e}")

    def _compute_source_hash(self, evidence_inputs: List[Dict]) -> str:
        """Compute SHA-256 of canonical evidence JSON for staleness detection.

        Each input: {source_type, source_table, source_id, url, snippet, scraped_at}
        """
        canonical = []
        for inp in evidence_inputs:
            canonical.append({
                "source_type": inp.get("source_type", ""),
                "source_table": inp.get("source_table", ""),
                "source_id": inp.get("source_id", ""),
                "url": (inp.get("url") or "").strip().rstrip("/").lower(),
                "snippet": (inp.get("snippet") or "").strip(),
                "scraped_at": inp.get("scraped_at", ""),
            })
        canonical.sort(key=lambda x: (x["source_type"], x["source_table"], x["source_id"]))
        blob = json.dumps(canonical, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------
    # AI suggestions
    # ------------------------------------------------------------------

    async def generate_suggestion(
        self,
        gap_key: str,
        brand_id: str,
        product_id: str,
        offer_variant_id: Optional[str] = None,
    ) -> Optional[Dict]:
        """Generate an AI suggestion for a single gap field.

        Returns:
            Dict with: field, value, confidence, evidence/evidence_map, reasoning
            or None if generation fails.
        """
        spec = GAP_FIELD_REGISTRY.get(gap_key)
        if not spec or not spec.auto_fillable:
            return None

        source_data = self._gather_all_source_data(
            brand_id, product_id, offer_variant_id, gap_specs=[spec],
        )
        if not source_data:
            return None

        prompt = self._build_extraction_prompt([spec], source_data)
        try:
            result = await self._run_extraction_llm(prompt, operation=f"gap_fill_{gap_key}")
            suggestions = result if isinstance(result, list) else [result]
            for s in suggestions:
                if s.get("field") == gap_key:
                    return s
            return suggestions[0] if suggestions else None
        except Exception as e:
            logger.error(f"AI suggestion failed for {gap_key}: {e}")
            return None

    async def generate_all_suggestions(
        self,
        gaps: List[Dict],
        brand_id: str,
        product_id: str,
        offer_variant_id: Optional[str] = None,
    ) -> List[Dict]:
        """Generate AI suggestions for all auto-fillable gaps in batches.

        Groups fields by compatible data source to minimize LLM calls:
        - LP-derived batch: guarantee, ingredients, faq_items, mechanism, voice_tone
        - Review-derived batch: pain_points, results_timeline

        Returns:
            List of suggestion dicts with field, value, confidence, evidence.
        """
        # Resolve and filter to auto-fillable only
        auto_fillable_specs = []
        for gap in gaps:
            gap_key = resolve_gap_key(gap)
            if not gap_key or gap_key not in GAP_FIELD_REGISTRY:
                continue
            spec = GAP_FIELD_REGISTRY[gap_key]
            if spec.auto_fillable and not spec.needs_setup:
                auto_fillable_specs.append(spec)

        if not auto_fillable_specs:
            return []

        source_data = self._gather_all_source_data(
            brand_id, product_id, offer_variant_id, gap_specs=auto_fillable_specs,
        )
        if not source_data:
            return []

        # Group by source type
        lp_sources = {"brand_landing_pages", "fresh_scrape"}
        review_sources = {"amazon_review_analysis", "reddit_sentiment_quotes"}

        lp_batch = [s for s in auto_fillable_specs if lp_sources & set(s.sources)]
        review_batch = [s for s in auto_fillable_specs if review_sources & set(s.sources)]

        # Deduplicate: if a spec is in both, keep it in the batch where its primary source is
        seen = set()
        deduped_lp = []
        for s in lp_batch:
            if s.key not in seen:
                deduped_lp.append(s)
                seen.add(s.key)
        deduped_review = []
        for s in review_batch:
            if s.key not in seen:
                deduped_review.append(s)
                seen.add(s.key)

        all_suggestions = []

        # LP-derived batch (max 6 fields)
        if deduped_lp:
            batch = deduped_lp[:6]
            prompt = self._build_extraction_prompt(batch, source_data)
            try:
                result = await self._run_extraction_llm(prompt, operation="gap_fill_batch_lp")
                suggestions = result if isinstance(result, list) else [result]
                all_suggestions.extend(suggestions)
            except Exception as e:
                logger.error(f"LP batch AI suggestion failed: {e}")

        # Review-derived batch (max 4 fields)
        if deduped_review:
            batch = deduped_review[:4]
            prompt = self._build_extraction_prompt(batch, source_data)
            try:
                result = await self._run_extraction_llm(prompt, operation="gap_fill_batch_review")
                suggestions = result if isinstance(result, list) else [result]
                all_suggestions.extend(suggestions)
            except Exception as e:
                logger.error(f"Review batch AI suggestion failed: {e}")

        return all_suggestions

    def _gather_all_source_data(
        self,
        brand_id: str,
        product_id: str,
        offer_variant_id: Optional[str] = None,
        gap_specs: Optional[List[GapFieldSpec]] = None,
    ) -> Dict[str, Any]:
        """Gather all available source data for AI extraction."""
        data = {}

        amazon = self._fetch_amazon_review_data(product_id)
        if amazon:
            data["amazon_review_analysis"] = {
                "pain_points": amazon.get("pain_points"),
                "desires": amazon.get("desires"),
                "top_positive_quotes": amazon.get("top_positive_quotes"),
                "transformation_quotes": amazon.get("transformation_quotes"),
                "analyzed_at": amazon.get("analyzed_at"),
            }

        brand_lps = self._fetch_brand_lp_data(brand_id, product_id)
        if brand_lps:
            # Take the most relevant LP (first one, already sorted by recency)
            lp = brand_lps[0]
            lp_entry: Dict[str, Any] = {
                "url": lp.get("url"),
                "guarantee": lp.get("guarantee"),
                "benefits": lp.get("benefits"),
                "features": lp.get("features"),
                "testimonials": lp.get("testimonials"),
                "extracted_data": lp.get("extracted_data"),
            }
            # Use chunking instead of truncation — select relevant portions for LLM
            full_markdown = lp.get("raw_markdown") or ""
            if full_markdown:
                chunks = chunk_markdown(full_markdown)
                specs_for_chunking = gap_specs or list(GAP_FIELD_REGISTRY.values())
                relevant = pick_chunks_for_fields(chunks, specs_for_chunking)
                lp_entry["chunks"] = [
                    {"heading": "/".join(c.heading_path), "text": c.text, "chunk_id": c.chunk_id}
                    for c in relevant
                ]
            data["brand_landing_pages"] = lp_entry

        reddit = self._fetch_reddit_quote_data(product_id)
        if reddit:
            data["reddit_sentiment_quotes"] = [
                {
                    "quote": q.get("quote_text", ""),
                    "category": q.get("sentiment_category", ""),
                    "confidence": q.get("confidence_score", 0),
                }
                for q in reddit[:20]
            ]

        return data

    def _build_extraction_prompt(
        self,
        gap_specs: List[GapFieldSpec],
        source_data: Dict[str, Any],
    ) -> str:
        """Build the LLM prompt for extracting gap field values from source data.

        Uses strict JSON schema and requires evidence for every suggestion.
        """
        fields_desc = []
        for spec in gap_specs:
            type_hint = ""
            if spec.value_type == "text":
                type_hint = "Return a single text string."
            elif spec.value_type == "text_list":
                type_hint = "Return a JSON array of strings."
            elif spec.value_type == "qa_list":
                type_hint = 'Return a JSON array of {"question": "...", "answer": "..."}.'
            elif spec.value_type == "timeline_list":
                type_hint = 'Return a JSON array of {"timeframe": "...", "expected_result": "..."}.'
            elif spec.value_type == "json_array":
                if spec.key == "product.ingredients":
                    type_hint = 'Return a JSON array of {"name": "...", "benefit": "...", "proof_point": "..."}.'
                else:
                    type_hint = "Return a JSON array of objects."

            fields_desc.append(
                f'- field: "{spec.key}" ({spec.display_name}). {type_hint}'
            )

        fields_section = "\n".join(fields_desc)

        source_json = json.dumps(source_data, indent=2, ensure_ascii=False, default=str)
        # Safety cap — pick_chunks_for_fields already limits LLM-bound content,
        # but guard against unexpectedly large non-chunk data (e.g., Amazon reviews)
        if len(source_json) > 20000:
            logger.warning(
                f"Source JSON unexpectedly large ({len(source_json)} chars) — "
                "chunking should have limited this. Applying safety cap."
            )
            source_json = source_json[:20000] + "\n... (safety-capped)"

        has_list_field = any(s.value_type == "text_list" for s in gap_specs)

        if has_list_field:
            list_schema = '''
For list fields (text_list), use this schema:
{
  "field": "<gap_key>",
  "value": [
    {"id": "item1", "text": "..."},
    {"id": "item2", "text": "..."}
  ],
  "confidence": "high|medium|low",
  "evidence_map": {
    "item1": {"source": "...", "snippet": "exact quote...", "url": null},
    "item2": {"source": "...", "snippet": "exact quote...", "url": null}
  },
  "reasoning": "Brief explanation"
}'''
        else:
            list_schema = ""

        prompt = f"""Extract the following brand/product fields from the available data sources.

FIELDS TO EXTRACT:
{fields_section}

AVAILABLE SOURCE DATA:
{source_json}

INSTRUCTIONS:
1. For each field, find the best evidence in the source data.
2. Return a JSON array of suggestions (one per field).
3. Every suggestion MUST include evidence with source attribution.
4. If no evidence is found for a field, set confidence to "low" and explain in reasoning.
5. Only extract factual information — do not invent or hallucinate data.
6. IMPORTANT: Some fields (e.g. brand voice/tone) are ALWAYS inferred — there is never an explicit "Brand Voice:" heading.
   For these fields, SYNTHESIZE a value from the copy style, word choices, and emotional tone observed in the source data.
   A synthesized value is still valid — set confidence to "medium" and cite the snippets you inferred from.
7. The "value" field must ALWAYS be populated for every field suggestion. Never leave it null or empty.
   If evidence is weak, still provide your best extraction/synthesis and set confidence to "low".

CONFIDENCE RULES:
- "high": Exact-match field pattern in source (e.g. explicit "Guarantee:" heading) + strong snippet + product-level source
- "medium": Inferred/condensed from multiple snippets, or brand-level source (not product-specific), or indirect evidence
- "low": Weak evidence only, or generic source, or no strong match found

OUTPUT FORMAT — return a JSON array:
For scalar fields (text, json, qa_list, timeline_list, json_array):
{{
  "field": "<gap_key>",
  "value": <extracted value matching the type>,
  "confidence": "high|medium|low",
  "evidence": [
    {{"source": "<source_type>", "snippet": "exact relevant quote...", "url": null}}
  ],
  "reasoning": "Brief explanation of extraction"
}}
{list_schema}

Return ONLY the JSON array, no markdown fencing or explanation."""

        return prompt

    async def _run_extraction_llm(
        self,
        prompt: str,
        operation: str = "gap_fill",
    ) -> Any:
        """Run the extraction LLM call with tracking."""
        from pydantic_ai import Agent
        from pydantic_ai.settings import ModelSettings
        from viraltracker.core.config import Config
        from viraltracker.services.agent_tracking import run_agent_with_tracking
        from viraltracker.services.landing_page_analysis.utils import parse_llm_json

        system = (
            "You are a data extraction specialist. Extract structured field values "
            "from available data sources. Always cite evidence. Return strict JSON only."
        )

        model = Config.get_model("complex")
        agent = Agent(
            model=model,
            system_prompt=system,
            model_settings=ModelSettings(max_tokens=8192, temperature=0.2),
        )

        result = await run_agent_with_tracking(
            agent,
            prompt,
            tracker=self._tracker,
            user_id=self._user_id,
            organization_id=self._org_id,
            tool_name="content_gap_filler",
            operation=operation,
        )

        return parse_llm_json(result.output)

    # ------------------------------------------------------------------
    # Fresh scrape
    # ------------------------------------------------------------------

    async def scrape_and_extract_from_lp(
        self,
        url: str,
        target_fields: List[str],
        brand_id: str,
        product_id: str,
        offer_variant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Scrape a landing page and extract field values.

        Args:
            url: URL to scrape
            target_fields: List of gap_keys to extract
            brand_id: Brand UUID (for caching)
            product_id: Product UUID (for product keyword check)
            offer_variant_id: Optional offer variant UUID

        Returns:
            Dict keyed by gap_key with extracted values.
        """
        self._validate_scrape_url(url)

        from viraltracker.services.web_scraping_service import WebScrapingService

        scraper = WebScrapingService()
        result = scraper.scrape_url(url, formats=["markdown"])

        if not result.success or not result.markdown:
            raise ValueError(f"Scrape failed: {result.error or 'No content returned'}")

        markdown = result.markdown

        # Product keyword check
        product_name = self._get_product_name(product_id)
        brand_name = self._get_brand_name(brand_id)
        keyword_warning = None
        if product_name and product_name.lower() not in markdown.lower():
            if brand_name and brand_name.lower() not in markdown.lower():
                keyword_warning = (
                    f"This page may not be about {product_name}. "
                    f"Neither product name nor brand name found in page content."
                )

        # Cache result in brand_landing_pages
        self._cache_scrape_result(url, markdown, brand_id, product_id)

        # Extract fields using AI
        specs = [GAP_FIELD_REGISTRY[k] for k in target_fields if k in GAP_FIELD_REGISTRY]
        if not specs:
            return {}

        # Chunk full markdown for LLM prompt — no truncation of stored content
        chunks = chunk_markdown(markdown)
        relevant = pick_chunks_for_fields(chunks, specs)
        source_data = {
            "fresh_scrape": {
                "url": url,
                "chunks": [
                    {"heading": "/".join(c.heading_path), "text": c.text, "chunk_id": c.chunk_id}
                    for c in relevant
                ],
            }
        }

        prompt = self._build_extraction_prompt(specs, source_data)
        try:
            suggestions = await self._run_extraction_llm(prompt, operation="gap_fill_fresh_scrape")
            if not isinstance(suggestions, list):
                suggestions = [suggestions]

            extracted = {}
            for s in suggestions:
                field_key = s.get("field", "")
                if field_key:
                    extracted[field_key] = s

            if keyword_warning:
                for key in extracted:
                    extracted[key]["keyword_warning"] = keyword_warning

            return extracted
        except Exception as e:
            logger.error(f"Fresh scrape extraction failed: {e}")
            return {}

    def _validate_scrape_url(self, url: str) -> None:
        """Validate a URL for SSRF protection.

        Raises:
            ValueError: If URL is invalid, non-HTTPS, or resolves to private IP.
        """
        import socket
        import ipaddress
        from urllib.parse import urlparse

        if not url:
            raise ValueError("URL is required")

        parsed = urlparse(url)

        # Must be HTTPS
        if parsed.scheme not in ("https",):
            raise ValueError("Only HTTPS URLs are allowed")

        hostname = parsed.hostname
        if not hostname:
            raise ValueError("Invalid URL: no hostname")

        # Resolve DNS and check for private IPs
        try:
            addr_infos = socket.getaddrinfo(hostname, parsed.port or 443)
        except socket.gaierror:
            raise ValueError(f"Could not resolve hostname: {hostname}")

        for family, type_, proto, canonname, sockaddr in addr_infos:
            ip = sockaddr[0]
            addr = ipaddress.ip_address(ip)
            if addr.is_private or addr.is_loopback or addr.is_reserved or addr.is_link_local:
                raise ValueError(
                    f"URL resolves to private/reserved IP ({ip}). "
                    "Only public URLs are allowed."
                )

    def _rank_scrape_urls(
        self,
        product_id: str,
        offer_variant_id: Optional[str],
        brand_id: str,
    ) -> List[Dict[str, Any]]:
        """Rank available URLs for scraping.

        Priority: (1) offer variant LP URL, (2) known brand LP URLs, (3) user-provided.
        """
        urls = []

        # 1. Offer variant LP URL
        if offer_variant_id:
            try:
                result = self.supabase.table("product_offer_variants").select(
                    "landing_page_url, name"
                ).eq("id", offer_variant_id).single().execute()
                if result.data and result.data.get("landing_page_url"):
                    urls.append({
                        "url": result.data["landing_page_url"],
                        "source": "offer_variant",
                        "label": f"Offer Variant: {result.data.get('name', '')}",
                        "priority": 1,
                    })
            except Exception:
                pass

        # 2. Known brand LP URLs
        seen_urls = {u["url"] for u in urls}
        try:
            result = self.supabase.table("brand_landing_pages").select(
                "url, page_title, created_at"
            ).eq("brand_id", brand_id).order(
                "created_at", desc=True
            ).limit(5).execute()
            for lp in (result.data or []):
                url = lp.get("url")
                if url and url not in seen_urls:
                    urls.append({
                        "url": url,
                        "source": "brand_landing_pages",
                        "label": f"Brand LP: {lp.get('page_title', url[:50])}",
                        "priority": 2,
                        "scraped_at": lp.get("created_at"),
                    })
                    seen_urls.add(url)
        except Exception:
            pass

        return urls

    def _get_scrape_cooldown_info(self, brand_id: str) -> Optional[Dict]:
        """Check if a recent scrape exists (within 24h) for cooldown."""
        try:
            result = self.supabase.table("brand_landing_pages").select(
                "url, created_at"
            ).eq("brand_id", brand_id).order(
                "created_at", desc=True
            ).limit(1).execute()
            if result.data:
                from datetime import datetime, timezone, timedelta
                scraped_at = result.data[0].get("created_at", "")
                if scraped_at:
                    dt = datetime.fromisoformat(scraped_at.replace("Z", "+00:00"))
                    age = datetime.now(timezone.utc) - dt
                    hours_ago = age.total_seconds() / 3600
                    return {
                        "url": result.data[0].get("url"),
                        "scraped_at": scraped_at,
                        "hours_ago": round(hours_ago, 1),
                        "within_cooldown": hours_ago < 24,
                    }
            return None
        except Exception:
            return None

    def _cache_scrape_result(
        self,
        url: str,
        markdown: str,
        brand_id: str,
        product_id: Optional[str] = None,
    ) -> None:
        """Cache a scrape result in brand_landing_pages with content_hash dedup."""
        try:
            content_hash = hashlib.sha256(markdown.encode()).hexdigest()
            now = datetime.now(timezone.utc).isoformat()
            content_length = len(markdown)
            logger.info(f"Caching scrape for {url}: {content_length} chars")

            # Check if URL already exists for this brand
            existing = self.supabase.table("brand_landing_pages").select(
                "id, content_hash"
            ).eq("brand_id", brand_id).eq("url", url).limit(1).execute()

            if existing.data:
                row = existing.data[0]
                if row.get("content_hash") == content_hash:
                    # Content unchanged — bump last_scraped_at only
                    self.supabase.table("brand_landing_pages").update({
                        "last_scraped_at": now,
                    }).eq("id", row["id"]).execute()
                else:
                    # Content changed — update full content
                    self.supabase.table("brand_landing_pages").update({
                        "raw_markdown": markdown,
                        "content_hash": content_hash,
                        "last_scraped_at": now,
                        "scrape_status": "scraped",
                    }).eq("id", row["id"]).execute()
            else:
                # Insert new
                self.supabase.table("brand_landing_pages").insert({
                    "brand_id": brand_id,
                    "product_id": product_id,
                    "url": url,
                    "raw_markdown": markdown,
                    "content_hash": content_hash,
                    "last_scraped_at": now,
                    "scrape_status": "scraped",
                }).execute()
        except Exception as e:
            logger.warning(f"Failed to cache scrape result: {e}")

    def _get_product_name(self, product_id: str) -> Optional[str]:
        """Get product name for keyword check."""
        try:
            result = self.supabase.table("products").select(
                "name"
            ).eq("id", product_id).single().execute()
            return result.data.get("name") if result.data else None
        except Exception:
            return None

    def _get_brand_name(self, brand_id: str) -> Optional[str]:
        """Get brand name for keyword check."""
        try:
            result = self.supabase.table("brands").select(
                "name"
            ).eq("id", brand_id).single().execute()
            return result.data.get("name") if result.data else None
        except Exception:
            return None
