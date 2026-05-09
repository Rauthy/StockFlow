import { buildMarketSummary, calculateFlowMetrics } from "../../shared/analytics.js";
import type { AssetSnapshot, MarketSnapshot, SnapshotFreshness } from "../../shared/models.js";
import { readSnapshot, writeSnapshot } from "../storage/snapshotStore.js";
import { persistSnapshotToDatabase } from "./investmentIntelligenceService.js";
import { fetchSinaAssetData } from "./sinaMarketClient.js";
import { readWatchlist } from "./watchlistService.js";

const todayStamp = (): string => new Date().toISOString().slice(0, 10);

const createSnapshot = (
  assets: AssetSnapshot[],
  freshness: SnapshotFreshness,
  staleReason?: string
): MarketSnapshot => ({
  updatedAt: new Date().toISOString(),
  source: "sina-market",
  freshness,
  staleReason,
  marketSummary: buildMarketSummary(assets.map((asset) => asset.flow)),
  assets
});

export const refreshMarketData = async (): Promise<MarketSnapshot> => {
  const watchlist = await readWatchlist();
  const assetResults = await Promise.all(
    watchlist.map(async (asset) => {
      const marketData = await fetchSinaAssetData(asset);
      const flow = calculateFlowMetrics(marketData.history);
      const change = marketData.regularMarketPrice - marketData.previousClose;
      const changePct =
        marketData.previousClose === 0 ? 0 : (change / marketData.previousClose) * 100;

      const assetSnapshot: AssetSnapshot = {
        asset,
        shortName: marketData.shortName,
        exchangeName: marketData.exchangeName,
        currency: marketData.currency,
        lastPrice: Number(marketData.regularMarketPrice.toFixed(2)),
        previousClose: Number(marketData.previousClose.toFixed(2)),
        change: Number(change.toFixed(2)),
        changePct: Number(changePct.toFixed(2)),
        volume: marketData.history.at(-1)?.volume ?? 0,
        history: marketData.history,
        flow,
        updatedAt: new Date().toISOString()
      };

      return assetSnapshot;
    })
  );

  const snapshot = createSnapshot(assetResults, "fresh");
  await writeSnapshot(snapshot);
  await persistSnapshotToDatabase(snapshot);
  return snapshot;
};

export const getMarketSnapshot = async (): Promise<MarketSnapshot> => {
  const snapshot = await readSnapshot();
  const currentStamp = todayStamp();
  const snapshotStamp = snapshot.updatedAt?.slice(0, 10);

  if (snapshotStamp === currentStamp && snapshot.freshness === "fresh") {
    return snapshot;
  }

  try {
    return await refreshMarketData();
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "刷新市场数据时发生未知错误。";
    const staleSnapshot: MarketSnapshot = {
      ...snapshot,
      freshness: "stale",
      staleReason: message
    };
    await writeSnapshot(staleSnapshot);
    return staleSnapshot;
  }
};
