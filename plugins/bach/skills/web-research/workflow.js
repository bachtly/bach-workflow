export const meta = {
  name: 'web-research',
  description: 'Streaming web research: search+screen per query, fetch+harvest per URL, early and final Opus judge per round, CSV evidence trail',
  whenToUse: 'Invoked by the web-research skill after the Frame step; needs args from run.json',
  phases: [
    { title: 'Search', detail: 'Haiku per query: WebSearch + screen', model: 'haiku' },
    { title: 'Pages', detail: 'Haiku per URL: fetch to disk + verbatim harvest (Sonnet re-harvest on low recall)', model: 'haiku' },
    { title: 'Judge', detail: 'Opus low: early judge at 50% notes, final judge at 100%', model: 'opus' },
  ],
}

// ---------------- args ----------------
const A = args || {}
const RUN = A.run_dir
const SKILL = A.skill_dir
const B = A.budget || {}
const CAP = B.cap || 100                  // total fetches for the whole run
const PER_QUERY = B.per_query || 5        // max URLs fetched per query
const MAX_RESULTS = B.max_results || 10   // results screened per query
const MAX_QUERIES = B.max_queries || 8    // queries per round after round 1
const MAX_ROUNDS = B.max_rounds || 8
const TERMS_PER_ROUND = B.terms_per_round || 5
const RECALL_MIN = 0.5
if (!RUN || !SKILL || !A.topic || !(A.queue || []).length) throw new Error('args need run_dir, skill_dir, topic, queue')

const CTX = `Research topic: ${A.topic}
Purpose: ${A.purpose || 'general understanding'}
Recency need: ${A.recency || 'none stated'}
Today: ${A.today}`

const REC = `python3 ${SKILL}/scripts/record.py ${RUN}`

// ---------------- helpers ----------------
function normUrl(u) {
  // must match norm_url() in record.py
  try {
    const m = String(u).trim().match(/^([a-z][a-z0-9+.-]*):\/\/([^/?#]+)([^?#]*)(\?[^#]*)?/i)
    if (!m) return String(u).trim()
    const host = m[2].toLowerCase().replace(/^www\./, '')
    const path = m[3].replace(/\/+$/, '') || '/'
    const q = (m[4] || '').slice(1).split('&').filter(kv => {
      if (!kv) return false
      const k = kv.split('=')[0].toLowerCase()
      return !k.startsWith('utm_') && !['ref', 'fbclid', 'gclid'].includes(k)
    })
    return `${m[1].toLowerCase()}://${host}${path}${q.length ? '?' + q.join('&') : ''}`
  } catch (e) { return String(u) }
}
const shq = s => `'${String(s).replace(/'/g, `'\\''`)}'`
const pad = n => String(n).padStart(2, '0')

// ---------------- schemas ----------------
const SEARCH_SCHEMA = {
  type: 'object',
  properties: {
    results: {
      type: 'array',
      items: {
        type: 'object',
        properties: { rank: { type: 'integer' }, url: { type: 'string' }, include: { type: 'boolean' } },
        required: ['rank', 'url', 'include'],
      },
    },
  },
  required: ['results'],
}
const PAGE_SCHEMA = {
  type: 'object',
  properties: {
    status: { type: 'string', enum: ['ok', 'failed'] },
    method: { type: 'string' },
    recall: { type: ['number', 'null'] },
    l1_terms: { type: 'integer' },
    missing: { type: 'array', items: { type: 'string' } },
  },
  required: ['status'],
}
const JUDGE_SCHEMA = {
  type: 'object',
  properties: {
    new_terms: { type: 'integer' },
    total_terms_seen: { type: 'integer' },
    new_facts: { type: 'integer' },
    next_queue: {
      type: 'array',
      items: { type: 'object', properties: { query: { type: 'string' }, origin: { type: 'string' } }, required: ['query', 'origin'] },
    },
    stop: { type: 'boolean' },
    stop_reason: { type: 'string' },
  },
  required: ['new_terms', 'new_facts', 'next_queue', 'stop', 'stop_reason'],
}

// ---------------- prompts ----------------
const searchPrompt = (q) => `You are a search-and-screen worker in a web research run. Work fast; do not research beyond these steps.
${CTX}

1. Run WebSearch with exactly this query: ${q.query}
2. Take up to ${MAX_RESULTS} results in rank order. For each, decide include (worth fetching) or exclude, judging ONLY its title, URL and snippet.
   Include: likely relevant and substantive. Prefer primary sources (official docs, standards, papers, government, vendor engineering blogs, original research).
   Exclude: off-topic, SEO listicle or aggregator, thin page, stale for the recency need, login/paywall, video-only.
   reason: at most 8 words, starting with one of: relevant | primary | off-topic | seo | thin | outdated | paywall | other.
3. Use the Write tool to write ${RUN}/search/${q.qid}.json with exactly:
   {"qid":"${q.qid}","round":${q.round},"query":${JSON.stringify(q.query)},"origin":"${q.origin}","results":[{"rank":1,"url":"...","title":"...","snippet":"...","include":true,"reason":"..."}]}
   (snippet = whatever summary text the search gave; "" if none)
4. Run: ${REC} --check search/${q.qid}.json
   If it prints ok:false, fix the file and run it again.
Return the results list (rank, url, include).`

const harvestSteps = (u, extra) => `Read ${RUN}/pages/${u.sid}.md and ${RUN}/notes/${u.sid}.struct.json (L1 terms a script already found).
Harvest VERBATIM. You are a copier, not a summariser: over-include, never rank, never filter for importance, keep original wording.
${extra || ''}
Write ${RUN}/notes/${u.sid}.json with the Write tool:
{
 "sid": "${u.sid}", "url": ${JSON.stringify(u.url)}, "title": "...",
 "published": "YYYY-MM-DD or YYYY or \"\" if not on the page",
 "source_type": "primary | vendor | news | blog | forum | academic | gov | other",
 "quality_flags": ["undated" | "seo" | "vendor-claim" | "thin" | "outdated" ...],
 "terms": [{"term": "exact phrase from the page", "context": "<= 15 words around it"}],
 "claims": [{"claim": "one factual statement, paraphrased tightly", "quote": "<= 15 words verbatim or \"\"", "numbers": ["every number/stat with unit"]}],
 "analysis_rows": [ ...rows per the spec below, each with "type": "<type key>" ... ],
 "model": "${extra ? 'sonnet' : 'haiku'}"
}
terms: every jargon term, named method, product, org, person, standard, metric, acronym (with expansion if given) the page uses about the topic. Usually 20-80 entries. Include the L1 terms that are meaningful.
claims: every substantive claim and every number. Usually 10-40 entries.
analysis_rows spec (only rows the page actually supports; [] if none):
${A.types_spec}

Then run: ${REC} --check notes/${u.sid}.json
If ok:false, fix and rerun.`

const pagePrompt = (u) => `You are a page worker in a web research run: fetch one page to disk, then harvest it. Work fast.
${CTX}
URL: ${u.url}

STEP 1. Fetch. Run:
  python3 ${SKILL}/scripts/fetch.py ${RUN} ${u.sid} ${shq(u.url)}
Exit 0 means pages/${u.sid}.md is ready; go to step 2.
Exit 4 means a hard failure (e.g. a PDF it could not convert). Do NOT use WebFetch; stop and return {"status":"failed","method":"curl"}.
Exit 3 (any other failure): use the fallback. call WebFetch on the URL with this prompt:
  "Return the full main text of this page as markdown. Keep every heading, list, table, number, name and technical term verbatim. Do not summarise or shorten. Omit navigation, ads and cookie banners."
Write the returned text to ${RUN}/pages/${u.sid}.md with the Write tool, then run:
  python3 ${SKILL}/scripts/fetch.py ${RUN} ${u.sid} ${shq(u.url)} --from-file
If that also fails, stop and return {"status":"failed","method":"webfetch"}.

STEP 2. Harvest.
${harvestSteps(u)}

Return status, method (curl or webfetch), and recall, l1_terms, missing from the check output.`

const reharvestPrompt = (u, missing) => `You are a re-harvest worker. A cheaper model harvested this page but missed many terms the page clearly marks as important. Redo the harvest properly and overwrite the notes file.
${CTX}
${harvestSteps(u, `The previous harvest missed these marked-up terms, among others: ${missing.join(' | ')}`)}

Return status "ok", method "reharvest", and recall, l1_terms, missing from the check output.`

const judgePrompt = (round, phase, sids, priorQueries) => `You are the ${phase === 'interim' ? 'EARLY' : 'FINAL'} judge for round ${round} of a web research run. Effort is low: be decisive, batch your reading, do not search the web.
${CTX}
Outcome types: ${(A.types || []).join(', ')}

Read:
- ${RUN}/terms.csv (terms from earlier rounds; empty in round 1)
- the harvest notes of this round: ${sids.map(s => `notes/${s}.json`).join(', ')} (all under ${RUN})
${phase === 'final' ? `- ${RUN}/judge/${round}-interim.json if it exists: build on it rather than redoing it` : ''}
You may open a raw page (${RUN}/pages/<sid>.md) only if a note looks thin.

Do:
1. Candidate terms = all note terms. Merge synonyms, spelling variants and acronym/expansion pairs into one canonical term.
2. Score each canonical term 0-3 on: freq (how many sources use it), centrality (to the research topic), novelty (vs terms.csv). Drop terms scoring under 5 total or clearly off-topic (status "dropped").
3. Mark the top ${TERMS_PER_ROUND} new, unexpanded terms as status "queued" (the rest: "kept" or "dropped"; terms expanded in earlier rounds stay "expanded").
4. new_facts = number of claims in this round's notes that add information not already known from earlier rounds.
5. Expand queries (origin "expand"), only when warranted: contradiction between sources -> query for a primary source; an important single-source claim -> corroboration query; a key number -> query for its original source and date; recency gap -> query with "latest" or the current year; only vendor or one-sided sources -> a "limitations", "criticism" or "vs" query; a named entity central to the topic -> query for its official page.
6. next_queue: the queued terms phrased as term + topic context (e.g. "RAG chunking strategy", not "chunking"), plus the expand queries. At most ${MAX_QUERIES}. Never repeat or trivially rephrase these earlier queries: ${JSON.stringify(priorQueries)}
${phase === 'final'
    ? `7. Stop check. stop=true if ANY: answered (every key question of the topic has >=2 independent sources); saturation (under 20% of this round's terms are new, or new_facts < 3); drift (most new terms are off-topic). The orchestrator separately enforces the fetch budget and source repetition.`
    : `7. This is the interim pass: stop must be false. next_queue is provisional.`}

Write ${RUN}/judge/${round}-${phase}.json with the Write tool:
{"round":${round},"phase":"${phase}","terms":[{"term":"...","score":7,"freq":3,"centrality":3,"novelty":1,"status":"queued|kept|dropped|expanded","sources":["sid",...]}],
 "new_terms":0,"new_facts":0,"contradictions":[{"topic":"...","sides":["sid: claim","sid: claim"]}],
 "next_queue":[{"query":"...","origin":"term|expand"}],"stop":{"stop":false,"reason":"..."}}
Then run: ${REC} --check judge/${round}-${phase}.json  (fix and rerun if ok:false)
Return new_terms, total_terms_seen, new_facts, next_queue, stop, stop_reason.`

// ---------------- run ----------------
const seen = new Set()
const priorQueries = []
const rounds = []
let fetched = 0
let queue = A.queue.map(q => ({ query: q.query, origin: q.origin || 'paraphrase' }))
let stopReason = ''
let dropped = 0

for (let round = 1; round <= MAX_ROUNDS; round++) {
  const queries = queue.slice(0, round === 1 ? queue.length : MAX_QUERIES)
    .map((q, i) => ({ ...q, round, qid: `r${round}q${pad(i + 1)}` }))
  queries.forEach(q => priorQueries.push(q.query))
  log(`Round ${round}: ${queries.length} queries · ${fetched}/${CAP} fetches used`)

  const seenBefore = new Set(seen)
  const sids = []
  let identified = 0, repeated = 0
  let searchesDone = 0, expected = null, notesDone = 0, early = null

  const maybeEarly = () => {
    if (early || expected === null || expected < 4) return
    if (notesDone >= Math.ceil(expected / 2) && notesDone < expected) {
      const snap = sids.slice()
      log(`Round ${round}: early judge on ${snap.length}/${expected} notes`)
      early = agent(judgePrompt(round, 'interim', snap, priorQueries),
        { label: `early judge r${round}`, phase: 'Judge', model: 'opus', effort: 'low', schema: JUDGE_SCHEMA })
    }
  }

  await pipeline(
    queries,
    // stage 1: search + screen (one Haiku per query)
    (q) => agent(searchPrompt(q), { label: `search ${q.qid}`, phase: 'Search', model: 'haiku', effort: 'low', schema: SEARCH_SCHEMA }),
    // stage 2: dedupe in-script (single-threaded, race-free), cap, then stream each URL through fetch+harvest
    (res, q) => {
      const results = (res && res.results) || []
      identified += results.length
      const picked = []
      for (const r of results.slice().sort((a, b) => a.rank - b.rank)) {
        const n = normUrl(r.url)
        if (seenBefore.has(n)) repeated++
        if (!r.include || seen.has(n)) continue
        if (picked.length >= PER_QUERY) continue
        if (fetched >= CAP) { dropped++; continue }
        seen.add(n)
        fetched++
        picked.push({ url: r.url, sid: `${q.qid}-${pad(r.rank)}` })
      }
      searchesDone++
      if (searchesDone === queries.length) { expected = fetched - rounds.reduce((a, r) => a + r.fetched, 0); maybeEarly() }
      return pipeline(
        picked,
        (u) => agent(pagePrompt(u), { label: `page ${u.sid}`, phase: 'Pages', model: 'haiku', effort: 'low', schema: PAGE_SCHEMA }),
        (p, u) => {
          if (p && p.status === 'ok' && p.recall !== null && p.recall !== undefined && p.recall < RECALL_MIN && (p.l1_terms || 0) >= 5) {
            log(`${u.sid}: recall ${p.recall}, Sonnet re-harvest`)
            return agent(reharvestPrompt(u, p.missing || []), { label: `reharvest ${u.sid}`, phase: 'Pages', model: 'sonnet', effort: 'low', schema: PAGE_SCHEMA })
          }
          return p
        },
        (p, u) => {
          if (p && p.status === 'ok') sids.push(u.sid)
          notesDone++
          maybeEarly()
          return p
        },
      )
    },
  )

  const roundFetched = fetched - rounds.reduce((a, r) => a + r.fetched, 0)
  if (early) await early
  if (!sids.length) {
    rounds.push({ round, queries: queries.length, identified, fetched: roundFetched, included: 0 })
    stopReason = 'no usable pages this round'
    break
  }
  const j = await agent(judgePrompt(round, 'final', sids, priorQueries),
    { label: `judge r${round}`, phase: 'Judge', model: 'opus', effort: 'low', schema: JUDGE_SCHEMA })

  const repetition = identified ? repeated / identified : 0
  rounds.push({
    round, queries: queries.length, identified, repeated, fetched: roundFetched, included: sids.length,
    new_terms: j && j.new_terms, new_facts: j && j.new_facts, judge_stop: j && j.stop, judge_reason: j && j.stop_reason,
  })
  log(`Round ${round}: ${sids.length} pages harvested · new terms ${j && j.new_terms} · new facts ${j && j.new_facts}`)

  if (!j) { stopReason = 'judge failed'; break }
  if (j.stop) { stopReason = j.stop_reason || 'judge: stop'; break }
  if (fetched >= CAP) { stopReason = `budget: ${fetched}/${CAP} fetches`; break }
  if (round > 1 && repetition > 0.5) { stopReason = `repetition: ${Math.round(repetition * 100)}% of results already seen`; break }
  queue = (j.next_queue || []).filter(q => !priorQueries.includes(q.query))
  if (!queue.length) { stopReason = 'no new queries'; break }
  if (round === MAX_ROUNDS) stopReason = `max rounds (${MAX_ROUNDS})`
}

if (dropped) log(`${dropped} screened-in URLs were not fetched because the fetch cap (${CAP}) was reached`)
return { run_dir: RUN, stop_reason: stopReason, fetched, cap: CAP, dropped_by_cap: dropped, rounds }
