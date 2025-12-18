# Reddit Sentiment Pipeline - Checkpoint 3 (FINAL)

**Date:** 2025-12-17
**Status:** COMPLETE

---

## Implementation Summary

Successfully implemented a Reddit Domain Sentiment Analysis Pipeline that:
1. Scrapes Reddit posts via Apify
2. Filters by engagement (upvotes, comments)
3. Scores with LLMs (Sonnet for filtering, Opus 4.5 for extraction)
4. Categorizes into 6 sentiment buckets
5. Extracts quotes with reasoning
6. Optionally syncs to persona fields for belief-first planning

---

## All Files Created/Modified

| File | Action | Lines | Purpose |
|------|--------|-------|---------|
| `migrations/2025-12-18_reddit_sentiment.sql` | Created (user ran) | ~100 | Database schema |
| `viraltracker/services/models.py` | Modified | +170 | Pydantic models |
| `viraltracker/services/reddit_sentiment_service.py` | Created | ~700 | Core service |
| `viraltracker/pipelines/states.py` | Modified | +95 | State dataclass |
| `viraltracker/pipelines/reddit_sentiment.py` | Created | ~450 | Pipeline + nodes |
| `viraltracker/pipelines/__init__.py` | Modified | +20 | Exports |
| `viraltracker/agent/dependencies.py` | Modified | +5 | DI container |
| `viraltracker/ui/pages/15_🔍_Reddit_Research.py` | Created | ~400 | Streamlit UI |

**Total new code:** ~1,940 lines

---

## Architecture Overview

```
Streamlit UI (15_🔍_Reddit_Research.py)
    │
    ├── Search config form
    ├── Brand/persona selector (optional)
    ├── Pipeline execution
    └── Results display
    │
    ▼
Reddit Sentiment Pipeline (pydantic-graph)
    │
    ├── ScrapeRedditNode ────────────► ApifyService
    ├── EngagementFilterNode ────────► Deterministic
    ├── RelevanceFilterNode ─────────► Claude Sonnet
    ├── SignalFilterNode ────────────► Claude Sonnet
    ├── IntentScoreNode ─────────────► Claude Sonnet
    ├── TopSelectionNode ────────────► Deterministic
    ├── CategorizeNode ──────────────► Claude Opus 4.5
    └── SaveNode ────────────────────► Supabase + Persona Sync
    │
    ▼
RedditSentimentService (business logic)
    │
    ▼
Supabase Tables:
    ├── reddit_scrape_runs
    ├── reddit_posts
    ├── reddit_comments
    └── reddit_sentiment_quotes
```

---

## Key Features

### 1. Optional Brand Association
- Can run standalone research (brand_id = NULL)
- Or associate with a brand for organized research
- Persona sync only available when brand+persona selected

### 2. 6 Sentiment Categories
| Category | Maps To | Type |
|----------|---------|------|
| PAIN_POINT | pain_points | DomainSentiment |
| DESIRED_OUTCOME | outcomes_jtbd | DomainSentiment |
| BUYING_OBJECTION | buying_objections | DomainSentiment |
| FAILED_SOLUTION | failed_solutions | List |
| DESIRED_FEATURE | desired_features | List |
| FAMILIAR_SOLUTION | familiar_promises | List |

### 3. Multi-Stage Filtering
1. **Engagement Filter** - Min upvotes/comments (deterministic)
2. **Relevance Filter** - Persona/topic match (LLM)
3. **Signal Filter** - Remove noise (LLM)
4. **Intent Score** - Buyer sophistication (LLM)
5. **Top Selection** - Keep top 20% (deterministic)

### 4. Cost Tracking
- Apify cost estimated at $1.50/1000 items
- LLM costs tracked per run
- Displayed in UI before and after execution

---

## Verification

```bash
# All files pass syntax check
python3 -m py_compile viraltracker/services/models.py              # ✅
python3 -m py_compile viraltracker/services/reddit_sentiment_service.py  # ✅
python3 -m py_compile viraltracker/pipelines/states.py             # ✅
python3 -m py_compile viraltracker/pipelines/reddit_sentiment.py   # ✅
python3 -m py_compile viraltracker/pipelines/__init__.py           # ✅
python3 -m py_compile viraltracker/agent/dependencies.py           # ✅
python3 -m py_compile "viraltracker/ui/pages/15_🔍_Reddit_Research.py"  # ✅
```

---

## Usage

### Via Streamlit UI
1. Navigate to "Reddit Research" in sidebar
2. Enter search queries (one per line)
3. Optionally specify subreddits
4. Set timeframe and filters
5. Optionally associate with brand/persona
6. Click "Run Reddit Sentiment Analysis"
7. Review extracted quotes by category

### Via Python
```python
from viraltracker.pipelines import run_reddit_sentiment

result = await run_reddit_sentiment(
    search_queries=["dog food allergies", "best dog food"],
    brand_id=UUID("..."),  # Optional
    persona_id=UUID("..."),  # Optional - enables sync
    timeframe="month",
    max_posts=500,
    auto_sync_to_persona=True
)

print(f"Extracted {result['quotes_extracted']} quotes")
print(f"By category: {result['quotes_by_category']}")
```

---

## Cost Estimates (per run)

| Component | Model | Est. Cost |
|-----------|-------|-----------|
| Apify Scrape (500 posts) | - | ~$0.75 |
| Relevance Filter | Sonnet | ~$0.15 |
| Signal Filter | Sonnet | ~$0.10 |
| Intent Scoring | Sonnet | ~$0.10 |
| Categorization + Extraction | Opus 4.5 | ~$0.50 |
| **Total** | | **~$1.60** |

---

## Next Steps (Future Enhancements)

1. **Comment Analysis** - Currently scrapes comments but doesn't analyze them
2. **Trend Detection** - Compare across time periods
3. **Competitor Mentions** - Extract and track competitor brand mentions
4. **Export to CSV** - Add export functionality for quotes
5. **Scheduled Runs** - Automated periodic scraping

---

## Adherence to CLAUDE.md

✅ **Thin Tools Pattern** - Pipeline nodes call service methods
✅ **Service Layer** - All business logic in RedditSentimentService
✅ **Pydantic Models** - All data structures use Pydantic v2
✅ **Streamlit Patterns** - Uses render_brand_selector pattern (custom for optional)
✅ **Error Handling** - Each node handles errors and updates run status
✅ **Logging** - Comprehensive logging throughout
✅ **Checkpoints** - Created checkpoints at ~40K token intervals
