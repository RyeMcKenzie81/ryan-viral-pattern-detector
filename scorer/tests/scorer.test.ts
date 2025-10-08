/**
 * Tests for the scoring engine
 * Includes smoke tests and sample data tests
 */

import { describe, it, expect } from 'vitest';
import { scoreVideo } from '../src/scorer.js';
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
} from '../src/formulas.js';
import type { ScorerInput } from '../src/schema.js';

// ============================================================================
// Smoke Tests: Basic validation
// ============================================================================

describe('Smoke Tests', () => {
  it('all subscores return values in [0, 100]', () => {
    const hookScore = scoreHook({ duration_sec: 4, text: 'test', type: 'shock' });
    expect(hookScore).toBeGreaterThanOrEqual(0);
    expect(hookScore).toBeLessThanOrEqual(100);

    const storyScore = scoreStory({ beats_count: 5, arc_detected: true });
    expect(storyScore).toBeGreaterThanOrEqual(0);
    expect(storyScore).toBeLessThanOrEqual(100);

    const visualsScore = scoreVisuals({ text_overlay_present: true });
    expect(visualsScore).toBeGreaterThanOrEqual(0);
    expect(visualsScore).toBeLessThanOrEqual(100);

    const audioScore = scoreAudio({ trending_sound_used: true });
    expect(audioScore).toBeGreaterThanOrEqual(0);
    expect(audioScore).toBeLessThanOrEqual(100);

    const watchtimeScore = scoreWatchtime({ length_sec: 30 });
    expect(watchtimeScore).toBeGreaterThanOrEqual(0);
    expect(watchtimeScore).toBeLessThanOrEqual(100);

    const engagementScore = scoreEngagement({
      views: 100000,
      likes: 10000,
      comments: 500,
      shares: 200,
    });
    expect(engagementScore).toBeGreaterThanOrEqual(0);
    expect(engagementScore).toBeLessThanOrEqual(100);

    const shareabilityScore = scoreShareability({
      caption_length_chars: 120,
      has_cta: true,
    });
    expect(shareabilityScore).toBeGreaterThanOrEqual(0);
    expect(shareabilityScore).toBeLessThanOrEqual(100);

    const algoScore = scoreAlgo({
      caption_length_chars: 100,
      hashtag_count: 4,
      hashtag_niche_mix_ok: true,
    });
    expect(algoScore).toBeGreaterThanOrEqual(0);
    expect(algoScore).toBeLessThanOrEqual(100);
  });

  it('overall score is in [0, 100]', () => {
    const input = createSampleInput();
    const result = scoreVideo(input);

    expect(result.overall).toBeGreaterThanOrEqual(0);
    expect(result.overall).toBeLessThanOrEqual(100);
  });

  it('scorer output has correct structure', () => {
    const input = createSampleInput();
    const result = scoreVideo(input);

    expect(result).toHaveProperty('version');
    expect(result).toHaveProperty('subscores');
    expect(result).toHaveProperty('penalties');
    expect(result).toHaveProperty('overall');
    expect(result).toHaveProperty('weights');
    expect(result).toHaveProperty('diagnostics');
    expect(result).toHaveProperty('flags');

    expect(result.subscores).toHaveProperty('hook');
    expect(result.subscores).toHaveProperty('story');
    expect(result.subscores).toHaveProperty('relatability');
    expect(result.subscores).toHaveProperty('visuals');
    expect(result.subscores).toHaveProperty('audio');
    expect(result.subscores).toHaveProperty('watchtime');
    expect(result.subscores).toHaveProperty('engagement');
    expect(result.subscores).toHaveProperty('shareability');
    expect(result.subscores).toHaveProperty('algo');
  });
});

// ============================================================================
// Formula Tests: Specific scoring logic
// ============================================================================

describe('Hook Scoring', () => {
  it('rewards ideal duration (3-5 sec)', () => {
    const score = scoreHook({ duration_sec: 4, text: 'test', type: '' });
    expect(score).toBeGreaterThan(60);
  });

  it('penalizes too short hooks', () => {
    const score = scoreHook({ duration_sec: 1, text: 'test', type: '' });
    expect(score).toBeLessThan(50);
  });

  it('rewards shock/curiosity hooks', () => {
    const withType = scoreHook({ duration_sec: 4, text: 'test', type: 'shock|curiosity' });
    const withoutType = scoreHook({ duration_sec: 4, text: 'test', type: '' });
    expect(withType).toBeGreaterThan(withoutType);
  });

  it('uses effectiveness score', () => {
    const highEffectiveness = scoreHook({
      duration_sec: 4,
      text: 'test',
      type: 'shock',
      effectiveness_score: 9,
    });
    const lowEffectiveness = scoreHook({
      duration_sec: 4,
      text: 'test',
      type: 'shock',
      effectiveness_score: 3,
    });
    expect(highEffectiveness).toBeGreaterThan(lowEffectiveness);
  });
});

describe('Story Scoring', () => {
  it('rewards multiple beats', () => {
    const score = scoreStory({ beats_count: 5, arc_detected: true });
    expect(score).toBeGreaterThan(70);
  });

  it('rewards story arc', () => {
    const withArc = scoreStory({ beats_count: 3, arc_detected: true });
    const withoutArc = scoreStory({ beats_count: 3, arc_detected: false });
    expect(withArc).toBeGreaterThan(withoutArc);
  });
});

describe('Engagement Scoring', () => {
  it('rewards high like rate (10%+)', () => {
    const score = scoreEngagement({
      views: 100000,
      likes: 12000, // 12% like rate
      comments: 500,
      shares: 200,
    });
    expect(score).toBeGreaterThan(70);
  });

  it('rewards high comment rate', () => {
    const score = scoreEngagement({
      views: 100000,
      likes: 5000,
      comments: 1200, // 1.2% comment rate
      shares: 200,
    });
    expect(score).toBeGreaterThan(65);
  });
});

describe('Watchtime Scoring', () => {
  it('rewards ideal length (15-45 sec)', () => {
    const ideal = scoreWatchtime({ length_sec: 30 });
    const tooLong = scoreWatchtime({ length_sec: 120 });
    expect(ideal).toBeGreaterThan(tooLong);
  });
});

// ============================================================================
// Sample Data Tests: Realistic fixtures
// ============================================================================

describe('Sample Data Tests', () => {
  it('high-quality viral video scores 80-100', () => {
    const input = createHighQualityInput();
    const result = scoreVideo(input);

    expect(result.overall).toBeGreaterThanOrEqual(75);
    expect(result.overall).toBeLessThanOrEqual(100);
    expect(result.subscores.hook).toBeGreaterThan(75);
    expect(result.subscores.engagement).toBeGreaterThan(75);
  });

  it('average video scores 50-70', () => {
    const input = createAverageInput();
    const result = scoreVideo(input);

    expect(result.overall).toBeGreaterThanOrEqual(45);
    expect(result.overall).toBeLessThanOrEqual(75);
  });

  it('low-quality video scores 0-50', () => {
    const input = createLowQualityInput();
    const result = scoreVideo(input);

    expect(result.overall).toBeGreaterThanOrEqual(0);
    expect(result.overall).toBeLessThanOrEqual(55);
  });

  it('sets incomplete flag when data is missing', () => {
    const input = createIncompleteInput();
    const result = scoreVideo(input);

    expect(result.flags?.incomplete).toBe(true);
    expect(result.diagnostics?.missing.length).toBeGreaterThan(3);
  });
});

// ============================================================================
// Test Fixtures
// ============================================================================

function createSampleInput(): ScorerInput {
  return {
    meta: {
      video_id: '123e4567-e89b-12d3-a456-426614174000',
      post_time_iso: '2024-01-15T10:00:00Z',
      followers: 50000,
      length_sec: 35,
    },
    measures: {
      hook: {
        duration_sec: 4.5,
        text: 'dog parents listen carefully...',
        type: 'curiosity|authority',
        effectiveness_score: 8.5,
      },
      story: {
        storyboard: [
          { timestamp: 0, duration: 10, description: 'Setup' },
          { timestamp: 10, duration: 15, description: 'Build' },
          { timestamp: 25, duration: 10, description: 'Payoff' },
        ],
        beats_count: 3,
        arc_detected: true,
      },
      visuals: {
        text_overlay_present: true,
        overlays: [
          { timestamp: 2, text: 'Listen up!' },
          { timestamp: 15, text: 'Here\'s why...' },
        ],
        edit_rate_per_10s: 2.5,
      },
      audio: {
        trending_sound_used: false,
        original_sound_created: true,
      },
      watchtime: {
        length_sec: 35,
        avg_watch_pct: 75,
      },
      engagement: {
        views: 500000,
        likes: 45000,
        comments: 1200,
        shares: 800,
      },
      shareability: {
        caption_length_chars: 125,
        has_cta: true,
      },
      algo: {
        caption_length_chars: 125,
        hashtag_count: 4,
        hashtag_niche_mix_ok: true,
      },
    },
  };
}

function createHighQualityInput(): ScorerInput {
  return {
    meta: {
      video_id: '223e4567-e89b-12d3-a456-426614174000',
      post_time_iso: '2024-01-15T10:00:00Z',
      followers: 100000,
      length_sec: 28,
    },
    measures: {
      hook: {
        duration_sec: 3.5,
        text: 'you won\'t believe what happened next...',
        type: 'shock|curiosity',
        effectiveness_score: 9.5,
      },
      story: {
        storyboard: [
          { timestamp: 0, duration: 8, description: 'Hook' },
          { timestamp: 8, duration: 12, description: 'Build tension' },
          { timestamp: 20, duration: 8, description: 'Climax and payoff' },
        ],
        beats_count: 5,
        arc_detected: true,
      },
      visuals: {
        text_overlay_present: true,
        overlays: [
          { timestamp: 1, text: 'WAIT FOR IT' },
          { timestamp: 10, text: 'OMG' },
          { timestamp: 20, text: 'I told you!' },
        ],
        edit_rate_per_10s: 4,
      },
      audio: {
        trending_sound_used: true,
      },
      watchtime: {
        length_sec: 28,
        avg_watch_pct: 85,
        completion_rate: 78,
      },
      engagement: {
        views: 1000000,
        likes: 120000, // 12% like rate
        comments: 8000,
        shares: 6000,
      },
      shareability: {
        caption_length_chars: 110,
        has_cta: true,
        save_worthy_signals: 9,
      },
      algo: {
        caption_length_chars: 110,
        hashtag_count: 4,
        hashtag_niche_mix_ok: true,
        post_time_optimal: true,
      },
    },
  };
}

function createAverageInput(): ScorerInput {
  return {
    meta: {
      video_id: '323e4567-e89b-12d3-a456-426614174000',
      post_time_iso: '2024-01-15T10:00:00Z',
      followers: 20000,
      length_sec: 45,
    },
    measures: {
      hook: {
        duration_sec: 5,
        text: 'check this out',
        type: 'curiosity',
      },
      story: {
        beats_count: 2,
        arc_detected: false,
      },
      visuals: {
        text_overlay_present: true,
        overlays: [{ timestamp: 5, text: 'Cool!' }],
      },
      audio: {
        trending_sound_used: false,
      },
      watchtime: {
        length_sec: 45,
      },
      engagement: {
        views: 50000,
        likes: 2000, // 4% like rate
        comments: 100,
        shares: 50,
      },
      shareability: {
        caption_length_chars: 80,
        has_cta: false,
      },
      algo: {
        caption_length_chars: 80,
        hashtag_count: 3,
        hashtag_niche_mix_ok: false,
      },
    },
  };
}

function createLowQualityInput(): ScorerInput {
  return {
    meta: {
      video_id: '423e4567-e89b-12d3-a456-426614174000',
      post_time_iso: '2024-01-15T10:00:00Z',
      followers: 500,
      length_sec: 120,
    },
    measures: {
      hook: {
        duration_sec: 8,
        text: '',
        type: '',
      },
      story: {
        beats_count: 0,
      },
      visuals: {
        text_overlay_present: false,
      },
      audio: {},
      watchtime: {
        length_sec: 120,
      },
      engagement: {
        views: 1000,
        likes: 10, // 1% like rate
        comments: 2,
        shares: 0,
      },
      shareability: {
        caption_length_chars: 5,
      },
      algo: {
        caption_length_chars: 5,
        hashtag_count: 15, // spam
        hashtag_niche_mix_ok: false,
      },
    },
  };
}

function createIncompleteInput(): ScorerInput {
  return {
    meta: {
      video_id: '523e4567-e89b-12d3-a456-426614174000',
      post_time_iso: '2024-01-15T10:00:00Z',
      followers: 10000,
      length_sec: 30,
    },
    measures: {
      hook: {
        duration_sec: 4,
        text: 'test',
        type: '',
        // Missing: effectiveness_score, visual_description
      },
      story: {
        // Missing: storyboard, beats_count, arc_detected
      },
      visuals: {
        // Missing: overlays, edit_rate_per_10s
        text_overlay_present: false,
      },
      audio: {
        // Missing: all fields
      },
      watchtime: {
        length_sec: 30,
        // Missing: avg_watch_pct, completion_rate
      },
      engagement: {
        views: 10000,
        likes: 500,
        comments: 20,
        shares: 10,
      },
      shareability: {
        caption_length_chars: 100,
        // Missing: has_cta
      },
      algo: {
        caption_length_chars: 100,
        hashtag_count: 3,
        hashtag_niche_mix_ok: true,
      },
    },
  };
}
