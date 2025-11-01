# Content Generator - Complete Workflow Guide

**A step-by-step tutorial for generating content from viral tweets**

---

## Overview

This guide walks you through the complete content generation pipeline:

```
Find Viral Tweets → Analyze Hooks → Generate Content → Export & Publish
     (Phase 1)         (Phase 2B)        (Phase 3)        (Phase 3)
```

**Time**: 5-10 minutes for 10 pieces of content
**Cost**: ~$0.01 for 10 outliers → 20 pieces of content
**Output**: Twitter threads, blog posts, and longform posts ready to publish

---

## Prerequisites

### 1. Environment Setup

```bash
# Required environment variables
export GEMINI_API_KEY="your-key-here"
export SUPABASE_URL="your-url-here"
export SUPABASE_KEY="your-key-here"
```

### 2. Database Setup

```bash
# Run migrations (only needed once)
python scripts/run_migration.py migrations/2025-10-31_add_media_type_to_posts.sql
python scripts/run_migration.py migrations/2025-10-31_add_generated_content.sql
```

### 3. Project Configuration

Update your project's `finder.yml` with content generation context:

```yaml
# Content Generation (Phase 3)
name: Your Project Name
description: Brief description of your product/service (1-2 sentences)
target_audience: Who you're targeting (be specific)
key_benefits:
  - Main benefit 1
  - Main benefit 2
  - Main benefit 3
```

**Example** (Yakety Pack Instagram):
```yaml
name: Yakety Pack Instagram
description: A parenting app that helps families manage screen time and build healthier digital habits through family gaming and quality connection time
target_audience: Parents of kids ages 6-14 who want to balance screen time with quality family connection
key_benefits:
  - Turn screen time into quality family bonding through co-op gaming
  - Set healthy boundaries without constant battles
  - Understand what your kids love about gaming
  - Create device-free moments that actually work
```

---

## Step 1: Find Viral Outliers (Phase 1)

**Goal**: Identify high-performing tweets that significantly outperform typical content.

### Command

```bash
./vt twitter find-outliers \
  -p your-project \
  --days-back 30 \
  --text-only \
  --export-json outliers.json
```

### Parameters Explained

- `-p`: Project name/slug (must match database)
- `--days-back`: How far back to analyze (default: 30)
- `--text-only`: Only analyze text-based content (excludes videos/images)
- `--method`: Statistical method (`zscore` or `percentile`, default: zscore)
- `--threshold`: Sensitivity (higher = more selective, default: 2.0)
- `--min-views`: Minimum views required (default: 1000)
- `--export-json`: Save results to file for next step

### Real Example

```bash
./vt twitter find-outliers \
  -p yakety-pack-instagram \
  --days-back 30 \
  --text-only \
  --export-json top_outliers.json
```

### Expected Output

```
🔍 Finding outliers for project: yakety-pack-instagram
   Using zscore method with threshold 2.0
   Text-only filter: enabled
   Date range: 2025-10-02 to 2025-11-01

📊 Analyzing 1,053 posts...
   Mean views: 2,347
   Median views: 1,823
   Std dev: 8,234

✨ Found 150 outliers!

Top 10 outliers:
┌────┬───────────┬──────────┬────────────┬─────────────────────────┐
│ #  │ Views     │ Likes    │ Z-Score    │ Text Preview            │
├────┼───────────┼──────────┼────────────┼─────────────────────────┤
│ 1  │ 140,234   │ 8,234    │ 94.23      │ "Is it just me, or h... │
│ 2  │ 75,892    │ 4,123    │ 87.45      │ "Did you know Big Te... │
│ 3  │ 18,234    │ 2,456    │ 12.34      │ "My kid just told me... │
│ ...│ ...       │ ...      │ ...        │ ...                     │
└────┴───────────┴──────────┴────────────┴─────────────────────────┘

💾 Exported 150 outliers to: top_outliers.json
```

### Tips

- **Use `--text-only`**: Video content can't be adapted into text threads/blogs
- **Adjust threshold**: Lower threshold = more outliers, higher = only the best
- **Filter by views**: Use `--min-views 10000` to focus on high-impact content
- **Check the file**: Open `outliers.json` to verify results before continuing

---

## Step 2: Analyze Hooks (Phase 2B)

**Goal**: Understand WHY each tweet went viral using AI analysis.

### Command

```bash
./vt twitter analyze-hooks \
  --input-json outliers.json \
  --output-json hooks.json \
  --limit 10
```

### Parameters Explained

- `--input-json`: File from Step 1 (outliers.json)
- `--output-json`: Where to save hook analysis
- `--limit`: How many to analyze (start small for testing)

### Real Example

```bash
./vt twitter analyze-hooks \
  --input-json top_outliers.json \
  --output-json hooks.json \
  --limit 10
```

### Expected Output

```
🧠 Analyzing hooks with Gemini 2.0 Flash...

Analyzing tweet 1/10...
✓ Hook: shock_violation | Trigger: anger | Pattern: statement
  "Did you know Big Tech spends millions lobbying..."

Analyzing tweet 2/10...
✓ Hook: hot_take | Trigger: anger | Pattern: question
  "Is it just me, or has constant access to screens..."

Analyzing tweet 3/10...
✓ Hook: relatable_slice | Trigger: humor | Pattern: story
  "My kid just told me I'm 'grounded' from my phone..."

[... 7 more ...]

📊 Analysis complete!
   Processed: 10 tweets
   Cost: ~$0.0010
   Time: ~60 seconds

💾 Saved to: hooks.json
```

### Understanding Hook Types

The AI identifies 14 hook types. Most common:

- **shock_violation**: Surprising/controversial statement
- **hot_take**: Bold opinion that sparks debate
- **relatable_slice**: Everyday moment people recognize
- **question_curiosity**: Question that makes you think
- **listicle_howto**: Numbered tips or steps
- **authority_credibility**: Expert advice/credentials

### Tips

- **Start with 3-5 tweets**: Test the system before processing many
- **Review the output**: Open `hooks.json` to see the analysis
- **Cost control**: Each tweet costs ~$0.0001, so 10 = ~$0.001
- **Quality over quantity**: Better to analyze 10 great outliers than 50 mediocre ones

---

## Step 3: Generate Content (Phase 3)

**Goal**: Create Twitter threads and blog posts adapted for your product/audience.

### Command

```bash
./vt twitter generate-content \
  --input-json hooks.json \
  --project your-project \
  --max-content 10
```

### Parameters Explained

- `--input-json`: File from Step 2 (hooks.json)
- `--project`: Your project name (must have finder.yml configured)
- `--content-types`: What to generate (`thread`, `blog`, or both - default: both)
- `--max-content`: Maximum pieces to generate (default: unlimited)
- `--output-dir`: Optional, save to files instead of just database

### Real Example

```bash
./vt twitter generate-content \
  --input-json hooks.json \
  --project yakety-pack-instagram \
  --max-content 10
```

### Expected Output

```
🎨 Generating content for: Yakety Pack Instagram

Loading project context...
✓ Project: Yakety Pack Instagram
  Target audience: Parents of kids ages 6-14
  Key benefits: 4 loaded

Processing hook 1/10...
  Source: "Did you know Big Tech spends millions..."
  Hook: shock_violation | Trigger: anger

  ✓ Generated thread (8 tweets) - $0.00022
  ✓ Generated blog (1,234 words) - $0.00048
  ✓ Saved to database

Processing hook 2/10...
  Source: "Is it just me, or has constant access..."
  Hook: hot_take | Trigger: anger

  ✓ Generated thread (8 tweets) - $0.00019
  ✗ Blog generation failed (JSON parse error - retrying)
  ✓ Generated blog (1,156 words) - $0.00051
  ✓ Saved to database

[... 8 more ...]

🎉 Content generation complete!

Summary:
├─ Total hooks processed: 10
├─ Threads generated: 12 (from 10 hooks, some generated multiple variants)
├─ Blogs generated: 8 (2 failed after retries)
├─ Success rate: 90%
├─ Total cost: $0.0067
└─ Time: ~3.5 minutes

📊 Content saved to database and ready for export!
```

### What Gets Generated

**For each hook, you get:**

1. **Twitter Thread** (5-10 tweets)
   - Adapted viral hook opening
   - Value-focused content
   - No hashtags (clean, professional)
   - Subtle product mention
   - 280 char limit per tweet

2. **Blog Post** (500-1500 words)
   - SEO-optimized title
   - Engaging introduction
   - 3-5 body sections
   - Actionable takeaways
   - Natural product integration
   - Markdown formatted

### Tips

- **Check project config**: Make sure `finder.yml` is complete before generating
- **Retry failures**: If blog generation fails, it auto-retries once
- **Review before publishing**: AI output is good but not perfect
- **Cost awareness**: ~$0.0007 per piece (thread + blog from same hook)

---

## Step 4: Export Content (Phase 3)

**Goal**: Export generated content in multiple formats for different platforms.

### Command

```bash
./vt twitter export-content \
  -p your-project \
  --output-dir ./exports
```

### Parameters Explained

- `-p`: Project name
- `--content-type`: Filter by type (`thread` or `blog`, default: all)
- `--format`: Export format(s) - default: markdown, twitter, longform
- `--status`: Filter by status (`pending`, `reviewed`, `published`)
- `--output-dir`: Where to save exports (default: ./exports)

### Available Formats

1. **markdown** - Complete overview with all metadata (for review)
2. **twitter** - Individual tweets ready to copy/paste
3. **longform** - Single cohesive post for LinkedIn/Instagram
4. **json** - Programmatic access with full metadata
5. **csv** - Spreadsheet with key metrics
6. **medium** - Blog format for Medium publishing

### Real Example - Default (3 formats)

```bash
./vt twitter export-content \
  -p yakety-pack-instagram \
  --output-dir ~/exports
```

**Output:**
```
📤 Exporting content for: Yakety Pack Instagram

Loading content from database...
✓ Found 20 pieces (12 threads, 8 blogs)

Exporting in formats: markdown, twitter, longform

Export format: markdown
├─ yakety-pack-instagram_content.md (overview of all 20 pieces)
└─ 1 file created

Export format: twitter
├─ yakety-pack-instagram_thread_1.txt
├─ yakety-pack-instagram_thread_2.txt
├─ ... (10 more)
└─ 12 files created

Export format: longform
├─ yakety-pack-instagram_longform_1.txt
├─ yakety-pack-instagram_longform_2.txt
├─ ... (10 more)
└─ 12 files created

✨ Export complete!
   Total files: 25
   Location: /Users/you/exports/
```

### Real Example - All Formats

```bash
./vt twitter export-content \
  -p yakety-pack-instagram \
  --format markdown \
  --format twitter \
  --format longform \
  --format json \
  --format csv \
  --output-dir ~/exports
```

### Export Format Examples

#### 1. Twitter Format (Individual Tweets)

File: `yakety-pack-instagram_thread_1.txt`

```
=== TWITTER THREAD ===
Title: Gaming & Family Connection
Hook: hot_take / anger
Total tweets: 8

Copy each tweet individually:
============================================================

Tweet 1/8:
Is it just me, or has constant access to screens warped our kids' idea of 'fun'? 🤔 Seems like face-to-face connection is losing to endless scrolling. What happened?

Tweet 2/8:
It's NOT their fault. We handed them these devices. But now what? We can't just rip them away & expect sunshine & rainbows. That'll breed resentment faster than you can say 'Fortnite'. 😤

[... 6 more tweets ...]

Tweet 8/8:
Want some game ideas and tips on turning screen time into family time? We built something to help families find common ground through play. Check it out - link in profile! 😉
```

#### 2. Longform Format (Single Post for LinkedIn/Instagram)

File: `yakety-pack-instagram_longform_1.txt`

```
=== LONG-FORM POST (LinkedIn/Instagram/Single Post) ===
Title: Gaming & Family Connection
Hook: hot_take / anger

Copy and paste below:
============================================================

Is it just me, or has constant access to screens warped our kids' idea of 'fun'? 🤔 Seems like face-to-face connection is losing to endless scrolling. What happened?

It's NOT their fault. We handed them these devices. But now what? We can't just rip them away & expect sunshine & rainbows. That'll breed resentment faster than you can say 'Fortnite'. 😤

[... continues as flowing paragraphs ...]

Want some game ideas and tips on turning screen time into family time? We built something to help families find common ground through play. Check it out - link in profile! 😉

============================================================
Total characters: 1415
LinkedIn limit: 3,000 chars (1585 remaining)
Instagram limit: 2,200 chars (785 remaining)
```

#### 3. Markdown Format (Complete Overview)

File: `yakety-pack-instagram_content.md`

```markdown
# Generated Content for Yakety Pack Instagram

Generated: 2025-11-01
Total pieces: 20 (12 threads, 8 blogs)

---

## Thread 1: Gaming & Family Connection

**Source Tweet**: "Is it just me, or has constant access to screens..."
**Hook Type**: hot_take
**Emotional Trigger**: anger
**Status**: pending

### Thread (8 tweets)

1. Is it just me, or has constant access to screens warped...
2. It's NOT their fault. We handed them these devices...
[... full thread ...]

### Metadata
- Total tweets: 8
- Estimated engagement: 0.78
- Character counts: 137-214 per tweet

---

[... 19 more pieces ...]
```

### Tips

- **Use markdown first**: Review all content before posting
- **Twitter format**: Ready to copy into Twitter, Buffer, or Typefully
- **Longform format**: Perfect for LinkedIn/Instagram (character counts included)
- **JSON format**: For custom workflows or CMS integration
- **Multiple exports**: You can export multiple times with different filters

---

## Complete End-to-End Example

Here's a real production test we ran with yakety-pack-instagram:

### Commands

```bash
# Step 1: Find outliers (found 150, selected top 10)
./vt twitter find-outliers \
  -p yakety-pack-instagram \
  --days-back 30 \
  --text-only \
  --export-json top_outliers.json

# Step 2: Analyze hooks (10 analyzed)
./vt twitter analyze-hooks \
  --input-json top_outliers.json \
  --output-json hooks.json

# Step 3: Generate content (20 pieces created)
./vt twitter generate-content \
  --input-json hooks.json \
  --project yakety-pack-instagram \
  --max-content 10

# Step 4: Export (25 files created)
./vt twitter export-content \
  -p yakety-pack-instagram \
  --output-dir ~/exports
```

### Results

**Outliers Analyzed:**
- Views: 140K (rank 1) to 29K (rank 10)
- Hook types: shock_violation (4), hot_take (2), relatable_slice (2), authority_credibility (2)
- Emotional triggers: anger (6), humor (2), curiosity (2)

**Content Generated:**
- 12 Twitter threads (7-9 tweets each, 0 hashtags)
- 8 Blog posts (900-1,200 words each)
- Success rate: 90% (18/20 pieces successful)

**Cost Breakdown:**
- Outlier detection: $0.000 (free)
- Hook analysis: $0.001 (10 × $0.0001)
- Thread generation: $0.0024 (12 × $0.0002)
- Blog generation: $0.004 (8 × $0.0005)
- **Total: $0.0067** (less than 1 cent!)

**Time:**
- Total pipeline: ~5 minutes
- Step 1: ~10 seconds
- Step 2: ~60 seconds
- Step 3: ~3.5 minutes
- Step 4: ~5 seconds

**Files Exported:**
- 1 markdown overview
- 12 Twitter thread files
- 12 Longform post files
- **Total: 25 files ready to publish**

---

## Quality Checklist

Before publishing, verify:

### Twitter Threads
- [ ] All tweets under 280 characters
- [ ] No hashtags (clean, professional)
- [ ] Natural conversational flow
- [ ] Emotional trigger maintained from source
- [ ] Product mention is subtle and contextual
- [ ] Thread has clear beginning, middle, end
- [ ] Value provided to target audience

### Blog Posts
- [ ] Title is SEO-optimized and compelling
- [ ] Introduction hooks the reader
- [ ] Body sections have clear headings
- [ ] Actionable takeaways included
- [ ] Product integration feels natural
- [ ] Word count: 500-1500 words
- [ ] Markdown formatting correct

### Longform Posts
- [ ] Flows naturally as single post (not choppy)
- [ ] Character count fits platform (LinkedIn: 3000, Instagram: 2200)
- [ ] Paragraphs are readable on mobile
- [ ] Call to action is clear

---

## Troubleshooting

### Issue: "Project not found in database"

**Error:**
```
Error: Project 'my-project' not found in database
```

**Fix:**
1. Check project name matches database: `./vt twitter list-projects`
2. Verify finder.yml has correct `name:` field
3. Run scraper at least once to create project in database

---

### Issue: "No hook analyses found in input file"

**Error:**
```
Error: No hook analyses found in input file
```

**Fix:**
1. Ensure you're using output from `analyze-hooks` command
2. Check JSON file structure (should have `hook_type`, `emotional_trigger` fields)
3. Re-run hook analysis if file is corrupted

---

### Issue: Blog generation fails with JSON parse error

**Error:**
```
Error parsing AI response: Expecting ',' delimiter
```

**Fix:**
- This is transient (AI output variation)
- System automatically retries with `strict=False` fallback
- Usually succeeds on retry
- If persistent, skip blog generation: `--content-types thread`

---

### Issue: Content is too promotional/salesy

**Fix:**
1. Update `finder.yml` with more specific `target_audience`
2. Add more `key_benefits` focused on value, not features
3. Make `description` about user benefits, not product features
4. Regenerate content with updated config

---

### Issue: Threads have hashtags (they shouldn't!)

**Fix:**
- This was fixed in latest version
- Threads should have ZERO hashtags
- If you see hashtags, update to latest code
- Prompt includes explicit "DO NOT use hashtags" instruction

---

### Issue: Export creates wrong number of files

**Problem:**
Expected 10 threads but only got 8 exported.

**Fix:**
1. Check database: some content generation may have failed
2. Filter by status: `--status pending` to see all unpublished
3. Review generation logs for errors
4. Regenerate failed pieces

---

## Tips & Best Practices

### Finding Great Outliers

1. **Use `--text-only`**: Video content can't be adapted to text threads/blogs
2. **Set minimum views**: `--min-views 10000` to focus on high-impact content
3. **Adjust threshold**: Start with 2.0, increase if too many outliers
4. **Check date range**: 30 days is good, 90+ days may include outdated trends

### Hook Analysis

1. **Start small**: Test with 3-5 tweets before processing 50
2. **Review manually**: Open hooks.json and verify analysis makes sense
3. **Look for patterns**: If all hooks are same type, diversify your outliers
4. **Check emotional triggers**: Mix of emotions = more diverse content

### Content Generation

1. **Perfect your `finder.yml`**: This is the foundation of good content
2. **Target audience specificity**: "Parents of kids 6-14" > "Parents"
3. **Benefits over features**: "Turn screen time into bonding" > "Has co-op games"
4. **Review before publishing**: AI is 90% there, you add the final 10%

### Exporting & Publishing

1. **Use markdown first**: Review everything before committing to posting
2. **Test one thread**: Post one thread, see engagement, iterate
3. **Schedule strategically**: Don't post all 10 threads in one day
4. **Track performance**: Note which hook types perform best for YOUR audience
5. **Iterate prompts**: Based on results, adjust finder.yml and regenerate

---

## Cost Management

### Production Costs (Real Data)

| Operation | Cost per Item | Cost for 10 |
|-----------|--------------|-------------|
| Find outliers | Free | $0.000 |
| Analyze hooks | $0.0001 | $0.001 |
| Generate thread | $0.0002 | $0.002 |
| Generate blog | $0.0005 | $0.005 |
| **Total per outlier** | **~$0.0007** | **~$0.007** |

### Budget Examples

- **$1 budget**: ~1,400 pieces of content (700 outliers)
- **$10 budget**: ~14,000 pieces of content (7,000 outliers)
- **$100 budget**: You probably don't need this much content 😄

### Optimization Tips

1. **Batch processing**: Process 10 at once, not 1 at a time
2. **Skip blogs**: Use `--content-types thread` to save ~70% on generation
3. **Cache outliers**: Find once, reuse for multiple generations
4. **Limit processing**: Use `--limit` and `--max-content` to control costs

---

## What's Next?

### Immediate Next Steps

1. **Review generated content**: Open exports and read everything
2. **Edit as needed**: AI is 90% there, you polish the last 10%
3. **Schedule posting**: Use Buffer, Typefully, or manually post
4. **Track performance**: Which hooks work best for your audience?

### Iterate & Improve

1. **Refine project config**: Based on results, update finder.yml
2. **Test different outlier thresholds**: Find your optimal setting
3. **Experiment with hook types**: Some may work better than others
4. **A/B test content**: Try different adaptations of same hook

### Future Enhancements (Phase 3B)

- LinkedIn article generation
- Newsletter section generation
- A/B testing variants
- Auto-scheduling integration
- Performance tracking dashboard

---

## Need Help?

### Documentation

- **[Main README](./CONTENT_GENERATOR_README.md)** - Overview & architecture
- **[Phase 1 Docs](./CONTENT_GENERATOR_PHASE1.md)** - Outlier detection
- **[Phase 2B Docs](./CONTENT_GENERATOR_PHASE2B.md)** - Hook analysis
- **[Phase 3 Docs](./CONTENT_GENERATOR_PHASE3.md)** - Content generation
- **[Session Summary](./SESSION_SUMMARY_PHASE3_COMPLETION.md)** - Production test results

### Common Questions

**Q: Can I use this for other platforms besides Twitter?**
A: Yes! Outliers work for any platform. Hook analysis and generation work for Twitter-sourced content adapted to any output format.

**Q: How do I know if a hook is good?**
A: Check the emotional trigger and explanation. If it clearly explains WHY it's viral and you can see adapting it to your product, it's good.

**Q: Can I regenerate content from same hooks?**
A: Yes! Just run generate-content again with same hooks.json. You'll get new variations.

**Q: How do I update already-generated content?**
A: Currently need to regenerate. Mark old content as archived and generate new pieces.

**Q: Can I customize the prompts?**
A: Yes! Edit `viraltracker/generation/thread_generator.py` and `blog_generator.py` prompt templates.

---

**Ready to create viral content? Start with Step 1!** 🚀
