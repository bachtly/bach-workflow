# Scope rules: demo script, cut test, fakes, budget, done criteria

Demo type is fixed: **single-feature web app**, one real feature end to end, ≤1 risky dependency.

## Core job sentence
"<Persona> can <job> without <W2 weakness>." Under 20 words, one persona.

## Demo script: 5 beats, ≤2 minutes (this is the user journey)

| Beat | Seconds | Content |
|---|---|---|
| 1 Hook | 15 | A real W1 quote on screen |
| 2 Today | 15 | How they do it now (competitor or manual workaround) |
| 3 Core action | 45 | Do the core job live in the app |
| 4 Wow | 30 | The visible "after" from W3 |
| 5 Next | 15 | The Later list framed as the roadmap |

Impact should land within 60 s. Storytelling beats stronger code with weak storytelling.

## Cut test (per feature, in order)

| # | Question | Answer → column |
|---|---|---|
| 1 | Does it appear on screen in a demo beat? | No → **Later** |
| 2 | Would beat 3 or 4 break if this were faked? | No → **Fake** |
| 3 | Does it add a second user type? | Yes → **Later** |
| 4 | Is it on the always-later list? | Yes → **Later** |
| — | Otherwise | **Build** |

Always later: settings, dark mode, profile editing, email preferences, admin panel, payments, mobile app, integrations off the demo path, multi-tenant, i18n, edge cases off the demo path.

First passes over-classify Build. Be strict.

## Fake methods

| To fake | Method |
|---|---|
| Auth / signup | One seeded demo account, already logged in |
| Data | Realistic seeded dataset, using wording from W1 quotes |
| External or AI API | Live call + cached response fallback for rate limits and failure |
| Email / notifications | Show in the UI instead of sending |
| Background jobs | Trigger on a click |
| Payments | Leave out, or show a static price |

## Budget
- About 20–24 build hours over 2 days; Build items ≤ about 14 h (⅔), ≤5 items.
- AI hour estimates are a second opinion and run optimistic; the user's estimate wins.

## Demo done criteria
- Beats 1–5 run in ≤2 min, no code edits, no dev tools open
- 3 full rehearsals pass in a row
- Works with network off or API down, via the fallback
- Backup video recorded
- Hits ≥3 of 5 judging criteria: creativity, usability, technical fit, growth path, business or social value

## Self-review (all must pass before lock)
- Core job <20 words and names one persona
- Every Build item appears in a demo beat
- Build ≤14 h and ≤5 items
- Every Fake item has a method
- LATER lists ≥8 items
- Riskiest dependency has a spike and a fallback
- Code-freeze time written down
