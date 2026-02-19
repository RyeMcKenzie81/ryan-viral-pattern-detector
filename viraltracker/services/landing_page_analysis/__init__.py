"""
Landing Page Analysis Service - Skills 1-5 pipeline.

Analyzes landing pages across four dimensions:
- Skill 1: Page Classification (awareness, sophistication, architecture)
- Skill 2: Element Detection (34 elements across 6 sections)
- Skill 3: Gap Analysis (missing elements vs ideal set)
- Skill 4: Copy Scoring (per-element quality scoring)
- Skill 5: Reconstruction Blueprint (maps analysis to brand-specific creative brief)
"""

from viraltracker.services.landing_page_analysis.analysis_service import (
    LandingPageAnalysisService,
)
from viraltracker.services.landing_page_analysis.brand_profile_service import (
    BrandProfileService,
)
from viraltracker.services.landing_page_analysis.blueprint_service import (
    ReconstructionBlueprintService,
)
from viraltracker.services.landing_page_analysis.chunk_markdown import (
    MarkdownChunk,
    chunk_markdown,
    pick_chunks_for_fields,
    extract_deterministic_snippet,
)
from viraltracker.services.landing_page_analysis.content_gap_filler_service import (
    ContentGapFillerService,
    GapFieldSpec,
    GAP_FIELD_REGISTRY,
    SourceCandidate,
    resolve_gap_key,
)
from viraltracker.services.landing_page_analysis.mockup_service import (
    MockupService,
)

__all__ = [
    "LandingPageAnalysisService",
    "BrandProfileService",
    "ReconstructionBlueprintService",
    "ContentGapFillerService",
    "GapFieldSpec",
    "GAP_FIELD_REGISTRY",
    "SourceCandidate",
    "resolve_gap_key",
    "MarkdownChunk",
    "chunk_markdown",
    "pick_chunks_for_fields",
    "extract_deterministic_snippet",
    "MockupService",
]
