#!/usr/bin/env python3
"""Rebuild every CSV in a research run from the per-item JSON files (idempotent, file-locked).

Usage:
  record.py <run_dir>                       rebuild all CSVs
  record.py <run_dir> --check <rel.json>    validate one item file, then rebuild; prints a JSON summary
                                            (for notes/<sid>.json it also prints L1-vs-L2 recall)

Item files (written by agents):
  run.json                    topic, types, depth, ...
  search/<qid>.json           {qid, round, query, origin, results:[{rank,url,title,snippet,include,reason}]}
  fetch/<sid>.json            written by fetch.py
  notes/<sid>.json            {sid, url, title, published, source_type, quality_flags, terms, claims, analysis_rows, model}
  notes/<sid>.struct.json     written by fetch.py (L1)
  judge/<round>-<phase>.json  {round, phase, terms, new_terms, new_facts, contradictions, next_queue, stop}
"""
import csv
import fcntl
import glob
import json
import os
import re
import sys
import tempfile
from contextlib import contextmanager
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECALL_TOP = 20


def norm_url(u):
    """Must match normUrl() in workflow.js."""
    try:
        p = urlsplit(u.strip())
    except ValueError:
        return u.strip()
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
         if not k.lower().startswith("utm_") and k.lower() not in ("ref", "fbclid", "gclid")]
    path = p.path.rstrip("/") or "/"
    return urlunsplit((p.scheme.lower(), p.netloc.lower().removeprefix("www."), path, urlencode(q), ""))


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def write_csv(path, cols, rows):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: flat(r.get(k, "")) for k in cols})
    os.replace(tmp, path)


def flat(v):
    if isinstance(v, (list, tuple)):
        return "; ".join(flat(x) for x in v)
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, bool):
        return "yes" if v else "no"
    return "" if v is None else str(v)


@contextmanager
def locked(run_dir):
    os.makedirs(run_dir, exist_ok=True)
    with open(os.path.join(run_dir, ".lock"), "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def load_dir(run_dir, sub, pattern="*.json"):
    out = {}
    for p in sorted(glob.glob(os.path.join(run_dir, sub, pattern))):
        name = os.path.basename(p)
        if name.endswith(".struct.json"):
            continue
        d = read_json(p)
        if isinstance(d, dict):
            out[name[:-5]] = d
    return out


def qid_key(qid):
    m = re.match(r"r(\d+)q(\d+)", qid)
    return (int(m.group(1)), int(m.group(2))) if m else (9999, 9999)


def _rebuild(run_dir):
    run = read_json(os.path.join(run_dir, "run.json"), {}) or {}
    searches = load_dir(run_dir, "search")
    fetches = load_dir(run_dir, "fetch")
    notes = load_dir(run_dir, "notes")
    judges = load_dir(run_dir, "judge")

    owner = {norm_url(f.get("url", "")): sid for sid, f in fetches.items()}

    # ---- sources.csv ----
    sources, first_seen, qstats = [], {}, {}
    for qid in sorted(searches, key=qid_key):
        s = searches[qid]
        rnd = s.get("round", qid_key(qid)[0])
        st = qstats.setdefault(qid, {"results": 0, "screened_in": 0, "duplicates": 0})
        for r in s.get("results", []) or []:
            url = r.get("url", "")
            if not url:
                continue
            sid = f"{qid}-{int(r.get('rank', 0)):02d}"
            n = norm_url(url)
            own = owner.get(n)
            if own:
                dup_of = "" if own == sid else own
            else:
                dup_of = first_seen.get(n, "")
            first_seen.setdefault(n, sid)
            f = fetches.get(sid, {}) if not dup_of else {}
            note = notes.get(sid, {}) if not dup_of else {}
            st["results"] += 1
            st["duplicates"] += bool(dup_of)
            st["screened_in"] += (not dup_of) and bool(r.get("include"))
            sources.append({
                "sid": sid, "round": rnd, "qid": qid, "rank": r.get("rank", ""), "url": url,
                "domain": urlsplit(url).netloc.removeprefix("www."), "title": r.get("title", ""),
                "duplicate_of": dup_of,
                "screen": "" if dup_of else ("include" if r.get("include") else "exclude"),
                "screen_reason": "" if dup_of else r.get("reason", ""),
                "fetch_method": f.get("method", ""), "fetch_status": f.get("status", ""),
                "fetch_reason": f.get("reason", ""), "chars": f.get("chars", ""),
                "format": f.get("format", "html" if f else ""), "html_mode": f.get("mode", ""),
                "truncated": f.get("truncated", ""),
                "harvest_model": note.get("model", ""), "recall": note.get("_recall", ""),
                "source_type": note.get("source_type", ""), "published": note.get("published", ""),
                "included": bool(note) and f.get("status") == "ok",
            })
    write_csv(os.path.join(run_dir, "sources.csv"),
              ["sid", "round", "qid", "rank", "url", "domain", "title", "duplicate_of", "screen", "screen_reason",
               "fetch_method", "fetch_status", "fetch_reason", "chars", "format", "html_mode", "truncated",
               "harvest_model", "recall",
               "source_type", "published", "included"], sources)

    # ---- queries.csv ----
    qrows = []
    for qid in sorted(searches, key=qid_key):
        s = searches[qid]
        qrows.append({"round": s.get("round", ""), "qid": qid, "query": s.get("query", ""),
                      "origin": s.get("origin", ""), **qstats.get(qid, {})})
    write_csv(os.path.join(run_dir, "queries.csv"),
              ["round", "qid", "query", "origin", "results", "screened_in", "duplicates"], qrows)

    # ---- rounds.csv (PRISMA flow per judge pass) ----
    phase_order = {"interim": 0, "final": 1}
    jkeys = sorted(judges, key=lambda k: (int(judges[k].get("round", 0)), phase_order.get(judges[k].get("phase"), 2)))
    rrows = []
    for k in jkeys:
        j = judges[k]
        rnd = int(j.get("round", 0))
        rs = [s for s in sources if int(s["round"]) == rnd]
        live = [s for s in rs if not s["duplicate_of"]]
        stop = j.get("stop") or {}
        rrows.append({
            "round": rnd, "phase": j.get("phase", ""),
            "queries": len({s["qid"] for s in rs}), "identified": len(rs),
            "duplicates": len(rs) - len(live),
            "screened_out": sum(s["screen"] == "exclude" for s in live),
            "sought": sum(bool(s["fetch_status"]) for s in live),
            "failed": sum(s["fetch_status"] == "failed" for s in live),
            "via_webfetch": sum(s["fetch_method"] == "webfetch" and s["fetch_status"] == "ok" for s in live),
            "included": sum(bool(s["included"]) for s in live),
            "new_terms": j.get("new_terms", ""), "new_facts": j.get("new_facts", ""),
            "stop": stop.get("stop", ""), "stop_reason": stop.get("reason", ""),
        })
    write_csv(os.path.join(run_dir, "rounds.csv"),
              ["round", "phase", "queries", "identified", "duplicates", "screened_out", "sought", "failed",
               "via_webfetch", "included", "new_terms", "new_facts", "stop", "stop_reason"], rrows)

    # ---- terms.csv (later passes overwrite earlier ones) ----
    terms = {}
    for k in jkeys:
        j = judges[k]
        for t in j.get("terms", []) or []:
            name = (t.get("term") or "").strip()
            if not name:
                continue
            key = name.lower()
            prev = terms.get(key, {})
            srcs = t.get("sources") or []
            terms[key] = {
                "term": name, "first_round": prev.get("first_round", j.get("round")),
                "last_round": j.get("round"), "phase": j.get("phase"),
                "score": t.get("score", ""), "freq": t.get("freq", ""), "centrality": t.get("centrality", ""),
                "novelty": t.get("novelty", ""), "status": t.get("status", ""),
                "source_count": len(srcs), "source_ids": srcs,
            }
    trows = sorted(terms.values(), key=lambda r: (-(float(r["score"]) if str(r["score"]).replace(".", "", 1).isdigit() else 0), r["term"].lower()))
    write_csv(os.path.join(run_dir, "terms.csv"),
              ["term", "first_round", "last_round", "phase", "score", "freq", "centrality", "novelty", "status",
               "source_count", "source_ids"], trows)

    # ---- analysis_<type>.csv ----
    spec = read_json(os.path.join(SKILL_DIR, "references", "outcome-types.json"), {}) or {}
    for typ in run.get("types", []) or []:
        cols = list((spec.get(typ) or {}).get("columns", {}).keys())
        rows = []
        for sid, n in sorted(notes.items()):
            for r in n.get("analysis_rows", []) or []:
                if isinstance(r, dict) and r.get("type", typ if len(run["types"]) == 1 else None) == typ:
                    rows.append({**r, "sid": sid, "url": n.get("url", ""), "published": n.get("published", "")})
        write_csv(os.path.join(run_dir, f"analysis_{typ}.csv"), cols + ["sid", "url", "published"], rows)


def rebuild(run_dir):
    with locked(run_dir):
        _rebuild(run_dir)


def recall_of(run_dir, sid, note):
    struct = read_json(os.path.join(run_dir, "notes", sid + ".struct.json"), {}) or {}
    l1 = [t for t in struct.get("terms", []) if t.get("kind") != "ngram" or t.get("count", 0) >= 2][:RECALL_TOP]
    if not l1:
        return None, 0, []
    hay = " ".join([json.dumps(note.get("terms", []), ensure_ascii=False),
                    json.dumps(note.get("claims", []), ensure_ascii=False),
                    json.dumps(note.get("analysis_rows", []), ensure_ascii=False)]).lower()
    missing = [t["term"] for t in l1 if t["term"].lower() not in hay]
    return round(1 - len(missing) / len(l1), 2), len(l1), missing


def check(run_dir, rel):
    path = os.path.join(run_dir, rel)
    d = read_json(path)
    if not isinstance(d, dict):
        return {"ok": False, "error": f"{rel} is missing or not valid JSON; rewrite it"}
    kind = rel.split("/")[0]
    need = {"search": ["qid", "query", "results"], "notes": ["sid", "url", "terms", "claims"],
            "judge": ["round", "phase", "terms", "next_queue", "stop"]}.get(kind, [])
    miss = [k for k in need if k not in d]
    if miss:
        return {"ok": False, "error": f"{rel} lacks keys: {miss}"}
    out = {"ok": True}
    if kind == "notes":
        sid = os.path.basename(rel)[:-5]
        r, n, missing = recall_of(run_dir, sid, d)
        d["_recall"] = "" if r is None else r
        write_json(path, d)
        out.update(recall=r, l1_terms=n, missing=missing[:12],
                   terms=len(d.get("terms", [])), claims=len(d.get("claims", [])),
                   rows=len(d.get("analysis_rows", []) or []))
    return out


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit("usage: record.py <run_dir> [--check <rel.json>]")
    run_dir = a[0]
    out = {"ok": True}
    if len(a) == 3 and a[1] == "--check":
        with locked(run_dir):
            out = check(run_dir, a[2])
    rebuild(run_dir)
    print(json.dumps(out, ensure_ascii=False))
    sys.exit(0 if out.get("ok") else 2)


if __name__ == "__main__":
    main()
