# Continuation Prompt for Next Session 🔄

**Copy and paste this into your next Claude Code session:**

---

## Context

We're building a **Search Term Analyzer** tool for the viraltracker project to find optimal Twitter search terms that yield the most "green" scored tweets (engagement opportunities).

**IMPORTANT**: This analyzer is **project-specific** and **taxonomy-driven**. A "green" tweet means it semantically matches the project's taxonomy topics (relevance weight: 0.4) and meets scoring thresholds (≥ 0.55). The same tweet could score differently for different projects.

**Current Status:**
- V1.3 of Comment Finder is complete and shipped (5 comment types, no forced tie-ins)
- Search Term Analyzer is fully planned but not yet implemented
- All design docs are in the repo

**Goal for This Session:**
Implement the Search Term Analyzer tool so we can test which Twitter search terms yield the best engagement opportunities for the yakety-pack-instagram project based on its taxonomy (screen time management, parenting tips, digital wellness).

---

## Task

Please implement the Search Term Analyzer tool according to the plan in `SEARCH_TERM_ANALYZER_PLAN.md`.

**Key Requirements:**
1. Create `viraltracker/analysis/search_term_analyzer.py` with `SearchTermAnalyzer` class
2. Add `analyze-search-term` CLI command to `viraltracker/cli/twitter.py`
3. **Use existing comment generator** to score tweets against the project's taxonomy
4. Implement these metrics:
   - **Green Ratio**: % of tweets scoring ≥ 0.55 based on project taxonomy match (out of 1000 tweets)
   - **Freshness**: % of tweets posted in last 48 hours
   - **Virality**: Average/median views per tweet
   - **Cost Efficiency**: Cost per green tweet found
   - **Topic Distribution**: Which of the project's taxonomy topics matched most
5. Output JSON report with all metrics + recommendation (Excellent/Good/Okay/Poor)

**Target Usage:**
```bash
./vt twitter analyze-search-term \
  --project yakety-pack-instagram \
  --term "screen time kids" \
  --count 1000 \
  --min-likes 20 \
  --report-file ~/Downloads/analysis_report.json
```

**Test Plan:**
After implementation, test with "screen time kids" search term (1000 tweets) to validate the tool works correctly.

---

## Important Files to Reference

1. **Plan**: `SEARCH_TERM_ANALYZER_PLAN.md` - Complete implementation blueprint
2. **Strategy**: `SEARCH_TERM_OPTIMIZATION_STRATEGY.md` - Testing methodology
3. **Checkpoint**: `CHECKPOINT_2025-10-23_FINAL.md` - Session summary
4. **Config**: `projects/yakety-pack-instagram/finder.yml` - Project taxonomy & scoring

**Existing Code to Reuse:**
- `viraltracker/cli/twitter.py` - `search` command (for scraping)
- `viraltracker/generation/comment_generator.py` - **`generate_suggestions` (CRITICAL: this scores tweets against project taxonomy)**
- `viraltracker/scoring/scorer.py` - Project-specific scoring logic
- Database schema in migrations folder

**How Scoring Works:**
The comment generator uses the project's `finder.yml` taxonomy to calculate semantic similarity (relevance: 40% weight). A "green" score (≥0.55) means the tweet is highly relevant to the project's specific topics.

---

## Expected Deliverables

1. ✅ `viraltracker/analysis/search_term_analyzer.py` - Core analyzer
2. ✅ Updated `viraltracker/cli/twitter.py` - New CLI command
3. ✅ Test results for "screen time kids" (1000 tweets)
4. ✅ Sample JSON report showing all metrics
5. ✅ Documentation of findings

**Estimated Time**: 2-3 hours implementation + 1 hour testing

---

## Success Criteria

The tool should:
- Scrape 1000 tweets for a given search term
- Generate comments/scores for all tweets
- Calculate and report all 5 metric categories
- Provide clear recommendation (Excellent/Good/Okay/Poor)
- Export results to JSON
- Cost approximately $0.11 per 1000 tweets analyzed

---

## Notes

- The viraltracker project is at `/Users/ryemckenzie/projects/viraltracker`
- Current branch: `feature/comment-finder-v1`
- Python virtual environment: `venv/`
- Database: Supabase (connection via environment variable)

**Start by reviewing** `SEARCH_TERM_ANALYZER_PLAN.md` to understand the full architecture, then begin implementation.

Good luck! 🚀
