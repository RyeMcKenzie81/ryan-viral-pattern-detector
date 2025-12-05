# Checkpoint: Sprint 2 - Brand Research Analysis Complete

**Date**: 2025-12-05
**Branch**: `feature/brand-research-pipeline`
**Status**: Analysis methods complete, UI and persona synthesis pending

---

## Overview

Sprint 2 implements comprehensive ad analysis for building 4D customer personas. The system can now analyze:
- **Video ads** - Full transcript, hooks, visual elements, persona signals
- **Image ads** - Visual analysis, text overlays, style detection
- **Ad copy** - Headlines, body text, hooks, messaging patterns

All analysis extracts **4D persona-relevant data** that maps directly to the personas_4d schema.

---

## Analysis Methods in BrandResearchService

### Video Analysis
```python
# Single video
await service.analyze_video(asset_id, storage_path, brand_id)

# From direct URL (for testing)
await service.analyze_video_from_url(video_url)

# Batch processing
await service.analyze_videos_batch(asset_ids, brand_id)
```

### Image Analysis
```python
# Single image
await service.analyze_image(asset_id, image_base64, brand_id)

# Batch processing
await service.analyze_images_batch(asset_ids, brand_id)
```

### Copy Analysis
```python
# Single ad copy
await service.analyze_copy(ad_id, ad_copy, headline, brand_id)

# Batch processing (all ads for brand)
await service.analyze_copy_batch(brand_id, limit=50)
```

### Asset Management
```python
# Download videos/images to storage
await service.download_assets_for_brand(brand_id, limit=50)

# Get unanalyzed video assets
service.get_video_assets_for_brand(brand_id, only_unanalyzed=True)
```

---

## 4D Persona Fields Extracted

Each analysis type extracts the same core fields for persona building:

| Field | Description | 4D Mapping |
|-------|-------------|------------|
| `target_persona` | Demographics, lifestyle, identity statements | Demographics, Self-narratives |
| `desires_appealed_to` | care_protection, freedom_from_fear, social_approval, etc. | Desires (Dimension 2) |
| `transformation` | before/after states | Transformation Map |
| `pain_points` | emotional, functional | Pain Points (Dimension 6) |
| `benefits_outcomes` | emotional, functional results | Outcomes/JTBD (Dimension 6) |
| `brand_voice` | tone, key phrases | Brand Voice |
| `worldview` | values, villains, heroes | Worldview (Dimension 5) |
| `testimonial` | speaker type, quotes, results | Social Proof |
| `objections_handled` | concerns addressed | Buying Objections |
| `activation_events` | purchase triggers | Activation Events (Dimension 7) |

---

## Database Schema

### Tables Used

**`brand_ad_analysis`** - Stores all analysis results
- `analysis_type`: 'image_vision', 'video_vision', 'copy_analysis', 'synthesis'
- `raw_response`: Full JSON response from AI
- `extracted_hooks`: Structured hook data
- `extracted_benefits`: Flattened benefits list
- `pain_points`: Flattened pain points
- `persona_signals`: Target persona data
- `brand_voice_notes`: Brand voice JSON

**`scraped_ad_assets`** - Downloaded video/image files
- `storage_path`: Path in Supabase storage
- `mime_type`: video/mp4, image/jpeg, etc.
- `facebook_ad_id`: Link to source ad

### Migrations Required
```sql
-- Add video_vision to analysis types (already run)
ALTER TABLE brand_ad_analysis DROP CONSTRAINT IF EXISTS brand_ad_analysis_analysis_type_check;
ALTER TABLE brand_ad_analysis ADD CONSTRAINT brand_ad_analysis_analysis_type_check
    CHECK (analysis_type IN ('image_vision', 'video_vision', 'video_storyboard', 'copy_analysis', 'synthesis'));
```

---

## Analysis Prompts

### VIDEO_ANALYSIS_PROMPT
Extracts from video:
- Hook (first 3 seconds transcript + type)
- Full transcript
- Text overlays
- Target persona signals
- Desires, transformation, pain points
- Benefits/outcomes
- Testimonial content
- Brand voice and worldview

### IMAGE_ANALYSIS_PROMPT
Extracts from images:
- Visual style and colors
- Text overlays and headlines
- Product visibility
- Emotional tone
- Persona signals

### COPY_ANALYSIS_PROMPT
Extracts from ad text:
- Hook and headline
- Target persona
- Desires and pain points
- Claims and social proof
- Call to action
- Brand voice

---

## Testing Results

### Wonder Paws Video Analysis
Successfully analyzed video showing:
```json
{
  "hook": {
    "transcript": "If you have a senior dog like I do, listen to this.",
    "hook_type": "curiosity"
  },
  "target_persona": {
    "age_range": "30-55",
    "gender_focus": "female",
    "lifestyle": ["pet parent", "senior dog owner"],
    "identity_statements": ["I'm the kind of person who will do anything..."]
  },
  "transformation": {
    "before": ["Dog was slowing down with low energy"],
    "after": ["Dog is moving faster and has more energy"]
  }
}
```

---

## Files Modified

```
viraltracker/services/brand_research_service.py
├── VIDEO_ANALYSIS_PROMPT (updated for 4D)
├── COPY_ANALYSIS_PROMPT (new)
├── analyze_video()
├── analyze_video_from_url() (new)
├── analyze_videos_batch() (new)
├── analyze_copy() (new)
├── analyze_copy_batch() (new)
├── download_assets_for_brand() (new)
├── get_video_assets_for_brand() (new)
├── _download_video_to_temp() (new)
├── _save_video_analysis() (new)
└── _save_copy_analysis() (new)

migrations/
└── 2025-12-05_add_video_vision_type.sql (new)
```

---

## Next Steps (Remaining for Sprint 2)

### 1. Brand Research UI Page
Create `19_🔬_Brand_Research.py` with:
- [ ] Brand selector
- [ ] "Download Assets" button
- [ ] "Analyze Images" button
- [ ] "Analyze Videos" button
- [ ] "Analyze Copy" button
- [ ] Progress indicators
- [ ] Analysis results preview

### 2. Persona Synthesis
Add `synthesize_to_personas()` method:
- [ ] Aggregate all analyses for brand
- [ ] Cluster similar persona signals
- [ ] Generate 1-3 suggested personas
- [ ] Populate 4D fields from aggregated data
- [ ] Confidence scoring per persona

### 3. Multi-Persona Detection
- [ ] Detect distinct customer segments from data
- [ ] Suggest multiple personas if segments differ
- [ ] Allow user to review and approve
- [ ] Link personas to products

---

## Commits in This Sprint

```
b59244d feat: Add video analysis with Gemini for 4D persona extraction
a073b19 feat: Add asset download and video_vision analysis type
4583a3a feat: Add copy/headline analysis for 4D persona extraction
```

---

## Usage Example

```python
from viraltracker.services.brand_research_service import BrandResearchService
from uuid import UUID
import asyncio

async def analyze_brand(brand_id: str):
    service = BrandResearchService()
    brand_uuid = UUID(brand_id)

    # 1. Download assets to storage
    download_result = await service.download_assets_for_brand(brand_uuid, limit=50)
    print(f"Downloaded {download_result['videos_downloaded']} videos")

    # 2. Analyze videos
    video_assets = service.get_video_assets_for_brand(brand_uuid)
    video_ids = [UUID(v['id']) for v in video_assets]
    video_results = await service.analyze_videos_batch(video_ids, brand_uuid)

    # 3. Analyze copy
    copy_results = await service.analyze_copy_batch(brand_uuid, limit=50)

    # 4. Analyze images (existing method)
    # ... similar pattern

    print(f"Analyzed {len(video_results)} videos, {len(copy_results)} copy")

asyncio.run(analyze_brand("bc8461a8-232d-4765-8775-c75eaafc5503"))
```

---

## Related Documents

- `/docs/CHECKPOINT_2025-12-04_SPRINT1_URL_MAPPING_COMPLETE.md` - URL mapping system
- `/docs/plans/4D_PERSONA_IMPLEMENTATION_PLAN.md` - Full persona framework
- `/CLAUDE.md` - Development guidelines
