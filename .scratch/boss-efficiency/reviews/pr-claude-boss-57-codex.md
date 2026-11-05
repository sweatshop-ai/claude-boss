# Codex review, claude-boss PR 57, merge f9c27a6 (first parent as base)

Run 2026-11-05 by Britt for ticket 10. Raw Codex output below, then the answers.

Goes to OpenAI through the Codex CLI (read-only sandbox)
repo:  /home/tiroir/Projects/boss-plugin-wt/Britt-cr3
scope: base f9c27a6^1
diff:  3 file(s), 113 changed line(s)
files:
  routines/boss-efficiency.md
  routines/boss_efficiency_core.py
  skills/boss/test_boss_efficiency.py
Codex reads with your user's rights: it can open any file on this machine, not only under /home/tiroir/Projects/boss-plugin-wt/Britt-cr3.
The secret check covers the diff listed above, not what Codex opens on its own.

Reference extraction can mistake arbitrary transcript content for a session's own ListAgents identity, causing valid ref-qualified sends to lose worker attribution.

Review comment:

- [P2] Restrict reference extraction to ListAgents results — /home/tiroir/Projects/boss-plugin-wt/Britt-cr3/routines/boss_efficiency_core.py:231-233
  This scans every raw JSONL record, including Bash output, assistant text, and context blobs, rather than verifying a `ListAgents` tool result. For example, a worker named `Mira` that reads the new test file will record the fixture's `This session is Mira [ab12cd]` as its own ref; a later send to its real ref is then rejected by `_attribute_by_name`, dropping that worker's attribution. Associate the result with a preceding `ListAgents` tool use before recording the ref.

## Answers

Verdict: GO with one follow-up. Class a/b/c/d: 0/1/0/0. Citation VERIFIED at the merge commit (f9c27a6, `routines/boss_efficiency_core.py:231-233`) and on main (line 236, unchanged); not fixed by a later PR. In ticket 38.

- [P2] `routines/boss_efficiency_core.py:231-233`, the own-ref extraction scans every raw record containing "This session is ", not only a ListAgents result; a worker that reads the test fixture holding such a line records a false ref for itself, and later ref-qualified sends to its real ref lose attribution. Class b (needs a worker of the same name as the fixture's reading that file). Ticket 38.
