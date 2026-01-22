# ViralTracker System Inventory

> **Auto-Discovery**: This document provides an overview of the system. For real-time accurate counts,
> use the UI Catalogs at `/pages/61_Agent_Catalog.py`, `/pages/62_Tools_Catalog.py`, and `/pages/63_Services_Catalog.py`.

Last Updated: 2025-01-22

---

## System Overview

ViralTracker is a comprehensive viral content tracking and ad creation platform built on a three-layer architecture:

```
┌─────────────────────────────────────────────────────┐
│              AGENT LAYER (PydanticAI)               │
│   Orchestrator → Specialized Agents → Tools         │
└─────────────────────────┬───────────────────────────┘
                          │ (thin wrappers)
┌─────────────────────────▼───────────────────────────┐
│              SERVICE LAYER (Core)                   │
│   Platform | AI/LLM | Content | Research | ...      │
└─────────────────────────┬───────────────────────────┘
                          │
       ┌──────────────────┼──────────────────┬────────┐
       │                  │                  │        │
       ▼                  ▼                  ▼        ▼
   ┌───────┐        ┌─────────┐        ┌────────┐  ┌─────┐
   │  CLI  │        │Streamlit│        │FastAPI │  │Agent│
   └───────┘        │   UI    │        │  API   │  │Chat │
                    └─────────┘        └────────┘  └─────┘
```

---

## 1. Agents

The agent layer uses PydanticAI with Claude Sonnet 4.5 for intelligent orchestration.

### 1.1 Orchestrator

| Agent | Role | Tools | Module |
|-------|------|-------|--------|
| **Orchestrator** | Intelligent request routing | 7 | `viraltracker.agent.orchestrator` |

The orchestrator analyzes user queries and routes them to specialized agents based on:
- Platform keywords (Twitter, TikTok, YouTube, Facebook)
- Task type (scraping, analysis, generation, audio)
- Context and intent

### 1.2 Specialized Agents

| Agent | Role | Tools | Module |
|-------|------|-------|--------|
| **Twitter Agent** | Twitter/X platform specialist | 8 | `viraltracker.agent.agents.twitter_agent` |
| **TikTok Agent** | TikTok platform specialist | 5 | `viraltracker.agent.agents.tiktok_agent` |
| **YouTube Agent** | YouTube platform specialist | 1 | `viraltracker.agent.agents.youtube_agent` |
| **Facebook Agent** | Facebook Ad Library specialist | 2 | `viraltracker.agent.agents.facebook_agent` |
| **Analysis Agent** | Advanced analytics and AI insights | 3 | `viraltracker.agent.agents.analysis_agent` |
| **Ad Creation Agent** | Facebook ad creative generation | 14+ | `viraltracker.agent.agents.ad_creation_agent` |
| **Audio Production Agent** | ElevenLabs audio generation | 11 | `viraltracker.agent.agents.audio_production_agent` |

**Total: 8 agents with 50+ tools**

---

## 2. Tools by Pipeline Stage

Tools are organized by their role in the data pipeline:

### Routing (Orchestrator)
| Tool | Description | Platform |
|------|-------------|----------|
| `route_to_twitter_agent` | Route to Twitter Agent | Orchestrator |
| `route_to_tiktok_agent` | Route to TikTok Agent | Orchestrator |
| `route_to_youtube_agent` | Route to YouTube Agent | Orchestrator |
| `route_to_facebook_agent` | Route to Facebook Agent | Orchestrator |
| `route_to_analysis_agent` | Route to Analysis Agent | Orchestrator |
| `route_to_ad_creation_agent` | Route to Ad Creation Agent | Orchestrator |
| `resolve_product_name` | Look up product by name | Orchestrator |

### Ingestion
| Tool | Description | Platform |
|------|-------------|----------|
| `search_twitter_tool` | Search and scrape tweets | Twitter |
| `search_tiktok_tool` | Search TikTok videos | TikTok |
| `search_youtube_tool` | Search YouTube videos | YouTube |
| `search_ads_tool` | Search Facebook Ad Library | Facebook |
| `scrape_user_tool` | Scrape TikTok user account | TikTok |
| `scrape_page_ads_tool` | Scrape Facebook page ads | Facebook |

### Filtration
| Tool | Description | Platform |
|------|-------------|----------|
| `validate_els_script` | Validate ELS script format | Audio |
| `get_top_tweets_tool` | Filter top tweets by engagement | Twitter |

### Discovery
| Tool | Description | Platform |
|------|-------------|----------|
| `find_outliers_tool` | Find viral outliers | Analysis |
| `find_comment_opportunities_tool` | Find comment opportunities | Twitter |

### Analysis
| Tool | Description | Platform |
|------|-------------|----------|
| `analyze_hooks_tool` | AI analysis of viral hooks | Analysis |
| `analyze_reference_ad` | Claude vision analysis | Ad Creation |
| `analyze_video_tool` | Analyze TikTok video | TikTok |
| `batch_analyze_videos_tool` | Batch analyze videos | TikTok |
| `analyze_search_term_tool` | Analyze keyword performance | Twitter |

### Generation
| Tool | Description | Platform |
|------|-------------|----------|
| `generate_content_tool` | Generate content from hooks | Twitter |
| `generate_nano_banana_prompt` | Create Gemini prompt | Ad Creation |
| `execute_nano_banana` | Generate ad image | Ad Creation |
| `select_hooks` | Smart hook selection | Ad Creation |
| `select_product_images` | Choose product images | Ad Creation |
| `generate_beat_audio` | Generate audio for beat | Audio |
| `assemble_final_audio` | Assemble final audio | Audio |

### Export
| Tool | Description | Platform |
|------|-------------|----------|
| `export_tweets_tool` | Export tweets to file | Twitter |
| `export_comments_tool` | Export comments to file | Twitter |
| `export_analysis_tool` | Export analysis results | Analysis |
| `export_tiktok_tool` | Export TikTok data | TikTok |
| `save_generated_ad` | Save ad to database | Ad Creation |
| `export_production` | Export audio production | Audio |

---

## 3. Services by Category

The service layer contains 60+ services organized by functional category.

### Platform Services
| Service | Description | Module |
|---------|-------------|--------|
| `TwitterService` | Twitter/X database operations | `viraltracker.services.twitter_service` |
| `TikTokService` | TikTok data operations | `viraltracker.services.tiktok_service` |
| `YouTubeService` | YouTube data operations | `viraltracker.services.youtube_service` |
| `FacebookService` | Facebook data operations | `viraltracker.services.facebook_service` |
| `MetaAdsService` | Meta Ads API integration | `viraltracker.services.meta_ads_service` |

### AI/LLM Services
| Service | Description | Module |
|---------|-------------|--------|
| `GeminiService` | Google Gemini AI integration | `viraltracker.services.gemini_service` |
| `VeoService` | Google Veo video generation | `viraltracker.services.veo_service` |
| `ElevenLabsService` | ElevenLabs voice synthesis | `viraltracker.services.elevenlabs_service` |
| `ELSParserService` | ElevenLabs Script parser | `viraltracker.services.els_parser_service` |

### Content Creation Services
| Service | Description | Module |
|---------|-------------|--------|
| `AdCreationService` | Facebook ad creation workflows | `viraltracker.services.ad_creation_service` |
| `CopyScaffoldService` | Ad copy scaffolding | `viraltracker.services.copy_scaffold_service` |
| `AudioProductionService` | Audio production orchestration | `viraltracker.services.audio_production_service` |
| `TemplateEvaluationService` | Template quality evaluation | `viraltracker.services.template_evaluation_service` |
| `TemplateRecommendationService` | Template recommendations | `viraltracker.services.template_recommendation_service` |
| `TemplateElementService` | Template element management | `viraltracker.services.template_element_service` |
| `TemplateQueueService` | Template queue management | `viraltracker.services.template_queue_service` |
| `AvatarService` | Avatar generation | `viraltracker.services.avatar_service` |

### Research & Analysis Services
| Service | Description | Module |
|---------|-------------|--------|
| `AngleCandidateService` | Angle candidate management | `viraltracker.services.angle_candidate_service` |
| `PatternDiscoveryService` | Pattern discovery clustering | `viraltracker.services.pattern_discovery_service` |
| `RedditSentimentService` | Reddit sentiment analysis | `viraltracker.services.reddit_sentiment_service` |
| `AmazonReviewService` | Amazon review analysis | `viraltracker.services.amazon_review_service` |
| `BrandResearchService` | Brand research and analysis | `viraltracker.services.brand_research_service` |
| `CompetitorService` | Competitor analysis | `viraltracker.services.competitor_service` |
| `BeliefAnalysisService` | Belief analysis pipeline | `viraltracker.services.belief_analysis_service` |
| `AdAnalysisService` | Ad performance analysis | `viraltracker.services.ad_analysis_service` |

### Business Logic Services
| Service | Description | Module |
|---------|-------------|--------|
| `PlanningService` | Ad planning workflows | `viraltracker.services.planning_service` |
| `PersonaService` | Persona management | `viraltracker.services.persona_service` |
| `ProductContextService` | Product context builder | `viraltracker.services.product_context_service` |
| `ProductOfferVariantService` | Product offer variants | `viraltracker.services.product_offer_variant_service` |
| `ProductUrlService` | Product URL management | `viraltracker.services.product_url_service` |

### Utility Services
| Service | Description | Module |
|---------|-------------|--------|
| `FFmpegService` | FFmpeg audio/video processing | `viraltracker.services.ffmpeg_service` |
| `StatsService` | Statistical calculations | `viraltracker.services.stats_service` |
| `CommentService` | Comment operations | `viraltracker.services.comment_service` |
| `ComparisonUtils` | Comparison utilities | `viraltracker.services.comparison_utils` |

### Integration Services
| Service | Description | Module |
|---------|-------------|--------|
| `ApifyService` | Apify scraping integration | `viraltracker.services.apify_service` |
| `SlackService` | Slack notifications | `viraltracker.services.slack_service` |
| `EmailService` | Email sending | `viraltracker.services.email_service` |
| `ScrapingService` | General scraping | `viraltracker.services.scraping_service` |
| `WebScrapingService` | Web content scraping | `viraltracker.services.web_scraping_service` |
| `AdScrapingService` | Ad-specific scraping | `viraltracker.services.ad_scraping_service` |
| `ClientOnboardingService` | Client onboarding | `viraltracker.services.client_onboarding_service` |

### Comic Video Services
| Service | Description | Module |
|---------|-------------|--------|
| `ComicVideoService` | Comic video orchestration | `viraltracker.services.comic_video.comic_video_service` |
| `ComicDirectorService` | Comic directing logic | `viraltracker.services.comic_video.comic_director_service` |
| `ComicRenderService` | Comic rendering | `viraltracker.services.comic_video.comic_render_service` |
| `ComicAudioService` | Comic audio production | `viraltracker.services.comic_video.comic_audio_service` |

### Content Pipeline Services
| Service | Description | Module |
|---------|-------------|--------|
| `ContentPipelineService` | Content pipeline orchestration | `viraltracker.services.content_pipeline.services.content_pipeline_service` |
| `TopicService` | Topic discovery and management | `viraltracker.services.content_pipeline.services.topic_service` |
| `ScriptService` | Script generation | `viraltracker.services.content_pipeline.services.script_service` |
| `AssetService` | Asset management | `viraltracker.services.content_pipeline.services.asset_service` |
| `AssetGenerationService` | Asset generation | `viraltracker.services.content_pipeline.services.asset_generation_service` |
| `HandoffService` | Pipeline handoffs | `viraltracker.services.content_pipeline.services.handoff_service` |
| `SoraService` | Sora video generation | `viraltracker.services.content_pipeline.services.sora_service` |
| `ComicService` | Comic generation | `viraltracker.services.content_pipeline.services.comic_service` |

### Knowledge Base Services
| Service | Description | Module |
|---------|-------------|--------|
| `DocService` | Document/RAG operations | `viraltracker.services.knowledge_base.service` |

---

## 4. Key Mappings

### Tool → Service Mapping

| Tool | Primary Service |
|------|-----------------|
| `search_twitter_tool` | `ScrapingService`, `TwitterService` |
| `get_top_tweets_tool` | `TwitterService` |
| `find_outliers_tool` | `StatsService` |
| `analyze_hooks_tool` | `GeminiService` |
| `generate_content_tool` | `GeminiService` |
| `analyze_reference_ad` | `AdCreationService` |
| `execute_nano_banana` | `GeminiService` |
| `generate_beat_audio` | `ElevenLabsService`, `FFmpegService` |
| `validate_els_script` | `ELSParserService` |

### Tool → Agent Mapping

| Agent | Tools |
|-------|-------|
| Orchestrator | `route_to_*`, `resolve_product_name` |
| Twitter Agent | `search_twitter_tool`, `get_top_tweets_tool`, `export_tweets_tool`, `find_comment_opportunities_tool`, `export_comments_tool`, `analyze_search_term_tool`, `generate_content_tool`, `verify_scrape_tool` |
| TikTok Agent | `search_tiktok_tool`, `scrape_user_tool`, `analyze_video_tool`, `batch_analyze_videos_tool`, `export_tiktok_tool` |
| YouTube Agent | `search_youtube_tool` |
| Facebook Agent | `search_ads_tool`, `scrape_page_ads_tool` |
| Analysis Agent | `find_outliers_tool`, `analyze_hooks_tool`, `export_analysis_tool` |
| Ad Creation Agent | `get_product_with_images`, `get_hooks_for_product`, `upload_reference_ad`, `analyze_reference_ad`, `select_hooks`, `select_product_images`, `generate_nano_banana_prompt`, `execute_nano_banana`, `save_generated_ad`, `review_ad_claude`, `review_ad_gemini`, `create_ad_run`, `complete_ad_workflow` |
| Audio Production Agent | `validate_els_script`, `parse_els_script`, `create_production_session`, `get_voice_settings`, `generate_beat_audio`, `regenerate_beat`, `select_take`, `list_session_takes`, `assemble_final_audio`, `get_session_status`, `export_production` |

---

## 5. Quick Reference

### File Locations

```
viraltracker/
├── agent/
│   ├── orchestrator.py          # Main orchestrator agent
│   ├── dependencies.py          # AgentDependencies (service container)
│   ├── tool_collector.py        # Tool discovery for catalog
│   ├── agent_collector.py       # Agent discovery for catalog
│   ├── service_collector.py     # Service discovery for catalog
│   └── agents/                   # Specialized agents
│       ├── twitter_agent.py
│       ├── tiktok_agent.py
│       ├── youtube_agent.py
│       ├── facebook_agent.py
│       ├── analysis_agent.py
│       ├── ad_creation_agent.py
│       └── audio_production_agent.py
├── services/                     # Service layer (60+ files)
│   ├── twitter_service.py
│   ├── gemini_service.py
│   ├── ad_creation_service.py
│   ├── ...
│   ├── comic_video/             # Comic video services
│   ├── content_pipeline/        # Content pipeline services
│   └── knowledge_base/          # Knowledge base services
└── ui/
    └── pages/
        ├── 61_🤖_Agent_Catalog.py
        ├── 62_📚_Tools_Catalog.py
        └── 63_⚙️_Services_Catalog.py
```

### Summary Statistics

| Component | Count |
|-----------|-------|
| **Agents** | 8 (1 orchestrator + 7 specialized) |
| **Tools** | 60+ |
| **Services** | 60+ |
| **Service Categories** | 11 |
| **UI Catalog Pages** | 3 |

---

## 6. Maintenance Notes

### Adding a New Agent

1. Create agent file in `viraltracker/agent/agents/`
2. Add tools using `@agent.tool()` decorator with metadata
3. Export from `viraltracker/agent/agents/__init__.py`
4. Add routing tool to orchestrator if needed
5. Agent will auto-appear in catalogs

### Adding a New Service

1. Create service file in `viraltracker/services/`
2. Follow `*Service` naming convention
3. Add docstrings for class and methods
4. Service will auto-appear in Services Catalog

### Adding a New Tool

1. Add to appropriate agent with `@agent.tool()` decorator
2. Include metadata with category, platform, rate_limit, use_cases, examples
3. Tool will auto-appear in Tools Catalog

---

*This document is generated manually but reflects the auto-discovered system inventory.
For real-time accurate counts, use the UI Catalog pages.*
