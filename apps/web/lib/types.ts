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
}
export interface Experiment {
  id: string;
  name: string;
  comparison: Comparison;
  symbol: string;
  status: string;
  created_at: string;
  data_source: string;
  seed: number;
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
  seed: number;
  initial_cash: number;
  bars: number;
}
