# DATASET INTEGRATION REPORT

> **Status:** Inspection and integration planning only.
> **No datasets merged into a master file. No missing values invented. No
> synthetic data generated. The existing `freight_forecast_model_v1.joblib`
> was not modified. No retraining was performed.**
>
> **Date of report:** 2026-08-28
> **Auditor:** Z.ai Code (automated)
> **Repository:** https://github.com/junaid693/Freight---bulk-Cargo
> **Branch:** `audit/dataset-integration`

---

## Table of Contents

1. [Dataset Inventory](#1-dataset-inventory)
2. [Primary Original Training Dataset](#2-primary-original-training-dataset)
3. [Dataset Relationships & Overlap](#3-dataset-relationships--overlap)
4. [Column Mapping to Model Schema](#4-column-mapping-to-model-schema)
5. [Unit Conversions](#5-unit-conversions)
6. [Missing-Value Analysis](#6-missing-value-analysis)
7. [Leakage Analysis](#7-leakage-analysis)
8. [Route / Commodity / Vessel Coverage](#8-route--commodity--vessel-coverage)
9. [Proposed Master Dataset Schema](#9-proposed-master-dataset-schema)
10. [Files for Training vs Validation-Only](#10-files-for-training-vs-validation-only)
11. [Recommendation for the Next Step](#11-recommendation-for-the-next-step)
12. [Appendix: Per-Dataset Detailed Profiles](#12-appendix-per-dataset-detailed-profiles)

---

## 1. Dataset Inventory

Five files were uploaded to `/home/z/my-project/upload/`. A sixth file
(`real_route_validation_predictions_v1.csv`) was announced but **not present
at audit time** — see §10.

| # | File | Rows | Cols | Date range | Frequency | Status |
|---|------|------|------|------------|-----------|--------|
| 1 | `freight_forecasting_training_table_v1.csv` | 110 | 23 | 2024-02 → 2025-11 | monthly | **PRIMARY ORIGINAL TRAINING** |
| 2 | `expanded_monthly_freight_training_v1.csv` | 3 | 14 | 2025-05 → 2025-09 | monthly | supplementary (separate routes) |
| 3 | `expanded_freight_benchmark_2024_2025.csv` | 120 | 10 | 2024-01 → 2025-12 | monthly | benchmark / supplementary |
| 4 | `world_bank_coal_iron_ore_monthly.csv` | 799 | 3 | 1960-01 → 2026-07 | monthly | supporting reference |
| 5 | `weather_monthly_all_locations_2024_2025.csv` | 96 | 6 | 2024-01 → 2025-12 | monthly | supporting reference |
| 6 | `real_route_validation_predictions_v1.csv` | — | — | — | — | **NOT UPLOADED YET** |

### Quick file facts

- **No file is empty.** All five have header rows and data rows.
- **No file has full-row duplicates** (verified with `pandas.DataFrame.duplicated()`).
- **No file has BOM / encoding issues** — all are plain ASCII CSV.
- The smallest file (`expanded_monthly_freight_training_v1.csv`) has only **3 rows**; treat with caution for statistical use.

---

## 2. Primary Original Training Dataset

### ✅ `freight_forecasting_training_table_v1.csv` (FFT)

This is the **primary original training dataset**. Evidence:

1. **It is the only file that contains the target column**
   `next_month_freight_usd_per_tonne` together with all 14 model input
   features (in transformed form — see §4).
2. Its columns include every market, weather, freight, and derived feature
   the model was trained on.
3. The row count (110) and the monthly cadence match the structure of a
   "this month's rate → next month's rate" forecasting problem.
4. The training distribution extracted from the model's one-hot categories
   (origins `Hay Point`/`Taboneo`, destinations `Paradip`/`Visakhapatnam` —
   see the prior audit) corresponds to the **port-level** portmanteau of the
   broader region routes in this file. (See §8 for the route-naming
   reconciliation.)

> **Conclusion:** FFT is the original training dataset. All other files are
> either expansions, benchmarks, or supporting references.

---

## 3. Dataset Relationships & Overlap

### 3.1 `expanded_monthly_freight_training_v1.csv` vs FFT

- **Not** a transformation of FFT — it has a different (smaller) column set
  (no weather, no coal/iron-ore prices, no cyclone/delay).
- **Routes are completely disjoint from FFT:**
  - FFT routes: `Australia East Coast → East Coast India`,
    `Australia West Coast → East Coast India`, `Taboneo → East Coast India`
  - Expanded routes: `Hay Point → Visakhapatnam`, `Hay Point → Paradip`
- **No duplicate `(date, route, commodity, vessel_type)` keys** between the
  two files (0 overlapping keys).
- Expanded commodity is `Metallurgical Coal` (FFT has `Coal`, `Thermal Coal`,
  `Iron Ore`) — **new categorical value** not in the model's training
  distribution.
- Expanded vessel type is `Panamax` (already in FFT).

> **Conclusion:** `expanded_monthly_freight_training_v1.csv` is a **separate,
> small, supplementary** dataset (3 rows) covering routes that are *not* in
> FFT. It is **not** a row-level expansion of FFT. It can only be incorporated
> after weather, market, and `cargo_tonnes` are joined from external sources —
> and only if you accept `Metallurgical Coal` as a new commodity category.

### 3.2 `expanded_freight_benchmark_2024_2025.csv` vs FFT

- Same 5-key grain: `(date, origin, destination, commodity, vessel_type)`.
- FFT's `route` string parses cleanly into the benchmark's
  `origin`/`destination` columns.
- **110 of 120 benchmark rows exactly match FFT rows** on the 5-key
  `(date, origin, destination, commodity, vessel_type)` and the
  `freight_rate_usd_per_tonne` value agrees to 4 decimal places (diff = 0.0
  on every matched row).
- The benchmark's `vlsfo_bunker_usd_per_tonne` and `baltic_dry_index` also
  agree exactly with FFT on all 22 shared dates (diff = 0.0).
- **10 benchmark rows are NOT in FFT** — they are the boundary months
  (2024-01-01 and 2025-12-01) for 5 route/commodity/vessel combinations
  where FFT has no `next_month_freight` target:
  - Taboneo → East Coast India, Thermal Coal, Supramax (2024-01, 2025-12)
  - Taboneo → East Coast India, Thermal Coal, Panamax (2024-01, 2025-12)
  - Australia East Coast → East Coast India, Coal, Capesize (2024-01, 2025-12)
  - Australia East Coast → East Coast India, Coal, Panamax (2024-01, 2025-12)
  - Australia West Coast → East Coast India, Iron Ore, Capesize (2024-01, 2025-12)

> **Conclusion:** The benchmark file is **a superset of FFT's freight +
> bunker + BDI columns** with 10 extra boundary rows. The 110 overlapping
> rows are duplicates (same values). Only the 10 boundary rows are new —
> but they **cannot be used for training as-is** because they lack a
> `next_month_freight_usd_per_tonne` target.

### 3.3 `world_bank_coal_iron_ore_monthly.csv` vs FFT

- FFT columns `coal_australian_usd_per_mt` and `iron_ore_cfr_usd_per_dmt`
  **match the World Bank file exactly** (diff = 0.0) on all 22 overlapping
  months (2024-02 → 2025-11).
- World Bank file extends back to 1960 and forward to 2026-07 — far beyond
  FFT's range.

> **Conclusion:** World Bank is the **authoritative source** for the
> `coal_price_usd_per_mt` and `iron_ore_price_usd_per_dmt` model features.
> FFT's values are simply the World Bank values joined on month. World Bank
> can be used to extend the price series backward/forward, but only months
> that also have a freight target are useful for training.

### 3.4 `weather_monthly_all_locations_2024_2025.csv` vs FFT

- Weather file locations: `Hay Point`, `Taboneo`, `Visakhapatnam`, `Paradip`
  (4 ports, 24 months each = 96 rows).
- FFT weather columns are named by *region* (Taboneo, Aus East, Aus West)
  and include wind (in knots) and wave height (in metres).
- The weather file has wind in **km/h** (`avg_wind_speed_kmh`) and **no
  wave height column** at all (only temperature, wind, gust, precipitation).
- A direct numeric check on shared (Taboneo, 2024-02..2025-11) months shows
  the ratio `weather_avg_wind_kmh / FFT_taboneo_wind_kts` averages **0.62**,
  not the expected 1.852 (km/h per knot). The two are **different
  aggregations** of different underlying data — they are NOT the same series
  rescaled.

> **Conclusion:** The weather file is a **supporting reference**, not a
> 1:1 match for FFT's weather columns. It cannot be used as a drop-in
> replacement. It may be useful as supplementary weather context (e.g.
> temperature, precipitation) for future feature engineering — **not for
> the current model's weather features**.

### 3.5 `expanded_monthly_freight_training_v1.csv` vs benchmark

- Expanded routes (`Hay Point → Paradip/Vizag`) use **port-level** naming.
- Benchmark routes (`origin` column) use **region-level** naming
  (`Australia East Coast`, `Taboneo`, `Australia West Coast`).
- No row-level overlap (different origin granularity).

---

## 4. Column Mapping to Model Schema

The model expects these 14 input features + 1 target:

```
origin, destination, commodity, vessel_type, cargo_tonnes,
bdi, vlsfo_usd_per_tonne, coal_price_usd_per_mt, iron_ore_price_usd_per_dmt,
wind_kmh, wave_height_m, cyclone_risk, weather_delay_days,
current_freight_usd_per_tonne   [TARGET: next_month_freight_usd_per_tonne]
```

### FFT column → model feature mapping

| # | Model feature | FFT source column | Transformation | Notes |
|---|---------------|-------------------|-----------------|-------|
| 1 | `origin` | `route` (left of ` -> `) | **parse** | e.g. `Australia East Coast -> East Coast India` → `Australia East Coast` |
| 2 | `destination` | `route` (right of ` -> `) | **parse** | same split |
| 3 | `commodity` | `commodity` | direct | values: `Coal`, `Iron Ore`, `Thermal Coal` |
| 4 | `vessel_type` | `vessel_type` | direct | values: `Capesize`, `Panamax`, `Supramax` |
| 5 | `cargo_tonnes` | — | **❌ unavailable** | FFT has no cargo size column |
| 6 | `bdi` | `baltic_dry_index` | rename | unit: index points |
| 7 | `vlsfo_usd_per_tonne` | `vlsfo_bunker_usd_per_tonne` | rename | unit: USD/tonne |
| 8 | `coal_price_usd_per_mt` | `coal_australian_usd_per_mt` | rename | = World Bank `coal_australian_usd_per_mt` |
| 9 | `iron_ore_price_usd_per_dmt` | `iron_ore_cfr_usd_per_dmt` | rename | = World Bank `iron_ore_cfr_usd_per_dmt` |
| 10 | `wind_kmh` | `taboneo_wind_kts` / `aus_east_wind_kts` / `aus_west_wind_kts` | **choose + convert** | knots → km/h (×1.852). Route-dependent choice — see §5 |
| 11 | `wave_height_m` | `taboneo_wave_hs_m` / `aus_east_wave_hs_m` / `aus_west_wave_hs_m` | **choose** | already in metres; choose per route |
| 12 | `cyclone_risk` | `bob_cyclone_alert_index` | rename | range 1–5 (matches model's 0–5 domain) |
| 13 | `weather_delay_days` | `estimated_weather_delay_days` | rename | range 0–4 |
| 14 | `current_freight_usd_per_tonne` | `freight_rate_usd_per_tonne` | rename | unit: USD/tonne |
| — | `next_month_freight_usd_per_tonne` (target) | `next_month_freight_usd_per_tonne` | direct | already present |

> FFT also contains **auxiliary columns not used by the model**:
> `previous_month_freight`, `freight_3_month_avg`, `year`, `month_number`,
> `quarter_number`. These are useful for time-aware modelling but are **not**
> inputs to the current model. The lag features
> (`previous_month_freight`, `freight_3_month_avg`) are derived from the
> target column and **must not be used as inputs** without explicit leakage
> handling (see §7).

### Other datasets' column contributions

| File | Contributes to model feature? | How |
|------|------------------------------|-----|
| `expanded_monthly_freight_training_v1.csv` | partial | provides `freight_rate`, `vlsfo`, `bdi`, `previous_month_freight`, `freight_3_month_avg`, target — but **no weather, no coal/iron-ore, no cargo_tonnes** |
| `expanded_freight_benchmark_2024_2025.csv` | partial | duplicates FFT's freight/vlsfo/bdi for 110 rows; adds 10 boundary rows (no target) |
| `world_bank_coal_iron_ore_monthly.csv` | yes | authoritative source for `coal_price_usd_per_mt` + `iron_ore_price_usd_per_dmt` |
| `weather_monthly_all_locations_2024_2025.csv` | **no** | different aggregation, no wave height, no cyclone, no delay — supporting only |

---

## 5. Unit Conversions

Only **one** conversion is required, and it is dimensionally exact:

| From | To | Factor | Verified? |
|------|----|--------|-----------|
| FFT `*_wind_kts` (knots) | model `wind_kmh` | **× 1.852** | Yes — standard unit conversion. (Cannot be cross-verified against the weather file because that file uses a different aggregation; see §3.4.) |

All other model features are already in the correct unit:

- `bdi` — index points (no unit)
- `vlsfo_usd_per_tonne` — USD/tonne ✅
- `coal_price_usd_per_mt` — USD/MT ✅ (World Bank uses the same unit)
- `iron_ore_price_usd_per_dmt` — USD/dmt ✅ (World Bank uses the same unit)
- `wave_height_m` — metres ✅ (FFT `_hs_m` = significant wave height in metres)
- `cyclone_risk` — 0–5 score ✅
- `weather_delay_days` — days ✅
- `current_freight_usd_per_tonne` — USD/tonne ✅

### Route-dependent weather column choice (transformation, not unit)

FFT stores weather for **three regions** per row:

```
taboneo_wind_kts, taboneo_wave_hs_m         # Taboneo (Indonesia)
aus_east_wind_kts, aus_east_wave_hs_m       # Australia East Coast
aus_west_wind_kts, aus_west_wave_hs_m       # Australia West Coast
```

The model's `wind_kmh` and `wave_height_m` are **single** values. To produce
them, the wind/wave columns must be chosen **per route** based on origin:

| Route (origin) | Use FFT columns |
|----------------|-----------------|
| `Taboneo` | `taboneo_wind_kts`, `taboneo_wave_hs_m` |
| `Australia East Coast` | `aus_east_wind_kts`, `aus_east_wave_hs_m` |
| `Australia West Coast` | `aus_west_wind_kts`, `aus_west_wave_hs_m` |

> This is a **selection** (not a fabrication): every row already contains
> the relevant value; we simply pick the right region. For routes whose
> origin is none of these three (e.g. `Hay Point`, which is in the expanded
> file), FFT has no matching weather column — see §6.

---

## 6. Missing-Value Analysis

### Per-file null counts

| File | Columns with nulls | Null count |
|------|--------------------|-----------|
| `freight_forecasting_training_table_v1.csv` | (none) | 0 |
| `expanded_monthly_freight_training_v1.csv` | (none) | 0 |
| `expanded_freight_benchmark_2024_2025.csv` | (none) | 0 |
| `weather_monthly_all_locations_2024_2025.csv` | (none) | 0 |
| `world_bank_coal_iron_ore_monthly.csv` | `coal_australian_usd_per_mt` | **120 nulls** (all in pre-1990 rows; the column starts being populated around 1990) |

### Missing-from-schema analysis (features absent from each file)

| Model feature | FFT | Expanded | Benchmark | World Bank | Weather |
|---------------|-----|----------|-----------|-----------|---------|
| `origin` | ✅ (in route) | ✅ (in route) | ✅ | ❌ | ❌ (location, not route) |
| `destination` | ✅ (in route) | ✅ (in route) | ✅ | ❌ | ❌ |
| `commodity` | ✅ | ✅ | ✅ | ❌ | ❌ |
| `vessel_type` | ✅ | ✅ | ✅ | ❌ | ❌ |
| `cargo_tonnes` | **❌ MISSING** | **❌ MISSING** | **❌ MISSING** | ❌ | ❌ |
| `bdi` | ✅ | ✅ | ✅ | ❌ | ❌ |
| `vlsfo_usd_per_tonne` | ✅ | ✅ | ✅ | ❌ | ❌ |
| `coal_price_usd_per_mt` | ✅ | ❌ | ❌ | ✅ | ❌ |
| `iron_ore_price_usd_per_dmt` | ✅ | ❌ | ❌ | ✅ | ❌ |
| `wind_kmh` | ✅ (knots, route-specific) | ❌ | ❌ | ❌ | ✅ (different aggregation, no match) |
| `wave_height_m` | ✅ (route-specific) | ❌ | ❌ | ❌ | **❌ NOT IN FILE** |
| `cyclone_risk` | ✅ (`bob_cyclone_alert_index`) | ❌ | ❌ | ❌ | ❌ |
| `weather_delay_days` | ✅ (`estimated_weather_delay_days`) | ❌ | ❌ | ❌ | ❌ |
| `current_freight_usd_per_tonne` | ✅ | ✅ | ✅ | ❌ | ❌ |
| target `next_month_freight_usd_per_tonne` | ✅ | ✅ | **❌ MISSING** | ❌ | ❌ |

> **`cargo_tonnes` is missing from every uploaded file.** This is a hard
> gap. The current model expects it as an input (it appears in
> `feature_names_in_`), so the original training data must have had it —
> it was likely dropped when the FFT was exported. **This must be recovered
> or supplied before retraining.**

### `wave_height_m` in the weather file

The weather file has **no wave-height column at all**. It cannot be used to
source `wave_height_m` for any route not already in FFT.

---

## 7. Leakage Analysis

### 7.1 Target definition verified (legitimate)

For every FFT row that has a successor in the same route/commodity/vessel
group (105 of 110 rows), I verified:

```
next_month_freight_usd_per_tonne[t] == freight_rate_usd_per_tonne[t+1]   (same route)
```

**Result: 105/105 exact matches.**

This confirms `next_month_freight_usd_per_tonne` is the **true one-month-forward
target** — it is the freight rate observed one month later for the same
route. Using it as the target is **correct** and is not leakage *per se*.

### 7.2 Lag features — potential leakage if misused

FFT contains two derived lag columns:

- `previous_month_freight` — verified to equal `freight_rate[t-1]` for 105/105
  rows (legitimate lag, **must not be used as an input** unless you also
  have it at inference time; the current model does **not** use it).
- `freight_3_month_avg` — a rolling 3-month average of freight rate. Also
  target-derived; same caveat.

> ⚠️ **Leakage risk:** if the master dataset is built and these lag columns
> are accidentally fed to a retrained model, the model will achieve
> artificially high training scores by reading near-duplicates of the target.
> They must be **excluded** from the input feature set unless you
> deliberately design the model to consume lag features (and provide them
> at inference).

### 7.3 Forward-looking columns

Across all 5 files, the only column whose name suggests a future value is
`next_month_freight_usd_per_tonne` (the legitimate target). **No
`future_*`, `prediction_*`, or `forecast_*` input columns exist** in any
file. Good.

### 7.4 Validation file leakage

`real_route_validation_predictions_v1.csv` was **not uploaded** at audit
time. When it arrives, it must be:

- Stored in a separate directory (e.g. `data/validation/`).
- **Never joined** to the training datasets.
- Its `prediction` / `future` / `next-month` columns must **never** appear
  in any training row.
- Used only for evaluation/metrics.

### 7.5 Benchmark-to-FFT duplicate leakage

Because 110 of 120 benchmark rows are exact duplicates of FFT rows, **using
both files in training would double-count those 110 observations**. The
benchmark file should be deduplicated against FFT before any join (see §10).

---

## 8. Route / Commodity / Vessel Coverage

### 8.1 Route coverage (FFT)

| Route | Origin | Destination | Rows | Date range |
|-------|--------|-------------|------|------------|
| `Australia East Coast -> East Coast India` | Australia East Coast | East Coast India | 44 | 2024-02 → 2025-11 |
| `Taboneo -> East Coast India` | Taboneo | Taboneo | East Coast India | 44 | 2024-02 → 2025-11 |
| `Australia West Coast -> East Coast India` | Australia West Coast | East Coast India | 22 | 2024-02 → 2025-11 |

All FFT routes use `East Coast India` as destination. **`origin` is a region,
not a single port** — note that the model's trained one-hot categories are
`Hay Point` and `Taboneo` (port-level). There is a **granularity mismatch**
between FFT's region-level origins and the model's port-level origins.
This must be resolved before retraining (see §11).

### 8.2 Commodity coverage

| File | Commodities |
|------|-------------|
| FFT | `Coal`, `Iron Ore`, `Thermal Coal` (3) |
| Expanded | `Metallurgical Coal` (1, **new**) |
| Benchmark | `Coal`, `Iron Ore`, `Thermal Coal` (3, same as FFT) |
| Model training categories | `Coal`, `Iron Ore` (2) |

`Thermal Coal` and `Metallurgical Coal` are present in the uploaded data
but **not** in the model's trained one-hot categories. They will be
silently zero-encoded by `handle_unknown='ignore'`.

### 8.3 Vessel type coverage

| File | Vessel types |
|------|--------------|
| FFT, Benchmark | `Capesize`, `Panamax`, `Supramax` |
| Expanded | `Panamax` |
| Model training categories | `Panamax`, `Supramax` |

`Capesize` is in the data but **not** in the model's trained one-hot
categories — it will be zero-encoded.

### 8.4 Geographic coverage of supporting files

- **World Bank**: global coal/iron-ore benchmarks (no geography — applies to
  all routes by date).
- **Weather file**: 4 ports (`Hay Point`, `Taboneo`, `Visakhapatnam`,
  `Paradip`) × 24 months. Matches the model's trained port categories,
  but does **not** match FFT's region-level origins
  (`Australia East Coast`, `Australia West Coast`).

---

## 9. Proposed Master Dataset Schema

One row = one monthly observation of a freight forecast scenario:

```
(date, origin, destination, commodity, vessel_type) → features + target
```

### Columns (proposed — NOT yet materialized)

| Column | Type | Source | Notes |
|--------|------|--------|-------|
| `date` | DATE (monthly, day=1) | FFT.`date` | calendar month of observation |
| `origin` | TEXT | parsed from `route` | choose granularity (region or port) — see §11 |
| `destination` | TEXT | parsed from `route` | same granularity as origin |
| `commodity` | TEXT | FFT.`commodity` | |
| `vessel_type` | TEXT | FFT.`vessel_type` | |
| `cargo_tonnes` | REAL | **❌ NOT AVAILABLE** | must be recovered externally |
| `bdi` | REAL | FFT.`baltic_dry_index` | = benchmark.`baltic_dry_index` |
| `vlsfo_usd_per_tonne` | REAL | FFT.`vlsfo_bunker_usd_per_tonne` | = benchmark.`vlsfo_bunker_usd_per_tonne` |
| `coal_price_usd_per_mt` | REAL | FFT.`coal_australian_usd_per_mt` | = World Bank `coal_australian_usd_per_mt` |
| `iron_ore_price_usd_per_dmt` | REAL | FFT.`iron_ore_cfr_usd_per_dmt` | = World Bank `iron_ore_cfr_usd_per_dmt` |
| `wind_kmh` | REAL | FFT route-specific wind column × 1.852 | route-dependent selection |
| `wave_height_m` | REAL | FFT route-specific wave column | route-dependent selection |
| `cyclone_risk` | REAL | FFT.`bob_cyclone_alert_index` | range 1–5 |
| `weather_delay_days` | REAL | FFT.`estimated_weather_delay_days` | range 0–4 |
| `current_freight_usd_per_tonne` | REAL | FFT.`freight_rate_usd_per_tonne` | = benchmark freight_rate (duplicates must be deduped) |
| `next_month_freight_usd_per_tonne` (TARGET) | REAL | FFT.`next_month_freight_usd_per_tonne` | forward 1-month freight |
| `data_source` | TEXT | audit metadata | which file the row came from |
| `ingested_at` | TIMESTAMP | audit metadata | when added |

### Primary key

```
PRIMARY KEY (date, origin, destination, commodity, vessel_type)
```

### Estimated row count if built today

- FFT provides **110 complete rows** (all features + target, except
  `cargo_tonnes`).
- Expanded provides 0 complete rows (missing weather, coal/iron-ore, cargo).
- Benchmark provides 0 complete rows (no target, no weather).

> **Effective master dataset size with current uploads: 110 rows**
> (FFT only). `cargo_tonnes` is still missing and would have to be
> recovered before retraining.

---

## 10. Files for Training vs Validation-Only

### ✅ Files that can be used for TRAINING (after the master join)

| File | Role | Used for |
|------|------|---------|
| `freight_forecasting_training_table_v1.csv` | **PRIMARY training data** | all 14 features + target (except `cargo_tonnes`) |
| `world_bank_coal_iron_ore_monthly.csv` | **reference source** for coal/iron-ore prices | authoritative source — can extend price series beyond FFT range when freight+target rows exist |
| `expanded_freight_benchmark_2024_2025.csv` | **deduplicated against FFT**; only the 10 non-overlapping boundary rows are candidates — but they **lack a target**, so they cannot be used for training as-is | optional supplementary source |
| `expanded_monthly_freight_training_v1.csv` | **separate routes** — usable only if weather/market/cargo are joined from elsewhere; introduces a new commodity (`Metallurgical Coal`) | supplementary, low value (3 rows) |
| `weather_monthly_all_locations_2024_2025.csv` | **supporting reference only** — does not match FFT weather aggregation, has no wave height | not for direct use as model weather inputs |

### 🚫 Files that must be VALIDATION-ONLY

| File | Reason |
|------|--------|
| `real_route_validation_predictions_v1.csv` | **not yet uploaded**; when provided, must be kept in a separate directory and its prediction/target columns must never enter training |

### 🚫 Files that must NOT be used at all

None of the uploaded files are forbidden outright, but the following must
be **excluded from the input feature set**:

- `previous_month_freight` (FFT, Expanded) — derived from target → leakage
- `freight_3_month_avg` (FFT, Expanded) — derived from target → leakage
- `freight_observation_count` (Expanded) — metadata, not a model input

---

## 11. Recommendation for the Next Step

The pipeline is **not yet ready to retrain**. Three blockers must be
resolved first, in this order:

### Blocker 1 — Recover `cargo_tonnes`

This feature is in the model's `feature_names_in_` but is **absent from
every uploaded file**. Options:
- (a) Recover it from the original source workbook (`Dry_Bulk_Freight_Benchmarks_India.xlsx`,
  referenced in the benchmark's `source` column) if available.
- (b) Drop `cargo_tonnes` from the retrained model's feature set (requires
  a new model — out of scope of "do not retrain yet").
- (c) Use a documented representative value per route/vessel_type — **only
  with explicit user approval**, since this would be a (transparent)
  assumption, not recovered ground truth.

### Blocker 2 — Resolve the route granularity mismatch

FFT uses **region-level** origins (`Australia East Coast`,
`Australia West Coast`); the model was trained on **port-level** origins
(`Hay Point`, `Taboneo`). Before any join:
- Decide whether to map regions → representative ports (e.g.
  `Australia East Coast → Hay Point`), or
- Retrain with region-level categories (requires new model).

This decision must be made explicitly. **No automatic mapping is performed
in this report.**

### Blocker 3 — Confirm the treatment of the 10 benchmark boundary rows

The 10 benchmark rows for 2024-01 and 2025-12 have freight/vlsfo/bdi but
**no target**. Decide:
- (a) Use 2024-01 rows where the 2024-02 target exists (target shift), or
- (b) Drop the boundary rows.

### Recommended next action (after the 3 blockers are resolved)

1. Build the master dataset by joining FFT (110 rows) on
   `(date, route→origin/destination, commodity, vessel_type)` with itself
   to select route-specific wind/wave columns.
2. Convert `*_wind_kts → wind_kmh` (×1.852) and rename all FFT columns to
   the model's feature names (§4).
3. Tag every row with `data_source='FFT'` and `ingested_at=<now>`.
4. Do **not** merge the 110 duplicate benchmark rows.
5. Do **not** merge the 3 expanded rows until their missing features are
   sourced — or exclude them from the first retraining pass.
6. Place `real_route_validation_predictions_v1.csv` (when uploaded) in
   `data/validation/` and exclude it from training.

> **STOP.** This report does not perform any of the above. It only
> documents what was found and proposes the next step. No model file was
> modified. No retraining was performed.

---

## 12. Appendix: Per-Dataset Detailed Profiles

### A. `freight_forecasting_training_table_v1.csv` (FFT)

- **Shape:** 110 rows × 23 cols
- **Date range:** 2024-02-01 → 2025-11-01 (monthly)
- **Frequency:** monthly
- **Full-row duplicates:** 0
- **Duplicate `(date, route, commodity, vessel_type)` keys:** 0
- **Missing values:** none
- **Routes (3):**
  - `Australia East Coast -> East Coast India` (44 rows)
  - `Taboneo -> East Coast India` (44 rows)
  - `Australia West Coast -> East Coast India` (22 rows)
- **Commodities (3):** `Coal`, `Iron Ore`, `Thermal Coal`
- **Vessel types (3):** `Capesize`, `Panamax`, `Supramax`
- **Target column:** `next_month_freight_usd_per_tonne` ✅ present
- **Auxiliary (lag/derived) columns:** `previous_month_freight`,
  `freight_3_month_avg`, `year`, `month_number`, `quarter_number`
- **Notable:** contains the target and 13 of 14 model features (missing
  only `cargo_tonnes`). **This is the primary training dataset.**

### B. `expanded_monthly_freight_training_v1.csv`

- **Shape:** 3 rows × 14 cols
- **Date range:** 2025-05-01 → 2025-09-01 (monthly)
- **Frequency:** monthly
- **Duplicates:** 0
- **Missing values:** none
- **Routes (2):** `Hay Point -> Visakhapatnam`, `Hay Point -> Paradip`
- **Commodity (1):** `Metallurgical Coal` (**new**)
- **Vessel type (1):** `Panamax`
- **Has target:** ✅ `next_month_freight_usd_per_tonne`
- **Missing model features:** `coal_price_usd_per_mt`,
  `iron_ore_price_usd_per_dmt`, `wind_kmh`, `wave_height_m`,
  `cyclone_risk`, `weather_delay_days`, `cargo_tonnes`
- **Notable:** separate routes from FFT, but **incomplete** — most model
  features are absent. Only 3 rows. Treat as supplementary.

### C. `expanded_freight_benchmark_2024_2025.csv`

- **Shape:** 120 rows × 10 cols
- **Date range:** 2024-01-01 → 2025-12-01 (monthly)
- **Frequency:** monthly
- **Duplicates:** 0 within the file
- **Missing values:** none
- **Origins (3):** `Australia East Coast`, `Australia West Coast`, `Taboneo`
- **Destination (1):** `East Coast India`
- **Commodities (3):** `Coal`, `Iron Ore`, `Thermal Coal`
- **Vessel types (3):** `Capesize`, `Panamax`, `Supramax`
- **Has target:** ❌ no `next_month_freight` column
- **Notable:** 110 of 120 rows are exact duplicates of FFT rows on
  `(date, origin, destination, commodity, vessel_type)` with matching
  freight/vlsfo/bdi values. The remaining 10 rows are boundary months
  (2024-01, 2025-12) with no target.

### D. `world_bank_coal_iron_ore_monthly.csv`

- **Shape:** 799 rows × 3 cols
- **Date range:** 1960-01 → 2026-07 (monthly, format `YYYYMNN`)
- **Frequency:** monthly
- **Duplicates:** 0
- **Missing values:** `coal_australian_usd_per_mt` has 120 nulls (all
  pre-1990 — the series begins around 1990)
- **Has model features:** `coal_price_usd_per_mt`, `iron_ore_price_usd_per_dmt`
  (under World Bank column names)
- **Notable:** values match FFT exactly on all 22 overlapping months
  (2024-02 → 2025-11). Authoritative source for these two features.

### E. `weather_monthly_all_locations_2024_2025.csv`

- **Shape:** 96 rows × 6 cols
- **Date range:** 2024-01 → 2025-12 (monthly, format `YYYY-MM`)
- **Frequency:** monthly
- **Duplicates:** 0
- **Missing values:** none
- **Locations (4):** `Hay Point`, `Taboneo`, `Visakhapatnam`, `Paradip`
  (24 months each)
- **Has model features:** **no** — file has temperature, avg wind, gust,
  precipitation. **No wave height, no cyclone risk, no weather delay.**
- **Notable:** wind values do **not** match FFT's `*_wind_kts` columns
  (different aggregation, ratio ≈ 0.62 not 1.852). Supporting reference
  only — not a drop-in source for the model's weather features.

### F. `real_route_validation_predictions_v1.csv`

- **Status:** **NOT UPLOADED** at audit time.
- **Planned handling:** validation-only. Separate directory. Target/prediction
  columns never used for training.

---

## Audit Artefacts

- This report: `DATASET_INTEGRATION_REPORT.md`
- No other files were created, modified, or deleted.
- `freight_forecast_model_v1.joblib` was **not** loaded or modified.
- No datasets were merged.
- No missing values were filled.
- No synthetic data was generated.
- All numeric findings in this report were computed directly from the
  uploaded CSV files using `pandas`.

---

*End of report. STOP.*
