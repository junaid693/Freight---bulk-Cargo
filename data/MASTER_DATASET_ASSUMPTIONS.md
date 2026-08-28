# MASTER DATASET ASSUMPTIONS

> This document records every assumption made when building
> `data/master_freight_training_v1.csv`. It is the companion to
> `data/master_freight_training_report.md` and the build script
> `build_master_dataset.py`.
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

### Assumption
- **`Australia East Coast` → `Hay Point`** — Hay Point is the principal coal
  loading port on Australia's east coast (Queensland). This is an explicit
  one-way mapping for the retraining-ready subset.
- **`Taboneo` → `Taboneo`** — already port-level; no mapping needed.
- **`Australia West Coast` → EXCLUDED** — there is no port-level equivalent
  in the existing model's training categories, and silently mapping it to
  `Hay Point` would be geographically incorrect (different coast, different
  ports). These rows are placed in
  `data/excluded/west_coast_unmapped.csv`.

### Destination
All FFT routes use `East Coast India` as destination. This is already
region-level and is preserved as-is (the existing model was trained with
`Paradip` and `Visakhapatnam` as port-level destinations, but the FFT data
does not distinguish them, so we cannot map down to port level on the
destination side without inventing data). This is a known limitation — see
the report.

---

## 3. Categorical domain — preserve original, exclude unsupported

### Problem
The existing model's one-hot categories (from
`OneHotEncoder.categories_`) are:
- commodities: `Coal`, `Iron Ore`
- vessel types: `Panamax`, `Supramax`

FFT also contains `Thermal Coal` (commodity) and `Capesize` (vessel). These
are NOT in the model's training distribution.

### Assumption
- **Do not silently rename** `Thermal Coal` → `Coal` (they are distinct
  commodities in the real world).
- **Do not silently convert** `Capesize` → another vessel class.
- Keep the original categorical value in the row, but **exclude the row**
  from the retraining-ready subset.
- Excluded rows go to:
  - `data/excluded/unsupported_commodity_rows.csv`
  - `data/excluded/unsupported_vessel_rows.csv`

This preserves the original data for future use (e.g. if you later expand
the model to support `Thermal Coal` and `Capesize`) without contaminating
the current retraining subset with out-of-distribution categories.

---

## 4. World Bank as canonical source for coal/iron-ore prices

### Assumption
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

### Assumption
FFT stores weather for three regions per row:
- `taboneo_wind_kts`, `taboneo_wave_hs_m`
- `aus_east_wind_kts`, `aus_east_wave_hs_m`
- `aus_west_wind_kts`, `aus_west_wave_hs_m`

The model expects a single `wind_kmh` and `wave_height_m`. We select the
**region-matching pair** per row based on its origin:
- `Taboneo` rows → taboneo columns
- `Australia East Coast` rows → aus_east columns
- `Australia West Coast` rows → aus_west columns (these rows are later
  excluded — see §2 — but the selection is still recorded for transparency)

This is a **selection** from existing observed values, not fabrication.

---

## 6. Unit conversion — wind knots → km/h

### Assumption
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
the master dataset's feature matrix because they are derived from the target
or are metadata:

| Column | Reason for exclusion |
|--------|---------------------|
| `previous_month_freight` | target-derived lag (= `freight_rate[t-1]`); would cause leakage if used as input |
| `freight_3_month_avg` | target-derived rolling average; same leakage risk |
| `freight_observation_count` | metadata (count of underlying fixtures), not a model input |
| `year`, `month_number`, `quarter_number` | calendar metadata — useful for time-aware CV but NOT model inputs |

These columns are NOT carried into `master_freight_training_v1.csv`.

---

## 8. Benchmark duplicate handling

### Assumption
`expanded_freight_benchmark_2024_2025.csv` has 120 rows. 110 of them are
**exact duplicates** of FFT rows on the key
`(date, origin, destination, commodity, vessel_type)` — freight, VLSFO and
BDI all agree to 4 decimal places. The other 10 rows are **boundary months**
(2024-01 and 2025-12) that have freight/vlsfo/bdi but **no target**.

### Action
- The 110 duplicate rows are **not added** to the master dataset (would
  double-count observations).
- The 10 boundary rows are saved to
  `data/excluded/boundary_benchmark_rows.csv` as **reference only** — they
  are not added to training because they have no target.

---

## 9. Validation data separation

### Assumption
`real_route_validation_predictions_v1.csv` (when uploaded) is
**validation-only**. Its prediction / target / future columns must NEVER
enter training.

### Action
- The build script `build_master_dataset.py` **never reads** the validation
  file.
- When uploaded, it should be placed in `data/validation/` (a directory
  excluded from training data loading).
- Quality check #4 confirms the validation file was not used.

---

## Summary table

| Assumption | Affects | Reversibility |
|-----------|--------|---------------|
| Representative cargo tonnes by vessel class | `cargo_tonnes` | Replace with real fixture quantities when recovered |
| Australia East Coast → Hay Point | `origin` | One-way mapping; reversible |
| Australia West Coast excluded | (excluded rows) | Re-include if model is retrained with region-level origins |
| Thermal Coal excluded (commodity) | (excluded rows) | Re-include if model is retrained with Thermal Coal category |
| Capesize excluded (vessel) | (excluded rows) | Re-include if model is retrained with Capesize category |
| World Bank canonical for coal/iron-ore | `coal_price`, `iron_ore` | Already matches FFT; no risk |
| Wind knots → km/h (×1.852) | `wind_kmh` | Exact unit conversion; reversible |
| Weather column selection per route | `wind_kmh`, `wave_height_m` | Selection from observed values; not fabrication |
| Excluded lag/metadata columns | (excluded features) | Can be re-added if model design changes |

---

*End of assumptions document.*
