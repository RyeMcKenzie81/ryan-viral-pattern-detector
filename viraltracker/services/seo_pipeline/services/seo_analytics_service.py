"""
SEO Analytics Service - Ranking history and project-level analytics.

Handles:
- Recording keyword ranking positions
- Retrieving ranking history per article
- Project-level dashboard analytics (aggregated KPIs)
- Internal link statistics

All queries filter by organization_id for multi-tenancy.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class SEOAnalyticsService:
    """Service for SEO ranking tracking and analytics."""

    def __init__(self, supabase_client=None):
        self._supabase = supabase_client

    @property
    def supabase(self):
        """Lazy-load Supabase client."""
        if self._supabase is None:
            from viraltracker.core.database import get_supabase_client
            self._supabase = get_supabase_client()
        return self._supabase

    # =========================================================================
    # RANKING TRACKING
    # =========================================================================

    def record_ranking(
        self,
        article_id: str,
        keyword: str,
        position: int,
        checked_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Record a keyword ranking data point.

        Args:
            article_id: Article UUID
            keyword: Keyword being tracked
            position: SERP position (1-100+)
            checked_at: ISO timestamp (defaults to now)

        Returns:
            Created ranking record
        """
        data = {
            "article_id": article_id,
            "keyword": keyword,
            "position": position,
        }
        if checked_at:
            data["checked_at"] = checked_at

        result = self.supabase.table("seo_article_rankings").insert(data).execute()
        logger.info(f"Recorded ranking: article={article_id[:8]}... keyword='{keyword}' position={position}")
        return result.data[0] if result.data else data

    def get_ranking_history(
        self,
        article_id: str,
        keyword: Optional[str] = None,
        days: int = 30,
    ) -> List[Dict[str, Any]]:
        """
        Get ranking history for an article.

        Args:
            article_id: Article UUID
            keyword: Optional keyword filter (all keywords if omitted)
            days: Number of days to look back (default: 30)

        Returns:
            List of ranking records ordered by checked_at descending
        """
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        query = (
            self.supabase.table("seo_article_rankings")
            .select("*")
            .eq("article_id", article_id)
            .gte("checked_at", since)
        )
        if keyword:
            query = query.eq("keyword", keyword)

        result = query.order("checked_at", desc=True).execute()
        return result.data or []

    def get_latest_rankings(
        self,
        project_id: str,
        organization_id: str,
    ) -> List[Dict[str, Any]]:
        """
        Get the latest ranking for each article in a project.

        Fetches all articles in the project, then gets the most recent
        ranking for each.

        Args:
            project_id: SEO project UUID
            organization_id: Org UUID for access control

        Returns:
            List of dicts with article_id, keyword, position, checked_at
        """
        # Get articles for the project
        query = (
            self.supabase.table("seo_articles")
            .select("id, keyword")
            .eq("project_id", project_id)
        )
        if organization_id != "all":
            query = query.eq("organization_id", organization_id)
        articles = query.execute().data or []

        rankings = []
        for article in articles:
            history = self.get_ranking_history(article["id"], days=90)
            if history:
                latest = history[0]
                rankings.append({
                    "article_id": article["id"],
                    "keyword": article.get("keyword", latest.get("keyword", "")),
                    "position": latest.get("position"),
                    "checked_at": latest.get("checked_at"),
                })

        return rankings

    # =========================================================================
    # PROJECT DASHBOARD
    # =========================================================================

    def _get_link_stats_batch(self, article_ids: List[str]) -> Dict[str, int]:
        """Get internal link stats using batch .in_() query instead of N+1 loop."""
        link_stats = {"suggested": 0, "implemented": 0, "total": 0}
        if not article_ids:
            return link_stats

        # Batch query: up to 50 article IDs at once
        batch_ids = article_ids[:50]
        link_query = (
            self.supabase.table("seo_internal_links")
            .select("id, status")
            .in_("source_article_id", batch_ids)
        )
        links = link_query.execute().data or []
        for link in links:
            link_stats["total"] += 1
            if link.get("status") == "implemented":
                link_stats["implemented"] += 1
            elif link.get("status") == "pending":
                link_stats["suggested"] += 1

        return link_stats

    def get_project_dashboard(
        self,
        project_id: str,
        organization_id: str,
    ) -> Dict[str, Any]:
        """
        Get comprehensive project dashboard analytics.

        Returns:
            Dict with:
            - total_articles, status_counts, published_count
            - total_keywords, selected_keywords
            - internal_links (suggested, implemented)
        """
        # Article stats (exclude discovered pages from KPIs)
        article_query = (
            self.supabase.table("seo_articles")
            .select("id, keyword, status, published_url, cms_article_id")
            .eq("project_id", project_id)
            .neq("status", "discovered")
        )
        if organization_id != "all":
            article_query = article_query.eq("organization_id", organization_id)
        articles = article_query.execute().data or []

        status_counts = {}
        for a in articles:
            s = a.get("status", "unknown")
            status_counts[s] = status_counts.get(s, 0) + 1

        published = [a for a in articles if a.get("published_url")]

        # Keyword stats
        keyword_query = (
            self.supabase.table("seo_keywords")
            .select("id, status")
            .eq("project_id", project_id)
        )
        keywords = keyword_query.execute().data or []
        keyword_status = {}
        for k in keywords:
            s = k.get("status", "unknown")
            keyword_status[s] = keyword_status.get(s, 0) + 1

        # Internal link stats — batch query
        article_ids = [a["id"] for a in articles]
        link_stats = self._get_link_stats_batch(article_ids)

        return {
            "project_id": project_id,
            "articles": {
                "total": len(articles),
                "published": len(published),
                "status_counts": status_counts,
            },
            "keywords": {
                "total": len(keywords),
                "status_counts": keyword_status,
            },
            "links": link_stats,
        }

    def get_brand_dashboard(
        self,
        brand_id: str,
        organization_id: str,
    ) -> Dict[str, Any]:
        """
        Get brand-level dashboard aggregated across all projects.

        Returns zero-state dict when no projects exist (never errors).

        Returns:
            Dict with articles, keywords, links, projects counts
        """
        zero_state = {
            "articles": {"total": 0, "published": 0, "status_counts": {}},
            "keywords": {"total": 0, "status_counts": {}},
            "links": {"suggested": 0, "implemented": 0, "total": 0},
            "projects": {"total": 0, "active": 0},
        }

        # Get projects for brand
        project_query = (
            self.supabase.table("seo_projects")
            .select("id, status")
            .eq("brand_id", brand_id)
        )
        if organization_id != "all":
            project_query = project_query.eq("organization_id", organization_id)
        projects = project_query.execute().data or []

        if not projects:
            return zero_state

        project_ids = [p["id"] for p in projects]
        active_projects = [p for p in projects if p.get("status") != "archived"]

        # Articles by brand_id (exclude discovered pages from KPIs)
        article_query = (
            self.supabase.table("seo_articles")
            .select("id, keyword, status, published_url")
            .eq("brand_id", brand_id)
            .neq("status", "discovered")
        )
        if organization_id != "all":
            article_query = article_query.eq("organization_id", organization_id)
        articles = article_query.execute().data or []

        status_counts = {}
        for a in articles:
            s = a.get("status", "unknown")
            status_counts[s] = status_counts.get(s, 0) + 1
        published = [a for a in articles if a.get("published_url")]

        # Keywords — batch by project IDs
        keyword_query = (
            self.supabase.table("seo_keywords")
            .select("id, status")
            .in_("project_id", project_ids)
        )
        keywords = keyword_query.execute().data or []
        keyword_status = {}
        for k in keywords:
            s = k.get("status", "unknown")
            keyword_status[s] = keyword_status.get(s, 0) + 1

        # Internal links — batch by article IDs
        article_ids = [a["id"] for a in articles]
        link_stats = self._get_link_stats_batch(article_ids)

        return {
            "articles": {
                "total": len(articles),
                "published": len(published),
                "status_counts": status_counts,
            },
            "keywords": {
                "total": len(keywords),
                "status_counts": keyword_status,
            },
            "links": link_stats,
            "projects": {
                "total": len(projects),
                "active": len(active_projects),
            },
        }

    def get_brand_orphans(
        self,
        brand_id: str,
        organization_id: str,
    ) -> Dict[str, Any]:
        """
        Brand-wide list of ORPHAN published articles.

        Orphan = a published article (published_url IS NOT NULL) with ZERO
        implemented inbound internal links. Orphans receive no internal link
        equity and rarely rank — this is the brand-level signal for whether
        interlinking is actually working.

        Filters by brand_id, which pins the organization, so a superuser's
        organization_id='all' needs no UUID resolution here (we only add the org
        filter when it is a concrete id). Read-only.

        Returns:
            {
              "published_count": int,
              "orphan_count": int,
              "orphan_pct": float,
              "orphans": [ {article_id, keyword, published_url, project_id} ],
            }
        """
        zero_state = {
            "published_count": 0,
            "orphan_count": 0,
            "orphan_pct": 0.0,
            "exempt_count": 0,
            "orphans": [],
        }

        # Live = status 'published' (set by the publish flow / mark_published) AND
        # a published_url. published_url alone is NOT a live signal: Shopify DRAFT
        # publishes and the transient 'publishing' state also carry a url, and
        # imported 'discovered' pages have urls — any of those would manufacture
        # false orphans. The url check is a defensive co-filter.
        article_query = (
            self.supabase.table("seo_articles")
            # select("*") so a missing interlink_exempt column (migration not
            # applied yet) reads as not-exempt instead of erroring.
            .select("*")
            .eq("brand_id", brand_id)
            .eq("status", "published")
        )
        if organization_id and organization_id != "all":
            article_query = article_query.eq("organization_id", organization_id)
        rows = article_query.execute().data or []
        published = [a for a in rows if (a.get("published_url") or "").strip()]
        if not published:
            return zero_state

        published_ids = [a["id"] for a in published]
        # Source-scope inbound to the brand's live set: seo_internal_links has no
        # brand column, so an unscoped count could be inflated by a cross-brand or
        # dead-source 'implemented' row and hide a real orphan.
        from viraltracker.services.seo_pipeline.services.interlinking_service import (
            InterlinkingService,
        )
        inbound = InterlinkingService(supabase_client=self.supabase).count_inbound_links(
            published_ids, source_ids=published_ids
        )

        # interlink_exempt articles (intentional standalones, R6) are not
        # orphans — they are deliberately outside the link graph. Counted
        # separately so they stay visible without polluting the orphan rate.
        exempt_count = sum(1 for a in published if a.get("interlink_exempt"))
        orphans = [
            {
                "article_id": a["id"],
                "keyword": a.get("keyword") or "(untitled)",
                "published_url": a.get("published_url"),
                "project_id": a.get("project_id"),
            }
            for a in published
            if inbound.get(a["id"], 0) == 0 and not a.get("interlink_exempt")
        ]
        published_count = len(published) - exempt_count
        orphan_count = len(orphans)
        orphan_pct = round(orphan_count / published_count * 100, 1) if published_count else 0.0
        return {
            "published_count": published_count,
            "orphan_count": orphan_count,
            "orphan_pct": orphan_pct,
            "exempt_count": exempt_count,
            "orphans": orphans,
        }

    # =========================================================================
    # LINK IMPACT (§7 increment 2 — R7: directional telemetry)
    # =========================================================================

    # A feed older than this gates the Link Impact card (R3: stale ⇒ red badge
    # AND the correlation claim suppressed — stale data must not drive ranking
    # claims). Matches OpportunityMinerService.FEED_STALE_DAYS.
    LINK_IMPACT_STALE_DAYS = 7

    def get_link_impact(
        self,
        brand_id: str,
        organization_id: str,
        window_days: int = 90,
    ) -> Dict[str, Any]:
        """R7: link-gain vs position-movement, framed as DIRECTIONAL telemetry.

        Explicitly NOT a causal claim — position movement is confounded by
        topic, age, intent, and authority, so no "+N links ≈ +M positions"
        coefficient is computed. The card groups articles by whether they
        GAINED inbound links over the window and reports the median position
        delta per bucket. Useful direction, honest about strength.

        Link-count series:
        - MEASURED: seo_link_coverage_snapshots (weekly, started 2026-06-09).
        - APPROXIMATE (cold start): reconstructed from implemented AUTO link
          created_at timestamps (idempotent writes preserved them). Related-
          block (bidirectional) records churn their timestamps, so the
          reconstruction UNDERCOUNTS — every series it feeds is labeled
          approximate and is replaced by measured data as snapshots accrue.

        Position series: seo_article_analytics (source=gsc, daily). Delta =
        avg(last 7 days with data) - avg(first 7 days with data) inside the
        window; NEGATIVE = improved (moved up).

        Staleness gates the card: GSC data older than LINK_IMPACT_STALE_DAYS
        sets stale=True and the UI suppresses the buckets entirely (R3).

        Returns:
            {
              "window_days": int,
              "data_as_of": {"gsc": iso|None, "snapshots": iso|None},
              "stale": bool,
              "measured_since": iso|None,   # earliest snapshot day (provenance switch)
              "articles": [{article_id, keyword, link_gain, links_now,
                            position_first, position_now, position_delta,
                            provenance}],
              "buckets": {bucket: {"count": int, "median_position_delta": float|None}},
              "insufficient_data": bool,
            }
        """
        now = datetime.now(timezone.utc)
        window_start = (now - timedelta(days=window_days)).date()

        empty: Dict[str, Any] = {
            "window_days": window_days,
            "data_as_of": {"gsc": None, "snapshots": None},
            "stale": True,
            "measured_since": None,
            "articles": [],
            "buckets": {},
            "insufficient_data": True,
        }

        # Live article set (same definition as everywhere: published + url).
        art_query = (
            self.supabase.table("seo_articles")
            .select("*")
            .eq("brand_id", brand_id)
            .eq("status", "published")
        )
        if organization_id and organization_id != "all":
            art_query = art_query.eq("organization_id", organization_id)
        live = [
            a for a in (art_query.execute().data or [])
            if (a.get("published_url") or "").strip()
        ]
        if not live:
            return empty
        live_ids = [a["id"] for a in live]
        kw_by_id = {a["id"]: a.get("keyword") or "(untitled)" for a in live}

        # --- Position series (GSC) -------------------------------------------
        pos_rows: List[Dict[str, Any]] = []
        for i in range(0, len(live_ids), 50):
            batch = live_ids[i:i + 50]
            try:
                res = (
                    self.supabase.table("seo_article_analytics")
                    .select("article_id, date, average_position")
                    .in_("article_id", batch)
                    .eq("source", "gsc")
                    # One row per search_type exists (web/image/video) — only
                    # web positions are the ranking signal; averaging across
                    # types corrupts the delta.
                    .eq("search_type", "web")
                    .gte("date", window_start.isoformat())
                    .execute()
                )
                pos_rows.extend(res.data or [])
            except Exception as e:
                logger.warning(f"Link impact: GSC fetch failed: {e}")

        gsc_newest = max((r["date"] for r in pos_rows), default=None)
        stale = True
        if gsc_newest:
            try:
                age = (now.date() - datetime.fromisoformat(str(gsc_newest)).date()).days
                stale = age > self.LINK_IMPACT_STALE_DAYS
            except Exception:
                stale = True

        # Per-article first/last 7-days-with-data position averages.
        by_article: Dict[str, List[tuple]] = {}
        for r in pos_rows:
            if r.get("average_position") is None:
                continue
            by_article.setdefault(r["article_id"], []).append(
                (str(r["date"]), float(r["average_position"]))
            )

        def _edge_avg(series: List[tuple], last: bool) -> Optional[float]:
            days = sorted({d for d, _ in series}, reverse=last)[:7]
            vals = [p for d, p in series if d in days]
            return round(sum(vals) / len(vals), 2) if vals else None

        # --- Link-count series ------------------------------------------------
        # Measured: earliest + latest snapshot per article in the window.
        snap_first: Dict[str, tuple] = {}
        snap_last: Dict[str, tuple] = {}
        measured_since: Optional[str] = None
        snap_newest: Optional[str] = None
        try:
            snaps = (
                self.supabase.table("seo_link_coverage_snapshots")
                .select("article_id, captured_on, inbound_count")
                .eq("brand_id", brand_id)
                .gte("captured_on", window_start.isoformat())
                .execute()
            )
            for s in (snaps.data or []):
                key = s["article_id"]
                day = str(s["captured_on"])
                if key not in snap_first or day < snap_first[key][0]:
                    snap_first[key] = (day, s["inbound_count"])
                if key not in snap_last or day > snap_last[key][0]:
                    snap_last[key] = (day, s["inbound_count"])
                if measured_since is None or day < measured_since:
                    measured_since = day
                if snap_newest is None or day > snap_newest:
                    snap_newest = day
        except Exception as e:
            logger.warning(f"Link impact: snapshot fetch failed (migration applied?): {e}")

        # Approximate: implemented AUTO inbound links by created_at, source-
        # scoped to the live set. Cumulative count <= T reconstructs history.
        auto_links: Dict[str, List[str]] = {}
        live_set = set(live_ids)
        for i in range(0, len(live_ids), 50):
            batch = live_ids[i:i + 50]
            try:
                res = (
                    self.supabase.table("seo_internal_links")
                    .select("source_article_id, target_article_id, created_at")
                    .in_("target_article_id", batch)
                    .eq("status", "implemented")
                    .eq("link_type", "auto")
                    .execute()
                )
                for r in (res.data or []):
                    if r.get("source_article_id") in live_set and r.get("created_at"):
                        # Parse to aware datetimes here — comparing timestamptz
                        # STRINGS against a naive cutoff misbuckets boundary
                        # links across formats/offsets.
                        try:
                            raw = str(r["created_at"]).replace("Z", "+00:00").replace(" ", "T")
                            dt = datetime.fromisoformat(raw)
                            if dt.tzinfo is None:
                                dt = dt.replace(tzinfo=timezone.utc)
                            auto_links.setdefault(r["target_article_id"], []).append(dt)
                        except Exception:
                            continue
            except Exception as e:
                logger.warning(f"Link impact: auto-link fetch failed: {e}")

        def _approx_at(aid: str, day) -> int:
            cutoff = datetime(
                day.year, day.month, day.day, 23, 59, 59, tzinfo=timezone.utc
            )
            return sum(1 for ts in auto_links.get(aid, []) if ts <= cutoff)

        # --- Combine ----------------------------------------------------------
        articles = []
        for aid in live_ids:
            series = by_article.get(aid) or []
            pos_first = _edge_avg(series, last=False)
            pos_now = _edge_avg(series, last=True)
            # Require a real spread: at least ~2 distinct weeks of data.
            distinct_days = {d for d, _ in series}
            if pos_first is None or pos_now is None or len(distinct_days) < 8:
                continue

            sf, sl = snap_first.get(aid), snap_last.get(aid)
            # A snapshot only counts as a window-EDGE measurement if it was
            # captured near that edge: the latest within 14 days of now, the
            # earliest within 7 days of the window start. A mid-window stale
            # snapshot serving as the "end" would silently miss recent gains.
            end_fresh = (
                sl is not None
                and sl[0] >= (now.date() - timedelta(days=14)).isoformat()
            )
            start_covered = (
                sf is not None
                and sf[0] <= (window_start + timedelta(days=7)).isoformat()
            )
            if end_fresh:
                end_count = sl[1]
                if start_covered:
                    start_count = sf[1]
                    provenance = "measured"
                else:
                    start_count = _approx_at(aid, window_start)
                    provenance = "mixed"
            else:
                end_count = _approx_at(aid, now.date())
                start_count = _approx_at(aid, window_start)
                provenance = "approximate"

            articles.append({
                "article_id": aid,
                "keyword": kw_by_id.get(aid, ""),
                "link_gain": end_count - start_count,
                "links_now": end_count,
                "position_first": pos_first,
                "position_now": pos_now,
                "position_delta": round(pos_now - pos_first, 2),
                "provenance": provenance,
            })

        def _median(vals: List[float]) -> Optional[float]:
            if not vals:
                return None
            vals = sorted(vals)
            mid = len(vals) // 2
            return round(
                vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2, 2
            )

        gained = [a for a in articles if a["link_gain"] > 0]
        no_gain = [a for a in articles if a["link_gain"] == 0]
        lost = [a for a in articles if a["link_gain"] < 0]
        buckets = {
            "gained_links": {
                "count": len(gained),
                "median_position_delta": _median([a["position_delta"] for a in gained]),
            },
            "no_gain": {
                "count": len(no_gain),
                "median_position_delta": _median([a["position_delta"] for a in no_gain]),
            },
        }
        if lost:
            buckets["lost_links"] = {
                "count": len(lost),
                "median_position_delta": _median([a["position_delta"] for a in lost]),
            }

        return {
            "window_days": window_days,
            "data_as_of": {"gsc": gsc_newest, "snapshots": snap_newest},
            "stale": stale,
            "measured_since": measured_since,
            "articles": articles,
            "buckets": buckets,
            "insufficient_data": len(articles) < 3,
        }
