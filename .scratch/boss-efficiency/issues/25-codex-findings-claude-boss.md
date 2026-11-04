# 25: Codex findings on claude-boss PRs 45, 43, 44, 47 and 53

**What to build:** Codex ran on these merges after three Opus fallback reviews (ticket 10). Each box below was read against the code on main (46c7c3e) and is VERIFIED, with the PR's own text kept in `.scratch/boss-efficiency/reviews/pr-claude-boss-<n>-codex.md`. The findings are fixes, not reverts. Later PRs of ticket 10 (48 to 52) have no Codex run yet; their findings go in a further ticket.

**Blocked by:** None (can start immediately)

**Claimed by:** Anouk 2026-11-05 00:07

**Status:** in-progress

PR 45 (concierge)
- [x] P2 `skills/boss/fleet.py:173-175` and `skills/boss/boss-lifecycle.sh:284`: `concierge_of` skips a concierge waiting on a permission or trust prompt, and `spawn --concierge` reuses the same lookup, so it starts a second concierge. Spawn needs an existence check that counts a prompt-blocked live concierge; the guard and pulse keep the current "holds the question" rule.
- (the watchdog finding on this PR, `boss-lifecycle.sh:239`: fixed already by PR 48, commits cb21bf5 to 29c18a2)

PR 43 (guard counts real work): `skills/boss/boss-guard.py`, `is_coordination`. The guard only warns and logs, so these let real work go unlogged; none is a security boundary. Checked by calling `is_coordination` on each example: all returned True.
- [x] P1 `:143` `sed -i 'w /repo/src/app.ts' ~/.claude/pm/a.md` passes the four-token sed check; the sed program (`w`, `e`) is not constrained
- [x] P1 `:122-125` a heredoc marker inside a comment (`echo x >> ~/.claude/pm/a.md # <<EOF`, then `npm test`, then `EOF`) hides the following lines
- [x] P2 `:141-142` `cat /repo/src/app.ts >> ~/.claude/pm/a.md`: with an approved redirect, `cat`'s input operands are not checked
- [x] P2 `:179-181` a filter after a pipe is accepted with file operands or `<` (`echo x | head /repo/src/app.ts`)
- [x] P2 `:177-178` `cd ~/.claude/pm/missing; echo x > src/app.ts`: a `;`-separated `cd` that fails still marks the cwd as owned
- [x] P2 `:92` `cat <<EOF >> ~/.claude/pm/a.md` is not seen as a heredoc (the regex anchors at the end of the line), so the body is parsed as statements and a legitimate tracker write is flagged

PR 44 (P17 proof)
- [x] P1 `skills/boss/SKILL.md:841-843` the proof asks for an import path, a database URL and a pid; a standalone script, compiled CLI or PATH executable with none of those proves nothing. Ask for the resolved executable path.
- (the database-URL finding on this PR: credentials in a reported URL; fixed by PR 55 (75b06b6))

PR 47 (plugin update gap): `skills/boss/version_gap.py`
- [x] P2 `:88` `_same_process` returns True when the marker has no `procStart` (`want is None`), so a reused pid, a zombie or an orphan counts as a live session. Use `registry.is_live`'s rules.
- [x] P2 `:97-98` the cache's `until` is trusted even if it lies far in the future (clock set back), freezing the release check. Treat `until > now + CACHE_TTL` as stale.

PR 53 (efficiency routine follow-ups)
- [x] P2 `systemd/boss-efficiency.service.in:16` the `MemoryMax=1G` cap reaches only fresh installs: `install.sh` copies the unit once and README.md:85-90 says it need not be re-run after an upgrade, so installed units stay uncapped. Add an upgrade path that rewrites and reloads the unit (e.g. `boss-link` on SessionStart).

PR 56, head aba4258: CI green, code-review and Opus verdict GO (reviews/pr-claude-boss-56-*). Open lows from the verdict, for a follow-up ticket: backslash in a sed program counts as work; unwritable unit makes boss-link exit 1; concierge with no session record skipped by spawn. Codex follow-up owed. Status stays in-progress until merge.
