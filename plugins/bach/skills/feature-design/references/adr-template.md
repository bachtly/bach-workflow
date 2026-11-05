# ADR template (MADR, short)

Write an ADR when a decision is significant, costly to reverse, and had a real alternative. One decision per ADR. File name: `NNNN-<imperative-verb-phrase>.md`, for example `0003-use-optimistic-locking-for-bookings.md`. Never rewrite an accepted ADR: supersede it with a new one.

```markdown
# <short title: problem and solution>

Status: proposed | accepted | superseded by NNNN · Date: YYYY-MM-DD · Deciders: <user> · Stage: <stage doc>

## Context and problem
<2–3 sentences>

## Decision drivers
- <goal, NFR id, constraint>

## Options
1. <option> 2. <option>

## Decision
Chosen: "<option>", because <justification tied to the drivers>.
- Good: <consequence>
- Bad: <consequence, and how we live with it>

## Pros and cons of the options
### <option>
- Good, because …
- Bad, because …
```
