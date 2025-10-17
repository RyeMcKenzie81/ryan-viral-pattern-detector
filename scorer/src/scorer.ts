/**
 * Main scoring orchestrator
 * Coordinates all subscores and produces final output
 */

import type { ScorerInput, ScorerOutput } from './schema.js';
import { ScorerInputSchema } from './schema.js';
import {
  scoreHookAdaptive,
  scoreHookContent,
  scoreStory,
  scoreRelatability,
  scoreVisuals,
  scoreAudio,
  scoreWatchtime,
  scoreEngagement,
  scoreShareability,
  scoreAlgo,
  scorePenalties,
  calculateTotalPenalty,
} from './formulas.js';
import { DEFAULT_WEIGHTS, DEFAULT_NORMALIZATION, SCORER_VERSION } from './types.js';
import type { WeightConfig } from './types.js';

// ============================================================================
// Helper Functions
// ============================================================================

function clamp(val: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, val));
}

function coverageCount(obj: any, keys: string[]): number {
  return keys.reduce((acc, k) => acc + (obj && obj[k] != null ? 1 : 0), 0);
}

// ============================================================================
// Diagnostics: Track missing data and coverage
// ============================================================================

function generateDiagnostics(input: ScorerInput): any {
  const m = input.measures;

  const coverage = {
    hook: coverageCount(m.hook, ['time_to_value_sec', 'first_frame_face_present_pct', 'first_2s_motion_intensity']),
    story: coverageCount(m.story, ['beats_count', 'avg_beat_length_sec', 'storyboard']),
    audio: coverageCount(m.audio, ['music_to_voice_db_diff', 'beat_sync_score', 'speech_intelligibility_score', 'trending_sound_used', 'original_sound_created']),
    shareability: coverageCount(m.shareability, ['emotion_intensity', 'simplicity_score']),
    visuals: coverageCount(m.visuals, ['avg_scene_duration_sec', 'edit_rate_per_10s', 'text_overlay_occlusion_pct']),
    algo: coverageCount(m.algo, ['caption_length_chars', 'hashtag_count', 'hashtag_niche_mix_ok']),
  };

  // Legacy missing array (for backwards compatibility)
  const missing: string[] = [];
  const checks = [
    { path: 'hook.time_to_value_sec', value: m.hook?.time_to_value_sec },
    { path: 'story.beats_count', value: m.story?.beats_count },
    { path: 'audio.beat_sync_score', value: m.audio?.beat_sync_score },
  ];

  let totalFields = 0;
  let presentFields = 0;

  for (const check of checks) {
    totalFields++;
    if (check.value !== undefined && check.value !== null) {
      presentFields++;
    } else {
      missing.push(check.path);
    }
  }

  const overall_confidence = presentFields / totalFields;

  return {
    missing,
    overall_confidence,
    coverage,
  };
}

// ============================================================================
// Weight Re-normalization (v1.1.0)
// ============================================================================

function renormalizeWeights(
  subscores: Record<string, number | null>,
  weights: WeightConfig
): WeightConfig {
  const keys = ['hook', 'story', 'relatability', 'visuals', 'audio', 'watchtime', 'engagement', 'shareability', 'algo'];
  const active = keys.filter(k => subscores[k] != null);
  const sum = active.reduce((a, k) => a + Math.max(0, weights[k as keyof WeightConfig] ?? 0), 0);

  const scaled: any = { ...weights };
  for (const k of keys) {
    scaled[k] = active.includes(k) ? (weights[k as keyof WeightConfig] / (sum || 1)) : 0;
  }

  return scaled as WeightConfig;
}

// ============================================================================
// Normalization (optional post-hoc adjustment)
// ============================================================================

function normalizeScore(
  rawScore: number,
  enabled: boolean = DEFAULT_NORMALIZATION.enabled,
  targetMean: number = DEFAULT_NORMALIZATION.targetMean,
  targetStd: number = DEFAULT_NORMALIZATION.targetStd
): number {
  if (!enabled) {
    return rawScore;
  }

  // Simple normalization: shift score towards target distribution
  // This is a simplified version - full normalization would require
  // dataset statistics across many videos

  // For now, apply gentle adjustment if score is extreme
  const currentMean = 60; // Assume formulas center around 60
  const currentStd = 15;  // Assume ~15 point spread

  const zScore = (rawScore - currentMean) / currentStd;
  const normalized = targetMean + (zScore * targetStd);

  return Math.max(0, Math.min(100, normalized));
}

// ============================================================================
// Main Scorer Function
// ============================================================================

export function scoreVideo(
  input: ScorerInput,
  weights: WeightConfig = DEFAULT_WEIGHTS,
  normalizeResults: boolean = DEFAULT_NORMALIZATION.enabled
): ScorerOutput {
  // Validate input
  const validated = ScorerInputSchema.parse(input);

  // Generate diagnostics
  const diagnostics = generateDiagnostics(validated);

  // Calculate hook score with v1.2.0 blending (70% pace + 30% content)
  const hookPace = scoreHookAdaptive(validated.measures.hook, validated.measures.hook_content);
  const hookContent = scoreHookContent(validated.measures.hook_content);
  let hookFinal: number | null = null;
  if (hookPace != null && hookContent != null) {
    hookFinal = clamp(0.7 * hookPace + 0.3 * hookContent, 0, 100);
  } else {
    hookFinal = hookPace ?? hookContent;
  }

  // Calculate all subscores (now returns null when missing)
  const subscores: any = {
    hook: hookFinal,
    story: scoreStory(validated.measures.story),
    relatability: scoreRelatability(validated.measures, {
      followers: validated.meta.followers,
    }),
    visuals: scoreVisuals(validated.measures.visuals),
    audio: scoreAudio(validated.measures.audio),
    watchtime: scoreWatchtime(validated.measures.watchtime),
    engagement: scoreEngagement(validated.measures.engagement),
    shareability: scoreShareability(validated.measures.shareability),
    algo: scoreAlgo(validated.measures.algo),
  };

  // Re-normalize weights over present subscores
  const normalizedWeights = renormalizeWeights(subscores, weights);

  // Calculate penalties
  const penaltyFactors = scorePenalties(validated.measures, {
    length_sec: validated.meta.length_sec,
  });
  const penalties = calculateTotalPenalty(penaltyFactors);

  // Calculate weighted overall score (only for present subscores)
  let rawOverall = 0;
  const keys = ['hook', 'story', 'relatability', 'visuals', 'audio', 'watchtime', 'engagement', 'shareability', 'algo'] as const;
  for (const k of keys) {
    if (subscores[k] != null) {
      rawOverall += (subscores[k] as number) * normalizedWeights[k];
    }
  }

  // Apply penalties
  rawOverall -= penalties;

  // Clamp to [0, 100]
  rawOverall = Math.max(0, Math.min(100, rawOverall));

  // Optional normalization
  const overall = normalizeResults
    ? normalizeScore(rawOverall, true)
    : rawOverall;

  // Determine flags
  const incomplete = diagnostics.missing.length > 3;
  const low_confidence = diagnostics.overall_confidence < 0.6;

  // Build output
  const output: any = {
    version: SCORER_VERSION,
    subscores,
    penalties,
    overall: Math.round(overall * 10) / 10, // Round to 1 decimal
    weights: normalizedWeights,
    diagnostics,
    flags: {
      incomplete,
      low_confidence,
    },
    score_details: {
      hook_attribution: {
        modality: validated.measures.hook_content?.hook_modality_attribution ?? null,
        top_motifs: validated.measures.hook_content?.hook_type_probs
          ? Object.entries(validated.measures.hook_content.hook_type_probs)
              .sort((a, b) => (b[1] ?? 0) - (a[1] ?? 0))
              .slice(0, 3)
              .map(([type, prob]) => ({ type, probability: prob }))
          : null,
      },
      hook_span: validated.measures.hook_content?.hook_span ?? null,
      payoff_time_sec: validated.measures.hook_content?.payoff_time_sec ?? null,
    },
  };

  return output;
}
