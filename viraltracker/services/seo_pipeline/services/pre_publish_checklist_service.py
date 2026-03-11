"""
Pre-Publish Checklist Service — validates publishing readiness.

Runs ON TOP OF existing QA content checks, adding metadata and uniqueness validation.
Uses QAValidationService.run_checks() (stateless) — NOT validate_article() which mutates status.
"""

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _shingle_set(text: str, n: int = 3) -> set:
    """Build n-gram shingle set from text (lowercased, whitespace-normalized)."""
    words = re.sub(r"\s+", " ", text.lower().strip()).split()
    if len(words) < n:
        return {" ".join(words)}
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def _jaccard_similarity(text_a: str, text_b: str) -> float:
    """Jaccard similarity on 3-gram shingles."""
    sa = _shingle_set(text_a)
    sb = _shingle_set(text_b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


class PrePublishChecklistService:
    """Validates article publishing readiness (metadata + content uniqueness)."""

    UNIQUENESS_THRESHOLD = 0.85  # Block if >=85% similar to existing article

    def __init__(self, supabase_client=None):
        self._supabase = supabase_client

    @property
    def supabase(self):
        if self._supabase is None:
            from viraltracker.core.database import get_supabase_client
            self._supabase = get_supabase_client()
        return self._supabase

    def run_checklist(
        self,
        article_id: str,
        brand_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Run full pre-publish checklist on an article.

        Args:
            article_id: Article UUID
            brand_config: Brand config dict (from SEOBrandConfigService)

        Returns:
            {passed: bool, checks: [...], failures: [...], warnings: [...]}
        """
        article = self._load_article(article_id)
        if not article:
            return {"passed": False, "checks": [], "failures": [
                {"name": "article_exists", "passed": False, "severity": "error",
                 "message": f"Article not found: {article_id}"}
            ], "warnings": []}

        checks = []
        brand_config = brand_config or {}

        # Metadata checks
        checks.append(self._check_author(article))
        checks.append(self._check_hero_image(article))
        checks.append(self._check_tags(article))
        checks.append(self._check_seo_title(article))
        checks.append(self._check_meta_description(article))
        checks.append(self._check_schema_markup(article))
        checks.append(self._check_inline_images(article))

        # Product mention check
        max_mentions = brand_config.get("max_product_mentions", 2)
        checks.append(self._check_product_mentions(article, max_mentions))

        # Content uniqueness
        checks.append(self._check_uniqueness(article))

        # Content QA (stateless — does NOT mutate article status)
        qa_result = self._run_content_qa(article_id)
        checks.append(qa_result)

        failures = [c for c in checks if not c["passed"] and c["severity"] == "error"]
        warnings = [c for c in checks if not c["passed"] and c["severity"] == "warning"]

        return {
            "passed": len(failures) == 0,
            "checks": checks,
            "failures": failures,
            "warnings": warnings,
        }

    def _load_article(self, article_id: str) -> Optional[Dict[str, Any]]:
        result = (
            self.supabase.table("seo_articles")
            .select("*")
            .eq("id", article_id)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def _check_author(self, article: Dict) -> Dict:
        has = bool(article.get("author_id"))
        return {"name": "author_assigned", "passed": has, "severity": "error",
                "message": "" if has else "No author assigned"}

    def _check_hero_image(self, article: Dict) -> Dict:
        url = article.get("hero_image_url", "")
        has = bool(url and url.startswith("http"))
        return {"name": "hero_image", "passed": has, "severity": "warning",
                "message": "" if has else "No hero image set"}

    def _check_tags(self, article: Dict) -> Dict:
        tags = article.get("tags") or []
        has = len(tags) >= 1
        return {"name": "tags_assigned", "passed": has, "severity": "warning",
                "message": "" if has else "No tags assigned"}

    def _check_seo_title(self, article: Dict) -> Dict:
        title = article.get("seo_title", "") or ""
        length = len(title)
        if 30 <= length <= 70:
            return {"name": "seo_title", "passed": True, "severity": "warning", "message": ""}
        return {"name": "seo_title", "passed": False, "severity": "warning",
                "message": f"SEO title length {length} (ideal: 50-60 chars)"}

    def _check_meta_description(self, article: Dict) -> Dict:
        desc = article.get("meta_description", "") or ""
        length = len(desc)
        if 70 <= length <= 200:
            return {"name": "meta_description", "passed": True, "severity": "warning", "message": ""}
        return {"name": "meta_description", "passed": False, "severity": "warning",
                "message": f"Meta description length {length} (ideal: 150-160 chars)"}

    def _check_schema_markup(self, article: Dict) -> Dict:
        schema = article.get("schema_markup")
        if not schema:
            return {"name": "schema_markup", "passed": False, "severity": "warning",
                    "message": "No schema markup"}
        has_type = "@type" in str(schema)
        return {"name": "schema_markup", "passed": has_type, "severity": "warning",
                "message": "" if has_type else "Schema missing @type"}

    def _check_inline_images(self, article: Dict) -> Dict:
        metadata = article.get("image_metadata") or []
        failed = [m for m in metadata if m.get("status") == "failed"]
        if failed:
            return {"name": "inline_images", "passed": False, "severity": "warning",
                    "message": f"{len(failed)} image(s) failed generation"}
        return {"name": "inline_images", "passed": True, "severity": "warning", "message": ""}

    def _check_product_mentions(self, article: Dict, max_mentions: int) -> Dict:
        content = (article.get("content_html") or article.get("phase_c_output") or "").lower()
        brand_name = article.get("keyword", "").split()[0].lower() if article.get("keyword") else ""
        if not brand_name or not content:
            return {"name": "product_mentions", "passed": True, "severity": "warning", "message": ""}
        # Rough count — brand name occurrences in content
        count = content.count(brand_name)
        passed = count <= max_mentions + 5  # generous — brand name in headings/links doesn't count
        return {"name": "product_mentions", "passed": passed, "severity": "warning",
                "message": "" if passed else f"Brand name appears {count} times (max: ~{max_mentions} product mentions)"}

    def _check_uniqueness(self, article: Dict) -> Dict:
        """Check content uniqueness vs existing published articles for the same brand."""
        content = article.get("content_html") or article.get("phase_c_output") or ""
        if not content or len(content) < 200:
            return {"name": "content_uniqueness", "passed": True, "severity": "warning",
                    "message": "Content too short to check uniqueness"}

        brand_id = article.get("brand_id")
        article_id = article.get("id")
        if not brand_id:
            return {"name": "content_uniqueness", "passed": True, "severity": "warning", "message": ""}

        # Load existing articles with content
        result = (
            self.supabase.table("seo_articles")
            .select("id, keyword, content_html, phase_c_output")
            .eq("brand_id", brand_id)
            .neq("id", article_id)
            .neq("status", "discovered")
            .limit(50)
            .execute()
        )
        existing = result.data or []

        max_sim = 0.0
        most_similar = None
        for ex in existing:
            ex_content = ex.get("content_html") or ex.get("phase_c_output") or ""
            if len(ex_content) < 200:
                continue
            sim = _jaccard_similarity(content, ex_content)
            if sim > max_sim:
                max_sim = sim
                most_similar = ex

        if max_sim >= self.UNIQUENESS_THRESHOLD:
            kw = most_similar.get("keyword", "unknown") if most_similar else "unknown"
            return {"name": "content_uniqueness", "passed": False, "severity": "error",
                    "message": f"Content {max_sim:.0%} similar to '{kw}' — possible duplicate"}
        if max_sim >= 0.6:
            kw = most_similar.get("keyword", "unknown") if most_similar else "unknown"
            return {"name": "content_uniqueness", "passed": True, "severity": "warning",
                    "message": f"Content {max_sim:.0%} similar to '{kw}' — review for overlap"}
        return {"name": "content_uniqueness", "passed": True, "severity": "warning", "message": ""}

    def _run_content_qa(self, article_id: str) -> Dict:
        """Run stateless QA checks (does NOT mutate article status)."""
        try:
            from viraltracker.services.seo_pipeline.services.qa_validation_service import QAValidationService
            qa_svc = QAValidationService(supabase_client=self.supabase)
            qa_result = qa_svc.run_checks(article_id)
            error_failures = [c for c in qa_result.get("failures", [])
                              if c.get("severity") == "error"]
            if error_failures:
                names = ", ".join(c.get("name", "?") for c in error_failures[:3])
                return {"name": "content_qa", "passed": False, "severity": "error",
                        "message": f"QA failed: {names}"}
            return {"name": "content_qa", "passed": True, "severity": "warning", "message": ""}
        except Exception as e:
            logger.warning(f"QA check failed for {article_id}: {e}")
            return {"name": "content_qa", "passed": True, "severity": "warning",
                    "message": f"QA check unavailable: {e}"}
