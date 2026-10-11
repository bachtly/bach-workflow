#!/usr/bin/env python3
"""PreToolUse(Agent): block a pr-team teammate spawn from outside the repo root.

A teammate starts in the lead's current directory. Started in a subfolder, it
counts as another project: the repo's .claude/settings.json (env, hooks such as
an infra guard) doesn't load. Only acts on named spawns (teammates) while a
pr-team run is live (see task_guard.py) and one of its tasks isn't completed;
anything else passes.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import task_guard  # noqa: E402


def open_tasks(run):
    return any(t.get("status") not in ("completed", "deleted") for t in task_guard.all_tasks(run).values())


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
    run = task_guard.run_dir(cwd)
    if not top or not run or not task_guard.active(run) or not open_tasks(run) \
            or os.path.realpath(cwd) == os.path.realpath(top):
        return 0
    print(f"Teammates start in your current directory ({cwd}), not the repo root, so they "
          f"would miss the repo's settings and hooks. Run `cd {top}` and spawn again.",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
