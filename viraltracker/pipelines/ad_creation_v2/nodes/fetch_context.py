"""
FetchContextNode - Fetch product, persona, variant, hooks, and brief data.
"""

import logging
from dataclasses import dataclass
from typing import ClassVar
from uuid import UUID

from pydantic_graph import BaseNode, GraphRunContext

from ..state import AdCreationPipelineState
from ....agent.dependencies import AgentDependencies
from ...metadata import NodeMetadata

logger = logging.getLogger(__name__)


@dataclass
class FetchContextNode(BaseNode[AdCreationPipelineState]):
    """
    Step 2: Fetch all context data needed for ad generation.

    Fetches product data, persona, variant, offer variant, brand fonts,
    hooks (if hooks mode), and ad brief template.

    Reads: product_id, persona_id, variant_id, offer_variant_id,
           content_source, additional_instructions
    Writes: product_dict, persona_data, hooks_list, ad_brief_instructions
    Services: AdCreationService.get_product(), .get_hooks(), .get_ad_brief_template(),
              .get_persona_for_ad_generation()
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        inputs=["product_id", "persona_id", "variant_id", "offer_variant_id", "content_source"],
        outputs=["product_dict", "persona_data", "hooks_list", "ad_brief_instructions"],
        services=["ad_creation.get_product", "ad_creation.get_hooks",
                   "ad_creation.get_ad_brief_template", "ad_creation.get_persona_for_ad_generation"],
    )

    async def run(
        self,
        ctx: GraphRunContext[AdCreationPipelineState, AgentDependencies]
    ) -> "AnalyzeTemplateNode":
        from .analyze_template import AnalyzeTemplateNode

        logger.info("Step 2: Fetching context data...")
        ctx.state.current_step = "fetch_context"

        try:
            product_uuid = UUID(ctx.state.product_id)

            # Fetch product data
            product = await ctx.deps.ad_creation.get_product(product_uuid)
            product_dict = product.model_dump() if hasattr(product, 'model_dump') else dict(product)
            logger.info(f"Loaded product: {product_dict.get('name', 'Unknown')}")

            # Fetch persona data (optional)
            persona_data = None
            if ctx.state.persona_id:
                try:
                    persona_data = ctx.deps.ad_creation.get_persona_for_ad_generation(
                        UUID(ctx.state.persona_id)
                    )
                    if persona_data:
                        logger.info(f"Loaded persona: {persona_data.get('persona_name', 'Unknown')}")
                    else:
                        logger.warning(f"Persona not found: {ctx.state.persona_id}")
                except Exception as e:
                    logger.warning(f"Failed to load persona {ctx.state.persona_id}: {e}")
            ctx.state.persona_data = persona_data

            # Fetch variant data (optional)
            if ctx.state.variant_id:
                try:
                    from viraltracker.core.database import get_supabase_client
                    db = get_supabase_client()
                    result = db.table("product_variants").select(
                        "id, name, slug, variant_type, description, differentiators"
                    ).eq("id", ctx.state.variant_id).single().execute()
                    if result.data:
                        variant_data = result.data
                        product_dict['variant'] = variant_data
                        original_name = product_dict.get('name', 'Product')
                        variant_name = variant_data.get('name', '')
                        product_dict['display_name'] = f"{original_name} - {variant_name}" if variant_name else original_name
                        logger.info(f"Enhanced product with variant: {product_dict['display_name']}")
                    else:
                        product_dict['variant'] = None
                        product_dict['display_name'] = product_dict.get('name', 'Product')
                except Exception as e:
                    logger.warning(f"Failed to load variant {ctx.state.variant_id}: {e}")
                    product_dict['variant'] = None
                    product_dict['display_name'] = product_dict.get('name', 'Product')
            else:
                product_dict['variant'] = None
                product_dict['display_name'] = product_dict.get('name', 'Product')

            # Fetch offer variant data (optional)
            if ctx.state.offer_variant_id:
                try:
                    from viraltracker.services.product_offer_variant_service import ProductOfferVariantService
                    offer_variant_service = ProductOfferVariantService()
                    offer_variant_data = offer_variant_service.get_offer_variant(
                        UUID(ctx.state.offer_variant_id)
                    )
                    if offer_variant_data:
                        product_dict['offer_variant'] = offer_variant_data
                        if offer_variant_data.get('pain_points'):
                            product_dict['offer_pain_points'] = offer_variant_data['pain_points']
                        if offer_variant_data.get('benefits'):
                            product_dict['offer_benefits'] = offer_variant_data['benefits']
                        if offer_variant_data.get('target_audience'):
                            product_dict['offer_target_audience'] = offer_variant_data['target_audience']
                        if offer_variant_data.get('landing_page_url'):
                            product_dict['offer_landing_page_url'] = offer_variant_data['landing_page_url']
                        logger.info(f"Loaded offer variant: {offer_variant_data.get('name', 'Unknown')}")
                    else:
                        product_dict['offer_variant'] = None
                except Exception as e:
                    logger.warning(f"Failed to load offer variant {ctx.state.offer_variant_id}: {e}")
                    product_dict['offer_variant'] = None
            else:
                product_dict['offer_variant'] = None

            # Fetch brand fonts
            brand_id = product_dict.get('brand_id')
            if brand_id:
                try:
                    from viraltracker.core.database import get_supabase_client
                    db = get_supabase_client()
                    brand_result = db.table("brands").select("brand_fonts").eq("id", brand_id).single().execute()
                    if brand_result.data and brand_result.data.get('brand_fonts'):
                        ctx.state.brand_fonts = brand_result.data['brand_fonts']
                        logger.info(f"Loaded brand fonts: {ctx.state.brand_fonts.get('primary', 'N/A')}")
                except Exception as e:
                    logger.warning(f"Failed to load brand fonts: {e}")

            # Phase 3: Fetch template elements + brand assets (non-fatal)
            if ctx.state.template_id:
                # A. Fetch template elements using element_detection_version to distinguish
                #    None (never ran) from {} (ran but found nothing)
                try:
                    from viraltracker.core.database import get_supabase_client as _get_db
                    _db = _get_db()
                    te_result = _db.table("scraped_templates").select(
                        "template_elements, element_detection_version"
                    ).eq("id", ctx.state.template_id).execute()

                    if te_result.data:
                        row = te_result.data[0]
                        if row.get("element_detection_version") is not None:
                            # Detection has run — use elements (may be {} if nothing detected)
                            ctx.state.template_elements = row.get("template_elements") or {}
                        else:
                            # Detection never ran
                            ctx.state.template_elements = None
                    else:
                        ctx.state.template_elements = None

                    # If detection has run, get informational asset match against all images
                    if ctx.state.template_elements is not None:
                        try:
                            from viraltracker.services.template_element_service import TemplateElementService
                            tes = TemplateElementService()
                            match_result = tes.match_assets_to_template(
                                ctx.state.template_id, ctx.state.product_id
                            )
                            ctx.state.asset_match_result = match_result
                            logger.info(f"Asset match (all images): score={match_result.get('asset_match_score', 'N/A')}")
                        except Exception as e:
                            logger.warning(f"Asset match failed (non-fatal): {e}")

                    logger.info(f"Template elements: {'loaded' if ctx.state.template_elements is not None else 'no detection'}")
                except Exception as e:
                    logger.warning(f"Failed to fetch template elements (non-fatal): {e}")

                # B. Fetch brand assets (logo/badge)
                if brand_id:
                    try:
                        from viraltracker.core.database import get_supabase_client as _get_db2
                        _db2 = _get_db2()
                        ba_result = _db2.table("brand_assets").select(
                            "asset_type, storage_path"
                        ).eq("brand_id", brand_id).execute()

                        has_logo = False
                        logo_path = None
                        has_badge = False
                        for asset in (ba_result.data or []):
                            asset_type = (asset.get("asset_type") or "").lower()
                            if "logo" in asset_type:
                                has_logo = True
                                logo_path = asset.get("storage_path")
                            if "badge" in asset_type:
                                has_badge = True

                        ctx.state.brand_asset_info = {
                            "has_logo": has_logo,
                            "logo_path": logo_path,
                            "has_badge": has_badge,
                        }
                        logger.info(f"Brand assets: logo={has_logo}, badge={has_badge}")
                    except Exception as e:
                        logger.warning(f"Failed to fetch brand assets (non-fatal): {e}")

            # Build combined instructions
            combined_instructions = ""
            if ctx.state.additional_instructions:
                combined_instructions = ctx.state.additional_instructions
            product_dict['combined_instructions'] = combined_instructions if combined_instructions else None

            # Fetch hooks (only if hooks mode)
            hooks_list = []
            if ctx.state.content_source == "hooks":
                logger.info("Fetching hooks...")
                hooks = await ctx.deps.ad_creation.get_hooks(
                    product_id=product_uuid,
                    limit=50,
                    active_only=True
                )
                hooks_list = [h.model_dump() if hasattr(h, 'model_dump') else dict(h) for h in hooks]
                logger.info(f"Loaded {len(hooks_list)} hooks")
            else:
                logger.info(f"Skipping hooks (using {ctx.state.content_source} mode)")
            ctx.state.hooks_list = hooks_list

            # Fetch ad brief template
            brand_uuid = brand_id if isinstance(brand_id, UUID) else (UUID(brand_id) if brand_id else None)
            ad_brief = await ctx.deps.ad_creation.get_ad_brief_template(brand_id=brand_uuid)
            ad_brief_dict = ad_brief.model_dump() if hasattr(ad_brief, 'model_dump') else dict(ad_brief)
            ctx.state.ad_brief_instructions = ad_brief_dict.get('instructions', '')
            logger.info("Ad brief template loaded")

            ctx.state.product_dict = product_dict
            ctx.state.mark_step_complete("fetch_context")

            return AnalyzeTemplateNode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.error_step = "fetch_context"
            logger.error(f"Fetch context failed: {e}")

            # Mark ad run as failed if we have an ID
            if ctx.state.ad_run_id:
                try:
                    await ctx.deps.ad_creation.update_ad_run(
                        ad_run_id=UUID(ctx.state.ad_run_id),
                        status="failed",
                        error_message=str(e)
                    )
                except Exception:
                    pass

            raise
