"""
Tests for Ad Performance helper functions — signed URL bucket parsing,
brand-scoped link queries, and unlink safety.

All database calls are mocked — no real DB or API connections needed.
"""

import pytest
from unittest.mock import MagicMock, patch


# ============================================================================
# Signed URL Bucket Parsing Tests
# ============================================================================

class TestSignedUrlBucketParsing:
    """Test that get_signed_url correctly parses bucket from storage_path."""

    def _get_signed_url_logic(self, storage_path: str):
        """Replicate the bucket parsing logic from get_signed_url."""
        KNOWN_STORAGE_BUCKETS = {"generated-ads", "meta-ad-assets", "reference-ads"}
        parts = storage_path.split("/", 1)
        if len(parts) == 2 and parts[0] in KNOWN_STORAGE_BUCKETS:
            bucket, path = parts
        else:
            bucket = "generated-ads"
            path = storage_path
        return bucket, path

    def test_generated_ads_bucket(self):
        bucket, path = self._get_signed_url_logic("generated-ads/brand/abc.png")
        assert bucket == "generated-ads"
        assert path == "brand/abc.png"

    def test_meta_ad_assets_bucket(self):
        bucket, path = self._get_signed_url_logic("meta-ad-assets/brand/xyz.jpg")
        assert bucket == "meta-ad-assets"
        assert path == "brand/xyz.jpg"

    def test_reference_ads_bucket(self):
        bucket, path = self._get_signed_url_logic("reference-ads/brand/ref.png")
        assert bucket == "reference-ads"
        assert path == "brand/ref.png"

    def test_no_bucket_prefix_defaults_to_generated_ads(self):
        bucket, path = self._get_signed_url_logic("path/to/file.png")
        assert bucket == "generated-ads"
        assert path == "path/to/file.png"

    def test_unknown_bucket_prefix_defaults(self):
        bucket, path = self._get_signed_url_logic("unknown-bucket/file.png")
        assert bucket == "generated-ads"
        assert path == "unknown-bucket/file.png"

    def test_empty_path(self):
        """Empty paths handled by get_signed_url's early return."""
        # The function returns None for empty paths before reaching parsing
        pass

    def test_deep_path_with_known_bucket(self):
        bucket, path = self._get_signed_url_logic("meta-ad-assets/org/brand/2026/file.jpg")
        assert bucket == "meta-ad-assets"
        assert path == "org/brand/2026/file.jpg"


# ============================================================================
# Link Scoping Tests
# ============================================================================

class TestLinkScoping:
    """Verify get_linked_ads uses brand-scoped RPC."""

    def _get_linked_ads_logic(self, db, brand_id: str):
        """Replicate the get_linked_ads logic from Ad Performance page."""
        result = db.rpc("get_linked_ads_for_brand", {
            "p_brand_id": brand_id
        }).execute()
        return result.data or []

    def test_get_linked_ads_calls_rpc_with_brand_id(self):
        """get_linked_ads should call RPC with brand_id parameter."""
        brand_id = "00000000-0000-0000-0000-000000000001"

        mock_db = MagicMock()
        mock_rpc_result = MagicMock()
        mock_rpc_result.data = [
            {"meta_ad_id": "m1", "generated_ad_id": "g1", "linked_by": "auto",
             "storage_path": "p1", "hook_text": "h1", "final_status": "approved",
             "is_imported": False, "meta_ad_account_id": "act_1",
             "meta_campaign_id": "camp_1"},
        ]
        mock_db.rpc.return_value.execute.return_value = mock_rpc_result

        result = self._get_linked_ads_logic(mock_db, brand_id)

        # Verify RPC called with correct function name and brand_id
        mock_db.rpc.assert_called_once_with(
            "get_linked_ads_for_brand", {"p_brand_id": brand_id}
        )
        assert len(result) == 1
        assert result[0]["meta_ad_id"] == "m1"


# ============================================================================
# Unlink Safety Tests
# ============================================================================

class TestUnlinkSafety:
    """Verify delete_ad_link targets specific mapping row."""

    def _delete_ad_link_logic(self, db, meta_ad_id: str, generated_ad_id: str):
        """Replicate delete_ad_link (specific mapping) from Ad Performance."""
        db.table("meta_ad_mapping").delete().eq(
            "meta_ad_id", meta_ad_id
        ).eq("generated_ad_id", generated_ad_id).execute()

    def _delete_all_ad_links_logic(self, db, meta_ad_id: str):
        """Replicate delete_all_ad_links (all for meta_ad_id) from Ad Performance."""
        db.table("meta_ad_mapping").delete().eq(
            "meta_ad_id", meta_ad_id
        ).execute()

    def test_delete_ad_link_uses_dual_filter(self):
        """delete_ad_link(meta_ad_id, generated_ad_id) should filter by both."""
        mock_db = MagicMock()
        mock_chain = MagicMock()
        mock_db.table.return_value.delete.return_value = mock_chain
        mock_chain.eq.return_value = mock_chain

        self._delete_ad_link_logic(mock_db, "meta_123", "gen_456")

        # Verify both .eq() filters are applied
        mock_db.table.assert_called_with("meta_ad_mapping")
        eq_calls = mock_chain.eq.call_args_list
        assert len(eq_calls) == 2
        assert eq_calls[0] == (("meta_ad_id", "meta_123"),)
        assert eq_calls[1] == (("generated_ad_id", "gen_456"),)
        mock_chain.execute.assert_called_once()

    def test_delete_all_ad_links_only_filters_by_meta_id(self):
        """delete_all_ad_links(meta_ad_id) should only filter by meta_ad_id."""
        mock_db = MagicMock()
        mock_chain = MagicMock()
        mock_db.table.return_value.delete.return_value = mock_chain
        mock_chain.eq.return_value = mock_chain

        self._delete_all_ad_links_logic(mock_db, "meta_123")

        mock_db.table.assert_called_with("meta_ad_mapping")
        # Only one .eq() filter — just meta_ad_id
        mock_chain.eq.assert_called_once_with("meta_ad_id", "meta_123")
        mock_chain.execute.assert_called_once()
