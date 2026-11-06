export const meta = {
  name: 'feature-design-stage',
  description: 'feature-design: bach:design-drafter writes or revises the focus stage doc from its template, then design critic + consistency check in parallel',
  whenToUse: 'Launched by the feature-design lead in the background right after the previous stage is approved, and once per revision round',
  phases: [
    { title: 'Survey', detail: 'research stage only: nested bach:web-research (quick) + Opus low codebase survey, in parallel', model: 'opus' },
    { title: 'Draft', detail: 'bach:design-drafter (Opus low): write or revise the stage doc', model: 'opus' },
    { title: 'Review', detail: 'bach:design-critic (Opus medium) + Sonnet low consistency check, in parallel', model: 'opus' },
  ],
}

const A = args || {}
const RUN = A.run_dir, SKILL = A.skill_dir, AGENTS = A.agents_dir
if (!RUN || !SKILL || !AGENTS || !A.stage) throw new Error('args need run_dir, skill_dir, agents_dir, stage')

const STAGES = {
  research: { doc: '01-research.md', ref: 'stage-1-research.md', up: ['00-brief.md'] },
  requirements: { doc: '02-requirements.md', ref: 'stage-2-requirements.md', up: ['00-brief.md', '01-research.md'] },
  'data-model': { doc: '03-data-model.md', ref: 'stage-3-data-model.md', up: ['00-brief.md', '01-research.md', '02-requirements.md'] },
  api: { doc: '04-api.md', ref: 'stage-4-api.md', up: ['00-brief.md', '02-requirements.md', '03-data-model.md'] },
  ui: { doc: '05-ui.md', ref: 'stage-5-ui.md', up: ['00-brief.md', '02-requirements.md', '04-api.md'] },
  backend: { doc: '06-backend.md', ref: 'stage-6-backend.md', up: ['00-brief.md', '02-requirements.md', '03-data-model.md', '04-api.md', '05-ui.md'] },
  design: { doc: 'design.md', ref: 'stage-7-design.md', up: ['00-brief.md', '01-research.md', '02-requirements.md', '03-data-model.md', '04-api.md', '05-ui.md', '06-backend.md'] },
}
const S = STAGES[A.stage]
if (!S) throw new Error(`unknown stage ${A.stage}`)
const DOC = `${RUN}/${S.doc}`

const CTX = `Feature design run folder: ${RUN}. Target repo: ${A.repo || '.'}
- Stage: ${A.stage} → ${DOC}. Template and exit checklist (follow exactly): ${SKILL}/references/${S.ref}
- Approved upstream docs (read the ones that exist; a missing one was skipped): ${S.up.map((d) => `${RUN}/${d}`).join(', ')}
- Glossary: the Glossary section of ${RUN}/00-brief.md. Use its terms only, never synonyms.
- Decisions: ADRs in ${A.adr_dir || `${RUN}/adr`}. Link to them; don't re-argue a decided question.
- Repo canonical docs (CLAUDE.md, AGENTS.md, README, docs/, existing ADRs) override general best practice. Follow the conventions of the existing code.
Stay at design altitude: no implementation code; pseudo-code only for a novel algorithm.`

const QUESTION = { type: 'object', properties: {
  question: { type: 'string' }, header: { type: 'string' },
  options: { type: 'array', items: { type: 'object', properties: { label: { type: 'string' }, description: { type: 'string' } }, required: ['label', 'description'] } } },
  required: ['question', 'header', 'options'] }
const DRAFT = { type: 'object', properties: {
  summary: { type: 'string' },
  changes: { type: 'array', items: { type: 'string' } },
  open_questions: { type: 'array', items: QUESTION },
  adr_candidates: { type: 'array', items: { type: 'object', properties: {
    title: { type: 'string' }, options: { type: 'array', items: { type: 'string' } }, recommended: { type: 'string' }, why: { type: 'string' } },
    required: ['title', 'options', 'recommended', 'why'] } },
  unfilled: { type: 'array', items: { type: 'string' } } },
  required: ['summary', 'open_questions', 'adr_candidates'] }
const REVIEW = { type: 'object', properties: {
  verdict: { type: 'string', enum: ['APPROVE', 'APPROVE WITH CHANGES', 'REVISE'] },
  new_information: { type: 'boolean' },
  findings: { type: 'array', items: { type: 'object', properties: {
    severity: { type: 'string', enum: ['blocking', 'issue', 'suggestion'] }, where: { type: 'string' },
    finding: { type: 'string' }, failure_scenario: { type: 'string' }, fix: { type: 'string' } },
    required: ['severity', 'where', 'finding', 'fix'] } } },
  required: ['verdict', 'findings'] }
const ISSUES = { type: 'object', properties: { issues: { type: 'array', items: { type: 'object', properties: {
  kind: { type: 'string', enum: ['term', 'id', 'contradiction', 'missing-trace'] }, where: { type: 'string' }, issue: { type: 'string' } },
  required: ['kind', 'where', 'issue'] } } }, required: ['issues'] }

async function survey() {
  phase('Survey')
  const web = async () => {
    if (!A.web_research) { log('web-research skipped (no args)'); return null }
    try {
      return await workflow({ scriptPath: A.web_research.script_path }, A.web_research.args)
    } catch (e) {
      log(`web-research failed: ${e}`)
      return { error: String(e) }
    }
  }
  const code = () => agent(`${CTX}\n\nSurvey the target repo for this feature (brief: ${RUN}/00-brief.md). Find: how the job is done today (flow, step by step), the modules, data and contracts involved, pieces we can reuse, constraints and debt, and the repo's conventions for API, schema, layering, tests and docs.
Cite path:line for every claim. Write ${RUN}/research/codebase.md, then list the folder to check the file exists. Return "ok" only if it does, otherwise the error.`,
    { label: 'codebase survey', phase: 'Survey', model: 'opus', effort: 'low' })
  const [w] = await parallel([web, code])
  return w
}

let wr = null
if (A.stage === 'research' && !A.revise) wr = await survey()

phase('Draft')
const sources = A.stage === 'research'
  ? `\n- Codebase survey: ${RUN}/research/codebase.md · Web research: ${A.wr_run_dir || 'none'} (report.md, analysis_*.csv, notes/<sid>.json; cite claims as [sid])`
  : ''
const extra = A.stage === 'ui' ? `\n- Reference screenshots: ${RUN}/refs/ (if any)`
  : A.stage === 'design' ? `\n- Also write ${RUN}/roadmap.md in the format the template gives. Skipped stages are listed in the brief's Stages table.` : ''
const RETURN_NEW = `Return {summary (≤5 lines), open_questions (≤6, the ones that change the design; each with 2–4 concrete options, first one the evidence favours, label ≤5 words, header ≤12 chars), adr_candidates (significant, costly-to-reverse choices that had a real alternative), unfilled (template sections left TBD)}.`
const task = A.revise
  ? `Revise ${DOC}. Read it first: the user may have edited it, and the user's edits win; never revert them.
Apply the user's feedback in ${A.feedback_file} and the review findings it accepts. Edit only the sections they name. The reviewers' full findings were:
${A.previous_review || '(none passed)'}
${A.previous_consistency ? `Consistency issues: ${A.previous_consistency}
` : ''}Change only what they require.
Return {summary, changes (one line each), open_questions (still unresolved), adr_candidates (new ones only), unfilled}.`
  : `Write ${DOC} by filling the template completely. Where facts are missing, write "TBD: <question>" and add the question to open_questions instead of guessing.
${RETURN_NEW}`
async function drafter() {
  const ask = `${CTX}${sources}${extra}\n\n${task}`
  const opts = { label: `${A.revise ? 'revise' : 'draft'} ${A.stage}`, phase: 'Draft', model: 'opus', effort: 'low', schema: DRAFT }
  try {
    return await agent(ask, { ...opts, agentType: 'bach:design-drafter' })
  } catch (e) {
    log(`design-drafter agent type unavailable (${e}); using the role file inline`)
    return agent(`First read ${AGENTS}/design-drafter.md and follow it as your role.\n\n${ask}`, opts)
  }
}
const draft = await drafter()

phase('Review')
const reviewAsk = `${CTX}\n\nReview ${DOC} for the ${A.stage} stage. Check every item of the exit checklist in the template file, traceability to the upstream docs, and plausible failure modes.` +
  (A.revise && A.previous_review ? `\nThis is a re-review. Your previous findings: ${A.previous_review}. The user's response: ${A.feedback_file}. Keep a finding unless the doc now fixes it or the user brought new information; set new_information accordingly.` : '') +
  `\nChange nothing. Return {verdict, new_information, findings}.`
async function critic() {
  try {
    return await agent(reviewAsk, { label: 'design critic', phase: 'Review', agentType: 'bach:design-critic', model: 'opus', effort: 'medium', schema: REVIEW })
  } catch (e) {
    log(`design-critic agent type unavailable (${e}); using the role file inline`)
    return agent(`First read ${AGENTS}/design-critic.md and follow it as your role.\n\n${reviewAsk}`,
      { label: 'design critic (inline)', phase: 'Review', model: 'opus', effort: 'medium', schema: REVIEW })
  }
}
const [review, consistency] = await parallel([
  critic,
  () => agent(`${CTX}\n\nCheck ${DOC} against the upstream docs and the glossary. Report only: terms not in the glossary or synonyms of glossary terms (term), ids referenced but not defined upstream (id), names, types or behaviour that contradict an upstream doc (contradiction), upstream UC/AC/NFR ids this stage should cover but doesn't (missing-trace). Change nothing.`,
    { label: 'consistency', phase: 'Review', model: 'sonnet', effort: 'low', schema: ISSUES }),
])

return { stage: A.stage, doc: DOC, web_research: wr, draft, review, consistency }
