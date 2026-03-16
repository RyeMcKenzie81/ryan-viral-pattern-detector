"""
Interlinking Service - Three tools for building internal link networks.

Tool 1: Link Suggestion — Jaccard similarity on keyword word-sets,
        generates anchor text variations, suggests placement & priority.
Tool 2: Auto-Link — Pattern matching in <p> tags, inserts <a> tags,
        word-boundary regex, one link per paragraph, first occurrence only.
Tool 3: Bidirectional — Adds "Related Articles" HTML section before
        FAQ / author bio / end of article.

Ported from:
- seo-pipeline/linking/suggest.js
- seo-pipeline/publisher/auto-link-existing-text.js
- seo-pipeline/publisher/add-bidirectional-links.js

All results saved to seo_internal_links table.
"""

import logging
import random
import re
import time
from typing import Dict, Any, Optional, List

from viraltracker.services.seo_pipeline.models import (
    LinkType,
    LinkStatus,
    LinkPriority,
    LinkPlacement,
)

logger = logging.getLogger(__name__)

# Words to strip when generating anchor text variations
GENERIC_WORDS = {"guide", "tips", "advice", "best", "top", "complete", "ultimate"}


class InterlinkingService:
    """Service for internal link suggestions, auto-linking, and bidirectional links."""

    def __init__(self, supabase_client=None, publisher_service=None):
        self._supabase = supabase_client
        self._publisher_service = publisher_service

    @property
    def supabase(self):
        """Lazy-load Supabase client."""
        if self._supabase is None:
            from viraltracker.core.database import get_supabase_client
            self._supabase = get_supabase_client()
        return self._supabase

    # =========================================================================
    # TOOL 1: LINK SUGGESTION (from linking/suggest.js)
    # =========================================================================

    def suggest_links(
        self,
        article_id: str,
        min_similarity: float = 0.2,
        max_suggestions: int = 5,
        save: bool = True,
    ) -> Dict[str, Any]:
        """
        Suggest internal links for an article using Jaccard similarity.

        Finds related articles by keyword word-set overlap, generates anchor
        text variations, and suggests placement (middle or end).

        Args:
            article_id: Source article UUID
            min_similarity: Minimum Jaccard similarity threshold (default: 0.2)
            max_suggestions: Maximum number of suggestions (default: 5)
            save: Whether to save suggestions to seo_internal_links table

        Returns:
            Dict with suggestions list, count, and article info
        """
        article = self._get_article(article_id)
        if not article:
            raise ValueError(f"Article not found: {article_id}")

        # Get all other articles in the same project
        project_id = article.get("project_id")
        all_articles = self._get_project_articles(project_id, exclude_id=article_id)

        source_keyword = article.get("keyword", "")
        suggestions = []

        for target in all_articles:
            target_keyword = target.get("keyword", "")
            similarity = self._jaccard_similarity(source_keyword, target_keyword)

            if similarity >= min_similarity:
                anchor_texts = self._generate_anchor_texts(target_keyword)
                placement = self._suggest_placement(source_keyword, target_keyword)
                priority = LinkPriority.HIGH if similarity > 0.4 else LinkPriority.MEDIUM

                suggestions.append({
                    "target_article_id": target["id"],
                    "target_keyword": target_keyword,
                    "target_url": target.get("published_url", ""),
                    "target_title": target.get("title") or target_keyword,
                    "similarity": round(similarity, 3),
                    "anchor_texts": anchor_texts,
                    "placement": placement.value,
                    "priority": priority.value,
                })

        # Sort by similarity descending, limit
        suggestions.sort(key=lambda s: s["similarity"], reverse=True)
        suggestions = suggestions[:max_suggestions]

        # Save to DB
        if save and suggestions:
            self._save_suggestions(article_id, suggestions)

        return {
            "article_id": article_id,
            "keyword": source_keyword,
            "suggestion_count": len(suggestions),
            "suggestions": suggestions,
        }

    # =========================================================================
    # TOOL 2: AUTO-LINK (from publisher/auto-link-existing-text.js)
    # =========================================================================

    def auto_link_article(
        self,
        article_id: str,
        push_to_cms: bool = False,
        brand_id: Optional[str] = None,
        organization_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Auto-insert internal links into article HTML by finding matching text.

        Generates match patterns from other article titles + keywords, then
        finds those patterns in <p> tags and inserts <a> tags.

        Rules (matching original auto-link-existing-text.js):
        - Only link in <p> tags
        - Skip paragraphs with existing links
        - Skip "Related Articles" section
        - Word-boundary regex, case-insensitive
        - One link per paragraph, first occurrence only
        - Minimum pattern length: 10 chars

        Args:
            article_id: Article UUID to update
            push_to_cms: Whether to push updated HTML to CMS
            brand_id: Brand UUID (required if push_to_cms=True)
            organization_id: Org UUID (required if push_to_cms=True)

        Returns:
            Dict with links_added count, linked_articles, updated HTML info
        """
        article = self._get_article(article_id)
        if not article:
            raise ValueError(f"Article not found: {article_id}")

        html = article.get("content_html", "")
        if not html and article.get("phase_c_output"):
            from viraltracker.services.seo_pipeline.services.cms_publisher_service import CMSPublisherService
            cms_svc = CMSPublisherService(supabase_client=self.supabase)
            html = cms_svc.sync_content_html(article_id)
        if not html:
            return {
                "article_id": article_id,
                "links_added": 0,
                "message": "No content_html to process. Generate and publish first.",
            }

        project_id = article.get("project_id")
        other_articles = self._get_project_articles(project_id, exclude_id=article_id)

        total_links = 0
        linked_articles = []

        for target in other_articles:
            target_url = target.get("published_url", "")
            if not target_url:
                # Build relative URL from handle if no published_url
                keyword = target.get("keyword", "")
                if keyword:
                    handle = re.sub(r'[^a-z0-9]+', '-', keyword.lower()).strip('-')
                    target_url = f"/blogs/articles/{handle}"
                else:
                    continue

            # Skip if link to this target already exists
            if target_url in html:
                continue

            patterns = self._generate_match_patterns(target)
            result = self._insert_links_in_paragraphs(html, patterns, target_url)

            if result["count"] > 0:
                html = result["html"]
                total_links += result["count"]
                linked_articles.append({
                    "article_id": target["id"],
                    "keyword": target.get("keyword", ""),
                    "links_added": result["count"],
                })

        if total_links > 0:
            # Update article HTML in DB
            self._update_article_html(article_id, html)

            # Save link records
            for linked in linked_articles:
                self._save_link_record(
                    source_id=article_id,
                    target_id=linked["article_id"],
                    link_type=LinkType.AUTO,
                    status=LinkStatus.IMPLEMENTED,
                )

            # Push to CMS if requested
            if push_to_cms and brand_id and organization_id:
                self._push_html_to_cms(article_id, brand_id, organization_id, html)

        return {
            "article_id": article_id,
            "links_added": total_links,
            "linked_articles": linked_articles,
        }

    # =========================================================================
    # TOOL 3: BIDIRECTIONAL LINKING (from publisher/add-bidirectional-links.js)
    # =========================================================================

    def add_related_section(
        self,
        article_id: str,
        related_article_ids: List[str],
        push_to_cms: bool = False,
        brand_id: Optional[str] = None,
        organization_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Add a "Related Articles" HTML section to an article.

        Inserts before: FAQ section -> author bio -> end of article (priority order).
        Checks for existing links to avoid duplicates.

        Args:
            article_id: Source article UUID
            related_article_ids: List of target article UUIDs
            push_to_cms: Whether to push to CMS
            brand_id: Brand UUID (for CMS push)
            organization_id: Org UUID (for CMS push)

        Returns:
            Dict with status, articles_linked count, placement position
        """
        article = self._get_article(article_id)
        if not article:
            raise ValueError(f"Article not found: {article_id}")

        html = article.get("content_html", "")
        if not html and article.get("phase_c_output"):
            from viraltracker.services.seo_pipeline.services.cms_publisher_service import CMSPublisherService
            cms_svc = CMSPublisherService(supabase_client=self.supabase)
            html = cms_svc.sync_content_html(article_id)
        if not html:
            return {
                "article_id": article_id,
                "articles_linked": 0,
                "message": "No content_html to update.",
            }

        # Check if Related Articles section already exists
        if "<h2>Related Articles</h2>" in html:
            return {
                "article_id": article_id,
                "articles_linked": 0,
                "message": "Related Articles section already exists. Remove it first to regenerate.",
            }

        # Load related articles
        related_articles = []
        for rid in related_article_ids:
            related = self._get_article(rid)
            if related:
                title = related.get("title") or related.get("keyword", "Untitled")
                url = related.get("published_url", "")
                if not url:
                    keyword = related.get("keyword", "")
                    handle = re.sub(r'[^a-z0-9]+', '-', keyword.lower()).strip('-')
                    url = f"/blogs/articles/{handle}"
                related_articles.append({
                    "id": rid,
                    "title": title,
                    "url": url,
                })

        if not related_articles:
            return {
                "article_id": article_id,
                "articles_linked": 0,
                "message": "No valid related articles found.",
            }

        # Build Related Articles HTML
        links_html = "\n".join(
            f'<li><a href="{a["url"]}">{a["title"]}</a></li>'
            for a in related_articles
        )
        section_html = (
            '<h2>Related Articles</h2>\n'
            '<p>Looking for more? Check out these related articles:</p>\n'
            f'<ul>\n{links_html}\n</ul>'
        )

        # Insert: before FAQ -> before author bio -> at end
        placement = "end"
        if re.search(r'<h[23]>\s*FAQ\s*</h[23]>', html, re.IGNORECASE):
            html = re.sub(
                r'(<h[23]>\s*FAQ\s*</h[23]>)',
                section_html + '\n\\1',
                html,
                count=1,
                flags=re.IGNORECASE,
            )
            placement = "before_faq"
        elif '<div style="background: #f8f9fa' in html:
            html = html.replace(
                '<div style="background: #f8f9fa',
                section_html + '\n<div style="background: #f8f9fa',
                1,
            )
            placement = "before_author_bio"
        else:
            html += '\n' + section_html
            placement = "end"

        # Update DB
        self._update_article_html(article_id, html)

        # Save link records
        for related in related_articles:
            self._save_link_record(
                source_id=article_id,
                target_id=related["id"],
                link_type=LinkType.BIDIRECTIONAL,
                status=LinkStatus.IMPLEMENTED,
            )

        # Push to CMS
        if push_to_cms and brand_id and organization_id:
            self._push_html_to_cms(article_id, brand_id, organization_id, html)

        return {
            "article_id": article_id,
            "articles_linked": len(related_articles),
            "placement": placement,
            "related_articles": [a["title"] for a in related_articles],
        }

    # =========================================================================
    # CLUSTER-AWARE INTERLINKING
    # =========================================================================

    def interlink_cluster(
        self,
        cluster_id: str,
        trigger_article_id: Optional[str] = None,
        push_to_cms: bool = False,
        brand_id: Optional[str] = None,
        organization_id: Optional[str] = None,
        cms_delay: float = 1.0,
    ) -> Dict[str, Any]:
        """
        Run cluster-aware interlinking for all published articles in a cluster.

        Ensures pillar-spoke linking, contextual cross-links, and Related Articles
        sections for every article in the cluster.

        Args:
            cluster_id: Cluster UUID
            trigger_article_id: The article that triggered this (e.g., just published)
            push_to_cms: Whether to push updated HTML to CMS
            brand_id: Brand UUID (required if push_to_cms)
            organization_id: Org UUID (required if push_to_cms)
            cms_delay: Seconds between CMS pushes (Shopify rate limit: 2 req/s)

        Returns:
            Dict with articles_processed, links_added, related_sections_added, errors
        """
        from viraltracker.services.seo_pipeline.services.cluster_management_service import ClusterManagementService
        cluster_svc = ClusterManagementService(self._supabase)

        # Get cluster details
        cluster = cluster_svc.get_cluster(cluster_id)
        if not cluster:
            raise ValueError(f"Cluster not found: {cluster_id}")

        # Get all article IDs in cluster
        all_article_ids = cluster_svc.get_cluster_spoke_article_ids(cluster_id)
        if not all_article_ids:
            return {"articles_processed": 0, "links_added": 0, "related_sections_added": 0, "errors": []}

        # Filter to published articles with URLs
        published_articles = []
        for aid in all_article_ids:
            article = self._get_article(aid)
            if article and article.get("published_url"):
                published_articles.append(article)

        if len(published_articles) < 2:
            return {"articles_processed": 0, "links_added": 0, "related_sections_added": 0,
                    "errors": [{"message": "Need at least 2 published articles to interlink"}]}

        # Identify pillar article
        spokes = cluster.get("spokes", [])
        pillar_article_id = None
        for spoke in spokes:
            if spoke.get("role") == "pillar" and spoke.get("article_id"):
                pillar_article_id = spoke["article_id"]
                break

        total_links = 0
        related_sections = 0
        errors = []

        for article in published_articles:
            aid = article["id"]
            try:
                # Auto-link against all project articles (contextual links)
                auto_result = self.auto_link_article(aid)
                added = auto_result.get("links_added", 0)

                # Save cluster link records for pillar-spoke relationships
                if pillar_article_id:
                    if aid != pillar_article_id:
                        # Spoke → pillar link record
                        self._save_link_record(
                            source_id=aid, target_id=pillar_article_id,
                            link_type=LinkType.CLUSTER, status=LinkStatus.IMPLEMENTED,
                            anchor_text=self._varied_anchor(
                                next((a.get("keyword", "") for a in published_articles if a["id"] == pillar_article_id), ""),
                            ),
                        )
                    else:
                        # Pillar → spoke link records
                        for other in published_articles:
                            if other["id"] != aid:
                                self._save_link_record(
                                    source_id=aid, target_id=other["id"],
                                    link_type=LinkType.CLUSTER, status=LinkStatus.IMPLEMENTED,
                                    anchor_text=self._varied_anchor(other.get("keyword", "")),
                                )

                total_links += added

                # Remove old Related section, rebuild
                self._remove_related_section(aid)

                # Pick top related articles (pillar first if this is a spoke, then others)
                related_ids = []
                if pillar_article_id and aid != pillar_article_id:
                    related_ids.append(pillar_article_id)
                for other in published_articles:
                    if other["id"] != aid and other["id"] not in related_ids:
                        related_ids.append(other["id"])
                related_ids = related_ids[:5]  # Cap at 5

                if related_ids:
                    self.add_related_section(aid, related_ids)
                    related_sections += 1

                # Push to CMS
                if push_to_cms and brand_id and organization_id:
                    # Re-read latest HTML after modifications
                    updated = self._get_article(aid)
                    if updated and updated.get("cms_article_id"):
                        self._push_html_to_cms(aid, brand_id, organization_id, updated.get("content_html", ""))
                        time.sleep(cms_delay)

            except Exception as e:
                logger.warning(f"Cluster interlink failed for article {aid}: {e}")
                errors.append({"article_id": aid, "error": str(e)[:200]})

        return {
            "articles_processed": len(published_articles),
            "links_added": total_links,
            "related_sections_added": related_sections,
            "errors": errors,
        }

    @staticmethod
    def _varied_anchor(keyword: str) -> str:
        """
        Generate a varied anchor text for a keyword.

        Distribution: ~20% exact, ~35% partial, ~35% semantic, ~10% natural phrase.
        """
        if not keyword:
            return "(auto)"

        roll = random.random()

        if roll < 0.2:
            # Exact keyword
            return keyword
        elif roll < 0.55:
            # Partial match — drop a word
            words = keyword.split()
            if len(words) > 2:
                drop_idx = random.randint(0, len(words) - 1)
                return " ".join(w for i, w in enumerate(words) if i != drop_idx)
            return keyword
        elif roll < 0.9:
            # Semantic variation
            variations = [
                keyword[0].upper() + keyword[1:] if len(keyword) > 1 else keyword,
                f"guide to {keyword}",
                f"everything about {keyword}",
                f"understanding {keyword}",
            ]
            return random.choice(variations)
        else:
            # Natural phrase
            return random.choice(["this guide", "learn more", "this article", "our full guide"])

    # =========================================================================
    # GSC LINK OPPORTUNITIES
    # =========================================================================

    def find_linking_opportunities(
        self,
        brand_id: str,
        organization_id: str,
        min_impressions: int = 10,
        position_range: tuple = (8, 30),
        min_wow_growth: float = 0.1,
        max_inbound_links: int = 3,
    ) -> Dict[str, Any]:
        """
        Find articles that would benefit from more internal links, based on GSC data.

        Identifies articles in striking distance (position 8-30) with growing impressions
        but few inbound internal links.

        Args:
            brand_id: Brand UUID
            organization_id: Organization UUID
            min_impressions: Minimum total impressions to consider
            position_range: (min_pos, max_pos) for striking distance
            min_wow_growth: Minimum week-over-week impression growth
            max_inbound_links: Maximum existing inbound links to qualify
        """
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        recent_start = (now - timedelta(days=7)).isoformat()
        prior_start = (now - timedelta(days=14)).isoformat()
        prior_end = (now - timedelta(days=7)).isoformat()

        # Get articles for this brand with GSC analytics
        articles_result = (
            self.supabase.table("seo_articles")
            .select("id, keyword, title, published_url, project_id")
            .eq("brand_id", brand_id)
            .not_.is_("published_url", "null")
            .execute()
        )
        articles = articles_result.data or []
        if not articles:
            return {"opportunities": [], "total_scanned": 0}

        article_map = {a["id"]: a for a in articles}
        article_ids = list(article_map.keys())

        # Get recent analytics (last 7 days)
        recent_result = (
            self.supabase.table("seo_article_analytics")
            .select("article_id, impressions, average_position")
            .in_("article_id", article_ids)
            .eq("source", "gsc")
            .gte("date", recent_start)
            .execute()
        )

        # Get prior period analytics (7-14 days ago)
        prior_result = (
            self.supabase.table("seo_article_analytics")
            .select("article_id, impressions")
            .in_("article_id", article_ids)
            .eq("source", "gsc")
            .gte("date", prior_start)
            .lt("date", prior_end)
            .execute()
        )

        # Aggregate per article
        recent_stats: Dict[str, Dict] = {}
        for row in (recent_result.data or []):
            aid = row["article_id"]
            if aid not in recent_stats:
                recent_stats[aid] = {"impressions": 0, "positions": [], "count": 0}
            recent_stats[aid]["impressions"] += row.get("impressions", 0)
            pos = row.get("average_position")
            if pos:
                recent_stats[aid]["positions"].append(pos)
            recent_stats[aid]["count"] += 1

        prior_stats: Dict[str, int] = {}
        for row in (prior_result.data or []):
            aid = row["article_id"]
            prior_stats[aid] = prior_stats.get(aid, 0) + row.get("impressions", 0)

        # Count inbound links
        inbound_counts = self._batch_count_inbound_links(article_ids)

        # Find opportunities
        opportunities = []
        for aid, stats in recent_stats.items():
            total_impressions = stats["impressions"]
            if total_impressions < min_impressions:
                continue

            # Absolute floor
            if total_impressions < 50:
                continue

            avg_position = (
                sum(stats["positions"]) / len(stats["positions"])
                if stats["positions"] else 0
            )

            # WoW growth
            prior_impressions = prior_stats.get(aid, 0)
            wow_growth = (
                (total_impressions - prior_impressions) / prior_impressions
                if prior_impressions > 0 else 0
            )

            # Check filters
            in_range = position_range[0] <= avg_position <= position_range[1]
            growing = wow_growth >= min_wow_growth

            if not (in_range or growing):
                continue

            inbound = inbound_counts.get(aid, 0)
            if inbound > max_inbound_links:
                continue

            article = article_map.get(aid, {})

            # Find top 5 source articles that could link to this target
            project_id = article.get("project_id")
            suggested_sources = []
            if project_id:
                project_articles = self._get_project_articles(project_id, exclude_id=aid)
                # Exclude articles already linking to target
                existing_sources = set()
                try:
                    existing = (
                        self.supabase.table("seo_internal_links")
                        .select("source_article_id")
                        .eq("target_article_id", aid)
                        .eq("status", LinkStatus.IMPLEMENTED.value)
                        .execute()
                    )
                    existing_sources = {r["source_article_id"] for r in (existing.data or [])}
                except Exception:
                    pass

                for pa in project_articles:
                    if pa["id"] in existing_sources:
                        continue
                    sim = self._jaccard_similarity(article.get("keyword", ""), pa.get("keyword", ""))
                    if sim > 0.1:
                        suggested_sources.append({
                            "article_id": pa["id"],
                            "keyword": pa.get("keyword", ""),
                            "similarity": round(sim, 3),
                        })
                suggested_sources.sort(key=lambda x: x["similarity"], reverse=True)
                suggested_sources = suggested_sources[:5]

            # Composite score: (1/position) * impressions * (1 + wow_growth)
            score = (
                (1 / avg_position if avg_position > 0 else 0)
                * total_impressions
                * (1 + wow_growth)
            )

            opportunities.append({
                "article_id": aid,
                "keyword": article.get("keyword", ""),
                "title": article.get("title", ""),
                "published_url": article.get("published_url", ""),
                "avg_position": round(avg_position, 1),
                "impressions": total_impressions,
                "wow_growth": round(wow_growth, 3),
                "inbound_link_count": inbound,
                "score": round(score, 2),
                "suggested_sources": suggested_sources,
            })

        # Sort by composite score descending, take top 20
        opportunities.sort(key=lambda x: x["score"], reverse=True)
        opportunities = opportunities[:20]

        # Find last sync date
        last_sync = None
        try:
            sync_result = (
                self.supabase.table("seo_article_analytics")
                .select("date")
                .in_("article_id", article_ids[:1])
                .eq("source", "gsc")
                .order("date", desc=True)
                .limit(1)
                .execute()
            )
            if sync_result.data:
                last_sync = sync_result.data[0].get("date")
        except Exception:
            pass

        return {
            "opportunities": opportunities,
            "total_scanned": len(articles),
            "last_synced_at": last_sync,
        }

    # =========================================================================
    # SIMILARITY & ANCHOR TEXT (from suggest.js)
    # =========================================================================

    @staticmethod
    def _jaccard_similarity(keyword1: str, keyword2: str) -> float:
        """
        Calculate Jaccard similarity between two keyword strings.

        Jaccard = |intersection| / |union| of word sets.
        """
        if not keyword1 or not keyword2:
            return 0.0

        words1 = set(keyword1.lower().split())
        words2 = set(keyword2.lower().split())

        intersection = words1 & words2
        union = words1 | words2

        if not union:
            return 0.0

        return len(intersection) / len(union)

    @staticmethod
    def _generate_anchor_texts(keyword: str) -> List[str]:
        """
        Generate anchor text variations for a keyword.

        Produces: exact match, without "how to", without generic words,
        capitalized version, branded variations.
        """
        variations = set()
        kw = keyword.strip()

        if not kw:
            return []

        # Exact match
        variations.add(kw)

        # Without "how to"
        no_how_to = re.sub(r'^how to\s+', '', kw, flags=re.IGNORECASE)
        if no_how_to != kw:
            variations.add(no_how_to)

        # Without generic words
        words = kw.split()
        filtered = [w for w in words if w.lower() not in GENERIC_WORDS]
        if filtered and len(filtered) < len(words):
            variations.add(" ".join(filtered))

        # Capitalized version
        variations.add(kw[0].upper() + kw[1:] if len(kw) > 1 else kw.upper())

        # Branded variations
        variations.add(f"learn more about {kw}")
        variations.add(f"guide to {kw}")

        # Filter out short/empty
        return [v.strip() for v in variations if v.strip() and len(v.strip()) > 3]

    @staticmethod
    def _suggest_placement(source_keyword: str, target_keyword: str) -> LinkPlacement:
        """
        Suggest where to place a link in the article.

        If there are common substantive words (>3 chars), suggest "middle"
        (contextual). Otherwise suggest "end" (related resources section).
        """
        source_words = set(source_keyword.lower().split())
        target_words = set(target_keyword.lower().split())
        common = [w for w in source_words & target_words if len(w) > 3]

        if common:
            return LinkPlacement.MIDDLE
        return LinkPlacement.END

    # =========================================================================
    # AUTO-LINK HELPERS (from auto-link-existing-text.js)
    # =========================================================================

    @staticmethod
    def _generate_match_patterns(article: Dict[str, Any]) -> List[str]:
        """
        Generate text patterns to match for an article.

        Creates variations from title and keyword: full text, without
        "how to", without parentheticals, 3-4 word n-grams.
        Minimum 10 characters per pattern.
        """
        patterns = set()
        title = (article.get("title") or "").lower()
        keyword = (article.get("keyword") or "").lower()

        if title:
            patterns.add(title)
            # Without parentheticals
            no_parens = re.sub(r'\([^)]*\)', '', title).strip()
            if no_parens != title:
                patterns.add(no_parens)

        if keyword:
            patterns.add(keyword)
            # Without "how to"
            if keyword.startswith("how to "):
                patterns.add(keyword[7:])

            # 3-4 word n-grams
            words = keyword.split()
            if len(words) >= 3:
                for i in range(len(words) - 2):
                    patterns.add(" ".join(words[i:i + 3]))
                    if i <= len(words) - 4:
                        patterns.add(" ".join(words[i:i + 4]))

        # Dedupe and filter by min length
        return [p for p in patterns if len(p) >= 10]

    @staticmethod
    def _insert_links_in_paragraphs(
        html: str,
        patterns: List[str],
        target_url: str,
    ) -> Dict[str, Any]:
        """
        Find matching patterns in <p> tags and insert <a> links.

        Rules:
        - Only match in <p>...</p> tags
        - Skip paragraphs with existing links (<a )
        - Skip content after <h2>Related Articles</h2>
        - Word-boundary regex, case-insensitive
        - One link per paragraph, first occurrence only
        """
        count = 0

        # Find the "Related Articles" boundary (skip everything after it)
        related_pos = html.find("<h2>Related Articles</h2>")
        if related_pos == -1:
            related_pos = len(html)

        def replace_paragraph(match):
            nonlocal count
            full_match = match.group(0)
            inner = match.group(1)

            # Skip if this paragraph is after Related Articles section
            if match.start() > related_pos:
                return full_match

            # Skip if paragraph already has a link
            if "<a " in inner:
                return full_match

            # Try each pattern
            for pattern in patterns:
                escaped = re.escape(pattern)
                regex = re.compile(rf'\b{escaped}\b', re.IGNORECASE)
                if regex.search(inner):
                    # Replace first occurrence only
                    inner = regex.sub(
                        lambda m: f'<a href="{target_url}">{m.group(0)}</a>',
                        inner,
                        count=1,
                    )
                    count += 1
                    return f"<p>{inner}</p>"

            return full_match

        result_html = re.sub(r'<p>(.*?)</p>', replace_paragraph, html, flags=re.DOTALL)
        return {"html": result_html, "count": count}

    # =========================================================================
    # DB HELPERS
    # =========================================================================

    def _get_article(self, article_id: str) -> Optional[Dict[str, Any]]:
        """Get article from DB."""
        result = (
            self.supabase.table("seo_articles")
            .select("*")
            .eq("id", article_id)
            .execute()
        )
        return result.data[0] if result.data else None

    def _get_project_articles(
        self,
        project_id: str,
        exclude_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get all linkable articles in a project (published with a URL)."""
        query = (
            self.supabase.table("seo_articles")
            .select("id, keyword, title, published_url, status, content_html, project_id")
            .eq("project_id", project_id)
            .neq("status", "discovered")
            .not_.is_("published_url", "null")
        )
        if exclude_id:
            query = query.neq("id", exclude_id)
        result = query.execute()
        return result.data or []

    def _save_suggestions(
        self,
        source_id: str,
        suggestions: List[Dict[str, Any]],
    ) -> None:
        """Save link suggestions to seo_internal_links."""
        for s in suggestions:
            self._save_link_record(
                source_id=source_id,
                target_id=s["target_article_id"],
                link_type=LinkType.SUGGESTED,
                status=LinkStatus.PENDING,
                anchor_text=s["anchor_texts"][0] if s["anchor_texts"] else "",
                similarity=s["similarity"],
                placement=s["placement"],
                priority=s["priority"],
            )

    def _save_link_record(
        self,
        source_id: str,
        target_id: str,
        link_type: LinkType,
        status: LinkStatus,
        anchor_text: str = "",
        similarity: float = 0.0,
        placement: str = "",
        priority: str = "",
    ) -> None:
        """Save a single link record to seo_internal_links."""
        try:
            data = {
                "source_article_id": source_id,
                "target_article_id": target_id,
                "link_type": link_type.value,
                "status": status.value,
                "anchor_text": anchor_text or "(auto)",
            }
            if similarity:
                data["similarity_score"] = similarity
            if placement:
                data["placement"] = placement
            if priority:
                data["priority"] = priority

            self.supabase.table("seo_internal_links").insert(data).execute()
        except Exception as e:
            logger.warning(f"Failed to save link record {source_id}->{target_id}: {e}")

    def _remove_related_section(self, article_id: str) -> str:
        """
        Remove existing 'Related Articles' HTML section from an article.

        Also deletes BIDIRECTIONAL link records from seo_internal_links for this article.

        Returns:
            Updated HTML with the section removed.
        """
        article = self._get_article(article_id)
        if not article:
            return ""

        html = article.get("content_html", "")
        if not html:
            return ""

        # Remove Related Articles section (h2 or h3, with optional attributes)
        cleaned = re.sub(
            r'<h[23][^>]*>\s*Related Articles\s*</h[23]>[\s\S]*?</ul>\s*',
            '',
            html,
        )
        # Also remove the intro paragraph if present
        cleaned = re.sub(
            r'<p>Looking for more\? Check out these related articles:</p>\s*',
            '',
            cleaned,
        )

        if cleaned != html:
            self._update_article_html(article_id, cleaned)
            # Delete bidirectional link records
            try:
                self.supabase.table("seo_internal_links").delete().eq(
                    "source_article_id", article_id
                ).eq("link_type", LinkType.BIDIRECTIONAL.value).execute()
            except Exception as e:
                logger.warning(f"Failed to delete bidirectional link records for {article_id}: {e}")

        return cleaned

    def _batch_count_inbound_links(self, article_ids: List[str]) -> Dict[str, int]:
        """
        Count implemented inbound links for a batch of articles.

        Args:
            article_ids: List of target article UUIDs

        Returns:
            Dict mapping article_id -> inbound link count
        """
        if not article_ids:
            return {}

        try:
            result = (
                self.supabase.table("seo_internal_links")
                .select("target_article_id")
                .in_("target_article_id", article_ids)
                .eq("status", LinkStatus.IMPLEMENTED.value)
                .execute()
            )
            counts: Dict[str, int] = {}
            for row in (result.data or []):
                tid = row["target_article_id"]
                counts[tid] = counts.get(tid, 0) + 1
            return counts
        except Exception as e:
            logger.warning(f"Failed to count inbound links: {e}")
            return {}

    def _update_article_html(self, article_id: str, html: str) -> None:
        """Update content_html in seo_articles."""
        try:
            self.supabase.table("seo_articles").update({
                "content_html": html,
            }).eq("id", article_id).execute()
        except Exception as e:
            logger.error(f"Failed to update article HTML for {article_id}: {e}")
            raise

    def _push_html_to_cms(
        self,
        article_id: str,
        brand_id: str,
        organization_id: str,
        html: str,
    ) -> None:
        """Push updated HTML to CMS via publisher service."""
        try:
            if self._publisher_service is None:
                from viraltracker.services.seo_pipeline.services.cms_publisher_service import CMSPublisherService
                self._publisher_service = CMSPublisherService(self._supabase)

            article = self._get_article(article_id)
            cms_id = article.get("cms_article_id") if article else None
            if not cms_id:
                logger.warning(f"Article {article_id} has no cms_article_id, skipping CMS push")
                return

            publisher = self._publisher_service.get_publisher(brand_id, organization_id)
            if publisher:
                publisher.update(cms_id, {"body_html": html}, body_only=True)
                logger.info(f"Pushed updated HTML to CMS for article {article_id}")
        except Exception as e:
            logger.warning(f"Failed to push HTML to CMS for {article_id}: {e}")
