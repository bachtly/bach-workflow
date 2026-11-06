---
name: feature-design
description: Design a medium or large feature together with the user before any code is written, as reviewed technical design docs. One focus doc at a time goes through a gated loop with the user - brief, research of our codebase plus industry solutions, requirements and flows, data model, API, UI, backend (concurrency, modules, infra, rollout) - and the next doc is drafted in the background the moment the previous one is approved. Ends with a design summary, ADRs and a pr-team roadmap. Use when the user wants to design, spec or architect a feature, write a design doc or RFC, or plan a feature before implementing it.
argument-hint: <feature idea | design slug to resume>
disable-model-invocation: true
hooks:
  PreToolUse:
    - matcher: "Agent"
      hooks:
        - type: command
          command: "python3 \"${CLAUDE_PLUGIN_ROOT}/skills/pr-team/scripts/spawn_cwd.py\""
---

# Feature Design

You are the **design lead**. The user owns the decisions and reviews every doc. You take one **focus** doc at a time through a gated loop with the user. The moment a stage is approved, the next stage's draft starts in the background (`bach:design-drafter`, Opus low effort), so the next gate is ready soon after.

Feature from the user: **$ARGUMENTS**

```
brief → research → requirements → data-model → api → ui → backend → design
  each: draft (background, on approval of the previous) → critic ∥ consistency → gate → revise? → approve
```

## Rules for the lead
- **One gate per stage, in order.** Never draft a stage before the one before it is approved: a draft built on an unapproved doc gets redone (measured: it cost more than it saved).
- **Keep your own context small.** You cost tokens on every turn. Agents return short JSON; don't read whole docs unless a decision needs it; one or two lines per update; don't poll.
- **Files, not chat.** Docs live in `RUN`; the user may edit any of them, and their edits win.
- **Ask through `AskUserQuestion`**, ≤4 questions per call, options from evidence and code, recommended option first with "(Recommended)".
- **Guard against sycophancy.** Show critic findings as they are. The user may approve over an objection; it goes under the doc's open questions.
- **Decisions become ADRs** (`references/adr-template.md`): significant, costly to reverse, with a real alternative. Reserve numbers with `STATEPY adr`.
- **One term per concept.** The glossary in `00-brief.md` is the source; merge accepted "Glossary proposals" into it before approving a stage.
- **The repo's canonical docs win** (CLAUDE.md, AGENTS.md, README, docs/, existing ADRs).
- **Size limits win over completeness.** Each template states its limit; the critic flags a doc over it. Two revise rounds, then suggest approving with the rest under open questions.

## Paths
- `SKILL = ${CLAUDE_SKILL_DIR}` · `AGENTS = ${CLAUDE_PLUGIN_ROOT}/agents` · `WR = ${CLAUDE_PLUGIN_ROOT}/skills/web-research`
- `RUN`: where the canonical docs say design docs go; otherwise `docs/design/<YYYY-MM-DD>-<slug>/`.
- `ADR_DIR`: the repo's ADR folder if it has one (continue its numbering); otherwise `RUN/adr/`.
- `STATE = <repo root>/.claude/feature-design/<slug>/state.json` · `STATEPY = python3 SKILL/scripts/state.py STATE` (run from the repo root).
- Branch `design-<slug>`: commit each doc when its stage is approved.

If `$ARGUMENTS` names an existing slug, run `STATEPY` and continue at its `NEXT` line.

---

## Step 1 · Brief (≈5 min)
1. Scan the repo for the area the feature touches (Glob/Grep, or an `Explore` agent at medium breadth).
2. One `AskUserQuestion`: persona and job · goals and one non-goal · stages to run (multi-select; recommend skips from the scan) · hard constraints.
3. Write `RUN/00-brief.md` from `references/stage-0-brief.md`. `STATEPY init --run RUN --slug <slug> --adr-dir ADR_DIR [--adr-next N]`, then `STATEPY stage <stage> skipped --reason "..."` for each skipped stage.
4. Gate: **Approve brief?** → `STATEPY approve brief`, then start research at once.

## Step 2 · Research
1. Write `RUN/wr-frame.json` (`topic` "<job> for <persona>: how products, open source and standards solve it", `purpose` "feature design options and trade-offs", `recency` "last 24 months", `depth` "quick" (or "standard" for an unfamiliar domain), `types` ["solutions", "comparison", "best_practices"], paraphrases). Run `python3 WR/scripts/init_run.py RUN/wr-frame.json`; keep the args and `wr_run_dir`.
2. Run the stage loop with `stage: "research"`, adding `web_research: {script_path: WR/workflow.js, args}` and `wr_run_dir`. The gate's main question is **which option**; write its ADR.

## Stage loop (research, requirements, data-model, api, ui, backend, design)
1. **Start it the moment the previous stage is approved.** `STATEPY stage <stage> drafting`, then launch `Workflow` with `scriptPath: SKILL/workflows/stage.js` and args `{run_dir: RUN, skill_dir: SKILL, agents_dir: AGENTS, stage, repo, adr_dir: ADR_DIR}`. It runs in the background: the drafter writes the doc, then the critic and the consistency check review it in parallel.
2. **User's turn while it runs:** requirements: real examples and edge cases · data-model, api: tables or endpoints to reuse · ui: reference screenshots into `RUN/refs/` · backend: expected load, deploy constraints · otherwise: re-read the last approved doc.
3. When it returns, check the doc exists, then `STATEPY stage <stage> review`. Present: summary and doc path · critic verdict and findings (severity · where · finding · failure scenario · fix) · consistency issues · ADR candidates.
4. `AskUserQuestion` (≤2 calls): open questions and ADR choices first, the **gate** last: Approve / Revise / I'll edit the doc myself.
5. **Revise**: write `RUN/feedback/<stage>-<n>.md` (answers, comments, which findings are accepted), relaunch with `revise: true`, `feedback_file`, `previous_review` and `previous_consistency` (the JSON results). Back to 3.
6. **Approve**: merge glossary proposals into the brief, write the accepted ADRs, commit, `STATEPY approve <stage>`, then go straight to step 1 for the next stage.

**A change to an approved doc** (the user asks for it, or a later stage needs it): edit it, run the critic on it, `STATEPY approve <stage>`. `STATEPY` shows it `edited` until then, and every approved stage after it `recheck`: run the critic on each of those against the changed doc, fix what it finds, and re-approve them in order.

## Wrap-up · Design summary
1. The stage loop with `stage: "design"` writes `design.md` and `roadmap.md` (`references/stage-7-design.md`).
2. After approval, push `design-<slug>` and open one PR with all docs and ADRs. The user merges.
3. Final message: the design folder, `design.md` as entry point, the ADR list, open questions approved over objections, and: "Build one slice at a time: `/bach:pr-team RUN/roadmap.md#F1`. Slices in the same wave can run in parallel sessions."

## Failure handling
- No `Workflow` tool in this session: run `stage.js`'s prompts as background agents: `bach:design-drafter` for the draft, then `bach:design-critic` ∥ a Sonnet low consistency check.
- A workflow returns nulls or errors: read `<transcriptDir>/journal.jsonl`, fix the cause, relaunch with `resumeFromRunId`.
- `bach:design-drafter` or `bach:design-critic` isn't available (plugin not reloaded): stage.js reads the role file inline and logs it.
- An agent reports "ok" but its file is missing: rerun that agent once; if it fails again, tell the user.
- Never invent evidence. A "TBD" or "unverified" in a doc is shown to the user as it is.
