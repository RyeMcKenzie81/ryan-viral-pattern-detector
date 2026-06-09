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

from .awareness_rubric import AWARENESS_RUBRIC

logger = logging.getLogger(__name__)

# v2: awareness_level is now judged by the shared Schwartz AWARENESS_RUBRIC, from the
# ON-IMAGE text/visual only (creative awareness; the surrounding FB caption is judged
# separately as copy awareness). Bumping this re-analyzes image ads onto the calibrated
# rubric (the image-version staleness gate in the classifier keys on it).
PROMPT_VERSION = "v2"

# Image awareness model. Was hardcoded gemini-2.5-flash; promoted to a named constant
# and upgraded to gemini-pro-latest for consistency with the video path and to honor
# the rubric calibration (which was hand-validated on pro-latest).
IMAGE_ANALYSIS_MODEL = "gemini-pro-latest"

# The 5 canonical Schwartz awareness levels — the ONLY values allowed by the
# ad_image_analysis.awareness_level and ad_creative_classifications.creative_awareness_level
# DB CHECK constraints. Gemini occasionally drifts off-format (e.g. "Product Aware",
# a trailing space, a hallucinated 6th label); normalizing at the trust boundary keeps
# the stored row valid (NULL on a miss) instead of throwing a CHECK violation — which
# would otherwise drop the analysis row, leave analysis_id unset, and re-bill every run.
VALID_AWARENESS_LEVELS = frozenset(
    {"unaware", "problem_aware", "solution_aware", "product_aware", "most_aware"}
)


def _normalize_awareness_level(value):
    """Lower/strip/space->underscore an awareness label; return None if not canonical."""
    if not value or not isinstance(value, str):
        return None
    norm = value.strip().lower().replace(" ", "_")
    return norm if norm in VALID_AWARENESS_LEVELS else None


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

**AWARENESS — how to set `awareness_level` (read carefully):**
A static ad is a SINGLE moment (no opening/ending). Judge `awareness_level` by what the DOMINANT readable on-image element presumes the viewer knows — the headline / hero text / offer in its visual hierarchy, NOT every tiny text block weighted equally. Judge from the ON-IMAGE text + visual ONLY: the AD COPY above is the surrounding Facebook caption — use it for messaging_theme / persona context, but do NOT let it set `awareness_level` (caption awareness is judged separately). If the on-image text is too small or dense to read reliably, LOWER `awareness_confidence` and do NOT hallucinate text you cannot actually see.

Static-format tells:
- PROMINENT BRANDED PRODUCT (decisive): when the visual CENTER is a branded product shot (the bottle/pack is the hero, with a brand name or logo visible), tag product_aware — EVEN IF the headline is a problem hook ("Feeling tired?", "IBS?"), a solution mechanism ("reduce cortisol", "not a sleep pill"), or an educational listicle ("7 Reasons... this supplement"). Showing the specific branded bottle ties the problem/mechanism directly to THIS product instead of teaching the category, so it is the DOMINANT signal. Product-level proof (specific claims, a customer review like "Karen T., Ohio", authority markers like "Doctor-formulated" or a founder signature, competitor differentiation, or a listicle/"This [product]" reference) reinforces it, but the prominent branded product shot alone is enough. Scan the WHOLE frame for it: a prominent branded bottle/pack is decisive even when it sits ALONGSIDE a cartoon, before/after panels, or a lifestyle scene (a composite ad is still product_aware if it features the branded bottle). (Still not most_aware unless the LEAD is an explicit offer/price/urgency.)
- COUNTER-EXAMPLES (no prominent branded product): the same mechanism/category message ("not a sleep pill", "natural cortisol supplement") on a LIFESTYLE image with NO bottle and no brand/logo stays solution_aware. A PURE SYMPTOM visual (a 3 AM clock, an exhausted person) with NO text, mechanism, or product/brand is problem_aware.
- product-hero (product + name): only the product on a neutral background -> judge by visual context (paired with a PROBLEM visual = problem_aware; with a DESIRED-STATE visual or shown as the answer = product_aware; bare packshot led by a price/offer = most_aware).
- before/after: if a prominent branded product/bottle appears anywhere in the frame, product_aware (the bottle overrides the before/after framing, per the decisive rule above). With NO product shown: a visual transformation alone = product_aware; a mechanism / explanatory lead = solution_aware.
- pure offer (discount / %-off / urgency / "back in stock" as the LEAD) = most_aware.
- listicle / article-style headline ("5 signs your gut is damaged", "the real reason you're tired") = problem_aware (or unaware if pure curiosity with no felt problem).
- long advertorial / sales image: judge by the HEADLINE / lead, not the body.
- review or testimonial screenshot: route by CONTENT — pain only = problem_aware; a category/ingredient = solution_aware; the BRAND named = product_aware.
- blind hook (meme / relatable / emotional narrative — e.g. a bathroom-embarrassment sticky note — that explicitly NAMES a solution category or mechanism like "Probiotics" or "cortisol reducer" but shows NO brand, logo, or identifiable product packaging): solution_aware. The named category/mechanism overrides the emotional/symptom framing, and the hidden brand keeps it below product. (A meme that names NO category and shows no product stays problem_aware.)
- objection-handling / hidden-product authority: if the copy's primary job is to DEFEND or DIFFERENTIATE a specific product — "what makes THIS one different?", unique authority / manufacturing claims ("crafted from 45 years of patient care by a real clinic", "doctor-formulated"), or pitting "this one" against the rest of the market — tag product_aware EVEN IF the brand, logo, and bottle are intentionally hidden (a curiosity / retargeting play). Distinguish from the blind hook above: a blind hook NAMES a category to sell the concept (-> solution); this DEFENDS a specific product's uniqueness/authority (-> product).
- comparison chart (this product vs named rivals) = product_aware.

{awareness_rubric}

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
    analysis_id: Optional[UUID] = None  # ad_image_analysis row id (set on save/fetch; links the classification)
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
        store: bool = True,
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

            # 1b. Guard against low-res thumbnails. Some early-batch assets were stored
            # as 64x64 (the captured thumbnail_url IS 64x64) — unreadable, so a confident
            # awareness off them is garbage. Mark low_res and emit NO awareness; the
            # classifier treats this like a missing image (skip), and the digest never
            # buckets it. These ads need a high-res re-fetch from Meta to classify.
            if self._image_too_small(image_bytes):
                logger.info(f"Image too low-res to classify for {meta_ad_id}")
                return ImageAnalysisResult(
                    meta_ad_id=meta_ad_id,
                    brand_id=brand_id,
                    input_hash=hashlib.sha256(image_bytes[:10000]).hexdigest(),
                    prompt_version=PROMPT_VERSION,
                    status="low_res",
                    error_message="image too low-res to classify (likely a 64x64 thumbnail)",
                    awareness_confidence=0.0,
                    source_url=source_url,
                )

            # 2. Compute input hash for dedup
            input_hash = hashlib.sha256(image_bytes[:10000]).hexdigest()

            # 3. Check existing analysis
            existing = self._check_existing(meta_ad_id, brand_id, input_hash)
            if existing:
                logger.info(f"Image analysis already exists for {meta_ad_id}")
                return existing

            # 4. Call Gemini
            # NOTE: make_genai_client was used below but never imported (PR #180
            # regression, same as video_analysis_service + classifier_service) —
            # left this whole service raising NameError on every call.
            from google.genai import types
            from ..core.genai_client import make_genai_client

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

            client = make_genai_client(api_key)
            prompt = IMAGE_ANALYSIS_PROMPT.format(
                ad_copy=ad_copy or "(no copy available)",
                awareness_rubric=AWARENESS_RUBRIC,
            )

            # Detect mime type
            mime_type = "image/jpeg"
            if image_bytes[:4] == b'\x89PNG':
                mime_type = "image/png"
            elif image_bytes[:4] == b'RIFF':
                mime_type = "image/webp"

            response = client.models.generate_content(
                model=IMAGE_ANALYSIS_MODEL,
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
                # Normalize to a canonical enum value (or None) so the stored row and
                # every downstream insert satisfy the awareness_level CHECK constraints.
                awareness_level=_normalize_awareness_level(parsed.get("awareness_level")),
                awareness_confidence=parsed.get("awareness_confidence"),
                raw_analysis=parsed,
                model_used=IMAGE_ANALYSIS_MODEL,
                source_url=source_url,
            )

            # 7. Store result (skipped for preview/eval runs)
            if store:
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
                analysis_id=UUID(row["id"]) if row.get("id") else None,
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
        """Store analysis result in ad_image_analysis table; set result.analysis_id."""
        try:
            resp = self.supabase.table("ad_image_analysis").insert({
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
            if resp.data:
                result.analysis_id = UUID(resp.data[0]["id"])
        except Exception as e:
            if "23505" in str(e):  # unique violation — already exists; fetch its id so the link resolves
                try:
                    ex = self.supabase.table("ad_image_analysis").select("id").eq(
                        "meta_ad_id", result.meta_ad_id
                    ).eq("brand_id", str(result.brand_id)).eq(
                        "input_hash", result.input_hash
                    ).eq("prompt_version", result.prompt_version).limit(1).execute()
                    if ex.data:
                        result.analysis_id = UUID(ex.data[0]["id"])
                except Exception:
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

    @staticmethod
    def _image_too_small(image_bytes: bytes, min_dim: int = 256) -> bool:
        """True if the image's largest side is < min_dim px (an unreadable thumbnail).

        Some early-batch assets were stored as 64x64. Falls back to a byte-size proxy
        if PIL is unavailable (64x64 thumbnails are ~4-12 KB; real creatives are 50KB+).
        """
        try:
            import io as _io
            from PIL import Image
            with Image.open(_io.BytesIO(image_bytes)) as im:
                return max(im.width, im.height) < min_dim
        except Exception:
            return len(image_bytes) < 12000
