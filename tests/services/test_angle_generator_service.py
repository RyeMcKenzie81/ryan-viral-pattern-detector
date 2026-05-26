"""
Tests for AngleGeneratorService.

Exercises every code path: model resolution, prompt template loading + splitting,
prompt rendering (with and without LP), input fetching (happy + missing rows),
LLM response parsing (clean JSON / fenced JSON / malformed / wrong type / count
mismatch / per-angle validation), and save_angles transactional persist (happy
path + partial-failure rollback).

All Anthropic + Supabase access is mocked — pure unit tests, no network.
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from viraltracker.services.angle_generator_service import (
    AngleGeneratorService,
    DEFAULT_N_ANGLES,
    PROMPT_VERSION,
    ProposedAngle,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


PERSONA_ID = uuid4()
OFFER_VARIANT_ID = uuid4()


def make_persona_row(**overrides) -> Dict[str, Any]:
    base = {
        "id": str(PERSONA_ID),
        "name": "Tired Mom",
        "desires": {"care_protection": [{"text": "kids healthy"}]},
        "pain_points": {"emotional": ["constant exhaustion"]},
        "familiar_promises": ["safe and effective"],
        "allergies": {"tonal": ["girlboss energy"]},
    }
    base.update(overrides)
    return base


def make_offer_variant_row(**overrides) -> Dict[str, Any]:
    base = {
        "id": str(OFFER_VARIANT_ID),
        "name": "Sleep Pack",
        "landing_page_url": "https://example.com/sleep",
        "pain_points": ["can't fall asleep"],
        "desires_goals": ["wake up rested"],
        "benefits": ["natural", "no grogginess"],
        "target_audience": "moms 30-50",
    }
    base.update(overrides)
    return base


def make_proposed_angle(name: str = "Thermal Reframe") -> ProposedAngle:
    return ProposedAngle(
        name=name,
        belief_statement="The reason you can't sleep isn't stress, it's body temperature.",
        jtbd_text="When I go to bed exhausted, I want to fall asleep within 10 minutes, so I can feel rested in the morning.",
        pain_points=["lying awake", "morning grogginess"],
        desired_outcome="You fall asleep within 10 minutes like you did in your twenties.",
        emotional_register="relief",
        explanation="Activates the failed_solutions field (melatonin tried, didn't work). LP supports it via the thermal-regulation claim.",
    )


def mock_supabase_for_lookups(persona_row=None, offer_variant_row=None):
    """Build a Supabase mock that returns specific rows for personas_4d / product_offer_variants lookups."""
    client = MagicMock()

    def table_router(table_name):
        table_mock = MagicMock()

        if table_name == "personas_4d":
            data = [persona_row] if persona_row else []
            table_mock.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = data
        elif table_name == "product_offer_variants":
            data = [offer_variant_row] if offer_variant_row else []
            table_mock.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = data
        # For save_angles, both insert + update + delete chains need to be no-ops
        table_mock.insert.return_value.execute.return_value = MagicMock(data=[{}])
        table_mock.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[{}])
        table_mock.delete.return_value.eq.return_value.execute.return_value = MagicMock(data=[{}])

        return table_mock

    client.table.side_effect = table_router
    return client


def mock_anthropic_with_response(text: str):
    """Build an Anthropic mock whose messages.create() returns the given text."""
    client = MagicMock()
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    client.messages.create.return_value = msg
    return client


# ---------------------------------------------------------------------------
# Model resolution (decision M1)
# ---------------------------------------------------------------------------


def test_get_model_reads_from_config():
    from viraltracker.core.config import Config
    assert AngleGeneratorService.get_model() == Config.CREATIVE_MODEL


def test_get_model_returns_opus_4_7():
    """Sanity check — at time of writing this should be claude-opus-4-7 per decision M1."""
    assert AngleGeneratorService.get_model() == "claude-opus-4-7"


# ---------------------------------------------------------------------------
# Prompt template loading + splitting
# ---------------------------------------------------------------------------


def test_prompt_template_loads_from_disk():
    svc = AngleGeneratorService()
    template = svc.prompt_template
    assert "# SYSTEM PROMPT" in template
    assert "# USER PROMPT" in template
    assert "{n_angles}" in template
    assert "{persona_json}" in template


def test_prompt_template_is_cached_after_first_read():
    svc = AngleGeneratorService()
    t1 = svc.prompt_template
    t2 = svc.prompt_template
    assert t1 is t2  # Same object reference — cached


def test_split_system_user_extracts_both_sections():
    svc = AngleGeneratorService()
    rendered = "<!-- comment -->\n# SYSTEM PROMPT\nyou are a strategist\n# USER PROMPT\ngenerate 5"
    system, user = svc._split_system_user(rendered)
    assert system == "you are a strategist"
    assert user == "generate 5"


def test_split_system_user_raises_when_user_section_missing():
    svc = AngleGeneratorService()
    with pytest.raises(ValueError, match="USER PROMPT"):
        svc._split_system_user("# SYSTEM PROMPT\nonly system here")


# ---------------------------------------------------------------------------
# Prompt rendering
# ---------------------------------------------------------------------------


def test_render_prompt_substitutes_all_slots():
    svc = AngleGeneratorService()
    persona = {"name": "test persona"}
    offer = {"name": "test offer"}
    system, user = svc._render_prompt(
        n_angles=5,
        persona=persona,
        offer_variant=offer,
        landing_page_summary="LP says X",
        brand_voice="brand voice block",
    )
    assert "5" in user
    assert '"test persona"' in user
    assert '"test offer"' in user
    assert "LP says X" in user
    assert "brand voice block" in user


def test_render_prompt_uses_placeholder_when_lp_missing():
    svc = AngleGeneratorService()
    _, user = svc._render_prompt(
        n_angles=3,
        persona={"x": 1},
        offer_variant={"y": 2},
        landing_page_summary=None,
    )
    assert svc.NO_LP_PLACEHOLDER in user


# ---------------------------------------------------------------------------
# Input fetching
# ---------------------------------------------------------------------------


def test_fetch_persona_returns_row():
    persona = make_persona_row()
    svc = AngleGeneratorService(supabase_client=mock_supabase_for_lookups(persona_row=persona))
    assert svc._fetch_persona(PERSONA_ID) == persona


def test_fetch_persona_raises_when_missing():
    svc = AngleGeneratorService(supabase_client=mock_supabase_for_lookups(persona_row=None))
    with pytest.raises(ValueError, match="Persona not found"):
        svc._fetch_persona(PERSONA_ID)


def test_fetch_offer_variant_returns_row():
    ov = make_offer_variant_row()
    svc = AngleGeneratorService(supabase_client=mock_supabase_for_lookups(offer_variant_row=ov))
    assert svc._fetch_offer_variant(OFFER_VARIANT_ID) == ov


def test_fetch_offer_variant_raises_when_missing():
    svc = AngleGeneratorService(supabase_client=mock_supabase_for_lookups(offer_variant_row=None))
    with pytest.raises(ValueError, match="Offer variant not found"):
        svc._fetch_offer_variant(OFFER_VARIANT_ID)


# ---------------------------------------------------------------------------
# LLM response parsing
# ---------------------------------------------------------------------------


def _angle_json(name: str = "A") -> Dict[str, Any]:
    return {
        "name": name,
        "belief_statement": "stmt",
        "jtbd_text": "When I X, I want to Y, so I can Z.",
        "pain_points": ["p1"],
        "desired_outcome": "feel rested",
        "emotional_register": "relief",
        "explanation": "explanation here",
    }


def test_parse_clean_json_array():
    svc = AngleGeneratorService()
    raw = '[' + ', '.join([str(_angle_json(f"a{i}")).replace("'", '"') for i in range(5)]) + ']'
    angles = svc._parse_llm_response(raw, expected_n=5)
    assert len(angles) == 5
    assert all(isinstance(a, ProposedAngle) for a in angles)


def test_parse_strips_markdown_code_fence():
    svc = AngleGeneratorService()
    raw = "```json\n" + str([_angle_json("A")]).replace("'", '"') + "\n```"
    angles = svc._parse_llm_response(raw, expected_n=1)
    assert len(angles) == 1
    assert angles[0].name == "A"


def test_parse_strips_bare_code_fence():
    svc = AngleGeneratorService()
    raw = "```\n" + str([_angle_json("B")]).replace("'", '"') + "\n```"
    angles = svc._parse_llm_response(raw, expected_n=1)
    assert angles[0].name == "B"


def test_parse_raises_on_malformed_json():
    svc = AngleGeneratorService()
    with pytest.raises(ValueError, match="non-JSON"):
        svc._parse_llm_response("not json at all", expected_n=1)


def test_parse_raises_when_response_is_object_not_array():
    svc = AngleGeneratorService()
    with pytest.raises(ValueError, match="expected JSON array"):
        svc._parse_llm_response('{"oops": "object"}', expected_n=1)


def test_parse_warns_on_count_mismatch_but_returns_what_came_back(caplog):
    svc = AngleGeneratorService()
    raw = str([_angle_json("only_one")]).replace("'", '"')
    angles = svc._parse_llm_response(raw, expected_n=5)
    assert len(angles) == 1


def test_parse_raises_on_per_angle_validation_failure():
    svc = AngleGeneratorService()
    bad = _angle_json("A")
    del bad["belief_statement"]   # required field missing
    raw = str([bad]).replace("'", '"')
    with pytest.raises(ValueError, match="failed validation"):
        svc._parse_llm_response(raw, expected_n=1)


# ---------------------------------------------------------------------------
# generate_angles (integration of fetch + LLM + parse)
# ---------------------------------------------------------------------------


def test_generate_angles_happy_path():
    raw = str([_angle_json(f"a{i}") for i in range(5)]).replace("'", '"')
    svc = AngleGeneratorService(
        anthropic_client=mock_anthropic_with_response(raw),
        supabase_client=mock_supabase_for_lookups(
            persona_row=make_persona_row(),
            offer_variant_row=make_offer_variant_row(),
        ),
    )
    angles = svc.generate_angles(
        persona_id=PERSONA_ID,
        offer_variant_id=OFFER_VARIANT_ID,
        landing_page_summary="LP analysis text",
        n=5,
    )
    assert len(angles) == 5


def test_generate_angles_works_without_landing_page():
    raw = str([_angle_json("a1")]).replace("'", '"')
    anthropic_client = mock_anthropic_with_response(raw)
    svc = AngleGeneratorService(
        anthropic_client=anthropic_client,
        supabase_client=mock_supabase_for_lookups(
            persona_row=make_persona_row(),
            offer_variant_row=make_offer_variant_row(),
        ),
    )
    angles = svc.generate_angles(persona_id=PERSONA_ID, offer_variant_id=OFFER_VARIANT_ID, n=1)
    assert len(angles) == 1
    # Confirm the NO LP placeholder ended up in the user prompt
    call_args = anthropic_client.messages.create.call_args
    user_msg = call_args.kwargs["messages"][0]["content"]
    assert svc.NO_LP_PLACEHOLDER in user_msg


def test_generate_angles_rejects_n_below_1():
    svc = AngleGeneratorService(
        anthropic_client=MagicMock(),
        supabase_client=MagicMock(),
    )
    with pytest.raises(ValueError, match="n must be >= 1"):
        svc.generate_angles(persona_id=PERSONA_ID, offer_variant_id=OFFER_VARIANT_ID, n=0)


def test_generate_angles_rejects_n_above_20():
    svc = AngleGeneratorService(
        anthropic_client=MagicMock(),
        supabase_client=MagicMock(),
    )
    with pytest.raises(ValueError, match="n must be <= 20"):
        svc.generate_angles(persona_id=PERSONA_ID, offer_variant_id=OFFER_VARIANT_ID, n=21)


def test_generate_angles_calls_correct_model():
    raw = str([_angle_json("a")]).replace("'", '"')
    anthropic_client = mock_anthropic_with_response(raw)
    svc = AngleGeneratorService(
        anthropic_client=anthropic_client,
        supabase_client=mock_supabase_for_lookups(
            persona_row=make_persona_row(),
            offer_variant_row=make_offer_variant_row(),
        ),
    )
    svc.generate_angles(persona_id=PERSONA_ID, offer_variant_id=OFFER_VARIANT_ID, n=1)
    call_args = anthropic_client.messages.create.call_args
    assert call_args.kwargs["model"] == "claude-opus-4-7"


# ---------------------------------------------------------------------------
# save_angles (transactional persist)
# ---------------------------------------------------------------------------


def test_save_angles_inserts_run_then_angles_then_updates_array():
    sb = mock_supabase_for_lookups()
    svc = AngleGeneratorService(supabase_client=sb)
    angles = [make_proposed_angle(f"a{i}") for i in range(3)]

    result = svc.save_angles(
        proposed_angles=angles,
        persona_id=PERSONA_ID,
        offer_variant_id=OFFER_VARIANT_ID,
        landing_page_url="https://example.com",
    )

    assert "angle_generation_run_id" in result
    assert len(result["angle_ids"]) == 3
    # Verify all 3 belief_angles + 1 run insert + 1 run update happened
    table_calls = [call.args[0] for call in sb.table.call_args_list]
    # Each call to sb.table() returns the same router output; count by table name
    assert table_calls.count("angle_generation_runs") >= 2  # 1 insert + 1 update
    assert table_calls.count("belief_angles") == 3


def test_save_angles_records_correct_provenance():
    sb = mock_supabase_for_lookups()
    inserted_rows = []
    original_table = sb.table
    def capturing_table(name):
        t = original_table(name)
        if name == "belief_angles":
            orig_insert = t.insert
            def capture(row):
                inserted_rows.append(row)
                return orig_insert(row)
            t.insert = capture
        return t
    sb.table = capturing_table

    svc = AngleGeneratorService(supabase_client=sb)
    user_id = uuid4()
    svc.save_angles(
        proposed_angles=[make_proposed_angle()],
        persona_id=PERSONA_ID,
        offer_variant_id=OFFER_VARIANT_ID,
        landing_page_url="https://lp.example.com",
        created_by_user_id=user_id,
    )

    assert len(inserted_rows) == 1
    row = inserted_rows[0]
    assert row["source_persona_id"] == str(PERSONA_ID)
    assert row["source_offer_variant_id"] == str(OFFER_VARIANT_ID)
    assert row["source_landing_page_url"] == "https://lp.example.com"
    assert row["generation_method"] == PROMPT_VERSION
    assert row["jtbd_framed_id"] is None  # decision OV-1 — nullable for AI-generated
    assert row["jtbd_text"] is not None
    assert row["status"] == "untested"


def test_save_angles_rejects_empty_list():
    svc = AngleGeneratorService(supabase_client=MagicMock())
    with pytest.raises(ValueError, match="at least one ProposedAngle"):
        svc.save_angles(
            proposed_angles=[],
            persona_id=PERSONA_ID,
            offer_variant_id=OFFER_VARIANT_ID,
        )


def test_save_angles_rolls_back_on_partial_failure():
    """If belief_angles insert fails midway, both the run row and any inserted angles should be cleaned up."""
    sb = MagicMock()
    deleted_belief_angle_ids: List[str] = []
    deleted_run_ids: List[str] = []

    insert_call_count = [0]

    def table_router(name):
        t = MagicMock()
        if name == "angle_generation_runs":
            t.insert.return_value.execute.return_value = MagicMock(data=[{}])
            t.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[{}])
            # delete tracker
            def delete_fn():
                d = MagicMock()
                def eq_fn(col, val):
                    deleted_run_ids.append(val)
                    e = MagicMock()
                    e.execute.return_value = MagicMock(data=[{}])
                    return e
                d.eq.side_effect = eq_fn
                return d
            t.delete.side_effect = delete_fn
        elif name == "belief_angles":
            def insert_fn(row):
                insert_call_count[0] += 1
                if insert_call_count[0] == 2:
                    raise RuntimeError("simulated DB constraint violation")
                ins = MagicMock()
                ins.execute.return_value = MagicMock(data=[{}])
                return ins
            t.insert.side_effect = insert_fn
            def delete_fn():
                d = MagicMock()
                def eq_fn(col, val):
                    deleted_belief_angle_ids.append(val)
                    e = MagicMock()
                    e.execute.return_value = MagicMock(data=[{}])
                    return e
                d.eq.side_effect = eq_fn
                return d
            t.delete.side_effect = delete_fn
        return t

    sb.table.side_effect = table_router

    svc = AngleGeneratorService(supabase_client=sb)
    angles = [make_proposed_angle(f"a{i}") for i in range(3)]

    with pytest.raises(RuntimeError, match="simulated DB constraint violation"):
        svc.save_angles(
            proposed_angles=angles,
            persona_id=PERSONA_ID,
            offer_variant_id=OFFER_VARIANT_ID,
        )

    # First angle inserted successfully should be cleaned up; the run row too
    assert len(deleted_belief_angle_ids) == 1
    assert len(deleted_run_ids) == 1


def test_save_angles_defaults_n_angles_requested_to_list_length():
    """When n_angles_requested isn't passed, it defaults to len(proposed_angles)."""
    inserted_run_rows: List[Dict[str, Any]] = []
    sb = MagicMock()
    def table_router(name):
        t = MagicMock()
        if name == "angle_generation_runs":
            def capture_insert(row):
                inserted_run_rows.append(row)
                ins = MagicMock()
                ins.execute.return_value = MagicMock(data=[{}])
                return ins
            t.insert.side_effect = capture_insert
            t.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[{}])
        elif name == "belief_angles":
            t.insert.return_value.execute.return_value = MagicMock(data=[{}])
        return t
    sb.table.side_effect = table_router

    svc = AngleGeneratorService(supabase_client=sb)
    svc.save_angles(
        proposed_angles=[make_proposed_angle(f"a{i}") for i in range(4)],
        persona_id=PERSONA_ID,
        offer_variant_id=OFFER_VARIANT_ID,
    )
    assert inserted_run_rows[0]["n_angles_requested"] == 4
