# Balanced momentum

A moderate position limit and twelve-bar observation window. A bar is one daily
session for real-data replays, or one minute in local test fixtures. The shared
parameters apply to every selected baseline model; the model determines how
to interpret observed returns or deviations. Signals execute at the next open.

```json
{"lookback":12,"threshold":0.0015,"max_allocation":0.70,"rebalance_threshold":0.025}
```
