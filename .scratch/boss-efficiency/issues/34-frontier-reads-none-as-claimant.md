# 34: frontier.py reads any "Claimed by" value, "none" and "nobody" included, as a claimant

**What to build:** `skills/hand-to-boss/frontier.py` sets `claimed_by` to whatever follows `**Claimed by:**` and calls the ticket Claimed when that string is non-empty (`classify`, `elif t["claimed_by"]`). Two consequences, both seen on 2026-11-05:
- `frontier.py claim <dir> 33 Adnan` on a ticket written `**Claimed by:** none` exits 3 with "33 is already claimed by none"; the claim had to be written by hand.
- The listing of `.scratch/boss-efficiency/issues` prints `Claimed: ..., 27 (nobody), 28 (nobody), ...`. Tickets 27 and 28 carry `**Claimed by:** nobody` and `**Status:** waiting` (blocked by time), so they are listed as Claimed with a claimant who does not exist, and a ticket with `none` or `nobody` and no other blocker would never show as Ready.

Fix to decide: treat an empty value, `none`, `nobody` and `-` (any case) as unclaimed, in `parse` or in `classify`; then say which words the ticket template may use. Not fixed in the PR that found it.

**Blocked by:** None (can start immediately)

**Claimed by:**

**Status:** ready

- [ ] Test first: a ticket with `Claimed by: none` and one with `nobody`, otherwise ready, are listed under Ready and `claim` takes them
- [ ] A ticket with a real name and a date is still Claimed
- [ ] Re-run the listing on `.scratch/boss-efficiency/issues`: 27 and 28 no longer appear under Claimed
