"""FastAPI application exposing the FINAL freight forecasting model.

Run locally:
    cd backend
    python -m data.update_data          # populate the database once
    uvicorn main:app --reload --port 8000

Interactive docs: http://localhost:8000/docs
Frontend UI:      http://localhost:8000/
"""

import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# Make the backend root importable so `from data...` and `from services...`
# work regardless of the current working directory.
_BACKEND_ROOT = Path(__file__).resolve().parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from data import database
from predict import FEATURES, get_model, MODEL_PATH
from schemas import (
    DataStatus,
    FreightRequest,
    FreightResponse,
    LatestData,
    MarketQuoteOut,
    WeatherSnapshot,
)
from services.forecast_service import forecast, init_data_layer


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Eagerly load the model + initialise the database on startup so failures
    # surface immediately and the first request is fast.
    get_model()
    init_data_layer()
    yield


app = FastAPI(
    title="Freight Forecasting API",
    description=(
        "Forecast next-month bulk-cargo freight rates (USD/tonne) using the "
        "FINAL trained model (HistGradientBoostingRegressor). Weather data is "
        "fetched from Open-Meteo and cached in SQLite; market/freight sources "
        "are pluggable. The final model uses 13 input features (no cargo_tonnes)."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

# Allow a local frontend (any localhost port) to call the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8000",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve the static frontend (single-page HTML) at /
_STATIC_DIR = _BACKEND_ROOT / "static"


# --------------------------------------------------------------------------- #
# Health, model info, and data
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    """Health check used by load balancers / uptime monitors."""
    return {"status": "ok"}


@app.get("/model/info")
def model_info():
    """Return metadata about the active model."""
    return {
        "model": "freight_forecast_model_final",
        "version": "final",
        "type": "HistGradientBoostingRegressor (sklearn Pipeline)",
        "features": len(FEATURES),
        "feature_names": FEATURES,
        "excludes_cargo_tonnes": True,
        "model_file": MODEL_PATH.name,
    }


@app.get("/data/status", response_model=DataStatus)
def data_status():
    """Report when each data category was last updated."""
    return database.get_data_status()


@app.get("/data/latest", response_model=LatestData)
def data_latest():
    """Return the latest stored weather, market and freight data."""
    weather = database.get_all_latest_weather()
    market_map = database.get_latest_market()
    market = [
        MarketQuoteOut(
            series=series,
            value=q["value"],
            unit=q["unit"],
            source=q["source"],
            fetched_at=q["fetched_at"],
        )
        for series, q in market_map.items()
    ]
    with database.get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM freight_observations"
        ).fetchone()["c"]
        latest = conn.execute(
            "SELECT * FROM freight_observations ORDER BY observed_at DESC LIMIT 1"
        ).fetchone()
    return LatestData(
        weather=[WeatherSnapshot(**w) for w in weather],
        market=market,
        freight_observations_count=count,
        latest_freight_observation=dict(latest) if latest else None,
    )


# --------------------------------------------------------------------------- #
# Prediction
# --------------------------------------------------------------------------- #
@app.post("/predict", response_model=FreightResponse)
def predict(req: FreightRequest):
    """Forecast next-month freight rate and return a chartering recommendation.

    Required: origin, destination, commodity, vessel_type, current_freight_usd_per_tonne.
    Optional (filled from DB if omitted): bdi, vlsfo, coal_price, iron_ore,
    wind_kmh, wave_height_m, cyclone_risk, weather_delay_days.

    The final model does NOT use cargo_tonnes.
    """
    try:
        return forecast(req.model_dump(exclude_unset=False))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=f"Model unavailable: {exc}")
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=400, detail=f"Prediction failed: {exc}")


# --------------------------------------------------------------------------- #
# Static frontend (served at /)
# --------------------------------------------------------------------------- #
if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.get("/")
    def frontend():
        """Serve the single-page freight forecasting UI."""
        index = _STATIC_DIR / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return {"message": "Frontend not found. Use /docs for API."}
