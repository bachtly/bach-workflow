---
name: web-research
description: Deep, iterative web research on a given topic, with a PRISMA-style evidence trail in CSV files. Paraphrases the topic with industry terms, then streams every query and URL through parallel cheap agents (Haiku search+screen, Haiku fetch+verbatim harvest), with batched low-effort Opus judging that expands on key terms over multiple rounds until coverage saturates. Use whenever the user asks to "research", "deep dive", "investigate", "find everything about", "survey the landscape of", compare options, find solutions or best practices, or wants a thorough, well-sourced understanding of a topic, even if they don't say "web research".
---

# Web Research

A streaming expand-and-read loop. It is fast because it runs cheap agents in parallel and batches Opus judging, and it leaves evidence on disk at every step.

**Invoking this skill opts into a large fan-out.** One Workflow can start 20–100+ agents per round, which is above the default workflow size guideline. Concurrency is capped by the runtime at min(16, CPUs−2).

## Architecture

| Step | Who | Shape | Writes |
|---|---|---|---|
| 0 Frame | main loop (you), low effort | once | `frame.json` → `init_run.py` → run folder |
| 1 Search + screen | Haiku · low | 1 agent per query, streaming | `search/<qid>.json` |
| — Dedupe + cap | workflow script (no model) | in-memory, race-free | — |
| 2 Fetch + harvest | `fetch.py` (curl) → WebFetch fallback; Haiku · low harvests verbatim | 1 agent per URL, streaming | `pages/`, `fetch/`, `notes/<sid>.json`, `notes/<sid>.struct.json` |
| — Recall check | `record.py` (L1 script terms vs L2 Haiku terms) | per page | `_recall` in the note |
| 2b Re-harvest | Sonnet · low | only pages with recall < 0.5 | overwrites the note |
| 3a Early judge | Opus · low | 1 batch at ≥50% of the round's notes | `judge/<r>-interim.json` |
| 3b Final judge | Opus · low | 1 batch at 100% (the only barrier) | `judge/<r>-final.json` |
| 4 Report | main loop (you) | once | `report.md`, HTML artifact |

Every agent runs `record.py` after writing its JSON. That rebuilds **all CSVs** under a file lock, so the CSVs are always current and can be used mid-run.

## Prerequisite (blocker)

`pdftotext` (poppler) must be installed. `init_run.py` refuses to start without it, because PDFs (papers, reports, standards) would otherwise be lost or read lossily through WebFetch.
- If it prints `BLOCKED`, ask the user to run `! brew install poppler` (Linux: `apt install poppler-utils`), then retry.
- Pass `--allow-no-pdf` only if the user explicitly accepts losing every PDF source, and state that in the report's Method section.

## Inputs (ask only what is unclear, in one AskUserQuestion)

- **topic**
- **purpose/audience**: market scan, technical, academic, decision
- **recency need**: e.g. last 12 months, or none
- **depth**: quick / standard / deep (default standard)
- **outcome types**, one or more from `references/outcome-types.json`:

| Type | Answers |
|---|---|
| `solutions` | How do people solve X? |
| `landscape` | Who/what is in space X? |
| `comparison` | A vs B vs C? |
| `situation` | What is happening with X? |
| `root_cause` | Why does X fail? |
| `how_to` | Steps to do X? |
| `best_practices` | What is recommended for X? |

Infer the types from the wording when it is obvious ("how do teams handle…" → solutions + best_practices).

## Budgets (`scripts/init_run.py`)

| | quick | standard | deep |
|---|---|---|---|
| paraphrases (round 1 queries) | 3 | 5 | 10 |
| results screened / query | 8 | 10 | 10 |
| URLs fetched / query | 3 | 5 | 5 |
| new terms queued / round | 3 | 5 | 8 |
| queries / later round | 5 | 8 | 12 |
| **fetch cap (hard)** | 30 | 100 | 250 |
| max rounds (safety) | 3 | 6 | 10 |

The fetch cap is the real limit, and there are no minimum rounds. To override a budget, add `"budget": {...}` to `frame.json`.

## Procedure

### 0. Frame (you, low effort, no web calls)

1. Paraphrase the topic N ways (N from the budget table). Mix: industry jargon, layman wording, acronym and its expanded form, an adjacent-field term, problem framing ("how to X"), and one non-English or regional term if relevant. Add the recency need into the wording where it matters, using the real current year, never a hardcoded one.
2. Write `frame.json` to the scratchpad:
   `{"topic","purpose","recency","depth","types":[...],"paraphrases":[...]}`
3. Run `python3 <skill_dir>/scripts/init_run.py <frame.json>` from the project root. It creates `./research/<YYYY-MM-DD>-<slug>/` and prints the Workflow args JSON.
4. Tell the user the run folder path. They can open the CSVs at any time.

### 1–3. Run the workflow

Call `Workflow` with `scriptPath: <skill_dir>/workflow.js` and `args: <the printed JSON object>`. Pass it as a JSON object, not a string.

The script loops over rounds on its own: search+screen → dedupe/cap → fetch+harvest (+ Sonnet re-harvest) → early judge → final judge → stop check → next round. Don't poll it; you are notified when it finishes. If it is interrupted, relaunch with `resumeFromRunId`.

Stop conditions:

| Who decides | Condition |
|---|---|
| script | **Budget**: fetch cap reached |
| script | **Repetition**: >50% of a later round's results were already seen (counted before dedupe) |
| script | no new queries, no usable pages, or max rounds |
| final judge | **Answered**: every key question has ≥2 independent sources (can stop after round 1) |
| final judge | **Saturation**: <20% new terms, or <3 new facts |
| final judge | **Drift**: most new terms are off-topic |

The early judge never stops a run. It only gives an interim `terms.csv` and a provisional queue.

Expand queries come from the judge: contradictions, important single-source claims, key numbers (to find the original source and date), recency gaps, one-sided sources (limitations/vs queries), and central named entities (their official page).

### 4. Report (you)

1. Read `rounds.csv`, `terms.csv`, `analysis_<type>.csv`, and `sources.csv`. Open individual `notes/<sid>.json` only for claims you cite. Don't reread raw pages unless a claim is disputed.
2. Write `report.md` in the run folder:
   1. TL;DR (3–5 lines)
   2. Key concepts / glossary (top terms, 1 line each)
   3. Findings by theme. Each claim is cited `[sid]` → URL and gets a confidence: **high** (≥2 independent sources, at least one primary), **medium** (2 sources, or 1 primary), **low** (single non-primary source)
   4. Analysis tables, aggregated per outcome type (e.g. one row per solution with `src_count`)
   5. Disagreements and open questions
   6. Method: a PRISMA flow table (identified → duplicates → screened out → sought → not retrieved → included), rounds run, stop reason, models used
   7. Sources: sid, title, URL, date, source_type, and flags for undated or low quality
3. Publish the report as an HTML artifact (a PRISMA flow diagram plus sortable analysis tables), following the Artifact tool's rules.
4. In chat, give a short TL;DR, the run folder path, and the artifact link.

## Rules

- Paraphrase and never paste long passages. Quotes are ≤15 words, at most one per source in the report.
- Never invent citations. Every cited claim must trace to a `notes/<sid>.json` entry.
- Flag low-quality, vendor-only, and undated sources.
- Never edit the CSVs by hand. They are rebuilt from the JSON files by `record.py`.
- PDFs are never sent to WebFetch. A PDF that `pdftotext` can't read (scanned, or download failed) is logged as failed in `sources.csv`.
- HTML: boilerplate (nav, popups, and header/footer/aside outside `<main>`/`<article>`) is stripped. If stripping would remove more than 50% of the text, the full text is kept instead (`html_mode=raw`). Pages are truncated only beyond 500k characters, as a safety valve (`truncated=yes`).
- Don't reread URLs. The workflow dedupes on normalised URLs across all rounds.
- If the workflow reports `dropped_by_cap > 0`, say so in the Method section. Truncation must never be silent.

## Files

| Path | Purpose |
|---|---|
| `workflow.js` | Orchestration (rounds, streaming pipeline, early/final judge, stop logic) and all agent prompts |
| `scripts/init_run.py` | Frame → run folder, `run.json`, `args.json`, budgets, outcome-type spec text |
| `scripts/fetch.py` | curl + HTML→markdown (stdlib only), PDF via `pdftotext`, bot-wall/JS-only detection, L1 terms, `--from-file` for the WebFetch fallback. Exit 0 ok · 3 → WebFetch fallback · 4 hard fail, no fallback (PDFs) |
| `scripts/structural_terms.py` | L1 terms: headings, bold, code, acronyms, capitalised n-grams |
| `scripts/record.py` | Rebuilds every CSV from the JSON files (file-locked); `--check` validates an item and computes harvest recall |
| `references/outcome-types.json` | Columns and harvest hints per outcome type |

Run folder: `run.json`, `args.json`, `queries.csv`, `sources.csv`, `terms.csv`, `rounds.csv`, `analysis_<type>.csv`, `search/`, `pages/`, `fetch/`, `notes/`, `judge/`, `report.md`.
