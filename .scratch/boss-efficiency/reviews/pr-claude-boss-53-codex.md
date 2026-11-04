# Codex review, claude-boss PR 53, merge de0e2ca (base baf92e0)

Goes to OpenAI through the Codex CLI (read-only sandbox)
repo:  /home/tiroir/Projects/boss-plugin-wt/Elke-claude-boss
scope: base baf92e0
diff:  5 file(s), 81 changed line(s)
files:
  routines/boss-efficiency.md
  routines/boss-efficiency.sh
  routines/boss_efficiency_core.py
  skills/boss/test_boss_efficiency.py
  systemd/boss-efficiency.service.in
Codex reads with your user's rights: it can open any file on this machine, not only under /home/tiroir/Projects/boss-plugin-wt/Elke-claude-boss.
The secret check covers the diff listed above, not what Codex opens on its own.

The memory limit works for fresh installations but is not propagated through the repository's documented upgrade mechanism, leaving existing users uncapped.

Review comment:

- [P2] Propagate the memory cap to installed units — /home/tiroir/Projects/boss-plugin-wt/Elke-claude-boss/systemd/boss-efficiency.service.in:16-16
  For existing marketplace installations, this template is not rendered again: `install.sh` copies it into `~/.config/systemd/user` only once, while upgrades merely retarget the stable plugin symlink, and README.md:85-90 explicitly says installation need not be rerun. Consequently, upgraded users retain the old uncapped service and never receive this protection; add an upgrade path that rewrites and reloads the installed unit.
