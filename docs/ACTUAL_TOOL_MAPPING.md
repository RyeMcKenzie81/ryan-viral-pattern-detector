# Actual Tool Mapping for Orchestrator Refactor

**Created:** 2025-01-24
**Status:** Phase 1 Complete - Tool Mapping Documented

## Reality Check

The original plan assumed tools were split across multiple files (`tools.py`, `tools_registered.py`, `tools_phase15.py`, etc.), but **all 19 tools are actually in `tools_registered.py`**.

## Actual Tools (from tools_registered.py)

### Twitter/Analysis Tools (8 tools)
1. `find_outliers_tool` - Statistical analysis of viral tweets
2. `analyze_hooks_tool` - AI analysis of tweet hooks
3. `verify_scrape_tool` - Verify Twitter scraping worked
4. `export_results_tool` - Export comprehensive analysis reports
5. `get_top_tweets_tool` - Query database for top tweets
6. `export_tweets_tool` - Export tweets to CSV/JSON/Markdown
7. `search_twitter_tool` - Search/scrape Twitter by keyword
8. `find_comment_opportunities_tool` - Find high-quality comment opportunities
9. `export_comments_tool` - Export comment opportunities
10. `analyze_search_term_tool` - Analyze keyword engagement patterns
11. `generate_content_tool` - Generate long-form content from hooks

### TikTok Tools (5 tools)
12. `search_tiktok_tool` - Search TikTok by keyword
13. `search_tiktok_hashtag_tool` - Search TikTok by hashtag
14. `scrape_tiktok_user_tool` - Scrape TikTok user posts
15. `analyze_tiktok_video_tool` - Analyze single TikTok video
16. `analyze_tiktok_batch_tool` - Batch analyze TikTok videos

### YouTube Tools (1 tool)
17. `search_youtube_tool` - Search YouTube by keyword

### Facebook Tools (2 tools)
18. `search_facebook_ads_tool` - Search Facebook Ad Library
19. `scrape_facebook_page_ads_tool` - Scrape ads from Facebook page

## Agent Tool Allocation

### Twitter Agent (8 tools)
**Primary:** Twitter data operations
- `search_twitter_tool` - Scrape new tweets
- `get_top_tweets_tool` - Query existing tweets
- `export_tweets_tool` - Export to files
- `find_comment_opportunities_tool` - Find comment targets
- `export_comments_tool` - Export comments
- `analyze_search_term_tool` - Keyword analysis
- `generate_content_tool` - Content generation
- `verify_scrape_tool` - Verify scraping

### TikTok Agent (5 tools)
**Primary:** TikTok data operations
- `search_tiktok_tool`
- `search_tiktok_hashtag_tool`
- `scrape_tiktok_user_tool`
- `analyze_tiktok_video_tool`
- `analyze_tiktok_batch_tool`

### YouTube Agent (1 tool)
**Primary:** YouTube data operations
- `search_youtube_tool`

### Facebook Agent (2 tools)
**Primary:** Facebook advertising data operations
- `search_facebook_ads_tool`
- `scrape_facebook_page_ads_tool`

### Analysis Agent (3 tools)
**Primary:** Cross-platform analysis and insights
- `find_outliers_tool` - Statistical viral analysis
- `analyze_hooks_tool` - Hook pattern analysis
- `export_results_tool` - Comprehensive reports

## Updated Architecture

```
Orchestrator Agent (5 routing tools)
├── Twitter Agent (8 tools) - Twitter/X operations
├── TikTok Agent (5 tools) - TikTok operations
├── YouTube Agent (1 tool) - YouTube operations
├── Facebook Agent (2 tools) - Facebook Ad Library
└── Analysis Agent (3 tools) - Cross-platform insights
```

**Total:** 19 tools distributed across 5 specialized agents

## Phase 1 Status: ✅ COMPLETE

- [x] Created `ResultCache` class in dependencies.py
- [x] Converted `AgentDependencies` to Pydantic BaseModel
- [x] Added `result_cache` field with default factory
- [x] Tested imports successfully
- [x] Committed changes to feature branch
- [x] Documented actual tool mappings

## Next Steps

**Phase 2:** Create 5 specialized agents with correct tool imports
**Phase 3:** Create orchestrator with routing logic
**Phase 4:** Update agent.py for backwards compatibility
**Phase 5:** Integration testing (FastAPI, CLI, Streamlit)
**Phase 6:** Documentation and final push

## Notes

- All tools use `RunContext[AgentDependencies]` pattern
- All tools are async functions
- Tools already work with existing services
- No tool modifications needed - only agent creation and routing
