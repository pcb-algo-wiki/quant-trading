# Live Trading Runbook

## Preconditions

1. Shadow trading metrics satisfy configured thresholds.
2. Risk guard is enabled and tested.
3. Manual confirmation channel is available.

## Deployment steps

1. Start with canary capital bucket only.
2. Enable `LiveGuard` with manual confirmation.
3. Place first batch with strict slippage and loss limits.
4. Monitor fills, drawdown, and slippage in real time.

## Rollback triggers

1. Consecutive loss limit breached.
2. Slippage over threshold for multiple orders.
3. Data quality or broker connectivity anomalies.

## Rollback actions

1. Stop submitting new orders immediately.
2. Cancel pending orders.
3. Reduce or close risky positions.
4. Switch to shadow mode and investigate root cause.
