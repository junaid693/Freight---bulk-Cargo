/**
 * Freight Intelligence Platform — Application Controller
 * Stitch UI Fidelity & Model v3 Decision Support Engine
 */

import { API } from "./api.js";
import { Charts } from "./charts.js";

// Canonical 5 Trade Lanes Definition (Strict Enforcement)
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

  // Load initial route from window hash
  handleNavigation(window.location.hash.replace("#", "") || "overview");
});

// Router & View Switcher
function initRouter() {
  window.addEventListener("hashchange", () => {
    const route = window.location.hash.replace("#", "") || "overview";
    handleNavigation(route);
  });

  document.querySelectorAll(".nav-link").forEach((link) => {
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
  document.querySelectorAll(".nav-link").forEach((link) => {
    if (link.getAttribute("data-route") === route) {
      link.classList.add("active");
    } else {
      link.classList.remove("active");
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
    forecast: "Freight Forecast",
    scenario: "What-If Scenario Simulation",
    routes: "Route Intelligence",
    market: "Market Intelligence",
    weather: "Weather Intelligence",
    sources: "Data & Sources Provenance",
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
      if (state.currentRoute === "overview") loadOverview();
      if (state.currentRoute === "routes") loadRoutesScreen();
    });
  }
}

function syncLaneAcrossForms() {
  const lane = CANONICAL_LANES[state.selectedLaneIndex];
  if (!lane) return;

  const topbarSelect = document.getElementById("topbar-route-select");
  if (topbarSelect) topbarSelect.value = state.selectedLaneIndex;

  // Sync Forecast Form
  const fcLaneSelect = document.getElementById("fc-lane-select");
  if (fcLaneSelect) fcLaneSelect.value = state.selectedLaneIndex;

  const fcFreight = document.getElementById("fc-current-freight");
  if (fcFreight) fcFreight.value = lane.defaultFreight.toFixed(2);

  // Sync Scenario Form
  const scLaneSelect = document.getElementById("sc-lane-select");
  if (scLaneSelect) scLaneSelect.value = state.selectedLaneIndex;
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

    const selectedLane = CANONICAL_LANES[state.selectedLaneIndex];
    const selectedRouteFc = (data.forecast && data.forecast.route_forecasts) 
      ? (data.forecast.route_forecasts[state.selectedLaneIndex] || data.forecast.route_forecasts[0])
      : null;

    // Top 6 KPIs
    if (selectedRouteFc) {
      document.getElementById("ov-kpi-current-freight").innerHTML = `$${selectedRouteFc.current_freight_usd_per_tonne.toFixed(2)}<span class="text-xs text-on-surface-variant ml-1 font-normal">/ t</span>`;
      document.getElementById("ov-kpi-forecast").innerHTML = `$${selectedRouteFc.predicted_next_month_freight_usd_per_tonne.toFixed(2)}<span class="text-xs text-on-surface-variant ml-1 font-normal">/ t</span>`;
      
      const chg = selectedRouteFc.forecast_change_percent;
      const isPos = chg >= 0;
      const changeEl = document.getElementById("ov-kpi-change");
      changeEl.textContent = `${isPos ? "+" : ""}${chg.toFixed(2)}%`;
      changeEl.className = `font-kpi-value text-2xl mt-auto ${isPos ? "text-error" : "text-success-green"}`;

      const sigBadge = document.getElementById("ov-kpi-signal");
      sigBadge.textContent = selectedRouteFc.recommendation;
      sigBadge.className = `reco-badge ${selectedRouteFc.recommendation === "CHARTER NOW" ? "reco-charter" : selectedRouteFc.recommendation === "WAIT" ? "reco-wait" : "reco-monitor"}`;

      const riskBadge = document.getElementById("ov-kpi-weather-risk");
      riskBadge.textContent = selectedRouteFc.risk_level;
      riskBadge.className = `risk-badge ${selectedRouteFc.risk_level === "HIGH" ? "risk-high" : selectedRouteFc.risk_level === "MEDIUM" ? "risk-medium" : "risk-low"}`;
    }

    document.getElementById("ov-kpi-bdi").textContent = Number(data.market.bdi).toLocaleString();

    // Map Route Labels
    const mapOrigin = document.getElementById("ov-map-origin-label");
    if (mapOrigin) mapOrigin.textContent = selectedLane.origin.toUpperCase();

    const mapDest = document.getElementById("ov-map-dest-label");
    if (mapDest) mapDest.textContent = selectedLane.destination.toUpperCase();

    const mapTitle = document.getElementById("ov-map-route-title");
    if (mapTitle) mapTitle.textContent = `${selectedLane.commodity} • ${selectedLane.vessel_type}`;

    const mapSub = document.getElementById("ov-map-route-sub");
    if (mapSub) mapSub.textContent = `${selectedLane.origin} → ${selectedLane.destination}`;

    // Algorithm Recommendation Hero Card
    if (selectedRouteFc) {
      document.getElementById("ov-hero-reco").textContent = selectedRouteFc.recommendation;
      document.getElementById("ov-hero-reason").textContent = (
        data.forecast.reference_summary ||
        `Model v3 projects next-month rates will move by ${selectedRouteFc.forecast_change_percent >= 0 ? '+' : ''}${selectedRouteFc.forecast_change_percent.toFixed(2)}% for ${selectedLane.origin} to ${selectedLane.destination}.`
      );
    }

    // Market Snapshot
    document.getElementById("ov-snap-bdi").textContent = Number(data.market.bdi).toLocaleString();
    document.getElementById("ov-snap-vlsfo").textContent = `$${data.market.vlsfo_usd_per_tonne.toFixed(2)}/t`;
    document.getElementById("ov-snap-coal").textContent = `$${data.market.coal_price_usd_per_mt.toFixed(2)}/MT`;
    document.getElementById("ov-snap-fe").textContent = `$${data.market.iron_ore_price_usd_per_dmt.toFixed(2)}/dmt`;

    // Weather Snapshot (match origin port)
    const matchedWeather = (data.weather.ports || []).find(p => p.port === selectedLane.origin) || (data.weather.ports || [])[0];
    if (matchedWeather) {
      document.getElementById("ov-snap-wind").textContent = `${matchedWeather.wind_kmh.toFixed(1)} km/h`;
      document.getElementById("ov-snap-wave").textContent = `${matchedWeather.wave_height_m.toFixed(1)} m`;
      document.getElementById("ov-snap-cyclone").textContent = `${matchedWeather.cyclone_risk.toFixed(1)} / 5`;
      document.getElementById("ov-snap-delay").textContent = `${matchedWeather.weather_delay_days.toFixed(1)} days`;
    }

    // 5 Routes Table
    const routesTbody = document.getElementById("ov-routes-tbody");
    if (routesTbody && data.routes && data.routes.canonical_lanes) {
      routesTbody.innerHTML = data.routes.canonical_lanes.map((r, i) => {
        const fc = data.forecast.route_forecasts[i] || {};
        const recoClass = fc.recommendation === "CHARTER NOW" ? "reco-charter" : fc.recommendation === "WAIT" ? "reco-wait" : "reco-monitor";
        const riskClass = fc.risk_level === "HIGH" ? "risk-high" : fc.risk_level === "MEDIUM" ? "risk-medium" : "risk-low";
        return `
          <tr class="hover:bg-surface-container-low transition-colors">
            <td class="py-3 px-4 whitespace-nowrap font-medium text-on-surface">${r.origin} → ${r.destination}</td>
            <td class="py-3 px-4 text-on-surface-variant">${r.commodity}</td>
            <td class="py-3 px-4 text-on-surface-variant">${r.vessel_type}</td>
            <td class="py-3 px-4 font-mono-data text-right font-semibold">$${r.latest_freight.toFixed(2)}</td>
            <td class="py-3 px-4 font-mono-data text-right text-primary font-semibold">$${fc.predicted_next_month_freight_usd_per_tonne ? fc.predicted_next_month_freight_usd_per_tonne.toFixed(2) : "--"}</td>
            <td class="py-3 px-4 font-mono-data text-right ${r.latest_monthly_change >= 0 ? 'text-error' : 'text-success-green'}">
              ${r.latest_monthly_change >= 0 ? '+' : ''}${r.latest_monthly_change_percent.toFixed(2)}%
            </td>
            <td class="py-3 px-4"><span class="risk-badge ${riskClass}">${fc.risk_level || 'LOW'}</span></td>
            <td class="py-3 px-4 text-center">
              <span class="reco-badge ${recoClass}">${fc.recommendation || 'MONITOR'}</span>
            </td>
          </tr>
        `;
      }).join("");
    }

    // Historical Trend Chart for selected route
    const trendsData = await API.getFreightTrends({
      origin: selectedLane.origin,
      commodity: selectedLane.commodity,
    });
    const trendChartContainer = document.getElementById("ov-trend-chart-container");
    if (trendChartContainer && trendsData.series) {
      Charts.renderTimeSeries(trendChartContainer, trendsData.series, {
        yKey: "freight_rate_usd_per_tonne",
        xKey: "date",
        strokeColor: "#7c5cfc",
        height: 360,
      });
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
    // Set standard weather benchmark
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
    renderForecastResults(res, payload.current_freight_usd_per_tonne);
  } catch (err) {
    alert(`Forecast Error [${err.errorCode}]: ${err.message}`);
  } finally {
    if (btn) btn.disabled = false;
  }
}

function renderForecastResults(res, currentRate) {
  document.getElementById("fc-res-forecast").innerHTML = `$${res.predicted_next_month_freight_usd_per_tonne.toFixed(2)} <span class="text-lg text-on-surface-variant font-normal">/ t</span>`;
  
  const chgEl = document.getElementById("fc-res-change");
  const isPos = res.forecast_change_percent >= 0;
  chgEl.innerHTML = `
    <span class="material-symbols-outlined text-[14px]">${isPos ? 'arrow_upward' : 'arrow_downward'}</span>
    ${isPos ? "+" : ""}${res.forecast_change_percent.toFixed(2)}%
  `;
  chgEl.className = `trend-pill ${isPos ? "trend-up" : "trend-down"} px-2 py-0.5 rounded-sm flex items-center gap-1`;

  const recoBadge = document.getElementById("fc-res-reco");
  recoBadge.textContent = res.recommendation;
  recoBadge.className = `reco-badge ${res.recommendation === "CHARTER NOW" ? "reco-charter" : res.recommendation === "WAIT" ? "reco-wait" : "reco-monitor"}`;

  const riskBadge = document.getElementById("fc-res-risk");
  riskBadge.textContent = res.risk_level;
  riskBadge.className = `risk-badge ${res.risk_level === "HIGH" ? "risk-high" : res.risk_level === "MEDIUM" ? "risk-medium" : "risk-low"}`;

  document.getElementById("fc-res-reason").textContent = res.reason;

  // Render Explainability Section
  if (res.explanation && res.explanation.drivers) {
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
  // Baseline vs Scenario
  document.getElementById("sc-base-val").textContent = `$${res.baseline.predicted_next_month_freight_usd_per_tonne.toFixed(2)}`;
  document.getElementById("sc-sim-val").textContent = `$${res.scenario.predicted_next_month_freight_usd_per_tonne.toFixed(2)}`;

  const diff = res.impact.difference_usd_per_tonne;
  const diffEl = document.getElementById("sc-diff-val");
  diffEl.textContent = `${diff >= 0 ? "+" : ""}$${diff.toFixed(2)}/t (${res.impact.difference_percent >= 0 ? "+" : ""}${res.impact.difference_percent.toFixed(2)}%)`;
  diffEl.className = `trend-pill font-mono-data ${diff >= 0 ? "trend-up" : "trend-down"}`;

  document.getElementById("sc-risk-shift").textContent = res.impact.risk_level_shift;
  document.getElementById("sc-reco-shift").textContent = res.impact.recommendation_shift;
  document.getElementById("sc-summary").textContent = res.summary;

  // Changed variables list
  const changesList = document.getElementById("sc-changes-list");
  if (changesList) {
    if (res.changes.length === 0) {
      changesList.innerHTML = `<div class="text-on-surface-variant text-xs italic">No parameter shocks applied (Baseline State).</div>`;
    } else {
      changesList.innerHTML = res.changes.map((c) => `
        <div class="flex justify-between py-1 border-b border-border-subtle text-xs">
          <span class="text-on-surface">${c.feature_label}</span>
          <span class="font-mono-data font-semibold">
            ${c.baseline.toFixed(1)} → <span class="text-primary">${c.scenario.toFixed(1)}</span> (${c.percentage_change >= 0 ? "+" : ""}${c.percentage_change ? c.percentage_change.toFixed(1) + "%" : ""})
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
      tbody.innerHTML = data.routes.map((r) => `
        <tr class="hover:bg-surface-container-low transition-colors">
          <td class="py-3 px-4 whitespace-nowrap font-medium text-on-surface">
            <div>${r.origin} → ${r.destination}</div>
            <small class="text-on-surface-variant font-normal">${r.commodity} • ${r.vessel_type}</small>
          </td>
          <td class="py-3 px-4 font-mono-data text-right font-bold text-on-surface">$${r.latest_freight.toFixed(2)}</td>
          <td class="py-3 px-4 font-mono-data text-right text-on-surface-variant">$${r.average_freight.toFixed(2)}</td>
          <td class="py-3 px-4 font-mono-data text-right text-on-surface-variant">$${r.minimum_freight.toFixed(2)} – $${r.maximum_freight.toFixed(2)}</td>
          <td class="py-3 px-4 font-mono-data text-right ${r.latest_monthly_change >= 0 ? 'text-error' : 'text-success-green'}">
            ${r.latest_monthly_change >= 0 ? '+' : ''}${r.latest_monthly_change_percent.toFixed(2)}%
          </td>
          <td class="py-3 px-4 text-center">
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
        strokeColor: "#7c5cfc",
        height: 250,
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
      Charts.renderMultiSeries(macroChartEl, marketTrends.series, {
        height: 300,
      });
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

    const ports = ["Australia West Coast", "Hay Point", "Taboneo"];
    const container = document.getElementById("wi-ports-grid");
    if (container) {
      container.innerHTML = ports.map((port) => {
        const portTrends = trends.series.filter((s) => s.origin === port);
        const latestPt = portTrends[portTrends.length - 1] || {};
        const liveMatch = (latest.weather || []).find((w) => w.port === port);
        const isHigh = latestPt.cyclone_risk >= 3.0;

        return `
          <div class="bg-surface-container-lowest border border-border-subtle rounded p-gutter ambient-shadow flex flex-col justify-between">
            <div>
              <div class="flex justify-between items-center mb-4 border-b border-border-subtle pb-2">
                <div class="font-headline-sm text-base font-bold text-on-surface flex items-center gap-1.5">
                  <span class="material-symbols-outlined text-primary text-lg">location_on</span>
                  ${port}
                </div>
                <span class="risk-badge ${isHigh ? 'risk-high' : 'risk-low'}">
                  Score: ${latestPt.cyclone_risk ? latestPt.cyclone_risk.toFixed(1) : '1.0'}/5
                </span>
              </div>
              <div class="grid grid-cols-2 gap-3 mb-4 text-xs">
                <div class="p-2.5 bg-surface-container rounded border border-border-subtle">
                  <span class="text-on-surface-variant block uppercase text-[10px]">Wind Speed</span>
                  <span class="font-mono-data text-sm font-bold text-on-surface">${latestPt.wind_kmh ? latestPt.wind_kmh.toFixed(1) : '--'} km/h</span>
                </div>
                <div class="p-2.5 bg-surface-container rounded border border-border-subtle">
                  <span class="text-on-surface-variant block uppercase text-[10px]">Wave Height</span>
                  <span class="font-mono-data text-sm font-bold text-on-surface">${latestPt.wave_height_m ? latestPt.wave_height_m.toFixed(1) : '--'} m</span>
                </div>
                <div class="p-2.5 bg-surface-container rounded border border-border-subtle">
                  <span class="text-on-surface-variant block uppercase text-[10px]">Cyclone Score</span>
                  <span class="font-mono-data text-sm font-bold ${isHigh ? 'text-error' : 'text-success-green'}">${latestPt.cyclone_risk ? latestPt.cyclone_risk.toFixed(1) : '--'} / 5</span>
                </div>
                <div class="p-2.5 bg-surface-container rounded border border-border-subtle">
                  <span class="text-on-surface-variant block uppercase text-[10px]">Weather Delay</span>
                  <span class="font-mono-data text-sm font-bold text-on-surface">${latestPt.weather_delay_days ? latestPt.weather_delay_days.toFixed(1) : '0.0'} d</span>
                </div>
              </div>
            </div>
            <div class="text-[10px] text-on-surface-variant border-t border-border-subtle pt-2 flex justify-between">
              <span>Observation: ${latestPt.date || '2025-11-01'}</span>
              <span class="text-secondary font-mono-data">${liveMatch ? 'Active DB Cache' : 'Historical Anchor'}</span>
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

    document.getElementById("ds-model-name").textContent = modelInfo.model || "freight_forecast_model_v3";
    document.getElementById("ds-model-algo").textContent = modelInfo.algorithm || "Bounded Residual Ridge Regression";
    document.getElementById("ds-model-alpha").textContent = modelInfo.alpha ? modelInfo.alpha.toFixed(1) : "10.0";
    document.getElementById("ds-model-features").textContent = `${modelInfo.features || 13} Features (NO cargo_tonnes)`;
    document.getElementById("ds-dataset-name").textContent = "master_freight_training_expanded_v1.csv";
    document.getElementById("ds-dataset-obs").textContent = "110 Genuine Observations (2024-02-01 to 2025-11-01)";

    // Telemetry Table
    const tbody = document.getElementById("ds-telemetry-tbody");
    if (tbody && telemetry) {
      tbody.innerHTML = telemetry.map((t) => `
        <tr class="hover:bg-surface-container-low transition-colors">
          <td class="py-2.5 px-4 font-mono-data text-xs text-on-surface-variant">${(t.timestamp || '').substring(0, 19)}</td>
          <td class="py-2.5 px-4 font-medium text-on-surface">${t.origin} → ${t.destination}</td>
          <td class="py-2.5 px-4 text-on-surface-variant">${t.commodity}</td>
          <td class="py-2.5 px-4 font-mono-data text-right text-on-surface">$${t.current_freight_usd_per_tonne.toFixed(2)}</td>
          <td class="py-2.5 px-4 font-mono-data text-right font-bold text-primary">$${t.predicted_next_month_freight_usd_per_tonne.toFixed(2)}</td>
          <td class="py-2.5 px-4"><span class="risk-badge ${t.risk_level === 'HIGH' ? 'risk-high' : 'risk-low'}">${t.risk_level}</span></td>
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
