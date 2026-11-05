# Stage 3 · Data model → `03-data-model.md`

Only new or changed persisted state, plus the neighbours it relates to. Show shape and rules, not a full DDL dump: the schema itself is written during implementation.

## Template

```markdown
# <Feature>: data model

## Entities
| Entity | Purpose | Owning module | New / changed | Lifecycle (created → … → deleted) |
|---|---|---|---|---|

## ERD
<Mermaid erDiagram: new and changed entities and their direct neighbours>

## Attributes (new or changed only)
| Entity.field | Type | Null | Default | Constraint / note |
|---|---|---|---|---|

## Invariants
| Rule | Enforced where (DB constraint, domain model, both) |
|---|---|

## Access patterns
| Query or write (UC/AC id) | Frequency | Index or key | Expected volume and growth |
|---|---|---|---|

## Transactions and consistency
<what must change atomically; cascade and delete behaviour>

## Migration and backfill
<expand → migrate → contract steps, safe while old code runs, reversible, duration at production volume>

## Retention and privacy
<PII fields, classification, retention, deletion or export path>
```

## Exit checklist
- Every entity has a primary key and an owning module.
- Every access pattern has an index or key, or a stated reason it doesn't need one.
- Every invariant has an enforcement point.
- Cascade and delete behaviour is stated for each relationship.
- The migration runs safely alongside the currently deployed code and can be rolled back.
- PII is marked, with retention and deletion.
- Names and types follow the repo's existing schema conventions.
