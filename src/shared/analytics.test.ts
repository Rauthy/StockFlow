import { describe, expect, it } from "vitest";
import { buildMarketSummary, calculateFlowMetrics } from "./analytics.js";
import type { PriceBar } from "./models.js";

const sampleHistory: PriceBar[] = [
  { date: "2026-04-07", open: 10, high: 11, low: 9.8, close: 10.5, volume: 1000 },
  { date: "2026-04-08", open: 10.4, high: 11.2, low: 10.2, close: 11, volume: 1100 },
  { date: "2026-04-09", open: 11, high: 11.1, low: 10.5, close: 10.7, volume: 950 },
  { date: "2026-04-10", open: 10.8, high: 11.3, low: 10.6, close: 11.2, volume: 1250 },
  { date: "2026-04-11", open: 11.2, high: 11.5, low: 11, close: 11.4, volume: 1300 },
  { date: "2026-04-12", open: 11.3, high: 11.6, low: 11.1, close: 11.5, volume: 1400 },
  { date: "2026-04-13", open: 11.4, high: 11.9, low: 11.3, close: 11.8, volume: 1600 },
  { date: "2026-04-14", open: 11.7, high: 12.1, low: 11.5, close: 12, volume: 1700 },
  { date: "2026-04-15", open: 11.9, high: 12.2, low: 11.7, close: 12.1, volume: 1750 },
  { date: "2026-04-16", open: 12.1, high: 12.3, low: 11.8, close: 12, volume: 1800 },
  { date: "2026-04-17", open: 12, high: 12.4, low: 11.9, close: 12.3, volume: 1900 }
];

describe("calculateFlowMetrics", () => {
  it("builds a flow series and classifies inflow correctly", () => {
    const metrics = calculateFlowMetrics(sampleHistory);

    expect(metrics.netFlowSeries).toHaveLength(sampleHistory.length - 1);
    expect(metrics.estimatedNetFlow).toBeGreaterThan(0);
    expect(metrics.flowStrength).toBe("inflow");
    expect(metrics.moneyFlowIndex).toBeGreaterThan(50);
  });

  it("aggregates summary values", () => {
    const metrics = calculateFlowMetrics(sampleHistory);
    const summary = buildMarketSummary([metrics, { ...metrics, estimatedNetFlow: -500, flowStrength: "outflow" }]);

    expect(summary.assetCount).toBe(2);
    expect(summary.inflowCount).toBe(1);
    expect(summary.outflowCount).toBe(1);
  });
});

