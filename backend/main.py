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
    ErrorResponse,
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
        "Forecast next-month bulk-cargo freight rates (USD/tonne) using Model v3 "
        "(Bounded Residual Ridge Regression). Weather data is fetched from Open-Meteo "
        "and cached in SQLite; market/freight sources are pluggable. "
        "The model uses 13 input features (no cargo_tonnes) trained on 110 real observations."
    ),
    version="3.0.0",
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
    from predict import get_model_metadata
    return get_model_metadata()


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
# Prediction & Telemetry
# --------------------------------------------------------------------------- #
@app.post(
    "/predict",
    response_model=FreightResponse,
    responses={422: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
def predict(req: FreightRequest):
    """Forecast next-month freight rate and return a chartering recommendation.

    Required: origin, destination, commodity, vessel_type, current_freight_usd_per_tonne.
    Optional (filled from DB if omitted): bdi, vlsfo, coal_price, iron_ore,
    wind_kmh, wave_height_m, cyclone_risk, weather_delay_days.

    Model v3 uses exactly 13 features (NO cargo_tonnes).
    """
    from fastapi.responses import JSONResponse
    from services.forecast_service import ForecastDataError

    try:
        return forecast(req.model_dump(exclude_unset=False))
    except ForecastDataError as exc:
        return JSONResponse(
            status_code=422,
            content={
                "error_code": exc.error_code,
                "message": exc.message,
                "missing_fields": exc.missing_fields,
                "detail": exc.detail,
            },
        )
    except FileNotFoundError as exc:
        return JSONResponse(
            status_code=503,
            content={
                "error_code": "MODEL_UNAVAILABLE",
                "message": "Model artifact not found on server.",
                "missing_fields": [],
                "detail": str(exc),
            },
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=422,
            content={
                "error_code": "INVALID_FORECAST_INPUT",
                "message": str(exc),
                "missing_fields": [],
                "detail": str(exc),
            },
        )
    except Exception as exc:  # pragma: no cover - defensive
        return JSONResponse(
            status_code=500,
            content={
                "error_code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected error occurred during forecasting.",
                "missing_fields": [],
                "detail": str(exc),
            },
        )


@app.get("/data/telemetry")
def get_telemetry(limit: int = 50):
    """Retrieve recent prediction audit logs (telemetry)."""
    return database.get_recent_prediction_logs(limit=limit)


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
