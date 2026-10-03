# Codex review 3d of the codex-down plan: ticket 01 after review 3c

Run by Anouk, 2026-10-04 00:19–00:24 (+02:00). Same setup as 3b and 3c, checkout root at commit `b25ce2f` (main).
The brief added review 3c's three points and asked whether the amendment answers them.

**Verdict: NO-GO, on one point that is in ticket 03, not in 01.** Codex raises nothing against ticket 01 and says
the `Fallback.when` interface is sufficient ("Interface change: no"). The point: ticket 03 still builds its
fallback without `when`, which would take the default and let a Codex `noverdict` reach `claude`. The fix is in
ticket 03 (`when=("absent","timeout","error")` in its constructor), which another worker owns; the boss has told
that worker that 03 names `Fallback.when`. Ticket 01 is built as it stands. The citation marks are Anouk's; the
checkout path prefix is removed from Codex's links.

## Codex's answer, verbatim

NO-GO

1. Ticket 03 still does not actually exclude `noverdict`. Ticket 01 says the default includes it and claims ticket 03 passes `("absent", "timeout", "error")` ([01-one-reviewer-chain.md:54](.scratch/codex-down/issues/01-one-reviewer-chain.md:54)). But ticket 03’s prescribed constructor omits `when`, thereby using that default ([03-labelled-fallback-review.md:14](.scratch/codex-down/issues/03-labelled-fallback-review.md:14)), contradicting its requirement that `noverdict` never invokes Claude ([03-labelled-fallback-review.md:20](.scratch/codex-down/issues/03-labelled-fallback-review.md:20)). A worker cannot satisfy both boxes literally. Add `when=("absent", "timeout", "error")` to ticket 03’s constructor. **Ticket-text change: yes, in ticket 03. Interface change: no; the amended `Fallback.when` interface is sufficient.**
## Citation check (Anouk)

| Point | Citation | Mark |
|---|---|---|
| 1 | 01:54 at `b25ce2f` (the sentence that gives `Fallback.when` its default and says 03 passes the three reasons) | VERIFIED |
| 1 | 03-labelled-fallback-review.md:14 (the constructor, no `when`), :20 (noverdict never reaches `claude`) | VERIFIED (working copy of 03, uncommitted at the time) |
