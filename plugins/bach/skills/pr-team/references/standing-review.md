# pr-team: standing review mode (opt-in)

Used only when `plan.md` has `Review: standing` (the user asked for it). The default is on-demand review: a short-lived `reviewer-pr<N>` per big PR (`SKILL.md` Step 4). Everything about standing mode lives in this file.

## Lead
- **Team.** 1 `reviewer-<n>` (`bach:pr-reviewer`) per 3–4 builders. Reviewer prompt: its name, the repo root, `review: standing`, `PLAN=`, `RUN_PY=`, `RULES=`, `STANDING=<this file>`. Each builder's prompt names its reviewer.
- **Retire.** A reviewer ends its turn with `retire` after 4 PRs. Replace it like a builder (`SKILL.md` Step 3, `retire` row).
- Reviewers never message you about routine reviews; they talk to builders directly.

## Builder
`RUN_PY pr` prints `next: SendMessage your reviewer PR #<n> ready`. Send that to the reviewer named in your spawn prompt, then claim your next task. A blocker from the reviewer takes priority, as in on-demand mode.

## Reviewer
Builders message you `PR #n ready`. For each one:
1. Read the task (the PR body) and the diff (only the source and test files; see "Keep your context small" in your agent file). Read surrounding code when the diff alone can't tell you.
2. Post inline comments (`gh api` review comments, or `gh pr review <n> --comment`) only for blockers:
   - broken behaviour or a failing acceptance criterion
   - security or data-loss risk
   - missing or wrong tests for the changed behaviour
   - scope leak: files outside the task's folder, or more than one intent
   - a UI change with neither `## Screenshots` nor `visual: trivial` in the PR body
   - a PR that can't merge on its own (depends on another open PR, unflagged partial feature)
3. UI or interactive change with `## Screenshots`: download each image (`curl -sL -H "Authorization: token $(gh auth token)" -o <file> <url>`) and open it with Read. An image that doesn't show what its caption or the acceptance criteria say is a `nit:`. If an image won't download or open, say so in the summary comment.
4. Put up to 5 nits in one summary comment labelled `nit:`. Don't comment on style that a linter would catch. No finding? Post a one-line `pre-review: no blockers` comment so the human knows it ran.
5. Message the owning builder for each blocker. The watcher sees your review on GitHub; don't message it.

Re-review only when the watcher or the owning builder says a fix was pushed (`fix pushed <sha>`), and only the threads you opened.

After your 4th finished PR, finish any re-check you owe, then end your turn with the final answer `retire`. A fresh reviewer of the same name takes over, so no review re-reads all the earlier ones.

Never approve, request changes as a merge gate, or merge. Comment reviews only. The human owns approval.
