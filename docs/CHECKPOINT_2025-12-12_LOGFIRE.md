# Checkpoint: Logfire Setup Issue

**Date:** 2025-12-12
**Context:** Logfire causing deployment failure due to dependency resolution

## Problem

Adding `logfire>=0.50.0` to requirements.txt caused pip to backtrack through 100+ versions trying to resolve OpenTelemetry dependency conflicts with `pydantic-ai-slim==1.18.0`.

Deploy logs show:
- `INFO: pip is looking at multiple versions of opentelemetry-proto...`
- `INFO: This is taking longer than usual...`
- Downloads logfire 4.16.0, 4.15.1, 4.15.0... all the way down to 2.1.2+

## Root Cause

- `logfire` depends on `opentelemetry-*` packages
- `pydantic-ai-slim` also depends on `opentelemetry-api>=1.28.0`
- Version constraints conflict, causing pip to try every combination

## Solution Options

1. **Remove logfire** - Quick fix, no observability
2. **Pin specific version** - Find compatible logfire + opentelemetry combo
3. **Use logfire-api** - Lightweight shim, no actual tracing

## Recommendation

Remove logfire for now. Add back later with pinned versions after testing locally.

## Files Changed

- `requirements.txt` - Added `logfire>=0.50.0`
- `viraltracker/core/observability.py` - New file
- `viraltracker/ui/app.py` - Added setup_logfire() call
- `viraltracker/services/brand_research_service.py` - Added logfire import

## To Revert

```bash
# Remove logfire line from requirements.txt
# The observability.py module handles missing logfire gracefully (no-op stub)
```
