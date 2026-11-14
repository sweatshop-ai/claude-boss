# Handoff: Otilia, 2026-11-14, paste-first rule (PR 152, 0.24.0)

**Done.** PR 152 merged as e446d9cad24f4d32761a51e3ff966907342d4c77, plugin 0.24.0, CI pytest green on c59a5f0. Bosses make the Paste on their own card before any ASK or AskUserQuestion with a `$ ` command; `boss-guard.py` (now also on SendMessage) denies one that names no Paste; concierge-brief.md has the backstop; 59 tests in `skills/boss/test_boss_guard.py`. Plugin cache updated to 0.24.0, `install.sh` re-run from it, timers enabled. Signe restarted by Petra; the other bosses are Thierry's to restart.

**Review.** Standards + spec reviews done. Codex was out of tokens (exit 7, reset 20:00 on 2026-11-14), so a fresh Opus agent did the bug hunt: GO 44d3411, two P2 fixed, delta check GO c59a5f0.

**OWED: Codex follow-up.** Run `/codex-review` (`--commit e446d9c` or `--base e446d9c^` from a clean worktree) once Codex is back; its findings become tickets, not a revert. Not run: Thierry's rule is not to wait for a Codex reset, so the follow-up was left owed instead of scheduled (Petra's fallback, 2026-11-14).

**Known limits (accepted).** The check is on text: any word "paste" clears it; a pasted shell transcript with `$ cmd` in an ASK trips it. The concierge's own AskUserQuestion is not guarded (it is no registered boss).
