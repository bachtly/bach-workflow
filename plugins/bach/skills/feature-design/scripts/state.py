#!/usr/bin/env python3
"""State of a feature-design run: stage status, approvals and ADR numbers.

One JSON file (STATE) under <repo>/.claude/feature-design/<slug>/, written under a file lock.

  state.py STATE init --run RUN --slug SLUG [--adr-dir DIR] [--adr-next N]
  state.py STATE                        stages, focus, what to do next
  state.py STATE stage NAME STATUS [--reason TEXT]    STATUS: pending | drafting | review | skipped
  state.py STATE approve NAME           lock a stage: record the hash of its doc
  state.py STATE adr --title TITLE      reserve the next ADR number, print its path

Focus = the first stage that is neither approved nor skipped. An approved doc that changed since its
approval shows as `edited`; approved stages after it show as `recheck` until they are re-approved.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import sys
import time

STAGES = [("brief", "00-brief.md"), ("research", "01-research.md"), ("requirements", "02-requirements.md"),
          ("data-model", "03-data-model.md"), ("api", "04-api.md"), ("ui", "05-ui.md"),
          ("backend", "06-backend.md"), ("design", "design.md")]
IDS = [s for s, _ in STAGES]
DOC = dict(STAGES)
UNSKIPPABLE = {"brief", "requirements", "design"}


def now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def die(msg, code=2):
    print(f"ERROR: {msg}")
    sys.exit(code)


class Lock:
    def __init__(self, path):
        self.path = path + ".lock"

    def __enter__(self):
        start = time.time()
        while True:
            try:
                os.close(os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                return self
            except FileExistsError:
                if time.time() - os.path.getmtime(self.path) > 30:  # holder crashed; edits take ms
                    os.remove(self.path)
                elif time.time() - start > 15:
                    die(f"lock busy: {self.path}")
                time.sleep(0.1)

    def __exit__(self, *exc):
        os.remove(self.path)


def load(path):
    if not os.path.exists(path):
        die(f"{path} not found; run: state.py {path} init ...")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(path, state):
    state["updated"] = now()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, path)


def sha(path):
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:16]


def doc_path(state, stage):
    return os.path.join(state["root"], state["run"], DOC[stage])


def focus(state):
    for s in IDS:
        if state["stages"][s]["status"] not in ("approved", "skipped"):
            return s
    return None


def edited(state, stage):
    st = state["stages"][stage]
    return st["status"] == "approved" and sha(doc_path(state, stage)) != st.get("hash")


def recheck(state, stage):
    """Approved, and an approved doc before it was re-approved later or is edited now."""
    st = state["stages"][stage]
    if st["status"] != "approved" or edited(state, stage):
        return False
    for s in IDS[:IDS.index(stage)]:
        up = state["stages"][s]
        if edited(state, s) or (up["status"] == "approved" and up.get("approved", "") > st.get("approved", "")):
            return True
    return False


def show(state):
    f = focus(state)
    print(f"run: {state['run']}   focus: {f or '-'}")
    for s in IDS:
        st = state["stages"][s]
        status = "edited" if edited(state, s) else "recheck" if recheck(state, s) else st["status"]
        extra = f"  ({st.get('reason')})" if st["status"] == "skipped" else ""
        print(f"{s:<13} {status}{extra}")
    redo = [s for s in IDS if edited(state, s) or recheck(state, s)]
    if redo:
        print(f"NEXT: re-review and re-approve, in order: {', '.join(redo)}")
    elif f:
        print(f"NEXT: focus {f}")
    else:
        print("NEXT: done. Open the design PR, then hand off roadmap.md to pr-team")


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows consoles default to cp1252
    if len(sys.argv) < 2:
        die(__doc__)
    path = os.path.abspath(sys.argv[1])
    p = argparse.ArgumentParser(prog="state.py STATE")
    sub = p.add_subparsers(dest="cmd")
    i = sub.add_parser("init")
    i.add_argument("--run", required=True)
    i.add_argument("--slug", required=True)
    i.add_argument("--adr-dir")
    i.add_argument("--adr-next", type=int, default=1)
    g = sub.add_parser("stage")
    g.add_argument("name", choices=IDS)
    g.add_argument("status", choices=["pending", "drafting", "review", "skipped"])
    g.add_argument("--reason")
    a = sub.add_parser("approve")
    a.add_argument("name", choices=IDS)
    d = sub.add_parser("adr")
    d.add_argument("--title", required=True)
    args = p.parse_args(sys.argv[2:])

    if args.cmd == "init":
        if os.path.exists(path):
            die("state already exists")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        state = {"created": now(), "root": os.getcwd(), "run": args.run, "slug": args.slug,
                 "adr_dir": args.adr_dir or f"{args.run}/adr", "next_adr": args.adr_next,
                 "stages": {s: {"status": "pending"} for s in IDS}}
        with Lock(path):
            save(path, state)
        return show(state)

    if args.cmd is None:
        return show(load(path))

    with Lock(path):
        state = load(path)
        if args.cmd == "stage":
            if args.status == "skipped" and args.name in UNSKIPPABLE:
                die(f"{args.name} cannot be skipped")
            st = state["stages"][args.name]
            st["status"] = args.status
            if args.reason:
                st["reason"] = args.reason
        elif args.cmd == "approve":
            h = sha(doc_path(state, args.name))
            if h is None:
                die(f"missing doc: {doc_path(state, args.name)}")
            if focus(state) != args.name and not (edited(state, args.name) or recheck(state, args.name)):
                die(f"{args.name} is not the focus ({focus(state)})")
            stamp = datetime.datetime.now().isoformat(timespec="microseconds")  # ordering for recheck()
            state["stages"][args.name].update(status="approved", hash=h, approved=stamp)
        elif args.cmd == "adr":
            n = state["next_adr"]
            state["next_adr"] = n + 1
            slug = re.sub(r"[^a-z0-9]+", "-", args.title.lower()).strip("-")
            if len(slug) > 60:  # cut at a word boundary, never mid-word
                slug = slug[:61].rsplit("-", 1)[0]
            save(path, state)
            print(f"{state['adr_dir']}/{n:04d}-{slug}.md")
            return
        save(path, state)
    show(state)


if __name__ == "__main__":
    main()
