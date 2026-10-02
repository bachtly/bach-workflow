#!/usr/bin/env python3
"""Frame step helper: create the run folder and print the Workflow args.

Usage: init_run.py <frame.json> [--out-root <dir>] [--allow-no-pdf]
Exits non-zero (BLOCKED) when pdftotext is missing, unless --allow-no-pdf.
frame.json (written by the main loop):
  {"topic": "...", "purpose": "...", "recency": "...", "depth": "quick|standard|deep",
   "types": ["solutions", ...], "paraphrases": ["...", ...]}
Prints the args object for Workflow (also saved as <run_dir>/args.json).
"""
import datetime
import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import record  # noqa: E402

SKILL_DIR = record.SKILL_DIR
BUDGETS = {
    #            cap  per_query terms_per_round max_queries max_rounds max_results
    "quick":    dict(cap=30, per_query=3, terms_per_round=3, max_queries=5, max_rounds=3, max_results=8),
    "standard": dict(cap=100, per_query=5, terms_per_round=5, max_queries=8, max_rounds=6, max_results=10),
    "deep":     dict(cap=250, per_query=5, terms_per_round=8, max_queries=12, max_rounds=10, max_results=10),
}


def types_spec(types):
    spec = record.read_json(os.path.join(SKILL_DIR, "references", "outcome-types.json"), {})
    out = []
    for t in types:
        s = spec[t]
        cols = ", ".join(f'"{k}" ({v})' for k, v in s["columns"].items())
        out.append(f'- type "{t}" ({s["answers"]}): {s["hint"]} Columns: {cols}.')
    return "\n".join(out)


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    frame = record.read_json(a[0])
    if not frame:
        sys.exit(f"cannot read {a[0]}")
    pdf_ok = bool(shutil.which("pdftotext"))
    if not pdf_ok and "--allow-no-pdf" not in a:
        sys.exit("BLOCKED: pdftotext not found. PDFs (papers, reports, standards) would be lost or read lossily.\n"
                 "Fix: brew install poppler   (Linux: apt install poppler-utils)\n"
                 "Override only if the user accepts losing every PDF source: rerun with --allow-no-pdf")
    root = os.path.abspath(a[a.index("--out-root") + 1] if "--out-root" in a else os.path.join(os.getcwd(), "research"))

    spec = record.read_json(os.path.join(SKILL_DIR, "references", "outcome-types.json"), {})
    bad = [t for t in frame.get("types", []) if t not in spec]
    if bad or not frame.get("types"):
        sys.exit(f"unknown or missing types {bad}; valid: {list(spec)}")
    depth = frame.get("depth", "standard")
    budget = {**BUDGETS[depth], **(frame.get("budget") or {})}

    today = datetime.date.today().isoformat()
    slug = re.sub(r"[^a-z0-9]+", "-", frame["topic"].lower()).strip("-")[:50].strip("-") or "research"
    run_dir = os.path.join(root, f"{today}-{slug}")
    n = 2
    while os.path.exists(run_dir):
        run_dir = os.path.join(root, f"{today}-{slug}-{n}")
        n += 1
    for d in ("search", "pages", "fetch", "notes", "judge"):
        os.makedirs(os.path.join(run_dir, d), exist_ok=True)

    run = {**frame, "depth": depth, "budget": budget, "created": today, "run_dir": run_dir, "pdf_support": pdf_ok}
    record.write_json(os.path.join(run_dir, "run.json"), run)
    args = {
        "run_dir": run_dir, "skill_dir": SKILL_DIR, "today": today,
        "topic": frame["topic"], "purpose": frame.get("purpose", ""), "recency": frame.get("recency", ""),
        "types": frame["types"], "types_spec": types_spec(frame["types"]), "budget": budget,
        "queue": [{"query": p, "origin": "paraphrase"} for p in frame["paraphrases"]],
    }
    record.write_json(os.path.join(run_dir, "args.json"), args)
    record.rebuild(run_dir)
    print(json.dumps(args, ensure_ascii=False))


if __name__ == "__main__":
    main()
