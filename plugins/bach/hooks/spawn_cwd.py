#!/usr/bin/env python3
"""PreToolUse(Agent): block a pr-team teammate spawn from outside the repo root.

A teammate starts in the lead's current directory. Started in a subfolder, it
counts as another project: the repo's .claude/settings.json (env, hooks such as
an infra guard) doesn't load. Only acts on named spawns (teammates) while a
pr-team run is active (a task in <repo root>/.claude/pr-team/tasks/ is not
completed); anything else passes.
"""
import json
import os
import subprocess
import sys


def active_run(top):
    tasks = os.path.join(top, ".claude", "pr-team", "tasks")
    if not os.path.isdir(tasks):
        return False
    for name in os.listdir(tasks):
        try:
            with open(os.path.join(tasks, name)) as f:
                if json.load(f).get("status") not in ("completed", "deleted"):
                    return True
        except (OSError, ValueError):
            continue
    return False


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    tool_input = event.get("tool_input") or {}
    cwd = event.get("cwd") or ""
    if not tool_input.get("name") or tool_input.get("isolation") or not cwd:
        return 0
    top = subprocess.run(["git", "-C", cwd, "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True).stdout.strip()
    if not top or not active_run(top) or os.path.realpath(cwd) == os.path.realpath(top):
        return 0
    print(f"Teammates start in your current directory ({cwd}), not the repo root, so they "
          f"would miss the repo's settings and hooks. Run `cd {top}` and spawn again.",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
