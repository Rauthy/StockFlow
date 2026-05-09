import { execFile } from "node:child_process";
import { promisify } from "node:util";
import type { InvestmentIntelligence, MarketSnapshot } from "../../shared/models.js";
import { dataFile, stockflowScriptFile } from "../config.js";

const execFileAsync = promisify(execFile);

const runStockflowScript = async (args: string[]): Promise<string> => {
  const { stdout } = await execFileAsync("python3", [stockflowScriptFile, ...args], {
    maxBuffer: 1024 * 1024 * 10
  });
  return stdout;
};

export const persistSnapshotToDatabase = async (
  _snapshot: MarketSnapshot
): Promise<void> => {
  await runStockflowScript(["ingest-market-snapshot", "--input", dataFile]);
};

export interface InvestmentIntelligenceQuery {
  date?: string;
  pageSize?: number;
  sectorPage?: number;
  leaderPage?: number;
  newsPage?: number;
  opportunityPage?: number;
  marketPage?: number;
}

export const readInvestmentIntelligence = async (
  query: InvestmentIntelligenceQuery = {}
): Promise<InvestmentIntelligence> => {
  const args = ["api-summary"];
  if (query.date) {
    args.push("--date", query.date);
  }
  if (query.pageSize) {
    args.push("--page-size", String(query.pageSize));
  }
  if (query.sectorPage) {
    args.push("--sector-page", String(query.sectorPage));
  }
  if (query.leaderPage) {
    args.push("--leader-page", String(query.leaderPage));
  }
  if (query.newsPage) {
    args.push("--news-page", String(query.newsPage));
  }
  if (query.opportunityPage) {
    args.push("--opportunity-page", String(query.opportunityPage));
  }
  if (query.marketPage) {
    args.push("--market-page", String(query.marketPage));
  }
  const stdout = await runStockflowScript(args);
  return JSON.parse(stdout) as InvestmentIntelligence;
};

export type IntelligenceTaskAction =
  | "backfill"
  | "collect-indices"
  | "collect-sectors"
  | "collect-news"
  | "collect-external"
  | "enrich-news"
  | "analyze-opportunities"
  | "analyze-cycles"
  | "report-weekly";

const taskArguments: Record<IntelligenceTaskAction, string[]> = {
  backfill: ["backfill"],
  "collect-indices": ["collect-indices"],
  "collect-sectors": ["collect-sectors"],
  "collect-news": ["collect-news"],
  "collect-external": ["collect-external"],
  "enrich-news": ["enrich-news"],
  "analyze-opportunities": ["analyze-opportunities"],
  "analyze-cycles": ["analyze-cycles"],
  "report-weekly": ["report-weekly"]
};

export interface IntelligenceTaskResult {
  action: IntelligenceTaskAction;
  output: unknown;
}

export const runInvestmentTask = async (
  action: IntelligenceTaskAction
): Promise<IntelligenceTaskResult> => {
  const args = taskArguments[action];
  if (!args) {
    throw new Error(`不支持的投资情报任务：${action}`);
  }
  const stdout = await runStockflowScript(args);
  const trimmed = stdout.trim();
  return {
    action,
    output: trimmed ? JSON.parse(trimmed) : { status: "ok" }
  };
};
