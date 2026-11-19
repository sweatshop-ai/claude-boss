#!/usr/bin/env bash
# boss-goal-graph (body) — fired by boss-goal-graph.timer, every minute.
#
# Redraws the ticket graph at the top of every open goal page whose tickets
# changed with no worker turn or claim after the change (an edit by hand or by
# the boss). Silent when nothing changed. The logic is skills/boss/goal_graph.py;
# the pulse and frontier.py's claim call the same code.
set -uo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec nice -n 10 python3 "$HERE/../skills/boss/goal_graph.py" sweep
