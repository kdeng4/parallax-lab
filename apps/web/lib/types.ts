export type Comparison = 'models' | 'strategies';
export type Section = 'overview' | 'experiments' | 'strategies' | 'audit';

export interface Model {
  id: string;
  name: string;
  provider: string;
  description: string;
}
export interface Strategy {
  id: string;
  name: string;
  description: string;
  markdown: string;
  version: string;
}
export interface Catalog {
  models: Model[];
  strategies: Strategy[];
  symbols: string[];
  data_source: string;
  interval: string;
  max_bars: number;
  replay_available: boolean;
  replay_requirement?: string | null;
}
export interface Experiment {
  id: string;
  name: string;
  comparison: Comparison;
  symbol: string;
  status: string;
  created_at: string;
  data_source: string;
  seed: number | null;
  interval?: string;
  bars: number;
  initial_cash: number;
  participants: number;
  best_return_pct: number;
}
export interface Trade {
  id: string;
  timestamp: string;
  side: string;
  quantity: number;
  price: number;
  fee: number;
  realized_pnl: number | null;
}
export interface Run {
  id: string;
  model_id: string;
  model_name: string;
  provider: string;
  strategy_id: string;
  strategy_name: string;
  strategy_version: string;
  return_pct: number;
  equity: number;
  pnl: number;
  max_drawdown_pct: number;
  sharpe: number | null;
  win_rate_pct: number;
  trade_count: number;
  cash: number;
  position_qty: number;
  equity_curve: { timestamp: string; equity: number }[];
  trades: Trade[];
}
export interface AuditEvent {
  id: string;
  sequence: number;
  timestamp: string;
  type: string;
  run_id: string | null;
  model_name: string | null;
  strategy_name: string | null;
  message: string;
  details: Record<string, unknown>;
}
export interface Detail extends Experiment {
  metadata?: { dataset: { fetched_at?: string; as_of?: string; limitations?: string }; metrics: { periods_per_year: number; sharpe: string } };
  strategy_name: string;
  data_hash: string;
  costs: { fee_bps: number; slippage_bps: number };
  runs: Run[];
  candles: { timestamp: string; open: number; high: number; low: number; close: number; volume: number }[];
  events: AuditEvent[];
}
export interface CreateExperiment {
  name?: string;
  comparison: Comparison;
  model_ids: string[];
  strategy_ids: string[];
  symbol: string;
  seed?: number;
  initial_cash: number;
  bars: number;
}

export interface MarketOverview {
  as_of: string;
  refresh_interval_seconds: number;
  price_frequency: string;
  indicator_basis: string;
  replay_ready: boolean;
  stocks: {
    symbol: string; source: string; source_url: string; status: string;
    fetched_at: string | null; next_refresh_at: string | null;
    data: null | {
      as_of: string; close: number; adjusted_close: number; change_pct: number; volume: number;
      indicators: { sma20: number | null; sma50: number | null; rsi14: number | null; macd: number | null; macd_signal: number | null };
    };
  }[];
  macro: {
    id: string; label: string; unit: string; frequency: string; value: number | null; change: number | null;
    as_of: string | null; status: string; source: string; source_url: string;
    fetched_at: string | null; next_refresh_at: string | null;
  }[];
}
