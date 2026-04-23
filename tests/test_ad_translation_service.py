"""
Ad Translation Service Tests

Tests for ad lookup, language normalization, identifier parsing,
copy translation, prompt spec modification, single ad translation,
batch translation, and filename suffix generation.

Run with: pytest tests/test_ad_translation_service.py -v
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

from viraltracker.services.ad_translation_service import (
    AdTranslationService,
    _LANGUAGE_MAP,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_supabase():
    """Mock Supabase client with chainable query builder."""
    client = MagicMock()
    return client


@pytest.fixture
def mock_gemini():
    """Mock GeminiService."""
    gemini = MagicMock()
    gemini.generate_image = AsyncMock(return_value={
        "image_base64": "dGVzdA==",
        "model_requested": "gemini-3-pro",
        "model_used": "gemini-3-pro",
        "retries": 0,
    })
    return gemini


@pytest.fixture
def mock_ad_creation():
    """Mock AdCreationService."""
    svc = MagicMock()
    svc.get_ad_for_variant = AsyncMock()
    svc.save_generated_ad = AsyncMock()
    svc.create_ad_run = AsyncMock()
    svc.update_ad_run = AsyncMock()
    svc.upload_generated_ad = AsyncMock(return_value=("ads/test/image.png", "image.png"))
    svc.download_image = AsyncMock(return_value=b"fake_image_bytes")
    return svc


@pytest.fixture
def service(mock_supabase, mock_gemini, mock_ad_creation):
    return AdTranslationService(
        supabase=mock_supabase,
        gemini_service=mock_gemini,
        ad_creation_service=mock_ad_creation,
    )


# ============================================================================
# _parse_ad_identifier
# ============================================================================

class TestParseAdIdentifier:
    def test_full_uuid_with_hyphens(self, service):
        result = service._parse_ad_identifier("65bb40a1-1234-5678-9abc-def012345678")
        assert result["type"] == "uuid"
        assert result["value"] == "65bb40a1-1234-5678-9abc-def012345678"

    def test_full_uuid_without_hyphens(self, service):
        result = service._parse_ad_identifier("65bb40a112345678abcdef0123456789")
        assert result["type"] == "uuid"
        assert result["value"] == "65bb40a1-1234-5678-abcd-ef0123456789"

    def test_structured_filename(self, service):
        result = service._parse_ad_identifier("SAV-FTS-65bb40-04161b-SQ")
        assert result["type"] == "filename_fragment"
        assert result["value"] == "04161b"

    def test_m5_format(self, service):
        result = service._parse_ad_identifier("M5-d4e5f6a7-WP-C3-SQ.png")
        assert result["type"] == "filename_fragment"
        assert result["value"] == "d4e5f6a7"

    def test_bare_hex_6_chars(self, service):
        result = service._parse_ad_identifier("65bb40")
        assert result["type"] == "filename_fragment"
        assert result["value"] == "65bb40"

    def test_bare_hex_8_chars(self, service):
        result = service._parse_ad_identifier("65bb40a1")
        assert result["type"] == "filename_fragment"
        assert result["value"] == "65bb40a1"

    def test_meta_ad_id_numeric(self, service):
        result = service._parse_ad_identifier("23851234567890")
        assert result["type"] == "meta_ad_id"
        assert result["value"] == "23851234567890"

    def test_unknown_format(self, service):
        result = service._parse_ad_identifier("not a valid id at all")
        assert result["type"] == "unknown"

    def test_whitespace_stripped(self, service):
        result = service._parse_ad_identifier("  65bb40  ")
        assert result["type"] == "filename_fragment"
        assert result["value"] == "65bb40"


# ============================================================================
# _normalize_language
# ============================================================================

class TestNormalizeLanguage:
    def test_ietf_tag_passthrough(self, service):
        assert service._normalize_language("es-MX") == "es-MX"

    def test_ietf_tag_case_normalization(self, service):
        assert service._normalize_language("PT-br") == "pt-BR"

    def test_iso_code(self, service):
        assert service._normalize_language("es") == "es"

    def test_iso_code_case(self, service):
        assert service._normalize_language("FR") == "fr"

    def test_full_name_spanish(self, service):
        assert service._normalize_language("Spanish") == "es"

    def test_full_name_mexican_spanish(self, service):
        assert service._normalize_language("Mexican Spanish") == "es-MX"

    def test_full_name_brazilian_portuguese(self, service):
        assert service._normalize_language("Brazilian Portuguese") == "pt-BR"

    def test_native_name(self, service):
        assert service._normalize_language("español") == "es"

    def test_native_name_japanese(self, service):
        assert service._normalize_language("日本語") == "ja"

    def test_underscore_separator(self, service):
        assert service._normalize_language("es_MX") == "es-MX"

    def test_unknown_fallback(self, service):
        result = service._normalize_language("Klingon")
        assert result == "klingon"


# ============================================================================
# _swap_prompt_spec_text
# ============================================================================

class TestSwapPromptSpecText:
    def test_primary_path(self, service):
        spec = {
            "content": {
                "headline": {"text": "Original hook", "font_size": 48},
                "subheadline": {"text": "Original benefit", "font_size": 24},
            }
        }
        result = service._swap_prompt_spec_text(spec, "Gancho traducido", "Beneficio traducido")
        assert result["content"]["headline"]["text"] == "Gancho traducido"
        assert result["content"]["subheadline"]["text"] == "Beneficio traducido"

    def test_headline_only(self, service):
        spec = {
            "content": {
                "headline": {"text": "Original hook"},
            }
        }
        result = service._swap_prompt_spec_text(spec, "Gancho traducido")
        assert result["content"]["headline"]["text"] == "Gancho traducido"

    def test_no_benefit_translation(self, service):
        spec = {
            "content": {
                "headline": {"text": "Original"},
                "subheadline": {"text": "Stays same"},
            }
        }
        result = service._swap_prompt_spec_text(spec, "Traducido", None)
        assert result["content"]["headline"]["text"] == "Traducido"
        assert result["content"]["subheadline"]["text"] == "Stays same"

    def test_does_not_mutate_original(self, service):
        spec = {"content": {"headline": {"text": "Original"}}}
        result = service._swap_prompt_spec_text(spec, "Nuevo")
        assert spec["content"]["headline"]["text"] == "Original"
        assert result["content"]["headline"]["text"] == "Nuevo"

    def test_fallback_recursive_replacement(self, service):
        """When content.headline.text path doesn't exist, falls back to recursive search."""
        spec = {
            "layout": {
                "headline_block": {"text": "Original", "style": "bold"},
            }
        }
        result = service._swap_prompt_spec_text(spec, "Traducido")
        assert result["layout"]["headline_block"]["text"] == "Traducido"

    def test_empty_spec(self, service):
        spec = {}
        result = service._swap_prompt_spec_text(spec, "Traducido")
        assert result == {}


# ============================================================================
# translate_ad_copy (mocked Anthropic)
# ============================================================================

class TestTranslateAdCopy:
    @pytest.mark.asyncio
    async def test_translates_all_fields(self, service):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps({
            "hook_text": "Tu piel merece lo mejor",
            "meta_headline": "Descubre el secreto",
            "meta_primary_text": "Miles de clientes satisfechos",
        }))]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        service._anthropic = mock_client

        result = await service.translate_ad_copy(
            hook_text="Your skin deserves the best",
            meta_headline="Discover the secret",
            meta_primary_text="Thousands of happy customers",
            target_language="es-MX",
        )

        assert result["hook_text"] == "Tu piel merece lo mejor"
        assert result["meta_headline"] == "Descubre el secreto"
        assert result["meta_primary_text"] == "Miles de clientes satisfechos"

    @pytest.mark.asyncio
    async def test_handles_code_fence_response(self, service):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='```json\n{"hook_text": "Traducido"}\n```')]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        service._anthropic = mock_client

        result = await service.translate_ad_copy(
            hook_text="Original",
            meta_headline=None,
            meta_primary_text=None,
            target_language="es",
        )

        assert result["hook_text"] == "Traducido"

    @pytest.mark.asyncio
    async def test_skips_none_fields(self, service):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"hook_text": "Traducido"}')]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        service._anthropic = mock_client

        result = await service.translate_ad_copy(
            hook_text="Original",
            meta_headline=None,
            meta_primary_text=None,
            target_language="es",
        )

        assert result["hook_text"] == "Traducido"
        assert result["meta_headline"] is None
        assert result["meta_primary_text"] is None


# ============================================================================
# translate_single_ad
# ============================================================================

class TestTranslateSingleAd:
    @pytest.mark.asyncio
    async def test_skips_already_translated(self, service, mock_supabase):
        """Idempotency: skip if translation already exists."""
        existing_id = str(uuid4())
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"id": existing_id}]
        )

        result = await service.translate_single_ad(uuid4(), "es-MX")
        assert result["status"] == "exists"
        assert result["reason"] == "already_translated"

    @pytest.mark.asyncio
    async def test_error_source_not_found(self, service, mock_supabase, mock_ad_creation):
        """Error when source ad doesn't exist."""
        # Idempotency check returns empty
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
        mock_ad_creation.get_ad_for_variant.return_value = None

        result = await service.translate_single_ad(uuid4(), "es-MX")
        assert result["status"] == "error"
        assert result["reason"] == "source_not_found"

    @pytest.mark.asyncio
    async def test_error_no_prompt_spec(self, service, mock_supabase, mock_ad_creation):
        """Error when source ad has no prompt_spec."""
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
        mock_ad_creation.get_ad_for_variant.return_value = {
            "hook_text": "Hook",
            "prompt_spec": None,
            "storage_path": "ads/test.png",
            "ad_run_id": str(uuid4()),
        }

        result = await service.translate_single_ad(uuid4(), "es-MX")
        assert result["status"] == "error"
        assert result["reason"] == "no_prompt_spec"


# ============================================================================
# translate_batch
# ============================================================================

class TestTranslateBatch:
    @pytest.mark.asyncio
    async def test_error_no_params(self, service):
        """Error when neither ad_ids nor product_id+top_n provided."""
        result = await service.translate_batch(target_language="es-MX")
        assert result["status"] == "error"
        assert result["reason"] == "invalid_params"

    @pytest.mark.asyncio
    async def test_language_normalization_in_batch(self, service, mock_supabase, mock_ad_creation):
        """Batch normalizes language name to IETF tag."""
        # Make it return no ads to shortcircuit
        mock_ad_creation.get_ad_for_variant.return_value = None
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])

        ad_id = uuid4()
        # This triggers translate_single_ad for each, but the first call (idempotency check)
        # and get_ad_for_variant will return no data since we need product_id
        mock_ad_creation.get_ad_for_variant.return_value = {
            "hook_text": "Test",
            "prompt_spec": None,
            "ad_run_id": str(uuid4()),
            "ad_runs": {"product_id": str(uuid4())},
        }
        mock_ad_creation.create_ad_run.return_value = uuid4()
        mock_ad_creation.update_ad_run.return_value = None

        result = await service.translate_batch(
            ad_ids=[str(ad_id)],
            target_language="Spanish",
        )
        # Should have normalized "Spanish" to "es"
        assert result["target_language"] == "es"


# ============================================================================
# Filename suffix (AdCreationService)
# ============================================================================

class TestFilenameSuffix:
    def test_english_no_suffix(self):
        from viraltracker.services.ad_creation_service import AdCreationService
        svc = AdCreationService.__new__(AdCreationService)
        result = svc.generate_ad_filename("WP", "C3", uuid4(), uuid4(), "SQ", language="en")
        assert "-EN" not in result
        assert result.endswith(".png")

    def test_none_language_no_suffix(self):
        from viraltracker.services.ad_creation_service import AdCreationService
        svc = AdCreationService.__new__(AdCreationService)
        result = svc.generate_ad_filename("WP", "C3", uuid4(), uuid4(), "SQ", language=None)
        assert result.count("-") == 4  # M5-{ad}-{brand}-{product}-{format}

    def test_spanish_suffix(self):
        from viraltracker.services.ad_creation_service import AdCreationService
        svc = AdCreationService.__new__(AdCreationService)
        ad_id = uuid4()
        result = svc.generate_ad_filename("WP", "C3", uuid4(), ad_id, "SQ", language="es-MX")
        assert result.endswith("-ES.png")

    def test_portuguese_suffix(self):
        from viraltracker.services.ad_creation_service import AdCreationService
        svc = AdCreationService.__new__(AdCreationService)
        result = svc.generate_ad_filename("WP", "C3", uuid4(), uuid4(), "SQ", language="pt-BR")
        assert "-PT." in result


class TestExportUtilsFilenameSuffix:
    def test_english_no_suffix(self):
        from viraltracker.ui.export_utils import generate_structured_filename
        result = generate_structured_filename("WP", "C3", str(uuid4()), str(uuid4()), "SQ", language="en")
        assert "-EN" not in result

    def test_spanish_suffix(self):
        from viraltracker.ui.export_utils import generate_structured_filename
        result = generate_structured_filename("WP", "C3", str(uuid4()), str(uuid4()), "SQ", language="es-MX")
        assert result.endswith("-ES.png")

    def test_none_language_no_suffix(self):
        from viraltracker.ui.export_utils import generate_structured_filename
        result = generate_structured_filename("WP", "C3", str(uuid4()), str(uuid4()), "SQ", language=None)
        assert result.count("-") == 4  # {bc}-{pc}-{run}-{ad}-{format}
