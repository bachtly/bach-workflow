#!/usr/bin/env bash
# Feeds sample PreToolUse inputs into guard-infra.sh and checks the exit codes. No network, no docker.
set -uo pipefail
hook="$(cd "$(dirname "$0")" && pwd)/guard-infra.sh"
fail=0
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
git init -q "$tmp/stack-repo" && touch "$tmp/stack-repo/stack.toml" && mkdir "$tmp/stack-repo/sub"
git init -q "$tmp/plain-repo"
cwd="$tmp/stack-repo"

check() {  # check <expected-exit> <agent_id|-> <command>
  local want=$1 agent=$2 cmd=$3 json got
  if [[ "$agent" == - ]]; then
    json=$(jq -n --arg c "$cmd" --arg d "$cwd" \
      '{hook_event_name:"PreToolUse",tool_name:"Bash",cwd:$d,tool_input:{command:$c}}')
  else
    json=$(jq -n --arg c "$cmd" --arg a "$agent" --arg d "$cwd" \
      '{hook_event_name:"PreToolUse",tool_name:"Bash",cwd:$d,agent_id:$a,tool_input:{command:$c}}')
  fi
  bash "$hook" <<<"$json" 2>/dev/null; got=$?
  if [[ "$got" == "$want" ]]; then echo "ok   $want  [${agent}] ${cwd##*/}: $cmd"
  else echo "FAIL want $want got $got  [${agent}] ${cwd##*/}: $cmd"; fail=1; fi
}

# agents in a stack repo: blocked
check 2 builder-1 'docker ps'
check 2 builder-1 'docker compose up -d db'
check 2 builder-1 'docker-compose down -v'
check 2 builder-1 'cd /x && docker compose down -v'
check 2 builder-1 'FOO=1 docker run --rm alpine'
check 2 builder-1 'sudo docker system prune'
check 2 builder-1 'echo $(docker ps -q)'
check 2 builder-1 'podman ps'
check 2 builder-1 'make dev'
check 2 builder-1 'make up'
check 2 builder-1 'make -C /x down'
check 2 builder-1 'podman compose down'
check 2 builder-1 'scripts/stack infra down'
check 2 builder-1 'STACK_ROLE=human ~/.claude/plugins/x/stack/stack infra reset'
check 2 reviewer-1 $'ls\ndocker ps'
# agents in a stack repo: allowed
check 0 builder-1 'stack run --db test --heavy -- make check-backend'
check 0 builder-1 'stack infra ensure'
check 0 builder-1 'make check-backend'
check 0 builder-1 'make reseed'
check 0 builder-1 'grep -n docker docs/playbooks/05-database.md'
check 0 builder-1 'git commit -m "docs: mention docker in the playbook"'
# known false positive, accepted: "compose down" matches anywhere, even in a message
check 2 builder-1 'git commit -m "docs: compose down is human-only"'
# subfolder of a stack repo: still guarded
cwd="$tmp/stack-repo/sub"
check 2 builder-1 'docker ps'
# main session: everything passes
cwd="$tmp/stack-repo"
check 0 - 'docker compose down -v'
check 0 - 'make dev'
# repos without stack.toml, or outside git: the hook stays out of the way
cwd="$tmp/plain-repo"
check 0 builder-1 'docker compose down -v'
cwd="$tmp"
check 0 builder-1 'docker ps'

exit $fail
