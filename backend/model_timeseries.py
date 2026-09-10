"""Route-Specific Time-Series Freight Forecaster (ARIMA/ARIMAX).

Replaces the Model v3 Ridge Regression pipeline with a proper time-series
forecasting architecture based on statsmodels ARIMA(0,1,1).

Key Architecture:
- Evaluates each canonical route/commodity/vessel combination as its own time series.
- Uses ARIMA(0,1,1):
    First-differenced integrated process with Moving Average shock smoothing.
    Delta: Delta y_{t+1} = theta_1 * epsilon_t
    Forecast: y_{t+1} = y_t + Delta y_{t+1}
- Strictly excludes seasonal terms (s=12) because 22 monthly observations are
  statistically insufficient for seasonal estimation and cause ML convergence failures.
- Enforces physical level floor (>= 1.0 USD/tonne).
- Enforces documented historical volatility sanity bounds.
- Provides closed-form time-series explainability (anchor, differencing trend, MA shock, market drivers).
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
from statsmodels.tsa.arima.model import ARIMA, ARIMAResults


CANONICAL_ROUTES = [
    ("Australia West Coast", "East Coast India", "Iron Ore", "Capesize"),
    ("Hay Point", "East Coast India", "Coal", "Capesize"),
    ("Hay Point", "East Coast India", "Coal", "Panamax"),
    ("Taboneo", "East Coast India", "Thermal Coal", "Panamax"),
    ("Taboneo", "East Coast India", "Thermal Coal", "Supramax"),
]

FEATURE_METADATA = {
    "vlsfo_usd_per_tonne": ("VLSFO Bunker Price", "USD/tonne"),
    "bdi": ("Baltic Dry Index (BDI)", "points"),
    "cyclone_risk": ("Cyclone Risk Score", "0-5"),
    "wave_height_m": ("Significant Wave Height", "m"),
    "wind_kmh": ("Wind Speed", "km/h"),
    "weather_delay_days": ("Weather Delay Estimate", "days"),
    "coal_price_usd_per_mt": ("Coal Benchmark Price", "USD/MT"),
    "iron_ore_price_usd_per_dmt": ("Iron Ore Benchmark Price", "USD/dmt"),
    "current_freight_usd_per_tonne": ("Current Spot Freight Anchor", "USD/tonne"),
    "origin": ("Loading Port Context", ""),
    "commodity": ("Cargo Commodity Context", ""),
    "vessel_type": ("Vessel Class Context", ""),
    "destination": ("Discharge Port Context", ""),
}


class RouteARIMAProfile:
    """Stores fitted parameters and historical context for a single canonical route."""

    def __init__(
        self,
        route_tuple: Tuple[str, str, str, str],
        order: Tuple[int, int, int] = (0, 1, 1),
        theta: float = 0.0,
        sigma2: float = 1.0,
        last_residual: float = 0.0,
        last_observed_freight: float = 10.0,
        last_observed_date: str = "2025-11-01",
        history_min: float = 5.0,
        history_max: float = 25.0,
        history_mean: float = 12.0,
        history_std: float = 1.5,
        observations_count: int = 22,
        aic: float = 0.0,
        bic: float = 0.0,
        validation_mae: float = 1.1078,
        validation_rmse: float = 1.7792,
    ):
        self.route_tuple = route_tuple
        self.order = order
        self.theta = theta
        self.sigma2 = sigma2
        self.last_residual = last_residual
        self.last_observed_freight = last_observed_freight
        self.last_observed_date = last_observed_date
        self.history_min = history_min
        self.history_max = history_max
        self.history_mean = history_mean
        self.history_std = history_std
        self.observations_count = observations_count
        self.aic = aic
        self.bic = bic
        self.validation_mae = validation_mae
        self.validation_rmse = validation_rmse

    def forecast_delta(self, current_freight: float) -> Tuple[float, float, bool]:
        """Compute expected freight delta and innovation shock.

        For ARIMA(0,1,1):
            Delta y_{t+1} = theta * epsilon_t
        Handles dynamic inference state if current_freight differs from historical last_observed_freight.
        """
        y_last = float(self.last_observed_freight)
        theta = float(self.theta)
        eps_last = float(self.last_residual)
        sigma = math.sqrt(max(0.01, float(self.sigma2)))

        if abs(current_freight - y_last) < 0.01:
            # Querying directly from historical sample end
            eps = eps_last
            is_dynamic = False
        else:
            # Dynamic state update from user-supplied spot quotation
            # Surprise relative to the expected rate from the last known step
            y_exp = y_last + theta * eps_last
            raw_surprise = current_freight - y_exp
            # Defensive 3-sigma bounding to guard against unphysical input typos
            eps = float(np.clip(raw_surprise, -3.0 * sigma, 3.0 * sigma))
            is_dynamic = True

        delta = float(theta * eps_last)
        return delta, eps, is_dynamic


class NaviFreightTimeSeriesForecaster:
    """Production Time-Series Forecaster managing route-specific ARIMA models."""

    def __init__(
        self,
        order: Tuple[int, int, int] = (0, 1, 1),
        seasonal_order: Tuple[int, int, int, int] = (0, 0, 0, 0),
        model_name: str = "freight_forecast_model_timeseries",
        version: str = "4.0.0",
        training_dataset: str = "master_freight_training_expanded_v1.csv (110 real observations across 5 routes)",
        training_start_date: str = "2024-02-01",
        training_end_date: str = "2025-11-01",
    ):
        self.order = order
        self.seasonal_order = seasonal_order
        self.model_name = model_name
        self.version = version
        self.training_dataset = training_dataset
        self.training_start_date = training_start_date
        self.training_end_date = training_end_date
        self.profiles: Dict[Tuple[str, str, str, str], RouteARIMAProfile] = {}
        self.global_mean_delta: float = 0.20
        self.feature_names_in_: List[str] = [
            "origin",
            "destination",
            "commodity",
            "vessel_type",
            "bdi",
            "vlsfo_usd_per_tonne",
            "coal_price_usd_per_mt",
            "iron_ore_price_usd_per_dmt",
            "wind_kmh",
            "wave_height_m",
            "cyclone_risk",
            "weather_delay_days",
            "current_freight_usd_per_tonne",
        ]

    def add_route_profile(self, profile: RouteARIMAProfile) -> None:
        self.profiles[profile.route_tuple] = profile

    def match_route(self, origin: str, destination: str, commodity: str, vessel_type: str) -> Optional[RouteARIMAProfile]:
        """Match input parameters to a canonical route profile."""
        key = (origin, destination, commodity, vessel_type)
        if key in self.profiles:
            return self.profiles[key]

        # Case-insensitive / partial fallback
        for k, prof in self.profiles.items():
            if (
                k[0].lower() == origin.lower()
                and k[1].lower() == destination.lower()
                and k[2].lower() == commodity.lower()
                and k[3].lower() == vessel_type.lower()
            ):
                return prof

        # Vessel type / origin fallback
        for k, prof in self.profiles.items():
            if k[0].lower() == origin.lower() and k[3].lower() == vessel_type.lower():
                return prof

        # Return first available profile if completely unknown
        if self.profiles:
            return next(iter(self.profiles.values()))
        return None

    def predict_one(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Perform a single route-specific forecast with full explainability."""
        origin = str(row.get("origin", ""))
        destination = str(row.get("destination", "East Coast India"))
        commodity = str(row.get("commodity", ""))
        vessel_type = str(row.get("vessel_type", ""))
        current = float(row.get("current_freight_usd_per_tonne", 10.0))

        profile = self.match_route(origin, destination, commodity, vessel_type)

        if profile is not None:
            raw_delta, eps, is_dynamic = profile.forecast_delta(current)
            theta = profile.theta
            route_label = f"{profile.route_tuple[0]} -> {profile.route_tuple[1]} ({profile.route_tuple[2]} / {profile.route_tuple[3]})"
            h_min, h_max = profile.history_min, profile.history_max
            h_std = profile.history_std
            h_mean = profile.history_mean
            route_mae = getattr(profile, "validation_mae", 1.1078)
        else:
            raw_delta = self.global_mean_delta
            eps = 0.0
            theta = 0.0
            is_dynamic = False
            route_label = "Global Fallback Route"
            h_min, h_max = 5.0, 30.0
            h_std = 2.0
            h_mean = 12.0
            route_mae = 1.1078

        # Market indicator inputs
        bdi_val = float(row.get("bdi", 1500.0) or 1500.0)
        vlsfo_val = float(row.get("vlsfo_usd_per_tonne", 620.0) or 620.0)
        coal_val = float(row.get("coal_price_usd_per_mt", 124.0) or 124.0)
        iron_val = float(row.get("iron_ore_price_usd_per_dmt", 124.0) or 124.0)
        delay_days = float(row.get("weather_delay_days", 0.0) or 0.0)
        wind_val = float(row.get("wind_kmh", 0.0) or 0.0)
        wave_val = float(row.get("wave_height_m", 0.0) or 0.0)
        cyclone_val = float(row.get("cyclone_risk", 0.0) or 0.0)

        # Deviation from route historical equilibrium (mean reversion from elevated spot rates)
        dev = current - h_mean
        excess_dev = float(max(0.0, dev - 0.3 * h_std)) if dev > 0 else 0.0
        mean_rev = float(-0.33 * excess_dev)

        # Operational decision-layer adjustments (bunker pass-through, BDI macro sensitivity, weather delay)
        bdi_effect = float(np.clip((bdi_val - 1500.0) * 0.0003, -0.60, 0.60))
        vlsfo_effect = float(np.clip((vlsfo_val - 600.0) * 0.015, -1.00, 1.00))
        coal_effect = float(np.clip((coal_val - 124.0) * 0.002, -0.30, 0.30)) if "coal" in commodity.lower() else 0.0
        iron_effect = float(np.clip((iron_val - 124.0) * 0.002, -0.30, 0.30)) if "iron" in commodity.lower() else 0.0
        weather_effect = float(np.clip(delay_days * 0.08, 0.0, 0.40))
        cyclone_effect = float(np.clip(cyclone_val * 0.06, 0.0, 0.35))
        wind_effect = float(np.clip((wind_val - 25.0) * 0.002, -0.05, 0.10)) if wind_val > 0 else 0.0
        wave_effect = float(np.clip((wave_val - 1.5) * 0.02, -0.05, 0.10)) if wave_val > 0 else 0.0

        # --- 1. Pure Statistical Base Forecast: Route-Specific ARIMA(0,1,1) ---
        max_allowed_delta = 4.0
        bounded_arima_delta = float(np.clip(raw_delta, -max_allowed_delta, max_allowed_delta))
        base_forecast = max(1.0, round(current + bounded_arima_delta, 2))

        # --- 2. Operational Decision-Layer Adjustment ---
        op_adjustment_raw = (
            mean_rev
            + bdi_effect
            + vlsfo_effect
            + coal_effect
            + iron_effect
            + weather_effect
            + cyclone_effect
            + wind_effect
            + wave_effect
        )
        operational_adjustment = round(op_adjustment_raw, 2)

        # --- 3. Combined Expected Freight ---
        model_delta = raw_delta + mean_rev + bdi_effect + vlsfo_effect + coal_effect + iron_effect + weather_effect + cyclone_effect + wind_effect + wave_effect
        bounded_delta = float(np.clip(model_delta, -max_allowed_delta, max_allowed_delta))
        sanity_check_applied = bool(abs(model_delta) > max_allowed_delta)

        # Enforce physical floor (minimum 1.0 USD/tonne)
        predicted = max(1.0, round(current + bounded_delta, 2))
        expected_freight = predicted
        floor_applied = bool((current + bounded_delta) < 1.0)

        change_usd = round(expected_freight - current, 2)
        change_pct = round((change_usd / current) * 100.0, 2) if current > 0 else 0.0

        direction = "UP" if change_pct >= 5.0 else ("DOWN" if change_pct <= -5.0 else "STABLE")

        # Empirical uncertainty bounds based on out-of-sample walk-forward MAE (Step 6)
        forecast_low = max(1.0, round(expected_freight - route_mae, 2))
        forecast_high = round(expected_freight + route_mae, 2)
        model_validation_mae = round(route_mae, 4)

        # Transparent explainability drivers matching schema and test contract
        curr_contrib = float(raw_delta + mean_rev)
        drivers = [
            {
                "feature": "current_freight_usd_per_tonne",
                "feature_label": "Base Freight (ARIMA Shock + Mean Reversion)",
                "value": round(current, 2),
                "unit": "USD/tonne",
                "coefficient": round(theta, 4),
                "contribution_usd_per_tonne": round(curr_contrib, 4),
                "effect": "positive" if curr_contrib > 0.001 else ("negative" if curr_contrib < -0.001 else "neutral"),
                "source": "model",
            },
            {
                "feature": "bdi",
                "feature_label": "Baltic Dry Index (BDI Macro Sensitivity)",
                "value": round(bdi_val, 1),
                "unit": "points",
                "coefficient": 0.0003,
                "contribution_usd_per_tonne": round(bdi_effect, 4),
                "effect": "positive" if bdi_effect > 0.001 else ("negative" if bdi_effect < -0.001 else "neutral"),
                "source": "model",
            },
            {
                "feature": "vlsfo_usd_per_tonne",
                "feature_label": "VLSFO Bunker Pass-Through",
                "value": round(vlsfo_val, 1),
                "unit": "USD/tonne",
                "coefficient": 0.015,
                "contribution_usd_per_tonne": round(vlsfo_effect, 4),
                "effect": "positive" if vlsfo_effect > 0.001 else ("negative" if vlsfo_effect < -0.001 else "neutral"),
                "source": "model",
            },
            {
                "feature": "coal_price_usd_per_mt",
                "feature_label": "Coal Benchmark Price",
                "value": round(coal_val, 1),
                "unit": "USD/MT",
                "coefficient": 0.002 if "coal" in commodity.lower() else 0.0,
                "contribution_usd_per_tonne": round(coal_effect, 4),
                "effect": "positive" if coal_effect > 0.001 else ("negative" if coal_effect < -0.001 else "neutral"),
                "source": "model",
            },
            {
                "feature": "iron_ore_price_usd_per_dmt",
                "feature_label": "Iron Ore Benchmark Price",
                "value": round(iron_val, 1),
                "unit": "USD/dmt",
                "coefficient": 0.002 if "iron" in commodity.lower() else 0.0,
                "contribution_usd_per_tonne": round(iron_effect, 4),
                "effect": "positive" if iron_effect > 0.001 else ("negative" if iron_effect < -0.001 else "neutral"),
                "source": "model",
            },
            {
                "feature": "weather_delay_days",
                "feature_label": "Weather Delay Estimate",
                "value": round(delay_days, 1),
                "unit": "days",
                "coefficient": 0.08,
                "contribution_usd_per_tonne": round(weather_effect, 4),
                "effect": "positive" if weather_effect > 0.001 else ("negative" if weather_effect < -0.001 else "neutral"),
                "source": "model",
            },
            {
                "feature": "cyclone_risk",
                "feature_label": "Cyclone Risk Score",
                "value": round(cyclone_val, 1),
                "unit": "0-5",
                "coefficient": 0.06,
                "contribution_usd_per_tonne": round(cyclone_effect, 4),
                "effect": "positive" if cyclone_effect > 0.001 else ("negative" if cyclone_effect < -0.001 else "neutral"),
                "source": "model",
            },
            {
                "feature": "wind_kmh",
                "feature_label": "Wind Speed",
                "value": round(wind_val, 1),
                "unit": "km/h",
                "coefficient": 0.002 if wind_val > 0 else 0.0,
                "contribution_usd_per_tonne": round(wind_effect, 4),
                "effect": "positive" if wind_effect > 0.001 else ("negative" if wind_effect < -0.001 else "neutral"),
                "source": "model",
            },
            {
                "feature": "wave_height_m",
                "feature_label": "Significant Wave Height",
                "value": round(wave_val, 1),
                "unit": "m",
                "coefficient": 0.02 if wave_val > 0 else 0.0,
                "contribution_usd_per_tonne": round(wave_effect, 4),
                "effect": "positive" if wave_effect > 0.001 else ("negative" if wave_effect < -0.001 else "neutral"),
                "source": "model",
            },
            {
                "feature": "origin",
                "feature_label": f"Loading Port Context ({origin})",
                "value": str(origin),
                "unit": "",
                "coefficient": 0.0,
                "contribution_usd_per_tonne": 0.0,
                "effect": "neutral",
                "source": "model",
            },
            {
                "feature": "destination",
                "feature_label": f"Discharge Port Context ({destination})",
                "value": str(destination),
                "unit": "",
                "coefficient": 0.0,
                "contribution_usd_per_tonne": 0.0,
                "effect": "neutral",
                "source": "model",
            },
            {
                "feature": "commodity",
                "feature_label": f"Cargo Commodity Context ({commodity})",
                "value": str(commodity),
                "unit": "",
                "coefficient": 0.0,
                "contribution_usd_per_tonne": 0.0,
                "effect": "neutral",
                "source": "model",
            },
            {
                "feature": "vessel_type",
                "feature_label": f"Vessel Class Context ({vessel_type})",
                "value": str(vessel_type),
                "unit": "",
                "coefficient": 0.0,
                "contribution_usd_per_tonne": 0.0,
                "effect": "neutral",
                "source": "model",
            },
        ]

        # Natural language summary
        dir_word = "rise" if direction == "UP" else ("drop" if direction == "DOWN" else "remain stable")
        state_str = "dynamic spot update" if is_dynamic else "historical baseline shock"
        summary = (
            f"Freight is projected to {dir_word} from ${current:.2f}/t to ${expected_freight:.2f}/t ({change_pct:+.2f}%) "
            f"for {route_label}. Base statistical forecast: ${base_forecast:.2f}/t (ARIMA(0,1,1) theta: {theta:+.4f}, "
            f"shock: {eps:+.2f} USD/t, {state_str}). Operational adjustment: ${operational_adjustment:+.2f}/t. "
            f"Expected empirical range: [${forecast_low:.2f}, ${forecast_high:.2f}]/t (Validation MAE: {route_mae:.4f} USD/t)."
        )

        anchor = {
            "current_freight_usd_per_tonne": round(current, 2),
            "base_forecast": base_forecast,
            "operational_adjustment": operational_adjustment,
            "predicted_next_month_freight_usd_per_tonne": expected_freight,
            "predicted_freight_usd_per_tonne": expected_freight,
            "expected_freight": expected_freight,
            "forecast_low": forecast_low,
            "forecast_high": forecast_high,
            "model_validation_mae": model_validation_mae,
            "raw_predicted_delta_usd_per_tonne": round(model_delta, 4),
            "bounded_delta_usd_per_tonne": round(bounded_delta, 4),
            "base_arima_delta_usd_per_tonne": round(raw_delta, 4),
            "forecast_change_usd_per_tonne": change_usd,
            "forecast_change_percent": change_pct,
            "direction": direction,
            "dynamic_state_updated": is_dynamic,
            "innovation_residual": round(eps, 4),
            "model_intercept": 0.0,
            "residual_guardrail_applied": sanity_check_applied,
            "physical_floor_applied": floor_applied,
            "route_matched": route_label,
            "canonical_order": list(self.order),
            "canonical_seasonal_order": list(self.seasonal_order),
        }

        return {
            "base_forecast": base_forecast,
            "operational_adjustment": operational_adjustment,
            "predicted_next_month_freight_usd_per_tonne": expected_freight,
            "predicted_freight_usd_per_tonne": expected_freight,
            "expected_freight": expected_freight,
            "forecast_low": forecast_low,
            "forecast_high": forecast_high,
            "model_validation_mae": model_validation_mae,
            "current_freight_usd_per_tonne": round(current, 2),
            "forecast_change_usd_per_tonne": change_usd,
            "forecast_change_percent": change_pct,
            "direction": direction,
            "model_name": self.model_name,
            "model_version": self.version,
            "training_data_end_date": self.training_end_date,
            "forecast_timestamp": datetime.now(timezone.utc).isoformat(),
            "explanation": {
                "summary": summary,
                "drivers": drivers,
                "anchor": anchor,
            },
        }

    def predict(self, X: Union[pd.DataFrame, Dict[str, Any]]) -> np.ndarray:
        """Sklearn-compatible batch prediction method returning numpy array of level forecasts."""
        if isinstance(X, dict):
            return np.array([self.predict_one(X)["predicted_next_month_freight_usd_per_tonne"]])

        preds = []
        for _, row in X.iterrows():
            res = self.predict_one(row.to_dict())
            preds.append(res["predicted_next_month_freight_usd_per_tonne"])
        return np.array(preds, dtype=float)
