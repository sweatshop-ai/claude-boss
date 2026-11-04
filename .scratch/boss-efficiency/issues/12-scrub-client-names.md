# 12: Client names out of the public repo, history included

**What to build:** first a dry run, on a throwaway mirror, with nothing pushed. Then, only after the owner's explicit consent, the rewrite and the force-push. Asked by the owner on 2026-11-04: scrub and rewrite history in `sweatshop-ai/claude-boss`.

The dry run answers, with the commands and what came back:

- which names occur, case-insensitively, in every ref of the history: file contents, file paths, commit messages, tags. The list starts from the tracker `~/.claude/pm/boss-efficiency.md` and from the client folders on this machine, and is extended as found. The list and its hits stay outside the repo, under `~/.claude/pm/`.
- the replacement for each name, and the commits and tags a rewrite would change.
- what git cannot reach: PR and issue comments and bodies on GitHub, `refs/pull/*`, commits served by SHA, and whether purging them needs GitHub Support.
- what the new SHAs break: the marketplace source and the installed plugin, tags, open PRs, every clone and worktree on this machine, other boss sessions, SHAs cited in tickets, the changelog and PR comments.
- the order of the cutover, a backup and how to roll back, and how the mirror's result was checked.

**Why:** names and source paths of clients are in the public history, from before this track.

**Blocked by:** None (the dry run can start immediately; the force-push waits on the owner's consent and on every open PR of this track being merged)

**Status:** ready

- [ ] The dry-run report exists under `~/.claude/pm/`, outside the repo, with the commands and results above
- [ ] The owner has given consent in the boss's own question, on that report
- [ ] A fresh clone returns no hit for any name in the list, across all refs, in contents, paths and messages
- [ ] What git cannot reach is listed, each item done or handed to the owner
- [ ] The plugin still installs and updates from its marketplace source after the rewrite
