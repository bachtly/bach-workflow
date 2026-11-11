# pr-team: rules every teammate follows

Builders, reviewers and the watcher read this once at spawn (`RULES` in the spawn prompt). The lead's `SKILL.md` points here instead of repeating it.

## Messages: the lead's attention is the team's budget
Every message to the lead, and every time a teammate ends its turn, wakes the lead, and each wake re-reads the lead's whole context.

- **Scripts replace routine messages.** `RUN_PY pr` records a PR, `RUN_PY lesson` a lesson, `RUN_PY note` an event, `RUN_PY scope` checks scope. Do what a script's `next:` line says, nothing more.
- **Your final answer is your report.** When a teammate ends its turn, the lead is notified and the notification carries the final answer. So put the news in the final answer, one line, and don't also SendMessage the lead the same thing.
- **One message per event**, one or two lines. No acknowledgements, no "already done", no "PR body already updated", no repeats.
- **Ask once.** A scope or design answer from the lead is recorded in `## Decisions` of `PLAN`. Read that section before asking, and never ask the same question twice.
- **Talk to the owner directly.** Reviewer ↔ builder and watcher ↔ builder talk without the lead.

## Lessons
Record a lesson with `python3 RUN_PY --plan PLAN lesson "[<folder>|all] <rule> — PR #n" --by <your name>`. It goes into `## Lessons` of `PLAN` (exact repeats dropped). Never edit `## Lessons` by hand.

A lesson must pass all four:
1. It is a rule for future PRs, not a fix for this one.
2. It is checkable on a diff.
3. It came from a human comment or a reviewer blocker.
4. The repo's `CLAUDE.md`, a linter or a test doesn't already enforce it.

Use `[all]` unless the rule is truly about one folder. Typos and one-off nits are never lessons.
