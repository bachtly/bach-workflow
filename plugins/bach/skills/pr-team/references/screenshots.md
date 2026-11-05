# Screenshots in the PR description

For UI or interactive changes. The human should see the change without checking out the branch. Images are uploaded with `gh --attach` (gh 2.102.0 or later), so nothing is committed.

1. Start the app using only the ports and databases your spawn prompt or the repo's CLAUDE.md gives you, never another agent's.
2. Drive the flow with the repo's own UI tooling (see its CLAUDE.md or test setup). Save one PNG per key step outside the worktree, e.g. `../shots-<task-id>/<step>.png`.
3. Open each PNG with Read and check it shows what the acceptance criteria say. Re-shoot if not.
4. In the PR body, add `## Screenshots` with one `![<caption>](<step>.png)` line per step, then pass each file to `gh pr create` with `--attach <dir>/<step>.png`. gh uploads them and rewrites the references to the uploaded URLs.
5. After a fix that changes the UI, re-shoot and run `gh pr edit <n> --body-file <body> --attach ...` with the same references.
6. Stop any server you started and delete the shots folder.

Small visual tweaks (copy, spacing, one colour) don't need screenshots: write `visual: trivial` in the PR body instead.
