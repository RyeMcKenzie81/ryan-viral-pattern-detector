"""
Length-Segmented Viral Pattern Analyzer

Analyzes what makes tweets viral WITHIN each length category,
since optimal strategies likely differ between short and long content.
"""

import json
import re
from typing import List, Dict, Any
import numpy as np
from scipy.stats import spearmanr
from collections import Counter


class LengthSegmentedAnalyzer:
    """Analyzes viral patterns segmented by content length."""

    def __init__(self, outliers_path: str):
        """Initialize with path to outliers JSON."""
        with open(outliers_path, 'r') as f:
            data = json.load(f)
        self.outliers = data['outliers']

    def segment_by_length(self, top_n: int = 100) -> Dict[str, List[Dict]]:
        """Segment tweets by length."""
        top_outliers = self.outliers[:top_n]

        segments = {
            'short': [],   # <30 words
            'medium': [],  # 30-60 words
            'long': []     # 60+ words
        }

        for outlier in top_outliers:
            text = outlier['text']
            word_count = len(text.split())

            tweet_data = {
                'text': text,
                'word_count': word_count,
                'char_count': len(text),
                'z_score': outlier['outlier_metrics']['z_score'],
                'views': outlier['metrics']['views'],
                'engagement_rate': outlier['metrics']['engagement_rate'],
                'followers': outlier['author_followers'],
                'author': outlier['author'],
                'url': outlier['url'],

                # Content features
                'mention_count': text.count('@'),
                'has_url': 'http' in text.lower() or 't.co' in text.lower(),
                'has_number': bool(re.search(r'\d', text)),
                'has_question': '?' in text,
                'has_exclamation': '!' in text,
                'emoji_count': len(re.findall(r'[^\w\s,.:;!?-]', text)),

                # Voice/tone
                'first_person': sum(text.lower().count(w) for w in [' i ', ' me ', ' my ', ' we ', ' us ', ' our ']),
                'has_first_person': sum(text.lower().count(w) for w in [' i ', ' me ', ' my ', ' we ', ' us ', ' our ']) > 0,

                # Urgency
                'has_urgency': any(word in text.lower() for word in ['today', 'now', 'just', 'breaking']),

                # Data/authority
                'has_data': any(word in text.lower() for word in ['study', 'research', 'data', 'survey']) or bool(re.search(r'\d+%', text)),
            }

            if word_count < 30:
                segments['short'].append(tweet_data)
            elif word_count <= 60:
                segments['medium'].append(tweet_data)
            else:
                segments['long'].append(tweet_data)

        return segments

    def analyze_segment(self, segment: List[Dict], segment_name: str) -> Dict[str, Any]:
        """Analyze viral factors within a specific length segment."""
        if len(segment) < 5:
            return {
                'segment_name': segment_name,
                'count': len(segment),
                'insufficient_data': True
            }

        # Calculate summary statistics
        summary = {
            'segment_name': segment_name,
            'count': len(segment),
            'avg_words': np.mean([t['word_count'] for t in segment]),
            'word_range': f"{min(t['word_count'] for t in segment)}-{max(t['word_count'] for t in segment)}",
            'avg_z_score': np.mean([t['z_score'] for t in segment]),
            'median_z_score': np.median([t['z_score'] for t in segment]),
            'avg_views': np.mean([t['views'] for t in segment]),
        }

        # Feature prevalence
        prevalence = {
            'urls': 100 * sum(t['has_url'] for t in segment) / len(segment),
            'mentions': 100 * sum(t['mention_count'] > 0 for t in segment) / len(segment),
            'numbers': 100 * sum(t['has_number'] for t in segment) / len(segment),
            'questions': 100 * sum(t['has_question'] for t in segment) / len(segment),
            'first_person': 100 * sum(t['has_first_person'] for t in segment) / len(segment),
            'urgency': 100 * sum(t['has_urgency'] for t in segment) / len(segment),
            'data_citations': 100 * sum(t['has_data'] for t in segment) / len(segment),
            'emojis': 100 * sum(t['emoji_count'] > 0 for t in segment) / len(segment),
        }
        summary['prevalence'] = prevalence

        # Correlations with virality within this segment
        correlations = {}
        y = np.array([t['z_score'] for t in segment])

        # Boolean features
        bool_features = {
            'has_url': 'URLs/media',
            'has_first_person': 'First-person voice',
            'has_urgency': 'Urgency markers',
            'has_data': 'Data/stats',
            'has_question': 'Questions',
            'has_number': 'Numbers',
        }

        for feature, label in bool_features.items():
            x = np.array([1 if t[feature] else 0 for t in segment])
            if x.sum() > 0 and x.sum() < len(x):  # Has variance
                corr, p_value = spearmanr(x, y)
                correlations[label] = {
                    'correlation': float(corr),
                    'p_value': float(p_value),
                    'significant': p_value < 0.05
                }

        # Numeric features
        numeric_features = {
            'mention_count': 'Mention count',
            'emoji_count': 'Emoji count',
            'first_person': 'First-person count',
            'followers': 'Follower count',
        }

        for feature, label in numeric_features.items():
            x = np.array([t[feature] for t in segment])
            if np.std(x) > 0:  # Has variance
                corr, p_value = spearmanr(x, y)
                correlations[label] = {
                    'correlation': float(corr),
                    'p_value': float(p_value),
                    'significant': p_value < 0.05
                }

        summary['correlations'] = correlations

        # Top performers in this segment
        top_performers = sorted(segment, key=lambda t: t['z_score'], reverse=True)[:3]
        summary['top_examples'] = [
            {
                'rank_in_segment': i+1,
                'z_score': t['z_score'],
                'words': t['word_count'],
                'author': t['author'],
                'text_preview': t['text'][:100] + '...' if len(t['text']) > 100 else t['text'],
                'has_url': t['has_url'],
                'mentions': t['mention_count'],
                'first_person': t['has_first_person'],
            }
            for i, t in enumerate(top_performers)
        ]

        return summary

    def compare_segments(self, segments_data: Dict[str, List[Dict]]) -> Dict[str, Any]:
        """Compare what works across different length segments."""
        analyses = {}
        for segment_name, segment_tweets in segments_data.items():
            analyses[segment_name] = self.analyze_segment(segment_tweets, segment_name)

        # Cross-segment comparison
        comparison = {
            'segment_sizes': {
                name: analysis['count']
                for name, analysis in analyses.items()
            },
            'avg_virality_by_length': {
                name: analysis.get('avg_z_score', 0)
                for name, analysis in analyses.items()
            },
            'significant_factors_by_length': {}
        }

        for segment_name, analysis in analyses.items():
            if 'correlations' in analysis:
                sig_factors = [
                    (factor, data['correlation'])
                    for factor, data in analysis['correlations'].items()
                    if data['significant']
                ]
                sig_factors.sort(key=lambda x: abs(x[1]), reverse=True)
                comparison['significant_factors_by_length'][segment_name] = sig_factors

        return comparison


def main():
    """Run length-segmented analysis."""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python length_segmented_analyzer.py <outliers.json> [top_n]")
        sys.exit(1)

    outliers_path = sys.argv[1]
    top_n = int(sys.argv[2]) if len(sys.argv) > 2 else 100

    analyzer = LengthSegmentedAnalyzer(outliers_path)

    print(f"\n{'='*80}")
    print(f"LENGTH-SEGMENTED VIRAL ANALYSIS - Top {top_n} Tweets")
    print(f"{'='*80}\n")

    print("Segmenting tweets by length...")
    segments = analyzer.segment_by_length(top_n)
    print(f"✓ Short (<30 words): {len(segments['short'])} tweets")
    print(f"✓ Medium (30-60 words): {len(segments['medium'])} tweets")
    print(f"✓ Long (60+ words): {len(segments['long'])} tweets\n")

    # Analyze each segment
    analyses = {}
    for segment_name in ['short', 'medium', 'long']:
        print("="*80)
        print(f"{segment_name.upper()} TWEETS ANALYSIS")
        print("="*80)

        analysis = analyzer.analyze_segment(segments[segment_name], segment_name)
        analyses[segment_name] = analysis

        if analysis.get('insufficient_data'):
            print(f"\n⚠️  Insufficient data ({analysis['count']} tweets)\n")
            continue

        print(f"\n📊 Summary:")
        print(f"  • Count: {analysis['count']} tweets")
        print(f"  • Word range: {analysis['word_range']}")
        print(f"  • Avg Z-score: {analysis['avg_z_score']:.2f}")
        print(f"  • Median Z-score: {analysis['median_z_score']:.2f}")
        print(f"  • Avg views: {analysis['avg_views']:,.0f}")

        print(f"\n📈 Feature Prevalence:")
        for feature, pct in sorted(analysis['prevalence'].items(), key=lambda x: x[1], reverse=True):
            print(f"  • {feature.replace('_', ' ').title()}: {pct:.1f}%")

        if analysis.get('correlations'):
            sig_corrs = [(f, d) for f, d in analysis['correlations'].items() if d['significant']]
            if sig_corrs:
                print(f"\n✅ SIGNIFICANT CORRELATIONS (p < 0.05):")
                for feature, data in sorted(sig_corrs, key=lambda x: abs(x[1]['correlation']), reverse=True):
                    print(f"  • {feature}: r={data['correlation']:.3f}, p={data['p_value']:.4f}")
            else:
                print(f"\n⚠️  No statistically significant correlations found")

        print(f"\n🏆 Top {len(analysis['top_examples'])} Performers:")
        for ex in analysis['top_examples']:
            print(f"\n  #{ex['rank_in_segment']} (Z-score: {ex['z_score']:.2f}, {ex['words']} words)")
            print(f"     @{ex['author']}")
            features = []
            if ex['has_url']: features.append('URL')
            if ex['mentions'] > 0: features.append(f"{ex['mentions']} mentions")
            if ex['first_person']: features.append('1st-person')
            print(f"     Features: {', '.join(features) if features else 'None notable'}")
            print(f"     \"{ex['text_preview']}\"")

        print()

    # Cross-segment comparison
    print("="*80)
    print("CROSS-SEGMENT COMPARISON")
    print("="*80)

    comparison = analyzer.compare_segments(segments)

    print(f"\n📊 Segment Distribution:")
    for segment, count in comparison['segment_sizes'].items():
        pct = 100 * count / top_n
        print(f"  • {segment.title()}: {count} tweets ({pct:.1f}%)")

    print(f"\n🎯 Average Virality by Length:")
    for segment, score in comparison['avg_virality_by_length'].items():
        print(f"  • {segment.title()}: {score:.2f} avg z-score")

    print(f"\n🔑 What Works for Each Length:")
    for segment, factors in comparison['significant_factors_by_length'].items():
        print(f"\n  {segment.upper()} TWEETS:")
        if factors:
            for i, (factor, corr) in enumerate(factors[:5], 1):
                direction = "✓" if corr > 0 else "✗"
                print(f"    {i}. {factor}: {direction} (r={corr:.3f})")
        else:
            print(f"    • No significant factors identified")

    # Save results
    output_path = outliers_path.replace('.json', '_length_segmented_analysis.json')
    with open(output_path, 'w') as f:
        json.dump({
            'analyses_by_length': analyses,
            'cross_segment_comparison': comparison,
            'segments': {k: [{'text': t['text'], 'z_score': t['z_score']} for t in v[:10]] for k, v in segments.items()}
        }, f, indent=2)

    print(f"\n✓ Detailed analysis saved to: {output_path}\n")


if __name__ == "__main__":
    main()
