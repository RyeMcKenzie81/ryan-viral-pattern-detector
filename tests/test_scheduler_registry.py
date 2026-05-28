"""Verify the JOB_HANDLERS registry is populated after importing the worker.

PR 1 of 2 — the registry is populated at scheduler_worker import time via
@register_job_handler decorators above each execute_*_job function. The
legacy execute_job() elif dispatcher is still the active path in PR 1; the
registry is dormant but must be correctly populated so PR 2 can flip the
switch without surprises.

This test guards against the "added a new job_type but forgot to register
the handler" footgun for all future contributors.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from viraltracker.worker import scheduler_concurrency as sc
import viraltracker.worker.scheduler_worker  # noqa: F401 (import triggers decorators)


# The full job_type set as defined by the dispatcher at scheduler_worker.py:935.
# Source of truth: parsed at runtime below. Static list here is for clarity in
# review — if the dispatcher diverges from this list, the dynamic test catches it.
EXPECTED_JOB_TYPES = {
    "meta_sync", "scorecard", "template_scrape", "template_approval",
    "congruence_reanalysis", "ad_classification", "asset_download",
    "competitor_scrape", "reddit_scrape", "amazon_review_scrape",
    "ad_creation_v2", "ad_creation", "creative_genome_update",
    "creative_deep_analysis", "genome_validation", "winner_evolution",
    "experiment_analysis", "quality_calibration", "ad_intelligence_analysis",
    "analytics_sync", "seo_status_sync", "iteration_auto_run",
    "size_variant", "smart_edit", "seo_content_eval", "seo_publish",
    "seo_auto_interlink", "demographic_backfill", "seo_opportunity_scan",
    "token_refresh", "competitor_intel_analysis", "quick_intel_analysis",
}


def _parse_dispatcher_job_types() -> set[str]:
    """Read scheduler_worker.py and extract job_type strings from the current
    elif dispatcher. The registry MUST match this set."""
    src = Path("viraltracker/worker/scheduler_worker.py").read_text()
    # The dispatcher is `if/elif job_type == 'X': return await execute_X_job(`.
    return set(re.findall(
        r"(?:if|elif)\s+job_type\s*==\s*'([^']+)':\s*\n\s*return\s+await\s+execute_\w+_job\(",
        src,
    ))


class TestRegistryPopulation:

    def test_registry_has_every_dispatcher_job_type(self):
        """Every job_type the elif dispatcher knows about must also be in the
        decorator-driven registry. If this fails, someone added a new branch
        to the dispatcher without adding @register_job_handler."""
        dispatcher_types = _parse_dispatcher_job_types()
        registered_types = set(sc.JOB_HANDLERS.keys())
        missing = dispatcher_types - registered_types
        assert not missing, (
            f"Job types in dispatcher but NOT in registry: {sorted(missing)}. "
            f"Add @register_job_handler({sorted(missing)[0]!r}) to the corresponding execute_*_job."
        )

    def test_registry_has_no_orphans(self):
        """Every registered job_type must correspond to a real dispatcher
        branch. Orphans usually mean a handler was decorated but the
        dispatcher branch was deleted — silent bit-rot waiting to happen."""
        dispatcher_types = _parse_dispatcher_job_types()
        registered_types = set(sc.JOB_HANDLERS.keys())
        orphans = registered_types - dispatcher_types
        assert not orphans, (
            f"Job types registered but NOT in dispatcher: {sorted(orphans)}. "
            f"Either add a dispatcher branch or remove the @register_job_handler."
        )

    def test_expected_set_matches_runtime(self):
        """Sanity: the EXPECTED_JOB_TYPES set in this file matches reality.
        If the codebase gains/loses job types, fail loudly here so the test
        file stays in sync with the dispatcher."""
        runtime_types = _parse_dispatcher_job_types()
        assert runtime_types == EXPECTED_JOB_TYPES, (
            "EXPECTED_JOB_TYPES is out of date. "
            f"Runtime has: {sorted(runtime_types)}. "
            f"Expected: {sorted(EXPECTED_JOB_TYPES)}. "
            "Update EXPECTED_JOB_TYPES in this test file."
        )

    def test_registered_count_matches_dispatcher(self):
        """If counts diverge, one of the more specific tests above gives the
        useful error; this is just a fast read for the operator scanning a
        failure log."""
        assert len(sc.JOB_HANDLERS) == len(_parse_dispatcher_job_types())
