# Your research tasks (about 40 minutes, while the agents run)

Agents cannot open these sites (403 / login walls). Paste what you find into
`evidence_human.csv` in this folder, one row per quote. Columns:

| Column | Value |
|---|---|
| type | `pain` (a complaint), `review` (competitor 1–3★ review), `competitor` (a tool you found), `spend` (someone paying for it) |
| source | e.g. `reddit r/freelance`, `G2 <competitor>`, `Capterra <competitor>` |
| url | link to the post or review |
| date | YYYY-MM-DD (approx is fine) |
| quote_or_number | the exact words, copy-pasted |
| persona_match | `y` if the writer matches the persona, else `n` |
| theme | 2–4 word tag, e.g. `chasing payment`, `too complex` (optional) |
| note | anything else |

## H1 · Reddit (20 min)
Open each link, set **Sort: Top · Time: Past year** if not already, open the
10 longest threads, copy the most specific complaints. Long rants with details
count most.

{{REDDIT_LINKS}}

## H4 · G2 / Capterra 1–3★ reviews (20 min)
For each competitor: open reviews, filter to 1–3 stars, read 10, copy each
complaint and tag a theme (price, missing feature, too complex, support, …).

{{REVIEW_LINKS}}

When done, reply **done** in the Claude session.
