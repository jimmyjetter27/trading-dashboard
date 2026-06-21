(function () {
  if (!document.body || document.body.dataset.currentPage !== "market-intel") {
    return;
  }

  const API_BASE = window.location.protocol === "file:" ? "http://127.0.0.1:8765" : "";
  const STORAGE = {
    symbol: "trade-observer-market-intel-symbol",
    timeframe: "trade-observer-market-intel-timeframe",
    sessionFocus: "trade-observer-market-intel-session-focus",
    macroPrefix: "trade-observer-market-intel-macro",
  };

  const state = {
    symbol: (localStorage.getItem(STORAGE.symbol) || "XAUUSD").trim() || "XAUUSD",
    timeframe: localStorage.getItem(STORAGE.timeframe) || "H1",
    sessionFocus: localStorage.getItem(STORAGE.sessionFocus) || "auto",
    payload: null,
  };

  const els = {
    statusPill: document.querySelector("#marketIntelStatusPill"),
    symbolInput: document.querySelector("#marketIntelSymbolInput"),
    timeframeSelect: document.querySelector("#marketIntelTimeframeSelect"),
    sessionFocusSelect: document.querySelector("#marketIntelSessionFocusSelect"),
    refreshButton: document.querySelector("#marketIntelRefreshButton"),
    symbol: document.querySelector("#marketIntelSymbol"),
    bias: document.querySelector("#marketIntelBias"),
    confidence: document.querySelector("#marketIntelConfidence"),
    price: document.querySelector("#marketIntelPrice"),
    summary: document.querySelector("#marketIntelSummary"),
    newsBrief: document.querySelector("#marketIntelNewsBrief"),
    regime: document.querySelector("#marketIntelRegime"),
    session: document.querySelector("#marketIntelSession"),
    predictionDirection: document.querySelector("#marketIntelPredictionDirection"),
    predictionScore: document.querySelector("#marketIntelPredictionScore"),
    primaryRisk: document.querySelector("#marketIntelPrimaryRisk"),
    primaryRiskDetail: document.querySelector("#marketIntelPrimaryRiskDetail"),
    primaryOpportunity: document.querySelector("#marketIntelPrimaryOpportunity"),
    primaryOpportunityDetail: document.querySelector("#marketIntelPrimaryOpportunityDetail"),
    indicators: document.querySelector("#marketIntelIndicators"),
    sessionModels: document.querySelector("#marketIntelSessionModels"),
    journalBridge: document.querySelector("#marketIntelJournalBridge"),
    liquidity: document.querySelector("#marketIntelLiquidity"),
    scenarios: document.querySelector("#marketIntelScenarios"),
    watchlist: document.querySelector("#marketIntelWatchlist"),
    confluences: document.querySelector("#marketIntelConfluences"),
    macroImpactSelect: document.querySelector("#marketIntelMacroImpactSelect"),
    macroNotesInput: document.querySelector("#marketIntelMacroNotesInput"),
    macroSavedState: document.querySelector("#marketIntelMacroSavedState"),
    saveMacroNotesButton: document.querySelector("#marketIntelSaveMacroNotesButton"),
    canvas: document.querySelector("#marketIntelCanvas"),
  };

  const ctx = els.canvas?.getContext("2d");

  function fixed(value, digits = 2) {
    const numeric = Number(value || 0);
    return Number.isFinite(numeric) ? numeric.toFixed(digits) : "-";
  }

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function macroStorageKey() {
    return `${STORAGE.macroPrefix}:${state.symbol.toUpperCase()}:${state.timeframe}:${state.sessionFocus}`;
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

  function toneClass(tone) {
    return tone === "bullish" || tone === "support" || tone === "london" || tone === "aligned" ? "support"
      : tone === "bearish" || tone === "resistance" || tone === "new-york" || tone === "risk" ? "resistance"
      : "neutral";
  }

  function renderList(target, items, builder, emptyMessage) {
    if (!target) return;
    if (!items || !items.length) {
      target.innerHTML = `<div class="empty-state">${emptyMessage}</div>`;
      return;
    }
    target.innerHTML = items.map(builder).join("");
  }

  function loadMacroNotes() {
    const raw = localStorage.getItem(macroStorageKey());
    if (!raw) {
      if (els.macroImpactSelect) els.macroImpactSelect.value = "neutral";
      if (els.macroNotesInput) els.macroNotesInput.value = "";
      return;
    }
    try {
      const parsed = JSON.parse(raw);
      if (els.macroImpactSelect) els.macroImpactSelect.value = parsed.impact || "neutral";
      if (els.macroNotesInput) els.macroNotesInput.value = parsed.notes || "";
    } catch {
      if (els.macroImpactSelect) els.macroImpactSelect.value = "neutral";
      if (els.macroNotesInput) els.macroNotesInput.value = "";
    }
  }

  function saveMacroNotes() {
    const payload = {
      impact: els.macroImpactSelect?.value || "neutral",
      notes: String(els.macroNotesInput?.value || "").trim(),
      saved_at: new Date().toISOString(),
    };
    localStorage.setItem(macroStorageKey(), JSON.stringify(payload));
    if (els.macroSavedState) {
      els.macroSavedState.textContent = `Saved for ${state.symbol.toUpperCase()} ${state.timeframe} (${state.sessionFocus}).`;
    }
  }

  function drawChart(payload) {
    if (!ctx || !els.canvas) return;
    const canvas = els.canvas;
    const width = Math.max(540, canvas.clientWidth || canvas.width);
    const height = Math.max(360, Math.round(width * 0.42));
    canvas.width = width;
    canvas.height = height;
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = getComputedStyle(document.body).getPropertyValue("--panel-soft");
    ctx.fillRect(0, 0, width, height);

    const candles = payload?.candles || [];
    if (!candles.length) {
      ctx.fillStyle = getComputedStyle(document.body).getPropertyValue("--muted");
      ctx.font = "18px Aptos";
      ctx.fillText(payload?.connection_error || "Waiting for Market Intel candle data...", 24, height / 2);
      return;
    }

    const padding = { top: 22, right: 96, bottom: 28, left: 48 };
    const highs = candles.map((item) => Number(item.high));
    const lows = candles.map((item) => Number(item.low));
    const maxPrice = Math.max(...highs);
    const minPrice = Math.min(...lows);
    const spread = Math.max(maxPrice - minPrice, 0.01);
    const plotWidth = width - padding.left - padding.right;
    const plotHeight = height - padding.top - padding.bottom;
    const candleWidth = Math.max(4, plotWidth / candles.length * 0.74);

    (payload?.zones || []).forEach((zone) => {
      const topY = padding.top + ((maxPrice - Number(zone.high)) / spread) * plotHeight;
      const bottomY = padding.top + ((maxPrice - Number(zone.low)) / spread) * plotHeight;
      const zoneY = Math.min(topY, bottomY);
      const zoneHeight = Math.max(8, Math.abs(bottomY - topY));
      const fill = zone.kind === "support"
        ? "rgba(75, 240, 179, 0.12)"
        : zone.kind === "resistance"
          ? "rgba(255, 107, 122, 0.12)"
          : "rgba(105, 211, 255, 0.10)";
      const stroke = zone.kind === "support"
        ? "rgba(75, 240, 179, 0.9)"
        : zone.kind === "resistance"
          ? "rgba(255, 107, 122, 0.9)"
          : "rgba(105, 211, 255, 0.85)";
      ctx.fillStyle = fill;
      ctx.fillRect(padding.left, zoneY, plotWidth, zoneHeight);
      ctx.strokeStyle = stroke;
      ctx.setLineDash([7, 5]);
      ctx.strokeRect(padding.left, zoneY, plotWidth, zoneHeight);
      ctx.setLineDash([]);
    });

    candles.forEach((candle, index) => {
      const centerX = padding.left + (index + 0.5) * (plotWidth / candles.length);
      const open = Number(candle.open);
      const close = Number(candle.close);
      const high = Number(candle.high);
      const low = Number(candle.low);
      const bullish = close >= open;
      const color = bullish
        ? getComputedStyle(document.body).getPropertyValue("--accent-2").trim()
        : getComputedStyle(document.body).getPropertyValue("--danger").trim();
      const yHigh = padding.top + ((maxPrice - high) / spread) * plotHeight;
      const yLow = padding.top + ((maxPrice - low) / spread) * plotHeight;
      const yOpen = padding.top + ((maxPrice - open) / spread) * plotHeight;
      const yClose = padding.top + ((maxPrice - close) / spread) * plotHeight;

      ctx.strokeStyle = color;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(centerX, yHigh);
      ctx.lineTo(centerX, yLow);
      ctx.stroke();

      ctx.fillStyle = color;
      ctx.fillRect(centerX - candleWidth / 2, Math.min(yOpen, yClose), candleWidth, Math.max(2, Math.abs(yClose - yOpen)));
    });

    const currentPrice = Number(payload?.current_price || candles.at(-1)?.close || 0);
    const liveY = padding.top + ((maxPrice - currentPrice) / spread) * plotHeight;
    ctx.strokeStyle = "rgba(105, 211, 255, 0.9)";
    ctx.lineWidth = 1.4;
    ctx.beginPath();
    ctx.moveTo(padding.left, liveY);
    ctx.lineTo(width - padding.right + 8, liveY);
    ctx.stroke();
    ctx.fillStyle = "rgba(105, 211, 255, 0.96)";
    ctx.fillRect(width - padding.right + 10, liveY - 12, 74, 22);
    ctx.fillStyle = "#04131c";
    ctx.font = "12px Aptos";
    ctx.fillText(fixed(currentPrice), width - padding.right + 18, liveY + 4);

    ctx.fillStyle = getComputedStyle(document.body).getPropertyValue("--text");
    ctx.font = "12px Cascadia Mono";
    [maxPrice, (maxPrice + minPrice) / 2, minPrice].forEach((price) => {
      const y = padding.top + ((maxPrice - Number(price)) / spread) * plotHeight;
      ctx.fillText(fixed(price), width - padding.right + 16, y + 4);
    });
  }

  function renderIntel(payload) {
    state.payload = payload;
    if (els.statusPill) {
      els.statusPill.textContent = payload?.connection_error ? "Data Blocked" : "Live Read Ready";
      els.statusPill.classList.toggle("ok", !payload?.connection_error);
    }
    if (els.symbol) els.symbol.textContent = payload?.symbol || state.symbol;
    if (els.bias) {
      els.bias.textContent = String(payload?.bias || "neutral").toUpperCase();
      els.bias.className = payload?.bias === "bullish" ? "positive" : payload?.bias === "bearish" ? "negative" : "";
    }
    if (els.confidence) els.confidence.textContent = `${Math.round(Number(payload?.confidence || 0))}%`;
    if (els.price) els.price.textContent = payload?.current_price ? fixed(payload.current_price) : "-";
    if (els.summary) {
      const direction = payload?.prediction?.direction || "neutral";
      els.summary.textContent = payload?.ai_summary || "Market Intel summary is unavailable.";
      els.summary.className = `analysis-banner ${direction}`;
    }
    if (els.newsBrief) els.newsBrief.textContent = payload?.news_brief || "";
    if (els.regime) els.regime.textContent = String(payload?.regime || "unknown").replace(/\b\w/g, (char) => char.toUpperCase());
    if (els.session) els.session.textContent = payload?.session_focus_label || payload?.active_session || "No major market open";
    if (els.predictionDirection) els.predictionDirection.textContent = String(payload?.prediction?.direction || "neutral").toUpperCase();
    if (els.predictionScore) els.predictionScore.textContent = `Score ${payload?.prediction?.score ?? 0}`;

    const topScenario = Array.isArray(payload?.scenario_cards) && payload.scenario_cards.length
      ? [...payload.scenario_cards].sort((a, b) => Number(b.confidence || 0) - Number(a.confidence || 0))[0]
      : null;
    const riskScenario = Array.isArray(payload?.scenario_cards) && payload.scenario_cards.length
      ? [...payload.scenario_cards].sort((a, b) => Number(a.confidence || 0) - Number(b.confidence || 0))[0]
      : null;
    if (els.primaryOpportunity) els.primaryOpportunity.textContent = topScenario?.title || "Waiting...";
    if (els.primaryOpportunityDetail) els.primaryOpportunityDetail.textContent = topScenario?.target || "The strongest scenario target will appear here.";
    if (els.primaryRisk) els.primaryRisk.textContent = riskScenario?.title || "Waiting...";
    if (els.primaryRiskDetail) els.primaryRiskDetail.textContent = riskScenario?.invalidation || "The first invalidation point will appear here.";

    renderList(
      els.indicators,
      payload?.indicator_board || [],
      (item) => `
        <article class="analysis-item ${toneClass(item.tone)}">
          <strong>${item.label}</strong>
          <p>${item.value}</p>
        </article>
      `,
      payload?.connection_error || "Indicator reads will appear once MT5 data loads."
    );

    renderList(
      els.sessionModels,
      payload?.session_models || [],
      (item) => `
        <article class="analysis-item ${toneClass(item.tone)}">
          <strong>${item.title}</strong>
          <p>${item.explanation}</p>
          <p><strong>Trigger:</strong> ${item.trigger}</p>
          <p><strong>Ideal if:</strong> ${item.ideal_if}</p>
        </article>
      `,
      "Session-specific models will appear here."
    );

    renderList(
      els.journalBridge,
      payload?.journal_bridge?.cards || [],
      (item) => `
        <article class="analysis-item ${toneClass(item.tone)}">
          <strong>${item.title}</strong>
          <p>${item.value}</p>
          <p>${item.detail}</p>
        </article>
      `,
      "Once you have MT5 history cached, this section will compare the current read with your recent trading behavior."
    );

    renderList(
      els.liquidity,
      payload?.liquidity_map || [],
      (item) => `
        <article class="analysis-item ${toneClass(item.kind)}">
          <strong>${item.label}</strong>
          <p>${fixed(item.price)}${item.detail ? ` | ${item.detail}` : ""}</p>
        </article>
      `,
      "Liquidity levels will appear here."
    );

    renderList(
      els.scenarios,
      payload?.scenario_cards || [],
      (item) => `
        <article class="analysis-item ${toneClass(item.direction)}">
          <strong>${item.title}</strong>
          <p><strong>Trigger:</strong> ${item.trigger}</p>
          <p><strong>Invalidation:</strong> ${item.invalidation}</p>
          <p><strong>Target:</strong> ${item.target}</p>
          <p><strong>Confidence:</strong> ${Math.round(Number(item.confidence || 0))}%</p>
        </article>
      `,
      "Scenario cards will appear here."
    );

    renderList(
      els.watchlist,
      payload?.what_to_watch || [],
      (item) => `<article class="analysis-item neutral"><p>${item}</p></article>`,
      "What to watch next will appear here."
    );

    renderList(
      els.confluences,
      payload?.confluences || [],
      (item) => `
        <article class="analysis-item ${toneClass(item.tone)}">
          <strong>${item.title}</strong>
          <p>${item.detail}</p>
        </article>
      `,
      payload?.connection_error || "Confluence notes will appear once live data loads."
    );

    drawChart(payload);
  }

  async function refreshIntel() {
    try {
      const payload = await fetchJson(
        `/api/market-intel?symbol=${encodeURIComponent(state.symbol)}&timeframe=${encodeURIComponent(state.timeframe)}&session_focus=${encodeURIComponent(state.sessionFocus)}`
      );
      renderIntel(payload);
    } catch (error) {
      renderIntel({
        symbol: state.symbol,
        timeframe: state.timeframe,
        candles: [],
        confluences: [],
        connection_error: error.message || "Could not load Market Intel data.",
        prediction: { direction: "neutral", score: 0 },
        confidence: 0,
      });
    }
  }

  function bind() {
    els.symbolInput?.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        state.symbol = String(els.symbolInput.value || "XAUUSD").trim().toUpperCase() || "XAUUSD";
        localStorage.setItem(STORAGE.symbol, state.symbol);
        loadMacroNotes();
        refreshIntel().catch(() => {});
      }
    });

    els.timeframeSelect?.addEventListener("change", () => {
      state.timeframe = els.timeframeSelect.value || "H1";
      localStorage.setItem(STORAGE.timeframe, state.timeframe);
      loadMacroNotes();
      refreshIntel().catch(() => {});
    });

    els.sessionFocusSelect?.addEventListener("change", () => {
      state.sessionFocus = els.sessionFocusSelect.value || "auto";
      localStorage.setItem(STORAGE.sessionFocus, state.sessionFocus);
      loadMacroNotes();
      refreshIntel().catch(() => {});
    });

    els.refreshButton?.addEventListener("click", () => {
      state.symbol = String(els.symbolInput?.value || state.symbol).trim().toUpperCase() || "XAUUSD";
      localStorage.setItem(STORAGE.symbol, state.symbol);
      loadMacroNotes();
      refreshIntel().catch(() => {});
    });

    els.saveMacroNotesButton?.addEventListener("click", () => {
      saveMacroNotes();
    });

    window.addEventListener("resize", () => {
      if (state.payload) {
        drawChart(state.payload);
      }
    });
  }

  function start() {
    if (els.symbolInput) els.symbolInput.value = state.symbol;
    if (els.timeframeSelect) els.timeframeSelect.value = state.timeframe;
    if (els.sessionFocusSelect) els.sessionFocusSelect.value = state.sessionFocus;
    loadMacroNotes();
    bind();
    refreshIntel().catch(() => {});
    window.setInterval(() => {
      refreshIntel().catch(() => {});
    }, 15000);
  }

  start();
})();
