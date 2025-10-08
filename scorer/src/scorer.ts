/**
 * Main scoring orchestrator
 * Coordinates all subscores and produces final output
 */

import type { ScorerInput, ScorerOutput, Subscores, Diagnostics } from './schema.js';
import { ScorerInputSchema } from './schema.js';
import {
  scoreHook,
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
// Diagnostics: Track missing data
// ============================================================================

function generateDiagnostics(input: ScorerInput): Diagnostics {
  const missing: string[] = [];
  let totalFields = 0;
  let presentFields = 0;

  // Check critical fields in measures
  const checks = [
    { path: 'hook.effectiveness_score', value: input.measures.hook.effectiveness_score },
    { path: 'story.storyboard', value: input.measures.story.storyboard },
    { path: 'story.arc_detected', value: input.measures.story.arc_detected },
    { path: 'visuals.overlays', value: input.measures.visuals.overlays },
    { path: 'visuals.edit_rate_per_10s', value: input.measures.visuals.edit_rate_per_10s },
    { path: 'audio.trending_sound_used', value: input.measures.audio.trending_sound_used },
    { path: 'audio.beat_sync_score', value: input.measures.audio.beat_sync_score },
    { path: 'watchtime.avg_watch_pct', value: input.measures.watchtime.avg_watch_pct },
    { path: 'watchtime.completion_rate', value: input.measures.watchtime.completion_rate },
    { path: 'shareability.has_cta', value: input.measures.shareability.has_cta },
  ];

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
  };
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

  // Calculate all subscores
  const subscores: Subscores = {
    hook: scoreHook(validated.measures.hook),
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

  // Calculate penalties
  const penaltyFactors = scorePenalties(validated.measures, {
    length_sec: validated.meta.length_sec,
  });
  const penalties = calculateTotalPenalty(penaltyFactors);

  // Calculate weighted overall score
  let rawOverall =
    subscores.hook * weights.hook +
    subscores.story * weights.story +
    subscores.relatability * weights.relatability +
    subscores.visuals * weights.visuals +
    subscores.audio * weights.audio +
    subscores.watchtime * weights.watchtime +
    subscores.engagement * weights.engagement +
    subscores.shareability * weights.shareability +
    subscores.algo * weights.algo -
    penalties;

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
  const output: ScorerOutput = {
    version: SCORER_VERSION,
    subscores,
    penalties,
    overall: Math.round(overall * 10) / 10, // Round to 1 decimal
    weights,
    diagnostics,
    flags: {
      incomplete,
      low_confidence,
    },
  };

  return output;
}
