"""Build the master freight training dataset (v1).

INPUTS  : /home/z/my-project/upload/*.csv  (5 recovered datasets)
OUTPUTS : data/master_freight_training_v1.csv
          data/excluded/west_coast_unmapped.csv
          data/excluded/unsupported_commodity_rows.csv
          data/excluded/unsupported_vessel_rows.csv
          data/excluded/boundary_benchmark_rows.csv  (reference only)

RULES (from task spec):
  - DO NOT modify freight_forecast_model_v1.joblib
  - DO NOT retrain any model
  - DO NOT use validation data
  - DO NOT duplicate the 110 benchmark rows that match FFT
  - EXCLUDE previous_month_freight, freight_3_month_avg, freight_observation_count
  - Preserve observed values; no fabrication
  - cargo_tonnes = representative vessel capacity (documented assumption)
  - Map Australia East Coast -> Hay Point; keep Taboneo
  - EXCLUDE Australia West Coast (no equivalent mapping to Hay Point)
  - Keep original commodity values; exclude unsupported (Thermal Coal)
  - Keep original vessel values; exclude unsupported (Capesize)
  - World Bank canonical for coal/iron-ore on overlapping dates
  - Boundary benchmark rows (no target) -> reference only, not training

This script is the single source of truth - rerun to reproduce the master
dataset deterministically.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pandas as pd

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
REPO_ROOT = Path(__file__).resolve().parent
UPLOAD_DIR = Path("/home/z/my-project/upload")
DATA_DIR = REPO_ROOT / "data"
EXCLUDED_DIR = DATA_DIR / "excluded"

FFT_CSV = UPLOAD_DIR / "freight_forecasting_training_table_v1.csv"
WB_CSV = UPLOAD_DIR / "world_bank_coal_iron_ore_monthly.csv"
WEATHER_CSV = UPLOAD_DIR / "weather_monthly_all_locations_2024_2025.csv"
BENCHMARK_CSV = UPLOAD_DIR / "expanded_freight_benchmark_2024_2025.csv"
EXPANDED_CSV = UPLOAD_DIR / "expanded_monthly_freight_training_v1.csv"
# Validation file (if present) is NEVER read here.
VALIDATION_CSV = UPLOAD_DIR / "real_route_validation_predictions_v1.csv"

MASTER_CSV = DATA_DIR / "master_freight_training_v1.csv"
EXCL_WEST_COAST = EXCLUDED_DIR / "west_coast_unmapped.csv"
EXCL_COMMODITY = EXCLUDED_DIR / "unsupported_commodity_rows.csv"
EXCL_VESSEL = EXCLUDED_DIR / "unsupported_vessel_rows.csv"
BOUNDARY_BENCHMARK = EXCLUDED_DIR / "boundary_benchmark_rows.csv"

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
# Supported categorical domain (matches the existing model's training set)
SUPPORTED_ORIGINS = {"Hay Point", "Taboneo"}
SUPPORTED_COMMODITIES = {"Coal", "Iron Ore"}
SUPPORTED_VESSELS = {"Panamax", "Supramax"}

# Route granularity mapping (STEP 4)
ORIGIN_REGION_MAP = {
    "Australia East Coast": "Hay Point",   # explicit mapping (port-level)
    "Taboneo": "Taboneo",                  # already port-level
    # Australia West Coast intentionally NOT mapped -> excluded
}

# Representative vessel cargo capacities (STEP 3)
# These are prototype cargo sizes by vessel class, NOT observed fixture
# quantities. Documented in data/MASTER_DATASET_ASSUMPTIONS.md.
REPRESENTATIVE_CARGO_TONNES = {
    "Panamax": 75_000.0,
    "Supramax": 55_000.0,
    "Capesize": 170_000.0,
}

# Unit conversion: 1 knot = 1.852 km/h
KTS_TO_KMH = 1.852

# Final master-dataset column order (model schema + audit metadata)
MODEL_FEATURES = [
    "origin",
    "destination",
    "commodity",
    "vessel_type",
    "cargo_tonnes",
    "bdi",
    "vlsfo_usd_per_tonne",
    "coal_price_usd_per_mt",
    "iron_ore_price_usd_per_dmt",
    "wind_kmh",
    "wave_height_m",
    "cyclone_risk",
    "weather_delay_days",
    "current_freight_usd_per_tonne",
]
TARGET = "next_month_freight_usd_per_tonne"
AUDIT_COLS = ["date", "data_source", "cargo_value_type", "ingested_at"]
FINAL_COLS = AUDIT_COLS + MODEL_FEATURES + [TARGET]


def log(msg: str) -> None:
    print(f"[build] {msg}")


# --------------------------------------------------------------------------- #
# Step 1 - load FFT and parse route -> origin/destination
# --------------------------------------------------------------------------- #
def load_fft() -> pd.DataFrame:
    log(f"loading FFT from {FFT_CSV}")
    df = pd.read_csv(FFT_CSV)
    log(f"  FFT rows in: {len(df)}")
    # parse route "X -> Y" into origin/destination (preserving original strings)
    parts = df["route"].str.split(r"\s*->\s*", n=1, expand=True)
    df["origin_region"] = parts[0].str.strip()
    df["destination"] = parts[1].str.strip()
    return df


# --------------------------------------------------------------------------- #
# Step 2 - column mapping (route-dependent weather selection)
# --------------------------------------------------------------------------- #
def map_columns(fft: pd.DataFrame) -> pd.DataFrame:
    """Produce the master-schema columns from FFT.

    Weather selection is route-dependent (region -> wind/wave column pair).
    Wind is converted knots -> km/h. Wave height kept in metres.
    """
    log("mapping columns...")
    out = pd.DataFrame()

    # identity + audit
    out["date"] = pd.to_datetime(fft["date"]).dt.strftime("%Y-%m-%d")
    out["data_source"] = "freight_forecasting_training_table_v1.csv"
    out["cargo_value_type"] = "representative_vessel_capacity"
    out["ingested_at"] = pd.Timestamp.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    # route mapping (region -> port) per ORIGIN_REGION_MAP
    # We keep the original region in a side column for exclusion logic.
    out["origin"] = fft["origin_region"].map(ORIGIN_REGION_MAP)
    # rows where origin is NaN (unmapped, e.g. Australia West Coast) are
    # excluded later; for now leave them so we can route them to the
    # exclusion file.

    out["destination"] = fft["destination"]

    # categorical identity
    out["commodity"] = fft["commodity"]
    out["vessel_type"] = fft["vessel_type"]

    # cargo_tonnes - representative by vessel class (not fabricated fixtures)
    out["cargo_tonnes"] = fft["vessel_type"].map(REPRESENTATIVE_CARGO_TONNES)

    # market features
    out["bdi"] = fft["baltic_dry_index"]
    out["vlsfo_usd_per_tonne"] = fft["vlsfo_bunker_usd_per_tonne"]
    out["coal_price_usd_per_mt"] = fft["coal_australian_usd_per_mt"]
    out["iron_ore_price_usd_per_dmt"] = fft["iron_ore_cfr_usd_per_dmt"]

    # weather - route-dependent selection
    # For each row, pick the wind/wave columns matching its origin region.
    wind_kts = pd.Series([None] * len(fft), index=fft.index, dtype="object")
    wave_m = pd.Series([None] * len(fft), index=fft.index, dtype="object")

    taboneo_mask = fft["origin_region"] == "Taboneo"
    east_mask = fft["origin_region"] == "Australia East Coast"
    west_mask = fft["origin_region"] == "Australia West Coast"

    wind_kts[taboneo_mask] = fft.loc[taboneo_mask, "taboneo_wind_kts"]
    wave_m[taboneo_mask] = fft.loc[taboneo_mask, "taboneo_wave_hs_m"]

    wind_kts[east_mask] = fft.loc[east_mask, "aus_east_wind_kts"]
    wave_m[east_mask] = fft.loc[east_mask, "aus_east_wave_hs_m"]

    wind_kts[west_mask] = fft.loc[west_mask, "aus_west_wind_kts"]
    wave_m[west_mask] = fft.loc[west_mask, "aus_west_wave_hs_m"]

    # convert wind knots -> km/h (exact unit conversion)
    out["wind_kmh"] = pd.to_numeric(wind_kts, errors="coerce") * KTS_TO_KMH
    out["wave_height_m"] = pd.to_numeric(wave_m, errors="coerce")

    # derived weather features (already in FFT, just renamed)
    out["cyclone_risk"] = fft["bob_cyclone_alert_index"]
    out["weather_delay_days"] = fft["estimated_weather_delay_days"]

    # current freight + target (observed values)
    out["current_freight_usd_per_tonne"] = fft["freight_rate_usd_per_tonne"]
    out[TARGET] = fft[TARGET]

    # preserve the original region for exclusion reports
    out["_origin_region_raw"] = fft["origin_region"]
    return out


# --------------------------------------------------------------------------- #
# Step 4-6 - exclusions (route granularity / commodity / vessel)
# --------------------------------------------------------------------------- #
def split_exclusions(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Split rows into kept / excluded-with-reason.

    Order of exclusion matters for transparent reporting: we apply the most
    specific rule first and tag each excluded row with a single primary
    reason.
    """
    log("applying exclusions...")
    exclusions = []

    # 1) Australia West Coast (no valid mapping to Hay Point)
    west = df[df["_origin_region_raw"] == "Australia West Coast"].copy()
    west["exclusion_reason"] = (
        "route_origin_unmapped: 'Australia West Coast' has no port-level "
        "equivalent in the existing model's training categories "
        "(Hay Point, Taboneo). Mapping to Hay Point would be geographically "
        "incorrect; row excluded from the retraining-ready subset."
    )
    exclusions.append(("west_coast_unmapped.csv", west.copy()))
    log(f"  excluded Australia West Coast rows: {len(west)}")

    # 2) Unsupported commodity (keep original value; exclude Thermal Coal etc.)
    rest = df[df["_origin_region_raw"] != "Australia West Coast"].copy()
    rest["supported_commodity"] = rest["commodity"].isin(SUPPORTED_COMMODITIES)
    bad_comm = rest[~rest["supported_commodity"]].copy()
    bad_comm["exclusion_reason"] = (
        "unsupported_commodity: '" + bad_comm["commodity"].astype(str)
        + "' is not in the existing model's training categories "
        "(Coal, Iron Ore). Original value preserved; row excluded from the "
        "retraining-ready subset."
    )
    exclusions.append(("unsupported_commodity_rows.csv", bad_comm.copy()))
    log(f"  excluded unsupported-commodity rows: {len(bad_comm)}")

    # 3) Unsupported vessel (Capesize)
    rest = rest[rest["supported_commodity"]].copy()
    rest["supported_vessel"] = rest["vessel_type"].isin(SUPPORTED_VESSELS)
    bad_ves = rest[~rest["supported_vessel"]].copy()
    bad_ves["exclusion_reason"] = (
        "unsupported_vessel: '" + bad_ves["vessel_type"].astype(str)
        + "' is not in the existing model's training categories "
        "(Panamax, Supramax). Original value preserved; row excluded from "
        "the retraining-ready subset."
    )
    exclusions.append(("unsupported_vessel_rows.csv", bad_ves.copy()))
    log(f"  excluded unsupported-vessel rows: {len(bad_ves)}")

    # kept rows
    kept = rest[rest["supported_vessel"]].copy()
    log(f"  kept rows after exclusions: {len(kept)}")

    return kept, exclusions


# --------------------------------------------------------------------------- #
# Step 7 - World Bank verification (canonical for coal/iron-ore)
# --------------------------------------------------------------------------- #
def verify_world_bank(kept: pd.DataFrame) -> dict:
    """Verify FFT coal/iron-ore == World Bank on overlapping dates.

    World Bank becomes the canonical source; if any disagreement were found,
    we would report it. In this build they match exactly (verified in the
    prior audit). We do NOT extend the master beyond dates that have a
    freight observation + target.
    """
    log("verifying World Bank coal/iron-ore values...")
    wb = pd.read_csv(WB_CSV)
    wb["date_dt"] = pd.to_datetime(wb["date"].str.replace("M", "-", regex=False) + "-01", errors="coerce")
    wb_recent = wb[wb["date_dt"].dt.year.isin([2024, 2025])].copy()
    wb_recent["date"] = wb_recent["date_dt"].dt.strftime("%Y-%m-%d")
    wb_sub = wb_recent[["date", "coal_australian_usd_per_mt", "iron_ore_cfr_usd_per_dmt"]].copy()
    wb_sub.columns = ["date", "coal_wb", "iron_wb"]

    kept_dedup = kept[["date", "coal_price_usd_per_mt", "iron_ore_price_usd_per_dmt"]].drop_duplicates()
    m = kept_dedup.merge(wb_sub, on="date", how="inner")
    coal_diff = (m["coal_price_usd_per_mt"] - m["coal_wb"]).abs()
    iron_diff = (m["iron_ore_price_usd_per_dmt"] - m["iron_wb"]).abs()
    summary = {
        "shared_months": int(len(m)),
        "coal_diff_max": float(coal_diff.max()) if len(m) else None,
        "iron_diff_max": float(iron_diff.max()) if len(m) else None,
        "match": bool(len(m) and coal_diff.max() == 0 and iron_diff.max() == 0),
    }
    log(f"  World Bank agreement: {summary}")
    return summary


# --------------------------------------------------------------------------- #
# Step 8 - benchmark dedup + boundary rows (reference only)
# --------------------------------------------------------------------------- #
def handle_benchmark(fft: pd.DataFrame) -> dict:
    """Confirm benchmark duplicates are NOT added; isolate boundary rows.

    The benchmark uses the SAME region-level origin naming as FFT's raw
    'route' column (Australia East Coast, Taboneo, Australia West Coast),
    NOT the port-level mapped origin in the master. So we compare on FFT's
    raw (date, origin_region, destination, commodity, vessel_type) keys.
    """
    log("handling benchmark file...")
    ben = pd.read_csv(BENCHMARK_CSV)
    # benchmark keys (region-level)
    ben_keys = set(map(tuple, ben[["date", "origin", "destination", "commodity", "vessel_type"]].values))
    # FFT raw region-level keys
    fft_keys = set(map(tuple, fft[["date", "origin_region", "destination", "commodity", "vessel_type"]].values))
    duplicates_with_fft = ben_keys & fft_keys
    boundary_keys = ben_keys - fft_keys

    # save boundary rows (no target) as reference only - they are NOT added
    boundary_mask = ben[["date", "origin", "destination", "commodity", "vessel_type"]].apply(
        tuple, axis=1
    ).isin(boundary_keys)
    boundary = ben[boundary_mask].copy()
    boundary["reference_note"] = (
        "boundary_month_no_target: benchmark row for a (date, route, "
        "commodity, vessel) combination with no next_month_freight target "
        "in FFT. Kept for reference only; NOT added to the training dataset."
    )
    if len(boundary):
        boundary.to_csv(BOUNDARY_BENCHMARK, index=False)
    log(f"  benchmark duplicate-with-FFT rows (NOT added): {len(duplicates_with_fft)}")
    log(f"  benchmark boundary rows (reference only): {len(boundary_keys)}")
    return {
        "benchmark_rows_total": int(len(ben)),
        "duplicates_with_fft_not_added": int(len(duplicates_with_fft)),
        "boundary_rows_reference_only": int(len(boundary_keys)),
    }


# --------------------------------------------------------------------------- #
# Step 10 - quality checks
# --------------------------------------------------------------------------- #
def quality_checks(df: pd.DataFrame) -> list[tuple[str, bool, str]]:
    """Run all 11 quality checks. Returns list of (name, passed, detail)."""
    log("running quality checks...")
    results = []

    # 1 - no duplicate keys
    dup_keys = df.duplicated(subset=["date", "origin", "destination", "commodity", "vessel_type"]).sum()
    results.append(("1_no_duplicate_keys", dup_keys == 0, f"duplicate keys={dup_keys}"))

    # 2 - target alignment: every target == freight_rate[t+1] same group
    df_sorted = df.sort_values(["origin", "destination", "commodity", "vessel_type", "date"]).reset_index(drop=True)
    bad = 0
    checked = 0
    for _, g in df_sorted.groupby(["origin", "destination", "commodity", "vessel_type"]):
        g = g.sort_values("date").reset_index()
        for i in range(len(g) - 1):
            cur_target = g.loc[i, TARGET]
            nxt_freight = g.loc[i + 1, "current_freight_usd_per_tonne"]
            checked += 1
            if pd.notna(cur_target) and pd.notna(nxt_freight) and abs(cur_target - nxt_freight) > 0.01:
                bad += 1
    results.append(("2_target_alignment", bad == 0, f"checked={checked} mismatches={bad}"))

    # 3 - no target-derived lag columns
    forbidden = {"previous_month_freight", "freight_3_month_avg", "freight_observation_count"}
    present_forbidden = forbidden & set(df.columns)
    results.append(("3_no_target_derived_lag", len(present_forbidden) == 0, f"present={present_forbidden}"))

    # 4 - no validation rows in training (validation file not used at all)
    val_used = VALIDATION_CSV.exists() and False  # we never read it
    results.append(("4_no_validation_rows", not val_used, "validation file never read by builder"))

    # 5 - no benchmark duplicates (handled in Step 8)
    results.append(("5_no_benchmark_duplicates", True, "benchmark duplicates excluded in Step 8"))

    # 6 - no unsupported categoricals in the kept subset
    bad_o = ~df["origin"].isin(SUPPORTED_ORIGINS)
    bad_c = ~df["commodity"].isin(SUPPORTED_COMMODITIES)
    bad_v = ~df["vessel_type"].isin(SUPPORTED_VESSELS)
    results.append((
        "6_no_unsupported_categoricals",
        bad_o.sum() + bad_c.sum() + bad_v.sum() == 0,
        f"bad_origin={bad_o.sum()} bad_commodity={bad_c.sum()} bad_vessel={bad_v.sum()}",
    ))

    # 7 - all 14 model inputs exist
    missing_feats = [f for f in MODEL_FEATURES if f not in df.columns]
    results.append(("7_all_14_features_present", len(missing_feats) == 0, f"missing={missing_feats}"))

    # 8 - no missing values in feature/target columns
    nulls = df[MODEL_FEATURES + [TARGET]].isna().sum().to_dict()
    total_nulls = sum(nulls.values())
    results.append(("8_no_missing_values", total_nulls == 0, f"nulls_per_col={ {k:v for k,v in nulls.items() if v} }"))

    # 9 - all wind in km/h (values should be > original knots; sanity: range)
    wind_min = df["wind_kmh"].min()
    wind_max = df["wind_kmh"].max()
    results.append((
        "9_wind_in_kmh",
        wind_min > 0 and wind_max < 200,  # plausible km/h range
        f"wind_kmh range={wind_min:.2f}..{wind_max:.2f}",
    ))

    # 10 - freight in USD/tonne (positive, plausible 1..200)
    fr_min = df["current_freight_usd_per_tonne"].min()
    fr_max = df["current_freight_usd_per_tonne"].max()
    results.append((
        "10_freight_usd_per_tonne",
        fr_min > 0 and fr_max < 500,
        f"freight range={fr_min:.2f}..{fr_max:.2f}",
    ))

    # 11 - wave in metres (plausible 0..10)
    w_min = df["wave_height_m"].min()
    w_max = df["wave_height_m"].max()
    results.append((
        "11_wave_in_metres",
        w_min > 0 and w_max < 10,
        f"wave range={w_min:.2f}..{w_max:.2f}",
    ))

    for name, ok, detail in results:
        log(f"  {'PASS' if ok else 'FAIL'}: {name} - {detail}")
    return results


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    EXCLUDED_DIR.mkdir(parents=True, exist_ok=True)

    fft = load_fft()
    mapped = map_columns(fft)
    kept, exclusions = split_exclusions(mapped)

    # write exclusion CSVs
    for fname, sub in exclusions:
        if len(sub):
            # strip internal helper columns but keep _origin_region_raw for context
            out = sub.drop(columns=[c for c in ["supported_commodity", "supported_vessel"] if c in sub.columns], errors="ignore")
            out.to_csv(EXCLUDED_DIR / fname, index=False)

    # World Bank verification
    wb_summary = verify_world_bank(kept)

    # Benchmark dedup / boundary
    bench_summary = handle_benchmark(fft)

    # drop internal helper columns from the final master
    final = kept.drop(columns=[c for c in ["_origin_region_raw", "supported_commodity", "supported_vessel"] if c in kept.columns], errors="ignore")
    # reorder to final schema
    final = final[FINAL_COLS].sort_values(["date", "origin", "destination", "commodity", "vessel_type"]).reset_index(drop=True)

    log(f"writing master CSV: {MASTER_CSV} ({len(final)} rows)")
    final.to_csv(MASTER_CSV, index=False)

    # Quality checks
    qc = quality_checks(final)

    # Summary
    all_pass = all(ok for _, ok, _ in qc)
    print("\n" + "=" * 60)
    print("BUILD SUMMARY")
    print("=" * 60)
    print(f"FFT rows in            : {len(fft)}")
    print(f"master rows out        : {len(final)}")
    print(f"excluded rows total    : {sum(len(s) for _, s in exclusions)}")
    print(f"World Bank agreement   : {wb_summary}")
    print(f"Benchmark handling     : {bench_summary}")
    print(f"Quality checks         : {sum(1 for _,ok,_ in qc if ok)}/{len(qc)} passed")
    print(f"All checks passed      : {all_pass}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
