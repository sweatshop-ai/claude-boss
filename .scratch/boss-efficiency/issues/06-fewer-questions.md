# 06: Fewer questions reach the owner

**What to build:** a measured way to send back what is not the owner's. A prompt filter was tried on 87 labelled questions and failed: it sent back 14 of 50 of the owner's, one of them an irreversible deletion, and let through 23 of 37 of the rest. Try Jev, on labels the owner gave, with a confidence threshold below which the question always goes through. Redact first: the text leaves the machine.

**Correction, 2026-11-05:** the 87 labels are a model's classes, not the owner's, so they cannot be reused as his labels. "The owner's" above means the 50 a model classed as HAND (25) or DECISION (25); "the rest" means the 37 it classed as TECH (12), APPROVAL (12), INFO (8) or PREMORTEM (5). The filter's 14 of 50 and 23 of 37 measure agreement with that model, not with the owner. New labels are needed: a sample of 20.

**Why:** 18 questions per active day. About 38% break the rule "only when blocked", by a model's reading of their first lines, which is itself unreliable.

**Decided, 2026-11-05.** Thierry labelled 20 of the 87, in his words: 2 should not have reached him, 4 he could not judge, 14 should have. "So there are not many. I think probably my input is not very useful in this case, but maybe we should instead build a system where I can report when you ask me a question, I can say after I have answered something like, I shouldn't answer this kind of question in the future. You can take the decision yourself."

- Against his labels the model's classes are wrong in both directions: of the 8 it called not his, he kept 5 as his, called 1 not his and could not judge 2. So the 38% above is too high: on this sample 10%, 30% at most counting every unsure one. 20 questions is a small sample.
- The decision he left to this session: no Jev filter. Two clear cases cannot measure a threshold, and the gain is small against the risk of returning an irreversible action. This ticket now builds his report instead.

**What to build instead:**

- After answering, or at any later moment, the owner can say in plain words that this kind of question should not reach him. No command to remember, in any of his languages.
- The session records one line: date, session, the question, his words. In a private file under `~/.claude/pm/`, never the repo. It also works when the answer came through the concierge.
- The session does not put that kind of question to him again in that track, and says so in one line.
- The weekly efficiency routine (ticket 04) counts the reports and, when one kind recurs, proposes a rule for the skill. A rule still goes through the normal review; no question is filtered automatically.
- These reports are labels from the owner, given when he is in the moment, so Jev can be measured on them later if enough pile up.

**Blocked by:**
- External: the first time the owner makes such a report in a real session, after they update the plugin (ticket 21); Anton reads the line it wrote

**Claimed by:**

**Status:** waiting. Merged as 5afec09 (PR 71); the live test is the owner's first real report

- [x] The owner labels a sample of past questions
- [x] Measured on it: the sample holds too few of the other kind to measure a filter, so none is built
- [ ] A report in plain words is recorded and honoured in the track, tested in a live session
- [x] The weekly routine counts the reports (PR for this ticket)

## Left over from review (2026-11-05)

- The live-session test is owed: a temp config has no login and credentials are not copied. It happens the first time the owner makes such a report in a real session, after they update the plugin; read the line `boss-unask` wrote.
- The weekly windows are `[now-7d, now)`, not tied to the Monday timer: a late run leaves a gap, the next overlaps.
- `TRACK_RE` in `boss_store.py` ends in `$` and accepts a trailing newline.
- Kind slugs are free per session; two names for one kind under-count. Look again when real reports exist.
- Should it also hold outside boss sessions? That would be a rule in `~/.claude/CLAUDE.md`; not changed here, for the owner to decide.
