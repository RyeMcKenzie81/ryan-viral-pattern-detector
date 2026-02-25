"""
Chainlit authentication adapter using Supabase.

Authenticates users via Supabase email/password and resolves their organization.
"""

import logging
from typing import Optional

import chainlit as cl

logger = logging.getLogger(__name__)


async def authenticate(username: str, password: str) -> Optional[cl.User]:
    """
    Authenticate a user via Supabase email/password.

    Args:
        username: User email address
        password: User password

    Returns:
        cl.User on success with user_id and org_id in metadata, None on failure.
    """
    try:
        from viraltracker.core.database import get_anon_client, get_supabase_client

        # Sign in with Supabase auth (anon client for RLS-enforced auth)
        client = get_anon_client()
        response = client.auth.sign_in_with_password({
            "email": username,
            "password": password,
        })

        if not response or not response.user:
            return None

        user_id = response.user.id
        email = response.user.email

        # Look up the user's organization using the service client (bypasses RLS)
        service_client = get_supabase_client()
        org_result = (
            service_client.table("user_organizations")
            .select("organization_id")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )

        org_id = None
        if org_result.data:
            org_id = org_result.data[0]["organization_id"]

        logger.info(f"Chainlit auth success: {email} (org: {org_id})")
        return cl.User(
            identifier=email,
            metadata={
                "user_id": user_id,
                "org_id": org_id,
            },
        )

    except Exception as e:
        error_msg = str(e)
        if "Invalid login credentials" in error_msg:
            logger.info(f"Chainlit auth failed: invalid credentials for {username}")
        else:
            logger.warning(f"Chainlit auth error: {e}")
        return None
