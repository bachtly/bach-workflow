#!/usr/bin/env bash
# One-time (and re-runnable) setup: claude-hud statusline, tmux teammates, bach plugin.
set -euo pipefail

REPO=$(cd "$(dirname "$0")" && pwd)
CLAUDE_DIR=${CLAUDE_CONFIG_DIR:-$HOME/.claude}
SETTINGS="$CLAUDE_DIR/settings.json"

step() { printf '\n[%s] %s\n' "$1" "$2"; }

step 1/5 "deps"
missing=()
for bin in claude jq tmux git node; do
  command -v "$bin" >/dev/null || missing+=("$bin")
done
if [ ${#missing[@]} -gt 0 ]; then
  echo "missing: ${missing[*]}  (brew install ${missing[*]})"
  exit 1
fi
echo "ok"

step 2/5 "claude-hud plugin"
claude plugin marketplace list 2>/dev/null | grep -q claude-hud \
  || claude plugin marketplace add jarrodwatts/claude-hud
claude plugin install claude-hud@claude-hud
mkdir -p "$CLAUDE_DIR/plugins/claude-hud"
if [ ! -f "$CLAUDE_DIR/plugins/claude-hud/config.json" ]; then
  cp "$REPO/setup/claude-hud.json" "$CLAUDE_DIR/plugins/claude-hud/config.json"
  echo "hud config installed"
else
  echo "hud config exists, kept"
fi
chmod +x "$REPO/setup/hud-statusline.sh"
ln -sfn "$REPO/setup/hud-statusline.sh" "$CLAUDE_DIR/hud-statusline.sh"
echo "linked $CLAUDE_DIR/hud-statusline.sh"

step 3/5 "settings.json (statusLine, teammateMode, agent teams env only)"
[ -f "$SETTINGS" ] || echo '{}' > "$SETTINGS"
cp "$SETTINGS" "$SETTINGS.bak.$(date +%Y%m%d-%H%M%S)"
tmp=$(mktemp)
jq --arg cmd "$CLAUDE_DIR/hud-statusline.sh" \
  '.statusLine = {type: "command", command: $cmd, padding: 0, refreshInterval: 5}
   | .teammateMode = "tmux"
   | .env.CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS = "1"' "$SETTINGS" > "$tmp"
mv "$tmp" "$SETTINGS"
echo "updated (backup kept)"

step 4/5 "tmux"
line="source-file $REPO/setup/tmux.conf"
if [ ! -e "$HOME/.tmux.conf" ]; then
  ln -s "$REPO/setup/tmux.conf" "$HOME/.tmux.conf"
  echo "linked ~/.tmux.conf"
elif grep -qxF "$line" "$HOME/.tmux.conf"; then
  echo "already sourced"
else
  printf '\n%s\n' "$line" >> "$HOME/.tmux.conf"
  echo "appended source-file to ~/.tmux.conf"
fi

step 5/5 "bach plugin"
claude plugin marketplace list 2>/dev/null | grep -q bach-workflow \
  || claude plugin marketplace add "$REPO"
claude plugin install bach@bach-workflow

printf '\nDone. Start Claude Code inside tmux:  tmux new -s work\n'
