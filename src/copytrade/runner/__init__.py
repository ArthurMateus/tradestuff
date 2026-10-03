"""The minimal v0 runner (R0): ONE command, ``copytrade run``, paper only.

Interface stubs written by the test designer (docs/sdlc/copytrade-v1/05-test-plan-R0.md pins every name below).
The developer owns the implementation. Modules:

- ``endpoints``  the four network endpoints (build constants; tests inject loopback ones)
- ``deps``       the injected true boundaries (clock, sleeper, disk probe, identity, endpoints)
- ``wiring``     the composition root ``build_runner``
- ``runner``     ``Runner``: start (reload), step (one loop iteration), stop (clean), run
- ``timebase``   the F11 time-base contract (advance on every iteration, jump guard)
- ``reload``     ledger -> state at start, and the uncertain-state codes
- ``disk``       the real DiskProbe and the start-up disk check
- ``retention``  the local recording-retention cap
- ``adapters``   the F3/F4/F6/F10/F12 ports over the real REST client, WebSocket connector and the live books
- ``policy``     the entry-policy stand-in
- ``app``        ``run_app``: what ``copytrade run`` does
"""
