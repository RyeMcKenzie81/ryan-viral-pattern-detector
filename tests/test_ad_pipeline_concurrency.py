"""Within-job parallelization of the V2 ad pipeline (generate / defect-scan / review).

1. bounded_gather: order preservation, concurrency cap, sequential fallback,
   no-orphan exception semantics.
2. pipeline_concurrency: env parsing (default 1 = historical sequential behavior).
3. generate_image source tripwire: the image-gen SDK call must run via
   asyncio.to_thread — a bare sync call freezes the event loop and silently
   serializes the whole feature (PR #290 bug class).
4. GenerateAdsNode integration: ordered results, per-variant failure isolation,
   ads_generated counting, cap honored under concurrency.

Run with: pytest tests/test_ad_pipeline_concurrency.py -v
"""
from __future__ import annotations

import asyncio
import inspect
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from viraltracker.pipelines.ad_creation_v2.utils import (
    AD_PIPELINE_CONCURRENCY_ENV,
    bounded_gather,
    pipeline_concurrency,
)


# ---------------------------------------------------------------------------
# 1. bounded_gather mechanics
# ---------------------------------------------------------------------------
class TestBoundedGather:
    def test_preserves_item_order_despite_completion_order(self):
        async def main():
            async def worker(n):
                # Earlier items sleep LONGER, so completion order is reversed
                await asyncio.sleep(0.03 - n * 0.01)
                return n * 10
            return await bounded_gather([0, 1, 2], worker, concurrency=3)
        assert asyncio.run(main()) == [0, 10, 20]

    def test_concurrency_cap_enforced(self):
        async def main():
            active = 0
            high_water = 0

            async def worker(n):
                nonlocal active, high_water
                active += 1
                high_water = max(high_water, active)
                await asyncio.sleep(0.01)
                active -= 1
                return n
            await bounded_gather(list(range(10)), worker, concurrency=3)
            return high_water
        assert asyncio.run(main()) == 3

    def test_sequential_when_concurrency_one(self):
        async def main():
            active = 0
            overlapped = False

            async def worker(n):
                nonlocal active, overlapped
                active += 1
                if active > 1:
                    overlapped = True
                await asyncio.sleep(0.005)
                active -= 1
                return n
            out = await bounded_gather([1, 2, 3], worker, concurrency=1)
            return out, overlapped
        out, overlapped = asyncio.run(main())
        assert out == [1, 2, 3] and overlapped is False

    def test_exception_reraised_after_all_workers_finish(self):
        # A raising worker must not orphan in-flight siblings mid-DB-write:
        # everyone finishes, THEN the exception propagates.
        async def main():
            finished = []

            async def worker(n):
                if n == 1:
                    raise RuntimeError("boom")
                await asyncio.sleep(0.02)
                finished.append(n)
                return n
            try:
                await bounded_gather([0, 1, 2, 3], worker, concurrency=4)
            except RuntimeError as e:
                return finished, str(e)
            return finished, None
        finished, err = asyncio.run(main())
        assert err == "boom"
        assert sorted(finished) == [0, 2, 3]  # siblings ran to completion


class TestPipelineConcurrencyEnv:
    def test_default_is_one(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(AD_PIPELINE_CONCURRENCY_ENV, None)
            assert pipeline_concurrency() == 1

    def test_valid_value(self):
        with patch.dict(os.environ, {AD_PIPELINE_CONCURRENCY_ENV: "6"}):
            assert pipeline_concurrency() == 6

    def test_garbage_and_zero_clamp_to_one(self):
        with patch.dict(os.environ, {AD_PIPELINE_CONCURRENCY_ENV: "banana"}):
            assert pipeline_concurrency() == 1
        with patch.dict(os.environ, {AD_PIPELINE_CONCURRENCY_ENV: "0"}):
            assert pipeline_concurrency() == 1
        with patch.dict(os.environ, {AD_PIPELINE_CONCURRENCY_ENV: "-3"}):
            assert pipeline_concurrency() == 1


# ---------------------------------------------------------------------------
# 3. generate_image must not block the event loop
# ---------------------------------------------------------------------------
class TestGenerateImageNonBlocking:
    def test_image_gen_sdk_call_wrapped_in_to_thread(self):
        from viraltracker.services.gemini_service import GeminiService
        src = inspect.getsource(GeminiService.generate_image)
        assert "asyncio.to_thread" in src, "image-gen SDK call must run via to_thread"
        for line in src.splitlines():
            if "self.client.models.generate_content(" in line and "to_thread" not in line:
                raise AssertionError(
                    f"bare sync SDK call in generate_image: {line.strip()!r} — "
                    "blocks the event loop and serializes AD_PIPELINE_MAX_CONCURRENCY"
                )


# ---------------------------------------------------------------------------
# 4. GenerateAdsNode integration
# ---------------------------------------------------------------------------
def _make_ctx(num_hooks=4):
    from viraltracker.pipelines.ad_creation_v2.state import AdCreationPipelineState
    state = AdCreationPipelineState(product_id="prod-1", reference_ad_base64="ref")
    state.selected_hooks = [{"hook_id": f"h{i}", "adapted_text": f"hook {i}"} for i in range(num_hooks)]
    state.canvas_sizes = ["1080x1080"]
    state.color_modes = ["brand"]
    state.selected_images = []
    state.ad_run_id = "11111111-1111-1111-1111-111111111111"
    state.product_dict = {"name": "P", "brand_id": None}
    state.performance_context = None  # skip genome scoring
    state.logo_image_base64 = None
    state.brand_asset_info = {}
    state.ad_analysis = None

    deps = SimpleNamespace(
        ad_creation=SimpleNamespace(
            get_product_id_for_run=AsyncMock(return_value="prod-1"),
            upload_generated_ad=AsyncMock(side_effect=lambda **kw: (f"ads/{kw['prompt_index']}.png", None)),
        ),
        gemini=MagicMock(),
    )
    return SimpleNamespace(state=state, deps=deps)


class TestGenerateAdsNodeConcurrency:
    def _run_node(self, ctx, execute_generation, concurrency: str):
        from viraltracker.pipelines.ad_creation_v2.nodes.generate_ads import GenerateAdsNode

        svc = MagicMock()
        svc.generate_prompt = MagicMock(
            side_effect=lambda **kw: {"full_prompt": "x", "json_prompt": {},
                                      "prompt_version": "v9", "prompt_index": kw["prompt_index"]}
        )
        svc.execute_generation = execute_generation

        with patch.dict(os.environ, {AD_PIPELINE_CONCURRENCY_ENV: concurrency}), \
             patch("viraltracker.pipelines.ad_creation_v2.services.generation_service.AdGenerationService",
                   return_value=svc):
            asyncio.run(GenerateAdsNode().run(ctx))

    def test_ordered_results_failure_isolation_and_cap(self):
        ctx = _make_ctx(num_hooks=4)
        active = {"n": 0, "high": 0}

        async def execute_generation(**kw):
            idx = kw["nano_banana_prompt"]["prompt_index"]
            active["n"] += 1
            active["high"] = max(active["high"], active["n"])
            await asyncio.sleep(0.01)
            active["n"] -= 1
            if idx == 2:
                raise RuntimeError("gen blew up")
            return {"image_base64": "aW1n", "model_used": "m"}

        self._run_node(ctx, execute_generation, concurrency="3")

        ads = ctx.state.generated_ads
        assert [a["prompt_index"] for a in ads] == [1, 2, 3, 4]   # stable order
        assert ads[1]["final_status"] == "generation_failed"      # idx 2 failed
        assert "gen blew up" in ads[1]["error"]
        assert all(a.get("storage_path") for i, a in enumerate(ads) if i != 1)
        assert ctx.state.ads_generated == 3                        # only successes
        assert active["high"] <= 3 and active["high"] >= 2         # actually overlapped, capped

    def test_product_id_fetched_once_not_per_variant(self):
        ctx = _make_ctx(num_hooks=3)

        async def execute_generation(**kw):
            return {"image_base64": "aW1n"}

        self._run_node(ctx, execute_generation, concurrency="2")
        assert ctx.deps.ad_creation.get_product_id_for_run.await_count == 1

    def test_sequential_default_still_works(self):
        ctx = _make_ctx(num_hooks=2)

        async def execute_generation(**kw):
            return {"image_base64": "aW1n"}

        self._run_node(ctx, execute_generation, concurrency="1")
        assert [a["prompt_index"] for a in ctx.state.generated_ads] == [1, 2]
        assert ctx.state.ads_generated == 2


# ---------------------------------------------------------------------------
# 5. DefectScanNode: ordered 3-way partition under scrambled completion order
# ---------------------------------------------------------------------------
class TestDefectScanNodeConcurrency:
    def test_partition_contents_and_order_match_sequential_semantics(self):
        from viraltracker.pipelines.ad_creation_v2.nodes.defect_scan import DefectScanNode
        from viraltracker.pipelines.ad_creation_v2.services.defect_scan_service import (
            Defect, DefectScanResult,
        )

        ctx = _make_ctx()
        # 4 ads: idx1 passes, idx2 was a failed generation, idx3 gets rejected,
        # idx4 passes — with sleeps arranged so completion order is scrambled.
        ctx.state.generated_ads = [
            {"prompt_index": 1, "storage_path": "p1", "hook": {}, "hook_list_index": 0},
            {"prompt_index": 2, "final_status": "generation_failed", "error": "boom"},
            {"prompt_index": 3, "storage_path": "p3", "hook": {}, "hook_list_index": 1},
            {"prompt_index": 4, "storage_path": "p4", "hook": {}, "hook_list_index": 2},
        ]
        ctx.state.content_source = "angles"  # hook_id branch -> None
        ctx.deps.ad_creation.get_image_as_base64 = AsyncMock(return_value="aW1n")
        ctx.deps.ad_creation.save_generated_ad = AsyncMock()

        delays = {1: 0.03, 3: 0.001, 4: 0.015}  # idx3 finishes first, idx1 last

        # Patch DefectScanService used inside the node; the scan identifies the
        # ad via the echoed storage path (get_image_as_base64 returns its input).
        svc = MagicMock()
        call_seq = {"p1": 1, "p3": 3, "p4": 4}

        async def fake_b64(path):
            return path  # echo the storage path so the scan can key off it

        ctx.deps.ad_creation.get_image_as_base64 = AsyncMock(side_effect=fake_b64)

        async def fake_scan(image_base64, product_name):
            idx = call_seq[image_base64]
            await asyncio.sleep(delays[idx])
            if idx == 3:
                return DefectScanResult(passed=False,
                                        defects=[Defect(type="TEXT_GARBLED", description="x")],
                                        model="m", latency_ms=1)
            return DefectScanResult(passed=True, model="m", latency_ms=1)

        async def fake_offer_scan(image_base64, product_name, provided_offer):
            return DefectScanResult(passed=True, model="m", latency_ms=1)

        svc.scan_for_defects = fake_scan
        svc.scan_for_offer_hallucination = fake_offer_scan

        with patch.dict(os.environ, {AD_PIPELINE_CONCURRENCY_ENV: "4"}), \
             patch("viraltracker.pipelines.ad_creation_v2.services.defect_scan_service.DefectScanService",
                   return_value=svc):
            asyncio.run(DefectScanNode().run(ctx))

        # Partition contents + ORIGINAL order, regardless of completion order
        assert [a["prompt_index"] for a in ctx.state.defect_passed_ads] == [1, 4]
        assert [r["prompt_index"] for r in ctx.state.defect_scan_results] == [1, 3, 4]
        # reviewed_ads: gen-failed passthrough (2) before defect-rejected (3), in ad order
        assert [(r["prompt_index"], r["final_status"]) for r in ctx.state.reviewed_ads] == [
            (2, "generation_failed"), (3, "rejected"),
        ]
        ctx.deps.ad_creation.save_generated_ad.assert_awaited_once()  # only the rejected ad


# ---------------------------------------------------------------------------
# 6. ReviewAdsNode: ordered results + count under scrambled completion order
# ---------------------------------------------------------------------------
class TestReviewAdsNodeConcurrency:
    def test_reviewed_order_and_count(self):
        from viraltracker.pipelines.ad_creation_v2.nodes.review_ads import ReviewAdsNode

        ctx = _make_ctx()
        ctx.state.content_source = "angles"
        ctx.state.defect_passed_ads = [
            {"prompt_index": 1, "storage_path": "p1", "hook": {"adapted_text": "h1"},
             "ad_uuid": None, "hook_list_index": 0},
            {"prompt_index": 2, "final_status": "generation_failed", "error": "boom"},
            {"prompt_index": 3, "storage_path": "p3", "hook": {"adapted_text": "h3"},
             "ad_uuid": None, "hook_list_index": 1},
        ]
        ctx.deps.ad_creation.get_image_as_base64 = AsyncMock(return_value="aW1n")
        ctx.deps.ad_creation.save_generated_ad = AsyncMock()

        delays = {1: 0.03, 3: 0.001}

        async def fake_review(image_data, product_name, hook_text, ad_analysis,
                              config=None, exemplar_context=None, current_offer=None):
            idx = 1 if hook_text == "h1" else 3
            await asyncio.sleep(delays[idx])
            return {"final_status": "approved", "review_check_scores": {"idx": idx},
                    "weighted_score": idx * 1.0}

        svc = MagicMock()
        svc.review_ad_staged = fake_review

        async def fake_quality_config():
            return None

        with patch.dict(os.environ, {AD_PIPELINE_CONCURRENCY_ENV: "3"}), \
             patch("viraltracker.pipelines.ad_creation_v2.services.review_service.AdReviewService",
                   return_value=svc), \
             patch("viraltracker.pipelines.ad_creation_v2.services.review_service.load_quality_config",
                   fake_quality_config):
            asyncio.run(ReviewAdsNode().run(ctx))

        out = ctx.state.reviewed_ads
        assert [(r["prompt_index"], r["final_status"]) for r in out] == [
            (1, "approved"), (2, "generation_failed"), (3, "approved"),
        ]
        assert ctx.state.ads_reviewed == 2          # gen-failed not counted
        assert ctx.deps.ad_creation.save_generated_ad.await_count == 2
