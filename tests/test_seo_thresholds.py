"""B7: single source of truth for SEO length thresholds."""
from viraltracker.services.seo_pipeline.seo_thresholds import (
    DEFAULT_SEO_THRESHOLDS, resolve_seo_thresholds,
)
from viraltracker.services.seo_pipeline.services.qa_validation_service import QAValidationService
from viraltracker.services.seo_pipeline.services.pre_publish_checklist_service import PrePublishChecklistService


class TestResolveThresholds:
    def test_defaults_when_no_policy(self):
        assert resolve_seo_thresholds(None) == DEFAULT_SEO_THRESHOLDS
        assert resolve_seo_thresholds({}) == DEFAULT_SEO_THRESHOLDS

    def test_brand_override_merges(self):
        t = resolve_seo_thresholds({"seo_thresholds": {"title_ideal_max": 65}})
        assert t["title_ideal_max"] == 65
        assert t["title_ideal_min"] == 50  # untouched key keeps default

    def test_malformed_override_ignored(self):
        t = resolve_seo_thresholds({"seo_thresholds": {"title_ideal_min": "oops", "bogus": 1, "title_ideal_max": True}})
        assert t == DEFAULT_SEO_THRESHOLDS  # non-numeric / bool / unknown all ignored


class TestQAChecklistConsistency:
    """The whole point of B7: QA and the checklist agree on the SAME range."""

    def _qa(self, **t):
        return QAValidationService(thresholds=resolve_seo_thresholds({"seo_thresholds": t}) if t else None)

    def _checklist(self, **t):
        return PrePublishChecklistService(thresholds=resolve_seo_thresholds({"seo_thresholds": t}) if t else None)

    def test_title_45_chars_consistent(self):
        # 45-char title: was QA-warn but checklist-pass (the B7 bug). Now both
        # treat it the same (outside 50-60 ideal -> not passed in either).
        title = "A" * 45
        qa = self._qa()._check_title_length(title)
        cl = self._checklist()._check_seo_title({"seo_title": title})
        assert qa.passed is False and cl["passed"] is False

    def test_title_55_chars_both_pass(self):
        title = "A" * 55
        assert self._qa()._check_title_length(title).passed is True
        assert self._checklist()._check_seo_title({"seo_title": title})["passed"] is True

    def test_brand_override_flows_to_both(self):
        # Brand widens title ideal to 40-80; a 45-char title now passes BOTH.
        title = "A" * 45
        assert self._qa(title_ideal_min=40, title_ideal_max=80)._check_title_length(title).passed is True
        assert self._checklist(title_ideal_min=40, title_ideal_max=80)._check_seo_title({"seo_title": title})["passed"] is True

    def test_title_at_hard_cap_is_error(self):
        assert self._qa()._check_title_length("A" * 70).severity == "error"   # >= hard_max
        assert self._qa()._check_title_length("A" * 69).severity == "warning"  # below hard_max
