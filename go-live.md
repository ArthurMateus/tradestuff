---
description: Step 10 (trading). Readiness gate before any execution-path change runs with real money. Only the PO flips the switch.
argument-hint: <epic-slug>
---
You are the CTO. Epic: $ARGUMENTS. Gate check: `gate_passed: ship` and `touches_money_path: yes`.

**No agent ever sets mode=live, edits live keys, or places a live order.** This command produces a
checklist and evidence. The PO acts.

1. Dispatch **explore** to collect the evidence (the paper-trading logs and metrics since ship, the
   current config values for limits, and the kill-switch test results).
2. Dispatch **quant-researcher** to compare the paper-trading results with the pre-registered criteria
   and backtest expectations (D6). Dispatch **reviewer-risk** on the **current config values**
   (limits, sizes, blackout windows) as if they were a diff.
3. Write `docs/sdlc/<slug>/08-go-live.md` with this checklist. Every item is PASS/FAIL with evidence:
   - [ ] Paper period ≥ the planned duration and ≥ the minimum trade count from `edge-hypothesis.md`
   - [ ] Paper results within the tolerated divergence from backtest, and the kill criteria not triggered
   - [ ] Zero invariant violations in paper logs. Reconciliation mismatches explained.
   - [ ] Kill switch drilled in paper (Telegram and CLI), and it stays halted across a restart
   - [ ] Limits set for a **starter** capital tier (the smallest viable size), with a daily-loss limit
   - [ ] Latency p99 within budget in paper
   - [ ] Alerts reach the PO's phone (fill, reject, limit breach, disconnect, reconciliation mismatch)
   - [ ] **PO manual checks:** API key is trade-only, withdrawals disabled, IP whitelist on,
         `.env` not in git, 2FA on the exchange account
   - [ ] Capital ramp plan: the criteria for moving to the next size tier and for stepping back down
4. Present it to the PO. Say plainly whether you recommend go or no-go.
5. **Only if the PO replies with the exact phrase `I approve go-live for <slug>`**: record the
   approval with a timestamp in `08-go-live.md`, set `gate_passed: go-live`, and tell the PO which
   setting *they* must change to enable live mode.
