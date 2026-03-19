"""Klaviyo Email Marketing Specialist Agent"""

import json
import logging
from typing import Dict, List, Optional

from pydantic_ai import Agent, RunContext

from ..dependencies import AgentDependencies

logger = logging.getLogger(__name__)

from ...core.config import Config

klaviyo_agent = Agent(
    model=Config.get_model("orchestrator"),
    deps_type=AgentDependencies,
    system_prompt="""You are the Klaviyo email marketing specialist agent.

Your responsibilities include:
- Managing Klaviyo email campaigns (list, create, schedule, send)
- Managing automation flows (list, create from template, update status)
- Viewing email marketing analytics (campaign metrics, flow metrics)
- Managing lists and segments

**Important:**
- All operations require a connected Klaviyo account for the brand
- Flow creation is limited to 100/day (Klaviyo API constraint)
- Provide clear summaries of campaign and flow performance
- Include key metrics: open rate, click rate, revenue

**Available Services:**
- KlaviyoService: For all Klaviyo API operations
"""
)


# ============================================================================
# Campaigns
# ============================================================================

@klaviyo_agent.tool(
    metadata={
        "category": "Integration",
        "platform": "Klaviyo",
        "rate_limit": "API-dependent",
        "use_cases": ["List Klaviyo campaigns", "Show email campaigns"],
        "examples": ["Show me all email campaigns for Savage"],
    }
)
async def list_campaigns(
    ctx: RunContext[AgentDependencies],
    brand_id: str,
    status: Optional[str] = None,
) -> str:
    """List all email campaigns for a brand's Klaviyo account.

    Args:
        brand_id: Brand UUID.
        status: Optional status filter (draft, scheduled, sending, sent).
    """
    try:
        org_id = getattr(ctx.deps, "organization_id", "all") or "all"
        campaigns = ctx.deps.klaviyo.get_campaigns(brand_id, org_id, filter_status=status)
        return json.dumps({"success": True, "campaigns": campaigns, "count": len(campaigns)})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


@klaviyo_agent.tool(
    metadata={
        "category": "Integration",
        "platform": "Klaviyo",
        "rate_limit": "M tier",
        "use_cases": ["Create email campaign", "Set up a new email blast"],
        "examples": ["Create a campaign called Spring Sale targeting the VIP list"],
    }
)
async def create_campaign(
    ctx: RunContext[AgentDependencies],
    brand_id: str,
    name: str,
    audience_type: str,
    audience_id: str,
) -> str:
    """Create a new email campaign.

    Args:
        brand_id: Brand UUID.
        name: Campaign name.
        audience_type: 'list' or 'segment'.
        audience_id: Klaviyo list or segment ID.
    """
    try:
        org_id = getattr(ctx.deps, "organization_id", "all") or "all"
        audiences = {"included": [{"type": audience_type, "id": audience_id}]}
        result = ctx.deps.klaviyo.create_campaign(brand_id, org_id, name, audiences)
        return json.dumps({"success": True, "campaign": result})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


@klaviyo_agent.tool(
    metadata={
        "category": "Integration",
        "platform": "Klaviyo",
        "rate_limit": "M tier",
        "use_cases": ["Send campaign", "Schedule email"],
        "examples": ["Send the Spring Sale campaign now"],
    }
)
async def send_campaign(
    ctx: RunContext[AgentDependencies],
    brand_id: str,
    campaign_id: str,
    scheduled_at: Optional[str] = None,
) -> str:
    """Send or schedule a campaign.

    Args:
        brand_id: Brand UUID.
        campaign_id: Klaviyo campaign ID.
        scheduled_at: Optional ISO8601 datetime for scheduling.
    """
    try:
        org_id = getattr(ctx.deps, "organization_id", "all") or "all"
        result = ctx.deps.klaviyo.send_campaign(
            brand_id, org_id, campaign_id, scheduled_at=scheduled_at
        )
        return json.dumps({"success": True, "job": result})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


# ============================================================================
# Flows
# ============================================================================

@klaviyo_agent.tool(
    metadata={
        "category": "Integration",
        "platform": "Klaviyo",
        "rate_limit": "XS tier",
        "use_cases": ["List automation flows", "Show active flows"],
        "examples": ["What flows are active for Savage?"],
    }
)
async def list_flows(
    ctx: RunContext[AgentDependencies],
    brand_id: str,
) -> str:
    """List all automation flows for a brand."""
    try:
        org_id = getattr(ctx.deps, "organization_id", "all") or "all"
        flows = ctx.deps.klaviyo.get_flows(brand_id, org_id)
        return json.dumps({"success": True, "flows": flows, "count": len(flows)})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


@klaviyo_agent.tool(
    metadata={
        "category": "Integration",
        "platform": "Klaviyo",
        "rate_limit": "XS tier (100/day)",
        "use_cases": ["Create post-purchase flow", "Set up welcome series"],
        "examples": ["Create a post-purchase flow for Savage"],
    }
)
async def create_flow(
    ctx: RunContext[AgentDependencies],
    brand_id: str,
    template_name: str,
    template_ids: List[str],
    delays: Optional[List[int]] = None,
    brand_name: str = "",
    flow_name: str = "",
) -> str:
    """Create a flow from a pre-built template.

    Args:
        brand_id: Brand UUID.
        template_name: Template type (post_purchase, welcome_series, abandoned_cart, winback).
        template_ids: List of Klaviyo template IDs for each email step.
        delays: Optional delay values (days or hours depending on template).
        brand_name: Brand name for personalization.
        flow_name: Custom flow name.
    """
    try:
        org_id = getattr(ctx.deps, "organization_id", "all") or "all"
        config = {
            "template_ids": template_ids,
            "delays": delays,
            "brand_name": brand_name,
            "flow_name": flow_name,
        }
        result = ctx.deps.klaviyo.create_flow_from_template(brand_id, org_id, template_name, config)
        return json.dumps({"success": True, "flow": result})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


@klaviyo_agent.tool(
    metadata={
        "category": "Integration",
        "platform": "Klaviyo",
        "rate_limit": "XS tier",
        "use_cases": ["Activate flow", "Pause flow", "Set flow to draft"],
        "examples": ["Make the post-purchase flow live"],
    }
)
async def update_flow_status(
    ctx: RunContext[AgentDependencies],
    brand_id: str,
    flow_id: str,
    status: str,
) -> str:
    """Update a flow's status (draft, manual, live).

    Args:
        brand_id: Brand UUID.
        flow_id: Klaviyo flow ID.
        status: New status (draft, manual, live).
    """
    try:
        org_id = getattr(ctx.deps, "organization_id", "all") or "all"
        result = ctx.deps.klaviyo.update_flow_status(brand_id, org_id, flow_id, status)
        return json.dumps({"success": True, "flow": result})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


# ============================================================================
# Analytics
# ============================================================================

@klaviyo_agent.tool(
    metadata={
        "category": "Analytics",
        "platform": "Klaviyo",
        "rate_limit": "S tier",
        "use_cases": ["Campaign performance", "Email marketing metrics"],
        "examples": ["How are our email campaigns performing?"],
    }
)
async def get_campaign_metrics(
    ctx: RunContext[AgentDependencies],
    brand_id: str,
    timeframe: str = "last_30_days",
) -> str:
    """Get campaign performance metrics.

    Args:
        brand_id: Brand UUID.
        timeframe: Time range (last_7_days, last_14_days, last_30_days, last_90_days).
    """
    try:
        org_id = getattr(ctx.deps, "organization_id", "all") or "all"
        campaigns = ctx.deps.klaviyo.get_campaigns(brand_id, org_id)
        if not campaigns:
            return json.dumps({"success": True, "metrics": [], "message": "No campaigns found"})
        campaign_ids = [c["id"] for c in campaigns if c.get("id")]
        metrics = ctx.deps.klaviyo.get_campaign_metrics(brand_id, org_id, campaign_ids, timeframe)
        return json.dumps({"success": True, "metrics": metrics, "count": len(metrics)})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


@klaviyo_agent.tool(
    metadata={
        "category": "Analytics",
        "platform": "Klaviyo",
        "rate_limit": "S tier",
        "use_cases": ["Flow performance", "Automation metrics"],
        "examples": ["How is the welcome series performing?"],
    }
)
async def get_flow_metrics(
    ctx: RunContext[AgentDependencies],
    brand_id: str,
    timeframe: str = "last_30_days",
) -> str:
    """Get flow performance metrics.

    Args:
        brand_id: Brand UUID.
        timeframe: Time range (last_7_days, last_14_days, last_30_days, last_90_days).
    """
    try:
        org_id = getattr(ctx.deps, "organization_id", "all") or "all"
        flows = ctx.deps.klaviyo.get_flows(brand_id, org_id)
        if not flows:
            return json.dumps({"success": True, "metrics": [], "message": "No flows found"})
        flow_ids = [f["id"] for f in flows if f.get("id")]
        metrics = ctx.deps.klaviyo.get_flow_metrics(brand_id, org_id, flow_ids, timeframe)
        return json.dumps({"success": True, "metrics": metrics, "count": len(metrics)})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


# ============================================================================
# Lists & Segments
# ============================================================================

@klaviyo_agent.tool(
    metadata={
        "category": "Integration",
        "platform": "Klaviyo",
        "rate_limit": "L tier",
        "use_cases": ["List mailing lists", "Show subscriber lists"],
        "examples": ["What lists does Savage have in Klaviyo?"],
    }
)
async def list_lists(
    ctx: RunContext[AgentDependencies],
    brand_id: str,
) -> str:
    """List all mailing lists for a brand."""
    try:
        org_id = getattr(ctx.deps, "organization_id", "all") or "all"
        lists = ctx.deps.klaviyo.get_lists(brand_id, org_id)
        return json.dumps({"success": True, "lists": lists, "count": len(lists)})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


@klaviyo_agent.tool(
    metadata={
        "category": "Integration",
        "platform": "Klaviyo",
        "rate_limit": "L tier",
        "use_cases": ["List segments", "Show audience segments"],
        "examples": ["What segments are defined in Klaviyo?"],
    }
)
async def list_segments(
    ctx: RunContext[AgentDependencies],
    brand_id: str,
) -> str:
    """List all segments for a brand."""
    try:
        org_id = getattr(ctx.deps, "organization_id", "all") or "all"
        segments = ctx.deps.klaviyo.get_segments(brand_id, org_id)
        return json.dumps({"success": True, "segments": segments, "count": len(segments)})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


logger.info("Klaviyo Agent initialized with 10 tools")
