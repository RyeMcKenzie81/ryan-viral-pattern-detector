"""
KlingVideoService - Kling AI video generation via native API.

Direct integration with Kling API at api-singapore.klingai.com.
Uses JWT auth (HS256) with AccessKey + SecretKey.

Official API docs: https://app.klingai.com/global/dev/document-api/

Supported generation types (MVP):
- Avatar talking-head (image + audio)
- Text to video
- Image to video
- Lip-sync (2-step: identify faces, then apply)
- AI Multi-Shot (3 angle images from 1 frontal)

Deferred to V2:
- Video Extension (only works with v1.x model outputs)
- Omni Video (kling-video-o1)
- Callback URL integration (using polling for MVP)

API Pricing (approximate):
- Avatar std: $0.052/second
- Avatar pro: $0.104/second
- Video std 5s: $0.20/clip
- Video pro 5s: $0.33/clip
"""

import asyncio
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any

import httpx
import jwt

from ..core.config import Config
from ..core.database import get_supabase_client
from .usage_tracker import UsageTracker, UsageRecord
from .kling_models import (
    KlingEndpoint,
    KlingTaskStatus,
    KlingGenerationType,
)

logger = logging.getLogger(__name__)


class KlingAPIError(Exception):
    """Error from Kling API with structured error info."""

    def __init__(self, message: str, code: int = 0, request_id: str = ""):
        super().__init__(message)
        self.code = code
        self.request_id = request_id


class KlingVideoService:
    """Kling AI video generation via native API (api-singapore.klingai.com).

    Features:
    - JWT auth with caching (25-min TTL)
    - All MVP generation endpoints (avatar, text2video, image2video, lip-sync, multi-shot)
    - Exponential backoff polling
    - Concurrency control via semaphore
    - Structured error handling with retry logic
    - Supabase storage for persistent video access
    - Usage tracking integration
    """

    BASE_URL = "https://api-singapore.klingai.com"
    STORAGE_BUCKET = "kling-videos"

    # Endpoint path mapping
    ENDPOINTS = {
        KlingEndpoint.TEXT2VIDEO: "/v1/videos/text2video",
        KlingEndpoint.IMAGE2VIDEO: "/v1/videos/image2video",
        KlingEndpoint.AVATAR: "/v1/videos/avatar/image2video",
        KlingEndpoint.IDENTIFY_FACE: "/v1/videos/identify-face",
        KlingEndpoint.LIP_SYNC: "/v1/videos/advanced-lip-sync",
        KlingEndpoint.VIDEO_EXTEND: "/v1/videos/video-extend",
        KlingEndpoint.MULTI_SHOT: "/v1/general/ai-multi-shot",
        KlingEndpoint.OMNI_VIDEO: "/v1/videos/omni-video",
        KlingEndpoint.ADVANCED_CUSTOM_ELEMENTS: "/v1/general/advanced-custom-elements",
    }

    # API task statuses
    TERMINAL_STATUSES = {KlingTaskStatus.SUCCEED.value, KlingTaskStatus.FAILED.value}

    # Default models per endpoint
    DEFAULT_MODELS = {
        KlingEndpoint.TEXT2VIDEO: "kling-v2-6",
        KlingEndpoint.IMAGE2VIDEO: "kling-v2-6",
    }

    # Retry configuration
    MAX_RETRIES_TRANSIENT = 3     # 5xx errors
    MAX_RETRIES_CONCURRENCY = 5   # 1303 errors
    MAX_RETRIES_JWT = 1           # 1004 JWT expired
    BACKOFF_BASE_SECONDS = 2
    BACKOFF_CAP_SECONDS = 60

    # Polling defaults
    DEFAULT_POLL_TIMEOUT = 600    # 10 minutes
    DEFAULT_POLL_INTERVAL = 10    # seconds

    def __init__(
        self,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        max_concurrent: Optional[int] = None,
    ):
        """Initialize Kling video service.

        Args:
            access_key: Kling API access key (defaults to Config.KLING_ACCESS_KEY).
            secret_key: Kling API secret key (defaults to Config.KLING_SECRET_KEY).
            max_concurrent: Max concurrent generation tasks (defaults to Config.KLING_MAX_CONCURRENT).
        """
        self.access_key = access_key or Config.KLING_ACCESS_KEY
        self.secret_key = secret_key or Config.KLING_SECRET_KEY
        self.supabase = get_supabase_client()

        # JWT caching
        self._cached_jwt: Optional[str] = None
        self._jwt_expires_at: float = 0

        # Concurrency control
        self._generation_semaphore = asyncio.Semaphore(
            max_concurrent or Config.KLING_MAX_CONCURRENT
        )

        # Usage tracking (optional)
        self._usage_tracker: Optional[UsageTracker] = None
        self._user_id: Optional[str] = None
        self._organization_id: Optional[str] = None
        self._limit_service = None

        # HTTP client (reused across requests)
        self._client: Optional[httpx.AsyncClient] = None

        logger.info("KlingVideoService initialized")

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the async HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=60.0)
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def set_tracking_context(
        self,
        usage_tracker: UsageTracker,
        user_id: Optional[str] = None,
        organization_id: Optional[str] = None,
    ) -> None:
        """Set usage tracking context for cost tracking.

        Args:
            usage_tracker: UsageTracker instance.
            user_id: User ID for tracking.
            organization_id: Organization ID for billing.
        """
        self._usage_tracker = usage_tracker
        self._user_id = user_id
        self._organization_id = organization_id
        # Set up limit enforcement
        self._limit_service = None
        if organization_id and organization_id != "all":
            try:
                from .usage_limit_service import UsageLimitService
                self._limit_service = UsageLimitService(self.supabase)
            except Exception as e:
                logger.debug(f"UsageLimitService not available: {e}")
        logger.debug(f"KlingVideoService usage tracking enabled for org: {organization_id}")

    # ========================================================================
    # JWT Authentication
    # ========================================================================

    def _get_jwt(self) -> str:
        """Get JWT token, caching with 25-min TTL.

        Token has 30-min expiry. We cache and reuse until 5 minutes before expiry.

        Returns:
            JWT token string.
        """
        now = time.time()
        if self._cached_jwt and self._jwt_expires_at > now + 300:  # 5 min buffer
            return self._cached_jwt

        headers = {"alg": "HS256", "typ": "JWT"}
        payload = {
            "iss": self.access_key,
            "exp": int(now) + 1800,   # 30 min expiry
            "nbf": int(now) - 30,     # 30s buffer for clock skew
        }
        self._cached_jwt = jwt.encode(payload, self.secret_key, headers=headers)
        self._jwt_expires_at = now + 1800
        return self._cached_jwt

    def _invalidate_jwt(self) -> None:
        """Force JWT regeneration on next request."""
        self._cached_jwt = None
        self._jwt_expires_at = 0

    def _headers(self) -> dict:
        """Get HTTP headers with JWT auth."""
        return {
            "Authorization": f"Bearer {self._get_jwt()}",
            "Content-Type": "application/json",
        }

    # ========================================================================
    # Input Validation Helpers
    # ========================================================================

    @staticmethod
    def _strip_base64_prefix(data: str) -> str:
        """Strip data URI prefix from base64 string if present.

        Kling API requires raw Base64 only -- NO data:image/...;base64, prefix.

        Args:
            data: Base64 string, possibly with data URI prefix.

        Returns:
            Clean base64 string.
        """
        if data.startswith("data:"):
            _, _, data = data.partition(",")
        return data

    @staticmethod
    def _validate_mutual_exclusion(
        param_a: Optional[str],
        param_b: Optional[str],
        name_a: str,
        name_b: str,
    ) -> None:
        """Validate exactly one of two mutually exclusive params is provided.

        Args:
            param_a: First parameter value.
            param_b: Second parameter value.
            name_a: Name of first parameter (for error messages).
            name_b: Name of second parameter (for error messages).

        Raises:
            ValueError: If both or neither are provided.
        """
        if param_a and param_b:
            raise ValueError(f"Provide exactly one of {name_a} or {name_b}, not both")
        if not param_a and not param_b:
            raise ValueError(f"Must provide one of {name_a} or {name_b}")

    def _validate_image(self, image_data: str) -> str:
        """Validate and clean image input.

        Args:
            image_data: URL or Base64 image string.

        Returns:
            Cleaned image string.

        Raises:
            ValueError: If image is empty.
        """
        if not image_data:
            raise ValueError("Image is required")
        return self._strip_base64_prefix(image_data)

    # ========================================================================
    # HTTP Methods with Retry Logic
    # ========================================================================

    async def _post(
        self,
        endpoint: KlingEndpoint,
        payload: dict,
    ) -> dict:
        """POST to Kling API with retry logic.

        Handles:
        - 1303 (concurrent limit): Retry up to 5 times with exponential backoff.
        - 1302 (rate limit): Retry up to 5 times with exponential backoff.
        - 1004 (JWT expired): Invalidate cache, regenerate, retry once.
        - 5xx (server error): Retry up to 3 times with exponential backoff.
        - 1301 (content safety): No retry, raise immediately.

        Args:
            endpoint: KlingEndpoint for URL resolution.
            payload: JSON request body.

        Returns:
            Parsed JSON response.

        Raises:
            KlingAPIError: On non-retryable or exhausted-retry errors.
        """
        url = f"{self.BASE_URL}{self.ENDPOINTS[endpoint]}"
        client = await self._get_client()
        last_error = None

        for attempt in range(max(
            self.MAX_RETRIES_TRANSIENT,
            self.MAX_RETRIES_CONCURRENCY,
        ) + 1):
            try:
                response = await client.post(
                    url,
                    json=payload,
                    headers=self._headers(),
                )

                data = response.json()
                code = data.get("code", 0)
                request_id = data.get("request_id", "")

                # Success
                if code == 0:
                    return data

                # Content safety filter -- no retry
                if code == 1301:
                    raise KlingAPIError(
                        "Content safety filter triggered. Try modifying your prompt or image.",
                        code=1301,
                        request_id=request_id,
                    )

                # JWT expired -- invalidate and retry once
                if code == 1004:
                    if attempt < self.MAX_RETRIES_JWT + 1:
                        logger.warning(f"JWT expired (attempt {attempt + 1}), regenerating")
                        self._invalidate_jwt()
                        continue
                    raise KlingAPIError(
                        "Authentication failed after JWT refresh",
                        code=1004,
                        request_id=request_id,
                    )

                # Concurrent task limit -- retry with backoff
                if code == 1303:
                    if attempt < self.MAX_RETRIES_CONCURRENCY:
                        wait = min(
                            self.BACKOFF_BASE_SECONDS * (2 ** attempt),
                            self.BACKOFF_CAP_SECONDS,
                        )
                        logger.warning(
                            f"Concurrent limit (1303), retrying in {wait}s "
                            f"(attempt {attempt + 1}/{self.MAX_RETRIES_CONCURRENCY})"
                        )
                        await asyncio.sleep(wait)
                        continue
                    raise KlingAPIError(
                        "Service busy. Please try again in a few minutes.",
                        code=1303,
                        request_id=request_id,
                    )

                # Rate limit -- retry with backoff
                if code == 1302:
                    if attempt < self.MAX_RETRIES_CONCURRENCY:
                        wait = min(
                            self.BACKOFF_BASE_SECONDS * (2 ** attempt),
                            self.BACKOFF_CAP_SECONDS,
                        )
                        logger.warning(
                            f"Rate limit (1302), retrying in {wait}s "
                            f"(attempt {attempt + 1}/{self.MAX_RETRIES_CONCURRENCY})"
                        )
                        await asyncio.sleep(wait)
                        continue
                    raise KlingAPIError(
                        "Rate limit exceeded. Please try again later.",
                        code=1302,
                        request_id=request_id,
                    )

                # Other API errors -- no retry
                msg = data.get("message", f"Kling API error code {code}")
                raise KlingAPIError(msg, code=code, request_id=request_id)

            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                if status >= 500 and attempt < self.MAX_RETRIES_TRANSIENT:
                    wait = min(
                        self.BACKOFF_BASE_SECONDS * (2 ** attempt),
                        self.BACKOFF_CAP_SECONDS,
                    )
                    logger.warning(
                        f"Server error {status}, retrying in {wait}s "
                        f"(attempt {attempt + 1}/{self.MAX_RETRIES_TRANSIENT})"
                    )
                    await asyncio.sleep(wait)
                    last_error = e
                    continue
                raise KlingAPIError(
                    f"Kling service error (HTTP {status}). This is temporary -- try again.",
                    code=status,
                )

            except (httpx.ConnectError, httpx.TimeoutException) as e:
                if attempt < self.MAX_RETRIES_TRANSIENT:
                    wait = min(
                        self.BACKOFF_BASE_SECONDS * (2 ** attempt),
                        self.BACKOFF_CAP_SECONDS,
                    )
                    logger.warning(
                        f"Connection error, retrying in {wait}s: {e}"
                    )
                    await asyncio.sleep(wait)
                    last_error = e
                    continue
                raise KlingAPIError(f"Connection to Kling API failed: {e}")

        raise KlingAPIError(
            f"Max retries exhausted: {last_error}",
            code=getattr(last_error, 'code', 0) if hasattr(last_error, 'code') else 0,
        )

    async def _get(self, url: str) -> dict:
        """GET from Kling API with JWT auth.

        Args:
            url: Full URL to GET.

        Returns:
            Parsed JSON response.
        """
        client = await self._get_client()
        response = await client.get(url, headers=self._headers())
        response.raise_for_status()
        return response.json()

    # ========================================================================
    # Database Helpers
    # ========================================================================

    async def _create_db_record(self, record: dict) -> str:
        """Create a generation record in the database.

        Args:
            record: Dict of column values.

        Returns:
            The generation ID.
        """
        generation_id = record.get("id", str(uuid.uuid4()))
        record["id"] = generation_id
        record.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        record.setdefault("updated_at", datetime.now(timezone.utc).isoformat())

        await asyncio.to_thread(
            lambda: self.supabase.table("kling_video_generations")
            .insert(record)
            .execute()
        )
        return generation_id

    async def _update_db_record(self, generation_id: str, updates: dict) -> None:
        """Update a generation record in the database.

        Args:
            generation_id: Generation UUID string.
            updates: Dict of column updates.
        """
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        await asyncio.to_thread(
            lambda: self.supabase.table("kling_video_generations")
            .update(updates)
            .eq("id", generation_id)
            .execute()
        )

    # ========================================================================
    # Usage Tracking
    # ========================================================================

    def _track_usage(
        self,
        operation: str,
        unit_type: str,
        units: float,
        cost_usd: float,
        metadata: Optional[dict] = None,
    ) -> None:
        """Track Kling API usage (fire-and-forget).

        Args:
            operation: Operation name (e.g., "generate_avatar_video").
            unit_type: Unit type for billing (e.g., "kling_avatar_std_seconds").
            units: Number of units consumed.
            cost_usd: Estimated cost in USD.
            metadata: Additional metadata.
        """
        if not self._usage_tracker or not self._organization_id:
            return

        try:
            record = UsageRecord(
                provider="kling",
                model="kling-native-api",
                tool_name="kling_video_service",
                operation=operation,
                units=units,
                unit_type=unit_type,
                cost_usd=cost_usd,
                request_metadata=metadata,
            )
            self._usage_tracker.track(
                user_id=self._user_id,
                organization_id=self._organization_id,
                record=record,
            )
        except Exception as e:
            logger.warning(f"Usage tracking failed (non-fatal): {e}")

    def _enforce_limit(self) -> None:
        """Enforce usage limits before expensive operations."""
        if self._limit_service and self._organization_id:
            self._limit_service.enforce_limit(self._organization_id, "monthly_cost")

    # ========================================================================
    # Generation Methods
    # ========================================================================

    async def generate_avatar_video(
        self,
        organization_id: str,
        brand_id: str,
        image: str,
        sound_file: Optional[str] = None,
        audio_id: Optional[str] = None,
        prompt: Optional[str] = None,
        mode: str = "std",
        avatar_id: Optional[str] = None,
        candidate_id: Optional[str] = None,
        callback_url: Optional[str] = None,
        external_task_id: Optional[str] = None,
    ) -> dict:
        """Generate avatar (talking-head) video from image + audio.

        Endpoint: POST /v1/videos/avatar/image2video

        Args:
            organization_id: Organization UUID.
            brand_id: Brand UUID.
            image: URL or Base64 image (jpg/jpeg/png, <=10MB, >=300px).
            sound_file: URL or Base64 audio (mp3/wav/m4a/aac, <=5MB, 2-300s).
                Mutually exclusive with audio_id.
            audio_id: TTS-generated audio ID. Mutually exclusive with sound_file.
            prompt: Actions/emotions/camera (max 2500 chars).
            mode: "std" or "pro".
            avatar_id: Optional brand_avatars reference.
            candidate_id: Optional video_recreation_candidates reference.
            callback_url: Callback URL (deferred to V2).
            external_task_id: Custom task ID for tracking.

        Returns:
            Dict with generation_id, kling_task_id, status.

        Raises:
            ValueError: If input validation fails.
            KlingAPIError: If API call fails.
        """
        self._enforce_limit()
        self._validate_mutual_exclusion(sound_file, audio_id, "sound_file", "audio_id")
        image = self._validate_image(image)

        if sound_file and not sound_file.startswith("http"):
            sound_file = self._strip_base64_prefix(sound_file)

        generation_id = str(uuid.uuid4())
        ext_task_id = external_task_id or generation_id

        # Create DB record before API call
        await self._create_db_record({
            "id": generation_id,
            "organization_id": organization_id,
            "brand_id": brand_id,
            "avatar_id": avatar_id,
            "candidate_id": candidate_id,
            "generation_type": KlingGenerationType.AVATAR.value,
            "mode": mode,
            "prompt": prompt,
            "input_image_url": image[:200] if not image.startswith("http") else image,
            "input_audio_url": sound_file[:200] if sound_file and not sound_file.startswith("http") else sound_file,
            "status": KlingTaskStatus.PENDING.value,
            "kling_external_task_id": ext_task_id,
        })

        # Build payload
        payload: Dict[str, Any] = {
            "image": image,
            "mode": mode,
        }
        if sound_file:
            payload["sound_file"] = sound_file
        elif audio_id:
            payload["audio_id"] = audio_id
        if prompt:
            payload["prompt"] = prompt
        if callback_url:
            payload["callback_url"] = callback_url
        payload["external_task_id"] = ext_task_id

        try:
            async with self._generation_semaphore:
                response = await self._post(KlingEndpoint.AVATAR, payload)

            data = response.get("data", {})
            kling_task_id = data.get("task_id")
            request_id = response.get("request_id", "")

            await self._update_db_record(generation_id, {
                "kling_task_id": kling_task_id,
                "kling_request_id": request_id,
                "status": data.get("task_status", KlingTaskStatus.SUBMITTED.value),
            })

            unit_type = f"kling_avatar_{mode}_seconds"
            self._track_usage(
                operation="generate_avatar_video",
                unit_type=unit_type,
                units=1,  # actual duration unknown until completion
                cost_usd=Config.get_unit_cost(unit_type),
                metadata={"generation_id": generation_id},
            )

            return {
                "generation_id": generation_id,
                "kling_task_id": kling_task_id,
                "status": data.get("task_status", "submitted"),
                "request_id": request_id,
            }

        except Exception as e:
            error_code = getattr(e, "code", None)
            await self._update_db_record(generation_id, {
                "status": KlingTaskStatus.FAILED.value,
                "error_message": str(e),
                "error_code": error_code,
            })
            raise

    async def generate_text_to_video(
        self,
        organization_id: str,
        brand_id: str,
        prompt: str,
        model_name: str = "kling-v2-6",
        mode: str = "pro",
        duration: str = "5",
        aspect_ratio: str = "16:9",
        negative_prompt: Optional[str] = None,
        sound: str = "off",
        cfg_scale: Optional[float] = None,
        camera_control: Optional[dict] = None,
        candidate_id: Optional[str] = None,
        callback_url: Optional[str] = None,
        external_task_id: Optional[str] = None,
    ) -> dict:
        """Generate video from text prompt.

        Endpoint: POST /v1/videos/text2video

        Args:
            organization_id: Organization UUID.
            brand_id: Brand UUID.
            prompt: Video generation prompt (max 2500 chars, required).
            model_name: Model name (kling-v2-6, kling-v2-5-turbo).
            mode: "std" or "pro".
            duration: Duration as STRING "5" or "10".
            aspect_ratio: "16:9", "9:16", or "1:1".
            negative_prompt: Content to avoid (max 2500 chars).
            sound: "on" or "off" (native audio, v2.6+ only).
            cfg_scale: Prompt adherence 0-1 (v1.x only, auto-omitted for v2.x).
            camera_control: Camera movement config.
            candidate_id: Optional recreation candidate reference.
            callback_url: Callback URL (deferred to V2).
            external_task_id: Custom task ID.

        Returns:
            Dict with generation_id, kling_task_id, status.
        """
        self._enforce_limit()

        if not prompt:
            raise ValueError("Prompt is required for text-to-video")
        if duration not in ("5", "10"):
            raise ValueError("Duration must be '5' or '10' (string)")

        generation_id = str(uuid.uuid4())
        ext_task_id = external_task_id or generation_id

        # Estimate cost
        dur_seconds = int(duration)
        if mode == "pro":
            estimated_cost = Config.get_unit_cost("kling_video_pro_5s") * (dur_seconds / 5)
        else:
            estimated_cost = Config.get_unit_cost("kling_video_std_5s") * (dur_seconds / 5)

        await self._create_db_record({
            "id": generation_id,
            "organization_id": organization_id,
            "brand_id": brand_id,
            "candidate_id": candidate_id,
            "generation_type": KlingGenerationType.TEXT_TO_VIDEO.value,
            "model_name": model_name,
            "mode": mode,
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "duration": duration,
            "aspect_ratio": aspect_ratio,
            "cfg_scale": cfg_scale,
            "sound": sound,
            "status": KlingTaskStatus.PENDING.value,
            "estimated_cost_usd": estimated_cost,
            "kling_external_task_id": ext_task_id,
        })

        # Build payload
        payload: Dict[str, Any] = {
            "prompt": prompt,
            "model_name": model_name,
            "mode": mode,
            "duration": duration,
            "aspect_ratio": aspect_ratio,
            "external_task_id": ext_task_id,
        }
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt
        if sound == "on":
            payload["sound"] = "on"
        # cfg_scale only for v1.x models -- auto-omit for v2.x
        if cfg_scale is not None and not model_name.startswith("kling-v2"):
            payload["cfg_scale"] = cfg_scale
        if camera_control:
            payload["camera_control"] = camera_control
        if callback_url:
            payload["callback_url"] = callback_url

        try:
            async with self._generation_semaphore:
                response = await self._post(KlingEndpoint.TEXT2VIDEO, payload)

            data = response.get("data", {})
            kling_task_id = data.get("task_id")
            request_id = response.get("request_id", "")

            await self._update_db_record(generation_id, {
                "kling_task_id": kling_task_id,
                "kling_request_id": request_id,
                "status": data.get("task_status", KlingTaskStatus.SUBMITTED.value),
            })

            self._track_usage(
                operation="generate_text_to_video",
                unit_type=f"kling_video_{mode}_5s",
                units=dur_seconds / 5,
                cost_usd=estimated_cost,
                metadata={"generation_id": generation_id, "model_name": model_name},
            )

            return {
                "generation_id": generation_id,
                "kling_task_id": kling_task_id,
                "status": data.get("task_status", "submitted"),
                "estimated_cost_usd": estimated_cost,
                "request_id": request_id,
            }

        except Exception as e:
            error_code = getattr(e, "code", None)
            await self._update_db_record(generation_id, {
                "status": KlingTaskStatus.FAILED.value,
                "error_message": str(e),
                "error_code": error_code,
            })
            raise

    async def generate_image_to_video(
        self,
        organization_id: str,
        brand_id: str,
        image: str,
        prompt: Optional[str] = None,
        model_name: str = "kling-v2-6",
        mode: str = "pro",
        duration: str = "5",
        image_tail: Optional[str] = None,
        negative_prompt: Optional[str] = None,
        sound: str = "off",
        cfg_scale: Optional[float] = None,
        camera_control: Optional[dict] = None,
        candidate_id: Optional[str] = None,
        callback_url: Optional[str] = None,
        external_task_id: Optional[str] = None,
    ) -> dict:
        """Generate video from image (animate still image).

        Endpoint: POST /v1/videos/image2video

        Args:
            organization_id: Organization UUID.
            brand_id: Brand UUID.
            image: URL or Base64 image (required).
            prompt: Animation prompt (max 2500 chars).
            model_name: Model name (kling-v2-6, kling-v2-5-turbo).
            mode: "std" or "pro".
            duration: Duration as STRING "5" or "10".
            image_tail: End frame image (mutually exclusive with camera_control).
            negative_prompt: Content to avoid.
            sound: "on" or "off" (v2.6+ only).
            cfg_scale: Prompt adherence 0-1 (v1.x only).
            camera_control: Camera movement (mutually exclusive with image_tail).
            candidate_id: Optional recreation candidate reference.
            callback_url: Callback URL (deferred to V2).
            external_task_id: Custom task ID.

        Returns:
            Dict with generation_id, kling_task_id, status.

        Raises:
            ValueError: If image_tail and camera_control both provided.
        """
        self._enforce_limit()

        image = self._validate_image(image)
        if image_tail and camera_control:
            raise ValueError("image_tail and camera_control are mutually exclusive")
        if duration not in ("5", "10"):
            raise ValueError("Duration must be '5' or '10' (string)")

        if image_tail:
            image_tail = self._strip_base64_prefix(image_tail)

        generation_id = str(uuid.uuid4())
        ext_task_id = external_task_id or generation_id

        dur_seconds = int(duration)
        if mode == "pro":
            estimated_cost = Config.get_unit_cost("kling_video_pro_5s") * (dur_seconds / 5)
        else:
            estimated_cost = Config.get_unit_cost("kling_video_std_5s") * (dur_seconds / 5)

        await self._create_db_record({
            "id": generation_id,
            "organization_id": organization_id,
            "brand_id": brand_id,
            "candidate_id": candidate_id,
            "generation_type": KlingGenerationType.IMAGE_TO_VIDEO.value,
            "model_name": model_name,
            "mode": mode,
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "input_image_url": image[:200] if not image.startswith("http") else image,
            "duration": duration,
            "aspect_ratio": "16:9",  # default; image determines actual
            "cfg_scale": cfg_scale,
            "sound": sound,
            "status": KlingTaskStatus.PENDING.value,
            "estimated_cost_usd": estimated_cost,
            "kling_external_task_id": ext_task_id,
        })

        payload: Dict[str, Any] = {
            "image": image,
            "model_name": model_name,
            "mode": mode,
            "duration": duration,
            "external_task_id": ext_task_id,
        }
        if prompt:
            payload["prompt"] = prompt
        if image_tail:
            payload["image_tail"] = image_tail
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt
        if sound == "on":
            payload["sound"] = "on"
        if cfg_scale is not None and not model_name.startswith("kling-v2"):
            payload["cfg_scale"] = cfg_scale
        if camera_control:
            payload["camera_control"] = camera_control
        if callback_url:
            payload["callback_url"] = callback_url

        try:
            async with self._generation_semaphore:
                response = await self._post(KlingEndpoint.IMAGE2VIDEO, payload)

            data = response.get("data", {})
            kling_task_id = data.get("task_id")
            request_id = response.get("request_id", "")

            await self._update_db_record(generation_id, {
                "kling_task_id": kling_task_id,
                "kling_request_id": request_id,
                "status": data.get("task_status", KlingTaskStatus.SUBMITTED.value),
            })

            self._track_usage(
                operation="generate_image_to_video",
                unit_type=f"kling_video_{mode}_5s",
                units=dur_seconds / 5,
                cost_usd=estimated_cost,
                metadata={"generation_id": generation_id, "model_name": model_name},
            )

            return {
                "generation_id": generation_id,
                "kling_task_id": kling_task_id,
                "status": data.get("task_status", "submitted"),
                "estimated_cost_usd": estimated_cost,
                "request_id": request_id,
            }

        except Exception as e:
            error_code = getattr(e, "code", None)
            await self._update_db_record(generation_id, {
                "status": KlingTaskStatus.FAILED.value,
                "error_message": str(e),
                "error_code": error_code,
            })
            raise

    async def identify_faces(
        self,
        organization_id: str,
        brand_id: str,
        video_id: Optional[str] = None,
        video_url: Optional[str] = None,
        parent_generation_id: Optional[str] = None,
    ) -> dict:
        """Identify faces in a video (lip-sync step 1).

        Endpoint: POST /v1/videos/identify-face
        This is a SYNCHRONOUS endpoint -- returns immediately with face data.

        Args:
            organization_id: Organization UUID.
            brand_id: Brand UUID.
            video_id: Kling-generated video ID (mutually exclusive with video_url).
            video_url: External video URL (mp4/mov, <=100MB, 2-60s).
                Mutually exclusive with video_id.
            parent_generation_id: Optional link to source video generation.

        Returns:
            Dict with generation_id, session_id, face_data, session_expires_at.
        """
        self._validate_mutual_exclusion(video_id, video_url, "video_id", "video_url")

        generation_id = str(uuid.uuid4())

        await self._create_db_record({
            "id": generation_id,
            "organization_id": organization_id,
            "brand_id": brand_id,
            "parent_generation_id": parent_generation_id,
            "generation_type": KlingGenerationType.IDENTIFY_FACE.value,
            "status": KlingTaskStatus.PENDING.value,
        })

        payload: Dict[str, Any] = {}
        if video_id:
            payload["video_id"] = video_id
        elif video_url:
            payload["video_url"] = video_url

        try:
            # identify-face is sync, no semaphore needed
            response = await self._post(KlingEndpoint.IDENTIFY_FACE, payload)

            data = response.get("data", {})
            session_id = data.get("session_id")
            face_data = data.get("face_data", [])
            request_id = response.get("request_id", "")
            session_expires_at = (
                datetime.now(timezone.utc) + timedelta(hours=24)
            ).isoformat()

            await self._update_db_record(generation_id, {
                "kling_request_id": request_id,
                "status": KlingTaskStatus.AWAITING_FACE_SELECTION.value,
                "lip_sync_session_id": session_id,
                "lip_sync_session_expires_at": session_expires_at,
                "lip_sync_face_data": face_data,
            })

            return {
                "generation_id": generation_id,
                "session_id": session_id,
                "face_data": face_data,
                "session_expires_at": session_expires_at,
                "request_id": request_id,
            }

        except Exception as e:
            error_code = getattr(e, "code", None)
            await self._update_db_record(generation_id, {
                "status": KlingTaskStatus.FAILED.value,
                "error_message": str(e),
                "error_code": error_code,
            })
            raise

    async def apply_lip_sync(
        self,
        organization_id: str,
        brand_id: str,
        session_id: str,
        face_id: str,
        sound_file: Optional[str] = None,
        audio_id: Optional[str] = None,
        sound_start_time: int = 0,
        sound_end_time: Optional[int] = None,
        sound_insert_time: int = 0,
        sound_volume: float = 1.0,
        original_audio_volume: float = 1.0,
        parent_generation_id: Optional[str] = None,
        callback_url: Optional[str] = None,
        external_task_id: Optional[str] = None,
    ) -> dict:
        """Apply lip-sync to a video (step 2).

        Endpoint: POST /v1/videos/advanced-lip-sync
        Wraps params into face_choose array per API spec.

        Args:
            organization_id: Organization UUID.
            brand_id: Brand UUID.
            session_id: Session ID from identify_faces (valid 24h).
            face_id: Selected face_id from face detection results.
            sound_file: Audio (mp3/wav/m4a, <=5MB, 2-60s). Mutually exclusive with audio_id.
            audio_id: TTS audio ID. Mutually exclusive with sound_file.
            sound_start_time: Audio crop start in ms.
            sound_end_time: Audio crop end in ms.
            sound_insert_time: Insert point in video timeline in ms.
            sound_volume: Audio volume 0-2 (default 1.0).
            original_audio_volume: Original video audio volume 0-2 (default 1.0).
            parent_generation_id: Link to identify-face generation record.
            callback_url: Callback URL (deferred to V2).
            external_task_id: Custom task ID.

        Returns:
            Dict with generation_id, kling_task_id, status.
        """
        self._enforce_limit()
        self._validate_mutual_exclusion(sound_file, audio_id, "sound_file", "audio_id")

        if sound_file and not sound_file.startswith("http"):
            sound_file = self._strip_base64_prefix(sound_file)

        generation_id = str(uuid.uuid4())
        ext_task_id = external_task_id or generation_id

        await self._create_db_record({
            "id": generation_id,
            "organization_id": organization_id,
            "brand_id": brand_id,
            "parent_generation_id": parent_generation_id,
            "generation_type": KlingGenerationType.LIP_SYNC.value,
            "lip_sync_session_id": session_id,
            "lip_sync_face_id": face_id,
            "input_audio_url": sound_file[:200] if sound_file and not sound_file.startswith("http") else sound_file,
            "status": KlingTaskStatus.PENDING.value,
            "kling_external_task_id": ext_task_id,
        })

        # Build face_choose array per API spec
        face_entry: Dict[str, Any] = {
            "face_id": face_id,
            "sound_start_time": sound_start_time,
            "sound_insert_time": sound_insert_time,
            "sound_volume": sound_volume,
            "original_audio_volume": original_audio_volume,
        }
        if sound_file:
            face_entry["sound_file"] = sound_file
        else:
            face_entry["audio_id"] = audio_id
        if sound_end_time is not None:
            face_entry["sound_end_time"] = sound_end_time

        payload: Dict[str, Any] = {
            "session_id": session_id,
            "face_choose": [face_entry],
            "external_task_id": ext_task_id,
        }
        if callback_url:
            payload["callback_url"] = callback_url

        try:
            async with self._generation_semaphore:
                response = await self._post(KlingEndpoint.LIP_SYNC, payload)

            data = response.get("data", {})
            kling_task_id = data.get("task_id")
            request_id = response.get("request_id", "")

            await self._update_db_record(generation_id, {
                "kling_task_id": kling_task_id,
                "kling_request_id": request_id,
                "status": data.get("task_status", KlingTaskStatus.SUBMITTED.value),
            })

            self._track_usage(
                operation="apply_lip_sync",
                unit_type="kling_lip_sync",
                units=1,
                cost_usd=Config.get_unit_cost("kling_lip_sync"),
                metadata={"generation_id": generation_id},
            )

            return {
                "generation_id": generation_id,
                "kling_task_id": kling_task_id,
                "status": data.get("task_status", "submitted"),
                "request_id": request_id,
            }

        except Exception as e:
            error_code = getattr(e, "code", None)
            await self._update_db_record(generation_id, {
                "status": KlingTaskStatus.FAILED.value,
                "error_message": str(e),
                "error_code": error_code,
            })
            raise

    async def create_multi_shot(
        self,
        organization_id: str,
        brand_id: str,
        element_frontal_image: str,
        callback_url: Optional[str] = None,
        external_task_id: Optional[str] = None,
    ) -> dict:
        """Create multi-shot images (3 angles from 1 frontal image).

        Endpoint: POST /v1/general/ai-multi-shot
        Returns 3 images showing different angles of the element.

        Args:
            organization_id: Organization UUID.
            brand_id: Brand UUID.
            element_frontal_image: URL or Base64 frontal image.
            callback_url: Callback URL (deferred to V2).
            external_task_id: Custom task ID.

        Returns:
            Dict with generation_id, kling_task_id, status.
        """
        element_frontal_image = self._validate_image(element_frontal_image)

        generation_id = str(uuid.uuid4())
        ext_task_id = external_task_id or generation_id

        await self._create_db_record({
            "id": generation_id,
            "organization_id": organization_id,
            "brand_id": brand_id,
            "generation_type": KlingGenerationType.MULTI_SHOT.value,
            "input_image_url": element_frontal_image[:200] if not element_frontal_image.startswith("http") else element_frontal_image,
            "status": KlingTaskStatus.PENDING.value,
            "kling_external_task_id": ext_task_id,
        })

        payload: Dict[str, Any] = {
            "element_frontal_image": element_frontal_image,
            "external_task_id": ext_task_id,
        }
        if callback_url:
            payload["callback_url"] = callback_url

        try:
            async with self._generation_semaphore:
                response = await self._post(KlingEndpoint.MULTI_SHOT, payload)

            data = response.get("data", {})
            kling_task_id = data.get("task_id")
            request_id = response.get("request_id", "")

            await self._update_db_record(generation_id, {
                "kling_task_id": kling_task_id,
                "kling_request_id": request_id,
                "status": data.get("task_status", KlingTaskStatus.SUBMITTED.value),
            })

            self._track_usage(
                operation="create_multi_shot",
                unit_type="kling_multi_shot",
                units=1,
                cost_usd=Config.get_unit_cost("kling_multi_shot"),
                metadata={"generation_id": generation_id},
            )

            return {
                "generation_id": generation_id,
                "kling_task_id": kling_task_id,
                "status": data.get("task_status", "submitted"),
                "request_id": request_id,
            }

        except Exception as e:
            error_code = getattr(e, "code", None)
            await self._update_db_record(generation_id, {
                "status": KlingTaskStatus.FAILED.value,
                "error_message": str(e),
                "error_code": error_code,
            })
            raise

    async def create_element(
        self,
        organization_id: str,
        brand_id: str,
        element_name: str,
        element_description: str,
        frontal_image: str,
        refer_images: Optional[List[str]] = None,
        callback_url: Optional[str] = None,
        external_task_id: Optional[str] = None,
    ) -> dict:
        """Create a custom element for character consistency across videos.

        Endpoint: POST /v1/general/advanced-custom-elements

        Elements are created once per avatar and reused indefinitely across all
        video generations via element_list in Omni Video requests.

        Args:
            organization_id: Organization UUID.
            brand_id: Brand UUID.
            element_name: Element name (max 20 chars).
            element_description: Element description (max 100 chars).
            frontal_image: URL or Base64 front-facing reference image (required).
            refer_images: Optional list of 1-3 additional angle reference image URLs/Base64.
            callback_url: Callback URL.
            external_task_id: Custom task ID.

        Returns:
            Dict with generation_id, kling_task_id, status.
        """
        self._enforce_limit()
        frontal_image = self._validate_image(frontal_image)

        generation_id = str(uuid.uuid4())
        ext_task_id = external_task_id or generation_id

        await self._create_db_record({
            "id": generation_id,
            "organization_id": organization_id,
            "brand_id": brand_id,
            "generation_type": KlingGenerationType.ADVANCED_CUSTOM_ELEMENTS.value,
            "input_image_url": frontal_image[:200] if not frontal_image.startswith("http") else frontal_image,
            "status": KlingTaskStatus.PENDING.value,
            "kling_external_task_id": ext_task_id,
        })

        element_image_list = {"frontal_image": frontal_image}
        if refer_images:
            element_image_list["refer_images"] = [
                {"image_url": self._strip_base64_prefix(img) if not img.startswith("http") else img}
                for img in refer_images[:3]
            ]

        payload: Dict[str, Any] = {
            "element_name": element_name[:20],
            "element_description": element_description[:100],
            "reference_type": "image_refer",
            "element_image_list": element_image_list,
        }
        if callback_url:
            payload["callback_url"] = callback_url
        payload["external_task_id"] = ext_task_id

        try:
            async with self._generation_semaphore:
                response = await self._post(KlingEndpoint.ADVANCED_CUSTOM_ELEMENTS, payload)

            data = response.get("data", {})
            kling_task_id = data.get("task_id")
            request_id = response.get("request_id", "")

            await self._update_db_record(generation_id, {
                "kling_task_id": kling_task_id,
                "kling_request_id": request_id,
                "status": data.get("task_status", KlingTaskStatus.SUBMITTED.value),
            })

            self._track_usage(
                operation="create_element",
                unit_type="kling_multi_shot",
                units=1,
                cost_usd=Config.get_unit_cost("kling_multi_shot"),
                metadata={"generation_id": generation_id},
            )

            return {
                "generation_id": generation_id,
                "kling_task_id": kling_task_id,
                "status": data.get("task_status", "submitted"),
                "request_id": request_id,
            }

        except Exception as e:
            error_code = getattr(e, "code", None)
            await self._update_db_record(generation_id, {
                "status": KlingTaskStatus.FAILED.value,
                "error_message": str(e),
                "error_code": error_code,
            })
            raise

    async def create_video_element(
        self,
        organization_id: str,
        brand_id: str,
        element_name: str,
        element_description: str,
        video_url: str,
        element_voice_id: Optional[str] = None,
        callback_url: Optional[str] = None,
        external_task_id: Optional[str] = None,
    ) -> dict:
        """Create a video-based custom element for character + voice consistency.

        Uses reference_type: "video_refer" with a video file instead of images.
        If the video contains speech, Kling auto-extracts voice and binds it
        to the element. An existing voice_id can be bound via element_voice_id.

        Endpoint: POST /v1/general/advanced-custom-elements

        Args:
            organization_id: Organization UUID.
            brand_id: Brand UUID.
            element_name: Element name (max 20 chars).
            element_description: Element description (max 100 chars).
            video_url: URL of reference video (.mp4/.mov, 1080p, 3-8s, max 200MB).
            element_voice_id: Optional existing voice_id to bind to the element.
            callback_url: Callback URL.
            external_task_id: Custom task ID.

        Returns:
            Dict with generation_id, kling_task_id, status.
        """
        self._enforce_limit()

        if not video_url:
            raise ValueError("video_url is required for video element creation")

        generation_id = str(uuid.uuid4())
        ext_task_id = external_task_id or generation_id

        await self._create_db_record({
            "id": generation_id,
            "organization_id": organization_id,
            "brand_id": brand_id,
            "generation_type": KlingGenerationType.ADVANCED_CUSTOM_ELEMENTS.value,
            "status": KlingTaskStatus.PENDING.value,
            "kling_external_task_id": ext_task_id,
        })

        payload: Dict[str, Any] = {
            "element_name": element_name[:20],
            "element_description": element_description[:100],
            "reference_type": "video_refer",
            "element_video_list": {
                "refer_videos": [{"video_url": video_url}]
            },
            "tag_list": [{"tag_id": "o_102"}],
            "external_task_id": ext_task_id,
        }
        if element_voice_id:
            payload["element_voice_id"] = element_voice_id
        if callback_url:
            payload["callback_url"] = callback_url

        try:
            async with self._generation_semaphore:
                response = await self._post(KlingEndpoint.ADVANCED_CUSTOM_ELEMENTS, payload)

            data = response.get("data", {})
            kling_task_id = data.get("task_id")
            request_id = response.get("request_id", "")

            await self._update_db_record(generation_id, {
                "kling_task_id": kling_task_id,
                "kling_request_id": request_id,
                "status": data.get("task_status", KlingTaskStatus.SUBMITTED.value),
            })

            self._track_usage(
                operation="create_video_element",
                unit_type="kling_multi_shot",
                units=1,
                cost_usd=Config.get_unit_cost("kling_multi_shot"),
                metadata={"generation_id": generation_id},
            )

            return {
                "generation_id": generation_id,
                "kling_task_id": kling_task_id,
                "status": data.get("task_status", "submitted"),
                "request_id": request_id,
            }

        except Exception as e:
            error_code = getattr(e, "code", None)
            await self._update_db_record(generation_id, {
                "status": KlingTaskStatus.FAILED.value,
                "error_message": str(e),
                "error_code": error_code,
            })
            raise

    async def query_element(self, task_id: str) -> dict:
        """Query element creation status and extract element_voice_info.

        Endpoint: GET /v1/general/advanced-custom-elements/{task_id}

        After element creation succeeds, use this to extract:
        - element_id
        - element_voice_info.voice_id
        - element_voice_info.voice_name
        - element_voice_info.trial_url

        Args:
            task_id: Kling task_id from create response.

        Returns:
            Full element query response data.
        """
        url = f"{self.BASE_URL}{self.ENDPOINTS[KlingEndpoint.ADVANCED_CUSTOM_ELEMENTS]}/{task_id}"
        return await self._get(url)

    async def delete_element(self, element_id: str) -> dict:
        """Delete a custom element.

        Endpoint: POST /v1/general/delete-elements

        Used to clean up temporary elements created solely for voice extraction.

        Args:
            element_id: Element ID to delete.

        Returns:
            API response dict.
        """
        url = f"{self.BASE_URL}/v1/general/delete-elements"
        client = await self._get_client()
        response = await client.post(
            url,
            json={"element_id": element_id},
            headers=self._headers(),
        )
        response.raise_for_status()
        return response.json()

    async def generate_omni_video(
        self,
        organization_id: str,
        brand_id: str,
        prompt: str,
        duration: str = "5",
        mode: str = "pro",
        sound: str = "on",
        image_list: Optional[List[Dict[str, str]]] = None,
        element_list: Optional[List[Dict[str, str]]] = None,
        aspect_ratio: Optional[str] = None,
        candidate_id: Optional[str] = None,
        callback_url: Optional[str] = None,
        external_task_id: Optional[str] = None,
    ) -> dict:
        """Generate video using Kling Omni Video (3.0).

        Endpoint: POST /v1/videos/omni-video

        Supports first/last frame keyframes for scene transitions,
        element references for character consistency, and native audio.

        Args:
            organization_id: Organization UUID.
            brand_id: Brand UUID.
            prompt: Video prompt (max 2500 chars). Use <<<element_1>>> for element refs.
            duration: Duration as string '3'-'15'.
            mode: 'std' (720p) or 'pro' (1080p).
            sound: 'on' or 'off' for native audio.
            image_list: Keyframe images. Each: {image_url: str, type: 'first_frame'|'end_frame'}.
            element_list: Pre-created element IDs. Each: {element_id: str}.
            aspect_ratio: '16:9', '9:16', '1:1'. Required when no first-frame image.
            candidate_id: Optional recreation candidate reference.
            callback_url: Callback URL.
            external_task_id: Custom task ID.

        Returns:
            Dict with generation_id, kling_task_id, status, estimated_cost_usd.

        Raises:
            ValueError: If validation fails.
        """
        self._enforce_limit()

        # Validate duration
        try:
            dur_int = int(duration)
        except (ValueError, TypeError):
            raise ValueError(f"Duration must be a numeric string, got '{duration}'")
        if dur_int < 3 or dur_int > 15:
            raise ValueError(f"Duration must be between 3 and 15, got {dur_int}")

        # Validate prompt length
        if len(prompt) > 2500:
            raise ValueError(f"Prompt exceeds 2500 chars ({len(prompt)})")

        # Validate image+element count constraints
        num_images = len(image_list) if image_list else 0
        num_elements = len(element_list) if element_list else 0
        has_video_ref = bool(self)  # placeholder — video_list not used yet
        has_video_ref = False  # no video refs in this implementation
        max_refs = 4 if has_video_ref else 7
        if num_images + num_elements > max_refs:
            raise ValueError(
                f"Total images ({num_images}) + elements ({num_elements}) "
                f"exceeds max {max_refs}"
            )

        # Validate keyframe ordering: first_frame required before end_frame
        if image_list:
            types = [img.get("type") for img in image_list]
            if "end_frame" in types and "first_frame" not in types:
                raise ValueError("first_frame required before end_frame")
            if types.count("end_frame") > 0 and num_images > 2:
                raise ValueError("end_frame not supported with >2 images in image_list")

        # Require aspect_ratio when no first-frame image
        has_first_frame = image_list and any(
            img.get("type") == "first_frame" for img in image_list
        )
        if not has_first_frame and not aspect_ratio:
            aspect_ratio = "16:9"

        # Cost estimation (verified from official pricing)
        has_audio = sound == "on"
        if mode == "pro":
            cost_key = "kling_omni_pro_audio_seconds" if has_audio else "kling_omni_pro_seconds"
        else:
            cost_key = "kling_omni_std_audio_seconds" if has_audio else "kling_omni_std_seconds"
        estimated_cost = dur_int * Config.get_unit_cost(cost_key)

        generation_id = str(uuid.uuid4())
        ext_task_id = external_task_id or generation_id

        await self._create_db_record({
            "id": generation_id,
            "organization_id": organization_id,
            "brand_id": brand_id,
            "candidate_id": candidate_id,
            "generation_type": KlingGenerationType.OMNI_VIDEO.value,
            "model_name": "kling-v3-omni",
            "mode": mode,
            "prompt": prompt[:2500],
            "duration": str(dur_int),
            "aspect_ratio": aspect_ratio,
            "sound": sound,
            "status": KlingTaskStatus.PENDING.value,
            "estimated_cost_usd": estimated_cost,
            "kling_external_task_id": ext_task_id,
        })

        payload: Dict[str, Any] = {
            "model_name": "kling-v3-omni",
            "prompt": prompt[:2500],
            "duration": str(dur_int),
            "mode": mode,
            "sound": sound,
            "external_task_id": ext_task_id,
        }
        if image_list:
            payload["image_list"] = image_list
        if element_list:
            payload["element_list"] = element_list
        if aspect_ratio:
            payload["aspect_ratio"] = aspect_ratio
        if callback_url:
            payload["callback_url"] = callback_url

        try:
            async with self._generation_semaphore:
                response = await self._post(KlingEndpoint.OMNI_VIDEO, payload)

            data = response.get("data", {})
            kling_task_id = data.get("task_id")
            request_id = response.get("request_id", "")

            await self._update_db_record(generation_id, {
                "kling_task_id": kling_task_id,
                "kling_request_id": request_id,
                "status": data.get("task_status", KlingTaskStatus.SUBMITTED.value),
            })

            self._track_usage(
                operation="generate_omni_video",
                unit_type=cost_key,
                units=dur_int,
                cost_usd=estimated_cost,
                metadata={"generation_id": generation_id, "model_name": "kling-v3-omni"},
            )

            return {
                "generation_id": generation_id,
                "kling_task_id": kling_task_id,
                "status": data.get("task_status", "submitted"),
                "estimated_cost_usd": estimated_cost,
                "request_id": request_id,
            }

        except Exception as e:
            error_code = getattr(e, "code", None)
            await self._update_db_record(generation_id, {
                "status": KlingTaskStatus.FAILED.value,
                "error_message": str(e),
                "error_code": error_code,
            })
            raise

    # ========================================================================
    # Polling
    # ========================================================================

    async def poll_task(
        self,
        task_id: str,
        endpoint_type: KlingEndpoint,
        timeout_seconds: int = DEFAULT_POLL_TIMEOUT,
        initial_interval: int = DEFAULT_POLL_INTERVAL,
    ) -> dict:
        """Poll task status with exponential backoff.

        Backoff pattern: 10s, 15s, 22s, 33s... capped at 60s.
        On 1004 (JWT expired): invalidate cache, regenerate, retry once.

        Args:
            task_id: Kling task_id from create response.
            endpoint_type: KlingEndpoint enum for query path resolution.
            timeout_seconds: Max time to poll (default 600s / 10 min).
            initial_interval: Initial polling interval in seconds.

        Returns:
            Full response data on succeed/failed.

        Raises:
            TimeoutError: If polling exceeds timeout.
            KlingAPIError: On unrecoverable errors.
        """
        query_url = f"{self.BASE_URL}{self.ENDPOINTS[endpoint_type]}/{task_id}"
        start_time = time.time()
        interval = initial_interval
        jwt_retried = False

        while (time.time() - start_time) < timeout_seconds:
            try:
                data = await self._get(query_url)
                code = data.get("code", 0)

                # JWT expired during polling
                if code == 1004 and not jwt_retried:
                    self._invalidate_jwt()
                    jwt_retried = True
                    continue

                task_data = data.get("data", {})
                task_status = task_data.get("task_status", "")

                if task_status in self.TERMINAL_STATUSES:
                    return data

                logger.debug(
                    f"Polling {endpoint_type.value}/{task_id}: "
                    f"status={task_status}, elapsed={time.time() - start_time:.0f}s"
                )

            except httpx.HTTPStatusError as e:
                if e.response.status_code >= 500:
                    logger.warning(f"Server error during polling: {e}")
                else:
                    raise

            # Exponential backoff: interval * 1.5, capped at 60s
            await asyncio.sleep(interval)
            interval = min(interval * 1.5, self.BACKOFF_CAP_SECONDS)

        raise TimeoutError(
            f"Polling timed out after {timeout_seconds}s for "
            f"{endpoint_type.value}/{task_id}"
        )

    async def poll_and_complete(
        self,
        generation_id: str,
        kling_task_id: str,
        endpoint_type: KlingEndpoint,
        timeout_seconds: int = DEFAULT_POLL_TIMEOUT,
    ) -> dict:
        """Poll a task and update DB record on completion.

        Convenience method that combines polling with DB updates and
        video download on success.

        Args:
            generation_id: Internal generation UUID.
            kling_task_id: Kling task_id for polling.
            endpoint_type: KlingEndpoint for query path.
            timeout_seconds: Max poll time.

        Returns:
            Dict with final status, video_url, storage_path.
        """
        start_time = time.time()

        try:
            result = await self.poll_task(
                kling_task_id, endpoint_type, timeout_seconds
            )

            task_data = result.get("data", {})
            task_status = task_data.get("task_status", "")
            task_status_msg = task_data.get("task_status_msg", "")
            final_units = task_data.get("final_unit_deduction", "")
            generation_time = time.time() - start_time

            if task_status == KlingTaskStatus.SUCCEED.value:
                # Extract video/image results
                task_result = task_data.get("task_result", {})
                videos = task_result.get("videos", [])
                images = task_result.get("images", [])

                video_url = videos[0]["url"] if videos else None
                video_id = videos[0].get("id") if videos else None

                updates: Dict[str, Any] = {
                    "status": KlingTaskStatus.SUCCEED.value,
                    "task_status_msg": task_status_msg,
                    "actual_kling_units": final_units,
                    "generation_time_seconds": round(generation_time, 2),
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                }

                if video_url:
                    updates["video_url"] = video_url
                    # Download to Supabase
                    try:
                        storage_path = await self.download_and_store(
                            video_url, generation_id
                        )
                        updates["video_storage_path"] = storage_path
                        updates["download_status"] = "downloaded"
                    except Exception as e:
                        logger.error(f"Download failed for {generation_id}: {e}")
                        updates["download_status"] = "failed"

                if images:
                    multi_shot_data = []
                    for img in images:
                        try:
                            img_path = await self._download_image_to_storage(
                                img["url"],
                                f"{generation_id}/multi_shot_{img['index']}.png",
                            )
                            multi_shot_data.append({
                                "index": img["index"],
                                "storage_path": img_path,
                                "kling_url": img["url"],
                            })
                        except Exception as e:
                            logger.error(f"Multi-shot download failed: {e}")
                            multi_shot_data.append({
                                "index": img["index"],
                                "storage_path": None,
                                "kling_url": img["url"],
                            })
                    updates["multi_shot_images"] = multi_shot_data

                await self._update_db_record(generation_id, updates)

                return {
                    "generation_id": generation_id,
                    "status": "succeed",
                    "video_url": video_url,
                    "video_storage_path": updates.get("video_storage_path"),
                    "multi_shot_images": updates.get("multi_shot_images"),
                    "generation_time_seconds": round(generation_time, 2),
                }

            else:
                # Failed
                await self._update_db_record(generation_id, {
                    "status": KlingTaskStatus.FAILED.value,
                    "task_status_msg": task_status_msg,
                    "error_message": task_status_msg or "Generation failed",
                    "generation_time_seconds": round(generation_time, 2),
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                })

                return {
                    "generation_id": generation_id,
                    "status": "failed",
                    "error_message": task_status_msg,
                }

        except TimeoutError as e:
            await self._update_db_record(generation_id, {
                "status": KlingTaskStatus.FAILED.value,
                "error_message": str(e),
                "completed_at": datetime.now(timezone.utc).isoformat(),
            })
            raise

    # ========================================================================
    # Download & Storage
    # ========================================================================

    async def download_and_store(
        self,
        video_url: str,
        generation_id: str,
    ) -> str:
        """Download video from Kling CDN and store in Supabase.

        Kling CDN URLs expire after 30 days. This downloads immediately
        to Supabase for persistent access.

        Args:
            video_url: Kling CDN video URL.
            generation_id: Internal generation UUID (used for storage path).

        Returns:
            Supabase storage path.
        """
        client = await self._get_client()
        response = await client.get(video_url)
        response.raise_for_status()
        video_data = response.content

        path = f"{generation_id}/video.mp4"
        await asyncio.to_thread(
            lambda: self.supabase.storage.from_(self.STORAGE_BUCKET).upload(
                path, video_data, {"content-type": "video/mp4"}
            )
        )
        return f"{self.STORAGE_BUCKET}/{path}"

    async def _download_image_to_storage(
        self,
        image_url: str,
        storage_path: str,
    ) -> str:
        """Download image from URL and store in Supabase.

        Args:
            image_url: Source image URL.
            storage_path: Target path within STORAGE_BUCKET.

        Returns:
            Full Supabase storage path.
        """
        client = await self._get_client()
        response = await client.get(image_url)
        response.raise_for_status()
        image_data = response.content

        await asyncio.to_thread(
            lambda: self.supabase.storage.from_(self.STORAGE_BUCKET).upload(
                storage_path, image_data, {"content-type": "image/png"}
            )
        )
        return f"{self.STORAGE_BUCKET}/{storage_path}"

    # ========================================================================
    # Query Methods
    # ========================================================================

    async def get_generation(self, generation_id: str) -> Optional[dict]:
        """Get a generation record from the database.

        Args:
            generation_id: Internal generation UUID.

        Returns:
            Dict of generation data or None if not found.
        """
        result = await asyncio.to_thread(
            lambda: self.supabase.table("kling_video_generations")
            .select("*")
            .eq("id", generation_id)
            .single()
            .execute()
        )
        return result.data if result.data else None

    async def list_generations(
        self,
        organization_id: str,
        brand_id: Optional[str] = None,
        status: Optional[str] = None,
        generation_type: Optional[str] = None,
        limit: int = 20,
    ) -> List[dict]:
        """List generation records with optional filters.

        Args:
            organization_id: Organization UUID (required for multi-tenancy).
            brand_id: Optional brand filter.
            status: Optional status filter.
            generation_type: Optional generation type filter.
            limit: Max results (default 20).

        Returns:
            List of generation record dicts.
        """
        query = (
            self.supabase.table("kling_video_generations")
            .select("*")
            .eq("organization_id", organization_id)
        )
        if brand_id:
            query = query.eq("brand_id", brand_id)
        if status:
            query = query.eq("status", status)
        if generation_type:
            query = query.eq("generation_type", generation_type)

        result = await asyncio.to_thread(
            lambda: query.order("created_at", desc=True).limit(limit).execute()
        )
        return result.data or []

    async def get_video_url(
        self,
        storage_path: str,
        expires_in: int = 3600,
    ) -> str:
        """Get a signed URL for video playback.

        Args:
            storage_path: Full storage path (e.g., "kling-videos/gen-id/video.mp4").
            expires_in: URL expiry in seconds (default 1 hour).

        Returns:
            Signed URL for video playback.
        """
        parts = storage_path.split("/", 1)
        bucket = parts[0]
        path = parts[1] if len(parts) > 1 else storage_path

        result = await asyncio.to_thread(
            lambda: self.supabase.storage.from_(bucket).create_signed_url(
                path, expires_in
            )
        )
        return result.get("signedURL", "")
