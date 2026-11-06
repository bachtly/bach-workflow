# Stage 0 · Brief → `00-brief.md`

Written by the lead with the user. Every later stage reads it. The glossary is the one source for names: later docs use its terms, never synonyms.

## Template

```markdown
# <Feature>: brief

## Problem
<2–3 sentences: who has the problem, what happens today, how we know (link, ticket, metric) or "assumption">

## Users and job
<persona(s)> · job: <under 20 words>

## Goals
- G1 <outcome, measurable where possible>

## Non-goals
- <things that could reasonably be goals but are explicitly not>

## Constraints
<deadline, stack, compliance, budget, systems that must be reused or must not change>

## Area of the system
| Module / service | Path | Why it is touched |
|---|---|---|

## Stages
| Stage | Run / skip | Reason |
|---|---|---|
| research · requirements · data-model · api · ui · backend · design | | |

## Glossary
| Term | Meaning | Name in code (if it exists) |
|---|---|---|
```

## Exit checklist
- The problem cites evidence, or is marked as an assumption.
- At least one non-goal.
- Every goal is checkable after launch.
- Every skipped stage has a reason (for example "no persisted state changes").
- Glossary terms match the names already used in the code.
