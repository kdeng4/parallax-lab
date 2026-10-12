# Balanced momentum

A moderate position limit and twelve-bar observation window. A bar is one daily
session for real-data replays, or one minute in local test fixtures. The shared
parameters apply to every selected baseline model; the model determines how
to interpret observed returns or deviations. Historical replay signals execute at the next open.

For ongoing studies, an observation is the common daily window snapshot.
Apply the position limit to total exposure across the selected tickers. Use
observable prices, news and announced events to choose tickers, cash and a delay
within the current window. The objective is to maximise net paper equity within
these limits. Price-only controls use the same configured observation lookback.

```json
{"lookback":12,"threshold":0.0015,"max_allocation":0.70,"rebalance_threshold":0.025}
```
