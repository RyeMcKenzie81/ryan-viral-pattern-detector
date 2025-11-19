# Railway Deployment Guide

Complete guide for deploying Viraltracker API to Railway.

## Prerequisites

- Railway account ([railway.app](https://railway.app))
- GitHub repository with Viraltracker code
- Required API keys (Supabase, OpenAI, Gemini)

## Step 1: Prepare Your Repository

Ensure these files exist in your repo:

- `/Users/ryemckenzie/projects/viraltracker/Procfile` - Railway process definition
- `/Users/ryemckenzie/projects/viraltracker/railway.json` - Railway configuration
- `/Users/ryemckenzie/projects/viraltracker/requirements.txt` - Python dependencies

## Step 2: Create Railway Project

1. Go to [railway.app](https://railway.app) and sign in
2. Click "New Project"
3. Select "Deploy from GitHub repo"
4. Choose your `viraltracker` repository
5. Railway will auto-detect Python and begin building

## Step 3: Configure Environment Variables

In Railway dashboard → Variables, add these environment variables:

### Required Variables

```bash
# Supabase Database
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-supabase-anon-key

# AI APIs
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=...

# API Security
VIRALTRACKER_API_KEY=your-secure-random-key-here
```

### Optional Variables

```bash
# CORS Configuration (comma-separated)
CORS_ORIGINS=https://your-frontend.com,https://your-app.com

# Custom Port (Railway auto-provides $PORT)
PORT=8000
```

## Step 4: Generate Secure API Key

Generate a secure API key for production:

```bash
# Option 1: Using OpenSSL
openssl rand -hex 32

# Option 2: Using Python
python -c "import secrets; print(secrets.token_hex(32))"

# Option 3: Using Node.js
node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"
```

Copy the output and set as `VIRALTRACKER_API_KEY` in Railway.

## Step 5: Deploy

1. Railway automatically builds and deploys on git push
2. Monitor deployment in Railway dashboard → Deployments
3. Once deployed, Railway provides a public URL (e.g., `https://viraltracker-production.up.railway.app`)

## Step 6: Verify Deployment

### Test Health Endpoint

```bash
curl https://your-app.up.railway.app/health
```

Expected response:
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "services": {
    "database": "connected",
    "gemini_ai": "available",
    "pydantic_ai": "available"
  }
}
```

### Test Agent Endpoint

```bash
curl -X POST https://your-app.up.railway.app/agent/run \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key-here" \
  -d '{
    "prompt": "Find viral tweets from the last 24 hours",
    "project_name": "yakety-pack-instagram"
  }'
```

## Step 7: View Logs

Monitor application logs in Railway dashboard:

1. Go to your project in Railway
2. Click on the service
3. Click "Logs" tab
4. Filter by severity: Info, Warning, Error

## Auto-Deployment

Railway automatically redeploys on:

- Git push to main branch
- Manual redeploy via dashboard
- Environment variable changes

## Custom Domain (Optional)

1. In Railway dashboard → Settings
2. Click "Generate Domain" for a railway.app subdomain
3. Or add custom domain and configure DNS:
   - Add CNAME record: `your-domain.com` → `your-app.up.railway.app`
   - Wait for DNS propagation (5-60 minutes)

## Monitoring & Alerts

### Built-in Railway Monitoring

Railway provides:
- CPU usage
- Memory usage
- Network traffic
- Request count
- Response times

### Health Check

Railway uses `/health` endpoint for health checks:

```json
{
  "healthcheckPath": "/health",
  "healthcheckTimeout": 100
}
```

## Troubleshooting

### Deployment Fails

1. Check Railway build logs for errors
2. Verify all environment variables are set
3. Ensure `requirements.txt` includes all dependencies
4. Check Python version compatibility

### API Returns 500 Error

1. Check Railway logs for Python exceptions
2. Verify Supabase credentials are correct
3. Test database connection from Railway logs
4. Ensure OpenAI API key has credits

### API Returns 401 Unauthorized

1. Verify `VIRALTRACKER_API_KEY` is set in Railway
2. Check request includes `X-API-Key` header
3. Ensure API key matches exactly (no extra spaces)

### Rate Limit Errors

1. Default rate limit: 10 requests/minute per IP
2. Increase by setting `RATE_LIMIT_PER_MINUTE` env var
3. Implement client-side retry with exponential backoff

## Cost Estimation

Railway pricing (as of 2025):

- **Hobby Plan**: $5/month
  - 500 hours of usage
  - Good for development and testing

- **Pro Plan**: $20/month
  - Unlimited usage
  - Better for production

**Estimated costs for Viraltracker:**
- Small workload (< 1000 requests/day): Hobby plan sufficient
- Medium workload (1000-10000 requests/day): Pro plan recommended

## Security Best Practices

1. **Use strong API keys**: 32+ character random strings
2. **Rotate keys regularly**: Every 3-6 months
3. **Restrict CORS origins**: Don't use `*` in production
4. **Monitor logs**: Watch for suspicious activity
5. **Enable Railway's built-in DDoS protection**
6. **Use HTTPS only**: Railway provides SSL by default

## Scaling

Railway auto-scales based on:
- Horizontal: Multiple instances for high traffic
- Vertical: More CPU/memory for intensive workloads

Configure in `railway.json` if needed:

```json
{
  "deploy": {
    "numReplicas": 2,
    "restartPolicyType": "ON_FAILURE"
  }
}
```

## Backup & Disaster Recovery

1. **Database backups**: Supabase handles automatically
2. **Code backups**: Git repository is source of truth
3. **Redeploy**: Can redeploy from any git commit

## Next Steps

- [n8n Integration Guide](N8N_INTEGRATION.md)
- [Zapier Integration Guide](ZAPIER_INTEGRATION.md)
- [API Documentation](../viraltracker/api/README.md)
