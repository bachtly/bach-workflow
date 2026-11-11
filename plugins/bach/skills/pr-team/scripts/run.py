#!/usr/bin/env python3
"""Run state for a pr-team run, so routine events never need the lead.

Teammates record events here instead of messaging the lead; the lead reads the
result only when it is woken for something that needs judgment. State lives in
RUN/status.json (RUN = the folder of plan.md), next to plan.md, which keeps the
plan, `## Decisions` and `## Lessons`. A resumed lead recovers from both.

  run.py pr <task> <n> --builder B [--step S]... [size hints]   a builder opened PR #n
  run.py scope <task> [--base origin/main]                       check the worktree's changed files
  run.py lesson "<rule> — PR #n" --by <who>                      queue a lesson for the lead
  run.py lessons [--keep]                                        print queued lessons (and clear them)
  run.py decision "<question> → <answer>"                        append to plan.md ## Decisions
  run.py todo add <pr> "<when> · <where> · <action> · <why>"     add a human step
  run.py todo done <id>...                                       tick human steps
  run.py note <pr> "<text>"                                      log an event (fix round started/ended)
  run.py set <task> key=value...                                 set task fields (size, reviewer, ...)
  run.py waiting                                                 builders waiting for a claimable task
  run.py status                                                  the human TODO list and the PR table

Size hints for `pr` (on-demand review): --lines N --ui none|page|interactive
--risk yes|no (contract, schema, migration or security) --verified yes|no|n/a
--tests all|skipped. `pr` prints `size: big|small (<why>)` and the `next:` step.
All commands take --plan <path> (default: <git root>/.claude/pr-team/plan.md).
Exit 0, 1 when `scope` finds files out of scope, 2 on error.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import claim  # noqa: E402

WHEN = ["before merge", "review", "after merge", "to try it"]
BIG_LINES = 300
MAX_FILES = 10


def run(*args, cwd=None):
    out = subprocess.run(args, capture_output=True, text=True, cwd=cwd, timeout=60)
    if out.returncode != 0:
        raise RuntimeError(f"{' '.join(args[:3])}: {out.stderr.strip()}")
    return out.stdout.strip()


def plan_text(plan):
    with open(plan, encoding="utf-8") as f:
        return f.read()


def review_mode(text):
    m = re.search(r"^\s*Review(?: mode)?:\s*(on-demand|standing)", text, re.MULTILINE | re.IGNORECASE)
    return m.group(1).lower() if m else "on-demand"


@contextmanager
def state(plan, write=True):
    """Lock RUN/status.json, yield its dict, save it on exit."""
    path = os.path.join(os.path.dirname(plan), "status.json")
    with claim.file_lock(path + ".lock"):
        try:
            with open(path) as f:
                data = json.load(f)
        except FileNotFoundError:
            data = {}
        for k, v in (("tasks", {}), ("todo", []), ("notes", [])):
            data.setdefault(k, v)
        yield data
        if write:
            tmp = path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(data, f, indent=1)
            os.replace(tmp, path)


def add_todo(data, pr, line):
    parts = [p.strip() for p in line.split("·")]
    when = parts[0].lower() if parts and parts[0].lower() in WHEN else "before merge"
    text = " · ".join(parts[1:] if parts[0].lower() in WHEN else parts)
    if any(t["pr"] == pr and t["text"] == text for t in data["todo"]):
        return  # a repeat of the same step is a no-op
    data["todo"].append({"id": max([t["id"] for t in data["todo"]] + [0]) + 1,
                         "pr": pr, "when": when, "text": text, "done": False})


def size_of(a):
    """(big?, reasons) from a builder's size hints. Mirrors the SKILL's Big rule."""
    why = []
    if a.ui in ("page", "interactive"):
        why.append(f"UI: {a.ui}")
    if a.risk == "yes":
        why.append("contract/migration/security")
    if a.lines is not None and a.lines > BIG_LINES:
        why.append(f"{a.lines} lines")
    if a.verified == "no":
        why.append("not verified in a browser")
    if a.tests == "skipped":
        why.append("tests skipped")
    return bool(why), why


def cmd_pr(a, plan):
    big, why = size_of(a)
    mode = review_mode(plan_text(plan))
    with state(plan) as data:
        t = data["tasks"].setdefault(a.task, {})
        t.update({"pr": a.n, "builder": a.builder, "size": "big" if big else "small", "at": time.time()})
        if a.risk == "yes":
            t["risk"] = True
        for s in a.step or []:
            if s.strip().lower().rstrip(".") not in ("none", "human steps: none"):
                add_todo(data, a.n, s)
    reason = ", ".join(why) or "no UI, no contract/security, small diff"
    print(f"size: {'big' if big else 'small'} ({reason})")
    if mode == "standing":
        print(f"next: SendMessage your reviewer `PR #{a.n} ready`, then claim your next task")
    elif big:
        print(f"next: SendMessage the lead `{a.task} → PR #{a.n} big: {reason}` (it spawns a reviewer), "
              f"then claim your next task")
    else:
        print("next: nothing to send; claim your next task")


def changed_files(base, cwd):
    tracked = run("git", "diff", "--name-only", base, cwd=cwd).splitlines()
    new = run("git", "ls-files", "--others", "--exclude-standard", cwd=cwd).splitlines()
    return sorted(set(f for f in tracked + new if f))


def cmd_scope(a, plan):
    _, tasks, _ = claim.parse_plan(plan_text(plan))
    task = next((t for t in tasks if t["id"] == a.task), None)
    if not task:
        raise RuntimeError(f"no task {a.task} in {plan}")
    folder = task["folder"].strip().rstrip("/")
    named = [f.strip() for f in re.split(r"[,\s]+", " ".join([task.get("files", ""), task.get("contract", "")]))
             if f.strip() and f.strip() not in {"-", "—"}]
    files = changed_files(a.base, os.getcwd())

    def ok(path):
        return (folder in ("", ".") or path == folder or path.startswith(folder + "/")
                or any(path == n or path.endswith("/" + n) or n.endswith("/" + path) for n in named))

    out = [f for f in files if not ok(f)]
    if out:
        print(f"out of scope ({folder}/ plus {', '.join(named) or 'no named files'}): {', '.join(out)}")
        print("next: revert them, or SendMessage the lead one line: the files and why you need them")
        return 1
    print(f"scope ok: {len(files)} files in {folder}/" + (f" (over {MAX_FILES}: consider asking the lead to split)"
                                                         if len(files) > MAX_FILES else ""))
    return 0


MAX_LESSONS = 10


def section_span(lines, heading):
    """(start, end) line indexes of the body of `## <heading>`, or None."""
    for i, l in enumerate(lines):
        if l.rstrip() == f"## {heading}":
            j = i + 1
            while j < len(lines) and not lines[j].startswith("## "):
                j += 1
            return i + 1, j
    return None


def append_to_section(plan, heading, line):
    """Append `line` under `## <heading>` in plan.md (creating the section). False if already there."""
    lines = plan_text(plan).splitlines()
    if line in lines:
        return False
    span = section_span(lines, heading)
    if span is None:
        lines += ["", f"## {heading}", line]
    else:
        start, end = span
        while end > start and not lines[end - 1].strip():
            end -= 1  # insert after the last non-blank line of the section
        lines.insert(end, line)
        if end + 1 < len(lines) and lines[end + 1].startswith("## "):
            lines.insert(end + 1, "")
    with open(plan, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip("\n") + "\n")
    return True


def section_lines(plan, heading):
    lines = plan_text(plan).splitlines()
    span = section_span(lines, heading)
    return [l for l in lines[span[0]:span[1]] if l.startswith("- ")] if span else []


def cmd_lesson(a, plan):
    """Lessons go straight into plan.md ## Lessons; the lead only merges them when there are too many."""
    text = a.text if a.text.startswith("- ") else f"- {a.text}"
    if not text.rstrip().endswith(")") and a.by:
        text = f"{text} ({a.by})"
    with state(plan):  # the lock serialises plan.md writers too
        added = append_to_section(plan, "Lessons", text)
        n = len(section_lines(plan, "Lessons"))
    print("lesson added to plan.md" if added else "lesson already there")
    if n > MAX_LESSONS:
        print(f"next: SendMessage the lead `lessons: {n} lines, over {MAX_LESSONS}: merge them`")


def cmd_lessons(a, plan):
    print("\n".join(section_lines(plan, "Lessons")) or "no lessons")


def cmd_decision(a, plan):
    with state(plan):
        added = append_to_section(plan, "Decisions", f"- {a.text}")
    print("decision recorded in plan.md" if added else "decision already recorded")


def cmd_todo(a, plan):
    with state(plan) as data:
        if a.action == "add":
            add_todo(data, int(a.args[0]), " ".join(a.args[1:]))
        else:
            ids = {int(i) for i in a.args}
            for t in data["todo"]:
                if t["id"] in ids:
                    t["done"] = True
    print("ok")


def cmd_note(a, plan):
    with state(plan) as data:
        data["notes"].append({"pr": a.pr, "text": a.text, "at": time.time()})
    print("ok")


def cmd_set(a, plan):
    with state(plan) as data:
        t = data["tasks"].setdefault(a.task, {})
        for kv in a.pairs:
            k, _, v = kv.partition("=")
            t[k] = int(v) if v.isdigit() else v
    print("ok")


def claims_dir(plan):
    plan_id, _, _ = claim.parse_plan(plan_text(plan))
    return os.path.join(os.path.dirname(plan), "claims", plan_id or "")


def cmd_waiting(a, plan):
    print("\n".join(claim.waiting_builders(claims_dir(plan))) or "none")


def pr_info(n):
    return json.loads(run("gh", "pr", "view", str(n), "--json", "number,title,url,state,reviewDecision,labels"))


def status_icon(p):
    labels = {l["name"] for l in p.get("labels", [])}
    if p["state"] == "MERGED":
        return "✅ Merged"
    if p["state"] == "CLOSED":
        return "⚫ Closed"
    if "pre-review:running" in labels:
        return "🔵 Pre-review"
    if p.get("reviewDecision") == "CHANGES_REQUESTED" or "pre-review:blocked" in labels:
        return "🔴 Changes requested"
    return "🟡 Ready for review"


def cmd_status(a, plan):
    with state(plan, write=False) as data:
        tasks, todo = data["tasks"], data["todo"]
    with_pr = {t: v for t, v in tasks.items() if v.get("pr")}
    with ThreadPoolExecutor(max_workers=8) as pool:
        infos = dict(zip(with_pr, pool.map(lambda t: pr_info(with_pr[t]["pr"]), with_pr)))
    state_of = {v["pr"]: infos[t]["state"] for t, v in with_pr.items()}
    print("## Your TODO")
    groups = {w: [] for w in WHEN}
    for t in todo:
        if t["done"] or state_of.get(t["pr"]) == "CLOSED":
            continue
        if t["when"] == "before merge" and state_of.get(t["pr"]) == "MERGED":
            continue  # merged without it: the human did it or chose not to
        groups[t["when"]].append(f"- [ ] #{t['pr']} · {t['text']}  `(todo {t['id']})`")
    for task, v in with_pr.items():
        p = infos[task]
        icon = status_icon(p)
        if icon.startswith("🟡") or icon.startswith("🔴"):
            gate = " (wait for label `pre-review:ok`)" if v.get("reviewer") and "pre-review:ok" not in \
                {l["name"] for l in p.get("labels", [])} else ""
            groups["review"].append(f"- [ ] Review #{p['number']} {p['title']}{gate}")
    if not any(groups.values()):
        print("Nothing for you right now.")
    for w in WHEN:
        if groups[w]:
            print(f"**{w.capitalize()}**")
            print("\n".join(groups[w]))
    print("\n## PRs\n| PR | Title | Task | Owner | Status |\n|---|---|---|---|---|")
    order = {"OPEN": 0, "MERGED": 1, "CLOSED": 2}
    for task, v in sorted(with_pr.items(), key=lambda kv: (order[infos[kv[0]]["state"]], kv[1]["pr"])):
        p = infos[task]
        print(f"| [#{p['number']}]({p['url']}) | {p['title']} | {task} | {v.get('builder', '?')} | {status_icon(p)} |")
    open_n = sum(1 for p in infos.values() if p["state"] == "OPEN")
    budget = claim.review_budget(plan_text(plan))
    print(f"\nOpen PRs: {open_n}" + (f" / review budget {budget}" if budget else ""))
    waiting = claim.waiting_builders(claims_dir(plan))
    if waiting:
        print(f"Builders waiting for a task: {', '.join(waiting)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pr")
    p.add_argument("task")
    p.add_argument("n", type=int)
    p.add_argument("--builder", required=True)
    p.add_argument("--step", action="append")
    p.add_argument("--lines", type=int)
    p.add_argument("--ui", choices=["none", "page", "interactive"], default="none")
    p.add_argument("--risk", choices=["yes", "no"], default="no")
    p.add_argument("--verified", choices=["yes", "no", "n/a"], default="n/a")
    p.add_argument("--tests", choices=["all", "skipped"], default="all")
    p = sub.add_parser("scope")
    p.add_argument("task")
    p.add_argument("--base", default="origin/main")
    p = sub.add_parser("lesson")
    p.add_argument("text")
    p.add_argument("--by", required=True)
    sub.add_parser("lessons")
    p = sub.add_parser("decision")
    p.add_argument("text")
    p = sub.add_parser("todo")
    p.add_argument("action", choices=["add", "done"])
    p.add_argument("args", nargs="+")
    p = sub.add_parser("note")
    p.add_argument("pr", type=int)
    p.add_argument("text")
    p = sub.add_parser("set")
    p.add_argument("task")
    p.add_argument("pairs", nargs="+")
    sub.add_parser("waiting")
    sub.add_parser("status")
    a = ap.parse_args()
    try:
        plan = a.plan or claim.default_plan()
        return globals()[f"cmd_{a.cmd}"](a, plan) or 0
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as e:
        print(f"run.py: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
