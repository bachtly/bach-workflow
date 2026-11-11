"""Tests for run.py, claim.py retirement and idle_claim.py.
Run: python3 -m unittest plugins/bach/skills/pr-team/scripts/test_run.py"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import claim  # noqa: E402

PLAN = """# Plan

Plan: run-1
Review budget: 5
Retire builders after: 2

| id | folder | files | blockedBy | acceptance criteria | flag |
|---|---|---|---|---|---|
| be-schema | api | models.py, shared/types.ts | - | schema exists | - |
| be-route | api | routes.py | - | GET works | - |
| docs-readme | docs | README.md | - | documented | - |
| web-page | web | page.tsx | - | renders | - |

## Lessons

## Decisions
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.realpath(self.tmp.name)
        subprocess.run(["git", "init", "-q", "-b", "main", self.repo], check=True)
        subprocess.run(["git", "-C", self.repo, "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-q", "--allow-empty", "-m", "init"], check=True)
        self.run_dir = os.path.join(self.repo, ".claude", "pr-team")
        os.makedirs(self.run_dir)
        self.plan = os.path.join(self.run_dir, "plan.md")
        with open(self.plan, "w") as f:
            f.write(PLAN)
        bindir = os.path.join(self.repo, "bin")
        os.makedirs(bindir)
        self.gh = os.path.join(bindir, "gh")
        self.stub_gh("echo '[]'")
        self.env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}"}

    def stub_gh(self, body):
        with open(self.gh, "w") as f:
            f.write("#!/bin/sh\n" + body + "\n")
        os.chmod(self.gh, 0o755)

    def tearDown(self):
        self.tmp.cleanup()

    def run_py(self, *args, cwd=None):
        return subprocess.run([sys.executable, os.path.join(HERE, "run.py"), "--plan", self.plan, *args],
                              capture_output=True, text=True, env=self.env, cwd=cwd or self.repo)

    def claim(self, builder, *extra):
        return subprocess.run([sys.executable, os.path.join(HERE, "claim.py"), builder, "--plan", self.plan, *extra],
                              capture_output=True, text=True, env=self.env).stdout.split("\n")[0]

    def status_json(self):
        with open(os.path.join(self.run_dir, "status.json")) as f:
            return json.load(f)


class Pr(Base):
    def test_small_pr_needs_no_message(self):
        out = self.run_py("pr", "be-route", "12", "--builder", "builder-1", "--lines", "40",
                          "--step", "after merge · shell · `pnpm db:migrate` · new table", "--step", "none")
        self.assertIn("size: small", out.stdout)
        self.assertIn("next: nothing to send", out.stdout)
        data = self.status_json()
        self.assertEqual(data["tasks"]["be-route"]["pr"], 12)
        self.assertEqual([(t["when"], t["text"]) for t in data["todo"]],
                         [("after merge", "shell · `pnpm db:migrate` · new table")])

    def test_big_pr_tells_the_builder_to_message_the_lead(self):
        out = self.run_py("pr", "web-page", "13", "--builder", "builder-2", "--ui", "interactive", "--lines", "400")
        self.assertIn("size: big (UI: interactive, 400 lines)", out.stdout)
        self.assertIn("SendMessage the lead `web-page → PR #13 big:", out.stdout)

    def test_standing_mode_messages_the_reviewer(self):
        with open(self.plan, "a") as f:
            f.write("\nReview: standing\n")
        out = self.run_py("pr", "be-route", "12", "--builder", "builder-1")
        self.assertIn("SendMessage your reviewer", out.stdout)

    def test_repeated_step_is_a_no_op(self):
        for _ in range(2):
            self.run_py("pr", "be-route", "12", "--builder", "b", "--step", "before merge · .env · set X · auth")
        self.assertEqual(len(self.status_json()["todo"]), 1)


class Lessons(Base):
    def test_lessons_go_into_plan_once(self):
        self.run_py("lesson", "[all] Tests must fail when the fix is reverted — PR #8", "--by", "reviewer-pr8")
        out = self.run_py("lesson", "[all] Tests must fail when the fix is reverted — PR #8", "--by", "reviewer-pr8")
        self.assertIn("already there", out.stdout)
        with open(self.plan) as f:
            text = f.read()
        self.assertEqual(text.count("Tests must fail"), 1)
        self.assertLess(text.index("## Lessons"), text.index("Tests must fail"))
        self.assertLess(text.index("Tests must fail"), text.index("## Decisions"))

    def test_too_many_lessons_asks_the_lead_to_merge(self):
        for i in range(11):
            out = self.run_py("lesson", f"[all] rule {i} — PR #{i}", "--by", "w")
        self.assertIn("over 10: merge them", out.stdout)

    def test_decision_goes_into_plan(self):
        self.run_py("decision", "PR #8 scope: keep the fallback out → answered 10:05")
        self.run_py("decision", "PR #8 scope: keep the fallback out → answered 10:05")
        with open(self.plan) as f:
            text = f.read()
        self.assertEqual(text.count("PR #8 scope"), 1)
        self.assertLess(text.index("## Decisions"), text.index("PR #8 scope"))


class Scope(Base):
    def worktree(self):
        subprocess.run(["git", "-C", self.repo, "update-ref", "refs/remotes/origin/main", "HEAD"], check=True)
        return self.repo

    def test_in_scope_and_named_contract_file(self):
        wt = self.worktree()
        os.makedirs(os.path.join(wt, "api"))
        os.makedirs(os.path.join(wt, "shared"))
        open(os.path.join(wt, "api", "models.py"), "w").close()
        open(os.path.join(wt, "shared", "types.ts"), "w").close()
        with open(os.path.join(wt, ".gitignore"), "w") as f:
            f.write(".claude/\nbin/\n.gitignore\n")
        out = self.run_py("scope", "be-schema", cwd=wt)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("scope ok: 2 files", out.stdout)

    def test_out_of_scope(self):
        wt = self.worktree()
        os.makedirs(os.path.join(wt, "web"))
        open(os.path.join(wt, "web", "x.tsx"), "w").close()
        with open(os.path.join(wt, ".gitignore"), "w") as f:
            f.write(".claude/\nbin/\n.gitignore\n")
        out = self.run_py("scope", "be-route", cwd=wt)
        self.assertEqual(out.returncode, 1)
        self.assertIn("web/x.tsx", out.stdout)


class Status(Base):
    def test_status_table_and_todo(self):
        self.stub_gh("""case "$*" in
  *"view 12"*) echo '{"number":12,"title":"Route","url":"u12","state":"OPEN","reviewDecision":"","labels":[]}';;
  *"view 13"*) echo '{"number":13,"title":"Page","url":"u13","state":"MERGED","reviewDecision":"","labels":[]}';;
  *) echo '[]';;
esac""")
        self.run_py("pr", "be-route", "12", "--builder", "builder-1", "--step", "before merge · .env · set KEY · api")
        self.run_py("pr", "web-page", "13", "--builder", "builder-2", "--step", "after merge · shell · seed · demo")
        out = self.run_py("status")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("- [ ] #12 · .env · set KEY · api", out.stdout)
        self.assertIn("- [ ] Review #12 Route", out.stdout)
        self.assertIn("- [ ] #13 · shell · seed · demo", out.stdout)
        self.assertIn("| [#12](u12) | Route | be-route | builder-1 | 🟡 Ready for review |", out.stdout)
        self.assertLess(out.stdout.index("#12](u12)"), out.stdout.index("#13](u13)"))  # open first
        self.assertIn("Open PRs: 1 / review budget 5", out.stdout)


class Retire(Base):
    def test_builder_retires_after_n_tasks_and_its_replacement_starts_fresh(self):
        self.assertEqual(self.claim("builder-1"), "claimed be-schema")
        # be-schema got a PR so builder-1 can claim again; api is held, so it gets docs-readme
        self.stub_gh("""case "$*" in *'--head be-schema'*) echo '[{"number":1,"headRefName":"be-schema","state":"OPEN","createdAt":"2999-01-01T00:00:00Z"}]';;
*'--head docs-readme'*) echo '[{"number":2,"headRefName":"docs-readme","state":"OPEN","createdAt":"2999-01-01T00:00:00Z"}]';; *) echo '[]';; esac""")
        self.assertEqual(self.claim("builder-1"), "claimed docs-readme")
        self.assertTrue(self.claim("builder-1", "--peek").startswith("retire:"))
        self.assertFalse(os.path.exists(os.path.join(self.run_dir, "claims", "run-1", ".retired")))  # peek wrote nothing
        self.assertTrue(self.claim("builder-1").startswith("retire:"))
        # the fresh builder-1 counts from the retire mark
        self.assertEqual(self.claim("builder-1"), "claimed web-page")


class IdleHook(Base):
    def hook(self, name):
        event = json.dumps({"hook_event_name": "TeammateIdle", "teammate_name": name, "cwd": self.repo})
        return subprocess.run([sys.executable, os.path.join(HERE, "idle_claim.py")], input=event,
                              capture_output=True, text=True, env=self.env)

    def test_pushes_a_builder_to_a_claimable_task_once(self):
        out = self.hook("builder-1")
        self.assertEqual(out.returncode, 2)
        self.assertIn("Task `be-schema` is claimable", out.stderr)
        self.assertEqual(self.hook("builder-1").returncode, 0)  # same task again within 10 min: no loop

    def test_ignores_other_teammates_and_held_tasks(self):
        self.assertEqual(self.hook("pr-watcher").returncode, 0)
        self.assertEqual(self.hook("reviewer-pr3").returncode, 0)
        self.claim("builder-2")  # holds be-schema without a PR: waiting on purpose
        self.assertEqual(self.hook("builder-2").returncode, 0)

    def test_every_call_in_a_run_is_logged(self):
        self.hook("builder-1")
        self.hook("pr-watcher")
        event = json.dumps({"hook_event_name": "TeammateIdle", "cwd": self.repo})  # no teammate_name
        subprocess.run([sys.executable, os.path.join(HERE, "idle_claim.py")], input=event,
                       capture_output=True, text=True, env=self.env)
        with open(os.path.join(self.run_dir, ".idle-hook.log")) as f:
            rows = [json.loads(l) for l in f]
        self.assertEqual([(r["teammate_name"], r["exit"]) for r in rows],
                         [("builder-1", 2), ("pr-watcher", 0), (None, 0)])
        self.assertEqual(rows[0]["reason"], "pushed to be-schema")
        self.assertEqual(rows[2]["reason"], "no teammate_name in input")
        self.assertIn("cwd", rows[0]["keys"])

    def test_no_run_no_op(self):
        os.remove(self.plan)
        self.assertEqual(self.hook("builder-1").returncode, 0)


if __name__ == "__main__":
    unittest.main()
