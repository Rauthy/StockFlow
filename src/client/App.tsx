import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";
import {
  fetchInvestmentIntelligence,
  fetchMarketSnapshot,
  refreshMarketSnapshot,
  runInvestmentTask,
  type IntelligenceTaskAction
} from "./api.js";
import type {
  AssetSnapshot,
  InvestmentIntelligence,
  MarketSnapshot
} from "../shared/models.js";

const typeLabel: Record<AssetSnapshot["asset"]["type"], string> = {
  stock: "股票",
  fund: "基金"
};

const formatCompact = (value: number): string =>
  new Intl.NumberFormat("zh-CN", {
    notation: "compact",
    maximumFractionDigits: 2
  }).format(value);

const formatPercent = (value: number): string => `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;

const formatOptionalPercent = (value: number | null): string =>
  value == null ? "--" : formatPercent(value);

const sentimentLabel = {
  positive: "利好",
  negative: "利空",
  neutral: "中性"
} as const;

type PageKey = "marketIndices" | "opportunities" | "sectorFlows" | "sectorLeaders" | "news";

type PageState = Record<PageKey, number>;

const taskLabels: Array<{
  action: IntelligenceTaskAction;
  title: string;
  description: string;
}> = [
  {
    action: "collect-daily",
    title: "一键每日采集",
    description: "刷新观察列表、指数、板块、新闻并生成周报"
  },
  {
    action: "backfill",
    title: "历史快照回填",
    description: "从本地行情快照回填历史日线和基础分析"
  },
  {
    action: "collect-indices",
    title: "抓取市场指数",
    description: "采集 A股 / 美股 / 港股指数并识别周期"
  },
  {
    action: "collect-sectors",
    title: "抓取板块资金",
    description: "采集 A股行业概念、美股/港股板块代理"
  },
  {
    action: "collect-news",
    title: "抓取新闻舆情",
    description: "采集财经新闻 RSS 并做利好利空初筛"
  },
  {
    action: "enrich-news",
    title: "新闻中文化",
    description: "调用本地 Ollama 转换中文标题和影响判断"
  },
  {
    action: "analyze-opportunities",
    title: "分析投资机会",
    description: "生成早期机会、基金映射和机会跟踪复盘"
  },
  {
    action: "analyze-cycles",
    title: "分析历史周期",
    description: "整理过去半年市场周期、指数强弱和资金主线"
  },
  {
    action: "report-weekly",
    title: "生成周报",
    description: "基于已入库数据刷新最近一周投资周报"
  }
];

const formatDateTime = (value: string | null): string =>
  value
    ? new Intl.DateTimeFormat("zh-CN", {
        dateStyle: "medium",
        timeStyle: "short"
      }).format(new Date(value))
    : "暂无数据";

const cardTone = (value: number): string => {
  if (value > 0) {
    return "positive";
  }
  if (value < 0) {
    return "negative";
  }
  return "neutral";
};

const formatMatchedFunds = (value: string | null): string => {
  if (!value) {
    return "暂无映射";
  }
  try {
    const funds = JSON.parse(value) as Array<{ symbol: string; name: string }>;
    return funds.map((fund) => `${fund.name} ${fund.symbol}`).join("；");
  } catch {
    return value;
  }
};

interface CollapsibleSectionProps {
  title: string;
  subtitle?: string;
  defaultOpen?: boolean;
  children: ReactNode;
}

const CollapsibleSection = ({
  title,
  subtitle,
  defaultOpen = true,
  children
}: CollapsibleSectionProps) => {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <section className="collapsible-section">
      <button className="section-toggle" type="button" onClick={() => setOpen((current) => !current)}>
        <span>
          <strong>{title}</strong>
          {subtitle ? <small>{subtitle}</small> : null}
        </span>
        <b>{open ? "收起" : "展开"}</b>
      </button>
      {open ? <div className="section-body">{children}</div> : null}
    </section>
  );
};

interface PaginationControlsProps {
  label: string;
  pageInfo?: { page: number; totalPages: number; total: number; pageSize: number };
  onPageChange: (page: number) => void;
}

const PaginationControls = ({ label, pageInfo, onPageChange }: PaginationControlsProps) => {
  if (!pageInfo || pageInfo.total <= pageInfo.pageSize) {
    return null;
  }

  return (
    <div className="pagination">
      <span>
        {label}：第 {pageInfo.page} / {pageInfo.totalPages} 页，共 {pageInfo.total} 条
      </span>
      <div>
        <button
          type="button"
          onClick={() => onPageChange(pageInfo.page - 1)}
          disabled={pageInfo.page <= 1}
        >
          上一页
        </button>
        <button
          type="button"
          onClick={() => onPageChange(pageInfo.page + 1)}
          disabled={pageInfo.page >= pageInfo.totalPages}
        >
          下一页
        </button>
      </div>
    </div>
  );
};

const App = () => {
  const [snapshot, setSnapshot] = useState<MarketSnapshot | null>(null);
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [intelligenceLoading, setIntelligenceLoading] = useState(false);
  const [runningTask, setRunningTask] = useState<IntelligenceTaskAction | null>(null);
  const [taskMessage, setTaskMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [intelligence, setIntelligence] = useState<InvestmentIntelligence | null>(null);
  const [selectedDate, setSelectedDate] = useState("");
  const [pageSize, setPageSize] = useState(10);
  const [pages, setPages] = useState<PageState>({
    marketIndices: 1,
    opportunities: 1,
    sectorFlows: 1,
    sectorLeaders: 1,
    news: 1
  });

  const intelligenceQuery = () => ({
    date: selectedDate || undefined,
    pageSize,
    marketPage: pages.marketIndices,
    opportunityPage: pages.opportunities,
    sectorPage: pages.sectorFlows,
    leaderPage: pages.sectorLeaders,
    newsPage: pages.news
  });

  const loadIntelligence = async () => {
    setIntelligenceLoading(true);
    setError(null);
    try {
      const nextIntelligence = await fetchInvestmentIntelligence(intelligenceQuery());
      setIntelligence(nextIntelligence);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "加载投资情报失败。");
    } finally {
      setIntelligenceLoading(false);
    }
  };

  const loadSnapshot = async () => {
    setLoading(true);
    setError(null);
    try {
      const nextSnapshot = await fetchMarketSnapshot();
      setSnapshot(nextSnapshot);
      setSelectedSymbol((current) => current ?? nextSnapshot.assets[0]?.asset.symbol ?? null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "加载数据失败。");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadSnapshot();
  }, []);

  useEffect(() => {
    void loadIntelligence();
  }, [selectedDate, pageSize, pages]);

  const handleRefresh = async () => {
    setRefreshing(true);
    setError(null);
    try {
      const nextSnapshot = await refreshMarketSnapshot();
      const nextIntelligence = await fetchInvestmentIntelligence(intelligenceQuery());
      setSnapshot(nextSnapshot);
      setIntelligence(nextIntelligence);
      setSelectedSymbol((current) => current ?? nextSnapshot.assets[0]?.asset.symbol ?? null);
    } catch (refreshError) {
      setError(refreshError instanceof Error ? refreshError.message : "刷新失败。");
    } finally {
      setRefreshing(false);
    }
  };

  const handleRunTask = async (action: IntelligenceTaskAction) => {
    setRunningTask(action);
    setTaskMessage(null);
    setError(null);
    try {
      await runInvestmentTask(action);
      const nextIntelligence = await fetchInvestmentIntelligence(intelligenceQuery());
      setIntelligence(nextIntelligence);
      setTaskMessage("任务执行完成，页面数据已更新。");
      if (action === "collect-daily" || action === "backfill") {
        void loadSnapshot();
      }
    } catch (taskError) {
      setError(taskError instanceof Error ? taskError.message : "任务执行失败。");
    } finally {
      setRunningTask(null);
    }
  };

  const updatePage = (key: PageKey, page: number) => {
    setPages((current) => ({ ...current, [key]: Math.max(1, page) }));
  };

  const resetPages = () => {
    setPages({
      marketIndices: 1,
      opportunities: 1,
      sectorFlows: 1,
      sectorLeaders: 1,
      news: 1
    });
  };

  const selectedAsset = useMemo<AssetSnapshot | null>(() => {
    if (!snapshot || snapshot.assets.length === 0) {
      return null;
    }

    return (
      snapshot.assets.find((asset) => asset.asset.symbol === selectedSymbol) ?? snapshot.assets[0]
    );
  }, [selectedSymbol, snapshot]);

  const strongestInflow = useMemo(
    () =>
      snapshot?.assets
        .filter((asset) => asset.flow.estimatedNetFlow > 0)
        .sort((left, right) => right.flow.estimatedNetFlow - left.flow.estimatedNetFlow)[0] ??
      null,
    [snapshot]
  );

  const strongestOutflow = useMemo(
    () =>
      snapshot?.assets
        .filter((asset) => asset.flow.estimatedNetFlow < 0)
        .sort((left, right) => left.flow.estimatedNetFlow - right.flow.estimatedNetFlow)[0] ??
      null,
    [snapshot]
  );

  const chartHistory =
    selectedAsset?.history.map((point) => ({
      date: point.date.slice(5),
      close: point.close
    })) ?? [];

  const flowHistory =
    selectedAsset?.flow.netFlowSeries.slice(-30).map((point) => ({
      date: point.date.slice(5),
      value: point.value
    })) ?? [];

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">StockFlow</p>
          <h1>股票 / 基金资金流向可视化</h1>
          <p className="subtitle">
            基于每日 OHLCV 数据估算资金流向，支持股票与基金观察列表的日常更新和对比。
          </p>
        </div>
        <button className="refresh-button" onClick={handleRefresh} disabled={refreshing}>
          {refreshing ? "刷新中..." : "立即刷新"}
        </button>
      </header>

      {error ? <div className="banner error">{error}</div> : null}
      {snapshot?.freshness === "stale" ? (
        <div className="banner warning">{snapshot.staleReason ?? "当前数据已过期。"}</div>
      ) : null}

      {loading ? (
        <div className="empty-state">正在加载市场数据...</div>
      ) : snapshot == null || snapshot.assets.length === 0 ? (
        <div className="empty-state">暂无资产数据，请先执行数据刷新。</div>
      ) : (
        <>
          <section className="summary-grid">
            <article className={`summary-card ${cardTone(snapshot.marketSummary.totalEstimatedNetFlow)}`}>
              <span>10 日估算净流向</span>
              <strong>{formatCompact(snapshot.marketSummary.totalEstimatedNetFlow)}</strong>
              <small>观察列表合计</small>
            </article>
            <article className="summary-card neutral">
              <span>平均 MFI</span>
              <strong>{snapshot.marketSummary.averageMoneyFlowIndex.toFixed(2)}</strong>
              <small>高于 50 通常代表偏强资金动能</small>
            </article>
            <article className="summary-card positive">
              <span>最强流入</span>
              <strong>{strongestInflow?.asset.symbol ?? "--"}</strong>
              <small>{strongestInflow ? formatCompact(strongestInflow.flow.estimatedNetFlow) : "暂无"}</small>
            </article>
            <article className="summary-card negative">
              <span>最强流出</span>
              <strong>{strongestOutflow?.asset.symbol ?? "--"}</strong>
              <small>{strongestOutflow ? formatCompact(strongestOutflow.flow.estimatedNetFlow) : "暂无"}</small>
            </article>
          </section>

          <section className="panel">
            <div className="panel-header">
              <div>
                <h2>周度投资情报</h2>
                <p>
                  SQLite 历史库：
                  {intelligence?.databasePath ?? "尚未初始化"}。平时自动沉淀数据，周末集中复盘。
                </p>
              </div>
              <div className="pill-group">
                <span className="pill">日报 {intelligence?.latestDailyAnalysis?.trade_date ?? "--"}</span>
                <span className="pill">
                  周报 {intelligence?.latestWeeklyReport?.week_end ?? "--"}
                </span>
              </div>
            </div>

            <div className="filter-bar">
              <label>
                截止日期
                <input
                  type="date"
                  value={selectedDate}
                  onChange={(event) => {
                    setSelectedDate(event.target.value);
                    resetPages();
                  }}
                />
              </label>
              <label>
                每页条数
                <select
                  value={pageSize}
                  onChange={(event) => {
                    setPageSize(Number(event.target.value));
                    resetPages();
                  }}
                >
                  <option value={5}>5</option>
                  <option value={10}>10</option>
                  <option value={20}>20</option>
                  <option value={50}>50</option>
                </select>
              </label>
              <button
                className="ghost-button"
                type="button"
                onClick={() => {
                  setSelectedDate("");
                  resetPages();
                }}
              >
                查看最新
              </button>
              {intelligenceLoading ? <span className="inline-loading">列表更新中...</span> : null}
            </div>

            <CollapsibleSection title="历史数据与分析任务" subtitle="在页面触发行情、板块、新闻、中文化和周报生成">
              <div className="task-grid">
                {taskLabels.map((task) => (
                  <button
                    className="task-card"
                    disabled={runningTask != null}
                    key={task.action}
                    onClick={() => void handleRunTask(task.action)}
                    type="button"
                  >
                    <strong>{runningTask === task.action ? "执行中..." : task.title}</strong>
                    <span>{task.description}</span>
                  </button>
                ))}
              </div>
              {taskMessage ? <div className="banner success">{taskMessage}</div> : null}
              {runningTask ? (
                <div className="inline-empty">
                  正在执行任务，请稍候。涉及 Ollama 或外部数据源时可能需要几十秒。
                </div>
              ) : null}
            </CollapsibleSection>

            <CollapsibleSection title="周报日报" subtitle="每日摘要、周度复盘和下周关注">
              {intelligence?.latestWeeklyReport ? (
                <div className="intelligence-grid">
                  <article className="insight-card">
                    <span>本周市场</span>
                    <p>{intelligence.latestWeeklyReport.market_review}</p>
                  </article>
                  <article className="insight-card">
                    <span>资金与轮动</span>
                    <p>{intelligence.latestWeeklyReport.capital_flow_review}</p>
                  </article>
                  <article className="insight-card">
                    <span>机会观察</span>
                    <p>{intelligence.latestWeeklyReport.opportunity_watchlist}</p>
                  </article>
                  <article className="insight-card">
                    <span>风险提示</span>
                    <p>{intelligence.latestWeeklyReport.risk_watchlist}</p>
                  </article>
                </div>
              ) : (
                <div className="inline-empty">
                  暂无周报。执行 npm run report:weekly 或刷新行情后会生成历史分析底座。
                </div>
              )}
              {intelligence?.latestDailyAnalysis ? (
                <div className="intelligence-grid compact-grid">
                  <article className="insight-card">
                    <span>日报市场</span>
                    <p>{intelligence.latestDailyAnalysis.market_summary}</p>
                  </article>
                  <article className="insight-card">
                    <span>日报板块</span>
                    <p>{intelligence.latestDailyAnalysis.sector_summary}</p>
                  </article>
                  <article className="insight-card">
                    <span>日报新闻</span>
                    <p>{intelligence.latestDailyAnalysis.news_summary}</p>
                  </article>
                  <article className="insight-card">
                    <span>日报风险</span>
                    <p>{intelligence.latestDailyAnalysis.risk_summary}</p>
                  </article>
                </div>
              ) : null}
            </CollapsibleSection>

            <CollapsibleSection title="市场指数与周期" subtitle="A股、美股、港股主要指数及市场状态识别">
              {intelligence?.latestCycleReport ? (
                <div className="intelligence-grid compact-grid">
                  <article className="insight-card">
                    <span>半年周期阶段</span>
                    <p>
                      {intelligence.latestCycleReport.cycle_stage} ·{" "}
                      {intelligence.latestCycleReport.period_start} 至{" "}
                      {intelligence.latestCycleReport.period_end}
                    </p>
                  </article>
                  <article className="insight-card">
                    <span>市场概览</span>
                    <p>{intelligence.latestCycleReport.market_summary}</p>
                  </article>
                  <article className="insight-card">
                    <span>指数强弱</span>
                    <p>{intelligence.latestCycleReport.index_summary}</p>
                  </article>
                  <article className="insight-card">
                    <span>状态分布</span>
                    <p>{intelligence.latestCycleReport.regime_summary}</p>
                  </article>
                  <article className="insight-card">
                    <span>资金主线</span>
                    <p>{intelligence.latestCycleReport.sector_summary}</p>
                  </article>
                  <article className="insight-card">
                    <span>机会线索</span>
                    <p>{intelligence.latestCycleReport.opportunity_summary}</p>
                  </article>
                  <article className="insight-card">
                    <span>风险提示</span>
                    <p>{intelligence.latestCycleReport.risk_summary}</p>
                  </article>
                </div>
              ) : (
                <div className="inline-empty">暂无半年周期报告，请执行“分析历史周期”。</div>
              )}

              {intelligence?.latestMarketRegime ? (
                <div className="intelligence-grid compact-grid">
                  <article className="insight-card">
                    <span>市场状态</span>
                    <p>
                      {intelligence.latestMarketRegime.regime} · 趋势分
                      {intelligence.latestMarketRegime.trend_score.toFixed(1)} · 风险偏好
                      {intelligence.latestMarketRegime.risk_appetite_score.toFixed(1)}
                    </p>
                  </article>
                  <article className="insight-card">
                    <span>市场广度</span>
                    <p>
                      上涨广度 {intelligence.latestMarketRegime.breadth_score.toFixed(1)} · 流动性
                      {intelligence.latestMarketRegime.liquidity_score.toFixed(1)}
                    </p>
                  </article>
                  <article className="insight-card">
                    <span>判断依据</span>
                    <p>{intelligence.latestMarketRegime.notes ?? "暂无说明。"}</p>
                  </article>
                  <article className="insight-card">
                    <span>日期</span>
                    <p>{intelligence.latestMarketRegime.trade_date}</p>
                  </article>
                </div>
              ) : (
                <div className="inline-empty">暂无市场周期数据，请执行 npm run collect:indices。</div>
              )}

              {intelligence?.marketIndices.length ? (
                <>
                  <div className="table-wrapper">
                    <table>
                      <thead>
                        <tr>
                          <th>日期</th>
                          <th>指数</th>
                          <th>市场</th>
                          <th>收盘</th>
                          <th>涨跌幅</th>
                          <th>成交量</th>
                        </tr>
                      </thead>
                      <tbody>
                        {intelligence.marketIndices.map((item) => (
                          <tr key={`${item.trade_date}-${item.symbol}`}>
                            <td>{item.trade_date}</td>
                            <td>
                              {item.name} · {item.symbol}
                            </td>
                            <td>{item.region}</td>
                            <td>{item.close.toFixed(2)}</td>
                            <td className={cardTone(item.change_pct ?? 0)}>
                              {formatOptionalPercent(item.change_pct)}
                            </td>
                            <td>{formatCompact(item.volume ?? 0)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <PaginationControls
                    label="市场指数"
                    pageInfo={intelligence.pagination.marketIndices}
                    onPageChange={(page) => updatePage("marketIndices", page)}
                  />
                </>
              ) : null}
            </CollapsibleSection>

            <CollapsibleSection title="资金流向" subtitle="A股行业/概念板块、美股/港股ETF代理、板块头部股票">
              {intelligence?.sectorFlows.length ? (
                <>
                  <div className="table-wrapper">
                    <table>
                      <thead>
                        <tr>
                          <th>日期</th>
                          <th>板块</th>
                          <th>市场</th>
                          <th>涨跌幅</th>
                          <th>净流入</th>
                          <th>主力净流入</th>
                        </tr>
                      </thead>
                      <tbody>
                        {intelligence.sectorFlows.map((item) => (
                          <tr key={`${item.trade_date}-${item.sector_code}`}>
                            <td>{item.trade_date}</td>
                            <td>
                              {item.sector_name} · {item.sector_code}
                            </td>
                            <td>{item.market}</td>
                            <td className={cardTone(item.change_pct ?? 0)}>
                              {formatOptionalPercent(item.change_pct)}
                            </td>
                            <td className={cardTone(item.net_inflow ?? 0)}>
                              {formatCompact(item.net_inflow ?? 0)}
                            </td>
                            <td className={cardTone(item.main_net_inflow ?? 0)}>
                              {formatCompact(item.main_net_inflow ?? 0)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <PaginationControls
                    label="资金流向"
                    pageInfo={intelligence.pagination.sectorFlows}
                    onPageChange={(page) => updatePage("sectorFlows", page)}
                  />
                </>
              ) : (
                <div className="inline-empty">暂无资金流向数据。</div>
              )}

              {intelligence?.sectorLeaders.length ? (
                <>
                  <div className="table-wrapper">
                    <table>
                      <thead>
                        <tr>
                          <th>日期</th>
                          <th>所属板块</th>
                          <th>头部股票</th>
                          <th>涨跌幅</th>
                          <th>净流入</th>
                        </tr>
                      </thead>
                      <tbody>
                        {intelligence.sectorLeaders.map((item) => (
                          <tr key={`${item.trade_date}-${item.sector_code}-${item.symbol}`}>
                            <td>{item.trade_date}</td>
                            <td>{item.sector_name ?? item.sector_code}</td>
                            <td>
                              {item.symbol} · {item.name}
                            </td>
                            <td className={cardTone(item.change_pct ?? 0)}>
                              {formatOptionalPercent(item.change_pct)}
                            </td>
                            <td className={cardTone(item.net_inflow ?? 0)}>
                              {formatCompact(item.net_inflow ?? 0)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <PaginationControls
                    label="板块头部股票"
                    pageInfo={intelligence.pagination.sectorLeaders}
                    onPageChange={(page) => updatePage("sectorLeaders", page)}
                  />
                </>
              ) : null}
            </CollapsibleSection>

            <CollapsibleSection title="新闻行情" subtitle="财经新闻、利好利空标签和相关主题">
              {intelligence?.news.length ? (
                <>
                  <div className="news-list">
                    {intelligence.news.map((item) => (
                      <a className="news-card" href={item.url} key={item.id} target="_blank" rel="noreferrer">
                        <div>
                          <span className={`sentiment ${item.sentiment}`}>
                            {sentimentLabel[item.sentiment]} · {item.impact_level}
                          </span>
                          <strong>{item.title}</strong>
                          <small>
                            {item.source}
                            {item.related_sectors ? ` · ${item.related_sectors}` : ""}
                          </small>
                        </div>
                        <p>{item.thesis ?? "暂无舆情理由。"}</p>
                      </a>
                    ))}
                  </div>
                  <PaginationControls
                    label="新闻行情"
                    pageInfo={intelligence.pagination.news}
                    onPageChange={(page) => updatePage("news", page)}
                  />
                </>
              ) : (
                <div className="inline-empty">暂无新闻舆情数据。</div>
              )}
            </CollapsibleSection>

            <CollapsibleSection title="潜在早期机会" subtitle="资金持续性、排名改善、新闻热度、拥挤风险和基金映射">
              {intelligence?.earlyOpportunities.length ? (
                <div className="table-wrapper">
                  <table>
                    <thead>
                      <tr>
                        <th>日期</th>
                        <th>板块</th>
                        <th>早期分</th>
                        <th>资金持续</th>
                        <th>热度</th>
                        <th>拥挤风险</th>
                        <th>基金映射</th>
                        <th>动作建议</th>
                      </tr>
                    </thead>
                    <tbody>
                      {intelligence.earlyOpportunities.map((item) => (
                        <tr key={`${item.trade_date}-${item.target_code}`}>
                          <td>{item.trade_date}</td>
                          <td>
                            {item.target_code} · {item.target_name}
                            <div className="subtext">{item.thesis}</div>
                          </td>
                          <td>{item.early_score.toFixed(1)}</td>
                          <td>{item.flow_persistence_score.toFixed(1)}</td>
                          <td>{item.heat_score.toFixed(1)}</td>
                          <td className={item.crowding_risk_score > 60 ? "negative" : "neutral"}>
                            {item.crowding_risk_score.toFixed(1)}
                          </td>
                          <td className="wide-cell">{formatMatchedFunds(item.matched_funds)}</td>
                          <td className="wide-cell">{item.action_hint}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="inline-empty">暂无早期机会数据，请执行“分析投资机会”。</div>
              )}

              {intelligence?.trackedOpportunities.length ? (
                <div className="table-wrapper">
                  <table>
                    <thead>
                      <tr>
                        <th>周报日期</th>
                        <th>跟踪标的</th>
                        <th>入选分</th>
                        <th>最新日期</th>
                        <th>跟踪表现</th>
                        <th>状态</th>
                        <th>基金映射</th>
                      </tr>
                    </thead>
                    <tbody>
                      {intelligence.trackedOpportunities.map((item) => (
                        <tr key={item.id}>
                          <td>{item.source_report_date}</td>
                          <td>
                            {item.target_code} · {item.target_name}
                            <div className="subtext">{item.thesis}</div>
                          </td>
                          <td>{item.entry_score.toFixed(1)}</td>
                          <td>{item.latest_date ?? "--"}</td>
                          <td className={cardTone(item.return_pct ?? 0)}>
                            {item.return_pct == null ? "--" : formatPercent(item.return_pct)}
                          </td>
                          <td>{item.status}</td>
                          <td className="wide-cell">{formatMatchedFunds(item.matched_funds)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : null}
            </CollapsibleSection>

            <CollapsibleSection title="机会评分" subtitle="按趋势、资金、新闻和风险生成的关注列表">
              {intelligence?.opportunities.length ? (
                <>
                  <div className="table-wrapper">
                    <table>
                      <thead>
                        <tr>
                          <th>日期</th>
                          <th>标的</th>
                          <th>机会分</th>
                          <th>趋势</th>
                          <th>资金</th>
                          <th>风险</th>
                          <th>理由</th>
                        </tr>
                      </thead>
                      <tbody>
                        {intelligence.opportunities.map((item) => (
                          <tr key={`${item.trade_date}-${item.target_code}`}>
                            <td>{item.trade_date}</td>
                            <td>
                              {item.target_code} · {item.target_name}
                            </td>
                            <td>{item.opportunity_score.toFixed(1)}</td>
                            <td>{item.trend_score.toFixed(1)}</td>
                            <td>{item.capital_score.toFixed(1)}</td>
                            <td>{item.risk_score.toFixed(1)}</td>
                            <td className="wide-cell">{item.thesis}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <PaginationControls
                    label="机会评分"
                    pageInfo={intelligence.pagination.opportunities}
                    onPageChange={(page) => updatePage("opportunities", page)}
                  />
                </>
              ) : (
                <div className="inline-empty">暂无机会评分数据。</div>
              )}

              {intelligence?.coverage.length ? (
                <div className="coverage-list">
                  {intelligence.coverage.map((item) => (
                    <span
                      className={`coverage-chip ${item.status}`}
                      key={`${item.dataset}-${item.target_date}`}
                      title={item.notes ?? undefined}
                    >
                      {item.target_date} · {item.dataset} · {item.status}
                    </span>
                  ))}
                </div>
              ) : null}
            </CollapsibleSection>
          </section>

          <section className="panel">
            <div className="panel-header">
              <div>
                <h2>观察列表</h2>
                <p>最后更新：{formatDateTime(snapshot.updatedAt)}</p>
              </div>
              <div className="pill-group">
                <span className="pill">流入 {snapshot.marketSummary.inflowCount}</span>
                <span className="pill">流出 {snapshot.marketSummary.outflowCount}</span>
                <span className="pill">资产 {snapshot.marketSummary.assetCount}</span>
              </div>
            </div>
            <div className="table-wrapper">
              <table>
                <thead>
                  <tr>
                    <th>代码</th>
                    <th>名称</th>
                    <th>类型</th>
                    <th>现价</th>
                    <th>涨跌幅</th>
                    <th>10 日净流向</th>
                    <th>MFI</th>
                    <th>CMF</th>
                  </tr>
                </thead>
                <tbody>
                  {snapshot.assets.map((asset) => (
                    <tr
                      key={asset.asset.symbol}
                      className={asset.asset.symbol === selectedAsset?.asset.symbol ? "selected-row" : ""}
                      onClick={() => setSelectedSymbol(asset.asset.symbol)}
                    >
                      <td>{asset.asset.symbol}</td>
                      <td>{asset.shortName}</td>
                      <td>{typeLabel[asset.asset.type]}</td>
                      <td>{asset.lastPrice.toFixed(2)}</td>
                      <td className={cardTone(asset.changePct)}>{formatPercent(asset.changePct)}</td>
                      <td className={cardTone(asset.flow.estimatedNetFlow)}>
                        {formatCompact(asset.flow.estimatedNetFlow)}
                      </td>
                      <td>{asset.flow.moneyFlowIndex.toFixed(2)}</td>
                      <td>{asset.flow.chaikinMoneyFlow.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {selectedAsset ? (
            <section className="detail-grid">
              <article className="panel">
                <div className="panel-header">
                  <div>
                    <h2>
                      {selectedAsset.asset.symbol} · {selectedAsset.shortName}
                    </h2>
                    <p>
                      {selectedAsset.exchangeName} · {selectedAsset.currency} · {typeLabel[selectedAsset.asset.type]}
                    </p>
                  </div>
                  <div className="metric-stack">
                    <span>最新单日资金流：{formatCompact(selectedAsset.flow.latestDailyFlow)}</span>
                    <span>成交量：{formatCompact(selectedAsset.volume)}</span>
                  </div>
                </div>
                <div className="chart-shell">
                  <ResponsiveContainer width="100%" height={320}>
                    <LineChart data={chartHistory}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                      <XAxis dataKey="date" />
                      <YAxis domain={["auto", "auto"]} />
                      <Tooltip />
                      <Line
                        type="monotone"
                        dataKey="close"
                        stroke="#2563eb"
                        strokeWidth={2}
                        dot={false}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </article>

              <article className="panel">
                <div className="panel-header">
                  <div>
                    <h2>近 30 日估算资金流</h2>
                    <p>绿色代表流入，红色代表流出。</p>
                  </div>
                  <div className="metric-stack">
                    <span>MFI：{selectedAsset.flow.moneyFlowIndex.toFixed(2)}</span>
                    <span>CMF：{selectedAsset.flow.chaikinMoneyFlow.toFixed(2)}</span>
                  </div>
                </div>
                <div className="chart-shell">
                  <ResponsiveContainer width="100%" height={320}>
                    <BarChart data={flowHistory}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                      <XAxis dataKey="date" />
                      <YAxis />
                      <Tooltip />
                      <Bar dataKey="value" radius={[6, 6, 0, 0]}>
                        {flowHistory.map((entry) => (
                          <Cell key={entry.date} fill={entry.value >= 0 ? "#dc2626" : "#16a34a"} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </article>
            </section>
          ) : null}
        </>
      )}
    </div>
  );
};

export default App;
