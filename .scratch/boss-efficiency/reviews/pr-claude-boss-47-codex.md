# Codex review, claude-boss PR 47, merge c398114 (base 6877a569df89b6109eb35efb6bb5029ce09fe241)

Goes to OpenAI through the Codex CLI (read-only sandbox)
repo:  /home/tiroir/Projects/boss-plugin-wt/Elke-claude-boss
scope: base 6877a569df89b6109eb35efb6bb5029ce09fe241
diff:  7 file(s), 307 changed line(s)
files:
  .claude-plugin/plugin.json
  CHANGELOG.md
  skills/boss/SKILL.md
  skills/boss/bin/boss-version-gap
  skills/boss/boss_store.py
  skills/boss/test_version_gap.py
  skills/boss/version_gap.py
Codex reads with your user's rights: it can open any file on this machine, not only under /home/tiroir/Projects/boss-plugin-wt/Elke-claude-boss.
The secret check covers the diff listed above, not what Codex opens on its own.
The new checker can misclassify dead or unrelated processes as live sessions and can retain stale release data well beyond its intended TTL after a clock rollback. Both defects undermine the accuracy of its version-gap reporting.

Full review comments:

- [P2] Use the canonical live-session predicate — /home/tiroir/Projects/boss-plugin-wt/Elke-claude-boss/skills/boss/version_gap.py:88-88
  When a stale `.in_use/<pid>` marker lacks `procStart`, this returns true for any unrelated process that later reuses the PID; it also accepts zombies and orphaned CLI sessions. Because the scan targets old version directories, these cases produce false persistent “live session” warnings. The repository’s canonical `registry.is_live` explicitly rejects missing start times, zombies, and terminal sessions without a controlling terminal, so this check should apply the same rules.

- [P2] Expire cache entries after a backward clock adjustment — /home/tiroir/Projects/boss-plugin-wt/Elke-claude-boss/skills/boss/version_gap.py:97-98
  If the cache is written while the system clock is ahead and the clock is then corrected backward, `until` can remain in the future far beyond `CACHE_TTL`, suppressing release checks for hours or days. Treat an implausibly future expiry as stale (or store and validate the fetch time) so a clock correction cannot freeze the version result.

codex-review: output kept at /tmp/codex-review-Elke-claude-boss-20261104T235915-2638168-review.txt (Codex's session log: /tmp/codex-review-Elke-claude-boss-20261104T235915-2638168-review.txt.stderr)
