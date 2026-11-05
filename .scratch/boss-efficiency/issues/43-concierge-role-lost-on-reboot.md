# 43: A concierge's role does not survive a reboot

**What to build:** after a reboot a concierge must come back as a concierge. The machine rebooted at 16:01 on 2026-11-05. Pane stamps and `@worker_role` are tmux state and are gone with the tmux server, so `claim` makes the concierge an ordinary worker, and `--concierge` refuses `claim` by design (`skills/boss/bin/boss-lifecycle.sh:91`). The boss set the role by hand with `tmux set-option`. Effect: no `[concierge]` label, and the guard no longer sees it. Decide where the role is kept (the registry, or a flag `claim` accepts for a name that was a concierge) and test the path through a reboot-shaped case: a fresh tmux server and a claim for a name that was a concierge.

Ready for a worker when picked, but a small one.

**Why:** the label and the guard depend on a mark that a reboot erases.

**Blocked by:** None (can start immediately)

**Claimed by:**

**Status:** ready-for-agent

- [ ] Test first: after the tmux state is gone, claiming a concierge's name gives it the concierge role again
- [ ] `--concierge` on `claim` is still refused where it was refused (line 91), or the refusal is changed on purpose and the test says why
