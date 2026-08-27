"""Model loading and freight forecasting logic.

Uses the existing trained model file `freight_forecast_model_v1.joblib`
(located at the repository root). The model file is never modified or
retrained - it is only loaded for inference.
"""

from pathlib import Path

import joblib
import pandas as pd

# Repository root is the parent of this backend/ directory.
REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = REPO_ROOT / "freight_forecast_model_v1.joblib"

# Exact feature order expected by the trained pipeline (model.feature_names_in_).
FEATURES = [
    "origin",
    "destination",
    "commodity",
    "vessel_type",
    "cargo_tonnes",
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

# Loaded once and cached for the lifetime of the process.
_model = None


def get_model():
    """Load and cache the trained sklearn pipeline from disk."""
    global _model
    if _model is None:
        if not MODEL_PATH.exists():
            raise FileNotFoundError(f"Model file not found: {MODEL_PATH}")
        _model = joblib.load(MODEL_PATH)
    return _model


def compute_risk_level(cyclone_risk: float, weather_delay_days: float) -> str:
    """Classify weather risk into LOW / MEDIUM / HIGH.

    - HIGH   if cyclone_risk >= 4 OR weather_delay_days >= 2.5
    - MEDIUM if cyclone_risk >= 3 OR weather_delay_days >= 1
    - otherwise LOW
    """
    if cyclone_risk >= 4 or weather_delay_days >= 2.5:
        return "HIGH"
    if cyclone_risk >= 3 or weather_delay_days >= 1:
        return "MEDIUM"
    return "LOW"


def compute_recommendation(forecast_change_percent: float, risk_level: str):
    """Decide the chartering recommendation and a human-readable reason.

    - WAIT        if forecast decreases by 5% or more AND risk is not HIGH
    - CHARTER NOW if forecast increases by 5% or more OR risk is HIGH
    - MONITOR     otherwise
    """
    if forecast_change_percent >= 5 or risk_level == "HIGH":
        if risk_level == "HIGH":
            reason = (
                "High weather risk detected (cyclone/delay thresholds exceeded). "
                "Charter now to avoid potential delays and rate spikes."
            )
        else:
            reason = (
                f"Forecast indicates freight rates will rise by "
                f"{forecast_change_percent:.2f}%. Lock in current rates "
                f"before they increase."
            )
        return "CHARTER NOW", reason

    if forecast_change_percent <= -5 and risk_level != "HIGH":
        reason = (
            f"Forecast indicates freight rates will drop by "
            f"{abs(forecast_change_percent):.2f}%. Waiting could secure "
            f"lower rates."
        )
        return "WAIT", reason

    reason = (
        f"Freight rates are expected to remain stable "
        f"({forecast_change_percent:+.2f}%). Continue monitoring the market."
    )
    return "MONITOR", reason


def predict_freight(data: dict) -> dict:
    """Run a single freight forecast.

    Args:
        data: dict containing all 14 model input features.

    Returns:
        dict with the prediction, risk level, recommendation and reason.
    """
    model = get_model()

    # Build a single-row DataFrame with the exact column order the
    # ColumnTransformer expects (it selects columns by name).
    X = pd.DataFrame([{feature: data[feature] for feature in FEATURES}])

    predicted = float(model.predict(X)[0])
    current = float(data["current_freight_usd_per_tonne"])

    if current > 0:
        change_percent = (predicted - current) / current * 100.0
    else:
        change_percent = 0.0

    risk_level = compute_risk_level(
        float(data["cyclone_risk"]), float(data["weather_delay_days"])
    )
    recommendation, reason = compute_recommendation(change_percent, risk_level)

    return {
        "predicted_next_month_freight_usd_per_tonne": round(predicted, 2),
        "current_freight_usd_per_tonne": round(current, 2),
        "forecast_change_percent": round(change_percent, 2),
        "risk_level": risk_level,
        "recommendation": recommendation,
        "reason": reason,
    }
