# 50: The merge gate learns review-by-risk rules 2 and 4

**What to build:** `skills/boss/boss_merge.py` lets through what the owner's review-by-risk rules (ticket 49) allow:
1. Rule 4: `--merged-base-since SHA`. A live head that is the GO'd head SHA plus a merge of the base passes when the PR's own files are byte-identical at both heads.
2. Rule 2: a provisional GO on a deploying base merges when the PR is tests-only or docs-only and CI is green.
3. `boss_review.py`: a flag to run Opus directly for such a PR (follow-up below, not small).

**Status:** done

## Decisions

- **Rule 4 takes an explicit flag, not a guess.** The boss names the GO'd head, as `--test-only-since` does, and the two flags are exclusive (exit 2 together). SHA is held to the same conditions (a GO `decide` allows, no NO-GO above it), and the check runs only on `no-round`.
- **How "only by merging the base" is checked, from GitHub, never from a local clone.** Three compares: `SHA...head` (what differs between the GO'd and the live head, with its commits), `base...head` and `base...SHA` (the PR's own files at each end, a rename by both names; status `diverged` is allowed there because the base moves). Pass iff the first is `ahead`, lists all its commits, holds a commit with two parents, and no PR file (at either end) is among the files that differ. The "PR's own files" are by definition everything that differs from the base, so a conflict resolution or a plain commit that changed anything of the PR shows in the set; the files a merge of main brings in are not the PR's and do not count. Refusals: compare failed, truncated (300 files), not ahead, commits cut short or unlisted, no merge commit, a PR file differs.
- **Rule 2 is automatic, no flag, and only for a provisional GO.** It fires where `decide` said `deploying-base` for kind `provisional`; there the refusal was exit 4 and stays 4 with the reason when the rule fails. A waived GO is the owner's tests-only call and never qualifies; "no round" and "superseded" are untouched, so zero reviews is still refused.
- **The files are the PR's, base...head** (rename by both names), all matching `test_paths` (from the base's deploy list, as `--test-only-since`) or the docs set. No file, or a truncated list, refuses.
- **Docs are narrow: `README.md`, `CHANGELOG.md`, `docs/*.md`, hard-coded.** SKILL.md is the instructions agents act on, so it is code: `SKILL.md`, `AGENTS.md`, `CLAUDE.md` (any case, any directory) and anything under `skills`, `commands`, `agents`, `hooks`, `.claude`, `.github` are never docs, even under `docs/`. A repo that wants wider docs gets a `docs_paths` key later, from the base's deploy list; not built now.
- **Green CI** is read from `commits/<head>/check-runs`: every run `completed` and `success`, `neutral` or `skipped`, all listed (total equals what came back), and at least one `success` (no check, or only skipped/neutral ones, is not green: nothing ran). Legacy commit statuses are not read.

- **Round 1 (provisional Opus GO, two class b findings, both fixed in round 2):** an instruction file is refused even where a broad `test_paths` pattern matches it; all-skipped checks are not green.

## Done when

- [x] Pure helpers (`is_doc`, `not_docs_or_tests`, `touched_by_the_pr`) and the command tests, written first (DocsAndTests, DocsTestsOnly, MergedBase in `test_boss_merge.py`)
- [x] CHANGELOG (Unreleased), SKILL.md rules 2 and 4 and the gate paragraph say what the gate now does
- [x] The existing 121 tests of `test_boss_merge.py` still pass

## Follow-ups (not fixed here)

- `boss_review.py` flag to run the Opus pass without asking Codex first for a docs/tests-only PR: not small (the fallback chain, the record and the head binding all assume Codex went first), so a ticket of its own.
- A `docs_paths` key in `.boss/deploy.json`.
- Rule 2 does not check that the Opus round was run over the docs/tests diff of this head beyond the head binding `decide` already enforces.
- Legacy commit statuses (not check runs) are not read for CI.
