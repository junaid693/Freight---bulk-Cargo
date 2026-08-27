# Freight --- bulk Cargo

Freight rate forecasting for bulk-cargo shipping. A FastAPI backend wraps an
existing trained scikit-learn model (`freight_forecast_model_v1.joblib`) to
forecast next-month freight rates (USD/tonne) and produce weather-risk based
chartering recommendations (CHARTER NOW / WAIT / MONITOR).

> The model file is used **as-is** for inference only - it is never modified
> or retrained.

---

## Table of contents

- [Repository layout](#repository-layout)
- [Tech stack](#tech-stack)
- [The model](#the-model)
- [Setup](#setup)
- [Run the API](#run-the-api)
- [Endpoints](#endpoints)
- [Input features](#input-features)
- [Response fields](#response-fields)
- [Recommendation logic](#recommendation-logic)
- [Testing](#testing)
- [CORS](#cors)
- [Troubleshooting](#troubleshooting)

---

## Repository layout

```
.
├── freight_forecast_model_v1.joblib   # existing trained model (do NOT modify)
├── README.md
└── backend/
    ├── main.py            # FastAPI app: /health, /predict, CORS
    ├── predict.py         # model loading + recommendation logic
    ├── schemas.py         # Pydantic request/response models
    ├── test_example.py    # example request (Hay Point -> Visakhapatnam)
    └── requirements.txt   # Python dependencies
```

| File | Responsibility |
|------|----------------|
| `main.py` | HTTP layer - FastAPI app, CORS, route handlers |
| `predict.py` | ML layer - loads the joblib model, runs predictions, applies risk + recommendation business rules |
| `schemas.py` | Data layer - Pydantic request/response models with input validation |
| `test_example.py` | Standalone test script that POSTs the Hay Point example and verifies the response |

## Tech stack

| Layer | Tool | Purpose |
|-------|------|---------|
| Web framework | **FastAPI** | Async API with automatic OpenAPI docs |
| ASGI server | **uvicorn** | Runs the FastAPI app |
| ML model | **scikit-learn** | RandomForestRegressor pipeline |
| Data handling | **pandas** / **numpy** | Building model input DataFrames |
| Model persistence | **joblib** | Loading the trained `.joblib` file |
| Validation | **Pydantic** | Request/response schemas (bundled with FastAPI) |

## The model

A scikit-learn `Pipeline` with two stages:

1. **`prep`** - `ColumnTransformer`
   - `cat` -> `OneHotEncoder` on `origin`, `destination`, `commodity`, `vessel_type`
   - `num` -> passthrough on the 10 numerical features
2. **`model`** - `RandomForestRegressor` (`n_estimators=250`, `max_depth=10`, `random_state=42`)

The model expects **14 input features** in a fixed order (taken from
`model.feature_names_in_`). See [Input features](#input-features) below.

## Setup

```bash
cd backend
pip install -r requirements.txt
```

Requirements: `fastapi`, `uvicorn`, `pandas`, `numpy`, `scikit-learn`, `joblib`

## Run the API

```bash
cd backend
uvicorn main:app --reload --port 8000
```

- Interactive docs (Swagger UI): http://localhost:8000/docs
- ReDoc docs: http://localhost:8000/redoc
- OpenAPI schema: http://localhost:8000/openapi.json

The model is loaded **once at startup** (fail-fast if the file is missing) and
cached for the lifetime of the process, so only the first request pays the
load cost.

## Endpoints

### GET /health

Health check for load balancers / uptime monitors.

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

### POST /predict

Forecast the next-month freight rate and get a chartering recommendation.

**Example - Hay Point -> Visakhapatnam, Coal, Panamax:**

```bash
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{
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
    "current_freight_usd_per_tonne": 28
  }'
```

Or run the bundled example script:

```bash
python test_example.py
```

**Response (verified output for the request above):**

```json
{
  "predicted_next_month_freight_usd_per_tonne": 21.07,
  "current_freight_usd_per_tonne": 28.0,
  "forecast_change_percent": -24.75,
  "risk_level": "MEDIUM",
  "recommendation": "WAIT",
  "reason": "Forecast indicates freight rates will drop by 24.75%. Waiting could secure lower rates."
}
```

## Input features

All 14 fields are **required**. The order shown matches `model.feature_names_in_`.

| Field | Type | Constraint | Description |
|-------|------|------------|-------------|
| `origin` | string | - | Loading port name (e.g. `Hay Point`) |
| `destination` | string | - | Discharge port name (e.g. `Visakhapatnam`) |
| `commodity` | string | - | Cargo commodity (e.g. `Coal`, `Iron Ore`) |
| `vessel_type` | string | - | Vessel class (e.g. `Panamax`, `Capesize`) |
| `cargo_tonnes` | float | `> 0` | Cargo size in metric tonnes |
| `bdi` | float | - | Baltic Dry Index value |
| `vlsfo_usd_per_tonne` | float | `>= 0` | VLSFO bunker fuel price (USD/tonne) |
| `coal_price_usd_per_mt` | float | `>= 0` | Coal benchmark price (USD/MT) |
| `iron_ore_price_usd_per_dmt` | float | `>= 0` | Iron ore price (USD/dmt) |
| `wind_kmh` | float | `>= 0` | Wind speed along route (km/h) |
| `wave_height_m` | float | `>= 0` | Significant wave height (m) |
| `cyclone_risk` | float | `0 - 5` | Cyclone risk score |
| `weather_delay_days` | float | `>= 0` | Expected weather-related delay (days) |
| `current_freight_usd_per_tonne` | float | `> 0` | Current freight rate (USD/tonne) |

Invalid inputs (e.g. negative `cargo_tonnes`, `cyclone_risk` outside 0-5) are
rejected automatically by Pydantic with a `422 Unprocessable Entity` response
that lists every offending field.

## Response fields

| Field | Type | Description |
|-------|------|-------------|
| `predicted_next_month_freight_usd_per_tonne` | float | Model forecast for the next-month freight rate (USD/tonne) |
| `current_freight_usd_per_tonne` | float | Current freight rate (echoed from the request) |
| `forecast_change_percent` | float | Percent change of forecast vs current rate |
| `risk_level` | enum | `LOW` / `MEDIUM` / `HIGH` weather risk band |
| `recommendation` | enum | `CHARTER NOW` / `WAIT` / `MONITOR` chartering action |
| `reason` | string | Human-readable explanation of the recommendation |

## Recommendation logic

### Risk level

| Condition | Risk |
|-----------|------|
| `cyclone_risk >= 4` OR `weather_delay_days >= 2.5` | HIGH |
| `cyclone_risk >= 3` OR `weather_delay_days >= 1` | MEDIUM |
| otherwise | LOW |

### Recommendation

| Condition | Recommendation |
|-----------|----------------|
| forecast change `>= +5%` OR risk is HIGH | **CHARTER NOW** |
| forecast change `<= -5%` AND risk is not HIGH | **WAIT** |
| otherwise | **MONITOR** |

> **Note:** HIGH risk always yields **CHARTER NOW**, even if rates are
> forecast to fall - because cyclone / severe-delay risk outweighs a
> favourable market trend.

## Testing

### Run the example test

The repository ships with a standalone test script that POSTs the Hay Point
example and asserts the prediction is numeric.

```bash
# 1. Start the API in one terminal
cd backend
uvicorn main:app --port 8000

# 2. In another terminal
cd backend
python test_example.py
```

Expected output:

```
HTTP status: 200
Response: {
  "predicted_next_month_freight_usd_per_tonne": 21.07,
  ...
}
Verified: predicted freight is numeric -> 21.07
```

### Verified test coverage

| Check | Status |
|-------|--------|
| Model loads via `joblib.load` | ✅ |
| `GET /health` returns `{"status":"ok"}` (HTTP 200) | ✅ |
| `POST /predict` returns HTTP 200 with all 6 fields | ✅ |
| Prediction is numeric | ✅ (21.07) |
| Risk logic: HIGH (cyclone_risk = 4) | ✅ |
| Risk logic: HIGH (weather_delay_days = 2.5 boundary) | ✅ |
| Risk logic: HIGH (weather_delay_days = 3.0) | ✅ |
| Risk logic: MEDIUM (cyclone_risk = 3) | ✅ |
| Risk logic: MEDIUM (weather_delay_days = 1.0 boundary) | ✅ |
| Risk logic: LOW (cyclone_risk = 1, delay = 0.5) | ✅ |

## CORS

The API allows requests from these origins so a local frontend can call it
directly without browser cross-origin errors:

- `http://localhost`
- `http://localhost:3000`
- `http://localhost:5173`
- `http://127.0.0.1:3000`
- `http://127.0.0.1:5173`

All methods and headers are allowed.

## Troubleshooting

### `InconsistentVersionWarning` on model load

The model was trained with a newer scikit-learn version than the one
installed. The warning looks like:

```
InconsistentVersionWarning: Trying to unpickle estimator ... from version 1.8.0
when using version 1.5.2. This might lead to breaking code or invalid results.
```

This is **non-fatal** - the model still loads and produces valid predictions
(verified). To silence the warning:

```bash
uvicorn main:app --port 8000 -W ignore
```

### `Model unavailable: ...` on `/predict`

The model file `freight_forecast_model_v1.joblib` must be at the repository
root (the parent of `backend/`). Make sure it was not moved or deleted.

### Port already in use

```bash
# find what is using port 8000
lsof -i :8000      # macOS / Linux
# then kill that process, or run on a different port:
uvicorn main:app --port 8001
```
