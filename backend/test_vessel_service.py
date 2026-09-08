"""Automated Test Suite for Vessel Suitability & Chartering Decision Service.

Tests:
- Authentic Baltic vessel specifications loading and dimension verification
- East Coast India port constraint loading and hydrographic limits
- Cargo-volume fit and deadfreight/overload eligibility boundaries
- Physical draft compatibility against port constraints (e.g. Paradip vs Dhamra vs Haldia)
- Trade lane / canonical corridor operational viability
- Total freight outlay calculation (predicted_freight * cargo_tonnes)
- Recommendation selection based on multi-criteria suitability (not merely lowest $/t)
- Structured "NO_SUITABLE_VESSEL" output when no class is feasible
- FastAPI integration for POST /vessel/optimize with schema and error validation
"""

import sys
import unittest
from pathlib import Path
import pandas as pd
from fastapi.testclient import TestClient

_BACKEND_DIR = Path(__file__).resolve().parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from main import app
from services import vessel_service
from services.vessel_service import (
    VESSEL_SPECS_PATH,
    PORT_CONSTRAINTS_PATH,
    BALTIC_ROUTES_PATH,
    load_vessel_specs,
    load_port_constraints,
    load_baltic_routes,
    check_port_compatibility,
    optimize_vessel_chartering,
)


class TestVesselService(unittest.TestCase):
    """Comprehensive automated tests for NaviFreight vessel suitability service."""

    def setUp(self):
        self.client = TestClient(app)

    # -------------------------------------------------------------------------
    # 1. Vessel Specifications Loading
    # -------------------------------------------------------------------------
    def test_vessel_specs_loading_and_dimensions(self):
        """Verify authentic Baltic Exchange vessel specifications exist and have exact dimensions."""
        self.assertTrue(VESSEL_SPECS_PATH.exists(), f"Vessel specs missing at {VESSEL_SPECS_PATH}")
        df = load_vessel_specs()
        self.assertIsInstance(df, pd.DataFrame)
        self.assertGreaterEqual(len(df), 3)

        v_map = df.set_index("vessel_type").to_dict(orient="index")
        self.assertIn("Capesize", v_map)
        self.assertIn("Panamax", v_map)
        self.assertIn("Supramax", v_map)

        # Authentic dimensions check
        self.assertEqual(float(v_map["Capesize"]["standard_dwt"]), 182000.0)
        self.assertEqual(float(v_map["Capesize"]["draft_m"]), 18.20)

        self.assertEqual(float(v_map["Panamax"]["standard_dwt"]), 82500.0)
        self.assertEqual(float(v_map["Panamax"]["draft_m"]), 14.43)

        self.assertEqual(float(v_map["Supramax"]["standard_dwt"]), 58328.0)
        self.assertEqual(float(v_map["Supramax"]["draft_m"]), 12.80)

    # -------------------------------------------------------------------------
    # 2. Port Constraint Loading
    # -------------------------------------------------------------------------
    def test_port_constraints_loading(self):
        """Verify East Coast India port constraints load correctly with draft limits."""
        self.assertTrue(PORT_CONSTRAINTS_PATH.exists(), f"Port constraints missing at {PORT_CONSTRAINTS_PATH}")
        df = load_port_constraints()
        self.assertIsInstance(df, pd.DataFrame)
        self.assertGreaterEqual(len(df), 7)

        ports = df["port"].tolist()
        self.assertIn("Dhamra", ports)
        self.assertIn("Paradip", ports)
        self.assertIn("Haldia", ports)
        self.assertIn("Visakhapatnam", ports)

        p_map = df.set_index("port").to_dict(orient="index")
        self.assertEqual(float(p_map["Dhamra"]["operational_draft_m"]), 18.00)
        self.assertEqual(bool(p_map["Dhamra"]["capesize_compatible"]), True)

        self.assertEqual(float(p_map["Paradip"]["operational_draft_m"]), 14.50)
        self.assertEqual(bool(p_map["Paradip"]["capesize_compatible"]), False)
        self.assertEqual(bool(p_map["Paradip"]["panamax_compatible"]), True)

        self.assertEqual(float(p_map["Haldia"]["operational_draft_m"]), 8.00)
        self.assertEqual(bool(p_map["Haldia"]["capesize_compatible"]), False)
        self.assertEqual(bool(p_map["Haldia"]["panamax_compatible"]), False)

    # -------------------------------------------------------------------------
    # 3. Baltic Route Specs Loading (Reference Only)
    # -------------------------------------------------------------------------
    def test_baltic_routes_reference_loading(self):
        """Verify Baltic route benchmark specifications load as reference definitions."""
        self.assertTrue(BALTIC_ROUTES_PATH.exists(), f"Baltic routes missing at {BALTIC_ROUTES_PATH}")
        df = load_baltic_routes()
        self.assertIsInstance(df, pd.DataFrame)
        codes = df["route_code"].tolist()
        self.assertIn("C18", codes)
        self.assertIn("P9", codes)

    # -------------------------------------------------------------------------
    # 4. Draft Compatibility Checks
    # -------------------------------------------------------------------------
    def test_draft_compatibility_paradip(self):
        """Paradip has 14.50m draft limit: Capesize (18.2m) must be excluded; Panamax (14.43m) allowed."""
        # Capesize at Paradip -> Incompatible
        ok_cape, reason_cape = check_port_compatibility("Capesize", 18.20, "Paradip")
        self.assertFalse(ok_cape)
        self.assertIn("exceeds Paradip operational draft limit", reason_cape)

        # Panamax at Paradip -> Compatible
        ok_pan, reason_pan = check_port_compatibility("Panamax", 14.43, "Paradip")
        self.assertTrue(ok_pan)
        self.assertIn("accommodates fully laden Panamax", reason_pan)

        # Supramax at Paradip -> Compatible (12.80m <= 14.50m)
        ok_sup, reason_sup = check_port_compatibility("Supramax", 12.80, "Paradip")
        self.assertTrue(ok_sup)

    def test_draft_compatibility_dhamra(self):
        """Dhamra is a deepwater port (18.00m permissible draft) accommodating Capesize."""
        ok_cape, reason_cape = check_port_compatibility("Capesize", 18.20, "Dhamra")
        self.assertTrue(ok_cape)
        self.assertIn("accommodates Capesize bulk carriers", reason_cape)

    def test_draft_compatibility_haldia(self):
        """Haldia has 8.00m riverine draft: all standard bulk carriers must be excluded."""
        ok_cape, _ = check_port_compatibility("Capesize", 18.20, "Haldia")
        self.assertFalse(ok_cape)

        ok_pan, _ = check_port_compatibility("Panamax", 14.43, "Haldia")
        self.assertFalse(ok_pan)

        ok_sup, _ = check_port_compatibility("Supramax", 12.80, "Haldia")
        self.assertFalse(ok_sup)

    # -------------------------------------------------------------------------
    # 5. Cargo Volume Eligibility & Deadfreight / Overload Logic
    # -------------------------------------------------------------------------
    def test_cargo_volume_deadfreight_exclusion(self):
        """A 75,000 mt parcel must exclude Capesize (182k DWT) due to uneconomic deadfreight (<45% util)."""
        res = optimize_vessel_chartering(
            origin="Hay Point",
            destination="East Coast India",
            commodity="Coal",
            cargo_tonnes=75000,
        )
        self.assertEqual(res["status"], "OPTIMIZED")
        # Find Capesize evaluation
        cape_eval = next(v for v in res["evaluated_vessels"] if v["vessel_type"] == "Capesize")
        self.assertFalse(cape_eval["cargo_fit"])
        self.assertFalse(cape_eval["eligible"])
        self.assertTrue(any("underutilizes Capesize" in r for r in cape_eval["reasons"]))

        # Panamax (82.5k DWT) must be eligible and recommended
        pan_eval = next(v for v in res["evaluated_vessels"] if v["vessel_type"] == "Panamax")
        self.assertTrue(pan_eval["cargo_fit"])
        self.assertTrue(pan_eval["eligible"])
        self.assertEqual(res["recommended_vessel"], "Panamax")

    def test_cargo_volume_overload_exclusion(self):
        """A 160,000 mt parcel must exclude Panamax (82.5k DWT) and Supramax (58.3k DWT) as physical overloads."""
        res = optimize_vessel_chartering(
            origin="Hay Point",
            destination="East Coast India",
            commodity="Coal",
            cargo_tonnes=160000,
        )
        self.assertEqual(res["status"], "OPTIMIZED")
        self.assertEqual(res["recommended_vessel"], "Capesize")

        pan_eval = next(v for v in res["evaluated_vessels"] if v["vessel_type"] == "Panamax")
        self.assertFalse(pan_eval["cargo_fit"])
        self.assertFalse(pan_eval["eligible"])
        self.assertTrue(any("exceeds Panamax maximum capacity" in r for r in pan_eval["reasons"]))

        sup_eval = next(v for v in res["evaluated_vessels"] if v["vessel_type"] == "Supramax")
        self.assertFalse(sup_eval["cargo_fit"])
        self.assertFalse(sup_eval["eligible"])

    # -------------------------------------------------------------------------
    # 6. Trade Lane / Corridor Support
    # -------------------------------------------------------------------------
    def test_unsupported_corridor_vessel(self):
        """Capesize is not an active canonical vessel on the Taboneo -> East Coast India lane."""
        res = optimize_vessel_chartering(
            origin="Taboneo",
            destination="East Coast India",
            commodity="Thermal Coal",
            cargo_tonnes=70000,
        )
        cape_eval = next(v for v in res["evaluated_vessels"] if v["vessel_type"] == "Capesize")
        self.assertFalse(cape_eval["corridor_supported"])
        self.assertFalse(cape_eval["eligible"])
        self.assertTrue(any("not an active canonical vessel class" in r for r in cape_eval["reasons"]))

    def test_unsupported_origin_validation(self):
        """Unsupported origin should raise ValueError with supported corridor hints."""
        with self.assertRaises(ValueError) as ctx:
            optimize_vessel_chartering(
                origin="Rotterdam",
                destination="East Coast India",
                commodity="Coal",
                cargo_tonnes=75000,
            )
        self.assertIn("Unsupported origin", str(ctx.exception))

    # -------------------------------------------------------------------------
    # 7. Outlay Arithmetic & Model v3 Integration
    # -------------------------------------------------------------------------
    def test_freight_outlay_calculation(self):
        """Verify estimated_freight_outlay_usd = predicted_freight_usd_per_tonne * cargo_tonnes."""
        cargo = 150000.0
        res = optimize_vessel_chartering(
            origin="Hay Point",
            destination="Dhamra",
            commodity="Coal",
            cargo_tonnes=cargo,
        )
        cape_eval = next(v for v in res["evaluated_vessels"] if v["vessel_type"] == "Capesize")
        self.assertTrue(cape_eval["eligible"])
        pred_rate = cape_eval["predicted_freight_usd_per_tonne"]
        outlay = cape_eval["estimated_freight_outlay_usd"]

        self.assertIsNotNone(pred_rate)
        self.assertGreater(pred_rate, 5.0)
        expected_outlay = round(pred_rate * cargo, 2)
        self.assertEqual(outlay, expected_outlay)

    # -------------------------------------------------------------------------
    # 8. Recommendation Selection Multi-Criteria
    # -------------------------------------------------------------------------
    def test_recommendation_selection_multi_criteria(self):
        """Recommendation chooses highest suitability score (capacity fit + economics + corridor)."""
        res = optimize_vessel_chartering(
            origin="Hay Point",
            destination="East Coast India",
            commodity="Coal",
            cargo_tonnes=150000,
        )
        self.assertEqual(res["status"], "OPTIMIZED")
        self.assertEqual(res["recommended_vessel"], "Capesize")

        winner_eval = next(v for v in res["evaluated_vessels"] if v["vessel_type"] == res["recommended_vessel"])
        self.assertGreater(winner_eval["suitability_score"], 60.0)

    # -------------------------------------------------------------------------
    # 9. No Suitable Vessel Structured Case
    # -------------------------------------------------------------------------
    def test_no_suitable_vessel_draft_infeasible(self):
        """Large cargo (150,000 mt) to Paradip must return NO_SUITABLE_VESSEL due to draft and overload limits."""
        res = optimize_vessel_chartering(
            origin="Hay Point",
            destination="Paradip",
            commodity="Coal",
            cargo_tonnes=150000,
        )
        self.assertEqual(res["status"], "NO_SUITABLE_VESSEL")
        self.assertIsNone(res["recommended_vessel"])
        self.assertIn("No suitable vessel class found", res["recommendation_reason"])

        # Capesize was excluded for port draft
        cape = next(v for v in res["evaluated_vessels"] if v["vessel_type"] == "Capesize")
        self.assertFalse(cape["port_compatible"])
        self.assertFalse(cape["eligible"])

        # Panamax was excluded for capacity overload
        pan = next(v for v in res["evaluated_vessels"] if v["vessel_type"] == "Panamax")
        self.assertFalse(pan["cargo_fit"])
        self.assertFalse(pan["eligible"])

    def test_no_suitable_vessel_haldia_shallow(self):
        """Any standard bulk shipment to Haldia must return NO_SUITABLE_VESSEL due to riverine shallow draft."""
        res = optimize_vessel_chartering(
            origin="Hay Point",
            destination="Haldia",
            commodity="Coal",
            cargo_tonnes=75000,
        )
        self.assertEqual(res["status"], "NO_SUITABLE_VESSEL")
        self.assertIsNone(res["recommended_vessel"])

    # -------------------------------------------------------------------------
    # 10. API Integration: POST /vessel/optimize
    # -------------------------------------------------------------------------
    def test_api_optimize_vessel_valid(self):
        """Verify POST /vessel/optimize endpoint returns 200 with valid schema."""
        payload = {
            "origin": "Hay Point",
            "destination": "Dhamra",
            "commodity": "Coal",
            "cargo_tonnes": 150000,
        }
        resp = self.client.post("/vessel/optimize", json=payload)
        self.assertEqual(resp.status_code, 200, f"Error: {resp.text}")
        data = resp.json()

        self.assertEqual(data["origin"], "Hay Point")
        self.assertEqual(data["destination"], "Dhamra")
        self.assertEqual(data["status"], "OPTIMIZED")
        self.assertEqual(data["recommended_vessel"], "Capesize")
        self.assertIsInstance(data["evaluated_vessels"], list)
        self.assertEqual(len(data["evaluated_vessels"]), 3)

        # Check required evaluation item fields
        first = data["evaluated_vessels"][0]
        self.assertIn("vessel_type", first)
        self.assertIn("standard_dwt", first)
        self.assertIn("draft_m", first)
        self.assertIn("cargo_tonnes", first)
        self.assertIn("utilization_pct", first)
        self.assertIn("port_compatible", first)
        self.assertIn("cargo_fit", first)
        self.assertIn("eligible", first)
        self.assertIn("suitability_score", first)
        self.assertIn("reasons", first)

    def test_api_optimize_vessel_invalid_cargo(self):
        """Verify POST /vessel/optimize returns 422 for non-positive cargo."""
        payload = {
            "origin": "Hay Point",
            "destination": "Dhamra",
            "commodity": "Coal",
            "cargo_tonnes": 0,
        }
        resp = self.client.post("/vessel/optimize", json=payload)
        self.assertEqual(resp.status_code, 422)
        data = resp.json()
        self.assertEqual(data["error_code"], "INVALID_VESSEL_OPTIMIZATION_INPUT")

    def test_api_optimize_vessel_invalid_origin(self):
        """Verify POST /vessel/optimize returns 422 for unsupported origin."""
        payload = {
            "origin": "Antwerp",
            "destination": "Dhamra",
            "commodity": "Coal",
            "cargo_tonnes": 75000,
        }
        resp = self.client.post("/vessel/optimize", json=payload)
        self.assertEqual(resp.status_code, 422)
        data = resp.json()
        self.assertEqual(data["error_code"], "INVALID_VESSEL_OPTIMIZATION_INPUT")


if __name__ == "__main__":
    unittest.main()
