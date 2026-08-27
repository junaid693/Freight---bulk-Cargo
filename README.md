# Freight --- bulk Cargo

Freight rate forecasting for bulk-cargo shipping. Uses an existing trained
scikit-learn model (`freight_forecast_model_v1.joblib`) to forecast next-month
freight rates (USD/tonne) and produce weather-risk based chartering
recommendations.

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
    └── requirements.txt
```

## The model

A scikit-learn `Pipeline`:

1. `prep` - `ColumnTransformer`
   - `cat` -> `OneHotEncoder` on `origin`, `destination`, `commodity`, `vessel_type`
   - `num` -> passthrough on the numerical features
2. `model` - `RandomForestRegressor` (`n_estimators=250`, `max_depth=10`)

Input features (exact order expected by the model):

```
origin, destination, commodity, vessel_type, cargo_tonnes, bdi,
vlsfo_usd_per_tonne, coal_price_usd_per_mt, iron_ore_price_usd_per_dmt,
wind_kmh, wave_height_m, cyclone_risk, weather_delay_days,
current_freight_usd_per_tonne
```

## Setup

```bash
cd backend
pip install -r requirements.txt
```

## Run the API

```bash
cd backend
uvicorn main:app --reload --port 8000
```

Interactive docs: http://localhost:8000/docs

## Endpoints

### GET /health

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

### POST /predict

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

Or run the bundled example:

```bash
python test_example.py
```

**Response:**

```json
{
  "predicted_next_month_freight_usd_per_tonne": 30.45,
  "current_freight_usd_per_tonne": 28.0,
  "forecast_change_percent": 8.75,
  "risk_level": "MEDIUM",
  "recommendation": "CHARTER NOW",
  "reason": "Forecast indicates freight rates will rise by 8.75%. Lock in current rates before they increase."
}
```

## Recommendation logic

**Risk level**

| Condition | Risk |
|-----------|------|
| `cyclone_risk >= 4` OR `weather_delay_days >= 2.5` | HIGH |
| `cyclone_risk >= 3` OR `weather_delay_days >= 1` | MEDIUM |
| otherwise | LOW |

**Recommendation**

| Condition | Recommendation |
|-----------|----------------|
| forecast change `>= +5%` OR risk is HIGH | CHARTER NOW |
| forecast change `<= -5%` AND risk is not HIGH | WAIT |
| otherwise | MONITOR |

## CORS

The API allows requests from `http://localhost:3000`, `http://localhost:5173`
and other localhost origins so a local frontend can call it directly.
