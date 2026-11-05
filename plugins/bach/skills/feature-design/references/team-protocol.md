# Phase 2 team protocol

Read by every phase-2 teammate. The spawn prompt gives the values: `RUN` (design folder, same path in every branch), `SYNC` (state file), `SYNCPY` (sync.py), `SKILL` (skill folder), `SLUG`, your `STAGE`, and the writer ↔ stage ↔ branch map.

## Branches and docs
| Stage | Doc | Branch | Writer |
|---|---|---|---|
| data-model | `RUN/03-data-model.md` | `design/SLUG/data-model` | `data-writer` |
| api | `RUN/04-api.md` | `design/SLUG/api` | `api-writer` |
| ui | `RUN/05-ui.md` | `design/SLUG/ui` | `ui-writer` |
| backend | `RUN/06-backend.md` | `design/SLUG/backend` | `backend-writer` |

- Every branch starts from `main`, which already holds the merged foundation (`00-brief.md`, `01-research.md`, `02-requirements.md`, ADRs). The foundation is the source of truth for goals, glossary and UC/AC/NFR ids.
- A writer edits only its own doc and ADRs it reserved. Nobody else pushes to its branch.
- Read a peer's **current** doc from its branch, not from main: `git fetch -q origin && git show origin/design/SLUG/<stage>:RUN/<doc>`. If the branch doesn't exist yet, use the foundation and mark what you assumed.

## Who owns which fact
A fact's owner decides it; everyone else follows the owner's branch.

| Fact | Owner |
|---|---|
| Goals, non-goals, glossary terms, actors, UC/US/AC/NFR ids | lead (foundation) |
| Entities, fields, types, keys, invariants, migrations | data-model |
| Operations, request/response shapes, errors, auth rules, events | api |
| Screens, states, navigation, client-side behaviour | ui |
| Components, modules, concurrency control, infra, failure handling, rollout | backend |

- Need a fact you don't own, and the owner hasn't written it? Write it in your doc as `ASSUMES(<owner stage>): <fact>` and message the owner. Remove the marker once the owner's branch has it.
- Need the owner to change a fact? Send it a **change request** (message: what, why, which of your sections depend on it). Don't edit around it. The owner accepts and emits a change, or declines with a reason. If you still disagree, tell the lead, who asks the user.
- A change to a foundation fact goes to the lead as a change request. Only the user can approve it.

## Change events
After you change a fact you own that another doc may use (a rename, an added or removed field or operation, changed behaviour, a decision):
1. Push the change.
2. `python3 SYNCPY SYNC emit --from STAGE --kind <rename|add|remove|change|decision> --subject "<fact>" --change "<before → after>" --reason "<PR comment or request>"`. By default every open phase-2 stage is notified; narrow it with `--affects` only when you are sure.
3. Message each notified writer and `design-sync` with the CHG id, in one line.

Changes inside your own doc that no one else uses are not events. Don't emit them.

When you receive a CHG id:
1. If it comes from `brief` or `requirements`, first `git fetch origin && git merge origin/main` in your worktree. Then re-read your doc against it.
2. Ack it, within your current task:
   - `--status fixed --note <sha>` after pushing the fix
   - `--status n/a --note "<why not affected>"`
   - `--status objects --note "<reason>"`, then message the emitter and the lead
3. A fix may change a fact you own. Then you emit your own CHG. That is how a change ripples through the docs.

`python3 SYNCPY SYNC pending --stage STAGE` lists what you still owe (`ACK`) and what others still owe on your changes (`WAIT`). Run it before you tell anyone your PR is ready.

## ADRs
Reserve the number first: `python3 SYNCPY SYNC adr --stage STAGE --title "<imperative title>"` prints the path. Write it from `SKILL/references/adr-template.md` with status `proposed`. The user's approval of your PR accepts it.

## PR ready for the user
A PR is ready when all of these hold:
- the template's exit checklist passes
- no `ASSUMES(...)` markers are left
- `design-critic` has no open `blocking` finding
- `pending` prints `CLEAR`

Then mark it ready (`gh pr ready`), set `sync.py stage STAGE review`, and tell the lead and `pr-watcher`. The user approves and merges. Never merge, never push to `main`.

## Loops and caps
- The same fact changed back and forth twice: stop and tell the lead. The user decides, and the decision becomes an ADR.
- More than 3 fix rounds on one PR thread: the watcher asks the user (existing pr-watcher cap).
