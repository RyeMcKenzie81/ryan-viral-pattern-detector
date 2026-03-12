"""
Tests for VisualPropertyExtractor — JSON parsing, validation, caching.

All database calls are mocked — no real DB or API connections needed.
"""

import json
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from viraltracker.services.visual_property_extractor import (
    VisualPropertyExtractor,
    VALID_ENUMS,
    PROMPT_VERSION,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def extractor():
    """Create a VisualPropertyExtractor with mocked dependencies."""
    mock_supabase = MagicMock()
    mock_gemini = MagicMock()
    mock_gemini.analyze_image = AsyncMock()
    return VisualPropertyExtractor(mock_supabase, mock_gemini)


VALID_JSON_RESPONSE = json.dumps({
    "contrast_level": "high",
    "color_palette_type": "warm",
    "dominant_colors": [{"hex": "#FF5733", "name": "red-orange", "pct": 0.4}],
    "text_density": "minimal",
    "headline_word_count": 3,
    "visual_hierarchy": "face_centric",
    "composition_style": "centered",
    "face_presence": True,
    "face_count": 1,
    "face_emotion": "happy",
    "person_framing": "close_up",
    "product_visible": False,
    "product_prominence": "absent",
    "before_after_present": False,
    "headline_style": "bold",
    "cta_visual_treatment": "button",
    "visual_quality_score": 0.85,
    "thumb_stop_prediction": 0.70,
})


# ============================================================================
# _parse_and_validate tests
# ============================================================================

class TestParseAndValidate:
    def test_valid_json(self, extractor):
        result = extractor._parse_and_validate(VALID_JSON_RESPONSE)
        assert result is not None
        assert result["contrast_level"] == "high"
        assert result["face_presence"] is True
        assert result["visual_quality_score"] == 0.85

    def test_strips_markdown_fences(self, extractor):
        wrapped = f"```json\n{VALID_JSON_RESPONSE}\n```"
        result = extractor._parse_and_validate(wrapped)
        assert result is not None
        assert result["contrast_level"] == "high"

    def test_invalid_json_returns_none(self, extractor):
        result = extractor._parse_and_validate("not json at all")
        assert result is None

    def test_invalid_enum_set_to_none(self, extractor):
        data = json.loads(VALID_JSON_RESPONSE)
        data["contrast_level"] = "super_mega_contrast"
        result = extractor._parse_and_validate(json.dumps(data))
        assert result["contrast_level"] is None

    def test_enum_lowercase_normalization(self, extractor):
        data = json.loads(VALID_JSON_RESPONSE)
        data["contrast_level"] = "HIGH"
        result = extractor._parse_and_validate(json.dumps(data))
        assert result["contrast_level"] == "high"

    def test_float_clamped_above_one(self, extractor):
        data = json.loads(VALID_JSON_RESPONSE)
        data["visual_quality_score"] = 1.5
        result = extractor._parse_and_validate(json.dumps(data))
        assert result["visual_quality_score"] == 1.0

    def test_float_clamped_below_zero(self, extractor):
        data = json.loads(VALID_JSON_RESPONSE)
        data["thumb_stop_prediction"] = -0.3
        result = extractor._parse_and_validate(json.dumps(data))
        assert result["thumb_stop_prediction"] == 0.0

    def test_headline_word_count_coerced_to_int(self, extractor):
        data = json.loads(VALID_JSON_RESPONSE)
        data["headline_word_count"] = "five"
        result = extractor._parse_and_validate(json.dumps(data))
        assert result["headline_word_count"] == 0

    def test_face_count_coerced_to_int(self, extractor):
        data = json.loads(VALID_JSON_RESPONSE)
        data["face_count"] = 2.5
        result = extractor._parse_and_validate(json.dumps(data))
        assert result["face_count"] == 2

    def test_null_face_emotion_allowed(self, extractor):
        data = json.loads(VALID_JSON_RESPONSE)
        data["face_emotion"] = None
        result = extractor._parse_and_validate(json.dumps(data))
        assert result["face_emotion"] is None


# ============================================================================
# _row_to_props tests
# ============================================================================

class TestRowToProps:
    def test_from_raw_extraction_json_string(self, extractor):
        row = {"raw_extraction": VALID_JSON_RESPONSE, "contrast_level": "low"}
        result = extractor._row_to_props(row)
        # raw_extraction takes priority
        assert result["contrast_level"] == "high"

    def test_from_raw_extraction_dict(self, extractor):
        data = json.loads(VALID_JSON_RESPONSE)
        row = {"raw_extraction": data}
        result = extractor._row_to_props(row)
        assert result["contrast_level"] == "high"

    def test_fallback_to_columns(self, extractor):
        row = {
            "raw_extraction": None,
            "contrast_level": "medium",
            "color_palette_type": "cool",
            "face_presence": True,
            "visual_quality_score": 0.5,
        }
        result = extractor._row_to_props(row)
        assert result["contrast_level"] == "medium"
        assert result["face_presence"] is True


# ============================================================================
# _resolve_org_id tests
# ============================================================================

class TestResolveOrgId:
    def test_non_all_passes_through(self, extractor):
        result = extractor._resolve_org_id("some-uuid", "brand-id")
        assert result == "some-uuid"

    def test_all_resolves_from_brand(self, extractor):
        extractor.supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"organization_id": "real-org-uuid"}]
        )
        result = extractor._resolve_org_id("all", "brand-id")
        assert result == "real-org-uuid"

    def test_all_fallback_on_error(self, extractor):
        extractor.supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.side_effect = Exception("DB error")
        result = extractor._resolve_org_id("all", "brand-id")
        assert result == "all"


# ============================================================================
# extract() cache hit test
# ============================================================================

class TestExtract:
    @pytest.mark.asyncio
    async def test_cache_hit_skips_gemini(self, extractor):
        """When cached visual props exist, Gemini should NOT be called."""
        cached_row = {
            "raw_extraction": VALID_JSON_RESPONSE,
            "contrast_level": "high",
        }
        extractor.supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[cached_row]
        )

        result = await extractor.extract("ad123", "brand1", "org1")
        assert result is not None
        assert result["contrast_level"] == "high"
        extractor.gemini.analyze_image.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_image_returns_none(self, extractor):
        """When no image is available, return None."""
        # Cache miss
        extractor.supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[]
        )
        # No asset
        extractor.supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[]
        )

        result = await extractor.extract("ad_no_image", "brand1", "org1")
        assert result is None
