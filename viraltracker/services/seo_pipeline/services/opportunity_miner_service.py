"""
OpportunityMinerService — detect near-ranking SEO opportunities and generate reports.

Scans GSC ranking data for keywords at positions 4-20, scores them by multiple
signals, classifies recommended actions, and generates weekly digest reports
for the Activity Feed.

Two opportunity types:
- page1_improvement (positions 4-10): already on page 1, push into top 3
- striking_distance (positions 11-20): near page 1, push onto it

Phase 1 = intelligence + reporting. Phase 2 = automated execution.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class OpportunityMinerService:
    """Detect near-ranking SEO opportunities and generate weekly reports."""

    def __init__(self, supabase_client=None):
        self._supabase = supabase_client

    @property
    def supabase(self):
        """Lazy-load Supabase client."""
        if self._supabase is None:
            from viraltracker.core.database import get_supabase_client
            self._supabase = get_supabase_client()
        return self._supabase

    def _resolve_org_id(self, organization_id: str, brand_id: str) -> str:
        """Resolve real UUID org_id from brand when superuser passes 'all'."""
        if organization_id != "all":
            return organization_id
        row = self.supabase.table("brands").select("organization_id").eq("id", brand_id).limit(1).execute()
        if row.data:
            return row.data[0]["organization_id"]
        return organization_id

    # =========================================================================
    # SCORING COMPONENTS
    # =========================================================================

    def _score_impression_trend(self, recent_14d: int, previous_14d: int) -> float:
        """Score impression trend (30% weight).

        Rising (>10% increase) = 100, Stable = 50, Declining = 20.
        """
        if previous_14d <= 0:
            # No prior data — treat as stable
            return 50.0
        change_pct = (recent_14d - previous_14d) / previous_14d
        if change_pct > 0.10:
            return 100.0
        elif change_pct >= -0.10:
            return 50.0
        else:
            return 20.0

    def _score_position_proximity(self, position: float) -> float:
        """Score position proximity (30% weight).

        Positions 4-6 = 100 (easiest wins, already top half of page 1).
        Position 7-10 = 80-60 (bottom of page 1, still very reachable).
        Position 11 = 50, position 20 = 10 (striking distance, harder push).
        """
        if position <= 6:
            return 100.0
        if position <= 10:
            # 7→80, 8→73, 9→67, 10→60
            return 80.0 - (position - 7) * (20.0 / 3)
        if position >= 20:
            return 10.0
        # 11→50, 20→10
        return 50.0 - (position - 11) * (40.0 / 9)

    def _score_keyword_volume(
        self,
        keyword: str,
        brand_id: str,
        volume_percentile_90: float,
    ) -> float:
        """Score keyword volume (20% weight).

        Normalize monthly search volume 0-100, capped at 90th percentile.
        """
        try:
            kw_res = (
                self.supabase.table("seo_keywords")
                .select("search_volume")
                .eq("keyword", keyword)
                .limit(1)
                .execute()
            )
            if not kw_res.data or kw_res.data[0].get("search_volume") is None:
                return 0.0
            volume = float(kw_res.data[0]["search_volume"])
        except Exception:
            return 0.0

        if volume_percentile_90 <= 0:
            return 50.0
        score = min(volume / volume_percentile_90, 1.0) * 100.0
        return score

    def _score_cluster_gap(self, article_id: str, cluster_map: Dict[str, int]) -> float:
        """Score cluster gap (20% weight).

        Step function: 0 supporting = 100, 1 = 80, 2 = 60, 3 = 40, 4 = 20, 5+ = 0.
        Articles with no cluster entry (orphans) get 100.
        """
        supporting_count = cluster_map.get(article_id, -1)
        if supporting_count < 0:
            # No cluster association — orphan, maximum gap
            return 100.0
        return max(0.0, (5 - supporting_count) * 20.0)

    # =========================================================================
    # SCAN OPPORTUNITIES
    # =========================================================================

    def scan_opportunities(
        self,
        brand_id: str,
        organization_id: str,
    ) -> List[Dict[str, Any]]:
        """Scan for opportunity keywords (positions 4-20) and score opportunities.

        Args:
            brand_id: Brand UUID
            organization_id: Organization UUID (may be "all" for superuser)

        Returns:
            List of scored opportunity dicts ready for UPSERT into seo_opportunities
        """
        real_org_id = self._resolve_org_id(organization_id, brand_id)
        now = datetime.now(timezone.utc)
        cutoff_28d = (now - timedelta(days=28)).isoformat()
        cutoff_14d = (now - timedelta(days=14)).isoformat()

        # Fetch ranking data for this brand's articles over last 28 days
        # JOIN path: seo_article_rankings → seo_articles (for brand_id filter)
        try:
            articles_res = (
                self.supabase.table("seo_articles")
                .select("id")
                .eq("brand_id", brand_id)
                .execute()
            )
            article_ids = [a["id"] for a in (articles_res.data or [])]
        except Exception as e:
            logger.error(f"Failed to load articles for brand {brand_id}: {e}")
            return []

        if not article_ids:
            logger.info(f"No articles for brand {brand_id}, skipping opportunity scan")
            return []

        # Batch fetch rankings for all articles (avoid N+1)
        all_rankings = []
        for i in range(0, len(article_ids), 50):
            batch_ids = article_ids[i:i + 50]
            try:
                rank_res = (
                    self.supabase.table("seo_article_rankings")
                    .select("article_id, keyword, position, impressions, clicks, checked_at")
                    .in_("article_id", batch_ids)
                    .gte("checked_at", cutoff_28d)
                    .execute()
                )
                all_rankings.extend(rank_res.data or [])
            except Exception as e:
                logger.error(f"Failed to fetch rankings batch: {e}")

        if not all_rankings:
            logger.info(f"No ranking data for brand {brand_id} in last 28 days")
            return []

        # Group rankings by (article_id, keyword)
        grouped: Dict[tuple, List[Dict]] = {}
        for r in all_rankings:
            key = (r["article_id"], r["keyword"])
            grouped.setdefault(key, []).append(r)

        # Filter for average position 4-20
        candidates = []
        for (article_id, keyword), rows in grouped.items():
            positions = [float(r["position"]) for r in rows if r.get("position") is not None]
            if not positions:
                continue
            avg_position = sum(positions) / len(positions)
            if avg_position < 4 or avg_position > 20:
                continue

            # Split impressions into recent 14d vs previous 14d
            recent_imps = 0
            previous_imps = 0
            for r in rows:
                checked = r.get("checked_at", "")
                imps = r.get("impressions") or 0
                if checked >= cutoff_14d:
                    recent_imps += imps
                else:
                    previous_imps += imps

            candidates.append({
                "article_id": article_id,
                "keyword": keyword,
                "avg_position": avg_position,
                "recent_14d_impressions": recent_imps,
                "previous_14d_impressions": previous_imps,
                "total_impressions_14d": recent_imps,
                "total_impressions_28d": recent_imps + previous_imps,
            })

        if not candidates:
            logger.info(f"No keywords in position 4-20 for brand {brand_id}")
            return []

        # Batch cluster queries — single IN() query for all candidate article_ids
        candidate_article_ids = list({c["article_id"] for c in candidates})
        cluster_map = self._build_cluster_map(candidate_article_ids)

        # Compute 90th percentile keyword volume for this brand's project
        volume_p90 = self._get_volume_percentile_90(brand_id)

        # Score each candidate
        opportunities = []
        for c in candidates:
            trend_score = self._score_impression_trend(
                c["recent_14d_impressions"], c["previous_14d_impressions"]
            )
            proximity_score = self._score_position_proximity(c["avg_position"])
            volume_score = self._score_keyword_volume(c["keyword"], brand_id, volume_p90)
            gap_score = self._score_cluster_gap(c["article_id"], cluster_map)

            total_score = (
                trend_score * 0.3
                + proximity_score * 0.3
                + volume_score * 0.2
                + gap_score * 0.2
            )

            # Determine impression trend label
            if c["previous_14d_impressions"] > 0:
                change = (c["recent_14d_impressions"] - c["previous_14d_impressions"]) / c["previous_14d_impressions"]
                trend = "rising" if change > 0.10 else ("declining" if change < -0.10 else "stable")
            else:
                trend = "stable"

            # Classify action
            action_info = self.classify_action({
                "article_id": c["article_id"],
                "keyword": c["keyword"],
                "cluster_map": cluster_map,
            })

            # Classify opportunity type
            opp_type = "page1_improvement" if c["avg_position"] <= 10 else "striking_distance"

            opportunities.append({
                "organization_id": real_org_id,
                "brand_id": brand_id,
                "article_id": c["article_id"],
                "keyword": c["keyword"],
                "current_position": round(c["avg_position"], 2),
                "position_at_identification": round(c["avg_position"], 2),
                "opportunity_type": opp_type,
                "impression_trend": trend,
                "impressions_14d": c["total_impressions_14d"],
                "impressions_28d": c["total_impressions_28d"],
                "opportunity_score": round(total_score, 2),
                "recommended_action": action_info["action"],
                "action_reason": action_info["reason"],
                "status": "identified",
            })

        # Sort by score descending
        opportunities.sort(key=lambda x: x["opportunity_score"], reverse=True)
        logger.info(
            f"Found {len(opportunities)} opportunities for brand {brand_id} "
            f"(top score: {opportunities[0]['opportunity_score'] if opportunities else 0})"
        )
        return opportunities

    def _build_cluster_map(self, article_ids: List[str]) -> Dict[str, int]:
        """Build a map of article_id -> supporting_article_count via seo_cluster_spokes.

        Returns dict where key = article_id, value = count of OTHER articles in same cluster.
        Articles not in any cluster are absent from the map (treated as orphans).
        """
        if not article_ids:
            return {}

        try:
            # Get cluster assignments for all candidate articles
            spoke_res = (
                self.supabase.table("seo_cluster_spokes")
                .select("article_id, cluster_id")
                .in_("article_id", article_ids)
                .execute()
            )
            spokes = spoke_res.data or []
        except Exception as e:
            logger.error(f"Failed to query cluster spokes: {e}")
            return {}

        if not spokes:
            return {}

        # Map article -> cluster
        article_to_cluster = {s["article_id"]: s["cluster_id"] for s in spokes}
        cluster_ids = list(set(article_to_cluster.values()))

        # Count articles per cluster
        try:
            count_res = (
                self.supabase.table("seo_cluster_spokes")
                .select("cluster_id, article_id")
                .in_("cluster_id", cluster_ids)
                .execute()
            )
            count_data = count_res.data or []
        except Exception as e:
            logger.error(f"Failed to count cluster articles: {e}")
            return {}

        # Count per cluster
        cluster_counts: Dict[str, int] = {}
        for row in count_data:
            cid = row["cluster_id"]
            cluster_counts[cid] = cluster_counts.get(cid, 0) + 1

        # Map back: for each candidate article, supporting count = cluster total - 1 (exclude self)
        result = {}
        for article_id, cluster_id in article_to_cluster.items():
            total = cluster_counts.get(cluster_id, 1)
            result[article_id] = max(0, total - 1)

        return result

    def _get_volume_percentile_90(self, brand_id: str) -> float:
        """Get 90th percentile search volume for keywords in this brand's projects."""
        try:
            # Get project IDs for this brand
            proj_res = (
                self.supabase.table("seo_projects")
                .select("id")
                .eq("brand_id", brand_id)
                .execute()
            )
            project_ids = [p["id"] for p in (proj_res.data or [])]
            if not project_ids:
                return 0.0

            # Get all keyword volumes
            kw_res = (
                self.supabase.table("seo_keywords")
                .select("search_volume")
                .in_("project_id", project_ids)
                .not_.is_("search_volume", "null")
                .execute()
            )
            volumes = sorted([
                float(k["search_volume"])
                for k in (kw_res.data or [])
                if k.get("search_volume") is not None
            ])

            if not volumes:
                return 0.0

            # 90th percentile
            idx = int(len(volumes) * 0.9)
            return volumes[min(idx, len(volumes) - 1)]

        except Exception as e:
            logger.error(f"Failed to compute volume percentile: {e}")
            return 0.0

    # =========================================================================
    # CLASSIFY ACTION
    # =========================================================================

    def classify_action(self, opportunity: Dict[str, Any]) -> Dict[str, str]:
        """Classify the recommended action for an opportunity.

        Decision tree:
        1. Discovered article → skip REFRESH (only suggest new/links)
        2. Content age >1 year → REFRESH
        3. time_sensitive metadata flag → REFRESH
        4. No cluster association → NEW_SUPPORTING_CONTENT
        5. Cluster <3 supporting articles → NEW_SUPPORTING_CONTENT
        6. Cluster 5+ supporting articles → OPTIMIZE_LINKS
        7. Default → NEW_SUPPORTING_CONTENT

        Args:
            opportunity: Dict with article_id, keyword, and optionally cluster_map

        Returns:
            Dict with 'action' and 'reason' keys
        """
        article_id = opportunity.get("article_id")
        cluster_map = opportunity.get("cluster_map", {})

        if not article_id:
            return {"action": "new_supporting_content", "reason": "No article associated"}

        # Load article data
        try:
            art_res = (
                self.supabase.table("seo_articles")
                .select("published_at, created_at, source, metadata")
                .eq("id", article_id)
                .limit(1)
                .execute()
            )
            article = art_res.data[0] if art_res.data else None
        except Exception:
            article = None

        if not article:
            return {"action": "new_supporting_content", "reason": "Article not found"}

        # 1. Discovered article — skip REFRESH
        is_discovered = article.get("source") == "discovered"

        # 2. Content age >1 year
        if not is_discovered:
            pub_date_str = article.get("published_at") or article.get("created_at")
            if pub_date_str:
                try:
                    pub_date = datetime.fromisoformat(pub_date_str.replace("Z", "+00:00"))
                    age_days = (datetime.now(timezone.utc) - pub_date).days
                    if age_days > 365:
                        return {
                            "action": "refresh",
                            "reason": f"Content is {age_days} days old (>{365} day threshold)",
                        }
                except (ValueError, TypeError):
                    pass

            # 3. time_sensitive flag
            metadata = article.get("metadata") or {}
            if metadata.get("time_sensitive"):
                return {
                    "action": "refresh",
                    "reason": "Article flagged as time-sensitive content",
                }

        # 4. No cluster association
        supporting_count = cluster_map.get(article_id, -1)
        if supporting_count < 0:
            return {
                "action": "new_supporting_content",
                "reason": "Article has no cluster — create new cluster around this keyword",
            }

        # 5. Cluster <3 supporting articles
        if supporting_count < 3:
            return {
                "action": "new_supporting_content",
                "reason": f"Cluster has only {supporting_count} supporting articles (need 3+)",
            }

        # 6. Cluster 5+ supporting articles
        if supporting_count >= 5:
            return {
                "action": "optimize_links",
                "reason": f"Cluster has {supporting_count} articles — optimize interlinking",
            }

        # 7. Default
        return {
            "action": "new_supporting_content",
            "reason": f"Cluster has {supporting_count} supporting articles — add more",
        }

    # =========================================================================
    # WEEKLY REPORT
    # =========================================================================

    def generate_weekly_report(
        self,
        brand_id: str,
        organization_id: str,
    ) -> Dict[str, Any]:
        """Generate a weekly SEO performance report for a brand.

        Aggregates: articles published this week, ranking movements,
        top opportunities, impression/click trends.

        Args:
            brand_id: Brand UUID
            organization_id: Organization UUID

        Returns:
            Dict matching the seo_weekly_report Activity Feed event format
        """
        now = datetime.now(timezone.utc)
        week_start = (now - timedelta(days=7)).isoformat()
        period_start = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        period_end = now.strftime("%Y-%m-%d")

        # Articles published this week
        articles_published = 0
        try:
            pub_res = (
                self.supabase.table("seo_articles")
                .select("id", count="exact")
                .eq("brand_id", brand_id)
                .gte("published_at", week_start)
                .execute()
            )
            articles_published = pub_res.count or 0
        except Exception as e:
            logger.warning(f"Failed to count published articles: {e}")

        # Impression and click trends (this week vs last week)
        impressions_this_week = 0
        clicks_this_week = 0
        impressions_last_week = 0
        clicks_last_week = 0
        two_weeks_ago = (now - timedelta(days=14)).isoformat()

        try:
            # Get article IDs for this brand
            art_ids_res = (
                self.supabase.table("seo_articles")
                .select("id")
                .eq("brand_id", brand_id)
                .execute()
            )
            art_ids = [a["id"] for a in (art_ids_res.data or [])]

            if art_ids:
                for i in range(0, len(art_ids), 50):
                    batch = art_ids[i:i + 50]
                    # This week
                    tw_res = (
                        self.supabase.table("seo_article_rankings")
                        .select("impressions, clicks")
                        .in_("article_id", batch)
                        .gte("checked_at", week_start)
                        .execute()
                    )
                    for r in (tw_res.data or []):
                        impressions_this_week += r.get("impressions") or 0
                        clicks_this_week += r.get("clicks") or 0

                    # Last week
                    lw_res = (
                        self.supabase.table("seo_article_rankings")
                        .select("impressions, clicks")
                        .in_("article_id", batch)
                        .gte("checked_at", two_weeks_ago)
                        .lt("checked_at", week_start)
                        .execute()
                    )
                    for r in (lw_res.data or []):
                        impressions_last_week += r.get("impressions") or 0
                        clicks_last_week += r.get("clicks") or 0

        except Exception as e:
            logger.warning(f"Failed to compute impression/click trends: {e}")

        impressions_delta = impressions_this_week - impressions_last_week
        clicks_delta = clicks_this_week - clicks_last_week

        # Top opportunities (from seo_opportunities table)
        top_opportunities = []
        try:
            opp_res = (
                self.supabase.table("seo_opportunities")
                .select("keyword, current_position, recommended_action, opportunity_score")
                .eq("brand_id", brand_id)
                .eq("status", "identified")
                .order("opportunity_score", desc=True)
                .limit(5)
                .execute()
            )
            for o in (opp_res.data or []):
                top_opportunities.append({
                    "keyword": o["keyword"],
                    "position": float(o["current_position"]) if o.get("current_position") else None,
                    "action": o["recommended_action"],
                    "score": float(o["opportunity_score"]) if o.get("opportunity_score") else 0,
                })
        except Exception as e:
            logger.warning(f"Failed to fetch top opportunities: {e}")

        # Rank milestones — articles that moved to page 1 this week
        rank_milestones = []
        try:
            milestone_res = (
                self.supabase.table("seo_opportunities")
                .select("keyword, position_at_identification, current_position")
                .eq("brand_id", brand_id)
                .lte("current_position", 10)
                .gt("position_at_identification", 10)
                .execute()
            )
            for m in (milestone_res.data or []):
                rank_milestones.append({
                    "keyword": m["keyword"],
                    "from": float(m["position_at_identification"]),
                    "to": float(m["current_position"]),
                })
        except Exception as e:
            logger.warning(f"Failed to fetch rank milestones: {e}")

        report = {
            "period": f"{period_start} to {period_end}",
            "articles_published": articles_published,
            "total_impressions_delta": f"{'+' if impressions_delta >= 0 else ''}{impressions_delta:,}",
            "total_clicks_delta": f"{'+' if clicks_delta >= 0 else ''}{clicks_delta:,}",
            "impressions_this_week": impressions_this_week,
            "clicks_this_week": clicks_this_week,
            "top_opportunities": top_opportunities,
            "rank_milestones": rank_milestones,
        }

        logger.info(
            f"Weekly report for brand {brand_id}: "
            f"{articles_published} published, {impressions_delta:+,} impressions, "
            f"{len(top_opportunities)} opportunities"
        )
        return report

    # =========================================================================
    # UPSERT OPPORTUNITIES
    # =========================================================================

    def upsert_opportunities(self, opportunities: List[Dict[str, Any]]) -> int:
        """UPSERT scored opportunities into seo_opportunities table.

        Uses (article_id, keyword) unique constraint for dedup.

        Returns:
            Number of rows upserted
        """
        if not opportunities:
            return 0

        total = 0
        for i in range(0, len(opportunities), 50):
            batch = opportunities[i:i + 50]
            for row in batch:
                row["updated_at"] = datetime.now(timezone.utc).isoformat()
            try:
                self.supabase.table("seo_opportunities").upsert(
                    batch,
                    on_conflict="article_id,keyword",
                ).execute()
                total += len(batch)
            except Exception as e:
                logger.error(f"Failed to upsert opportunities batch: {e}")

        logger.info(f"Upserted {total} opportunities")
        return total

    # =========================================================================
    # RANK DELTA TRACKING
    # =========================================================================

    def update_rank_deltas(self, brand_id: str) -> int:
        """Update rank deltas for actioned opportunities.

        For each actioned opportunity where rank_delta columns are still NULL:
        - Query latest position from seo_article_rankings
        - Compute delta = latest_position - position_at_identification
        - Set rank_delta_7d if NULL and days_since_actioned >= 7
        - Set rank_delta_14d if NULL and days_since_actioned >= 14
        - Set rank_delta_28d if NULL and days_since_actioned >= 28
        Each delta is a one-time snapshot, frozen after first qualifying scan.

        Returns:
            Number of opportunities updated
        """
        try:
            # Fetch actioned opportunities with at least one NULL delta
            opp_res = (
                self.supabase.table("seo_opportunities")
                .select("id, article_id, keyword, position_at_identification, actioned_at, rank_delta_7d, rank_delta_14d, rank_delta_28d")
                .eq("brand_id", brand_id)
                .eq("status", "actioned")
                .execute()
            )
            candidates = [
                o for o in (opp_res.data or [])
                if o.get("actioned_at") and (
                    o.get("rank_delta_7d") is None
                    or o.get("rank_delta_14d") is None
                    or o.get("rank_delta_28d") is None
                )
            ]
        except Exception as e:
            logger.error(f"Failed to fetch actioned opportunities: {e}")
            return 0

        if not candidates:
            return 0

        now = datetime.now(timezone.utc)
        updated = 0

        for opp in candidates:
            actioned_at = datetime.fromisoformat(opp["actioned_at"].replace("Z", "+00:00"))
            days_since = (now - actioned_at).days
            baseline = float(opp["position_at_identification"]) if opp.get("position_at_identification") else None

            if baseline is None:
                continue

            # Get latest position for this article+keyword
            try:
                pos_res = (
                    self.supabase.table("seo_article_rankings")
                    .select("position")
                    .eq("article_id", opp["article_id"])
                    .eq("keyword", opp["keyword"])
                    .order("checked_at", desc=True)
                    .limit(1)
                    .execute()
                )
                if not pos_res.data:
                    continue
                latest_position = float(pos_res.data[0]["position"])
            except Exception:
                continue

            delta = latest_position - baseline
            updates = {}

            if opp.get("rank_delta_7d") is None and days_since >= 7:
                updates["rank_delta_7d"] = round(delta, 2)
            if opp.get("rank_delta_14d") is None and days_since >= 14:
                updates["rank_delta_14d"] = round(delta, 2)
            if opp.get("rank_delta_28d") is None and days_since >= 28:
                updates["rank_delta_28d"] = round(delta, 2)

            if updates:
                updates["updated_at"] = now.isoformat()
                try:
                    self.supabase.table("seo_opportunities").update(updates).eq("id", opp["id"]).execute()
                    updated += 1
                except Exception as e:
                    logger.error(f"Failed to update rank delta for opportunity {opp['id']}: {e}")

        logger.info(f"Updated rank deltas for {updated} opportunities (brand {brand_id})")
        return updated
