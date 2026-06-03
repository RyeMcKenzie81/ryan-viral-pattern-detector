"""Verify the JOB_HANDLERS registry is populated after importing the worker.

PR 2 of 2 — the legacy execute_job() elif dispatcher is gone. The registry
populated at scheduler_worker import time IS the only dispatcher. These tests
guard against the "added a new job_type but forgot @register_job_handler"
footgun and against drift between the static EXPECTED_JOB_TYPES list and
what's actually registered.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from viraltracker.worker import scheduler_concurrency as sc
import viraltracker.worker.scheduler_worker  # noqa: F401 (import triggers decorators)


# The full job_type set as registered by @register_job_handler decorators
# across scheduler_worker.py. Static list here is for clarity in review and
# in failure messages; the dynamic test below parses the source so this list
# can't silently drift from reality.
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
    "destination_sync", "weekly_product_digest",
}


def _parse_decorator_job_types() -> set[str]:
    """Read scheduler_worker.py and extract job_type strings from each
    @register_job_handler decorator. The runtime registry MUST match this
    set — if a decorator is in source but didn't register, something is
    very wrong with import order."""
    src = Path("viraltracker/worker/scheduler_worker.py").read_text()
    return set(re.findall(r"@register_job_handler\('([^']+)'\)", src))


class TestRegistryPopulation:

    def test_runtime_registry_matches_source_decorators(self):
        """Every @register_job_handler('X') in source must appear in the
        runtime registry. If they diverge, decorator import is broken."""
        source_types = _parse_decorator_job_types()
        registered_types = set(sc.JOB_HANDLERS.keys())
        in_source_not_runtime = source_types - registered_types
        in_runtime_not_source = registered_types - source_types
        assert not in_source_not_runtime, (
            f"Decorators in source but NOT in runtime registry: "
            f"{sorted(in_source_not_runtime)}. Import order issue?"
        )
        assert not in_runtime_not_source, (
            f"In runtime registry but NOT in source decorators: "
            f"{sorted(in_runtime_not_source)}. Someone called "
            f"register_job_handler outside of scheduler_worker.py?"
        )

    def test_expected_set_matches_runtime(self):
        """Sanity: the EXPECTED_JOB_TYPES set in this file matches reality.
        If the codebase gains/loses job types, fail loudly here so the test
        file stays in sync with the registry."""
        runtime_types = set(sc.JOB_HANDLERS.keys())
        assert runtime_types == EXPECTED_JOB_TYPES, (
            "EXPECTED_JOB_TYPES is out of date. "
            f"Runtime has: {sorted(runtime_types)}. "
            f"Expected: {sorted(EXPECTED_JOB_TYPES)}. "
            "Update EXPECTED_JOB_TYPES in this test file."
        )

    def test_registered_count_matches_source(self):
        """If counts diverge, one of the more specific tests above gives the
        useful error; this is a fast read for an operator scanning a fail."""
        assert len(sc.JOB_HANDLERS) == len(_parse_decorator_job_types())

    def test_dispatch_unknown_raises_clear_error(self):
        """The new execute_job() at scheduler_worker.py routes via
        dispatch_job(); unknown job_types now raise a KeyError that names
        what IS registered, not the silent 'Unknown job_type' fallthrough
        that the old elif chain had."""
        with pytest.raises(KeyError) as ei:
            sc.dispatch_job("definitely_not_a_real_job_type_xyz")
        msg = str(ei.value)
        assert "definitely_not_a_real_job_type_xyz" in msg
        # And the error names at least one real registered job_type so the
        # reader can see the legal set.
        assert any(jt in msg for jt in EXPECTED_JOB_TYPES)
