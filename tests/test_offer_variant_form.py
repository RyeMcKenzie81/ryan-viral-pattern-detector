"""
Unit tests for offer_variant_form.py:
- sync_url_to_landing_pages()

Note: render_offer_variant_review_form() is primarily a Streamlit UI function
and is tested via manual verification, not unit tests.

Run with: pytest tests/test_offer_variant_form.py -v
"""

import pytest
from unittest.mock import MagicMock, patch, call
from uuid import uuid4


# ---------------------------------------------------------------------------
# sync_url_to_landing_pages
# ---------------------------------------------------------------------------


class TestSyncUrlToLandingPages:
    @patch("viraltracker.ui.offer_variant_form.get_supabase_client")
    @patch("viraltracker.services.url_canonicalizer.canonicalize_url", return_value="example.com/page")
    def test_creates_new_row_with_pending_status(self, mock_canon, mock_get_db):
        from viraltracker.ui.offer_variant_form import sync_url_to_landing_pages

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db

        brand_id = str(uuid4())
        url = "https://example.com/page"
        product_id = str(uuid4())

        # No existing row
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])

        result = sync_url_to_landing_pages(brand_id, url, product_id)
        assert result is True

        # Verify insert was called
        insert_call = mock_db.table.return_value.insert
        assert insert_call.called
        data = insert_call.call_args[0][0]
        assert data["brand_id"] == brand_id
        assert data["url"] == url
        assert data["canonical_url"] == "example.com/page"
        assert data["scrape_status"] == "pending"
        assert data["product_id"] == product_id

    @patch("viraltracker.ui.offer_variant_form.get_supabase_client")
    @patch("viraltracker.services.url_canonicalizer.canonicalize_url", return_value="example.com/page")
    def test_does_not_overwrite_existing_scrape_status(self, mock_canon, mock_get_db):
        from viraltracker.ui.offer_variant_form import sync_url_to_landing_pages

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db

        brand_id = str(uuid4())
        row_id = str(uuid4())

        # Existing row with analyzed status
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{
                "id": row_id,
                "product_id": str(uuid4()),
                "scrape_status": "analyzed",
                "canonical_url": "example.com/page",
            }]
        )

        result = sync_url_to_landing_pages(brand_id, "https://example.com/page")
        assert result is True

        # Verify NO update or insert was called (existing row has product_id and canonical_url)
        mock_db.table.return_value.update.assert_not_called()
        mock_db.table.return_value.insert.assert_not_called()

    @patch("viraltracker.ui.offer_variant_form.get_supabase_client")
    @patch("viraltracker.services.url_canonicalizer.canonicalize_url", return_value="example.com/page")
    def test_does_not_overwrite_product_id_with_null(self, mock_canon, mock_get_db):
        from viraltracker.ui.offer_variant_form import sync_url_to_landing_pages

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db

        brand_id = str(uuid4())
        existing_product_id = str(uuid4())
        row_id = str(uuid4())

        # Existing row WITH product_id
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{
                "id": row_id,
                "product_id": existing_product_id,
                "scrape_status": "analyzed",
                "canonical_url": "example.com/page",
            }]
        )

        # Call WITHOUT product_id — should NOT null it out
        result = sync_url_to_landing_pages(brand_id, "https://example.com/page")
        assert result is True

        # No update since existing has product_id and canonical_url
        mock_db.table.return_value.update.assert_not_called()

    @patch("viraltracker.ui.offer_variant_form.get_supabase_client")
    @patch("viraltracker.services.url_canonicalizer.canonicalize_url", return_value="example.com/page")
    def test_sets_product_id_when_existing_has_none(self, mock_canon, mock_get_db):
        from viraltracker.ui.offer_variant_form import sync_url_to_landing_pages

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db

        brand_id = str(uuid4())
        product_id = str(uuid4())
        row_id = str(uuid4())

        # Existing row WITHOUT product_id or canonical_url
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{
                "id": row_id,
                "product_id": None,
                "scrape_status": "analyzed",
                "canonical_url": None,
            }]
        )

        result = sync_url_to_landing_pages(brand_id, "https://example.com/page", product_id)
        assert result is True

        # Should have updated product_id and canonical_url
        update_call = mock_db.table.return_value.update
        assert update_call.called
        updates = update_call.call_args[0][0]
        assert updates["product_id"] == product_id
        assert updates["canonical_url"] == "example.com/page"

    @patch("viraltracker.ui.offer_variant_form.get_supabase_client")
    @patch("viraltracker.services.url_canonicalizer.canonicalize_url", return_value="example.com/page")
    def test_new_row_without_product_id(self, mock_canon, mock_get_db):
        from viraltracker.ui.offer_variant_form import sync_url_to_landing_pages

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db

        brand_id = str(uuid4())

        # No existing row
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])

        result = sync_url_to_landing_pages(brand_id, "https://example.com/page")
        assert result is True

        data = mock_db.table.return_value.insert.call_args[0][0]
        assert "product_id" not in data  # Should NOT include product_id key
        assert data["scrape_status"] == "pending"

    @patch("viraltracker.ui.offer_variant_form.get_supabase_client")
    @patch("viraltracker.services.url_canonicalizer.canonicalize_url", return_value="example.com/page")
    def test_exception_returns_false(self, mock_canon, mock_get_db):
        from viraltracker.ui.offer_variant_form import sync_url_to_landing_pages

        mock_get_db.side_effect = Exception("DB connection failed")

        result = sync_url_to_landing_pages("brand", "https://example.com")
        assert result is False
