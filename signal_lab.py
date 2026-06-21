from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import math
import re
import sqlite3
import statistics
import tempfile
import unicodedata
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_now() -> str:
    return utc_now().isoformat()


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in ("", None):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return text.replace("\ufeff", "").strip()


def normalize_header(value: Any) -> str:
    text = normalize_text(value).lower()
    text = re.sub(r"[\s\-]+", "_", text)
    text = re.sub(r"[^a-z0-9_]", "", text)
    return text.strip("_")


def normalize_price_token(value: Any) -> tuple[float | None, str | None]:
    raw = normalize_text(value)
    if not raw:
        return None, None
    compact = raw.replace(",", "").replace(" ", "")
    compact = re.sub(r":00+$", "", compact)
    compact = compact.replace("—", "-").replace("–", "-")
    if re.search(r"[a-zA-Z]", compact):
        return None, raw
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", compact):
        return None, raw
    try:
        return float(compact), None
    except ValueError:
        return None, raw


def normalize_direction(value: Any) -> str:
    text = normalize_text(value).upper()
    if text in {"BUY", "SELL"}:
        return text
    return text


def parse_date_value(value: Any) -> datetime | None:
    text = normalize_text(value)
    if not text:
        return None
    formats = [
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%m/%d/%Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def parse_time_value(value: Any) -> time | None:
    text = normalize_text(value)
    if not text:
        return None
    text = re.sub(r"\s+", " ", text).strip()
    text_upper = text.upper().replace(".", "")
    formats = ["%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M%p"]
    for fmt in formats:
        try:
            return datetime.strptime(text_upper if "%p" in fmt else text, fmt).time()
        except ValueError:
            continue
    return None


def classify_session(dt_utc: datetime) -> str:
    hour = dt_utc.hour
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


def round_or_none(value: Any, digits: int = 5) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def ensure_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True)


def parse_json_text(value: Any, default: Any) -> Any:
    if value in ("", None):
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


@dataclass
class ParsedSignal:
    signal_id: str
    date_text: str
    time_text: str
    symbol: str
    direction: str
    entry: float | None
    limit_price: float | None
    stop_loss: float | None
    tps: list[float]
    raw_preview: str
    validation_status: str
    validation_errors: list[str]
    validation_warnings: list[str]
    broker_symbol: str


class SignalLabService:
    DEFAULT_SYMBOL_MAPPINGS = {
        "XAUUSD": "XAUUSDm",
    }

    TIMEFRAME_MAP = {
        "M1": ("TIMEFRAME_M1", 1),
        "M5": ("TIMEFRAME_M5", 5),
        "M15": ("TIMEFRAME_M15", 15),
        "H1": ("TIMEFRAME_H1", 16385),
    }

    EXIT_MODE_LABELS = {
        "TP1_ONLY": "TP1 only",
        "TP2_ONLY": "TP2 only",
        "TP3_ONLY": "TP3 only",
        "TP4_ONLY": "TP4 only",
        "TP1_BE_TP2": "TP1 then breakeven to TP2",
        "TP1_BE_TP3": "TP1 then breakeven to TP3",
        "CUSTOM_TP": "Custom TP",
        "MULTI_POSITION": "Multi-position",
    }

    def __init__(self, db: Any, mt5_module: Any, ensure_mt5_ready: Any, logger: Any) -> None:
        self.db = db
        self.mt5 = mt5_module
        self.ensure_mt5_ready = ensure_mt5_ready
        self.logger = logger
        self.log_buffer: list[dict[str, Any]] = []
        self._init_tables()

    def _log(self, message: str, **payload: Any) -> None:
        text = f"Signal Lab: {message}"
        if payload:
            text = f"{text} | {json.dumps(payload, ensure_ascii=True)}"
        try:
            self.logger(text)
        except Exception:
            pass
        self.log_buffer.append({"ts": iso_now(), "message": message, "payload": payload})
        self.log_buffer = self.log_buffer[-250:]

    def _init_tables(self) -> None:
        with self.db.lock, self.db.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS signal_import_batches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_name TEXT NOT NULL,
                    file_hash TEXT NOT NULL,
                    imported_at TEXT NOT NULL,
                    total_rows INTEGER NOT NULL DEFAULT 0,
                    valid_rows INTEGER NOT NULL DEFAULT 0,
                    invalid_rows INTEGER NOT NULL DEFAULT 0,
                    notes TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS signal_calls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_id INTEGER NOT NULL,
                    signal_id TEXT NOT NULL DEFAULT '',
                    date TEXT NOT NULL DEFAULT '',
                    time_gmt TEXT NOT NULL DEFAULT '',
                    symbol TEXT NOT NULL DEFAULT '',
                    broker_symbol TEXT NOT NULL DEFAULT '',
                    direction TEXT NOT NULL DEFAULT '',
                    entry REAL,
                    limit_price REAL,
                    stop_loss REAL,
                    tps_json TEXT NOT NULL DEFAULT '[]',
                    raw_preview TEXT NOT NULL DEFAULT '',
                    validation_status TEXT NOT NULL DEFAULT 'invalid',
                    validation_errors_json TEXT NOT NULL DEFAULT '[]',
                    validation_warnings_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(batch_id, signal_id, date, time_gmt, symbol, direction, entry)
                );

                CREATE TABLE IF NOT EXISTS signal_backtest_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    signal_call_id INTEGER NOT NULL,
                    entry_mode TEXT NOT NULL,
                    exit_model TEXT NOT NULL,
                    timeframe_used TEXT NOT NULL,
                    replay_start_time TEXT NOT NULL,
                    replay_end_time TEXT NOT NULL,
                    entry_filled INTEGER NOT NULL DEFAULT 0,
                    limit_filled INTEGER NOT NULL DEFAULT 0,
                    selected_entry_price REAL,
                    selected_exit_price REAL,
                    outcome TEXT NOT NULL DEFAULT '',
                    tp_hits_json TEXT NOT NULL DEFAULT '{}',
                    sl_hit INTEGER NOT NULL DEFAULT 0,
                    first_outcome TEXT NOT NULL DEFAULT '',
                    max_favorable_excursion REAL DEFAULT 0,
                    max_adverse_excursion REAL DEFAULT 0,
                    time_to_tp1 INTEGER,
                    time_to_tp2 INTEGER,
                    time_to_tp3 INTEGER,
                    time_to_tp4 INTEGER,
                    time_to_sl INTEGER,
                    balance_before REAL DEFAULT 0,
                    profit_loss REAL DEFAULT 0,
                    balance_after REAL DEFAULT 0,
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS signal_feature_analysis (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    signal_call_id INTEGER NOT NULL,
                    asian_high REAL,
                    asian_low REAL,
                    london_high REAL,
                    london_low REAL,
                    previous_day_high REAL,
                    previous_day_low REAL,
                    asian_high_swept INTEGER DEFAULT 0,
                    asian_low_swept INTEGER DEFAULT 0,
                    london_high_swept INTEGER DEFAULT 0,
                    london_low_swept INTEGER DEFAULT 0,
                    ema_20 REAL,
                    ema_50 REAL,
                    ema_bias TEXT NOT NULL DEFAULT '',
                    rsi REAL,
                    atr REAL,
                    vwap REAL,
                    vwap_position TEXT NOT NULL DEFAULT '',
                    round_number_distance REAL,
                    detected_setup TEXT NOT NULL DEFAULT 'Unknown',
                    confidence_score REAL DEFAULT 0,
                    notes TEXT NOT NULL DEFAULT '',
                    evidence_json TEXT NOT NULL DEFAULT '[]'
                );

                CREATE INDEX IF NOT EXISTS idx_signal_calls_batch_id ON signal_calls(batch_id);
                CREATE INDEX IF NOT EXISTS idx_signal_calls_validation_status ON signal_calls(validation_status);
                CREATE INDEX IF NOT EXISTS idx_signal_backtest_signal_call_id ON signal_backtest_results(signal_call_id);
                CREATE INDEX IF NOT EXISTS idx_signal_feature_signal_call_id ON signal_feature_analysis(signal_call_id);
                """
            )
            conn.commit()

    def list_logs(self) -> dict[str, Any]:
        return {"logs": list(self.log_buffer)}

    def get_symbol_mappings(self) -> dict[str, Any]:
        raw = self.db.get_setting("signal_lab_symbol_mappings", "")
        data = parse_json_text(raw, None)
        normalized = dict(self.DEFAULT_SYMBOL_MAPPINGS)
        if isinstance(data, dict):
            for imported_symbol, broker_symbol in data.items():
                imported = normalize_text(imported_symbol).upper()
                broker = normalize_text(broker_symbol)
                if imported and broker:
                    normalized[imported] = broker
        rows = [
            {"imported_symbol": imported_symbol, "broker_symbol": broker_symbol}
            for imported_symbol, broker_symbol in sorted(normalized.items())
        ]
        return {"ok": True, "mappings": rows}

    def save_symbol_mappings(self, mappings: list[dict[str, Any]]) -> dict[str, Any]:
        normalized: dict[str, str] = {}
        for item in mappings:
            if not isinstance(item, dict):
                continue
            imported = normalize_text(item.get("imported_symbol", "")).upper()
            broker = normalize_text(item.get("broker_symbol", ""))
            if imported and broker:
                normalized[imported] = broker
        if "XAUUSD" not in normalized:
            normalized["XAUUSD"] = self.DEFAULT_SYMBOL_MAPPINGS["XAUUSD"]
        self.db.set_setting("signal_lab_symbol_mappings", ensure_json(normalized))
        self._log("symbol mappings saved", mappings=normalized)
        return self.get_symbol_mappings()

    def test_symbol_mapping(self, imported_symbol: str, broker_symbol: str) -> dict[str, Any]:
        imported = normalize_text(imported_symbol).upper() or "XAUUSD"
        preferred = normalize_text(broker_symbol) or self.DEFAULT_SYMBOL_MAPPINGS.get(imported, "")
        resolution = self.resolve_symbol(imported, preferred)
        end = utc_now()
        start = end - timedelta(hours=2)
        candles, meta = self._fetch_candles_with_meta(resolution["broker_symbol"], start, end, "M1")
        ok = bool(candles)
        self._log(
            "symbol mapping test",
            imported_symbol=imported,
            resolved_broker_symbol=resolution["broker_symbol"],
            mapping_mode=resolution["mapping_mode"],
            candle_count=meta["count"],
            mt5_last_error=meta["last_error"],
        )
        return {
            "ok": ok,
            "imported_symbol": imported,
            "resolved_broker_symbol": resolution["broker_symbol"],
            "mapping_mode": resolution["mapping_mode"],
            "candle_count": meta["count"],
            "timeframe": "M1",
            "requested_start_time": start.isoformat(),
            "requested_end_time": end.isoformat(),
            "mt5_last_error": meta["last_error"],
            "message": (
                f"Mapping test succeeded: {imported} -> {resolution['broker_symbol']} returned {meta['count']} recent M1 candles."
                if ok
                else f"Mapping test failed: no recent M1 candles returned for {imported} -> {resolution['broker_symbol']}."
            ),
        }

    def list_batches(self) -> dict[str, Any]:
        with self.db.lock, self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, file_name, imported_at, total_rows, valid_rows, invalid_rows, notes
                FROM signal_import_batches
                ORDER BY imported_at DESC, id DESC
                """
            ).fetchall()
        return {
            "batches": [
                {
                    "id": row["id"],
                    "file_name": row["file_name"],
                    "imported_at": row["imported_at"],
                    "total_rows": row["total_rows"],
                    "valid_rows": row["valid_rows"],
                    "invalid_rows": row["invalid_rows"],
                    "notes": row["notes"],
                }
                for row in rows
            ]
        }

    def import_file(self, file_name: str, content_base64: str, allow_duplicates: bool = False) -> dict[str, Any]:
        self._log("import started", file_name=file_name)
        if not file_name.strip():
            return {"ok": False, "message": "A file name is required."}
        if not content_base64.strip():
            return {"ok": False, "message": "The uploaded file was empty."}
        ext = Path(file_name).suffix.lower()
        if ext not in {".csv", ".txt", ".xlsx"}:
            return {"ok": False, "message": "Unsupported file type. Use CSV, TXT, or XLSX."}
        try:
            raw_bytes = base64.b64decode(content_base64)
        except Exception:
            return {"ok": False, "message": "File upload could not be decoded."}
        if not raw_bytes:
            return {"ok": False, "message": "The uploaded file was empty."}

        file_hash = hashlib.sha256(raw_bytes).hexdigest()
        with self.db.lock, self.db.connect() as conn:
            dupe = conn.execute("SELECT id FROM signal_import_batches WHERE file_hash = ?", (file_hash,)).fetchone()
        if dupe and not allow_duplicates:
            existing_batch_id = int(dupe["id"])
            self._log("duplicate import blocked", file_name=file_name, batch_id=existing_batch_id)
            payload = self.get_batch_payload(existing_batch_id)
            payload.update(
                {
                    "ok": False,
                    "message": f"Duplicate file import detected. This file already exists as batch #{existing_batch_id}.",
                    "batch_id": existing_batch_id,
                }
            )
            return payload

        try:
            rows = self._parse_file(ext, raw_bytes)
        except zipfile.BadZipFile:
            self._log("import failed", stage="parse", file_type=ext, reason="bad_zip")
            return {"ok": False, "message": "The XLSX file could not be opened. It may be corrupted or not a real Excel file."}
        except ET.ParseError:
            self._log("import failed", stage="parse", file_type=ext, reason="xml_parse_error")
            return {"ok": False, "message": "The spreadsheet structure could not be parsed. Try exporting the file again and re-importing it."}
        except Exception as exc:
            self._log("import failed", stage="parse", file_type=ext, reason=str(exc))
            return {"ok": False, "message": f"Signal file parsing failed: {exc}"}
        if not rows:
            return {"ok": False, "message": "No rows could be parsed from the file."}
        self._log("file parsed", file_type=ext, rows=len(rows))

        existing_keys = self._load_existing_signal_keys()
        parsed_signals: list[ParsedSignal] = []
        batch_seen: set[str] = set()
        valid_rows = 0
        invalid_rows = 0

        for idx, row in enumerate(rows, start=1):
            parsed = self._normalize_row(row, idx, existing_keys, batch_seen)
            batch_key = self._signal_key(parsed)
            batch_seen.add(batch_key)
            parsed_signals.append(parsed)
            if parsed.validation_status == "valid":
                valid_rows += 1
            else:
                invalid_rows += 1

        now = iso_now()
        try:
            with self.db.lock, self.db.connect() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO signal_import_batches(file_name, file_hash, imported_at, total_rows, valid_rows, invalid_rows, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (file_name.strip(), file_hash, now, len(parsed_signals), valid_rows, invalid_rows, ""),
                )
                batch_id = int(cursor.lastrowid)
                conn.executemany(
                    """
                    INSERT INTO signal_calls(
                        batch_id, signal_id, date, time_gmt, symbol, broker_symbol, direction, entry, limit_price,
                        stop_loss, tps_json, raw_preview, validation_status, validation_errors_json,
                        validation_warnings_json, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            batch_id,
                            item.signal_id,
                            item.date_text,
                            item.time_text,
                            item.symbol,
                            item.broker_symbol,
                            item.direction,
                            item.entry,
                            item.limit_price,
                            item.stop_loss,
                            ensure_json(item.tps),
                            item.raw_preview,
                            item.validation_status,
                            ensure_json(item.validation_errors),
                            ensure_json(item.validation_warnings),
                            now,
                            now,
                        )
                        for item in parsed_signals
                    ],
                )
                conn.commit()
        except sqlite3.DatabaseError as exc:
            self._log("import failed", stage="database", reason=str(exc))
            return {"ok": False, "message": f"Signal import could not be saved to SQLite: {exc}"}

        self._log("signals stored", batch_id=batch_id, valid_rows=valid_rows, invalid_rows=invalid_rows)
        return {
            "ok": True,
            "batch_id": batch_id,
            "message": f"Imported {len(parsed_signals)} signal rows.",
            "total_rows": len(parsed_signals),
            "valid_rows": valid_rows,
            "invalid_rows": invalid_rows,
            **self.get_batch_payload(batch_id),
        }

    def import_raw_text(self, raw_text: str, source_name: str = "pasted_signals.txt") -> dict[str, Any]:
        text = normalize_text(raw_text)
        if not text:
            return {"ok": False, "message": "Paste some Telegram-style signal text first."}
        encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
        return self.import_file(source_name, encoded, allow_duplicates=True)

    def import_mt5_tester_logs(self, terminal_root: str = r"C:\MT5\JamesANabiah") -> dict[str, Any]:
        files_dir = self._discover_tester_files_dir(Path(terminal_root))
        if files_dir is None:
            return {"ok": False, "message": "Could not find MT5 tester output files. Run the EA in Strategy Tester first."}

        all_signals_path = files_dir / "all_signals_log.csv"
        summary_path = files_dir / "summary_log.txt"
        wins_path = files_dir / "wins_log.csv"
        losses_path = files_dir / "losses_log.csv"
        skipped_path = files_dir / "skipped_log.csv"

        if not all_signals_path.exists():
            return {"ok": False, "message": f"Could not find {all_signals_path.name} in {files_dir}."}

        self._log("tester import started", files_dir=str(files_dir))
        all_signals_text = all_signals_path.read_text(encoding="utf-8-sig", errors="replace")
        if not normalize_text(all_signals_text):
            return {"ok": False, "message": "The MT5 tester signal log is empty."}

        summary_text = summary_path.read_text(encoding="utf-8-sig", errors="replace") if summary_path.exists() else ""
        summary_meta = self._parse_tester_summary(summary_text)
        signal_rows = list(csv.DictReader(io.StringIO(all_signals_text)))
        if not signal_rows:
            return {"ok": False, "message": "No tester signal rows were found in all_signals_log.csv."}

        now = iso_now()
        file_hash = hashlib.sha256((all_signals_text + "\n" + summary_text).encode("utf-8")).hexdigest()
        valid_rows = 0
        invalid_rows = 0
        parsed_signals: list[dict[str, Any]] = []
        parsed_results: list[dict[str, Any]] = []
        previous_balance = safe_float(summary_meta.get("starting_balance"), 0.0)
        default_exit_model = self._summary_exit_model(summary_meta.get("tp_mode_used", "TP1"))

        for index, raw_row in enumerate(signal_rows, start=1):
            normalized_row = {normalize_header(key): normalize_text(value) for key, value in raw_row.items() if key is not None}
            signal_payload = self._tester_signal_to_payload(normalized_row, index)
            if signal_payload["validation_status"] == "valid":
                valid_rows += 1
            else:
                invalid_rows += 1
            parsed_signals.append(signal_payload)

            status_text = normalize_text(normalized_row.get("status")).upper()
            profit_loss = safe_float(normalized_row.get("profit"), 0.0)
            balance_after = safe_float(normalized_row.get("balance_after_trade"), previous_balance + profit_loss)
            balance_before = balance_after - profit_loss if balance_after or profit_loss else previous_balance
            result_payload = self._tester_result_to_payload(
                signal_payload,
                normalized_row,
                balance_before=balance_before,
                balance_after=balance_after,
                exit_model=default_exit_model,
                summary_meta=summary_meta,
            )
            parsed_results.append(result_payload)
            previous_balance = balance_after

        try:
            with self.db.lock, self.db.connect() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO signal_import_batches(file_name, file_hash, imported_at, total_rows, valid_rows, invalid_rows, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"mt5_tester::{all_signals_path.name}",
                        file_hash,
                        now,
                        len(parsed_signals),
                        valid_rows,
                        invalid_rows,
                        f"Imported from {files_dir}",
                    ),
                )
                batch_id = int(cursor.lastrowid)
                signal_call_ids: list[int] = []
                for signal_payload in parsed_signals:
                    result = conn.execute(
                        """
                        INSERT INTO signal_calls(
                            batch_id, signal_id, date, time_gmt, symbol, broker_symbol, direction, entry, limit_price,
                            stop_loss, tps_json, raw_preview, validation_status, validation_errors_json,
                            validation_warnings_json, created_at, updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            batch_id,
                            signal_payload["signal_id"],
                            signal_payload["date"],
                            signal_payload["time_gmt"],
                            signal_payload["symbol"],
                            signal_payload["broker_symbol"],
                            signal_payload["direction"],
                            signal_payload["entry"],
                            signal_payload["limit_price"],
                            signal_payload["stop_loss"],
                            ensure_json(signal_payload["tps"]),
                            signal_payload["raw_preview"],
                            signal_payload["validation_status"],
                            ensure_json(signal_payload["validation_errors"]),
                            ensure_json(signal_payload["validation_warnings"]),
                            now,
                            now,
                        ),
                    )
                    signal_call_ids.append(int(result.lastrowid))

                for signal_call_id, result_payload in zip(signal_call_ids, parsed_results):
                    conn.execute(
                        """
                        INSERT INTO signal_backtest_results(
                            signal_call_id, entry_mode, exit_model, timeframe_used, replay_start_time, replay_end_time,
                            entry_filled, limit_filled, selected_entry_price, selected_exit_price, outcome, tp_hits_json,
                            sl_hit, first_outcome, max_favorable_excursion, max_adverse_excursion, time_to_tp1, time_to_tp2,
                            time_to_tp3, time_to_tp4, time_to_sl, balance_before, profit_loss, balance_after, notes,
                            created_at, updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            signal_call_id,
                            result_payload["entry_mode"],
                            result_payload["exit_model"],
                            result_payload["timeframe_used"],
                            result_payload["replay_start_time"],
                            result_payload["replay_end_time"],
                            int(result_payload["entry_filled"]),
                            int(result_payload["limit_filled"]),
                            result_payload["selected_entry_price"],
                            result_payload["selected_exit_price"],
                            result_payload["outcome"],
                            ensure_json(result_payload["tp_hits"]),
                            int(result_payload["sl_hit"]),
                            result_payload["first_outcome"],
                            result_payload["max_favorable_excursion"],
                            result_payload["max_adverse_excursion"],
                            result_payload["time_to_tp1"],
                            result_payload["time_to_tp2"],
                            result_payload["time_to_tp3"],
                            result_payload["time_to_tp4"],
                            result_payload["time_to_sl"],
                            result_payload["balance_before"],
                            result_payload["profit_loss"],
                            result_payload["balance_after"],
                            result_payload["notes"],
                            now,
                            now,
                        ),
                    )
                conn.commit()
        except sqlite3.DatabaseError as exc:
            self._log("tester import failed", reason=str(exc))
            return {"ok": False, "message": f"Tester log import could not be saved to SQLite: {exc}"}

        self._log(
            "tester logs stored",
            batch_id=batch_id,
            valid_rows=valid_rows,
            invalid_rows=invalid_rows,
            wins_file_found=wins_path.exists(),
            losses_file_found=losses_path.exists(),
            skipped_file_found=skipped_path.exists(),
        )
        return {
            "ok": True,
            "batch_id": batch_id,
            "message": f"Imported {len(parsed_signals)} MT5 tester signal rows from {files_dir}.",
            "total_rows": len(parsed_signals),
            "valid_rows": valid_rows,
            "invalid_rows": invalid_rows,
            **self.get_batch_payload(batch_id),
        }

    def _discover_tester_files_dir(self, terminal_root: Path) -> Path | None:
        candidates: list[Path] = []
        direct = terminal_root / "MQL5" / "Files"
        if direct.exists():
            if (direct / "all_signals_log.csv").exists():
                candidates.append(direct)
        tester_root = terminal_root / "Tester"
        if tester_root.exists():
            for item in tester_root.glob("Agent-*"):
                files_dir = item / "MQL5" / "Files"
                if (files_dir / "all_signals_log.csv").exists():
                    candidates.append(files_dir)
        if not candidates:
            return None
        return max(candidates, key=lambda path: (path / "all_signals_log.csv").stat().st_mtime)

    def _parse_tester_summary(self, text: str) -> dict[str, str]:
        summary: dict[str, str] = {}
        for raw_line in text.splitlines():
            line = normalize_text(raw_line)
            if not line or ":" not in line:
                continue
            key, value = line.split(":", 1)
            summary[normalize_header(key)] = normalize_text(value)
        return summary

    def _summary_exit_model(self, tp_mode: str) -> str:
        mode = normalize_text(tp_mode).upper()
        if mode == "TP1":
            return "TP1_ONLY"
        if mode == "TP2":
            return "TP2_ONLY"
        if mode == "TP3":
            return "TP3_ONLY"
        if mode == "TP4":
            return "TP4_ONLY"
        return "TP1_ONLY"

    def _tester_signal_to_payload(self, row: dict[str, Any], index: int) -> dict[str, Any]:
        signal_dt = normalize_text(row.get("signal_datetime"))
        date_text = ""
        time_text = ""
        if signal_dt:
            try:
                parsed_dt = datetime.strptime(signal_dt, "%Y.%m.%d %H:%M").replace(tzinfo=UTC)
                date_text = parsed_dt.strftime("%Y-%m-%d")
                time_text = parsed_dt.strftime("%H:%M")
            except ValueError:
                pass

        symbol = normalize_text(row.get("symbol")).upper()
        direction = normalize_direction(row.get("final_direction") or row.get("original_direction"))
        entry, entry_bad = normalize_price_token(row.get("entry_price"))
        limit_price, limit_bad = normalize_price_token(row.get("limit_price"))
        stop_loss, stop_bad = normalize_price_token(row.get("stop_loss"))
        selected_tp, tp_bad = normalize_price_token(row.get("selected_tp"))
        validation_errors: list[str] = []
        validation_warnings: list[str] = []

        if not date_text:
            validation_errors.append("Invalid signal datetime")
        if not symbol:
            validation_errors.append("Missing symbol")
        if direction not in {"BUY", "SELL"}:
            validation_errors.append("Direction must be BUY or SELL")
        if entry is None or entry_bad:
            validation_errors.append(f"Invalid entry price: {entry_bad or row.get('entry_price')}")
        if stop_loss is None or stop_bad:
            validation_errors.append(f"Invalid stop loss: {stop_bad or row.get('stop_loss')}")
        if selected_tp is None or tp_bad:
            validation_errors.append(f"Invalid selected TP: {tp_bad or row.get('selected_tp')}")
        if limit_bad:
            validation_errors.append(f"Invalid limit price: {limit_bad}")

        raw_preview = ensure_json(row)
        return {
            "signal_id": normalize_text(row.get("signal_number") or index),
            "date": date_text,
            "time_gmt": time_text,
            "symbol": "XAUUSD" if symbol.startswith("XAUUSD") else symbol,
            "broker_symbol": symbol or "XAUUSDm",
            "direction": direction,
            "entry": entry,
            "limit_price": limit_price,
            "stop_loss": stop_loss,
            "tps": [selected_tp] if selected_tp is not None else [],
            "raw_preview": raw_preview,
            "validation_status": "invalid" if validation_errors else "valid",
            "validation_errors": validation_errors,
            "validation_warnings": validation_warnings,
        }

    def _tester_result_to_payload(
        self,
        signal_payload: dict[str, Any],
        row: dict[str, Any],
        *,
        balance_before: float,
        balance_after: float,
        exit_model: str,
        summary_meta: dict[str, str],
    ) -> dict[str, Any]:
        status = normalize_text(row.get("status")).upper()
        reason = normalize_text(row.get("reason"))
        trigger_time = normalize_text(row.get("trigger_time"))
        exit_time = normalize_text(row.get("exit_time"))
        entry_execution_price, _ = normalize_price_token(row.get("entry_execution_price"))
        exit_price, _ = normalize_price_token(row.get("exit_price"))
        selected_tp = signal_payload["tps"][0] if signal_payload["tps"] else None
        profit_loss = safe_float(row.get("profit"), 0.0)

        entry_filled = bool(trigger_time) and status not in {"SKIPPED", "NO_FILL"}
        limit_filled = entry_filled and signal_payload.get("limit_price") is not None
        sl_hit = status in {"SL_HIT", "STOP_LOSS", "SL"}
        tp_hit = status in {"TP_HIT", "TP1_HIT", "TP"}
        if tp_hit:
            outcome = "TP1"
            first_outcome = "TP1"
        elif sl_hit:
            outcome = "SL"
            first_outcome = "SL"
        elif status == "SKIPPED":
            outcome = "SKIPPED"
            first_outcome = "NO_FILL"
        elif status == "EXPIRED":
            outcome = "EXPIRED"
            first_outcome = "EXPIRED"
        else:
            outcome = status or "UNKNOWN"
            first_outcome = outcome

        time_to_target = self._seconds_between(trigger_time, exit_time) if trigger_time and exit_time else None
        notes = {
            "reason": reason,
            "summary_entry_mode": summary_meta.get("entry_mode", ""),
            "summary_symbol": summary_meta.get("symbol_used", ""),
            "status": status,
        }
        return {
            "entry_mode": normalize_text(summary_meta.get("entry_mode", "MT5_TESTER")) or "MT5_TESTER",
            "exit_model": exit_model,
            "timeframe_used": "MT5_TESTER",
            "replay_start_time": signal_payload["date"] + "T" + signal_payload["time_gmt"] if signal_payload["date"] and signal_payload["time_gmt"] else "",
            "replay_end_time": exit_time or "",
            "entry_filled": entry_filled,
            "limit_filled": limit_filled,
            "selected_entry_price": entry_execution_price if entry_execution_price is not None else signal_payload.get("entry"),
            "selected_exit_price": exit_price if exit_price is not None else selected_tp,
            "outcome": outcome,
            "tp_hits": {"tp1": tp_hit},
            "sl_hit": sl_hit,
            "first_outcome": first_outcome,
            "max_favorable_excursion": None,
            "max_adverse_excursion": None,
            "time_to_tp1": time_to_target if tp_hit else None,
            "time_to_tp2": None,
            "time_to_tp3": None,
            "time_to_tp4": None,
            "time_to_sl": time_to_target if sl_hit else None,
            "balance_before": balance_before,
            "profit_loss": profit_loss,
            "balance_after": balance_after,
            "notes": ensure_json(notes),
        }

    def _seconds_between(self, start_text: str, end_text: str) -> int | None:
        try:
            start_dt = datetime.strptime(start_text, "%Y.%m.%d %H:%M:%S").replace(tzinfo=UTC)
            end_dt = datetime.strptime(end_text, "%Y.%m.%d %H:%M:%S").replace(tzinfo=UTC)
        except ValueError:
            return None
        return max(0, int((end_dt - start_dt).total_seconds()))

    def reset_results(self, batch_id: int) -> dict[str, Any]:
        with self.db.lock, self.db.connect() as conn:
            signal_ids = conn.execute("SELECT id FROM signal_calls WHERE batch_id = ?", (batch_id,)).fetchall()
            ids = [int(row["id"]) for row in signal_ids]
            if ids:
                placeholders = ",".join("?" for _ in ids)
                conn.execute(f"DELETE FROM signal_backtest_results WHERE signal_call_id IN ({placeholders})", ids)
                conn.execute(f"DELETE FROM signal_feature_analysis WHERE signal_call_id IN ({placeholders})", ids)
                conn.commit()
        self._log("results reset", batch_id=batch_id)
        payload = self.get_batch_payload(batch_id)
        payload["ok"] = True
        payload["message"] = "Current Signal Lab test results were cleared."
        return payload

    def clear_all_batches(self) -> dict[str, Any]:
        with self.db.lock, self.db.connect() as conn:
            conn.execute("DELETE FROM signal_feature_analysis")
            conn.execute("DELETE FROM signal_backtest_results")
            conn.execute("DELETE FROM signal_calls")
            conn.execute("DELETE FROM signal_import_batches")
            conn.commit()
        self.log_buffer.clear()
        self._log("all batches cleared")
        return {"ok": True, "message": "All imported Signal Lab batches were cleared."}

    def _parse_file(self, ext: str, raw_bytes: bytes) -> list[dict[str, Any]]:
        if ext in {".csv", ".txt"}:
            text = raw_bytes.decode("utf-8-sig", errors="replace")
            parsed_telegram = self._parse_telegram_text(text)
            if parsed_telegram:
                return parsed_telegram
            return self._parse_delimited_text(text)
        return self._parse_xlsx(raw_bytes)

    def _parse_telegram_text(self, text: str) -> list[dict[str, Any]]:
        if "ENTRY" not in text.upper() or "TP1" not in text.upper():
            return []
        cleaned = unicodedata.normalize("NFKC", text).replace("\r\n", "\n")
        cleaned = re.sub(r"[\u200b\u00a0]", " ", cleaned)
        lines = [line.strip() for line in cleaned.splitlines()]
        blocks: list[list[str]] = []
        current: list[str] = []

        def is_signal_start(value: str) -> bool:
            return bool(
                re.match(
                    r"^\s*(?:\d+\.\s*)?\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s*:\s*\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?\s*$",
                    value,
                )
            )

        for line in lines:
            if not line:
                continue
            if is_signal_start(line):
                if current:
                    blocks.append(current)
                current = [line]
                continue
            if current:
                current.append(line)
        if current:
            blocks.append(current)

        parsed_rows: list[dict[str, Any]] = []
        signal_counter = 1
        for block in blocks:
            joined = " ".join(block)
            if "ENTRY" not in joined.upper():
                continue

            date_line = block[0]
            header_line = next((line for line in block if "ENTRY" in line.upper()), joined)
            date_match = re.search(
                r"(?P<day>\d{1,2})(?:st|nd|rd|th)?\s+(?P<month>[A-Za-z]+)\s*:\s*(?P<time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)",
                date_line,
            )
            current_date = self._normalize_telegram_date(date_match.group("day"), date_match.group("month")) if date_match else ""
            current_time = self._normalize_telegram_time(date_match.group("time")) if date_match else ""

            compact = re.sub(r"\s+", " ", header_line)
            entry_match = re.search(
                r"(?P<symbol>[A-Za-z0-9\.]+)\s+ENTRY\s*:\s*(?P<direction>BUY|SELL)\s+(?P<entry>[-\d\.:]+)(?:\s+LIMIT\s+(?P<limit>[-\d\.:A-Za-z]+))?",
                compact,
                flags=re.IGNORECASE,
            )
            sl_match = re.search(r"(?:STOP\s+LOSS|SL)\s*:\s*(?P<sl>[-\d\.:A-Za-z]+)", joined, flags=re.IGNORECASE)
            tp_matches = re.findall(r"TP(?P<idx>\d+)\s*:\s*(?P<price>[-\d\.:A-Za-z]+)", joined, flags=re.IGNORECASE)
            if not entry_match:
                continue
            row: dict[str, Any] = {
                "signal_id": str(signal_counter),
                "date": current_date,
                "time_gmt": current_time,
                "symbol": normalize_text(entry_match.group("symbol")).upper(),
                "direction": normalize_text(entry_match.group("direction")).upper(),
                "entry": normalize_text(entry_match.group("entry")),
                "limit_price": normalize_text(entry_match.group("limit") or ""),
                "stop_loss": normalize_text(sl_match.group("sl") if sl_match else ""),
                "raw_preview": joined,
            }
            for idx, price in tp_matches:
                row[f"tp{idx}"] = normalize_text(price)
            parsed_rows.append(row)
            signal_counter += 1
        return parsed_rows

    def _normalize_telegram_date(self, day_text: str, month_text: str) -> str:
        year = utc_now().year
        month_map = {
            "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
            "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
        }
        month = month_map.get(normalize_text(month_text).lower(), 1)
        day = max(1, min(31, int(day_text)))
        return f"{year:04d}-{month:02d}-{day:02d}"

    def _normalize_telegram_time(self, time_text: str) -> str:
        parsed = parse_time_value(time_text)
        return parsed.strftime("%H:%M") if parsed else normalize_text(time_text)

    def _parse_delimited_text(self, text: str) -> list[dict[str, Any]]:
        if not text.strip():
            return []
        sample = text[:2048]
        delimiter = ","
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            delimiter = dialect.delimiter
        except csv.Error:
            delimiter = "," if "," in sample else "\t"
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        rows: list[dict[str, Any]] = []
        for raw_row in reader:
            if raw_row is None:
                continue
            normalized = {normalize_header(key): normalize_text(value) for key, value in raw_row.items() if key is not None}
            if not any(str(value).strip() for value in normalized.values()):
                continue
            rows.append(normalized)
        return rows

    def _parse_xlsx(self, raw_bytes: bytes) -> list[dict[str, Any]]:
        with zipfile.ZipFile(io.BytesIO(raw_bytes)) as archive:
            shared_strings: list[str] = []
            if "xl/sharedStrings.xml" in archive.namelist():
                root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
                ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                for si in root.findall("a:si", ns):
                    parts = [node.text or "" for node in si.findall(".//a:t", ns)]
                    shared_strings.append("".join(parts))

            workbook = ET.fromstring(archive.read("xl/workbook.xml"))
            rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
            ns_main = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            ns_rel = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
            first_sheet = workbook.find("a:sheets/a:sheet", ns_main)
            if first_sheet is None:
                return []
            rel_id = first_sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id", "")
            target = None
            for rel in rels.findall("r:Relationship", ns_rel):
                if rel.attrib.get("Id") == rel_id:
                    target = rel.attrib.get("Target")
                    break
            if not target:
                return []
            sheet_path = f"xl/{target.lstrip('/')}"
            sheet_root = ET.fromstring(archive.read(sheet_path))
            rows: list[list[str]] = []
            for row in sheet_root.findall(".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row"):
                values: list[str] = []
                expected_index = 0
                for cell in row.findall("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c"):
                    ref = cell.attrib.get("r", "")
                    column_letters = re.sub(r"\d", "", ref)
                    if column_letters:
                        col_index = self._column_index(column_letters)
                        while expected_index < col_index:
                            values.append("")
                            expected_index += 1
                    cell_type = cell.attrib.get("t", "")
                    value_node = cell.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v")
                    text_value = value_node.text if value_node is not None else ""
                    if cell_type == "s" and text_value.isdigit():
                        idx = int(text_value)
                        values.append(shared_strings[idx] if 0 <= idx < len(shared_strings) else "")
                    else:
                        values.append(text_value or "")
                    expected_index += 1
                rows.append(values)
            if not rows:
                return []
            headers = [normalize_header(cell) for cell in rows[0]]
            parsed: list[dict[str, Any]] = []
            for row in rows[1:]:
                if not any(normalize_text(item) for item in row):
                    continue
                item = {}
                for idx, header in enumerate(headers):
                    if not header:
                        continue
                    item[header] = normalize_text(row[idx] if idx < len(row) else "")
                parsed.append(item)
            return parsed

    def _column_index(self, letters: str) -> int:
        result = 0
        for char in letters.upper():
            result = result * 26 + (ord(char) - 64)
        return result - 1

    def _load_existing_signal_keys(self) -> set[str]:
        with self.db.lock, self.db.connect() as conn:
            rows = conn.execute(
                "SELECT date, time_gmt, symbol, direction, entry FROM signal_calls WHERE validation_status = 'valid'"
            ).fetchall()
        keys = set()
        for row in rows:
            keys.add(
                self._signal_key(
                    ParsedSignal(
                        signal_id="",
                        date_text=row["date"],
                        time_text=row["time_gmt"],
                        symbol=row["symbol"],
                        direction=row["direction"],
                        entry=row["entry"],
                        limit_price=None,
                        stop_loss=None,
                        tps=[],
                        raw_preview="",
                        validation_status="valid",
                        validation_errors=[],
                        validation_warnings=[],
                        broker_symbol="",
                    )
                )
            )
        return keys

    def _signal_key(self, signal: ParsedSignal) -> str:
        entry_key = "" if signal.entry is None else f"{signal.entry:.5f}"
        return "|".join([signal.date_text, signal.time_text, signal.symbol.upper(), signal.direction.upper(), entry_key])

    def _normalize_row(self, row: dict[str, Any], index: int, existing_keys: set[str], batch_seen: set[str]) -> ParsedSignal:
        signal_id = normalize_text(row.get("signal_id") or row.get("id") or index)
        date_text = normalize_text(row.get("date"))
        time_text = normalize_text(row.get("time_gmt") or row.get("time"))
        symbol = normalize_text(row.get("symbol")).upper()
        direction = normalize_direction(row.get("direction"))
        entry, entry_bad = normalize_price_token(row.get("entry"))
        limit_price, limit_bad = normalize_price_token(row.get("limit_price") or row.get("limit"))
        stop_loss, sl_bad = normalize_price_token(row.get("stop_loss") or row.get("sl"))
        raw_preview = normalize_text(row.get("raw_preview") or " | ".join(f"{key}={value}" for key, value in row.items()))

        tps: list[float] = []
        missing_tp_gap = False
        last_seen_tp = 0
        for tp_index in range(1, 9):
            tp_key = f"tp{tp_index}"
            if tp_key in row and normalize_text(row.get(tp_key)):
                tp_value, tp_bad = normalize_price_token(row.get(tp_key))
                if tp_bad:
                    tps.append(math.nan)
                else:
                    tps.append(tp_value if tp_value is not None else math.nan)
                if last_seen_tp and tp_index > last_seen_tp + 1:
                    missing_tp_gap = True
                last_seen_tp = tp_index

        validation_errors: list[str] = []
        validation_warnings: list[str] = []

        dt_date = parse_date_value(date_text)
        dt_time = parse_time_value(time_text)
        if dt_date is None:
            validation_errors.append("Invalid date format")
        if dt_time is None:
            validation_errors.append("Invalid time format")
        if not symbol:
            validation_errors.append("Missing symbol")
        if direction not in {"BUY", "SELL"}:
            validation_errors.append("Direction must be BUY or SELL")
        if entry_bad:
            validation_errors.append(f"Invalid entry price: {entry_bad}")
        if sl_bad:
            validation_errors.append(f"Invalid stop loss: {sl_bad}")
        if limit_bad:
            validation_errors.append(f"Invalid limit price: {limit_bad}")
        if entry is None:
            validation_errors.append("Entry must be numeric")
        if stop_loss is None:
            validation_errors.append("Stop loss must be numeric")

        clean_tps: list[float] = []
        for idx, tp in enumerate(tps, start=1):
            if math.isnan(tp):
                validation_errors.append(f"Invalid TP{idx}")
            else:
                clean_tps.append(tp)
        if not clean_tps:
            validation_errors.append("At least TP1 is required")
        if missing_tp_gap:
            validation_errors.append("Missing TP levels in the middle of the ladder")

        if dt_date and dt_time:
            dt_full = datetime.combine(dt_date.date(), dt_time, tzinfo=UTC)
            if dt_full.weekday() >= 5:
                validation_warnings.append("Weekend date selected. Market may be closed.")
        else:
            dt_full = None

        if direction == "BUY" and entry is not None and stop_loss is not None:
            if stop_loss >= entry:
                validation_errors.append("BUY signal has SL above or equal to entry")
            for idx, tp in enumerate(clean_tps, start=1):
                if tp <= entry:
                    validation_errors.append(f"BUY signal has TP{idx} below or equal to entry")
            if limit_price is not None and limit_price > entry:
                validation_warnings.append("BUY limit is above entry; treating entry and limit as an entry zone")
        if direction == "SELL" and entry is not None and stop_loss is not None:
            if stop_loss <= entry:
                validation_errors.append("SELL signal has SL below or equal to entry")
            for idx, tp in enumerate(clean_tps, start=1):
                if tp >= entry:
                    validation_errors.append(f"SELL signal has TP{idx} above or equal to entry")
            if limit_price is not None and limit_price < entry:
                validation_warnings.append("SELL limit is below entry; treating entry and limit as an entry zone")

        broker_symbol = symbol
        if symbol:
            resolution = self.resolve_symbol(symbol)
            broker_symbol = resolution["broker_symbol"] or symbol
            if broker_symbol != symbol:
                validation_warnings.append(f"Mapped {symbol} to broker symbol {broker_symbol} ({resolution['mapping_mode']})")

        signal = ParsedSignal(
            signal_id=signal_id,
            date_text=date_text,
            time_text=time_text,
            symbol=symbol,
            direction=direction,
            entry=entry,
            limit_price=limit_price,
            stop_loss=stop_loss,
            tps=clean_tps,
            raw_preview=raw_preview,
            validation_status="valid",
            validation_errors=validation_errors,
            validation_warnings=validation_warnings,
            broker_symbol=broker_symbol,
        )
        key = self._signal_key(signal)
        if key in batch_seen:
            signal.validation_errors.append("Duplicate signal within current import batch")
        elif key in existing_keys:
            signal.validation_warnings.append("Signal already exists in an earlier batch")

        if entry is not None and clean_tps:
            distances = [abs(tp - entry) for tp in clean_tps]
            if len(distances) >= 4:
                baseline = statistics.median(distances[: min(3, len(distances))]) or 0.0
                if baseline > 0 and distances[3] > baseline * 3:
                    signal.validation_errors.append("Suspicious TP4 distance")
            if len(distances) >= 2:
                steps = [abs(clean_tps[idx] - clean_tps[idx - 1]) for idx in range(1, len(clean_tps))]
                if steps and max(steps) > (statistics.median(steps) or 1) * 4:
                    signal.validation_warnings.append("Suspicious TP ladder spacing")

        signal.validation_status = "invalid" if signal.validation_errors else "valid"
        return signal

    def map_symbol(self, imported_symbol: str) -> str:
        return self.resolve_symbol(imported_symbol)["broker_symbol"]

    def resolve_symbol(self, imported_symbol: str, preferred_broker_symbol: str = "") -> dict[str, Any]:
        imported = normalize_text(imported_symbol).upper()
        preferred = normalize_text(preferred_broker_symbol)
        if not imported:
            return {"imported_symbol": "", "broker_symbol": "", "mapping_mode": "none", "manual": False}

        mappings = {item["imported_symbol"]: item["broker_symbol"] for item in self.get_symbol_mappings()["mappings"]}
        manual_target = normalize_text(mappings.get(imported, "")) or preferred
        if self.mt5 is None or not self.ensure_mt5_ready():
            return {
                "imported_symbol": imported,
                "broker_symbol": manual_target or imported,
                "mapping_mode": "manual" if manual_target else "unresolved",
                "manual": bool(manual_target),
            }

        try:
            if manual_target:
                info = self.mt5.symbol_info(manual_target)
                if info is not None:
                    try:
                        self.mt5.symbol_select(manual_target, True)
                    except Exception:
                        pass
                    return {
                        "imported_symbol": imported,
                        "broker_symbol": manual_target,
                        "mapping_mode": "manual",
                        "manual": True,
                        "visible": bool(getattr(info, "visible", False)),
                    }

            exact = self.mt5.symbol_info(imported)
            if exact is not None:
                return {
                    "imported_symbol": imported,
                    "broker_symbol": imported,
                    "mapping_mode": "exact",
                    "manual": False,
                    "visible": bool(getattr(exact, "visible", False)),
                }

            matches = list(self.mt5.symbols_get(f"*{imported}*") or [])
            if not matches and imported == "XAUUSD":
                matches = list(self.mt5.symbols_get("*GOLD*") or [])
            if matches:
                def score(item: Any) -> tuple[int, int, int, int]:
                    name = str(getattr(item, "name", ""))
                    upper = name.upper()
                    visible = 1 if bool(getattr(item, "visible", False)) else 0
                    exactish = 1 if upper == imported else 0
                    starts = 1 if upper.startswith(imported) else 0
                    contains = 1 if imported in upper else 0
                    return (visible, exactish, starts, contains)

                chosen = sorted(matches, key=score, reverse=True)[0]
                chosen_name = str(getattr(chosen, "name", imported))
                try:
                    self.mt5.symbol_select(chosen_name, True)
                except Exception:
                    pass
                return {
                    "imported_symbol": imported,
                    "broker_symbol": chosen_name,
                    "mapping_mode": "auto-detected",
                    "manual": False,
                    "visible": bool(getattr(chosen, "visible", False)),
                }
        except Exception:
            pass

        return {
            "imported_symbol": imported,
            "broker_symbol": manual_target or imported,
            "mapping_mode": "fallback-manual" if manual_target else "unresolved",
            "manual": bool(manual_target),
        }

    def get_batch_payload(self, batch_id: int) -> dict[str, Any]:
        with self.db.lock, self.db.connect() as conn:
            batch = conn.execute("SELECT * FROM signal_import_batches WHERE id = ?", (batch_id,)).fetchone()
            signals = conn.execute(
                """
                SELECT id, signal_id, date, time_gmt, symbol, broker_symbol, direction, entry, limit_price,
                       stop_loss, tps_json, raw_preview, validation_status, validation_errors_json, validation_warnings_json
                FROM signal_calls
                WHERE batch_id = ?
                ORDER BY date ASC, time_gmt ASC, id ASC
                """,
                (batch_id,),
            ).fetchall()
            results = conn.execute(
                """
                SELECT r.*, s.signal_id, s.date, s.time_gmt, s.symbol, s.direction, s.entry, s.limit_price, s.stop_loss, s.tps_json
                FROM signal_backtest_results r
                JOIN signal_calls s ON s.id = r.signal_call_id
                WHERE s.batch_id = ?
                ORDER BY s.date ASC, s.time_gmt ASC, r.id ASC
                """,
                (batch_id,),
            ).fetchall()
            features = conn.execute(
                """
                SELECT f.*, s.id as signal_call_id, s.signal_id, s.date, s.time_gmt, s.symbol, s.direction
                FROM signal_feature_analysis f
                JOIN signal_calls s ON s.id = f.signal_call_id
                WHERE s.batch_id = ?
                """,
                (batch_id,),
            ).fetchall()

        signal_rows = [self._row_to_signal_payload(row) for row in signals]
        result_rows = [self._row_to_result_payload(row) for row in results]
        feature_rows = [self._row_to_feature_payload(row) for row in features]
        analytics = self._build_analytics(signal_rows, result_rows, feature_rows)
        return {
            "batch": dict(batch) if batch else None,
            "signals": signal_rows,
            "valid_signals": [row for row in signal_rows if row["validation_status"] == "valid"],
            "invalid_signals": [row for row in signal_rows if row["validation_status"] != "valid"],
            "results": result_rows,
            "features": feature_rows,
            "analytics": analytics,
            "symbol_mappings": self.get_symbol_mappings()["mappings"],
            "logs": list(self.log_buffer),
        }

    def _row_to_signal_payload(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "signal_id": row["signal_id"],
            "date": row["date"],
            "time_gmt": row["time_gmt"],
            "imported_symbol": row["symbol"],
            "symbol": row["symbol"],
            "broker_symbol": row["broker_symbol"],
            "direction": row["direction"],
            "entry": row["entry"],
            "limit_price": row["limit_price"],
            "stop_loss": row["stop_loss"],
            "tps": parse_json_text(row["tps_json"], []),
            "raw_preview": row["raw_preview"],
            "validation_status": row["validation_status"],
            "validation_errors": parse_json_text(row["validation_errors_json"], []),
            "validation_warnings": parse_json_text(row["validation_warnings_json"], []),
            "session": classify_session(self._signal_datetime(row["date"], row["time_gmt"])) if self._signal_datetime(row["date"], row["time_gmt"]) else "Unknown",
        }

    def _row_to_result_payload(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "signal_call_id": row["signal_call_id"],
            "signal_id": row["signal_id"],
            "date": row["date"],
            "time_gmt": row["time_gmt"],
            "symbol": row["symbol"],
            "direction": row["direction"],
            "entry": row["entry"],
            "limit_price": row["limit_price"],
            "stop_loss": row["stop_loss"],
            "tps": parse_json_text(row["tps_json"], []),
            "entry_mode": row["entry_mode"],
            "exit_model": row["exit_model"],
            "timeframe_used": row["timeframe_used"],
            "entry_filled": bool(row["entry_filled"]),
            "limit_filled": bool(row["limit_filled"]),
            "selected_entry_price": row["selected_entry_price"],
            "selected_exit_price": row["selected_exit_price"],
            "outcome": row["outcome"],
            "tp_hits": parse_json_text(row["tp_hits_json"], {}),
            "sl_hit": bool(row["sl_hit"]),
            "first_outcome": row["first_outcome"],
            "max_favorable_excursion": row["max_favorable_excursion"],
            "max_adverse_excursion": row["max_adverse_excursion"],
            "time_to_tp1": row["time_to_tp1"],
            "time_to_tp2": row["time_to_tp2"],
            "time_to_tp3": row["time_to_tp3"],
            "time_to_tp4": row["time_to_tp4"],
            "time_to_sl": row["time_to_sl"],
            "balance_before": row["balance_before"],
            "profit_loss": row["profit_loss"],
            "balance_after": row["balance_after"],
            "notes": row["notes"],
        }

    def _row_to_feature_payload(self, row: sqlite3.Row) -> dict[str, Any]:
        extra = parse_json_text(row["notes"], {})
        if not isinstance(extra, dict):
            extra = {"notes_summary": normalize_text(row["notes"])}
        payload = {
            "signal_call_id": row["signal_call_id"],
            "signal_id": row["signal_id"],
            "date": row["date"],
            "time_gmt": row["time_gmt"],
            "symbol": row["symbol"],
            "direction": row["direction"],
            "detected_setup": row["detected_setup"],
            "confidence_score": row["confidence_score"],
            "ema_bias": row["ema_bias"],
            "rsi": row["rsi"],
            "atr": row["atr"],
            "vwap": row["vwap"],
            "vwap_position": row["vwap_position"],
            "asian_high": row["asian_high"],
            "asian_low": row["asian_low"],
            "london_high": row["london_high"],
            "london_low": row["london_low"],
            "previous_day_high": row["previous_day_high"],
            "previous_day_low": row["previous_day_low"],
            "asian_high_swept": bool(row["asian_high_swept"]),
            "asian_low_swept": bool(row["asian_low_swept"]),
            "london_high_swept": bool(row["london_high_swept"]),
            "london_low_swept": bool(row["london_low_swept"]),
            "round_number_distance": row["round_number_distance"],
            "notes": row["notes"],
            "evidence": parse_json_text(row["evidence_json"], []),
        }
        payload.update(extra)
        return payload

    def _signal_datetime(self, date_text: str, time_text: str) -> datetime | None:
        date_value = parse_date_value(date_text)
        time_value = parse_time_value(time_text)
        if date_value is None or time_value is None:
            return None
        return datetime.combine(date_value.date(), time_value, tzinfo=UTC)

    def update_signal(self, signal_call_id: int, updates: dict[str, Any]) -> dict[str, Any]:
        with self.db.lock, self.db.connect() as conn:
            row = conn.execute("SELECT * FROM signal_calls WHERE id = ?", (signal_call_id,)).fetchone()
            if row is None:
                return {"ok": False, "message": "Signal not found."}
            batch_id = int(row["batch_id"])
            current = self._row_to_signal_payload(row)
            merged = {
                "signal_id": updates.get("signal_id", current["signal_id"]),
                "date": updates.get("date", current["date"]),
                "time_gmt": updates.get("time_gmt", current["time_gmt"]),
                "symbol": updates.get("symbol", current["symbol"]),
                "direction": updates.get("direction", current["direction"]),
                "entry": updates.get("entry", current["entry"]),
                "limit_price": updates.get("limit_price", current["limit_price"]),
                "stop_loss": updates.get("stop_loss", current["stop_loss"]),
                "raw_preview": updates.get("raw_preview", current["raw_preview"]),
            }
            for idx in range(1, 9):
                tp_value = None
                if idx - 1 < len(current["tps"]):
                    tp_value = current["tps"][idx - 1]
                merged[f"tp{idx}"] = updates.get(f"tp{idx}", tp_value)
            existing_keys = self._load_existing_signal_keys()
            existing_keys.discard(self._signal_key(ParsedSignal(
                signal_id=current["signal_id"],
                date_text=current["date"],
                time_text=current["time_gmt"],
                symbol=current["symbol"],
                direction=current["direction"],
                entry=current["entry"],
                limit_price=current["limit_price"],
                stop_loss=current["stop_loss"],
                tps=current["tps"],
                raw_preview=current["raw_preview"],
                validation_status=current["validation_status"],
                validation_errors=[],
                validation_warnings=[],
                broker_symbol=current["broker_symbol"],
            )))
            parsed = self._normalize_row(merged, signal_call_id, existing_keys, set())
            conn.execute(
                """
                UPDATE signal_calls
                SET signal_id = ?, date = ?, time_gmt = ?, symbol = ?, broker_symbol = ?, direction = ?,
                    entry = ?, limit_price = ?, stop_loss = ?, tps_json = ?, raw_preview = ?,
                    validation_status = ?, validation_errors_json = ?, validation_warnings_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    parsed.signal_id,
                    parsed.date_text,
                    parsed.time_text,
                    parsed.symbol,
                    parsed.broker_symbol,
                    parsed.direction,
                    parsed.entry,
                    parsed.limit_price,
                    parsed.stop_loss,
                    ensure_json(parsed.tps),
                    parsed.raw_preview,
                    parsed.validation_status,
                    ensure_json(parsed.validation_errors),
                    ensure_json(parsed.validation_warnings),
                    iso_now(),
                    signal_call_id,
                ),
            )
            totals = conn.execute(
                "SELECT COUNT(*) as total, SUM(CASE WHEN validation_status = 'valid' THEN 1 ELSE 0 END) as valid_count FROM signal_calls WHERE batch_id = ?",
                (batch_id,),
            ).fetchone()
            total = int(totals["total"] or 0)
            valid = int(totals["valid_count"] or 0)
            conn.execute(
                "UPDATE signal_import_batches SET total_rows = ?, valid_rows = ?, invalid_rows = ? WHERE id = ?",
                (total, valid, total - valid, batch_id),
            )
            conn.commit()
        return {"ok": True, **self.get_batch_payload(batch_id)}

    def backtest_batch(self, batch_id: int, settings: dict[str, Any]) -> dict[str, Any]:
        self._log("replay started", batch_id=batch_id, settings=settings)
        with self.db.lock, self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM signal_calls WHERE batch_id = ? ORDER BY date ASC, time_gmt ASC, id ASC", (batch_id,)).fetchall()
        valid_rows = [row for row in rows if row["validation_status"] == "valid"]
        if not valid_rows:
            return {"ok": False, "message": "No valid signals found in this batch."}
        if self.mt5 is None or not self.ensure_mt5_ready():
            return {"ok": False, "message": "MT5 is not connected. Historical replay needs MT5 candle data."}

        timeframe = str(settings.get("timeframe", "M1")).upper()
        replay_hours = max(1, int(settings.get("replay_window_hours", 24) or 24))
        entry_mode = str(settings.get("entry_mode", "MARKET")).upper()
        exit_model = str(settings.get("exit_model", "TP1_ONLY")).upper()
        custom_tp_index = max(1, int(settings.get("custom_tp_index", 1) or 1))
        tolerance = safe_float(settings.get("entry_tolerance", 0.0))
        starting_balance = safe_float(settings.get("starting_balance", 50.0), 50.0)
        fixed_lot_size = safe_float(settings.get("fixed_lot_size", 0.01), 0.01)
        lot_mode = str(settings.get("lot_size_mode", "fixed")).lower()
        risk_percent = safe_float(settings.get("risk_percent", 1.0), 1.0)
        price_value_per_dollar = safe_float(settings.get("profit_per_1_dollar_move_per_0_01_lot", 1.0), 1.0)
        commission = safe_float(settings.get("commission_per_trade", 0.0))
        spread_cost = safe_float(settings.get("spread_cost", 0.0))
        range_preset = str(settings.get("range_preset", "all") or "all").lower()
        from_date = normalize_text(settings.get("from_date", ""))
        to_date = normalize_text(settings.get("to_date", ""))

        mode_list = ["MARKET", "LIMIT"] if entry_mode == "BOTH" else [entry_mode]
        results_to_store: list[dict[str, Any]] = []
        features_to_store: dict[int, dict[str, Any]] = {}
        mode_balances = {mode: starting_balance for mode in mode_list}
        lot_warnings: list[str] = []
        halted_modes: set[str] = set()

        if fixed_lot_size <= 0.01 and exit_model in {"MULTI_POSITION", "TP1_BE_TP2", "TP1_BE_TP3"}:
            lot_warnings.append("Partial closes may not be possible because your total position size is already at the broker minimum lot size. Full-close logic may be more realistic.")

        valid_rows = self._filter_rows_by_range(valid_rows, range_preset, from_date, to_date)
        if not valid_rows:
            return {"ok": False, "message": "No valid signals matched the selected date range."}

        for row in valid_rows:
            dt_signal = self._signal_datetime(row["date"], row["time_gmt"])
            if dt_signal is None:
                continue
            signal = self._row_to_signal_payload(row)
            resolution = self.resolve_symbol(signal["symbol"], signal.get("broker_symbol", ""))
            symbol = resolution["broker_symbol"] or signal["broker_symbol"] or signal["symbol"]
            signal["broker_symbol"] = symbol
            replay_end_time = dt_signal + timedelta(hours=replay_hours)
            self._log(
                "broker symbol mapping",
                signal_id=signal["signal_id"],
                imported_symbol=signal["symbol"],
                resolved_broker_symbol=symbol,
                mapping_mode=resolution["mapping_mode"],
            )
            candles, candle_meta = self._fetch_candles_with_meta(symbol, dt_signal, replay_end_time, timeframe)
            self._log(
                "candle fetch attempt",
                signal_id=signal["signal_id"],
                imported_symbol=signal["symbol"],
                resolved_broker_symbol=symbol,
                mapping_mode=resolution["mapping_mode"],
                timeframe=timeframe,
                requested_start_time=dt_signal.isoformat(),
                requested_end_time=replay_end_time.isoformat(),
                candle_count=candle_meta["count"],
                mt5_last_error=candle_meta["last_error"],
            )
            if not candles:
                no_data_note = (
                    f"NO_CANDLE_DATA | imported symbol: {signal['symbol']} | resolved broker symbol: {symbol} | "
                    f"start: {dt_signal.isoformat()} | end: {replay_end_time.isoformat()} | timeframe: {timeframe} | "
                    f"mt5_last_error: {candle_meta['last_error']}"
                )
                self._log(
                    "missing candle data",
                    signal_id=signal["signal_id"],
                    imported_symbol=signal["symbol"],
                    resolved_broker_symbol=symbol,
                    mapping_mode=resolution["mapping_mode"],
                    timeframe=timeframe,
                    requested_start_time=dt_signal.isoformat(),
                    requested_end_time=replay_end_time.isoformat(),
                    candle_count=candle_meta["count"],
                    mt5_last_error=candle_meta["last_error"],
                )
                for mode in mode_list:
                    balance_before = mode_balances[mode]
                    results_to_store.append(
                        self._result_template(
                            signal_call_id=int(row["id"]),
                            entry_mode=mode,
                            exit_model=exit_model,
                            timeframe=timeframe,
                            replay_start=dt_signal,
                            replay_end=replay_end_time,
                            balance_before=balance_before,
                            balance_after=balance_before,
                            notes=no_data_note,
                            outcome="NO_CANDLE_DATA",
                            first_outcome="NO_CANDLE_DATA",
                        )
                    )
                continue

            features_to_store[int(row["id"])] = self._detect_features(signal, dt_signal, candles, symbol)
            symbol_info = self._symbol_info(symbol)
            for mode in mode_list:
                if mode in halted_modes:
                    continue
                balance_before = mode_balances[mode]
                if balance_before <= 0:
                    halted_modes.add(mode)
                    continue
                lot_size = self._determine_lot_size(signal, balance_before, lot_mode, fixed_lot_size, risk_percent, price_value_per_dollar, symbol_info)
                margin_required = self._required_margin(signal, lot_size, symbol_info)
                if margin_required > balance_before:
                    results_to_store.append(
                        self._result_template(
                            signal_call_id=int(row["id"]),
                            entry_mode=mode,
                            exit_model=exit_model,
                            timeframe=timeframe,
                            replay_start=dt_signal,
                            replay_end=dt_signal + timedelta(hours=replay_hours),
                            balance_before=balance_before,
                            balance_after=balance_before,
                            notes=f"REJECTED_INSUFFICIENT_MARGIN | required margin {margin_required:.2f} exceeded balance {balance_before:.2f}.",
                            outcome="REJECTED_INSUFFICIENT_MARGIN",
                            first_outcome="REJECTED_INSUFFICIENT_MARGIN",
                        )
                    )
                    self._log("trade rejected", signal_id=signal["signal_id"], entry_mode=mode, reason="insufficient_margin", balance_before=balance_before, required_margin=margin_required)
                    halted_modes.add(mode)
                    continue
                result = self._replay_signal(
                    signal=signal,
                    signal_call_id=int(row["id"]),
                    candles=candles,
                    signal_time=dt_signal,
                    timeframe=timeframe,
                    replay_hours=replay_hours,
                    entry_mode=mode,
                    exit_model=exit_model,
                    custom_tp_index=custom_tp_index,
                    tolerance=tolerance,
                    balance_before=balance_before,
                    lot_size=lot_size,
                    commission=commission,
                    spread_cost=spread_cost,
                    price_value_per_dollar=price_value_per_dollar,
                )
                result["required_margin"] = round(margin_required, 2)
                if result["balance_after"] <= 0:
                    result["balance_after"] = 0.0
                    result["notes"] = f"{result['notes']} Account cleared. Replay stopped for this mode.".strip()
                    halted_modes.add(mode)
                results_to_store.append(result)
                mode_balances[mode] = result["balance_after"]
                self._log("replay result", signal_id=signal["signal_id"], entry_mode=mode, outcome=result["outcome"], balance_after=result["balance_after"])

        with self.db.lock, self.db.connect() as conn:
            valid_signal_ids = tuple(int(row["id"]) for row in valid_rows) or (-1,)
            placeholders = ",".join("?" for _ in valid_signal_ids)
            conn.execute(
                f"DELETE FROM signal_backtest_results WHERE signal_call_id IN ({placeholders})",
                valid_signal_ids,
            )
            conn.execute(
                f"DELETE FROM signal_feature_analysis WHERE signal_call_id IN ({placeholders})",
                valid_signal_ids,
            )
            conn.executemany(
                """
                INSERT INTO signal_backtest_results(
                    signal_call_id, entry_mode, exit_model, timeframe_used, replay_start_time, replay_end_time,
                    entry_filled, limit_filled, selected_entry_price, selected_exit_price, outcome, tp_hits_json,
                    sl_hit, first_outcome, max_favorable_excursion, max_adverse_excursion, time_to_tp1, time_to_tp2,
                    time_to_tp3, time_to_tp4, time_to_sl, balance_before, profit_loss, balance_after, notes, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item["signal_call_id"],
                        item["entry_mode"],
                        item["exit_model"],
                        item["timeframe_used"],
                        item["replay_start_time"],
                        item["replay_end_time"],
                        int(item["entry_filled"]),
                        int(item["limit_filled"]),
                        item["selected_entry_price"],
                        item["selected_exit_price"],
                        item["outcome"],
                        ensure_json(item["tp_hits"]),
                        int(item["sl_hit"]),
                        item["first_outcome"],
                        item["max_favorable_excursion"],
                        item["max_adverse_excursion"],
                        item["time_to_tp1"],
                        item["time_to_tp2"],
                        item["time_to_tp3"],
                        item["time_to_tp4"],
                        item["time_to_sl"],
                        item["balance_before"],
                        item["profit_loss"],
                        item["balance_after"],
                        item["notes"],
                        iso_now(),
                        iso_now(),
                    )
                    for item in results_to_store
                ],
            )
            conn.executemany(
                """
                INSERT INTO signal_feature_analysis(
                    signal_call_id, asian_high, asian_low, london_high, london_low, previous_day_high, previous_day_low,
                    asian_high_swept, asian_low_swept, london_high_swept, london_low_swept, ema_20, ema_50, ema_bias,
                    rsi, atr, vwap, vwap_position, round_number_distance, detected_setup, confidence_score, notes, evidence_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        signal_call_id,
                        feature.get("asian_high"),
                        feature.get("asian_low"),
                        feature.get("london_high"),
                        feature.get("london_low"),
                        feature.get("previous_day_high"),
                        feature.get("previous_day_low"),
                        int(feature.get("asian_high_swept", False)),
                        int(feature.get("asian_low_swept", False)),
                        int(feature.get("london_high_swept", False)),
                        int(feature.get("london_low_swept", False)),
                        feature.get("ema_20"),
                        feature.get("ema_50"),
                        feature.get("ema_bias", ""),
                        feature.get("rsi"),
                        feature.get("atr"),
                        feature.get("vwap"),
                        feature.get("vwap_position", ""),
                        feature.get("round_number_distance"),
                        feature.get("detected_setup", "Unknown"),
                        feature.get("confidence_score", 0.0),
                        feature.get("notes_json", feature.get("notes", "")),
                        ensure_json(feature.get("evidence", [])),
                    )
                    for signal_call_id, feature in features_to_store.items()
                ],
            )
            conn.commit()

        payload = self.get_batch_payload(batch_id)
        payload["ok"] = True
        payload["message"] = "Signal Lab replay completed."
        payload["warnings"] = lot_warnings
        payload["settings"] = {
            "timeframe": timeframe,
            "entry_mode": entry_mode,
            "exit_model": exit_model,
            "replay_window_hours": replay_hours,
            "starting_balance": starting_balance,
            "fixed_lot_size": fixed_lot_size,
            "lot_size_mode": lot_mode,
            "risk_percent": risk_percent,
        }
        return payload

    def _filter_rows_by_range(self, rows: list[sqlite3.Row], range_preset: str, from_date: str, to_date: str) -> list[sqlite3.Row]:
        dated_rows = []
        for row in rows:
            dt = self._signal_datetime(row["date"], row["time_gmt"])
            if dt is not None:
                dated_rows.append((row, dt))
        if not dated_rows:
            return rows
        max_date = max(dt.date() for _row, dt in dated_rows)
        min_bound = None
        max_bound = None
        if range_preset == "week":
            min_bound = max_date - timedelta(days=6)
            max_bound = max_date
        elif range_preset == "month":
            min_bound = max_date - timedelta(days=29)
            max_bound = max_date
        elif range_preset == "custom":
            parsed_from = parse_date_value(from_date)
            parsed_to = parse_date_value(to_date)
            min_bound = parsed_from.date() if parsed_from else None
            max_bound = parsed_to.date() if parsed_to else None
        filtered = []
        for row, dt in dated_rows:
            date_value = dt.date()
            if min_bound and date_value < min_bound:
                continue
            if max_bound and date_value > max_bound:
                continue
            filtered.append(row)
        return filtered or [row for row, _dt in dated_rows]

    def _result_template(
        self,
        *,
        signal_call_id: int,
        entry_mode: str,
        exit_model: str,
        timeframe: str,
        replay_start: datetime,
        replay_end: datetime,
        balance_before: float,
        balance_after: float,
        notes: str,
        outcome: str,
        first_outcome: str,
    ) -> dict[str, Any]:
        return {
            "signal_call_id": signal_call_id,
            "entry_mode": entry_mode,
            "exit_model": exit_model,
            "timeframe_used": timeframe,
            "replay_start_time": replay_start.isoformat(),
            "replay_end_time": replay_end.isoformat(),
            "entry_filled": False,
            "limit_filled": False,
            "selected_entry_price": None,
            "selected_exit_price": None,
            "outcome": outcome,
            "tp_hits": {},
            "sl_hit": False,
            "first_outcome": first_outcome,
            "max_favorable_excursion": 0.0,
            "max_adverse_excursion": 0.0,
            "time_to_tp1": None,
            "time_to_tp2": None,
            "time_to_tp3": None,
            "time_to_tp4": None,
            "time_to_sl": None,
            "balance_before": round(balance_before, 2),
            "profit_loss": 0.0,
            "balance_after": round(balance_after, 2),
            "notes": notes,
        }

    def _fetch_candles_with_meta(self, symbol: str, start: datetime, end: datetime, timeframe: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if self.mt5 is None:
            return [], {"count": 0, "last_error": "MT5 unavailable"}
        tf_attr, tf_default = self.TIMEFRAME_MAP.get(timeframe, ("TIMEFRAME_M1", 1))
        rates = self.mt5.copy_rates_range(symbol, getattr(self.mt5, tf_attr, tf_default), start, end)
        last_error = ""
        try:
            if hasattr(self.mt5, "last_error"):
                last_error = str(self.mt5.last_error())
        except Exception:
            last_error = ""
        if rates is None:
            return [], {"count": 0, "last_error": last_error}
        candles = []
        for rate in rates:
            candles.append(
                {
                    "time": datetime.fromtimestamp(int(rate["time"]), UTC),
                    "open": safe_float(rate["open"]),
                    "high": safe_float(rate["high"]),
                    "low": safe_float(rate["low"]),
                    "close": safe_float(rate["close"]),
                    "tick_volume": safe_float(rate.get("tick_volume", 0)) if isinstance(rate, dict) else safe_float(rate["tick_volume"]),
                }
            )
        return candles, {"count": len(candles), "last_error": last_error}

    def _fetch_candles(self, symbol: str, start: datetime, end: datetime, timeframe: str) -> list[dict[str, Any]]:
        candles, _meta = self._fetch_candles_with_meta(symbol, start, end, timeframe)
        return candles

    def _symbol_info(self, symbol: str) -> dict[str, Any]:
        if self.mt5 is None:
            return {"point": 0.01, "digits": 2, "trade_contract_size": 100.0, "trade_tick_value": 1.0, "volume_min": 0.01, "volume_step": 0.01}
        info = self.mt5.symbol_info(symbol)
        if info is None:
            return {"point": 0.01, "digits": 2, "trade_contract_size": 100.0, "trade_tick_value": 1.0, "volume_min": 0.01, "volume_step": 0.01}
        return {
            "point": safe_float(getattr(info, "point", 0.01), 0.01),
            "digits": int(getattr(info, "digits", 2) or 2),
            "trade_contract_size": safe_float(getattr(info, "trade_contract_size", 100.0), 100.0),
            "trade_tick_value": safe_float(getattr(info, "trade_tick_value", 1.0), 1.0),
            "trade_tick_size": safe_float(getattr(info, "trade_tick_size", safe_float(getattr(info, "point", 0.01), 0.01)), 0.01),
            "volume_min": safe_float(getattr(info, "volume_min", 0.01), 0.01),
            "volume_step": safe_float(getattr(info, "volume_step", 0.01), 0.01),
            "leverage": self._account_leverage(),
        }

    def _account_leverage(self) -> float:
        if self.mt5 is None:
            return 200.0
        try:
            account = self.mt5.account_info()
            leverage = float(getattr(account, "leverage", 0) or 0) if account is not None else 0.0
            return leverage if leverage > 0 else 200.0
        except Exception:
            return 200.0

    def _determine_lot_size(self, signal: dict[str, Any], balance: float, lot_mode: str, fixed_lot_size: float, risk_percent: float, price_value_per_dollar: float, symbol_info: dict[str, Any]) -> float:
        min_lot = max(symbol_info.get("volume_min", 0.01), 0.01)
        step = max(symbol_info.get("volume_step", 0.01), 0.01)
        if lot_mode != "risk_based":
            return max(min_lot, round(fixed_lot_size / step) * step)
        entry = safe_float(signal["entry"])
        stop = safe_float(signal["stop_loss"])
        risk_distance = abs(entry - stop)
        if risk_distance <= 0:
            return max(min_lot, round(fixed_lot_size / step) * step)
        risk_amount = balance * (risk_percent / 100.0)
        loss_per_001 = risk_distance * price_value_per_dollar
        raw_lot = (risk_amount / max(loss_per_001, 0.0001)) * 0.01
        normalized = max(min_lot, math.floor(raw_lot / step) * step if raw_lot >= min_lot else min_lot)
        return round(normalized, 2 if step >= 0.01 else 4)

    def _required_margin(self, signal: dict[str, Any], lot_size: float, symbol_info: dict[str, Any]) -> float:
        entry = safe_float(signal.get("entry"), 0.0)
        contract_size = safe_float(symbol_info.get("trade_contract_size", 100.0), 100.0)
        leverage = max(safe_float(symbol_info.get("leverage", 200.0), 200.0), 1.0)
        notional = entry * contract_size * max(lot_size, 0.0)
        if notional <= 0:
            return 0.0
        return round(notional / leverage, 2)

    def _replay_signal(
        self,
        *,
        signal: dict[str, Any],
        signal_call_id: int,
        candles: list[dict[str, Any]],
        signal_time: datetime,
        timeframe: str,
        replay_hours: int,
        entry_mode: str,
        exit_model: str,
        custom_tp_index: int,
        tolerance: float,
        balance_before: float,
        lot_size: float,
        commission: float,
        spread_cost: float,
        price_value_per_dollar: float,
    ) -> dict[str, Any]:
        replay_end = signal_time + timedelta(hours=replay_hours)
        result = self._result_template(
            signal_call_id=signal_call_id,
            entry_mode=entry_mode,
            exit_model=exit_model,
            timeframe=timeframe,
            replay_start=signal_time,
            replay_end=replay_end,
            balance_before=balance_before,
            balance_after=balance_before,
            notes="",
            outcome="NO_FILL",
            first_outcome="NO_FILL",
        )

        direction = signal["direction"]
        entry = safe_float(signal["entry"])
        limit_price = signal["limit_price"]
        stop_loss = safe_float(signal["stop_loss"])
        tps = list(signal["tps"])

        active = False
        active_entry_price: float | None = None
        tp_times: dict[int, int | None] = {}
        tp_hits: dict[str, bool] = {}
        sl_time: int | None = None
        mfe = 0.0
        mae = 0.0

        for candle in candles:
            if candle["time"] < signal_time:
                continue

            if not active:
                if entry_mode == "MARKET":
                    active = True
                    active_entry_price = entry
                    result["entry_filled"] = True
                elif entry_mode == "LIMIT":
                    target_limit = safe_float(limit_price)
                    if target_limit and candle["low"] - tolerance <= target_limit <= candle["high"] + tolerance:
                        active = True
                        active_entry_price = target_limit
                        result["entry_filled"] = True
                        result["limit_filled"] = True
                if not active:
                    continue

            assert active_entry_price is not None
            result["selected_entry_price"] = round_or_none(active_entry_price, 3)
            move_up = candle["high"] - active_entry_price
            move_down = active_entry_price - candle["low"]
            if direction == "BUY":
                mfe = max(mfe, move_up)
                mae = max(mae, move_down)
            else:
                mfe = max(mfe, active_entry_price - candle["low"])
                mae = max(mae, candle["high"] - active_entry_price)

            self._mark_tp_times(direction, active_entry_price, candle, signal_time, tps, tp_times, tp_hits)
            if sl_time is None and self._price_touched(direction, stop_loss, candle, level_type="sl"):
                sl_time = int((candle["time"] - signal_time).total_seconds())

            event = self._resolve_candle_event(direction, candle, active_entry_price, stop_loss, tps, signal_time, tp_times, sl_time)
            if result["first_outcome"] == "NO_FILL" and event:
                result["first_outcome"] = event

            exit_info = self._evaluate_exit_model(
                direction=direction,
                entry_price=active_entry_price,
                stop_loss=stop_loss,
                tps=tps,
                tp_times=tp_times,
                sl_time=sl_time,
                candle=candle,
                signal_time=signal_time,
                exit_model=exit_model,
                custom_tp_index=custom_tp_index,
            )
            if exit_info["done"]:
                exit_price = exit_info["exit_price"]
                profit_loss = self._profit_loss(direction, active_entry_price, exit_price, lot_size, price_value_per_dollar, commission, spread_cost)
                result.update(
                    {
                        "selected_exit_price": round_or_none(exit_price, 3),
                        "outcome": exit_info["outcome"],
                        "sl_hit": exit_info["outcome"] in {"SL", "BREAKEVEN"} or (sl_time is not None and exit_info["outcome"] == "SL"),
                        "profit_loss": round(profit_loss, 2),
                        "balance_after": round(balance_before + profit_loss, 2),
                        "notes": exit_info["notes"],
                    }
                )
                break

        if result["selected_entry_price"] is None:
            result["notes"] = "Entry was never filled inside the replay window."
            return result

        if result["selected_exit_price"] is None:
            final_close = candles[-1]["close"] if candles else active_entry_price
            profit_loss = self._profit_loss(direction, active_entry_price, final_close, lot_size, price_value_per_dollar, commission, spread_cost)
            result.update(
                {
                    "selected_exit_price": round_or_none(final_close, 3),
                    "outcome": "EXPIRED",
                    "profit_loss": round(profit_loss, 2),
                    "balance_after": round(balance_before + profit_loss, 2),
                    "notes": "Replay window ended before the selected exit model completed.",
                }
            )

        result["tp_hits"] = {f"tp{idx}": bool(tp_hits.get(f"tp{idx}", False)) for idx in range(1, max(5, len(tps) + 1))}
        result["time_to_tp1"] = tp_times.get(1)
        result["time_to_tp2"] = tp_times.get(2)
        result["time_to_tp3"] = tp_times.get(3)
        result["time_to_tp4"] = tp_times.get(4)
        result["time_to_sl"] = sl_time
        result["max_favorable_excursion"] = round(mfe, 3)
        result["max_adverse_excursion"] = round(mae, 3)
        return result

    def _price_touched(self, direction: str, level: float, candle: dict[str, Any], *, level_type: str) -> bool:
        if level <= 0:
            return False
        return candle["low"] <= level <= candle["high"]

    def _mark_tp_times(self, direction: str, entry: float, candle: dict[str, Any], signal_time: datetime, tps: list[float], tp_times: dict[int, int | None], tp_hits: dict[str, bool]) -> None:
        for idx, tp in enumerate(tps, start=1):
            if idx in tp_times:
                continue
            if direction == "BUY" and candle["high"] >= tp:
                tp_times[idx] = int((candle["time"] - signal_time).total_seconds())
                tp_hits[f"tp{idx}"] = True
            elif direction == "SELL" and candle["low"] <= tp:
                tp_times[idx] = int((candle["time"] - signal_time).total_seconds())
                tp_hits[f"tp{idx}"] = True

    def _resolve_candle_event(self, direction: str, candle: dict[str, Any], entry: float, stop_loss: float, tps: list[float], signal_time: datetime, tp_times: dict[int, int | None], sl_time: int | None) -> str | None:
        touched_tps = [idx for idx, _tp in enumerate(tps, start=1) if idx in tp_times]
        if sl_time is None and not touched_tps:
            return None
        candle_bullish = candle["close"] >= candle["open"]
        path = [candle["open"], candle["high"], candle["low"], candle["close"]] if candle_bullish else [candle["open"], candle["low"], candle["high"], candle["close"]]
        levels: list[tuple[str, float]] = [("SL", stop_loss)]
        levels.extend((f"TP{idx}", tp) for idx, tp in enumerate(tps, start=1))
        seen: list[str] = []
        for path_idx in range(len(path) - 1):
            a = path[path_idx]
            b = path[path_idx + 1]
            low, high = min(a, b), max(a, b)
            for label, price in levels:
                if label in seen or price <= 0:
                    continue
                if low <= price <= high:
                    seen.append(label)
        return seen[0] if seen else None

    def _evaluate_exit_model(
        self,
        *,
        direction: str,
        entry_price: float,
        stop_loss: float,
        tps: list[float],
        tp_times: dict[int, int | None],
        sl_time: int | None,
        candle: dict[str, Any],
        signal_time: datetime,
        exit_model: str,
        custom_tp_index: int,
    ) -> dict[str, Any]:
        def target_hit(tp_index: int) -> bool:
            return tp_index in tp_times

        if exit_model.startswith("TP") and exit_model.endswith("_ONLY"):
            target_idx = int(exit_model[2])
            if target_idx <= len(tps) and target_hit(target_idx):
                return {"done": True, "exit_price": tps[target_idx - 1], "outcome": f"TP{target_idx}", "notes": f"Closed fully at TP{target_idx}."}
            if sl_time is not None and (target_idx not in tp_times or sl_time <= (tp_times.get(target_idx) or 10**9)):
                return {"done": True, "exit_price": stop_loss, "outcome": "SL", "notes": "Stop loss hit before selected TP."}
        if exit_model == "CUSTOM_TP":
            target_idx = min(max(custom_tp_index, 1), len(tps))
            if target_hit(target_idx):
                return {"done": True, "exit_price": tps[target_idx - 1], "outcome": f"TP{target_idx}", "notes": f"Closed at custom TP{target_idx}."}
            if sl_time is not None and sl_time <= (tp_times.get(target_idx) or 10**9):
                return {"done": True, "exit_price": stop_loss, "outcome": "SL", "notes": "Stop loss hit before custom TP."}
        if exit_model == "TP1_BE_TP2" and len(tps) >= 2:
            tp1 = tp_times.get(1)
            tp2 = tp_times.get(2)
            if tp1 is not None and tp2 is not None and tp2 >= tp1:
                return {"done": True, "exit_price": tps[1], "outcome": "TP2", "notes": "TP1 reached, SL moved to breakeven, TP2 hit."}
            if tp1 is not None and sl_time is not None and sl_time > tp1:
                return {"done": True, "exit_price": entry_price, "outcome": "BREAKEVEN", "notes": "TP1 reached, then breakeven stop was hit."}
            if sl_time is not None and (tp1 is None or sl_time <= tp1):
                return {"done": True, "exit_price": stop_loss, "outcome": "SL", "notes": "Stop loss hit before TP1."}
        if exit_model == "TP1_BE_TP3" and len(tps) >= 3:
            tp1 = tp_times.get(1)
            tp3 = tp_times.get(3)
            if tp1 is not None and tp3 is not None and tp3 >= tp1:
                return {"done": True, "exit_price": tps[2], "outcome": "TP3", "notes": "TP1 reached, SL moved to breakeven, TP3 hit."}
            if tp1 is not None and sl_time is not None and sl_time > tp1:
                return {"done": True, "exit_price": entry_price, "outcome": "BREAKEVEN", "notes": "TP1 reached, then breakeven stop was hit."}
            if sl_time is not None and (tp1 is None or sl_time <= tp1):
                return {"done": True, "exit_price": stop_loss, "outcome": "SL", "notes": "Stop loss hit before TP1."}
        if exit_model == "MULTI_POSITION" and tps:
            hits = [idx for idx in range(1, len(tps) + 1) if idx in tp_times]
            if hits:
                average_exit = sum(tps[idx - 1] for idx in hits) / len(hits)
                return {"done": True, "exit_price": average_exit, "outcome": f"TP{hits[-1]}", "notes": "Multi-position simulation averaged the TP exits that were reached."}
            if sl_time is not None:
                return {"done": True, "exit_price": stop_loss, "outcome": "SL", "notes": "No TP tranche was reached before stop loss."}
        return {"done": False, "exit_price": None, "outcome": "", "notes": ""}

    def _profit_loss(self, direction: str, entry: float, exit_price: float, lot_size: float, price_value_per_dollar: float, commission: float, spread_cost: float) -> float:
        if direction == "BUY":
            movement = exit_price - entry
        else:
            movement = entry - exit_price
        profit = movement * price_value_per_dollar * (lot_size / 0.01)
        return profit - commission - spread_cost

    def _detect_features(self, signal: dict[str, Any], signal_time: datetime, candles: list[dict[str, Any]], symbol: str) -> dict[str, Any]:
        context = self._fetch_feature_context(symbol, signal_time)
        m1 = context["M1"]
        m5 = context["M5"]
        m15 = context["M15"]
        h1 = context["H1"]
        pre_m1 = [c for c in m1 if c["time"] <= signal_time]
        pre_m5 = [c for c in m5 if c["time"] <= signal_time]
        pre_m15 = [c for c in m15 if c["time"] <= signal_time]
        pre_h1 = [c for c in h1 if c["time"] <= signal_time]

        entry = safe_float(signal["entry"])
        stop_loss = safe_float(signal["stop_loss"])
        direction = signal["direction"]
        tps = list(signal["tps"] or [])
        session_label = classify_session(signal_time)

        bias_m5 = self._bias_snapshot(pre_m5, entry)
        bias_m15 = self._bias_snapshot(pre_m15, entry)
        bias_h1 = self._bias_snapshot(pre_h1, entry)
        rsi = self._rsi([c["close"] for c in pre_m5[-80:]], 14)
        atr_m5 = self._atr(pre_m5[-80:], 14)
        atr_m15 = self._atr(pre_m15[-80:], 14)
        vwap = self._vwap(pre_m1[-180:])

        round_levels = {}
        for step in (5, 10, 25, 50, 100):
            nearest = round(entry / step) * step if step else entry
            round_levels[f"distance_to_{step}_dollar_level"] = round_or_none(abs(entry - nearest), 3)
        round_number_distance = round_levels.get("distance_to_5_dollar_level")

        tp_distances = {
            "sl_distance": round_or_none(abs(entry - stop_loss), 3),
            "tp1_distance": round_or_none(abs(tps[0] - entry), 3) if len(tps) >= 1 else None,
            "tp2_distance": round_or_none(abs(tps[1] - entry), 3) if len(tps) >= 2 else None,
            "tp3_distance": round_or_none(abs(tps[2] - entry), 3) if len(tps) >= 3 else None,
            "tp4_distance": round_or_none(abs(tps[3] - entry), 3) if len(tps) >= 4 else None,
        }
        tp_steps = [abs(tps[idx] - tps[idx - 1]) for idx in range(1, len(tps))]
        is_fixed_5_dollar_ladder = bool(tp_steps and all(abs(step - 5.0) <= 0.75 for step in tp_steps[:4]))
        approximate_rr_to_tp1 = round_or_none((abs(tps[0] - entry) / abs(entry - stop_loss)) if len(tps) >= 1 and entry != stop_loss else None, 2)
        approximate_rr_to_tp2 = round_or_none((abs(tps[1] - entry) / abs(entry - stop_loss)) if len(tps) >= 2 and entry != stop_loss else None, 2)

        session_ranges = self._session_ranges(pre_m15, signal_time)
        sweep_buffer = max((atr_m5 or 0.8) * 0.08, 0.25)
        recent_high_sweep = self._detect_sweep(pre_m5[-36:], session_ranges["recent_high"], "high", sweep_buffer)
        recent_low_sweep = self._detect_sweep(pre_m5[-36:], session_ranges["recent_low"], "low", sweep_buffer)
        asian_high_sweep = self._detect_sweep(pre_m5[-72:], session_ranges["asian_high"], "high", sweep_buffer)
        asian_low_sweep = self._detect_sweep(pre_m5[-72:], session_ranges["asian_low"], "low", sweep_buffer)
        london_high_sweep = self._detect_sweep(pre_m5[-72:], session_ranges["london_high"], "high", sweep_buffer)
        london_low_sweep = self._detect_sweep(pre_m5[-72:], session_ranges["london_low"], "low", sweep_buffer)
        prev_high_sweep = self._detect_sweep(pre_m5[-72:], session_ranges["previous_day_high"], "high", sweep_buffer)
        prev_low_sweep = self._detect_sweep(pre_m5[-72:], session_ranges["previous_day_low"], "low", sweep_buffer)

        mss = self._detect_mss(pre_m5[-90:], direction, recent_high_sweep if direction == "SELL" else recent_low_sweep)
        displacement = self._detect_displacement(pre_m5[-40:], direction, atr_m5 or 0.0)
        fvg = self._detect_recent_fvg(pre_m5[-50:], entry)
        order_block = self._detect_order_block(pre_m5[-50:], direction, displacement, entry)

        evidence: list[str] = []
        score = 42.0
        if direction == "SELL" and bias_m15["bias"] == "bearish":
            evidence.append("Price was below the M15 EMA structure before the sell signal.")
            score += 8
        if direction == "BUY" and bias_m15["bias"] == "bullish":
            evidence.append("Price was above the M15 EMA structure before the buy signal.")
            score += 8
        if is_fixed_5_dollar_ladder:
            evidence.append("TP ladder used repeated 5-dollar spacing.")
            score += 10
        if round_number_distance is not None and round_number_distance <= 1.0:
            evidence.append("Entry sat close to a 5-dollar round number.")
            score += 7
        if displacement["detected"] and displacement["direction"] == direction:
            evidence.append("A displacement candle aligned with the signal direction.")
            score += 8
        if mss["detected"]:
            evidence.append(f"MSS/CHOCH was detected on M5 before the signal ({mss['direction']}).")
            score += 9
        if fvg["recent_fvg_detected"] and (fvg["entry_inside_fvg"] or fvg["entry_near_fvg"]):
            evidence.append("Entry aligned with a recent fair value gap.")
            score += 8
        if order_block["order_block_detected"] and (order_block["entry_inside_order_block"] or order_block["entry_near_order_block"]):
            evidence.append("Entry aligned with the last opposite candle before displacement.")
            score += 8

        setup = "Unknown/mixed"
        if is_fixed_5_dollar_ladder and "London" in session_label and direction == "SELL":
            setup = "Fixed ladder scalp"
            evidence.append("Sell signal appeared during London with a fixed ladder profile.")
            score += 10
        elif direction == "SELL" and (asian_high_sweep["detected"] or london_high_sweep["detected"] or prev_high_sweep["detected"]) and mss["detected"]:
            setup = "London liquidity sweep reversal" if "London" in session_label else "New York liquidity sweep reversal"
            evidence.append("A high sweep was followed by a bearish structure break before entry.")
            score += 12
        elif direction == "BUY" and (asian_low_sweep["detected"] or london_low_sweep["detected"] or prev_low_sweep["detected"]) and mss["detected"]:
            setup = "London liquidity sweep reversal" if "London" in session_label else "New York liquidity sweep reversal"
            evidence.append("A low sweep was followed by a bullish structure break before entry.")
            score += 12
        elif fvg["recent_fvg_detected"] and (fvg["entry_inside_fvg"] or fvg["entry_near_fvg"]):
            setup = "FVG retracement model"
            score += 10
        elif order_block["order_block_detected"] and (order_block["entry_inside_order_block"] or order_block["entry_near_order_block"]):
            setup = "Order block retracement model"
            score += 10
        elif direction == "SELL" and bias_h1["bias"] == "bearish" and bias_m5["bias"] == "bearish":
            setup = "London continuation sell model" if "London" in session_label else "Trend continuation pullback"
            score += 9
        elif direction == "BUY" and bias_h1["bias"] == "bullish" and bias_m5["bias"] == "bullish":
            setup = "Trend continuation pullback"
            score += 9
        elif round_number_distance is not None and round_number_distance <= 0.5:
            setup = "Round-number rejection scalp"
            score += 8

        notes_payload = {
            "notes_summary": f"Session: {session_label}",
            "session_label": session_label,
            "m5_bias": bias_m5["bias"],
            "m15_bias": bias_m15["bias"],
            "h1_bias": bias_h1["bias"],
            "m5_price_above_ema20": bias_m5["price_above_ema20"],
            "m5_price_above_ema50": bias_m5["price_above_ema50"],
            "m5_ema20_above_ema50": bias_m5["ema20_above_ema50"],
            "m15_price_above_ema20": bias_m15["price_above_ema20"],
            "m15_price_above_ema50": bias_m15["price_above_ema50"],
            "m15_ema20_above_ema50": bias_m15["ema20_above_ema50"],
            "h1_price_above_ema20": bias_h1["price_above_ema20"],
            "h1_price_above_ema50": bias_h1["price_above_ema50"],
            "h1_ema20_above_ema50": bias_h1["ema20_above_ema50"],
            "ema20_m5": round_or_none(bias_m5["ema20"], 3),
            "ema50_m5": round_or_none(bias_m5["ema50"], 3),
            "ema20_m15": round_or_none(bias_m15["ema20"], 3),
            "ema50_m15": round_or_none(bias_m15["ema50"], 3),
            "ema20_h1": round_or_none(bias_h1["ema20"], 3),
            "ema50_h1": round_or_none(bias_h1["ema50"], 3),
            **round_levels,
            **tp_distances,
            "is_fixed_5_dollar_ladder": is_fixed_5_dollar_ladder,
            "approximate_rr_to_tp1": approximate_rr_to_tp1,
            "approximate_rr_to_tp2": approximate_rr_to_tp2,
            **session_ranges,
            "recent_high_swept_before_signal": recent_high_sweep["detected"],
            "recent_low_swept_before_signal": recent_low_sweep["detected"],
            "asian_high_swept_before_signal": asian_high_sweep["detected"],
            "asian_low_swept_before_signal": asian_low_sweep["detected"],
            "london_high_swept_before_signal": london_high_sweep["detected"],
            "london_low_swept_before_signal": london_low_sweep["detected"],
            "previous_day_high_swept_before_signal": prev_high_sweep["detected"],
            "previous_day_low_swept_before_signal": prev_low_sweep["detected"],
            "mss_detected": mss["detected"],
            "mss_direction": mss["direction"],
            "mss_time": mss["time"],
            "bars_between_mss_and_signal": mss["bars_between"],
            "displacement_detected": displacement["detected"],
            "displacement_direction": displacement["direction"],
            "displacement_time": displacement["time"],
            "displacement_strength": displacement["strength"],
            "recent_fvg_detected": fvg["recent_fvg_detected"],
            "fvg_direction": fvg["fvg_direction"],
            "entry_inside_fvg": fvg["entry_inside_fvg"],
            "entry_near_fvg": fvg["entry_near_fvg"],
            "order_block_detected": order_block["order_block_detected"],
            "order_block_high": order_block["order_block_high"],
            "order_block_low": order_block["order_block_low"],
            "entry_inside_order_block": order_block["entry_inside_order_block"],
            "entry_near_order_block": order_block["entry_near_order_block"],
            "feature_fetch_counts": {tf: len(context[tf]) for tf in ("M1", "M5", "M15", "H1")},
        }

        return {
            "asian_high": round_or_none(session_ranges["asian_high"], 3),
            "asian_low": round_or_none(session_ranges["asian_low"], 3),
            "london_high": round_or_none(session_ranges["london_high"], 3),
            "london_low": round_or_none(session_ranges["london_low"], 3),
            "previous_day_high": round_or_none(session_ranges["previous_day_high"], 3),
            "previous_day_low": round_or_none(session_ranges["previous_day_low"], 3),
            "asian_high_swept": asian_high_sweep["detected"],
            "asian_low_swept": asian_low_sweep["detected"],
            "london_high_swept": london_high_sweep["detected"],
            "london_low_swept": london_low_sweep["detected"],
            "ema_20": round_or_none(bias_m15["ema20"], 3),
            "ema_50": round_or_none(bias_m15["ema50"], 3),
            "ema_bias": bias_m15["bias"],
            "rsi": round_or_none(rsi, 2),
            "atr": round_or_none(atr_m15 or atr_m5, 3),
            "vwap": round_or_none(vwap, 3),
            "vwap_position": "above" if vwap is not None and entry > vwap else "below" if vwap is not None and entry < vwap else "flat",
            "round_number_distance": round_or_none(round_number_distance, 3),
            "detected_setup": setup,
            "confidence_score": max(0.0, min(99.0, round(score, 1))),
            "notes_json": ensure_json(notes_payload),
            "evidence": evidence[:10],
        }

    def _fetch_feature_context(self, symbol: str, signal_time: datetime) -> dict[str, list[dict[str, Any]]]:
        windows = {
            "M1": signal_time - timedelta(hours=3),
            "M5": signal_time - timedelta(hours=12),
            "M15": signal_time - timedelta(days=2),
            "H1": signal_time - timedelta(days=5),
        }
        output: dict[str, list[dict[str, Any]]] = {}
        for timeframe, start in windows.items():
            candles, meta = self._fetch_candles_with_meta(symbol, start, signal_time, timeframe)
            self._log(
                "feature candle fetch",
                resolved_broker_symbol=symbol,
                timeframe=timeframe,
                requested_start_time=start.isoformat(),
                requested_end_time=signal_time.isoformat(),
                candle_count=meta["count"],
                mt5_last_error=meta["last_error"],
            )
            output[timeframe] = candles
        return output

    def _bias_snapshot(self, candles: list[dict[str, Any]], entry: float) -> dict[str, Any]:
        closes = [c["close"] for c in candles[-120:]]
        ema20 = self._ema(closes, 20)
        ema50 = self._ema(closes, 50)
        bias = "neutral"
        if ema20 is not None and ema50 is not None:
            if ema20 > ema50:
                bias = "bullish"
            elif ema20 < ema50:
                bias = "bearish"
        return {
            "ema20": ema20,
            "ema50": ema50,
            "price_above_ema20": bool(ema20 is not None and entry > ema20),
            "price_above_ema50": bool(ema50 is not None and entry > ema50),
            "ema20_above_ema50": bool(ema20 is not None and ema50 is not None and ema20 > ema50),
            "bias": bias,
        }

    def _session_ranges(self, candles: list[dict[str, Any]], signal_time: datetime) -> dict[str, Any]:
        current_date = signal_time.date()
        previous_date = current_date - timedelta(days=1)
        day_candles = [c for c in candles if c["time"].date() == current_date and c["time"] <= signal_time]
        prev_candles = [c for c in candles if c["time"].date() == previous_date]
        asian = [c for c in day_candles if 0 <= c["time"].hour <= 6]
        london = [c for c in day_candles if 7 <= c["time"].hour <= 12]
        recent = candles[-24:] if candles else []
        return {
            "asian_high": max((c["high"] for c in asian), default=None),
            "asian_low": min((c["low"] for c in asian), default=None),
            "london_high": max((c["high"] for c in london), default=None),
            "london_low": min((c["low"] for c in london), default=None),
            "previous_day_high": max((c["high"] for c in prev_candles), default=None),
            "previous_day_low": min((c["low"] for c in prev_candles), default=None),
            "current_day_high": max((c["high"] for c in day_candles), default=None),
            "current_day_low": min((c["low"] for c in day_candles), default=None),
            "recent_high": max((c["high"] for c in recent), default=None),
            "recent_low": min((c["low"] for c in recent), default=None),
        }

    def _detect_sweep(self, candles: list[dict[str, Any]], level: float | None, side: str, buffer: float, max_candles_back_inside: int = 3) -> dict[str, Any]:
        if level is None or not candles:
            return {"detected": False, "time": None}
        for idx, candle in enumerate(candles):
            if side == "high":
                took = candle["high"] >= level + buffer
                inside = candle["close"] <= level
            else:
                took = candle["low"] <= level - buffer
                inside = candle["close"] >= level
            if took and inside:
                return {"detected": True, "time": candle["time"].isoformat(), "index": idx}
            if took:
                for forward in candles[idx + 1: idx + 1 + max_candles_back_inside]:
                    if side == "high" and forward["close"] <= level:
                        return {"detected": True, "time": forward["time"].isoformat(), "index": idx}
                    if side == "low" and forward["close"] >= level:
                        return {"detected": True, "time": forward["time"].isoformat(), "index": idx}
        return {"detected": False, "time": None}

    def _detect_mss(self, candles: list[dict[str, Any]], direction: str, sweep: dict[str, Any]) -> dict[str, Any]:
        if not candles or not sweep.get("detected"):
            return {"detected": False, "direction": "", "time": None, "bars_between": None}
        sweep_time = sweep.get("time")
        sweep_dt = datetime.fromisoformat(sweep_time) if sweep_time else None
        start_idx = next((idx for idx, candle in enumerate(candles) if sweep_dt and candle["time"] >= sweep_dt), len(candles))
        if direction == "SELL":
            prior_low = min((c["low"] for c in candles[max(0, start_idx - 12):start_idx]), default=None)
            for idx in range(start_idx, len(candles)):
                if prior_low is not None and candles[idx]["close"] < prior_low:
                    return {"detected": True, "direction": "bearish", "time": candles[idx]["time"].isoformat(), "bars_between": idx - start_idx}
        else:
            prior_high = max((c["high"] for c in candles[max(0, start_idx - 12):start_idx]), default=None)
            for idx in range(start_idx, len(candles)):
                if prior_high is not None and candles[idx]["close"] > prior_high:
                    return {"detected": True, "direction": "bullish", "time": candles[idx]["time"].isoformat(), "bars_between": idx - start_idx}
        return {"detected": False, "direction": "", "time": None, "bars_between": None}

    def _detect_displacement(self, candles: list[dict[str, Any]], direction: str, atr_value: float) -> dict[str, Any]:
        if not candles or atr_value <= 0:
            return {"detected": False, "direction": "", "time": None, "strength": None, "index": None}
        for idx in range(len(candles) - 1, -1, -1):
            candle = candles[idx]
            body = abs(candle["close"] - candle["open"])
            candle_dir = "BUY" if candle["close"] >= candle["open"] else "SELL"
            if body >= atr_value * 1.2 and candle_dir == direction:
                return {
                    "detected": True,
                    "direction": direction,
                    "time": candle["time"].isoformat(),
                    "strength": round(body / atr_value, 2),
                    "index": idx,
                }
        return {"detected": False, "direction": "", "time": None, "strength": None, "index": None}

    def _detect_recent_fvg(self, candles: list[dict[str, Any]], entry: float) -> dict[str, Any]:
        if len(candles) < 3:
            return {"recent_fvg_detected": False, "fvg_direction": "", "entry_inside_fvg": False, "entry_near_fvg": False}
        for idx in range(len(candles) - 3, -1, -1):
            c1, _c2, c3 = candles[idx], candles[idx + 1], candles[idx + 2]
            if c1["high"] < c3["low"]:
                low, high = c1["high"], c3["low"]
                return {
                    "recent_fvg_detected": True,
                    "fvg_direction": "bullish",
                    "entry_inside_fvg": low <= entry <= high,
                    "entry_near_fvg": min(abs(entry - low), abs(entry - high)) <= 0.8,
                    "fvg_low": low,
                    "fvg_high": high,
                }
            if c1["low"] > c3["high"]:
                low, high = c3["high"], c1["low"]
                return {
                    "recent_fvg_detected": True,
                    "fvg_direction": "bearish",
                    "entry_inside_fvg": low <= entry <= high,
                    "entry_near_fvg": min(abs(entry - low), abs(entry - high)) <= 0.8,
                    "fvg_low": low,
                    "fvg_high": high,
                }
        return {"recent_fvg_detected": False, "fvg_direction": "", "entry_inside_fvg": False, "entry_near_fvg": False}

    def _detect_order_block(self, candles: list[dict[str, Any]], direction: str, displacement: dict[str, Any], entry: float) -> dict[str, Any]:
        idx = displacement.get("index")
        if idx is None or idx <= 0 or idx >= len(candles):
            return {"order_block_detected": False, "order_block_high": None, "order_block_low": None, "entry_inside_order_block": False, "entry_near_order_block": False}
        opposite = "SELL" if direction == "BUY" else "BUY"
        for probe in range(idx - 1, max(-1, idx - 8), -1):
            candle = candles[probe]
            candle_dir = "BUY" if candle["close"] >= candle["open"] else "SELL"
            if candle_dir == opposite:
                high = candle["high"]
                low = candle["low"]
                return {
                    "order_block_detected": True,
                    "order_block_high": round_or_none(high, 3),
                    "order_block_low": round_or_none(low, 3),
                    "entry_inside_order_block": low <= entry <= high,
                    "entry_near_order_block": min(abs(entry - low), abs(entry - high)) <= 0.8,
                }
        return {"order_block_detected": False, "order_block_high": None, "order_block_low": None, "entry_inside_order_block": False, "entry_near_order_block": False}

    def _ema(self, values: list[float], period: int) -> float | None:
        if len(values) < period:
            return None
        k = 2 / (period + 1)
        ema = values[0]
        for value in values[1:]:
            ema = value * k + ema * (1 - k)
        return ema

    def _rsi(self, values: list[float], period: int) -> float | None:
        if len(values) <= period:
            return None
        gains = []
        losses = []
        for idx in range(1, len(values)):
            delta = values[idx] - values[idx - 1]
            gains.append(max(delta, 0))
            losses.append(abs(min(delta, 0)))
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        for idx in range(period, len(gains)):
            avg_gain = ((avg_gain * (period - 1)) + gains[idx]) / period
            avg_loss = ((avg_loss * (period - 1)) + losses[idx]) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _atr(self, candles: list[dict[str, Any]], period: int) -> float | None:
        if len(candles) <= period:
            return None
        true_ranges = []
        prev_close = candles[0]["close"]
        for candle in candles[1:]:
            tr = max(candle["high"] - candle["low"], abs(candle["high"] - prev_close), abs(candle["low"] - prev_close))
            true_ranges.append(tr)
            prev_close = candle["close"]
        if len(true_ranges) < period:
            return None
        return sum(true_ranges[-period:]) / period

    def _vwap(self, candles: list[dict[str, Any]]) -> float | None:
        if not candles:
            return None
        cumulative_tp_vol = 0.0
        cumulative_vol = 0.0
        for candle in candles:
            typical = (candle["high"] + candle["low"] + candle["close"]) / 3
            volume = candle.get("tick_volume", 1.0) or 1.0
            cumulative_tp_vol += typical * volume
            cumulative_vol += volume
        if cumulative_vol <= 0:
            return None
        return cumulative_tp_vol / cumulative_vol

    def _build_analytics(self, signals: list[dict[str, Any]], results: list[dict[str, Any]], features: list[dict[str, Any]]) -> dict[str, Any]:
        valid_signals = [row for row in signals if row["validation_status"] == "valid"]
        invalid_signals = [row for row in signals if row["validation_status"] != "valid"]
        tested = results
        entry_fill_rate = (sum(1 for row in tested if row["entry_filled"]) / len(tested) * 100) if tested else 0.0
        limit_fill_rate = (sum(1 for row in tested if row["limit_filled"]) / len(tested) * 100) if tested else 0.0
        tp_rates = {}
        for idx in range(1, 5):
            tp_rates[f"tp{idx}"] = (sum(1 for row in tested if row["tp_hits"].get(f"tp{idx}")) / len(tested) * 100) if tested else 0.0
        sl_rate = (sum(1 for row in tested if row["sl_hit"]) / len(tested) * 100) if tested else 0.0
        avg_tp1 = self._average_metric(tested, "time_to_tp1")
        avg_tp2 = self._average_metric(tested, "time_to_tp2")
        balances = [row["balance_after"] for row in tested if row.get("balance_after") is not None]
        starting_balance = tested[0]["balance_before"] if tested else 0.0
        final_balance = tested[-1]["balance_after"] if tested else starting_balance
        net_profit = final_balance - starting_balance
        peak = starting_balance
        max_drawdown = 0.0
        drawdown_points = []
        equity_curve = []
        for idx, row in enumerate(tested, start=1):
            bal = row["balance_after"]
            peak = max(peak, bal)
            dd = peak - bal
            max_drawdown = max(max_drawdown, dd)
            drawdown_points.append({"x": idx, "y": round(dd, 2)})
            equity_curve.append({"x": idx, "y": round(bal, 2)})
        best_direction = self._best_bucket(tested, "direction")
        best_session = self._best_bucket(
            [{**row, "session": classify_session(self._signal_datetime(row["date"], row["time_gmt"]) or utc_now())} for row in tested],
            "session",
        )
        exit_comp = self._exit_model_comparison(tested)
        best_exit = max(exit_comp, key=lambda item: item["final_balance"], default={"label": "-"}) if exit_comp else {"label": "-"}

        strategy_detective = self._build_strategy_detective(features, tested, best_session, best_direction, best_exit.get("label", "-"))

        return {
            "cards": {
                "total_signals": len(signals),
                "valid_signals": len(valid_signals),
                "invalid_signals": len(invalid_signals),
                "tested_signals": len(tested),
                "entry_fill_rate": round(entry_fill_rate, 1),
                "limit_fill_rate": round(limit_fill_rate, 1),
                "tp1_hit_rate": round(tp_rates["tp1"], 1),
                "tp2_hit_rate": round(tp_rates["tp2"], 1),
                "tp3_hit_rate": round(tp_rates["tp3"], 1),
                "tp4_hit_rate": round(tp_rates["tp4"], 1),
                "sl_hit_rate": round(sl_rate, 1),
                "avg_time_to_tp1": avg_tp1,
                "avg_time_to_tp2": avg_tp2,
                "starting_balance": round(starting_balance, 2),
                "final_balance": round(final_balance, 2),
                "net_profit_loss": round(net_profit, 2),
                "growth_percent": round((net_profit / starting_balance * 100) if starting_balance else 0.0, 2),
                "max_drawdown": round(max_drawdown, 2),
                "best_session": best_session,
                "best_direction": best_direction,
                "best_exit_model": best_exit.get("label", "-"),
            },
            "equity_curve": equity_curve,
            "drawdown_curve": drawdown_points,
            "tp_success": [{"label": f"TP{idx}", "value": round(tp_rates[f'tp{idx}'], 1)} for idx in range(1, 5)],
            "by_direction": self._profit_by_bucket(tested, "direction"),
            "by_session": self._profit_by_bucket(
                [{**row, "session": classify_session(self._signal_datetime(row["date"], row["time_gmt"]) or utc_now())} for row in tested],
                "session",
            ),
            "by_hour": self._profit_by_bucket(
                [{**row, "hour": (self._signal_datetime(row["date"], row["time_gmt"]) or utc_now()).hour} for row in tested],
                "hour",
            ),
            "exit_model_comparison": exit_comp,
            "strategy_detective": strategy_detective,
        }

    def _build_strategy_detective(self, features: list[dict[str, Any]], results: list[dict[str, Any]], best_session: str, best_direction: str, best_exit_model: str) -> dict[str, Any]:
        if not features or not results:
            return {
                "winner_features": [],
                "loser_features": [],
                "edge_scores": [],
                "best_session": best_session,
                "best_direction": best_direction,
                "best_tp_model": best_exit_model,
                "likely_strategy_label": "-",
                "confidence_score": 0,
                "evidence": [],
            }
        result_map = {int(row["signal_call_id"]): row for row in results}
        enriched = []
        for feature in features:
            result = result_map.get(int(feature["signal_call_id"]))
            if not result:
                continue
            enriched.append({**feature, "profit_loss": safe_float(result.get("profit_loss")), "outcome": result.get("outcome", ""), "session_label": feature.get("session_label", classify_session(self._signal_datetime(feature["date"], feature["time_gmt"]) or utc_now()))})

        winners = [row for row in enriched if row["profit_loss"] > 0]
        losers = [row for row in enriched if row["profit_loss"] < 0]
        feature_extractors = [
            ("SELL direction", lambda row: row.get("direction") == "SELL"),
            ("BUY direction", lambda row: row.get("direction") == "BUY"),
            ("London morning", lambda row: row.get("session_label") == "London morning"),
            ("New York", lambda row: row.get("session_label") == "New York"),
            ("Fixed $5 ladder", lambda row: bool(row.get("is_fixed_5_dollar_ladder"))),
            ("Below M15 EMA50", lambda row: not bool(row.get("m15_price_above_ema50"))),
            ("Above M15 EMA50", lambda row: bool(row.get("m15_price_above_ema50"))),
            ("Near round number", lambda row: safe_float(row.get("distance_to_5_dollar_level"), 99) <= 1.0),
            ("MSS detected", lambda row: bool(row.get("mss_detected"))),
            ("Displacement detected", lambda row: bool(row.get("displacement_detected"))),
            ("FVG aligned", lambda row: bool(row.get("recent_fvg_detected")) and (bool(row.get("entry_inside_fvg")) or bool(row.get("entry_near_fvg")))),
            ("Order block aligned", lambda row: bool(row.get("order_block_detected")) and (bool(row.get("entry_inside_order_block")) or bool(row.get("entry_near_order_block")))),
            ("Liquidity sweep before signal", lambda row: any(bool(row.get(key)) for key in ("asian_high_swept_before_signal", "asian_low_swept_before_signal", "london_high_swept_before_signal", "london_low_swept_before_signal", "previous_day_high_swept_before_signal", "previous_day_low_swept_before_signal"))),
        ]

        def summarize(group: list[dict[str, Any]]) -> list[dict[str, Any]]:
            if not group:
                return []
            items = []
            total = len(group)
            for label, fn in feature_extractors:
                count = sum(1 for row in group if fn(row))
                if count:
                    items.append({"label": label, "count": count, "rate": round(count / total * 100, 1)})
            items.sort(key=lambda item: (item["rate"], item["count"]), reverse=True)
            return items[:6]

        winner_features = summarize(winners)
        loser_features = summarize(losers)
        edge_scores = []
        if winners or losers:
            for label, fn in feature_extractors:
                win_rate = (sum(1 for row in winners if fn(row)) / len(winners) * 100) if winners else 0.0
                lose_rate = (sum(1 for row in losers if fn(row)) / len(losers) * 100) if losers else 0.0
                edge = round(win_rate - lose_rate, 1)
                if abs(edge) >= 5:
                    edge_scores.append({"label": label, "winner_rate": round(win_rate, 1), "loser_rate": round(lose_rate, 1), "edge_score": edge})
            edge_scores.sort(key=lambda item: abs(item["edge_score"]), reverse=True)

        winning_setups: dict[str, int] = {}
        for row in winners:
            label = str(row.get("detected_setup") or "Unknown/mixed")
            winning_setups[label] = winning_setups.get(label, 0) + 1
        likely_strategy_label = max(winning_setups, key=winning_setups.get) if winning_setups else "Unknown/mixed"
        confidence = 0.0
        evidence: list[str] = []
        if winners:
            if winner_features:
                evidence.append(f"{winner_features[0]['rate']}% of winning trades shared: {winner_features[0]['label']}.")
                confidence += min(winner_features[0]["rate"] * 0.35, 25)
            if likely_strategy_label and likely_strategy_label != "Unknown/mixed":
                evidence.append(f"Most common winning setup label was {likely_strategy_label}.")
                confidence += 18
            if best_direction and best_direction != "-":
                evidence.append(f"Best direction by net result was {best_direction}.")
                confidence += 10
            if best_session and best_session != "-":
                evidence.append(f"Best session by net result was {best_session}.")
                confidence += 10
            if best_exit_model and best_exit_model != "-":
                evidence.append(f"Best exit model from replay was {best_exit_model}.")
                confidence += 8
        confidence = round(min(confidence, 99.0), 1)

        return {
            "winner_features": winner_features,
            "loser_features": loser_features,
            "edge_scores": edge_scores[:8],
            "best_session": best_session,
            "best_direction": best_direction,
            "best_tp_model": best_exit_model,
            "likely_strategy_label": likely_strategy_label,
            "confidence_score": confidence,
            "evidence": evidence[:6],
        }

    def _average_metric(self, rows: list[dict[str, Any]], key: str) -> str:
        values = [row[key] for row in rows if row.get(key) not in (None, "")]
        if not values:
            return "-"
        avg_seconds = sum(values) / len(values)
        return f"{round(avg_seconds / 60, 1)} min"

    def _best_bucket(self, rows: list[dict[str, Any]], key: str) -> str:
        buckets = self._profit_by_bucket(rows, key)
        if not buckets:
            return "-"
        best = max(buckets, key=lambda item: item["profit"])
        return str(best["label"])

    def _profit_by_bucket(self, rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
        buckets: dict[str, dict[str, Any]] = {}
        for row in rows:
            label = str(row.get(key, "Unknown"))
            bucket = buckets.setdefault(label, {"label": label, "profit": 0.0, "count": 0, "wins": 0})
            bucket["profit"] += safe_float(row.get("profit_loss"))
            bucket["count"] += 1
            if safe_float(row.get("profit_loss")) > 0:
                bucket["wins"] += 1
        return sorted(
            [{"label": item["label"], "profit": round(item["profit"], 2), "count": item["count"], "win_rate": round(item["wins"] / item["count"] * 100, 1) if item["count"] else 0.0} for item in buckets.values()],
            key=lambda item: item["profit"],
            reverse=True,
        )

    def _exit_model_comparison(self, tested: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in tested:
            grouped.setdefault(row["exit_model"], []).append(row)
        output = []
        for key, rows in grouped.items():
            final_balance = rows[-1]["balance_after"] if rows else 0.0
            output.append({"label": self.EXIT_MODE_LABELS.get(key, key), "exit_model": key, "final_balance": round(final_balance, 2), "net_profit": round(final_balance - rows[0]["balance_before"], 2) if rows else 0.0})
        output.sort(key=lambda item: item["final_balance"], reverse=True)
        return output

    def chart_preview(self, signal_call_id: int, timeframe: str = "M5") -> dict[str, Any]:
        with self.db.lock, self.db.connect() as conn:
            row = conn.execute("SELECT * FROM signal_calls WHERE id = ?", (signal_call_id,)).fetchone()
            feature = conn.execute("SELECT * FROM signal_feature_analysis WHERE signal_call_id = ?", (signal_call_id,)).fetchone()
            result = conn.execute("SELECT * FROM signal_backtest_results WHERE signal_call_id = ? ORDER BY id DESC LIMIT 1", (signal_call_id,)).fetchone()
        if row is None:
            return {"ok": False, "message": "Signal not found."}
        dt_signal = self._signal_datetime(row["date"], row["time_gmt"])
        if dt_signal is None:
            return {"ok": False, "message": "Signal date/time is invalid."}
        resolution = self.resolve_symbol(row["symbol"], row["broker_symbol"])
        symbol = resolution["broker_symbol"] or row["broker_symbol"] or row["symbol"]
        if self.mt5 is None or not self.ensure_mt5_ready():
            return {"ok": False, "message": "MT5 is not connected for chart preview."}
        candles, candle_meta = self._fetch_candles_with_meta(symbol, dt_signal - timedelta(hours=4), dt_signal + timedelta(hours=24), timeframe)
        feature_payload = self._row_to_feature_payload(feature) if feature is not None else {}
        return {
            "ok": True,
            "signal": self._row_to_signal_payload(row),
            "result": self._row_to_result_payload(result) if result is not None else None,
            "feature": feature_payload,
            "mapping": resolution,
            "candle_meta": candle_meta,
            "candles": [
                {
                    "time": candle["time"].isoformat(),
                    "open": candle["open"],
                    "high": candle["high"],
                    "low": candle["low"],
                    "close": candle["close"],
                }
                for candle in candles
            ],
            "timeframe": timeframe,
        }

    def export_dataset(self, batch_id: int, export_type: str) -> tuple[str, bytes, str]:
        payload = self.get_batch_payload(batch_id)
        if export_type == "analytics_xlsx":
            sheets = {
                "Summary": [
                    ["Metric", "Value"],
                    *[[key, str(value)] for key, value in payload["analytics"]["cards"].items()],
                ],
                "Results": self._sheet_from_dicts(payload["results"]),
                "Features": self._sheet_from_dicts(payload["features"]),
            }
            file_name = f"signal_lab_batch_{batch_id}_analytics.xlsx"
            return file_name, self._build_xlsx(sheets), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

        if export_type == "validated_csv":
            rows = payload["valid_signals"]
        elif export_type == "invalid_csv":
            rows = payload["invalid_signals"]
        elif export_type == "backtest_csv":
            rows = payload["results"]
        elif export_type == "features_csv":
            rows = payload["features"]
        elif export_type == "equity_curve_csv":
            rows = payload["analytics"]["equity_curve"]
        else:
            rows = payload["signals"]
        csv_bytes = self._dicts_to_csv(rows)
        return f"signal_lab_batch_{batch_id}_{export_type}.csv", csv_bytes, "text/csv; charset=utf-8"

    def _dicts_to_csv(self, rows: list[dict[str, Any]]) -> bytes:
        output = io.StringIO()
        if not rows:
            output.write("empty\n")
            return output.getvalue().encode("utf-8")
        fieldnames = list(rows[0].keys())
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=True) if isinstance(value, (dict, list)) else value for key, value in row.items()})
        return output.getvalue().encode("utf-8")

    def _sheet_from_dicts(self, rows: list[dict[str, Any]]) -> list[list[str]]:
        if not rows:
            return [["empty"], ["No rows"]]
        headers = list(rows[0].keys())
        sheet = [headers]
        for row in rows:
            sheet.append([json.dumps(row.get(header), ensure_ascii=True) if isinstance(row.get(header), (dict, list)) else str(row.get(header, "")) for header in headers])
        return sheet

    def _build_xlsx(self, sheets: dict[str, list[list[str]]]) -> bytes:
        content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
{sheet_overrides}
</Types>"""
        workbook_rels = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">']
        workbook = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>']
        sheet_parts: dict[str, bytes] = {}
        overrides = []
        for idx, (name, rows) in enumerate(sheets.items(), start=1):
            workbook_rels.append(f'<Relationship Id="rId{idx}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{idx}.xml"/>')
            workbook.append(f'<sheet name="{self._xml_escape(name)}" sheetId="{idx}" r:id="rId{idx}"/>')
            overrides.append(f'<Override PartName="/xl/worksheets/sheet{idx}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>')
            sheet_parts[f"xl/worksheets/sheet{idx}.xml"] = self._sheet_xml(rows)
        workbook.append("</sheets></workbook>")
        workbook_rels.append('<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>')
        workbook_rels.append("</Relationships>")
        root_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""
        styles = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="1"><font><sz val="11"/><name val="Aptos"/></font></fonts>
<fills count="1"><fill><patternFill patternType="none"/></fill></fills>
<borders count="1"><border/></borders>
<cellStyleXfs count="1"><xf/></cellStyleXfs>
<cellXfs count="1"><xf xfId="0"/></cellXfs>
</styleSheet>"""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", content_types.format(sheet_overrides="".join(overrides)))
            archive.writestr("_rels/.rels", root_rels)
            archive.writestr("xl/workbook.xml", "".join(workbook))
            archive.writestr("xl/_rels/workbook.xml.rels", "".join(workbook_rels))
            archive.writestr("xl/styles.xml", styles)
            for path, content in sheet_parts.items():
                archive.writestr(path, content)
        return buffer.getvalue()

    def _sheet_xml(self, rows: list[list[str]]) -> bytes:
        xml = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>']
        for row_idx, row in enumerate(rows, start=1):
            xml.append(f'<row r="{row_idx}">')
            for col_idx, value in enumerate(row, start=1):
                cell_ref = f"{self._column_letters(col_idx)}{row_idx}"
                xml.append(f'<c r="{cell_ref}" t="inlineStr"><is><t>{self._xml_escape(str(value))}</t></is></c>')
            xml.append("</row>")
        xml.append("</sheetData></worksheet>")
        return "".join(xml).encode("utf-8")

    def _column_letters(self, index: int) -> str:
        result = ""
        while index:
            index, remainder = divmod(index - 1, 26)
            result = chr(65 + remainder) + result
        return result

    def _xml_escape(self, value: str) -> str:
        return (
            value.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
        )
