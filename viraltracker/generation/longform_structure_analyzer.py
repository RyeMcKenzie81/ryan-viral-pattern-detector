"""
Long-Form Tweet Structure Analyzer

Identifies structural components in long-form tweets (60+ words)
and correlates them with virality.
"""

import json
import re
import sys
from typing import List, Dict, Any
import numpy as np
from scipy.stats import spearmanr


class LongFormStructureAnalyzer:
    """Analyzes structural patterns in long-form viral tweets."""

    def __init__(self, outliers_path: str):
        """Initialize with path to outliers JSON."""
        with open(outliers_path, 'r') as f:
            data = json.load(f)

        # Filter to long-form only (60+ words)
        self.all_outliers = data['outliers']
        self.longform_tweets = [
            t for t in data['outliers']
            if len(t['text'].split()) >= 60
        ]

        print(f"Analyzing {len(self.longform_tweets)} long-form tweets (60+ words)")

    def detect_structure(self, text: str) -> Dict[str, Any]:
        """Detect structural components in a tweet."""
        lines = text.split('\n')
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
        sentences = re.split(r'[.!?]+', text)
        sentences = [s.strip() for s in sentences if s.strip()]

        structure = {
            # Opening analysis
            'opening_type': self._detect_opening(text),
            'has_greeting': bool(re.search(r'^(GM|Good morning|Hello|Hey|Hi)\b', text, re.I)),
            'starts_with_mention': text.strip().startswith('@'),
            'starts_with_question': sentences[0].strip().endswith('?') if sentences else False,
            'starts_with_bold_claim': self._is_bold_claim(sentences[0]) if sentences else False,

            # Body structure
            'paragraph_count': len(paragraphs),
            'line_break_count': text.count('\n'),
            'has_bullets': self._has_bullet_structure(text),
            'has_numbered_list': bool(re.search(r'^\d+[.)]', text, re.M)),
            'has_section_headers': self._has_section_headers(text),

            # Content type
            'is_thread_like': len(paragraphs) >= 3 and self._is_thread_like(paragraphs),
            'is_story': self._is_story(text),
            'is_argument': self._is_argument(text),
            'is_informative': self._is_informative(text),
            'is_promotional': self._is_promotional(text),
            'is_personal_vent': self._is_personal_vent(text),

            # Specific elements
            'has_event_details': bool(re.search(r'(date|time|join|register|rsvp|sunday|monday|tuesday|wednesday|thursday|friday|saturday)', text, re.I)),
            'has_controversy': self._has_controversy(text),
            'has_personal_anecdote': bool(re.search(r'\b(my |I |me |when I|I\'m|I\'ve)\b', text, re.I)),
            'has_data_evidence': bool(re.search(r'(study|research|data|survey|\d+%|statistics|report|found that)', text, re.I)),
            'has_specifics': bool(re.search(r'(\d{1,2}:\d{2}|@\w+|https?://|\d{4})', text)),

            # Formatting
            'uses_emoji_bullets': bool(re.search(r'^[🎙️📊🗓️🕗💡🔥✓✅⚠️❌]', text, re.M)),
            'has_emphasis': bool(re.search(r'[A-Z]{3,}|_\w+_|\*\w+\*', text)),

            # Closing
            'ends_with_question': sentences[-1].strip().endswith('?') if sentences else False,
            'ends_with_cta': self._has_cta_ending(text),
            'ends_with_statement': not (sentences[-1].strip().endswith('?') or sentences[-1].strip().endswith('!')) if sentences else False,
        }

        return structure

    def _detect_opening(self, text: str) -> str:
        """Detect primary opening type."""
        first_30 = text[:100].lower()

        if text.strip().startswith('@'):
            return 'reply/mention'
        elif re.search(r'^(gm|good morning|hello|hey)', first_30):
            return 'greeting'
        elif '?' in text.split('\n')[0] if '\n' in text else text[:100]:
            return 'question'
        elif re.search(r'(breaking|urgent|warning|alert)', first_30):
            return 'urgent_claim'
        elif any(word in first_30 for word in ['not just', 'are not', 'every', 'all']):
            return 'bold_claim'
        else:
            return 'statement'

    def _is_bold_claim(self, sentence: str) -> bool:
        """Check if sentence is a bold/strong claim."""
        bold_patterns = [
            r'\bnot just\b',
            r'\bevery\b.*\b(is|are|has)\b',
            r'\ball\b.*\b(is|are|has)\b',
            r'\bno one\b',
            r'\bnever\b',
            r'\balways\b'
        ]
        return any(re.search(pattern, sentence, re.I) for pattern in bold_patterns)

    def _has_bullet_structure(self, text: str) -> bool:
        """Check for bullet-point structure."""
        patterns = [
            r'^[-•*]\s',  # Traditional bullets
            r'^[🎙️📊🗓️🕗💡🔥✓✅⚠️❌]\s',  # Emoji bullets
            r'^\d+[.):]\s',  # Numbered
        ]
        bullet_count = sum(1 for line in text.split('\n') if any(re.match(p, line.strip()) for p in patterns))
        return bullet_count >= 2

    def _has_section_headers(self, text: str) -> bool:
        """Check for section headers (Title: or - Title)."""
        return bool(re.search(r'^([-•]\s)?[A-Z][a-z]+(\s[A-Z][a-z]+)*:', text, re.M))

    def _is_thread_like(self, paragraphs: List[str]) -> bool:
        """Check if structure is thread-like (multiple distinct points)."""
        if len(paragraphs) < 3:
            return False
        # Thread-like if paragraphs are roughly balanced in length
        lengths = [len(p) for p in paragraphs]
        avg_len = np.mean(lengths)
        return all(l > avg_len * 0.3 for l in lengths)  # No paragraph too short

    def _is_story(self, text: str) -> bool:
        """Check for narrative/story elements."""
        story_markers = [
            r'\b(when |then |after |before |finally |suddenly )\b',
            r'\b(I remember|I was|we were|my |our )\b',
            r'\b(told |said |asked |replied )\b'
        ]
        return sum(1 for pattern in story_markers if re.search(pattern, text, re.I)) >= 2

    def _is_argument(self, text: str) -> bool:
        """Check for argumentative structure."""
        arg_markers = [
            r'\b(but |however |although |despite |yet |while )\b',
            r'\b(because |since |therefore |thus |hence )\b',
            r'\b(first |second |third |finally )\b',
            r'\b(not |no |never |don\'t |doesn\'t )\b'
        ]
        return sum(1 for pattern in arg_markers if re.search(pattern, text, re.I)) >= 2

    def _is_informative(self, text: str) -> bool:
        """Check for informative/educational content."""
        info_markers = [
            r'\b(study |research |data |survey |report |found |according )\b',
            r'\b(topic|date|time|speaker|guest|host)\b',
            r'\d+%|\d+ (people|users|children|parents)',
            r'(platform|system|program|service|tool)'
        ]
        return sum(1 for pattern in info_markers if re.search(pattern, text, re.I)) >= 2

    def _is_promotional(self, text: str) -> bool:
        """Check for promotional content."""
        promo_markers = [
            r'\b(join |register |rsvp |don\'t miss |check out |visit |follow )\b',
            r'@\w+',  # Mentions
            r'https?://',
            r'\b(new |exciting |exclusive |special |limited )\b'
        ]
        return sum(1 for pattern in promo_markers if re.search(pattern, text, re.I)) >= 2

    def _is_personal_vent(self, text: str) -> bool:
        """Check for personal venting/complaint."""
        vent_markers = [
            r'\b(I\'m|I am|I\'ve|I have)\s+(aware|sick|tired|done|frustrated)\b',
            r'\b(they |their |them ).*(don\'t|doesn\'t|won\'t|can\'t|refuse)\b',
            r'\b(unfair|unjust|wrong|bullied|targeted|attacked)\b',
            r'\ball I want\b'
        ]
        return sum(1 for pattern in vent_markers if re.search(pattern, text, re.I)) >= 2

    def _has_controversy(self, text: str) -> bool:
        """Check for controversial/outrage content."""
        controversy_markers = [
            r'\b(suicide|murder|kill|death|abuse|violence)\b',
            r'\b(corrupt|fake|lie|fraud|scam|cheat)\b',
            r'\b(racist|sexist|discrimination|injustice)\b',
            r'\b(outrage|scandal|shocking|disturbing)\b',
            r'!'
        ]
        return sum(1 for pattern in controversy_markers if re.search(pattern, text, re.I)) >= 1

    def _has_cta_ending(self, text: str) -> bool:
        """Check if ending has a call-to-action."""
        last_100 = text[-100:].lower()
        cta_patterns = [
            r'\b(join|register|follow|subscribe|click|visit|check|share|retweet|comment)\b',
            r'\b(don\'t miss|limited time|act now|today only)\b',
            r'https?://',
            r'@\w+'
        ]
        return any(re.search(pattern, last_100) for pattern in cta_patterns)

    def analyze_structures(self) -> Dict[str, Any]:
        """Analyze all long-form tweets and find correlations."""
        results = []

        for tweet in self.longform_tweets:
            structure = self.detect_structure(tweet['text'])
            structure.update({
                'z_score': tweet['outlier_metrics']['z_score'],
                'word_count': len(tweet['text'].split()),
                'views': tweet['metrics']['views'],
                'text': tweet['text']
            })
            results.append(structure)

        # Calculate correlations
        correlations = {}
        z_scores = np.array([r['z_score'] for r in results])

        # Test each structural feature
        for key in results[0].keys():
            if key in ['z_score', 'word_count', 'views', 'text', 'opening_type']:
                continue

            values = np.array([int(r[key]) if isinstance(r[key], bool) else r[key] for r in results])

            if np.std(values) > 0 and len(set(values)) > 1:
                corr, p_value = spearmanr(values, z_scores)
                correlations[key] = {
                    'correlation': float(corr),
                    'p_value': float(p_value),
                    'prevalence': float(np.mean(values) * 100),
                    'significant': p_value < 0.05
                }

        return {
            'sample_size': len(results),
            'correlations': correlations,
            'structures': results
        }

    def print_analysis(self, analysis: Dict):
        """Print structure analysis results."""
        print(f"\n{'='*80}")
        print(f"LONG-FORM STRUCTURE ANALYSIS ({analysis['sample_size']} tweets)")
        print(f"{'='*80}\n")

        # Sort by correlation strength
        corr_items = [(k, v) for k, v in analysis['correlations'].items()]
        corr_items.sort(key=lambda x: abs(x[1]['correlation']), reverse=True)

        print("STRUCTURAL PATTERNS & CORRELATIONS:")
        print(f"{'Feature':<30} {'Prevalence':>12} {'Correlation':>12} {'p-value':>12}")
        print("-" * 80)

        for feature, data in corr_items:
            sig = "✓" if data['significant'] else "✗"
            direction = "+" if data['correlation'] > 0 else "-"
            feature_name = feature.replace('_', ' ').title()

            print(f"{sig} {feature_name:<28} {data['prevalence']:>10.1f}% {direction}{abs(data['correlation']):>10.3f} {data['p_value']:>12.6f}")


def main():
    """Run long-form structure analysis."""
    if len(sys.argv) < 2:
        print("Usage: python longform_structure_analyzer.py <outliers.json>")
        sys.exit(1)

    outliers_path = sys.argv[1]

    analyzer = LongFormStructureAnalyzer(outliers_path)
    analysis = analyzer.analyze_structures()
    analyzer.print_analysis(analysis)

    # Save detailed results
    output_path = outliers_path.replace('.json', '_longform_structure_analysis.json')

    # Remove 'text' field for cleaner output
    for s in analysis['structures']:
        s.pop('text', None)

    with open(output_path, 'w') as f:
        json.dump(analysis, f, indent=2)

    print(f"\n✓ Detailed results saved to: {output_path}\n")


if __name__ == "__main__":
    main()
