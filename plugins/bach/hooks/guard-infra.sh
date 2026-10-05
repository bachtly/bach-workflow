#!/usr/bin/env bash
# PreToolUse hook (Bash), shipped by the bach plugin: subagents and teammates (hook input has
# agent_id) may not touch shared infra directly; they go through the app stack, which only does
# safe operations. The main session (no agent_id) is never restricted.
# Active only in repos that opted into the app stack (a stack.toml at the git root of the cwd).
# Exit 2 = block; stderr goes to the agent. A guardrail against mistakes, not a security boundary.
set -euo pipefail

input="$(cat)"
agent_id="$(jq -r '.agent_id // empty' <<<"$input")"
[[ -z "$agent_id" ]] && exit 0
cmd="$(jq -r '.tool_input.command // empty' <<<"$input")"
[[ -z "$cmd" ]] && exit 0
cwd="$(jq -r '.cwd // empty' <<<"$input")"
root="$(git -C "${cwd:-.}" rev-parse --show-toplevel 2>/dev/null || true)"
[[ -n "$root" && -f "$root/stack.toml" ]] || exit 0

stack="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/skills/pr-team/stack/stack"
[[ -x "$root/scripts/stack" ]] && stack="scripts/stack"

# Start of a command: line start, or after ; & | ( ` $( , optionally behind sudo/env/VAR=x.
start='(^|[;&|(`]|\$\()[[:space:]]*(sudo[[:space:]]+)?(env[[:space:]]+)?([A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+)*'
patterns=(
  "${start}(docker|docker-compose|podman|podman-compose)([[:space:]]|$)"
  "${start}make([[:space:]]+[^;&|[:space:]]+)*[[:space:]]+(dev|up|down)([[:space:]]|$)"
  "compose[[:space:]]+down"
  "stack[[:space:]]+infra[[:space:]]+(down|reset)"
)

while IFS= read -r line; do
  for re in "${patterns[@]}"; do
    if [[ "$line" =~ $re ]]; then
      cat >&2 <<MSG
Blocked by guard-infra: agents must not run docker/compose or the human-only make targets
(matched: "${BASH_REMATCH[0]}").
Use the app stack instead (STACK=$stack):
  \$STACK lease <owner>                     # once per worktree
  \$STACK run --db test --heavy -- <cmd>    # tests; --db dev for the dev DB, --ports for servers
  \$STACK infra ensure                      # if Postgres/Redis are down
Anything destructive (down, reset, recreate): ask the human.
MSG
      exit 2
    fi
  done
done <<<"$cmd"
exit 0
