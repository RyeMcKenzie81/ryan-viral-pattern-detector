"""Test _add_to_review_queue handles both ad_ids and meta_ad_ids merge.

Verifies:
- New URL with meta_ad_ids inserts correctly
- Existing row merges meta_ad_ids, increments occurrence_count
- Existing scrape behavior preserved (ad_ids only, no meta_ad_ids touched)
"""
import unittest
from unittest.mock import MagicMock, patch, PropertyMock
from uuid import uuid4


class TestReviewQueueMetaMerge(unittest.TestCase):

    def setUp(self):
        self.mock_supabase = MagicMock()
        # Patch get_supabase_client so ProductURLService.__init__ uses our mock
        with patch("viraltracker.services.product_url_service.get_supabase_client", return_value=self.mock_supabase):
            from viraltracker.services.product_url_service import ProductURLService
            self.service = ProductURLService()

    def _mock_no_existing_row(self):
        """Set up mock chain for 'no existing row in review queue'."""
        chain = self.mock_supabase.table.return_value
        chain.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

    def _mock_existing_row(self, row_data):
        """Set up mock chain for 'existing row in review queue'."""
        chain = self.mock_supabase.table.return_value
        chain.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[row_data])

    def test_insert_with_meta_ad_ids(self):
        """New URL with meta_ad_ids inserts correctly."""
        self._mock_no_existing_row()

        self.service._add_to_review_queue(
            brand_id=uuid4(),
            url="https://example.com/product",
            normalized_url="example.com/product",
            meta_ad_ids=["meta_1", "meta_2"],
        )

        # Verify insert was called
        insert_call = self.mock_supabase.table.return_value.insert
        self.assertTrue(insert_call.called, "insert() should have been called for new URL")

        insert_data = insert_call.call_args[0][0]
        self.assertEqual(insert_data["sample_meta_ad_ids"], ["meta_1", "meta_2"])
        self.assertEqual(insert_data.get("sample_ad_ids", []), [])
        self.assertEqual(insert_data["occurrence_count"], 1)

    def test_insert_with_both_id_types(self):
        """New URL with both ad_ids and meta_ad_ids inserts both."""
        self._mock_no_existing_row()

        self.service._add_to_review_queue(
            brand_id=uuid4(),
            url="https://example.com/product",
            normalized_url="example.com/product",
            ad_ids=["uuid_1"],
            meta_ad_ids=["meta_1"],
        )

        insert_call = self.mock_supabase.table.return_value.insert
        insert_data = insert_call.call_args[0][0]
        self.assertEqual(insert_data["sample_ad_ids"], ["uuid_1"])
        self.assertEqual(insert_data["sample_meta_ad_ids"], ["meta_1"])

    def test_merge_meta_ad_ids_on_existing(self):
        """Existing row merges meta_ad_ids, increments occurrence_count."""
        self._mock_existing_row({
            "id": "row1",
            "occurrence_count": 3,
            "sample_ad_ids": ["uuid1"],
            "sample_meta_ad_ids": ["meta_1"],
        })

        self.service._add_to_review_queue(
            brand_id=uuid4(),
            url="https://example.com/product",
            normalized_url="example.com/product",
            meta_ad_ids=["meta_2", "meta_3"],
        )

        # Verify update was called
        update_call = self.mock_supabase.table.return_value.update
        self.assertTrue(update_call.called, "update() should have been called for existing URL")

        update_data = update_call.call_args[0][0]
        self.assertEqual(update_data["occurrence_count"], 4)
        self.assertEqual(set(update_data["sample_meta_ad_ids"]), {"meta_1", "meta_2", "meta_3"})
        # Existing ad_ids should be preserved
        self.assertEqual(update_data["sample_ad_ids"], ["uuid1"])

    def test_existing_scrape_behavior_preserved(self):
        """Calling with only ad_ids (no meta_ad_ids) works same as before."""
        self._mock_existing_row({
            "id": "row1",
            "occurrence_count": 1,
            "sample_ad_ids": ["uuid1"],
            "sample_meta_ad_ids": None,
        })

        self.service._add_to_review_queue(
            brand_id=uuid4(),
            url="https://example.com/product",
            normalized_url="example.com/product",
            ad_ids=["uuid2"],
        )

        update_call = self.mock_supabase.table.return_value.update
        update_data = update_call.call_args[0][0]
        # sample_meta_ad_ids should not be in update when no meta_ad_ids passed
        self.assertNotIn("sample_meta_ad_ids", update_data,
                         "sample_meta_ad_ids should not be touched when meta_ad_ids is empty")
        self.assertEqual(set(update_data["sample_ad_ids"]), {"uuid1", "uuid2"})
        self.assertEqual(update_data["occurrence_count"], 2)

    def test_meta_ad_ids_capped_at_five(self):
        """sample_meta_ad_ids should not exceed 5 entries."""
        self._mock_existing_row({
            "id": "row1",
            "occurrence_count": 1,
            "sample_ad_ids": [],
            "sample_meta_ad_ids": ["m1", "m2", "m3", "m4"],
        })

        self.service._add_to_review_queue(
            brand_id=uuid4(),
            url="https://example.com/product",
            normalized_url="example.com/product",
            meta_ad_ids=["m5", "m6", "m7"],
        )

        update_call = self.mock_supabase.table.return_value.update
        update_data = update_call.call_args[0][0]
        # Should be capped at 5
        self.assertLessEqual(len(update_data["sample_meta_ad_ids"]), 5,
                             "sample_meta_ad_ids should be capped at 5")


if __name__ == "__main__":
    unittest.main()
