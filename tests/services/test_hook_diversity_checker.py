"""
Tests for HookDiversityChecker.

Exercises every code path in the module: threshold lookup (cached + system_settings
override + fallback), embedding (single + batched), check (empty-batch + accept +
reject + pre-computed-embedding shortcut), and the full generate_with_diversity
retry loop (first-attempt success + retry success + all-rejected best-of-N
fallback + raise on generate_fn failure).

All OpenAI + Supabase access is mocked — pure unit tests, no network.
"""

from __future__ import annotations

from typing import List
from unittest.mock import MagicMock

import numpy as np
import pytest

from viraltracker.services.hook_diversity_checker import (
    HookDiversityChecker,
    INTRA_ANGLE_THRESHOLD_DEFAULT,
    SYSTEM_SETTINGS_KEY,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_embedding(seed: int, dim: int = 1536) -> List[float]:
    """Deterministic pseudo-embedding for tests."""
    rng = np.random.default_rng(seed)
    vec = rng.normal(size=dim).astype(np.float32)
    return vec.tolist()


def mock_openai_with_embeddings(embeddings: List[List[float]]):
    """
    Build a mocked OpenAI client whose embeddings.create() returns the supplied
    embeddings in order across all calls (queue-style).
    """
    client = MagicMock()
    queue = list(embeddings)

    def fake_create(model, input, **kwargs):
        # `input` can be str or list[str]; figure out how many we need to consume
        if isinstance(input, str):
            n = 1
        else:
            n = len(input)
        taken = [queue.pop(0) for _ in range(n)]
        response = MagicMock()
        response.data = [MagicMock(embedding=e) for e in taken]
        return response

    client.embeddings.create.side_effect = fake_create
    return client


def mock_supabase_with_threshold(threshold_value):
    """Build a mocked Supabase client whose system_settings lookup returns threshold_value."""
    client = MagicMock()
    if threshold_value is None:
        client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
    else:
        client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {"value": str(threshold_value)}
        ]
    return client


# ---------------------------------------------------------------------------
# get_threshold
# ---------------------------------------------------------------------------


def test_threshold_falls_back_to_default_when_unset():
    checker = HookDiversityChecker(supabase_client=mock_supabase_with_threshold(None))
    assert checker.get_threshold() == INTRA_ANGLE_THRESHOLD_DEFAULT


def test_threshold_uses_system_settings_value_when_present():
    checker = HookDiversityChecker(supabase_client=mock_supabase_with_threshold(0.72))
    assert checker.get_threshold() == 0.72


def test_threshold_is_cached_after_first_read():
    sb = mock_supabase_with_threshold(0.90)
    checker = HookDiversityChecker(supabase_client=sb)
    checker.get_threshold()
    checker.get_threshold()
    checker.get_threshold()
    # Only one Supabase round-trip despite three calls
    assert sb.table.call_count == 1


def test_threshold_cache_can_be_reset():
    sb = mock_supabase_with_threshold(0.90)
    checker = HookDiversityChecker(supabase_client=sb)
    checker.get_threshold()
    checker.reset_threshold_cache()
    checker.get_threshold()
    assert sb.table.call_count == 2


def test_threshold_falls_back_when_supabase_raises():
    sb = MagicMock()
    sb.table.side_effect = Exception("db unreachable")
    checker = HookDiversityChecker(supabase_client=sb)
    assert checker.get_threshold() == INTRA_ANGLE_THRESHOLD_DEFAULT


def test_threshold_supabase_query_targets_correct_key():
    sb = mock_supabase_with_threshold(0.80)
    checker = HookDiversityChecker(supabase_client=sb)
    checker.get_threshold()
    sb.table.assert_called_with("system_settings")
    sb.table.return_value.select.return_value.eq.assert_called_with("key", SYSTEM_SETTINGS_KEY)


# ---------------------------------------------------------------------------
# embed_one / batched_embed
# ---------------------------------------------------------------------------


def test_embed_one_returns_single_vector():
    e1 = make_embedding(1)
    openai = mock_openai_with_embeddings([e1])
    checker = HookDiversityChecker(openai_client=openai)
    result = checker.embed_one("hook text")
    assert result == e1


def test_batched_embed_empty_input_returns_empty():
    openai = mock_openai_with_embeddings([])
    checker = HookDiversityChecker(openai_client=openai)
    assert checker.batched_embed([]) == []
    openai.embeddings.create.assert_not_called()


def test_batched_embed_single_batch_below_size():
    embs = [make_embedding(i) for i in range(5)]
    openai = mock_openai_with_embeddings(embs)
    checker = HookDiversityChecker(openai_client=openai)
    result = checker.batched_embed(["a", "b", "c", "d", "e"], batch_size=10)
    assert result == embs
    assert openai.embeddings.create.call_count == 1


def test_batched_embed_multiple_batches_partial_remainder():
    embs = [make_embedding(i) for i in range(25)]
    openai = mock_openai_with_embeddings(embs)
    checker = HookDiversityChecker(openai_client=openai)
    result = checker.batched_embed([f"hook_{i}" for i in range(25)], batch_size=10)
    assert result == embs
    # 25 hooks / batch_size 10 = 3 calls (10, 10, 5)
    assert openai.embeddings.create.call_count == 3


def test_batched_embed_propagates_api_failure():
    openai = MagicMock()
    openai.embeddings.create.side_effect = Exception("rate limit")
    checker = HookDiversityChecker(openai_client=openai)
    with pytest.raises(Exception, match="rate limit"):
        checker.batched_embed(["hook"])


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------


def test_check_empty_batch_always_accepts():
    e1 = make_embedding(1)
    openai = mock_openai_with_embeddings([e1])
    checker = HookDiversityChecker(openai_client=openai)
    accept, sim, emb = checker.check("first hook", [], threshold=0.85)
    assert accept is True
    assert sim == 0.0
    assert emb == e1


def test_check_accepts_below_threshold():
    # Use vectors deliberately far apart in cosine space
    candidate_emb = [1.0] + [0.0] * 1535
    accepted_emb = [0.0, 1.0] + [0.0] * 1534
    # Cosine similarity between these = 0.0
    checker = HookDiversityChecker(openai_client=MagicMock())
    accept, sim, _ = checker.check(
        "candidate",
        [accepted_emb],
        threshold=0.85,
        candidate_embedding=candidate_emb,
    )
    assert accept is True
    assert sim == pytest.approx(0.0, abs=1e-5)


def test_check_rejects_above_threshold():
    # Identical vectors → cosine = 1.0 > any threshold < 1.0
    emb = [1.0] + [0.0] * 1535
    checker = HookDiversityChecker(openai_client=MagicMock())
    accept, sim, _ = checker.check(
        "candidate",
        [emb],
        threshold=0.85,
        candidate_embedding=emb,
    )
    assert accept is False
    assert sim == pytest.approx(1.0, abs=1e-5)


def test_check_uses_max_across_multiple_accepted():
    candidate_emb = [1.0, 0.0] + [0.0] * 1534
    far_emb = [0.0, 1.0] + [0.0] * 1534   # cosine 0 with candidate
    near_emb = [0.99, 0.1] + [0.0] * 1534  # cosine ~0.99 with candidate
    checker = HookDiversityChecker(openai_client=MagicMock())
    accept, sim, _ = checker.check(
        "candidate",
        [far_emb, near_emb],
        threshold=0.85,
        candidate_embedding=candidate_emb,
    )
    # Should reject — max similarity is the near_emb one, which exceeds 0.85
    assert accept is False
    assert sim > 0.85


def test_check_skips_api_call_when_candidate_embedding_provided():
    openai = MagicMock()
    checker = HookDiversityChecker(openai_client=openai)
    accept, sim, emb = checker.check(
        "hook",
        [],
        threshold=0.85,
        candidate_embedding=[0.5] * 1536,
    )
    assert emb == [0.5] * 1536
    openai.embeddings.create.assert_not_called()


def test_check_calls_api_when_candidate_embedding_missing():
    e1 = make_embedding(42)
    openai = mock_openai_with_embeddings([e1])
    checker = HookDiversityChecker(openai_client=openai)
    _, _, emb = checker.check("hook", [], threshold=0.85)
    assert emb == e1
    openai.embeddings.create.assert_called_once()


def test_check_falls_back_to_system_settings_threshold_when_not_provided():
    """Verify that when threshold=None, get_threshold() is consulted."""
    e1 = make_embedding(7)
    e2 = make_embedding(8)
    openai = mock_openai_with_embeddings([e1])
    sb = mock_supabase_with_threshold(0.99)  # Loose threshold → accept anything
    checker = HookDiversityChecker(openai_client=openai, supabase_client=sb)
    accept, _, _ = checker.check("c", [e2], threshold=None)
    # With threshold 0.99 and random vectors, similarity should be < 0.99 → accept
    assert accept is True


# ---------------------------------------------------------------------------
# generate_with_diversity
# ---------------------------------------------------------------------------


def test_generate_with_diversity_first_attempt_accepted():
    # Candidate is far from accepted
    candidate_emb = [1.0, 0.0] + [0.0] * 1534
    accepted_emb = [0.0, 1.0] + [0.0] * 1534

    openai = mock_openai_with_embeddings([candidate_emb])
    checker = HookDiversityChecker(openai_client=openai)
    gen_fn = MagicMock(return_value="fresh hook")

    text, emb, sim, clean = checker.generate_with_diversity(
        gen_fn, [accepted_emb], threshold=0.85, max_retries=3,
    )
    assert text == "fresh hook"
    assert emb == candidate_emb
    assert clean is True
    assert gen_fn.call_count == 1


def test_generate_with_diversity_retry_then_accept():
    # First candidate is too similar; second is diverse
    bad_emb = [1.0, 0.0] + [0.0] * 1534
    good_emb = [0.0, 1.0] + [0.0] * 1534
    accepted_emb = [1.0, 0.0] + [0.0] * 1534  # identical to bad → reject

    openai = mock_openai_with_embeddings([bad_emb, good_emb])
    checker = HookDiversityChecker(openai_client=openai)
    gen_fn = MagicMock(side_effect=["bad hook", "good hook"])

    text, emb, sim, clean = checker.generate_with_diversity(
        gen_fn, [accepted_emb], threshold=0.85, max_retries=3,
    )
    assert text == "good hook"
    assert emb == good_emb
    assert clean is True
    assert gen_fn.call_count == 2


def test_generate_with_diversity_all_rejected_returns_best_of_n():
    # All 3 candidates exceed threshold, but with different similarities
    accepted_emb = [1.0, 0.0] + [0.0] * 1534
    # Each candidate is increasingly similar; best-of-N is the first (least similar)
    cand1 = [0.99, 0.1] + [0.0] * 1534   # high similarity but lowest of the 3
    cand2 = [0.999, 0.05] + [0.0] * 1534
    cand3 = [1.0, 0.0] + [0.0] * 1534   # identical → similarity 1.0

    openai = mock_openai_with_embeddings([cand1, cand2, cand3])
    checker = HookDiversityChecker(openai_client=openai)
    gen_fn = MagicMock(side_effect=["c1", "c2", "c3"])

    text, emb, sim, clean = checker.generate_with_diversity(
        gen_fn, [accepted_emb], threshold=0.85, max_retries=3,
    )
    # Should pick cand1 (lowest similarity to accepted_emb)
    assert text == "c1"
    assert emb == cand1
    assert clean is False
    assert gen_fn.call_count == 3


def test_generate_with_diversity_propagates_generate_fn_exception():
    openai = MagicMock()
    checker = HookDiversityChecker(openai_client=openai)
    gen_fn = MagicMock(side_effect=RuntimeError("LLM down"))

    with pytest.raises(RuntimeError, match="LLM down"):
        checker.generate_with_diversity(gen_fn, [], threshold=0.85, max_retries=3)


def test_generate_with_diversity_propagates_embedding_api_failure():
    openai = MagicMock()
    openai.embeddings.create.side_effect = Exception("rate limit")
    checker = HookDiversityChecker(openai_client=openai)
    gen_fn = MagicMock(return_value="hook")

    with pytest.raises(Exception, match="rate limit"):
        checker.generate_with_diversity(gen_fn, [], threshold=0.85, max_retries=3)


def test_generate_with_diversity_falls_back_to_system_threshold_when_not_provided():
    candidate_emb = [1.0, 0.0] + [0.0] * 1534
    accepted_emb = [0.0, 1.0] + [0.0] * 1534
    openai = mock_openai_with_embeddings([candidate_emb])
    sb = mock_supabase_with_threshold(0.50)
    checker = HookDiversityChecker(openai_client=openai, supabase_client=sb)
    gen_fn = MagicMock(return_value="hook")

    text, _, _, clean = checker.generate_with_diversity(
        gen_fn, [accepted_emb], threshold=None, max_retries=2,
    )
    # Random orthogonal vectors → sim ~0 → accept under threshold 0.50
    assert clean is True
