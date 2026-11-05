# Stage 7 · Design summary → `design.md` + `roadmap.md`

`design.md` is the entry point a reviewer reads in about 15 minutes, shaped like a classic design doc. It summarises and links the stage docs; it doesn't repeat them. Sections of skipped stages are written here in a few lines.

## `design.md` template

```markdown
# <Feature>: design   (status · date · authors)

## Context and scope
## Goals and non-goals          (from the brief)
## Overview                     (system-context diagram + one paragraph)
## Design
### Requirements   → 02-requirements.md   (3–6 lines each)
### Data model     → 03-data-model.md
### API            → 04-api.md
### UI             → 05-ui.md
### Backend        → 06-backend.md
## Alternatives considered      (rejected options and why, from research and ADRs)
## Cross-cutting concerns       (security, privacy, observability, accessibility, cost)
## Risks and open questions     (each with an owner)
## Decisions                    (ADR index)
```

## `roadmap.md` (pr-team hand-off)

The same format pr-team reads from demo-scope:
- One section per feature slice: `## F<n> · <name>`, with Status (⬜/✅), Depends on (F ids or none), AC ids, Design refs (`<doc>#<section>` links), and a one-line goal.
- Prefer vertical slices that each ship behind a flag. A shared contract (schema, API types) goes in its own early slice.
- A Mermaid dependency graph of the F ids, and a waves table: Wave | Features (features in one wave don't depend on each other).

## Exit checklist
- Every AC appears in exactly one F.
- Every ADR is referenced from design.md or a stage doc.
- No two docs contradict each other (names, types, ids, behaviour).
- Alternatives considered lists at least one rejected option with its reason.
- Every open question has an owner.
- Pre-mortem: the critic's "it is six months later and this failed: why?" answers are either mitigated or listed as risks.
