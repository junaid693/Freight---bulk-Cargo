"""Forecast service: merges user-supplied input with stored DB data and logs telemetry.

Strategy:
    User-provided values ALWAYS win. Any field the user omits is filled from
    the database when a recent value is available:
        - weather (wind_kmh, wave_height_m, cyclone_risk, weather_delay_days)
          <- latest weather_data row for the ORIGIN port
        - market (bdi, vlsfo_usd_per_tonne, coal_price_usd_per_mt,
          iron_ore_price_usd_per_dmt) <- latest market_data rows
        - current_freight_usd_per_tonne <- strictly required from the user

If any model-required field is still missing after merging, a structured
ForecastDataError is raised so the API layer can return a clear 422 JSON response.
Zero fabricated values are used.
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Ensure backend root is importable
_THIS_DIR = Path(__file__).resolve().parent
_BACKEND_ROOT = _THIS_DIR.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from data import database
from predict import FEATURES, MODEL_PATH, predict_freight


# Default freshness thresholds
MAX_WEATHER_AGE_HOURS = 24.0
MAX_MARKET_AGE_HOURS = 72.0


class ForecastDataError(ValueError):
    """Structured error for missing or invalid forecast inputs."""

    def __init__(
        self,
        error_code: str,
        message: str,
        missing_fields: list[str] | None = None,
        detail: str | None = None,
    ):
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.missing_fields = missing_fields or []
        self.detail = detail or message


# Fields the model needs that the user is allowed to omit (filled from DB).
DB_FILLABLE = {
    "wind_kmh", "wave_height_m", "cyclone_risk", "weather_delay_days",
    "bdi", "vlsfo_usd_per_tonne", "coal_price_usd_per_mt",
    "iron_ore_price_usd_per_dmt",
}

# Fields the user MUST always provide (identity + current freight).
REQUIRED_FROM_USER = {
    "origin", "destination", "commodity", "vessel_type",
    "current_freight_usd_per_tonne",
}


def _parse_iso_utc(ts_str: str) -> Optional[datetime]:
    """Parse ISO timestamp string into timezone-aware UTC datetime."""
    try:
        clean = ts_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _fill_weather(merged: dict, sources: dict, port: str) -> None:
    weather = database.get_latest_weather(port)
    if not weather:
        return
    mapping = {
        "wind_kmh": weather.get("wind_kmh"),
        "wave_height_m": weather.get("wave_height_m"),
        "cyclone_risk": weather.get("cyclone_risk"),
        "weather_delay_days": weather.get("weather_delay_days"),
    }
    fetched_at = weather.get("fetched_at", "")
    
    # Calculate age and freshness tag
    dt = _parse_iso_utc(fetched_at)
    if dt:
        age_hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
        if age_hours > MAX_WEATHER_AGE_HOURS:
            tag = f"weather_db[{port}@{fetched_at}:STALE({age_hours:.1f}h_old)]"
        else:
            tag = f"weather_db[{port}@{fetched_at}]"
    else:
        tag = f"weather_db[{port}@{fetched_at}]"

    for field, value in mapping.items():
        if value is None:
            continue
        if merged.get(field) is None:
            merged[field] = value
            sources[field] = tag


def _fill_market(merged: dict, sources: dict) -> None:
    market = database.get_latest_market()
    if not market:
        return
    mapping = {
        "bdi": market.get("bdi"),
        "vlsfo_usd_per_tonne": market.get("vlsfo_usd_per_tonne"),
        "coal_price_usd_per_mt": market.get("coal_price_usd_per_mt"),
        "iron_ore_price_usd_per_dmt": market.get("iron_ore_price_usd_per_dmt"),
    }
    for field, quote in mapping.items():
        if quote is None:
            continue
        value = quote.get("value") if isinstance(quote, dict) else None
        if value is None:
            continue
        fetched_at = quote.get("fetched_at", "")
        dt = _parse_iso_utc(fetched_at)
        if dt:
            age_hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
            if age_hours > MAX_MARKET_AGE_HOURS:
                tag = f"market_db[{field}@{fetched_at}:STALE({age_hours:.1f}h_old)]"
            else:
                tag = f"market_db[{field}@{fetched_at}]"
        else:
            tag = f"market_db[{field}@{fetched_at}]"

        if merged.get(field) is None:
            merged[field] = value
            sources[field] = tag


def build_forecast_input(user_input: dict) -> tuple[dict, dict]:
    """Merge user input with stored data and enforce zero-fabrication.

    Returns:
        (merged_input, sources) where sources maps field_name -> provenance string.
    Raises:
        ForecastDataError if any required feature is missing.
    """
    merged: dict = {}
    sources: dict = {}
    for field in FEATURES:
        val = user_input.get(field)
        if val is not None:
            merged[field] = val
            sources[field] = "user"

    # Identity fields must come from user
    missing_identity = [f for f in REQUIRED_FROM_USER if f not in merged or merged[f] is None]
    if missing_identity:
        raise ForecastDataError(
            error_code="INVALID_FORECAST_INPUT",
            message=f"Missing required identity fields: {', '.join(missing_identity)}",
            missing_fields=missing_identity,
            detail="Ensure origin, destination, commodity, vessel_type, and current_freight_usd_per_tonne are provided.",
        )

    # Fill weather from origin port
    _fill_weather(merged, sources, merged["origin"])
    # Fill market data
    _fill_market(merged, sources)

    # Check for missing values and classify error
    missing = [f for f in FEATURES if f not in merged or merged[f] is None]
    if missing:
        market_missing = [f for f in missing if f in {"bdi", "vlsfo_usd_per_tonne", "coal_price_usd_per_mt", "iron_ore_price_usd_per_dmt"}]
        weather_missing = [f for f in missing if f in {"wind_kmh", "wave_height_m", "cyclone_risk", "weather_delay_days"}]

        if market_missing and not weather_missing:
            error_code = "MARKET_DATA_MISSING"
        elif weather_missing and not market_missing:
            error_code = "WEATHER_DATA_MISSING"
        else:
            error_code = "DATA_MISSING"

        raise ForecastDataError(
            error_code=error_code,
            message=f"Missing model inputs that could not be filled from the database: {', '.join(missing)}.",
            missing_fields=missing,
            detail="Provide missing fields in the request or populate the database using `python -m data.update_data`.",
        )

    return merged, sources


def forecast(user_input: dict) -> dict:
    """Build complete input dict, run model inference, and record telemetry log."""
    start_time = time.perf_counter()
    merged, sources = build_forecast_input(user_input)
    result = predict_freight(merged)
    result["sources"] = sources
    latency_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

    # Insert prediction telemetry log (safely, non-blocking)
    database.insert_prediction_log(
        model_version=MODEL_PATH.stem,
        origin=str(merged.get("origin", "")),
        destination=str(merged.get("destination", "")),
        commodity=str(merged.get("commodity", "")),
        vessel_type=str(merged.get("vessel_type", "")),
        current_freight_usd_per_tonne=float(result.get("current_freight_usd_per_tonne", 0.0)),
        predicted_next_month_freight_usd_per_tonne=float(result.get("predicted_next_month_freight_usd_per_tonne", 0.0)),
        forecast_change_percent=float(result.get("forecast_change_percent", 0.0)),
        risk_level=str(result.get("risk_level", "LOW")),
        recommendation=str(result.get("recommendation", "MONITOR")),
        latency_ms=latency_ms,
        provenance=sources,
    )

    return result


def init_data_layer() -> None:
    """Make sure the database exists before serving requests."""
    database.init_db()
