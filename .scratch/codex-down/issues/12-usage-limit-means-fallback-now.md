# 12: A usage limit means the fallback now, not a wait

**What to build:** the boss skill's Codex routine ("Codex is the external reviewer, twice") still tells the worker to type `codex exec -s read-only ... < /dev/null` by hand, and says nothing about a usage limit. On 2026-10-21/22 that cost a morning: Codex hit its limit ("try again at 2:41 AM", then "12:44 PM"), and workers and the boss scheduled waits for the reset instead of reviewing with Opus. The owner (2026-10-22): "It should be generalized that codex falls back to opus when it's out of tokens", and chose to route the boss skill's reviews through a runner rather than a global `codex` wrapper.

**Scope:** until 02's `boss_review.py` and 08's fallback reach `main`, the skill text must already say: a usage limit or an outage means the labelled fallback review in the same turn; the reset time Codex gives goes in the review file's header and is never a time to wait for; no wakeup or loop is scheduled for Codex. Once 02 and 08 are on `main`, the routine names `boss_review.py` instead of bare `codex exec`, and this ticket's interim sentence goes. The owner's personal runner (`~/.claude/skills/codex-review/codex-review.sh`, exit 7 on a usage limit, commit e1d02c4 in the owner's config repo) is the model for the wording, but it is not shipped with the plugin, so the skill cannot depend on it.

**Blocked by:** None for the interim text; the switch to `boss_review.py` after 02 and 08.

**Status:** ready-for-agent

- [ ] SKILL.md's Codex routine says, in one or two sentences: on a usage limit or an outage, run the labelled fallback review in the same turn; never wait for the reset, never schedule a wakeup or loop for it
- [ ] After 02 and 08 merge to `main`: the routine names `boss_review.py`, and no line of SKILL.md tells a worker to run `codex exec` by hand for a PR review (`grep -n 'codex exec' skills/boss/SKILL.md` shows none in the review routine)
- [ ] The plugin version is bumped and the change is in the marketplace release, so the installed boss skill carries it
