"""Unit tests for KlingVideoService.

Tests validation helpers, JWT caching, retry logic, generation methods,
polling, cost estimation, and error handling.

All external dependencies (httpx, Supabase, jwt) are mocked.
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import httpx
import pytest

from viraltracker.services.kling_video_service import (
    KlingAPIError,
    KlingVideoService,
)
from viraltracker.services.kling_models import (
    KlingEndpoint,
    KlingTaskStatus,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_supabase():
    """Mock Supabase client."""
    mock = MagicMock()
    # Table operations
    table = MagicMock()
    table.insert.return_value.execute.return_value = MagicMock(data=[{"id": "gen-123"}])
    table.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
    table.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(data=None)
    table.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
    mock.table.return_value = table
    # Storage operations
    storage_bucket = MagicMock()
    storage_bucket.upload.return_value = None
    storage_bucket.create_signed_url.return_value = {"signedURL": "https://signed-url"}
    mock.storage.from_.return_value = storage_bucket
    return mock


@pytest.fixture
def service(mock_supabase):
    """Create KlingVideoService with mocked dependencies."""
    with patch("viraltracker.services.kling_video_service.get_supabase_client", return_value=mock_supabase):
        svc = KlingVideoService(
            access_key="test-access-key",
            secret_key="test-secret-key",
            max_concurrent=3,
        )
    return svc


def _make_success_response(task_id="task-abc", task_status="submitted"):
    """Build a standard Kling API success response."""
    return {
        "code": 0,
        "message": "OK",
        "request_id": "req-xyz",
        "data": {
            "task_id": task_id,
            "task_status": task_status,
            "task_info": {"external_task_id": "ext-123"},
            "created_at": 1722769557708,
            "updated_at": 1722769557708,
        },
    }


def _make_error_response(code, message="Error"):
    """Build a Kling API error response."""
    return {
        "code": code,
        "message": message,
        "request_id": "req-err",
    }


# ---------------------------------------------------------------------------
# Validation Helpers (no mocks needed)
# ---------------------------------------------------------------------------

class TestStripBase64Prefix:
    def test_strips_png_prefix(self):
        data = "data:image/png;base64,iVBORw0KGgo="
        assert KlingVideoService._strip_base64_prefix(data) == "iVBORw0KGgo="

    def test_strips_jpeg_prefix(self):
        data = "data:image/jpeg;base64,/9j/4AAQ"
        assert KlingVideoService._strip_base64_prefix(data) == "/9j/4AAQ"

    def test_strips_audio_prefix(self):
        data = "data:audio/mp3;base64,SUQzBAA="
        assert KlingVideoService._strip_base64_prefix(data) == "SUQzBAA="

    def test_preserves_raw_base64(self):
        data = "iVBORw0KGgo="
        assert KlingVideoService._strip_base64_prefix(data) == "iVBORw0KGgo="

    def test_preserves_url(self):
        url = "https://example.com/image.png"
        assert KlingVideoService._strip_base64_prefix(url) == url

    def test_handles_data_prefix_no_comma(self):
        # Edge case: starts with "data:" but no comma
        data = "data:something"
        result = KlingVideoService._strip_base64_prefix(data)
        # partition on "," returns ("data:something", "", "")
        assert result == ""


class TestValidateMutualExclusion:
    def test_exactly_one_a(self):
        # Should not raise
        KlingVideoService._validate_mutual_exclusion("a", None, "param_a", "param_b")

    def test_exactly_one_b(self):
        KlingVideoService._validate_mutual_exclusion(None, "b", "param_a", "param_b")

    def test_both_provided_raises(self):
        with pytest.raises(ValueError, match="not both"):
            KlingVideoService._validate_mutual_exclusion("a", "b", "param_a", "param_b")

    def test_neither_provided_raises(self):
        with pytest.raises(ValueError, match="Must provide one"):
            KlingVideoService._validate_mutual_exclusion(None, None, "param_a", "param_b")

    def test_empty_strings_treated_as_none(self):
        # Empty string is falsy
        with pytest.raises(ValueError, match="Must provide one"):
            KlingVideoService._validate_mutual_exclusion("", "", "param_a", "param_b")


class TestValidateImage:
    def test_valid_url(self, service):
        result = service._validate_image("https://example.com/img.png")
        assert result == "https://example.com/img.png"

    def test_valid_base64(self, service):
        result = service._validate_image("iVBORw0KGgo=")
        assert result == "iVBORw0KGgo="

    def test_strips_prefix(self, service):
        result = service._validate_image("data:image/png;base64,iVBORw0KGgo=")
        assert result == "iVBORw0KGgo="

    def test_empty_string_raises(self, service):
        with pytest.raises(ValueError, match="Image is required"):
            service._validate_image("")

    def test_none_like_empty_raises(self, service):
        # Passing empty string explicitly
        with pytest.raises(ValueError, match="Image is required"):
            service._validate_image("")


# ---------------------------------------------------------------------------
# JWT Caching
# ---------------------------------------------------------------------------

class TestJWTCaching:
    def test_generates_jwt(self, service):
        token = service._get_jwt()
        assert isinstance(token, str)
        assert len(token) > 0

    def test_caches_jwt(self, service):
        token1 = service._get_jwt()
        token2 = service._get_jwt()
        assert token1 == token2

    def test_invalidate_forces_regeneration(self, service):
        token1 = service._get_jwt()
        service._invalidate_jwt()
        # After invalidation, cache is cleared
        assert service._cached_jwt is None
        assert service._jwt_expires_at == 0
        token2 = service._get_jwt()
        # New token generated (may differ due to timestamp in payload)
        assert isinstance(token2, str)

    def test_jwt_contains_expected_fields(self, service):
        import jwt as pyjwt
        token = service._get_jwt()
        decoded = pyjwt.decode(token, "test-secret-key", algorithms=["HS256"],
                               options={"verify_exp": False, "verify_nbf": False})
        assert decoded["iss"] == "test-access-key"
        assert "exp" in decoded
        assert "nbf" in decoded

    def test_jwt_expiry_30_min(self, service):
        import jwt as pyjwt
        now = time.time()
        token = service._get_jwt()
        decoded = pyjwt.decode(token, "test-secret-key", algorithms=["HS256"],
                               options={"verify_exp": False, "verify_nbf": False})
        # exp should be ~30 min from now
        assert abs(decoded["exp"] - (int(now) + 1800)) < 5

    def test_nbf_has_30s_buffer(self, service):
        import jwt as pyjwt
        now = time.time()
        token = service._get_jwt()
        decoded = pyjwt.decode(token, "test-secret-key", algorithms=["HS256"],
                               options={"verify_exp": False, "verify_nbf": False})
        # nbf should be ~30s before now
        assert abs(decoded["nbf"] - (int(now) - 30)) < 5

    def test_headers_include_bearer_token(self, service):
        headers = service._headers()
        assert headers["Authorization"].startswith("Bearer ")
        assert headers["Content-Type"] == "application/json"


# ---------------------------------------------------------------------------
# Retry Logic in _post()
# ---------------------------------------------------------------------------

class TestPostRetryLogic:
    @pytest.mark.asyncio
    async def test_success_returns_data(self, service):
        mock_response = MagicMock()
        mock_response.json.return_value = _make_success_response()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.is_closed = False
        service._client = mock_client

        result = await service._post(KlingEndpoint.TEXT2VIDEO, {"prompt": "test"})
        assert result["code"] == 0
        assert result["data"]["task_id"] == "task-abc"

    @pytest.mark.asyncio
    async def test_content_safety_1301_no_retry(self, service):
        mock_response = MagicMock()
        mock_response.json.return_value = _make_error_response(1301, "Safety")

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.is_closed = False
        service._client = mock_client

        with pytest.raises(KlingAPIError) as exc_info:
            await service._post(KlingEndpoint.TEXT2VIDEO, {"prompt": "bad"})
        assert exc_info.value.code == 1301
        assert "safety" in str(exc_info.value).lower()
        # Only called once (no retry)
        assert mock_client.post.call_count == 1

    @pytest.mark.asyncio
    async def test_jwt_expired_1004_retry_once(self, service):
        error_resp = MagicMock()
        error_resp.json.return_value = _make_error_response(1004, "JWT expired")
        success_resp = MagicMock()
        success_resp.json.return_value = _make_success_response()

        mock_client = AsyncMock()
        mock_client.post.side_effect = [error_resp, success_resp]
        mock_client.is_closed = False
        service._client = mock_client

        result = await service._post(KlingEndpoint.AVATAR, {"image": "test"})
        assert result["code"] == 0
        assert mock_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_concurrent_limit_1303_retries_with_backoff(self, service):
        error_resp = MagicMock()
        error_resp.json.return_value = _make_error_response(1303, "Concurrent limit")
        success_resp = MagicMock()
        success_resp.json.return_value = _make_success_response()

        mock_client = AsyncMock()
        # Fail twice, then succeed
        mock_client.post.side_effect = [error_resp, error_resp, success_resp]
        mock_client.is_closed = False
        service._client = mock_client

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await service._post(KlingEndpoint.TEXT2VIDEO, {"prompt": "test"})
        assert result["code"] == 0
        assert mock_client.post.call_count == 3

    @pytest.mark.asyncio
    async def test_1303_exhausted_raises(self, service):
        error_resp = MagicMock()
        error_resp.json.return_value = _make_error_response(1303, "Concurrent limit")

        mock_client = AsyncMock()
        mock_client.post.return_value = error_resp
        mock_client.is_closed = False
        service._client = mock_client

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(KlingAPIError) as exc_info:
                await service._post(KlingEndpoint.TEXT2VIDEO, {"prompt": "test"})
        assert exc_info.value.code == 1303

    @pytest.mark.asyncio
    async def test_rate_limit_1302_retries(self, service):
        error_resp = MagicMock()
        error_resp.json.return_value = _make_error_response(1302, "Rate limit")
        success_resp = MagicMock()
        success_resp.json.return_value = _make_success_response()

        mock_client = AsyncMock()
        mock_client.post.side_effect = [error_resp, success_resp]
        mock_client.is_closed = False
        service._client = mock_client

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await service._post(KlingEndpoint.TEXT2VIDEO, {"prompt": "test"})
        assert result["code"] == 0

    @pytest.mark.asyncio
    async def test_connection_error_retries(self, service):
        mock_client = AsyncMock()
        mock_client.post.side_effect = [
            httpx.ConnectError("Connection refused"),
            MagicMock(json=MagicMock(return_value=_make_success_response())),
        ]
        mock_client.is_closed = False
        service._client = mock_client

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await service._post(KlingEndpoint.TEXT2VIDEO, {"prompt": "test"})
        assert result["code"] == 0

    @pytest.mark.asyncio
    async def test_unknown_error_code_raises_immediately(self, service):
        mock_response = MagicMock()
        mock_response.json.return_value = _make_error_response(9999, "Unknown")

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.is_closed = False
        service._client = mock_client

        with pytest.raises(KlingAPIError) as exc_info:
            await service._post(KlingEndpoint.TEXT2VIDEO, {"prompt": "test"})
        assert exc_info.value.code == 9999
        assert mock_client.post.call_count == 1


# ---------------------------------------------------------------------------
# KlingAPIError
# ---------------------------------------------------------------------------

class TestKlingAPIError:
    def test_basic_construction(self):
        err = KlingAPIError("fail", code=1301, request_id="req-123")
        assert str(err) == "fail"
        assert err.code == 1301
        assert err.request_id == "req-123"

    def test_default_values(self):
        err = KlingAPIError("generic error")
        assert err.code == 0
        assert err.request_id == ""


# ---------------------------------------------------------------------------
# Generation Methods (mock _post, _create_db_record, _update_db_record)
# ---------------------------------------------------------------------------

class TestGenerateTextToVideo:
    @pytest.mark.asyncio
    async def test_happy_path(self, service):
        service._post = AsyncMock(return_value=_make_success_response("task-t2v"))
        service._create_db_record = AsyncMock(return_value="gen-t2v")
        service._update_db_record = AsyncMock()
        service._enforce_limit = MagicMock()
        service._track_usage = MagicMock()

        result = await service.generate_text_to_video(
            organization_id="org-1",
            brand_id="brand-1",
            prompt="A cat running in a field",
        )

        assert result["kling_task_id"] == "task-t2v"
        assert result["status"] == "submitted"
        assert "generation_id" in result
        assert "estimated_cost_usd" in result
        service._create_db_record.assert_called_once()
        service._update_db_record.assert_called_once()
        service._track_usage.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_prompt_raises(self, service):
        service._enforce_limit = MagicMock()
        with pytest.raises(ValueError, match="Prompt is required"):
            await service.generate_text_to_video(
                organization_id="org-1",
                brand_id="brand-1",
                prompt="",
            )

    @pytest.mark.asyncio
    async def test_invalid_duration_raises(self, service):
        service._enforce_limit = MagicMock()
        with pytest.raises(ValueError, match="Duration must be"):
            await service.generate_text_to_video(
                organization_id="org-1",
                brand_id="brand-1",
                prompt="A cat",
                duration="15",
            )

    @pytest.mark.asyncio
    async def test_cfg_scale_omitted_for_v2(self, service):
        service._post = AsyncMock(return_value=_make_success_response())
        service._create_db_record = AsyncMock(return_value="gen-123")
        service._update_db_record = AsyncMock()
        service._enforce_limit = MagicMock()
        service._track_usage = MagicMock()

        await service.generate_text_to_video(
            organization_id="org-1",
            brand_id="brand-1",
            prompt="Test",
            model_name="kling-v2-6",
            cfg_scale=0.5,
        )

        # Verify payload doesn't include cfg_scale for v2.x
        call_args = service._post.call_args
        payload = call_args[0][1]  # second positional arg is payload
        assert "cfg_scale" not in payload

    @pytest.mark.asyncio
    async def test_cost_estimation_pro_10s(self, service):
        service._post = AsyncMock(return_value=_make_success_response())
        service._create_db_record = AsyncMock(return_value="gen-123")
        service._update_db_record = AsyncMock()
        service._enforce_limit = MagicMock()
        service._track_usage = MagicMock()

        result = await service.generate_text_to_video(
            organization_id="org-1",
            brand_id="brand-1",
            prompt="Test",
            mode="pro",
            duration="10",
        )

        # Pro 10s = kling_video_pro_5s * 2
        expected = 0.33 * 2  # Config.get_unit_cost returns 0.33
        assert result["estimated_cost_usd"] == pytest.approx(expected, abs=0.01)

    @pytest.mark.asyncio
    async def test_api_error_updates_db_record(self, service):
        service._post = AsyncMock(side_effect=KlingAPIError("fail", code=1301))
        service._create_db_record = AsyncMock(return_value="gen-err")
        service._update_db_record = AsyncMock()
        service._enforce_limit = MagicMock()

        with pytest.raises(KlingAPIError):
            await service.generate_text_to_video(
                organization_id="org-1",
                brand_id="brand-1",
                prompt="Bad content",
            )

        # DB should be updated with failure
        update_call = service._update_db_record.call_args
        assert update_call[0][1]["status"] == "failed"
        assert "fail" in update_call[0][1]["error_message"]


class TestGenerateAvatarVideo:
    @pytest.mark.asyncio
    async def test_happy_path(self, service):
        service._post = AsyncMock(return_value=_make_success_response("task-avatar"))
        service._create_db_record = AsyncMock(return_value="gen-avatar")
        service._update_db_record = AsyncMock()
        service._enforce_limit = MagicMock()
        service._track_usage = MagicMock()

        result = await service.generate_avatar_video(
            organization_id="org-1",
            brand_id="brand-1",
            image="https://example.com/face.jpg",
            sound_file="https://example.com/audio.mp3",
        )

        assert result["kling_task_id"] == "task-avatar"
        assert result["status"] == "submitted"
        service._track_usage.assert_called_once()

    @pytest.mark.asyncio
    async def test_mutual_exclusion_both_audio(self, service):
        service._enforce_limit = MagicMock()
        with pytest.raises(ValueError, match="not both"):
            await service.generate_avatar_video(
                organization_id="org-1",
                brand_id="brand-1",
                image="https://example.com/face.jpg",
                sound_file="audio.mp3",
                audio_id="aud-123",
            )

    @pytest.mark.asyncio
    async def test_mutual_exclusion_neither_audio(self, service):
        service._enforce_limit = MagicMock()
        with pytest.raises(ValueError, match="Must provide one"):
            await service.generate_avatar_video(
                organization_id="org-1",
                brand_id="brand-1",
                image="https://example.com/face.jpg",
            )

    @pytest.mark.asyncio
    async def test_image_validation(self, service):
        service._enforce_limit = MagicMock()
        with pytest.raises(ValueError, match="Image is required"):
            await service.generate_avatar_video(
                organization_id="org-1",
                brand_id="brand-1",
                image="",
                sound_file="https://audio.mp3",
            )

    @pytest.mark.asyncio
    async def test_base64_image_stripped(self, service):
        service._post = AsyncMock(return_value=_make_success_response())
        service._create_db_record = AsyncMock(return_value="gen-123")
        service._update_db_record = AsyncMock()
        service._enforce_limit = MagicMock()
        service._track_usage = MagicMock()

        await service.generate_avatar_video(
            organization_id="org-1",
            brand_id="brand-1",
            image="data:image/png;base64,iVBORw0=",
            sound_file="https://audio.mp3",
        )

        # The payload image should be stripped
        call_args = service._post.call_args
        payload = call_args[0][1]
        assert payload["image"] == "iVBORw0="


class TestGenerateImageToVideo:
    @pytest.mark.asyncio
    async def test_happy_path(self, service):
        service._post = AsyncMock(return_value=_make_success_response("task-i2v"))
        service._create_db_record = AsyncMock(return_value="gen-i2v")
        service._update_db_record = AsyncMock()
        service._enforce_limit = MagicMock()
        service._track_usage = MagicMock()

        result = await service.generate_image_to_video(
            organization_id="org-1",
            brand_id="brand-1",
            image="https://example.com/img.png",
        )

        assert result["kling_task_id"] == "task-i2v"
        assert result["status"] == "submitted"

    @pytest.mark.asyncio
    async def test_image_tail_and_camera_control_exclusive(self, service):
        service._enforce_limit = MagicMock()
        with pytest.raises(ValueError, match="mutually exclusive"):
            await service.generate_image_to_video(
                organization_id="org-1",
                brand_id="brand-1",
                image="https://example.com/img.png",
                image_tail="https://example.com/tail.png",
                camera_control={"zoom": "in"},
            )

    @pytest.mark.asyncio
    async def test_invalid_duration(self, service):
        service._enforce_limit = MagicMock()
        with pytest.raises(ValueError, match="Duration must be"):
            await service.generate_image_to_video(
                organization_id="org-1",
                brand_id="brand-1",
                image="https://example.com/img.png",
                duration="7",
            )


class TestIdentifyFaces:
    @pytest.mark.asyncio
    async def test_happy_path(self, service):
        face_response = {
            "code": 0,
            "request_id": "req-face",
            "data": {
                "session_id": "sess-123",
                "face_data": [
                    {"face_id": "f1", "face_image": "url1", "start_time": 0, "end_time": 5200},
                ],
            },
        }
        service._post = AsyncMock(return_value=face_response)
        service._create_db_record = AsyncMock(return_value="gen-face")
        service._update_db_record = AsyncMock()

        result = await service.identify_faces(
            organization_id="org-1",
            brand_id="brand-1",
            video_id="vid-123",
        )

        assert result["session_id"] == "sess-123"
        assert len(result["face_data"]) == 1
        assert "session_expires_at" in result

    @pytest.mark.asyncio
    async def test_mutual_exclusion_both(self, service):
        with pytest.raises(ValueError, match="not both"):
            await service.identify_faces(
                organization_id="org-1",
                brand_id="brand-1",
                video_id="vid-123",
                video_url="https://example.com/video.mp4",
            )

    @pytest.mark.asyncio
    async def test_mutual_exclusion_neither(self, service):
        with pytest.raises(ValueError, match="Must provide one"):
            await service.identify_faces(
                organization_id="org-1",
                brand_id="brand-1",
            )


class TestApplyLipSync:
    @pytest.mark.asyncio
    async def test_happy_path(self, service):
        service._post = AsyncMock(return_value=_make_success_response("task-lip"))
        service._create_db_record = AsyncMock(return_value="gen-lip")
        service._update_db_record = AsyncMock()
        service._enforce_limit = MagicMock()
        service._track_usage = MagicMock()

        result = await service.apply_lip_sync(
            organization_id="org-1",
            brand_id="brand-1",
            session_id="sess-123",
            face_id="f1",
            sound_file="https://example.com/audio.mp3",
        )

        assert result["kling_task_id"] == "task-lip"

        # Verify face_choose array in payload
        call_args = service._post.call_args
        payload = call_args[0][1]
        assert "face_choose" in payload
        assert len(payload["face_choose"]) == 1
        assert payload["face_choose"][0]["face_id"] == "f1"
        assert payload["face_choose"][0]["sound_file"] == "https://example.com/audio.mp3"

    @pytest.mark.asyncio
    async def test_audio_mutual_exclusion(self, service):
        service._enforce_limit = MagicMock()
        with pytest.raises(ValueError, match="not both"):
            await service.apply_lip_sync(
                organization_id="org-1",
                brand_id="brand-1",
                session_id="sess-123",
                face_id="f1",
                sound_file="audio.mp3",
                audio_id="aud-123",
            )


class TestCreateMultiShot:
    @pytest.mark.asyncio
    async def test_happy_path(self, service):
        service._post = AsyncMock(return_value=_make_success_response("task-ms"))
        service._create_db_record = AsyncMock(return_value="gen-ms")
        service._update_db_record = AsyncMock()
        service._track_usage = MagicMock()

        result = await service.create_multi_shot(
            organization_id="org-1",
            brand_id="brand-1",
            element_frontal_image="https://example.com/frontal.png",
        )

        assert result["kling_task_id"] == "task-ms"

    @pytest.mark.asyncio
    async def test_empty_image_raises(self, service):
        with pytest.raises(ValueError, match="Image is required"):
            await service.create_multi_shot(
                organization_id="org-1",
                brand_id="brand-1",
                element_frontal_image="",
            )


# ---------------------------------------------------------------------------
# Polling
# ---------------------------------------------------------------------------

class TestPollTask:
    @pytest.mark.asyncio
    async def test_returns_on_succeed(self, service):
        succeed_response = {
            "code": 0,
            "data": {
                "task_id": "t1",
                "task_status": "succeed",
                "task_result": {"videos": [{"id": "v1", "url": "http://cdn/v.mp4", "duration": "5.0"}]},
            },
        }
        service._get = AsyncMock(return_value=succeed_response)

        result = await service.poll_task("t1", KlingEndpoint.TEXT2VIDEO, timeout_seconds=30)
        assert result["data"]["task_status"] == "succeed"

    @pytest.mark.asyncio
    async def test_returns_on_failed(self, service):
        failed_response = {
            "code": 0,
            "data": {
                "task_id": "t1",
                "task_status": "failed",
                "task_status_msg": "Content safety",
            },
        }
        service._get = AsyncMock(return_value=failed_response)

        result = await service.poll_task("t1", KlingEndpoint.TEXT2VIDEO, timeout_seconds=30)
        assert result["data"]["task_status"] == "failed"

    @pytest.mark.asyncio
    async def test_polls_until_terminal(self, service):
        processing_resp = {
            "code": 0,
            "data": {"task_id": "t1", "task_status": "processing"},
        }
        succeed_resp = {
            "code": 0,
            "data": {"task_id": "t1", "task_status": "succeed", "task_result": {"videos": []}},
        }
        service._get = AsyncMock(side_effect=[processing_resp, processing_resp, succeed_resp])

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await service.poll_task("t1", KlingEndpoint.TEXT2VIDEO, timeout_seconds=300)
        assert result["data"]["task_status"] == "succeed"
        assert service._get.call_count == 3

    @pytest.mark.asyncio
    async def test_timeout_raises(self, service):
        processing_resp = {
            "code": 0,
            "data": {"task_id": "t1", "task_status": "processing"},
        }
        service._get = AsyncMock(return_value=processing_resp)

        # Simulate time advancing past the timeout
        call_count = 0
        def fake_time():
            nonlocal call_count
            call_count += 1
            # First call (start_time capture) returns 0, then advance past timeout
            if call_count <= 1:
                return 0
            return 700  # Past the 600s timeout

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with patch("viraltracker.services.kling_video_service.time") as mock_time:
                mock_time.time = fake_time
                with pytest.raises(TimeoutError, match="timed out"):
                    await service.poll_task("t1", KlingEndpoint.TEXT2VIDEO, timeout_seconds=600)

    @pytest.mark.asyncio
    async def test_jwt_retry_during_polling(self, service):
        jwt_error_resp = {"code": 1004, "data": {}}
        succeed_resp = {
            "code": 0,
            "data": {"task_id": "t1", "task_status": "succeed", "task_result": {"videos": []}},
        }
        service._get = AsyncMock(side_effect=[jwt_error_resp, succeed_resp])

        result = await service.poll_task("t1", KlingEndpoint.TEXT2VIDEO, timeout_seconds=300)
        assert result["data"]["task_status"] == "succeed"


# ---------------------------------------------------------------------------
# Usage Tracking
# ---------------------------------------------------------------------------

class TestUsageTracking:
    def test_track_usage_without_tracker_is_noop(self, service):
        # No tracker set, should not raise
        service._track_usage("op", "unit", 1, 0.10)

    def test_track_usage_with_tracker(self, service):
        mock_tracker = MagicMock()
        service.set_tracking_context(mock_tracker, user_id="user-1", organization_id="org-1")
        service._track_usage("op", "unit", 1, 0.10, {"key": "val"})
        mock_tracker.track.assert_called_once()

    def test_track_usage_swallows_exceptions(self, service):
        mock_tracker = MagicMock()
        mock_tracker.track.side_effect = RuntimeError("DB error")
        service.set_tracking_context(mock_tracker, user_id="user-1", organization_id="org-1")
        # Should not raise
        service._track_usage("op", "unit", 1, 0.10)


# ---------------------------------------------------------------------------
# Config unit cost presence
# ---------------------------------------------------------------------------

class TestConfigUnitCosts:
    def test_kling_costs_in_config(self):
        from viraltracker.core.config import Config
        expected_keys = [
            "kling_avatar_std_seconds",
            "kling_avatar_pro_seconds",
            "kling_video_std_5s",
            "kling_video_pro_5s",
            "kling_lip_sync",
            "kling_multi_shot",
        ]
        for key in expected_keys:
            cost = Config.get_unit_cost(key)
            assert cost > 0, f"Expected positive cost for {key}, got {cost}"


# ---------------------------------------------------------------------------
# Service Constants
# ---------------------------------------------------------------------------

class TestServiceConstants:
    def test_base_url(self):
        assert KlingVideoService.BASE_URL == "https://api-singapore.klingai.com"

    def test_all_endpoints_mapped(self):
        for ep in KlingEndpoint:
            assert ep in KlingVideoService.ENDPOINTS, f"Missing endpoint mapping for {ep}"

    def test_terminal_statuses(self):
        assert "succeed" in KlingVideoService.TERMINAL_STATUSES
        assert "failed" in KlingVideoService.TERMINAL_STATUSES
        assert len(KlingVideoService.TERMINAL_STATUSES) == 2

    def test_default_models(self):
        assert KlingVideoService.DEFAULT_MODELS[KlingEndpoint.TEXT2VIDEO] == "kling-v2-6"
        assert KlingVideoService.DEFAULT_MODELS[KlingEndpoint.IMAGE2VIDEO] == "kling-v2-6"

    def test_storage_bucket(self):
        assert KlingVideoService.STORAGE_BUCKET == "kling-videos"


# ---------------------------------------------------------------------------
# poll_and_complete (HIGH priority - ~120 lines of branching logic)
# ---------------------------------------------------------------------------

class TestPollAndComplete:
    @pytest.mark.asyncio
    async def test_succeed_with_video_download(self, service):
        poll_result = {
            "code": 0,
            "data": {
                "task_id": "t1",
                "task_status": "succeed",
                "task_status_msg": "",
                "final_unit_deduction": "10",
                "task_result": {
                    "videos": [{"id": "v1", "url": "http://cdn/v.mp4", "duration": "5.0"}],
                },
            },
        }
        service.poll_task = AsyncMock(return_value=poll_result)
        service.download_and_store = AsyncMock(return_value="kling-videos/gen-1/video.mp4")
        service._update_db_record = AsyncMock()

        result = await service.poll_and_complete(
            generation_id="gen-1",
            kling_task_id="t1",
            endpoint_type=KlingEndpoint.TEXT2VIDEO,
        )

        assert result["status"] == "succeed"
        assert result["video_url"] == "http://cdn/v.mp4"
        assert result["video_storage_path"] == "kling-videos/gen-1/video.mp4"
        assert result["generation_time_seconds"] is not None
        service.download_and_store.assert_called_once_with("http://cdn/v.mp4", "gen-1")

    @pytest.mark.asyncio
    async def test_succeed_with_multi_shot_images(self, service):
        poll_result = {
            "code": 0,
            "data": {
                "task_id": "t1",
                "task_status": "succeed",
                "task_status_msg": "",
                "final_unit_deduction": "5",
                "task_result": {
                    "images": [
                        {"index": 0, "url": "http://cdn/img0.png"},
                        {"index": 1, "url": "http://cdn/img1.png"},
                        {"index": 2, "url": "http://cdn/img2.png"},
                    ],
                },
            },
        }
        service.poll_task = AsyncMock(return_value=poll_result)
        service._download_image_to_storage = AsyncMock(
            side_effect=["kling-videos/gen-ms/multi_shot_0.png",
                         "kling-videos/gen-ms/multi_shot_1.png",
                         "kling-videos/gen-ms/multi_shot_2.png"]
        )
        service._update_db_record = AsyncMock()

        result = await service.poll_and_complete(
            generation_id="gen-ms",
            kling_task_id="t1",
            endpoint_type=KlingEndpoint.MULTI_SHOT,
        )

        assert result["status"] == "succeed"
        assert len(result["multi_shot_images"]) == 3
        assert result["multi_shot_images"][0]["index"] == 0
        assert result["multi_shot_images"][0]["storage_path"] == "kling-videos/gen-ms/multi_shot_0.png"

    @pytest.mark.asyncio
    async def test_failed_task_updates_db(self, service):
        poll_result = {
            "code": 0,
            "data": {
                "task_id": "t1",
                "task_status": "failed",
                "task_status_msg": "Content safety violation",
                "final_unit_deduction": "0",
            },
        }
        service.poll_task = AsyncMock(return_value=poll_result)
        service._update_db_record = AsyncMock()

        result = await service.poll_and_complete(
            generation_id="gen-fail",
            kling_task_id="t1",
            endpoint_type=KlingEndpoint.TEXT2VIDEO,
        )

        assert result["status"] == "failed"
        assert result["error_message"] == "Content safety violation"
        # Verify DB was updated with failure status
        update_call = service._update_db_record.call_args
        assert update_call[0][1]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_timeout_propagates(self, service):
        service.poll_task = AsyncMock(side_effect=TimeoutError("Timed out"))
        service._update_db_record = AsyncMock()

        with pytest.raises(TimeoutError):
            await service.poll_and_complete(
                generation_id="gen-timeout",
                kling_task_id="t1",
                endpoint_type=KlingEndpoint.TEXT2VIDEO,
            )

        # DB should be updated with failure
        update_call = service._update_db_record.call_args
        assert update_call[0][1]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_download_failure_still_succeeds(self, service):
        poll_result = {
            "code": 0,
            "data": {
                "task_id": "t1",
                "task_status": "succeed",
                "task_status_msg": "",
                "final_unit_deduction": "10",
                "task_result": {
                    "videos": [{"id": "v1", "url": "http://cdn/v.mp4", "duration": "5.0"}],
                },
            },
        }
        service.poll_task = AsyncMock(return_value=poll_result)
        service.download_and_store = AsyncMock(side_effect=httpx.HTTPStatusError(
            "404", request=MagicMock(), response=MagicMock(status_code=404)
        ))
        service._update_db_record = AsyncMock()

        result = await service.poll_and_complete(
            generation_id="gen-dl-fail",
            kling_task_id="t1",
            endpoint_type=KlingEndpoint.TEXT2VIDEO,
        )

        # Generation succeeded even though download failed
        assert result["status"] == "succeed"
        assert result["video_url"] == "http://cdn/v.mp4"
        # Storage path should be None since download failed
        assert result.get("video_storage_path") is None
        # DB update should include download_status=failed
        update_args = service._update_db_record.call_args[0][1]
        assert update_args["download_status"] == "failed"


# ---------------------------------------------------------------------------
# Download & Storage
# ---------------------------------------------------------------------------

class TestDownloadAndStore:
    @pytest.mark.asyncio
    async def test_happy_path(self, service, mock_supabase):
        mock_response = MagicMock()
        mock_response.content = b"video-data-bytes"
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.is_closed = False
        service._client = mock_client

        result = await service.download_and_store("http://cdn/v.mp4", "gen-dl")
        assert result == "kling-videos/gen-dl/video.mp4"

    @pytest.mark.asyncio
    async def test_http_error_propagates(self, service):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.HTTPStatusError(
            "404", request=MagicMock(), response=MagicMock(status_code=404)
        ))
        mock_client.is_closed = False
        service._client = mock_client

        with pytest.raises(httpx.HTTPStatusError):
            await service.download_and_store("http://cdn/missing.mp4", "gen-err")


class TestDownloadImageToStorage:
    @pytest.mark.asyncio
    async def test_happy_path(self, service, mock_supabase):
        mock_response = MagicMock()
        mock_response.content = b"png-data"
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.is_closed = False
        service._client = mock_client

        result = await service._download_image_to_storage(
            "http://cdn/img.png", "gen-img/multi_shot_0.png"
        )
        assert result == "kling-videos/gen-img/multi_shot_0.png"

    @pytest.mark.asyncio
    async def test_http_error_propagates(self, service):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock(status_code=500)
        ))
        mock_client.is_closed = False
        service._client = mock_client

        with pytest.raises(httpx.HTTPStatusError):
            await service._download_image_to_storage("http://cdn/err.png", "path")


# ---------------------------------------------------------------------------
# Query Methods
# ---------------------------------------------------------------------------

class TestGetGeneration:
    @pytest.mark.asyncio
    async def test_found(self, service, mock_supabase):
        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
            data={"id": "gen-1", "status": "succeed"}
        )
        result = await service.get_generation("gen-1")
        assert result["id"] == "gen-1"
        assert result["status"] == "succeed"

    @pytest.mark.asyncio
    async def test_not_found(self, service, mock_supabase):
        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
            data=None
        )
        result = await service.get_generation("gen-missing")
        assert result is None


class TestListGenerations:
    @pytest.mark.asyncio
    async def test_basic_list(self, service, mock_supabase):
        mock_query = MagicMock()
        mock_query.eq.return_value = mock_query
        mock_query.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"id": "g1"}, {"id": "g2"}]
        )
        mock_supabase.table.return_value.select.return_value.eq.return_value = mock_query

        result = await service.list_generations(organization_id="org-1")
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_with_filters(self, service, mock_supabase):
        mock_query = MagicMock()
        mock_query.eq.return_value = mock_query
        mock_query.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"id": "g1"}]
        )
        mock_supabase.table.return_value.select.return_value.eq.return_value = mock_query

        result = await service.list_generations(
            organization_id="org-1",
            brand_id="brand-1",
            status="succeed",
            generation_type="text_to_video",
        )
        assert len(result) == 1


class TestGetVideoUrl:
    @pytest.mark.asyncio
    async def test_correct_path_split(self, service, mock_supabase):
        result = await service.get_video_url("kling-videos/gen-1/video.mp4")
        assert result == "https://signed-url"
        # Verify correct bucket/path split
        mock_supabase.storage.from_.assert_called_with("kling-videos")

    @pytest.mark.asyncio
    async def test_path_without_bucket(self, service, mock_supabase):
        result = await service.get_video_url("just-a-path")
        assert result == "https://signed-url"
