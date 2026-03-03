"""
Competitor Analysis Service - SERP page analysis and winning formula calculation.

Analyzes competitor pages for a target keyword by:
1. Fetching page content via WebScrapingService (FireCrawl)
2. Extracting SEO metrics (headings, word count, readability, links, schema, etc.)
3. Calculating a "winning formula" from aggregated competitor metrics

Ported from seo-pipeline/scraper/scraper.js, analyze.js, competitive-analyzer.js.

Usage modes:
- Manual URL input (primary): User searches Google, pastes top 10-20 URLs
- Automated: Optional Apify SERP actor (future)
"""

import json
import logging
import re
import statistics
from typing import List, Dict, Any, Optional

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class CompetitorAnalysisService:
    """Service for analyzing competitor pages and computing winning formulas."""

    def __init__(self, supabase_client=None, web_scraping_service=None):
        """
        Initialize with optional dependencies.

        Args:
            supabase_client: Supabase client for saving results
            web_scraping_service: WebScrapingService instance for fetching pages
        """
        self._supabase = supabase_client
        self._web_scraping = web_scraping_service

    @property
    def supabase(self):
        """Lazy-load Supabase client."""
        if self._supabase is None:
            from viraltracker.core.database import get_supabase_client
            self._supabase = get_supabase_client()
        return self._supabase

    @property
    def web_scraping(self):
        """Lazy-load WebScrapingService."""
        if self._web_scraping is None:
            from viraltracker.services.web_scraping_service import WebScrapingService
            self._web_scraping = WebScrapingService()
        return self._web_scraping

    def analyze_urls(
        self,
        keyword_id: str,
        urls: List[str],
    ) -> Dict[str, Any]:
        """
        Analyze competitor pages for a keyword.

        Fetches each URL via FireCrawl, extracts SEO metrics, computes
        a winning formula from the aggregate, and saves results to DB.

        Args:
            keyword_id: SEO keyword UUID
            urls: List of competitor URLs to analyze

        Returns:
            Dict with:
                - results: List of per-URL metric dicts
                - winning_formula: Aggregated target metrics
                - analyzed_count: Number of successfully analyzed pages
                - failed_count: Number of pages that failed
        """
        results = []
        failed = []

        for i, url in enumerate(urls):
            logger.info(f"Analyzing [{i+1}/{len(urls)}]: {url}")
            try:
                metrics = self._analyze_page(url, position=i + 1)
                if metrics:
                    results.append(metrics)
                    self._save_analysis(keyword_id, metrics)
                else:
                    failed.append(url)
            except Exception as e:
                logger.warning(f"Failed to analyze {url}: {e}")
                failed.append(url)

        winning_formula = self._calculate_winning_formula(results) if results else {}

        logger.info(
            f"Analysis complete: {len(results)} succeeded, {len(failed)} failed "
            f"out of {len(urls)} URLs"
        )

        return {
            "results": results,
            "winning_formula": winning_formula,
            "analyzed_count": len(results),
            "failed_count": len(failed),
            "failed_urls": failed,
        }

    def _analyze_page(self, url: str, position: int = 0) -> Optional[Dict[str, Any]]:
        """
        Fetch and analyze a single competitor page.

        Uses WebScrapingService (FireCrawl) for fetching, then parses
        the HTML to extract SEO metrics.

        Args:
            url: Page URL to analyze
            position: SERP position (for tracking)

        Returns:
            Dict of extracted metrics, or None if fetch failed
        """
        result = self.web_scraping.scrape_url(
            url, formats=["html", "markdown"], only_main_content=False
        )

        if not result.success:
            logger.warning(f"Scrape failed for {url}: {result.error}")
            return None

        html = result.html or ""
        markdown = result.markdown or ""

        if not html and not markdown:
            logger.warning(f"No content returned for {url}")
            return None

        metrics = self._parse_html_metrics(html, url)
        metrics["url"] = url
        metrics["position"] = position

        # Use markdown for word count if HTML parsing gave 0
        if metrics.get("word_count", 0) == 0 and markdown:
            words = re.findall(r'\b\w+\b', markdown)
            metrics["word_count"] = len(words)

        # Calculate readability from the body text
        body_text = metrics.pop("_body_text", "")
        if body_text:
            metrics["flesch_reading_ease"] = self._calculate_flesch(body_text)

        return metrics

    def _parse_html_metrics(self, html: str, url: str) -> Dict[str, Any]:
        """
        Extract structured SEO metrics from HTML.

        Args:
            html: Raw HTML string
            url: Page URL (for link classification)

        Returns:
            Dict of extracted metrics
        """
        soup = BeautifulSoup(html, "html.parser")

        # Title and meta
        title_tag = soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else ""

        meta_desc_tag = soup.find("meta", attrs={"name": "description"})
        meta_description = meta_desc_tag.get("content", "") if meta_desc_tag else ""

        # Headings
        h1s = [h.get_text(strip=True) for h in soup.find_all("h1")]
        h2s = [h.get_text(strip=True) for h in soup.find_all("h2")]
        h3s = [h.get_text(strip=True) for h in soup.find_all("h3")]
        h4s = [h.get_text(strip=True) for h in soup.find_all("h4")]

        # Schema markup (extract BEFORE decomposing scripts)
        schema_scripts = soup.find_all("script", attrs={"type": "application/ld+json"})
        schema_types = []
        for script in schema_scripts:
            try:
                data = json.loads(script.string or "")
                if isinstance(data, dict):
                    if "@type" in data:
                        schema_types.append(data["@type"])
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and "@type" in item:
                            schema_types.append(item["@type"])
            except (json.JSONDecodeError, TypeError):
                pass

        # Body text and word count
        # Remove script/style tags first
        for tag in soup.find_all(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        body_text = soup.get_text(separator=" ", strip=True)
        words = re.findall(r'\b\w+\b', body_text)
        word_count = len(words)

        # Paragraphs
        paragraphs = soup.find_all("p")
        para_lengths = []
        for p in paragraphs:
            text = p.get_text(strip=True)
            if len(text) > 20:
                para_lengths.append(len(text.split()))

        # Links
        all_links = soup.find_all("a", href=True)
        internal_count = 0
        external_count = 0
        external_links = []

        from urllib.parse import urlparse
        page_domain = urlparse(url).netloc.replace("www.", "")

        for link in all_links:
            href = link.get("href", "")
            if not href or href.startswith("#") or href.startswith("javascript:"):
                continue
            parsed = urlparse(href)
            link_domain = parsed.netloc.replace("www.", "")

            if not link_domain or link_domain == page_domain:
                internal_count += 1
            else:
                external_count += 1
                nofollow = "nofollow" in link.get("rel", [])
                link_type = self._classify_external_link(link_domain)
                external_links.append({
                    "url": href,
                    "anchor": link.get_text(strip=True),
                    "nofollow": nofollow,
                    "type": link_type,
                })

        # Images
        images = soup.find_all("img")
        images_with_alt = sum(1 for img in images if img.get("alt", "").strip())

        # Feature detection
        has_toc = bool(
            soup.find(class_=re.compile(r"table.of.contents", re.I))
            or soup.find("nav", attrs={"aria-label": re.compile(r"table", re.I)})
        )

        has_faq = bool(
            soup.find(attrs={"itemtype": re.compile(r"FAQPage", re.I)})
            or soup.find(class_=re.compile(r"\bfaq\b", re.I))
            or any(
                re.search(r"frequently asked|faq", h.get_text(), re.I)
                for h in soup.find_all(["h2", "h3"])
            )
        )

        has_author = bool(
            soup.find(attrs={"rel": "author"})
            or soup.find(class_=re.compile(r"\bauthor\b", re.I))
            or soup.find(attrs={"itemprop": "author"})
        )

        has_breadcrumbs = bool(
            soup.find(attrs={"itemtype": re.compile(r"BreadcrumbList", re.I)})
            or soup.find(class_=re.compile(r"\bbreadcrumb\b", re.I))
        )

        # Tables
        tables = soup.find_all("table")

        # Videos
        video_embeds = len(soup.find_all("iframe", src=re.compile(r"youtube|vimeo", re.I)))
        video_embeds += len(soup.find_all("video"))

        # CTAs
        cta_count = len(soup.find_all("button"))
        cta_count += len(soup.find_all("a", string=re.compile(
            r"sign.?up|subscribe|download|buy|get.started|free.trial", re.I
        )))

        return {
            "title": title,
            "meta_description": meta_description,
            "h1_count": len(h1s),
            "h2_count": len(h2s),
            "h3_count": len(h3s),
            "h4_count": len(h4s),
            "word_count": word_count,
            "paragraph_count": len(para_lengths),
            "avg_paragraph_length": (
                round(statistics.mean(para_lengths), 1) if para_lengths else 0.0
            ),
            "internal_link_count": internal_count,
            "external_link_count": external_count,
            "image_count": len(images),
            "images_with_alt": images_with_alt,
            "has_toc": has_toc,
            "has_faq": has_faq,
            "has_schema": len(schema_types) > 0,
            "has_author": has_author,
            "has_breadcrumbs": has_breadcrumbs,
            "schema_types": schema_types,
            "has_tables": len(tables) > 0,
            "table_count": len(tables),
            "video_embeds": video_embeds,
            "cta_count": cta_count,
            "_body_text": body_text,  # Used for Flesch, removed before return
            "raw_analysis": {
                "h1s": h1s,
                "h2s": h2s,
                "external_links": external_links[:20],
            },
        }

    @staticmethod
    def _classify_external_link(domain: str) -> str:
        """Classify an external link by its domain."""
        domain = domain.lower()
        if "wikipedia" in domain:
            return "wikipedia"
        if domain.endswith(".edu"):
            return "educational"
        if domain.endswith(".gov"):
            return "government"
        if any(f in domain for f in ["reddit.com", "quora.com", "forum"]):
            return "forum"
        if any(v in domain for v in ["youtube.com", "vimeo.com"]):
            return "video"
        return "general"

    @staticmethod
    def _calculate_flesch(text: str) -> float:
        """
        Calculate Flesch Reading Ease score.

        Formula: 206.835 - (1.015 * avg words/sentence) - (84.6 * avg syllables/word)

        Args:
            text: Plain text to analyze

        Returns:
            Flesch score clamped to 0-100
        """
        sentences = re.split(r'[.!?]+', text)
        sentences = [s.strip() for s in sentences if s.strip()]
        if not sentences:
            return 0.0

        words = re.findall(r'\b[a-zA-Z]+\b', text)
        if not words:
            return 0.0

        total_syllables = sum(
            CompetitorAnalysisService._count_syllables(w) for w in words
        )

        avg_words_per_sentence = len(words) / len(sentences)
        avg_syllables_per_word = total_syllables / len(words)

        score = 206.835 - (1.015 * avg_words_per_sentence) - (84.6 * avg_syllables_per_word)
        return round(max(0.0, min(100.0, score)), 1)

    @staticmethod
    def _count_syllables(word: str) -> int:
        """
        Count syllables in a word using vowel-group heuristic.

        Matches the original Node.js implementation.
        """
        word = word.lower()
        vowel_groups = re.findall(r'[aeiouy]+', word)
        count = len(vowel_groups)
        # Subtract 1 for trailing silent 'e'
        if word.endswith('e') and count > 1:
            count -= 1
        return max(1, count)

    def _calculate_winning_formula(
        self, results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Calculate winning formula from aggregated competitor metrics.

        Computes median/average for numeric metrics, percentages for
        boolean features, and identifies content opportunities.

        Args:
            results: List of per-URL metric dicts

        Returns:
            Winning formula dict with targets and opportunities
        """
        if not results:
            return {}

        def _stats(values):
            """Compute stats for a list of numbers."""
            clean = [v for v in values if v is not None]
            if not clean:
                return {"avg": 0, "median": 0, "min": 0, "max": 0}
            return {
                "avg": round(statistics.mean(clean)),
                "median": round(statistics.median(clean)),
                "min": min(clean),
                "max": max(clean),
            }

        def _pct(field):
            """Compute percentage of results where boolean field is True."""
            count = sum(1 for r in results if r.get(field))
            return round(count / len(results) * 100, 1)

        n = len(results)
        word_stats = _stats([r.get("word_count", 0) for r in results])
        flesch_values = [r.get("flesch_reading_ease") for r in results if r.get("flesch_reading_ease") is not None]

        formula = {
            "competitor_count": n,
            "avg_word_count": word_stats["avg"],
            "median_word_count": word_stats["median"],
            "min_word_count": word_stats["min"],
            "max_word_count": word_stats["max"],
            "target_word_count": round(word_stats["avg"] * 1.12),  # 10-15% longer
            "avg_h2_count": _stats([r.get("h2_count", 0) for r in results])["avg"],
            "avg_h3_count": _stats([r.get("h3_count", 0) for r in results])["avg"],
            "avg_paragraph_count": _stats([r.get("paragraph_count", 0) for r in results])["avg"],
            "avg_flesch_score": round(statistics.mean(flesch_values), 1) if flesch_values else 0.0,
            "target_flesch": 65.0,
            "avg_internal_links": _stats([r.get("internal_link_count", 0) for r in results])["avg"],
            "avg_external_links": _stats([r.get("external_link_count", 0) for r in results])["avg"],
            "avg_image_count": _stats([r.get("image_count", 0) for r in results])["avg"],
            "avg_cta_count": _stats([r.get("cta_count", 0) for r in results])["avg"],
            "pct_with_schema": _pct("has_schema"),
            "pct_with_faq": _pct("has_faq"),
            "pct_with_toc": _pct("has_toc"),
            "pct_with_author": _pct("has_author"),
            "pct_with_breadcrumbs": _pct("has_breadcrumbs"),
        }

        # Identify opportunities (gaps competitors don't cover)
        opportunities = []
        if formula["pct_with_schema"] < 50:
            opportunities.append({
                "feature": "schema_markup",
                "severity": "HIGH",
                "detail": f"Only {formula['pct_with_schema']}% have schema - add Article + FAQPage",
            })
        if formula["pct_with_faq"] < 40:
            opportunities.append({
                "feature": "faq_section",
                "severity": "HIGH",
                "detail": f"Only {formula['pct_with_faq']}% have FAQ - add 5-7 questions",
            })
        if formula["pct_with_author"] < 50:
            opportunities.append({
                "feature": "author_bio",
                "severity": "MEDIUM",
                "detail": f"Only {formula['pct_with_author']}% show author - add author bio + schema",
            })
        if formula["pct_with_toc"] < 30:
            opportunities.append({
                "feature": "table_of_contents",
                "severity": "LOW",
                "detail": f"Only {formula['pct_with_toc']}% have TOC - consider adding for long content",
            })

        formula["opportunities"] = opportunities
        return formula

    def _save_analysis(self, keyword_id: str, metrics: Dict[str, Any]) -> None:
        """Save competitor analysis results to database."""
        try:
            data = {
                "keyword_id": keyword_id,
                "url": metrics["url"],
                "position": metrics.get("position"),
                "title": metrics.get("title"),
                "meta_description": metrics.get("meta_description"),
                "word_count": metrics.get("word_count", 0),
                "h1_count": metrics.get("h1_count", 0),
                "h2_count": metrics.get("h2_count", 0),
                "h3_count": metrics.get("h3_count", 0),
                "h4_count": metrics.get("h4_count", 0),
                "paragraph_count": metrics.get("paragraph_count", 0),
                "avg_paragraph_length": metrics.get("avg_paragraph_length", 0),
                "flesch_reading_ease": metrics.get("flesch_reading_ease"),
                "internal_link_count": metrics.get("internal_link_count", 0),
                "external_link_count": metrics.get("external_link_count", 0),
                "image_count": metrics.get("image_count", 0),
                "images_with_alt": metrics.get("images_with_alt", 0),
                "has_toc": metrics.get("has_toc", False),
                "has_faq": metrics.get("has_faq", False),
                "has_schema": metrics.get("has_schema", False),
                "has_author": metrics.get("has_author", False),
                "has_breadcrumbs": metrics.get("has_breadcrumbs", False),
                "schema_types": metrics.get("schema_types", []),
                "cta_count": metrics.get("cta_count", 0),
                "has_tables": metrics.get("has_tables", False),
                "table_count": metrics.get("table_count", 0),
                "video_embeds": metrics.get("video_embeds", 0),
                "raw_analysis": metrics.get("raw_analysis"),
            }
            self.supabase.table("seo_competitor_analyses").insert(data).execute()
        except Exception as e:
            logger.error(f"Failed to save analysis for {metrics.get('url')}: {e}")

    def get_analyses(self, keyword_id: str) -> List[Dict[str, Any]]:
        """
        Get competitor analyses for a keyword.

        Args:
            keyword_id: Keyword UUID

        Returns:
            List of analysis records ordered by position
        """
        result = (
            self.supabase.table("seo_competitor_analyses")
            .select("*")
            .eq("keyword_id", keyword_id)
            .order("position")
            .execute()
        )
        return result.data
