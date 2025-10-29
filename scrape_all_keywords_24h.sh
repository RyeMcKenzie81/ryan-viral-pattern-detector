#!/bin/bash

# Scrape All Keywords (Last 24 Hours)
# Daily scrape of all 19 keywords with 5-topic taxonomy (V1.6)

# Create output directory
mkdir -p ~/Downloads/keyword_analysis_24h

# All 19 keywords
terms=(
  "device limits"
  "digital parenting"
  "digital wellness"
  "family routines"
  "kids"
  "kids gaming"
  "kids gaming addiction"
  "kids screen time"
  "kids social media"
  "kids technology"
  "mindful parenting"
  "online safety kids"
  "parenting"
  "parenting advice"
  "parenting tips"
  "screen time kids"
  "screen time rules"
  "tech boundaries"
  "toddler behavior"
)

# Track start time
start_time=$(date +%s)

echo "========================================"
echo "Scraping All Keywords (24 Hours)"
echo "========================================"
echo "Total keywords: ${#terms[@]}"
echo "Tweets per keyword: 500"
echo "Time window: 24 hours (1 day)"
echo "Green threshold: 0.50"
echo "Min likes: 0"
echo "Skip comments: Yes (saves scores for later generation)"
echo "Taxonomy: 5 topics (V1.6)"
echo "========================================"
echo ""

# Analyze each term
term_count=0
for term in "${terms[@]}"; do
  term_count=$((term_count + 1))

  echo "========================================"
  echo "[$term_count/${#terms[@]}] Scraping: $term"
  echo "========================================"

  # Convert term to filename (replace spaces with underscores)
  filename=$(echo "$term" | tr ' ' '_')

  # Run analysis (scores only, no comments - saves to DB for later generation)
  source venv/bin/activate && python -m viraltracker.cli.main twitter analyze-search-term \
    --project yakety-pack-instagram \
    --term "$term" \
    --count 500 \
    --days-back 1 \
    --min-likes 0 \
    --skip-comments \
    --report-file ~/Downloads/keyword_analysis_24h/${filename}_report.json

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
minutes=$((duration / 60))

echo ""
echo "========================================"
echo "All scrapes complete!"
echo "========================================"
echo "Results saved to: ~/Downloads/keyword_analysis_24h/"
echo "Total time: ${minutes} minutes"
echo ""

# Show summary
echo "Summary of Results:"
echo "========================================"
printf "%-30s %s\n" "Keyword" "Greens | Total | %"
echo "----------------------------------------"

total_greens=0
total_tweets=0

for term in "${terms[@]}"; do
  filename=$(echo "$term" | tr ' ' '_')
  report_file=~/Downloads/keyword_analysis_24h/${filename}_report.json

  if [ -f "$report_file" ]; then
    # Extract green count using Python
    green_info=$(python3 -c "
import json
with open('$report_file') as f:
    data = json.load(f)
    green_count = data.get('metrics', {}).get('score_distribution', {}).get('green', {}).get('count', 0)
    total = data.get('tweets_analyzed', 0)
    green_pct = (green_count / total * 100) if total > 0 else 0
    print(f'{green_count:3d} | {total:3d} | {green_pct:5.2f}%')
" 2>/dev/null)

    if [ -n "$green_info" ]; then
      printf "%-30s %s\n" "$term" "$green_info"

      # Add to totals
      green_count=$(python3 -c "
import json
with open('$report_file') as f:
    data = json.load(f)
    print(data.get('metrics', {}).get('score_distribution', {}).get('green', {}).get('count', 0))
" 2>/dev/null)

      tweet_count=$(python3 -c "
import json
with open('$report_file') as f:
    print(data.get('tweets_analyzed', 0))
" 2>/dev/null)

      total_greens=$((total_greens + green_count))
      total_tweets=$((total_tweets + tweet_count))
    else
      printf "%-30s Report exists but couldn't parse\n" "$term"
    fi
  else
    printf "%-30s No report generated\n" "$term"
  fi
done

echo "----------------------------------------"
if [ $total_tweets -gt 0 ]; then
  overall_pct=$(python3 -c "print(f'{($total_greens / $total_tweets * 100):.2f}')")
  printf "%-30s %3d | %3d | %5s%%\n" "TOTAL" "$total_greens" "$total_tweets" "$overall_pct"
fi

echo "========================================"
echo ""
echo "Step 2: Generate comments for all greens from last 24 hours"
echo "========================================"

source venv/bin/activate && python -m viraltracker.cli.main twitter generate-comments \
  --project yakety-pack-instagram \
  --hours-back 24 \
  --max-candidates 10000 \
  --min-followers 10 \
  --min-likes 0 \
  --greens-only

echo ""
echo "Step 3: Export greens to CSV"
echo "========================================"

source venv/bin/activate && python -m viraltracker.cli.main twitter export-comments \
  --project yakety-pack-instagram \
  --out ~/Downloads/keyword_greens_24h.csv \
  --status pending \
  --greens-only \
  --sort-by balanced

echo ""
echo "✅ Complete! Greens exported to: ~/Downloads/keyword_greens_24h.csv"
