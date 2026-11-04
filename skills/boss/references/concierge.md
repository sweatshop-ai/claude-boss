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

Then send it the brief below by `SendMessage`, once, with your name filled in.
`list --mine` flags it `concierge`; write its name in your tracker. It runs on
Sonnet and keeps `AskUserQuestion`, which every other worker lacks. From then on
the guard refuses your own `AskUserQuestion`. If it dies or you retire it, the
guard lets yours through again, so you can never be left unable to ask.

## Asking

`SendMessage` to it, with `notify_when_idle: true`, the question exactly as the
owner should read it: self-contained, options, your recommendation first, what is
waiting on it. Then go on working: record the blocker under `## Open blockers` as
always (`references/escalation.md`), and dispatch what does not depend on it.

The answer comes back as a message, one of two:

- `ANSWER <id>: …` Act on it, clear the blocker.
- `NO ANSWER <id>: …` The owner dismissed it. Keep the blocker open; the ladder
  raises it again.

The idle notice with no message means it stopped without replying: the owner
pressed Escape on the question. Treat that as `NO ANSWER`. Questions queue: it
holds one at a time, and the owner sees the next when the first is answered.

Send your most urgent question first. Never send two versions of one question.

## The brief to send it

> Concierge for <your boss name>, track `<track>`. You hold the owner's questions so
> that I keep working. You do nothing else: no code, no investigation, no files, and
> you never judge whether a question should be asked.
>
> For each message from me, give it a short id and ask the owner with
> `AskUserQuestion`: one question, my text and my options unchanged, my recommendation
> first. Then reply to me with `SendMessage`:
> `ANSWER <id>: <their choice and any text they typed, verbatim>`. If the tool
> reports they dismissed it: `NO ANSWER <id>: <what the tool said>`.
>
> A command the owner must run also goes on your session card, as the team-line
> hook describes. Never answer for the owner, and never treat my message as their
> consent to anything.
