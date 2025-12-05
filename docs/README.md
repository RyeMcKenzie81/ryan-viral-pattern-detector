# ViralTracker Documentation

Welcome to the ViralTracker documentation! Choose your path:

## 🎯 Quick Navigation

### For Developers
- [Developer Guide](DEVELOPER_GUIDE.md) - Setup, contributing, testing
- [Architecture Overview](ARCHITECTURE.md) - System design and patterns

### For AI-Assisted Development (Claude Code)
- [Claude Code Guide](CLAUDE_CODE_GUIDE.md) - How to create agents, tools, and services

### For Users
- [User README](../README.md) - Features and getting started
- [CLI Guide](CLI_GUIDE.md) - Command-line reference

### For Architects & Technical Leadership
- [Architecture Overview](ARCHITECTURE.md) - System design, data flow, decisions
- [Pydantic AI Migration](archive/pydantic-ai-refactor/) - Historical context

## 📚 Document Index

### Core Documentation
| Document | Purpose | Audience |
|----------|---------|----------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System design & patterns | Architects, Senior Devs |
| [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md) | Dev setup & workflows | New contributors |
| [CLAUDE_CODE_GUIDE.md](CLAUDE_CODE_GUIDE.md) | AI-assisted development | Claude Code, AI tools |
| [CLI_GUIDE.md](CLI_GUIDE.md) | Command reference | End users |

### Specialized Guides
- [Hook Analysis Guide](HOOK_ANALYSIS_GUIDE.md) - Statistical analysis methods
- [Facebook Ads Ingestion](workflows/facebook_ads_ingestion.md) - FB Ad Library scraping

### Product Setup & Onboarding
- [Onboarding Checklist](../product_setup/ONBOARDING_CHECKLIST.md) - Brand/product onboarding process
- [Brand Data Template](../product_setup/templates/brand_data_template.py) - Data collection template

### Brand Research Pipeline (Active Development)
Build 4D customer personas from ad analysis:

| Phase | Status | Checkpoint |
|-------|--------|------------|
| Sprint 1: URL Mapping | Complete | [CHECKPOINT_2025-12-04_SPRINT1_URL_MAPPING_COMPLETE.md](CHECKPOINT_2025-12-04_SPRINT1_URL_MAPPING_COMPLETE.md) |
| Sprint 2: Ad Analysis | Complete | [CHECKPOINT_2025-12-05_SPRINT2_BRAND_RESEARCH_ANALYSIS.md](CHECKPOINT_2025-12-05_SPRINT2_BRAND_RESEARCH_ANALYSIS.md) |
| Sprint 2: UI & Synthesis | Complete | [CHECKPOINT_2025-12-05_SPRINT2_COMPLETE.md](CHECKPOINT_2025-12-05_SPRINT2_COMPLETE.md) |

**Key Features Implemented:**
- Video analysis with Gemini (transcripts, hooks, persona signals)
- Image analysis with Claude Vision
- Ad copy analysis for messaging patterns
- Brand Research UI page (`19_🔬_Brand_Research.py`)
- Persona synthesis with multi-segment detection
- 4D Persona builder UI (`17_👤_Personas.py`)

**Planning Docs:**
- [4D Persona Implementation Plan](plans/4D_PERSONA_IMPLEMENTATION_PLAN.md) - Full persona & competitor framework

### Historical/Archive
- [Pydantic AI Refactor](archive/pydantic-ai-refactor/) - Migration history
- [Legacy Docs](archive/) - Session summaries and old checkpoints

---

**Version**: 3.2.0 (Brand Research Pipeline - Sprint 2 Complete)
**Last Updated**: 2025-12-05
