#!/bin/bash
# Railway startup script for Streamlit UI

# Ensure we're in the right directory
cd /app || exit 1

# Start Streamlit with proper configuration
exec python -m streamlit run viraltracker/ui/app.py \
  --server.port="${PORT:-8501}" \
  --server.address=0.0.0.0 \
  --server.headless=true \
  --browser.gatherUsageStats=false
