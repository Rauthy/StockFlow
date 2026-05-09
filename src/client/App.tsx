import { useEffect, useMemo, useState } from "react";
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
import { fetchMarketSnapshot, refreshMarketSnapshot } from "./api.js";
import type { AssetSnapshot, MarketSnapshot } from "../shared/models.js";

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

const App = () => {
  const [snapshot, setSnapshot] = useState<MarketSnapshot | null>(null);
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

  const handleRefresh = async () => {
    setRefreshing(true);
    setError(null);
    try {
      const nextSnapshot = await refreshMarketSnapshot();
      setSnapshot(nextSnapshot);
      setSelectedSymbol((current) => current ?? nextSnapshot.assets[0]?.asset.symbol ?? null);
    } catch (refreshError) {
      setError(refreshError instanceof Error ? refreshError.message : "刷新失败。");
    } finally {
      setRefreshing(false);
    }
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
                          <Cell key={entry.date} fill={entry.value >= 0 ? "#16a34a" : "#dc2626"} />
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
