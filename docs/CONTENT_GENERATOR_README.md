# Content Generator - Complete Documentation

**Status**: Phases 1, 2A, 2B Complete ✅ | Phase 3 Planned 📋
**Branch**: `feature/content-generator-v1`
**Started**: 2025-10-31

---

## Quick Start

```bash
# 1. Find viral outliers (text-only for content adaptation)
vt twitter find-outliers -p your-project \
  --days-back 30 \
  --min-views 5000 \
  --text-only \
  --method percentile \
  --threshold 5.0 \
  --export-json outliers.json

# 2. Analyze what makes them viral
vt twitter analyze-hooks \
  --input-json outliers.json \
  --output-json hooks.json \
  --limit 10

# 3. Review hooks.json for adaptation ideas
cat hooks.json | jq '.analyses[] | {hook_type, emotional_trigger, adaptation_notes}'

# 4. Generate content (Phase 3 - coming soon)
# vt twitter generate-content --input-json hooks.json --content-types thread,blog
```

---

## What Is This?

The **Content Generator** helps you create long-form content from viral Twitter tweets by:
1. **Finding outliers** - Statistical analysis to identify high-performing tweets
2. **Understanding hooks** - AI analysis of what makes them viral
3. **Generating content** - Adapted long-form content (threads, blogs, articles)

**Goal**: Transform proven viral hooks into content for your product/project.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    CONTENT GENERATOR                    │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  Phase 1: Outlier Detection                ✅          │
│  ├─ Statistical analysis (z-score/percentile)          │
│  ├─ Engagement scoring                                 │
│  └─ JSON export                                        │
│                                                         │
│  Phase 2A: Media Type Detection           ✅           │
│  ├─ Classify tweets (text/video/image)                │
│  ├─ Database migration                                 │
│  └─ Text-only filtering                                │
│                                                         │
│  Phase 2B: Hook Analyzer                  ✅           │
│  ├─ AI classification (14 hook types)                  │
│  ├─ Emotional triggers (10 types)                      │
│  ├─ Content patterns (8 types)                         │
│  └─ Adaptation guidance                                │
│                                                         │
│  Phase 3: Content Generation              📋           │
│  ├─ Thread generation                                  │
│  ├─ Blog post generation                               │
│  ├─ LinkedIn articles                                  │
│  ├─ Newsletter sections                                │
│  └─ Export & publishing                                │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## Documentation

- **[Phase 1: Outlier Detection](./CONTENT_GENERATOR_PHASE1.md)** ✅
  - Statistical methods, CLI usage, testing results

- **[Phase 2B: Hook Analyzer](./CONTENT_GENERATOR_PHASE2B.md)** ✅
  - AI classification, hook types, emotional triggers

- **[Phase 3: Content Generation (Plan)](./CONTENT_GENERATOR_PHASE3_PLAN.md)** 📋
  - Architecture, database schema, implementation phases

---

## Current Status

### ✅ Complete

**Phase 1: Outlier Detection**
- Z-score and percentile methods
- 10 outliers found from 322 tweets
- JSON export working

**Phase 2A: Media Type Detection**
- 30,546 posts classified (26K text, 4K video)
- Text-only filtering (42% are video!)
- Database migration complete

**Phase 2B: Hook Analyzer**
- 14 hook types, 10 emotions, 8 patterns
- AI-powered with Gemini 2.0 Flash
- Tested on 3 tweets successfully

### 📋 Planned

**Phase 3: Content Generation**
- Thread generation (5-10 tweets)
- Blog post generation (500-1500 words)
- Database storage
- Export functionality

---

## Files

### Code
```
viraltracker/generation/
├── outlier_detector.py        (410 lines) - Phase 1
├── hook_analyzer.py            (327 lines) - Phase 2B
└── content_generator.py        (TODO) - Phase 3

viraltracker/cli/
└── twitter.py                  (+270 lines)
    ├── find-outliers           - Phase 1 CLI
    ├── analyze-hooks           - Phase 2B CLI
    └── generate-content        (TODO) - Phase 3 CLI

viraltracker/scrapers/
└── twitter.py                  (+53 lines)
    └── _detect_media_type()    - Phase 2A
```

### Database
```
migrations/
├── 2025-10-31_add_media_type_to_posts.sql  - Phase 2A
└── 2025-XX-XX_add_generated_content.sql    (TODO) - Phase 3
```

### Documentation
```
docs/
├── CONTENT_GENERATOR_README.md        (this file)
├── CONTENT_GENERATOR_PHASE1.md        - Phase 1 docs
├── CONTENT_GENERATOR_PHASE2B.md       - Phase 2B docs
└── CONTENT_GENERATOR_PHASE3_PLAN.md   - Phase 3 plan
```

---

## Examples

### Example 1: Find and Analyze Parenting Content

```bash
# Find viral parenting tweets
vt twitter find-outliers -p yakety-pack-instagram \
  --days-back 30 \
  --min-views 10000 \
  --text-only \
  --method percentile \
  --threshold 3.0 \
  --export-json parenting_outliers.json

# Result: 10 outliers, avg 2.3M views, 45K likes

# Analyze hooks
vt twitter analyze-hooks \
  --input-json parenting_outliers.json \
  --output-json parenting_hooks.json

# Result:
# - 4x relatable_slice (humor)
# - 3x listicle_howto (curiosity)
# - 2x shock_violation (humor)
```

### Example 2: Hook Analysis Output

```json
{
  "tweet_text": "8 parenting hacks I learned from a nanny with a PhD 👇",
  "hook_type": "listicle_howto",
  "emotional_trigger": "curiosity",
  "content_pattern": "statement",
  "hook_explanation": "Combines authority (PhD), usefulness (hacks), and curiosity (numbered list)",
  "adaptation_notes": "Expand into full blog with 8 detailed tips, each with examples and explanations"
}
```

---

## Performance & Cost

### Phase 1: Outlier Detection
- **Speed**: ~2 seconds for 1000 tweets
- **Cost**: $0 (database queries only)

### Phase 2B: Hook Analysis
- **Speed**: ~5-7 seconds per tweet
- **Cost**: ~$0.001 per tweet (Gemini 2.0 Flash)
- **Batch of 10**: ~$0.01, ~60 seconds

### Phase 3: Content Generation (Estimated)
- **Speed**: ~10-15 seconds per piece
- **Cost**: ~$0.01 per thread, ~$0.02 per blog
- **Quality**: Publishable with minor edits

---

## Dependencies

### Python Packages
```
google-generativeai  - Gemini API (Phase 2B, 3)
supabase            - Database
numpy               - Statistical analysis (Phase 1)
scipy               - Statistical functions (Phase 1)
click               - CLI framework
```

### Environment Variables
```
GEMINI_API_KEY      - For hook analysis and content generation
SUPABASE_URL        - Database connection
SUPABASE_KEY        - Database authentication
```

### Database
- PostgreSQL with pgvector
- Tables: projects, posts, generated_content (Phase 3)

---

## Testing

### Test Datasets
- **yakety-pack-instagram**: 1000 tweets, 30 days
- **Outliers found**: 10-17 depending on filters
- **Top outlier**: 13.2M views (parenting hack video)

### Test Commands
```bash
# Test outlier detection
vt twitter find-outliers -p yakety-pack-instagram \
  --days-back 30 --min-views 5000 --text-only \
  --method percentile --threshold 5.0 \
  --export-json test_outliers.json

# Test hook analysis
vt twitter analyze-hooks \
  --input-json test_outliers.json \
  --output-json test_hooks.json \
  --limit 3
```

---

## Known Issues

### Phase 1
- No per-account outlier detection (compares across all accounts)
- No topic filtering yet

### Phase 2A
- Media detection based on Apify fields (may miss some cases)
- Existing tweets backfilled as 'text' (need re-scraping for accurate types)

### Phase 2B
- Sequential processing (slow for large batches)
- No result caching (re-analyzes on every run)
- Only Gemini 2.0 Flash (no model fallback)
- Limited testing (3 tweets only)

### Phase 3
- Not implemented yet

---

## Roadmap

### V1.0 (Current Sprint)
- [x] Phase 1: Outlier Detection
- [x] Phase 2A: Media Type Detection
- [x] Phase 2B: Hook Analyzer
- [ ] Phase 3: Content Generation

### V1.1 (Future)
- [ ] Batch processing (async, parallel)
- [ ] Result caching in database
- [ ] Template system for content generation
- [ ] Quality scoring for generated content

### V1.2 (Future)
- [ ] Auto-publishing integrations
- [ ] A/B testing different formats
- [ ] SEO optimization
- [ ] Engagement prediction

---

## Contributing

### Adding New Hook Types

Edit `viraltracker/generation/hook_analyzer.py`:
```python
HOOK_TYPES = [
    "your_new_type",  # Description
    # ... existing types
]
```

### Adding New Content Types

Phase 3 will support pluggable content generators:
```python
class BlogGenerator(ContentGenerator):
    def generate(self, hook_analysis, project_context):
        # Your implementation
        pass
```

---

## Support

### Issues
Report bugs or feature requests on GitHub issues.

### Questions
Check existing documentation first, then ask in discussions.

### Feature Requests
Phase 3 is open for feature suggestions!

---

## License

Part of the ViralTracker project.

---

## Credits

- **Hook Intelligence Framework**: 14 hook types
- **Statistical Methods**: Trimmed mean, z-score analysis
- **AI Model**: Google Gemini 2.0 Flash
- **Built with**: Claude Code

---

**Last Updated**: 2025-10-31
**Branch**: feature/content-generator-v1
**Status**: Phases 1-2B Complete, Phase 3 Planned
