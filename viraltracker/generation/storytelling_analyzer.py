"""
Storytelling Pattern Analyzer

Analyzes narrative and storytelling elements in viral tweets.
"""

import json
import re
from typing import List, Dict, Any
import numpy as np
from scipy.stats import spearmanr, mannwhitneyu
from collections import Counter


class StorytellingAnalyzer:
    """Analyzes storytelling patterns in tweets."""

    def __init__(self, outliers_path: str):
        """Initialize with path to outliers JSON."""
        with open(outliers_path, 'r') as f:
            data = json.load(f)
        self.outliers = data['outliers']
        self.features = []

    def extract_storytelling_features(self, top_n: int = 100) -> List[Dict[str, Any]]:
        """Extract storytelling-specific features."""
        top_outliers = self.outliers[:top_n]

        features_list = []
        for outlier in top_outliers:
            text = outlier['text']
            words = text.lower().split()

            features = {
                # Basic info
                'rank': outlier['rank'],
                'views': outlier['metrics']['views'],
                'z_score': outlier['outlier_metrics']['z_score'],
                'text': text,
                'author': outlier['author'],
                'url': outlier['url'],

                # Narrative structure
                'has_temporal_sequence': self._has_temporal_sequence(text),
                'has_cause_effect': self._has_cause_effect(text),
                'has_transformation': self._has_transformation(text),
                'has_dialogue': self._has_dialogue(text),

                # Storytelling tense
                'past_tense_ratio': self._calculate_past_tense_ratio(text),
                'is_past_tense_narrative': self._calculate_past_tense_ratio(text) > 0.3,
                'present_tense_ratio': self._calculate_present_tense_ratio(text),

                # Point of view
                'first_person_count': self._count_first_person(text),
                'is_first_person': self._count_first_person(text) > 0,
                'third_person_count': self._count_third_person(text),
                'is_third_person': self._count_third_person(text) > 0,
                'second_person_you': ' you ' in text.lower() or text.lower().startswith('you '),

                # Story elements
                'has_protagonist': self._has_protagonist(text),
                'has_conflict': self._has_conflict(text),
                'has_resolution': self._has_resolution(text),
                'has_lesson': self._has_lesson(text),

                # Narrative vs data-driven
                'has_anecdote': self._has_anecdote(text),
                'has_statistics': self._has_statistics(text),
                'has_example': self._has_example(text),
                'is_anecdotal': self._has_anecdote(text) and not self._has_statistics(text),
                'is_data_driven': self._has_statistics(text) and not self._has_anecdote(text),
                'is_hybrid': self._has_anecdote(text) and self._has_statistics(text),

                # Concrete vs abstract
                'concreteness_score': self._calculate_concreteness(text),
                'has_sensory_details': self._has_sensory_details(text),
                'has_specific_names': self._has_specific_names(text),

                # Story flow markers
                'has_opening_hook': self._has_opening_hook(text),
                'has_suspense': '...' in text or '…' in text,
                'has_surprise': any(word in text.lower() for word in ['shocking', 'unexpected', 'surprise', 'turns out', 'actually']),
                'has_emotional_arc': self._has_emotional_arc(text),

                # Narrative complexity
                'sentence_variety': self._calculate_sentence_variety(text),
                'uses_quotes': '"' in text or '"' in text or '"' in text,
                'has_parentheticals': '(' in text,
                'has_rhetorical_question': '?' in text and any(word in text.lower() for word in ['why', 'how', 'what', 'when', 'who']),
            }

            features_list.append(features)

        self.features = features_list
        return features_list

    def _has_temporal_sequence(self, text: str) -> bool:
        """Detect temporal sequencing (then, after, before, now, later, etc.)."""
        markers = ['then', 'after', 'before', 'next', 'later', 'first', 'finally', 'eventually', 'soon']
        return any(f' {marker} ' in text.lower() or text.lower().startswith(f'{marker} ') for marker in markers)

    def _has_cause_effect(self, text: str) -> bool:
        """Detect cause-effect relationships."""
        markers = ['because', 'so', 'therefore', 'that\'s why', 'as a result', 'led to', 'caused', 'made']
        return any(marker in text.lower() for marker in markers)

    def _has_transformation(self, text: str) -> bool:
        """Detect transformation/change narratives."""
        markers = ['used to', 'now', 'changed', 'became', 'turned into', 'went from', 'no longer', 'started']
        return any(marker in text.lower() for marker in markers)

    def _has_dialogue(self, text: str) -> bool:
        """Detect dialogue or quotes."""
        return bool(re.search(r'["\'""].*["\'""]', text))

    def _calculate_past_tense_ratio(self, text: str) -> float:
        """Calculate ratio of past tense verbs."""
        # Common past tense markers
        past_patterns = [
            r'\b\w+ed\b',  # regular past tense
            r'\b(was|were|had|did|said|told|went|came|saw|made|got|took)\b'  # irregular past
        ]
        past_count = sum(len(re.findall(pattern, text.lower())) for pattern in past_patterns)
        words = len(text.split())
        return past_count / words if words > 0 else 0

    def _calculate_present_tense_ratio(self, text: str) -> float:
        """Calculate ratio of present tense verbs."""
        present_patterns = [
            r'\b(is|are|am|has|have|do|does|says|tells|goes|comes|sees|makes|gets|takes)\b'
        ]
        present_count = sum(len(re.findall(pattern, text.lower())) for pattern in present_patterns)
        words = len(text.split())
        return present_count / words if words > 0 else 0

    def _count_first_person(self, text: str) -> int:
        """Count first-person pronouns."""
        return sum(text.lower().count(word) for word in [' i ', ' me ', ' my ', ' mine ', ' we ', ' us ', ' our ', ' ours '])

    def _count_third_person(self, text: str) -> int:
        """Count third-person pronouns."""
        return sum(text.lower().count(word) for word in [' he ', ' she ', ' they ', ' him ', ' her ', ' them ', ' his ', ' hers ', ' their '])

    def _has_protagonist(self, text: str) -> bool:
        """Detect presence of a protagonist/character."""
        # First person or third person pronouns suggest a character
        return self._count_first_person(text) > 0 or self._count_third_person(text) > 0

    def _has_conflict(self, text: str) -> bool:
        """Detect conflict/problem."""
        markers = ['problem', 'issue', 'challenge', 'struggle', 'difficult', 'hard', 'fight', 'battle', 'against', 'vs']
        return any(marker in text.lower() for marker in markers)

    def _has_resolution(self, text: str) -> bool:
        """Detect resolution/solution."""
        markers = ['solution', 'solved', 'fixed', 'resolved', 'answer', 'figured out', 'discovered', 'learned']
        return any(marker in text.lower() for marker in markers)

    def _has_lesson(self, text: str) -> bool:
        """Detect moral/lesson."""
        markers = ['lesson', 'learned', 'realize', 'understand', 'important to', 'key is', 'secret is', 'truth is']
        return any(marker in text.lower() for marker in markers)

    def _has_anecdote(self, text: str) -> bool:
        """Detect anecdotal content (personal story/specific incident)."""
        anecdote_markers = [
            self._count_first_person(text) > 2,  # Strong first-person presence
            self._calculate_past_tense_ratio(text) > 0.2,  # Past tense narrative
            any(word in text.lower() for word in ['yesterday', 'last', 'ago', 'remember when', 'one time'])
        ]
        return sum(anecdote_markers) >= 2

    def _has_statistics(self, text: str) -> bool:
        """Detect statistics/data."""
        return bool(re.search(r'\d+%', text)) or bool(re.search(r'\$\d+', text)) or \
               any(word in text.lower() for word in ['study', 'research', 'data', 'survey', 'report', 'statistics'])

    def _has_example(self, text: str) -> bool:
        """Detect examples."""
        return any(word in text.lower() for word in ['example', 'for instance', 'such as', 'like when', 'imagine'])

    def _calculate_concreteness(self, text: str) -> float:
        """Estimate concreteness (specific vs abstract)."""
        # Concrete words: numbers, names, specific nouns
        concrete_score = 0
        if re.search(r'\d', text):
            concrete_score += 1
        if re.search(r'[A-Z][a-z]+', text):  # Proper nouns
            concrete_score += 1
        if self._has_sensory_details(text):
            concrete_score += 1
        return concrete_score / 3

    def _has_sensory_details(self, text: str) -> bool:
        """Detect sensory language."""
        sensory_words = ['saw', 'heard', 'felt', 'smelled', 'tasted', 'looked', 'sounded', 'touched']
        return any(word in text.lower() for word in sensory_words)

    def _has_specific_names(self, text: str) -> bool:
        """Detect specific names (capitalized words that aren't sentence starts)."""
        words = text.split()
        return len([w for w in words[1:] if w and w[0].isupper()]) > 0

    def _has_opening_hook(self, text: str) -> bool:
        """Detect strong opening hooks."""
        first_sentence = text.split('.')[0] if '.' in text else text
        hooks = [
            first_sentence.strip().endswith('?'),  # Question
            len(first_sentence) < 50,  # Short punchy opening
            any(word in first_sentence.lower() for word in ['imagine', 'picture this', 'what if', 'breaking'])
        ]
        return any(hooks)

    def _has_emotional_arc(self, text: str) -> bool:
        """Detect emotional progression."""
        return self._has_conflict(text) and self._has_resolution(text)

    def _calculate_sentence_variety(self, text: str) -> float:
        """Calculate variety in sentence lengths."""
        sentences = [s.strip() for s in text.split('.') if s.strip()]
        if len(sentences) < 2:
            return 0
        lengths = [len(s.split()) for s in sentences]
        return np.std(lengths) if lengths else 0

    def analyze_storytelling_correlations(self) -> Dict[str, Any]:
        """Analyze correlations between storytelling features and virality."""
        if not self.features:
            raise ValueError("Extract features first")

        storytelling_features = [
            'has_temporal_sequence', 'has_cause_effect', 'has_transformation', 'has_dialogue',
            'is_past_tense_narrative', 'is_first_person', 'is_third_person', 'second_person_you',
            'has_protagonist', 'has_conflict', 'has_resolution', 'has_lesson',
            'is_anecdotal', 'is_data_driven', 'is_hybrid', 'has_sensory_details',
            'has_opening_hook', 'has_suspense', 'has_surprise', 'has_emotional_arc',
            'uses_quotes', 'has_parentheticals', 'has_rhetorical_question'
        ]

        numeric_features = ['past_tense_ratio', 'present_tense_ratio', 'first_person_count',
                           'third_person_count', 'concreteness_score', 'sentence_variety']

        correlations = {}
        y = np.array([f['z_score'] for f in self.features])

        # Boolean features
        for feature in storytelling_features:
            x = np.array([1 if f[feature] else 0 for f in self.features])
            if x.sum() > 0 and x.sum() < len(x):  # Not all same value
                corr, p_value = spearmanr(x, y)
                correlations[feature] = {
                    'correlation': float(corr),
                    'p_value': float(p_value),
                    'significant': p_value < 0.05,
                    'prevalence': f"{100 * x.sum() / len(x):.1f}%"
                }

        # Numeric features
        for feature in numeric_features:
            x = np.array([f[feature] for f in self.features])
            if np.std(x) > 0:  # Has variance
                corr, p_value = spearmanr(x, y)
                correlations[feature] = {
                    'correlation': float(corr),
                    'p_value': float(p_value),
                    'significant': p_value < 0.05,
                    'mean': float(np.mean(x))
                }

        return correlations

    def compare_story_vs_data(self) -> Dict[str, Any]:
        """Compare anecdotal vs data-driven content."""
        if not self.features:
            raise ValueError("Extract features first")

        anecdotal = [f for f in self.features if f['is_anecdotal']]
        data_driven = [f for f in self.features if f['is_data_driven']]
        hybrid = [f for f in self.features if f['is_hybrid']]

        comparison = {
            'counts': {
                'anecdotal': len(anecdotal),
                'data_driven': len(data_driven),
                'hybrid': len(hybrid),
                'neither': len(self.features) - len(anecdotal) - len(data_driven) - len(hybrid)
            },
            'avg_z_scores': {
                'anecdotal': float(np.mean([f['z_score'] for f in anecdotal])) if anecdotal else 0,
                'data_driven': float(np.mean([f['z_score'] for f in data_driven])) if data_driven else 0,
                'hybrid': float(np.mean([f['z_score'] for f in hybrid])) if hybrid else 0,
            }
        }

        # Statistical test: anecdotal vs data-driven
        if len(anecdotal) > 0 and len(data_driven) > 0:
            anec_scores = [f['z_score'] for f in anecdotal]
            data_scores = [f['z_score'] for f in data_driven]
            stat, p_value = mannwhitneyu(anec_scores, data_scores, alternative='two-sided')
            comparison['statistical_test'] = {
                'test': 'Mann-Whitney U',
                'statistic': float(stat),
                'p_value': float(p_value),
                'significant': p_value < 0.05
            }

        return comparison

    def get_top_stories(self, n: int = 5) -> List[Dict[str, Any]]:
        """Get top N viral stories with high storytelling scores."""
        if not self.features:
            raise ValueError("Extract features first")

        # Calculate storytelling score
        for f in self.features:
            story_score = sum([
                f['has_temporal_sequence'],
                f['has_cause_effect'],
                f['has_protagonist'],
                f['has_emotional_arc'],
                f['is_first_person'],
                f['is_past_tense_narrative'],
                f['has_anecdote']
            ])
            f['storytelling_score'] = story_score

        # Sort by storytelling score, then by virality
        stories = sorted(
            [f for f in self.features if f['storytelling_score'] >= 3],
            key=lambda x: (x['storytelling_score'], x['z_score']),
            reverse=True
        )

        return stories[:n]


def main():
    """Run storytelling analysis."""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python storytelling_analyzer.py <outliers.json> [top_n]")
        sys.exit(1)

    outliers_path = sys.argv[1]
    top_n = int(sys.argv[2]) if len(sys.argv) > 2 else 100

    analyzer = StorytellingAnalyzer(outliers_path)

    print(f"\n{'='*80}")
    print(f"STORYTELLING PATTERN ANALYSIS - Top {top_n} Tweets")
    print(f"{'='*80}\n")

    # Extract features
    print("Extracting storytelling features...")
    features = analyzer.extract_storytelling_features(top_n)
    print(f"✓ Extracted {len(features)} storytelling profiles\n")

    # Analyze correlations
    print("="*80)
    print("STORYTELLING CORRELATIONS WITH VIRALITY")
    print("="*80)
    correlations = analyzer.analyze_storytelling_correlations()

    # Sort by significance and correlation strength
    significant = {k: v for k, v in correlations.items() if v['significant']}
    sorted_corrs = sorted(significant.items(), key=lambda x: abs(x[1]['correlation']), reverse=True)

    print(f"\n📊 SIGNIFICANT CORRELATIONS (p < 0.05):")
    print(f"\n{'Feature':<35} {'Correlation':>12} {'P-Value':>12} {'Prevalence/Mean':>15}")
    print("-"*80)
    for feat, data in sorted_corrs:
        if 'prevalence' in data:
            extra = data['prevalence']
        else:
            extra = f"{data['mean']:.3f}"
        print(f"{feat:<35} {data['correlation']:>12.4f} {data['p_value']:>12.4f} {extra:>15}")

    # Compare story vs data
    print("\n" + "="*80)
    print("ANECDOTAL vs DATA-DRIVEN CONTENT")
    print("="*80)
    comparison = analyzer.compare_story_vs_data()

    print(f"\n📈 Content Distribution:")
    for content_type, count in comparison['counts'].items():
        pct = 100 * count / top_n
        print(f"  • {content_type.replace('_', ' ').title()}: {count} ({pct:.1f}%)")

    print(f"\n🎯 Average Z-Scores:")
    for content_type, score in comparison['avg_z_scores'].items():
        print(f"  • {content_type.replace('_', ' ').title()}: {score:.2f}")

    if 'statistical_test' in comparison:
        test = comparison['statistical_test']
        sig = "✓ SIGNIFICANT" if test['significant'] else "✗ Not significant"
        print(f"\n📊 Statistical Test: {test['test']}")
        print(f"  P-value: {test['p_value']:.4f} - {sig}")

    # Top stories
    print("\n" + "="*80)
    print("TOP VIRAL STORIES")
    print("="*80)
    top_stories = analyzer.get_top_stories(5)

    for i, story in enumerate(top_stories, 1):
        print(f"\n{i}. Story Score: {story['storytelling_score']}/7 | Z-Score: {story['z_score']:.2f}")
        print(f"   Author: @{story['author']}")
        print(f"   Features: ", end="")
        features_present = [
            'temporal_seq' if story['has_temporal_sequence'] else None,
            'cause-effect' if story['has_cause_effect'] else None,
            'protagonist' if story['has_protagonist'] else None,
            'emotional_arc' if story['has_emotional_arc'] else None,
            '1st_person' if story['is_first_person'] else None,
            'past_tense' if story['is_past_tense_narrative'] else None,
            'anecdote' if story['has_anecdote'] else None,
        ]
        print(", ".join([f for f in features_present if f]))
        print(f"   Text: {story['text'][:150]}...")

    # Save results
    output_path = outliers_path.replace('.json', '_storytelling_analysis.json')
    with open(output_path, 'w') as f:
        # Convert numpy types to native Python types for JSON serialization
        json_safe_features = []
        for f in features:
            safe_f = {}
            for k, v in f.items():
                if isinstance(v, (np.integer, np.floating)):
                    safe_f[k] = float(v)
                elif isinstance(v, (bool, np.bool_)):
                    safe_f[k] = bool(v)
                else:
                    safe_f[k] = v
            json_safe_features.append(safe_f)

        json.dump({
            'correlations': correlations,
            'story_vs_data_comparison': comparison,
            'top_stories': top_stories[:10],
            'features': json_safe_features
        }, f, indent=2)

    print(f"\n✓ Detailed analysis saved to: {output_path}\n")


if __name__ == "__main__":
    main()
