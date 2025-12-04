#!/bin/bash
# Railway startup script for Viraltracker Web Dashboard

# Ensure we're in the right directory
cd /app || exit 1

# Start uvicorn with proper configuration
# Uses web.app (cron dashboard) - change to api.app:app for REST API
exec python -m uvicorn viraltracker.web.app:app --host 0.0.0.0 --port "${PORT:-8000}"
