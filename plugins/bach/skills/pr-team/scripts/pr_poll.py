#!/usr/bin/env python3
"""Poll open PRs for new comments, reviews, reactions and state changes.

GitHub sends no webhook for reactions, so the pr-watcher polls. This script does
the mechanical part: one GraphQL query per PR, a diff against a state file, and
one JSON line per new event on stdout. The watcher only reasons about events.

  pr_poll.py --state .claude/pr-watch/state.json                  one pass
  pr_poll.py --state ... --wait 540 --interval 75                 block until events or timeout
  pr_poll.py --state ... --prs 12,14                              only these PRs
  pr_poll.py --state ... --bump-round <thread_id>                 count a fix round (survives restarts)

First pass on an empty state records a baseline and prints nothing (use
--emit-existing to print it). Exit 0 with events, 1 on timeout with none, 2 on error.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time

QUERY = """
query($o:String!,$r:String!,$n:Int!){ repository(owner:$o,name:$r){ pullRequest(number:$n){
  number title url state isDraft reviewDecision headRefName author{login}
  reactionGroups{ content reactors{ totalCount } }
  reviews(last:30){ nodes{ id state body submittedAt authorAssociation author{login __typename} } }
  comments(last:50){ nodes{ databaseId body createdAt authorAssociation author{login __typename}
    reactionGroups{ content reactors{ totalCount } } } }
  reviewThreads(first:100){ nodes{ id isResolved isOutdated path line
    comments(first:30){ nodes{ databaseId body createdAt authorAssociation author{login __typename}
      reactionGroups{ content reactors{ totalCount } } } } } }
}}}"""

TRUSTED = {"OWNER", "MEMBER", "COLLABORATOR"}


def gh(*args):
    out = subprocess.run(["gh", *args], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])}: {out.stderr.strip()}")
    return out.stdout


def repo_slug(repo):
    if repo:
        return repo.split("/", 1)
    r = json.loads(gh("repo", "view", "--json", "owner,name"))
    return r["owner"]["login"], r["name"]


def open_prs(author):
    rows = json.loads(gh("pr", "list", "--state", "open", "--author", author,
                         "--json", "number", "--limit", "100"))
    return [r["number"] for r in rows]


def fetch(owner, name, n):
    data = json.loads(gh("api", "graphql", "-F", f"o={owner}", "-F", f"r={name}",
                         "-F", f"n={n}", "-f", f"query={QUERY}"))
    return data["data"]["repository"]["pullRequest"]


def reactions(groups):
    return {g["content"]: g["reactors"]["totalCount"] for g in groups or [] if g["reactors"]["totalCount"]}


def who(node):
    a = node.get("author") or {}
    login = a.get("login", "ghost")
    bot = a.get("__typename") == "Bot" or login.endswith("[bot]")
    return login, bot, bot or node.get("authorAssociation") in TRUSTED


def snapshot(pr):
    """Flatten a PR into {key: (fingerprint, event)} so diffs are trivial."""
    items = {}
    base = {"pr": pr["number"], "url": pr["url"], "branch": pr["headRefName"]}
    items[f"pr:{pr['number']}:state"] = (
        f"{pr['state']}|{pr['reviewDecision']}|{pr['isDraft']}",
        {**base, "kind": "pr_state", "state": pr["state"],
         "review_decision": pr["reviewDecision"], "draft": pr["isDraft"]})
    items[f"pr:{pr['number']}:reactions"] = (
        json.dumps(reactions(pr["reactionGroups"]), sort_keys=True),
        {**base, "kind": "reaction", "on": "pr", "reactions": reactions(pr["reactionGroups"])})

    for r in pr["reviews"]["nodes"]:
        login, bot, trusted = who(r)
        items[f"review:{r['id']}"] = (r["state"], {
            **base, "kind": "review", "id": r["id"], "state": r["state"], "author": login,
            "bot": bot, "trusted": trusted, "body": r["body"][:2000]})

    def comment(c, extra):
        login, bot, trusted = who(c)
        cid = c["databaseId"]
        items[f"comment:{cid}"] = ("1", {
            **base, **extra, "kind": "comment", "id": cid, "author": login, "bot": bot,
            "trusted": trusted, "body": c["body"][:2000]})
        items[f"comment:{cid}:reactions"] = (
            json.dumps(reactions(c["reactionGroups"]), sort_keys=True),
            {**base, **extra, "kind": "reaction", "on": "comment", "id": cid,
             "reactions": reactions(c["reactionGroups"])})

    for c in pr["comments"]["nodes"]:
        comment(c, {"where": "conversation"})
    for t in pr["reviewThreads"]["nodes"]:
        extra = {"where": "thread", "thread_id": t["id"], "path": t["path"], "line": t["line"],
                 "resolved": t["isResolved"], "outdated": t["isOutdated"]}
        items[f"thread:{t['id']}"] = (f"{t['isResolved']}|{t['isOutdated']}",
                                      {**base, **extra, "kind": "thread_state"})
        for c in t["comments"]["nodes"]:
            comment(c, extra)
    return items


def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {"seen": {}, "rounds": {}}


def save(path, state):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)))
    with os.fdopen(fd, "w") as f:
        json.dump(state, f, indent=1, sort_keys=True)
    os.replace(tmp, path)


def one_pass(args, state):
    owner, name = repo_slug(args.repo)
    prs = [int(p) for p in args.prs.split(",")] if args.prs else open_prs(args.author)
    first = not state["seen"]
    events = []
    for n in prs:
        for key, (fp, ev) in snapshot(fetch(owner, name, n)).items():
            if state["seen"].get(key) == fp:
                continue
            new_item = key not in state["seen"]
            state["seen"][key] = fp
            # A reaction set that is empty and new is noise, not an event.
            if ev["kind"] == "reaction" and new_item and not ev["reactions"]:
                continue
            if ev["kind"] == "thread_state" and new_item:
                continue
            if "thread_id" in ev:
                ev["fix_rounds"] = state["rounds"].get(ev["thread_id"], 0)
            events.append(ev)
    if first and not args.emit_existing:
        return []
    return events


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--state", required=True)
    p.add_argument("--repo", help="owner/name (default: current repo)")
    p.add_argument("--prs", help="comma-separated PR numbers (default: open PRs by --author)")
    p.add_argument("--author", default="@me")
    p.add_argument("--wait", type=int, default=0, help="seconds to keep polling until an event")
    p.add_argument("--interval", type=int, default=75)
    p.add_argument("--emit-existing", action="store_true")
    p.add_argument("--bump-round", metavar="THREAD_ID")
    args = p.parse_args()

    state = load(args.state)
    if args.bump_round:
        state["rounds"][args.bump_round] = state["rounds"].get(args.bump_round, 0) + 1
        save(args.state, state)
        print(json.dumps({"thread_id": args.bump_round, "fix_rounds": state["rounds"][args.bump_round]}))
        return 0

    deadline = time.time() + args.wait
    while True:
        try:
            events = one_pass(args, state)
        except RuntimeError as e:
            print(json.dumps({"kind": "error", "message": str(e)}))
            return 2
        save(args.state, state)
        if events or time.time() + args.interval > deadline:
            break
        time.sleep(args.interval)
    for ev in events:
        print(json.dumps(ev, ensure_ascii=False))
    return 0 if events else 1


if __name__ == "__main__":
    sys.exit(main())
