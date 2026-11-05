# Stage 2 · Requirements and flows → `02-requirements.md`

What the feature must do, for whom, and how well, for the chosen direction only. The ids defined here (UC, US, AC, NFR) are what every later stage and the roadmap trace to.

## Template

```markdown
# <Feature>: requirements

## Actors
| Actor | Description | Permissions |
|---|---|---|

## Use cases
### UC-1 · <name>
Actor · trigger · preconditions
Main flow: 1. … 2. …
Alternate / exception flows: 2a. <condition> → …
Postconditions

## User stories
### US-1 · As a <actor>, I want <capability>, so that <goal G#>
- AC-1.1 When <trigger>, the <system> shall <response>.
- AC-1.2 If <unwanted condition>, then the <system> shall <response>.

## User flows
<one Mermaid flowchart per main use case, including error, empty and cancel paths>

## Non-functional requirements
| Id | Quality | Scenario | Target |
|---|---|---|---|
| NFR-1 | latency | <operation> under <load> | p95 < 300 ms |

## Out of scope
```

AC use EARS patterns, one behaviour each:

| Pattern | Form |
|---|---|
| Ubiquitous | The <system> shall … |
| Event | When <trigger>, the <system> shall … |
| State | While <state>, the <system> shall … |
| Unwanted | If <condition>, then the <system> shall … |
| Optional | Where <feature is enabled>, the <system> shall … |

## Exit checklist
- Every use case has exception flows.
- Every AC is testable, has an id and states one behaviour.
- Every story traces to a goal in the brief; no goal is left without a story.
- Flows cover error, empty and permission-denied paths.
- Every NFR has a number (latency, throughput, availability, data volume, retention, accessibility level).
- Uses glossary terms only.
