# Hyperliquid info/WS fixtures (F3)

PROVENANCE: SYNTHETIC. These payloads were written from the documented Hyperliquid response shapes
(docs.hyperliquid.xyz info endpoint and websocket pages; field list in edge-hypothesis.md section 5 and
market-context.md 2.3) because the test-designer sandbox has no route to the API. They are NOT recordings.

Replace with real recordings before /verify: run `docs/sdlc/copytrade-v1/research/scripts/hl_sample.py` on the
PO's PC (it keeps raw/*.json.gz of real responses), pick one response per endpoint, redact nothing (all public),
and overwrite the file of the same name. Tests read these files by name and check structure, not values, except
`tid`, `time` and `oid` which are self-consistent inside each file.
