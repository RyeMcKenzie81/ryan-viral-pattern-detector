"""
QA Validation Service - Pre-publish quality assurance checks for SEO articles.

Runs a suite of checks on article content before publishing:
- Em dash detection (should use hyphens for web)
- Title length (50-60 chars ideal)
- Meta description length (150-160 chars ideal)
- Heading structure (H1 presence, H2 hierarchy)
- Readability (Flesch Reading Ease 60-70)
- Keyword placement (title, H1, first paragraph, meta description)
- Internal links presence
- Image presence and alt text
- Schema markup presence
- Word count (minimum 500)

Ported from seo-pipeline QA checks.
"""

import json
import logging
import re
from typing import Dict, Any, Optional, List

from bs4 import BeautifulSoup

from viraltracker.services.seo_pipeline.models import (
    ArticleStatus,
    QACheck,
    QAResult,
)

logger = logging.getLogger(__name__)


class QAValidationService:
    """Service for running pre-publish QA checks on SEO articles."""

    MIN_WORD_COUNT = 500
    IDEAL_TITLE_MIN = 50
    IDEAL_TITLE_MAX = 60
    IDEAL_META_MIN = 150
    IDEAL_META_MAX = 160
    IDEAL_FLESCH_MIN = 60.0
    IDEAL_FLESCH_MAX = 70.0

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
    # PUBLIC API
    # =========================================================================

    def validate_article(self, article_id: str) -> Dict[str, Any]:
        """
        Run all QA checks on an article and save the report.

        Loads the article from DB, runs checks against its content,
        saves the QA report to seo_articles.qa_report, and updates status.

        Args:
            article_id: Article UUID

        Returns:
            Dict with passed, total_checks, passed_checks, checks, failures, warnings
        """
        article = self._get_article(article_id)
        if not article:
            raise ValueError(f"Article not found: {article_id}")

        content_md = article.get("content_markdown") or article.get("phase_c_output") or article.get("phase_b_output") or ""
        content_html = article.get("content_html") or ""
        keyword = article.get("keyword", "")
        seo_title = article.get("seo_title") or article.get("title") or ""
        meta_description = article.get("meta_description") or ""
        schema_markup = article.get("schema_markup")

        checks = self.run_checks(
            content_markdown=content_md,
            content_html=content_html,
            keyword=keyword,
            seo_title=seo_title,
            meta_description=meta_description,
            schema_markup=schema_markup,
        )

        result = self._build_result(article_id, checks)

        # Save QA report to DB
        status = ArticleStatus.QA_PASSED.value if result["passed"] else ArticleStatus.QA_FAILED.value
        self._save_qa_report(article_id, result, status)

        return result

    def run_checks(
        self,
        content_markdown: str,
        content_html: str = "",
        keyword: str = "",
        seo_title: str = "",
        meta_description: str = "",
        schema_markup: Optional[Dict[str, Any]] = None,
    ) -> List[QACheck]:
        """
        Run all QA checks on article content (without DB dependency).

        Args:
            content_markdown: Article content in Markdown
            content_html: Article content as HTML (optional, parsed from markdown if empty)
            keyword: Target keyword
            seo_title: SEO title tag
            meta_description: Meta description
            schema_markup: Schema.org JSON-LD markup

        Returns:
            List of QACheck results
        """
        # Parse HTML for structural checks
        if content_html:
            soup = BeautifulSoup(content_html, "html.parser")
        else:
            soup = self._markdown_to_soup(content_markdown)

        plain_text = self._extract_plain_text(content_markdown)

        checks = []
        checks.append(self._check_word_count(plain_text))
        checks.append(self._check_em_dashes(content_markdown))
        checks.append(self._check_title_length(seo_title))
        checks.append(self._check_meta_description(meta_description))
        checks.append(self._check_heading_structure(soup, content_markdown))
        checks.append(self._check_readability(plain_text))
        checks.append(self._check_keyword_placement(
            keyword, seo_title, meta_description, content_markdown, soup
        ))
        checks.append(self._check_internal_links(soup, content_markdown))
        checks.append(self._check_images(soup, content_markdown))
        checks.append(self._check_schema_markup(schema_markup))

        return checks

    # =========================================================================
    # INDIVIDUAL CHECKS
    # =========================================================================

    def _check_word_count(self, plain_text: str) -> QACheck:
        """Check article meets minimum word count."""
        words = plain_text.split()
        count = len(words)

        if count >= self.MIN_WORD_COUNT:
            return QACheck(
                name="word_count",
                passed=True,
                message=f"Word count: {count} (minimum: {self.MIN_WORD_COUNT})",
                details={"word_count": count, "minimum": self.MIN_WORD_COUNT},
            )
        return QACheck(
            name="word_count",
            passed=False,
            severity="error",
            message=f"Word count too low: {count} (minimum: {self.MIN_WORD_COUNT})",
            details={"word_count": count, "minimum": self.MIN_WORD_COUNT},
        )

    def _check_em_dashes(self, content: str) -> QACheck:
        """Check for em dashes (should use hyphens for web readability)."""
        em_dash_count = content.count("\u2014")  # —
        en_dash_count = content.count("\u2013")  # –

        total = em_dash_count + en_dash_count
        if total == 0:
            return QACheck(
                name="em_dashes",
                passed=True,
                message="No em/en dashes found",
            )
        return QACheck(
            name="em_dashes",
            passed=False,
            severity="warning",
            message=f"Found {total} em/en dash(es). Replace with hyphens for web readability.",
            details={"em_dashes": em_dash_count, "en_dashes": en_dash_count},
        )

    def _check_title_length(self, seo_title: str) -> QACheck:
        """Check SEO title length is within ideal range."""
        length = len(seo_title)

        if not seo_title:
            return QACheck(
                name="title_length",
                passed=False,
                severity="error",
                message="No SEO title set",
                details={"length": 0},
            )

        if self.IDEAL_TITLE_MIN <= length <= self.IDEAL_TITLE_MAX:
            return QACheck(
                name="title_length",
                passed=True,
                message=f"Title length: {length} chars (ideal: {self.IDEAL_TITLE_MIN}-{self.IDEAL_TITLE_MAX})",
                details={"length": length},
            )

        severity = "warning" if length < 70 else "error"
        return QACheck(
            name="title_length",
            passed=False,
            severity=severity,
            message=f"Title length: {length} chars (ideal: {self.IDEAL_TITLE_MIN}-{self.IDEAL_TITLE_MAX})",
            details={"length": length},
        )

    def _check_meta_description(self, meta_description: str) -> QACheck:
        """Check meta description length is within ideal range."""
        length = len(meta_description)

        if not meta_description:
            return QACheck(
                name="meta_description",
                passed=False,
                severity="error",
                message="No meta description set",
                details={"length": 0},
            )

        if self.IDEAL_META_MIN <= length <= self.IDEAL_META_MAX:
            return QACheck(
                name="meta_description",
                passed=True,
                message=f"Meta description: {length} chars (ideal: {self.IDEAL_META_MIN}-{self.IDEAL_META_MAX})",
                details={"length": length},
            )

        severity = "warning" if length < 200 else "error"
        return QACheck(
            name="meta_description",
            passed=False,
            severity=severity,
            message=f"Meta description: {length} chars (ideal: {self.IDEAL_META_MIN}-{self.IDEAL_META_MAX})",
            details={"length": length},
        )

    def _check_heading_structure(self, soup: BeautifulSoup, content_md: str) -> QACheck:
        """Check heading hierarchy: H2s exist, no skipped levels.

        Note: H1 is NOT expected in article body — CMS (Shopify) renders the
        article title as the page H1. Having an H1 in the body would create
        a duplicate.
        """
        # Check in markdown as well (# heading)
        h1_md = len(re.findall(r'^# [^\n]+', content_md, re.MULTILINE))
        h2_md = len(re.findall(r'^## [^\n]+', content_md, re.MULTILINE))
        h3_md = len(re.findall(r'^### [^\n]+', content_md, re.MULTILINE))

        h1_html = len(soup.find_all("h1")) if soup else 0
        h2_html = len(soup.find_all("h2")) if soup else 0

        h1_count = max(h1_md, h1_html)
        h2_count = max(h2_md, h2_html)
        h3_count = h3_md  # Usually only in markdown

        issues = []
        if h1_count > 0:
            issues.append(f"H1 found in body ({h1_count}) — CMS provides H1 from article title, remove from body to avoid duplicate")
        if h2_count == 0:
            issues.append("No H2 headings found — article needs structure")
        if h3_count > 0 and h2_count == 0:
            issues.append("H3 used without H2 — skipped heading level")

        if not issues:
            return QACheck(
                name="heading_structure",
                passed=True,
                message=f"Heading structure OK: {h2_count} H2, {h3_count} H3 (H1 provided by CMS)",
                details={"h1_in_body": h1_count, "h2": h2_count, "h3": h3_count},
            )
        return QACheck(
            name="heading_structure",
            passed=False,
            severity="warning",
            message="; ".join(issues),
            details={"h1_in_body": h1_count, "h2": h2_count, "h3": h3_count, "issues": issues},
        )

    def _check_readability(self, plain_text: str) -> QACheck:
        """Check Flesch Reading Ease score is in target range (60-70)."""
        score = self._calculate_flesch(plain_text)

        if self.IDEAL_FLESCH_MIN <= score <= self.IDEAL_FLESCH_MAX:
            return QACheck(
                name="readability",
                passed=True,
                message=f"Flesch Reading Ease: {score} (target: {self.IDEAL_FLESCH_MIN}-{self.IDEAL_FLESCH_MAX})",
                details={"flesch_score": score},
            )

        severity = "warning"
        if score < 40 or score > 90:
            severity = "error"

        direction = "too difficult" if score < self.IDEAL_FLESCH_MIN else "too simple"
        return QACheck(
            name="readability",
            passed=False,
            severity=severity,
            message=f"Flesch Reading Ease: {score} ({direction}, target: {self.IDEAL_FLESCH_MIN}-{self.IDEAL_FLESCH_MAX})",
            details={"flesch_score": score},
        )

    def _check_keyword_placement(
        self,
        keyword: str,
        seo_title: str,
        meta_description: str,
        content_md: str,
        soup: BeautifulSoup,
    ) -> QACheck:
        """Check keyword appears in title (H1), first paragraph, and meta description.

        Note: CMS (Shopify) renders seo_title as the page H1, so we check
        seo_title for both 'title' and 'h1' placement.
        """
        if not keyword:
            return QACheck(
                name="keyword_placement",
                passed=True,
                message="No keyword specified — skipping placement check",
            )

        kw_lower = keyword.lower()
        title_has_kw = kw_lower in seo_title.lower()
        placements = {
            "title/h1": title_has_kw,  # seo_title = page H1 in CMS
            "meta_description": kw_lower in meta_description.lower(),
            "first_paragraph": False,
        }

        # Check first paragraph
        paragraphs = re.split(r'\n\n+', content_md.strip())
        for p in paragraphs:
            stripped = p.strip()
            if stripped and not stripped.startswith("#"):
                placements["first_paragraph"] = kw_lower in stripped.lower()
                break

        found = [k for k, v in placements.items() if v]
        missing = [k for k, v in placements.items() if not v]

        if not missing:
            return QACheck(
                name="keyword_placement",
                passed=True,
                message=f"Keyword '{keyword}' found in: {', '.join(found)}",
                details={"placements": placements},
            )

        severity = "error" if "title/h1" in missing else "warning"
        return QACheck(
            name="keyword_placement",
            passed=False,
            severity=severity,
            message=f"Keyword '{keyword}' missing from: {', '.join(missing)}",
            details={"placements": placements, "missing": missing},
        )

    def _check_internal_links(self, soup: BeautifulSoup, content_md: str) -> QACheck:
        """Check for presence of internal links."""
        # Count markdown links
        md_links = re.findall(r'\[([^\]]+)\]\(([^)]+)\)', content_md)

        # Count HTML links
        html_links = soup.find_all("a", href=True) if soup else []

        total = max(len(md_links), len(html_links))

        if total >= 2:
            return QACheck(
                name="internal_links",
                passed=True,
                message=f"Found {total} link(s) in article",
                details={"link_count": total},
            )
        return QACheck(
            name="internal_links",
            passed=False,
            severity="warning",
            message=f"Only {total} link(s) found — add internal links for SEO",
            details={"link_count": total},
        )

    def _check_images(self, soup: BeautifulSoup, content_md: str) -> QACheck:
        """Check for images and alt text."""
        # Check markdown images: ![alt](url)
        md_images = re.findall(r'!\[([^\]]*)\]\(([^)]+)\)', content_md)

        # Check HTML images
        html_images = soup.find_all("img") if soup else []

        total = max(len(md_images), len(html_images))

        if total == 0:
            return QACheck(
                name="images",
                passed=False,
                severity="warning",
                message="No images found — add at least one image",
                details={"image_count": 0, "with_alt": 0},
            )

        # Check alt text
        if md_images:
            with_alt = sum(1 for alt, _ in md_images if alt.strip())
        elif html_images:
            with_alt = sum(1 for img in html_images if img.get("alt", "").strip())
        else:
            with_alt = 0

        missing_alt = total - with_alt
        if missing_alt == 0:
            return QACheck(
                name="images",
                passed=True,
                message=f"Found {total} image(s), all with alt text",
                details={"image_count": total, "with_alt": with_alt},
            )
        return QACheck(
            name="images",
            passed=False,
            severity="warning",
            message=f"Found {total} image(s), {missing_alt} missing alt text",
            details={"image_count": total, "with_alt": with_alt, "missing_alt": missing_alt},
        )

    def _check_schema_markup(self, schema_markup: Optional[Dict[str, Any]]) -> QACheck:
        """Check for schema.org structured data."""
        if schema_markup and isinstance(schema_markup, dict):
            schema_type = schema_markup.get("@type", "unknown")
            return QACheck(
                name="schema_markup",
                passed=True,
                message=f"Schema markup present (type: {schema_type})",
                details={"schema_type": schema_type},
            )
        return QACheck(
            name="schema_markup",
            passed=False,
            severity="warning",
            message="No schema markup found — add Article schema for better SERP results",
        )

    # =========================================================================
    # HELPERS
    # =========================================================================

    @staticmethod
    def _calculate_flesch(text: str) -> float:
        """
        Calculate Flesch Reading Ease score.

        Formula: 206.835 - (1.015 * avg words/sentence) - (84.6 * avg syllables/word)
        Same implementation as CompetitorAnalysisService.
        """
        sentences = re.split(r'[.!?]+', text)
        sentences = [s.strip() for s in sentences if s.strip()]
        if not sentences:
            return 0.0

        words = re.findall(r'\b[a-zA-Z]+\b', text)
        if not words:
            return 0.0

        total_syllables = sum(QAValidationService._count_syllables(w) for w in words)

        avg_words_per_sentence = len(words) / len(sentences)
        avg_syllables_per_word = total_syllables / len(words)

        score = 206.835 - (1.015 * avg_words_per_sentence) - (84.6 * avg_syllables_per_word)
        return round(max(0.0, min(100.0, score)), 1)

    @staticmethod
    def _count_syllables(word: str) -> int:
        """Count syllables in a word using vowel-group heuristic."""
        word = word.lower()
        vowel_groups = re.findall(r'[aeiouy]+', word)
        count = len(vowel_groups)
        if word.endswith('e') and count > 1:
            count -= 1
        return max(1, count)

    @staticmethod
    def _extract_plain_text(markdown: str) -> str:
        """Extract plain text from markdown, removing markup."""
        text = markdown
        # Remove images
        text = re.sub(r'!\[([^\]]*)\]\([^)]+\)', r'\1', text)
        # Remove links but keep text
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
        # Remove headings markers
        text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
        # Remove bold/italic markers
        text = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', text)
        text = re.sub(r'_{1,3}([^_]+)_{1,3}', r'\1', text)
        # Remove code blocks
        text = re.sub(r'```[\s\S]*?```', '', text)
        text = re.sub(r'`([^`]+)`', r'\1', text)
        # Remove horizontal rules
        text = re.sub(r'^---+$', '', text, flags=re.MULTILINE)
        # Remove blockquotes
        text = re.sub(r'^>\s+', '', text, flags=re.MULTILINE)
        # Remove list markers
        text = re.sub(r'^[\s]*[-*+]\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'^[\s]*\d+\.\s+', '', text, flags=re.MULTILINE)
        # Collapse whitespace
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    @staticmethod
    def _markdown_to_soup(markdown: str) -> BeautifulSoup:
        """Convert markdown to BeautifulSoup for structural analysis."""
        try:
            from markdown_it import MarkdownIt
            md = MarkdownIt()
            html = md.render(markdown)
            return BeautifulSoup(html, "html.parser")
        except ImportError:
            return BeautifulSoup("", "html.parser")

    def _build_result(self, article_id: str, checks: List[QACheck]) -> Dict[str, Any]:
        """Build QA result dict from checks."""
        failures = [c for c in checks if not c.passed and c.severity == "error"]
        warnings = [c for c in checks if not c.passed and c.severity == "warning"]
        passed_checks = [c for c in checks if c.passed]

        # Pass if no errors (warnings are OK)
        overall_passed = len(failures) == 0

        return {
            "article_id": article_id,
            "passed": overall_passed,
            "total_checks": len(checks),
            "passed_checks": len(passed_checks),
            "error_count": len(failures),
            "warning_count": len(warnings),
            "checks": [c.model_dump() for c in checks],
            "failures": [c.model_dump() for c in failures],
            "warnings": [c.model_dump() for c in warnings],
        }

    def _get_article(self, article_id: str) -> Optional[Dict[str, Any]]:
        """Get article from DB."""
        result = (
            self.supabase.table("seo_articles")
            .select("*")
            .eq("id", article_id)
            .execute()
        )
        return result.data[0] if result.data else None

    def _save_qa_report(self, article_id: str, report: Dict[str, Any], status: str) -> None:
        """Save QA report to seo_articles.qa_report and update status."""
        try:
            self.supabase.table("seo_articles").update({
                "qa_report": report,
                "status": status,
            }).eq("id", article_id).execute()
            logger.info(f"Saved QA report for article {article_id}: {'PASS' if report['passed'] else 'FAIL'}")
        except Exception as e:
            logger.error(f"Failed to save QA report for {article_id}: {e}")
            raise
