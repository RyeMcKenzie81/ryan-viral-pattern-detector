# Chat-First Service Access — Status

> **Plan:** [PLAN.md](PLAN.md) (originally office-hours, 2026-04-15)
> **Source:** `~/.gstack/projects/RyeMcKenzie81-ryan-viral-pattern-detector/ryemckenzie-RyeMcKenzie81-framework-eval-design-20260415-123723.md`
> **Sequence:** A (Ops Copilot) → C (API foundation) → Next.js → MCP

This doc tracks the implementation state of the chat-first roadmap. **Update it whenever a phase increment ships** so future sessions don't have to re-audit from scratch.

---

## Phase Status (2026-04-29)

| Phase | Description | Status | % |
|-------|---|---|---|
| **Phase 1** | Ops Copilot — read-only chat tools, job management, push notifications | Substantially shipped | ~95% |
| **Phase 2** | High-value services — competitor intel, image analysis, SEO, ad creation, pattern discovery | In progress | ~75% |
| **Phase 3** | API foundation — FastAPI REST endpoints over services, auth, rate limiting | Not started | 0% |
| **Phase 4** | Next.js frontend — port high-pain Streamlit pages | Not started | 0% |
| **Phase 5** | MCP server — expose tools as MCP for Claude Code / Cursor / Claude Desktop | Not started | 0% |

---

## Phase 1 — Shipped

**Core query tools (6/6):** `get_ad_details`, `get_top_ads`, `get_breakdown_by_*`, `queue_job`, `check_job_status`, `list_recent_jobs`

**Service wiring (11/11 instantiated, 6/11 with chat tools):**

| Service | Wired | Has Tools |
|---|:-:|:-:|
| BrandResearchService | ✓ | partial |
| TemplateQueueService | ✓ | partial |
| ProductURLService | ✓ | ❌ |
| ContentPipelineService | ✓ | ❌ |
| RedditSentimentService | ✓ | ✓ |
| ProductContextService | ✓ | partial |
| BeliefAnalysisService | ✓ | ❌ |
| MetaAdsService | ✓ | partial |
| SEOProjectService | ✓ | ✓ |
| DocService | ✓ | ❌ |
| UsageTracker | ✓ | n/a (internal) |

**Infrastructure:**
- ✓ `CHAT_OPS_ENABLED` feature flag (`orchestrator.py`)
- ✓ Push notifications via 30s polling (`chainlit_app/notifications.py`)
- ✓ Duplicate job detection in `queue_job` (`ops_agent.py`)
- ✓ Per-tool provenance markers (not unified format yet)
- ❌ Deferred tool loading — all 109 tools load upfront. May not matter at this scale.

**Pre-Phase Validation Spike:** Implicitly validated — Chainlit push works, the orchestrator's static routing replaced the deferred-loading approach.

---

## Phase 2 — Shipped

- **Competitor intel** (`competitor_agent.py`): 11 tools — list, summary, LP analysis, Amazon reviews, intel pack, persona synthesis, copy briefs
- **Image analysis** (`ad_creation_agent.py`): Vision AI for product/reference ad analysis
- **SEO** (`analysis_agent.py`): 7+ tools — projects, keywords, opportunities, rankings, articles, GA4, Reddit
- **Ad creation workflows** (`ad_creation_agent.py`): 22+ tools including `complete_ad_workflow`, translations, smart edits
- **Brand research** (partial): Summary + analysis count; no pipeline triggers
- **Provenance:** Per-tool format (not unified)

---

## Phase 2 — Remaining

| Gap | Priority | Effort | Notes |
|---|---|---|---|
| **Iteration Lab + Winner DNA** | **HIGH (next up)** | 1-2 days | Services exist (`IterationOpportunityDetector`, `WinnerDNAAnalyzer`) — Streamlit-only today. Closes the "pattern discovery / winner DNA" gap from the plan. See [Next Increment](#next-increment-iteration-lab--chat) below. |
| Template recommendations | Medium | 0.5 day | Bidirectional template advice over the existing template queue. |
| Content pipeline triggers | Small | 0.5 day | `ContentPipelineService` is wired but has no chat tools. |
| `ProductURLService` chat tool | Small | <1 hour | "What product is this URL for?" |
| `DocService` knowledge base search | Small | 1-2 hours | Semantic search over docs. Requires `OPENAI_API_KEY` (already optional dep). |
| `BeliefAnalysisService` chat tools | Medium | Half day | Currently used internally by LP analysis only. |
| Unified provenance format | Small | 1-2 hours | Standardize all tool responses to `[Source: {agent} | {services} | {timestamp}]`. |

---

## Next Increment: Iteration Lab → Chat

**Goal:** Wire `IterationOpportunityDetector` and `WinnerDNAAnalyzer` services as chat tools. Closes Phase 2's "winner DNA / pattern discovery" gap and surfaces the most operationally valuable tooling currently buried in Streamlit.

**Tools to add (~6-8):**
- `find_iteration_opportunities(brand_id, days_back?)` → list of opportunities with explanations + ROAS projections
- `get_iteration_opportunity(opportunity_id)` → full details
- `act_on_opportunity(opportunity_id, action)` → execute (iterate / kill / dismiss / restore)
- `batch_iterate_winners(brand_id, top_n)` → queue iteration jobs for top performers
- `analyze_winner_dna(ad_id)` → DNA breakdown for one ad
- `analyze_winning_patterns(brand_id, days_back?)` → cross-winner DNA + action brief
- `get_iteration_track_record(brand_id)` → historical iterations + outcomes

**Service deps to add to `AgentDependencies`:**
- `IterationOpportunityDetector(supabase_client)`
- `WinnerDNAAnalyzer(supabase_client, gemini_service=...)`

**Reference services:**
- `viraltracker/services/iteration_opportunity_detector.py` (~1500 lines, full API documented)
- `viraltracker/services/winner_dna_analyzer.py`

**Reference UI** (so we know what good UX looks like): `viraltracker/ui/pages/38_🔬_Iteration_Lab.py`

**Effort:** 1-2 days CC. Each tool is a thin delegation + LLM-friendly response formatting.

---

## Deferred (See TECH_DEBT.md)

These are valuable but explicitly outside the roadmap. They're tracked in `docs/TECH_DEBT.md` so they don't get lost:

- **Item 36** — Brand Data Audit Tool (chat wrapper for `ToolReadinessService`)
- **Item 37** — Chat-Native Brand Enrichment Tools (add product/competitor/LP from chat)
- **Item 38** — Chat-Native AC2 Prerequisite Workflows (offer variants, persona building, LP blueprints — fits in Phase 4 territory)

---

## How to Update This Doc

Whenever a Phase 2+ increment ships:

1. Move items from "Remaining" to "Shipped"
2. Bump the "% Complete" in the Phase Status table
3. Update the "Next Increment" section to point at whatever's next
4. Date the change at the top: "Phase Status (YYYY-MM-DD)"

If the roadmap itself changes (new phase, reordering, scope cut), update PLAN.md and explain the change here.
