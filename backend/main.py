"""FastAPI application exposing the freight forecasting model.

Run locally:
    cd backend
    uvicorn main:app --reload --port 8000

Interactive docs are available at http://localhost:8000/docs
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from predict import get_model, predict_freight
from schemas import FreightRequest, FreightResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Eagerly load the model on startup so failures surface immediately
    # and the first /predict request is fast.
    get_model()
    yield


app = FastAPI(
    title="Freight Forecasting API",
    description=(
        "Forecast next-month bulk-cargo freight rates (USD/tonne) using the "
        "existing trained RandomForest model, with weather-risk based "
        "chartering recommendations."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# Allow a local frontend (any localhost port) to call the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    """Health check used by load balancers / uptime monitors."""
    return {"status": "ok"}


@app.post("/predict", response_model=FreightResponse)
def predict(req: FreightRequest):
    """Forecast next-month freight rate and return a chartering recommendation."""
    try:
        return predict_freight(req.model_dump())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=f"Model unavailable: {exc}")
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=400, detail=f"Prediction failed: {exc}")
