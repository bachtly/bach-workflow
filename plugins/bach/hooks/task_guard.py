#!/usr/bin/env python3
"""Hooks that enforce pr-team's task rules on the Claude Code Task tools.

Active only while a pr-team run exists (<main checkout>/.claude/pr-team/plan.md).
State lives next to it: run (lead session id), tasks/<id>.json, claims/<id>.

  TaskCreated              record subject (= task id = branch) and `folder:`;
                           a new lead session starts a new run and wipes old state
  PreToolUse  TaskUpdate   with an owner (a claim): one owner per task, one open
                           task per folder, open PRs below `Review budget: <n>`;
                           the lead's session may reassign any task
  PostToolUse TaskUpdate   record owner, status and the PR URL in the description
  PreToolUse  TaskUpdate   with status completed: only when the task's PR is
                           MERGED, so blockedBy dependents unblock at merge, not
                           when the PR opens. (Not a TaskCompleted hook: Claude
                           Code also fires that when a teammate ends a turn with
                           a task still in_progress, and blocking it loops.)

Exit 2 blocks the action and shows stderr to the agent.
"""
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
from contextlib import contextmanager

DEFAULT_BUDGET = 5
PR_URL = re.compile(r"https://github\.com/[^/\s]+/[^/\s]+/pull/(\d+)")


def run_dir(cwd):
    out = subprocess.run(["git", "-C", cwd, "rev-parse", "--path-format=absolute", "--git-common-dir"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        return None
    path = os.path.join(os.path.dirname(out.stdout.strip()), ".claude", "pr-team")
    return path if os.path.exists(os.path.join(path, "plan.md")) else None


@contextmanager
def locked(run):
    os.makedirs(os.path.join(run, "tasks"), exist_ok=True)
    os.makedirs(os.path.join(run, "claims"), exist_ok=True)
    with open(os.path.join(run, ".lock"), "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def load(run, task_id):
    try:
        with open(os.path.join(run, "tasks", f"{task_id}.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save(run, task_id, task):
    with open(os.path.join(run, "tasks", f"{task_id}.json"), "w") as f:
        json.dump(task, f)


def all_tasks(run):
    d = os.path.join(run, "tasks")
    return {n[:-5]: load(run, n[:-5]) for n in os.listdir(d) if n.endswith(".json")}


def claim_owner(run, task_id):
    try:
        with open(os.path.join(run, "claims", task_id)) as f:
            return f.read().strip()
    except OSError:
        return None


def is_lead(run, e):
    """The lead may (re)assign any task; its session id is recorded at TaskCreated.
    Events from inside a teammate or subagent carry agent_id, even in the lead's process."""
    if e.get("agent_id"):
        return False
    try:
        with open(os.path.join(run, "run")) as f:
            return f.read().strip() == e.get("session_id")
    except OSError:
        return False


def release(run, task_id):
    try:
        os.remove(os.path.join(run, "claims", task_id))
    except OSError:
        pass


def budget(run):
    with open(os.path.join(run, "plan.md")) as f:
        m = re.search(r"review budget\D{0,20}(\d+)", f.read(), re.IGNORECASE)
    return int(m.group(1)) if m else DEFAULT_BUDGET


def gh_json(*args):
    out = subprocess.run(["gh", *args], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "gh failed")
    return json.loads(out.stdout)


def block(msg):
    print(msg, file=sys.stderr)
    return 2


def on_created(run, e):
    run_file = os.path.join(run, "run")
    with locked(run):
        try:
            with open(run_file) as f:
                current = f.read().strip()
        except OSError:
            current = None
        if current != e.get("session_id"):
            for sub in ("tasks", "claims"):
                shutil.rmtree(os.path.join(run, sub), ignore_errors=True)
                os.makedirs(os.path.join(run, sub))
            with open(run_file, "w") as f:
                f.write(e.get("session_id") or "")
        m = re.search(r"^\s*folder:\s*`?([^`\s]+)", e.get("task_description") or "", re.MULTILINE)
        save(run, e["task_id"], {"subject": e.get("task_subject"), "folder": m.group(1) if m else None,
                                 "status": "pending", "owner": None, "pr": None})
    return 0


def on_claim(run, e):
    ti = e["tool_input"]
    task_id, owner = str(ti["taskId"]), ti["owner"]
    with locked(run):
        holder = claim_owner(run, task_id)
        if holder == owner:
            return 0
        if is_lead(run, e):
            with open(os.path.join(run, "claims", task_id), "w") as f:
                f.write(owner + "\n")
            return 0
        if holder:
            return block(f"Task {task_id} is already claimed by {holder}. Claim another task.")
        task = load(run, task_id)
        tasks = all_tasks(run)
        folder = task.get("folder")
        if folder:
            for other_id, other in tasks.items():
                if other_id != task_id and other.get("folder") == folder and other.get("status") != "completed" \
                        and claim_owner(run, other_id):
                    return block(f"Folder {folder} is held by {claim_owner(run, other_id)} (task {other_id}) "
                                 f"until its PR merges. Claim a task in another folder.")
        with_pr = {t["pr"] for t in tasks.values() if t.get("pr") and t.get("status") != "completed"}
        if with_pr:
            try:
                open_prs = {p["number"] for p in gh_json("pr", "list", "--state", "open", "--limit", "200",
                                                         "--json", "number")}
            except RuntimeError as err:
                return block(f"Can't check the review budget: {err}")
            mine = sorted(with_pr & open_prs)
            limit = budget(run)
            if len(mine) >= limit:
                nums = " ".join(f"#{n}" for n in mine)
                return block(f"Review budget hit: {len(mine)}/{limit} open PRs ({nums}). "
                             f"Tell the lead and wait for a merge before claiming.")
        with open(os.path.join(run, "claims", task_id), "w") as f:
            f.write(owner + "\n")
    return 0


def on_updated(run, e):
    ti = e["tool_input"]
    task_id = str(ti["taskId"])
    with locked(run):
        task = load(run, task_id)
        if "owner" in ti:
            task["owner"] = ti["owner"] or None
            if not ti["owner"]:
                release(run, task_id)
        if "status" in ti:
            task["status"] = ti["status"]
            if ti["status"] in ("completed", "deleted"):
                release(run, task_id)
        m = PR_URL.search(ti.get("description") or "")
        if m:
            task["pr"] = int(m.group(1))
        save(run, task_id, task)
    return 0


def on_completing(run, e):
    task_id = str(e["tool_input"]["taskId"])
    with locked(run):
        pr = load(run, task_id).get("pr")
    if not pr:
        return block(f"Task {task_id} has no PR URL in its description. Add it before completing.")
    try:
        state = gh_json("pr", "view", str(pr), "--json", "state")["state"]
    except RuntimeError as err:
        return block(f"Can't check PR #{pr}: {err}")
    if state != "MERGED":
        return block(f"PR #{pr} is {state}. Keep task {task_id} in_progress; "
                     f"the lead marks it completed when the PR merges.")
    return 0


def main():
    try:
        e = json.load(sys.stdin)
    except ValueError:
        return 0
    run = run_dir(e.get("cwd") or os.getcwd())
    if not run:
        return 0
    event, tool, ti = e.get("hook_event_name"), e.get("tool_name"), e.get("tool_input") or {}
    if event == "TaskCreated":
        return on_created(run, e)
    if event == "PreToolUse" and tool == "TaskUpdate" and ti.get("status") == "completed":
        return on_completing(run, e)
    if event == "PreToolUse" and tool == "TaskUpdate" and ti.get("owner"):
        return on_claim(run, e)
    if event == "PostToolUse" and tool == "TaskUpdate":
        return on_updated(run, e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
