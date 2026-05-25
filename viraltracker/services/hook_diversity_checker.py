"""
HookDiversityChecker - intra-batch hook diversity guardrail.

Prevents hooks within a single ad batch from collapsing onto the same phrasing.
The diversity rule and its enforcement live here (not in scheduler_worker) so
the policy is unit-testable and the scheduler stays thin (decision 2A in
docs/plans/angle-driven-ad-creator/PLAN.md).

Two-tiered API:
  - `check(...)` — pure decision: given a candidate hook + already-accepted
    embeddings + a threshold, accept or reject. Returns the candidate's
    embedding so callers don't pay to re-embed it.
  - `generate_with_diversity(...)` — full policy loop: call `generate_fn`,
    embed, check, retry up to N times, then fall back to best-of-N (lowest
    max-similarity). Never infinite-loops.

Embedding model: OpenAI text-embedding-3-small (1536d). Same model
PatternDiscoveryService uses for angle_candidates. Consistent dimensions are
required so generated_ads.hook_embedding (HNSW index, VECTOR(1536)) can store
the result without dimension mismatch.

Threshold configuration (decision 2A.1):
  - Hardcoded default: INTRA_ANGLE_THRESHOLD_DEFAULT = 0.85
  - Override via system_settings.angle_pipeline.intra_angle_threshold
    (mirrors the DEFAULT_MAX_ADS_PER_SCHEDULED_RUN pattern in scheduler_worker)
  - Tune via UPDATE without redeploy

Rate-limit handling:
  This service does NOT catch OpenAI rate-limit errors. They propagate to the
  caller (the scheduler extension), which is responsible for marking the batch
  status='incomplete' rather than infinite-retrying. This is the critical-gap
  contract from PLAN.md (Failure Modes section).
"""

from __future__ import annotations

import logging
from typing import Callable, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# Embedding model — matches PatternDiscoveryService for cross-service consistency
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536

# Diversity threshold defaults (decision 2A.1)
INTRA_ANGLE_THRESHOLD_DEFAULT = 0.85
SYSTEM_SETTINGS_KEY = "angle_pipeline.intra_angle_threshold"

# Embedding batch size (decision 1B — amortize round-trips)
EMBEDDING_BATCH_SIZE = 10

# Retry policy
DEFAULT_MAX_RETRIES = 3


class HookDiversityChecker:
    """
    Embeds candidate hooks and rejects those too similar to already-accepted
    hooks in the same batch. See module docstring for design rationale.
    """

    def __init__(self, openai_client=None, supabase_client=None):
        """
        Args:
            openai_client: Optional pre-built OpenAI client. If None, lazy-loaded
                from `openai.OpenAI()` on first use (reads OPENAI_API_KEY env).
            supabase_client: Optional pre-built Supabase client. If None, lazy-loaded
                via get_supabase_client(). Only used for threshold lookup.
        """
        self._openai_client = openai_client
        self._supabase_client = supabase_client
        self._cached_threshold: Optional[float] = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @property
    def openai_client(self):
        if self._openai_client is None:
            import openai
            self._openai_client = openai.OpenAI()
        return self._openai_client

    @property
    def supabase_client(self):
        if self._supabase_client is None:
            from viraltracker.core.database import get_supabase_client
            self._supabase_client = get_supabase_client()
        return self._supabase_client

    def get_threshold(self) -> float:
        """
        Read INTRA_ANGLE_THRESHOLD from system_settings, falling back to default.

        Cached per-instance after first read so we don't query Supabase per hook.
        Call `reset_threshold_cache()` to force a re-read (e.g. between batches).
        """
        if self._cached_threshold is not None:
            return self._cached_threshold

        try:
            result = (
                self.supabase_client.table("system_settings")
                .select("value")
                .eq("key", SYSTEM_SETTINGS_KEY)
                .execute()
            )
            if result.data:
                self._cached_threshold = float(result.data[0]["value"])
                return self._cached_threshold
        except Exception as e:
            logger.warning(
                f"Failed to read {SYSTEM_SETTINGS_KEY} from system_settings "
                f"({e}); falling back to default {INTRA_ANGLE_THRESHOLD_DEFAULT}"
            )

        self._cached_threshold = INTRA_ANGLE_THRESHOLD_DEFAULT
        return self._cached_threshold

    def reset_threshold_cache(self) -> None:
        """Force the next get_threshold() call to re-read from system_settings."""
        self._cached_threshold = None

    # ------------------------------------------------------------------
    # Embedding
    # ------------------------------------------------------------------

    def embed_one(self, text: str) -> List[float]:
        """
        Embed a single hook string. Raises on API failure (caller responsible).

        Use batched_embed() when embedding multiple hooks at once — it's 10x
        cheaper in round-trip terms.
        """
        response = self.openai_client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=text,
        )
        return response.data[0].embedding

    def batched_embed(
        self,
        hooks: Sequence[str],
        batch_size: int = EMBEDDING_BATCH_SIZE,
    ) -> List[List[float]]:
        """
        Embed multiple hooks in batches of `batch_size`.

        Decision 1B in PLAN.md — batch=10 amortizes OpenAI round-trips ~10x
        without changing the design's retry semantics.

        Raises on any batch failure. Caller (scheduler) is responsible for
        catching and marking the surrounding batch status='incomplete' rather
        than infinite-retrying (the critical-gap contract from PLAN.md).
        """
        if not hooks:
            return []

        embeddings: List[List[float]] = []
        for i in range(0, len(hooks), batch_size):
            batch = list(hooks[i : i + batch_size])
            response = self.openai_client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=batch,
            )
            embeddings.extend([d.embedding for d in response.data])
        return embeddings

    # ------------------------------------------------------------------
    # Diversity check
    # ------------------------------------------------------------------

    def check(
        self,
        candidate_hook: str,
        accepted_embeddings: Sequence[Sequence[float]],
        threshold: Optional[float] = None,
        candidate_embedding: Optional[Sequence[float]] = None,
    ) -> Tuple[bool, float, List[float]]:
        """
        Decide whether a candidate hook is diverse enough to accept.

        Args:
            candidate_hook: The hook text being evaluated.
            accepted_embeddings: Embeddings of hooks already accepted in this batch.
            threshold: Cosine similarity cutoff. If None, reads from system_settings.
            candidate_embedding: Optional pre-computed embedding of candidate_hook.
                When provided, this method does NOT call the OpenAI API. Used by
                generate_with_diversity to avoid double-embedding during retries.

        Returns:
            (accept: bool, similarity_to_nearest: float, candidate_embedding: List[float])
            - When accepted_embeddings is empty: always accept; similarity = 0.0.
            - When max(cosine_sim) > threshold: reject.
            - Otherwise: accept.
            - candidate_embedding is always returned so the caller can reuse it
              (e.g. write it to generated_ads.hook_embedding without re-paying).
        """
        if threshold is None:
            threshold = self.get_threshold()

        # Embed candidate if not provided
        if candidate_embedding is None:
            candidate_embedding = self.embed_one(candidate_hook)
        candidate_vec = list(candidate_embedding)

        # Empty batch → first hook is always accepted (similarity = 0.0)
        if not accepted_embeddings:
            return (True, 0.0, candidate_vec)

        # Compute max cosine similarity to accepted set
        max_sim = self._max_cosine_similarity(candidate_vec, accepted_embeddings)
        accept = max_sim <= threshold
        return (accept, max_sim, candidate_vec)

    @staticmethod
    def _max_cosine_similarity(
        candidate: Sequence[float],
        accepted: Sequence[Sequence[float]],
    ) -> float:
        """
        Return max cosine similarity between `candidate` and any vector in `accepted`.

        Both `candidate` and `accepted` are assumed to be unnormalized OpenAI
        embeddings; we normalize on the fly. NumPy handles the dot products.
        """
        cand = np.asarray(candidate, dtype=np.float32)
        cand_norm = cand / max(np.linalg.norm(cand), 1e-12)

        acc = np.asarray(accepted, dtype=np.float32)
        # acc shape: (n, dim)
        acc_norms = np.linalg.norm(acc, axis=1, keepdims=True)
        acc_normalized = acc / np.where(acc_norms == 0, 1, acc_norms)

        sims = acc_normalized @ cand_norm  # shape: (n,)
        return float(np.max(sims))

    # ------------------------------------------------------------------
    # Full policy loop
    # ------------------------------------------------------------------

    def generate_with_diversity(
        self,
        generate_fn: Callable[[], str],
        accepted_embeddings: Sequence[Sequence[float]],
        threshold: Optional[float] = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> Tuple[str, List[float], float, bool]:
        """
        Generate a hook that passes the diversity check, retrying up to
        `max_retries` times. If all retries are rejected, returns the
        best-of-N candidate (lowest max-similarity to the accepted set).

        Args:
            generate_fn: Callable that returns a fresh candidate hook string
                on each call. Typically a closure around the LLM hook generator.
            accepted_embeddings: Embeddings of hooks already accepted in batch.
            threshold: Cosine cutoff. If None, reads from system_settings.
            max_retries: Maximum number of generate-and-check attempts before
                falling back to best-of-N. Default 3.

        Returns:
            (hook_text, hook_embedding, similarity_to_nearest, was_accepted_cleanly)
            - was_accepted_cleanly is False if all retries were rejected and
              best-of-N was used (caller can log a warning).
            - Never infinite-loops. Never raises on rejection — only on
              underlying API failures, which propagate up.
        """
        if threshold is None:
            threshold = self.get_threshold()

        # Track the best (lowest-similarity) candidate so far, for fallback
        best_candidate: Optional[Tuple[str, List[float], float]] = None

        for attempt in range(1, max_retries + 1):
            candidate_text = generate_fn()
            accepted, similarity, candidate_emb = self.check(
                candidate_text,
                accepted_embeddings,
                threshold=threshold,
            )

            if accepted:
                return (candidate_text, candidate_emb, similarity, True)

            # Track the lowest-similarity candidate as our fallback
            if best_candidate is None or similarity < best_candidate[2]:
                best_candidate = (candidate_text, candidate_emb, similarity)

            logger.debug(
                f"Diversity reject attempt {attempt}/{max_retries}: "
                f"similarity={similarity:.4f} > threshold={threshold:.4f}"
            )

        # All retries exhausted — fall back to best-of-N
        assert best_candidate is not None  # Loop ran at least once
        logger.info(
            f"Diversity check rejected all {max_retries} attempts; accepting "
            f"best-of-{max_retries} with similarity={best_candidate[2]:.4f} "
            f"(threshold={threshold:.4f})"
        )
        return (best_candidate[0], best_candidate[1], best_candidate[2], False)
