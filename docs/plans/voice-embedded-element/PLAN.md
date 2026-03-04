# Plan: Fix Voice Binding — Embed Voice Audio into Calibration Video Before Element Creation

## Context

**Problem**: When creating a video element for the avatar, the voice extracted by Kling is from the calibration video's default TTS — not the Australian accent the user uploaded. The `element_voice_id` binding during element creation doesn't reliably make Kling use that voice during Omni video generation. `voice_list` and `element_list` are mutually exclusive in the API, so we can't pass both.

**Root cause**: The calibration video (generated from image element) uses Kling's default TTS for audio. When this video is passed to `create_video_element`, Kling auto-extracts the default voice, not the uploaded Australian voice. The `element_voice_id` parameter binds metadata but doesn't override what voice Kling actually uses.

**Fix**: Before creating the video element, use FFmpeg to replace the calibration video's audio with the audio from the user's uploaded voice sample. This produces a video with the correct visual (from images) AND the correct voice (from upload). Kling then auto-extracts the right voice when creating the element.

## New Workflow (3 phases in UI)

```
Phase 1: Upload Voice Sample
  └─ User uploads .mp4/.mov with Australian accent speech
  └─ FFmpeg extracts audio track → stored in session_state
  └─ Voice sample stored to Supabase (for reuse)

Phase 2: Generate & Preview Combined Video
  └─ Generate calibration video from image element (existing flow)
  └─ FFmpeg: replace calibration video audio with uploaded voice audio
  └─ Show combined video preview with st.video() for user confirmation
  └─ User clicks "Confirm & Create Element" to proceed

Phase 3: Create Video Element
  └─ Upload combined video to Kling → create_video_element (NO separate voice creation needed)
  └─ Kling auto-extracts voice from the embedded audio
  └─ Element now carries the correct voice natively
```

## Files to Modify

| File | Changes |
|------|---------|
| `viraltracker/services/ffmpeg_service.py` | Add `extract_audio()` and `replace_audio()` methods |
| `viraltracker/services/avatar_service.py` | Add `combine_video_with_voice()` method; modify `create_kling_video_element()` to skip separate voice creation when combined video provided |
| `viraltracker/ui/pages/47_🎭_Avatars.py` | Rewrite `render_video_avatar_section()` with preview/confirm flow |

---

## Implementation Details

### 1. FFmpeg Service — Two new methods

**`extract_audio(video_bytes: bytes) -> bytes`** in `ffmpeg_service.py`:
```python
# FFmpeg: extract audio track from video as AAC
# ffmpeg -i input.mp4 -vn -acodec aac -b:a 128k output.m4a
# Returns audio bytes. Raises ValueError if no audio track.
```

**`replace_audio(video_bytes: bytes, audio_bytes: bytes) -> bytes`** in `ffmpeg_service.py`:
```python
# FFmpeg: strip original audio, mux new audio onto video
# ffmpeg -i video.mp4 -i audio.m4a -c:v copy -c:a aac -b:a 128k -map 0:v:0 -map 1:a:0 -shortest output.mp4
# Returns combined video bytes.
# -shortest ensures output matches shorter of video/audio duration.
```

Both methods follow the existing pattern: write to temp files, run subprocess, read output, cleanup.

### 2. Avatar Service — New method + modified flow

**New `combine_video_with_voice(calibration_video_path: str, voice_audio_bytes: bytes) -> bytes`**:
- Download calibration video from Supabase storage
- Call `ffmpeg_service.replace_audio(video_bytes, audio_bytes)`
- Return combined video bytes (not uploaded yet — caller decides)

**Modify `create_kling_video_element()`** — add `combined_video_bytes: Optional[bytes] = None` param:
- When `combined_video_bytes` is provided: use it directly (normalize + upload), **skip** `create_custom_voice` step entirely AND skip `element_voice_id` param (voice is embedded in the video, Kling auto-extracts)
- When not provided: existing flow unchanged (backwards compatible)

### 3. Avatar UI — Rewrite `render_video_avatar_section()`

Replace the current 3-section layout with a clearer phased flow:

**Phase 1: Upload Voice Sample**
- File uploader for voice video (`.mp4/.mov`, 3-8s)
- On upload: extract audio via FFmpeg, store in `st.session_state.avatar_voice_audio_{avatar.id}`
- Upload voice video to Supabase for future reference
- Show audio duration and success message
- **No Kling custom voice creation** — voice lives in the element video only (saves ~5 min)
- If avatar already has a voice sample stored, show "Voice sample ready" with option to re-upload

**Phase 2: Generate & Preview Combined Video**
- Only enabled when voice audio is available (from phase 1 or previously extracted)
- Button: "Generate Combined Preview"
- Flow:
  1. Generate calibration video (or reuse existing `calibration_video_path`)
  2. Call `combine_video_with_voice()` to mux voice audio onto calibration video
  3. Upload combined video to temp storage, get signed URL
  4. Store combined bytes in `st.session_state.avatar_combined_video_{avatar.id}`
  5. Show `st.video()` preview wrapped in columns for sizing
  6. Caption: "Confirm this video has the correct voice before creating the element."

**Phase 3: Create Element**
- Only enabled when combined video is previewed and approved
- Button: "Confirm & Create Element"
- Calls `create_kling_video_element(avatar_id, ..., combined_video_bytes=combined_bytes)`
- This uploads the combined video and creates the element — Kling auto-extracts the voice

**Keep existing "Alternative: Upload Video" section** — for users who have their own video with both visual + voice already combined.

### 4. Cleanup: Revert prompt format change

Revert the `<<<element_1>>> says:` prompt change in `manual_video_service.py` back to using `[Speaker]:` format (or just include dialogue naturally). The voice fix is at element creation time, not prompt time.

---

## Session State Keys

| Key | Type | Purpose |
|-----|------|---------|
| `avatar_voice_audio_{id}` | `bytes` | Extracted audio from uploaded voice sample |
| `avatar_voice_video_path_{id}` | `str` | Storage path of uploaded voice sample |
| `avatar_combined_video_{id}` | `bytes` | Combined calibration video + voice audio |
| `avatar_combined_url_{id}` | `str` | Signed URL for preview |

---

## Implementation Steps

1. Add `extract_audio()` to `FFmpegService`
2. Add `replace_audio()` to `FFmpegService`
3. Add `combine_video_with_voice()` to `AvatarService`
4. Add `combined_video_bytes` param to `create_kling_video_element()` with skip-voice-creation logic
5. Rewrite `render_video_avatar_section()` with phased flow + preview
6. Revert `<<<element_1>>> says:` prompt change in `manual_video_service.py`
7. `python3 -m py_compile` all changed files
8. Test: upload voice sample → generate preview → confirm preview has correct voice → create element → generate scene video → verify voice matches

## Verification

1. Upload a voice sample video with Australian accent
2. Click "Generate Combined Preview" — watch the preview video, confirm it has the Australian voice audio
3. Click "Confirm & Create Element" — element is created from combined video
4. Go to Video Studio → Manual Creator → generate a scene with dialogue
5. Verify the generated scene uses the Australian accent voice
