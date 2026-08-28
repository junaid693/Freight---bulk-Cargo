# Expanded Master Freight Training Dataset — Build Report

> **Status:** Expanded master dataset constructed. **No production model
> modified. No retraining performed. No new .joblib created. No FastAPI
> changes. STOP after build.**
>
> **Build script:** `build_master_dataset_expanded.py` (single source of
> truth, reproducible)
> **Assumptions doc:** `data/MASTER_DATASET_ASSUMPTIONS.md`
> **Date of build:** 2026-08-28

---

## 1. Build overview

| Metric | Value |
|--------|-------|
| Source file | `freight_forecasting_training_table_v1.csv` (FFT) |
| FFT rows in | 110 |
| **Master rows out** | **110** |
| **Retention** | **110 / 110 = 100.0%** |
| Excluded rows total | 0 (no row excluded — all 110 retained) |
| Master columns | 19 (4 audit + 14 model features + 1 target) |
| Date range | 2024-02-01 → 2025-11-01 (monthly) |
| Frequency | monthly |
| Build quality checks | **11/11 passed** ✅ |
| Model file `freight_forecast_model_v1.joblib` | **untouched** (sha256 `695fafe3...`) |

### Difference from the narrow build (`master_freight_training_v1.csv`)

| Dimension | Narrow build | **Expanded build** |
|-----------|--------------|--------------------|
| Rows | 22 | **110** |
| Retention | 20% | **100%** |
| Origins | 1 (Hay Point) | **3 (Hay Point, Taboneo, Australia West Coast)** |
| Commodities | 1 (Coal) | **3 (Coal, Thermal Coal, Iron Ore)** |
| Vessel types | 1 (Panamax) | **3 (Panamax, Supramax, Capesize)** |
| (route, commodity, vessel) combos | 1 | **5** |
| corr(current_freight, target) | 0.5078 | **0.8567** |
| Use case | Retraining with the existing model's vocabulary | **Retraining a NEW model with expanded vocabulary** |

---

## 2. Original FFT rows vs final retained rows

| Stage | Rows |
|-------|------|
| FFT rows in | 110 |
| − rows with genuinely missing required values | 0 |
| **Final retained rows** | **110** |
| Retention | **100.0%** |

No rows were excluded. Every FFT observation is preserved in the expanded
master dataset.

---

## 3. Excluded rows

**0 rows excluded** from training.

No categorical exclusions were applied (the expanded build intentionally
keeps `Australia West Coast`, `Thermal Coal`, and `Capesize` as new
categories for the future retrained model to learn).

No rows had genuinely missing required values — every FFT row has all 14
model features (after transformation) plus the target.

### Reference-only files

| Path | Rows | Note |
|------|------|------|
| `data/excluded_expanded/boundary_benchmark_rows.csv` | 10 | Boundary months (2024-01, 2025-12) from the benchmark file — have freight/vlsfo/bdi but no target. Reference only, NOT in training. |

### Benchmark duplicates

110 of the 120 benchmark rows are exact duplicates of FFT rows on
`(date, origin, destination, commodity, vessel_type)` with matching
freight/vlsfo/bdi. These are NOT added (would double-count observations).

---

## 4. Retention percentage

**110 / 110 = 100.0%**

---

## 5. Route counts

| Route (origin → destination) | Rows |
|------------------------------|------|
| Hay Point → East Coast India | 44 |
| Taboneo → East Coast India | 44 |
| Australia West Coast → East Coast India | 22 |
| **Total** | **110** |

---

## 6. Origin counts

| Origin | Rows |
|--------|------|
| Hay Point | 44 |
| Taboneo | 44 |
| Australia West Coast | 22 |
| **Total** | **110** |

---

## 7. Destination counts

| Destination | Rows |
|-------------|------|
| East Coast India | 110 |

> Single destination. FFT does not distinguish `Paradip` from
> `Visakhapatnam` on the destination side; the destination is preserved
> at region level. This is a known limitation (see §13).

---

## 8. Commodity counts

| Commodity | Rows |
|-----------|------|
| Coal | 44 |
| Thermal Coal | 44 |
| Iron Ore | 22 |
| **Total** | **110** |

---

## 9. Vessel counts

| Vessel type | Rows |
|-------------|------|
| Capesize | 44 |
| Panamax | 44 |
| Supramax | 22 |
| **Total** | **110** |

---

## 10. Date range

- **Start:** 2024-02-01
- **End:** 2025-11-01
- **Frequency:** monthly (day = 1)
- **Span:** 22 months per combination
- **Coverage:** one observation per month per route/commodity/vessel combination

---

## 11. Missing values

**None.** Every column in every row is populated.

```
nulls_per_col = {}
```

Verified by quality check #7.

---

## 12. Duplicate keys

**Zero duplicate keys** on `(date, origin, destination, commodity, vessel_type)`.

Verified by quality check #1.

---

## 13. Freight range

### `current_freight_usd_per_tonne` (USD/tonne)

| Stat | Value |
|------|-------|
| min | 8.50 |
| median | 12.55 |
| max | 21.20 |

---

## 14. Target range

### `next_month_freight_usd_per_tonne` (target, USD/tonne)

| Stat | Value |
|------|-------|
| min | 8.50 |
| median | 12.75 |
| max | 21.20 |

---

## 15. Target alignment result

The target `next_month_freight_usd_per_tonne` should equal the
`current_freight_usd_per_tonne` of the **next month** for the same route /
commodity / vessel group.

**Result:** 105 of 105 consecutive row-pairs align exactly. ✅

```
checked=105  aligned=105  mismatches=0
```

(The 5 missing successor rows are the last observation in each
route/commodity/vessel group — they have no successor by definition.)

Verified by quality check #2.

---

## 16. World Bank comparison

| Check | Result |
|-------|--------|
| Shared months (FFT ∩ World Bank, 2024–2025) | 22 |
| `coal_price_usd_per_mt` max diff | 0.000 |
| `iron_ore_price_usd_per_dmt` max diff | 0.000 |
| Match | ✅ True |

World Bank values match FFT exactly on every overlapping month. World Bank
is treated as the canonical source for these two features (per Step 6).

---

## 17. Weather transformation checks

### Wind unit conversion

| Check | Result |
|-------|--------|
| Source unit | knots (`*_wind_kts`) |
| Target unit | km/h |
| Conversion factor | × 1.852 |
| Resulting range | 19.45 .. 57.41 km/h |
| Plausible? | ✅ Yes (passes quality check #8) |

### Wave height

| Check | Result |
|-------|--------|
| Source unit | metres (`*_wave_hs_m`, significant wave height) |
| Target unit | metres |
| Conversion | none (already correct) |
| Resulting range | 1.10 .. 4.30 m |
| Plausible? | ✅ Yes (passes quality check #10) |

### Route-specific weather column selection

| Origin | Wind column used | Wave column used |
|--------|-----------------|------------------|
| Taboneo | `taboneo_wind_kts` | `taboneo_wave_hs_m` |
| Australia East Coast → Hay Point | `aus_east_wind_kts` | `aus_east_wave_hs_m` |
| Australia West Coast | `aus_west_wind_kts` | `aus_west_wave_hs_m` |

Selection from existing observed values — not fabrication.

### `weather_monthly_all_locations_2024_2025.csv` NOT used

Per the audit, this file's aggregation does NOT match FFT's weather columns
(ratio ≈ 0.62, not the 1.852 km/h-per-knot ratio expected if they were the
same series rescaled). It also has no wave-height column. Therefore it is
NOT used to source `wind_kmh`, `wave_height_m`, `cyclone_risk`, or
`weather_delay_days`.

---

## 18. cargo_tonnes assumption

`cargo_tonnes` is **missing from every uploaded CSV file**. We use
**representative vessel capacities** (not random, not observed fixtures):

| Vessel type | Representative cargo (tonnes) | Rows affected |
|-------------|------------------------------|---------------|
| Panamax | 75,000 | 44 |
| Supramax | 55,000 | 22 |
| Capesize | 170,000 | 44 |

Every master row carries `cargo_value_type = "representative_vessel_capacity"`
so downstream code knows these are NOT observed fixture quantities.

**Full rationale:** see `data/MASTER_DATASET_ASSUMPTIONS.md` §1.

---

## 19. Exact categorical vocabulary (for the new model)

| Dimension | Values |
|-----------|--------|
| origins (3) | `Australia West Coast`, `Hay Point`, `Taboneo` |
| destinations (1) | `East Coast India` |
| commodities (3) | `Coal`, `Iron Ore`, `Thermal Coal` |
| vessel_types (3) | `Capesize`, `Panamax`, `Supramax` |

The future retrained model's `OneHotEncoder` should be fit on these values
(with `handle_unknown='ignore'` recommended so unseen values at inference
time are gracefully handled).

---

## 20. Quality checks — 11/11 passed ✅

| # | Check | Result | Detail |
|---|-------|--------|--------|
| 1 | No duplicate `(date, origin, destination, commodity, vessel_type)` keys | ✅ PASS | duplicate keys=0 |
| 2 | Every target = next month's freight (same route/commodity/vessel) | ✅ PASS | checked=105 mismatches=0 |
| 3 | No target-derived lag columns in features | ✅ PASS | `previous_month_freight`, `freight_3_month_avg`, `freight_observation_count` all absent |
| 4 | No validation rows in training | ✅ PASS | validation file never read by builder |
| 5 | No benchmark duplicate rows | ✅ PASS | 110 benchmark duplicates excluded |
| 6 | All 14 model inputs present | ✅ PASS | missing=[] |
| 7 | No missing values in feature/target columns | ✅ PASS | nulls_per_col={} |
| 8 | All wind values in km/h | ✅ PASS | wind_kmh range=19.45..57.41 |
| 9 | All freight values in USD/tonne | ✅ PASS | freight range=8.50..21.20 |
| 10 | All wave values in metres | ✅ PASS | wave range=1.10..4.30 |
| 11 | Expanded categorical vocabulary (≥2 each) | ✅ PASS | origins=3 commodities=3 vessels=3 |

---

## 21. Model readiness analysis (STEP 12)

### Multiple routes? ✅ Yes

3 origins × 1 destination = 3 routes.

### Multiple commodities? ✅ Yes

`Coal`, `Thermal Coal`, `Iron Ore` (3 commodities).

### Multiple vessel classes? ✅ Yes

`Panamax`, `Supramax`, `Capesize` (3 vessel types).

### Temporal observations per (origin, destination, commodity, vessel_type) combination

| origin | destination | commodity | vessel_type | rows |
|--------|-------------|-----------|-------------|------|
| Australia West Coast | East Coast India | Iron Ore | Capesize | 22 |
| Hay Point | East Coast India | Coal | Capesize | 22 |
| Hay Point | East Coast India | Coal | Panamax | 22 |
| Taboneo | East Coast India | Thermal Coal | Panamax | 22 |
| Taboneo | East Coast India | Thermal Coal | Supramax | 22 |

- **5 unique combinations**, each with exactly **22 monthly observations**
- min obs per combo: 22
- max obs per combo: 22

### Readiness assessment

| Criterion | Status |
|-----------|--------|
| Multiple routes | ✅ |
| Multiple commodities | ✅ |
| Multiple vessel classes | ✅ |
| Sufficient temporal observations per combination (22 each) | ✅ |
| All 14 model inputs available | ✅ |
| Target alignment verified | ✅ |
| No missing values | ✅ |
| No leakage (lag/metadata excluded) | ✅ |
| No validation contamination | ✅ |
| No benchmark duplicate contamination | ✅ |

**The expanded dataset is structurally ready for a new model.**

### Recommended training considerations (NOT executed — out of scope)

- Use **group-aware cross-validation** (group by route/commodity/vessel) so
  all 22 months of a combination stay together in either train or test — this
  prevents temporal leakage within a combination.
- Consider whether 22 observations per combination is sufficient; a
  RandomForest with 250 trees may overfit. Consider regularisation or a
  simpler model (e.g. GradientBoosting with shallow trees) if performance
  is poor.
- The destination is region-level (`East Coast India`); the new model will
  inherit this granularity.
- `cargo_tonnes` is constant within each vessel class; the model cannot
  learn intra-class cargo effects.

---

## 22. Source mapping (per feature)

| Feature | Source | Transformation |
|---------|--------|----------------|
| `date` | FFT.`date` | direct (ISO format) |
| `origin` | FFT.`route` (left of ` -> `) | region→port mapping: `Australia East Coast → Hay Point`; `Taboneo` and `Australia West Coast` kept as-is |
| `destination` | FFT.`route` (right of ` -> `) | direct (region-level preserved) |
| `commodity` | FFT.`commodity` | direct (Thermal Coal / Iron Ore / Coal kept) |
| `vessel_type` | FFT.`vessel_type` | direct (Capesize / Panamax / Supramax kept) |
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

---

## 23. Output files

| Path | Purpose | Rows |
|------|---------|------|
| `data/master_freight_training_expanded_v1.csv` | **Expanded retraining-ready master dataset** | 110 |
| `data/MASTER_DATASET_ASSUMPTIONS.md` | All assumptions documented (covers both narrow + expanded builds) | — |
| `data/master_freight_training_expanded_report.md` | This report | — |
| `data/excluded_expanded/boundary_benchmark_rows.csv` | Boundary benchmark rows (reference only) | 10 |
| `build_master_dataset_expanded.py` | Reproducible build script | — |

---

## 24. Limitations and caveats

1. **5 combinations, each with 22 monthly observations.** Sufficient for
   per-combination learning, but a 22-month span limits the model's ability
   to capture multi-year market cycles.
2. **`cargo_tonnes` is representative, not observed.** Constant within each
   vessel class — the retrained model cannot learn cargo-size effects within
   a class.
3. **Destination is region-level** (`East Coast India`), not port-level
   (`Paradip`/`Visakhapatnam`). The new model will inherit this granularity.
4. **Origin `Australia West Coast` is a single-region aggregate.** It does
   not distinguish specific West-Australian ports (e.g. Port Hedland,
   Geraldton). This is a known limitation of FFT.
5. **`corr(current_freight, target) = 0.8567`** — high correlation. The new
   model will likely rely heavily on `current_freight` (like the existing
   model, which had 93.6% importance on this feature). This is a structural
   property of the data, not a bug.

---

## 25. What was NOT done (per strict rules)

- ❌ `freight_forecast_model_v1.joblib` — **not modified** (sha256 verified: `695fafe3f31b560d5a4412124c0839e0e622c9d2bd090191a5e02eaef6c3819a`).
- ❌ No retraining was performed.
- ❌ No new `.joblib` file was created.
- ❌ The FastAPI prediction code was **not altered**.
- ❌ The validation file (`real_route_validation_predictions_v1.csv`) was
  **never read** by the builder.
- ❌ No synthetic market / weather / freight / target values were generated.
- ❌ No benchmark duplicate rows were added to training.
- ❌ No silent renaming of `Thermal Coal` → `Coal` or `Capesize` → other class.
- ❌ No silent mapping of `Australia West Coast` → `Hay Point`.

---

## 26. STOP

The expanded master dataset is built. The build stops here.

**Next step (when you choose to proceed):** retrain a new model on
`data/master_freight_training_expanded_v1.csv` with the expanded categorical
vocabulary. The existing `freight_forecast_model_v1.joblib` should be
preserved, and the new model should be saved to a different filename
(e.g. `freight_forecast_model_v2.joblib`).

*End of report.*
