"""App stack for parallel agents: isolated slots on one shared Postgres (+ optional Redis).

Run it through the `stack` wrapper next to this file, from inside a git worktree of a repo
that has a `stack.toml` at its root (see stack.example.toml).

    stack lease <owner>          reserve a slot, write .env.slot in this worktree
    stack run [--db dev|test] [--ports] [--heavy] -- <cmd>
    stack release [N]            drop the slot's DBs, free it
    stack ls | gc | doctor
    stack infra ensure           compose up the configured services (idempotent, never recreates)
    stack template refresh       rebuild the template DB (template.build), swap under a lock
    stack infra down|reset       human only (STACK_ROLE=human)

Slot N: <NAME>_PORT = ports.<name> + N, dev DB <names.dev>N (cloned from the template),
test DB <names.test>N (empty), Redis DB index N.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import re
import shlex
import socket
import subprocess
import sys
import time
import urllib.parse
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any

SLOT_FILE = ".env.slot"
CONFIG_FILE = "stack.toml"
MAX_WAITS = 50
PROG = os.environ.get("STACK_PROG", "stack")
_NAME_RE = re.compile(r"[a-z_][a-z0-9_]*")


class StackError(Exception):
    pass


# ---------------------------------------------------------------- pure helpers


def interpolate(value: str, env: dict[str, str]) -> str:
    """Expand ${VAR} and ${VAR:-default}."""

    def sub(m: re.Match[str]) -> str:
        name, default = m.group(1), m.group(3)
        return env.get(name) or (default if default is not None else "")

    return re.sub(r"\$\{(\w+)(:-([^}]*))?\}", sub, value)


def parse_env(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip("'\"")
    return out


def _toml_loads(text: str) -> dict[str, Any]:
    try:
        import tomllib
    except ModuleNotFoundError:  # Python < 3.11
        raise StackError("needs Python >= 3.11 (tomllib); use the `stack` wrapper") from None
    return tomllib.loads(text)


def _name(value: str, what: str) -> str:
    if not _NAME_RE.fullmatch(value):
        raise StackError(f"{what} {value!r} must match [a-z_][a-z0-9_]*")
    return value


@dataclass(frozen=True)
class Config:
    project: str
    db_url: str
    db_test_url: str
    redis_url: str | None
    db_env: str = "DATABASE_URL"
    db_test_env: str = "TEST_DATABASE_URL"
    redis_env: str = "REDIS_URL"
    dev_prefix: str = "app_s"
    test_prefix: str = "app_test_s"
    template: str = "app_template"
    template_cwd: str = "."
    template_build: tuple[str, ...] = ()
    revision_sql: str | None = None
    migrations: str | None = None
    ports: dict[str, int] = field(default_factory=dict)
    slots: int = 6
    heavy: int = 2
    grace_s: int = 600
    compose_file: str | None = None
    services: tuple[str, ...] = ()
    env_file: str = ".env"

    @staticmethod
    def load(toml_text: str, env: dict[str, str], project: str) -> Config:
        raw = _toml_loads(toml_text)
        pools = raw.get("pools", {})
        if "db" not in pools:
            raise StackError(f"{CONFIG_FILE}: [pools.db] url is required")
        db, db_test = pools["db"], pools.get("db_test", pools["db"])
        redis = pools.get("redis")
        names, tmpl = raw.get("names", {}), raw.get("template", {})
        lim, infra, proj = raw.get("limits", {}), raw.get("infra", {}), raw.get("project", {})
        cfg = Config(
            project=_name(
                re.sub(r"[^a-z0-9_]", "_", (proj.get("name") or project).lower()), "project.name"
            ),
            db_url=interpolate(db["url"], env).rstrip("/"),
            db_test_url=interpolate(db_test["url"], env).rstrip("/"),
            redis_url=interpolate(redis["url"], env).rstrip("/") if redis else None,
            db_env=db.get("env", "DATABASE_URL"),
            db_test_env=db_test.get("env", "TEST_DATABASE_URL")
            if db_test is not db
            else "TEST_DATABASE_URL",
            redis_env=(redis or {}).get("env", "REDIS_URL"),
            dev_prefix=_name(names.get("dev", "app_s"), "names.dev"),
            test_prefix=_name(names.get("test", "app_test_s"), "names.test"),
            template=_name(tmpl.get("name", "app_template"), "template.name"),
            template_cwd=tmpl.get("cwd", "."),
            template_build=tuple(tmpl.get("build", ())),
            revision_sql=tmpl.get("revision_sql"),
            migrations=tmpl.get("migrations"),
            ports={k: int(v) for k, v in raw.get("ports", {}).items()},
            slots=int(lim.get("slots", 6)),
            heavy=int(lim.get("heavy", 2)),
            grace_s=int(lim.get("grace_s", 600)),
            compose_file=infra.get("compose_file"),
            services=tuple(infra.get("services", ())),
            env_file=proj.get("env_file", ".env"),
        )
        if cfg.dev_prefix == cfg.test_prefix:
            raise StackError(f"{CONFIG_FILE}: names.dev and names.test must differ")
        return cfg


def db_dev(cfg: Config, n: int) -> str:
    return f"{cfg.dev_prefix}{n}"


def db_test(cfg: Config, n: int) -> str:
    return f"{cfg.test_prefix}{n}"


def stack_db_pattern(cfg: Config) -> str:
    """The only database names the stack will create, clone or drop."""
    t = re.escape(cfg.template)
    return (
        rf"({re.escape(cfg.dev_prefix)}\d+|{re.escape(cfg.test_prefix)}\d+|{t}|{t}_new)"
    )


def ident(cfg: Config, name: str) -> str:
    if not re.fullmatch(stack_db_pattern(cfg), name):
        raise StackError(f"refusing to touch database {name!r} (not a stack DB)")
    return f'"{name}"'


def is_test_db(cfg: Config, name: str) -> bool:
    return re.fullmatch(rf"{re.escape(cfg.test_prefix)}\d+", name) is not None


def slot_env(cfg: Config, n: int) -> dict[str, str]:
    """Everything a job in slot N needs: the port math lives here."""
    env = {"STACK_SLOT": str(n)}
    for name, base in cfg.ports.items():
        env[f"{name.upper()}_PORT"] = str(base + n)
        env[f"{name.upper()}_URL"] = f"http://127.0.0.1:{base + n}"
    env[cfg.db_env] = f"{cfg.db_url}/{db_dev(cfg, n)}"
    env[cfg.db_test_env] = f"{cfg.db_test_url}/{db_test(cfg, n)}"
    if cfg.redis_url:
        env[cfg.redis_env] = f"{cfg.redis_url}/{n}"
    return env


def render_env(env: dict[str, str], owner: str) -> str:
    head = f"# written by `stack lease {owner}`; do not commit\n"
    return head + "".join(f"{k}={v}\n" for k, v in env.items())


def live_worktrees(cwds: Iterable[str], worktrees: Iterable[str]) -> set[str]:
    """Worktrees that have at least one process whose cwd is inside them."""
    roots = {w.rstrip("/") for w in worktrees}
    live: set[str] = set()
    for cwd in cwds:
        for root in roots:
            if cwd == root or cwd.startswith(root + "/"):
                live.add(root)
    return live


def is_dead(slot: dict[str, Any], live: set[str], now: float, grace_s: int) -> bool:
    wt = slot["worktree"].rstrip("/")
    if not Path(wt).is_dir():
        return True
    if wt in live:
        return False
    return now - float(slot.get("last_used", slot["leased_at"])) > grace_s


def pick_slot(
    reg: dict[str, Any], cfg: Config, live: set[str], now: float
) -> tuple[int, int | None]:
    """Return (slot, reclaimed): lowest free slot, else the oldest dead one."""
    slots: dict[str, Any] = reg["slots"]
    for n in range(1, cfg.slots + 1):
        if str(n) not in slots:
            return n, None
    dead = [
        (float(s["leased_at"]), int(k))
        for k, s in slots.items()
        if int(k) <= cfg.slots and is_dead(s, live, now, cfg.grace_s)
    ]
    if not dead:
        raise StackError(
            f"all {cfg.slots} slots busy and alive; see `{PROG} doctor`, "
            f"release one, or raise limits.slots in {CONFIG_FILE}"
        )
    n = min(dead)[1]
    return n, n


def alembic_heads(files: dict[str, str]) -> set[str]:
    """Alembic heads from {filename: source} of a versions folder."""
    revs: set[str] = set()
    downs: set[str] = set()
    for src in files.values():
        rev = re.search(r"^revision\s*(?::\s*str\s*)?=\s*['\"](\w+)['\"]", src, re.M)
        if not rev:
            continue
        revs.add(rev.group(1))
        down = re.search(r"^down_revision[^=]*=\s*(.+)$", src, re.M)
        if down:
            downs.update(re.findall(r"['\"](\w+)['\"]", down.group(1)))
    return revs - downs


def pg_dsn(url: str, db: str = "postgres") -> str:
    """SQLAlchemy-style URL (postgresql+driver://) -> libpq URL for database `db`."""
    return re.sub(r"^postgres(ql)?\+\w+://", "postgresql://", url).rstrip("/") + "/" + db


def resp(args: list[str]) -> bytes:
    out = f"*{len(args)}\r\n"
    for a in args:
        out += f"${len(a.encode())}\r\n{a}\r\n"
    return out.encode()


# ---------------------------------------------------------------- environment


def git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def worktree_root(cwd: Path | None = None) -> Path:
    try:
        return Path(git("rev-parse", "--show-toplevel", cwd=cwd or Path.cwd()))
    except subprocess.CalledProcessError:
        raise StackError("not inside a git worktree") from None


def main_root(cwd: Path | None = None) -> Path:
    common = git("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=cwd)
    return Path(common).parent


def load_config() -> tuple[Config, Path, Path]:
    """(config, this worktree's root, the main checkout's root)."""
    root = worktree_root()
    main = main_root(root)
    path = next((p / CONFIG_FILE for p in (root, main) if (p / CONFIG_FILE).exists()), None)
    if path is None:
        raise StackError(
            f"no {CONFIG_FILE} in {root} or {main}; copy stack.example.toml from the plugin"
        )
    text = path.read_text()
    env_name = _toml_loads(text).get("project", {}).get("env_file", ".env")
    env_file = main / env_name
    file_env = parse_env(env_file.read_text()) if env_file.exists() else {}
    env = {**file_env, **os.environ}
    project = env.get("PROJECT_NAME") or main.name
    return Config.load(text, env, project), root, main


def stack_home() -> Path:
    home = Path(os.environ.get("STACK_HOME", Path.home() / ".stack"))
    home.mkdir(parents=True, exist_ok=True)
    return home


def process_cwds() -> list[str]:
    out = subprocess.run(
        ["lsof", "-w", "-d", "cwd", "-Fn"], capture_output=True, text=True
    ).stdout
    return [line[1:] for line in out.splitlines() if line.startswith("n")]


# ---------------------------------------------------------------- registry


class Registry:
    """JSON file guarded by an exclusive fcntl lock on a sibling .lock file."""

    def __init__(self, home: Path, project: str) -> None:
        self.path = home / f"{project}.json"
        self.lock_path = home / f"{project}.lock"

    @contextlib.contextmanager
    def locked(self) -> Iterator[dict[str, Any]]:
        with open(self.lock_path, "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                data = self.read()
                yield data
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
                tmp.replace(self.path)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def read(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if self.path.exists():
            data = json.loads(self.path.read_text() or "{}")
        data.setdefault("slots", {})
        data.setdefault("heavy_waits", [])
        data.setdefault("template", {})
        return data


# ---------------------------------------------------------------- semaphore


class Heavy:
    """N permit files; holding an flock on one = holding a heavy permit."""

    def __init__(self, home: Path, project: str, limit: int) -> None:
        self.files = [home / f"{project}.heavy.{i}" for i in range(limit)]

    def try_acquire(self, info: dict[str, Any]) -> IO[str] | None:
        for path in self.files:
            f = open(path, "a+")
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                f.close()
                continue
            f.seek(0)
            f.truncate()
            f.write(json.dumps(info))
            f.flush()
            return f
        return None

    def holders(self) -> list[dict[str, Any]]:
        out = []
        for path in self.files:
            if not path.exists():
                continue
            with open(path, "a+") as f:
                try:
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(f, fcntl.LOCK_UN)
                    continue  # free
                except BlockingIOError:
                    pass
                f.seek(0)
                try:
                    out.append(json.loads(f.read() or "{}"))
                except json.JSONDecodeError:
                    out.append({"owner": "?"})
        return out


# ---------------------------------------------------------------- postgres / redis


@contextlib.contextmanager
def pg(url: str, db: str = "postgres") -> Iterator[Any]:
    try:
        import psycopg
    except ModuleNotFoundError:
        raise StackError(
            "psycopg missing; run through the `stack` wrapper (uv adds it) "
            "or `pip install 'psycopg[binary]'`"
        ) from None
    with psycopg.connect(pg_dsn(url, db), autocommit=True, connect_timeout=3) as conn:
        yield conn


def db_exists(url: str, name: str) -> bool:
    with pg(url) as c:
        row = c.execute("SELECT 1 FROM pg_database WHERE datname=%s", (name,)).fetchone()
        return row is not None


def redis_ping(url: str) -> bool:
    u = urllib.parse.urlparse(url)
    with socket.create_connection((u.hostname or "127.0.0.1", u.port or 6379), timeout=2) as s:
        if u.password:
            auth = [u.username, u.password] if u.username else [u.password]
            s.sendall(resp(["AUTH", *auth]))
            if not s.recv(64).startswith(b"+OK"):
                return False
        s.sendall(resp(["PING"]))
        return s.recv(64).startswith(b"+PONG")


def port_busy(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.2)
        return s.connect_ex(("127.0.0.1", port)) == 0


# ---------------------------------------------------------------- commands


class Stack:
    def __init__(self, cfg: Config, home: Path, root: Path, main: Path) -> None:
        self.cfg = cfg
        self.root = root  # this worktree
        self.main = main  # the main checkout: .env and compose live here
        self.reg = Registry(home, cfg.project)
        self.heavy = Heavy(home, cfg.project, cfg.heavy)
        self.template_lock = home / f"{cfg.project}.template.lock"
        self.permit: IO[str] | None = None

    def drop_db(self, url: str, name: str) -> None:
        with pg(url) as c:
            c.execute(f"DROP DATABASE IF EXISTS {ident(self.cfg, name)} WITH (FORCE)")

    def _free(self, reg: dict[str, Any], n: int) -> list[str]:
        """Drop the DBs slot N created, remove .env.slot, forget the slot."""
        slot = reg["slots"].pop(str(n), None)
        if slot is None:
            return []
        dropped = []
        for name in slot.get("dbs", []):
            url = self.cfg.db_test_url if is_test_db(self.cfg, name) else self.cfg.db_url
            self.drop_db(url, name)
            dropped.append(name)
        f = Path(slot["worktree"]) / SLOT_FILE
        if f.exists() and parse_env(f.read_text()).get("STACK_SLOT") == str(n):
            f.unlink()
        return dropped

    # -- template helpers

    def template_revision(self) -> str | None:
        if not self.cfg.revision_sql:
            return None
        try:
            with pg(self.cfg.db_url, self.cfg.template) as c:
                row = c.execute(self.cfg.revision_sql).fetchone()
                return str(row[0]) if row else None
        except Exception:
            return None

    def main_heads(self) -> set[str]:
        """Alembic heads on the default branch, if template.migrations is set."""
        if not self.cfg.migrations:
            return set()
        folder = self.cfg.migrations.rstrip("/") + "/"
        for ref in ("origin/HEAD", "origin/main", "origin/master", "main", "master"):
            try:
                names = git("ls-tree", "--name-only", ref, folder, cwd=self.main)
            except subprocess.CalledProcessError:
                continue
            files = {
                n: git("show", f"{ref}:{n}", cwd=self.main)
                for n in names.splitlines()
                if n.endswith(".py")
            }
            return alembic_heads(files)
        return set()

    def warn_template_stale(self) -> None:
        try:
            exists = db_exists(self.cfg.db_url, self.cfg.template)
        except Exception:
            return
        if not exists:
            print(
                f"stack: warning: {self.cfg.template} missing; run `{PROG} template refresh`",
                file=sys.stderr,
            )
            return
        rev, heads = self.template_revision(), self.main_heads()
        if rev and heads and rev not in heads:
            print(
                f"stack: warning: {self.cfg.template} is at {rev}, main head is "
                f"{','.join(sorted(heads))}; run `{PROG} template refresh`",
                file=sys.stderr,
            )

    # -- slots

    def lease(self, owner: str) -> int:
        wt = str(self.root)
        with self.reg.locked() as reg:
            now = time.time()
            for k, s in reg["slots"].items():
                if s["worktree"] == wt:
                    n = int(k)
                    s.update(owner=owner, last_used=now)
                    print(f"stack: {wt} already holds slot {n}")
                    break
            else:
                live = live_worktrees(
                    process_cwds(), [s["worktree"] for s in reg["slots"].values()]
                )
                n, reclaimed = pick_slot(reg, self.cfg, live, now)
                if reclaimed is not None:
                    old = reg["slots"][str(n)]
                    dropped = self._free(reg, n)
                    print(
                        f"stack: reclaimed dead slot {n} from {old['owner']} "
                        f"({old['worktree']}), dropped {dropped or 'nothing'}"
                    )
                reg["slots"][str(n)] = {
                    "owner": owner,
                    "worktree": wt,
                    "leased_at": now,
                    "last_used": now,
                    "dbs": [],
                }
        env = slot_env(self.cfg, n)
        (Path(wt) / SLOT_FILE).write_text(render_env(env, owner))
        ports = " ".join(f"{k}={v}" for k, v in env.items() if k.endswith("_PORT"))
        print(
            f"slot {n}: {ports} DB={db_dev(self.cfg, n)} TEST_DB={db_test(self.cfg, n)}"
            + (f" REDIS=/{n}" if self.cfg.redis_url else "")
            + f" -> {wt}/{SLOT_FILE}"
        )
        self.warn_template_stale()
        return n

    def release(self, n: int | None) -> None:
        if n is None:
            n = int(read_slot_file(self.root)["STACK_SLOT"])
        with self.reg.locked() as reg:
            if str(n) not in reg["slots"]:
                raise StackError(f"slot {n} is not leased")
            dropped = self._free(reg, n)
        print(f"stack: released slot {n}, dropped {dropped or 'nothing'}")

    def gc(self) -> None:
        with self.reg.locked() as reg:
            live = live_worktrees(process_cwds(), [s["worktree"] for s in reg["slots"].values()])
            now = time.time()
            dead = [
                int(k) for k, s in reg["slots"].items() if is_dead(s, live, now, self.cfg.grace_s)
            ]
            for n in sorted(dead):
                owner = reg["slots"][str(n)]["owner"]
                print(f"stack: gc slot {n} ({owner}): dropped {self._free(reg, n) or 'nothing'}")
        if not dead:
            print("stack: nothing to collect")

    def _rows(self) -> list[str]:
        reg = self.reg.read()
        live = live_worktrees(process_cwds(), [s["worktree"] for s in reg["slots"].values()])
        now = time.time()
        rows = [f"{'slot':<5}{'owner':<16}{'state':<8}{'age':>7}  {'dbs':<28}worktree"]
        for k in sorted(reg["slots"], key=int):
            s = reg["slots"][k]
            if s["worktree"].rstrip("/") in live:
                state = "live"
            elif is_dead(s, live, now, self.cfg.grace_s):
                state = "dead"
            else:
                state = "idle"
            age = f"{(now - s['leased_at']) / 60:.0f}m"
            dbs = ",".join(s.get("dbs", [])) or "-"
            rows.append(f"{k:<5}{s['owner'][:15]:<16}{state:<8}{age:>7}  {dbs:<28}{s['worktree']}")
        rows.append(f"{self.cfg.slots - len(reg['slots'])} of {self.cfg.slots} slots free")
        return rows

    def ls(self) -> None:
        print("\n".join(self._rows()))
        holders = self.heavy.holders()
        print(
            f"heavy: {len(holders)}/{self.cfg.heavy} in use"
            + "".join(f"\n  {h_desc(h)}" for h in holders)
        )

    def doctor(self) -> None:
        print(f"project: {self.cfg.project} (registry {self.reg.path})")
        self.ls()
        waits = self.reg.read()["heavy_waits"]
        if waits:
            secs = [w["wait_s"] for w in waits]
            print(
                f"heavy waits (last {len(secs)}): max {max(secs):.1f}s, "
                f"avg {sum(secs) / len(secs):.1f}s, latest {secs[-1]:.1f}s"
            )
        try:
            with pg(self.cfg.db_url) as c:
                n_conn = c.execute("SELECT count(*) FROM pg_stat_activity").fetchone()[0]
                max_conn = c.execute("SHOW max_connections").fetchone()[0]
                print(f"postgres: {n_conn}/{max_conn} connections")
                for sql in (  # PG17+ moved checkpoint stats to pg_stat_checkpointer
                    "SELECT num_timed + num_requested, write_time + sync_time "
                    "FROM pg_stat_checkpointer",
                    "SELECT checkpoints_timed + checkpoints_req, "
                    "checkpoint_write_time + checkpoint_sync_time FROM pg_stat_bgwriter",
                ):
                    try:
                        cp = c.execute(sql).fetchone()
                        break
                    except Exception:
                        cp = None
                if cp:
                    avg = cp[1] / cp[0] / 1000 if cp[0] else 0.0
                    print(f"postgres: avg checkpoint duration {avg:.1f}s over {cp[0]}")
                names = c.execute(
                    "SELECT datname FROM pg_database WHERE datname ~ %s ORDER BY 1",
                    (f"^{stack_db_pattern(self.cfg)}$",),
                ).fetchall()
                print("postgres: stack DBs: " + (", ".join(r[0] for r in names) or "none"))
        except Exception as e:  # noqa: BLE001
            print(f"postgres: unreachable ({e.__class__.__name__}: {e})")
        if self.cfg.redis_url:
            try:
                print(f"redis: {'ok' if redis_ping(self.cfg.redis_url) else 'no PONG'}")
            except OSError as e:
                print(f"redis: unreachable ({e})")
        t = self.reg.read()["template"]
        print(
            f"template: {self.cfg.template} rev={self.template_revision() or '-'} "
            f"(built {t.get('built_at', '-')} from {t.get('from', '-')}), "
            f"main heads={','.join(sorted(self.main_heads())) or '-'}"
        )

    # -- run

    def ensure_db(self, n: int, kind: str) -> None:
        if kind == "dev":
            name, url = db_dev(self.cfg, n), self.cfg.db_url
        else:
            name, url = db_test(self.cfg, n), self.cfg.db_test_url
        t = time.perf_counter()
        if not db_exists(url, name):
            if kind == "dev":
                with open(self.template_lock, "a") as lock:
                    fcntl.flock(lock, fcntl.LOCK_SH)
                    if not db_exists(url, self.cfg.template):
                        raise StackError(
                            f"{self.cfg.template} missing; run `{PROG} template refresh`"
                        )
                    with pg(url) as c:
                        c.execute(
                            f"CREATE DATABASE {ident(self.cfg, name)} "
                            f"TEMPLATE {ident(self.cfg, self.cfg.template)}"
                        )
            else:
                with pg(url) as c:
                    c.execute(f"CREATE DATABASE {ident(self.cfg, name)}")
            print(f"stack: created {name} in {time.perf_counter() - t:.2f}s", file=sys.stderr)
        with self.reg.locked() as reg:
            slot = reg["slots"].get(str(n))
            if slot is None:
                raise StackError(f"slot {n} is not leased (stale {SLOT_FILE}?); run `{PROG} lease`")
            if name not in slot["dbs"]:
                slot["dbs"].append(name)
            slot["last_used"] = time.time()

    def acquire_heavy(self, n: int, owner: str, cmd: list[str]) -> IO[str]:
        info = {
            "owner": owner,
            "slot": n,
            "pid": os.getpid(),
            "cmd": " ".join(cmd)[:80],
            "since": time.time(),
        }
        t0 = time.time()
        next_report = 0.0
        while True:
            f = self.heavy.try_acquire(info)
            if f is not None:
                break
            if time.time() >= next_report:
                hs = "; ".join(h_desc(h) for h in self.heavy.holders()) or "?"
                print(
                    f"stack: waiting for heavy permit ({self.cfg.heavy} in use: {hs})",
                    file=sys.stderr,
                )
                next_report = time.time() + 15
            time.sleep(0.5)
        waited = time.time() - t0
        if waited > 0.5:
            print(f"stack: got heavy permit after {waited:.1f}s", file=sys.stderr)
        with self.reg.locked() as reg:
            reg["heavy_waits"] = (
                reg["heavy_waits"]
                + [{"slot": n, "owner": owner, "wait_s": round(waited, 2), "at": time.time()}]
            )[-MAX_WAITS:]
        os.set_inheritable(f.fileno(), True)  # the permit lives until the exec'd command exits
        return f

    def run(self, dbs: list[str], ports: bool, heavy: bool, cmd: list[str]) -> None:
        if not cmd:
            raise StackError(f"nothing to run; usage: {PROG} run [opts] -- <cmd>")
        n = int(read_slot_file(self.root)["STACK_SLOT"])
        owner = self.reg.read()["slots"].get(str(n), {}).get("owner", "?")
        env = slot_env(self.cfg, n)
        if ports:
            busy = [v for k, v in env.items() if k.endswith("_PORT") and port_busy(int(v))]
            if busy:
                print(f"stack: warning: port(s) {', '.join(busy)} already in use", file=sys.stderr)
        if "dev" in dbs:
            self.warn_template_stale()
        for kind in dict.fromkeys(dbs):
            self.ensure_db(n, kind)
        if heavy:
            self.permit = self.acquire_heavy(n, owner, cmd)  # keep open: closing frees the lock
        os.environ.update(env)
        os.execvp(cmd[0], cmd)

    # -- infra

    def infra_healthy(self) -> bool:
        try:
            with pg(self.cfg.db_url) as c:
                c.execute("SELECT 1")
            return redis_ping(self.cfg.redis_url + "/0") if self.cfg.redis_url else True
        except StackError:
            raise
        except Exception:
            return False

    def _compose(self) -> list[str]:
        if not self.cfg.compose_file:
            raise StackError(
                f"no [infra] compose_file in {CONFIG_FILE}; start Postgres/Redis yourself"
            )
        cmd = ["docker", "compose", "-f", str(self.main / self.cfg.compose_file)]
        env_file = self.main / self.cfg.env_file
        if env_file.exists():
            cmd += ["--env-file", str(env_file)]
        return cmd

    def infra_ensure(self) -> None:
        if self.infra_healthy():
            print("stack: infra healthy, nothing to do")
            return
        cmd = [*self._compose(), "up", "-d", "--wait", "--no-recreate", *self.cfg.services]
        print(f"stack: infra not healthy, running in {self.main}: {shlex.join(cmd)}")
        subprocess.run(cmd, cwd=self.main, check=True)

    def infra_destructive(self, what: str) -> None:
        if os.environ.get("STACK_ROLE") != "human":
            raise StackError(
                f"`{PROG} infra {what}` is human-only; set STACK_ROLE=human (agents: ask the human)"
            )
        base = self._compose()
        if what == "down":
            subprocess.run([*base, "down"], cwd=self.main, check=True)
        else:
            subprocess.run([*base, "down", "-v"], cwd=self.main, check=True)
            with self.reg.locked() as reg:
                reg["slots"].clear()
                reg["template"] = {}
            self.infra_ensure()

    def template_refresh(self) -> None:
        if not self.cfg.template_build:
            raise StackError(f"no template.build commands in {CONFIG_FILE}")
        new = f"{self.cfg.template}_new"
        url = self.cfg.db_url
        cwd = self.root / self.cfg.template_cwd
        self.drop_db(url, new)
        with pg(url) as c:
            c.execute(f"CREATE DATABASE {ident(self.cfg, new)}")
        env = {**os.environ, self.cfg.db_env: f"{url}/{new}"}
        try:
            for step in self.cfg.template_build:
                print(f"stack: {step}  (in {cwd}, {self.cfg.db_env} -> {new})")
                subprocess.run(step, shell=True, cwd=cwd, env=env, check=True)
        except BaseException:
            self.drop_db(url, new)
            raise
        with open(self.template_lock, "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)  # no clone in flight
            self.drop_db(url, self.cfg.template)
            with pg(url) as c:
                c.execute(
                    f"ALTER DATABASE {ident(self.cfg, new)} "
                    f"RENAME TO {ident(self.cfg, self.cfg.template)}"
                )
        rev = self.template_revision()
        with self.reg.locked() as reg:
            reg["template"] = {
                "revision": rev,
                "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "from": f"{self.root} @ {git('rev-parse', '--short', 'HEAD', cwd=self.root)}",
            }
        print(f"stack: {self.cfg.template} refreshed" + (f" at revision {rev}" if rev else ""))
        heads = self.main_heads()
        if rev and heads and rev not in heads:
            print(
                f"stack: warning: built from {self.root} at {rev}, main head is "
                f"{','.join(sorted(heads))}",
                file=sys.stderr,
            )


def h_desc(h: dict[str, Any]) -> str:
    since = time.time() - float(h.get("since", time.time()))
    return f"slot {h.get('slot')} {h.get('owner')} pid {h.get('pid')} {since:.0f}s: {h.get('cmd')}"


def read_slot_file(root: Path) -> dict[str, str]:
    f = root / SLOT_FILE
    if not f.exists():
        raise StackError(f"no {SLOT_FILE} in {root}; run `{PROG} lease <owner>` first")
    return parse_env(f.read_text())


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=PROG, description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("lease").add_argument("owner")
    sub.add_parser("release").add_argument("slot", type=int, nargs="?")
    sub.add_parser("ls")
    sub.add_parser("gc")
    sub.add_parser("doctor")
    r = sub.add_parser("run")
    r.add_argument("--db", action="append", choices=["dev", "test"], default=[])
    r.add_argument("--ports", action="store_true")
    r.add_argument("--heavy", action="store_true")
    r.add_argument("command", nargs=argparse.REMAINDER)
    sub.add_parser("infra").add_argument("action", choices=["ensure", "down", "reset"])
    sub.add_parser("template").add_argument("action", choices=["refresh"])
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg, root, main_ = load_config()
        st = Stack(cfg, stack_home(), root, main_)
        match args.cmd:
            case "lease":
                st.lease(args.owner)
            case "release":
                st.release(args.slot)
            case "ls":
                st.ls()
            case "gc":
                st.gc()
            case "doctor":
                st.doctor()
            case "run":
                cmd = args.command[1:] if args.command[:1] == ["--"] else args.command
                st.run(args.db, args.ports, args.heavy, cmd)
            case "infra":
                if args.action == "ensure":
                    st.infra_ensure()
                else:
                    st.infra_destructive(args.action)
            case "template":
                st.template_refresh()
    except StackError as e:
        print(f"stack: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
