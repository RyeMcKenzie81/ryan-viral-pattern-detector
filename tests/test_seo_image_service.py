"""
Tests for SEOImageService — image marker extraction, generation, and pipeline integration.

Tests cover:
- Marker extraction from all 4 formats
- Hero detection (explicit and first-marker fallback)
- Image metadata structure (success and failure)
- Pipeline node routing
- from_dict() unknown field stripping
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from uuid import UUID

from viraltracker.services.seo_pipeline.services.seo_image_service import (
    SEOImageService,
)
from viraltracker.services.seo_pipeline.state import SEOPipelineState


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def service():
    """Service with mocked dependencies."""
    mock_supabase = MagicMock()
    mock_gemini = AsyncMock()
    return SEOImageService(supabase_client=mock_supabase, gemini_service=mock_gemini)


# =============================================================================
# MARKER EXTRACTION
# =============================================================================

class TestExtractImageMarkers:
    def test_basic_image_marker(self, service):
        md = "Some text\n[IMAGE: A happy family walking their dog]\nMore text"
        markers = service.extract_image_markers(md)
        assert len(markers) == 1
        assert markers[0]["description"] == "A happy family walking their dog"
        # First marker becomes hero if no explicit hero
        assert markers[0]["type"] == "hero"

    def test_hero_image_marker(self, service):
        md = "[HERO IMAGE: Beautiful sunset over ocean]\n[IMAGE: Beach scene]"
        markers = service.extract_image_markers(md)
        assert len(markers) == 2
        assert markers[0]["type"] == "hero"
        assert markers[0]["description"] == "Beautiful sunset over ocean"
        assert markers[1]["type"] == "inline"

    def test_html_comment_featured(self, service):
        md = "<!-- FEATURED IMAGE: Product hero shot -->\nContent"
        markers = service.extract_image_markers(md)
        assert len(markers) == 1
        assert markers[0]["type"] == "hero"
        assert markers[0]["description"] == "Product hero shot"

    def test_html_comment_image(self, service):
        md = "Content\n<!-- IMAGE: Lifestyle photo -->\nMore"
        markers = service.extract_image_markers(md)
        assert len(markers) == 1
        assert markers[0]["description"] == "Lifestyle photo"

    def test_mixed_formats(self, service):
        md = (
            "[HERO IMAGE: Main product shot]\n"
            "Some content\n"
            "[IMAGE: Side view of product]\n"
            "More content\n"
            "<!-- IMAGE: Customer using product -->"
        )
        markers = service.extract_image_markers(md)
        assert len(markers) == 3
        assert markers[0]["type"] == "hero"
        assert markers[1]["type"] == "inline"
        assert markers[2]["type"] == "inline"

    def test_no_markers(self, service):
        md = "This is a plain article with no image markers."
        markers = service.extract_image_markers(md)
        assert markers == []

    def test_first_becomes_hero_when_no_explicit(self, service):
        md = "[IMAGE: First image]\n[IMAGE: Second image]"
        markers = service.extract_image_markers(md)
        assert markers[0]["type"] == "hero"
        assert markers[1]["type"] == "inline"

    def test_index_ordering(self, service):
        md = "[IMAGE: Third]\nSome text\n[IMAGE: First]\n[IMAGE: Second]"
        markers = service.extract_image_markers(md)
        # Should be in document order
        assert markers[0]["index"] == 0
        assert markers[1]["index"] == 1
        assert markers[2]["index"] == 2


# =============================================================================
# IMAGE TAG BUILDING
# =============================================================================

class TestBuildImgTag:
    def test_success_hero(self, service):
        entry = {
            "status": "success",
            "cdn_url": "https://cdn.example.com/hero.png",
            "alt_text": "Hero image",
            "type": "hero",
        }
        tag = service._build_img_tag(entry)
        assert 'src="https://cdn.example.com/hero.png"' in tag
        assert 'loading="eager"' in tag
        assert 'alt="Hero image"' in tag

    def test_success_inline(self, service):
        entry = {
            "status": "success",
            "cdn_url": "https://cdn.example.com/inline.png",
            "alt_text": "Inline image",
            "type": "inline",
        }
        tag = service._build_img_tag(entry)
        assert 'loading="lazy"' in tag

    def test_failed_image(self, service):
        entry = {"status": "failed", "cdn_url": None, "error": "Rate limit"}
        tag = service._build_img_tag(entry)
        assert "[Image unavailable]" in tag


# =============================================================================
# SLUG & FILENAME GENERATION
# =============================================================================

class TestHelpers:
    def test_generate_slug(self, service):
        assert service._generate_slug("Best Gaming PC 2026") == "best-gaming-pc-2026"
        assert service._generate_slug("  hello world  ") == "hello-world"
        assert service._generate_slug("") == "article"

    def test_generate_filename_hero(self, service):
        assert service._generate_filename("my-article", "hero", 0) == "my-article-hero.png"

    def test_generate_filename_inline(self, service):
        assert service._generate_filename("my-article", "inline", 2) == "my-article-inline-2.png"

    def test_storage_path(self, service):
        path = service._storage_path("brand-123", "my-article", "my-article-hero.png")
        assert path == "seo-articles/brand-123/my-article/my-article-hero.png"


# =============================================================================
# GENERATE ARTICLE IMAGES
# =============================================================================

class TestGenerateArticleImages:
    @pytest.mark.asyncio
    async def test_no_markers_returns_early(self, service):
        result = await service.generate_article_images(
            article_id="art-001",
            markdown="No markers here.",
            brand_id="brand-001",
            organization_id="org-001",
            keyword="test",
        )
        assert result["stats"]["total"] == 0
        assert result["hero_image_url"] is None
        assert result["updated_markdown"] == "No markers here."

    @pytest.mark.asyncio
    async def test_generates_and_uploads(self, service):
        """Full flow: extract, generate, upload, replace."""
        import base64

        # Mock Gemini to return base64 image
        fake_b64 = base64.b64encode(b"fake-png-data").decode()
        service._gemini.generate_image = AsyncMock(return_value=fake_b64)

        # Mock Supabase storage upload
        storage_mock = MagicMock()
        storage_mock.upload.return_value = None
        storage_mock.get_public_url.return_value = "https://cdn.example.com/img.png?"
        service._supabase.storage.from_.return_value = storage_mock

        # Mock DB save
        service._supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        # Mock usage tracker
        service._track_usage = MagicMock()

        md = "[HERO IMAGE: A beautiful sunset]\nContent here"
        result = await service.generate_article_images(
            article_id="art-001",
            markdown=md,
            brand_id="brand-001",
            organization_id="org-001",
            keyword="sunset article",
        )

        assert result["stats"]["total"] == 1
        assert result["stats"]["success"] == 1
        assert result["stats"]["failed"] == 0
        assert result["hero_image_url"] == "https://cdn.example.com/img.png"
        assert "<img" in result["updated_markdown"]
        assert "[HERO IMAGE:" not in result["updated_markdown"]

    @pytest.mark.asyncio
    async def test_failed_image_non_fatal(self, service):
        """Failed image generation should not crash the pipeline."""
        service._gemini.generate_image = AsyncMock(side_effect=Exception("Rate limit exceeded"))

        # Mock DB save
        service._supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        md = "[IMAGE: Something]\nContent"
        result = await service.generate_article_images(
            article_id="art-001",
            markdown=md,
            brand_id="brand-001",
            organization_id="org-001",
            keyword="test",
        )

        assert result["stats"]["total"] == 1
        assert result["stats"]["failed"] == 1
        assert result["hero_image_url"] is None
        assert "[Image unavailable]" in result["updated_markdown"]

        # Verify metadata captured the error
        meta = result["image_metadata"][0]
        assert meta["status"] == "failed"
        assert "Rate limit" in meta["error"]


# =============================================================================
# STATE from_dict() ROLLBACK SAFETY
# =============================================================================

class TestFromDictRollbackSafety:
    def test_unknown_fields_stripped(self):
        """from_dict() should strip unknown fields without crashing."""
        data = {
            "project_id": "00000000-0000-0000-0000-000000000001",
            "brand_id": "00000000-0000-0000-0000-000000000002",
            "organization_id": "00000000-0000-0000-0000-000000000003",
            "unknown_future_field": "should be stripped",
            "another_unknown": 42,
        }
        state = SEOPipelineState.from_dict(data)
        assert state.project_id == UUID("00000000-0000-0000-0000-000000000001")
        assert not hasattr(state, "unknown_future_field")

    def test_image_fields_preserved(self):
        """Image fields added in Phase 2 should deserialize correctly."""
        data = {
            "project_id": "00000000-0000-0000-0000-000000000001",
            "brand_id": "00000000-0000-0000-0000-000000000002",
            "organization_id": "00000000-0000-0000-0000-000000000003",
            "hero_image_url": "https://cdn.example.com/hero.png",
            "image_results": {"total": 2, "success": 1, "failed": 1},
        }
        state = SEOPipelineState.from_dict(data)
        assert state.hero_image_url == "https://cdn.example.com/hero.png"
        assert state.image_results["total"] == 2
