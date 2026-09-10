/**
 * High-Performance SVG Charting Engine for Freight Intelligence Platform
 * Zero external dependencies. Renders crisp, responsive SVG visualizations.
 */

export const Charts = {
  renderTimeSeries(container, dataPoints, options = {}) {
    if (!container) return;
    container.innerHTML = "";

    if (!dataPoints || dataPoints.length === 0) {
      container.innerHTML = `<div class="p-6 text-center text-xs text-slate-400">Historical trend data unavailable for this route.</div>`;
      return;
    }

    const width = container.clientWidth || 600;
    const height = 240;
    const padding = { top: 20, right: 40, bottom: 30, left: 50 };

    const chartW = Math.max(100, width - padding.left - padding.right);
    const chartH = Math.max(50, height - padding.top - padding.bottom);

    const yKey = options.yKey || "freight_rate_usd_per_tonne";
    const xKey = options.xKey || "date";
    const strokeColor = options.strokeColor || "#0284c7";
    const expectedRate = options.expectedRate || null;
    const forecastLow = options.forecastLow || null;
    const forecastHigh = options.forecastHigh || null;

    const yValues = dataPoints.map(d => Number(d[yKey]) || 0);
    if (expectedRate) yValues.push(Number(expectedRate));
    if (forecastLow) yValues.push(Number(forecastLow));
    if (forecastHigh) yValues.push(Number(forecastHigh));

    const minY = Math.min(...yValues);
    const maxY = Math.max(...yValues);
    const yBuffer = Math.max(1.0, (maxY - minY) * 0.2);
    const yMin = Math.max(0, minY - yBuffer);
    const yMax = maxY + yBuffer;

    const totalSteps = dataPoints.length + (expectedRate ? 1 : 0);
    const getX = (i) => padding.left + (i / Math.max(1, totalSteps - 1)) * chartW;
    const getY = (val) => padding.top + chartH - ((val - yMin) / Math.max(0.001, yMax - yMin)) * chartH;

    // SVG Construction
    let svg = `<svg width="100%" height="${height}" viewBox="0 0 ${width} ${height}" class="overflow-visible select-none" xmlns="http://www.w3.org/2000/svg">`;

    // Grid lines (3 horizontal lines)
    const ySteps = 3;
    for (let i = 0; i <= ySteps; i++) {
      const val = yMin + (i / ySteps) * (yMax - yMin);
      const y = getY(val);
      svg += `<line x1="${padding.left}" y1="${y}" x2="${width - padding.right}" y2="${y}" stroke="#e2e8f0" stroke-dasharray="3,3" stroke-width="1"/>`;
      svg += `<text x="${padding.left - 8}" y="${y + 4}" font-family="Inter, sans-serif" font-size="10" fill="#94a3b8" text-anchor="end">$${val.toFixed(1)}</text>`;
    }

    // Historical Line & Area Path
    let pathD = "";
    let areaD = `M ${padding.left} ${padding.top + chartH} `;

    dataPoints.forEach((d, i) => {
      const x = getX(i);
      const y = getY(d[yKey]);
      if (i === 0) {
        pathD += `M ${x} ${y} `;
        areaD += `L ${x} ${y} `;
      } else {
        pathD += `L ${x} ${y} `;
        areaD += `L ${x} ${y} `;
      }
    });

    const lastHistIndex = dataPoints.length - 1;
    const lastHistX = getX(lastHistIndex);
    const lastHistY = getY(dataPoints[lastHistIndex][yKey]);

    areaD += `L ${lastHistX} ${padding.top + chartH} Z`;

    // Area gradient
    svg += `
      <defs>
        <linearGradient id="chart-area-grad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#0284c7" stop-opacity="0.25"/>
          <stop offset="100%" stop-color="#0284c7" stop-opacity="0.0"/>
        </linearGradient>
      </defs>
      <path d="${areaD}" fill="url(#chart-area-grad)" />
      <path d="${pathD}" fill="none" stroke="${strokeColor}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
    `;

    // Forecast Projection
    if (expectedRate && lastHistIndex >= 0) {
      const targetX = getX(totalSteps - 1);
      const targetY = getY(expectedRate);

      // Forecast dotted line
      svg += `<line x1="${lastHistX}" y1="${lastHistY}" x2="${targetX}" y2="${targetY}" stroke="#10b981" stroke-width="2.5" stroke-dasharray="4,4" stroke-linecap="round"/>`;

      // CI Envelope if bounds available
      if (forecastLow && forecastHigh) {
        const lowY = getY(forecastLow);
        const highY = getY(forecastHigh);
        const ciPath = `M ${lastHistX} ${lastHistY} L ${targetX} ${highY} L ${targetX} ${lowY} Z`;
        svg += `<path d="${ciPath}" fill="#10b981" fill-opacity="0.12"/>`;
        svg += `<line x1="${targetX}" y1="${highY}" x2="${targetX}" y2="${lowY}" stroke="#10b981" stroke-width="2" stroke-linecap="round"/>`;
      }

      // Target Node (Forecast point)
      svg += `
        <circle cx="${targetX}" cy="${targetY}" r="5" fill="#10b981" stroke="#ffffff" stroke-width="2"/>
        <text x="${targetX}" y="${targetY - 10}" font-family="Inter, sans-serif" font-size="11" font-weight="700" fill="#047857" text-anchor="middle">$${Number(expectedRate).toFixed(2)}</text>
        <text x="${targetX}" y="${height - 10}" font-family="Inter, sans-serif" font-size="10" font-weight="600" fill="#047857" text-anchor="middle">Forecast</text>
      `;
    }

    // Historical Nodes & Dates
    dataPoints.forEach((d, i) => {
      const x = getX(i);
      const y = getY(d[yKey]);
      const isLast = i === lastHistIndex;

      if (isLast) {
        // Spot node
        svg += `
          <circle cx="${x}" cy="${y}" r="5" fill="#0f172a" stroke="#ffffff" stroke-width="2"/>
          <text x="${x}" y="${y - 10}" font-family="Inter, sans-serif" font-size="11" font-weight="700" fill="#0f172a" text-anchor="middle">$${Number(d[yKey]).toFixed(2)}</text>
        `;
      }

      // X-Axis labels (every 2-3 points or start/end)
      if (i === 0 || i === Math.floor(lastHistIndex / 2) || i === lastHistIndex) {
        const rawDate = d[xKey] || "";
        const label = rawDate.length >= 7 ? rawDate.substring(0, 7) : rawDate;
        svg += `<text x="${x}" y="${height - 10}" font-family="Inter, sans-serif" font-size="10" fill="#64748b" text-anchor="middle">${label}</text>`;
      }
    });

    svg += `</svg>`;
    container.innerHTML = svg;
  }
};
