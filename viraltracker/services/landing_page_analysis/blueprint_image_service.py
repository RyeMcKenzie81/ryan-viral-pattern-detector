"""
BlueprintImageService — Context-aware AI image replacement for blueprint mockups.

Two-phase workflow:
1. ANALYZE: Extract image slots from HTML, download originals, run Vision analysis
2. GENERATE: Build narrative prompts, generate with Gemini 3 Pro, replace in HTML

Each image slot tracks its own metadata for selective per-image regeneration.
"""

import asyncio
import base64
import html as _html_module
import json
import logging
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from io import BytesIO
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Standard aspect ratios for snapping detected dimensions
STANDARD_RATIOS = {
    (16, 9): "16:9",
    (9, 16): "9:16",
    (4, 3): "4:3",
    (3, 4): "3:4",
    (3, 2): "3:2",
    (2, 3): "2:3",
    (1, 1): "1:1",
    (21, 9): "21:9",
}


def snap_aspect_ratio(width: int, height: int) -> str:
    """Snap image dimensions to the nearest standard aspect ratio."""
    if width <= 0 or height <= 0:
        return "1:1"
    ratio = width / height
    best = "1:1"
    best_diff = float("inf")
    for (w, h), label in STANDARD_RATIOS.items():
        diff = abs(ratio - w / h)
        if diff < best_diff:
            best_diff = diff
            best = label
    return best


@dataclass
class ImageSlot:
    """Represents a single <img> tag in the blueprint HTML."""

    index: int
    original_src: str
    alt_text: str
    surrounding_text: str
    section_heading: str
    original_base64: Optional[str] = None
    image_analysis: Optional[dict] = None
    scene_direction: Optional[dict] = None
    aspect_ratio: Optional[str] = None
    prompt: Optional[str] = None
    generated_base64: Optional[str] = None
    storage_url: Optional[str] = None
    error: Optional[str] = None
    selected: bool = True


# ---------------------------------------------------------------------------
# HTML Parsers
# ---------------------------------------------------------------------------

class _ImageContextExtractor(HTMLParser):
    """Walk HTML, extract <img> tags with surrounding text context."""

    def __init__(self):
        super().__init__()
        self.slots: List[ImageSlot] = []
        self._img_index = 0
        self._current_section_text: List[str] = []
        self._current_heading = ""
        self._in_heading = False
        self._heading_tag = ""

    def _process_img(self, attrs_dict: dict):
        """Process an <img> tag, always incrementing the DOM-order counter."""
        src = attrs_dict.get("src", "")
        alt = attrs_dict.get("alt", "")
        width = attrs_dict.get("width", "")
        height = attrs_dict.get("height", "")

        # Always capture current index, then increment (must match _SrcReplacer)
        current_index = self._img_index
        self._img_index += 1

        # Filter out small icons
        try:
            if width and height and int(width) < 48 and int(height) < 48:
                return
        except (ValueError, TypeError):
            pass

        # Validate URL
        if not src:
            return
        if not self._is_valid_image_url(src):
            return

        slot = ImageSlot(
            index=current_index,
            original_src=src,
            alt_text=alt,
            surrounding_text=" ".join(self._current_section_text[-20:]).strip()[:500],
            section_heading=self._current_heading,
        )
        self.slots.append(slot)

    def handle_starttag(self, tag: str, attrs: list):
        attrs_dict = dict(attrs)

        # Track section headings
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._in_heading = True
            self._heading_tag = tag

        # Track data-section for context
        if attrs_dict.get("data-slot", "").startswith("heading-"):
            # This is a heading slot — capture text
            pass

        if tag == "img":
            self._process_img(attrs_dict)

    def handle_startendtag(self, tag: str, attrs: list):
        """Handle self-closing <img /> tags (XHTML style)."""
        if tag == "img":
            self._process_img(dict(attrs))
        # Track headings that might be self-closing (unlikely but safe)
        attrs_dict = dict(attrs)
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            text = attrs_dict.get("title", "")
            if text:
                self._current_heading = text

    def handle_endtag(self, tag: str):
        if tag == self._heading_tag and self._in_heading:
            self._in_heading = False
            self._heading_tag = ""

    def handle_data(self, data: str):
        text = data.strip()
        if text:
            self._current_section_text.append(text)
            if self._in_heading:
                self._current_heading = text

    def _is_valid_image_url(self, url: str) -> bool:
        """Check if URL is a valid, safe image URL."""
        from viraltracker.services.landing_page_analysis.multipass._url_validator import (
            validate_image_url,
        )

        # Skip remote SVGs (not useful for image generation)
        parsed = urlparse(url)
        if parsed.path.lower().endswith(".svg"):
            return False

        is_safe, _, reason = validate_image_url(url)
        if not is_safe:
            logger.debug(f"Skipping image URL: {reason} — {url[:80]}")
            return False
        return True


class _SrcReplacer(HTMLParser):
    """Replace <img> src attributes by DOM-order index.

    When an <img> inside a <picture> is replaced, the sibling <source>
    elements are dropped so the browser uses the new src instead of the
    original srcset URLs.
    """

    def __init__(self, replacements: Dict[int, str]):
        super().__init__(convert_charrefs=False)
        self._replacements = replacements
        self._img_index = 0
        self._output_parts: List[str] = []
        # <picture> buffering: collect <source> tags until we see the <img>
        self._in_picture = False
        self._picture_buffer: List[str] = []

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _reconstruct_tag(tag: str, attrs: list, self_closing: bool = False) -> str:
        attr_str = ""
        if attrs:
            parts = []
            for name, value in attrs:
                if value is not None:
                    parts.append(f'{name}="{_html_module.escape(value, quote=True)}"')
                else:
                    parts.append(name)
            attr_str = " " + " ".join(parts)
        close = " /" if self_closing else ""
        return f"<{tag}{attr_str}{close}>"

    def _build_replaced_img(self, attrs: list, self_closing: bool = False) -> str:
        """Build an <img> tag with the replacement src for the current index."""
        new_attrs = []
        for name, value in attrs:
            if name == "src":
                new_attrs.append(("src", self._replacements[self._img_index]))
            elif name == "srcset":
                continue  # drop srcset on replaced <img> too
            else:
                new_attrs.append((name, value))
        attr_str = " ".join(
            f'{n}="{_html_module.escape(v, quote=True)}"' if v is not None else n
            for n, v in new_attrs
        )
        close = " /" if self_closing else ""
        return f"<img {attr_str}{close}>"

    def _flush_picture_buffer(self):
        """Emit buffered <source> tags (used when <img> is NOT replaced)."""
        self._output_parts.extend(self._picture_buffer)
        self._picture_buffer = []

    def _drop_picture_buffer(self):
        """Discard buffered <source> tags (used when <img> IS replaced)."""
        self._picture_buffer = []

    def _emit(self, html: str):
        """Append to output, respecting picture buffering for <source> tags."""
        self._output_parts.append(html)

    # -- HTMLParser callbacks ----------------------------------------------

    def handle_starttag(self, tag: str, attrs: list):
        if tag == "picture":
            self._in_picture = True
            self._picture_buffer = []
            self._emit(self._reconstruct_tag(tag, attrs))
            return

        if tag == "source" and self._in_picture:
            # Buffer <source> — we decide whether to keep or drop at <img>
            self._picture_buffer.append(self._reconstruct_tag(tag, attrs))
            return

        if tag == "img":
            if self._img_index in self._replacements:
                if self._in_picture:
                    self._drop_picture_buffer()
                self._emit(self._build_replaced_img(attrs, self_closing=False))
            else:
                if self._in_picture:
                    self._flush_picture_buffer()
                self._emit(self._reconstruct_tag(tag, attrs))
            self._img_index += 1
            return

        self._emit(self._reconstruct_tag(tag, attrs))

    def handle_endtag(self, tag: str):
        if tag == "picture":
            self._flush_picture_buffer()  # flush any remaining
            self._in_picture = False
        self._emit(f"</{tag}>")

    def handle_data(self, data: str):
        if self._in_picture and self._picture_buffer:
            # Whitespace/text between <source> tags — buffer it too
            self._picture_buffer.append(data)
        else:
            self._emit(data)

    def handle_startendtag(self, tag: str, attrs: list):
        if tag == "source" and self._in_picture:
            self._picture_buffer.append(self._reconstruct_tag(tag, attrs, self_closing=True))
            return

        if tag == "img":
            if self._img_index in self._replacements:
                if self._in_picture:
                    self._drop_picture_buffer()
                self._emit(self._build_replaced_img(attrs, self_closing=True))
            else:
                if self._in_picture:
                    self._flush_picture_buffer()
                self._emit(self._reconstruct_tag(tag, attrs, self_closing=True))
            self._img_index += 1
            return

        self._emit(self._reconstruct_tag(tag, attrs, self_closing=True))

    def handle_comment(self, data: str):
        self._emit(f"<!--{data}-->")

    def handle_decl(self, decl: str):
        self._emit(f"<!{decl}>")

    def handle_entityref(self, name: str):
        self._emit(f"&{name};")

    def handle_charref(self, name: str):
        self._emit(f"&#{name};")

    def get_output(self) -> str:
        return "".join(self._output_parts)


def replace_image_sources(html: str, replacements: Dict[int, str]) -> str:
    """Replace <img> src attrs by DOM-order index using HTMLParser (not regex)."""
    replacer = _SrcReplacer(replacements)
    replacer.feed(html)
    return replacer.get_output()


# ---------------------------------------------------------------------------
# Main Service
# ---------------------------------------------------------------------------

VISION_ANALYSIS_PROMPT = """Analyze this image and return a JSON object with these fields:
{
  "image_type": "product_shot|lifestyle|hero_banner|infographic|testimonial_photo|before_after|ingredient|background_texture",
  "subject": "what's in the image",
  "composition": "layout style, colors, mood",
  "has_people": true/false,
  "people_description": "demographics if people present, else empty string",
  "aspect_ratio": "estimated aspect ratio like 16:9"
}
Return ONLY the JSON, no markdown fences or explanation."""


SCENE_DIRECTOR_PROMPT = """You are a Scene Director planning ALL images for a landing page at once.
Your #1 job: make each image illustrate EXACTLY what its surrounding copy says,
and ensure VISUAL VARIETY across the full page.

PRODUCT (for reference only — do NOT default every scene to this):
- Name: {product_name}
- Benefits: {benefits}
- Problems solved: {problems}

TARGET CUSTOMER (use for demographics when showing people):
- Demographics: {persona_demographics}
- Pain symptoms: {pain_symptoms}
- Desired self-image: {desired_self_image}

IMAGE SLOTS TO DIRECT:
{slots_block}

For EACH slot above, return a JSON object. Return a JSON array with one object per slot:
[
  {{
    "slot_index": 0,
    "narrative_role": "solution_state|problem_state|social_proof|lifestyle_aspiration|product_showcase|transformation|educational|hero_attention",
    "scene_description": "One vivid sentence (under 30 words) of the exact scene",
    "emotional_tone": "One or two words: peaceful, energetic, confident, relieved, etc.",
    "setting": "Where: bedroom at dawn, modern kitchen, gym, etc.",
    "activity": "What the subject is doing",
    "key_element_from_copy": "The specific claim from the surrounding text this illustrates",
    "show_product": true/false
  }}
]

CRITICAL RULES:
- Read each slot's heading and copy LITERALLY — the scene must match THAT SPECIFIC text
- VARIETY IS MANDATORY: never assign the same setting or activity to two different slots.
  Mix settings (bedroom, kitchen, office, gym, outdoors, studio, etc.) and
  activities (sleeping, working, exercising, taking pills, reading, etc.)
- Read the heading LITERALLY:
  - "Two Capsules" → show capsules/pills in a hand (product_showcase), NOT a lifestyle scene
  - "Sleep Better" → show someone sleeping peacefully (solution_state)
  - "Real Results" with a quote → show an authentic person (social_proof)
  - "How It Works" → show a process or diagram (educational)
  - "Energy crash" → show the problem state, NOT the solution
- If copy talks about the product form (capsules, pills, powder, dosage, protocol) → use product_showcase
- If copy talks about a symptom or problem → use problem_state, show the struggle
- If copy is a testimonial or quote → use social_proof, show a real person
- Set show_product to true ONLY when the copy specifically mentions the product or its usage
- If no surrounding text, fall back to the original image alt text
- Be specific about demographics only if persona info is provided"""

# Narrative role → photography style prefix mapping
NARRATIVE_ROLE_STYLES = {
    "solution_state": "Realistic lifestyle photo",
    "problem_state": "Authentic documentary-style photo",
    "social_proof": "Genuine natural portrait photo",
    "lifestyle_aspiration": "Aspirational lifestyle photo",
    "product_showcase": "Professional product photography",
    "transformation": "Before-and-after style photo",
    "educational": "Clean infographic-style image",
    "hero_attention": "Wide cinematic hero image",
    "trust_credibility": "Professional authoritative photo",
    "process_explainer": "Clear step-by-step instructional image",
    "objection_handler": "Reassuring, confidence-building photo",
    "pattern_interrupt": "Bold, unexpected attention-grabbing image",
}


class BlueprintImageService:
    """Context-aware AI image replacement for blueprint mockups."""

    def __init__(self, supabase=None):
        from viraltracker.core.database import get_supabase_client

        self.supabase = supabase or get_supabase_client()
        self._tracker = None
        self._user_id: Optional[str] = None
        self._org_id: Optional[str] = None

    def set_tracking_context(self, tracker, user_id: Optional[str], org_id: str):
        """Set usage tracking context for billing."""
        self._tracker = tracker
        self._user_id = user_id
        self._org_id = org_id

    # ------------------------------------------------------------------
    # Phase 1: Analyze
    # ------------------------------------------------------------------

    def extract_image_slots(self, html: str) -> List[ImageSlot]:
        """Parse HTML and extract <img> tags with surrounding context."""
        parser = _ImageContextExtractor()
        parser.feed(html)
        return parser.slots

    async def download_images_parallel(
        self, slots: List[ImageSlot], progress_cb: Optional[Callable] = None
    ) -> int:
        """Download all original images in parallel. Returns count of successful downloads."""
        import httpx
        from PIL import Image

        from viraltracker.services.landing_page_analysis.multipass._url_validator import (
            validate_image_url,
        )

        success_count = 0

        async def _download_one(slot: ImageSlot):
            nonlocal success_count

            # Pre-validate URL
            parsed = urlparse(slot.original_src)
            if parsed.path.lower().endswith(".svg"):
                logger.debug(f"Skipping SVG: {slot.original_src[:80]}")
                return
            is_safe, _, reason = validate_image_url(slot.original_src)
            if not is_safe:
                logger.debug(f"Skipping unsafe URL: {reason}")
                return

            try:
                async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                    resp = await client.get(slot.original_src)
                    resp.raise_for_status()
                    img_bytes = resp.content

                # Detect aspect ratio from image dimensions
                try:
                    img = Image.open(BytesIO(img_bytes))
                    slot.aspect_ratio = snap_aspect_ratio(img.width, img.height)
                except Exception:
                    slot.aspect_ratio = "1:1"

                slot.original_base64 = base64.b64encode(img_bytes).decode("utf-8")
                success_count += 1
            except Exception as e:
                logger.warning(f"Failed to download image {slot.index}: {e}")

        tasks = [_download_one(slot) for slot in slots]
        await asyncio.gather(*tasks)

        if progress_cb:
            progress_cb(-1, len(slots), f"Downloaded {success_count}/{len(slots)} images")

        return success_count

    async def analyze_original_images(
        self,
        slots: List[ImageSlot],
        gemini_service,
        progress_cb: Optional[Callable] = None,
    ) -> List[ImageSlot]:
        """Run Vision analysis on each downloaded image (parallel with semaphore)."""
        sem = asyncio.Semaphore(5)

        async def _analyze_one(slot: ImageSlot):
            if not slot.original_base64:
                # Fallback: use alt text + surrounding context
                slot.image_analysis = {
                    "image_type": "unknown",
                    "subject": slot.alt_text or "unknown",
                    "composition": "unknown",
                    "has_people": False,
                    "people_description": "",
                    "aspect_ratio": slot.aspect_ratio or "1:1",
                }
                return

            async with sem:
                try:
                    if progress_cb:
                        progress_cb(slot.index, len(slots), f"Analyzing image {slot.index + 1}/{len(slots)}")

                    raw = await gemini_service.analyze_image_async(
                        slot.original_base64,
                        VISION_ANALYSIS_PROMPT,
                        skip_internal_rate_limit=True,
                    )

                    # Parse JSON response
                    try:
                        # Strip markdown fences if present
                        text = raw.strip()
                        if text.startswith("```"):
                            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                            if text.endswith("```"):
                                text = text[:-3]
                        slot.image_analysis = json.loads(text.strip())
                    except (json.JSONDecodeError, ValueError):
                        slot.image_analysis = {
                            "image_type": "unknown",
                            "subject": raw[:200] if raw else slot.alt_text,
                            "composition": "unknown",
                            "has_people": False,
                            "people_description": "",
                            "aspect_ratio": slot.aspect_ratio or "1:1",
                        }
                except Exception as e:
                    logger.warning(f"Vision analysis failed for slot {slot.index}: {e}")
                    slot.image_analysis = {
                        "image_type": "unknown",
                        "subject": slot.alt_text or "unknown",
                        "composition": "unknown",
                        "has_people": False,
                        "people_description": "",
                        "aspect_ratio": slot.aspect_ratio or "1:1",
                    }

        tasks = [_analyze_one(slot) for slot in slots]
        await asyncio.gather(*tasks)
        return slots

    # ------------------------------------------------------------------
    # Scene Direction (runs in parallel with Vision)
    # ------------------------------------------------------------------

    async def direct_scenes_for_slots(
        self,
        slots: List[ImageSlot],
        gemini_service,
        product_info: Optional[Dict[str, Any]] = None,
        persona: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Run a single batch Scene Director call for ALL slots at once.

        Sends all slots in one prompt so the LLM can see the full page and
        ensure visual variety across images. Results stored in slot.scene_direction.
        Does NOT call progress_cb to avoid flickering with Vision updates.
        """
        if product_info is None:
            return

        # Filter to slots that have text context
        directable = [s for s in slots if s.surrounding_text or s.section_heading]
        if not directable:
            return

        try:
            prompt = self._build_scene_director_prompt(directable, product_info, persona)
            raw = await gemini_service.analyze_text_async(
                text="",
                prompt=prompt,
                skip_internal_rate_limit=True,
            )

            # Strip markdown fences before parsing
            text = raw.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]

            results = json.loads(text.strip())

            # Map results back to slots by slot_index
            if isinstance(results, list):
                index_map = {s.index: s for s in directable}
                for item in results:
                    if not isinstance(item, dict):
                        continue
                    idx = item.get("slot_index")
                    if idx is not None and idx in index_map:
                        index_map[idx].scene_direction = item
            elif isinstance(results, dict):
                # Single-slot fallback: LLM returned a single object
                if len(directable) == 1:
                    directable[0].scene_direction = results

        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Scene direction batch JSON parse failed: {e}")
        except Exception as e:
            logger.warning(f"Scene direction batch call failed: {e}")

    @staticmethod
    def _build_scene_director_prompt(
        slots: List["ImageSlot"],
        product_info: Dict[str, Any],
        persona: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Format SCENE_DIRECTOR_PROMPT with all slots, product info, and persona."""
        # Product fields
        product_name = product_info.get("name", "the product")
        benefits = ", ".join(product_info.get("key_benefits", [])) or "Not specified"
        problems = ", ".join(product_info.get("key_problems_solved", [])) or "Not specified"

        # Persona fields
        persona_demographics = "Not specified"
        pain_symptoms = "Not specified"
        desired_self_image = "Not specified"
        if persona:
            demographics = persona.get("demographics", {})
            age = demographics.get("age_range", "")
            gender = demographics.get("gender", "")
            if age or gender:
                persona_demographics = f"{age} {gender}".strip()
            pain = persona.get("pain_symptoms", [])
            if pain:
                pain_symptoms = ", ".join(pain[:5]) if isinstance(pain, list) else str(pain)
            desired = persona.get("desired_self_image", "")
            if desired:
                desired_self_image = desired[:200]

        # Build per-slot context block
        slot_lines = []
        for slot in slots:
            analysis = slot.image_analysis or {}
            slot_lines.append(
                f"SLOT {slot.index}:\n"
                f"  Heading: {slot.section_heading or 'None'}\n"
                f"  Copy: {(slot.surrounding_text or 'None')[:300]}\n"
                f"  Alt text: {slot.alt_text or 'None'}\n"
                f"  Original type: {analysis.get('image_type', 'unknown')}\n"
                f"  Has people: {analysis.get('has_people', False)}"
            )
        slots_block = "\n\n".join(slot_lines)

        return SCENE_DIRECTOR_PROMPT.format(
            product_name=product_name,
            benefits=benefits,
            problems=problems,
            persona_demographics=persona_demographics,
            pain_symptoms=pain_symptoms,
            desired_self_image=desired_self_image,
            slots_block=slots_block,
        )

    # ------------------------------------------------------------------
    # Phase 2: Generate
    # ------------------------------------------------------------------

    def build_generation_prompts(
        self,
        slots: List[ImageSlot],
        product_info: Dict[str, Any],
        persona: Optional[Dict[str, Any]] = None,
        brand_profile: Optional[Dict[str, Any]] = None,
    ) -> List[ImageSlot]:
        """Build narrative-style prompts for each image slot.

        Prompts are grounded in the TARGET brand's product info, persona, and
        brand profile — NOT the competitor's original image content.  Vision
        analysis is used only for *composition style* (lighting, angle, layout)
        never for product-specific subject matter.
        """
        product_name = product_info.get("name", "the product")

        # Build a short product description from brand profile fields so
        # the prompt describes the ACTUAL product, not the competitor's.
        product_desc_parts = []
        benefits = product_info.get("key_benefits", [])
        if benefits:
            product_desc_parts.append(benefits[0])
        problems = product_info.get("key_problems_solved", [])
        if problems:
            product_desc_parts.append(f"helps with {problems[0].lower()}")
        product_desc = f" ({', '.join(product_desc_parts)})" if product_desc_parts else ""

        brand_colors = ""
        if brand_profile:
            basics = brand_profile.get("brand_basics", {})
            colors = basics.get("colors", [])
            if colors:
                brand_colors = ", ".join(colors[:3])

        # Persona demographics + context
        persona_age = ""
        persona_gender = ""
        persona_context = ""
        if persona:
            demographics = persona.get("demographics", {})
            persona_age = demographics.get("age_range", "")
            persona_gender = demographics.get("gender", "")
            # Use desired_self_image for aspirational lifestyle shots
            desired = persona.get("desired_self_image", "")
            if desired:
                persona_context = desired[:100]

        has_persona = bool(persona_age and persona_gender)

        for slot in slots:
            if not slot.selected:
                continue

            # Scene-directed path: when scene_direction is available,
            # use the contextual prompt instead of generic templates
            if slot.scene_direction:
                # Skip slots that the narrative director marked as skip
                if slot.scene_direction.get("action") == "skip":
                    continue
                slot.prompt = self._build_scene_directed_prompt(
                    slot, product_name, product_desc, persona, brand_colors,
                )
                continue

            analysis = slot.image_analysis or {}
            image_type = analysis.get("image_type", "unknown")
            # Only use Vision for composition STYLE, not product subject
            composition = analysis.get("composition", "")
            has_people = analysis.get("has_people", False)

            # Extract only style cues from composition (lighting, angle, mood)
            # — strip anything that describes the competitor product or people
            style_cues = self._extract_style_cues(composition)

            # Person description: use ONLY persona when available.
            # Never mix persona demographics with Vision people_description —
            # conflicting age/gender signals cause hallucination, especially
            # when the original image is also passed as a reference.
            person_desc = ""
            if has_persona:
                person_desc = f"a {persona_age} {persona_gender}"
            # Only fall back to Vision people desc when NO persona is set
            elif has_people:
                # Use a generic description — Vision people_description
                # often includes specific ages that conflict with reference images
                person_desc = "a person"

            # When the image has people and we have persona demographics,
            # drop the original image as a composition reference — it shows
            # the competitor's model which conflicts with the persona age/gender.
            # Keep it only for non-people images (product shots, banners, etc.)
            if has_people and has_persona:
                slot.original_base64 = None

            color_note = f", brand colors {brand_colors}" if brand_colors else ""

            if image_type == "lifestyle":
                activity = persona_context or "enjoying their daily wellness routine"
                slot.prompt = (
                    f"Realistic iPhone photo of {person_desc or 'a person'} "
                    f"{activity}, "
                    f"{product_name}{product_desc} visible nearby{color_note}, "
                    f"{style_cues or 'natural lighting'}, candid natural moment, warm tones"
                )

            elif image_type == "product_shot":
                slot.prompt = (
                    f"Professional product photography of {product_name}{product_desc} "
                    f"on a clean surface, studio lighting{color_note}, "
                    f"{style_cues or 'sharp focus'}, shot from a flattering angle, no text overlays"
                )

            elif image_type == "hero_banner":
                slot.prompt = (
                    f"Wide cinematic hero image for {product_name}{product_desc}, "
                    f"{style_cues or 'dramatic composition'}{color_note} prominent, "
                    f"commercial photography quality, no text overlays"
                )

            elif image_type == "testimonial_photo":
                slot.prompt = (
                    f"Realistic natural headshot of {person_desc or 'a satisfied customer'}, "
                    f"genuine warm smile, soft natural lighting, slightly blurred background, "
                    f"authentic feel"
                )

            elif image_type == "before_after":
                problem = ""
                if problems:
                    problem = problems[0].lower()
                slot.prompt = (
                    f"Side-by-side comparison image showing transformation, "
                    f"left side: {problem or 'before state'}, "
                    f"right side: improved wellness with {product_name}, "
                    f"clean layout{color_note}"
                )

            elif image_type == "infographic":
                # Infographics contain competitor branding — generate from
                # scratch based on the SECTION CONTEXT, not the original image.
                slot.original_base64 = None
                slot.prompt = (
                    f"Clean modern infographic layout for {product_name}{product_desc}, "
                    f"showing key benefits and features, "
                    f"{color_note or 'professional color scheme'}, "
                    f"minimal clean design, no competitor branding, no text overlays"
                )

            else:
                # Default / unknown / ingredient / background_texture
                slot.prompt = (
                    f"High-quality commercial photograph for {product_name}{product_desc}, "
                    f"{style_cues or 'professional lighting'}"
                    f"{color_note}, no text overlays"
                )

        return slots

    @staticmethod
    def _extract_style_cues(composition: str) -> str:
        """Extract lighting/angle/mood cues from Vision composition.

        Drops product references AND people/demographic descriptions.
        Vision describes "bright natural lighting, 30s woman at marble counter,
        warm tones". We want "bright natural lighting, warm tones" but NOT
        "30s woman at marble counter".
        """
        if not composition:
            return ""

        # Reject phrases containing people/demographic/product keywords
        reject_keywords = {
            "woman", "man", "person", "people", "girl", "boy", "child",
            "young", "old", "elderly", "teen", "adult", "male", "female",
            "bottle", "shake", "pill", "product", "package", "jar", "box",
            "holding", "drinking", "eating", "pouring", "sitting", "standing",
            "counter", "table", "desk", "kitchen", "bathroom", "gym",
            "20s", "30s", "40s", "50s", "60s",
        }

        # Keep only style-related phrases
        style_keywords = {
            "lighting", "light", "lit", "bright", "dark", "soft", "warm", "cool",
            "tone", "tones", "mood", "angle", "overhead", "close-up", "wide",
            "cinematic", "natural", "studio", "dramatic", "minimalist", "clean",
            "blur", "blurred", "bokeh", "shallow", "depth", "vibrant", "muted",
            "pastel", "neutral", "candid", "posed", "symmetr", "centered",
        }
        parts = [p.strip() for p in composition.split(",")]
        kept = []
        for part in parts:
            words = part.lower().split()
            # Skip if it mentions people or products
            if any(rk in word for word in words for rk in reject_keywords):
                continue
            if any(kw in word for word in words for kw in style_keywords):
                kept.append(part.strip())
        return ", ".join(kept[:3]) if kept else ""

    def _build_scene_directed_prompt(
        self,
        slot: "ImageSlot",
        product_name: str,
        product_desc: str,
        persona: Optional[Dict[str, Any]],
        brand_colors: str,
    ) -> str:
        """Build a generation prompt from Scene Director output + Vision style cues.

        Combines the scene description (from surrounding text context) with
        composition style (from Vision analysis) and persona demographics.
        """
        scene = slot.scene_direction
        analysis = slot.image_analysis or {}
        has_people = analysis.get("has_people", False)
        composition = analysis.get("composition", "")

        # Style prefix from narrative role
        role = scene.get("narrative_role", "")
        style_prefix = NARRATIVE_ROLE_STYLES.get(role, "High-quality commercial photograph")

        # Scene description is the key differentiator
        scene_desc = scene.get("scene_description", "")
        emotional_tone = scene.get("emotional_tone", "")
        setting = scene.get("setting", "")

        # Person description from persona (same logic as template path)
        person_desc = ""
        has_persona = False
        if persona:
            demographics = persona.get("demographics", {})
            age = demographics.get("age_range", "")
            gender = demographics.get("gender", "")
            if age and gender:
                person_desc = f"a {age} {gender}"
                has_persona = True

        if not person_desc and has_people:
            person_desc = "a person"

        # Preserve persona/Vision conflict prevention:
        # drop original image when people + persona to avoid demographic conflicts
        if has_people and has_persona:
            slot.original_base64 = None

        # Clear original for infographic/educational (competitor branding)
        if role == "educational":
            slot.original_base64 = None

        # Vision style cues (lighting, angle, mood only)
        style_cues = self._extract_style_cues(composition)

        color_note = f", brand colors {brand_colors}" if brand_colors else ""

        # Should the product be shown? Respect the LLM's decision.
        show_product = scene.get("show_product", False)

        # New strategy pipeline fields
        persuasion_job = scene.get("persuasion_job", "")
        product_placement = scene.get("product_placement", "")
        gaze = scene.get("gaze_direction", "")

        # Compose prompt
        parts = [style_prefix]
        if person_desc and role not in ("product_showcase", "educational"):
            parts.append(f"of {person_desc}")
        if scene_desc:
            parts.append(f"— {scene_desc}")
        if setting:
            parts.append(f"Setting: {setting}.")
        if emotional_tone:
            parts.append(f"Mood: {emotional_tone}.")
        # Only mention the product when the scene calls for it
        if show_product and product_name:
            if product_placement:
                parts.append(f"{product_name}{product_desc} — {product_placement}.")
            elif role == "product_showcase":
                parts.append(f"Featuring {product_name}{product_desc}.")
            else:
                parts.append(f"{product_name}{product_desc} visible nearby.")
        # Persuasion context for richer generation
        if persuasion_job:
            parts.append(f"This image should {persuasion_job.lower()}.")
        # Gaze direction for people images
        if gaze and (has_people or person_desc):
            parts.append(f"Subject looking {gaze}.")
        if style_cues:
            parts.append(f"Style: {style_cues}.")
        if color_note:
            parts.append(color_note.lstrip(", ") + ".")
        parts.append("No text overlays.")

        return " ".join(parts)

    async def generate_images(
        self,
        slots: List[ImageSlot],
        gemini_service,
        reference_images_b64: List[str],
        progress_cb: Optional[Callable] = None,
    ) -> List[ImageSlot]:
        """Generate images sequentially via Gemini 3 Pro."""
        from viraltracker.services.gemini_service import SafetyFilterError

        selected = [s for s in slots if s.selected and s.prompt]
        total = len(selected)

        for i, slot in enumerate(selected):
            if progress_cb:
                progress_cb(i, total, f"Generating image {i + 1}/{total}: {slot.image_analysis.get('image_type', 'image')}...")

            # Build reference images: original first, then product refs
            refs = []
            if slot.original_base64:
                refs.append(slot.original_base64)
            refs.extend(reference_images_b64[:3])

            try:
                result = await gemini_service.generate_image(
                    slot.prompt,
                    reference_images=refs if refs else None,
                    return_metadata=True,
                    aspect_ratio=slot.aspect_ratio,
                )
                slot.generated_base64 = result["image_base64"]
            except SafetyFilterError as e:
                logger.warning(f"Safety filter for slot {slot.index}: {e}")
                # Retry with product-only prompt if people were involved
                if slot.image_analysis and slot.image_analysis.get("has_people"):
                    try:
                        fallback_prompt = (
                            f"Professional product photography of a wellness product on a clean surface, "
                            f"studio lighting, neutral background, sharp focus, no people, no text overlays"
                        )
                        result = await gemini_service.generate_image(
                            fallback_prompt,
                            reference_images=reference_images_b64[:3] if reference_images_b64 else None,
                            return_metadata=True,
                            aspect_ratio=slot.aspect_ratio,
                        )
                        slot.generated_base64 = result["image_base64"]
                    except Exception as retry_err:
                        logger.error(f"Safety fallback also failed for slot {slot.index}: {retry_err}")
                        slot.error = f"Blocked by safety filter (retry failed): {retry_err}"
                else:
                    slot.error = f"Blocked by safety filter: {e}"
            except Exception as e:
                logger.error(f"Image generation failed for slot {slot.index}: {e}")
                slot.error = str(e)

        return slots

    async def upload_and_replace_html(
        self,
        slots: List[ImageSlot],
        html: str,
        blueprint_id: str,
    ) -> Tuple[str, Dict[str, Any]]:
        """Upload generated PNGs and replace image sources in HTML."""
        replacements: Dict[int, str] = {}
        meta: Dict[str, Any] = {}
        bucket = self.supabase.storage.from_("generated-ads")

        for slot in slots:
            if not slot.generated_base64:
                # Store analysis meta even for non-generated slots
                meta[str(slot.index)] = self._build_slot_meta(slot)
                continue

            ts = int(time.time() * 1000)
            file_path = f"blueprint-images/{blueprint_id}/img_{slot.index}_{ts}.png"
            img_bytes = base64.b64decode(slot.generated_base64)

            try:
                # Upload to Supabase storage
                await asyncio.to_thread(
                    bucket.upload,
                    file_path,
                    img_bytes,
                    {"content-type": "image/png"},
                )

                # Get public URL
                slot.storage_url = bucket.get_public_url(file_path)

                replacements[slot.index] = slot.storage_url
            except Exception as e:
                logger.error(f"Upload failed for slot {slot.index}: {e}")
                slot.error = f"Upload failed: {e}"

            meta[str(slot.index)] = self._build_slot_meta(slot, storage_path=file_path)

        # Replace image sources in HTML
        logger.info(
            f"Image replacement: {len(replacements)} replacements to apply, "
            f"indices={sorted(replacements.keys())}, "
            f"html_len={len(html)}"
        )
        new_html = replace_image_sources(html, replacements) if replacements else html
        if replacements:
            logger.info(
                f"Image replacement done: input_len={len(html)}, "
                f"output_len={len(new_html)}, "
                f"changed={html != new_html}"
            )

        return new_html, meta

    # ------------------------------------------------------------------
    # Orchestrators
    # ------------------------------------------------------------------

    async def analyze_blueprint_images(
        self,
        blueprint_id: str,
        html: str,
        progress_cb: Optional[Callable] = None,
        product_info: Optional[Dict[str, Any]] = None,
        persona: Optional[Dict[str, Any]] = None,
        blueprint_sections: Optional[list] = None,
        brand_profile: Optional[Dict[str, Any]] = None,
        product_id: Optional[str] = None,
    ) -> Tuple[List[ImageSlot], int]:
        """Phase 1: Extract, download, and analyze images. Saves analysis to DB.

        Args:
            product_info: Product dict for scene direction context.
            persona: Persona dict for scene direction demographics.
            blueprint_sections: Reconstruction blueprint sections for strategy pipeline.
            brand_profile: Full brand profile dict for strategy pipeline.
            product_id: Product UUID for playbook caching.
        """
        from viraltracker.services.gemini_service import GeminiService

        if progress_cb:
            progress_cb(0, 1, "Extracting image slots...")

        slots = self.extract_image_slots(html)
        if not slots:
            return [], 0

        if progress_cb:
            progress_cb(0, len(slots), f"Downloading {len(slots)} images...")

        success = await self.download_images_parallel(slots, progress_cb)

        # Create Vision service (Flash for cheap analysis)
        vision_svc = GeminiService(model="gemini-2.5-flash")
        if self._tracker:
            vision_svc.set_tracking_context(self._tracker, self._user_id, self._org_id)

        # Image Strategy Pipeline (replaces Scene Director when full context available)
        if product_id and brand_profile:
            from viraltracker.services.landing_page_analysis.image_strategy_service import (
                ImageStrategyService,
            )

            strategy_svc = ImageStrategyService(
                supabase=self._supabase if hasattr(self, '_supabase') else self.supabase,
                org_id=self._org_id,
            )
            if self._tracker:
                strategy_svc.set_tracking_context(
                    self._tracker, self._user_id, self._org_id
                )

            # Step 1 (playbook, cached) || Vision in parallel
            playbook_coro = strategy_svc.get_or_create_visual_playbook(
                product_id, brand_profile
            )
            vision_coro = self.analyze_original_images(slots, vision_svc, progress_cb)
            playbook, _ = await asyncio.gather(playbook_coro, vision_coro)

            # Step 2 (needs both Vision results and playbook) + deterministic QA
            await strategy_svc.run_narrative_and_validate(
                slots=slots,
                playbook=playbook,
                brand_profile=brand_profile,
                persona=persona,
                blueprint_sections=blueprint_sections,
                progress_cb=progress_cb,
            )
        elif product_info:
            # Fallback: old Scene Director + Vision in parallel
            scene_svc = GeminiService(model="gemini-2.5-flash")
            if self._tracker:
                scene_svc.set_tracking_context(
                    self._tracker, self._user_id, self._org_id
                )
            await asyncio.gather(
                self.analyze_original_images(slots, vision_svc, progress_cb),
                self.direct_scenes_for_slots(slots, scene_svc, product_info, persona),
            )
        else:
            # No product context — Vision analysis only
            await self.analyze_original_images(slots, vision_svc, progress_cb)

        # Build and save analysis meta
        meta = {}
        for slot in slots:
            meta[str(slot.index)] = self._build_slot_meta(slot)

        self.save_analysis(blueprint_id, meta)

        return slots, success

    async def generate_blueprint_images(
        self,
        blueprint_id: str,
        html: str,
        product_id: str,
        persona_id: Optional[str] = None,
        brand_profile: Optional[Dict[str, Any]] = None,
        selected_indices: Optional[List[int]] = None,
        prompt_overrides: Optional[Dict[int, str]] = None,
        progress_cb: Optional[Callable] = None,
    ) -> Tuple[str, int, int]:
        """Phase 2: Generate AI images and replace in HTML.

        Args:
            prompt_overrides: Dict mapping slot index → custom prompt string.
                Overrides the auto-generated prompt for those slots.

        Returns (new_html, generated_count, failed_count).
        """
        from viraltracker.services.gemini_service import GeminiService

        # Load cached analysis
        bp = self.supabase.table("landing_page_blueprints").select(
            "generated_images_meta"
        ).eq("id", blueprint_id).single().execute()
        existing_meta = (bp.data or {}).get("generated_images_meta", {})

        # Rebuild slots from cached meta, or re-analyze if empty
        if existing_meta:
            slots = self._rebuild_slots_from_meta(existing_meta)
        else:
            slots, _ = await self.analyze_blueprint_images(blueprint_id, html, progress_cb)
            # Re-read meta after analysis
            bp = self.supabase.table("landing_page_blueprints").select(
                "generated_images_meta"
            ).eq("id", blueprint_id).single().execute()
            existing_meta = (bp.data or {}).get("generated_images_meta", {})

        if not slots:
            return html, 0, 0

        # Apply selection filter
        if selected_indices is not None:
            for slot in slots:
                slot.selected = slot.index in selected_indices

        # Load product reference images
        product_refs_b64 = await self._load_product_images(product_id)

        # Load persona
        persona_data = None
        if persona_id:
            try:
                from uuid import UUID
                from viraltracker.services.persona_service import PersonaService

                persona_data = PersonaService().export_for_ad_generation(UUID(persona_id))
            except (ValueError, Exception) as e:
                logger.warning(f"Failed to load persona {persona_id}: {e}")

        # Product info from brand profile
        product_info = {}
        if brand_profile:
            product_info = brand_profile.get("product", {})
        if not product_info.get("name"):
            product_info["name"] = "the product"

        # Build prompts
        self.build_generation_prompts(slots, product_info, persona_data, brand_profile)

        # Apply user prompt overrides
        if prompt_overrides:
            for slot in slots:
                if slot.index in prompt_overrides and prompt_overrides[slot.index].strip():
                    slot.prompt = prompt_overrides[slot.index].strip()

        # Create generation service
        gen_svc = GeminiService()
        if self._tracker:
            gen_svc.set_tracking_context(self._tracker, self._user_id, self._org_id)

        # Generate images
        await self.generate_images(slots, gen_svc, product_refs_b64, progress_cb)

        # Upload and replace
        new_html, meta = await self.upload_and_replace_html(slots, html, blueprint_id)

        # Merge meta: keep analysis for non-generated slots, update generated ones
        merged_meta = {**existing_meta, **meta}

        # Save to DB
        self.save_generated_images(blueprint_id, new_html, merged_meta)

        generated = sum(1 for s in slots if s.selected and s.generated_base64)
        failed = sum(1 for s in slots if s.selected and s.error)

        return new_html, generated, failed

    async def regenerate_single_image(
        self,
        blueprint_id: str,
        slot_index: int,
        product_id: str,
        persona_id: Optional[str] = None,
        brand_profile: Optional[Dict[str, Any]] = None,
        prompt_override: Optional[str] = None,
        progress_cb: Optional[Callable] = None,
    ) -> Tuple[str, bool]:
        """Regenerate a single image slot. Returns (new_html, success)."""
        from viraltracker.services.gemini_service import GeminiService

        # Load existing data
        bp = self.supabase.table("landing_page_blueprints").select(
            "generated_images_meta, blueprint_mockup_html_with_images"
        ).eq("id", blueprint_id).single().execute()

        if not bp.data:
            raise ValueError(f"Blueprint {blueprint_id} not found")

        existing_meta = bp.data.get("generated_images_meta", {})
        existing_html = bp.data.get("blueprint_mockup_html_with_images")
        slot_key = str(slot_index)

        if slot_key not in existing_meta:
            raise ValueError(f"No metadata for slot {slot_index}")

        if not existing_html:
            raise ValueError("No existing generated HTML to update")

        # Rebuild slot from stored meta (including scene_direction for cached context)
        slot_data = existing_meta[slot_key]
        slot = ImageSlot(
            index=slot_index,
            original_src=slot_data.get("original_src", ""),
            alt_text=slot_data.get("alt_text", ""),
            surrounding_text=slot_data.get("surrounding_text", ""),
            section_heading=slot_data.get("section_heading", ""),
            image_analysis=slot_data.get("analysis"),
            scene_direction=slot_data.get("scene_direction"),
            aspect_ratio=slot_data.get("aspect_ratio"),
            selected=True,
        )

        # Re-download original for composition reference
        if slot.original_src:
            try:
                import httpx

                async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                    resp = await client.get(slot.original_src)
                    resp.raise_for_status()
                    slot.original_base64 = base64.b64encode(resp.content).decode("utf-8")
            except Exception as e:
                logger.warning(f"Failed to re-download original for regen: {e}")

        # Load product refs + persona + product info
        product_refs_b64 = await self._load_product_images(product_id)

        persona_data = None
        if persona_id:
            try:
                from uuid import UUID
                from viraltracker.services.persona_service import PersonaService

                persona_data = PersonaService().export_for_ad_generation(UUID(persona_id))
            except (ValueError, Exception) as e:
                logger.warning(f"Failed to load persona for regen: {e}")

        product_info = {}
        if brand_profile:
            product_info = brand_profile.get("product", {})
        if not product_info.get("name"):
            product_info["name"] = "the product"

        # Build prompt (user override takes precedence)
        if prompt_override and prompt_override.strip():
            slot.prompt = prompt_override.strip()
        else:
            self.build_generation_prompts([slot], product_info, persona_data, brand_profile)

        if not slot.prompt:
            return existing_html, False

        # Generate
        gen_svc = GeminiService()
        if self._tracker:
            gen_svc.set_tracking_context(self._tracker, self._user_id, self._org_id)

        if progress_cb:
            progress_cb(0, 1, "Generating replacement image...")

        await self.generate_images([slot], gen_svc, product_refs_b64, progress_cb)

        if not slot.generated_base64:
            return existing_html, False

        # Upload
        ts = int(time.time() * 1000)
        file_path = f"blueprint-images/{blueprint_id}/img_{slot_index}_{ts}.png"
        img_bytes = base64.b64decode(slot.generated_base64)
        bucket = self.supabase.storage.from_("generated-ads")

        try:
            await asyncio.to_thread(
                bucket.upload,
                file_path,
                img_bytes,
                {"content-type": "image/png"},
            )
            slot.storage_url = bucket.get_public_url(file_path)
        except Exception as e:
            logger.error(f"Upload failed for regen slot {slot_index}: {e}")
            return existing_html, False

        # Replace in existing generated HTML
        new_html = replace_image_sources(existing_html, {slot_index: slot.storage_url})

        # Build slot meta and merge
        slot_meta = self._build_slot_meta(slot, storage_path=file_path)

        self.save_single_slot(blueprint_id, slot_index, new_html, slot_meta)

        # Best-effort delete old storage file
        old_path = slot_data.get("storage_path")
        if old_path:
            try:
                await asyncio.to_thread(bucket.remove, [old_path])
            except Exception as e:
                logger.warning(f"Failed to delete old image {old_path}: {e}")

        return new_html, True

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def save_analysis(self, blueprint_id: str, meta: dict):
        """Save Vision analysis results (Phase 1 cache)."""
        self.supabase.table("landing_page_blueprints").update({
            "generated_images_meta": meta,
        }).eq("id", blueprint_id).execute()

    def save_generated_images(self, blueprint_id: str, html: str, meta: dict):
        """Save generated images HTML and metadata."""
        self.supabase.table("landing_page_blueprints").update({
            "blueprint_mockup_html_with_images": html,
            "generated_images_meta": meta,
        }).eq("id", blueprint_id).execute()

    def save_single_slot(self, blueprint_id: str, slot_index: int, html: str, slot_meta: dict):
        """Merge a single regenerated slot into existing data."""
        bp = self.supabase.table("landing_page_blueprints").select(
            "generated_images_meta"
        ).eq("id", blueprint_id).single().execute()
        existing_meta = bp.data.get("generated_images_meta", {}) if bp.data else {}
        existing_meta[str(slot_index)] = slot_meta
        self.supabase.table("landing_page_blueprints").update({
            "blueprint_mockup_html_with_images": html,
            "generated_images_meta": existing_meta,
        }).eq("id", blueprint_id).execute()

    def clear_generated_images(self, blueprint_id: str):
        """Clear generated images when base mockup is regenerated."""
        # Delete storage objects
        try:
            prefix = f"blueprint-images/{blueprint_id}/"
            bucket = self.supabase.storage.from_("generated-ads")
            while True:
                files = bucket.list(prefix, {"limit": 100})
                if not files:
                    break
                paths = [f"{prefix}{f['name']}" for f in files]
                bucket.remove(paths)
                if len(files) < 100:
                    break
        except Exception as e:
            logger.warning(f"Failed to clean storage for {blueprint_id}: {e}")

        # Clear DB columns
        self.supabase.table("landing_page_blueprints").update({
            "blueprint_mockup_html_with_images": None,
            "generated_images_meta": {},
        }).eq("id", blueprint_id).execute()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _load_product_images(self, product_id: str) -> List[str]:
        """Load top 3 product reference images as base64."""
        image_extensions = (".jpg", ".jpeg", ".png", ".webp", ".gif")
        try:
            result = self.supabase.table("product_images").select(
                "storage_path, is_main"
            ).eq("product_id", product_id).order("is_main", desc=True).execute()

            images = [
                img for img in (result.data or [])
                if img["storage_path"].lower().endswith(image_extensions)
            ][:3]

            refs = []
            for img in images:
                try:
                    storage_path = img["storage_path"]
                    parts = storage_path.split("/", 1)
                    bucket_name = parts[0]
                    file_path = parts[1] if len(parts) > 1 else storage_path

                    data = await asyncio.to_thread(
                        self.supabase.storage.from_(bucket_name).download,
                        file_path,
                    )
                    refs.append(base64.b64encode(data).decode("utf-8"))
                except Exception as e:
                    logger.warning(f"Failed to download product image: {e}")

            return refs
        except Exception as e:
            logger.warning(f"Failed to load product images for {product_id}: {e}")
            return []

    def _rebuild_slots_from_meta(self, meta: Dict[str, Any]) -> List[ImageSlot]:
        """Rebuild ImageSlot list from stored metadata."""
        slots = []
        for idx_str, data in sorted(meta.items(), key=lambda x: int(x[0])):
            slot = ImageSlot(
                index=int(idx_str),
                original_src=data.get("original_src", ""),
                alt_text=data.get("alt_text", ""),
                surrounding_text=data.get("surrounding_text", ""),
                section_heading=data.get("section_heading", ""),
                image_analysis=data.get("analysis"),
                scene_direction=data.get("scene_direction"),
                aspect_ratio=data.get("aspect_ratio"),
                selected=True,
            )
            slots.append(slot)
        return slots

    def _build_slot_meta(
        self, slot: ImageSlot, storage_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """Build metadata dict for a single slot."""
        return {
            "original_src": slot.original_src,
            "alt_text": slot.alt_text,
            "surrounding_text": slot.surrounding_text,
            "section_heading": slot.section_heading,
            "aspect_ratio": slot.aspect_ratio,
            "analysis": slot.image_analysis,
            "scene_direction": slot.scene_direction,
            "prompt": slot.prompt,
            "storage_path": storage_path,
            "storage_url": slot.storage_url,
            "error": slot.error,
        }
