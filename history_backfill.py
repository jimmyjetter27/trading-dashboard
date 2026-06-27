from __future__ import annotations

import json
import math
import sqlite3
import threading
import traceback
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable

try:
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover
    mt5 = None


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def iso_now() -> str:
    return datetime.now(UTC).isoformat()


def to_utc_date_start(raw_value: str) -> datetime:
    parsed = datetime.fromisoformat(str(raw_value).strip())
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def to_utc_date_end(raw_value: str) -> datetime:
    start = to_utc_date_start(raw_value)
    return start + timedelta(days=1) - timedelta(seconds=1)


def session_label_for(dt_value: datetime) -> str:
    hour = dt_value.hour
    if 0 <= hour <= 6:
        return "Asian/Tokyo"
    if 7 <= hour <= 10:
        return "London morning"
    if 11 <= hour <= 12:
        return "London midday/pre-NY"
    if 13 <= hour <= 16:
        return "New York"
    if 17 <= hour <= 21:
        return "Late New York"
    return "Off-session"


def asset_class_for_symbol(symbol: str) -> str:
    normalized = symbol.upper()
    if "XAU" in normalized or normalized == "GOLD":
        return "metal"
    if "BTC" in normalized:
        return "crypto"
    if "OIL" in normalized:
        return "energy"
    if normalized in {"NAS100", "USTEC", "US30"}:
        return "index"
    return "forex"


def rolling_sum(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if period <= 0:
        return result
    running = 0.0
    for index, value in enumerate(values):
        running += value
        if index >= period:
            running -= values[index - period]
        if index >= period - 1:
            result[index] = running
    return result


def sma(values: list[float], period: int) -> list[float | None]:
    sums = rolling_sum(values, period)
    return [(item / period if item is not None else None) for item in sums]


def ema_series(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if not values or period <= 0:
        return result
    alpha = 2.0 / (period + 1.0)
    seeded = False
    ema_value = 0.0
    for index, value in enumerate(values):
        if index == period - 1 and not seeded:
            ema_value = sum(values[:period]) / period
            result[index] = ema_value
            seeded = True
            continue
        if not seeded:
            continue
        ema_value = (value - ema_value) * alpha + ema_value
        result[index] = ema_value
    return result


def standard_deviation(values: list[float]) -> float:
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((item - mean) ** 2 for item in values) / len(values)
    return math.sqrt(variance)


def atr_series(rows: list[dict[str, Any]], period: int = 14) -> list[float | None]:
    if not rows:
        return []
    true_ranges: list[float] = []
    previous_close = None
    for row in rows:
        high = safe_float(row["high"])
        low = safe_float(row["low"])
        close = safe_float(row["close"])
        if previous_close is None:
            tr = high - low
        else:
            tr = max(high - low, abs(high - previous_close), abs(low - previous_close))
        true_ranges.append(tr)
        previous_close = close
    return sma(true_ranges, period)


def adx_series(rows: list[dict[str, Any]], period: int = 14) -> tuple[list[float | None], list[float | None], list[float | None]]:
    length = len(rows)
    if length < 2:
        empty = [None] * length
        return empty, empty, empty
    plus_dm = [0.0] * length
    minus_dm = [0.0] * length
    tr_values = [0.0] * length
    for index in range(1, length):
        current = rows[index]
        previous = rows[index - 1]
        up_move = safe_float(current["high"]) - safe_float(previous["high"])
        down_move = safe_float(previous["low"]) - safe_float(current["low"])
        plus_dm[index] = up_move if up_move > down_move and up_move > 0 else 0.0
        minus_dm[index] = down_move if down_move > up_move and down_move > 0 else 0.0
        high = safe_float(current["high"])
        low = safe_float(current["low"])
        previous_close = safe_float(previous["close"])
        tr_values[index] = max(high - low, abs(high - previous_close), abs(low - previous_close))

    plus_dm_sum = rolling_sum(plus_dm, period)
    minus_dm_sum = rolling_sum(minus_dm, period)
    tr_sum = rolling_sum(tr_values, period)
    plus_di: list[float | None] = [None] * length
    minus_di: list[float | None] = [None] * length
    dx_values: list[float | None] = [None] * length
    for index in range(length):
        if plus_dm_sum[index] is None or minus_dm_sum[index] is None or tr_sum[index] in {None, 0}:
            continue
        plus_di[index] = 100.0 * safe_float(plus_dm_sum[index]) / safe_float(tr_sum[index], 1.0)
        minus_di[index] = 100.0 * safe_float(minus_dm_sum[index]) / safe_float(tr_sum[index], 1.0)
        denominator = safe_float(plus_di[index]) + safe_float(minus_di[index])
        if denominator > 0:
            dx_values[index] = 100.0 * abs(safe_float(plus_di[index]) - safe_float(minus_di[index])) / denominator
    adx = sma([safe_float(item) for item in dx_values], period)
    return adx, plus_di, minus_di


def bollinger_width_series(values: list[float], period: int = 20, deviation_factor: float = 2.0) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    for index in range(period - 1, len(values)):
        window = values[index - period + 1:index + 1]
        middle = sum(window) / period
        if middle == 0:
            continue
        deviation = standard_deviation(window)
        upper = middle + deviation_factor * deviation
        lower = middle - deviation_factor * deviation
        result[index] = (upper - lower) / middle
    return result


def chop_series(rows: list[dict[str, Any]], period: int = 14) -> list[float | None]:
    atr_like = atr_series(rows, 1)
    result: list[float | None] = [None] * len(rows)
    for index in range(period - 1, len(rows)):
        window = rows[index - period + 1:index + 1]
        high_max = max(safe_float(item["high"]) for item in window)
        low_min = min(safe_float(item["low"]) for item in window)
        tr_sum = sum(safe_float(value) for value in atr_like[index - period + 1:index + 1] if value is not None)
        denominator = high_max - low_min
        if denominator <= 0 or tr_sum <= 0:
            continue
        result[index] = 100.0 * math.log10(tr_sum / denominator) / math.log10(period)
    return result


@dataclass
class BackfillConfig:
    default_terminal_path: str
    default_symbols: list[str]
    default_timeframes: list[str]
    default_days: int = 30


class AurumBoxMemoryDB:
    def __init__(self, path: Path, default_symbols: list[str]) -> None:
        self.path = path
        self.lock = threading.Lock()
        self.default_symbols = default_symbols
        self._init_db()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;

                CREATE TABLE IF NOT EXISTS symbols (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    display_name TEXT NOT NULL,
                    broker_symbol TEXT NOT NULL UNIQUE,
                    asset_class TEXT NOT NULL DEFAULT 'unknown',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    notes TEXT DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS market_bars (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    time INTEGER NOT NULL,
                    datetime_utc TEXT NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    tick_volume INTEGER,
                    spread INTEGER,
                    real_volume INTEGER,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(symbol, timeframe, time)
                );

                CREATE TABLE IF NOT EXISTS market_ticks_optional (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    time_msc INTEGER NOT NULL,
                    datetime_utc TEXT NOT NULL,
                    bid REAL NOT NULL,
                    ask REAL NOT NULL,
                    last REAL NOT NULL,
                    volume REAL DEFAULT 0,
                    flags INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(symbol, time_msc)
                );

                CREATE TABLE IF NOT EXISTS indicator_features (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    time INTEGER NOT NULL,
                    datetime_utc TEXT NOT NULL,
                    atr REAL,
                    adx REAL,
                    plus_di REAL,
                    minus_di REAL,
                    ema50 REAL,
                    ema_slope REAL,
                    bollinger_band_width REAL,
                    chop_index REAL,
                    candle_body_size REAL,
                    upper_wick_size REAL,
                    lower_wick_size REAL,
                    wick_body_ratio REAL,
                    average_spread REAL,
                    session_label TEXT,
                    day_of_week INTEGER,
                    hour_of_day INTEGER,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(symbol, timeframe, time)
                );

                CREATE TABLE IF NOT EXISTS range_states (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    time INTEGER NOT NULL,
                    datetime_utc TEXT NOT NULL,
                    range_high REAL,
                    range_low REAL,
                    range_midpoint REAL,
                    range_height REAL,
                    top_touches INTEGER,
                    bottom_touches INTEGER,
                    range_quality_score REAL,
                    current_zone TEXT,
                    breakout_status TEXT,
                    invalidation_status TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(symbol, timeframe, time)
                );

                CREATE TABLE IF NOT EXISTS liquidity_levels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    time INTEGER NOT NULL,
                    datetime_utc TEXT NOT NULL,
                    level_type TEXT NOT NULL,
                    level_price REAL NOT NULL,
                    side TEXT DEFAULT '',
                    source_window TEXT DEFAULT '',
                    notes TEXT DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(symbol, timeframe, time, level_type, level_price)
                );

                CREATE TABLE IF NOT EXISTS liquidity_sweeps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    time INTEGER NOT NULL,
                    datetime_utc TEXT NOT NULL,
                    swept_level_type TEXT NOT NULL,
                    swept_level_price REAL NOT NULL,
                    sweep_side TEXT NOT NULL,
                    sweep_size REAL DEFAULT 0,
                    close_back_confirmed INTEGER DEFAULT 0,
                    rejection_wick_ratio REAL DEFAULT 0,
                    displacement_confirmed INTEGER DEFAULT 0,
                    mss_confirmed INTEGER DEFAULT 0,
                    choch_confirmed INTEGER DEFAULT 0,
                    notes TEXT DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(symbol, timeframe, time, swept_level_type, swept_level_price)
                );

                CREATE TABLE IF NOT EXISTS strategy_setups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    time INTEGER NOT NULL,
                    datetime_utc TEXT NOT NULL,
                    setup_type TEXT NOT NULL,
                    setup_side TEXT DEFAULT '',
                    confidence REAL DEFAULT 0,
                    notes TEXT DEFAULT '',
                    payload_json TEXT DEFAULT '{}',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(symbol, timeframe, time, setup_type)
                );

                CREATE TABLE IF NOT EXISTS backfill_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    status TEXT NOT NULL,
                    terminal_path TEXT NOT NULL,
                    include_ticks INTEGER NOT NULL DEFAULT 0,
                    calculate_indicators INTEGER NOT NULL DEFAULT 1,
                    detect_ranges INTEGER NOT NULL DEFAULT 1,
                    detect_liquidity_sweeps INTEGER NOT NULL DEFAULT 1,
                    from_date TEXT NOT NULL,
                    to_date TEXT NOT NULL,
                    requested_symbols_json TEXT NOT NULL DEFAULT '[]',
                    requested_timeframes_json TEXT NOT NULL DEFAULT '[]',
                    inserted_count INTEGER NOT NULL DEFAULT 0,
                    duplicates_skipped INTEGER NOT NULL DEFAULT 0,
                    failed_count INTEGER NOT NULL DEFAULT 0,
                    tick_inserted_count INTEGER NOT NULL DEFAULT 0,
                    progress_completed INTEGER NOT NULL DEFAULT 0,
                    progress_total INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS backfill_job_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    requested_from TEXT NOT NULL,
                    requested_to TEXT NOT NULL,
                    fetched_rows INTEGER NOT NULL DEFAULT 0,
                    inserted_rows INTEGER NOT NULL DEFAULT 0,
                    duplicates_skipped INTEGER NOT NULL DEFAULT 0,
                    failed_rows INTEGER NOT NULL DEFAULT 0,
                    tick_rows INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    FOREIGN KEY(job_id) REFERENCES backfill_jobs(id)
                );

                CREATE TABLE IF NOT EXISTS ai_training_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    time INTEGER NOT NULL,
                    datetime_utc TEXT NOT NULL,
                    feature_json TEXT NOT NULL DEFAULT '{}',
                    label_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(symbol, timeframe, time)
                );

                CREATE INDEX IF NOT EXISTS idx_market_bars_symbol_tf_time ON market_bars(symbol, timeframe, time);
                CREATE INDEX IF NOT EXISTS idx_market_ticks_symbol_time ON market_ticks_optional(symbol, time_msc);
                CREATE INDEX IF NOT EXISTS idx_indicator_features_symbol_tf_time ON indicator_features(symbol, timeframe, time);
                CREATE INDEX IF NOT EXISTS idx_range_states_symbol_tf_time ON range_states(symbol, timeframe, time);
                CREATE INDEX IF NOT EXISTS idx_liquidity_levels_symbol_tf_time ON liquidity_levels(symbol, timeframe, time);
                CREATE INDEX IF NOT EXISTS idx_liquidity_sweeps_symbol_tf_time ON liquidity_sweeps(symbol, timeframe, time);
                CREATE INDEX IF NOT EXISTS idx_strategy_setups_symbol_tf_time ON strategy_setups(symbol, timeframe, time);
                CREATE INDEX IF NOT EXISTS idx_backfill_job_items_job_id ON backfill_job_items(job_id);
                CREATE INDEX IF NOT EXISTS idx_ai_training_samples_symbol_tf_time ON ai_training_samples(symbol, timeframe, time);
                """
            )
            conn.commit()
        self.seed_symbols()

    def seed_symbols(self) -> None:
        rows = [
            (
                symbol,
                symbol,
                asset_class_for_symbol(symbol),
                1,
                "Default backfill symbol",
            )
            for symbol in self.default_symbols
        ]
        with self.lock, self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO symbols(display_name, broker_symbol, asset_class, enabled, notes)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(broker_symbol) DO UPDATE SET
                    display_name = excluded.display_name,
                    asset_class = excluded.asset_class,
                    enabled = COALESCE(symbols.enabled, excluded.enabled),
                    notes = CASE WHEN symbols.notes = '' THEN excluded.notes ELSE symbols.notes END
                """,
                rows,
            )
            conn.commit()

    def list_symbols(self) -> list[dict[str, Any]]:
        with self.lock, self.connect() as conn:
            rows = conn.execute(
                "SELECT id, display_name, broker_symbol, asset_class, enabled, notes FROM symbols ORDER BY enabled DESC, broker_symbol ASC"
            ).fetchall()
        return [dict(row) for row in rows]

    def create_job(self, payload: dict[str, Any]) -> int:
        now = iso_now()
        with self.lock, self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO backfill_jobs(
                    status, terminal_path, include_ticks, calculate_indicators, detect_ranges, detect_liquidity_sweeps,
                    from_date, to_date, requested_symbols_json, requested_timeframes_json,
                    inserted_count, duplicates_skipped, failed_count, tick_inserted_count,
                    progress_completed, progress_total, last_error, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0, 0, ?, '', ?)
                """,
                (
                    "queued",
                    payload["terminal_path"],
                    1 if payload.get("include_ticks") else 0,
                    1 if payload.get("calculate_indicators") else 0,
                    1 if payload.get("detect_ranges") else 0,
                    1 if payload.get("detect_liquidity_sweeps") else 0,
                    payload["from_date"],
                    payload["to_date"],
                    json.dumps(payload["symbols"], ensure_ascii=True),
                    json.dumps(payload["timeframes"], ensure_ascii=True),
                    len(payload["symbols"]) * len(payload["timeframes"]),
                    now,
                ),
            )
            job_id = int(cursor.lastrowid)
            conn.executemany(
                """
                INSERT INTO backfill_job_items(
                    job_id, symbol, timeframe, status, requested_from, requested_to,
                    fetched_rows, inserted_rows, duplicates_skipped, failed_rows, tick_rows,
                    last_error, created_at
                )
                VALUES (?, ?, ?, 'pending', ?, ?, 0, 0, 0, 0, 0, '', ?)
                """,
                [
                    (job_id, symbol, timeframe, payload["from_date"], payload["to_date"], now)
                    for symbol in payload["symbols"]
                    for timeframe in payload["timeframes"]
                ],
            )
            conn.commit()
        return job_id

    def update_job(self, job_id: int, **fields: Any) -> None:
        if not fields:
            return
        columns = ", ".join(f"{key} = ?" for key in fields)
        values = list(fields.values()) + [job_id]
        with self.lock, self.connect() as conn:
            conn.execute(f"UPDATE backfill_jobs SET {columns} WHERE id = ?", values)
            conn.commit()

    def update_job_item(self, item_id: int, **fields: Any) -> None:
        if not fields:
            return
        columns = ", ".join(f"{key} = ?" for key in fields)
        values = list(fields.values()) + [item_id]
        with self.lock, self.connect() as conn:
            conn.execute(f"UPDATE backfill_job_items SET {columns} WHERE id = ?", values)
            conn.commit()

    def list_job_items(self, job_id: int) -> list[dict[str, Any]]:
        with self.lock, self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, job_id, symbol, timeframe, status, requested_from, requested_to,
                       fetched_rows, inserted_rows, duplicates_skipped, failed_rows, tick_rows,
                       last_error, created_at, started_at, completed_at
                FROM backfill_job_items
                WHERE job_id = ?
                ORDER BY symbol ASC, timeframe ASC
                """,
                (job_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_job(self, job_id: int) -> dict[str, Any] | None:
        with self.lock, self.connect() as conn:
            row = conn.execute("SELECT * FROM backfill_jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        try:
            data["requested_symbols"] = json.loads(data.pop("requested_symbols_json", "[]") or "[]")
        except json.JSONDecodeError:
            data["requested_symbols"] = []
        try:
            data["requested_timeframes"] = json.loads(data.pop("requested_timeframes_json", "[]") or "[]")
        except json.JSONDecodeError:
            data["requested_timeframes"] = []
        return data

    def insert_market_bars(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        now = iso_now()
        with self.lock, self.connect() as conn:
            before = conn.total_changes
            conn.executemany(
                """
                INSERT OR IGNORE INTO market_bars(
                    symbol, timeframe, time, datetime_utc, open, high, low, close,
                    tick_volume, spread, real_volume, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row["symbol"],
                        row["timeframe"],
                        row["time"],
                        row["datetime_utc"],
                        row["open"],
                        row["high"],
                        row["low"],
                        row["close"],
                        row.get("tick_volume"),
                        row.get("spread"),
                        row.get("real_volume"),
                        now,
                        now,
                    )
                    for row in rows
                ],
            )
            inserted = conn.total_changes - before
            conn.commit()
        return inserted

    def insert_ticks(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        with self.lock, self.connect() as conn:
            before = conn.total_changes
            conn.executemany(
                """
                INSERT OR IGNORE INTO market_ticks_optional(
                    symbol, time_msc, datetime_utc, bid, ask, last, volume, flags
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row["symbol"],
                        row["time_msc"],
                        row["datetime_utc"],
                        row["bid"],
                        row["ask"],
                        row["last"],
                        row.get("volume", 0),
                        row.get("flags", 0),
                    )
                    for row in rows
                ],
            )
            inserted = conn.total_changes - before
            conn.commit()
        return inserted

    def replace_indicator_features(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        now = iso_now()
        with self.lock, self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO indicator_features(
                    symbol, timeframe, time, datetime_utc, atr, adx, plus_di, minus_di, ema50, ema_slope,
                    bollinger_band_width, chop_index, candle_body_size, upper_wick_size, lower_wick_size,
                    wick_body_ratio, average_spread, session_label, day_of_week, hour_of_day, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, timeframe, time) DO UPDATE SET
                    atr = excluded.atr,
                    adx = excluded.adx,
                    plus_di = excluded.plus_di,
                    minus_di = excluded.minus_di,
                    ema50 = excluded.ema50,
                    ema_slope = excluded.ema_slope,
                    bollinger_band_width = excluded.bollinger_band_width,
                    chop_index = excluded.chop_index,
                    candle_body_size = excluded.candle_body_size,
                    upper_wick_size = excluded.upper_wick_size,
                    lower_wick_size = excluded.lower_wick_size,
                    wick_body_ratio = excluded.wick_body_ratio,
                    average_spread = excluded.average_spread,
                    session_label = excluded.session_label,
                    day_of_week = excluded.day_of_week,
                    hour_of_day = excluded.hour_of_day,
                    updated_at = excluded.updated_at
                """,
                [
                    (
                        row["symbol"],
                        row["timeframe"],
                        row["time"],
                        row["datetime_utc"],
                        row.get("atr"),
                        row.get("adx"),
                        row.get("plus_di"),
                        row.get("minus_di"),
                        row.get("ema50"),
                        row.get("ema_slope"),
                        row.get("bollinger_band_width"),
                        row.get("chop_index"),
                        row.get("candle_body_size"),
                        row.get("upper_wick_size"),
                        row.get("lower_wick_size"),
                        row.get("wick_body_ratio"),
                        row.get("average_spread"),
                        row.get("session_label"),
                        row.get("day_of_week"),
                        row.get("hour_of_day"),
                        now,
                        now,
                    )
                    for row in rows
                ],
            )
            conn.commit()
        return len(rows)

    def replace_range_states(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        now = iso_now()
        with self.lock, self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO range_states(
                    symbol, timeframe, time, datetime_utc, range_high, range_low, range_midpoint, range_height,
                    top_touches, bottom_touches, range_quality_score, current_zone, breakout_status,
                    invalidation_status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, timeframe, time) DO UPDATE SET
                    range_high = excluded.range_high,
                    range_low = excluded.range_low,
                    range_midpoint = excluded.range_midpoint,
                    range_height = excluded.range_height,
                    top_touches = excluded.top_touches,
                    bottom_touches = excluded.bottom_touches,
                    range_quality_score = excluded.range_quality_score,
                    current_zone = excluded.current_zone,
                    breakout_status = excluded.breakout_status,
                    invalidation_status = excluded.invalidation_status,
                    updated_at = excluded.updated_at
                """,
                [
                    (
                        row["symbol"],
                        row["timeframe"],
                        row["time"],
                        row["datetime_utc"],
                        row.get("range_high"),
                        row.get("range_low"),
                        row.get("range_midpoint"),
                        row.get("range_height"),
                        row.get("top_touches"),
                        row.get("bottom_touches"),
                        row.get("range_quality_score"),
                        row.get("current_zone"),
                        row.get("breakout_status"),
                        row.get("invalidation_status"),
                        now,
                        now,
                    )
                    for row in rows
                ],
            )
            conn.commit()
        return len(rows)

    def replace_liquidity_levels(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        now = iso_now()
        with self.lock, self.connect() as conn:
            conn.executemany(
                """
                INSERT OR IGNORE INTO liquidity_levels(
                    symbol, timeframe, time, datetime_utc, level_type, level_price, side, source_window, notes, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row["symbol"],
                        row["timeframe"],
                        row["time"],
                        row["datetime_utc"],
                        row["level_type"],
                        row["level_price"],
                        row.get("side", ""),
                        row.get("source_window", ""),
                        row.get("notes", ""),
                        now,
                        now,
                    )
                    for row in rows
                ],
            )
            conn.commit()
        return len(rows)

    def replace_liquidity_sweeps(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        now = iso_now()
        with self.lock, self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO liquidity_sweeps(
                    symbol, timeframe, time, datetime_utc, swept_level_type, swept_level_price, sweep_side,
                    sweep_size, close_back_confirmed, rejection_wick_ratio, displacement_confirmed,
                    mss_confirmed, choch_confirmed, notes, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, timeframe, time, swept_level_type, swept_level_price) DO UPDATE SET
                    sweep_side = excluded.sweep_side,
                    sweep_size = excluded.sweep_size,
                    close_back_confirmed = excluded.close_back_confirmed,
                    rejection_wick_ratio = excluded.rejection_wick_ratio,
                    displacement_confirmed = excluded.displacement_confirmed,
                    mss_confirmed = excluded.mss_confirmed,
                    choch_confirmed = excluded.choch_confirmed,
                    notes = excluded.notes,
                    updated_at = excluded.updated_at
                """,
                [
                    (
                        row["symbol"],
                        row["timeframe"],
                        row["time"],
                        row["datetime_utc"],
                        row["swept_level_type"],
                        row["swept_level_price"],
                        row["sweep_side"],
                        row.get("sweep_size", 0),
                        1 if row.get("close_back_confirmed") else 0,
                        row.get("rejection_wick_ratio", 0),
                        1 if row.get("displacement_confirmed") else 0,
                        1 if row.get("mss_confirmed") else 0,
                        1 if row.get("choch_confirmed") else 0,
                        row.get("notes", ""),
                        now,
                        now,
                    )
                    for row in rows
                ],
            )
            conn.commit()
        return len(rows)

    def replace_strategy_setups(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        now = iso_now()
        with self.lock, self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO strategy_setups(
                    symbol, timeframe, time, datetime_utc, setup_type, setup_side, confidence, notes, payload_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, timeframe, time, setup_type) DO UPDATE SET
                    setup_side = excluded.setup_side,
                    confidence = excluded.confidence,
                    notes = excluded.notes,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                [
                    (
                        row["symbol"],
                        row["timeframe"],
                        row["time"],
                        row["datetime_utc"],
                        row["setup_type"],
                        row.get("setup_side", ""),
                        row.get("confidence", 0),
                        row.get("notes", ""),
                        json.dumps(row.get("payload", {}), ensure_ascii=True),
                        now,
                        now,
                    )
                    for row in rows
                ],
            )
            conn.commit()
        return len(rows)

    def replace_ai_training_samples(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        now = iso_now()
        with self.lock, self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO ai_training_samples(
                    symbol, timeframe, time, datetime_utc, feature_json, label_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, timeframe, time) DO UPDATE SET
                    feature_json = excluded.feature_json,
                    label_json = excluded.label_json,
                    updated_at = excluded.updated_at
                """,
                [
                    (
                        row["symbol"],
                        row["timeframe"],
                        row["time"],
                        row["datetime_utc"],
                        json.dumps(row.get("feature_json", {}), ensure_ascii=True),
                        json.dumps(row.get("label_json", {}), ensure_ascii=True),
                        now,
                        now,
                    )
                    for row in rows
                ],
            )
            conn.commit()
        return len(rows)

    def summary(self) -> dict[str, Any]:
        with self.lock, self.connect() as conn:
            bar_count = conn.execute("SELECT COUNT(*) AS count FROM market_bars").fetchone()["count"]
            tick_count = conn.execute("SELECT COUNT(*) AS count FROM market_ticks_optional").fetchone()["count"]
            feature_count = conn.execute("SELECT COUNT(*) AS count FROM indicator_features").fetchone()["count"]
            range_count = conn.execute("SELECT COUNT(*) AS count FROM range_states").fetchone()["count"]
            sweep_count = conn.execute("SELECT COUNT(*) AS count FROM liquidity_sweeps").fetchone()["count"]
            setup_count = conn.execute("SELECT COUNT(*) AS count FROM strategy_setups").fetchone()["count"]
            sample_count = conn.execute("SELECT COUNT(*) AS count FROM ai_training_samples").fetchone()["count"]
            jobs = conn.execute(
                """
                SELECT id, status, terminal_path, include_ticks, calculate_indicators, detect_ranges, detect_liquidity_sweeps,
                       from_date, to_date, inserted_count, duplicates_skipped, failed_count, tick_inserted_count,
                       progress_completed, progress_total, last_error, created_at, started_at, completed_at
                FROM backfill_jobs
                ORDER BY id DESC
                LIMIT 10
                """
            ).fetchall()
        return {
            "database_path": str(self.path),
            "counts": {
                "market_bars": bar_count,
                "market_ticks_optional": tick_count,
                "indicator_features": feature_count,
                "range_states": range_count,
                "liquidity_sweeps": sweep_count,
                "strategy_setups": setup_count,
                "ai_training_samples": sample_count,
            },
            "recent_jobs": [dict(row) for row in jobs],
        }

    def clear_all_data(self) -> dict[str, Any]:
        with self.lock, self.connect() as conn:
            conn.executescript(
                """
                DELETE FROM market_bars;
                DELETE FROM market_ticks_optional;
                DELETE FROM indicator_features;
                DELETE FROM range_states;
                DELETE FROM liquidity_levels;
                DELETE FROM liquidity_sweeps;
                DELETE FROM strategy_setups;
                DELETE FROM backfill_job_items;
                DELETE FROM backfill_jobs;
                DELETE FROM ai_training_samples;
                """
            )
            conn.commit()
        self.seed_symbols()
        return {"ok": True, "message": "Historical backfill data cleared."}


class HistoricalBackfillService:
    TIMEFRAME_MAP = {
        "M1": ("TIMEFRAME_M1", 1),
        "M5": ("TIMEFRAME_M5", 5),
        "M15": ("TIMEFRAME_M15", 15),
        "M30": ("TIMEFRAME_M30", 30),
        "H1": ("TIMEFRAME_H1", 60),
        "H4": ("TIMEFRAME_H4", 240),
        "D1": ("TIMEFRAME_D1", 1440),
    }

    def __init__(
        self,
        db_path: Path,
        *,
        config: BackfillConfig,
        log_output: Callable[[str], None] | None = None,
        log_error: Callable[[str], None] | None = None,
    ) -> None:
        self.config = config
        self.db = AurumBoxMemoryDB(db_path, config.default_symbols)
        self.log_output = log_output or (lambda message: None)
        self.log_error = log_error or (lambda message: None)
        self.mt5_lock = threading.Lock()

    def list_symbols(self) -> dict[str, Any]:
        return {"ok": True, "symbols": self.db.list_symbols()}

    def list_timeframes(self) -> dict[str, Any]:
        return {"ok": True, "timeframes": list(self.TIMEFRAME_MAP.keys())}

    def summary(self) -> dict[str, Any]:
        payload = self.db.summary()
        payload.update(
            {
                "ok": True,
                "default_terminal_path": self.config.default_terminal_path,
                "default_days": self.config.default_days,
            }
        )
        return payload

    def clear_all_data(self) -> dict[str, Any]:
        try:
            response = self.db.clear_all_data()
            self.log_output("History backfill data cleared")
            return response
        except sqlite3.OperationalError as exc:
            self.log_error(f"History backfill clear failed | {exc}")
            return {"ok": False, "error": f"SQLite locked or unavailable: {exc}"}
        except Exception as exc:
            self.log_error(f"History backfill clear failed | {exc}\n{traceback.format_exc()}")
            return {"ok": False, "error": f"Could not clear historical data: {exc}"}

    def get_job_status(self, job_id: int) -> dict[str, Any]:
        job = self.db.get_job(job_id)
        if not job:
            return {"ok": False, "error": f"Backfill job {job_id} was not found."}
        return {"ok": True, "job": job, "items": self.db.list_job_items(job_id)}

    def start_backfill(self, payload: dict[str, Any]) -> dict[str, Any]:
        if mt5 is None:
            return {"ok": False, "error": "MetaTrader5 Python package is not installed."}
        symbols = payload.get("symbols") or [row["broker_symbol"] for row in self.db.list_symbols() if int(row.get("enabled", 1)) == 1]
        timeframes = payload.get("timeframes") or list(self.TIMEFRAME_MAP.keys())
        terminal_path = str(payload.get("terminal_path") or self.config.default_terminal_path).strip() or self.config.default_terminal_path
        try:
            from_date_text = str(payload.get("from_date") or "").strip() or (datetime.now(UTC) - timedelta(days=self.config.default_days)).date().isoformat()
            to_date_text = str(payload.get("to_date") or "").strip() or datetime.now(UTC).date().isoformat()
            from_date = to_utc_date_start(from_date_text)
            to_date = to_utc_date_end(to_date_text)
        except Exception:
            return {"ok": False, "error": "Invalid date range. Use YYYY-MM-DD values."}
        if to_date < from_date:
            return {"ok": False, "error": "Invalid date range. 'To date' must be on or after 'From date'."}
        cleaned_symbols = [str(item).strip() for item in symbols if str(item).strip()]
        cleaned_timeframes = [str(item).strip().upper() for item in timeframes if str(item).strip()]
        unsupported = [item for item in cleaned_timeframes if item not in self.TIMEFRAME_MAP]
        if unsupported:
            return {"ok": False, "error": f"Unsupported timeframe(s): {', '.join(unsupported)}"}
        if not cleaned_symbols:
            return {"ok": False, "error": "Select at least one symbol."}
        job_payload = {
            "terminal_path": terminal_path,
            "symbols": cleaned_symbols,
            "timeframes": cleaned_timeframes,
            "from_date": from_date.date().isoformat(),
            "to_date": to_date.date().isoformat(),
            "from_dt": from_date,
            "to_dt": to_date,
            "include_ticks": bool(payload.get("include_ticks")),
            "calculate_indicators": bool(payload.get("calculate_indicators", True)),
            "detect_ranges": bool(payload.get("detect_ranges", True)),
            "detect_liquidity_sweeps": bool(payload.get("detect_liquidity_sweeps", True)),
        }
        job_id = self.db.create_job(job_payload)
        thread = threading.Thread(target=self._run_job, args=(job_id, job_payload), daemon=True)
        thread.start()
        self.log_output(f"History backfill job queued | {json.dumps({'job_id': job_id, 'symbols': cleaned_symbols, 'timeframes': cleaned_timeframes, 'from': job_payload['from_date'], 'to': job_payload['to_date']}, ensure_ascii=True)}")
        return {"ok": True, "job_id": job_id}

    def _run_job(self, job_id: int, payload: dict[str, Any]) -> None:
        started_at = iso_now()
        self.db.update_job(job_id, status="running", started_at=started_at)
        totals = {
            "inserted_count": 0,
            "duplicates_skipped": 0,
            "failed_count": 0,
            "tick_inserted_count": 0,
            "progress_completed": 0,
            "progress_total": len(payload["symbols"]) * len(payload["timeframes"]),
            "last_error": "",
        }
        last_error = ""
        try:
            with self.mt5_lock:
                if not mt5.initialize(path=payload["terminal_path"]):
                    raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
                try:
                    for item in self.db.list_job_items(job_id):
                        item_id = int(item["id"])
                        symbol = str(item["symbol"])
                        timeframe = str(item["timeframe"]).upper()
                        self.db.update_job_item(item_id, status="running", started_at=iso_now(), last_error="")
                        try:
                            result = self._process_symbol_timeframe(
                                symbol=symbol,
                                timeframe=timeframe,
                                from_dt=payload["from_dt"],
                                to_dt=payload["to_dt"],
                                include_ticks=payload["include_ticks"],
                                calculate_indicators=payload["calculate_indicators"],
                                detect_ranges=payload["detect_ranges"],
                                detect_liquidity_sweeps=payload["detect_liquidity_sweeps"],
                            )
                            totals["inserted_count"] += result["inserted_rows"]
                            totals["duplicates_skipped"] += result["duplicates_skipped"]
                            totals["failed_count"] += result["failed_rows"]
                            totals["tick_inserted_count"] += result["tick_rows"]
                            self.db.update_job_item(
                                item_id,
                                status="completed",
                                fetched_rows=result["fetched_rows"],
                                inserted_rows=result["inserted_rows"],
                                duplicates_skipped=result["duplicates_skipped"],
                                failed_rows=result["failed_rows"],
                                tick_rows=result["tick_rows"],
                                completed_at=iso_now(),
                                last_error=result.get("last_error", ""),
                            )
                            self.log_output(
                                f"History backfill item completed | {json.dumps({'job_id': job_id, 'symbol': symbol, 'timeframe': timeframe, 'fetched_rows': result['fetched_rows'], 'inserted_rows': result['inserted_rows'], 'duplicates_skipped': result['duplicates_skipped'], 'tick_rows': result['tick_rows']}, ensure_ascii=True)}"
                            )
                        except Exception as exc:
                            last_error = str(exc)
                            totals["failed_count"] += 1
                            self.db.update_job_item(
                                item_id,
                                status="failed",
                                failed_rows=1,
                                completed_at=iso_now(),
                                last_error=last_error,
                            )
                            self.log_error(
                                f"History backfill item failed | {json.dumps({'job_id': job_id, 'symbol': symbol, 'timeframe': timeframe, 'error': last_error}, ensure_ascii=True)}\n{traceback.format_exc()}"
                            )
                        totals["progress_completed"] += 1
                        self.db.update_job(job_id, **totals)
                finally:
                    mt5.shutdown()
            final_status = "completed" if not last_error else "completed_with_errors"
            final_totals = dict(totals)
            final_totals["status"] = final_status
            final_totals["completed_at"] = iso_now()
            final_totals["last_error"] = last_error
            self.db.update_job(job_id, **final_totals)
        except Exception as exc:
            last_error = str(exc)
            failed_totals = dict(totals)
            failed_totals["status"] = "failed"
            failed_totals["completed_at"] = iso_now()
            failed_totals["last_error"] = last_error
            self.db.update_job(job_id, **failed_totals)
            self.log_error(f"History backfill job failed | {json.dumps({'job_id': job_id, 'error': last_error}, ensure_ascii=True)}\n{traceback.format_exc()}")

    def _process_symbol_timeframe(
        self,
        *,
        symbol: str,
        timeframe: str,
        from_dt: datetime,
        to_dt: datetime,
        include_ticks: bool,
        calculate_indicators: bool,
        detect_ranges: bool,
        detect_liquidity_sweeps: bool,
    ) -> dict[str, Any]:
        timeframe_attr, timeframe_minutes = self.TIMEFRAME_MAP[timeframe]
        timeframe_value = getattr(mt5, timeframe_attr, None)
        if timeframe_value is None:
            raise ValueError(f"Unsupported timeframe {timeframe}.")
        if not mt5.symbol_select(symbol, True):
            raise RuntimeError(f"Symbol not found or not selectable: {symbol}. MT5 last_error={mt5.last_error()}")
        rates = mt5.copy_rates_range(symbol, timeframe_value, from_dt, to_dt)
        if rates is None or len(rates) == 0:
            raise RuntimeError(f"No historical data returned for {symbol} {timeframe}. MT5 last_error={mt5.last_error()}")
        bars = [
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "time": int(rate["time"]),
                "datetime_utc": datetime.fromtimestamp(int(rate["time"]), UTC).isoformat(),
                "open": safe_float(rate["open"]),
                "high": safe_float(rate["high"]),
                "low": safe_float(rate["low"]),
                "close": safe_float(rate["close"]),
                "tick_volume": int(rate["tick_volume"]) if rate["tick_volume"] is not None else 0,
                "spread": int(rate["spread"]) if rate["spread"] is not None else 0,
                "real_volume": int(rate["real_volume"]) if rate["real_volume"] is not None else 0,
            }
            for rate in rates
        ]
        inserted_rows = self.db.insert_market_bars(bars)
        duplicates = max(0, len(bars) - inserted_rows)
        tick_rows = 0
        if include_ticks:
            ticks = mt5.copy_ticks_range(symbol, from_dt, to_dt, getattr(mt5, "COPY_TICKS_ALL", 0))
            if ticks is None:
                self.log_error(f"History backfill ticks missing | {json.dumps({'symbol': symbol, 'timeframe': timeframe, 'error': str(mt5.last_error())}, ensure_ascii=True)}")
            else:
                tick_payload = [
                    {
                        "symbol": symbol,
                        "time_msc": int(item["time_msc"]),
                        "datetime_utc": datetime.fromtimestamp(int(item["time"]), UTC).isoformat(),
                        "bid": safe_float(item["bid"]),
                        "ask": safe_float(item["ask"]),
                        "last": safe_float(item["last"]),
                        "volume": safe_float(item["volume"]),
                        "flags": int(item["flags"]),
                    }
                    for item in ticks
                ]
                tick_rows = self.db.insert_ticks(tick_payload)

        if bars and calculate_indicators:
            indicator_rows = self._build_indicator_rows(bars)
            self.db.replace_indicator_features(indicator_rows)
            ai_rows = [
                {
                    "symbol": row["symbol"],
                    "timeframe": row["timeframe"],
                    "time": row["time"],
                    "datetime_utc": row["datetime_utc"],
                    "feature_json": row,
                    "label_json": {"outcome": "unlabeled"},
                }
                for row in indicator_rows
            ]
            self.db.replace_ai_training_samples(ai_rows)
        if bars and detect_ranges:
            range_rows = self._build_range_rows(bars, timeframe_minutes)
            self.db.replace_range_states(range_rows)
        if bars and detect_liquidity_sweeps:
            level_rows, sweep_rows, setup_rows = self._build_liquidity_rows(bars, timeframe, timeframe_minutes)
            self.db.replace_liquidity_levels(level_rows)
            self.db.replace_liquidity_sweeps(sweep_rows)
            self.db.replace_strategy_setups(setup_rows)

        return {
            "fetched_rows": len(bars),
            "inserted_rows": inserted_rows,
            "duplicates_skipped": duplicates,
            "failed_rows": 0,
            "tick_rows": tick_rows,
            "last_error": "",
        }

    def _build_indicator_rows(self, bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
        closes = [safe_float(item["close"]) for item in bars]
        spreads = [safe_float(item.get("spread")) for item in bars]
        atr_values = atr_series(bars, 14)
        adx_values, plus_di_values, minus_di_values = adx_series(bars, 14)
        ema50_values = ema_series(closes, 50)
        bb_width_values = bollinger_width_series(closes, 20, 2.0)
        chop_values = chop_series(bars, 14)
        spread_sma = sma(spreads, 20)
        rows: list[dict[str, Any]] = []
        for index, bar in enumerate(bars):
            dt_value = datetime.fromisoformat(bar["datetime_utc"])
            open_price = safe_float(bar["open"])
            close_price = safe_float(bar["close"])
            high_price = safe_float(bar["high"])
            low_price = safe_float(bar["low"])
            body = abs(close_price - open_price)
            upper_wick = max(0.0, high_price - max(open_price, close_price))
            lower_wick = max(0.0, min(open_price, close_price) - low_price)
            ema50 = ema50_values[index]
            previous_ema50 = ema50_values[index - 1] if index > 0 else None
            rows.append(
                {
                    "symbol": bar["symbol"],
                    "timeframe": bar["timeframe"],
                    "time": bar["time"],
                    "datetime_utc": bar["datetime_utc"],
                    "atr": atr_values[index],
                    "adx": adx_values[index],
                    "plus_di": plus_di_values[index],
                    "minus_di": minus_di_values[index],
                    "ema50": ema50,
                    "ema_slope": (ema50 - previous_ema50) if ema50 is not None and previous_ema50 is not None else None,
                    "bollinger_band_width": bb_width_values[index],
                    "chop_index": chop_values[index],
                    "candle_body_size": body,
                    "upper_wick_size": upper_wick,
                    "lower_wick_size": lower_wick,
                    "wick_body_ratio": ((upper_wick + lower_wick) / body) if body > 0 else None,
                    "average_spread": spread_sma[index],
                    "session_label": session_label_for(dt_value),
                    "day_of_week": dt_value.weekday(),
                    "hour_of_day": dt_value.hour,
                }
            )
        return rows

    def _build_range_rows(self, bars: list[dict[str, Any]], timeframe_minutes: int) -> list[dict[str, Any]]:
        lookback = 24 if timeframe_minutes >= 60 else 36 if timeframe_minutes >= 15 else 48
        rows: list[dict[str, Any]] = []
        for index in range(len(bars)):
            if index < lookback - 1:
                continue
            window = bars[index - lookback + 1:index + 1]
            high_value = max(safe_float(item["high"]) for item in window)
            low_value = min(safe_float(item["low"]) for item in window)
            height = high_value - low_value
            midpoint = (high_value + low_value) / 2.0
            tolerance = max(height * 0.08, 0.01)
            top_touches = sum(1 for item in window if abs(safe_float(item["high"]) - high_value) <= tolerance)
            bottom_touches = sum(1 for item in window if abs(safe_float(item["low"]) - low_value) <= tolerance)
            current_close = safe_float(window[-1]["close"])
            if current_close > midpoint + height * 0.15:
                current_zone = "upper"
            elif current_close < midpoint - height * 0.15:
                current_zone = "lower"
            else:
                current_zone = "mid"
            breakout_status = "inside"
            if current_close > high_value + tolerance * 0.25:
                breakout_status = "breakout_up"
            elif current_close < low_value - tolerance * 0.25:
                breakout_status = "breakout_down"
            quality_score = min(100.0, max(0.0, top_touches * 8 + bottom_touches * 8 + (25.0 if height > 0 else 0.0)))
            rows.append(
                {
                    "symbol": bars[index]["symbol"],
                    "timeframe": bars[index]["timeframe"],
                    "time": bars[index]["time"],
                    "datetime_utc": bars[index]["datetime_utc"],
                    "range_high": high_value,
                    "range_low": low_value,
                    "range_midpoint": midpoint,
                    "range_height": height,
                    "top_touches": top_touches,
                    "bottom_touches": bottom_touches,
                    "range_quality_score": quality_score,
                    "current_zone": current_zone,
                    "breakout_status": breakout_status,
                    "invalidation_status": "valid" if breakout_status == "inside" else "watch",
                }
            )
        return rows

    def _build_liquidity_rows(
        self,
        bars: list[dict[str, Any]],
        timeframe: str,
        timeframe_minutes: int,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        if not bars:
            return [], [], []
        level_rows: list[dict[str, Any]] = []
        sweep_rows: list[dict[str, Any]] = []
        setup_rows: list[dict[str, Any]] = []
        tolerance = 0.05

        def append_level(bar: dict[str, Any], level_type: str, level_price: float, side: str, source_window: str, notes: str) -> None:
            level_rows.append(
                {
                    "symbol": bar["symbol"],
                    "timeframe": timeframe,
                    "time": bar["time"],
                    "datetime_utc": bar["datetime_utc"],
                    "level_type": level_type,
                    "level_price": round(level_price, 5),
                    "side": side,
                    "source_window": source_window,
                    "notes": notes,
                }
            )

        def append_sweep(
            bar: dict[str, Any],
            level_type: str,
            level_price: float,
            sweep_side: str,
            sweep_size: float,
            rejection_wick_ratio: float,
            displacement_confirmed: bool,
            mss_confirmed: bool,
            choch_confirmed: bool,
            notes: str,
        ) -> None:
            sweep_rows.append(
                {
                    "symbol": bar["symbol"],
                    "timeframe": timeframe,
                    "time": bar["time"],
                    "datetime_utc": bar["datetime_utc"],
                    "swept_level_type": level_type,
                    "swept_level_price": round(level_price, 5),
                    "sweep_side": sweep_side,
                    "sweep_size": sweep_size,
                    "close_back_confirmed": True,
                    "rejection_wick_ratio": rejection_wick_ratio,
                    "displacement_confirmed": displacement_confirmed,
                    "mss_confirmed": mss_confirmed,
                    "choch_confirmed": choch_confirmed,
                    "notes": notes,
                }
            )
            setup_rows.append(
                {
                    "symbol": bar["symbol"],
                    "timeframe": timeframe,
                    "time": bar["time"],
                    "datetime_utc": bar["datetime_utc"],
                    "setup_type": "liquidity_sweep_reversal",
                    "setup_side": sweep_side,
                    "confidence": 78 if displacement_confirmed else 64,
                    "notes": notes,
                    "payload": {
                        "level_type": level_type,
                        "level_price": level_price,
                        "mss_confirmed": mss_confirmed,
                        "choch_confirmed": choch_confirmed,
                    },
                }
            )

        previous_day_high: dict[str, float] = {}
        previous_day_low: dict[str, float] = {}
        by_day: dict[str, list[dict[str, Any]]] = {}
        for bar in bars:
            day_key = bar["datetime_utc"][:10]
            by_day.setdefault(day_key, []).append(bar)
        ordered_days = sorted(by_day)
        for index in range(1, len(ordered_days)):
            previous_rows = by_day[ordered_days[index - 1]]
            day_key = ordered_days[index]
            previous_day_high[day_key] = max(safe_float(item["high"]) for item in previous_rows)
            previous_day_low[day_key] = min(safe_float(item["low"]) for item in previous_rows)

        asia_by_day: dict[str, tuple[float, float]] = {}
        london_by_day: dict[str, tuple[float, float]] = {}
        for day_key, day_rows in by_day.items():
            asia_rows = [row for row in day_rows if 0 <= datetime.fromisoformat(row["datetime_utc"]).hour <= 6]
            london_rows = [row for row in day_rows if 7 <= datetime.fromisoformat(row["datetime_utc"]).hour <= 12]
            if asia_rows:
                asia_by_day[day_key] = (
                    max(safe_float(row["high"]) for row in asia_rows),
                    min(safe_float(row["low"]) for row in asia_rows),
                )
            if london_rows:
                london_by_day[day_key] = (
                    max(safe_float(row["high"]) for row in london_rows),
                    min(safe_float(row["low"]) for row in london_rows),
                )

        for index, bar in enumerate(bars):
            current_day = bar["datetime_utc"][:10]
            current_high = safe_float(bar["high"])
            current_low = safe_float(bar["low"])
            current_close = safe_float(bar["close"])
            current_open = safe_float(bar["open"])
            body = abs(current_close - current_open)
            upper_wick = max(0.0, current_high - max(current_open, current_close))
            lower_wick = max(0.0, min(current_open, current_close) - current_low)
            displacement_confirmed = body > max(0.08, (current_high - current_low) * 0.55)

            if current_day in previous_day_high:
                pdh = previous_day_high[current_day]
                pdl = previous_day_low[current_day]
                append_level(bar, "previous_day_high", pdh, "sell", "previous_day", "PDH reference")
                append_level(bar, "previous_day_low", pdl, "buy", "previous_day", "PDL reference")
                if current_high > pdh + tolerance and current_close <= pdh:
                    append_sweep(bar, "previous_day_high", pdh, "sell", current_high - pdh, (upper_wick / body) if body > 0 else 0.0, displacement_confirmed, True, False, "Price swept PDH and closed back below.")
                if current_low < pdl - tolerance and current_close >= pdl:
                    append_sweep(bar, "previous_day_low", pdl, "buy", pdl - current_low, (lower_wick / body) if body > 0 else 0.0, displacement_confirmed, True, False, "Price swept PDL and closed back above.")

            if current_day in asia_by_day:
                ash, asl = asia_by_day[current_day]
                append_level(bar, "asia_high", ash, "sell", "asia", "Asia high")
                append_level(bar, "asia_low", asl, "buy", "asia", "Asia low")
                if current_high > ash + tolerance and current_close <= ash:
                    append_sweep(bar, "asia_high", ash, "sell", current_high - ash, (upper_wick / body) if body > 0 else 0.0, displacement_confirmed, True, True, "Price swept Asia high and rejected.")
                if current_low < asl - tolerance and current_close >= asl:
                    append_sweep(bar, "asia_low", asl, "buy", asl - current_low, (lower_wick / body) if body > 0 else 0.0, displacement_confirmed, True, True, "Price swept Asia low and rejected.")

            if current_day in london_by_day:
                ldh, ldl = london_by_day[current_day]
                append_level(bar, "london_high", ldh, "sell", "london", "London high")
                append_level(bar, "london_low", ldl, "buy", "london", "London low")
                if current_high > ldh + tolerance and current_close <= ldh:
                    append_sweep(bar, "london_high", ldh, "sell", current_high - ldh, (upper_wick / body) if body > 0 else 0.0, displacement_confirmed, True, True, "Price swept London high and rejected.")
                if current_low < ldl - tolerance and current_close >= ldl:
                    append_sweep(bar, "london_low", ldl, "buy", ldl - current_low, (lower_wick / body) if body > 0 else 0.0, displacement_confirmed, True, True, "Price swept London low and rejected.")

            if timeframe in {"M5", "M15"} and 2 <= index < len(bars) - 2:
                previous_2 = bars[index - 2:index]
                next_2 = bars[index + 1:index + 3]
                if current_high > max(safe_float(item["high"]) for item in previous_2 + next_2):
                    append_level(bar, f"{timeframe.lower()}_swing_high", current_high, "sell", timeframe, f"{timeframe} swing high")
                if current_low < min(safe_float(item["low"]) for item in previous_2 + next_2):
                    append_level(bar, f"{timeframe.lower()}_swing_low", current_low, "buy", timeframe, f"{timeframe} swing low")
                if index >= 1:
                    previous_high = safe_float(bars[index - 1]["high"])
                    previous_low = safe_float(bars[index - 1]["low"])
                    if abs(current_high - previous_high) <= tolerance:
                        append_level(bar, f"{timeframe.lower()}_equal_high", current_high, "sell", timeframe, f"{timeframe} equal highs")
                    if abs(current_low - previous_low) <= tolerance:
                        append_level(bar, f"{timeframe.lower()}_equal_low", current_low, "buy", timeframe, f"{timeframe} equal lows")

        return level_rows, sweep_rows, setup_rows
