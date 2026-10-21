# 02: Above five workers, merge in batches or through a queue

**What to build:** with up to 12 workers (0.11.0), ticket 01's overlap rule still serialises
the merges, and every PR waits for its own run on three shared runners. Choose one and build it:

- **Batch branch** (Pocock's `implement-spec`): ready PRs merge onto an integration branch,
  CI runs once there, the branch merges to main. Cost: a red batch has to be bisected.
- **Merge queue**: GitHub's own. Check first whether the org's plan offers it for private
  repos (render-doc's branch protection API answered 403 "Upgrade to GitHub Pro" on 2026-10-21).

Malik (sheaf-v2) keeps the one-at-a-time flow at five workers; the batch earns its
bisect cost only with more PRs in flight.

**Blocked by:**
- 01: Rebase only on a conflict or an overlap

**Status:** needs-grilling

- [ ] Grilling settled the choice, with the plan check done
- [ ] The boss uses it when more than five PRs of one repo wait to merge
