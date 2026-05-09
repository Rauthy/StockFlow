import type { FlowMetrics, FlowPoint, PriceBar } from "./models.js";

const moneyFlowWindow = 14;
const chaikinWindow = 20;
const trendWindow = 10;

const round = (value: number): number => Number(value.toFixed(2));

const typicalPrice = (bar: PriceBar): number => (bar.high + bar.low + bar.close) / 3;

const dailySignedFlow = (current: PriceBar, previousClose: number): number =>
  (current.close - previousClose) * current.volume;

export const calculateFlowMetrics = (history: PriceBar[]): FlowMetrics => {
  if (history.length < 2) {
    return {
      latestDailyFlow: 0,
      estimatedNetFlow: 0,
      moneyFlowIndex: 50,
      chaikinMoneyFlow: 0,
      accumulationDistribution: 0,
      flowStrength: "neutral",
      netFlowSeries: []
    };
  }

  const netFlowSeries: FlowPoint[] = [];
  for (let index = 1; index < history.length; index += 1) {
    const bar = history[index]!;
    const previousBar = history[index - 1]!;
    netFlowSeries.push({
      date: bar.date,
      value: round(dailySignedFlow(bar, previousBar.close))
    });
  }

  const trailingFlows = netFlowSeries.slice(-trendWindow);
  const estimatedNetFlow = round(
    trailingFlows.reduce((sum, point) => sum + point.value, 0)
  );
  const latestDailyFlow = trailingFlows.at(-1)?.value ?? 0;

  const moneyFlowBars = history.slice(-moneyFlowWindow - 1);
  let positiveMoneyFlow = 0;
  let negativeMoneyFlow = 0;

  for (let index = 1; index < moneyFlowBars.length; index += 1) {
    const current = moneyFlowBars[index]!;
    const previous = moneyFlowBars[index - 1]!;
    const rawMoneyFlow = typicalPrice(current) * current.volume;
    if (typicalPrice(current) > typicalPrice(previous)) {
      positiveMoneyFlow += rawMoneyFlow;
    } else if (typicalPrice(current) < typicalPrice(previous)) {
      negativeMoneyFlow += rawMoneyFlow;
    }
  }

  const moneyFlowRatio =
    negativeMoneyFlow === 0 ? positiveMoneyFlow : positiveMoneyFlow / negativeMoneyFlow;
  const moneyFlowIndex =
    negativeMoneyFlow === 0
      ? 100
      : round(100 - 100 / (1 + moneyFlowRatio));

  const chaikinBars = history.slice(-chaikinWindow);
  let adlRunningTotal = 0;
  let chaikinNumerator = 0;
  let chaikinDenominator = 0;

  for (const bar of chaikinBars) {
    const range = bar.high - bar.low;
    const moneyFlowMultiplier =
      range === 0 ? 0 : ((bar.close - bar.low) - (bar.high - bar.close)) / range;
    const moneyFlowVolume = moneyFlowMultiplier * bar.volume;
    adlRunningTotal += moneyFlowVolume;
    chaikinNumerator += moneyFlowVolume;
    chaikinDenominator += bar.volume;
  }

  const chaikinMoneyFlow =
    chaikinDenominator === 0 ? 0 : round(chaikinNumerator / chaikinDenominator);

  const flowStrength =
    estimatedNetFlow > 0 ? "inflow" : estimatedNetFlow < 0 ? "outflow" : "neutral";

  return {
    latestDailyFlow,
    estimatedNetFlow,
    moneyFlowIndex,
    chaikinMoneyFlow,
    accumulationDistribution: round(adlRunningTotal),
    flowStrength,
    netFlowSeries
  };
};

export const buildMarketSummary = (assetFlows: FlowMetrics[]) => {
  const assetCount = assetFlows.length;
  const totalEstimatedNetFlow = round(
    assetFlows.reduce((sum, flow) => sum + flow.estimatedNetFlow, 0)
  );
  const averageMoneyFlowIndex = round(
    assetCount === 0
      ? 0
      : assetFlows.reduce((sum, flow) => sum + flow.moneyFlowIndex, 0) / assetCount
  );
  const inflowCount = assetFlows.filter((flow) => flow.flowStrength === "inflow").length;
  const outflowCount = assetFlows.filter((flow) => flow.flowStrength === "outflow").length;

  return {
    assetCount,
    totalEstimatedNetFlow,
    averageMoneyFlowIndex,
    inflowCount,
    outflowCount
  };
};
