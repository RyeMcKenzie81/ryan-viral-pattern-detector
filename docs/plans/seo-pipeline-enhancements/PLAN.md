# SEO Pipeline Enhancement Plan

Plan saved for context recovery. See implementation conversation for full details.

## Phases
1. **Pre-Req**: CMS publisher platform filter fix
2. **Phase 1**: Dashboard without project requirement (brand-level overview, zero-state UX)
3. **Phase 2**: Article image generation (Gemini + Supabase Storage)
4. **Phase 3**: External analytics (GSC, GA4, Shopify conversions)

## Key Files
- `services/seo_pipeline/services/cms_publisher_service.py` - Pre-req fix
- `services/seo_pipeline/services/seo_analytics_service.py` - Phase 1
- `services/seo_pipeline/services/cluster_management_service.py` - Phase 1 (brand-level clusters was already implemented as `list_clusters()` takes project_id)
- `ui/pages/48_🔍_SEO_Dashboard.py` - Phase 1 + 3
- `services/seo_pipeline/services/seo_image_service.py` - Phase 2 (NEW)
- `services/seo_pipeline/nodes/image_generation.py` - Phase 2 (NEW)
- `services/seo_pipeline/state.py` - Phase 2
- `services/seo_pipeline/nodes/qa_publish.py` - Phase 2
- `services/seo_pipeline/orchestrator.py` - Phase 2
- `ui/pages/51_📤_Article_Publisher.py` - Phase 2
- `services/seo_pipeline/utils.py` - Phase 3 (NEW)
- `services/seo_pipeline/services/base_analytics_service.py` - Phase 3 (NEW)
- `services/seo_pipeline/services/gsc_service.py` - Phase 3 (NEW)
- `services/seo_pipeline/services/ga4_service.py` - Phase 3 (NEW)
- `services/seo_pipeline/services/shopify_analytics_service.py` - Phase 3 (NEW)
- `worker/scheduler_worker.py` - Phase 3
