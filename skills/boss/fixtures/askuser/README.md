Real PostToolUse payloads, captured 2026-11-12 from a throwaway interactive Claude Code 2.1.311 session
(hook command: `cat >> dump.jsonl`), one per button pressed. Ids, paths and the prompt id are replaced by
placeholders, and the typed text in `post-ask-free-text.json` by a neutral phrase; nothing else is edited.

- `post-ask-yes.json`, `post-ask-no.json`: the selected button's label is the value in `tool_response.answers`,
  keyed by the question text (it is in `tool_input.answers` too).
- `post-ask-free-text.json`: a typed answer lands in the same place as the typed string, so it cannot be told
  from a button by the payload. `annotations` is empty in all three.
- `post-bash-in-subagent.json`: a tool call made by a subagent carries the PARENT's `session_id` plus
  `agent_id` and `agent_type`. A subagent therefore has no id of its own at the hook.
