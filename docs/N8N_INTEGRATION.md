# n8n Integration Guide

**Last Updated:** 2025-11-19
**Viraltracker API Version:** 1.0.0
**Status:** Production Ready

---

## Overview

This guide shows how to integrate Viraltracker's FastAPI backend with n8n for automated viral content analysis workflows.

**Use Cases:**
- Daily viral tweet reports delivered to Slack/Email
- Automated hook analysis for content strategy
- Scheduled data exports for analytics
- Real-time alerts for viral opportunities

n8n is a workflow automation tool that can trigger Viraltracker analysis on:
- Scheduled intervals (daily, hourly, etc.)
- Webhook triggers (external events)
- Database changes (new data)

---

## Prerequisites

### 1. Viraltracker API Deployed

Your Viraltracker API should be deployed and accessible:
- **Production URL:** https://ryan-viral-pattern-detector-production.up.railway.app
- **Health Check:** `GET /health`
- **API Docs:** `GET /docs`

### 2. API Key

Set your API key in Railway environment variables:
```bash
VIRALTRACKER_API_KEY=your-secret-key-here
```

### 3. n8n Instance

You need access to an n8n instance:
- **Cloud:** https://n8n.io (Recommended for beginners)
- **Self-hosted:** https://docs.n8n.io/hosting/

---

## Available API Endpoints

### 1. Find Outliers
**Endpoint:** `POST /tools/find-outliers`

Finds statistically viral tweets using Z-score analysis.

**Request:**
```json
{
  "hours_back": 24,
  "threshold": 2.0,
  "method": "zscore"
}
```

**Response:**
```json
{
  "outliers": [
    {
      "tweet_id": "123...",
      "text": "Amazing tweet...",
      "view_count": 150000,
      "zscore": 3.5,
      "url": "https://twitter.com/..."
    }
  ],
  "total_analyzed": 450,
  "outliers_found": 8,
  "threshold_used": 2.0
}
```

### 2. Analyze Hooks
**Endpoint:** `POST /tools/analyze-hooks`

Analyzes what makes tweets go viral using Gemini AI.

**Request:**
```json
{
  "tweet_ids": ["123...", "456..."],
  "limit": 20
}
```

**Response:**
```json
{
  "analyses": [
    {
      "tweet_id": "123...",
      "hook_type": "hot_take",
      "emotional_trigger": "validation",
      "hook_explanation": "Strong opinion that...",
      "adaptation_notes": "For your brand, try..."
    }
  ],
  "summary": {
    "top_hook_type": "hot_take",
    "top_trigger": "validation",
    "average_confidence": 0.85
  }
}
```

### 3. Agent Execution
**Endpoint:** `POST /agent/run`

Run natural language queries through the Pydantic AI agent.

**Request:**
```json
{
  "prompt": "Find viral tweets from the last 24 hours and analyze their hooks",
  "project_name": "yakety-pack-instagram",
  "model": "openai:gpt-4o"
}
```

**Response:**
```json
{
  "response": "Found 8 viral tweets... [analysis]",
  "tool_calls": ["find_outliers_tool", "analyze_hooks_tool"],
  "execution_time": 12.5
}
```

---

## Example Workflows

### Workflow 1: Daily Viral Report (Simple)

**Description:** Get a daily report of viral tweets delivered to Slack every morning at 9 AM.

**Node Structure:**
```
Schedule Trigger (Daily 9am)
    ↓
HTTP Request: Find Outliers
    ↓
Format Results (Code Node)
    ↓
Send to Slack
```

#### Step-by-Step Setup

**1. Schedule Trigger**
- Node Type: `Schedule Trigger`
- Configuration:
  - Trigger Interval: `Days`
  - Days Between Triggers: `1`
  - Trigger at Hour: `9`
  - Trigger at Minute: `0`

**2. HTTP Request: Find Outliers**
- Node Type: `HTTP Request`
- Configuration:
  - Method: `POST`
  - URL: `https://ryan-viral-pattern-detector-production.up.railway.app/tools/find-outliers`
  - Authentication: `Header Auth`
    - Name: `X-API-Key`
    - Value: `{{ $env.VIRALTRACKER_API_KEY }}`
  - Send Body: `Yes`
  - Body Content Type: `JSON`
  - Body:
    ```json
    {
      "hours_back": 24,
      "threshold": 2.0,
      "method": "zscore"
    }
    ```

**3. Format Results (Code Node)**
- Node Type: `Code`
- Mode: `Run Once for All Items`
- JavaScript Code:
```javascript
const data = $input.first().json;

const report = `🔥 *Daily Viral Report*

📊 *Summary*
- Total Analyzed: ${data.total_analyzed} tweets
- Viral Tweets Found: ${data.outliers_found}
- Threshold: ${data.threshold_used} SD

🏆 *Top 5 Viral Tweets:*

${data.outliers.slice(0, 5).map((tweet, i) => `
${i + 1}. *${tweet.view_count.toLocaleString()} views* (Z: ${tweet.zscore.toFixed(2)})
   ${tweet.text.substring(0, 100)}${tweet.text.length > 100 ? '...' : ''}
   ${tweet.url}
`).join('\n')}

_Generated: ${new Date().toLocaleString()}_
`;

return [{ json: { report } }];
```

**4. Send to Slack**
- Node Type: `Slack`
- Operation: `Post Message`
- Configuration:
  - Channel: `#viral-content`
  - Text: `{{ $json.report }}`
  - As User: `Yes`

---

### Workflow 2: Complete Analysis Pipeline (Advanced)

**Description:** Find viral tweets, analyze their hooks, and generate a comprehensive report with actionable insights.

**Node Structure:**
```
Schedule Trigger (Daily 9am)
    ↓
HTTP Request: Find Outliers
    ↓
Extract Tweet IDs (Code Node)
    ↓
HTTP Request: Analyze Hooks
    ↓
Combine Data (Merge Node)
    ↓
Generate Report (Code Node)
    ↓
Send Email with Attachments
```

#### Step-by-Step Setup

**1-2.** Same as Workflow 1

**3. Extract Tweet IDs (Code Node)**
- Node Type: `Code`
- Mode: `Run Once for All Items`
- JavaScript Code:
```javascript
const outliers = $input.first().json.outliers;
const tweetIds = outliers.map(tweet => tweet.tweet_id);

return [{
  json: {
    tweet_ids: tweetIds,
    outlier_data: outliers
  }
}];
```

**4. HTTP Request: Analyze Hooks**
- Node Type: `HTTP Request`
- Configuration:
  - Method: `POST`
  - URL: `https://ryan-viral-pattern-detector-production.up.railway.app/tools/analyze-hooks`
  - Authentication: `Header Auth`
    - Name: `X-API-Key`
    - Value: `{{ $env.VIRALTRACKER_API_KEY }}`
  - Send Body: `Yes`
  - Body Content Type: `JSON`
  - Body:
    ```json
    {
      "tweet_ids": "{{ $json.tweet_ids }}",
      "limit": 20
    }
    ```

**5. Generate Comprehensive Report (Code Node)**
```javascript
const outlierData = $input.first().json.outlier_data;
const hookData = $input.last().json;

const report = `
# 🔥 Daily Viral Content Report
**Date:** ${new Date().toLocaleDateString()}

## 📊 Executive Summary
- **Viral Tweets Found:** ${outlierData.length}
- **Top Hook Type:** ${hookData.summary?.top_hook_type || 'N/A'}
- **Top Trigger:** ${hookData.summary?.top_trigger || 'N/A'}

## 🏆 Top Viral Tweets
${outlierData.slice(0, 5).map((tweet, i) => {
  const hook = hookData.analyses?.find(a => a.tweet_id === tweet.tweet_id);
  return `
### ${i + 1}. ${tweet.view_count.toLocaleString()} Views
**Tweet:** ${tweet.text}
**Hook:** ${hook?.hook_type || 'N/A'}
**Trigger:** ${hook?.emotional_trigger || 'N/A'}
${tweet.url}
`;
}).join('\n')}
`;

return [{ json: { report } }];
```

---

### Workflow 3: Agent-Based Natural Language Queries

**Description:** Use the Pydantic AI agent for complex, multi-step analysis with natural language.

**Node Structure:**
```
Webhook Trigger
    ↓
HTTP Request: Agent Run
    ↓
Parse Response
    ↓
Send to Slack/Email
```

#### Step-by-Step Setup

**1. Webhook Trigger**
- Node Type: `Webhook`
- Configuration:
  - HTTP Method: `POST`
  - Path: `viral-analysis`

**2. HTTP Request: Agent Run**
- Node Type: `HTTP Request`
- Configuration:
  - Method: `POST`
  - URL: `https://ryan-viral-pattern-detector-production.up.railway.app/agent/run`
  - Authentication: `Header Auth`
    - Name: `X-API-Key`
    - Value: `{{ $env.VIRALTRACKER_API_KEY }}`
  - Send Body: `Yes`
  - Body Content Type: `JSON`
  - Body:
    ```json
    {
      "prompt": "{{ $json.body.prompt }}",
      "project_name": "yakety-pack-instagram",
      "model": "openai:gpt-4o"
    }
    ```

**Example Webhook Request:**
```bash
curl -X POST https://your-n8n.com/webhook/viral-analysis \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Find viral tweets from the last 24 hours, analyze their hooks, and give me the top 3 content ideas for tomorrow"
  }'
```

---

## Authentication

### Method 1: Header Authentication (Recommended)

All API requests require the `X-API-Key` header:

```
X-API-Key: your-secret-key-here
```

In n8n, use **Header Auth** authentication type:
- Header Name: `X-API-Key`
- Header Value: `{{ $env.VIRALTRACKER_API_KEY }}`

### Method 2: Environment Variables

Store your API key in n8n environment variables for security:

1. Go to **Settings** → **Environment Variables**
2. Add: `VIRALTRACKER_API_KEY = your-secret-key-here`
3. Reference in nodes: `{{ $env.VIRALTRACKER_API_KEY }}`

---

## Error Handling

### Common Errors

**1. 401 Unauthorized**
```json
{
  "detail": "Invalid API key"
}
```
**Fix:** Check `X-API-Key` header is set correctly

**2. 429 Too Many Requests**
```json
{
  "detail": "Rate limit exceeded. Try again in 60 seconds."
}
```
**Fix:** Add delay between requests or reduce frequency

**3. 500 Internal Server Error**
```json
{
  "detail": "Gemini API quota exceeded"
}
```
**Fix:** Check Gemini API quota on Google AI Studio

### Error Handling in n8n

Add an **Error Trigger** node to handle failures gracefully:

```javascript
// Error Handler Code Node
const error = $input.first().json;

const errorReport = `
⚠️ *Viraltracker Workflow Failed*

**Error:** ${error.message}
**Time:** ${new Date().toLocaleString()}
**Node:** ${error.node}

Please check the n8n logs for details.
`;

return [{ json: { errorReport } }];
```

---

## Rate Limits

### Viraltracker API
- **Rate Limit:** 10 requests per minute per IP
- **Concurrent Requests:** Max 3 simultaneous

### Gemini API (Hook Analysis)
- **Rate Limit:** 9 requests per minute (free tier)
- **Daily Quota:** Check Google AI Studio

### Best Practices
1. Use caching when possible
2. Batch analyze tweets instead of one-by-one
3. Schedule heavy workflows during off-peak hours
4. Add delays between API calls (6-7 seconds for Gemini)

---

## Cost Estimation

### Viraltracker API (Railway)
- **Hosting:** ~$20-25/month (Railway Pro plan)
- **API Calls:** Included (no per-request cost)

### Gemini API (Hook Analysis)
- **Free Tier:** 60 requests per minute
- **Paid Tier:** $0.00125 per 1K characters
- **Estimated:** ~$0.01-0.05 per tweet analysis

### n8n
- **Cloud:** $20/month (Starter plan)
- **Self-hosted:** Free (hosting costs vary)

### Total Monthly Cost
- **Minimal Usage:** ~$20-30/month
- **Heavy Usage:** ~$40-60/month

---

## Best Practices

1. **Use direct tool endpoints** for deterministic workflows
2. **Use agent endpoint** for flexible, natural language requests
3. **Add retry logic** for API failures (n8n built-in)
4. **Cache results** to avoid redundant API calls
5. **Monitor rate limits** (10 req/min default)
6. **Set up error notifications** to catch failures early
7. **Use environment variables** for all sensitive data
8. **Test workflows** before deploying to production
9. **Document your workflows** for team collaboration
10. **Monitor costs** especially for Gemini API usage

---

## Testing Workflows

### Test Mode

Before deploying to production, test your workflows:

1. **Use Test Webhook:** n8n provides test webhook URLs
2. **Manual Trigger:** Click "Execute Workflow" to test
3. **Check Logs:** View execution logs for errors
4. **Verify Data:** Inspect node outputs

### Sample Test Data

Use this sample request to test without hitting the API:

```json
{
  "outliers": [
    {
      "tweet_id": "1234567890",
      "text": "This is a test viral tweet",
      "view_count": 50000,
      "zscore": 2.5,
      "url": "https://twitter.com/test/status/1234567890"
    }
  ],
  "total_analyzed": 100,
  "outliers_found": 1,
  "threshold_used": 2.0
}
```

---

## Deployment Checklist

Before going live with your n8n workflows:

- [ ] API key set in environment variables
- [ ] Webhook URLs are secured (not public)
- [ ] Error handling configured
- [ ] Rate limiting respected
- [ ] Test workflow executed successfully
- [ ] Notification channels tested (Slack/Email)
- [ ] Schedule triggers set correctly
- [ ] Cost monitoring enabled

---

## Support and Resources

### Viraltracker API
- **Docs:** https://ryan-viral-pattern-detector-production.up.railway.app/docs
- **Health Check:** https://ryan-viral-pattern-detector-production.up.railway.app/health
- **GitHub Issues:** https://github.com/yourusername/viraltracker/issues

### n8n
- **Documentation:** https://docs.n8n.io/
- **Community Forum:** https://community.n8n.io/
- **Templates:** https://n8n.io/workflows/

### Gemini API
- **Documentation:** https://ai.google.dev/docs
- **API Console:** https://aistudio.google.com/apikey
- **Rate Limits:** https://ai.google.dev/pricing

---

**Last Updated:** 2025-11-19
**Maintained By:** Viraltracker Team
**Questions?** Open an issue on GitHub
