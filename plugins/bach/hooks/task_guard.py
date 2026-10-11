#!/usr/bin/env python3
"""Hooks that enforce pr-team's task rules on the Claude Code Task tools.

A run is armed when the lead creates a task while RUN/plan.md has a `Run: <id>`
line that differs from the recorded one (RUN/run: id + the lead's session id);
that wipes the previous run's state. The run is live only while the lead's
team still exists (~/.claude/teams/session-<lead>/config.json is removed when
the session ends), so an abandoned run stops gating by itself. Without a
`Run:` line, or in another session, nothing here acts.

  TaskCreated              arm a run (lead only); record subject (= task id =
                           branch) and the `folder:` line
  PreToolUse  TaskUpdate   with an owner (a claim): one owner per task, one open
                           task per folder, open PRs of the repo below
                           `Review budget: <n>`; the lead may reassign any task
  PreToolUse  TaskUpdate   with status completed: only when the task's PR is
                           MERGED, so blockedBy dependents unblock at merge, not
                           when the PR opens. (Not a TaskCompleted hook: Claude
                           Code also fires that when a teammate ends a turn with
                           a task still in_progress, and blocking it loops.)
  PostToolUse TaskUpdate   record owner, status and the `PR: <url>` line

Exit 2 blocks the action and shows stderr to the agent. Teammate events carry
`agent_type` (and `teammate_name` on TaskCreated); the lead's carry neither.
"""
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager

DEFAULT_BUDGET = 5
PENDING_CLAIM_SECONDS = 60
PR_LINE = re.compile(r"^\s*PR:\s*https://github\.com/([^/\s]+/[^/\s]+)/pull/(\d+)", re.MULTILINE)
RUN_LINE = re.compile(r"^\s*Run:\s*(\S+)", re.MULTILINE)


def run_dir(cwd):
    out = subprocess.run(["git", "-C", cwd, "rev-parse", "--path-format=absolute", "--git-common-dir"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        return None
    path = os.path.join(os.path.dirname(out.stdout.strip()), ".claude", "pr-team")
    return path if os.path.exists(os.path.join(path, "plan.md")) else None


def repo_root(run):
    return os.path.dirname(os.path.dirname(run))


def read_plan(run):
    with open(os.path.join(run, "plan.md")) as f:
        return f.read()


def plan_run_id(run):
    m = RUN_LINE.search(read_plan(run))
    return m.group(1) if m else None


def is_teammate(e):
    return bool(e.get("agent_type") or e.get("teammate_name"))


def team_alive(lead):
    cfg = os.path.join(os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude"),
                       "teams", f"session-{lead[:8]}", "config.json")
    try:
        with open(cfg) as f:
            return json.load(f).get("leadSessionId") == lead
    except (OSError, ValueError):
        return False


def read_state(run):
    try:
        with open(os.path.join(run, "run")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def active(run):
    """The run recorded for this plan, with its lead's team still alive."""
    state = read_state(run)
    return bool(state.get("id")) and state["id"] == plan_run_id(run) and team_alive(state.get("lead") or "")


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
    if not os.path.isdir(d):
        return {}
    return {n[:-5]: load(run, n[:-5]) for n in os.listdir(d) if n.endswith(".json")}


def claim_owner(run, task_id):
    """Owner of a live claim. A claim is written before TaskUpdate runs; if the update never
    happened (failed or denied) it expires instead of holding the task forever."""
    path = os.path.join(run, "claims", task_id)
    try:
        with open(path) as f:
            holder = f.read().strip()
        age = time.time() - os.path.getmtime(path)
    except OSError:
        return None
    if load(run, task_id).get("owner") == holder or age < PENDING_CLAIM_SECONDS:
        return holder
    return None


def write_claim(run, task_id, owner):
    with open(os.path.join(run, "claims", task_id), "w") as f:
        f.write(owner + "\n")


def release(run, task_id):
    try:
        os.remove(os.path.join(run, "claims", task_id))
    except OSError:
        pass


def budget(run):
    m = re.search(r"review budget\D{0,20}(\d+)", read_plan(run), re.IGNORECASE)
    return int(m.group(1)) if m else DEFAULT_BUDGET


def gh_json(*args, cwd=None):
    out = subprocess.run(["gh", *args], capture_output=True, text=True, cwd=cwd)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "gh failed")
    return json.loads(out.stdout)


def block(msg):
    print(msg, file=sys.stderr)
    return 2


def on_created(run, e):
    rid = plan_run_id(run)
    if not rid or not e.get("session_id"):
        return 0
    with locked(run):
        state = read_state(run)
        if state.get("id") != rid:
            if is_teammate(e):
                return 0
            for sub in ("tasks", "claims"):
                shutil.rmtree(os.path.join(run, sub), ignore_errors=True)
                os.makedirs(os.path.join(run, sub))
            with open(os.path.join(run, "run"), "w") as f:
                json.dump({"id": rid, "lead": e["session_id"]}, f)
        elif not active(run):
            return 0
        m = re.search(r"^\s*folder:\s*`?([^`\s]+)", e.get("task_description") or "", re.MULTILINE)
        save(run, e["task_id"], {"subject": e.get("task_subject"), "folder": m.group(1) if m else None,
                                 "status": "pending", "owner": None, "pr": None, "repo": None})
    return 0


def on_claim(run, e, state):
    ti = e["tool_input"]
    task_id, owner = str(ti["taskId"]), ti["owner"]
    with locked(run):
        if not is_teammate(e) and e.get("session_id") == state.get("lead"):
            write_claim(run, task_id, owner)  # the lead may (re)assign any task
            return 0
        holder = claim_owner(run, task_id)
        if holder == owner:
            return 0
        if holder:
            return block(f"Task {task_id} is already claimed by {holder}. Claim another task.")
        tasks = all_tasks(run)
        folder = load(run, task_id).get("folder")
        if folder:
            for other_id, other in tasks.items():
                if other_id != task_id and other.get("folder") == folder and other.get("status") != "completed" \
                        and claim_owner(run, other_id):
                    return block(f"Folder {folder} is held by {claim_owner(run, other_id)} (task {other_id}) "
                                 f"until its PR merges. Claim a task in another folder.")
        limit = budget(run)
        try:
            open_prs = sorted(p["number"] for p in gh_json("pr", "list", "--state", "open", "--limit", "200",
                                                           "--json", "number", cwd=repo_root(run)))
        except RuntimeError as err:
            return block(f"Can't check the review budget: {err}")
        if len(open_prs) >= limit:
            nums = " ".join(f"#{n}" for n in open_prs)
            return block(f"Review budget hit: {len(open_prs)}/{limit} open PRs ({nums}). "
                         f"Wait for a merge; do not message the lead.")
        write_claim(run, task_id, owner)
    return 0


def on_completing(run, e):
    task_id = str(e["tool_input"]["taskId"])
    with locked(run):
        task = load(run, task_id)
    if not task.get("pr"):
        return block(f"Task {task_id} has no `PR: <url>` line in its description. Add it before completing.")
    try:
        state = gh_json("pr", "view", str(task["pr"]), "-R", task["repo"], "--json", "state")["state"]
    except RuntimeError as err:
        return block(f"Can't check PR #{task['pr']}: {err}")
    if state != "MERGED":
        return block(f"PR #{task['pr']} is {state}. Keep task {task_id} in_progress; "
                     f"the lead marks it completed when the PR merges.")
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
        prs = PR_LINE.findall(ti.get("description") or "")
        if prs:
            task["repo"], task["pr"] = prs[-1][0], int(prs[-1][1])
        save(run, task_id, task)
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
    if tool != "TaskUpdate":
        return 0
    state = read_state(run)
    if not active(run):
        return 0
    if event == "PostToolUse":
        return on_updated(run, e)
    if event == "PreToolUse" and ti.get("status") == "completed":
        return on_completing(run, e)
    if event == "PreToolUse" and ti.get("owner"):
        return on_claim(run, e, state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
