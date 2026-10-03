# Gates: worksheets W1–W4 and the decision rule

Pre-registered: these rules are written before research and must not be edited after evidence arrives.

## W1 · Pain: do people complain about this without being asked?
1. Use `evidence.csv` rows with type=`pain` and persona_match=y; ignore rows older than 24 months and vendor-written text.
2. Group into themes (merge near-duplicates); pick the top theme.
3. Count quotes and **independent places** (each subreddit / site = one place). `evidence_stats.json` has a first-pass count.

| Pass | Partial | Fail |
|---|---|---|
| ≥10 quotes from ≥3 places on one theme | 5–9 quotes, or only 1–2 places | <5 quotes |

## W2 · Gap: what will the demo show that competitors don't?
1. Competitors: web-research `analysis_landscape.csv` + `analysis_comparison.csv` + any in `evidence.csv` (type=`competitor`). List 5–15 with name, URL, main promise.
2. Tag 1–3★ reviews (`type=review`) by theme. A theme in the bad reviews of ≥3 different competitors = **shared weakness**. Also use `analysis_root_cause.csv`.
3. Write: "Unlike <X>, <product> <does the weakness right> for <persona>."

| Pass | Partial | Fail |
|---|---|---|
| Shared weakness found + one-sentence differentiator | Weakness in only 1–2 competitors, or 0 competitors (novel, unproven) | Nothing you would do differently |

## W3 · Demo moment: is the payoff visible on screen in under 2 minutes?
1. One line "before → after": what the persona sees today vs in the app.
2. The result is visible (screen change, generated output, chart, file), not invisible backend work.
3. Reachable in ≤2 min and ≤5 clicks.
4. Not a generic AI wrapper (judges no longer reward generic LLM demos).

| Pass | Partial | Fail |
|---|---|---|
| Visible before → after in ≤2 min, with a clear "wow" | Visible but slow or underwhelming | Value invisible, or needs days of usage |

## W4 · 2-day build: can the demo path be built in about 14 hours?
1. List every dependency on the demo path: external APIs, data sources, auth, AI models, file processing.
2. Rate each: **known**, **new but documented**, **unknown/risky**.
3. Riskiest dependency → a 30-minute spike in Plan.
4. Every risky dependency gets a fallback: mock, seeded data, or cached response.

| Pass | Partial | Fail |
|---|---|---|
| ≤1 risky dependency, with a fallback | 2 risky, both with fallbacks | Needs unobtainable data, hardware, or >2 risky |

## Decision

| Result | Decision |
|---|---|
| 4 pass, or 3 pass + 1 partial | **GO** |
| No fail and ≥2 partial | **NARROW** once: narrow persona/job (G1/G2) or shrink the demo (G3/G4); redo only the weak worksheets |
| G1 or G2 fail | **KILL** |
| Only G3 or G4 fail | **NARROW** once (smaller demo moment or swap the risky dependency); fail again → **KILL** |

The critic's verdict is advice. If the critic flipped its verdict under a push-back that had no new evidence, its verdict is discarded as sycophantic.
