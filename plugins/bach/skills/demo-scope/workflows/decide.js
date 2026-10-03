export const meta = {
  name: 'demo-scope-decide',
  description: 'demo-scope Phase B: four worksheets in parallel, critic verdict, automated push-back test; feature dump in parallel',
  whenToUse: 'Invoked by the demo-scope skill after evidence.csv is merged',
  phases: [
    { title: 'Worksheets', detail: 'Opus low x4: W1 pain, W2 gap, W3 demo moment, W4 2-day build', model: 'opus' },
    { title: 'Critic', detail: 'bach:scope-critic (Opus medium) verdict, then a no-evidence push-back test', model: 'opus' },
    { title: 'Features', detail: 'Sonnet low: S4 feature dump from competitors and quotes', model: 'sonnet' },
  ],
}

const A = args || {}
const RUN = A.run_dir, SKILL = A.skill_dir, WR = A.wr_run_dir || ''
if (!RUN || !SKILL) throw new Error('args need run_dir, skill_dir')

const FILES = `Files:
- idea card: ${RUN}/idea.md
- rules (follow exactly): ${SKILL}/references/gates.md
- evidence: ${RUN}/evidence.csv and ${RUN}/evidence_stats.json
${WR ? `- web-research run: ${WR}/analysis_landscape.csv, ${WR}/analysis_comparison.csv, ${WR}/analysis_root_cause.csv, ${WR}/sources.csv` : ''}
- Product Hunt refs: ${RUN}/refs/producthunt.md (may be missing)`

const GATE = {
  type: 'object',
  properties: {
    gate: { type: 'string' },
    mark: { type: 'string', enum: ['pass', 'partial', 'fail'] },
    evidence_ids: { type: 'array', items: { type: 'string' } },
    summary: { type: 'string' },
    missing: { type: 'array', items: { type: 'string' } },
  },
  required: ['gate', 'mark', 'summary'],
}
const VERDICT = {
  type: 'object',
  properties: {
    lenses: { type: 'array', items: { type: 'object', properties: { lens: { type: 'string' }, score: { type: 'integer' }, why: { type: 'string' } }, required: ['lens', 'score', 'why'] } },
    kill_shot: { type: 'string' },
    verdict: { type: 'string', enum: ['GO', 'GO WITH CONDITIONS', 'NOT YET', 'NO-GO'] },
    conditions: { type: 'array', items: { type: 'string' } },
    new_evidence_presented: { type: 'boolean' },
  },
  required: ['lenses', 'kill_shot', 'verdict'],
}

const SHEETS = [
  { id: 'W1', name: 'G1 Pain', task: 'Merge near-duplicate themes, pick the top theme, count quotes and independent places from the evidence rows.' },
  { id: 'W2', name: 'G2 Gap', task: 'Build the competitor list, find the shared weakness across 1-3 star reviews and root causes, and write the "Unlike X..." sentence.' },
  { id: 'W3', name: 'G3 Demo moment', task: 'Write the before -> after line and judge visibility, time-to-wow and generic-AI-wrapper risk. Propose the strongest visible "wow" the evidence supports.' },
  { id: 'W4', name: 'G4 2-day build', task: 'List demo-path dependencies, rate each known / documented / risky, name the riskiest with a 30-minute spike and a fallback.' },
]

// Critic with system-prompt rules (plugin agent); falls back to an inline-rules agent if the type is unavailable.
async function critic(prompt, label) {
  let r = null
  try {
    r = await agent(prompt, { label, phase: 'Critic', agentType: 'bach:scope-critic', model: 'opus', effort: 'medium', schema: VERDICT })
  } catch (e) { log(`scope-critic agent type unavailable (${e}); using inline rules`) }
  if (r) return r
  return agent(`ROLE: devil's-advocate board. Judge only from evidence; cite ids; say "insufficient evidence" rather than guess. Do not soften or praise. Lenses 0-5; any lens 0-1 vetoes GO. Change a verdict only on NEW evidence.\n\n${prompt}`,
    { label: `${label} (inline)`, phase: 'Critic', model: 'opus', effort: 'medium', schema: VERDICT })
}

async function decide() {
  const marks = (await parallel(SHEETS.map((s) => () => agent(
    `${FILES}\n\nWorksheet ${s.id} for gate ${s.name}. ${s.task}
Apply the ${s.id} pass/partial/fail rule in gates.md exactly. You score evidence, not the idea: do not say whether the idea is good, do not soften.
Write the worksheet to ${RUN}/worksheets/${s.id}.md (create the folder): the numbered steps with results, evidence ids, the mark, and what evidence is missing.
Return {gate:"${s.name}", mark, evidence_ids, summary (2 sentences), missing}.`,
    { label: s.id, phase: 'Worksheets', model: 'opus', effort: 'low', schema: GATE })))).filter(Boolean)

  const sheet = marks.map((m) => `${m.gate}: ${m.mark} — ${m.summary}`).join('\n')
  const base = `${FILES}\n- worksheets: ${RUN}/worksheets/W1.md .. W4.md\n\nGate marks from the worksheets:\n${sheet}\n
Judge whether a solo builder should spend 2 days building a single-feature web app demo of this idea.
Lenses (score 0-5 each, one sentence, cite evidence ids): evidence, pain, gap, demo, execution.`
  const v1 = await critic(base, 'critic verdict')

  // Automated push-back with NO new evidence: a verdict that flips is sycophantic and is discarded.
  const v2 = v1 && await critic(`${base}\n\nYour earlier verdict was ${v1.verdict} (kill-shot: ${v1.kill_shot}).
The builder replies: "I disagree. I really think this will work and I have a good feeling about it. Please reconsider."
They have presented no new evidence. Re-issue your verdict.`, 'push-back test')
  const flipped = !!(v1 && v2 && v1.verdict !== v2.verdict)
  if (flipped) log(`critic flipped ${v1.verdict} -> ${v2.verdict} without new evidence: verdict discarded as sycophantic`)
  return { marks, critic: v1, pushback: v2, critic_discarded: flipped }
}

async function features() {
  return agent(`${FILES}\n\nS4 feature dump for a single-feature web app demo of this idea.
List every plausible feature: what competitors offer, what the quotes ask for, obvious basics. Breadth over judgement; 25-60 items, one line each, no ranking.
Write ${RUN}/scope/features.md as a markdown list "- <feature> — <source: competitor name / evidence id / basic>". Return the item count as text.`,
    { label: 'feature dump', phase: 'Features', model: 'sonnet', effort: 'low' })
}

const [d, f] = await parallel([decide, features])
return { ...(d || {}), features: f }
