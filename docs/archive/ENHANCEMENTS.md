# ViralTracker - Planned Enhancements

**Last Updated:** 2025-10-03

---

## Account Metadata Enhancement

### Overview
When scraping accounts via Apify, capture additional account metadata (follower count, bio, profile info) for better context and analysis.

### Rationale
- We're already making API calls to scrape posts
- Account context helps understand viral patterns
- Follower count can inform content strategy
- Bio helps identify account type/niche
- Historical follower tracking shows growth trends

### Database Changes

**New Columns for `accounts` table:**
```sql
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS follower_count integer;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS following_count integer;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS bio text;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS profile_pic_url text;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS display_name text;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS is_verified boolean DEFAULT false;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS account_type text; -- 'personal', 'business', 'creator'
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS external_url text;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS metadata_updated_at timestamptz;

CREATE INDEX idx_accounts_follower_count ON accounts(follower_count);
CREATE INDEX idx_accounts_is_verified ON accounts(is_verified);
CREATE INDEX idx_accounts_metadata_updated_at ON accounts(metadata_updated_at);

COMMENT ON COLUMN accounts.follower_count IS 'Number of followers at last metadata update';
COMMENT ON COLUMN accounts.bio IS 'Account bio/description';
COMMENT ON COLUMN accounts.metadata_updated_at IS 'When account metadata (follower count, bio, etc.) was last updated - separate from last_scraped_at for posts';
```

**Timestamp Strategy:**
- `last_scraped_at` - Tracks when we last scraped **posts** from this account
- `metadata_updated_at` - Tracks when we last updated **account metadata** (follower count, bio, profile info)

This separation allows:
- Update metadata independently from post scraping
- Skip metadata updates if recently refreshed (e.g., < 24 hours)
- Track metadata freshness for reporting
- Optimize API usage (don't fetch metadata every post scrape)

**Optional: Account History Table (for tracking follower growth over time):**
```sql
CREATE TABLE IF NOT EXISTS account_history (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id uuid NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  follower_count integer,
  following_count integer,
  post_count integer,
  scraped_at timestamptz DEFAULT now(),
  UNIQUE(account_id, scraped_at)
);

CREATE INDEX idx_account_history_account_id ON account_history(account_id);
CREATE INDEX idx_account_history_scraped_at ON account_history(scraped_at);

COMMENT ON TABLE account_history IS 'Historical snapshots of account metrics for tracking growth';
```

### Implementation Changes

**1. Update InstagramScraper class:**
```python
# In viraltracker/scrapers/instagram.py

def _extract_account_metadata(self, apify_item: Dict) -> Dict:
    """
    Extract account metadata from Apify response

    Apify Instagram scraper returns owner info:
    - ownerUsername
    - ownerFullName
    - ownerFollowers
    - ownerIsVerified
    - ownerProfilePicUrl
    - etc.
    """
    return {
        'display_name': apify_item.get('ownerFullName'),
        'follower_count': apify_item.get('ownerFollowers'),
        'is_verified': apify_item.get('ownerIsVerified', False),
        'profile_pic_url': apify_item.get('ownerProfilePicUrl'),
        # Add more fields as needed
    }

def _upsert_accounts(self, df: pd.DataFrame, account_map: Dict, platform_id: str):
    """Update to include account metadata"""

    # Group posts by account to get metadata from first post
    account_metadata = {}
    for username in df['account'].unique():
        account_posts = df[df['account'] == username]
        first_post = account_posts.iloc[0]

        # Extract metadata from raw Apify data
        # (Would need to pass raw items to this method)
        account_metadata[username] = {
            'follower_count': first_post.get('follower_count'),
            'bio': first_post.get('bio'),
            # ... other fields
        }

    # Update accounts with metadata
    for handle, metadata in account_metadata.items():
        if handle in account_map:
            account_id = account_map[handle]['account_id']
            update_data = {
                'last_scraped_at': datetime.now().isoformat(),
                'follower_count': metadata.get('follower_count'),
                'bio': metadata.get('bio'),
                'follower_count_scraped_at': datetime.now().isoformat(),
                # ... other fields
            }
            self.supabase.table('accounts').update(update_data).eq('id', account_id).execute()
```

**2. Update data normalization:**
```python
def _normalize_items(self, items: List[Dict]) -> Tuple[pd.DataFrame, Dict]:
    """
    Normalize items and extract account metadata

    Returns:
        Tuple of (posts_df, account_metadata_dict)
    """
    normalized_posts = []
    account_metadata = {}

    for item in items:
        # Extract post data (existing logic)
        post_data = {...}
        normalized_posts.append(post_data)

        # Extract account metadata (new logic)
        username = item.get('ownerUsername')
        if username not in account_metadata:
            account_metadata[username] = {
                'follower_count': item.get('ownerFollowers'),
                'following_count': item.get('ownerFollowing'),
                'bio': item.get('ownerBio'),
                'profile_pic_url': item.get('ownerProfilePicUrl'),
                'display_name': item.get('ownerFullName'),
                'is_verified': item.get('ownerIsVerified', False),
            }

    return pd.DataFrame(normalized_posts), account_metadata
```

**3. Pydantic Model Update:**
```python
# In viraltracker/core/models.py

class Account(BaseModel):
    """Account model"""
    id: UUID4
    handle: str  # Legacy field
    platform_id: Optional[UUID4] = None
    platform_username: Optional[str] = None

    # New metadata fields
    follower_count: Optional[int] = None
    following_count: Optional[int] = None
    bio: Optional[str] = None
    profile_pic_url: Optional[str] = None
    display_name: Optional[str] = None
    is_verified: bool = False
    account_type: Optional[str] = None
    external_url: Optional[str] = None

    # Timestamps
    last_scraped_at: Optional[datetime] = None  # When posts were last scraped
    metadata_updated_at: Optional[datetime] = None  # When account metadata was last updated
    created_at: datetime
```

### Apify Data Availability

**Instagram Scraper Returns:**
- ✅ `ownerUsername` - Username
- ✅ `ownerFullName` - Display name
- ✅ `ownerFollowers` - Follower count
- ✅ `ownerIsVerified` - Verified status
- ✅ `ownerProfilePicUrl` - Profile picture URL
- ⚠️ `ownerBio` - Bio (may require additional API call)
- ⚠️ `ownerFollowing` - Following count (may require additional API call)

**TikTok Scraper Returns:**
- Similar fields for TikTok accounts
- `authorMeta.followers`
- `authorMeta.verified`
- `authorMeta.signature` (bio)

**YouTube Scraper Returns:**
- Channel subscriber count
- Channel description
- Verified status

### Benefits

**For Analysis:**
- Identify micro vs macro influencers
- Understand niche/vertical from bio
- Track verified accounts separately
- Correlate follower count with engagement rates

**For Reporting:**
- "Top posts from verified accounts"
- "Best performing content from accounts with 10k-100k followers"
- "Account growth tracking over time"

**For Product Adaptation:**
- Tailor content to account size
- Understand audience from bio keywords
- Identify relevant influencers for partnerships

### Future Enhancements

**Account Segmentation:**
```sql
-- Segment accounts by follower count
SELECT
  CASE
    WHEN follower_count < 10000 THEN 'micro'
    WHEN follower_count < 100000 THEN 'mid-tier'
    WHEN follower_count < 1000000 THEN 'macro'
    ELSE 'mega'
  END as influencer_tier,
  COUNT(*) as account_count,
  AVG(follower_count) as avg_followers
FROM accounts
WHERE follower_count IS NOT NULL
GROUP BY 1;
```

**Growth Tracking:**
```sql
-- Track follower growth over time
SELECT
  a.platform_username,
  ah.scraped_at::date as date,
  ah.follower_count,
  LAG(ah.follower_count) OVER (PARTITION BY a.id ORDER BY ah.scraped_at) as previous_count,
  ah.follower_count - LAG(ah.follower_count) OVER (PARTITION BY a.id ORDER BY ah.scraped_at) as growth
FROM accounts a
JOIN account_history ah ON a.id = ah.account_id
ORDER BY a.platform_username, ah.scraped_at;
```

**Bio Analysis:**
```sql
-- Find common keywords in viral account bios
SELECT
  word,
  COUNT(*) as frequency
FROM (
  SELECT
    unnest(string_to_array(lower(bio), ' ')) as word
  FROM accounts
  WHERE bio IS NOT NULL
) words
WHERE length(word) > 3
GROUP BY word
ORDER BY frequency DESC
LIMIT 20;
```

### Priority

**Phase:** 4.5 (After Phase 4b, before Phase 5)
**Effort:** ~2-4 hours
**Impact:** Medium (nice to have, valuable for future analysis)

### Implementation Checklist

- [ ] Create database migration for new columns
- [ ] Update Account Pydantic model
- [ ] Modify InstagramScraper to extract metadata
- [ ] Update _normalize_items to return account metadata
- [ ] Update _upsert_accounts to save metadata
- [ ] Test with real Instagram accounts
- [ ] Add similar support for TikTok (Phase 5)
- [ ] Add similar support for YouTube (Phase 6)
- [ ] (Optional) Create account_history table
- [ ] (Optional) Create historical tracking script
- [ ] Update documentation

### Notes

- Some Apify actors may require additional credits for account metadata
- Bio and following count may require separate API calls
- Consider rate limiting when making additional requests
- Profile picture URLs may expire - consider downloading/storing
- Follower count changes frequently - decide on update frequency

---

## Other Planned Enhancements

### Post Engagement Rate Calculation
Calculate and store engagement rate per post:
```sql
ALTER TABLE posts ADD COLUMN engagement_rate float;

-- Engagement rate = (likes + comments) / views * 100
UPDATE posts
SET engagement_rate = ((likes + comments)::float / NULLIF(views, 0)) * 100
WHERE views > 0;
```

### Platform-Specific Metrics Storage
Store platform-specific metrics in structured JSONB:
```sql
-- Already exists in video_analysis table
-- Extend to posts table for quick access
ALTER TABLE posts ADD COLUMN platform_metrics jsonb;

-- Example for Instagram:
-- {
--   "instagram": {
--     "shares": 123,
--     "saves": 456,
--     "reach": 12345,
--     "impressions": 15000
--   }
-- }
```

### Bulk Operations
Add bulk update/delete commands to CLI:
```bash
vt project bulk-update <slug> --set-active false
vt account bulk-import <project> --file accounts.csv --priority 5
vt post bulk-tag <project> --tag "viral" --min-views 100000
```

---

**Document will be updated as new enhancements are identified**
