# n8n Integration Guide

How to integrate Viraltracker API with n8n workflows.

## Overview

n8n is a workflow automation tool that can trigger Viraltracker analysis on:
- Scheduled intervals (daily, hourly, etc.)
- Webhook triggers (external events)
- Database changes (new data)

## Example Workflow: Daily Viral Report

### Workflow Nodes

1. **Schedule Trigger** → 2. **HTTP Request (Viraltracker)** → 3. **Email** → 4. **Save to Database**

### Node Configuration

#### 1. Schedule Trigger
```
- Trigger: Cron
- Expression: 0 9 * * * (Every day at 9 AM)
```

#### 2. HTTP Request - Find Viral Tweets
```
Method: POST
URL: https://your-app.up.railway.app/agent/run
Authentication: Header Auth
  Header Name: X-API-Key
  Header Value: your-api-key-here

Body (JSON):
{
  "prompt": "Find viral tweets from the last 24 hours and analyze their hooks",
  "project_name": "yakety-pack-instagram",
  "model": "openai:gpt-4o"
}
```

#### 3. Send Email (optional)
```
To: team@yourcompany.com
Subject: Daily Viral Content Report
Body: {{ $json.result }}
```

#### 4. Save to Notion/Airtable (optional)
```
Database: Viral Reports
Fields:
  - Date: {{ $now }}
  - Report: {{ $node["HTTP Request"].json.result }}
  - Outlier Count: {{ $node["HTTP Request"].json.metadata.outlier_count }}
```

## Example Workflow: Webhook-Triggered Analysis

### Use Case
Analyze tweets when new data is scraped.

### Nodes
1. **Webhook** → 2. **HTTP Request (Viraltracker)** → 3. **Slack Notification**

#### 1. Webhook Trigger
```
Method: POST
Path: /viraltracker-webhook
Authentication: Header Auth (optional)
```

#### 2. HTTP Request
```
URL: https://your-app.up.railway.app/tools/find-outliers
Method: POST

Body:
{
  "project_name": "{{ $json.project }}",
  "hours_back": 24,
  "threshold": 2.0,
  "method": "zscore",
  "limit": 10
}
```

#### 3. Slack Message
```
Channel: #viral-content
Message:
Found {{ $json.data.outlier_count }} viral tweets!
Top performer: {{ $json.data.outliers[0].tweet.text }}
Engagement: {{ $json.data.outliers[0].tweet.engagement_score }}
```

## Available Endpoints

### 1. Agent Run (Natural Language)
```bash
POST /agent/run
{
  "prompt": "your natural language request",
  "project_name": "your-project"
}
```

### 2. Find Outliers (Direct)
```bash
POST /tools/find-outliers
{
  "project_name": "your-project",
  "hours_back": 24,
  "threshold": 2.0
}
```

### 3. Analyze Hooks (Direct)
```bash
POST /tools/analyze-hooks
{
  "project_name": "your-project",
  "hours_back": 24,
  "limit": 20
}
```

## Error Handling in n8n

Add error handling nodes:

```
HTTP Request → [Error Trigger] → Slack Alert
```

Configure error trigger:
```
Trigger on: Error
Send to: #alerts channel
Message: Viraltracker API failed: {{ $json.error }}
```

## Best Practices

1. **Use direct tool endpoints** for deterministic workflows
2. **Use agent endpoint** for flexible, natural language requests
3. **Add retry logic** for API failures (n8n built-in)
4. **Cache results** to avoid redundant API calls
5. **Monitor rate limits** (10 req/min default)

## Example Templates

### Template 1: Content Calendar Automation
```
Schedule → Viraltracker (find trends) → ChatGPT (generate ideas) → Notion (save)
```

### Template 2: Real-Time Alerts
```
Webhook (new tweet) → Viraltracker (analyze) → If (viral) → Slack (alert team)
```

### Template 3: Weekly Report
```
Schedule (Monday) → Viraltracker (7 days) → Google Docs → Email
```

## Troubleshooting

**401 Unauthorized**: Check X-API-Key header
**429 Rate Limited**: Add delay between requests
**500 Server Error**: Check Railway logs for details

## Resources

- [n8n Documentation](https://docs.n8n.io)
- [HTTP Request Node](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.httprequest/)
- [Webhook Node](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook/)
