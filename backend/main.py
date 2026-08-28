"""FastAPI application exposing Model v3 forecasting, scenario simulation, and market intelligence.

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
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# Make the backend root importable so `from data...` and `from services...`
# work regardless of the current working directory.
_BACKEND_ROOT = Path(__file__).resolve().parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from data import database
from predict import FEATURES, get_model, get_model_metadata, MODEL_PATH
from schemas import (
    CorrelationsResponse,
    DataStatus,
    ErrorResponse,
    ExecutiveSummaryResponse,
    FreightRequest,
    FreightResponse,
    FreightTrendsResponse,
    LatestData,
    LatestMarketSnapshotResponse,
    MarketQuoteOut,
    MarketTrendsResponse,
    RoutesResponse,
    ScenarioRequest,
    ScenarioResponse,
    WeatherSnapshot,
    WeatherTrendsResponse,
)
from services import analytics_service
from services.forecast_service import (
    ForecastDataError,
    forecast,
    init_data_layer,
    run_scenario_forecast,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Eagerly load the model + initialise the database on startup so failures
    # surface immediately and the first request is fast.
    get_model()
    init_data_layer()
    yield


app = FastAPI(
    title="Freight Forecasting & Market Intelligence API (Model v3)",
    description=(
        "Production inference, what-if scenario simulation, and market intelligence API for dry bulk ocean freight. "
        "Forecasts next-month rates (USD/tonne) with closed-form mathematical explainability and provides "
        "comprehensive historical market trends and correlations."
    ),
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_STATIC_DIR = _BACKEND_ROOT / "static"


# --------------------------------------------------------------------------- #
# Health & info
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/model/info")
def model_info():
    """Return runtime metadata for the currently active production model."""
    return get_model_metadata()


# --------------------------------------------------------------------------- #
# Data status & latest values (Live DB Cache)
# --------------------------------------------------------------------------- #
@app.get("/data/status", response_model=DataStatus)
def data_status():
    """Return the last_updated ISO-8601 timestamp for weather, market, and freight."""
    return database.get_data_status()


@app.get("/data/latest", response_model=LatestData)
def data_latest():
    """Return the most recent stored snapshot for weather, market, and freight."""
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
# Prediction, Explainability & Scenario Simulation
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


@app.post(
    "/predict/scenario",
    response_model=ScenarioResponse,
    responses={422: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
def predict_scenario(req: ScenarioRequest):
    """Execute a what-if scenario simulation comparing baseline to modified market/weather shocks.

    Reuses the exact Model v3 inference pipeline.
    """
    try:
        return run_scenario_forecast(req.model_dump(exclude_unset=False))
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
                "error_code": "INVALID_SCENARIO_INPUT",
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
                "message": "An unexpected error occurred during scenario simulation.",
                "missing_fields": [],
                "detail": str(exc),
            },
        )


# --------------------------------------------------------------------------- #
# Market Intelligence & Historical Analytics (Phase 3)
# --------------------------------------------------------------------------- #
@app.get(
    "/analytics/freight-trends",
    response_model=FreightTrendsResponse,
    responses={422: {"model": ErrorResponse}},
)
def get_freight_trends(
    origin: Optional[str] = Query(None, description="Filter by loading port/region"),
    destination: Optional[str] = Query(None, description="Filter by discharge port/region"),
    commodity: Optional[str] = Query(None, description="Filter by cargo commodity"),
    vessel_type: Optional[str] = Query(None, description="Filter by vessel class"),
):
    """Retrieve chronological historical freight rates with MoM change and 3-month rolling averages."""
    try:
        return analytics_service.get_freight_trends(
            origin=origin,
            destination=destination,
            commodity=commodity,
            vessel_type=vessel_type,
        )
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


@app.get("/analytics/market-trends", response_model=MarketTrendsResponse)
def get_market_trends():
    """Retrieve historical monthly macroeconomic drivers (BDI, VLSFO, Coal, Iron Ore) and freight averages."""
    return analytics_service.get_market_trends()


@app.get(
    "/analytics/weather-trends",
    response_model=WeatherTrendsResponse,
    responses={422: {"model": ErrorResponse}},
)
def get_weather_trends(
    origin: Optional[str] = Query(None, description="Filter weather series by origin port"),
):
    """Retrieve historical weather observations (wind, waves, cyclone risk, delays) by port."""
    try:
        return analytics_service.get_weather_trends(origin=origin)
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


@app.get("/analytics/routes", response_model=RoutesResponse)
def get_routes_analytics():
    """Retrieve key statistics and trend classifications across canonical trade lanes."""
    return analytics_service.get_routes_analytics()


@app.get("/analytics/summary", response_model=ExecutiveSummaryResponse)
def get_executive_summary():
    """Retrieve high-level executive snapshot of latest market state, momentum, and top route movers."""
    return analytics_service.get_executive_summary()


@app.get("/analytics/correlations", response_model=CorrelationsResponse)
def get_correlations():
    """Retrieve Pearson correlation coefficients of freight against market and weather drivers."""
    return analytics_service.get_correlations()


@app.get("/analytics/latest", response_model=LatestMarketSnapshotResponse)
def get_latest_market_snapshot():
    """Retrieve comprehensive snapshot of latest available historical data and database cache status."""
    return analytics_service.get_latest_market_snapshot()


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
