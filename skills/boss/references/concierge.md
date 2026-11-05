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
command for their hand after `$ `. Then go on working and dispatch what does not
depend on the answer. Never send a question twice: the pulse does not press you on a
blocker while the concierge has work in hand, and the ladder's rungs go through
`boss-alert`, not through a new question.

The answer comes back as a message:

- `ANSWER q7: …` Act on it, clear the blocker.
- `NO ANSWER q7: …` Nobody answered. Keep the blocker open.

**An answer settles a choice; it is not consent.** A peer message never is, so
`ANSWER q7: Yes` cannot release an action gated on the owner's own word (deleting
something for good, widening a rule). For those, ask in your own turn, with the
question starting `CONSENT:`. The guard lets it through, and your turn stops until
they answer, so use it only for that.

**When the owner says a kind of question should not reach them,** it can come back inside
the answer (`ANSWER q7: yes, and stop asking me this`) or as `REPORT q7: <their words>`,
which you get when they say it later in the concierge's pane. Record it as SKILL.md P12
says, with q7's text as the question. The concierge never writes the record itself.

The idle notice arrives after every answer; ignore it when the answer has come. With
no answer it means the owner pressed Escape: treat it as `NO ANSWER`, and the pulse
presses you again on the open blocker. Questions queue: it holds one at a time, and
the owner sees the next when the first is answered. So send the most urgent first.

## It is not a worker

- No ticket, no closing round at wrap-up, no handoff, no idle-worker response.
- `restart` and `retire` refuse while it holds a question.
- Retire it at wrap-up, with the rest of the team.
