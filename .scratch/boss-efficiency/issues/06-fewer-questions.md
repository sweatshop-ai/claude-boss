# 06: Fewer questions reach the owner

**What to build:** a measured way to send back what is not the owner's. A prompt filter was tried on 87 labelled questions and failed: it sent back 14 of 50 of the owner's, one of them an irreversible deletion, and let through 23 of 37 of the rest. Try Jev, on labels the owner gave, with a confidence threshold below which the question always goes through. Redact first: the text leaves the machine.

**Why:** 18 questions per active day. About 38% break the rule "only when blocked", by a model's reading of their first lines, which is itself unreliable.

**Blocked by:** None (can start immediately)

**Status:** needs the owner's labels

- [ ] The owner labels a sample of past questions
- [ ] Measured on it: how many of the owner's are sent back. Zero wrongly returned irreversible actions is the bar
- [ ] Built only if the bar is met; otherwise the numbers are recorded and this closes
