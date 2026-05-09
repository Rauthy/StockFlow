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

export interface DailyAnalysis {
  trade_date: string;
  market_summary: string;
  sector_summary: string;
  capital_flow_summary: string;
  news_summary: string;
  opportunity_summary: string;
  risk_summary: string;
  generated_at: string;
}

export interface WeeklyReport {
  week_start: string;
  week_end: string;
  report_title: string;
  market_review: string;
  sector_rotation: string;
  capital_flow_review: string;
  news_theme_review: string;
  opportunity_watchlist: string;
  risk_watchlist: string;
  historical_context: string | null;
  next_week_focus: string | null;
  generated_at: string;
}

export interface MarketRegime {
  trade_date: string;
  regime: string;
  risk_appetite_score: number;
  trend_score: number;
  liquidity_score: number;
  breadth_score: number;
  notes: string | null;
  generated_at: string;
}

export interface CycleReport {
  period_start: string;
  period_end: string;
  lookback_days: number;
  cycle_stage: string;
  market_summary: string;
  regime_summary: string;
  index_summary: string;
  sector_summary: string;
  opportunity_summary: string;
  risk_summary: string;
  generated_at: string;
}

export interface DataCoverage {
  dataset: string;
  target_date: string;
  status: string;
  source: string | null;
  checked_at: string;
  notes: string | null;
}

export interface InvestmentOpportunity {
  target_type: string;
  target_code: string;
  target_name: string;
  trade_date: string;
  opportunity_score: number;
  trend_score: number;
  capital_score: number;
  news_score: number;
  risk_score: number;
  thesis: string;
  risk_note: string | null;
}

export interface EarlyOpportunity {
  target_type: string;
  target_code: string;
  target_name: string;
  trade_date: string;
  early_score: number;
  flow_persistence_score: number;
  rank_improvement_score: number;
  heat_score: number;
  crowding_risk_score: number;
  matched_funds: string | null;
  thesis: string;
  action_hint: string;
}

export interface TrackedOpportunity {
  id: string;
  target_type: string;
  target_code: string;
  target_name: string;
  source_report_date: string;
  entry_date: string;
  entry_score: number;
  entry_price: number | null;
  latest_date: string | null;
  latest_price: number | null;
  return_pct: number | null;
  status: string;
  thesis: string;
  matched_funds: string | null;
  updated_at: string;
}

export interface MarketIndex {
  symbol: string;
  trade_date: string;
  name: string;
  region: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number;
  previous_close: number | null;
  change: number | null;
  change_pct: number | null;
  volume: number | null;
  turnover: number | null;
  source: string;
}

export interface SectorFlow {
  sector_code: string;
  sector_name: string;
  trade_date: string;
  market: string;
  change_pct: number | null;
  turnover: number | null;
  net_inflow: number | null;
  main_net_inflow: number | null;
  source: string;
}

export interface SectorLeader {
  sector_code: string;
  sector_name: string | null;
  trade_date: string;
  symbol: string;
  name: string;
  rank_type: string;
  rank_value: number | null;
  change_pct: number | null;
  net_inflow: number | null;
  source: string;
}

export interface NewsImpactArticle {
  id: string;
  source: string;
  title: string;
  summary: string | null;
  url: string;
  published_at: string | null;
  language: string | null;
  sentiment: "positive" | "negative" | "neutral";
  impact_level: "high" | "medium" | "low";
  related_sectors: string | null;
  thesis: string | null;
  risk_note: string | null;
}

export interface PageInfo {
  page: number;
  pageSize: number;
  total: number;
  totalPages: number;
}

export interface IntelligencePagination {
  marketIndices: PageInfo;
  opportunities: PageInfo;
  sectorFlows: PageInfo;
  sectorLeaders: PageInfo;
  news: PageInfo;
}

export interface IntelligenceFilters {
  asOfDate: string | null;
  pageSize: number;
}

export interface InvestmentIntelligence {
  databasePath: string;
  filters: IntelligenceFilters;
  latestDailyAnalysis: DailyAnalysis | null;
  latestWeeklyReport: WeeklyReport | null;
  latestMarketRegime: MarketRegime | null;
  latestCycleReport: CycleReport | null;
  coverage: DataCoverage[];
  marketIndices: MarketIndex[];
  opportunities: InvestmentOpportunity[];
  earlyOpportunities: EarlyOpportunity[];
  trackedOpportunities: TrackedOpportunity[];
  sectorFlows: SectorFlow[];
  sectorLeaders: SectorLeader[];
  news: NewsImpactArticle[];
  pagination: IntelligencePagination;
}
