"""
ContentBucketService — Bucket CRUD + Gemini video analysis + categorization.

Organizes bulk video uploads into user-defined "content buckets" for
Facebook ad campaigns. Uses Gemini Files API for video analysis and
text-only Gemini calls for bucket categorization.
"""

import json
import logging
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

VIDEO_ANALYSIS_PROMPT = """Analyze this video and return a JSON object with the following fields:

{
  "transcript": "Full transcript of all spoken words",
  "text_overlays": ["List of all text shown on screen"],
  "video_summary": "2-3 sentence summary of the video content and message",
  "hook": "The opening hook or attention-grabber (first 3-5 seconds)",
  "pain_points": ["Pain points addressed in the video"],
  "benefits": ["Benefits or solutions presented"],
  "solution": "The main solution or product positioning",
  "tone": "Overall tone (e.g., urgent, educational, testimonial, emotional)",
  "format_type": "Video format (e.g., UGC, talking head, slideshow, B-roll, before/after)",
  "key_themes": ["Main themes or topics covered"]
}

Return ONLY the JSON object, no other text."""

CATEGORIZATION_PROMPT_TEMPLATE = """You are a video content categorizer for Facebook ad campaigns.

Given a video analysis and a set of content buckets, determine which bucket is the BEST fit.

## Video Analysis
{video_analysis}

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
    """Service for content bucket management and video categorization."""

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
            best_for: What types of videos belong here.
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

    # ─── Video Analysis ───────────────────────────────────────────────

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
            Dict with analysis fields (transcript, video_summary, etc.)
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

    def categorize_video(
        self, analysis: Dict[str, Any], buckets: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Categorize a video into a bucket using text-only Gemini call.

        Args:
            analysis: Video analysis dict from analyze_video().
            buckets: List of bucket dicts from get_buckets().

        Returns:
            Dict with bucket_name, confidence_score, reasoning.
        """
        from google import genai

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return {"bucket_name": "Uncategorized", "confidence_score": 0.0,
                    "reasoning": "GEMINI_API_KEY not set"}

        # Build video analysis summary
        video_summary = (
            f"Summary: {analysis.get('video_summary', 'N/A')}\n"
            f"Hook: {analysis.get('hook', 'N/A')}\n"
            f"Tone: {analysis.get('tone', 'N/A')}\n"
            f"Format: {analysis.get('format_type', 'N/A')}\n"
            f"Pain Points: {', '.join(analysis.get('pain_points', []))}\n"
            f"Benefits: {', '.join(analysis.get('benefits', []))}\n"
            f"Solution: {analysis.get('solution', 'N/A')}\n"
            f"Key Themes: {', '.join(analysis.get('key_themes', []))}\n"
            f"Transcript excerpt: {(analysis.get('transcript', '') or '')[:500]}"
        )

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
            video_analysis=video_summary,
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
    ) -> List[Dict[str, Any]]:
        """Process a batch of videos: analyze each then categorize.

        Processes sequentially with 7s delay between videos to respect
        Gemini rate limits (9 req/min). Continues on error.

        Args:
            files: List of dicts with 'bytes', 'name', 'type' keys.
            buckets: List of bucket dicts.
            product_id: Product ID.
            org_id: Organization ID.
            session_id: UUID grouping this upload batch.
            progress_callback: Optional fn(index, total, filename, status_msg).

        Returns:
            List of result dicts for each video.
        """
        resolved_org = self._resolve_org_id(org_id, product_id)
        results = []
        total = len(files)

        # Build bucket lookup by name
        bucket_lookup = {b["name"]: b["id"] for b in buckets}

        for i, file_info in enumerate(files):
            filename = file_info["name"]

            if progress_callback:
                progress_callback(i, total, filename, "Analyzing video...")

            # Step 1: Analyze video
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
                }
                self._db.table("video_bucket_categorizations").insert(record).execute()
                results.append({"filename": filename, "status": "error",
                                "error": analysis["error"]})

                if progress_callback:
                    progress_callback(i, total, filename, f"Error: {analysis['error'][:100]}")

                # Still delay before next video
                if i < total - 1:
                    time.sleep(7)
                continue

            if progress_callback:
                progress_callback(i, total, filename, "Categorizing...")

            # Step 2: Categorize (text-only call)
            categorization = self.categorize_video(analysis, buckets)

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
                "video_summary": analysis.get("video_summary", ""),
                "transcript": analysis.get("transcript", ""),
                "analysis_data": json.dumps(analysis),
                "status": "categorized" if bucket_id else "analyzed",
                "session_id": session_id,
            }
            self._db.table("video_bucket_categorizations").insert(record).execute()

            result = {
                "filename": filename,
                "status": "categorized",
                "bucket_name": bucket_name,
                "confidence_score": confidence,
                "reasoning": categorization.get("reasoning", ""),
                "video_summary": analysis.get("video_summary", ""),
            }
            results.append(result)

            if progress_callback:
                progress_callback(
                    i, total, filename,
                    f"Categorized → {bucket_name} ({confidence:.0%})"
                )

            # Rate limit delay (skip after last video)
            if i < total - 1:
                time.sleep(7)

        return results

    # ─── Results ──────────────────────────────────────────────────────

    def delete_categorization(self, session_id: str, filename: str) -> bool:
        """Delete a categorization record by session + filename (for retry).

        Args:
            session_id: Session UUID.
            filename: Original filename of the video.

        Returns:
            True after deletion.
        """
        self._db.table("video_bucket_categorizations") \
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
            self._db.table("video_bucket_categorizations")
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
            List of dicts with session_id, created_at, video_count.
        """
        query = (
            self._db.table("video_bucket_categorizations")
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
                    "video_count": 0,
                }
            sessions[sid]["video_count"] += 1

        sorted_sessions = sorted(
            sessions.values(), key=lambda s: s["created_at"], reverse=True
        )
        return sorted_sessions[:limit]

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
