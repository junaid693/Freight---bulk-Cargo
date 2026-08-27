"""Forecast service: merges user-supplied input with stored DB data.

Strategy:
    User-provided values ALWAYS win. Any field the user omits is filled from
    the database when a recent value is available:
        - weather (wind_kmh, wave_height_m, cyclone_risk, weather_delay_days)
          <- latest weather_data row for the ORIGIN port
        - market (bdi, vlsfo_usd_per_tonne, coal_price_usd_per_mt,
          iron_ore_price_usd_per_dmt) <- latest market_data rows
        - current_freight_usd_per_tonne <- latest freight_observation row
          matching the route (origin/destination/commodity/vessel_type)

If any model-required field is still missing after merging, a ValueError is
raised listing the missing fields so the API layer can return a clear 4xx.
"""

from __future__ import annotations

from typing import Optional

import sys
from pathlib import Path

# Ensure the backend root is importable when the service is used from main.py.
_THIS_DIR = Path(__file__).resolve().parent
_BACKEND_ROOT = _THIS_DIR.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from data import database
from predict import FEATURES, predict_freight


# Fields the model needs but that the user is allowed to omit (filled from DB).
DB_FILLABLE = {
    "wind_kmh", "wave_height_m", "cyclone_risk", "weather_delay_days",
    "bdi", "vlsfo_usd_per_tonne", "coal_price_usd_per_mt",
    "iron_ore_price_usd_per_dmt", "current_freight_usd_per_tonne",
}

# Fields the user MUST always provide (identity of the forecast scenario).
REQUIRED_FROM_USER = {
    "origin", "destination", "commodity", "vessel_type", "cargo_tonnes",
}


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
    fetched_at = weather.get("fetched_at")
    for field, value in mapping.items():
        if value is None:
            continue
        if merged.get(field) is None:
            merged[field] = value
            sources[field] = f"weather_db[{port}@{fetched_at}]"


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
        if merged.get(field) is None:
            merged[field] = value
            sources[field] = f"market_db[{field}@{quote.get('fetched_at')}]"


def _fill_freight(merged: dict, sources: dict) -> None:
    obs = database.get_latest_freight_observation(
        origin=merged["origin"],
        destination=merged["destination"],
        commodity=merged["commodity"],
        vessel_type=merged["vessel_type"],
    )
    if not obs:
        return
    value = obs.get("current_freight_usd_per_tonne")
    if value is None:
        return
    if merged.get("current_freight_usd_per_tonne") is None:
        merged["current_freight_usd_per_tonne"] = value
        sources["current_freight_usd_per_tonne"] = (
            f"freight_db[{obs.get('observed_at')}]"
        )


def build_forecast_input(user_input: dict) -> tuple[dict, dict]:
    """Merge user input with stored data.

    Args:
        user_input: dict possibly containing a subset of FEATURES. None values
            are treated as "not provided".

    Returns:
        (merged_input, sources) where sources maps field_name -> provenance
        string ('user' or a DB reference). Raises ValueError if any required
        field is still missing after the merge.
    """
    # Start from user input, dropping None values so DB can fill them.
    merged: dict = {}
    sources: dict = {}
    for field in FEATURES:
        val = user_input.get(field)
        if val is not None:
            merged[field] = val
            sources[field] = "user"

    # Identity fields must come from the user.
    missing_identity = [f for f in REQUIRED_FROM_USER if f not in merged]
    if missing_identity:
        raise ValueError(
            "Missing required identity fields: " + ", ".join(missing_identity)
        )

    # Fill weather from the origin port.
    _fill_weather(merged, sources, merged["origin"])
    # Fill market data.
    _fill_market(merged, sources)
    # Fill current freight from observations.
    _fill_freight(merged, sources)

    # Anything still missing?
    missing = [f for f in FEATURES if f not in merged or merged[f] is None]
    if missing:
        raise ValueError(
            "Missing model inputs that could not be filled from the database: "
            + ", ".join(missing)
            + ". Provide them in the request or run `python -m data.update_data`."
        )

    return merged, sources


def forecast(user_input: dict) -> dict:
    """Build a complete input dict (user + DB) and run the model.

    Returns the FreightResponse dict augmented with a 'sources' key describing
    where each field came from.
    """
    merged, sources = build_forecast_input(user_input)
    result = predict_freight(merged)
    result["sources"] = sources
    return result


def init_data_layer() -> None:
    """Make sure the database exists before serving requests."""
    database.init_db()
