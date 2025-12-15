# Checkpoint 023 - FFmpeg Audio Sync Fix (Final)

**Date:** 2025-12-15
**Branch:** `feature/trash-panda-content-pipeline`
**Status:** Phase 9 Complete - Comic Video Audio Sync Fixed

---

## Summary

After 3+ hours of debugging, we finally fixed the audio sync issue where panel 4's audio was starting during panel 3's visual playback. The root cause was a combination of FFmpeg issues with the concat demuxer approach.

---

## Root Cause Analysis

### The Problem
When rendering a comic video with 4 panels where panel 3 had no voice audio:
- Panel 1: Voice audio plays correctly
- Panel 2: Voice audio plays correctly
- Panel 3: Should show visual with silence
- Panel 4: Audio was starting RIGHT AFTER panel 2 ended (during panel 3's visual)

### Why It Happened

**Issue 1: Concat Demuxer Audio Drift**
The original implementation used FFmpeg's concat demuxer with `-c copy`:
```bash
ffmpeg -f concat -safe 0 -i list.txt -c copy output.mp4
```
This has a [known bug](https://trac.ffmpeg.org/ticket/5058) where segments with different audio sources (real voice vs generated silence) have timestamp mismatches, causing audio drift.

**Issue 2: Missing Audio Streams**
Segments without voice audio were sometimes missing audio streams entirely, causing concat to fail or misalign.

**Issue 3: SAR (Sample Aspect Ratio) Mismatch**
Different encoding paths produced different SARs (e.g., `1712:1719` vs `1:1`), causing the concat filter to fail with "parameters do not match" error.

---

## The Fix (Multi-Part)

### 1. Switched from Concat Demuxer to Concat Filter
The concat filter re-encodes everything, rebuilding the timeline from scratch:
```bash
# Old (broken):
ffmpeg -f concat -safe 0 -i list.txt -c copy output.mp4

# New (working):
ffmpeg -i seg1.mp4 -i seg2.mp4 ... \
  -filter_complex "[0:v][0:a][1:v][1:a]...concat=n=N:v=1:a=1[outv][outa]" \
  -map "[outv]" -map "[outa]" output.mp4
```

### 2. Silent Audio Generation for No-Voice Panels
Added `anullsrc` filter to generate silent audio for panels without voice:
```python
silent_audio = f"anullsrc=r=44100:cl=stereo,atrim=0:{total_duration_sec}[aout]"
```

### 3. Audio Stream Verification
Added ffprobe check before concatenation to verify all segments have audio:
```python
async def _has_audio_stream(self, video_path: Path) -> bool:
    # Uses ffprobe to check for audio stream

async def _add_silent_audio_to_segment(self, video_path: Path) -> Path:
    # Adds silent audio track if missing
```

### 4. SAR Normalization
Added `setsar=1:1` filter to normalize all segments before concat:
```python
# Normalize SAR for each segment before concat
for i in range(n):
    sar_filters.append(f"[{i}:v]setsar=1:1[v{i}]")
    concat_inputs.append(f"[v{i}][{i}:a]")
```

### 5. Minimum Duration for No-Audio Panels
Added 2-second minimum duration for panels without audio to prevent zero-length segments:
```python
MIN_NO_AUDIO_DURATION_MS = 2000
if content_duration_ms < MIN_NO_AUDIO_DURATION_MS:
    content_duration_ms = MIN_NO_AUDIO_DURATION_MS
```

---

## Files Modified

| File | Changes |
|------|---------|
| `comic_render_service.py` | Concat filter, SAR normalization, audio verification, silent audio generation, error logging |
| `CLAUDE.md` | Added "Third-Party Tool Research" section |
| `30_📝_Content_Pipeline.py` | Cache-busting for video URLs |

---

## Key Lesson Learned

**Always research third-party tools before implementing.**

We spent 3+ hours debugging issues that would have been avoided by reading FFmpeg documentation first. The concat demuxer vs concat filter trade-offs are well-documented.

Added to `CLAUDE.md`:
```markdown
## Third-Party Tool Research (CRITICAL)

Before implementing anything that uses external tools or libraries, ALWAYS:
1. Search for official documentation
2. Look for common pitfalls and best practices
3. Verify the approach before writing code

Take the extra 5 minutes to research. It saves hours of debugging.
```

---

## Git Commits This Session

1. `fix: Add cache-busting to final video URL`
2. `fix: Add minimum duration for panels without audio`
3. `fix: Replace concat demuxer with concat filter for audio sync`
4. `fix: Add audio stream verification before concat + docs update`
5. `fix: Show actual FFmpeg error instead of version spam`
6. `fix: Normalize SAR before concat to fix parameter mismatch`

---

## Final FFmpeg Filter Graph

For a 4-panel video where panel 3 has no audio:
```
[0:v]setsar=1:1[v0];
[1:v]setsar=1:1[v1];
[2:v]setsar=1:1[v2];
[3:v]setsar=1:1[v3];
[v0][0:a][v1][1:a][v2][2:a][v3][3:a]concat=n=4:v=1:a=1[outv][outa]
```

Each segment:
- Has normalized SAR (1:1)
- Has audio stream (real voice or generated silence)
- Is re-encoded during concat for proper timeline

---

## Testing Verified

- Panel 3 displays with silence for ~2 seconds
- Panel 4 audio starts when panel 4 visual begins
- Video timestamp updates on re-render (cache-busting working)
- All panels concatenate without errors

---

## Phase 9 Status: COMPLETE

The Comic Video feature is now fully functional with proper audio sync.

---

## References

- [FFmpeg Concatenate Wiki](https://trac.ffmpeg.org/wiki/Concatenate)
- [FFmpeg concat filter audio delay bug](https://trac.ffmpeg.org/ticket/5058)
- [FFmpeg concat missing audio stream](https://github.com/PHP-FFMpeg/PHP-FFMpeg/issues/712)
