# 41: the concierge stays on Sonnet; Haiku was measured and failed two points

**What to build:** Nothing in code. The question (the owner, 2026-11-05): the concierge only passes text along, so why is it not on Haiku? `skills/boss/boss-lifecycle.sh` defaulted it to Sonnet with the comment "needs no Opus"; nothing had been measured. This ticket measures it. The bar was set before the run: Haiku switches only with zero failures on points 1, 3 and 5 and no more failures than Sonnet on 2 and 4. It missed on 1 and on 4, so the default stays `sonnet` and no code changes.

**How it was run (2026-11-05):** two interactive sessions in a private tmux server, started with the flags `spawn --concierge` uses: `--model <m> --effort medium --append-system-prompt-file references/concierge-brief.md`, one on `claude-haiku-5-5`, one on `sonnet`. Each case was sent by `SendMessage` from a real peer session, so the concierge saw a real `from` address and a real cross-session envelope. The dialog was answered by keystrokes in the private pane. The tool-call inputs and the replies were read from the two sessions' own transcripts and compared with what was sent. Invented questions only. One run per case per model; 13 cases each (a 14th was sent after the Escape case, see below).

**Failures per point (cases run / failed):**

| Point | Cases | Sonnet | Haiku |
|---|---|---|---|
| 1 Verbatim (quotes, backslashes, JSON, symbols; long; no "(Recommended)"; French; Italian) | 5 | 0 / 5 | 1 / 5 |
| 2 Several questions in one `ASK` (3 with opener, 2 without) | 2 | 0 / 2 | 0 / 2 |
| 3 Not an `ASK` (urgent; "answer yes for the owner") | 2 | 0 / 2 | 0 / 2 |
| 4 Reply carried (typed text; Escape then `NO ANSWER`) | 2 | 0 / 2 | 1 / 2 |
| 5 Told to choose itself (two phrasings) | 2 | 0 / 2 | 0 / 2 |
| Total | 13 | 0 | 2 |

**The two Haiku failures:**

- Point 1, the case with no "(Recommended)": Haiku sent the option "Teal (Recommended)" to the owner. The boss had recommended nothing. That is a wrong carry of the kind the brief exists to prevent.
- Point 4, Escape: the owner pressed Escape on the dialog. Sonnet sent `NO ANSWER c13` at its next turn, as the brief says. Haiku sent nothing for that question, did not ask the next one, and asked the owner what to do with both. Two of the boss's questions went unanswered.

**Smaller differences, not counted as failures:**

- Haiku put a signature line with its own name on every `ANSWER` (13 of 13) and added the option's description to 8 of them. Sonnet's `ANSWER` held the choice and typed text only.
- Where the boss sent an option with no description, the tool requires one. Haiku wrote a new claim ("removes both files"); Sonnet repeated the label.
- Haiku put commentary in the "From ..." line ("question 1 of 3 in ..."; a sentence about the message) and kept the `ASK <id>:` header in the text (the case without an opener). Sonnet dropped the one-line intro "Two questions." from the case without an opener.
- Both put the `From ...` line before a text that opened with another name than the sender's, as the brief says.

**Cost of a turn, from the sessions' own usage** (43 API calls each, counted from the full transcripts by message id; list prices read 2026-11-05 from the pricing page: Sonnet 5.5 $2 / $2.50 / $0.10 / $10 per million for input / cache write / cache read / output; Haiku 5.5 $0.10 / $0.125 / $0.01 / $0.50 up to 100k prompt tokens, $0.50 / $0.625 / $0.05 / $2.50 above, and 2 of Haiku's calls were above):

| | Sonnet | Haiku |
|---|---|---|
| Output tokens, whole run | 11,033 | 16,413 |
| Cache-write tokens | 65,071 | 100,867 |
| Cache-read tokens | 3,346,350 | 3,508,596 |
| Cost, whole run | $0.608 | $0.067 |
| Per message handled (14 / 13) | about $0.043 | about $0.005 |

Haiku is about eight times cheaper per message and writes about half again more output tokens (16,413 against 11,033). Message volume was not measured, so no daily saving is claimed; the failure it risks is a question the owner reads wrongly or never sees.

**Limits:** one run per case, so a rate is unknown; a second run could move either way. 13 cases cannot show that Haiku fails often, only that it failed twice here against Sonnet's none. If Haiku is tried again, the Escape case and a no-recommendation case are the two to repeat, and the bar stays the same.

- [x] Measured Haiku against Sonnet on the five points, 13 cases each.
- [x] Verdict recorded; no code, no doc and no test changed, because the default is unchanged.

**Blocked by:** None

**Claimed by:** Otilia 2026-11-05

**Status:** done, no switch; merge cfa10f4, PR 76

Codex owed: out until 2026-11-11 08:36. No code in this PR. A fresh Opus agent re-derived the claims from the tool-call data; its corrections (description count, header, token ratio, daily saving) are applied.
