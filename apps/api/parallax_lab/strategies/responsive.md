# Responsive momentum

A shorter window and higher exposure to react to smaller observed moves.
Trading costs are identical across all strategies. Faster decisions may increase
turnover and losses; performance is evaluated after all simulated costs.

For ongoing studies, an observation is the common daily window snapshot.
Apply the position limit to total exposure across the selected tickers. Use
observable prices, news and announced events to choose tickers, cash and a delay
within the current window. The objective is to maximise net paper equity within
these limits. Price-only controls use the same configured observation lookback.

```json
{"lookback":6,"threshold":0.0008,"max_allocation":0.85,"rebalance_threshold":0.02}
```
