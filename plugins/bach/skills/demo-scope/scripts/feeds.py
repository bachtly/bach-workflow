#!/usr/bin/env python3
"""Fetch raw demand evidence from agent-reachable public feeds (stdlib only).

Usage:
  feeds.py <run_dir> --keywords "k1" "k2" [--subreddits a b] [--appids 123 456]

Sources (verified reachable 2026-10-02): Reddit search RSS, Hacker News Algolia,
App Store customer-review RSS. Writes evidence/raw/<source>-<n>.json and prints a
JSON summary. Failures are recorded, never fatal.
"""
import argparse, concurrent.futures as cf, html, json, re, sys, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path
import xml.etree.ElementTree as ET

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 Chrome/126 Safari/537.36"
ATOM = "{http://www.w3.org/2005/Atom}"


def get(url, timeout=20, retries=3):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == retries:
                raise
            wait = int(e.headers.get("Retry-After") or 0) or 6 * (attempt + 1)
            time.sleep(min(wait, 30))


def strip_html(s):
    s = re.sub(r"<[^>]+>", " ", html.unescape(s or ""))
    return re.sub(r"\s+", " ", s).strip()


def reddit(sub, kw):
    base = f"https://www.reddit.com/r/{sub}/search.rss" if sub else "https://www.reddit.com/search.rss"
    q = {"q": kw, "sort": "top", "t": "year"}
    if sub:
        q["restrict_sr"] = "1"
    url = base + "?" + urllib.parse.urlencode(q)
    root = ET.fromstring(get(url))
    items = []
    for e in root.findall(f"{ATOM}entry"):
        link = e.find(f"{ATOM}link")
        items.append({
            "source": f"reddit r/{sub}" if sub else "reddit",
            "url": link.get("href") if link is not None else "",
            "date": (e.findtext(f"{ATOM}updated") or "")[:10],
            "title": strip_html(e.findtext(f"{ATOM}title")),
            "text": strip_html(e.findtext(f"{ATOM}content"))[:2000],
        })
    return url, items


def hn(kw, tags):
    url = "https://hn.algolia.com/api/v1/search?" + urllib.parse.urlencode({"query": kw, "tags": tags, "hitsPerPage": 40})
    items = []
    for h in json.loads(get(url)).get("hits", []):
        oid = h.get("objectID")
        items.append({
            "source": "hackernews",
            "url": f"https://news.ycombinator.com/item?id={oid}",
            "date": (h.get("created_at") or "")[:10],
            "title": h.get("title") or h.get("story_title") or "",
            "text": strip_html(h.get("comment_text") or h.get("story_text") or "")[:2000],
            "points": h.get("points"),
        })
    return url, items


def appstore(appid):
    url = f"https://itunes.apple.com/us/rss/customerreviews/id={appid}/sortby=mostrecent/json"
    entries = json.loads(get(url)).get("feed", {}).get("entry", []) or []
    if isinstance(entries, dict):
        entries = [entries]
    items = []
    for x in entries:
        rating = int((x.get("im:rating") or {}).get("label", "0") or 0)
        if not rating or rating > 3:
            continue
        items.append({
            "source": f"appstore {appid}",
            "url": f"https://apps.apple.com/app/id{appid}",
            "date": (x.get("updated") or {}).get("label", "")[:10],
            "title": (x.get("title") or {}).get("label", ""),
            "text": (x.get("content") or {}).get("label", "")[:2000],
            "rating": rating,
        })
    return url, items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--keywords", nargs="+", required=True)
    ap.add_argument("--subreddits", nargs="*", default=[])
    ap.add_argument("--appids", nargs="*", default=[])
    a = ap.parse_args()
    out = Path(a.run_dir) / "evidence" / "raw"
    out.mkdir(parents=True, exist_ok=True)
    kws = a.keywords[:4]

    # Reddit rate-limits anonymous RSS hard (429 after a few calls): keep the job list small.
    reddit_jobs = [(None, k) for k in kws] + [(s, k) for s in a.subreddits[:3] for k in kws[:2]]
    other_jobs = [("hn", (k, t)) for k in kws for t in ("comment", "story")] + [("app", (i,)) for i in a.appids[:5]]

    results, failures = [], []

    def run(kind, args):
        try:
            if kind == "reddit":
                return kind, args, reddit(*args)
            if kind == "hn":
                return kind, args, hn(*args)
            return kind, args, appstore(*args)
        except Exception as e:  # recorded, never fatal
            return kind, args, e

    # Reddit politely: 1 worker, 3 s spacing, backoff on 429. Others: parallel.
    with cf.ThreadPoolExecutor(max_workers=6) as pool:
        futs = [pool.submit(run, k, ar) for k, ar in other_jobs]
        for s, k in reddit_jobs:
            results.append(run("reddit", (s, k)))
            time.sleep(3)
        results += [f.result() for f in futs]

    files, n_items = [], 0
    for i, (kind, args, res) in enumerate(results):
        if isinstance(res, Exception):
            failures.append({"kind": kind, "args": [x for x in args if x], "error": str(res)[:200]})
            continue
        url, items = res
        if not items:
            continue
        p = out / f"{kind}-{i:02d}.json"
        p.write_text(json.dumps({"query_url": url, "args": [x for x in args if x], "items": items}, indent=1))
        files.append(str(p))
        n_items += len(items)
    summary = {"files": files, "items": n_items, "failures": failures}
    (out / "_summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary))


if __name__ == "__main__":
    sys.exit(main())
