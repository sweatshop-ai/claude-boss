# 19: frontier reads lettered ticket ids

**Blocked by:** none

**Status:** in-progress

`skills/hand-to-boss/frontier.py` reads only numeric ids (`TICKET_FILE`, `LEADING_ID`). The codex-down track split 05 into 05a, 05b and 05c on 2026-11-12, so `frontier.py .scratch/codex-down/issues` ignores those three files and shows 05 and 06 as "Ready now" while both wait on 05c. A gate that calls blocked work ready is wrong on the normal path (Chiara's dispatch, task #19).

- [ ] A file `05a-slug.md` is ticket `05a`, and `Blocked by: 05a` resolves to it. `05` and `05a` are distinct tickets. `claim <dir> 05a <name>` works.
- [ ] Tickets sort 05, 05a, 05b, 06 (by number, then letter), in the text and the JSON.
- [ ] An index ticket blocked by its lettered parts is ready only when all of them are done.
- [ ] A lettered id with no ticket file is reported (exit 2), never dropped.
- [ ] Purely numeric tracks behave exactly as before (the existing tests pass unchanged).
- [ ] The PR body holds frontier's output on the real `.scratch/codex-down/issues`: 05c not done, 05 and 06 waiting.
