"""Tests for claim.py. Run: python3 -m unittest plugins/bach/skills/pr-team/scripts/test_claim.py"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import claim  # noqa: E402

PLAN = """# Plan

Run: run-1

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
        self.run_id, self.tasks, self.headers = claim.parse_plan(PLAN)

    def pick(self, builder, claims=None, prs=None):
        return claim.pick(builder, self.tasks, claims or {}, prs or [])

    def test_parse(self):
        self.assertEqual(self.run_id, "run-1")
        self.assertEqual([t["id"] for t in self.tasks], ["be-schema", "be-route", "fe-page", "docs-readme"])
        self.assertEqual(self.tasks[1]["blockedby"], ["be-schema"])
        self.assertEqual(self.tasks[3]["blockedby"], [])

    def test_no_run_line(self):
        self.assertIsNone(claim.parse_plan(PLAN.replace("Run: run-1", ""))[0])
        self.assertEqual(self.headers[:3], ["id", "folder", "files"])

    def test_first_ready_in_plan_order(self):
        self.assertEqual(self.pick("b1")[1]["id"], "be-schema")

    def test_folder_held_until_its_pr_merges(self):
        claims = {"be-schema": {"builder": "b1", "at": 100}}
        self.assertEqual(self.pick("b2", claims)[1]["id"], "docs-readme")
        open_pr = [("be-schema", "OPEN", 1, 200)]
        self.assertEqual(self.pick("b2", claims, open_pr)[1]["id"], "docs-readme")  # still held
        claims["docs-readme"] = {"builder": "b2", "at": 100}
        kind, why = self.pick("b2", claims, open_pr + [("docs-readme", "OPEN", 2, 200)])
        self.assertEqual(kind, "none")
        self.assertIn("be-route: folder api/ is held", why)

    def test_same_builder_gets_its_task_back_until_it_has_a_pr(self):
        claims = {"be-schema": {"builder": "b1", "at": 100}}
        self.assertEqual(self.pick("b1", claims)[1]["id"], "be-schema")
        self.assertEqual(self.pick("b1", claims, [("be-schema", "OPEN", 1, 200)])[1]["id"], "docs-readme")

    def test_blocked_until_merged_not_opened(self):
        claims = {"be-schema": {"builder": "b1", "at": 100}, "docs-readme": {"builder": "b2", "at": 100}}
        kind, _ = self.pick("b1", claims, [("be-schema", "OPEN", 1, 200), ("docs-readme", "MERGED", 2, 200)])
        self.assertEqual(kind, "none")
        kind, task = self.pick("b1", claims, [("be-schema", "MERGED", 1, 200), ("docs-readme", "MERGED", 2, 200)])
        self.assertEqual(task["id"], "be-route")

    def test_only_a_pr_created_after_the_claim_counts(self):
        claims = {"be-schema": {"builder": "b1", "at": 100}, "docs-readme": {"builder": "b2", "at": 100}}
        old_merged = [("be-schema", "MERGED", 7, -900), ("docs-readme", "MERGED", 8, 200)]
        kind, why = self.pick("b2", claims, old_merged)
        self.assertEqual(kind, "none")
        self.assertIn("be-route: folder api/ is held", why)

    def test_closed_pr_keeps_the_folder_and_blocks_dependents(self):
        claims = {"be-schema": {"builder": "b1", "at": 100}}
        closed = [("be-schema", "CLOSED", 1, 200)]
        self.assertEqual(self.pick("b2", claims, closed)[1]["id"], "docs-readme")
        claims["docs-readme"] = {"builder": "b2", "at": 100}
        kind, why = self.pick("b2", claims, closed + [("docs-readme", "OPEN", 2, 200)])
        self.assertEqual(kind, "none")
        self.assertIn("be-route: folder api/ is held", why)

    def test_pr_a_little_before_the_claim_counts_for_clock_skew(self):
        claims = {"be-schema": {"builder": "b1", "at": 1000}, "docs-readme": {"builder": "b2", "at": 1000}}
        prs = [("be-schema", "MERGED", 1, 1000 - 30), ("docs-readme", "MERGED", 2, 1000 - 30)]
        self.assertEqual(self.pick("b1", claims, prs)[1]["id"], "be-route")
        stale = [("be-schema", "MERGED", 1, 1000 - 600)]
        self.assertEqual(self.pick("b3", claims, stale)[0], "none")

    def test_unknown_blocker_is_reported(self):
        tasks = [{"id": "b", "folder": "web/", "blockedby": ["gone"]}]
        kind, why = claim.pick("b1", tasks, {}, [])
        self.assertEqual(kind, "none")
        self.assertIn("blockedBy unknown task gone", why)

    def test_all_claimed(self):
        claims = {t["id"]: {"builder": "b1", "at": 100} for t in self.tasks}
        prs = [(t["id"], "MERGED", n, 200) for n, t in enumerate(self.tasks)]
        self.assertEqual(self.pick("b2", claims, prs), ("none", "all tasks claimed"))


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.realpath(self.tmp.name)
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        self.run_dir = os.path.join(self.repo, ".claude", "pr-team")
        os.makedirs(self.run_dir)
        self.plan = os.path.join(self.run_dir, "plan.md")
        with open(self.plan, "w") as f:
            f.write(PLAN)
        bindir = os.path.join(self.tmp.name, "bin")
        os.makedirs(bindir)
        with open(os.path.join(bindir, "gh"), "w") as f:
            f.write("#!/bin/sh\necho '[]'\n")
        os.chmod(os.path.join(bindir, "gh"), 0o755)
        self.env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}"}
        self.script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "claim.py")

    def tearDown(self):
        self.tmp.cleanup()

    def claim(self, builder):
        return subprocess.run([sys.executable, self.script, builder, "--plan", self.plan],
                              capture_output=True, text=True, env=self.env)

    def test_parallel_claims_never_share_a_task(self):
        out = {}
        threads = [threading.Thread(target=lambda b=f"b{i}": out.update({b: self.claim(b).stdout.split("\n")[0]}))
                   for i in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        claimed = sorted(v for v in out.values() if v.startswith("claimed"))
        self.assertEqual(claimed, ["claimed be-schema", "claimed docs-readme"])
        names = sorted(os.listdir(os.path.join(self.run_dir, "claims", "run-1")))
        self.assertEqual(names, [".lock", "be-schema", "docs-readme"])

    def test_a_new_run_id_starts_clean(self):
        self.claim("b1")
        with open(self.plan, "w") as f:
            f.write(PLAN.replace("run-1", "run-2"))
        self.assertEqual(self.claim("b2").stdout.split("\n")[0], "claimed be-schema")

    def test_error_without_a_run_line(self):
        with open(self.plan, "w") as f:
            f.write(PLAN.replace("Run: run-1", ""))
        out = self.claim("b1")
        self.assertEqual(out.returncode, 2)
        self.assertIn("no `Run: <id>` line", out.stderr)

    def test_task_ids_must_be_kebab_names(self):
        with open(self.plan, "w") as f:
            f.write("Run: r\n\n| id | folder | blockedBy |\n|---|---|---|\n| fix/a-b | api/ | - |\n")
        out = self.claim("b1")
        self.assertEqual(out.returncode, 2)
        self.assertIn("short kebab names", out.stderr)
        self.assertIn("fix/a-b", out.stderr)

    def test_the_lead_releases_a_claim_by_deleting_its_file(self):
        self.claim("b1")
        os.remove(os.path.join(self.run_dir, "claims", "run-1", "be-schema"))
        self.assertEqual(self.claim("b2").stdout.split("\n")[0], "claimed be-schema")

    def test_a_broken_claim_file_affects_only_itself(self):
        self.assertEqual(self.claim("b1").stdout.split("\n")[0], "claimed be-schema")
        self.assertEqual(self.claim("b2").stdout.split("\n")[0], "claimed docs-readme")
        with open(os.path.join(self.run_dir, "claims", "run-1", "docs-readme"), "w") as f:
            f.write("oops, not json\n")
        out = self.claim("b3")
        self.assertEqual(out.returncode, 0)
        self.assertIn("ignoring unreadable claim docs-readme", out.stderr)
        self.assertEqual(out.stdout.split("\n")[0], "claimed docs-readme")  # released as the message says
        with open(os.path.join(self.run_dir, "claims", "run-1", "be-schema")) as f:
            self.assertEqual(json.load(f)["builder"], "b1")  # the other claim is untouched

    def test_error_lists_the_headers_it_found(self):
        with open(self.plan, "w") as f:
            f.write("Run: r\n\n| id | folder | deps |\n|---|---|---|\n| a | b | c |\n")
        out = self.claim("b1")
        self.assertEqual(out.returncode, 2)
        self.assertIn("first table has: id, folder, deps", out.stderr)

    def test_claim_file_records_builder_and_time(self):
        self.claim("b1")
        with open(os.path.join(self.run_dir, "claims", "run-1", "be-schema")) as f:
            data = json.load(f)
        self.assertEqual(data["builder"], "b1")
        self.assertGreater(data["at"], 0)


if __name__ == "__main__":
    unittest.main()
