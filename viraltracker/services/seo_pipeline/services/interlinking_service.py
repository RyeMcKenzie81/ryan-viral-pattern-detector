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
import re
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
        """Get all articles in a project, optionally excluding one."""
        query = (
            self.supabase.table("seo_articles")
            .select("id, keyword, title, published_url, status, content_html, project_id")
            .eq("project_id", project_id)
            .neq("status", "discovered")
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
            }
            if anchor_text:
                data["anchor_text"] = anchor_text
            if similarity:
                data["similarity_score"] = similarity
            if placement:
                data["placement"] = placement
            if priority:
                data["priority"] = priority

            self.supabase.table("seo_internal_links").insert(data).execute()
        except Exception as e:
            logger.warning(f"Failed to save link record {source_id}->{target_id}: {e}")

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
                publisher.update(cms_id, {"body_html": html, "title": article.get("title", "")})
                logger.info(f"Pushed updated HTML to CMS for article {article_id}")
        except Exception as e:
            logger.warning(f"Failed to push HTML to CMS for {article_id}: {e}")
