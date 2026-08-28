# Master Freight Training Dataset — Build Report

> **Status:** Master dataset constructed. **No production model modified.**
> **No retraining performed.** This report documents the build of
> `data/master_freight_training_v1.csv` from the recovered datasets.
>
> **Build script:** `build_master_dataset.py` (single source of truth,
> reproducible)
> **Assumptions doc:** `data/MASTER_DATASET_ASSUMPTIONS.md`
> **Date of build:** 2026-08-28

---

## 1. Build overview

| Metric | Value |
|--------|-------|
| Source file | `freight_forecasting_training_table_v1.csv` (FFT) |
| FFT rows in | 110 |
| **Master rows out** | **22** |
| Excluded rows total | 88 |
| Master columns | 19 (5 audit + 14 model features + 1 target) |
| Date range | 2024-02-01 → 2025-11-01 (monthly) |
| Frequency | monthly |
| Build quality checks | **11/11 passed** ✅ |
| Model file `freight_forecast_model_v1.joblib` | **untouched** (sha256 `695fafe3...`) |

---

## 2. Final row count

**22 rows** in the retraining-ready master dataset.

This is the result of applying the categorical-domain exclusions to FFT:

| Step | Rows | Cumulative |
|------|------|-----------|
| FFT in | 110 | 110 |
| − Australia West Coast (no port-level mapping) | −22 | 88 |
| − Unsupported commodity (Thermal Coal) | −44 | 44 |
| − Unsupported vessel (Capesize) | −22 | **22** |

> Note: the exclusions are applied in this order so each excluded row gets
> a single primary reason. A row that is both `Australia West Coast` AND
> `Capesize` is counted only in the West Coast bucket.

---

## 3. Date range

- **Start:** 2024-02-01
- **End:** 2025-11-01
- **Frequency:** monthly (day = 1)
- **Span:** 22 months
- **Coverage:** one observation per month (no gaps in the kept subset)

---

## 4. Route distribution

| Origin | Destination | Rows |
|--------|-------------|------|
| Hay Point | East Coast India | 22 |

Only **one route** remains after the West Coast exclusion. The destination
is region-level (`East Coast India`) because FFT does not distinguish
between `Paradip` and `Visakhapatnam` on the destination side — this is a
known limitation (see §13).

---

## 5. Commodity distribution

| Commodity | Rows |
|-----------|------|
| Coal | 22 |

`Thermal Coal` and `Iron Ore` rows were excluded (not in the existing
model's training categories for this route/vessel combination).

---

## 6. Vessel distribution

| Vessel type | Rows |
|-------------|------|
| Panamax | 22 |

`Capesize` and `Supramax` rows were excluded (no `Supramax` rows survive
the route + commodity filters).

---

## 7. Route × commodity × vessel combinations remaining

| origin | destination | commodity | vessel_type | rows |
|--------|-------------|-----------|-------------|------|
| Hay Point | East Coast India | Coal | Panamax | 22 |

**Exactly one (route, commodity, vessel) combination remains.** This is a
very narrow training distribution — see §13 (limitations) for implications.

---

## 8. Missing values

**None.** Every column in every row is populated.

```
nulls_per_col = {}
```

This is verified by quality check #8.

---

## 9. Duplicate keys

**Zero duplicate keys** on `(date, origin, destination, commodity, vessel_type)`.

Verified by quality check #1.

---

## 10. Freight and target statistics

### `current_freight_usd_per_tonne` (USD/tonne)

| Stat | Value |
|------|-------|
| min | 14.50 |
| 25% | 15.625 |
| median | 17.40 |
| 75% | 19.175 |
| max | 21.20 |

### `next_month_freight_usd_per_tonne` (target, USD/tonne)

| Stat | Value |
|------|-------|
| min | 14.50 |
| median | 18.30 |
| max | 21.20 |

---

## 11. Target alignment check

The target `next_month_freight_usd_per_tonne` should equal the
`current_freight_usd_per_tonne` of the **next month** for the same route /
commodity / vessel group.

**Result:** 21 of 21 consecutive row-pairs align exactly (the 22nd row has
no successor in the kept subset). ✅

```
checked=21  aligned=21  mismatches=0
```

Verified by quality check #2.

---

## 12. Current freight vs next-month target correlation

| Metric | Value |
|--------|-------|
| Pearson correlation | **0.5078** |

A moderate positive correlation — current freight is a useful but not
dominant predictor of next-month freight. (For comparison, the existing
trained model relies on `current_freight` for 93.6% of its feature
importance — see the prior audit report. The master dataset's correlation
is much lower than the model's reliance would suggest, which is worth
investigating during the retraining phase — but that is out of scope here.)

---

## 13. Source mapping

Every master row is tagged with `data_source = freight_forecasting_training_table_v1.csv`.

### Per-feature source

| Feature | Source | Transformation |
|---------|--------|----------------|
| `date` | FFT.`date` | direct (ISO format) |
| `origin` | FFT.`route` (left of ` -> `) | region→port mapping: `Australia East Coast → Hay Point` |
| `destination` | FFT.`route` (right of ` -> `) | direct (region-level preserved) |
| `commodity` | FFT.`commodity` | direct |
| `vessel_type` | FFT.`vessel_type` | direct |
| `cargo_tonnes` | representative by vessel class | `Panamax=75,000`, `Supramax=55,000`, `Capesize=170,000`. Flagged `cargo_value_type=representative_vessel_capacity`. NOT observed fixtures. |
| `bdi` | FFT.`baltic_dry_index` | rename |
| `vlsfo_usd_per_tonne` | FFT.`vlsfo_bunker_usd_per_tonne` | rename |
| `coal_price_usd_per_mt` | FFT = World Bank (verified identical) | rename; World Bank canonical |
| `iron_ore_price_usd_per_dmt` | FFT = World Bank (verified identical) | rename; World Bank canonical |
| `wind_kmh` | FFT route-specific `*_wind_kts` × 1.852 | unit conversion knots→km/h |
| `wave_height_m` | FFT route-specific `*_wave_hs_m` | direct (already metres) |
| `cyclone_risk` | FFT.`bob_cyclone_alert_index` | rename |
| `weather_delay_days` | FFT.`estimated_weather_delay_days` | rename |
| `current_freight_usd_per_tonne` | FFT.`freight_rate_usd_per_tonne` | rename |
| `next_month_freight_usd_per_tonne` (target) | FFT.`next_month_freight_usd_per_tonne` | direct |

### World Bank verification

| Check | Result |
|-------|--------|
| Shared months (FFT ∩ World Bank, 2024–2025) | 22 |
| coal_price max diff | 0.000 |
| iron_ore max diff | 0.000 |
| Match | ✅ True |

World Bank values match FFT exactly on every overlapping month, so World
Bank is treated as the canonical source for these two features (per Step 7).

---

## 14. Exclusions and reasons

### 14.1 `data/excluded/west_coast_unmapped.csv` — 22 rows

| Reason | Count |
|--------|-------|
| `route_origin_unmapped: 'Australia West Coast' has no port-level equivalent in the existing model's training categories (Hay Point, Taboneo). Mapping to Hay Point would be geographically incorrect; row excluded from the retraining-ready subset.` | 22 |

### 14.2 `data/excluded/unsupported_commodity_rows.csv` — 44 rows

| Reason | Count |
|--------|-------|
| `unsupported_commodity: 'Thermal Coal' is not in the existing model's training categories (Coal, Iron Ore). Original value preserved; row excluded from the retraining-ready subset.` | 44 |

### 14.3 `data/excluded/unsupported_vessel_rows.csv` — 22 rows

| Reason | Count |
|--------|-------|
| `unsupported_vessel: 'Capesize' is not in the existing model's training categories (Panamax, Supramax). Original value preserved; row excluded from the retraining-ready subset.` | 22 |

### 14.4 `data/excluded/boundary_benchmark_rows.csv` — 10 rows (reference only)

These are the 10 rows in `expanded_freight_benchmark_2024_2025.csv` for
boundary months (2024-01 and 2025-12) that have freight/vlsfo/bdi values
but **no `next_month_freight` target** in FFT. They are kept for reference
only and are NOT added to the training dataset.

### 14.5 Benchmark duplicate rows — 110 (NOT added)

110 of the 120 benchmark rows are **exact duplicates** of FFT rows on
`(date, origin, destination, commodity, vessel_type)` with matching
freight/vlsfo/bdi. These are NOT added to the master (would double-count).

### Summary of all exclusions

| Bucket | Count | Added to training? |
|--------|-------|-------------------|
| West Coast unmapped | 22 | ❌ excluded |
| Unsupported commodity (Thermal Coal) | 44 | ❌ excluded |
| Unsupported vessel (Capesize) | 22 | ❌ excluded |
| Boundary benchmark rows (no target) | 10 | ❌ reference only |
| Benchmark duplicates of FFT | 110 | ❌ not added (would double-count) |
| **Total excluded / not added** | **208** | — |
| **Master rows (kept)** | **22** | ✅ training |

---

## 15. cargo_tonnes assumption

`cargo_tonnes` is **missing from every uploaded CSV file**. We use
**representative vessel capacities** (not random, not observed fixtures):

| Vessel type | Representative cargo (tonnes) |
|-------------|------------------------------|
| Panamax | 75,000 |
| Supramax | 55,000 |
| Capesize | 170,000 |

Every master row carries `cargo_value_type = "representative_vessel_capacity"`
so downstream code knows these are NOT observed fixture quantities.

**Full rationale:** see `data/MASTER_DATASET_ASSUMPTIONS.md` §1.

---

## 16. All transformations applied

| # | Transformation | Affected columns | Reversible? |
|---|----------------|------------------|-------------|
| 1 | Parse `route` → `origin` + `destination` | `route` | yes (concatenate) |
| 2 | Map `Australia East Coast` → `Hay Point` | `origin` | yes (one-way mapping) |
| 3 | Rename `baltic_dry_index` → `bdi` | `bdi` | yes |
| 4 | Rename `vlsfo_bunker_usd_per_tonne` → `vlsfo_usd_per_tonne` | `vlsfo_usd_per_tonne` | yes |
| 5 | Rename `coal_australian_usd_per_mt` → `coal_price_usd_per_mt` | `coal_price_usd_per_mt` | yes |
| 6 | Rename `iron_ore_cfr_usd_per_dmt` → `iron_ore_price_usd_per_dmt` | `iron_ore_price_usd_per_dmt` | yes |
| 7 | Rename `freight_rate_usd_per_tonne` → `current_freight_usd_per_tonne` | `current_freight_usd_per_tonne` | yes |
| 8 | Rename `bob_cyclone_alert_index` → `cyclone_risk` | `cyclone_risk` | yes |
| 9 | Rename `estimated_weather_delay_days` → `weather_delay_days` | `weather_delay_days` | yes |
| 10 | Select route-specific wind column (`taboneo`/`aus_east`/`aus_west`) | `wind_kmh` | selection from observed |
| 11 | Convert wind knots → km/h (× 1.852) | `wind_kmh` | yes (÷ 1.852) |
| 12 | Select route-specific wave column | `wave_height_m` | selection from observed |
| 13 | Assign representative `cargo_tonnes` by vessel class | `cargo_tonnes` | yes (replace with real fixtures when available) |
| 14 | Add audit metadata (`data_source`, `cargo_value_type`, `ingested_at`) | (new cols) | yes |

---

## 17. Quality checks — 11/11 passed ✅

| # | Check | Result | Detail |
|---|-------|--------|--------|
| 1 | No duplicate `(date, origin, destination, commodity, vessel_type)` keys | ✅ PASS | duplicate keys=0 |
| 2 | Every target = next month's freight (same route/commodity/vessel) | ✅ PASS | checked=21 mismatches=0 |
| 3 | No target-derived lag columns in features | ✅ PASS | `previous_month_freight`, `freight_3_month_avg`, `freight_observation_count` all absent |
| 4 | No validation rows in training | ✅ PASS | validation file never read by builder |
| 5 | No benchmark duplicate rows | ✅ PASS | 110 benchmark duplicates excluded in Step 8 |
| 6 | No unsupported categoricals in retraining subset | ✅ PASS | bad_origin=0 bad_commodity=0 bad_vessel=0 |
| 7 | All 14 model inputs present | ✅ PASS | missing=[] |
| 8 | No missing values in feature/target columns | ✅ PASS | nulls_per_col={} |
| 9 | All wind values in km/h | ✅ PASS | wind_kmh range=26.30..50.93 |
| 10 | All freight values in USD/tonne | ✅ PASS | freight range=14.50..21.20 |
| 11 | All wave values in metres | ✅ PASS | wave range=1.60..3.80 |

---

## 18. Output files

| Path | Purpose | Rows |
|------|---------|------|
| `data/master_freight_training_v1.csv` | **Retraining-ready master dataset** | 22 |
| `data/MASTER_DATASET_ASSUMPTIONS.md` | All assumptions documented | — |
| `data/master_freight_training_report.md` | This report | — |
| `data/excluded/west_coast_unmapped.csv` | Excluded Australia West Coast rows | 22 |
| `data/excluded/unsupported_commodity_rows.csv` | Excluded Thermal Coal rows | 44 |
| `data/excluded/unsupported_vessel_rows.csv` | Excluded Capesize rows | 22 |
| `data/excluded/boundary_benchmark_rows.csv` | Boundary benchmark rows (reference only) | 10 |
| `build_master_dataset.py` | Reproducible build script | — |

---

## 19. Limitations and caveats

1. **Only one route/commodity/vessel combination remains** (Hay Point →
   East Coast India, Coal, Panamax). The retraining subset is very narrow.
2. **`cargo_tonnes` is representative, not observed.** Constant within each
   vessel class — the retrained model cannot learn cargo-size effects
   within a class.
3. **Destination is region-level** (`East Coast India`), not port-level
   (`Paradip`/`Visakhapatnam`). The existing model was trained with
   port-level destinations; this is a granularity mismatch that retraining
   will inherit.
4. **22 rows is small for retraining a RandomForest.** Consider whether
   this is sufficient before retraining (out of scope here).
5. The benchmark file's 110 duplicate rows could be used to **augment** if
   augmentation were desired — but the spec forbids duplicating rows, so
   they are excluded.

---

## 20. What was NOT done

- ❌ The production model `freight_forecast_model_v1.joblib` was **not
  modified** (sha256 verified: `695fafe3f31b560d5a4412124c0839e0e622c9d2bd090191a5e02eaef6c3819a`).
- ❌ No retraining was performed.
- ❌ No new `.joblib` file was created.
- ❌ The FastAPI prediction code was **not altered**.
- ❌ The validation file (`real_route_validation_predictions_v1.csv`) was
  **never read** by the builder.
- ❌ No synthetic market / weather / freight / target values were generated.
- ❌ No benchmark duplicate rows were added to training.

---

## 21. STOP

The master dataset is built. The build stops here.

**Next step (when you choose to proceed):** review this report and
`MASTER_DATASET_ASSUMPTIONS.md`, then decide whether to:
- (a) retrain a new model on `data/master_freight_training_v1.csv`, or
- (b) expand the dataset first (e.g. recover real cargo quantities, add
  West Coast / Thermal Coal / Capesize support).

*End of report.*
