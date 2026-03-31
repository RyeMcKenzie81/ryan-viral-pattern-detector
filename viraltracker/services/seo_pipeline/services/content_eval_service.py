"""
Content Evaluation Service — automated QA + image evaluation for SEO articles.

Aggregates three evaluation layers:
1. QA checks (qa_validation_service.py) — word count, headings, readability, etc.
2. Pre-publish checklist (pre_publish_checklist_service.py) — metadata, uniqueness
3. AI image evaluation (Claude vision) — brand-specific visual rules

Produces a single pass/fail verdict per article. Passed articles are enqueued
for scheduled publishing. Failed articles surface in the Exceptions Dashboard.
"""

import base64
import hashlib
import json
import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


class ContentEvalService:
    """Evaluates SEO article content and images against brand-specific rules."""

    def __init__(self, supabase_client=None):
        self._supabase = supabase_client
        self._anthropic = None

    @property
    def supabase(self):
        """Lazy-load Supabase client."""
        if self._supabase is None:
            from viraltracker.core.database import get_supabase_client
            self._supabase = get_supabase_client()
        return self._supabase

    @property
    def anthropic(self):
        """Lazy-load Anthropic client."""
        if self._anthropic is None:
            import anthropic
            self._anthropic = anthropic.Anthropic()
        return self._anthropic

    # =========================================================================
    # PUBLIC API
    # =========================================================================

    def evaluate_article(
        self,
        article_id: str,
        brand_id: str,
        organization_id: str,
    ) -> Dict[str, Any]:
        """
        Run full content evaluation on an article.

        Runs QA checks, pre-publish checklist, and AI image evaluation.
        Stores result in seo_content_eval_results. Updates article status
        to eval_passed or eval_failed.

        Args:
            article_id: Article UUID
            brand_id: Brand UUID
            organization_id: Organization UUID

        Returns:
            Dict with verdict, check counts, and detailed results
        """
        # Load brand content policy
        policy = self._get_policy(brand_id)

        # Run QA checks (stateless — does NOT mutate article status)
        from viraltracker.services.seo_pipeline.services.qa_validation_service import QAValidationService
        qa_service = QAValidationService(supabase_client=self.supabase)
        qa_result = self._run_qa_checks(qa_service, article_id)

        # Run pre-publish checklist
        from viraltracker.services.seo_pipeline.services.pre_publish_checklist_service import PrePublishChecklistService
        checklist_service = PrePublishChecklistService(supabase_client=self.supabase)
        checklist_result = checklist_service.run_checklist(article_id)

        # Run AI image evaluation if enabled
        image_eval_result = None
        if policy.get("image_eval_enabled", True):
            rules = policy.get("image_eval_rules", [])
            min_confidence = policy.get("image_eval_min_confidence", 0.8)
            if rules:
                image_eval_result = self._evaluate_images(
                    article_id, rules, min_confidence
                )

        # Aggregate verdict
        result = self._aggregate_verdict(
            qa_result, checklist_result, image_eval_result, policy
        )

        # Store result
        eval_record = {
            "article_id": article_id,
            "brand_id": brand_id,
            "organization_id": organization_id,
            "verdict": result["verdict"],
            "total_checks": result["total_checks"],
            "passed_checks": result["passed_checks"],
            "failed_checks": result["failed_checks"],
            "warning_count": result["warning_count"],
            "qa_result": json.dumps(qa_result) if qa_result else None,
            "checklist_result": json.dumps(checklist_result) if checklist_result else None,
            "image_eval_result": json.dumps(image_eval_result) if image_eval_result else None,
            "evaluated_by": "scheduler",
        }
        self._save_eval_result(eval_record)

        # Update article status
        new_status = "eval_passed" if result["verdict"] == "passed" else "eval_failed"
        self.supabase.table("seo_articles").update(
            {"status": new_status}
        ).eq("id", article_id).execute()

        logger.info(
            f"Article {article_id} evaluation: {result['verdict']} "
            f"({result['passed_checks']}/{result['total_checks']} checks passed, "
            f"{result['warning_count']} warnings)"
        )

        return result

    def get_pending_articles(
        self,
        brand_id: Optional[str] = None,
        organization_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Find articles ready for evaluation (qa_passed or optimized, not yet evaluated).

        Args:
            brand_id: Optional brand filter
            organization_id: Optional org filter

        Returns:
            List of article dicts
        """
        query = (
            self.supabase.table("seo_articles")
            .select("id, brand_id, organization_id, keyword, title, status")
            .in_("status", ["qa_passed", "optimized"])
        )

        if brand_id:
            query = query.eq("brand_id", brand_id)
        if organization_id:
            query = query.eq("organization_id", organization_id)

        # Exclude articles that already have eval results
        # We do this in Python since Supabase doesn't support NOT EXISTS easily
        articles = (query.execute()).data or []

        if not articles:
            return []

        article_ids = [a["id"] for a in articles]
        existing = (
            self.supabase.table("seo_content_eval_results")
            .select("article_id")
            .in_("article_id", article_ids)
            .execute()
        ).data or []
        already_evaluated = {r["article_id"] for r in existing}

        return [a for a in articles if a["id"] not in already_evaluated]

    def get_eval_result(self, article_id: str) -> Optional[Dict[str, Any]]:
        """Get the most recent evaluation result for an article."""
        result = (
            self.supabase.table("seo_content_eval_results")
            .select("*")
            .eq("article_id", article_id)
            .is_("superseded_by", "null")
            .order("evaluated_at", desc=True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def get_failed_evals(
        self,
        brand_id: Optional[str] = None,
        organization_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get failed evaluation results for the exceptions dashboard."""
        query = (
            self.supabase.table("seo_content_eval_results")
            .select("*, seo_articles(keyword, title, seo_title)")
            .eq("verdict", "failed")
            .eq("manually_overridden", False)
            .is_("superseded_by", "null")
            .order("evaluated_at", desc=True)
            .limit(limit)
        )
        if brand_id:
            query = query.eq("brand_id", brand_id)
        if organization_id:
            query = query.eq("organization_id", organization_id)

        return (query.execute()).data or []

    def override_eval(
        self, eval_id: str, reason: str
    ) -> Dict[str, Any]:
        """
        Override a failed evaluation (human approves despite failures).

        Args:
            eval_id: Eval result UUID
            reason: Human-provided reason for override

        Returns:
            Updated eval result
        """
        result = (
            self.supabase.table("seo_content_eval_results")
            .update({
                "manually_overridden": True,
                "override_reason": reason,
            })
            .eq("id", eval_id)
            .execute()
        )
        if result.data:
            article_id = result.data[0]["article_id"]
            self.supabase.table("seo_articles").update(
                {"status": "eval_passed"}
            ).eq("id", article_id).execute()
            logger.info(f"Eval {eval_id} overridden: {reason}")
        return result.data[0] if result.data else {}

    @staticmethod
    def compute_content_hash(article: Dict[str, Any]) -> str:
        """
        Compute a content hash for idempotency.

        Hash = SHA256(content_html + hero_image_url + sorted inline image URLs)
        """
        content_html = article.get("content_html") or ""
        hero_url = article.get("hero_image_url") or ""

        # Collect inline image URLs
        inline_images = article.get("inline_images") or []
        if isinstance(inline_images, str):
            try:
                inline_images = json.loads(inline_images)
            except (json.JSONDecodeError, TypeError):
                inline_images = []
        inline_urls = sorted(
            img.get("url", "") if isinstance(img, dict) else str(img)
            for img in inline_images
        )

        hash_input = content_html + hero_url + "|".join(inline_urls)
        return hashlib.sha256(hash_input.encode()).hexdigest()[:16]

    # =========================================================================
    # PRIVATE — QA checks
    # =========================================================================

    def _run_qa_checks(
        self, qa_service, article_id: str
    ) -> Dict[str, Any]:
        """Run QA checks without mutating article status."""
        try:
            article = self._get_article(article_id)
            if not article:
                return {"passed": False, "checks": [], "failures": [
                    {"name": "article_exists", "passed": False,
                     "severity": "error", "message": "Article not found"}
                ]}

            content_md = (
                article.get("content_markdown")
                or article.get("phase_c_output")
                or article.get("phase_b_output")
                or ""
            )
            content_html = article.get("content_html") or ""
            keyword = article.get("keyword", "")
            seo_title = article.get("seo_title") or article.get("title") or ""
            meta_description = article.get("meta_description") or ""
            schema_markup = article.get("schema_markup")

            checks = qa_service.run_checks(
                content_markdown=content_md,
                content_html=content_html,
                keyword=keyword,
                seo_title=seo_title,
                meta_description=meta_description,
                schema_markup=schema_markup,
            )

            failures = [c for c in checks if not c.passed and c.severity == "error"]
            warnings = [c for c in checks if not c.passed and c.severity == "warning"]

            return {
                "passed": len(failures) == 0,
                "total_checks": len(checks),
                "passed_checks": sum(1 for c in checks if c.passed),
                "checks": checks,
                "failures": failures,
                "warnings": warnings,
            }
        except Exception as e:
            logger.error(f"QA checks failed for article {article_id}: {e}")
            return {
                "passed": False,
                "checks": [],
                "failures": [{"name": "qa_error", "passed": False,
                              "severity": "error", "message": str(e)}],
                "warnings": [],
            }

    # =========================================================================
    # PRIVATE — AI image evaluation
    # =========================================================================

    def _evaluate_images(
        self,
        article_id: str,
        rules: List[Dict[str, str]],
        min_confidence: float,
    ) -> Dict[str, Any]:
        """
        Evaluate all images for an article using Claude vision.

        Args:
            article_id: Article UUID
            rules: List of {"rule": str, "severity": "error"|"warning"}
            min_confidence: Minimum confidence for definitive pass/fail

        Returns:
            Dict with images_evaluated, images_passed, images_failed, evaluations
        """
        article = self._get_article(article_id)
        if not article:
            return {"images_evaluated": 0, "images_passed": 0,
                    "images_failed": 0, "uncertain_count": 0, "evaluations": []}

        images_to_eval = []

        # Hero image
        hero_url = article.get("hero_image_url")
        if hero_url:
            images_to_eval.append({"url": hero_url, "type": "hero"})

        # Inline images
        inline_images = article.get("inline_images") or []
        if isinstance(inline_images, str):
            try:
                inline_images = json.loads(inline_images)
            except (json.JSONDecodeError, TypeError):
                inline_images = []
        for img in inline_images:
            url = img.get("url") if isinstance(img, dict) else str(img)
            if url:
                images_to_eval.append({"url": url, "type": "inline"})

        if not images_to_eval:
            return {"images_evaluated": 0, "images_passed": 0,
                    "images_failed": 0, "uncertain_count": 0, "evaluations": []}

        evaluations = []
        images_passed = 0
        images_failed = 0
        uncertain_count = 0

        article_context = f"Article: {article.get('title', 'Unknown')} | Keyword: {article.get('keyword', '')}"

        for img_info in images_to_eval:
            eval_result = self._evaluate_single_image(
                img_info["url"], img_info["type"], rules, min_confidence, article_context
            )
            if eval_result is None:
                # API failure — skip this image (transient error)
                continue

            evaluations.append(eval_result)
            if eval_result["passed"]:
                images_passed += 1
            elif eval_result.get("uncertain"):
                uncertain_count += 1
            else:
                images_failed += 1

        return {
            "images_evaluated": len(evaluations),
            "images_passed": images_passed,
            "images_failed": images_failed,
            "uncertain_count": uncertain_count,
            "evaluations": evaluations,
        }

    def _evaluate_single_image(
        self,
        image_url: str,
        image_type: str,
        rules: List[Dict[str, str]],
        min_confidence: float,
        article_context: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Evaluate a single image against brand rules using Claude vision.

        Returns None on transient API failure (image will be skipped, not failed).
        """
        # Fetch image as base64
        image_base64, media_type = self._fetch_image(image_url)
        if not image_base64:
            logger.warning(f"Could not fetch image: {image_url}")
            return None

        # Build rules text
        rules_text = "\n".join(
            f"- Rule {i+1} ({r['severity'].upper()}): {r['rule']}"
            for i, r in enumerate(rules)
        )

        prompt = f"""You are evaluating a generated image for a blog article. Look for flaws.
Assume the image has problems and verify each rule independently.

Context: {article_context}
Image type: {image_type}

RULES TO CHECK:
{rules_text}

For EACH rule, respond with a JSON object. Be honest and critical.

Respond with ONLY a JSON array, no other text:
[
  {{
    "rule_index": 1,
    "rule": "rule text",
    "passed": true/false,
    "confidence": 0.0-1.0,
    "explanation": "brief explanation of what you see"
  }}
]"""

        try:
            response = self.anthropic.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1024,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": image_base64,
                                },
                            },
                            {
                                "type": "text",
                                "text": prompt,
                            },
                        ],
                    }
                ],
            )

            response_text = response.content[0].text.strip()
            # Clean markdown fences if present
            if response_text.startswith("```"):
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]
                response_text = response_text.strip()

            rule_results = json.loads(response_text)

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse image eval response: {e}")
            return None
        except Exception as e:
            error_str = str(e).lower()
            if any(kw in error_str for kw in ["rate", "timeout", "connection", "503", "529"]):
                logger.warning(f"Transient API error evaluating image: {e}")
                return None  # Skip — retry next cycle
            logger.error(f"Image evaluation failed: {e}")
            return None

        # Apply confidence gating and determine pass/fail
        image_passed = True
        uncertain = False
        processed_rules = []

        for i, rule_def in enumerate(rules):
            # Find matching result from Claude
            matching = next(
                (r for r in rule_results if r.get("rule_index") == i + 1),
                None,
            )
            if not matching:
                processed_rules.append({
                    "rule": rule_def["rule"],
                    "passed": True,
                    "confidence": 0.0,
                    "explanation": "Rule not evaluated by vision model",
                })
                continue

            confidence = matching.get("confidence", 0.5)
            rule_passed = matching.get("passed", True)

            if not rule_passed and confidence >= min_confidence:
                # Definitive failure
                if rule_def["severity"] == "error":
                    image_passed = False
            elif not rule_passed and confidence < min_confidence:
                # Uncertain — flag for human review
                uncertain = True

            processed_rules.append({
                "rule": rule_def["rule"],
                "severity": rule_def["severity"],
                "passed": rule_passed,
                "confidence": confidence,
                "explanation": matching.get("explanation", ""),
            })

        return {
            "image_url": image_url,
            "image_type": image_type,
            "passed": image_passed and not uncertain,
            "uncertain": uncertain,
            "rules": processed_rules,
        }

    def _fetch_image(self, url: str) -> tuple:
        """Fetch image from URL and return (base64_data, media_type)."""
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.get(url)
                response.raise_for_status()

                content_type = response.headers.get("content-type", "image/png")
                if "jpeg" in content_type or "jpg" in content_type:
                    media_type = "image/jpeg"
                elif "png" in content_type:
                    media_type = "image/png"
                elif "webp" in content_type:
                    media_type = "image/webp"
                elif "gif" in content_type:
                    media_type = "image/gif"
                else:
                    media_type = "image/png"

                b64 = base64.b64encode(response.content).decode("utf-8")
                return b64, media_type
        except Exception as e:
            logger.error(f"Failed to fetch image from {url}: {e}")
            return None, None

    # =========================================================================
    # PRIVATE — Verdict aggregation
    # =========================================================================

    def _aggregate_verdict(
        self,
        qa_result: Dict[str, Any],
        checklist_result: Dict[str, Any],
        image_eval_result: Optional[Dict[str, Any]],
        policy: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Aggregate all check results into a single verdict."""
        max_warnings = policy.get("max_warnings_for_auto_publish", 0)

        total_checks = 0
        passed_checks = 0
        failed_checks = 0
        warning_count = 0

        # Count QA results
        if qa_result:
            total_checks += qa_result.get("total_checks", 0)
            passed_checks += qa_result.get("passed_checks", 0)
            failed_checks += len(qa_result.get("failures", []))
            warning_count += len(qa_result.get("warnings", []))

        # Count checklist results
        if checklist_result:
            checks = checklist_result.get("checks", [])
            total_checks += len(checks)
            passed_checks += sum(1 for c in checks if c.get("passed"))
            failed_checks += len(checklist_result.get("failures", []))
            warning_count += len(checklist_result.get("warnings", []))

        # Count image eval results
        if image_eval_result:
            total_checks += image_eval_result.get("images_evaluated", 0)
            passed_checks += image_eval_result.get("images_passed", 0)
            failed_checks += image_eval_result.get("images_failed", 0)
            # Uncertain images count as warnings
            warning_count += image_eval_result.get("uncertain_count", 0)

        # Determine verdict
        has_errors = failed_checks > 0
        warnings_exceeded = warning_count > max_warnings

        if has_errors:
            verdict = "failed"
        elif warnings_exceeded:
            verdict = "failed"
        else:
            verdict = "passed"

        return {
            "verdict": verdict,
            "total_checks": total_checks,
            "passed_checks": passed_checks,
            "failed_checks": failed_checks,
            "warning_count": warning_count,
        }

    # =========================================================================
    # PRIVATE — Database helpers
    # =========================================================================

    def _get_article(self, article_id: str) -> Optional[Dict[str, Any]]:
        """Load article from DB."""
        result = (
            self.supabase.table("seo_articles")
            .select("*")
            .eq("id", article_id)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def _get_policy(self, brand_id: str) -> Dict[str, Any]:
        """Load brand content policy, returning defaults if none exists."""
        result = (
            self.supabase.table("brand_content_policies")
            .select("*")
            .eq("brand_id", brand_id)
            .limit(1)
            .execute()
        )
        if result.data:
            return result.data[0]
        # Return defaults
        return {
            "image_eval_enabled": True,
            "image_eval_rules": [],
            "image_eval_min_confidence": 0.8,
            "publish_enabled": False,
            "publish_times_per_day": 2,
            "publish_window_start": "09:00",
            "publish_window_end": "17:00",
            "publish_timezone": "America/New_York",
            "publish_days_of_week": [1, 2, 3, 4, 5],
            "interlink_enabled": True,
            "interlink_modes": ["auto_link", "bidirectional"],
            "max_warnings_for_auto_publish": 0,
        }

    def _save_eval_result(self, record: Dict[str, Any]) -> Optional[str]:
        """Save evaluation result to DB."""
        try:
            result = (
                self.supabase.table("seo_content_eval_results")
                .insert(record)
                .execute()
            )
            return result.data[0]["id"] if result.data else None
        except Exception as e:
            logger.error(f"Failed to save eval result: {e}")
            return None
