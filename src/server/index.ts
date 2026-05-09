import express from "express";
import { readFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { getMarketSnapshot, refreshMarketData } from "./services/marketDataService.js";
import {
  readInvestmentIntelligence,
  runInvestmentTask,
  type IntelligenceTaskAction
} from "./services/investmentIntelligenceService.js";

const currentFile = fileURLToPath(import.meta.url);
const currentDirectory = dirname(currentFile);
const clientDirectory = resolve(currentDirectory, "../client");

const app = express();
const port = Number(process.env.PORT ?? 3001);

app.use(express.json());

const optionalString = (value: unknown): string | undefined =>
  typeof value === "string" && value.trim() !== "" ? value.trim() : undefined;

const optionalPositiveInteger = (value: unknown): number | undefined => {
  const raw = optionalString(value);
  if (!raw) {
    return undefined;
  }
  const parsed = Number.parseInt(raw, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : undefined;
};

type IntelligenceTaskRequestAction = IntelligenceTaskAction | "collect-daily";

const isTaskAction = (value: unknown): value is IntelligenceTaskRequestAction =>
  typeof value === "string" &&
  [
    "backfill",
    "collect-indices",
    "collect-sectors",
    "collect-news",
    "collect-external",
    "enrich-news",
    "analyze-opportunities",
    "analyze-cycles",
    "report-weekly",
    "collect-daily"
  ].includes(value);

app.get("/api/market", async (_request, response) => {
  try {
    const snapshot = await getMarketSnapshot();
    response.json(snapshot);
  } catch (error) {
    response.status(500).json({
      message: error instanceof Error ? error.message : "读取市场数据失败。"
    });
  }
});

app.post("/api/update", async (_request, response) => {
  try {
    const snapshot = await refreshMarketData();
    response.json(snapshot);
  } catch (error) {
    response.status(500).json({
      message: error instanceof Error ? error.message : "更新市场数据失败。"
    });
  }
});

app.get("/api/watchlist", async (_request, response) => {
  try {
    const raw = await readFile(resolve(process.cwd(), "config/watchlist.json"), "utf8");
    response.type("application/json").send(raw);
  } catch (error) {
    response.status(500).json({
      message: error instanceof Error ? error.message : "读取观察列表失败。"
    });
  }
});

app.get("/api/intelligence", async (request, response) => {
  try {
    const intelligence = await readInvestmentIntelligence({
      date: optionalString(request.query.date),
      pageSize: optionalPositiveInteger(request.query.pageSize),
      sectorPage: optionalPositiveInteger(request.query.sectorPage),
      leaderPage: optionalPositiveInteger(request.query.leaderPage),
      newsPage: optionalPositiveInteger(request.query.newsPage),
      opportunityPage: optionalPositiveInteger(request.query.opportunityPage),
      marketPage: optionalPositiveInteger(request.query.marketPage)
    });
    response.json(intelligence);
  } catch (error) {
    response.status(500).json({
      message: error instanceof Error ? error.message : "读取投资情报数据失败。"
    });
  }
});

app.post("/api/intelligence/tasks", async (request, response) => {
  try {
    const action = request.body?.action;
    if (!isTaskAction(action)) {
      response.status(400).json({ message: "不支持的历史数据或分析任务。" });
      return;
    }

    if (action === "collect-daily") {
      await refreshMarketData();
      const external = await runInvestmentTask("collect-external");
      const report = await runInvestmentTask("report-weekly");
      const opportunities = await runInvestmentTask("analyze-opportunities");
      response.json({ action, output: { external, report, opportunities } });
      return;
    }

    const result = await runInvestmentTask(action);
    response.json(result);
  } catch (error) {
    response.status(500).json({
      message: error instanceof Error ? error.message : "执行历史数据或分析任务失败。"
    });
  }
});

if (existsSync(resolve(clientDirectory, "index.html"))) {
  app.use(express.static(clientDirectory));
  app.get("/{*splat}", (_request, response) => {
    response.sendFile(resolve(clientDirectory, "index.html"));
  });
}

app.listen(port, () => {
  console.log(`StockFlow server listening on http://localhost:${port}`);
});
