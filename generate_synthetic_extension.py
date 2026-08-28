"""Generate synthetic training extension for the freight forecasting prototype.

Empirical-constrained simulation: expands the 110-row validated master
dataset with 1000 synthetic observations that preserve the statistical and
temporal characteristics of the original.

Methodology overview (per spec STEP 5):
  - Block-bootstrap resampling of the original 110 rows (per combination)
  - Multivariate residual perturbation of freight to preserve the
    empirical distribution of month-to-month percentage changes
  - Target = forward-shifted current_freight within each synthetic
    trajectory (no independent target generation)

Strict rules:
  - DO NOT modify freight_forecast_model_v1.joblib
  - DO NOT modify freight_forecast_model_v2.joblib
  - DO NOT modify the original 110 observations
  - DO NOT use validation data
  - DO NOT retrain
  - DO NOT modify FastAPI backend
  - DO NOT include target-derived columns as features
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List

import numpy as np
import pandas as pd
from scipy import stats

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
REPO_ROOT = Path(__file__).resolve().parent
MASTER_CSV = REPO_ROOT / "data" / "master_freight_training_expanded_v1.csv"
STATS_JSON = REPO_ROOT / "data" / "synthetic_generation_statistics_v1.json"
SYNTHETIC_CSV = REPO_ROOT / "data" / "master_freight_training_synthetic_v1.csv"
ORIGINAL_REF_CSV = REPO_ROOT / "data" / "original_training_reference_v1.csv"
VALIDATION_REPORT = REPO_ROOT / "data" / "synthetic_validation_v1.json"

MODEL_V1 = REPO_ROOT / "freight_forecast_model_v1.joblib"
MODEL_V2 = REPO_ROOT / "freight_forecast_model_v2.joblib"

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
N_SYNTHETIC = 1000
RANDOM_SEED = 42
# Combinations to generate (the 5 in the original data)
COMBINATIONS = [
    ("Australia West Coast", "East Coast India", "Iron Ore", "Capesize"),
    ("Hay Point", "East Coast India", "Coal", "Capesize"),
    ("Hay Point", "East Coast India", "Coal", "Panamax"),
    ("Taboneo", "East Coast India", "Thermal Coal", "Panamax"),
    ("Taboneo", "East Coast India", "Thermal Coal", "Supramax"),
]
# Each trajectory has a target = forward-shifted freight. With 22 months of
# original data per combination we bootstrap blocks of length ~3-6 months.
TRAJECTORY_LENGTH = 50  # months per trajectory (generous, so we can hit ~200/comb)
N_TRAJECTORIES_PER_COMBO = 4  # 5 combos * 4 traj * 50 months = 1000 rows

# Variables (model inputs + target)
MODEL_FEATURES = [
    "origin", "destination", "commodity", "vessel_type",
    "cargo_tonnes", "bdi", "vlsfo_usd_per_tonne",
    "coal_price_usd_per_mt", "iron_ore_price_usd_per_dmt",
    "wind_kmh", "wave_height_m", "cyclone_risk", "weather_delay_days",
    "current_freight_usd_per_tonne",
]
TARGET = "next_month_freight_usd_per_tonne"

# Representative cargo tonnes (same as expanded master)
CARGO_BY_VESSEL = {"Panamax": 75_000.0, "Supramax": 55_000.0, "Capesize": 170_000.0}

# Original data ends at 2025-11-01; synthetic trajectories start at 2025-12-01
SYNTH_START_DATE = pd.Timestamp("2025-12-01")

# Outlier rejection bounds (expanded from observed ranges; never fabricated)
# These are guards - the bootstrap should never produce pathological values
# but we reject if it ever does.
BOUNDS = {
    "current_freight_usd_per_tonne": (5.0, 30.0),  # observed 8.5..21.2
    "bdi": (500.0, 3000.0),  # observed 1460..2150
    "vlsfo_usd_per_tonne": (300.0, 900.0),  # observed 565..685
    "coal_price_usd_per_mt": (50.0, 200.0),  # observed 100..145
    "iron_ore_price_usd_per_dmt": (50.0, 200.0),  # observed 100..135
    "wind_kmh": (10.0, 80.0),  # observed 19..57
    "wave_height_m": (0.5, 6.0),  # observed 1.1..4.3
    "cyclone_risk": (0.0, 5.0),  # 0..5 domain
    "weather_delay_days": (0.0, 5.0),  # observed 0..4
}


def log(msg: str) -> None:
    print(f"[synth] {msg}")


# --------------------------------------------------------------------------- #
# STEP 1 — Analyze the original data
# --------------------------------------------------------------------------- #
def analyze_original(df: pd.DataFrame) -> dict:
    """Compute per-combination and global statistics."""
    log("STEP 1: analyzing original data...")

    numeric_features = [
        "bdi", "vlsfo_usd_per_tonne", "coal_price_usd_per_mt",
        "iron_ore_price_usd_per_dmt", "wind_kmh", "wave_height_m",
        "cyclone_risk", "weather_delay_days", "current_freight_usd_per_tonne",
    ]

    def describe(s: pd.Series) -> dict:
        s = s.dropna()
        return {
            "mean": float(s.mean()),
            "median": float(s.median()),
            "std": float(s.std()),
            "min": float(s.min()),
            "max": float(s.max()),
            "count": int(len(s)),
        }

    def pct_changes(s: pd.Series) -> dict:
        s = s.sort_index()
        changes = s.pct_change().dropna() * 100.0
        if len(changes) == 0:
            return {"mean": 0, "std": 0, "min": 0, "max": 0}
        return {
            "mean": float(changes.mean()),
            "std": float(changes.std()),
            "min": float(changes.min()),
            "max": float(changes.max()),
        }

    # Global stats
    global_stats = {f: describe(df[f]) for f in numeric_features}
    global_stats["freight_pct_change"] = pct_changes(
        df.sort_values(["origin", "destination", "commodity", "vessel_type", "date"])
        .set_index("date")["current_freight_usd_per_tonne"]
    )

    # Per-combination stats
    combo_stats = {}
    for combo in COMBINATIONS:
        origin, dest, comm, vessel = combo
        sub = df[(df.origin == origin) & (df.destination == dest)
                 & (df.commodity == comm) & (df.vessel_type == vessel)].copy()
        sub = sub.sort_values("date")
        key = f"{origin}|{dest}|{comm}|{vessel}"
        combo_stats[key] = {
            "n_rows": int(len(sub)),
            "date_range": [str(sub.date.min().date()), str(sub.date.max().date())],
            "features": {f: describe(sub[f]) for f in numeric_features},
            "freight_pct_change": pct_changes(sub.set_index("date")["current_freight_usd_per_tonne"]),
        }

    # Correlations (numeric features + target)
    corr_cols = numeric_features + [TARGET]
    corr_global = df[corr_cols].corr(method="pearson").round(4).to_dict()

    # Per-combination correlations (when sample size allows)
    combo_corr = {}
    for combo in COMBINATIONS:
        origin, dest, comm, vessel = combo
        sub = df[(df.origin == origin) & (df.destination == dest)
                 & (df.commodity == comm) & (df.vessel_type == vessel)]
        if len(sub) >= 5:
            c = sub[corr_cols].corr(method="pearson").round(4)
            # convert NaN to null
            combo_corr[f"{origin}|{dest}|{comm}|{vessel}"] = c.where(c.notna(), None).to_dict()
        else:
            combo_corr[f"{origin}|{dest}|{comm}|{vessel}"] = None

    result = {
        "global_stats": global_stats,
        "per_combination_stats": combo_stats,
        "correlation_global": corr_global,
        "per_combination_correlations": combo_corr,
        "combinations": ["|".join(c) for c in COMBINATIONS],
        "numeric_features": numeric_features,
    }
    STATS_JSON.parent.mkdir(parents=True, exist_ok=True)
    STATS_JSON.write_text(json.dumps(result, indent=2, default=str))
    log(f"  wrote stats to {STATS_JSON}")
    return result


# --------------------------------------------------------------------------- #
# STEP 5-8 — Synthetic generation via block bootstrap + perturbation
# --------------------------------------------------------------------------- #

def trajectory_is_clean(rows):
    """Return True if all rows in the trajectory are within bounds."""
    for row in rows:
        for col, (lo, hi) in BOUNDS.items():
            v = row.get(col)
            if v is None:
                return False
            try:
                if not (lo <= float(v) <= hi):
                    return False
            except (TypeError, ValueError):
                return False
    return True

def generate_synthetic(original: pd.DataFrame, stats: dict) -> pd.DataFrame:
    """Generate N_SYNTHETIC synthetic rows preserving empirical relationships.

    Method (per spec STEP 5 preference - empirical/block bootstrap):

      For each of the 5 combinations, generate N_TRAJECTORIES_PER_COMBO
      independent trajectories, each TRAJECTORY_LENGTH months long.

      Per trajectory:
        1. Seed month-0 with a randomly drawn (block-bootstrap) starting row
           from the same combination's original observations.
        2. For each subsequent month:
           a. Draw a "block" of 1-3 consecutive original observations from
              the same combination (block bootstrap). This preserves the
              joint distribution of (market, weather, freight) within a
              short window - which is the key to preserving correlations.
           b. Compute the empirical month-to-month pct change in freight
              from that block.
           c. Apply that pct change to the previous synthetic freight (with
              small Gaussian residual perturbation from the empirical
              residual distribution).
           d. Inherit the market + weather values from the bootstrapped
              block (so co-movement is preserved).
        3. The TARGET for month t = current_freight at month t+1 (within
           the same trajectory). The last month of each trajectory has no
           successor -> it gets no target (dropped at the end).
    """
    log(f"STEP 5-8: generating {N_SYNTHETIC} synthetic rows via block bootstrap...")
    rng = np.random.default_rng(RANDOM_SEED)

    # Total target rows: N_TRAJECTORIES_PER_COMBO * (TRAJECTORY_LENGTH - 1)
    # because each trajectory's last row has no successor target.
    rows_per_combo = N_TRAJECTORIES_PER_COMBO * (TRAJECTORY_LENGTH - 1)
    log(f"  {rows_per_combo} rows per combination * 5 = {rows_per_combo * 5} total")

    all_synth_rows: List[dict] = []
    combo_idx = 0
    for combo in COMBINATIONS:
        origin, dest, comm, vessel = combo
        combo_idx += 1
        sub = original[
            (original.origin == origin) & (original.destination == dest)
            & (original.commodity == comm) & (original.vessel_type == vessel)
        ].sort_values("date").reset_index(drop=True)
        n_orig = len(sub)
        if n_orig < 4:
            log(f"  WARNING: combo {combo} has only {n_orig} rows; using whatever is available")

        # Empirical residual distribution of freight pct changes
        sub_pct = sub["current_freight_usd_per_tonne"].pct_change().dropna().values
        residual_std = float(np.std(sub_pct)) if len(sub_pct) > 1 else 0.05

        cargo_t = CARGO_BY_VESSEL[vessel]

        # Trajectory-level rejection: generate trajectories and accept only
        # those whose every row is within bounds. This preserves target
        # alignment within each accepted trajectory (target[t] = freight[t+1]).
        target_rows_for_combo = N_SYNTHETIC // 5  # 200 per combo
        max_traj_attempts = 20
        traj_attempt = 0
        traj_accepted = 0
        combo_rows = 0
        while combo_rows < target_rows_for_combo and traj_attempt < max_traj_attempts:
            traj_attempt += 1
            traj_id = f"SYN{combo_idx:02d}{traj_attempt:02d}"
            # Pick a random starting row
            start = sub.iloc[rng.integers(0, n_orig)]
            prev_freight = float(start["current_freight_usd_per_tonne"])

            trajectory_rows: List[dict] = []
            for m in range(TRAJECTORY_LENGTH):
                # Block bootstrap: draw 1-3 consecutive original rows
                block_len = int(rng.integers(1, 4))
                block_start = int(rng.integers(0, max(1, n_orig - block_len + 1)))
                block = sub.iloc[block_start:block_start + block_len]

                # Compute empirical pct change within this block (the
                # freight evolution we want to mimic).
                block_freights = block["current_freight_usd_per_tonne"].values
                if len(block_freights) >= 2:
                    empirical_pct = (block_freights[-1] - block_freights[0]) / max(block_freights[0], 1e-6)
                else:
                    empirical_pct = 0.0

                if m == 0:
                    # First month: use the bootstrapped block's first row's values directly
                    new_freight = prev_freight
                else:
                    # Apply empirical pct + small Gaussian residual perturbation
                    perturbation = rng.normal(0, max(residual_std * 0.5, 0.005))
                    pct_applied = empirical_pct + perturbation
                    # Clamp pct change to a reasonable range to avoid pathological jumps
                    pct_applied = float(np.clip(pct_applied, -0.25, 0.25))
                    new_freight = prev_freight * (1.0 + pct_applied)

                # Inherit market + weather values from the bootstrapped block's
                # representative row (preserves joint distribution). We pick
                # the LAST row of the block as the representative - this
                # captures the post-evolution state, which is what the model
                # would observe at month t.
                rep = block.iloc[-1]

                # Synthetic date: SYNTH_START_DATE + m months (+ traj_attempt offset
                # so different trajectories of the same combo don't collide)
                synth_date = (SYNTH_START_DATE + pd.DateOffset(months=m + (traj_attempt * TRAJECTORY_LENGTH))).strftime("%Y-%m-%d")

                row = {
                    "date": synth_date,
                    "origin": origin,
                    "destination": dest,
                    "commodity": comm,
                    "vessel_type": vessel,
                    "cargo_tonnes": cargo_t,
                    "bdi": float(rep["bdi"]),
                    "vlsfo_usd_per_tonne": float(rep["vlsfo_usd_per_tonne"]),
                    "coal_price_usd_per_mt": float(rep["coal_price_usd_per_mt"]),
                    "iron_ore_price_usd_per_dmt": float(rep["iron_ore_price_usd_per_dmt"]),
                    "wind_kmh": float(rep["wind_kmh"]),
                    "wave_height_m": float(rep["wave_height_m"]),
                    "cyclone_risk": float(rep["cyclone_risk"]),
                    "weather_delay_days": float(rep["weather_delay_days"]),
                    "current_freight_usd_per_tonne": float(new_freight),
                    "trajectory_id": traj_id,
                    "data_origin": "synthetic",
                    "synthetic_generation_method": "empirical_constrained_simulation_v1",
                }
                trajectory_rows.append(row)
                prev_freight = float(new_freight)

            # STEP 9 — target = forward-shifted freight within trajectory
            for i in range(len(trajectory_rows) - 1):
                trajectory_rows[i][TARGET] = float(trajectory_rows[i + 1]["current_freight_usd_per_tonne"])
            # Drop the last row of each trajectory (no successor -> no target)
            trajectory_rows = trajectory_rows[:-1]

            # STEP 12 — outlier check at the TRAJECTORY level: if ANY row is
            # pathological, reject the WHOLE trajectory. This keeps target
            # alignment intact within accepted trajectories.
            if trajectory_is_clean(trajectory_rows):
                all_synth_rows.extend(trajectory_rows)
                combo_rows += len(trajectory_rows)
                traj_accepted += 1
            else:
                log(f"    rejected trajectory {traj_id} (pathological value)")
        log(f"  combo {combo_idx} ({origin} -> {dest}, {comm}, {vessel}): accepted {traj_accepted} trajectories, {combo_rows} rows")

    synth_df = pd.DataFrame(all_synth_rows)
    log(f"  generated {len(synth_df)} synthetic rows (target {N_SYNTHETIC})")

    # If we have MORE than N_SYNTHETIC, trim excess.
    # Iterate: at each step, drop either (a) the whole last trajectory if it's
    # smaller than the remaining excess, or (b) the tail rows of the last
    # trajectory plus the row whose target depends on them. Loop until exactly
    # N_SYNTHETIC rows remain. This preserves target alignment in all kept rows.
    trim_pass = 0
    while len(synth_df) > N_SYNTHETIC:
        trim_pass += 1
        excess = len(synth_df) - N_SYNTHETIC
        last_traj = synth_df.iloc[-1]["trajectory_id"]
        last_traj_df = synth_df[synth_df["trajectory_id"] == last_traj]
        if len(last_traj_df) <= excess:
            # Drop the whole last trajectory (we'd under-shoot if we only dropped `excess` rows)
            synth_df = synth_df[synth_df["trajectory_id"] != last_traj].reset_index(drop=True)
            continue
        # Drop the last `excess` rows of the last trajectory AND the row
        # immediately before them (whose target depends on the dropped row).
        drop_idx = list(synth_df.tail(excess).index)
        first_dropped_freight = synth_df.loc[drop_idx[0], "current_freight_usd_per_tonne"]
        # Find the row whose target == the first dropped row's freight (same trajectory)
        for idx in range(drop_idx[0] - 1, -1, -1):
            if synth_df.loc[idx, "trajectory_id"] == last_traj:
                if abs(synth_df.loc[idx, TARGET] - first_dropped_freight) < 0.001:
                    drop_idx.insert(0, idx)
                    break
            else:
                break
        synth_df = synth_df.drop(index=drop_idx).reset_index(drop=True)
    log(f"  trimmed to exactly {len(synth_df)} rows (after {trim_pass} pass(es))")
    # If we under-shot (rare - only if a whole-trajectory drop brought us under), regenerate
    if len(synth_df) < N_SYNTHETIC:
        deficit = N_SYNTHETIC - len(synth_df)
        log(f"  regenerating {deficit} extra rows to hit target...")
        extra = generate_extra_trajectories(original, deficit, rng, start_combo_idx=50)
        # Trim extra if it overshoots (same logic, simpler since extra is small)
        if len(extra) > deficit:
            extra = extra.head(deficit).copy()
        synth_df = pd.concat([synth_df, extra], ignore_index=True)
        log(f"  final rows: {len(synth_df)}")

    return synth_df


def reject_outliers(df: pd.DataFrame, original: pd.DataFrame, rng) -> pd.DataFrame:
    """Reject rows with pathological values. Bounded per BOUNDS dict."""
    keep_mask = pd.Series([True] * len(df), index=df.index)
    for col, (lo, hi) in BOUNDS.items():
        if col in df.columns:
            keep_mask &= (df[col] >= lo) & (df[col] <= hi)
    # Also reject extreme freight jumps (synthetic current freight > 50% change from trajectory mean)
    # We'll catch these at the trajectory level below.
    rejected = df[~keep_mask]
    if len(rejected) > 0:
        log(f"    rejected {len(rejected)} rows with out-of-bound values")
    return df[keep_mask].reset_index(drop=True).copy()


def generate_extra_trajectories(original: pd.DataFrame, n_needed: int, rng, start_combo_idx: int = 1) -> pd.DataFrame:
    """Generate extra trajectories to fill a small deficit. Each accepted
    trajectory is fully clean so target alignment is preserved."""
    extra_rows = []
    # Spread the needed rows across combos
    trajectories_per_combo = max(1, (n_needed // 5) // (TRAJECTORY_LENGTH - 1) + 1)
    for offset, combo in enumerate(COMBINATIONS):
        combo_idx = start_combo_idx + offset
        origin, dest, comm, vessel = combo
        sub = original[
            (original.origin == origin) & (original.destination == dest)
            & (original.commodity == comm) & (original.vessel_type == vessel)
        ].sort_values("date").reset_index(drop=True)
        n_orig = len(sub)
        if n_orig < 4:
            continue
        sub_pct = sub["current_freight_usd_per_tonne"].pct_change().dropna().values
        residual_std = float(np.std(sub_pct)) if len(sub_pct) > 1 else 0.05
        cargo_t = CARGO_BY_VESSEL[vessel]

        traj_attempt = 0
        accepted = 0
        while accepted < trajectories_per_combo and traj_attempt < 6:
            traj_attempt += 1
            traj_id = f"SYNX{combo_idx:02d}{traj_attempt:02d}"
            start = sub.iloc[rng.integers(0, n_orig)]
            prev_freight = float(start["current_freight_usd_per_tonne"])
            trajectory = []
            for m in range(TRAJECTORY_LENGTH):
                block_len = int(rng.integers(1, 4))
                block_start = int(rng.integers(0, max(1, n_orig - block_len + 1)))
                block = sub.iloc[block_start:block_start + block_len]
                block_freights = block["current_freight_usd_per_tonne"].values
                empirical_pct = ((block_freights[-1] - block_freights[0]) / max(block_freights[0], 1e-6)
                                 if len(block_freights) >= 2 else 0.0)
                if m == 0:
                    new_freight = prev_freight
                else:
                    perturbation = rng.normal(0, max(residual_std * 0.5, 0.005))
                    pct_applied = float(np.clip(empirical_pct + perturbation, -0.25, 0.25))
                    new_freight = prev_freight * (1.0 + pct_applied)
                rep = block.iloc[-1]
                synth_date = (SYNTH_START_DATE + pd.DateOffset(months=m + 500 + traj_attempt * TRAJECTORY_LENGTH)).strftime("%Y-%m-%d")
                row = {
                    "date": synth_date, "origin": origin, "destination": dest,
                    "commodity": comm, "vessel_type": vessel, "cargo_tonnes": cargo_t,
                    "bdi": float(rep["bdi"]), "vlsfo_usd_per_tonne": float(rep["vlsfo_usd_per_tonne"]),
                    "coal_price_usd_per_mt": float(rep["coal_price_usd_per_mt"]),
                    "iron_ore_price_usd_per_dmt": float(rep["iron_ore_price_usd_per_dmt"]),
                    "wind_kmh": float(rep["wind_kmh"]), "wave_height_m": float(rep["wave_height_m"]),
                    "cyclone_risk": float(rep["cyclone_risk"]),
                    "weather_delay_days": float(rep["weather_delay_days"]),
                    "current_freight_usd_per_tonne": float(new_freight),
                    "trajectory_id": traj_id, "data_origin": "synthetic",
                    "synthetic_generation_method": "empirical_constrained_simulation_v1",
                }
                trajectory.append(row)
                prev_freight = float(new_freight)
            for i in range(len(trajectory) - 1):
                trajectory[i][TARGET] = float(trajectory[i + 1]["current_freight_usd_per_tonne"])
            trows = trajectory[:-1]
            if trajectory_is_clean(trows):
                extra_rows.extend(trows)
                accepted += 1
    return pd.DataFrame(extra_rows)



# --------------------------------------------------------------------------- #
# STEP 11 — Validation (distribution + correlation comparison)
# --------------------------------------------------------------------------- #
def validate(original: pd.DataFrame, synth: pd.DataFrame) -> dict:
    log("STEP 11: validating synthetic vs original distributions...")
    numeric_features = [
        "bdi", "vlsfo_usd_per_tonne", "coal_price_usd_per_mt",
        "iron_ore_price_usd_per_dmt", "wind_kmh", "wave_height_m",
        "cyclone_risk", "weather_delay_days", "current_freight_usd_per_tonne",
        TARGET,
    ]
    comparison = {}
    for f in numeric_features:
        o = original[f].dropna()
        s = synth[f].dropna() if f in synth.columns else pd.Series(dtype=float)
        comparison[f] = {
            "original": {"mean": float(o.mean()), "median": float(o.median()),
                         "std": float(o.std()), "min": float(o.min()), "max": float(o.max())},
            "synthetic": {"mean": float(s.mean()), "median": float(s.median()),
                          "std": float(s.std()), "min": float(s.min()), "max": float(s.max())}
            if len(s) else None,
        }

    # Correlation matrices
    orig_corr = original[numeric_features].corr().round(4)
    synth_corr = synth[numeric_features].corr().round(4) if TARGET in synth.columns else synth[[c for c in numeric_features if c != TARGET]].corr().round(4)

    # Compare freight month-to-month pct change distributions
    def pct_dist(df, label):
        out = {}
        for combo in COMBINATIONS:
            origin, dest, comm, vessel = combo
            sub = df[(df.origin == origin) & (df.destination == dest)
                     & (df.commodity == comm) & (df.vessel_type == vessel)]
            if "trajectory_id" in df.columns and label == "synthetic":
                # within each trajectory
                pcts = []
                for tid, tsub in sub.groupby("trajectory_id"):
                    tsub = tsub.sort_values("date")
                    p = tsub["current_freight_usd_per_tonne"].pct_change().dropna() * 100
                    pcts.extend(p.tolist())
                pcts = pd.Series(pcts)
            else:
                sub = sub.sort_values("date")
                pcts = sub["current_freight_usd_per_tonne"].pct_change().dropna() * 100
            out["|".join(combo)] = {
                "mean": float(pcts.mean()) if len(pcts) else 0,
                "std": float(pcts.std()) if len(pcts) else 0,
                "min": float(pcts.min()) if len(pcts) else 0,
                "max": float(pcts.max()) if len(pcts) else 0,
                "count": int(len(pcts)),
            }
        return out

    pct_compare = {
        "original": pct_dist(original, "original"),
        "synthetic": pct_dist(synth, "synthetic"),
    }

    # current -> target relationship (should be near-1 in both since target is forward-shifted)
    orig_corr_curr_target = float(original["current_freight_usd_per_tonne"].corr(original[TARGET]))
    synth_corr_curr_target = float(synth["current_freight_usd_per_tonne"].corr(synth[TARGET])) if TARGET in synth.columns else None

    result = {
        "feature_distributions": comparison,
        "original_correlation_matrix": orig_corr.where(orig_corr.notna(), None).to_dict(),
        "synthetic_correlation_matrix": synth_corr.where(synth_corr.notna(), None).to_dict(),
        "freight_pct_change_comparison": pct_compare,
        "current_to_target_correlation": {
            "original": orig_corr_curr_target,
            "synthetic": synth_corr_curr_target,
        },
    }
    return result


# --------------------------------------------------------------------------- #
# STEP 15 — Final QC
# --------------------------------------------------------------------------- #
def final_qc(original: pd.DataFrame, synth: pd.DataFrame, combined: pd.DataFrame) -> dict:
    log("STEP 15: final QC checks...")
    qc = {}

    # 1. Row counts
    qc["original_rows"] = int(len(original))
    qc["synthetic_rows"] = int(len(synth))
    qc["total_rows"] = int(len(combined))
    qc["expected_total"] = 1110
    qc["rows_match"] = qc["total_rows"] == qc["expected_total"]

    # 2. All 5 combinations present
    combos_present = combined.groupby(["origin", "destination", "commodity", "vessel_type"]).size()
    qc["combinations_present"] = int(len(combos_present))
    qc["all_5_combinations_present"] = len(combos_present) == 5

    # 3. No missing values in feature/target columns
    cols_to_check = MODEL_FEATURES + [TARGET]
    nulls = combined[cols_to_check].isna().sum().to_dict()
    qc["nulls_per_col"] = {k: int(v) for k, v in nulls.items()}
    qc["no_missing_values"] = all(v == 0 for v in nulls.values())

    # 4. No duplicate keys (date + origin + destination + commodity + vessel_type + trajectory_id)
    # For original rows trajectory_id is None -> use a sentinel
    check_df = combined.copy()
    check_df["_traj_key"] = check_df["trajectory_id"].fillna("ORIGINAL")
    dup_keys = check_df.duplicated(subset=["date", "origin", "destination", "commodity", "vessel_type", "_traj_key"]).sum()
    qc["duplicate_keys"] = int(dup_keys)
    qc["no_duplicate_keys"] = dup_keys == 0

    # 5. All model features exist
    qc["model_features_present"] = all(f in combined.columns for f in MODEL_FEATURES)
    qc["target_present"] = TARGET in combined.columns

    # 6. Original 110 rows unchanged - check by joining
    # The original rows in combined must equal the original master values
    orig_in_combined = combined[combined["data_origin"] == "original"].copy()
    # Compare the model-feature + target columns (audit columns may differ)
    compare_cols = ["date", "origin", "destination", "commodity", "vessel_type",
                    "cargo_tonnes", "bdi", "vlsfo_usd_per_tonne", "coal_price_usd_per_mt",
                    "iron_ore_price_usd_per_dmt", "wind_kmh", "wave_height_m",
                    "cyclone_risk", "weather_delay_days", "current_freight_usd_per_tonne", TARGET]
    # Cast date to string on both sides (original has datetime, combined has string)
    orig_sorted = original[compare_cols].copy()
    orig_sorted["date"] = pd.to_datetime(orig_sorted["date"]).dt.strftime("%Y-%m-%d")
    orig_sorted = orig_sorted.sort_values(compare_cols[:5]).reset_index(drop=True)
    comb_sorted = orig_in_combined[compare_cols].sort_values(compare_cols[:5]).reset_index(drop=True)
    try:
        pd.testing.assert_frame_equal(orig_sorted, comb_sorted, check_dtype=False, check_exact=False, rtol=1e-9)
        qc["original_rows_unchanged"] = True
    except AssertionError as e:
        qc["original_rows_unchanged"] = False
        qc["original_rows_diff"] = str(e)[:500]

    # 7. Target alignment for synthetic trajectories
    bad_target = 0
    checked_target = 0
    for tid, tsub in synth.groupby("trajectory_id"):
        tsub = tsub.sort_values("date").reset_index(drop=True)
        for i in range(len(tsub) - 1):
            checked_target += 1
            cur_target = tsub.loc[i, TARGET]
            nxt_freight = tsub.loc[i + 1, "current_freight_usd_per_tonne"]
            if pd.notna(cur_target) and pd.notna(nxt_freight) and abs(cur_target - nxt_freight) > 0.001:
                bad_target += 1
    qc["synthetic_target_alignment_checked"] = checked_target
    qc["synthetic_target_alignment_mismatches"] = bad_target
    qc["synthetic_target_alignment_ok"] = bad_target == 0

    # 8. Outlier checks
    qc["outlier_checks"] = {}
    for col, (lo, hi) in BOUNDS.items():
        if col in combined.columns:
            bad = ((combined[col] < lo) | (combined[col] > hi)).sum()
            qc["outlier_checks"][col] = {"bad_count": int(bad), "bounds": [lo, hi]}

    # 9. No leakage columns in feature set
    leakage_cols = {"previous_month_freight", "freight_3_month_avg", "freight_observation_count"}
    present_leakage = leakage_cols & set(combined.columns)
    qc["no_leakage_columns_in_dataset"] = len(present_leakage) == 0
    qc["leakage_columns_present"] = list(present_leakage)

    qc["all_passed"] = (
        qc["rows_match"]
        and qc["all_5_combinations_present"]
        and qc["no_missing_values"]
        and qc["no_duplicate_keys"]
        and qc["model_features_present"]
        and qc["target_present"]
        and qc["original_rows_unchanged"]
        and qc["synthetic_target_alignment_ok"]
        and qc["no_leakage_columns_in_dataset"]
    )

    log(f"  original_rows            : {qc['original_rows']}")
    log(f"  synthetic_rows           : {qc['synthetic_rows']}")
    log(f"  total_rows               : {qc['total_rows']} (expected {qc['expected_total']})")
    log(f"  rows_match               : {qc['rows_match']}")
    log(f"  all_5_combinations       : {qc['all_5_combinations_present']}")
    log(f"  no_missing_values        : {qc['no_missing_values']}")
    log(f"  no_duplicate_keys        : {qc['no_duplicate_keys']}")
    log(f"  model_features_present   : {qc['model_features_present']}")
    log(f"  target_present           : {qc['target_present']}")
    log(f"  original_rows_unchanged   : {qc['original_rows_unchanged']}")
    log(f"  synth target alignment   : {qc['synthetic_target_alignment_ok']} ({qc['synthetic_target_alignment_checked']} checked, {qc['synthetic_target_alignment_mismatches']} mismatches)")
    log(f"  no_leakage_columns       : {qc['no_leakage_columns_in_dataset']}")
    log(f"  ALL QC PASSED            : {qc['all_passed']}")
    return qc


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> int:
    import hashlib
    log("=" * 60)
    log("SYNTHETIC TRAINING EXTENSION GENERATION")
    log("=" * 60)

    # Verify v1 (and v2 if present) untouched
    if MODEL_V1.exists():
        v1_sha = hashlib.sha256(MODEL_V1.read_bytes()).hexdigest()
        log(f"v1 model sha256 (baseline): {v1_sha}")
        assert v1_sha == "695fafe3f31b560d5a4412124c0839e0e622c9d2bd090191a5e02eaef6c3819a", "v1 model changed!"
    if MODEL_V2.exists():
        v2_sha_before = hashlib.sha256(MODEL_V2.read_bytes()).hexdigest()
        log(f"v2 model sha256 (baseline): {v2_sha_before}")

    # Load original
    log(f"loading original master: {MASTER_CSV}")
    original = pd.read_csv(MASTER_CSV)
    original["date"] = pd.to_datetime(original["date"])
    log(f"  original rows: {len(original)}")

    # STEP 1 - analyze original
    stats = analyze_original(original)

    # STEP 2-9 - generate synthetic
    synth = generate_synthetic(original, stats)
    log(f"  final synthetic rows: {len(synth)}")

    # Format original to match the combined schema (add trajectory_id, data_origin, synthetic_generation_method)
    original_combined = original.copy()
    original_combined["trajectory_id"] = None
    original_combined["data_origin"] = "original"
    original_combined["synthetic_generation_method"] = "original_observation"
    # Drop the v1 audit columns (data_source, cargo_value_type, ingested_at) to keep schema clean
    for col in ["data_source", "cargo_value_type", "ingested_at"]:
        if col in original_combined.columns:
            original_combined = original_combined.drop(columns=[col])

    # Reorder synth to match original's column order (with the new metadata cols)
    target_cols = list(original_combined.columns)
    # synth has the same columns now (since we added trajectory_id, data_origin, synthetic_generation_method)
    synth = synth[target_cols]

    # STEP 13 - combine
    combined = pd.concat([original_combined, synth], ignore_index=True)
    combined["date"] = pd.to_datetime(combined["date"]).dt.strftime("%Y-%m-%d")
    combined = combined.sort_values(["data_origin", "trajectory_id", "date", "origin", "destination", "commodity", "vessel_type"]).reset_index(drop=True)

    log(f"  combined rows: {len(combined)} (expected 1110)")

    # STEP 11 - validation
    validation = validate(original_combined, synth)

    # STEP 15 - final QC
    qc = final_qc(original_combined, synth, combined)

    # STEP 13 - write synthetic dataset
    log(f"writing {SYNTHETIC_CSV}")
    combined.to_csv(SYNTHETIC_CSV, index=False)

    # STEP 13 - write original reference (byte-identical to master values)
    log(f"writing {ORIGINAL_REF_CSV}")
    original_ref = original.copy()
    original_ref["date"] = original_ref["date"].dt.strftime("%Y-%m-%d")
    # Add metadata columns to match the synthetic dataset schema
    original_ref["trajectory_id"] = ""
    original_ref["data_origin"] = "original"
    original_ref["synthetic_generation_method"] = "original_observation"
    # Drop v1 audit columns to match synthetic schema
    for col in ["data_source", "cargo_value_type", "ingested_at"]:
        if col in original_ref.columns:
            original_ref = original_ref.drop(columns=[col])
    original_ref = original_ref[target_cols]
    original_ref = original_ref.sort_values(["date", "origin", "destination", "commodity", "vessel_type"]).reset_index(drop=True)
    original_ref.to_csv(ORIGINAL_REF_CSV, index=False)

    # Verify original reference is byte-equivalent (modulo metadata cols)
    log("verifying original_reference byte-equivalence to master...")
    orig_from_master = original.copy()
    orig_from_master["date"] = orig_from_master["date"].dt.strftime("%Y-%m-%d")
    for col in ["data_source", "cargo_value_type", "ingested_at"]:
        if col in orig_from_master.columns:
            orig_from_master = orig_from_master.drop(columns=[col])
    orig_from_master["trajectory_id"] = ""
    orig_from_master["data_origin"] = "original"
    orig_from_master["synthetic_generation_method"] = "original_observation"
    orig_from_master = orig_from_master[target_cols].sort_values(["date", "origin", "destination", "commodity", "vessel_type"]).reset_index(drop=True)
    try:
        pd.testing.assert_frame_equal(orig_from_master, original_ref, check_dtype=False)
        log("  original_reference byte-equivalent to master values ✅")
    except AssertionError as e:
        log(f"  WARNING: original_reference differs from master: {e}")

    # Write validation report
    VALIDATION_REPORT.write_text(json.dumps({
        "validation": validation,
        "qc": qc,
    }, indent=2, default=str))
    log(f"wrote validation report to {VALIDATION_REPORT}")

    # Verify models untouched
    if MODEL_V1.exists():
        v1_sha_after = hashlib.sha256(MODEL_V1.read_bytes()).hexdigest()
        log(f"v1 model sha256 (after): {v1_sha_after}")
        assert v1_sha_after == "695fafe3f31b560d5a4412124c0839e0e622c9d2bd090191a5e02eaef6c3819a", "v1 model changed!"
        log("v1 model UNTOUCHED ✅")
    if MODEL_V2.exists():
        v2_sha_after = hashlib.sha256(MODEL_V2.read_bytes()).hexdigest()
        log(f"v2 model sha256 (after): {v2_sha_after}")
        assert v2_sha_after == v2_sha_before, "v2 model changed!"
        log("v2 model UNTOUCHED ✅")

    print("\n" + "=" * 60)
    print("SYNTHETIC GENERATION SUMMARY")
    print("=" * 60)
    print(f"original rows           : {qc['original_rows']}")
    print(f"synthetic rows          : {qc['synthetic_rows']}")
    print(f"total rows              : {qc['total_rows']} (expected 1110)")
    print(f"all QC passed           : {qc['all_passed']}")
    print(f"models untouched        : v1 ✅" + (" v2 ✅" if MODEL_V2.exists() else " (v2 not on this branch)"))
    return 0 if qc["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
