#!/usr/bin/env bash
# Claude Code statusLine entry point: runs the newest installed claude-hud with a
# node binary found at runtime (statusline shells don't load nvm).

cols=${COLUMNS:-}
case "$cols" in ""|*[!0-9]*) cols=$(stty size 2>/dev/null </dev/tty | awk '{print $2}') ;; esac
case "$cols" in ""|*[!0-9]*) cols=120 ;; esac
export COLUMNS=$(( cols > 4 ? cols - 4 : 1 ))

config_dir=${CLAUDE_CONFIG_DIR:-$HOME/.claude}
plugin_dir=$(ls -d "$config_dir"/plugins/cache/*/claude-hud/*/ 2>/dev/null \
  | awk -F/ '{ print $(NF-1) "\t" $0 }' \
  | grep -E '^[0-9]+\.[0-9]+\.[0-9]+[[:space:]]' \
  | sort -t. -k1,1n -k2,2n -k3,3n \
  | tail -1 | cut -f2-)
[ -z "$plugin_dir" ] && { echo "claude-hud not installed"; exit 0; }

node_bin=${CLAUDE_HUD_NODE:-$(command -v node)}
if [ -z "$node_bin" ]; then
  node_bin=$(ls -d "$HOME"/.nvm/versions/node/*/bin/node 2>/dev/null | sort -V | tail -1)
fi
[ -z "$node_bin" ] && [ -x /opt/homebrew/bin/node ] && node_bin=/opt/homebrew/bin/node
[ -z "$node_bin" ] && { echo "node not found (set CLAUDE_HUD_NODE)"; exit 0; }

exec "$node_bin" "${plugin_dir}dist/index.js"
