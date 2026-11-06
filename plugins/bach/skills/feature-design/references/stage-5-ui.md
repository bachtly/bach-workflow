# Stage 5 · UI → `05-ui.md`

Low-fidelity design: which screens, what's on them, every state, and which API call each action makes. Reuse the repo's design system and component names. Visual polish is out of scope unless the brief makes it a goal.

Inputs also include reference screenshots the user put in `refs/`.

**Size limit:** about 1,500 words, wireframes excluded.

## Template

```markdown
# <Feature>: UI

## Screens
| Screen | Route / entry point | Use cases | New / changed | Main components (existing names) |
|---|---|---|---|---|

## Navigation
<Mermaid flowchart between screens, matching the user flows in 02-requirements.md>

## Wireframes
<one low-fidelity ASCII wireframe per screen, or a link to an HTML mockup in ui/>

## States
| Screen | Empty | Loading | Error | Partial | Success | No permission |
|---|---|---|---|---|---|---|

## Interactions
| Screen | User action | API operation | Optimistic update? | On error |
|---|---|---|---|---|

## Accessibility and responsiveness
<keyboard path, labels, focus, contrast, breakpoints>

## Look and feel
<tone, density, references in refs/>
```

## Exit checklist
- Every step of every user flow lands on a screen.
- Every screen has all its states designed, not only success.
- Every action maps to an operation in `04-api.md`, and its error is handled.
- Existing components are reused; each new component is justified.
- A keyboard-only path exists for every main flow.
- Within the size limit.
