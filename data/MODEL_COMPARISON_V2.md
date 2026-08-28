# MODEL COMPARISON V2

> **Status:** V2 model trained, evaluated, and saved as a **separate** file.
> The existing `freight_forecast_model_v1.joblib` was **not modified or
> overwritten**. The FastAPI backend was **not modified**.
>
> **Date of training:** 2026-08-28
> **Training script:** `train_v2.py` (reproducible)
> **Saved model:** `freight_forecast_model_v2.joblib`

---

## Table of Contents

1. [Dataset](#1-dataset)
2. [Feature list](#2-feature-list)
3. [Excluded leakage features](#3-excluded-leakage-features)
4. [Train/test methodology](#4-traintest-methodology)
5. [Naive baseline metrics](#5-naive-baseline-metrics)
6. [Random Forest metrics](#6-random-forest-metrics)
7. [Gradient Boosting metrics](#7-gradient-boosting-metrics)
8. [RF-without-cargo metrics](#8-rf-without-cargo-metrics)
9. [Training vs test performance](#9-training-vs-test-performance)
10. [Feature importance](#10-feature-importance)
11. [Overfitting analysis](#11-overfitting-analysis)
12. [Selected model](#12-selected-model)
13. [Why it was selected](#13-why-it-was-selected)
14. [Limitations](#14-limitations)
15. [Model parameters](#15-model-parameters)
16. [Exact reproduction commands](#16-exact-reproduction-commands)

---

## 1. Dataset

- **File:** `data/master_freight_training_expanded_v1.csv`
- **Rows:** 110
- **Columns:** 19 (4 audit + 14 model features + 1 target)
- **Date range:** 2024-02-01 → 2025-11-01 (monthly)
- **Frequency:** monthly (day = 1)
- **Route × commodity × vessel combinations:** 5, each with 22 monthly observations
- **Origins (3):** `Australia West Coast`, `Hay Point`, `Taboneo`
- **Destinations (1):** `East Coast India` (region-level)
- **Commodities (3):** `Coal`, `Iron Ore`, `Thermal Coal`
- **Vessel types (3):** `Capesize`, `Panamax`, `Supramax`
- **Missing values:** 0
- **Duplicate keys:** 0
- **Target alignment:** 105/105 verified (target[t] = freight[t+1] for same route)

### Combinations in the dataset

| origin | destination | commodity | vessel_type | rows |
|--------|-------------|-----------|-------------|------|
| Australia West Coast | East Coast India | Iron Ore | Capesize | 22 |
| Hay Point | East Coast India | Coal | Capesize | 22 |
| Hay Point | East Coast India | Coal | Panamax | 22 |
| Taboneo | East Coast India | Thermal Coal | Panamax | 22 |
| Taboneo | East Coast India | Thermal Coal | Supramax | 22 |

---

## 2. Feature list

The 14 model input features (matching `freight_forecast_model_v1.joblib`'s
`feature_names_in_`):

| # | Feature | Type | Category |
|---|---------|------|----------|
| 1 | `origin` | categorical | route identity |
| 2 | `destination` | categorical | route identity |
| 3 | `commodity` | categorical | route identity |
| 4 | `vessel_type` | categorical | route identity |
| 5 | `cargo_tonnes` | numeric | cargo (representative) |
| 6 | `bdi` | numeric | market |
| 7 | `vlsfo_usd_per_tonne` | numeric | market |
| 8 | `coal_price_usd_per_mt` | numeric | market |
| 9 | `iron_ore_price_usd_per_dmt` | numeric | market |
| 10 | `wind_kmh` | numeric | weather |
| 11 | `wave_height_m` | numeric | weather |
| 12 | `cyclone_risk` | numeric | weather (derived) |
| 13 | `weather_delay_days` | numeric | weather (derived) |
| 14 | `current_freight_usd_per_tonne` | numeric | freight |

**Target:** `next_month_freight_usd_per_tonne`

---

## 3. Excluded leakage features

The following columns are present in the source data but were **excluded**
from the feature matrix because they are target-derived or metadata:

| Excluded column | Reason |
|-----------------|--------|
| `previous_month_freight` | target-derived lag (= `freight_rate[t-1]`); would leak the target |
| `freight_3_month_avg` | target-derived rolling average; same leakage risk |
| `freight_observation_count` | metadata, not a model input |
| `next_month_freight_usd_per_tonne` | **the target** — must never enter the feature matrix |
| `year`, `month_number`, `quarter_number` | calendar metadata — useful for CV splits but not model inputs |
| `data_source`, `cargo_value_type`, `ingested_at` | audit metadata only |

---

## 4. Train/test methodology

- **Split type:** chronological holdout (NOT random)
- **Sort key:** `date` ascending; temporal order preserved within every
  route/commodity/vessel combination
- **Split date:** `2025-07-01` (same cutoff used for every combination)
- **Training set:** `2024-02-01` → `2025-06-01` (17 months per combination)
- **Test set:** `2025-07-01` → `2025-11-01` (5 months per combination)

### Row counts

| Set | Rows | Date range |
|-----|------|-----------|
| Training | 85 | 2024-02-01 → 2025-06-01 |
| Test | 25 | 2025-07-01 → 2025-11-01 |
| **Total** | **110** | 2024-02-01 → 2025-11-01 |

### Why chronological

A random train/test split would leak future information into training
(next-month target leaking into the current-month feature row of the same
combination). The chronological split ensures every test row is later in
time than every training row, simulating a real-world deployment.

---

## 5. Naive baseline metrics

The naive baseline predicts:

```
prediction = current_freight_usd_per_tonne
```

("next month's freight will equal this month's freight" — a persistence
forecast).

| Set | MAE | RMSE | R² |
|-----|-----|------|-----|
| Training | 1.3082 | 1.8433 | 0.6660 |
| **Test** | **0.8280** | **1.0750** | **0.8819** |

---

## 6. Random Forest metrics

**Configuration:** `RandomForestRegressor(n_estimators=300, max_depth=8, min_samples_leaf=2, random_state=42)` with `OneHotEncoder(handle_unknown="ignore")` for the 4 categorical features, in a single sklearn `Pipeline`.

**With `cargo_tonnes`:**

| Set | MAE | RMSE | R² |
|-----|-----|------|-----|
| Training | 0.5176 | 0.6945 | 0.9526 |
| **Test** | **1.2878** | **1.5439** | **0.7564** |

---

## 7. Gradient Boosting metrics

**Configuration:** `GradientBoostingRegressor(n_estimators=200, max_depth=3, learning_rate=0.05, min_samples_leaf=3, random_state=42)` (conservative for 110 rows) with the same `OneHotEncoder` preprocessing in a single `Pipeline`.

| Set | MAE | RMSE | R² |
|-----|-----|------|-----|
| Training | 0.0772 | 0.0991 | 0.9990 |
| **Test** | **1.5665** | **1.7837** | **0.6749** |

> Training R² = 0.999 vs test R² = 0.675 → severe overfitting signal
> (see §11).

---

## 8. RF-without-cargo metrics

**Configuration:** identical to §6 but `cargo_tonnes` removed from the
feature set. Reason: `cargo_tonnes` is a **representative vessel capacity**,
not an observed shipment quantity, so it adds no real signal and could
introduce spurious splits.

| Set | MAE | RMSE | R² |
|-----|-----|------|-----|
| Training | 0.5177 | 0.6935 | 0.9527 |
| **Test** | **1.2820** | **1.5379** | **0.7583** |

---

## 9. Training vs test performance

| Model | Train MAE | Test MAE | MAE gap | Train R² | Test R² | R² gap |
|-------|-----------|----------|---------|----------|---------|--------|
| Naive baseline | 1.3082 | 0.8280 | −0.4802 | 0.6660 | 0.8819 | −0.2159 |
| RF (with cargo) | 0.5176 | 1.2878 | +0.7702 | 0.9526 | 0.7564 | +0.1962 |
| GradientBoosting | 0.0772 | 1.5665 | +1.4893 | 0.9990 | 0.6749 | +0.3242 |
| RF (no cargo) | 0.5177 | 1.2820 | +0.7644 | 0.9527 | 0.7583 | +0.1944 |

> **Interpretation:** The naive baseline is the only model whose test
> performance is *better* than its training performance (because the test
> period happened to be more stable than the training period). All three ML
> models show a train→test performance drop, with Gradient Boosting showing
> the largest gap.

---

## 10. Feature importance

### Permutation importance on the temporal TEST set (preferred per spec)

For the selected model (`RandomForest (no cargo)`):

| Rank | Feature | Permutation importance (%) |
|------|---------|------------------------------|
| 1 | `coal_price_usd_per_mt` | 84.73% |
| 2 | `origin` | 7.55% |
| 3 | `vessel_type` | 2.70% |
| 4 | `destination` | 2.26% |
| 5 | `bdi` | 2.15% |
| 6 | `commodity` | 0.39% |
| 7 | `vlsfo_usd_per_tonne` | 0.23% |
| 8 | `iron_ore_price_usd_per_dmt` | 0.00% |
| 9 | `wind_kmh` | 0.00% |
| 10 | `wave_height_m` | 0.00% |
| 11 | `cyclone_risk` | 0.00% |
| 12 | `weather_delay_days` | 0.00% |
| 13 | `current_freight_usd_per_tonne` | 0.00% |

### Built-in (impurity) feature importance (cross-reference)

| Rank | Feature | Built-in importance (%) |
|------|---------|-------------------------|
| 1 | `current_freight_usd_per_tonne` | 60.41% |
| 2 | `origin` | 9.18% |
| 3 | `commodity` | 8.12% |
| 4 | `coal_price_usd_per_mt` | 6.66% |
| 5 | `wind_kmh` | 2.87% |
| 6 | `vessel_type` | 2.69% |
| 7 | `wave_height_m` | 2.59% |
| 8 | `bdi` | 1.90% |
| 9 | `cyclone_risk` | 1.84% |
| 10 | `iron_ore_price_usd_per_dmt` | 1.73% |
| 11 | `vlsfo_usd_per_tonne` | 1.24% |
| 12 | `weather_delay_days` | 0.78% |
| 13 | `destination` | 0.00% |

### Discrepancy between the two importance measures

Permutation importance on the test set assigns 84.73% to
`coal_price_usd_per_mt` and **0%** to `current_freight_usd_per_tonne` — the
opposite of the v1 model. The built-in (impurity) importance still gives
`current_freight` 60.41%, but that is below the 90% dominance threshold.

**Why the discrepancy?** Impurity importance is biased toward high-cardinality
numeric features and reflects training-set splits, which is why v1 (which was
likely evaluated only on impurity importance) appeared to be 93.6% dominated
by `current_freight`. Permutation importance on the held-out test set is the
more reliable measure of *generalisation* contribution, and on that measure
`coal_price_usd_per_mt` is the dominant feature for v2.

### Does current freight dominate?

| Measure | `current_freight` importance | Dominant (>90%)? |
|---------|------------------------------|-------------------|
| Permutation (test) | 0.00% | ❌ No |
| Built-in (train) | 60.41% | ❌ No |

> **Conclusion:** Unlike v1 (which was ~93.6% dominated by `current_freight`
> on impurity importance), v2 is **NOT** dominated by `current_freight` on
> either measure. The model does not behave primarily as a persistence
> forecast — but note that `coal_price_usd_per_mt` now dominates permutation
> importance at 84.73%, so v2 has effectively shifted from one dominant
> feature to another.

---

## 11. Overfitting analysis

| Model | Train MAE | Test MAE | Gap (test−train) | Train R² | Test R² | R² drop |
|-------|-----------|----------|------------------|----------|---------|---------|
| RF (with cargo) | 0.5176 | 1.2878 | **+0.7702** | 0.9526 | 0.7564 | +0.1962 |
| GradientBoosting | 0.0772 | 1.5665 | **+1.4893** | 0.9990 | 0.6749 | +0.3242 |
| RF (no cargo) | 0.5177 | 1.2820 | **+0.7644** | 0.9527 | 0.7583 | +0.1944 |

### Findings

- **Gradient Boosting shows severe overfitting**: train R² = 0.999 vs test
  R² = 0.675 (R² drop of 0.32). Train MAE = 0.08 vs test MAE = 1.57 — the
  model essentially memorises the training data.
- **Both Random Forests show moderate overfitting**: train R² ≈ 0.95 vs
  test R² ≈ 0.76 (R² drop ≈ 0.19). Less severe than GB, but still a clear
  train→test performance gap.
- **The naive baseline does NOT overfit** — in fact its test metrics are
  *better* than its training metrics because the test window (Jul–Nov 2025)
  happened to be more stable than the training window.

> ⚠️ **We do not claim strong generalisation.** All ML candidates show a
> train→test performance drop, and on this small dataset (110 rows, 5
> combinations, 22 months) the drop is expected. The test MAE of the best
> ML model (1.282) is **worse** than the naive baseline (0.828).

---

## 12. Selected model

**Selected model:** `RandomForest (no cargo_tonnes)`

**Path:** `freight_forecast_model_v2.joblib`

### Selection criterion (per spec)

1. Primary: **lowest temporal test MAE** among ML candidates
2. Secondary: **lowest temporal test RMSE**
3. Then: reasonable R² and sensible feature importance

### Test-set ranking (ML candidates only)

| Rank | Model | Test MAE | Test RMSE | Test R² |
|------|-------|----------|-----------|---------|
| 1 | **RandomForest (no cargo)** | **1.2820** | **1.5379** | 0.7583 |
| 2 | RandomForest (with cargo) | 1.2878 | 1.5439 | 0.7564 |
| 3 | GradientBoosting | 1.5665 | 1.7837 | 0.6749 |

The selected `RandomForest (no cargo)` has the lowest test MAE (1.2820) and
lowest test RMSE (1.5379) of the three ML candidates.

### Does it beat the naive baseline?

| Model | Test MAE | Test RMSE | Test R² |
|-------|----------|-----------|---------|
| Naive (current_freight) | **0.8280** | **1.0750** | **0.8819** |
| Selected RF (no cargo) | 1.2820 | 1.5379 | 0.7583 |

> ❌ **NO.** The selected ML model does **not** beat the naive baseline.
> The naive "predict current freight" baseline has *lower* test MAE
> (0.828 vs 1.282), *lower* test RMSE (1.075 vs 1.538), and *higher* test
> R² (0.882 vs 0.758). This is an honest, important finding: on this small
> dataset, a simple persistence forecast outperforms every ML model we
> trained.

---

## 13. Why it was selected

The selected model was chosen because:

1. **Lowest test MAE** among the three ML candidates (1.2820 vs 1.2878 for
   RF-with-cargo and 1.5665 for GradientBoosting).
2. **Lowest test RMSE** among the three ML candidates (1.5379).
3. **Reasonable test R²** (0.7583 — the highest of the three ML candidates).
4. **`cargo_tonnes` is representative, not observed.** Removing it eliminated
   a non-informative feature without hurting performance (test MAE improved
   by 0.0058 and R² improved by 0.0019). The two RFs are essentially tied,
   but the no-cargo variant is preferable on principle.
5. **Less overfitting than GradientBoosting** (R² drop 0.19 vs 0.32).

### Honest caveats

- The selected ML model is the best **among ML candidates**, but it does
  **not** beat the naive baseline (§12). If the deployment goal is purely
  "lowest MAE on this temporal test set", the naive baseline is the better
  choice. The ML model is saved as `freight_forecast_model_v2.joblib` per
  the spec ("save ONLY the selected model"), with the explicit
  understanding that beating the naive baseline is **not** demonstrated.
- The 0.0058 MAE difference between RF-with-cargo and RF-no-cargo is within
  noise for a 25-row test set. The selection of "no cargo" is driven by the
  principle that `cargo_tonnes` is a representative (not observed) value,
  not by a meaningful performance difference.

---

## 14. Limitations

This is a **hackathon prototype**. The following limitations apply:

1. **Dataset has only 110 observations.** This is very small for a
   RandomForest with 300 trees. Overfitting is expected and observed.
2. **Only 5 route/commodity/vessel combinations.** The model has limited
   categorical diversity to learn from.
3. **Destination is region-level** (`East Coast India`), not port-level
   (`Paradip`/`Visakhapatnam`). The model cannot distinguish port-level
   destination effects.
4. **`cargo_tonnes` is representative** (vessel-class capacity), not an
   observed fixture quantity. Constant within each vessel class — the
   model cannot learn intra-class cargo effects. (This is why the
   no-cargo variant was selected.)
5. **Data covers only 22 months** (Feb 2024 – Nov 2025). Multi-year market
   cycles cannot be learned.
6. **Test set is only 25 rows** (5 months × 5 combinations). Metric
   estimates have high variance.
7. **Naive baseline outperforms the ML model** on the temporal test set.
   This suggests the signal-to-noise ratio in the data is low enough that
   "predict current freight" is hard to beat with 110 rows.
8. **No hyperparameter tuning was performed.** Parameters were chosen
   conservatively per the spec; tuning might improve results but risks
   overfitting to the small test set.
9. **No cross-validation** beyond the single chronological holdout. With
   only 22 months per combination, k-fold CV would leak temporal
   information.

---

## 15. Model parameters

### Selected model: `RandomForestRegressor` (no `cargo_tonnes`)

```python
RandomForestRegressor(
    n_estimators=300,
    max_depth=8,
    min_samples_leaf=2,
    random_state=42,
    n_jobs=-1,
)
```

### Preprocessing (inside the same Pipeline)

```python
ColumnTransformer(
    transformers=[
        ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False),
         ["origin", "destination", "commodity", "vessel_type"]),
        ("num", "passthrough",
         ["bdi", "vlsfo_usd_per_tonne", "coal_price_usd_per_mt",
          "iron_ore_price_usd_per_dmt", "wind_kmh", "wave_height_m",
          "cyclone_risk", "weather_delay_days",
          "current_freight_usd_per_tonne"]),
    ],
    remainder="drop",
)
```

### Feature set (13 inputs — `cargo_tonnes` excluded)

```
origin, destination, commodity, vessel_type,
bdi, vlsfo_usd_per_tonne, coal_price_usd_per_mt,
iron_ore_price_usd_per_dmt, wind_kmh, wave_height_m,
cyclone_risk, weather_delay_days, current_freight_usd_per_tonne
```

### Other candidates' parameters

- **Gradient Boosting:** `GradientBoostingRegressor(n_estimators=200, max_depth=3, learning_rate=0.05, min_samples_leaf=3, random_state=42)` with the same preprocessing.
- **RF with cargo:** identical to the selected model but with `cargo_tonnes` added back to the numeric features.

### Split configuration

- Split date: `2025-07-01`
- Training: `2024-02-01` → `2025-06-01` (85 rows)
- Test: `2025-07-01` → `2025-11-01` (25 rows)
- Random seed: `42`

---

## 16. Exact reproduction commands

```bash
# 1. Ensure the expanded master dataset exists
ls data/master_freight_training_expanded_v1.csv
# (If missing, rebuild it from the uploads:
#  python build_master_dataset_expanded.py)

# 2. Train the v2 model (this script is fully deterministic with random_state=42)
python train_v2.py

# 3. Verify the v2 model was created and v1 was untouched
ls -lh freight_forecast_model_v2.joblib
sha256sum freight_forecast_model_v1.joblib
# Expected v1 sha256: 695fafe3f31b560d5a4412124c0839e0e622c9d2bd090191a5e02eaef6c3819a

# 4. Load and inspect the v2 pipeline
python -c "import joblib; m=joblib.load('freight_forecast_model_v2.joblib'); print(type(m).__name__); print(m.named_steps)"

# 5. Re-run the 5-combination smoke test (already done in train_v2.py STEP 10)
python -c "
import joblib, pandas as pd
df = pd.read_csv('data/master_freight_training_expanded_v1.csv')
m = joblib.load('freight_forecast_model_v2.joblib')
feats = ['origin','destination','commodity','vessel_type','bdi','vlsfo_usd_per_tonne','coal_price_usd_per_mt','iron_ore_price_usd_per_dmt','wind_kmh','wave_height_m','cyclone_risk','weather_delay_days','current_freight_usd_per_tonne']
combos = [
  ('Australia West Coast','East Coast India','Iron Ore','Capesize'),
  ('Hay Point','East Coast India','Coal','Capesize'),
  ('Hay Point','East Coast India','Coal','Panamax'),
  ('Taboneo','East Coast India','Thermal Coal','Panamax'),
  ('Taboneo','East Coast India','Thermal Coal','Supramax'),
]
for o,d,c,v in combos:
    row = df[(df.origin==o)&(df.destination==d)&(df.commodity==c)&(df.vessel_type==v)].iloc[0:1]
    p = float(m.predict(row[feats])[0])
    print(f'{o:22} {c:13} {v:9}: {p:.4f}')
"
```

---

## 17. Output files

| Path | Purpose |
|------|---------|
| `freight_forecast_model_v2.joblib` | **Trained v2 model** (Pipeline: preprocessing + RandomForestRegressor, no cargo) |
| `data/model_predictions_v2.csv` | Test-set predictions (25 rows) with absolute errors |
| `data/model_training_metrics_v2.json` | Machine-readable metrics (all models, importance, overfitting) |
| `data/MODEL_COMPARISON_V2.md` | This report |
| `train_v2.py` | Reproducible training script |

### `freight_forecast_model_v1.joblib` status

- **Not modified.** sha256 before and after training is identical:
  `695fafe3f31b560d5a4412124c0839e0e622c9d2bd090191a5e02eaef6c3819a`
- **Not overwritten.** The v2 model was saved to a separate filename
  (`freight_forecast_model_v2.joblib`).

### FastAPI backend status

- **Not modified.** `backend/main.py`, `backend/predict.py`,
  `backend/schemas.py`, and `backend/services/forecast_service.py` are all
  untouched on this branch. The backend still loads and serves
  `freight_forecast_model_v1.joblib`. Connecting v2 to the API is a
  follow-up task per the spec ("STEP 13 — DO NOT MODIFY THE APPLICATION").

---

## 18. Explicit summary (per spec)

- ✅ Dataset has only **110 observations**
- ✅ Only **5 route/commodity/vessel combinations**
- ✅ Destination is **region-level** (`East Coast India`)
- ✅ `cargo_tonnes` is **representative** (vessel-class capacity, not observed)
- ✅ Data covers only **22 months**
- ✅ **This is a hackathon prototype**

---

## 19. STOP

Model training V2 complete. The v2 model is saved as
`freight_forecast_model_v2.joblib`. The v1 model and the FastAPI backend
are untouched.

Awaiting your review of the model results before connecting v2 to the API.

*End of report.*
