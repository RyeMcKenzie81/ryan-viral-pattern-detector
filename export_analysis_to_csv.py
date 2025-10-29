#!/usr/bin/env python3
"""
Export search term analysis results to CSV
"""
import json
import csv
from pathlib import Path

# Input directory with JSON files
input_dir = Path.home() / "Downloads" / "term_analysis_v3"
output_file = Path.home() / "Downloads" / "search_term_analysis_v3.csv"

# Collect all results
results = []

for json_file in sorted(input_dir.glob("*_analysis.json")):
    with open(json_file) as f:
        data = json.load(f)

    metrics = data["metrics"]
    tracking = data["tracking"]

    result = {
        "search_term": data["search_term"],
        "analyzed_at": data["analyzed_at"],
        "tweets_analyzed": data["tweets_analyzed"],

        # Tracking
        "analysis_run_id": tracking["analysis_run_id"],
        "apify_run_id": tracking["apify_run_id"],
        "apify_dataset_id": tracking["apify_dataset_id"],

        # Score distribution
        "green_count": metrics["score_distribution"]["green"]["count"],
        "green_percentage": metrics["score_distribution"]["green"]["percentage"],
        "green_avg_score": metrics["score_distribution"]["green"]["avg_score"],
        "yellow_count": metrics["score_distribution"]["yellow"]["count"],
        "yellow_percentage": metrics["score_distribution"]["yellow"]["percentage"],
        "yellow_avg_score": metrics["score_distribution"]["yellow"]["avg_score"],
        "red_count": metrics["score_distribution"]["red"]["count"],
        "red_percentage": metrics["score_distribution"]["red"]["percentage"],
        "red_avg_score": metrics["score_distribution"]["red"]["avg_score"],

        # Freshness
        "last_48h_count": metrics["freshness"]["last_48h_count"],
        "last_48h_percentage": metrics["freshness"]["last_48h_percentage"],
        "conversations_per_day": metrics["freshness"]["conversations_per_day"],
        "tweets_per_24h": metrics["freshness"]["tweets_per_24h"],

        # Virality
        "avg_views": metrics["virality"]["avg_views"],
        "median_views": metrics["virality"]["median_views"],
        "top_10_percent_avg_views": metrics["virality"]["top_10_percent_avg_views"],
        "tweets_with_10k_plus_views": metrics["virality"]["tweets_with_10k_plus_views"],

        # Relevance-only scores
        "avg_relevance_score": metrics["relevance_only"]["avg_relevance_score"],
        "green_avg_relevance": metrics["relevance_only"]["green_avg_relevance"],
        "yellow_avg_relevance": metrics["relevance_only"]["yellow_avg_relevance"],
        "red_avg_relevance": metrics["relevance_only"]["red_avg_relevance"],

        # Top topics
        "top_topic": max(metrics["topic_distribution"].items(), key=lambda x: x[1])[0],
        "top_topic_count": max(metrics["topic_distribution"].values()),

        # Cost
        "total_cost_usd": metrics["cost_efficiency"]["total_cost_usd"],
        "cost_per_green": metrics["cost_efficiency"]["cost_per_green_tweet"],

        # Recommendation
        "recommendation": data["recommendation"]["rating"],
        "confidence": data["recommendation"]["confidence"],
        "reasoning": data["recommendation"]["reasoning"],
    }

    results.append(result)

# Write CSV
with open(output_file, 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=results[0].keys())
    writer.writeheader()
    writer.writerows(results)

print(f"✅ Exported {len(results)} results to: {output_file}")
print(f"\nColumns: {', '.join(results[0].keys())}")
