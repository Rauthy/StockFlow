import type { MarketSnapshot } from "../shared/models.js";

const parseResponse = async (response: Response): Promise<MarketSnapshot> => {
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { message?: string } | null;
    throw new Error(payload?.message ?? "请求失败。");
  }

  return (await response.json()) as MarketSnapshot;
};

export const fetchMarketSnapshot = async (): Promise<MarketSnapshot> =>
  parseResponse(await fetch("/api/market"));

export const refreshMarketSnapshot = async (): Promise<MarketSnapshot> =>
  parseResponse(
    await fetch("/api/update", {
      method: "POST"
    })
  );

