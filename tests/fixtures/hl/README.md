# Hyperliquid fixtures for the R1 backfill-fix tests

PROVENANCE: SYNTHETIC-PENDING-RECORDING. Written from the documented `userFillsByTime` response (full field set: coin, px,
sz, side, time, startPosition, dir, closedPnl, hash, oid, crossed, fee, tid, feeToken, and the optional twapId, cloid,
liquidation object, builderFee) plus a few unknown extra keys. NOT recordings.

Replace with real responses from `docs/sdlc/copytrade-v1/research/scripts/hl_sample.py` (summary.json and raw/*.json.gz)
when the PO sends them; keep the file names (tests read them by name). Fills 1 to 9 time-stamp one to two hours before
`tests.hl.support.T0` and have distinct tids.
