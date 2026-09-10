"""Tests for NaviFreight Phase 2: Data Credibility & Decision Intelligence."""

import unittest
from fastapi.testclient import TestClient
from main import app
from predict import predict_freight
from services import (
    decision_service,
    forecast_service,
    landed_cost_service,
    procurement_service,
    vessel_service,
)
from data.market import MarketProvenanceState


class TestPhase2DecisionIntelligence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_forecast_separation_base_vs_operational(self):
        """Task 1: Verify separation of pure statistical ARIMA base forecast and operational adjustment."""
        payload = {
            "origin": "Australia West Coast",
            "destination": "East Coast India",
            "commodity": "Iron Ore",
            "vessel_type": "Capesize",
            "current_freight_usd_per_tonne": 10.0,
            "bdi": 1500.0,
            "vlsfo_usd_per_tonne": 600.0,
            "coal_price_usd_per_mt": 124.0,
            "iron_ore_price_usd_per_dmt": 124.0,
            "weather_delay_days": 0.0,
            "cyclone_risk": 0.0,
            "wind_kmh": 0.0,
            "wave_height_m": 0.0,
        }
        res = predict_freight(payload)
        self.assertIn("base_forecast", res)
        self.assertIn("operational_adjustment", res)
        self.assertIn("expected_freight", res)
        self.assertIn("forecast_low", res)
        self.assertIn("forecast_high", res)

        # Base forecast should be numeric and >= 1.0
        self.assertGreaterEqual(res["base_forecast"], 1.0)
        self.assertAlmostEqual(res["expected_freight"], round(res["base_forecast"] + res["operational_adjustment"], 2), places=2)

        # In anchor explanation
        anchor = res["explanation"]["anchor"]
        self.assertIn("base_forecast", anchor)
        self.assertIn("operational_adjustment", anchor)
        self.assertIn("expected_freight", anchor)

    def test_market_data_provenance_states(self):
        """Task 2 & 8: Verify clear provenance states: USER_PROVIDED vs HISTORICAL_FALLBACK vs UNAVAILABLE."""
        # 1. User provided
        user_input = {
            "origin": "Hay Point",
            "destination": "East Coast India",
            "commodity": "Coal",
            "vessel_type": "Panamax",
            "current_freight_usd_per_tonne": 16.5,
            "bdi": 1600.0,
            "vlsfo_usd_per_tonne": 650.0,
            "coal_price_usd_per_mt": 124.0,
            "iron_ore_price_usd_per_dmt": 124.0,
            "wind_kmh": 25.0,
            "wave_height_m": 1.5,
            "cyclone_risk": 0.0,
            "weather_delay_days": 0.0,
        }
        merged, sources = forecast_service.build_forecast_input(user_input)
        self.assertEqual(sources["bdi"], "user:USER_PROVIDED")
        self.assertEqual(sources["vlsfo_usd_per_tonne"], "user:USER_PROVIDED")
        self.assertEqual(sources["coal_price_usd_per_mt"], "user:USER_PROVIDED")

        # 2. MarketProvenanceState enum values
        self.assertEqual(MarketProvenanceState.LIVE.value, "LIVE")
        self.assertEqual(MarketProvenanceState.HISTORICAL_FALLBACK.value, "HISTORICAL_FALLBACK")
        self.assertEqual(MarketProvenanceState.USER_PROVIDED.value, "USER_PROVIDED")
        self.assertEqual(MarketProvenanceState.UNAVAILABLE.value, "UNAVAILABLE")

    def test_independent_cargo_and_charter_decisions(self):
        """Task 3: Verify cargo decision and freight charter decision remain decoupled and distinct."""
        res = decision_service.analyze_decision(
            origin="Hay Point",
            destination="Dhamra",
            commodity="Coal",
            cargo_tonnes=75000,
            current_freight_usd_per_tonne=16.5,
        )
        self.assertIn("cargo_decision", res)
        self.assertIn("charter_decision", res)
        self.assertIn("overall_strategy", res)
        self.assertIn(res["cargo_decision"], ["BUY CARGO", "MONITOR CARGO", "WAIT TO BUY"])
        self.assertIn(res["charter_decision"], ["CHARTER NOW", "MONITOR FREIGHT", "WAIT TO CHARTER", "NO SUITABLE VESSEL"])
        self.assertTrue(res["overall_strategy"].startswith("BUY") or res["overall_strategy"].startswith("MONITOR") or res["overall_strategy"].startswith("WAIT"))

    def test_arbitrary_cargo_volumes_no_bucketing(self):
        """Task 4: Test exact arbitrary cargo volume integers reaching backend without rounding/bucketing."""
        test_volumes = [12345, 18437, 46038, 51729, 82741, 100123, 127843, 150001, 165700, 181999]
        for vol in test_volumes:
            res = vessel_service.optimize_vessel_chartering(
                origin="Australia West Coast",
                destination="Dhamra",
                commodity="Iron Ore",
                cargo_tonnes=vol,
            )
            self.assertEqual(res["cargo_tonnes"], float(vol))
            self.assertEqual(len(res["evaluated_vessels"]), 4)
            for ev in res["evaluated_vessels"]:
                self.assertEqual(ev["cargo_tonnes"], float(vol))
                # Capacity utilization calculation is exact
                expected_util = round((vol / ev["standard_dwt"]) * 100.0, 1)
                self.assertEqual(ev["utilization_pct"], expected_util)

    def test_vessel_optimization_evaluation_all_four_classes(self):
        """Task 4: Confirm Handysize, Supramax, Panamax, Capesize are evaluated dynamically."""
        res = vessel_service.optimize_vessel_chartering(
            origin="Hay Point",
            destination="Dhamra",
            commodity="Coal",
            cargo_tonnes=80000,
        )
        vessel_classes = {ev["vessel_type"] for ev in res["evaluated_vessels"]}
        self.assertEqual(vessel_classes, {"Capesize", "Panamax", "Supramax", "Handysize"})
        self.assertEqual(res["status"], "OPTIMIZED")
        self.assertEqual(res["recommended_vessel"], "Panamax")

    def test_port_draft_rejection_integrity(self):
        """Task 5: Verify port constraints are evaluated from port_constraints.csv without blanket claims."""
        # 1. Dhamra (18.0m draft): Capesize suitable
        res_dhamra = vessel_service.optimize_vessel_chartering(
            origin="Hay Point",
            destination="Dhamra",
            commodity="Coal",
            cargo_tonnes=160000,
        )
        self.assertEqual(res_dhamra["status"], "OPTIMIZED")
        self.assertEqual(res_dhamra["recommended_vessel"], "Capesize")

        # 2. Paradip (14.5m draft): Capesize rejected due to 18.2m draft > 14.5m
        res_paradip = vessel_service.optimize_vessel_chartering(
            origin="Hay Point",
            destination="Paradip",
            commodity="Coal",
            cargo_tonnes=160000,
        )
        self.assertEqual(res_paradip["status"], "NO_SUITABLE_VESSEL")
        capesize_eval = next(v for v in res_paradip["evaluated_vessels"] if v["vessel_type"] == "Capesize")
        self.assertFalse(capesize_eval["port_compatible"])
        self.assertIn("exceeds Paradip operational draft limit (14.50m)", " ".join(capesize_eval["reasons"]))

        # 3. Haldia (8.0m draft): All major bulk carriers rejected
        res_haldia = vessel_service.optimize_vessel_chartering(
            origin="Hay Point",
            destination="Haldia",
            commodity="Coal",
            cargo_tonnes=70000,
        )
        self.assertEqual(res_haldia["status"], "NO_SUITABLE_VESSEL")

    def test_procurement_logic_when_to_buy(self):
        """Task 6: Verify procurement logic determines WHEN to buy the selected commodity."""
        # Test Coal
        coal_val = procurement_service.calculate_procurement_valuation("Coal")
        self.assertEqual(coal_val["commodity"], "Coal")
        self.assertIn(coal_val["signal"], ["BUY", "MONITOR", "WAIT"])
        self.assertGreater(coal_val["benchmark_price_usd_per_mt"], 0)
        self.assertTrue(0.0 <= coal_val["percentile"] <= 100.0)

        # Test Iron Ore
        iron_val = procurement_service.calculate_procurement_valuation("Iron Ore")
        self.assertEqual(iron_val["commodity"], "Iron Ore")
        self.assertIn(iron_val["signal"], ["BUY", "MONITOR", "WAIT"])
        self.assertGreater(iron_val["benchmark_price_usd_per_mt"], 0)

    def test_landed_cost_formula_and_explicit_exclusions(self):
        """Task 7: Verify landed cost transparent formula and explicit exclusions list."""
        res = landed_cost_service.calculate_landed_cost(
            commodity="Coal",
            commodity_fob_usd=124.0,
            ocean_freight_usd_per_tonne=16.5,
            cargo_tonnes=75000,
        )
        self.assertEqual(res["estimated_landed_cost_usd"], 140.5)
        self.assertEqual(res["estimated_total_landed_outlay_usd"], 10537500.0)
        self.assertEqual(res["formula"], "Landed Cost = Commodity FOB + Ocean Freight")
        self.assertIn("exclusions", res)
        self.assertGreater(len(res["exclusions"]), 0)
        self.assertTrue(any("Customs" in ex for ex in res["exclusions"]))
        self.assertTrue(any("GST" in ex for ex in res["exclusions"]))
        self.assertTrue(any("insurance" in ex.lower() for ex in res["exclusions"]))

    def test_api_endpoints_compatibility(self):
        """Task 9: Verify all primary API endpoints return 200 and adhere to response contracts."""
        # 1. /predict
        pred_res = self.client.post("/predict", json={
            "origin": "Hay Point",
            "destination": "East Coast India",
            "commodity": "Coal",
            "vessel_type": "Panamax",
            "current_freight_usd_per_tonne": 16.5,
            "bdi": 1500.0,
            "vlsfo_usd_per_tonne": 600.0,
            "coal_price_usd_per_mt": 124.0,
            "iron_ore_price_usd_per_dmt": 124.0,
            "weather_delay_days": 0.0,
            "cyclone_risk": 0.0,
            "wind_kmh": 0.0,
            "wave_height_m": 0.0,
        })
        self.assertEqual(pred_res.status_code, 200)
        pred_json = pred_res.json()
        self.assertIn("base_forecast", pred_json)
        self.assertIn("operational_adjustment", pred_json)
        self.assertIn("expected_freight", pred_json)

        # 2. /decision/analyze
        dec_res = self.client.post("/decision/analyze", json={
            "origin": "Australia West Coast",
            "destination": "Dhamra",
            "commodity": "Iron Ore",
            "cargo_tonnes": 160000,
            "current_freight_usd_per_tonne": 10.0,
        })
        self.assertEqual(dec_res.status_code, 200)
        dec_json = dec_res.json()
        self.assertIn("cargo_decision", dec_json)
        self.assertIn("charter_decision", dec_json)
        self.assertIn("overall_strategy", dec_json)
        self.assertIn("exclusions", dec_json["landed_cost"])

        # 3. /vessel/optimize
        vess_res = self.client.post("/vessel/optimize", json={
            "origin": "Hay Point",
            "destination": "Dhamra",
            "commodity": "Coal",
            "cargo_tonnes": 75000,
        })
        self.assertEqual(vess_res.status_code, 200)

        # 4. /procurement/valuation
        proc_res = self.client.get("/procurement/valuation?commodity=Coal")
        self.assertEqual(proc_res.status_code, 200)

        # 2. /decision/analyze
        dec_res = self.client.post("/decision/analyze", json={
            "origin": "Australia West Coast",
            "destination": "Dhamra",
            "commodity": "Iron Ore",
            "cargo_tonnes": 160000,
            "current_freight_usd_per_tonne": 10.0,
        })
        self.assertEqual(dec_res.status_code, 200)
        dec_json = dec_res.json()
        self.assertIn("cargo_decision", dec_json)
        self.assertIn("charter_decision", dec_json)
        self.assertIn("overall_strategy", dec_json)
        self.assertIn("exclusions", dec_json["landed_cost"])

        # 3. /vessel/optimize
        vess_res = self.client.post("/vessel/optimize", json={
            "origin": "Hay Point",
            "destination": "Dhamra",
            "commodity": "Coal",
            "cargo_tonnes": 75000,
        })
        self.assertEqual(vess_res.status_code, 200)

        # 4. /procurement/valuation
        proc_res = self.client.get("/procurement/valuation?commodity=Coal")
        self.assertEqual(proc_res.status_code, 200)


if __name__ == "__main__":
    unittest.main()
