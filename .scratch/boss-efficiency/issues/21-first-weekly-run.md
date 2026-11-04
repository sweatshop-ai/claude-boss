# 21: The weekly routine runs on this machine

**What to build:** nothing; a check. The timer exists on this machine only after the owner updates the plugin and runs `install.sh`. Then confirm the timer is enabled, read its first run, and confirm a quiet week stays silent. Do it after ticket 12's rewrite, which changes the commit the plugin installs from.

**Blocked by:**
- External: the owner updates the plugin and runs install.sh, after ticket 12

**Status:** waits for the owner

- [ ] `systemctl --user list-timers` shows the timer enabled
- [ ] The first run's report exists and its coverage line is there; the run was silent or said why not
