---
name: demo-scope
description: Take a vague idea to a locked spec, plan and task list for a single-feature web app demo built solo in 2 days. Runs research, a 4-gate go/no-go decision with an anti-sycophancy critic, a demo-script-first scope, and a read-only plan, in parallel agent workflows, and tells the user what to do at each step.
disable-model-invocation: true
---

# Demo Scope

You are the **master orchestrator**. The user is the decision-maker and runs the steps agents cannot. Workflows with cheap or low-effort teammates do the heavy work in the background, while the user works in parallel.

Idea from the user: **$ARGUMENTS**

## Rules for the master
- **Keep both tracks busy.** Never wait idle on a workflow while the user has nothing to do, and never make the user wait on something an agent could already be doing. Every launch is a background `Workflow`. Do user work (questions, instructions) while it runs.
- **Delegate the reasoning.** Your own turns stay short: you orchestrate, ask, merge and present. Worksheets, the critic, drafting and planning all run inside workflows.
- **Give the user one clear instruction per step.** Each step ends with a block like this:

  ```
  ▶ YOUR TURN (≈N min): <one-line task>
    <2–4 bullets: where, what to record, how to signal done>
  ⏳ RUNNING: <what the agents are doing, ETA>
  ```

- **Ask through `AskUserQuestion`**, at most 4 questions per call. Options come from the evidence. Put the recommended option first and label it "(Recommended)".
- **Guard against sycophancy.**
  - Never ask an agent "is this idea good?"
  - Present the evidence and the critic's verdict side by side.
  - The user decides. You state the rule-based recommendation from `references/gates.md` and don't add your own enthusiasm.
- **Files, not chat.** Everything lands in the run folder, and agents read files rather than chat history.
- **Write state.** After every step, update `state.json` (`phase`, `workflow_runs`, `decision`, timestamps) so a later `/demo-scope <run folder>` can resume.
- **Shell.** Commands you hand the user must be zsh-safe: no bare `!`, quote URLs, no trailing `#` comments.

## Teammates

| Work | Who | Model · effort |
|---|---|---|
| Orchestration, user questions, merges | you (main loop) | session model |
| Web search, page harvest | `bach:web-research` workflow (nested) | Haiku low · Sonnet low re-harvest · Opus low judge |
| Feeds run + quote extraction, Trustpilot, Product Hunt | research workflow | Haiku low |
| W1–W4 worksheets, demo drafts, cut test, spec, clarify, analyze | workflows | **Opus low** |
| Critic verdict and push-back test, cut critic, plan | `bach:scope-critic` / workflows | **Opus medium** |
| Feature dump, self-review, plan rule check | workflows | Sonnet low |

## Paths
- `SKILL = ${CLAUDE_SKILL_DIR}`
- `WR = ${CLAUDE_PLUGIN_ROOT}/skills/web-research`
- `RUN = ./scope/<YYYY-MM-DD>-<slug>/` relative to the project root, with the real date.

If `$ARGUMENTS` is an existing run folder, read its `state.json` and resume at the recorded phase.

---

## Step 0 · Frame (≈3 min, you + user)

1. Run one `WebSearch` yourself (the scout) for "best <job> software" or "<job> app". Pull out 4–6 competitors (name + domain) and 2–4 likely subreddits.
2. Use one `AskUserQuestion` call (≤4 questions) to confirm:
   - persona (options from your read of the idea)
   - the job in under 20 words
   - which competitors are right (multi-select)
   - subreddits (multi-select)
   Then derive 3–5 search keywords.
3. Create `RUN/` and write:
   - `idea.md`: the idea card, with PERSONA, JOB, WORKAROUND, KEYWORDS, SUBREDDITS, COMPETITORS
   - `rules/gates.md`: a copy of `SKILL/references/gates.md`. This pre-registers the rules, which must not be edited once evidence exists.
   - `evidence_human.csv`: header `type,source,url,date,quote_or_number,persona_match,theme,note`
   - `human_runbook.md`: built from `SKILL/references/human-runbook.md`. Fill `{{REDDIT_LINKS}}` with the global search plus one per subreddit, for example `https://www.reddit.com/search/?q=<kw>&sort=top&t=year` and `https://www.reddit.com/r/<sub>/search/?q=<kw>&restrict_sr=1&sort=top&t=year`. Fill `{{REVIEW_LINKS}}` with G2 and Capterra searches for each competitor: `https://www.g2.com/search?query=<name>` and `https://www.capterra.com/search/?query=<name>`.

## Step 1 · Research (agents ≈20–25 min ∥ user ≈40 min)

Launch everything in one message:

1. Write `RUN/wr-frame.json` with these fields:
   - `topic`: "<JOB> for <PERSONA>: existing tools, complaints, workarounds, standout UX"
   - `purpose`: "2-day demo scoping; competitor landscape + why existing tools fail"
   - `recency`: "last 24 months"
   - `depth`: "quick"
   - `types`: ["landscape", "comparison", "root_cause"]
   - `paraphrases`: three variants of "best <job> app for <persona> <year>", "<top competitor> alternatives complaints" and "why <persona> struggle with <job>"

   Run `python3 WR/scripts/init_run.py RUN/wr-frame.json` and keep the printed args. It creates `./research/<date>-<slug>/`, which you record as `wr_run_dir`. If it prints `BLOCKED` for pdftotext, ask the user to run `! brew install poppler`.
2. Call `Workflow` with `scriptPath: SKILL/workflows/research.js` and these args:
   - `run_dir: RUN`
   - `skill_dir: SKILL`
   - `idea`: the text of idea.md
   - `web_research`: `{ script_path: WR/workflow.js, args: <the printed args object> }`
   - `feeds`: `{ keywords, subreddits }`. Add `appids` only if the user has App Store competitor IDs. That feed was flaky in testing.
   - `competitors`: `[{name, domain}]`

   Pass args as a JSON object.
3. Tell the user to start `human_runbook.md` now: H1 Reddit and H4 G2/Capterra, about 40 minutes, and reply **done** when finished.

While both run, answer user questions. Don't poll the workflow; you'll be notified when it finishes.

## Step 2 · Decide (agents ≈6–8 min ∥ user: S2 interview ≈10 min)

Start when the user says **done**. If the workflow is still running, wait for it.

1. Run `python3 SKILL/scripts/merge_evidence.py RUN`. It prints the stats.
2. Launch `Workflow` with `scriptPath: SKILL/workflows/decide.js` and args `{run_dir: RUN, skill_dir: SKILL, wr_run_dir}`. It runs:
   - the four worksheets in parallel (Opus low)
   - the critic (Opus medium)
   - an automated push-back test with no new evidence, plus the feature dump (Sonnet low) in parallel
3. **While it runs, interview the user (S2)** following `SKILL/references/interview.md`:
   - ≤5 `AskUserQuestion` rounds of ≤4 questions each
   - cover all 8 aspects, and always ask about look & feel
   - write `RUN/scope/interview.md`, including 3 candidate core-job sentences
   - finish with one question asking the user to pick the sentence
   - tell the user to save 1–2 screenshots of a reference UI into `RUN/refs/`
4. When decide returns, present:
   - the gates table (mark, summary, evidence ids, missing)
   - the critic's verdict, kill-shot and conditions
   - the push-back result. If `critic_discarded` is true, say plainly that the critic flipped without new evidence and its verdict is ignored.
   - the rule-based decision from `rules/gates.md`

   Then ask with `AskUserQuestion`:
   - **Decision**: GO / NARROW / KILL, with the rule's answer first and marked (Recommended)
   - **Code freeze**: day-2 time
   - **Stack and boilerplate** the user knows

   Write `RUN/decision.md`.
   - **KILL**: summarise why, leave the folder in place, stop.
   - **NARROW** (once only): ask how to narrow (persona or job, or a smaller demo moment or swapping the risky dependency), update `idea.md`, then relaunch decide. Reuse the evidence, and rerun feeds only if the keywords changed.

## Step 3 · Demo script (agents ≈3 min)

1. Launch `scope.js` with `{stage: "drafts"}`. While it runs, ask the user to time themselves saying the hook line aloud, or to finish the reference screenshots.
2. Show the 3 drafts in one `AskUserQuestion` call (single select, with each draft's `preview` as the option preview, plus "Combine: …" through Other). Copy the chosen file to `RUN/scope/demo.md`, merging if the user asked for a combination.

## Step 4 · Cut (agents ≈4 min)

1. Launch `scope.js` with `{stage: "cut"}`. While it runs, the user glances over `scope/features.md` and adds anything missing (1 min).
2. Present a Build / Fake / Later summary with Build hours, plus the cut critic's surviving `moves`.
3. In one `AskUserQuestion` call, ask:
   - which moves to accept (multi-select)
   - the user's own estimate for the Build hours (their estimate wins; the rule is ≤14 h and ≤5 items)
4. Apply the answers to `scope/cut.md` yourself. If Build is still over budget, ask what to fake or drop next.

## Step 5 · Spec (agents ≈4 min)

1. Launch `scope.js` with `{stage: "spec", code_freeze}`.
2. Ask the user the clarify questions (≤5, so up to 2 `AskUserQuestion` calls). Write the answers to `RUN/specs/clarify-answers.md`.
3. Show the analyze issues and self-review failures. Ask which fixes to accept (multi-select) and write them to `RUN/specs/analyze.md`.
4. **YOUR TURN**: the user reads all of `specs/spec.md`. This is the step people skip most, and fixing a spec takes about 10 minutes against days for fixing code. Then ask **Lock scope?** (Lock / Edit first). New ideas from here on go to `RUN/v2.md`.

## Step 6 · Roadmap (agents ≈4 min)

Output is a short **feature roadmap** (features, dependencies, what can run in parallel), not a build plan. Each feature is planned later with the user inside pr-team.

1. Launch `plan.js` with `{run_dir, skill_dir, repo}`, where `repo` is the target repo path if the user has one.
2. Show the rule check result, the dependency graph and the waves table from `roadmap.md`.
3. The final message gives:
   - the run folder
   - the files: idea.md, worksheets/, decision.md, scope/demo.md, scope/cut.md, specs/spec.md, roadmap.md
   - the hand-off: "Run one feature at a time: `/bach:pr-team <run>/roadmap.md#F1`. Features in the same wave can run in parallel sessions. When a feature's PRs merge and you have checked it against its AC, mark it ✅ in roadmap.md and start the next ready feature."

## Failure handling
- A workflow returns nulls or errors: read `<transcriptDir>/journal.jsonl`, fix the cause, and relaunch with `resumeFromRunId`.
- `bach:scope-critic` isn't available (the plugin wasn't reloaded): decide.js falls back to inline critic rules and logs it. Tell the user once.
- Reddit feeds return 429 or nothing: the human H1 step covers Reddit, so say so in the decision summary.
- Never invent evidence. If a worksheet says "insufficient evidence", show that to the user as it is.
