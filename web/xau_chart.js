(function () {
  const API_BASE = window.location.protocol === "file:" ? "http://127.0.0.1:8765" : "";
  const STORAGE = {
    timeframe: "trade-observer-xau-tv-timeframe",
    symbol: "trade-observer-xau-tv-symbol",
    zoom: "trade-observer-xau-tv-zoom",
    pan: "trade-observer-xau-tv-pan",
    vertical: "trade-observer-xau-tv-vertical-scale",
    verticalPan: "trade-observer-xau-tv-vertical-pan",
    tool: "trade-observer-xau-tv-tool",
    drawings: "trade-observer-xau-tv-drawings",
  };

  const LINE_TOOLS = new Set([
    "trendline",
    "ray",
    "info-line",
    "extended-line",
    "trend-angle",
    "horizontal-ray",
    "vertical-line",
    "cross-line",
  ]);

  const DRAWING_TOOLS = new Set([
    "dot",
    "arrow",
    ...LINE_TOOLS,
  ]);

  const TOOL_OPTION_ICONS = {
    cross: "+",
    dot: "o",
    arrow: "->",
    trendline: "/",
    ray: "\\",
    "info-line": "i",
    "extended-line": "<->",
    "trend-angle": "/_",
    "horizontal-ray": "-->",
    "vertical-line": "|",
    "cross-line": "+",
  };

  const state = {
    timeframe: localStorage.getItem(STORAGE.timeframe) || "H1",
    symbol: (localStorage.getItem(STORAGE.symbol) || "XAUUSD").trim() || "XAUUSD",
    anchorDate: "",
    anchorTime: "",
    draftTimeframe: localStorage.getItem(STORAGE.timeframe) || "H1",
    draftDate: "",
    draftTime: "",
    payload: null,
    zoom: Number(localStorage.getItem(STORAGE.zoom) || 0),
    panOffset: Number(localStorage.getItem(STORAGE.pan) || 0),
    verticalScale: Number(localStorage.getItem(STORAGE.vertical) || 1),
    verticalPan: Number(localStorage.getItem(STORAGE.verticalPan) || 0),
    activeTool: localStorage.getItem(STORAGE.tool) || "cross",
    drawings: JSON.parse(localStorage.getItem(STORAGE.drawings) || "[]"),
    geometry: null,
    hover: null,
    hoverRaw: null,
    dragMode: null,
    dragStartX: 0,
    dragStartY: 0,
    dragStartPan: 0,
    dragStartVerticalScale: 1,
    dragStartVerticalPan: 0,
    toolMenuOpen: false,
    pendingShape: null,
    ctrlKey: false,
    shiftKey: false,
  };

  const els = {
    canvas: document.querySelector("#xauTvCanvas"),
    timeframeButtons: [...document.querySelectorAll("[data-xau-tv-timeframe]")],
    symbolInput: document.querySelector("#xauTvSymbolInput"),
    symbolLoadButton: document.querySelector("#xauTvLoadSymbolButton"),
    periodTimeframe: document.querySelector("#xauTvPeriodTimeframe"),
    periodDate: document.querySelector("#xauTvPeriodDate"),
    periodTime: document.querySelector("#xauTvPeriodTime"),
    loadPeriodButton: document.querySelector("#xauTvLoadPeriodButton"),
    liveNowButton: document.querySelector("#xauTvLiveNowButton"),
    periodNote: document.querySelector("#xauTvPeriodNote"),
    currentTimeframe: document.querySelector("#xauTvCurrentTimeframe"),
    currentPrice: document.querySelector("#xauTvCurrentPrice"),
    headerPrice: document.querySelector("#xauTvHeaderPrice"),
    resolvedSymbol: document.querySelector("#xauTvResolvedSymbol"),
    activeFilter: document.querySelector("#xauTvActiveFilter"),
    symbol: document.querySelector("#xauTvSymbol"),
    titleSymbol: document.querySelector("#xauTvTitleSymbol"),
    subtitle: document.querySelector("#xauTvSubtitle"),
    pageSection: document.querySelector('[data-page-panel="xau-chart"]'),
    toolButton: document.querySelector("#xauToolSelectorButton"),
    toolButtonIcon: document.querySelector("#xauToolSelectorIcon"),
    toolButtonCaret: document.querySelector("#xauToolSelectorButton .xau-tool-caret"),
    toolMenu: document.querySelector("#xauToolMenu"),
    toolOptions: [...document.querySelectorAll("[data-xau-tool]")],
    previousDaySummary: document.querySelector("#xauTvPreviousDaySummary"),
  };

  const ctx = els.canvas?.getContext("2d");

  function fixed(value, digits = 2) {
    const numeric = Number(value || 0);
    return Number.isFinite(numeric) ? numeric.toFixed(digits) : "-";
  }

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function normalizeSymbolInput(value) {
    return String(value || "").trim().toUpperCase() || "XAUUSD";
  }

  function persistView() {
    localStorage.setItem(STORAGE.timeframe, state.timeframe);
    localStorage.setItem(STORAGE.symbol, state.symbol);
    localStorage.setItem(STORAGE.zoom, String(state.zoom));
    localStorage.setItem(STORAGE.pan, String(state.panOffset));
    localStorage.setItem(STORAGE.vertical, String(state.verticalScale));
    localStorage.setItem(STORAGE.verticalPan, String(state.verticalPan));
    localStorage.setItem(STORAGE.tool, state.activeTool);
    localStorage.setItem(STORAGE.drawings, JSON.stringify(state.drawings));
  }

  function syncDraftPeriodControls() {
    if (els.periodTimeframe && document.activeElement !== els.periodTimeframe) {
      els.periodTimeframe.value = state.draftTimeframe || state.timeframe;
    }
    if (els.periodDate && document.activeElement !== els.periodDate) {
      els.periodDate.value = state.draftDate;
    }
    if (els.periodTime && document.activeElement !== els.periodTime) {
      els.periodTime.value = state.draftTime;
    }
  }

  function timeframeLabel(value) {
    const labels = {
      M1: "1m",
      M2: "2m",
      M3: "3m",
      M5: "5m",
      M15: "15m",
      M30: "30m",
      H1: "1h",
      H2: "2h",
      H4: "4h",
      D1: "D",
      W1: "W",
      MN1: "M",
    };
    return labels[value] || value;
  }

  function isLineTool(tool = state.activeTool) {
    return LINE_TOOLS.has(tool);
  }

  function isDrawingTool(tool = state.activeTool) {
    return DRAWING_TOOLS.has(tool);
  }

  function toolIconMarkup(tool) {
    const map = {
      cross: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4v16M4 12h16" /></svg>',
      dot: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3.5" /></svg>',
      arrow: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 18 18 6M11 6h7v7" /></svg>',
      trendline: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 18 19 6" /></svg>',
      ray: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 18 18 6M18 6h-5M18 6v5" /></svg>',
      "info-line": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 18 19 6" /><circle cx="8" cy="8" r="1.4" /></svg>',
      "extended-line": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 19 21 5" /></svg>',
      "trend-angle": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 18h10M6 18l9-9" /></svg>',
      "horizontal-ray": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14M14 8l5 4-5 4" /></svg>',
      "vertical-line": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4v16" /></svg>',
      "cross-line": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4v16M4 12h16" /></svg>',
    };
    return map[tool] || map.cross;
  }

  async function fetchJson(path) {
    const response = await fetch(`${API_BASE}${path}`, {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    const text = await response.text();
    let payload = {};
    try {
      payload = text ? JSON.parse(text) : {};
    } catch {
      payload = {};
    }
    if (!response.ok) {
      throw new Error(payload.error || payload.message || `Request failed (${response.status})`);
    }
    return payload;
  }

  function displaySymbolName(symbol) {
    const upper = String(symbol || "").trim().toUpperCase();
    if (upper.includes("XAU") || upper.includes("GOLD")) {
      return "Gold Spot / U.S. Dollar";
    }
    return upper || "Market Board";
  }

  function formatSnapshotLabel(payload) {
    const timeframe = timeframeLabel(payload?.timeframe || state.timeframe);
    const anchorDate = payload?.anchor_date || state.anchorDate || "";
    const anchorTime = payload?.anchor_time || state.anchorTime || "";
    if (!anchorDate) {
      return `Live feed | ${timeframe} | latest market candles`;
    }
    return anchorTime
      ? `Snapshot | ${timeframe} | ${anchorDate} ${anchorTime} UTC`
      : `Snapshot | ${timeframe} | ${anchorDate} 23:59 UTC`;
  }

  function formatCandleTimestamp(rawTime, timeframe = state.timeframe) {
    const date = new Date(rawTime || "");
    if (Number.isNaN(date.getTime())) return "-";
    const year = date.getUTCFullYear();
    const month = String(date.getUTCMonth() + 1).padStart(2, "0");
    const day = String(date.getUTCDate()).padStart(2, "0");
    const hours = String(date.getUTCHours()).padStart(2, "0");
    const minutes = String(date.getUTCMinutes()).padStart(2, "0");
    const tf = String(timeframe || "").toUpperCase();
    if (tf === "D1") return `${year}-${month}-${day}`;
    if (tf === "W1") return `Week of ${year}-${month}-${day}`;
    if (tf === "MN1") return `${year}-${month}`;
    return `${year}-${month}-${day} ${hours}:${minutes} UTC`;
  }

  function renderMeta(payload) {
    const resolved = payload?.symbol || state.symbol || "XAUUSD";
    const requested = payload?.requested_symbol || state.symbol || resolved;
    const currentPrice = Number(payload?.current_price || 0);
    const snapshotLabel = payload?.snapshot_label || "";
    if (els.symbol) els.symbol.textContent = resolved;
    if (els.currentTimeframe) els.currentTimeframe.textContent = timeframeLabel(state.timeframe);
    if (els.currentPrice) els.currentPrice.textContent = currentPrice ? fixed(currentPrice) : "-";
    if (els.headerPrice) {
      els.headerPrice.textContent = currentPrice
        ? `Current price ${fixed(currentPrice)}`
        : (payload?.connection_error || "Waiting for candles...");
    }
    if (els.resolvedSymbol) els.resolvedSymbol.textContent = `Resolved broker symbol: ${resolved}`;
    if (els.titleSymbol) els.titleSymbol.textContent = displaySymbolName(resolved);
    if (els.subtitle) {
      els.subtitle.textContent = snapshotLabel
        ? `${resolved} | ${timeframeLabel(state.timeframe)} | ${snapshotLabel}`
        : `${resolved} | ${timeframeLabel(state.timeframe)} | live MT5 feed`;
    }
    if (els.symbolInput && document.activeElement !== els.symbolInput) {
      els.symbolInput.value = requested;
    }
    syncDraftPeriodControls();
    if (els.periodNote) {
      els.periodNote.textContent = snapshotLabel
        ? `Viewing ${snapshotLabel}. Click Live Now to return to the live feed.`
        : "Pick a date and optional time to jump the chart. Default timeframe is 1H.";
    }
    if (els.activeFilter) {
      els.activeFilter.textContent = formatSnapshotLabel(payload);
    }
    if (els.previousDaySummary) {
      const levels = Array.isArray(payload?.previous_day_levels) ? payload.previous_day_levels : [];
      const latest = levels.at(-1);
      els.previousDaySummary.textContent = latest
        ? `Using only ${latest.previous_day} as PDH ${fixed(latest.previous_high)} / PDL ${fixed(latest.previous_low)}. Status: ${String(latest.sweep_status || "pending").replaceAll("_", " ")}.`
        : "Previous day high/low levels will appear after daily MT5 history loads.";
    }
  }

  function updateToolUi() {
    if (els.toolButtonIcon) {
      els.toolButtonIcon.innerHTML = toolIconMarkup(state.activeTool);
    }
    if (els.toolButtonCaret) {
      els.toolButtonCaret.textContent = "›";
    }
    if (els.toolButton) {
      els.toolButton.classList.toggle("is-open", state.toolMenuOpen);
      els.toolButton.setAttribute("aria-expanded", state.toolMenuOpen ? "true" : "false");
    }
    if (els.toolMenu) {
      els.toolMenu.classList.toggle("hidden-page", !state.toolMenuOpen);
    }
    els.toolOptions.forEach((option) => {
      option.classList.toggle("active", option.dataset.xauTool === state.activeTool);
      const icon = option.querySelector(".xau-tool-option-icon");
      if (icon) {
        icon.textContent = TOOL_OPTION_ICONS[option.dataset.xauTool || "cross"] || "+";
      }
    });
  }

  function updateTimeframeButtons() {
    els.timeframeButtons.forEach((button) => {
      button.classList.toggle("active", button.dataset.xauTvTimeframe === state.timeframe);
    });
  }

  function getVisibleCandles(candles) {
    const all = Array.isArray(candles) ? candles : [];
    if (!all.length) return [];
    const width = els.canvas?.clientWidth || 1200;
    const baseCount = Math.max(30, Math.min(140, Math.floor(width / 13.6)));
    const zoomFactor = Math.pow(1.1, state.zoom);
    const visibleCount = clamp(Math.round(baseCount * zoomFactor), 22, all.length);
    const maxPan = Math.max(0, all.length - visibleCount);
    state.panOffset = clamp(state.panOffset, 0, maxPan);
    const end = all.length - state.panOffset;
    const start = Math.max(0, end - visibleCount);
    return all.slice(start, end);
  }

  function canvasPoint(event) {
    const rect = els.canvas.getBoundingClientRect();
    return {
      x: event.clientX - rect.left,
      y: event.clientY - rect.top,
    };
  }

  function xToIndex(x) {
    const geo = state.geometry;
    if (!geo) return 0;
    return clamp(Math.round((x - geo.padding.left) / geo.step), 0, geo.candles.length - 1);
  }

  function yToPrice(y) {
    const geo = state.geometry;
    if (!geo) return 0;
    return geo.paddedMax - ((y - geo.padding.top) / geo.plotHeight) * geo.adjustedSpread;
  }

  function drawingPoint(index, price) {
    const geo = state.geometry;
    return {
      x: geo.padding.left + index * geo.step + geo.step / 2,
      y: geo.priceToY(price),
    };
  }

  function nearestCandleAnchor(index, price) {
    const geo = state.geometry;
    const candle = geo?.candles?.[clamp(index, 0, (geo?.candles?.length || 1) - 1)];
    if (!candle) {
      return { index, price };
    }
    const anchors = [
      { price: Number(candle.high), kind: "wick-high" },
      { price: Number(candle.low), kind: "wick-low" },
      { price: Number(candle.open), kind: "body-open" },
      { price: Number(candle.close), kind: "body-close" },
    ].filter((item) => Number.isFinite(item.price));
    const nearest = anchors.reduce((best, current) => {
      if (!best) return current;
      return Math.abs(current.price - price) < Math.abs(best.price - price) ? current : best;
    }, null);
    return {
      index,
      price: nearest?.price ?? price,
      kind: nearest?.kind || "free",
    };
  }

  function constrainLinePoint(anchor, index, price) {
    const geo = state.geometry;
    if (!geo) return { index, price };
    const start = drawingPoint(anchor.index, anchor.price);
    const end = drawingPoint(index, price);
    const dx = end.x - start.x;
    const dy = end.y - start.y;
    const length = Math.max(Math.hypot(dx, dy), 1);
    const snappedAngle = Math.round(Math.atan2(dy, dx) / (Math.PI / 4)) * (Math.PI / 4);
    const snappedX = start.x + Math.cos(snappedAngle) * length;
    const snappedY = start.y + Math.sin(snappedAngle) * length;
    return {
      index: xToIndex(snappedX),
      price: yToPrice(snappedY),
    };
  }

  function resolveHover(rawPoint, modifierState = {}) {
    const geo = state.geometry;
    if (!geo || !rawPoint) return null;
    const inPriceScale = rawPoint.x >= geo.chartRight;
    let index = xToIndex(rawPoint.x);
    let price = yToPrice(rawPoint.y);
    let snapped = false;
    let snapKind = "";

    if (!inPriceScale && modifierState.ctrlKey && isDrawingTool()) {
      const nearest = nearestCandleAnchor(index, price);
      index = nearest.index;
      price = nearest.price;
      snapped = true;
      snapKind = nearest.kind;
    }

    if (!inPriceScale && modifierState.shiftKey && state.pendingShape && isLineTool(state.pendingShape.tool || state.activeTool)) {
      const constrained = constrainLinePoint(state.pendingShape, index, price);
      index = constrained.index;
      price = constrained.price;
    }

    const display = drawingPoint(index, price);
    return {
      rawX: rawPoint.x,
      rawY: rawPoint.y,
      x: display.x,
      y: display.y,
      inPriceScale,
      index,
      price,
      snapped,
      snapKind,
    };
  }

  function updateCursor() {
    if (!els.canvas || !state.geometry) return;
    if (state.dragMode === "price-scale") {
      els.canvas.style.cursor = "ns-resize";
      return;
    }
    if (state.dragMode === "pan") {
      els.canvas.style.cursor = "grabbing";
      return;
    }
    const hover = state.hover;
    if (!hover) {
      els.canvas.style.cursor = "default";
      return;
    }
    if (hover.inPriceScale) {
      els.canvas.style.cursor = "ns-resize";
      return;
    }
    if (state.activeTool === "cross" || isDrawingTool()) {
      els.canvas.style.cursor = "crosshair";
      return;
    }
    els.canvas.style.cursor = "grab";
  }

  function setHover(point, modifierState = {}) {
    state.hoverRaw = point || null;
    state.hover = resolveHover(point, modifierState);
    updateCursor();
  }

  function drawLineKind(tool, p1, p2, geo, drawing = null) {
    const dx = p2.x - p1.x;
    const dy = p2.y - p1.y;
    const length = Math.max(Math.hypot(dx, dy), 1);
    const ux = dx / length;
    const uy = dy / length;
    let startX = p1.x;
    let startY = p1.y;
    let endX = p2.x;
    let endY = p2.y;

    if (tool === "ray" || tool === "info-line" || tool === "trend-angle") {
      endX = p1.x + ux * 2400;
      endY = p1.y + uy * 2400;
    } else if (tool === "extended-line") {
      startX = p1.x - ux * 2400;
      startY = p1.y - uy * 2400;
      endX = p2.x + ux * 2400;
      endY = p2.y + uy * 2400;
    } else if (tool === "horizontal-ray") {
      endX = geo.chartRight;
      endY = p1.y;
    } else if (tool === "vertical-line") {
      startX = p1.x;
      endX = p1.x;
      startY = geo.padding.top;
      endY = geo.chartBottom;
    } else if (tool === "cross-line") {
      ctx.beginPath();
      ctx.moveTo(p1.x, geo.padding.top);
      ctx.lineTo(p1.x, geo.chartBottom);
      ctx.moveTo(geo.padding.left, p1.y);
      ctx.lineTo(geo.chartRight, p1.y);
      ctx.stroke();
      return;
    }

    ctx.beginPath();
    ctx.moveTo(startX, startY);
    ctx.lineTo(endX, endY);
    ctx.stroke();

    if (tool === "trend-angle") {
      const angle = Math.atan2(-(p2.y - p1.y), p2.x - p1.x) * (180 / Math.PI);
      ctx.fillStyle = "#111111";
      ctx.font = "12px Aptos";
      ctx.fillText(`${fixed(angle, 1)}°`, p1.x + 10, p1.y - 8);
    }
    if (tool === "info-line" && drawing) {
      const priceDelta = Math.abs(Number(drawing.price2 ?? drawing.price) - Number(drawing.price));
      ctx.fillStyle = "#111111";
      ctx.font = "12px Aptos";
      ctx.fillText(`Δ ${fixed(priceDelta, 2)}`, p2.x + 8, p2.y - 8);
    }
  }

  function buildPreviewDrawing() {
    if (!state.pendingShape || !state.hover || state.hover.inPriceScale) return null;
    return {
      ...state.pendingShape,
      index2: state.hover.index,
      price2: state.hover.price,
      preview: true,
    };
  }

  function drawAnnotations() {
    const geo = state.geometry;
    if (!geo) return;

    const preview = buildPreviewDrawing();
    const visibleDrawings = state.drawings.filter((drawing) => {
      const symbol = String(drawing.symbol || state.symbol).toUpperCase();
      const timeframe = String(drawing.timeframe || state.timeframe).toUpperCase();
      return symbol === state.symbol.toUpperCase() && timeframe === state.timeframe.toUpperCase();
    });
    const allDrawings = preview ? [...visibleDrawings, preview] : visibleDrawings;

    allDrawings.forEach((drawing) => {
      const p1 = drawingPoint(drawing.index ?? 0, drawing.price ?? 0);
      const p2 = drawing.index2 != null && drawing.price2 != null
        ? drawingPoint(drawing.index2, drawing.price2)
        : p1;

      ctx.save();
      ctx.strokeStyle = drawing.preview ? "rgba(17,17,17,0.55)" : "#111111";
      ctx.fillStyle = drawing.preview ? "rgba(17,17,17,0.55)" : "#111111";
      ctx.lineWidth = 1.45;

      if (drawing.tool === "dot") {
        ctx.beginPath();
        ctx.arc(p1.x, p1.y, 4, 0, Math.PI * 2);
        ctx.fill();
      } else if (drawing.tool === "arrow") {
        ctx.beginPath();
        ctx.moveTo(p1.x - 10, p1.y + 10);
        ctx.lineTo(p1.x + 8, p1.y - 8);
        ctx.lineTo(p1.x + 1, p1.y - 8);
        ctx.moveTo(p1.x + 8, p1.y - 8);
        ctx.lineTo(p1.x + 8, p1.y - 1);
        ctx.stroke();
      } else {
        drawLineKind(drawing.tool, p1, p2, geo, drawing);
      }

      ctx.restore();
    });
  }

  function drawCrosshair() {
    const geo = state.geometry;
    const hover = state.hover;
    if (!geo || !hover || hover.inPriceScale) return;
    if (hover.x < geo.padding.left || hover.x > geo.chartRight || hover.y < geo.padding.top || hover.y > geo.chartBottom) {
      return;
    }
    ctx.save();
    ctx.strokeStyle = "rgba(31, 35, 39, 0.4)";
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(geo.padding.left, hover.y);
    ctx.lineTo(geo.chartRight, hover.y);
    ctx.moveTo(hover.x, geo.padding.top);
    ctx.lineTo(hover.x, geo.chartBottom);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = "rgba(17, 17, 17, 0.88)";
    ctx.fillRect(geo.chartRight + 8, hover.y - 12, 98, 24);
    ctx.fillStyle = "#f7f7f7";
    ctx.font = "12px Cascadia Mono";
    ctx.fillText(fixed(hover.price), geo.chartRight + 16, hover.y + 4);
    const candle = geo.candles?.[hover.index];
    const timeLabel = formatCandleTimestamp(candle?.time, state.timeframe);
    const labelWidth = Math.max(136, Math.min(240, ctx.measureText(timeLabel).width + 20));
    const desiredX = hover.x - labelWidth / 2;
    const labelX = clamp(desiredX, geo.padding.left, geo.chartRight - labelWidth);
    const labelY = geo.chartBottom + 8;
    ctx.fillStyle = "rgba(17, 17, 17, 0.9)";
    ctx.fillRect(labelX, labelY, labelWidth, 22);
    ctx.fillStyle = "#f7f7f7";
    ctx.fillText(timeLabel, labelX + 10, labelY + 15);
    ctx.restore();
  }

  function candleTime(candle) {
    const parsed = Date.parse(candle?.time || "");
    return Number.isFinite(parsed) ? parsed : 0;
  }

  function getLatestPreviousDayLevel(levels) {
    if (!Array.isArray(levels) || !levels.length) return [];
    const latest = levels.at(-1);
    return latest ? [latest] : [];
  }

  function drawLevelLabel(text, x, y, fillStyle) {
    ctx.font = "bold 12px Aptos";
    const width = Math.min(240, Math.max(132, ctx.measureText(text).width + 18));
    ctx.fillStyle = fillStyle;
    ctx.fillRect(x, y - 13, width, 24);
    ctx.fillStyle = "#ffffff";
    ctx.fillText(text, x + 8, y + 4);
  }

  function drawPreviousDayLevels(levels, geo) {
    if (!Array.isArray(levels) || !levels.length || !geo?.candles?.length) return;
    const candleTimes = geo.candles.map(candleTime);
    const chartLeft = geo.padding.left;

    levels.forEach((level) => {
      const x1 = Math.max(chartLeft, chartLeft + geo.step * 0.25);
      const x2 = Math.min(geo.chartRight, chartLeft + geo.step * candleTimes.length - geo.step * 0.25);
      const labelX = clamp(x2 - 192, chartLeft + 8, geo.chartRight - 202);
      const lines = [
        { price: Number(level.previous_high), label: `PDH ${fixed(level.previous_high)} ${level.previous_day || ""}`, color: "rgba(222, 74, 91, 0.92)", dash: [10, 6] },
        { price: Number(level.previous_low), label: `PDL ${fixed(level.previous_low)} ${level.previous_day || ""}`, color: "rgba(38, 143, 91, 0.92)", dash: [6, 5] },
      ];

      lines.forEach((item) => {
        if (!Number.isFinite(item.price)) return;
        const y = geo.priceToY(item.price);
        if (y < geo.padding.top - 2 || y > geo.chartBottom + 2) return;
        ctx.save();
        ctx.setLineDash(item.dash);
        ctx.strokeStyle = item.color;
        ctx.lineWidth = 1.8;
        ctx.beginPath();
        ctx.moveTo(x1, y);
        ctx.lineTo(x2, y);
        ctx.stroke();
        ctx.setLineDash([]);
        drawLevelLabel(item.label, labelX, y, item.color);
        ctx.restore();
      });
    });
  }

  function drawChart(payload) {
    if (!ctx || !els.canvas) return;
    const width = Math.max(1220, els.canvas.clientWidth || els.canvas.width);
    const height = Math.max(740, Math.round(width * 0.56));
    els.canvas.width = width;
    els.canvas.height = height;
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = "#c8c8c8";
    ctx.fillRect(0, 0, width, height);

    const candles = getVisibleCandles(payload?.candles || []);
    renderMeta(payload);
    if (!candles.length) {
      ctx.fillStyle = "#4f5358";
      ctx.font = "22px Aptos";
      ctx.fillText(payload?.connection_error || `Waiting for ${state.symbol} candles...`, 28, height / 2);
      state.geometry = null;
      updateCursor();
      return;
    }

    const padding = { top: 18, right: 108, bottom: 34, left: 24 };
    const previousDayLevels = getLatestPreviousDayLevel(payload?.previous_day_levels || []);
    const activeTrades = Array.isArray(payload?.active_trades) ? payload.active_trades : [];
    const highs = candles.map((candle) => Number(candle.high));
    const lows = candles.map((candle) => Number(candle.low));
    const closes = candles.map((candle) => Number(candle.close));
    const levelHighs = previousDayLevels.map((level) => Number(level.previous_high)).filter(Number.isFinite);
    const levelLows = previousDayLevels.map((level) => Number(level.previous_low)).filter(Number.isFinite);
    const tradePrices = activeTrades.flatMap((trade) => [
      Number(trade.entry_price),
      Number(trade.stop_loss),
      Number(trade.take_profit),
    ]).filter(Number.isFinite);
    const maxPrice = Math.max(...highs, ...levelHighs, ...tradePrices);
    const minPrice = Math.min(...lows, ...levelLows, ...tradePrices);
    const baseSpread = Math.max(maxPrice - minPrice, Number(payload?.point || 0.01) * 12, 0.5);
    const center = (maxPrice + minPrice) / 2;
    const adjustedSpread = baseSpread / clamp(state.verticalScale, 0.35, 5);
    const adjustedCenter = center - state.verticalPan;
    const paddedMax = adjustedCenter + adjustedSpread / 2;
    const paddedMin = adjustedCenter - adjustedSpread / 2;
    const plotWidth = width - padding.left - padding.right;
    const plotHeight = height - padding.top - padding.bottom;
    const step = plotWidth / candles.length;
    const candleWidth = Math.max(6, Math.min(22, step * 0.9));
    const chartRight = width - padding.right;
    const chartBottom = height - padding.bottom;
    const priceToY = (price) => padding.top + ((paddedMax - Number(price)) / adjustedSpread) * plotHeight;

    state.geometry = {
      padding,
      plotWidth,
      plotHeight,
      step,
      chartRight,
      chartBottom,
      candles,
      previousDayLevels,
      activeTrades,
      paddedMax,
      adjustedSpread,
      priceToY,
    };

    ctx.strokeStyle = "rgba(0, 0, 0, 0.08)";
    ctx.lineWidth = 1;
    for (let row = 0; row <= 6; row += 1) {
      const y = padding.top + (plotHeight / 6) * row;
      ctx.beginPath();
      ctx.moveTo(padding.left, y);
      ctx.lineTo(chartRight, y);
      ctx.stroke();
    }
    for (let col = 0; col <= 7; col += 1) {
      const x = padding.left + (plotWidth / 7) * col;
      ctx.beginPath();
      ctx.moveTo(x, padding.top);
      ctx.lineTo(x, chartBottom);
      ctx.stroke();
    }

    drawPreviousDayLevels(previousDayLevels, state.geometry);

    const drawTradeLevel = (price, color, label) => {
      if (!Number.isFinite(Number(price))) return;
      const y = priceToY(Number(price));
      if (y < padding.top - 2 || y > chartBottom + 2) return;
      ctx.save();
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.8;
      ctx.setLineDash([9, 6]);
      ctx.beginPath();
      ctx.moveTo(padding.left, y);
      ctx.lineTo(chartRight, y);
      ctx.stroke();
      ctx.setLineDash([]);
      drawLevelLabel(label, clamp(chartRight - 182, padding.left + 8, chartRight - 194), y, color);
      ctx.restore();
    };

    activeTrades.forEach((trade) => {
      drawTradeLevel(trade.entry_price, "rgba(52, 139, 235, 0.92)", `ENTRY ${fixed(trade.entry_price)}`);
      if (Number(trade.stop_loss) > 0) {
        drawTradeLevel(trade.stop_loss, "rgba(222, 74, 91, 0.92)", `SL ${fixed(trade.stop_loss)}`);
      }
      if (Number(trade.take_profit) > 0) {
        drawTradeLevel(trade.take_profit, "rgba(38, 143, 91, 0.92)", `TP ${fixed(trade.take_profit)}`);
      }
    });

    candles.forEach((candle, index) => {
      const x = padding.left + index * step + step / 2;
      const open = Number(candle.open);
      const close = Number(candle.close);
      const high = Number(candle.high);
      const low = Number(candle.low);
      const bullish = close >= open;
      ctx.strokeStyle = bullish ? "#2d2d2d" : "#111111";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, priceToY(high));
      ctx.lineTo(x, priceToY(low));
      ctx.stroke();
      ctx.fillStyle = bullish ? "#45a749" : "#111111";
      ctx.fillRect(
        x - candleWidth / 2,
        Math.min(priceToY(open), priceToY(close)),
        candleWidth,
        Math.max(2, Math.abs(priceToY(close) - priceToY(open))),
      );
    });

    drawAnnotations();

    const currentPrice = Number(payload?.current_price || closes.at(-1) || 0);
    const currentY = priceToY(currentPrice);
    ctx.setLineDash([2, 6]);
    ctx.strokeStyle = "rgba(69, 167, 73, 0.75)";
    ctx.beginPath();
    ctx.moveTo(padding.left, currentY);
    ctx.lineTo(chartRight, currentY);
    ctx.stroke();
    ctx.setLineDash([]);

    const priceLabels = Array.from({ length: 10 }, (_, index) => paddedMax - (adjustedSpread / 9) * index);
    ctx.fillStyle = "#33383d";
    ctx.font = "12px Cascadia Mono";
    priceLabels.forEach((price) => {
      ctx.fillText(fixed(price), chartRight + 18, priceToY(price) + 4);
    });

    ctx.fillStyle = "#45a749";
    ctx.fillRect(chartRight + 10, currentY - 12, 88, 24);
    ctx.fillStyle = "#ffffff";
    ctx.font = "bold 12px Aptos";
    ctx.fillText(fixed(currentPrice), chartRight + 18, currentY + 4);

    ctx.fillStyle = "rgba(79, 83, 88, 0.18)";
    ctx.font = "600 82px Aptos";
    ctx.textAlign = "center";
    ctx.fillText(payload?.symbol || state.symbol, width / 2, height / 2 + 10);
    ctx.textAlign = "left";

    drawCrosshair();
    updateCursor();
  }

  async function refresh() {
    try {
      const params = new URLSearchParams({
        symbol: state.symbol,
        timeframe: state.timeframe,
      });
      if (state.anchorDate) {
        params.set("anchor_date", state.anchorDate);
      }
      if (state.anchorTime) {
        params.set("anchor_time", state.anchorTime);
      }
      const payload = await fetchJson(`/api/chart-data?${params.toString()}`);
      state.payload = payload;
      drawChart(payload);
    } catch {
      drawChart({
        connection_error: `Could not load ${state.symbol} candles from the local server.`,
        candles: [],
        symbol: state.symbol,
        requested_symbol: state.symbol,
        current_price: 0,
      });
    }
  }

  function addDrawingFromHover() {
    const hover = state.hover;
    if (!hover || hover.inPriceScale) return;
    const point = {
      tool: state.activeTool,
      index: hover.index,
      price: hover.price,
      timeframe: state.timeframe,
      symbol: state.symbol,
    };

    if (isLineTool()) {
      if (!state.pendingShape) {
        state.pendingShape = point;
      } else {
        state.drawings.push({
          ...state.pendingShape,
          index2: point.index,
          price2: point.price,
        });
        state.pendingShape = null;
        persistView();
      }
    } else {
      state.drawings.push(point);
      persistView();
    }

    drawChart(state.payload || {});
  }

  function applyHorizontalZoom(deltaY, mouseX) {
    const all = state.payload?.candles || [];
    if (!all.length || !state.geometry) return;
    const before = getVisibleCandles(all).length;
    const ratio = clamp((mouseX - state.geometry.padding.left) / state.geometry.plotWidth, 0, 1);
    state.zoom = clamp(state.zoom + (deltaY < 0 ? 0.08 : -0.08), -8, 10);
    const after = getVisibleCandles(all).length;
    const diff = after - before;
    state.panOffset = clamp(state.panOffset + Math.round(diff * (1 - ratio)), 0, Math.max(0, all.length - after));
    persistView();
    drawChart(state.payload || {});
  }

  async function toggleFullscreen() {
    const target = els.pageSection;
    if (!target) return;
    if (document.fullscreenElement) {
      await document.exitFullscreen().catch(() => {});
      return;
    }
    await target.requestFullscreen?.().catch(() => {});
  }

  function applySymbolChange() {
    const next = normalizeSymbolInput(els.symbolInput?.value || state.symbol);
    if (!next) return;
    state.symbol = next;
    state.panOffset = 0;
    state.pendingShape = null;
    persistView();
    refresh().catch(() => {});
  }

  function applyPeriodSelection() {
    state.draftTimeframe = (els.periodTimeframe?.value || state.draftTimeframe || state.timeframe || "H1").toUpperCase();
    state.draftDate = String(els.periodDate?.value || "").trim();
    state.draftTime = String(els.periodTime?.value || "").trim();
    state.timeframe = state.draftTimeframe;
    state.anchorDate = state.draftDate;
    state.anchorTime = state.draftTime;
    state.panOffset = 0;
    state.pendingShape = null;
    persistView();
    updateTimeframeButtons();
    refresh().catch(() => {});
  }

  function clearPeriodSelection() {
    state.anchorDate = "";
    state.anchorTime = "";
    state.draftDate = "";
    state.draftTime = "";
    state.draftTimeframe = state.timeframe;
    state.panOffset = 0;
    state.pendingShape = null;
    syncDraftPeriodControls();
    refresh().catch(() => {});
  }

  function updateHoverFromModifiers() {
    if (!state.hoverRaw) return;
    setHover(state.hoverRaw, { ctrlKey: state.ctrlKey, shiftKey: state.shiftKey });
    drawChart(state.payload || {});
  }

  function undoLastAction() {
    if (state.pendingShape) {
      state.pendingShape = null;
    } else {
      const currentIndex = [...state.drawings].reverse().findIndex((drawing) => {
        const symbol = String(drawing.symbol || state.symbol).toUpperCase();
        const timeframe = String(drawing.timeframe || state.timeframe).toUpperCase();
        return symbol === state.symbol.toUpperCase() && timeframe === state.timeframe.toUpperCase();
      });
      if (currentIndex < 0) return;
      const actualIndex = state.drawings.length - 1 - currentIndex;
      state.drawings.splice(actualIndex, 1);
      persistView();
    }
    drawChart(state.payload || {});
  }

  function bind() {
    els.timeframeButtons.forEach((button) => {
      button.addEventListener("click", () => {
        state.timeframe = button.dataset.xauTvTimeframe || "M1";
        state.draftTimeframe = state.timeframe;
        state.panOffset = 0;
        state.pendingShape = null;
        localStorage.setItem(STORAGE.timeframe, state.timeframe);
        syncDraftPeriodControls();
        updateTimeframeButtons();
        refresh().catch(() => {});
      });
    });

    els.symbolLoadButton?.addEventListener("click", () => {
      applySymbolChange();
    });

    els.symbolInput?.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        applySymbolChange();
      }
    });

    els.loadPeriodButton?.addEventListener("click", () => {
      applyPeriodSelection();
    });

    els.liveNowButton?.addEventListener("click", () => {
      clearPeriodSelection();
    });

    els.periodTimeframe?.addEventListener("change", () => {
      state.draftTimeframe = (els.periodTimeframe?.value || "H1").toUpperCase();
      updateTimeframeButtons();
    });

    els.periodDate?.addEventListener("input", () => {
      state.draftDate = String(els.periodDate?.value || "").trim();
    });

    els.periodTime?.addEventListener("input", () => {
      state.draftTime = String(els.periodTime?.value || "").trim();
    });

    els.periodDate?.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        applyPeriodSelection();
      }
    });

    els.periodTime?.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        applyPeriodSelection();
      }
    });

    els.toolButton?.addEventListener("click", (event) => {
      event.stopPropagation();
      state.toolMenuOpen = !state.toolMenuOpen;
      updateToolUi();
    });

    els.toolOptions.forEach((option) => {
      option.addEventListener("click", () => {
        state.activeTool = option.dataset.xauTool || "cross";
        state.pendingShape = null;
        state.toolMenuOpen = false;
        persistView();
        updateToolUi();
        updateCursor();
        drawChart(state.payload || {});
      });
    });

    document.addEventListener("click", (event) => {
      if (!els.toolMenu || !els.toolButton) return;
      if (!els.toolMenu.contains(event.target) && !els.toolButton.contains(event.target)) {
        state.toolMenuOpen = false;
        updateToolUi();
      }
    });

    els.canvas?.addEventListener("mousemove", (event) => {
      const point = canvasPoint(event);
      setHover(point, { ctrlKey: event.ctrlKey, shiftKey: event.shiftKey });
      if (state.dragMode === "pan" && state.geometry) {
        const deltaX = point.x - state.dragStartX;
        const deltaY = point.y - state.dragStartY;
        const moved = Math.round(deltaX / state.geometry.step);
        const all = state.payload?.candles || [];
        const visible = getVisibleCandles(all).length;
        state.panOffset = clamp(state.dragStartPan + moved, 0, Math.max(0, all.length - visible));
        state.verticalPan = state.dragStartVerticalPan + (deltaY / state.geometry.plotHeight) * state.geometry.adjustedSpread;
        persistView();
        drawChart(state.payload || {});
        return;
      }
      if (state.dragMode === "price-scale") {
        const deltaY = point.y - state.dragStartY;
        state.verticalScale = clamp(state.dragStartVerticalScale * (1 - deltaY / 320), 0.35, 5);
        persistView();
        drawChart(state.payload || {});
        return;
      }
      drawChart(state.payload || {});
    });

    els.canvas?.addEventListener("mouseleave", () => {
      if (!state.dragMode) {
        state.hover = null;
        state.hoverRaw = null;
        updateCursor();
        drawChart(state.payload || {});
      }
    });

    els.canvas?.addEventListener("pointerdown", (event) => {
      const point = canvasPoint(event);
      setHover(point, { ctrlKey: event.ctrlKey, shiftKey: event.shiftKey });
      els.canvas.setPointerCapture(event.pointerId);
      if (state.hover?.inPriceScale) {
        state.dragMode = "price-scale";
        state.dragStartY = point.y;
        state.dragStartVerticalScale = state.verticalScale;
        updateCursor();
        return;
      }
      if (state.activeTool === "cross") {
        state.dragMode = "pan";
        state.dragStartX = point.x;
        state.dragStartY = point.y;
        state.dragStartPan = state.panOffset;
        state.dragStartVerticalPan = state.verticalPan;
        updateCursor();
        return;
      }
      addDrawingFromHover();
    });

    els.canvas?.addEventListener("pointerup", (event) => {
      if (els.canvas.hasPointerCapture(event.pointerId)) {
        els.canvas.releasePointerCapture(event.pointerId);
      }
      state.dragMode = null;
      updateCursor();
    });

    els.canvas?.addEventListener("wheel", (event) => {
      if (!state.geometry) return;
      const point = canvasPoint(event);
      setHover(point, { ctrlKey: event.ctrlKey, shiftKey: event.shiftKey });
      event.preventDefault();
      if (state.hover?.inPriceScale) {
        state.verticalScale = clamp(state.verticalScale * (event.deltaY < 0 ? 1.02 : 0.98), 0.35, 5);
        persistView();
        drawChart(state.payload || {});
        return;
      }
      applyHorizontalZoom(event.deltaY, point.x);
    }, { passive: false });

    window.addEventListener("resize", () => {
      if (state.payload) drawChart(state.payload);
    });

    window.addEventListener("keydown", (event) => {
      state.ctrlKey = event.ctrlKey;
      state.shiftKey = event.shiftKey;
      if (event.defaultPrevented) return;
      const target = event.target;
      if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;

      if (event.ctrlKey && String(event.key || "").toLowerCase() === "z") {
        event.preventDefault();
        undoLastAction();
        return;
      }
      if (event.key === "Escape" && state.pendingShape) {
        state.pendingShape = null;
        drawChart(state.payload || {});
        return;
      }
      if (String(event.key || "").toLowerCase() === "f") {
        event.preventDefault();
        toggleFullscreen().catch(() => {});
        return;
      }
      if (event.key === "Control" || event.key === "Shift") {
        updateHoverFromModifiers();
      }
    });

    window.addEventListener("keyup", (event) => {
      state.ctrlKey = event.ctrlKey;
      state.shiftKey = event.shiftKey;
      if (event.key === "Control" || event.key === "Shift") {
        updateHoverFromModifiers();
      }
    });
  }

  function start() {
    if (!els.canvas) return;
    if (els.symbolInput) {
      els.symbolInput.value = state.symbol;
    }
    state.draftTimeframe = state.timeframe;
    syncDraftPeriodControls();
    updateTimeframeButtons();
    updateToolUi();
    bind();
    refresh().catch(() => {});
    window.setInterval(() => {
      refresh().catch(() => {});
    }, 10000);
  }

  start();
})();
