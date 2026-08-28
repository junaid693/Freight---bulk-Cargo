"""Comprehensive automated test suite for Freight Forecasting backend and ML pipeline.

Uses Python standard library `unittest` + FastAPI TestClient.
Tests are deterministic and do not make live external network calls.
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add backend directory to sys.path
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

import joblib
import numpy as np
from fastapi.testclient import TestClient

from data import database
from data.weather import PORTS
from main import app
from predict import (
    FEATURES,
    MODEL_PATH,
    compute_recommendation,
    compute_risk_level,
    get_model,
    get_model_metadata,
    predict_freight,
)
from schemas import FreightRequest, FreightResponse
from services.forecast_service import ForecastDataError, build_forecast_input, forecast


class TestModelContract(unittest.TestCase):
    """Tests active Model v3 loading and feature contract."""

    def test_model_file_exists(self):
        self.assertTrue(MODEL_PATH.exists(), f"Model file missing: {MODEL_PATH}")

    def test_model_loads(self):
        model = get_model()
        self.assertIsNotNone(model)
        self.assertTrue(hasattr(model, "predict"))

    def test_13_feature_contract(self):
        model = get_model()
        features = list(model.feature_names_in_)
        self.assertEqual(len(features), 13)
        self.assertNotIn("cargo_tonnes", features)
        self.assertEqual(features, FEATURES)

    def test_model_prediction_output(self):
        sample = {
            "origin": "Hay Point",
            "destination": "East Coast India",
            "commodity": "Coal",
            "vessel_type": "Panamax",
            "current_freight_usd_per_tonne": 16.5,
            "bdi": 1560,
            "vlsfo_usd_per_tonne": 638,
            "coal_price_usd_per_mt": 124,
            "iron_ore_price_usd_per_dmt": 124,
            "wind_kmh": 32,
            "wave_height_m": 2.0,
            "cyclone_risk": 2,
            "weather_delay_days": 0.5,
        }
        res = predict_freight(sample)
        self.assertIn("predicted_next_month_freight_usd_per_tonne", res)
        self.assertIsInstance(res["predicted_next_month_freight_usd_per_tonne"], float)
        self.assertGreater(res["predicted_next_month_freight_usd_per_tonne"], 0)
        self.assertIn(res["risk_level"], ["LOW", "MEDIUM", "HIGH"])
        self.assertIn(res["recommendation"], ["CHARTER NOW", "WAIT", "MONITOR"])
        self.assertIn("explanation", res)


class TestForecastExplainability(unittest.TestCase):
    """Tests feature attribution, explainability summary, and mathematical consistency."""

    def test_explanation_structure_and_mathematical_consistency(self):
        sample = {
            "origin": "Hay Point",
            "destination": "East Coast India",
            "commodity": "Coal",
            "vessel_type": "Panamax",
            "current_freight_usd_per_tonne": 16.5,
            "bdi": 1560.0,
            "vlsfo_usd_per_tonne": 638.0,
            "coal_price_usd_per_mt": 124.0,
            "iron_ore_price_usd_per_dmt": 124.0,
            "wind_kmh": 32.0,
            "wave_height_m": 2.0,
            "cyclone_risk": 2.0,
            "weather_delay_days": 0.5,
        }
        res = predict_freight(sample)
        self.assertIn("explanation", res)
        expl = res["explanation"]

        # Check required fields
        self.assertIn("summary", expl)
        self.assertIn("drivers", expl)
        self.assertIn("anchor", expl)

        # Check summary is non-empty and references dollar values
        self.assertIn("$16.50", expl["summary"])
        self.assertIn("$17.47", expl["summary"])

        # Check drivers
        drivers = expl["drivers"]
        self.assertGreater(len(drivers), 5)
        for d in drivers:
            self.assertIn("feature", d)
            self.assertIn("feature_label", d)
            self.assertIn("contribution_usd_per_tonne", d)
            self.assertIn("effect", d)
            self.assertIn(d["effect"], ["positive", "negative", "neutral"])
            self.assertEqual(d["source"], "model")

        # Mathematical consistency: sum of contributions + intercept == raw_delta (within float precision)
        total_contrib = sum(d["contribution_usd_per_tonne"] for d in drivers)
        intercept = expl["anchor"]["model_intercept"]
        raw_delta = expl["anchor"]["raw_predicted_delta_usd_per_tonne"]
        reconstructed_delta = total_contrib + intercept
        self.assertAlmostEqual(reconstructed_delta, raw_delta, places=2)

    def test_explainability_across_all_5_routes(self):
        routes = [
            ("Australia West Coast", "East Coast India", "Iron Ore", "Capesize", 10.0),
            ("Hay Point", "East Coast India", "Coal", "Capesize", 14.0),
            ("Hay Point", "East Coast India", "Coal", "Panamax", 16.5),
            ("Taboneo", "East Coast India", "Thermal Coal", "Panamax", 11.0),
            ("Taboneo", "East Coast India", "Thermal Coal", "Supramax", 12.0),
        ]
        for origin, dest, comm, vessel, curr in routes:
            sample = {
                "origin": origin,
                "destination": dest,
                "commodity": comm,
                "vessel_type": vessel,
                "current_freight_usd_per_tonne": curr,
                "bdi": 1560.0,
                "vlsfo_usd_per_tonne": 638.0,
                "coal_price_usd_per_mt": 124.0,
                "iron_ore_price_usd_per_dmt": 124.0,
                "wind_kmh": 32.0,
                "wave_height_m": 2.0,
                "cyclone_risk": 2.0,
                "weather_delay_days": 0.5,
            }
            res = predict_freight(sample)
            self.assertIn("explanation", res)
            self.assertTrue(len(res["explanation"]["drivers"]) > 0)
            self.assertTrue(len(res["explanation"]["summary"]) > 20)


class TestPredictionSafetyAndBounds(unittest.TestCase):
    """Tests physical minimum floor and safety limits."""

    def test_physical_forecast_floor_prevents_negative(self):
        """Even with an extreme downward push on a very low base rate, forecast cannot be negative."""
        sample = {
            "origin": "Australia West Coast",
            "destination": "East Coast India",
            "commodity": "Iron Ore",
            "vessel_type": "Capesize",
            "current_freight_usd_per_tonne": 2.0,  # very low base rate
            "bdi": 500,
            "vlsfo_usd_per_tonne": 200,
            "coal_price_usd_per_mt": 50,
            "iron_ore_price_usd_per_dmt": 50,
            "wind_kmh": 5,
            "wave_height_m": 0.5,
            "cyclone_risk": 0,
            "weather_delay_days": 0.0,
        }
        res = predict_freight(sample)
        pred = res["predicted_next_month_freight_usd_per_tonne"]
        self.assertGreaterEqual(pred, 1.0, f"Forecast must enforce minimum 1.0 floor, got {pred}")
        self.assertTrue(res["explanation"]["anchor"]["physical_floor_applied"])

    def test_normal_forecast_not_altered_by_floor(self):
        sample = {
            "origin": "Hay Point",
            "destination": "East Coast India",
            "commodity": "Coal",
            "vessel_type": "Capesize",
            "current_freight_usd_per_tonne": 14.0,
            "bdi": 1560,
            "vlsfo_usd_per_tonne": 638,
            "coal_price_usd_per_mt": 124,
            "iron_ore_price_usd_per_dmt": 124,
            "wind_kmh": 32,
            "wave_height_m": 2.0,
            "cyclone_risk": 2,
            "weather_delay_days": 0.5,
        }
        res = predict_freight(sample)
        pred = res["predicted_next_month_freight_usd_per_tonne"]
        self.assertGreater(pred, 10.0)
        self.assertLess(pred, 25.0)


class TestRecommendationBoundaries(unittest.TestCase):
    """Tests exact threshold boundary cases for risk level and recommendations."""

    def test_risk_level_boundaries(self):
        # cyclone_risk >= 4 -> HIGH
        self.assertEqual(compute_risk_level(4.0, 0.0), "HIGH")
        # cyclone_risk = 3.99, delay = 0 -> MEDIUM
        self.assertEqual(compute_risk_level(3.99, 0.0), "MEDIUM")
        # cyclone_risk = 3.0 -> MEDIUM
        self.assertEqual(compute_risk_level(3.0, 0.0), "MEDIUM")
        # cyclone_risk = 2.99 -> LOW
        self.assertEqual(compute_risk_level(2.99, 0.0), "LOW")

        # weather_delay_days >= 2.5 -> HIGH
        self.assertEqual(compute_risk_level(0.0, 2.5), "HIGH")
        # weather_delay_days = 2.49 -> MEDIUM
        self.assertEqual(compute_risk_level(0.0, 2.49), "MEDIUM")
        # weather_delay_days = 1.0 -> MEDIUM
        self.assertEqual(compute_risk_level(0.0, 1.0), "MEDIUM")
        # weather_delay_days = 0.99 -> LOW
        self.assertEqual(compute_risk_level(0.0, 0.99), "LOW")

    def test_recommendation_boundaries(self):
        # +5.0% -> CHARTER NOW
        rec, _ = compute_recommendation(5.0, "LOW")
        self.assertEqual(rec, "CHARTER NOW")
        # +4.99% -> MONITOR
        rec, _ = compute_recommendation(4.99, "LOW")
        self.assertEqual(rec, "MONITOR")

        # -5.0% -> WAIT
        rec, _ = compute_recommendation(-5.0, "LOW")
        self.assertEqual(rec, "WAIT")
        # -4.99% -> MONITOR
        rec, _ = compute_recommendation(-4.99, "LOW")
        self.assertEqual(rec, "MONITOR")

        # -10.0% with HIGH risk -> CHARTER NOW (risk overrides drop)
        rec, _ = compute_recommendation(-10.0, "HIGH")
        self.assertEqual(rec, "CHARTER NOW")


class TestAPIEndpointsAndValidation(unittest.TestCase):
    """Tests FastAPI HTTP endpoints, schema validation, and error responses."""

    def setUp(self):
        self.client = TestClient(app)
        database.init_db()

    def test_health_endpoint(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})

    def test_model_info_endpoint(self):
        resp = self.client.get("/model/info")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["model"], "freight_forecast_model_v3")
        self.assertEqual(data["algorithm"], "Bounded Residual Ridge Regression")
        self.assertEqual(data["alpha"], 10.0)
        self.assertEqual(data["features"], 13)
        self.assertTrue(data["excludes_cargo_tonnes"])
        self.assertFalse(data["synthetic_data_used"])
        self.assertEqual(data["feature_names"], FEATURES)

    def test_bdi_validation_rejects_zero_and_negative(self):
        payload_zero = {
            "origin": "Hay Point", "destination": "East Coast India", "commodity": "Coal",
            "vessel_type": "Panamax", "current_freight_usd_per_tonne": 16.5,
            "bdi": 0,  # Invalid <= 0
        }
        resp = self.client.post("/predict", json=payload_zero)
        self.assertEqual(resp.status_code, 422)

        payload_neg = {
            "origin": "Hay Point", "destination": "East Coast India", "commodity": "Coal",
            "vessel_type": "Panamax", "current_freight_usd_per_tonne": 16.5,
            "bdi": -100,  # Invalid < 0
        }
        resp = self.client.post("/predict", json=payload_neg)
        self.assertEqual(resp.status_code, 422)

    def test_predict_missing_required_current_freight_422(self):
        payload = {
            "origin": "Hay Point", "destination": "East Coast India",
            "commodity": "Coal", "vessel_type": "Panamax",
        }
        resp = self.client.post("/predict", json=payload)
        self.assertEqual(resp.status_code, 422)

    def test_missing_market_data_structured_error(self):
        """When optional market fields are omitted and DB has no quotes, return structured MARKET_DATA_MISSING."""
        payload = {
            "origin": "Hay Point", "destination": "East Coast India", "commodity": "Coal",
            "vessel_type": "Panamax", "current_freight_usd_per_tonne": 16.5,
            "wind_kmh": 25, "wave_height_m": 1.5, "cyclone_risk": 1, "weather_delay_days": 0.0,
            # omitted: bdi, vlsfo, coal_price, iron_ore
        }
        resp = self.client.post("/predict", json=payload)
        self.assertEqual(resp.status_code, 422)
        err = resp.json()
        self.assertEqual(err.get("error_code"), "MARKET_DATA_MISSING")
        self.assertIn("bdi", err.get("missing_fields", []))

    def test_predict_all_5_production_combinations_with_explanation(self):
        combos = [
            ("Australia West Coast", "East Coast India", "Iron Ore", "Capesize", 10.0),
            ("Hay Point", "East Coast India", "Coal", "Capesize", 14.0),
            ("Hay Point", "East Coast India", "Coal", "Panamax", 16.5),
            ("Taboneo", "East Coast India", "Thermal Coal", "Panamax", 11.0),
            ("Taboneo", "East Coast India", "Thermal Coal", "Supramax", 12.0),
        ]
        for origin, dest, comm, vessel, curr in combos:
            payload = {
                "origin": origin, "destination": dest, "commodity": comm, "vessel_type": vessel,
                "current_freight_usd_per_tonne": curr,
                "bdi": 1560, "vlsfo_usd_per_tonne": 638, "coal_price_usd_per_mt": 124, "iron_ore_price_usd_per_dmt": 124,
                "wind_kmh": 32, "wave_height_m": 2.0, "cyclone_risk": 2, "weather_delay_days": 0.5,
            }
            resp = self.client.post("/predict", json=payload)
            self.assertEqual(resp.status_code, 200)
            res = resp.json()
            pred = res["predicted_next_month_freight_usd_per_tonne"]
            self.assertGreaterEqual(pred, 1.0)
            self.assertLessEqual(pred, 30.0)
            self.assertIn(res["recommendation"], ["CHARTER NOW", "WAIT", "MONITOR"])
            self.assertIn("explanation", res)
            self.assertIn("drivers", res["explanation"])
            self.assertGreater(len(res["explanation"]["drivers"]), 5)


class TestDataFreshnessAndWeatherPorts(unittest.TestCase):
    """Tests Australia West Coast coordinates, DB auto-fill, staleness tags, and telemetry logging."""

    def setUp(self):
        self.client = TestClient(app)
        database.init_db()

    def test_australia_west_coast_in_ports(self):
        self.assertIn("Australia West Coast", PORTS)
        lat, lon = PORTS["Australia West Coast"]
        self.assertAlmostEqual(lat, -20.32, places=2)
        self.assertAlmostEqual(lon, 118.57, places=2)

    def test_australia_west_coast_weather_autofill_and_staleness(self):
        # Clear existing weather rows to test specific fixtures cleanly
        with database.get_connection() as conn:
            conn.execute("DELETE FROM weather_data")
            conn.commit()

        # 1. Insert fresh weather for Australia West Coast
        fresh_ts = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        with database.get_connection() as conn:
            conn.execute(
                """INSERT INTO weather_data
                   (port, latitude, longitude, wind_kmh, wave_height_m, cyclone_risk,
                    weather_delay_days, temperature_c, fetched_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ("Australia West Coast", -20.32, 118.57, 28.0, 1.8, 1.0, 0.15, 29.0, fresh_ts),
            )
            conn.commit()

        payload = {
            "origin": "Australia West Coast",
            "destination": "East Coast India",
            "commodity": "Iron Ore",
            "vessel_type": "Capesize",
            "current_freight_usd_per_tonne": 10.5,
            "bdi": 1560,
            "vlsfo_usd_per_tonne": 638,
            "coal_price_usd_per_mt": 124,
            "iron_ore_price_usd_per_dmt": 124,
            # Weather omitted: will auto-fill from Australia West Coast DB record
        }
        resp = self.client.post("/predict", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("weather_db[Australia West Coast@", data["sources"]["wind_kmh"])
        self.assertNotIn("STALE", data["sources"]["wind_kmh"])

        # 2. Insert STALE weather (3 days old)
        stale_dt = datetime.now(timezone.utc) - timedelta(days=3)
        stale_ts = stale_dt.isoformat(timespec="seconds").replace("+00:00", "Z")
        with database.get_connection() as conn:
            conn.execute(
                """INSERT INTO weather_data
                   (port, latitude, longitude, wind_kmh, wave_height_m, cyclone_risk,
                    weather_delay_days, temperature_c, fetched_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ("Taboneo", -3.65, 114.85, 15.0, 1.0, 0.5, 0.0, 27.0, stale_ts),
            )
            conn.commit()

        payload_taboneo = {
            "origin": "Taboneo",
            "destination": "East Coast India",
            "commodity": "Thermal Coal",
            "vessel_type": "Panamax",
            "current_freight_usd_per_tonne": 11.0,
            "bdi": 1560,
            "vlsfo_usd_per_tonne": 638,
            "coal_price_usd_per_mt": 124,
            "iron_ore_price_usd_per_dmt": 124,
        }
        resp_tab = self.client.post("/predict", json=payload_taboneo)
        self.assertEqual(resp_tab.status_code, 200)
        data_tab = resp_tab.json()
        self.assertIn("STALE", data_tab["sources"]["wind_kmh"])

    def test_prediction_telemetry_logged_in_database(self):
        payload = {
            "origin": "Hay Point",
            "destination": "East Coast India",
            "commodity": "Coal",
            "vessel_type": "Panamax",
            "current_freight_usd_per_tonne": 16.5,
            "bdi": 1560,
            "vlsfo_usd_per_tonne": 638,
            "coal_price_usd_per_mt": 124,
            "iron_ore_price_usd_per_dmt": 124,
            "wind_kmh": 32,
            "wave_height_m": 2.0,
            "cyclone_risk": 2,
            "weather_delay_days": 0.5,
        }
        resp = self.client.post("/predict", json=payload)
        self.assertEqual(resp.status_code, 200)

        logs = database.get_recent_prediction_logs(limit=5)
        self.assertGreater(len(logs), 0)
        latest = logs[0]
        self.assertEqual(latest["origin"], "Hay Point")
        self.assertEqual(latest["commodity"], "Coal")
        self.assertGreater(latest["predicted_next_month_freight_usd_per_tonne"], 0)
        self.assertIn(latest["risk_level"], ["LOW", "MEDIUM", "HIGH"])


if __name__ == "__main__":
    unittest.main()
