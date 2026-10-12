# Capital preservation

A longer observation window and lower exposure for slower, selective decisions.
Each model receives exactly the same market observations. This is a research
configuration, not a claim that losses will be prevented.

For ongoing studies, an observation is the common daily window snapshot.
Apply the position limit to total exposure across the selected tickers. Use
observable prices, news and announced events to choose tickers, cash and a delay
within the current window. The objective is to maximise net paper equity within
these limits. Price-only controls use the same configured observation lookback.

```json
{"lookback":24,"threshold":0.003,"max_allocation":0.40,"rebalance_threshold":0.04}
```
