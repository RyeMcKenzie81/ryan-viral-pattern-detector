# Search Term Optimization Strategy 🎯

**Goal**: Find which Twitter search terms yield the most "green" scored tweets (high-quality engagement opportunities) for yakety-pack-instagram project.

**Why This Matters**:
- Green tweets = best engagement opportunities (score > 0.55)
- Better search terms = more efficient scraping
- Higher green ratio = better ROI on comment generation

---

## 📊 Current Taxonomy (yakety-pack-instagram)

From `projects/yakety-pack-instagram/finder.yml`:

1. **screen time management** - Managing kids screen time, setting boundaries, device rules, digital balance
2. **parenting tips** - Practical parenting advice, behavior management, family routines
3. **digital wellness** - Healthy technology habits, social media impact, mental health, online safety

**Scoring Weights:**
- Velocity: 0.3 (engagement speed)
- Relevance: 0.4 (semantic match to taxonomy)
- Openness: 0.2 (conversational potential)
- Author Quality: 0.1 (follower count/engagement)

**Thresholds:**
- Green: ≥ 0.55
- Yellow: 0.4 - 0.549
- Red: < 0.4

---

## 🔬 Proposed Testing Methodology

### Phase 1: Baseline Testing (Test 10-15 Search Terms)

**Approach:**
1. Select candidate search terms (see list below)
2. Scrape 50 tweets per term (minimum required by Apify)
3. Generate comments on all tweets (no filtering)
4. Analyze score distribution

**Metrics to Track:**
- Green count (score ≥ 0.55)
- Yellow count (score 0.4-0.549)
- Red count (score < 0.4)
- Green ratio (green / total)
- Average score
- Cost per green tweet

**Test Structure:**
```bash
# For each search term:
1. Scrape tweets
   ./vt twitter search --terms "SEARCH_TERM" --count 50 --min-likes 20 --days-back 3 --project yakety-pack-instagram

2. Generate comments (no filtering to see all scores)
   ./vt twitter generate-comments --project yakety-pack-instagram --hours-back 72 --max-candidates 50 --batch-size 5 --no-skip-low-scores

3. Export and analyze
   ./vt twitter export-comments --project yakety-pack-instagram -o results/SEARCH_TERM_results.csv --status pending
```

### Phase 2: Analysis & Refinement

**SQL Query for Analysis:**
```sql
-- Analyze scores by search term
SELECT
    -- Add search_term tracking field first
    COUNT(*) as total_tweets,
    SUM(CASE WHEN score_total >= 0.55 THEN 1 ELSE 0 END) as green_count,
    SUM(CASE WHEN score_total >= 0.4 AND score_total < 0.55 THEN 1 ELSE 0 END) as yellow_count,
    SUM(CASE WHEN score_total < 0.4 THEN 1 ELSE 0 END) as red_count,
    ROUND(SUM(CASE WHEN score_total >= 0.55 THEN 1 ELSE 0 END)::decimal / COUNT(*) * 100, 1) as green_ratio,
    ROUND(AVG(score_total), 3) as avg_score,
    topic
FROM generated_comments
WHERE project_id = 'YOUR_PROJECT_ID'
  AND created_at > NOW() - INTERVAL '7 days'
GROUP BY topic
ORDER BY green_ratio DESC;
```

### Phase 3: Implement Winners

**Create a tracking system:**
1. Tag tweets with search term metadata
2. Build a "best search terms" list
3. Automate daily scraping of top performers

---

## 🎯 Candidate Search Terms to Test

### Tier 1: Direct Matches (High Confidence)
These directly match your taxonomy topics:

**Screen Time Management:**
- "screen time kids"
- "screen time rules"
- "device limits"
- "iPad rules toddler"
- "phone rules kids"

**Parenting Tips:**
- "parenting tips"
- "toddler behavior"
- "parenting advice"
- "raising kids"
- "family routines"

**Digital Wellness:**
- "digital wellness"
- "kids social media"
- "online safety kids"
- "tech boundaries"

### Tier 2: Adjacent Topics (Medium Confidence)
Related but may score lower on relevance:

- "gentle parenting"
- "screen addiction"
- "family screen time"
- "kids YouTube"
- "parenting challenges"
- "digital detox family"

### Tier 3: Broader Topics (Lower Confidence)
May capture relevant discussions but with noise:

- "parenting"
- "toddler"
- "family life"
- "modern parenting"

---

## 📈 Expected Outcomes

### Hypothesis
**Tier 1 terms** will yield:
- Green ratio: 15-30%
- Average score: 0.48-0.52
- High relevance to taxonomy

**Tier 2 terms** will yield:
- Green ratio: 8-15%
- Average score: 0.42-0.48
- Medium relevance

**Tier 3 terms** will yield:
- Green ratio: 3-8%
- Average score: 0.38-0.44
- Lower relevance but may surface unexpected opportunities

### Success Criteria
A "winning" search term should have:
- ✅ Green ratio > 10%
- ✅ Average score > 0.45
- ✅ At least 5 green tweets per 50 scraped
- ✅ Low red ratio (< 40%)

---

## 🔧 Technical Implementation

### Option 1: Manual Testing (Quick Start)
Run searches manually and track in spreadsheet:

| Search Term | Total | Green | Yellow | Red | Green % | Avg Score | Notes |
|------------|-------|-------|--------|-----|---------|-----------|-------|
| screen time kids | 50 | 12 | 28 | 10 | 24% | 0.51 | Strong! |
| parenting tips | 50 | 8 | 30 | 12 | 16% | 0.48 | Good |
| ... | ... | ... | ... | ... | ... | ... | ... |

### Option 2: Automated Testing (Better)
Create a test script:

```python
# search_term_tester.py
import subprocess
import csv
from datetime import datetime

terms_to_test = [
    "screen time kids",
    "parenting tips",
    "digital wellness",
    # ... add all terms
]

results = []

for term in terms_to_test:
    print(f"Testing: {term}")

    # 1. Scrape
    subprocess.run([
        "./vt", "twitter", "search",
        "--terms", term,
        "--count", "50",
        "--min-likes", "20",
        "--days-back", "3",
        "--project", "yakety-pack-instagram"
    ])

    # 2. Generate comments
    subprocess.run([
        "./vt", "twitter", "generate-comments",
        "--project", "yakety-pack-instagram",
        "--hours-back", "72",
        "--max-candidates", "50",
        "--batch-size", "5",
        "--no-skip-low-scores"
    ])

    # 3. Query DB for scores
    # ... analyze results ...

    # 4. Store results
    results.append({
        'term': term,
        'green_count': green,
        'green_ratio': ratio,
        'avg_score': avg
    })

# Export results
with open('search_term_analysis.csv', 'w') as f:
    writer = csv.DictWriter(f, fieldnames=['term', 'green_count', 'green_ratio', 'avg_score'])
    writer.writeheader()
    writer.writerows(results)
```

### Option 3: Add Search Term Tracking to DB (Best Long-term)

**Database Schema Update:**
```sql
-- Add search_term tracking to posts or create junction table
ALTER TABLE posts
ADD COLUMN search_term TEXT;

-- Or create a tracking table
CREATE TABLE post_search_terms (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    post_id TEXT REFERENCES posts(post_id),
    search_term TEXT NOT NULL,
    search_date TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_post_search_terms_term ON post_search_terms(search_term);
```

**Update search command:**
Modify `viraltracker/cli/twitter.py` to tag tweets with search term.

---

## 🎓 Analysis Tips

### What to Look For

**High-Performing Terms:**
- Consistent green scores
- Low variance in scores (predictable quality)
- Aligns with 2+ taxonomy topics

**Red Flags:**
- Too broad (captures off-topic content)
- Too narrow (< 20 tweets found)
- High red ratio (> 50%)

### Optimization Strategies

**If green ratio is low overall:**
- Revisit taxonomy topics (are they too narrow?)
- Adjust scoring weights (increase relevance weight?)
- Test more specific long-tail terms

**If specific topics underperform:**
- Add more exemplars to that taxonomy topic
- Try alternative phrasings
- Consider if topic is viable on Twitter

---

## 📅 Recommended Testing Schedule

### Week 1: Tier 1 Terms (5 terms)
- Test direct matches
- Establish baseline metrics
- Identify clear winners

### Week 2: Tier 2 Terms (7 terms)
- Test adjacent topics
- Compare to baseline
- Refine hypothesis

### Week 3: Tier 3 + Custom (3-5 terms)
- Test broader terms
- Try any custom ideas from findings
- Finalize "winner list"

### Week 4: Production
- Automate scraping of top 5-7 terms
- Monitor ongoing performance
- Adjust as needed

---

## 💰 Cost Estimation

**Per Search Term Test:**
- Scrape: 50 tweets × Apify cost (minimal)
- Generate: 50 tweets × $0.0001 = **$0.005**
- Total: ~$0.01 per term test

**Full Testing Campaign:**
- 15 terms × $0.01 = **$0.15 total**
- Very affordable for the insights gained!

---

## 🚀 Quick Start: Test Your First Term

To get started right now:

```bash
# 1. Test "screen time kids"
./vt twitter search --terms "screen time kids" \
  --count 50 --min-likes 20 --days-back 3 \
  --project yakety-pack-instagram

# 2. Generate comments
./vt twitter generate-comments --project yakety-pack-instagram \
  --hours-back 72 --max-candidates 50 --batch-size 5 \
  --no-skip-low-scores

# 3. Export and review
./vt twitter export-comments --project yakety-pack-instagram \
  -o ~/Downloads/screen_time_kids_test.csv --status pending

# 4. Check the label distribution in the CSV
# Count greens vs yellows vs reds manually or with:
python3 << 'EOF'
import csv
from collections import Counter

with open('/Users/ryemckenzie/Downloads/screen_time_kids_test.csv', 'r') as f:
    reader = csv.DictReader(f)
    labels = [row['label'] for row in reader]

counts = Counter(labels)
total = len(labels)

print(f"\n📊 Results for 'screen time kids':\n")
print(f"Total tweets: {total}")
print(f"Green: {counts['green']} ({counts['green']/total*100:.1f}%)")
print(f"Yellow: {counts['yellow']} ({counts['yellow']/total*100:.1f}%)")
print(f"Red: {counts['red']} ({counts['red']/total*100:.1f}%)")
EOF
```

---

## 📝 Next Steps

1. ✅ Commit V1.3 changes
2. ✅ Push to GitHub
3. ⏭️ Choose testing approach (manual vs automated)
4. ⏭️ Run first test on "screen time kids"
5. ⏭️ Analyze results
6. ⏭️ Iterate on additional terms

---

**Created**: 2025-10-23
**Status**: Strategy document ready
**Next**: Begin Tier 1 testing
