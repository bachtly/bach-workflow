---
name: pr-team
description: Lead an agent team that ships a feature as many small, self-contained PRs in parallel. Plans the task graph and folder map, fans builders out horizontally or vertically, adds a pre-reviewer and a PR watcher (own tmux pane) that routes review comments back to builders. Opt-in `review: on-demand` replaces the standing reviewer with a short-lived per-PR reviewer for big PRs only. Use when the user wants to build a feature with parallel agents, small PRs, or continuous PR delivery.
disable-model-invocation: true
hooks:
  PreToolUse:
    - matcher: "Agent"
      hooks:
        - type: command
          command: "python3 \"${CLAUDE_PLUGIN_ROOT}/skills/pr-team/scripts/spawn_cwd.py\""
---

# PR Team

You are the **lead**. Your job is PR throughput: as many small, self-contained, mergeable PRs per hour as the human can review. You plan and dispatch. **You never write feature code yourself.**

Feature from the user: **$ARGUMENTS**

If the argument has the form `<path>/roadmap.md#F<n>` (a demo-scope or feature-design hand-off), the feature is the `## F<n>` section of that file. Also read the docs next to it that define the AC ids it lists: `specs/spec.md` from demo-scope, or `02-requirements.md` plus the section's Design refs from feature-design.

## Paths
- `SKILL = ${CLAUDE_SKILL_DIR}`
- `AGENTS = ${CLAUDE_PLUGIN_ROOT}/agents`
- `POLL = SKILL/scripts/pr_poll.py`
- `CLAIM = SKILL/scripts/claim.py`
- `SHOTS = SKILL/references/screenshots.md`
- `RUN = .claude/pr-team/` in the project root. Holds `plan.md`, the watcher's `state.json` and builders' `claims/`.

## Preflight (stop and tell the user if any fails)
| Check | Fix |
|---|---|
| `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` is `1` | Add it to `settings.json` `env` (`bootstrap.sh` does this), restart |
| Running inside tmux (`$TMUX` set) and `teammateMode` is `tmux` | `tmux new -s work`, then `claude` |
| `gh auth status` ok, repo has a GitHub remote | `gh auth login` |
| `git status` clean on `main` | Commit or stash first |

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
   - **Opt-in `review: on-demand`** (only if the user asks for it, or passes `review: on-demand` in the args or plan.md): no standing reviewer; reviewers are spawned per big PR in Step 4 (cap `max_reviewers`, default 3).
   - 1 `pr-watcher`, always.
7. **Review budget.** Ask the user how many open PRs they can keep up with (default 5). This is the WIP limit on open PRs, not on agents.
8. Write `RUN/plan.md` (task table + shape + team + review budget + review mode) and present it. It has a `Plan: <id>` line (letters, digits, `.`, `_`, `-`, e.g. `20261024-1000`; new for a new run, unchanged on re-plan, since claims are kept per plan id), and a task table with `id | folder | files | blockedBy | acceptance criteria | flag` columns (these exact names) in priority order (critical path first); in on-demand mode it also has `size | reviewer` columns, plus a `max_reviewers` line. Task ids are short kebab names (`a-z`, `0-9`, `-`): each is also the task's branch name. Builders claim from it with `CLAIM`. It also has an empty `## Lessons` section (see [Review lessons](#review-lessons)). Exit plan mode only after the user approves.

## Step 2 · Spawn

1. Spawn teammates with predictable names: `builder-1..N`, `reviewer-1..M`, `pr-watcher`. Use the plugin agent types `bach:pr-builder`, `bach:pr-reviewer`, `bach:pr-watcher`. In on-demand mode skip `reviewer-1..M`. Spawn from the project directory (a hook blocks a spawn from anywhere else).
   - If the runtime refuses a plugin agent type as a teammate, spawn a general teammate and paste the body of `AGENTS/<role>.md` at the top of its prompt.
   - Builder prompt: its name, the repo root, `CLAIM=<absolute path>`, `PLAN=<absolute RUN/plan.md>`, `SHOTS=<absolute path>`, the folder-ownership rule, and the review mode.
   - Reviewer prompt: its name, the repo root, `PLAN=<absolute RUN/plan.md>`.
   - Watcher prompt: `POLL=<absolute path>`, `STATE=<absolute RUN/state.json>`, the list of builder names, `CLAIMS=<absolute RUN/claims/<plan id>>`, and the review mode.
2. Require plan approval for builders: approve a builder's plan only if its files stay inside the task's folder.

## Step 3 · Run (your loop)

You react to teammate messages and task changes. Don't poll.

| Signal | Action |
|---|---|
| Builder plan arrives | Approve if in-scope; otherwise send it back with the rubric line it breaks |
| Builder needs a file outside its folder | Add a row for that folder (or a contract task) to `RUN/plan.md` with `blockedBy`, tell the builder to finish without it or wait |
| Builder reports `<task> → PR #n` | Check the rubric quickly (a UI change has `## Screenshots` or `visual: trivial`); add its human steps to the `## Human TODO` section of `RUN/plan.md`; tell the user "PR #n ready for review: <title>", then show the TODO list (below). Then count the open PRs with `gh` (the next row). In on-demand mode, classify it first (Step 4) and say whether pre-review runs |
| Reviewer verdict `ok` (on-demand mode) | Record in plan.md, shut the reviewer down. Tell the human "PR #N pre-review ok, ready to merge" |
| Reviewer says `blocked` (on-demand mode) | Keep the reviewer (no `shutdown_request`). Route the fix to the owning builder and give it the reviewer's name; wait for the re-check. Tell the human only if it needs a decision |
| `lesson: …` from a reviewer, builder or the watcher | Filter and merge it into `## Lessons` in `RUN/plan.md` (see Review lessons) |
| Watcher: human-comment fix round started / ended | Record in plan.md. Don't route fixes yourself |
| Watcher: PR merged | Dependent tasks unblock (`CLAIM` checks). If builders are idle and ready tasks exist, tell them to claim again |
| Watcher: PR closed, not merged | Ask the user: redo (the builder opens a new PR) or drop (remove its row and re-plan its dependents; a claim on a removed row is ignored) |
| Open PRs ≥ review budget | Tell builders to pause after their current task. Resume when PRs merge |
| Builder stuck 3+ attempts on the same error | Stop it, re-scope or reassign the task (release its claim: `rm RUN/claims/<plan>/<task>`) |
| No tasks left (every builder reported `none: all tasks claimed`) and no open PRs | Ask builders, reviewers, then the watcher to shut down. Summarise PRs merged and show the TODO list with every step still open |

## Stay responsive: orchestrate, don't execute

The user chats with you while the team runs. A lead busy with a long job blocks the user and every teammate message. Before acting on any request (from the user or a teammate), estimate how long it takes:

- **Seconds** (answer from what you know, read one file, run one quick `gh`/`git` command, update `RUN/plan.md`, send a message): do it yourself.
- **Longer** (research, reading many files, investigation, debugging, writing or editing code or docs, multi-step commands, anything that waits on a build or tests): don't do it. Hand it off and go back to listening:
  - Fits the plan → add a task row to `RUN/plan.md` so a builder claims it.
  - Fix on an open PR → send it to that PR's builder.
  - Anything else (a question to investigate, a one-off chore) → spawn a teammate for it (`helper-1..`, a general teammate with a self-contained prompt), and tell the user who took it.

Reply to the user within seconds: what you decided and who owns it. Relay the result when the teammate reports. If unsure whether a job is quick, it isn't: delegate.

## TODO list

Next steps for the user are a TODO list, not only PRs to review. Whenever you report to the user (a new PR, a merge or close, a pause, the final summary, or when asked), show:

1. **Your TODO**: open human steps from `RUN/plan.md` `## Human TODO` plus "review PR #n" for each PR waiting on the user, as checkboxes grouped by when: **Before merge**, **Review**, **After merge**, **To try it**. Each item names the PR it belongs to, where to do it (link to the provider console page, or the shell), and the exact zsh-safe command in a code block. Example:
   - **Before merge**
     - [ ] #12 · Create a GitHub OAuth app at https://github.com/settings/developers, callback `http://localhost:3000/auth/callback`; put its id and secret in `.env` as `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`
   - **Review**
     - [ ] Review #12 Add login form
   - **After merge**
     - [ ] #13 · Run the migration: `pnpm db:migrate`
2. **The PR table** below.

Tick a step in `RUN/plan.md` when the user says it's done or the watcher sees its PR merged (for review items). Drop steps of a PR that's closed and dropped.

## PR table

Show every PR of the run as one table, built from `RUN/plan.md` and `gh pr list --state all`:

| PR | Title | Task | Owner | Status |
|---|---|---|---|---|
| #12 | Add login form | T3 | builder-1 | 🟡 Ready for review |
| #13 | Session API | T4 | builder-2 | 🔴 Changes requested |

Status is one of: 🔵 Pre-review (reviewer still checking), 🟡 Ready for review, 🔴 Changes requested, ✅ Merged, ⚫ Closed. Sort open PRs first, oldest first. Link each PR number to its URL.

## Review lessons

Goal: a mistake caught once in review is not repeated by the next builder. Teammates send you `lesson: [<folder>|all] <rule> — PR #n (<who>)`. You are the only writer of `## Lessons` in `RUN/plan.md`; builders read it before every plan, reviewers check against it.

- **Be picky.** Add a lesson only if it is a rule for future PRs (not a fix for this one), it is checkable on a diff, it came from a human comment or a reviewer blocker, and the repo's `CLAUDE.md`, a linter or a test doesn't already enforce it. Drop everything else, typos and one-off nits included.
- **Merge every time.** On each add, re-read the section: fold the new lesson into a similar line, rewrite overlapping lines as one more general rule, and remove lines a `CLAUDE.md` now covers. Keep at most 10 lines; over that, merge harder or drop the least useful. Use `[all]` unless the rule is truly about one folder.
- One imperative line each, ending with its sources: `- [all] A test for a fix must fail when the fix is reverted — PR #8, #18`.
- When every other task is claimed and `## Lessons` has lines not yet in the repo's `CLAUDE.md` files, add a last task row `lessons-docs`: files = root `CLAUDE.md` (for `[all]`) and `<folder>/CLAUDE.md` (for folder lessons). Acceptance: each lesson merged into the existing rules there (no near-duplicates, the same pickiness bar), one line each. The human reviews it like any PR.

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
| big | Spawn ONE teammate `reviewer-pr<N>` (`bach:pr-reviewer`, Agent tool with `name`) for that PR only. Prompt: `review: on-demand`, PR number, owning builder name, repo root, `PLAN=<absolute RUN/plan.md>`. Tell the human: "PR #N ready, pre-review running (big: <reason>). Wait for label `pre-review:ok` before merging." |

- Several big PRs → several reviewers in parallel, at most `max_reviewers` alive. Over the cap, queue the PR in plan.md and spawn when a reviewer finishes.
- A reviewer that sends an `ok` verdict is done: send it a `shutdown_request`. Update `size` and `reviewer` in plan.md.
- **`blocked`: keep the reviewer.** Don't shut it down and don't spawn a new reviewer for the same PR. Tell the owning builder: "reviewer `reviewer-pr<N>` is waiting on PR #N; fix, push, then send it `fix pushed <sha>`". The builder and reviewer talk directly; the reviewer re-checks only `git diff <old>..<new>` and sends a new verdict.
  - Owning builder gone (shut down or busy elsewhere): spawn or assign a builder for the fix, keep the same reviewer, and give the new builder the reviewer's name. Tell the reviewer the new builder's name.
  - Shut a reviewer down only on: `ok`, the PR merged or closed, or the builder or human saying no fix is coming.
- If a big PR merges mid-review, the reviewer stops on its own (it re-checks state); you just record it.
- Merge gate for big PRs is the label `pre-review:ok`. Say so to the human for every big PR.

## Rules
- **Never write feature code.** If you catch yourself editing, stop and make a task instead.
- **Never block on heavy work.** Anything longer than seconds goes to a teammate (see Stay responsive).
- Never merge, approve, or push to `main`. The human merges.
- Two agents never own the same folder at the same time.
- Keep `RUN/plan.md` current: task → owner → PR → state, and the `## Human TODO` checklist. It is how a resumed lead recovers (`/resume` doesn't restore in-process teammates).
- Commands you hand the user must be zsh-safe: no bare `!`, no trailing `#` comments.
