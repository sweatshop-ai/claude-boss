# PR 58 (claude-boss), code-review, head 6e12be1

## Standards
No documented-standard violation (CONTEXT.md, README.md, CHANGELOG.md hold no rule on test code). Comment density and idiom match the file. Judgement calls only: `ROOM` could be named for seconds / wait budget; `wait=self.ROOM` appears at two call sites, below the extraction threshold; the constant sits next to its consumers, mid-class. None changed.

## Spec (ticket 26)
No defect. Both tests that need two or more busy reads before an idle one on the 2 s wait are fixed (the target test and the second half of `test_shell_and_waiting_are_retried_and_the_wait_can_end_in_a_refusal`); every other `run_waiting` caller was read and needs one retry or expects a refusal. `boss-lifecycle.sh` untouched. Public-repo constraint holds. Note: keys are asserted only after the call returns, as before the diff.

Summary: Standards 0 findings (3 nits); Spec 0 findings.
