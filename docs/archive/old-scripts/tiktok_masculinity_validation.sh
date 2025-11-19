#!/bin/bash

# TikTok Masculinity Content Validation (Phase 2)
# Scrapes individual accounts to validate masculinity focus

# Input file with usernames
ACCOUNTS_FILE="masculinity_accounts.txt"

# Check if file exists
if [ ! -f "$ACCOUNTS_FILE" ]; then
  echo "Error: $ACCOUNTS_FILE not found"
  exit 1
fi

# Count total accounts
TOTAL_ACCOUNTS=$(wc -l < "$ACCOUNTS_FILE")

# Track start time
start_time=$(date +%s)

echo "========================================"
echo "TIKTOK MASCULINITY VALIDATION - PHASE 2"
echo "========================================"
echo "Total accounts: $TOTAL_ACCOUNTS"
echo "Posts per account: 50"
echo "Project: masculinity-tiktok"
echo "========================================"
echo ""

# Scrape each account
account_count=0
while IFS= read -r username || [ -n "$username" ]; do
  account_count=$((account_count + 1))

  echo "========================================"
  echo "[$account_count/$TOTAL_ACCOUNTS] Scraping: @$username"
  echo "========================================"

  # Run TikTok user scrape
  source venv/bin/activate && python -m viraltracker.cli.main tiktok user "$username" \
    --count 50 \
    --project masculinity-tiktok \
    --save

  # Check if command was successful
  if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Completed: @$username"
    echo ""
  else
    echo ""
    echo "❌ Failed: @$username"
    echo ""
  fi

  # Wait between scrapes (rate limiting)
  # Skip wait on last account
  if [ $account_count -lt $TOTAL_ACCOUNTS ]; then
    echo "Waiting 30 seconds before next account..."
    sleep 30
  fi
done < "$ACCOUNTS_FILE"

# Calculate total time
end_time=$(date +%s)
duration=$((end_time - start_time))
minutes=$((duration / 60))

echo ""
echo "========================================"
echo "PHASE 2 COMPLETE!"
echo "========================================"
echo "Total time: ${minutes} minutes"
echo "Accounts scraped: $account_count"
echo ""
echo "Next step: Analyze content for masculinity focus"
echo "  - Calculate what % of each account's posts are masculinity-related"
echo "  - Filter to accounts with >70% masculinity content"
echo ""
