# Recorder fixtures (F4)

PROVENANCE: SYNTHETIC. `leaderboard.json` was written from the documented shape of the public leaderboard endpoint
(`leaderboardRows[*].ethAddress`, `accountValue`, `windowPerformances`) because the test-designer sandbox has no route
to the API. It is NOT a recording. **NEEDS RECORDING**: replace it with one real response from
`https://stats-data.hyperliquid.xyz/Mainnet/leaderboard` (public, nothing to redact) before /verify. The tests read only
`leaderboardRows[*].ethAddress` (a mixed-case address is on purpose) and store the body verbatim, so a real body with
~10,000 rows should work unchanged.

The other market data the recorder stores (L2 books, `allMids`, asset contexts, funding, candles) reaches it through typed
ports (`copytrade.recorder.ports`), so there is no raw payload to fixture until the concrete adapters exist (F21). The
recorded `l2Book.json` and `candleSnapshot.json` of F3 are still marked NEEDS RECORDING in `README.md`.
