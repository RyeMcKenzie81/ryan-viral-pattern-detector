"""
Generate Angles — Strategy-first angle generation for the angle-driven ad creator.

Pairs with Ad Creator V2 (21b). Workflow:
  1. Select brand → product → persona → (optional) offer variant
  2. Click "Generate Angles" → AngleGeneratorService produces N=5 angles via Claude Opus 4.7
  3. Review/edit each angle inline
  4. Save the rows you want; angles persist to belief_angles
  5. "Continue to AC2" deep-links to Ad Creator V2 with the saved angles pre-selected

This page is the entry point for the "lead with strategy" workflow. The angle
becomes the top-level entity; downstream hook generation in AC2 works against
the saved belief. Performance flows back via generated_ads.angle_id +
hook_embedding for the 30-day cross-angle similarity report (PLAN.md P4).

Design source: docs/plans/angle-driven-ad-creator/PLAN.md (Step 5a, decision 1E)
"""

import streamlit as st
from typing import Any, Dict, List, Optional
from uuid import UUID

st.set_page_config(
    page_title="Generate Angles",
    page_icon="🎯",
    layout="wide",
)

from viraltracker.ui.auth import require_auth
require_auth()
from viraltracker.ui.utils import render_brand_selector, require_feature
require_feature("generate_angles", "Generate Angles")


# ============================================
# SERVICE HELPERS (lazy-loaded)
# ============================================

def get_angle_generator_service():
    from viraltracker.services.angle_generator_service import AngleGeneratorService
    return AngleGeneratorService()


def get_supabase():
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()


def get_personas_for_product(product_id: str) -> List[Dict[str, Any]]:
    """Return list of persona dicts for the product (mirrors AC2's pattern)."""
    from viraltracker.services.persona_service import PersonaService
    service = PersonaService()
    summaries = service.get_personas_for_product(UUID(product_id))
    return [
        {
            "id": str(p.id),
            "name": p.name,
            "is_primary": getattr(p, "is_primary", False),
        }
        for p in summaries
    ]


def get_offer_variants_for_product(product_id: str) -> List[Dict[str, Any]]:
    """Return active offer variants for the product (mirrors AC2's pattern)."""
    from viraltracker.services.product_offer_variant_service import ProductOfferVariantService
    service = ProductOfferVariantService()
    return service.get_offer_variants(UUID(product_id), active_only=True)


def get_products_for_brand(brand_id: str) -> List[Dict[str, Any]]:
    """Return active products for the brand."""
    sb = get_supabase()
    result = (
        sb.table("products")
        .select("id, name")
        .eq("brand_id", brand_id)
        .order("name")
        .execute()
    )
    return result.data or []


def get_existing_angles_for_combo(persona_id: str, offer_variant_id: str) -> List[Dict[str, Any]]:
    """
    Return saved belief_angles for this (persona, offer) combination, newest first.

    Used in two places on the Generate Angles page:
      1. Visibility: show the user what they've already saved for this combo
         so they know what they're working with before generating more
      2. Dedupe: pass into AngleGeneratorService.generate_angles() as the
         existing_angles list so the prompt tells Opus to avoid producing
         angles that overlap with these

    All statuses included (untested, testing, winner, loser) — even losers are
    territory the user has already explored, so the generator shouldn't waste
    a slot revisiting them.
    """
    if not persona_id or not offer_variant_id:
        return []
    try:
        sb = get_supabase()
        result = (
            sb.table("belief_angles")
            .select(
                "id, name, belief_statement, jtbd_text, pain_points, "
                "desired_outcome, emotional_register, explanation, status, "
                "generation_method, created_at"
            )
            .eq("source_persona_id", persona_id)
            .eq("source_offer_variant_id", offer_variant_id)
            .order("created_at", desc=True)
            .limit(50)
            .execute()
        )
        return result.data or []
    except Exception as e:
        st.warning(f"Could not load existing angles: {e}")
        return []


def get_landing_page_summary(landing_page_url: Optional[str]) -> Optional[str]:
    """
    Pull the most recent landing_page_analyses summary for the given URL.

    Returns a short summary string for the generator prompt, or None if no
    analysis exists. The AngleGeneratorService treats None as "no LP grounding"
    and notes that in each angle's explanation.

    Uses the real columns on landing_page_analyses:
      - awareness_level / market_sophistication / architecture_type / classification
      - primary_content_pattern + content_patterns (JSONB)
      - elements (JSONB array of analyzed sections — title, body, etc.)
      - page_markdown (full LP text — truncated to ~3000 chars for prompt fit)

    Page_markdown is the most useful single field for angle generation since it
    contains the LP's actual copy. We include a truncated form (first ~3000 chars)
    plus the structured classification fields as supporting context.
    """
    if not landing_page_url:
        return None
    try:
        sb = get_supabase()
        result = (
            sb.table("landing_page_analyses")
            .select(
                "awareness_level, market_sophistication, architecture_type, "
                "classification, primary_content_pattern, content_patterns, "
                "elements, page_markdown, status"
            )
            .eq("url", landing_page_url)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if not result.data:
            return None
        row = result.data[0]
        # Skip rows where the analysis itself failed
        if (row.get("status") or "").lower() == "failed":
            return None

        parts = []
        if row.get("classification"):
            parts.append(f"Page type: {row['classification']}")
        if row.get("architecture_type"):
            parts.append(f"Architecture: {row['architecture_type']}")
        if row.get("awareness_level"):
            parts.append(f"Targets awareness level: {row['awareness_level']}")
        if row.get("market_sophistication"):
            parts.append(f"Market sophistication: {row['market_sophistication']}")
        if row.get("primary_content_pattern"):
            parts.append(f"Primary content pattern: {row['primary_content_pattern']}")

        # Page markdown carries the actual LP copy — most strategic value per token.
        # Truncate to keep the prompt fit comfortable (Opus context is huge but
        # the generator prompt is already substantial; ~3000 chars of LP = ~750 tokens).
        page_md = row.get("page_markdown")
        if page_md:
            md_snippet = page_md[:3000].strip()
            if len(page_md) > 3000:
                md_snippet += "\n[...LP truncated for prompt size...]"
            parts.append(f"LP copy:\n{md_snippet}")

        return "\n\n".join(parts) if parts else None
    except Exception as e:
        st.warning(f"Could not load LP analysis: {e}")
        return None


# ============================================
# SESSION STATE
# ============================================

def _init_state():
    defaults = {
        "ga_product_id": None,
        "ga_persona_id": None,
        "ga_offer_variant_id": None,
        "ga_n_angles": 5,
        "ga_generated_angles": None,    # List[Dict] when generation runs
        "ga_generation_inputs": None,   # Dict snapshot of inputs at gen time
        "ga_selected_indices": set(),
        "ga_last_save": None,           # Dict with angle_generation_run_id + angle_ids
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


_init_state()


# ============================================
# PAGE
# ============================================

st.title("🎯 Generate Angles")
st.caption(
    "Strategy-first angle generation. Produces N belief-level angles for a "
    "(persona, offer) pair. Save the winners → run ads against them from Ad Creator V2."
)

# Brand selector (shared utility, session-state-backed)
brand_id = render_brand_selector(key="ga_brand_selector")
if not brand_id:
    st.info("Select a brand to continue.")
    st.stop()

# Product selector
products = get_products_for_brand(brand_id)
if not products:
    st.warning("This brand has no products. Add one from the Brand Manager first.")
    st.stop()

product_options = {p["id"]: p["name"] for p in products}
product_ids = list(product_options.keys())

# Guard stale product_id when brand changes
if st.session_state.ga_product_id not in product_ids:
    st.session_state.ga_product_id = product_ids[0]

st.selectbox(
    "Product",
    options=product_ids,
    format_func=lambda pid: product_options[pid],
    key="ga_product_id",
)

product_id = st.session_state.ga_product_id

# Persona + offer variant selectors
col1, col2 = st.columns(2)

with col1:
    personas = get_personas_for_product(product_id)
    if not personas:
        st.warning("This product has no personas. Create one on the Personas page.")
        st.stop()

    persona_options = {p["id"]: p["name"] + (" (primary)" if p["is_primary"] else "") for p in personas}
    persona_ids = list(persona_options.keys())

    # Auto-select primary if no selection yet
    if st.session_state.ga_persona_id not in persona_ids:
        primary = next((p for p in personas if p["is_primary"]), None)
        st.session_state.ga_persona_id = primary["id"] if primary else persona_ids[0]

    st.selectbox(
        "Persona",
        options=persona_ids,
        format_func=lambda pid: persona_options[pid],
        key="ga_persona_id",
        help="The persona this angle batch is being built for. Drives the generator's psychographic inputs.",
    )

with col2:
    offer_variants = get_offer_variants_for_product(product_id)

    if not offer_variants:
        st.warning("No active offer variants for this product. Create one on the Brand Manager → Products tab.")
        st.session_state.ga_offer_variant_id = None
        offer_variant_id = None
    else:
        variant_options = {v["id"]: v for v in offer_variants}
        variant_ids = list(variant_options.keys())

        # Auto-select default variant
        if st.session_state.ga_offer_variant_id not in variant_ids:
            default_v = next((v for v in offer_variants if v.get("is_default")), None)
            st.session_state.ga_offer_variant_id = default_v["id"] if default_v else variant_ids[0]

        def _fmt_variant(vid):
            v = variant_options[vid]
            label = v["name"]
            if v.get("is_default"):
                label += " (default)"
            return label

        st.selectbox(
            "Offer variant",
            options=variant_ids,
            format_func=_fmt_variant,
            key="ga_offer_variant_id",
            help="Landing page + offer. The generator anchors each angle to what this offer's LP actually promises.",
        )
        offer_variant_id = st.session_state.ga_offer_variant_id

# Readiness banner: warn if no LP for the selected offer variant
lp_url = None
if offer_variant_id and offer_variants:
    selected_variant = variant_options[offer_variant_id]
    lp_url = selected_variant.get("landing_page_url")

if not lp_url:
    st.warning(
        "**No landing page URL on the selected offer variant.** The generator will "
        "still produce angles, but quality will be sharper if you add the LP URL to "
        "the offer variant (Brand Manager → Products → Offer Variants) and rerun."
    )

# Existing angles for this combo — visibility + dedup input
existing_for_combo: List[Dict[str, Any]] = []
if st.session_state.ga_persona_id and offer_variant_id:
    existing_for_combo = get_existing_angles_for_combo(
        st.session_state.ga_persona_id, offer_variant_id
    )

if existing_for_combo:
    st.markdown(f"### 📚 {len(existing_for_combo)} angle(s) saved for this persona + offer")
    st.caption(
        "Each card below is the full strategic breakdown of a saved angle. "
        "Generating more angles tells Opus to AVOID these and explore different "
        "psychographic territory. To retire a stale angle, set its status to "
        "`loser` in Research Insights — losers are still passed to the prompt "
        "as 'tried this, didn't work, don't repeat.'"
    )

    for a in existing_for_combo:
        status = a.get("status") or "untested"
        register = a.get("emotional_register") or ""
        created = (a.get("created_at") or "")[:10]
        method = a.get("generation_method") or "—"

        # Per-angle expander = the full ingredient breakdown. Collapsed by
        # default so the list stays scannable; expand one to see the recipe.
        header = f"**{a['name']}**"
        if register:
            header += f"  ·  _{register}_"
        header += f"  ·  `{status}`"

        with st.expander(header, expanded=False):
            # Metadata line
            st.caption(f"Created {created}  ·  via `{method}`  ·  id `{a['id'][:8]}`")

            belief = (a.get("belief_statement") or "").strip()
            if belief:
                st.markdown("**Belief statement**")
                st.info(belief)

            jtbd = (a.get("jtbd_text") or "").strip()
            if jtbd:
                st.markdown("**Job to be done**")
                st.write(jtbd)

            pain_points = a.get("pain_points") or []
            if pain_points:
                st.markdown("**Pain points**")
                for pp in pain_points:
                    st.markdown(f"- {pp}")

            desired = (a.get("desired_outcome") or "").strip()
            if desired:
                st.markdown("**Desired outcome**")
                st.write(desired)

            explanation = (a.get("explanation") or "").strip()
            if explanation:
                st.markdown("**Why this angle works**")
                st.caption(explanation)

# N angles slider
st.slider(
    "Number of angles to generate",
    min_value=3, max_value=10, value=st.session_state.ga_n_angles,
    key="ga_n_angles",
    help="The generator orders these safest-bet first (Angle 1 mirrors current winners; Angle N tests new ground).",
)

# Generate button
generate_disabled = not (st.session_state.ga_persona_id and offer_variant_id)
if st.button("✨ Generate Angles", type="primary", disabled=generate_disabled):
    with st.spinner(f"Generating {st.session_state.ga_n_angles} angles via Claude Opus 4.7..."):
        try:
            lp_summary = get_landing_page_summary(lp_url)
            svc = get_angle_generator_service()
            angles = svc.generate_angles(
                persona_id=UUID(st.session_state.ga_persona_id),
                offer_variant_id=UUID(offer_variant_id),
                landing_page_url=lp_url,
                landing_page_summary=lp_summary,
                n=st.session_state.ga_n_angles,
                existing_angles=existing_for_combo,
            )
            st.session_state.ga_generated_angles = [a.dict() for a in angles]
            st.session_state.ga_generation_inputs = {
                "persona_id": st.session_state.ga_persona_id,
                "offer_variant_id": offer_variant_id,
                "landing_page_url": lp_url,
                "n_requested": st.session_state.ga_n_angles,
            }
            st.session_state.ga_selected_indices = set(range(len(angles)))  # default: all selected
            st.session_state.ga_last_save = None
            st.success(f"Generated {len(angles)} angles. Review and edit below.")
        except Exception as e:
            st.error(f"Generation failed: {e}")

# ============================================
# REVIEW + EDIT + SAVE
# ============================================

if st.session_state.ga_generated_angles:
    st.divider()
    st.subheader(f"Generated Angles ({len(st.session_state.ga_generated_angles)})")

    if st.session_state.ga_last_save:
        st.info(
            f"Saved {len(st.session_state.ga_last_save['angle_ids'])} angle(s). "
            f"Run ID: `{st.session_state.ga_last_save['angle_generation_run_id']}`"
        )

    edited_angles: List[Dict[str, Any]] = []

    for idx, angle in enumerate(st.session_state.ga_generated_angles):
        # Each angle in its own expander; selection toggle in the header
        is_selected = idx in st.session_state.ga_selected_indices
        header_label = (
            f"{'☑️' if is_selected else '☐'}  "
            f"Angle {idx + 1}: **{angle['name']}**  ·  "
            f"_{angle['emotional_register']}_"
        )
        with st.expander(header_label, expanded=(idx == 0)):
            include = st.checkbox(
                "Include this angle in save",
                value=is_selected,
                key=f"ga_include_{idx}",
            )
            if include:
                st.session_state.ga_selected_indices.add(idx)
            else:
                st.session_state.ga_selected_indices.discard(idx)

            name = st.text_input(
                "Name",
                value=angle["name"],
                key=f"ga_name_{idx}",
            )
            belief_statement = st.text_area(
                "Belief statement",
                value=angle["belief_statement"],
                height=80,
                key=f"ga_belief_{idx}",
                help="The core belief the angle tests. Not a benefit — a belief.",
            )
            jtbd_text = st.text_area(
                "JTBD",
                value=angle["jtbd_text"],
                height=68,
                key=f"ga_jtbd_{idx}",
                help="Progress format: 'When I X, I want to Y, so I can Z'.",
            )
            pain_points_str = st.text_area(
                "Pain points (one per line)",
                value="\n".join(angle.get("pain_points", []) or []),
                height=80,
                key=f"ga_pp_{idx}",
            )
            desired_outcome = st.text_area(
                "Desired outcome",
                value=angle["desired_outcome"],
                height=68,
                key=f"ga_outcome_{idx}",
            )
            emotional_register = st.text_input(
                "Emotional register",
                value=angle["emotional_register"],
                key=f"ga_register_{idx}",
            )
            explanation = st.text_area(
                "Why this angle works (generator's reasoning)",
                value=angle["explanation"],
                height=100,
                key=f"ga_explanation_{idx}",
            )

            edited_angles.append({
                "name": name,
                "belief_statement": belief_statement,
                "jtbd_text": jtbd_text,
                "pain_points": [p.strip() for p in pain_points_str.split("\n") if p.strip()],
                "desired_outcome": desired_outcome,
                "emotional_register": emotional_register,
                "explanation": explanation,
            })

    st.divider()

    # Save button
    selected_count = len(st.session_state.ga_selected_indices)
    save_col, cont_col, _ = st.columns([1, 1, 2])

    with save_col:
        save_disabled = (selected_count == 0) or (st.session_state.ga_last_save is not None)
        save_label = f"💾 Save {selected_count} angle(s)" if selected_count else "💾 Save (none selected)"
        if st.button(save_label, type="primary", disabled=save_disabled):
            with st.spinner(f"Saving {selected_count} angle(s)..."):
                try:
                    from viraltracker.services.angle_generator_service import ProposedAngle
                    selected_proposed = [
                        ProposedAngle(**edited_angles[i])
                        for i in sorted(st.session_state.ga_selected_indices)
                    ]
                    inputs = st.session_state.ga_generation_inputs
                    svc = get_angle_generator_service()
                    result = svc.save_angles(
                        proposed_angles=selected_proposed,
                        persona_id=UUID(inputs["persona_id"]),
                        offer_variant_id=UUID(inputs["offer_variant_id"]),
                        landing_page_url=inputs.get("landing_page_url"),
                        n_angles_requested=inputs["n_requested"],
                    )
                    st.session_state.ga_last_save = result
                    st.success(
                        f"Saved {len(result['angle_ids'])} angle(s). "
                        f"They're now available in Ad Creator V2 under this persona + offer."
                    )
                    st.rerun()
                except Exception as e:
                    st.error(f"Save failed: {e}")

    with cont_col:
        if st.session_state.ga_last_save:
            saved_ids = st.session_state.ga_last_save["angle_ids"]
            multi_saved = len(saved_ids) > 1

            # Primary path: AC2 (one-shot immediate-ish run, ~1 min via scheduler).
            # AC2 = one angle per run by design, so if multiple were saved we hand off
            # only the first; user can repeat the AC2 launch for the others.
            ac2_label = (
                f"🚀 Run angle 1 of {len(saved_ids)} in Ad Creator V2"
                if multi_saved else
                "🚀 Continue to Ad Creator V2"
            )
            if st.button(ac2_label, type="primary"):
                st.session_state["preselect_angle_ids"] = list(saved_ids)
                st.session_state["v2_content_source"] = "angles"
                st.switch_page("pages/21b_🎨_Ad_Creator_V2.py")

            # Secondary path: Ad Scheduler for batch / recurring runs across all
            # saved angles. Surfaced as a smaller secondary action.
            if st.button("📅 Schedule all in Ad Scheduler", type="secondary"):
                st.session_state["sched_selected_angle_ids"] = list(saved_ids)
                st.session_state["sched_persona_id"] = st.session_state.ga_persona_id
                st.session_state["sched_offer_variant_id"] = st.session_state.ga_offer_variant_id
                st.switch_page("pages/24_📅_Ad_Scheduler.py")
