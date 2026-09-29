# Implicit requirements (apply to every epic)

The PM must turn each into criteria or explicitly mark it N/A; `compliance-reviewer` audits them.

## Security
- Secrets only from environment or a secret manager; never in code, logs, tests, or client bundles.
- Broker/exchange API keys encrypted at rest, trade-only scope, no withdrawal permission, revocable by the user.
- Authn/authz on every endpoint; users can only act on their own accounts. Validate all input at trust boundaries. Rate limit. Fail closed.
- Inbound webhooks signature-verified and replay-protected.
- Dependencies pinned and scanned.

## Money correctness
- `Decimal` / integer minor units; explicit currency and rounding rules; UTC timezone-aware timestamps.
- Every order-creating path is idempotent (client order ids) and passes through the risk gate. No bypass.
- Positions reconciled against the broker on schedule and after any disconnect. The broker is the source of truth.

## Safety
- Paper/sandbox by default. Real-money paths behind a feature flag that ships OFF and needs the PO's written go.
- Global and per-user kill switch works when other components are degraded. Fail closed: no new positions when unsure.
- Limits are configuration with safe defaults and hard ceilings.

## Data-driven
- Everything that can be data is data: thresholds, weights, fee tables, symbol lists, calendars, limits, feature flags. Schema-validated, versioned, and changes are audit-logged.

## Reliability and operations
- Structured logs with correlation ids (no PII or secrets), metrics, and alerts for: feed lag, copy latency, rejects, reconciliation drift, kill-switch trips.
- Graceful degradation, timeouts and bounded retries with backoff on every external call. Idempotent jobs; safe restart at any point.
- Audit trail of every money-moving or permission-changing action (who, what, when, why, before/after).

## Quality
- Tests written first and red-first; no over-mocking. Linters, type checks clean. Deterministic tests (injected clock, seeded randomness).
- Accessible, responsive UI. Errors shown to users are actionable and leak nothing internal.

## Honesty
- No performance guarantee in UI, copy or docs. Past-performance and risk disclosures wherever returns appear. No fabricated or cherry-picked stats.
