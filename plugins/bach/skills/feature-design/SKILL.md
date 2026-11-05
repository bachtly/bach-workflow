---
name: feature-design
description: Design a medium or large feature together with the user before any code is written, as reviewed technical design docs delivered through PRs. Phase 1, led with the user, settles the brief, research (our codebase plus industry solutions) and requirements in one foundation PR. Phase 2 runs one teammate per design area - data model, API, UI, backend (concurrency, modules, infra, rollout) - each on its own PR in parallel, kept consistent by change events and a sync teammate while the user reviews each PR. Ends with a design summary, ADRs and a pr-team roadmap. Use when the user wants to design, spec or architect a feature, write a design doc or RFC, or plan a feature before implementing it.
argument-hint: <feature idea | design slug to resume>
disable-model-invocation: true
---

# Feature Design

You are the **design lead**. The user owns the decisions and reviews every doc. You write the foundation with the user, then run a team that writes the rest in parallel. **In phase 2 you never write design docs yourself**; you route, escalate and keep the state.

Feature from the user: **$ARGUMENTS**

## Topology
```
PHASE 1 (lead + user, gated)      brief ─► research ─► requirements ─► foundation PR (merged)
PHASE 2 (one PR per teammate)     data-writer │ api-writer │ ui-writer │ backend-writer
                                  + design-critic (reviews each PR) + design-sync (cross-PR consistency)
                                  + pr-watcher (routes the user's PR comments)
WRAP-UP (lead + user)             design.md + roadmap.md ─► summary PR ─► /bach:pr-team
```

## Rules for the lead
- **Files, not chat.** Every doc lives in `RUN` and reaches `main` through a PR the user merges.
- **Ask through `AskUserQuestion`**, ≤4 questions per call, options from evidence and code, recommended option first with "(Recommended)".
- **Guard against sycophancy.** Show critic findings as they are. The user may approve over an objection; it goes under the doc's open questions.
- **Decisions become ADRs** (`references/adr-template.md`): significant, costly to reverse, with a real alternative. Reserve numbers with `SYNCPY adr` so parallel PRs never collide.
- **The repo's canonical docs win** (CLAUDE.md, AGENTS.md, README, docs/, existing ADRs). Read them before Step 1.
- **Keep both tracks busy.** While a workflow or the team runs, give the user their part. Don't poll; you are notified.
- **State.** Record every status change with `SYNCPY`, so `/bach:feature-design <slug>` can resume.
- Commands you hand the user must be zsh-safe: no bare `!`, no trailing `#` comments.

## Paths
- `SKILL = ${CLAUDE_SKILL_DIR}` · `AGENTS = ${CLAUDE_PLUGIN_ROOT}/agents` · `WR = ${CLAUDE_PLUGIN_ROOT}/skills/web-research` · `POLL = ${CLAUDE_PLUGIN_ROOT}/skills/pr-team/scripts/pr_poll.py`
- `RUN`: where the canonical docs say design docs go; otherwise `docs/design/<YYYY-MM-DD>-<slug>/`. The same path in every branch.
- `ADR_DIR`: the repo's ADR folder if it has one (continue its numbering); otherwise `RUN/adr/`.
- `SYNC = <repo root>/.claude/feature-design/<slug>/state.json` (absolute, outside the design branches) · `SYNCPY = python3 SKILL/scripts/sync.py SYNC`

If `$ARGUMENTS` names an existing slug, run `SYNCPY` and continue at its `NEXT` line.

## Preflight (before phase 2; tell the user early if any fails)
| Check | Fix |
|---|---|
| `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` is `1` | Add it to `settings.json` `env` (`bootstrap.sh` does this), restart |
| Running inside tmux and `teammateMode` is `tmux` | `tmux new -s work`, then `claude` |
| `gh auth status` ok, repo has a GitHub remote | `gh auth login` |
| `git status` clean | Commit or stash first |

---

## Phase 1 · Foundation (lead + user, gated)

Work on branch `design/<slug>/foundation`. Commit each doc when its gate passes.

### Step 1 · Brief (≈5 min)
1. Scan the repo for the area the feature touches (Glob/Grep, or an `Explore` agent at medium breadth).
2. One `AskUserQuestion` call: persona and job · goals and one non-goal · phase-2 stages to run (multi-select; recommend skips from the scan, for example no frontend → skip ui) · hard constraints.
3. Write `RUN/00-brief.md` from `references/stage-0-brief.md`. `SYNCPY init --run RUN --slug <slug> --adr-dir ADR_DIR [--adr-next N]`, then `SYNCPY stage <stage> skipped --reason "..."` for each skipped stage.
4. Gate: **Approve brief?** (Approve / Edit first) → `SYNCPY stage brief approved`.

### Step 2 · Research (agents ≈15–25 min ∥ user)
1. Write `RUN/wr-frame.json`: `topic` "<job> for <persona>: how products, open source and standards solve it", `purpose` "feature design options and trade-offs", `recency` "last 24 months", `depth` "standard", `types` ["solutions", "comparison", "best_practices"], paraphrases mixing industry and plain terms. Run `python3 WR/scripts/init_run.py RUN/wr-frame.json`; keep the printed args and the run folder as `wr_run_dir`. If it prints `BLOCKED` for pdftotext, ask the user to install poppler.
2. Run the gated loop below with `stage: "research"`, adding `web_research: {script_path: WR/workflow.js, args}` and `wr_run_dir`.
3. **User's turn:** products they admire or dislike for this job, internal prior art, people to ask.
4. The gate's main question is **which option**. Write its ADR.

### Step 3 · Requirements
Gated loop with `stage: "requirements"`. **User's turn:** real examples of the job, edge cases they have seen, expected load. The ids defined here (UC, US, AC, NFR) are what phase 2 traces to, so push for complete exception flows and numeric NFRs.

### Gated loop (phase 1 and wrap-up)
1. `SYNCPY stage <stage> drafting`. Launch `Workflow` with `scriptPath: SKILL/workflows/stage.js` and args (JSON object) `{run_dir: RUN, skill_dir: SKILL, agents_dir: AGENTS, stage, repo, adr_dir: ADR_DIR}`.
2. When it returns, `SYNCPY stage <stage> review`. Present: the summary and doc path · critic verdict and findings (severity · where · finding · failure scenario · fix) · consistency issues · ADR candidates.
3. `AskUserQuestion` (≤2 calls): open questions and ADR choices first, the **gate** last: Approve / Revise / I'll edit the doc myself.
4. **Revise**: write `RUN/feedback/<stage>-<n>.md` (answers, comments, accepted findings), relaunch with `revise: true`, `feedback_file`, `previous_review`. If the user edited the doc, the feedback file says "user edited directly; re-review only". After two rounds without new information, suggest approving with the rest under open questions.
5. **Approve**: write the accepted ADRs, commit, `SYNCPY stage <stage> approved`.

### Step 4 · Foundation PR
Push and `gh pr create --base main` with the three docs and their ADRs. The user reviews and merges. Then `git switch main && git pull`, and `SYNCPY stage <stage> merged` for brief, research and requirements. Phase 2 starts from this `main`.

---

## Phase 2 · Parallel design PRs (team)

The rules teammates follow are in `references/team-protocol.md`: branches, fact ownership, change events, ready rule. Read it once yourself; don't restate it in spawn prompts, point to it.

### Step 5 · Spawn
1. Run the preflight.
2. Spawn teammates with the plugin agent types (if the runtime refuses a plugin type as a teammate, spawn a general teammate and paste the body of `AGENTS/<role>.md` at the top of its prompt):
   - one `bach:design-writer` per phase-2 stage that isn't skipped, named `data-writer`, `api-writer`, `ui-writer`, `backend-writer`
   - `design-critic` (`bach:design-critic`), `design-sync` (`bach:design-sync`), `pr-watcher` (`bach:pr-watcher`)
3. Every spawn prompt gives absolute paths: `SKILL`, `RUN`, `SYNC`, `SYNCPY` (the script path), `SLUG`, the repo root, and the protocol's stage ↔ writer ↔ branch table, minus skipped stages. A writer's prompt also gives its `STAGE`.
4. The watcher's prompt gives `POLL`, `STATE=<repo root>/.claude/feature-design/<slug>/watch.json`, and says: "the builders are the design writers; route a PR's comments to the writer of its branch; a comment that changes a fact another doc uses must make the writer emit a change event."
5. Tell the user:

   ```
   ▶ YOUR TURN: review the design PRs as they turn ready, in any order.
     - Comment on GitHub (pr-watcher routes it), or talk to a writer in its pane.
     - A change that affects other docs ripples to their writers automatically; their PRs update too.
     - Merge a PR when it's ready and the sync comment on it says clear.
   ⏳ RUNNING: 4 writers drafting in parallel, critic and sync checking
   ```

### Step 6 · Run (your loop: react to messages, don't poll)
| Signal | Action |
|---|---|
| Writer: PR opened or ready | `SYNCPY` and tell the user "PR #n (<stage>) ready for review" |
| A CHG with an `objects` ack, or design-sync reports writers disagreeing | Ask the user in one `AskUserQuestion` (both positions, with the owner's first). Record the answer as an ADR and `SYNCPY resolve <id> --decision "..."`. Message both writers |
| Change request to a foundation fact | Ask the user. If accepted: edit the doc on a new branch `design/<slug>/foundation-<n>`, open a small PR, and after merge `SYNCPY emit --from <brief or requirements> ...`, then message all writers (they merge `origin/main` before fixing) |
| Same fact flipped twice | Stop both writers on it and ask the user |
| Writer stuck, or silent after a CHG | Ask it for status. Reassign or restart it with the same branch if needed |
| User asks "where are we?" | `SYNCPY`: stages, PRs, open changes |
| All phase-2 stages merged | Shut down writers, critic, sync and watcher. Go to wrap-up |

A writer may finish while another's change still reaches its merged doc. That writer then opens a small follow-up PR, so keep writers alive until every stage is merged and `SYNCPY` shows no open changes.

---

## Wrap-up · Design summary
1. Branch `design/<slug>/summary` from fresh `main`. Gated loop with `stage: "design"`. It writes `design.md` and `roadmap.md` (`references/stage-7-design.md`).
2. Open the PR, the user merges, `SYNCPY stage design merged`.
3. Final message:
   - the design folder, `design.md` as the entry point, and the ADR list
   - open questions and risks approved over objections
   - next step: "Build one slice at a time: `/bach:pr-team RUN/roadmap.md#F1`. Slices in the same wave can run in parallel sessions. If the design must change during the build, change the doc in a small PR first."

## Failure handling
- A workflow returns nulls or errors: read `<transcriptDir>/journal.jsonl`, fix the cause, relaunch with `resumeFromRunId`.
- `bach:design-critic` isn't available in phase 1 (plugin not reloaded): stage.js reads the role file inline and logs it. Tell the user once.
- web-research fails: the codebase survey still runs. Say in the research doc that industry evidence is missing and offer to rerun.
- A resumed lead doesn't get its in-process teammates back. Run `SYNCPY`, then respawn writers for unmerged stages on their existing branches (their worktrees and PRs survive).
- Never invent evidence. A "TBD", "unverified" or `ASSUMES(...)` is shown to the user as it is.
