# PR 69 (ticket 32, part 3): review

Final head: see the PR. Three rounds, the hard limit; the last found nothing in class a or b. Reviewers: `mattpocock-skills:code-review` (Standards and Spec once, fresh Opus agents) and two further fresh Opus bug hunts. **Codex owed** (it was out until 09:41). Name grep on the added lines: no hit.

## Round 1 (db3fc00): Standards and Spec
- Standards: no breach of a documented standard; only class d (header lists of env knobs, test duplication, naming). Header fixed; the rest is in ticket 32.
- Spec: lines 12, 13, 14, 16 meet the spec (VERIFIED: bin/boss-link `check_units`; the three `Environment=CLAUDE_CONFIG_DIR=@CFG@` lines; `unsent` queue in `boss_efficiency_core.py`; item 5 not built with a measured reason).
- **b, fixed (43187dc):** `timeout -k` exits 137 when the scan ignores the TERM, and the body alerted only on 124. VERIFIED at `routines/boss-efficiency.sh:60`; test `test_a_scan_that_ignores_the_first_signal_is_alerted_too` failed before.
- Does not reproduce: a rerun of a week leaves a duplicate `unsent` entry. The retry at the start of the run sends and clears the old entry first; `test_a_rerun_of_the_week_that_gets_through_drops_its_unsent_entry` passes on the old code too and stays as a guard.
- c, d: unquoted `Environment=` with a space in the path; dry run skips `unsent` silently; test duplication and naming. Ticket 32.

## Round 2 (43187dc): bug hunt
- **b, fixed (3eccc7c):** a masked unit (link to `/dev/null`) was reported missing every session start. VERIFIED at `bin/boss-link:54`; `test_a_masked_unit_is_the_owners_choice_and_is_not_reported_missing` failed before.
- c: three edges of the `unsent` queue (state written late, label replaced only on failure, hand-edited state without `text`). Ticket 32.

## Round 3 (3eccc7c): the last commit
- Nothing in class a or b. `[[ -L ]] && continue` is safe under `set -e`. c, d: a linked unit is skipped whole; the test covers only the `/dev/null` link. Ticket 32.

Verdict: no open class a or b. 131+ tests in `test_bin.py` and `test_boss_efficiency.py` pass locally (132 with the new ones).
