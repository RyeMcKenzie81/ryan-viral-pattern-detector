"""
Unit tests for DataForSEOService.

Covers:
- _normalize_competition: string/float/int/None normalization
- _days_ago_iso: ISO timestamp generation
- enrich_keywords_google_ads: Google Ads enrichment + clickstream fallback
- _clickstream_fallback: in-place volume fill from clickstream data
- get_keyword_suggestions: keyword suggestions with nested response structure
- enrich_with_cache: cache-first enrichment with stale detection
- enrich_keywords_bulk: combined volume + KD enrichment

Run with: pytest tests/test_dataforseo_service.py -v
"""

import logging
from datetime import datetime, timedelta
from unittest.mock import MagicMock, call, patch

import pytest

from viraltracker.services.seo_pipeline.services.dataforseo_service import (
    DataForSEOService,
    _days_ago_iso,
    _normalize_competition,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def service():
    """DataForSEOService with mocked Supabase and credentials set."""
    mock_supabase = MagicMock()
    svc = DataForSEOService(supabase_client=mock_supabase)
    svc._login = "test_login"
    svc._password = "test_password"
    return svc


@pytest.fixture
def unavailable_service():
    """DataForSEOService with no credentials (not available)."""
    svc = DataForSEOService(supabase_client=MagicMock())
    svc._login = ""
    svc._password = ""
    return svc


# ---------------------------------------------------------------------------
# _normalize_competition
# ---------------------------------------------------------------------------


def test_normalize_competition_none():
    assert _normalize_competition(None) is None


def test_normalize_competition_float():
    assert _normalize_competition(0.5) == 0.5


def test_normalize_competition_int():
    result = _normalize_competition(1)
    assert result == 1.0
    assert isinstance(result, float)


def test_normalize_competition_low():
    assert _normalize_competition("LOW") == 0.33


def test_normalize_competition_medium():
    assert _normalize_competition("MEDIUM") == 0.66


def test_normalize_competition_high():
    assert _normalize_competition("HIGH") == 1.0


def test_normalize_competition_lowercase():
    assert _normalize_competition("medium") == 0.66


def test_normalize_competition_unknown_string():
    assert _normalize_competition("UNKNOWN") is None


def test_normalize_competition_unsupported_type():
    assert _normalize_competition([1, 2]) is None


# ---------------------------------------------------------------------------
# _days_ago_iso
# ---------------------------------------------------------------------------


def test_days_ago_iso_returns_iso_string():
    result = _days_ago_iso(7)
    # Should parse as a valid datetime
    parsed = datetime.fromisoformat(result)
    # Should be roughly 7 days ago (within 10 seconds tolerance)
    expected = datetime.utcnow() - timedelta(days=7)
    assert abs((parsed - expected).total_seconds()) < 10


def test_days_ago_iso_zero_days():
    result = _days_ago_iso(0)
    parsed = datetime.fromisoformat(result)
    expected = datetime.utcnow()
    assert abs((parsed - expected).total_seconds()) < 10


# ---------------------------------------------------------------------------
# enrich_keywords_google_ads
# ---------------------------------------------------------------------------


@patch.object(DataForSEOService, "_post")
def test_enrich_google_ads_basic(mock_post, service):
    """Google Ads enrichment returns volume/CPC/competition for keywords with data."""
    mock_post.return_value = {
        "status_code": 20000,
        "tasks": [{
            "result": [
                {
                    "keyword": "best shoes",
                    "search_volume": 14800,
                    "cpc": 1.25,
                    "competition": "HIGH",
                },
                {
                    "keyword": "running shoes",
                    "search_volume": 33100,
                    "cpc": 0.95,
                    "competition": "MEDIUM",
                },
            ]
        }],
    }

    results = service.enrich_keywords_google_ads(["Best Shoes", "Running Shoes"])

    assert len(results) == 2
    by_kw = {r["keyword"]: r for r in results}
    assert by_kw["best shoes"]["search_volume"] == 14800
    assert by_kw["best shoes"]["cpc"] == 1.25
    assert by_kw["best shoes"]["competition"] == 1.0  # HIGH -> 1.0
    assert by_kw["best shoes"]["volume_source"] == "google_ads"
    assert by_kw["running shoes"]["competition"] == 0.66  # MEDIUM -> 0.66


@patch.object(DataForSEOService, "_clickstream_fallback")
@patch.object(DataForSEOService, "_post")
def test_enrich_google_ads_triggers_clickstream_fallback(mock_post, mock_cs, service):
    """Clickstream fallback is triggered for keywords with null volume."""
    mock_post.return_value = {
        "status_code": 20000,
        "tasks": [{
            "result": [
                {"keyword": "best shoes", "search_volume": 14800, "cpc": 1.0, "competition": 0.5},
                {"keyword": "kids shoes", "search_volume": None, "cpc": None, "competition": None},
            ]
        }],
    }

    service.enrich_keywords_google_ads(["best shoes", "kids shoes"])

    # Clickstream should be called with only the null-volume keyword
    mock_cs.assert_called_once()
    call_args = mock_cs.call_args
    assert call_args[0][0] == ["kids shoes"]


@patch.object(DataForSEOService, "_post")
def test_enrich_google_ads_with_clickstream_filling(mock_post, service):
    """Clickstream fallback fills null volumes end-to-end."""
    # First call: Google Ads (kids shoes has null volume)
    # Second call: clickstream (fills kids shoes)
    mock_post.side_effect = [
        {
            "status_code": 20000,
            "tasks": [{
                "result": [
                    {"keyword": "best shoes", "search_volume": 14800, "cpc": 1.0, "competition": "LOW"},
                    {"keyword": "kids shoes", "search_volume": None, "cpc": None, "competition": None},
                ]
            }],
        },
        {
            "status_code": 20000,
            "tasks": [{
                "result": [{
                    "items": [
                        {"keyword": "kids shoes", "search_volume": 8200},
                    ]
                }]
            }],
        },
    ]

    results = service.enrich_keywords_google_ads(["best shoes", "kids shoes"])
    by_kw = {r["keyword"]: r for r in results}

    assert by_kw["best shoes"]["search_volume"] == 14800
    assert by_kw["best shoes"]["volume_source"] == "google_ads"
    assert by_kw["kids shoes"]["search_volume"] == 8200
    assert by_kw["kids shoes"]["volume_source"] == "clickstream"


def test_enrich_google_ads_empty_input(service):
    """Empty input returns empty list without API call."""
    assert service.enrich_keywords_google_ads([]) == []


def test_enrich_google_ads_not_available(unavailable_service):
    """Returns empty list when credentials are missing."""
    assert unavailable_service.enrich_keywords_google_ads(["test"]) == []


# ---------------------------------------------------------------------------
# _clickstream_fallback
# ---------------------------------------------------------------------------


@patch.object(DataForSEOService, "_post")
def test_clickstream_fallback_fills_null_volume(mock_post, service):
    """Clickstream fills in search_volume for keywords with null volume."""
    mock_post.return_value = {
        "status_code": 20000,
        "tasks": [{
            "result": [{
                "items": [
                    {"keyword": "kids shoes", "search_volume": 8200},
                    {"keyword": "baby clothes", "search_volume": 4500},
                ]
            }]
        }],
    }

    results = {
        "kids shoes": {"keyword": "kids shoes"},
        "baby clothes": {"keyword": "baby clothes"},
    }
    service._clickstream_fallback(["kids shoes", "baby clothes"], results)

    assert results["kids shoes"]["search_volume"] == 8200
    assert results["kids shoes"]["volume_source"] == "clickstream"
    assert results["baby clothes"]["search_volume"] == 4500


@patch.object(DataForSEOService, "_post")
def test_clickstream_fallback_skips_zero_volume(mock_post, service):
    """Volume of 0 is NOT filled by clickstream (only vol > 0)."""
    mock_post.return_value = {
        "status_code": 20000,
        "tasks": [{
            "result": [{
                "items": [
                    {"keyword": "rare keyword", "search_volume": 0},
                ]
            }]
        }],
    }

    results = {"rare keyword": {"keyword": "rare keyword"}}
    service._clickstream_fallback(["rare keyword"], results)

    assert "search_volume" not in results["rare keyword"]


@patch.object(DataForSEOService, "_post")
def test_clickstream_fallback_api_failure_no_crash(mock_post, service, caplog):
    """API failure in clickstream logs warning but doesn't crash."""
    mock_post.side_effect = RuntimeError("API timeout")

    results = {"kids shoes": {"keyword": "kids shoes"}}
    with caplog.at_level(logging.WARNING):
        service._clickstream_fallback(["kids shoes"], results)

    assert "Clickstream fallback failed" in caplog.text
    # Original results unchanged
    assert "search_volume" not in results["kids shoes"]


# ---------------------------------------------------------------------------
# get_keyword_suggestions
# ---------------------------------------------------------------------------


@patch.object(DataForSEOService, "_post")
def test_get_keyword_suggestions_basic(mock_post, service):
    """Keyword suggestions are parsed from the correct nested structure."""
    mock_post.return_value = {
        "status_code": 20000,
        "tasks": [{
            "result": [{
                "items": [
                    {
                        "keyword": "organic dog food",
                        "keyword_info": {
                            "search_volume": 22000,
                            "cpc": 2.10,
                            "competition": 0.45,
                        },
                        "keyword_properties": {
                            "keyword_difficulty": 62,
                        },
                        "search_intent_info": {
                            "main_intent": "commercial",
                        },
                    },
                    {
                        "keyword": "best organic dog food",
                        "keyword_info": {
                            "search_volume": 8100,
                            "cpc": 1.80,
                            "competition": "MEDIUM",
                        },
                        "keyword_properties": {
                            "keyword_difficulty": 55,
                        },
                        "search_intent_info": {
                            "main_intent": "informational",
                        },
                    },
                ]
            }]
        }],
    }

    results = service.get_keyword_suggestions("dog food", limit=10)

    assert len(results) == 2
    # Verify keyword is read from item level, not keyword_info
    assert results[0]["keyword"] == "organic dog food"
    assert results[0]["search_volume"] == 22000
    assert results[0]["cpc"] == 2.10
    assert results[0]["competition"] == 0.45  # float passed through
    assert results[0]["keyword_difficulty"] == 62
    assert results[0]["search_intent"] == "commercial"

    # Verify string competition is normalized
    assert results[1]["competition"] == 0.66  # MEDIUM -> 0.66


@patch.object(DataForSEOService, "_clickstream_fallback")
@patch.object(DataForSEOService, "_post")
def test_get_keyword_suggestions_clickstream_fallback(mock_post, mock_cs, service):
    """Clickstream fallback is triggered for suggestions with null volume."""
    mock_post.return_value = {
        "status_code": 20000,
        "tasks": [{
            "result": [{
                "items": [
                    {
                        "keyword": "organic dog food",
                        "keyword_info": {"search_volume": 22000, "cpc": 2.0, "competition": 0.5},
                        "keyword_properties": {"keyword_difficulty": 60},
                        "search_intent_info": {"main_intent": "commercial"},
                    },
                    {
                        "keyword": "kids dog food",
                        "keyword_info": {"search_volume": None, "cpc": None, "competition": None},
                        "keyword_properties": {"keyword_difficulty": 30},
                        "search_intent_info": {"main_intent": "informational"},
                    },
                ]
            }]
        }],
    }

    service.get_keyword_suggestions("dog food")

    # Clickstream should be called for the null-volume keyword
    mock_cs.assert_called_once()
    call_args = mock_cs.call_args
    assert "kids dog food" in call_args[0][0]


def test_get_keyword_suggestions_not_available(unavailable_service):
    """Returns empty list when credentials missing."""
    assert unavailable_service.get_keyword_suggestions("test") == []


# ---------------------------------------------------------------------------
# enrich_with_cache
# ---------------------------------------------------------------------------


@patch.object(DataForSEOService, "_post")
def test_enrich_with_cache_returns_cached_data(mock_post, service):
    """Cached keywords are returned without API calls."""
    # Set up cache to return fresh data for "best shoes"
    mock_table = MagicMock()
    service._supabase.table.return_value = mock_table
    mock_select = MagicMock()
    mock_table.select.return_value = mock_select
    mock_in = MagicMock()
    mock_select.in_.return_value = mock_in
    mock_eq = MagicMock()
    mock_in.eq.return_value = mock_eq
    mock_gte = MagicMock()
    mock_eq.gte.return_value = mock_gte
    mock_gte.execute.return_value = MagicMock(data=[
        {
            "keyword": "best shoes",
            "search_volume": 14800,
            "keyword_difficulty": 65,
            "cpc": 1.25,
            "competition": 0.8,
            "search_intent": "commercial",
            "refreshed_at": datetime.utcnow().isoformat(),
        }
    ])

    results = service.enrich_with_cache(["best shoes"])

    assert len(results) == 1
    assert results[0]["keyword"] == "best shoes"
    assert results[0]["search_volume"] == 14800
    # No API calls should have been made
    mock_post.assert_not_called()


@patch.object(DataForSEOService, "enrich_keywords_google_ads")
@patch.object(DataForSEOService, "_post")
def test_enrich_with_cache_fetches_stale_keywords(mock_post, mock_google_ads, service):
    """Stale/missing keywords are fetched from API."""
    # Cache returns data for "best shoes" but NOT "running shoes"
    mock_table = MagicMock()
    service._supabase.table.return_value = mock_table
    mock_select = MagicMock()
    mock_table.select.return_value = mock_select
    mock_in = MagicMock()
    mock_select.in_.return_value = mock_in
    mock_eq = MagicMock()
    mock_in.eq.return_value = mock_eq
    mock_gte = MagicMock()
    mock_eq.gte.return_value = mock_gte
    mock_gte.execute.return_value = MagicMock(data=[
        {
            "keyword": "best shoes",
            "search_volume": 14800,
            "keyword_difficulty": 65,
            "cpc": 1.25,
            "competition": 0.8,
            "search_intent": "commercial",
            "refreshed_at": datetime.utcnow().isoformat(),
        }
    ])

    # Google Ads returns data for "running shoes"
    mock_google_ads.return_value = [
        {"keyword": "running shoes", "search_volume": 33100, "cpc": 0.95, "competition": 0.66},
    ]

    # KD endpoint returns data for "running shoes"
    mock_post.return_value = {
        "status_code": 20000,
        "tasks": [{
            "result": [{
                "items": [
                    {"keyword": "running shoes", "keyword_difficulty": 72},
                ]
            }]
        }],
    }

    results = service.enrich_with_cache(["best shoes", "running shoes"])

    assert len(results) == 2
    by_kw = {r["keyword"]: r for r in results}

    # Cached result
    assert by_kw["best shoes"]["search_volume"] == 14800

    # Freshly fetched result
    assert by_kw["running shoes"]["search_volume"] == 33100
    assert by_kw["running shoes"]["keyword_difficulty"] == 72

    # enrich_keywords_google_ads only called with the stale keyword
    mock_google_ads.assert_called_once_with(["running shoes"], 2840, "en")


@patch.object(DataForSEOService, "enrich_keywords_google_ads")
@patch.object(DataForSEOService, "_post")
def test_enrich_with_cache_upserts_fresh_results(mock_post, mock_google_ads, service):
    """Fresh API results are upserted to the cache table."""
    # Cache returns nothing
    mock_table = MagicMock()
    service._supabase.table.return_value = mock_table
    mock_select = MagicMock()
    mock_table.select.return_value = mock_select
    mock_in = MagicMock()
    mock_select.in_.return_value = mock_in
    mock_eq = MagicMock()
    mock_in.eq.return_value = mock_eq
    mock_gte = MagicMock()
    mock_eq.gte.return_value = mock_gte
    mock_gte.execute.return_value = MagicMock(data=[])

    mock_google_ads.return_value = [
        {"keyword": "new shoes", "search_volume": 5000, "cpc": 0.80, "competition": 0.33},
    ]
    mock_post.return_value = {
        "status_code": 20000,
        "tasks": [{"result": [{"items": [{"keyword": "new shoes", "keyword_difficulty": 40}]}]}],
    }

    # Track upsert calls
    mock_upsert = MagicMock()
    mock_upsert.execute.return_value = MagicMock()
    mock_table.upsert.return_value = mock_upsert

    service.enrich_with_cache(["new shoes"])

    # Verify upsert was called
    mock_table.upsert.assert_called_once()
    upserted_rows = mock_table.upsert.call_args[0][0]
    assert len(upserted_rows) == 1
    assert upserted_rows[0]["keyword"] == "new shoes"
    assert upserted_rows[0]["search_volume"] == 5000
    assert upserted_rows[0]["keyword_difficulty"] == 40


@patch.object(DataForSEOService, "enrich_keywords_google_ads")
@patch.object(DataForSEOService, "_post")
def test_enrich_with_cache_force_refresh(mock_post, mock_google_ads, service):
    """force_refresh=True bypasses cache and fetches everything from API."""
    mock_table = MagicMock()
    service._supabase.table.return_value = mock_table
    mock_upsert = MagicMock()
    mock_upsert.execute.return_value = MagicMock()
    mock_table.upsert.return_value = mock_upsert

    mock_google_ads.return_value = [
        {"keyword": "best shoes", "search_volume": 15000, "cpc": 1.30, "competition": 0.9},
    ]
    mock_post.return_value = {
        "status_code": 20000,
        "tasks": [{"result": [{"items": [{"keyword": "best shoes", "keyword_difficulty": 70}]}]}],
    }

    results = service.enrich_with_cache(["best shoes"], force_refresh=True)

    assert len(results) == 1
    assert results[0]["search_volume"] == 15000
    # Cache select should NOT have been called
    mock_table.select.assert_not_called()


def test_enrich_with_cache_empty_input(service):
    """Empty input returns empty list."""
    assert service.enrich_with_cache([]) == []


# ---------------------------------------------------------------------------
# enrich_keywords_bulk
# ---------------------------------------------------------------------------


@patch.object(DataForSEOService, "_post")
def test_enrich_keywords_bulk_basic(mock_post, service):
    """Bulk enrichment merges volume (Google Ads) and KD."""
    mock_post.side_effect = [
        # First call: Google Ads volume
        {
            "status_code": 20000,
            "tasks": [{
                "result": [
                    {"keyword": "best shoes", "search_volume": 14800, "cpc": 1.25, "competition": "HIGH"},
                    {"keyword": "running shoes", "search_volume": 33100, "cpc": 0.95, "competition": 0.5},
                ]
            }],
        },
        # Second call: clickstream (no null-vol keywords in this test, won't be called)
        # Third call: keyword difficulty — but first let's handle the clickstream branch
        # Actually, since neither keyword has null volume, clickstream won't be called.
        # Second call: keyword difficulty
        {
            "status_code": 20000,
            "tasks": [{
                "result": [{
                    "items": [
                        {"keyword": "best shoes", "keyword_difficulty": 65},
                        {"keyword": "running shoes", "keyword_difficulty": 72},
                    ]
                }]
            }],
        },
    ]

    results = service.enrich_keywords_bulk(["Best Shoes", "Running Shoes"])

    assert len(results) == 2
    by_kw = {r["keyword"]: r for r in results}
    assert by_kw["best shoes"]["search_volume"] == 14800
    assert by_kw["best shoes"]["keyword_difficulty"] == 65
    assert by_kw["best shoes"]["competition"] == 1.0  # HIGH
    assert by_kw["running shoes"]["search_volume"] == 33100
    assert by_kw["running shoes"]["keyword_difficulty"] == 72


@patch.object(DataForSEOService, "_post")
def test_enrich_keywords_bulk_with_clickstream_fallback(mock_post, service):
    """Bulk enrichment triggers clickstream fallback for null-volume keywords."""
    mock_post.side_effect = [
        # Google Ads: "kids shoes" has null volume
        {
            "status_code": 20000,
            "tasks": [{
                "result": [
                    {"keyword": "best shoes", "search_volume": 14800, "cpc": 1.25, "competition": "HIGH"},
                    {"keyword": "kids shoes", "search_volume": None, "cpc": None, "competition": None},
                ]
            }],
        },
        # Clickstream fallback for "kids shoes"
        {
            "status_code": 20000,
            "tasks": [{
                "result": [{
                    "items": [
                        {"keyword": "kids shoes", "search_volume": 6500},
                    ]
                }]
            }],
        },
        # Keyword difficulty
        {
            "status_code": 20000,
            "tasks": [{
                "result": [{
                    "items": [
                        {"keyword": "best shoes", "keyword_difficulty": 65},
                        {"keyword": "kids shoes", "keyword_difficulty": 35},
                    ]
                }]
            }],
        },
    ]

    results = service.enrich_keywords_bulk(["best shoes", "kids shoes"])

    by_kw = {r["keyword"]: r for r in results}
    assert by_kw["kids shoes"]["search_volume"] == 6500
    assert by_kw["kids shoes"]["volume_source"] == "clickstream"
    assert by_kw["kids shoes"]["keyword_difficulty"] == 35
    assert by_kw["best shoes"]["volume_source"] == "google_ads"


def test_enrich_keywords_bulk_empty_input(service):
    """Empty input returns empty list."""
    assert service.enrich_keywords_bulk([]) == []


def test_enrich_keywords_bulk_not_available(unavailable_service):
    """Returns empty list when credentials are missing."""
    assert unavailable_service.enrich_keywords_bulk(["test"]) == []


@patch.object(DataForSEOService, "_post")
def test_enrich_keywords_bulk_kd_merges_into_results(mock_post, service):
    """KD data is properly merged into the existing volume results."""
    mock_post.side_effect = [
        # Google Ads volume
        {
            "status_code": 20000,
            "tasks": [{
                "result": [
                    {"keyword": "seo tools", "search_volume": 12000, "cpc": 3.50, "competition": "HIGH"},
                ]
            }],
        },
        # KD
        {
            "status_code": 20000,
            "tasks": [{
                "result": [{
                    "items": [
                        {"keyword": "seo tools", "keyword_difficulty": 88},
                    ]
                }]
            }],
        },
    ]

    results = service.enrich_keywords_bulk(["seo tools"])

    assert len(results) == 1
    assert results[0]["keyword"] == "seo tools"
    assert results[0]["search_volume"] == 12000
    assert results[0]["cpc"] == 3.50
    assert results[0]["competition"] == 1.0
    assert results[0]["keyword_difficulty"] == 88
    assert results[0]["volume_source"] == "google_ads"
