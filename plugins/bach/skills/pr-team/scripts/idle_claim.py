#!/usr/bin/env python3
"""TeammateIdle hook (registered by the bach plugin): keep a pr-team builder working instead of idling.

A builder that goes idle wakes the lead (an idle notice), and the lead then has to
tell it to claim again: two lead turns per task. When a task is claimable, this hook
blocks the idle (exit 2) and tells the builder to claim it, so neither happens.

It does nothing (exit 0) unless all of these hold, so it is safe in any session:
  - the teammate is named `builder-<n>` and a pr-team run exists (<git root>/.claude/pr-team/plan.md),
  - `claim.py --peek` says a new task is claimable for it (not `held`: a builder
    holding a task without a PR is waiting on purpose, e.g. for a scope answer),
  - the builder has not just retired (a `.retired/<name>` mark with no claim after it),
  - it was not already pushed to the same task in the last 10 minutes (no loops).
Any error also exits 0: the hook is a shortcut, never a gate.
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import claim  # noqa: E402

REPUSH_SECONDS = 600


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    name = event.get("teammate_name") or ""
    if not name.startswith("builder-"):
        return 0
    cwd = event.get("cwd") or os.getcwd()
    try:
        common = subprocess.run(["git", "-C", cwd, "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                capture_output=True, text=True, timeout=20).stdout.strip()
        plan = os.path.join(os.path.dirname(common), ".claude", "pr-team", "plan.md")
        if not common or not os.path.exists(plan):
            return 0
        with open(plan) as f:
            plan_id, _, _ = claim.parse_plan(f.read())
        claims_dir = os.path.join(os.path.dirname(plan), "claims", plan_id or "")
        mark = claim.retired_at(claims_dir, name)
        if mark:
            mine = [n for n in os.listdir(claims_dir) if not n.startswith(".")]
            newer = False
            for n in mine:
                try:
                    with open(os.path.join(claims_dir, n)) as f:
                        c = json.load(f)
                    newer = newer or (c.get("builder") == name and float(c.get("at", 0)) > mark)
                except (OSError, ValueError):
                    continue
            if not newer:
                return 0  # this instance retired; its replacement claims on its own
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "claim.py")
        out = subprocess.run([sys.executable, script, name, "--plan", plan, "--peek"],
                             capture_output=True, text=True, cwd=cwd, timeout=90).stdout.splitlines()
        if not out or not out[0].startswith("claimed "):
            return 0
        task = out[0].split(" ", 1)[1]
        pushes_path = os.path.join(os.path.dirname(plan), ".idle-push.json")
        try:
            with open(pushes_path) as f:
                pushes = json.load(f)
        except (OSError, ValueError):
            pushes = {}
        last = pushes.get(name) or {}
        if last.get("task") == task and time.time() - float(last.get("at", 0)) < REPUSH_SECONDS:
            return 0
        pushes[name] = {"task": task, "at": time.time()}
        with open(pushes_path, "w") as f:
            json.dump(pushes, f)
    except (OSError, subprocess.SubprocessError, ValueError):
        return 0
    print(f"Task `{task}` is claimable now. Don't go idle: run `python3 {script} {name} --plan {plan}` "
          f"and build it (the normal per-task steps).", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
