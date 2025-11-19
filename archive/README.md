# Archive

This directory contains legacy code and historical documentation that has been superseded by the current ViralTracker system.

## Legacy Code (`legacy-code/`)

### ryan-viral-pattern-detector/
Original Instagram scraping and analysis tool (September 2024). This was the first iteration of the system, built specifically for Instagram Reels.

**Superseded by:**
- `viraltracker/scrapers/instagram.py` - Modern Instagram scraper
- `viraltracker/importers/instagram.py` - URL importer
- `viraltracker/cli/scrape.py` - Unified scraping CLI

**Status:** Deprecated, retained for reference

### video-processor/
Original video processing and analysis tool with Yakety Pack-specific evaluator (September-October 2024).

**Superseded by:**
- `viraltracker/processing/` - Video download and processing
- `viraltracker/analysis/video_analyzer.py` - Generic, product-aware video analysis
- `viraltracker/cli/process.py` and `viraltracker/cli/analyze.py` - Modern CLI

**Status:** Deprecated, retained for reference

## Historical Documentation (`../docs/archive/`)

The `docs/archive/` directory contains:
- **Phase documentation** (PHASE_*.md) - Implementation phases from the multi-brand refactoring (Phases 1-6.4)
- **Checkpoints** (CHECKPOINT_*.md) - Historical snapshots from October 2024 development
- **Session summaries** (SESSION_SUMMARY*.md) - Development session notes
- **Implementation docs** - Original plans for TikTok, YouTube, scoring engine, etc.
- **Status reports** (PROJECT_STATUS*.md) - Outdated project status documents
- **Handoff documents** (HANDOFF_*.md, CONTINUATION_PROMPT*.md) - Context for continuing work

## Why Archived?

The original tools were built for single-brand (Yakety Pack) analysis. In October 2024, the system was refactored to support:
- **Multi-brand, multi-platform architecture**
- **Generic product adapters** (no hardcoded product context)
- **Unified CLI** (`./vt`) for all platforms
- **Modern database schema** with proper relationships
- **Hook Intelligence v1.2.0** with advanced AI analysis

The legacy tools remain functional but are no longer maintained.

## Current System

For current documentation, see:
- **[Main README](../README.md)** - Project overview and quick start
- **[CLI Guide](../docs/CLI_GUIDE.md)** - Complete command reference
- **[Hook Analysis Guide](../docs/HOOK_ANALYSIS_GUIDE.md)** - Statistical analysis methods
- **[CHANGELOG](../CHANGELOG.md)** - Recent changes and updates

---

**Last Updated:** 2025-10-16
