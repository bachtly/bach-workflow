# Stage 6 · Backend → `06-backend.md`

How the system delivers the API and NFRs: structure, runtime behaviour under concurrency and failure, infrastructure, and how it ships safely. Pseudo-code only for a novel algorithm; link to a prototype instead when one exists.

## Template

```markdown
# <Feature>: backend

## Components
<Mermaid C4-style container/component diagram; mark new and changed parts>

## Key sequences
<one Mermaid sequenceDiagram per main use case, plus at least one failure path>

## Modules and types
| Module | Responsibility | Main types / interfaces | Depends on |
|---|---|---|---|
<where the business rules live, following the repo's layering>

## Concurrency model
- Execution: <sync request, background job, stream, scheduled>
- Shared state and contention points: <what two actors can change at once>
- Consistency per operation: <strong / eventual, and what the user sees meanwhile>
- Control: <transaction boundary and isolation, optimistic version, lock, unique constraint>
- Idempotency and dedupe: <keys, window>
- Ordering: <what must be ordered, by which key>
- Retries and timeouts: <per external call: timeout, retry policy, backoff>
- Backpressure and limits: <queue bounds, concurrency caps, rate limits>
- Load model: <concurrency, payload size, fan-out, burst> → what breaks first

## Infrastructure
<runtime, storage, queues, caches, config and secrets, cost; any new infra links an ADR>

## Failure modes
| Failure | Detection | Impact | Mitigation |
|---|---|---|---|

## Observability
| Signal (log, metric, trace, alert) | Proves which NFR or failure | Threshold |
|---|---|---|

## Security and privacy
<threats per trust boundary (spoofing, tampering, disclosure, abuse), data handling>

## Testing strategy
<unit, integration, contract, load: what proves each AC group and each NFR>

## Rollout and rollback
<flag, migration order against deploy order, stages, halt metrics, kill switch, rollback steps>
```

## Exit checklist
- Every NFR has a mechanism that meets it and a signal that observes it.
- Every piece of shared mutable state has a named concurrency control.
- Every retried operation is idempotent; every external call has a timeout.
- The failure-mode table covers each external dependency being slow and being down.
- Each rollout step can be rolled back, and migration order is compatible with deploy order.
- New infrastructure has an ADR.
- Module boundaries follow the repo's existing layering.
