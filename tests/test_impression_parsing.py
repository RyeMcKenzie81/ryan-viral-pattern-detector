"""Tests for parse_impression_data() and _parse_impression_text() from ad_scraping_service."""

import pytest
from viraltracker.services.ad_scraping_service import parse_impression_data, _parse_impression_text


class TestParseImpressionText:
    """Tests for the range text parser."""

    def test_simple_range_k(self):
        assert _parse_impression_text("1K-5K") == (1000, 5000)

    def test_simple_range_m(self):
        assert _parse_impression_text("1M-5M") == (1_000_000, 5_000_000)

    def test_simple_range_no_suffix(self):
        assert _parse_impression_text("100-500") == (100, 500)

    def test_mixed_suffixes(self):
        assert _parse_impression_text("500K-1M") == (500_000, 1_000_000)

    def test_single_value(self):
        assert _parse_impression_text("5K") == (5000, 5000)

    def test_decimal(self):
        assert _parse_impression_text("1.5K-3K") == (1500, 3000)

    def test_less_than(self):
        lower, upper = _parse_impression_text("<1K")
        assert lower == 1000
        assert upper == 1000

    def test_greater_than(self):
        lower, upper = _parse_impression_text(">1M")
        assert lower == 1_000_000
        assert upper == 1_000_000

    def test_unparseable(self):
        assert _parse_impression_text("unknown") == (None, None)

    def test_empty_string(self):
        assert _parse_impression_text("") == (None, None)

    def test_with_spaces(self):
        assert _parse_impression_text("10K - 50K") == (10_000, 50_000)

    def test_en_dash(self):
        assert _parse_impression_text("1K\u201350K") == (1000, 50_000)

    def test_case_insensitive(self):
        assert _parse_impression_text("1k-5k") == (1000, 5000)


class TestParseImpressionData:
    """Tests for the main impression data parser."""

    def test_none(self):
        assert parse_impression_data(None) == (None, None, None)

    def test_integer(self):
        assert parse_impression_data(12345) == (12345, 12345, "12345")

    def test_float(self):
        assert parse_impression_data(12345.0) == (12345, 12345, "12345")

    def test_integer_string(self):
        assert parse_impression_data("99999") == (99999, 99999, "99999")

    def test_dict_with_text(self):
        raw = {"impressions_text": "1K-5K", "impressions_index": 3}
        lower, upper, text = parse_impression_data(raw)
        assert lower == 1000
        assert upper == 5000
        assert text == "1K-5K"

    def test_dict_with_null_text(self):
        raw = {"impressions_text": None, "impressions_index": -1}
        assert parse_impression_data(raw) == (None, None, None)

    def test_dict_missing_text_key(self):
        raw = {"impressions_index": -1}
        assert parse_impression_data(raw) == (None, None, None)

    def test_json_string_dict(self):
        import json
        raw = json.dumps({"impressions_text": "10K-50K", "impressions_index": 5})
        lower, upper, text = parse_impression_data(raw)
        assert lower == 10_000
        assert upper == 50_000
        assert text == "10K-50K"

    def test_json_string_dict_null_text(self):
        import json
        raw = json.dumps({"impressions_text": None, "impressions_index": -1})
        assert parse_impression_data(raw) == (None, None, None)

    def test_non_json_string(self):
        assert parse_impression_data("not a number") == (None, None, None)

    def test_empty_dict(self):
        assert parse_impression_data({}) == (None, None, None)

    def test_unexpected_type(self):
        assert parse_impression_data([1, 2, 3]) == (None, None, None)
