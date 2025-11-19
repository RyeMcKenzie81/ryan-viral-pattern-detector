# Viraltracker Railway Deployment Guide

This guide explains how to deploy both the **FastAPI backend** and **Streamlit UI** to Railway.

---

## Architecture Overview

The Viraltracker project has **two separate Railway services**:

1. **API Service** (FastAPI) - REST API for agent execution and tool endpoints
2. **UI Service** (Streamlit) - Web-based chat interface for the agent

Both services share the same codebase and dependencies, but use different entry points.

---

## Prerequisites

- Railway account (https://railway.app)
- GitHub repository connected to Railway
- Environment variables configured (see below)

---

## Service 1: FastAPI API

### Configuration Files

- **Entry point**: `start.sh`
- **Railway config**: `railway.json`
- **Health check**: `/health`
- **Port**: Provided by Railway via `$PORT` env var

### Deployment Steps

1. **Create New Service in Railway**
   - Go to Railway dashboard
   - Click "New Project" → "Deploy from GitHub repo"
   - Select the `viraltracker` repository
   - Select branch: `phase-3-api-deployment` (or `main` after merge)

2. **Configure Service Settings**
   - Service Name: `viraltracker-api`
   - Root Directory: `/` (default)
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `bash start.sh`

3. **Set Environment Variables**
   ```bash
   # Required
   OPENAI_API_KEY=<your-openai-api-key>
   SUPABASE_URL=<your-supabase-url>
   SUPABASE_KEY=<your-supabase-key>
   GEMINI_API_KEY=<your-gemini-api-key>

   # Optional
   VIRALTRACKER_API_KEY=<your-custom-api-key>  # For API authentication
   CORS_ORIGINS=*  # Or specific domains: https://example.com,https://app.example.com
   PROJECT_NAME=yakety-pack-instagram  # Default project
   ```

4. **Deploy**
   - Railway will automatically build and deploy
   - Monitor logs for any errors
   - Once deployed, test health endpoint: `https://<your-api-url>/health`

### API Endpoints

Once deployed, you'll have access to:

- **Health**: `GET /health`
- **Root info**: `GET /`
- **Agent execution**: `POST /agent/run`
- **Auto-generated tool endpoints**: `POST /tools/*` (16 endpoints)
- **API docs**: `GET /docs` (Swagger UI)
- **ReDoc**: `GET /redoc` (Alternative docs)

### Example Usage

```bash
# Health check
curl https://<your-api-url>/health

# Agent execution
curl -X POST https://<your-api-url>/agent/run \
  -H "X-API-Key: <your-api-key>" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Find viral tweets from the last 24 hours",
    "project_name": "yakety-pack-instagram",
    "model": "openai:gpt-4o"
  }'

# Direct tool call (find outliers)
curl -X POST https://<your-api-url>/tools/find-outliers \
  -H "X-API-Key: <your-api-key>" \
  -H "Content-Type: application/json" \
  -d '{
    "hours_back": 24,
    "threshold": 2.0,
    "method": "zscore"
  }'
```

---

## Service 2: Streamlit UI

### Configuration Files

- **Entry point**: `streamlit_start.sh`
- **Railway config**: `railway-streamlit.json` (if using custom config)
- **Streamlit config**: `.streamlit/config.toml`
- **Health check**: `/` (Streamlit auto-provides)
- **Port**: Provided by Railway via `$PORT` env var (defaults to 8501)

### Deployment Steps

1. **Create Second Service in Railway**
   - In the same Railway project, click "New Service"
   - Select "Deploy from GitHub repo"
   - Select the same `viraltracker` repository
   - Select branch: `phase-3-api-deployment` (or `main` after merge)

2. **Configure Service Settings**
   - Service Name: `viraltracker-ui`
   - Root Directory: `/` (default)
   - Build Command: Leave empty (Railway auto-detects)
   - Start Command: `python -m streamlit run viraltracker/ui/app.py --server.port=8501 --server.address=0.0.0.0 --server.headless=true --browser.gatherUsageStats=false`
   - Public Networking Port: `8501`

3. **Set Environment Variables**
   ```bash
   # Required (same as API service)
   OPENAI_API_KEY=<your-openai-api-key>
   SUPABASE_URL=<your-supabase-url>
   SUPABASE_KEY=<your-supabase-key>
   GEMINI_API_KEY=<your-gemini-api-key>
   APIFY_TOKEN=<your-apify-token>  # NOTE: Must be APIFY_TOKEN, not APIFY_API_TOKEN

   # Optional
   PROJECT_NAME=yakety-pack-instagram  # Default project
   DB_PATH=viraltracker.db  # Database path (default)
   ```

4. **Deploy**
   - Railway will automatically build and deploy
   - Monitor logs for any errors
   - Once deployed, open the public URL to access the UI

### UI Features

The Streamlit UI provides:

- **Chat interface** - Natural language queries to the agent
- **Quick actions** - Pre-built queries for common tasks
- **Download buttons** - Export results as JSON, CSV, or Markdown
- **Multi-turn conversations** - Context-aware follow-up queries
- **Project switcher** - Change projects without redeployment
- **Structured results** - Pretty-printed results with statistics

### Example Queries

Users can ask questions like:

- "Show me viral tweets from the last 24 hours"
- "Why did those tweets go viral? Analyze their hooks"
- "Give me a full report for the last 48 hours with hooks"
- "Find comment opportunities with high engagement"
- "Search TikTok for trending fitness content"

---

## Environment Variables Reference

### Required for Both Services

| Variable | Description | Example |
|----------|-------------|---------|
| `OPENAI_API_KEY` | OpenAI API key for Pydantic AI agent | `sk-...` |
| `SUPABASE_URL` | Supabase project URL | `https://xxx.supabase.co` |
| `SUPABASE_KEY` | Supabase API key | `eyJ...` |
| `GEMINI_API_KEY` | Google Gemini API key for hook analysis | `AIza...` |

### Optional for API Service

| Variable | Description | Default |
|----------|-------------|---------|
| `VIRALTRACKER_API_KEY` | API key for authentication (if not set, no auth) | None |
| `CORS_ORIGINS` | Comma-separated list of allowed origins | `*` |
| `PROJECT_NAME` | Default project name | `yakety-pack-instagram` |

### Optional for UI Service

| Variable | Description | Default |
|----------|-------------|---------|
| `PROJECT_NAME` | Default project name (can be changed in UI) | `yakety-pack-instagram` |
| `DB_PATH` | Database file path | `viraltracker.db` |

---

## Monitoring and Logs

### Railway Dashboard

Both services provide real-time logs in the Railway dashboard:

1. Go to your Railway project
2. Click on the service (API or UI)
3. Click "Deployments" tab
4. Click on the active deployment
5. View logs in real-time

### Common Issues

**API Service**

- **502 Bad Gateway**: Service failed to start - check logs for errors
- **401 Unauthorized**: Missing or invalid `X-API-Key` header
- **429 Too Many Requests**: Rate limit exceeded (10 req/min per IP)
- **500 Internal Server Error**: Check logs for Python exceptions

**UI Service**

- **502 Bad Gateway**: Service running wrong application (FastAPI instead of Streamlit) - verify start command is correct
- **$PORT variable not expanding**: Don't use `$PORT` in Streamlit command - use hardcoded port `8501`
- **Wrong service starting**: Check Custom Start Command - should NOT be in Build Command
- **Blank page**: Streamlit failed to start - check logs for errors
- **"Missing APIFY_TOKEN" error**: Environment variable must be named `APIFY_TOKEN` (not `APIFY_API_TOKEN`)
- **Initialization Error**: Missing environment variables
- **Connection Error**: Supabase or database connection failed

---

## Production Checklist

Before going to production, ensure:

### Security
- [ ] `VIRALTRACKER_API_KEY` is set (enables authentication)
- [ ] `CORS_ORIGINS` is restricted to your domains (not `*`)
- [ ] Environment variables are set via Railway (not hardcoded)
- [ ] Supabase RLS (Row Level Security) is enabled

### Performance
- [ ] Database indexes are optimized
- [ ] Rate limiting is configured appropriately
- [ ] Healthcheck endpoints are responding correctly

### Monitoring
- [ ] Railway logs are being collected
- [ ] Error tracking is set up (Sentry, etc.)
- [ ] Uptime monitoring is configured

---

## Current Deployments

### API Service
- **URL**: https://ryan-viral-pattern-detector-production.up.railway.app
- **Status**: ✅ Deployed and healthy
- **Branch**: `phase-3-api-deployment`
- **Endpoints**:
  - Swagger Docs: `/docs`
  - Health: `/health`
  - Agent: `/agent/run`
  - Tools: `/tools/*` (16 auto-generated endpoints)

### UI Service
- **URL**: https://viraltracker-ui-production.up.railway.app
- **Status**: ✅ Deployed and healthy
- **Branch**: `phase-3-api-deployment`
- **Features**: Chat interface, quick actions, download exports, project switcher

---

## Deployment Summary

**Phase 3 - API & UI Deployment: COMPLETED** ✅

Both services are now live on Railway:
- FastAPI backend provides REST endpoints and programmatic access
- Streamlit UI provides user-friendly chat interface for natural language queries
- Both services share the same codebase and dependencies
- Environment variables configured for production use
- Health checks and monitoring enabled

### Troubleshooting Notes

During deployment, we encountered and resolved:
1. **Wrong service starting** - Railway was running API instead of UI (fixed start command)
2. **Port variable expansion** - `$PORT` not working in Streamlit CLI (hardcoded 8501)
3. **Build vs Start commands** - Confusion between build-time and runtime commands (removed custom build)
4. **Environment variable naming** - `APIFY_TOKEN` vs `APIFY_API_TOKEN` mismatch (added correct variable)

---

## Next Steps

1. ✅ **Deploy UI Service** - Completed
2. ✅ **Test Both Services** - Both verified working
3. **Merge to Main** - Create PR to merge `phase-3-api-deployment` → `main`
4. **Update Production** - Switch Railway to deploy from `main` branch
5. **Set Up Monitoring** - Configure error tracking and uptime monitoring
6. **Add Custom Domain** (Optional) - Configure custom domains for both services
7. **Enable Authentication** - Set `VIRALTRACKER_API_KEY` and restrict `CORS_ORIGINS`

---

## Support

For issues or questions:
- Check Railway logs for errors
- Review environment variables
- Test health endpoints
- Check GitHub issues for known problems
