"""GEMINI_REQUESTS_PER_MINUTE env var must drive the client-side rate limiter.

The default (9 req/min) protects free-tier keys; paid tiers raise throughput via
the env var on Railway/local without code changes. Garbage values fall back to 9;
zero/negative clamp to 1 (the limiter must never divide by zero).
"""
from unittest.mock import patch

from viraltracker.services.gemini_service import GeminiService


def _svc():
    with patch("viraltracker.services.gemini_service.make_genai_client"):
        return GeminiService(api_key="test-key")


def test_default_is_9_rpm(monkeypatch):
    monkeypatch.delenv("GEMINI_REQUESTS_PER_MINUTE", raising=False)
    svc = _svc()
    assert svc._requests_per_minute == 9
    assert svc._min_delay == 60.0 / 9


def test_env_var_raises_limit(monkeypatch):
    monkeypatch.setenv("GEMINI_REQUESTS_PER_MINUTE", "30")
    svc = _svc()
    assert svc._requests_per_minute == 30
    assert svc._min_delay == 2.0


def test_garbage_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("GEMINI_REQUESTS_PER_MINUTE", "fast please")
    assert _svc()._requests_per_minute == 9


def test_zero_clamps_to_one(monkeypatch):
    monkeypatch.setenv("GEMINI_REQUESTS_PER_MINUTE", "0")
    assert _svc()._requests_per_minute == 1
