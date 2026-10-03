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

## Troubleshooting

| Symptom | Fix |
|---|---|
| Statusline shows `node not found` | Set `CLAUDE_HUD_NODE` to an absolute node path, e.g. in `settings.json` `env` |
| Statusline shows `claude-hud not installed` | `claude plugin install claude-hud@claude-hud` |
| Teammates don't open in panes | Make sure Claude was started inside a tmux session |
| Restore previous settings | Copy the newest `~/.claude/settings.json.bak.*` back over `settings.json` |

## Not in this repo

Secrets, tokens, `~/.claude.json`, history, sessions, and machine-specific permissions stay local.
