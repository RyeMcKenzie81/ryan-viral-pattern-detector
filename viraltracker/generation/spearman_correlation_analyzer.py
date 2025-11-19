"""
Spearman Correlation Analyzer

Runs Spearman correlations between features and z-score across ALL tweets
(viral + non-viral combined) to find what correlates with virality.
"""

import json
import re
import sys
from typing import List, Dict, Any
import numpy as np
from scipy.stats import spearmanr


class SpearmanCorrelationAnalyzer:
    """Analyzes correlation between features and z-score across all tweets."""

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
                'has_url': int('http' in text.lower() or 't.co' in text.lower()),
                'has_number': int(bool(re.search(r'\d', text))),
                'has_question': int('?' in text),
                'has_exclamation': int('!' in text),
                'emoji_count': len(re.findall(r'[^\w\s,.:;!?-]', text)),
                'sentence_count': max(1, len(re.split(r'[.!?]+', text)) - 1),

                # Voice/tone
                'first_person_count': sum(text.lower().count(w) for w in [' i ', ' me ', ' my ', ' we ', ' us ', ' our ']),
                'has_first_person': int(sum(text.lower().count(w) for w in [' i ', ' me ', ' my ', ' we ', ' us ', ' our ']) > 0),
                'second_person_count': sum(text.lower().count(w) for w in [' you ', ' your ', ' yours ']),
                'has_second_person': int(sum(text.lower().count(w) for w in [' you ', ' your ', ' yours ']) > 0),

                # Urgency
                'has_urgency': int(any(word in text.lower() for word in ['today', 'now', 'just', 'breaking', 'urgent'])),

                # Data/authority
                'has_data': int(any(word in text.lower() for word in ['study', 'research', 'data', 'survey', 'report']) or bool(re.search(r'\d+%', text))),

                # Length category (as ordinal: 0=short, 1=medium, 2=long)
                'length_ordinal': 0 if word_count < 30 else (1 if word_count <= 60 else 2),
            }

            features.append(feature_dict)

        return features

    def run_correlations(self) -> Dict[str, Any]:
        """Run Spearman correlations on all tweets combined."""

        # Extract features for all tweets
        viral_features = self.extract_features(self.viral_tweets)
        nonviral_features = self.extract_features(self.nonviral_tweets)
        all_features = viral_features + nonviral_features

        print(f"\nAnalyzing {len(viral_features)} viral + {len(nonviral_features)} non-viral = {len(all_features)} total tweets")

        # Prepare results
        results = {
            'sample_size': len(all_features),
            'viral_count': len(viral_features),
            'nonviral_count': len(nonviral_features),
            'correlations': {}
        }

        # Get z-scores
        z_scores = np.array([t['z_score'] for t in all_features])

        # Features to analyze
        numeric_features = [
            ('word_count', 'Word Count'),
            ('char_count', 'Character Count'),
            ('mention_count', 'Mention Count'),
            ('emoji_count', 'Emoji Count'),
            ('sentence_count', 'Sentence Count'),
            ('first_person_count', 'First-Person Count'),
            ('second_person_count', 'Second-Person Count'),
            ('followers', 'Follower Count'),
            ('length_ordinal', 'Length Category (ordinal)')
        ]

        boolean_features = [
            ('has_url', 'Has URL'),
            ('has_number', 'Has Number'),
            ('has_question', 'Has Question'),
            ('has_exclamation', 'Has Exclamation'),
            ('has_first_person', 'Has First-Person'),
            ('has_second_person', 'Has Second-Person'),
            ('has_urgency', 'Has Urgency'),
            ('has_data', 'Has Data/Stats')
        ]

        all_feature_list = numeric_features + boolean_features

        # Run correlations
        for feature_key, feature_label in all_feature_list:
            x = np.array([t[feature_key] for t in all_features])

            # Check for variance
            if np.std(x) > 0:
                corr, p_value = spearmanr(x, z_scores)

                results['correlations'][feature_key] = {
                    'label': feature_label,
                    'correlation': float(corr),
                    'p_value': float(p_value),
                    'significant': p_value < 0.05,
                    'effect_size': abs(corr)
                }
            else:
                # No variance
                results['correlations'][feature_key] = {
                    'label': feature_label,
                    'correlation': 0.0,
                    'p_value': 1.0,
                    'significant': False,
                    'effect_size': 0.0
                }

        return results

    def print_results(self, results: Dict):
        """Print correlation results."""
        print(f"\n{'='*80}")
        print("SPEARMAN CORRELATION ANALYSIS - All Tweets Combined")
        print(f"{'='*80}\n")

        print(f"Sample: {results['viral_count']} viral + {results['nonviral_count']} non-viral = {results['sample_size']} total\n")

        # Get significant correlations
        significant = [
            (key, data) for key, data in results['correlations'].items()
            if data['significant']
        ]

        # Sort by absolute correlation
        significant.sort(key=lambda x: abs(x[1]['correlation']), reverse=True)

        if significant:
            print(f"{'='*80}")
            print(f"SIGNIFICANT CORRELATIONS (p < 0.05)")
            print(f"{'='*80}\n")

            for feature_key, data in significant:
                direction = "+" if data['correlation'] > 0 else "-"
                print(f"{data['label']:25} r = {direction}{abs(data['correlation']):.4f}, p = {data['p_value']:.6f}")
        else:
            print("No significant correlations found.\n")

        # All correlations sorted by effect size
        print(f"\n{'='*80}")
        print(f"ALL CORRELATIONS (sorted by absolute correlation)")
        print(f"{'='*80}\n")

        all_corr = [(key, data) for key, data in results['correlations'].items()]
        all_corr.sort(key=lambda x: abs(x[1]['correlation']), reverse=True)

        for feature_key, data in all_corr:
            sig = "✓" if data['significant'] else "✗"
            direction = "+" if data['correlation'] > 0 else "-"
            print(f"{sig} {data['label']:25} r = {direction}{abs(data['correlation']):.4f}, p = {data['p_value']:.6f}")


def main():
    """Run Spearman correlation analysis."""
    if len(sys.argv) < 3:
        print("Usage: python spearman_correlation_analyzer.py <viral.json> <nonviral.json>")
        sys.exit(1)

    viral_path = sys.argv[1]
    nonviral_path = sys.argv[2]

    analyzer = SpearmanCorrelationAnalyzer(viral_path, nonviral_path)
    results = analyzer.run_correlations()
    analyzer.print_results(results)

    # Save results
    output_path = viral_path.replace('.json', '_spearman_correlations.json')
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"\n✓ Results saved to: {output_path}\n")


if __name__ == "__main__":
    main()
