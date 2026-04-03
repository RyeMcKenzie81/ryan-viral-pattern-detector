# ViralTracker Documentation

Welcome to the ViralTracker documentation! Choose your path:

## 🎯 Quick Navigation

### For Developers
- [Developer Guide](DEVELOPER_GUIDE.md) - Setup, contributing, testing
- [Architecture Overview](ARCHITECTURE.md) - System design and patterns
- [Multi-Tenant Auth](MULTI_TENANT_AUTH.md) - Organizations, feature flags, usage tracking, data isolation

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
| [MULTI_TENANT_AUTH.md](MULTI_TENANT_AUTH.md) | Multi-tenant auth & authorization | All developers |
| [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md) | Dev setup & workflows | New contributors |
| [CLAUDE_CODE_GUIDE.md](CLAUDE_CODE_GUIDE.md) | AI-assisted development | Claude Code, AI tools |
| [CLI_GUIDE.md](CLI_GUIDE.md) | Command reference | End users |

### Specialized Guides
- [Hook Analysis Guide](HOOK_ANALYSIS_GUIDE.md) - Statistical analysis methods
- [Facebook Ads Ingestion](workflows/facebook_ads_ingestion.md) - FB Ad Library scraping
- [Content Buckets](CONTENT_BUCKETS.md) - Bulk image/video categorization, Drive import/export, upload tracking

### Video Generation & Avatars
- **Kling AI Integration**: Omni Video, avatar talking-head, lip-sync, multi-shot, custom elements
  - Service: `viraltracker/services/kling_video_service.py`
  - Models: `viraltracker/services/kling_models.py`
- **Brand Avatars**: 4-angle reference images, video elements with voice binding
  - Service: `viraltracker/services/avatar_service.py`
  - Models: `viraltracker/services/veo_models.py` (BrandAvatar)
  - UI: `viraltracker/ui/pages/47_🎭_Avatars.py`
- **Video Tools Suite Plan**: [docs/plans/video-tools-suite/](plans/video-tools-suite/)
  - [Checkpoint 11: Video Avatar with Voice](plans/video-tools-suite/CHECKPOINT_11_VIDEO_AVATAR_WITH_VOICE.md)

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

### SEO Content Pipeline
Full 7-phase content workflow: keyword discovery, competitor analysis, AI content generation, QA, Shopify publishing, interlinking, analytics.

| Phase | Document | Status |
|-------|----------|--------|
| Plan & Implementation | [PLAN_INTEGRATION_TESTS.md](plans/seo-pipeline-port/PLAN_INTEGRATION_TESTS.md) | Complete |
| Phase 4 Checkpoint | [CHECKPOINT_PHASE_4.md](plans/seo-pipeline-port/CHECKPOINT_PHASE_4.md) | Complete |
| Phase 5 Checkpoint | [CHECKPOINT_PHASE_5.md](plans/seo-pipeline-port/CHECKPOINT_PHASE_5.md) | Complete |
| Phase 6 Checkpoint | [CHECKPOINT_PHASE_6.md](plans/seo-pipeline-port/CHECKPOINT_PHASE_6.md) | Complete |
| Phase 7 Checkpoint | [CHECKPOINT_PHASE_7.md](plans/seo-pipeline-port/CHECKPOINT_PHASE_7.md) | Complete |
| Post-Review | [CHECKPOINT_POST_REVIEW.md](plans/seo-pipeline-port/CHECKPOINT_POST_REVIEW.md) | Complete |
| Integration Tests | [CHECKPOINT_INTEGRATION_TESTS.md](plans/seo-pipeline-port/CHECKPOINT_INTEGRATION_TESTS.md) | Complete |
| Live Testing & Deploy | [CHECKPOINT_LIVE_DEPLOY.md](plans/seo-pipeline-port/CHECKPOINT_LIVE_DEPLOY.md) | Complete |

**Architecture**: See [architecture.md](architecture.md#seo-content-pipeline) for full details.

### Activity Feed
Real-time event timeline showing system activity across all brands and job types, with rich media thumbnail previews for visual events.

- [Phase 3 Plan: Rich Media Cards](plans/activity-feed-phase3/PLAN.md) — Thumbnail preview grids in event cards for `ads_generated` and `templates_scraped` events

### Historical/Archive
- [Pydantic AI Refactor](archive/pydantic-ai-refactor/) - Migration history
- [Legacy Docs](archive/) - Session summaries and old checkpoints

---

**Version**: 0.19.5.0 (Iteration Lab: Custom Changes & Multi-Variable)
**Last Updated**: 2026-04-03
