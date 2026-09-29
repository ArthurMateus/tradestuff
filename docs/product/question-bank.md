# Brainstorm question bank (for the CTO to interview the PO)

Skip anything already in `decisions.md`.

## Business
- Who is the follower (beginner, active retail, semi-pro)? Who is the leader (public brokers' traders, our own marketplace, both)?
- Revenue: subscription, performance fee, spread, leader revenue share? Any conflicts of interest?
- Target markets and jurisdictions at launch? Where is the company based?
- Budget, timeline, team, and what you can spend on data and infrastructure?

## Markets and brokers
- Asset classes: stocks, crypto, forex, futures, options? Start with which one?
- Which brokers/exchanges, and do they allow this via API? Where do leaders' trades come from (public leaderboards, connected accounts, on-chain, scraping)? Is that permitted?
- Custody: does the user's money stay at their broker with our trade-only API key?

## Copying behavior
- Latency target (ms) and how it is measured. What is acceptable slippage, and what happens beyond it?
- Sizing: proportional to equity, fixed, risk-based? Handling of leverage, minimum lots, fractional shares.
- One leader or a portfolio of leaders? Auto-switching leaders or human approval?
- Open-position handling when a leader is dropped: close, hold, or ask?

## Finding traders
- Min history, min trades, eligible metrics? Your definition of "most profitable": return, risk-adjusted, consistency?
- How often to re-rank? Are you OK with excluding high-return, high-risk styles (martingale, grid)?

## Risk and safety
- Maximum loss you or a user should ever be exposed to per day/week? Automatic stops? Who can override?
- What must happen when the feed, broker, or our system fails mid-trade?

## Legal
- Do you have counsel? Any licenses held? Marketing claims you want to make?

## Product and UX
- Web, mobile, both? What must a user see in 30 seconds? Notifications and reporting needs?

## Success
- Metrics at 30/90/180 days (users, AUM, copy latency, follower drawdown, retention)? What would make you kill it?
