"""Pydantic request/response schemas for the freight forecasting API."""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class FreightRequest(BaseModel):
    """Forecast request.

    Identity fields (origin, destination, commodity, vessel_type, cargo_tonnes)
    are ALWAYS required - they identify the scenario.

    Every other field is OPTIONAL: if omitted, the service fills it from the
    SQLite database (latest weather for the origin port, latest market
    quotes, latest freight observation for the route). If a field still
    cannot be resolved, the API returns a 422 listing the missing fields.

    Sending all fields reproduces the original /predict behaviour exactly
    (backward compatible).
    """

    # --- identity (required) ---
    origin: str = Field(..., description="Loading port name, e.g. 'Hay Point'")
    destination: str = Field(..., description="Discharge port name, e.g. 'Visakhapatnam'")
    commodity: str = Field(..., description="Cargo commodity, e.g. 'Coal'")
    vessel_type: str = Field(..., description="Vessel class, e.g. 'Panamax'")
    cargo_tonnes: float = Field(..., gt=0, description="Cargo size in metric tonnes")

    # --- market (optional, filled from market_data if omitted) ---
    bdi: Optional[float] = Field(default=None, description="Baltic Dry Index value")
    vlsfo_usd_per_tonne: Optional[float] = Field(
        default=None, ge=0, description="VLSFO bunker price (USD/tonne)"
    )
    coal_price_usd_per_mt: Optional[float] = Field(
        default=None, ge=0, description="Coal benchmark price (USD/MT)"
    )
    iron_ore_price_usd_per_dmt: Optional[float] = Field(
        default=None, ge=0, description="Iron ore price (USD/dmt)"
    )

    # --- weather (optional, filled from weather_data for the origin port) ---
    wind_kmh: Optional[float] = Field(default=None, ge=0, description="Wind speed (km/h)")
    wave_height_m: Optional[float] = Field(default=None, ge=0, description="Wave height (m)")
    cyclone_risk: Optional[float] = Field(
        default=None, ge=0, le=5, description="Cyclone risk score 0-5"
    )
    weather_delay_days: Optional[float] = Field(
        default=None, ge=0, description="Expected weather delay (days)"
    )

    # --- current rate (optional, filled from freight_observations if omitted) ---
    current_freight_usd_per_tonne: Optional[float] = Field(
        default=None, gt=0, description="Current freight rate (USD/tonne)"
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "origin": "Hay Point",
                "destination": "Visakhapatnam",
                "commodity": "Coal",
                "vessel_type": "Panamax",
                "cargo_tonnes": 75000,
                "bdi": 1200,
                "vlsfo_usd_per_tonne": 600,
                "coal_price_usd_per_mt": 130,
                "iron_ore_price_usd_per_dmt": 115,
                "wind_kmh": 25,
                "wave_height_m": 2.5,
                "cyclone_risk": 2,
                "weather_delay_days": 1.5,
                "current_freight_usd_per_tonne": 28,
            }
        }
    }


class FreightResponse(BaseModel):
    """Forecast result returned by the /predict endpoint.

    `sources` documents where each filled field came from ('user' or a
    database reference) so callers can see which inputs were auto-filled.
    """

    predicted_next_month_freight_usd_per_tonne: float = Field(
        ..., description="Model forecast for next-month freight rate (USD/tonne)"
    )
    current_freight_usd_per_tonne: float = Field(
        ..., description="Current freight rate (USD/tonne)"
    )
    forecast_change_percent: float = Field(
        ..., description="Percent change of forecast vs current rate"
    )
    risk_level: Literal["LOW", "MEDIUM", "HIGH"] = Field(..., description="Weather risk band")
    recommendation: Literal["CHARTER NOW", "WAIT", "MONITOR"] = Field(
        ..., description="Actionable chartering recommendation"
    )
    reason: str = Field(..., description="Human-readable explanation of the recommendation")
    sources: dict[str, str] = Field(
        default_factory=dict,
        description="Provenance of each model input: 'user' or a DB reference.",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "predicted_next_month_freight_usd_per_tonne": 21.07,
                "current_freight_usd_per_tonne": 28.0,
                "forecast_change_percent": -24.75,
                "risk_level": "MEDIUM",
                "recommendation": "WAIT",
                "reason": "Forecast indicates freight rates will drop by 24.75%. "
                "Waiting could secure lower rates.",
                "sources": {
                    "origin": "user",
                    "destination": "user",
                    "commodity": "user",
                    "vessel_type": "user",
                    "cargo_tonnes": "user",
                    "wind_kmh": "weather_db[Hay Point@2026-08-27T17:00:00Z]",
                    "wave_height_m": "weather_db[Hay Point@2026-08-27T17:00:00Z]",
                    "current_freight_usd_per_tonne": "user",
                },
            }
        }
    }


# --------------------------------------------------------------------------- #
# /data endpoints
# --------------------------------------------------------------------------- #
class DataStatus(BaseModel):
    """Per-category last-updated timestamps."""

    weather: Optional[str] = Field(None, description="Last weather update (ISO-8601 UTC) or null")
    market: Optional[str] = Field(None, description="Last market update (ISO-8601 UTC) or null")
    freight: Optional[str] = Field(None, description="Last freight observation (ISO-8601 UTC) or null")


class WeatherSnapshot(BaseModel):
    port: str
    latitude: float
    longitude: float
    wind_kmh: Optional[float] = None
    wave_height_m: Optional[float] = None
    cyclone_risk: Optional[float] = None
    weather_delay_days: Optional[float] = None
    temperature_c: Optional[float] = None
    fetched_at: str


class MarketQuoteOut(BaseModel):
    series: str
    value: Optional[float] = None
    unit: Optional[str] = None
    source: Optional[str] = None
    fetched_at: str


class LatestData(BaseModel):
    """Latest stored data across all categories."""

    weather: list[WeatherSnapshot] = Field(
        default_factory=list, description="Latest weather row per port"
    )
    market: list[MarketQuoteOut] = Field(
        default_factory=list, description="Latest quote per market series"
    )
    freight_observations_count: int = Field(
        0, description="Total number of stored freight observations"
    )
    latest_freight_observation: Optional[dict] = Field(
        None, description="Most recent freight observation overall (if any)"
    )
