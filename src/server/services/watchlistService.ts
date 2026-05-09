import { readFile } from "node:fs/promises";
import { watchlistFile } from "../config.js";
import type { WatchlistAsset } from "../../shared/models.js";

export const readWatchlist = async (): Promise<WatchlistAsset[]> => {
  const raw = await readFile(watchlistFile, "utf8");
  return JSON.parse(raw) as WatchlistAsset[];
};

