# 21: The weekly routine runs on this machine

**What to build:** nothing; a check. The timer exists on this machine only after the owner updates the plugin and runs `install.sh`. Then confirm the timer is enabled, read its first run, and confirm a quiet week stays silent. Do it after ticket 12's rewrite, which changes the commit the plugin installs from.

**Blocked by:**
- External: the first run of the timer, Mon 2026-11-09 06:17; its report is what the second box waits on

**Status:** waits for the first run (Mon 2026-11-09 06:17)

- [x] `systemctl --user list-timers` shows the timer enabled (the owner ran install.sh on 2026-11-05 at 19:24: boss-efficiency.timer enabled, next run Mon 2026-11-09 06:17)
- [ ] The first run's report exists and its coverage line is there; the run was silent or said why not
