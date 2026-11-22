# 04: A broken deploy list is not a CI wait

**What to build:** since merge-flow 03 the gate refuses as `ci-not-green` when `.boss/deploy.json` cannot be read
or is invalid, because its `required_checks` cannot be known. SKILL.md tells the boss that `ci-not-green` means
"wait for the run", and the pulse re-runs the dry run on every PR each time, so a broken deploy file looks like CI
that never finishes. Give it its own reason (for example `deploy-list-unknown`, still exit 3), keep a transient read
failure apart from an invalid file, and have SKILL.md say that an invalid file goes to the owner.

Found by the fallback review of PR 182 (round 2, head 9e52852), minor.

**Blocked by:**
- 03: The merge gate refuses unless the head's CI is complete and green

**Status:** ready-for-agent

- [ ] A test: an invalid deploy list refuses with its own reason, and the dry run says it
- [ ] SKILL.md, "Merge on the pulse": what the boss does with that reason
