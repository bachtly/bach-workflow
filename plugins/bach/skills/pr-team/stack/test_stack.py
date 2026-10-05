"""Pure unit tests for stack.py: no DB, no Redis, no docker.

    python3 -m unittest discover -s plugins/bach/skills/pr-team/stack    (or python3 -m pytest <dir>)
"""

from __future__ import annotations

import fcntl
import importlib.util
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any

_PATH = Path(__file__).resolve().parent / "stack.py"
_spec = importlib.util.spec_from_file_location("stack", _PATH)
assert _spec and _spec.loader
stack: Any = importlib.util.module_from_spec(_spec)
sys.modules["stack"] = stack
_spec.loader.exec_module(stack)

TOML = """
[pools.db]
url = "postgresql+psycopg://app:app@127.0.0.1:${DB_PORT:-5432}"
[pools.db_test]
url = "postgresql+psycopg://app:app@127.0.0.1:${DB_TEST_PORT:-5443}"
[pools.redis]
url = "redis://127.0.0.1:${REDIS_PORT:-6379}"
[names]
dev = "app_s"
test = "app_test_s"
[template]
name = "app_template"
build = ["true"]
[ports]
api = 8100
web = 5200
[limits]
slots = 3
heavy = 2
grace_s = 60
"""


def cfg(toml: str = TOML, **env: str) -> Any:
    return stack.Config.load(toml, env, "Proj-X")


class TempDir(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self) -> None:
        self._td.cleanup()


class ConfigTests(unittest.TestCase):
    def test_interpolates_env_and_defaults(self) -> None:
        c = cfg(DB_PORT="5442")
        self.assertEqual(c.db_url, "postgresql+psycopg://app:app@127.0.0.1:5442")
        self.assertTrue(c.db_test_url.endswith(":5443"))
        self.assertEqual(c.redis_url, "redis://127.0.0.1:6379")
        self.assertEqual((c.slots, c.heavy, c.grace_s), (3, 2, 60))
        self.assertEqual(c.project, "proj_x")

    def test_minimal_config(self) -> None:
        c = cfg('[pools.db]\nurl = "postgresql://u@h:1"\n')
        self.assertEqual(c.db_test_url, c.db_url)
        self.assertIsNone(c.redis_url)
        self.assertEqual(c.ports, {})
        env = stack.slot_env(c, 2)
        self.assertEqual(env["DATABASE_URL"], "postgresql://u@h:1/app_s2")
        self.assertEqual(env["TEST_DATABASE_URL"], "postgresql://u@h:1/app_test_s2")
        self.assertNotIn("REDIS_URL", env)

    def test_rejects_bad_names(self) -> None:
        for bad in ('dev = "App-s"', 'test = "x; drop"', 'dev = "s"\ntest = "s"'):
            with self.assertRaises(stack.StackError):
                cfg(f'[pools.db]\nurl = "postgresql://h"\n[names]\n{bad}\n')

    def test_pg_dsn_strips_driver(self) -> None:
        self.assertEqual(
            stack.pg_dsn("postgresql+psycopg://a:b@h:1/", "x"), "postgresql://a:b@h:1/x"
        )
        self.assertEqual(stack.pg_dsn("postgres://h:1"), "postgres://h:1/postgres")


class SlotEnvTests(unittest.TestCase):
    def test_port_math(self) -> None:
        env = stack.slot_env(cfg(DB_PORT="5442", REDIS_PORT="6389"), 4)
        self.assertEqual(
            env,
            {
                "STACK_SLOT": "4",
                "API_PORT": "8104",
                "API_URL": "http://127.0.0.1:8104",
                "WEB_PORT": "5204",
                "WEB_URL": "http://127.0.0.1:5204",
                "DATABASE_URL": "postgresql+psycopg://app:app@127.0.0.1:5442/app_s4",
                "TEST_DATABASE_URL": "postgresql+psycopg://app:app@127.0.0.1:5443/app_test_s4",
                "REDIS_URL": "redis://127.0.0.1:6389/4",
            },
        )
        self.assertEqual(stack.parse_env(stack.render_env(env, "me")), env)

    def test_custom_env_names_and_prefixes(self) -> None:
        c = cfg(
            '[pools.db]\nurl = "postgresql://h"\nenv = "PG_URL"\n'
            '[names]\ndev = "shop_dev_"\ntest = "shop_t_"\n[ports]\nadmin = 9000\n'
        )
        env = stack.slot_env(c, 1)
        self.assertEqual(env["PG_URL"], "postgresql://h/shop_dev_1")
        self.assertEqual(env["TEST_DATABASE_URL"], "postgresql://h/shop_t_1")
        self.assertEqual(env["ADMIN_PORT"], "9001")


class IdentTests(unittest.TestCase):
    def test_allows_only_stack_databases(self) -> None:
        c = cfg()
        self.assertEqual(stack.ident(c, "app_s3"), '"app_s3"')
        self.assertEqual(stack.ident(c, "app_test_s12"), '"app_test_s12"')
        self.assertEqual(stack.ident(c, "app_template_new"), '"app_template_new"')
        for bad in ("app", "app_test", "app_review", "app_test_b1", "postgres", 'app_s1"; --'):
            with self.assertRaises(stack.StackError, msg=bad):
                stack.ident(c, bad)

    def test_follows_configured_prefixes(self) -> None:
        c = cfg('[pools.db]\nurl = "postgresql://h"\n[names]\ndev = "x_"\ntest = "y_"\n')
        stack.ident(c, "x_1")
        with self.assertRaises(stack.StackError):
            stack.ident(c, "app_s1")
        self.assertTrue(stack.is_test_db(c, "y_1"))
        self.assertFalse(stack.is_test_db(c, "x_1"))


class LivenessTests(TempDir):
    def test_live_worktrees_matches_on_path_boundary(self) -> None:
        cwds = ["/w/a/backend", "/w/ab", "/tmp"]
        self.assertEqual(stack.live_worktrees(cwds, ["/w/a", "/w/abc", "/w/b"]), {"/w/a"})
        self.assertEqual(stack.live_worktrees(["/w/b"], ["/w/b/"]), {"/w/b"})

    def test_is_dead(self) -> None:
        now, wt = 1000.0, str(self.tmp)
        slot = {"worktree": wt, "leased_at": 0.0, "last_used": 990.0}
        self.assertFalse(stack.is_dead(slot, set(), now, grace_s=60))  # idle, within grace
        self.assertTrue(stack.is_dead(slot, set(), now + 100, grace_s=60))  # idle past grace
        self.assertFalse(stack.is_dead(slot, {wt}, now + 100, grace_s=60))  # process inside
        gone = {**slot, "worktree": str(self.tmp / "gone")}
        self.assertTrue(stack.is_dead(gone, {gone["worktree"]}, now, grace_s=60))  # removed

    def test_pick_slot_lowest_free_then_oldest_dead(self) -> None:
        c = cfg()
        a, b, d = (self.tmp / x for x in "abd")
        for p in (a, b, d):
            p.mkdir()

        def s(wt: Path, at: float) -> dict[str, Any]:
            return {"worktree": str(wt), "leased_at": at, "last_used": at}

        reg: dict[str, Any] = {"slots": {"1": s(a, 10), "3": s(b, 20)}}
        self.assertEqual(stack.pick_slot(reg, c, set(), 1000), (2, None))
        reg["slots"]["2"] = s(d, 5)
        self.assertEqual(stack.pick_slot(reg, c, {str(b)}, 1000), (2, 2))  # 1, 2 dead; 2 oldest
        self.assertEqual(stack.pick_slot(reg, c, {str(b), str(d)}, 1000), (1, 1))
        with self.assertRaisesRegex(stack.StackError, "busy"):
            stack.pick_slot(reg, c, {str(a), str(b), str(d)}, 1000)
        # within grace, nothing is reclaimed even with no live process
        with self.assertRaisesRegex(stack.StackError, "busy"):
            stack.pick_slot(reg, c, set(), 30)


class RegistryTests(TempDir):
    def test_lock_is_exclusive_and_persists(self) -> None:
        reg = stack.Registry(self.tmp, "proj")
        with reg.locked() as data:
            data["slots"]["1"] = {"owner": "x"}
            with open(reg.lock_path, "a") as other, self.assertRaises(BlockingIOError):
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.assertEqual(reg.read()["slots"], {"1": {"owner": "x"}})

    def test_concurrent_leases_never_share_a_slot(self) -> None:
        c, reg = cfg(), stack.Registry(self.tmp, "proj")
        got: list[int] = []
        barrier = threading.Barrier(3)

        def lease(i: int) -> None:
            barrier.wait()
            with reg.locked() as data:
                n, _ = stack.pick_slot(data, c, set(), time.time())
                time.sleep(0.05)  # widen the race window
                data["slots"][str(n)] = {"worktree": str(self.tmp / str(i)), "leased_at": 0}
                got.append(n)

        threads = [threading.Thread(target=lease, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(got), [1, 2, 3])
        self.assertEqual(sorted(reg.read()["slots"]), ["1", "2", "3"])

    def test_heavy_semaphore_limits_and_reports_holders(self) -> None:
        heavy = stack.Heavy(self.tmp, "proj", 2)
        a = heavy.try_acquire({"owner": "a", "slot": 1})
        b = heavy.try_acquire({"owner": "b", "slot": 2})
        assert a and b
        self.assertIsNone(heavy.try_acquire({"owner": "c", "slot": 3}))
        self.assertEqual(sorted(h["owner"] for h in heavy.holders()), ["a", "b"])
        a.close()
        c = heavy.try_acquire({"owner": "c", "slot": 3})
        assert c is not None
        self.assertEqual(sorted(h["owner"] for h in heavy.holders()), ["b", "c"])
        b.close()
        c.close()
        self.assertEqual(heavy.holders(), [])


class MiscTests(TempDir):
    def test_alembic_heads(self) -> None:
        files = {
            "a.py": "revision: str = 'aaa'\ndown_revision: str | None = None\n",
            "b.py": 'revision = "bbb"\ndown_revision = "aaa"\n',
            "c.py": "revision = 'ccc'\ndown_revision = ('bbb',)\n",
        }
        self.assertEqual(stack.alembic_heads(files), {"ccc"})

    def test_resp_encoding(self) -> None:
        self.assertEqual(stack.resp(["PING"]), b"*1\r\n$4\r\nPING\r\n")

    def test_destructive_infra_needs_human(self) -> None:
        os.environ.pop("STACK_ROLE", None)
        st = stack.Stack(cfg(), self.tmp, self.tmp, self.tmp)
        for what in ("down", "reset"):
            with self.assertRaisesRegex(stack.StackError, "human-only"):
                st.infra_destructive(what)


if __name__ == "__main__":
    unittest.main()
