# Comment Finder V1.1 - Feature Planning

**Date**: 2025-10-22
**Status**: Planning Phase
**Previous**: V1 Production-Ready (Phase 5 Complete)

---

## V1 Accomplishments (Baseline)

✅ **Proven in Production**:
- End-to-end pipeline working (search → embed → score → generate → export)
- Multi-domain validation (ecommerce + parenting)
- Cost-efficient (~$0.19 for 36 tweets)
- High success rate (100% generation, 0 safety blocks after fixes)
- Good quality suggestions (on-brand, contextual, actionable)

✅ **Core Features**:
- Taxonomy-based relevance scoring
- 4-component scoring (velocity, relevance, openness, author_quality)
- 3 suggestion types (add_value, ask_question, mirror_reframe)
- Voice/persona configuration
- CSV export with one-row-per-tweet format
- Gate filtering and thresholds

---

## V1.1 Goals

**Theme**: Polish, Performance, and Practicality

**Success Criteria**:
1. Reduce manual work by 50% (semantic deduplication)
2. Support 5x scale (500 tweets processed in <10 min)
3. Add tweet metadata to exports (author, followers, text)
4. Improve suggestion quality through post-generation filtering
5. Better cost visibility and control

---

## Feature Set

### Priority 1: Production Essentials

#### 1.1 Tweet Metadata in CSV Export
**Why**: Users need context (author, tweet text, followers) to evaluate opportunities
**Impact**: High - currently a V1 limitation

**Implementation**:
- Add FK constraint between `generated_comments.tweet_id` and `tweet_snapshot.post_id`
- Update export query to join with `tweet_snapshot` and `accounts`
- Add columns: `author_username`, `author_followers`, `tweet_text`, `posted_at`

**CSV Format (new)**:
```csv
project, tweet_id, url, author, followers, tweet_text, posted_at,
score_total, label, topic, why,
suggested_response, suggested_type,
alternative_1, alt_1_type,
alternative_2, alt_2_type
```

**Effort**: Small (1-2 hours)
**Files**: `viraltracker/cli/twitter.py`, `migrations/add_fk_constraint.sql`

---

#### 1.2 Semantic Duplicate Detection
**Why**: Currently calls Gemini API for duplicate tweets (wastes $0.01/tweet)
**Impact**: High - reduces cost and noise

**Problem**: If user searches "screen time" twice, same tweets get scored/generated multiple times

**Solution**: Embedding-based similarity check before generation
- Before generating for tweet X, check if similar tweet already has suggestions
- Use cosine similarity on tweet embeddings (threshold: 0.95)
- Skip generation if duplicate found
- Link to existing suggestions in database

**Implementation**:
1. Add `tweet_embedding` column to `generated_comments` (JSONB or vector)
2. Before generation: query existing embeddings for project
3. Compute cosine similarity with candidate tweet
4. If sim > 0.95: skip generation, log duplicate

**Effort**: Medium (3-4 hours)
**Files**: `viraltracker/generation/comment_finder.py`, `migrations/add_embedding_column.sql`

**Cost Impact**: Saves ~$0.01 per duplicate (could be 20-30% of tweets in real usage)

---

#### 1.3 Rate Limit Handling for Gemini
**Why**: Currently no protection against hitting free tier limits
**Impact**: Medium - prevents crashes during large runs

**Implementation**:
- Track API calls per minute in memory
- Add exponential backoff on rate limit errors (429)
- Display progress with rate limit info: "Generated 10/50 (rate limit: 15 req/min)"
- Add `--max-rate` flag to control API call speed

**Effort**: Small (2 hours)
**Files**: `viraltracker/generation/comment_generator.py`

---

### Priority 2: Quality Improvements

#### 2.1 Post-Generation Quality Filter
**Why**: Some generated suggestions may be off-topic or low-quality
**Impact**: Medium - improves user trust

**Implementation**:
- After generation, run quick quality check:
  - Length check (30-120 chars)
  - No generic phrases ("Great post!", "Thanks for sharing")
  - No repeated words from original tweet (avoid circular responses)
- Add `quality_score` field (0-1) to `generated_comments`
- Filter out suggestions with quality_score < 0.6

**Effort**: Medium (3 hours)
**Files**: `viraltracker/generation/comment_generator.py`

---

#### 2.2 Improved "Why" Rationale
**Why**: Current "why" is too terse ("high velocity", "score 0.50")
**Impact**: Low-Medium - helps user understand selections

**Current**: `high velocity + topic digital wellness (0.78)`
**Improved**: `Trending fast (2.1K likes/hr) + matches digital wellness (78% match) + author has 5K followers`

**Implementation**:
- Enhance `_build_why_rationale()` in `comment_generator.py`
- Include: engagement rate, topic match %, author metrics
- Keep under 100 chars

**Effort**: Small (1 hour)
**Files**: `viraltracker/generation/comment_generator.py`

---

### Priority 3: Performance & Scale

#### 3.1 Batch Generation
**Why**: Currently processes tweets serially (~5s per tweet)
**Impact**: High - 5x faster for large runs

**Current**: 36 tweets = ~3 minutes
**Target**: 36 tweets = ~40 seconds (batch of 5 concurrent)

**Implementation**:
- Use `asyncio` to batch Gemini API calls (max 5 concurrent)
- Maintain rate limit compliance
- Add progress bar with concurrent display

**Effort**: Medium (4 hours)
**Files**: `viraltracker/generation/comment_generator.py`

**Risk**: Need to test Gemini API concurrent limit (may be lower than 5)

---

#### 3.2 Incremental Taxonomy Embedding
**Why**: Currently recomputes ALL embeddings if config changes
**Impact**: Low-Medium - saves time during config iteration

**Implementation**:
- Hash taxonomy nodes (label + description + exemplars)
- Only recompute embeddings if hash changes
- Store hash in cache metadata

**Effort**: Small (2 hours)
**Files**: `viraltracker/core/embeddings.py`

---

### Priority 4: Developer Experience

#### 4.1 Cost Tracking & Reporting
**Why**: Users should know cost before/after runs
**Impact**: Medium - builds trust

**Implementation**:
- Estimate cost before generation: "Estimated cost: $0.15-0.20 (15 tweets × 3 suggestions)"
- Show actual cost after: "Actual cost: $0.17 (45 API calls)"
- Add `--dry-run` flag to show what would be generated without calling API

**Pricing** (Gemini Flash):
- Input: $0.01 per 1M tokens (~500 tokens per tweet = $0.000005)
- Output: $0.04 per 1M tokens (~150 tokens per response = $0.000006)
- **Total per tweet**: ~$0.000011 × 1 call = $0.000011 (~100 tweets per cent)

**Effort**: Small (2 hours)
**Files**: `viraltracker/cli/twitter.py`, `viraltracker/generation/comment_generator.py`

---

#### 4.2 Better Logging & Debugging
**Why**: Hard to debug scoring/generation issues
**Impact**: Low - developer quality of life

**Implementation**:
- Add `--verbose` flag to show detailed scoring breakdown
- Log sample tweet embeddings for inspection
- Add `--debug-tweet <tweet_id>` to show full scoring trace for one tweet

**Effort**: Small (2 hours)
**Files**: `viraltracker/cli/twitter.py`, `viraltracker/generation/comment_finder.py`

---

### Future Considerations (V1.2+)

**Not in V1.1 scope, but worth tracking**:

1. **Multi-language Support**
   - Currently English-only
   - Would need: language detection, multilingual embeddings, per-language voice config
   - Effort: Large (8+ hours)

2. **Semantic Search for Manual Review**
   - Query: "Show me tweets about checkout optimization"
   - Uses embeddings to find relevant tweets beyond keyword matching
   - Effort: Medium (4 hours)

3. **Auto-Reply Integration** (requires Twitter API)
   - Mark suggestions as "approved" in DB
   - Automatically post via Twitter API
   - Effort: Large (8+ hours) + API costs + compliance risk

4. **Learning from User Feedback**
   - Track which suggestions users post
   - Fine-tune scoring weights based on acceptance rate
   - Effort: Large (10+ hours)

5. **Hook Analysis Integration**
   - Show hook patterns from scored tweets
   - Link comment opportunities to hook types
   - Effort: Medium (4 hours)

6. **Multi-Project Batch Mode**
   - Run generation for all projects in one command
   - Useful for daily automation
   - Effort: Small (2 hours)

---

## Implementation Roadmap

### Week 1: Production Essentials
- Day 1-2: Tweet metadata in CSV export (1.1)
- Day 3-4: Semantic duplicate detection (1.2)
- Day 5: Rate limit handling (1.3)

### Week 2: Quality + Performance
- Day 1-2: Post-generation quality filter (2.1)
- Day 3: Improved "why" rationale (2.2)
- Day 4-5: Batch generation (3.1)

### Week 3: Polish + Release
- Day 1: Cost tracking (4.1)
- Day 2: Better logging (4.2)
- Day 3: Testing + bug fixes
- Day 4: Documentation updates
- Day 5: V1.1 release

**Total Effort**: ~15-18 hours development + 3-5 hours testing/docs

---

## Success Metrics (V1.1)

**Before V1.1** (current):
- ❌ No tweet metadata in exports
- ❌ Duplicates cost $0.01 each (20-30% waste)
- ❌ No rate limit protection
- ⚠️ 36 tweets in 3 minutes (serial processing)
- ⚠️ Generic "why" rationale
- ⚠️ No cost visibility

**After V1.1** (target):
- ✅ Full tweet context in CSV (author, text, followers)
- ✅ 0 duplicate API calls (semantic dedup working)
- ✅ Rate limit handling prevents crashes
- ✅ 36 tweets in <1 minute (batch processing)
- ✅ Detailed "why" rationale
- ✅ Cost estimate + actual cost shown

**Key KPIs**:
- Cost per opportunity: $0.005 → $0.003 (40% reduction via dedup)
- Time per 50 tweets: 4 min → 1 min (4x faster)
- Export usability: 6/10 → 9/10 (tweet metadata added)
- User confidence: 7/10 → 9/10 (cost transparency)

---

## Risk Assessment

**Low Risk**:
- Tweet metadata export (1.1) - straightforward SQL join
- Improved rationale (2.2) - string formatting only
- Cost tracking (4.1) - read-only display
- Logging improvements (4.2) - no user-facing changes

**Medium Risk**:
- Semantic dedup (1.2) - need to tune similarity threshold, could skip good tweets if too aggressive
- Quality filter (2.1) - might filter out valid suggestions, needs testing
- Incremental embeddings (3.2) - cache invalidation bugs possible

**High Risk**:
- Batch generation (3.1) - async complexity, potential race conditions, need to test Gemini concurrent limits
- Rate limit handling (1.3) - need to test actual Gemini rate limits (docs unclear)

**Mitigation**:
- Add feature flags for risky features (can disable if issues arise)
- Extensive testing on ecom + yakety-pack projects before release
- Gradual rollout: start with serial mode, enable batch mode after validation

---

## Open Questions

1. **Gemini API Concurrent Limits**: What's the actual concurrent request limit? (docs say "varies")
   - Action: Test with 1, 3, 5, 10 concurrent requests

2. **Semantic Dedup Threshold**: Is 0.95 too high? Too low?
   - Action: Test with ecom dataset, measure false positive rate

3. **Quality Filter Impact**: How many suggestions will be filtered out?
   - Action: Run quality filter on V1 generated suggestions, measure distribution

4. **CSV Column Order**: Should tweet metadata come before or after scoring metadata?
   - Action: User feedback (ask in next session)

5. **Batch Size**: Is 5 concurrent the right number, or should it be configurable?
   - Action: Make it a config value with default=3 (conservative)

---

## Notes

- V1.1 focuses on **polish and production-readiness**, not new features
- All V1.1 features are **backwards compatible** with V1 (no breaking changes)
- V1.1 database migrations are **additive only** (no data loss)
- V1.1 can be shipped **incrementally** (each feature is independent)

---

**Next Steps After This Plan**:
1. Get user feedback on priorities
2. Create GitHub issues for each feature
3. Start with P1 features (production essentials)
4. Ship V1.1 in 2-3 weeks
