"""Example request for the /predict endpoint.

Route:   Hay Point  ->  Visakhapatnam
Cargo:   Coal
Vessel:  Panamax

Usage:
    1. Start the API:
        cd backend
        uvicorn main:app --port 8000
    2. In another terminal run:
        python test_example.py

Uses only the Python standard library (no extra dependencies needed).
"""

import json
import urllib.request

URL = "http://localhost:8000/predict"

PAYLOAD = {
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
    "current_freight_usd_per_tonne": 28,
}


def main():
    body = json.dumps(PAYLOAD).encode("utf-8")
    req = urllib.request.Request(
        URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        status = resp.status
        result = json.loads(resp.read().decode("utf-8"))

    print("Request:", json.dumps(PAYLOAD, indent=2))
    print("\nHTTP status:", status)
    print("Response:", json.dumps(result, indent=2))

    predicted = result.get("predicted_next_month_freight_usd_per_tonne")
    assert isinstance(predicted, (int, float)), "prediction is not numeric!"
    print(f"\nVerified: predicted freight is numeric -> {predicted}")


if __name__ == "__main__":
    main()
