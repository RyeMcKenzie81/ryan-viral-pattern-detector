"""
Pairs Analysis for Viral Tweet Patterns

Performs matched-pairs analysis to test hypotheses while controlling for confounding variables.
"""

import json
import numpy as np
from typing import List, Dict, Any, Tuple
from scipy.stats import mannwhitneyu, ttest_ind
from collections import defaultdict


class PairsAnalyzer:
    """Analyzes pairs of tweets to test specific hypotheses."""

    def __init__(self, outliers_path: str):
        """Initialize with path to outliers JSON."""
        with open(outliers_path, 'r') as f:
            data = json.load(f)
        self.outliers = data['outliers']

    def analyze_mention_effect(self) -> Dict[str, Any]:
        """
        Test if mentions hurt virality when controlling for follower count.

        Strategy: Match tweets with similar follower counts, compare those
        with many mentions vs few/no mentions.
        """
        # Categorize tweets
        tweets_with_data = []
        for tweet in self.outliers[:100]:
            text = tweet['text']
            mention_count = text.count('@')

            tweets_with_data.append({
                'followers': tweet['author_followers'],
                'mentions': mention_count,
                'has_mentions': mention_count > 0,
                'many_mentions': mention_count >= 2,
                'z_score': tweet['outlier_metrics']['z_score'],
                'views': tweet['metrics']['views'],
                'engagement_rate': tweet['metrics']['engagement_rate'],
                'text': text,
                'author': tweet['author']
            })

        # Group by follower tiers for matching
        follower_tiers = {
            'micro': (0, 1000),
            'small': (1000, 10000),
            'medium': (10000, 100000),
            'large': (100000, 1000000),
            'mega': (1000000, float('inf'))
        }

        matched_pairs = []
        for tier_name, (min_f, max_f) in follower_tiers.items():
            tier_tweets = [t for t in tweets_with_data if min_f <= t['followers'] < max_f]

            if len(tier_tweets) < 2:
                continue

            # Split into with/without mentions
            no_mentions = [t for t in tier_tweets if t['mentions'] == 0]
            few_mentions = [t for t in tier_tweets if t['mentions'] == 1]
            many_mentions = [t for t in tier_tweets if t['mentions'] >= 2]

            matched_pairs.append({
                'tier': tier_name,
                'follower_range': f"{min_f:,} - {max_f:,}",
                'no_mentions': {
                    'count': len(no_mentions),
                    'avg_z_score': np.mean([t['z_score'] for t in no_mentions]) if no_mentions else 0,
                    'avg_views': np.mean([t['views'] for t in no_mentions]) if no_mentions else 0,
                },
                'few_mentions': {
                    'count': len(few_mentions),
                    'avg_z_score': np.mean([t['z_score'] for t in few_mentions]) if few_mentions else 0,
                    'avg_views': np.mean([t['views'] for t in few_mentions]) if few_mentions else 0,
                },
                'many_mentions': {
                    'count': len(many_mentions),
                    'avg_z_score': np.mean([t['z_score'] for t in many_mentions]) if many_mentions else 0,
                    'avg_views': np.mean([t['views'] for t in many_mentions]) if many_mentions else 0,
                }
            })

        # Overall comparison: 0-1 mentions vs 2+ mentions
        low_mention = [t for t in tweets_with_data if t['mentions'] <= 1]
        high_mention = [t for t in tweets_with_data if t['mentions'] >= 2]

        overall_comparison = {
            'low_mention_group': {
                'count': len(low_mention),
                'avg_mentions': np.mean([t['mentions'] for t in low_mention]),
                'avg_z_score': np.mean([t['z_score'] for t in low_mention]),
                'median_z_score': np.median([t['z_score'] for t in low_mention]),
                'avg_views': np.mean([t['views'] for t in low_mention]),
            },
            'high_mention_group': {
                'count': len(high_mention),
                'avg_mentions': np.mean([t['mentions'] for t in high_mention]),
                'avg_z_score': np.mean([t['z_score'] for t in high_mention]),
                'median_z_score': np.median([t['z_score'] for t in high_mention]),
                'avg_views': np.mean([t['views'] for t in high_mention]),
            }
        }

        # Statistical test
        if len(low_mention) > 0 and len(high_mention) > 0:
            low_scores = [t['z_score'] for t in low_mention]
            high_scores = [t['z_score'] for t in high_mention]
            stat, p_value = mannwhitneyu(low_scores, high_scores, alternative='two-sided')

            overall_comparison['statistical_test'] = {
                'test': 'Mann-Whitney U',
                'statistic': float(stat),
                'p_value': float(p_value),
                'significant': p_value < 0.05,
                'effect_direction': 'Low mentions perform better' if np.mean(low_scores) > np.mean(high_scores) else 'High mentions perform better'
            }

        return {
            'hypothesis': 'Mentions hurt virality (controlling for followers)',
            'matched_pairs_by_tier': matched_pairs,
            'overall_comparison': overall_comparison
        }

    def analyze_url_effect(self) -> Dict[str, Any]:
        """Test if URLs help virality when controlling for other factors."""
        tweets_with_data = []
        for tweet in self.outliers[:100]:
            text = tweet['text']
            has_url = 'http' in text.lower() or 't.co' in text.lower()

            tweets_with_data.append({
                'followers': tweet['author_followers'],
                'has_url': has_url,
                'z_score': tweet['outlier_metrics']['z_score'],
                'views': tweet['metrics']['views'],
                'char_count': len(text),
            })

        # Split by URL presence
        with_url = [t for t in tweets_with_data if t['has_url']]
        without_url = [t for t in tweets_with_data if not t['has_url']]

        comparison = {
            'with_url': {
                'count': len(with_url),
                'avg_z_score': np.mean([t['z_score'] for t in with_url]),
                'avg_views': np.mean([t['views'] for t in with_url]),
                'avg_followers': np.mean([t['followers'] for t in with_url]),
            },
            'without_url': {
                'count': len(without_url),
                'avg_z_score': np.mean([t['z_score'] for t in without_url]),
                'avg_views': np.mean([t['views'] for t in without_url]),
                'avg_followers': np.mean([t['followers'] for t in without_url]),
            }
        }

        # Statistical test
        if len(with_url) > 0 and len(without_url) > 0:
            url_scores = [t['z_score'] for t in with_url]
            no_url_scores = [t['z_score'] for t in without_url]
            stat, p_value = mannwhitneyu(url_scores, no_url_scores, alternative='two-sided')

            comparison['statistical_test'] = {
                'test': 'Mann-Whitney U',
                'statistic': float(stat),
                'p_value': float(p_value),
                'significant': p_value < 0.05,
                'effect_direction': 'URLs perform better' if np.mean(url_scores) > np.mean(no_url_scores) else 'No URLs perform better'
            }

        return {
            'hypothesis': 'URLs/media increase virality',
            'comparison': comparison
        }

    def analyze_length_effect(self) -> Dict[str, Any]:
        """Test if longer content performs better."""
        tweets_with_data = []
        for tweet in self.outliers[:100]:
            text = tweet['text']
            word_count = len(text.split())

            tweets_with_data.append({
                'word_count': word_count,
                'char_count': len(text),
                'is_short': word_count < 30,
                'is_medium': 30 <= word_count < 60,
                'is_long': word_count >= 60,
                'z_score': tweet['outlier_metrics']['z_score'],
                'views': tweet['metrics']['views'],
            })

        # Categorize by length
        short = [t for t in tweets_with_data if t['is_short']]
        medium = [t for t in tweets_with_data if t['is_medium']]
        long = [t for t in tweets_with_data if t['is_long']]

        comparison = {
            'short_tweets': {
                'count': len(short),
                'word_range': '< 30 words',
                'avg_words': np.mean([t['word_count'] for t in short]) if short else 0,
                'avg_z_score': np.mean([t['z_score'] for t in short]) if short else 0,
            },
            'medium_tweets': {
                'count': len(medium),
                'word_range': '30-60 words',
                'avg_words': np.mean([t['word_count'] for t in medium]) if medium else 0,
                'avg_z_score': np.mean([t['z_score'] for t in medium]) if medium else 0,
            },
            'long_tweets': {
                'count': len(long),
                'word_range': '60+ words',
                'avg_words': np.mean([t['word_count'] for t in long]) if long else 0,
                'avg_z_score': np.mean([t['z_score'] for t in long]) if long else 0,
            }
        }

        return {
            'hypothesis': 'Longer content performs better',
            'comparison': comparison
        }

    def analyze_first_person_effect(self) -> Dict[str, Any]:
        """Test if first-person voice increases virality."""
        tweets_with_data = []
        for tweet in self.outliers[:100]:
            text = tweet['text'].lower()

            # Count first-person pronouns
            first_person = sum(text.count(word) for word in [' i ', ' me ', ' my ', ' mine ', ' we ', ' us ', ' our ', ' ours '])
            has_first_person = first_person > 0

            tweets_with_data.append({
                'has_first_person': has_first_person,
                'first_person_count': first_person,
                'z_score': tweet['outlier_metrics']['z_score'],
                'views': tweet['metrics']['views'],
                'followers': tweet['author_followers'],
            })

        # Split by first-person presence
        with_fp = [t for t in tweets_with_data if t['has_first_person']]
        without_fp = [t for t in tweets_with_data if not t['has_first_person']]

        comparison = {
            'with_first_person': {
                'count': len(with_fp),
                'avg_z_score': np.mean([t['z_score'] for t in with_fp]),
                'avg_views': np.mean([t['views'] for t in with_fp]),
                'avg_followers': np.mean([t['followers'] for t in with_fp]),
            },
            'without_first_person': {
                'count': len(without_fp),
                'avg_z_score': np.mean([t['z_score'] for t in without_fp]),
                'avg_views': np.mean([t['views'] for t in without_fp]),
                'avg_followers': np.mean([t['followers'] for t in without_fp]),
            }
        }

        # Statistical test
        if len(with_fp) > 0 and len(without_fp) > 0:
            fp_scores = [t['z_score'] for t in with_fp]
            no_fp_scores = [t['z_score'] for t in without_fp]
            stat, p_value = mannwhitneyu(fp_scores, no_fp_scores, alternative='two-sided')

            comparison['statistical_test'] = {
                'test': 'Mann-Whitney U',
                'statistic': float(stat),
                'p_value': float(p_value),
                'significant': p_value < 0.05,
                'effect_direction': 'First-person performs better' if np.mean(fp_scores) > np.mean(no_fp_scores) else 'Third-person performs better'
            }

        return {
            'hypothesis': 'First-person voice increases engagement',
            'comparison': comparison
        }


def main():
    """Run pairs analysis."""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python pairs_analyzer.py <outliers.json>")
        sys.exit(1)

    outliers_path = sys.argv[1]
    analyzer = PairsAnalyzer(outliers_path)

    print(f"\n{'='*80}")
    print(f"PAIRS ANALYSIS - Controlled Comparisons")
    print(f"{'='*80}\n")

    # Analyze mention effect
    print("="*80)
    print("HYPOTHESIS: Mentions Hurt Virality")
    print("="*80)
    mention_analysis = analyzer.analyze_mention_effect()

    print(f"\n📊 Overall Comparison:")
    low = mention_analysis['overall_comparison']['low_mention_group']
    high = mention_analysis['overall_comparison']['high_mention_group']

    print(f"\nLow Mentions (0-1):")
    print(f"  • Count: {low['count']}")
    print(f"  • Avg mentions: {low['avg_mentions']:.2f}")
    print(f"  • Avg Z-score: {low['avg_z_score']:.2f}")
    print(f"  • Median Z-score: {low['median_z_score']:.2f}")
    print(f"  • Avg views: {low['avg_views']:,.0f}")

    print(f"\nHigh Mentions (2+):")
    print(f"  • Count: {high['count']}")
    print(f"  • Avg mentions: {high['avg_mentions']:.2f}")
    print(f"  • Avg Z-score: {high['avg_z_score']:.2f}")
    print(f"  • Median Z-score: {high['median_z_score']:.2f}")
    print(f"  • Avg views: {high['avg_views']:,.0f}")

    if 'statistical_test' in mention_analysis['overall_comparison']:
        test = mention_analysis['overall_comparison']['statistical_test']
        sig = "✓ SIGNIFICANT" if test['significant'] else "✗ Not significant"
        print(f"\n📈 Statistical Test: {test['test']}")
        print(f"  P-value: {test['p_value']:.4f} - {sig}")
        print(f"  Effect: {test['effect_direction']}")

    print(f"\n🎯 Matched Pairs by Follower Tier:")
    for pair in mention_analysis['matched_pairs_by_tier']:
        print(f"\n  {pair['tier'].upper()} ({pair['follower_range']}):")
        print(f"    No mentions: {pair['no_mentions']['count']} tweets, avg z-score: {pair['no_mentions']['avg_z_score']:.2f}")
        print(f"    Few mentions (1): {pair['few_mentions']['count']} tweets, avg z-score: {pair['few_mentions']['avg_z_score']:.2f}")
        print(f"    Many mentions (2+): {pair['many_mentions']['count']} tweets, avg z-score: {pair['many_mentions']['avg_z_score']:.2f}")

    # Analyze URL effect
    print("\n" + "="*80)
    print("HYPOTHESIS: URLs Increase Virality")
    print("="*80)
    url_analysis = analyzer.analyze_url_effect()

    with_url = url_analysis['comparison']['with_url']
    without_url = url_analysis['comparison']['without_url']

    print(f"\nWith URL:")
    print(f"  • Count: {with_url['count']}")
    print(f"  • Avg Z-score: {with_url['avg_z_score']:.2f}")
    print(f"  • Avg views: {with_url['avg_views']:,.0f}")
    print(f"  • Avg followers: {with_url['avg_followers']:,.0f}")

    print(f"\nWithout URL:")
    print(f"  • Count: {without_url['count']}")
    print(f"  • Avg Z-score: {without_url['avg_z_score']:.2f}")
    print(f"  • Avg views: {without_url['avg_views']:,.0f}")
    print(f"  • Avg followers: {without_url['avg_followers']:,.0f}")

    if 'statistical_test' in url_analysis['comparison']:
        test = url_analysis['comparison']['statistical_test']
        sig = "✓ SIGNIFICANT" if test['significant'] else "✗ Not significant"
        print(f"\n📈 Statistical Test: {test['test']}")
        print(f"  P-value: {test['p_value']:.4f} - {sig}")
        print(f"  Effect: {test['effect_direction']}")

    # Analyze length effect
    print("\n" + "="*80)
    print("HYPOTHESIS: Longer Content Performs Better")
    print("="*80)
    length_analysis = analyzer.analyze_length_effect()

    for category, data in length_analysis['comparison'].items():
        print(f"\n{category.replace('_', ' ').title()}:")
        print(f"  • Count: {data['count']}")
        print(f"  • Range: {data['word_range']}")
        print(f"  • Avg words: {data['avg_words']:.1f}")
        print(f"  • Avg Z-score: {data['avg_z_score']:.2f}")

    # Analyze first-person effect
    print("\n" + "="*80)
    print("HYPOTHESIS: First-Person Voice Increases Engagement")
    print("="*80)
    fp_analysis = analyzer.analyze_first_person_effect()

    with_fp = fp_analysis['comparison']['with_first_person']
    without_fp = fp_analysis['comparison']['without_first_person']

    print(f"\nWith First-Person:")
    print(f"  • Count: {with_fp['count']}")
    print(f"  • Avg Z-score: {with_fp['avg_z_score']:.2f}")
    print(f"  • Avg views: {with_fp['avg_views']:,.0f}")
    print(f"  • Avg followers: {with_fp['avg_followers']:,.0f}")

    print(f"\nWithout First-Person:")
    print(f"  • Count: {without_fp['count']}")
    print(f"  • Avg Z-score: {without_fp['avg_z_score']:.2f}")
    print(f"  • Avg views: {without_fp['avg_views']:,.0f}")
    print(f"  • Avg followers: {without_fp['avg_followers']:,.0f}")

    if 'statistical_test' in fp_analysis['comparison']:
        test = fp_analysis['comparison']['statistical_test']
        sig = "✓ SIGNIFICANT" if test['significant'] else "✗ Not significant"
        print(f"\n📈 Statistical Test: {test['test']}")
        print(f"  P-value: {test['p_value']:.4f} - {sig}")
        print(f"  Effect: {test['effect_direction']}")

    # Save results
    output_path = outliers_path.replace('.json', '_pairs_analysis.json')
    with open(output_path, 'w') as f:
        json.dump({
            'mention_analysis': mention_analysis,
            'url_analysis': url_analysis,
            'length_analysis': length_analysis,
            'first_person_analysis': fp_analysis,
        }, f, indent=2)

    print(f"\n✓ Detailed analysis saved to: {output_path}\n")


if __name__ == "__main__":
    main()
