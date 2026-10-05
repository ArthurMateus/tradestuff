# F10 round 2: blocking findings for the architect (reviewer-risk, verify-only, at the cap)

Round-1 items B1-B5, B7 verified closed (reviewer-risk probes). Two BLOCKING items remain.

## RISK-20 (B6/RISK-5 not truly fixed): /flatten can leave positions open while reporting nothing outstanding
src/copytrade/risk/gate.py flatten (~294-335).
(a) It lists broker positions() BEFORE any advance_to; the first close's submit then advances the broker, so an entry that is due fills mid-flatten. That entry is neither in the close list nor in FlattenReport.in_flight. Probe: ETH held, SOL OPEN pending, flatten at T0+1500 -> SOL fills inside the ETH close's events, in_flight=(), SOL 1.00 still open.
(b) A share with a pending partial exit (REDUCE waiting for a book, or a triggered partial TP): the flatten CLOSE for the full share_qtys is refused `exceeds_position`; after the reduce fills 0.60 stays open, in_flight=(). The F21/R0 rule "re-run while in_flight is non-empty" will not re-run in either case.
Reviewer-risk's proposed fix: advance the broker once after the pause, before listing (or repeat the listing pass until no new share appears, with a cap); add `still_open` to FlattenReport (every broker share not covered by an accepted close in this run, incl. closes refused exceeds_position); the supervisor re-runs while in_flight or still_open is non-empty. Tests: entry fill due before flatten with another position held; pending partial REDUCE then flatten -> reported, and a re-run after the fill closes the residual.
Loss: the PO pulls the kill switch, is told nothing is outstanding, a fresh full-size position stays open.

## RISK-21 (B2: own-advance fills not handled for ADDs): filled ADD under-counted in caps
gate.py _known_entries (~545-602, ADD drop at ~583).
Once a pending ADD fills, `_known_entries` drops its record. The share book still carries the pre-add risk until F12 consumes broker_events, which happens only after the submit returns. Any entry decided in a submit whose own advance_to filled the ADD undercounts share, symbol, leader, total and bucket risk (margin and liquidation stay correct, from the broker). Probe: share risk 0.3, ADD1 approved risk 2.7, then ADD2 at ADD1's fill time approved risk 1.5 -> true share risk 4.5 vs share cap 3.0 (held to 1.0 only by margin; 1.8 without it -> 5.7 vs 3.0). An OPEN on another coin in the same race saw total risk "used 6.80" when the truth was 9.50. F12 cannot close it: the decision happens before F12 sees the fill.
Proposed fix: keep an ADD's record after it leaves pending while the broker's share qty exceeds the book's qty for that share (count its approved risk); drop it once the book's qty catches up or the share is no longer held. Tests: ADD1 pending, then at its fill time ADD2 on the same share and an OPEN on another coin: caps include ADD1's risk.
Loss: each such race can exceed every risk cap by up to one more share's cap (about 1% of equity: total 6% vs 5%, a share at 2x its cap).

## Non-blocking (logged): RISK-22 share_closed/netting should use the broker's share qty for close=True (orphan risk); RISK-23 rejected marks only logged (R0: exchange-time stamps + alert after N rejects); RISK-24 position_mismatch only logged not alerted; RISK-25 gate has no lock around submit: R0 must serialise every gate call including flatten.
