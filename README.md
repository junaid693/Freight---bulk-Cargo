# Freight --- bulk Cargo

Freight rate forecasting for bulk-cargo shipping. A FastAPI backend wraps an
existing trained scikit-learn model (`freight_forecast_model_v1.joblib`) to
forecast next-month freight rates (USD/tonne) and produce weather-risk based
chartering recommendations (CHARTER NOW / WAIT / MONITOR).

A SQLite data layer caches the latest weather (fetched from the free
Open-Meteo API) so `/predict` can auto-fill market/weather variables instead
of requiring the frontend to enter every field manually. Market data sources
(BDI, bunker, commodity prices) are pluggable via a clean provider interface
with a no-op placeholder until a real subscription is connected.

> The model file is used **as-is** for inference only - it is never modified
> or retrained.

---

## Table of contents

- [Repository layout](#repository-layout)
- [Tech stack](#tech-stack)
- [The model](#the-model)
- [Data layer](#data-layer)
- [Setup](#setup)
- [Initializing the database](#initializing-the-database)
- [Updating data](#updating-data)
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
    ├── main.py                        # FastAPI app: /health, /predict, /data/*, CORS
    ├── predict.py                     # model loading + recommendation logic
    ├── schemas.py                     # Pydantic request/response models
    ├── test_example.py                # example request (Hay Point -> Visakhapatnam)
    ├── requirements.txt               # Python dependencies
    ├── data/
    │   ├── database.py                # SQLite schema + CRUD helpers
    │   ├── weather.py                 # Open-Meteo fetcher for the 4 ports
    │   ├── market.py                  # abstract market provider + placeholder
    │   ├── update_data.py             # CLI script to refresh the database
    │   └── freight.db                 # SQLite DB (auto-created, git-ignored)
    └── services/
        └── forecast_service.py        # merges user input with stored DB data
```

| File | Responsibility |
|------|----------------|
| `main.py` | HTTP layer - FastAPI app, CORS, route handlers |
| `predict.py` | ML layer - loads the joblib model, runs predictions, applies risk + recommendation business rules |
| `schemas.py` | API layer - Pydantic request/response models with input validation |
| `data/database.py` | SQLite schema and CRUD helpers for weather, market and freight tables |
| `data/weather.py` | Fetches live wind/wave/temperature for the 4 ports from Open-Meteo; derives cyclone_risk and weather_delay_days transparently |
| `data/market.py` | Abstract `MarketDataProvider` interface + a placeholder implementation that never fabricates values |
| `data/update_data.py` | CLI script that initialises the DB and refreshes weather/market data |
| `services/forecast_service.py` | Merges user-supplied input with the latest stored DB values before calling the model |
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
| Database | **SQLite** (stdlib `sqlite3`) | Caches latest weather/market/freight data |
| Weather data | **Open-Meteo** | Free, keyless API for wind/wave/temperature |
| Market data | pluggable interface | Placeholder provider by default (no fabricated values) |

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
(No extra dependencies are needed for the data layer - it uses the Python
standard library `sqlite3` and `urllib` modules.)

## Initializing the database

The SQLite database is created automatically on first use, but you can
create it explicitly (recommended before the first run):

```bash
cd backend
python -c "from data import database; database.init_db()"
```

This creates `backend/data/freight.db` with four tables:

| Table | Contents |
|-------|----------|
| `weather_data` | One row per (port, fetched_at) weather snapshot |
| `market_data` | One row per (series, fetched_at) market quote |
| `freight_observations` | One row per historical freight rate observation |
| `data_status` | `last_updated` timestamp per category |

The `.db` file is git-ignored - it is regenerated at runtime and never
committed.

## Updating data

Run the bundled CLI script to refresh the database:

```bash
cd backend
python -m data.update_data              # update weather + market (default)
python -m data.update_data --weather     # weather only
python -m data.update_data --market      # market only (no-op with placeholder)
python -m data.update_data --ports "Hay Point" "Paradip"
```

What it does:

- **Weather** - fetches live wind/wave/temperature for all four ports from
  Open-Meteo and stores a new snapshot per port. `cyclone_risk` and
  `weather_delay_days` are derived transparently (see
  [Data layer](#data-layer) below).
- **Market** - asks the configured `MarketDataProvider` for each series. The
  default placeholder returns nothing, so the `market_data` table stays empty
  until you wire up a real (paid) provider. Values are never fabricated.

### Supported ports

| Port | Coordinates | Region |
|------|-----------|--------|
| Hay Point | -21.37, 149.32 | Queensland, Australia (coal) |
| Taboneo | -3.65, 114.85 | South Kalimantan, Indonesia (coal) |
| Visakhapatnam | 17.68, 83.27 | Andhra Pradesh, India |
| Paradip | 20.32, 86.70 | Odisha, India |

### Wiring up a real market provider

Implement the `MarketDataProvider` protocol from `data/market.py`:

```python
from data.market import MarketDataProvider, MarketQuote, set_default_provider

class MyBdiProvider:
    def fetch_series(self, series: str):
        # call your paid API here
        return MarketQuote(series=series, value=1234.0, unit="index points",
                           source="baltic-exchange")
    def fetch_all(self):
        return [self.fetch_series(s) for s in ("bdi", ...)]

set_default_provider(MyBdiProvider())
```

Then `python -m data.update_data --market` will populate `market_data`, and
`/predict` will auto-fill market fields from the DB when the user omits them.

### Adding freight observations

Freight observations (used to fill `current_freight_usd_per_tonne` for a
route when the user omits it) can be inserted programmatically:

```python
from data import database
database.insert_freight_observation(
    origin="Hay Point", destination="Visakhapatnam",
    commodity="Coal", vessel_type="Panamax",
    current_freight_usd_per_tonne=28.0, cargo_tonnes=75000,
)
```

## Run the API

```bash
cd backend
python -m data.update_data          # populate the database once
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

### GET /data/status

Reports when each data category was last updated (ISO-8601 UTC, or `null`).

```bash
curl http://localhost:8000/data/status
# {"weather":"2026-08-27T17:14:18Z","market":null,"freight":null}
```

### GET /data/latest

Returns the latest stored weather (per port), latest market quotes (per
series), the total number of freight observations, and the single most recent
freight observation.

```bash
curl http://localhost:8000/data/latest
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

**Response (verified output for the full request above):**

```json
{
  "predicted_next_month_freight_usd_per_tonne": 21.07,
  "current_freight_usd_per_tonne": 28.0,
  "forecast_change_percent": -24.75,
  "risk_level": "MEDIUM",
  "recommendation": "WAIT",
  "reason": "Forecast indicates freight rates will drop by 24.75%. Waiting could secure lower rates.",
  "sources": {
    "origin": "user",
    "wind_kmh": "user",
    ...
  }
}
```

### POST /predict with stored data (minimal request)

Identity fields are always required; every other field is optional and will
be filled from the SQLite database when omitted. Below, the four weather
fields are omitted and auto-filled from the latest weather for the origin
port (Hay Point):

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
    "current_freight_usd_per_tonne": 28
  }'
```

```json
{
  "predicted_next_month_freight_usd_per_tonne": 19.46,
  ...,
  "sources": {
    "wind_kmh": "weather_db[Hay Point@2026-08-27T17:14:09Z]",
    "wave_height_m": "weather_db[Hay Point@2026-08-27T17:14:09Z]",
    "cyclone_risk": "weather_db[Hay Point@2026-08-27T17:14:09Z]",
    "weather_delay_days": "weather_db[Hay Point@2026-08-27T17:14:09Z]",
    ...
  }
}
```

If a field cannot be filled from the DB (e.g. market data when no provider
is configured), the API returns a `422` listing the missing fields rather
than fabricating values.

## Input features

The 5 identity fields are **required**. The other 9 are **optional** and will
be filled from the SQLite database when omitted (weather from the origin
port, market from the latest quotes, freight from route observations). The
order shown matches `model.feature_names_in_`.

| Field | Type | Required? | DB source | Constraint | Description |
|-------|------|----------|-----------|------------|-------------|
| `origin` | string | yes | - | - | Loading port name (e.g. `Hay Point`) |
| `destination` | string | yes | - | - | Discharge port name (e.g. `Visakhapatnam`) |
| `commodity` | string | yes | - | - | Cargo commodity (e.g. `Coal`, `Iron Ore`) |
| `vessel_type` | string | yes | - | - | Vessel class (e.g. `Panamax`, `Capesize`) |
| `cargo_tonnes` | float | yes | - | `> 0` | Cargo size in metric tonnes |
| `bdi` | float | optional | `market_data` | - | Baltic Dry Index value |
| `vlsfo_usd_per_tonne` | float | optional | `market_data` | `>= 0` | VLSFO bunker fuel price (USD/tonne) |
| `coal_price_usd_per_mt` | float | optional | `market_data` | `>= 0` | Coal benchmark price (USD/MT) |
| `iron_ore_price_usd_per_dmt` | float | optional | `market_data` | `>= 0` | Iron ore price (USD/dmt) |
| `wind_kmh` | float | optional | `weather_data` (origin port) | `>= 0` | Wind speed (km/h) |
| `wave_height_m` | float | optional | `weather_data` (origin port) | `>= 0` | Significant wave height (m) |
| `cyclone_risk` | float | optional | `weather_data` (origin port) | `0 - 5` | Cyclone risk score |
| `weather_delay_days` | float | optional | `weather_data` (origin port) | `>= 0` | Expected weather delay (days) |
| `current_freight_usd_per_tonne` | float | optional | `freight_observations` | `> 0` | Current freight rate (USD/tonne) |

Sending all 14 fields reproduces the original behaviour exactly (backward
compatible). Invalid inputs (e.g. negative `cargo_tonnes`, `cyclone_risk`
outside 0-5) are rejected automatically by Pydantic with a `422` response.

## Response fields

| Field | Type | Description |
|-------|------|-------------|
| `predicted_next_month_freight_usd_per_tonne` | float | Model forecast for the next-month freight rate (USD/tonne) |
| `current_freight_usd_per_tonne` | float | Current freight rate (echoed from the request) |
| `forecast_change_percent` | float | Percent change of forecast vs current rate |
| `risk_level` | enum | `LOW` / `MEDIUM` / `HIGH` weather risk band |
| `recommendation` | enum | `CHARTER NOW` / `WAIT` / `MONITOR` chartering action |
| `reason` | string | Human-readable explanation of the recommendation |
| `sources` | object | Provenance of each model input: `"user"` or a DB reference like `weather_db[Hay Point@...]` |

## Data layer

A SQLite database (`backend/data/freight.db`) caches the latest inputs so the
frontend does not have to enter every market/weather variable.

### Weather (Open-Meteo, live)

`data/weather.py` fetches live data from the free Open-Meteo API for the four
ports. No API key is required.

- **wind_speed_10m** (km/h) and **temperature_2m** (°C) from the forecast API
- **wave_height** (m) from the marine API
- If the forecast API is rate-limited, the archive API (most recent hour) is
  used as a transparent fallback - all values still come from Open-Meteo.

Two model features are **derived** with transparent, documented formulas
(not fabricated):

```
cyclone_risk       = clamp(wind_kmh / 30, 0, 5)
weather_delay_days = max(0, wave_height_m - 1.5) * 0.5   (+0.25 if wind > 40 km/h)
```

### Market (placeholder, pluggable)

There is no free, keyless API for BDI, bunker prices, or commodity
benchmarks - those require paid subscriptions. `data/market.py` defines a
clean `MarketDataProvider` interface with a no-op placeholder that **never
fabricates values**. Wire up a real adapter (see
[Updating data](#updating-data)) and the DB + `/predict` will pick it up
automatically.

### Merge strategy in `/predict`

`services/forecast_service.py` merges user input with stored data:

1. User-provided values always win.
2. Missing weather fields <- latest `weather_data` row for the **origin** port.
3. Missing market fields <- latest `market_data` row per series.
4. Missing `current_freight_usd_per_tonne` <- latest `freight_observations`
   row matching the route.
5. If any field is still missing, the API returns a `422` listing them.

The response's `sources` field documents where every value came from.

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
| `GET /data/status` returns last-updated per category | ✅ |
| `GET /data/latest` returns weather for all 4 ports | ✅ |
| `POST /predict` (full request) returns HTTP 200 with all fields | ✅ |
| `POST /predict` (minimal request) fills weather from DB for origin port | ✅ |
| `POST /predict` (missing market fields) returns 422 listing them | ✅ |
| Prediction is numeric | ✅ (21.07 / 19.46 / 19.40) |
| Database creation (`init_db`) creates all 4 tables | ✅ |
| Weather update fetches real Open-Meteo data for all 4 ports | ✅ |
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
