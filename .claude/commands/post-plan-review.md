# Post-Plan Review Workflow

You are entering **Post-Plan Review Mode**. Your task is to review code changes against the implemented plan, checking correctness, architecture compliance, and test coverage.

## Input

**Review scope (optional — defaults to all changes on current branch vs main):**
$ARGUMENTS

---

## Required Reading (Load These First)

Before proceeding, you MUST read these files — they are your review specs:

1. `agents/review/post_plan_review_orchestrator.md` - How to run the full review and produce the consolidated report
2. `agents/review/graph_invariants_checker.md` - Code correctness and architecture checks
3. `agents/review/test_evals_gatekeeper.md` - Test and eval coverage checks

Also load for context:
4. The **plan document** — find the most recent file under `docs/plans/`, or use the plan text in the current PR/issue description. If `$ARGUMENTS` specifies a plan path, use that instead.

---

## Your Process

### STEP 1: GATHER CONTEXT

1. **Identify the plan** — Read the plan document to understand what was supposed to be built
2. **Get changed files** — Run `git diff --name-only main...HEAD`
3. **Get full diff** — Run `git diff main...HEAD`
4. **Classify changed files** — Note which are graph/pipeline/agent/node files (triggers conditional checks)

### STEP 2: RUN GRAPH INVARIANTS CHECKER

Follow `agents/review/graph_invariants_checker.md` exactly:

1. Run all 6 general checks (G1-G6) against every changed file
2. If any changed files match graph/pipeline/agent/node patterns, run all 8 conditional checks (P1-P8)
3. Produce the checker's output report
4. Record the sub-verdict: PASS or FAIL

### STEP 3: RUN TEST/EVALS GATEKEEPER

Follow `agents/review/test_evals_gatekeeper.md` exactly:

1. Run all 4 general checks (T1-T4) against every changed file
2. If any changed files match graph/pipeline/agent/node patterns, run all 5 conditional checks (A1-A5)
3. Produce the gatekeeper's output report
4. Record the sub-verdict: PASS or FAIL

### STEP 4: PRODUCE CONSOLIDATED REPORT

Follow `agents/review/post_plan_review_orchestrator.md` to produce the final report:

1. Combine both sub-verdicts into the consolidated verdict
2. Build the Plan → Code → Coverage map
3. Identify top 5 risks ranked by severity
4. List missing plan items
5. Produce the minimum fix set (ordered: contracts/schemas → core logic → tests/evals → lint/format)
6. List nice-to-have improvements
7. List required tests/evals to add
8. Provide the rerun checklist

### STEP 5: RERUN LOOP (if FAIL)

If the verdict is FAIL and the user applies fixes:
1. Re-gather context (new diff)
2. Re-run both checkers on affected files only
3. Produce updated consolidated report
4. Repeat until PASS

---

## Core Rules

### Rule 1: Be Specific
- Every violation must include `file_path:line_number` and the exact fix
- Don't say "consider fixing" — say "change X to Y at path:line"

### Rule 2: Follow the Specs
- The three review spec files define the checks — don't invent new ones, don't skip any
- Use the exact output formats specified in each spec

### Rule 3: Run What You Can
- If you have terminal access, run the suggested automated checks from each spec
- If not, use Grep/Read/Glob to inspect files manually
- Always run `python3 -m py_compile` on changed Python files

### Rule 4: Minimum Fix Set Over Wishlist
- The goal is to get to PASS with the smallest change set
- Separate "must fix" (blocking) from "nice to have" (non-blocking)
- Order fixes by dependency so they can be applied sequentially

---

## Start Now

Begin by:
1. Reading the three review spec files
2. Identifying the plan document
3. Gathering the changed files and diff
4. Running Step 2 (Graph Invariants Checker)
