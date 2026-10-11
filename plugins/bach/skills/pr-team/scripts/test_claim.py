"""Tests for claim.py. Run: python3 -m unittest plugins/bach/skills/pr-team/scripts/test_claim.py"""
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
import claim  # noqa: E402

PLAN = """# Plan

| id | folder | files | blockedBy | AC |
|---|---|---|---|---|
| be-schema | api/ | models.py | - | schema exists |
| be-route | api/ | routes.py | be-schema | GET works |
| fe-page | web/ | page.tsx | be-route | page renders |
| docs-readme | docs/ | README.md | — | documented |

Review budget: 2
"""


class Pick(unittest.TestCase):
    def setUp(self):
        self.tasks, self.budget = claim.parse_plan(PLAN)

    def pick(self, builder, claims=None, prs=None):
        return claim.pick(builder, self.tasks, self.budget, claims or {}, prs or {})

    def test_parse(self):
        self.assertEqual([t["id"] for t in self.tasks], ["be-schema", "be-route", "fe-page", "docs-readme"])
        self.assertEqual(self.tasks[1]["blockedby"], ["be-schema"])
        self.assertEqual(self.tasks[3]["blockedby"], [])
        self.assertEqual(self.budget, 2)

    def test_first_ready_in_plan_order(self):
        self.assertEqual(self.pick("b1")[1]["id"], "be-schema")

    def test_folder_held_until_pr_exists(self):
        claims = {"be-schema": "b1"}
        self.assertEqual(self.pick("b2", claims)[1]["id"], "docs-readme")

    def test_same_builder_gets_its_task_back(self):
        self.assertEqual(self.pick("b1", {"be-schema": "b1"})[1]["id"], "be-schema")

    def test_blocked_until_merged_not_opened(self):
        claims = {"be-schema": "b1", "docs-readme": "b2"}
        kind, msg = self.pick("b1", claims, {"be-schema": ("OPEN", 1), "docs-readme": ("OPEN", 2)})
        self.assertEqual(kind, "paused")  # budget 2 hit first
        kind, msg = self.pick("b1", claims, {"be-schema": ("OPEN", 1), "docs-readme": ("MERGED", 2)})
        self.assertEqual(kind, "none")
        self.assertIn("be-route waits for be-schema", msg)
        kind, task = self.pick("b1", claims, {"be-schema": ("MERGED", 1), "docs-readme": ("MERGED", 2)})
        self.assertEqual(task["id"], "be-route")

    def test_budget_pauses(self):
        claims = {"be-schema": "b1", "docs-readme": "b2"}
        kind, msg = self.pick("b3", claims, {"be-schema": ("OPEN", 11), "docs-readme": ("OPEN", 12)})
        self.assertEqual(kind, "paused")
        self.assertIn("2/2", msg)

    def test_all_claimed(self):
        claims = {t["id"]: "b1" for t in self.tasks}
        prs = {t["id"]: ("MERGED", n) for n, t in enumerate(self.tasks)}
        self.assertEqual(self.pick("b2", claims, prs), ("none", "all tasks claimed"))


class Concurrency(unittest.TestCase):
    def test_parallel_claims_never_share_a_task(self):
        with tempfile.TemporaryDirectory() as d:
            plan = os.path.join(d, "plan.md")
            with open(plan, "w") as f:
                f.write(PLAN)
            script = os.path.join(os.path.dirname(__file__), "claim.py")
            stub = os.path.join(d, "gh")
            with open(stub, "w") as f:
                f.write("#!/bin/sh\necho '[]'\n")
            os.chmod(stub, 0o755)
            env = {**os.environ, "PATH": f"{d}:{os.environ['PATH']}"}
            out = {}

            def run(b):
                out[b] = subprocess.run([sys.executable, script, b, "--plan", plan],
                                        capture_output=True, text=True, env=env).stdout.split("\n")[0]

            threads = [threading.Thread(target=run, args=(f"b{i}",)) for i in range(6)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            claimed = [v for v in out.values() if v.startswith("claimed")]
            self.assertEqual(sorted(claimed), ["claimed be-schema", "claimed docs-readme"])
            self.assertEqual(sorted(os.listdir(os.path.join(d, "claims"))), [".lock", "be-schema", "docs-readme"])


if __name__ == "__main__":
    unittest.main()
