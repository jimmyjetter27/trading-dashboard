from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import smtplib
import sys
import threading
import time
import traceback
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from history_backfill import BackfillConfig, HistoricalBackfillService
from signal_lab import SignalLabService
from orl_suite import (
    ATRService,
    CandlestickPatternService,
    GmailNotificationService,
    MT5CandleService,
    ORLAlertService,
    ORLAnalysisService,
    ORLFilterSettings,
    ORLHistoricalAnalyzerService,
    ORLLiveObserverService,
    ORLProfitCalculator,
    ORLSettings,
    ORLValidationService,
    SoundAlertService,
)

try:
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover
    mt5 = None

try:
    import winsound
except ImportError:  # pragma: no cover
    winsound = None


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "web"
DB_PATH = BASE_DIR / "trade_observer.sqlite3"
AURUMBOX_MEMORY_DB_PATH = BASE_DIR / "aurumbox_memory.sqlite3"
OBSERVERS_DIR = BASE_DIR.parent / "Bot" / "Observers"
HOST = "127.0.0.1"
PORT = int(os.environ.get("MT5_OBSERVER_PORT", "8765"))
USD_PER_GHS = 0.09
MT5_DISCOVERY_ROOT = Path(os.environ.get("MT5_DISCOVERY_ROOT", "C:/MT5"))
SECURITY_DEFAULT_TERMINAL_ROOT = Path(os.environ.get("MT5_SECURITY_DEFAULT_ROOT", "C:/MT5/JamesANabiah"))
SERVER_OUTPUT_LOG_PATH = BASE_DIR / "server_output.log"
SERVER_ERROR_LOG_PATH = BASE_DIR / "server_error.log"
DEFAULT_HISTORY_TERMINAL_PATH = Path(os.environ.get("MT5_HISTORY_TERMINAL_PATH", "C:/MT5/XMLive/terminal64.exe"))
DEFAULT_HISTORY_SYMBOLS = [
    "XAUUSDm",
    "XAUUSD",
    "GOLD",
    "BTCUSD",
    "BTCUSDm",
    "USOIL",
    "USOILm",
    "NAS100",
    "USTEC",
    "US30",
    "EURUSD",
    "GBPUSD",
    "USDJPY",
]
DEFAULT_HISTORY_TIMEFRAMES = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]
MT5_AUTHORIZED_RE = re.compile(
    r"'(?P<login>\d+)': authorized on (?P<server>.+?)"
    r"(?: through Access Point #(?P<access_point>\d+) \(ping: (?P<ping_ms>[\d.]+) ms, build (?P<build>\d+)\))?$"
)
MT5_PREVIOUS_AUTH_RE = re.compile(
    r"'(?P<login>\d+)': previous successful authorization performed from (?P<ip>[0-9a-fA-F:\.]+)"
    r" on (?P<date>\d{4}\.\d{2}\.\d{2}) (?P<time>\d{2}:\d{2}:\d{2})"
)
SECURITY_LOGIN_CACHE: dict[str, Any] = {"events": [], "summary": {}, "terminals": [], "limitations": [], "source_root": str(SECURITY_DEFAULT_TERMINAL_ROOT)}
SERVER_LOG_LOCK = threading.Lock()


@dataclass(frozen=True)
class AppConfig:
    poll_seconds: float = 1.0
    history_lookback_hours: int = 48
    price_history_limit: int = 240
    stop_warning_fraction: float = 0.18
    capital_warning_drawdown_fraction: float = 0.8
    account_blown_drawdown_fraction: float = 0.95
    m5_direction_fast_period: int = 5
    m5_direction_slow_period: int = 12
    m5_direction_confirm_candles: int = 3
    m5_direction_alert_cooldown_seconds: int = 240
    browser_autostart: bool = os.environ.get("MT5_OBSERVER_AUTO_OPEN", "0") == "1"
    preferred_symbol: str = ""
    symbol_candidates: tuple[str, ...] = ("XAUUSD", "XAUUSDm", "GOLD", "XAUUSD.")


CONFIG = AppConfig()


@dataclass(frozen=True)
class SMTPConfig:
    host: str
    port: int
    username: str
    password: str
    from_email: str
    to_email: str


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_now() -> str:
    return utc_now().isoformat()


def append_server_log(path: Path, message: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with SERVER_LOG_LOCK:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(f"[{iso_now()}] {message}\n")
    except Exception:
        pass


def log_output(message: str) -> None:
    append_server_log(SERVER_OUTPUT_LOG_PATH, message)


def log_error(message: str) -> None:
    append_server_log(SERVER_ERROR_LOG_PATH, message)


def json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, set):
        return list(value)
    return str(value)


def to_json(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=True, default=json_default).encode("utf-8")


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def fmt_number(value: Any, digits: int = 2) -> str:
    numeric = safe_float(value, float("nan"))
    if math.isnan(numeric):
        return "-"
    return f"{numeric:.{digits}f}"


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def build_grouped_days(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        day_key = (row.get("close_time") or row.get("open_time") or "")[:10]
        groups.setdefault(day_key, []).append(row)

    grouped_days = []
    for day, items in sorted(groups.items(), reverse=True):
        items_sorted = sorted(items, key=lambda item: item.get("open_time") or "")
        start_balance = None
        for item in items_sorted:
            value = item.get("entry_balance")
            if value is not None:
                start_balance = safe_float(value)
                break
        grouped_days.append(
            {
                "day": day,
                "rows": items,
                "start_balance": start_balance,
                "day_profit": sum(safe_float(item.get("profit")) for item in items),
            }
        )
    return grouped_days


def parse_trade_timestamp(row: dict[str, Any]) -> datetime | None:
    raw_value = row.get("open_time") or row.get("close_time")
    if not raw_value:
        return None
    try:
        return datetime.fromisoformat(str(raw_value))
    except ValueError:
        return None


def trade_time_bucket(hour: int) -> str:
    if 5 <= hour < 12:
        return "Morning"
    if 12 <= hour < 17:
        return "Afternoon"
    if 17 <= hour < 22:
        return "Evening"
    return "Overnight"


def build_journal_insights(rows: list[dict[str, Any]]) -> dict[str, Any]:
    weekday_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    bucket_order = ["Overnight", "Morning", "Afternoon", "Evening"]
    side_order = ["BUY", "SELL"]

    if not rows:
        return {
            "cards": [],
            "day_of_week": [],
            "time_of_day": [],
            "top_setups": [],
            "ideas": [],
        }

    def make_bucket(label: str) -> dict[str, Any]:
        return {"label": label, "count": 0, "wins": 0, "losses": 0, "total_profit": 0.0}

    weekday_stats = {label: make_bucket(label) for label in weekday_order}
    time_stats = {label: make_bucket(label) for label in bucket_order}
    hour_stats = {f"{hour:02d}:00": make_bucket(f"{hour:02d}:00") for hour in range(24)}
    side_stats = {label: make_bucket(label) for label in side_order}
    month_stats: dict[str, dict[str, Any]] = {}
    daily_stats: dict[str, dict[str, Any]] = {}
    symbol_stats: dict[str, dict[str, Any]] = {}
    setup_stats: dict[str, dict[str, Any]] = {}
    total_profit = 0.0
    win_amounts: list[float] = []
    loss_amounts: list[float] = []
    hold_minutes_wins: list[float] = []
    hold_minutes_losses: list[float] = []
    longest_win_streak = 0
    longest_loss_streak = 0
    current_win_streak = 0
    current_loss_streak = 0

    ordered_rows = sorted(
        rows,
        key=lambda row: (row.get("close_time") or row.get("open_time") or "", row.get("ticket") or 0),
    )

    for row in ordered_rows:
        timestamp = parse_trade_timestamp(row)
        if timestamp is None:
            continue
        profit = safe_float(row.get("profit"))
        symbol = str(row.get("symbol") or "Unknown")
        side = str(row.get("side") or "-").upper()
        volume = safe_float(row.get("volume"))
        weekday_label = timestamp.strftime("%A")
        bucket_label = trade_time_bucket(timestamp.hour)
        hour_label = f"{timestamp.hour:02d}:00"
        month_label = timestamp.strftime("%Y-%m")
        day_label = timestamp.strftime("%Y-%m-%d")
        total_profit += profit

        weekday_item = weekday_stats.setdefault(weekday_label, make_bucket(weekday_label))
        weekday_item["count"] += 1
        weekday_item["total_profit"] += profit
        weekday_item["wins"] += 1 if profit > 0 else 0
        weekday_item["losses"] += 1 if profit < 0 else 0

        bucket_item = time_stats.setdefault(bucket_label, make_bucket(bucket_label))
        bucket_item["count"] += 1
        bucket_item["total_profit"] += profit
        bucket_item["wins"] += 1 if profit > 0 else 0
        bucket_item["losses"] += 1 if profit < 0 else 0

        hour_item = hour_stats.setdefault(hour_label, make_bucket(hour_label))
        hour_item["count"] += 1
        hour_item["total_profit"] += profit
        hour_item["wins"] += 1 if profit > 0 else 0
        hour_item["losses"] += 1 if profit < 0 else 0

        side_item = side_stats.setdefault(side, make_bucket(side))
        side_item["count"] += 1
        side_item["total_profit"] += profit
        side_item["wins"] += 1 if profit > 0 else 0
        side_item["losses"] += 1 if profit < 0 else 0

        month_item = month_stats.setdefault(month_label, make_bucket(month_label))
        month_item["count"] += 1
        month_item["total_profit"] += profit
        month_item["wins"] += 1 if profit > 0 else 0
        month_item["losses"] += 1 if profit < 0 else 0

        daily_item = daily_stats.setdefault(day_label, make_bucket(day_label))
        daily_item["count"] += 1
        daily_item["total_profit"] += profit
        daily_item["wins"] += 1 if profit > 0 else 0
        daily_item["losses"] += 1 if profit < 0 else 0

        symbol_item = symbol_stats.setdefault(symbol, make_bucket(symbol))
        symbol_item["count"] += 1
        symbol_item["total_profit"] += profit
        symbol_item["wins"] += 1 if profit > 0 else 0
        symbol_item["losses"] += 1 if profit < 0 else 0

        setup_key = f"{symbol}|{side}|{volume:.2f}"
        setup_item = setup_stats.setdefault(
            setup_key,
            {
                "label": f"{symbol} {side} · {volume:.2f} lot",
                "symbol": symbol,
                "side": side,
                "volume": volume,
                "count": 0,
                "wins": 0,
                "losses": 0,
                "total_profit": 0.0,
            },
        )
        setup_item["count"] += 1
        setup_item["total_profit"] += profit
        setup_item["wins"] += 1 if profit > 0 else 0
        setup_item["losses"] += 1 if profit < 0 else 0

        open_time = row.get("open_time")
        close_time = row.get("close_time")
        if open_time and close_time:
            try:
                hold_minutes = max(
                    0.0,
                    (datetime.fromisoformat(str(close_time)) - datetime.fromisoformat(str(open_time))).total_seconds() / 60.0,
                )
                if profit > 0:
                    hold_minutes_wins.append(hold_minutes)
                elif profit < 0:
                    hold_minutes_losses.append(hold_minutes)
            except ValueError:
                pass

        if profit > 0:
            win_amounts.append(profit)
            current_win_streak += 1
            current_loss_streak = 0
        elif profit < 0:
            loss_amounts.append(abs(profit))
            current_loss_streak += 1
            current_win_streak = 0
        else:
            current_win_streak = 0
            current_loss_streak = 0

        longest_win_streak = max(longest_win_streak, current_win_streak)
        longest_loss_streak = max(longest_loss_streak, current_loss_streak)

    def finalize(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        finalized: list[dict[str, Any]] = []
        for item in items:
            count = int(item.get("count") or 0)
            total_profit = safe_float(item.get("total_profit"))
            wins = int(item.get("wins") or 0)
            losses = int(item.get("losses") or 0)
            finalized.append(
                {
                    **item,
                    "count": count,
                    "wins": wins,
                    "losses": losses,
                    "total_profit": total_profit,
                    "average_profit": total_profit / count if count else 0.0,
                    "win_rate": wins / count if count else 0.0,
                }
            )
        return finalized

    weekday_rows = [item for item in finalize([weekday_stats[label] for label in weekday_order]) if item["count"] > 0]
    time_rows = [item for item in finalize([time_stats[label] for label in bucket_order]) if item["count"] > 0]
    hour_rows = [item for item in finalize([hour_stats[f"{hour:02d}:00"] for hour in range(24)]) if item["count"] > 0]
    side_rows = [item for item in finalize([side_stats[label] for label in side_order]) if item["count"] > 0]
    month_rows = [item for item in finalize(list(month_stats.values())) if item["count"] > 0]
    daily_rows = [item for item in finalize(list(daily_stats.values())) if item["count"] > 0]
    symbol_rows = [item for item in finalize(list(symbol_stats.values())) if item["count"] > 0]
    setup_rows = [item for item in finalize(list(setup_stats.values())) if item["count"] > 0]
    setup_rows.sort(key=lambda item: (item["win_rate"], item["total_profit"], item["count"]), reverse=True)
    hour_rows.sort(key=lambda item: (item["total_profit"], item["win_rate"], item["count"]), reverse=True)
    month_rows.sort(key=lambda item: item["label"])
    daily_rows.sort(key=lambda item: item["label"])

    cards: list[dict[str, Any]] = []
    ideas: list[str] = []
    total_trades = len([row for row in ordered_rows if parse_trade_timestamp(row) is not None])
    total_wins = len(win_amounts)
    total_losses = len(loss_amounts)
    average_win = sum(win_amounts) / total_wins if total_wins else 0.0
    average_loss = sum(loss_amounts) / total_losses if total_losses else 0.0
    expectancy = total_profit / total_trades if total_trades else 0.0
    profit_factor = (sum(win_amounts) / sum(loss_amounts)) if loss_amounts else None

    if weekday_rows:
        best_day = max(weekday_rows, key=lambda item: item["total_profit"])
        worst_day = min(weekday_rows, key=lambda item: item["total_profit"])
        cards.append(
            {
                "title": "Best Day",
                "value": best_day["label"],
                "meta": f"${best_day['total_profit']:.2f} across {best_day['count']} trade(s)",
                "tone": "positive" if best_day["total_profit"] >= 0 else "negative",
            }
        )
        cards.append(
            {
                "title": "Weakest Day",
                "value": worst_day["label"],
                "meta": f"${worst_day['total_profit']:.2f} across {worst_day['count']} trade(s)",
                "tone": "negative" if worst_day["total_profit"] < 0 else "neutral",
            }
        )
        if worst_day["total_profit"] < 0:
            ideas.append(f"{worst_day['label']} is currently your weakest weekday. That may be a day to trade smaller or be more selective.")

    if time_rows:
        best_window = max(time_rows, key=lambda item: item["total_profit"])
        worst_window = min(time_rows, key=lambda item: item["total_profit"])
        cards.append(
            {
                "title": "Best Time Window",
                "value": best_window["label"],
                "meta": f"${best_window['total_profit']:.2f} with {best_window['win_rate'] * 100:.0f}% win rate",
                "tone": "positive" if best_window["total_profit"] >= 0 else "negative",
            }
        )
        cards.append(
            {
                "title": "Needs Attention",
                "value": worst_window["label"],
                "meta": f"${worst_window['total_profit']:.2f} with {worst_window['count']} trade(s)",
                "tone": "negative" if worst_window["total_profit"] < 0 else "neutral",
            }
        )
        if best_window["label"] == "Morning":
            ideas.append("Your morning trades are outperforming the rest of the day. That may be where your edge is clearest.")
        elif best_window["label"] == "Afternoon":
            ideas.append("Your afternoon trades are carrying the strongest returns right now. That could be worth leaning into.")

    if side_rows:
        best_side = max(side_rows, key=lambda item: item["total_profit"])
        worst_side = min(side_rows, key=lambda item: item["total_profit"])
        cards.append(
            {
                "title": "Best Direction",
                "value": best_side["label"],
                "meta": f"${best_side['total_profit']:.2f} over {best_side['count']} trade(s) with {(best_side['win_rate'] * 100):.0f}% wins",
                "tone": "positive" if best_side["total_profit"] >= 0 else "negative",
            }
        )
        if best_side["label"] != worst_side["label"] and best_side["total_profit"] > worst_side["total_profit"]:
            ideas.append(
                f"Your {best_side['label']} trades are outperforming your {worst_side['label']} trades. That may be the cleaner side of your edge right now."
            )

    if symbol_rows:
        best_symbol = max(symbol_rows, key=lambda item: item["total_profit"])
        cards.append(
            {
                "title": "Strongest Market",
                "value": best_symbol["label"],
                "meta": f"${best_symbol['total_profit']:.2f} across {best_symbol['count']} trade(s)",
                "tone": "positive" if best_symbol["total_profit"] >= 0 else "negative",
            }
        )

    if profit_factor is not None:
        cards.append(
            {
                "title": "Profit Factor",
                "value": f"{profit_factor:.2f}",
                "meta": f"Avg win ${average_win:.2f} vs avg loss ${average_loss:.2f}",
                "tone": "positive" if profit_factor >= 1 else "negative",
            }
        )
    elif total_wins:
        cards.append(
            {
                "title": "Profit Factor",
                "value": "No losses",
                "meta": f"{total_wins} winning trade(s) recorded in this insight set",
                "tone": "positive",
            }
        )

    cards.append(
        {
            "title": "Expectancy",
            "value": f"${expectancy:.2f}",
            "meta": f"Average outcome per trade across {total_trades} trade(s)",
            "tone": "positive" if expectancy >= 0 else "negative",
        }
    )

    if hour_rows:
        best_hour = max(hour_rows, key=lambda item: (item["total_profit"], item["win_rate"], item["count"]))
        cards.append(
            {
                "title": "Best Hour",
                "value": best_hour["label"],
                "meta": f"${best_hour['total_profit']:.2f} over {best_hour['count']} trade(s)",
                "tone": "positive" if best_hour["total_profit"] >= 0 else "negative",
            }
        )
        if best_hour["count"] >= 2:
            ideas.append(
                f"Your best trading hour has been around {best_hour['label']}. That may be a strong window to plan around instead of forcing activity all day."
            )

    if month_rows:
        best_month = max(month_rows, key=lambda item: item["total_profit"])
        worst_month = min(month_rows, key=lambda item: item["total_profit"])
        cards.append(
            {
                "title": "Best Month",
                "value": best_month["label"],
                "meta": f"${best_month['total_profit']:.2f} across {best_month['count']} trade(s)",
                "tone": "positive" if best_month["total_profit"] >= 0 else "negative",
            }
        )
        if worst_month["total_profit"] < 0:
            ideas.append(
                f"{worst_month['label']} was your roughest month so far. Reviewing what changed around that period may reveal avoidable mistakes or conditions you handle poorly."
            )

    streak_value = f"{longest_win_streak}W / {longest_loss_streak}L"
    cards.append(
        {
            "title": "Longest Streaks",
            "value": streak_value,
            "meta": "Winning streak vs losing streak",
            "tone": "positive" if longest_win_streak >= longest_loss_streak else "neutral",
        }
    )

    repeated_setups = [item for item in setup_rows if item["count"] >= 2]
    if repeated_setups:
        best_setup = repeated_setups[0]
        cards.append(
            {
                "title": "Most Reliable Pattern",
                "value": best_setup["label"],
                "meta": f"{best_setup['win_rate'] * 100:.0f}% win rate over {best_setup['count']} trade(s)",
                "tone": "positive" if best_setup["total_profit"] >= 0 else "negative",
            }
        )
        ideas.append(f"{best_setup['label']} looks like a recurring edge. It may deserve more deliberate screen time when it appears.")
        underused = [item for item in repeated_setups if item["count"] <= 3 and item["win_rate"] >= 0.66 and item["total_profit"] > 0]
        if underused:
            underused_best = max(underused, key=lambda item: (item["win_rate"], item["total_profit"]))
            ideas.append(f"Underused winner: {underused_best['label']} is profitable with a {underused_best['win_rate'] * 100:.0f}% win rate, but you have only taken it {underused_best['count']} times.")

    if hold_minutes_wins and hold_minutes_losses:
        avg_hold_wins = sum(hold_minutes_wins) / len(hold_minutes_wins)
        avg_hold_losses = sum(hold_minutes_losses) / len(hold_minutes_losses)
        if avg_hold_losses > avg_hold_wins * 1.25:
            ideas.append(
                f"Your losing trades are being held longer than your winners on average ({avg_hold_losses:.0f} min vs {avg_hold_wins:.0f} min). Cutting weak trades faster may improve your expectancy."
            )
        elif avg_hold_wins > avg_hold_losses * 1.25:
            ideas.append(
                f"Your winners tend to run longer than your losers ({avg_hold_wins:.0f} min vs {avg_hold_losses:.0f} min). That patience looks constructive when you are on the right side."
            )

    if daily_rows:
        worst_trading_day = min(daily_rows, key=lambda item: item["total_profit"])
        best_trading_day = max(daily_rows, key=lambda item: item["total_profit"])
        if worst_trading_day["total_profit"] < 0:
            ideas.append(
                f"Your largest losing day was {worst_trading_day['label']} at ${worst_trading_day['total_profit']:.2f}, while your best day reached ${best_trading_day['total_profit']:.2f}. Protecting against those deep red days may matter more than squeezing a few extra winners."
            )

    if not ideas and rows:
        ideas.append("As more trades build up, this section will get better at spotting your strongest days, time windows, and recurring trade patterns.")

    return {
        "cards": cards[:8],
        "day_of_week": weekday_rows,
        "time_of_day": time_rows,
        "top_setups": setup_rows[:5],
        "ideas": ideas[:5],
    }


def apply_special_filter(rows: list[dict[str, Any]], special_filter: str) -> list[dict[str, Any]]:
    if special_filter == "best_trade" and rows:
        return [max(rows, key=lambda row: safe_float(row.get("profit")))]
    if special_filter == "worst_trade" and rows:
        return [min(rows, key=lambda row: safe_float(row.get("profit")))]
    if special_filter in {"best_day", "worst_day"} and rows:
        grouped = build_grouped_days(rows)
        chooser = max if special_filter == "best_day" else min
        selected = chooser(grouped, key=lambda day: safe_float(day.get("day_profit")))
        return selected["rows"]
    return rows


def parse_exact_date(exact_date: str) -> tuple[datetime, datetime] | None:
    if not exact_date:
        return None
    try:
        target = datetime.strptime(exact_date, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return None
    return target, target + timedelta(days=1)


def normalize_account_server(server: Any) -> str:
    return str(server or "").strip()


def normalize_account_login(login: Any) -> int | None:
    try:
        if login in ("", None):
            return None
        return int(login)
    except (TypeError, ValueError):
        return None


def account_scope_key(login: Any, server: Any) -> str:
    normalized_login = normalize_account_login(login)
    normalized_server = normalize_account_server(server) or "unknown"
    return f"{normalized_server}::{normalized_login if normalized_login is not None else 'unknown'}"


MAIN_LIVE_TERMINAL_PATH = r"C:\MT5\JamesANabiah\terminal64.exe"
SECOND_LIVE_TERMINAL_PATH = r"C:\MT5\SecondDemo\terminal64.exe"


def normalized_windows_path(value: str) -> str:
    return str(value or "").strip().replace("/", "\\").lower()


def is_known_live_terminal_path(value: str) -> bool:
    normalized = normalized_windows_path(value)
    return normalized in {
        normalized_windows_path(MAIN_LIVE_TERMINAL_PATH),
        normalized_windows_path(SECOND_LIVE_TERMINAL_PATH),
    }


def scoped_history_ticket(ticket: int, account_login: int | None, account_server: str) -> int:
    base = f"{normalize_account_login(account_login) or 0}|{normalize_account_server(account_server)}|{int(ticket)}"
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:15]
    return int(digest, 16)


def discover_mt5_terminals(root: Path | None = None) -> list[dict[str, str]]:
    base = root or MT5_DISCOVERY_ROOT
    if not base.exists() or not base.is_dir():
        return []
    items: list[dict[str, str]] = []
    for child in sorted(base.iterdir(), key=lambda item: item.name.lower()):
        if not child.is_dir():
            continue
        terminal_path = child / "terminal64.exe"
        if not terminal_path.exists():
            continue
        items.append(
            {
                "alias": child.name,
                "terminal_path": str(terminal_path),
                "folder": str(child),
            }
        )
    return items


def discover_mt5_terminals_from_roots(roots: list[Path]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for root in roots:
        terminal_path = root / "terminal64.exe"
        if not terminal_path.exists():
            continue
        normalized = str(root).lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        items.append(
            {
                "alias": root.name,
                "terminal_path": str(terminal_path),
                "folder": str(root),
            }
        )
    return items


def parse_mt5_log_datetime(log_file: Path, time_text: str) -> str | None:
    stem = log_file.stem
    if not re.fullmatch(r"\d{8}", stem):
        return None
    try:
        dt = datetime.strptime(f"{stem} {time_text}", "%Y%m%d %H:%M:%S.%f").replace(tzinfo=UTC)
    except ValueError:
        try:
            dt = datetime.strptime(f"{stem} {time_text}", "%Y%m%d %H:%M:%S").replace(tzinfo=UTC)
        except ValueError:
            return None
    return dt.isoformat()


def read_mt5_login_events(
    root: Path | None = None,
    *,
    roots: list[Path] | None = None,
    max_files_per_terminal: int = 12,
) -> dict[str, Any]:
    terminals = discover_mt5_terminals_from_roots(roots) if roots else discover_mt5_terminals(root)
    events: list[dict[str, Any]] = []
    parsed_files = 0

    for terminal in terminals:
        alias = terminal["alias"]
        terminal_path = Path(terminal["terminal_path"])
        terminal_dir = terminal_path.parent
        logs_dir = terminal_dir / "logs"
        if not logs_dir.exists():
            continue

        log_files = sorted(
            [item for item in logs_dir.iterdir() if item.is_file() and re.fullmatch(r"\d{8}\.log", item.name)],
            key=lambda item: item.name,
            reverse=True,
        )[:max_files_per_terminal]

        for log_file in log_files:
            parsed_files += 1
            try:
                lines = log_file.read_text(encoding="utf-16", errors="replace").splitlines()
            except UnicodeError:
                lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue

            last_event_by_login: dict[str, dict[str, Any]] = {}
            for line in lines:
                parts = line.split("\t", 4)
                if len(parts) < 5:
                    continue
                _, severity, time_text, source, message = parts
                auth_match = MT5_AUTHORIZED_RE.search(message)
                if auth_match:
                    event = {
                        "terminal_alias": alias,
                        "terminal_path": str(terminal_dir),
                        "log_file": log_file.name,
                        "severity": severity,
                        "source": source,
                        "event_time": parse_mt5_log_datetime(log_file, time_text),
                        "account_login": int(auth_match.group("login")),
                        "server": auth_match.group("server").strip(),
                        "access_point": int(auth_match.group("access_point")) if auth_match.group("access_point") else None,
                        "ping_ms": safe_float(auth_match.group("ping_ms")) if auth_match.group("ping_ms") else 0.0,
                        "build": int(auth_match.group("build")) if auth_match.group("build") else None,
                        "previous_ip": "",
                        "previous_authorized_at": "",
                    }
                    events.append(event)
                    last_event_by_login[auth_match.group("login")] = event
                    continue

                prev_match = MT5_PREVIOUS_AUTH_RE.search(message)
                if prev_match:
                    prior = last_event_by_login.get(prev_match.group("login"))
                    if prior is not None:
                        prior["previous_ip"] = prev_match.group("ip")
                        try:
                            previous_dt = datetime.strptime(
                                f"{prev_match.group('date')} {prev_match.group('time')}",
                                "%Y.%m.%d %H:%M:%S",
                            ).replace(tzinfo=UTC)
                            prior["previous_authorized_at"] = previous_dt.isoformat()
                        except ValueError:
                            prior["previous_authorized_at"] = f"{prev_match.group('date')} {prev_match.group('time')}"

    events.sort(key=lambda item: item.get("event_time") or "", reverse=True)
    unique_accounts = sorted({item["account_login"] for item in events})
    unique_ips = sorted({item["previous_ip"] for item in events if item.get("previous_ip")})
    latest = events[0]["event_time"] if events else ""
    oldest = events[-1]["event_time"] if events else ""
    return {
        "events": events,
        "summary": {
            "terminals_scanned": len(terminals),
            "log_files_scanned": parsed_files,
            "authorization_events": len(events),
            "unique_accounts": len(unique_accounts),
            "unique_previous_ips": len(unique_ips),
            "latest_event_time": latest,
            "oldest_event_time": oldest,
        },
        "terminals": terminals,
        "limitations": [
            "MT5 logs show terminal-side authorization history, not the real human identity behind a login.",
            "The 'previous successful authorization' IP is the IP from the last successful login MT5 knows about.",
            "If a terminal log was deleted or rotated out, older login evidence may no longer be available.",
        ],
        "source_root": str(roots[0] if roots else (root or MT5_DISCOVERY_ROOT)),
    }


def resolve_security_log_roots() -> list[Path]:
    roots: list[Path] = []
    seen: set[str] = set()

    def add_root(path_value: str | Path | None) -> None:
        if not path_value:
            return
        candidate = Path(path_value)
        root = candidate if candidate.is_dir() else candidate.parent
        key = str(root).lower()
        if key in seen or not root.exists():
            return
        seen.add(key)
        roots.append(root)

    profile = getattr(globals().get("MONITOR", None), "connection_profile", None) or {}
    add_root(str(profile.get("terminal_path", "")).strip())

    selected_alias = getattr(globals().get("MONITOR", None), "selected_profile_alias", "") or ""
    if selected_alias:
        saved_profile = DB.find_account_profile(selected_alias) if "DB" in globals() else None
        if saved_profile:
            add_root(str(saved_profile.get("terminal_path", "")).strip())

    add_root(SECURITY_DEFAULT_TERMINAL_ROOT)

    if not roots:
        roots.extend(Path(item["folder"]) for item in discover_mt5_terminals())

    return roots


def refresh_security_login_cache() -> dict[str, Any]:
    global SECURITY_LOGIN_CACHE
    SECURITY_LOGIN_CACHE = read_mt5_login_events(roots=resolve_security_log_roots(), max_files_per_terminal=12)
    return SECURITY_LOGIN_CACHE


def normalize_side(side: str) -> str:
    return side.strip().lower()


def load_smtp_config() -> SMTPConfig | None:
    candidates = [
        OBSERVERS_DIR / "test_email.py",
        OBSERVERS_DIR / "price_alert_bot.py",
    ]
    pattern = re.compile(r'^(SMTP_HOST|SMTP_PORT|SMTP_USERNAME|SMTP_PASSWORD|FROM_EMAIL|TO_EMAIL)\s*=\s*"?(.*?)"?\s*$')
    values: dict[str, str] = {}
    for path in candidates:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            match = pattern.match(line.strip())
            if match:
                values[match.group(1)] = match.group(2)
        if {"SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD", "FROM_EMAIL", "TO_EMAIL"} <= values.keys():
            break
    required = {"SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD", "FROM_EMAIL", "TO_EMAIL"}
    if not required <= values.keys():
        return None
    try:
        return SMTPConfig(
            host=values["SMTP_HOST"],
            port=int(values["SMTP_PORT"]),
            username=values["SMTP_USERNAME"],
            password=values["SMTP_PASSWORD"],
            from_email=values["FROM_EMAIL"],
            to_email=values["TO_EMAIL"],
        )
    except ValueError:
        return None


def period_bounds(now: datetime) -> dict[str, tuple[datetime, datetime]]:
    start_today = datetime(now.year, now.month, now.day, tzinfo=UTC)
    start_week = start_today - timedelta(days=start_today.weekday())
    start_month = datetime(now.year, now.month, 1, tzinfo=UTC)
    start_year = datetime(now.year, 1, 1, tzinfo=UTC)
    end_time = now + timedelta(days=2)
    return {
        "week": (start_week, end_time),
        "month": (start_month, end_time),
        "year": (start_year, end_time),
    }


def session_time_label(hour: int, minute: int = 0) -> str:
    return f"{hour:02d}:{minute:02d} UTC"


def utc_datetime_label(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def range_window(range_key: str, now: datetime | None = None) -> tuple[datetime, datetime]:
    current = now or utc_now()
    start_today = datetime(current.year, current.month, current.day, tzinfo=UTC)
    start_week = start_today - timedelta(days=start_today.weekday())
    start_month = datetime(current.year, current.month, 1, tzinfo=UTC)
    start_year = datetime(current.year, 1, 1, tzinfo=UTC)
    start_map = {
        "today": start_today,
        "week": start_week,
        "month": start_month,
        "year": start_year,
        "all": current - timedelta(days=3650),
    }
    return start_map.get((range_key or "all").strip().lower(), start_month), current + timedelta(days=2)


def resolve_time_window(range_key: str = "all", exact_date: str = "") -> tuple[datetime, datetime]:
    exact_window = parse_exact_date(exact_date)
    if exact_window:
        return exact_window
    return range_window(range_key)


def market_sessions_snapshot(now: datetime | None = None) -> dict[str, Any]:
    current = now or utc_now()
    current_minutes = current.hour * 60 + current.minute
    current_seconds = current.second
    sessions = [
        {"key": "sydney", "name": "Sydney", "open": 21 * 60, "close": 6 * 60, "color": "support"},
        {"key": "tokyo", "name": "Tokyo", "open": 0, "close": 9 * 60, "color": "pivot"},
        {"key": "london", "name": "London", "open": 8 * 60, "close": 17 * 60, "color": "bullish"},
        {"key": "new_york", "name": "New York", "open": 13 * 60, "close": 22 * 60, "color": "resistance"},
    ]
    items: list[dict[str, Any]] = []
    open_sessions: list[str] = []

    for session in sessions:
        open_minute = int(session["open"])
        close_minute = int(session["close"])
        crosses_midnight = close_minute <= open_minute
        is_open = (
            current_minutes >= open_minute or current_minutes < close_minute
        ) if crosses_midnight else (open_minute <= current_minutes < close_minute)

        if is_open:
            target_minutes = close_minute
            remaining = (target_minutes - current_minutes) % (24 * 60)
            status = "open"
            countdown_label = "Closes in"
            open_sessions.append(str(session["name"]))
        else:
            target_minutes = open_minute
            remaining = (target_minutes - current_minutes) % (24 * 60)
            status = "closed"
            countdown_label = "Opens in"

        hours = remaining // 60
        minutes = remaining % 60
        items.append(
            {
                "key": session["key"],
                "name": session["name"],
                "status": status,
                "countdown_label": countdown_label,
                "countdown": f"{hours:02d}h {minutes:02d}m",
                "countdown_minutes": remaining,
                "opens_at": session_time_label(open_minute // 60, open_minute % 60),
                "closes_at": session_time_label(close_minute // 60, close_minute % 60),
                "color": session["color"],
            }
        )

    return {
        "generated_at": current.isoformat(),
        "generated_at_utc_label": utc_datetime_label(current),
        "current_utc_label": utc_datetime_label(current),
        "current_utc_time": f"{current.hour:02d}:{current.minute:02d}:{current.second:02d} UTC",
        "clock": {
            "hour": current.hour,
            "minute": current.minute,
            "second": current_seconds,
        },
        "timezone": "UTC",
        "open_sessions": open_sessions,
        "items": items,
    }


def infer_close_reason(side: str, close_price: float, sl: float, tp: float) -> str:
    if tp and math.isclose(close_price, tp, rel_tol=0.0, abs_tol=0.03):
        return "take_profit"
    if sl and math.isclose(close_price, sl, rel_tol=0.0, abs_tol=0.03):
        return "stop_loss"
    if side == "buy":
        if tp and close_price >= tp:
            return "take_profit"
        if sl and close_price <= sl:
            return "stop_loss"
    if side == "sell":
        if tp and close_price <= tp:
            return "take_profit"
        if sl and close_price >= sl:
            return "stop_loss"
    return "manual_or_other"


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()
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

                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS trade_records (
                    ticket INTEGER PRIMARY KEY,
                    position_id INTEGER,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    volume REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    stop_loss REAL,
                    take_profit REAL,
                    open_time TEXT NOT NULL,
                    close_price REAL,
                    close_time TEXT,
                    profit REAL DEFAULT 0,
                    swap REAL DEFAULT 0,
                    commission REAL DEFAULT 0,
                    reason TEXT DEFAULT '',
                    status TEXT NOT NULL,
                    entry_balance REAL DEFAULT 0,
                    exit_balance REAL DEFAULT 0,
                    last_price REAL DEFAULT 0,
                    last_pips REAL DEFAULT 0,
                    max_profit REAL DEFAULT 0,
                    max_drawdown REAL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS mt5_history_records (
                    ticket INTEGER PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    volume REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    stop_loss REAL DEFAULT 0,
                    take_profit REAL DEFAULT 0,
                    open_time TEXT NOT NULL,
                    close_price REAL DEFAULT 0,
                    close_time TEXT,
                    profit REAL DEFAULT 0,
                    reason TEXT DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'closed',
                    imported_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS trade_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    ticket INTEGER,
                    message TEXT NOT NULL,
                    payload TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS account_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    balance REAL NOT NULL,
                    equity REAL NOT NULL,
                    profit REAL NOT NULL,
                    margin REAL NOT NULL,
                    free_margin REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS trader_journal_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    journal_date TEXT NOT NULL,
                    scope_key TEXT NOT NULL,
                    scope_label TEXT NOT NULL,
                    session_grade TEXT DEFAULT '',
                    followed_plan TEXT DEFAULT '',
                    emotional_state TEXT DEFAULT '',
                    best_setup TEXT DEFAULT '',
                    tags_json TEXT DEFAULT '[]',
                    market_conditions TEXT DEFAULT '',
                    what_went_well TEXT DEFAULT '',
                    mistakes TEXT DEFAULT '',
                    lesson TEXT DEFAULT '',
                    next_focus TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(journal_date, scope_key)
                );

                CREATE TABLE IF NOT EXISTS price_ticks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    bid REAL NOT NULL,
                    ask REAL NOT NULL,
                    last REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_trade_records_open_time ON trade_records(open_time);
                CREATE INDEX IF NOT EXISTS idx_trade_records_close_time ON trade_records(close_time);
                CREATE INDEX IF NOT EXISTS idx_trade_records_status ON trade_records(status);
                CREATE INDEX IF NOT EXISTS idx_mt5_history_open_time ON mt5_history_records(open_time);
                CREATE INDEX IF NOT EXISTS idx_mt5_history_close_time ON mt5_history_records(close_time);
                CREATE INDEX IF NOT EXISTS idx_trade_events_ts ON trade_events(ts);
                CREATE INDEX IF NOT EXISTS idx_account_snapshots_ts ON account_snapshots(ts);
                CREATE INDEX IF NOT EXISTS idx_price_ticks_ts ON price_ticks(ts);
                """
            )
            self._ensure_column(conn, "trade_records", "account_login", "INTEGER")
            self._ensure_column(conn, "trade_records", "account_server", "TEXT DEFAULT ''")
            self._ensure_column(conn, "mt5_history_records", "account_login", "INTEGER")
            self._ensure_column(conn, "mt5_history_records", "account_server", "TEXT DEFAULT ''")
            self._ensure_column(conn, "mt5_history_records", "original_ticket", "INTEGER")
            self._ensure_column(conn, "trade_events", "account_login", "INTEGER")
            self._ensure_column(conn, "trade_events", "account_server", "TEXT DEFAULT ''")
            self._ensure_column(conn, "account_snapshots", "account_login", "INTEGER")
            self._ensure_column(conn, "account_snapshots", "account_server", "TEXT DEFAULT ''")
            conn.commit()

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        existing = {row["name"] for row in rows}
        if column in existing:
            return
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def get_setting(self, key: str, default: str = "") -> str:
        with self.lock, self.connect() as conn:
            row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.lock, self.connect() as conn:
            conn.execute(
                """
                INSERT INTO app_settings(key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )
            conn.commit()

    def get_account_profiles(self) -> list[dict[str, Any]]:
        raw = self.get_setting("account_profiles", "[]")
        try:
            profiles = json.loads(raw)
        except json.JSONDecodeError:
            profiles = []
        if not isinstance(profiles, list):
            return []
        cleaned = []
        for item in profiles:
            if not isinstance(item, dict):
                continue
            alias = str(item.get("alias", "")).strip()
            if not alias:
                continue
            cleaned.append(
                {
                    "alias": alias,
                    "login": normalize_account_login(item.get("login")),
                    "password": str(item.get("password", "")),
                    "server": normalize_account_server(item.get("server")),
                    "terminal_path": str(item.get("terminal_path", "")).strip(),
                    "group": str(item.get("group", "")).strip(),
                }
            )
        cleaned.sort(key=lambda item: item["alias"].lower())
        return cleaned

    def save_account_profiles(self, profiles: list[dict[str, Any]]) -> None:
        self.set_setting("account_profiles", json.dumps(profiles, ensure_ascii=True))

    def upsert_account_profile(self, profile: dict[str, Any]) -> dict[str, Any]:
        profiles = self.get_account_profiles()
        normalized = {
            "alias": str(profile.get("alias", "")).strip(),
            "login": normalize_account_login(profile.get("login")),
            "password": str(profile.get("password", "")),
            "server": normalize_account_server(profile.get("server")),
            "terminal_path": str(profile.get("terminal_path", "")).strip(),
            "group": str(profile.get("group", "")).strip(),
        }
        if not normalized["alias"]:
            raise ValueError("Account alias is required.")
        profiles = [item for item in profiles if item["alias"].lower() != normalized["alias"].lower()]
        profiles.append(normalized)
        profiles.sort(key=lambda item: item["alias"].lower())
        self.save_account_profiles(profiles)
        return normalized

    def delete_account_profile(self, alias: str) -> bool:
        alias_text = alias.strip().lower()
        if not alias_text:
            return False
        profiles = self.get_account_profiles()
        remaining = [item for item in profiles if item["alias"].lower() != alias_text]
        if len(remaining) == len(profiles):
            return False
        self.save_account_profiles(remaining)
        selected = self.get_setting("selected_account_profile", "")
        if selected.strip().lower() == alias_text:
            self.set_setting("selected_account_profile", "")
        return True

    def find_account_profile(self, alias: str) -> dict[str, Any] | None:
        alias_text = alias.strip().lower()
        for item in self.get_account_profiles():
            if item["alias"].lower() == alias_text:
                return item
        return None

    def get_trader_journal_entry(self, journal_date: str, scope_key: str) -> dict[str, Any] | None:
        with self.lock, self.connect() as conn:
            row = conn.execute(
                """
                SELECT journal_date, scope_key, scope_label, session_grade, followed_plan, emotional_state,
                       best_setup, tags_json, market_conditions, what_went_well, mistakes, lesson, next_focus,
                       created_at, updated_at
                FROM trader_journal_entries
                WHERE journal_date = ? AND scope_key = ?
                """,
                (journal_date, scope_key),
            ).fetchone()
        if not row:
            return None
        data = dict(row)
        try:
            data["tags"] = json.loads(data.pop("tags_json") or "[]")
        except json.JSONDecodeError:
            data["tags"] = []
        return data

    def save_trader_journal_entry(self, payload: dict[str, Any]) -> dict[str, Any]:
        journal_date = str(payload.get("journal_date", "")).strip()
        scope_key = str(payload.get("scope_key", "")).strip()
        scope_label = str(payload.get("scope_label", "")).strip() or scope_key
        if not journal_date or not scope_key:
            raise ValueError("Journal date and scope key are required.")
        tags = payload.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        now = iso_now()
        existing = self.get_trader_journal_entry(journal_date, scope_key)
        created_at = str((existing or {}).get("created_at") or now)
        with self.lock, self.connect() as conn:
            conn.execute(
                """
                INSERT INTO trader_journal_entries(
                    journal_date, scope_key, scope_label, session_grade, followed_plan, emotional_state,
                    best_setup, tags_json, market_conditions, what_went_well, mistakes, lesson, next_focus,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(journal_date, scope_key) DO UPDATE SET
                    scope_label = excluded.scope_label,
                    session_grade = excluded.session_grade,
                    followed_plan = excluded.followed_plan,
                    emotional_state = excluded.emotional_state,
                    best_setup = excluded.best_setup,
                    tags_json = excluded.tags_json,
                    market_conditions = excluded.market_conditions,
                    what_went_well = excluded.what_went_well,
                    mistakes = excluded.mistakes,
                    lesson = excluded.lesson,
                    next_focus = excluded.next_focus,
                    updated_at = excluded.updated_at
                """,
                (
                    journal_date,
                    scope_key,
                    scope_label,
                    str(payload.get("session_grade", "")).strip(),
                    str(payload.get("followed_plan", "")).strip(),
                    str(payload.get("emotional_state", "")).strip(),
                    str(payload.get("best_setup", "")).strip(),
                    json.dumps([str(item).strip() for item in tags if str(item).strip()], ensure_ascii=True),
                    str(payload.get("market_conditions", "")).strip(),
                    str(payload.get("what_went_well", "")).strip(),
                    str(payload.get("mistakes", "")).strip(),
                    str(payload.get("lesson", "")).strip(),
                    str(payload.get("next_focus", "")).strip(),
                    created_at,
                    now,
                ),
            )
            conn.commit()
        return self.get_trader_journal_entry(journal_date, scope_key) or {}

    def clear_all(self) -> None:
        with self.lock, self.connect() as conn:
            conn.executescript(
                """
                DELETE FROM trade_records;
                DELETE FROM mt5_history_records;
                DELETE FROM trade_events;
                DELETE FROM account_snapshots;
                DELETE FROM trader_journal_entries;
                DELETE FROM price_ticks;
                DELETE FROM app_settings;
                """
            )
            conn.commit()

    def save_mt5_history_rows(self, rows: list[dict[str, Any]], *, account_login: int | None, account_server: str) -> int:
        if not rows:
            return 0
        imported_at = iso_now()
        with self.lock, self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO mt5_history_records(
                    ticket, symbol, side, volume, entry_price, stop_loss, take_profit,
                    open_time, close_price, close_time, profit, reason, status, imported_at,
                    account_login, account_server, original_ticket
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticket) DO UPDATE SET
                    symbol = excluded.symbol,
                    side = excluded.side,
                    volume = excluded.volume,
                    entry_price = excluded.entry_price,
                    stop_loss = excluded.stop_loss,
                    take_profit = excluded.take_profit,
                    open_time = excluded.open_time,
                    close_price = excluded.close_price,
                    close_time = excluded.close_time,
                    profit = excluded.profit,
                    reason = excluded.reason,
                    status = excluded.status,
                    imported_at = excluded.imported_at,
                    account_login = excluded.account_login,
                    account_server = excluded.account_server,
                    original_ticket = excluded.original_ticket
                """,
                [
                    (
                        scoped_history_ticket(int(row["ticket"]), account_login, account_server),
                        row["symbol"],
                        row["side"],
                        safe_float(row["volume"]),
                        safe_float(row["entry_price"]),
                        safe_float(row.get("stop_loss", 0.0)),
                        safe_float(row.get("take_profit", 0.0)),
                        row["open_time"],
                        safe_float(row.get("close_price", 0.0)),
                        row.get("close_time"),
                        safe_float(row.get("profit", 0.0)),
                        row.get("reason", "history"),
                        row.get("status", "closed"),
                        imported_at,
                        account_login,
                        account_server,
                        int(row["ticket"]),
                    )
                    for row in rows
                ],
            )
            conn.commit()
        return len(rows)

    def account_start_balance_for_window(
        self,
        *,
        date_from: datetime,
        date_to: datetime,
        account_scopes: list[tuple[int | None, str]] | None = None,
    ) -> float | None:
        normalized_scopes = [
            (normalize_account_login(login), normalize_account_server(server))
            for login, server in (account_scopes or [])
            if normalize_account_login(login) is not None
        ]
        if not normalized_scopes:
            return None

        total_balance = 0.0
        found_any = False
        with self.lock, self.connect() as conn:
            for login, server in normalized_scopes:
                row = conn.execute(
                    """
                    SELECT balance
                    FROM account_snapshots
                    WHERE account_login = ? AND COALESCE(account_server, '') = ? AND ts <= ?
                    ORDER BY ts DESC
                    LIMIT 1
                    """,
                    (login, server, date_from.isoformat()),
                ).fetchone()
                if row is None:
                    row = conn.execute(
                        """
                        SELECT balance
                        FROM account_snapshots
                        WHERE account_login = ? AND COALESCE(account_server, '') = ? AND ts >= ? AND ts < ?
                        ORDER BY ts ASC
                        LIMIT 1
                        """,
                        (login, server, date_from.isoformat(), date_to.isoformat()),
                    ).fetchone()
                if row is None:
                    continue
                total_balance += safe_float(row["balance"])
                found_any = True
        return total_balance if found_any else None

    def mt5_history_performance_summary(
        self,
        *,
        account_scopes: list[tuple[int | None, str]] | None = None,
        symbols: list[str] | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        windows = period_bounds(now)
        normalized_scopes = [
            (normalize_account_login(login), normalize_account_server(server))
            for login, server in (account_scopes or [])
            if normalize_account_login(login) is not None
        ]
        normalized_symbols = sorted({str(item or "").strip().upper() for item in (symbols or []) if str(item or "").strip()})
        with self.lock, self.connect() as conn:
            summary: dict[str, Any] = {}
            for key, (start_at, end_at) in windows.items():
                params: list[Any] = [start_at.isoformat(), end_at.isoformat()]
                clauses = [
                    "COALESCE(close_time, open_time) >= ?",
                    "COALESCE(close_time, open_time) < ?",
                ]
                if normalized_scopes:
                    scope_clauses: list[str] = []
                    for login, server in normalized_scopes:
                        scope_clauses.append("(account_login = ? AND COALESCE(account_server, '') = ?)")
                        params.extend([login, server])
                    clauses.append(f"({' OR '.join(scope_clauses)})")
                if normalized_symbols:
                    placeholders = ", ".join("?" for _ in normalized_symbols)
                    clauses.append(f"UPPER(COALESCE(symbol, '')) IN ({placeholders})")
                    params.extend(normalized_symbols)
                where_sql = " AND ".join(clauses)
                row = conn.execute(
                    f"""
                    SELECT
                        COUNT(*) AS trade_count,
                        COALESCE(SUM(profit), 0) AS total_profit
                    FROM mt5_history_records
                    WHERE {where_sql}
                    """,
                    params,
                ).fetchone()
                summary[key] = {
                    "trade_count": int(row["trade_count"] or 0),
                    "total_profit": safe_float(row["total_profit"]),
                }
        return summary

    def mt5_history_insight_rows(
        self,
        *,
        account_scopes: list[tuple[int | None, str]] | None = None,
        symbols: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        normalized_scopes = [
            (normalize_account_login(login), normalize_account_server(server))
            for login, server in (account_scopes or [])
            if normalize_account_login(login) is not None
        ]
        normalized_symbols = sorted({str(item or "").strip().upper() for item in (symbols or []) if str(item or "").strip()})
        params: list[Any] = []
        clauses: list[str] = []
        if normalized_scopes:
            scope_clauses: list[str] = []
            for login, server in normalized_scopes:
                scope_clauses.append("(account_login = ? AND COALESCE(account_server, '') = ?)")
                params.extend([login, server])
            clauses.append(f"({' OR '.join(scope_clauses)})")
        if normalized_symbols:
            placeholders = ", ".join("?" for _ in normalized_symbols)
            clauses.append(f"UPPER(COALESCE(symbol, '')) IN ({placeholders})")
            params.extend(normalized_symbols)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.lock, self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    COALESCE(original_ticket, ticket) AS ticket, symbol, side, volume, entry_price, stop_loss, take_profit, open_time,
                    close_price, close_time, profit, reason, status, account_login, account_server
                FROM mt5_history_records
                {where_sql}
                ORDER BY COALESCE(close_time, open_time) DESC, ticket DESC
                """,
                params,
            ).fetchall()

        return [
            {
                "ticket": int(row["ticket"]),
                "symbol": row["symbol"],
                "side": row["side"],
                "volume": safe_float(row["volume"]),
                "entry_price": safe_float(row["entry_price"]),
                "stop_loss": safe_float(row["stop_loss"]),
                "take_profit": safe_float(row["take_profit"]),
                "open_time": row["open_time"],
                "close_price": safe_float(row["close_price"]),
                "close_time": row["close_time"],
                "profit": safe_float(row["profit"]),
                "reason": row["reason"],
                "status": row["status"],
                "account_login": normalize_account_login(row["account_login"]),
                "account_server": normalize_account_server(row["account_server"]),
            }
            for row in rows
        ]

    def mt5_history_journal(
        self,
        *,
        range_key: str,
        outcome: str,
        lot_size: str,
        symbols: list[str] | None,
        special_filter: str,
        exact_date: str,
        account_scopes: list[tuple[int | None, str]] | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        start_today = datetime(now.year, now.month, now.day, tzinfo=UTC)
        start_map = {
            "today": start_today,
            "2d": start_today - timedelta(days=1),
            "2w": start_today - timedelta(days=13),
            "month": start_today - timedelta(days=29),
            "all": now - timedelta(days=3650),
        }
        exact_window = parse_exact_date(exact_date)
        if exact_window:
            date_from, date_to = exact_window
        else:
            date_from = start_map.get(range_key, start_today)
            date_to = now + timedelta(days=2)

        normalized_scopes = [
            (normalize_account_login(login), normalize_account_server(server))
            for login, server in (account_scopes or [])
            if normalize_account_login(login) is not None
        ]
        normalized_symbols = sorted({str(item or "").strip().upper() for item in (symbols or []) if str(item or "").strip()})

        params: list[Any] = [date_from.isoformat(), date_to.isoformat()]
        clauses = [
            "COALESCE(close_time, open_time) >= ?",
            "COALESCE(close_time, open_time) < ?",
        ]
        if normalized_scopes:
            scope_clauses: list[str] = []
            for login, server in normalized_scopes:
                scope_clauses.append("(account_login = ? AND COALESCE(account_server, '') = ?)")
                params.extend([login, server])
            clauses.append(f"({' OR '.join(scope_clauses)})")
        if normalized_symbols:
            placeholders = ", ".join("?" for _ in normalized_symbols)
            clauses.append(f"UPPER(COALESCE(symbol, '')) IN ({placeholders})")
            params.extend(normalized_symbols)

        with self.lock, self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    COALESCE(original_ticket, ticket) AS ticket, symbol, side, volume, entry_price, stop_loss, take_profit, open_time,
                    close_price, close_time, profit, reason, status, account_login, account_server
                FROM mt5_history_records
                WHERE {' AND '.join(clauses)}
                ORDER BY COALESCE(close_time, open_time) DESC, ticket DESC
                """,
                params,
            ).fetchall()
            symbol_rows = conn.execute(
                f"""
                SELECT DISTINCT symbol
                FROM mt5_history_records
                WHERE {' AND '.join(clauses)}
                ORDER BY symbol
                """,
                params,
            ).fetchall()

        row_dicts = [
            {
                "ticket": int(row["ticket"]),
                "symbol": row["symbol"],
                "side": row["side"],
                "volume": safe_float(row["volume"]),
                "entry_price": safe_float(row["entry_price"]),
                "stop_loss": safe_float(row["stop_loss"]),
                "take_profit": safe_float(row["take_profit"]),
                "open_time": row["open_time"],
                "close_price": safe_float(row["close_price"]),
                "close_time": row["close_time"],
                "profit": safe_float(row["profit"]),
                "reason": row["reason"],
                "status": row["status"],
                "account_login": normalize_account_login(row["account_login"]),
                "account_server": normalize_account_server(row["account_server"]),
            }
            for row in rows
        ]

        if outcome == "profit":
            row_dicts = [row for row in row_dicts if safe_float(row["profit"]) > 0]
        elif outcome == "loss":
            row_dicts = [row for row in row_dicts if safe_float(row["profit"]) < 0]

        if lot_size:
            target_lot = safe_float(lot_size, -1.0)
            row_dicts = [row for row in row_dicts if math.isclose(safe_float(row["volume"]), target_lot, rel_tol=0.0, abs_tol=0.000001)]

        row_dicts = apply_special_filter(row_dicts, special_filter)
        insight_rows = self.mt5_history_insight_rows(account_scopes=normalized_scopes, symbols=normalized_symbols)
        grouped_days = build_grouped_days(row_dicts)
        if exact_date and len(grouped_days) == 1 and grouped_days[0].get("start_balance") is None:
            grouped_days[0]["start_balance"] = self.account_start_balance_for_window(
                date_from=date_from,
                date_to=date_to,
                account_scopes=normalized_scopes,
            )
        total_profit = sum(safe_float(row["profit"]) for row in row_dicts)

        return {
            "days": grouped_days,
            "totals": {
                "total_trades": len(row_dicts),
                "wins": sum(1 for row in row_dicts if safe_float(row["profit"]) > 0),
                "losses": sum(1 for row in row_dicts if safe_float(row["profit"]) < 0),
                "total_profit": total_profit,
            },
            "lot_sizes": sorted({safe_float(row["volume"]) for row in row_dicts}),
            "symbols": [str(row["symbol"] or "").strip().upper() for row in symbol_rows if str(row["symbol"] or "").strip()],
            "summary": self.mt5_history_performance_summary(account_scopes=normalized_scopes, symbols=normalized_symbols),
            "insights": build_journal_insights(insight_rows),
            "source": "mt5_history_cache",
        }

    def open_trade(self, trade: dict[str, Any]) -> None:
        with self.lock, self.connect() as conn:
            conn.execute(
                """
                INSERT INTO trade_records(
                    ticket, position_id, symbol, side, volume, entry_price, stop_loss, take_profit,
                    open_time, status, entry_balance, last_price, last_pips, account_login, account_server
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?)
                ON CONFLICT(ticket) DO UPDATE SET
                    position_id = excluded.position_id,
                    symbol = excluded.symbol,
                    side = excluded.side,
                    volume = excluded.volume,
                    stop_loss = excluded.stop_loss,
                    take_profit = excluded.take_profit,
                    last_price = excluded.last_price,
                    last_pips = excluded.last_pips,
                    account_login = excluded.account_login,
                    account_server = excluded.account_server
                """,
                (
                    trade["ticket"],
                    trade["position_id"],
                    trade["symbol"],
                    trade["side"],
                    trade["volume"],
                    trade["entry_price"],
                    trade["stop_loss"],
                    trade["take_profit"],
                    trade["open_time"],
                    trade["entry_balance"],
                    trade["last_price"],
                    trade["last_pips"],
                    normalize_account_login(trade.get("account_login")),
                    normalize_account_server(trade.get("account_server")),
                ),
            )
            conn.commit()

    def update_open_trade(self, ticket: int, updates: dict[str, Any]) -> None:
        assignments = ", ".join(f"{key} = ?" for key in updates)
        params = list(updates.values()) + [ticket]
        with self.lock, self.connect() as conn:
            conn.execute(f"UPDATE trade_records SET {assignments} WHERE ticket = ?", params)
            conn.commit()

    def close_trade(self, ticket: int, updates: dict[str, Any]) -> None:
        payload = {"status": "closed", **updates}
        self.update_open_trade(ticket, payload)

    def log_event(
        self,
        event_type: str,
        severity: str,
        message: str,
        *,
        ticket: int | None = None,
        payload: dict[str, Any] | None = None,
        account_login: int | None = None,
        account_server: str = "",
    ) -> None:
        with self.lock, self.connect() as conn:
            conn.execute(
                """
                INSERT INTO trade_events(ts, event_type, severity, ticket, message, payload, account_login, account_server)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    iso_now(),
                    event_type,
                    severity,
                    ticket,
                    message,
                    json.dumps(payload or {}, ensure_ascii=True),
                    normalize_account_login(account_login),
                    normalize_account_server(account_server),
                ),
            )
            conn.commit()

    def add_account_snapshot(self, snapshot: dict[str, float]) -> None:
        with self.lock, self.connect() as conn:
            conn.execute(
                """
                INSERT INTO account_snapshots(ts, balance, equity, profit, margin, free_margin, account_login, account_server)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    iso_now(),
                    snapshot["balance"],
                    snapshot["equity"],
                    snapshot["profit"],
                    snapshot["margin"],
                    snapshot["free_margin"],
                    normalize_account_login(snapshot.get("login")),
                    normalize_account_server(snapshot.get("server")),
                ),
            )
            conn.commit()

    def add_price_tick(self, symbol: str, bid: float, ask: float, last: float) -> None:
        with self.lock, self.connect() as conn:
            conn.execute(
                "INSERT INTO price_ticks(ts, symbol, bid, ask, last) VALUES (?, ?, ?, ?, ?)",
                (iso_now(), symbol, bid, ask, last),
            )
            conn.commit()

    def get_open_tickets(self) -> set[int]:
        with self.lock, self.connect() as conn:
            rows = conn.execute("SELECT ticket FROM trade_records WHERE status = 'open'").fetchall()
        return {int(row["ticket"]) for row in rows}

    def get_recent_alerts(self, limit: int = 20, *, account_login: int | None = None, account_server: str = "") -> list[dict[str, Any]]:
        with self.lock, self.connect() as conn:
            normalized_login = normalize_account_login(account_login)
            normalized_server = normalize_account_server(account_server)
            clauses = []
            params: list[Any] = []
            if normalized_login is not None:
                clauses.append("account_login = ?")
                params.append(normalized_login)
                clauses.append("COALESCE(account_server, '') = ?")
                params.append(normalized_server)
            where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            rows = conn.execute(
                f"""
                SELECT ts, event_type, severity, ticket, message, payload
                FROM trade_events
                {where_sql}
                ORDER BY id DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
        alerts = []
        for row in rows:
            alerts.append(
                {
                    "ts": row["ts"],
                    "event_type": row["event_type"],
                    "severity": row["severity"],
                    "ticket": row["ticket"],
                    "message": row["message"],
                    "payload": json.loads(row["payload"]),
                }
            )
        return alerts

    def journal(
        self,
        *,
        range_key: str,
        outcome: str,
        lot_size: str,
        symbols: list[str] | None,
        special_filter: str,
        exact_date: str,
        account_login: int | None,
        account_server: str,
    ) -> dict[str, Any]:
        clauses = []
        params: list[Any] = []
        normalized_login = normalize_account_login(account_login)
        normalized_server = normalize_account_server(account_server)

        now = utc_now()
        start_today = datetime(now.year, now.month, now.day, tzinfo=UTC)
        start_map = {
            "today": start_today,
            "2d": start_today - timedelta(days=1),
            "2w": start_today - timedelta(days=13),
            "month": start_today - timedelta(days=29),
        }
        exact_window = parse_exact_date(exact_date)
        if exact_window:
            clauses.append("COALESCE(close_time, open_time) >= ?")
            clauses.append("COALESCE(close_time, open_time) < ?")
            params.extend([exact_window[0].isoformat(), exact_window[1].isoformat()])
        elif range_key in start_map:
            clauses.append("COALESCE(close_time, open_time) >= ?")
            params.append(start_map[range_key].isoformat())

        if outcome == "profit":
            clauses.append("profit > 0")
        elif outcome == "loss":
            clauses.append("profit < 0")

        if lot_size:
            clauses.append("ABS(volume - ?) < 0.000001")
            params.append(float(lot_size))

        normalized_symbols = sorted({str(item or "").strip().upper() for item in (symbols or []) if str(item or "").strip()})
        if normalized_symbols:
            placeholders = ", ".join("?" for _ in normalized_symbols)
            clauses.append(f"UPPER(COALESCE(symbol, '')) IN ({placeholders})")
            params.extend(normalized_symbols)

        if normalized_login is not None:
            clauses.append("account_login = ?")
            params.append(normalized_login)
            clauses.append("COALESCE(account_server, '') = ?")
            params.append(normalized_server)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        with self.lock, self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT ticket, symbol, side, volume, entry_price, stop_loss, take_profit, open_time,
                       close_price, close_time, profit, reason, status, entry_balance, exit_balance
                FROM trade_records
                {where_sql}
                ORDER BY COALESCE(close_time, open_time) DESC
                """,
                params,
            ).fetchall()

            totals = conn.execute(
                f"""
                SELECT
                    COUNT(*) AS total_trades,
                    SUM(CASE WHEN profit > 0 THEN 1 ELSE 0 END) AS wins,
                    SUM(CASE WHEN profit < 0 THEN 1 ELSE 0 END) AS losses,
                    COALESCE(SUM(profit), 0) AS total_profit
                FROM trade_records
                {where_sql}
                """,
                params,
            ).fetchone()

            if normalized_login is not None:
                lots = conn.execute(
                    """
                    SELECT DISTINCT volume
                    FROM trade_records
                    WHERE account_login = ? AND COALESCE(account_server, '') = ?
                    ORDER BY volume
                    """,
                    (normalized_login, normalized_server),
                ).fetchall()
            else:
                lots = conn.execute("SELECT DISTINCT volume FROM trade_records ORDER BY volume").fetchall()
            symbol_rows = conn.execute(
                f"""
                SELECT DISTINCT symbol
                FROM trade_records
                {where_sql}
                ORDER BY symbol
                """,
                params,
            ).fetchall()

        row_dicts = [dict(row) for row in rows]
        row_dicts = apply_special_filter(row_dicts, special_filter)
        insight_rows = self.insight_rows(
            account_login=normalized_login,
            account_server=normalized_server,
        )
        grouped_days = build_grouped_days(row_dicts)
        if exact_date and len(grouped_days) == 1 and grouped_days[0].get("start_balance") is None:
            grouped_days[0]["start_balance"] = self.account_start_balance_for_window(
                date_from=date_from,
                date_to=date_to,
                account_scopes=[(normalized_login, normalized_server)] if normalized_login is not None else None,
            )
        return {
            "days": grouped_days,
            "totals": {
                "total_trades": int(totals["total_trades"] or 0),
                "wins": int(totals["wins"] or 0),
                "losses": int(totals["losses"] or 0),
                "total_profit": safe_float(totals["total_profit"]),
            },
            "lot_sizes": [safe_float(row["volume"]) for row in lots],
            "symbols": [str(row["symbol"] or "").strip().upper() for row in symbol_rows if str(row["symbol"] or "").strip()],
            "summary": self.performance_summary(
                account_login=normalized_login,
                account_server=normalized_server,
            ),
            "insights": build_journal_insights(insight_rows),
        }

    def performance_summary(self, *, account_login: int | None, account_server: str) -> dict[str, Any]:
        normalized_login = normalize_account_login(account_login)
        normalized_server = normalize_account_server(account_server)
        now = utc_now()
        windows = period_bounds(now)
        with self.lock, self.connect() as conn:
            summary: dict[str, Any] = {}
            for key, (start_at, end_at) in windows.items():
                params: list[Any] = [start_at.isoformat(), end_at.isoformat()]
                clauses = [
                    "COALESCE(close_time, open_time) >= ?",
                    "COALESCE(close_time, open_time) < ?",
                ]
                if normalized_login is not None:
                    clauses.append("account_login = ?")
                    clauses.append("COALESCE(account_server, '') = ?")
                    params.extend([normalized_login, normalized_server])
                where_sql = " AND ".join(clauses)
                row = conn.execute(
                    f"""
                    SELECT
                        COUNT(*) AS trade_count,
                        COALESCE(SUM(profit), 0) AS total_profit
                    FROM trade_records
                    WHERE {where_sql}
                    """,
                    params,
                ).fetchone()
                summary[key] = {
                    "trade_count": int(row["trade_count"] or 0),
                    "total_profit": safe_float(row["total_profit"]),
                }
        return summary

    def insight_rows(self, *, account_login: int | None, account_server: str) -> list[dict[str, Any]]:
        normalized_login = normalize_account_login(account_login)
        normalized_server = normalize_account_server(account_server)
        params: list[Any] = []
        clauses: list[str] = []
        if normalized_login is not None:
            clauses.append("account_login = ?")
            clauses.append("COALESCE(account_server, '') = ?")
            params.extend([normalized_login, normalized_server])
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        with self.lock, self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT ticket, symbol, side, volume, entry_price, stop_loss, take_profit, open_time,
                       close_price, close_time, profit, reason, status, entry_balance, exit_balance
                FROM trade_records
                {where_sql}
                ORDER BY COALESCE(close_time, open_time) DESC
                """,
                params,
            ).fetchall()

        return [dict(row) for row in rows]


class Sounder:
    TONES = {
        "entry": [(740, 120), (988, 160), (1244, 180)],
        "close": [(880, 120), (1175, 140), (1568, 180)],
        "tp": [(1047, 140), (1319, 160), (1568, 240)],
        "tp_set": [(988, 120), (1175, 140)],
        "sl_set": [(523, 140), (659, 160)],
        "warning": [(523, 240), (523, 240)],
        "sl": [(440, 200), (349, 260), (262, 320)],
        "blown": [(659, 180), (523, 220), (392, 340), (196, 520)],
        "orl": [(988, 120), (1319, 160), (988, 120), (1568, 200)],
        "trend_bullish": [(880, 100), (1047, 120), (1319, 160), (1568, 180)],
        "trend_bearish": [(1319, 100), (1047, 120), (784, 160), (659, 180)],
    }

    def play(self, sound: str) -> None:
        if winsound is None:
            return
        for frequency, duration in self.TONES.get(sound, []):
            try:
                winsound.Beep(frequency, duration)
            except RuntimeError:
                break


class EmailNotifier:
    def __init__(self, config: SMTPConfig | None) -> None:
        self.config = config

    @property
    def enabled(self) -> bool:
        return self.config is not None

    def send(self, subject: str, body: str) -> None:
        if self.config is None:
            return
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.config.from_email
        msg["To"] = self.config.to_email
        msg.set_content(body)
        with smtplib.SMTP_SSL(self.config.host, self.config.port) as server:
            server.login(self.config.username, self.config.password)
            server.send_message(msg)


@dataclass
class TradeSnapshot:
    ticket: int
    position_id: int
    symbol: str
    side: str
    volume: float
    entry_price: float
    stop_loss: float
    take_profit: float
    open_time: str
    current_price: float
    profit: float
    pips: float
    seconds_open: int
    max_profit: float = 0.0
    max_drawdown: float = 0.0
    flags_sent: set[str] = field(default_factory=set)


@dataclass
class PendingOrderSnapshot:
    ticket: int
    symbol: str
    side: str
    order_type: str
    volume: float
    trigger_price: float
    stop_loss: float
    take_profit: float
    stop_limit_price: float
    current_price: float
    placed_time: str
    seconds_open: int
    expiration_time: str = ""


class MT5Monitor:
    def __init__(self, db: Database, sounder: Sounder, notifier: EmailNotifier) -> None:
        self.db = db
        self.sounder = sounder
        self.notifier = notifier
        self.lock = threading.Lock()
        self.running = False
        self.thread: threading.Thread | None = None
        self.connected = False
        self.connection_error = ""
        self.trades: dict[int, TradeSnapshot] = {}
        self.pending_orders: dict[int, PendingOrderSnapshot] = {}
        self.recent_prices: deque[dict[str, Any]] = deque(maxlen=CONFIG.price_history_limit)
        self.last_alert_id = 0
        self.account: dict[str, Any] = {
            "balance": 0.0,
            "equity": 0.0,
            "profit": 0.0,
            "margin": 0.0,
            "free_margin": 0.0,
            "leverage": 0,
            "currency": "USD",
            "login": None,
            "server": None,
        }
        self.last_account_login: int | None = None
        self.last_account_server: str | None = None
        self.primary_symbol = CONFIG.preferred_symbol
        self.selected_profile_alias = self.db.get_setting("selected_account_profile", "")
        self.connection_profile = self.db.find_account_profile(self.selected_profile_alias) if self.selected_profile_alias else None
        self.connect_requested = False
        self.trade_lock_enabled = self.db.get_setting("trade_lock_enabled", "no").strip().lower() == "yes"
        self.initial_balance = self._load_initial_balance()
        self.orl_live_observer: ORLLiveObserverService | None = None
        self.m5_direction_status: dict[str, Any] = {
            "symbol": "",
            "timeframe": "M5",
            "direction": "neutral",
            "strength": 0,
            "last_closed_candle_time": "",
            "last_price": 0.0,
            "fast_average": 0.0,
            "slow_average": 0.0,
            "reason": "Waiting for M5 direction data.",
            "last_alerted_direction": "",
            "last_alerted_candle_time": "",
            "last_alerted_at": "",
        }

    def email_notifications_enabled(self) -> bool:
        return self.db.get_setting("email_notifications_enabled", "yes").strip().lower() != "no"

    def set_email_notifications_enabled(self, enabled: bool) -> dict[str, Any]:
        self.db.set_setting("email_notifications_enabled", "yes" if enabled else "no")
        return {"ok": True, "enabled": self.email_notifications_enabled()}

    def notifications_enabled(self) -> bool:
        return self.db.get_setting("notifications_enabled", "yes").strip().lower() != "no"

    def set_notifications_enabled(self, enabled: bool) -> dict[str, Any]:
        self.db.set_setting("notifications_enabled", "yes" if enabled else "no")
        return {"ok": True, "enabled": self.notifications_enabled()}

    def alert_type_preferences(self) -> dict[str, bool]:
        raw = self.db.get_setting("alert_type_enabled", "{}")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if not isinstance(parsed, dict):
            return {}
        cleaned: dict[str, bool] = {}
        for key, value in parsed.items():
            name = str(key).strip()
            if not name:
                continue
            cleaned[name] = bool(value)
        return cleaned

    def set_alert_type_preferences(self, preferences: dict[str, Any]) -> dict[str, Any]:
        cleaned: dict[str, bool] = {}
        for key, value in dict(preferences or {}).items():
            name = str(key).strip()
            if not name:
                continue
            cleaned[name] = bool(value)
        self.db.set_setting("alert_type_enabled", json.dumps(cleaned, ensure_ascii=True))
        return {"ok": True, "preferences": self.alert_type_preferences()}

    def set_trade_lock_enabled(self, enabled: bool) -> dict[str, Any]:
        self.trade_lock_enabled = bool(enabled)
        self.db.set_setting("trade_lock_enabled", "yes" if self.trade_lock_enabled else "no")
        return {"ok": True, "enabled": self.trade_lock_enabled}

    def _load_initial_balance(self) -> float:
        saved = self.db.get_setting(self._initial_balance_setting_key(), "")
        return safe_float(saved, 0.0)

    def _remember_initial_balance(self, balance: float) -> None:
        if self.initial_balance > 0:
            return
        self.initial_balance = balance
        self.db.set_setting(self._initial_balance_setting_key(), str(balance))

    def _current_account_login(self) -> int | None:
        return normalize_account_login(self.account.get("login"))

    def _current_account_server(self) -> str:
        return normalize_account_server(self.account.get("server"))

    def _initial_balance_setting_key(self, login: Any | None = None, server: Any | None = None) -> str:
        login_value = self._current_account_login() if login is None else normalize_account_login(login)
        server_value = self._current_account_server() if server is None else normalize_account_server(server)
        return f"initial_balance::{account_scope_key(login_value, server_value)}"

    def start(self) -> None:
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)
        if mt5 is not None:
            try:
                mt5.shutdown()
            except Exception:
                pass

    def reconnect(self, profile_alias: str = "", terminal_path: str = "", quick_alias: str = "") -> dict[str, Any]:
        profile_alias = profile_alias.strip()
        terminal_path = terminal_path.strip()
        quick_alias = quick_alias.strip()
        if profile_alias:
            profile = self.db.find_account_profile(profile_alias)
            if profile is None:
                return {
                    "connected": False,
                    "connection_error": f"Account profile '{profile_alias}' was not found.",
                    "account": self.account,
                    "selected_profile_alias": self.selected_profile_alias,
                }
            self.selected_profile_alias = profile["alias"]
            self.connection_profile = profile
            self.db.set_setting("selected_account_profile", self.selected_profile_alias)
        elif terminal_path:
            self.selected_profile_alias = quick_alias or Path(terminal_path).parent.name
            self.connection_profile = {
                "alias": self.selected_profile_alias,
                "login": None,
                "password": "",
                "server": "",
                "terminal_path": terminal_path,
                "group": "Direct Terminal",
            }
        elif self.selected_profile_alias:
            self.connection_profile = self.db.find_account_profile(self.selected_profile_alias)
        if mt5 is not None:
            try:
                mt5.shutdown()
            except Exception:
                pass
        self.connected = False
        self.connection_error = ""
        self.primary_symbol = CONFIG.preferred_symbol
        self.connect_requested = True
        self._poll()
        return {
            "connected": self.connected,
            "connection_error": self.connection_error,
            "account": self.account,
            "selected_profile_alias": self.selected_profile_alias,
        }

    def disconnect(self) -> dict[str, Any]:
        self.connect_requested = False
        if mt5 is not None:
            try:
                mt5.shutdown()
            except Exception:
                pass
        self.connected = False
        self.connection_error = "Disconnected. Select an account or terminal, then click Connect to MT5."
        self.primary_symbol = CONFIG.preferred_symbol
        self.trades.clear()
        self.pending_orders.clear()
        self.recent_prices.clear()
        self.m5_direction_status = {
            **self.m5_direction_status,
            "symbol": "",
            "direction": "neutral",
            "strength": 0,
            "last_closed_candle_time": "",
            "last_price": 0.0,
            "fast_average": 0.0,
            "slow_average": 0.0,
            "reason": "Disconnected from MT5.",
        }
        return {
            "connected": False,
            "connection_error": self.connection_error,
            "account": self.account,
            "selected_profile_alias": self.selected_profile_alias,
        }

    def reset_runtime_state(self) -> None:
        if mt5 is not None:
            try:
                mt5.shutdown()
            except Exception:
                pass
        self.connected = False
        self.connection_error = ""
        self.primary_symbol = CONFIG.preferred_symbol
        self.connect_requested = False
        self.trades.clear()
        self.pending_orders.clear()
        self.recent_prices.clear()
        self.initial_balance = 0.0
        self.account = {
            "balance": 0.0,
            "equity": 0.0,
            "profit": 0.0,
            "margin": 0.0,
            "free_margin": 0.0,
            "leverage": 0,
            "currency": "USD",
            "login": None,
            "server": None,
        }
        self.m5_direction_status = {
            **self.m5_direction_status,
            "symbol": "",
            "direction": "neutral",
            "strength": 0,
            "last_closed_candle_time": "",
            "last_price": 0.0,
            "fast_average": 0.0,
            "slow_average": 0.0,
            "reason": "Waiting for a fresh MT5 connection.",
            "last_alerted_direction": "",
            "last_alerted_candle_time": "",
            "last_alerted_at": "",
        }

    def _run(self) -> None:
        while self.running:
            try:
                self._poll()
            except Exception as exc:  # pragma: no cover
                self.connected = False
                self.connection_error = str(exc)
            time.sleep(CONFIG.poll_seconds)

    def _initialize(self) -> bool:
        if mt5 is None:
            self.connected = False
            self.connection_error = "MetaTrader5 package is not installed in the Python runtime used by this app."
            return False

        if not self.connect_requested:
            self.connected = False
            self.connection_error = "Select an account or terminal, then click Connect to MT5."
            return False

        if self.connected:
            return True

        profile = self.connection_profile or {}
        terminal_path = str(profile.get("terminal_path", "")).strip()
        if terminal_path:
            initialized = bool(mt5.initialize(path=terminal_path))
        else:
            initialized = bool(mt5.initialize())
        if not initialized:
            self.connected = False
            self.connection_error = f"MT5 initialize failed: {mt5.last_error()}"
            self.connect_requested = False
            return False

        login = normalize_account_login(profile.get("login"))
        password = str(profile.get("password", ""))
        server_name = normalize_account_server(profile.get("server"))
        if login is not None:
            if not mt5.login(login=login, password=password, server=server_name or None):
                self.connected = False
                self.connection_error = f"MT5 login failed: {mt5.last_error()}"
                self.connect_requested = False
                try:
                    mt5.shutdown()
                except Exception:
                    pass
                return False

        self.connected = True
        self.connection_error = ""
        return True

    def _select_symbol(self, positions: list[Any]) -> str:
        if self.primary_symbol:
            return self.primary_symbol

        if positions:
            self.primary_symbol = positions[0].symbol
            return self.primary_symbol

        for symbol in CONFIG.symbol_candidates:
            info = mt5.symbol_info(symbol) if mt5 is not None else None
            if info is None:
                continue
            if not info.visible and mt5 is not None:
                mt5.symbol_select(symbol, True)
            self.primary_symbol = symbol
            return symbol

        self.primary_symbol = "UNKNOWN"
        return self.primary_symbol

    def _poll(self) -> None:
        if not self._initialize():
            return

        account = mt5.account_info()
        if account is None:
            self.connected = False
            self.connection_error = f"account_info failed: {mt5.last_error()}"
            return

        balance = safe_float(account.balance)
        equity = safe_float(account.equity)

        account_snapshot = {
            "balance": balance,
            "equity": equity,
            "profit": safe_float(account.profit),
            "margin": safe_float(account.margin),
            "free_margin": safe_float(account.margin_free),
            "leverage": int(getattr(account, "leverage", 0) or 0),
            "currency": getattr(account, "currency", "USD"),
            "login": getattr(account, "login", None),
            "server": getattr(account, "server", None),
        }
        self._scan_account_switch(account_snapshot)
        self.account = account_snapshot
        self._remember_initial_balance(balance)
        self.db.add_account_snapshot(account_snapshot)

        positions = list(mt5.positions_get() or [])
        orders = list(mt5.orders_get() or [])
        symbol = self._select_symbol(positions)
        self._capture_tick(symbol)
        self._scan_m5_direction(symbol)
        self._sync_positions(positions, balance)
        self._sync_pending_orders(orders)
        self._scan_closed_positions(balance)
        self._scan_account_risk()
        if self.orl_live_observer is not None and symbol and symbol != "UNKNOWN":
            self.orl_live_observer.poll(symbol)

    def _capture_tick(self, symbol: str) -> None:
        if mt5 is None or symbol == "UNKNOWN":
            return
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return
        last_price = safe_float(getattr(tick, "last", 0.0)) or safe_float(getattr(tick, "bid", 0.0))
        point = {
            "ts": iso_now(),
            "symbol": symbol,
            "bid": safe_float(getattr(tick, "bid", 0.0)),
            "ask": safe_float(getattr(tick, "ask", 0.0)),
            "last": last_price,
        }
        self.recent_prices.append(point)
        self.db.add_price_tick(symbol, point["bid"], point["ask"], point["last"])

    def _position_side(self, position: Any) -> str:
        if mt5 is not None and getattr(position, "type", None) == mt5.POSITION_TYPE_SELL:
            return "sell"
        return "buy"

    def _position_pips(self, position: Any, current_price: float) -> float:
        entry = safe_float(position.price_open)
        point = safe_float(getattr(mt5.symbol_info(position.symbol), "point", 0.01) if mt5 is not None else 0.01, 0.01)
        move = current_price - entry if self._position_side(position) == "buy" else entry - current_price
        return move / point if point else 0.0

    def _pending_order_side(self, order: Any) -> str:
        buy_types = {
            getattr(mt5, "ORDER_TYPE_BUY_LIMIT", -1000) if mt5 is not None else -1000,
            getattr(mt5, "ORDER_TYPE_BUY_STOP", -1001) if mt5 is not None else -1001,
            getattr(mt5, "ORDER_TYPE_BUY_STOP_LIMIT", -1002) if mt5 is not None else -1002,
        }
        if getattr(order, "type", None) in buy_types:
            return "buy"
        return "sell"

    def _pending_order_type_label(self, order: Any) -> str:
        if mt5 is None:
            return "Pending Order"
        mapping = {
            getattr(mt5, "ORDER_TYPE_BUY_LIMIT", -1): "Buy Limit",
            getattr(mt5, "ORDER_TYPE_SELL_LIMIT", -2): "Sell Limit",
            getattr(mt5, "ORDER_TYPE_BUY_STOP", -3): "Buy Stop",
            getattr(mt5, "ORDER_TYPE_SELL_STOP", -4): "Sell Stop",
            getattr(mt5, "ORDER_TYPE_BUY_STOP_LIMIT", -5): "Buy Stop Limit",
            getattr(mt5, "ORDER_TYPE_SELL_STOP_LIMIT", -6): "Sell Stop Limit",
        }
        return mapping.get(getattr(order, "type", None), "Pending Order")

    def _sync_pending_orders(self, orders: list[Any]) -> None:
        latest: dict[int, PendingOrderSnapshot] = {}
        now_dt = utc_now()
        for order in orders:
            ticket = int(getattr(order, "ticket", 0) or 0)
            if ticket <= 0:
                continue
            symbol = str(getattr(order, "symbol", "") or "")
            tick = mt5.symbol_info_tick(symbol) if mt5 is not None and symbol else None
            current_price = safe_float(getattr(tick, "last", 0.0)) or safe_float(getattr(tick, "bid", 0.0)) or safe_float(getattr(order, "price_open", 0.0))
            setup_dt = datetime.fromtimestamp(int(safe_float(getattr(order, "time_setup", 0.0)) or time.time()), UTC)
            expiration_raw = safe_float(getattr(order, "time_expiration", 0.0))
            expiration_dt = datetime.fromtimestamp(int(expiration_raw), UTC) if expiration_raw > 0 else None
            latest[ticket] = PendingOrderSnapshot(
                ticket=ticket,
                symbol=symbol,
                side=self._pending_order_side(order),
                order_type=self._pending_order_type_label(order),
                volume=safe_float(getattr(order, "volume_initial", 0.0)),
                trigger_price=safe_float(getattr(order, "price_open", 0.0)),
                stop_loss=safe_float(getattr(order, "sl", 0.0)),
                take_profit=safe_float(getattr(order, "tp", 0.0)),
                stop_limit_price=safe_float(getattr(order, "price_stoplimit", 0.0)),
                current_price=current_price,
                placed_time=setup_dt.isoformat(),
                seconds_open=max(0, int((now_dt - setup_dt).total_seconds())),
                expiration_time=expiration_dt.isoformat() if expiration_dt is not None else "",
            )
        self.pending_orders = latest

    def _average(self, values: list[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    def _scan_m5_direction(self, symbol: str) -> None:
        if mt5 is None or not symbol or symbol == "UNKNOWN":
            self.m5_direction_status = {
                **self.m5_direction_status,
                "symbol": symbol or "",
                "direction": "neutral",
                "reason": "No symbol is selected for the M5 direction observer yet.",
            }
            return

        resolved_symbol, symbol_info, error_message = self._resolve_chart_symbol(symbol)
        if symbol_info is None:
            self.m5_direction_status = {
                **self.m5_direction_status,
                "symbol": resolved_symbol,
                "direction": "neutral",
                "reason": error_message or f"Could not resolve {symbol} for M5 direction analysis.",
            }
            return

        candle_count = max(CONFIG.m5_direction_slow_period + CONFIG.m5_direction_confirm_candles + 3, 24)
        rates = mt5.copy_rates_from_pos(
            resolved_symbol,
            getattr(mt5, "TIMEFRAME_M5", 5),
            0,
            candle_count,
        )
        if rates is None or len(rates) < CONFIG.m5_direction_slow_period + CONFIG.m5_direction_confirm_candles + 1:
            self.m5_direction_status = {
                **self.m5_direction_status,
                "symbol": resolved_symbol,
                "direction": "neutral",
                "reason": f"Not enough M5 candles yet to determine direction for {resolved_symbol}.",
            }
            return

        candles = [
            {
                "time": datetime.fromtimestamp(int(rate["time"]), UTC).isoformat(),
                "open": safe_float(rate["open"]),
                "high": safe_float(rate["high"]),
                "low": safe_float(rate["low"]),
                "close": safe_float(rate["close"]),
            }
            for rate in rates
        ]
        closed_candles = candles[:-1]
        if len(closed_candles) < CONFIG.m5_direction_slow_period + CONFIG.m5_direction_confirm_candles:
            self.m5_direction_status = {
                **self.m5_direction_status,
                "symbol": resolved_symbol,
                "direction": "neutral",
                "reason": f"Waiting for more fully closed M5 candles on {resolved_symbol}.",
            }
            return

        closes = [item["close"] for item in closed_candles]
        fast_average = self._average(closes[-CONFIG.m5_direction_fast_period:])
        slow_average = self._average(closes[-CONFIG.m5_direction_slow_period:])
        confirm_window = closes[-CONFIG.m5_direction_confirm_candles:]
        previous_window = closes[-(CONFIG.m5_direction_confirm_candles + 1):-1]
        last_candle = closed_candles[-1]
        bullish_stack = all(curr > prev for prev, curr in zip(previous_window, confirm_window))
        bearish_stack = all(curr < prev for prev, curr in zip(previous_window, confirm_window))
        last_candle_bullish = last_candle["close"] > last_candle["open"]
        last_candle_bearish = last_candle["close"] < last_candle["open"]

        direction = "neutral"
        strength = 0
        reason = f"{resolved_symbol} is ranging on M5 right now."
        if fast_average > slow_average and bullish_stack and last_candle_bullish:
            direction = "bullish"
            strength = 3
            reason = (
                f"{resolved_symbol} M5 turned bullish: the last {CONFIG.m5_direction_confirm_candles} closes are rising "
                "and price is holding above the fast/slow averages."
            )
        elif fast_average < slow_average and bearish_stack and last_candle_bearish:
            direction = "bearish"
            strength = 3
            reason = (
                f"{resolved_symbol} M5 turned bearish: the last {CONFIG.m5_direction_confirm_candles} closes are falling "
                "and price is trading below the fast/slow averages."
            )

        previous_direction = str(self.m5_direction_status.get("direction") or "neutral")
        last_alerted_direction = str(self.m5_direction_status.get("last_alerted_direction") or "")
        last_alerted_candle_time = str(self.m5_direction_status.get("last_alerted_candle_time") or "")
        last_alerted_at_raw = str(self.m5_direction_status.get("last_alerted_at") or "")
        last_alerted_at = None
        if last_alerted_at_raw:
            try:
                last_alerted_at = datetime.fromisoformat(last_alerted_at_raw)
            except ValueError:
                last_alerted_at = None

        self.m5_direction_status = {
            **self.m5_direction_status,
            "symbol": resolved_symbol,
            "timeframe": "M5",
            "direction": direction,
            "strength": strength,
            "last_closed_candle_time": last_candle["time"],
            "last_price": last_candle["close"],
            "fast_average": fast_average,
            "slow_average": slow_average,
            "reason": reason,
        }

        cooldown_ok = last_alerted_at is None or (utc_now() - last_alerted_at).total_seconds() >= CONFIG.m5_direction_alert_cooldown_seconds
        should_alert = (
            direction in {"bullish", "bearish"}
            and direction != previous_direction
            and (last_alerted_direction != direction or last_alerted_candle_time != last_candle["time"])
            and cooldown_ok
        )
        if not should_alert:
            return

        self.m5_direction_status["last_alerted_direction"] = direction
        self.m5_direction_status["last_alerted_candle_time"] = last_candle["time"]
        self.m5_direction_status["last_alerted_at"] = iso_now()
        self._alert(
            "m5_direction_shift",
            "info",
            reason,
            sound="trend_bullish" if direction == "bullish" else "trend_bearish",
            payload={
                "symbol": resolved_symbol,
                "timeframe": "M5",
                "direction": direction,
                "last_closed_candle_time": last_candle["time"],
                "last_close": last_candle["close"],
                "fast_average": round(fast_average, 5),
                "slow_average": round(slow_average, 5),
            },
            email_subject=f"M5 {direction.title()} Alert: {resolved_symbol}",
        )

    def _send_trade_request(self, request: dict[str, Any]) -> tuple[bool, str, Any]:
        if mt5 is None:
            return False, "MetaTrader5 package is not installed.", None
        result = mt5.order_send(request)
        if result is not None and getattr(result, "retcode", None) == getattr(mt5, "TRADE_RETCODE_DONE", 10009):
            return True, "ok", result

        last_error = mt5.last_error()
        message = f"MT5 order_send failed: {last_error}"
        if result is not None:
            comment = getattr(result, "comment", "")
            retcode = getattr(result, "retcode", "")
            message = f"MT5 order_send failed: retcode={retcode} comment={comment or last_error}"
        return False, message, result

    def _build_market_request(self, *, symbol: str, volume: float, side: str, position_ticket: int | None = None) -> tuple[dict[str, Any] | None, str]:
        if mt5 is None:
            return None, "MetaTrader5 package is not installed."
        symbol_name = symbol.strip()
        if not symbol_name:
            return None, "A symbol is required."
        normalized_side = normalize_side(side)
        if normalized_side not in {"buy", "sell"}:
            return None, "Trade side must be buy or sell."
        if volume <= 0:
            return None, "Volume must be greater than zero."

        symbol_info = mt5.symbol_info(symbol_name)
        if symbol_info is None:
            return None, f"Symbol {symbol_name} is not available in this terminal."
        if not getattr(symbol_info, "visible", True):
            mt5.symbol_select(symbol_name, True)
            symbol_info = mt5.symbol_info(symbol_name)
        tick = mt5.symbol_info_tick(symbol_name)
        if tick is None:
            return None, f"Could not read live price for {symbol_name}."

        order_type = getattr(mt5, "ORDER_TYPE_BUY", 0) if normalized_side == "buy" else getattr(mt5, "ORDER_TYPE_SELL", 1)
        price = safe_float(getattr(tick, "ask", 0.0) if normalized_side == "buy" else getattr(tick, "bid", 0.0))
        filling_mode = getattr(symbol_info, "filling_mode", getattr(mt5, "ORDER_FILLING_IOC", 1))
        request = {
            "action": getattr(mt5, "TRADE_ACTION_DEAL", 1),
            "symbol": symbol_name,
            "volume": volume,
            "type": order_type,
            "price": price,
            "deviation": 20,
            "magic": 20260427,
            "comment": "Trade Observer Dashboard",
            "type_time": getattr(mt5, "ORDER_TIME_GTC", 0),
            "type_filling": filling_mode,
        }
        if position_ticket is not None:
            request["position"] = int(position_ticket)
        return request, "ok"

    def close_position(self, ticket: int) -> dict[str, Any]:
        if not self._initialize():
            return {"ok": False, "message": self.connection_error}
        position = None
        if mt5 is not None:
            matches = mt5.positions_get(ticket=int(ticket)) or []
            position = matches[0] if matches else None
        if position is None:
            return {"ok": False, "message": f"Open position {ticket} was not found."}

        side = "sell" if self._position_side(position) == "buy" else "buy"
        request, message = self._build_market_request(
            symbol=str(getattr(position, "symbol", "")),
            volume=safe_float(getattr(position, "volume", 0.0)),
            side=side,
            position_ticket=int(getattr(position, "ticket", ticket)),
        )
        if request is None:
            return {"ok": False, "message": message}
        success, send_message, result = self._send_trade_request(request)
        if not success:
            extra_hint = ""
            if "retcode=10027" in send_message or "AutoTrading disabled by client" in send_message:
                extra_hint = " Enable AutoTrading/Algo Trading in the MT5 terminal, then try closing the trade again."
            return {"ok": False, "message": f"{send_message}{extra_hint}"}

        self.connected = False
        self._poll()
        return {
            "ok": True,
            "message": f"Close request sent for trade {ticket}.",
            "ticket": ticket,
            "retcode": getattr(result, "retcode", None),
        }

    def open_market_trade(self, symbol: str, volume: float, side: str) -> dict[str, Any]:
        if self.trade_lock_enabled:
            return {
                "ok": False,
                "message": "Trade Lock is enabled. New trade entries are blocked by this dashboard.",
                "trade_lock_enabled": True,
            }
        if not self._initialize():
            return {"ok": False, "message": self.connection_error}
        request, message = self._build_market_request(symbol=symbol, volume=volume, side=side)
        if request is None:
            return {"ok": False, "message": message}
        success, send_message, result = self._send_trade_request(request)
        if not success:
            return {"ok": False, "message": send_message}

        self.connected = False
        self._poll()
        return {
            "ok": True,
            "message": f"{normalize_side(side).upper()} order sent for {symbol.strip()} at {volume:.2f} lots.",
            "symbol": symbol.strip(),
            "volume": volume,
            "side": normalize_side(side),
            "retcode": getattr(result, "retcode", None),
        }

    def _sync_positions(self, positions: list[Any], balance: float) -> None:
        for position in positions:
            ticket = int(position.ticket)
            current_price = safe_float(position.price_current)
            trade = TradeSnapshot(
                ticket=ticket,
                position_id=int(getattr(position, "identifier", ticket)),
                symbol=position.symbol,
                side=self._position_side(position),
                volume=safe_float(position.volume),
                entry_price=safe_float(position.price_open),
                stop_loss=safe_float(position.sl),
                take_profit=safe_float(position.tp),
                open_time=datetime.fromtimestamp(int(position.time), UTC).isoformat(),
                current_price=current_price,
                profit=safe_float(position.profit),
                pips=self._position_pips(position, current_price),
                seconds_open=max(0, int(time.time() - int(position.time))),
            )

            previous = self.trades.get(ticket)
            if previous is None:
                self.trades[ticket] = trade
                self.db.open_trade(
                    {
                        "ticket": trade.ticket,
                        "position_id": trade.position_id,
                        "symbol": trade.symbol,
                        "side": trade.side,
                        "volume": trade.volume,
                        "entry_price": trade.entry_price,
                        "stop_loss": trade.stop_loss,
                        "take_profit": trade.take_profit,
                        "open_time": trade.open_time,
                        "entry_balance": balance,
                        "last_price": trade.current_price,
                        "last_pips": trade.pips,
                        "account_login": self._current_account_login(),
                        "account_server": self._current_account_server(),
                    }
                )
                if self.trade_lock_enabled:
                    self._alert(
                        "trade_lock_breached",
                        "warn",
                        f"Trade {ticket} opened while Trade Lock was enabled. This entry likely came from outside the dashboard.",
                        ticket=ticket,
                        sound="warning",
                        payload={
                            "ticket": trade.ticket,
                            "symbol": trade.symbol,
                            "side": trade.side,
                            "volume": trade.volume,
                            "entry_price": trade.entry_price,
                        },
                    )
                self._alert(
                    "entry",
                    "info",
                    f"Trade {ticket} opened ({trade.side.upper()}) at {trade.entry_price:.2f}",
                    ticket=ticket,
                    sound="entry",
                    payload={
                        "ticket": trade.ticket,
                        "symbol": trade.symbol,
                        "side": trade.side,
                        "volume": trade.volume,
                        "entry_price": trade.entry_price,
                        "stop_loss": trade.stop_loss,
                        "take_profit": trade.take_profit,
                        "open_time": trade.open_time,
                    },
                    email_subject=f"Trade Started: #{ticket} {trade.symbol} {trade.side.upper()}",
                )
                previous = trade
            else:
                if not math.isclose(previous.take_profit, trade.take_profit, rel_tol=0.0, abs_tol=0.0000001):
                    action = "set" if previous.take_profit <= 0 < trade.take_profit else "updated"
                    self._alert(
                        "take_profit_updated",
                        "success",
                        f"Trade {ticket} take profit {action} to {trade.take_profit:.2f}.",
                        ticket=ticket,
                        sound="tp_set",
                        payload={
                            "previous_take_profit": previous.take_profit,
                            "take_profit": trade.take_profit,
                        },
                    )

                if not math.isclose(previous.stop_loss, trade.stop_loss, rel_tol=0.0, abs_tol=0.0000001):
                    action = "set" if previous.stop_loss <= 0 < trade.stop_loss else "updated"
                    severity = "warn" if trade.stop_loss > 0 else "info"
                    self._alert(
                        "stop_loss_updated",
                        severity,
                        f"Trade {ticket} stop loss {action} to {trade.stop_loss:.2f}.",
                        ticket=ticket,
                        sound="sl_set",
                        payload={
                            "previous_stop_loss": previous.stop_loss,
                            "stop_loss": trade.stop_loss,
                        },
                    )

                trade.flags_sent = previous.flags_sent
                trade.max_profit = max(previous.max_profit, trade.profit)
                trade.max_drawdown = min(previous.max_drawdown, trade.profit)
                self.trades[ticket] = trade

            self.db.update_open_trade(
                ticket,
                {
                    "last_price": trade.current_price,
                    "last_pips": trade.pips,
                    "stop_loss": trade.stop_loss,
                    "take_profit": trade.take_profit,
                    "max_profit": trade.max_profit,
                    "max_drawdown": trade.max_drawdown,
                },
            )
            self._scan_trade_risk(trade)

    def _scan_trade_risk(self, trade: TradeSnapshot) -> None:
        sl = trade.stop_loss
        if sl > 0:
            total_distance = abs(trade.entry_price - sl)
            remaining = abs(trade.current_price - sl)
            if total_distance > 0:
                progress_fraction = max(0.0, min(1.0, 1.0 - (remaining / total_distance)))
                for threshold in (0.50, 0.75):
                    flag = f"stop_warning_{int(threshold * 100)}"
                    if progress_fraction >= threshold and flag not in trade.flags_sent:
                        trade.flags_sent.add(flag)
                        self._alert(
                            "approaching_stop",
                            "warn",
                            f"Trade {trade.ticket} is approaching stop loss ({int(threshold * 100)}% of the stop distance used).",
                            ticket=trade.ticket,
                            sound="warning",
                            payload={
                                "remaining_distance": remaining,
                                "stop_loss": sl,
                                "threshold_percent": int(threshold * 100),
                                "progress_fraction": round(progress_fraction, 4),
                            },
                            email_subject=f"Stop Loss Warning {int(threshold * 100)}%: Trade #{trade.ticket}",
                        )

        tp = trade.take_profit
        if tp > 0:
            if trade.side == "buy" and trade.current_price >= tp and "tp_live" not in trade.flags_sent:
                trade.flags_sent.add("tp_live")
                self._alert(
                    "take_profit_reached",
                    "success",
                    f"Trade {trade.ticket} reached take profit.",
                    ticket=trade.ticket,
                    sound="tp",
                    payload={"price": trade.current_price, "take_profit": tp},
                )
            if trade.side == "sell" and trade.current_price <= tp and "tp_live" not in trade.flags_sent:
                trade.flags_sent.add("tp_live")
                self._alert(
                    "take_profit_reached",
                    "success",
                    f"Trade {trade.ticket} reached take profit.",
                    ticket=trade.ticket,
                    sound="tp",
                    payload={"price": trade.current_price, "take_profit": tp},
                )

    def _scan_closed_positions(self, balance: float) -> None:
        open_tickets = {int(position.ticket) for position in (mt5.positions_get() or [])} if mt5 is not None else set()
        closed_candidates = [ticket for ticket in list(self.trades) if ticket not in open_tickets]
        closed_count = len(closed_candidates)
        for ticket in closed_candidates:
            trade = self.trades.pop(ticket)
            close_info = self._resolve_close_info(ticket, trade)
            reason = infer_close_reason(trade.side, close_info["close_price"], trade.stop_loss, trade.take_profit)

            self.db.close_trade(
                ticket,
                {
                    "close_price": close_info["close_price"],
                    "close_time": close_info["close_time"],
                    "profit": close_info["profit"],
                    "swap": close_info["swap"],
                    "commission": close_info["commission"],
                    "reason": reason,
                    "exit_balance": balance,
                },
            )

            if reason == "take_profit":
                event_type = "closed_take_profit"
                sound = "tp"
                severity = "success"
                message = f"Trade {ticket} closed at take profit."
            elif reason == "stop_loss":
                event_type = "stop_loss_hit"
                sound = "sl"
                severity = "danger"
                message = f"Trade {ticket} hit stop loss."
            else:
                event_type = "close"
                sound = "close"
                severity = "info"
                message = f"Trade {ticket} closed."

            if closed_count > 1:
                message = f"{message} {closed_count} trades closed in this batch."

            self._alert(
                event_type,
                severity,
                message,
                ticket=ticket,
                sound=sound,
                payload={
                    "close_price": close_info["close_price"],
                    "close_time": close_info["close_time"],
                    "profit": close_info["profit"],
                    "reason": reason,
                    "closed_count": closed_count,
                },
                email_subject=f"Trade Closed: #{ticket} {trade.symbol}",
            )

    def _resolve_close_info(self, ticket: int, trade: TradeSnapshot) -> dict[str, Any]:
        default = {
            "close_price": trade.current_price or trade.entry_price,
            "close_time": iso_now(),
            "profit": trade.profit,
            "swap": 0.0,
            "commission": 0.0,
        }
        if mt5 is None:
            return default

        date_from = utc_now() - timedelta(hours=CONFIG.history_lookback_hours)
        date_to = utc_now() + timedelta(minutes=1)
        deals = mt5.history_deals_get(date_from, date_to)
        if deals is None:
            return default

        matching = [deal for deal in deals if int(getattr(deal, "position_id", 0) or 0) in {ticket, trade.position_id}]
        if not matching:
            return default

        matching.sort(key=lambda deal: int(getattr(deal, "time", 0)))
        closing = matching[-1]
        profit = sum(safe_float(getattr(deal, "profit", 0.0)) for deal in matching)
        swap = sum(safe_float(getattr(deal, "swap", 0.0)) for deal in matching)
        commission = sum(safe_float(getattr(deal, "commission", 0.0)) for deal in matching)
        return {
            "close_price": safe_float(getattr(closing, "price", trade.current_price)),
            "close_time": datetime.fromtimestamp(int(getattr(closing, "time", time.time())), UTC).isoformat(),
            "profit": profit,
            "swap": swap,
            "commission": commission,
        }

    def _scan_account_risk(self) -> None:
        balance = safe_float(self.account.get("balance"))
        equity = safe_float(self.account.get("equity"))
        if self.initial_balance <= 0:
            return

        drawdown = max(0.0, self.initial_balance - equity)
        drawdown_fraction = drawdown / self.initial_balance if self.initial_balance else 0.0

        account_key = account_scope_key(self._current_account_login(), self._current_account_server())
        for threshold in (0.20, 0.50, 0.75):
            setting_key = f"capital_email::{account_key}::{int(threshold * 100)}"
            if drawdown_fraction >= threshold and self.db.get_setting(setting_key, "") != "yes":
                self.db.set_setting(setting_key, "yes")
                self._alert(
                    "capital_warning",
                    "warn",
                    f"Account drawdown has reached {int(threshold * 100)}% of starting capital.",
                    sound="warning",
                    payload={
                        "initial_balance": self.initial_balance,
                        "equity": equity,
                        "balance": balance,
                        "threshold_percent": int(threshold * 100),
                    },
                    email_subject=f"Capital Warning {int(threshold * 100)}%: Account {self.account.get('login')}",
                )

        if drawdown_fraction >= CONFIG.account_blown_drawdown_fraction:
            if self.db.get_setting("account_blown_announced", "") != "yes":
                self.db.set_setting("account_blown_announced", "yes")
                self._alert(
                    "account_blown",
                    "danger",
                    "Account drawdown has reached the critical blowout threshold.",
                    sound="blown",
                    payload={"initial_balance": self.initial_balance, "equity": equity, "balance": balance},
                )
        elif drawdown_fraction >= CONFIG.capital_warning_drawdown_fraction:
            key = f"capital_warning_{utc_now().date().isoformat()}"
            if self.db.get_setting(key, "") != "yes":
                self.db.set_setting(key, "yes")
                self._alert(
                    "capital_warning",
                    "warn",
                    "Equity is approaching a critical capital-loss threshold.",
                    sound="warning",
                    payload={"initial_balance": self.initial_balance, "equity": equity, "balance": balance},
                )

    def _scan_account_switch(self, snapshot: dict[str, Any]) -> None:
        login = snapshot.get("login")
        server = snapshot.get("server")
        if login is None:
            return

        if self.last_account_login is None:
            self.last_account_login = login
            self.last_account_server = server
            self.account = snapshot
            self.initial_balance = self._load_initial_balance()
            return

        if login != self.last_account_login or server != self.last_account_server:
            previous_login = self.last_account_login
            previous_server = self.last_account_server
            self.last_account_login = login
            self.last_account_server = server
            self.trades = {}
            self.pending_orders = {}
            self.initial_balance = 0.0
            self.account = snapshot
            self.initial_balance = self._load_initial_balance()
            self._remember_initial_balance(safe_float(snapshot.get("balance")))
            self._alert(
                "account_switched",
                "info",
                f"Trading account switched to {login} on {server}.",
                sound="entry",
                payload={
                    "previous_login": previous_login,
                    "previous_server": previous_server,
                    "login": login,
                    "server": server,
                },
            )

    def _alert(
        self,
        event_type: str,
        severity: str,
        message: str,
        *,
        ticket: int | None = None,
        sound: str | None = None,
        payload: dict[str, Any] | None = None,
        email_subject: str | None = None,
    ) -> None:
        self.db.log_event(
            event_type,
            severity,
            message,
            ticket=ticket,
            payload=payload,
            account_login=self._current_account_login(),
            account_server=self._current_account_server(),
        )
        if sound:
            self.sounder.play(sound)
        if email_subject:
            self._send_email_notification(email_subject, message, ticket=ticket, payload=payload or {})

    def _send_email_notification(
        self,
        subject: str,
        message: str,
        *,
        ticket: int | None = None,
        payload: dict[str, Any],
    ) -> None:
        if not self.notifier.enabled:
            return
        if not self.email_notifications_enabled():
            return
        details = [
            message,
            "",
            f"Time: {iso_now()}",
            f"Account: {self.account.get('login') or '-'} on {self.account.get('server') or '-'}",
            f"Equity: {safe_float(self.account.get('equity')):.2f}",
            f"Balance: {safe_float(self.account.get('balance')):.2f}",
        ]
        if ticket is not None:
            details.append(f"Trade Ticket: {ticket}")
        for key, value in payload.items():
            details.append(f"{key}: {value}")
        try:
            self.notifier.send(subject, "\n".join(details))
        except Exception as exc:
            self.db.log_event(
                "email_error",
                "warn",
                f"Email notification failed: {exc}",
                ticket=ticket,
                payload={"subject": subject},
                account_login=self._current_account_login(),
                account_server=self._current_account_server(),
            )

    def send_test_email_alert(self, event_type: str) -> dict[str, Any]:
        normalized = event_type.strip().lower()
        templates = {
            "entry": ("Test Email: Trade Started", "Test only: this simulates a trade start email notification."),
            "close": ("Test Email: Trade Closed", "Test only: this simulates a trade close email notification."),
            "approaching_stop": ("Test Email: Stop Loss Warning", "Test only: this simulates a stop loss warning email notification at a configured threshold."),
            "capital_warning": ("Test Email: Capital Warning", "Test only: this simulates a capital warning email notification."),
            "stop_loss_hit": ("Test Email: Stop Loss Hit", "Test only: this simulates a stop loss hit email notification."),
            "account_blown": ("Test Email: Account Blown", "Test only: this simulates an account blown email notification."),
        }
        if normalized not in templates:
            return {"ok": False, "message": f"No email test template is configured for {event_type}."}
        if not self.notifier.enabled:
            return {"ok": False, "message": "SMTP is not configured for email notifications."}
        subject, body = templates[normalized]
        self._send_email_notification(subject, body, ticket=999999, payload={"event_type": normalized, "test": True})
        return {"ok": True, "message": f"Test email sent for {normalized}.", "event_type": normalized}

    def state(self) -> dict[str, Any]:
        with self.lock:
            trades = []
            for trade in sorted(self.trades.values(), key=lambda item: item.open_time):
                trades.append(
                    {
                        "ticket": trade.ticket,
                        "position_id": trade.position_id,
                        "symbol": trade.symbol,
                        "side": trade.side,
                        "volume": trade.volume,
                        "entry_price": trade.entry_price,
                        "stop_loss": trade.stop_loss,
                        "take_profit": trade.take_profit,
                        "current_price": trade.current_price,
                        "profit": trade.profit,
                        "pips": trade.pips,
                        "open_time": trade.open_time,
                        "seconds_open": trade.seconds_open,
                    }
                )

            pending_orders = []
            for order in sorted(self.pending_orders.values(), key=lambda item: item.placed_time):
                pending_orders.append(
                    {
                        "ticket": order.ticket,
                        "symbol": order.symbol,
                        "side": order.side,
                        "order_type": order.order_type,
                        "volume": order.volume,
                        "trigger_price": order.trigger_price,
                        "stop_loss": order.stop_loss,
                        "take_profit": order.take_profit,
                        "stop_limit_price": order.stop_limit_price,
                        "current_price": order.current_price,
                        "placed_time": order.placed_time,
                        "seconds_open": order.seconds_open,
                        "expiration_time": order.expiration_time,
                    }
                )

            return {
                "connected": self.connected,
                "connection_error": self.connection_error,
                "mt5_package_available": mt5 is not None,
                "symbol": self.primary_symbol,
                "account": {
                    **self.account,
                    "initial_balance": self.initial_balance,
                },
                "active_trades": trades,
                "pending_orders": pending_orders,
                "recent_prices": list(self.recent_prices),
                "recent_alerts": self.db.get_recent_alerts(
                    account_login=self._current_account_login(),
                    account_server=self._current_account_server(),
                ),
                "trade_lock_enabled": self.trade_lock_enabled,
                "email_notifications_enabled": self.email_notifications_enabled(),
                "notifications_enabled": self.notifications_enabled(),
                "alert_type_enabled": self.alert_type_preferences(),
                "smtp_configured": self.notifier.enabled,
                "selected_profile_alias": self.selected_profile_alias,
                "selected_profile_group": str((self.connection_profile or {}).get("group", "")),
                "config": asdict(CONFIG),
                "server_time": iso_now(),
                "orl_live_status": self.orl_live_observer.get_live_status() if self.orl_live_observer is not None else {"active": False, "message": "ORL observer unavailable"},
                "m5_direction_status": self.m5_direction_status,
            }

    def deposit_history(self, range_key: str = "all", exact_date: str = "") -> dict[str, Any]:
        if not self._initialize():
            return {
                "connected": False,
                "connection_error": self.connection_error,
                "items": [],
                "totals": {"usd": 0.0, "ghs": 0.0, "count": 0},
                "rate": {"usd_per_ghs": USD_PER_GHS},
            }

        date_from, date_to = resolve_time_window(range_key, exact_date)
        deals = mt5.history_deals_get(date_from, date_to) if mt5 is not None else None
        if deals is None:
            return {
                "connected": self.connected,
                "connection_error": f"history_deals_get failed: {mt5.last_error() if mt5 is not None else 'MT5 unavailable'}",
                "items": [],
                "totals": {"usd": 0.0, "ghs": 0.0, "count": 0},
                "rate": {"usd_per_ghs": USD_PER_GHS},
            }

        items = self._deposit_items_from_deals(
            deals,
            account_alias=self.selected_profile_alias or "Current MT5 Session",
            account_login=self._current_account_login(),
            account_server=self._current_account_server(),
        )
        total_usd = sum(item["amount_usd"] for item in items)
        return {
            "connected": self.connected,
            "connection_error": self.connection_error,
            "items": items,
            "totals": {
                "usd": total_usd,
                "ghs": total_usd / USD_PER_GHS if USD_PER_GHS else 0.0,
                "count": len(items),
            },
            "rate": {"usd_per_ghs": USD_PER_GHS},
            "range_key": range_key,
            "exact_date": exact_date,
        }

    def _deposit_items_from_deals(
        self,
        deals: Any,
        *,
        account_alias: str,
        account_login: int | None,
        account_server: str,
    ) -> list[dict[str, Any]]:
        balance_types = {
            getattr(mt5, "DEAL_TYPE_BALANCE", -1),
            getattr(mt5, "DEAL_TYPE_CREDIT", -2),
        }
        items: list[dict[str, Any]] = []
        for deal in deals or []:
            deal_type = int(getattr(deal, "type", -999))
            amount = safe_float(getattr(deal, "profit", 0.0))
            if deal_type not in balance_types or amount <= 0:
                continue
            items.append(
                {
                    "ticket": int(getattr(deal, "ticket", 0)),
                    "time": datetime.fromtimestamp(int(getattr(deal, "time", time.time())), UTC).isoformat(),
                    "amount_usd": amount,
                    "amount_ghs": amount / USD_PER_GHS if USD_PER_GHS else 0.0,
                    "comment": getattr(deal, "comment", "") or "Deposit / balance funding",
                    "type": "credit" if deal_type == getattr(mt5, "DEAL_TYPE_CREDIT", -2) else "balance",
                    "account_alias": account_alias,
                    "account_login": account_login,
                    "account_server": account_server,
                }
            )
        items.sort(key=lambda item: item["time"], reverse=True)
        return items

    def _fetch_deposit_items_for_profile(self, profile: dict[str, Any], *, range_key: str, exact_date: str = "") -> tuple[list[dict[str, Any]], str]:
        date_from, date_to = resolve_time_window(range_key, exact_date)
        alias = str(profile.get("alias", "")).strip() or "MT5 Profile"
        login = normalize_account_login(profile.get("login"))
        server_name = normalize_account_server(profile.get("server"))
        terminal_path = str(profile.get("terminal_path", "")).strip()

        use_current_connection = (
            self.connected
            and (
                alias.lower() == str(self.selected_profile_alias or "").strip().lower()
                or (terminal_path and terminal_path.lower() == str((self.connection_profile or {}).get("terminal_path", "")).strip().lower())
            )
        )

        if use_current_connection:
            deals = mt5.history_deals_get(date_from, date_to) if mt5 is not None else None
            if deals is None:
                return [], f"{alias}: history_deals_get failed: {mt5.last_error() if mt5 is not None else 'MT5 unavailable'}"
            return (
                self._deposit_items_from_deals(
                    deals,
                    account_alias=alias,
                    account_login=self._current_account_login(),
                    account_server=self._current_account_server(),
                ),
                "",
            )

        if login is None:
            return [], f"{alias}: missing MT5 login in saved profile."

        try:
            if mt5 is not None:
                mt5.shutdown()
        except Exception:
            pass

        initialized = bool(mt5.initialize(path=terminal_path)) if terminal_path and mt5 is not None else bool(mt5.initialize()) if mt5 is not None else False
        if not initialized:
            return [], f"{alias}: MT5 initialize failed: {mt5.last_error() if mt5 is not None else 'MT5 unavailable'}"

        if not mt5.login(login=login, password=str(profile.get("password", "")), server=server_name or None):
            error_text = f"{alias}: MT5 login failed: {mt5.last_error() if mt5 is not None else 'MT5 unavailable'}"
            try:
                mt5.shutdown()
            except Exception:
                pass
            return [], error_text

        deals = mt5.history_deals_get(date_from, date_to) if mt5 is not None else None
        if deals is None:
            error_text = f"{alias}: history_deals_get failed: {mt5.last_error() if mt5 is not None else 'MT5 unavailable'}"
            try:
                mt5.shutdown()
            except Exception:
                pass
            return [], error_text

        return self._deposit_items_from_deals(
            deals,
            account_alias=alias,
            account_login=login,
            account_server=server_name,
        ), ""

    def deposit_history_for_profiles(self, *, range_key: str, profile_aliases: list[str], exact_date: str = "") -> dict[str, Any]:
        aliases = [item.strip() for item in profile_aliases if item and item.strip()]
        if not aliases:
            payload = self.deposit_history(range_key=range_key, exact_date=exact_date)
            payload["profile_aliases"] = []
            payload["warnings"] = []
            return payload

        previous_profile = dict(self.connection_profile or {})
        previous_alias = self.selected_profile_alias
        previous_connect_requested = self.connect_requested
        previous_connected = self.connected
        warnings: list[str] = []
        items: list[dict[str, Any]] = []
        try:
            for alias in aliases:
                profile = DB.find_account_profile(alias)
                if not profile:
                    warnings.append(f"{alias}: saved profile not found.")
                    continue
                profile_items, warning = self._fetch_deposit_items_for_profile(profile, range_key=range_key, exact_date=exact_date)
                items.extend(profile_items)
                if warning:
                    warnings.append(warning)
        finally:
            try:
                if mt5 is not None:
                    mt5.shutdown()
            except Exception:
                pass
            self.connection_profile = previous_profile or None
            self.selected_profile_alias = previous_alias
            self.connect_requested = previous_connect_requested
            self.connected = False
            self.connection_error = ""
            if previous_connect_requested and self.connection_profile:
                self._initialize()
            else:
                self.connected = previous_connected

        items.sort(key=lambda item: item["time"], reverse=True)
        total_usd = sum(item["amount_usd"] for item in items)
        return {
            "connected": self.connected,
            "connection_error": self.connection_error,
            "items": items,
            "totals": {
                "usd": total_usd,
                "ghs": total_usd / USD_PER_GHS if USD_PER_GHS else 0.0,
                "count": len(items),
            },
            "rate": {"usd_per_ghs": USD_PER_GHS},
            "range_key": range_key,
            "exact_date": exact_date,
            "profile_aliases": aliases,
            "warnings": warnings,
        }

    def history_journal(
        self,
        range_key: str,
        outcome: str,
        lot_size: str,
        symbols: list[str] | None,
        special_filter: str,
        exact_date: str,
    ) -> dict[str, Any]:
        if not self._initialize():
            return {
                "connected": False,
                "connection_error": self.connection_error,
                "days": [],
                "totals": {"total_trades": 0, "wins": 0, "losses": 0, "total_profit": 0.0},
                "lot_sizes": [],
                "source": "mt5",
            }

        now = utc_now()
        start_today = datetime(now.year, now.month, now.day, tzinfo=UTC)
        start_map = {
            "today": start_today,
            "2d": start_today - timedelta(days=1),
            "2w": start_today - timedelta(days=13),
            "month": start_today - timedelta(days=29),
            "all": now - timedelta(days=3650),
        }
        exact_window = parse_exact_date(exact_date)
        if exact_window:
            date_from, date_to = exact_window
        else:
            date_from = start_map.get(range_key, start_today)
            date_to = now + timedelta(days=2)
        history_fetch_from = date_from if range_key == "all" else max(datetime(2000, 1, 1, tzinfo=UTC), date_from - timedelta(days=90))
        deals = mt5.history_deals_get(history_fetch_from, date_to) if mt5 is not None else None
        if deals is None:
            return {
                "connected": self.connected,
                "connection_error": f"history_deals_get failed: {mt5.last_error() if mt5 is not None else 'MT5 unavailable'}",
                "days": [],
                "totals": {"total_trades": 0, "wins": 0, "losses": 0, "total_profit": 0.0},
                "lot_sizes": [],
                "source": "mt5",
            }

        position_map: dict[int, dict[str, Any]] = {}
        entry_in_types = {
            getattr(mt5, "DEAL_ENTRY_IN", 0),
            getattr(mt5, "DEAL_ENTRY_INOUT", 1),
        }
        entry_out_types = {
            getattr(mt5, "DEAL_ENTRY_OUT", 1),
            getattr(mt5, "DEAL_ENTRY_INOUT", 1),
            getattr(mt5, "DEAL_ENTRY_OUT_BY", 3),
        }
        for deal in deals:
            deal_type = int(getattr(deal, "type", -999))
            if deal_type in {getattr(mt5, "DEAL_TYPE_BALANCE", -1), getattr(mt5, "DEAL_TYPE_CREDIT", -2)}:
                continue

            position_id = int(getattr(deal, "position_id", 0) or 0)
            if position_id == 0:
                position_id = int(getattr(deal, "order", 0) or getattr(deal, "ticket", 0) or 0)
            if position_id == 0:
                continue

            item = position_map.setdefault(
                position_id,
                {
                    "ticket": position_id,
                    "symbol": getattr(deal, "symbol", ""),
                    "side": "buy" if int(getattr(deal, "type", 0)) == getattr(mt5, "DEAL_TYPE_BUY", 0) else "sell",
                    "volume": safe_float(getattr(deal, "volume", 0.0)),
                    "entry_price": 0.0,
                    "stop_loss": 0.0,
                    "take_profit": 0.0,
                    "open_time": None,
                    "close_price": 0.0,
                    "close_time": None,
                    "profit": 0.0,
                    "reason": "history",
                    "status": "closed",
                    "entry_balance": 0.0,
                    "exit_balance": 0.0,
                },
            )

            entry_flag = int(getattr(deal, "entry", -1))
            deal_time = datetime.fromtimestamp(int(getattr(deal, "time", time.time())), UTC).isoformat()
            deal_price = safe_float(getattr(deal, "price", 0.0))
            item["volume"] = max(item["volume"], safe_float(getattr(deal, "volume", 0.0)))
            item["profit"] += safe_float(getattr(deal, "profit", 0.0))

            if entry_flag in entry_in_types and (item["open_time"] is None or deal_time < item["open_time"]):
                item["open_time"] = deal_time
                item["entry_price"] = deal_price
                item["symbol"] = getattr(deal, "symbol", item["symbol"])
                item["side"] = "buy" if int(getattr(deal, "type", 0)) == getattr(mt5, "DEAL_TYPE_BUY", 0) else "sell"

            if entry_flag in entry_out_types and (item["close_time"] is None or deal_time > item["close_time"]):
                item["close_time"] = deal_time
                item["close_price"] = deal_price

        def row_in_requested_window(row: dict[str, Any]) -> bool:
            close_time = row.get("close_time")
            open_time = row.get("open_time")
            for raw_value in (close_time, open_time):
                if not raw_value:
                    continue
                try:
                    dt = datetime.fromisoformat(str(raw_value))
                except ValueError:
                    continue
                if date_from <= dt < date_to:
                    return True
            return False

        rows = [row for row in position_map.values() if row["open_time"] and row_in_requested_window(row)]
        available_symbols = sorted({str(row.get("symbol") or "").strip().upper() for row in rows if str(row.get("symbol") or "").strip()})
        normalized_symbols = sorted({str(item or "").strip().upper() for item in (symbols or []) if str(item or "").strip()})

        if outcome == "profit":
            rows = [row for row in rows if safe_float(row["profit"]) > 0]
        elif outcome == "loss":
            rows = [row for row in rows if safe_float(row["profit"]) < 0]

        if lot_size:
            target_lot = safe_float(lot_size, -1.0)
            rows = [row for row in rows if math.isclose(safe_float(row["volume"]), target_lot, rel_tol=0.0, abs_tol=0.000001)]
        if normalized_symbols:
            rows = [row for row in rows if str(row.get("symbol") or "").strip().upper() in normalized_symbols]

        rows = apply_special_filter(rows, special_filter)
        rows.sort(key=lambda row: row["close_time"] or row["open_time"], reverse=True)
        grouped_days = build_grouped_days(rows)
        total_profit = sum(safe_float(row["profit"]) for row in rows)
        imported_count = DB.save_mt5_history_rows(
            rows,
            account_login=self._current_account_login(),
            account_server=self._current_account_server(),
        )
        current_scope = []
        if self._current_account_login() is not None:
            current_scope = [(self._current_account_login(), self._current_account_server())]
        return {
            "connected": self.connected,
            "connection_error": self.connection_error,
            "days": grouped_days,
            "totals": {
                "total_trades": len(rows),
                "wins": sum(1 for row in rows if safe_float(row["profit"]) > 0),
                "losses": sum(1 for row in rows if safe_float(row["profit"]) < 0),
                "total_profit": total_profit,
            },
            "lot_sizes": sorted({safe_float(row["volume"]) for row in rows}),
            "symbols": available_symbols,
            "summary": DB.mt5_history_performance_summary(account_scopes=current_scope, symbols=normalized_symbols),
            "insights": build_journal_insights(
                DB.mt5_history_insight_rows(account_scopes=current_scope, symbols=normalized_symbols)
            ),
            "source": "mt5",
            "saved_to_sqlite": True,
            "saved_count": imported_count,
        }

    def import_mt5_history(self) -> dict[str, Any]:
        payload = self.history_journal("all", "all", "", None, "all", "")
        return {
            "connected": payload.get("connected", False),
            "connection_error": payload.get("connection_error", ""),
            "saved_to_sqlite": payload.get("saved_to_sqlite", False),
            "saved_count": payload.get("saved_count", 0),
            "total_trades": payload.get("totals", {}).get("total_trades", 0),
        }

    def _journal_profile_scopes(self, aliases: list[str]) -> list[tuple[int | None, str]]:
        scopes: list[tuple[int | None, str]] = []
        seen: set[str] = set()
        current_alias = str(self.selected_profile_alias or "").strip().lower()
        current_login = self._current_account_login()
        current_server = self._current_account_server()
        current_terminal_path = str((self.connection_profile or {}).get("terminal_path", "")).strip().lower()
        for alias in aliases:
            profile = DB.find_account_profile(alias)
            if not profile:
                continue
            login = normalize_account_login(profile.get("login"))
            server = normalize_account_server(profile.get("server"))
            profile_terminal_path = str(profile.get("terminal_path", "")).strip().lower()
            alias_key = str(alias or "").strip().lower()
            if login is None and current_login is not None:
                if (current_alias and alias_key == current_alias) or (
                    profile_terminal_path and current_terminal_path and profile_terminal_path == current_terminal_path
                ):
                    login = current_login
                    if not server:
                        server = current_server
            if login is None:
                continue
            key = account_scope_key(login, server)
            if key in seen:
                continue
            seen.add(key)
            scopes.append((login, server))
        return scopes

    def cached_history_journal(
        self,
        range_key: str,
        outcome: str,
        lot_size: str,
        symbols: list[str] | None,
        special_filter: str,
        exact_date: str,
        profile_aliases: list[str],
    ) -> dict[str, Any]:
        scopes = self._journal_profile_scopes(profile_aliases)
        payload = DB.mt5_history_journal(
            range_key=range_key,
            outcome=outcome,
            lot_size=lot_size,
            symbols=symbols,
            special_filter=special_filter,
            exact_date=exact_date,
            account_scopes=scopes,
        )
        payload.update(
            {
                "connected": self.connected,
                "connection_error": self.connection_error,
                "profile_aliases": profile_aliases,
            }
        )
        return payload

    def _resolve_journal_scope(self, source_mode: str, profile_aliases: list[str] | None = None) -> tuple[str, str]:
        aliases = [item.strip() for item in (profile_aliases or []) if item and item.strip()]
        if source_mode == "profiles" and aliases:
            scopes = self._journal_profile_scopes(aliases)
            scope_key = "profiles::" + "|".join(sorted(account_scope_key(login, server) for login, server in scopes))
            return scope_key, ", ".join(aliases)
        login = self._current_account_login()
        server = self._current_account_server()
        return account_scope_key(login, server), (self.selected_profile_alias or "Current Connected Account")

    def _build_journal_auto_review(self, exact_date: str, journal_payload: dict[str, Any], deposit_payload: dict[str, Any]) -> dict[str, Any]:
        day_row = journal_payload.get("days", [{}])[0] if journal_payload.get("days") else {}
        rows = list(day_row.get("rows") or [])
        total_profit = safe_float(journal_payload.get("totals", {}).get("total_profit"))
        wins = int(journal_payload.get("totals", {}).get("wins") or 0)
        losses = int(journal_payload.get("totals", {}).get("losses") or 0)
        trade_count = int(journal_payload.get("totals", {}).get("total_trades") or 0)
        deposits_total = safe_float(deposit_payload.get("totals", {}).get("usd"))

        symbol_totals: dict[str, float] = {}
        side_totals: dict[str, float] = {}
        setup_totals: dict[str, int] = {}
        for row in rows:
            symbol = str(row.get("symbol", "") or "Unknown").upper()
            side = normalize_side(str(row.get("side", "") or ""))
            reason = str(row.get("reason", "") or "General")
            symbol_totals[symbol] = symbol_totals.get(symbol, 0.0) + safe_float(row.get("profit"))
            side_totals[side] = side_totals.get(side, 0.0) + safe_float(row.get("profit"))
            setup_totals[reason] = setup_totals.get(reason, 0) + 1

        best_symbol = max(symbol_totals.items(), key=lambda item: item[1])[0] if symbol_totals else "No trades"
        best_side = max(side_totals.items(), key=lambda item: item[1])[0] if side_totals else "No side edge"
        top_reason = max(setup_totals.items(), key=lambda item: item[1])[0] if setup_totals else "No repeat setup"
        biggest_winner = max((safe_float(row.get("profit")) for row in rows), default=0.0)
        biggest_loser = min((safe_float(row.get("profit")) for row in rows), default=0.0)

        cards = [
            {
                "title": "Daily Result",
                "value": f"{'+' if total_profit > 0 else ''}{total_profit:.2f}",
                "note": f"{trade_count} trade(s) on {exact_date or 'this day'}",
                "tone": "positive" if total_profit > 0 else "negative" if total_profit < 0 else "neutral",
            },
            {
                "title": "Best Symbol",
                "value": best_symbol,
                "note": "Strongest contributor for the selected day",
                "tone": "neutral",
            },
            {
                "title": "Best Direction",
                "value": best_side or "Unknown",
                "note": "Direction with the better result that day",
                "tone": "neutral",
            },
        ]

        ideas: list[dict[str, str]] = []
        if trade_count == 0:
            ideas.append({"title": "No Trades Logged", "detail": "Use this journal space to document why you stood aside. Knowing when not to trade is part of the pattern."})
        else:
            ideas.append({"title": "Most Repeated Setup", "detail": f"The most repeated closing reason/setup tag was '{top_reason}'. Check whether that is a real edge or just your most common habit."})
            if wins > losses:
                ideas.append({"title": "Positive Session Read", "detail": f"You finished {wins}/{losses} on wins versus losses. Review which entries matched your plan and repeat those conditions."})
            elif losses > wins:
                ideas.append({"title": "Loss Pressure", "detail": f"Losses outnumbered wins {losses} to {wins}. Recheck whether you forced entries, ignored bias, or traded inside messy structure."})
            if deposits_total > 0:
                ideas.append({"title": "Deposit Context", "detail": f"You added {deposits_total:.2f} in deposits on this day. Separate trading performance from account funding when reviewing confidence and risk."})
            if biggest_loser < 0 and abs(biggest_loser) > max(1.5 * max(biggest_winner, 0.01), 5):
                ideas.append({"title": "Outlier Loss", "detail": f"Your biggest loss ({biggest_loser:.2f}) was much larger than your biggest win ({biggest_winner:.2f}). That usually points to weak stop discipline or late exits."})
            if total_profit > 0:
                ideas.append({"title": "Protect The Good Day", "detail": "Write down exactly what confirmed your best trade today. The fastest way to improve is to repeat what already worked under the same conditions."})
            else:
                ideas.append({"title": "Repair Plan", "detail": "Use the manual journal fields to name the exact mistake pattern from today: early entry, bias mismatch, overtrading, or poor risk control."})

        return {"cards": cards, "ideas": ideas}

    def trader_journal_entry(self, *, exact_date: str, source_mode: str = "current", profile_aliases: list[str] | None = None) -> dict[str, Any]:
        scope_key, scope_label = self._resolve_journal_scope(source_mode, profile_aliases)
        if not exact_date:
            return {
                "ok": True,
                "date": "",
                "scope_key": scope_key,
                "scope_label": scope_label,
                "entry": None,
                "auto_review": {"cards": [], "ideas": []},
            }
        aliases = [item.strip() for item in (profile_aliases or []) if item and item.strip()]
        if source_mode == "profiles" and aliases:
            journal_payload = self.cached_history_journal("all", "all", "", None, "all", exact_date, aliases)
            deposit_payload = self.deposit_history_for_profiles(range_key="all", profile_aliases=aliases, exact_date=exact_date)
        else:
            journal_payload = self.history_journal("all", "all", "", None, "all", exact_date)
            deposit_payload = self.deposit_history(range_key="all", exact_date=exact_date)
        return {
            "ok": True,
            "date": exact_date,
            "scope_key": scope_key,
            "scope_label": scope_label,
            "entry": DB.get_trader_journal_entry(exact_date, scope_key),
            "auto_review": self._build_journal_auto_review(exact_date, journal_payload, deposit_payload),
        }

    def journal_day_summary(self, *, exact_date: str, source_mode: str = "current", profile_aliases: list[str] | None = None) -> dict[str, Any]:
        if not exact_date:
            return {
                "connected": self.connected,
                "connection_error": self.connection_error,
                "date": "",
                "starting_balance": None,
                "deposits_total": 0.0,
                "deposits_count": 0,
                "trade_profit": 0.0,
                "net_change_ex_deposits": 0.0,
                "ending_balance_estimate": None,
                "trade_count": 0,
                "wins": 0,
                "losses": 0,
            }

        aliases = [item.strip() for item in (profile_aliases or []) if item and item.strip()]
        if source_mode == "profiles" and aliases:
            journal_payload = self.cached_history_journal("all", "all", "", None, "all", exact_date, aliases)
            deposit_payload = self.deposit_history_for_profiles(range_key="all", profile_aliases=aliases, exact_date=exact_date)
            scope_label = ", ".join(aliases)
        else:
            journal_payload = self.history_journal("all", "all", "", None, "all", exact_date)
            deposit_payload = self.deposit_history(range_key="all", exact_date=exact_date)
            scope_label = self.selected_profile_alias or "Current Connected Account"

        day_row = journal_payload.get("days", [{}])[0] if journal_payload.get("days") else {}
        starting_balance = day_row.get("start_balance")
        trade_profit = safe_float(journal_payload.get("totals", {}).get("total_profit"))
        deposits_total = safe_float(deposit_payload.get("totals", {}).get("usd"))
        ending_balance_estimate = None
        if starting_balance is not None:
            ending_balance_estimate = safe_float(starting_balance) + deposits_total + trade_profit

        return {
            "connected": self.connected,
            "connection_error": self.connection_error,
            "date": exact_date,
            "scope_label": scope_label,
            "starting_balance": starting_balance,
            "deposits_total": deposits_total,
            "deposits_count": int(deposit_payload.get("totals", {}).get("count") or 0),
            "trade_profit": trade_profit,
            "net_change_ex_deposits": trade_profit,
            "ending_balance_estimate": ending_balance_estimate,
            "trade_count": int(journal_payload.get("totals", {}).get("total_trades") or 0),
            "wins": int(journal_payload.get("totals", {}).get("wins") or 0),
            "losses": int(journal_payload.get("totals", {}).get("losses") or 0),
            "warnings": deposit_payload.get("warnings", []),
        }

    def market_analysis(self, symbol: str = "XAUUSD", timeframe: str = "H1") -> dict[str, Any]:
        def average(values: list[float]) -> float:
            return sum(values) / len(values) if values else 0.0

        def ema(values: list[float], period: int) -> float:
            if not values:
                return 0.0
            alpha = 2.0 / (max(period, 1) + 1.0)
            result = values[0]
            for value in values[1:]:
                result = alpha * value + (1.0 - alpha) * result
            return result

        def atr_from_candles(candles_input: list[dict[str, Any]], period: int = 14) -> float:
            if len(candles_input) < period + 1:
                return 0.0
            ranges: list[float] = []
            for index in range(1, len(candles_input)):
                current = candles_input[index]
                previous_close = safe_float(candles_input[index - 1]["close"])
                high = safe_float(current["high"])
                low = safe_float(current["low"])
                ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
            return average(ranges[-period:])

        def adx_from(candles_input: list[dict[str, Any]], period: int = 14) -> dict[str, float]:
            if len(candles_input) < period + 2:
                return {"adx": 0.0, "plus_di": 0.0, "minus_di": 0.0}

            true_ranges: list[float] = []
            plus_dm_values: list[float] = []
            minus_dm_values: list[float] = []
            for index in range(1, len(candles_input)):
                current = candles_input[index]
                previous = candles_input[index - 1]
                high = safe_float(current["high"])
                low = safe_float(current["low"])
                prev_high = safe_float(previous["high"])
                prev_low = safe_float(previous["low"])
                prev_close = safe_float(previous["close"])
                up_move = high - prev_high
                down_move = prev_low - low
                plus_dm_values.append(up_move if up_move > down_move and up_move > 0 else 0.0)
                minus_dm_values.append(down_move if down_move > up_move and down_move > 0 else 0.0)
                true_ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))

            tr_smoothed = average(true_ranges[:period]) * period
            plus_smoothed = average(plus_dm_values[:period]) * period
            minus_smoothed = average(minus_dm_values[:period]) * period
            dx_values: list[float] = []
            for index in range(period, len(true_ranges)):
                tr_smoothed = tr_smoothed - (tr_smoothed / period) + true_ranges[index]
                plus_smoothed = plus_smoothed - (plus_smoothed / period) + plus_dm_values[index]
                minus_smoothed = minus_smoothed - (minus_smoothed / period) + minus_dm_values[index]
                plus_di = 100.0 * (plus_smoothed / tr_smoothed) if tr_smoothed else 0.0
                minus_di = 100.0 * (minus_smoothed / tr_smoothed) if tr_smoothed else 0.0
                denominator = plus_di + minus_di
                dx_values.append((100.0 * abs(plus_di - minus_di) / denominator) if denominator else 0.0)

            adx_value = average(dx_values[-period:]) if dx_values else 0.0
            plus_di = 100.0 * (plus_smoothed / tr_smoothed) if tr_smoothed else 0.0
            minus_di = 100.0 * (minus_smoothed / tr_smoothed) if tr_smoothed else 0.0
            return {"adx": adx_value, "plus_di": plus_di, "minus_di": minus_di}

        def normalize_volume_down(volume: float, min_volume: float, max_volume: float, step: float) -> float:
            step = step or min_volume or 0.01
            min_volume = min_volume or 0.01
            max_volume = max_volume or 100.0
            if volume < min_volume:
                return 0.0
            volume = min(volume, max_volume)
            steps = math.floor((volume - min_volume) / step + 1e-7)
            normalized = min_volume + steps * step
            digits = max(0, len(f"{step:.8f}".rstrip("0").split(".")[1]) if "." in f"{step:.8f}".rstrip("0") else 0)
            return round(max(min_volume, min(normalized, max_volume)), digits)

        def classify_session(hour: int) -> str:
            if 0 <= hour <= 6:
                return "Asian"
            if 7 <= hour <= 11:
                return "London"
            if 12 <= hour <= 17:
                return "New York"
            return "Off Hours"

        def is_in_range(hour: int, start_hour: int, end_hour: int) -> bool:
            return start_hour <= hour <= end_hour if start_hour <= end_hour else hour >= start_hour or hour <= end_hour

        def build_gate(label: str, passed: bool, detail: str, blocking: bool = True) -> dict[str, Any]:
            tone = "bullish" if passed else ("bearish" if blocking else "neutral")
            return {"label": label, "passed": passed, "detail": detail, "blocking": blocking, "tone": tone}

        def recent_liquidity_levels(candles_input: list[dict[str, Any]], lookback: int, tolerance: float) -> list[dict[str, Any]]:
            levels: list[dict[str, Any]] = []
            start_index = 2
            end_index = max(2, len(candles_input) - 2)
            for index in range(start_index, end_index):
                current = candles_input[index]
                high = safe_float(current["high"])
                low = safe_float(current["low"])
                if (
                    high > safe_float(candles_input[index - 1]["high"])
                    and high > safe_float(candles_input[index - 2]["high"])
                    and high > safe_float(candles_input[index + 1]["high"])
                    and high > safe_float(candles_input[index + 2]["high"])
                ):
                    levels.append({
                        "price": round(high, 2),
                        "kind": "high",
                        "time": current["time"],
                        "strength": sum(
                            1
                            for item in candles_input[max(0, index - 25): index + 25]
                            if abs(safe_float(item["high"]) - high) <= tolerance or abs(safe_float(item["low"]) - high) <= tolerance
                        ),
                    })
                if (
                    low < safe_float(candles_input[index - 1]["low"])
                    and low < safe_float(candles_input[index - 2]["low"])
                    and low < safe_float(candles_input[index + 1]["low"])
                    and low < safe_float(candles_input[index + 2]["low"])
                ):
                    levels.append({
                        "price": round(low, 2),
                        "kind": "low",
                        "time": current["time"],
                        "strength": sum(
                            1
                            for item in candles_input[max(0, index - 25): index + 25]
                            if abs(safe_float(item["high"]) - low) <= tolerance or abs(safe_float(item["low"]) - low) <= tolerance
                        ),
                    })
            levels.sort(key=lambda item: item["time"], reverse=True)
            return levels[:6]

        def recent_fvgs(candles_input: list[dict[str, Any]], atr_value: float) -> list[dict[str, Any]]:
            minimum_gap = atr_value * 0.5
            fvgs: list[dict[str, Any]] = []
            for index in range(2, len(candles_input)):
                candle_1 = candles_input[index - 2]
                candle_3 = candles_input[index]
                bullish_gap = safe_float(candle_3["low"]) - safe_float(candle_1["high"])
                bearish_gap = safe_float(candle_1["low"]) - safe_float(candle_3["high"])
                if bullish_gap >= minimum_gap:
                    fvgs.append({
                        "kind": "bullish",
                        "low": round(safe_float(candle_1["high"]), 2),
                        "high": round(safe_float(candle_3["low"]), 2),
                        "size": round(bullish_gap, 2),
                        "time": candle_3["time"],
                    })
                if bearish_gap >= minimum_gap:
                    fvgs.append({
                        "kind": "bearish",
                        "low": round(safe_float(candle_3["high"]), 2),
                        "high": round(safe_float(candle_1["low"]), 2),
                        "size": round(bearish_gap, 2),
                        "time": candle_3["time"],
                    })
            fvgs.sort(key=lambda item: item["time"], reverse=True)
            return fvgs[:5]

        def recent_order_blocks(candles_input: list[dict[str, Any]], atr_value: float) -> list[dict[str, Any]]:
            order_blocks: list[dict[str, Any]] = []
            threshold = atr_value * 0.8
            for index in range(1, len(candles_input) - 1):
                current = candles_input[index]
                next_candle = candles_input[index + 1]
                body = abs(safe_float(next_candle["close"]) - safe_float(next_candle["open"]))
                if body < threshold:
                    continue
                current_open = safe_float(current["open"])
                current_close = safe_float(current["close"])
                next_open = safe_float(next_candle["open"])
                next_close = safe_float(next_candle["close"])
                if current_close < current_open and next_close > next_open:
                    order_blocks.append({
                        "kind": "bullish",
                        "low": round(min(current_open, current_close), 2),
                        "high": round(max(current_open, current_close), 2),
                        "time": current["time"],
                    })
                elif current_close > current_open and next_close < next_open:
                    order_blocks.append({
                        "kind": "bearish",
                        "low": round(min(current_open, current_close), 2),
                        "high": round(max(current_open, current_close), 2),
                        "time": current["time"],
                    })
            order_blocks.sort(key=lambda item: item["time"], reverse=True)
            return order_blocks[:5]

        def swing_structure_summary(levels: list[dict[str, Any]]) -> dict[str, Any]:
            highs = sorted((item for item in levels if item.get("kind") == "high"), key=lambda item: item.get("time", ""))
            lows = sorted((item for item in levels if item.get("kind") == "low"), key=lambda item: item.get("time", ""))
            if len(highs) < 2 or len(lows) < 2:
                return {
                    "direction": "neutral",
                    "summary": "Not enough recent swing highs and lows yet to confirm a clean HH/HL or LH/LL sequence.",
                }
            previous_high = safe_float(highs[-2].get("price"))
            latest_high = safe_float(highs[-1].get("price"))
            previous_low = safe_float(lows[-2].get("price"))
            latest_low = safe_float(lows[-1].get("price"))
            if latest_high > previous_high and latest_low > previous_low:
                return {
                    "direction": "bullish",
                    "summary": f"Recent swings are printing higher highs and higher lows ({previous_high:.2f} -> {latest_high:.2f}, {previous_low:.2f} -> {latest_low:.2f}).",
                }
            if latest_high < previous_high and latest_low < previous_low:
                return {
                    "direction": "bearish",
                    "summary": f"Recent swings are printing lower highs and lower lows ({previous_high:.2f} -> {latest_high:.2f}, {previous_low:.2f} -> {latest_low:.2f}).",
                }
            return {
                "direction": "neutral",
                "summary": f"Recent swings are mixed. Highs moved {previous_high:.2f} -> {latest_high:.2f} while lows moved {previous_low:.2f} -> {latest_low:.2f}.",
            }

        timeframe_key = (timeframe or "H1").strip().upper()
        timeframe_map = {
            "M1": ("TIMEFRAME_M1", "M1"),
            "M5": ("TIMEFRAME_M5", "M5"),
            "M15": ("TIMEFRAME_M15", "M15"),
            "M30": ("TIMEFRAME_M30", "M30"),
            "H1": ("TIMEFRAME_H1", "H1"),
            "H4": ("TIMEFRAME_H4", "H4"),
            "D1": ("TIMEFRAME_D1", "D1"),
        }
        timeframe_attr, timeframe_label = timeframe_map.get(timeframe_key, ("TIMEFRAME_H1", "H1"))
        empty_payload = {
            "connected": False,
            "connection_error": self.connection_error or "Not connected.",
            "symbol": symbol,
            "timeframe": timeframe_label,
            "candles": [],
            "zones": [],
            "confluences": [],
            "bias": "neutral",
            "current_price": 0.0,
            "prediction": {"direction": "neutral", "summary": self.connection_error or "Not connected.", "score": 0},
            "trade_advice": {"advisable": False, "bias": "wait", "tone": "neutral", "summary": self.connection_error or "Not connected."},
            "gate_checks": [],
            "day_state": {},
            "market_snapshot": {},
            "bias_model": {},
            "execution_plan": {},
            "risk_plan": {},
            "management_plan": {},
            "structure_context": {},
            "active_position": None,
            "prompt_state": {"state": "wait", "tone": "neutral", "summary": self.connection_error or "Not connected."},
            "market_sessions": market_sessions_snapshot(),
        }
        if not self._initialize():
            return empty_payload
        if mt5 is None:
            empty_payload["connection_error"] = "MetaTrader5 package is not installed."
            empty_payload["prediction"]["summary"] = empty_payload["connection_error"]
            empty_payload["trade_advice"]["summary"] = empty_payload["connection_error"]
            empty_payload["prompt_state"]["summary"] = empty_payload["connection_error"]
            return empty_payload

        requested_symbol = symbol.strip() or self.primary_symbol or "XAUUSD"
        target_symbol, symbol_info, resolve_error = self._resolve_chart_symbol(requested_symbol)
        if symbol_info is None:
            empty_payload["connected"] = self.connected
            empty_payload["symbol"] = target_symbol
            empty_payload["connection_error"] = resolve_error or f"Symbol {target_symbol} is not available in this terminal."
            empty_payload["prediction"]["summary"] = empty_payload["connection_error"]
            empty_payload["trade_advice"]["summary"] = empty_payload["connection_error"]
            empty_payload["prompt_state"]["summary"] = empty_payload["connection_error"]
            return empty_payload

        if not getattr(symbol_info, "visible", True):
            mt5.symbol_select(target_symbol, True)

        rates = mt5.copy_rates_from_pos(
            target_symbol,
            getattr(mt5, timeframe_attr, getattr(mt5, "TIMEFRAME_H1", 16385)),
            0,
            420,
        )
        m5_rates = mt5.copy_rates_from_pos(target_symbol, getattr(mt5, "TIMEFRAME_M5", 5), 0, 220)
        h4_rates = mt5.copy_rates_from_pos(target_symbol, getattr(mt5, "TIMEFRAME_H4", 16388), 0, 260)
        h1_rates = mt5.copy_rates_from_pos(target_symbol, getattr(mt5, "TIMEFRAME_H1", 16385), 0, 120)
        if rates is None or len(rates) < 80 or m5_rates is None or len(m5_rates) < 80 or h4_rates is None or len(h4_rates) < 210:
            empty_payload["connected"] = self.connected
            empty_payload["symbol"] = target_symbol
            empty_payload["connection_error"] = f"Could not load bot-style analysis candles for {target_symbol}."
            empty_payload["prediction"]["summary"] = empty_payload["connection_error"]
            empty_payload["trade_advice"]["summary"] = empty_payload["connection_error"]
            empty_payload["prompt_state"]["summary"] = empty_payload["connection_error"]
            return empty_payload

        candles = [
            {
                "time": datetime.fromtimestamp(int(rate["time"]), UTC).isoformat(),
                "open": safe_float(rate["open"]),
                "high": safe_float(rate["high"]),
                "low": safe_float(rate["low"]),
                "close": safe_float(rate["close"]),
                "tick_volume": int(rate["tick_volume"]),
            }
            for rate in rates
        ]
        m5_candles = [
            {
                "time": datetime.fromtimestamp(int(rate["time"]), UTC).isoformat(),
                "open": safe_float(rate["open"]),
                "high": safe_float(rate["high"]),
                "low": safe_float(rate["low"]),
                "close": safe_float(rate["close"]),
                "tick_volume": int(rate["tick_volume"]),
            }
            for rate in m5_rates
        ]
        h4_closes = [safe_float(rate["close"]) for rate in h4_rates]
        h1_closes = [safe_float(rate["close"]) for rate in h1_rates] if h1_rates is not None else []

        point = safe_float(getattr(symbol_info, "point", 0.01), 0.01) or 0.01
        digits = int(getattr(symbol_info, "digits", 2))
        bid = safe_float(getattr(symbol_info, "bid", 0.0))
        ask = safe_float(getattr(symbol_info, "ask", 0.0))
        current_price = bid or ask or safe_float(candles[-1]["close"])
        spread_price = max(ask - bid, 0.0) if ask and bid else 0.0
        spread_points = spread_price / point if point else 0.0
        atr_value = atr_from_candles(m5_candles, 14)
        atr_points = atr_value / point if point else 0.0

        h4_ema200 = ema(h4_closes[-220:], 200)
        h1_ema34 = ema(h1_closes[-60:], 34) if h1_closes else 0.0
        local_closes = [safe_float(item["close"]) for item in candles]
        local_ema34 = ema(local_closes[-60:], 34) if local_closes else 0.0
        bias = "bullish" if current_price > h4_ema200 else "bearish" if current_price < h4_ema200 else "neutral"
        local_bias = "bullish" if current_price > local_ema34 else "bearish" if current_price < local_ema34 else "neutral"
        if bias in {"bullish", "bearish"} and local_bias in {"bullish", "bearish"}:
            bias_alignment = "aligned" if bias == local_bias else "pullback"
        else:
            bias_alignment = "mixed"
        side = "buy" if bias == "bullish" else "sell" if bias == "bearish" else "wait"

        now_utc = datetime.now(UTC)
        current_hour = now_utc.hour
        session_name = classify_session(current_hour)
        in_asian = is_in_range(current_hour, 0, 6)
        in_london = is_in_range(current_hour, 7, 11)
        in_new_york = is_in_range(current_hour, 13, 17)
        session_allowed = in_asian or in_london or in_new_york
        kill_zone_active = is_in_range(current_hour, 8, 9) or is_in_range(current_hour, 15, 16)

        account_info = mt5.account_info()
        balance = safe_float(getattr(account_info, "balance", 0.0)) if account_info else 0.0
        equity = safe_float(getattr(account_info, "equity", balance)) if account_info else balance
        free_margin = safe_float(getattr(account_info, "margin_free", 0.0)) if account_info else 0.0
        positions_all = list(mt5.positions_get() or [])
        symbol_positions = [position for position in positions_all if str(getattr(position, "symbol", "")).upper() == target_symbol.upper()]
        open_positions_total = len(positions_all)

        today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        today_deals = list(mt5.history_deals_get(today_start, now_utc) or [])
        today_entries = [
            deal for deal in today_deals
            if getattr(deal, "entry", None) == getattr(mt5, "DEAL_ENTRY_IN", 0)
        ]
        today_exits = [
            deal for deal in today_deals
            if getattr(deal, "entry", None) in {getattr(mt5, "DEAL_ENTRY_OUT", 1), getattr(mt5, "DEAL_ENTRY_INOUT", 3)}
        ]
        realized_daily_pl = sum(
            safe_float(getattr(deal, "profit", 0.0))
            + safe_float(getattr(deal, "swap", 0.0))
            + safe_float(getattr(deal, "commission", 0.0))
            for deal in today_exits
        )
        day_start_balance = balance - realized_daily_pl
        daily_pl_pct = (realized_daily_pl / day_start_balance * 100.0) if day_start_balance else 0.0
        today_trade_count = len(today_entries)

        liquidity_levels = recent_liquidity_levels(m5_candles[-120:], 50, atr_value * 0.1 if atr_value else point * 20)
        fvgs = recent_fvgs(m5_candles[-80:], atr_value or point * 120)
        order_blocks = recent_order_blocks(m5_candles[-80:], atr_value or point * 120)
        swing_structure = swing_structure_summary(recent_liquidity_levels(candles[-160:], 50, atr_value * 0.1 if atr_value else point * 20))

        recent_window = candles[-80:]
        range_high = max(safe_float(item["high"]) for item in recent_window)
        range_low = min(safe_float(item["low"]) for item in recent_window)
        swing_high = max(safe_float(item["high"]) for item in candles[-24:])
        swing_low = min(safe_float(item["low"]) for item in candles[-24:])
        midline = (range_high + range_low) / 2.0
        fib_anchor_high = max(safe_float(item["high"]) for item in recent_window[-40:])
        fib_anchor_low = min(safe_float(item["low"]) for item in recent_window[-40:])
        fib_range = max(fib_anchor_high - fib_anchor_low, point * 20)
        fib_382 = fib_anchor_high - fib_range * 0.382
        fib_500 = fib_anchor_high - fib_range * 0.5
        fib_618 = fib_anchor_high - fib_range * 0.618

        def session_range_for_day(candles_input: list[dict[str, Any]], start_hour: int, end_hour: int) -> dict[str, Any] | None:
            session_rows: list[dict[str, Any]] = []
            for item in candles_input:
                try:
                    ts = datetime.fromisoformat(str(item.get("time") or ""))
                except Exception:
                    continue
                if ts.date() != now_utc.date():
                    continue
                if start_hour <= ts.hour <= end_hour:
                    session_rows.append(item)
            if not session_rows:
                return None
            return {
                "high": round(max(safe_float(row["high"]) for row in session_rows), 2),
                "low": round(min(safe_float(row["low"]) for row in session_rows), 2),
                "start_time": str(session_rows[0].get("time") or ""),
                "end_time": str(session_rows[-1].get("time") or ""),
            }

        latest_candle_time = str(candles[-1].get("time") or "")
        previous_day_level = self._active_period_level_for_time(self._previous_day_levels(target_symbol, point), latest_candle_time)
        previous_week_level = self._active_period_level_for_time(self._previous_week_levels(target_symbol, point), latest_candle_time)
        previous_month_level = self._active_period_level_for_time(self._previous_month_levels(target_symbol, point), latest_candle_time)
        asian_session_range = session_range_for_day(m5_candles, 0, 6)
        london_session_range = session_range_for_day(m5_candles, 7, 12)

        key_levels: list[dict[str, Any]] = []
        if previous_day_level:
            key_levels.extend(
                [
                    {"label": "PDH", "code": "PDH", "price": round(safe_float(previous_day_level.get("previous_high")), 2), "kind": "resistance", "group": "previous_day"},
                    {"label": "PDL", "code": "PDL", "price": round(safe_float(previous_day_level.get("previous_low")), 2), "kind": "support", "group": "previous_day"},
                ]
            )
        if previous_week_level:
            key_levels.extend(
                [
                    {"label": "PWH", "code": "PWH", "price": round(safe_float(previous_week_level.get("previous_high")), 2), "kind": "resistance", "group": "weekly"},
                    {"label": "PWL", "code": "PWL", "price": round(safe_float(previous_week_level.get("previous_low")), 2), "kind": "support", "group": "weekly"},
                ]
            )
        if previous_month_level:
            key_levels.extend(
                [
                    {"label": "PMH", "code": "PMH", "price": round(safe_float(previous_month_level.get("previous_high")), 2), "kind": "resistance", "group": "monthly"},
                    {"label": "PML", "code": "PML", "price": round(safe_float(previous_month_level.get("previous_low")), 2), "kind": "support", "group": "monthly"},
                ]
            )
        if asian_session_range:
            key_levels.extend(
                [
                    {"label": "Asian High", "code": "ASH", "price": round(safe_float(asian_session_range.get("high")), 2), "kind": "resistance", "group": "asian"},
                    {"label": "Asian Low", "code": "ASL", "price": round(safe_float(asian_session_range.get("low")), 2), "kind": "support", "group": "asian"},
                ]
            )
        if london_session_range:
            key_levels.extend(
                [
                    {"label": "London High", "code": "LDNH", "price": round(safe_float(london_session_range.get("high")), 2), "kind": "resistance", "group": "london"},
                    {"label": "London Low", "code": "LDNL", "price": round(safe_float(london_session_range.get("low")), 2), "kind": "support", "group": "london"},
                ]
            )

        recent_local_high = max(safe_float(item["high"]) for item in candles[-13:-1]) if len(candles) >= 14 else swing_high
        recent_local_low = min(safe_float(item["low"]) for item in candles[-13:-1]) if len(candles) >= 14 else swing_low
        last_close = safe_float(candles[-1]["close"]) if candles else current_price
        previous_local_ema34 = ema(local_closes[-61:-1], 34) if len(local_closes) >= 35 else local_ema34
        local_ema_slope = local_ema34 - previous_local_ema34
        bullish_breakout = last_close > recent_local_high
        bearish_breakout = last_close < recent_local_low
        continuation_side = local_bias if local_bias in {"bullish", "bearish"} else bias
        continuation_score = 50
        continuation_factors: list[str] = []

        if bias_alignment == "aligned":
            continuation_score += 20
            continuation_factors.append("Macro and local bias are aligned.")
        elif bias_alignment == "pullback":
            continuation_score -= 20
            continuation_factors.append("Local move is currently counter-trend versus the macro bias.")
        else:
            continuation_factors.append("Bias is mixed or neutral, so continuation confidence is softer.")

        if swing_structure.get("direction") == continuation_side:
            continuation_score += 15
            continuation_factors.append("Recent swing structure supports the local direction.")
        elif swing_structure.get("direction") in {"bullish", "bearish"}:
            continuation_score -= 10
            continuation_factors.append("Recent swing structure disagrees with the local direction.")

        if continuation_side == "bullish":
            if bullish_breakout:
                continuation_score += 15
                continuation_factors.append("Price is breaking above the recent local high.")
            if local_ema_slope > 0:
                continuation_score += 10
                continuation_factors.append("The selected-timeframe EMA34 is sloping upward.")
            else:
                continuation_score -= 5
            if current_price > h1_ema34:
                continuation_score += 10
                continuation_factors.append("Price is also above the H1 EMA34, which supports follow-through.")
        elif continuation_side == "bearish":
            if bearish_breakout:
                continuation_score += 15
                continuation_factors.append("Price is breaking below the recent local low.")
            if local_ema_slope < 0:
                continuation_score += 10
                continuation_factors.append("The selected-timeframe EMA34 is sloping downward.")
            else:
                continuation_score -= 5
            if current_price < h1_ema34:
                continuation_score += 10
                continuation_factors.append("Price is also below the H1 EMA34, which supports follow-through.")

        continuation_score = max(5, min(95, continuation_score))
        if bias_alignment == "pullback" and continuation_score < 60:
            continuation_label = "Likely pullback"
        elif continuation_score >= 75:
            continuation_label = "Continuation confirmed"
        elif continuation_score >= 60:
            continuation_label = "Possible continuation building"
        else:
            continuation_label = "Mixed / fragile"

        risk_percent = 1.0
        max_daily_risk_percent = 5.0
        max_daily_profit_percent = 8.0
        max_margin_usage_percent = 80.0
        max_positions = 2
        max_daily_trades = 10
        min_atr_points = 100.0
        max_spread_points = 50.0
        atr_sl_multiplier = 2.0
        atr_tp_multiplier = 3.0
        allow_min_lot = True
        be_trigger_atr = 1.0
        trail_start_atr = 1.5
        trail_step_atr = 0.5

        session_gate = build_gate("Trading session", session_allowed, f"{session_name} window {'is active' if session_allowed else 'is outside the bot trading windows 00-06, 07-11, 13-17 UTC.'}")
        spread_gate = build_gate(
            "Spread",
            spread_points <= max_spread_points,
            f"{spread_points:.1f} pts right now. Reference ceiling: {max_spread_points:.1f} pts.",
            blocking=False,
        )
        atr_gate = build_gate("ATR filter", atr_points >= min_atr_points, f"{atr_points:.1f} pts against a minimum of {min_atr_points:.1f} pts.")
        position_gate = build_gate("Open-position cap", open_positions_total < max_positions, f"{open_positions_total} open position(s) against a max of {max_positions}.")
        trade_cap_gate = build_gate("Daily trade cap", today_trade_count < max_daily_trades, f"{today_trade_count} entry deal(s) today against a max of {max_daily_trades}.")
        daily_loss_gate = build_gate("Daily drawdown cap", daily_pl_pct > -max_daily_risk_percent, f"Realized daily P/L is {daily_pl_pct:.2f}% versus a floor of -{max_daily_risk_percent:.2f}%.")
        daily_profit_gate = build_gate("Daily profit cap", daily_pl_pct < max_daily_profit_percent, f"Realized daily P/L is {daily_pl_pct:.2f}% versus a cap of {max_daily_profit_percent:.2f}%.")
        kill_zone_note = build_gate("Kill zone", kill_zone_active, f"{'Inside' if kill_zone_active else 'Outside'} the London/NY kill zone windows.", blocking=False)
        gate_checks = [session_gate, spread_gate, atr_gate, position_gate, trade_cap_gate, daily_loss_gate, daily_profit_gate, kill_zone_note]
        blocking_failures = [gate for gate in gate_checks if gate["blocking"] and not gate["passed"]]
        can_trade_now = not blocking_failures and side in {"buy", "sell"}
        consolidation_timeframe = timeframe_label if timeframe_label in {"M5", "M15"} else "M5"
        consolidation_snapshot = self.consolidation_data(target_symbol, consolidation_timeframe)

        entry_price = round(ask if side == "buy" else bid if side == "sell" else current_price, digits)
        stop_loss = round(entry_price - atr_value * atr_sl_multiplier, digits) if side == "buy" else round(entry_price + atr_value * atr_sl_multiplier, digits) if side == "sell" else entry_price
        take_profit = round(entry_price + atr_value * atr_tp_multiplier, digits) if side == "buy" else round(entry_price - atr_value * atr_tp_multiplier, digits) if side == "sell" else entry_price
        stop_distance = abs(entry_price - stop_loss)
        take_profit_distance = abs(take_profit - entry_price)
        rr_ratio = take_profit_distance / stop_distance if stop_distance else 0.0

        tick_size = safe_float(getattr(symbol_info, "trade_tick_size", point), point) or point
        tick_value = safe_float(getattr(symbol_info, "trade_tick_value", 0.0))
        if tick_value <= 0:
            tick_value = safe_float(getattr(symbol_info, "trade_tick_value_profit", 0.0))
        risk_amount = balance * (risk_percent / 100.0)
        risk_per_lot = (stop_distance / tick_size) * tick_value if tick_size and tick_value and stop_distance else 0.0
        raw_lot = (risk_amount / risk_per_lot) if risk_per_lot else 0.0
        min_volume = safe_float(getattr(symbol_info, "volume_min", 0.01), 0.01)
        max_volume = safe_float(getattr(symbol_info, "volume_max", 100.0), 100.0)
        volume_step = safe_float(getattr(symbol_info, "volume_step", min_volume or 0.01), min_volume or 0.01)
        lot_reason = "Risk-based size calculated normally."
        if 0 < raw_lot < min_volume and allow_min_lot:
            raw_lot = min_volume
            lot_reason = "Risk size fell below broker minimum, so the plan uses minimum lot."
        normalized_lot = normalize_volume_down(raw_lot, min_volume, max_volume, volume_step) if raw_lot else 0.0

        margin_per_lot = 0.0
        margin_capped_lot = normalized_lot
        if side in {"buy", "sell"} and entry_price > 0:
            margin_mode = getattr(mt5, "ORDER_TYPE_BUY", 0) if side == "buy" else getattr(mt5, "ORDER_TYPE_SELL", 1)
            estimated_margin = mt5.order_calc_margin(margin_mode, target_symbol, 1.0, entry_price)
            margin_per_lot = safe_float(estimated_margin, 0.0)
            allowed_margin = free_margin * (max_margin_usage_percent / 100.0)
            if margin_per_lot > 0 and allowed_margin > 0:
                cap_lot = normalize_volume_down(allowed_margin / margin_per_lot, min_volume, max_volume, volume_step)
                if cap_lot and (margin_capped_lot == 0.0 or cap_lot < margin_capped_lot):
                    margin_capped_lot = cap_lot
                    lot_reason = "Lot was capped by the bot's free-margin guardrail."

        execution_plan = {
            "side": side,
            "entry": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "stop_distance": stop_distance,
            "take_profit_distance": take_profit_distance,
            "rr_ratio": rr_ratio,
            "atr_multiplier_sl": atr_sl_multiplier,
            "atr_multiplier_tp": atr_tp_multiplier,
            "reason": (
                "The bot would buy because price is above the H4 EMA200."
                if side == "buy"
                else "The bot would sell because price is below the H4 EMA200."
                if side == "sell"
                else "Bias is neutral, so the bot would not form a directional plan yet."
            ),
        }
        risk_plan = {
            "risk_percent": risk_percent,
            "risk_amount": risk_amount,
            "lot_size": margin_capped_lot,
            "raw_lot_size": raw_lot,
            "risk_per_lot": risk_per_lot,
            "margin_per_lot": margin_per_lot,
            "free_margin": free_margin,
            "min_volume": min_volume,
            "volume_step": volume_step,
            "note": lot_reason,
        }

        active_position = None
        management_plan: dict[str, Any] = {
            "has_open_position": False,
            "summary": "No live position on this symbol, so the page is in planning mode.",
            "tone": "neutral",
        }
        if symbol_positions:
            position = symbol_positions[0]
            position_side = "buy" if int(getattr(position, "type", 0)) == getattr(mt5, "POSITION_TYPE_BUY", 0) else "sell"
            position_entry = safe_float(getattr(position, "price_open", 0.0))
            position_sl = safe_float(getattr(position, "sl", 0.0))
            position_tp = safe_float(getattr(position, "tp", 0.0))
            be_trigger_price = position_entry + atr_value * be_trigger_atr if position_side == "buy" else position_entry - atr_value * be_trigger_atr
            trail_activation_price = position_entry + atr_value * trail_start_atr if position_side == "buy" else position_entry - atr_value * trail_start_atr
            trail_step_price = atr_value * trail_step_atr
            live_price = bid if position_side == "buy" else ask if ask else current_price
            move_distance = live_price - position_entry if position_side == "buy" else position_entry - live_price
            break_even_due = move_distance >= atr_value * be_trigger_atr and (position_sl == 0 or (position_side == "buy" and position_sl < position_entry) or (position_side == "sell" and position_sl > position_entry))
            trailing_due = move_distance >= atr_value * trail_start_atr
            suggested_trail_sl = round((bid - trail_step_price) if position_side == "buy" else (ask + trail_step_price), digits) if trail_step_price else position_sl
            management_summary = "Hold the current plan."
            management_tone = "neutral"
            if break_even_due:
                management_summary = f"Move stop to breakeven now. Price has covered at least {be_trigger_atr:.1f} ATR in your favor."
                management_tone = "bullish" if position_side == "buy" else "bearish"
            elif trailing_due:
                management_summary = f"Trail the stop now. Price has moved beyond the {trail_start_atr:.1f} ATR activation level."
                management_tone = "bullish" if position_side == "buy" else "bearish"

            active_position = {
                "ticket": int(getattr(position, "ticket", 0)),
                "side": position_side,
                "entry": position_entry,
                "stop_loss": position_sl,
                "take_profit": position_tp,
                "volume": safe_float(getattr(position, "volume", 0.0)),
                "profit": safe_float(getattr(position, "profit", 0.0)),
            }
            management_plan = {
                "has_open_position": True,
                "side": position_side,
                "entry": position_entry,
                "stop_loss": position_sl,
                "take_profit": position_tp,
                "profit": safe_float(getattr(position, "profit", 0.0)),
                "break_even_trigger": round(be_trigger_price, digits),
                "trailing_trigger": round(trail_activation_price, digits),
                "trailing_step": round(trail_step_price, digits),
                "suggested_trailing_stop": suggested_trail_sl,
                "break_even_due": break_even_due,
                "trailing_due": trailing_due,
                "summary": management_summary,
                "tone": management_tone,
            }

        prompt_state = {"state": "wait", "tone": "neutral", "summary": "Wait for the bot gates to line up."}
        if management_plan.get("has_open_position"):
            if management_plan.get("break_even_due"):
                prompt_state = {"state": "break_even", "tone": management_plan["tone"], "summary": management_plan["summary"]}
            elif management_plan.get("trailing_due"):
                prompt_state = {"state": "trail_stop", "tone": management_plan["tone"], "summary": management_plan["summary"]}
            else:
                prompt_state = {"state": "manage", "tone": "neutral", "summary": management_plan["summary"]}
        elif can_trade_now and side == "buy":
            prompt_state = {"state": "buy_now", "tone": "bullish", "summary": f"Buy now. All bot gates are open and price is above the H4 EMA200. Entry {entry_price:.2f}, stop {stop_loss:.2f}, take profit {take_profit:.2f}."}
        elif can_trade_now and side == "sell":
            prompt_state = {"state": "sell_now", "tone": "bearish", "summary": f"Sell now. All bot gates are open and price is below the H4 EMA200. Entry {entry_price:.2f}, stop {stop_loss:.2f}, take profit {take_profit:.2f}."}
        elif blocking_failures:
            prompt_state = {"state": "blocked", "tone": "neutral", "summary": f"Stand aside for now. The first blocking condition is: {blocking_failures[0]['label']}."}

        market_sessions = market_sessions_snapshot()
        zones = [
            {"label": "Primary Resistance", "kind": "resistance", "low": round(range_high - atr_value * 0.35, 2), "high": round(range_high + atr_value * 0.15, 2)},
            {"label": "Intraday Pivot", "kind": "pivot", "low": round(midline - atr_value * 0.18, 2), "high": round(midline + atr_value * 0.18, 2)},
            {"label": "Fib Pocket", "kind": "pivot", "low": round(min(fib_500, fib_618), 2), "high": round(max(fib_500, fib_618), 2)},
            {"label": "Primary Support", "kind": "support", "low": round(range_low - atr_value * 0.15, 2), "high": round(range_low + atr_value * 0.35, 2)},
        ]
        confluences = [
            {"title": "Bias Model", "detail": f"Current price {current_price:.2f} is {'above' if bias == 'bullish' else 'below' if bias == 'bearish' else 'at'} the H4 EMA200 at {h4_ema200:.2f}.", "tone": "bullish" if bias == "bullish" else "bearish" if bias == "bearish" else "neutral"},
            {"title": "Continuation Read", "detail": f"{continuation_label} ({continuation_score}/100). {' '.join(continuation_factors[:3])}", "tone": "bullish" if continuation_side == "bullish" and continuation_score >= 60 else "bearish" if continuation_side == "bearish" and continuation_score >= 60 else "neutral"},
            {"title": "Session & Kill Zone", "detail": f"Session is {session_name}. Trading window is {'open' if session_allowed else 'closed'} and kill zone is {'active' if kill_zone_active else 'inactive'}.", "tone": "neutral"},
            {"title": "Spread / ATR", "detail": f"Spread is {spread_points:.1f} pts and M5 ATR is {atr_points:.1f} pts.", "tone": "neutral"},
            {"title": "Consolidation Read", "detail": consolidation_snapshot.get("message", f"{target_symbol} consolidation read is unavailable right now."), "tone": "pivot" if consolidation_snapshot.get("in_consolidation") else "neutral"},
            {"title": "Swing Structure", "detail": swing_structure.get("summary", "Recent swing structure is unavailable right now."), "tone": "bullish" if swing_structure.get("direction") == "bullish" else "bearish" if swing_structure.get("direction") == "bearish" else "neutral"},
            {"title": "Liquidity Context", "detail": f"{len(liquidity_levels)} recent liquidity levels, {len(fvgs)} fair value gaps, and {len(order_blocks)} order blocks are in view.", "tone": "pivot"},
            {"title": "Risk Plan", "detail": f"Suggested lot is {margin_capped_lot:.2f} with {risk_percent:.1f}% risk and ~{rr_ratio:.2f}R reward profile.", "tone": "neutral"},
        ]

        trade_advice = {
            "advisable": can_trade_now,
            "bias": side,
            "tone": prompt_state["tone"],
            "summary": prompt_state["summary"],
            "method_note": "This page mirrors the bot: session/spread/ATR/day checks, H4 EMA200 bias, ATR-based stop/target, risk lot sizing, and break-even/trailing prompts. It never sends trades.",
        }
        prediction = {
            "direction": "bullish" if side == "buy" else "bearish" if side == "sell" else "neutral",
            "summary": prompt_state["summary"],
            "score": max(0, 100 - len(blocking_failures) * 20),
        }

        return {
            "connected": self.connected,
            "connection_error": self.connection_error,
            "symbol": target_symbol,
            "timeframe": timeframe_label,
            "candles": candles[-320:],
            "zones": zones,
            "key_levels": key_levels,
            "confluences": confluences,
            "bias": bias,
            "current_price": current_price,
            "prediction": prediction,
            "trade_advice": trade_advice,
            "gate_checks": gate_checks,
            "day_state": {
                "session_label": session_name,
                "day_start_balance": day_start_balance,
                "balance": balance,
                "equity": equity,
                "realized_daily_pl": realized_daily_pl,
                "daily_pl_pct": daily_pl_pct,
                "today_trade_count": today_trade_count,
                "open_positions_total": open_positions_total,
            },
            "market_snapshot": {
                "bid": bid,
                "ask": ask,
                "spread_points": spread_points,
                "spread_price": spread_price,
                "atr": atr_value,
                "atr_points": atr_points,
                "recent_high": swing_high,
                "recent_low": swing_low,
                "session_name": session_name,
                "session_allowed": session_allowed,
                "kill_zone_active": kill_zone_active,
                "digits": digits,
                "point": point,
            },
            "consolidation_context": {
                "timeframe": consolidation_snapshot.get("timeframe", consolidation_timeframe),
                "in_consolidation": bool(consolidation_snapshot.get("in_consolidation")),
                "status": consolidation_snapshot.get("status", "unavailable"),
                "message": consolidation_snapshot.get("message", ""),
                "range": consolidation_snapshot.get("range"),
                "upper_zone": consolidation_snapshot.get("upper_zone"),
                "lower_zone": consolidation_snapshot.get("lower_zone"),
                "average_true_range": consolidation_snapshot.get("average_true_range", 0.0),
                "average_body": consolidation_snapshot.get("average_body", 0.0),
                "breakout_buffer": consolidation_snapshot.get("breakout_buffer", 0.0),
            },
            "bias_model": {
                "side": side,
                "macro_bias": bias,
                "local_bias": local_bias,
                "alignment": bias_alignment,
                "h4_ema200": h4_ema200,
                "h1_ema34": h1_ema34,
                "local_ema34": local_ema34,
                "price_vs_h4_ema200": current_price - h4_ema200,
                "price_vs_local_ema34": current_price - local_ema34,
                "continuation_side": continuation_side,
                "continuation_score": continuation_score,
                "continuation_label": continuation_label,
                "continuation_factors": continuation_factors,
            },
            "execution_plan": execution_plan,
            "risk_plan": risk_plan,
            "management_plan": management_plan,
            "structure_context": {
                "liquidity_levels": liquidity_levels,
                "fair_value_gaps": fvgs,
                "order_blocks": order_blocks,
                "swing_structure": swing_structure,
            },
            "active_position": active_position,
            "prompt_state": prompt_state,
            "market_sessions": market_sessions,
        }

    def market_intel(self, symbol: str = "XAUUSD", timeframe: str = "H1", session_focus: str = "auto") -> dict[str, Any]:
        analysis = self.market_analysis(symbol, timeframe)
        candles = analysis.get("candles", [])
        requested_symbol = str(symbol or "XAUUSD").strip() or "XAUUSD"
        focus_key = str(session_focus or "auto").strip().lower() or "auto"
        if focus_key not in {"auto", "london", "new-york", "asia", "off-session"}:
            focus_key = "auto"
        if not candles:
            return {
                **analysis,
                "requested_symbol": requested_symbol,
                "regime": "unknown",
                "confidence": 0,
                "ai_summary": analysis.get("connection_error") or "No market data is available yet.",
                "indicator_board": [],
                "liquidity_map": [],
                "scenario_cards": [],
                "session_models": [],
                "journal_bridge": {"cards": []},
                "what_to_watch": [],
                "session_focus": focus_key,
                "session_focus_label": focus_key.replace("-", " ").title(),
                "news_brief": "News feed integration is not wired in yet. Use this page for structure, levels, and scenario planning.",
            }

        def ema(values: list[float], period: int) -> float:
            if not values:
                return 0.0
            period = max(1, period)
            alpha = 2 / (period + 1)
            result = values[0]
            for value in values[1:]:
                result = alpha * value + (1 - alpha) * result
            return result

        def rsi(values: list[float], period: int = 14) -> float:
            if len(values) < period + 1:
                return 50.0
            gains: list[float] = []
            losses: list[float] = []
            for index in range(1, len(values)):
                delta = values[index] - values[index - 1]
                gains.append(max(delta, 0.0))
                losses.append(max(-delta, 0.0))
            avg_gain = sum(gains[-period:]) / period
            avg_loss = sum(losses[-period:]) / period
            if avg_loss == 0:
                return 100.0 if avg_gain > 0 else 50.0
            rs = avg_gain / avg_loss
            return 100 - (100 / (1 + rs))

        def atr_from(candles_input: list[dict[str, Any]], period: int = 14) -> float:
            if len(candles_input) < 2:
                return 0.0
            true_ranges: list[float] = []
            for index in range(1, len(candles_input)):
                current = candles_input[index]
                previous = candles_input[index - 1]
                true_ranges.append(
                    max(
                        safe_float(current["high"]) - safe_float(current["low"]),
                        abs(safe_float(current["high"]) - safe_float(previous["close"])),
                        abs(safe_float(current["low"]) - safe_float(previous["close"])),
                    )
                )
            window = true_ranges[-period:] if len(true_ranges) >= period else true_ranges
            return sum(window) / max(len(window), 1)

        closes = [safe_float(item["close"]) for item in candles]
        highs = [safe_float(item["high"]) for item in candles]
        lows = [safe_float(item["low"]) for item in candles]
        current_price = safe_float(analysis.get("current_price"), closes[-1] if closes else 0.0)
        ema20 = ema(closes[-40:], 20)
        ema50 = ema(closes[-80:], 50)
        rsi14 = rsi(closes[-40:], 14)
        atr14 = atr_from(candles[-30:], 14)
        day_range = max(highs[-24:]) - min(lows[-24:]) if len(highs) >= 24 else max(highs) - min(lows)
        distance_to_high = max(highs[-24:]) - current_price if len(highs) >= 24 else max(highs) - current_price
        distance_to_low = current_price - min(lows[-24:]) if len(lows) >= 24 else current_price - min(lows)
        bias = analysis.get("bias", "neutral")
        prediction = analysis.get("prediction", {})
        score = int(prediction.get("score") or 0)
        confidence = clamp(48 + abs(score) * 9, 35, 92)
        if bias == "neutral":
            confidence = clamp(confidence - 8, 25, 80)

        regime = "ranging"
        if ema20 > ema50 and current_price > ema20:
            regime = "bullish trend"
        elif ema20 < ema50 and current_price < ema20:
            regime = "bearish trend"
        elif atr14 > max(day_range * 0.18, 0.01):
            regime = "volatile rotation"

        market_sessions = analysis.get("market_sessions", {})
        open_sessions = market_sessions.get("open_sessions", [])
        active_session = ", ".join(open_sessions) if open_sessions else "Off-session"
        session_focus_label = focus_key.replace("-", " ").title() if focus_key != "auto" else active_session
        session_tone = "neutral"
        if any("London" in item for item in open_sessions):
            session_tone = "london"
        elif any("New York" in item for item in open_sessions):
            session_tone = "new-york"
        elif any("Tokyo" in item or "Asia" in item for item in open_sessions):
            session_tone = "asia"

        indicator_board = [
            {
                "label": "Bias",
                "value": str(bias).upper(),
                "tone": "bullish" if bias == "bullish" else "bearish" if bias == "bearish" else "neutral",
            },
            {
                "label": "Regime",
                "value": regime.title(),
                "tone": "bullish" if "bullish" in regime else "bearish" if "bearish" in regime else "neutral",
            },
            {
                "label": "EMA 20 / 50",
                "value": f"{fmt_number(ema20)} / {fmt_number(ema50)}",
                "tone": "bullish" if ema20 > ema50 else "bearish" if ema20 < ema50 else "neutral",
            },
            {
                "label": "RSI 14",
                "value": fmt_number(rsi14, 1),
                "tone": "bearish" if rsi14 > 68 else "bullish" if rsi14 < 32 else "neutral",
            },
            {
                "label": "ATR 14",
                "value": fmt_number(atr14, 2),
                "tone": "neutral",
            },
            {
                "label": "Active Session",
                "value": active_session,
                "tone": session_tone,
            },
            {
                "label": "Focus Mode",
                "value": session_focus_label,
                "tone": session_tone if focus_key == "auto" else focus_key,
            },
        ]

        liquidity_map = [
            {
                "label": "Session High",
                "price": round(max(highs[-24:]) if len(highs) >= 24 else max(highs), 2),
                "kind": "resistance",
                "detail": "Nearest visible buy-side liquidity from the last trading day window.",
            },
            {
                "label": "Session Low",
                "price": round(min(lows[-24:]) if len(lows) >= 24 else min(lows), 2),
                "kind": "support",
                "detail": "Nearest visible sell-side liquidity from the last trading day window.",
            },
        ]

        for zone in analysis.get("zones", []):
            liquidity_map.append(
                {
                    "label": zone.get("label", "Zone"),
                    "price": round((safe_float(zone.get("low")) + safe_float(zone.get("high"))) / 2, 2),
                    "kind": zone.get("kind", "pivot"),
                    "detail": f"{fmt_number(zone.get('low'))} to {fmt_number(zone.get('high'))}",
                }
            )

        bullish_trigger = "A clean hold above the intraday pivot with higher lows and a reclaim of nearby resistance."
        bearish_trigger = "A rejection from resistance or fib pocket followed by a lower high and momentum close lower."
        if bias == "bullish":
            bullish_trigger = "Bias already favors upside. Watch for continuation above the pivot or a pullback hold into support."
        elif bias == "bearish":
            bearish_trigger = "Bias already favors downside. Watch for rejection from resistance or continuation under the pivot."

        scenario_cards = [
            {
                "title": "Bullish continuation",
                "direction": "bullish",
                "trigger": bullish_trigger,
                "invalidation": f"Lose the nearest support and slip back under {fmt_number(ema20)}.",
                "target": f"Run into {fmt_number(max(highs[-24:]) if len(highs) >= 24 else max(highs))} first, then the top of resistance.",
                "confidence": clamp(confidence + (10 if bias == 'bullish' else -8), 20, 95),
            },
            {
                "title": "Bearish continuation",
                "direction": "bearish",
                "trigger": bearish_trigger,
                "invalidation": f"Recover above {fmt_number(ema20)} and hold above resistance.",
                "target": f"Retest {fmt_number(min(lows[-24:]) if len(lows) >= 24 else min(lows))} and then look for follow-through lower.",
                "confidence": clamp(confidence + (10 if bias == 'bearish' else -8), 20, 95),
            },
            {
                "title": "Rotation / mean reversion",
                "direction": "neutral",
                "trigger": "Price keeps crossing the pivot and fails to break session extremes with conviction.",
                "invalidation": "A clean breakout that holds beyond the current range edges.",
                "target": "Fade back toward the midline until one side of liquidity finally gives way.",
                "confidence": clamp(70 - abs(score) * 6, 18, 76),
            },
        ]

        focus_bias = {
            "london": {"bullish": 6, "bearish": 6, "neutral": -3},
            "new-york": {"bullish": 4, "bearish": 4, "neutral": 0},
            "asia": {"bullish": -4, "bearish": -4, "neutral": 5},
            "off-session": {"bullish": -8, "bearish": -8, "neutral": 8},
            "auto": {"bullish": 0, "bearish": 0, "neutral": 0},
        }
        focus_adjustment = focus_bias.get(focus_key, focus_bias["auto"])
        for card in scenario_cards:
            direction = str(card.get("direction", "neutral"))
            card["confidence"] = clamp(
                safe_float(card.get("confidence")) + safe_float(focus_adjustment.get(direction, 0)),
                12,
                96,
            )

        session_models = [
            {
                "title": "London continuation model",
                "tone": "london",
                "trigger": "Strong push from London open holds above or below the pivot and keeps respecting the EMA stack.",
                "ideal_if": "You already have trend alignment and price keeps defending the first retracement.",
                "explanation": "Best for trend days when London creates the cleanest directional impulse and New York has not yet reversed it.",
            },
            {
                "title": "New York reversal model",
                "tone": "new-york",
                "trigger": "New York raids a London or Asian extreme, then snaps back through structure with momentum.",
                "ideal_if": "You see exhaustion into a liquidity pool and price fails to hold beyond the sweep.",
                "explanation": "Best for reversal conditions when New York attacks prior session liquidity before rotating back through the range.",
            },
            {
                "title": "Asia range hold",
                "tone": "asia",
                "trigger": "Price rotates around a narrow range and fails to expand cleanly away from the midline.",
                "ideal_if": "Volatility is muted and session extremes keep rejecting without follow-through.",
                "explanation": "Useful when the market is balanced and you want patience instead of forcing trend assumptions too early.",
            },
        ]
        if focus_key != "auto":
            preferred_tone = "new-york" if focus_key == "new-york" else "asia" if focus_key == "asia" else "london" if focus_key == "london" else "neutral"
            session_models.sort(key=lambda item: 0 if item["tone"] == preferred_tone else 1)

        symbol_aliases = {str(analysis.get("symbol", requested_symbol)).strip().upper(), requested_symbol.upper()}
        if any(item.startswith("XAUUSD") or item == "GOLD" for item in symbol_aliases):
            symbol_aliases.update({"XAUUSD", "XAUUSDM", "GOLD", "XAUUSD."})
        account_login = self._current_account_login()
        account_server = self._current_account_server()
        account_scopes = [(account_login, account_server)] if account_login is not None else None
        recent_rows = DB.mt5_history_insight_rows(
            account_scopes=account_scopes,
            symbols=sorted(symbol_aliases),
        )
        recent_rows = recent_rows[:25]
        recent_profit = sum(safe_float(row.get("profit")) for row in recent_rows)
        long_profit = sum(safe_float(row.get("profit")) for row in recent_rows if normalize_side(str(row.get("side", ""))) == "BUY")
        short_profit = sum(safe_float(row.get("profit")) for row in recent_rows if normalize_side(str(row.get("side", ""))) == "SELL")
        journal_bridge_cards: list[dict[str, Any]] = []
        if recent_rows:
            favored_side = "BUY" if long_profit > short_profit else "SELL" if short_profit > long_profit else "MIXED"
            alignment = "aligned" if favored_side == "BUY" and bias == "bullish" or favored_side == "SELL" and bias == "bearish" else "risk"
            journal_bridge_cards.extend(
                [
                    {
                        "title": "Recent Symbol Edge",
                        "value": f"{recent_profit:+.2f} across {len(recent_rows)} cached trade(s)",
                        "detail": f"Recent history for {analysis.get('symbol', requested_symbol)} is what this page is comparing against.",
                        "tone": "aligned" if recent_profit > 0 else "risk" if recent_profit < 0 else "neutral",
                    },
                    {
                        "title": "Direction Match",
                        "value": f"Journal side edge: {favored_side}",
                        "detail": f"Market Intel bias is {str(bias).upper()}. A mismatch means you should demand cleaner confirmation before acting.",
                        "tone": alignment if favored_side != "MIXED" else "neutral",
                    },
                ]
            )
        else:
            journal_bridge_cards.append(
                {
                    "title": "No Cached Symbol History",
                    "value": "Market Intel has no recent closed-trade sample for this symbol yet.",
                    "detail": "Once journal history is cached for this symbol and account, this section will compare the live read to your actual recent results.",
                    "tone": "neutral",
                }
            )

        what_to_watch = [
            f"Price is {fmt_number(distance_to_high, 2)} away from session high liquidity and {fmt_number(distance_to_low, 2)} away from session low liquidity.",
            f"Current regime reads as {regime}, so don't treat this like a trend day unless price keeps respecting the EMA stack.",
            f"ATR is {fmt_number(atr14, 2)} and the visible day range is {fmt_number(day_range, 2)}. If momentum expands beyond that balance, expect the stronger scenario to take over.",
            f"Live prediction score is {score}. Use that as context, not as an auto-trade signal.",
        ]

        summary_direction = prediction.get("direction", "neutral")
        if summary_direction == "bullish":
            ai_summary = f"{analysis.get('symbol', symbol)} currently leans bullish on {analysis.get('timeframe', timeframe)}. Structure and session context suggest buyers still have control as long as price respects the pivot and EMA 20."
        elif summary_direction == "bearish":
            ai_summary = f"{analysis.get('symbol', symbol)} currently leans bearish on {analysis.get('timeframe', timeframe)}. The cleaner path is lower if resistance keeps rejecting and price stays beneath the intraday midline."
        else:
            ai_summary = f"{analysis.get('symbol', symbol)} is mixed right now. The best read is to treat the market as rotational until one side of liquidity breaks with follow-through."

        return {
            **analysis,
            "requested_symbol": requested_symbol,
            "regime": regime,
            "confidence": confidence,
            "ai_summary": ai_summary,
            "indicator_board": indicator_board,
            "liquidity_map": liquidity_map,
            "scenario_cards": scenario_cards,
            "session_models": session_models,
            "journal_bridge": {"cards": journal_bridge_cards},
            "what_to_watch": what_to_watch,
            "session_focus": focus_key,
            "session_focus_label": session_focus_label,
            "active_session": active_session,
            "news_brief": "Live headlines are not wired in yet, so use the Macro Notes panel to track CPI, NFP, FOMC, or broker-specific risk before trusting the live scenario stack.",
        }

    def _resolve_chart_symbol(self, symbol: str) -> tuple[str, Any, str]:
        if mt5 is None:
            return symbol.strip() or "XAUUSD", None, "MetaTrader5 package is not installed."
        requested = (symbol or "").strip()
        normalized = requested.upper()
        candidates = [requested, normalized]
        if normalized == "XAUUSD":
            candidates.extend(["XAUUSDm", "GOLD", "XAUUSD."])
        elif normalized == "USOIL":
            candidates.extend(["USOILm", "XBRUSD", "XTIUSD", "WTI", "WTIm", "USOilCash", "USOIL.", "USOILCash"])
        elif normalized == "NASDAQ":
            candidates.extend(["USTEC", "USTECm", "NAS100", "NAS100m", "US100", "US100m", "NASDAQ.", "NAS"])
        elif normalized == "BTCUSD":
            candidates.extend(["BTCUSDm", "BTCUSD.", "BTCUSDm."])
        elif normalized == "EURUSD":
            candidates.extend(["EURUSDm", "EURUSD."])
        if self.primary_symbol:
            candidates.append(self.primary_symbol)
        seen: set[str] = set()
        for candidate in candidates:
            candidate = str(candidate or "").strip()
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            info = mt5.symbol_info(candidate)
            if info is not None:
                if not getattr(info, "visible", True):
                    mt5.symbol_select(candidate, True)
                    info = mt5.symbol_info(candidate)
                return candidate, info, ""
        return requested or normalized or "UNKNOWN", None, f"Symbol {requested or normalized} is not available in this terminal."

    def _aggregate_candles(self, candles: list[dict[str, Any]], ratio: int) -> list[dict[str, Any]]:
        if ratio <= 1:
            return candles
        usable = candles[-((len(candles) // ratio) * ratio):]
        aggregated: list[dict[str, Any]] = []
        for index in range(0, len(usable), ratio):
            chunk = usable[index:index + ratio]
            if len(chunk) < ratio:
                continue
            aggregated.append(
                {
                    "time": chunk[0]["time"],
                    "open": chunk[0]["open"],
                    "high": max(item["high"] for item in chunk),
                    "low": min(item["low"] for item in chunk),
                    "close": chunk[-1]["close"],
                    "tick_volume": sum(int(item.get("tick_volume", 0)) for item in chunk),
                }
            )
        return aggregated

    def _previous_period_levels(
        self,
        symbol: str,
        *,
        timeframe_attr: str,
        fallback_value: int,
        count: int,
        point: float,
        label_prefix: str,
        fallback_step: timedelta,
    ) -> list[dict[str, Any]]:
        if mt5 is None:
            return []
        timeframe_value = getattr(mt5, timeframe_attr, fallback_value)
        rates = mt5.copy_rates_from_pos(symbol, timeframe_value, 0, count)
        if rates is None or len(rates) < 2:
            return []

        candles = [
            {
                "time": datetime.fromtimestamp(int(rate["time"]), UTC),
                "open": safe_float(rate["open"]),
                "high": safe_float(rate["high"]),
                "low": safe_float(rate["low"]),
                "close": safe_float(rate["close"]),
                "tick_volume": int(rate["tick_volume"]),
            }
            for rate in rates
        ]
        candles.sort(key=lambda item: item["time"])

        levels: list[dict[str, Any]] = []
        pip_size = max(point, 0.01)
        period_label = {"PD": "day", "PW": "week", "PM": "month"}.get(label_prefix, "period")
        for index in range(1, len(candles)):
            current = candles[index]
            previous = candles[index - 1]
            next_start = candles[index + 1]["time"] if index + 1 < len(candles) else current["time"] + fallback_step
            previous_high = safe_float(previous["high"])
            previous_low = safe_float(previous["low"])
            current_high = safe_float(current["high"])
            current_low = safe_float(current["low"])
            current_close = safe_float(current["close"])
            swept_high = current_high > previous_high
            swept_low = current_low < previous_low
            close_back_inside = previous_low <= current_close <= previous_high
            if swept_high and swept_low:
                sweep_status = "swept_both"
            elif swept_high and close_back_inside:
                sweep_status = "swept_high_rejected"
            elif swept_low and close_back_inside:
                sweep_status = "swept_low_rejected"
            elif swept_high:
                sweep_status = "swept_high"
            elif swept_low:
                sweep_status = "swept_low"
            else:
                sweep_status = f"inside_previous_{period_label}"

            levels.append(
                {
                    "period_type": period_label,
                    "period_label": label_prefix,
                    "start_time": current["time"].isoformat(),
                    "end_time": next_start.isoformat(),
                    "period": current["time"].date().isoformat(),
                    f"previous_{period_label}": previous["time"].date().isoformat(),
                    "previous_high": previous_high,
                    "previous_low": previous_low,
                    "previous_mid": (previous_high + previous_low) / 2,
                    "previous_range_pips": (previous_high - previous_low) / pip_size,
                    "swept_high": swept_high,
                    "swept_low": swept_low,
                    "sweep_status": sweep_status,
                    "high_code": f"{label_prefix}H",
                    "low_code": f"{label_prefix}L",
                }
            )
        return levels

    def _previous_day_levels(self, symbol: str, point: float) -> list[dict[str, Any]]:
        return self._previous_period_levels(
            symbol,
            timeframe_attr="TIMEFRAME_D1",
            fallback_value=16408,
            count=280,
            point=point,
            label_prefix="PD",
            fallback_step=timedelta(days=1),
        )

    def _previous_week_levels(self, symbol: str, point: float) -> list[dict[str, Any]]:
        return self._previous_period_levels(
            symbol,
            timeframe_attr="TIMEFRAME_W1",
            fallback_value=32769,
            count=220,
            point=point,
            label_prefix="PW",
            fallback_step=timedelta(days=7),
        )

    def _previous_month_levels(self, symbol: str, point: float) -> list[dict[str, Any]]:
        return self._previous_period_levels(
            symbol,
            timeframe_attr="TIMEFRAME_MN1",
            fallback_value=49153,
            count=120,
            point=point,
            label_prefix="PM",
            fallback_step=timedelta(days=31),
        )

    def _active_period_level_for_time(self, levels: list[dict[str, Any]], candle_time_iso: str) -> dict[str, Any] | None:
        if not levels:
            return None
        try:
            candle_time = datetime.fromisoformat(candle_time_iso)
        except Exception:
            return None
        active = None
        for level in levels:
            try:
                start_time = datetime.fromisoformat(str(level.get("start_time", "")))
                end_time = datetime.fromisoformat(str(level.get("end_time", "")))
            except Exception:
                continue
            if start_time <= candle_time < end_time:
                active = level
            elif start_time > candle_time:
                break
        return active

    def _detect_liquidity_sweeps(
        self,
        candles: list[dict[str, Any]],
        *,
        point: float,
        previous_day_levels: list[dict[str, Any]],
        previous_week_levels: list[dict[str, Any]],
        previous_month_levels: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not candles:
            return []
        buffer_value = max(point * 8, 0.02)
        local_lookback = 8
        events: list[dict[str, Any]] = []

        def append_event(
            *,
            candle: dict[str, Any],
            price: float,
            label: str,
            side: str,
            source_type: str,
            level_period: str,
            confidence: int,
            note: str,
            level_ref: dict[str, Any] | None = None,
        ) -> None:
            events.append(
                {
                    "time": candle.get("time"),
                    "price": price,
                    "label": label,
                    "side": side,
                    "source_type": source_type,
                    "level_period": level_period,
                    "confidence": confidence,
                    "note": note,
                    "open": safe_float(candle.get("open")),
                    "high": safe_float(candle.get("high")),
                    "low": safe_float(candle.get("low")),
                    "close": safe_float(candle.get("close")),
                    "level_start_time": (level_ref or {}).get("start_time"),
                    "level_end_time": (level_ref or {}).get("end_time"),
                }
            )

        for index, candle in enumerate(candles):
            candle_high = safe_float(candle.get("high"))
            candle_low = safe_float(candle.get("low"))
            candle_close = safe_float(candle.get("close"))
            candle_time = str(candle.get("time") or "")

            active_levels = [
                self._active_period_level_for_time(previous_day_levels, candle_time),
                self._active_period_level_for_time(previous_week_levels, candle_time),
                self._active_period_level_for_time(previous_month_levels, candle_time),
            ]
            for active_level in [item for item in active_levels if item]:
                previous_high = safe_float(active_level.get("previous_high"))
                previous_low = safe_float(active_level.get("previous_low"))
                high_code = str(active_level.get("high_code") or "PDH")
                low_code = str(active_level.get("low_code") or "PDL")
                period_label = str(active_level.get("period_label") or "PD")
                if candle_high > previous_high + buffer_value and candle_close <= previous_high:
                    append_event(
                        candle=candle,
                        price=previous_high,
                        label=f"{high_code} sweep",
                        side="sell",
                        source_type="engineered",
                        level_period=period_label,
                        confidence=86 if period_label == "PD" else 90 if period_label == "PW" else 93,
                        note=f"Price raided {high_code} and closed back below the level.",
                        level_ref=active_level,
                    )
                if candle_low < previous_low - buffer_value and candle_close >= previous_low:
                    append_event(
                        candle=candle,
                        price=previous_low,
                        label=f"{low_code} sweep",
                        side="buy",
                        source_type="engineered",
                        level_period=period_label,
                        confidence=86 if period_label == "PD" else 90 if period_label == "PW" else 93,
                        note=f"Price raided {low_code} and closed back above the level.",
                        level_ref=active_level,
                    )

            if index < local_lookback:
                continue
            prior = candles[max(0, index - local_lookback):index]
            if not prior:
                continue
            recent_high = max(safe_float(item.get("high")) for item in prior)
            recent_low = min(safe_float(item.get("low")) for item in prior)
            if candle_high > recent_high + buffer_value and candle_close <= recent_high:
                append_event(
                    candle=candle,
                    price=recent_high,
                    label="Recent high sweep",
                    side="sell",
                    source_type="local",
                    level_period="swing",
                    confidence=72,
                    note="Price took a recent swing high and closed back beneath it.",
                )
            if candle_low < recent_low - buffer_value and candle_close >= recent_low:
                append_event(
                    candle=candle,
                    price=recent_low,
                    label="Recent low sweep",
                    side="buy",
                    source_type="local",
                    level_period="swing",
                    confidence=72,
                    note="Price took a recent swing low and closed back above it.",
                )

        deduped: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for event in events:
            key = (str(event.get("time")), str(event.get("label")), str(event.get("side")))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(event)
        return deduped

    def _chart_symbol_matches_trade(self, requested_symbol: str, resolved_symbol: str, trade_symbol: str) -> bool:
        def simplify(value: Any) -> str:
            return "".join(character for character in str(value or "").lower() if character.isalnum())

        requested = simplify(requested_symbol)
        resolved = simplify(resolved_symbol)
        trade = simplify(trade_symbol)
        if not trade:
            return False
        return trade == resolved or trade == requested or resolved in trade or trade in resolved or requested in trade or trade in requested

    def chart_data(
        self,
        symbol: str = "XAUUSD",
        timeframe: str = "M1",
        anchor_date: str = "",
        anchor_time: str = "",
    ) -> dict[str, Any]:
        if not self._initialize():
            return {
                "connected": False,
                "connection_error": self.connection_error,
                "requested_symbol": symbol,
                "symbol": symbol,
                "timeframe": timeframe,
                "candles": [],
                "current_price": 0.0,
                "previous_day_levels": [],
                "anchor_date": anchor_date,
                "anchor_time": anchor_time,
            }
        if mt5 is None:
            return {
                "connected": False,
                "connection_error": "MetaTrader5 package is not installed.",
                "requested_symbol": symbol,
                "symbol": symbol,
                "timeframe": timeframe,
                "candles": [],
                "current_price": 0.0,
                "previous_day_levels": [],
                "anchor_date": anchor_date,
                "anchor_time": anchor_time,
            }

        resolved_symbol, symbol_info, connection_error = self._resolve_chart_symbol(symbol)
        if symbol_info is None:
            return {
                "connected": self.connected,
                "connection_error": connection_error,
                "requested_symbol": symbol,
                "symbol": resolved_symbol,
                "timeframe": timeframe,
                "candles": [],
                "current_price": 0.0,
                "previous_day_levels": [],
                "anchor_date": anchor_date,
                "anchor_time": anchor_time,
            }

        timeframe_key = (timeframe or "M1").strip().upper()
        timeframe_specs: dict[str, tuple[str, int, int, int]] = {
            "M1": ("TIMEFRAME_M1", 1, 2400, 1),
            "M2": ("TIMEFRAME_M1", 2, 3200, 1),
            "M3": ("TIMEFRAME_M1", 3, 3600, 1),
            "M5": ("TIMEFRAME_M5", 1, 2200, 5),
            "M10": ("TIMEFRAME_M5", 2, 2800, 5),
            "M15": ("TIMEFRAME_M15", 1, 1800, 15),
            "M30": ("TIMEFRAME_M30", 1, 1500, 30),
            "H1": ("TIMEFRAME_H1", 1, 1200, 60),
            "H2": ("TIMEFRAME_H1", 2, 1600, 60),
            "H4": ("TIMEFRAME_H4", 1, 900, 240),
            "D1": ("TIMEFRAME_D1", 1, 500, 1440),
            "W1": ("TIMEFRAME_W1", 1, 320, 10080),
            "MN1": ("TIMEFRAME_MN1", 1, 180, 43200),
        }
        timeframe_attr, ratio, count, base_minutes = timeframe_specs.get(timeframe_key, ("TIMEFRAME_M1", 1, 360, 1))
        timeframe_value = getattr(mt5, timeframe_attr, getattr(mt5, "TIMEFRAME_M1", 1))
        normalized_anchor_date = str(anchor_date or "").strip()
        normalized_anchor_time = str(anchor_time or "").strip()
        anchor_dt: datetime | None = None
        if normalized_anchor_date:
            try:
                if normalized_anchor_time:
                    time_value = normalized_anchor_time if len(normalized_anchor_time.split(":")) == 3 else f"{normalized_anchor_time}:00"
                    anchor_dt = datetime.fromisoformat(f"{normalized_anchor_date}T{time_value}").replace(tzinfo=UTC)
                else:
                    anchor_dt = datetime.fromisoformat(f"{normalized_anchor_date}T23:59:00").replace(tzinfo=UTC)
            except ValueError:
                return {
                    "connected": self.connected,
                    "connection_error": f"Invalid chart date/time: {normalized_anchor_date} {normalized_anchor_time}".strip(),
                    "requested_symbol": symbol,
                    "symbol": resolved_symbol,
                    "timeframe": timeframe_key,
                    "candles": [],
                    "current_price": 0.0,
                    "previous_day_levels": [],
                    "anchor_date": normalized_anchor_date,
                    "anchor_time": normalized_anchor_time,
                }

        if anchor_dt is not None:
            lookback_minutes = base_minutes * (count + max(ratio * 8, 12))
            range_start = anchor_dt - timedelta(minutes=lookback_minutes)
            range_end = anchor_dt + timedelta(minutes=max(base_minutes, 1))
            rates = mt5.copy_rates_range(resolved_symbol, timeframe_value, range_start, range_end)
        else:
            rates = mt5.copy_rates_from_pos(resolved_symbol, timeframe_value, 0, count)
        if rates is None or len(rates) < max(20, ratio * 10):
            return {
                "connected": self.connected,
                "connection_error": f"Could not load candle history for {resolved_symbol} on {timeframe_key}."
                if anchor_dt is None
                else f"Could not load candle history for {resolved_symbol} on {timeframe_key} near {anchor_dt.isoformat()}.",
                "requested_symbol": symbol,
                "symbol": resolved_symbol,
                "timeframe": timeframe_key,
                "candles": [],
                "current_price": 0.0,
                "previous_day_levels": [],
                "anchor_date": normalized_anchor_date,
                "anchor_time": normalized_anchor_time,
            }

        base_candles = [
            {
                "time": datetime.fromtimestamp(int(rate["time"]), UTC).isoformat(),
                "open": safe_float(rate["open"]),
                "high": safe_float(rate["high"]),
                "low": safe_float(rate["low"]),
                "close": safe_float(rate["close"]),
                "tick_volume": int(rate["tick_volume"]),
            }
            for rate in rates
        ]
        candles = self._aggregate_candles(base_candles, ratio)[-1600:]
        tick = mt5.symbol_info_tick(resolved_symbol)
        current_price = (
            safe_float(candles[-1]["close"])
            if anchor_dt is not None
            else safe_float(getattr(tick, "last", 0.0)) or safe_float(getattr(tick, "bid", 0.0)) or safe_float(candles[-1]["close"])
        )
        point_value = safe_float(getattr(symbol_info, "point", 0.01), 0.01)
        previous_day_levels = self._previous_day_levels(resolved_symbol, point_value)
        previous_week_levels = self._previous_week_levels(resolved_symbol, point_value)
        previous_month_levels = self._previous_month_levels(resolved_symbol, point_value)
        liquidity_sweeps = self._detect_liquidity_sweeps(
            candles,
            point=point_value,
            previous_day_levels=previous_day_levels,
            previous_week_levels=previous_week_levels,
            previous_month_levels=previous_month_levels,
        )
        active_trades = []
        with self.lock:
            for trade in self.trades.values():
                if not self._chart_symbol_matches_trade(symbol, resolved_symbol, getattr(trade, "symbol", "")):
                    continue
                active_trades.append(
                    {
                        "ticket": trade.ticket,
                        "symbol": trade.symbol,
                        "side": trade.side,
                        "volume": trade.volume,
                        "entry_price": trade.entry_price,
                        "stop_loss": trade.stop_loss,
                        "take_profit": trade.take_profit,
                        "current_price": trade.current_price,
                        "profit": trade.profit,
                        "pips": trade.pips,
                        "open_time": trade.open_time,
                    }
                )
        return {
            "connected": self.connected,
            "connection_error": self.connection_error,
            "requested_symbol": symbol,
            "symbol": resolved_symbol,
            "timeframe": timeframe_key,
            "candles": candles,
            "current_price": current_price,
            "point": point_value,
            "anchor_date": normalized_anchor_date,
            "anchor_time": normalized_anchor_time,
            "snapshot_label": (
                f"snapshot ending {anchor_dt.strftime('%Y-%m-%d %H:%M UTC')}"
                if anchor_dt is not None
                else ""
            ),
            "previous_day_levels": previous_day_levels,
            "previous_week_levels": previous_week_levels,
            "previous_month_levels": previous_month_levels,
            "liquidity_sweeps": liquidity_sweeps,
            "active_trades": active_trades,
        }

    def consolidation_data(self, symbol: str = "XAUUSD", timeframe: str = "M5") -> dict[str, Any]:
        payload = self.chart_data(symbol, timeframe)
        candles = payload.get("candles", [])
        if not candles:
            return {
                **payload,
                "in_consolidation": False,
                "range": None,
                "upper_zone": None,
                "lower_zone": None,
                "status": "unavailable",
                "message": payload.get("connection_error") or "No candles available for consolidation analysis.",
                "signals": [],
            }

        window = candles[-36:]
        highs = [safe_float(item["high"]) for item in window]
        lows = [safe_float(item["low"]) for item in window]
        closes = [safe_float(item["close"]) for item in window]
        opens = [safe_float(item["open"]) for item in window]
        current_price = safe_float(payload.get("current_price"), closes[-1] if closes else 0.0)
        range_high = max(highs)
        range_low = min(lows)
        range_size = max(range_high - range_low, safe_float(payload.get("point"), 0.01))
        true_ranges = [
            max(highs[index] - lows[index], abs(highs[index] - closes[index - 1]), abs(lows[index] - closes[index - 1]))
            for index in range(1, len(window))
        ]
        average_true_range = sum(true_ranges) / len(true_ranges) if true_ranges else range_size
        average_body = sum(abs(closes[index] - opens[index]) for index in range(len(window))) / max(len(window), 1)
        recent_high_cluster = sorted(highs)[-6:]
        recent_low_cluster = sorted(lows)[:6]
        upper_zone_low = min(recent_high_cluster) if recent_high_cluster else range_high - (range_size * 0.18)
        upper_zone_high = range_high
        lower_zone_low = range_low
        lower_zone_high = max(recent_low_cluster) if recent_low_cluster else range_low + (range_size * 0.18)
        mid_price = (range_high + range_low) / 2
        cluster_ratio = (upper_zone_high - upper_zone_low + lower_zone_high - lower_zone_low) / max(range_size, 0.00001)
        resolved_symbol = str(payload.get("symbol", symbol)).strip().upper()
        gold_symbol = resolved_symbol.startswith("XAUUSD") or resolved_symbol in {"GOLD", "XAUUSD."}
        range_multiplier_limit = 6.2 if gold_symbol else 8.5
        body_multiplier_limit = 0.62 if gold_symbol else 0.9
        cluster_ratio_limit = 0.52 if gold_symbol else 0.68
        in_consolidation = (
            range_size <= average_true_range * range_multiplier_limit
            and average_body <= average_true_range * body_multiplier_limit
            and cluster_ratio <= cluster_ratio_limit
        )
        breakout_buffer = max(range_size * 0.035, safe_float(payload.get("point"), 0.01) * 12)
        entered_upper_zone = upper_zone_low <= current_price <= upper_zone_high
        entered_lower_zone = lower_zone_low <= current_price <= lower_zone_high
        broke_above = current_price > (range_high + breakout_buffer)
        broke_below = current_price < (range_low - breakout_buffer)
        if broke_above:
            status = "breakout_up"
            message = f"{payload.get('symbol', symbol)} has pushed above the consolidation range."
        elif broke_below:
            status = "breakout_down"
            message = f"{payload.get('symbol', symbol)} has dropped below the consolidation range."
        elif entered_upper_zone:
            status = "testing_upper"
            message = f"{payload.get('symbol', symbol)} is testing the upper consolidation rejection zone."
        elif entered_lower_zone:
            status = "testing_lower"
            message = f"{payload.get('symbol', symbol)} is testing the lower consolidation rejection zone."
        elif in_consolidation:
            status = "inside_range"
            message = f"{payload.get('symbol', symbol)} is still ranging between the current consolidation boundaries."
        else:
            status = "not_consolidating"
            message = f"{payload.get('symbol', symbol)} no longer looks to be in consolidation on {payload.get('timeframe', timeframe)}."

        signals: list[dict[str, Any]] = []
        if entered_upper_zone:
            signals.append({"type": "upper_zone", "message": "Price is nearing the upper rejection area where bearish reversals often start."})
        if entered_lower_zone:
            signals.append({"type": "lower_zone", "message": "Price is nearing the lower rejection area where bullish reversals often start."})
        if broke_above:
            signals.append({"type": "breakout_up", "message": "Price has broken above the range and may be leaving consolidation to the upside."})
        if broke_below:
            signals.append({"type": "breakout_down", "message": "Price has broken below the range and may be leaving consolidation to the downside."})
        if not in_consolidation:
            signals.append({"type": "not_consolidating", "message": "The recent candle structure no longer fits a clean consolidation profile."})

        return {
            **payload,
            "in_consolidation": in_consolidation,
            "range": {
                "high": range_high,
                "low": range_low,
                "size": range_size,
                "mid": mid_price,
            },
            "upper_zone": {
                "low": upper_zone_low,
                "high": upper_zone_high,
            },
            "lower_zone": {
                "low": lower_zone_low,
                "high": lower_zone_high,
            },
            "status": status,
            "message": message,
            "signals": signals,
            "average_true_range": average_true_range,
            "average_body": average_body,
            "breakout_buffer": breakout_buffer,
            "strictness_profile": "gold_strict" if gold_symbol else "default",
        }


DB = Database(DB_PATH)
SOUNDER = Sounder()
NOTIFIER = EmailNotifier(load_smtp_config())
MONITOR = MT5Monitor(DB, SOUNDER, NOTIFIER)
ORL_SETTINGS = ORLSettings()
ORL_CANDLE_SERVICE = MT5CandleService(mt5)
ORL_ATR_SERVICE = ATRService()
ORL_PATTERN_SERVICE = CandlestickPatternService()
ORL_PROFIT_CALCULATOR = ORLProfitCalculator(mt5, ORL_CANDLE_SERVICE)
ORL_VALIDATION_SERVICE = ORLValidationService(ORL_CANDLE_SERVICE, ORL_SETTINGS)
ORL_ENGINE = ORLAnalysisService(
    ORL_SETTINGS,
    ORL_CANDLE_SERVICE,
    ORL_ATR_SERVICE,
    ORL_PATTERN_SERVICE,
    ORL_PROFIT_CALCULATOR,
    ORL_VALIDATION_SERVICE,
)
ORL_HISTORICAL_ANALYZER = ORLHistoricalAnalyzerService(ORL_ENGINE)
ORL_GMAIL_SERVICE = GmailNotificationService(lambda subject, body: NOTIFIER.send(subject, body), lambda: NOTIFIER.enabled and MONITOR.email_notifications_enabled())
ORL_SOUND_SERVICE = SoundAlertService(lambda sound_name: SOUNDER.play("orl"), enabled=ORL_SETTINGS.sound_enabled)
ORL_ALERTS = ORLAlertService(
    lambda event_type, message, payload: MONITOR._alert(
        event_type,
        "info" if "signal" not in event_type and "confirmed" not in event_type else "success",
        message,
        payload=payload,
    ),
    ORL_SOUND_SERVICE,
    ORL_GMAIL_SERVICE,
    ORL_SETTINGS,
)
MONITOR.orl_live_observer = ORLLiveObserverService(ORL_ENGINE, ORL_ALERTS, ORL_SETTINGS)
SIGNAL_LAB = SignalLabService(DB, mt5, lambda: MONITOR._initialize(), print)
HISTORY_BACKFILL = HistoricalBackfillService(
    AURUMBOX_MEMORY_DB_PATH,
    config=BackfillConfig(
        default_terminal_path=str(DEFAULT_HISTORY_TERMINAL_PATH),
        default_symbols=DEFAULT_HISTORY_SYMBOLS,
        default_timeframes=DEFAULT_HISTORY_TIMEFRAMES,
        default_days=30,
    ),
    log_output=log_output,
    log_error=log_error,
)


class AppHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        if parsed.path == "/api/state":
            self._send_json(MONITOR.state())
            return
        if parsed.path == "/api/deposits":
            range_key = params.get("range", ["year"])[0]
            profile_aliases = [item.strip() for item in params.get("profile_aliases", [""])[0].split(",") if item.strip()]
            exact_date = params.get("exact_date", [""])[0]
            if profile_aliases:
                self._send_json(MONITOR.deposit_history_for_profiles(range_key=range_key, profile_aliases=profile_aliases, exact_date=exact_date))
            else:
                self._send_json(MONITOR.deposit_history(range_key=range_key, exact_date=exact_date))
            return
        if parsed.path == "/api/journal-day-summary":
            profile_aliases = [item.strip() for item in params.get("profile_aliases", [""])[0].split(",") if item.strip()]
            source_mode = params.get("source_mode", ["current"])[0]
            exact_date = params.get("exact_date", [""])[0]
            self._send_json(
                MONITOR.journal_day_summary(
                    exact_date=exact_date,
                    source_mode=source_mode,
                    profile_aliases=profile_aliases,
                )
            )
            return
        if parsed.path == "/api/trader-journal-entry":
            profile_aliases = [item.strip() for item in params.get("profile_aliases", [""])[0].split(",") if item.strip()]
            source_mode = params.get("source_mode", ["current"])[0]
            exact_date = params.get("exact_date", [""])[0]
            self._send_json(
                MONITOR.trader_journal_entry(
                    exact_date=exact_date,
                    source_mode=source_mode,
                    profile_aliases=profile_aliases,
                )
            )
            return
        if parsed.path == "/api/analysis":
            self._send_json(
                MONITOR.market_analysis(
                    params.get("symbol", ["XAUUSD"])[0],
                    params.get("timeframe", ["H1"])[0],
                )
            )
            return
        if parsed.path == "/api/market-intel":
            self._send_json(
                MONITOR.market_intel(
                    params.get("symbol", ["XAUUSD"])[0],
                    params.get("timeframe", ["H1"])[0],
                    params.get("session_focus", ["auto"])[0],
                )
            )
            return
        if parsed.path == "/api/chart-data":
            params = parse_qs(parsed.query)
            self._send_json(
                MONITOR.chart_data(
                    params.get("symbol", ["XAUUSD"])[0],
                    params.get("timeframe", ["M1"])[0],
                    params.get("anchor_date", [""])[0],
                    params.get("anchor_time", [""])[0],
                )
            )
            return
        if parsed.path == "/api/consolidation":
            params = parse_qs(parsed.query)
            self._send_json(
                MONITOR.consolidation_data(
                    params.get("symbol", ["XAUUSD"])[0],
                    params.get("timeframe", ["M5"])[0],
                )
            )
            return
        if parsed.path == "/api/markets":
            self._send_json(market_sessions_snapshot())
            return
        if parsed.path == "/api/orl/sessions":
            self._send_json({"success": True, "sessions": ORL_SETTINGS.as_public_dict()["sessions"], "default_session": ORL_SETTINGS.default_session})
            return
        if parsed.path == "/api/orl/symbols":
            self._send_json({"success": True, "symbols": ORL_CANDLE_SERVICE.list_symbols()})
            return
        if parsed.path == "/api/orl/live/status":
            self._send_json({"success": True, "status": MONITOR.orl_live_observer.get_live_status() if MONITOR.orl_live_observer else {"active": False}, "config": ORL_SETTINGS.as_public_dict()})
            return
        if parsed.path == "/api/terminals":
            self._send_json(
                {
                    "terminals": discover_mt5_terminals(),
                    "selected_profile_alias": MONITOR.selected_profile_alias,
                }
            )
            return
        if parsed.path == "/api/security-logins":
            self._send_json(refresh_security_login_cache())
            return
        if parsed.path == "/api/signal-lab/batches":
            self._send_json(SIGNAL_LAB.list_batches())
            return
        if parsed.path == "/api/signal-lab/batch":
            params = parse_qs(parsed.query)
            batch_id = int(params.get("batch_id", ["0"])[0] or 0)
            self._send_json(SIGNAL_LAB.get_batch_payload(batch_id))
            return
        if parsed.path == "/api/signal-lab/chart":
            params = parse_qs(parsed.query)
            signal_call_id = int(params.get("signal_call_id", ["0"])[0] or 0)
            timeframe = params.get("timeframe", ["M5"])[0]
            self._send_json(SIGNAL_LAB.chart_preview(signal_call_id, timeframe))
            return
        if parsed.path == "/api/signal-lab/logs":
            self._send_json(SIGNAL_LAB.list_logs())
            return
        if parsed.path == "/api/signal-lab/symbol-mappings":
            self._send_json(SIGNAL_LAB.get_symbol_mappings())
            return
        if parsed.path == "/api/signal-lab/export":
            params = parse_qs(parsed.query)
            batch_id = int(params.get("batch_id", ["0"])[0] or 0)
            export_type = params.get("type", ["validated_csv"])[0]
            file_name, body, content_type = SIGNAL_LAB.export_dataset(batch_id, export_type)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Disposition", f'attachment; filename="{file_name}"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/api/account-profiles":
            profiles = DB.get_account_profiles()
            self._send_json(
                {
                    "profiles": profiles,
                    "selected_profile_alias": MONITOR.selected_profile_alias,
                }
            )
            return
        if parsed.path == "/api/mt5-journal":
            params = parse_qs(parsed.query)
            profile_aliases = [item.strip() for item in params.get("profile_aliases", [""])[0].split(",") if item.strip()]
            symbols = [item.strip().upper() for item in params.get("symbols", [""])[0].split(",") if item.strip()]
            source_mode = params.get("source_mode", ["current"])[0]
            if source_mode == "profiles" and profile_aliases:
                payload = MONITOR.cached_history_journal(
                    params.get("range", ["today"])[0],
                    params.get("outcome", ["all"])[0],
                    params.get("lot_size", [""])[0],
                    symbols,
                    params.get("special", ["all"])[0],
                    params.get("exact_date", [""])[0],
                    profile_aliases,
                )
            else:
                payload = MONITOR.history_journal(
                    params.get("range", ["today"])[0],
                    params.get("outcome", ["all"])[0],
                    params.get("lot_size", [""])[0],
                    symbols,
                    params.get("special", ["all"])[0],
                    params.get("exact_date", [""])[0],
                )
            self._send_json(payload)
            return
        if parsed.path == "/api/journal":
            params = parse_qs(parsed.query)
            payload = DB.journal(
                range_key=params.get("range", ["today"])[0],
                outcome=params.get("outcome", ["all"])[0],
                lot_size=params.get("lot_size", [""])[0],
                symbols=[item.strip().upper() for item in params.get("symbols", [""])[0].split(",") if item.strip()],
                special_filter=params.get("special", ["all"])[0],
                exact_date=params.get("exact_date", [""])[0],
                account_login=MONITOR.account.get("login"),
                account_server=normalize_account_server(MONITOR.account.get("server")),
            )
            self._send_json(payload)
            return
        if parsed.path == "/api/health":
            self._send_json({"ok": True, "time": iso_now()})
            return
        if parsed.path == "/api/history/symbols":
            self._send_json(HISTORY_BACKFILL.list_symbols())
            return
        if parsed.path == "/api/history/timeframes":
            self._send_json(HISTORY_BACKFILL.list_timeframes())
            return
        if parsed.path == "/api/history/summary":
            self._send_json(HISTORY_BACKFILL.summary())
            return
        if parsed.path.startswith("/api/history/backfill/") and parsed.path.endswith("/status"):
            try:
                job_id = int(parsed.path.split("/")[-2])
            except (TypeError, ValueError):
                self._send_json({"ok": False, "error": "Invalid backfill job id."}, status=HTTPStatus.BAD_REQUEST)
                return
            payload = HISTORY_BACKFILL.get_job_status(job_id)
            status = HTTPStatus.OK if payload.get("ok") else HTTPStatus.NOT_FOUND
            self._send_json(payload, status=status)
            return
        page_routes = {
            "/live": "/live.html",
            "/analysis": "/analysis.html",
            "/historical-data": "/historical_data.html",
            "/market-intel": "/market_intel.html",
            "/playbook": "/playbook.html",
            "/signal-lab": "/signal_lab.html",
            "/charts": "/charts.html",
            "/xau-chart": "/xau_chart.html",
            "/liquidity-sweeps": "/liquidity_sweeps.html",
            "/consolidation": "/consolidation.html",
            "/calculator": "/calculator.html",
            "/risk": "/risk.html",
            "/orl": "/analysis.html",
            "/markets": "/markets.html",
            "/security": "/security.html",
            "/journal": "/journal.html",
            "/tools": "/tools.html",
            "/live.html": "/live.html",
            "/analysis.html": "/analysis.html",
            "/historical_data.html": "/historical_data.html",
            "/market_intel.html": "/market_intel.html",
            "/playbook.html": "/playbook.html",
            "/signal_lab.html": "/signal_lab.html",
            "/charts.html": "/charts.html",
            "/xau_chart.html": "/xau_chart.html",
            "/liquidity_sweeps.html": "/liquidity_sweeps.html",
            "/consolidation.html": "/consolidation.html",
            "/calculator.html": "/calculator.html",
            "/risk.html": "/risk.html",
            "/orl.html": "/analysis.html",
            "/markets.html": "/markets.html",
            "/security.html": "/security.html",
            "/journal.html": "/journal.html",
            "/tools.html": "/tools.html",
        }
        if parsed.path in page_routes:
            self.path = page_routes[parsed.path]
            return super().do_GET()
        if parsed.path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/trader-journal-entry":
            payload = self._read_json_body()
            try:
                entry = DB.save_trader_journal_entry(payload)
            except ValueError as exc:
                self.send_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_json({"ok": True, "entry": entry})
            return
        if parsed.path == "/api/connect":
            payload = self._read_json_body()
            self._send_json(
                MONITOR.reconnect(
                    str(payload.get("profile_alias", "")),
                    str(payload.get("terminal_path", "")),
                    str(payload.get("quick_alias", "")),
                )
            )
            return
        if parsed.path == "/api/disconnect":
            self._read_json_body()
            self._send_json(MONITOR.disconnect())
            return
        if parsed.path == "/api/account-profiles":
            payload = self._read_json_body()
            try:
                profile = DB.upsert_account_profile(payload)
            except ValueError as exc:
                self.send_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            MONITOR.connection_profile = DB.find_account_profile(MONITOR.selected_profile_alias) if MONITOR.selected_profile_alias else MONITOR.connection_profile
            self._send_json(
                {
                    "ok": True,
                    "profile": profile,
                    "profiles": DB.get_account_profiles(),
                    "selected_profile_alias": MONITOR.selected_profile_alias,
                }
            )
            return
        if parsed.path == "/api/account-profiles/delete":
            payload = self._read_json_body()
            deleted = DB.delete_account_profile(str(payload.get("alias", "")))
            if MONITOR.selected_profile_alias and not DB.find_account_profile(MONITOR.selected_profile_alias):
                MONITOR.selected_profile_alias = ""
                MONITOR.connection_profile = None
            self._send_json(
                {
                    "ok": deleted,
                    "profiles": DB.get_account_profiles(),
                    "selected_profile_alias": MONITOR.selected_profile_alias,
                }
            )
            return
        if parsed.path == "/api/import-mt5-history":
            self._read_json_body()
            self._send_json(MONITOR.import_mt5_history())
            return
        if parsed.path == "/api/trade/open":
            payload = self._read_json_body()
            side = str(payload.get("side", ""))
            symbol = str(payload.get("symbol", ""))
            volume = safe_float(payload.get("volume"), 0.0)
            response = MONITOR.open_market_trade(symbol, volume, side)
            status = HTTPStatus.OK if response.get("ok") else (HTTPStatus.LOCKED if response.get("trade_lock_enabled") else HTTPStatus.BAD_REQUEST)
            self._send_json(response, status=status)
            return
        if parsed.path == "/api/trade/close":
            payload = self._read_json_body()
            ticket = int(payload.get("ticket", 0) or 0)
            response = MONITOR.close_position(ticket)
            status = HTTPStatus.OK if response.get("ok") else HTTPStatus.BAD_REQUEST
            self._send_json(response, status=status)
            return
        if parsed.path == "/api/test-email-alert":
            payload = self._read_json_body()
            response = MONITOR.send_test_email_alert(str(payload.get("event_type", "")))
            status = HTTPStatus.OK if response.get("ok") else HTTPStatus.BAD_REQUEST
            self._send_json(response, status=status)
            return
        if parsed.path == "/api/orl/analyze-past-chart":
            payload = self._read_json_body()
            response = ORL_HISTORICAL_ANALYZER.analyze_past_chart(payload)
            status = HTTPStatus.OK if response.get("success") else HTTPStatus.BAD_REQUEST
            self._send_json(response, status=status)
            return
        if parsed.path == "/api/signal-lab/import":
            payload = self._read_json_body()
            try:
                response = SIGNAL_LAB.import_file(str(payload.get("file_name", "")), str(payload.get("content_base64", "")))
                status = HTTPStatus.OK if response.get("ok") else HTTPStatus.BAD_REQUEST
            except Exception as exc:
                print(f"Signal Lab import failure: {exc}")
                traceback.print_exc()
                response = {"ok": False, "message": f"Signal Lab import failed: {exc}"}
                status = HTTPStatus.INTERNAL_SERVER_ERROR
            self._send_json(response, status=status)
            return
        if parsed.path == "/api/signal-lab/import-text":
            payload = self._read_json_body()
            try:
                response = SIGNAL_LAB.import_raw_text(str(payload.get("raw_text", "")), str(payload.get("source_name", "pasted_signals.txt")))
                status = HTTPStatus.OK if response.get("ok") else HTTPStatus.BAD_REQUEST
            except Exception as exc:
                print(f"Signal Lab raw-text import failure: {exc}")
                traceback.print_exc()
                response = {"ok": False, "message": f"Signal Lab raw-text import failed: {exc}"}
                status = HTTPStatus.INTERNAL_SERVER_ERROR
            self._send_json(response, status=status)
            return
        if parsed.path == "/api/signal-lab/import-mt5-logs":
            payload = self._read_json_body()
            try:
                response = SIGNAL_LAB.import_mt5_tester_logs(str(payload.get("terminal_root", r"C:\MT5\JamesANabiah")))
                status = HTTPStatus.OK if response.get("ok") else HTTPStatus.BAD_REQUEST
            except Exception as exc:
                print(f"Signal Lab MT5 tester import failure: {exc}")
                traceback.print_exc()
                response = {"ok": False, "message": f"Signal Lab MT5 tester import failed: {exc}"}
                status = HTTPStatus.INTERNAL_SERVER_ERROR
            self._send_json(response, status=status)
            return
        if parsed.path == "/api/signal-lab/update":
            payload = self._read_json_body()
            try:
                response = SIGNAL_LAB.update_signal(int(payload.get("signal_call_id", 0) or 0), dict(payload.get("updates", {}) or {}))
                status = HTTPStatus.OK if response.get("ok") else HTTPStatus.BAD_REQUEST
            except Exception as exc:
                print(f"Signal Lab update failure: {exc}")
                traceback.print_exc()
                response = {"ok": False, "message": f"Signal Lab update failed: {exc}"}
                status = HTTPStatus.INTERNAL_SERVER_ERROR
            self._send_json(response, status=status)
            return
        if parsed.path == "/api/signal-lab/reset-results":
            payload = self._read_json_body()
            try:
                response = SIGNAL_LAB.reset_results(int(payload.get("batch_id", 0) or 0))
                status = HTTPStatus.OK if response.get("ok") else HTTPStatus.BAD_REQUEST
            except Exception as exc:
                print(f"Signal Lab reset failure: {exc}")
                traceback.print_exc()
                response = {"ok": False, "message": f"Signal Lab reset failed: {exc}"}
                status = HTTPStatus.INTERNAL_SERVER_ERROR
            self._send_json(response, status=status)
            return
        if parsed.path == "/api/signal-lab/clear-batches":
            try:
                response = SIGNAL_LAB.clear_all_batches()
                status = HTTPStatus.OK if response.get("ok") else HTTPStatus.BAD_REQUEST
            except Exception as exc:
                print(f"Signal Lab clear batches failure: {exc}")
                traceback.print_exc()
                response = {"ok": False, "message": f"Signal Lab clear batches failed: {exc}"}
                status = HTTPStatus.INTERNAL_SERVER_ERROR
            self._send_json(response, status=status)
            return
        if parsed.path == "/api/signal-lab/symbol-mappings":
            payload = self._read_json_body()
            try:
                response = SIGNAL_LAB.save_symbol_mappings(list(payload.get("mappings", []) or []))
                status = HTTPStatus.OK if response.get("ok") else HTTPStatus.BAD_REQUEST
            except Exception as exc:
                print(f"Signal Lab symbol mapping save failure: {exc}")
                traceback.print_exc()
                response = {"ok": False, "message": f"Signal Lab symbol mapping save failed: {exc}"}
                status = HTTPStatus.INTERNAL_SERVER_ERROR
            self._send_json(response, status=status)
            return
        if parsed.path == "/api/signal-lab/test-symbol-mapping":
            payload = self._read_json_body()
            try:
                response = SIGNAL_LAB.test_symbol_mapping(str(payload.get("imported_symbol", "")), str(payload.get("broker_symbol", "")))
                status = HTTPStatus.OK if response.get("ok") else HTTPStatus.BAD_REQUEST
            except Exception as exc:
                print(f"Signal Lab symbol mapping test failure: {exc}")
                traceback.print_exc()
                response = {"ok": False, "message": f"Signal Lab symbol mapping test failed: {exc}"}
                status = HTTPStatus.INTERNAL_SERVER_ERROR
            self._send_json(response, status=status)
            return
        if parsed.path == "/api/signal-lab/backtest":
            payload = self._read_json_body()
            try:
                response = SIGNAL_LAB.backtest_batch(int(payload.get("batch_id", 0) or 0), dict(payload.get("settings", {}) or {}))
                status = HTTPStatus.OK if response.get("ok") else HTTPStatus.BAD_REQUEST
            except Exception as exc:
                print(f"Signal Lab backtest failure: {exc}")
                traceback.print_exc()
                response = {"ok": False, "message": f"Signal Lab backtest failed: {exc}"}
                status = HTTPStatus.INTERNAL_SERVER_ERROR
            self._send_json(response, status=status)
            return
        if parsed.path == "/api/history/backfill":
            payload = self._read_json_body()
            response = HISTORY_BACKFILL.start_backfill(payload)
            status = HTTPStatus.OK if response.get("ok") else HTTPStatus.BAD_REQUEST
            self._send_json(response, status=status)
            return
        if parsed.path == "/api/history/clear":
            self._read_json_body()
            response = HISTORY_BACKFILL.clear_all_data()
            status = HTTPStatus.OK if response.get("ok") else HTTPStatus.INTERNAL_SERVER_ERROR
            self._send_json(response, status=status)
            return
        if parsed.path == "/api/email-notifications":
            payload = self._read_json_body()
            enabled = bool(payload.get("enabled", True))
            self._send_json(MONITOR.set_email_notifications_enabled(enabled))
            return
        if parsed.path == "/api/notifications-preferences":
            payload = self._read_json_body()
            enabled = bool(payload.get("notifications_enabled", True))
            preferences = dict(payload.get("alert_type_enabled", {}) or {})
            MONITOR.set_notifications_enabled(enabled)
            response = MONITOR.set_alert_type_preferences(preferences)
            response["notifications_enabled"] = MONITOR.notifications_enabled()
            self._send_json(response)
            return
        if parsed.path == "/api/trade-lock":
            payload = self._read_json_body()
            enabled = bool(payload.get("enabled", False))
            self._send_json(MONITOR.set_trade_lock_enabled(enabled))
            return
        if parsed.path == "/api/clear-db":
            self._read_json_body()
            DB.clear_all()
            MONITOR.reset_runtime_state()
            self._send_json({"ok": True, "message": "Database cleared."})
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = to_json(payload)
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError):
            return

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}


def main() -> None:
    server: ThreadingHTTPServer | None = None
    try:
        refresh_security_login_cache()
        MONITOR.start()
        server = ThreadingHTTPServer((HOST, PORT), AppHandler)
        url = f"http://{HOST}:{PORT}"
        print(f"MetaTrader Trade Observer running at {url}")
        print(f"Database: {DB_PATH}")
        print(f"Python: {sys.executable}")
        print(f"MetaTrader5 available: {'yes' if mt5 is not None else 'no'}")
        print(
            "Security logins cached: "
            f"{SECURITY_LOGIN_CACHE.get('summary', {}).get('authorization_events', 0)} event(s) "
            f"from {SECURITY_LOGIN_CACHE.get('source_root', str(SECURITY_DEFAULT_TERMINAL_ROOT))}"
        )
        print("Open that URL in your browser after this server starts.")
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    except OSError as exc:
        print(f"Server failed to start on {HOST}:{PORT}: {exc}")
        print("If another app is using this port, close it or run with a different MT5_OBSERVER_PORT value.")
        raise
    except Exception as exc:  # pragma: no cover
        print(f"Unexpected startup/runtime failure: {exc}")
        traceback.print_exc()
        raise
    finally:
        if server is not None:
            server.server_close()
        MONITOR.stop()


if __name__ == "__main__":
    main()
