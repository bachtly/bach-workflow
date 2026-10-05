---
name: pr-team
description: Lead an agent team that ships a feature as many small, self-contained PRs in parallel. Plans the task graph and folder map, fans builders out horizontally or vertically, adds a pre-reviewer and a PR watcher (own tmux pane) that routes review comments back to builders. Opt-in `review: on-demand` replaces the standing reviewer with a short-lived per-PR reviewer for big PRs only. Use when the user wants to build a feature with parallel agents, small PRs, or continuous PR delivery.
disable-model-invocation: true
---

# PR Team

You are the **lead**. Your job is PR throughput: as many small, self-contained, mergeable PRs per hour as the human can review. You plan and dispatch. **You never write feature code yourself.**

Feature from the user: **$ARGUMENTS**

## Paths
- `SKILL = ${CLAUDE_SKILL_DIR}`
- `AGENTS = ${CLAUDE_PLUGIN_ROOT}/agents`
- `POLL = SKILL/scripts/pr_poll.py`
- `STACK` = the app stack CLI, only when the repo root has `stack.toml`: the repo's own `scripts/stack` if it has one, else `SKILL/stack/stack` (absolute path). See [App stack](#app-stack).
- `RUN = .claude/pr-team/` in the project root. Holds `plan.md` and the watcher's `state.json`.

## Preflight (stop and tell the user if any fails)
| Check | Fix |
|---|---|
| `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` is `1` | Add it to `settings.json` `env` (`bootstrap.sh` does this), restart |
| Running inside tmux (`$TMUX` set) and `teammateMode` is `tmux` | `tmux new -s work`, then `claude` |
| Interactive terminal `claude`, not Agent SDK, `claude -p` or the VS Code extension chat (those spawn plain subagents, not teammates) | Fail: "pr-team needs an interactive terminal session". Run `claude` in a terminal |
| Task tools present: `CLAUDE_CODE_ENABLE_TODO_TOOLS=1`, and `TaskCreate` loads via ToolSearch (the Task tools are deferred; off by default on models newer than Opus 4.7 / Sonnet 4.6, see [Task tool availability](https://code.claude.com/docs/en/tools-reference.md#task-tool-availability)) | Fail: "Task tools missing". Restart with `CLAUDE_CODE_ENABLE_TODO_TOOLS=1 claude`, or `claude --allowedTools TaskCreate` |
| After the first spawn, `~/.claude/teams/*/config.json` lists the teammate | Fail: "team didn't form, teammate is a plain subagent". Stop it; no subagent fallback |
| After every spawn, that member's `cwd` in `~/.claude/teams/<team>/config.json` equals the repo root (see [Teammate cwd](#teammate-cwd)) | `shutdown_request` the teammate, `cd <repo root>`, respawn it |
| `gh auth status` ok, repo has a GitHub remote | `gh auth login` |
| `git status` clean on `main` | Commit or stash first |
| Repo has `stack.toml`: run `$STACK infra ensure`, then `$STACK template refresh`. No `stack.toml` but the app needs a DB/Redis/ports: offer to create one from `SKILL/stack/stack.example.toml` | Show the error to the user; don't start docker yourself |

### Teammate cwd
A tmux teammate starts in **your current Bash cwd**, and that cwd persists between your commands. A teammate started in a subfolder (e.g. `RUN`) is treated as a different project: the repo's `.claude/settings.json` is not loaded, so it has no Task tools (and likely no project hooks). So:
- Never leave your Bash cwd anywhere but the repo root. For a command in another folder use absolute paths or a subshell: `( cd .claude/pr-team && … )`, never a bare `cd`.
- Run `cd <repo root>` (absolute path) right before every teammate spawn.

Teammate permission prompts appear in **your** pane, and teammates start in your permission mode. In auto mode the classifier treats an approval relayed by another agent as untrusted, so the human approves directly or adds allow rules. Suggest the user allow `Bash(gh:*)` and `Bash(git:*)` for this project if they haven't.

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
   - **Opt-in `review: on-demand`** (only if the user asks for it, or passes `review: on-demand` in the args or plan.md): no standing reviewer; reviewers are spawned per big PR in Step 4 (cap `max_reviewers`, default 3).
   - 1 `pr-watcher`, always.
7. **Review budget.** Ask the user how many open PRs they can keep up with (default 5). This is the WIP limit on open PRs, not on agents.
8. Write `RUN/plan.md` (task table + shape + team + review budget + review mode) and present it. Task table columns: `id | folder | files | blockedBy | flag | owner | PR | state`; in on-demand mode add `size | reviewer` and `max_reviewers`. Exit plan mode only after the user approves.

## Step 2 · Spawn

1. Load the Task tools with ToolSearch, then create one shared task per planned task (`TaskCreate`), then set `blockedBy` (`TaskUpdate addBlockedBy`). Description first line is `folder: <path>` (builders filter claims on it), then files, acceptance criteria and flag.
2. Spawn teammates with predictable names: `builder-1..N`, `reviewer-1..M`, `pr-watcher`. Use the plugin agent types `bach:pr-builder`, `bach:pr-reviewer`, `bach:pr-watcher`. In on-demand mode skip `reviewer-1..M`. Run the team-config preflight check right after the first spawn.
   - Spawn each with the Agent tool and a `name` (no `run_in_background`, no `isolation`). You are `team-lead`; teammates address you and each other by name.
   - Right before **every** spawn, run `cd <repo root>` (absolute path). Right after it, read `~/.claude/teams/<team>/config.json` and check the new member's `cwd` is the repo root; if not, `shutdown_request` it and respawn after `cd <repo root>` ([Teammate cwd](#teammate-cwd)).
   - If the runtime refuses a plugin agent type as a teammate, spawn a general teammate and paste the body of `AGENTS/<role>.md` at the top of its prompt.
   - Every prompt includes the absolute repo root (teammates check `pwd` against it).
   - Builder prompt: its name, the repo root, "claim tasks from the task list", the folder-ownership rule, and the absolute `STACK` path if the repo has `stack.toml`.
   - Watcher prompt: `POLL=<absolute path>`, `STATE=<absolute RUN/state.json>`, the list of builder names, and the review mode.
3. Require plan approval for builders: approve a builder's plan only if its files stay inside the task's folder. Builders send the plan by SendMessage and wait for your reply. Don't use plan-mode spawns for this: the built-in teammate plan approval is granted automatically, without your review ([agent-teams](https://code.claude.com/docs/en/agent-teams.md#have-teammates-plan-before-implementing)).

## Step 3 · Run (your loop)

You react to teammate messages and task changes. Don't poll.

Teammates send you an `idle_notification` after each turn and stay addressable; idle doesn't mean done. The task list and `RUN/plan.md` are the source of truth.

| Signal | Action |
|---|---|
| Builder plan arrives | Approve if in-scope; otherwise send it back with the rubric line it breaks |
| Builder needs a file outside its folder | Make a new task for that folder (or a contract task), add `blockedBy`, tell the builder to finish without it or wait |
| Task completed with a PR URL | Check the rubric quickly; tell the user "PR #n ready for review: <title>" |
| Builder reports a new PR (on-demand mode) | Step 4: classify, then tell the human or spawn `reviewer-pr<N>` |
| Reviewer verdict `ok` / `blocked` (on-demand mode) | Record in plan.md, shut the reviewer down. `ok`: tell the human "PR #N pre-review ok, ready to merge". `blocked`: the reviewer already talks to the builder; tell the human only if it needs a decision |
| Watcher: human-comment fix round started / ended | Record in plan.md. Don't route fixes yourself |
| Watcher: PR merged | Dependent tasks unblock automatically. If builders are idle and ready tasks exist, keep them claiming |
| Open PRs ≥ review budget (watcher recounts via `gh`) | Tell builders to pause after their current task. Resume when PRs merge |
| Two builders claimed the same task | Tell the loser to stop. Keep the earlier PR or branch, close the duplicate |
| Teammate reports missing Task tools or a wrong cwd | Check its `cwd` in `~/.claude/teams/<team>/config.json`, `shutdown_request` it, `cd <repo root>`, respawn it |
| Builder stuck 3+ attempts on the same error | Stop it, re-scope or reassign the task |
| No tasks left and no open PRs | Ask builders, reviewers, then the watcher to shut down (`shutdown_request`, wait for each `shutdown_response`). Summarise PRs merged |

## Step 4 · Review on demand (opt-in, `review: on-demand` only)

Skip this step in the default mode. A builder reports each PR to you right after `gh pr create`, with size hints. Classify it at once (read `gh pr diff <n> --name-only` and `gh pr view <n> --json additions,deletions` if the hints are thin).

**Big** = any of:
- interactive UI (popup, panel, form, buttons, animation, toggle) or a visible page change
- API contract, schema or migration, or security-sensitive code (auth, secrets, input sanitising, permissions)
- more than ~300 changed lines, excluding generated files (lockfiles, codegen output, snapshots)
- the builder says it is not verified in a browser, or that tests were skipped

Everything else is **small**.

| Size | Action |
|---|---|
| small | Tell the human: "PR #N ready, no pre-review needed (small: <reason>)". |
| big | Spawn ONE teammate `reviewer-pr<N>` (`bach:pr-reviewer`, Agent tool with `name`) for that PR only. Prompt: `review: on-demand`, PR number, owning builder name, the absolute `STACK` path (if `stack.toml`). Tell the human: "PR #N ready, pre-review running (big: <reason>). Wait for label `pre-review:ok` before merging." |

- Several big PRs → several reviewers in parallel, at most `max_reviewers` alive. Over the cap, queue the PR in plan.md and spawn when a reviewer finishes.
- A reviewer that sends its one-line verdict is done: send it a `shutdown_request`. Update `size` and `reviewer` in plan.md.
- If a big PR merges mid-review, the reviewer stops on its own (it re-checks state); you just record it.
- Merge gate for big PRs is the label `pre-review:ok`. Say so to the human for every big PR.

## App stack

For repos whose app needs Postgres (and optionally Redis) and ports. Parallel builders and reviewers each get an isolated **slot** on one shared Postgres + Redis: slot N gets `<NAME>_PORT = base + N`, dev DB `<names.dev>N` cloned from a migrated + seeded template, test DB `<names.test>N` (empty), Redis DB index N. Config: `stack.toml` at the repo root (start from `SKILL/stack/stack.example.toml`). Registry and locks: `~/.stack/<project>.*`.

- **Preflight (f)** runs it straight from the plugin path (`SKILL/stack/stack`, needs `uv` or Python ≥ 3.11 with psycopg). Nothing is copied into the repo; a repo may ship its own `scripts/stack`, which wins.
- **Builders and reviewers** lease once per worktree (`$STACK lease <name>`), then run everything that needs a DB, Redis or a port through `$STACK run [--db dev|test] [--ports] [--heavy] -- <cmd>`. `--heavy` (test suites, builds) queues behind `limits.heavy`. They `$STACK release` when done.
- **Only the human** runs destructive ops: `$STACK infra down|reset` (needs `STACK_ROLE=human`), `docker compose down`, volume or config changes. The plugin's `guard-infra` hook blocks raw docker/compose for every subagent and teammate in repos with `stack.toml`; the lead's own session is not blocked, but you still don't run destructive ops yourself.
- Diagnose with `$STACK ls` / `$STACK doctor`; `$STACK gc` frees slots whose worktree has no process and was idle longer than `limits.grace_s`.

## Rules
- **Never write feature code.** If you catch yourself editing, stop and make a task instead.
- Never merge, approve, or push to `main`. The human merges.
- Two agents never own the same folder at the same time. Give each builder exactly one folder; it is also the builder's claim filter.
- Shared infra (docker, compose, databases) belongs to you and the human. Agents use `$STACK lease/run/release` when the repo has `stack.toml`.
- Keep `RUN/plan.md` current: task → owner → PR → state. It is how a resumed lead recovers (`/resume` doesn't restore in-process teammates), and the only history: completed tasks vanish from TaskList. Update it when a task completes.
- Your Bash cwd stays at the repo root. Use absolute paths or `( cd … && … )` subshells for other folders ([Teammate cwd](#teammate-cwd)).
- Commands you hand the user must be zsh-safe: no bare `!`, no trailing `#` comments.
