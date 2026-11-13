# The concierge: questions that do not stop the boss

Load this before your first question to the owner in a session, or when the guard
sends you here.

**Why it exists.** `AskUserQuestion` stops the turn of the session that opens it.
Measured 2026-11-04 on 36 boss sessions: in 420 of 421 questions held over two
minutes the boss did nothing until the owner answered, and 762 worker messages
queued meanwhile. No worker was active for 459 of 2,184 project hours while a
question was open. "Dispatch everything that does not depend on the answer"
cannot be obeyed from inside a question. And 226 of 601 questions were not the
owner's to answer: approvals of what was already decided, technical choices with
a sensible default, announcements, risk lists.

**What it is.** A small session of yours that holds the question for you, so the
chime rings and your own turn goes on. It is not a worker: the pulse does not count
it, no ticket is for it. It never judges a question.

**It does not filter, and that was measured.** A Sonnet given the classes below,
on 87 past questions already labelled by another reading, sent back 14 of 50 that
were the owner's, among them "shall I delete the old key, it cannot be undone", and
let through 23 of 37 that were not. Whether a question is the owner's stays your
judgement, before you send it:

- **Theirs:** only their hand can do it (a password, sudo, a browser sign-in, a
  physical machine, a command the classifier refuses agents), or a product, money or
  scope judgement where different answers produce materially different work.
- **Not theirs:** a go-ahead on what is decided or staged, a technical choice with a
  sensible default, a report dressed as a question, a list of risks. Decide, log it.

## Starting it

At session start, after your roster:

```bash
boss-lifecycle.sh spawn "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/pm" --concierge
```

It prints the pane and the name; if you already have a live one, it prints that one
and starts nothing, so a resumed boss can run it again. `list --mine` flags it
`concierge`. It runs on Sonnet, keeps the `AskUserQuestion` every worker lacks, and
gets its instructions from `references/concierge-brief.md` at every start, so a
restart loses nothing and you send it no brief. While it lives the guard refuses your
own `AskUserQuestion`. If it is dead or stuck on a prompt, the guard lets yours
through, so you can never be left unable to ask. On a trust dialog in that folder
(the machine has not trusted it) it is stuck the same way; look at its pane once.

## Asking

Pick an id, write it on the blocker's line under `## Open blockers`, and send:

```
SendMessage {to: "<concierge>", notify_when_idle: true,
             message: "ASK q7: <the question as the owner should read it>"}
```

Self-contained, with options, your recommendation first, what waits on it, and any
command for their hand after `$ `. **Open with who you are:** your own name and your
track, as the first words of the text (`<your name>, boss of <track>: ...`). The
concierge sees your session name and address, not that you are the boss or which track;
without it the owner reads a question from a lesser worker and asks why it is not the boss
asking. If you leave it out, the concierge still asks, with `From <your name>, the boss
that sent this question.` in front and your text unchanged.

**One question per `ASK`.** Several decisions are several messages, the most urgent
first. If one message does hold several, the concierge asks them one at a time and
answers each as it comes, `ANSWER q7.1: …`, `ANSWER q7.2: …`; one left open reads
`NO ANSWER q7.2: …` and so do the ones after it. The blocker clears only when every `q7.<n>`
has an `ANSWER`; an idle notice after only some have come means the rest are `NO ANSWER`. None is
lost.

Then go on working and dispatch what does not depend on the answer. Never send a question twice: the pulse does not press you on a
blocker while the concierge has work in hand, and the ladder's rungs go through
`boss-alert`, not through a new question.

The answer comes back as a message:

- `ANSWER q7: …` Act on it, clear the blocker. The exception is a `Codex down` blocker: record the answer with
  `codex_blocker.py --choose` (SKILL.md, ticket 09b) and do not clear it; the sync clears it when Codex answers.
- `NO ANSWER q7: …` Nobody answered. Keep the blocker open.

**A merge is not an `ASK`.** A PR ready for the owner's merge goes to the desk, not to your concierge: run
`desk ready` yourself (SKILL.md P13/P14). The concierge answers an `ASK` that only asks for a merge with
`NOT AN ASK q7: …`: no owner was asked, so close that blocker by handing the PR to the desk.

**An answer settles a choice; it is not consent.** A peer message never is, so
`ANSWER q7: Yes` cannot release an action gated on the owner's own word (deleting
something for good, widening a rule). For those, ask in your own turn, with the
question starting `CONSENT:`. The guard lets it through, and your turn stops until
they answer, so use it only for that.

**When the owner says a kind of question should not reach them,** it can come back inside
the answer (`ANSWER q7: yes, and stop asking me this`) or as `REPORT q7: <their words>`,
which you get when they say it later in the concierge's pane. Record it as SKILL.md P12
says, with q7's text as the question (for `REPORT q7.2`, the text of the second question only). The concierge never writes the record itself.

The idle notice arrives after every answer; ignore it when the answer has come. With
no answer it means the owner pressed Escape: treat it as `NO ANSWER`, and the pulse
presses you again on the open blocker. Questions queue: it holds one at a time, and
the owner sees the next when the first is answered. So send the most urgent first.

## It is not a worker

- No ticket, no closing round at wrap-up, no handoff, no idle-worker response.
- `restart` and `retire` refuse while it holds a question; wrap-up closes it anyway with `retire <pane> --kill --force`.
- Close it at wrap-up, with the rest of the team, even with a question open: SKILL.md Phase E writes
  that question into the tracker first, and the recap tells the owner it no longer rings.
