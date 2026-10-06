export const meta = {
  name: 'demo-scope-plan',
  description: 'demo-scope Phase D: apply clarify answers, feature roadmap with dependency waves (Opus medium), rule check, one fix round',
  whenToUse: 'Invoked by the demo-scope skill after the user answers clarify questions and locks scope',
  phases: [
    { title: 'Finalize spec', detail: 'Opus low: apply clarify answers and analyze fixes to spec.md', model: 'opus' },
    { title: 'Roadmap', detail: 'Opus medium: roadmap.md (features, deps, parallel waves), no tasks', model: 'opus' },
    { title: 'Check', detail: 'Sonnet low rule check; Opus low fix round if needed', model: 'sonnet' },
  ],
}

const A = args || {}
const RUN = A.run_dir, SKILL = A.skill_dir
if (!RUN || !SKILL) throw new Error('args need run_dir, skill_dir')

const RESULT = {
  type: 'object',
  properties: { ok: { type: 'boolean' }, problems: { type: 'array', items: { type: 'string' } }, features: { type: 'integer' } },
  required: ['ok', 'problems'],
}

phase('Finalize spec')
await agent(`Update ${RUN}/specs/spec.md using the user's answers in ${RUN}/specs/clarify-answers.md and the accepted fixes in ${RUN}/specs/analyze.md.
Keep the template structure. Do not add scope: anything new goes to the Later list or ${RUN}/v2.md. Return "ok".`,
  { label: 'apply answers', phase: 'Finalize spec', model: 'opus', effort: 'low' })

phase('Roadmap')
const PLAN_RULES = `Goal: a short ROADMAP, not a build plan. Do not write code, tasks or schedules; the user plans each feature later together with pr-team.
Read specs/spec.md, ${RUN}/scope/demo.md, ${RUN}/scope/cut.md and, if present, the target repo's CLAUDE.md (${A.repo || 'none given'}).
The roadmap must make clear: which features exist (as many as the scope needs), what each depends on, and which can be built in parallel. Keep it brief; link to spec.md AC ids instead of repeating detail.
Format (SKILL.md and pr-team rely on it):
- One section per feature headed \`## F<n> · <name>\` (n = 1, 2, ...), each with: Status (⬜/✅), Depends on (F ids or none), AC ids, one-line goal.
- A Mermaid dependency graph of the F ids.
- A waves table: Wave | Features (features in one wave have no dependency on each other and can run in parallel).`
await agent(`${PLAN_RULES}\n\nWrite ${RUN}/roadmap.md. Return "ok".`,
  { label: 'roadmap', phase: 'Roadmap', model: 'opus', effort: 'medium' })

phase('Check')
let check = await agent(`Check ${RUN}/roadmap.md against ${RUN}/specs/spec.md and ${RUN}/scope/cut.md. Change nothing.\n${PLAN_RULES}\nFail only if a Build item from cut.md is missing, dependencies are unclear or contradictory, or parallel work is not visible. Return {ok, problems, features} where features = number of features.`,
  { label: 'rule check', phase: 'Check', model: 'sonnet', effort: 'low', schema: RESULT })
if (check && !check.ok) {
  await agent(`Fix these problems in ${RUN}/roadmap.md without adding scope:\n- ${check.problems.join('\n- ')}\n${PLAN_RULES}\nReturn "ok".`,
    { label: 'fix round', phase: 'Check', model: 'opus', effort: 'low' })
  check = await agent(`Re-check ${RUN}/roadmap.md against the rules below, ${RUN}/specs/spec.md and ${RUN}/scope/cut.md. Change nothing.\n${PLAN_RULES}\nReturn {ok, problems, features}.`,
    { label: 're-check', phase: 'Check', model: 'sonnet', effort: 'low', schema: RESULT })
}
return check
