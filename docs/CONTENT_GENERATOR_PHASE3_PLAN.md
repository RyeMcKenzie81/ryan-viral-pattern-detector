# Content Generator - Phase 3 Plan: Content Generation

**Status**: 📋 Planning
**Depends On**: Phase 1 (Outlier Detection) ✅, Phase 2A (Media Filtering) ✅, Phase 2B (Hook Analysis) ✅

---

## Overview

Phase 3 will generate long-form content from analyzed outlier tweets, adapting their viral hooks for different content formats.

**Input**: Hook analysis from Phase 2B
**Output**: Long-form content (threads, blogs, articles) saved to database

---

## Goals

1. **Automate content creation** from viral tweet hooks
2. **Multiple content formats** (thread, blog, LinkedIn, newsletter)
3. **Database storage** for review and publishing
4. **Export functionality** for different platforms

---

## Content Types

### 1. Twitter Thread (Priority 1)
- **Length**: 5-10 tweets
- **Format**: Series of connected tweets
- **Hook adaptation**: First tweet = adapted hook, rest = expansion
- **CTA**: Last tweet with project link

### 2. Blog Post (Priority 2)
- **Length**: 500-1500 words
- **Format**: Title, intro (hook), body (3-5 sections), conclusion (CTA)
- **Hook adaptation**: Intro paragraph uses adapted hook
- **Structure**: Markdown with headers

### 3. LinkedIn Article (Priority 3)
- **Length**: 300-800 words
- **Format**: Professional tone, shorter sections
- **Hook adaptation**: Opening paragraph uses adapted hook
- **CTA**: Subtle, professional

### 4. Newsletter Section (Priority 4)
- **Length**: 200-400 words
- **Format**: Standalone section for weekly newsletter
- **Hook adaptation**: Opening sentence uses adapted hook
- **CTA**: Link to full blog post or product

---

## Database Schema

### New Table: `generated_content`

```sql
CREATE TABLE generated_content (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL REFERENCES projects(id),

    -- Source
    source_tweet_id VARCHAR REFERENCES posts(post_id),

    -- Hook analysis (from Phase 2B)
    hook_type VARCHAR,              -- From hook analysis
    emotional_trigger VARCHAR,      -- From hook analysis
    content_pattern VARCHAR,        -- From hook analysis
    hook_explanation TEXT,          -- Why it works

    -- Generated content
    content_type VARCHAR,           -- 'thread', 'blog', 'linkedin', 'newsletter'
    content_title TEXT,
    content_body TEXT,
    content_metadata JSONB,         -- Format-specific data

    -- Adaptation strategy
    adaptation_notes TEXT,          -- How hook was adapted
    project_context TEXT,           -- Project-specific additions

    -- AI tracking
    api_cost_usd NUMERIC(10, 8),
    model_used VARCHAR DEFAULT 'gemini-2.0-flash-exp',
    generation_timestamp TIMESTAMPTZ DEFAULT NOW(),

    -- Status
    status VARCHAR DEFAULT 'pending',  -- pending, reviewed, exported, published

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

## Architecture

### ContentGenerator Class

```python
class ContentGenerator:
    """
    Generates long-form content from hook analysis

    Methods:
    - generate_thread(hook_analysis, project_context)
    - generate_blog(hook_analysis, project_context)
    - generate_linkedin(hook_analysis, project_context)
    - generate_newsletter(hook_analysis, project_context)
    - save_to_db(generated_content)
    - export_to_format(content, format)
    """
```

### Generation Flow

```
1. Load hook analysis (from Phase 2B JSON)
   ↓
2. Load project context (from finder.yml or config)
   ↓
3. Build AI prompt based on:
   - Hook type (determines template)
   - Emotional trigger (maintain tone)
   - Adaptation notes (expansion strategy)
   - Project context (product info)
   ↓
4. Generate content via Gemini
   ↓
5. Parse and validate output
   ↓
6. Save to database
   ↓
7. Export to desired format
```

---

## AI Prompts

### Thread Generation Template

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
{project_description}
{product_benefits}
{target_audience}

TASK:
Create a Twitter thread (5-10 tweets) that:
1. Adapts this viral hook for the project
2. Maintains the emotional trigger ({emotional_trigger})
3. Expands the core idea with project-relevant insights
4. Includes a CTA in the last tweet

OUTPUT FORMAT (JSON):
{
  "thread": [
    {"tweet_number": 1, "text": "First tweet (hook)..."},
    {"tweet_number": 2, "text": "Expansion..."},
    ...
  ],
  "hook_adaptation": "How you adapted the hook",
  "key_insights": ["insight 1", "insight 2"]
}
```

### Blog Post Generation Template

```
You are an expert content writer adapting viral hooks for blog posts.

[Similar structure, different output format]

OUTPUT FORMAT (JSON):
{
  "title": "Compelling blog title",
  "intro": "Opening paragraph with adapted hook",
  "sections": [
    {"heading": "H2", "content": "..."},
    {"heading": "H2", "content": "..."}
  ],
  "conclusion": "Closing with CTA",
  "seo_keywords": ["keyword1", "keyword2"]
}
```

---

## CLI Commands

### Command 1: Generate Content

```bash
vt twitter generate-content \
  --input-json hook_analysis.json \
  --project my-project \
  --content-types thread,blog \
  --max-content 10 \
  --output-dir ~/content/
```

**Options**:
- `--input-json`: Hook analysis from Phase 2B
- `--project`: Project slug (for context)
- `--content-types`: Comma-separated (thread, blog, linkedin, newsletter)
- `--max-content`: Limit to top N hooks
- `--output-dir`: Where to save generated content

### Command 2: Export Content

```bash
vt twitter export-content \
  --project my-project \
  --content-type thread \
  --format markdown \
  --out ~/Downloads/threads.md
```

**Formats**:
- `markdown` - For blogs/documentation
- `json` - For automation
- `csv` - For spreadsheet review
- `thread` - Twitter thread format (numbered)

---

## Example Workflow

```bash
# Full pipeline
# 1. Find outliers (Phase 1 + 2A)
vt twitter find-outliers -p yakety-pack-instagram \
  --days-back 30 \
  --min-views 10000 \
  --text-only \
  --method percentile \
  --threshold 5.0 \
  --export-json outliers.json

# 2. Analyze hooks (Phase 2B)
vt twitter analyze-hooks \
  --input-json outliers.json \
  --output-json hooks.json \
  --limit 10

# 3. Generate content (Phase 3)
vt twitter generate-content \
  --input-json hooks.json \
  --project yakety-pack-instagram \
  --content-types thread,blog \
  --max-content 5

# 4. Review in database
# Check generated_content table

# 5. Export for publishing
vt twitter export-content \
  --project yakety-pack-instagram \
  --content-type thread \
  --format markdown \
  --out threads.md
```

---

## Implementation Phases

### Phase 3A: Core Generation (Week 1)
- [ ] Create `ContentGenerator` class
- [ ] Implement thread generation
- [ ] Implement blog generation
- [ ] Database table and migration
- [ ] Save to database functionality

### Phase 3B: Export & Review (Week 2)
- [ ] Export to markdown
- [ ] Export to JSON
- [ ] Export to CSV
- [ ] CLI command: `export-content`
- [ ] Status lifecycle (pending → reviewed → published)

### Phase 3C: Polish & Test (Week 3)
- [ ] LinkedIn article generation
- [ ] Newsletter section generation
- [ ] Batch processing optimization
- [ ] Cost tracking
- [ ] End-to-end testing

---

## Success Metrics

### Quality
- **Coherence**: Generated content flows naturally
- **Relevance**: Stays on topic with project
- **Tone**: Maintains emotional trigger from source
- **CTA**: Includes appropriate call-to-action

### Performance
- **Speed**: <15 seconds per piece of content
- **Cost**: <$0.02 per blog post, <$0.01 per thread
- **Success rate**: >90% valid output

### User Value
- **Time saved**: 30+ minutes per content piece
- **Quality**: Publishable with minor edits
- **Variety**: Multiple formats from one hook

---

## Risks & Mitigation

### Risk 1: AI Output Quality
- **Risk**: Generated content too generic or off-topic
- **Mitigation**:
  - Detailed prompts with examples
  - Project context in every prompt
  - Human review before publishing
  - Iteration on poor outputs

### Risk 2: API Costs
- **Risk**: Expensive at scale (1000 pieces = $20+)
- **Mitigation**:
  - Use Gemini Flash (cheapest)
  - Limit to top outliers only
  - Cache and reuse generations
  - Cost tracking built-in

### Risk 3: Content Duplication
- **Risk**: Multiple pieces too similar
- **Mitigation**:
  - Vary templates per hook type
  - Add randomization to prompts
  - Track similarity scores
  - Human curation

---

## Future Enhancements

### V1.1: Batch Processing
- Generate multiple pieces in parallel
- Async API calls (5-10 concurrent)
- Progress tracking

### V1.2: Template System
- User-defined templates
- A/B test different formats
- Template library

### V1.3: Auto-Publishing
- Direct posting to Twitter
- WordPress integration
- LinkedIn API integration
- Newsletter platform APIs

### V1.4: Quality Scoring
- AI-powered quality assessment
- Readability scoring
- SEO optimization
- Engagement prediction

---

## Dependencies

- Phases 1, 2A, 2B (complete ✅)
- Google Gemini API
- Project finder.yml (for context)
- Database migration

---

## Estimated Effort

- **Phase 3A**: 6-8 hours (core generation)
- **Phase 3B**: 4-6 hours (export & review)
- **Phase 3C**: 4-6 hours (polish & test)
- **Total**: ~16-20 hours

---

## Ready to Start?

Prerequisites:
1. ✅ Phase 1 complete (outlier detection)
2. ✅ Phase 2A complete (media filtering)
3. ✅ Phase 2B complete (hook analysis)
4. ✅ All tests passing
5. ✅ Documentation complete

**Status**: Ready to begin Phase 3! 🚀

Start with Phase 3A: Core thread and blog generation.
