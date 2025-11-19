#!/bin/bash

# Daily Scrape Wrapper for Cron
# Runs the 24-hour scrape with proper logging

# Set working directory
cd /Users/ryemckenzie/projects/viraltracker

# Create log directory
mkdir -p ~/Downloads/cron_logs

# Generate log filename with timestamp
LOG_FILE=~/Downloads/cron_logs/daily_scrape_$(date +\%Y\%m\%d_\%H\%M\%S).log

# Run the scrape script and log output
echo "==================================================" >> "$LOG_FILE"
echo "Daily Scrape Started: $(date)" >> "$LOG_FILE"
echo "==================================================" >> "$LOG_FILE"

./scrape_all_keywords_24h.sh >> "$LOG_FILE" 2>&1

echo "" >> "$LOG_FILE"
echo "==================================================" >> "$LOG_FILE"
echo "Daily Scrape Completed: $(date)" >> "$LOG_FILE"
echo "==================================================" >> "$LOG_FILE"

# Keep only last 30 days of logs
find ~/Downloads/cron_logs -name "daily_scrape_*.log" -mtime +30 -delete
