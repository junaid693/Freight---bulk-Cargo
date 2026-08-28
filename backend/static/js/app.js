/**
 * Freight Intelligence Platform — Application Controller
 * High-Density Maritime Analytics & Model v3 Decision Engine
 */

import { API } from "./api.js";
import { Charts } from "./charts.js";

// Canonical 5 Trade Lanes Definition
const CANONICAL_LANES = [
  {
    id: "lane-1",
    origin: "Australia West Coast",
    destination: "East Coast India",
    commodity: "Iron Ore",
    vessel_type: "Capesize",
    defaultFreight: 12.90,
    label: "Australia West Coast → East Coast India (Iron Ore / Capesize)",
  },
  {
    id: "lane-2",
    origin: "Hay Point",
    destination: "East Coast India",
    commodity: "Coal",
    vessel_type: "Capesize",
    defaultFreight: 17.20,
    label: "Hay Point → East Coast India (Coal / Capesize)",
  },
  {
    id: "lane-3",
    origin: "Hay Point",
    destination: "East Coast India",
    commodity: "Coal",
    vessel_type: "Panamax",
    defaultFreight: 20.00,
    label: "Hay Point → East Coast India (Coal / Panamax)",
  },
  {
    id: "lane-4",
    origin: "Taboneo",
    destination: "East Coast India",
    commodity: "Thermal Coal",
    vessel_type: "Panamax",
    defaultFreight: 11.80,
    label: "Taboneo → East Coast India (Thermal Coal / Panamax)",
  },
  {
    id: "lane-5",
    origin: "Taboneo",
    destination: "East Coast India",
    commodity: "Thermal Coal",
    vessel_type: "Supramax",
    defaultFreight: 13.80,
    label: "Taboneo → East Coast India (Thermal Coal / Supramax)",
  },
];

// App State
const state = {
  currentRoute: "overview",
  selectedLaneIndex: 2, // Default Hay Point / Coal / Panamax
  overviewData: null,
  routesData: null,
  marketData: null,
  weatherData: null,
  latestForecast: null,
  scenarioResult: null,
};

// Initialize Application
document.addEventListener("DOMContentLoaded", () => {
  initRouter();
  initLaneSelectors();
  initForecastForm();
  initScenarioForm();
  initGlobalEvents();

  // Load initial route
  handleNavigation(window.location.hash.replace("#", "") || "overview");
});

// Router & View Switcher
function initRouter() {
  window.addEventListener("hashchange", () => {
    const route = window.location.hash.replace("#", "") || "overview";
    handleNavigation(route);
  });

  document.querySelectorAll(".nav-item a").forEach((link) => {
    link.addEventListener("click", (e) => {
      e.preventDefault();
      const targetRoute = link.getAttribute("data-route");
      window.location.hash = targetRoute;
    });
  });
}

function handleNavigation(route) {
  state.currentRoute = route;

  // Update Nav Active State
  document.querySelectorAll(".nav-item").forEach((item) => {
    const link = item.querySelector("a");
    if (link && link.getAttribute("data-route") === route) {
      item.classList.add("active");
    } else {
      item.classList.remove("active");
    }
  });

  // Switch Screen Visibility
  document.querySelectorAll(".screen-container").forEach((el) => {
    el.classList.remove("active");
  });

  const activeScreen = document.getElementById(`screen-${route}`);
  if (activeScreen) {
    activeScreen.classList.add("active");
  }

  // Update Topbar Title
  const titleMap = {
    overview: "Overview Dashboard",
    forecast: "Freight Forecast Engine",
    scenario: "What-If Scenario Simulation",
    routes: "Route Intelligence & Benchmarks",
    market: "Market Intelligence & Macro Trends",
    weather: "Weather Intelligence & Maritime Risk",
    sources: "Data Provenance & Model Validation",
  };
  const titleEl = document.getElementById("topbar-page-title");
  if (titleEl) titleEl.textContent = titleMap[route] || "Freight Intelligence";

  // Load Screen Data
  loadScreenData(route);
}

async function loadScreenData(route) {
  switch (route) {
    case "overview":
      await loadOverview();
      break;
    case "forecast":
      await loadForecastScreen();
      break;
    case "scenario":
      await loadScenarioScreen();
      break;
    case "routes":
      await loadRoutesScreen();
      break;
    case "market":
      await loadMarketScreen();
      break;
    case "weather":
      await loadWeatherScreen();
      break;
    case "sources":
      await loadSourcesScreen();
      break;
  }
}

// Global Lane Selector Dropdowns
function initLaneSelectors() {
  const topbarSelect = document.getElementById("topbar-route-select");
  if (topbarSelect) {
    topbarSelect.innerHTML = CANONICAL_LANES.map(
      (lane, idx) => `<option value="${idx}">${lane.label}</option>`
    ).join("");

    topbarSelect.value = state.selectedLaneIndex;
    topbarSelect.addEventListener("change", (e) => {
      state.selectedLaneIndex = Number(e.target.value);
      syncLaneAcrossForms();
      if (state.currentRoute === "routes") loadRoutesScreen();
    });
  }
}

function syncLaneAcrossForms() {
  const lane = CANONICAL_LANES[state.selectedLaneIndex];
  if (!lane) return;

  // Sync Forecast Form
  const fcLaneSelect = document.getElementById("fc-lane-select");
  if (fcLaneSelect) fcLaneSelect.value = state.selectedLaneIndex;

  const fcFreight = document.getElementById("fc-current-freight");
  if (fcFreight) fcFreight.value = lane.defaultFreight.toFixed(2);

  // Sync Scenario Form
  const scLaneSelect = document.getElementById("sc-lane-select");
  if (scLaneSelect) scLaneSelect.value = state.selectedLaneIndex;

  const scFreight = document.getElementById("sc-current-freight");
  if (scFreight) scFreight.value = lane.defaultFreight.toFixed(2);
}

// ---------------------------------------------------------------------------
// 1. Overview Dashboard
// ---------------------------------------------------------------------------
async function loadOverview() {
  const container = document.getElementById("screen-overview");
  if (!container) return;

  try {
    const data = await API.getDashboardOverview();
    state.overviewData = data;

    // Macro KPIs
    document.getElementById("ov-kpi-bdi").textContent = Number(data.market.bdi).toLocaleString();
    document.getElementById("ov-kpi-vlsfo").textContent = `$${data.market.vlsfo_usd_per_tonne.toFixed(2)}`;
    document.getElementById("ov-kpi-coal").textContent = `$${data.market.coal_price_usd_per_mt.toFixed(2)}`;
    document.getElementById("ov-kpi-fe").textContent = `$${data.market.iron_ore_price_usd_per_dmt.toFixed(2)}`;
    document.getElementById("ov-kpi-avg-freight").textContent = `$${data.market.average_freight_usd_per_tonne.toFixed(2)}`;

    // Trend Pill
    const trendEl = document.getElementById("ov-kpi-trend");
    if (trendEl) {
      trendEl.textContent = `${data.market.freight_trend_classification} (${data.market.shift_percent >= 0 ? "+" : ""}${data.market.shift_percent.toFixed(2)}%)`;
      trendEl.className = `trend-pill trend-${data.market.freight_trend_classification.toLowerCase()}`;
    }

    // 5 Routes Table
    const routesTbody = document.getElementById("ov-routes-tbody");
    if (routesTbody && data.routes && data.routes.canonical_lanes) {
      routesTbody.innerHTML = data.routes.canonical_lanes.map((r, i) => {
        const fc = data.forecast.route_forecasts[i] || {};
        const recoClass = fc.recommendation === "CHARTER NOW" ? "reco-charter" : fc.recommendation === "WAIT" ? "reco-wait" : "reco-monitor";
        return `
          <tr>
            <td>
              <div style="font-weight:600;">${r.origin} → ${r.destination}</div>
              <small style="color:var(--text-muted);">${r.commodity} • ${r.vessel_type}</small>
            </td>
            <td class="tabular-nums" style="font-family:var(--font-mono);font-weight:600;">$${r.latest_freight.toFixed(2)}</td>
            <td class="tabular-nums" style="font-family:var(--font-mono);">$${fc.predicted_next_month_freight_usd_per_tonne ? fc.predicted_next_month_freight_usd_per_tonne.toFixed(2) : "--"}</td>
            <td>
              <span class="trend-pill ${r.latest_monthly_change >= 0 ? 'trend-up' : 'trend-down'}">
                ${r.latest_monthly_change >= 0 ? '+' : ''}${r.latest_monthly_change_percent.toFixed(2)}%
              </span>
            </td>
            <td>
              <span class="reco-badge ${recoClass}">${fc.recommendation || 'MONITOR'}</span>
            </td>
          </tr>
        `;
      }).join("");
    }

    // Weather Port Cards
    const weatherGrid = document.getElementById("ov-weather-grid");
    if (weatherGrid && data.weather && data.weather.ports) {
      weatherGrid.innerHTML = data.weather.ports.map((w) => {
        const riskClass = w.risk_level === "HIGH" ? "risk-high" : w.risk_level === "MEDIUM" ? "risk-medium" : "risk-low";
        return `
          <div class="card" style="padding:16px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
              <span style="font-weight:600;font-size:0.85rem;">${w.port}</span>
              <span class="risk-badge ${riskClass}">${w.risk_level}</span>
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:0.75rem;color:var(--text-secondary);">
              <div>Wind: <span style="font-family:var(--font-mono);color:var(--text-primary);">${w.wind_kmh.toFixed(1)} km/h</span></div>
              <div>Wave: <span style="font-family:var(--font-mono);color:var(--text-primary);">${w.wave_height_m.toFixed(1)} m</span></div>
              <div>Cyclone: <span style="font-family:var(--font-mono);color:var(--text-primary);">${w.cyclone_risk.toFixed(1)}/5</span></div>
              <div>Delay: <span style="font-family:var(--font-mono);color:var(--text-primary);">${w.weather_delay_days.toFixed(1)} d</span></div>
            </div>
          </div>
        `;
      }).join("");
    }

    // Deterministic Signals List
    const signalsList = document.getElementById("ov-signals-list");
    if (signalsList && data.signals) {
      signalsList.innerHTML = data.signals.map((sig) => {
        const sevClass = sig.severity === "HIGH" ? "signal-high" : sig.severity === "MEDIUM" ? "signal-medium" : "signal-low";
        const iconName = sig.severity === "HIGH" ? "warning" : sig.severity === "MEDIUM" ? "info" : "verified";
        return `
          <div class="signal-card ${sevClass}">
            <div class="signal-icon-wrapper">
              <span class="material-symbols-outlined" style="font-size:20px;">${iconName}</span>
            </div>
            <div class="signal-content">
              <h4>${sig.title}</h4>
              <p>${sig.description}</p>
            </div>
          </div>
        `;
      }).join("");
    }
  } catch (err) {
    console.error("Failed to load overview dashboard:", err);
  }
}

// ---------------------------------------------------------------------------
// 2. Freight Forecast Screen
// ---------------------------------------------------------------------------
function initForecastForm() {
  const laneSelect = document.getElementById("fc-lane-select");
  if (laneSelect) {
    laneSelect.innerHTML = CANONICAL_LANES.map(
      (lane, idx) => `<option value="${idx}">${lane.label}</option>`
    ).join("");

    laneSelect.value = state.selectedLaneIndex;
    laneSelect.addEventListener("change", (e) => {
      state.selectedLaneIndex = Number(e.target.value);
      syncLaneAcrossForms();
    });
  }

  const btnAutoFill = document.getElementById("fc-btn-autofill");
  if (btnAutoFill) {
    btnAutoFill.addEventListener("click", autoFillForecastInputs);
  }

  const form = document.getElementById("forecast-form");
  if (form) {
    form.addEventListener("submit", handleForecastSubmit);
  }
}

async function loadForecastScreen() {
  syncLaneAcrossForms();
  await autoFillForecastInputs();
  // Trigger default prediction if none yet
  if (!state.latestForecast) {
    await executeForecast();
  }
}

async function autoFillForecastInputs() {
  try {
    const summary = await API.getExecutiveSummary();
    if (summary && summary.market_state) {
      const m = summary.market_state;
      document.getElementById("fc-bdi").value = m.bdi;
      document.getElementById("fc-vlsfo").value = m.vlsfo_usd_per_tonne;
      document.getElementById("fc-coal").value = m.coal_price_usd_per_mt;
      document.getElementById("fc-iron-ore").value = m.iron_ore_price_usd_per_dmt;
    }
    // Default nominal weather
    document.getElementById("fc-wind").value = "28.5";
    document.getElementById("fc-wave").value = "1.8";
    document.getElementById("fc-cyclone").value = "1.5";
    document.getElementById("fc-delay").value = "0.2";
  } catch (err) {
    console.warn("Auto-fill notice:", err);
  }
}

async function handleForecastSubmit(e) {
  if (e) e.preventDefault();
  await executeForecast();
}

async function executeForecast() {
  const btn = document.getElementById("fc-btn-submit");
  if (btn) btn.disabled = true;

  const lane = CANONICAL_LANES[state.selectedLaneIndex];
  const payload = {
    origin: lane.origin,
    destination: lane.destination,
    commodity: lane.commodity,
    vessel_type: lane.vessel_type,
    current_freight_usd_per_tonne: parseFloat(document.getElementById("fc-current-freight").value),
    bdi: parseFloat(document.getElementById("fc-bdi").value),
    vlsfo_usd_per_tonne: parseFloat(document.getElementById("fc-vlsfo").value),
    coal_price_usd_per_mt: parseFloat(document.getElementById("fc-coal").value),
    iron_ore_price_usd_per_dmt: parseFloat(document.getElementById("fc-iron-ore").value),
    wind_kmh: parseFloat(document.getElementById("fc-wind").value),
    wave_height_m: parseFloat(document.getElementById("fc-wave").value),
    cyclone_risk: parseFloat(document.getElementById("fc-cyclone").value),
    weather_delay_days: parseFloat(document.getElementById("fc-delay").value),
  };

  try {
    const res = await API.predict(payload);
    state.latestForecast = res;
    renderForecastResults(res);
  } catch (err) {
    alert(`Forecast Error [${err.errorCode}]: ${err.message}`);
  } finally {
    if (btn) btn.disabled = false;
  }
}

function renderForecastResults(res) {
  document.getElementById("fc-res-forecast").textContent = `$${res.predicted_next_month_freight_usd_per_tonne.toFixed(2)}`;
  
  const chgEl = document.getElementById("fc-res-change");
  const isPos = res.forecast_change_percent >= 0;
  chgEl.textContent = `${isPos ? "+" : ""}${res.forecast_change_percent.toFixed(2)}% vs Current`;
  chgEl.className = `trend-pill ${isPos ? "trend-up" : "trend-down"}`;

  const recoBadge = document.getElementById("fc-res-reco");
  recoBadge.textContent = res.recommendation;
  recoBadge.className = `reco-badge ${res.recommendation === "CHARTER NOW" ? "reco-charter" : res.recommendation === "WAIT" ? "reco-wait" : "reco-monitor"}`;

  const riskBadge = document.getElementById("fc-res-risk");
  riskBadge.textContent = res.risk_level;
  riskBadge.className = `risk-badge ${res.risk_level === "HIGH" ? "risk-high" : res.risk_level === "MEDIUM" ? "risk-medium" : "risk-low"}`;

  document.getElementById("fc-res-reason").textContent = res.reason;

  // Render Explainability Section
  if (res.explanation) {
    const summaryEl = document.getElementById("fc-expl-summary");
    if (summaryEl) summaryEl.textContent = res.explanation.summary;

    const waterfallEl = document.getElementById("fc-expl-waterfall");
    if (waterfallEl) {
      Charts.renderDriverWaterfall(waterfallEl, res.explanation.drivers);
    }
  }
}

// ---------------------------------------------------------------------------
// 3. What-If Scenario Simulation
// ---------------------------------------------------------------------------
function initScenarioForm() {
  const laneSelect = document.getElementById("sc-lane-select");
  if (laneSelect) {
    laneSelect.innerHTML = CANONICAL_LANES.map(
      (lane, idx) => `<option value="${idx}">${lane.label}</option>`
    ).join("");

    laneSelect.value = state.selectedLaneIndex;
    laneSelect.addEventListener("change", (e) => {
      state.selectedLaneIndex = Number(e.target.value);
      syncLaneAcrossForms();
      runScenarioSimulation();
    });
  }

  // Bind slider shocks
  const sliders = [
    { id: "sc-slider-vlsfo", badge: "sc-badge-vlsfo", suffix: "%" },
    { id: "sc-slider-bdi", badge: "sc-badge-bdi", suffix: "%" },
    { id: "sc-slider-cyclone", badge: "sc-badge-cyclone", suffix: " pts" },
    { id: "sc-slider-delay", badge: "sc-badge-delay", suffix: "%" },
  ];

  sliders.forEach((s) => {
    const el = document.getElementById(s.id);
    const badge = document.getElementById(s.badge);
    if (el && badge) {
      el.addEventListener("input", () => {
        const val = Number(el.value);
        badge.textContent = `${val >= 0 ? "+" : ""}${val}${s.suffix}`;
        runScenarioSimulation();
      });
    }
  });

  const btnReset = document.getElementById("sc-btn-reset");
  if (btnReset) {
    btnReset.addEventListener("click", () => {
      sliders.forEach((s) => {
        const el = document.getElementById(s.id);
        const badge = document.getElementById(s.badge);
        if (el) el.value = 0;
        if (badge) badge.textContent = `0${s.suffix}`;
      });
      runScenarioSimulation();
    });
  }
}

async function loadScenarioScreen() {
  syncLaneAcrossForms();
  await runScenarioSimulation();
}

async function runScenarioSimulation() {
  const lane = CANONICAL_LANES[state.selectedLaneIndex];
  const vlsfoShock = parseFloat(document.getElementById("sc-slider-vlsfo").value) || 0;
  const bdiShock = parseFloat(document.getElementById("sc-slider-bdi").value) || 0;
  const cycloneShock = parseFloat(document.getElementById("sc-slider-cyclone").value) || 0;
  const delayShock = parseFloat(document.getElementById("sc-slider-delay").value) || 0;

  const payload = {
    origin: lane.origin,
    destination: lane.destination,
    commodity: lane.commodity,
    vessel_type: lane.vessel_type,
    current_freight_usd_per_tonne: lane.defaultFreight,
    bdi: 1850.0,
    vlsfo_usd_per_tonne: 640.0,
    coal_price_usd_per_mt: 112.0,
    iron_ore_price_usd_per_dmt: 102.0,
    wind_kmh: 28.0,
    wave_height_m: 1.8,
    cyclone_risk: 1.5,
    weather_delay_days: 0.2,
    scenario_changes: {
      vlsfo_change_percent: vlsfoShock !== 0 ? vlsfoShock : null,
      bdi_change_percent: bdiShock !== 0 ? bdiShock : null,
      cyclone_risk_change: cycloneShock !== 0 ? cycloneShock : null,
      weather_delay_change_percent: delayShock !== 0 ? delayShock : null,
    },
  };

  try {
    const res = await API.predictScenario(payload);
    state.scenarioResult = res;
    renderScenarioResults(res);
  } catch (err) {
    console.error("Scenario simulation error:", err);
  }
}

function renderScenarioResults(res) {
  // Baseline vs Scenario comparison
  document.getElementById("sc-base-val").textContent = `$${res.baseline.predicted_next_month_freight_usd_per_tonne.toFixed(2)}`;
  document.getElementById("sc-sim-val").textContent = `$${res.scenario.predicted_next_month_freight_usd_per_tonne.toFixed(2)}`;

  const diff = res.impact.difference_usd_per_tonne;
  const diffEl = document.getElementById("sc-diff-val");
  diffEl.textContent = `${diff >= 0 ? "+" : ""}$${diff.toFixed(2)}/t (${res.impact.difference_percent >= 0 ? "+" : ""}${res.impact.difference_percent.toFixed(2)}%)`;
  diffEl.className = `trend-pill ${diff >= 0 ? "trend-up" : "trend-down"}`;

  document.getElementById("sc-risk-shift").textContent = res.impact.risk_level_shift;
  document.getElementById("sc-reco-shift").textContent = res.impact.recommendation_shift;
  document.getElementById("sc-summary").textContent = res.summary;

  // Changed variables list
  const changesList = document.getElementById("sc-changes-list");
  if (changesList) {
    if (res.changes.length === 0) {
      changesList.innerHTML = `<div style="color:var(--text-muted);font-size:0.8rem;">No parameter shocks applied (Baseline State).</div>`;
    } else {
      changesList.innerHTML = res.changes.map((c) => `
        <div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--border-subtle);font-size:0.82rem;">
          <span style="color:var(--text-secondary);">${c.feature_label}</span>
          <span style="font-family:var(--font-mono);font-weight:600;">
            ${c.baseline.toFixed(1)} → <span style="color:var(--primary);">${c.scenario.toFixed(1)}</span> (${c.percentage_change >= 0 ? "+" : ""}${c.percentage_change ? c.percentage_change.toFixed(1) + "%" : ""})
          </span>
        </div>
      `).join("");
    }
  }
}

// ---------------------------------------------------------------------------
// 4. Route Intelligence
// ---------------------------------------------------------------------------
async function loadRoutesScreen() {
  try {
    const data = await API.getRoutesAnalytics();
    state.routesData = data;

    const tbody = document.getElementById("ri-routes-tbody");
    if (tbody && data.routes) {
      tbody.innerHTML = data.routes.map((r, i) => `
        <tr>
          <td>
            <div style="font-weight:600;">${r.origin} → ${r.destination}</div>
            <small style="color:var(--text-muted);">${r.commodity} • ${r.vessel_type}</small>
          </td>
          <td class="tabular-nums" style="font-family:var(--font-mono);font-weight:600;">$${r.latest_freight.toFixed(2)}</td>
          <td class="tabular-nums" style="font-family:var(--font-mono);">$${r.average_freight.toFixed(2)}</td>
          <td class="tabular-nums" style="font-family:var(--font-mono);">$${r.minimum_freight.toFixed(2)} – $${r.maximum_freight.toFixed(2)}</td>
          <td>
            <span class="trend-pill ${r.latest_monthly_change >= 0 ? 'trend-up' : 'trend-down'}">
              ${r.latest_monthly_change >= 0 ? '+' : ''}${r.latest_monthly_change_percent.toFixed(2)}%
            </span>
          </td>
          <td>
            <span class="trend-pill trend-${r.trend.toLowerCase()}">${r.trend}</span>
          </td>
        </tr>
      `).join("");
    }

    // Historical Trend Chart for selected route
    const currentLane = CANONICAL_LANES[state.selectedLaneIndex];
    const trendsData = await API.getFreightTrends({
      origin: currentLane.origin,
      commodity: currentLane.commodity,
    });

    const chartContainer = document.getElementById("ri-trends-chart");
    if (chartContainer && trendsData.series) {
      Charts.renderTimeSeries(chartContainer, trendsData.series, {
        yKey: "freight_rate_usd_per_tonne",
        xKey: "date",
        strokeColor: "#7C5CFC",
        unit: "$/t",
      });
    }
  } catch (err) {
    console.error("Route intelligence load error:", err);
  }
}

// ---------------------------------------------------------------------------
// 5. Market Intelligence
// ---------------------------------------------------------------------------
async function loadMarketScreen() {
  try {
    const marketTrends = await API.getMarketTrends();
    const correlations = await API.getCorrelations();

    // Render Multi-series macro chart
    const macroChartEl = document.getElementById("mi-macro-chart");
    if (macroChartEl && marketTrends.series) {
      Charts.renderMultiSeries(macroChartEl, marketTrends.series);
    }

    // Render Correlation Matrix
    const corrChartEl = document.getElementById("mi-correlations-chart");
    if (corrChartEl && correlations.correlations) {
      Charts.renderCorrelations(corrChartEl, correlations.correlations);
    }
  } catch (err) {
    console.error("Market intelligence load error:", err);
  }
}

// ---------------------------------------------------------------------------
// 6. Weather Intelligence
// ---------------------------------------------------------------------------
async function loadWeatherScreen() {
  try {
    const trends = await API.getWeatherTrends();
    const latest = await API.getLatestData();

    // Group by port
    const ports = ["Australia West Coast", "Hay Point", "Taboneo"];
    const container = document.getElementById("wi-ports-grid");
    if (container) {
      container.innerHTML = ports.map((port) => {
        const portTrends = trends.series.filter((s) => s.origin === port);
        const latestPt = portTrends[portTrends.length - 1] || {};
        const liveMatch = (latest.weather || []).find((w) => w.port === port);

        return `
          <div class="card">
            <div class="card-header">
              <div class="card-title">
                <span class="material-symbols-outlined icon">location_on</span>
                ${port}
              </div>
              <span class="risk-badge ${latestPt.cyclone_risk >= 3 ? 'risk-high' : 'risk-low'}">
                Risk Score: ${latestPt.cyclone_risk ? latestPt.cyclone_risk.toFixed(1) : '1.0'}/5
              </span>
            </div>
            <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px;">
              <div class="kpi-card">
                <span class="kpi-label">Wind Speed</span>
                <span class="kpi-value">${latestPt.wind_kmh ? latestPt.wind_kmh.toFixed(1) : '--'}<span class="unit">km/h</span></span>
              </div>
              <div class="kpi-card">
                <span class="kpi-label">Wave Height</span>
                <span class="kpi-value">${latestPt.wave_height_m ? latestPt.wave_height_m.toFixed(1) : '--'}<span class="unit">m</span></span>
              </div>
              <div class="kpi-card">
                <span class="kpi-label">Cyclone Score</span>
                <span class="kpi-value">${latestPt.cyclone_risk ? latestPt.cyclone_risk.toFixed(1) : '--'}<span class="unit">0-5</span></span>
              </div>
              <div class="kpi-card">
                <span class="kpi-label">Est. Delay</span>
                <span class="kpi-value">${latestPt.weather_delay_days ? latestPt.weather_delay_days.toFixed(1) : '0.0'}<span class="unit">days</span></span>
              </div>
            </div>
            <div style="font-size:0.75rem;color:var(--text-muted);display:flex;justify-content:space-between;">
              <span>Historical Observation Date: ${latestPt.date || '2025-11-01'}</span>
              <span>Live DB Status: ${liveMatch ? 'Active Cache' : 'Nominal Fallback'}</span>
            </div>
          </div>
        `;
      }).join("");
    }
  } catch (err) {
    console.error("Weather intelligence load error:", err);
  }
}

// ---------------------------------------------------------------------------
// 7. Data & Sources Screen
// ---------------------------------------------------------------------------
async function loadSourcesScreen() {
  try {
    const modelInfo = await API.getModelInfo();
    const telemetry = await API.getTelemetry(10);
    const dataStatus = await API.getDataStatus();

    // Model Details
    document.getElementById("ds-model-name").textContent = modelInfo.model || "freight_forecast_model_v3";
    document.getElementById("ds-model-algo").textContent = modelInfo.algorithm || "Bounded Residual Ridge Regression";
    document.getElementById("ds-model-alpha").textContent = modelInfo.alpha ? modelInfo.alpha.toFixed(1) : "10.0";
    document.getElementById("ds-model-features").textContent = `${modelInfo.features || 13} Features`;
    document.getElementById("ds-dataset-name").textContent = "master_freight_training_expanded_v1.csv";
    document.getElementById("ds-dataset-obs").textContent = "110 Genuine Observations (2024-02-01 to 2025-11-01)";

    // Telemetry Table
    const tbody = document.getElementById("ds-telemetry-tbody");
    if (tbody && telemetry) {
      tbody.innerHTML = telemetry.map((t) => `
        <tr>
          <td style="font-family:var(--font-mono);font-size:0.75rem;">${(t.timestamp || '').substring(0, 19)}</td>
          <td>${t.origin} → ${t.destination}</td>
          <td>${t.commodity}</td>
          <td class="tabular-nums" style="font-family:var(--font-mono);">$${t.current_freight_usd_per_tonne.toFixed(2)}</td>
          <td class="tabular-nums" style="font-family:var(--font-mono);font-weight:600;">$${t.predicted_next_month_freight_usd_per_tonne.toFixed(2)}</td>
          <td><span class="risk-badge ${t.risk_level === 'HIGH' ? 'risk-high' : 'risk-low'}">${t.risk_level}</span></td>
        </tr>
      `).join("");
    }
  } catch (err) {
    console.error("Data sources load error:", err);
  }
}

// Global Refresh Button
function initGlobalEvents() {
  const refreshBtn = document.getElementById("btn-global-refresh");
  if (refreshBtn) {
    refreshBtn.addEventListener("click", async () => {
      refreshBtn.style.transform = "rotate(180deg)";
      await loadScreenData(state.currentRoute);
      setTimeout(() => {
        refreshBtn.style.transform = "none";
      }, 300);
    });
  }
}
