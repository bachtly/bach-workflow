# Stage 1 · Research → `01-research.md`

Brainstorm grounded in two kinds of evidence: how **our system** works today, and how **the industry** solves this job. The output is a set of options with trade-offs. The user picks the direction; later stages design only that direction.

Inputs: `00-brief.md`, `research/codebase.md` (codebase survey), the web-research `report.md` and `analysis_*.csv`.

## Template

```markdown
# <Feature>: research

## Our system today
- Current flow: <how the job is done now, step by step, with path:line>
- Relevant modules, data and contracts: <path:line>
- Reusable pieces: <what we can build on>
- Constraints and debt: <what limits the options>

## How others solve it
| Solution (product, OSS, pattern, standard) | Approach | Strengths | Weaknesses | Source |
|---|---|---|---|---|

## Options
### O1 · <name>
<summary> · fit with our system · rough cost · main risk · reversible? (yes / costly / no)
### O2 · <name>
### O0 · Buy / reuse / do nothing   (include when plausible)

## Comparison
| Criterion (from goals, constraints, NFR hints) | O1 | O2 | O0 |
|---|---|---|---|

## Recommendation
<option, the trade-off accepted, and what evidence would change the recommendation>

## Open questions
```

## Exit checklist
- At least 2 real options, plus buy/reuse/do-nothing when plausible.
- Every industry claim is cited (`[sid]` from web-research); every codebase claim has `path:line`.
- The comparison criteria come from the brief, not invented after the fact.
- The recommendation names the trade-off it accepts.
- The chosen direction becomes an ADR candidate.
