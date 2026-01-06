"""
Logfire observability configuration for ViralTracker.

Provides tracing and monitoring for:
- Service method calls
- Async operations
- Database queries
- AI/LLM calls (via Pydantic AI integration)

Usage:
    # At app startup (e.g., in main.py or streamlit app)
    from viraltracker.core.observability import setup_logfire
    setup_logfire()

    # In services, use the logger or span context
    import logfire

    with logfire.span("download_assets", competitor_id=str(competitor_id)):
        # ... operation code
        logfire.info("Downloaded {count} assets", count=len(results))

Environment Variables:
    LOGFIRE_TOKEN: Your Logfire write token (required for production)
    LOGFIRE_PROJECT_NAME: Project name in Logfire dashboard
    LOGFIRE_ENVIRONMENT: Environment name (development, staging, production)
"""

import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_logfire_configured = False


def setup_logfire(
    project_name: Optional[str] = None,
    environment: Optional[str] = None,
    service_name: str = "viraltracker"
) -> bool:
    """
    Configure Logfire for observability.

    Args:
        project_name: Logfire project name (or LOGFIRE_PROJECT_NAME env var)
        environment: Environment name (or LOGFIRE_ENVIRONMENT env var)
        service_name: Service name for tracing

    Returns:
        True if Logfire was configured, False if skipped (no token)
    """
    global _logfire_configured

    if _logfire_configured:
        logger.debug("Logfire already configured")
        return True

    import sys

    try:
        import logfire
        print("[LOGFIRE] logfire module imported successfully", file=sys.stderr, flush=True)
    except ImportError:
        print("[LOGFIRE] ERROR: logfire not installed. Run: pip install logfire", file=sys.stderr, flush=True)
        logger.warning("Logfire not installed. Run: pip install logfire")
        return False

    # Check for token
    token = os.environ.get("LOGFIRE_TOKEN")
    if not token:
        print("[LOGFIRE] LOGFIRE_TOKEN not set, skipping Logfire configuration", file=sys.stderr, flush=True)
        logger.info("LOGFIRE_TOKEN not set, skipping Logfire configuration")
        return False
    else:
        print(f"[LOGFIRE] LOGFIRE_TOKEN found (length: {len(token)})", file=sys.stderr, flush=True)

    # Get configuration from env or params
    project = project_name or os.environ.get("LOGFIRE_PROJECT_NAME", "viraltracker")
    env = environment or os.environ.get("LOGFIRE_ENVIRONMENT", "development")

    try:
        # Configure Logfire
        logfire.configure(
            token=token,
            project_name=project,
            service_name=service_name,
            environment=env,
            send_to_logfire=True,
        )

        # Instrument Pydantic for validation tracing
        logfire.instrument_pydantic()

        # Instrument Pydantic AI for LLM call tracing (prompts, responses, tool calls)
        logfire.instrument_pydantic_ai()

        _logfire_configured = True
        print(f"[LOGFIRE] Configured successfully: project={project}, environment={env}", file=sys.stderr, flush=True)
        logger.info(f"Logfire configured: project={project}, environment={env}")
        return True

    except Exception as e:
        print(f"[LOGFIRE] Failed to configure: {e}", file=sys.stderr, flush=True)
        logger.error(f"Failed to configure Logfire: {e}")
        return False


def get_logfire():
    """
    Get the logfire module if configured, otherwise return a no-op stub.

    Usage:
        lf = get_logfire()
        with lf.span("operation"):
            lf.info("message")
    """
    try:
        import logfire
        if _logfire_configured:
            return logfire
    except ImportError:
        pass

    # Return no-op stub
    return _LogfireStub()


class _LogfireStub:
    """No-op stub when Logfire is not configured."""

    def span(self, *args, **kwargs):
        return _NoOpContext()

    def info(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class _NoOpContext:
    """No-op context manager."""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass
