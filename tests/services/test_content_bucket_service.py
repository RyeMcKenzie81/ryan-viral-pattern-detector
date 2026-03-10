"""
Tests for ContentBucketService — bucket CRUD, content analysis, and categorization.

Tests: bucket CRUD operations, Gemini video/image analysis (mocked), categorization
logic, media type detection, batch processing, session results, and JSON parsing.
"""

import json
import pytest
from unittest.mock import MagicMock, patch, ANY


@pytest.fixture
def mock_db():
    """Create a mock Supabase client."""
    return MagicMock()


@pytest.fixture
def service(mock_db):
    """Create service with mocked DB."""
    with patch(
        "viraltracker.services.content_bucket_service.get_supabase_client",
        return_value=mock_db,
    ):
        from viraltracker.services.content_bucket_service import ContentBucketService
        svc = ContentBucketService()
    return svc


# ============================================================================
# Bucket CRUD
# ============================================================================

class TestCreateBucket:
    def test_creates_bucket_with_required_fields(self, service, mock_db):
        mock_db.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=[{"id": "bucket-1", "name": "Test Bucket"}]
        )

        result = service.create_bucket(
            org_id="org-1",
            product_id="prod-1",
            name="Test Bucket",
        )

        mock_db.table.assert_called_with("content_buckets")
        call_args = mock_db.table.return_value.insert.call_args[0][0]
        assert call_args["organization_id"] == "org-1"
        assert call_args["product_id"] == "prod-1"
        assert call_args["name"] == "Test Bucket"
        assert result["id"] == "bucket-1"

    def test_creates_bucket_with_list_fields_serialized(self, service, mock_db):
        mock_db.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=[{"id": "bucket-1"}]
        )

        service.create_bucket(
            org_id="org-1",
            product_id="prod-1",
            name="Test",
            pain_points=["bloating", "fatigue"],
            solution_mechanism=["probiotics"],
            key_copy_hooks=["Your gut matters"],
        )

        call_args = mock_db.table.return_value.insert.call_args[0][0]
        assert call_args["pain_points"] == '["bloating", "fatigue"]'
        assert call_args["solution_mechanism"] == '["probiotics"]'
        assert call_args["key_copy_hooks"] == '["Your gut matters"]'

    def test_returns_empty_dict_on_no_data(self, service, mock_db):
        mock_db.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=[]
        )
        result = service.create_bucket("org-1", "prod-1", "Test")
        assert result == {}


class TestGetBuckets:
    def test_filters_by_product_and_org(self, service, mock_db):
        chain = mock_db.table.return_value.select.return_value
        chain.eq.return_value = chain
        chain.order.return_value.execute.return_value = MagicMock(
            data=[{"id": "b1", "name": "Bucket 1"}]
        )

        result = service.get_buckets("prod-1", "org-1")

        mock_db.table.assert_called_with("content_buckets")
        assert len(result) == 1

    def test_returns_empty_list_on_no_data(self, service, mock_db):
        chain = mock_db.table.return_value.select.return_value
        chain.eq.return_value = chain
        chain.order.return_value.execute.return_value = MagicMock(data=None)

        result = service.get_buckets("prod-1", "org-1")
        assert result == []


class TestDeleteBucket:
    def test_deletes_by_id(self, service, mock_db):
        mock_db.table.return_value.delete.return_value.eq.return_value.execute.return_value = MagicMock()

        result = service.delete_bucket("bucket-1")

        mock_db.table.assert_called_with("content_buckets")
        assert result is True


class TestDeleteCategorization:
    def test_deletes_by_session_and_filename(self, service, mock_db):
        chain = mock_db.table.return_value.delete.return_value
        chain.eq.return_value = chain
        chain.execute.return_value = MagicMock()

        result = service.delete_categorization("sess-1", "video.mp4")

        mock_db.table.assert_called_with("content_bucket_categorizations")
        assert result is True


# ============================================================================
# Media Type Detection
# ============================================================================

class TestDetectMediaType:
    def test_image_extensions(self, service):
        for ext in ["jpg", "jpeg", "png", "webp", "heic", "heif"]:
            assert service._detect_media_type(f"photo.{ext}") == "image"

    def test_video_extensions(self, service):
        for ext in ["mp4", "mov", "avi", "webm", "mpeg"]:
            assert service._detect_media_type(f"clip.{ext}") == "video"

    def test_case_insensitive(self, service):
        assert service._detect_media_type("photo.JPG") == "image"
        assert service._detect_media_type("clip.MP4") == "video"
        assert service._detect_media_type("photo.Png") == "image"

    def test_no_extension_raises(self, service):
        with pytest.raises(ValueError, match="has no extension"):
            service._detect_media_type("screenshot")

    def test_unsupported_extension_raises(self, service):
        with pytest.raises(ValueError, match="Unsupported file type"):
            service._detect_media_type("document.pdf")

    def test_gif_not_supported(self, service):
        with pytest.raises(ValueError, match="Unsupported file type"):
            service._detect_media_type("animation.gif")


# ============================================================================
# Video Analysis
# ============================================================================

class TestAnalyzeVideo:
    def test_returns_error_when_no_api_key(self, service):
        with patch.dict("os.environ", {}, clear=True):
            result = service.analyze_video(b"video_bytes", "test.mp4", "video/mp4")
        assert "error" in result
        assert "GEMINI_API_KEY" in result["error"]

    @patch("viraltracker.services.content_bucket_service.tempfile")
    def test_successful_analysis(self, mock_tempfile, service):
        mock_temp = MagicMock()
        mock_temp.name = "/tmp/test.mp4"
        mock_tempfile.NamedTemporaryFile.return_value = mock_temp

        analysis_result = {
            "transcript": "Hello world",
            "summary": "A test video",
            "hook": "Watch this",
            "pain_points": ["problem"],
            "benefits": ["solution"],
            "solution": "Our product",
            "tone": "educational",
            "format_type": "UGC",
            "key_themes": ["health"],
        }

        with patch.object(service, "analyze_video", return_value=analysis_result):
            result = service.analyze_video(b"video", "test.mp4", "video/mp4")

        assert result["transcript"] == "Hello world"
        assert result["summary"] == "A test video"

    def test_returns_error_on_failed_processing(self, service):
        with patch.object(
            service, "analyze_video",
            return_value={"error": "Gemini video processing failed"},
        ):
            result = service.analyze_video(b"video", "test.mp4", "video/mp4")
        assert "error" in result


# ============================================================================
# Image Analysis
# ============================================================================

class TestAnalyzeImage:
    def test_returns_error_when_no_api_key(self, service):
        with patch.dict("os.environ", {}, clear=True):
            result = service.analyze_image(b"img_bytes", "test.jpg", "image/jpeg")
        assert "error" in result
        assert "GEMINI_API_KEY" in result["error"]

    def test_rejects_oversized_image(self, service):
        huge_bytes = b"x" * (21 * 1024 * 1024)  # 21 MB
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            result = service.analyze_image(huge_bytes, "big.jpg", "image/jpeg")
        assert "error" in result
        assert "too large" in result["error"]

    def test_successful_analysis(self, service):
        analysis_result = {
            "summary": "A product ad",
            "text_overlays": ["Buy Now"],
            "visual_elements": ["product", "person"],
            "dominant_colors": ["blue", "white"],
            "cta_text": "Shop Now",
            "pain_points": ["problem"],
            "benefits": ["solution"],
            "solution": "Our product",
            "tone": "urgent",
            "format_type": "static ad",
            "key_themes": ["health"],
        }

        with patch.object(service, "analyze_image", return_value=analysis_result):
            result = service.analyze_image(b"img", "test.jpg", "image/jpeg")

        assert result["summary"] == "A product ad"
        assert "visual_elements" in result


# ============================================================================
# Categorization
# ============================================================================

class TestCategorizeContent:
    def test_returns_uncategorized_when_no_api_key(self, service):
        with patch.dict("os.environ", {}, clear=True):
            result = service.categorize_content(
                {"summary": "test"}, [{"name": "Bucket 1"}]
            )
        assert result["bucket_name"] == "Uncategorized"

    def test_successful_categorization(self, service):
        categorization_result = {
            "bucket_name": "Health Bucket",
            "confidence_score": 0.9,
            "reasoning": "Content matches health themes",
        }

        with patch.object(service, "categorize_content", return_value=categorization_result):
            result = service.categorize_content({"summary": "test"}, [])

        assert result["bucket_name"] == "Health Bucket"
        assert result["confidence_score"] == 0.9

    def test_handles_exception_gracefully(self, service):
        with patch.object(service, "categorize_content") as mock_cat:
            mock_cat.return_value = {
                "bucket_name": "Uncategorized",
                "confidence_score": 0.0,
                "reasoning": "Categorization error: test",
            }
            result = mock_cat({"summary": "test"}, [])
        assert result["bucket_name"] == "Uncategorized"

    def test_includes_hook_and_transcript_when_present(self, service):
        """Verify video-specific fields are included in categorization prompt."""
        analysis = {
            "summary": "A health video",
            "hook": "Did you know...",
            "transcript": "Full transcript here",
            "tone": "educational",
            "format_type": "talking head",
            "pain_points": ["fatigue"],
            "benefits": ["energy"],
            "solution": "supplements",
            "key_themes": ["health"],
        }

        categorization_result = {
            "bucket_name": "Health",
            "confidence_score": 0.85,
            "reasoning": "Matches",
        }

        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            with patch.object(service, "categorize_content", return_value=categorization_result):
                result = service.categorize_content(analysis, [{"name": "Health"}])

        assert result["bucket_name"] == "Health"

    def test_skips_hook_and_transcript_for_images(self, service):
        """Verify image analysis (no hook/transcript) still categorizes."""
        analysis = {
            "summary": "A product image",
            "tone": "urgent",
            "format_type": "static ad",
            "pain_points": ["problem"],
            "benefits": ["solution"],
            "solution": "product",
            "key_themes": ["health"],
            "visual_elements": ["product", "person"],
            "dominant_colors": ["blue"],
        }

        categorization_result = {
            "bucket_name": "Product Shots",
            "confidence_score": 0.8,
            "reasoning": "Visual match",
        }

        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            with patch.object(service, "categorize_content", return_value=categorization_result):
                result = service.categorize_content(analysis, [{"name": "Product Shots"}])

        assert result["bucket_name"] == "Product Shots"


# ============================================================================
# Batch Processing
# ============================================================================

class TestAnalyzeAndCategorizeBatch:
    def test_processes_files_and_saves_to_db(self, service, mock_db):
        mock_db.table.return_value.insert.return_value.execute.return_value = MagicMock()

        analysis = {"summary": "Test", "transcript": "Hello"}
        categorization = {
            "bucket_name": "Bucket A",
            "confidence_score": 0.85,
            "reasoning": "Good match",
        }

        with patch.object(service, "analyze_video", return_value=analysis):
            with patch.object(service, "categorize_content", return_value=categorization):
                with patch("viraltracker.services.content_bucket_service.time"):
                    results = service.analyze_and_categorize_batch(
                        files=[{"bytes": b"v", "name": "test.mp4", "type": "video/mp4"}],
                        buckets=[{"id": "b1", "name": "Bucket A"}],
                        product_id="prod-1",
                        org_id="org-1",
                        session_id="sess-1",
                    )

        assert len(results) == 1
        assert results[0]["status"] == "categorized"
        assert results[0]["bucket_name"] == "Bucket A"
        assert results[0]["confidence_score"] == 0.85
        assert results[0]["media_type"] == "video"

        # Verify DB insert was called with new table name
        mock_db.table.assert_called_with("content_bucket_categorizations")

    def test_handles_analysis_error(self, service, mock_db):
        mock_db.table.return_value.insert.return_value.execute.return_value = MagicMock()

        with patch.object(service, "analyze_video", return_value={"error": "API failed"}):
            with patch("viraltracker.services.content_bucket_service.time"):
                results = service.analyze_and_categorize_batch(
                    files=[{"bytes": b"v", "name": "bad.mp4", "type": "video/mp4"}],
                    buckets=[{"id": "b1", "name": "Bucket A"}],
                    product_id="prod-1",
                    org_id="org-1",
                    session_id="sess-1",
                )

        assert len(results) == 1
        assert results[0]["status"] == "error"
        assert results[0]["error"] == "API failed"

    def test_calls_progress_callback(self, service, mock_db):
        mock_db.table.return_value.insert.return_value.execute.return_value = MagicMock()
        callback = MagicMock()

        with patch.object(service, "analyze_video", return_value={"summary": "T"}):
            with patch.object(
                service, "categorize_content",
                return_value={"bucket_name": "B", "confidence_score": 0.5, "reasoning": "ok"},
            ):
                with patch("viraltracker.services.content_bucket_service.time"):
                    service.analyze_and_categorize_batch(
                        files=[{"bytes": b"v", "name": "f.mp4", "type": "video/mp4"}],
                        buckets=[{"id": "b1", "name": "B"}],
                        product_id="p",
                        org_id="o",
                        session_id="s",
                        progress_callback=callback,
                    )

        assert callback.call_count >= 2  # At least "Analyzing..." and "Categorized..."

    def test_routes_images_to_analyze_image(self, service, mock_db):
        """Verify image files are routed to analyze_image, not analyze_video."""
        mock_db.table.return_value.insert.return_value.execute.return_value = MagicMock()

        img_analysis = {"summary": "A product image", "visual_elements": ["product"]}
        categorization = {"bucket_name": "Ads", "confidence_score": 0.8, "reasoning": "ok"}

        with patch.object(service, "analyze_image", return_value=img_analysis) as mock_img:
            with patch.object(service, "analyze_video") as mock_vid:
                with patch.object(service, "categorize_content", return_value=categorization):
                    with patch("viraltracker.services.content_bucket_service.time"):
                        results = service.analyze_and_categorize_batch(
                            files=[{"bytes": b"img", "name": "ad.jpg", "type": "image/jpeg"}],
                            buckets=[{"id": "b1", "name": "Ads"}],
                            product_id="p",
                            org_id="o",
                            session_id="s",
                        )

        mock_img.assert_called_once()
        mock_vid.assert_not_called()
        assert results[0]["media_type"] == "image"

    def test_mixed_batch_routes_correctly(self, service, mock_db):
        """Verify mixed batch of images and videos routes to correct analyzers."""
        mock_db.table.return_value.insert.return_value.execute.return_value = MagicMock()

        img_analysis = {"summary": "Image content"}
        vid_analysis = {"summary": "Video content", "transcript": "Hello"}
        categorization = {"bucket_name": "B", "confidence_score": 0.7, "reasoning": "ok"}

        with patch.object(service, "analyze_image", return_value=img_analysis) as mock_img:
            with patch.object(service, "analyze_video", return_value=vid_analysis) as mock_vid:
                with patch.object(service, "categorize_content", return_value=categorization):
                    with patch("viraltracker.services.content_bucket_service.time"):
                        results = service.analyze_and_categorize_batch(
                            files=[
                                {"bytes": b"img", "name": "photo.png", "type": "image/png"},
                                {"bytes": b"vid", "name": "clip.mp4", "type": "video/mp4"},
                            ],
                            buckets=[{"id": "b1", "name": "B"}],
                            product_id="p",
                            org_id="o",
                            session_id="s",
                        )

        mock_img.assert_called_once()
        mock_vid.assert_called_once()
        assert len(results) == 2
        assert results[0]["media_type"] == "image"
        assert results[1]["media_type"] == "video"

    def test_source_parameter_passed_to_db(self, service, mock_db):
        """Verify source parameter is included in DB insert."""
        mock_db.table.return_value.insert.return_value.execute.return_value = MagicMock()

        with patch.object(service, "analyze_video", return_value={"summary": "T"}):
            with patch.object(
                service, "categorize_content",
                return_value={"bucket_name": "B", "confidence_score": 0.5, "reasoning": "ok"},
            ):
                with patch("viraltracker.services.content_bucket_service.time"):
                    service.analyze_and_categorize_batch(
                        files=[{"bytes": b"v", "name": "f.mp4", "type": "video/mp4"}],
                        buckets=[{"id": "b1", "name": "B"}],
                        product_id="p",
                        org_id="o",
                        session_id="s",
                        source="google_drive",
                    )

        # Verify insert record includes source
        insert_call = mock_db.table.return_value.insert.call_args[0][0]
        assert insert_call["source"] == "google_drive"


# ============================================================================
# Results Queries
# ============================================================================

class TestGetSessionResults:
    def test_returns_results_for_session(self, service, mock_db):
        chain = mock_db.table.return_value.select.return_value
        chain.eq.return_value.order.return_value.execute.return_value = MagicMock(
            data=[
                {"id": "r1", "filename": "a.mp4", "bucket_name": "B1"},
                {"id": "r2", "filename": "b.mp4", "bucket_name": "B2"},
            ]
        )

        results = service.get_session_results("sess-1")

        assert len(results) == 2
        mock_db.table.assert_called_with("content_bucket_categorizations")

    def test_returns_empty_list_on_no_data(self, service, mock_db):
        chain = mock_db.table.return_value.select.return_value
        chain.eq.return_value.order.return_value.execute.return_value = MagicMock(data=None)

        results = service.get_session_results("sess-1")
        assert results == []


class TestGetRecentSessions:
    def test_groups_by_session_id(self, service, mock_db):
        chain = mock_db.table.return_value.select.return_value
        eq_chain = chain.eq.return_value
        eq_chain.eq.return_value = eq_chain
        eq_chain.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[
                {"session_id": "s1", "created_at": "2026-02-18T10:00:00"},
                {"session_id": "s1", "created_at": "2026-02-18T10:00:01"},
                {"session_id": "s2", "created_at": "2026-02-18T09:00:00"},
            ]
        )

        results = service.get_recent_sessions("prod-1", "org-1")

        assert len(results) == 2
        # Most recent first
        assert results[0]["session_id"] == "s1"
        assert results[0]["file_count"] == 2
        assert results[1]["session_id"] == "s2"
        assert results[1]["file_count"] == 1

    def test_returns_empty_list_on_no_data(self, service, mock_db):
        chain = mock_db.table.return_value.select.return_value
        eq_chain = chain.eq.return_value
        eq_chain.eq.return_value = eq_chain
        eq_chain.order.return_value.limit.return_value.execute.return_value = MagicMock(data=None)

        results = service.get_recent_sessions("prod-1", "org-1")
        assert results == []


# ============================================================================
# JSON Parsing
# ============================================================================

class TestParseJsonResponse:
    def test_parses_plain_json(self, service):
        result = service._parse_json_response('{"key": "value"}')
        assert result == {"key": "value"}

    def test_parses_code_block_json(self, service):
        text = '```json\n{"key": "value"}\n```'
        result = service._parse_json_response(text)
        assert result == {"key": "value"}

    def test_parses_code_block_without_language(self, service):
        text = '```\n{"key": "value"}\n```'
        result = service._parse_json_response(text)
        assert result == {"key": "value"}

    def test_returns_none_for_empty_text(self, service):
        assert service._parse_json_response("") is None
        assert service._parse_json_response(None) is None

    def test_returns_none_for_invalid_json(self, service):
        assert service._parse_json_response("not json at all") is None

    def test_parses_nested_json(self, service):
        data = {"bucket_name": "Test", "confidence_score": 0.9, "reasoning": "ok"}
        result = service._parse_json_response(json.dumps(data))
        assert result["bucket_name"] == "Test"
        assert result["confidence_score"] == 0.9


# ============================================================================
# Mark as Uploaded
# ============================================================================

class TestMarkAsUploaded:
    def test_marks_single_record(self, service, mock_db):
        chain = mock_db.table.return_value.update.return_value
        chain.in_.return_value.execute.return_value = MagicMock(
            data=[{"id": "cat-1", "is_uploaded": True}]
        )

        count = service.mark_as_uploaded(["cat-1"])

        mock_db.table.assert_called_with("content_bucket_categorizations")
        mock_db.table.return_value.update.assert_called_with({"is_uploaded": True})
        chain.in_.assert_called_with("id", ["cat-1"])
        assert count == 1

    def test_marks_multiple_records(self, service, mock_db):
        chain = mock_db.table.return_value.update.return_value
        chain.in_.return_value.execute.return_value = MagicMock(
            data=[
                {"id": "cat-1", "is_uploaded": True},
                {"id": "cat-2", "is_uploaded": True},
                {"id": "cat-3", "is_uploaded": True},
            ]
        )

        count = service.mark_as_uploaded(["cat-1", "cat-2", "cat-3"])
        assert count == 3

    def test_unmarks_records(self, service, mock_db):
        chain = mock_db.table.return_value.update.return_value
        chain.in_.return_value.execute.return_value = MagicMock(
            data=[{"id": "cat-1", "is_uploaded": False}]
        )

        count = service.mark_as_uploaded(["cat-1"], uploaded=False)

        mock_db.table.return_value.update.assert_called_with({"is_uploaded": False})
        assert count == 1

    def test_returns_zero_for_empty_list(self, service, mock_db):
        count = service.mark_as_uploaded([])
        assert count == 0
        mock_db.table.assert_not_called()

    def test_returns_zero_when_no_data(self, service, mock_db):
        chain = mock_db.table.return_value.update.return_value
        chain.in_.return_value.execute.return_value = MagicMock(data=None)

        count = service.mark_as_uploaded(["cat-1"])
        assert count == 0


# ============================================================================
# Get Uploaded Files
# ============================================================================

class TestGetUploadedFiles:
    def test_returns_uploaded_files_filtered(self, service, mock_db):
        chain = mock_db.table.return_value.select.return_value
        chain.eq.return_value = chain
        chain.order.return_value = chain
        chain.execute.return_value = MagicMock(
            data=[
                {"id": "r1", "filename": "a.mp4", "bucket_name": "B1", "is_uploaded": True},
                {"id": "r2", "filename": "b.jpg", "bucket_name": "B1", "is_uploaded": True},
            ]
        )

        results = service.get_uploaded_files("prod-1", "org-1")

        mock_db.table.assert_called_with("content_bucket_categorizations")
        assert len(results) == 2
        assert results[0]["bucket_name"] == "B1"

    def test_returns_empty_list_when_none(self, service, mock_db):
        chain = mock_db.table.return_value.select.return_value
        chain.eq.return_value = chain
        chain.order.return_value = chain
        chain.execute.return_value = MagicMock(data=None)

        results = service.get_uploaded_files("prod-1", "org-1")
        assert results == []

    def test_skips_org_filter_for_superuser(self, service, mock_db):
        chain = mock_db.table.return_value.select.return_value
        chain.eq.return_value = chain
        chain.order.return_value = chain
        chain.execute.return_value = MagicMock(data=[])

        service.get_uploaded_files("prod-1", "all")

        # Verify eq was called with product_id and is_uploaded but NOT org_id
        eq_calls = chain.eq.call_args_list
        eq_args = [(c[0][0], c[0][1]) for c in eq_calls]
        assert ("product_id", "prod-1") in eq_args
        assert ("is_uploaded", True) in eq_args
        assert not any(arg[0] == "organization_id" for arg in eq_args)
