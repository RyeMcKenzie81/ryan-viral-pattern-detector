# Search Term Analyzer Tool - Implementation Plan 🔍

**Purpose**: Reusable tool to analyze which Twitter search terms yield the best engagement opportunities for any project.

**Target Metrics per Search Term:**
1. **Green Ratio**: % of tweets scoring ≥ 0.55 (out of 1000)
2. **Freshness**: % of tweets posted in last 48 hours (volume indicator)
3. **Virality**: Average/median views per tweet
4. **Cost Efficiency**: Cost per green tweet found
5. **Topic Distribution**: Which taxonomy topics matched

---

## 🎯 Requirements

### Input
- Project slug (e.g., "yakety-pack-instagram")
- Search term to test (e.g., "screen time kids")
- Number of tweets to analyze (default: 1000)
- Filters: min_likes, days_back

### Output
- Comprehensive report with all metrics
- CSV export with full tweet data
- Recommendation: "Good", "Okay", or "Poor" term

### Constraints
- Apify requires minimum 50 tweets per search
- Twitter search can go back max 7-14 days typically
- Cost: ~$0.10 per 1000 tweets analyzed

---

## 🏗️ Architecture

### Component 1: CLI Command
**Location**: `viraltracker/cli/twitter.py`

```bash
# Usage
./vt twitter analyze-search-term \
  --project yakety-pack-instagram \
  --term "screen time kids" \
  --count 1000 \
  --min-likes 10 \
  --days-back 7 \
  --report-file ~/Downloads/analysis_report.json
```

**Flags:**
- `--project` (required): Project slug
- `--term` (required): Search term to analyze
- `--count` (default: 1000): Tweets to analyze
- `--min-likes` (default: 10): Minimum likes filter
- `--days-back` (default: 7): Time window
- `--report-file` (optional): Output JSON report path
- `--batch-size` (default: 10): Comment generation batch size

### Component 2: Analyzer Module
**Location**: `viraltracker/analysis/search_term_analyzer.py` (NEW)

**Class**: `SearchTermAnalyzer`

**Methods:**
1. `scrape_tweets(term, count, filters)` - Scrape tweets via existing search
2. `generate_comments(tweets, batch_size)` - Generate comments for all tweets
3. `analyze_scores()` - Calculate green/yellow/red ratios
4. `analyze_freshness()` - Calculate % in last 48h
5. `analyze_virality()` - Calculate view statistics
6. `analyze_topics()` - Topic distribution
7. `calculate_cost_efficiency()` - Cost per green tweet
8. `generate_report()` - Compile all metrics into report
9. `export_results(format)` - Export to JSON/CSV

### Component 3: Report Format
**JSON Structure:**

```json
{
  "project": "yakety-pack-instagram",
  "search_term": "screen time kids",
  "analyzed_at": "2025-10-23T12:00:00Z",
  "tweets_analyzed": 1000,
  "metrics": {
    "score_distribution": {
      "green": {
        "count": 180,
        "percentage": 18.0,
        "avg_score": 0.62
      },
      "yellow": {
        "count": 620,
        "percentage": 62.0,
        "avg_score": 0.48
      },
      "red": {
        "count": 200,
        "percentage": 20.0,
        "avg_score": 0.32
      }
    },
    "freshness": {
      "last_48h_count": 450,
      "last_48h_percentage": 45.0,
      "conversations_per_day": 225
    },
    "virality": {
      "avg_views": 12500,
      "median_views": 3200,
      "top_10_percent_avg_views": 85000,
      "tweets_with_10k_plus_views": 120
    },
    "topic_distribution": {
      "screen time management": 650,
      "parenting tips": 280,
      "digital wellness": 70
    },
    "cost_efficiency": {
      "total_cost_usd": 0.10,
      "cost_per_green_tweet": 0.00056,
      "greens_per_dollar": 1800
    }
  },
  "recommendation": {
    "rating": "Good",
    "confidence": "High",
    "reasoning": "18% green ratio exceeds 10% target. High freshness (45% in 48h) indicates active conversation. Good virality potential."
  }
}
```

**CSV Export:**
All tweet data with scores, labels, topics for manual review.

---

## 🔨 Implementation Steps

### Phase 1: Core Analyzer Module (60 min)
**File**: `viraltracker/analysis/search_term_analyzer.py`

```python
"""
Search Term Analyzer - Find optimal Twitter search terms

Analyzes search terms across multiple dimensions:
- Score quality (green/yellow/red ratio)
- Conversation volume (freshness)
- Virality potential (views)
- Cost efficiency
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import statistics

@dataclass
class SearchTermMetrics:
    """Metrics for a search term analysis"""
    project: str
    search_term: str
    tweets_analyzed: int
    green_count: int
    green_percentage: float
    yellow_count: int
    yellow_percentage: float
    red_count: int
    red_percentage: float
    avg_score: float
    last_48h_count: int
    last_48h_percentage: float
    avg_views: float
    median_views: float
    total_cost_usd: float
    cost_per_green: float
    topic_distribution: Dict[str, int]
    recommendation: str
    reasoning: str

class SearchTermAnalyzer:
    """Analyze Twitter search terms for engagement potential"""

    def __init__(self, project_slug: str):
        self.project_slug = project_slug
        self.db = get_supabase_client()

    def analyze(
        self,
        search_term: str,
        count: int = 1000,
        min_likes: int = 10,
        days_back: int = 7,
        batch_size: int = 10
    ) -> SearchTermMetrics:
        """
        Run complete analysis on a search term

        Steps:
        1. Scrape tweets
        2. Generate comments (scores)
        3. Analyze metrics
        4. Generate recommendation
        """

        # 1. Scrape tweets
        tweets = self._scrape_tweets(search_term, count, min_likes, days_back)

        # 2. Generate comments to get scores
        results = self._generate_comments(tweets, batch_size)

        # 3. Analyze all metrics
        metrics = self._calculate_metrics(search_term, results, tweets)

        # 4. Generate recommendation
        metrics = self._add_recommendation(metrics)

        return metrics

    def _scrape_tweets(self, term, count, min_likes, days_back):
        """Scrape tweets using existing search functionality"""
        # Call existing search command or logic
        pass

    def _generate_comments(self, tweets, batch_size):
        """Generate comments to score tweets"""
        # Use existing comment generator
        pass

    def _calculate_metrics(self, term, results, tweets) -> SearchTermMetrics:
        """Calculate all metrics from results"""

        # Score distribution
        green = [r for r in results if r.score >= 0.55]
        yellow = [r for r in results if 0.4 <= r.score < 0.55]
        red = [r for r in results if r.score < 0.4]

        # Freshness (last 48h)
        cutoff = datetime.now() - timedelta(hours=48)
        recent = [t for t in tweets if t.posted_at >= cutoff]

        # Virality (views)
        views = [t.views for t in tweets if t.views > 0]

        # Topic distribution
        topics = {}
        for r in results:
            topics[r.topic] = topics.get(r.topic, 0) + 1

        # Cost
        total_cost = len(tweets) * 0.0001  # $0.0001 per tweet

        return SearchTermMetrics(
            project=self.project_slug,
            search_term=term,
            tweets_analyzed=len(results),
            green_count=len(green),
            green_percentage=len(green) / len(results) * 100,
            yellow_count=len(yellow),
            yellow_percentage=len(yellow) / len(results) * 100,
            red_count=len(red),
            red_percentage=len(red) / len(results) * 100,
            avg_score=statistics.mean([r.score for r in results]),
            last_48h_count=len(recent),
            last_48h_percentage=len(recent) / len(tweets) * 100,
            avg_views=statistics.mean(views) if views else 0,
            median_views=statistics.median(views) if views else 0,
            total_cost_usd=total_cost,
            cost_per_green=total_cost / len(green) if green else 0,
            topic_distribution=topics,
            recommendation="",  # Set in _add_recommendation
            reasoning=""
        )

    def _add_recommendation(self, metrics: SearchTermMetrics) -> SearchTermMetrics:
        """Add recommendation based on thresholds"""

        # Scoring criteria
        green_good = metrics.green_percentage >= 15
        green_okay = metrics.green_percentage >= 8
        freshness_good = metrics.last_48h_percentage >= 30
        views_good = metrics.avg_views >= 5000

        if green_good and freshness_good:
            metrics.recommendation = "Excellent"
            metrics.reasoning = f"{metrics.green_percentage:.1f}% green (target: 15%+). High volume ({metrics.last_48h_percentage:.1f}% in 48h). Use this term regularly."
        elif green_okay and freshness_good:
            metrics.recommendation = "Good"
            metrics.reasoning = f"{metrics.green_percentage:.1f}% green (target: 8%+). Active conversation. Consider using."
        elif green_okay:
            metrics.recommendation = "Okay"
            metrics.reasoning = f"{metrics.green_percentage:.1f}% green but low volume ({metrics.last_48h_percentage:.1f}% in 48h). Use occasionally."
        else:
            metrics.recommendation = "Poor"
            metrics.reasoning = f"Only {metrics.green_percentage:.1f}% green (target: 8%+). Consider other terms."

        return metrics

    def export_json(self, metrics: SearchTermMetrics, filepath: str):
        """Export metrics to JSON"""
        import json
        with open(filepath, 'w') as f:
            json.dump(metrics.__dict__, f, indent=2, default=str)

    def export_csv(self, tweets_with_scores, filepath: str):
        """Export full tweet data to CSV for review"""
        # Similar to existing export-comments but with search term metadata
        pass
```

### Phase 2: CLI Integration (30 min)
**File**: `viraltracker/cli/twitter.py`

Add new command:

```python
@twitter_group.command(name="analyze-search-term")
@click.option('--project', '-p', required=True, help='Project slug')
@click.option('--term', required=True, help='Search term to analyze')
@click.option('--count', default=1000, type=int, help='Tweets to analyze (default: 1000)')
@click.option('--min-likes', default=10, type=int, help='Minimum likes (default: 10)')
@click.option('--days-back', default=7, type=int, help='Days to look back (default: 7)')
@click.option('--batch-size', default=10, type=int, help='Comment generation batch size (default: 10)')
@click.option('--report-file', help='Output JSON report path (optional)')
@click.option('--export-csv', help='Export full data to CSV (optional)')
def analyze_search_term(
    project: str,
    term: str,
    count: int,
    min_likes: int,
    days_back: int,
    batch_size: int,
    report_file: Optional[str],
    export_csv: Optional[str]
):
    """
    Analyze a search term to find engagement opportunities

    Tests a search term by scraping tweets, scoring them, and analyzing
    multiple dimensions: quality (green ratio), volume (freshness),
    virality (views), and cost efficiency.

    Use this to find the best search terms for your project before
    committing to regular scraping.

    Examples:
        # Quick test
        vt twitter analyze-search-term -p my-project --term "screen time kids"

        # Full analysis with 1000 tweets
        vt twitter analyze-search-term -p my-project --term "parenting tips" \\
          --count 1000 --min-likes 20 --report-file ~/Downloads/report.json

        # Export full data
        vt twitter analyze-search-term -p my-project --term "digital wellness" \\
          --export-csv ~/Downloads/full_data.csv
    """

    from ..analysis.search_term_analyzer import SearchTermAnalyzer

    click.echo(f"\n{'='*60}")
    click.echo(f"🔍 Search Term Analysis")
    click.echo(f"{'='*60}\n")

    click.echo(f"Project: {project}")
    click.echo(f"Search term: \"{term}\"")
    click.echo(f"Analyzing {count} tweets...")
    click.echo()

    # Run analysis
    analyzer = SearchTermAnalyzer(project)

    with click.progressbar(length=100, label='Analyzing') as bar:
        # This would be more sophisticated with real progress tracking
        metrics = analyzer.analyze(term, count, min_likes, days_back, batch_size)
        bar.update(100)

    # Display results
    click.echo(f"\n{'='*60}")
    click.echo(f"📊 Analysis Results")
    click.echo(f"{'='*60}\n")

    click.echo(f"Tweets analyzed: {metrics.tweets_analyzed}")
    click.echo()

    click.echo(f"Score Distribution:")
    click.echo(f"  🟢 Green:  {metrics.green_count:4d} ({metrics.green_percentage:5.1f}%)")
    click.echo(f"  🟡 Yellow: {metrics.yellow_count:4d} ({metrics.yellow_percentage:5.1f}%)")
    click.echo(f"  🔴 Red:    {metrics.red_count:4d} ({metrics.red_percentage:5.1f}%)")
    click.echo()

    click.echo(f"Freshness:")
    click.echo(f"  Last 48h: {metrics.last_48h_count} ({metrics.last_48h_percentage:.1f}%)")
    click.echo(f"  ~{metrics.last_48h_count / 2:.0f} tweets/day")
    click.echo()

    click.echo(f"Virality:")
    click.echo(f"  Avg views:    {metrics.avg_views:,.0f}")
    click.echo(f"  Median views: {metrics.median_views:,.0f}")
    click.echo()

    click.echo(f"Cost Efficiency:")
    click.echo(f"  Total cost:        ${metrics.total_cost_usd:.3f}")
    click.echo(f"  Cost per green:    ${metrics.cost_per_green:.5f}")
    click.echo(f"  Greens per dollar: {1/metrics.cost_per_green:.0f}")
    click.echo()

    click.echo(f"{'='*60}")
    click.echo(f"💡 Recommendation: {metrics.recommendation}")
    click.echo(f"{'='*60}")
    click.echo(f"{metrics.reasoning}")
    click.echo()

    # Export if requested
    if report_file:
        analyzer.export_json(metrics, report_file)
        click.echo(f"✅ Report saved to: {report_file}")

    if export_csv:
        analyzer.export_csv(metrics, export_csv)
        click.echo(f"✅ Data exported to: {export_csv}")
```

### Phase 3: Batch Analysis Tool (30 min)
**File**: `viraltracker/cli/twitter.py`

Add batch command:

```python
@twitter_group.command(name="batch-analyze-terms")
@click.option('--project', '-p', required=True, help='Project slug')
@click.option('--terms-file', required=True, help='File with search terms (one per line)')
@click.option('--count', default=1000, type=int, help='Tweets per term (default: 1000)')
@click.option('--output-dir', required=True, help='Directory for reports')
def batch_analyze_terms(
    project: str,
    terms_file: str,
    count: int,
    output_dir: str
):
    """
    Analyze multiple search terms and generate comparison report

    Examples:
        # Create terms file
        echo "screen time kids\\nparenting tips\\ndigital wellness" > terms.txt

        # Run batch analysis
        vt twitter batch-analyze-terms -p my-project \\
          --terms-file terms.txt \\
          --output-dir ~/Downloads/analysis/
    """

    # Read terms
    with open(terms_file, 'r') as f:
        terms = [line.strip() for line in f if line.strip()]

    click.echo(f"Analyzing {len(terms)} search terms...")

    analyzer = SearchTermAnalyzer(project)
    results = []

    for i, term in enumerate(terms, 1):
        click.echo(f"\n[{i}/{len(terms)}] Analyzing: {term}")
        metrics = analyzer.analyze(term, count)
        results.append(metrics)

        # Save individual report
        report_path = f"{output_dir}/{term.replace(' ', '_')}_report.json"
        analyzer.export_json(metrics, report_path)

    # Generate comparison report
    comparison = _generate_comparison_report(results)
    comparison_path = f"{output_dir}/comparison_report.json"

    with open(comparison_path, 'w') as f:
        json.dump(comparison, f, indent=2)

    click.echo(f"\n✅ Analysis complete!")
    click.echo(f"📊 Comparison report: {comparison_path}")
```

---

## 📋 Usage Workflow

### Single Term Analysis
```bash
# Test one term
./vt twitter analyze-search-term \
  --project yakety-pack-instagram \
  --term "screen time kids" \
  --count 1000 \
  --min-likes 20 \
  --report-file ~/Downloads/screen_time_analysis.json \
  --export-csv ~/Downloads/screen_time_data.csv
```

### Batch Analysis (All Terms)
```bash
# Create terms file
cat > search_terms.txt << EOF
screen time kids
parenting tips
digital wellness
toddler behavior
device limits
screen time rules
family routines
kids social media
online safety kids
tech boundaries
EOF

# Run batch analysis
./vt twitter batch-analyze-terms \
  --project yakety-pack-instagram \
  --terms-file search_terms.txt \
  --count 1000 \
  --output-dir ~/Downloads/term_analysis/

# Review comparison report
cat ~/Downloads/term_analysis/comparison_report.json
```

---

## 🎯 Success Criteria

**"Excellent" Term:**
- ✅ Green ratio ≥ 15%
- ✅ Freshness ≥ 30% in last 48h
- ✅ Average score ≥ 0.50

**"Good" Term:**
- ✅ Green ratio ≥ 8%
- ✅ Freshness ≥ 20% in last 48h
- ✅ Average score ≥ 0.45

**"Okay" Term:**
- Green ratio ≥ 5%
- May use occasionally

**"Poor" Term:**
- Green ratio < 5%
- Avoid

---

## 💰 Cost Estimation

**Per Term (1000 tweets):**
- Scrape: Minimal Apify cost (~$0.01)
- Generate: 1000 × $0.0001 = $0.10
- **Total: ~$0.11 per term**

**Batch Analysis (10 terms):**
- Total: ~$1.10
- Very affordable for comprehensive insights!

---

## 📁 File Structure

```
viraltracker/
├── analysis/
│   ├── __init__.py (NEW)
│   └── search_term_analyzer.py (NEW)
├── cli/
│   └── twitter.py (MODIFIED - add 2 new commands)
└── SEARCH_TERM_ANALYZER_PLAN.md (this file)
```

---

## ⏭️ Implementation Priority

**Must Have (MVP):**
1. ✅ Core SearchTermAnalyzer class
2. ✅ Single term analysis CLI command
3. ✅ JSON report export
4. ✅ Score distribution metrics
5. ✅ Freshness metrics
6. ✅ Virality metrics

**Nice to Have (V2):**
1. Batch analysis command
2. Comparison report generation
3. CSV export with full data
4. Progress tracking during analysis
5. Database caching of analysis results

**Future Enhancements (V3):**
1. Web dashboard for results
2. Automated term suggestion based on taxonomy
3. Historical trend tracking
4. A/B testing framework
5. Integration with scheduling/automation

---

## 🚀 Next Session: Implementation Checklist

1. Create `viraltracker/analysis/` directory
2. Implement `SearchTermAnalyzer` class
3. Add `analyze-search-term` CLI command
4. Test with "screen time kids" (1000 tweets)
5. Review results and tune thresholds
6. Document findings
7. (Optional) Implement batch analysis command

---

**Estimated Implementation Time**: 2-3 hours
**Testing Time**: 1 hour (run on 3-5 terms)
**Total**: 3-4 hours to fully functional tool

**Status**: Plan complete, ready for implementation
**Created**: 2025-10-23
