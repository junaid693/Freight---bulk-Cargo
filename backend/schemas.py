"""Pydantic request/response schemas for the freight forecasting API."""

from typing import Literal

from pydantic import BaseModel, Field


class FreightRequest(BaseModel):
    """Input features required by the trained freight forecasting model.

    Field order mirrors the model's `feature_names_in_` order so the request
    can be passed straight into the model pipeline.
    """

    origin: str = Field(..., description="Loading port name, e.g. 'Hay Point'")
    destination: str = Field(..., description="Discharge port name, e.g. 'Visakhapatnam'")
    commodity: str = Field(..., description="Cargo commodity, e.g. 'Coal'")
    vessel_type: str = Field(..., description="Vessel class, e.g. 'Panamax'")
    cargo_tonnes: float = Field(..., gt=0, description="Cargo size in metric tonnes")
    bdi: float = Field(..., description="Baltic Dry Index value")
    vlsfo_usd_per_tonne: float = Field(..., ge=0, description="VLSFO bunker price (USD/tonne)")
    coal_price_usd_per_mt: float = Field(..., ge=0, description="Coal benchmark price (USD/MT)")
    iron_ore_price_usd_per_dmt: float = Field(..., ge=0, description="Iron ore price (USD/dmt)")
    wind_kmh: float = Field(..., ge=0, description="Wind speed along route (km/h)")
    wave_height_m: float = Field(..., ge=0, description="Significant wave height (m)")
    cyclone_risk: float = Field(..., ge=0, le=5, description="Cyclone risk score 0-5")
    weather_delay_days: float = Field(..., ge=0, description="Expected weather-related delay (days)")
    current_freight_usd_per_tonne: float = Field(
        ..., gt=0, description="Current freight rate (USD/tonne)"
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
    """Forecast result returned by the /predict endpoint."""

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

    model_config = {
        "json_schema_extra": {
            "example": {
                "predicted_next_month_freight_usd_per_tonne": 30.45,
                "current_freight_usd_per_tonne": 28.00,
                "forecast_change_percent": 8.75,
                "risk_level": "MEDIUM",
                "recommendation": "CHARTER NOW",
                "reason": "Forecast indicates freight rates will rise by 8.75%. "
                "Lock in current rates before they increase.",
            }
        }
    }
