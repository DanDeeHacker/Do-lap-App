# Došlap — What Our Startup Does

## Summary

Došlap connects athletes and physiotherapists in a single digital environment that today does
not exist between them. It gives athletes a clear, day-by-day picture of how their movement is
loading their musculoskeletal system and when it's time to act. It gives physiotherapists the
operational infrastructure to replace today's fragmented, paper-based processes and connects
them directly to clients with real data. The core value is **digital continuity** between
client and physio — from the examination, through the plan and its ongoing adjustments, to the
next check-up.

As our entry wedge we use **runners**: they generate dense wearable data, have a strong
motivation to prevent injuries, and follow a natural cycle in which problems can be caught
early.

---

## Interface 1 — Athlete (runner)

The goal is for the runner to **transparently understand the impact of their movement on the
musculoskeletal system** and to receive an early signal of whether it's time to slow down or
see a specialist.

**Data collection.** In the ideal mode the app draws data from wearables (running dynamics,
heart-rate response, sleep and recovery). In a limited mode — without a smartwatch — the
athlete at least keeps a structured **diary** (runs, pain, mood, perceived exertion), which on
its own is enough for a baseline assessment.

**Daily state assessment.** Each day the current state is placed into one of four quadrant
cells:

- **Stable** — load and mechanics sit within your own norm.
- **Silent drift** — mechanics are changing without the athlete feeling it (an early, "silent"
  signal).
- **Ease off** — load has jumped above the usual level; time to back off and watch recovery.
- **Book a physio visit** — a critical combination where seeing a specialist makes sense.

The state is built from three axes: **movement mechanics** (drift of running technique against
your own norm at comparable pace and terrain — not against a population average), **load**
(acute vs. chronic load, monotony, high intensity, downhill running, overnight recovery), and
**diary results** (pain and its recurrence, subjective symptoms). The athlete sees not just the
resulting score but **what makes it up** and how it has evolved over time, so the decision is
understandable rather than a black box.

This moves the runner beyond "I ran X km" toward understanding **how much they can absorb and
how well they recover from it** — and, above all, toward an early warning before a micro-change
turns into an injury.

---

## Interface 2 — Physiotherapist (individuals and sports clinics)

On the physiotherapy side we are building **infrastructure**, because today's processes are —
from our own experience — outdated: online forms and emails for registration, paper
questionnaires on site, no digital records from examinations, no continuity between visits, and
no direct digital consultation of the plan that has been set.

Došlap for physios offers a unified environment for:

- **Scheduling and booking** — calendar, slots, reservations.
- **Client communication** — chat and sharing tied directly to the client's data.
- **New-client registration** — digital, without paper or re-typing.
- **New-client acquisition** — in a later phase as one of the channels via Interface 1
  (athletes whose state indicates the need for a specialist are matched to a suitable physio).
- **Program creation** for clients with a weekly breakdown.
- **Session summaries** — with the option to upload the examination transcript.
- **Exercise database** — selection from a professional physio exercise database (external
  partner via API / cooperation).
- **Wearable data overview** — in a shortened version (without per-run detail).
- **Client state assessment** with an optional **AI summary** that walks the expert through the
  client's movement patterns and points them toward potential pitfalls — as an assistant, not a
  replacement for judgment.

The physio thus faces the client with full context: history, data, progress, and evolution over
time.

*Note: in this version the physiotherapist interface is not yet fully built.*

---

## Digital continuity — the core of the value

For both interfaces the goal is to **maintain the connection between client and physio between
visits**, when that is desired. Specifically, after an examination:

1. The client receives an **examination summary** — first generated from the transcript and AI,
   then **confirmed and edited by the expert** (the expert always has the final word).
2. They get **action steps and tips** and a **program in the app** with a simple weekly
   breakdown.
3. They **check off** the program dynamically, see **progress**, and can take **notes**.
4. Via **chat** they can message the physio, who can respond within limits on the given
   training structure and **adjust the plan before the next visit** (typically a month away).
5. On their side, the physio sees the client's **progress, chat, and the ongoing evolution of
   their data**.

A one-off examination thus becomes an **ongoing, data-backed relationship** — the client is not
left alone for a month, and the physio does not work blind.

---

## Why it makes sense

- **For athletes:** an early warning and a clear picture of their own body, not just kilometers.
- **For physios:** modern operations, less administration, clients with context, and a new
  acquisition channel.
- **For the whole system:** prevention and continuity instead of firefighting injuries that
  have already happened.

Runners are the ideal first market; from there the model expands to other sports and to broader
cooperation with both sports and individual physiotherapy clinics.
