#!/usr/bin/env python3
"""Merge agent-extracted and human-collected evidence into one evidence.csv (stdlib only).

Usage:
  merge_evidence.py <run_dir>

Inputs:
  evidence/extracted/*.json   agent rows: {"rows": [{type, source, url, date, quote_or_number,
                              persona_match, theme, note}]}
  evidence_human.csv          rows the user filled in (same columns; theme optional)
Output:
  evidence.csv                with stable ids E001.. and a `by` column (agent|human)
  evidence_stats.json         counts the W1/W2 worksheets rely on
Dedupes on (url, first 80 chars of the quote). Prints the stats JSON.
"""
import csv, json, sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

COLS = ["id", "by", "type", "source", "url", "date", "quote_or_number", "persona_match", "theme", "note"]


def place(row):
    """An 'independent place' = subreddit / site, so W1 can count spread, not volume."""
    src = (row.get("source") or "").strip().lower()
    if src.startswith("reddit r/"):
        return src
    host = urlparse(row.get("url") or "").netloc.lower().removeprefix("www.")
    return host or src or "unknown"


def main(run_dir):
    run = Path(run_dir)
    rows = []
    for f in sorted((run / "evidence" / "extracted").glob("*.json")):
        try:
            for r in json.loads(f.read_text()).get("rows", []):
                rows.append({**r, "by": "agent"})
        except Exception as e:
            print(f"skip {f.name}: {e}", file=sys.stderr)
    human = run / "evidence_human.csv"
    if human.exists():
        with human.open(newline="") as fh:
            for r in csv.DictReader(fh):
                if any((v or "").strip() for v in r.values()):
                    rows.append({**r, "by": "human"})

    seen, out = set(), []
    for r in rows:
        key = ((r.get("url") or "").strip(), (r.get("quote_or_number") or "").strip()[:80].lower())
        if key in seen or not key[1]:
            continue
        seen.add(key)
        out.append(r)
    for i, r in enumerate(out, 1):
        r["id"] = f"E{i:03d}"

    with (run / "evidence.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(out)

    pain = [r for r in out if (r.get("type") or "").strip() == "pain" and (r.get("persona_match") or "y").strip().lower().startswith("y")]
    themes = defaultdict(lambda: {"quotes": 0, "places": set(), "ids": []})
    for r in pain:
        t = (r.get("theme") or "untagged").strip().lower()
        themes[t]["quotes"] += 1
        themes[t]["places"].add(place(r))
        themes[t]["ids"].append(r["id"])
    stats = {
        "rows": len(out),
        "by": {"agent": sum(r["by"] == "agent" for r in out), "human": sum(r["by"] == "human" for r in out)},
        "by_type": {t: sum((r.get("type") or "") == t for r in out) for t in sorted({r.get("type") or "" for r in out})},
        "pain_quotes": len(pain),
        "pain_places": len({place(r) for r in pain}),
        "themes": sorted(
            ({"theme": t, "quotes": v["quotes"], "places": len(v["places"]), "ids": v["ids"]} for t, v in themes.items()),
            key=lambda x: (-x["quotes"], -x["places"]),
        ),
    }
    (run / "evidence_stats.json").write_text(json.dumps(stats, indent=1))
    print(json.dumps({k: v for k, v in stats.items() if k != "themes"} | {"top_themes": stats["themes"][:5]}, default=list))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
