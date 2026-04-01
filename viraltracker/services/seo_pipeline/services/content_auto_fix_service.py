"""
Content Auto-Fix Service — automated repair of fixable QA issues before evaluation.

Runs before ContentEvalService to fix issues that would cause unnecessary eval failures:
- Tier 1 (deterministic): em/en dash replacement, FAQPage schema generation
- Tier 2 (AI rewrite): SEO title optimization, meta description generation, keyword placement

Fixes are logged with before/after diffs for auditability.
"""

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

AUTOFIX_MODEL = "claude-sonnet-4-20250514"

# Map QA check names to fix methods
FIXABLE_CHECKS = {
    # Tier 1 (deterministic)
    "em_dashes": "_fix_em_dashes",
    "schema_markup": "_fix_schema_markup",
    # Tier 2 (AI rewrite)
    "title_length": "_fix_seo_title",
    "meta_description": "_fix_meta_description",
    "keyword_placement": "_fix_keyword_placement",
}


class ContentAutoFixService:
    """Fixes auto-repairable QA issues on SEO articles before evaluation."""

    def __init__(self, supabase_client=None, usage_tracker=None):
        self._supabase = supabase_client
        self._usage_tracker = usage_tracker
        self._anthropic = None

    @property
    def supabase(self):
        if self._supabase is None:
            from viraltracker.core.database import get_supabase_client
            self._supabase = get_supabase_client()
        return self._supabase

    @property
    def anthropic(self):
        if self._anthropic is None:
            import anthropic
            self._anthropic = anthropic.Anthropic()
        return self._anthropic

    # =========================================================================
    # PUBLIC API
    # =========================================================================

    def fix_article(
        self,
        article_id: str,
        brand_id: str,
        organization_id: str,
    ) -> Dict[str, Any]:
        """
        Run all applicable auto-fixes on an article.

        1. Load article from DB
        2. Run QA checks to identify failing checks
        3. Apply Tier 1 (deterministic) fixes
        4. Apply Tier 2 (AI rewrite) fixes via single Claude call
        5. Save fixed fields to DB
        6. Return fix report with before/after diffs

        Args:
            article_id: Article UUID
            brand_id: Brand UUID
            organization_id: Organization UUID

        Returns:
            {
                "fixed": bool,
                "fixes_applied": [{check, method, before, after, ...}],
                "fixes_failed": [{check, method, reason}],
                "fixes_skipped": [check_name, ...],
                "total_fixes": int,
                "ai_cost_tokens": int,
            }
        """
        report = {
            "fixed": False,
            "fixes_applied": [],
            "fixes_failed": [],
            "fixes_skipped": [],
            "total_fixes": 0,
            "ai_cost_tokens": 0,
        }

        # Load article
        article = self._get_article(article_id)
        if not article:
            report["fixes_failed"].append({
                "check": "load_article",
                "method": "db_fetch",
                "reason": f"Article not found: {article_id}",
            })
            return report

        # Run QA checks to identify what needs fixing
        from viraltracker.services.seo_pipeline.services.qa_validation_service import QAValidationService
        qa_svc = QAValidationService()

        content_md = article.get("content_markdown") or article.get("phase_c_output") or article.get("phase_b_output") or ""
        seo_title = article.get("seo_title") or article.get("title") or ""
        meta_description = article.get("meta_description") or ""
        keyword = article.get("keyword") or ""
        schema_markup = article.get("schema_markup")

        checks = qa_svc.run_checks(
            content_markdown=content_md,
            seo_title=seo_title,
            meta_description=meta_description,
            keyword=keyword,
            schema_markup=schema_markup,
        )

        # Identify which fixable checks failed
        failing_fixable = {}
        for check in checks:
            if not check.passed and check.name in FIXABLE_CHECKS:
                failing_fixable[check.name] = check

        if not failing_fixable:
            logger.info(f"Article {article_id}: no fixable issues found")
            return report

        logger.info(f"Article {article_id}: {len(failing_fixable)} fixable issues: {list(failing_fixable.keys())}")

        # Track updates to save to DB
        db_updates = {}

        # ---- Tier 1: Deterministic fixes ----
        if "em_dashes" in failing_fixable:
            result = self._fix_em_dashes(content_md)
            if result["success"]:
                report["fixes_applied"].append(result["fix"])
                content_md = result["new_value"]
                db_updates["content_markdown"] = content_md
            else:
                report["fixes_failed"].append(result["error"])

        if "schema_markup" in failing_fixable:
            result = self._fix_schema_markup(content_md, article=article)
            if result["success"]:
                report["fixes_applied"].append(result["fix"])
                schema_markup = result["new_value"]
                db_updates["schema_markup"] = schema_markup
            else:
                report["fixes_skipped"].append("schema_markup")

        # ---- Tier 2: AI rewrites (single Claude call) ----
        tier2_needed = {}
        tier2_reasons = {}  # Track why each field needs fixing

        if "title_length" in failing_fixable:
            tier2_needed["seo_title"] = seo_title
            tier2_reasons["seo_title"] = "length"
        if "meta_description" in failing_fixable:
            tier2_needed["meta_description"] = meta_description
            tier2_reasons["meta_description"] = "length"
        if "keyword_placement" in failing_fixable:
            kw_check = failing_fixable["keyword_placement"]
            missing_from = kw_check.details.get("missing", []) if kw_check.details else []

            # Fix title for keyword placement if not already queued for length fix
            if "title/h1" in missing_from and "seo_title" not in tier2_needed:
                tier2_needed["seo_title"] = seo_title
                tier2_reasons["seo_title"] = "keyword"
            # If title already queued for length, it already asks for keyword inclusion

            # Fix meta_description for keyword placement if not already queued
            if "meta_description" in missing_from and "meta_description" not in tier2_needed:
                tier2_needed["meta_description"] = meta_description
                tier2_reasons["meta_description"] = "keyword"

            # Fix first paragraph for keyword placement
            if "first_paragraph" in missing_from:
                first_para = self._extract_first_paragraph(content_md)
                if first_para:
                    tier2_needed["first_paragraph"] = first_para
                    tier2_reasons["first_paragraph"] = "keyword"

        if tier2_needed:
            ai_result = self._fix_with_ai(
                tier2_needed, keyword, article_id, organization_id,
                reasons=tier2_reasons,
            )

            if ai_result.get("error"):
                # AI call failed entirely
                for check_name in tier2_needed:
                    mapped_check = {
                        "seo_title": "title_length",
                        "meta_description": "meta_description",
                        "first_paragraph": "keyword_placement",
                    }.get(check_name, check_name)
                    report["fixes_failed"].append({
                        "check": mapped_check,
                        "method": "ai_rewrite",
                        "reason": ai_result["error"],
                    })
            else:
                report["ai_cost_tokens"] = ai_result.get("total_tokens", 0)

                # Process each AI fix result independently
                if "seo_title" in ai_result.get("fixes", {}):
                    new_title = ai_result["fixes"]["seo_title"]
                    validation = self._validate_seo_title(new_title, keyword)
                    if validation["valid"]:
                        report["fixes_applied"].append({
                            "check": "title_length",
                            "method": "ai_rewrite",
                            "before": seo_title,
                            "after": new_title,
                            "model": AUTOFIX_MODEL,
                        })
                        db_updates["seo_title"] = new_title
                    else:
                        report["fixes_failed"].append({
                            "check": "title_length",
                            "method": "ai_rewrite",
                            "reason": validation["reason"],
                        })

                if "meta_description" in ai_result.get("fixes", {}):
                    new_meta = ai_result["fixes"]["meta_description"]
                    validation = self._validate_meta_description(new_meta)
                    if validation["valid"]:
                        report["fixes_applied"].append({
                            "check": "meta_description",
                            "method": "ai_rewrite",
                            "before": meta_description,
                            "after": new_meta,
                            "model": AUTOFIX_MODEL,
                        })
                        db_updates["meta_description"] = new_meta
                    else:
                        report["fixes_failed"].append({
                            "check": "meta_description",
                            "method": "ai_rewrite",
                            "reason": validation["reason"],
                        })

                if "first_paragraph" in ai_result.get("fixes", {}):
                    new_para = ai_result["fixes"]["first_paragraph"]
                    if keyword.lower() in new_para.lower():
                        old_para = tier2_needed["first_paragraph"]
                        content_md = content_md.replace(old_para, new_para, 1)
                        report["fixes_applied"].append({
                            "check": "keyword_placement",
                            "method": "ai_rewrite",
                            "before": old_para[:100] + "..." if len(old_para) > 100 else old_para,
                            "after": new_para[:100] + "..." if len(new_para) > 100 else new_para,
                            "model": AUTOFIX_MODEL,
                        })
                        db_updates["content_markdown"] = content_md
                    else:
                        report["fixes_failed"].append({
                            "check": "keyword_placement",
                            "method": "ai_rewrite",
                            "reason": f"AI rewrite did not include keyword '{keyword}'",
                        })

                # Validate keyword presence in title/meta fixes when reason was "keyword"
                if tier2_reasons.get("seo_title") == "keyword" and "seo_title" in ai_result.get("fixes", {}):
                    new_title = ai_result["fixes"]["seo_title"]
                    if keyword.lower() not in new_title.lower():
                        report["fixes_failed"].append({
                            "check": "keyword_placement",
                            "method": "ai_rewrite",
                            "reason": f"AI title rewrite did not include keyword '{keyword}'",
                        })
                if tier2_reasons.get("meta_description") == "keyword" and "meta_description" in ai_result.get("fixes", {}):
                    new_meta = ai_result["fixes"]["meta_description"]
                    if keyword.lower() not in new_meta.lower():
                        report["fixes_failed"].append({
                            "check": "keyword_placement",
                            "method": "ai_rewrite",
                            "reason": f"AI meta description rewrite did not include keyword '{keyword}'",
                        })

        # ---- Save fixes to DB ----
        if db_updates:
            try:
                self.supabase.table("seo_articles").update(
                    db_updates
                ).eq("id", article_id).execute()
                report["fixed"] = True
                report["total_fixes"] = len(report["fixes_applied"])
                logger.info(
                    f"Article {article_id}: {report['total_fixes']} fixes applied, "
                    f"{len(report['fixes_failed'])} failed"
                )
            except Exception as e:
                logger.error(f"Failed to save fixes for article {article_id}: {e}")
                report["fixes_failed"].append({
                    "check": "save_to_db",
                    "method": "db_update",
                    "reason": str(e),
                })

        return report

    # =========================================================================
    # TIER 1: DETERMINISTIC FIXES
    # =========================================================================

    def _fix_em_dashes(self, content: str) -> Dict[str, Any]:
        """Replace em/en dashes with hyphens."""
        em_count = content.count("\u2014")
        en_count = content.count("\u2013")
        total = em_count + en_count

        if total == 0:
            return {"success": False, "error": {
                "check": "em_dashes", "method": "deterministic",
                "reason": "No em/en dashes found",
            }}

        new_content = content.replace("\u2014", "-").replace("\u2013", "-")
        return {
            "success": True,
            "fix": {
                "check": "em_dashes",
                "method": "deterministic",
                "before": f"{total} em/en dashes",
                "after": f"Replaced with hyphens",
            },
            "new_value": new_content,
        }

    def _fix_schema_markup(self, content: str, article: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Generate schema markup from article content.

        Tries FAQPage schema first (from FAQ section), falls back to Article schema.
        """
        # Strip code fence wrapper
        clean = content.strip()
        clean = re.sub(r'^```\w*\n', '', clean)
        clean = re.sub(r'\n```\s*$', '', clean)

        # Find FAQ section
        faq_match = re.search(
            r'##\s+(?:FAQ|Frequently Asked Questions?|Common Questions)\s*\n([\s\S]*?)(?=\n## [^#]|\Z)',
            clean, re.IGNORECASE,
        )

        qa_pairs = []
        faq_text = faq_match.group(1) if faq_match else ""

        # Pattern 1: ### Question\nAnswer
        for m in re.finditer(r'###\s+(.+?)\n([\s\S]*?)(?=\n###|\Z)', faq_text):
            q = m.group(1).strip().strip('*')
            a = m.group(2).strip()
            if q and a:
                a = re.sub(r'\*\*(.+?)\*\*', r'\1', a)
                a = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', a)
                qa_pairs.append({"q": q, "a": a})

        # Pattern 2: **Question**\nAnswer
        if not qa_pairs:
            for m in re.finditer(r'\*\*(.+?)\*\*\s*\n([\s\S]*?)(?=\n\*\*|\Z)', faq_text):
                q = m.group(1).strip()
                a = m.group(2).strip()
                if q and a and '?' in q:
                    a = re.sub(r'\*\*(.+?)\*\*', r'\1', a)
                    a = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', a)
                    qa_pairs.append({"q": q, "a": a})

        if qa_pairs:
            schema = {
                "@context": "https://schema.org",
                "@type": "FAQPage",
                "mainEntity": [
                    {
                        "@type": "Question",
                        "name": pair["q"],
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": pair["a"],
                        },
                    }
                    for pair in qa_pairs
                ],
            }
            return {
                "success": True,
                "fix": {
                    "check": "schema_markup",
                    "method": "deterministic",
                    "before": "No schema markup",
                    "after": f"FAQPage schema with {len(qa_pairs)} Q&A pairs",
                },
                "new_value": schema,
            }

        # Fallback: generate Article schema
        seo_title = ""
        meta_desc = ""
        keyword = ""
        if article:
            seo_title = article.get("seo_title") or article.get("title") or ""
            meta_desc = article.get("meta_description") or ""
            keyword = article.get("keyword") or ""

        if not seo_title:
            return {"success": False, "error": {
                "check": "schema_markup", "method": "deterministic",
                "reason": "No FAQ section and no title for Article schema",
            }}

        schema = {
            "@context": "https://schema.org",
            "@type": "Article",
            "headline": seo_title,
            "description": meta_desc or seo_title,
        }
        if keyword:
            schema["keywords"] = keyword

        return {
            "success": True,
            "fix": {
                "check": "schema_markup",
                "method": "deterministic",
                "before": "No schema markup",
                "after": "Article schema generated",
            },
            "new_value": schema,
        }

    # =========================================================================
    # TIER 2: AI REWRITES
    # =========================================================================

    def _fix_with_ai(
        self,
        fields_to_fix: Dict[str, str],
        keyword: str,
        article_id: str,
        organization_id: str,
        reasons: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Batch all Tier 2 fixes into a single Claude call.

        Args:
            fields_to_fix: Dict of field_name -> current_value for fields needing fix
            keyword: Target SEO keyword
            article_id: For logging
            organization_id: For usage tracking
            reasons: Dict of field_name -> reason ("length" or "keyword") for context

        Returns:
            {"fixes": {"seo_title": "...", ...}, "total_tokens": N}
            or {"error": "..."} on failure
        """
        reasons = reasons or {}
        prompt_parts = [
            f"You are an SEO optimization expert. Fix the following fields for an article targeting the keyword \"{keyword}\".",
            f"CRITICAL: The keyword \"{keyword}\" MUST appear in every field you return. This is the #1 priority.",
            "",
        ]

        if "seo_title" in fields_to_fix:
            reason = reasons.get("seo_title", "length")
            if reason == "keyword":
                # Title length is fine, just missing the keyword
                prompt_parts.append(
                    f"SEO TITLE (current: \"{fields_to_fix['seo_title']}\"): "
                    f"The keyword \"{keyword}\" is missing from the title. "
                    f"Rewrite to naturally include the keyword while keeping a similar length (50-60 chars). "
                    f"The keyword should appear near the front."
                )
            else:
                prompt_parts.append(
                    f"SEO TITLE (current: \"{fields_to_fix['seo_title']}\"): "
                    f"Rewrite to be 50-60 characters. Include the keyword \"{keyword}\" near the front. "
                    f"Preserve the meaning. Make it compelling for search results."
                )
            prompt_parts.append("")

        if "meta_description" in fields_to_fix:
            current = fields_to_fix["meta_description"]
            reason = reasons.get("meta_description", "length")
            if current:
                if reason == "keyword":
                    prompt_parts.append(
                        f"META DESCRIPTION (current: \"{current}\"): "
                        f"The keyword \"{keyword}\" is missing. "
                        f"Rewrite to naturally include the keyword while keeping 150-160 characters. "
                        f"Use action-oriented, natural language."
                    )
                else:
                    prompt_parts.append(
                        f"META DESCRIPTION (current: \"{current}\"): "
                        f"Rewrite to be 150-160 characters. Include the keyword \"{keyword}\". "
                        f"Use action-oriented, natural language."
                    )
            else:
                prompt_parts.append(
                    f"META DESCRIPTION (missing): "
                    f"Write a meta description of 150-160 characters for this article about \"{keyword}\". "
                    f"Include the keyword. Use action-oriented, natural language."
                )
            prompt_parts.append("")

        if "first_paragraph" in fields_to_fix:
            prompt_parts.append(
                f"FIRST PARAGRAPH (current: \"{fields_to_fix['first_paragraph']}\"): "
                f"Rewrite to naturally include the keyword \"{keyword}\" while preserving the meaning and tone."
            )
            prompt_parts.append("")

        prompt_parts.append(
            "Return ONLY valid JSON with the fixed fields. Only include fields you were asked to fix. Example format:"
        )
        prompt_parts.append('{"seo_title": "...", "meta_description": "...", "first_paragraph": "..."}')

        prompt = "\n".join(prompt_parts)

        # Try with one retry
        for attempt in range(2):
            try:
                start = time.time()
                response = self.anthropic.messages.create(
                    model=AUTOFIX_MODEL,
                    max_tokens=1024,
                    messages=[{"role": "user", "content": prompt}],
                )
                duration_ms = int((time.time() - start) * 1000)

                # Track usage
                total_tokens = (response.usage.input_tokens or 0) + (response.usage.output_tokens or 0)
                self._track_usage(
                    organization_id,
                    response.usage.input_tokens or 0,
                    response.usage.output_tokens or 0,
                    duration_ms,
                )

                # Parse response
                text = response.content[0].text.strip()
                # Strip markdown code fences if present
                text = re.sub(r'^```(?:json)?\s*\n?', '', text)
                text = re.sub(r'\n?```\s*$', '', text)

                fixes = json.loads(text)
                return {"fixes": fixes, "total_tokens": total_tokens}

            except json.JSONDecodeError as e:
                if attempt == 0:
                    logger.warning(f"AI fix JSON parse error (attempt 1), retrying: {e}")
                    time.sleep(2)
                    continue
                logger.error(f"AI fix JSON parse error (attempt 2): {e}")
                return {"error": f"AI returned invalid JSON: {e}"}
            except Exception as e:
                if attempt == 0:
                    logger.warning(f"AI fix error (attempt 1), retrying: {e}")
                    time.sleep(2)
                    continue
                logger.error(f"AI fix error (attempt 2): {e}")
                return {"error": f"Claude API error: {e}"}

        return {"error": "AI fix failed after 2 attempts"}

    # =========================================================================
    # VALIDATION
    # =========================================================================

    def _validate_seo_title(self, title: str, keyword: str) -> Dict[str, Any]:
        """Validate AI-generated SEO title."""
        if not title or not title.strip():
            return {"valid": False, "reason": "Empty title returned"}
        length = len(title.strip())
        if length < 30:
            return {"valid": False, "reason": f"Title too short: {length} chars (min 30)"}
        if length > 70:
            return {"valid": False, "reason": f"Title too long: {length} chars (max 70)"}
        return {"valid": True}

    def _validate_meta_description(self, description: str) -> Dict[str, Any]:
        """Validate AI-generated meta description."""
        if not description or not description.strip():
            return {"valid": False, "reason": "Empty description returned"}
        length = len(description.strip())
        if length < 120:
            return {"valid": False, "reason": f"Description too short: {length} chars (min 120)"}
        if length > 200:
            return {"valid": False, "reason": f"Description too long: {length} chars (max 200)"}
        return {"valid": True}

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _get_article(self, article_id: str) -> Optional[Dict[str, Any]]:
        """Load article from DB."""
        result = (
            self.supabase.table("seo_articles")
            .select("*")
            .eq("id", article_id)
            .execute()
        )
        return result.data[0] if result.data else None

    def _extract_first_paragraph(self, content: str) -> Optional[str]:
        """Extract first body paragraph from markdown content.

        First paragraph = text from start (after any frontmatter) to first
        double newline or heading, whichever comes first.
        """
        # Strip YAML frontmatter
        text = re.sub(r'^---\n[\s\S]*?\n---\n?', '', content.strip())

        # Split into blocks
        paragraphs = re.split(r'\n\n+', text.strip())
        for p in paragraphs:
            stripped = p.strip()
            # Skip headings, images (markdown and HTML), code blocks, empty
            if stripped and not stripped.startswith('#') and not stripped.startswith('![') and not stripped.startswith('```') and not stripped.startswith('<img') and not stripped.startswith('<figure'):
                return stripped
        return None

    def _track_usage(
        self,
        organization_id: str,
        input_tokens: int,
        output_tokens: int,
        duration_ms: int,
    ):
        """Track Claude API usage."""
        if not self._usage_tracker:
            return
        try:
            from viraltracker.services.usage_tracker import UsageRecord
            record = UsageRecord(
                provider="anthropic",
                model=AUTOFIX_MODEL,
                tool_name="seo_pipeline",
                operation="content_auto_fix",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                duration_ms=duration_ms,
            )
            self._usage_tracker.track(
                user_id=None,
                organization_id=organization_id,
                record=record,
            )
        except Exception as e:
            logger.warning(f"Failed to track usage: {e}")
