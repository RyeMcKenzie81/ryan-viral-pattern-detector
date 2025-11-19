# Handoff Document: Phase 3 Content Generation

**Date**: 2025-10-31
**From**: Phase 1-2B (Complete)
**To**: Phase 3 (Content Generation)
**Branch**: `feature/content-generator-v1`

---

## ✅ What's Complete

### Phase 1: Outlier Detection
- **Files**: `viraltracker/generation/outlier_detector.py`, CLI command
- **Testing**: Fully tested with yakety-pack-instagram (10 outliers from 322 tweets)
- **Documentation**: `docs/CONTENT_GENERATOR_PHASE1.md`

### Phase 2A: Media Type Detection
- **Files**: Updated `twitter.py` scraper, database migration
- **Database**: 30,546 posts classified (26K text, 4K video)
- **Testing**: Text-only filtering working (filters 42% of tweets)
- **Migration**: `migrations/2025-10-31_add_media_type_to_posts.sql` (ALREADY RUN)

### Phase 2B: Hook Analyzer
- **Files**: `viraltracker/generation/hook_analyzer.py`, CLI command
- **Testing**: Tested with 3 tweets, 80-90% confidence scores
- **Documentation**: `docs/CONTENT_GENERATOR_PHASE2B.md`
- **AI Model**: Gemini 2.0 Flash working

---

## 📊 Test Data Available

### Files in ~/Downloads/
Keep these for Phase 3 testing:
- `test_phase1_phase2a_outliers.json` - 10 outliers with full metadata
- `hook_analysis_test.json` - 3 analyzed hooks with adaptation notes
- `PHASE1_PHASE2A_TEST_RESULTS.md` - Comprehensive test analysis
- `SESSION_SUMMARY_CONTENT_GENERATOR.md` - Full session summary

Can delete:
- `outliers_phase1_verification.json` (duplicate)
- `outliers_test.json` (old test)
- `outliers_phase1_output.log` (old log)
- `PHASE1_VERIFICATION_SUMMARY.md` (superseded)

---

## 🎯 Phase 3 Objectives

Build content generation system that:

1. **Reads hook analysis** from Phase 2B JSON
2. **Generates long-form content** in multiple formats:
   - Twitter threads (5-10 tweets) - PRIORITY 1
   - Blog posts (500-1500 words) - PRIORITY 2
   - LinkedIn articles - PRIORITY 3
   - Newsletter sections - PRIORITY 4

3. **Saves to database** with new table `generated_content`
4. **Exports** in multiple formats (markdown, JSON, CSV)

---

## 📋 Implementation Checklist

### Phase 3A: Core Generation (Priority)
- [ ] Create database migration for `generated_content` table
- [ ] Create `ContentGenerator` base class
- [ ] Implement `ThreadGenerator` (5-10 tweets)
- [ ] Implement `BlogGenerator` (500-1500 words)
- [ ] Build AI prompts with hook adaptation
- [ ] Save generated content to database
- [ ] CLI command: `twitter generate-content`

### Phase 3B: Export & Review
- [ ] Export to Markdown
- [ ] Export to JSON
- [ ] Export to CSV
- [ ] CLI command: `twitter export-content`
- [ ] Status lifecycle (pending → reviewed → published)

### Phase 3C: Testing & Polish
- [ ] Test thread generation
- [ ] Test blog generation
- [ ] Cost tracking
- [ ] Documentation
- [ ] End-to-end workflow test

---

## 🗂️ Database Schema

Run this migration in Phase 3A:

```sql
-- migrations/2025-XX-XX_add_generated_content.sql

CREATE TABLE generated_content (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL REFERENCES projects(id),

    -- Source
    source_tweet_id VARCHAR REFERENCES posts(post_id),

    -- Hook analysis
    hook_type VARCHAR,
    emotional_trigger VARCHAR,
    content_pattern VARCHAR,
    hook_explanation TEXT,

    -- Generated content
    content_type VARCHAR,  -- 'thread', 'blog', 'linkedin', 'newsletter'
    content_title TEXT,
    content_body TEXT,
    content_metadata JSONB,

    -- Adaptation
    adaptation_notes TEXT,
    project_context TEXT,

    -- Tracking
    api_cost_usd NUMERIC(10, 8),
    model_used VARCHAR DEFAULT 'gemini-2.0-flash-exp',
    status VARCHAR DEFAULT 'pending',

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    published_at TIMESTAMPTZ
);

CREATE INDEX idx_generated_content_project ON generated_content(project_id);
CREATE INDEX idx_generated_content_source ON generated_content(source_tweet_id);
CREATE INDEX idx_generated_content_status ON generated_content(status);
CREATE INDEX idx_generated_content_type ON generated_content(content_type);
```

---

## 🔧 Key Files to Create

```
viraltracker/generation/
├── content_generator.py       # Base class
├── thread_generator.py        # Twitter threads
├── blog_generator.py          # Blog posts
└── content_exporter.py        # Export functionality

viraltracker/cli/
└── twitter.py                 # Add generate-content, export-content commands

migrations/
└── 2025-XX-XX_add_generated_content.sql
```

---

## 💡 Design Patterns to Use

### 1. Generator Pattern

```python
class ContentGenerator:
    """Base class for content generators"""

    def generate(self, hook_analysis, project_context):
        raise NotImplementedError

    def save_to_db(self, content, project_id, source_tweet_id):
        # Common save logic
        pass

class ThreadGenerator(ContentGenerator):
    def generate(self, hook_analysis, project_context):
        # Thread-specific generation
        return thread_content
```

### 2. Prompt Template Pattern

```python
def build_prompt(hook_analysis, project_context, content_type):
    template = TEMPLATES[content_type]
    return template.format(
        tweet_text=hook_analysis.tweet_text,
        hook_type=hook_analysis.hook_type,
        emotional_trigger=hook_analysis.emotional_trigger,
        adaptation_notes=hook_analysis.adaptation_notes,
        project_description=project_context.description,
        ...
    )
```

### 3. Strategy Pattern for Export

```python
EXPORTERS = {
    'markdown': MarkdownExporter(),
    'json': JSONExporter(),
    'csv': CSVExporter(),
    'thread': ThreadFormatExporter()
}

def export(content, format):
    return EXPORTERS[format].export(content)
```

---

## 📝 Example AI Prompts

### Thread Generation Prompt

```
You are an expert content creator adapting viral Twitter hooks.

SOURCE TWEET (went viral):
{tweet_text}

HOOK ANALYSIS:
- Type: {hook_type}
- Emotional trigger: {emotional_trigger}
- Why it works: {hook_explanation}
- How to adapt: {adaptation_notes}

PROJECT CONTEXT:
- Product: {product_name}
- Description: {product_description}
- Target audience: {target_audience}
- Key benefits: {key_benefits}

TASK:
Create a Twitter thread (5-10 tweets) that:
1. Opens with an adapted version of this viral hook
2. Maintains the {emotional_trigger} emotional trigger
3. Expands the core idea with insights relevant to {product_name}
4. Provides value to {target_audience}
5. Ends with a CTA for {product_name}

REQUIREMENTS:
- Each tweet must be ≤280 characters
- Use simple, conversational language
- Include 1-2 emojis per tweet (optional)
- Thread should flow naturally
- CTA should be subtle, not salesy

OUTPUT FORMAT (JSON):
{{
  "thread": [
    {{"tweet_number": 1, "text": "Adapted hook tweet..."}},
    {{"tweet_number": 2, "text": "Expansion..."}},
    ...
  ],
  "hook_adaptation_explanation": "How you adapted the hook",
  "key_insights": ["insight 1", "insight 2", "insight 3"]
}}
```

---

## 🧪 Testing Strategy

### Unit Tests
- Test each generator independently
- Mock AI responses
- Validate output format

### Integration Tests
- Test full pipeline: outliers → hooks → content
- Test database save/retrieve
- Test export functions

### Manual Testing
```bash
# 1. Generate from test hooks
vt twitter generate-content \
  --input-json ~/Downloads/hook_analysis_test.json \
  --project yakety-pack-instagram \
  --content-types thread \
  --max-content 1

# 2. Verify in database
# Check generated_content table

# 3. Export and review
vt twitter export-content \
  --project yakety-pack-instagram \
  --content-type thread \
  --format markdown \
  --out test_thread.md
```

---

## ⚠️ Common Pitfalls to Avoid

### 1. AI Output Parsing
- **Issue**: Gemini may not return perfect JSON
- **Solution**: Wrap in try/catch, handle markdown code blocks

### 2. Token Limits
- **Issue**: Long prompts may exceed limits
- **Solution**: Keep prompts concise, truncate long tweets

### 3. Cost Tracking
- **Issue**: Forgetting to track API costs
- **Solution**: Log every API call with cost

### 4. Content Quality
- **Issue**: Generic or off-topic output
- **Solution**: Iterate on prompts, add examples, use project context

---

## 📚 Reference Documentation

- **Phase 3 Plan**: `docs/CONTENT_GENERATOR_PHASE3_PLAN.md`
- **Phase 1 Docs**: `docs/CONTENT_GENERATOR_PHASE1.md`
- **Phase 2B Docs**: `docs/CONTENT_GENERATOR_PHASE2B.md`
- **Master README**: `docs/CONTENT_GENERATOR_README.md`

---

## 🚀 Quick Start for Phase 3

```bash
# 1. Checkout branch
git checkout feature/content-generator-v1
git pull origin feature/content-generator-v1

# 2. Review existing code
cat viraltracker/generation/hook_analyzer.py  # Model for structure
cat viraltracker/cli/twitter.py | grep -A 50 "analyze-hooks"  # CLI pattern

# 3. Test existing phases
vt twitter find-outliers -p yakety-pack-instagram --days-back 30 --text-only --export-json test.json
vt twitter analyze-hooks --input-json test.json --output-json hooks.json --limit 3

# 4. Start Phase 3A
# - Create content_generator.py
# - Create thread_generator.py
# - Add database migration
# - Add CLI command
```

---

## 💰 Cost Estimates

### Per Content Piece (Gemini 2.0 Flash)
- Thread (5-10 tweets): ~$0.005-0.010
- Blog post (500-1500 words): ~$0.015-0.025
- LinkedIn article: ~$0.010-0.020

### Batch Costs
- 10 threads: ~$0.10
- 10 blog posts: ~$0.20
- 10 of each: ~$0.30

**Total for MVP**: <$1 for testing, <$5 for production batch

---

## ✅ Success Criteria

Phase 3 is complete when:

1. **Thread generation works**
   - Generates 5-10 tweet thread
   - Adapts hook from Phase 2B
   - Includes CTA
   - Saves to database

2. **Blog generation works**
   - Generates 500-1500 word post
   - Uses markdown format
   - Includes title, sections, conclusion
   - Saves to database

3. **Export works**
   - Can export to markdown, JSON, CSV
   - Includes all metadata
   - Status tracking works

4. **End-to-end pipeline works**
   - Find outliers → Analyze hooks → Generate content → Export
   - All commands work together
   - Documentation complete

---

## 🎯 Recommended Approach

### Day 1: Core Thread Generator
1. Create database migration
2. Create `ContentGenerator` base class
3. Implement `ThreadGenerator`
4. Add CLI command (basic)
5. Test with 1 hook

### Day 2: Blog Generator & Database
1. Implement `BlogGenerator`
2. Database save functionality
3. Test with 3-5 hooks
4. Cost tracking

### Day 3: Export & Polish
1. Export to markdown, JSON
2. Status lifecycle
3. CLI polish (progress bars, better output)
4. Documentation

### Day 4: Testing & Docs
1. End-to-end testing
2. Update all docs
3. Create examples
4. Push to GitHub

---

## 📞 Questions to Consider

Before starting Phase 3:

1. **Should we support custom templates?**
   - User-defined prompt templates?
   - Or stick with built-in templates?

2. **How much human review before publishing?**
   - Auto-publish to drafts?
   - Or always require manual review?

3. **What project context format?**
   - Use existing finder.yml?
   - Or separate content-generator.yml?

4. **Batch processing strategy?**
   - Process all at once?
   - Or one-by-one with user confirmation?

---

**Ready to build Phase 3!** 🚀

All foundations are in place. Time to generate some content!
