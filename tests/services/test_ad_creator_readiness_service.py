"""
Tests for AdCreatorReadinessService.

Exercises each of the six checks across their OK / PARTIAL / BLOCKED / N/A
branches, plus the overall-status rollup and the _compute_asset_pool helper.

All Supabase access is mocked — these are pure unit tests, no network.
"""

from __future__ import annotations

from typing import List, Optional
from unittest.mock import MagicMock, patch

import pytest

from viraltracker.services.ad_creator_readiness_service import (
    AdCreatorReadinessService,
    _compute_asset_pool,
)
from viraltracker.services.models import ReadinessStatus


BRAND_ID = "00000000-0000-0000-0000-000000000aaa"
PRODUCT_ID = "00000000-0000-0000-0000-000000000bbb"
VARIANT_ID = "00000000-0000-0000-0000-000000000ccc"


# ----------------------------------------------------------------------
# Supabase mock helpers
#
# Each call chain on db.table(...) is a separate _Chain object. The test
# pre-registers expected responses keyed by (table_name, action), where
# action is "count" for head=True/count="exact" probes and "select" for
# everything else returning .data. This keeps each individual check
# easy to set up in isolation.
# ----------------------------------------------------------------------

class _Result:
    def __init__(self, data=None, count=None):
        self.data = data
        self.count = count


class _Chain:
    """Fluent mock matching supabase-py's builder shape."""

    def __init__(self, response: _Result):
        self._response = response

    def select(self, *a, count=None, head=False, **kw):
        return self

    def eq(self, *a, **kw):
        return self

    def in_(self, *a, **kw):
        return self

    def gte(self, *a, **kw):
        return self

    def limit(self, *a, **kw):
        return self

    def range(self, *a, **kw):
        return self

    def order(self, *a, **kw):
        return self

    def execute(self):
        return self._response


def _fake_db(responses: dict):
    """Build a mock db whose .table(name) returns the matching _Chain.

    responses: {table_name: _Result(...)}
    """
    db = MagicMock()
    db.table.side_effect = lambda name: _Chain(responses.get(name, _Result(data=[], count=0)))
    return db


def _make_service(responses: dict) -> AdCreatorReadinessService:
    svc = AdCreatorReadinessService.__new__(AdCreatorReadinessService)
    svc._db = _fake_db(responses)
    return svc


# ----------------------------------------------------------------------
# _check_product_images
# ----------------------------------------------------------------------

class TestProductImagesCheck:
    def test_zero_images_blocked(self):
        svc = _make_service({"product_images": _Result(count=0)})
        c = svc._check_product_images(PRODUCT_ID)
        assert c.key == "product_images"
        assert c.status == ReadinessStatus.BLOCKED
        assert "0 images" in c.summary

    def test_few_images_partial(self):
        svc = _make_service({"product_images": _Result(count=3)})
        c = svc._check_product_images(PRODUCT_ID)
        assert c.status == ReadinessStatus.PARTIAL
        assert "3 image" in c.summary

    def test_five_images_ready(self):
        svc = _make_service({"product_images": _Result(count=5)})
        c = svc._check_product_images(PRODUCT_ID)
        assert c.status == ReadinessStatus.READY

    def test_many_images_ready(self):
        svc = _make_service({"product_images": _Result(count=42)})
        c = svc._check_product_images(PRODUCT_ID)
        assert c.status == ReadinessStatus.READY
        assert "42 images" in c.summary


# ----------------------------------------------------------------------
# _check_asset_tags
# ----------------------------------------------------------------------

class TestAssetTagsCheck:
    def _patch_helpers(self, product_tags, pool_result):
        async def _fake_prefetch(_product_id):
            return set(product_tags)

        return patch.multiple(
            "viraltracker.services.ad_creator_readiness_service",
            _prefetch_product_asset_tags=_fake_prefetch,
            _compute_asset_pool=MagicMock(return_value=pool_result),
        )

    def test_no_tags_partial(self):
        svc = _make_service({})
        with self._patch_helpers(set(), (3134, 432, 432)):
            c = svc._check_asset_tags(PRODUCT_ID)
        assert c.status == ReadinessStatus.PARTIAL
        assert "No asset tags" in c.summary
        assert "432/3134" in c.summary

    def test_tagged_low_coverage_partial(self):
        svc = _make_service({})
        # 600/3134 = 19% — under the 25% threshold
        with self._patch_helpers({"product:bottle"}, (3134, 600, 432)):
            c = svc._check_asset_tags(PRODUCT_ID)
        assert c.status == ReadinessStatus.PARTIAL
        assert "600/3134" in c.summary

    def test_tagged_high_coverage_ready(self):
        svc = _make_service({})
        # 1552/3134 = 50% — above threshold
        with self._patch_helpers({"product:bottle"}, (3134, 1552, 432)):
            c = svc._check_asset_tags(PRODUCT_ID)
        assert c.status == ReadinessStatus.READY
        assert "1552/3134" in c.summary

    def test_empty_pool_not_applicable(self):
        svc = _make_service({})
        with self._patch_helpers(set(), (0, 0, 0)):
            c = svc._check_asset_tags(PRODUCT_ID)
        assert c.status == ReadinessStatus.NOT_APPLICABLE


# ----------------------------------------------------------------------
# _check_persona
# ----------------------------------------------------------------------

class TestPersonaCheck:
    def test_no_link_partial(self):
        svc = _make_service({"product_personas": _Result(data=[])})
        c = svc._check_persona(PRODUCT_ID)
        assert c.status == ReadinessStatus.PARTIAL
        assert "No persona linked" in c.summary

    def test_link_but_persona_missing_partial(self):
        svc = _make_service({
            "product_personas": _Result(data=[{"persona_id": "p1", "is_primary": True}]),
            "personas_4d": _Result(data=[]),
        })
        c = svc._check_persona(PRODUCT_ID)
        assert c.status == ReadinessStatus.PARTIAL
        assert "not found" in c.summary

    def test_persona_with_empty_demographics_partial(self):
        svc = _make_service({
            "product_personas": _Result(data=[{"persona_id": "p1", "is_primary": True}]),
            "personas_4d": _Result(data=[{"id": "p1", "name": "Test", "demographics": {}}]),
        })
        c = svc._check_persona(PRODUCT_ID)
        assert c.status == ReadinessStatus.PARTIAL
        assert "no demographics" in c.summary

    def test_persona_with_demographics_ready(self):
        svc = _make_service({
            "product_personas": _Result(data=[{"persona_id": "p1", "is_primary": True}]),
            "personas_4d": _Result(data=[{
                "id": "p1",
                "name": "Test Persona",
                "demographics": {"gender": "female", "age": "40-55"},
            }]),
        })
        c = svc._check_persona(PRODUCT_ID)
        assert c.status == ReadinessStatus.READY
        assert "Test Persona" in c.summary

    def test_prefers_primary_persona(self):
        # When multiple personas linked, the primary one is consulted first.
        svc = _make_service({
            "product_personas": _Result(data=[
                {"persona_id": "secondary", "is_primary": False},
                {"persona_id": "primary",   "is_primary": True},
            ]),
            "personas_4d": _Result(data=[{
                "id": "primary",
                "name": "Primary Persona",
                "demographics": {"gender": "male"},
            }]),
        })
        c = svc._check_persona(PRODUCT_ID)
        assert c.status == ReadinessStatus.READY
        assert "Primary Persona" in c.summary


# ----------------------------------------------------------------------
# _check_offer_variant_mechanism
# ----------------------------------------------------------------------

class TestOfferVariantCheck:
    def test_no_variant_id_not_applicable(self):
        svc = _make_service({})
        c = svc._check_offer_variant_mechanism(None)
        assert c.status == ReadinessStatus.NOT_APPLICABLE

    def test_missing_row_partial(self):
        svc = _make_service({"product_offer_variants": _Result(data=[])})
        c = svc._check_offer_variant_mechanism(VARIANT_ID)
        assert c.status == ReadinessStatus.PARTIAL
        assert "not found" in c.summary

    def test_incomplete_mechanism_partial(self):
        svc = _make_service({"product_offer_variants": _Result(data=[{
            "name": "Variant A",
            "mechanism_name": "",
            "mechanism_problem": None,
            "mechanism_solution": "",
            "sample_hooks": [],
        }])})
        c = svc._check_offer_variant_mechanism(VARIANT_ID)
        assert c.status == ReadinessStatus.PARTIAL
        assert "Variant A" in c.summary

    def test_partial_when_only_one_hook(self):
        svc = _make_service({"product_offer_variants": _Result(data=[{
            "name": "Variant B",
            "mechanism_name": "The Stack",
            "mechanism_problem": "cortisol",
            "mechanism_solution": "magnesium",
            "sample_hooks": ["one hook only"],
        }])})
        c = svc._check_offer_variant_mechanism(VARIANT_ID)
        assert c.status == ReadinessStatus.PARTIAL
        assert "1 sample hook" in c.summary

    def test_complete_ready(self):
        svc = _make_service({"product_offer_variants": _Result(data=[{
            "name": "Variant C",
            "mechanism_name": "The Stack",
            "mechanism_problem": "cortisol dysregulation",
            "mechanism_solution": "adaptogen synergy",
            "sample_hooks": ["hook 1", "hook 2", "hook 3"],
        }])})
        c = svc._check_offer_variant_mechanism(VARIANT_ID)
        assert c.status == ReadinessStatus.READY
        assert "3 sample hook" in c.summary


# ----------------------------------------------------------------------
# _check_brand_voice
# ----------------------------------------------------------------------

class TestBrandVoiceCheck:
    def test_empty_voice_partial(self):
        svc = _make_service({"brands": _Result(data=[{"brand_voice_tone": ""}])})
        c = svc._check_brand_voice(BRAND_ID)
        assert c.status == ReadinessStatus.PARTIAL

    def test_whitespace_only_voice_partial(self):
        svc = _make_service({"brands": _Result(data=[{"brand_voice_tone": "   "}])})
        c = svc._check_brand_voice(BRAND_ID)
        assert c.status == ReadinessStatus.PARTIAL

    def test_brand_row_missing_partial(self):
        svc = _make_service({"brands": _Result(data=[])})
        c = svc._check_brand_voice(BRAND_ID)
        assert c.status == ReadinessStatus.PARTIAL

    def test_voice_set_ready(self):
        svc = _make_service({"brands": _Result(data=[{
            "brand_voice_tone": "Confident, direct, evidence-based; no hype.",
        }])})
        c = svc._check_brand_voice(BRAND_ID)
        assert c.status == ReadinessStatus.READY


# ----------------------------------------------------------------------
# _check_recent_template_diversity
# ----------------------------------------------------------------------

class TestDiversityCheck:
    def test_no_runs_not_applicable(self):
        svc = _make_service({"ad_runs": _Result(data=[])})
        c = svc._check_recent_template_diversity(PRODUCT_ID)
        assert c.status == ReadinessStatus.NOT_APPLICABLE

    def test_low_diversity_partial(self):
        # 3 unique templates across 10 runs → 30% diversity → PARTIAL
        runs = (
            [{"source_scraped_template_id": "t1"}] * 4
            + [{"source_scraped_template_id": "t2"}] * 4
            + [{"source_scraped_template_id": "t3"}] * 2
        )
        svc = _make_service({"ad_runs": _Result(data=runs)})
        c = svc._check_recent_template_diversity(PRODUCT_ID)
        assert c.status == ReadinessStatus.PARTIAL
        assert "3 unique" in c.summary

    def test_high_diversity_ready(self):
        # 9 unique / 10 runs = 90% → READY
        runs = [{"source_scraped_template_id": f"t{i}"} for i in range(10)]
        runs[-1] = {"source_scraped_template_id": "t0"}  # one repeat
        svc = _make_service({"ad_runs": _Result(data=runs)})
        c = svc._check_recent_template_diversity(PRODUCT_ID)
        assert c.status == ReadinessStatus.READY
        assert "9 unique" in c.summary


# ----------------------------------------------------------------------
# Overall rollup
# ----------------------------------------------------------------------

class TestOverallRollup:
    """`check()` rolls individual statuses up to a single `overall`."""

    def _stub_checks(self, svc, statuses: List[ReadinessStatus]):
        from viraltracker.services.models import AdCreatorReadinessCheck

        def make(s, key):
            return AdCreatorReadinessCheck(
                key=key, label=key, status=s, summary=""
            )

        keys = [
            "_check_product_images",
            "_check_asset_tags",
            "_check_persona",
            "_check_offer_variant_mechanism",
            "_check_brand_voice",
            "_check_recent_template_diversity",
        ]
        for method, status in zip(keys, statuses):
            setattr(
                svc,
                method,
                lambda *a, status=status, key=method, **kw: make(status, key),
            )

    def test_all_ready(self):
        svc = _make_service({})
        self._stub_checks(svc, [ReadinessStatus.READY] * 6)
        r = svc.check(BRAND_ID, PRODUCT_ID)
        assert r.overall == ReadinessStatus.READY

    def test_partial_wins_over_ready(self):
        svc = _make_service({})
        self._stub_checks(svc, [
            ReadinessStatus.READY, ReadinessStatus.READY,
            ReadinessStatus.PARTIAL, ReadinessStatus.READY,
            ReadinessStatus.READY, ReadinessStatus.READY,
        ])
        r = svc.check(BRAND_ID, PRODUCT_ID)
        assert r.overall == ReadinessStatus.PARTIAL

    def test_blocked_wins_over_everything(self):
        svc = _make_service({})
        self._stub_checks(svc, [
            ReadinessStatus.READY, ReadinessStatus.PARTIAL,
            ReadinessStatus.BLOCKED, ReadinessStatus.NOT_APPLICABLE,
            ReadinessStatus.READY, ReadinessStatus.READY,
        ])
        r = svc.check(BRAND_ID, PRODUCT_ID)
        assert r.overall == ReadinessStatus.BLOCKED

    def test_not_applicable_ignored_when_others_ready(self):
        svc = _make_service({})
        self._stub_checks(svc, [
            ReadinessStatus.NOT_APPLICABLE,
            ReadinessStatus.READY, ReadinessStatus.READY,
            ReadinessStatus.NOT_APPLICABLE,
            ReadinessStatus.READY, ReadinessStatus.READY,
        ])
        r = svc.check(BRAND_ID, PRODUCT_ID)
        assert r.overall == ReadinessStatus.READY

    def test_all_not_applicable_falls_through(self):
        svc = _make_service({})
        self._stub_checks(svc, [ReadinessStatus.NOT_APPLICABLE] * 6)
        r = svc.check(BRAND_ID, PRODUCT_ID)
        assert r.overall == ReadinessStatus.NOT_APPLICABLE


# ----------------------------------------------------------------------
# _compute_asset_pool helper
# ----------------------------------------------------------------------

class TestComputeAssetPool:
    def _db_with_templates(self, templates):
        # Single-page response; signal end-of-stream by returning < 1000 rows.
        responses = {"scraped_templates": _Result(data=templates)}
        return _fake_db(responses)

    def test_no_requirements_counts_as_full_match(self):
        db = self._db_with_templates([
            {"template_elements": {}},
            {"template_elements": {"required_assets": []}},
            {"template_elements": None},
        ])
        total, fully, no_req = _compute_asset_pool(db, set())
        assert total == 3
        assert no_req == 3
        assert fully == 3

    def test_full_match_when_required_subset_of_product_tags(self):
        db = self._db_with_templates([
            {"template_elements": {"required_assets": ["product:bottle"]}},
            {"template_elements": {"required_assets": ["product:bottle", "product:capsules"]}},
        ])
        total, fully, no_req = _compute_asset_pool(
            db, {"product:bottle", "product:capsules", "product:supplements"}
        )
        assert total == 2
        assert fully == 2  # both fully matched
        assert no_req == 0

    def test_partial_match_does_not_count_as_full(self):
        db = self._db_with_templates([
            {"template_elements": {"required_assets": ["product:bottle", "product:gummies"]}},
        ])
        total, fully, _ = _compute_asset_pool(db, {"product:bottle"})
        assert total == 1
        assert fully == 0  # missing product:gummies

    def test_empty_product_tags_only_matches_no_req_templates(self):
        db = self._db_with_templates([
            {"template_elements": {"required_assets": ["product:bottle"]}},
            {"template_elements": {"required_assets": []}},
        ])
        total, fully, no_req = _compute_asset_pool(db, set())
        assert total == 2
        assert fully == 1
        assert no_req == 1


