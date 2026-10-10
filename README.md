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
  agents/*.md
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
| Ship a feature as parallel small PRs | `/bach:pr-team <feature>`: the lead plans a task graph, spawns `pr-builder`s (one folder each), a `pr-reviewer` and a `pr-watcher` pane that routes review comments back. You review and merge |
| Update | `git -C ~/bach-workflow pull` then `claude plugin marketplace update bach-workflow` |
| Add a skill | Create `plugins/bach/skills/<name>/SKILL.md`, bump `version` in `plugin.json`, commit, push |
| Change HUD display | Run `/claude-hud:configure`, or edit `~/.claude/plugins/claude-hud/config.json` |

## pr-team and your app's dev env

Parallel builders each work in their own git worktree, but they share your machine: one Postgres, one Redis, the same ports. pr-team doesn't ship infra tooling; your repo tells agents how to get an isolated env, in its CLAUDE.md:

```markdown
## Parallel agents
1. Once per worktree: `<your command to get an env>` (e.g. a slot lease that sets ports and DB names).
2. Tests and servers: `<your command>` (e.g. `make check-backend`, `<runner> -- npm run dev`).
3. Never run `docker`, `docker compose`, `make up|down`. If Postgres/Redis are down: `<safe ensure command>`.
4. Done: `<release command>`.
Lead, before spawning: `<infra ensure / template refresh>`.
```

The lead runs the "Lead, before spawning" steps in preflight; builders and reviewers follow the rest. Without the section, agents never touch infra and avoid each other's ports, and the lead warns you if the app needs a DB. Example implementation: the slot allocator in [lean-web-stack](https://github.com/bachtly/lean-web-stack) (`scripts/stack`).

## Troubleshooting

| Symptom | Fix |
|---|---|
| Statusline shows `node not found` | Set `CLAUDE_HUD_NODE` to an absolute node path, e.g. in `settings.json` `env` |
| Statusline shows `claude-hud not installed` | `claude plugin install claude-hud@claude-hud` |
| Teammates don't open in panes | Make sure Claude was started inside a tmux session |
| Restore previous settings | Copy the newest `~/.claude/settings.json.bak.*` back over `settings.json` |

## Not in this repo

Secrets, tokens, `~/.claude.json`, history, sessions, and machine-specific permissions stay local.
