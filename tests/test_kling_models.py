"""Unit tests for Kling AI Pydantic models.

Tests enum values, field validators, Literal constraints, model construction,
and default values for all models in kling_models.py.
"""

import pytest
from pydantic import ValidationError

from viraltracker.services.kling_models import (
    KlingEndpoint,
    KlingTaskStatus,
    KlingGenerationType,
    KlingAspectRatio,
    KlingMode,
    AvatarVideoRequest,
    TextToVideoRequest,
    ImageToVideoRequest,
    IdentifyFacesRequest,
    LipSyncRequest,
    VideoExtendRequest,
    MultiShotRequest,
    OmniVideoRequest,
    OmniVideoImageRef,
    CreateElementRequest,
    KlingCreateResponse,
    KlingQueryResponse,
    KlingIdentifyFaceResponse,
    KlingGenerationRecord,
    KlingFaceData,
    KlingVideoResult,
    KlingImageResult,
)


# ---------------------------------------------------------------------------
# Enum value tests
# ---------------------------------------------------------------------------

class TestKlingEndpoint:
    def test_all_endpoint_values(self):
        assert KlingEndpoint.TEXT2VIDEO == "text2video"
        assert KlingEndpoint.IMAGE2VIDEO == "image2video"
        assert KlingEndpoint.AVATAR == "avatar"
        assert KlingEndpoint.IDENTIFY_FACE == "identify_face"
        assert KlingEndpoint.LIP_SYNC == "lip_sync"
        assert KlingEndpoint.VIDEO_EXTEND == "video_extend"
        assert KlingEndpoint.MULTI_SHOT == "multi_shot"
        assert KlingEndpoint.OMNI_VIDEO == "omni_video"

    def test_advanced_custom_elements_value(self):
        assert KlingEndpoint.ADVANCED_CUSTOM_ELEMENTS == "advanced_custom_elements"

    def test_endpoint_count(self):
        assert len(KlingEndpoint) == 9


class TestKlingTaskStatus:
    def test_all_status_values(self):
        assert KlingTaskStatus.PENDING == "pending"
        assert KlingTaskStatus.CANCELLED == "cancelled"
        assert KlingTaskStatus.SUBMITTED == "submitted"
        assert KlingTaskStatus.PROCESSING == "processing"
        assert KlingTaskStatus.SUCCEED == "succeed"
        assert KlingTaskStatus.FAILED == "failed"
        assert KlingTaskStatus.AWAITING_FACE_SELECTION == "awaiting_face_selection"

    def test_status_count(self):
        assert len(KlingTaskStatus) == 7


class TestKlingGenerationType:
    def test_all_type_values(self):
        assert KlingGenerationType.AVATAR == "avatar"
        assert KlingGenerationType.TEXT_TO_VIDEO == "text_to_video"
        assert KlingGenerationType.IMAGE_TO_VIDEO == "image_to_video"
        assert KlingGenerationType.IDENTIFY_FACE == "identify_face"
        assert KlingGenerationType.LIP_SYNC == "lip_sync"
        assert KlingGenerationType.VIDEO_EXTEND == "video_extend"
        assert KlingGenerationType.MULTI_SHOT == "multi_shot"

    def test_omni_video_value(self):
        assert KlingGenerationType.OMNI_VIDEO == "omni_video"

    def test_advanced_custom_elements_value(self):
        assert KlingGenerationType.ADVANCED_CUSTOM_ELEMENTS == "advanced_custom_elements"

    def test_type_count(self):
        assert len(KlingGenerationType) == 9


class TestKlingMode:
    def test_mode_values(self):
        assert KlingMode.STD == "std"
        assert KlingMode.PRO == "pro"


class TestKlingAspectRatio:
    def test_aspect_ratio_values(self):
        assert KlingAspectRatio.LANDSCAPE == "16:9"
        assert KlingAspectRatio.PORTRAIT == "9:16"
        assert KlingAspectRatio.SQUARE == "1:1"


# ---------------------------------------------------------------------------
# Request model tests
# ---------------------------------------------------------------------------

class TestAvatarVideoRequest:
    def test_minimal_valid(self):
        req = AvatarVideoRequest(image="http://example.com/face.jpg")
        assert req.image == "http://example.com/face.jpg"
        assert req.mode == KlingMode.STD
        assert req.sound_file is None
        assert req.audio_id is None
        assert req.prompt is None

    def test_with_sound_file(self):
        req = AvatarVideoRequest(
            image="base64data",
            sound_file="http://example.com/audio.mp3",
            prompt="smile and wave",
        )
        assert req.sound_file == "http://example.com/audio.mp3"
        assert req.prompt == "smile and wave"

    def test_image_required(self):
        with pytest.raises(ValidationError):
            AvatarVideoRequest()

    def test_prompt_max_length(self):
        req = AvatarVideoRequest(image="img", prompt="a" * 2500)
        assert len(req.prompt) == 2500

        with pytest.raises(ValidationError):
            AvatarVideoRequest(image="img", prompt="a" * 2501)


class TestTextToVideoRequest:
    def test_minimal_valid(self):
        req = TextToVideoRequest(prompt="A cat running")
        assert req.prompt == "A cat running"
        assert req.model_name == "kling-v2-6"
        assert req.mode == KlingMode.PRO
        assert req.duration == "5"
        assert req.aspect_ratio == KlingAspectRatio.LANDSCAPE
        assert req.sound == "off"
        assert req.cfg_scale is None

    def test_duration_must_be_string(self):
        req = TextToVideoRequest(prompt="test", duration="10")
        assert req.duration == "10"

    def test_duration_rejects_invalid(self):
        with pytest.raises(ValidationError):
            TextToVideoRequest(prompt="test", duration="15")

    def test_duration_rejects_integer_type(self):
        # Literal["5", "10"] should reject int
        with pytest.raises(ValidationError):
            TextToVideoRequest(prompt="test", duration=5)

    def test_cfg_scale_bounds(self):
        req = TextToVideoRequest(prompt="test", cfg_scale=0.0)
        assert req.cfg_scale == 0.0

        req = TextToVideoRequest(prompt="test", cfg_scale=1.0)
        assert req.cfg_scale == 1.0

        with pytest.raises(ValidationError):
            TextToVideoRequest(prompt="test", cfg_scale=1.5)

        with pytest.raises(ValidationError):
            TextToVideoRequest(prompt="test", cfg_scale=-0.1)

    def test_prompt_required(self):
        with pytest.raises(ValidationError):
            TextToVideoRequest()

    def test_sound_literal(self):
        req = TextToVideoRequest(prompt="test", sound="on")
        assert req.sound == "on"

        with pytest.raises(ValidationError):
            TextToVideoRequest(prompt="test", sound="yes")


class TestImageToVideoRequest:
    def test_minimal_valid(self):
        req = ImageToVideoRequest(image="http://example.com/img.png")
        assert req.image == "http://example.com/img.png"
        assert req.model_name == "kling-v2-6"
        assert req.duration == "5"

    def test_image_required(self):
        with pytest.raises(ValidationError):
            ImageToVideoRequest()

    def test_duration_string_literal(self):
        req = ImageToVideoRequest(image="img", duration="10")
        assert req.duration == "10"

        with pytest.raises(ValidationError):
            ImageToVideoRequest(image="img", duration="7")


class TestIdentifyFacesRequest:
    def test_with_video_id(self):
        req = IdentifyFacesRequest(video_id="abc123")
        assert req.video_id == "abc123"
        assert req.video_url is None

    def test_with_video_url(self):
        req = IdentifyFacesRequest(video_url="http://example.com/video.mp4")
        assert req.video_url == "http://example.com/video.mp4"

    def test_both_none_allowed_at_model_level(self):
        # Mutual exclusion enforced at service level, not model level
        req = IdentifyFacesRequest()
        assert req.video_id is None
        assert req.video_url is None


class TestLipSyncRequest:
    def test_minimal_valid(self):
        req = LipSyncRequest(
            session_id="sess123",
            face_id="face456",
            sound_file="http://example.com/audio.mp3",
        )
        assert req.session_id == "sess123"
        assert req.face_id == "face456"
        assert req.sound_start_time == 0
        assert req.sound_volume == 1.0
        assert req.original_audio_volume == 1.0

    def test_volume_bounds(self):
        req = LipSyncRequest(
            session_id="s", face_id="f", sound_file="a",
            sound_volume=0.0, original_audio_volume=2.0,
        )
        assert req.sound_volume == 0.0
        assert req.original_audio_volume == 2.0

        with pytest.raises(ValidationError):
            LipSyncRequest(
                session_id="s", face_id="f", sound_file="a",
                sound_volume=2.5,
            )

    def test_required_fields(self):
        with pytest.raises(ValidationError):
            LipSyncRequest()


class TestMultiShotRequest:
    def test_minimal_valid(self):
        req = MultiShotRequest(element_frontal_image="base64data")
        assert req.element_frontal_image == "base64data"

    def test_required_field(self):
        with pytest.raises(ValidationError):
            MultiShotRequest()


class TestVideoExtendRequest:
    def test_minimal_valid(self):
        req = VideoExtendRequest(video_id="vid123")
        assert req.video_id == "vid123"
        assert req.cfg_scale == 0.5

    def test_cfg_scale_default(self):
        req = VideoExtendRequest(video_id="v")
        assert req.cfg_scale == 0.5


class TestOmniVideoImageRef:
    def test_first_frame(self):
        ref = OmniVideoImageRef(image_url="http://example.com/img.png", type="first_frame")
        assert ref.type == "first_frame"

    def test_end_frame(self):
        ref = OmniVideoImageRef(image_url="base64data", type="end_frame")
        assert ref.type == "end_frame"

    def test_invalid_type_rejected(self):
        with pytest.raises(ValidationError):
            OmniVideoImageRef(image_url="img", type="middle_frame")

    def test_image_url_required(self):
        with pytest.raises(ValidationError):
            OmniVideoImageRef(type="first_frame")


class TestOmniVideoRequest:
    def test_minimal_valid(self):
        req = OmniVideoRequest(prompt="A sunset over the ocean")
        assert req.model_name == "kling-v3-omni"
        assert req.sound == "on"
        assert req.mode == "pro"
        assert req.duration == "5"
        assert req.multi_shot is False

    def test_prompt_required(self):
        with pytest.raises(ValidationError):
            OmniVideoRequest()

    def test_prompt_max_length(self):
        req = OmniVideoRequest(prompt="a" * 2500)
        assert len(req.prompt) == 2500

        with pytest.raises(ValidationError):
            OmniVideoRequest(prompt="a" * 2501)

    def test_duration_validation_range(self):
        req = OmniVideoRequest(prompt="test", duration="3")
        assert req.duration == "3"

        req = OmniVideoRequest(prompt="test", duration="15")
        assert req.duration == "15"

        with pytest.raises(ValidationError):
            OmniVideoRequest(prompt="test", duration="2")

        with pytest.raises(ValidationError):
            OmniVideoRequest(prompt="test", duration="16")

    def test_duration_accepts_string_integers(self):
        for d in range(3, 16):
            req = OmniVideoRequest(prompt="test", duration=str(d))
            assert req.duration == str(d)

    def test_sound_literal(self):
        req = OmniVideoRequest(prompt="test", sound="off")
        assert req.sound == "off"

        with pytest.raises(ValidationError):
            OmniVideoRequest(prompt="test", sound="yes")

    def test_mode_literal(self):
        req = OmniVideoRequest(prompt="test", mode="std")
        assert req.mode == "std"

        with pytest.raises(ValidationError):
            OmniVideoRequest(prompt="test", mode="ultra")

    def test_with_image_list(self):
        req = OmniVideoRequest(
            prompt="test",
            image_list=[
                {"image_url": "http://img1.jpg", "type": "first_frame"},
                {"image_url": "http://img2.jpg", "type": "end_frame"},
            ],
        )
        assert len(req.image_list) == 2

    def test_with_element_list(self):
        req = OmniVideoRequest(
            prompt="<<<element_1>>> walks forward",
            element_list=[{"element_id": "elem-123"}],
        )
        assert len(req.element_list) == 1


class TestCreateElementRequest:
    def test_minimal_valid(self):
        req = CreateElementRequest(
            element_name="Avatar",
            element_description="Brand spokesperson",
        )
        assert req.element_name == "Avatar"
        assert req.reference_type == "image_refer"

    def test_name_max_length(self):
        req = CreateElementRequest(
            element_name="a" * 20,
            element_description="test",
        )
        assert len(req.element_name) == 20

        with pytest.raises(ValidationError):
            CreateElementRequest(
                element_name="a" * 21,
                element_description="test",
            )

    def test_description_max_length(self):
        req = CreateElementRequest(
            element_name="test",
            element_description="a" * 100,
        )
        assert len(req.element_description) == 100

        with pytest.raises(ValidationError):
            CreateElementRequest(
                element_name="test",
                element_description="a" * 101,
            )

    def test_with_image_list(self):
        req = CreateElementRequest(
            element_name="Avatar",
            element_description="test",
            element_image_list={
                "frontal_image": "http://front.jpg",
                "refer_images": [{"image_url": "http://side.jpg"}],
            },
        )
        assert req.element_image_list["frontal_image"] == "http://front.jpg"

    def test_required_fields(self):
        with pytest.raises(ValidationError):
            CreateElementRequest()


# ---------------------------------------------------------------------------
# Response model tests
# ---------------------------------------------------------------------------

class TestKlingCreateResponse:
    def test_minimal_response(self):
        resp = KlingCreateResponse(code=0, message="OK", request_id="req123")
        assert resp.code == 0
        assert resp.task_id is None

    def test_full_response(self):
        resp = KlingCreateResponse(
            code=0, message="OK", request_id="req123",
            task_id="task456", task_status="submitted",
        )
        assert resp.task_id == "task456"
        assert resp.task_status == "submitted"


class TestKlingFaceData:
    def test_face_data(self):
        face = KlingFaceData(
            face_id="f1", face_image="http://img.jpg",
            start_time=0, end_time=5200,
        )
        assert face.face_id == "f1"
        assert face.end_time == 5200


class TestKlingVideoResult:
    def test_video_result(self):
        vid = KlingVideoResult(id="v1", url="http://cdn/v.mp4", duration="5.0")
        assert vid.id == "v1"
        assert vid.duration == "5.0"


class TestKlingImageResult:
    def test_image_result(self):
        img = KlingImageResult(index=0, url="http://cdn/img.png")
        assert img.index == 0


# ---------------------------------------------------------------------------
# Database record model tests
# ---------------------------------------------------------------------------

class TestKlingGenerationRecord:
    def test_defaults(self):
        from uuid import uuid4
        record = KlingGenerationRecord(
            id=uuid4(),
            organization_id=uuid4(),
            brand_id=uuid4(),
            generation_type=KlingGenerationType.TEXT_TO_VIDEO,
        )
        assert record.mode == KlingMode.STD
        assert record.status == "pending"
        assert record.sound == "off"
        assert record.download_status == "pending"
        assert record.model_name is None
        assert record.lip_sync_session_id is None
        assert record.multi_shot_images is None

    def test_all_generation_types_accepted(self):
        from uuid import uuid4
        for gen_type in KlingGenerationType:
            record = KlingGenerationRecord(
                id=uuid4(),
                organization_id=uuid4(),
                brand_id=uuid4(),
                generation_type=gen_type,
            )
            assert record.generation_type == gen_type
