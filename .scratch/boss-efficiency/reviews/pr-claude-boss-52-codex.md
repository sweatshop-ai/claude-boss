# Codex review, claude-boss PR 52, merge 063b2d8

Run 2026-11-05 by Britt for ticket 10. Raw Codex output below, then the answers.

Goes to OpenAI through the Codex CLI (read-only sandbox)
repo:  /home/tiroir/Projects/boss-plugin-wt/Britt-cr2
scope: commit 063b2d8
diff:  8 file(s), 408 changed line(s)
files:
  .scratch/boss-efficiency/issues/22-lifecycle-follow-ups.md
  CHANGELOG.md
  skills/boss/SKILL.md
  skills/boss/boss-lifecycle.sh
  skills/boss/boss-panes.py
  skills/boss/test_boss_lifecycle.py
  skills/boss/test_transcript.py
  skills/boss/transcript.py
Codex reads with your user's rights: it can open any file on this machine, not only under /home/tiroir/Projects/boss-plugin-wt/Britt-cr2.
The secret check covers the diff listed above, not what Codex opens on its own.

The production changes appear sound, but the revised retry timing makes two success-path tests flaky because their wall-clock budget has no allowance for command overhead.

Review comment:

- [P2] Give two-retry tests a larger wait budget — /home/tiroir/Projects/boss-plugin-wt/Britt-cr2/skills/boss/test_boss_lifecycle.py:312-312
  On slower CI runners, the helper allows exactly two seconds while successful three-row sequences require two one-second sleeps. Time spent reading the first retry can make `SECONDS - t0` reach 2 before the second iteration, so the final idle row is never read and the tests at lines 315 and 346 fail intermittently; give those success cases a larger wait budget.

## Answers

Verdict: GO. Class a/b/c/d: 0/0/0/1.

- [P2] `skills/boss/test_boss_lifecycle.py:312`, the two-retry success tests have a 2 s wall-clock budget against two 1 s sleeps. Class d (test flake). Citation VERIFIED at the merge commit (063b2d8, the `run_waiting` helper, `wait="2"` default). Already fixed by PR 58 (af13162): the two tests take `wait=self.ROOM` ("30") on main. No ticket.
