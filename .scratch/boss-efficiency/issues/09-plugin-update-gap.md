# 09: Why the installed plugin fell behind main

**What to build:** a diagnosis, then a check. On 2026-11-04 the installed plugin was 0.19.2 while main had reached 0.20.0: rules merged on 2026-11-02 were not active on the machine they were written for, and nothing said so. Find out why, and have something report a gap between installed and released.

**Blocked by:** None (can start immediately)

**Claimed by:** Ruben 2026-11-04 20:52

**Status:** done

- [x] The cause is named, with evidence (PR 47 body: install record timestamps, unpinned third-party marketplace, no tag after v0.5.0, .in_use pids)
- [x] A gap between installed and released version is reported where the owner sees it (boss-version-gap at boss session start, said once in the first reply; PR 47, CI green on 06cc852, gate-ready pending Codex follow-up)
