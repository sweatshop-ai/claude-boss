# Reporting format, and how to read a worker's report

## Emoji status indicators

| Emoji | Meaning | Use for |
|---|---|---|
| ✅ | Done / success | Completed tasks, passing checks, confirmed outcomes |
| ⏳ | In progress | Active work, running tests, waiting for results |
| ❌ | Failed / blocked | Errors, test failures, permission blocks, hard stops |
| 🔁 | Retrying | Nudge sent, worker restarted, task re-dispatched |
| ⚠️ | Needs attention | Permission prompts, ambiguous state, approaching risk |
| 🔲 | Not started | Open/queued tasks, planned but unassigned work |

## Structure

1. **Hierarchical, not flat** — main items with indented sub-items:
   ```
   - ⏳ **Yuki** (39:0.2) — acme-api
     - ✅ Fixed 4 missing meta descriptions
     - ⏳ Running ruff check
     - ⚠️ 1 lint warning to resolve
   ```
2. **Tables for multi-column data** — worker status, issue lists, test results.
3. **Bold key outcomes** — ✅ **4 metas fixed, all tests passing**.
4. **Section headers carry emoji** — `### ✅ Completed`, `### ⚠️ Needs attention`.

**TTS does not read emoji** — with `voice: ON`, speak the same information conversationally.

## Status table shape

```
| Worker | Pane | Status | Project | Task | Activity |
|--------|------|--------|---------|------|----------|
| Yuki   | 39:0.2 | ⏳ | acme-web    | #120: soft 404s on example.com | Running ruff check |
| Lars   | 39:0.3 | ✅ | acme-agent  | — | **Deploy complete, idle** |
| Mei    | 39:0.4 | ⚠️ | compute-node | #k2m: RAG endpoint | Permission prompt — needs you |
```

## Session summary (Phase E)

```
### ✅ Completed
| Issue | Title | Worker | Project | Outcome |
|---|---|---|---|---|
| #120 | Fix soft 404s on example.com | Yuki | acme-web    | **fixed, sitemap clean** |

### ⏳ Still in progress
| #k2m | RAG endpoint | Mei | compute-node | Almost done, running tests |

### ⚠️ Git state
- ⚠️ Lars has 2 unpushed commits on `dev` in acme-agent
- 🔲 Branch `fix/meta-descriptions` merged but not deleted

### Suggested priorities next session
1. **#k2m** — Mei was close
2. **#54** — Schema markup, next on the board
```

---

# Reading a worker's report

A report is not a result. Four habits, each of which caught a real defect in one night.

**1. The first authorised step of expensive work is the verification of its
criterion, not the work.** When you authorise a costly job because a criterion is
met, authorise the ten-minute check of that criterion first. Three times in one
night the cheap step dissolved the expensive job it had been authorised to
justify. It feels like delay on a decision already taken; that is exactly why
nobody does it.

**2. A marked hypothesis must not become load-bearing without being measured.**
When a worker writes "probably X" and you build a ruling on it, the hedge is lost
in the relay and the hypothesis comes back to them as an established premise.
Reuse is not verification, and it looks like it from outside. Measure the premise
before the decision, not after.

**3. Read the premises, not only the answers.** The largest finding of the night
arrived as *context* inside a reply to a smaller question — a 26% vs 7% asymmetry
mentioned in passing while answering something else. A big defect travels
comfortably inside the explanation of a small one, because in that position it
reads as background and nobody audits background.

**4. Interrogate a null.** When a worker reports "zero found", ask two things
before believing it: *what unit was counted* (composer ≠ work, pair ≠ judgment,
file ≠ record), and *are the known-bad cases inside the check's coverage* — a
cross-field check covers the intersection of its fields, and a clean zero from a
detector that structurally cannot see the case you already confirmed says nothing
at all.

**A cheap worker still reports.** If it says "done and nothing looked wrong", that
sentence carries no evidence — ask for the command it ran, not for its confidence.

---

# Plan review

Workers run their own plan-mode prompts; **the owner approves them in the worker's
own pane** — they are watching. Your job is to review plan *content* when a worker
sends its plan, and reply with a verdict and specifics.

Evaluate against the task and the issue:
- Does it address the actual task, or a tangent?
- Is the scope right — not too narrow, not scope-creeping?
- Obvious risks? Destructive operations, wrong branch, unrelated files.
- Does it collide with another worker's current work?

Push back on: work outside the task's project scope; deletes or force-pushes
without justification; skipping tests or lint; reimplementing something that
exists; vagueness ("investigate and fix" with no steps); touching files another
worker is editing.

Reply with a decision, not a shrug: *"Looks right, go"* / *"Problem: <specific>.
Revise: <concrete guidance>"* / *"Before you start: <specific question>"*. Log
rejections in the tracker so a revised plan is judged against the original
objection.
