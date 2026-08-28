"""Train freight_forecast_model_v2.joblib (MODEL TRAINING V2).

Implements STEP 1-12 of the v2 training spec.

Inputs:
  data/master_freight_training_expanded_v1.csv   (110 rows, expanded build)

Outputs:
  freight_forecast_model_v2.joblib               (best model pipeline)
  data/model_predictions_v2.csv                  (test predictions)
  data/MODEL_COMPARISON_V2.md                    (full report)
  data/model_training_metrics_v2.json            (machine-readable metrics)

Strict rules:
  - DO NOT modify freight_forecast_model_v1.joblib
  - Save new model to freight_forecast_model_v2.joblib (separate file)
  - DO NOT use validation data
  - DO NOT generate synthetic rows
  - DO NOT fabricate values
  - DO NOT modify FastAPI backend
  - DO NOT use target-derived columns as features
    (previous_month_freight, freight_3_month_avg, freight_observation_count, next_month_freight_usd_per_tonne)
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

warnings.filterwarnings("ignore")

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
REPO_ROOT = Path(__file__).resolve().parent
MASTER_CSV = REPO_ROOT / "data" / "master_freight_training_expanded_v1.csv"
MODEL_V2_PATH = REPO_ROOT / "freight_forecast_model_v2.joblib"
MODEL_V1_PATH = REPO_ROOT / "freight_forecast_model_v1.joblib"
PREDICTIONS_CSV = REPO_ROOT / "data" / "model_predictions_v2.csv"
METRICS_JSON = REPO_ROOT / "data" / "model_training_metrics_v2.json"

# Model features (14) - per spec
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
# Variant without cargo_tonnes (STEP 5)
MODEL_FEATURES_NO_CARGO = [f for f in MODEL_FEATURES if f != "cargo_tonnes"]

CATEGORICAL = ["origin", "destination", "commodity", "vessel_type"]

TARGET = "next_month_freight_usd_per_tonne"

# Chronological split (STEP 1)
# Train: 2024-02 .. 2025-06 (<= 2025-06-01)
# Test : 2025-07 .. 2025-11 (>= 2025-07-01)
SPLIT_DATE = "2025-07-01"

# Fixed random seed for reproducibility
RANDOM_STATE = 42

# Feature importance labels we want to report (STEP 7)
IMPORTANCE_LABELS = [
    "current_freight_usd_per_tonne",
    "bdi",
    "vlsfo_usd_per_tonne",
    "coal_price_usd_per_mt",
    "iron_ore_price_usd_per_dmt",
    "cargo_tonnes",
    "wind_kmh",
    "wave_height_m",
    "cyclone_risk",
    "weather_delay_days",
    "origin",
    "destination",
    "commodity",
    "vessel_type",
]


def log(msg: str) -> None:
    print(f"[train-v2] {msg}")


def metrics(y_true, y_pred) -> dict:
    """Compute MAE, RMSE, R2."""
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    mae = float(mean_absolute_error(y_true, y_pred))
    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    r2 = float(r2_score(y_true, y_pred))
    return {"mae": mae, "rmse": rmse, "r2": r2}


# --------------------------------------------------------------------------- #
# STEP 1 - load + chronological split
# --------------------------------------------------------------------------- #
def load_and_split() -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    log(f"loading {MASTER_CSV}")
    df = pd.read_csv(MASTER_CSV)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["date", "origin", "destination", "commodity", "vessel_type"]).reset_index(drop=True)
    log(f"  total rows: {len(df)}  date range: {df['date'].min().date()} -> {df['date'].max().date()}")

    train = df[df["date"] < SPLIT_DATE].copy()
    test = df[df["date"] >= SPLIT_DATE].copy()
    log(f"  train rows: {len(train)}  ({train['date'].min().date()} -> {train['date'].max().date()})")
    log(f"  test  rows: {len(test)}   ({test['date'].min().date()} -> {test['date'].max().date()})")
    return df, train, test


# --------------------------------------------------------------------------- #
# Build a sklearn Pipeline (preprocessing + estimator)
# --------------------------------------------------------------------------- #
def build_pipeline(estimator, features: list) -> Pipeline:
    """Build ONE sklearn Pipeline: ColumnTransformer (OneHot + passthrough) + estimator."""
    cat_cols = [c for c in CATEGORICAL if c in features]
    num_cols = [c for c in features if c not in cat_cols]
    prep = ColumnTransformer(
        transformers=[
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), cat_cols),
            ("num", "passthrough", num_cols),
        ],
        remainder="drop",
    )
    return Pipeline(steps=[("prep", prep), ("model", estimator)])


# --------------------------------------------------------------------------- #
# STEP 2 - naive baseline (predict = current_freight)
# --------------------------------------------------------------------------- #
def naive_baseline(train: pd.DataFrame, test: pd.DataFrame) -> dict:
    log("STEP 2: naive baseline (predict = current_freight_usd_per_tonne)")
    y_pred_train = train["current_freight_usd_per_tonne"].values
    y_true_train = train[TARGET].values
    y_pred_test = test["current_freight_usd_per_tonne"].values
    y_true_test = test[TARGET].values
    res = {
        "train": metrics(y_true_train, y_pred_train),
        "test": metrics(y_true_test, y_pred_test),
    }
    log(f"  test: MAE={res['test']['mae']:.4f}  RMSE={res['test']['rmse']:.4f}  R2={res['test']['r2']:.4f}")
    return res


# --------------------------------------------------------------------------- #
# STEP 3 - Random Forest (with cargo)
# --------------------------------------------------------------------------- #
def train_rf(train, test, features, label: str) -> dict:
    log(f"STEP 3: Random Forest ({label})")
    rf = RandomForestRegressor(
        n_estimators=300,
        max_depth=8,
        min_samples_leaf=2,
        random_state=RANDOM_STATE,
        n_jobs=-1,
    )
    pipe = build_pipeline(rf, features)
    pipe.fit(train[features], train[TARGET])
    train_pred = pipe.predict(train[features])
    test_pred = pipe.predict(test[features])
    res = {
        "train": metrics(train[TARGET].values, train_pred),
        "test": metrics(test[TARGET].values, test_pred),
        "pipeline": pipe,
    }
    log(f"  train: MAE={res['train']['mae']:.4f}  RMSE={res['train']['rmse']:.4f}  R2={res['train']['r2']:.4f}")
    log(f"  test : MAE={res['test']['mae']:.4f}  RMSE={res['test']['rmse']:.4f}  R2={res['test']['r2']:.4f}")
    return res


# --------------------------------------------------------------------------- #
# STEP 4 - Gradient Boosting
# --------------------------------------------------------------------------- #
def train_gb(train, test, features, label: str) -> dict:
    log(f"STEP 4: Gradient Boosting ({label})")
    # GradientBoostingRegressor (not Hist) - works smoothly with OneHot in a Pipeline.
    # Conservative params for 110 rows.
    gb = GradientBoostingRegressor(
        n_estimators=200,
        max_depth=3,
        learning_rate=0.05,
        min_samples_leaf=3,
        random_state=RANDOM_STATE,
    )
    pipe = build_pipeline(gb, features)
    pipe.fit(train[features], train[TARGET])
    train_pred = pipe.predict(train[features])
    test_pred = pipe.predict(test[features])
    res = {
        "train": metrics(train[TARGET].values, train_pred),
        "test": metrics(test[TARGET].values, test_pred),
        "pipeline": pipe,
    }
    log(f"  train: MAE={res['train']['mae']:.4f}  RMSE={res['train']['rmse']:.4f}  R2={res['train']['r2']:.4f}")
    log(f"  test : MAE={res['test']['mae']:.4f}  RMSE={res['test']['rmse']:.4f}  R2={res['test']['r2']:.4f}")
    return res


# --------------------------------------------------------------------------- #
# STEP 5 - RF without cargo
# --------------------------------------------------------------------------- #
def train_rf_no_cargo(train, test) -> dict:
    log("STEP 5: Random Forest (no cargo_tonnes)")
    rf = RandomForestRegressor(
        n_estimators=300,
        max_depth=8,
        min_samples_leaf=2,
        random_state=RANDOM_STATE,
        n_jobs=-1,
    )
    pipe = build_pipeline(rf, MODEL_FEATURES_NO_CARGO)
    pipe.fit(train[MODEL_FEATURES_NO_CARGO], train[TARGET])
    train_pred = pipe.predict(train[MODEL_FEATURES_NO_CARGO])
    test_pred = pipe.predict(test[MODEL_FEATURES_NO_CARGO])
    res = {
        "train": metrics(train[TARGET].values, train_pred),
        "test": metrics(test[TARGET].values, test_pred),
        "pipeline": pipe,
    }
    log(f"  train: MAE={res['train']['mae']:.4f}  RMSE={res['train']['rmse']:.4f}  R2={res['train']['r2']:.4f}")
    log(f"  test : MAE={res['test']['mae']:.4f}  RMSE={res['test']['rmse']:.4f}  R2={res['test']['r2']:.4f}")
    return res


# --------------------------------------------------------------------------- #
# STEP 7 - permutation importance on test set
# --------------------------------------------------------------------------- #
def permutation_importance_on_test(pipe, test, features, n_repeats=10) -> dict:
    """Permutation importance on the test set (per spec preference)."""
    from sklearn.inspection import permutation_importance

    log("STEP 7: permutation importance on test set")
    result = permutation_importance(
        pipe, test[features], test[TARGET],
        n_repeats=n_repeats, random_state=RANDOM_STATE, n_jobs=-1,
    )
    # Map transformed feature names back to original feature names.
    # For one-hot categorical features, sum importances across the one-hot columns.
    prep = pipe.named_steps["prep"]
    try:
        transformed_names = list(prep.get_feature_names_out())
    except Exception:
        transformed_names = [f"f{i}" for i in range(len(result.importances_mean))]

    # Aggregate by original feature
    raw = list(zip(transformed_names, result.importances_mean))
    agg = {f: 0.0 for f in features}
    for name, imp in raw:
        # name format: "cat__origin_Hay Point" or "num__cargo_tonnes"
        matched = None
        if name.startswith("cat__"):
            rest = name[len("cat__"):]
            for c in ["origin", "destination", "commodity", "vessel_type"]:
                if rest.startswith(c + "_") and c in agg:
                    matched = c
                    break
        elif name.startswith("num__"):
            rest = name[len("num__"):]
            if rest in agg:
                matched = rest
        if matched is None:
            # fall back: try plain match
            for f in features:
                if f in name:
                    matched = f
                    break
        if matched is not None:
            agg[matched] += float(imp)

    total = sum(agg.values())
    if total > 0:
        agg_pct = {k: round(100.0 * v / total, 2) for k, v in agg.items()}
    else:
        agg_pct = {k: 0.0 for k in agg}
    sorted_imp = sorted(agg_pct.items(), key=lambda x: -x[1])
    log("  top features (perm importance % of total):")
    for name, imp in sorted_imp[:8]:
        log(f"    {imp:6.2f}%  {name}")
    return {"raw": agg, "pct": agg_pct, "sorted": sorted_imp, "total_importance": total}


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> int:
    log("=" * 60)
    log("MODEL TRAINING V2")
    log("=" * 60)

    # Verify v1 is untouched (we must not overwrite it)
    if not MODEL_V1_PATH.exists():
        raise FileNotFoundError(f"v1 model not found at {MODEL_V1_PATH}")
    import hashlib
    v1_sha = hashlib.sha256(MODEL_V1_PATH.read_bytes()).hexdigest()
    log(f"v1 model sha256 (baseline): {v1_sha}")

    # STEP 1
    df, train, test = load_and_split()

    # STEP 2 - naive baseline
    naive = naive_baseline(train, test)

    # STEP 3 - RF with cargo
    rf = train_rf(train, test, MODEL_FEATURES, label="with cargo_tonnes")

    # STEP 4 - Gradient Boosting
    gb = train_gb(train, test, MODEL_FEATURES, label="GradientBoosting")

    # STEP 5 - RF without cargo
    rf_no_cargo = train_rf_no_cargo(train, test)

    # STEP 6 - comparison + selection
    log("STEP 6: model comparison (selection by lowest TEST MAE, then RMSE)")
    candidates = [
        ("Naive (current_freight)", naive, None),
        ("RandomForest (with cargo)", rf, "rf"),
        ("GradientBoosting", gb, "gb"),
        ("RandomForest (no cargo)", rf_no_cargo, "rf_no_cargo"),
    ]
    print("\n" + "=" * 60)
    print("MODEL COMPARISON (TEMPORAL TEST SET)")
    print("=" * 60)
    print(f"{'Model':<32} {'MAE':>8} {'RMSE':>8} {'R2':>8}")
    print("-" * 60)
    for name, m, _ in candidates:
        t = m["test"]
        print(f"{name:<32} {t['mae']:>8.4f} {t['rmse']:>8.4f} {t['r2']:>8.4f}")
    print()

    # selection: skip naive baseline; pick lowest MAE among ML models
    ml_candidates = [c for c in candidates if c[2] is not None]
    ml_candidates.sort(key=lambda c: (c[1]["test"]["mae"], c[1]["test"]["rmse"]))
    selected_name, selected_metrics, selected_key = ml_candidates[0]
    log(f"SELECTED: {selected_name}")

    # STEP 7 - feature importance on the selected model
    selected_pipe = selected_metrics["pipeline"]
    selected_features = MODEL_FEATURES_NO_CARGO if selected_key == "rf_no_cargo" else MODEL_FEATURES
    perm_imp = permutation_importance_on_test(selected_pipe, test, selected_features)

    # Also get built-in feature_importances_ if RF (for cross-reference)
    builtin_imp = {}
    try:
        est = selected_pipe.named_steps["model"]
        if hasattr(est, "feature_importances_"):
            prep = selected_pipe.named_steps["prep"]
            tnames = list(prep.get_feature_names_out())
            raw = list(zip(tnames, est.feature_importances_))
            agg = {f: 0.0 for f in selected_features}
            for name, imp in raw:
                matched = None
                if name.startswith("cat__"):
                    rest = name[len("cat__"):]
                    for c in ["origin", "destination", "commodity", "vessel_type"]:
                        if rest.startswith(c + "_") and c in agg:
                            matched = c
                            break
                elif name.startswith("num__"):
                    rest = name[len("num__"):]
                    if rest in agg:
                        matched = rest
                if matched is not None:
                    agg[matched] += float(imp)
            total = sum(agg.values())
            builtin_imp = {k: round(100.0 * v / total, 2) for k, v in agg.items()} if total > 0 else {k: 0.0 for k in agg}
            builtin_imp = dict(sorted(builtin_imp.items(), key=lambda x: -x[1]))
    except Exception as e:
        log(f"  could not extract builtin importances: {e}")

    # STEP 8 - overfitting analysis (train vs test)
    log("STEP 8: overfitting analysis")
    overfit = {}
    for name, m, key in candidates:
        if key is None:
            continue
        overfit[name] = {
            "train_mae": m["train"]["mae"],
            "test_mae": m["test"]["mae"],
            "mae_gap": m["test"]["mae"] - m["train"]["mae"],
            "train_r2": m["train"]["r2"],
            "test_r2": m["test"]["r2"],
            "r2_gap": m["train"]["r2"] - m["test"]["r2"],
        }

    # Check current_freight dominance
    current_freight_pct_perm = perm_imp["pct"].get("current_freight_usd_per_tonne", 0.0)
    current_freight_pct_builtin = builtin_imp.get("current_freight_usd_per_tonne", 0.0)
    dominant_threshold = 90.0
    is_dominant = current_freight_pct_perm > dominant_threshold or current_freight_pct_builtin > dominant_threshold
    log(f"current_freight importance (perm): {current_freight_pct_perm:.2f}%")
    log(f"current_freight importance (builtin): {current_freight_pct_builtin:.2f}%")
    if is_dominant:
        log(">>> Current freight dominates the model (>90%). Persistence forecast behaviour.")

    # STEP 9 - save best model
    log(f"STEP 9: saving selected model to {MODEL_V2_PATH}")
    joblib.dump(selected_pipe, MODEL_V2_PATH)
    # verify it loads
    loaded = joblib.load(MODEL_V2_PATH)
    log(f"  reloaded OK, type={type(loaded).__name__}")

    # STEP 10 - test the saved model with one row per of the 5 combinations
    log("STEP 10: testing saved v2 with 5 representative rows")
    test_cases = [
        {"origin": "Australia West Coast", "destination": "East Coast India", "commodity": "Iron Ore", "vessel_type": "Capesize"},
        {"origin": "Hay Point", "destination": "East Coast India", "commodity": "Coal", "vessel_type": "Capesize"},
        {"origin": "Hay Point", "destination": "East Coast India", "commodity": "Coal", "vessel_type": "Panamax"},
        {"origin": "Taboneo", "destination": "East Coast India", "commodity": "Thermal Coal", "vessel_type": "Panamax"},
        {"origin": "Taboneo", "destination": "East Coast India", "commodity": "Thermal Coal", "vessel_type": "Supramax"},
    ]
    # use the first observation of each combination from the master as the input row
    sample_inputs = []
    for tc in test_cases:
        mask = (
            (df["origin"] == tc["origin"]) &
            (df["destination"] == tc["destination"]) &
            (df["commodity"] == tc["commodity"]) &
            (df["vessel_type"] == tc["vessel_type"])
        )
        row = df[mask].iloc[0]
        sample_inputs.append(row)
    sample_df = pd.DataFrame(sample_inputs)
    preds = loaded.predict(sample_df[selected_features])
    sample_check = []
    for i, row in enumerate(sample_inputs):
        p = float(preds[i])
        ok = (not np.isnan(p)) and isinstance(p, float)
        sample_check.append({
            "origin": row["origin"], "destination": row["destination"],
            "commodity": row["commodity"], "vessel_type": row["vessel_type"],
            "date": str(row["date"].date()),
            "predicted": p, "numeric": ok, "is_nan": bool(np.isnan(p)),
        })
        log(f"  {row['origin']:22} -> {row['destination']:18} {row['commodity']:13} {row['vessel_type']:9}: pred={p:.4f}  ok={ok}")
    all_numeric_ok = all(s["numeric"] and not s["is_nan"] for s in sample_check)
    log(f"  all 5 predictions numeric and non-NaN: {all_numeric_ok}")

    # STEP 11 - prediction file (test rows only)
    log(f"STEP 11: writing {PREDICTIONS_CSV}")
    test_pred = loaded.predict(test[selected_features])
    pred_df = test[["date", "origin", "destination", "commodity", "vessel_type",
                    "current_freight_usd_per_tonne", TARGET]].copy()
    pred_df["predicted_next_month_freight"] = test_pred
    pred_df["absolute_error"] = (pred_df["predicted_next_month_freight"] - pred_df[TARGET]).abs()
    pred_df = pred_df.rename(columns={TARGET: "actual_next_month_freight"})
    pred_df["date"] = pred_df["date"].dt.strftime("%Y-%m-%d")
    pred_df = pred_df[[
        "date", "origin", "destination", "commodity", "vessel_type",
        "current_freight_usd_per_tonne", "actual_next_month_freight",
        "predicted_next_month_freight", "absolute_error",
    ]]
    pred_df.to_csv(PREDICTIONS_CSV, index=False)
    log(f"  wrote {len(pred_df)} test predictions")

    # Persist machine-readable metrics
    metrics_out = {
        "dataset": {
            "rows_total": int(len(df)),
            "rows_train": int(len(train)),
            "rows_test": int(len(test)),
            "date_train_start": str(train["date"].min().date()),
            "date_train_end": str(train["date"].max().date()),
            "date_test_start": str(test["date"].min().date()),
            "date_test_end": str(test["date"].max().date()),
            "split_date": SPLIT_DATE,
            "n_combinations": int(df.groupby(["origin","destination","commodity","vessel_type"]).ngroups),
        },
        "naive_baseline": {k: naive[k] for k in ["train", "test"]},
        "rf_with_cargo": {k: (rf[k] if k != "pipeline" else None) for k in ["train", "test"]},
        "gradient_boosting": {k: (gb[k] if k != "pipeline" else None) for k in ["train", "test"]},
        "rf_no_cargo": {k: (rf_no_cargo[k] if k != "pipeline" else None) for k in ["train", "test"]},
        "selected_model": selected_name,
        "selected_features": selected_features,
        "permutation_importance_pct": perm_imp["pct"],
        "builtin_importance_pct": builtin_imp,
        "current_freight_pct_perm": current_freight_pct_perm,
        "current_freight_pct_builtin": current_freight_pct_builtin,
        "current_freight_dominant": is_dominant,
        "overfit_analysis": overfit,
        "sample_predictions": sample_check,
        "model_path": str(MODEL_V2_PATH),
        "v1_model_sha256_unchanged": v1_sha,
    }
    METRICS_JSON.parent.mkdir(parents=True, exist_ok=True)
    METRICS_JSON.write_text(json.dumps(metrics_out, indent=2, default=str))
    log(f"  wrote metrics to {METRICS_JSON}")

    # Verify v1 untouched
    v1_sha_after = hashlib.sha256(MODEL_V1_PATH.read_bytes()).hexdigest()
    log(f"v1 model sha256 (after):  {v1_sha_after}")
    assert v1_sha == v1_sha_after, "v1 model was modified!"
    log("v1 model UNTOUCHED ✅")

    print("\n" + "=" * 60)
    print("TRAINING V2 SUMMARY")
    print("=" * 60)
    print(f"selected model        : {selected_name}")
    print(f"saved to              : {MODEL_V2_PATH}")
    print(f"naive test MAE/RMSE/R2: {naive['test']['mae']:.4f} / {naive['test']['rmse']:.4f} / {naive['test']['r2']:.4f}")
    print(f"selected test MAE/RMSE/R2: {selected_metrics['test']['mae']:.4f} / {selected_metrics['test']['rmse']:.4f} / {selected_metrics['test']['r2']:.4f}")
    print(f"beats naive MAE?      : {selected_metrics['test']['mae'] < naive['test']['mae']}")
    print(f"current_freight > 90%?: {is_dominant}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
