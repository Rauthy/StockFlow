# StockFlow

一个使用 **TypeScript** 实现的股票 / 基金可视化工具，支持：

- 每日更新观察列表中的股票和基金数据
- 基于 OHLCV（日线开高低收量）估算资金流向
- 展示价格走势、近 30 日资金流柱状图、资产强弱对比
- 通过本地 JSON 缓存保存最新快照，接口按日自动补刷新

## 技术栈

- **前端**：React + Vite + Recharts
- **后端**：Express
- **语言**：TypeScript
- **数据源**：新浪公开行情接口

## 资金流向说明

页面中的“资金流向”不是交易所逐笔大单资金，而是基于日线价格和成交量计算出的**估算资金流指标**，主要包含：

- **10 日估算净流向**
- **Money Flow Index (MFI)**
- **Chaikin Money Flow (CMF)**
- **Accumulation / Distribution**

这套指标适合看资金强弱、趋势变化和资产之间的相对比较。

## 默认观察列表

默认内置了 6 个 A 股 / ETF 标的：

- 贵州茅台 `600519.SH`
- 宁德时代 `300750.SZ`
- 中国平安 `601318.SH`
- 沪深300ETF `510300.SH`
- 创业板ETF `159915.SZ`
- 科创50ETF `588000.SH`

可以直接修改 `config/watchlist.json` 扩展自己的观察列表。

## 安装

```bash
npm install
```

## 开发运行

```bash
npm run dev
```

前端默认运行在 `http://localhost:5173`，后端 API 默认运行在 `http://localhost:3001`。

## 手动刷新每日数据

```bash
npm run update:data
```

刷新结果会写入：

```text
data/market-snapshot.json
data/stockflow.sqlite
```

后端在读取 `/api/market` 时，如果发现缓存不是当天数据，也会自动尝试刷新；若刷新失败，会明确标记为 **stale** 并保留错误原因。刷新成功后会同时把历史日线、日报分析和机会评分写入本地 SQLite，供周报和历史趋势分析使用。

## 本地历史库与周报

StockFlow 使用 `data/stockflow.sqlite` 作为本地历史数据库，适合沉淀日线行情、资金流指标、新闻舆情结果、每日分析和周报。数据库文件为本地运行产物，不会提交到 Git。

初始化数据库：

```bash
npm run db:init
```

从现有快照回填历史日线并生成周报：

```bash
npm run backfill
```

每日采集并沉淀数据：

```bash
npm run collect:daily
```

单独采集 A 股行业 / 概念板块资金流：

```bash
npm run collect:sectors
```

单独采集 A 股 / 美股 / 港股主要指数并生成市场周期评分：

```bash
npm run collect:indices
```

回填指定时间段的指数历史数据：

```bash
python3 scripts/stockflow.py collect-indices --from 2025-01-01 --to 2025-12-31
```

单独采集财经新闻 RSS 并生成关键词舆情标签：

```bash
npm run collect:news
```

使用本地 Ollama 模型把新闻标题、摘要和影响判断统一转换为中文：

```bash
npm run enrich:news
```

默认使用 `qwen3:8b`，可以通过环境变量切换模型：

```bash
STOCKFLOW_OLLAMA_MODEL=gpt-oss:20b npm run enrich:news
```

分析潜在早期机会、基金映射和周报机会跟踪：

```bash
npm run analyze:opportunities
```

分析过去半年市场周期、指数强弱、资金主线和风险阶段：

```bash
npm run analyze:cycles
```

按指定截止日和窗口生成年度周期报告：

```bash
python3 scripts/stockflow.py analyze-cycles --lookback-days 364 --end-date 2025-12-31
```

生成或刷新最近一周周报：

```bash
npm run report:weekly
```

当前周报会基于观察列表日线、东方财富 A 股行业 / 概念板块资金流、板块头部股票、财经新闻 RSS 舆情标签生成。新闻舆情先使用关键词规则做初筛，再可选调用本地 Ollama 进行中文化和影响判断归纳。机会分析会结合资金持续性、排名改善、新闻热度、拥挤风险和 `config/fund-map.json` 中的基金映射，生成潜在早期机会和周报跟踪复盘。历史周期分析默认整理过去半年，用于判断市场处于修复、扩张、震荡还是防御阶段。

## 生产构建与启动

```bash
npm run build
npm run start
```

构建后：

- 前端产物位于 `dist/client`
- 后端产物位于 `dist/server`

## 主要接口

- `GET /api/market`：读取当前市场快照，必要时自动刷新
- `POST /api/update`：立即刷新全部观察标的数据
- `GET /api/watchlist`：读取当前观察列表
- `GET /api/intelligence`：读取 SQLite 中的日报、周报、机会评分和数据覆盖状态

## 项目结构

```text
config/watchlist.json         观察列表
data/market-snapshot.json     本地缓存快照
data/stockflow.sqlite         本地历史数据库（运行时生成）
scripts/stockflow.py          SQLite 初始化、入库、回填和周报生成
src/client/                   前端页面
src/server/                   后端服务与数据更新逻辑
src/shared/                   共享类型与资金流分析逻辑
```
