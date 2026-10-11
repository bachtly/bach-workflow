"""Tests for the pr-team hooks. Run: python3 -m unittest plugins/bach/hooks/test_hooks.py

Event shapes are the ones Claude Code 2.1.295 sends (captured in an interactive
session with CLAUDE_CODE_ENABLE_TODO_TOOLS=1). `gh` is a stub on PATH that
answers from GH_PRS (JSON: {"<number>": "<state>"}).
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
GUARD = os.path.join(HERE, "task_guard.py")
SPAWN = os.path.join(HERE, "spawn_cwd.py")
LEAD = "lead-session"

GH_STUB = """#!/usr/bin/env python3
import json, os, sys
prs = json.loads(os.environ.get("GH_PRS", "{}"))
a = sys.argv[1:]
if a[:2] == ["pr", "list"]:
    print(json.dumps([{"number": int(n)} for n, s in prs.items() if s == "OPEN"]))
elif a[:2] == ["pr", "view"]:
    print(json.dumps({"state": prs.get(a[2], "OPEN")}))
"""


class Hooks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "repo")
        os.makedirs(os.path.join(self.repo, ".claude", "pr-team"))
        os.makedirs(os.path.join(self.repo, "sub"))
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        self.run_dir = os.path.join(self.repo, ".claude", "pr-team")
        with open(os.path.join(self.run_dir, "plan.md"), "w") as f:
            f.write("# Plan\n\nReview budget: 2\n")
        bindir = os.path.join(self.tmp.name, "bin")
        os.makedirs(bindir)
        with open(os.path.join(bindir, "gh"), "w") as f:
            f.write(GH_STUB)
        os.chmod(os.path.join(bindir, "gh"), 0o755)
        self.env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "GH_PRS": "{}"}

    def tearDown(self):
        self.tmp.cleanup()

    def hook(self, script, event, cwd=None, prs=None):
        event = {"session_id": LEAD, "cwd": cwd or self.repo, **event}
        env = {**self.env, "GH_PRS": json.dumps(prs or {})}
        out = subprocess.run([sys.executable, script], input=json.dumps(event),
                             capture_output=True, text=True, env=env)
        return out.returncode, out.stderr

    def create(self, task_id, subject, folder, session=LEAD):
        return self.hook(GUARD, {"session_id": session, "hook_event_name": "TaskCreated", "task_id": task_id,
                                 "task_subject": subject, "task_description": f"folder: {folder}\nfiles: x"})

    def claim(self, task_id, owner, prs=None, **extra):
        return self.hook(GUARD, {"session_id": f"{owner}-session", "hook_event_name": "PreToolUse",
                                 "tool_name": "TaskUpdate", "agent_id": owner,
                                 "tool_input": {"taskId": task_id, "status": "in_progress", "owner": owner},
                                 **extra}, prs=prs)

    def update(self, task_id, **ti):
        return self.hook(GUARD, {"hook_event_name": "PostToolUse", "tool_name": "TaskUpdate",
                                 "tool_input": {"taskId": task_id, **ti},
                                 "tool_response": {"success": True, "taskId": task_id}})

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

    def test_review_budget(self):
        for i, (s, f) in enumerate([("a", "a/"), ("b", "b/"), ("c", "c/")], start=1):
            self.create(str(i), s, f)
        self.claimed("1", "builder-1")
        self.update("1", description="PR: https://github.com/o/r/pull/41")
        self.claimed("2", "builder-2")
        self.update("2", description="PR: https://github.com/o/r/pull/42")
        code, err = self.claim("3", "builder-1", prs={"41": "OPEN", "42": "OPEN"})
        self.assertEqual(code, 2)
        self.assertIn("2/2 open PRs (#41 #42)", err)
        self.assertEqual(self.claim("3", "builder-1", prs={"41": "MERGED", "42": "OPEN"})[0], 0)

    def test_completed_only_when_merged(self):
        self.create("1", "be-schema", "api/")
        ev = {"hook_event_name": "PreToolUse", "tool_name": "TaskUpdate",
              "tool_input": {"taskId": "1", "status": "completed"}}
        self.assertEqual(self.hook(GUARD, ev)[0], 2)  # no PR recorded yet
        self.update("1", description="folder: api/\nPR: https://github.com/o/r/pull/42")
        code, err = self.hook(GUARD, ev, prs={"42": "OPEN"})
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

    def test_new_lead_session_starts_a_new_run(self):
        self.create("1", "be-schema", "api/")
        self.claimed("1", "builder-1")
        self.create("1", "fe-page", "web/", session="next-lead-session")
        self.assertEqual(self.claim("1", "builder-2")[0], 0)

    def test_inactive_without_plan(self):
        os.remove(os.path.join(self.run_dir, "plan.md"))
        self.assertEqual(self.claim("1", "builder-1")[0], 0)
        self.assertFalse(os.path.exists(os.path.join(self.run_dir, "claims")))

    def test_spawn_cwd(self):
        spawn = {"hook_event_name": "PreToolUse", "tool_name": "Agent",
                 "tool_input": {"name": "builder-1", "prompt": "x"}}
        sub = os.path.join(self.repo, "sub")
        self.assertEqual(self.hook(SPAWN, spawn, cwd=sub)[0], 0)  # no active run yet
        self.create("1", "be-schema", "api/")
        code, err = self.hook(SPAWN, spawn, cwd=sub)
        self.assertEqual(code, 2)
        self.assertIn(f"cd {os.path.realpath(self.repo)}`", err)
        self.assertEqual(self.hook(SPAWN, spawn)[0], 0)
        self.assertEqual(self.hook(SPAWN, {**spawn, "tool_input": {"prompt": "x"}}, cwd=sub)[0], 0)
        self.update("1", status="completed")
        self.assertEqual(self.hook(SPAWN, spawn, cwd=sub)[0], 0)  # run over


if __name__ == "__main__":
    unittest.main()
