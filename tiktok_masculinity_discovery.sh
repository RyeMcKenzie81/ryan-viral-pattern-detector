#!/bin/bash

# TikTok Masculinity Content Discovery (Phase 1)
# Searches multiple masculinity keywords to discover viral creators

# Create output directory
mkdir -p ~/Downloads/masculinity_tiktok

# Masculinity-related keywords
keywords=(
  "masculinity"
  "men's health"
  "self improvement men"
  "fitness motivation"
  "alpha male"
  "modern masculinity"
  "men's lifestyle"
  "brotherhood"
  "father figure"
  "men's mental health"
)

# Track start time
start_time=$(date +%s)

echo "========================================"
echo "TIKTOK MASCULINITY DISCOVERY - PHASE 1"
echo "========================================"
echo "Total keywords: ${#keywords[@]}"
echo "Posts per keyword: 100"
echo "Project: masculinity-tiktok"
echo "========================================"
echo ""

# Search each keyword
keyword_count=0
for keyword in "${keywords[@]}"; do
  keyword_count=$((keyword_count + 1))

  echo "========================================"
  echo "[$keyword_count/${#keywords[@]}] Searching: $keyword"
  echo "========================================"

  # Run TikTok search
  source venv/bin/activate && python -m viraltracker.cli.main tiktok search "$keyword" \
    --count 100 \
    --min-views 50000 \
    --max-followers 200000 \
    --max-days 30 \
    --project masculinity-tiktok \
    --save

  # Check if command was successful
  if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Completed: $keyword"
    echo ""
  else
    echo ""
    echo "❌ Failed: $keyword"
    echo ""
  fi

  # Wait between searches (rate limiting)
  if [ $keyword_count -lt ${#keywords[@]}]; then
    echo "Waiting 30 seconds before next search..."
    sleep 30
  fi
done

# Calculate total time
end_time=$(date +%s)
duration=$((end_time - start_time))
minutes=$((duration / 60))

echo ""
echo "========================================"
echo "PHASE 1 COMPLETE!"
echo "========================================"
echo "Total time: ${minutes} minutes"
echo "Keywords searched: ${#keywords[@]}"
echo ""
echo "Next step: Extract unique creators from database"
echo "  Run: python extract_masculinity_creators.py"
echo ""
