# 01: The goal page carries its ticket graph, kept up to date

**Status:** ready-for-agent

**Why (2026-11-19, Thierry):** boss tracks keep their tickets in local markdown, and the graph of those
tickets goes **in the goal page** (`<pm>/<track>.goal.md`, opened through sheaf), drawn by fixed rules and
updated on the fly. This replaces agentview ticket boss-track/28.

**What exists:** `frontier.py --json <source>` gives every ticket with `state` (ready, claimed, waiting,
done), `claimed_by`, `blocked_by`, `open_blockers`, `external`; a `gh:owner/repo#N` source gives the same.
`boss-pulse.py` reads it each time a worker goes idle (`read_frontier`). sheaf renders a ```` ```mermaid ````
block through `mmdc` (installed, 11.12.0), caches the SVG by source, and reloads an open page when the
file changes on disk, merging a save from the page paragraph by paragraph (SPEC 7.3, D22, D23).

## The fixed rules

1. **Place.** One section `## Ticket graph`, right after `## Tickets`. Inside it, one block between
   `<!-- ticket-graph:start -->` and `<!-- ticket-graph:end -->`. A goal without `## Tickets` gets none.
2. **Ownership.** Only the generator writes between the markers. The start marker says so in one line;
   anything typed there is overwritten at the next write. Nothing outside the markers is ever touched.
3. **Form.** ```` ```mermaid ```` `flowchart LR`. One node per ticket, id `t<num>`, in ticket order; label
   `<num> · <title>` with the title cut at 48 characters (backticks and quotes taken out), and on a second
   line the state word: `ready`, `<worker>` for claimed (the name from `claimed_by`, no date), `waiting`,
   `done`.
4. **Edges.** One edge `t<blocker> --> t<ticket>` per entry of `blocked_by` within the source. An external
   blocker is a node of its own, `x<n>`, dashed, labelled with the blocker's text, with an edge to the ticket.
5. **Colours, by state, never anything else:** done green, claimed blue, ready amber, waiting grey,
   external red dashed. Given as four `classDef` lines and one `class` line per state, the same in every
   goal, readable in sheaf's light and dark theme.
6. **Under the diagram, one line:** `n tickets: d done, c in progress, r ready, w waiting` and the time of
   the frontier read (`HH:MM`). A broken source (exit 2) leaves the last graph standing and puts the
   error on that line.
7. **Deterministic.** The same frontier gives the same bytes. The file is written only when the block
   differs from what is there, so an unchanged frontier never reloads the page nor re-runs `mmdc`. The
   read time on the line in rule 6 changes only when something else in the block does.

## When it updates (on the fly)

- **The pulse**, after every `read_frontier` of a track: a worker going idle follows every ticket edit.
- **`frontier.py claim`**, after a claim it made: the worker's name shows the moment it is given the ticket.
- **A one-minute sweep** over the open tracks (the same timer family as the other boss routines), for an
  edit made by hand or by the boss with no worker turn after it. Silent when nothing changed.

## How it writes

The write replaces only the text between the markers, through the track store (`boss_store`, read, swap
the block, write via a sibling file and rename, under the store's `flock`), checks that the file still
holds the text it read just before the rename, and retries once if not. Never a whole-file rewrite from a
template: Thierry edits the goal page, and sheaf merges his save with this write by paragraph.

## Done when

- [ ] A goal with `## Tickets` has `## Ticket graph` with the block; one without is left alone
- [ ] A fixture frontier gives a block equal byte for byte to a checked-in expected file (all four states,
      one external blocker, one ticket blocked by two)
- [ ] An unchanged frontier writes nothing (mtime unchanged); a changed state rewrites only the block,
      and a paragraph Thierry typed elsewhere in the goal survives it
- [ ] The pulse, `claim` and the sweep each update the block; the sweep is silent on no change
- [ ] A broken source keeps the last graph and shows the error on the summary line
- [ ] Checked on a live goal in sheaf: the page reloads with the new graph after a ticket's Status changes
- [ ] CHANGELOG entry and a release; tests run on t-compute CI, only the touched files locally
