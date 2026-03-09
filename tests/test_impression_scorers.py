"""Tests for ImpressionRankScorer, ImpressionVelocityScorer, CreativeVariantScorer."""

import pytest
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from viraltracker.services.template_scoring_service import (
    ImpressionRankScorer,
    ImpressionVelocityScorer,
    CreativeVariantScorer,
    SelectionContext,
)


@pytest.fixture
def context():
    return SelectionContext(product_id=uuid4(), brand_id=uuid4())


class TestImpressionRankScorer:
    scorer = ImpressionRankScorer()

    def test_missing_position_returns_neutral(self, context):
        assert self.scorer.score({}, context) == 0.5

    def test_position_1_scores_highest(self, context):
        score = self.scorer.score({"best_scrape_position": 1, "scrape_total": 87}, context)
        assert score == 1.0

    def test_position_50_scores_low(self, context):
        score = self.scorer.score({"best_scrape_position": 50, "scrape_total": 87}, context)
        assert score == pytest.approx(0.216, abs=0.01)

    def test_position_100_floors_at_02(self, context):
        score = self.scorer.score({"best_scrape_position": 100, "scrape_total": 200}, context)
        assert score == 0.2

    def test_small_page_compressed(self, context):
        """Risk 10: Small pages (total <= 10) compress to [0.4, 0.6]."""
        score_top = self.scorer.score({"best_scrape_position": 1, "scrape_total": 5}, context)
        score_bottom = self.scorer.score({"best_scrape_position": 5, "scrape_total": 5}, context)
        assert 0.39 < score_top <= 0.61
        assert 0.39 < score_bottom <= 0.61
        assert score_top > score_bottom

    def test_no_total_uses_default(self, context):
        score = self.scorer.score({"best_scrape_position": 1}, context)
        assert score == 1.0


class TestImpressionVelocityScorer:
    scorer = ImpressionVelocityScorer()

    def test_missing_data_returns_neutral(self, context):
        assert self.scorer.score({}, context) == 0.5
        assert self.scorer.score({"latest_scrape_position": 1}, context) == 0.5
        assert self.scorer.score({"start_date": "2026-01-01"}, context) == 0.5

    def test_hot_new_ad_scores_high(self, context):
        """7-day-old ad at position 2 of 87 should score ~0.90."""
        start = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        score = self.scorer.score({
            "latest_scrape_position": 2,
            "scrape_total": 87,
            "start_date": start,
        }, context)
        assert score > 0.85

    def test_steady_workhorse_scores_medium(self, context):
        """180-day-old ad at position 1 should score ~0.41."""
        start = (datetime.now(timezone.utc) - timedelta(days=180)).isoformat()
        score = self.scorer.score({
            "latest_scrape_position": 1,
            "scrape_total": 87,
            "start_date": start,
        }, context)
        assert 0.35 < score < 0.50

    def test_hot_beats_steady(self, context):
        """7-day-old #2 should score higher than 180-day-old #1."""
        hot_start = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        steady_start = (datetime.now(timezone.utc) - timedelta(days=180)).isoformat()

        hot_score = self.scorer.score({
            "latest_scrape_position": 2,
            "scrape_total": 87,
            "start_date": hot_start,
        }, context)
        steady_score = self.scorer.score({
            "latest_scrape_position": 1,
            "scrape_total": 87,
            "start_date": steady_start,
        }, context)
        assert hot_score > steady_score

    def test_mediocre_position_low_score(self, context):
        """7-day-old ad at position 40 should score ~0.47."""
        start = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        score = self.scorer.score({
            "latest_scrape_position": 40,
            "scrape_total": 87,
            "start_date": start,
        }, context)
        assert 0.40 < score < 0.55

    def test_invalid_start_date_returns_neutral(self, context):
        score = self.scorer.score({
            "latest_scrape_position": 1,
            "scrape_total": 87,
            "start_date": "not-a-date",
        }, context)
        assert score == 0.5


class TestCreativeVariantScorer:
    scorer = CreativeVariantScorer()

    def test_no_variants_low_score(self, context):
        assert self.scorer.score({}, context) == 0.3
        assert self.scorer.score({"collation_count": 1}, context) == 0.3

    def test_few_variants_medium(self, context):
        assert self.scorer.score({"collation_count": 2}, context) == 0.6
        assert self.scorer.score({"collation_count": 3}, context) == 0.6

    def test_many_variants_high(self, context):
        assert self.scorer.score({"collation_count": 5}, context) == 0.8
        assert self.scorer.score({"collation_count": 7}, context) == 0.8

    def test_lots_of_variants_max(self, context):
        assert self.scorer.score({"collation_count": 8}, context) == 1.0
        assert self.scorer.score({"collation_count": 20}, context) == 1.0
