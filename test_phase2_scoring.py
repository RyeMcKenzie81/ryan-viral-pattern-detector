#!/usr/bin/env python3
"""
Phase 2 Scoring System Tests
Tests all scoring components with sample data
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from viraltracker.generation.comment_finder import (
    TweetMetrics,
    compute_velocity,
    relevance_from_taxonomy,
    openness_score,
    author_quality_score,
    total_score,
    label_from_score,
    gate_tweet,
    score_tweet
)
from viraltracker.core.config import FinderConfig, TaxonomyNode, VoiceConfig, SourcesConfig


def test_velocity_scoring():
    """Test velocity calculation"""
    print("\n=== Test 1: Velocity Scoring ===")

    try:
        # High velocity tweet (viral)
        vel1 = compute_velocity(
            likes=1000,
            replies=200,
            retweets=150,
            minutes_since=60,  # 1 hour old
            followers=10000
        )
        print(f"✓ High velocity (1000 likes in 1 hour, 10K followers): {vel1:.3f}")

        # Low velocity tweet
        vel2 = compute_velocity(
            likes=10,
            replies=2,
            retweets=1,
            minutes_since=120,  # 2 hours old
            followers=500
        )
        print(f"✓ Low velocity (10 likes in 2 hours, 500 followers): {vel2:.3f}")

        # Edge case: very new tweet
        vel3 = compute_velocity(
            likes=50,
            replies=10,
            retweets=5,
            minutes_since=5,  # 5 minutes old
            followers=1000
        )
        print(f"✓ Very fresh tweet (50 likes in 5 min, 1K followers): {vel3:.3f}")

        if vel1 > vel2 and vel3 > vel2:
            print(f"✓ Velocity ordering correct (high > fresh > low)")
            return True
        else:
            print(f"✗ Velocity ordering incorrect")
            return False

    except Exception as e:
        print(f"✗ Velocity test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_taxonomy_relevance():
    """Test taxonomy matching with mock embeddings"""
    print("\n\n=== Test 2: Taxonomy Relevance ===")

    try:
        # Mock embeddings (normalized vectors)
        tweet_embedding = [0.8, 0.2, 0.1] + [0.0] * 765  # 768 dims

        taxonomy_embeddings = {
            "facebook ads": [0.9, 0.1, 0.05] + [0.0] * 765,  # Very similar
            "email marketing": [0.1, 0.9, 0.05] + [0.0] * 765,  # Different
            "seo": [0.5, 0.5, 0.0] + [0.0] * 765  # Somewhat similar
        }

        relevance, best_topic, best_sim = relevance_from_taxonomy(
            tweet_embedding,
            taxonomy_embeddings
        )

        print(f"✓ Tweet classified as: {best_topic}")
        print(f"  Similarity: {best_sim:.3f}")
        print(f"  Relevance score: {relevance:.3f}")

        if best_topic == "facebook ads":
            print(f"✓ Correct topic identified")
            return True
        else:
            print(f"✗ Wrong topic identified")
            return False

    except Exception as e:
        print(f"✗ Taxonomy test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_openness_scoring():
    """Test openness regex patterns"""
    print("\n\n=== Test 3: Openness Scoring ===")

    try:
        # Question tweet
        text1 = "What do you think about this Facebook ads strategy?"
        score1 = openness_score(text1)
        print(f"✓ Question tweet: '{text1[:50]}...'")
        print(f"  Openness: {score1:.3f}")

        # Hedge words tweet
        text2 = "I think this might be a good approach for conversion optimization"
        score2 = openness_score(text2)
        print(f"✓ Hedge tweet: '{text2[:50]}...'")
        print(f"  Openness: {score2:.3f}")

        # Statement tweet
        text3 = "Facebook ads performed great this month"
        score3 = openness_score(text3)
        print(f"✓ Statement tweet: '{text3[:50]}...'")
        print(f"  Openness: {score3:.3f}")

        if score1 > score3 and score2 > score3:
            print(f"✓ Openness ordering correct (question/hedge > statement)")
            return True
        else:
            print(f"✗ Openness ordering incorrect")
            return False

    except Exception as e:
        print(f"✗ Openness test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_author_quality():
    """Test whitelist/blacklist logic"""
    print("\n\n=== Test 4: Author Quality ===")

    try:
        whitelist = ["mosseri", "shopify"]
        blacklist = ["spammer123"]

        # Whitelisted
        score1 = author_quality_score("mosseri", whitelist, blacklist)
        print(f"✓ Whitelisted author (@mosseri): {score1:.1f}")

        # Unknown
        score2 = author_quality_score("randomuser", whitelist, blacklist)
        print(f"✓ Unknown author (@randomuser): {score2:.1f}")

        # Blacklisted
        score3 = author_quality_score("spammer123", whitelist, blacklist)
        print(f"✓ Blacklisted author (@spammer123): {score3:.1f}")

        if score1 == 0.9 and score2 == 0.6 and score3 == 0.0:
            print(f"✓ Author quality scores correct")
            return True
        else:
            print(f"✗ Author quality scores incorrect")
            return False

    except Exception as e:
        print(f"✗ Author quality test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_total_score_and_labeling():
    """Test total score calculation and label assignment"""
    print("\n\n=== Test 5: Total Score & Labeling ===")

    try:
        weights = {
            'velocity': 0.35,
            'relevance': 0.35,
            'openness': 0.20,
            'author_quality': 0.10
        }

        thresholds = {
            'green_min': 0.72,
            'yellow_min': 0.55
        }

        # High scoring tweet (green)
        total1 = total_score(0.9, 0.9, 0.8, 0.9, weights)
        label1 = label_from_score(total1, thresholds)
        print(f"✓ High quality tweet: total={total1:.3f}, label={label1}")

        # Medium tweet (yellow)
        total2 = total_score(0.6, 0.6, 0.5, 0.6, weights)
        label2 = label_from_score(total2, thresholds)
        print(f"✓ Medium tweet: total={total2:.3f}, label={label2}")

        # Low tweet (red)
        total3 = total_score(0.3, 0.4, 0.2, 0.6, weights)
        label3 = label_from_score(total3, thresholds)
        print(f"✓ Low quality tweet: total={total3:.3f}, label={label3}")

        if label1 == 'green' and label2 == 'yellow' and label3 == 'red':
            print(f"✓ Labels assigned correctly")
            return True
        else:
            print(f"✗ Labels incorrect: got {label1}, {label2}, {label3}")
            return False

    except Exception as e:
        print(f"✗ Total score test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_gate_filtering():
    """Test gate filtering logic"""
    print("\n\n=== Test 6: Gate Filtering ===")

    try:
        blacklist_keywords = ["giveaway", "airdrop"]
        blacklist_handles = ["spammer"]

        # Clean tweet
        passed1, reason1 = gate_tweet(
            "Great insights on Facebook ads",
            "gooduser",
            "en",
            blacklist_keywords,
            blacklist_handles
        )
        print(f"✓ Clean tweet: passed={passed1}")

        # Blacklist keyword
        passed2, reason2 = gate_tweet(
            "Join our giveaway!",
            "promoter",
            "en",
            blacklist_keywords,
            blacklist_handles
        )
        print(f"✓ Blacklist keyword tweet: passed={passed2}, reason='{reason2}'")

        # Non-English
        passed3, reason3 = gate_tweet(
            "Great content",
            "user",
            "es",
            blacklist_keywords,
            blacklist_handles
        )
        print(f"✓ Non-English tweet: passed={passed3}, reason='{reason3}'")

        if passed1 and not passed2 and not passed3:
            print(f"✓ Gate filtering working correctly")
            return True
        else:
            print(f"✗ Gate filtering incorrect")
            return False

    except Exception as e:
        print(f"✗ Gate test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_full_scoring_pipeline():
    """Test complete scoring with TweetMetrics"""
    print("\n\n=== Test 7: Full Scoring Pipeline ===")

    try:
        # Create mock tweet
        tweet = TweetMetrics(
            tweet_id="1234567890",
            text="What do you think about this new Facebook ads strategy? I'm curious",
            author_handle="marketer_pro",
            author_followers=5000,
            tweeted_at=datetime.now(timezone.utc) - timedelta(minutes=30),
            likes=150,
            replies=20,
            retweets=10,
            lang="en"
        )

        # Mock embedding
        tweet_embedding = [0.8, 0.2, 0.1] + [0.0] * 765

        # Mock taxonomy
        taxonomy_embeddings = {
            "facebook ads": [0.9, 0.1, 0.05] + [0.0] * 765
        }

        # Mock config
        config = FinderConfig(
            taxonomy=[TaxonomyNode("facebook ads", "Paid acquisition on Meta", [])],
            voice=VoiceConfig("direct, practical", [], {}),
            sources=SourcesConfig(["shopify"], ["giveaway"]),
            weights={'velocity': 0.35, 'relevance': 0.35, 'openness': 0.20, 'author_quality': 0.10},
            thresholds={'green_min': 0.72, 'yellow_min': 0.55},
            generation={'temperature': 0.2, 'max_tokens': 80, 'model': 'gemini-2.5-flash'}
        )

        # Score tweet
        result = score_tweet(tweet, tweet_embedding, taxonomy_embeddings, config, use_gate=True)

        print(f"✓ Scored tweet {result.tweet_id}")
        print(f"  Velocity: {result.velocity:.3f}")
        print(f"  Relevance: {result.relevance:.3f}")
        print(f"  Openness: {result.openness:.3f}")
        print(f"  Author Quality: {result.author_quality:.3f}")
        print(f"  Total: {result.total_score:.3f}")
        print(f"  Label: {result.label}")
        print(f"  Topic: {result.best_topic}")
        print(f"  Passed Gate: {result.passed_gate}")

        if result.total_score > 0 and result.label in ['green', 'yellow', 'red']:
            print(f"✓ Full scoring pipeline working")
            return True
        else:
            print(f"✗ Scoring pipeline produced invalid results")
            return False

    except Exception as e:
        print(f"✗ Full pipeline test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all Phase 2 tests"""
    print("=" * 60)
    print("PHASE 2 SCORING SYSTEM TESTING")
    print("=" * 60)

    results = {}

    # Run tests
    results['velocity'] = test_velocity_scoring()
    results['taxonomy'] = test_taxonomy_relevance()
    results['openness'] = test_openness_scoring()
    results['author_quality'] = test_author_quality()
    results['total_score'] = test_total_score_and_labeling()
    results['gate'] = test_gate_filtering()
    results['full_pipeline'] = test_full_scoring_pipeline()

    # Summary
    print("\n\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    for test_name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{test_name.upper():20} {status}")

    all_passed = all(results.values())

    print("\n" + "=" * 60)
    if all_passed:
        print("✓ ALL TESTS PASSED - Phase 2 Scoring Complete!")
    else:
        print("✗ SOME TESTS FAILED - Review errors above")
    print("=" * 60)

    return 0 if all_passed else 1


if __name__ == '__main__':
    sys.exit(main())
