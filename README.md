# bach-workflow

Personal Claude Code setup: a plugin marketplace for my personal development workflow, aiming for eficiency and reduce dead time.

## Quick start

Requires `claude`, `jq`, `tmux`, `git`, `node` (`brew install jq tmux git node`).

```
git clone git@github.com:bachtly/bach-workflow.git ~/bach-workflow
~/bach-workflow/bootstrap.sh
tmux new -s work
claude
```

## What bootstrap does

| Step | Change |
|---|---|
| 1. deps | Checks required binaries, exits if any missing |
| 2. claude-hud | Installs `claude-hud@claude-hud`, copies `setup/claude-hud.json` to `~/.claude/plugins/claude-hud/config.json` (keeps existing), links `~/.claude/hud-statusline.sh` |
| 3. settings | Backs up `~/.claude/settings.json`, sets only `statusLine`, `teammateMode: "tmux"` and `env.CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS: "1"` |
| 4. tmux | Links `~/.tmux.conf`, or appends `source-file` to an existing one |
| 5. bach plugin | Adds this repo as marketplace `bach-workflow`, installs `bach@bach-workflow` |

Safe to re-run. Other settings keys, secrets and permissions are never touched.

## Layout

```
.claude-plugin/marketplace.json   marketplace "bach-workflow"
plugins/bach/                     plugin "bach"
  .claude-plugin/plugin.json
  skills/<name>/SKILL.md
  skills/pr-team/stack/           app stack CLI (stack, stack.py, stack.example.toml, tests)
  agents/*.md
  hooks/hooks.json                guard-infra PreToolUse hook (+ guard-infra.sh, its test)
setup/
  hud-statusline.sh               statusLine entry point (finds node + newest claude-hud)
  claude-hud.json                 HUD display config
  tmux.conf
bootstrap.sh
```

## Daily use

| Task | How |
|---|---|
| Run a skill | `/bach:<skill>` e.g. `/bach:web-research <topic>`, or let Claude pick it by description |
| Agent teammates | Start Claude inside tmux; each teammate opens in its own pane |
| Ship a feature as parallel small PRs | `/bach:pr-team <feature>`: the lead plans a task graph, spawns `pr-builder`s (one folder each), a `pr-reviewer` and a `pr-watcher` pane that routes review comments back. You review and merge. Opt-in `review: on-demand` (ask for it, or put it in the args): no standing reviewer; big PRs get a short-lived `reviewer-pr<N>`, wait for label `pre-review:ok` before merging those |
| Update | `git -C ~/bach-workflow pull`, `claude plugin marketplace update bach-workflow`, `claude plugin update bach@bach-workflow`, then restart `claude` |
| Add a skill | Create `plugins/bach/skills/<name>/SKILL.md`, bump `version` in `plugin.json`, commit, push |
| Change HUD display | Run `/claude-hud:configure`, or edit `~/.claude/plugins/claude-hud/config.json` |

## pr-team requirements

- **Interactive `claude` CLI session inside tmux** (unchanged; see Quick start). Agent SDK, `claude -p` and IDE-extension chat sessions are not supported: they don't spawn teammates, a named `Agent` call there becomes a plain subagent ([agent teams](https://code.claude.com/docs/en/agent-teams.md)).
- **Agent teams on:** `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` in `settings.json` `env` (bootstrap sets it).
- **Task tools:** off by default on models newer than Opus 4.7 / Sonnet 4.6. Opt in with `CLAUDE_CODE_ENABLE_TODO_TOOLS=1 claude` or `claude --allowedTools TaskCreate` ([Task tool availability](https://code.claude.com/docs/en/tools-reference.md#task-tool-availability)).
- **`teammateMode`:** `tmux` (bootstrap sets it).
- **After editing agent or skill files, update the plugin.** Installed copies are cached per version: bump `version` in `plugins/bach/.claude-plugin/plugin.json`, push, then run the Update steps above. Running teammates keep the old prompt until respawned.
- **Known limitation: task claiming is not atomic.** Two builders claiming the same task at once both succeed (last write wins). pr-team mitigates it: each builder only claims tasks in its own folder, then re-reads the task after ~2 s and drops it if another builder owns it.

## App stack

A slot allocator so parallel agents (pr-team builders, reviewers) never collide on ports or databases and never start or recreate infra themselves. One shared Postgres (+ optional Redis); slot N gets `<NAME>_PORT = base + N`, a dev DB cloned from a migrated + seeded template (~0.25 s), an empty test DB and Redis DB index N. No daemon: a JSON registry under `~/.stack/` behind `flock`, a file-lock semaphore for heavy jobs, and a `guard-infra` plugin hook that blocks raw docker/compose for subagents and teammates in repos that have a `stack.toml`. Needs `uv` (or Python ≥ 3.11 with `psycopg`), `git`, `lsof`, `jq`.

Quick start, in your app repo:

```
S=~/bach-workflow/plugins/bach/skills/pr-team/stack
cp $S/stack.example.toml stack.toml
echo .env.slot >> .gitignore
$S/stack infra ensure
$S/stack template refresh
$S/stack lease me
$S/stack run --db dev -- printenv DATABASE_URL API_PORT
$S/stack run --db test --heavy -- pytest -q
$S/stack ls
$S/stack release
```

Edit `stack.toml` first: pool URLs, DB name prefixes, `template.build`/`template.cwd`, ports, limits, compose file and services. Then commit it. `/bach:pr-team` picks it up and hands the path to every teammate. Destructive ops (`stack infra down|reset`) need `STACK_ROLE=human`.

Limits:
- **Postgres + Redis only.** Other services (queues, search, object storage) are not sliced.
- **One shared Postgres.** Slots are logical (separate DBs on the same server). `--heavy` and `limits.heavy` cap concurrent suites; they don't isolate CPU or I/O.
- **Slots can be reclaimed.** When all slots are taken, a new lease takes the oldest slot whose worktree has no running process and was idle longer than `limits.grace_s`, and drops its DBs.
- **The hook is a guardrail, not security.** It pattern-matches Bash commands for agents (input has `agent_id`); it misses indirection (scripts, aliases) and has a known false positive on the words `compose down`. The lead's own session (no `agent_id`) is never blocked.
- **Hook scope.** It is a plugin hook, so it is on wherever the plugin is enabled, but it does nothing in repos without `stack.toml` at the git root.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Statusline shows `node not found` | Set `CLAUDE_HUD_NODE` to an absolute node path, e.g. in `settings.json` `env` |
| Statusline shows `claude-hud not installed` | `claude plugin install claude-hud@claude-hud` |
| Teammates don't open in panes | Make sure Claude was started inside a tmux session |
| pr-team spawns plain subagents, no `~/.claude/teams/*/config.json` | You're in an SDK, `-p` or IDE-extension session; start `claude` in a terminal |
| Restore previous settings | Copy the newest `~/.claude/settings.json.bak.*` back over `settings.json` |

## Not in this repo

Secrets, tokens, `~/.claude.json`, history, sessions, and machine-specific permissions stay local.
