# Checkpoint 14: Voice Creation Fix — Dedicated Custom Voice Endpoint

**Date**: 2026-02-28
**Branch**: `feat/chainlit-agent-chat`
**Status**: RESOLVED — voice creation works via dedicated endpoint

---

## Root Cause

Voice was **never going to auto-extract from video elements**. The Kling API updated to a new architecture where voice cloning is a **separate operation** via a dedicated endpoint (`POST /v1/general/custom-voices`). The old approach of creating a video element and polling for `element_voice_info` was the wrong API flow.

The key clue: Section 3-50 in the NEW Kling API docs at `docs.qingque.cn` documents a **Create Custom Voice** endpoint that didn't exist in the old API spec we were referencing.

## What Changed

### New Kling API Endpoints (Sections 3-45 through 3-54)

| Section | Endpoint | Method | Description |
|---------|----------|--------|-------------|
| 3-45 | `/v1/general/advanced-custom-elements` | POST | Create element (image or video ref) |
| 3-46 | `/v1/general/advanced-custom-elements/{id}` | GET | Query single element |
| 3-47 | `/v1/general/advanced-custom-elements` | GET | List custom elements |
| 3-48 | `/v1/general/advanced-presets-elements` | GET | List preset elements |
| 3-49 | `/v1/general/delete-elements` | POST | Delete custom element |
| **3-50** | **`/v1/general/custom-voices`** | **POST** | **Create custom voice (NEW)** |
| 3-51 | `/v1/general/custom-voices/{id}` | GET | Query single voice |
| 3-52 | `/v1/general/custom-voices` | GET | List custom voices |
| 3-53 | `/v1/general/presets-voices` | GET | List preset voices |
| 3-54 | `/v1/general/delete-voices` | POST | Delete custom voice |

### Create Custom Voice (3-50) — Request Schema

```json
POST /v1/general/custom-voices
{
  "voice_name": "string",        // Required, max 20 chars
  "voice_url": "string",         // Optional — .mp3/.wav audio or .mp4/.mov video URL
  "video_id": "string",          // Optional — reference Kling-generated video (V2.6+/Avatar/LipSync)
  "callback_url": "string",      // Optional
  "external_task_id": "string"   // Optional
}
```

- `voice_url` or `video_id` must be provided (mutually exclusive)
- Audio must be 5-30 seconds, clean speech, one speaker
- Supported video formats: .mp4, .mov
- Supported audio formats: .mp3, .wav

### Create Custom Voice (3-50) — Response Schema

```json
{
  "code": 0,
  "message": "SUCCEED",
  "request_id": "string",
  "data": {
    "task_id": "string",
    "task_status": "submitted",
    "task_info": { "external_task_id": "string" },
    "created_at": 1722769557708,
    "updated_at": 1722769557708
  }
}
```

### Query Custom Voice (3-51) — Response Schema (on success)

```json
{
  "code": 0,
  "message": "SUCCEED",
  "data": {
    "task_id": "string",
    "task_status": "succeed",
    "task_result": {
      "voices": [{
        "voice_id": "string",
        "voice_name": "string",
        "trial_url": "string",
        "owned_by": "string",
        "status": "succeed"
      }]
    },
    "final_unit_deduction": "0.05",
    "created_at": 1722769557708,
    "updated_at": 1722769557708
  }
}
```

### Create Element (3-45) — Updated Request Body Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `element_name` | string | Yes | Max 20 chars |
| `element_description` | string | Yes | Max 100 chars |
| `reference_type` | string | Yes | `video_refer` or `image_refer` |
| `element_image_list` | object | For images | `{frontal_image, refer_images}` |
| `element_video_list` | object | For video | `{refer_videos: [{video_url}]}` |
| `element_voice_id` | string | No | **Bind existing voice to element** |
| `tag_list` | array | No | `[{tag_id: "o_102"}]` for Character |
| `callback_url` | string | No | |
| `external_task_id` | string | No | |

Key note from docs: *"The tone of element can be bound to existing tone colors in the tone library. The ID can be obtained through the voice-related API."*

### Query Element (3-46) — Response includes voice_info when bound

```json
"element_voice_info": {
  "voice_id": "string",
  "voice_name": "string",
  "trial_url": "string",
  "owned_by": "string"
}
```

### Delete Custom Voice (3-54)

```json
POST /v1/general/delete-voices
{ "voice_id": "string" }
```

## Test Results

Voice creation via the new endpoint succeeded immediately:

```
POST /v1/general/custom-voices
  voice_name: "test_voice_v2"
  voice_url: <Kling CDN video URL from existing element>

Response (after 15s poll):
  task_status: "succeed"
  voice_id: "856607216122601495"
  voice_name: "test_voice_v2"
  trial_url: <.wav file URL>
  final_unit_deduction: "0.05"
```

Compare: The old approach of polling `element_voice_info` for 15+ minutes never returned a voice.

## New Workflow

### Before (broken)
```
Upload video → Create video element → Poll element for voice_info → (never appears)
```

### After (working)
```
Upload video → Create custom voice (5-30s) → Get voice_id
             → Create video element with element_voice_id → Element has voice bound
```

## Files Changed

| File | Changes |
|------|---------|
| `viraltracker/services/kling_models.py` | Added `KlingEndpoint.CUSTOM_VOICES/DELETE_VOICES/PRESETS_VOICES`, `KlingGenerationType.CUSTOM_VOICE`, `CreateVoiceRequest` model, `KlingVoiceResult` model |
| `viraltracker/services/kling_video_service.py` | Added voice CRUD: `create_custom_voice()`, `query_custom_voice()`, `query_custom_voices_list()`, `query_preset_voices()`, `delete_custom_voice()`. Added endpoint paths for voice URLs. |
| `viraltracker/services/avatar_service.py` | Rewrote `extract_voice_from_video()` to use Create Custom Voice endpoint instead of element voice auto-extraction. Rewrote `create_kling_video_element()` to create voice first then element with `element_voice_id`. Replaced `_poll_for_voice_info()` with `_poll_for_voice_completion()` and `_poll_for_element_id()`. |
| `scripts/test_custom_voice.py` | Test script for voice creation endpoint |
| `scripts/scrape_kling_docs.py` | Playwright scraper for qingque.cn docs |

## Cost

Voice creation costs 0.05 units per voice (very cheap).

## Scraping Notes

The Kling docs at `docs.qingque.cn` are:
- JS-rendered (requires Playwright, not simple HTTP fetch)
- Lazy-loaded (must scroll past sections to load them)
- Some sections are collapsed with toggle arrows
- The page uses ant-tree for the TOC sidebar
- Content loads into `.vodka-page-content-wrapper`
