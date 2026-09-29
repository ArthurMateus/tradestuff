# Testing policy

**Goal:** thousands of fast, honest unit tests (target: 6,000 within the first month), plus integration and e2e where risk warrants.

1. **Tests come first and start red.** Two independent `test-designer` runs (A, B) write tests from the acceptance criteria; `test-reviewer` merges them and proves the suite fails for the right reason on a stub. Developers make it green; they never edit tests to pass. A test change needs `test-reviewer` approval.
2. **Bugs:** first write a failing test that reproduces it. It stays red until fixed, then stays forever.
3. **Do not test the mock or the framework.** Fake only true external boundaries (broker, exchange, clock, network, filesystem when needed), using realistic in-memory fakes. Never mock the unit under test or its in-module collaborators.
4. **Honesty check:** a test must fail if the code is wrong. `test-reviewer` verifies with deliberately broken stubs for critical logic.
5. **Expected values come from requirements**, not from running the code.
6. **Shapes:** table-driven tests for input matrices; property-based tests for invariants (limits never exceeded, PnL = sum of fills, sizing monotonic, idempotent replays); boundary and precision tests for all money math; time tests around market open/close, DST, weekends, holidays.
7. **Deterministic and fast:** injected clock, seeded randomness, no network, no sleeps. Unit test < 50 ms typical.
8. **Pyramid:** many unit tests, fewer integration tests against real dependencies (containerized DB/queue), a few e2e (Playwright) driven by QA.
9. **Trading-specific:** simulation tests replay recorded market and leader-trade data through the real copy engine with a fake broker that models fees, slippage, partial fills, rejects, disconnects.
10. **Track:** test count and per-criterion coverage in `tests.md`; CI fails on skipped, disabled or quarantined tests.
