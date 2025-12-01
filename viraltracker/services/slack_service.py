"""
SlackService - Send messages to Slack using Incoming Webhooks.

Handles Slack notifications for ad generation exports with support for
rich Block Kit formatting and image previews.
"""

import logging
import httpx
from typing import Optional, List
from dataclasses import dataclass

from ..core.config import Config

logger = logging.getLogger(__name__)


@dataclass
class SlackResult:
    """Result of a Slack message send operation."""
    success: bool
    error: Optional[str] = None


@dataclass
class AdSlackContent:
    """Content for an ad generation Slack message."""
    product_name: str
    brand_name: str
    image_urls: List[str]
    zip_download_url: Optional[str] = None
    ad_run_ids: Optional[List[str]] = None
    schedule_name: Optional[str] = None


class SlackService:
    """
    Service for sending messages to Slack via Incoming Webhooks.

    Features:
    - Rich Block Kit formatting
    - Image previews in messages
    - Zip download link buttons
    - Error handling and logging

    Example:
        >>> service = SlackService()
        >>> result = await service.send_ad_export_message(
        ...     content=AdSlackContent(
        ...         product_name="Widget Pro",
        ...         brand_name="Acme Inc",
        ...         image_urls=["https://storage.com/ad1.jpg", "https://storage.com/ad2.jpg"],
        ...         zip_download_url="https://storage.com/all_ads.zip"
        ...     )
        ... )
        >>> print(result.success)
        True
    """

    def __init__(self, webhook_url: Optional[str] = None):
        """
        Initialize SlackService.

        Args:
            webhook_url: Slack Incoming Webhook URL (if None, uses Config.SLACK_WEBHOOK_URL)
        """
        self.webhook_url = webhook_url or Config.SLACK_WEBHOOK_URL

        if not self.webhook_url:
            logger.warning("SLACK_WEBHOOK_URL not found - SlackService will be disabled")
            self._enabled = False
        else:
            self._enabled = True

        logger.info(f"SlackService initialized (enabled={self._enabled})")

    @property
    def enabled(self) -> bool:
        """Check if Slack service is enabled (has valid webhook URL)."""
        return self._enabled

    async def send_message(
        self,
        text: str,
        blocks: Optional[List[dict]] = None,
        webhook_url: Optional[str] = None
    ) -> SlackResult:
        """
        Send a message to Slack.

        Args:
            text: Fallback text for notifications
            blocks: Optional Block Kit blocks for rich formatting
            webhook_url: Optional override webhook URL (for per-schedule channels)

        Returns:
            SlackResult with success status or error
        """
        url = webhook_url or self.webhook_url

        if not url:
            return SlackResult(
                success=False,
                error="SlackService is disabled - no webhook URL configured"
            )

        try:
            logger.info("Sending Slack message")

            payload = {"text": text}
            if blocks:
                payload["blocks"] = blocks

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    json=payload,
                    timeout=30.0
                )

            if response.status_code == 200 and response.text == "ok":
                logger.info("Slack message sent successfully")
                return SlackResult(success=True)
            else:
                error_msg = f"Slack API error: {response.status_code} - {response.text}"
                logger.error(error_msg)
                return SlackResult(success=False, error=error_msg)

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to send Slack message: {error_msg}")
            return SlackResult(success=False, error=error_msg)

    async def send_ad_export_message(
        self,
        content: AdSlackContent,
        webhook_url: Optional[str] = None
    ) -> SlackResult:
        """
        Send an ad export notification to Slack with image previews.

        Args:
            content: AdSlackContent with product/brand info and image URLs
            webhook_url: Optional override webhook URL (for per-schedule channels)

        Returns:
            SlackResult with success status or error
        """
        blocks = self._build_ad_export_blocks(content)
        fallback_text = f"🎨 New ads ready for {content.product_name} ({len(content.image_urls)} images)"

        return await self.send_message(
            text=fallback_text,
            blocks=blocks,
            webhook_url=webhook_url
        )

    def _build_ad_export_blocks(self, content: AdSlackContent) -> List[dict]:
        """Build Slack Block Kit blocks for ad export message."""

        blocks = []

        # Header
        header_text = f"🎨 New Ads Ready!"
        if content.schedule_name:
            header_text = f"🎨 Scheduled Ads Ready: {content.schedule_name}"

        blocks.append({
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": header_text,
                "emoji": True
            }
        })

        # Context - Brand & Product info
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"*{content.brand_name}* • {content.product_name} • {len(content.image_urls)} images"
                }
            ]
        })

        blocks.append({"type": "divider"})

        # Image previews (show first 3, with note about more)
        max_preview = 3
        for i, url in enumerate(content.image_urls[:max_preview]):
            blocks.append({
                "type": "image",
                "image_url": url,
                "alt_text": f"Generated ad {i + 1}"
            })

        # Note about additional images
        if len(content.image_urls) > max_preview:
            remaining = len(content.image_urls) - max_preview
            blocks.append({
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"_+ {remaining} more images in download_"
                    }
                ]
            })

        # Action buttons
        actions_elements = []

        # Individual image links (first 5)
        if content.image_urls:
            image_links = " | ".join([
                f"<{url}|Image {i+1}>"
                for i, url in enumerate(content.image_urls[:5])
            ])
            if len(content.image_urls) > 5:
                image_links += f" | _+{len(content.image_urls) - 5} more_"

            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*View images:* {image_links}"
                }
            })

        # ZIP download button
        if content.zip_download_url:
            blocks.append({
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "📦 Download All (ZIP)",
                            "emoji": True
                        },
                        "url": content.zip_download_url,
                        "style": "primary"
                    }
                ]
            })

        # Footer
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Generated by ViralTracker Ad Creator"
                }
            ]
        })

        return blocks
