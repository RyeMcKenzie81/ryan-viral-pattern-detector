"""Review model pin + recalibration (2026-06-12 gemini-pro-latest drift incident).

Google retired gemini-3-pro-preview and repointed the floating
"gemini-pro-latest" alias to 3.1, which grades the ad-review rubric ~2.3
points harsher on a compressed scale. Every ad fell below pass_threshold=7.0
into the borderline band, where Stage 3 had been a silent no-op since PR #208
(analyze_image kwarg TypeError swallowed as non-fatal) — so 100% of ads stuck
at 'flagged' and Ad History exports matched nothing.

These tests pin the contract so neither failure mode can silently return:
1. The review model must be an explicit version, never a floating alias.
2. analyze_image must bind the kwargs its real call sites use.
3. Quality thresholds stay paired with the calibrated model.
4. No code references the retired model ids.

Run with: pytest tests/test_review_model_pin.py -v
"""
from __future__ import annotations

import inspect
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


class TestModelPin:
    def test_vision_model_is_pinned_not_floating(self):
        from viraltracker.core.config import Config
        assert "-latest" not in Config.VISION_MODEL, (
            "VISION_MODEL must be pinned to an explicit version. Floating "
            "aliases repoint when Google ships a new model, silently "
            "recalibrating every review score (2026-06-12 incident)."
        )
        assert "gemini-3-pro-preview" not in Config.VISION_MODEL.replace("3.1", ""), \
            "gemini-3-pro-preview was retired by Google on 2026-06-12"

    def test_stage3_and_thresholds_share_one_pinned_model(self):
        # Stage-3 scores flow through the calibrated gate via OR-logic, so it
        # must run on the SAME pinned model as Stage 2 — a floating-alias
        # Stage 3 silently becomes the binding reviewer (measured 2026-06-12:
        # flash-latest out-scored the calibrated pro in 24/25 reviews).
        from viraltracker.pipelines.ad_creation_v2.services import review_service
        src = inspect.getsource(review_service.AdReviewService._run_rubric_review_gemini)
        assert 'Config.get_model("vision")' in src, \
            "Stage 3 must use the pinned vision model, not GeminiService()'s default alias"
        assert "GeminiService()" not in src

    def test_pinned_model_has_cost_entry(self):
        # The retired ids were priced; the new pin must be too, or every review
        # records $0 and usage limits under-enforce.
        from viraltracker.core.config import Config
        bare = Config.VISION_MODEL.split("models/")[-1]
        assert Config.get_token_cost(bare) != (0.0, 0.0)

    def test_no_retired_model_ids_in_code(self):
        # The retired ids 404 on every call. grep the package, allowing only
        # comment/doc mentions (lines explaining the retirement).
        proc = subprocess.run(
            ["grep", "-rn", "-E", "gemini-3-pro(-preview)?['\\\"]", "viraltracker/", "--include=*.py"],
            capture_output=True, text=True, cwd=REPO,
        )
        # 0 = matches, 1 = clean; anything else means grep itself failed and
        # the check would pass vacuously.
        assert proc.returncode in (0, 1), f"grep failed: {proc.stderr}"
        out = proc.stdout
        offenders = [
            line for line in out.splitlines()
            if "gemini-3-pro-image-preview" not in line   # image-gen model, still live
            and "3.1" not in line                          # the replacement pin
            and "retired" not in line.lower()              # explanatory comments
            and "404" not in line                          # explanatory comments
            and ": (" not in line                          # pricing-table entries, not API calls
        ]
        assert not offenders, f"retired Gemini model still referenced:\n" + "\n".join(offenders)


class TestAnalyzeImageContract:
    def test_signature_binds_all_real_call_site_kwargs(self):
        # These exact kwarg shapes exist in defect_scan_service (x2),
        # review_service Stage 3, and visual_descriptor_service. The old
        # signature raised TypeError on the first three, which broad excepts
        # converted to passed=True — defect scanning silently off since #208.
        from viraltracker.services.gemini_service import GeminiService
        sig = inspect.signature(GeminiService.analyze_image)
        call_shapes = [
            dict(image_base64="x", prompt="p", media_type="image/png", model="m"),
            dict(image_base64="x", prompt="p"),
            dict(image_data="x", prompt="p"),
        ]
        for kwargs in call_shapes:
            sig.bind(object(), **kwargs)  # raises TypeError if incompatible

    def test_image_required(self):
        import asyncio
        from viraltracker.services.gemini_service import GeminiService
        svc = GeminiService.__new__(GeminiService)  # skip __init__ (no API key needed)
        try:
            asyncio.run(GeminiService.analyze_image(svc, prompt="p"))
            raise AssertionError("expected ValueError without image data")
        except ValueError:
            pass

    def test_no_bare_sync_sdk_call_in_analyze_image(self):
        from viraltracker.services.gemini_service import GeminiService
        src = inspect.getsource(GeminiService.analyze_image)
        for line in src.splitlines():
            if "self.client.models.generate_content(" in line and "to_thread" not in line:
                raise AssertionError(
                    f"bare sync SDK call in analyze_image: {line.strip()!r} — "
                    "blocks the event loop under AD_PIPELINE_MAX_CONCURRENCY"
                )


class TestCalibratedThresholds:
    def test_thresholds_match_3_1_calibration(self):
        # Calibration set (12 May ads, known outcomes, re-reviewed under 3.1):
        # old-approved scored 5.40-6.22, old-rejected 4.54-4.99. The gate
        # below reproduces the old approve/reject boundary on the new scale.
        # If you change the model, re-run the calibration BEFORE editing this.
        from viraltracker.pipelines.ad_creation_v2.services.review_service import (
            DEFAULT_QUALITY_CONFIG,
        )
        assert DEFAULT_QUALITY_CONFIG["pass_threshold"] == 5.5
        assert DEFAULT_QUALITY_CONFIG["borderline_range"] == {"low": 4.9, "high": 5.5}

    def test_staged_logic_maps_calibration_points_correctly(self):
        from viraltracker.pipelines.ad_creation_v2.services.review_service import (
            DEFAULT_QUALITY_CONFIG, apply_staged_review_logic,
        )
        t = DEFAULT_QUALITY_CONFIG["pass_threshold"]
        b = DEFAULT_QUALITY_CONFIG["borderline_range"]
        # Representative calibration points (new-scale scores):
        assert apply_staged_review_logic(6.22, t, b) == "approved"   # old 7.56 approved
        assert apply_staged_review_logic(5.76, t, b) == "approved"   # old 7.34 approved
        assert apply_staged_review_logic(4.54, t, b) == "rejected"   # old 3.50 rejected
        # The messy middle stays flagged for the (now working) Stage-3 tie-break
        assert apply_staged_review_logic(5.25, t, b) == "flagged"


class TestStage3Alive:
    def test_borderline_path_calls_gemini_without_typeerror(self):
        # End-to-end through review_ad_staged with Stage 2 forced borderline:
        # Stage 3 must produce scores, not an error dict (the #208 regression).
        import asyncio
        from unittest.mock import AsyncMock, patch
        from viraltracker.pipelines.ad_creation_v2.services.review_service import (
            AdReviewService,
        )
        svc = AdReviewService()
        borderline = {k: 5.2 for k in
                      ["V1","V2","V3","V4","V5","V6","V7","V8","V9","C1","C2","C3","C4","C5","G1","G2"]}
        stage3 = {k: 5.8 for k in borderline}

        with patch.object(svc, "_run_rubric_review_claude", AsyncMock(return_value=borderline)), \
             patch.object(svc, "_run_rubric_review_gemini", AsyncMock(return_value=stage3)) as g:
            res = asyncio.run(svc.review_ad_staged(
                image_data=b"img", product_name="P", hook_text="h", ad_analysis={},
            ))
        g.assert_awaited_once()
        assert res["stage3_result"] is not None and "error" not in res["stage3_result"]
        assert res["final_status"] == "approved"   # Stage-3 5.8 rescues borderline 5.2
