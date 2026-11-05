# Stage 4 · API → `04-api.md`

Every interface the feature adds or changes: HTTP, GraphQL, RPC, events, jobs, CLI, or a module's public interface. Follow the style the repo already uses. Sketch shapes; put a formal contract (for example an OpenAPI fragment in `api/`) only if the repo keeps one.

## Template

```markdown
# <Feature>: API

## Surface
| Operation | Kind | Caller | Covers (UC/AC ids) | New / changed |
|---|---|---|---|---|

## Contracts
### <operation>
Request: <shape> · Response: <shape> · Status / result codes

## Errors
| Error | When | Code | Retryable | Caller should |
|---|---|---|---|---|

## Auth
| Operation | Who may call | Check (role, ownership, scope) |
|---|---|---|

## Behaviour
Idempotency (mutating operations) · pagination and filtering · rate limits · timeouts

## Events and async (if any)
| Event / job | Producer | Consumers | Schema | Ordering key | Delivery (at-least-once …) |
|---|---|---|---|---|---|

## Compatibility
<breaking or not; versioning, deprecation and the migration path for existing callers>

## Consumer check
| Consumer (UI, service, partner) | Flow | Can it be built from this contract? |
|---|---|---|
```

## Exit checklist
- Every AC that needs an interface maps to an operation, and every operation maps to an AC.
- Naming, error model and pagination follow the repo's existing API style.
- Every operation has an auth rule and its error cases.
- Every mutating operation states its idempotency.
- Request and response shapes match the data model (types, nullability, ids).
- No breaking change without a versioning or migration path.
- Every consumer can build its flow from the contract.
