# Sprint 5: Ad Creation + 4D Persona Integration

**Date**: 2025-12-09
**Branch**: `feature/brand-research-pipeline`
**Status**: Planning
**Priority**: High - Gets personas actually used in ad creation

---

## Overview

Integrate 4D Personas into the ad creation workflow so that hooks and recreate-template modes both leverage persona data for more targeted, emotionally resonant ad copy.

### Business Value
- Ads written with persona context convert better
- Pain points, desires, and transformation language from Amazon reviews get used
- Authentic customer voice in ad copy (from testimonials)
- Copy addresses real objections and triggers

---

## Current State

### Ad Creation Flow
1. User selects **product** + **reference template**
2. User chooses **content source**:
   - `"hooks"` → `select_hooks()` picks from hooks DB, adapts to template style
   - `"recreate_template"` → `generate_benefit_variations()` applies template angle to product benefits
3. Workflow generates N ad variations
4. Dual AI review (Claude + Gemini)

### Key Files
| File | Purpose |
|------|---------|
| `ui/pages/01_🎨_Ad_Creator.py` | UI - product selection, content source, workflow trigger |
| `agent/agents/ad_creation_agent.py` | Workflow orchestration, `complete_ad_workflow()` |
| `services/ad_creation_service.py` | Business logic, hooks fetching |
| `services/persona_service.py` | Persona CRUD, `export_for_copy_brief()` |

### Existing Persona Export
`PersonaService.export_for_copy_brief(persona_id)` returns:
```python
CopyBrief(
    persona_name="Proactive Health-Conscious Pet Parent",
    snapshot="2-3 sentence description",
    target_demo={age_range, gender, location, ...},
    primary_desires=["[care_protection] Best care for pet", ...],
    top_pain_points=["worry about future health", "guilt over not doing enough"],
    their_language=["I'm the kind of person who...", ...],  # self_narratives
    transformation={before: [...], after: [...]},
    objections=["emotional objections", "functional objections"],
    failed_solutions=["Other products that failed"],
    activation_events=["What triggers purchase NOW"],
    allergies={"trigger": "reaction"}
)
```

---

## Proposed Changes

### Architecture Principle: Thin Tools Pattern

Per `CLAUDE.md` and `claude_code_guide.md`:
- **Tools** = thin orchestration, LLM decides when to call
- **Services** = business logic, deterministic preprocessing, reusable
- Persona data preparation belongs in **service layer**

### 1. Service Layer: Add Persona Export for Ad Copy

**File**: `viraltracker/services/persona_service.py`

Add method to export persona in ad-copy-optimized format:

```python
def export_for_ad_generation(self, persona_id: UUID) -> Dict[str, Any]:
    """
    Export persona data optimized for ad copy generation.

    Returns structured data for injection into hook selection and
    benefit variation prompts. Includes Amazon testimonials if available.

    Returns:
        Dict with keys:
        - persona_name: str
        - snapshot: str (2-3 sentence description)
        - pain_points: List[str] (top emotional + functional)
        - desires: List[str] (flattened with category context)
        - transformation: Dict[str, List[str]] (before/after)
        - their_language: List[str] (self_narratives - how they talk)
        - objections: List[str] (buying objections to address)
        - failed_solutions: List[str] (what they've tried)
        - activation_events: List[str] (what triggers purchase)
        - allergies: Dict[str, str] (what turns them off)
        - amazon_testimonials: Dict[str, List[Dict]] (if available)
    """
```

### 2. Service Layer: Add Persona Fetching Methods

**File**: `viraltracker/services/ad_creation_service.py`

```python
def get_personas_for_product(self, product_id: UUID) -> List[Dict]:
    """Get all personas linked to a product for UI dropdown."""
    # Delegate to persona_service
    pass

def get_persona_for_ad_generation(self, persona_id: UUID) -> Optional[Dict]:
    """Get persona data formatted for ad generation prompts."""
    # Call persona_service.export_for_ad_generation()
    pass
```

### 3. Workflow: Add persona_id Parameter

**File**: `viraltracker/agent/agents/ad_creation_agent.py`

Update `complete_ad_workflow()`:

```python
async def complete_ad_workflow(
    ctx: RunContext[AgentDependencies],
    product_id: str,
    reference_ad_base64: str,
    reference_ad_filename: str = "reference.png",
    project_id: Optional[str] = None,
    num_variations: int = 5,
    content_source: str = "hooks",
    color_mode: str = "original",
    brand_colors: Optional[Dict] = None,
    image_selection_mode: str = "auto",
    selected_image_paths: Optional[List[str]] = None,
    persona_id: Optional[str] = None  # NEW: Optional persona for targeting
) -> Dict:
```

**Changes**:
1. If `persona_id` provided, fetch persona data via service
2. Pass persona data to `select_hooks()` and `generate_benefit_variations()`
3. Include persona_id in run_parameters for tracking

### 4. Update select_hooks() with Persona Context

**File**: `viraltracker/agent/agents/ad_creation_agent.py`

Update function signature:
```python
async def select_hooks(
    ctx: RunContext[AgentDependencies],
    hooks: List[Dict],
    ad_analysis: Dict,
    product_name: str = "",
    target_audience: str = "",
    count: int = 10,
    persona_data: Optional[Dict] = None  # NEW
) -> List[Dict]:
```

**Prompt Enhancement**:
```
If persona_data is provided, use it to:
1. Prioritize hooks that match persona's emotional pain points
2. Prefer hooks that address persona's specific objections
3. Adapt hook language to match persona's self_narratives style
4. Consider persona's failed_solutions when selecting "vs alternatives" hooks

PERSONA CONTEXT:
{persona_data}

Select hooks that would resonate most with this specific persona.
```

### 5. Update generate_benefit_variations() with Persona Context

**File**: `viraltracker/agent/agents/ad_creation_agent.py`

Update function signature:
```python
async def generate_benefit_variations(
    ctx: RunContext[AgentDependencies],
    product: Dict,
    template_angle: Dict,
    ad_analysis: Dict,
    count: int = 5,
    persona_data: Optional[Dict] = None  # NEW
) -> List[Dict]:
```

**Prompt Enhancement**:
```
If persona_data is provided, incorporate:
1. Use persona's transformation language (before → after)
2. Address persona's specific pain points in headlines
3. Include language from their_language (self_narratives)
4. Reference their objections to overcome skepticism
5. Use amazon_testimonials quotes for authentic voice

PERSONA CONTEXT:
{persona_data}

Generate variations that speak directly to this persona's emotional triggers.
```

### 6. UI: Add Persona Selector

**File**: `viraltracker/ui/pages/01_🎨_Ad_Creator.py`

Add after product selection:

```python
# Session state
if 'selected_persona_id' not in st.session_state:
    st.session_state.selected_persona_id = None

# In the form, after product selector:
st.subheader("2. Target Persona (Optional)")

# Fetch personas for selected product
personas = []
if st.session_state.selected_product:
    product_id = st.session_state.selected_product['id']
    personas = get_personas_for_product(product_id)

if personas:
    persona_options = {"None - Use product defaults": None}
    persona_options.update({
        f"{p['name']} ({p['snapshot'][:50]}...)": p['id']
        for p in personas
    })

    selected_persona = st.selectbox(
        "Select a 4D Persona to target",
        options=list(persona_options.keys()),
        help="Persona data will inform hook selection and copy generation"
    )
    st.session_state.selected_persona_id = persona_options[selected_persona]

    # Show persona preview if selected
    if st.session_state.selected_persona_id:
        persona = next(p for p in personas if p['id'] == st.session_state.selected_persona_id)
        with st.expander("Persona Preview"):
            st.markdown(f"**{persona['name']}**")
            st.write(persona['snapshot'])
            if persona.get('pain_points'):
                st.markdown("**Key Pain Points:**")
                for pp in persona['pain_points'][:3]:
                    st.markdown(f"- {pp}")
else:
    st.info("No personas available. Create personas in Brand Research to enable targeting.")
```

Pass to workflow:
```python
result = await run_ad_workflow(
    ...,
    persona_id=st.session_state.selected_persona_id
)
```

---

## Implementation Order

### Phase 1: Service Layer (No UI changes)
1. Add `export_for_ad_generation()` to PersonaService
2. Add `get_personas_for_product()` to AdCreationService
3. Add `get_persona_for_ad_generation()` to AdCreationService
4. Verify syntax with `python3 -m py_compile`

### Phase 2: Workflow Updates
1. Add `persona_id` parameter to `complete_ad_workflow()`
2. Fetch persona data if persona_id provided
3. Update `select_hooks()` signature and prompt
4. Update `generate_benefit_variations()` signature and prompt
5. Test workflow with and without persona_id

### Phase 3: UI Integration
1. Add session state for selected_persona_id
2. Add persona dropdown after product selection
3. Add persona preview expander
4. Pass persona_id to workflow
5. Test full flow

### Phase 4: Verification
1. Test: Ad creation WITHOUT persona (unchanged behavior)
2. Test: Ad creation WITH persona (enhanced prompts)
3. Verify persona data appears in generated copy
4. Check Amazon testimonials flow through

---

## Database Changes

**None required** - Using existing tables:
- `personas_4d` - Persona data
- `product_personas` - Product-persona junction
- `ad_runs` - Already has `parameters` JSONB for storing persona_id

---

## Testing Checklist

- [ ] Ad creation works without persona (backwards compatible)
- [ ] Persona dropdown shows personas linked to selected product
- [ ] Persona preview shows key data
- [ ] `select_hooks()` prompt includes persona context when provided
- [ ] `generate_benefit_variations()` prompt includes persona context when provided
- [ ] Generated ad copy reflects persona's language/pain points
- [ ] Amazon testimonials appear in prompts when available
- [ ] persona_id stored in ad_run parameters for tracking

---

## Success Criteria

1. **No Breaking Changes**: Existing workflow works identically when no persona selected
2. **Persona Integration**: When persona selected, prompts include persona data
3. **Visible Impact**: Generated ads reflect persona's pain points and language
4. **Testimonials Used**: Amazon review quotes appear in generated copy

---

## Files to Modify

| File | Changes |
|------|---------|
| `services/persona_service.py` | Add `export_for_ad_generation()` |
| `services/ad_creation_service.py` | Add persona fetching methods |
| `agent/agents/ad_creation_agent.py` | Update workflow + tools with persona_id |
| `ui/pages/01_🎨_Ad_Creator.py` | Add persona selector dropdown |

---

## Related Documentation

- [CLAUDE.md](/CLAUDE.md) - Development guidelines, thin tools pattern
- [claude_code_guide.md](/docs/claude_code_guide.md) - Pydantic AI best practices
- [4D Persona Framework](/docs/reference/4d_persona_framework.md) - Persona model
- [Sprint 3.5 Amazon Reviews](/docs/plans/SPRINT_3.5_AMAZON_REVIEWS.md) - Testimonials source
