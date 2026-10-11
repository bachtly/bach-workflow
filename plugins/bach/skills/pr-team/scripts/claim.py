#!/usr/bin/env python3
"""Claim the next pr-team task for a builder.

The task list is the task table in the lead's RUN/plan.md (columns include
`id`, `folder`, `blockedBy`; row order is priority). Claims live in
RUN/claims/<task id> (content: builder name). Task id = branch name, so a
task's PR is found on GitHub by its head branch. A task is claimable when:

  - nobody has claimed it,
  - every task in its blockedBy has a MERGED PR,
  - no other claimed task in the same folder is still without a PR,
  - open PRs of claimed tasks are below the plan's review budget.

  claim.py <builder>                  claim and print the next task
  claim.py <builder> --plan <path>    plan.md elsewhere (default: <main checkout>/.claude/pr-team/plan.md)

Prints `claimed <id>` and the task's row, or `paused: …` (review budget hit),
or `none: …` (nothing ready). A builder that already holds a task without a
PR gets that task again. Exit 0, or 2 on error.
"""
import argparse
import fcntl
import json
import os
import re
import subprocess
import sys

DEFAULT_BUDGET = 5


def run(*args):
    out = subprocess.run(args, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"{' '.join(args[:3])}: {out.stderr.strip()}")
    return out.stdout.strip()


def default_plan():
    common = run("git", "rev-parse", "--path-format=absolute", "--git-common-dir")
    return os.path.join(os.path.dirname(common), ".claude", "pr-team", "plan.md")


def cells(line):
    return [c.strip().strip("`").strip() for c in line.strip().strip("|").split("|")]


def parse_plan(text):
    """Return (tasks, budget). tasks: list of dicts keyed by the table header."""
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
            values = cells(row)
            task = dict(zip(header, values))
            if task.get("id"):
                task["blockedby"] = [b for b in re.split(r"[,\s]+", task.get("blockedby", ""))
                                     if b and b not in {"-", "—", "none"}]
                tasks.append(task)
        break
    m = re.search(r"review budget\D{0,20}(\d+)", text, re.IGNORECASE)
    return tasks, int(m.group(1)) if m else DEFAULT_BUDGET


def pr_states():
    """head branch -> (state, number); MERGED beats OPEN beats CLOSED."""
    rank = {"MERGED": 2, "OPEN": 1, "CLOSED": 0}
    prs = json.loads(run("gh", "pr", "list", "--state", "all", "--limit", "500",
                         "--json", "number,headRefName,state"))
    best = {}
    for pr in prs:
        cur = best.get(pr["headRefName"])
        if cur is None or rank[pr["state"]] > rank[cur[0]]:
            best[pr["headRefName"]] = (pr["state"], pr["number"])
    return best


def pick(builder, tasks, budget, claims, prs):
    """Return ("claimed", task) | ("paused", msg) | ("none", msg). claims: id -> builder."""
    by_id = {t["id"]: t for t in tasks}
    no_pr = [i for i in claims if i not in prs]

    for i in no_pr:
        if claims[i] == builder and i in by_id:
            return "claimed", by_id[i]

    open_prs = sorted(prs[i][1] for i in claims if prs.get(i, ("",))[0] == "OPEN")
    if len(open_prs) >= budget:
        nums = " ".join(f"#{n}" for n in open_prs)
        return "paused", f"{len(open_prs)}/{budget} open PRs ({nums}); wait for a merge"

    held = {by_id[i]["folder"] for i in no_pr if i in by_id}
    waiting = []
    for t in tasks:
        if t["id"] in claims or t["folder"] in held:
            continue
        pending = [b for b in t["blockedby"] if prs.get(b, ("",))[0] != "MERGED"]
        if pending:
            waiting.append(f"{t['id']} waits for {', '.join(pending)}")
            continue
        return "claimed", t
    unclaimed = [t["id"] for t in tasks if t["id"] not in claims]
    if not unclaimed:
        return "none", "all tasks claimed"
    return "none", "; ".join(waiting) or f"folders busy for {', '.join(unclaimed)}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("builder")
    ap.add_argument("--plan")
    a = ap.parse_args()
    try:
        plan = a.plan or default_plan()
        with open(plan) as f:
            tasks, budget = parse_plan(f.read())
        if not tasks:
            raise RuntimeError(f"no task table with id | folder | blockedBy columns in {plan}")
        claims_dir = os.path.join(os.path.dirname(plan), "claims")
        os.makedirs(claims_dir, exist_ok=True)
        prs = pr_states()
        with open(os.path.join(claims_dir, ".lock"), "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            claims = {}
            for name in os.listdir(claims_dir):
                if not name.startswith("."):
                    with open(os.path.join(claims_dir, name)) as f:
                        claims[name] = f.read().strip()
            kind, result = pick(a.builder, tasks, budget, claims, prs)
            if kind == "claimed" and result["id"] not in claims:
                with open(os.path.join(claims_dir, result["id"]), "w") as f:
                    f.write(a.builder + "\n")
    except (OSError, RuntimeError, ValueError) as e:
        print(f"claim.py: {e}", file=sys.stderr)
        return 2
    if kind == "claimed":
        print(f"claimed {result['id']}")
        for k, v in result.items():
            if k != "id":
                print(f"{k}: {', '.join(v) if isinstance(v, list) else v}")
    else:
        print(f"{kind}: {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
