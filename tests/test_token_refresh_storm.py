"""Regression: Daily Meta Token Refresh retry storm.

Two bugs compounded into an every-6-minute storm:
  1. Meta's fb_exchange_token response omits `expires_in` for ~60-day long-lived
     tokens, but the consumer did `result["expires_in"]` -> KeyError -> the
     account was marked failed.
  2. With a failure, the handler wrote run status `completed_with_errors`, which
     is NOT in the scheduled_job_runs_status_check constraint
     (pending/running/completed/failed). update_job_run swallowed the 23514
     error, the run stayed `running`, and the stuck-run reaper killed it at the
     300s cap and re-queued it — forever.

Fixes: extend_token() defaults expires_in; the handler writes a constraint-valid
status.
"""
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest


WORKER_SRC = Path(__file__).resolve().parents[1] / "viraltracker/worker/scheduler_worker.py"
# Statuses permitted by the scheduled_job_runs_status_check DB constraint.
ALLOWED_RUN_STATUSES = {"pending", "running", "completed", "failed"}


def _mock_httpx_client(json_payload, status_code=200):
    """Build a context-manager mock standing in for httpx.Client()."""
    resp = MagicMock(status_code=status_code)
    resp.json.return_value = json_payload
    resp.text = ""
    client = MagicMock()
    client.get.return_value = resp
    cm = MagicMock()
    cm.__enter__.return_value = client
    cm.__exit__.return_value = False
    return cm


class TestExtendTokenExpiresIn:
    def test_defaults_expires_in_when_meta_omits_it(self):
        import viraltracker.services.meta_oauth_utils as mod
        payload = {"access_token": "fresh-token", "token_type": "bearer"}  # no expires_in
        with patch.object(mod, "_get_app_credentials", return_value=("id", "secret")), \
             patch.object(mod.httpx, "Client", return_value=_mock_httpx_client(payload)):
            result = mod.extend_token("old-long-lived-token")
        assert result is not None
        assert result["access_token"] == "fresh-token"
        # 60 days in seconds — prevents the KeyError that marked the refresh failed
        assert result["expires_in"] == 5184000

    def test_preserves_expires_in_when_present(self):
        import viraltracker.services.meta_oauth_utils as mod
        payload = {"access_token": "fresh-token", "expires_in": 1234}
        with patch.object(mod, "_get_app_credentials", return_value=("id", "secret")), \
             patch.object(mod.httpx, "Client", return_value=_mock_httpx_client(payload)):
            result = mod.extend_token("old-long-lived-token")
        assert result["expires_in"] == 1234

    def test_non_200_still_returns_none(self):
        import viraltracker.services.meta_oauth_utils as mod
        with patch.object(mod, "_get_app_credentials", return_value=("id", "secret")), \
             patch.object(mod.httpx, "Client",
                          return_value=_mock_httpx_client({}, status_code=400)):
            assert mod.extend_token("dead-token") is None


class TestTokenRefreshRunStatus:
    def test_no_invalid_run_status_literal_in_worker(self):
        # Guard: the only non-conforming status literal that caused the storm
        # must never reappear in the worker.
        assert "completed_with_errors" not in WORKER_SRC.read_text()

    def test_token_refresh_handler_writes_allowed_status(self):
        # Every `"status": "<x>"` literal inside execute_token_refresh_job must
        # be a constraint-valid value.
        import re
        src = WORKER_SRC.read_text()
        start = src.index("async def execute_token_refresh_job")
        # slice to the next top-level def/async def
        rest = src[start + 1:]
        m = re.search(r"\n(?:async def |def )", rest)
        body = rest[: m.start()] if m else rest
        statuses = re.findall(r'"status":\s*"([^"]+)"', body)
        assert statuses, "expected the handler to set a run status"
        bad = [s for s in statuses if s not in ALLOWED_RUN_STATUSES]
        assert not bad, f"handler writes invalid run status(es): {bad}"
