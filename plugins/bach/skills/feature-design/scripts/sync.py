#!/usr/bin/env python3
"""Shared state for a feature-design run: stage status, cross-PR change events, ADR numbers.

One JSON file (SYNC) in the main checkout, outside the design branches, written under a file lock
so the lead and all teammates can use it at the same time.

  sync.py SYNC init --run RUN --slug SLUG [--adr-dir DIR] [--adr-next N]
  sync.py SYNC                                   stages, open changes, what to do next
  sync.py SYNC stage NAME STATUS [--owner X] [--pr N] [--reason TEXT]
  sync.py SYNC emit --from STAGE --kind KIND --subject S --change C --reason R [--affects a,b]
  sync.py SYNC ack ID --stage STAGE --status fixed|n/a|objects --note TEXT
  sync.py SYNC resolve ID --decision TEXT        after the user decides an objection
  sync.py SYNC pending --stage STAGE             what blocks this stage's PR; prints CLEAR if nothing
  sync.py SYNC adr --stage STAGE --title TITLE   reserve the next ADR number, prints its path

STATUS: pending | drafting | review | approved | merged | skipped
KIND:   rename | add | remove | change | decision
"""
import argparse
import datetime
import json
import os
import re
import sys
import time

PHASE1 = ["brief", "research", "requirements"]
PHASE2 = ["data-model", "api", "ui", "backend"]
WRAP = ["design"]
STAGES = PHASE1 + PHASE2 + WRAP
STATUSES = ["pending", "drafting", "review", "approved", "merged", "skipped"]
KINDS = ["rename", "add", "remove", "change", "decision"]
DONE = ("merged", "skipped")


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
        die(f"{path} not found; run: sync.py {path} init ...")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(path, state):
    state["updated"] = now()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, path)


def active_phase2(state):
    return [s for s in PHASE2 if state["stages"][s]["status"] != "skipped"]


def open_items(change):
    return {s: a for s, a in change["acks"].items() if a["status"] in ("pending", "objects")}


def show(state):
    print(f"run: {state['run']}")
    print(f"{'stage':<13} {'status':<9} {'owner':<16} pr")
    for s in STAGES:
        st = state["stages"][s]
        extra = f"  ({st.get('reason')})" if st["status"] == "skipped" else ""
        print(f"{s:<13} {st['status']:<9} {st.get('owner', '-'):<16} {st.get('pr', '-')}{extra}")
    opened = [c for c in state["changes"] if open_items(c)]
    print(f"open changes: {len(opened)}")
    for c in opened:
        waits = ", ".join(f"{s}:{a['status']}" for s, a in open_items(c).items())
        print(f"  {c['id']} [{c['from']} {c['kind']}] {c['subject']}: {c['change']}  waiting {waits}")
    st = {s: state["stages"][s]["status"] for s in STAGES}
    todo1 = [s for s in PHASE1 if st[s] not in ("approved",) + DONE]
    if todo1:
        nxt = f"phase 1: {todo1[0]}"
    elif any(st[s] == "approved" for s in PHASE1):
        nxt = "phase 1 approved: open or merge the foundation PR, then mark phase-1 stages merged"
    elif any(st[s] not in DONE for s in PHASE2):
        nxt = "phase 2 running: " + ", ".join(f"{s}={st[s]}" for s in PHASE2 if st[s] not in DONE)
    elif st["design"] not in DONE:
        nxt = "wrap-up: design.md + roadmap.md"
    else:
        nxt = "done: hand off roadmap.md to pr-team"
    print(f"NEXT: {nxt}")


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # change texts may hold arrows etc.; Windows consoles default to cp1252
    if len(sys.argv) < 2:
        die(__doc__)
    path = os.path.abspath(sys.argv[1])
    p = argparse.ArgumentParser(prog="sync.py SYNC")
    sub = p.add_subparsers(dest="cmd")
    i = sub.add_parser("init")
    i.add_argument("--run", required=True)
    i.add_argument("--slug", required=True)
    i.add_argument("--adr-dir")
    i.add_argument("--adr-next", type=int, default=1)
    g = sub.add_parser("stage")
    g.add_argument("name", choices=STAGES)
    g.add_argument("status", choices=STATUSES)
    g.add_argument("--owner")
    g.add_argument("--pr")
    g.add_argument("--reason")
    e = sub.add_parser("emit")
    e.add_argument("--from", dest="frm", required=True, choices=STAGES)
    e.add_argument("--kind", required=True, choices=KINDS)
    e.add_argument("--subject", required=True)
    e.add_argument("--change", required=True)
    e.add_argument("--reason", required=True)
    e.add_argument("--affects")
    a = sub.add_parser("ack")
    a.add_argument("id")
    a.add_argument("--stage", required=True, choices=STAGES)
    a.add_argument("--status", required=True, choices=["fixed", "n/a", "objects"])
    a.add_argument("--note", required=True)
    r = sub.add_parser("resolve")
    r.add_argument("id")
    r.add_argument("--decision", required=True)
    q = sub.add_parser("pending")
    q.add_argument("--stage", required=True, choices=STAGES)
    d = sub.add_parser("adr")
    d.add_argument("--stage", required=True, choices=STAGES)
    d.add_argument("--title", required=True)
    args = p.parse_args(sys.argv[2:])

    if args.cmd == "init":
        if os.path.exists(path):
            die("state already exists")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        state = {"created": now(), "run": args.run, "slug": args.slug,
                 "adr_dir": args.adr_dir or f"{args.run}/adr", "next_adr": args.adr_next,
                 "stages": {s: {"status": "pending"} for s in STAGES}, "changes": []}
        with Lock(path):
            save(path, state)
        return show(state)

    if args.cmd is None:
        return show(load(path))

    with Lock(path):
        state = load(path)
        if args.cmd == "stage":
            if args.status == "skipped" and args.name not in PHASE2:
                die(f"{args.name} cannot be skipped")
            st = state["stages"][args.name]
            st["status"] = args.status
            for k in ("owner", "pr", "reason"):
                if getattr(args, k):
                    st[k] = getattr(args, k)
            if args.owner and args.name in PHASE2:
                # pr-watcher finds a PR's owner in CLAIMS/<branch> ({"builder", "at"}, pr-team's claim format)
                claims = os.path.join(os.path.dirname(path), "claims")
                os.makedirs(claims, exist_ok=True)
                with open(os.path.join(claims, f"design-{state['slug']}-{args.name}"), "w", encoding="utf-8") as f:
                    json.dump({"builder": args.owner, "at": now()}, f)
            save(path, state)
            return show(state)

        if args.cmd == "emit":
            affects = [s.strip() for s in args.affects.split(",")] if args.affects else active_phase2(state)
            affects = [s for s in affects if s != args.frm and state["stages"][s]["status"] not in DONE]
            bad = [s for s in affects if s not in STAGES]
            if bad:
                die(f"unknown stages: {bad}")
            cid = f"CHG-{len(state['changes']) + 1:03d}"
            state["changes"].append({"id": cid, "from": args.frm, "kind": args.kind, "subject": args.subject,
                                     "change": args.change, "reason": args.reason, "created": now(),
                                     "acks": {s: {"status": "pending"} for s in affects}})
            save(path, state)
            print(f"{cid} → notify: {', '.join(affects) or 'nobody (no open phase-2 stage)'}")
            return

        found = [c for c in state["changes"] if c["id"] == getattr(args, "id", None)]
        if args.cmd in ("ack", "resolve") and not found:
            die(f"unknown change {args.id}")

        if args.cmd == "ack":
            c = found[0]
            c["acks"][args.stage] = {"status": args.status, "note": args.note, "at": now()}
            save(path, state)
            print(f"{c['id']} {args.stage}: {args.status}")
            return

        if args.cmd == "resolve":
            c = found[0]
            c.setdefault("decisions", []).append({"decision": args.decision, "at": now()})
            for s, ack in c["acks"].items():
                if ack["status"] == "objects":
                    c["acks"][s] = {"status": "pending", "note": f"decided: {args.decision}"}
            save(path, state)
            print(f"{c['id']} resolved; objecting stages must re-ack")
            return

        if args.cmd == "pending":
            todo = [(c, a) for c in state["changes"] for s, a in c["acks"].items()
                    if s == args.stage and a["status"] == "pending"]
            blocked = [(c, s, a) for c in state["changes"] if c["from"] == args.stage
                       for s, a in c["acks"].items() if a["status"] in ("pending", "objects")]
            for c, a in todo:
                print(f"ACK {c['id']} [{c['from']} {c['kind']}] {c['subject']}: {c['change']} ({c['reason']})"
                      + (f" · {a['note']}" if a.get("note") else ""))
            for c, s, a in blocked:
                print(f"WAIT {c['id']} {s}: {a['status']}" + (f" · {a['note']}" if a.get("note") else ""))
            if not todo and not blocked:
                print("CLEAR")
            return

        if args.cmd == "adr":
            n = state["next_adr"]
            state["next_adr"] = n + 1
            slug = re.sub(r"[^a-z0-9]+", "-", args.title.lower()).strip("-")[:60]
            save(path, state)
            print(f"{state['adr_dir']}/{n:04d}-{slug}.md")
            return


if __name__ == "__main__":
    main()
