(function () {
  if (!document.body || document.body.dataset.currentPage !== "liquidity-sweeps") {
    return;
  }

  const API_BASE = window.location.protocol === "file:" ? "http://127.0.0.1:8765" : "";
  const STORAGE = {
    timeframe: "trade-observer-sweep-timeframe",
    symbol: "trade-observer-sweep-symbol",
    zoom: "trade-observer-sweep-zoom",
    pan: "trade-observer-sweep-pan",
    vertical: "trade-observer-sweep-vertical-scale",
    verticalPan: "trade-observer-sweep-vertical-pan",
    mode: "trade-observer-sweep-mode",
  };

  const state = {
    timeframe: localStorage.getItem(STORAGE.timeframe) || "H1",
    symbol: (localStorage.getItem(STORAGE.symbol) || "XAUUSD").trim() || "XAUUSD",
    mode: localStorage.getItem(STORAGE.mode) || "live",
    payload: null,
    frozenPayload: null,
    zoom: Number(localStorage.getItem(STORAGE.zoom) || 0),
    panOffset: Number(localStorage.getItem(STORAGE.pan) || 0),
    verticalScale: Number(localStorage.getItem(STORAGE.vertical) || 1),
    verticalPan: Number(localStorage.getItem(STORAGE.verticalPan) || 0),
    geometry: null,
    dragMode: null,
    dragStartX: 0,
    dragStartY: 0,
    dragStartPan: 0,
    dragStartVerticalPan: 0,
    dragStartVerticalScale: 1,
    lastSweepKey: "",
    audioCtx: null,
    activeAlarmInterval: null,
  };

  const els = {
    canvas: document.querySelector("#sweepCanvas"),
    symbolInput: document.querySelector("#sweepSymbolInput"),
    refreshButton: document.querySelector("#sweepRefreshButton"),
    timeframeButtons: [...document.querySelectorAll("[data-sweep-timeframe]")],
    modeButtons: [...document.querySelectorAll("[data-sweep-mode]")],
    statusPill: document.querySelector("#sweepStatusPill"),
    resolvedSymbol: document.querySelector("#sweepResolvedSymbol"),
    currentTimeframe: document.querySelector("#sweepCurrentTimeframe"),
    currentPrice: document.querySelector("#sweepCurrentPrice"),
    titleSymbol: document.querySelector("#sweepTitleSymbol"),
    subtitle: document.querySelector("#sweepSubtitle"),
    headerPrice: document.querySelector("#sweepHeaderPrice"),
    latestLabel: document.querySelector("#sweepLatestLabel"),
    latestMeta: document.querySelector("#sweepLatestMeta"),
    visibleCount: document.querySelector("#sweepVisibleCount"),
    visibleMeta: document.querySelector("#sweepVisibleMeta"),
    modeText: document.querySelector("#sweepModeText"),
    modeMeta: document.querySelector("#sweepModeMeta"),
    biasCards: document.querySelector("#sweepBiasCards"),
    adviceCards: document.querySelector("#sweepAdviceCards"),
    eventsList: document.querySelector("#sweepEventsList"),
    alarmModal: document.querySelector("#sweepAlarmModal"),
    alarmDialog: document.querySelector("#sweepAlarmDialog"),
    alarmKicker: document.querySelector("#sweepAlarmKicker"),
    alarmTitle: document.querySelector("#sweepAlarmTitle"),
    alarmMessage: document.querySelector("#sweepAlarmMessage"),
    alarmTradeMeta: document.querySelector("#sweepAlarmTradeMeta"),
    alarmTimeMeta: document.querySelector("#sweepAlarmTimeMeta"),
    stopAlarmButton: document.querySelector("#sweepStopAlarmButton"),
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

  function getAudioContext() {
    if (state.audioCtx) {
      return state.audioCtx;
    }
    const AudioCtor = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtor) {
      return null;
    }
    state.audioCtx = new AudioCtor();
    return state.audioCtx;
  }

  function playSweepAlert() {
    try {
      const audio = getAudioContext();
      if (!audio) return;
      if (audio.state === "suspended") {
        audio.resume().catch(() => {});
      }
      const tones = [
        { frequency: 660, start: 0, duration: 0.18 },
        { frequency: 990, start: 0.18, duration: 0.18 },
        { frequency: 770, start: 0.36, duration: 0.18 },
      ];
      const now = audio.currentTime;
      tones.forEach((tone) => {
        const oscillator = audio.createOscillator();
        const gain = audio.createGain();
        oscillator.type = "sine";
        oscillator.frequency.setValueAtTime(tone.frequency, now + tone.start);
        gain.gain.setValueAtTime(0.0001, now + tone.start);
        gain.gain.exponentialRampToValueAtTime(0.18, now + tone.start + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + tone.start + tone.duration);
        oscillator.connect(gain);
        gain.connect(audio.destination);
        oscillator.start(now + tone.start);
        oscillator.stop(now + tone.start + tone.duration + 0.03);
      });
    } catch {
      // Keep the detector running even if audio is blocked.
    }
  }

  function stopSweepAlarmLoop() {
    if (state.activeAlarmInterval) {
      clearInterval(state.activeAlarmInterval);
      state.activeAlarmInterval = null;
    }
  }

  function closeSweepAlarmModal() {
    if (!els.alarmModal) return;
    els.alarmModal.classList.add("hidden");
    els.alarmModal.setAttribute("aria-hidden", "true");
  }

  function formatLatestSweepMessage(event) {
    const isBuy = String(event?.side || "").toLowerCase() === "buy";
    const bias = isBuy ? "Bullish reversal watch." : "Bearish reversal watch.";
    const trigger = isBuy
      ? "Wait for a bullish reclaim or retest hold above the swept low before considering an entry."
      : "Wait for a bearish reclaim or retest failure below the swept high before considering an entry.";
    return `${bias} ${trigger}`;
  }

  function openSweepAlarmModal(event) {
    if (!els.alarmModal || !event) return;
    const isBuy = String(event.side || "").toLowerCase() === "buy";
    els.alarmDialog?.classList.toggle("negative", !isBuy);
    els.alarmDialog?.classList.toggle("positive", isBuy);
    if (els.alarmKicker) {
      els.alarmKicker.textContent = event.source_type === "engineered" ? "Engineered Sweep" : "Local Sweep";
    }
    if (els.alarmTitle) {
      els.alarmTitle.textContent = `${event.label} detected`;
    }
    if (els.alarmMessage) {
      els.alarmMessage.textContent = formatLatestSweepMessage(event);
    }
    if (els.alarmTradeMeta) {
      els.alarmTradeMeta.textContent = `${String(event.side || "").toUpperCase()} | ${event.level_period || "context"} | confidence ${event.confidence || 0}`;
    }
    if (els.alarmTimeMeta) {
      els.alarmTimeMeta.textContent = new Date(event.time).toLocaleString();
    }
    els.alarmModal.classList.remove("hidden");
    els.alarmModal.setAttribute("aria-hidden", "false");
  }

  function triggerSweepAlert(event) {
    openSweepAlarmModal(event);
    stopSweepAlarmLoop();
    playSweepAlert();
    state.activeAlarmInterval = setInterval(() => {
      playSweepAlert();
    }, 6000);
  }

  function timeframeLabel(value) {
    const labels = {
      M1: "1m",
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

  function persistView() {
    localStorage.setItem(STORAGE.timeframe, state.timeframe);
    localStorage.setItem(STORAGE.symbol, state.symbol);
    localStorage.setItem(STORAGE.zoom, String(state.zoom));
    localStorage.setItem(STORAGE.pan, String(state.panOffset));
    localStorage.setItem(STORAGE.vertical, String(state.verticalScale));
    localStorage.setItem(STORAGE.verticalPan, String(state.verticalPan));
    localStorage.setItem(STORAGE.mode, state.mode);
  }

  function currentPayload() {
    return state.mode === "frozen" ? (state.frozenPayload || state.payload) : state.payload;
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
    return upper || "Liquidity Board";
  }

  function candleTime(candle) {
    const parsed = Date.parse(candle?.time || "");
    return Number.isFinite(parsed) ? parsed : 0;
  }

  function getVisibleCandles(candles) {
    const all = Array.isArray(candles) ? candles : [];
    if (!all.length) return [];
    const width = els.canvas?.clientWidth || 1200;
    const baseCount = Math.max(34, Math.min(190, Math.floor(width / 12.5)));
    const zoomFactor = Math.pow(1.1, state.zoom);
    const visibleCount = clamp(Math.round(baseCount * zoomFactor), 28, all.length);
    const maxPan = Math.max(0, all.length - visibleCount);
    state.panOffset = clamp(state.panOffset, 0, maxPan);
    const end = all.length - state.panOffset;
    const start = Math.max(0, end - visibleCount);
    return all.slice(start, end);
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

  function drawLevelLabel(text, x, y, fillStyle) {
    ctx.font = "bold 12px Aptos";
    const width = Math.min(220, Math.max(112, ctx.measureText(text).width + 18));
    ctx.fillStyle = fillStyle;
    ctx.fillRect(x, y - 13, width, 24);
    ctx.fillStyle = "#ffffff";
    ctx.fillText(text, x + 8, y + 4);
  }

  function findActiveLevelsAt(levels, timeIso) {
    const time = Date.parse(timeIso || "");
    if (!Number.isFinite(time) || !Array.isArray(levels)) return [];
    return levels.filter((level) => {
      const start = Date.parse(level.start_time || "");
      const end = Date.parse(level.end_time || "");
      return Number.isFinite(start) && Number.isFinite(end) && start <= time && time < end;
    });
  }

  function levelIndexRange(level, candles) {
    const start = Date.parse(level.start_time || "");
    const end = Date.parse(level.end_time || "");
    if (!Number.isFinite(start) || !Number.isFinite(end)) return null;
    let first = -1;
    let last = -1;
    candles.forEach((candle, index) => {
      const time = candleTime(candle);
      if (time >= start && time < end) {
        if (first === -1) first = index;
        last = index;
      }
    });
    if (first === -1 || last === -1) return null;
    return { first, last };
  }

  function drawRollingLevels(levels, geo, colors) {
    if (!Array.isArray(levels) || !levels.length) return;
    levels.forEach((level) => {
      const range = levelIndexRange(level, geo.candles);
      if (!range) return;
      const x1 = geo.padding.left + range.first * geo.step + geo.step * 0.5;
      const x2 = geo.padding.left + range.last * geo.step + geo.step * 0.5;
      const high = Number(level.previous_high);
      const low = Number(level.previous_low);
      const labelCodeH = String(level.high_code || "PDH");
      const labelCodeL = String(level.low_code || "PDL");
      const lines = [
        { price: high, label: `${labelCodeH} ${fixed(high)}`, color: colors.high, dash: [10, 6] },
        { price: low, label: `${labelCodeL} ${fixed(low)}`, color: colors.low, dash: [6, 5] },
      ];
      lines.forEach((item) => {
        if (!Number.isFinite(item.price)) return;
        const y = geo.priceToY(item.price);
        if (y < geo.padding.top - 2 || y > geo.chartBottom + 2) return;
        ctx.save();
        ctx.setLineDash(item.dash);
        ctx.strokeStyle = item.color;
        ctx.lineWidth = 1.6;
        ctx.beginPath();
        ctx.moveTo(x1, y);
        ctx.lineTo(x2, y);
        ctx.stroke();
        ctx.setLineDash([]);
        drawLevelLabel(item.label, clamp(x2 - 148, geo.padding.left + 6, geo.chartRight - 160), y, item.color);
        ctx.restore();
      });
    });
  }

  function visibleSweepEvents(payload, candles) {
    const all = Array.isArray(payload?.liquidity_sweeps) ? payload.liquidity_sweeps : [];
    if (!candles.length) return [];
    const first = candleTime(candles[0]);
    const last = candleTime(candles[candles.length - 1]);
    return all.filter((event) => {
      const time = Date.parse(event.time || "");
      return Number.isFinite(time) && time >= first && time <= last;
    });
  }

  function cappedVisibleEvents(payload, candles) {
    const visible = visibleSweepEvents(payload, candles);
    const limit = state.mode === "frozen" ? 14 : 5;
    return visible.slice(-limit);
  }

  function buildLatestSweepRead(payload) {
    const all = Array.isArray(payload?.liquidity_sweeps) ? payload.liquidity_sweeps : [];
    const latest = all.length ? all[all.length - 1] : null;
    if (!latest) {
      return {
        biasCards: [
          {
            title: "No active sweep read",
            body: "Live mode is scanning for a candle that raids liquidity and closes back through the level.",
            tone: "neutral",
          },
        ],
        adviceCards: [
          {
            title: "Stand by",
            body: "Wait for a fresh sweep. Once one appears, this panel will reduce it to a short execution note.",
            tone: "neutral",
          },
        ],
      };
    }

    const isBuy = String(latest.side || "").toLowerCase() === "buy";
    const bias = isBuy ? "Bullish reversal watch" : "Bearish reversal watch";
    const periodText = latest.level_period ? `${latest.level_period} liquidity` : "liquidity";
    const sourceText = latest.source_type === "engineered" ? "engineered sweep" : "local sweep";
    const confidence = Number(latest.confidence || 0);
    const note = latest.note || `${sourceText} detected`;
    const entryText = isBuy
      ? "Wait for one strong bullish close or a small retest above the reclaimed low. Enter only if price keeps holding above the sweep level."
      : "Wait for one strong bearish close or a small retest below the reclaimed high. Enter only if price stays below the sweep level.";
    const invalidationText = isBuy
      ? "Risk stays below the sweep low. If price loses that reclaimed level, stand aside."
      : "Risk stays above the sweep high. If price reclaims that level again, stand aside.";
    const triggerText = isBuy
      ? "Best trigger: bullish shift after the raid, then a clean continuation candle."
      : "Best trigger: bearish shift after the raid, then a clean continuation candle.";

    return {
      biasCards: [
        {
          title: bias,
          body: `${sourceText} into ${periodText}. Confidence ${confidence}. ${note}`,
          tone: isBuy ? "support" : "resistance",
        },
        {
          title: "Context",
          body: `${latest.label} fired at ${new Date(latest.time).toLocaleString()}. Treat this as a sweep-and-reclaim setup, not an instant entry.`,
          tone: "neutral",
        },
      ],
      adviceCards: [
        {
          title: "Entry",
          body: entryText,
          tone: isBuy ? "support" : "resistance",
        },
        {
          title: "Invalidation",
          body: `${invalidationText} ${triggerText}`,
          tone: "neutral",
        },
      ],
    };
  }

  function renderQuickRead(payload) {
    const read = buildLatestSweepRead(payload);
    if (els.biasCards) {
      els.biasCards.innerHTML = read.biasCards.map((card) => `
        <article class="analysis-item ${card.tone}">
          <strong>${card.title}</strong>
          <p>${card.body}</p>
        </article>
      `).join("");
    }
    if (els.adviceCards) {
      els.adviceCards.innerHTML = read.adviceCards.map((card) => `
        <article class="analysis-item ${card.tone}">
          <strong>${card.title}</strong>
          <p>${card.body}</p>
        </article>
      `).join("");
    }
  }

  function drawSweepEvents(events, geo) {
    if (!events.length) return;
    const candleIndexByTime = new Map(geo.candles.map((candle, index) => [candle.time, index]));
    events.forEach((event) => {
      const index = candleIndexByTime.get(event.time);
      if (index == null) return;
      const x = geo.padding.left + index * geo.step + geo.step * 0.5;
      const y = geo.priceToY(Number(event.price));
      const bandWidth = Math.max(8, geo.step * 0.72);
      ctx.save();
      ctx.fillStyle = "rgba(0, 0, 0, 0.08)";
      ctx.fillRect(x - bandWidth / 2, geo.padding.top, bandWidth, geo.plotHeight);
      ctx.strokeStyle = "rgba(17, 17, 17, 0.88)";
      ctx.lineWidth = 1.7;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(x, geo.padding.top);
      ctx.lineTo(x, geo.chartBottom);
      ctx.moveTo(x, y);
      ctx.lineTo(geo.chartRight, y);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = "#111111";
      ctx.beginPath();
      ctx.arc(x, y, 4.5, 0, Math.PI * 2);
      ctx.fill();
      drawLevelLabel(`${event.label} | ${String(event.side || "").toUpperCase()}`, clamp(x + 10, geo.padding.left + 10, geo.chartRight - 180), y, "rgba(17,17,17,0.88)");
      ctx.restore();
    });
  }

  function renderMeta(payload, visibleEvents) {
    const resolved = payload?.symbol || state.symbol || "XAUUSD";
    const requested = payload?.requested_symbol || state.symbol || resolved;
    const currentPrice = Number(payload?.current_price || 0);
    const latest = Array.isArray(payload?.liquidity_sweeps) && payload.liquidity_sweeps.length ? payload.liquidity_sweeps[payload.liquidity_sweeps.length - 1] : null;

    if (els.resolvedSymbol) els.resolvedSymbol.textContent = resolved;
    if (els.currentTimeframe) els.currentTimeframe.textContent = timeframeLabel(state.timeframe);
    if (els.currentPrice) els.currentPrice.textContent = currentPrice ? fixed(currentPrice) : "-";
    if (els.titleSymbol) els.titleSymbol.textContent = displaySymbolName(resolved);
    if (els.subtitle) {
      els.subtitle.textContent = state.mode === "frozen"
        ? `${resolved} | ${timeframeLabel(state.timeframe)} | frozen sweep snapshot`
        : `${resolved} | ${timeframeLabel(state.timeframe)} | live sweep scan`;
    }
    if (els.headerPrice) {
      els.headerPrice.textContent = currentPrice
        ? `Current price ${fixed(currentPrice)}`
        : (payload?.connection_error || "Waiting for candles...");
    }
    if (els.symbolInput && document.activeElement !== els.symbolInput) {
      els.symbolInput.value = requested;
    }
    if (els.modeText) els.modeText.textContent = state.mode === "frozen" ? "Frozen" : "Live";
    if (els.modeMeta) {
      els.modeMeta.textContent = state.mode === "frozen"
        ? "Frozen mode keeps the current snapshot while you pan back through earlier sweeps."
        : "Live mode keeps fetching fresh candles and new sweep detections.";
    }
    if (els.visibleCount) els.visibleCount.textContent = String(visibleEvents.length);
    if (els.visibleMeta) {
      if (!visibleEvents.length) {
        els.visibleMeta.textContent = "No visible sweep candles in the current chart window.";
      } else if (state.mode === "live") {
        els.visibleMeta.textContent = `Live view keeps the latest setup plus ${Math.max(0, visibleEvents.length - 1)} recent sweeps for context.`;
      } else {
        els.visibleMeta.textContent = `${visibleEvents.filter((item) => item.source_type === "engineered").length} engineered and ${visibleEvents.filter((item) => item.source_type !== "engineered").length} local sweeps in the frozen window.`;
      }
    }
    if (els.latestLabel) els.latestLabel.textContent = latest ? latest.label : "Waiting...";
    if (els.latestMeta) {
      els.latestMeta.textContent = latest
        ? `${String(latest.side || "").toUpperCase()} bias | ${latest.level_period} | confidence ${latest.confidence}`
        : "No sweep detected yet.";
    }
    if (els.statusPill) {
      els.statusPill.textContent = latest ? `Latest: ${latest.label}` : (payload?.connection_error ? "Data Blocked" : "Scanning...");
      els.statusPill.classList.toggle("ok", !!latest && !payload?.connection_error);
    }
  }

  function renderEventsList(payload, visibleEvents) {
    if (!els.eventsList) return;
    const limit = state.mode === "frozen" ? 12 : 5;
    const latest = visibleEvents.slice().reverse().slice(0, limit);
    if (!latest.length) {
      els.eventsList.innerHTML = `<div class="empty-state">${payload?.connection_error || "No liquidity sweeps are visible in the current chart window yet."}</div>`;
      return;
    }
    els.eventsList.innerHTML = latest.map((event) => `
      <article class="analysis-item ${event.side === "buy" ? "support" : "resistance"}">
        <strong>${event.label}</strong>
        <p>${new Date(event.time).toLocaleString()} | ${String(event.side || "").toUpperCase()} | ${event.level_period}</p>
        <p>${event.note}</p>
      </article>
    `).join("");
  }

  function drawChart(payload) {
    if (!ctx || !els.canvas) return;
    const width = Math.max(1220, els.canvas.clientWidth || els.canvas.width);
    const height = Math.max(760, Math.round(width * 0.56));
    els.canvas.width = width;
    els.canvas.height = height;
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = "#c8c8c8";
    ctx.fillRect(0, 0, width, height);

    const candles = getVisibleCandles(payload?.candles || []);
    if (!candles.length) {
      ctx.fillStyle = "#4f5358";
      ctx.font = "22px Aptos";
      ctx.fillText(payload?.connection_error || `Waiting for ${state.symbol} candles...`, 28, height / 2);
      state.geometry = null;
      renderMeta(payload, []);
      renderQuickRead(payload);
      renderEventsList(payload, []);
      return;
    }

    const previousDayLevels = Array.isArray(payload?.previous_day_levels) ? payload.previous_day_levels : [];
    const previousWeekLevels = Array.isArray(payload?.previous_week_levels) ? payload.previous_week_levels : [];
    const previousMonthLevels = Array.isArray(payload?.previous_month_levels) ? payload.previous_month_levels : [];
    const activeTrades = Array.isArray(payload?.active_trades) ? payload.active_trades : [];
    const visibleEvents = cappedVisibleEvents(payload, candles);
    renderMeta(payload, visibleEvents);
    renderQuickRead(payload);
    renderEventsList(payload, visibleEvents);

    const padding = { top: 18, right: 108, bottom: 34, left: 24 };
    const highs = candles.map((candle) => Number(candle.high));
    const lows = candles.map((candle) => Number(candle.low));
    const activeLevels = [
      ...findActiveLevelsAt(previousDayLevels, candles[candles.length - 1]?.time),
      ...findActiveLevelsAt(previousWeekLevels, candles[candles.length - 1]?.time),
      ...findActiveLevelsAt(previousMonthLevels, candles[candles.length - 1]?.time),
    ];
    const levelHighs = activeLevels.map((level) => Number(level.previous_high)).filter(Number.isFinite);
    const levelLows = activeLevels.map((level) => Number(level.previous_low)).filter(Number.isFinite);
    const sweepPrices = visibleEvents.map((event) => Number(event.price)).filter(Number.isFinite);
    const tradePrices = activeTrades.flatMap((trade) => [
      Number(trade.entry_price),
      Number(trade.stop_loss),
      Number(trade.take_profit),
    ]).filter(Number.isFinite);
    const maxPrice = Math.max(...highs, ...(levelHighs.length ? levelHighs : highs), ...(sweepPrices.length ? sweepPrices : highs), ...(tradePrices.length ? tradePrices : highs));
    const minPrice = Math.min(...lows, ...(levelLows.length ? levelLows : lows), ...(sweepPrices.length ? sweepPrices : lows), ...(tradePrices.length ? tradePrices : lows));
    const baseSpread = Math.max(maxPrice - minPrice, Number(payload?.point || 0.01) * 12, 0.5);
    const center = (maxPrice + minPrice) / 2;
    const adjustedSpread = baseSpread / clamp(state.verticalScale, 0.35, 5);
    const adjustedCenter = center - state.verticalPan;
    const paddedMax = adjustedCenter + adjustedSpread / 2;
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

    drawRollingLevels(previousMonthLevels, state.geometry, { high: "rgba(98, 71, 170, 0.92)", low: "rgba(140, 103, 218, 0.92)" });
    drawRollingLevels(previousWeekLevels, state.geometry, { high: "rgba(55, 110, 190, 0.92)", low: "rgba(41, 154, 195, 0.92)" });
    drawRollingLevels(previousDayLevels, state.geometry, { high: "rgba(222, 74, 91, 0.92)", low: "rgba(38, 143, 91, 0.92)" });

    candles.forEach((candle, index) => {
      const x = padding.left + index * step + step / 2;
      const open = Number(candle.open);
      const close = Number(candle.close);
      const high = Number(candle.high);
      const low = Number(candle.low);
      const bullish = close >= open;
      const color = bullish ? "#4caf50" : "#111111";
      const yHigh = priceToY(high);
      const yLow = priceToY(low);
      const yOpen = priceToY(open);
      const yClose = priceToY(close);
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.05;
      ctx.beginPath();
      ctx.moveTo(x, yHigh);
      ctx.lineTo(x, yLow);
      ctx.stroke();
      ctx.fillStyle = color;
      ctx.fillRect(x - candleWidth / 2, Math.min(yOpen, yClose), candleWidth, Math.max(2, Math.abs(yClose - yOpen)));
    });

    drawSweepEvents(visibleEvents, state.geometry);

    const currentPrice = Number(payload?.current_price || candles.at(-1)?.close || 0);
    const liveY = priceToY(currentPrice);
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

    ctx.fillStyle = "#1f2327";
    ctx.font = "12px Cascadia Mono";
    [maxPrice, (maxPrice + minPrice) / 2, minPrice].forEach((price) => {
      const y = priceToY(price);
      ctx.fillText(fixed(price), width - padding.right + 16, y + 4);
    });
  }

  function render() {
    drawChart(currentPayload() || {
      symbol: state.symbol,
      requested_symbol: state.symbol,
      candles: [],
      current_price: 0,
      connection_error: "Waiting for liquidity sweep data...",
    });
  }

  async function refreshData(forceSnapshot = false) {
    try {
      const payload = await fetchJson(`/api/chart-data?symbol=${encodeURIComponent(state.symbol)}&timeframe=${encodeURIComponent(state.timeframe)}`);
      state.payload = payload;
      if (state.mode === "frozen") {
        if (!state.frozenPayload || forceSnapshot) {
          state.frozenPayload = JSON.parse(JSON.stringify(payload));
        }
      } else {
        const latest = Array.isArray(payload?.liquidity_sweeps) && payload.liquidity_sweeps.length ? payload.liquidity_sweeps[payload.liquidity_sweeps.length - 1] : null;
        const latestKey = latest ? `${latest.time}|${latest.label}|${latest.side}` : "";
        if (latestKey && latestKey !== state.lastSweepKey) {
          if (state.lastSweepKey) {
            triggerSweepAlert(latest);
          }
          state.lastSweepKey = latestKey;
        }
      }
      render();
    } catch (error) {
      const fallback = {
        symbol: state.symbol,
        requested_symbol: state.symbol,
        timeframe: state.timeframe,
        candles: [],
        current_price: 0,
        previous_day_levels: [],
        previous_week_levels: [],
        previous_month_levels: [],
        liquidity_sweeps: [],
        connection_error: error.message || "Could not load liquidity sweep data.",
      };
      if (state.mode === "frozen" && state.frozenPayload) {
        render();
        return;
      }
      state.payload = fallback;
      render();
    }
  }

  function updateTimeframeButtons() {
    els.timeframeButtons.forEach((button) => {
      button.classList.toggle("active", button.dataset.sweepTimeframe === state.timeframe);
    });
  }

  function updateModeButtons() {
    els.modeButtons.forEach((button) => {
      button.classList.toggle("active", button.dataset.sweepMode === state.mode);
    });
  }

  function setMode(mode) {
    state.mode = mode === "frozen" ? "frozen" : "live";
    if (state.mode === "frozen" && state.payload && !state.frozenPayload) {
      state.frozenPayload = JSON.parse(JSON.stringify(state.payload));
    }
    updateModeButtons();
    persistView();
    render();
  }

  function bind() {
    els.symbolInput?.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        state.symbol = normalizeSymbolInput(els.symbolInput.value);
        state.panOffset = 0;
        persistView();
        refreshData(true).catch(() => {});
      }
    });

    els.refreshButton?.addEventListener("click", () => {
      state.symbol = normalizeSymbolInput(els.symbolInput?.value || state.symbol);
      persistView();
      refreshData(true).catch(() => {});
    });

    els.timeframeButtons.forEach((button) => {
      button.addEventListener("click", () => {
        state.timeframe = button.dataset.sweepTimeframe || "H1";
        state.panOffset = 0;
        updateTimeframeButtons();
        persistView();
        refreshData(state.mode === "frozen").catch(() => {});
      });
    });

    els.modeButtons.forEach((button) => {
      button.addEventListener("click", () => {
        setMode(button.dataset.sweepMode || "live");
      });
    });

    els.canvas?.addEventListener("pointerdown", (event) => {
      if (!state.geometry) return;
      const rect = els.canvas.getBoundingClientRect();
      const x = event.clientX - rect.left;
      const y = event.clientY - rect.top;
      const inPriceScale = x >= state.geometry.chartRight;
      state.dragMode = inPriceScale ? "price-scale" : "pan";
      state.dragStartX = x;
      state.dragStartY = y;
      state.dragStartPan = state.panOffset;
      state.dragStartVerticalPan = state.verticalPan;
      state.dragStartVerticalScale = state.verticalScale;
      els.canvas.setPointerCapture?.(event.pointerId);
    });

    els.canvas?.addEventListener("pointermove", (event) => {
      if (!state.dragMode || !state.geometry) return;
      const rect = els.canvas.getBoundingClientRect();
      const x = event.clientX - rect.left;
      const y = event.clientY - rect.top;
      const deltaX = state.dragStartX - x;
      const deltaY = y - state.dragStartY;
      if (state.dragMode === "pan") {
        const all = currentPayload()?.candles || [];
        const visible = getVisibleCandles(all).length;
        const moved = Math.round(deltaX / state.geometry.step);
        state.panOffset = clamp(state.dragStartPan + moved, 0, Math.max(0, all.length - visible));
        state.verticalPan = state.dragStartVerticalPan + (deltaY / state.geometry.plotHeight) * state.geometry.adjustedSpread;
      } else if (state.dragMode === "price-scale") {
        const scaleDelta = clamp(1 - (deltaY / 260), 0.25, 4);
        state.verticalScale = clamp(state.dragStartVerticalScale * scaleDelta, 0.35, 5);
      }
      persistView();
      render();
    });

    const releaseDrag = () => {
      state.dragMode = null;
    };
    els.canvas?.addEventListener("pointerup", releaseDrag);
    els.canvas?.addEventListener("pointerleave", releaseDrag);
    els.canvas?.addEventListener("wheel", (event) => {
      if (!state.geometry) return;
      event.preventDefault();
      const all = currentPayload()?.candles || [];
      if (!all.length) return;
      const rect = els.canvas.getBoundingClientRect();
      const mouseX = event.clientX - rect.left;
      const before = getVisibleCandles(all).length;
      const delta = event.deltaY > 0 ? -1 : 1;
      state.zoom = clamp(state.zoom + delta, -12, 26);
      const after = getVisibleCandles(all).length;
      const ratio = clamp((mouseX - state.geometry.padding.left) / state.geometry.plotWidth, 0, 1);
      const diff = before - after;
      state.panOffset = clamp(state.panOffset + Math.round(diff * (1 - ratio)), 0, Math.max(0, all.length - after));
      persistView();
      render();
    }, { passive: false });

    els.stopAlarmButton?.addEventListener("click", () => {
      stopSweepAlarmLoop();
      closeSweepAlarmModal();
    });

    els.alarmModal?.addEventListener("click", (event) => {
      if (event.target === els.alarmModal || event.target.classList.contains("alarm-backdrop")) {
        stopSweepAlarmLoop();
        closeSweepAlarmModal();
      }
    });

    window.addEventListener("resize", () => {
      render();
    });
  }

  function start() {
    if (els.symbolInput) els.symbolInput.value = state.symbol;
    updateTimeframeButtons();
    updateModeButtons();
    bind();
    refreshData(state.mode === "frozen").catch(() => {});
    window.setInterval(() => {
      if (state.mode === "live") {
        refreshData(false).catch(() => {});
      }
    }, 15000);
  }

  start();
})();
