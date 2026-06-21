from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, time as dt_time, timedelta
from typing import Any

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


def utc_now() -> datetime:
    return datetime.now(UTC)


def parse_hhmm(value: str, fallback: str) -> tuple[int, int]:
    raw = (value or fallback).strip()
    hour, minute = raw.split(":", 1)
    return int(hour), int(minute)


@dataclass(frozen=True)
class ORLSessionConfig:
    name: str
    open_hour: int
    open_minute: int

    @property
    def open_label(self) -> str:
        return f"{self.open_hour:02d}:{self.open_minute:02d} UTC"


@dataclass(frozen=True)
class ORLFilterSettings:
    require_m5_close_outside_box: bool = True
    max_distance_from_box_points: float = 60.0
    minimum_breakout_distance_points: float = 30.0
    require_previous_3_candle_direction: bool = True
    max_sl_points: float = 200.0
    minimum_rr: float = 1.2
    max_signals_per_session: int = 1

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> "ORLFilterSettings":
        payload = payload or {}
        return cls(
            require_m5_close_outside_box=bool(payload.get("require_m5_close_outside_box", True)),
            max_distance_from_box_points=safe_float(payload.get("max_distance_from_box_points"), 60.0),
            minimum_breakout_distance_points=safe_float(payload.get("minimum_breakout_distance_points"), 30.0),
            require_previous_3_candle_direction=bool(payload.get("require_previous_3_candle_direction", True)),
            max_sl_points=safe_float(payload.get("max_sl_points"), 200.0),
            minimum_rr=safe_float(payload.get("minimum_rr"), 1.2),
            max_signals_per_session=max(1, int(payload.get("max_signals_per_session", 1) or 1)),
        )


@dataclass(frozen=True)
class ORLSettings:
    enabled: bool = os.environ.get("ORL_ENABLED", "true").strip().lower() != "false"
    default_symbol: str = os.environ.get("ORL_DEFAULT_SYMBOL", "auto").strip() or "auto"
    default_session: str = os.environ.get("ORL_DEFAULT_SESSION", "New York").strip() or "New York"
    atr_period: int = int(os.environ.get("ORL_ATR_PERIOD", "14"))
    atr_threshold_percent: float = safe_float(os.environ.get("ORL_ATR_THRESHOLD_PERCENT", "25"), 25.0)
    box_extension_minutes: int = int(os.environ.get("ORL_BOX_EXTENSION_MINUTES", "180"))
    pre_close_alert_minutes: int = int(os.environ.get("ORL_PRE_CLOSE_ALERT_MINUTES", "5"))
    alert_cooldown_seconds: int = int(os.environ.get("ORL_ALERT_COOLDOWN_SECONDS", "60"))
    sound_enabled: bool = os.environ.get("ORL_SOUND_ENABLED", "true").strip().lower() != "false"
    sound_file: str = os.environ.get("ORL_SOUND_FILE", "assets/sounds/orl_alert.mp3")
    email_enabled: bool = os.environ.get("ORL_EMAIL_ENABLED", "true").strip().lower() != "false"
    timezone_mode: str = "UTC"
    sessions: dict[str, ORLSessionConfig] = field(
        default_factory=lambda: {
            "Sydney": ORLSessionConfig("Sydney", *parse_hhmm(os.environ.get("ORL_SYDNEY_OPEN_UTC", "21:00"), "21:00")),
            "Tokyo": ORLSessionConfig("Tokyo", *parse_hhmm(os.environ.get("ORL_TOKYO_OPEN_UTC", "00:00"), "00:00")),
            "London": ORLSessionConfig("London", *parse_hhmm(os.environ.get("ORL_LONDON_OPEN_UTC", "08:00"), "08:00")),
            "New York": ORLSessionConfig("New York", *parse_hhmm(os.environ.get("ORL_NEW_YORK_OPEN_UTC", "13:00"), "13:00")),
        }
    )

    def as_public_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "default_symbol": self.default_symbol,
            "default_session": self.default_session,
            "atr_period": self.atr_period,
            "atr_threshold_percent": self.atr_threshold_percent,
            "box_extension_minutes": self.box_extension_minutes,
            "pre_close_alert_minutes": self.pre_close_alert_minutes,
            "alert_cooldown_seconds": self.alert_cooldown_seconds,
            "sound_enabled": self.sound_enabled,
            "email_enabled": self.email_enabled,
            "sessions": {
                name: {
                    "name": session.name,
                    "open_hour": session.open_hour,
                    "open_minute": session.open_minute,
                    "open_label": session.open_label,
                }
                for name, session in self.sessions.items()
            },
        }


class MT5CandleService:
    def __init__(self, mt5_module: Any) -> None:
        self.mt5 = mt5_module

    def validate_symbol(self, symbol: str) -> tuple[bool, str]:
        if self.mt5 is None:
            return False, "MetaTrader5 package is not installed."
        info = self.mt5.symbol_info(symbol)
        if info is None:
            return False, "Symbol not found in MetaTrader 5."
        if not getattr(info, "visible", True):
            self.mt5.symbol_select(symbol, True)
        return True, ""

    def list_symbols(self) -> list[str]:
        if self.mt5 is None:
            return []
        symbols = self.mt5.symbols_get() or []
        names = sorted({getattr(item, "name", "") for item in symbols if getattr(item, "name", "")})
        return names

    def get_symbol_info(self, symbol: str) -> Any:
        return self.mt5.symbol_info(symbol) if self.mt5 is not None else None

    def fetch_candles(self, symbol: str, timeframe_code: int, from_dt: datetime, to_dt: datetime) -> list[dict[str, Any]]:
        if self.mt5 is None:
            return []
        rates = self.mt5.copy_rates_range(symbol, timeframe_code, from_dt, to_dt)
        if rates is None:
            return []
        candles: list[dict[str, Any]] = []
        for rate in rates:
            candles.append(
                {
                    "time": datetime.fromtimestamp(int(rate["time"]), UTC).isoformat(),
                    "dt": datetime.fromtimestamp(int(rate["time"]), UTC),
                    "open": safe_float(rate["open"]),
                    "high": safe_float(rate["high"]),
                    "low": safe_float(rate["low"]),
                    "close": safe_float(rate["close"]),
                    "tick_volume": int(rate["tick_volume"]),
                }
            )
        return candles

    def fetch_m15_candles(self, symbol: str, from_dt: datetime, to_dt: datetime) -> list[dict[str, Any]]:
        return self.fetch_candles(symbol, getattr(self.mt5, "TIMEFRAME_M15", 15), from_dt, to_dt)

    def fetch_m5_candles(self, symbol: str, from_dt: datetime, to_dt: datetime) -> list[dict[str, Any]]:
        return self.fetch_candles(symbol, getattr(self.mt5, "TIMEFRAME_M5", 5), from_dt, to_dt)

    def fetch_daily_candles(self, symbol: str, from_dt: datetime, to_dt: datetime) -> list[dict[str, Any]]:
        return self.fetch_candles(symbol, getattr(self.mt5, "TIMEFRAME_D1", 1440), from_dt, to_dt)


class ATRService:
    def calculate_atr(self, daily_candles: list[dict[str, Any]], period: int) -> float | None:
        if len(daily_candles) < period + 1:
            return None
        true_ranges: list[float] = []
        for index in range(1, len(daily_candles)):
            candle = daily_candles[index]
            prev_close = safe_float(daily_candles[index - 1]["close"])
            high = safe_float(candle["high"])
            low = safe_float(candle["low"])
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            true_ranges.append(tr)
        if len(true_ranges) < period:
            return None
        return sum(true_ranges[-period:]) / period


class CandlestickPatternService:
    def classify(self, previous: dict[str, Any] | None, current: dict[str, Any]) -> list[dict[str, str]]:
        patterns: list[dict[str, str]] = []
        open_price = safe_float(current["open"])
        close_price = safe_float(current["close"])
        high = safe_float(current["high"])
        low = safe_float(current["low"])
        body = abs(close_price - open_price)
        candle_range = max(high - low, 0.0000001)
        upper_wick = high - max(open_price, close_price)
        lower_wick = min(open_price, close_price) - low

        if lower_wick >= body * 2 and upper_wick <= body and close_price > open_price:
            patterns.append({"pattern": "Bullish Hammer", "direction": "Buy"})
        if upper_wick >= body * 2 and lower_wick <= body and close_price < open_price:
            patterns.append({"pattern": "Bearish Inverted Hammer / Shooting Star", "direction": "Sell"})

        if previous:
            prev_open = safe_float(previous["open"])
            prev_close = safe_float(previous["close"])
            prev_bearish = prev_close < prev_open
            prev_bullish = prev_close > prev_open
            bullish_engulfing = prev_bearish and close_price > open_price and open_price <= prev_close and close_price >= prev_open
            bearish_engulfing = prev_bullish and close_price < open_price and open_price >= prev_close and close_price <= prev_open
            if bullish_engulfing:
                patterns.append({"pattern": "Bullish Engulfing", "direction": "Buy"})
            if bearish_engulfing:
                patterns.append({"pattern": "Bearish Engulfing", "direction": "Sell"})

        if not patterns and candle_range > 0:
            return []
        return patterns


class ORLProfitCalculator:
    def __init__(self, mt5_module: Any, candle_service: MT5CandleService) -> None:
        self.mt5 = mt5_module
        self.candle_service = candle_service

    def calculate_estimated_profit(
        self,
        symbol: str,
        direction: str,
        volume: float,
        entry_price: float,
        exit_price: float,
    ) -> float:
        if self.mt5 is not None:
            order_type = getattr(self.mt5, "ORDER_TYPE_BUY", 0) if direction.lower() == "buy" else getattr(self.mt5, "ORDER_TYPE_SELL", 1)
            try:
                result = self.mt5.order_calc_profit(order_type, symbol, volume, entry_price, exit_price)
                if result is not None:
                    return safe_float(result)
            except Exception:
                pass

        info = self.candle_service.get_symbol_info(symbol)
        tick_size = safe_float(getattr(info, "trade_tick_size", 0.0) or getattr(info, "point", 0.0), 0.01)
        tick_value = safe_float(getattr(info, "trade_tick_value", 0.0), 0.0)
        contract_size = safe_float(getattr(info, "trade_contract_size", 1.0), 1.0)
        move = exit_price - entry_price if direction.lower() == "buy" else entry_price - exit_price
        if tick_value > 0 and tick_size > 0:
            return (move / tick_size) * tick_value * volume
        return move * contract_size * volume


class ORLValidationService:
    def __init__(self, candle_service: MT5CandleService, settings: ORLSettings) -> None:
        self.candle_service = candle_service
        self.settings = settings

    def validate_symbol(self, symbol: str) -> dict[str, Any]:
        ok, message = self.candle_service.validate_symbol(symbol)
        return {"ok": ok, "message": message or "Symbol validated"}

    def validate_date(self, symbol: str, selected_date: date) -> dict[str, Any]:
        today = utc_now().date()
        if selected_date > today:
            return {"ok": False, "message": "Cannot analyze a future date."}
        is_weekend = selected_date.weekday() >= 5
        if is_weekend and not self._is_crypto_symbol(symbol):
            return {"ok": False, "message": "Market was closed on this date. Please select a weekday."}
        return {"ok": True, "message": "Date validated"}

    def validate_session(self, session_name: str, custom_session_time: dict[str, Any] | None = None) -> dict[str, Any]:
        if session_name == "Custom":
            if not custom_session_time:
                return {"ok": False, "message": "Custom session requires hour and minute."}
            hour = int(custom_session_time.get("hour", -1))
            minute = int(custom_session_time.get("minute", -1))
            if hour < 0 or hour > 23 or minute < 0 or minute > 59:
                return {"ok": False, "message": "Custom session time must use hour 0-23 and minute 0-59."}
            return {"ok": True, "message": "Custom session validated"}
        if session_name not in self.settings.sessions:
            return {"ok": False, "message": "Unknown session selected."}
        return {"ok": True, "message": "Session validated"}

    def validate_market_open(self, candles: list[dict[str, Any]]) -> dict[str, Any]:
        if not candles:
            return {"ok": False, "message": "Market appears closed or data unavailable for this session."}
        return {"ok": True, "message": "Market data available"}

    def validate_balance(self, starting_balance: float) -> dict[str, Any]:
        if starting_balance <= 0:
            return {"ok": False, "message": "Starting balance must be greater than 0."}
        return {"ok": True, "message": "Balance validated"}

    def validate_lot_size(self, symbol: str, lot_size: float) -> dict[str, Any]:
        info = self.candle_service.get_symbol_info(symbol)
        if info is None:
            return {"ok": False, "message": "Symbol not found in MetaTrader 5."}
        min_lot = safe_float(getattr(info, "volume_min", 0.01), 0.01)
        max_lot = safe_float(getattr(info, "volume_max", 100.0), 100.0)
        if lot_size < min_lot or lot_size > max_lot:
            return {"ok": False, "message": f"Lot size invalid. Broker min/max: {min_lot} / {max_lot}.", "min": min_lot, "max": max_lot}
        return {"ok": True, "message": "Lot size validated", "min": min_lot, "max": max_lot}

    def _is_crypto_symbol(self, symbol: str) -> bool:
        upper = symbol.upper()
        return any(token in upper for token in ("BTC", "ETH", "SOL", "XRP", "DOGE", "CRYPTO"))


class ORLAnalysisService:
    timeframe_map = {
        "M5": getattr(mt5, "TIMEFRAME_M5", 5) if mt5 is not None else 5,
        "M15": getattr(mt5, "TIMEFRAME_M15", 15) if mt5 is not None else 15,
        "D1": getattr(mt5, "TIMEFRAME_D1", 1440) if mt5 is not None else 1440,
    }

    def __init__(
        self,
        settings: ORLSettings,
        candle_service: MT5CandleService,
        atr_service: ATRService,
        pattern_service: CandlestickPatternService,
        calculator: ORLProfitCalculator,
        validation: ORLValidationService,
    ) -> None:
        self.settings = settings
        self.candle_service = candle_service
        self.atr_service = atr_service
        self.pattern_service = pattern_service
        self.calculator = calculator
        self.validation = validation

    def validate_symbol(self, symbol: str) -> dict[str, Any]:
        return self.validation.validate_symbol(symbol)

    def validate_date(self, symbol: str, selected_date: date) -> dict[str, Any]:
        return self.validation.validate_date(symbol, selected_date)

    def validate_session(self, session_name: str, custom_session_time: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.validation.validate_session(session_name, custom_session_time)

    def fetch_m15_candles(self, symbol: str, from_dt: datetime, to_dt: datetime) -> list[dict[str, Any]]:
        return self.candle_service.fetch_m15_candles(symbol, from_dt, to_dt)

    def fetch_m5_candles(self, symbol: str, from_dt: datetime, to_dt: datetime) -> list[dict[str, Any]]:
        return self.candle_service.fetch_m5_candles(symbol, from_dt, to_dt)

    def fetch_daily_candles(self, symbol: str, from_dt: datetime, to_dt: datetime) -> list[dict[str, Any]]:
        return self.candle_service.fetch_daily_candles(symbol, from_dt, to_dt)

    def calculate_atr(self, daily_candles: list[dict[str, Any]], period: int) -> float | None:
        return self.atr_service.calculate_atr(daily_candles, period)

    def capture_opening_range(self, session_open: datetime, m15_candles: list[dict[str, Any]]) -> dict[str, Any] | None:
        for candle in m15_candles:
            candle_dt = candle["dt"]
            if candle_dt >= session_open:
                return {
                    "open_time": candle_dt.isoformat(),
                    "close_time": (candle_dt + timedelta(minutes=15)).isoformat(),
                    "high": safe_float(candle["high"]),
                    "low": safe_float(candle["low"]),
                    "size": safe_float(candle["high"]) - safe_float(candle["low"]),
                }
        return None

    def confirm_manipulation(self, opening_range: dict[str, Any], atr_value: float, atr_threshold_percent: float) -> dict[str, Any]:
        threshold_value = atr_value * (atr_threshold_percent / 100.0)
        size = safe_float(opening_range.get("size"))
        passed = size >= threshold_value
        return {
            "passed": passed,
            "opening_range_size": size,
            "atr_value": atr_value,
            "threshold_percent": atr_threshold_percent,
            "threshold_value": threshold_value,
            "formula": f"{size:.3f} >= {atr_value:.3f} * {atr_threshold_percent / 100:.2f}",
        }

    def detect_breakout(self, opening_range: dict[str, Any], m5_candles: list[dict[str, Any]], filters: ORLFilterSettings, point: float) -> dict[str, Any]:
        high = safe_float(opening_range["high"])
        low = safe_float(opening_range["low"])
        breakout = {"detected": False, "direction": "", "candle": None, "distance_points": 0.0}
        for candle in m5_candles:
            close_price = safe_float(candle["close"])
            high_price = safe_float(candle["high"])
            low_price = safe_float(candle["low"])
            if close_price > high:
                distance_points = (close_price - high) / point if point else close_price - high
                if not filters.require_m5_close_outside_box or distance_points >= filters.minimum_breakout_distance_points:
                    breakout = {"detected": True, "direction": "above", "candle": candle, "distance_points": distance_points}
                    break
            if close_price < low:
                distance_points = (low - close_price) / point if point else low - close_price
                if not filters.require_m5_close_outside_box or distance_points >= filters.minimum_breakout_distance_points:
                    breakout = {"detected": True, "direction": "below", "candle": candle, "distance_points": distance_points}
                    break
            if high_price > high:
                distance_points = (high_price - high) / point if point else high_price - high
                if not filters.require_m5_close_outside_box and distance_points >= filters.minimum_breakout_distance_points:
                    breakout = {"detected": True, "direction": "above", "candle": candle, "distance_points": distance_points}
                    break
            if low_price < low:
                distance_points = (low - low_price) / point if point else low - low_price
                if not filters.require_m5_close_outside_box and distance_points >= filters.minimum_breakout_distance_points:
                    breakout = {"detected": True, "direction": "below", "candle": candle, "distance_points": distance_points}
                    break
        return breakout

    def detect_reversal_patterns(
        self,
        opening_range: dict[str, Any],
        breakout: dict[str, Any],
        m5_candles: list[dict[str, Any]],
        filters: ORLFilterSettings,
        point: float,
    ) -> dict[str, Any]:
        if not breakout.get("detected"):
            return {"detected": False, "pattern": "", "direction": "", "candle": None}
        high = safe_float(opening_range["high"])
        low = safe_float(opening_range["low"])
        breakout_time = breakout["candle"]["dt"]
        previous: dict[str, Any] | None = None
        matching_signals = 0
        for candle in m5_candles:
            candle_dt = candle["dt"]
            if candle_dt <= breakout_time:
                previous = candle
                continue
            patterns = self.pattern_service.classify(previous, candle)
            previous = candle
            if not patterns:
                continue
            close_price = safe_float(candle["close"])
            for pattern in patterns:
                direction = pattern["direction"]
                if breakout["direction"] == "below" and direction != "Buy":
                    continue
                if breakout["direction"] == "above" and direction != "Sell":
                    continue
                distance_from_box = abs(close_price - (low if breakout["direction"] == "below" else high)) / point if point else abs(close_price - (low if breakout["direction"] == "below" else high))
                if distance_from_box > filters.max_distance_from_box_points:
                    continue
                matching_signals += 1
                if matching_signals > filters.max_signals_per_session:
                    return {"detected": False, "pattern": "", "direction": "", "candle": None, "reason": "Max signals per session reached"}
                return {
                    "detected": True,
                    "pattern": pattern["pattern"],
                    "direction": direction,
                    "candle": candle,
                    "distance_from_box_points": distance_from_box,
                }
        return {"detected": False, "pattern": "", "direction": "", "candle": None}

    def calculate_entry_sl_tp(
        self,
        symbol: str,
        opening_range: dict[str, Any],
        breakout: dict[str, Any],
        pattern_hit: dict[str, Any],
        filters: ORLFilterSettings,
        point: float,
    ) -> dict[str, Any]:
        if not pattern_hit.get("detected"):
            return {"valid": False, "reason": "No valid reversal pattern detected."}
        candle = pattern_hit["candle"]
        direction = pattern_hit["direction"]
        entry = safe_float(candle["close"])
        range_high = safe_float(opening_range["high"])
        range_low = safe_float(opening_range["low"])
        if direction == "Buy":
            stop_loss = safe_float(candle["low"])
            take_profit = range_high
        else:
            stop_loss = safe_float(candle["high"])
            take_profit = range_low
        risk_distance = abs(entry - stop_loss)
        reward_distance = abs(take_profit - entry)
        sl_points = risk_distance / point if point else risk_distance
        rr_ratio = reward_distance / risk_distance if risk_distance > 0 else 0.0
        if sl_points > filters.max_sl_points:
            return {"valid": False, "reason": "Suggested SL is too large.", "entry": entry, "stop_loss": stop_loss, "take_profit": take_profit}
        if rr_ratio < filters.minimum_rr:
            return {"valid": False, "reason": "RR ratio is below the minimum threshold.", "entry": entry, "stop_loss": stop_loss, "take_profit": take_profit}
        return {
            "valid": True,
            "direction": direction,
            "entry": entry,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "risk_distance": risk_distance,
            "reward_distance": reward_distance,
            "rr_ratio": rr_ratio,
            "sl_points": sl_points,
        }

    def simulate_trade_outcome(self, direction: str, entry: float, stop_loss: float, take_profit: float, candles: list[dict[str, Any]]) -> dict[str, Any]:
        for candle in candles:
            high = safe_float(candle["high"])
            low = safe_float(candle["low"])
            if direction == "Buy":
                if low <= stop_loss:
                    return {"outcome": "SL hit", "exit_price": stop_loss, "exit_time": candle["time"]}
                if high >= take_profit:
                    return {"outcome": "TP hit", "exit_price": take_profit, "exit_time": candle["time"]}
            else:
                if high >= stop_loss:
                    return {"outcome": "SL hit", "exit_price": stop_loss, "exit_time": candle["time"]}
                if low <= take_profit:
                    return {"outcome": "TP hit", "exit_price": take_profit, "exit_time": candle["time"]}
        return {"outcome": "Neither hit during session window", "exit_price": safe_float(candles[-1]["close"]) if candles else entry, "exit_time": candles[-1]["time"] if candles else ""}

    def calculate_estimated_profit(self, symbol: str, direction: str, lot_size: float, entry: float, exit_price: float) -> float:
        return self.calculator.calculate_estimated_profit(symbol, direction, lot_size, entry, exit_price)

    def build_chart_annotations(
        self,
        session_open: datetime,
        opening_range: dict[str, Any] | None,
        manipulation: dict[str, Any] | None,
        breakout: dict[str, Any] | None,
        pattern_hit: dict[str, Any] | None,
        trade_plan: dict[str, Any] | None,
        outcome: dict[str, Any] | None,
        settings: ORLSettings,
    ) -> list[dict[str, Any]]:
        annotations: list[dict[str, Any]] = [
            {"type": "session_open", "time": session_open.isoformat(), "label": "Session Open"},
        ]
        if opening_range:
            annotations.extend(
                [
                    {
                        "type": "opening_range_box",
                        "start_time": opening_range["open_time"],
                        "end_time": (datetime.fromisoformat(opening_range["close_time"]) + timedelta(minutes=settings.box_extension_minutes)).isoformat(),
                        "high": opening_range["high"],
                        "low": opening_range["low"],
                        "label": "Opening Range",
                    },
                    {"type": "line", "price": opening_range["high"], "label": "Opening Range High"},
                    {"type": "line", "price": opening_range["low"], "label": "Opening Range Low"},
                ]
            )
        if manipulation:
            annotations.append({"type": "badge", "label": "Manipulation Confirmed" if manipulation["passed"] else "Manipulation Failed"})
        if breakout and breakout.get("detected"):
            annotations.append({"type": "marker", "time": breakout["candle"]["time"], "price": breakout["candle"]["close"], "label": f"Breakout {breakout['direction']}"})
        if pattern_hit and pattern_hit.get("detected"):
            annotations.append({"type": "marker", "time": pattern_hit["candle"]["time"], "price": pattern_hit["candle"]["close"], "label": pattern_hit["pattern"]})
        if trade_plan and trade_plan.get("valid"):
            annotations.extend(
                [
                    {"type": "line", "price": trade_plan["entry"], "label": "Suggested Entry"},
                    {"type": "line", "price": trade_plan["stop_loss"], "label": "Stop Loss"},
                    {"type": "line", "price": trade_plan["take_profit"], "label": "Take Profit"},
                    {"type": "arrow", "price": trade_plan["entry"], "label": trade_plan["direction"]},
                ]
            )
        if outcome:
            annotations.append({"type": "result", "time": outcome.get("exit_time"), "price": outcome.get("exit_price"), "label": outcome.get("outcome", "No trigger")})
        return annotations

    def build_analysis_response(self, result: dict[str, Any]) -> dict[str, Any]:
        return {"success": True, "message": "Analysis completed", **result}

    def _session_datetime(self, target_date: date, session_name: str, custom_session_time: dict[str, Any] | None) -> tuple[datetime, ORLSessionConfig]:
        if session_name == "Custom":
            config = ORLSessionConfig("Custom", int(custom_session_time["hour"]), int(custom_session_time["minute"]))
        else:
            config = self.settings.sessions[session_name]
        return datetime.combine(target_date, dt_time(config.open_hour, config.open_minute), tzinfo=UTC), config

    def analyze(self, payload: dict[str, Any], *, live_mode: bool = False) -> dict[str, Any]:
        logs: list[str] = ["ORL-25: Historical analysis started" if not live_mode else "ORL-25: Live observer cycle started"]
        symbol = str(payload.get("symbol") or self.settings.default_symbol or "").strip()
        if symbol.lower() == "auto" or not symbol:
            available = self.candle_service.list_symbols()
            symbol = next((item for item in available if item.upper().startswith("XAUUSD")), available[0] if available else "")
        session_name = str(payload.get("session") or self.settings.default_session)
        timezone_mode = str(payload.get("timezone_mode") or self.settings.timezone_mode)
        atr_period = int(payload.get("atr_period", self.settings.atr_period) or self.settings.atr_period)
        atr_threshold_percent = safe_float(payload.get("atr_threshold_percent"), self.settings.atr_threshold_percent)
        box_extension_minutes = int(payload.get("box_extension_minutes", self.settings.box_extension_minutes) or self.settings.box_extension_minutes)
        lot_size = safe_float(payload.get("lot_size"), 0.01)
        starting_balance = safe_float(payload.get("starting_balance"), 100.0)
        risk_mode = str(payload.get("risk_mode") or "Fixed lot")
        filters = ORLFilterSettings.from_payload(payload.get("filters"))
        custom_session_time = payload.get("custom_session_time")
        selected_date = datetime.strptime(str(payload.get("date") or utc_now().date().isoformat()), "%Y-%m-%d").date()

        symbol_validation = self.validate_symbol(symbol)
        logs.append(f"ORL-25: {symbol_validation['message']}")
        if not symbol_validation["ok"]:
            return {"success": False, "message": symbol_validation["message"], "logs": logs}

        date_validation = self.validate_date(symbol, selected_date)
        logs.append(f"ORL-25: {date_validation['message']}")
        if not date_validation["ok"]:
            return {"success": False, "message": date_validation["message"], "logs": logs}

        session_validation = self.validate_session(session_name, custom_session_time)
        logs.append(f"ORL-25: {session_validation['message']}")
        if not session_validation["ok"]:
            return {"success": False, "message": session_validation["message"], "logs": logs}

        balance_validation = self.validation.validate_balance(starting_balance)
        logs.append(f"ORL-25: {balance_validation['message']}")
        if not balance_validation["ok"]:
            return {"success": False, "message": balance_validation["message"], "logs": logs}

        lot_validation = self.validation.validate_lot_size(symbol, lot_size)
        logs.append(f"ORL-25: {lot_validation['message']}")
        if not lot_validation["ok"]:
            return {"success": False, "message": lot_validation["message"], "logs": logs}

        session_open_dt, session_config = self._session_datetime(selected_date, session_name, custom_session_time)
        pre_close_alert_time = session_open_dt + timedelta(minutes=15 - self.settings.pre_close_alert_minutes)
        first_m15_close = session_open_dt + timedelta(minutes=15)
        analysis_end = first_m15_close + timedelta(minutes=box_extension_minutes)

        m15_from = session_open_dt - timedelta(minutes=30)
        m15_to = first_m15_close + timedelta(minutes=30)
        m5_from = first_m15_close
        m5_to = analysis_end
        daily_from = session_open_dt - timedelta(days=atr_period + 25)
        daily_to = session_open_dt + timedelta(days=1)

        m15_candles = self.fetch_m15_candles(symbol, m15_from, m15_to)
        logs.append(f"ORL-25: M15 candles fetched ({len(m15_candles)})")
        market_validation = self.validation.validate_market_open(m15_candles)
        logs.append(f"ORL-25: {market_validation['message']}")
        if not market_validation["ok"]:
            return {"success": False, "message": market_validation["message"], "logs": logs}

        m5_candles = self.fetch_m5_candles(symbol, m5_from, m5_to)
        daily_candles = self.fetch_daily_candles(symbol, daily_from, daily_to)
        logs.append(f"ORL-25: M5 candles fetched ({len(m5_candles)})")
        logs.append(f"ORL-25: Daily candles fetched ({len(daily_candles)})")

        if len(daily_candles) < atr_period + 1:
            message = f"Not enough daily data to calculate ATR({atr_period})."
            logs.append(f"ORL-25: {message}")
            return {"success": False, "message": message, "logs": logs}

        opening_range = self.capture_opening_range(session_open_dt, m15_candles)
        if not opening_range:
            message = "No candle data found for this symbol/date/session. Check symbol name or broker history."
            logs.append(f"ORL-25: {message}")
            return {"success": False, "message": message, "logs": logs}
        logs.append("ORL-25: Opening range captured")

        atr_value = self.calculate_atr(daily_candles, atr_period)
        if atr_value is None:
            message = f"Not enough daily data to calculate ATR({atr_period})."
            logs.append(f"ORL-25: {message}")
            return {"success": False, "message": message, "logs": logs}
        logs.append("ORL-25: ATR calculated")

        manipulation = self.confirm_manipulation(opening_range, atr_value, atr_threshold_percent)
        logs.append(f"ORL-25: Manipulation {'confirmed' if manipulation['passed'] else 'not confirmed'}")

        point = safe_float(getattr(self.candle_service.get_symbol_info(symbol), "point", 0.01), 0.01)
        breakout = self.detect_breakout(opening_range, m5_candles, filters, point) if manipulation["passed"] else {"detected": False, "direction": "", "candle": None}
        logs.append("ORL-25: Breakout detected" if breakout.get("detected") else "ORL-25: Breakout not detected")

        pattern_hit = self.detect_reversal_patterns(opening_range, breakout, m5_candles, filters, point) if breakout.get("detected") else {"detected": False, "pattern": "", "direction": "", "candle": None}
        logs.append("ORL-25: Pattern detected" if pattern_hit.get("detected") else "ORL-25: Pattern not detected")

        trade_plan = self.calculate_entry_sl_tp(symbol, opening_range, breakout, pattern_hit, filters, point)
        if not trade_plan.get("valid"):
            final_reason = trade_plan.get("reason") or ("No valid ORL-25 setup. Opening range was not at least 25% of Daily ATR." if not manipulation["passed"] else "No valid reversal pattern after breakout.")
            outcome = {"outcome": "No trigger", "exit_price": 0.0, "exit_time": ""}
        else:
            outcome = self.simulate_trade_outcome(trade_plan["direction"], trade_plan["entry"], trade_plan["stop_loss"], trade_plan["take_profit"], m5_candles)
            logs.append("ORL-25: Outcome simulated")
            final_reason = f"Valid {trade_plan['direction'].upper()} signal detected"

        estimated_tp_profit = self.calculate_estimated_profit(symbol, trade_plan.get("direction", "Buy"), lot_size, trade_plan.get("entry", 0.0), trade_plan.get("take_profit", trade_plan.get("entry", 0.0))) if trade_plan.get("valid") else 0.0
        estimated_sl_loss = self.calculate_estimated_profit(symbol, trade_plan.get("direction", "Buy"), lot_size, trade_plan.get("entry", 0.0), trade_plan.get("stop_loss", trade_plan.get("entry", 0.0))) if trade_plan.get("valid") else 0.0
        estimated_outcome = self.calculate_estimated_profit(symbol, trade_plan.get("direction", "Buy"), lot_size, trade_plan.get("entry", 0.0), outcome.get("exit_price", trade_plan.get("entry", 0.0))) if trade_plan.get("valid") else 0.0

        chart_annotations = self.build_chart_annotations(session_open_dt, opening_range, manipulation, breakout, pattern_hit, trade_plan, outcome, self.settings)
        details = {
            "selected_symbol": symbol,
            "session_name": session_name,
            "session_open_time": session_config.open_label,
            "timezone_mode": timezone_mode,
            "first_m15_open_time": opening_range["open_time"],
            "first_m15_close_time": opening_range["close_time"],
            "pre_close_alert_time": pre_close_alert_time.isoformat(),
            "opening_range_high": opening_range["high"],
            "opening_range_low": opening_range["low"],
            "opening_range_size": opening_range["size"],
            "daily_atr_period": atr_period,
            "daily_atr_value": atr_value,
            "atr_threshold_percentage": atr_threshold_percent,
            "atr_threshold_value": manipulation["threshold_value"],
            "manipulation_formula": "Opening Range Size >= ATR * threshold",
            "manipulation_result": "Passed" if manipulation["passed"] else "Failed",
            "weekend_validation_result": date_validation["message"],
            "market_closed_validation_result": market_validation["message"],
            "candle_availability_validation": "Passed" if m15_candles and daily_candles else "Failed",
            "m15_candles_fetched_count": len(m15_candles),
            "m5_candles_fetched_count": len(m5_candles),
            "daily_candles_fetched_count": len(daily_candles),
            "breakout_status": "Detected" if breakout.get("detected") else "Not detected",
            "breakout_direction": breakout.get("direction", ""),
            "pattern_detected": pattern_hit.get("pattern", ""),
            "pattern_validation_result": "Passed" if pattern_hit.get("detected") else "Failed",
            "entry_price": trade_plan.get("entry", 0.0),
            "stop_loss": trade_plan.get("stop_loss", 0.0),
            "take_profit": trade_plan.get("take_profit", 0.0),
            "risk_distance": trade_plan.get("risk_distance", 0.0),
            "reward_distance": trade_plan.get("reward_distance", 0.0),
            "rr_ratio": trade_plan.get("rr_ratio", 0.0),
            "spread_validation": "Not enforced",
            "sl_size_validation": trade_plan.get("reason", "Passed") if not trade_plan.get("valid") else "Passed",
            "rr_validation": trade_plan.get("reason", "Passed") if not trade_plan.get("valid") else "Passed",
            "final_signal_status": "Valid signal" if trade_plan.get("valid") else "No valid signal",
            "final_reason": final_reason,
        }

        result = {
            "symbol": symbol,
            "date": selected_date.isoformat(),
            "session": session_name,
            "session_open": session_config.open_label,
            "timezone_mode": timezone_mode,
            "filters": asdict(filters),
            "opening_range": opening_range,
            "atr": {
                "period": atr_period,
                "value": atr_value,
                "threshold_percent": atr_threshold_percent,
                "threshold_value": manipulation["threshold_value"],
            },
            "manipulation": manipulation,
            "signal": {
                "breakout": breakout,
                "pattern": pattern_hit,
                "status": "Valid signal" if trade_plan.get("valid") else "No valid signal",
            },
            "trade_plan": trade_plan,
            "outcome": outcome,
            "profit_loss": {
                "estimated_tp_profit": estimated_tp_profit,
                "estimated_sl_loss": estimated_sl_loss,
                "estimated_result": estimated_outcome,
                "starting_balance": starting_balance,
                "lot_size": lot_size,
                "risk_mode": risk_mode,
            },
            "chart_candles": {
                "m15": [
                    {key: value for key, value in candle.items() if key != "dt"}
                    for candle in m15_candles
                ],
                "m5": [
                    {key: value for key, value in candle.items() if key != "dt"}
                    for candle in m5_candles
                ],
            },
            "chart_annotations": chart_annotations,
            "details": details,
            "logs": logs + ["ORL-25: Historical analysis completed" if not live_mode else "ORL-25: Live observer cycle completed"],
        }
        return self.build_analysis_response(result)


class ORLHistoricalAnalyzerService:
    def __init__(self, engine: ORLAnalysisService) -> None:
        self.engine = engine

    def analyze_past_chart(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.engine.analyze(payload, live_mode=False)


class GmailNotificationService:
    def __init__(self, send_callback: Any, enabled_callback: Any) -> None:
        self.send_callback = send_callback
        self.enabled_callback = enabled_callback

    def send(self, subject: str, body: str) -> None:
        if not self.enabled_callback():
            return
        self.send_callback(subject, body)


class SoundAlertService:
    def __init__(self, play_callback: Any, enabled: bool = True) -> None:
        self.play_callback = play_callback
        self.enabled = enabled

    def play(self, sound_name: str) -> None:
        if self.enabled:
            self.play_callback(sound_name)


class ORLAlertService:
    def __init__(self, dashboard_callback: Any, sound_service: SoundAlertService, gmail_service: GmailNotificationService, settings: ORLSettings) -> None:
        self.dashboard_callback = dashboard_callback
        self.sound_service = sound_service
        self.gmail_service = gmail_service
        self.settings = settings

    def send_orl_alert(self, event_type: str, message: str, payload: dict[str, Any]) -> None:
        self.dashboard_callback(event_type, message, payload)
        if self.settings.sound_enabled:
            self.sound_service.play("warning")
        if self.settings.email_enabled:
            body = "\n".join([message, "", *[f"{key}: {value}" for key, value in payload.items()]])
            self.gmail_service.send(f"ORL-25 Alert: {event_type}", body)


class ORLLiveObserverService:
    def __init__(self, engine: ORLAnalysisService, alerts: ORLAlertService, settings: ORLSettings) -> None:
        self.engine = engine
        self.alerts = alerts
        self.settings = settings
        self.last_status: dict[str, Any] = {"active": False, "message": "ORL live observer idle", "events": [], "analysis": None}
        self._sent_keys: set[str] = set()

    def get_live_status(self) -> dict[str, Any]:
        return self.last_status

    def poll(self, symbol: str, selected_session: str | None = None) -> dict[str, Any]:
        if not self.settings.enabled or not symbol:
            self.last_status = {"active": False, "message": "ORL-25 disabled or no symbol selected.", "events": [], "analysis": None}
            return self.last_status

        current = utc_now()
        session_name = selected_session or self.settings.default_session
        session = self.settings.sessions.get(session_name, self.settings.sessions[self.settings.default_session])
        session_open = datetime.combine(current.date(), dt_time(session.open_hour, session.open_minute), tzinfo=UTC)
        first_close = session_open + timedelta(minutes=15)
        pre_close = first_close - timedelta(minutes=self.settings.pre_close_alert_minutes)

        payload = {
            "symbol": symbol,
            "date": current.date().isoformat(),
            "session": session_name,
            "timezone_mode": "UTC",
            "atr_period": self.settings.atr_period,
            "atr_threshold_percent": self.settings.atr_threshold_percent,
            "box_extension_minutes": self.settings.box_extension_minutes,
            "lot_size": 0.01,
            "starting_balance": 100.0,
            "filters": asdict(ORLFilterSettings()),
        }
        analysis = self.engine.analyze(payload, live_mode=True)
        events: list[dict[str, Any]] = []

        if current >= pre_close and current < first_close:
            key = f"preclose::{symbol}::{session_name}::{current.date().isoformat()}"
            if key not in self._sent_keys:
                self._sent_keys.add(key)
                message = f"ORL-25 pre-close alert for {symbol} {session_name}: first M15 candle closes in 5 minutes."
                event = {"event_type": "orl_pre_close_alert", "message": message}
                self.alerts.send_orl_alert(event["event_type"], message, {"symbol": symbol, "session": session_name})
                events.append(event)

        if analysis.get("success"):
            details = analysis.get("details", {})
            if current >= first_close:
                range_key = f"range::{symbol}::{session_name}::{current.date().isoformat()}"
                if range_key not in self._sent_keys:
                    self._sent_keys.add(range_key)
                    message = f"ORL-25 opening range captured for {symbol} {session_name}."
                    self.alerts.send_orl_alert("orl_range_captured", message, {"symbol": symbol, "session": session_name, "high": details.get("opening_range_high"), "low": details.get("opening_range_low")})
                    events.append({"event_type": "orl_range_captured", "message": message})

            if analysis["manipulation"]["passed"]:
                key = f"manip::{symbol}::{session_name}::{current.date().isoformat()}"
                if key not in self._sent_keys:
                    self._sent_keys.add(key)
                    message = f"ORL-25 manipulation confirmed for {symbol} {session_name}."
                    self.alerts.send_orl_alert("orl_manipulation_confirmed", message, {"symbol": symbol, "session": session_name})
                    events.append({"event_type": "orl_manipulation_confirmed", "message": message})

            breakout = analysis["signal"]["breakout"]
            if breakout.get("detected"):
                key = f"breakout::{symbol}::{session_name}::{current.date().isoformat()}"
                if key not in self._sent_keys:
                    self._sent_keys.add(key)
                    message = f"ORL-25 breakout detected {breakout.get('direction')} for {symbol}."
                    self.alerts.send_orl_alert("orl_breakout_detected", message, {"symbol": symbol, "session": session_name, "direction": breakout.get("direction")})
                    events.append({"event_type": "orl_breakout_detected", "message": message})

            pattern = analysis["signal"]["pattern"]
            if pattern.get("detected") and analysis["trade_plan"].get("valid"):
                key = f"signal::{symbol}::{session_name}::{current.date().isoformat()}"
                if key not in self._sent_keys:
                    self._sent_keys.add(key)
                    message = f"ORL-25 {pattern.get('direction')} signal detected on {symbol}: {pattern.get('pattern')}."
                    self.alerts.send_orl_alert(
                        "orl_signal_detected",
                        message,
                        {
                            "symbol": symbol,
                            "session": session_name,
                            "pattern": pattern.get("pattern"),
                            "direction": analysis["trade_plan"].get("direction"),
                            "entry": analysis["trade_plan"].get("entry"),
                            "stop_loss": analysis["trade_plan"].get("stop_loss"),
                            "take_profit": analysis["trade_plan"].get("take_profit"),
                            "risk_distance": analysis["trade_plan"].get("risk_distance"),
                            "reward_distance": analysis["trade_plan"].get("reward_distance"),
                        },
                    )
                    events.append({"event_type": "orl_signal_detected", "message": message})

        self.last_status = {
            "active": True,
            "message": "ORL live observer running",
            "events": events,
            "analysis": analysis,
            "symbol": symbol,
            "session": session_name,
        }
        return self.last_status
