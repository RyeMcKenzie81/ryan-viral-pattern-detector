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

from apify_client import ApifyClient
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

    Uses the apify_client library (same as other scrapers in this codebase)
    for reliable API communication.

    Example usage:
        service = ApifyService()
        result = service.run_actor(
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
            self.client = None
        else:
            # Log token presence (not the actual token)
            logger.info(f"ApifyService initialized with token: {self.apify_token[:8]}...")
            self.client = ApifyClient(self.apify_token)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=8))
    def run_actor(
        self,
        actor_id: str,
        run_input: Dict[str, Any],
        timeout: int = 600,
        memory_mbytes: int = 1024
    ) -> ApifyRunResult:
        """
        Run an Apify actor and wait for results.

        Uses the apify_client library for reliable communication.

        Args:
            actor_id: Actor identifier (e.g., "axesso_data/amazon-reviews-scraper")
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
        if not self.client:
            raise ValueError("APIFY_TOKEN not configured - check environment variables")

        logger.info(f"Starting Apify actor: {actor_id}")
        logger.debug(f"Input: {run_input}")

        try:
            # Use apify_client library - handles URL encoding automatically
            run = self.client.actor(actor_id).call(
                run_input=run_input,
                timeout_secs=timeout,
                memory_mbytes=memory_mbytes
            )

            run_id = run["id"]
            dataset_id = run["defaultDatasetId"]
            status = run["status"]

            logger.info(f"Apify run completed: {run_id}, status: {status}")

            # Fetch results from dataset
            items = list(self.client.dataset(dataset_id).iterate_items())
            logger.info(f"Fetched {len(items)} items from dataset {dataset_id}")

            return ApifyRunResult(
                run_id=run_id,
                dataset_id=dataset_id,
                status=status,
                items=items,
                items_count=len(items)
            )

        except Exception as e:
            logger.error(f"Apify actor run failed: {type(e).__name__}: {e}")
            raise

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

        logger.info(f"Running batch with {len(batch_inputs)} configs")

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
