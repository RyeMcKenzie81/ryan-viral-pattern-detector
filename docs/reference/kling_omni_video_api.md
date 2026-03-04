# Kling Omni Video API Reference

> Scraped from official docs: https://docs.qingque.cn/d/home/eZQDkhg4h2Qg8SEVSUTBdzYeY?identityId=2Cn18n4EIHT
> Date: 2026-02-27

## Endpoint: POST `/v1/videos/omni-video`

**API Domain**: `https://api-singapore.klingai.com`

## Request Body Parameters

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `model_name` | string | Optional | `kling-video-o1` | Model name. Enum: `kling-video-o1`, `kling-v3-omni` |
| `multi_shot` | boolean | Optional | `false` | Multi-shot video. When `true`, `prompt` is invalid; when `false`, `shot_type` and `multi_prompt` are invalid |
| `shot_type` | string | Optional | None | Storyboard method. Enum: `customize`, `intelligence`. Required when `multi_shot=true` |
| `prompt` | string | Optional | None | Text prompt. Max 2500 chars. Supports `<<<element_1>>>`, `<<<image_1>>>`, `<<<video_1>>>`, `<<<voice_1>>>`. Required when `multi_shot=false` or `shot_type=intelligence` |
| `multi_prompt` | array | Optional | None | Storyboard info (index, prompt, duration). Required when `multi_shot=true` and `shot_type=customize` |
| `image_list` | array | Optional | None | Reference image list |
| `element_list` | array | Optional | None | Reference element list |
| `video_list` | array | Optional | None | Reference video list |
| `voice_list` | array | Optional | None | Voice list for voice control |
| `sound` | string | Optional | `off` | Enable audio generation. Enum: `on`, `off`. Only V2.6+ |
| `mode` | string | Optional | `pro` | Generation mode. Enum: `std`, `pro` |
| `aspect_ratio` | string | Optional | None | Frame aspect ratio. Enum: `16:9`, `9:16`, `1:1`. Required when not using start-frame or video editing |
| `duration` | string | Optional | `5` | Video length in seconds. Enum: `3,4,5,6,7,8,9,10,11,12,13,14,15` |
| `watermark_info` | object | Optional | None | Watermark config: `{"enabled": boolean}` |
| `callback_url` | string | Optional | None | Callback URL for task status changes |
| `external_task_id` | string | Optional | None | Custom task ID (must be unique per account) |

## voice_list Parameter (CRITICAL)

**Type**: `array`
**Required**: Optional
**Default**: None

**Description**: List of tones/voices referenced when generating videos.

**Format**:
```json
"voice_list": [
  {"voice_id": "voice_id_1"},
  {"voice_id": "voice_id_2"}
]
```

**Constraints**:
- Max **2 voices** per video generation task
- `voice_id` comes from Custom Voice API (`/v1/general/custom-voices`) or Preset Voices API, **NOT** Lip-Sync API
- When `voice_list` is not empty and prompt references voice, billed at "with voice generation" rate (higher cost)
- **`element_list` and `voice_list` are MUTUALLY EXCLUSIVE — cannot coexist**
- When specifying voice, `sound` parameter **must be `on`**

## How Voices Are Referenced in Prompts

Triple-angle-bracket syntax, 1-indexed matching order in `voice_list`:

```
<<<voice_1>>>
<<<voice_2>>>
```

**Example**:
```
The man <<<voice_1>>> said, "Hello.".
```

**Example (Image-to-Video with voice)**:
```
<<<voice_1>>>Ask the people in the picture to say the following words, 'Welcome everyone'
```

**Tips**:
- Simpler grammar = better results
- Use single quotes for dialogue within prompts
- Max 2 voice references per task

## image_list Parameter

**Type**: `array`
**Required**: Optional

**Format**:
```json
"image_list": [
  {
    "image_url": "image_url_or_base64",
    "type": "first_frame"
  },
  {
    "image_url": "image_url_or_base64",
    "type": "end_frame"
  }
]
```

**Constraints**:
- `type` values: `first_frame` (start frame), `end_frame` (end frame)
- Cannot have only end frame without first frame
- Supports Base64 encoding or image URL
- Formats: `.jpg`, `.jpeg`, `.png`
- Max file size: 10MB
- Min dimensions: 300px (width and height)
- Aspect ratio: 1:2.5 to 2.5:1
- With reference video: images + elements ≤ 4
- Without reference video: images + elements ≤ 7
- End frame not supported when >2 images
- Referenced in prompts as `<<<image_1>>>`, `<<<image_2>>>`, etc.

## element_list Parameter

**Type**: `array`
**Required**: Optional

**Format**:
```json
"element_list": [
  {"element_id": 12345},
  {"element_id": 67890}
]
```

**Constraints**:
- `element_id` is type `long` (integer)
- Based on element IDs from Element Library
- With first/last frames: max 3 subjects
- With reference video: images + elements ≤ 4
- Without reference video: images + elements ≤ 7
- **Mutually exclusive with `voice_list`**
- Referenced in prompts as `<<<element_1>>>`, `<<<element_2>>>`, etc.

## sound Parameter

**Type**: `string`
**Required**: Optional
**Default**: `off`

**Enum**: `on`, `off`

**Constraints**:
- Only V2.6+ model versions support this
- With reference video: value can only be `off`
- **Must be `on` when using voice control (`voice_list`)**

## Voice Control Support by Model

| Model | Mode | Voice Control |
|---|---|---|
| `kling-video-o1` | std/pro | Not supported |
| `kling-v3-omni` | std/pro | Not explicitly listed |
| `kling-v2-6` | std 5s/10s | Not supported |
| `kling-v2-6` | pro 5s | Supported |
| `kling-v2-6` | pro 10s | Supported |

## Billing for Voice Control

| Configuration | Duration | Cost |
|---|---|---|
| V2.6 Pro, with audio, WITHOUT voice control | 5s | $0.70 (5 units) |
| V2.6 Pro, with audio, WITHOUT voice control | 10s | $1.40 (10 units) |
| V2.6 Pro, with audio, WITH voice control | 5s | $0.84 (6 units) |
| V2.6 Pro, with audio, WITH voice control | 10s | $1.68 (12 units) |
| Custom Voice creation | per call | $0.007 (0.05 units) |

## Element-Voice Binding

When creating elements via `/v1/general/advanced-custom-elements`, you can bind a voice:

- **`element_voice_id`** (type: `long`/string, Optional): Binds existing voice to element
  - Only video-customized elements support voice binding
  - Audio videos uploaded during element creation can auto-trigger voice customization

Response includes `element_voice_info`:
```json
"element_voice_info": {
  "voice_id": "string",
  "voice_name": "string",
  "trial_url": "string",
  "owned_by": "kling"
}
```

## Complete Curl Example: Voice Control

```bash
curl --location 'https://api-singapore.klingai.com/v1/videos/image2video/' \
--header 'Authorization: Bearer {token}' \
--header 'Content-Type: application/json; charset=utf-8' \
--data '{
    "model_name": "kling-v2-6",
    "image": "image_url",
    "prompt": "<<<voice_1>>>Ask the people in the picture to say the following words, '\''Welcome everyone'\''",
    "voice_list": [
        {
            "voice_id": "your_voice_id_here"
        }
    ],
    "duration": "5",
    "mode": "pro",
    "sound": "on",
    "callback_url": "",
    "external_task_id": ""
}'
```

## Key Constraints Summary

1. **`voice_list` and `element_list` are MUTUALLY EXCLUSIVE**
2. **`sound` must be `on`** when using voice control
3. Max 2 voices per task
4. Voice control confirmed on `kling-v2-6 pro` mode
5. Voice IDs from Custom Voice API or Preset Voices, NOT Lip-Sync API
6. Prompts use `<<<voice_1>>>` syntax (1-indexed, matching voice_list order)
7. Use single quotes for dialogue within prompts
