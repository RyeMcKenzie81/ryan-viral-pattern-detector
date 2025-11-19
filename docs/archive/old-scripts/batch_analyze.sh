#!/bin/bash

# Batch Search Term Analysis Script
# Tests 15 search terms for yakety-pack-instagram project

# Create output directory
mkdir -p ~/Downloads/term_analysis

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
echo "Starting Batch Search Term Analysis"
echo "========================================"
echo "Total terms to test: ${#terms[@]}"
echo "Tweets per term: 1000"
echo "Min likes: None (analyzing full volume)"
echo "Estimated time: 5-6 hours"
echo "Estimated cost: ~$1.65"
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

  # Run analysis
  source venv/bin/activate && ./vt twitter analyze-search-term \
    --project yakety-pack-instagram \
    --term "$term" \
    --count 1000 \
    --min-likes 0 \
    --skip-comments \
    --report-file ~/Downloads/term_analysis/${filename}_analysis.json

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
echo "Batch analysis complete!"
echo "========================================"
echo "Results saved to: ~/Downloads/term_analysis/"
echo "Total time: ${hours}h ${minutes}m"
echo "========================================"
