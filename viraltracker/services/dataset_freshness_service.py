"""
Dataset Freshness Service - Track when datasets were last refreshed per brand.

Provides start/success/failure recording for dataset refreshes and freshness
checking for UI banners and health dashboards.

Invariants:
- record_start() never overwrites last_success_at
- record_success() clears error_message for that dataset_key only
- record_failure() never touches last_success_at
- All three methods always update last_attempt_at

Usage:
    from viraltracker.services.dataset_freshness_service import DatasetFreshnessService

    freshness = DatasetFreshnessService()
    freshness.record_start(brand_id, "meta_ads_performance", run_id=run_id)
    freshness.record_success(brand_id, "meta_ads_performance", records_affected=100)
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class DatasetFreshnessService:
    """Service for tracking dataset freshness per brand."""

    def __init__(self):
        from viraltracker.core.database import get_supabase_client
        self._db = get_supabase_client()

    def record_start(
        self,
        brand_id: str,
        dataset_key: str,
        run_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> None:
        """Mark a dataset refresh as started.

        Sets last_status='running', last_attempt_at=now.
        Does NOT touch last_success_at.

        Args:
            brand_id: Brand UUID string
            dataset_key: Dataset identifier (e.g. 'meta_ads_performance')
            run_id: Optional scheduled_job_runs ID for traceability
            org_id: Optional organization ID for multi-tenant filtering
        """
        now = datetime.now(timezone.utc).isoformat()
        data = {
            "brand_id": brand_id,
            "dataset_key": dataset_key,
            "last_status": "running",
            "last_attempt_at": now,
            "error_message": None,
        }
        if run_id:
            data["last_run_id"] = run_id
        if org_id:
            data["organization_id"] = org_id

        try:
            self._db.table("dataset_status").upsert(
                data, on_conflict="brand_id,dataset_key"
            ).execute()
        except Exception as e:
            logger.error(f"Failed to record_start for {dataset_key}/{brand_id}: {e}")

    def record_success(
        self,
        brand_id: str,
        dataset_key: str,
        records_affected: int = 0,
        run_id: Optional[str] = None,
        org_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Mark a dataset refresh as successful.

        Updates last_success_at=now, last_attempt_at=now, last_status='completed'.
        Clears error_message for this dataset_key only.

        Args:
            brand_id: Brand UUID string
            dataset_key: Dataset identifier
            records_affected: Number of rows inserted/updated
            run_id: Optional scheduled_job_runs ID
            org_id: Optional organization ID
            metadata: Optional extra info to store
        """
        now = datetime.now(timezone.utc).isoformat()
        data = {
            "brand_id": brand_id,
            "dataset_key": dataset_key,
            "last_success_at": now,
            "last_attempt_at": now,
            "last_status": "completed",
            "records_affected": records_affected,
            "error_message": None,
        }
        if run_id:
            data["last_run_id"] = run_id
        if org_id:
            data["organization_id"] = org_id
        if metadata:
            data["metadata"] = metadata

        try:
            self._db.table("dataset_status").upsert(
                data, on_conflict="brand_id,dataset_key"
            ).execute()
        except Exception as e:
            logger.error(f"Failed to record_success for {dataset_key}/{brand_id}: {e}")

    def record_failure(
        self,
        brand_id: str,
        dataset_key: str,
        error_message: str,
        run_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> None:
        """Mark a dataset refresh as failed.

        Sets last_status='failed', last_attempt_at=now, stores error_message.
        Does NOT update last_success_at.

        Args:
            brand_id: Brand UUID string
            dataset_key: Dataset identifier
            error_message: Error description
            run_id: Optional scheduled_job_runs ID
            org_id: Optional organization ID
        """
        now = datetime.now(timezone.utc).isoformat()
        data = {
            "brand_id": brand_id,
            "dataset_key": dataset_key,
            "last_status": "failed",
            "last_attempt_at": now,
            "error_message": error_message,
        }
        if run_id:
            data["last_run_id"] = run_id
        if org_id:
            data["organization_id"] = org_id

        try:
            self._db.table("dataset_status").upsert(
                data, on_conflict="brand_id,dataset_key"
            ).execute()
        except Exception as e:
            logger.error(f"Failed to record_failure for {dataset_key}/{brand_id}: {e}")

    def get_freshness(self, brand_id: str, dataset_key: str) -> Optional[Dict[str, Any]]:
        """Get current freshness status for a single dataset.

        Args:
            brand_id: Brand UUID string
            dataset_key: Dataset identifier

        Returns:
            Status dict or None if no record exists.
        """
        try:
            result = self._db.table("dataset_status").select("*").eq(
                "brand_id", brand_id
            ).eq("dataset_key", dataset_key).limit(1).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Failed to get_freshness for {dataset_key}/{brand_id}: {e}")
            return None

    def get_all_freshness(self, brand_id: str) -> List[Dict[str, Any]]:
        """Get freshness status for all datasets of a brand.

        Args:
            brand_id: Brand UUID string

        Returns:
            List of status dicts.
        """
        try:
            result = self._db.table("dataset_status").select("*").eq(
                "brand_id", brand_id
            ).order("dataset_key").execute()
            return result.data or []
        except Exception as e:
            logger.error(f"Failed to get_all_freshness for {brand_id}: {e}")
            return []

    def check_is_fresh(self, brand_id: str, dataset_key: str, max_age_hours: float) -> bool:
        """Check if a dataset's last success is within the max age.

        Args:
            brand_id: Brand UUID string
            dataset_key: Dataset identifier
            max_age_hours: Maximum acceptable age in hours

        Returns:
            True if last_success_at is within max_age_hours, False otherwise.
            Returns False if no success has ever been recorded.
        """
        freshness = self.get_freshness(brand_id, dataset_key)
        if not freshness or not freshness.get("last_success_at"):
            return False

        try:
            last_success = datetime.fromisoformat(freshness["last_success_at"])
            age_hours = (datetime.now(timezone.utc) - last_success).total_seconds() / 3600
            return age_hours <= max_age_hours
        except (ValueError, TypeError):
            return False
