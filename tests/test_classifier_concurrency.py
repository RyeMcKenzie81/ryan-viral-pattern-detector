"""classify_batch two-phase dispatch: caps stay deterministic at any concurrency.

CLASSIFIER_MAX_CONCURRENCY=1 (default) preserves sequential dispatch; >1 gathers
under a semaphore. Phase 1 enforces max_new as a DISPATCH cap and pre-allocates
video slots (first max_video prefetch-flagged video ads get budget 1, the rest 0),
so cost caps cannot be overrun by races. Exceptions tally as error_count.

Run with: pytest tests/test_classifier_concurrency.py -v
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from viraltracker.services.ad_intelligence.classifier_service import ClassifierService
from viraltracker.services.ad_intelligence.models import CreativeClassification


def _cls(source):
    return CreativeClassification.model_construct(source=source)


def _svc(ads: dict):
    svc = ClassifierService.__new__(ClassifierService)
    svc._get_ad_spend_order = AsyncMock(
        return_value={a: 100 - i for i, a in enumerate(ads)}
    )
    svc._batch_prefetch = AsyncMock(
        return_value=(ads, {a: [] for a in ads}, {}, {}, set())
    )
    svc._match_prefetched_classification = lambda rows, force=False: None
    return svc


def _run(svc, ids, **kw):
    from uuid import uuid4
    return asyncio.run(svc.classify_batch(uuid4(), uuid4(), uuid4(), ids, **kw))


def test_concurrent_dispatch_tallies_and_caps(monkeypatch):
    monkeypatch.setenv("CLASSIFIER_MAX_CONCURRENCY", "4")
    ids = [f"ad{i}" for i in range(6)]
    svc = _svc({a: {"meta_ad_id": a, "is_video": False} for a in ids})
    svc.classify_ad = AsyncMock(
        side_effect=lambda *a, **k: _cls("gemini_image_deep")
    )
    res = _run(svc, ids, max_new=4)
    assert svc.classify_ad.await_count == 4          # dispatch cap == max_new
    assert res.new_count == 4
    assert res.skipped_count == 2                    # the capped remainder


def test_video_slots_preallocated(monkeypatch):
    monkeypatch.setenv("CLASSIFIER_MAX_CONCURRENCY", "8")
    ids = ["v1", "v2", "v3"]
    svc = _svc({a: {"meta_ad_id": a, "is_video": True, "has_video_in_storage": True} for a in ids})
    seen = {}

    async def fake_classify(ad_id, *a, video_budget_remaining=0, **k):
        seen[ad_id] = video_budget_remaining
        src = "gemini_video" if video_budget_remaining > 0 else "skipped_video_budget"
        return _cls(src)

    svc.classify_ad = fake_classify
    res = _run(svc, ids, max_new=10, max_video=2)
    assert sorted(seen.values(), reverse=True) == [1, 1, 0]  # 2 slots, third starved
    assert res.new_count == 2 and res.skipped_count == 1


def test_exceptions_count_as_errors_not_crashes(monkeypatch):
    monkeypatch.setenv("CLASSIFIER_MAX_CONCURRENCY", "4")
    ids = ["a", "b"]
    svc = _svc({a: {"meta_ad_id": a, "is_video": False} for a in ids})

    async def flaky(ad_id, *a, **k):
        if ad_id == "a":
            raise RuntimeError("boom")
        return _cls("gemini_image_deep")

    svc.classify_ad = flaky
    res = _run(svc, ids, max_new=10)
    assert res.error_count == 1 and res.new_count == 1


def test_default_is_sequential(monkeypatch):
    monkeypatch.delenv("CLASSIFIER_MAX_CONCURRENCY", raising=False)
    ids = ["a", "b", "c"]
    svc = _svc({a: {"meta_ad_id": a, "is_video": False} for a in ids})
    in_flight, peak = 0, 0

    async def tracking(ad_id, *a, **k):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return _cls("gemini_image_deep")

    svc.classify_ad = tracking
    _run(svc, ids, max_new=10)
    assert peak == 1  # default stays strictly sequential


def test_storageless_videos_preskipped_without_burning_caps(monkeypatch):
    # Review finding: file-less videos are guaranteed skipped_missing_video_file —
    # they must not consume max_new dispatch slots or max_video budget.
    monkeypatch.setenv("CLASSIFIER_MAX_CONCURRENCY", "4")
    ids = ["nofile1", "nofile2", "hasfile"]
    ads = {
        "nofile1": {"meta_ad_id": "nofile1", "is_video": True},
        "nofile2": {"meta_ad_id": "nofile2", "is_video": True, "has_video_in_storage": False},
        "hasfile": {"meta_ad_id": "hasfile", "is_video": True, "has_video_in_storage": True},
    }
    svc = _svc(ads)
    dispatched = []

    async def fake_classify(ad_id, *a, video_budget_remaining=0, **k):
        dispatched.append((ad_id, video_budget_remaining))
        return _cls("gemini_video")

    svc.classify_ad = fake_classify
    res = _run(svc, ids, max_new=2, max_video=1)
    assert dispatched == [("hasfile", 1)]   # only the file-backed video dispatches
    assert res.skipped_count == 2           # the two file-less ones counted, not dispatched
    assert res.new_count == 1


def test_hard_cap_attrs_set_for_dispatch(monkeypatch):
    # classify_ad enforces the global cap via these attrs (race-free sync
    # check/increment); classify_batch must arm them per batch.
    monkeypatch.setenv("CLASSIFIER_MAX_CONCURRENCY", "2")
    ids = ["a"]
    svc = _svc({"a": {"meta_ad_id": "a", "is_video": False}})
    svc.classify_ad = AsyncMock(side_effect=lambda *a, **k: _cls("gemini_image_deep"))
    _run(svc, ids, max_new=5, max_video=7)
    assert svc._video_slots_cap == 7
    assert svc._video_slots_used == 0
