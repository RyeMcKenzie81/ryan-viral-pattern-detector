"""Unit tests for VideoGenerationProtocol and related models.

Tests VideoGenStatus enum values and VideoGenerationResult computed properties.
"""

from viraltracker.services.video_generation_protocol import (
    VideoGenStatus,
    VideoGenerationResult,
    VideoGenerationProtocol,
)


class TestVideoGenStatus:
    def test_all_status_values(self):
        assert VideoGenStatus.PENDING == "pending"
        assert VideoGenStatus.GENERATING == "generating"
        assert VideoGenStatus.COMPLETED == "completed"
        assert VideoGenStatus.FAILED == "failed"

    def test_status_count(self):
        assert len(VideoGenStatus) == 4


class TestVideoGenerationResult:
    def test_is_complete_for_completed(self):
        result = VideoGenerationResult(
            generation_id="gen1",
            status=VideoGenStatus.COMPLETED,
        )
        assert result.is_complete is True

    def test_is_complete_for_failed(self):
        result = VideoGenerationResult(
            generation_id="gen1",
            status=VideoGenStatus.FAILED,
        )
        assert result.is_complete is True

    def test_is_complete_for_pending(self):
        result = VideoGenerationResult(
            generation_id="gen1",
            status=VideoGenStatus.PENDING,
        )
        assert result.is_complete is False

    def test_is_complete_for_generating(self):
        result = VideoGenerationResult(
            generation_id="gen1",
            status=VideoGenStatus.GENERATING,
        )
        assert result.is_complete is False

    def test_is_success_for_completed(self):
        result = VideoGenerationResult(
            generation_id="gen1",
            status=VideoGenStatus.COMPLETED,
        )
        assert result.is_success is True

    def test_is_success_for_failed(self):
        result = VideoGenerationResult(
            generation_id="gen1",
            status=VideoGenStatus.FAILED,
        )
        assert result.is_success is False

    def test_is_success_for_pending(self):
        result = VideoGenerationResult(
            generation_id="gen1",
            status=VideoGenStatus.PENDING,
        )
        assert result.is_success is False

    def test_optional_fields_default_none(self):
        result = VideoGenerationResult(
            generation_id="gen1",
            status=VideoGenStatus.PENDING,
        )
        assert result.video_storage_path is None
        assert result.video_url is None
        assert result.duration_seconds is None
        assert result.generation_time_seconds is None
        assert result.estimated_cost_usd is None
        assert result.error_message is None

    def test_full_construction(self):
        result = VideoGenerationResult(
            generation_id="gen1",
            status=VideoGenStatus.COMPLETED,
            video_storage_path="kling-videos/gen1/video.mp4",
            video_url="http://cdn.kling.com/v.mp4",
            duration_seconds=5.0,
            generation_time_seconds=45.2,
            estimated_cost_usd=0.33,
        )
        assert result.video_storage_path == "kling-videos/gen1/video.mp4"
        assert result.estimated_cost_usd == 0.33


class TestVideoGenerationProtocolRuntimeCheckable:
    def test_protocol_is_runtime_checkable(self):
        """Verify @runtime_checkable decorator works."""
        # A class that implements all protocol methods should pass isinstance
        class FakeEngine:
            async def generate_from_prompt(self, prompt, duration_sec, aspect_ratio,
                                           reference_images=None, negative_prompt=None):
                pass

            async def generate_talking_head(self, avatar_image_url, audio_url, prompt=None):
                pass

            async def get_status(self, generation_id):
                pass

            async def download_and_store(self, generation_id):
                pass

        assert isinstance(FakeEngine(), VideoGenerationProtocol)

    def test_non_conforming_class_fails(self):
        """A class missing methods should not match the protocol."""
        class Incomplete:
            async def generate_from_prompt(self, prompt, duration_sec, aspect_ratio):
                pass

        assert not isinstance(Incomplete(), VideoGenerationProtocol)
