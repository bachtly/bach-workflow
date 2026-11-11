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
  - no other claimed task in its folder is still without a MERGED PR,
  - the review budget is not full: fewer than `Review budget: <n>` (a plan.md line,
    optional) claimed tasks have an OPEN PR. This is the WIP limit on open PRs, so the
    lead never has to count PRs and pause builders itself.

  claim.py <builder>                  claim and print the next task
  claim.py <builder> --plan <path>    plan.md elsewhere (default: <git root>/.claude/pr-team/plan.md,
                                      which assumes the project root is the git root)
  claim.py <builder> --peek           print what a claim would give, write nothing

Retirement: after `Retire builders after: <n>` tasks (a plan.md line, default 3), a
claim prints `retire: <why>` instead of a new task and marks the builder retired
(claims/<plan id>/.retired/<builder>). The lead then replaces it with a fresh
teammate of the same name, whose claims count from that mark. This keeps builder
contexts small; plan.md, Lessons and Decisions carry what the old one learned.

Prints `claimed <id>` and the task's row, `held <id>` (--peek: the builder already
holds a task without a PR), or `none: <why>`. A builder that holds a task without a
PR gets that task again. On `none`, the builder is marked waiting
(claims/<plan id>/.waiting/<builder>) so the watcher can wake it when a PR merges; a
claim clears the mark. Exit 0, or 2 on error.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime

if os.name == "nt":
    import msvcrt
else:
    import fcntl

CLOCK_SKEW_SECONDS = 60  # the builder's clock vs GitHub's createdAt


@contextmanager
def file_lock(path):
    """Hold an exclusive lock on `path` (created if missing) until the block exits; blocks until free."""
    with open(path, "w") as f:
        if os.name == "nt":
            # msvcrt has no blocking mode: LK_LOCK retries for ~10 s, then raises. Keep retrying.
            # It locks from the current position, so always lock byte 0.
            while True:
                f.seek(0)
                try:
                    msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
                    break
                except OSError:
                    continue
        else:
            fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(f, fcntl.LOCK_UN)


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


def review_budget(text):
    """The `Review budget: <n>` line, or None (no limit)."""
    m = re.search(r"^\s*Review budget:\s*(\d+)", text, re.MULTILINE | re.IGNORECASE)
    return int(m.group(1)) if m else None


def retire_after(text):
    """The `Retire builders after: <n>` line (default 3; 0 = never)."""
    m = re.search(r"^\s*Retire builders after:\s*(\d+)", text, re.MULTILINE | re.IGNORECASE)
    return int(m.group(1)) if m else 3


def retired_at(claims_dir, builder):
    try:
        with open(os.path.join(claims_dir, ".retired", builder)) as f:
            return float(f.read().strip() or 0)
    except (OSError, ValueError):
        return 0.0


def claims_since(claims, builder, since):
    return sum(1 for c in claims.values() if c["builder"] == builder and c["at"] > since)


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


def pick(builder, tasks, claims, prs, budget=None):
    """Return ("claimed", task), ("held", task) or ("none", why). claims: id -> {"builder", "at"}.
    "held": the builder already holds this task without a PR (a claim hands it out again)."""
    by_id = {t["id"]: t for t in tasks}
    pr_of = {i: task_pr(prs, i, c["at"]) for i, c in claims.items()}

    for i, c in claims.items():
        if c["builder"] == builder and i in by_id and pr_of[i] is None:
            return "held", by_id[i]

    open_prs = sorted(pr_of[i][1] for i in claims if i in by_id and (pr_of[i] or ("", 0))[0] == "OPEN")
    if budget is not None and len(open_prs) >= budget and any(t["id"] not in claims for t in tasks):
        return "none", (f"review budget full: {len(open_prs)} open PRs (budget {budget}): "
                        f"{', '.join(f'#{n}' for n in open_prs)}; wait for a merge")

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


def mark_waiting(claims_dir, builder, waiting):
    """Mark (or unmark) a builder as waiting for a claimable task. The watcher wakes marked builders on a merge."""
    path = os.path.join(claims_dir, ".waiting", builder)
    if waiting:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(str(time.time()))
    elif os.path.exists(path):
        os.remove(path)


def waiting_builders(claims_dir):
    """Builders whose last claim got `none`."""
    d = os.path.join(claims_dir, ".waiting")
    return sorted(os.listdir(d)) if os.path.isdir(d) else []


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("builder")
    ap.add_argument("--plan")
    ap.add_argument("--peek", action="store_true", help="print what a claim would give, write nothing")
    a = ap.parse_args()
    try:
        plan = a.plan or default_plan()
        with open(plan) as f:
            text = f.read()
        plan_id, tasks, headers = parse_plan(text)
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
        with file_lock(os.path.join(claims_dir, ".lock")):
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
            kind, result = pick(a.builder, tasks, claims, prs, review_budget(text))
            limit, since = retire_after(text), retired_at(claims_dir, a.builder)
            if kind == "claimed" and limit and claims_since(claims, a.builder, since) >= limit:
                kind, result = "retire", f"{limit} tasks done; end your turn with `retire` so the lead starts a fresh {a.builder}"
                if not a.peek:
                    os.makedirs(os.path.join(claims_dir, ".retired"), exist_ok=True)
                    with open(os.path.join(claims_dir, ".retired", a.builder), "w") as f:
                        f.write(str(time.time()))
            if not a.peek:
                if kind == "claimed":
                    with open(os.path.join(claims_dir, result["id"]), "w") as f:
                        json.dump({"builder": a.builder, "at": time.time()}, f)
                mark_waiting(claims_dir, a.builder, kind == "none")
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as e:
        print(f"claim.py: {e}", file=sys.stderr)
        return 2
    if kind == "held" and not a.peek:
        kind = "claimed"
    if kind in ("claimed", "held"):
        print(f"{kind} {result['id']}")
        for k, v in result.items():
            if k != "id":
                print(f"{k}: {', '.join(v) if isinstance(v, list) else v}")
    else:
        print(f"{'retire' if kind == 'retire' else 'none'}: {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
