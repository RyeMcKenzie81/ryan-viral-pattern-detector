"""
ContentBucketService — Bucket CRUD + Gemini content analysis + categorization.

Organizes bulk uploads (images and videos) into user-defined "content buckets"
for ad campaigns. Uses Gemini Files API for video analysis and inline
Part.from_bytes for image analysis, plus text-only Gemini calls for
bucket categorization.
"""

import json
import logging
import mimetypes
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from viraltracker.core.database import get_supabase_client

logger = logging.getLogger(__name__)

# Gemini model for classification tasks (fast + cheap)
GEMINI_MODEL = "gemini-2.5-flash"

# Supported image extensions (Gemini-compatible — GIF not supported in 2.0+)
IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "heic", "heif"}

# Supported video extensions
VIDEO_EXTENSIONS = {"mp4", "mov", "avi", "webm", "mpeg"}

# Max inline image size for Gemini (conservative; actual limit is 100MB)
MAX_IMAGE_BYTES = 20 * 1024 * 1024  # 20 MB

VIDEO_ANALYSIS_PROMPT = """Analyze this video and return a JSON object with the following fields:

{
  "transcript": "Full transcript of all spoken words",
  "text_overlays": ["List of all text shown on screen"],
  "summary": "2-3 sentence summary of the video content and message",
  "hook": "The opening hook or attention-grabber (first 3-5 seconds)",
  "pain_points": ["Pain points addressed in the video"],
  "benefits": ["Benefits or solutions presented"],
  "solution": "The main solution or product positioning",
  "tone": "Overall tone (e.g., urgent, educational, testimonial, emotional)",
  "format_type": "Video format (e.g., UGC, talking head, slideshow, B-roll, before/after)",
  "key_themes": ["Main themes or topics covered"]
}

Return ONLY the JSON object, no other text."""

IMAGE_ANALYSIS_PROMPT = """Analyze this image and return a JSON object with the following fields:

{
  "text_overlays": ["List of all text shown in the image"],
  "summary": "2-3 sentence summary of the image content and message",
  "visual_elements": ["Key visual elements (people, products, backgrounds, icons, etc.)"],
  "dominant_colors": ["Top 3-5 dominant colors"],
  "cta_text": "Call-to-action text if present, or null",
  "pain_points": ["Pain points addressed in the image"],
  "benefits": ["Benefits or solutions presented"],
  "solution": "The main solution or product positioning",
  "tone": "Overall tone (e.g., urgent, educational, testimonial, emotional)",
  "format_type": "Image format (e.g., static ad, carousel card, infographic, before/after, lifestyle, product shot)",
  "key_themes": ["Main themes or topics covered"]
}

Return ONLY the JSON object, no other text."""

CATEGORIZATION_PROMPT_TEMPLATE = """You are a content categorizer for ad campaigns.

Given a content analysis and a set of content buckets, determine which bucket is the BEST fit.

## Content Analysis
{content_analysis}

## Available Buckets
{buckets_description}

## Instructions
Choose the single best-matching bucket based on:
1. Theme/topic alignment with the bucket's description and angle
2. Pain points overlap
3. Solution mechanism match
4. Tone and avatar fit

Return a JSON object:
{{
  "bucket_name": "Exact name of the chosen bucket",
  "confidence_score": 0.85,
  "reasoning": "1-2 sentence explanation of why this bucket is the best fit"
}}

If no bucket is a good fit (confidence < 0.3), return:
{{
  "bucket_name": "Uncategorized",
  "confidence_score": 0.0,
  "reasoning": "Explanation of why no bucket fits"
}}

Return ONLY the JSON object, no other text."""


class ContentBucketService:
    """Service for content bucket management and media categorization."""

    def __init__(self):
        self._db = get_supabase_client()

    def _resolve_org_id(self, org_id: str, product_id: str) -> str:
        """Resolve 'all' superuser org to the actual org owning the product."""
        if org_id != "all":
            return org_id
        # products has brand_id, not organization_id — join through brands
        result = (
            self._db.table("products")
            .select("brand_id")
            .eq("id", product_id)
            .limit(1)
            .execute()
        )
        if not result.data:
            raise ValueError(f"Product {product_id} not found")
        brand_id = result.data[0]["brand_id"]
        brand_result = (
            self._db.table("brands")
            .select("organization_id")
            .eq("id", brand_id)
            .limit(1)
            .execute()
        )
        if brand_result.data:
            return brand_result.data[0]["organization_id"]
        raise ValueError(f"Brand {brand_id} not found for product {product_id}")

    # ─── Media Type Detection ──────────────────────────────────────────

    @staticmethod
    def _detect_media_type(filename: str) -> str:
        """Detect whether a file is an image or video based on extension.

        Args:
            filename: Original filename with extension.

        Returns:
            'image' or 'video'.

        Raises:
            ValueError: If file has no extension or unsupported extension.
        """
        ext = Path(filename).suffix.lstrip(".").lower()
        if not ext:
            raise ValueError(f"Cannot determine file type: '{filename}' has no extension")
        if ext in IMAGE_EXTENSIONS:
            return "image"
        if ext in VIDEO_EXTENSIONS:
            return "video"
        raise ValueError(
            f"Unsupported file type '.{ext}'. "
            f"Supported: {', '.join(sorted(IMAGE_EXTENSIONS | VIDEO_EXTENSIONS))}"
        )

    # ─── Bucket CRUD ──────────────────────────────────────────────────

    def create_bucket(
        self,
        org_id: str,
        product_id: str,
        name: str,
        best_for: Optional[str] = None,
        angle: Optional[str] = None,
        avatar: Optional[str] = None,
        pain_points: Optional[List[str]] = None,
        solution_mechanism: Optional[List[str]] = None,
        key_copy_hooks: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Create a new content bucket.

        Args:
            org_id: Organization ID for multi-tenant isolation.
            product_id: Product this bucket belongs to.
            name: Bucket name (unique per product).
            best_for: What types of content belong here.
            angle: The angle/approach for this bucket.
            avatar: Target avatar description.
            pain_points: List of pain point strings.
            solution_mechanism: List of solution mechanism strings.
            key_copy_hooks: List of key copy hook strings.

        Returns:
            Created bucket record.
        """
        resolved_org = self._resolve_org_id(org_id, product_id)
        data = {
            "organization_id": resolved_org,
            "product_id": product_id,
            "name": name,
            "best_for": best_for,
            "angle": angle,
            "avatar": avatar,
            "pain_points": json.dumps(pain_points or []),
            "solution_mechanism": json.dumps(solution_mechanism or []),
            "key_copy_hooks": json.dumps(key_copy_hooks or []),
        }
        result = self._db.table("content_buckets").insert(data).execute()
        return result.data[0] if result.data else {}

    def get_buckets(self, product_id: str, org_id: str) -> List[Dict[str, Any]]:
        """Get all content buckets for a product.

        Args:
            product_id: Product ID.
            org_id: Organization ID for multi-tenant filtering.

        Returns:
            List of bucket records ordered by display_order.
        """
        query = (
            self._db.table("content_buckets")
            .select("*")
            .eq("product_id", product_id)
        )
        if org_id != "all":
            query = query.eq("organization_id", org_id)
        result = query.order("display_order").execute()
        return result.data or []

    def update_bucket(self, bucket_id: str, **fields) -> Dict[str, Any]:
        """Update a content bucket.

        Args:
            bucket_id: Bucket ID to update.
            **fields: Fields to update (name, best_for, angle, etc.).

        Returns:
            Updated bucket record.
        """
        # Serialize list fields to JSON
        for key in ("pain_points", "solution_mechanism", "key_copy_hooks"):
            if key in fields and isinstance(fields[key], list):
                fields[key] = json.dumps(fields[key])

        fields["updated_at"] = "now()"
        result = (
            self._db.table("content_buckets")
            .update(fields)
            .eq("id", bucket_id)
            .execute()
        )
        return result.data[0] if result.data else {}

    def delete_bucket(self, bucket_id: str) -> bool:
        """Delete a content bucket.

        Args:
            bucket_id: Bucket ID to delete.

        Returns:
            True if deleted.
        """
        self._db.table("content_buckets").delete().eq("id", bucket_id).execute()
        return True

    # ─── Content Analysis ──────────────────────────────────────────────

    def analyze_video(
        self, file_bytes: bytes, filename: str, mime_type: str
    ) -> Dict[str, Any]:
        """Analyze a video using Gemini Files API.

        Uploads video to Gemini, waits for processing, then extracts
        transcript, text overlays, summary, and thematic data.

        Args:
            file_bytes: Raw video file bytes.
            filename: Original filename.
            mime_type: MIME type (e.g., video/mp4).

        Returns:
            Dict with analysis fields (transcript, summary, etc.)
            or error dict with 'error' key.
        """
        from google import genai

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return {"error": "GEMINI_API_KEY not set"}

        client = genai.Client(api_key=api_key)
        gemini_file = None
        temp_path = None

        try:
            # Write to temp file
            suffix = Path(filename).suffix or ".mp4"
            temp_file = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            temp_file.write(file_bytes)
            temp_file.close()
            temp_path = temp_file.name

            # Upload to Gemini Files API
            logger.info(f"Uploading {filename} to Gemini Files API")
            gemini_file = client.files.upload(file=temp_path)
            logger.info(f"Uploaded {filename}: {gemini_file.uri}")

            # Poll until processed (up to 180s)
            max_wait = 180
            waited = 0
            while gemini_file.state.name == "PROCESSING" and waited < max_wait:
                time.sleep(3)
                waited += 3
                gemini_file = client.files.get(name=gemini_file.name)

            if gemini_file.state.name == "FAILED":
                return {"error": "Gemini video processing failed"}

            if gemini_file.state.name == "PROCESSING":
                return {"error": "Gemini video processing timed out"}

            # Analyze
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[gemini_file, VIDEO_ANALYSIS_PROMPT],
            )

            result_text = response.text.strip() if response.text else ""
            parsed = self._parse_json_response(result_text)

            if not parsed:
                return {"error": f"Failed to parse Gemini response for {filename}"}

            logger.info(f"Analysis complete for {filename}")
            return parsed

        except Exception as e:
            logger.error(f"Video analysis failed for {filename}: {e}")
            return {"error": str(e)[:500]}

        finally:
            # Cleanup Gemini file
            if gemini_file and client:
                try:
                    client.files.delete(name=gemini_file.name)
                except Exception:
                    pass
            # Cleanup temp file
            if temp_path and Path(temp_path).exists():
                try:
                    Path(temp_path).unlink()
                except Exception:
                    pass

    def analyze_image(
        self, file_bytes: bytes, filename: str, mime_type: str
    ) -> Dict[str, Any]:
        """Analyze an image using Gemini inline (Part.from_bytes).

        No Files API upload needed — sends image bytes directly.
        Much faster than video (~2-3s vs ~12s).

        Args:
            file_bytes: Raw image file bytes.
            filename: Original filename.
            mime_type: MIME type (e.g., image/jpeg).

        Returns:
            Dict with analysis fields (summary, visual_elements, etc.)
            or error dict with 'error' key.
        """
        from google import genai
        from google.genai import types as genai_types

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return {"error": "GEMINI_API_KEY not set"}

        # Size guard
        if len(file_bytes) > MAX_IMAGE_BYTES:
            size_mb = len(file_bytes) / (1024 * 1024)
            return {"error": f"Image too large ({size_mb:.1f}MB). Max is 20MB."}

        try:
            client = genai.Client(api_key=api_key)
            image_part = genai_types.Part.from_bytes(
                data=file_bytes, mime_type=mime_type
            )

            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[image_part, IMAGE_ANALYSIS_PROMPT],
            )

            result_text = response.text.strip() if response.text else ""
            parsed = self._parse_json_response(result_text)

            if not parsed:
                return {"error": f"Failed to parse Gemini response for {filename}"}

            logger.info(f"Image analysis complete for {filename}")
            return parsed

        except Exception as e:
            logger.error(f"Image analysis failed for {filename}: {e}")
            return {"error": str(e)[:500]}

    def categorize_content(
        self, analysis: Dict[str, Any], buckets: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Categorize content into a bucket using text-only Gemini call.

        Works for both image and video analyses — conditionally includes
        transcript/hook only when present.

        Args:
            analysis: Analysis dict from analyze_video() or analyze_image().
            buckets: List of bucket dicts from get_buckets().

        Returns:
            Dict with bucket_name, confidence_score, reasoning.
        """
        from google import genai

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return {"bucket_name": "Uncategorized", "confidence_score": 0.0,
                    "reasoning": "GEMINI_API_KEY not set"}

        # Build content analysis summary (media-agnostic)
        parts = [
            f"Summary: {analysis.get('summary', 'N/A')}",
            f"Tone: {analysis.get('tone', 'N/A')}",
            f"Format: {analysis.get('format_type', 'N/A')}",
            f"Pain Points: {', '.join(analysis.get('pain_points', []))}",
            f"Benefits: {', '.join(analysis.get('benefits', []))}",
            f"Solution: {analysis.get('solution', 'N/A')}",
            f"Key Themes: {', '.join(analysis.get('key_themes', []))}",
        ]
        # Conditionally include video-only fields
        if analysis.get("hook"):
            parts.insert(1, f"Hook: {analysis['hook']}")
        if analysis.get("transcript"):
            parts.append(f"Transcript excerpt: {analysis['transcript'][:500]}")
        # Include image-specific fields when present
        if analysis.get("visual_elements"):
            parts.append(f"Visual Elements: {', '.join(analysis['visual_elements'])}")
        if analysis.get("dominant_colors"):
            parts.append(f"Dominant Colors: {', '.join(analysis['dominant_colors'])}")

        content_summary = "\n".join(parts)

        # Build bucket descriptions
        bucket_descs = []
        for b in buckets:
            pain_pts = b.get("pain_points", [])
            if isinstance(pain_pts, str):
                pain_pts = json.loads(pain_pts)
            sol_mech = b.get("solution_mechanism", [])
            if isinstance(sol_mech, str):
                sol_mech = json.loads(sol_mech)
            hooks = b.get("key_copy_hooks", [])
            if isinstance(hooks, str):
                hooks = json.loads(hooks)

            desc = (
                f"### {b['name']}\n"
                f"- Best for: {b.get('best_for', 'N/A')}\n"
                f"- Angle: {b.get('angle', 'N/A')}\n"
                f"- Avatar: {b.get('avatar', 'N/A')}\n"
                f"- Pain Points: {', '.join(pain_pts)}\n"
                f"- Solution Mechanism: {', '.join(sol_mech)}\n"
                f"- Key Copy Hooks: {', '.join(hooks)}"
            )
            bucket_descs.append(desc)

        prompt = CATEGORIZATION_PROMPT_TEMPLATE.format(
            content_analysis=content_summary,
            buckets_description="\n\n".join(bucket_descs),
        )

        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[prompt],
            )
            result_text = response.text.strip() if response.text else ""
            parsed = self._parse_json_response(result_text)

            if not parsed:
                return {"bucket_name": "Uncategorized", "confidence_score": 0.0,
                        "reasoning": "Failed to parse categorization response"}

            return parsed

        except Exception as e:
            logger.error(f"Categorization failed: {e}")
            return {"bucket_name": "Uncategorized", "confidence_score": 0.0,
                    "reasoning": f"Categorization error: {str(e)[:200]}"}

    def analyze_and_categorize_batch(
        self,
        files: List[Dict[str, Any]],
        buckets: List[Dict[str, Any]],
        product_id: str,
        org_id: str,
        session_id: str,
        progress_callback: Optional[Callable] = None,
        source: str = "upload",
    ) -> List[Dict[str, Any]]:
        """Process a batch of files (images + videos): analyze each then categorize.

        Routes each file to analyze_image() or analyze_video() based on
        extension. Processes sequentially with rate-limit delays (2s for
        images, 7s for videos).

        Args:
            files: List of dicts with 'bytes', 'name', 'type' keys.
            buckets: List of bucket dicts.
            product_id: Product ID.
            org_id: Organization ID.
            session_id: UUID grouping this upload batch.
            progress_callback: Optional fn(index, total, filename, status_msg).
            source: Origin of the files ('upload' or 'google_drive').

        Returns:
            List of result dicts for each file.
        """
        resolved_org = self._resolve_org_id(org_id, product_id)
        results = []
        total = len(files)

        # Build bucket lookup by name
        bucket_lookup = {b["name"]: b["id"] for b in buckets}

        for i, file_info in enumerate(files):
            filename = file_info["name"]

            # Detect media type
            try:
                media_type = self._detect_media_type(filename)
            except ValueError as e:
                # Unsupported file type — save error and continue
                record = {
                    "organization_id": resolved_org,
                    "product_id": product_id,
                    "filename": filename,
                    "status": "error",
                    "error_message": str(e),
                    "session_id": session_id,
                    "media_type": "video",  # default for DB constraint
                    "source": source,
                }
                self._db.table("content_bucket_categorizations").insert(record).execute()
                results.append({"filename": filename, "status": "error",
                                "error": str(e), "media_type": "video"})
                if progress_callback:
                    progress_callback(i, total, filename, f"Error: {str(e)[:100]}")
                continue

            type_label = "image" if media_type == "image" else "video"

            if progress_callback:
                progress_callback(i, total, filename, f"Analyzing {type_label}...")

            # Step 1: Analyze (route by media type)
            if media_type == "image":
                analysis = self.analyze_image(
                    file_info["bytes"], filename, file_info["type"]
                )
            else:
                analysis = self.analyze_video(
                    file_info["bytes"], filename, file_info["type"]
                )

            if "error" in analysis:
                # Save error record
                record = {
                    "organization_id": resolved_org,
                    "product_id": product_id,
                    "filename": filename,
                    "status": "error",
                    "error_message": analysis["error"],
                    "session_id": session_id,
                    "media_type": media_type,
                    "source": source,
                }
                self._db.table("content_bucket_categorizations").insert(record).execute()
                results.append({"filename": filename, "status": "error",
                                "error": analysis["error"], "media_type": media_type})

                if progress_callback:
                    progress_callback(i, total, filename, f"Error: {analysis['error'][:100]}")

                # Still delay before next file
                if i < total - 1:
                    time.sleep(2 if media_type == "image" else 7)
                continue

            if progress_callback:
                progress_callback(i, total, filename, "Categorizing...")

            # Step 2: Categorize (text-only call, media-agnostic)
            categorization = self.categorize_content(analysis, buckets)

            bucket_name = categorization.get("bucket_name", "Uncategorized")
            bucket_id = bucket_lookup.get(bucket_name)
            confidence = categorization.get("confidence_score", 0.0)

            # Step 3: Save to DB
            record = {
                "organization_id": resolved_org,
                "product_id": product_id,
                "bucket_id": bucket_id,
                "filename": filename,
                "bucket_name": bucket_name,
                "confidence_score": confidence,
                "reasoning": categorization.get("reasoning", ""),
                "summary": analysis.get("summary", ""),
                "transcript": analysis.get("transcript", ""),
                "analysis_data": json.dumps(analysis),
                "status": "categorized" if bucket_id else "analyzed",
                "session_id": session_id,
                "media_type": media_type,
                "source": source,
            }
            self._db.table("content_bucket_categorizations").insert(record).execute()

            result = {
                "filename": filename,
                "status": "categorized",
                "bucket_name": bucket_name,
                "confidence_score": confidence,
                "reasoning": categorization.get("reasoning", ""),
                "summary": analysis.get("summary", ""),
                "media_type": media_type,
            }
            results.append(result)

            if progress_callback:
                progress_callback(
                    i, total, filename,
                    f"Categorized → {bucket_name} ({confidence:.0%})"
                )

            # Rate limit delay: 2s for images, 7s for videos (skip after last)
            if i < total - 1:
                time.sleep(2 if media_type == "image" else 7)

        return results

    # ─── Results ──────────────────────────────────────────────────────

    def delete_categorization(self, session_id: str, filename: str) -> bool:
        """Delete a categorization record by session + filename (for retry).

        Args:
            session_id: Session UUID.
            filename: Original filename.

        Returns:
            True after deletion.
        """
        self._db.table("content_bucket_categorizations") \
            .delete() \
            .eq("session_id", session_id) \
            .eq("filename", filename) \
            .execute()
        return True

    def get_session_results(self, session_id: str) -> List[Dict[str, Any]]:
        """Get all categorization results for a session.

        Args:
            session_id: Session UUID.

        Returns:
            List of categorization records ordered by filename.
        """
        result = (
            self._db.table("content_bucket_categorizations")
            .select("*")
            .eq("session_id", session_id)
            .order("filename")
            .execute()
        )
        return result.data or []

    def get_recent_sessions(
        self, product_id: str, org_id: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get recent categorization sessions for a product.

        Returns one row per session with the session_id and timestamp.

        Args:
            product_id: Product ID.
            org_id: Organization ID.
            limit: Max sessions to return.

        Returns:
            List of dicts with session_id, created_at, file_count.
        """
        query = (
            self._db.table("content_bucket_categorizations")
            .select("session_id, created_at")
            .eq("product_id", product_id)
        )
        if org_id != "all":
            query = query.eq("organization_id", org_id)
        raw = query.order("created_at", desc=True).limit(200).execute()
        if not raw.data:
            return []

        # Group by session
        sessions: Dict[str, Dict] = {}
        for row in raw.data:
            sid = row["session_id"]
            if sid not in sessions:
                sessions[sid] = {
                    "session_id": sid,
                    "created_at": row["created_at"],
                    "file_count": 0,
                }
            sessions[sid]["file_count"] += 1

        sorted_sessions = sorted(
            sessions.values(), key=lambda s: s["created_at"], reverse=True
        )
        return sorted_sessions[:limit]

    # ─── Uploaded Tracking ─────────────────────────────────────────────

    def mark_as_uploaded(
        self, categorization_ids: List[str], uploaded: bool = True
    ) -> int:
        """Mark categorization records as uploaded (or un-uploaded).

        Args:
            categorization_ids: List of categorization record IDs.
            uploaded: True to mark as uploaded, False to unmark.

        Returns:
            Count of updated records.
        """
        if not categorization_ids:
            return 0

        result = (
            self._db.table("content_bucket_categorizations")
            .update({"is_uploaded": uploaded})
            .in_("id", categorization_ids)
            .execute()
        )
        return len(result.data) if result.data else 0

    def get_uploaded_files(
        self, product_id: str, org_id: str
    ) -> List[Dict[str, Any]]:
        """Get all files marked as uploaded for a product.

        Args:
            product_id: Product ID.
            org_id: Organization ID for multi-tenant filtering.

        Returns:
            List of categorization records ordered by bucket_name, filename.
        """
        query = (
            self._db.table("content_bucket_categorizations")
            .select("*")
            .eq("product_id", product_id)
            .eq("is_uploaded", True)
        )
        if org_id != "all":
            query = query.eq("organization_id", org_id)
        result = query.order("bucket_name").order("filename").execute()
        return result.data or []

    # ─── Helpers ──────────────────────────────────────────────────────

    def _parse_json_response(self, text: str) -> Optional[Dict[str, Any]]:
        """Parse JSON from Gemini response, handling markdown code blocks."""
        if not text:
            return None

        # Try to extract JSON from markdown code block
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if json_match:
            text = json_match.group(1)

        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON response: {e}")
            return None
