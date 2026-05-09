import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import { dataFile } from "../config.js";
import type { MarketSnapshot } from "../../shared/models.js";

export const readSnapshot = async (): Promise<MarketSnapshot> => {
  const raw = await readFile(dataFile, "utf8");
  return JSON.parse(raw) as MarketSnapshot;
};

export const writeSnapshot = async (snapshot: MarketSnapshot): Promise<void> => {
  await mkdir(dirname(dataFile), { recursive: true });
  await writeFile(dataFile, `${JSON.stringify(snapshot, null, 2)}\n`, "utf8");
};

