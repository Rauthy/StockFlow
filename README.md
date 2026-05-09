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
```

后端在读取 `/api/market` 时，如果发现缓存不是当天数据，也会自动尝试刷新；若刷新失败，会明确标记为 **stale** 并保留错误原因。

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

## 项目结构

```text
config/watchlist.json         观察列表
data/market-snapshot.json     本地缓存快照
src/client/                   前端页面
src/server/                   后端服务与数据更新逻辑
src/shared/                   共享类型与资金流分析逻辑
```
