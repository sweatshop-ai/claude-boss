# Pre-mortem

You are reading the standing objective of a `/boss` session that coordinates
several Claude worker sessions on the owner's laptop. The boss is about to work
from it for hours. Your job is to list the ways this track could go wrong, so the
owner only has to strike out the ones that do not matter.

**Imagine it is a week from now and the track failed.** The criteria were ticked,
or the work was abandoned, and the owner says it went wrong anyway. List as many
distinct, concrete ways that could have happened as you can find.

Quantity first. Do not filter for plausibility and do not propose fixes: the owner
filters, and the boss writes the fixes. A risk you leave out is one nobody
considers; a risk you include costs the owner one number to strike.

Look in every direction:

- the outcome reached but the wrong problem solved, or solved for the wrong user
- data already there: migrations, backfills, formats, what an old record looks like
- isolation and permissions: one user, owner or tenant seeing or changing another's
- security: secrets, tokens, what leaves the machine, what a hostile input does
- deploys: what runs in production afterwards, and how anyone would know
- regressions: what worked before and has no criterion saying it still works
- people: an approval that never comes, a reviewer who reads it differently
- dependencies and timing: another track, another boss, an external service, a deadline
- the workers themselves: a plausible wrong answer reported as done, work lost on a branch
- cost: tokens, money, hours of the owner's attention

If you can read files in your working directory, read the code and documents the
objective names and ground risks in what is actually there. Mark a risk you
confirmed in a file with `[seen: <path>]`.

**Answer in this shape, nothing else — no preamble, no code fence:**

```
RISK: <what happens> — <what triggers it>
RISK: <another>
```

One line per risk, at least eight and at most twenty-five. Each names a concrete
consequence, not a category: "the backfill assigns every old memory to the first
user", not "data migration risk".

---

TRACK: {{TRACK}}
OBJECTIVE:
{{GOAL}}
