#!/usr/bin/env python3
"""Claim the next pr-team task for a builder (the shared task list without the Claude Task tools).

The task list is the table in the lead's RUN/plan.md (columns `id`, `folder`,
`blockedBy`; row order is priority) and a `Run: <id>` line. Claims live in
RUN/claims/<run id>/<task id> (builder + claim time), so another run never sees
them. Task id = branch name; a task's PR is the one with that head branch created
after the claim. A task is claimable when:

  - nobody has claimed it,
  - every task in its blockedBy has a MERGED PR,
  - no other claimed task in its folder is still without a MERGED PR.

  claim.py <builder>                  claim and print the next task
  claim.py <builder> --plan <path>    plan.md elsewhere (default: <main checkout>/.claude/pr-team/plan.md)

Prints `claimed <id>` and the task's row, or `none: <why>`. A builder that holds a
task without a PR gets that task again. Exit 0, or 2 on error. The review budget
is the lead's to check, not this script's.
"""
import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime


def run(*args, cwd=None):
    out = subprocess.run(args, capture_output=True, text=True, cwd=cwd, timeout=60)
    if out.returncode != 0:
        raise RuntimeError(f"{' '.join(args[:3])}: {out.stderr.strip()}")
    return out.stdout.strip()


def default_plan():
    common = run("git", "rev-parse", "--path-format=absolute", "--git-common-dir")
    return os.path.join(os.path.dirname(common), ".claude", "pr-team", "plan.md")


def cells(line):
    return [c.strip().strip("`").strip() for c in line.strip().strip("|").split("|")]


def parse_plan(text):
    """Return (run id or None, tasks). tasks: dicts keyed by the lower-cased table header."""
    m = re.search(r"^\s*Run:\s*(\S+)", text, re.MULTILINE)
    lines = text.splitlines()
    tasks = []
    for i, line in enumerate(lines):
        if not line.lstrip().startswith("|"):
            continue
        header = [h.lower() for h in cells(line)]
        if not {"id", "folder", "blockedby"} <= set(header):
            continue
        for row in lines[i + 2:]:
            if not row.lstrip().startswith("|"):
                break
            task = dict(zip(header, cells(row)))
            if task.get("id"):
                task["blockedby"] = [b for b in re.split(r"[,\s]+", task.get("blockedby", ""))
                                     if b and b not in {"-", "—", "none"}]
                tasks.append(task)
        break
    return (m.group(1) if m else None), tasks


def open_prs(cwd):
    """All PRs of the repo: [(head branch, state, number, created epoch)]."""
    prs = json.loads(run("gh", "pr", "list", "--state", "all", "--limit", "500",
                         "--json", "number,headRefName,state,createdAt", cwd=cwd))
    return [(p["headRefName"], p["state"], p["number"],
             datetime.fromisoformat(p["createdAt"].replace("Z", "+00:00")).timestamp()) for p in prs]


def task_pr(prs, task_id, claimed_at):
    """The task's PR: head branch = task id, created after the claim. MERGED beats OPEN beats CLOSED."""
    rank = {"MERGED": 2, "OPEN": 1, "CLOSED": 0}
    best = None
    for head, state, number, created in prs:
        if head == task_id and created >= claimed_at and (best is None or rank[state] > rank[best[0]]):
            best = (state, number)
    return best


def pick(builder, tasks, claims, prs):
    """Return ("claimed", task) or ("none", why). claims: id -> {"builder", "at"}."""
    by_id = {t["id"]: t for t in tasks}
    pr_of = {i: task_pr(prs, i, c["at"]) for i, c in claims.items()}

    for i, c in claims.items():
        if c["builder"] == builder and i in by_id and pr_of[i] is None:
            return "claimed", by_id[i]

    held = {by_id[i]["folder"] for i in claims if i in by_id and (pr_of[i] or ("", 0))[0] != "MERGED"}
    waiting = []
    for t in tasks:
        if t["id"] in claims:
            continue
        if t["folder"] in held:
            waiting.append(f"{t['id']}: folder {t['folder']} is held until its task's PR merges")
            continue
        pending = [b for b in t["blockedby"] if (pr_of.get(b) or ("", 0))[0] != "MERGED"]
        if pending:
            waiting.append(f"{t['id']} waits for {', '.join(pending)}")
            continue
        return "claimed", t
    unclaimed = [t["id"] for t in tasks if t["id"] not in claims]
    if not unclaimed:
        return "none", "all tasks claimed"
    return "none", "; ".join(waiting)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("builder")
    ap.add_argument("--plan")
    a = ap.parse_args()
    try:
        plan = a.plan or default_plan()
        with open(plan) as f:
            run_id, tasks = parse_plan(f.read())
        if not run_id:
            raise RuntimeError(f"no `Run: <id>` line in {plan}; ask the lead to add one")
        if not tasks:
            raise RuntimeError(f"no task table with id | folder | blockedBy columns in {plan}")
        claims_dir = os.path.join(os.path.dirname(plan), "claims", run_id)
        os.makedirs(claims_dir, exist_ok=True)
        prs = open_prs(os.path.dirname(os.path.dirname(os.path.dirname(plan))))
        with open(os.path.join(claims_dir, ".lock"), "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            claims = {}
            for name in os.listdir(claims_dir):
                if not name.startswith("."):
                    with open(os.path.join(claims_dir, name)) as f:
                        claims[name] = json.load(f)
            kind, result = pick(a.builder, tasks, claims, prs)
            if kind == "claimed" and result["id"] not in claims:
                with open(os.path.join(claims_dir, result["id"]), "w") as f:
                    json.dump({"builder": a.builder, "at": time.time()}, f)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as e:
        print(f"claim.py: {e}", file=sys.stderr)
        return 2
    if kind == "claimed":
        print(f"claimed {result['id']}")
        for k, v in result.items():
            if k != "id":
                print(f"{k}: {', '.join(v) if isinstance(v, list) else v}")
    else:
        print(f"none: {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
