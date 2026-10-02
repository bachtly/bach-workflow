#!/usr/bin/env python3
"""Interim-snapshot helper: print what changed since the last snapshot, compactly.

Usage:
  digest.py <run_dir>          print progress + notes/judge passes not yet digested
  digest.py <run_dir> --all    same, but include every note (rebuild interim from scratch)
  digest.py <run_dir> --mark   commit the items the last print showed as digested

The main loop runs this on each 5-minute tick, folds the output into
snapshots/interim.md, publishes, then runs --mark. Only the items that were
printed get marked, so notes landing mid-tick are picked up next time.
State: <run_dir>/snapshots/state.json.
"""
import glob
import json
import os
import sys
import time

MAX_CLAIMS = 8   # per note, keeps a tick's input small


def read_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    run = sys.argv[1].rstrip("/")
    flags = set(sys.argv[2:])
    snap = os.path.join(run, "snapshots")
    os.makedirs(snap, exist_ok=True)
    state_path = os.path.join(snap, "state.json")
    state = read_json(state_path, {}) or {}
    done = set(state.get("digested", []))

    if "--mark" in flags:
        done |= set(state.get("pending", []))
        state.update(digested=sorted(done), pending=[], ticks=state.get("ticks", 0) + 1,
                     last=time.strftime("%H:%M"))
        with open(state_path, "w") as f:
            json.dump(state, f, indent=1)
        print(f"marked; tick {state['ticks']}, {len(done)} items digested")
        return

    args = read_json(os.path.join(run, "args.json"), {}) or {}
    cap = (args.get("budget") or {}).get("cap", "?")
    searches = glob.glob(os.path.join(run, "search", "*.json"))
    fetches = [read_json(p, {}) or {} for p in glob.glob(os.path.join(run, "fetch", "*.json"))]
    note_paths = sorted(p for p in glob.glob(os.path.join(run, "notes", "*.json")) if not p.endswith(".struct.json"))
    judge_paths = sorted(glob.glob(os.path.join(run, "judge", "*.json")), key=os.path.getmtime)
    rnd = max((int(os.path.basename(p)[1:].split("q")[0]) for p in searches), default=0)

    print(f"# PROGRESS {time.strftime('%H:%M')} · tick {state.get('ticks', 0) + 1} · last snapshot {state.get('last', 'never')}")
    print(f"round {rnd} · searches {len(searches)} · fetched {len(fetches)}/{cap} "
          f"(failed {sum(f.get('status') == 'failed' for f in fetches)}) · notes {len(note_paths)} · "
          f"judge passes {', '.join(os.path.basename(p)[:-5] for p in judge_paths) or 'none'}")
    if os.path.exists(os.path.join(run, "report.md")) and os.path.getmtime(os.path.join(run, "report.md")) > os.path.getmtime(state_path if os.path.exists(state_path) else run):
        print("NOTE: report.md exists and is newer than the last snapshot; the run may be finished")

    pending = []
    for p in judge_paths:
        key = "judge/" + os.path.basename(p)
        if key in done and "--all" not in flags:
            continue
        j = read_json(p, {}) or {}
        pending.append(key)
        print(f"\n## JUDGE {os.path.basename(p)[:-5]} · new_terms {j.get('new_terms')} · new_facts {j.get('new_facts')} · "
              f"stop {(j.get('stop') or {}).get('stop')} ({(j.get('stop') or {}).get('reason', '')})")
        top = [t for t in j.get("terms", []) or [] if t.get("status") in ("queued", "kept", "expanded")]
        top.sort(key=lambda t: -(t.get("score") or 0))
        print("top terms: " + "; ".join(f"{t['term']} ({t.get('score')}, {len(t.get('sources') or [])} src)" for t in top[:15]))
        for c in j.get("contradictions", []) or []:
            print(f"contradiction: {c.get('topic')} :: " + " | ".join(c.get("sides", [])))
        print("next queue: " + "; ".join(q.get("query", "") for q in j.get("next_queue", []) or []))

    new_notes = [p for p in note_paths if "notes/" + os.path.basename(p) not in done or "--all" in flags]
    print(f"\n## NEW NOTES ({len(new_notes)})")
    for p in new_notes:
        n = read_json(p)
        if not n:
            continue  # being written right now; next tick
        pending.append("notes/" + os.path.basename(p))
        flags_s = ",".join(n.get("quality_flags") or []) or "-"
        print(f"\n[{n.get('sid')}] {n.get('title', '')[:90]} · {n.get('source_type', '')} · {n.get('published') or 'undated'} · flags {flags_s}")
        print(f"  {n.get('url', '')}")
        for c in (n.get("claims") or [])[:MAX_CLAIMS]:
            nums = f" [{'; '.join(c.get('numbers') or [])}]" if c.get("numbers") else ""
            print(f"  - {c.get('claim', '')}{nums}")
        extra = len(n.get("claims") or []) - MAX_CLAIMS
        if extra > 0:
            print(f"  (+{extra} more claims in notes/{os.path.basename(p)})")
        for r in (n.get("analysis_rows") or [])[:4]:
            print("  row: " + " · ".join(f"{k}={str(v)[:60]}" for k, v in r.items()))

    state["pending"] = pending
    with open(state_path, "w") as f:
        json.dump(state, f, indent=1)


if __name__ == "__main__":
    main()
