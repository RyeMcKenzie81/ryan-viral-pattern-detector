"""
Unit tests for ContentGapFillerService — pure logic (no DB required).

Covers:
- _normalize_and_validate() for all value types
- _merge_append() near-duplicate detection
- _values_equal() and _is_empty()
- _validate_scrape_url() SSRF protection
- _compute_source_hash()
- resolve_gap_key()
- _normalize_for_comparison()
- GAP_FIELD_REGISTRY completeness

Run with: pytest tests/test_content_gap_filler.py -v
"""

import json
import pytest
from unittest.mock import MagicMock

from viraltracker.services.landing_page_analysis.content_gap_filler_service import (
    ContentGapFillerService,
    GAP_FIELD_REGISTRY,
    GapFieldSpec,
    SourceCandidate,
    ApplyResult,
    resolve_gap_key,
    _normalize_for_comparison,
)


@pytest.fixture
def service():
    """Create a service with a mocked Supabase client."""
    mock_supabase = MagicMock()
    svc = ContentGapFillerService(supabase=mock_supabase)
    svc._user_id = "test-user-id"
    svc._org_id = "test-org-id"
    return svc


# ---------------------------------------------------------------------------
# GAP_FIELD_REGISTRY completeness
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_all_keys_have_valid_entity(self):
        valid_entities = {"brand", "product", "offer_variant"}
        for key, spec in GAP_FIELD_REGISTRY.items():
            assert spec.entity in valid_entities, f"{key} has invalid entity: {spec.entity}"

    def test_all_keys_have_valid_value_type(self):
        valid_types = {"text", "text_list", "qa_list", "timeline_list",
                       "json_array", "json", "quote_list", "complex"}
        for key, spec in GAP_FIELD_REGISTRY.items():
            assert spec.value_type in valid_types, f"{key} has invalid value_type: {spec.value_type}"

    def test_all_keys_have_valid_write_policy(self):
        valid_policies = {"allow_if_empty", "confirm_overwrite", "append"}
        for key, spec in GAP_FIELD_REGISTRY.items():
            assert spec.write_policy in valid_policies, f"{key} has invalid write_policy: {spec.write_policy}"

    def test_needs_setup_fields_are_not_auto_fillable(self):
        for key, spec in GAP_FIELD_REGISTRY.items():
            if spec.needs_setup:
                assert not spec.auto_fillable, f"{key} is needs_setup but also auto_fillable"

    def test_all_keys_match_spec_key(self):
        for key, spec in GAP_FIELD_REGISTRY.items():
            assert key == spec.key, f"Registry key '{key}' != spec.key '{spec.key}'"

    def test_non_setup_non_complex_have_column(self):
        for key, spec in GAP_FIELD_REGISTRY.items():
            if not spec.needs_setup and spec.value_type != "complex":
                assert spec.column is not None, f"{key} should have a column defined"

    def test_registry_has_expected_count(self):
        assert len(GAP_FIELD_REGISTRY) == 13


# ---------------------------------------------------------------------------
# resolve_gap_key
# ---------------------------------------------------------------------------

class TestResolveGapKey:
    def test_section_field_mapping(self):
        assert resolve_gap_key({"section": "guarantee", "field": "text"}) == "product.guarantee"

    def test_mechanism_name(self):
        assert resolve_gap_key({"section": "mechanism", "field": "name"}) == "offer_variant.mechanism.name"

    def test_mechanism_root_cause(self):
        assert resolve_gap_key({"section": "mechanism", "field": "root_cause"}) == "offer_variant.mechanism.root_cause"

    def test_pain_points(self):
        assert resolve_gap_key({"section": "pain_points", "field": "pain_points"}) == "offer_variant.pain_points"

    def test_voice_tone(self):
        assert resolve_gap_key({"section": "brand_basics", "field": "voice_tone"}) == "brand.voice_tone"

    def test_personas(self):
        assert resolve_gap_key({"section": "personas", "field": "personas"}) == "product.personas"

    def test_pricing(self):
        assert resolve_gap_key({"section": "pricing", "field": "pricing"}) == "product.pricing"

    def test_unknown_field_returns_none(self):
        assert resolve_gap_key({"section": "unknown", "field": "unknown"}) is None

    def test_empty_gap_returns_none(self):
        assert resolve_gap_key({}) is None

    def test_fallback_to_field_only(self):
        # "guarantee" maps via field-only fallback
        assert resolve_gap_key({"section": "something", "field": "guarantee"}) == "product.guarantee"


# ---------------------------------------------------------------------------
# _normalize_for_comparison
# ---------------------------------------------------------------------------

class TestNormalizeForComparison:
    def test_basic(self):
        assert _normalize_for_comparison("  Hello World  ") == "hello world"

    def test_removes_punctuation(self):
        # "it's" -> "its" (stopword, removed), "a" (stopword, removed), "test!" -> "test"
        assert _normalize_for_comparison("it's a test!") == "test"

    def test_removes_stopwords(self):
        assert _normalize_for_comparison("The quick brown fox") == "quick brown fox"

    def test_collapses_whitespace(self):
        assert _normalize_for_comparison("multiple   spaces   here") == "multiple spaces here"


# ---------------------------------------------------------------------------
# _normalize_and_validate
# ---------------------------------------------------------------------------

class TestValidateText:
    def test_valid_text(self, service):
        spec = GAP_FIELD_REGISTRY["product.guarantee"]
        result = service._normalize_and_validate(spec, "  365-day guarantee  ")
        assert result == "365-day guarantee"

    def test_empty_text_raises(self, service):
        spec = GAP_FIELD_REGISTRY["product.guarantee"]
        with pytest.raises(ValueError, match="cannot be empty"):
            service._normalize_and_validate(spec, "   ")

    def test_collapses_whitespace(self, service):
        spec = GAP_FIELD_REGISTRY["product.guarantee"]
        result = service._normalize_and_validate(spec, "hello    world")
        assert result == "hello world"

    def test_non_string_coerced(self, service):
        spec = GAP_FIELD_REGISTRY["product.guarantee"]
        result = service._normalize_and_validate(spec, 123)
        assert result == "123"


class TestValidateTextList:
    def test_valid_list(self, service):
        spec = GAP_FIELD_REGISTRY["offer_variant.pain_points"]
        result = service._normalize_and_validate(spec, ["Joint pain", "Stiffness"])
        assert result == ["Joint pain", "Stiffness"]

    def test_string_split_by_newline(self, service):
        spec = GAP_FIELD_REGISTRY["offer_variant.pain_points"]
        result = service._normalize_and_validate(spec, "Joint pain\nStiffness\nFatigue")
        assert result == ["Joint pain", "Stiffness", "Fatigue"]

    def test_string_split_by_semicolon(self, service):
        spec = GAP_FIELD_REGISTRY["offer_variant.pain_points"]
        result = service._normalize_and_validate(spec, "Joint pain;Stiffness;Fatigue")
        assert result == ["Joint pain", "Stiffness", "Fatigue"]

    def test_deduplicates(self, service):
        spec = GAP_FIELD_REGISTRY["offer_variant.pain_points"]
        result = service._normalize_and_validate(spec, ["pain", "PAIN", "other"])
        assert result == ["pain", "other"]

    def test_removes_empty(self, service):
        spec = GAP_FIELD_REGISTRY["offer_variant.pain_points"]
        result = service._normalize_and_validate(spec, ["valid", "", "  ", "also valid"])
        assert result == ["valid", "also valid"]

    def test_empty_list_raises(self, service):
        spec = GAP_FIELD_REGISTRY["offer_variant.pain_points"]
        with pytest.raises(ValueError, match="at least 1 item"):
            service._normalize_and_validate(spec, [])


class TestValidateQAList:
    def test_valid_qa(self, service):
        spec = GAP_FIELD_REGISTRY["product.faq_items"]
        value = [{"question": "How does it work?", "answer": "It works great."}]
        result = service._normalize_and_validate(spec, value)
        assert result == [{"question": "How does it work?", "answer": "It works great."}]

    def test_from_json_string(self, service):
        spec = GAP_FIELD_REGISTRY["product.faq_items"]
        value = json.dumps([{"question": "Q?", "answer": "A."}])
        result = service._normalize_and_validate(spec, value)
        assert result == [{"question": "Q?", "answer": "A."}]

    def test_strips_whitespace(self, service):
        spec = GAP_FIELD_REGISTRY["product.faq_items"]
        value = [{"question": "  Q?  ", "answer": "  A.  "}]
        result = service._normalize_and_validate(spec, value)
        assert result == [{"question": "Q?", "answer": "A."}]

    def test_skips_empty_qa(self, service):
        spec = GAP_FIELD_REGISTRY["product.faq_items"]
        value = [
            {"question": "Q?", "answer": "A."},
            {"question": "", "answer": "orphan"},
            {"question": "Q2?", "answer": ""},
        ]
        result = service._normalize_and_validate(spec, value)
        assert len(result) == 1

    def test_empty_raises(self, service):
        spec = GAP_FIELD_REGISTRY["product.faq_items"]
        with pytest.raises(ValueError, match="at least 1 item"):
            service._normalize_and_validate(spec, [])

    def test_invalid_json_raises(self, service):
        spec = GAP_FIELD_REGISTRY["product.faq_items"]
        with pytest.raises(ValueError, match="Invalid JSON"):
            service._normalize_and_validate(spec, "not json")


class TestValidateTimelineList:
    def test_valid_timeline(self, service):
        spec = GAP_FIELD_REGISTRY["product.results_timeline"]
        value = [{"timeframe": "Week 1-2", "expected_result": "Initial improvements"}]
        result = service._normalize_and_validate(spec, value)
        assert result == [{"timeframe": "Week 1-2", "expected_result": "Initial improvements"}]

    def test_empty_raises(self, service):
        spec = GAP_FIELD_REGISTRY["product.results_timeline"]
        with pytest.raises(ValueError):
            service._normalize_and_validate(spec, [])


class TestValidateJsonArray:
    def test_valid_json_array(self, service):
        spec = GAP_FIELD_REGISTRY["product.ingredients"]
        value = [{"name": "Collagen", "benefit": "Joint support", "proof_point": "Clinical study"}]
        result = service._normalize_and_validate(spec, value)
        assert len(result) == 1

    def test_from_json_string(self, service):
        spec = GAP_FIELD_REGISTRY["product.ingredients"]
        value = json.dumps([{"name": "Vitamin D"}])
        result = service._normalize_and_validate(spec, value)
        assert result == [{"name": "Vitamin D"}]

    def test_empty_raises(self, service):
        spec = GAP_FIELD_REGISTRY["product.ingredients"]
        with pytest.raises(ValueError, match="must not be empty"):
            service._normalize_and_validate(spec, [])

    def test_non_list_raises(self, service):
        spec = GAP_FIELD_REGISTRY["product.ingredients"]
        with pytest.raises(ValueError, match="Expected a JSON array"):
            service._normalize_and_validate(spec, {"key": "value"})


class TestValidateQuoteListAndComplex:
    def test_quote_list_raises(self, service):
        spec = GAP_FIELD_REGISTRY["product.top_positive_quotes"]
        with pytest.raises(ValueError, match="requires special handling"):
            service._normalize_and_validate(spec, ["quote"])

    def test_complex_raises(self, service):
        spec = GAP_FIELD_REGISTRY["product.pricing"]
        with pytest.raises(ValueError, match="requires special handling"):
            service._normalize_and_validate(spec, "anything")


# ---------------------------------------------------------------------------
# _merge_append
# ---------------------------------------------------------------------------

class TestMergeAppend:
    def test_empty_existing(self, service):
        result = service._merge_append([], ["new1", "new2"], "manual")
        assert result == ["new1", "new2"]

    def test_none_existing(self, service):
        result = service._merge_append(None, ["new1"], "manual")
        assert result == ["new1"]

    def test_dedup_exact(self, service):
        result = service._merge_append(["Joint pain"], ["Joint pain"], "manual")
        assert result == ["Joint pain"]

    def test_dedup_near_match(self, service):
        result = service._merge_append(
            ["Joint stiffness in the morning"],
            ["Joint stiffness in mornings"],
            "manual",
        )
        # These should be caught as near-duplicates (high similarity after normalization)
        assert len(result) == 1

    def test_adds_new_items(self, service):
        result = service._merge_append(
            ["Existing pain"],
            ["Completely different issue"],
            "manual",
        )
        assert len(result) == 2

    def test_cap_at_15(self, service):
        existing = [f"item_{i}" for i in range(12)]
        new = [f"new_item_{i}" for i in range(10)]
        result = service._merge_append(existing, new, "manual")
        assert len(result) <= 15

    def test_string_existing_converted(self, service):
        result = service._merge_append("single string", ["new"], "manual")
        assert result == ["single string", "new"]


# ---------------------------------------------------------------------------
# _values_equal and _is_empty
# ---------------------------------------------------------------------------

class TestValuesEqual:
    def test_both_none(self, service):
        assert service._values_equal(None, None) is True

    def test_one_none(self, service):
        assert service._values_equal(None, "value") is False
        assert service._values_equal("value", None) is False

    def test_same_string(self, service):
        assert service._values_equal("hello", "hello") is True

    def test_same_list(self, service):
        assert service._values_equal(["a", "b"], ["a", "b"]) is True

    def test_different_list(self, service):
        assert service._values_equal(["a", "b"], ["a", "c"]) is False

    def test_same_dict(self, service):
        assert service._values_equal({"a": 1}, {"a": 1}) is True


class TestIsEmpty:
    def test_none(self, service):
        assert service._is_empty(None) is True

    def test_empty_string(self, service):
        assert service._is_empty("") is True
        assert service._is_empty("   ") is True

    def test_non_empty_string(self, service):
        assert service._is_empty("value") is False

    def test_empty_list(self, service):
        assert service._is_empty([]) is True

    def test_non_empty_list(self, service):
        assert service._is_empty(["item"]) is False

    def test_empty_dict(self, service):
        assert service._is_empty({}) is True

    def test_non_empty_dict(self, service):
        assert service._is_empty({"key": "val"}) is False


# ---------------------------------------------------------------------------
# _validate_scrape_url (SSRF)
# ---------------------------------------------------------------------------

class TestValidateScrapeUrl:
    def test_valid_https(self, service):
        # Should not raise for a valid public URL
        service._validate_scrape_url("https://example.com/page")

    def test_rejects_http(self, service):
        with pytest.raises(ValueError, match="Only HTTPS"):
            service._validate_scrape_url("http://example.com")

    def test_rejects_ftp(self, service):
        with pytest.raises(ValueError, match="Only HTTPS"):
            service._validate_scrape_url("ftp://example.com/file")

    def test_rejects_empty(self, service):
        with pytest.raises(ValueError, match="URL is required"):
            service._validate_scrape_url("")

    def test_rejects_localhost(self, service):
        with pytest.raises(ValueError, match="private|reserved"):
            service._validate_scrape_url("https://localhost/admin")

    def test_rejects_127(self, service):
        with pytest.raises(ValueError, match="private|reserved"):
            service._validate_scrape_url("https://127.0.0.1/admin")

    def test_rejects_private_10(self, service):
        with pytest.raises(ValueError, match="private|reserved"):
            service._validate_scrape_url("https://10.0.0.1/internal")

    def test_rejects_private_192(self, service):
        with pytest.raises(ValueError, match="private|reserved"):
            service._validate_scrape_url("https://192.168.1.1/router")

    def test_rejects_private_172(self, service):
        with pytest.raises(ValueError, match="private|reserved"):
            service._validate_scrape_url("https://172.16.0.1/internal")

    def test_rejects_no_hostname(self, service):
        with pytest.raises(ValueError):
            service._validate_scrape_url("https:///path")


# ---------------------------------------------------------------------------
# _compute_source_hash
# ---------------------------------------------------------------------------

class TestComputeSourceHash:
    def test_deterministic(self, service):
        inputs = [{"source_type": "amazon", "source_table": "t", "source_id": "1",
                    "url": "https://example.com", "snippet": "hello", "scraped_at": "2026-01-01"}]
        h1 = service._compute_source_hash(inputs)
        h2 = service._compute_source_hash(inputs)
        assert h1 == h2

    def test_different_inputs_different_hash(self, service):
        inputs1 = [{"source_type": "amazon", "source_table": "t", "source_id": "1",
                     "url": "", "snippet": "hello", "scraped_at": ""}]
        inputs2 = [{"source_type": "amazon", "source_table": "t", "source_id": "1",
                     "url": "", "snippet": "world", "scraped_at": ""}]
        assert service._compute_source_hash(inputs1) != service._compute_source_hash(inputs2)

    def test_order_independent(self, service):
        inputs_a = [
            {"source_type": "a", "source_table": "t", "source_id": "1", "url": "", "snippet": "", "scraped_at": ""},
            {"source_type": "b", "source_table": "t", "source_id": "2", "url": "", "snippet": "", "scraped_at": ""},
        ]
        inputs_b = [
            {"source_type": "b", "source_table": "t", "source_id": "2", "url": "", "snippet": "", "scraped_at": ""},
            {"source_type": "a", "source_table": "t", "source_id": "1", "url": "", "snippet": "", "scraped_at": ""},
        ]
        assert service._compute_source_hash(inputs_a) == service._compute_source_hash(inputs_b)

    def test_url_normalization(self, service):
        inputs1 = [{"source_type": "x", "source_table": "t", "source_id": "1",
                     "url": "https://Example.com/Path/", "snippet": "", "scraped_at": ""}]
        inputs2 = [{"source_type": "x", "source_table": "t", "source_id": "1",
                     "url": "https://example.com/path", "snippet": "", "scraped_at": ""}]
        assert service._compute_source_hash(inputs1) == service._compute_source_hash(inputs2)

    def test_returns_hex_sha256(self, service):
        h = service._compute_source_hash([{"source_type": "", "source_table": "",
                                            "source_id": "", "url": "", "snippet": "", "scraped_at": ""}])
        assert len(h) == 64  # SHA-256 hex length
        assert all(c in "0123456789abcdef" for c in h)
