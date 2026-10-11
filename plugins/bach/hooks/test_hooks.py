"""Tests for the pr-team hooks. Run: python3 -m unittest plugins/bach/hooks/test_hooks.py

Event shapes are the ones Claude Code 2.1.296 sends (captured in an interactive
session): teammate events carry `agent_type` (and `teammate_name` on TaskCreated),
the lead's carry neither. `gh` is a stub on PATH: GH_PRS is {"<number>": "<state>"}.
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
GUARD = os.path.join(HERE, "task_guard.py")
SPAWN = os.path.join(HERE, "spawn_cwd.py")
LEAD = "aaaaaaaa-lead-session"

GH_STUB = """#!/usr/bin/env python3
import json, os, sys
prs = json.loads(os.environ.get("GH_PRS", "{}"))
a = sys.argv[1:]
if a[:2] == ["pr", "list"]:
    print(json.dumps([{"number": int(n)} for n, s in prs.items() if s == "OPEN"]))
elif a[:2] == ["pr", "view"]:
    assert "-R" in a, "gh pr view must pass -R"
    print(json.dumps({"state": prs.get(a[2], "OPEN")}))
"""


def read_json(path):
    with open(path) as f:
        return json.load(f)


class Hooks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.realpath(os.path.join(self.tmp.name, "repo"))
        os.makedirs(os.path.join(self.repo, ".claude", "pr-team"))
        os.makedirs(os.path.join(self.repo, "sub"))
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        self.run_dir = os.path.join(self.repo, ".claude", "pr-team")
        self.plan("run-1", 9)
        bindir = os.path.join(self.tmp.name, "bin")
        os.makedirs(bindir)
        with open(os.path.join(bindir, "gh"), "w") as f:
            f.write(GH_STUB)
        os.chmod(os.path.join(bindir, "gh"), 0o755)
        self.teams = os.path.join(self.tmp.name, "claude", "teams")
        self.env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}",
                    "CLAUDE_CONFIG_DIR": os.path.join(self.tmp.name, "claude")}
        self.team(LEAD)

    def tearDown(self):
        self.tmp.cleanup()

    def plan(self, run_id, budget):
        lines = ["# Plan", "", f"Run: {run_id}" if run_id else "", f"Review budget: {budget}"]
        with open(os.path.join(self.run_dir, "plan.md"), "w") as f:
            f.write("\n".join(lines) + "\n")

    def team(self, lead, alive=True):
        d = os.path.join(self.teams, f"session-{lead[:8]}")
        if alive:
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "config.json"), "w") as f:
                json.dump({"leadSessionId": lead, "members": []}, f)
        else:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    def hook(self, script, event, cwd=None, prs=None):
        event = {"session_id": LEAD, "cwd": cwd or self.repo, **event}
        env = {**self.env, "GH_PRS": json.dumps(prs or {})}
        out = subprocess.run([sys.executable, script], input=json.dumps(event),
                             capture_output=True, text=True, env=env)
        return out.returncode, out.stderr

    def create(self, task_id, subject, folder, **extra):
        return self.hook(GUARD, {"hook_event_name": "TaskCreated", "task_id": task_id, "task_subject": subject,
                                 "task_description": f"folder: {folder}\nfiles: x", **extra})

    def mate(self, name):
        return {"session_id": f"{name}-session", "agent_type": "general-purpose"}

    def claim(self, task_id, owner, prs=None):
        return self.hook(GUARD, {**self.mate(owner), "hook_event_name": "PreToolUse", "tool_name": "TaskUpdate",
                                 "tool_input": {"taskId": task_id, "status": "in_progress", "owner": owner}}, prs=prs)

    def update(self, task_id, **ti):
        return self.hook(GUARD, {"hook_event_name": "PostToolUse", "tool_name": "TaskUpdate",
                                 "tool_input": {"taskId": task_id, **ti}})

    def claimed(self, task_id, owner):
        self.assertEqual(self.claim(task_id, owner)[0], 0)
        self.update(task_id, owner=owner, status="in_progress")

    def test_one_owner_per_task(self):
        self.create("1", "be-schema", "api/")
        self.claimed("1", "builder-1")
        code, err = self.claim("1", "builder-2")
        self.assertEqual(code, 2)
        self.assertIn("already claimed by builder-1", err)

    def test_parallel_claims_have_one_winner(self):
        self.create("1", "be-schema", "api/")
        codes = []
        threads = [threading.Thread(target=lambda b=b: codes.append(self.claim("1", b)[0]))
                   for b in ("builder-1", "builder-2", "builder-3", "builder-4")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(codes), [0, 2, 2, 2])

    def test_failed_update_does_not_hold_the_task(self):
        self.create("1", "be-schema", "api/")
        self.assertEqual(self.claim("1", "builder-1")[0], 0)  # Pre ran, the update itself never happened
        claim = os.path.join(self.run_dir, "claims", "1")
        old = time.time() - 120
        os.utime(claim, (old, old))
        self.assertEqual(self.claim("1", "builder-2")[0], 0)

    def test_folder_held_until_completed(self):
        self.create("1", "be-schema", "api/")
        self.create("2", "be-search", "api/")
        self.create("3", "docs-readme", "docs/")
        self.claimed("1", "builder-1")
        self.update("1", description="folder: api/\nPR: https://github.com/o/r/pull/42")
        code, err = self.claim("2", "builder-2")
        self.assertEqual(code, 2)
        self.assertIn("Folder api/ is held by builder-1", err)
        self.assertEqual(self.claim("3", "builder-2")[0], 0)
        self.update("1", status="completed")
        self.assertEqual(self.claim("2", "builder-2")[0], 0)

    def test_review_budget_counts_all_open_prs_of_the_repo(self):
        self.plan("run-1", 2)
        self.create("1", "a", "a/")
        code, err = self.claim("1", "builder-1", prs={"7": "OPEN", "8": "OPEN", "9": "MERGED"})
        self.assertEqual(code, 2)
        self.assertIn("2/2 open PRs (#7 #8)", err)
        self.assertIn("do not message the lead", err)
        self.assertEqual(self.claim("1", "builder-1", prs={"7": "OPEN", "8": "MERGED"})[0], 0)

    def test_completed_only_when_merged_and_uses_the_pr_line(self):
        self.create("1", "be-schema", "api/")
        ev = {"hook_event_name": "PreToolUse", "tool_name": "TaskUpdate",
              "tool_input": {"taskId": "1", "status": "completed"}}
        self.assertEqual(self.hook(GUARD, ev)[0], 2)  # no PR recorded yet
        self.update("1", description="folder: api/\nsee https://github.com/o/r/pull/5\nPR: https://github.com/o/r/pull/42")
        code, err = self.hook(GUARD, ev, prs={"42": "OPEN", "5": "MERGED"})
        self.assertEqual(code, 2)
        self.assertIn("PR #42 is OPEN", err)
        self.assertEqual(self.hook(GUARD, ev, prs={"42": "MERGED"})[0], 0)

    def test_task_completed_event_is_not_blocked(self):
        """Claude Code fires TaskCompleted when a teammate ends a turn with the task still in_progress."""
        self.create("1", "be-schema", "api/")
        ev = {"hook_event_name": "TaskCompleted", "task_id": "1", "task_subject": "be-schema"}
        self.assertEqual(self.hook(GUARD, ev)[0], 0)

    def test_lead_reassigns_a_claimed_task(self):
        self.create("1", "be-schema", "api/")
        self.claimed("1", "builder-1")
        code, _ = self.hook(GUARD, {"hook_event_name": "PreToolUse", "tool_name": "TaskUpdate",
                                    "tool_input": {"taskId": "1", "owner": "builder-2"}})
        self.assertEqual(code, 0)
        self.assertEqual(self.claim("1", "builder-1")[0], 2)

    def test_teammate_cannot_arm_or_wipe_a_run(self):
        self.create("1", "be-schema", "api/")
        self.claimed("1", "builder-1")
        self.plan("run-2", 9)
        self.create("2", "x", "x/", **self.mate("builder-2"), teammate_name="builder-2")
        self.assertEqual(self.claim("1", "builder-2")[0], 0)  # state untouched, but run-2 isn't armed: inert

    def test_new_run_id_wipes_the_old_run(self):
        self.create("1", "be-schema", "api/")
        self.claimed("1", "builder-1")
        self.plan("run-2", 9)
        self.team("bbbbbbbb-lead-session")
        self.hook(GUARD, {"session_id": "bbbbbbbb-lead-session", "hook_event_name": "TaskCreated", "task_id": "1",
                          "task_subject": "fe-page", "task_description": "folder: web/"})
        self.assertFalse(os.path.exists(os.path.join(self.run_dir, "claims", "1")))
        self.assertEqual(read_json(os.path.join(self.run_dir, "run"))["lead"], "bbbbbbbb-lead-session")

    def test_resumed_lead_does_not_wipe_the_run(self):
        self.create("1", "be-schema", "api/")
        self.claimed("1", "builder-1")
        self.team("cccccccc-lead-session")  # /resume: new session id, same plan.md Run id
        self.hook(GUARD, {"session_id": "cccccccc-lead-session", "hook_event_name": "TaskCreated", "task_id": "2",
                          "task_subject": "x", "task_description": "folder: x/"})
        self.assertEqual(read_json(os.path.join(self.run_dir, "run"))["lead"], LEAD)
        self.assertTrue(os.path.exists(os.path.join(self.run_dir, "claims", "1")))

    def test_inert_when_the_lead_team_is_gone(self):
        self.create("1", "be-schema", "api/")
        self.claimed("1", "builder-1")
        self.team(LEAD, alive=False)
        self.assertEqual(self.claim("1", "builder-2")[0], 0)

    def test_inert_without_run_line_or_plan(self):
        self.plan(None, 9)
        self.create("1", "be-schema", "api/")
        self.assertFalse(os.path.exists(os.path.join(self.run_dir, "run")))
        self.assertEqual(self.claim("1", "builder-1")[0], 0)
        os.remove(os.path.join(self.run_dir, "plan.md"))
        self.assertEqual(self.claim("1", "builder-2")[0], 0)

    def test_hooks_json_points_at_existing_scripts(self):
        hooks = read_json(os.path.join(HERE, "hooks.json"))["hooks"]
        self.assertEqual(sorted(hooks), ["PostToolUse", "PreToolUse", "TaskCreated"])
        scripts = {c["command"].split("/hooks/")[1].rstrip('"') for groups in hooks.values()
                   for g in groups for c in g["hooks"]}
        self.assertEqual(scripts, {"spawn_cwd.py", "task_guard.py"})
        for s in scripts:
            self.assertTrue(os.path.exists(os.path.join(HERE, s)))

    def test_spawn_cwd(self):
        spawn = {"hook_event_name": "PreToolUse", "tool_name": "Agent",
                 "tool_input": {"name": "builder-1", "prompt": "x"}}
        sub = os.path.join(self.repo, "sub")
        self.assertEqual(self.hook(SPAWN, spawn, cwd=sub)[0], 0)  # no run armed yet
        self.create("1", "be-schema", "api/")
        code, err = self.hook(SPAWN, spawn, cwd=sub)
        self.assertEqual(code, 2)
        self.assertIn(f"cd {self.repo}`", err)
        self.assertEqual(self.hook(SPAWN, spawn)[0], 0)
        self.assertEqual(self.hook(SPAWN, {**spawn, "tool_input": {"prompt": "x"}}, cwd=sub)[0], 0)
        self.team(LEAD, alive=False)
        self.assertEqual(self.hook(SPAWN, spawn, cwd=sub)[0], 0)  # lead's team gone: abandoned run
        self.team(LEAD)
        self.update("1", status="completed")
        self.assertEqual(self.hook(SPAWN, spawn, cwd=sub)[0], 0)  # run finished


if __name__ == "__main__":
    unittest.main()
