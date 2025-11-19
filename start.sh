#!/bin/bash
# Railway startup script for Viraltracker API

# Ensure we're in the right directory
cd /app || exit 1

# Start uvicorn with proper configuration
exec python -m uvicorn viraltracker.api.app:app --host 0.0.0.0 --port "${PORT:-8000}"
