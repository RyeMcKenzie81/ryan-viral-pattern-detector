"""Multi-pass mockup generation pipeline.

Decomposes landing page HTML generation into 5 focused phases with
deterministic invariant enforcement between each pass.
"""

from .pipeline import MultiPassPipeline, PipelineRateLimiter
from .segmenter import SegmenterSection, segment_markdown
from .cropper import NormalizedBox, normalize_bounding_boxes, crop_section
from .invariants import (
    PipelineInvariants,
    SectionInvariant,
    capture_pipeline_invariants,
    check_section_invariant,
    check_global_invariants,
)
from .patch_applier import PatchApplier, ParsedSelector, parse_selector
from .popup_filter import PopupFilter

__all__ = [
    "MultiPassPipeline",
    "PipelineRateLimiter",
    "SegmenterSection",
    "segment_markdown",
    "NormalizedBox",
    "normalize_bounding_boxes",
    "crop_section",
    "PipelineInvariants",
    "SectionInvariant",
    "capture_pipeline_invariants",
    "check_section_invariant",
    "check_global_invariants",
    "PatchApplier",
    "ParsedSelector",
    "parse_selector",
    "PopupFilter",
]
