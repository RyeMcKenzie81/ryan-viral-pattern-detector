"""Quality benchmarking for multipass pipeline.

Scores: slot retention, text fidelity, visual SSIM, blueprint round-trip.
"""

import logging
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Go-live thresholds
MIN_SLOTS_PER_PAGE = 5
SLOT_RETENTION_THRESHOLD = 0.90  # >= 90% of single-pass slots
TEXT_FIDELITY_THRESHOLD = 0.85
SSIM_IMPROVEMENT_DELTA = 0.02
SSIM_WIN_RATE_THRESHOLD = 0.80
SSIM_MAX_REGRESSION = 0.05
MAX_LATENCY_P95_SECONDS = 90


@dataclass
class PageScore:
    """Score for a single page evaluation."""
    page_url: str
    slot_count: int = 0
    single_pass_slot_count: int = 0
    slot_retention: float = 0.0
    text_fidelity: float = 0.0
    visual_ssim: Optional[float] = None
    single_pass_ssim: Optional[float] = None
    blueprint_round_trip: bool = False
    escape_hatch_triggered: bool = False
    latency_seconds: float = 0.0
    issues: List[str] = field(default_factory=list)


@dataclass
class BenchmarkResult:
    """Aggregate benchmark result across all pages."""
    page_scores: List[PageScore] = field(default_factory=list)
    passed: bool = False
    failures: List[str] = field(default_factory=list)


class _SlotCounter(HTMLParser):
    """Count data-slot attributes in HTML."""

    def __init__(self):
        super().__init__()
        self.slots: List[str] = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name == 'data-slot' and value:
                self.slots.append(value)


class _TextExtractor(HTMLParser):
    """Extract visible text from HTML."""

    def __init__(self):
        super().__init__()
        self._parts: List[str] = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript'):
            self._skip = True

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript'):
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            self._parts.append(data)

    def get_text(self) -> str:
        return ' '.join(self._parts)


def count_slots(html: str) -> Tuple[int, List[str]]:
    """Count data-slot attributes in HTML.

    Returns:
        (count, list_of_slot_names)
    """
    counter = _SlotCounter()
    try:
        counter.feed(html)
    except Exception:
        pass
    return len(counter.slots), counter.slots


def score_text_fidelity(output_html: str, source_markdown: str) -> float:
    """Score text fidelity between output HTML and source markdown.

    Uses multiset Jaccard similarity on lowercased word tokens.

    Returns:
        Similarity score 0.0-1.0.
    """
    from .invariants import _tokenize_visible_text, _text_similarity

    output_tokens = _tokenize_visible_text(output_html)

    # Tokenize markdown similarly
    md_text = re.sub(r'[#*`\[\]()!]', ' ', source_markdown)
    md_words = re.split(r'\s+', md_text.lower().strip())
    md_tokens = [w for w in md_words if w]

    return _text_similarity(output_tokens, md_tokens)


def score_visual_fidelity(
    original_screenshot: bytes,
    output_screenshot: bytes,
) -> float:
    """Score visual fidelity between original and output screenshots.

    Uses SSIM (scikit-image) if available, else MAD fallback.

    Args:
        original_screenshot: PNG bytes of original page.
        output_screenshot: PNG bytes of rendered output.

    Returns:
        Similarity score 0.0-1.0.
    """
    from PIL import Image
    import io
    import numpy as np

    img_orig = Image.open(io.BytesIO(original_screenshot)).convert('L')
    img_out = Image.open(io.BytesIO(output_screenshot)).convert('L')

    # Resize to same dimensions
    target_size = (min(img_orig.width, img_out.width), min(img_orig.height, img_out.height))
    img_orig = img_orig.resize(target_size)
    img_out = img_out.resize(target_size)

    arr_orig = np.array(img_orig, dtype=np.float64)
    arr_out = np.array(img_out, dtype=np.float64)

    try:
        from skimage.metrics import structural_similarity as ssim
        score = ssim(arr_orig, arr_out, data_range=255)
        return float(score)
    except ImportError:
        # MAD fallback: 1 - mean_absolute_difference / 255
        mad = np.mean(np.abs(arr_orig - arr_out))
        return float(1.0 - mad / 255.0)


def check_blueprint_round_trip(
    output_html: str,
    mockup_service=None,
) -> bool:
    """Verify all slots survive extraction + rewrite + wrap.

    Args:
        output_html: Multipass output HTML.
        mockup_service: Optional MockupService instance for full round-trip.

    Returns:
        True if all slots survive the round-trip.
    """
    original_count, original_slots = count_slots(output_html)
    if original_count == 0:
        return False

    if mockup_service is None:
        # Without a service, just verify slots are well-formed
        return original_count >= MIN_SLOTS_PER_PAGE

    # Full round-trip: wrap → strip → check slots
    try:
        wrapped = mockup_service._wrap_mockup(output_html, None, mode="analysis")
        stripped = mockup_service._strip_mockup_wrapper(wrapped)
        stripped_count, stripped_slots = count_slots(stripped)

        if set(original_slots) != set(stripped_slots):
            logger.warning(
                f"Blueprint round-trip lost slots: "
                f"{set(original_slots) - set(stripped_slots)}"
            )
            return False

        return True
    except Exception as e:
        logger.warning(f"Blueprint round-trip check failed: {e}")
        return False


def evaluate_page(
    page_url: str,
    multipass_html: str,
    single_pass_html: str,
    source_markdown: str,
    latency_seconds: float,
    escape_hatch_triggered: bool = False,
    original_screenshot: Optional[bytes] = None,
    multipass_screenshot: Optional[bytes] = None,
    single_pass_screenshot: Optional[bytes] = None,
    mockup_service=None,
) -> PageScore:
    """Evaluate multipass output for a single page.

    Args:
        page_url: URL of the evaluated page.
        multipass_html: Multipass pipeline output.
        single_pass_html: Single-pass baseline output.
        source_markdown: Original page markdown.
        latency_seconds: Pipeline wall-clock time.
        escape_hatch_triggered: Whether catastrophic escape was triggered.
        original_screenshot: Original page screenshot bytes (optional).
        multipass_screenshot: Rendered multipass output screenshot (optional).
        single_pass_screenshot: Rendered single-pass output screenshot (optional).
        mockup_service: Optional MockupService for round-trip check.

    Returns:
        PageScore with all metrics.
    """
    score = PageScore(page_url=page_url)
    score.latency_seconds = latency_seconds
    score.escape_hatch_triggered = escape_hatch_triggered

    # Slot count
    score.slot_count, _ = count_slots(multipass_html)
    score.single_pass_slot_count, _ = count_slots(single_pass_html)

    # Slot retention vs single-pass
    if score.single_pass_slot_count > 0:
        score.slot_retention = score.slot_count / score.single_pass_slot_count
    else:
        score.slot_retention = 1.0 if score.slot_count > 0 else 0.0

    # Text fidelity
    score.text_fidelity = score_text_fidelity(multipass_html, source_markdown)

    # Visual fidelity (optional)
    if original_screenshot and multipass_screenshot:
        score.visual_ssim = score_visual_fidelity(original_screenshot, multipass_screenshot)
    if original_screenshot and single_pass_screenshot:
        score.single_pass_ssim = score_visual_fidelity(original_screenshot, single_pass_screenshot)

    # Blueprint round-trip
    score.blueprint_round_trip = check_blueprint_round_trip(multipass_html, mockup_service)

    # Issues
    if score.slot_count < MIN_SLOTS_PER_PAGE:
        score.issues.append(f"Slot count {score.slot_count} < {MIN_SLOTS_PER_PAGE}")
    if score.slot_retention < SLOT_RETENTION_THRESHOLD:
        score.issues.append(f"Slot retention {score.slot_retention:.2f} < {SLOT_RETENTION_THRESHOLD}")
    if score.text_fidelity < TEXT_FIDELITY_THRESHOLD:
        score.issues.append(f"Text fidelity {score.text_fidelity:.2f} < {TEXT_FIDELITY_THRESHOLD}")
    if score.escape_hatch_triggered:
        score.issues.append("Escape hatch triggered")
    if not score.blueprint_round_trip:
        score.issues.append("Blueprint round-trip failed")

    return score


def evaluate_benchmark(page_scores: List[PageScore]) -> BenchmarkResult:
    """Aggregate page scores into benchmark pass/fail result.

    Returns:
        BenchmarkResult with overall verdict and failure reasons.
    """
    result = BenchmarkResult(page_scores=page_scores)
    failures = []

    if not page_scores:
        result.passed = False
        result.failures = ["No pages evaluated"]
        return result

    # Slot count: all pages >= 5
    low_slot_pages = [s for s in page_scores if s.slot_count < MIN_SLOTS_PER_PAGE]
    if low_slot_pages:
        failures.append(
            f"{len(low_slot_pages)}/{len(page_scores)} pages below "
            f"{MIN_SLOTS_PER_PAGE} slots minimum"
        )

    # Slot retention: all pages >= 90%
    low_retention = [s for s in page_scores if s.slot_retention < SLOT_RETENTION_THRESHOLD]
    if low_retention:
        failures.append(
            f"{len(low_retention)}/{len(page_scores)} pages below "
            f"{SLOT_RETENTION_THRESHOLD:.0%} slot retention"
        )

    # Text fidelity: all pages >= 0.85
    low_text = [s for s in page_scores if s.text_fidelity < TEXT_FIDELITY_THRESHOLD]
    if low_text:
        failures.append(
            f"{len(low_text)}/{len(page_scores)} pages below "
            f"{TEXT_FIDELITY_THRESHOLD} text fidelity"
        )

    # Blueprint round-trip: 100%
    failed_rt = [s for s in page_scores if not s.blueprint_round_trip]
    if failed_rt:
        failures.append(
            f"{len(failed_rt)}/{len(page_scores)} pages failed blueprint round-trip"
        )

    # No escape hatches
    escapes = [s for s in page_scores if s.escape_hatch_triggered]
    if escapes:
        failures.append(
            f"{len(escapes)}/{len(page_scores)} pages triggered escape hatch"
        )

    # Visual fidelity (if data available)
    ssim_scores = [
        s for s in page_scores
        if s.visual_ssim is not None and s.single_pass_ssim is not None
    ]
    if ssim_scores:
        import statistics
        mp_median = statistics.median([s.visual_ssim for s in ssim_scores])
        sp_median = statistics.median([s.single_pass_ssim for s in ssim_scores])

        if mp_median < sp_median + SSIM_IMPROVEMENT_DELTA:
            failures.append(
                f"SSIM median {mp_median:.4f} not above single-pass "
                f"{sp_median:.4f} + {SSIM_IMPROVEMENT_DELTA}"
            )

        wins = sum(1 for s in ssim_scores if s.visual_ssim > s.single_pass_ssim)
        win_rate = wins / len(ssim_scores)
        if win_rate < SSIM_WIN_RATE_THRESHOLD:
            failures.append(
                f"SSIM win rate {win_rate:.0%} < {SSIM_WIN_RATE_THRESHOLD:.0%}"
            )

        regressions = [
            s for s in ssim_scores
            if s.single_pass_ssim - s.visual_ssim > SSIM_MAX_REGRESSION
        ]
        if regressions:
            failures.append(
                f"{len(regressions)} page(s) with major SSIM regression "
                f"(> {SSIM_MAX_REGRESSION})"
            )

    # Latency: p95 < 90s
    latencies = sorted([s.latency_seconds for s in page_scores])
    p95_idx = int(len(latencies) * 0.95)
    p95_latency = latencies[min(p95_idx, len(latencies) - 1)]
    if p95_latency > MAX_LATENCY_P95_SECONDS:
        failures.append(f"Latency p95 {p95_latency:.1f}s > {MAX_LATENCY_P95_SECONDS}s")

    result.failures = failures
    result.passed = len(failures) == 0

    return result
