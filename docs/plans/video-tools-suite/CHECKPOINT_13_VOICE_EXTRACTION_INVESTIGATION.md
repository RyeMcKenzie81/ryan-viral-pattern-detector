# Checkpoint 13: Kling Voice Extraction Investigation

**Date**: 2026-02-28
**Branch**: `feat/chainlit-agent-chat` (merged to `feat/ad-creator-v2-phase0`)
**Status**: BLOCKED — voice extraction never returns `element_voice_info`

---

## The Problem

When creating video-based Kling elements via `POST /v1/general/advanced-custom-elements` with `reference_type: "video_refer"`, the element is created successfully (visual works), but **`element_voice_info` is completely absent** from the query response. Not null — the key doesn't exist at all.

We need `element_voice_info.voice_id` to get consistent voice across multi-scene Omni Videos. Image-based elements can't carry voice, and Omni-Video has no `voice_list` parameter.

## What We Tried (All Failed)

| Attempt | Result |
|---------|--------|
| Raw video upload (1072x1928) | No voice_info |
| Manually trimmed video (1080x1942) | No voice_info |
| FFmpeg normalized (exact 1080x1920, H.264 Main/4.1, AAC 48kHz mono, 30fps) | No voice_info |
| Extended polling from 2 min to 15 min (60x15s) | No voice_info after 15 min |
| Added `tag_list: [{"tag_id": "o_102"}]` (Character) | No voice_info |
| Verified signed URL (200, Content-Length, Range 206) | URL is fine |
| Increased signed URL expiry from 1hr to 24hr | No voice_info |
| Verified Kling's stored copy has audio (AAC 48kHz mono) | Audio present, still no voice |

## What We Know

### Our Create Element Payload
```json
POST https://api-singapore.klingai.com/v1/general/advanced-custom-elements/
{
  "element_name": "Mr. Jeff Authority",
  "element_description": "Video avatar: Mr. Jeff Authority",
  "reference_type": "video_refer",
  "element_video_list": {
    "refer_videos": [{"video_url": "<supabase-signed-url>"}]
  },
  "tag_list": [{"tag_id": "o_102"}],
  "external_task_id": "<uuid>"
}
```

### Actual Query Response (after element succeeds)
```json
{
  "code": 0,
  "message": "SUCCEED",
  "data": {
    "task_id": "856528333369769993",
    "task_status": "succeed",
    "task_result": {
      "elements": [{
        "element_id": 856528387816046601,
        "element_name": "Mr. Jeff Authority",
        "element_description": "Video avatar: Mr. Jeff Authority",
        "element_type": "video_refer",
        "element_image_list": {},
        "element_video_list": {
          "refer_videos": [{"video_url": "https://v15-kling.klingai.com/..."}]
        },
        "owned_by": "855722760281784413",
        "status": "succeed",
        "tag_list": [{"id": "o_102", "name": "Character", "description": "None"}]
      }]
    }
  }
}
```

**Note**: `element_voice_info` key is completely absent. Per docs it should contain `voice_id`, `voice_name`, `trial_url`, `owned_by`.

### Kling's Stored Video Has Audio
```
ffprobe on Kling's v15-kling.klingai.com URL:
Video: 1080x1920, h264, yuv420p
Audio: aac, 48000Hz, mono
```

## New API Documentation Found

A NEW version of the Kling API docs exists at:
```
https://docs.qingque.cn/d/home/eZQDkhg4h2Qg8SEVSUTBdzYeY?identityId=2Cn18n4EIHT
```

This is a Chinese doc platform (轻雀文档) that requires JavaScript rendering. **WebFetch cannot read it** — must use Playwright.

### Key NEW Sections to Investigate

| Section | Title | Why It Matters |
|---------|-------|---------------|
| **3-45** | General - Create Element | Updated element creation — may have new required params |
| **3-46** | General - Query Custom Element (Single) | Response schema — does voice_info require something new? |
| **3-50** | General - Create Custom Voice | **NEW ENDPOINT** — may need to create voice separately first |
| **3-51** | General - Query Custom Voice (Single) | Query created voices |
| **3-52** | General - Query Custom Voice (List) | List voices |
| **3-53** | General - Query Presets Voice (List) | Preset voice library |
| **3-54** | General - Delete Custom Voice | Voice cleanup |

### How to Access with Playwright
```python
from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto('https://docs.qingque.cn/d/home/eZQDkhg4h2Qg8SEVSUTBdzYeY?identityId=2Cn18n4EIHT', timeout=60000)
    time.sleep(8)

    # Click section in TOC to navigate
    page.click('text=3-45 General - Create Element', timeout=5000)
    time.sleep(2)

    # Content is in: page.evaluate('document.querySelector("[class*=\\"page-content\\"]").innerText')
    # Sections may be collapsed — need to click expand arrows
    # Full page height is small (720px) so content loads in viewport
```

**Note**: The page renders as a single scrollable doc. Sections 3-50 to 3-54 (Custom Voice) are COLLAPSED by default — need to click the right-pointing arrows to expand them.

## Hypotheses (Ordered by Likelihood)

1. **Need to use new "Create Custom Voice" endpoint (3-50) separately** — voice may no longer auto-extract from video elements. May need: upload video → create voice → get voice_id → pass as element_voice_id when creating element
2. **Feature gating** — voice extraction may require specific account permissions or model version (`kling-video-o3` mentioned in old docs)
3. **Video content** — the test video may not contain clear enough human speech for voice detection
4. **Unknown new required parameter** — the new docs (3-45) may show a field we're missing

## Files Changed in This Session

| File | Changes |
|------|---------|
| `viraltracker/services/ffmpeg_service.py` | Added `normalize_video_for_kling()` — scale+crop, H.264 Main/4.1, AAC 48kHz mono |
| `viraltracker/services/avatar_service.py` | FFmpeg normalize before upload, URL verification, 24hr signed URLs, 15min voice polling, full JSON debug logging |
| `docs/plans/video-tools-suite/CHECKPOINT_12_FFMPEG_VIDEO_NORMALIZATION.md` | FFmpeg normalization checkpoint |

## Code Locations

- Element creation: `viraltracker/services/kling_video_service.py:1326` (`create_video_element`)
- Element query: `viraltracker/services/kling_video_service.py:1428` (`query_element`)
- Voice polling: `viraltracker/services/avatar_service.py:939` (`_poll_for_voice_info`)
- Video normalization: `viraltracker/services/ffmpeg_service.py:349` (`normalize_video_for_kling`)
- Avatar video methods: `viraltracker/services/avatar_service.py:1001` (`extract_voice_from_video`), line 1112 (`create_kling_video_element`)

## Railway Config

- Project: `pleasant-reverence`, all services have Kling keys
- To query Kling API locally: `railway link --project pleasant-reverence --service viraltracker-ui --environment production`, then use `railway variables` to get `KLING_ACCESS_KEY` and `KLING_SECRET_KEY`
