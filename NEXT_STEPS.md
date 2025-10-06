# ViralTracker - Next Steps & Roadmap

**Updated:** 2025-10-06
**Current Phase:** Multi-Brand Instagram Workflow Complete ✅

---

## Current State

### ✅ What's Complete

**Core Infrastructure:**
- Multi-brand/product database schema
- Brand, product, and project management CLI
- Instagram scraping (Apify integration)
- Account metadata extraction
- Statistical outlier detection
- Video downloading (yt-dlp)
- Gemini AI video analysis
- Product-aware adaptation generation

**Working Workflows:**
- URL import → Scrape → Outlier detection → Video download → AI analysis → Product adaptation
- Brand/product CRUD operations
- Project management
- Complete data persistence

**Data Quality:**
- 10-14 scene storyboards per video
- Timestamped transcripts
- Viral pattern identification
- Production-ready product adaptations
- 8.5-9.0/10 viral scores
- 9/10 audience fit scores

---

## Immediate Next Steps (Choose One)

### Option 1: Script Management CLI 📝 (Recommended - High ROI)

**Why:** Turn AI adaptations into managed, versionable assets

**Tasks:**
1. Create script CLI module (`viraltracker/cli/script.py`)
2. Implement commands:
   - `vt script create` - Create script from video analysis
   - `vt script list` - View scripts (filter by product/brand/status)
   - `vt script show` - Display full script details
   - `vt script update` - Edit script content
   - `vt script version` - Create new version/revision
   - `vt script status` - Update status (draft → review → approved → produced)
   - `vt script export` - Export to markdown/PDF for production team

3. Features to build:
   - Auto-populate from video_analysis.product_adaptation
   - Version control (parent_script_id linking)
   - Status workflow (draft → review → approved → in_production → produced → published)
   - Rich display formatting
   - Export templates for different formats

4. Test workflow:
   ```bash
   # Create script from analysis
   vt script create --analysis <uuid> --title "Screen Time Standoff"

   # List scripts for product
   vt script list --product core-deck --status draft

   # Make revision
   vt script version --script <uuid> --notes "Updated hook timing"

   # Export for production
   vt script export --script <uuid> --format pdf
   ```

**Estimated Time:** 3-4 hours
**Value:** High - Makes AI output actionable

---

### Option 2: TikTok Integration 🎵 (Platform Expansion)

**Why:** Expand viral content sources

**Tasks:**
1. Research TikTok scraping options:
   - Apify has TikTok scrapers
   - Might need different approach than Instagram

2. Update schema:
   - Add TikTok to platforms table
   - TikTok-specific metadata fields

3. Create TikTok scraper (`viraltracker/scrapers/tiktok.py`)
   - Similar to Instagram scraper
   - Handle TikTok-specific data (music, effects, etc.)

4. Update video downloader:
   - TikTok URL support
   - Handle TikTok video format

5. Update AI prompts:
   - TikTok-specific viral patterns
   - Platform differences in analysis

6. Test workflow:
   ```bash
   vt import url --project <slug> --url https://tiktok.com/@user/video/123
   vt scrape --project <slug> --platform tiktok
   vt analyze outliers --project <slug>
   vt process videos --project <slug>
   vt analyze videos --project <slug> --product <slug>
   ```

**Estimated Time:** 6-8 hours
**Value:** High - New content source, bigger opportunity

---

### Option 3: Batch Product Comparison 🔄 (Optimization)

**Why:** Efficient multi-product analysis

**Tasks:**
1. Update VideoAnalyzer:
   - Support multiple product IDs in single run
   - Batch product context loading
   - Parallel Gemini requests (if supported)

2. Create comparison logic:
   - Calculate fit scores across products
   - Rank products by audience alignment
   - Generate comparison report

3. Update CLI:
   ```bash
   # Analyze for all products
   vt analyze videos --project <slug> --all-products

   # Analyze for specific products
   vt analyze videos --project <slug> --products product-a,product-b,product-c

   # Show comparison
   vt analyze compare --video <post-id>
   ```

4. Add comparison view:
   ```
   Video: "Nursery Makeover"

   Product Fit Scores:
   1. Core Deck - 9/10 (Perfect age fit, strong emotional alignment)
   2. Expansion Pack - 7/10 (Good fit, less emotional hook)
   3. Travel Edition - 6/10 (Age fit, but location mismatch)

   Recommended: Core Deck
   Reason: Strongest emotional resonance with target audience
   ```

**Estimated Time:** 4-5 hours
**Value:** Medium-High - Optimize product selection

---

### Option 4: Performance Tracking Dashboard 📊 (Analytics)

**Why:** Learn what works, improve over time

**Tasks:**
1. Create tracking workflow:
   - Link produced videos to scripts
   - Capture actual metrics (views, engagement)
   - Compare to predictions

2. Update product_scripts:
   - Automatically populate produced_post_id when video goes live
   - Fetch actual metrics from platform
   - Calculate performance_vs_prediction

3. Build analytics CLI:
   ```bash
   # Track produced video
   vt script track --script <uuid> --post-url <url>

   # View performance
   vt script performance --script <uuid>

   # Generate report
   vt analyze performance --product <slug> --date-range 30d
   ```

4. Performance insights:
   ```
   Script: "Screen Time Standoff"
   Predicted Viral Score: 8.5/10
   Actual Performance:
     Views: 2.3M (predicted 1.5M) ✅ +53%
     Engagement: 12.3% (predicted 10%) ✅ +23%
     Shares: 45K

   Pattern Success:
     "Standoff" framing: Highly effective
     Gaming context: Strong resonance
     Recommended: Use in future adaptations
   ```

**Estimated Time:** 5-6 hours
**Value:** Medium - Long-term improvement

---

## Phase 5+ Features (Future)

### YouTube Shorts Integration
- YouTube API/scraper integration
- Shorts-specific viral patterns
- YouTube audience analysis

### Advanced AI Features
- Auto-script generation (full automation)
- A/B test script variations
- Predictive modeling (which will go viral?)
- Voice-over script generation
- Shot list generation with camera angles

### Production Tools
- Storyboard to video editor export
- Integration with video editing software
- Asset management (props, locations, talent)
- Production calendar/scheduling

### Analytics & Optimization
- Multi-platform performance comparison
- Viral pattern library
- Success pattern templates
- ROI tracking per product
- Competitive analysis

### Collaboration Features
- Team workflow (assign scripts to editors)
- Review/approval process
- Comments and feedback
- Version history visualization

### Platform Expansion
- LinkedIn video
- Twitter/X
- Facebook Reels
- Pinterest video pins

---

## Recommended Priority Order

### Phase 5A: Script Management (Next) ⭐
**Why First:** Makes current AI output actionable, high immediate value

**Deliverable:** Managed script library with versions and export

---

### Phase 5B: TikTok Integration
**Why Second:** Biggest viral content platform, huge opportunity

**Deliverable:** Full TikTok workflow like Instagram

---

### Phase 5C: Performance Tracking
**Why Third:** Learn and improve, optimize AI

**Deliverable:** Performance insights and pattern library

---

### Phase 5D: Batch Product Comparison
**Why Fourth:** Optimization, better product selection

**Deliverable:** Multi-product analysis and recommendations

---

### Phase 6: Advanced Features
- YouTube Shorts
- Auto-script generation
- Production tools
- Analytics dashboard
- Team collaboration

---

## Quick Wins (Small Tasks)

### 1. Environment Variable Docs
- Document all required .env variables
- Create .env.example file
- Add setup instructions to README

### 2. Error Handling Improvements
- Better error messages
- Retry logic for API calls
- Graceful degradation

### 3. CLI Help Text
- Improve command descriptions
- Add more examples
- Better flag documentation

### 4. Video Storage Optimization
- Compress videos before storage
- Add automatic cleanup of old temp files
- Storage quota monitoring

### 5. Logging Enhancements
- Structured logging
- Log levels
- Output to file option

---

## Technical Debt

### Known Issues to Fix:

1. **RuntimeWarning** in CLI execution
   - `'viraltracker.cli.main' found in sys.modules`
   - Not critical, but should clean up

2. **Gemini Trailing Comma Bug**
   - Sometimes returns invalid JSON
   - Add better JSON parsing/cleanup

3. **Token Usage Tracking**
   - Not capturing actual token counts from Gemini
   - Should log for cost tracking

4. **Video Processing Log Constraint**
   - Unique constraint added manually
   - Should be in initial schema

5. **Platform ID References**
   - Some queries still reference non-existent platform_id
   - Audit and clean up

---

## Documentation Needs

### User Documentation:
- [ ] Installation guide
- [ ] Quick start tutorial
- [ ] Command reference
- [ ] Workflow examples
- [ ] Troubleshooting guide

### Developer Documentation:
- [ ] Architecture overview
- [ ] Database schema docs
- [ ] API integration guides
- [ ] Adding new platforms guide
- [ ] Contributing guidelines

### Business Documentation:
- [ ] Use cases and benefits
- [ ] ROI calculation
- [ ] Product roadmap
- [ ] Feature comparison

---

## Testing Checklist

### Unit Tests Needed:
- [ ] VideoDownloader class
- [ ] VideoAnalyzer class
- [ ] Instagram scraper
- [ ] Database operations
- [ ] CLI commands

### Integration Tests:
- [ ] Complete Instagram workflow
- [ ] Multi-product analysis
- [ ] Error scenarios
- [ ] API failures
- [ ] Database migrations

### End-to-End Tests:
- [ ] URL import to final analysis
- [ ] Multi-brand workflows
- [ ] Performance scenarios

---

## Deployment Considerations

### Production Readiness:
- [ ] Environment configuration management
- [ ] API key security (secrets management)
- [ ] Database backups
- [ ] Error monitoring
- [ ] Usage analytics
- [ ] Cost tracking (Gemini API, Apify, Supabase)

### Scalability:
- [ ] Batch processing for large projects
- [ ] Rate limiting handling
- [ ] Queue system for long-running tasks
- [ ] Caching strategy
- [ ] CDN for video storage

### Reliability:
- [ ] Retry mechanisms
- [ ] Circuit breakers
- [ ] Health checks
- [ ] Graceful degradation

---

## Estimated Timeline

### This Week (Script Management):
- Day 1: Build script CLI module
- Day 2: Implement CRUD commands
- Day 3: Add versioning and export
- Day 4: Test and document

### Next Week (TikTok Integration):
- Day 1-2: Research and setup TikTok scraper
- Day 3-4: Implement TikTok workflow
- Day 5: Test and compare to Instagram

### Following Week (Performance Tracking):
- Day 1-2: Build tracking system
- Day 3-4: Analytics and reporting
- Day 5: Insights and optimization

---

## Decision: What to Build Next?

**Recommendation: Script Management CLI** ⭐

**Rationale:**
1. **Immediate Value** - Makes AI output actionable right now
2. **Low Risk** - Database schema already exists
3. **Quick Win** - Can complete in 3-4 hours
4. **High Usage** - Will be used constantly
5. **Foundation** - Enables production workflow

**Alternative Paths:**
- If expanding content sources is priority → TikTok Integration
- If optimizing current workflow → Batch Product Comparison
- If focused on learning/improvement → Performance Tracking

---

## Success Criteria

### Script Management Success:
- ✅ Can create scripts from video analyses
- ✅ Can edit and version scripts
- ✅ Can export scripts for production
- ✅ Status workflow implemented
- ✅ All adaptations can be managed as scripts

### TikTok Integration Success:
- ✅ Can scrape TikTok URLs
- ✅ Can download TikTok videos
- ✅ Can analyze with product context
- ✅ TikTok-specific patterns identified
- ✅ Full workflow working like Instagram

### Performance Tracking Success:
- ✅ Can link scripts to produced videos
- ✅ Can capture actual metrics
- ✅ Can compare predictions to actuals
- ✅ Insights generated from performance data
- ✅ AI prompts improved based on results

---

**Next Session:** Choose one of the above options and build it out!
