import express from "express";
import { readFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { getMarketSnapshot, refreshMarketData } from "./services/marketDataService.js";

const currentFile = fileURLToPath(import.meta.url);
const currentDirectory = dirname(currentFile);
const clientDirectory = resolve(currentDirectory, "../client");

const app = express();
const port = Number(process.env.PORT ?? 3001);

app.use(express.json());

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

if (existsSync(resolve(clientDirectory, "index.html"))) {
  app.use(express.static(clientDirectory));
  app.get("/{*splat}", (_request, response) => {
    response.sendFile(resolve(clientDirectory, "index.html"));
  });
}

app.listen(port, () => {
  console.log(`StockFlow server listening on http://localhost:${port}`);
});
