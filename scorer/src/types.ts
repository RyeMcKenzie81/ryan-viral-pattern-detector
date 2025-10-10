/**
 * TypeScript type definitions for the scoring engine
 */

// Re-export Zod-inferred types
export type {
  ScorerInput,
  ScorerOutput,
  Measures,
  Subscores,
  Diagnostics,
} from './schema.js';

// ============================================================================
// Configuration Types
// ============================================================================

export interface ScorerConfig {
  weights: WeightConfig;
  normalization: NormalizationConfig;
}

export interface WeightConfig {
  hook: number;
  story: number;
  relatability: number;
  visuals: number;
  audio: number;
  watchtime: number;
  engagement: number;
  shareability: number;
  algo: number;
}

export interface NormalizationConfig {
  enabled: boolean;
  targetMean: number;
  targetStd: number;
}

// ============================================================================
// Penalty Types
// ============================================================================

export interface PenaltyFactors {
  spam_indicators: number;
  low_quality_signals: number;
  excessive_length: number;
  poor_formatting: number;
}

// ============================================================================
// Constants
// ============================================================================

export const DEFAULT_WEIGHTS: WeightConfig = {
  hook: 0.18,        // 18% - First impression critical
  story: 0.10,       // 10% - Narrative structure
  relatability: 0.06, // 6%  - Audience connection
  visuals: 0.08,     // 8%  - Production quality
  audio: 0.06,       // 6%  - Sound/music
  watchtime: 0.25,   // 25% - Retention signals (highest weight)
  engagement: 0.15,  // 15% - Social proof
  shareability: 0.07, // 7%  - Viral mechanics
  algo: 0.05,        // 5%  - Platform optimization
};

export const DEFAULT_NORMALIZATION: NormalizationConfig = {
  enabled: true,
  targetMean: 70,
  targetStd: 10,
};

export const SCORER_VERSION = '1.1.0';
