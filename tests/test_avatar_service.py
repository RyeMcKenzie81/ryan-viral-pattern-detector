"""
Tests for AvatarService — 4-angle workflow + Kling element creation.

Covers:
- BrandAvatar model properties (reference_images, reference_image_count)
- generate_angle_image() slot validation, reference chaining, safety filter handling
- create_kling_element() missing frontal, happy path
- add_reference_image() kling_element_id invalidation
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from uuid import UUID, uuid4
from datetime import datetime


# ============================================================================
# Fixtures
# ============================================================================

def _make_avatar_row(
    avatar_id=None,
    brand_id=None,
    ref1="avatars/brand/avatar/ref1.png",
    ref2=None,
    ref3=None,
    ref4=None,
    kling_element_id=None,
    generation_prompt="Professional woman, 30s, friendly smile",
):
    """Build a standard brand_avatars DB row."""
    return {
        "id": str(avatar_id or uuid4()),
        "brand_id": str(brand_id or uuid4()),
        "name": "Test Avatar",
        "description": "Test description",
        "reference_image_1": ref1,
        "reference_image_2": ref2,
        "reference_image_3": ref3,
        "reference_image_4": ref4,
        "kling_element_id": kling_element_id,
        "generation_prompt": generation_prompt,
        "default_negative_prompt": "blurry, low quality",
        "default_aspect_ratio": "16:9",
        "default_resolution": "1080p",
        "default_duration_seconds": 8,
        "is_active": True,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }


@pytest.fixture
def mock_supabase():
    """Mock Supabase client with fluent API."""
    mock = MagicMock()

    # Table operations
    table = MagicMock()
    table.insert.return_value.execute.return_value = MagicMock(data=[{"id": "gen-123"}])
    table.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
    table.update.return_value.eq.return_value.not_.return_value.is_.return_value.execute.return_value = MagicMock(data=[])
    table.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(data=None)
    table.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
    table.delete.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
    mock.table.return_value = table

    # Storage operations
    storage = MagicMock()
    storage.upload.return_value = None
    storage.download.return_value = b"fake-image-bytes"
    storage.create_signed_url.return_value = {"signedURL": "https://signed-url.example.com"}
    storage.remove.return_value = None
    mock.storage.from_.return_value = storage

    return mock


@pytest.fixture
def mock_gemini():
    """Mock GeminiService."""
    gemini = MagicMock()
    # generate_image is async in practice but called via generate_avatar_image
    # which wraps it. We mock the high-level generate_image.
    import base64
    fake_b64 = base64.b64encode(b"generated-image-bytes").decode("utf-8")
    gemini.generate_image = AsyncMock(return_value=fake_b64)
    gemini.set_tracking_context = MagicMock()
    return gemini


@pytest.fixture
def service(mock_supabase, mock_gemini):
    """Create AvatarService with mocked dependencies."""
    with patch(
        "viraltracker.services.avatar_service.get_supabase_client",
        return_value=mock_supabase,
    ):
        from viraltracker.services.avatar_service import AvatarService
        svc = AvatarService(gemini_service=mock_gemini)
    return svc


# ============================================================================
# BrandAvatar Model Tests
# ============================================================================

class TestBrandAvatarModel:
    """Test BrandAvatar model properties."""

    def test_reference_images_all_four(self):
        """reference_images includes all 4 slots when populated."""
        from viraltracker.services.veo_models import BrandAvatar
        avatar = BrandAvatar(
            id=uuid4(),
            brand_id=uuid4(),
            name="Test",
            reference_image_1="path/1.png",
            reference_image_2="path/2.png",
            reference_image_3="path/3.png",
            reference_image_4="path/4.png",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        assert avatar.reference_images == [
            "path/1.png", "path/2.png", "path/3.png", "path/4.png"
        ]
        assert avatar.reference_image_count == 4

    def test_reference_images_partial(self):
        """reference_images only includes non-null slots."""
        from viraltracker.services.veo_models import BrandAvatar
        avatar = BrandAvatar(
            id=uuid4(),
            brand_id=uuid4(),
            name="Test",
            reference_image_1="path/1.png",
            reference_image_3="path/3.png",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        assert avatar.reference_images == ["path/1.png", "path/3.png"]
        assert avatar.reference_image_count == 2

    def test_reference_images_empty(self):
        """reference_images is empty when no slots populated."""
        from viraltracker.services.veo_models import BrandAvatar
        avatar = BrandAvatar(
            id=uuid4(),
            brand_id=uuid4(),
            name="Test",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        assert avatar.reference_images == []
        assert avatar.reference_image_count == 0


# ============================================================================
# generate_angle_image Tests
# ============================================================================

class TestGenerateAngleImage:
    """Test angle-specific image generation."""

    @pytest.mark.asyncio
    async def test_invalid_slot_raises(self, service):
        """Slot outside 1-4 raises ValueError."""
        with pytest.raises(ValueError, match="Slot must be 1-4"):
            await service.generate_angle_image(uuid4(), slot=5)

        with pytest.raises(ValueError, match="Slot must be 1-4"):
            await service.generate_angle_image(uuid4(), slot=0)

    @pytest.mark.asyncio
    async def test_avatar_not_found_returns_none(self, service, mock_supabase):
        """Returns None if avatar doesn't exist."""
        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(data=None)

        result = await service.generate_angle_image(uuid4(), slot=1)
        assert result is None

    @pytest.mark.asyncio
    async def test_reference_chaining_slot2_uses_slot1(self, service, mock_supabase, mock_gemini):
        """Generating slot 2 uses slot 1 image as reference."""
        avatar_id = uuid4()
        brand_id = uuid4()
        row = _make_avatar_row(avatar_id=avatar_id, brand_id=brand_id, ref1="avatars/b/a/ref1.png")

        # get_avatar call
        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(data=row)
        # download returns fake bytes for prior slot
        mock_supabase.storage.from_.return_value.download.return_value = b"slot1-image"

        await service.generate_angle_image(avatar_id, slot=2)

        # Verify generate_image was called with reference_images containing slot 1
        call_args = mock_gemini.generate_image.call_args
        assert call_args is not None
        ref_images = call_args.kwargs.get("reference_images") or call_args[1].get("reference_images")
        assert ref_images is not None
        assert len(ref_images) == 1  # Only slot 1 as reference

    @pytest.mark.asyncio
    async def test_reference_chaining_slot1_no_refs(self, service, mock_supabase, mock_gemini):
        """Generating slot 1 uses no prior references."""
        avatar_id = uuid4()
        brand_id = uuid4()
        row = _make_avatar_row(avatar_id=avatar_id, brand_id=brand_id, ref1=None)

        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(data=row)

        await service.generate_angle_image(avatar_id, slot=1)

        call_args = mock_gemini.generate_image.call_args
        assert call_args is not None
        ref_images = call_args.kwargs.get("reference_images") or call_args[1].get("reference_images")
        assert ref_images is None  # No references for slot 1

    @pytest.mark.asyncio
    async def test_safety_filter_returns_none(self, service, mock_supabase, mock_gemini):
        """Safety filter error returns None instead of raising."""
        avatar_id = uuid4()
        row = _make_avatar_row(avatar_id=avatar_id)

        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(data=row)
        mock_gemini.generate_image.side_effect = Exception("Content blocked by safety filter")

        result = await service.generate_angle_image(avatar_id, slot=1)
        assert result is None

    @pytest.mark.asyncio
    async def test_non_safety_error_raises(self, service, mock_supabase, mock_gemini):
        """Non-safety errors propagate."""
        avatar_id = uuid4()
        row = _make_avatar_row(avatar_id=avatar_id)

        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(data=row)
        mock_gemini.generate_image.side_effect = Exception("Network timeout")

        with pytest.raises(Exception, match="Network timeout"):
            await service.generate_angle_image(avatar_id, slot=1)

    @pytest.mark.asyncio
    async def test_prompt_includes_angle_template(self, service, mock_supabase, mock_gemini):
        """Generated prompt includes the angle-specific template."""
        avatar_id = uuid4()
        row = _make_avatar_row(avatar_id=avatar_id, generation_prompt="A tall woman with red hair")

        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(data=row)

        await service.generate_angle_image(avatar_id, slot=3)

        call_args = mock_gemini.generate_image.call_args
        prompt = call_args.kwargs.get("prompt") or call_args[1].get("prompt")
        assert "A tall woman with red hair" in prompt
        assert "Side profile" in prompt

    @pytest.mark.asyncio
    async def test_temperature_is_low(self, service, mock_supabase, mock_gemini):
        """Uses low temperature (0.3) for consistency."""
        avatar_id = uuid4()
        row = _make_avatar_row(avatar_id=avatar_id)

        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(data=row)

        await service.generate_angle_image(avatar_id, slot=1)

        call_args = mock_gemini.generate_image.call_args
        temperature = call_args.kwargs.get("temperature") or call_args[1].get("temperature")
        assert temperature == 0.3


# ============================================================================
# create_kling_element Tests
# ============================================================================

class TestCreateKlingElement:
    """Test Kling element creation from avatar references."""

    @pytest.mark.asyncio
    async def test_missing_frontal_returns_none(self, service, mock_supabase):
        """Returns None when slot 1 (frontal) is empty."""
        avatar_id = uuid4()
        row = _make_avatar_row(avatar_id=avatar_id, ref1=None)

        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(data=row)

        result = await service.create_kling_element(avatar_id, "org-123", "brand-123")
        assert result is None

    @pytest.mark.asyncio
    async def test_avatar_not_found_returns_none(self, service, mock_supabase):
        """Returns None if avatar doesn't exist."""
        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(data=None)

        result = await service.create_kling_element(uuid4(), "org-123", "brand-123")
        assert result is None

    @pytest.mark.asyncio
    async def test_happy_path_saves_element_id(self, service, mock_supabase):
        """Successful element creation saves element_id to DB."""
        avatar_id = uuid4()
        row = _make_avatar_row(
            avatar_id=avatar_id,
            ref1="avatars/b/a/ref1.png",
            ref2="avatars/b/a/ref2.png",
        )

        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(data=row)

        mock_kling = MagicMock()
        mock_kling.create_element = AsyncMock(return_value={"kling_task_id": "task-123"})
        mock_kling.poll_task = AsyncMock(return_value={
            "data": {
                "task_status": "succeed",
                "task_result": {
                    "elements": [{"element_id": "elem-abc-123"}]
                }
            }
        })
        mock_kling.close = AsyncMock()

        with patch(
            "viraltracker.services.kling_video_service.KlingVideoService",
            return_value=mock_kling,
        ):
            # Need to import after patching
            result = await service.create_kling_element(avatar_id, "org-123", "brand-123")

        assert result == "elem-abc-123"
        mock_kling.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_failed_task_returns_none(self, service, mock_supabase):
        """Returns None when Kling task fails."""
        avatar_id = uuid4()
        row = _make_avatar_row(avatar_id=avatar_id, ref1="avatars/b/a/ref1.png")

        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(data=row)

        mock_kling = MagicMock()
        mock_kling.create_element = AsyncMock(return_value={"kling_task_id": "task-123"})
        mock_kling.poll_task = AsyncMock(return_value={
            "data": {
                "task_status": "failed",
                "task_status_msg": "Content policy violation",
            }
        })
        mock_kling.close = AsyncMock()

        with patch(
            "viraltracker.services.kling_video_service.KlingVideoService",
            return_value=mock_kling,
        ):
            result = await service.create_kling_element(avatar_id, "org-123", "brand-123")

        assert result is None
        mock_kling.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_exception_returns_none_and_closes(self, service, mock_supabase):
        """Returns None on exception and still closes Kling client."""
        avatar_id = uuid4()
        row = _make_avatar_row(avatar_id=avatar_id, ref1="avatars/b/a/ref1.png")

        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(data=row)

        mock_kling = MagicMock()
        mock_kling.create_element = AsyncMock(side_effect=Exception("API timeout"))
        mock_kling.close = AsyncMock()

        with patch(
            "viraltracker.services.kling_video_service.KlingVideoService",
            return_value=mock_kling,
        ):
            result = await service.create_kling_element(avatar_id, "org-123", "brand-123")

        assert result is None
        mock_kling.close.assert_awaited_once()


# ============================================================================
# add_reference_image Invalidation Tests
# ============================================================================

class TestAddReferenceImageInvalidation:
    """Test stale Kling element auto-invalidation on ref image changes."""

    @pytest.mark.asyncio
    async def test_add_ref_clears_kling_element(self, service, mock_supabase):
        """Adding a reference image clears kling_element_id."""
        avatar_id = uuid4()
        row = _make_avatar_row(
            avatar_id=avatar_id,
            kling_element_id="elem-old",
        )

        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(data=row)

        await service.add_reference_image(avatar_id, b"new-image-bytes", slot=2)

        # Verify update was called to clear kling_element_id
        # The chain: .update({"kling_element_id": None}).eq(...).not_.is_(...).execute()
        update_calls = mock_supabase.table.return_value.update.call_args_list
        # Should have at least 2 update calls: one for ref image, one for clearing element
        assert len(update_calls) >= 2
        # The second update should clear kling_element_id
        second_update_arg = update_calls[1][0][0]
        assert second_update_arg == {"kling_element_id": None}

    @pytest.mark.asyncio
    async def test_remove_ref_clears_kling_element(self, service, mock_supabase):
        """Removing a reference image clears kling_element_id."""
        avatar_id = uuid4()
        row = _make_avatar_row(
            avatar_id=avatar_id,
            ref2="avatars/b/a/ref2.png",
            kling_element_id="elem-old",
        )

        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(data=row)

        await service.remove_reference_image(avatar_id, slot=2)

        update_calls = mock_supabase.table.return_value.update.call_args_list
        assert len(update_calls) >= 2
        second_update_arg = update_calls[1][0][0]
        assert second_update_arg == {"kling_element_id": None}

    @pytest.mark.asyncio
    async def test_slot_validation_rejects_invalid(self, service):
        """Slots outside 1-4 raise ValueError for add and remove."""
        with pytest.raises(ValueError, match="Slot must be 1, 2, 3, or 4"):
            await service.add_reference_image(uuid4(), b"bytes", slot=5)

        with pytest.raises(ValueError, match="Slot must be 1, 2, 3, or 4"):
            await service.remove_reference_image(uuid4(), slot=0)
