"""
ApifyService - Reusable service for running Apify actors.

This service provides a generic interface for:
- Running any Apify actor with custom inputs
- Polling for run completion
- Fetching results from datasets
- Handling retries and timeouts

Part of the Service Layer - contains business logic, no UI or agent code.
"""

import logging
import time
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from ..core.config import Config

logger = logging.getLogger(__name__)


@dataclass
class ApifyRunResult:
    """Result from an Apify actor run."""
    run_id: str
    dataset_id: str
    status: str
    items: List[Dict[str, Any]]
    items_count: int


class ApifyService:
    """
    Generic service for running Apify actors.

    Provides reusable methods for:
    - Starting actor runs with any input
    - Polling for completion
    - Fetching dataset results
    - Error handling and retries

    Example usage:
        service = ApifyService()
        result = await service.run_actor(
            actor_id="axesso_data/amazon-reviews-scraper",
            run_input={"asin": "B0DJWSV1J3", "domainCode": "com"},
            timeout=300
        )
        print(f"Got {result.items_count} items")
    """

    def __init__(self, apify_token: Optional[str] = None):
        """
        Initialize ApifyService.

        Args:
            apify_token: Apify API token. If not provided, reads from APIFY_TOKEN env var.
        """
        self.apify_token = apify_token or Config.APIFY_TOKEN
        if not self.apify_token:
            logger.warning("APIFY_TOKEN not set - Apify operations will fail")

        self.base_url = "https://api.apify.com/v2"

    def _get_headers(self) -> Dict[str, str]:
        """Get authorization headers for Apify API."""
        return {"Authorization": f"Bearer {self.apify_token}"}

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=8))
    def start_actor_run(
        self,
        actor_id: str,
        run_input: Dict[str, Any],
        memory_mbytes: int = 1024,
        timeout_secs: int = 300
    ) -> str:
        """
        Start an Apify actor run.

        Args:
            actor_id: Actor identifier (e.g., "axesso_data/amazon-reviews-scraper")
            run_input: Input dictionary for the actor
            memory_mbytes: Memory allocation in MB (default: 1024)
            timeout_secs: Actor timeout in seconds (default: 300)

        Returns:
            Run ID string

        Raises:
            ValueError: If API token not configured
            requests.HTTPError: If API call fails
        """
        if not self.apify_token:
            raise ValueError("APIFY_TOKEN not configured")

        url = f"{self.base_url}/acts/{actor_id}/runs"
        params = {
            "memory": memory_mbytes,
            "timeout": timeout_secs
        }

        logger.info(f"Starting Apify actor: {actor_id}")
        logger.debug(f"Input: {run_input}")

        response = requests.post(
            url,
            headers=self._get_headers(),
            params=params,
            json=run_input
        )
        response.raise_for_status()

        run_data = response.json()["data"]
        run_id = run_data["id"]

        logger.info(f"Started Apify run: {run_id}")
        return run_id

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=8))
    def poll_run_status(
        self,
        run_id: str,
        timeout: int = 600,
        poll_interval: float = 2.0
    ) -> Dict[str, Any]:
        """
        Poll an Apify run until completion.

        Args:
            run_id: Apify run ID
            timeout: Maximum seconds to wait (default: 600)
            poll_interval: Initial polling interval in seconds (default: 2.0)

        Returns:
            Dict with run info including datasetId and status

        Raises:
            TimeoutError: If run doesn't complete within timeout
            RuntimeError: If run fails
        """
        url = f"{self.base_url}/actor-runs/{run_id}"
        start_time = time.time()
        wait_time = poll_interval

        logger.info(f"Polling Apify run {run_id}...")

        while time.time() - start_time < timeout:
            response = requests.get(url, headers=self._get_headers())
            response.raise_for_status()

            run_data = response.json()["data"]
            status = run_data["status"]

            if status == "SUCCEEDED":
                dataset_id = run_data["defaultDatasetId"]
                logger.info(f"Apify run completed. Dataset ID: {dataset_id}")
                return {
                    "run_id": run_id,
                    "dataset_id": dataset_id,
                    "status": status
                }

            if status in ["FAILED", "ABORTED", "TIMED-OUT"]:
                error_msg = f"Apify run failed with status: {status}"
                logger.error(error_msg)
                raise RuntimeError(error_msg)

            logger.debug(f"Run status: {status}. Waiting {wait_time:.1f}s...")
            time.sleep(wait_time)
            # Exponential backoff up to 30s
            wait_time = min(wait_time * 1.5, 30)

        raise TimeoutError(f"Apify run timeout after {timeout}s")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=8))
    def fetch_dataset(
        self,
        dataset_id: str,
        limit: Optional[int] = None,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Fetch items from an Apify dataset.

        Args:
            dataset_id: Apify dataset ID
            limit: Maximum items to fetch (None = all)
            offset: Starting offset

        Returns:
            List of item dictionaries
        """
        url = f"{self.base_url}/datasets/{dataset_id}/items"
        params = {"offset": offset}
        if limit:
            params["limit"] = limit

        logger.info(f"Fetching dataset {dataset_id}...")

        response = requests.get(url, headers=self._get_headers(), params=params)
        response.raise_for_status()

        items = response.json()
        logger.info(f"Fetched {len(items)} items from dataset")

        return items

    def run_actor(
        self,
        actor_id: str,
        run_input: Dict[str, Any],
        timeout: int = 600,
        memory_mbytes: int = 1024
    ) -> ApifyRunResult:
        """
        Run an Apify actor and wait for results.

        Combines start_actor_run, poll_run_status, and fetch_dataset
        into a single convenient method.

        Args:
            actor_id: Actor identifier
            run_input: Input dictionary for the actor
            timeout: Maximum seconds to wait for completion
            memory_mbytes: Memory allocation in MB

        Returns:
            ApifyRunResult with run info and items

        Example:
            result = service.run_actor(
                "axesso_data/amazon-reviews-scraper",
                {"asin": "B0DJWSV1J3", "domainCode": "com"}
            )
        """
        # Start the run
        run_id = self.start_actor_run(
            actor_id=actor_id,
            run_input=run_input,
            memory_mbytes=memory_mbytes,
            timeout_secs=timeout
        )

        # Poll for completion
        run_info = self.poll_run_status(run_id, timeout=timeout)

        # Fetch results
        items = self.fetch_dataset(run_info["dataset_id"])

        return ApifyRunResult(
            run_id=run_id,
            dataset_id=run_info["dataset_id"],
            status=run_info["status"],
            items=items,
            items_count=len(items)
        )

    def run_actor_batch(
        self,
        actor_id: str,
        batch_inputs: List[Dict[str, Any]],
        timeout: int = 600,
        memory_mbytes: int = 2048
    ) -> ApifyRunResult:
        """
        Run an Apify actor with batched input (for actors that support input arrays).

        Some actors like axesso_data/amazon-reviews-scraper accept an array
        of configurations in a single run, which is more efficient.

        Args:
            actor_id: Actor identifier
            batch_inputs: List of input dictionaries to process in one run
            timeout: Maximum seconds to wait
            memory_mbytes: Memory allocation (higher for batch runs)

        Returns:
            ApifyRunResult with combined items from all inputs
        """
        # For actors that accept an "input" array
        run_input = {"input": batch_inputs}

        return self.run_actor(
            actor_id=actor_id,
            run_input=run_input,
            timeout=timeout,
            memory_mbytes=memory_mbytes
        )

    def estimate_cost(self, items_count: int, cost_per_1000: float = 0.75) -> float:
        """
        Estimate cost for Apify results.

        Args:
            items_count: Number of items returned
            cost_per_1000: Cost per 1000 results (default: $0.75 for Axesso)

        Returns:
            Estimated cost in dollars
        """
        return (items_count / 1000) * cost_per_1000
