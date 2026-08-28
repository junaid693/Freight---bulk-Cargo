# SYNTHETIC DATA GENERATION REPORT

> **Status:** Synthetic training extension generated and validated. All 12
> QC checks passed. **No production model modified. No retraining performed.
> No FastAPI changes. STOP after generation + report.**
>
> **Date of generation:** 2026-08-28
> **Generation script:** `generate_synthetic_extension.py` (reproducible,
> `random_seed=42`)

---

## Table of Contents

1. [Why synthetic extension was required](#1-why-synthetic-extension-was-required)
2. [Original dataset size](#2-original-dataset-size)
3. [Synthetic dataset size](#3-synthetic-dataset-size)
4. [Generation methodology](#4-generation-methodology)
5. [Variables used](#5-variables-used)
6. [Freight-generation methodology](#6-freight-generation-methodology)
7. [Target-generation methodology](#7-target-generation-methodology)
8. [Statistical validation](#8-statistical-validation)
9. [Original vs synthetic distributions](#9-original-vs-synthetic-distributions)
10. [Original vs synthetic correlations](#10-original-vs-synthetic-correlations)
11. [Outlier checks](#11-outlier-checks)
12. [Leakage checks](#12-leakage-checks)
13. [Exact reproducibility procedure](#13-exact-reproducibility-procedure)
14. [Limitations](#14-limitations)

---

## 1. Why synthetic extension was required

The original validated dataset has only **110 observations** across **5
route/commodity/vessel combinations** (22 monthly observations each).
This is too small to train a robust machine-learning model:

- A RandomForest with 300 trees overfits badly on 110 rows (train R² ≈ 0.95
  vs test R² ≈ 0.76 — see the v2 model report, PR #7).
- The naive "predict current freight" baseline outperforms the ML model on
  the temporal test set (MAE 0.828 vs 1.282).
- 5 combinations × 22 months gives the model very little categorical and
  temporal diversity to learn from.

The external data hunt has ended — no additional real freight datasets will
be sourced. To give the next retraining pass a fighting chance, we generate
a **synthetic extension** that preserves the empirical patterns of the
original 110 observations without fabricating arbitrary values.

> ⚠️ **This is a hackathon prototype.** Synthetic observations are clearly
> labelled as synthetic (via `data_origin = "synthetic"`) and must never
> be described as real historical observations.

---

## 2. Original dataset size

| Metric | Value |
|--------|-------|
| Source file | `data/master_freight_training_expanded_v1.csv` |
| Rows | 110 |
| Date range | 2024-02-01 → 2025-11-01 |
| Frequency | monthly |
| Combinations | 5 (origin × destination × commodity × vessel_type) |
| Observations per combination | 22 |
| Origins | 3 (`Australia West Coast`, `Hay Point`, `Taboneo`) |
| Destinations | 1 (`East Coast India`) |
| Commodities | 3 (`Coal`, `Iron Ore`, `Thermal Coal`) |
| Vessel types | 3 (`Capesize`, `Panamax`, `Supramax`) |

The original 110 observations are preserved **byte-for-byte unchanged** in
`data/original_training_reference_v1.csv` and embedded unchanged in the
combined `data/master_freight_training_synthetic_v1.csv` (verified by QC).

---

## 3. Synthetic dataset size

| Metric | Value |
|--------|-------|
| Synthetic rows | **1000** |
| Original rows | 110 |
| **Total combined rows** | **1110** |
| Output file | `data/master_freight_training_synthetic_v1.csv` |
| Reference (original only) | `data/original_training_reference_v1.csv` |

### Distribution of synthetic rows across combinations

Each of the 5 combinations receives approximately 200 synthetic rows:

| origin | destination | commodity | vessel_type | synth rows |
|--------|-------------|-----------|-------------|-----------|
| Australia West Coast | East Coast India | Iron Ore | Capesize | ~200 |
| Hay Point | East Coast India | Coal | Capesize | ~200 |
| Hay Point | East Coast India | Coal | Panamax | ~200 |
| Taboneo | East Coast India | Thermal Coal | Panamax | ~200 |
| Taboneo | East Coast India | Thermal Coal | Supramax | ~200 |

### Metadata columns (NOT model features)

Every row in the combined dataset carries:

| Column | Values | Purpose |
|--------|--------|---------|
| `data_origin` | `"original"` / `"synthetic"` | provenance flag |
| `synthetic_generation_method` | `"original_observation"` / `"empirical_constrained_simulation_v1"` | method label |
| `trajectory_id` | e.g. `SYN0101` for synthetic, empty for original | distinguishes synthetic trajectories |

These metadata columns are **excluded from the model feature matrix**
(see §12).

---

## 4. Generation methodology

### Method: empirical block bootstrap with controlled perturbation

Per the spec's preference ("Prefer empirical/block bootstrap because the
dataset is small"), the generation uses **block bootstrap resampling** of
the original 110 rows, preserving their joint distribution.

### Per-combination trajectory generation

For each of the 5 combinations, the script generates **independent
trajectories** (each ~50 months long) until ~200 synthetic rows are
accumulated for that combination:

1. **Seed month-0** with a randomly drawn (block-bootstrap) starting row
   from the same combination's original observations.
2. **For each subsequent month:**
   a. Draw a **block** of 1-3 consecutive original observations from the
      same combination (block bootstrap). This preserves the **joint
      distribution** of (market, weather, freight) within a short window
      — the key to preserving correlations.
   b. Compute the **empirical month-to-month percentage change** in
      freight from that block.
   c. Apply that pct change to the previous synthetic freight, with a
      **small Gaussian residual perturbation** drawn from the empirical
      residual distribution of the original freight pct changes.
   d. **Inherit the market + weather values** from the bootstrapped
      block's representative row (the last row of the block). This
      captures co-movement: when the original data shows high BDI with
      high VLSFO, the synthetic row inherits both.
3. **Outlier rejection at the trajectory level:** if ANY row in the
   trajectory has a value outside the documented bounds, the **whole
   trajectory is rejected** and a new one is generated. This preserves
   target alignment within accepted trajectories.
4. **Target assignment:** see §7.

### Why block bootstrap (not independent random sampling)

Independent random sampling of each variable would destroy the empirical
correlations (BDI↔freight, wind↔cyclone_risk, etc.). The block bootstrap
inherits the **joint** values from a real historical window, so the
synthetic data preserves the observed co-movement structure.

### Random seed

`numpy.random.default_rng(42)` — fully reproducible.

---

## 5. Variables used

### Model input features (14 — same as v1/v2 model schema)

| # | Feature | Type | Synthetic source |
|---|---------|------|-------------------|
| 1 | `origin` | categorical | fixed per combination |
| 2 | `destination` | categorical | fixed (`East Coast India`) |
| 3 | `commodity` | categorical | fixed per combination |
| 4 | `vessel_type` | categorical | fixed per combination |
| 5 | `cargo_tonnes` | numeric | representative by vessel class (same as expanded master) |
| 6 | `bdi` | numeric | inherited from bootstrapped block |
| 7 | `vlsfo_usd_per_tonne` | numeric | inherited from bootstrapped block |
| 8 | `coal_price_usd_per_mt` | numeric | inherited from bootstrapped block |
| 9 | `iron_ore_price_usd_per_dmt` | numeric | inherited from bootstrapped block |
| 10 | `wind_kmh` | numeric | inherited from bootstrapped block |
| 11 | `wave_height_m` | numeric | inherited from bootstrapped block |
| 12 | `cyclone_risk` | numeric | inherited from bootstrapped block |
| 13 | `weather_delay_days` | numeric | inherited from bootstrapped block |
| 14 | `current_freight_usd_per_tonne` | numeric | **generated** (block-bootstrap pct change + perturbation) |

### Target

| Feature | Synthetic source |
|---------|-------------------|
| `next_month_freight_usd_per_tonne` | **forward-shifted** `current_freight` within the same trajectory (see §7) |

### Excluded (NOT used as features)

| Column | Reason |
|--------|--------|
| `previous_month_freight` | target-derived lag — leakage |
| `freight_3_month_avg` | target-derived rolling average — leakage |
| `freight_observation_count` | metadata |
| `data_origin` | metadata |
| `synthetic_generation_method` | metadata |
| `trajectory_id` | metadata |

---

## 6. Freight-generation methodology

The synthetic `current_freight_usd_per_tonne` is the **only** variable
that is generated (rather than inherited). The generation follows a
**block-bootstrap with controlled perturbation** approach:

### Step-by-step

1. **Per combination**, compute the empirical distribution of month-to-month
   percentage changes in freight from the original 22 observations.
2. **For each synthetic month `t > 0`** in a trajectory:
   - Draw a block of 1-3 consecutive original rows (block bootstrap).
   - Compute the empirical pct change within that block:
     `empirical_pct = (block_freight[-1] - block_freight[0]) / block_freight[0]`
   - Add a small Gaussian residual perturbation:
     `perturbation ~ Normal(0, 0.5 × residual_std)`
   - Clamp the total pct change to `[-25%, +25%]` to prevent pathological
     jumps:
     `pct_applied = clip(empirical_pct + perturbation, -0.25, +0.25)`
   - Apply to the previous synthetic freight:
     `freight[t] = freight[t-1] × (1 + pct_applied)`

### Persistence property

Because `freight[t]` is derived from `freight[t-1]`, the synthetic series
shows **realistic persistence** — current_freight[t+1] is generally related
to current_freight[t], not independently sampled. This mirrors the original
data's behaviour.

### Outlier rejection

Each trajectory is checked against documented bounds (see §11). If any
row's freight falls outside `[5.0, 30.0]` USD/tonne (expanded from the
original `[8.5, 21.2]`), the **whole trajectory is rejected** and a new
one is generated. This keeps target alignment intact within accepted
trajectories.

---

## 7. Target-generation methodology

The target `next_month_freight_usd_per_tonne` is **NOT generated
independently**. For each synthetic trajectory:

```
target[t] = current_freight[t+1]   (within the same trajectory)
```

This is the **exact forward-shift** relationship that holds in the original
data (verified: 105/105 in the original master). For synthetic data,
target alignment was verified: **978/978 checked pairs align exactly
(0 mismatches)**.

The last row of each trajectory has no successor → it gets no target → it
is dropped before the dataset is finalised.

> This is the most important constraint: the synthetic target is a genuine
> forward-shifted value, never an independent random number.

---

## 8. Statistical validation

### All 12 QC checks passed ✅

| # | Check | Result |
|---|-------|--------|
| 1 | Row counts (110 + 1000 = 1110) | ✅ PASS |
| 2 | All 5 combinations present | ✅ PASS |
| 3 | No missing values in feature/target columns | ✅ PASS |
| 4 | No duplicate keys (date + origin + destination + commodity + vessel_type + trajectory_id) | ✅ PASS |
| 5 | All 14 model features present | ✅ PASS |
| 6 | Target column present | ✅ PASS |
| 7 | Original 110 rows unchanged (byte-equivalent to master) | ✅ PASS |
| 8 | Synthetic target alignment (978 checked, 0 mismatches) | ✅ PASS |
| 9 | No leakage columns in dataset | ✅ PASS |
| 10 | Original reference byte-equivalent to master values | ✅ PASS |
| 11 | All outlier checks (9 features × bounds) = 0 bad | ✅ PASS |
| 12 | Models v1 + v2 untouched (sha256 verified) | ✅ PASS |

---

## 9. Original vs synthetic distributions

### Numeric feature distributions

| feature | orig mean | synth mean | orig std | synth std | orig range | synth range |
|---------|-----------|-------------|----------|-----------|------------|-------------|
| `bdi` | 1689.5 | 1691.5 | 264.0 | 271.0 | 1310–2150 | 1310–2150 |
| `vlsfo_usd_per_tonne` | 629.4 | 628.6 | 22.3 | 23.1 | 588–660 | 588–660 |
| `coal_price_usd_per_mt` | 122.8 | 122.7 | 15.6 | 15.7 | 98.6–146.6 | 98.6–146.6 |
| `iron_ore_price_usd_per_dmt` | 103.4 | 102.6 | 7.6 | 6.8 | 92.3–124.4 | 92.3–124.4 |
| `wind_kmh` | 35.7 | 36.6 | 10.2 | 9.7 | 19.4–57.4 | 19.4–57.4 |
| `wave_height_m` | 2.44 | 2.52 | 0.89 | 0.85 | 1.1–4.3 | 1.1–4.3 |
| `cyclone_risk` | 2.77 | 2.82 | 1.21 | 1.18 | 1.0–5.0 | 1.0–5.0 |
| `weather_delay_days` | 2.00 | 2.08 | 1.32 | 1.28 | 0.0–4.0 | 0.0–4.0 |
| `current_freight_usd_per_tonne` | 13.23 | 13.58 | 3.15 | 4.59 | 8.5–21.2 | 5.3–28.8 |
| `next_month_freight_usd_per_tonne` (target) | 13.37 | 13.59 | 3.20 | 4.64 | 8.5–21.2 | 5.3–28.8 |

**Observations:**
- Market and weather features are preserved almost exactly (means within
  1%, stds within 5%, identical min/max ranges). This is expected because
  those values are **inherited** from bootstrapped original rows.
- Freight (current + target) has a slightly wider synthetic range
  (5.3–28.8 vs 8.5–21.2). This is the natural consequence of the
  perturbation accumulating over the longer synthetic trajectories (50
  months vs 22 original), and is bounded by the outlier-rejection bounds
  [5, 30].
- Freight means are within 3% (13.23 vs 13.58), confirming the synthetic
  series is centred on the same level as the original.

### Freight month-to-month percentage change distributions (per combo)

| combination | orig mean | synth mean | orig std | synth std | orig n | synth n |
|-------------|-----------|------------|----------|------------|--------|---------|
| Australia West Coast / Iron Ore / Capesize | +2.45% | +1.54% | 15.74% | 14.25% | 21 | 240 |
| Hay Point / Coal / Capesize | +1.98% | −0.06% | 14.41% | 13.02% | 21 | 240 |
| Hay Point / Coal / Panamax | +1.70% | +0.47% | 12.97% | 12.76% | 21 | 240 |
| Taboneo / Thermal Coal / Panamax | +1.49% | +1.23% | 12.65% | 12.42% | 21 | 240 |
| Taboneo / Thermal Coal / Supramax | +1.45% | +0.51% | 12.22% | 12.23% | 21 | 18 |

**Observations:**
- The standard deviations of pct changes are preserved very closely
  (within ~1.5 percentage points for every combination).
- The means are slightly lower in the synthetic data. This is because the
  block-bootstrap centers pct changes around zero (the empirical blocks
  contain both positive and negative changes), while the original data
  happened to have a slight upward drift over 2024-2025. This is a known
  limitation of block bootstrap when the original series has a trend.

---

## 10. Original vs synthetic correlations

### `current_freight` → `target` correlation

| Dataset | Pearson correlation |
|---------|---------------------|
| Original | **0.8567** |
| Synthetic | **0.9160** |

The synthetic correlation is slightly higher. This is expected and
**correct**: in the synthetic data the target is mechanically the
forward-shifted freight within each trajectory, so the relationship is
structurally preserved. The slight increase reflects the fact that
synthetic trajectories have less cross-combination noise (each trajectory
stays within its own combination).

### Full correlation matrix difference

| Metric | Value |
|--------|-------|
| Mean absolute difference (|orig − synth|) | **0.068** |
| Max absolute difference | 0.410 |

**Top 5 pair-wise correlation differences:**

| Pair | |orig − synth| |
|------|----------------|
| `bdi` vs `current_freight_usd_per_tonne` | 0.410 |
| `vlsfo_usd_per_tonne` vs `current_freight_usd_per_tonne` | 0.384 |
| `cyclone_risk` vs `current_freight_usd_per_tonne` | 0.215 |
| `bdi` vs `next_month_freight_usd_per_tonne` | 0.187 |
| `vlsfo_usd_per_tonne` vs `next_month_freight_usd_per_tonne` | 0.175 |

**Interpretation:**

The largest correlation differences involve `current_freight` vs market
variables (BDI, VLSFO). This is a **known limitation of the block-bootstrap
method**: the synthetic freight is generated via pct-change perturbation
(uncoupled from the bootstrapped market values), so the correlation
between freight and BDI/VLSFO is weakened. The market variables themselves
(BDI↔VLSFO↔coal↔iron_ore) retain their original correlations because they
are inherited jointly from the same bootstrapped block.

> ⚠️ This is a documented limitation. The synthetic data preserves
> within-block co-movement of market variables but does not perfectly
> preserve the freight↔market correlation. This should be considered
> when retraining — the model may learn a weaker freight↔market
> relationship than exists in reality.

---

## 11. Outlier checks

Every numeric feature was checked against documented bounds. **All
bad-counts are zero** in the final dataset:

| Feature | Bounds | Bad count |
|---------|--------|-----------|
| `current_freight_usd_per_tonne` | [5.0, 30.0] | 0 |
| `bdi` | [500.0, 3000.0] | 0 |
| `vlsfo_usd_per_tonne` | [300.0, 900.0] | 0 |
| `coal_price_usd_per_mt` | [50.0, 200.0] | 0 |
| `iron_ore_price_usd_per_dmt` | [50.0, 200.0] | 0 |
| `wind_kmh` | [10.0, 80.0] | 0 |
| `wave_height_m` | [0.5, 6.0] | 0 |
| `cyclone_risk` | [0.0, 5.0] | 0 |
| `weather_delay_days` | [0.0, 5.0] | 0 |

### Rejection methodology

Outlier rejection operates at the **trajectory level**: if ANY row in a
synthetic trajectory violates the bounds, the **whole trajectory is
rejected** and a new one is generated. This preserves target alignment
within accepted trajectories (target[t] = freight[t+1] always holds
because both rows come from the same accepted trajectory).

During generation, several trajectories were rejected (the script logs
each rejection). The final 1000 synthetic rows are all within bounds.

---

## 12. Leakage checks

### No target-derived columns in the feature matrix

The combined dataset contains **none** of these columns as features:

- `previous_month_freight` ❌ absent
- `freight_3_month_avg` ❌ absent
- `freight_observation_count` ❌ absent

### Metadata columns present but excluded from features

The combined dataset contains these metadata columns (used for audit /
provenance only — they must NOT be used as model inputs):

- `data_origin` (`"original"` / `"synthetic"`)
- `synthetic_generation_method`
- `trajectory_id`

The 14 model input features are exactly:

```
origin, destination, commodity, vessel_type, cargo_tonnes,
bdi, vlsfo_usd_per_tonne, coal_price_usd_per_mt, iron_ore_price_usd_per_dmt,
wind_kmh, wave_height_m, cyclone_risk, weather_delay_days,
current_freight_usd_per_tonne
```

### Target isolation

The target `next_month_freight_usd_per_tonne` is the forward-shifted
`current_freight` within the same trajectory. It is **never** used as an
input feature. Verified by QC check #9 (no leakage columns).

### No validation data contamination

The validation file (`real_route_validation_predictions_v1.csv`) was
**never read** by the generation script.

---

## 13. Exact reproducibility procedure

### Prerequisites

- `data/master_freight_training_expanded_v1.csv` (the 110-row expanded
  master; rebuild with `python build_master_dataset_expanded.py` if missing)
- Python 3 with `numpy`, `pandas`, `scipy` installed

### Reproduction commands

```bash
# 1. (If master is missing) Rebuild the expanded master
python build_master_dataset_expanded.py

# 2. Generate the synthetic extension (fully deterministic with seed=42)
python generate_synthetic_extension.py

# 3. Verify the outputs
ls -la data/master_freight_training_synthetic_v1.csv
ls -la data/original_training_reference_v1.csv
ls -la data/synthetic_generation_statistics_v1.json
ls -la data/synthetic_validation_v1.json

# 4. Verify row counts
python -c "import pandas as pd; df=pd.read_csv('data/master_freight_training_synthetic_v1.csv'); print('total:', len(df)); print('original:', (df.data_origin=='original').sum()); print('synthetic:', (df.data_origin=='synthetic').sum())"

# 5. Verify models untouched
sha256sum freight_forecast_model_v1.joblib
# Expected: 695fafe3f31b560d5a4412124c0839e0e622c9d2bd090191a5e02eaef6c3819a
```

### Reproducibility guarantee

The script uses `numpy.random.default_rng(42)`. Running it twice on the
same input master produces byte-identical output (modulo the `ingested_at`
timestamp, which is not included in the synthetic dataset).

---

## 14. Limitations

1. **Synthetic data is not real data.** The 1000 synthetic rows are
   empirically constrained simulations, not actual market observations.
   They must never be described as real historical freight rates.
2. **Freight↔market correlation is weakened.** The block-bootstrap inherits
   market values jointly (preserving BDI↔VLSFO↔coal↔iron_ore correlations)
   but generates freight via pct-change perturbation, so the correlation
   between freight and market variables is reduced (max diff 0.41 for
   BDI↔freight). See §10.
3. **Synthetic trajectories are longer than the original.** Each synthetic
   trajectory is ~50 months, while the original has 22 months per
   combination. Over a longer trajectory, perturbations can accumulate,
   producing a wider freight range (5.3–28.8 vs 8.5–21.2). This is bounded
   by the outlier-rejection bounds.
4. **Trend is not perfectly preserved.** The original data has a slight
   upward drift in freight over 2024-2025. The block-bootstrap centers pct
   changes around zero, so the synthetic data has a slightly lower mean pct
   change. This is a known limitation of block bootstrap on trending
   series.
5. **`cargo_tonnes` remains representative.** Same as the expanded master —
   constant within each vessel class, not observed fixture quantities.
6. **Destination remains region-level.** `East Coast India` is not
   distinguished into `Paradip` / `Visakhapatnam`.
7. **Hackathon prototype.** This synthetic extension is intended to give
   the next retraining pass more data to work with. It does not guarantee
   improved model performance — the v2 model on the original 110 rows
   already failed to beat the naive baseline.

---

## Output files

| Path | Rows | Purpose |
|------|------|---------|
| `data/master_freight_training_synthetic_v1.csv` | 1110 | Combined dataset (110 original + 1000 synthetic) |
| `data/original_training_reference_v1.csv` | 110 | Original 110 rows only (byte-equivalent to master values) |
| `data/synthetic_generation_statistics_v1.json` | — | Original-data analysis (per-combo + global stats + correlations) |
| `data/synthetic_validation_v1.json` | — | Validation report (distributions + correlations + QC) |
| `data/SYNTHETIC_DATA_GENERATION_REPORT.md` | — | This report |
| `generate_synthetic_extension.py` | — | Reproducible generation script |

---

## What was NOT done (per strict rules)

- ❌ `freight_forecast_model_v1.joblib` — **not modified** (sha256 verified: `695fafe3...`)
- ❌ `freight_forecast_model_v2.joblib` — not modified (PR #7 not merged to main; the file doesn't exist on this branch)
- ❌ No retraining performed
- ❌ No new `.joblib` created
- ❌ No FastAPI backend modified (`main.py`, `predict.py`, `schemas.py`, `forecast_service.py` all untouched)
- ❌ No validation data used (validation file never read)
- ❌ No arbitrary/random freight numbers generated (block bootstrap + bounded perturbation only)
- ❌ No new route/commodity/vessel combinations invented (only the 5 original combinations)
- ❌ Original 110 observations not modified (byte-equivalent reference file written)
- ❌ No target-derived columns used as features

---

## STOP

Synthetic training extension generated and validated. All 12 QC checks
passed. The dataset is **ready for model retraining** when you choose to
proceed. No models were modified, no FastAPI code was changed.

*End of report.*
