"""
Google Drive Service — OAuth2 + folder management + file upload.

Uses httpx for HTTP calls and shared google_oauth_utils for token refresh.
Tokens stored in brand_integrations with platform='google_drive'.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from viraltracker.services.google_oauth_utils import (
    encode_oauth_state,
    decode_oauth_state,
    refresh_google_token,
)

logger = logging.getLogger(__name__)


class GoogleDriveService:
    """Google Drive integration — OAuth, folder ops, file upload."""

    PLATFORM = "google_drive"
    SCOPE = "https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.readonly"
    DRIVE_API = "https://www.googleapis.com/drive/v3"
    UPLOAD_API = "https://www.googleapis.com/upload/drive/v3"

    def __init__(self):
        from viraltracker.core.database import get_supabase_client
        self.supabase = get_supabase_client()

    # =========================================================================
    # OAUTH2
    # =========================================================================

    @staticmethod
    def get_authorization_url(redirect_uri: str, state: str) -> str:
        """Build Google OAuth2 authorization URL for Drive scope."""
        client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
        if not client_id:
            raise ValueError("GOOGLE_OAUTH_CLIENT_ID env var not set")

        from urllib.parse import urlencode
        params = urlencode({
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": GoogleDriveService.SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        })
        return f"https://accounts.google.com/o/oauth2/v2/auth?{params}"

    @staticmethod
    def exchange_code_for_tokens(code: str, redirect_uri: str) -> Dict[str, Any]:
        """Exchange authorization code for tokens."""
        client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
        client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")
        if not client_id or not client_secret:
            raise ValueError("GOOGLE_OAUTH_CLIENT_ID/SECRET env vars not set")

        with httpx.Client(timeout=15.0) as client:
            response = client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )

        if response.status_code != 200:
            raise Exception(f"Drive token exchange failed: {response.status_code} — {response.text[:200]}")

        return response.json()

    def save_integration(
        self,
        brand_id: str,
        organization_id: str,
        tokens: Dict[str, Any],
    ) -> None:
        """Save Google Drive integration to brand_integrations."""
        config = {
            "access_token": tokens["access_token"],
            "refresh_token": tokens.get("refresh_token", ""),
            "token_expiry": (
                datetime.now(timezone.utc) + timedelta(seconds=tokens.get("expires_in", 3600))
            ).isoformat(),
        }

        self.supabase.table("brand_integrations").upsert(
            {
                "brand_id": brand_id,
                "organization_id": organization_id,
                "platform": self.PLATFORM,
                "config": config,
            },
            on_conflict="brand_id,platform",
        ).execute()

        logger.info(f"Saved Google Drive integration for brand {brand_id}")

    def _get_credentials(self, brand_id: str, organization_id: str) -> tuple:
        """
        Load and refresh Drive credentials.

        Returns (access_token, config) or raises on failure.
        Multi-tenant: filters by organization_id.
        """
        query = (
            self.supabase.table("brand_integrations")
            .select("config")
            .eq("brand_id", brand_id)
            .eq("platform", self.PLATFORM)
            .eq("organization_id", organization_id)
            .limit(1)
        )
        result = query.execute()

        if not result.data:
            raise ValueError("Google Drive not connected for this brand")

        config = result.data[0].get("config", {})
        if not config.get("access_token"):
            raise ValueError("Google Drive integration has no access token")

        # Refresh if needed
        refreshed = refresh_google_token(config)
        if refreshed is None:
            raise ValueError("Google Drive token refresh failed — please reconnect")

        # Persist refreshed tokens back to DB if they changed
        if refreshed.get("access_token") != config.get("access_token"):
            self.supabase.table("brand_integrations").update(
                {"config": refreshed}
            ).eq("brand_id", brand_id).eq("platform", self.PLATFORM).execute()

        return refreshed["access_token"], refreshed

    def is_connected(self, brand_id: str, organization_id: str) -> bool:
        """Check if Drive is connected for this brand."""
        try:
            result = (
                self.supabase.table("brand_integrations")
                .select("id")
                .eq("brand_id", brand_id)
                .eq("platform", self.PLATFORM)
                .eq("organization_id", organization_id)
                .limit(1)
                .execute()
            )
            return bool(result.data)
        except Exception:
            return False

    def disconnect(self, brand_id: str, organization_id: str) -> None:
        """Remove Drive integration for this brand."""
        self.supabase.table("brand_integrations").delete().eq(
            "brand_id", brand_id
        ).eq("platform", self.PLATFORM).eq(
            "organization_id", organization_id
        ).execute()
        logger.info(f"Disconnected Google Drive for brand {brand_id}")

    # =========================================================================
    # FOLDER OPERATIONS
    # =========================================================================

    @staticmethod
    def find_folder(access_token: str, name: str, parent_id: str = None) -> Optional[Dict]:
        """Find a folder by name (optionally within a parent)."""
        escaped_name = name.replace("\\", "\\\\").replace("'", "\\'")
        q = f"name='{escaped_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        if parent_id:
            q += f" and '{parent_id}' in parents"

        with httpx.Client(timeout=15.0) as client:
            response = client.get(
                f"{GoogleDriveService.DRIVE_API}/files",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"q": q, "fields": "files(id,name)", "spaces": "drive"},
            )

        if response.status_code != 200:
            logger.error(f"Drive find_folder failed: {response.status_code}")
            return None

        files = response.json().get("files", [])
        return files[0] if files else None

    @staticmethod
    def create_folder(access_token: str, name: str, parent_id: str = None) -> Dict:
        """Create a folder in Drive."""
        metadata = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        if parent_id:
            metadata["parents"] = [parent_id]

        with httpx.Client(timeout=15.0) as client:
            response = client.post(
                f"{GoogleDriveService.DRIVE_API}/files",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                content=json.dumps(metadata),
            )

        if response.status_code not in (200, 201):
            raise Exception(f"Drive create_folder failed: {response.status_code} — {response.text[:200]}")

        return response.json()

    @staticmethod
    def list_folders(access_token: str, parent_id: str = None) -> List[Dict]:
        """List folders visible to the user (including shared folders with drive.readonly)."""
        q = "mimeType='application/vnd.google-apps.folder' and trashed=false"
        if parent_id:
            q += f" and '{parent_id}' in parents"

        with httpx.Client(timeout=15.0) as client:
            response = client.get(
                f"{GoogleDriveService.DRIVE_API}/files",
                headers={"Authorization": f"Bearer {access_token}"},
                params={
                    "q": q,
                    "fields": "files(id,name)",
                    "spaces": "drive",
                    "orderBy": "name",
                },
            )

        if response.status_code != 200:
            logger.error(f"Drive list_folders failed: {response.status_code} — {response.text}")
            return []

        return response.json().get("files", [])

    @staticmethod
    def get_or_create_folder(access_token: str, name: str, parent_id: str = None) -> str:
        """Find folder by name, create if not found. Returns folder ID."""
        existing = GoogleDriveService.find_folder(access_token, name, parent_id)
        if existing:
            return existing["id"]
        created = GoogleDriveService.create_folder(access_token, name, parent_id)
        return created["id"]

    # =========================================================================
    # FILE UPLOAD
    # =========================================================================

    @staticmethod
    def upload_file_bytes(
        access_token: str,
        file_bytes: bytes,
        filename: str,
        mime_type: str,
        folder_id: str = None,
    ) -> Dict:
        """
        Upload a file to Drive using multipart upload.

        Uses /upload/drive/v3/files (NOT /drive/v3/files).
        """
        metadata = {"name": filename}
        if folder_id:
            metadata["parents"] = [folder_id]

        # Build multipart body
        boundary = "===export_boundary==="
        body = (
            f"--{boundary}\r\n"
            f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{json.dumps(metadata)}\r\n"
            f"--{boundary}\r\n"
            f"Content-Type: {mime_type}\r\n\r\n"
        ).encode() + file_bytes + f"\r\n--{boundary}--".encode()

        with httpx.Client(timeout=60.0) as client:
            response = client.post(
                f"{GoogleDriveService.UPLOAD_API}/files",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": f"multipart/related; boundary={boundary}",
                },
                params={"uploadType": "multipart", "fields": "id,name,webViewLink"},
                content=body,
            )

        if response.status_code not in (200, 201):
            raise Exception(f"Drive upload failed: {response.status_code} — {response.text[:200]}")

        return response.json()

    def upload_export_list(
        self,
        brand_id: str,
        organization_id: str,
        items: list,
        folder_id: str,
        progress_callback=None,
    ) -> Dict[str, Any]:
        """
        Upload all items from export list to a Drive folder.

        Args:
            brand_id: Brand ID for credential lookup
            organization_id: Organization ID (multi-tenant)
            items: Export list items (dicts with storage_path, etc.)
            folder_id: Target Drive folder ID
            progress_callback: Optional callable(current, total) for progress updates

        Returns:
            Dict with uploaded count, failed count, file links
        """
        import requests as req

        from viraltracker.ui.export_utils import get_signed_url, generate_structured_filename

        access_token, _ = self._get_credentials(brand_id, organization_id)

        uploaded = 0
        failed = 0
        links = []
        total = len(items)

        for idx, item in enumerate(items):
            storage_path = item.get("storage_path", "")
            if not storage_path:
                failed += 1
                continue

            url = get_signed_url(storage_path)
            if not url:
                failed += 1
                continue

            try:
                # Download from Supabase
                response = req.get(url, timeout=30)
                if response.status_code != 200:
                    failed += 1
                    continue

                # Detect mime type
                ct = response.headers.get('content-type', 'image/png')
                ext = item.get("ext", "png")
                if "jpeg" in ct:
                    ext = "jpg"
                    mime = "image/jpeg"
                elif "webp" in ct:
                    ext = "webp"
                    mime = "image/webp"
                else:
                    mime = "image/png"

                filename = generate_structured_filename(
                    brand_code=item.get("brand_code", "XX"),
                    product_code=item.get("product_code", "XX"),
                    run_id=item.get("run_id", "000000"),
                    ad_id=item.get("ad_id", "000000"),
                    format_code=item.get("format_code", "SQ"),
                    ext=ext,
                )

                result = self.upload_file_bytes(
                    access_token, response.content, filename, mime, folder_id
                )
                uploaded += 1
                links.append({
                    "filename": filename,
                    "id": result.get("id"),
                    "link": result.get("webViewLink"),
                })

            except Exception as e:
                logger.warning(f"Drive upload failed for {storage_path}: {e}")
                failed += 1

            if progress_callback:
                progress_callback(idx + 1, total)

        return {"uploaded": uploaded, "failed": failed, "total": total, "links": links}
