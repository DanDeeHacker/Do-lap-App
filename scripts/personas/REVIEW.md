# Persona review — the AI layer (stage 2)

The browser journeys (`journey.mjs`) leave a journal: for each day a persona opened the app, what
happened to the persona that day (events, check-in, what it did), what the app said in the
morning (`app`: Dnes type, readiness, the reasons, the week plan), and the screens it visited
(`screens`: route, visible text, screenshot). The automatic checks already caught crashes, server
errors, slow pages, Czech in the English version and the engine's own rules (`appFindings`,
`screens[].findings`). Your job is what a careful runner would notice and a rule can't.

Read `persona-journal/journal.json`, look at the screenshots of the days with events, and read the
screens in the persona's order. Then report **at most 3 findings per run**, only ones you would
defend to the owner.

## What counts

1. **Contradictions between screens or days.** Dnes says one thing, Trénink or the report another;
   a number changes between the morning and the evening without a reason the app gives; the week
   plan promises a session the persona was told to skip.
2. **Advice that ignores what the persona just reported.** A check-in with pain or illness, and the
   next screen behaves as if nothing happened; the app asks for something the persona already gave.
3. **Confusing or missing explanations** at the moments that matter: why today is easier, why a
   session moved, what to do after a data gap. Quote the text.
4. **Dead ends.** A screen with no next step where the persona clearly needs one (e.g. after an
   illness, after three days without the watch).
5. **Wording outside the medical-device boundary** (README): the app monitors load and supports the
   physiotherapist; it must not diagnose, predict injury or promise treatment.

## What does not count

- Taste (colours, layout preferences), generic "could be clearer", anything without a quote or a
  screenshot that shows it.
- Engine thresholds you would set differently: those are the clinical guarantor's call. Report
  only when the app breaks its *own* stated rule or contradicts itself.
- Anything already in `appFindings` / `screens[].findings` (it is filed).
- The personas are synthetic; never ask for or refer to real users' data.

## Output

Write `findings.json` and file it with
`node scripts/personas/journey.mjs file findings.json --base <staging>`:

```json
[{"persona": "jana", "simDate": "2026-09-14",
  "items": [{"check": "ai-contradiction", "route": "/app/training", "key": "short stable slug",
             "title": "Czech, one line, what is wrong",
             "detail": "Czech. Persona, day, what it reported, what each screen said (quoted), why it matters.",
             "type": "bug"}]}]
```

`check` is one of `ai-contradiction`, `ai-ignored-report`, `ai-unclear`, `ai-dead-end`,
`ai-wording`. Use `"type": "engine"` when the finding is about what runners are told about their
health; such a change will need the clinical guarantor's sign-off. Keep `key` stable (no dates), so
the same problem on another day lands on the same note. If nothing qualifies, file nothing and say
so.
