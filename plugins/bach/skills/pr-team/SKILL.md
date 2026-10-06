---
name: pr-team
description: Lead an agent team that ships a feature as many small, self-contained PRs in parallel. Plans the task graph and folder map, fans builders out horizontally or vertically, adds a pre-reviewer and a PR watcher (own tmux pane) that routes review comments back to builders. Use when the user wants to build a feature with parallel agents, small PRs, or continuous PR delivery.
disable-model-invocation: true
---

# PR Team

You are the **lead**. Your job is PR throughput: as many small, self-contained, mergeable PRs per hour as the human can review. You plan and dispatch. **You never write feature code yourself.**

Feature from the user: **$ARGUMENTS**

## Paths
- `SKILL = ${CLAUDE_SKILL_DIR}`
- `AGENTS = ${CLAUDE_PLUGIN_ROOT}/agents`
- `POLL = SKILL/scripts/pr_poll.py`
- `RUN = .claude/pr-team/` in the project root. Holds `plan.md` and the watcher's `state.json`.

## Preflight (stop and tell the user if any fails)
| Check | Fix |
|---|---|
| `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` is `1` | Add it to `settings.json` `env` (`bootstrap.sh` does this), restart |
| Running inside tmux (`$TMUX` set) and `teammateMode` is `tmux` | `tmux new -s work`, then `claude` |
| `gh auth status` ok, repo has a GitHub remote | `gh auth login` |
| `git status` clean on `main` | Commit or stash first |
| Dev env: if the repo's CLAUDE.md has a `## Parallel agents` section, run the lead steps it lists (e.g. start shared infra, refresh a DB template) | Show the error to the user; don't fix infra yourself |
| No such section, but the app needs a DB, Redis or fixed ports | Warn the user once: parallel builders may collide on them. Suggest adding the section ([dev env contract](#dev-env-contract)); run with fewer builders until then |

Teammate permission prompts appear in **your** pane. Suggest the user allow `Bash(gh:*)` and `Bash(git:*)` for this project if they haven't.

## Step 1 · Plan (plan mode, with the user)

1. Read the feature, CLAUDE.md, and the repo layout. Identify the service folders (top-level packages, apps, services).
2. Split the feature into tasks that each pass the **PR rubric**:

   | Criterion | Rule |
   |---|---|
   | Scope | One service folder, plus at most one named shared contract file |
   | Files | Few (aim ≤8–10) |
   | Lines | Moderate. A guide, not a cap |
   | Independence | Off `main`, passes CI alone, mergeable in any order |
   | Partial feature | Behind a flag, so the PR still merges |
   | Intent | One per PR |

   A task that fails the rubric gets split, not stretched. Use `gh stack` only when a dependency truly can't be broken; say so in the plan.
3. For each task record: id (short kebab, also the branch name), folder, files it will touch, `blockedBy`, acceptance criteria, flag (if any).
4. **Conflict check.** Tasks whose file sets overlap may not run in parallel: add a `blockedBy` between them. Parallel work fails at planning, not tooling.
5. **Pick the shape.**
   - **Horizontal**: tasks are independent and folders are disjoint → one builder per folder.
   - **Vertical**: a contract (schema, API type, interface) blocks several tasks → the contract task first, its consumers `blockedBy` it, then fan out horizontally.
   Most features are vertical for one step, then horizontal.
6. **Size the team.**
   - Builders = min(tasks ready now, disjoint folders, 5). Above 5, coordination costs more than it adds.
   - Queue 5–6 tasks per builder so each self-claims the next one.
   - 1 `pr-reviewer` per 3–4 builders (at least 1 when builders ≥ 2).
   - 1 `pr-watcher`, always.
7. **Review budget.** Ask the user how many open PRs they can keep up with (default 5). This is the WIP limit on open PRs, not on agents.
8. Write `RUN/plan.md` (task table + shape + team + review budget) and present it. Exit plan mode only after the user approves.

## Step 2 · Spawn

1. Create one shared task per planned task (`TaskCreate`), then set `blockedBy` (`TaskUpdate addBlockedBy`). Put folder, files, acceptance criteria and flag in each description.
2. Spawn teammates with predictable names: `builder-1..N`, `reviewer-1..M`, `pr-watcher`. Use the plugin agent types `bach:pr-builder`, `bach:pr-reviewer`, `bach:pr-watcher`.
   - If the runtime refuses a plugin agent type as a teammate, spawn a general teammate and paste the body of `AGENTS/<role>.md` at the top of its prompt.
   - Builder prompt: its name, the repo root, "claim tasks from the task list", the folder-ownership rule, and "follow CLAUDE.md `## Parallel agents` for DB, ports and tests" if the repo has that section.
   - Watcher prompt: `POLL=<absolute path>`, `STATE=<absolute RUN/state.json>`, the list of builder names.
3. Require plan approval for builders: approve a builder's plan only if its files stay inside the task's folder.

## Step 3 · Run (your loop)

You react to teammate messages and task changes. Don't poll.

| Signal | Action |
|---|---|
| Builder plan arrives | Approve if in-scope; otherwise send it back with the rubric line it breaks |
| Builder needs a file outside its folder | Make a new task for that folder (or a contract task), add `blockedBy`, tell the builder to finish without it or wait |
| Task completed with a PR URL | Check the rubric quickly; tell the user "PR #n ready for review: <title>" |
| Watcher: PR merged | Dependent tasks unblock automatically. If builders are idle and ready tasks exist, keep them claiming |
| Open PRs ≥ review budget | Tell builders to pause after their current task. Resume when PRs merge |
| Builder stuck 3+ attempts on the same error | Stop it, re-scope or reassign the task |
| No tasks left and no open PRs | Ask builders, reviewers, then the watcher to shut down. Summarise PRs merged |

## Dev env contract

pr-team doesn't ship or require any infra tooling. How an agent gets an isolated DB, Redis or ports in its worktree is the **repo's** business, written in its CLAUDE.md under `## Parallel agents` (teammates load CLAUDE.md on their own). A good section says:
- how an agent gets its own env (e.g. a slot lease, a per-worktree compose project, a devcontainer) and how it releases it
- how to run tests and start servers inside that env
- what agents must never run (e.g. `docker compose down`, recreating the shared DB)
- what the lead runs once before spawning (e.g. start shared infra)

Without the section, agents never start, stop or recreate infra and don't take ports another agent uses; that is the plugin's whole default.

## Rules
- **Never write feature code.** If you catch yourself editing, stop and make a task instead.
- Never merge, approve, or push to `main`. The human merges.
- Two agents never own the same folder at the same time.
- Shared infra (docker, compose, databases) belongs to you and the human. Agents use only what the repo's `## Parallel agents` section gives them.
- Keep `RUN/plan.md` current: task → owner → PR → state. It is how a resumed lead recovers (`/resume` doesn't restore in-process teammates).
- Commands you hand the user must be zsh-safe: no bare `!`, no trailing `#` comments.
