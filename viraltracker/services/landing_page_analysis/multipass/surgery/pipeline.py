"""Surgery Pipeline orchestrator.

Coordinates 5 passes (S0-S4) of HTML surgery:
  S0: Sanitize & resolve CSS
  S1: Section segmentation
  S2: Element classification & slot tagging
  S3: CSS isolation & scoping
  S4: Visual QA patches (conditional)
"""

import logging
import os
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from viraltracker.services.gemini_service import GeminiService

logger = logging.getLogger(__name__)

# Gemini model for surgery vision calls (S2 classification, S4 QA)
SURGERY_VISION_MODEL = os.environ.get(
    "SURGERY_VISION_MODEL", "models/gemini-2.5-pro-preview-06-05"
)

# SSIM threshold below which S4 QA patches are applied
S4_SSIM_THRESHOLD = 0.80

# Max wall clock for surgery pipeline
SURGERY_MAX_WALL_CLOCK = 180  # 3 minutes (much faster than reconstruction)


class SurgeryPipeline:
    """Orchestrates the HTML surgery pipeline (S0-S4).

    Instead of reconstructing HTML from scratch, performs surgery on the
    original page HTML to clean, segment, classify, and scope it.
    """

    def __init__(
        self,
        gemini_service: GeminiService,
        progress_callback: Optional[Callable] = None,
    ):
        self._gemini = gemini_service
        self._progress = progress_callback
        self._start_time = 0.0
        #: Phase snapshots for debugging/eval
        self.phase_snapshots: Dict[str, str] = {}

    def _report_progress(self, phase: int, message: str):
        """Report progress via callback if available."""
        if self._progress:
            try:
                self._progress(phase, message)
            except Exception:
                pass

    async def generate(
        self,
        screenshot_b64: str,
        page_markdown: str,
        page_url: str = "",
        element_detection: Optional[Dict] = None,
        page_html: str = "",
    ) -> str:
        """Run the surgery pipeline on original page HTML.

        Args:
            screenshot_b64: Base64-encoded full-page screenshot.
            page_markdown: Full page markdown text.
            page_url: Page URL for resolving relative URLs.
            element_detection: Optional element detection for section hints.
            page_html: Full page HTML from FireCrawl (required).

        Returns:
            Complete HTML string with data-section, data-slot attributes
            and CSS scoped under .lp-mockup.
        """
        self._start_time = time.time()
        api_calls = 0

        # ------------------------------------------------------------------
        # S0: Sanitize & Resolve CSS
        # ------------------------------------------------------------------
        self._report_progress(0, "Sanitizing HTML...")

        from .sanitizer import HTMLSanitizer
        sanitizer = HTMLSanitizer()
        sanitized_html, sanitize_stats = sanitizer.sanitize(
            page_html, page_url
        )

        self.phase_snapshots["phase_s0_sanitized"] = sanitized_html
        self.phase_snapshots["_s0_stats"] = _wrap_json(sanitize_stats)

        logger.info(
            f"S0 Sanitize: {sanitize_stats['input_size']:,} → "
            f"{sanitize_stats['output_size']:,} bytes, "
            f"visible_text={sanitize_stats['visible_text_len']:,} chars"
        )

        # Fallback: if not viable, return empty to trigger reconstruction
        if not sanitize_stats["viable"]:
            logger.warning(
                "S0: Visible text < 500 chars — falling back to reconstruction"
            )
            return ""

        # ------------------------------------------------------------------
        # S1: Section Segmentation
        # ------------------------------------------------------------------
        self._report_progress(1, "Segmenting sections...")

        from .section_mapper import SectionMapper
        from ..segmenter import segment_markdown
        from ..markdown_cleaner import classify_markdown

        # Use cleaned markdown for section mapping
        clean_result = classify_markdown(page_markdown, mode="extract")
        sections = segment_markdown(
            clean_result.cleaned_markdown, element_detection
        )

        mapper = SectionMapper()
        segmented_html, section_stats = mapper.map_sections(
            sanitized_html, sections
        )

        self.phase_snapshots["phase_s1_segmented"] = segmented_html
        self.phase_snapshots["_s1_stats"] = _wrap_json(section_stats)
        # Store cleaned markdown for downstream fidelity scoring
        self.phase_snapshots["_cleaned_markdown"] = clean_result.cleaned_markdown

        logger.info(
            f"S1 Segment: {section_stats['sections_mapped']}/{len(sections)} "
            f"sections mapped via {section_stats['strategy_used']}"
        )

        # ------------------------------------------------------------------
        # S2: Element Classification & Slot Tagging
        # ------------------------------------------------------------------
        self._report_progress(2, "Classifying elements...")

        from .element_classifier import ElementClassifier
        classifier = ElementClassifier()

        classified_html, classify_stats = classifier.classify(
            segmented_html, sections, screenshot_b64, self._gemini
        )
        api_calls += classify_stats.get("api_calls", 0)

        self.phase_snapshots["phase_s2_classified"] = classified_html
        self.phase_snapshots["_s2_stats"] = _wrap_json(classify_stats)

        logger.info(
            f"S2 Classify: {classify_stats['total_slots']} slots, "
            f"api_calls={classify_stats.get('api_calls', 0)}"
        )

        # ------------------------------------------------------------------
        # S3: CSS Isolation & Scoping
        # ------------------------------------------------------------------
        self._report_progress(3, "Scoping CSS...")

        from .css_scoper import CSSScoper

        # Get external CSS from CSSExtractor
        external_css = ""
        try:
            from ..html_extractor import CSSExtractor
            responsive_css = CSSExtractor.extract(page_html, page_url)
            external_css = responsive_css.to_css_block()
        except Exception as e:
            logger.warning(f"S3: External CSS extraction failed: {e}")

        scoper = CSSScoper()
        scoped_html, scope_stats = scoper.scope(classified_html, external_css)

        self.phase_snapshots["phase_s3_scoped"] = scoped_html
        self.phase_snapshots["_s3_stats"] = _wrap_json(scope_stats)

        logger.info(
            f"S3 Scope: {scope_stats['style_blocks_extracted']} style blocks, "
            f"{scope_stats['css_total_chars']:,} CSS chars"
        )

        # ------------------------------------------------------------------
        # S4: Visual QA Patches (conditional)
        # ------------------------------------------------------------------
        final_html = scoped_html
        s4_applied = False

        try:
            from ..html_renderer import render_html_to_png
            from ..eval_harness import score_visual_fidelity
            import base64

            self._report_progress(4, "Visual QA check...")

            s3_png = render_html_to_png(scoped_html)
            if s3_png and screenshot_b64:
                original_png = base64.b64decode(screenshot_b64)
                ssim_score = score_visual_fidelity(original_png, s3_png)

                logger.info(f"S4 QA: S3 SSIM = {ssim_score:.3f}")

                if ssim_score < S4_SSIM_THRESHOLD:
                    # Apply QA patches via LLM
                    from .prompts import build_surgery_patch_prompt
                    from ..patch_applier import PatchApplier
                    from ..invariants import check_global_invariants

                    prompt = build_surgery_patch_prompt(ssim_score)

                    try:
                        response = await self._gemini.generate_content_async(
                            model=SURGERY_VISION_MODEL,
                            contents=[
                                {"mime_type": "image/png", "data": screenshot_b64},
                                {"mime_type": "image/png", "data": base64.b64encode(s3_png).decode()},
                                prompt,
                            ],
                        )
                        api_calls += 1

                        patches_text = response.text if hasattr(response, 'text') else str(response)
                        applier = PatchApplier()
                        patched, patch_count = applier.apply(
                            scoped_html, patches_text
                        )

                        if patch_count > 0:
                            # Validate patched output
                            invariant_result = check_global_invariants(patched)
                            if invariant_result.passed:
                                final_html = patched
                                s4_applied = True
                                logger.info(
                                    f"S4 QA: Applied {patch_count} patches"
                                )
                            else:
                                logger.warning(
                                    f"S4 QA: Patches failed invariants, reverting"
                                )
                    except Exception as e:
                        logger.warning(f"S4 QA: LLM patch failed: {e}")
                else:
                    logger.info(
                        f"S4 QA: SSIM {ssim_score:.3f} >= {S4_SSIM_THRESHOLD}, "
                        "skipping patches"
                    )
        except ImportError:
            logger.debug("S4: Playwright not available, skipping visual QA")
        except Exception as e:
            logger.warning(f"S4 QA: Failed: {e}")

        self.phase_snapshots["phase_s4_final"] = final_html
        self.phase_snapshots["_s4_stats"] = _wrap_json({
            "s4_applied": s4_applied,
            "api_calls": api_calls,
        })

        # ------------------------------------------------------------------
        # Final validation: ensure at least 1 slot
        # ------------------------------------------------------------------
        from ..invariants import _extract_slots
        slots = _extract_slots(final_html)
        if not slots:
            logger.warning(
                "Surgery output has 0 slots — injecting fallback headline slot"
            )
            final_html = self._inject_fallback_slot(final_html)

        self._report_progress(5, "Complete!")

        elapsed = time.time() - self._start_time
        logger.info(
            f"Surgery pipeline complete: {elapsed:.1f}s, "
            f"{api_calls} API calls, {len(final_html):,} chars"
        )

        return final_html

    def _inject_fallback_slot(self, html: str) -> str:
        """Inject a data-slot='headline' on the first <h1> or <h2>."""
        import re
        for tag in ("h1", "h2", "h3"):
            pattern = re.compile(
                rf'(<{tag}\b)([^>]*>)',
                re.IGNORECASE,
            )
            match = pattern.search(html)
            if match:
                # Check if already has data-slot
                if 'data-slot' not in match.group(2):
                    replacement = f'{match.group(1)} data-slot="headline"{match.group(2)}'
                    html = html[:match.start()] + replacement + html[match.end():]
                    return html
        return html


def _wrap_json(data: Any) -> str:
    """Wrap JSON data as a string for phase_snapshots."""
    import json
    return json.dumps(data, indent=2, default=str)
