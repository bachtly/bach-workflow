export const meta = {
  name: 'demo-scope-research',
  description: 'demo-scope Phase A: nested web-research + public feeds + competitor reviews + Product Hunt refs, all in parallel',
  whenToUse: 'Invoked by the demo-scope skill after the idea card and competitor scout',
  phases: [
    { title: 'Web research', detail: 'nested bach:web-research workflow (quick)' },
    { title: 'Feeds', detail: 'Haiku low: run feeds.py, then extract quotes per raw file', model: 'haiku' },
    { title: 'Reviews', detail: 'Haiku low per competitor: Trustpilot 1-2 star reviews via WebFetch', model: 'haiku' },
    { title: 'References', detail: 'Haiku low: Product Hunt launches as UI/demo references', model: 'haiku' },
  ],
}

const A = args || {}
const RUN = A.run_dir
const SKILL = A.skill_dir
if (!RUN || !SKILL || !A.idea) throw new Error('args need run_dir, skill_dir, idea')

const IDEA = `Idea card:\n${A.idea}`
const ROW_RULES = `Each row: {type, source, url, date (YYYY-MM-DD), quote_or_number (exact words, <=300 chars), persona_match ("y"/"n"), theme (2-4 word tag), note}.
type is one of: pain (a complaint about the job), review (complaint about a named competitor), competitor (a tool doing this job), spend (someone paying money/time for it).
Keep only rows relevant to the idea; persona_match=y only when the writer plausibly is the persona. Copy words verbatim, never paraphrase into the quote field.`

const COUNT = { type: 'object', properties: { file: { type: 'string' }, rows: { type: 'integer' } }, required: ['file', 'rows'] }
const FEEDS = { type: 'object', properties: { files: { type: 'array', items: { type: 'string' } }, items: { type: 'integer' }, failures: { type: 'integer' } }, required: ['files'] }

async function webResearch() {
  if (!A.web_research) { log('web-research skipped (no args)'); return null }
  phase('Web research')
  try {
    return await workflow({ scriptPath: A.web_research.script_path }, A.web_research.args)
  } catch (e) {
    log(`web-research failed: ${e}`)
    return { error: String(e) }
  }
}

async function feeds() {
  const f = A.feeds || {}
  const q = (xs) => (xs || []).map((x) => `"${String(x).replace(/"/g, '')}"`).join(' ')
  const cmd = `python3 ${SKILL}/scripts/feeds.py ${RUN} --keywords ${q(f.keywords)}` +
    (f.subreddits && f.subreddits.length ? ` --subreddits ${q(f.subreddits)}` : '') +
    (f.appids && f.appids.length ? ` --appids ${q(f.appids)}` : '')
  const res = await agent(`Run exactly this command with Bash (timeout 600000 ms) and return the JSON it prints as {files, items, failures(count)}:\n${cmd}`,
    { label: 'feeds.py', phase: 'Feeds', model: 'haiku', effort: 'low', schema: FEEDS })
  const files = (res && res.files) || []
  log(`feeds: ${files.length} raw files, ${(res && res.items) || 0} items`)
  return pipeline(files, (file) => agent(
    `${IDEA}\n\nRead the raw feed file ${file} (JSON with "items": posts/comments/reviews).
Extract evidence rows. ${ROW_RULES}
Write {"rows":[...]} to ${RUN}/evidence/extracted/${file.split('/').pop()} (create the folder if needed). Return {file, rows}.`,
    { label: `extract ${file.split('/').pop()}`, phase: 'Feeds', model: 'haiku', effort: 'low', schema: COUNT }))
}

async function reviews() {
  const comps = (A.competitors || []).filter((c) => c && c.domain).slice(0, 6)
  return pipeline(comps, (c) => agent(
    `${IDEA}\n\nCompetitor: ${c.name} (${c.domain}).
Use WebFetch on https://www.trustpilot.com/review/${c.domain} and, if it has reviews, collect up to 15 of the 1-2 star reviews.
If the page has no reviews or fails, return rows=0 and write nothing.
${ROW_RULES} Use type=review, source="Trustpilot ${c.name}".
Write {"rows":[...]} to ${RUN}/evidence/extracted/trustpilot-${c.domain.replace(/[^a-z0-9]+/gi, '-')}.json. Return {file, rows}.`,
    { label: `trustpilot ${c.domain}`, phase: 'Reviews', model: 'haiku', effort: 'low', schema: COUNT }))
}

async function references() {
  return agent(
    `${IDEA}\n\nFind 3-6 recent Product Hunt launches (or similar showcase pages) for tools doing this job.
Use WebSearch "site:producthunt.com <job keywords>" and WebFetch on the launch pages.
Write ${RUN}/refs/producthunt.md: one bullet per launch with name, URL, tagline, and one line on what their demo/first screen shows (useful as UI and demo references).
Also append competitor rows (type=competitor) to ${RUN}/evidence/extracted/producthunt.json as {"rows":[...]}. ${ROW_RULES}
Return {file, rows}.`,
    { label: 'product hunt refs', phase: 'References', model: 'haiku', effort: 'low', schema: COUNT })
}

const [wr, fd, rv, rf] = await parallel([webResearch, feeds, reviews, references])
const flat = (x) => (x || []).filter(Boolean)
return {
  web_research: wr,
  feed_rows: flat(fd).reduce((s, r) => s + (r.rows || 0), 0),
  review_rows: flat(rv).reduce((s, r) => s + (r.rows || 0), 0),
  refs: rf,
}
