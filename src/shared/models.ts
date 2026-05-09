export type AssetType = "stock" | "fund";

export interface WatchlistAsset {
  symbol: string;
  name: string;
  type: AssetType;
  region: string;
  currency: string;
}

export interface PriceBar {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface FlowPoint {
  date: string;
  value: number;
}

export type FlowStrength = "inflow" | "outflow" | "neutral";

export interface FlowMetrics {
  latestDailyFlow: number;
  estimatedNetFlow: number;
  moneyFlowIndex: number;
  chaikinMoneyFlow: number;
  accumulationDistribution: number;
  flowStrength: FlowStrength;
  netFlowSeries: FlowPoint[];
}

export interface AssetSnapshot {
  asset: WatchlistAsset;
  shortName: string;
  currency: string;
  exchangeName: string;
  lastPrice: number;
  previousClose: number;
  change: number;
  changePct: number;
  volume: number;
  history: PriceBar[];
  flow: FlowMetrics;
  updatedAt: string;
}

export interface MarketSummary {
  assetCount: number;
  totalEstimatedNetFlow: number;
  averageMoneyFlowIndex: number;
  inflowCount: number;
  outflowCount: number;
}

export type SnapshotFreshness = "fresh" | "stale";

export interface MarketSnapshot {
  updatedAt: string | null;
  source: string;
  freshness: SnapshotFreshness;
  staleReason?: string;
  marketSummary: MarketSummary;
  assets: AssetSnapshot[];
}

