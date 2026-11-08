#!/usr/bin/env python3
"""TeammateIdle hook (registered by the bach plugin): keep a pr-team builder working instead of idling.

A builder that goes idle wakes the lead (an idle notice), and the lead then has to
tell it to claim again: two lead turns per task. When a task is claimable, this hook
blocks the idle (exit 2) and tells the builder to claim it, so neither happens.

It does nothing (exit 0) unless all of these hold, so it is safe in any session:
  - a pr-team run exists (<git root>/.claude/pr-team/plan.md) and the teammate is named `builder-<n>`,
  - `claim.py --peek` says a new task is claimable for it (not `held`: a builder
    holding a task without a PR is waiting on purpose, e.g. for a scope answer),
  - the builder has not just retired (a `.retired/<name>` mark with no claim after it),
  - it was not already pushed to the same task in the last 10 minutes (no loops).
Any error also exits 0: the hook is a shortcut, never a gate.

Evidence: inside a run, every call appends one JSON line to RUN/.idle-hook.log
(time, the input's keys, teammate_name, agent_id/agent_type, decision, reason), so a
real run shows whether the hook fires for in-process teammates and what it receives.
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import claim  # noqa: E402

REPUSH_SECONDS = 600
SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "claim.py")


def find_plan(cwd):
    common = subprocess.run(["git", "-C", cwd, "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            capture_output=True, text=True, timeout=20).stdout.strip()
    plan = os.path.join(os.path.dirname(common), ".claude", "pr-team", "plan.md") if common else ""
    return plan if plan and os.path.exists(plan) else None


def just_retired(claims_dir, name):
    """True if this builder has a retire mark and no claim after it (the retiring instance)."""
    mark = claim.retired_at(claims_dir, name)
    if not mark:
        return False
    for n in os.listdir(claims_dir):
        if n.startswith("."):
            continue
        try:
            with open(os.path.join(claims_dir, n)) as f:
                c = json.load(f)
            if c.get("builder") == name and float(c.get("at", 0)) > mark:
                return False
        except (OSError, ValueError):
            continue
    return True


def decide(name, plan, cwd):
    """(exit code, reason, stderr message)."""
    if not name.startswith("builder-"):
        return 0, "not a builder" if name else "no teammate_name in input", ""
    with open(plan) as f:
        plan_id, _, _ = claim.parse_plan(f.read())
    claims_dir = os.path.join(os.path.dirname(plan), "claims", plan_id or "")
    if os.path.isdir(claims_dir) and just_retired(claims_dir, name):
        return 0, "retired; the replacement claims on its own", ""
    out = subprocess.run([sys.executable, SCRIPT, name, "--plan", plan, "--peek"],
                         capture_output=True, text=True, cwd=cwd, timeout=90).stdout.splitlines()
    if not out or not out[0].startswith("claimed "):
        return 0, f"peek: {out[0] if out else 'no output'}", ""
    task = out[0].split(" ", 1)[1]
    pushes_path = os.path.join(os.path.dirname(plan), ".idle-push.json")
    try:
        with open(pushes_path) as f:
            pushes = json.load(f)
    except (OSError, ValueError):
        pushes = {}
    last = pushes.get(name) or {}
    if last.get("task") == task and time.time() - float(last.get("at", 0)) < REPUSH_SECONDS:
        return 0, f"already pushed to {task} recently", ""
    pushes[name] = {"task": task, "at": time.time()}
    with open(pushes_path, "w") as f:
        json.dump(pushes, f)
    return 2, f"pushed to {task}", (f"Task `{task}` is claimable now. Don't go idle: run "
                                    f"`python3 {SCRIPT} {name} --plan {plan}` and build it (the normal per-task steps).")


def log(plan, event, code, reason):
    try:
        entry = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "keys": sorted(event),
                 "teammate_name": event.get("teammate_name"), "agent_id": event.get("agent_id"),
                 "agent_type": event.get("agent_type"), "exit": code, "reason": reason}
        with open(os.path.join(os.path.dirname(plan), ".idle-hook.log"), "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(event, dict):
        return 0
    cwd = event.get("cwd") or os.getcwd()
    try:
        plan = find_plan(cwd)
    except (OSError, subprocess.SubprocessError):
        return 0
    if not plan:
        return 0
    try:
        code, reason, message = decide(event.get("teammate_name") or "", plan, cwd)
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        code, reason, message = 0, f"error: {e}", ""
    log(plan, event, code, reason)
    if message:
        print(message, file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
