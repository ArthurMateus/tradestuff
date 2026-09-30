# Test plan W0: websockets connector for F3

Branch `feat/copytrade-v1/W0-ws-connector`. Basis: PO decision 2026-09-30 (decisions.md), STATE.md W0, F3's `WsConnection`/`WsConnector` protocols (`src/copytrade/hl/ws.py`), F1.AC3, invariants B3, A2. There is no numbered spec for W0, so tests carry IDs `W0.1`..`W0.11` (groups below).
Tests: `tests/hl/test_w0_connector.py` (58 tests). Helpers: `tests/hl/ws_server.py` (loopback fake servers). Stub: `src/copytrade/hl/connector.py` (`WebsocketsConnector`, every body `raise NotImplementedError`, no defaults).

## Shared-file changes (made by the test designer, needed for imports)
- `pyproject.toml`: `dependencies = ["websockets==17.1"]` (exact pin; first runtime dependency).
- `uv.lock`: `websockets 17.1` added, no dependencies of its own; `copytrade` now requires it. Licence from installed metadata: `BSD-3-Clause`.

## Run summary
`uv run pytest -q tests/hl/test_w0_connector.py`: **58 collected, 54 failing, 4 passing.**

| Failure reason | Count |
|---|---|
| `NotImplementedError` from the connector stub | 53 |
| Assertion failure (`test_W0_only_hl_connector_imports_websockets`: the stub imports nothing yet) | 1 |
| Import, collection, fixture, syntax error | 0 |

The 4 passing tests guard the shared files and the stub, and must keep passing: the synthetic static-scan self-test, `connector has no exchange literal / signing import`, `uv.lock pins websockets exactly`, `pyproject pins exactly`. They pass now because the dependency change is part of this commit.
Whole suite: 3846 pass, 54 fail (all W0). `ruff check .`, `ruff format --check src`, `mypy` (strict) clean. The fake servers were smoke-checked against the real `websockets` 17.1 sync client (clean close, abrupt drop, server ping, bad UTF-8, HTTP 403 handshake behave as the tests assume).

## Contract decisions the tests fix (spec gaps; developer follows, PM may veto)
1. `WebsocketsConnector(url, *, connect_timeout_s, max_message_bytes)`; no defaults in the stub, config wiring is R0's.
2. Construction is lazy (no socket) and validates: scheme `ws`/`wss` only, non-empty host, path not containing `exchange` (case-insensitive), timeout > 0 and not NaN, limit > 0: `ValueError`.
3. `connect` raises only `OSError` (refused, timeout, failed handshake such as HTTP 403 which the library raises as non-OSError `InvalidStatus`, guard block). It never exceeds `connect_timeout_s` plus slack.
4. `recv`: text frame -> `str`; nothing waiting -> `None`; buffered text frames are delivered before the close surfaces; after close/drop/closed-by-us -> `OSError`, repeatedly. A binary frame, invalid UTF-8 or a frame over `max_message_bytes` -> `OSError` (fail closed: F3 reconnects and resyncs, B3/A2), never a silent drop. Valid-UTF-8 text that is not JSON is passed through (F3 judges it).
5. Heartbeat stays F3's application-level `{"method":"ping"}`; protocol pings are answered by the library and never surfaced. Note for the developer: library keepalive should be off (F3 owns liveness); not testable in a fast test (default interval 20 s), so a review item.
6. `close` idempotent, never raises, releases the socket (server sees the peer leave). websockets 17.1 sync `connect()` warns unless used as a context manager or `legacy=True`: developer to pick a non-warning construction.

## Coverage matrix
| Group | Requirement | Tests (all prefixed `test_W0_`) |
|---|---|---|
| W0.1 | connect to ws:// loopback, receive text frames | `connect_to_loopback_and_receive_text_frames_in_order`, `received_frames_are_str_and_unicode_survives`, `empty_text_frame_is_delivered_as_empty_string_not_as_none`, `frame_just_under_and_large_frames_up_to_the_limit_are_delivered`, `the_connector_opens_a_new_independent_connection_on_each_connect` |
| W0.2 | non-blocking recv, never blocks tick | `recv_returns_none_immediately_when_no_frame_is_waiting`, `recv_drains_every_waiting_frame_then_returns_none`, `recv_does_not_block_while_the_server_is_silent_but_the_link_is_open_for_seconds` |
| W0.3 | send subscribe messages | `send_delivers_subscribe_messages_exactly_as_given`, `send_after_the_server_closed_raises_oserror`, `send_after_an_abrupt_drop_raises_oserror_not_another_exception_type` |
| W0.4 | ping/pong as F3 requires | `application_ping_reaches_the_server_and_the_pong_text_frame_comes_back_unchanged`, `server_protocol_ping_is_answered_by_the_library_and_never_shown_to_the_feed`, e2e heartbeat |
| W0.5 | close, drop, refused, timeout surface as OSError, never hang | `clean_server_close_raises_oserror_from_recv_and_keeps_raising`, `frames_sent_before_a_server_close_are_delivered_before_recv_raises`, `abrupt_tcp_drop_raises_oserror_from_recv`, `connection_refused_raises_oserror_from_connect`, `connect_timeout_raises_oserror_and_does_not_hang`, `failed_handshake_http_403_raises_oserror_not_a_library_exception`, `a_failed_connect_does_not_poison_the_connector_a_retry_succeeds` |
| W0.5b | no non-loopback connect in tests; wss accepted | `connect_to_a_non_loopback_host_is_blocked_by_the_guard_and_raises_oserror`, `connect_to_a_hostname_is_resolved_through_the_guard_and_blocked`, `constructing_a_wss_connector_is_accepted_and_opens_no_socket` |
| W0.6 | info-ws only, argument validation | `a_url_that_is_not_ws_or_wss_or_points_at_the_exchange_endpoint_is_rejected_at_construction` (9 params), `a_non_positive_or_nan_connect_timeout_is_rejected` (3), `a_non_positive_message_limit_is_rejected` (2), `connector_has_no_exchange_endpoint_literal_and_no_signing_import` |
| W0.7 | large and malformed frames | `binary_frame_makes_recv_raise_oserror_fail_closed`, `text_frames_before_a_binary_frame_are_still_delivered`, `invalid_utf8_text_frame_raises_oserror_and_does_not_crash`, `frame_above_the_message_limit_raises_oserror_and_the_connection_is_dead`, `frame_one_byte_over_the_limit_is_rejected_and_one_at_the_limit_is_accepted`, `a_valid_json_frame_that_is_not_an_object_is_passed_through_for_f3_to_judge` |
| W0.8 | close idempotent, releases socket | `close_is_idempotent`, `close_releases_the_socket_the_server_sees_the_peer_leave`, `after_close_recv_and_send_raise_oserror`, `close_after_the_server_already_dropped_the_link_does_not_raise`, `many_connect_close_cycles_leave_no_connection_open_at_the_server` |
| W0.9 | only hl/connector.py imports websockets | `static_scan_detects_a_websockets_import_in_synthetic_source`, `only_hl_connector_imports_websockets` |
| W0.10 | dependency pinned exactly, no signing/crypto package | `uv_lock_pins_websockets_exactly_with_no_dependencies_and_no_signing_package`, `pyproject_pins_websockets_with_an_exact_version_equal_to_the_lock` |
| W0.11 | real HlWsFeed + real connector + fake server | `e2e_feed_subscribes_over_the_real_connector_and_delivers_each_fill_once`, `e2e_feed_heartbeat_ping_reaches_the_server_and_the_pong_keeps_the_feed_alive`, `e2e_server_drop_triggers_reconnect_and_resync_through_f3_and_nothing_is_lost_or_doubled`, `e2e_connection_refused_is_retried_by_f3_with_backoff_not_a_crash`, `e2e_binary_frame_from_the_server_is_treated_as_a_lost_connection_and_resynced` |

Invariants touched: B3 (reconnect/heartbeat/resync via the e2e tests, F3 logic unchanged), A2 (fail closed on any broken frame), F1.AC3 (info-only, no signing import, guard-blocked non-loopback).

## How the tests are built
Real sockets on 127.0.0.1 only; the suite network guard stays on (two tests use `expect_blocked` to prove a non-loopback or hostname connect cannot leave the machine). `FakeWsServer` uses the `websockets` server API; `RawWsServer` hand-speaks RFC 6455 for cases a server library won't produce (bad UTF-8, HTTP 403, silent peer, protocol ping). The feed e2e runs on F3's fake clock with the fake REST transport. The only waiting is `wait_for`, a bounded poll (5 s cap, 2 ms step) on a real socket event, because real sockets need real time; no test sleeps for a fixed duration and every wait fails loudly instead of hanging.

## Deliberately not covered (and where)
- TLS handshake and certificate checks over `wss://` (loopback `ws://` only): QA smoke on the PO's PC against the real Hyperliquid info WS, and the R0 gate.
- The real Hyperliquid message shapes beyond the existing F3 fixtures (still synthetic; `NEEDS RECORDING` list in the F3 plan).
- Library keepalive disabled, reconnect storm limits, long-idle behaviour, memory under sustained load: review and simulation/paper run.
- Windows-specific socket behaviour: QA on the PO's machine.
