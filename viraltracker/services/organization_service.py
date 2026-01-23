"""
Organization Service - Multi-Tenant Organization Management

Provides CRUD operations for organizations and user memberships.

Usage:
    from viraltracker.services.organization_service import OrganizationService
    from viraltracker.core.database import get_supabase_client

    service = OrganizationService(get_supabase_client())
    orgs = service.get_user_organizations(user_id)
"""

from typing import List, Optional
import logging

from supabase import Client

logger = logging.getLogger(__name__)


class OrganizationService:
    """Service for organization/tenant operations."""

    def __init__(self, supabase_client: Client):
        """
        Initialize OrganizationService.

        Args:
            supabase_client: Supabase client instance
        """
        self.client = supabase_client

    def get_user_organizations(self, user_id: str) -> List[dict]:
        """
        Get all organizations a user belongs to.

        Args:
            user_id: The user's ID

        Returns:
            List of organizations with membership info. Each item contains:
            - role: User's role in the organization
            - organization: Dict with id, name, slug, owner_user_id
        """
        result = self.client.table("user_organizations").select(
            "role, organization:organizations(id, name, slug, owner_user_id)"
        ).eq("user_id", user_id).execute()
        return result.data or []

    def get_organization(self, org_id: str) -> Optional[dict]:
        """
        Get organization by ID.

        Args:
            org_id: Organization ID

        Returns:
            Organization dict or None if not found
        """
        result = self.client.table("organizations").select("*").eq(
            "id", org_id
        ).single().execute()
        return result.data

    def get_user_role(self, user_id: str, org_id: str) -> Optional[str]:
        """
        Get user's role in an organization.

        Args:
            user_id: User ID
            org_id: Organization ID

        Returns:
            Role string ('owner', 'admin', 'member', 'viewer') or None if not a member
        """
        result = self.client.table("user_organizations").select("role").eq(
            "user_id", user_id
        ).eq("organization_id", org_id).single().execute()
        return result.data.get("role") if result.data else None

    def create_organization(self, name: str, owner_id: str) -> dict:
        """
        Create a new organization with owner.

        Args:
            name: Organization name
            owner_id: User ID of the owner

        Returns:
            Created organization dict
        """
        # Create organization
        org_result = self.client.table("organizations").insert({
            "name": name,
            "owner_user_id": owner_id
        }).execute()
        org = org_result.data[0]

        # Add owner membership
        self.client.table("user_organizations").insert({
            "user_id": owner_id,
            "organization_id": org["id"],
            "role": "owner"
        }).execute()

        logger.info(f"Created organization: {name} for user {owner_id}")
        return org

    def add_member(
        self,
        org_id: str,
        user_id: str,
        role: str = "member"
    ) -> dict:
        """
        Add a user to an organization.

        Args:
            org_id: Organization ID
            user_id: User ID to add
            role: Role to assign (default: 'member')

        Returns:
            Created membership dict
        """
        result = self.client.table("user_organizations").insert({
            "organization_id": org_id,
            "user_id": user_id,
            "role": role
        }).execute()
        logger.info(f"Added user {user_id} to org {org_id} as {role}")
        return result.data[0]

    def remove_member(self, org_id: str, user_id: str) -> bool:
        """
        Remove a user from an organization.

        Args:
            org_id: Organization ID
            user_id: User ID to remove

        Returns:
            True if removed successfully
        """
        self.client.table("user_organizations").delete().eq(
            "organization_id", org_id
        ).eq("user_id", user_id).execute()
        logger.info(f"Removed user {user_id} from org {org_id}")
        return True

    def update_member_role(
        self,
        org_id: str,
        user_id: str,
        new_role: str
    ) -> dict:
        """
        Update a user's role in an organization.

        Args:
            org_id: Organization ID
            user_id: User ID
            new_role: New role to assign

        Returns:
            Updated membership dict
        """
        result = self.client.table("user_organizations").update({
            "role": new_role
        }).eq("organization_id", org_id).eq("user_id", user_id).execute()
        logger.info(f"Updated user {user_id} role to {new_role} in org {org_id}")
        return result.data[0]
