# Handoff: command for the owner's hand goes on the session card (0.19.1)

Dispatch: Petra, track `action-list`, 2026-11-01. Worker: Santiago.

## What changed

- `skills/boss/references/escalation.md`, Rules: the single source. A command only the
  owner can run is carried in the question, as a Paste on the session card (agentview
  `hooks/paste create … --provider claude`), and after `$ ` in the team-line `--ask`.
- `skills/boss/SKILL.md`: P12 points to that rule; the "only their hand can do" paragraph
  under worker trust points to P12.
- Version 0.19.1 (`.claude-plugin/plugin.json`, `CHANGELOG.md`). The marketplace entry in
  `sweatshop-ai/cc-agent-names` carries no version, so nothing to bump there (0.19.0 did
  the same: 7c29c49).

## Review

Matt code-review, both axes. Applied: duplicated rule collapsed into escalation.md, CHANGELOG
entry given a bold lead and the incident, a no-op sentence cut, "session card" used
consistently. Kept as dispatched: the patch bump, and the full paste-hook path (framed as
agentview's hook on the author's machine). Not changed: the `/autocompact` and REJECT
spots in SKILL.md (not shell commands for the card), and the clipboard line in the
tmux-injection note (it describes damage, not where commands wait).

## Open

- `team-line`, "session card" and "Paste" are not in `CONTEXT.md`, and the skill never
  defines team-line `--ask`. A follow-up could add them to the glossary.
- Installing 0.19.1 on the laptop is the owner's/boss's step; see the PR.
