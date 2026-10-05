---
name: pr-team
description: Lead an agent team that ships a feature as many small, self-contained PRs in parallel. Plans the task graph and folder map, fans builders out horizontally or vertically, adds a PR watcher that routes human review comments back to builders, and spawns a short-lived per-PR reviewer only for big PRs. Use when the user wants to build a feature with parallel agents, small PRs, or continuous PR delivery.
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

## Preflight (stop and tell the user if any fails; no silent fallback)
| # | Check | Fix |
|---|---|---|
| a | The session is an **interactive terminal `claude`**, not an Agent SDK, `claude -p`, or IDE-extension session (the VS Code extension runs SDK sessions). In those, `Agent(name=…)` starts a plain subagent, not a teammate ([agent-teams](https://code.claude.com/docs/en/agent-teams.md)) | Open a terminal (the VS Code integrated terminal works) and run `claude` there |
| a | `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` is `1` | Add it to `settings.json` `env` (`bootstrap.sh` does this), restart |
| b | `TaskCreate` is in your tool list. On models newer than Opus 4.7 / Sonnet 4.6 the Task tools are off unless opted in ([Task tool availability](https://code.claude.com/docs/en/tools-reference.md#task-tool-availability)) | Restart with `CLAUDE_CODE_ENABLE_TODO_TOOLS=1 claude`, or `claude --allowedTools TaskCreate` |
| c | **After spawning the first teammate**, `ls ~/.claude/teams/*/config.json` finds the team config and it lists that teammate | If missing, the teammate is a plain subagent: stop it and tell the user the team didn't form (check a and the env var) |
| d | `teammateMode` is `in-process`, `auto` or `tmux`. tmux is **not** required; in-process works in any terminal | — |
| e | `gh auth status` ok, repo has a GitHub remote | `gh auth login` |
| e | `git status` clean on `main` | Commit or stash first |
| f | If the repo has `scripts/stack`: run `scripts/stack infra ensure`, then `scripts/stack template refresh` | Show the error to the user; don't start docker yourself |

Teammate permission prompts appear in **your** session. Suggest the user allow `Bash(gh:*)` and `Bash(git:*)` for this project if they haven't.

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
   - 1 `pr-watcher`, always.
   - **No standing reviewer.** Reviewers are spawned per big PR in Step 3 (cap `max_reviewers`, default 3; ask the user if they want another cap).
7. **Review budget.** Ask the user how many open PRs they can keep up with (default 5). This is the WIP limit on open PRs, not on agents.
8. Write `RUN/plan.md` and present it: task table with columns `id | folder | files | blockedBy | flag | owner | PR | size | reviewer | state`, plus shape, team, review budget and `max_reviewers`. `size` and `reviewer` stay empty until the PR is classified in Step 3. Exit plan mode only after the user approves.

## Step 2 · Spawn

1. Create one shared task per planned task (`TaskCreate`), then set `blockedBy` (`TaskUpdate addBlockedBy`). Description first line is `folder: <path>` (builders filter claims on it), then files, acceptance criteria and flag.
2. Spawn teammates with predictable names: `builder-1..N` and `pr-watcher`. Use the plugin agent types `bach:pr-builder` and `bach:pr-watcher`. Run preflight check (c) right after the first spawn.
   - If the runtime refuses a plugin agent type as a teammate, spawn a general teammate and paste the body of `AGENTS/<role>.md` at the top of its prompt.
   - Every prompt names **your** address for SendMessage: read it from the `members` entry with agent type `team-lead` in `~/.claude/teams/*/config.json`.
   - Builder prompt: its name, the repo root, your address, "claim tasks from the task list", the folder-ownership rule, and its slot hint if the repo has `scripts/stack`.
   - Watcher prompt: `POLL=<absolute path>`, `STATE=<absolute RUN/state.json>`, the list of builder names, your address.
3. Require plan approval for builders: approve a builder's plan only if its files stay inside the task's folder.

## Step 3 · Review on demand

A builder reports each PR to you right after `gh pr create`, with size hints. Classify it at once (read `gh pr diff <n> --name-only` and `gh pr view <n> --json additions,deletions` if the hints are thin).

**Big** = any of:
- interactive UI (popup, panel, form, buttons, animation, toggle) or a visible page change
- API contract, schema or migration, or security-sensitive code (auth, secrets, input sanitising, permissions)
- more than ~300 changed lines, excluding generated files (lockfiles, codegen output, snapshots)
- the builder says it is not verified in a browser, or that tests were skipped

Everything else is **small**.

| Size | Action |
|---|---|
| small | Tell the human: "PR #N ready, no pre-review needed (small: <reason>)". |
| big | Spawn ONE teammate `reviewer-pr<N>` (`bach:pr-reviewer`) for that PR only. Prompt: PR number, owning builder name, your address, slot hint (if `scripts/stack`). Tell the human: "PR #N ready, pre-review running (big: <reason>). Wait for label `pre-review:ok` before merging." |

- Several big PRs → several reviewers in parallel, at most `max_reviewers` alive. Over the cap, queue the PR in plan.md and spawn when a reviewer finishes.
- A reviewer that sends its one-line verdict is done: send it a shutdown request. Update `size` and `reviewer` in plan.md.
- If a big PR merges mid-review, the reviewer stops on its own (it re-checks state); you just record it.

## Step 4 · Run (your loop)

You react to teammate messages and task changes. Don't poll.

Teammates send you an `idle_notification` after each turn and stay addressable; idle doesn't mean done. The task list and `RUN/plan.md` are the source of truth.

| Signal | Action |
|---|---|
| Builder plan arrives | Approve if in-scope; otherwise send it back with the rubric line it breaks |
| Builder needs a file outside its folder | Make a new task for that folder (or a contract task), add `blockedBy`, tell the builder to finish without it or wait |
| Builder reports a new PR | Step 3: classify, then tell the human or spawn `reviewer-pr<N>` |
| Reviewer verdict (`ok` / `blocked`) | Record in plan.md, shut the reviewer down. `ok`: tell the human "PR #N pre-review ok, ready to merge". `blocked`: the reviewer already talks to the builder; tell the human only if it needs a decision |
| Watcher: human-comment fix round started / ended | Record in plan.md. Don't route fixes yourself; the watcher is the single router for human comments |
| Watcher: PR merged | Dependent tasks unblock automatically. If a `reviewer-pr<N>` is still alive, it stops on its own; shut it down. If builders are idle and ready tasks exist, keep them claiming |
| Open PRs ≥ review budget (watcher recounts via `gh`) | Tell builders to pause after their current task. Resume when PRs merge |
| Two builders claimed the same task | Tell the loser to stop. Keep the earlier PR or branch, close the duplicate |
| Builder stuck 3+ attempts on the same error | Stop it, re-scope or reassign the task |
| No tasks left and no open PRs | Ask builders, any reviewers, then the watcher to shut down. Summarise PRs merged |

## Rules
- **Never write feature code.** If you catch yourself editing, stop and make a task instead.
- Never merge, approve, or push to `main`. The human merges.
- Two agents never own the same folder at the same time. Give each builder exactly one folder; it is also the builder's claim filter.
- No standing reviewer. One short-lived `reviewer-pr<N>` per big PR, at most `max_reviewers` at once. Small PRs go straight to the human.
- Merge gate for big PRs is the label `pre-review:ok`. Say so to the human for every big PR. A merged PR is never reviewed after the fact unless the human asks.
- One router per channel: the watcher routes human PR comments; the reviewer talks to the owning builder directly. You don't relay either.
- Shared infra (docker, compose, databases) belongs to you and the human. Agents use `scripts/stack lease/run/release` when the repo has it.
- Keep `RUN/plan.md` current: task → owner → PR → size → reviewer → state. It is how a resumed lead recovers (`/resume` doesn't restore in-process teammates), and the only history: completed tasks vanish from TaskList. Update it when a task completes.
- Commands you hand the user must be zsh-safe: no bare `!`, no trailing `#` comments.
