#!/bin/bash

# Batch Search Term Analysis Script V3 - WITH TRACKING
# Tests 15 search terms with full run tracking via analysis_runs table
# New features: analysis_run_id, apify_run_id, apify_dataset_id, tweets_per_24h, relevance_only

# Create output directory
mkdir -p ~/Downloads/term_analysis_v3

# Define search terms (in priority order)
terms=(
  "screen time kids"
  "parenting tips"
  "digital wellness"
  "kids screen time"
  "parenting advice"
  "toddler behavior"
  "device limits"
  "screen time rules"
  "family routines"
  "digital parenting"
  "kids social media"
  "online safety kids"
  "tech boundaries"
  "kids technology"
  "mindful parenting"
)

# Track start time
start_time=$(date +%s)

echo "========================================"
echo "Starting Batch Search Term Analysis V3"
echo "========================================"
echo "NEW: Full run tracking with analysis_runs table"
echo "NEW: Enhanced metrics (tweets_per_24h, relevance_only)"
echo "Total terms to test: ${#terms[@]}"
echo "Tweets per term: up to 1000 (actual varies)"
echo "Min likes: 0 (analyzing full volume)"
echo "Estimated time: 50-60 minutes"
echo "Estimated cost: $0.00 (skip-comments mode)"
echo "========================================"
echo ""

# Analyze each term
term_count=0
for term in "${terms[@]}"; do
  term_count=$((term_count + 1))

  echo "========================================"
  echo "[$term_count/${#terms[@]}] Analyzing: $term"
  echo "========================================"

  # Convert term to filename (replace spaces with underscores)
  filename=$(echo "$term" | tr ' ' '_')

  # Run analysis with tracking
  source venv/bin/activate && python -m viraltracker.cli.main twitter analyze-search-term \
    --project yakety-pack-instagram \
    --term "$term" \
    --count 1000 \
    --min-likes 0 \
    --skip-comments \
    --report-file ~/Downloads/term_analysis_v3/${filename}_analysis.json

  # Check if command was successful
  if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Completed: $term"
    echo ""
  else
    echo ""
    echo "❌ Failed: $term"
    echo ""
  fi

  # Wait 2 minutes between searches (rate limiting)
  # Skip wait on last term
  if [ $term_count -lt ${#terms[@]} ]; then
    echo "Waiting 2 minutes before next search..."
    sleep 120
  fi
done

# Calculate total time
end_time=$(date +%s)
duration=$((end_time - start_time))
hours=$((duration / 3600))
minutes=$(((duration % 3600) / 60))

echo ""
echo "========================================"
echo "Batch analysis V3 complete!"
echo "========================================"
echo "Results saved to: ~/Downloads/term_analysis_v3/"
echo "Total time: ${hours}h ${minutes}m"
echo "========================================"
echo ""
echo "NEW FEATURES IN V3:"
echo "✓ Full run tracking (analysis_run_id in database)"
echo "✓ Apify run/dataset IDs captured"
echo "✓ tweets_per_24h metric (more accurate)"
echo "✓ relevance_only semantic similarity scores"
echo "✓ All runs queryable via analysis_runs table"
echo "========================================"
