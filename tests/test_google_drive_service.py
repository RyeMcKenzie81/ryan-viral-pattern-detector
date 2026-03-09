"""Tests for GoogleDriveService — OAuth, folders, upload."""

import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _env_vars(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test-client-secret")


@pytest.fixture
def mock_supabase():
    with patch("viraltracker.core.database.get_supabase_client") as m:
        client = MagicMock()
        m.return_value = client
        yield client


@pytest.fixture
def service(mock_supabase):
    from viraltracker.services.google_drive_service import GoogleDriveService
    svc = GoogleDriveService()
    svc.supabase = mock_supabase
    return svc


# ---------------------------------------------------------------------------
# OAuth tests
# ---------------------------------------------------------------------------

class TestOAuth:
    def test_authorization_url_contains_drive_scope(self):
        from viraltracker.services.google_drive_service import GoogleDriveService
        url = GoogleDriveService.get_authorization_url(
            redirect_uri="http://localhost:8501/Ad_Export",
            state="test-state",
        )
        assert "drive" in url
        assert "test-client-id" in url
        assert "offline" in url
        assert "consent" in url

    def test_exchange_code_for_tokens(self):
        from viraltracker.services.google_drive_service import GoogleDriveService
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "at-123",
            "refresh_token": "rt-456",
            "expires_in": 3600,
        }

        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__ = MagicMock(return_value=MagicMock(post=MagicMock(return_value=mock_response)))
            mock_client.return_value.__exit__ = MagicMock(return_value=False)

            tokens = GoogleDriveService.exchange_code_for_tokens("auth-code", "http://localhost/callback")

        assert tokens["access_token"] == "at-123"
        assert tokens["refresh_token"] == "rt-456"

    def test_save_integration(self, service, mock_supabase):
        service.save_integration(
            brand_id="brand-1",
            organization_id="org-1",
            tokens={"access_token": "at", "refresh_token": "rt", "expires_in": 3600},
        )

        mock_supabase.table.assert_called_with("brand_integrations")
        upsert_call = mock_supabase.table.return_value.upsert
        upsert_call.assert_called_once()
        call_args = upsert_call.call_args[0][0]
        assert call_args["brand_id"] == "brand-1"
        assert call_args["platform"] == "google_drive"

    def test_is_connected_true(self, service, mock_supabase):
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[{"id": "row-1"}])
        assert service.is_connected("brand-1", "org-1") is True

    def test_is_connected_false(self, service, mock_supabase):
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
        assert service.is_connected("brand-1", "org-1") is False

    def test_disconnect(self, service, mock_supabase):
        service.disconnect("brand-1", "org-1")
        mock_supabase.table.assert_called_with("brand_integrations")
        mock_supabase.table.return_value.delete.assert_called_once()


# ---------------------------------------------------------------------------
# Token refresh via shared utils
# ---------------------------------------------------------------------------

class TestTokenRefresh:
    def test_get_credentials_refreshes_expired_token(self, service, mock_supabase):
        expired = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        config = {
            "access_token": "old-token",
            "refresh_token": "rt-123",
            "token_expiry": expired,
        }
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"config": config}]
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new-token",
            "expires_in": 3600,
        }

        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__ = MagicMock(return_value=MagicMock(post=MagicMock(return_value=mock_response)))
            mock_client.return_value.__exit__ = MagicMock(return_value=False)

            token, updated_config = service._get_credentials("brand-1", "org-1")

        assert token == "new-token"

    def test_get_credentials_uses_valid_token(self, service, mock_supabase):
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        config = {
            "access_token": "valid-token",
            "refresh_token": "rt-123",
            "token_expiry": future,
        }
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"config": config}]
        )

        token, _ = service._get_credentials("brand-1", "org-1")
        assert token == "valid-token"


# ---------------------------------------------------------------------------
# Folder operations
# ---------------------------------------------------------------------------

class TestFolders:
    def test_find_folder_escapes_quotes(self):
        from viraltracker.services.google_drive_service import GoogleDriveService
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"files": [{"id": "f1", "name": "Bob's Folder"}]}

        with patch("httpx.Client") as mock_client:
            mock_instance = MagicMock()
            mock_instance.get.return_value = mock_response
            mock_client.return_value.__enter__ = MagicMock(return_value=mock_instance)
            mock_client.return_value.__exit__ = MagicMock(return_value=False)

            result = GoogleDriveService.find_folder("token", "Bob's Folder")

        assert result["id"] == "f1"
        # Verify the query escaped the single quote
        call_params = mock_instance.get.call_args[1]["params"]
        assert "\\'" in call_params["q"]

    def test_create_folder(self):
        from viraltracker.services.google_drive_service import GoogleDriveService
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "new-folder-id", "name": "Test"}

        with patch("httpx.Client") as mock_client:
            mock_instance = MagicMock()
            mock_instance.post.return_value = mock_response
            mock_client.return_value.__enter__ = MagicMock(return_value=mock_instance)
            mock_client.return_value.__exit__ = MagicMock(return_value=False)

            result = GoogleDriveService.create_folder("token", "Test", parent_id="parent-1")

        assert result["id"] == "new-folder-id"
        # Verify parent was included in metadata
        posted_body = mock_instance.post.call_args[1]["content"]
        metadata = json.loads(posted_body)
        assert metadata["parents"] == ["parent-1"]

    def test_list_folders(self):
        from viraltracker.services.google_drive_service import GoogleDriveService
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "files": [
                {"id": "f1", "name": "Folder A"},
                {"id": "f2", "name": "Folder B"},
            ]
        }

        with patch("httpx.Client") as mock_client:
            mock_instance = MagicMock()
            mock_instance.get.return_value = mock_response
            mock_client.return_value.__enter__ = MagicMock(return_value=mock_instance)
            mock_client.return_value.__exit__ = MagicMock(return_value=False)

            result = GoogleDriveService.list_folders("token")

        assert len(result) == 2

    def test_get_or_create_folder_finds_existing(self):
        from viraltracker.services.google_drive_service import GoogleDriveService

        with patch.object(GoogleDriveService, "find_folder", return_value={"id": "existing-id", "name": "Test"}) as find_mock, \
             patch.object(GoogleDriveService, "create_folder") as create_mock:
            folder_id = GoogleDriveService.get_or_create_folder("token", "Test")

        assert folder_id == "existing-id"
        find_mock.assert_called_once()
        create_mock.assert_not_called()

    def test_get_or_create_folder_creates_new(self):
        from viraltracker.services.google_drive_service import GoogleDriveService

        with patch.object(GoogleDriveService, "find_folder", return_value=None) as find_mock, \
             patch.object(GoogleDriveService, "create_folder", return_value={"id": "new-id"}) as create_mock:
            folder_id = GoogleDriveService.get_or_create_folder("token", "Test")

        assert folder_id == "new-id"
        find_mock.assert_called_once()
        create_mock.assert_called_once()


# ---------------------------------------------------------------------------
# Pagination, search, folder info, URL resolution
# ---------------------------------------------------------------------------

class TestPagination:
    def test_list_folders_paginates(self):
        from viraltracker.services.google_drive_service import GoogleDriveService

        page1 = MagicMock()
        page1.status_code = 200
        page1.json.return_value = {
            "files": [{"id": "f1", "name": "A"}],
            "nextPageToken": "page2_token",
        }
        page2 = MagicMock()
        page2.status_code = 200
        page2.json.return_value = {
            "files": [{"id": "f2", "name": "B"}],
        }

        with patch("httpx.Client") as mock_client:
            mock_instance = MagicMock()
            mock_instance.get.side_effect = [page1, page2]
            mock_client.return_value.__enter__ = MagicMock(return_value=mock_instance)
            mock_client.return_value.__exit__ = MagicMock(return_value=False)

            result = GoogleDriveService.list_folders("token")

        assert len(result) == 2
        assert result[0]["id"] == "f1"
        assert result[1]["id"] == "f2"
        assert mock_instance.get.call_count == 2

    def test_list_folders_caps_at_max_results(self):
        from viraltracker.services.google_drive_service import GoogleDriveService

        page1 = MagicMock()
        page1.status_code = 200
        page1.json.return_value = {
            "files": [{"id": f"f{i}", "name": f"Folder {i}"} for i in range(5)],
            "nextPageToken": "more",
        }

        with patch("httpx.Client") as mock_client:
            mock_instance = MagicMock()
            mock_instance.get.return_value = page1
            mock_client.return_value.__enter__ = MagicMock(return_value=mock_instance)
            mock_client.return_value.__exit__ = MagicMock(return_value=False)

            result = GoogleDriveService.list_folders("token", max_results=3)

        assert len(result) == 3

    def test_list_folders_root_uses_root_in_parents(self):
        from viraltracker.services.google_drive_service import GoogleDriveService

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"files": []}

        with patch("httpx.Client") as mock_client:
            mock_instance = MagicMock()
            mock_instance.get.return_value = mock_response
            mock_client.return_value.__enter__ = MagicMock(return_value=mock_instance)
            mock_client.return_value.__exit__ = MagicMock(return_value=False)

            GoogleDriveService.list_folders("token")

        q = mock_instance.get.call_args[1]["params"]["q"]
        assert "'root' in parents" in q

    def test_list_folders_shared_with_me(self):
        from viraltracker.services.google_drive_service import GoogleDriveService

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"files": [{"id": "s1", "name": "Shared"}]}

        with patch("httpx.Client") as mock_client:
            mock_instance = MagicMock()
            mock_instance.get.return_value = mock_response
            mock_client.return_value.__enter__ = MagicMock(return_value=mock_instance)
            mock_client.return_value.__exit__ = MagicMock(return_value=False)

            result = GoogleDriveService.list_folders("token", shared_with_me=True)

        q = mock_instance.get.call_args[1]["params"]["q"]
        assert "sharedWithMe=true" in q
        assert len(result) == 1

    def test_list_folders_subfolder(self):
        from viraltracker.services.google_drive_service import GoogleDriveService

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"files": []}

        with patch("httpx.Client") as mock_client:
            mock_instance = MagicMock()
            mock_instance.get.return_value = mock_response
            mock_client.return_value.__enter__ = MagicMock(return_value=mock_instance)
            mock_client.return_value.__exit__ = MagicMock(return_value=False)

            GoogleDriveService.list_folders("token", parent_id="folder-xyz")

        q = mock_instance.get.call_args[1]["params"]["q"]
        assert "'folder-xyz' in parents" in q


class TestSearch:
    def test_search_folders_basic(self):
        from viraltracker.services.google_drive_service import GoogleDriveService

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "files": [{"id": "f1", "name": "Campaign Assets", "parents": ["p1"]}]
        }

        # Mock get_folder_info for parent resolution
        parent_info = {"id": "p1", "name": "Client A"}

        with patch("httpx.Client") as mock_client, \
             patch.object(GoogleDriveService, "get_folder_info", return_value=parent_info):
            mock_instance = MagicMock()
            mock_instance.get.return_value = mock_response
            mock_client.return_value.__enter__ = MagicMock(return_value=mock_instance)
            mock_client.return_value.__exit__ = MagicMock(return_value=False)

            result = GoogleDriveService.search_folders("token", "Campaign")

        assert len(result) == 1
        assert result[0]["name"] == "Campaign Assets"
        assert result[0]["parent_name"] == "Client A"
        q = mock_instance.get.call_args[1]["params"]["q"]
        assert "name contains 'Campaign'" in q

    def test_search_folders_escapes_quotes(self):
        from viraltracker.services.google_drive_service import GoogleDriveService

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"files": []}

        with patch("httpx.Client") as mock_client:
            mock_instance = MagicMock()
            mock_instance.get.return_value = mock_response
            mock_client.return_value.__enter__ = MagicMock(return_value=mock_instance)
            mock_client.return_value.__exit__ = MagicMock(return_value=False)

            GoogleDriveService.search_folders("token", "Bob's Folder")

        q = mock_instance.get.call_args[1]["params"]["q"]
        assert "\\'" in q


class TestFolderInfo:
    def test_get_folder_info_success(self):
        from viraltracker.services.google_drive_service import GoogleDriveService

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "folder-1",
            "name": "My Folder",
            "parents": ["root"],
            "capabilities": {"canAddChildren": True},
        }

        with patch("httpx.Client") as mock_client:
            mock_instance = MagicMock()
            mock_instance.get.return_value = mock_response
            mock_client.return_value.__enter__ = MagicMock(return_value=mock_instance)
            mock_client.return_value.__exit__ = MagicMock(return_value=False)

            result = GoogleDriveService.get_folder_info("token", "folder-1")

        assert result["name"] == "My Folder"
        assert result["capabilities"]["canAddChildren"] is True
        # Verify supportsAllDrives param
        params = mock_instance.get.call_args[1]["params"]
        assert params["supportsAllDrives"] == "true"

    def test_get_folder_info_not_found(self):
        from viraltracker.services.google_drive_service import GoogleDriveService

        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("httpx.Client") as mock_client:
            mock_instance = MagicMock()
            mock_instance.get.return_value = mock_response
            mock_client.return_value.__enter__ = MagicMock(return_value=mock_instance)
            mock_client.return_value.__exit__ = MagicMock(return_value=False)

            result = GoogleDriveService.get_folder_info("token", "nonexistent")

        assert result is None


class TestResolveUrl:
    def test_standard_url(self):
        from viraltracker.services.google_drive_service import GoogleDriveService

        info = {"id": "abc123", "name": "Ads", "capabilities": {"canAddChildren": True}}

        with patch.object(GoogleDriveService, "get_folder_info", return_value=info):
            result = GoogleDriveService.resolve_folder_url(
                "token", "https://drive.google.com/drive/folders/abc123"
            )

        assert result["id"] == "abc123"
        assert result["name"] == "Ads"
        assert result["can_write"] is True

    def test_url_with_account_selector(self):
        from viraltracker.services.google_drive_service import GoogleDriveService

        info = {"id": "xyz789", "name": "Shared", "capabilities": {"canAddChildren": False}}

        with patch.object(GoogleDriveService, "get_folder_info", return_value=info):
            result = GoogleDriveService.resolve_folder_url(
                "token", "https://drive.google.com/drive/u/0/folders/xyz789"
            )

        assert result["id"] == "xyz789"
        assert result["can_write"] is False

    def test_url_with_query_params(self):
        from viraltracker.services.google_drive_service import GoogleDriveService

        info = {"id": "def456", "name": "Campaign", "capabilities": {"canAddChildren": True}}

        with patch.object(GoogleDriveService, "get_folder_info", return_value=info):
            result = GoogleDriveService.resolve_folder_url(
                "token", "https://drive.google.com/drive/folders/def456?usp=sharing"
            )

        assert result["id"] == "def456"

    def test_legacy_open_url(self):
        from viraltracker.services.google_drive_service import GoogleDriveService

        info = {"id": "leg123", "name": "Old Link", "capabilities": {"canAddChildren": True}}

        with patch.object(GoogleDriveService, "get_folder_info", return_value=info):
            result = GoogleDriveService.resolve_folder_url(
                "token", "https://drive.google.com/open?id=leg123"
            )

        assert result["id"] == "leg123"

    def test_invalid_url(self):
        from viraltracker.services.google_drive_service import GoogleDriveService

        result = GoogleDriveService.resolve_folder_url("token", "https://example.com/not-drive")
        assert result is None

    def test_folder_not_found(self):
        from viraltracker.services.google_drive_service import GoogleDriveService

        with patch.object(GoogleDriveService, "get_folder_info", return_value=None):
            result = GoogleDriveService.resolve_folder_url(
                "token", "https://drive.google.com/drive/folders/gone123"
            )

        assert result is None


# ---------------------------------------------------------------------------
# File upload
# ---------------------------------------------------------------------------

class TestUpload:
    def test_upload_file_bytes_uses_upload_api(self):
        from viraltracker.services.google_drive_service import GoogleDriveService
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "file-1", "name": "test.png", "webViewLink": "https://..."}

        with patch("httpx.Client") as mock_client:
            mock_instance = MagicMock()
            mock_instance.post.return_value = mock_response
            mock_client.return_value.__enter__ = MagicMock(return_value=mock_instance)
            mock_client.return_value.__exit__ = MagicMock(return_value=False)

            result = GoogleDriveService.upload_file_bytes(
                "token", b"image-data", "test.png", "image/png", "folder-1"
            )

        assert result["id"] == "file-1"
        # Verify it used the upload API endpoint (not /drive/v3/files)
        call_url = mock_instance.post.call_args[0][0]
        assert "/upload/drive/v3/files" in call_url
        # Verify multipart upload type
        call_params = mock_instance.post.call_args[1]["params"]
        assert call_params["uploadType"] == "multipart"


# ---------------------------------------------------------------------------
# Multi-tenant
# ---------------------------------------------------------------------------

class TestMultiTenant:
    def test_get_credentials_filters_by_org_id(self, service, mock_supabase):
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        config = {
            "access_token": "valid-token",
            "refresh_token": "rt-123",
            "token_expiry": future,
        }
        # Set up the chain mock
        chain = mock_supabase.table.return_value.select.return_value
        eq1 = chain.eq.return_value  # brand_id
        eq2 = eq1.eq.return_value    # platform
        eq3 = eq2.eq.return_value    # organization_id
        eq3.limit.return_value.execute.return_value = MagicMock(data=[{"config": config}])

        service._get_credentials("brand-1", "org-1")

        # Verify all 3 eq() calls were made (brand_id, platform, organization_id)
        calls = chain.eq.call_args_list + eq1.eq.call_args_list + eq2.eq.call_args_list
        eq_fields = [c[0][0] for c in calls]
        assert "brand_id" in eq_fields
        assert "platform" in eq_fields
        assert "organization_id" in eq_fields


# ---------------------------------------------------------------------------
# Shared OAuth utils
# ---------------------------------------------------------------------------

class TestSharedOAuthUtils:
    def test_encode_decode_roundtrip(self):
        from viraltracker.services.google_oauth_utils import encode_oauth_state, decode_oauth_state
        state = encode_oauth_state("brand-1", "org-1", "nonce-abc", extra_field="val")
        decoded = decode_oauth_state(state)
        assert decoded["brand_id"] == "brand-1"
        assert decoded["org_id"] == "org-1"
        assert decoded["nonce"] == "nonce-abc"
        assert decoded["extra_field"] == "val"

    def test_refresh_token_valid(self):
        from viraltracker.services.google_oauth_utils import refresh_google_token
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        config = {"access_token": "valid", "token_expiry": future}
        result = refresh_google_token(config)
        assert result["access_token"] == "valid"

    def test_refresh_token_expired(self):
        from viraltracker.services.google_oauth_utils import refresh_google_token
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        config = {"access_token": "old", "refresh_token": "rt", "token_expiry": past}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"access_token": "new", "expires_in": 3600}

        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__ = MagicMock(return_value=MagicMock(post=MagicMock(return_value=mock_response)))
            mock_client.return_value.__exit__ = MagicMock(return_value=False)

            result = refresh_google_token(config)

        assert result["access_token"] == "new"

    def test_refresh_no_refresh_token(self):
        from viraltracker.services.google_oauth_utils import refresh_google_token
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        config = {"access_token": "old", "token_expiry": past}
        result = refresh_google_token(config)
        assert result is None
