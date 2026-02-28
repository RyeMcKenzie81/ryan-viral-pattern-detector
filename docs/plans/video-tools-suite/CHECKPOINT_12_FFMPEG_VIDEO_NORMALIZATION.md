# Checkpoint 12: FFmpeg Video Normalization for Kling Elements

**Date**: 2026-02-28
**Branch**: `feat/chainlit-agent-chat`
**Status**: Implemented, pending deployment testing

---

## Summary

Added FFmpeg video preprocessing before uploading videos to Kling's element creation API. Kling silently fails voice extraction when videos don't meet exact specs — no error is returned, but `element_voice_info` is never populated. This fix normalizes all uploaded videos to Kling's exact requirements before upload.

### Problem

Our test video (`testvideo4.mp4`) was 1080x1942 (not 1080x1920), H.264 High profile (not Main), 44.1kHz stereo audio (not 48kHz mono). Kling created the visual element successfully but `element_voice_info` was completely absent after 2+ minutes of polling. No error was returned — voice extraction just silently didn't happen.

### Root Cause Analysis (from Kling API docs research)

Per Kling's API documentation ("Only supports 1080P videos ... 16:9 or 9:16"), voice extraction fails silently when:

1. **Non-exact dimensions** — 1080x1942 is not valid 1080x1920
2. **Wrong audio format** — Voice extraction expects AAC-LC, 48kHz, mono
3. **H.264 profile/level mismatch** — High profile instead of Main
4. **Variable frame rate or odd pixel formats**
5. **Insufficient polling time** — Voice extraction can take 15+ minutes

### Solution

Two changes:

1. **`FFmpegService.normalize_video_for_kling()`** — New sync method that re-encodes any video to exact Kling specs:
   - Scale + crop to exact 1080x1920 (portrait) or 1920x1080 (landscape)
   - H.264 Main profile, level 4.1, CRF 18, yuv420p
   - 30fps forced
   - AAC-LC audio at 128kbps, 48kHz, mono
   - SAR 1:1, movflags +faststart
   - Capped at 8 seconds
   - Validates audio track exists and duration >= 3s

2. **Voice polling timeout extended** — From 8 attempts x 15s (2 min) to 60 attempts x 15s (15 min)

---

## Files Changed

| File | Change |
|------|--------|
| `viraltracker/services/ffmpeg_service.py` | Added `normalize_video_for_kling()` method, updated module docstring |
| `viraltracker/services/avatar_service.py` | Call normalize before upload in `extract_voice_from_video()` and `create_kling_video_element()`, extended voice polling to 15 min |

## FFmpeg Command Details

```
ffmpeg -y -i input.mp4 -t 8 \
  -vf "scale=W:H:force_original_aspect_ratio=increase,crop=W:H,setsar=1,fps=30,format=yuv420p" \
  -c:v libx264 -profile:v main -level 4.1 -preset medium -crf 18 -pix_fmt yuv420p \
  -map 0:v:0 -map 0:a:0 \
  -c:a aac -b:a 128k -ar 48000 -ac 1 \
  -movflags +faststart \
  output.mp4
```

Key decisions:
- **`force_original_aspect_ratio=increase` + `crop`** instead of direct scale — avoids any distortion, crops minimal edges instead
- **`-map 0:a:0`** without `?` suffix — fails explicitly if no audio (which is what we want, since voice extraction requires speech)
- **48kHz mono** — per Kling's voice extraction pipeline expectations
- **Always re-encodes** even if specs already match — guarantees correct output, takes <5s for typical 7MB files

## Verification

Local test with `testvideo4.mp4` (1080x1942, H.264 High, 44.1kHz stereo):

| Spec | Before | After |
|------|--------|-------|
| Resolution | 1080x1942 | 1080x1920 |
| H.264 Profile | High | Main |
| H.264 Level | 42 | 41 |
| FPS | 30 | 30 |
| Audio Sample Rate | 44100 | 48000 |
| Audio Channels | 2 (stereo) | 1 (mono) |
| Audio Bitrate | 137kbps | 128kbps |
| File Size | 9.1MB | 3.2MB |

## Next Steps

1. Deploy and test in UI — upload video, verify `element_voice_info` is populated with `voice_id`
2. If voice extraction still fails after normalization + 15min polling, investigate signed URL expiry (Supabase default 1hr should be sufficient)
3. Clean up `scripts/check_element_voice.py` after verification
