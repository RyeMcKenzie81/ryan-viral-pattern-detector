/**
 * Deterministic scoring formulas for each subscore
 * All functions return scores in range [0, 100]
 */

import type { Measures } from './schema.js';
import type { PenaltyFactors } from './types.js';

// ============================================================================
// Utility Functions
// ============================================================================

function clamp(val: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, val));
}

// Unused currently - reserved for future normalization logic
// function normalize(val: number, min: number, max: number): number {
//   if (max === min) return 0;
//   return clamp((val - min) / (max - min) * 100, 0, 100);
// }

// ============================================================================
// 1. Hook Score (0-100)
// ============================================================================

export function scoreHook(m: Measures['hook']): number {
  let score = 50; // baseline

  // Duration: 3-5 sec ideal
  if (m.duration_sec >= 3 && m.duration_sec <= 5) {
    score += 20;
  } else if (m.duration_sec < 2) {
    score -= 15; // too short, audience confused
  } else if (m.duration_sec > 7) {
    score -= 10; // too long, lost attention
  } else {
    score += 10; // acceptable range (2-3 or 5-7)
  }

  // Type quality (from Gemini analysis)
  const types = m.type?.toLowerCase().split('|') || [];
  if (types.includes('shock')) score += 12;
  if (types.includes('curiosity')) score += 12;
  if (types.includes('authority')) score += 8;
  if (types.includes('question')) score += 10;
  if (types.includes('promise')) score += 8;

  // Effectiveness score from Gemini (if available)
  // Scale 0-10 → contribute -10 to +10 to score
  if (m.effectiveness_score !== undefined) {
    score += (m.effectiveness_score - 5) * 2;
  }

  // Has text (non-empty hook)
  if (m.text && m.text.length > 5) {
    score += 5;
  }

  return clamp(score, 0, 100);
}

// ============================================================================
// 2. Story Score (0-100)
// ============================================================================

export function scoreStory(m: Measures['story']): number {
  let score = 50;

  // Has storyboard beats
  if (m.beats_count !== undefined) {
    if (m.beats_count >= 5) {
      score += 20; // rich narrative
    } else if (m.beats_count >= 3) {
      score += 15; // adequate structure
    } else if (m.beats_count >= 1) {
      score += 8; // minimal structure
    }
  }

  // Story arc detected (setup, build, payoff)
  if (m.arc_detected) {
    score += 15;
  }

  // Consistent pacing (using storyboard durations)
  if (m.storyboard && m.storyboard.length >= 3) {
    const durations = m.storyboard.map(b => b.duration);
    const avgDuration = durations.reduce((a, b) => a + b, 0) / durations.length;
    const variance = durations.reduce((a, b) => a + Math.pow(b - avgDuration, 2), 0) / durations.length;
    const stdDev = Math.sqrt(variance);

    // Reward consistent pacing (low variance)
    if (stdDev < 2) {
      score += 10; // very consistent
    } else if (stdDev < 4) {
      score += 5; // moderately consistent
    }
  }

  return clamp(score, 0, 100);
}

// ============================================================================
// 3. Relatability Score (0-100)
// ============================================================================

export function scoreRelatability(m: Measures, meta: { followers: number }): number {
  let score = 50;

  // Hook relatability signals
  const hookText = m.hook.text?.toLowerCase() || '';

  // Direct address ("you", "your")
  const directAddress = (hookText.match(/\b(you|your)\b/g) || []).length;
  score += Math.min(directAddress * 5, 15);

  // Emotional triggers
  const emotionalWords = ['love', 'hate', 'fear', 'excited', 'worried', 'shocked', 'surprised'];
  const emotionCount = emotionalWords.filter(word => hookText.includes(word)).length;
  score += Math.min(emotionCount * 4, 12);

  // Story relatability (if storyboard descriptions mention common experiences)
  if (m.story.storyboard) {
    const allDescriptions = m.story.storyboard.map(s => s.description.toLowerCase()).join(' ');

    // Common life scenarios
    const relatableScenarios = ['everyday', 'daily', 'common', 'typical', 'normal', 'usual', 'regular'];
    const scenarioCount = relatableScenarios.filter(word => allDescriptions.includes(word)).length;
    score += Math.min(scenarioCount * 3, 10);
  }

  // Account size (smaller accounts often more relatable)
  if (meta.followers < 10000) {
    score += 8; // micro-influencer relatability
  } else if (meta.followers < 100000) {
    score += 5; // mid-tier relatability
  }

  return clamp(score, 0, 100);
}

// ============================================================================
// 4. Visuals Score (0-100)
// ============================================================================

export function scoreVisuals(m: Measures['visuals']): number {
  let score = 50;

  // Text overlays present (modern editing)
  if (m.text_overlay_present) {
    score += 15;
  }

  // Number of overlays (indicates editing effort)
  if (m.overlays) {
    const overlayCount = m.overlays.length;
    if (overlayCount >= 5) {
      score += 15; // highly edited
    } else if (overlayCount >= 2) {
      score += 10; // moderately edited
    } else if (overlayCount === 1) {
      score += 5; // minimal editing
    }
  }

  // Edit rate (cuts per 10 seconds)
  if (m.edit_rate_per_10s !== undefined) {
    if (m.edit_rate_per_10s >= 3) {
      score += 15; // fast-paced editing
    } else if (m.edit_rate_per_10s >= 1.5) {
      score += 10; // moderate pacing
    } else if (m.edit_rate_per_10s > 0) {
      score += 5; // some editing
    }
  }

  return clamp(score, 0, 100);
}

// ============================================================================
// 5. Audio Score (0-100)
// ============================================================================

export function scoreAudio(m: Measures['audio']): number {
  let score = 50;

  // Trending sound used (major boost)
  if (m.trending_sound_used) {
    score += 25;
  }

  // Original sound created (authenticity bonus)
  if (m.original_sound_created) {
    score += 20;
  }

  // Beat sync score (if available from future analysis)
  if (m.beat_sync_score !== undefined) {
    // Scale 0-10 → 0-15 points
    score += (m.beat_sync_score / 10) * 15;
  }

  // If neither trending nor original, apply neutral baseline
  if (!m.trending_sound_used && !m.original_sound_created) {
    // Assume generic audio, slight penalty
    score -= 10;
  }

  return clamp(score, 0, 100);
}

// ============================================================================
// 6. Watchtime Score (0-100)
// ============================================================================

export function scoreWatchtime(m: Measures['watchtime']): number {
  let score = 50;

  // Ideal length: 15-45 seconds (TikTok sweet spot)
  const length = m.length_sec;

  if (length >= 15 && length <= 45) {
    score += 25; // ideal range
  } else if (length >= 10 && length < 15) {
    score += 15; // acceptable but short
  } else if (length > 45 && length <= 60) {
    score += 10; // acceptable but long
  } else if (length < 10) {
    score -= 10; // too short, hard to tell story
  } else if (length > 90) {
    score -= 15; // too long, high drop-off risk
  }

  // Average watch percentage (future metric)
  if (m.avg_watch_pct !== undefined) {
    // 80%+ watch = excellent retention
    if (m.avg_watch_pct >= 80) {
      score += 20;
    } else if (m.avg_watch_pct >= 60) {
      score += 15;
    } else if (m.avg_watch_pct >= 40) {
      score += 10;
    } else {
      score -= 5; // poor retention
    }
  }

  // Completion rate (future metric)
  if (m.completion_rate !== undefined) {
    // High completion = strong content
    if (m.completion_rate >= 70) {
      score += 15;
    } else if (m.completion_rate >= 50) {
      score += 10;
    } else if (m.completion_rate >= 30) {
      score += 5;
    }
  }

  return clamp(score, 0, 100);
}

// ============================================================================
// 7. Engagement Score (0-100)
// ============================================================================

export function scoreEngagement(m: Measures['engagement']): number {
  let score = 50;

  const { views, likes, comments, shares, saves } = m;

  // Engagement rate calculations
  const likeRate = views > 0 ? (likes / views) * 100 : 0;
  const commentRate = views > 0 ? (comments / views) * 100 : 0;
  const shareRate = views > 0 ? (shares / views) * 100 : 0;
  const saveRate = saves && views > 0 ? (saves / views) * 100 : 0;

  // Like rate (benchmark: 5% is good, 10%+ is excellent)
  if (likeRate >= 10) {
    score += 20;
  } else if (likeRate >= 5) {
    score += 15;
  } else if (likeRate >= 3) {
    score += 10;
  } else if (likeRate >= 1) {
    score += 5;
  }

  // Comment rate (benchmark: 0.5% is good, 1%+ is excellent)
  if (commentRate >= 1) {
    score += 15;
  } else if (commentRate >= 0.5) {
    score += 10;
  } else if (commentRate >= 0.2) {
    score += 5;
  }

  // Share rate (benchmark: 0.5% is good, 1%+ is viral signal)
  if (shareRate >= 1) {
    score += 15;
  } else if (shareRate >= 0.5) {
    score += 10;
  } else if (shareRate >= 0.2) {
    score += 5;
  }

  // Save rate (if available)
  if (saveRate > 0) {
    if (saveRate >= 1) {
      score += 10;
    } else if (saveRate >= 0.5) {
      score += 5;
    }
  }

  return clamp(score, 0, 100);
}

// ============================================================================
// 8. Shareability Score (0-100)
// ============================================================================

export function scoreShareability(m: Measures['shareability']): number {
  let score = 50;

  // Caption length (100-150 chars is ideal for intrigue)
  const captionLen = m.caption_length_chars;

  if (captionLen >= 100 && captionLen <= 150) {
    score += 15; // ideal length
  } else if (captionLen >= 50 && captionLen < 100) {
    score += 10; // good length
  } else if (captionLen >= 20 && captionLen < 50) {
    score += 5; // acceptable
  } else if (captionLen > 200) {
    score -= 5; // too long, loses impact
  }

  // Has CTA (call to action)
  if (m.has_cta) {
    score += 15;
  }

  // Save-worthy signals (future metric from Gemini analysis)
  if (m.save_worthy_signals !== undefined) {
    // Scale 0-10 → 0-20 points
    score += (m.save_worthy_signals / 10) * 20;
  }

  return clamp(score, 0, 100);
}

// ============================================================================
// 9. Algo Score (0-100)
// ============================================================================

export function scoreAlgo(m: Measures['algo']): number {
  let score = 50;

  // Hashtag count (3-5 is optimal per TikTok best practices)
  const hashtagCount = m.hashtag_count;

  if (hashtagCount >= 3 && hashtagCount <= 5) {
    score += 20; // optimal
  } else if (hashtagCount >= 1 && hashtagCount < 3) {
    score += 10; // acceptable
  } else if (hashtagCount > 5 && hashtagCount <= 8) {
    score += 5; // slightly excessive
  } else if (hashtagCount > 8) {
    score -= 10; // spam-like
  }

  // Hashtag niche/broad mix
  if (m.hashtag_niche_mix_ok) {
    score += 15;
  }

  // Caption length (algo prefers some context)
  if (m.caption_length_chars >= 50) {
    score += 10;
  } else if (m.caption_length_chars >= 20) {
    score += 5;
  }

  // Post time optimal (future metric)
  if (m.post_time_optimal) {
    score += 10;
  }

  return clamp(score, 0, 100);
}

// ============================================================================
// 10. Penalties (subtracted from overall)
// ============================================================================

export function scorePenalties(m: Measures, meta: { length_sec: number }): PenaltyFactors {
  const penalties: PenaltyFactors = {
    spam_indicators: 0,
    low_quality_signals: 0,
    excessive_length: 0,
    poor_formatting: 0,
  };

  // Spam indicators (excessive hashtags)
  if (m.algo.hashtag_count > 10) {
    penalties.spam_indicators += 5;
  }
  if (m.algo.hashtag_count > 15) {
    penalties.spam_indicators += 5; // total 10
  }

  // Low quality signals (very short or very long caption)
  if (m.shareability.caption_length_chars < 10) {
    penalties.low_quality_signals += 5;
  }
  if (m.shareability.caption_length_chars > 300) {
    penalties.low_quality_signals += 5;
  }

  // Excessive length (over 2 minutes is rare for viral TikTok)
  if (meta.length_sec > 120) {
    penalties.excessive_length += 10;
  } else if (meta.length_sec > 90) {
    penalties.excessive_length += 5;
  }

  // Poor formatting (no text overlays in modern viral videos is unusual)
  if (!m.visuals.text_overlay_present && meta.length_sec > 10) {
    penalties.poor_formatting += 3;
  }

  return penalties;
}

export function calculateTotalPenalty(factors: PenaltyFactors): number {
  return Object.values(factors).reduce((sum, val) => sum + val, 0);
}
