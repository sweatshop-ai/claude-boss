# 39: a question through the concierge names its boss and holds one question

**What to build:** (1) Every question the owner sees through a concierge names the boss that wrote it and its track, in the question text itself. The boss writes it (`concierge.md`, `SKILL.md`, `escalation.md`); the concierge cannot know it. When it is missing the concierge still asks, with one line before the sender's text, `From <the sender's name>, the boss that sent this question.`, and changes nothing else, so "sender's text unchanged" stays true. (2) One question per `ASK` and per `AskUserQuestion` call. (3) Tests.

Why (the owner, 2026-11-05): a boss's question reached them through its concierge, a Sonnet pane with its own name. They read it as a lesser worker asking them things and asked why a worker asks and not the boss. The text was the boss's, unchanged; nothing on it said who wrote it. That boss also sent four questions in one call, though the brief says "one question".

**Blocked by:** None (can start immediately)

**Claimed by:** Thea 2026-11-05 18:30

**Status:** done

**Merged:** PR 73, merge commit fbb5220 (head 68300b4), 2026-11-05. Codex owed until 2026-11-11.

**Decision, several questions in one `ASK`:** the concierge asks them one at a time, in the order sent, each in its own call, and replies after each answer, `ANSWER <id>.1:`, `ANSWER <id>.2:`; one left open, and every one after it, reads `NO ANSWER <id>.<n>:`, and the boss clears the blocker only when all have an `ANSWER`. The sender's address is a socket path, so the line does not show it. Reason: sending the message back costs the boss a turn to rewrite and resend, and a boss that never reads the reply loses the question; the concierge already queues questions one at a time, so asking in turn never drops one and never stops the boss. The `ASK <id>:` line keeps its shape, because the weekly routine counts questions by `ASK_MSG`.

- [x] The brief says what the concierge does with a question that names no boss, and with several questions.
- [x] `concierge.md`, `SKILL.md` and `escalation.md` tell the boss to open with its name and track and to send one question per `ASK`.
- [x] A test holds those sentences in the three texts.

Codex owed: out until 2026-11-11 08:36; reviewed by a fresh Opus agent meanwhile.
