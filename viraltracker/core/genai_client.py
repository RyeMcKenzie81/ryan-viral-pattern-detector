"""
Centralized factory for `google.genai.Client` with a default request timeout.

The Gemini SDK constructs clients with no HTTP timeout by default, so a hung
request can block the calling coroutine indefinitely. In the scheduler worker
that means a single stuck call freezes the entire poll loop — see the
2026-05-22 incident where an Ad Creator V2 run hung mid-image-generation and
prevented `recover_stuck_runs()` from firing.

Always construct `genai.Client` via `make_genai_client(...)` so every call
site inherits a sensible per-request timeout. Override `GEMINI_REQUEST_TIMEOUT_MS`
to tune without code changes; pass `timeout_ms=` to override on a single call site.
"""

import logging
import os
from typing import Optional

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_MS = 600_000  # 10 minutes. Enough headroom for image / video calls.


def _resolve_timeout_ms(timeout_ms: Optional[int]) -> int:
    if timeout_ms is not None:
        return timeout_ms
    raw = os.getenv("GEMINI_REQUEST_TIMEOUT_MS")
    if raw:
        try:
            return int(raw)
        except ValueError:
            logger.warning(
                f"GEMINI_REQUEST_TIMEOUT_MS={raw!r} is not an int; using default {DEFAULT_TIMEOUT_MS}ms"
            )
    return DEFAULT_TIMEOUT_MS


def make_genai_client(
    api_key: str,
    timeout_ms: Optional[int] = None,
) -> genai.Client:
    """Construct a `genai.Client` with a per-request HTTP timeout applied."""
    resolved = _resolve_timeout_ms(timeout_ms)
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=resolved),
    )
