#!/usr/bin/env python3
"""Claim the next pr-team task for a builder (the shared task list without the Claude Task tools).

The task list is the table in the lead's RUN/plan.md (columns `id`, `folder`,
`blockedBy` by those exact names; row order is priority) and a `Plan: <id>` line.
Claims live in RUN/claims/<plan id>/<task id>, one small JSON file per claim
({"builder", "at"}): a plan never sees another plan's claims, one broken file never
affects the others, and the lead releases a claim by deleting its file. Task ids are
short kebab names (they are also the branch name), so they are safe file names.
The plan id names the claims directory, so it stays the same when the lead re-plans.
Task id = branch name; a task's PR is the one with that head branch created
after the claim. A task is claimable when:

  - nobody has claimed it,
  - every task in its blockedBy has a MERGED PR,
  - no other claimed task in its folder is still without a MERGED PR.

  claim.py <builder>                  claim and print the next task
  claim.py <builder> --plan <path>    plan.md elsewhere (default: <git root>/.claude/pr-team/plan.md,
                                      which assumes the project root is the git root)

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
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

CLOCK_SKEW_SECONDS = 60  # the builder's clock vs GitHub's createdAt


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
    """Return (plan id or None, tasks, headers of the first table). tasks: dicts keyed by the lower-cased header."""
    m = re.search(r"^\s*Plan:\s*(\S+)", text, re.MULTILINE)
    lines = text.splitlines()
    tasks, first = [], []
    for i, line in enumerate(lines):
        if not line.lstrip().startswith("|"):
            continue
        header = [h.lower() for h in cells(line)]
        first = first or header
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
    return (m.group(1) if m else None), tasks, first


def prs_for(task_ids):
    """PRs by head branch, asked for the given task ids only: [(head branch, state, number, created epoch)].
    No repo-wide list that a limit could cut off."""
    def one(task_id):
        rows = json.loads(run("gh", "pr", "list", "--state", "all", "--head", task_id, "--limit", "100",
                              "--json", "number,headRefName,state,createdAt"))
        return [(p["headRefName"], p["state"], p["number"],
                 datetime.fromisoformat(p["createdAt"].replace("Z", "+00:00")).timestamp()) for p in rows]

    with ThreadPoolExecutor(max_workers=8) as pool:
        return [pr for rows in pool.map(one, task_ids) for pr in rows]


def task_pr(prs, task_id, claimed_at):
    """The task's PR: head branch = task id, created after the claim. MERGED beats OPEN beats CLOSED."""
    rank = {"MERGED": 2, "OPEN": 1, "CLOSED": 0}
    best = None
    for head, state, number, created in prs:
        if head == task_id and created >= claimed_at - CLOCK_SKEW_SECONDS and (best is None or rank[state] > rank[best[0]]):
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
        unknown = [b for b in t["blockedby"] if b not in by_id]
        if unknown:
            waiting.append(f"{t['id']}: blockedBy unknown task {', '.join(unknown)} (not a row in the plan)")
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
            plan_id, tasks, headers = parse_plan(f.read())
        if not plan_id:
            raise RuntimeError(f"no `Plan: <id>` line in {plan}; ask the lead to add one")
        if not tasks:
            raise RuntimeError(f"no task table with id | folder | blockedBy columns in {plan} "
                               f"(first table has: {', '.join(headers) or 'no table'})")
        bad = [t["id"] for t in tasks if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", t["id"])]
        if bad:
            raise RuntimeError(f"task ids must be short kebab names, a-z 0-9 and - (they are also the branch name): {', '.join(bad)}")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", plan_id):
            raise RuntimeError(f"plan id must use letters, digits, ., _ and - (it names the claims directory): {plan_id}")
        claims_dir = os.path.join(os.path.dirname(plan), "claims", plan_id)
        os.makedirs(claims_dir, exist_ok=True)
        # Only claimed tasks have a PR to look up. Read before the lock: a claim made meanwhile has no PR
        # yet, and a stale snapshot only makes a claim more conservative.
        prs = prs_for([n for n in os.listdir(claims_dir) if not n.startswith(".")])
        with open(os.path.join(claims_dir, ".lock"), "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            claims = {}
            for name in sorted(os.listdir(claims_dir)):
                if name.startswith("."):
                    continue
                try:
                    with open(os.path.join(claims_dir, name)) as f:
                        c = json.load(f)
                    claims[name] = {"builder": c["builder"], "at": float(c["at"])}
                except (OSError, ValueError, KeyError, TypeError):
                    print(f"claim.py: ignoring unreadable claim {name} (delete its file to release it)", file=sys.stderr)
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
