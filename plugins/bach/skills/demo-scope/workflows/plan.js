export const meta = {
  name: 'demo-scope-plan',
  description: 'demo-scope Phase D: apply clarify answers, read-only plan + tasks (Opus medium), rule check, one fix round',
  whenToUse: 'Invoked by the demo-scope skill after the user answers clarify questions and locks scope',
  phases: [
    { title: 'Finalize spec', detail: 'Opus low: apply clarify answers and analyze fixes to spec.md', model: 'opus' },
    { title: 'Plan', detail: 'Opus medium: plan.md + tasks.md, no code', model: 'opus' },
    { title: 'Check', detail: 'Sonnet low rule check; Opus low fix round if needed', model: 'sonnet' },
  ],
}

const A = args || {}
const RUN = A.run_dir, SKILL = A.skill_dir
if (!RUN || !SKILL) throw new Error('args need run_dir, skill_dir')

const RESULT = {
  type: 'object',
  properties: { ok: { type: 'boolean' }, problems: { type: 'array', items: { type: 'string' } }, tasks: { type: 'integer' } },
  required: ['ok', 'problems'],
}

phase('Finalize spec')
await agent(`Update ${RUN}/specs/spec.md using the user's answers in ${RUN}/specs/clarify-answers.md and the accepted fixes in ${RUN}/specs/analyze.md.
Keep the template structure. Do not add scope: anything new goes to the Later list or ${RUN}/v2.md. Return "ok".`,
  { label: 'apply answers', phase: 'Finalize spec', model: 'opus', effort: 'low' })

phase('Plan')
const PLAN_RULES = `Rules:
- Do NOT write application code. Read only specs/spec.md, ${RUN}/scope/demo.md and, if present, the target repo's CLAUDE.md (${A.repo || 'none given'}).
- tasks ordered by demo beat as thin end-to-end vertical slices; end of day 1 = walking skeleton where every beat is clickable and deployed.
- Task 1 = 30-minute spike on the riskiest dependency named in spec.md, with its fallback.
- Each Build item keeps ≤6 acceptance criteria; split it otherwise.
- Include tasks for seeded demo data, the cached fallback, a "no secrets in client code" check, code freeze, 3 rehearsals and the backup video.
- Note any conflict between spec.md and CLAUDE.md.`
await agent(`${PLAN_RULES}\n\nWrite ${RUN}/plan.md (approach, day 1 / day 2 schedule with hours, risks) and ${RUN}/tasks.md (checkbox list, each task with beat, estimate, acceptance criteria ids). Return "ok".`,
  { label: 'plan', phase: 'Plan', model: 'opus', effort: 'medium' })

phase('Check')
let check = await agent(`Check ${RUN}/plan.md and ${RUN}/tasks.md against these rules and against ${RUN}/specs/spec.md. Change nothing.\n${PLAN_RULES}\nAlso fail if total estimated build hours exceed 14 for Build items or 24 overall. Return {ok, problems, tasks}.`,
  { label: 'rule check', phase: 'Check', model: 'sonnet', effort: 'low', schema: RESULT })
if (check && !check.ok) {
  await agent(`Fix these problems in ${RUN}/plan.md and ${RUN}/tasks.md without adding scope:\n- ${check.problems.join('\n- ')}\n${PLAN_RULES}\nReturn "ok".`,
    { label: 'fix round', phase: 'Check', model: 'opus', effort: 'low' })
  check = await agent(`Re-check ${RUN}/plan.md and ${RUN}/tasks.md against the rules below and ${RUN}/specs/spec.md. Change nothing.\n${PLAN_RULES}\nReturn {ok, problems, tasks}.`,
    { label: 're-check', phase: 'Check', model: 'sonnet', effort: 'low', schema: RESULT })
}
return check
