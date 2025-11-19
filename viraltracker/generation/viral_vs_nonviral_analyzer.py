"""
Viral vs Non-Viral Comparison Analyzer

Compares feature prevalence between viral and non-viral tweets to identify
what ACTUALLY causes virality (not just what varies among viral tweets).

This addresses the selection bias problem where analyzing only viral tweets
can find spurious correlations.
"""

import json
import re
from typing import List, Dict, Any
import numpy as np
from scipy.stats import mannwhitneyu, chi2_contingency
from collections import Counter


class ViralVsNonViralAnalyzer:
    """Compares viral vs non-viral tweets to identify causal factors."""

    def __init__(self, viral_path: str, nonviral_path: str):
        """Initialize with paths to viral and non-viral JSON files."""
        with open(viral_path, 'r') as f:
            viral_data = json.load(f)
        with open(nonviral_path, 'r') as f:
            nonviral_data = json.load(f)

        self.viral_tweets = viral_data['outliers']
        self.nonviral_tweets = nonviral_data['outliers']

    def extract_features(self, tweets: List[Dict]) -> List[Dict[str, Any]]:
        """Extract features from tweets."""
        features = []

        for tweet in tweets:
            text = tweet['text']
            word_count = len(text.split())

            feature_dict = {
                # Basic metadata
                'text': text,
                'word_count': word_count,
                'char_count': len(text),
                'z_score': tweet['outlier_metrics']['z_score'],
                'views': tweet['metrics']['views'],
                'engagement_rate': tweet['metrics']['engagement_rate'],
                'followers': tweet['author_followers'],

                # Content features
                'mention_count': text.count('@'),
                'has_url': 'http' in text.lower() or 't.co' in text.lower(),
                'has_number': bool(re.search(r'\d', text)),
                'has_question': '?' in text,
                'has_exclamation': '!' in text,
                'emoji_count': len(re.findall(r'[^\w\s,.:;!?-]', text)),
                'sentence_count': max(1, len(re.split(r'[.!?]+', text)) - 1),

                # Voice/tone
                'first_person_count': sum(text.lower().count(w) for w in [' i ', ' me ', ' my ', ' we ', ' us ', ' our ']),
                'has_first_person': sum(text.lower().count(w) for w in [' i ', ' me ', ' my ', ' we ', ' us ', ' our ']) > 0,
                'second_person_count': sum(text.lower().count(w) for w in [' you ', ' your ', ' yours ']),
                'has_second_person': sum(text.lower().count(w) for w in [' you ', ' your ', ' yours ']) > 0,

                # Urgency
                'has_urgency': any(word in text.lower() for word in ['today', 'now', 'just', 'breaking', 'urgent']),

                # Data/authority
                'has_data': any(word in text.lower() for word in ['study', 'research', 'data', 'survey', 'report']) or bool(re.search(r'\d+%', text)),

                # Length category
                'length_category': 'short' if word_count < 30 else ('medium' if word_count <= 60 else 'long'),
            }

            features.append(feature_dict)

        return features

    def compare_prevalence(self) -> Dict[str, Any]:
        """Compare feature prevalence between viral and non-viral tweets."""

        viral_features = self.extract_features(self.viral_tweets[:100])
        nonviral_features = self.extract_features(self.nonviral_tweets)

        print(f"\nAnalyzing {len(viral_features)} viral vs {len(nonviral_features)} non-viral tweets")

        results = {
            'sample_sizes': {
                'viral': len(viral_features),
                'nonviral': len(nonviral_features)
            },
            'boolean_features': {},
            'numeric_features': {},
            'categorical_features': {}
        }

        # Boolean features comparison
        boolean_features = [
            'has_url', 'has_first_person', 'has_second_person',
            'has_urgency', 'has_data', 'has_question', 'has_exclamation', 'has_number'
        ]

        for feature in boolean_features:
            viral_count = sum(1 for t in viral_features if t[feature])
            nonviral_count = sum(1 for t in nonviral_features if t[feature])

            viral_pct = 100 * viral_count / len(viral_features)
            nonviral_pct = 100 * nonviral_count / len(nonviral_features)

            # Chi-square test for independence
            contingency_table = [
                [viral_count, len(viral_features) - viral_count],
                [nonviral_count, len(nonviral_features) - nonviral_count]
            ]

            chi2, p_value, _, _ = chi2_contingency(contingency_table)

            # Effect size (percentage point difference)
            effect_size = viral_pct - nonviral_pct

            results['boolean_features'][feature] = {
                'viral_prevalence': round(viral_pct, 1),
                'nonviral_prevalence': round(nonviral_pct, 1),
                'difference_pct_points': round(effect_size, 1),
                'p_value': float(p_value),
                'significant': p_value < 0.05,
                'chi2': float(chi2)
            }

        # Numeric features comparison (Mann-Whitney U test)
        numeric_features = [
            ('mention_count', 'Mention count'),
            ('word_count', 'Word count'),
            ('emoji_count', 'Emoji count'),
            ('sentence_count', 'Sentence count'),
            ('first_person_count', 'First-person count'),
            ('second_person_count', 'Second-person count'),
            ('followers', 'Follower count')
        ]

        for feature, label in numeric_features:
            viral_values = [t[feature] for t in viral_features]
            nonviral_values = [t[feature] for t in nonviral_features]

            viral_median = np.median(viral_values)
            nonviral_median = np.median(nonviral_values)

            # Mann-Whitney U test (non-parametric)
            if len(set(viral_values + nonviral_values)) > 1:  # Has variance
                stat, p_value = mannwhitneyu(viral_values, nonviral_values, alternative='two-sided')

                # Effect size (median difference and ratio)
                median_diff = viral_median - nonviral_median
                if nonviral_median > 0:
                    ratio = viral_median / nonviral_median
                else:
                    ratio = None

                results['numeric_features'][feature] = {
                    'viral_median': float(viral_median),
                    'nonviral_median': float(nonviral_median),
                    'median_difference': float(median_diff),
                    'ratio': float(ratio) if ratio else None,
                    'p_value': float(p_value),
                    'significant': p_value < 0.05,
                    'u_statistic': float(stat)
                }

        # Categorical feature: length_category
        viral_lengths = Counter(t['length_category'] for t in viral_features)
        nonviral_lengths = Counter(t['length_category'] for t in nonviral_features)

        categories = ['short', 'medium', 'long']
        viral_dist = {cat: 100 * viral_lengths[cat] / len(viral_features) for cat in categories}
        nonviral_dist = {cat: 100 * nonviral_lengths[cat] / len(nonviral_features) for cat in categories}

        results['categorical_features']['length_category'] = {
            'viral_distribution': viral_dist,
            'nonviral_distribution': nonviral_dist,
            'difference': {cat: viral_dist[cat] - nonviral_dist[cat] for cat in categories}
        }

        return results

    def identify_key_differentiators(self, results: Dict) -> List[Dict]:
        """Identify features that significantly differ between viral and non-viral."""
        differentiators = []

        # Boolean features
        for feature, data in results['boolean_features'].items():
            if data['significant']:
                differentiators.append({
                    'feature': feature.replace('_', ' ').title(),
                    'type': 'boolean',
                    'viral_prevalence': data['viral_prevalence'],
                    'nonviral_prevalence': data['nonviral_prevalence'],
                    'effect': data['difference_pct_points'],
                    'p_value': data['p_value'],
                    'interpretation': self._interpret_boolean_effect(
                        feature, data['viral_prevalence'], data['nonviral_prevalence'], data['difference_pct_points']
                    )
                })

        # Numeric features
        for feature, data in results['numeric_features'].items():
            if data['significant']:
                differentiators.append({
                    'feature': feature.replace('_', ' ').title(),
                    'type': 'numeric',
                    'viral_median': data['viral_median'],
                    'nonviral_median': data['nonviral_median'],
                    'effect': data['median_difference'],
                    'ratio': data['ratio'],
                    'p_value': data['p_value'],
                    'interpretation': self._interpret_numeric_effect(
                        feature, data['viral_median'], data['nonviral_median'], data['ratio']
                    )
                })

        # Sort by effect size (absolute)
        differentiators.sort(key=lambda x: abs(x['effect']), reverse=True)

        return differentiators

    def _interpret_boolean_effect(self, feature: str, viral_pct: float, nonviral_pct: float, diff: float) -> str:
        """Interpret boolean feature effect."""
        direction = "more" if diff > 0 else "less"
        abs_diff = abs(diff)

        if abs_diff < 5:
            magnitude = "slightly"
        elif abs_diff < 15:
            magnitude = "moderately"
        else:
            magnitude = "much"

        return f"Viral tweets are {magnitude} {direction} likely to have this ({viral_pct:.1f}% vs {nonviral_pct:.1f}%)"

    def _interpret_numeric_effect(self, feature: str, viral_med: float, nonviral_med: float, ratio: float) -> str:
        """Interpret numeric feature effect."""
        if ratio and ratio > 1:
            pct_change = (ratio - 1) * 100
            return f"Viral tweets have {pct_change:.0f}% more ({viral_med:.1f} vs {nonviral_med:.1f})"
        elif ratio and ratio < 1:
            pct_change = (1 - ratio) * 100
            return f"Viral tweets have {pct_change:.0f}% less ({viral_med:.1f} vs {nonviral_med:.1f})"
        else:
            diff = viral_med - nonviral_med
            return f"Viral tweets differ by {diff:+.1f} ({viral_med:.1f} vs {nonviral_med:.1f})"


def main():
    """Run viral vs non-viral comparison analysis."""
    import sys

    if len(sys.argv) < 3:
        print("Usage: python viral_vs_nonviral_analyzer.py <viral.json> <nonviral.json>")
        sys.exit(1)

    viral_path = sys.argv[1]
    nonviral_path = sys.argv[2]

    analyzer = ViralVsNonViralAnalyzer(viral_path, nonviral_path)

    print(f"\n{'='*80}")
    print("VIRAL VS NON-VIRAL COMPARISON ANALYSIS")
    print(f"{'='*80}")

    # Run comparison
    results = analyzer.compare_prevalence()

    # Identify key differentiators
    print(f"\n{'='*80}")
    print("KEY DIFFERENTIATORS (p < 0.05)")
    print(f"{'='*80}\n")

    differentiators = analyzer.identify_key_differentiators(results)

    if differentiators:
        for i, diff in enumerate(differentiators, 1):
            print(f"{i}. {diff['feature']}")
            print(f"   {diff['interpretation']}")
            print(f"   p-value: {diff['p_value']:.4f}\n")
    else:
        print("No statistically significant differentiators found.\n")

    # Detailed breakdown
    print(f"{'='*80}")
    print("DETAILED BREAKDOWN")
    print(f"{'='*80}\n")

    print("BOOLEAN FEATURES:")
    for feature, data in sorted(results['boolean_features'].items(),
                                key=lambda x: abs(x[1]['difference_pct_points']), reverse=True):
        sig = "✓" if data['significant'] else "✗"
        print(f"\n  {sig} {feature.replace('_', ' ').title()}")
        print(f"     Viral: {data['viral_prevalence']:.1f}%")
        print(f"     Non-viral: {data['nonviral_prevalence']:.1f}%")
        print(f"     Difference: {data['difference_pct_points']:+.1f} percentage points")
        print(f"     p-value: {data['p_value']:.4f}")

    print(f"\n\nNUMERIC FEATURES:")
    for feature, data in sorted(results['numeric_features'].items(),
                                key=lambda x: abs(x[1]['median_difference']), reverse=True):
        sig = "✓" if data['significant'] else "✗"
        print(f"\n  {sig} {feature.replace('_', ' ').title()}")
        print(f"     Viral median: {data['viral_median']:.1f}")
        print(f"     Non-viral median: {data['nonviral_median']:.1f}")
        if data['ratio']:
            print(f"     Ratio: {data['ratio']:.2f}x")
        print(f"     p-value: {data['p_value']:.4f}")

    print(f"\n\nLENGTH DISTRIBUTION:")
    length_data = results['categorical_features']['length_category']
    for category in ['short', 'medium', 'long']:
        viral_pct = length_data['viral_distribution'][category]
        nonviral_pct = length_data['nonviral_distribution'][category]
        diff = length_data['difference'][category]
        print(f"  {category.title()}: Viral {viral_pct:.1f}% | Non-viral {nonviral_pct:.1f}% | Diff: {diff:+.1f}pp")

    # Save results (convert numpy bools to Python bools)
    output_path = viral_path.replace('.json', '_comparison_results.json')

    # Convert numpy types to Python types
    def convert_numpy(obj):
        if isinstance(obj, dict):
            return {k: convert_numpy(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [convert_numpy(item) for item in obj]
        elif isinstance(obj, np.bool_):
            return bool(obj)
        elif isinstance(obj, (np.integer, np.floating)):
            return float(obj)
        else:
            return obj

    results_clean = convert_numpy(results)
    differentiators_clean = convert_numpy(differentiators)

    with open(output_path, 'w') as f:
        json.dump({
            'comparison_results': results_clean,
            'key_differentiators': differentiators_clean
        }, f, indent=2)

    print(f"\n\n✓ Detailed results saved to: {output_path}\n")


if __name__ == "__main__":
    main()
