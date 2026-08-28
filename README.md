# Freight Intelligence Platform — Bulk-Cargo Freight Forecasting

Ocean freight rate forecasting platform for bulk-cargo shipping. A FastAPI backend wraps the trained scikit-learn Model v3 (`freight_forecast_model_v3.joblib`) to forecast next-month freight rates (USD/tonne) and produce weather-risk based chartering recommendations (`CHARTER NOW` / `WAIT` / `MONITOR`).

A hardened SQLite data layer (operating in WAL mode with connection timeouts) caches the latest weather (fetched from the free Open-Meteo API) so `/predict` can auto-fill market and weather variables instead of requiring the user to enter every field manually. Market data sources (BDI, bunker, commodity prices) are pluggable via a clean provider interface with a no-op placeholder until a real subscription is connected.

---

## Table of Contents

- [Repository Layout](#repository-layout)
- [Tech Stack](#tech-stack)
- [Active Model: Model v3](#active-model-model-v3)
- [Data Layer & Supported Ports](#data-layer--supported-ports)
- [Data Freshness & Staleness Policy](#data-freshness--staleness-policy)
- [Setup & Database Initialization](#setup--database-initialization)
- [Updating Data](#updating-data)
- [Running the API](#running-the-api)
- [Endpoints](#endpoints)
- [Structured Error Handling](#structured-error-handling)
- [Prediction Telemetry & Audit Logs](#prediction-telemetry--audit-logs)
- [Input Features (13-Feature Contract)](#input-features-13-feature-contract)
- [Recommendation Logic](#recommendation-logic)
- [Testing](#testing)
- [Model Rollback Procedure](#model-rollback-procedure)
- [Known Limitations](#known-limitations)

---

## Repository Layout

```
.
├── freight_forecast_model_v3.joblib       # Active production Model v3 (Bounded Residual Ridge)
├── freight_forecast_model_final.joblib    # Preserved legacy Model v2 artifact (Random Forest)
├── freight_forecast_model_v1.joblib       # Preserved legacy Model v1 artifact
├── train_v3.py                            # Model v3 training & verification script
├── MODEL_V3_FINAL_VALIDATION.md           # Pre-integration validation report
├── MODEL_V3_INTEGRATION_REPORT.md         # Final integration & benchmark report
├── BACKEND_PRODUCTION_READINESS_AUDIT.md  # Production readiness audit
├── BACKEND_HARDENING_IMPLEMENTATION_REPORT.md # Hardening report
├── README.md
├── data/
│   ├── master_freight_training_expanded_v1.csv   # Primary real training dataset (110 rows)
│   └── master_freight_training_synthetic_v2.csv  # Quarantined synthetic dataset (experimental)
└── backend/
    ├── main.py                            # FastAPI app: /health, /model/info, /predict, /data/*
    ├── predict.py                         # Model loading, level floor & recommendation logic
    ├── schemas.py                         # Pydantic request/response validation
    ├── test_suite.py                      # Comprehensive automated test suite
    ├── test_v3_model.py                   # Model v3 end-to-end integration tests
    ├── test_concurrency.py                # SQLite WAL concurrency test
    ├── requirements.txt                   # Backend dependencies
    ├── data/
    │   ├── database.py                    # SQLite WAL schema, CRUD & prediction logging
    │   ├── weather.py                     # Open-Meteo weather fetcher for all 5 ports
    │   ├── market.py                      # Pluggable MarketDataProvider interface
    │   ├── update_data.py                 # CLI data refresh script
    │   └── freight.db                     # SQLite database (auto-generated)
    └── services/
        └── forecast_service.py            # Input merging, freshness tracking & telemetry
```

---

## Tech Stack

| Layer | Tool | Purpose |
|-------|------|---------|
| Web framework | **FastAPI** | Async REST API with OpenAPI documentation |
| ASGI server | **uvicorn** | High-performance ASGI web server |
| ML framework | **scikit-learn** | Bounded Residual Ridge Regression pipeline |
| Data handling | **pandas** / **numpy** | Feature transformation and inference tensors |
| Model persistence | **joblib** | Serialized `.joblib` model pipeline |
| Validation | **Pydantic** | Request and response schema validation |
| Database | **SQLite** (WAL mode) | Concurrency-safe local cache for weather & telemetry |
| Weather provider | **Open-Meteo** | Free API for wind speed, wave height, and cyclone metrics |

---

## Active Model: Model v3

**Model v3** is a **Bounded Residual Ridge Regression** model configured as follows:

- **Mathematical Formulation**:
  $$\hat{y}_{t+1} = \max(1.0, \text{current\_freight}_t + \text{clip}(\widehat{\Delta y}, -4.0, 4.0))$$
  where $\widehat{\Delta y} = \text{Ridge}_{\alpha=10.0}(\mathbf{x})$ predicts the 1-month rate change.
- **Physical Non-Negative Floor**: Level forecast enforces a strict minimum floor ($\ge 1.0\text{ USD/t}$), guaranteeing ocean freight rates can never collapse into negative values.
- **Defensive Guardrail**: Residual delta is clipped to $[-4.0, +4.0]\text{ USD/t}$ (training-derived 99th percentile physical boundary).
- **Training Data**: Exclusively the **110 real historical observations** in `data/master_freight_training_expanded_v1.csv` across 5 trade lanes (Months 1–22).
- **Synthetic Data**: Excluded from training.

---

## Data Layer & Supported Ports

The weather provider supports all 5 canonical ports/regions matching the training data distribution:

| Port / Region | Coordinates | Trade Corridor Role |
|---|---|---|
| **Australia West Coast** | `(-20.32, 118.57)` | Western Australia iron ore loading (Dampier / Port Hedland) |
| **Hay Point** | `(-21.37, 149.32)` | Queensland metallurgical coal loading |
| **Taboneo** | `(-3.65, 114.85)` | South Kalimantan thermal coal loading |
| **Visakhapatnam** | `(17.68, 83.27)` | East Coast India discharge port |
| **Paradip** | `(20.32, 86.70)` | East Coast India discharge port |

---

## Data Freshness & Staleness Policy

- **Weather Freshness Threshold**: 24 hours.
- **Provenance Tags**:
  - `weather_db[Port@Timestamp]` when cached data is $<24\text{ hours}$ old.
  - `weather_db[Port@Timestamp:STALE(Xh_old)]` when cached data exceeds 24 hours.
- **Zero-Fabrication Policy**: When required market data is not present in the DB, the platform returns HTTP 422 with `MARKET_DATA_MISSING` rather than substituting zeros or synthetic numbers.

---

## Endpoints

### `GET /model/info`
Returns dynamic metadata about the active model:
```json
{
  "model": "freight_forecast_model_v3",
  "version": "3.0.0",
  "algorithm": "Bounded Residual Ridge Regression",
  "alpha": 10.0,
  "residual_guardrail_usd_per_tonne": [-4.0, 4.0],
  "features": 13,
  "feature_names": ["origin", "destination", "commodity", "vessel_type", "bdi", "vlsfo_usd_per_tonne", "coal_price_usd_per_mt", "iron_ore_price_usd_per_dmt", "wind_kmh", "wave_height_m", "cyclone_risk", "weather_delay_days", "current_freight_usd_per_tonne"],
  "excludes_cargo_tonnes": true,
  "model_file": "freight_forecast_model_v3.joblib",
  "training_dataset": "master_freight_training_expanded_v1.csv (110 real observations)",
  "synthetic_data_used": false
}
```

### `POST /predict`
```bash
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{
    "origin": "Australia West Coast",
    "destination": "East Coast India",
    "commodity": "Iron Ore",
    "vessel_type": "Capesize",
    "current_freight_usd_per_tonne": 10.5,
    "bdi": 1560,
    "vlsfo_usd_per_tonne": 638,
    "coal_price_usd_per_mt": 124,
    "iron_ore_price_usd_per_dmt": 124
  }'
```

### `GET /data/telemetry`
Returns recent prediction logs for auditing and model drift monitoring:
```bash
curl http://localhost:8000/data/telemetry?limit=10
```

---

## Structured Error Handling

When required input data cannot be resolved, the API returns structured error payloads:
```json
{
  "error_code": "MARKET_DATA_MISSING",
  "message": "Missing model inputs that could not be filled from the database: bdi, vlsfo_usd_per_tonne, coal_price_usd_per_mt, iron_ore_price_usd_per_dmt.",
  "missing_fields": ["bdi", "vlsfo_usd_per_tonne", "coal_price_usd_per_mt", "iron_ore_price_usd_per_dmt"],
  "detail": "Provide missing fields in the request or populate the database using `python -m data.update_data`."
}
```

---

## Testing

Run the full automated test suite:
```bash
python backend/test_suite.py
python backend/test_v3_model.py
python backend/test_concurrency.py
```
