"""Pydantic request/response schemas for the freight forecasting API."""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class FreightRequest(BaseModel):
    """Forecast request for the FINAL model (freight_forecast_model_final.joblib).

    The final model uses 13 input features (NO cargo_tonnes - it was
    intentionally excluded because cargo values were representative
    vessel capacities, not observed shipment quantities).

    Required fields (identity + current freight):
        origin, destination, commodity, vessel_type, current_freight_usd_per_tonne

    Optional fields (filled from the data layer if omitted):
        bdi, vlsfo_usd_per_tonne, coal_price_usd_per_mt,
        iron_ore_price_usd_per_dmt, wind_kmh, wave_height_m,
        cyclone_risk, weather_delay_days

    If an optional field cannot be resolved from the database AND the user
    has not supplied it, the API returns a 422 listing the missing fields.
    No values are fabricated.
    """

    # --- identity (required) ---
    origin: str = Field(..., description="Loading port/region, e.g. 'Hay Point'")
    destination: str = Field(..., description="Discharge port/region, e.g. 'East Coast India'")
    commodity: str = Field(..., description="Cargo commodity, e.g. 'Coal'")
    vessel_type: str = Field(..., description="Vessel class, e.g. 'Panamax'")

    # --- current freight (required - the model's primary numeric signal) ---
    current_freight_usd_per_tonne: float = Field(
        ..., gt=0, description="Current freight rate (USD/tonne)"
    )

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

    model_config = {
        "json_schema_extra": {
            "example": {
                "origin": "Hay Point",
                "destination": "East Coast India",
                "commodity": "Coal",
                "vessel_type": "Panamax",
                "current_freight_usd_per_tonne": 16.5,
                "bdi": 1560,
                "vlsfo_usd_per_tonne": 638,
                "coal_price_usd_per_mt": 124,
                "iron_ore_price_usd_per_dmt": 124,
                "wind_kmh": 32,
                "wave_height_m": 2.0,
                "cyclone_risk": 2,
                "weather_delay_days": 0.5,
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
                "predicted_next_month_freight_usd_per_tonne": 17.32,
                "current_freight_usd_per_tonne": 16.5,
                "forecast_change_percent": 4.97,
                "risk_level": "MEDIUM",
                "recommendation": "MONITOR",
                "reason": "Freight rates are expected to remain stable (+4.97%). Continue monitoring the market.",
                "sources": {
                    "origin": "user",
                    "destination": "user",
                    "commodity": "user",
                    "vessel_type": "user",
                    "current_freight_usd_per_tonne": "user",
                    "wind_kmh": "weather_db[Hay Point@2026-08-27T17:14:09Z]",
                    "wave_height_m": "weather_db[Hay Point@2026-08-27T17:14:09Z]",
                    "bdi": "user",
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
