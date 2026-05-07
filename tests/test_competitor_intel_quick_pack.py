"""Unit tests for the Quick URL pack methods on CompetitorIntelService.

Mocks Supabase client and the fb_video_resolver. Covers:
- _create_quick_pack execution order (upload → insert → enqueue)
- Failure paths: upload fail, insert fail, enqueue fail
- _resolve_org_id call for "all" superuser case
- _find_existing_quick_pack lookup
- copy_existing_pack happy path
- re_run_extraction happy path
- create_quick_pack_from_url runs the resolver and delegates to _create_quick_pack
- save_to_angle_pipeline derives QUICK_INTEL source for quick packs

Run with: pytest tests/test_competitor_intel_quick_pack.py -v
"""

import asyncio
import os
from unittest.mock import MagicMock, patch

import pytest

# Required env vars for service init (mocked supabase, but the constructor reads them)
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")


@pytest.fixture
def service():
    from viraltracker.services.competitor_intel_service import CompetitorIntelService
    # The constructor does `from supabase import create_client; self.supabase = create_client(...)`.
    # Patch supabase.create_client at the module level to avoid a real network call.
    with patch("supabase.create_client") as mock_create:
        mock_create.return_value = MagicMock()
        svc = CompetitorIntelService()
        return svc


# ---------------------------------------------------------------------------
# _create_quick_pack — happy path, ordering
# ---------------------------------------------------------------------------


def test_create_quick_pack_calls_upload_insert_enqueue_in_order(service):
    call_order = []

    def upload_mock(video_bytes, mime_type, organization_id, pack_uuid):
        call_order.append("upload")
        return f"scraped-assets/quick-intel/{organization_id}/{pack_uuid}/video.mp4"

    insert_mock = MagicMock(side_effect=lambda *_: call_order.append("insert") or MagicMock(execute=MagicMock()))
    enqueue_mock = MagicMock(side_effect=lambda *_args, **_kw: call_order.append("enqueue"))

    service._upload_quick_video = upload_mock
    service._enqueue_quick_intel_job = enqueue_mock
    service._resolve_org_id = MagicMock(return_value="org-uuid-real")

    # Mock the table insert chain
    table_mock = MagicMock()
    table_mock.insert.return_value.execute = MagicMock(side_effect=lambda: call_order.append("insert"))
    service.supabase.table = MagicMock(return_value=table_mock)

    pack_id = asyncio.run(service._create_quick_pack(
        video_bytes=b"fake-mp4-bytes",
        mime_type="video/mp4",
        source_type="quick_url",
        source_url="https://facebook.com/page/posts/1",
        brand_id="brand-uuid",
        product_id="product-uuid",
        organization_id="org-uuid",
    ))

    assert call_order == ["upload", "insert", "enqueue"]
    assert pack_id  # uuid string
    service._resolve_org_id.assert_called_once_with("org-uuid", "brand-uuid")


def test_create_quick_pack_resolves_all_org_id(service):
    """When organization_id='all', _resolve_org_id is called to get a real UUID."""
    service._upload_quick_video = MagicMock(return_value="scraped-assets/quick-intel/real/x/video.mp4")
    service._enqueue_quick_intel_job = MagicMock()
    service._resolve_org_id = MagicMock(return_value="org-uuid-real")

    table_mock = MagicMock()
    table_mock.insert.return_value.execute = MagicMock()
    service.supabase.table = MagicMock(return_value=table_mock)

    asyncio.run(service._create_quick_pack(
        video_bytes=b"x",
        mime_type="video/mp4",
        source_type="quick_url",
        source_url="https://facebook.com/page/posts/1",
        brand_id="brand-uuid",
        product_id="product-uuid",
        organization_id="all",
    ))

    service._resolve_org_id.assert_called_once_with("all", "brand-uuid")


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


def test_create_quick_pack_upload_fail_writes_no_db_row(service):
    """Upload failure aborts before any DB row is inserted."""
    service._upload_quick_video = MagicMock(side_effect=RuntimeError("upload exploded"))
    service._enqueue_quick_intel_job = MagicMock()
    service._resolve_org_id = MagicMock(return_value="org-real")

    insert_mock = MagicMock()
    table_mock = MagicMock()
    table_mock.insert = insert_mock
    service.supabase.table = MagicMock(return_value=table_mock)

    with pytest.raises(RuntimeError, match="upload exploded"):
        asyncio.run(service._create_quick_pack(
            video_bytes=b"x", mime_type="video/mp4",
            source_type="quick_url", source_url="https://facebook.com/x/posts/1",
            brand_id="b", product_id="p", organization_id="org",
        ))

    insert_mock.assert_not_called()
    service._enqueue_quick_intel_job.assert_not_called()


def test_create_quick_pack_enqueue_fail_marks_pack_failed(service):
    """Enqueue failure → pack is marked status='failed' so the UI doesn't
    show a perma-pending pack."""
    service._upload_quick_video = MagicMock(return_value="scraped-assets/quick-intel/o/u/video.mp4")
    service._enqueue_quick_intel_job = MagicMock(side_effect=RuntimeError("enqueue down"))
    service._resolve_org_id = MagicMock(return_value="org-real")

    insert_call = MagicMock(execute=MagicMock())
    update_call = MagicMock()
    update_call.eq.return_value.execute = MagicMock()

    table_mock = MagicMock()
    table_mock.insert.return_value = insert_call
    table_mock.update.return_value = update_call
    service.supabase.table = MagicMock(return_value=table_mock)

    with pytest.raises(RuntimeError, match="enqueue down"):
        asyncio.run(service._create_quick_pack(
            video_bytes=b"x", mime_type="video/mp4",
            source_type="quick_url", source_url="https://facebook.com/x/posts/1",
            brand_id="b", product_id="p", organization_id="org",
        ))

    # The recovery update was attempted
    table_mock.update.assert_called()
    update_args = table_mock.update.call_args[0][0]
    assert update_args["status"] == "failed"
    assert "enqueue failed" in update_args.get("error_summary", "")


# ---------------------------------------------------------------------------
# create_quick_pack_from_url
# ---------------------------------------------------------------------------


def test_create_quick_pack_from_url_canonicalizes_and_resolves(service):
    """from_url must canonicalize the URL, call the resolver, then delegate
    to _create_quick_pack with the canonical URL."""

    captured = {}

    async def fake_create_quick_pack(**kwargs):
        captured.update(kwargs)
        return "new-pack-id"

    service._create_quick_pack = fake_create_quick_pack

    with patch("viraltracker.services.fb_video_resolver.resolve_fb_video") as mock_resolve:
        mock_resolve.return_value = (b"video-bytes", "video/mp4")

        pack_id = asyncio.run(service.create_quick_pack_from_url(
            url="https://m.facebook.com/61586/posts/12345/?ref=share",
            brand_id="b", product_id="p", organization_id="o",
        ))

    assert pack_id == "new-pack-id"
    # URL was canonicalized before being passed to the resolver and persisted.
    # Canonical form preserves the www. subdomain so the Apify actor's URL
    # validator accepts it.
    expected_canonical = "https://www.facebook.com/61586/posts/12345"
    mock_resolve.assert_called_once_with(expected_canonical)
    assert captured["source_url"] == expected_canonical
    assert captured["source_type"] == "quick_url"


def test_create_quick_pack_from_url_rejects_non_fb(service):
    """Non-FB URL is rejected before the resolver runs."""
    with pytest.raises(ValueError, match="does not look like a Facebook URL"):
        asyncio.run(service.create_quick_pack_from_url(
            url="https://www.youtube.com/watch?v=abc",
            brand_id="b", product_id="p", organization_id="o",
        ))


# ---------------------------------------------------------------------------
# copy_existing_pack
# ---------------------------------------------------------------------------


def test_copy_existing_pack_creates_new_complete_row(service):
    """Copy creates a new pack row with status='complete', referencing the
    same storage_path and copying extraction data — no worker enqueue."""

    source = {
        "id": "source-pack-id",
        "status": "complete",
        "source_type": "quick_url",
        "source_url": "https://facebook.com/x/posts/1",
        "source_video_storage_path": "scraped-assets/quick-intel/o/source/video.mp4",
        "video_analyses": [{"extraction": {"hook": {"text": "great hook"}}}],
        "pack_data": {"hooks": [{"text": "great hook"}]},
        "field_coverage": {},
        "prompt_version": "v1",
        "model_version": "gemini-3-pro-preview",
    }

    service.get_pack = MagicMock(return_value=source)
    service._resolve_org_id = MagicMock(return_value="org-real")

    insert_mock = MagicMock()
    insert_mock.execute = MagicMock()
    table_mock = MagicMock()
    table_mock.insert.return_value = insert_mock
    service.supabase.table = MagicMock(return_value=table_mock)

    new_id = asyncio.run(service.copy_existing_pack(
        source_pack_id="source-pack-id",
        brand_id="b", product_id="p", organization_id="o",
    ))

    assert new_id  # a new uuid
    assert new_id != "source-pack-id"

    # The inserted row references the same storage_path and has status='complete'
    insert_args = table_mock.insert.call_args[0][0]
    assert insert_args["status"] == "complete"
    assert insert_args["source_video_storage_path"] == source["source_video_storage_path"]
    assert insert_args["video_analyses"] == source["video_analyses"]
    assert insert_args["pack_data"] == source["pack_data"]
    assert insert_args["competitor_id"] is None


def test_copy_existing_pack_rejects_non_complete_source(service):
    source = {"id": "src", "status": "pending", "source_video_storage_path": "x"}
    service.get_pack = MagicMock(return_value=source)

    with pytest.raises(ValueError, match="not complete"):
        asyncio.run(service.copy_existing_pack(
            source_pack_id="src", brand_id="b", product_id="p", organization_id="o",
        ))


# ---------------------------------------------------------------------------
# re_run_extraction
# ---------------------------------------------------------------------------


def test_re_run_extraction_creates_pending_pack_and_enqueues(service):
    """Re-run creates a new pack with status='pending' and enqueues a job;
    does NOT copy extraction data (that's what 'Use existing' is for)."""

    source = {
        "id": "src-id",
        "status": "complete",
        "source_type": "quick_url",
        "source_url": "https://facebook.com/x/posts/1",
        "source_video_storage_path": "scraped-assets/quick-intel/o/src/video.mp4",
    }

    service.get_pack = MagicMock(return_value=source)
    service._resolve_org_id = MagicMock(return_value="org-real")
    service._enqueue_quick_intel_job = MagicMock()

    insert_mock = MagicMock(execute=MagicMock())
    table_mock = MagicMock()
    table_mock.insert.return_value = insert_mock
    service.supabase.table = MagicMock(return_value=table_mock)

    new_id = asyncio.run(service.re_run_extraction(
        source_pack_id="src-id",
        brand_id="b", product_id="p", organization_id="o",
    ))

    assert new_id and new_id != "src-id"
    insert_args = table_mock.insert.call_args[0][0]
    assert insert_args["status"] == "pending"
    assert insert_args["source_video_storage_path"] == source["source_video_storage_path"]
    # Crucially: extraction data is NOT copied — fresh Gemini call expected
    assert "video_analyses" not in insert_args or insert_args.get("video_analyses") in (None, [])
    assert "pack_data" not in insert_args or insert_args.get("pack_data") in (None, {})

    service._enqueue_quick_intel_job.assert_called_once()


# ---------------------------------------------------------------------------
# save_to_angle_pipeline derives candidate source from pack
# ---------------------------------------------------------------------------


def test_save_to_angle_pipeline_uses_quick_intel_for_quick_pack(service):
    """Quick packs produce candidates with source_type=QUICK_INTEL."""
    from viraltracker.services.models import CandidateSourceType

    pack = {
        "id": "p1",
        "source_type": "quick_url",
        "pack_data": {
            "hooks": [{"text": "hook A", "type": "promise"}],
            "angles": [],
            "pain_points": [],
            "jtbds": [],
        },
    }

    service.get_pack = MagicMock(return_value=pack)
    service._resolve_org_id = MagicMock(return_value="org-real")

    captured_calls = []

    class FakeAngleService:
        def create_candidate(self, **kwargs):
            captured_calls.append(kwargs)

    with patch(
        "viraltracker.services.angle_candidate_service.AngleCandidateService",
        new=FakeAngleService,
    ):
        service.save_to_angle_pipeline(
            pack_id="p1", product_id="prod-1", organization_id="org",
        )

    assert captured_calls, "expected at least one candidate to be created"
    for call in captured_calls:
        assert call["source_type"] == CandidateSourceType.QUICK_INTEL.value


def test_save_to_angle_pipeline_uses_competitor_intel_for_competitor_pack(service):
    from viraltracker.services.models import CandidateSourceType

    pack = {
        "id": "p2",
        "source_type": "competitor",
        "pack_data": {
            "hooks": [{"text": "hook B", "type": "curiosity"}],
            "angles": [], "pain_points": [], "jtbds": [],
        },
    }

    service.get_pack = MagicMock(return_value=pack)
    service._resolve_org_id = MagicMock(return_value="org-real")

    captured_calls = []

    class FakeAngleService:
        def create_candidate(self, **kwargs):
            captured_calls.append(kwargs)

    with patch(
        "viraltracker.services.angle_candidate_service.AngleCandidateService",
        new=FakeAngleService,
    ):
        service.save_to_angle_pipeline(
            pack_id="p2", product_id="prod-1", organization_id="org",
        )

    assert captured_calls
    for call in captured_calls:
        assert call["source_type"] == CandidateSourceType.COMPETITOR_INTEL.value
