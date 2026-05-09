#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import sqlite3
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
DATABASE_FILE = DATA_DIR / "stockflow.sqlite"
SNAPSHOT_FILE = DATA_DIR / "market-snapshot.json"
FUND_MAP_FILE = ROOT_DIR / "config/fund-map.json"
OLLAMA_MODEL = os.environ.get("STOCKFLOW_OLLAMA_MODEL", "qwen3:8b")
OLLAMA_TIMEOUT_SECONDS = int(os.environ.get("STOCKFLOW_OLLAMA_TIMEOUT", "120"))
EASTMONEY_FIELDS = "f12,f14,f2,f3,f62,f66,f69,f72,f75,f78,f81,f84,f87,f124,f184"
EASTMONEY_SECTOR_URL = (
    "https://push2.eastmoney.com/api/qt/clist/get?"
    "pn=1&pz={limit}&po=1&np=1&fltt=2&invt=2&fid=f62&fs={fs}&fields="
    + EASTMONEY_FIELDS
)
EASTMONEY_LEADER_URL = (
    "https://push2.eastmoney.com/api/qt/clist/get?"
    "pn=1&pz={limit}&po=1&np=1&fltt=2&invt=2&fid=f62&fs=b:{sector_code}&fields=f12,f14,f2,f3,f62"
)
NEWS_RSS_SOURCES = [
    ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex", "en"),
    ("Sina Finance", "https://rss.sina.com.cn/finance/roll.xml", "zh"),
]
GLOBAL_SECTOR_PROXIES = [
    ("XLK", "美股科技", "美股板块ETF"),
    ("XLF", "美股金融", "美股板块ETF"),
    ("XLV", "美股医疗保健", "美股板块ETF"),
    ("XLY", "美股可选消费", "美股板块ETF"),
    ("XLP", "美股必需消费", "美股板块ETF"),
    ("XLE", "美股能源", "美股板块ETF"),
    ("XLI", "美股工业", "美股板块ETF"),
    ("XLB", "美股材料", "美股板块ETF"),
    ("XLU", "美股公用事业", "美股板块ETF"),
    ("XLRE", "美股房地产", "美股板块ETF"),
    ("XLC", "美股通信服务", "美股板块ETF"),
    ("2800.HK", "港股恒生指数ETF", "港股板块/指数ETF"),
    ("3033.HK", "港股科技ETF", "港股板块/指数ETF"),
    ("3067.HK", "港股医疗ETF", "港股板块/指数ETF"),
    ("2822.HK", "港股A50 ETF", "港股板块/指数ETF"),
    ("2836.HK", "港股印度ETF", "港股板块/指数ETF"),
]
MARKET_INDICES = [
    ("000001.SS", "上证指数", "CN"),
    ("399001.SZ", "深证成指", "CN"),
    ("399006.SZ", "创业板指", "CN"),
    ("000300.SS", "沪深300", "CN"),
    ("^GSPC", "标普500", "US"),
    ("^IXIC", "纳斯达克综合", "US"),
    ("^DJI", "道琼斯工业", "US"),
    ("^RUT", "罗素2000", "US"),
    ("^VIX", "VIX恐慌指数", "US"),
    ("^HSI", "恒生指数", "HK"),
    ("^HSCE", "恒生中国企业指数", "HK"),
]

POSITIVE_KEYWORDS = [
    "利好",
    "增长",
    "上涨",
    "突破",
    "支持",
    "回购",
    "预增",
    "降息",
    "刺激",
    "strong",
    "growth",
    "surge",
    "rally",
    "beat",
    "cuts rates",
    "optimism",
]
NEGATIVE_KEYWORDS = [
    "利空",
    "下跌",
    "风险",
    "监管",
    "制裁",
    "亏损",
    "下滑",
    "衰退",
    "crackdown",
    "risk",
    "falls",
    "slump",
    "miss",
    "recession",
    "tariff",
    "warning",
]
SECTOR_KEYWORDS = {
    "AI/算力": ["ai", "人工智能", "算力", "芯片", "semiconductor", "chip", "nvidia"],
    "新能源": ["新能源", "电池", "光伏", "储能", "ev", "battery", "solar"],
    "医药": ["医药", "创新药", "biotech", "pharma", "drug"],
    "金融": ["银行", "券商", "保险", "bank", "fed", "rates"],
    "消费": ["消费", "白酒", "零售", "consumer", "retail"],
    "地产": ["地产", "房地产", "property", "real estate"],
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_FILE)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def fetch_text(url: str, timeout: int = 20) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json,text/xml,application/xml,text/html,*/*",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "ignore")


def fetch_json(url: str) -> dict[str, Any]:
    return json.loads(fetch_text(url))


def ollama_available() -> bool:
    try:
        subprocess.run(
            ["ollama", "list"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=8,
        )
        return True
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def ollama_generate(prompt: str) -> str | None:
    if not ollama_available():
        return None
    payload = json.dumps(
        {
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1, "num_predict": 300},
        }
    ).encode("utf-8")
    try:
        request = Request(
            "http://127.0.0.1:11434/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=OLLAMA_TIMEOUT_SECONDS) as response:
            result = json.loads(response.read().decode("utf-8", "ignore"))
        generated = str(result.get("response") or "").strip()
        if generated:
            return generated
    except Exception:
        pass

    try:
        completed = subprocess.run(
            ["ollama", "run", OLLAMA_MODEL],
            input=prompt,
            text=True,
            check=True,
            capture_output=True,
            timeout=OLLAMA_TIMEOUT_SECONDS,
        )
        output = completed.stdout.strip()
        return output or None
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None


def strip_thinking(output: str) -> str:
    if "</think>" in output:
        return output.split("</think>", 1)[1].strip()
    return output.strip()


def parse_json_object(output: str | None) -> dict[str, Any] | None:
    if not output:
        return None
    cleaned = strip_thinking(output)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        parsed = json.loads(cleaned[start : end + 1])
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def localize_news_with_ollama(
    title: str,
    summary: str,
    thesis: str,
) -> dict[str, str] | None:
    prompt = f"""
/no_think
你是一个财经新闻整理助手。请把下面新闻统一转换为简体中文，并给出适合投资周报使用的简洁影响判断。

要求：
1. 只输出 JSON，不要 Markdown，不要解释。
2. title_zh 控制在 40 个汉字以内。
3. summary_zh 控制在 80 个汉字以内。
4. thesis_zh 控制在 80 个汉字以内，说明可能的利好/利空/中性影响。
5. 不要编造原文没有的信息。

原始标题：{title}
原始摘要：{summary}
规则初筛理由：{thesis}

输出格式：
{{"title_zh":"...","summary_zh":"...","thesis_zh":"..."}}
""".strip()
    parsed = parse_json_object(ollama_generate(prompt))
    if parsed is None:
        return None
    result = {
        "title_zh": str(parsed.get("title_zh") or "").strip(),
        "summary_zh": str(parsed.get("summary_zh") or "").strip(),
        "thesis_zh": str(parsed.get("thesis_zh") or "").strip(),
    }
    return result if result["title_zh"] else None


def date_from_unix(value: Any) -> str:
    if isinstance(value, (int, float)) and value > 0:
        return datetime.fromtimestamp(value, timezone.utc).date().isoformat()
    return datetime.now().date().isoformat()


def stable_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def safe_page(value: int | None, default: int = 1) -> int:
    return max(1, value or default)


def safe_page_size(value: int | None, default: int = 10) -> int:
    return max(1, min(100, value or default))


def pagination(page: int, page_size: int, total: int) -> dict[str, int]:
    return {
        "page": page,
        "pageSize": page_size,
        "total": total,
        "totalPages": max(1, (total + page_size - 1) // page_size),
    }


def load_fund_map() -> dict[str, list[dict[str, str]]]:
    if not FUND_MAP_FILE.exists():
        return {}
    parsed = json.loads(FUND_MAP_FILE.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        return {}
    result: dict[str, list[dict[str, str]]] = {}
    for theme, funds in parsed.items():
        if not isinstance(theme, str) or not isinstance(funds, list):
            continue
        clean_funds = []
        for fund in funds:
            if isinstance(fund, dict) and fund.get("symbol") and fund.get("name"):
                clean_funds.append({"symbol": str(fund["symbol"]), "name": str(fund["name"])})
        if clean_funds:
            result[theme] = clean_funds
    return result


def matched_funds_for_name(name: str) -> list[dict[str, str]]:
    fund_map = load_fund_map()
    matched: list[dict[str, str]] = []
    for theme, funds in fund_map.items():
        if theme in name or name in theme:
            matched.extend(funds)
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for fund in matched:
        if fund["symbol"] not in seen:
            seen.add(fund["symbol"])
            unique.append(fund)
    return unique[:5]


def funds_to_text(funds: list[dict[str, str]]) -> str | None:
    if not funds:
        return None
    return json.dumps(funds, ensure_ascii=False)


SCHEMA = """
CREATE TABLE IF NOT EXISTS assets (
  symbol TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  asset_type TEXT NOT NULL,
  region TEXT NOT NULL,
  exchange TEXT,
  currency TEXT,
  sector TEXT,
  industry TEXT,
  is_active INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS asset_daily_bars (
  symbol TEXT NOT NULL,
  trade_date TEXT NOT NULL,
  open REAL NOT NULL,
  high REAL NOT NULL,
  low REAL NOT NULL,
  close REAL NOT NULL,
  previous_close REAL,
  change REAL,
  change_pct REAL,
  volume REAL,
  turnover REAL,
  source TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (symbol, trade_date),
  FOREIGN KEY (symbol) REFERENCES assets(symbol)
);

CREATE TABLE IF NOT EXISTS market_indices (
  symbol TEXT NOT NULL,
  trade_date TEXT NOT NULL,
  name TEXT NOT NULL,
  region TEXT NOT NULL,
  open REAL,
  high REAL,
  low REAL,
  close REAL NOT NULL,
  previous_close REAL,
  change REAL,
  change_pct REAL,
  volume REAL,
  turnover REAL,
  source TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (symbol, trade_date)
);

CREATE TABLE IF NOT EXISTS daily_sector_flows (
  sector_code TEXT NOT NULL,
  sector_name TEXT NOT NULL,
  trade_date TEXT NOT NULL,
  market TEXT NOT NULL,
  change_pct REAL,
  turnover REAL,
  net_inflow REAL,
  main_net_inflow REAL,
  source TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (sector_code, trade_date)
);

CREATE TABLE IF NOT EXISTS daily_sector_leaders (
  sector_code TEXT NOT NULL,
  trade_date TEXT NOT NULL,
  symbol TEXT NOT NULL,
  name TEXT NOT NULL,
  rank_type TEXT NOT NULL,
  rank_value REAL,
  change_pct REAL,
  net_inflow REAL,
  source TEXT NOT NULL,
  PRIMARY KEY (sector_code, trade_date, symbol, rank_type)
);

CREATE TABLE IF NOT EXISTS news_articles (
  id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  title TEXT NOT NULL,
  title_zh TEXT,
  summary TEXT,
  summary_zh TEXT,
  url TEXT NOT NULL UNIQUE,
  published_at TEXT,
  fetched_at TEXT NOT NULL,
  language TEXT,
  raw_payload TEXT
);

CREATE TABLE IF NOT EXISTS news_impacts (
  article_id TEXT PRIMARY KEY,
  sentiment TEXT NOT NULL,
  impact_level TEXT NOT NULL,
  related_sectors TEXT,
  related_symbols TEXT,
  related_funds TEXT,
  thesis TEXT,
  thesis_zh TEXT,
  risk_note TEXT,
  analyzed_at TEXT NOT NULL,
  FOREIGN KEY (article_id) REFERENCES news_articles(id)
);

CREATE TABLE IF NOT EXISTS daily_analysis (
  trade_date TEXT PRIMARY KEY,
  market_summary TEXT NOT NULL,
  sector_summary TEXT NOT NULL,
  capital_flow_summary TEXT NOT NULL,
  news_summary TEXT NOT NULL,
  opportunity_summary TEXT NOT NULL,
  risk_summary TEXT NOT NULL,
  generated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS weekly_reports (
  week_start TEXT NOT NULL,
  week_end TEXT NOT NULL,
  report_title TEXT NOT NULL,
  market_review TEXT NOT NULL,
  sector_rotation TEXT NOT NULL,
  capital_flow_review TEXT NOT NULL,
  news_theme_review TEXT NOT NULL,
  opportunity_watchlist TEXT NOT NULL,
  risk_watchlist TEXT NOT NULL,
  historical_context TEXT,
  next_week_focus TEXT,
  generated_at TEXT NOT NULL,
  PRIMARY KEY (week_start, week_end)
);

CREATE TABLE IF NOT EXISTS market_regime_daily (
  trade_date TEXT PRIMARY KEY,
  regime TEXT NOT NULL,
  risk_appetite_score REAL NOT NULL,
  trend_score REAL NOT NULL,
  liquidity_score REAL NOT NULL,
  breadth_score REAL NOT NULL,
  notes TEXT,
  generated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sector_cycle_daily (
  sector_code TEXT NOT NULL,
  trade_date TEXT NOT NULL,
  cycle_stage TEXT NOT NULL,
  trend_score REAL NOT NULL,
  capital_flow_score REAL NOT NULL,
  momentum_score REAL NOT NULL,
  crowding_score REAL NOT NULL,
  news_heat_score REAL NOT NULL,
  generated_at TEXT NOT NULL,
  PRIMARY KEY (sector_code, trade_date)
);

CREATE TABLE IF NOT EXISTS investment_opportunity_daily (
  target_type TEXT NOT NULL,
  target_code TEXT NOT NULL,
  target_name TEXT NOT NULL,
  trade_date TEXT NOT NULL,
  opportunity_score REAL NOT NULL,
  trend_score REAL NOT NULL,
  capital_score REAL NOT NULL,
  news_score REAL NOT NULL,
  risk_score REAL NOT NULL,
  thesis TEXT NOT NULL,
  risk_note TEXT,
  generated_at TEXT NOT NULL,
  PRIMARY KEY (target_type, target_code, trade_date)
);

CREATE TABLE IF NOT EXISTS early_opportunities (
  target_type TEXT NOT NULL,
  target_code TEXT NOT NULL,
  target_name TEXT NOT NULL,
  trade_date TEXT NOT NULL,
  early_score REAL NOT NULL,
  flow_persistence_score REAL NOT NULL,
  rank_improvement_score REAL NOT NULL,
  heat_score REAL NOT NULL,
  crowding_risk_score REAL NOT NULL,
  matched_funds TEXT,
  thesis TEXT NOT NULL,
  action_hint TEXT NOT NULL,
  generated_at TEXT NOT NULL,
  PRIMARY KEY (target_type, target_code, trade_date)
);

CREATE TABLE IF NOT EXISTS opportunity_tracking (
  id TEXT PRIMARY KEY,
  target_type TEXT NOT NULL,
  target_code TEXT NOT NULL,
  target_name TEXT NOT NULL,
  source_report_date TEXT NOT NULL,
  entry_date TEXT NOT NULL,
  entry_score REAL NOT NULL,
  entry_price REAL,
  latest_date TEXT,
  latest_price REAL,
  return_pct REAL,
  status TEXT NOT NULL,
  thesis TEXT NOT NULL,
  matched_funds TEXT,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS historical_pattern_matches (
  trade_date TEXT NOT NULL,
  matched_start_date TEXT NOT NULL,
  matched_end_date TEXT NOT NULL,
  similarity_score REAL NOT NULL,
  pattern_summary TEXT NOT NULL,
  forward_20d_return REAL,
  forward_60d_return REAL,
  max_drawdown_60d REAL,
  generated_at TEXT NOT NULL,
  PRIMARY KEY (trade_date, matched_start_date)
);

CREATE TABLE IF NOT EXISTS cycle_reports (
  period_start TEXT NOT NULL,
  period_end TEXT NOT NULL,
  lookback_days INTEGER NOT NULL,
  cycle_stage TEXT NOT NULL,
  market_summary TEXT NOT NULL,
  regime_summary TEXT NOT NULL,
  index_summary TEXT NOT NULL,
  sector_summary TEXT NOT NULL,
  opportunity_summary TEXT NOT NULL,
  risk_summary TEXT NOT NULL,
  generated_at TEXT NOT NULL,
  PRIMARY KEY (period_start, period_end)
);

CREATE TABLE IF NOT EXISTS source_runs (
  id TEXT PRIMARY KEY,
  run_type TEXT NOT NULL,
  target_date TEXT,
  start_date TEXT,
  end_date TEXT,
  status TEXT NOT NULL,
  source TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  error_message TEXT
);

CREATE TABLE IF NOT EXISTS data_coverage (
  dataset TEXT NOT NULL,
  target_date TEXT NOT NULL,
  status TEXT NOT NULL,
  source TEXT,
  checked_at TEXT NOT NULL,
  notes TEXT,
  PRIMARY KEY (dataset, target_date)
);

CREATE INDEX IF NOT EXISTS idx_asset_daily_bars_date
ON asset_daily_bars (trade_date);

CREATE INDEX IF NOT EXISTS idx_asset_daily_bars_symbol_date
ON asset_daily_bars (symbol, trade_date DESC);

CREATE INDEX IF NOT EXISTS idx_market_indices_symbol_date
ON market_indices (symbol, trade_date DESC);

CREATE INDEX IF NOT EXISTS idx_market_indices_date
ON market_indices (trade_date DESC);

CREATE INDEX IF NOT EXISTS idx_daily_sector_flows_date_inflow
ON daily_sector_flows (trade_date, net_inflow DESC);

CREATE INDEX IF NOT EXISTS idx_news_published_at
ON news_articles (published_at DESC);

CREATE INDEX IF NOT EXISTS idx_news_source_time
ON news_articles (source, published_at DESC);

CREATE INDEX IF NOT EXISTS idx_opportunity_date_score
ON investment_opportunity_daily (trade_date, opportunity_score DESC);

CREATE INDEX IF NOT EXISTS idx_early_opportunities_date_score
ON early_opportunities (trade_date, early_score DESC);

CREATE INDEX IF NOT EXISTS idx_opportunity_tracking_report
ON opportunity_tracking (source_report_date DESC, entry_score DESC);

CREATE INDEX IF NOT EXISTS idx_cycle_reports_end
ON cycle_reports (period_end DESC);
"""


def init_db(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)
    ensure_column(connection, "news_articles", "title_zh", "TEXT")
    ensure_column(connection, "news_articles", "summary_zh", "TEXT")
    ensure_column(connection, "news_impacts", "thesis_zh", "TEXT")
    try:
        connection.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS news_articles_fts "
            "USING fts5(title, summary)"
        )
    except sqlite3.OperationalError:
        pass
    connection.commit()


def ensure_column(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
    column_definition: str,
) -> None:
    columns = {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if column_name not in columns:
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return None if row is None else dict(row)


def record_run(
    connection: sqlite3.Connection,
    run_type: str,
    source: str,
    status: str,
    *,
    target_date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    started_at: str | None = None,
    error_message: str | None = None,
) -> None:
    timestamp = now_iso()
    connection.execute(
        """
        INSERT INTO source_runs (
          id, run_type, target_date, start_date, end_date, status, source,
          started_at, finished_at, error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            run_type,
            target_date,
            start_date,
            end_date,
            status,
            source,
            started_at or timestamp,
            timestamp,
            error_message,
        ),
    )


def update_coverage(
    connection: sqlite3.Connection,
    dataset: str,
    target_date: str,
    status: str,
    source: str,
    notes: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO data_coverage (dataset, target_date, status, source, checked_at, notes)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(dataset, target_date) DO UPDATE SET
          status = excluded.status,
          source = excluded.source,
          checked_at = excluded.checked_at,
          notes = excluded.notes
        """,
        (dataset, target_date, status, source, now_iso(), notes),
    )


def classify_news(title: str, summary: str) -> dict[str, Any]:
    text = f"{title} {summary}".lower()
    positive_hits = [keyword for keyword in POSITIVE_KEYWORDS if keyword.lower() in text]
    negative_hits = [keyword for keyword in NEGATIVE_KEYWORDS if keyword.lower() in text]
    score = len(positive_hits) - len(negative_hits)
    sentiment = "positive" if score > 0 else "negative" if score < 0 else "neutral"
    impact_level = "high" if abs(score) >= 2 else "medium" if abs(score) == 1 else "low"
    related_sectors = [
        sector
        for sector, keywords in SECTOR_KEYWORDS.items()
        if any(keyword.lower() in text for keyword in keywords)
    ]
    reason_parts = []
    if positive_hits:
        reason_parts.append(f"positive keywords: {', '.join(positive_hits[:3])}")
    if negative_hits:
        reason_parts.append(f"negative keywords: {', '.join(negative_hits[:3])}")
    return {
        "sentiment": sentiment,
        "impact_level": impact_level,
        "related_sectors": ",".join(related_sectors) if related_sectors else None,
        "score": float(score),
        "thesis": "; ".join(reason_parts) or "No strong directional keyword was detected.",
    }


def parse_rss_datetime(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        return None


def enrich_news_with_ollama(connection: sqlite3.Connection, limit: int = 12) -> int:
    init_db(connection)
    if not ollama_available():
        return 0
    rows = connection.execute(
        """
        SELECT n.id, n.title, n.summary, i.thesis
        FROM news_articles n
        JOIN news_impacts i ON i.article_id = n.id
        WHERE n.title_zh IS NULL OR n.title_zh = '' OR i.thesis_zh IS NULL OR i.thesis_zh = ''
        ORDER BY coalesce(n.published_at, n.fetched_at) DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    enriched = 0
    for row in rows:
        localized = localize_news_with_ollama(
            row["title"],
            row["summary"] or "",
            row["thesis"] or "",
        )
        if localized is None:
            continue
        connection.execute(
            """
            UPDATE news_articles
            SET title_zh = ?, summary_zh = ?
            WHERE id = ?
            """,
            (localized["title_zh"], localized["summary_zh"], row["id"]),
        )
        connection.execute(
            """
            UPDATE news_impacts
            SET thesis_zh = ?
            WHERE article_id = ?
            """,
            (localized["thesis_zh"], row["id"]),
        )
        enriched += 1
    if enriched:
        update_coverage(
            connection,
            "news_zh",
            datetime.now().date().isoformat(),
            "complete",
            f"ollama:{OLLAMA_MODEL}",
        )
    connection.commit()
    return enriched


def collect_news(connection: sqlite3.Connection, target_date: str | None = None) -> int:
    init_db(connection)
    started_at = now_iso()
    fetched_count = 0
    target_date = target_date or datetime.now().date().isoformat()
    errors: list[str] = []

    for source_name, url, language in NEWS_RSS_SOURCES:
        try:
            root = ET.fromstring(fetch_text(url))
            for item in root.findall(".//item"):
                title = html.unescape((item.findtext("title") or "").strip())
                link = (item.findtext("link") or "").strip()
                summary = html.unescape((item.findtext("description") or "").strip())
                if not title or not link:
                    continue
                published_at = parse_rss_datetime(item.findtext("pubDate"))
                article_id = stable_id(link)
                raw_payload = ET.tostring(item, encoding="unicode")
                connection.execute(
                    """
                    INSERT INTO news_articles (
                      id, source, title, summary, url, published_at, fetched_at, language, raw_payload
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(url) DO UPDATE SET
                      title = excluded.title,
                      summary = excluded.summary,
                      published_at = excluded.published_at,
                      fetched_at = excluded.fetched_at,
                      language = excluded.language,
                      raw_payload = excluded.raw_payload
                    """,
                    (
                        article_id,
                        source_name,
                        title,
                        summary,
                        link,
                        published_at,
                        now_iso(),
                        language,
                        raw_payload,
                    ),
                )
                impact = classify_news(title, summary)
                connection.execute(
                    """
                    INSERT INTO news_impacts (
                      article_id, sentiment, impact_level, related_sectors,
                      related_symbols, related_funds, thesis, risk_note, analyzed_at
                    ) VALUES (?, ?, ?, ?, NULL, NULL, ?, ?, ?)
                    ON CONFLICT(article_id) DO UPDATE SET
                      sentiment = excluded.sentiment,
                      impact_level = excluded.impact_level,
                      related_sectors = excluded.related_sectors,
                      thesis = excluded.thesis,
                      risk_note = excluded.risk_note,
                      analyzed_at = excluded.analyzed_at
                    """,
                    (
                        article_id,
                        impact["sentiment"],
                        impact["impact_level"],
                        impact["related_sectors"],
                        impact["thesis"],
                        "Keyword-based sentiment is an early signal and should be reviewed manually.",
                        now_iso(),
                    ),
                )
                fetched_count += 1
        except Exception as error:
            errors.append(f"{source_name}: {error}")

    update_coverage(
        connection,
        "news",
        target_date,
        "complete" if fetched_count else "failed",
        "rss",
        None if not errors else "; ".join(errors),
    )
    enriched_count = enrich_news_with_ollama(connection, limit=10) if fetched_count else 0
    record_run(
        connection,
        "news",
        f"rss+ollama:{OLLAMA_MODEL}" if enriched_count else "rss",
        "success" if fetched_count else "failed",
        target_date=target_date,
        started_at=started_at,
        error_message=None if fetched_count else "; ".join(errors),
    )
    connection.commit()
    return fetched_count


def collect_sector_leaders(
    connection: sqlite3.Connection,
    sector_code: str,
    trade_date: str,
    source: str,
    limit: int = 5,
) -> int:
    try:
        payload = fetch_json(EASTMONEY_LEADER_URL.format(sector_code=quote(sector_code), limit=limit))
        rows = payload.get("data", {}).get("diff", []) or []
    except Exception:
        return 0

    inserted = 0
    for row in rows:
        symbol = str(row.get("f12") or "")
        name = str(row.get("f14") or symbol)
        if not symbol:
            continue
        connection.execute(
            """
            INSERT INTO daily_sector_leaders (
              sector_code, trade_date, symbol, name, rank_type, rank_value,
              change_pct, net_inflow, source
            ) VALUES (?, ?, ?, ?, 'main_net_inflow', ?, ?, ?, ?)
            ON CONFLICT(sector_code, trade_date, symbol, rank_type) DO UPDATE SET
              name = excluded.name,
              rank_value = excluded.rank_value,
              change_pct = excluded.change_pct,
              net_inflow = excluded.net_inflow,
              source = excluded.source
            """,
            (
                sector_code,
                trade_date,
                symbol,
                name,
                row.get("f62"),
                row.get("f3"),
                row.get("f62"),
                source,
            ),
        )
        inserted += 1
    return inserted


def fetch_yahoo_daily_proxy(symbol: str) -> dict[str, Any] | None:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol)}?range=5d&interval=1d"
    payload = fetch_json(url)
    result = (payload.get("chart", {}).get("result") or [None])[0]
    if not result:
        return None
    timestamps = result.get("timestamp") or []
    quote_data = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    closes = quote_data.get("close") or []
    opens = quote_data.get("open") or []
    highs = quote_data.get("high") or []
    lows = quote_data.get("low") or []
    volumes = quote_data.get("volume") or []
    valid_indexes = [
        index
        for index, close in enumerate(closes)
        if close is not None and index < len(timestamps)
    ]
    if len(valid_indexes) < 2:
        return None
    current_index = valid_indexes[-1]
    previous_index = valid_indexes[-2]
    close = float(closes[current_index])
    previous_close = float(closes[previous_index])
    volume = float(volumes[current_index] or 0)
    change_pct = 0 if previous_close == 0 else (close - previous_close) / previous_close * 100
    return {
        "trade_date": datetime.fromtimestamp(timestamps[current_index], timezone.utc).date().isoformat(),
        "open": opens[current_index],
        "high": highs[current_index],
        "low": lows[current_index],
        "close": close,
        "previous_close": previous_close,
        "change_pct": change_pct,
        "volume": volume,
        "turnover": close * volume,
        "estimated_flow": (close - previous_close) * volume,
    }


def unix_timestamp(date_value: str) -> int:
    return int(datetime.fromisoformat(date_value).replace(tzinfo=timezone.utc).timestamp())


def fetch_yahoo_history(
    symbol: str,
    range_value: str = "1y",
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict[str, Any]]:
    if start_date and end_date:
        period1 = unix_timestamp(start_date)
        period2 = unix_timestamp((datetime.fromisoformat(end_date).date() + timedelta(days=1)).isoformat())
        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol)}"
            f"?period1={period1}&period2={period2}&interval=1d"
        )
    else:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol)}?range={range_value}&interval=1d"
    payload = fetch_json(url)
    result = (payload.get("chart", {}).get("result") or [None])[0]
    if not result:
        return []
    timestamps = result.get("timestamp") or []
    quote_data = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    opens = quote_data.get("open") or []
    highs = quote_data.get("high") or []
    lows = quote_data.get("low") or []
    closes = quote_data.get("close") or []
    volumes = quote_data.get("volume") or []
    history: list[dict[str, Any]] = []
    previous_close: float | None = None
    for index, timestamp in enumerate(timestamps):
        if index >= len(closes) or closes[index] is None:
            continue
        close = float(closes[index])
        change = None if previous_close is None else close - previous_close
        change_pct = None if previous_close in (None, 0) else change / previous_close * 100
        volume = float(volumes[index] or 0) if index < len(volumes) else 0
        history.append(
            {
                "trade_date": datetime.fromtimestamp(timestamp, timezone.utc).date().isoformat(),
                "open": opens[index] if index < len(opens) else None,
                "high": highs[index] if index < len(highs) else None,
                "low": lows[index] if index < len(lows) else None,
                "close": close,
                "previous_close": previous_close,
                "change": change,
                "change_pct": change_pct,
                "volume": volume,
                "turnover": close * volume,
            }
        )
        previous_close = close
    return history


def average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def moving_average(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return average(values[-window:])


def classify_market_regime(connection: sqlite3.Connection, trade_date: str) -> None:
    rows = connection.execute(
        """
        SELECT symbol, name, region, close, change_pct
        FROM market_indices
        WHERE trade_date = ?
        """,
        (trade_date,),
    ).fetchall()
    if not rows:
        return

    trend_scores: list[float] = []
    risk_inputs: list[float] = []
    liquidity_inputs: list[float] = []
    positive_count = 0
    for row in rows:
        closes = [
            float(item["close"])
            for item in connection.execute(
                """
                SELECT close FROM market_indices
                WHERE symbol = ? AND trade_date <= ?
                ORDER BY trade_date ASC
                """,
                (row["symbol"], trade_date),
            ).fetchall()
        ]
        close = float(row["close"])
        ma20 = moving_average(closes, 20)
        ma60 = moving_average(closes, 60)
        score = 50.0
        if ma20 is not None:
            score += 20 if close >= ma20 else -20
        if ma60 is not None:
            score += 20 if close >= ma60 else -20
        trend_scores.append(max(0.0, min(100.0, score)))
        change_pct = float(row["change_pct"] or 0)
        if row["symbol"] == "^VIX":
            risk_inputs.append(max(0.0, min(100.0, 50 - change_pct * 2)))
        else:
            risk_inputs.append(max(0.0, min(100.0, 50 + change_pct * 5)))
            if change_pct > 0:
                positive_count += 1
        volume_row = connection.execute(
            """
            SELECT avg(volume) AS avg_volume
            FROM (
              SELECT volume FROM market_indices
              WHERE symbol = ? AND trade_date <= ? AND volume IS NOT NULL
              ORDER BY trade_date DESC LIMIT 20
            )
            """,
            (row["symbol"], trade_date),
        ).fetchone()
        if volume_row and volume_row["avg_volume"]:
            liquidity_inputs.append(50.0)

    breadth_score = positive_count / max(1, len([row for row in rows if row["symbol"] != "^VIX"])) * 100
    trend_score = round(average(trend_scores), 2)
    risk_appetite_score = round(average(risk_inputs), 2)
    liquidity_score = round(average(liquidity_inputs) if liquidity_inputs else 50.0, 2)
    if trend_score >= 68 and risk_appetite_score >= 55:
        regime = "risk_on"
    elif trend_score <= 38 or risk_appetite_score <= 40:
        regime = "risk_off"
    elif trend_score >= 55:
        regime = "recovery"
    else:
        regime = "range"
    notes = (
        f"Trend {trend_score}, risk appetite {risk_appetite_score}, "
        f"breadth {breadth_score:.2f}. Regime inferred from major CN/US/HK indices."
    )
    connection.execute(
        """
        INSERT INTO market_regime_daily (
          trade_date, regime, risk_appetite_score, trend_score,
          liquidity_score, breadth_score, notes, generated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(trade_date) DO UPDATE SET
          regime = excluded.regime,
          risk_appetite_score = excluded.risk_appetite_score,
          trend_score = excluded.trend_score,
          liquidity_score = excluded.liquidity_score,
          breadth_score = excluded.breadth_score,
          notes = excluded.notes,
          generated_at = excluded.generated_at
        """,
        (
            trade_date,
            regime,
            risk_appetite_score,
            trend_score,
            liquidity_score,
            round(breadth_score, 2),
            notes,
            now_iso(),
        ),
    )


def collect_market_indices(
    connection: sqlite3.Connection,
    start_date: str | None = None,
    end_date: str | None = None,
) -> int:
    init_db(connection)
    started_at = now_iso()
    inserted = 0
    dates: set[str] = set()
    errors: list[str] = []
    for symbol, name, region in MARKET_INDICES:
        try:
            for point in fetch_yahoo_history(symbol, start_date=start_date, end_date=end_date):
                connection.execute(
                    """
                    INSERT INTO market_indices (
                      symbol, trade_date, name, region, open, high, low, close,
                      previous_close, change, change_pct, volume, turnover, source, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'yahoo-index', ?)
                    ON CONFLICT(symbol, trade_date) DO UPDATE SET
                      name = excluded.name,
                      region = excluded.region,
                      open = excluded.open,
                      high = excluded.high,
                      low = excluded.low,
                      close = excluded.close,
                      previous_close = excluded.previous_close,
                      change = excluded.change,
                      change_pct = excluded.change_pct,
                      volume = excluded.volume,
                      turnover = excluded.turnover,
                      source = excluded.source,
                      created_at = excluded.created_at
                    """,
                    (
                        symbol,
                        point["trade_date"],
                        name,
                        region,
                        point["open"],
                        point["high"],
                        point["low"],
                        point["close"],
                        point["previous_close"],
                        point["change"],
                        point["change_pct"],
                        point["volume"],
                        point["turnover"],
                        now_iso(),
                    ),
                )
                dates.add(point["trade_date"])
                inserted += 1
        except Exception as error:
            errors.append(f"{symbol}: {error}")

    for trade_date in sorted(dates):
        classify_market_regime(connection, trade_date)

    target_date = max(dates) if dates else datetime.now().date().isoformat()
    update_coverage(
        connection,
        "market_indices",
        target_date,
        "complete" if inserted else "failed",
        "yahoo",
        None if not errors else "; ".join(errors),
    )
    update_coverage(
        connection,
        "market_regime",
        target_date,
        "complete" if inserted else "failed",
        "stockflow.py",
        None if inserted else "No index data was collected.",
    )
    if inserted:
        update_daily_analysis_from_database(connection, target_date)
        today = datetime.now().date().isoformat()
        if today != target_date:
            update_daily_analysis_from_database(connection, today)
    record_run(
        connection,
        "market_indices",
        "yahoo",
        "success" if inserted else "failed",
        target_date=target_date,
        started_at=started_at,
        error_message=None if inserted else "; ".join(errors),
    )
    connection.commit()
    return inserted


def analyze_early_opportunities(connection: sqlite3.Connection, as_of_date: str | None = None) -> int:
    init_db(connection)
    latest_row = connection.execute(
        "SELECT max(trade_date) AS trade_date FROM daily_sector_flows WHERE trade_date <= coalesce(?, trade_date)",
        (as_of_date,),
    ).fetchone()
    trade_date = latest_row["trade_date"] if latest_row and latest_row["trade_date"] else None
    if trade_date is None:
        return 0

    sectors = connection.execute(
        """
        SELECT DISTINCT sector_code, sector_name, market
        FROM daily_sector_flows
        WHERE trade_date <= ?
        """,
        (trade_date,),
    ).fetchall()
    inserted = 0
    for sector in sectors:
        rows = connection.execute(
            """
            SELECT trade_date, change_pct, net_inflow, main_net_inflow
            FROM daily_sector_flows
            WHERE sector_code = ? AND trade_date <= ?
            ORDER BY trade_date DESC
            LIMIT 10
            """,
            (sector["sector_code"], trade_date),
        ).fetchall()
        if not rows:
            continue
        flows = [float(row["net_inflow"] or 0) for row in rows]
        changes = [float(row["change_pct"] or 0) for row in rows]
        inflow_days = sum(1 for flow in flows[:5] if flow > 0)
        flow_total = sum(flows[:5])
        latest_change = changes[0]
        five_day_change = sum(changes[:5])
        flow_persistence_score = min(100.0, inflow_days * 16 + max(0.0, flow_total / 100000000) * 3)
        rank_rows = connection.execute(
            """
            SELECT trade_date, sector_code,
                   rank() OVER (PARTITION BY trade_date ORDER BY net_inflow DESC) AS flow_rank
            FROM daily_sector_flows
            WHERE trade_date IN (
              SELECT DISTINCT trade_date FROM daily_sector_flows
              WHERE trade_date <= ?
              ORDER BY trade_date DESC LIMIT 5
            )
            """,
            (trade_date,),
        ).fetchall()
        sector_ranks = [int(row["flow_rank"]) for row in rank_rows if row["sector_code"] == sector["sector_code"]]
        rank_improvement_score = 50.0
        if len(sector_ranks) >= 2:
            rank_improvement_score = max(0.0, min(100.0, 50 + (sector_ranks[-1] - sector_ranks[0]) * 2))
        news_heat = connection.execute(
            """
            SELECT count(*) AS count
            FROM news_articles n
            JOIN news_impacts i ON i.article_id = n.id
            WHERE date(coalesce(n.published_at, n.fetched_at)) <= ?
              AND (
                coalesce(i.related_sectors, '') LIKE ?
                OR n.title LIKE ?
                OR coalesce(n.title_zh, '') LIKE ?
              )
            """,
            (
                trade_date,
                f"%{sector['sector_name']}%",
                f"%{sector['sector_name']}%",
                f"%{sector['sector_name']}%",
            ),
        ).fetchone()["count"]
        heat_score = min(100.0, 35 + float(news_heat) * 12)
        crowding_risk_score = min(100.0, max(0.0, abs(five_day_change) * 8 + (20 if latest_change > 5 else 0)))
        early_score = max(
            0.0,
            min(
                100.0,
                flow_persistence_score * 0.42
                + rank_improvement_score * 0.23
                + heat_score * 0.2
                + max(0.0, 70 - crowding_risk_score) * 0.15,
            ),
        )
        if early_score < 45:
            continue
        funds = matched_funds_for_name(sector["sector_name"])
        action_hint = (
            "加入观察，等待回踩或连续性确认"
            if crowding_risk_score < 55
            else "热度偏高，优先等待分歧或缩量企稳"
        )
        thesis = (
            f"{sector['sector_name']}近5条记录中{inflow_days}次净流入，"
            f"累计净流入{flow_total / 100000000:.2f}亿，"
            f"近5条涨跌合计{five_day_change:+.2f}%，新闻热度{news_heat}。"
        )
        connection.execute(
            """
            INSERT INTO early_opportunities (
              target_type, target_code, target_name, trade_date, early_score,
              flow_persistence_score, rank_improvement_score, heat_score,
              crowding_risk_score, matched_funds, thesis, action_hint, generated_at
            ) VALUES ('sector', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(target_type, target_code, trade_date) DO UPDATE SET
              target_name = excluded.target_name,
              early_score = excluded.early_score,
              flow_persistence_score = excluded.flow_persistence_score,
              rank_improvement_score = excluded.rank_improvement_score,
              heat_score = excluded.heat_score,
              crowding_risk_score = excluded.crowding_risk_score,
              matched_funds = excluded.matched_funds,
              thesis = excluded.thesis,
              action_hint = excluded.action_hint,
              generated_at = excluded.generated_at
            """,
            (
                sector["sector_code"],
                sector["sector_name"],
                trade_date,
                round(early_score, 2),
                round(flow_persistence_score, 2),
                round(rank_improvement_score, 2),
                round(heat_score, 2),
                round(crowding_risk_score, 2),
                funds_to_text(funds),
                thesis,
                action_hint,
                now_iso(),
            ),
        )
        inserted += 1
    update_coverage(connection, "early_opportunities", trade_date, "complete" if inserted else "missing", "stockflow.py")
    record_run(connection, "early_opportunities", "stockflow.py", "success" if inserted else "partial", target_date=trade_date)
    connection.commit()
    return inserted


def track_weekly_opportunities(connection: sqlite3.Connection) -> int:
    init_db(connection)
    report = connection.execute(
        "SELECT week_start, week_end FROM weekly_reports ORDER BY week_end DESC LIMIT 1"
    ).fetchone()
    if not report:
        return 0
    week_end = report["week_end"]
    rows = connection.execute(
        """
        SELECT * FROM early_opportunities
        WHERE trade_date <= ?
        ORDER BY trade_date DESC, early_score DESC
        LIMIT 10
        """,
        (week_end,),
    ).fetchall()
    tracked = 0
    for row in rows:
        latest = connection.execute(
            """
            SELECT trade_date, close AS price
            FROM market_indices
            WHERE symbol = ? AND trade_date >= ?
            ORDER BY trade_date DESC LIMIT 1
            """,
            (row["target_code"], row["trade_date"]),
        ).fetchone()
        if latest is None:
            latest_flow = connection.execute(
                """
                SELECT trade_date, change_pct
                FROM daily_sector_flows
                WHERE sector_code = ? AND trade_date >= ?
                ORDER BY trade_date DESC LIMIT 1
                """,
                (row["target_code"], row["trade_date"]),
            ).fetchone()
            latest_date = latest_flow["trade_date"] if latest_flow else row["trade_date"]
            return_pct = float(latest_flow["change_pct"] or 0) if latest_flow else None
            latest_price = None
            entry_price = None
        else:
            latest_date = latest["trade_date"]
            latest_price = float(latest["price"])
            entry_price = latest_price
            return_pct = 0.0
        status = "有效跟踪" if return_pct is not None and return_pct >= 0 else "需复核"
        tracking_id = stable_id(f"{week_end}:{row['target_type']}:{row['target_code']}")
        connection.execute(
            """
            INSERT INTO opportunity_tracking (
              id, target_type, target_code, target_name, source_report_date,
              entry_date, entry_score, entry_price, latest_date, latest_price,
              return_pct, status, thesis, matched_funds, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              latest_date = excluded.latest_date,
              latest_price = excluded.latest_price,
              return_pct = excluded.return_pct,
              status = excluded.status,
              thesis = excluded.thesis,
              matched_funds = excluded.matched_funds,
              updated_at = excluded.updated_at
            """,
            (
                tracking_id,
                row["target_type"],
                row["target_code"],
                row["target_name"],
                week_end,
                row["trade_date"],
                row["early_score"],
                entry_price,
                latest_date,
                latest_price,
                return_pct,
                status,
                row["thesis"],
                row["matched_funds"],
                now_iso(),
            ),
        )
        tracked += 1
    update_coverage(connection, "opportunity_tracking", week_end, "complete" if tracked else "missing", "stockflow.py")
    record_run(connection, "opportunity_tracking", "stockflow.py", "success" if tracked else "partial", target_date=week_end)
    connection.commit()
    return tracked


def analyze_market_cycles(
    connection: sqlite3.Connection,
    lookback_days: int = 183,
    end_date: str | None = None,
) -> dict[str, Any]:
    init_db(connection)
    latest_row = connection.execute(
        "SELECT max(trade_date) AS trade_date FROM market_indices WHERE trade_date <= coalesce(?, trade_date)",
        (end_date,),
    ).fetchone()
    if latest_row is None or latest_row["trade_date"] is None:
        raise RuntimeError("没有可用于历史周期分析的市场指数数据，请先执行 collect-indices。")
    period_end = latest_row["trade_date"]
    period_start = (
        datetime.fromisoformat(period_end).date() - timedelta(days=lookback_days)
    ).isoformat()

    regimes = connection.execute(
        """
        SELECT regime, count(*) AS days, avg(trend_score) AS avg_trend,
               avg(risk_appetite_score) AS avg_risk, avg(breadth_score) AS avg_breadth
        FROM market_regime_daily
        WHERE trade_date BETWEEN ? AND ?
        GROUP BY regime
        ORDER BY days DESC
        """,
        (period_start, period_end),
    ).fetchall()
    latest_regime = row_to_dict(
        connection.execute(
            """
            SELECT * FROM market_regime_daily
            WHERE trade_date BETWEEN ? AND ?
            ORDER BY trade_date DESC LIMIT 1
            """,
            (period_start, period_end),
        ).fetchone()
    )
    index_returns = connection.execute(
        """
        WITH ranked AS (
          SELECT symbol, min(trade_date) AS first_date, max(trade_date) AS last_date
          FROM market_indices
          WHERE trade_date BETWEEN ? AND ?
          GROUP BY symbol
        )
        SELECT first_index.name, first_index.region, ranked.symbol,
               first_index.close AS first_close, last_index.close AS last_close,
               CASE WHEN first_index.close = 0 THEN 0
                    ELSE (last_index.close - first_index.close) / first_index.close * 100
               END AS return_pct
        FROM ranked
        JOIN market_indices first_index
          ON first_index.symbol = ranked.symbol AND first_index.trade_date = ranked.first_date
        JOIN market_indices last_index
          ON last_index.symbol = ranked.symbol AND last_index.trade_date = ranked.last_date
        ORDER BY return_pct DESC
        """,
        (period_start, period_end),
    ).fetchall()
    sector_flows = connection.execute(
        """
        SELECT sector_name, market, sum(net_inflow) AS total_net_inflow,
               avg(change_pct) AS avg_change_pct, count(*) AS samples
        FROM daily_sector_flows
        WHERE trade_date BETWEEN ? AND ?
        GROUP BY sector_code, sector_name, market
        HAVING samples > 0
        ORDER BY total_net_inflow DESC
        LIMIT 8
        """,
        (period_start, period_end),
    ).fetchall()
    weak_sectors = connection.execute(
        """
        SELECT sector_name, sum(net_inflow) AS total_net_inflow
        FROM daily_sector_flows
        WHERE trade_date BETWEEN ? AND ?
        GROUP BY sector_code, sector_name
        ORDER BY total_net_inflow ASC
        LIMIT 5
        """,
        (period_start, period_end),
    ).fetchall()
    early_rows = connection.execute(
        """
        SELECT target_name, early_score, action_hint
        FROM early_opportunities
        WHERE trade_date BETWEEN ? AND ?
        ORDER BY early_score DESC
        LIMIT 6
        """,
        (period_start, period_end),
    ).fetchall()

    dominant_regime = regimes[0]["regime"] if regimes else "unknown"
    avg_trend = average([float(row["avg_trend"] or 0) for row in regimes])
    avg_risk = average([float(row["avg_risk"] or 0) for row in regimes])
    if latest_regime and latest_regime["regime"] == "risk_on":
        cycle_stage = "风险偏好扩张期"
    elif latest_regime and latest_regime["regime"] == "recovery":
        cycle_stage = "修复上行期"
    elif latest_regime and latest_regime["regime"] == "risk_off":
        cycle_stage = "防御收缩期"
    else:
        cycle_stage = "震荡轮动期"

    strongest_index = index_returns[0] if index_returns else None
    weakest_index = index_returns[-1] if index_returns else None
    market_summary = (
        f"过去{lookback_days}天主导状态为{dominant_regime}，当前处于{cycle_stage}。"
        f"平均趋势分{avg_trend:.1f}，平均风险偏好{avg_risk:.1f}。"
    )
    regime_summary = (
        "；".join(
            f"{row['regime']} {row['days']}天(趋势{float(row['avg_trend'] or 0):.1f}/风险{float(row['avg_risk'] or 0):.1f})"
            for row in regimes
        )
        if regimes
        else "暂无市场状态样本。"
    )
    index_summary = (
        f"最强指数：{strongest_index['name']} {float(strongest_index['return_pct'] or 0):+.2f}%；"
        f"最弱指数：{weakest_index['name']} {float(weakest_index['return_pct'] or 0):+.2f}%。"
        if strongest_index and weakest_index
        else "暂无指数区间表现。"
    )
    sector_summary = (
        "资金主线：" + "；".join(
            f"{row['sector_name']}({float(row['total_net_inflow'] or 0) / 100000000:.2f}亿)"
            for row in sector_flows
        )
        if sector_flows
        else "暂无板块资金流样本。"
    )
    opportunity_summary = (
        "早期机会：" + "；".join(
            f"{row['target_name']}({float(row['early_score'] or 0):.1f})"
            for row in early_rows
        )
        if early_rows
        else "暂无早期机会样本。"
    )
    risk_summary = (
        "需回避/复核的流出方向：" + "，".join(row["sector_name"] for row in weak_sectors)
        if weak_sectors
        else "主要风险来自市场状态切换、拥挤度上升或外部利空。"
    )

    connection.execute(
        """
        INSERT INTO cycle_reports (
          period_start, period_end, lookback_days, cycle_stage, market_summary,
          regime_summary, index_summary, sector_summary, opportunity_summary,
          risk_summary, generated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(period_start, period_end) DO UPDATE SET
          lookback_days = excluded.lookback_days,
          cycle_stage = excluded.cycle_stage,
          market_summary = excluded.market_summary,
          regime_summary = excluded.regime_summary,
          index_summary = excluded.index_summary,
          sector_summary = excluded.sector_summary,
          opportunity_summary = excluded.opportunity_summary,
          risk_summary = excluded.risk_summary,
          generated_at = excluded.generated_at
        """,
        (
            period_start,
            period_end,
            lookback_days,
            cycle_stage,
            market_summary,
            regime_summary,
            index_summary,
            sector_summary,
            opportunity_summary,
            risk_summary,
            now_iso(),
        ),
    )
    update_coverage(connection, "cycle_report", period_end, "complete", "stockflow.py")
    record_run(
        connection,
        "cycle_report",
        "stockflow.py",
        "success",
        target_date=period_end,
        start_date=period_start,
        end_date=period_end,
    )
    connection.commit()
    return {"periodStart": period_start, "periodEnd": period_end, "cycleStage": cycle_stage}


def collect_global_sector_proxies(connection: sqlite3.Connection) -> int:
    inserted = 0
    for symbol, name, market in GLOBAL_SECTOR_PROXIES:
        try:
            point = fetch_yahoo_daily_proxy(symbol)
            if point is None:
                continue
            net_inflow = point["estimated_flow"]
            connection.execute(
                """
                INSERT INTO daily_sector_flows (
                  sector_code, sector_name, trade_date, market, change_pct,
                  turnover, net_inflow, main_net_inflow, source, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'yahoo-sector-proxy', ?)
                ON CONFLICT(sector_code, trade_date) DO UPDATE SET
                  sector_name = excluded.sector_name,
                  market = excluded.market,
                  change_pct = excluded.change_pct,
                  turnover = excluded.turnover,
                  net_inflow = excluded.net_inflow,
                  main_net_inflow = excluded.main_net_inflow,
                  source = excluded.source,
                  created_at = excluded.created_at
                """,
                (
                    symbol,
                    name,
                    point["trade_date"],
                    market,
                    point["change_pct"],
                    point["turnover"],
                    net_inflow,
                    net_inflow,
                    now_iso(),
                ),
            )
            flow_score = max(0.0, min(100.0, 50 + float(net_inflow or 0) / 10000000))
            momentum_score = max(0.0, min(100.0, 50 + float(point["change_pct"] or 0) * 8))
            score = round(flow_score * 0.55 + momentum_score * 0.3 + 50 * 0.15, 2)
            connection.execute(
                """
                INSERT INTO investment_opportunity_daily (
                  target_type, target_code, target_name, trade_date, opportunity_score,
                  trend_score, capital_score, news_score, risk_score, thesis, risk_note,
                  generated_at
                ) VALUES ('sector', ?, ?, ?, ?, ?, ?, 50, ?, ?, ?, ?)
                ON CONFLICT(target_type, target_code, trade_date) DO UPDATE SET
                  target_name = excluded.target_name,
                  opportunity_score = excluded.opportunity_score,
                  trend_score = excluded.trend_score,
                  capital_score = excluded.capital_score,
                  news_score = excluded.news_score,
                  risk_score = excluded.risk_score,
                  thesis = excluded.thesis,
                  risk_note = excluded.risk_note,
                  generated_at = excluded.generated_at
                """,
                (
                    symbol,
                    name,
                    point["trade_date"],
                    score,
                    momentum_score,
                    flow_score,
                    max(0.0, min(100.0, abs(float(point["change_pct"] or 0)) * 8)),
                    f"{name} proxy ETF {symbol} changed {point['change_pct']:+.2f}% with estimated flow {net_inflow:.2f}.",
                    "US/HK sector values are ETF proxies from Yahoo Finance, not exchange-reported sector fund flow.",
                    now_iso(),
                ),
            )
            inserted += 1
        except Exception:
            continue
    return inserted


def collect_sector_flows(connection: sqlite3.Connection, limit: int = 40) -> int:
    init_db(connection)
    started_at = now_iso()
    sources = [
        ("eastmoney-industry", "A股行业板块", "m:90+t:2"),
        ("eastmoney-concept", "A股概念板块", "m:90+t:3"),
    ]
    inserted = 0
    errors: list[str] = []
    trade_dates: set[str] = set()

    for source, market, fs in sources:
        try:
            payload = fetch_json(EASTMONEY_SECTOR_URL.format(limit=limit, fs=quote(fs, safe=":")))
            rows = payload.get("data", {}).get("diff", []) or []
            for row in rows:
                sector_code = str(row.get("f12") or "")
                sector_name = str(row.get("f14") or sector_code)
                if not sector_code:
                    continue
                trade_date = date_from_unix(row.get("f124"))
                trade_dates.add(trade_date)
                net_inflow = row.get("f62")
                main_net_inflow = row.get("f66")
                connection.execute(
                    """
                    INSERT INTO daily_sector_flows (
                      sector_code, sector_name, trade_date, market, change_pct,
                      turnover, net_inflow, main_net_inflow, source, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(sector_code, trade_date) DO UPDATE SET
                      sector_name = excluded.sector_name,
                      market = excluded.market,
                      change_pct = excluded.change_pct,
                      turnover = excluded.turnover,
                      net_inflow = excluded.net_inflow,
                      main_net_inflow = excluded.main_net_inflow,
                      source = excluded.source,
                      created_at = excluded.created_at
                    """,
                    (
                        sector_code,
                        sector_name,
                        trade_date,
                        market,
                        row.get("f3"),
                        row.get("f2"),
                        net_inflow,
                        main_net_inflow,
                        source,
                        now_iso(),
                    ),
                )
                flow_score = max(0.0, min(100.0, 50 + (float(net_inflow or 0) / 100000000)))
                momentum_score = max(0.0, min(100.0, 50 + float(row.get("f3") or 0) * 8))
                stage = "breakout" if flow_score >= 70 and momentum_score >= 60 else "decline" if flow_score <= 35 else "range"
                connection.execute(
                    """
                    INSERT INTO sector_cycle_daily (
                      sector_code, trade_date, cycle_stage, trend_score, capital_flow_score,
                      momentum_score, crowding_score, news_heat_score, generated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(sector_code, trade_date) DO UPDATE SET
                      cycle_stage = excluded.cycle_stage,
                      trend_score = excluded.trend_score,
                      capital_flow_score = excluded.capital_flow_score,
                      momentum_score = excluded.momentum_score,
                      crowding_score = excluded.crowding_score,
                      news_heat_score = excluded.news_heat_score,
                      generated_at = excluded.generated_at
                    """,
                    (
                        sector_code,
                        trade_date,
                        stage,
                        momentum_score,
                        flow_score,
                        momentum_score,
                        max(0.0, min(100.0, abs(float(row.get("f3") or 0)) * 10)),
                        50.0,
                        now_iso(),
                    ),
                )
                score = round(flow_score * 0.55 + momentum_score * 0.3 + 50 * 0.15, 2)
                connection.execute(
                    """
                    INSERT INTO investment_opportunity_daily (
                      target_type, target_code, target_name, trade_date, opportunity_score,
                      trend_score, capital_score, news_score, risk_score, thesis, risk_note,
                      generated_at
                    ) VALUES ('sector', ?, ?, ?, ?, ?, ?, 50, ?, ?, ?, ?)
                    ON CONFLICT(target_type, target_code, trade_date) DO UPDATE SET
                      target_name = excluded.target_name,
                      opportunity_score = excluded.opportunity_score,
                      trend_score = excluded.trend_score,
                      capital_score = excluded.capital_score,
                      news_score = excluded.news_score,
                      risk_score = excluded.risk_score,
                      thesis = excluded.thesis,
                      risk_note = excluded.risk_note,
                      generated_at = excluded.generated_at
                    """,
                    (
                        sector_code,
                        sector_name,
                        trade_date,
                        score,
                        momentum_score,
                        flow_score,
                        max(0.0, min(100.0, abs(float(row.get("f3") or 0)) * 8)),
                        f"{sector_name} main net inflow {float(main_net_inflow or 0):.2f}, total net inflow {float(net_inflow or 0):.2f}, change {float(row.get('f3') or 0):+.2f}%.",
                        "Sector rankings can reverse quickly; verify whether inflow is persistent across several sessions.",
                        now_iso(),
                    ),
                )
                if inserted < 20:
                    collect_sector_leaders(connection, sector_code, trade_date, source)
                inserted += 1
        except Exception as error:
            errors.append(f"{source}: {error}")

    inserted += collect_global_sector_proxies(connection)
    proxy_dates = [
        row["trade_date"]
        for row in connection.execute(
            "SELECT max(trade_date) AS trade_date FROM daily_sector_flows WHERE source = 'yahoo-sector-proxy'"
        ).fetchall()
        if row["trade_date"]
    ]
    trade_dates.update(proxy_dates)
    target_date = max(trade_dates) if trade_dates else datetime.now().date().isoformat()
    update_coverage(
        connection,
        "sector_flows",
        target_date,
        "complete" if inserted else "failed",
        "eastmoney+yahoo",
        None if not errors else "; ".join(errors),
    )
    update_coverage(
        connection,
        "sector_leaders",
        target_date,
        "complete" if inserted else "failed",
        "eastmoney+yahoo",
        None if inserted else "No sector rows were collected.",
    )
    record_run(
        connection,
        "sector_flows",
        "eastmoney+yahoo",
        "success" if inserted else "failed",
        target_date=target_date,
        started_at=started_at,
        error_message=None if inserted else "; ".join(errors),
    )
    if inserted:
        update_daily_analysis_from_database(connection, target_date)
        today = datetime.now().date().isoformat()
        if today != target_date:
            update_daily_analysis_from_database(connection, today)
    connection.commit()
    return inserted


def load_snapshot(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Market snapshot not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def summarize_daily(snapshot: dict[str, Any], trade_date: str) -> dict[str, str]:
    assets = snapshot.get("assets", [])
    if not assets:
        return {
            "market_summary": "No market assets were available for this date.",
            "sector_summary": "Sector data source is not configured yet.",
            "capital_flow_summary": "No capital-flow metrics were available.",
            "news_summary": "News collection is not configured yet.",
            "opportunity_summary": "No investment opportunities were generated.",
            "risk_summary": "No risk signals were generated.",
        }

    sorted_by_change = sorted(assets, key=lambda item: item.get("changePct", 0), reverse=True)
    sorted_by_flow = sorted(
        assets,
        key=lambda item: item.get("flow", {}).get("estimatedNetFlow", 0),
        reverse=True,
    )
    strongest = sorted_by_change[0]
    weakest = sorted_by_change[-1]
    flow_leader = sorted_by_flow[0]
    flow_lagger = sorted_by_flow[-1]
    summary = snapshot.get("marketSummary", {})

    return {
        "market_summary": (
            f"{trade_date}: tracked {len(assets)} assets. "
            f"Strongest price move: {strongest['asset']['symbol']} "
            f"{strongest.get('changePct', 0):+.2f}%; weakest: "
            f"{weakest['asset']['symbol']} {weakest.get('changePct', 0):+.2f}%."
        ),
        "sector_summary": "Sector flow capture is reserved for the next data-source integration.",
        "capital_flow_summary": (
            f"Estimated 10-day net flow total: "
            f"{summary.get('totalEstimatedNetFlow', 0):.2f}. "
            f"Top inflow: {flow_leader['asset']['symbol']} "
            f"{flow_leader.get('flow', {}).get('estimatedNetFlow', 0):.2f}; "
            f"top outflow: {flow_lagger['asset']['symbol']} "
            f"{flow_lagger.get('flow', {}).get('estimatedNetFlow', 0):.2f}."
        ),
        "news_summary": "News collection is not configured yet.",
        "opportunity_summary": (
            f"Watch {flow_leader['asset']['symbol']} if capital inflow remains persistent."
        ),
        "risk_summary": (
            f"Review {flow_lagger['asset']['symbol']} because it has the weakest tracked flow."
        ),
    }


def update_daily_analysis_from_database(connection: sqlite3.Connection, trade_date: str) -> None:
    latest_daily = row_to_dict(
        connection.execute(
            "SELECT * FROM daily_analysis WHERE trade_date <= ? ORDER BY trade_date DESC LIMIT 1",
            (trade_date,),
        ).fetchone()
    )
    top_sectors = connection.execute(
        """
        SELECT sector_name, market, change_pct, net_inflow, main_net_inflow
        FROM daily_sector_flows
        WHERE trade_date <= ?
        ORDER BY trade_date DESC, net_inflow DESC
        LIMIT 5
        """,
        (trade_date,),
    ).fetchall()
    weak_sectors = connection.execute(
        """
        SELECT sector_name, net_inflow
        FROM daily_sector_flows
        WHERE trade_date <= ?
        ORDER BY trade_date DESC, net_inflow ASC
        LIMIT 3
        """,
        (trade_date,),
    ).fetchall()
    news_rows = connection.execute(
        """
        SELECT coalesce(nullif(n.title_zh, ''), n.title) AS title,
               i.sentiment, i.impact_level, i.related_sectors
        FROM news_articles n
        JOIN news_impacts i ON i.article_id = n.id
        ORDER BY coalesce(n.published_at, n.fetched_at) DESC
        LIMIT 8
        """
    ).fetchall()
    latest_regime = row_to_dict(
        connection.execute(
            """
            SELECT * FROM market_regime_daily
            WHERE trade_date <= ?
            ORDER BY trade_date DESC
            LIMIT 1
            """,
            (trade_date,),
        ).fetchone()
    )
    top_indices = connection.execute(
        """
        SELECT name, region, change_pct
        FROM market_indices
        WHERE trade_date <= ?
        ORDER BY trade_date DESC, change_pct DESC
        LIMIT 5
        """,
        (trade_date,),
    ).fetchall()

    sector_summary = (
        "Top inflow sectors: "
        + "; ".join(
            f"{row['sector_name']}({float(row['net_inflow'] or 0) / 100000000:.2f}亿)"
            for row in top_sectors
        )
        if top_sectors
        else "No sector flow data is available yet."
    )
    news_summary = (
        "Recent sentiment: "
        + "; ".join(
            f"{row['sentiment']}/{row['impact_level']}: {row['title'][:40]}"
            for row in news_rows[:5]
        )
        if news_rows
        else "No news sentiment data is available yet."
    )
    opportunity_summary = (
        "Watch sectors with strong net inflow: "
        + ", ".join(row["sector_name"] for row in top_sectors[:3])
        if top_sectors
        else latest_daily["opportunity_summary"] if latest_daily else "No opportunities were generated."
    )
    risk_summary = (
        "Watch outflow sectors: "
        + ", ".join(row["sector_name"] for row in weak_sectors[:3])
        if weak_sectors
        else latest_daily["risk_summary"] if latest_daily else "No risks were generated."
    )

    connection.execute(
        """
        INSERT INTO daily_analysis (
          trade_date, market_summary, sector_summary, capital_flow_summary,
          news_summary, opportunity_summary, risk_summary, generated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(trade_date) DO UPDATE SET
          market_summary = excluded.market_summary,
          sector_summary = excluded.sector_summary,
          capital_flow_summary = excluded.capital_flow_summary,
          news_summary = excluded.news_summary,
          opportunity_summary = excluded.opportunity_summary,
          risk_summary = excluded.risk_summary,
          generated_at = excluded.generated_at
        """,
        (
            trade_date,
            (
                f"Market regime {latest_regime['regime']} with trend score "
                f"{latest_regime['trend_score']:.2f}, risk appetite "
                f"{latest_regime['risk_appetite_score']:.2f}. "
                + "Index leaders: "
                + "; ".join(
                    f"{row['name']}({float(row['change_pct'] or 0):+.2f}%)"
                    for row in top_indices
                )
                if latest_regime and top_indices
                else latest_daily["market_summary"] if latest_daily else "No market summary is available."
            ),
            sector_summary,
            latest_daily["capital_flow_summary"] if latest_daily else "No capital-flow summary is available.",
            news_summary,
            opportunity_summary,
            risk_summary,
            now_iso(),
        ),
    )
    update_coverage(connection, "daily_analysis", trade_date, "complete", "stockflow.py")


def opportunity_score(asset: dict[str, Any]) -> tuple[float, float, float, float, float]:
    change_pct = float(asset.get("changePct", 0))
    flow = asset.get("flow", {})
    mfi = float(flow.get("moneyFlowIndex", 50))
    cmf = float(flow.get("chaikinMoneyFlow", 0))
    estimated_flow = float(flow.get("estimatedNetFlow", 0))

    trend_score = max(0.0, min(100.0, 50 + change_pct * 5))
    capital_score = max(0.0, min(100.0, mfi + cmf * 50 + (10 if estimated_flow > 0 else -10)))
    news_score = 50.0
    risk_score = max(0.0, min(100.0, abs(change_pct) * 8 + (15 if mfi > 80 else 0)))
    total = max(0.0, min(100.0, trend_score * 0.35 + capital_score * 0.45 + news_score * 0.15 - risk_score * 0.2))
    return (round(total, 2), round(trend_score, 2), round(capital_score, 2), news_score, round(risk_score, 2))


def ingest_market_snapshot(connection: sqlite3.Connection, path: Path) -> None:
    started_at = now_iso()
    snapshot = load_snapshot(path)
    init_db(connection)

    updated_at = snapshot.get("updatedAt") or now_iso()
    trade_date = str(updated_at)[:10]
    source = str(snapshot.get("source") or "market-snapshot")

    try:
        for asset_snapshot in snapshot.get("assets", []):
            asset = asset_snapshot["asset"]
            symbol = asset["symbol"]
            connection.execute(
                """
                INSERT INTO assets (
                  symbol, name, asset_type, region, exchange, currency, is_active, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                  name = excluded.name,
                  asset_type = excluded.asset_type,
                  region = excluded.region,
                  exchange = excluded.exchange,
                  currency = excluded.currency,
                  is_active = 1,
                  updated_at = excluded.updated_at
                """,
                (
                    symbol,
                    asset.get("name") or asset_snapshot.get("shortName") or symbol,
                    asset.get("type") or "stock",
                    asset.get("region") or "UNKNOWN",
                    asset_snapshot.get("exchangeName"),
                    asset_snapshot.get("currency") or asset.get("currency"),
                    now_iso(),
                ),
            )

            history = asset_snapshot.get("history", [])
            closes_by_date = {bar["date"]: float(bar["close"]) for bar in history}
            previous_close = None
            for bar in history:
                close = float(bar["close"])
                change = None if previous_close is None else close - previous_close
                change_pct = None if previous_close in (None, 0) else change / previous_close * 100
                connection.execute(
                    """
                    INSERT INTO asset_daily_bars (
                      symbol, trade_date, open, high, low, close, previous_close,
                      change, change_pct, volume, turnover, source, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(symbol, trade_date) DO UPDATE SET
                      open = excluded.open,
                      high = excluded.high,
                      low = excluded.low,
                      close = excluded.close,
                      previous_close = excluded.previous_close,
                      change = excluded.change,
                      change_pct = excluded.change_pct,
                      volume = excluded.volume,
                      turnover = excluded.turnover,
                      source = excluded.source,
                      updated_at = excluded.updated_at
                    """,
                    (
                        symbol,
                        bar["date"],
                        float(bar["open"]),
                        float(bar["high"]),
                        float(bar["low"]),
                        close,
                        previous_close,
                        change,
                        change_pct,
                        float(bar.get("volume", 0)),
                        close * float(bar.get("volume", 0)),
                        source,
                        now_iso(),
                        now_iso(),
                    ),
                )
                previous_close = closes_by_date[bar["date"]]

            score, trend, capital, news, risk = opportunity_score(asset_snapshot)
            connection.execute(
                """
                INSERT INTO investment_opportunity_daily (
                  target_type, target_code, target_name, trade_date, opportunity_score,
                  trend_score, capital_score, news_score, risk_score, thesis, risk_note,
                  generated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(target_type, target_code, trade_date) DO UPDATE SET
                  target_name = excluded.target_name,
                  opportunity_score = excluded.opportunity_score,
                  trend_score = excluded.trend_score,
                  capital_score = excluded.capital_score,
                  news_score = excluded.news_score,
                  risk_score = excluded.risk_score,
                  thesis = excluded.thesis,
                  risk_note = excluded.risk_note,
                  generated_at = excluded.generated_at
                """,
                (
                    asset.get("type") or "stock",
                    symbol,
                    asset_snapshot.get("shortName") or asset.get("name") or symbol,
                    trade_date,
                    score,
                    trend,
                    capital,
                    news,
                    risk,
                    (
                        f"Opportunity score {score}: trend {trend}, capital {capital}, "
                        f"10-day estimated flow {asset_snapshot.get('flow', {}).get('estimatedNetFlow', 0):.2f}."
                    ),
                    "High short-term change or elevated MFI can indicate crowding.",
                    now_iso(),
                ),
            )

        daily = summarize_daily(snapshot, trade_date)
        connection.execute(
            """
            INSERT INTO daily_analysis (
              trade_date, market_summary, sector_summary, capital_flow_summary,
              news_summary, opportunity_summary, risk_summary, generated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(trade_date) DO UPDATE SET
              market_summary = excluded.market_summary,
              sector_summary = excluded.sector_summary,
              capital_flow_summary = excluded.capital_flow_summary,
              news_summary = excluded.news_summary,
              opportunity_summary = excluded.opportunity_summary,
              risk_summary = excluded.risk_summary,
              generated_at = excluded.generated_at
            """,
            (
                trade_date,
                daily["market_summary"],
                daily["sector_summary"],
                daily["capital_flow_summary"],
                daily["news_summary"],
                daily["opportunity_summary"],
                daily["risk_summary"],
                now_iso(),
            ),
        )

        update_coverage(connection, "market_bars", trade_date, "complete", source)
        update_coverage(connection, "daily_analysis", trade_date, "complete", "stockflow.py")
        update_coverage(
            connection,
            "sector_flows",
            trade_date,
            "missing",
            "not-configured",
            "Sector data source is not configured yet.",
        )
        update_coverage(
            connection,
            "news",
            trade_date,
            "missing",
            "not-configured",
            "News collection is not configured yet.",
        )
        record_run(connection, "daily", source, "success", target_date=trade_date, started_at=started_at)
        connection.commit()
    except Exception as error:
        connection.rollback()
        record_run(
            connection,
            "daily",
            source,
            "failed",
            target_date=trade_date,
            started_at=started_at,
            error_message=str(error),
        )
        connection.commit()
        raise


def infer_week_bounds(connection: sqlite3.Connection) -> tuple[str, str]:
    row = connection.execute(
        """
        SELECT max(target_date) AS trade_date
        FROM data_coverage
        WHERE status IN ('complete', 'partial')
        """
    ).fetchone()
    if row is None or row["trade_date"] is None:
        row = connection.execute("SELECT max(trade_date) AS trade_date FROM asset_daily_bars").fetchone()
    if row is None or row["trade_date"] is None:
        today = datetime.now().date()
        start = today - timedelta(days=today.weekday())
        return (start.isoformat(), (start + timedelta(days=6)).isoformat())

    end = datetime.fromisoformat(row["trade_date"]).date()
    start = end - timedelta(days=6)
    return (start.isoformat(), end.isoformat())


def generate_weekly_report(
    connection: sqlite3.Connection,
    week_start: str | None = None,
    week_end: str | None = None,
) -> None:
    init_db(connection)
    started_at = now_iso()
    if week_start is None or week_end is None:
        week_start, week_end = infer_week_bounds(connection)

    rows = connection.execute(
        """
        WITH ranked AS (
          SELECT
            symbol,
            min(trade_date) AS first_date,
            max(trade_date) AS last_date
          FROM asset_daily_bars
          WHERE trade_date BETWEEN ? AND ?
          GROUP BY symbol
        )
        SELECT
          a.symbol,
          assets.name,
          first_bar.close AS first_close,
          last_bar.close AS last_close,
          CASE
            WHEN first_bar.close = 0 THEN 0
            ELSE (last_bar.close - first_bar.close) / first_bar.close * 100
          END AS return_pct
        FROM ranked a
        JOIN asset_daily_bars first_bar
          ON first_bar.symbol = a.symbol AND first_bar.trade_date = a.first_date
        JOIN asset_daily_bars last_bar
          ON last_bar.symbol = a.symbol AND last_bar.trade_date = a.last_date
        JOIN assets ON assets.symbol = a.symbol
        ORDER BY return_pct DESC
        """,
        (week_start, week_end),
    ).fetchall()
    index_rows = connection.execute(
        """
        WITH ranked AS (
          SELECT
            symbol,
            min(trade_date) AS first_date,
            max(trade_date) AS last_date
          FROM market_indices
          WHERE trade_date BETWEEN ? AND ?
          GROUP BY symbol
        )
        SELECT
          a.symbol,
          first_index.name,
          first_index.region,
          first_index.close AS first_close,
          last_index.close AS last_close,
          CASE
            WHEN first_index.close = 0 THEN 0
            ELSE (last_index.close - first_index.close) / first_index.close * 100
          END AS return_pct
        FROM ranked a
        JOIN market_indices first_index
          ON first_index.symbol = a.symbol AND first_index.trade_date = a.first_date
        JOIN market_indices last_index
          ON last_index.symbol = a.symbol AND last_index.trade_date = a.last_date
        ORDER BY return_pct DESC
        """,
        (week_start, week_end),
    ).fetchall()
    latest_regime = row_to_dict(
        connection.execute(
            """
            SELECT * FROM market_regime_daily
            WHERE trade_date BETWEEN ? AND ?
            ORDER BY trade_date DESC
            LIMIT 1
            """,
            (week_start, week_end),
        ).fetchone()
    )

    opportunities = connection.execute(
        """
        SELECT target_code, target_name, opportunity_score, thesis, risk_note
        FROM investment_opportunity_daily
        WHERE trade_date BETWEEN ? AND ?
        ORDER BY trade_date DESC, opportunity_score DESC
        LIMIT 8
        """,
        (week_start, week_end),
    ).fetchall()
    top_sectors = connection.execute(
        """
        SELECT sector_name, max(trade_date) AS latest_date, avg(change_pct) AS avg_change_pct,
               sum(net_inflow) AS total_net_inflow, sum(main_net_inflow) AS total_main_net_inflow
        FROM daily_sector_flows
        WHERE trade_date BETWEEN ? AND ?
        GROUP BY sector_code, sector_name
        ORDER BY total_net_inflow DESC
        LIMIT 8
        """,
        (week_start, week_end),
    ).fetchall()
    bottom_sectors = connection.execute(
        """
        SELECT sector_name, sum(net_inflow) AS total_net_inflow
        FROM daily_sector_flows
        WHERE trade_date BETWEEN ? AND ?
        GROUP BY sector_code, sector_name
        ORDER BY total_net_inflow ASC
        LIMIT 5
        """,
        (week_start, week_end),
    ).fetchall()
    news_counts = connection.execute(
        """
        SELECT i.sentiment, count(*) AS count
        FROM news_articles n
        JOIN news_impacts i ON i.article_id = n.id
        WHERE date(coalesce(n.published_at, n.fetched_at)) BETWEEN ? AND ?
        GROUP BY i.sentiment
        ORDER BY count DESC
        """,
        (week_start, week_end),
    ).fetchall()
    important_news = connection.execute(
        """
        SELECT coalesce(nullif(n.title_zh, ''), n.title) AS title,
               i.sentiment, i.impact_level, i.related_sectors
        FROM news_articles n
        JOIN news_impacts i ON i.article_id = n.id
        WHERE i.impact_level IN ('high', 'medium')
        ORDER BY coalesce(n.published_at, n.fetched_at) DESC
        LIMIT 6
        """
    ).fetchall()

    if rows:
        strongest = rows[0]
        weakest = rows[-1]
        market_review = (
            f"{week_start} to {week_end}: tracked {len(rows)} assets. "
            f"Strongest: {strongest['symbol']} {strongest['return_pct']:+.2f}%; "
            f"weakest: {weakest['symbol']} {weakest['return_pct']:+.2f}%."
        )
        opportunity_watchlist = "; ".join(
            f"{row['target_code']}({row['opportunity_score']:.1f})" for row in opportunities
        ) or "No generated opportunities."
        risk_watchlist = (
            f"Review weak or crowded assets, especially {weakest['symbol']} if the trend persists."
        )
    elif index_rows:
        strongest = index_rows[0]
        weakest = index_rows[-1]
        market_review = (
            f"{week_start} to {week_end}: tracked {len(index_rows)} major indices. "
            f"Strongest: {strongest['name']} {strongest['return_pct']:+.2f}%; "
            f"weakest: {weakest['name']} {weakest['return_pct']:+.2f}%."
        )
        opportunity_watchlist = "Index context: " + ", ".join(
            f"{row['name']}({row['return_pct']:+.2f}%)" for row in index_rows[:4]
        )
        risk_watchlist = f"Review broad-market weakness, especially {weakest['name']}."
    else:
        market_review = f"{week_start} to {week_end}: no market bars are available."
        opportunity_watchlist = "No generated opportunities."
        risk_watchlist = "No generated risks."

    sector_rotation = (
        "Top weekly sector inflows: "
        + "; ".join(
            f"{row['sector_name']}({float(row['total_net_inflow'] or 0) / 100000000:.2f}亿)"
            for row in top_sectors
        )
        if top_sectors
        else "No sector-flow data was collected for this week."
    )
    capital_flow_review = (
        sector_rotation
        + (
            ". Main outflow sectors: "
            + ", ".join(row["sector_name"] for row in bottom_sectors[:3])
            if bottom_sectors
            else ""
        )
    )
    news_theme_review = (
        "News sentiment distribution: "
        + ", ".join(f"{row['sentiment']} {row['count']}" for row in news_counts)
        + (
            ". Key headlines: "
            + "; ".join(f"{row['sentiment']}: {row['title'][:50]}" for row in important_news[:4])
            if important_news
            else ""
        )
        if news_counts
        else "No news sentiment data was collected for this week."
    )
    if top_sectors:
        opportunity_watchlist = (
            opportunity_watchlist
            + "; sectors: "
            + ", ".join(row["sector_name"] for row in top_sectors[:4])
        )
    if bottom_sectors:
        risk_watchlist = risk_watchlist + "; sector outflows: " + ", ".join(
            row["sector_name"] for row in bottom_sectors[:3]
        )

    connection.execute(
        """
        INSERT INTO weekly_reports (
          week_start, week_end, report_title, market_review, sector_rotation,
          capital_flow_review, news_theme_review, opportunity_watchlist,
          risk_watchlist, historical_context, next_week_focus, generated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(week_start, week_end) DO UPDATE SET
          report_title = excluded.report_title,
          market_review = excluded.market_review,
          sector_rotation = excluded.sector_rotation,
          capital_flow_review = excluded.capital_flow_review,
          news_theme_review = excluded.news_theme_review,
          opportunity_watchlist = excluded.opportunity_watchlist,
          risk_watchlist = excluded.risk_watchlist,
          historical_context = excluded.historical_context,
          next_week_focus = excluded.next_week_focus,
          generated_at = excluded.generated_at
        """,
        (
            week_start,
            week_end,
            f"Investment weekly report {week_start} - {week_end}",
            market_review,
            sector_rotation,
            capital_flow_review,
            news_theme_review,
            opportunity_watchlist,
            risk_watchlist,
            (
                f"Latest market regime: {latest_regime['regime']} with trend score "
                f"{latest_regime['trend_score']:.2f} and risk appetite "
                f"{latest_regime['risk_appetite_score']:.2f}."
                if latest_regime
                else "Historical-cycle matching schema is ready; matching will run after enough history is collected."
            ),
            "Focus on assets with persistent capital scores and improving weekly trend.",
            now_iso(),
        ),
    )

    update_coverage(connection, "weekly_report", week_end, "complete", "stockflow.py")
    record_run(
        connection,
        "weekly",
        "stockflow.py",
        "success",
        start_date=week_start,
        end_date=week_end,
        started_at=started_at,
    )
    connection.commit()


def api_summary(
    connection: sqlite3.Connection,
    *,
    as_of_date: str | None = None,
    page_size: int = 10,
    sector_page: int = 1,
    leader_page: int = 1,
    news_page: int = 1,
    opportunity_page: int = 1,
    market_page: int = 1,
) -> dict[str, Any]:
    init_db(connection)
    page_size = safe_page_size(page_size)
    sector_page = safe_page(sector_page)
    leader_page = safe_page(leader_page)
    news_page = safe_page(news_page)
    opportunity_page = safe_page(opportunity_page)
    market_page = safe_page(market_page)
    as_of_clause = "WHERE trade_date <= ?" if as_of_date else ""
    date_params: tuple[Any, ...] = (as_of_date,) if as_of_date else ()
    latest_daily = row_to_dict(
        connection.execute(
            f"SELECT * FROM daily_analysis {as_of_clause} ORDER BY trade_date DESC LIMIT 1",
            date_params,
        ).fetchone()
    )
    latest_weekly = row_to_dict(
        connection.execute(
            "SELECT * FROM weekly_reports "
            + ("WHERE week_end <= ? " if as_of_date else "")
            + "ORDER BY week_end DESC LIMIT 1",
            date_params,
        ).fetchone()
    )
    latest_regime = row_to_dict(
        connection.execute(
            "SELECT * FROM market_regime_daily "
            + ("WHERE trade_date <= ? " if as_of_date else "")
            + "ORDER BY trade_date DESC LIMIT 1",
            date_params,
        ).fetchone()
    )
    latest_cycle_report = row_to_dict(
        connection.execute(
            "SELECT * FROM cycle_reports "
            + ("WHERE period_end <= ? " if as_of_date else "")
            + "ORDER BY period_end DESC, generated_at DESC LIMIT 1",
            date_params,
        ).fetchone()
    )
    coverage = [
        dict(row)
        for row in connection.execute(
            f"""
            SELECT dataset, target_date, status, source, checked_at, notes
            FROM data_coverage
            {"WHERE target_date <= ?" if as_of_date else ""}
            ORDER BY target_date DESC, dataset
            LIMIT 12
            """,
            date_params,
        ).fetchall()
    ]
    market_total = connection.execute(
        "SELECT count(*) AS total FROM market_indices "
        + ("WHERE trade_date <= ?" if as_of_date else ""),
        date_params,
    ).fetchone()["total"]
    market_indices = [
        dict(row)
        for row in connection.execute(
            f"""
            SELECT symbol, trade_date, name, region, open, high, low, close,
                   previous_close, change, change_pct, volume, turnover, source
            FROM market_indices
            {"WHERE trade_date <= ?" if as_of_date else ""}
            ORDER BY trade_date DESC, region, symbol
            LIMIT ? OFFSET ?
            """,
            (*date_params, page_size, (market_page - 1) * page_size),
        ).fetchall()
    ]
    opportunity_total = connection.execute(
        "SELECT count(*) AS total FROM investment_opportunity_daily "
        + ("WHERE trade_date <= ?" if as_of_date else ""),
        date_params,
    ).fetchone()["total"]
    opportunities = [
        dict(row)
        for row in connection.execute(
            f"""
            SELECT target_type, target_code, target_name, trade_date, opportunity_score,
                   trend_score, capital_score, news_score, risk_score, thesis, risk_note
            FROM investment_opportunity_daily
            {"WHERE trade_date <= ?" if as_of_date else ""}
            ORDER BY trade_date DESC, opportunity_score DESC
            LIMIT ? OFFSET ?
            """,
            (*date_params, page_size, (opportunity_page - 1) * page_size),
        ).fetchall()
    ]
    early_opportunities = [
        dict(row)
        for row in connection.execute(
            f"""
            SELECT target_type, target_code, target_name, trade_date, early_score,
                   flow_persistence_score, rank_improvement_score, heat_score,
                   crowding_risk_score, matched_funds, thesis, action_hint
            FROM early_opportunities
            {"WHERE trade_date <= ?" if as_of_date else ""}
            ORDER BY trade_date DESC, early_score DESC
            LIMIT 8
            """,
            date_params,
        ).fetchall()
    ]
    tracked_opportunities = [
        dict(row)
        for row in connection.execute(
            f"""
            SELECT id, target_type, target_code, target_name, source_report_date,
                   entry_date, entry_score, entry_price, latest_date, latest_price,
                   return_pct, status, thesis, matched_funds, updated_at
            FROM opportunity_tracking
            {"WHERE source_report_date <= ?" if as_of_date else ""}
            ORDER BY source_report_date DESC, entry_score DESC
            LIMIT 8
            """,
            date_params,
        ).fetchall()
    ]
    sector_total = connection.execute(
        "SELECT count(*) AS total FROM daily_sector_flows "
        + ("WHERE trade_date <= ?" if as_of_date else ""),
        date_params,
    ).fetchone()["total"]
    sector_flows = [
        dict(row)
        for row in connection.execute(
            f"""
            SELECT sector_code, sector_name, trade_date, market, change_pct, turnover,
                   net_inflow, main_net_inflow, source
            FROM daily_sector_flows
            {"WHERE trade_date <= ?" if as_of_date else ""}
            ORDER BY trade_date DESC, net_inflow DESC
            LIMIT ? OFFSET ?
            """,
            (*date_params, page_size, (sector_page - 1) * page_size),
        ).fetchall()
    ]
    leader_total = connection.execute(
        "SELECT count(*) AS total FROM daily_sector_leaders "
        + ("WHERE trade_date <= ?" if as_of_date else ""),
        date_params,
    ).fetchone()["total"]
    sector_leaders = [
        dict(row)
        for row in connection.execute(
            f"""
            SELECT l.sector_code, f.sector_name, l.trade_date, l.symbol, l.name,
                   l.rank_type, l.rank_value, l.change_pct, l.net_inflow, l.source
            FROM daily_sector_leaders l
            LEFT JOIN daily_sector_flows f
              ON f.sector_code = l.sector_code AND f.trade_date = l.trade_date
            {"WHERE l.trade_date <= ?" if as_of_date else ""}
            ORDER BY l.trade_date DESC, l.rank_value DESC
            LIMIT ? OFFSET ?
            """,
            (*date_params, page_size, (leader_page - 1) * page_size),
        ).fetchall()
    ]
    news_total = connection.execute(
        "SELECT count(*) AS total FROM news_articles n JOIN news_impacts i ON i.article_id = n.id "
        + ("WHERE date(coalesce(n.published_at, n.fetched_at)) <= ?" if as_of_date else ""),
        date_params,
    ).fetchone()["total"]
    news = [
        dict(row)
        for row in connection.execute(
            f"""
            SELECT n.id, n.source,
                   coalesce(nullif(n.title_zh, ''), n.title) AS title,
                   coalesce(nullif(n.summary_zh, ''), n.summary) AS summary,
                   n.url, n.published_at,
                   n.language, i.sentiment, i.impact_level, i.related_sectors,
                   coalesce(nullif(i.thesis_zh, ''), i.thesis) AS thesis,
                   i.risk_note
            FROM news_articles n
            JOIN news_impacts i ON i.article_id = n.id
            {"WHERE date(coalesce(n.published_at, n.fetched_at)) <= ?" if as_of_date else ""}
            ORDER BY coalesce(n.published_at, n.fetched_at) DESC
            LIMIT ? OFFSET ?
            """,
            (*date_params, page_size, (news_page - 1) * page_size),
        ).fetchall()
    ]
    return {
        "databasePath": str(DATABASE_FILE),
        "filters": {"asOfDate": as_of_date, "pageSize": page_size},
        "latestDailyAnalysis": latest_daily,
        "latestWeeklyReport": latest_weekly,
        "latestMarketRegime": latest_regime,
        "latestCycleReport": latest_cycle_report,
        "coverage": coverage,
        "marketIndices": market_indices,
        "opportunities": opportunities,
        "earlyOpportunities": early_opportunities,
        "trackedOpportunities": tracked_opportunities,
        "sectorFlows": sector_flows,
        "sectorLeaders": sector_leaders,
        "news": news,
        "pagination": {
            "marketIndices": pagination(market_page, page_size, market_total),
            "opportunities": pagination(opportunity_page, page_size, opportunity_total),
            "sectorFlows": pagination(sector_page, page_size, sector_total),
            "sectorLeaders": pagination(leader_page, page_size, leader_total),
            "news": pagination(news_page, page_size, news_total),
        },
    }


def backfill(connection: sqlite3.Connection, snapshot_path: Path) -> None:
    ingest_market_snapshot(connection, snapshot_path)
    generate_weekly_report(connection)


def collect_external(connection: sqlite3.Connection) -> None:
    init_db(connection)
    index_count = collect_market_indices(connection)
    sector_count = collect_sector_flows(connection)
    news_count = collect_news(connection)
    latest_date_row = connection.execute(
        """
        SELECT max(target_date) AS target_date
        FROM data_coverage
        WHERE dataset IN ('market_bars', 'sector_flows', 'news')
        """
    ).fetchone()
    target_date = latest_date_row["target_date"] or datetime.now().date().isoformat()
    update_daily_analysis_from_database(connection, target_date)
    analyze_early_opportunities(connection, target_date)
    track_weekly_opportunities(connection)
    record_run(
        connection,
        "external",
        "yahoo+eastmoney+rss",
        "success" if index_count or sector_count or news_count else "failed",
        target_date=target_date,
        error_message=None if index_count or sector_count or news_count else "No external data was collected.",
    )
    connection.commit()


def main() -> int:
    parser = argparse.ArgumentParser(description="StockFlow local intelligence database")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db")

    ingest_parser = subparsers.add_parser("ingest-market-snapshot")
    ingest_parser.add_argument("--input", default=str(SNAPSHOT_FILE))

    subparsers.add_parser("collect-external")

    sector_parser = subparsers.add_parser("collect-sectors")
    sector_parser.add_argument("--limit", type=int, default=40)

    index_parser = subparsers.add_parser("collect-indices")
    index_parser.add_argument("--from", dest="start_date")
    index_parser.add_argument("--to", dest="end_date")

    subparsers.add_parser("collect-news")

    enrich_parser = subparsers.add_parser("enrich-news")
    enrich_parser.add_argument("--limit", type=int, default=20)

    analyze_parser = subparsers.add_parser("analyze-opportunities")
    analyze_parser.add_argument("--date")

    cycle_parser = subparsers.add_parser("analyze-cycles")
    cycle_parser.add_argument("--lookback-days", type=int, default=183)
    cycle_parser.add_argument("--end-date")

    report_parser = subparsers.add_parser("report-weekly")
    report_parser.add_argument("--week-start")
    report_parser.add_argument("--week-end")

    backfill_parser = subparsers.add_parser("backfill")
    backfill_parser.add_argument("--input", default=str(SNAPSHOT_FILE))

    api_parser = subparsers.add_parser("api-summary")
    api_parser.add_argument("--date")
    api_parser.add_argument("--page-size", type=int, default=10)
    api_parser.add_argument("--sector-page", type=int, default=1)
    api_parser.add_argument("--leader-page", type=int, default=1)
    api_parser.add_argument("--news-page", type=int, default=1)
    api_parser.add_argument("--opportunity-page", type=int, default=1)
    api_parser.add_argument("--market-page", type=int, default=1)

    args = parser.parse_args()
    with connect() as connection:
        if args.command == "init-db":
            init_db(connection)
            print(json.dumps({"databasePath": str(DATABASE_FILE)}, ensure_ascii=False))
        elif args.command == "ingest-market-snapshot":
            ingest_market_snapshot(connection, Path(args.input))
            print(json.dumps({"status": "ok", "databasePath": str(DATABASE_FILE)}, ensure_ascii=False))
        elif args.command == "collect-external":
            collect_external(connection)
            print(json.dumps({"status": "ok", "databasePath": str(DATABASE_FILE)}, ensure_ascii=False))
        elif args.command == "collect-sectors":
            count = collect_sector_flows(connection, args.limit)
            print(json.dumps({"status": "ok", "count": count, "databasePath": str(DATABASE_FILE)}, ensure_ascii=False))
        elif args.command == "collect-indices":
            count = collect_market_indices(connection, args.start_date, args.end_date)
            print(json.dumps({"status": "ok", "count": count, "databasePath": str(DATABASE_FILE)}, ensure_ascii=False))
        elif args.command == "collect-news":
            count = collect_news(connection)
            print(json.dumps({"status": "ok", "count": count, "databasePath": str(DATABASE_FILE)}, ensure_ascii=False))
        elif args.command == "enrich-news":
            count = enrich_news_with_ollama(connection, args.limit)
            print(
                json.dumps(
                    {
                        "status": "ok",
                        "count": count,
                        "model": OLLAMA_MODEL,
                        "databasePath": str(DATABASE_FILE),
                    },
                    ensure_ascii=False,
                )
            )
        elif args.command == "analyze-opportunities":
            early_count = analyze_early_opportunities(connection, args.date)
            tracking_count = track_weekly_opportunities(connection)
            print(
                json.dumps(
                    {
                        "status": "ok",
                        "earlyCount": early_count,
                        "trackingCount": tracking_count,
                        "databasePath": str(DATABASE_FILE),
                    },
                    ensure_ascii=False,
                )
            )
        elif args.command == "analyze-cycles":
            result = analyze_market_cycles(connection, args.lookback_days, args.end_date)
            print(
                json.dumps(
                    {
                        "status": "ok",
                        **result,
                        "databasePath": str(DATABASE_FILE),
                    },
                    ensure_ascii=False,
                )
            )
        elif args.command == "report-weekly":
            generate_weekly_report(connection, args.week_start, args.week_end)
            print(json.dumps({"status": "ok", "databasePath": str(DATABASE_FILE)}, ensure_ascii=False))
        elif args.command == "backfill":
            backfill(connection, Path(args.input))
            print(json.dumps({"status": "ok", "databasePath": str(DATABASE_FILE)}, ensure_ascii=False))
        elif args.command == "api-summary":
            print(
                json.dumps(
                    api_summary(
                        connection,
                        as_of_date=args.date,
                        page_size=args.page_size,
                        sector_page=args.sector_page,
                        leader_page=args.leader_page,
                        news_page=args.news_page,
                        opportunity_page=args.opportunity_page,
                        market_page=args.market_page,
                    ),
                    ensure_ascii=False,
                )
            )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise
