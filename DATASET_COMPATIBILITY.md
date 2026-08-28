# DATASET COMPATIBILITY AUDIT

> **Status:** Audit only. No data merged, no values filled, no model modified,
> no retraining performed.
>
> **Date of audit:** 2026-08-27
> **Auditor:** Z.ai Code (automated)
> **Repository:** https://github.com/junaid693/Freight---bulk-Cargo
> **Branch:** `audit/data-pipeline`

---

## Executive Summary

⚠️ **The repository contains ZERO dataset files.**

There are no CSV, Excel, JSON, Parquet, or other tabular data files in the
repository. The only "data" present is:

1. A trained scikit-learn model binary (`freight_forecast_model_v1.joblib`,
   20 MB) — contains **no** training data, only fitted parameters.
2. A runtime SQLite database (`backend/data/freight.db`) — **git-ignored**,
   **empty** on a fresh clone (0 rows in every table). It is a snapshot cache,
   not a historical store.
3. Backend code that **could** fetch *current* weather from Open-Meteo (live
   only) and defines a **placeholder** interface for paid market data.

**Consequence:** A master dataset for retraining **does not yet exist and
cannot be assembled from the current repository contents alone**. To build
one we need to either obtain historical data from external sources or collect
it over time. This report documents exactly what is available, what is
missing, and proposes the target schema so the next step is unambiguous.

---

## Table of Contents

1. [Model Feature Schema](#1-model-feature-schema)
2. [Data Source Inventory](#2-data-source-inventory)
3. [Per-Source Detailed Audit](#3-per-source-detailed-audit)
4. [Feature-by-Feature Coverage Matrix](#4-feature-by-feature-coverage-matrix)
5. [Join Analysis](#5-join-analysis)
6. [Frequency & Date Alignment](#6-frequency--date-alignment)
7. [Gaps, Risks & Constraints](#7-gaps-risks--constraints)
8. [Proposed Master Dataset Schema](#8-proposed-master-dataset-schema)
9. [Recommended Next Steps (NOT executed)](#9-recommended-next-steps-not-executed)

---

## 1. Model Feature Schema

Re-extracted directly from the model artifact at audit time
(`model.feature_names_in_`):

| # | Feature | Type | Category | Role |
|---|---------|------|----------|------|
| 1 | `origin` | categorical | route identity | input |
| 2 | `destination` | categorical | route identity | input |
| 3 | `commodity` | categorical | route identity | input |
| 4 | `vessel_type` | categorical | route identity | input |
| 5 | `cargo_tonnes` | numeric | cargo | input |
| 6 | `bdi` | numeric | market | input |
| 7 | `vlsfo_usd_per_tonne` | numeric | market (bunker) | input |
| 8 | `coal_price_usd_per_mt` | numeric | market (commodity) | input |
| 9 | `iron_ore_price_usd_per_dmt` | numeric | market (commodity) | input |
| 10 | `wind_kmh` | numeric | weather | input |
| 11 | `wave_height_m` | numeric | weather | input |
| 12 | `cyclone_risk` | numeric | weather (derived) | input |
| 13 | `weather_delay_days` | numeric | weather (derived) | input |
| 14 | `current_freight_usd_per_tonne` | numeric | freight | input |
| — | `next_month_freight_usd_per_tonne` | numeric | freight | **target** |

### Training-distribution categories (inferred from one-hot feature names)

Because the `OneHotEncoder` was fit with `handle_unknown='ignore'`, the
model will technically accept unseen categories, but it has **no learned
weights for any value outside this set**:

| Feature | Values seen during training |
|---------|------------------------------|
| `origin` | `Hay Point`, `Taboneo` (2) |
| `destination` | `Paradip`, `Visakhapatnam` (2) |
| `commodity` | `Coal`, `Iron Ore` (2) |
| `vessel_type` | `Panamax`, `Supramax` (2) |

→ **4 routes × 2 commodities × 2 vessel types = up to 16 route/commodity/vessel
combinations** are within the training distribution. Anything else is an
out-of-distribution prediction.

### Feature importance (top 5)

| Rank | Feature | Importance | Note |
|------|---------|-----------|------|
| 1 | `current_freight_usd_per_tonne` | **0.9365** | dominates the prediction |
| 2 | `iron_ore_price_usd_per_dmt` | 0.0276 | |
| 3 | `cyclone_risk` | 0.0070 | |
| 4 | `coal_price_usd_per_mt` | 0.0052 | |
| 5 | `wave_height_m` | 0.0043 | |

> The model is essentially a "current rate ≈ next month rate" baseline with
> small corrections. This is a strong signal that the training data may have
> been thin / synthetic — but that is a question for the retraining step,
> not this audit.

---

## 2. Data Source Inventory

Full file inventory of the repository (after `git clone`):

| Path | Type | Size | Rows | Contains data? |
|------|------|------|------|---------------|
| `freight_forecast_model_v1.joblib` | sklearn Pipeline (binary) | 20 MB | n/a | **No** — fitted params only, no training rows |
| `README.md` | markdown | 19 KB | 537 lines | **No** — docs only (port coords, field tables) |
| `backend/main.py` | Python | 4.6 KB | 140 lines | No — FastAPI app |
| `backend/predict.py` | Python | 4.2 KB | 134 lines | No — model wrapper |
| `backend/schemas.py` | Python | 6.8 KB | 175 lines | No — Pydantic models |
| `backend/test_example.py` | Python | 1.6 KB | 62 lines | No — example request |
| `backend/requirements.txt` | text | 49 B | 6 lines | No — deps list |
| `backend/data/__init__.py` | Python | 16 B | 1 line | No |
| `backend/data/database.py` | Python | 8.5 KB | 245 lines | No — SQLite schema + CRUD |
| `backend/data/weather.py` | Python | 6.6 KB | 185 lines | No — Open-Meteo fetcher |
| `backend/data/market.py` | Python | 2.8 KB | 81 lines | No — placeholder provider |
| `backend/data/update_data.py` | Python | 5.3 KB | 155 lines | No — CLI updater |
| `backend/services/__init__.py` | Python | 16 B | 1 line | No |
| `backend/services/forecast_service.py` | Python | 5.7 KB | 167 lines | No — merge logic |
| `.gitignore` | text | 0.8 KB | 19 lines | No |

**External (runtime) data sources referenced by code:**

| Source | URL | Auth | Historical? | Used for |
|--------|-----|------|------------|----------|
| Open-Meteo Forecast API | `api.open-meteo.com/v1/forecast` | none | **No** (current only) | wind, temperature |
| Open-Meteo Marine API | `marine-api.open-meteo.com/v1/marine` | none | **No** (current only) | wave height |
| Open-Meteo Archive API | `archive-api.open-meteo.com/v1/archive` | none | **Yes** ✅ | (used as fallback only) |
| Market data provider | *(pluggable)* | varies | varies | BDI, bunker, coal, iron ore |
| Freight observations | *(manual insert)* | n/a | n/a | current freight rate |

---

## 3. Per-Source Detailed Audit

### Source A — Model artifact `freight_forecast_model_v1.joblib`

| Attribute | Value |
|-----------|-------|
| Type | `sklearn.pipeline.Pipeline` |
| Steps | `prep` (ColumnTransformer) → `model` (RandomForestRegressor) |
| `feature_names_in_` | 14 features (see §1) |
| Final estimator | `RandomForestRegressor(n_estimators=250, max_depth=10, random_state=42)` |
| `n_features_in_` (post-transform) | 18 (8 one-hot + 10 numeric) |
| Embedded X_train / y_train? | **No** — all `None` |
| Training data recoverable? | **No** |
| Pickled with sklearn | 1.8.0 (per `InconsistentVersionWarning`) |
| Runtime sklearn | 1.5.2 |
| Geographic coverage | 2 origins, 2 destinations (see §1) |
| Date range of training | **Unknown** (not stored) |
| Frequency of training data | **Unknown** (not stored) |
| sha256 (integrity) | `695fafe3f31b560d5a4412124c0839e0e622c9d2bd090191a5e02eaef6c3819a` |

**Conclusion:** the model confirms the feature schema and the categorical
domain, but contributes **zero rows** of training data.

---

### Source B — SQLite database `backend/data/freight.db`

| Attribute | Value |
|-----------|-------|
| Git-tracked? | **No** (`.gitignore`'d) |
| Present on fresh clone? | **No** — created at runtime by `init_db()` |
| Row count (fresh init) | 0 in every table |
| Designed for | latest-snapshot caching, **not** historical time series |

Schema (4 tables):

#### `weather_data` — one row per (port, fetched_at) snapshot
| Column | Type | Nullable | Note |
|--------|------|----------|------|
| `id` | INTEGER PK | | autoincrement |
| `port` | TEXT | not null | |
| `latitude` | REAL | not null | |
| `longitude` | REAL | not null | |
| `wind_kmh` | REAL | nullable | |
| `wave_height_m` | REAL | nullable | |
| `cyclone_risk` | REAL | nullable | derived |
| `weather_delay_days` | REAL | nullable | derived |
| `temperature_c` | REAL | nullable | |
| `fetched_at` | TEXT | not null | ISO-8601 UTC |
| Index | `idx_weather_port_time(port, fetched_at)` | | |
| **Missing for master dataset** | **no `date` column** (only `fetched_at`) | | snapshot semantics |

#### `market_data` — one row per (series, fetched_at) quote
| Column | Type | Nullable | Note |
|--------|------|----------|------|
| `id` | INTEGER PK | | |
| `series` | TEXT | not null | `bdi`, `vlsfo_usd_per_tonne`, etc. |
| `value` | REAL | nullable | |
| `unit` | TEXT | nullable | |
| `source` | TEXT | nullable | |
| `fetched_at` | TEXT | not null | |
| Index | `idx_market_series_time(series, fetched_at)` | | |
| **Missing for master dataset** | **no `date` column** | | snapshot, not time series |

#### `freight_observations` — one row per historical freight rate observation
| Column | Type | Nullable | Note |
|--------|------|----------|------|
| `id` | INTEGER PK | | |
| `origin` | TEXT | not null | |
| `destination` | TEXT | not null | |
| `commodity` | TEXT | not null | |
| `vessel_type` | TEXT | not null | |
| `cargo_tonnes` | REAL | nullable | |
| `current_freight_usd_per_tonne` | REAL | not null | |
| `observed_at` | TEXT | not null | |
| Index | `idx_freight_route(origin, destination, commodity, vessel_type, observed_at)` | | |
| **Has a date column (`observed_at`)** — best aligned table so far | | | |

#### `data_status` — per-category last_updated
| Column | Type |
|--------|------|
| `category` (PK) | TEXT |
| `last_updated` | TEXT |

**Conclusion:** the SQLite DB is empty and structurally a snapshot cache. It
cannot serve as a master training dataset without schema changes (adding a
proper `date` column to weather/market tables) **and** a backfill of
historical values. The `freight_observations` table is the only one with a
date column, but it is also empty.

---

### Source C — Open-Meteo API (live)

The code currently fetches **only current conditions**:

| Variable fetched | API | Endpoint | Unit | Historical available? |
|------------------|-----|----------|------|----------------------|
| `wind_speed_10m` | Forecast | `current=wind_speed_10m` | km/h | archive API has `wind_speed_10m_max` (daily) ✅ |
| `temperature_2m` | Forecast | `current=temperature_2m` | °C | archive API has `temperature_2m_mean` (daily) ✅ |
| `wave_height` | Marine | `current=wave_height` | m | marine archive has `wave_height_max` (daily) ✅ |

**Verified during audit:** the Open-Meteo **archive API** CAN return daily
historical weather (verified for `Hay Point`, 2024-01-01 to 2024-01-07):
```
wind_speed_10m_max: [14.1, 14.0, 13.2, 12.6, 16.2, ...]  # km/h, daily
wave_height_max:    [0.40, 0.22, ...]                      # m, daily
```

> The historical archive reaches back several years (Open-Meteo docs say
> typically to ~1940 / 1958 depending on variable). **Historical weather
> for the 4 supported ports is therefore obtainable** — but it is not
> currently fetched or stored by the backend.

**Ports with coordinates in code:**

| Port | Lat | Lon | Region |
|------|-----|-----|--------|
| Hay Point | -21.37 | 149.32 | Queensland, Australia |
| Taboneo | -3.65 | 114.85 | South Kalimantan, Indonesia |
| Visakhapatnam | 17.68 | 83.27 | Andhra Pradesh, India |
| Paradip | 20.32 | 86.70 | Odisha, India |

**Derived features (transparent formulas in `weather.py`, NOT fabricated):**
```
cyclone_risk       = clamp(wind_kmh / 30, 0, 5)
weather_delay_days = max(0, wave_height_m - 1.5) * 0.5   (+0.25 if wind > 40 km/h)
```

---

### Source D — Market data provider (placeholder)

`backend/data/market.py` defines an abstract `MarketDataProvider` protocol
and a `PlaceholderMarketDataProvider` that returns `None` for every series.

**Series defined (matches model features):**

| Series key | Label | Unit |
|-----------|-------|------|
| `bdi` | Baltic Dry Index | index points |
| `vlsfo_usd_per_tonne` | VLSFO bunker fuel | USD/tonne |
| `coal_price_usd_per_mt` | Coal benchmark | USD/MT |
| `iron_ore_price_usd_per_dmt` | Iron ore benchmark | USD/dmt |

**Conclusion:** clean interface exists, but **no real provider is wired up**
and there is **no free, keyless API** for these series. They require paid
subscriptions (Baltic Exchange, Signal Group, Platts, etc.). No data has
been or will be fabricated.

---

## 4. Feature-by-Feature Coverage Matrix

For each of the 14 model features + the target, what is the current
availability of a **historical** value (what a master dataset needs)?

| # | Feature | In model? | In SQLite schema? | Historical source available? | Status |
|---|---------|-----------|-------------------|------------------------------|--------|
| 1 | `origin` | ✅ | ✅ (`weather_data.port`, `freight_observations.origin`) | route identity, not time series | ✅ direct (categorical) |
| 2 | `destination` | ✅ | ✅ (`freight_observations.destination`) | route identity | ✅ direct (categorical) |
| 3 | `commodity` | ✅ | ✅ (`freight_observations.commodity`) | route identity | ✅ direct (categorical) |
| 4 | `vessel_type` | ✅ | ✅ (`freight_observations.vessel_type`) | route identity | ✅ direct (categorical) |
| 5 | `cargo_tonnes` | ✅ | ✅ (`freight_observations.cargo_tonnes`, nullable) | per-shipment, not time series | ⚠️ per-observation |
| 6 | `bdi` | ✅ | ✅ (`market_data` where `series='bdi'`) | **none configured** (paid) | ❌ **unavailable** |
| 7 | `vlsfo_usd_per_tonne` | ✅ | ✅ (`market_data`) | **none configured** (paid) | ❌ **unavailable** |
| 8 | `coal_price_usd_per_mt` | ✅ | ✅ (`market_data`) | **none configured** (paid) | ❌ **unavailable** |
| 9 | `iron_ore_price_usd_per_dmt` | ✅ | ✅ (`market_data`) | **none configured** (paid) | ❌ **unavailable** |
| 10 | `wind_kmh` | ✅ | ✅ (`weather_data.wind_kmh`) | ✅ Open-Meteo archive API (daily) | ⚠️ transform needed (daily max → representative) |
| 11 | `wave_height_m` | ✅ | ✅ (`weather_data.wave_height_m`) | ✅ Open-Meteo marine archive (daily) | ⚠️ transform needed (daily max → representative) |
| 12 | `cyclone_risk` | ✅ | ✅ (`weather_data.cyclone_risk`, derived) | derivable from wind via formula | ⚠️ transform: `clamp(wind/30,0,5)` |
| 13 | `weather_delay_days` | ✅ | ✅ (`weather_data.weather_delay_days`, derived) | derivable from wave+wind | ⚠️ transform: formula |
| 14 | `current_freight_usd_per_tonne` | ✅ | ✅ (`freight_observations.current_freight_usd_per_tonne`) | **no historical source** | ❌ **unavailable** (manual entry only) |
| — | `next_month_freight_usd_per_tonne` (target) | ✅ (target) | ❌ not stored | **no historical source** | ❌ **unavailable** |

### Summary

- **5 features** (route identity + cargo) are directly available — they are
  categorical or per-shipment, not time series.
- **4 features** (weather: wind, wave, cyclone_risk, weather_delay_days) are
  *transform-derivable* from the Open-Meteo archive API — needs a backfill ETL.
- **5 features + the target** (BDI, bunker, 2 commodity prices, current
  freight, next-month freight) are **completely unavailable** in any current
  or planned free source.

---

## 5. Join Analysis

### What could be joined today (in principle)

If we had historical data for each source, the natural grain of the master
dataset is **(date, origin, destination, commodity, vessel_type)**. The
join keys per source:

| Source | Grain | Join keys | Can join to master? |
|--------|-------|-----------|---------------------|
| Weather archive (Open-Meteo) | `(date, port)` | `date` + (`origin`→port or `destination`→port) | ✅ on origin port's date |
| Market data | `(date, series)` | `date` only (global per day) | ✅ on `date` |
| Freight observations | `(observed_at, origin, destination, commodity, vessel_type)` | full route key + date | ✅ direct |
| Target (`next_month_freight`) | `(date + 1 month, route, commodity, vessel_type)` | shifted date + route key | ✅ (needs lead shift) |

### Join keys for the master dataset

```
master_row = (
    date,                                  -- calendar date (daily grain)
    origin,                                -- e.g. "Hay Point"
    destination,                           -- e.g. "Visakhapatnam"
    commodity,                             -- e.g. "Coal"
    vessel_type                            -- e.g. "Panamax"
)
```

- **Weather** joins on `(date, origin)` — i.e. the loading port's weather
  on that date. (Could also add destination-port weather as extra columns.)
- **Market** joins on `date` only — BDI/bunker/commodity prices are global
  per day, not per route.
- **Freight observations** join on the full 5-key route + date.
- **Target** = `current_freight_usd_per_tonne` shifted forward by ~1 month
  (or the next available observation for the same route), per the model's
  intent of "next-month freight".

### What cannot be joined today

Anything that does not exist. Specifically, none of the joins above can be
materialized because no source table has historical rows yet.

---

## 6. Frequency & Date Alignment

| Source | Native frequency | Master target frequency | Alignment issue |
|--------|-----------------|-------------------------|-----------------|
| Open-Meteo weather archive | daily | daily | none |
| Marine wave archive | daily | daily | none |
| BDI | daily (trading days) | daily | forward-fill weekends/holidays |
| VLSFO / commodity prices | daily (trading days) | daily | forward-fill weekends/holidays |
| Freight observations | irregular (per fixture) | daily | **re-sample or pick representative rate per route-month** |
| Target `next_month_freight` | monthly intent | daily-grain rows | **lead-shift by ~30 days** |

**Critical alignment risk:** the model appears to have been trained with a
"this month's rate → next month's rate" framing (the target name is
`next_month_freight_usd_per_tonne` and `current_freight` dominates
importance at 93.6%). This suggests the original training grain may have
been **monthly per route**, not daily. **The exact training grain is
unknown** because no training data is present. This must be clarified
before retraining.

---

## 7. Gaps, Risks & Constraints

### Hard gaps (no data exists)
1. **No training dataset** for the existing model — cannot reproduce or
   validate the current model's training.
2. **No historical BDI** values.
3. **No historical bunker (VLSFO) prices**.
4. **No historical coal / iron-ore benchmark prices**.
5. **No historical freight rate observations** (current or next-month).
6. **No historical weather stored** in SQLite — only the latest snapshot
   would exist after a fetch.

### Schema gaps (SQLite not ready for historical ETL)
7. `weather_data` and `market_data` have **no `date` column** — only
   `fetched_at`. To store historical series, a `date` (calendar date of
   the observation) column distinct from `fetched_at` (when we stored it)
   is needed.
8. No `freight_rate_history` table with a future `next_month_freight`
   column for the target.

### Domain coverage gaps
9. Training distribution covers only 2×2×2×2 = 16 route/commodity/vessel
   combinations. Any retraining on a wider port set would need the model
   to handle new one-hot categories (currently `handle_unknown='ignore'`
   means new categories silently get zero encoding).
10. No `Capesize` vessel type in training; no routes outside the 4 ports.

### Integrity risks
11. Model was pickled with sklearn 1.8.0; runtime is 1.5.2 —
    `InconsistentVersionWarning`. Predictions still work but the version
    mismatch should be resolved before retraining.
12. The `cyclone_risk` and `weather_delay_days` features in the original
    training data may have been defined differently from the transparent
    formulas currently in `weather.py`. Without the training data we
    cannot confirm the formulas match. **Risk of distribution shift.**

### Out-of-scope (this audit)
- Merging datasets
- Filling missing values
- Retraining the model
- Creating synthetic data

---

## 8. Proposed Master Dataset Schema

One row = one observation of a freight forecast scenario:

```
(date, origin, destination, commodity, vessel_type) → features + target
```

### Columns (proposed, NOT yet created)

| Column | Type | Source | Derivation |
|--------|------|--------|------------|
| `date` | DATE | calendar | the observation date (monthly or daily, TBD) |
| `origin` | TEXT | route identity | direct |
| `destination` | TEXT | route identity | direct |
| `commodity` | TEXT | route identity | direct |
| `vessel_type` | TEXT | route identity | direct |
| `cargo_tonnes` | REAL | freight observation | direct (per fixture) or representative |
| `bdi` | REAL | market provider | lookup by `date` |
| `vlsfo_usd_per_tonne` | REAL | market provider | lookup by `date` |
| `coal_price_usd_per_mt` | REAL | market provider | lookup by `date` |
| `iron_ore_price_usd_per_dmt` | REAL | market provider | lookup by `date` |
| `wind_kmh` | REAL | Open-Meteo archive | daily value for `origin` port on `date` |
| `wave_height_m` | REAL | Open-Meteo marine archive | daily value for `origin` port on `date` |
| `cyclone_risk` | REAL | derived | `clamp(wind_kmh / 30, 0, 5)` |
| `weather_delay_days` | REAL | derived | `max(0, wave_height_m - 1.5) * 0.5 (+0.25 if wind>40)` |
| `current_freight_usd_per_tonne` | REAL | freight observation | direct on `date` |
| `next_month_freight_usd_per_tonne` | REAL | freight observation | lead-shifted ~30 days, same route — **TARGET** |
| `data_source` | TEXT | audit metadata | which provider contributed each row |
| `ingested_at` | TIMESTAMP | audit metadata | when the row was added |

### Grain

- **Preferred:** monthly per `(origin, destination, commodity, vessel_type)`
  — matches the model's apparent training framing ("next-month freight").
- **Alternative:** daily per route, aggregated to monthly for training. More
  flexible but more storage and joins.

### Uniqueness / dedup key

```
PRIMARY KEY (date, origin, destination, commodity, vessel_type)
```

---

## 9. Recommended Next Steps (NOT executed)

Listed in dependency order. **None of these are performed in this audit.**

1. **Decide the target grain** (monthly vs daily) based on the model's
   original training framing. Document the decision.
2. **Resolve the market-data source question.** Either:
   - (a) Obtain a paid subscription for BDI / bunker / commodity prices, or
   - (b) Decide to drop those features from a future retrained model, or
   - (c) Use a documented public proxy (e.g. ETF / futures proxies) with
     explicit labelling — **only if** the user approves.
3. **Resolve the freight-rate source question.** Historical fixture data is
   typically paid (Clarksons, Sea/intel, etc.).
4. **Extend the SQLite schema** (or create a new `master_dataset` table)
   with a `date` column on weather/market tables and a target column.
5. **Build a historical weather backfill** using the Open-Meteo archive API
   (already verified feasible) for the 4 ports over the desired date range.
6. **Derive `cyclone_risk` and `weather_delay_days`** from the backfilled
   wind/wave using the documented formulas.
7. **Join** all sources on `(date, route, commodity, vessel_type)` into the
   master table — only after steps 2-6 produce real rows.
8. **Do not fill missing values** until the join is complete and the missing
   pattern is understood.
9. **Do not retrain** until the master dataset has enough complete rows to
   beat the current model's implicit baseline.

---

## Audit Artefacts

- This report: `DATASET_COMPATIBILITY.md`
- No other files were created or modified during this audit.
- The model file `freight_forecast_model_v1.joblib` was loaded **read-only**
  for metadata extraction. Its sha256 hash is unchanged:
  `695fafe3f31b560d5a4412124c0839e0e622c9d2bd090191a5e02eaef6c3819a`
- The SQLite DB created during the audit (`backend/data/freight.db`) is
  git-ignored and was left empty.

---

## Appendix — Commands used to produce this audit

```bash
# Model metadata
python3 -c "import joblib; m=joblib.load('freight_forecast_model_v1.joblib'); print(m.feature_names_in_)"

# SQLite schema
python3 -c "from data import database; database.init_db()"   # creates empty DB
sqlite3 backend/data/freight.db ".schema"

# Open-Meteo archive capability check
curl "https://archive-api.open-meteo.com/v1/archive?latitude=-21.37&longitude=149.32&start_date=2024-01-01&end_date=2024-01-07&daily=wind_speed_10m_max"

# File inventory
git ls-files
find . -type f -not -path './.git/*' -size +1k
```
