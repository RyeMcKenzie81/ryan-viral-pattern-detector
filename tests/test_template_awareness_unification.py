"""Template-classifier unification onto the shared AWARENESS_RUBRIC (task #47).

Locks the one-definition guarantees:
- the enum<->INT ordinal mapping is lossless and matches the canonical order;
- the template prompt carries the SHARED rubric verbatim (no fork) and .format()s
  cleanly (brace mechanics);
- the rubric is HASH-PINNED to the template prompt version: editing the rubric
  without bumping TEMPLATE_ANALYSIS_PROMPT_VERSION (and re-pinning) fails here,
  which is what forces template re-classification and prevents silent drift;
- parse-time mapping: suggestions always carry an INT awareness (or NO key),
  never a string/None/fake default, because the approval UI (`index = value - 1`)
  and the machine-paced bulk auto-approval consume them directly;
- bulk approval SKIPS awareness-less items (no NULL writes, no fabricated grade);
- the scorer's distance math semantics are locked (the INT consumers stay valid).

Run with: pytest tests/test_template_awareness_unification.py -v
"""
from __future__ import annotations

import hashlib
from unittest.mock import MagicMock, patch

from viraltracker.services.awareness_rubric import (
    AWARENESS_RUBRIC,
    AWARENESS_LEVELS_ORDERED,
    AWARENESS_LEVEL_ORDER,
    AWARENESS_INT_TO_LEVEL,
    AWARENESS_LEVEL_LABELS,
    STATIC_AWARENESS_TELLS,
    VALID_AWARENESS_LEVELS,
    normalize_awareness_level,
)
from viraltracker.services.template_queue_service import (
    TemplateQueueService,
    TEMPLATE_ANALYSIS_PROMPT,
    TEMPLATE_ANALYSIS_PROMPT_VERSION,
    TEMPLATE_AWARENESS_MODEL,
    RUBRIC_HASH_PINS,
)


# ---------------------------------------------------------------------------
# Mapping lock: lossless, exhaustive, both directions, canonical order.
# ---------------------------------------------------------------------------
class TestMappingLock:
    def test_order_is_canonical_schwartz(self):
        assert AWARENESS_LEVELS_ORDERED == (
            "unaware", "problem_aware", "solution_aware", "product_aware", "most_aware",
        )

    def test_enum_int_roundtrip_exhaustive(self):
        assert AWARENESS_LEVEL_ORDER == {
            "unaware": 1, "problem_aware": 2, "solution_aware": 3,
            "product_aware": 4, "most_aware": 5,
        }
        for lvl, i in AWARENESS_LEVEL_ORDER.items():
            assert AWARENESS_INT_TO_LEVEL[i] == lvl
        assert set(AWARENESS_LEVEL_ORDER) == set(VALID_AWARENESS_LEVELS)

    def test_labels_derive_from_order(self):
        assert AWARENESS_LEVEL_LABELS == {
            1: "Unaware", 2: "Problem Aware", 3: "Solution Aware",
            4: "Product Aware", 5: "Most Aware",
        }

    def test_image_service_reexports_are_the_same_objects(self):
        # Back-compat re-export: image_analysis_service consumers keep working AND
        # share the exact same vocabulary objects (no second copy).
        from viraltracker.services import image_analysis_service as ias
        assert ias.VALID_AWARENESS_LEVELS is VALID_AWARENESS_LEVELS
        assert ias._normalize_awareness_level is normalize_awareness_level


# ---------------------------------------------------------------------------
# No-drift tripwire: rubric hash pinned to the template prompt version.
# ---------------------------------------------------------------------------
class TestRubricTripwire:
    def test_awareness_definition_hash_matches_pin_for_current_version(self):
        # The pin covers BOTH shared awareness constants: the core rubric AND the
        # static tells layer (bottle-as-hero etc.) — editing either must force a bump.
        live = hashlib.sha256((AWARENESS_RUBRIC + STATIC_AWARENESS_TELLS).encode()).hexdigest()
        pinned = RUBRIC_HASH_PINS.get(TEMPLATE_ANALYSIS_PROMPT_VERSION)
        assert pinned == live, (
            "AWARENESS_RUBRIC or STATIC_AWARENESS_TELLS changed but "
            "TEMPLATE_ANALYSIS_PROMPT_VERSION was not bumped/re-pinned. Bump the "
            "version in template_queue_service.py, add the new hash to "
            "RUBRIC_HASH_PINS, and plan a template re-classification "
            "(stale set: WHERE awareness_prompt_version IS DISTINCT FROM the new "
            "version). This coupling is what keeps ads and templates on ONE "
            "awareness definition — do not bypass it. (Hashing is byte-stable on "
            "purpose: even whitespace edits force a bump.)"
        )

    def test_ads_image_prompt_pinned_to_its_version(self):
        # STATIC_AWARENESS_TELLS is shared with the ads image prompt; any change to
        # the rendered ads prompt MUST ride an image PROMPT_VERSION bump (staling +
        # re-classifying image ads), never ship silently. Pin history:
        #   v2: dc625b6c... (pre-extraction original)
        #   v3: e12ba69f... (hand-review tells corrections 2026-06-10: before/after
        #       no-product -> solution_aware; multi-panel reading-order lead;
        #       risk-reversal lead -> product_aware)
        from viraltracker.services.image_analysis_service import (
            IMAGE_ANALYSIS_PROMPT, PROMPT_VERSION,
        )
        assert STATIC_AWARENESS_TELLS in IMAGE_ANALYSIS_PROMPT
        assert PROMPT_VERSION == "v3"
        assert hashlib.sha256(IMAGE_ANALYSIS_PROMPT.encode()).hexdigest() == (
            "ff526c265d021e0d83c3d10f32f1d3e9845ba2c48d3ce94a4ee64d73bbe8e9a1"
        ), (
            "IMAGE_ANALYSIS_PROMPT changed without an image PROMPT_VERSION bump. "
            "If this change is intentional, bump image_analysis_service."
            "PROMPT_VERSION (staling + re-classifying all image ads) and update "
            "this pin + the pin history above."
        )

    def test_every_pin_version_is_unique_hash(self):
        hashes = list(RUBRIC_HASH_PINS.values())
        assert len(hashes) == len(set(hashes)), "duplicate pins suggest a no-op bump"


# ---------------------------------------------------------------------------
# Prompt: shared rubric verbatim, brace-safe render, enum output contract.
# ---------------------------------------------------------------------------
class TestPromptContract:
    def test_prompt_formats_and_contains_rubric_verbatim(self):
        rendered = TEMPLATE_ANALYSIS_PROMPT.format(
            page_name="Brand", link_url="https://x", awareness_rubric=AWARENESS_RUBRIC,
        )
        assert AWARENESS_RUBRIC in rendered          # no fork, no paraphrase
        assert STATIC_AWARENESS_TELLS in rendered    # the shared static-tells layer too
        assert "Choose ONE: unaware | problem_aware | solution_aware | product_aware | most_aware" in rendered
        assert "<integer 1-5>" not in rendered        # the old bare scale is gone

    def test_model_is_the_calibrated_judge(self):
        assert TEMPLATE_AWARENESS_MODEL == "gemini-pro-latest"


# ---------------------------------------------------------------------------
# Parse-time mapping in analyze_template_for_approval.
# ---------------------------------------------------------------------------
def _service_with_image():
    svc = TemplateQueueService.__new__(TemplateQueueService)
    svc.supabase = MagicMock()
    # queue item lookup -> storage path; storage download -> bytes
    svc.supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{
            "id": "q1", "asset_id": "a1",
            "scraped_ad_assets": {"storage_path": "bucket/p.jpg", "asset_type": "image"},
            "facebook_ads": {"page_name": "Brand", "link_url": "https://x"},
        }]
    )
    svc.supabase.storage.from_.return_value.download.return_value = b"imagebytes"
    return svc


def _run_analyze(gemini_text):
    import asyncio
    svc = _service_with_image()
    fake_gemini = MagicMock()
    async def fake_analyze_image(b64, prompt):
        return gemini_text
    fake_gemini.analyze_image = fake_analyze_image
    return asyncio.run(svc.analyze_template_for_approval("q1", gemini=fake_gemini))


class TestParseTimeMapping:
    def test_enum_string_maps_to_int_with_enum_kept(self):
        out = _run_analyze('{"suggested_name":"N","awareness_level":"product_aware","awareness_level_reasoning":"r"}')
        assert out["awareness_level"] == 4                      # INT for UI/bulk/scorer
        assert out["awareness_level_enum"] == "product_aware"   # transparency
        assert out["awareness_prompt_version"] == TEMPLATE_ANALYSIS_PROMPT_VERSION

    def test_casing_variant_recovers(self):
        out = _run_analyze('{"awareness_level":"Problem Aware"}')
        assert out["awareness_level"] == 2

    def test_garbage_means_no_awareness_key(self):
        out = _run_analyze('{"awareness_level":"super_aware"}')
        assert "awareness_level" not in out      # never guess, never fake-default

    def test_legacy_integer_output_is_rejected(self):
        # v2 suggestions must come from the rubric's vocabulary; a stray int from a
        # stale/echoed prompt is NOT trusted as a rubric grade.
        out = _run_analyze('{"awareness_level": 4}')
        assert "awareness_level" not in out

    def test_unparseable_json_has_no_awareness_default(self):
        out = _run_analyze("not json at all")
        assert "awareness_level" not in out      # the old hardcoded-3 fallback is dead
        assert out["awareness_prompt_version"] == TEMPLATE_ANALYSIS_PROMPT_VERSION


# ---------------------------------------------------------------------------
# Bulk auto-approval skips awareness-less items (machine-paced safety).
# ---------------------------------------------------------------------------
class TestBulkSkipsUngraded:
    def test_items_without_usable_awareness_are_skipped(self):
        svc = TemplateQueueService.__new__(TemplateQueueService)
        svc.supabase = MagicMock()
        finalized = []
        svc.finalize_approval = MagicMock(side_effect=lambda **kw: (finalized.append(kw) or {"id": "t1"}))
        items = [
            {"queue_id": "00000000-0000-0000-0000-000000000001",
             "suggestions": {"suggested_name": "ok", "awareness_level": 3}},
            {"queue_id": "00000000-0000-0000-0000-000000000002",
             "suggestions": {"suggested_name": "no-grade"}},                 # absent
            {"queue_id": "00000000-0000-0000-0000-000000000003",
             "suggestions": {"suggested_name": "none", "awareness_level": None}},   # null
            {"queue_id": "00000000-0000-0000-0000-000000000004",
             "suggestions": {"suggested_name": "str", "awareness_level": "product_aware"}},  # leak
        ]
        result = svc.finalize_bulk_approval(items=items, reviewed_by="test")
        assert result["approved"] == 1
        assert len(finalized) == 1 and finalized[0]["awareness_level"] == 3


# ---------------------------------------------------------------------------
# Scorer semantics lock: the INT consumers stay valid after unification.
# ---------------------------------------------------------------------------
class TestScorerRegression:
    def test_awareness_align_distance_math(self):
        from uuid import uuid4
        from viraltracker.services.template_scoring_service import (
            AwarenessAlignScorer, SelectionContext,
        )
        scorer = AwarenessAlignScorer()
        ctx = SelectionContext(product_id=uuid4(), brand_id=uuid4(), awareness_stage=3)
        assert scorer.score({"awareness_level": 3}, ctx) == 1.0     # perfect match
        assert scorer.score({"awareness_level": 1}, ctx) == 0.5     # |1-3|/4 -> 0.5
        assert scorer.score({"awareness_level": None}, ctx) == 0.5  # neutral on missing
