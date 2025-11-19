#!/bin/bash

# Test New Search Terms (Nov 2025)
# Testing broader/gaming-focused keywords with 0.50 threshold

# Create output directory
mkdir -p ~/Downloads/new_term_tests

# Define new search terms to test
terms=(
  "parenting"
  "kids"
  "kids gaming"
  "kids gaming addiction"
)

# Track start time
start_time=$(date +%s)

echo "========================================"
echo "Testing New Search Terms"
echo "========================================"
echo "Total terms: ${#terms[@]}"
echo "Tweets per term: 500"
echo "Time window: 48 hours (2 days)"
echo "Green threshold: 0.50"
echo "Min likes: 0"
echo "Skip comments: Yes (faster)"
echo "========================================"
echo ""

# Analyze each term
term_count=0
for term in "${terms[@]}"; do
  term_count=$((term_count + 1))

  echo "========================================"
  echo "[$term_count/${#terms[@]}] Testing: $term"
  echo "========================================"

  # Convert term to filename (replace spaces with underscores)
  filename=$(echo "$term" | tr ' ' '_')

  # Run analysis
  source venv/bin/activate && python -m viraltracker.cli.main twitter analyze-search-term \
    --project yakety-pack-instagram \
    --term "$term" \
    --count 500 \
    --days-back 2 \
    --min-likes 0 \
    --skip-comments \
    --report-file ~/Downloads/new_term_tests/${filename}_report.json

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
echo "All tests complete!"
echo "========================================"
echo "Results saved to: ~/Downloads/new_term_tests/"
echo "Total time: ${minutes} minutes"
echo ""

# Show summary
echo "Summary of Results:"
echo "========================================"
for term in "${terms[@]}"; do
  filename=$(echo "$term" | tr ' ' '_')
  report_file=~/Downloads/new_term_tests/${filename}_report.json

  if [ -f "$report_file" ]; then
    # Extract green count and percentage using Python
    green_info=$(python3 -c "
import json
with open('$report_file') as f:
    data = json.load(f)
    green_count = data.get('metrics', {}).get('green_count', 0)
    total = data.get('metrics', {}).get('total_tweets', 0)
    green_pct = (green_count / total * 100) if total > 0 else 0
    print(f'{green_count:3d} greens ({green_pct:5.2f}%) from {total:3d} tweets')
" 2>/dev/null)

    if [ -n "$green_info" ]; then
      printf "%-25s %s\n" "$term:" "$green_info"
    else
      printf "%-25s Report exists but couldn't parse\n" "$term:"
    fi
  else
    printf "%-25s No report generated\n" "$term:"
  fi
done

echo "========================================"
