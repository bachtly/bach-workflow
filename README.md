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
| Ship a feature as parallel small PRs | `/bach:pr-team <feature>`: the lead plans a task graph, spawns `pr-builder`s (one folder each) and a `pr-watcher` that routes your PR comments back. Big PRs get a short-lived `reviewer-pr<N>`; wait for label `pre-review:ok` before merging those. You review and merge |
| Update | `git -C ~/bach-workflow pull`, `claude plugin marketplace update bach-workflow`, `claude plugin update bach@bach-workflow`, then restart `claude` |
| Add a skill | Create `plugins/bach/skills/<name>/SKILL.md`, bump `version` in `plugin.json`, commit, push |
| Change HUD display | Run `/claude-hud:configure`, or edit `~/.claude/plugins/claude-hud/config.json` |

## pr-team requirements

- **Interactive terminal session.** Run `claude` in a terminal (tmux optional; the VS Code integrated terminal works). Agent SDK, `claude -p` and IDE-extension chat sessions don't spawn teammates: a named `Agent` call there becomes a plain subagent ([agent teams](https://code.claude.com/docs/en/agent-teams.md)).
- **Agent teams on:** `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` in `settings.json` `env` (bootstrap sets it).
- **Task tools:** off by default on models newer than Opus 4.7 / Sonnet 4.6. Opt in with `CLAUDE_CODE_ENABLE_TODO_TOOLS=1 claude` or `claude --allowedTools TaskCreate` ([Task tool availability](https://code.claude.com/docs/en/tools-reference.md#task-tool-availability)).
- **`teammateMode`:** `in-process`, `auto` or `tmux` all work.
- **After editing agent or skill files, update the plugin.** Installed copies are cached per version: bump `version` in `plugins/bach/.claude-plugin/plugin.json`, push, then run the Update steps above. Running teammates keep the old prompt until respawned.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Statusline shows `node not found` | Set `CLAUDE_HUD_NODE` to an absolute node path, e.g. in `settings.json` `env` |
| Statusline shows `claude-hud not installed` | `claude plugin install claude-hud@claude-hud` |
| Teammates don't open in panes | Panes need tmux (or iTerm2) and `teammateMode` `tmux`/`auto`; in-process mode shows them in the agent panel instead |
| pr-team spawns plain subagents, no `~/.claude/teams/*/config.json` | You're in an SDK, `-p` or IDE-extension session; start `claude` in a terminal |
| Restore previous settings | Copy the newest `~/.claude/settings.json.bak.*` back over `settings.json` |

## Not in this repo

Secrets, tokens, `~/.claude.json`, history, sessions, and machine-specific permissions stay local.
