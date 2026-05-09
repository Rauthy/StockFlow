import type { PriceBar, WatchlistAsset } from "../../shared/models.js";

interface SinaKlineRecord {
  day: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: string;
}

export interface SinaAssetResult {
  history: PriceBar[];
  shortName: string;
  exchangeName: string;
  currency: string;
  regularMarketPrice: number;
  previousClose: number;
}

const endpointFor = (symbol: string): string =>
  `https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_data=/CN_MarketData.getKLineData?symbol=${encodeURIComponent(
    symbol
  )}&scale=240&ma=no&datalen=260`;

const toSinaSymbol = (symbol: string): string => {
  if (symbol.startsWith("sh") || symbol.startsWith("sz")) {
    return symbol.toLowerCase();
  }

  const normalized = symbol.trim().toUpperCase();
  if (normalized.endsWith(".SH")) {
    return `sh${normalized.slice(0, -3)}`;
  }
  if (normalized.endsWith(".SZ")) {
    return `sz${normalized.slice(0, -3)}`;
  }

  throw new Error(`暂不支持的证券代码格式：${symbol}`);
};

const extractPayload = (body: string): SinaKlineRecord[] => {
  const matched = body.match(/=\((.*)\)\s*;?\s*$/s);
  if (!matched?.[1]) {
    throw new Error("无法解析新浪行情接口返回内容。");
  }

  return JSON.parse(matched[1]) as SinaKlineRecord[];
};

export const fetchSinaAssetData = async (
  asset: WatchlistAsset
): Promise<SinaAssetResult> => {
  const response = await fetch(endpointFor(toSinaSymbol(asset.symbol)), {
    headers: {
      "user-agent": "Mozilla/5.0",
      referer: "https://finance.sina.com.cn/"
    }
  });

  if (!response.ok) {
    throw new Error(`无法获取 ${asset.symbol} 的行情数据：HTTP ${response.status}`);
  }

  const records = extractPayload(await response.text());
  const history = records.map((record) => ({
    date: record.day,
    open: Number(record.open),
    high: Number(record.high),
    low: Number(record.low),
    close: Number(record.close),
    volume: Number(record.volume)
  }));

  if (history.length < 2) {
    throw new Error(`${asset.symbol} 的有效历史数据不足，无法完成资金流向分析。`);
  }

  const lastBar = history.at(-1)!;
  const previousBar = history.at(-2)!;

  return {
    history,
    shortName: asset.name,
    exchangeName: asset.symbol.endsWith(".SH") ? "上交所" : "深交所",
    currency: asset.currency,
    regularMarketPrice: lastBar.close,
    previousClose: previousBar.close
  };
};
