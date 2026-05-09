import type { InvestmentIntelligence, MarketSnapshot } from "../shared/models.js";

const parseResponse = async <Payload>(response: Response): Promise<Payload> => {
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { message?: string } | null;
    throw new Error(payload?.message ?? "请求失败。");
  }

  return (await response.json()) as Payload;
};

export const fetchMarketSnapshot = async (): Promise<MarketSnapshot> =>
  parseResponse<MarketSnapshot>(await fetch("/api/market"));

export const refreshMarketSnapshot = async (): Promise<MarketSnapshot> =>
  parseResponse<MarketSnapshot>(
    await fetch("/api/update", {
      method: "POST"
    })
  );

export interface IntelligenceQuery {
  date?: string;
  pageSize?: number;
  sectorPage?: number;
  leaderPage?: number;
  newsPage?: number;
  opportunityPage?: number;
  marketPage?: number;
}

export const fetchInvestmentIntelligence = async (
  query: IntelligenceQuery = {}
): Promise<InvestmentIntelligence> => {
  const params = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (value != null && value !== "") {
      params.set(key, String(value));
    }
  });
  const queryString = params.toString();
  return parseResponse<InvestmentIntelligence>(
    await fetch(`/api/intelligence${queryString ? `?${queryString}` : ""}`)
  );
};

export type IntelligenceTaskAction =
  | "collect-daily"
  | "backfill"
  | "collect-indices"
  | "collect-sectors"
  | "collect-news"
  | "collect-external"
  | "enrich-news"
  | "analyze-opportunities"
  | "analyze-cycles"
  | "report-weekly";

export interface IntelligenceTaskResult {
  action: IntelligenceTaskAction;
  output: unknown;
}

export const runInvestmentTask = async (
  action: IntelligenceTaskAction
): Promise<IntelligenceTaskResult> =>
  parseResponse<IntelligenceTaskResult>(
    await fetch("/api/intelligence/tasks", {
      method: "POST",
      headers: {
        "content-type": "application/json"
      },
      body: JSON.stringify({ action })
    })
  );
