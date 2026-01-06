# Phase 7 Checkpoint: Research Insights UI

**Date:** 2026-01-05
**Status:** Complete
**Phase:** 7 - Research Insights UI

## Overview

Phase 7 creates a dedicated UI page for viewing and managing angle candidates from all research sources. This is the user-facing interface for the Angle Pipeline, allowing users to review insights, examine evidence, and promote candidates to full angles.

## Completed Work

### 1. New UI Page Created

**File:** `viraltracker/ui/pages/32_💡_Research_Insights.py`

### 2. Features Implemented

| Feature | Description |
|---------|-------------|
| **Stats Overview** | Shows total candidates, pending review, HIGH confidence, and promoted counts |
| **Source Breakdown** | Displays candidate counts by source type with icons |
| **Filtering** | Filter by status, source type, and confidence level |
| **Frequency-Ranked Display** | Candidates grouped by confidence (HIGH → MEDIUM → LOW) |
| **Candidate Cards** | Shows name, belief, source, type, frequency score, confidence |
| **Evidence Viewer** | Drill-down view showing all evidence items for a candidate |
| **Promote Workflow** | Two-step process: Select Persona → Select JTBD → Create Angle |
| **Reject Functionality** | Confirm dialog before rejecting candidates |
| **Recently Promoted** | Shows last 5 promoted candidates with angle IDs |

### 3. UI Layout

```
┌─────────────────────────────────────────────────────────────┐
│  💡 Research Insights                     [Brand ▼] [Prod ▼] │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  📊 Overview                                                 │
│  [Total: 45] [Pending: 32] [HIGH: 8] [Promoted: 13]         │
│  By Source: 🧠 Belief RE: 15 | 🔍 Reddit: 12 | 🎯 Comp: 8...│
│                                                              │
├────────────────────────────────────┬────────────────────────┤
│  Filters: [Status ▼] [Source ▼]    │  ✅ Recently Promoted  │
│           [Confidence ▼] [Refresh] │  • "Morning stiff..." │
│                                    │    → Angle #abc12...   │
├────────────────────────────────────┴────────────────────────┤
│                                                              │
│  📋 Candidates (32)                                         │
│                                                              │
│  🔴 HIGH Confidence (8)                                     │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ 🔴 Morning stiffness is first sign of problems       │   │
│  │ "Joint pain often starts as morning stiffness..."    │   │
│  │ 🧠 Belief RE | Pain Signal | Evidence: 7 | 2026-01-05│   │
│  │ [👁️ Evidence] [⬆️ Promote] [❌ Reject]               │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  🟡 MEDIUM Confidence (12)                                  │
│  ...                                                        │
│                                                              │
│  🟢 LOW Confidence (12)                                     │
│  ...                                                        │
└─────────────────────────────────────────────────────────────┘
```

### 4. Promote Workflow

The promotion workflow guides users through:

1. **Select Persona** - Dropdown of personas for the product's brand
2. **Select JTBD** - Dropdown of JTBDs for the selected persona+product combination
3. **Create Angle** - Button to finalize promotion

On success:
- Creates new `belief_angles` record linked to JTBD
- Updates candidate status to "approved"
- Sets `promoted_angle_id` on candidate
- Clears cache and shows success message

### 5. Evidence Viewer

Shows detailed evidence for each candidate:
- Evidence text (quoted)
- Source type and URL
- Post ID (for Reddit quotes)
- LLM confidence score
- Engagement score (upvotes)
- Created timestamp

## Files Modified/Created

| File | Status | Description |
|------|--------|-------------|
| `viraltracker/ui/pages/32_💡_Research_Insights.py` | Created | New UI page |

## Testing Checklist

- [x] Syntax verified with `python3 -m py_compile`
- [x] All imports verified in venv
- [ ] Page loads without errors (manual test)
- [ ] Filter by status works (manual test)
- [ ] Filter by source works (manual test)
- [ ] Filter by confidence works (manual test)
- [ ] Evidence viewer shows all evidence items (manual test)
- [ ] Promote workflow creates angle (manual test)
- [ ] Reject confirmation works (manual test)
- [ ] Recently promoted shows correct data (manual test)

## Service Methods Used

From `AngleCandidateService`:
- `get_candidates_for_product()` - Fetch filtered candidates
- `get_candidate()` - Fetch single candidate with evidence
- `get_evidence_for_candidate()` - Fetch evidence list
- `get_candidate_stats()` - Get statistics for overview
- `promote_to_angle()` - Promote candidate to belief_angle
- `reject_candidate()` - Reject a candidate

From `PlanningService`:
- `get_jtbd_for_persona_product()` - Fetch JTBDs for promote workflow

## Constants Defined

```python
SOURCE_LABELS = {
    "belief_reverse_engineer": "Belief RE",
    "reddit_research": "Reddit",
    "ad_performance": "Ad Performance",
    "competitor_research": "Competitor",
    "brand_research": "Brand",
}

TYPE_LABELS = {
    "pain_signal": "Pain Signal",
    "jtbd": "Job to Be Done",
    "pattern": "Pattern",
    "ad_hypothesis": "Ad Hypothesis",
    ...
}

CONFIDENCE_BADGES = {
    "HIGH": ("🔴", "red"),
    "MEDIUM": ("🟡", "orange"),
    "LOW": ("🟢", "green"),
}
```

## Session State Keys

| Key | Purpose |
|-----|---------|
| `ri_status_filter` | Current status filter value |
| `ri_source_filter` | Current source filter value |
| `ri_confidence_filter` | Current confidence filter value |
| `ri_selected_candidate_id` | ID of candidate in evidence view |
| `ri_promote_candidate_id` | ID of candidate in promote workflow |
| `ri_confirm_reject` | ID of candidate pending rejection |

## Next Steps (Phase 8+)

### Phase 8: Scheduler Belief-First Support
- Add belief-first support to Ad Scheduler
- Add plan_id support to scheduled_jobs
- Add angle loop logic to scheduler worker

### Phase 9: Pattern Discovery Engine
- Add embedding generation for candidates
- Implement clustering algorithm
- Add novelty scoring
- Create pattern discovery UI section

### Phase 10: Documentation & Logfire Integration
- Update CLAUDE.md with Angle Pipeline section
- Create pydantic-graph for extraction flow
- Add configurable settings to Settings page

## Architecture Notes

```
User Flow:
1. User selects Brand + Product
2. System shows stats and filtered candidates
3. User can:
   - View evidence for any candidate
   - Promote HIGH confidence candidates to angles
   - Reject irrelevant candidates
4. Promoted candidates create belief_angles linked to JTBD
```

```
Data Flow:
angle_candidates (status=candidate)
        │
        ├─── View Evidence ──→ angle_candidate_evidence
        │
        ├─── Promote ──→ belief_angles (new record)
        │               angle_candidates.status = 'approved'
        │               angle_candidates.promoted_angle_id = angle.id
        │
        └─── Reject ──→ angle_candidates.status = 'rejected'
```
