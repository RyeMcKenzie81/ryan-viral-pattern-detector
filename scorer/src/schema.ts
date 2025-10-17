/**
 * Zod schemas for TikTok video scoring input/output validation
 */

import { z } from 'zod';

// ============================================================================
// Input Schemas (from Python adapter)
// ============================================================================

export const HookMeasuresSchema = z.object({
  // v1.1.0 continuous fields
  time_to_value_sec: z.number().nullable().optional(),
  first_frame_face_present_pct: z.number().nullable().optional(),
  first_2s_motion_intensity: z.number().nullable().optional(),
  // Legacy v1.0.0 fields
  duration_sec: z.number().optional(),
  text: z.string().optional(),
  type: z.string().optional(),
  visual_description: z.string().optional(),
  effectiveness_score: z.number().min(0).max(10).optional(),
});

export const StoryMeasuresSchema = z.object({
  // v1.1.0 continuous fields
  beats_count: z.number().nullable().optional(),
  avg_beat_length_sec: z.number().nullable().optional(),
  storyboard: z.array(z.object({
    // v1.1.0 fields
    t_start: z.number().optional(),
    t_end: z.number().optional(),
    label: z.string().optional(),
    // Legacy v1.0.0 fields
    timestamp: z.number().optional(),
    duration: z.number().optional(),
    description: z.string().optional(),
  })).nullable().optional(),
  // Legacy v1.0.0 fields
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
  // v1.1.0 continuous fields
  music_to_voice_db_diff: z.number().nullable().optional(),
  beat_sync_score: z.number().nullable().optional(),
  speech_intelligibility_score: z.number().nullable().optional(),
  trending_sound_used: z.boolean().nullable().optional(),
  original_sound_created: z.boolean().nullable().optional(),
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

export const HookContentSchema = z.object({
  hook_type_probs: z.record(z.string(), z.number().min(0).max(1)).optional(),
  hook_modality_attribution: z.object({
    audio: z.number().min(0).max(1).nullable().optional(),
    visual: z.number().min(0).max(1).nullable().optional(),
    overlay: z.number().min(0).max(1).nullable().optional()
  }).optional(),
  hook_visual_catalysts: z.object({
    face_closeup: z.number().min(0).max(1).nullable().optional(),
    hands_object: z.number().min(0).max(1).nullable().optional(),
    large_motion_burst: z.number().min(0).max(1).nullable().optional(),
    color_pop: z.number().min(0).max(1).nullable().optional(),
    visual_evidence_present: z.boolean().nullable().optional(),
    first_frame_shot_type: z.enum([
      "face_closeup","hands_object","full_body_motion","product_macro","screen_recording","establishing","null"
    ]).nullable().optional(),
    skin_exposure_suggestive: z.boolean().nullable().optional()
  }).optional(),
  hook_audio_catalysts: z.object({
    spoken_question_present: z.boolean().nullable().optional(),
    spoken_callout_niche: z.boolean().nullable().optional(),
    spoken_numbers_present: z.boolean().nullable().optional(),
    prosody_energy: z.number().min(0).max(1).nullable().optional(),
    beat_drop_sync: z.number().min(0).max(1).nullable().optional()
  }).optional(),
  hook_overlay_catalysts: z.object({
    overlay_words_in_2s: z.number().min(0).nullable().optional(),
    overlay_chars_per_sec_2s: z.number().min(0).nullable().optional(),
    overlay_contrast_score: z.number().min(0).max(1).nullable().optional(),
    overlay_safe_area_pct: z.number().min(0).max(1).nullable().optional(),
    overlay_alignment_delay_ms: z.number().nullable().optional(),
    overlay_dup_spoken_pct: z.number().min(0).max(1).nullable().optional()
  }).optional(),
  hook_risk_flags: z.object({
    suggestive_visual_risk: z.boolean().nullable().optional(),
    violence_risk: z.boolean().nullable().optional(),
    minors_present_risk: z.boolean().nullable().optional(),
    medical_sensitive_risk: z.boolean().nullable().optional(),
    brand_logo_risk: z.boolean().nullable().optional()
  }).optional(),
  modifiers: z.object({
    stakes_clarity: z.number().min(0).max(1).nullable().optional(),
    curiosity_gap: z.number().min(0).max(1).nullable().optional(),
    specificity: z.number().min(0).max(1).nullable().optional()
  }).optional(),
  hook_span: z.object({ t_start: z.number().min(0), t_end: z.number().min(0) }).optional(),
  payoff_time_sec: z.number().min(0).optional(),
  hook_windows: z.object({
    w1_0_1s: z.any().optional(),
    w2_0_2s: z.any().optional(),
    w3_0_3s: z.any().optional(),
    w4_0_5s_or_hook_end: z.any().optional()
  }).optional()
}).optional();

export const MeasuresSchema = z.object({
  hook: HookMeasuresSchema,
  story: StoryMeasuresSchema,
  visuals: VisualsMeasuresSchema,
  audio: AudioMeasuresSchema,
  watchtime: WatchtimeMeasuresSchema,
  engagement: EngagementMeasuresSchema,
  shareability: ShareabilityMeasuresSchema,
  algo: AlgoMeasuresSchema,
  hook_content: HookContentSchema,
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
  hook: z.number().min(0).max(100).nullable(),
  story: z.number().min(0).max(100).nullable(),
  relatability: z.number().min(0).max(100).nullable(),
  visuals: z.number().min(0).max(100).nullable(),
  audio: z.number().min(0).max(100).nullable(),
  watchtime: z.number().min(0).max(100).nullable(),
  engagement: z.number().min(0).max(100).nullable(),
  shareability: z.number().min(0).max(100).nullable(),
  algo: z.number().min(0).max(100).nullable(),
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
