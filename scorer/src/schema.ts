/**
 * Zod schemas for TikTok video scoring input/output validation
 */

import { z } from 'zod';

// ============================================================================
// Input Schemas (from Python adapter)
// ============================================================================

export const HookMeasuresSchema = z.object({
  duration_sec: z.number(),
  text: z.string(),
  type: z.string().optional(), // e.g., "shock|curiosity|authority"
  visual_description: z.string().optional(),
  effectiveness_score: z.number().min(0).max(10).optional(),
});

export const StoryMeasuresSchema = z.object({
  storyboard: z.array(z.object({
    timestamp: z.number(),
    duration: z.number(),
    description: z.string(),
  })).optional(),
  beats_count: z.number().optional(),
  arc_detected: z.boolean().optional(),
});

export const VisualsMeasuresSchema = z.object({
  overlays: z.array(z.object({
    timestamp: z.number(),
    text: z.string(),
    style: z.string().optional(),
  })).optional(),
  edit_rate_per_10s: z.number().optional(),
  text_overlay_present: z.boolean().optional(),
});

export const AudioMeasuresSchema = z.object({
  trending_sound_used: z.boolean().optional(),
  original_sound_created: z.boolean().optional(),
  beat_sync_score: z.number().min(0).max(10).optional(),
});

export const WatchtimeMeasuresSchema = z.object({
  length_sec: z.number(),
  avg_watch_pct: z.number().min(0).max(100).optional(),
  completion_rate: z.number().min(0).max(100).optional(),
});

export const EngagementMeasuresSchema = z.object({
  views: z.number(),
  likes: z.number(),
  comments: z.number(),
  shares: z.number(),
  saves: z.number().optional(),
});

export const ShareabilityMeasuresSchema = z.object({
  caption_length_chars: z.number(),
  has_cta: z.boolean().optional(),
  save_worthy_signals: z.number().min(0).max(10).optional(),
});

export const AlgoMeasuresSchema = z.object({
  caption_length_chars: z.number(),
  hashtag_count: z.number(),
  hashtag_niche_mix_ok: z.boolean(),
  post_time_optimal: z.boolean().optional(),
});

export const MeasuresSchema = z.object({
  hook: HookMeasuresSchema,
  story: StoryMeasuresSchema,
  visuals: VisualsMeasuresSchema,
  audio: AudioMeasuresSchema,
  watchtime: WatchtimeMeasuresSchema,
  engagement: EngagementMeasuresSchema,
  shareability: ShareabilityMeasuresSchema,
  algo: AlgoMeasuresSchema,
});

export const MetaSchema = z.object({
  video_id: z.string().uuid(),
  post_time_iso: z.string(),
  followers: z.number(),
  length_sec: z.number(),
});

export const TranscriptSegmentSchema = z.object({
  timestamp: z.number(),
  speaker: z.string(),
  text: z.string(),
});

export const RawDataSchema = z.object({
  transcript: z.array(TranscriptSegmentSchema).optional(),
  hook_span: z.object({
    t_start: z.number(),
    t_end: z.number(),
  }).optional(),
  storyboard: z.any().optional(), // Full JSON from video_analysis
  overlays: z.any().optional(),   // Full JSON from video_analysis
});

// Main input schema
export const ScorerInputSchema = z.object({
  meta: MetaSchema,
  measures: MeasuresSchema,
  raw: RawDataSchema.optional(),
});

// ============================================================================
// Output Schemas
// ============================================================================

export const SubscoresSchema = z.object({
  hook: z.number().min(0).max(100),
  story: z.number().min(0).max(100),
  relatability: z.number().min(0).max(100),
  visuals: z.number().min(0).max(100),
  audio: z.number().min(0).max(100),
  watchtime: z.number().min(0).max(100),
  engagement: z.number().min(0).max(100),
  shareability: z.number().min(0).max(100),
  algo: z.number().min(0).max(100),
});

export const WeightsSchema = z.object({
  hook: z.number(),
  story: z.number(),
  relatability: z.number(),
  visuals: z.number(),
  audio: z.number(),
  watchtime: z.number(),
  engagement: z.number(),
  shareability: z.number(),
  algo: z.number(),
});

export const DiagnosticsSchema = z.object({
  missing: z.array(z.string()),
  overall_confidence: z.number().min(0).max(1),
});

export const FlagsSchema = z.object({
  incomplete: z.boolean(),
  low_confidence: z.boolean().optional(),
});

export const ScorerOutputSchema = z.object({
  version: z.string(),
  subscores: SubscoresSchema,
  penalties: z.number().min(0),
  overall: z.number().min(0).max(100),
  weights: WeightsSchema,
  diagnostics: DiagnosticsSchema.optional(),
  flags: FlagsSchema.optional(),
});

// ============================================================================
// Type exports (inferred from schemas)
// ============================================================================

export type ScorerInput = z.infer<typeof ScorerInputSchema>;
export type ScorerOutput = z.infer<typeof ScorerOutputSchema>;
export type Measures = z.infer<typeof MeasuresSchema>;
export type Subscores = z.infer<typeof SubscoresSchema>;
export type Diagnostics = z.infer<typeof DiagnosticsSchema>;
