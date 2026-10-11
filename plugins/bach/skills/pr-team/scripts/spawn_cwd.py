#!/usr/bin/env python3
"""PreToolUse(Agent), registered by the pr-team skill: block a teammate spawn from outside the project directory.

A teammate starts in the lead's current directory. Started elsewhere (e.g. a
subfolder after a `cd`), it counts as another project: the project's
.claude/settings.json (env, hooks such as an infra guard) doesn't load. The
project directory is where the lead's session started (CLAUDE_PROJECT_DIR, which
differs from the git root in a monorepo); the git root is the fallback. Only
named spawns (teammates) are checked. If neither is known (no CLAUDE_PROJECT_DIR,
not in a git repo) the hook lets the spawn through on purpose: it is a guard
against a common slip, not a gate.
"""
import json
import os
import subprocess
import sys


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    tool_input = event.get("tool_input") or {}
    cwd = event.get("cwd") or ""
    if not tool_input.get("name") or tool_input.get("isolation") or not cwd:
        return 0
    project = os.environ.get("CLAUDE_PROJECT_DIR") or subprocess.run(
        ["git", "-C", cwd, "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip()
    if not project or os.path.realpath(cwd) == os.path.realpath(project):
        return 0
    print(f"Teammates start in your current directory ({cwd}), not the project directory, so they "
          f"would miss the project's settings and hooks. Run `cd {project}` and spawn again.",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
