import { resolve } from "node:path";

export const rootDirectory = process.cwd();
export const dataFile = resolve(rootDirectory, "data/market-snapshot.json");
export const databaseFile = resolve(rootDirectory, "data/stockflow.sqlite");
export const stockflowScriptFile = resolve(rootDirectory, "scripts/stockflow.py");
export const watchlistFile = resolve(rootDirectory, "config/watchlist.json");
