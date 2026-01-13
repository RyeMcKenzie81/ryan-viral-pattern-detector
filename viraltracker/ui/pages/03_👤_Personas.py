"""
4D Persona Builder - Create and manage customer personas for better ad copy.

This page allows users to:
- View personas for a brand or product
- Create new personas manually
- Generate personas with AI from product data
- Edit persona details across all 8 dimensions
- Link personas to products with primary selection
- Export personas for copy generation
"""

import streamlit as st
import asyncio
import json
from datetime import datetime
from uuid import UUID
from typing import Optional, Dict, Any, List

# Apply nest_asyncio at module load for Streamlit compatibility
import nest_asyncio
nest_asyncio.apply()

# Page config
st.set_page_config(
    page_title="Persona Builder",
    page_icon="👤",
    layout="wide"
)

# Authentication
from viraltracker.ui.auth import require_auth
require_auth()

# Initialize session state
if 'selected_product_id' not in st.session_state:
    st.session_state.selected_product_id = None
if 'selected_persona_id' not in st.session_state:
    st.session_state.selected_persona_id = None
if 'editing_persona' not in st.session_state:
    st.session_state.editing_persona = None
if 'generating_persona' not in st.session_state:
    st.session_state.generating_persona = False


def get_supabase_client():
    """Get Supabase client."""
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()


def get_persona_service():
    """Get PersonaService instance."""
    from viraltracker.services.persona_service import PersonaService
    return PersonaService()


def get_brands():
    """Fetch all brands."""
    try:
        db = get_supabase_client()
        result = db.table("brands").select("id, name").order("name").execute()
        return result.data
    except Exception as e:
        st.error(f"Failed to fetch brands: {e}")
        return []


def get_products_for_brand(brand_id: str):
    """Fetch all products for a brand."""
    try:
        db = get_supabase_client()
        result = db.table("products").select("id, name, target_audience").eq(
            "brand_id", brand_id
        ).order("name").execute()
        return result.data
    except Exception as e:
        st.error(f"Failed to fetch products: {e}")
        return []


def get_personas_for_brand(brand_id: str):
    """Fetch all personas for a brand."""
    try:
        db = get_supabase_client()
        result = db.table("personas_4d").select(
            "id, name, persona_type, is_primary, snapshot, source_type, product_id"
        ).eq("brand_id", brand_id).order("name").execute()
        return result.data
    except Exception as e:
        st.error(f"Failed to fetch personas: {e}")
        return []


def get_product_persona_links(product_id: str):
    """Get personas linked to a product."""
    try:
        db = get_supabase_client()
        result = db.table("product_personas").select(
            "*, personas_4d(id, name, snapshot, source_type)"
        ).eq("product_id", product_id).execute()
        return result.data
    except Exception as e:
        st.error(f"Failed to fetch product personas: {e}")
        return []


def generate_persona_for_product_sync(product_id: str, brand_id: str, offer_variant_id: str = None):
    """Generate a persona using AI (sync wrapper for Streamlit)."""
    service = get_persona_service()

    return asyncio.run(
        service.generate_persona_from_product(
            product_id=UUID(product_id),
            brand_id=UUID(brand_id),
            offer_variant_id=UUID(offer_variant_id) if offer_variant_id else None
        )
    )


def get_offer_variants_for_product(product_id: str):
    """Fetch all offer variants for a product."""
    try:
        db = get_supabase_client()
        result = db.table("product_offer_variants").select(
            "id, name, pain_points, desires_goals, target_audience"
        ).eq("product_id", product_id).order("name").execute()
        return result.data
    except Exception as e:
        st.error(f"Failed to fetch offer variants: {e}")
        return []


def save_persona(persona_data: Dict[str, Any]) -> Optional[str]:
    """Save a new persona to the database."""
    try:
        from viraltracker.services.models import Persona4D, PersonaType, SourceType
        service = get_persona_service()

        persona = Persona4D(
            name=persona_data.get("name", "New Persona"),
            persona_type=PersonaType(persona_data.get("persona_type", "product_specific")),
            brand_id=UUID(persona_data["brand_id"]) if persona_data.get("brand_id") else None,
            product_id=UUID(persona_data["product_id"]) if persona_data.get("product_id") else None,
            source_type=SourceType(persona_data.get("source_type", "manual")),
            snapshot=persona_data.get("snapshot"),
            # Add other fields as needed from persona_data
        )

        persona_id = service.create_persona(persona)
        return str(persona_id)
    except Exception as e:
        st.error(f"Failed to save persona: {e}")
        return None


def link_persona_to_product(persona_id: str, product_id: str, is_primary: bool = False):
    """Link a persona to a product."""
    try:
        service = get_persona_service()
        service.link_persona_to_product(
            persona_id=UUID(persona_id),
            product_id=UUID(product_id),
            is_primary=is_primary
        )
        return True
    except Exception as e:
        st.error(f"Failed to link persona: {e}")
        return False


def render_persona_card(persona: Dict[str, Any], show_actions: bool = True):
    """Render a persona summary card."""
    with st.container():
        col1, col2 = st.columns([3, 1])

        with col1:
            # Header with name and type badge
            source_badge = {
                "manual": ":blue[Manual]",
                "ai_generated": ":green[AI Generated]",
                "competitor_analysis": ":orange[From Competitor]",
                "hybrid": ":violet[Hybrid]"
            }.get(persona.get("source_type", "manual"), ":gray[Unknown]")

            st.markdown(f"### {persona.get('name', 'Unnamed Persona')} {source_badge}")

            # Snapshot
            if persona.get("snapshot"):
                st.markdown(f"*{persona['snapshot']}*")

            # Type and primary indicator
            type_label = {
                "own_brand": "Brand-level",
                "product_specific": "Product-specific",
                "competitor": "Competitor"
            }.get(persona.get("persona_type"), "Unknown")

            badges = [f":gray[{type_label}]"]
            if persona.get("is_primary"):
                badges.append(":green[Primary]")

            st.markdown(" ".join(badges))

        with col2:
            if show_actions:
                if st.button("View/Edit", key=f"edit_{persona['id']}"):
                    st.session_state.selected_persona_id = persona['id']
                    st.rerun()


def render_dimension_editor(dimension_name: str, fields: List[Dict], data: Dict[str, Any]) -> Dict[str, Any]:
    """Render an editor for a persona dimension."""
    st.subheader(dimension_name)

    updated_data = {}

    for field in fields:
        field_key = field["key"]
        field_label = field["label"]
        field_type = field.get("type", "text")
        field_help = field.get("help", "")

        current_value = data.get(field_key, field.get("default", ""))

        if field_type == "text":
            updated_data[field_key] = st.text_input(
                field_label,
                value=current_value or "",
                help=field_help,
                key=f"field_{field_key}"
            )

        elif field_type == "textarea":
            updated_data[field_key] = st.text_area(
                field_label,
                value=current_value or "",
                help=field_help,
                key=f"field_{field_key}"
            )

        elif field_type == "list":
            # Convert list to newline-separated string for editing
            if isinstance(current_value, list):
                current_str = "\n".join(current_value)
            else:
                current_str = current_value or ""

            edited = st.text_area(
                f"{field_label} (one per line)",
                value=current_str,
                help=field_help,
                key=f"field_{field_key}"
            )
            # Convert back to list
            updated_data[field_key] = [line.strip() for line in edited.split("\n") if line.strip()]

        elif field_type == "json":
            # For complex JSON fields, show as formatted JSON
            if isinstance(current_value, dict):
                current_str = json.dumps(current_value, indent=2)
            else:
                current_str = "{}"

            edited = st.text_area(
                field_label,
                value=current_str,
                help=field_help,
                key=f"field_{field_key}"
            )
            try:
                updated_data[field_key] = json.loads(edited)
            except json.JSONDecodeError:
                updated_data[field_key] = current_value
                st.warning(f"Invalid JSON in {field_label}")

    return updated_data


def render_persona_editor(persona_id: str):
    """Render the full persona editor."""
    service = get_persona_service()
    persona = service.get_persona(UUID(persona_id))

    if not persona:
        st.error("Persona not found")
        return

    st.title(f"Editing: {persona.name}")

    # Back button
    if st.button("< Back to List"):
        st.session_state.selected_persona_id = None
        st.rerun()

    # Create tabs for each dimension
    tabs = st.tabs([
        "1. Basics",
        "2. Psychographic",
        "3. Identity",
        "4. Social",
        "5. Worldview",
        "6. Domain",
        "7. Purchase",
        "8. Objections",
        "9. Testimonials"
    ])

    updated_persona = {}

    # Tab 1: Basics
    with tabs[0]:
        st.subheader("Persona Basics")

        col1, col2 = st.columns(2)
        with col1:
            updated_persona["name"] = st.text_input("Persona Name", value=persona.name)
            updated_persona["snapshot"] = st.text_area(
                "Snapshot (2-3 sentence description)",
                value=persona.snapshot or "",
                height=100
            )

        with col2:
            st.markdown("**Demographics**")
            demo = persona.demographics.model_dump() if persona.demographics else {}
            updated_persona["demographics"] = {
                "age_range": st.text_input("Age Range", value=demo.get("age_range", "")),
                "gender": st.selectbox("Gender", ["any", "male", "female"],
                    index=["any", "male", "female"].index(demo.get("gender", "any")) if demo.get("gender") in ["any", "male", "female"] else 0
                ),
                "location": st.text_input("Location", value=demo.get("location", "")),
                "income_level": st.text_input("Income Level", value=demo.get("income_level", "")),
                "occupation": st.text_input("Occupation", value=demo.get("occupation", "")),
            }

    # Tab 2: Psychographic Mapping
    with tabs[1]:
        st.subheader("Transformation Map")
        col1, col2 = st.columns(2)

        tm = persona.transformation_map.model_dump() if persona.transformation_map else {"before": [], "after": []}

        with col1:
            st.markdown("**BEFORE (Current State)**")
            before_text = st.text_area(
                "Frustrations, limitations, current identity (one per line)",
                value="\n".join(tm.get("before", [])),
                height=150
            )
            updated_persona["transformation_map"] = {"before": [x.strip() for x in before_text.split("\n") if x.strip()]}

        with col2:
            st.markdown("**AFTER (Desired State)**")
            after_text = st.text_area(
                "Desired outcomes, capabilities, identity (one per line)",
                value="\n".join(tm.get("after", [])),
                height=150
            )
            updated_persona["transformation_map"]["after"] = [x.strip() for x in after_text.split("\n") if x.strip()]

        st.subheader("Core Desires")
        st.markdown("*The 10 core human desires with specific verbiage they use*")

        # Show desires as expandable sections
        desires = persona.desires or {}

        desire_categories = [
            ("care_protection", "Care & Protection of Loved Ones"),
            ("social_approval", "Social Approval / Being Seen"),
            ("freedom_from_fear", "Freedom from Fear, Pain, Worry"),
            ("superiority_status", "Superiority, Admiration, Status"),
            ("self_actualization", "Self-Actualization"),
            ("comfortable_living", "Comfortable Living Conditions"),
            ("survival_life_extension", "Survival & Life Extension"),
        ]

        updated_desires = {}
        for category_key, category_label in desire_categories:
            with st.expander(category_label):
                current = desires.get(category_key, [])
                # Convert to text
                if current:
                    current_text = "\n".join([
                        d.text if hasattr(d, "text") else (d.get("text", str(d)) if isinstance(d, dict) else str(d))
                        for d in current
                    ])
                else:
                    current_text = ""

                edited = st.text_area(
                    f"Verbiage for {category_label} (one per line)",
                    value=current_text,
                    height=100,
                    key=f"desire_{category_key}"
                )

                if edited.strip():
                    updated_desires[category_key] = [
                        {"text": line.strip(), "source": "manual"}
                        for line in edited.split("\n") if line.strip()
                    ]

        updated_persona["desires"] = updated_desires

    # Tab 3: Identity
    with tabs[2]:
        st.subheader("Identity")

        updated_persona["self_narratives"] = st.text_area(
            "Self-Narratives ('Because I am X, therefore I Y...' - one per line)",
            value="\n".join(persona.self_narratives or []),
            height=100
        ).split("\n")
        updated_persona["self_narratives"] = [x.strip() for x in updated_persona["self_narratives"] if x.strip()]

        col1, col2 = st.columns(2)
        with col1:
            updated_persona["current_self_image"] = st.text_area(
                "Current Self-Image (how they see themselves)",
                value=persona.current_self_image or "",
                height=100
            )

        with col2:
            updated_persona["desired_self_image"] = st.text_area(
                "Desired Self-Image (who they want to become)",
                value=persona.desired_self_image or "",
                height=100
            )

        updated_persona["identity_artifacts"] = st.text_area(
            "Identity Artifacts (brands/objects tied to desired identity - one per line)",
            value="\n".join(persona.identity_artifacts or []),
            height=100
        ).split("\n")
        updated_persona["identity_artifacts"] = [x.strip() for x in updated_persona["identity_artifacts"] if x.strip()]

    # Tab 4: Social Dynamics
    with tabs[3]:
        st.subheader("Social Relations")
        st.markdown("*Map the people in their life by relationship type*")

        sr = persona.social_relations.model_dump() if persona.social_relations else {}

        social_fields = [
            ("want_to_impress", "People They Want to Impress"),
            ("fear_judged_by", "People They Fear Being Judged By"),
            ("influence_decisions", "People Who Influence Their Decisions"),
            ("admire", "People They Admire"),
            ("envy", "People They Envy"),
            ("want_to_belong", "Groups They Want to Belong To"),
        ]

        updated_social = {}
        for field_key, field_label in social_fields:
            current = sr.get(field_key, [])
            edited = st.text_area(
                f"{field_label} (one per line)",
                value="\n".join(current) if current else "",
                height=80,
                key=f"social_{field_key}"
            )
            updated_social[field_key] = [x.strip() for x in edited.split("\n") if x.strip()]

        updated_persona["social_relations"] = updated_social

    # Tab 5: Worldview
    with tabs[4]:
        st.subheader("Worldview")

        updated_persona["worldview"] = st.text_area(
            "General Worldview / Reality Interpretation",
            value=persona.worldview or "",
            height=100
        )

        col1, col2 = st.columns(2)
        with col1:
            updated_persona["core_values"] = st.text_area(
                "Core Values (one per line)",
                value="\n".join(persona.core_values or []),
                height=100
            ).split("\n")
            updated_persona["core_values"] = [x.strip() for x in updated_persona["core_values"] if x.strip()]

            updated_persona["forces_of_good"] = st.text_area(
                "Forces of Good (one per line)",
                value="\n".join(persona.forces_of_good or []),
                height=100
            ).split("\n")
            updated_persona["forces_of_good"] = [x.strip() for x in updated_persona["forces_of_good"] if x.strip()]

        with col2:
            updated_persona["cultural_zeitgeist"] = st.text_input(
                "Cultural Zeitgeist (the era/moment they believe they're in)",
                value=persona.cultural_zeitgeist or ""
            )

            updated_persona["forces_of_evil"] = st.text_area(
                "Forces of Evil (one per line)",
                value="\n".join(persona.forces_of_evil or []),
                height=100
            ).split("\n")
            updated_persona["forces_of_evil"] = [x.strip() for x in updated_persona["forces_of_evil"] if x.strip()]

        st.subheader("Allergies (Messaging Turn-offs)")
        allergies = persona.allergies or {}
        allergies_text = st.text_area(
            "Triggers that cause negative reactions (format: trigger: reaction)",
            value="\n".join([f"{k}: {v}" for k, v in allergies.items()]),
            height=100
        )
        updated_persona["allergies"] = {}
        for line in allergies_text.split("\n"):
            if ":" in line:
                key, value = line.split(":", 1)
                updated_persona["allergies"][key.strip()] = value.strip()

    # Tab 6: Domain Sentiment
    with tabs[5]:
        st.subheader("Domain Sentiment (Product-Specific)")

        def edit_domain_sentiment(label: str, data: Any, key_prefix: str) -> Dict:
            d = data.model_dump() if hasattr(data, "model_dump") else (data or {})
            col1, col2, col3 = st.columns(3)

            with col1:
                emotional = st.text_area(
                    f"{label} - Emotional",
                    value="\n".join(d.get("emotional", [])),
                    height=100,
                    key=f"{key_prefix}_emotional"
                )

            with col2:
                social = st.text_area(
                    f"{label} - Social",
                    value="\n".join(d.get("social", [])),
                    height=100,
                    key=f"{key_prefix}_social"
                )

            with col3:
                functional = st.text_area(
                    f"{label} - Functional",
                    value="\n".join(d.get("functional", [])),
                    height=100,
                    key=f"{key_prefix}_functional"
                )

            return {
                "emotional": [x.strip() for x in emotional.split("\n") if x.strip()],
                "social": [x.strip() for x in social.split("\n") if x.strip()],
                "functional": [x.strip() for x in functional.split("\n") if x.strip()]
            }

        st.markdown("**Pain Points**")
        updated_persona["pain_points"] = edit_domain_sentiment("Pain Points", persona.pain_points, "pain")

        st.markdown("**Desired Outcomes / JTBD**")
        updated_persona["outcomes_jtbd"] = edit_domain_sentiment("Outcomes", persona.outcomes_jtbd, "outcomes")

        st.markdown("**Buying Objections**")
        updated_persona["buying_objections"] = edit_domain_sentiment("Objections", persona.buying_objections, "objections")

        st.subheader("Other Domain Data")
        col1, col2 = st.columns(2)

        with col1:
            updated_persona["failed_solutions"] = st.text_area(
                "Failed Solutions (what they've tried - one per line)",
                value="\n".join(persona.failed_solutions or []),
                height=100
            ).split("\n")
            updated_persona["failed_solutions"] = [x.strip() for x in updated_persona["failed_solutions"] if x.strip()]

        with col2:
            updated_persona["familiar_promises"] = st.text_area(
                "Familiar Promises (claims they've heard - one per line)",
                value="\n".join(persona.familiar_promises or []),
                height=100
            ).split("\n")
            updated_persona["familiar_promises"] = [x.strip() for x in updated_persona["familiar_promises"] if x.strip()]

    # Tab 7: Purchase Behavior
    with tabs[6]:
        st.subheader("Purchase Behavior")

        col1, col2 = st.columns(2)

        with col1:
            updated_persona["activation_events"] = st.text_area(
                "Activation Events (what triggers purchase NOW - one per line)",
                value="\n".join(persona.activation_events or []),
                height=100
            ).split("\n")
            updated_persona["activation_events"] = [x.strip() for x in updated_persona["activation_events"] if x.strip()]

            updated_persona["pain_symptoms"] = st.text_area(
                "Pain Symptoms (observable signs - one per line)",
                value="\n".join(persona.pain_symptoms or []),
                height=100
            ).split("\n")
            updated_persona["pain_symptoms"] = [x.strip() for x in updated_persona["pain_symptoms"] if x.strip()]

        with col2:
            updated_persona["purchasing_habits"] = st.text_area(
                "Purchasing Habits",
                value=persona.purchasing_habits or "",
                height=100
            )

            updated_persona["decision_process"] = st.text_area(
                "Decision Process",
                value=persona.decision_process or "",
                height=100
            )

        updated_persona["current_workarounds"] = st.text_area(
            "Current Workarounds (hacks they use instead - one per line)",
            value="\n".join(persona.current_workarounds or []),
            height=100
        ).split("\n")
        updated_persona["current_workarounds"] = [x.strip() for x in updated_persona["current_workarounds"] if x.strip()]

    # Tab 8: 3D Objections
    with tabs[7]:
        st.subheader("3D Objections")

        col1, col2 = st.columns(2)

        with col1:
            updated_persona["emotional_risks"] = st.text_area(
                "Emotional Risks (what they're afraid of feeling - one per line)",
                value="\n".join(persona.emotional_risks or []),
                height=150
            ).split("\n")
            updated_persona["emotional_risks"] = [x.strip() for x in updated_persona["emotional_risks"] if x.strip()]

        with col2:
            updated_persona["barriers_to_behavior"] = st.text_area(
                "Barriers to Behavior (what stops them from acting - one per line)",
                value="\n".join(persona.barriers_to_behavior or []),
                height=150
            ).split("\n")
            updated_persona["barriers_to_behavior"] = [x.strip() for x in updated_persona["barriers_to_behavior"] if x.strip()]

    # Tab 9: Testimonials (from Amazon Reviews)
    with tabs[8]:
        st.subheader("Customer Voice & Testimonials")
        st.caption("Real customer language from Amazon reviews - gold for ad copy")

        # Get testimonials from persona's amazon_testimonials field
        testimonials = persona.amazon_testimonials if hasattr(persona, 'amazon_testimonials') and persona.amazon_testimonials else {}

        if testimonials:
            # Helper function to render quotes
            def render_quotes(quotes_list, color="blue"):
                if not quotes_list:
                    st.caption("No quotes in this category")
                    return
                for q in quotes_list[:10]:  # Limit to 10
                    if isinstance(q, dict):
                        quote_text = q.get('quote', q.get('text', ''))
                        author = q.get('author', '')
                        rating = q.get('rating', '')
                        rating_stars = '⭐' * int(rating) if rating and str(rating).isdigit() else ''
                        if author and author.lower() not in ['verified buyer', 'anonymous', '']:
                            st.markdown(f"> \"{quote_text}\" — *{author}* {rating_stars}")
                        else:
                            st.markdown(f"> \"{quote_text}\" {rating_stars}")
                    else:
                        st.markdown(f"> \"{q}\"")

            col_left, col_right = st.columns(2)

            with col_left:
                st.markdown("**🌟 Transformation (Results/Outcomes)**")
                render_quotes(testimonials.get('transformation', []))
                st.markdown("---")

                st.markdown("**😣 Pain Points (Problems Before Product)**")
                render_quotes(testimonials.get('pain_points', []))
                st.markdown("---")

                st.markdown("**✨ Desired Features**")
                render_quotes(testimonials.get('desired_features', []))

            with col_right:
                st.markdown("**❌ Past Failures (Other Products)**")
                render_quotes(testimonials.get('past_failures', []))
                st.markdown("---")

                st.markdown("**🤔 Buying Objections (Skepticism)**")
                render_quotes(testimonials.get('buying_objections', []))
                st.markdown("---")

                st.markdown("**📢 Familiar Promises (Other Brand Claims)**")
                render_quotes(testimonials.get('familiar_promises', []))

        else:
            st.info("No Amazon testimonials available for this persona.")
            st.markdown("""
            **To populate this tab:**
            1. Go to **URL Mapping** page
            2. Add Amazon product URLs for this brand's products
            3. Scrape and analyze the reviews
            4. Re-synthesize the persona to include review insights
            """)

    # Save button
    st.divider()
    col1, col2, col3 = st.columns([1, 1, 2])

    with col1:
        if st.button("Save Changes", type="primary"):
            try:
                # Update the persona
                service.update_persona(UUID(persona_id), updated_persona)
                st.success("Persona saved successfully!")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to save: {e}")

    with col2:
        if st.button("Export for Copy"):
            try:
                brief = service.export_for_copy_brief(UUID(persona_id))
                st.json(brief.model_dump())
            except Exception as e:
                st.error(f"Failed to export: {e}")


def render_persona_list():
    """Render the main persona list view."""
    st.title("4D Persona Builder")

    # Brand selector (uses shared utility for cross-page persistence)
    from viraltracker.ui.utils import render_brand_selector
    selected_brand_id = render_brand_selector(key="personas_brand_selector")

    if not selected_brand_id:
        return

    # Product filter (optional)
    products = get_products_for_brand(selected_brand_id)
    product_options = {"All Products": None}
    product_options.update({p["name"]: p["id"] for p in products})

    selected_product_name = st.selectbox(
        "Filter by Product",
        options=list(product_options.keys())
    )
    selected_product_id = product_options[selected_product_name]

    st.divider()

    # Action buttons
    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("Create New Persona", type="primary"):
            st.session_state.editing_persona = "new"
            st.rerun()

    with col2:
        if selected_product_id and st.button("Generate with AI"):
            st.session_state.generating_persona = True
            st.session_state.selected_product_id = selected_product_id
            st.rerun()

    # Show personas
    st.subheader("Personas")

    if selected_product_id:
        # Show personas linked to this product
        links = get_product_persona_links(selected_product_id)
        if links:
            for link in links:
                persona_data = link.get("personas_4d", {})
                if persona_data:
                    persona_data["is_primary"] = link.get("is_primary", False)
                    render_persona_card(persona_data)
                    st.divider()
        else:
            st.info("No personas linked to this product yet.")
    else:
        # Show all personas for brand
        personas = get_personas_for_brand(selected_brand_id)
        if personas:
            for persona in personas:
                render_persona_card(persona)
                st.divider()
        else:
            st.info("No personas created yet. Click 'Create New Persona' to get started.")


def render_new_persona_form():
    """Render form for creating a new persona."""
    st.title("Create New Persona")

    if st.button("< Back"):
        st.session_state.editing_persona = None
        st.rerun()

    with st.form("new_persona_form"):
        name = st.text_input("Persona Name", placeholder="e.g., 'Worried First-Time Dog Mom'")
        snapshot = st.text_area("Snapshot", placeholder="2-3 sentence big picture description")

        persona_type = st.selectbox(
            "Persona Type",
            ["product_specific", "own_brand"],
            format_func=lambda x: "Product-specific" if x == "product_specific" else "Brand-level"
        )

        # Link to product if product-specific
        product_id = None
        if persona_type == "product_specific" and st.session_state.selected_brand_id:
            products = get_products_for_brand(st.session_state.selected_brand_id)
            if products:
                product_options = {p["name"]: p["id"] for p in products}
                selected_product = st.selectbox("Link to Product", list(product_options.keys()))
                product_id = product_options[selected_product]

        submitted = st.form_submit_button("Create Persona")

        if submitted and name:
            persona_data = {
                "name": name,
                "snapshot": snapshot,
                "persona_type": persona_type,
                "brand_id": st.session_state.selected_brand_id,
                "product_id": product_id,
                "source_type": "manual"
            }

            persona_id = save_persona(persona_data)
            if persona_id:
                # If product-specific, also link to product
                if product_id:
                    link_persona_to_product(persona_id, product_id, is_primary=True)

                st.success("Persona created!")
                st.session_state.editing_persona = None
                st.session_state.selected_persona_id = persona_id
                st.rerun()


def render_ai_generation():
    """Render AI persona generation interface."""
    st.title("Generate Persona with AI")

    if st.button("< Cancel"):
        st.session_state.generating_persona = False
        st.rerun()

    product_id = st.session_state.selected_product_id
    brand_id = st.session_state.selected_brand_id

    if not product_id or not brand_id:
        st.error("Please select a product first")
        return

    # Get product info
    db = get_supabase_client()
    product = db.table("products").select("name, target_audience, description").eq("id", product_id).execute()

    if product.data:
        p = product.data[0]
        st.info(f"Generating persona for **{p.get('name')}**")

    # Get offer variants for this product
    offer_variants = get_offer_variants_for_product(product_id)

    selected_variant_id = None
    if offer_variants:
        st.markdown("### Select Offer Variant")
        st.caption("Each offer variant targets different pain points and audiences. Select which angle to base the persona on.")

        # Build options - include "None" option for product-level generation
        variant_options = {"(Product-level - no specific variant)": None}
        for v in offer_variants:
            # Show variant name with preview of pain points
            pain_preview = ", ".join(v.get("pain_points", [])[:3]) if v.get("pain_points") else "No pain points"
            if len(pain_preview) > 60:
                pain_preview = pain_preview[:60] + "..."
            label = f"{v['name']}"
            variant_options[label] = v["id"]

        selected_variant_name = st.selectbox(
            "Offer Variant",
            options=list(variant_options.keys()),
            help="Select which offer variant's pain points and desires to use for persona generation"
        )
        selected_variant_id = variant_options[selected_variant_name]

        # Show selected variant details
        if selected_variant_id:
            selected_variant = next((v for v in offer_variants if v["id"] == selected_variant_id), None)
            if selected_variant:
                with st.expander("Variant Details", expanded=True):
                    if selected_variant.get("target_audience"):
                        st.markdown(f"**Target Audience:** {selected_variant['target_audience']}")
                    if selected_variant.get("pain_points"):
                        st.markdown("**Pain Points:**")
                        for pp in selected_variant["pain_points"][:8]:
                            st.markdown(f"- {pp}")
                        if len(selected_variant["pain_points"]) > 8:
                            st.caption(f"... and {len(selected_variant['pain_points']) - 8} more")
                    if selected_variant.get("desires_goals"):
                        st.markdown("**Desires/Goals:**")
                        for dg in selected_variant["desires_goals"][:5]:
                            st.markdown(f"- {dg}")
    else:
        # Fallback to product-level info
        if product.data:
            p = product.data[0]
            if p.get("target_audience"):
                st.markdown(f"**Current target audience:** {p.get('target_audience')}")
            st.info("No offer variants found. Persona will be generated from product-level data.")

    st.divider()

    if st.button("Generate Persona", type="primary", disabled=st.session_state.get('_generating', False)):
        st.session_state._generating = True
        variant_note = f" (variant: {selected_variant_name})" if selected_variant_id else ""
        with st.spinner(f"Generating 4D persona with Claude{variant_note}... (this takes 15-30 seconds)"):
            try:
                persona = generate_persona_for_product_sync(product_id, brand_id, selected_variant_id)
                st.session_state._generated_persona = persona
                st.session_state._generating = False
                st.success(f"Generated: **{persona.name}**")
                st.markdown(f"*{persona.snapshot}*")

                # Show preview
                with st.expander("Preview Generated Persona"):
                    st.json(persona.model_dump(mode="json", exclude_none=True))

                # Save options
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Save & Edit"):
                        service = get_persona_service()
                        persona_id = service.create_persona(persona)
                        service.link_persona_to_product(persona_id, UUID(product_id), is_primary=True)
                        st.session_state.generating_persona = False
                        st.session_state.selected_persona_id = str(persona_id)
                        st.rerun()

                with col2:
                    if st.button("Discard"):
                        st.session_state.generating_persona = False
                        st.rerun()

            except Exception as e:
                st.error(f"Generation failed: {e}")


# Main routing
if st.session_state.generating_persona:
    render_ai_generation()
elif st.session_state.selected_persona_id:
    render_persona_editor(st.session_state.selected_persona_id)
elif st.session_state.editing_persona == "new":
    render_new_persona_form()
else:
    render_persona_list()
