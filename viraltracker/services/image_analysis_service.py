"""
ImageAnalysisService — Deep image ad analysis with Gemini.

Extracts messaging themes, emotional tone, persona signals, people in the ad,
hook patterns, visual style, and text overlays from static image ads.

Results are stored in ad_image_analysis table with immutable, versioned rows.
Parallel to VideoAnalysisService for video ads.
"""

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

logger = logging.getLogger(__name__)

PROMPT_VERSION = "v1"

IMAGE_ANALYSIS_PROMPT = """Analyze this image advertisement and extract detailed structured data.

**AD COPY (for context):**
{ad_copy}

**EXTRACT THE FOLLOWING (return as JSON):**

```json
{{
  "messaging_theme": "<core message or proposition of the ad in one sentence>",

  "emotional_tone": ["<primary emotion>", "<secondary emotion>"],
  // Options: fear, aspiration, urgency, empathy, humor, curiosity, anger, joy,
  //          trust, authority, scarcity, social_proof, nostalgia, relief, pride

  "hook_pattern": "<question|statement|testimonial|statistic|story|before_after|callout|transformation|shock>",

  "cta_style": "<direct|soft|curiosity|none>",
  // direct = "Buy Now", "Shop Today"
  // soft = "Learn More", "See How"
  // curiosity = "Find Out Why", "See What Happened"
  // none = no visible CTA

  "benefits_shown": ["benefit 1", "benefit 2"],
  "pain_points_addressed": ["pain point 1", "pain point 2"],
  "claims_made": [
    {{"claim": "...", "proof_shown": true}}
  ],

  "headline_text": "<primary headline or text overlay, or null if none>",
  "body_text": "<secondary text, or null if none>",
  "text_overlays": [
    {{"text": "...", "position": "top|center|bottom", "style": "bold|regular|handwritten"}}
  ],

  "people_in_ad": [
    {{
      "role": "<spokesperson|customer_testimonial|lifestyle_model|ugc_creator|founder|expert|none>",
      "age_range": "<18-24|25-34|35-44|45-54|55-64|65+>",
      "gender": "<male|female|non_binary|unclear>",
      "description": "<brief description: what they're doing, expression, setting>"
    }}
  ],
  // If no people visible, return empty array []

  "target_persona_signals": {{
    "age_group": "<target age range>",
    "gender_signals": "<who this ad seems aimed at>",
    "pain_points": ["<pain points this persona has>"],
    "aspirations": ["<what this persona wants>"],
    "lifestyle": "<lifestyle indicators>"
  }},

  "visual_style": {{
    "color_mood": "<warm|cool|neutral|vibrant|muted|dark>",
    "imagery_type": "<product_hero|lifestyle|before_after|infographic|testimonial_card|ugc|meme|screenshot>",
    "setting": "<studio|home|outdoor|office|gym|kitchen|bathroom|bedroom|none>",
    "production_quality": "<raw|polished|professional>",
    "composition": "<centered|rule_of_thirds|text_heavy|image_heavy|split|collage>"
  }},

  "awareness_level": "<unaware|problem_aware|solution_aware|product_aware|most_aware>",
  "awareness_confidence": 0.85
}}
```

**IMPORTANT:**
- Be specific about messaging_theme — what is this ad actually saying?
- For people_in_ad, describe what you see: role, approximate age, gender, what they're doing
- If text is present in the image, extract it accurately
- Return ONLY valid JSON, no additional text
"""


@dataclass
class ImageAnalysisResult:
    """Result of deep image analysis."""
    meta_ad_id: str
    brand_id: UUID
    input_hash: str
    prompt_version: str

    # Status
    status: str = "ok"
    error_message: Optional[str] = None

    # Messaging
    messaging_theme: Optional[str] = None
    emotional_tone: List[str] = field(default_factory=list)
    hook_pattern: Optional[str] = None
    cta_style: Optional[str] = None
    benefits_shown: List[str] = field(default_factory=list)
    pain_points_addressed: List[str] = field(default_factory=list)
    claims_made: Optional[List[Dict]] = None

    # Text
    headline_text: Optional[str] = None
    body_text: Optional[str] = None
    text_overlays: List[Dict] = field(default_factory=list)

    # People
    people_in_ad: List[Dict] = field(default_factory=list)

    # Persona
    target_persona_signals: Optional[Dict] = None

    # Visual
    visual_style: Optional[Dict] = None

    # Psychology
    awareness_level: Optional[str] = None
    awareness_confidence: Optional[float] = None

    # Provenance
    raw_analysis: Optional[Dict] = None
    model_used: Optional[str] = None
    source_url: Optional[str] = None


class ImageAnalysisService:
    """Deep image ad analysis using Gemini vision."""

    def __init__(self, supabase_client=None):
        if supabase_client:
            self.supabase = supabase_client
        else:
            from viraltracker.core.database import get_supabase_client
            self.supabase = get_supabase_client()

    def analyze_image(
        self,
        meta_ad_id: str,
        brand_id: UUID,
        organization_id: UUID,
        ad_copy: Optional[str] = None,
    ) -> Optional[ImageAnalysisResult]:
        """Analyze a single image ad with Gemini.

        Tries stored image first, falls back to thumbnail URL.
        Deduplicates via input_hash + prompt_version.

        Args:
            meta_ad_id: Meta ad ID.
            brand_id: Brand UUID.
            organization_id: Organization UUID.
            ad_copy: Ad copy text for context.

        Returns:
            ImageAnalysisResult on success, None if no image available.
        """
        try:
            # 1. Get image data
            image_bytes, source_url = self._get_image(meta_ad_id, brand_id)
            if not image_bytes:
                return None

            # 2. Compute input hash for dedup
            input_hash = hashlib.sha256(image_bytes[:10000]).hexdigest()

            # 3. Check existing analysis
            existing = self._check_existing(meta_ad_id, brand_id, input_hash)
            if existing:
                logger.info(f"Image analysis already exists for {meta_ad_id}")
                return existing

            # 4. Call Gemini
            from google import genai
            from google.genai import types

            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                return ImageAnalysisResult(
                    meta_ad_id=meta_ad_id,
                    brand_id=brand_id,
                    input_hash=input_hash,
                    prompt_version=PROMPT_VERSION,
                    status="error",
                    error_message="GEMINI_API_KEY not set",
                )

            client = genai.Client(api_key=api_key)
            prompt = IMAGE_ANALYSIS_PROMPT.format(
                ad_copy=ad_copy or "(no copy available)"
            )

            # Detect mime type
            mime_type = "image/jpeg"
            if image_bytes[:4] == b'\x89PNG':
                mime_type = "image/png"
            elif image_bytes[:4] == b'RIFF':
                mime_type = "image/webp"

            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                    prompt,
                ],
            )

            # 5. Parse response
            result_text = response.text.strip() if response.text else ""
            parsed = self._parse_response(result_text)

            if not parsed:
                return ImageAnalysisResult(
                    meta_ad_id=meta_ad_id,
                    brand_id=brand_id,
                    input_hash=input_hash,
                    prompt_version=PROMPT_VERSION,
                    status="error",
                    error_message="Failed to parse Gemini response",
                    raw_analysis={"raw_text": result_text[:5000]},
                )

            # 6. Build result
            result = ImageAnalysisResult(
                meta_ad_id=meta_ad_id,
                brand_id=brand_id,
                input_hash=input_hash,
                prompt_version=PROMPT_VERSION,
                status="ok",
                messaging_theme=parsed.get("messaging_theme"),
                emotional_tone=parsed.get("emotional_tone", []),
                hook_pattern=parsed.get("hook_pattern"),
                cta_style=parsed.get("cta_style"),
                benefits_shown=parsed.get("benefits_shown", []),
                pain_points_addressed=parsed.get("pain_points_addressed", []),
                claims_made=parsed.get("claims_made"),
                headline_text=parsed.get("headline_text"),
                body_text=parsed.get("body_text"),
                text_overlays=parsed.get("text_overlays", []),
                people_in_ad=parsed.get("people_in_ad", []),
                target_persona_signals=parsed.get("target_persona_signals"),
                visual_style=parsed.get("visual_style"),
                awareness_level=parsed.get("awareness_level"),
                awareness_confidence=parsed.get("awareness_confidence"),
                raw_analysis=parsed,
                model_used="gemini-2.5-flash",
                source_url=source_url,
            )

            # 7. Store result
            self._store_result(result, organization_id)

            logger.info(
                f"Image analysis complete for {meta_ad_id}: "
                f"theme={result.messaging_theme}, "
                f"tone={result.emotional_tone}, "
                f"people={len(result.people_in_ad)}"
            )

            return result

        except Exception as e:
            logger.error(f"Image analysis failed for {meta_ad_id}: {e}")
            return None

    def analyze_batch(
        self,
        brand_id: UUID,
        organization_id: UUID,
        max_new: int = 100,
        days_back: int = 30,
    ) -> Dict[str, Any]:
        """Analyze unanalyzed image ads in batch.

        Finds ads with stored images or thumbnails that haven't been
        deep-analyzed yet. Processes up to max_new.

        Args:
            brand_id: Brand UUID.
            organization_id: Organization UUID.
            max_new: Maximum new analyses per run.
            days_back: Look-back window for active ads.

        Returns:
            Summary dict with counts.
        """
        from datetime import timedelta

        cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")

        # Get active non-video ads for this brand
        ads = self.supabase.table("meta_ads_performance").select(
            "meta_ad_id, thumbnail_url, ad_copy"
        ).eq(
            "brand_id", str(brand_id)
        ).gte(
            "date", cutoff
        ).eq(
            "is_video", False
        ).execute()

        if not ads.data:
            return {"analyzed": 0, "skipped": 0, "errors": 0, "message": "No image ads found"}

        # Deduplicate by meta_ad_id, keep latest copy
        ad_map = {}
        for ad in ads.data:
            ad_map[ad["meta_ad_id"]] = ad

        # Get already-analyzed ad IDs
        existing = self.supabase.table("ad_image_analysis").select(
            "meta_ad_id"
        ).eq(
            "brand_id", str(brand_id)
        ).eq(
            "prompt_version", PROMPT_VERSION
        ).execute()
        existing_ids = {r["meta_ad_id"] for r in (existing.data or [])}

        # Filter to unanalyzed
        to_analyze = [
            ad for mid, ad in ad_map.items()
            if mid not in existing_ids
        ][:max_new]

        analyzed = 0
        skipped = 0
        errors = 0

        for ad in to_analyze:
            result = self.analyze_image(
                meta_ad_id=ad["meta_ad_id"],
                brand_id=brand_id,
                organization_id=organization_id,
                ad_copy=ad.get("ad_copy"),
            )

            if result is None:
                skipped += 1
            elif result.status == "error":
                errors += 1
            else:
                analyzed += 1

        return {
            "analyzed": analyzed,
            "skipped": skipped,
            "errors": errors,
            "total_candidates": len(to_analyze),
        }

    def _get_image(
        self,
        meta_ad_id: str,
        brand_id: UUID,
    ) -> Tuple[Optional[bytes], Optional[str]]:
        """Get image bytes from storage or thumbnail URL.

        Returns:
            (image_bytes, source_url) tuple. Both None if no image.
        """
        # 1. Try stored image
        try:
            asset = self.supabase.table("meta_ad_assets").select(
                "storage_path, source_url"
            ).eq(
                "meta_ad_id", meta_ad_id
            ).eq(
                "asset_type", "image"
            ).eq(
                "status", "downloaded"
            ).limit(1).execute()

            if asset.data:
                storage_path = asset.data[0]["storage_path"]
                parts = storage_path.split("/", 1)
                if len(parts) == 2:
                    content = self.supabase.storage.from_(parts[0]).download(parts[1])
                    if content:
                        return content, storage_path
        except Exception as e:
            logger.debug(f"Storage fetch failed for {meta_ad_id}: {e}")

        # 2. Fall back to thumbnail URL
        try:
            perf = self.supabase.table("meta_ads_performance").select(
                "thumbnail_url"
            ).eq(
                "meta_ad_id", meta_ad_id
            ).not_.is_(
                "thumbnail_url", "null"
            ).limit(1).execute()

            if perf.data and perf.data[0].get("thumbnail_url"):
                import urllib.request
                url = perf.data[0]["thumbnail_url"]
                with urllib.request.urlopen(url, timeout=10) as resp:
                    image_bytes = resp.read()
                if image_bytes:
                    return image_bytes, url
        except Exception as e:
            logger.debug(f"Thumbnail fetch failed for {meta_ad_id}: {e}")

        return None, None

    def _check_existing(
        self,
        meta_ad_id: str,
        brand_id: UUID,
        input_hash: str,
    ) -> Optional[ImageAnalysisResult]:
        """Check if analysis already exists for this ad+hash+version."""
        try:
            result = self.supabase.table("ad_image_analysis").select(
                "*"
            ).eq(
                "meta_ad_id", meta_ad_id
            ).eq(
                "brand_id", str(brand_id)
            ).eq(
                "input_hash", input_hash
            ).eq(
                "prompt_version", PROMPT_VERSION
            ).limit(1).execute()

            if not result.data:
                return None

            row = result.data[0]
            return ImageAnalysisResult(
                meta_ad_id=row["meta_ad_id"],
                brand_id=UUID(row["brand_id"]),
                input_hash=row["input_hash"],
                prompt_version=row["prompt_version"],
                status=row.get("status", "ok"),
                error_message=row.get("error_message"),
                messaging_theme=row.get("messaging_theme"),
                emotional_tone=row.get("emotional_tone") or [],
                hook_pattern=row.get("hook_pattern"),
                cta_style=row.get("cta_style"),
                benefits_shown=row.get("benefits_shown") or [],
                pain_points_addressed=row.get("pain_points_addressed") or [],
                claims_made=row.get("claims_made"),
                headline_text=row.get("headline_text"),
                body_text=row.get("body_text"),
                text_overlays=row.get("text_overlays") or [],
                people_in_ad=row.get("people_in_ad") or [],
                target_persona_signals=row.get("target_persona_signals"),
                visual_style=row.get("visual_style"),
                awareness_level=row.get("awareness_level"),
                awareness_confidence=row.get("awareness_confidence"),
                raw_analysis=row.get("raw_analysis"),
                model_used=row.get("model_used"),
                source_url=row.get("source_url"),
            )

        except Exception as e:
            logger.warning(f"Error checking existing analysis for {meta_ad_id}: {e}")
            return None

    def _store_result(
        self,
        result: ImageAnalysisResult,
        organization_id: UUID,
    ) -> None:
        """Store analysis result in ad_image_analysis table."""
        try:
            self.supabase.table("ad_image_analysis").insert({
                "organization_id": str(organization_id),
                "brand_id": str(result.brand_id),
                "meta_ad_id": result.meta_ad_id,
                "input_hash": result.input_hash,
                "prompt_version": result.prompt_version,
                "status": result.status,
                "error_message": result.error_message,
                "messaging_theme": result.messaging_theme,
                "emotional_tone": result.emotional_tone,
                "hook_pattern": result.hook_pattern,
                "cta_style": result.cta_style,
                "benefits_shown": result.benefits_shown,
                "pain_points_addressed": result.pain_points_addressed,
                "claims_made": result.claims_made,
                "headline_text": result.headline_text,
                "body_text": result.body_text,
                "text_overlays": result.text_overlays,
                "people_in_ad": result.people_in_ad,
                "target_persona_signals": result.target_persona_signals,
                "visual_style": result.visual_style,
                "awareness_level": result.awareness_level,
                "awareness_confidence": result.awareness_confidence,
                "raw_analysis": result.raw_analysis,
                "model_used": result.model_used,
                "source_url": result.source_url,
            }).execute()
        except Exception as e:
            if "23505" in str(e):  # unique violation — already exists
                pass
            else:
                logger.error(f"Failed to store image analysis for {result.meta_ad_id}: {e}")

    def _parse_response(self, text: str) -> Optional[Dict]:
        """Parse JSON response from Gemini, handling markdown code blocks."""
        if not text:
            return None

        # Strip markdown code blocks
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            # Remove first line (```json) and last line (```)
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # Try to find JSON in the response
            match = re.search(r'\{[\s\S]*\}', cleaned)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass

            logger.warning(f"Failed to parse Gemini response as JSON: {cleaned[:200]}")
            return None
