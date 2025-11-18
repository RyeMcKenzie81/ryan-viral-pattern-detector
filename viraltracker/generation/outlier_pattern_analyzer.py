"""
Outlier Pattern Analyzer

Analyzes top outliers to identify patterns beyond hooks that correlate with virality.
"""

import json
import re
from typing import List, Dict, Any
from datetime import datetime
from collections import Counter
import numpy as np
from scipy.stats import spearmanr


class OutlierPatternAnalyzer:
    """Analyzes patterns in viral outlier tweets."""

    def __init__(self, outliers_path: str):
        """Initialize with path to outliers JSON."""
        with open(outliers_path, 'r') as f:
            data = json.load(f)
        self.outliers = data['outliers']
        self.features = []

    def extract_features(self, top_n: int = 100) -> List[Dict[str, Any]]:
        """Extract features from top N outliers."""
        top_outliers = self.outliers[:top_n]

        features_list = []
        for outlier in top_outliers:
            text = outlier['text']
            features = {
                # Basic metrics
                'rank': outlier['rank'],
                'views': outlier['metrics']['views'],
                'likes': outlier['metrics']['likes'],
                'replies': outlier['metrics']['replies'],
                'retweets': outlier['metrics']['retweets'],
                'engagement_rate': outlier['metrics']['engagement_rate'],
                'engagement_score': outlier['metrics']['engagement_score'],
                'z_score': outlier['outlier_metrics']['z_score'],
                'author_followers': outlier['author_followers'],

                # Text length features
                'char_count': len(text),
                'word_count': len(text.split()),
                'avg_word_length': np.mean([len(w) for w in text.split()]) if text.split() else 0,
                'sentence_count': len([s for s in text.split('.') if s.strip()]),

                # Punctuation & formatting
                'has_question': '?' in text,
                'question_count': text.count('?'),
                'has_exclamation': '!' in text,
                'exclamation_count': text.count('!'),
                'has_quotes': '"' in text or '"' in text or '"' in text or "'" in text,
                'emoji_count': len(re.findall(r'[^\w\s,.:;!?-]', text)),
                'ellipsis_count': text.count('...') + text.count('…'),

                # Content features
                'has_number': bool(re.search(r'\d', text)),
                'number_count': len(re.findall(r'\d+', text)),
                'has_dollar': '$' in text,
                'has_percentage': '%' in text,
                'has_url': 'http' in text.lower() or 't.co' in text.lower(),
                'has_mention': '@' in text,
                'mention_count': text.count('@'),
                'has_hashtag': '#' in text,
                'hashtag_count': text.count('#'),

                # Capitalization
                'all_caps_words': len([w for w in text.split() if w.isupper() and len(w) > 1]),
                'starts_with_caps': text[0].isupper() if text else False,

                # Specific keywords/phrases
                'has_we': ' we ' in text.lower() or text.lower().startswith('we '),
                'has_you': ' you ' in text.lower() or text.lower().startswith('you '),
                'has_i': ' i ' in text.lower() or text.lower().startswith('i '),
                'has_breaking': 'breaking' in text.lower(),
                'has_new': 'new' in text.lower(),
                'has_just': 'just' in text.lower(),
                'has_now': 'now' in text.lower(),
                'has_today': 'today' in text.lower(),
                'has_call_to_action': any(word in text.lower() for word in ['check', 'watch', 'read', 'listen', 'click', 'follow', 'share', 'retweet']),

                # Authority/credibility markers
                'has_data_cite': any(word in text.lower() for word in ['study', 'research', 'report', 'survey', 'data', 'according to']),
                'has_expert_cite': any(word in text.lower() for word in ['expert', 'professor', 'doctor', 'researcher', 'scientist']),

                # Controversy/emotion words
                'has_controversy': any(word in text.lower() for word in ['outrage', 'shocking', 'scandal', 'controversy', 'crisis', 'disaster']),
                'has_negative_emotion': any(word in text.lower() for word in ['angry', 'terrible', 'horrible', 'awful', 'worst', 'disgusting', 'hate']),
                'has_positive_emotion': any(word in text.lower() for word in ['amazing', 'incredible', 'awesome', 'wonderful', 'love', 'perfect', 'beautiful']),

                # Timing features
                'posted_hour': datetime.fromisoformat(outlier['posted_at'].replace('Z', '+00:00')).hour,
                'posted_day_of_week': datetime.fromisoformat(outlier['posted_at'].replace('Z', '+00:00')).weekday(),

                # Author features
                'is_verified': outlier['author_followers'] > 10000,  # Proxy for verification
                'follower_tier': self._get_follower_tier(outlier['author_followers']),

                # Original text for reference
                'text': text,
                'author': outlier['author'],
                'url': outlier['url'],
            }
            features_list.append(features)

        self.features = features_list
        return features_list

    def _get_follower_tier(self, followers: int) -> str:
        """Categorize follower count into tiers."""
        if followers < 1000:
            return 'micro'
        elif followers < 10000:
            return 'small'
        elif followers < 100000:
            return 'medium'
        elif followers < 1000000:
            return 'large'
        else:
            return 'mega'

    def generate_hypotheses(self) -> Dict[str, str]:
        """Generate hypotheses about viral factors."""
        if not self.features:
            raise ValueError("Extract features first using extract_features()")

        hypotheses = {
            'H1_authority': 'Tweets from accounts with larger followings (authority) have higher virality',
            'H2_numbers': 'Tweets with specific numbers/statistics are more viral',
            'H3_questions': 'Tweets with questions engage more viewers',
            'H4_emotion': 'Tweets with emotional content (positive or negative) perform better',
            'H5_controversy': 'Controversial or shocking content drives more engagement',
            'H6_length': 'Shorter tweets with focused messages are more viral',
            'H7_urgency': 'Tweets with urgency markers (now, just, breaking) get more attention',
            'H8_call_to_action': 'Tweets with clear CTAs drive higher engagement',
            'H9_data_authority': 'Tweets citing studies/research/data are more credible and viral',
            'H10_timing': 'Posting time affects virality',
            'H11_media': 'Tweets with URLs/media get more engagement',
            'H12_social_proof': 'Mentions and hashtags increase reach',
            'H13_punctuation': 'Strategic use of punctuation (!, ?) increases engagement',
            'H14_personal': 'Personal pronouns (I, we, you) create connection',
            'H15_formatting': 'All-caps words for emphasis drive attention',
        }

        return hypotheses

    def calculate_correlations(self) -> Dict[str, Any]:
        """Calculate Spearman correlations between features and virality metrics."""
        if not self.features:
            raise ValueError("Extract features first using extract_features()")

        # Prepare data for correlation analysis
        numeric_features = [
            'char_count', 'word_count', 'avg_word_length', 'sentence_count',
            'question_count', 'exclamation_count', 'emoji_count', 'ellipsis_count',
            'number_count', 'mention_count', 'hashtag_count', 'all_caps_words',
            'author_followers', 'posted_hour'
        ]

        boolean_features = [
            'has_question', 'has_exclamation', 'has_quotes', 'has_number',
            'has_dollar', 'has_percentage', 'has_url', 'has_mention', 'has_hashtag',
            'has_we', 'has_you', 'has_i', 'has_breaking', 'has_new', 'has_just',
            'has_now', 'has_today', 'has_call_to_action', 'has_data_cite',
            'has_expert_cite', 'has_controversy', 'has_negative_emotion',
            'has_positive_emotion'
        ]

        # Virality metrics to correlate against
        virality_metrics = ['views', 'engagement_rate', 'engagement_score', 'z_score']

        correlations = {}

        for metric in virality_metrics:
            correlations[metric] = {}
            y = np.array([f[metric] for f in self.features])

            # Numeric features
            for feature in numeric_features:
                x = np.array([f[feature] for f in self.features])
                # Filter out any NaN or inf values
                mask = np.isfinite(x) & np.isfinite(y)
                if mask.sum() > 2:  # Need at least 3 points
                    corr, p_value = spearmanr(x[mask], y[mask])
                    correlations[metric][feature] = {
                        'correlation': float(corr),
                        'p_value': float(p_value),
                        'significant': p_value < 0.05
                    }

            # Boolean features (convert to 0/1)
            for feature in boolean_features:
                x = np.array([1 if f[feature] else 0 for f in self.features])
                mask = np.isfinite(y)
                if mask.sum() > 2:
                    corr, p_value = spearmanr(x[mask], y[mask])
                    correlations[metric][feature] = {
                        'correlation': float(corr),
                        'p_value': float(p_value),
                        'significant': p_value < 0.05
                    }

        return correlations

    def summarize_patterns(self) -> Dict[str, Any]:
        """Summarize key patterns found in outliers."""
        if not self.features:
            raise ValueError("Extract features first using extract_features()")

        summary = {
            'total_analyzed': len(self.features),

            # Text characteristics
            'avg_char_count': np.mean([f['char_count'] for f in self.features]),
            'avg_word_count': np.mean([f['word_count'] for f in self.features]),
            'avg_sentence_count': np.mean([f['sentence_count'] for f in self.features]),

            # Prevalence of features (%)
            'pct_with_questions': 100 * sum(f['has_question'] for f in self.features) / len(self.features),
            'pct_with_exclamations': 100 * sum(f['has_exclamation'] for f in self.features) / len(self.features),
            'pct_with_numbers': 100 * sum(f['has_number'] for f in self.features) / len(self.features),
            'pct_with_url': 100 * sum(f['has_url'] for f in self.features) / len(self.features),
            'pct_with_mentions': 100 * sum(f['has_mention'] for f in self.features) / len(self.features),
            'pct_with_hashtags': 100 * sum(f['has_hashtag'] for f in self.features) / len(self.features),
            'pct_with_emoji': 100 * sum(f['emoji_count'] > 0 for f in self.features) / len(self.features),
            'pct_with_cta': 100 * sum(f['has_call_to_action'] for f in self.features) / len(self.features),
            'pct_with_data_cite': 100 * sum(f['has_data_cite'] for f in self.features) / len(self.features),
            'pct_with_controversy': 100 * sum(f['has_controversy'] for f in self.features) / len(self.features),
            'pct_with_negative_emotion': 100 * sum(f['has_negative_emotion'] for f in self.features) / len(self.features),
            'pct_with_positive_emotion': 100 * sum(f['has_positive_emotion'] for f in self.features) / len(self.features),
            'pct_with_urgency': 100 * sum(f['has_breaking'] or f['has_just'] or f['has_now'] for f in self.features) / len(self.features),

            # Follower distribution
            'follower_tiers': Counter(f['follower_tier'] for f in self.features),
            'avg_follower_count': np.mean([f['author_followers'] for f in self.features]),
            'median_follower_count': np.median([f['author_followers'] for f in self.features]),

            # Timing patterns
            'hour_distribution': Counter(f['posted_hour'] for f in self.features),
            'day_distribution': Counter(f['posted_day_of_week'] for f in self.features),

            # Engagement metrics
            'avg_views': np.mean([f['views'] for f in self.features]),
            'avg_engagement_rate': np.mean([f['engagement_rate'] for f in self.features]),
            'avg_engagement_score': np.mean([f['engagement_score'] for f in self.features]),
        }

        return summary

    def get_top_features_by_correlation(self, metric: str = 'z_score', top_n: int = 10) -> List[Dict[str, Any]]:
        """Get top N features most correlated with a given metric."""
        correlations = self.calculate_correlations()

        if metric not in correlations:
            raise ValueError(f"Metric '{metric}' not found. Available: {list(correlations.keys())}")

        # Sort by absolute correlation value
        sorted_features = sorted(
            correlations[metric].items(),
            key=lambda x: abs(x[1]['correlation']),
            reverse=True
        )

        return [
            {
                'feature': feat,
                'correlation': data['correlation'],
                'p_value': data['p_value'],
                'significant': data['significant']
            }
            for feat, data in sorted_features[:top_n]
        ]


def main():
    """Run analysis and print results."""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python outlier_pattern_analyzer.py <outliers.json> [top_n]")
        sys.exit(1)

    outliers_path = sys.argv[1]
    top_n = int(sys.argv[2]) if len(sys.argv) > 2 else 100

    analyzer = OutlierPatternAnalyzer(outliers_path)

    print(f"\n{'='*80}")
    print(f"OUTLIER PATTERN ANALYSIS - Top {top_n} Tweets")
    print(f"{'='*80}\n")

    # Extract features
    print("Extracting features...")
    features = analyzer.extract_features(top_n)
    print(f"✓ Extracted {len(features)} feature vectors\n")

    # Generate hypotheses
    print("="*80)
    print("HYPOTHESES ABOUT VIRAL FACTORS")
    print("="*80)
    hypotheses = analyzer.generate_hypotheses()
    for i, (key, hypothesis) in enumerate(hypotheses.items(), 1):
        print(f"{i}. {hypothesis}")
    print()

    # Summarize patterns
    print("="*80)
    print("PATTERN SUMMARY")
    print("="*80)
    summary = analyzer.summarize_patterns()

    print(f"\n📊 Text Characteristics:")
    print(f"  • Avg character count: {summary['avg_char_count']:.1f}")
    print(f"  • Avg word count: {summary['avg_word_count']:.1f}")
    print(f"  • Avg sentence count: {summary['avg_sentence_count']:.1f}")

    print(f"\n📈 Feature Prevalence:")
    print(f"  • Questions: {summary['pct_with_questions']:.1f}%")
    print(f"  • Exclamations: {summary['pct_with_exclamations']:.1f}%")
    print(f"  • Numbers/Stats: {summary['pct_with_numbers']:.1f}%")
    print(f"  • URLs/Media: {summary['pct_with_url']:.1f}%")
    print(f"  • Mentions: {summary['pct_with_mentions']:.1f}%")
    print(f"  • Hashtags: {summary['pct_with_hashtags']:.1f}%")
    print(f"  • Emojis: {summary['pct_with_emoji']:.1f}%")
    print(f"  • Call-to-Action: {summary['pct_with_cta']:.1f}%")
    print(f"  • Data Citations: {summary['pct_with_data_cite']:.1f}%")
    print(f"  • Controversy: {summary['pct_with_controversy']:.1f}%")
    print(f"  • Negative Emotion: {summary['pct_with_negative_emotion']:.1f}%")
    print(f"  • Positive Emotion: {summary['pct_with_positive_emotion']:.1f}%")
    print(f"  • Urgency Markers: {summary['pct_with_urgency']:.1f}%")

    print(f"\n👥 Author Characteristics:")
    print(f"  • Avg followers: {summary['avg_follower_count']:,.0f}")
    print(f"  • Median followers: {summary['median_follower_count']:,.0f}")
    print(f"  • Follower tiers: {dict(summary['follower_tiers'])}")

    print(f"\n⏰ Timing Patterns:")
    print(f"  • Most common hours: {summary['hour_distribution'].most_common(3)}")
    print(f"  • Most common days: {summary['day_distribution'].most_common(3)}")

    # Calculate correlations
    print("\n" + "="*80)
    print("TOP CORRELATIONS WITH VIRALITY (Z-Score)")
    print("="*80)
    top_features = analyzer.get_top_features_by_correlation('z_score', 15)

    print(f"\n{'Feature':<30} {'Correlation':>12} {'P-Value':>12} {'Significant':>12}")
    print("-"*80)
    for item in top_features:
        sig = "✓" if item['significant'] else "✗"
        print(f"{item['feature']:<30} {item['correlation']:>12.4f} {item['p_value']:>12.4f} {sig:>12}")

    # Save detailed results
    output_path = outliers_path.replace('.json', '_analysis.json')
    with open(output_path, 'w') as f:
        json.dump({
            'hypotheses': hypotheses,
            'summary': summary,
            'correlations': analyzer.calculate_correlations(),
            'features': features
        }, f, indent=2)

    print(f"\n✓ Detailed analysis saved to: {output_path}")
    print()


if __name__ == "__main__":
    main()
