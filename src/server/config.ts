import { resolve } from "node:path";

export const rootDirectory = process.cwd();
export const dataFile = resolve(rootDirectory, "data/market-snapshot.json");
export const watchlistFile = resolve(rootDirectory, "config/watchlist.json");

