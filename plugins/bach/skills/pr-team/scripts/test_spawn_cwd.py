"""Tests for spawn_cwd.py. Run: python3 -m unittest plugins/bach/skills/pr-team/scripts/test_spawn_cwd.py

The event is the PreToolUse(Agent) payload Claude Code 2.1.296 sends: `cwd` is the
lead's current directory, `tool_input.name` is set for a teammate.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "spawn_cwd.py")
SKILL = os.path.join(HERE, "..", "SKILL.md")


class SpawnCwd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.realpath(self.tmp.name)
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        os.makedirs(os.path.join(self.repo, "sub"))

    def tearDown(self):
        self.tmp.cleanup()

    def run_hook(self, cwd, tool_input, project_dir=None):
        event = {"hook_event_name": "PreToolUse", "tool_name": "Agent", "cwd": cwd, "tool_input": tool_input}
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
        if project_dir:
            env["CLAUDE_PROJECT_DIR"] = project_dir
        out = subprocess.run([sys.executable, SCRIPT], input=json.dumps(event), capture_output=True, text=True, env=env)
        return out.returncode, out.stderr

    def test_named_spawn_from_a_subfolder_is_blocked(self):
        code, err = self.run_hook(os.path.join(self.repo, "sub"), {"name": "builder-1", "prompt": "x"})
        self.assertEqual(code, 2)
        self.assertIn(f"cd {self.repo}`", err)

    def test_monorepo_project_dir_below_the_git_root(self):
        project = os.path.join(self.repo, "apps", "web")
        os.makedirs(project)
        self.assertEqual(self.run_hook(project, {"name": "b"}, project_dir=project)[0], 0)  # started here: fine
        code, err = self.run_hook(self.repo, {"name": "b"}, project_dir=project)  # lead cd'd up to the git root
        self.assertEqual(code, 2)
        self.assertIn(f"cd {project}`", err)

    def test_named_spawn_from_the_root_passes(self):
        self.assertEqual(self.run_hook(self.repo, {"name": "builder-1"})[0], 0)

    def test_unnamed_subagent_and_isolation_pass(self):
        sub = os.path.join(self.repo, "sub")
        self.assertEqual(self.run_hook(sub, {"prompt": "x"})[0], 0)
        self.assertEqual(self.run_hook(sub, {"name": "b", "isolation": "worktree"})[0], 0)

    def test_outside_a_repo_passes(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.run_hook(d, {"name": "b"})[0], 0)

    def test_skill_registers_the_hook_on_agent_spawns(self):
        with open(SKILL) as f:
            head = f.read().split("---")[1]
        self.assertRegex(head, r"PreToolUse:\s*\n\s*- matcher: \"Agent\"")
        self.assertIn('"python3 \\"${CLAUDE_PLUGIN_ROOT}/skills/pr-team/scripts/spawn_cwd.py\\""', head)
        path = re.search(r"skills/pr-team/scripts/(spawn_cwd\.py)", head).group(1)
        self.assertTrue(os.path.exists(os.path.join(HERE, path)))


if __name__ == "__main__":
    unittest.main()
