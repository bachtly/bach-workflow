export const meta = {
  name: 'demo-scope-scope',
  description: 'demo-scope Phase C: demo-script drafts, cut test + adversarial cut critic, spec + clarify/analyze/self-review (stage chosen by args.stage)',
  whenToUse: 'Invoked by the demo-scope skill between user checkpoints of the Scope phase',
  phases: [
    { title: 'Drafts', detail: 'Opus low x3: demo script from three angles', model: 'opus' },
    { title: 'Cut', detail: 'Opus low cut test + fakes + hours; Opus medium adversarial cut critic', model: 'opus' },
    { title: 'Spec', detail: 'Opus low spec writer; then clarify + analyze (Opus low) and self-review (Sonnet low) in parallel', model: 'opus' },
  ],
}

const A = args || {}
const RUN = A.run_dir, SKILL = A.skill_dir
if (!RUN || !SKILL || !A.stage) throw new Error('args need run_dir, skill_dir, stage')

const CTX = `Files:
- idea card: ${RUN}/idea.md · core job + interview notes: ${RUN}/scope/interview.md
- worksheets: ${RUN}/worksheets/W1.md .. W4.md · decision: ${RUN}/decision.md
- evidence: ${RUN}/evidence.csv · Product Hunt refs: ${RUN}/refs/producthunt.md
- scope rules (follow exactly): ${SKILL}/references/scope-rules.md
Demo type is fixed: single-feature web app, built solo in 2 days.`

const DRAFT = {
  type: 'object',
  properties: {
    angle: { type: 'string' },
    beats: { type: 'array', items: { type: 'object', properties: { beat: { type: 'string' }, seconds: { type: 'integer' }, script: { type: 'string' } }, required: ['beat', 'seconds', 'script'] } },
    preview: { type: 'string' },
  },
  required: ['angle', 'beats', 'preview'],
}
const CUT = {
  type: 'object',
  properties: {
    items: { type: 'array', items: { type: 'object', properties: {
      feature: { type: 'string' }, column: { type: 'string', enum: ['Build', 'Fake', 'Later'] }, rule: { type: 'string' },
      reason: { type: 'string' }, beat: { type: 'string' }, hours: { type: 'number' }, fake_method: { type: 'string' } },
      required: ['feature', 'column', 'reason'] } },
    build_hours: { type: 'number' },
  },
  required: ['items'],
}
const CHALLENGE = {
  type: 'object',
  properties: { challenges: { type: 'array', items: { type: 'object', properties: {
    feature: { type: 'string' }, move_to: { type: 'string', enum: ['Fake', 'Later', 'keep'] }, argument: { type: 'string' }, survives_demo_script: { type: 'boolean' } },
    required: ['feature', 'move_to', 'argument', 'survives_demo_script'] } } },
  required: ['challenges'],
}
const QUESTIONS = {
  type: 'object',
  properties: { questions: { type: 'array', items: { type: 'object', properties: {
    question: { type: 'string' }, header: { type: 'string' },
    options: { type: 'array', items: { type: 'object', properties: { label: { type: 'string' }, description: { type: 'string' } }, required: ['label', 'description'] } } },
    required: ['question', 'header', 'options'] } } },
  required: ['questions'],
}
const ISSUES = {
  type: 'object',
  properties: { issues: { type: 'array', items: { type: 'object', properties: { severity: { type: 'string', enum: ['blocker', 'fix', 'note'] }, issue: { type: 'string' }, where: { type: 'string' } }, required: ['severity', 'issue'] } } },
  required: ['issues'],
}
const CHECKS = {
  type: 'object',
  properties: { checks: { type: 'array', items: { type: 'object', properties: { check: { type: 'string' }, pass: { type: 'boolean' }, why: { type: 'string' } }, required: ['check', 'pass'] } } },
  required: ['checks'],
}

if (A.stage === 'drafts') {
  phase('Drafts')
  const ANGLES = [
    { id: 'pain-first', hint: 'open on the most painful real quote; the wow resolves exactly that pain' },
    { id: 'wow-first', hint: 'open by flashing the end result, then rewind to show how it was produced' },
    { id: 'contrast-first', hint: 'run the competitor/manual way side by side with the app on the same input' },
  ]
  const drafts = await parallel(ANGLES.map((g) => () => agent(
    `${CTX}\n\nDraft the 5-beat demo script (≤120 s total) from the "${g.id}" angle: ${g.hint}.
Use a real W1 quote (with evidence id) for the hook. Beat 3 must be ONE core action of the single feature. Beat 4 must be visible on screen.
Write ${RUN}/scope/demo-${g.id}.md. Return {angle:"${g.id}", beats, preview} where preview is the whole script as ≤12 short lines for a side-by-side comparison.`,
    { label: g.id, phase: 'Drafts', model: 'opus', effort: 'low', schema: DRAFT })))
  return { drafts: drafts.filter(Boolean) }
}

if (A.stage === 'cut') {
  phase('Cut')
  const cut = await agent(`${CTX}\n- chosen demo script: ${RUN}/scope/demo.md · feature list: ${RUN}/scope/features.md\n
Apply the cut test in scope-rules.md to EVERY feature in features.md, in rule order. For Build items: the demo beat it appears in and an hour estimate. For Fake items: the fake method from the table.
First passes over-classify Build: be strict. Write ${RUN}/scope/cut.md as a table (feature | column | rule | reason | beat | hours | fake method) plus totals.
Return {items, build_hours}.`, { label: 'cut test', phase: 'Cut', model: 'opus', effort: 'low', schema: CUT })
  const build = ((cut && cut.items) || []).filter((i) => i.column === 'Build')
  const ch = build.length ? await agent(`${CTX}\n- chosen demo script: ${RUN}/scope/demo.md · cut table: ${RUN}/scope/cut.md\n
You are an adversarial scope critic. For EACH Build item argue why it could be Fake or Later instead. Then test your own argument against the demo script:
survives_demo_script=true only if beats 3 and 4 still work and still look real with your change. Do not soften.
Build items: ${build.map((b) => b.feature).join(' | ')}`, { label: 'cut critic', phase: 'Cut', model: 'opus', effort: 'medium', schema: CHALLENGE }) : { challenges: [] }
  const moves = ((ch && ch.challenges) || []).filter((c) => c.survives_demo_script && c.move_to !== 'keep')
  return { cut, moves, build_hours: cut && cut.build_hours }
}

if (A.stage === 'spec') {
  phase('Spec')
  const written = await agent(`${CTX}\n- chosen demo script: ${RUN}/scope/demo.md · final cut: ${RUN}/scope/cut.md · template: ${SKILL}/references/spec-template.md\n
Write ${RUN}/specs/spec.md by filling the template completely from these files. Build table: ≤5 items, ≤6 acceptance criteria each (testable, on the demo path). Later list ≥8 items. Include the look & feel notes from interview.md.
Code freeze: ${A.code_freeze || '<ask user>'}. Return "ok" or the list of template fields you could not fill.`,
    { label: 'spec writer', phase: 'Spec', model: 'opus', effort: 'low' })
  const SPEC = `${CTX}\n- spec: ${RUN}/specs/spec.md (written: ${String(written).slice(0, 200)})`
  const [clarify, analyze, review] = await parallel([
    () => agent(`${SPEC}\n\nList ambiguities and edge cases ON THE DEMO PATH ONLY that would change what gets built. Turn the most important (max 5) into questions for the user, each with 2-4 concrete options (label ≤5 words, one-line description), first option the one the evidence favours. header ≤12 chars. Change nothing.`,
      { label: 'clarify', phase: 'Spec', model: 'opus', effort: 'low', schema: QUESTIONS }),
    () => agent(`${SPEC}\n\nAnalyze consistency across spec.md, demo.md and cut.md: contradictions, Build items not shown in any beat, beats needing something not in Build or Fake, acceptance criteria that are not testable, hours over budget. Change nothing.`,
      { label: 'analyze', phase: 'Spec', model: 'opus', effort: 'low', schema: ISSUES }),
    () => agent(`${SPEC}\n\nRun the self-review list in scope-rules.md against spec.md. One entry per check with pass true/false and why. Change nothing.`,
      { label: 'self-review', phase: 'Spec', model: 'sonnet', effort: 'low', schema: CHECKS }),
  ])
  return { written, clarify, analyze, review }
}

throw new Error(`unknown stage ${A.stage}`)
