"""Pydantic request/response schemas for the freight forecasting API."""

from typing import Literal, Optional, Union

from pydantic import BaseModel, Field


class FreightRequest(BaseModel):
    """Forecast request for Model v3 (freight_forecast_model_v3.joblib).

    Model v3 uses 13 input features (NO cargo_tonnes - it was
    intentionally excluded because cargo values were representative
    vessel capacities, not observed shipment quantities).

    Required fields (identity + current freight):
        origin, destination, commodity, vessel_type, current_freight_usd_per_tonne

    Optional fields (filled from the data layer if omitted):
        bdi, vlsfo_usd_per_tonne, coal_price_usd_per_mt,
        iron_ore_price_usd_per_dmt, wind_kmh, wave_height_m,
        cyclone_risk, weather_delay_days

    If an optional field cannot be resolved from the database AND the user
    has not supplied it, the API returns a structured 422 listing the missing fields.
    No values are fabricated.
    """

    # --- identity (required) ---
    origin: str = Field(..., min_length=1, description="Loading port/region, e.g. 'Hay Point'")
    destination: str = Field(..., min_length=1, description="Discharge port/region, e.g. 'East Coast India'")
    commodity: str = Field(..., min_length=1, description="Cargo commodity, e.g. 'Coal'")
    vessel_type: str = Field(..., min_length=1, description="Vessel class, e.g. 'Panamax'")

    # --- current freight (required - the model's primary numeric signal) ---
    current_freight_usd_per_tonne: float = Field(
        ..., gt=0, description="Current freight rate (USD/tonne)"
    )

    # --- market (optional, filled from market_data if omitted) ---
    bdi: Optional[float] = Field(
        default=None, gt=0, description="Baltic Dry Index value (>0)"
    )
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


class ExplanationDriver(BaseModel):
    """Additive feature contribution derived from the model pipeline."""

    feature: str = Field(..., description="Feature identifier")
    feature_label: str = Field(..., description="Human-readable feature label")
    value: Union[float, str] = Field(..., description="Observed or input feature value")
    unit: str = Field(default="", description="Unit of measurement (e.g. USD/tonne, points, km/h)")
    coefficient: float = Field(..., description="Ridge regression model coefficient")
    contribution_usd_per_tonne: float = Field(..., description="Additive linear contribution to delta (USD/tonne)")
    effect: Literal["positive", "negative", "neutral"] = Field(..., description="Direction of contribution")
    source: Literal["model", "context"] = Field(default="model", description="Contribution origin")


class ExplanationAnchor(BaseModel):
    """Mathematical decomposition of the residual prediction anchor."""

    current_freight_usd_per_tonne: float = Field(..., description="Anchor spot freight rate (USD/tonne)")
    predicted_next_month_freight_usd_per_tonne: float = Field(..., description="Forecasted level rate (USD/tonne)")
    raw_predicted_delta_usd_per_tonne: float = Field(..., description="Unbounded raw residual delta from Ridge pipeline")
    bounded_delta_usd_per_tonne: float = Field(..., description="Residual delta after [-4.0, +4.0] guardrail")
    model_intercept: float = Field(..., description="Global baseline intercept term")
    residual_guardrail_applied: bool = Field(..., description="Whether [-4.0, +4.0] clipping was triggered")
    physical_floor_applied: bool = Field(..., description="Whether >= 1.0 USD/tonne floor was triggered")


class PredictionExplanation(BaseModel):
    """Transparent mathematical and natural language explanation of the forecast."""

    summary: str = Field(..., description="Concise human-readable explanation of forecast drivers")
    drivers: list[ExplanationDriver] = Field(
        default_factory=list, description="Ranked feature-level additive contributions"
    )
    anchor: ExplanationAnchor = Field(..., description="Mathematical anchoring decomposition")


class FreightResponse(BaseModel):
    """Forecast result returned by the /predict endpoint.

    `sources` documents where each filled field came from ('user' or a
    database reference with freshness metadata) so callers can see which inputs
    were auto-filled.
    `explanation` provides an exact mathematical and natural language breakdown
    of model drivers.
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
        description="Provenance of each model input: 'user' or a DB reference with freshness info.",
    )
    explanation: Optional[PredictionExplanation] = Field(
        default=None,
        description="Transparent mathematical breakdown and natural language drivers of the prediction.",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "predicted_next_month_freight_usd_per_tonne": 17.47,
                "current_freight_usd_per_tonne": 16.5,
                "forecast_change_percent": 5.88,
                "risk_level": "LOW",
                "recommendation": "CHARTER NOW",
                "reason": "Forecast indicates freight rates will rise by 5.88%. Lock in current rates before they increase.",
                "sources": {
                    "origin": "user",
                    "destination": "user",
                    "commodity": "user",
                    "vessel_type": "user",
                    "current_freight_usd_per_tonne": "user",
                    "wind_kmh": "weather_db[Hay Point@2026-08-28T17:14:09Z]",
                    "wave_height_m": "weather_db[Hay Point@2026-08-28T17:14:09Z]",
                    "bdi": "user",
                },
            }
        }
    }


# --------------------------------------------------------------------------- #
# Scenario Analysis Schemas (Phase 2)
# --------------------------------------------------------------------------- #
class ScenarioModifications(BaseModel):
    """Simulated parameter shifts. Supports both absolute overrides and percentage shocks."""

    # Absolute value overrides
    bdi: Optional[float] = Field(default=None, gt=0, description="Simulated absolute BDI (>0)")
    vlsfo_usd_per_tonne: Optional[float] = Field(
        default=None, ge=0, description="Simulated absolute VLSFO bunker price (USD/tonne)"
    )
    coal_price_usd_per_mt: Optional[float] = Field(
        default=None, ge=0, description="Simulated absolute Coal benchmark price (USD/MT)"
    )
    iron_ore_price_usd_per_dmt: Optional[float] = Field(
        default=None, ge=0, description="Simulated absolute Iron ore price (USD/dmt)"
    )
    wind_kmh: Optional[float] = Field(
        default=None, ge=0, description="Simulated absolute Wind speed (km/h)"
    )
    wave_height_m: Optional[float] = Field(
        default=None, ge=0, description="Simulated absolute Wave height (m)"
    )
    cyclone_risk: Optional[float] = Field(
        default=None, ge=0, le=5, description="Simulated absolute Cyclone risk score (0-5)"
    )
    weather_delay_days: Optional[float] = Field(
        default=None, ge=0, description="Simulated absolute Weather delay estimate (days)"
    )
    current_freight_usd_per_tonne: Optional[float] = Field(
        default=None, gt=0, description="Simulated absolute Current base freight (USD/tonne)"
    )

    # Relative percentage shocks
    bdi_change_percent: Optional[float] = Field(
        default=None, description="Percentage change in BDI (e.g. +20.0 for +20%)"
    )
    vlsfo_change_percent: Optional[float] = Field(
        default=None, description="Percentage change in VLSFO price (e.g. +10.0 for +10%)"
    )
    coal_price_change_percent: Optional[float] = Field(
        default=None, description="Percentage change in Coal price (e.g. -5.0 for -5%)"
    )
    iron_ore_price_change_percent: Optional[float] = Field(
        default=None, description="Percentage change in Iron Ore price (e.g. +5.0 for +5%)"
    )
    wind_change_percent: Optional[float] = Field(
        default=None, description="Percentage change in Wind speed (e.g. +30.0 for +30%)"
    )
    wave_height_change_percent: Optional[float] = Field(
        default=None, description="Percentage change in Wave height (e.g. +25.0 for +25%)"
    )
    cyclone_risk_change: Optional[float] = Field(
        default=None, description="Point change in Cyclone risk (e.g. +2.0 to move 2 -> 4)"
    )
    weather_delay_change_percent: Optional[float] = Field(
        default=None, description="Percentage change in Weather delay (e.g. +50.0 for +50%)"
    )
    current_freight_change_percent: Optional[float] = Field(
        default=None, description="Percentage change in Current freight (e.g. -10.0 for -10%)"
    )


class ScenarioRequest(FreightRequest):
    """What-if scenario request inheriting baseline inputs plus scenario modifications."""

    scenario_changes: Optional[ScenarioModifications] = Field(
        default=None,
        description="Scenario parameter modifications or relative shocks.",
    )


class ScenarioChangeItem(BaseModel):
    """Detailed record of a single changed input parameter."""

    feature: str = Field(..., description="Feature identifier")
    feature_label: str = Field(..., description="Human-readable feature name")
    baseline: float = Field(..., description="Baseline input value")
    scenario: float = Field(..., description="Simulated scenario input value")
    absolute_change: float = Field(..., description="Scenario minus baseline value")
    percentage_change: Optional[float] = Field(
        default=None, description="Percentage shift relative to baseline"
    )
    unit: str = Field(default="", description="Unit of measurement")


class ScenarioImpact(BaseModel):
    """Comparative impact metrics between baseline and scenario predictions."""

    difference_usd_per_tonne: float = Field(
        ..., description="Scenario predicted rate minus baseline predicted rate (USD/tonne)"
    )
    difference_percent: float = Field(
        ..., description="Percentage difference in forecast vs baseline forecast"
    )
    baseline_change_percent: float = Field(
        ..., description="Baseline forecast change percent vs base freight"
    )
    scenario_change_percent: float = Field(
        ..., description="Scenario forecast change percent vs base freight"
    )
    risk_level_shift: str = Field(
        ..., description="Risk level change, e.g. 'LOW -> HIGH' or 'LOW (unchanged)'"
    )
    recommendation_shift: str = Field(
        ..., description="Recommendation change, e.g. 'MONITOR -> CHARTER NOW'"
    )


class ScenarioResponse(BaseModel):
    """Complete response returned by POST /predict/scenario."""

    summary: str = Field(..., description="Executive natural language scenario summary")
    baseline: FreightResponse = Field(..., description="Baseline prediction & explainability")
    scenario: FreightResponse = Field(..., description="Simulated scenario prediction & explainability")
    impact: ScenarioImpact = Field(..., description="Comparative delta impact metrics")
    changes: list[ScenarioChangeItem] = Field(
        default_factory=list, description="Applied scenario modifications"
    )


class ErrorResponse(BaseModel):
    """Structured error payload for failed requests."""

    error_code: str = Field(..., description="Machine-readable error code")
    message: str = Field(..., description="Human-readable summary of the error")
    missing_fields: Optional[list[str]] = Field(
        default=None, description="List of missing feature names if applicable"
    )
    detail: Optional[str] = Field(default=None, description="Detailed troubleshooting instruction")


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
