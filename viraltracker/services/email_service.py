"""
EmailService - Send emails using Resend API.

Handles email sending for ad generation exports with support for
HTML templates, image links, and zip download links.
"""

import logging
from typing import Optional, List
from dataclasses import dataclass

import resend

from ..core.config import Config

logger = logging.getLogger(__name__)


@dataclass
class EmailResult:
    """Result of an email send operation."""
    success: bool
    message_id: Optional[str] = None
    error: Optional[str] = None


@dataclass
class AdEmailContent:
    """Content for an ad generation email."""
    product_name: str
    brand_name: str
    image_urls: List[str]
    zip_download_url: Optional[str] = None
    ad_run_ids: Optional[List[str]] = None
    schedule_name: Optional[str] = None


class EmailService:
    """
    Service for sending emails via Resend API.

    Features:
    - HTML email templates for ad exports
    - Support for multiple image links
    - Zip download link inclusion
    - Error handling and logging

    Example:
        >>> service = EmailService()
        >>> result = await service.send_ad_export_email(
        ...     to_email="user@example.com",
        ...     content=AdEmailContent(
        ...         product_name="Widget Pro",
        ...         brand_name="Acme Inc",
        ...         image_urls=["https://storage.com/ad1.jpg", "https://storage.com/ad2.jpg"],
        ...         zip_download_url="https://storage.com/all_ads.zip"
        ...     )
        ... )
        >>> print(result.success)
        True
    """

    def __init__(self, api_key: Optional[str] = None, from_email: Optional[str] = None):
        """
        Initialize EmailService.

        Args:
            api_key: Resend API key (if None, uses Config.RESEND_API_KEY)
            from_email: Default sender email (if None, uses Config.EMAIL_FROM)

        Raises:
            ValueError: If API key not found
        """
        self.api_key = api_key or Config.RESEND_API_KEY
        if not self.api_key:
            logger.warning("RESEND_API_KEY not found - EmailService will be disabled")
            self._enabled = False
        else:
            self._enabled = True
            resend.api_key = self.api_key

        self.from_email = from_email or Config.EMAIL_FROM or "noreply@viraltracker.io"

        logger.info(f"EmailService initialized (enabled={self._enabled}, from={self.from_email})")

    @property
    def enabled(self) -> bool:
        """Check if email service is enabled (has valid API key)."""
        return self._enabled

    async def send_email(
        self,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: Optional[str] = None
    ) -> EmailResult:
        """
        Send a basic email.

        Args:
            to_email: Recipient email address
            subject: Email subject line
            html_body: HTML content of the email
            text_body: Optional plain text fallback

        Returns:
            EmailResult with success status and message ID or error
        """
        if not self._enabled:
            return EmailResult(
                success=False,
                error="EmailService is disabled - RESEND_API_KEY not configured"
            )

        try:
            logger.info(f"Sending email to {to_email}: {subject}")

            params = {
                "from": self.from_email,
                "to": [to_email],
                "subject": subject,
                "html": html_body,
            }

            if text_body:
                params["text"] = text_body

            response = resend.Emails.send(params)

            message_id = response.get("id") if isinstance(response, dict) else getattr(response, "id", None)

            logger.info(f"Email sent successfully: {message_id}")
            return EmailResult(success=True, message_id=message_id)

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to send email: {error_msg}")
            return EmailResult(success=False, error=error_msg)

    async def send_ad_export_email(
        self,
        to_email: str,
        content: AdEmailContent,
        subject: Optional[str] = None
    ) -> EmailResult:
        """
        Send an ad export email with image links and zip download.

        Args:
            to_email: Recipient email address
            content: AdEmailContent with product/brand info and image URLs
            subject: Optional custom subject (default: auto-generated)

        Returns:
            EmailResult with success status and message ID or error
        """
        if not subject:
            if content.schedule_name:
                subject = f"🎨 Scheduled Ads Ready: {content.schedule_name} - {content.product_name}"
            else:
                subject = f"🎨 Your Generated Ads are Ready - {content.product_name}"

        html_body = self._build_ad_export_html(content)
        text_body = self._build_ad_export_text(content)

        return await self.send_email(
            to_email=to_email,
            subject=subject,
            html_body=html_body,
            text_body=text_body
        )

    def _build_ad_export_html(self, content: AdEmailContent) -> str:
        """Build HTML email body for ad export."""

        # Build image gallery HTML
        images_html = ""
        for i, url in enumerate(content.image_urls, 1):
            images_html += f"""
            <div style="margin-bottom: 20px; text-align: center;">
                <a href="{url}" target="_blank">
                    <img src="{url}" alt="Ad {i}" style="max-width: 100%; max-height: 400px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
                </a>
                <div style="margin-top: 8px;">
                    <a href="{url}" target="_blank" style="color: #4F46E5; text-decoration: none; font-size: 14px;">View Full Size →</a>
                </div>
            </div>
            """

        # Build zip download section
        zip_section = ""
        if content.zip_download_url:
            zip_section = f"""
            <div style="background: #F3F4F6; padding: 20px; border-radius: 8px; text-align: center; margin: 30px 0;">
                <p style="margin: 0 0 15px 0; color: #374151; font-size: 16px;">
                    📦 Download all {len(content.image_urls)} images in one file:
                </p>
                <a href="{content.zip_download_url}"
                   style="display: inline-block; background: #4F46E5; color: white; padding: 12px 24px;
                          border-radius: 6px; text-decoration: none; font-weight: 600;">
                    Download ZIP File
                </a>
            </div>
            """

        # Schedule info section
        schedule_info = ""
        if content.schedule_name:
            schedule_info = f"""
            <p style="color: #6B7280; font-size: 14px; margin-bottom: 20px;">
                From scheduled job: <strong>{content.schedule_name}</strong>
            </p>
            """

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                     line-height: 1.6; color: #1F2937; max-width: 600px; margin: 0 auto; padding: 20px;">

            <div style="text-align: center; margin-bottom: 30px;">
                <h1 style="color: #111827; margin-bottom: 10px;">Your Ads are Ready! 🎉</h1>
                <p style="color: #6B7280; font-size: 18px; margin: 0;">
                    {content.brand_name} • {content.product_name}
                </p>
                {schedule_info}
            </div>

            <div style="margin-bottom: 30px;">
                <h2 style="color: #374151; font-size: 18px; margin-bottom: 20px;">
                    Generated Ads ({len(content.image_urls)} images)
                </h2>
                {images_html}
            </div>

            {zip_section}

            <div style="border-top: 1px solid #E5E7EB; padding-top: 20px; margin-top: 30px;
                        text-align: center; color: #9CA3AF; font-size: 12px;">
                <p>Generated by ViralTracker Ad Creator</p>
            </div>
        </body>
        </html>
        """

    def _build_ad_export_text(self, content: AdEmailContent) -> str:
        """Build plain text email body for ad export."""

        lines = [
            f"Your Ads are Ready!",
            f"",
            f"Brand: {content.brand_name}",
            f"Product: {content.product_name}",
        ]

        if content.schedule_name:
            lines.append(f"Schedule: {content.schedule_name}")

        lines.extend([
            f"",
            f"Generated Ads ({len(content.image_urls)} images):",
            f"",
        ])

        for i, url in enumerate(content.image_urls, 1):
            lines.append(f"  {i}. {url}")

        if content.zip_download_url:
            lines.extend([
                f"",
                f"Download all images as ZIP:",
                f"  {content.zip_download_url}",
            ])

        lines.extend([
            f"",
            f"---",
            f"Generated by ViralTracker Ad Creator",
        ])

        return "\n".join(lines)
