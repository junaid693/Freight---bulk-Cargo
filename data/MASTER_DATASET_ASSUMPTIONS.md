# MASTER DATASET ASSUMPTIONS

> This document records every assumption made when building the master
> training datasets. It applies to BOTH:
>
> - `data/master_freight_training_v1.csv` (narrow build — 22 rows, only
>   categories already in the existing model)
> - `data/master_freight_training_expanded_v1.csv` (expanded build —
>   110 rows, new categories included for a future retrained model)
>
> Differences between the two builds are highlighted inline.
>
> **No production model was modified. No retraining was performed.**

---

## 1. cargo_tonnes — representative vessel capacity

### Problem
`cargo_tonnes` is one of the 14 model input features (it appears in
`freight_forecast_model_v1.joblib`'s `feature_names_in_`), but it is **absent
from every uploaded CSV file**. The original training data must have had it;
it was dropped when the FFT CSV was exported. We cannot recover the original
per-fixture cargo quantities from the current uploads.

### Assumption
Instead of fabricating per-row cargo values, we assign a single
**representative vessel capacity** per vessel class. These are well-known
industry prototype cargo sizes for the major dry-bulk vessel classes — they
are NOT observed fixture quantities.

| Vessel type | Representative cargo (tonnes) | Source / convention |
|-------------|------------------------------|---------------------|
| Panamax     | 75,000                       | Standard Panamax deadweight capacity for coal/ore trades |
| Supramax    | 55,000                       | Typical Supramax deadweight capacity |
| Capesize    | 170,000                      | Standard Capesize deadweight capacity |

### Metadata flag
Every master row carries `cargo_value_type = "representative_vessel_capacity"`
so downstream code and auditors know these are NOT observed fixture values.

### What this means for retraining
- The retrained model will learn a cargo effect that is **constant within each
  vessel class** — it cannot distinguish cargo variation within a class.
- If you can later recover real fixture-level cargo quantities (e.g. from the
  original `Dry_Bulk_Freight_Benchmarks_India.xlsx` workbook referenced in the
  benchmark's `source` column), rebuild the master dataset with those values
  and remove the `representative_vessel_capacity` flag.

### Exclusion from feature set
`cargo_value_type` is **metadata only** — it must NOT be used as an ML input.
The 14 model features are exactly the ones listed in the build script's
`MODEL_FEATURES` constant.

---

## 2. Route granularity mapping (region → port)

### Problem
FFT uses **region-level** origins:
- `Australia East Coast`
- `Australia West Coast`
- `Taboneo`

The existing model was trained with **port-level** origins:
- `Hay Point`
- `Taboneo`

There is a granularity mismatch.

### Assumption — applies to BOTH builds

- **`Australia East Coast` → `Hay Point`** — Hay Point is the principal coal
  loading port on Australia's east coast (Queensland). This is an explicit
  one-way mapping.
- **`Taboneo` → `Taboneo`** — already port-level; no mapping needed.

### `Australia West Coast` — DIFFERS between builds

| Build | Treatment | Reason |
|-------|-----------|--------|
| Narrow (`master_freight_training_v1.csv`) | **EXCLUDED** — saved to `data/excluded/west_coast_unmapped.csv` | The existing model has no port-level training category for it; silently mapping to `Hay Point` would be geographically incorrect |
| **Expanded** (`master_freight_training_expanded_v1.csv`) | **KEPT AS `Australia West Coast`** | The future retrained model will learn this as a new origin category. No silent mapping |

### Destination
All FFT routes use `East Coast India` as destination. This is already
region-level and is preserved as-is in **both** builds. The existing model
was trained with `Paradip` and `Visakhapatnam` as port-level destinations,
but the FFT data does not distinguish them, so we cannot map down to port
level on the destination side without inventing data. This is a known
limitation — see the reports.

---

## 3. Categorical domain — DIFFERS between builds

### Problem
The existing model's one-hot categories (from
`OneHotEncoder.categories_`) are:
- commodities: `Coal`, `Iron Ore`
- vessel types: `Panamax`, `Supramax`

FFT also contains `Thermal Coal` (commodity) and `Capesize` (vessel). These
are NOT in the existing model's training distribution.

### Narrow build (v1) — preserve original, exclude unsupported
- Do not silently rename `Thermal Coal` → `Coal`.
- Do not silently convert `Capesize` → another vessel class.
- **Exclude** these rows → `data/excluded/unsupported_*.csv`.
- Result: only `Coal` + `Panamax` survive (with `Hay Point` origin).

### Expanded build — keep all original values, let the new model learn them
- `Thermal Coal` is **kept as a distinct commodity**.
- `Capesize` is **kept as a distinct vessel type**.
- `Australia West Coast` is **kept as a distinct origin**.
- The future retrained model will learn the expanded vocabulary:
  - origins: `Hay Point`, `Taboneo`, `Australia West Coast` (3)
  - destination: `East Coast India` (1)
  - commodities: `Coal`, `Thermal Coal`, `Iron Ore` (3)
  - vessel types: `Panamax`, `Supramax`, `Capesize` (3)

This preserves all original data and lets the new model learn the expanded
categorical space.

---

## 4. World Bank as canonical source for coal/iron-ore prices

### Assumption (both builds)
The World Bank file (`world_bank_coal_iron_ore_monthly.csv`) is treated as
the **canonical source** for `coal_price_usd_per_mt` and
`iron_ore_price_usd_per_dmt` on dates where both FFT and World Bank have
values. This is justified because:
- World Bank values match FFT exactly on all 22 overlapping months
  (max diff = 0.0 for both series).
- World Bank extends further back (to 1960) and forward (to 2026-07).
- World Bank is a recognised, citable primary source.

### What we do NOT do
- We do NOT extend the master dataset into dates where there is no freight
  observation + target. Adding more market-only rows would create rows
  with no target — useless (and harmful) for supervised training.

---

## 5. Weather column selection (route-dependent)

### Assumption (both builds)
FFT stores weather for three regions per row:
- `taboneo_wind_kts`, `taboneo_wave_hs_m`
- `aus_east_wind_kts`, `aus_east_wave_hs_m`
- `aus_west_wind_kts`, `aus_west_wave_hs_m`

The model expects a single `wind_kmh` and `wave_height_m`. We select the
**region-matching pair** per row based on its origin:
- `Taboneo` rows → taboneo columns
- `Australia East Coast` → Hay Point rows → aus_east columns
- `Australia West Coast` rows → aus_west columns (kept in the expanded build;
  excluded in the narrow build)

This is a **selection** from existing observed values, not fabrication.

### weather_monthly_all_locations_2024_2025.csv — NOT used as a replacement
The audit established that this file's aggregation does NOT match FFT's
weather columns (ratio ≈ 0.62, not the 1.852 km/h-per-knot ratio expected if
they were the same series rescaled). It also has no wave-height column.
Therefore it is **not** used to source `wind_kmh`, `wave_height_m`,
`cyclone_risk`, or `weather_delay_days` in either build. It remains a
supporting reference only.

---

## 6. Unit conversion — wind knots → km/h

### Assumption (both builds)
FFT wind columns are in **knots** (suffix `_kts`). The model expects
`wind_kmh`. We apply the exact, dimensionally-correct conversion:

```
wind_kmh = wind_kts * 1.852
```

1 knot = 1.852 km/h (international standard).

### No other unit conversions
- `wave_height_m` — already in metres (suffix `_hs_m` = significant wave height in metres). Kept unchanged.
- `bdi` — index points (dimensionless).
- `vlsfo_usd_per_tonne` — USD/tonne (matches model).
- `coal_price_usd_per_mt` — USD/MT (matches model; = World Bank unit).
- `iron_ore_price_usd_per_dmt` — USD/dmt (matches model; = World Bank unit).
- `current_freight_usd_per_tonne` — USD/tonne (matches model).
- `cyclone_risk` — 0–5 score (FFT `bob_cyclone_alert_index` is 1–5, within model's 0–5 domain).
- `weather_delay_days` — days (FFT `estimated_weather_delay_days` is 0–4 days).

---

## 7. Excluded target-derived / metadata columns

The following columns are present in FFT/Expanded but are **excluded** from
both master datasets' feature matrices because they are derived from the
target or are metadata:

| Column | Reason for exclusion |
|--------|---------------------|
| `previous_month_freight` | target-derived lag (= `freight_rate[t-1]`); would cause leakage if used as input |
| `freight_3_month_avg` | target-derived rolling average; same leakage risk |
| `freight_observation_count` | metadata (count of underlying fixtures), not a model input |
| `year`, `month_number`, `quarter_number` | calendar metadata — useful for time-aware CV but NOT model inputs |

These columns are NOT carried into either `master_freight_training_v1.csv`
or `master_freight_training_expanded_v1.csv`.

---

## 8. Benchmark duplicate handling

### Assumption (both builds)
`expanded_freight_benchmark_2024_2025.csv` has 120 rows. 110 of them are
**exact duplicates** of FFT rows on the key
`(date, origin, destination, commodity, vessel_type)` — freight, VLSFO and
BDI all agree to 4 decimal places. The other 10 rows are **boundary months**
(2024-01 and 2025-12) that have freight/vlsfo/bdi but **no target**.

### Action
- The 110 duplicate rows are **not added** to either master dataset (would
  double-count observations).
- The 10 boundary rows are saved to
  `data/excluded/boundary_benchmark_rows.csv` (narrow build) and
  `data/excluded_expanded/boundary_benchmark_rows.csv` (expanded build) as
  **reference only** — they are not added to training because they have no
  target.

---

## 9. Validation data separation

### Assumption (both builds)
`real_route_validation_predictions_v1.csv` (when uploaded) is
**validation-only**. Its prediction / target / future columns must NEVER
enter training.

### Action
- Both build scripts (`build_master_dataset.py` and
  `build_master_dataset_expanded.py`) **never read** the validation file.
- When uploaded, it should be placed in `data/validation/` (a directory
  excluded from training data loading).
- Quality check #4 in both builds confirms the validation file was not used.

---

## 10. Expanded build — model readiness

The expanded build produces a dataset with:
- **3 origins** × 1 destination × **3 commodities** × **3 vessel types**
- **5 unique (origin, destination, commodity, vessel_type) combinations**,
  each with exactly 22 monthly observations
- 110 total rows, 100% retention from FFT
- target alignment verified 105/105
- corr(current_freight, target) = 0.8567

These combinations (with 22 obs each) are sufficient for a RandomForest
to learn per-combination effects. See
`data/master_freight_training_expanded_report.md` for the full readiness
analysis.

---

## Summary table

| Assumption | Affects | Reversibility |
|-----------|--------|---------------|
| Representative cargo tonnes by vessel class | `cargo_tonnes` | Replace with real fixture quantities when recovered |
| Australia East Coast → Hay Point | `origin` | One-way mapping; reversible |
| Australia West Coast (narrow: excluded / expanded: kept as new origin) | `origin` | Re-include in narrow build, or remap in expanded build, if desired |
| Thermal Coal (narrow: excluded / expanded: kept as new commodity) | `commodity` | Re-include or remap if desired |
| Capesize (narrow: excluded / expanded: kept as new vessel) | `vessel_type` | Re-include or remap if desired |
| World Bank canonical for coal/iron-ore | `coal_price`, `iron_ore` | Already matches FFT; no risk |
| Wind knots → km/h (×1.852) | `wind_kmh` | Exact unit conversion; reversible |
| Weather column selection per route | `wind_kmh`, `wave_height_m` | Selection from observed values; not fabrication |
| Excluded lag/metadata columns | (excluded features) | Can be re-added if model design changes |
| weather_monthly_all_locations NOT used as weather source | (no effect) | Could be re-evaluated if model design changes |

---

*End of assumptions document.*
