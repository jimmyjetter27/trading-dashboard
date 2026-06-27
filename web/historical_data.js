(function () {
  if (!document.body || document.body.dataset.currentPage !== "historical-data") {
    return;
  }

  const API_BASE = window.location.protocol === "file:" ? "http://127.0.0.1:8765" : "";
  const STORAGE = {
    theme: "trade-observer-theme",
    sidenav: "trade-observer-sidenav",
    terminalPath: "trade-observer-history-terminal-path",
    symbols: "trade-observer-history-symbols",
    timeframes: "trade-observer-history-timeframes",
    includeTicks: "trade-observer-history-include-ticks",
    indicators: "trade-observer-history-indicators",
    ranges: "trade-observer-history-ranges",
    sweeps: "trade-observer-history-sweeps",
    lastJobId: "trade-observer-history-last-job-id",
  };

  const state = {
    theme: localStorage.getItem(STORAGE.theme) || "dark",
    sideNavCollapsed: localStorage.getItem(STORAGE.sidenav) === "collapsed",
    terminalPath: localStorage.getItem(STORAGE.terminalPath) || "C:/MT5/XMLive/terminal64.exe",
    symbols: new Set(JSON.parse(localStorage.getItem(STORAGE.symbols) || "[]")),
    timeframes: new Set(JSON.parse(localStorage.getItem(STORAGE.timeframes) || "[]")),
    includeTicks: localStorage.getItem(STORAGE.includeTicks) === "on",
    calculateIndicators: localStorage.getItem(STORAGE.indicators) !== "off",
    detectRanges: localStorage.getItem(STORAGE.ranges) !== "off",
    detectSweeps: localStorage.getItem(STORAGE.sweeps) !== "off",
    lastJobId: Number(localStorage.getItem(STORAGE.lastJobId) || 0),
    pollTimer: null,
  };

  const els = {
    body: document.body,
    sideNav: document.querySelector("#sideNav"),
    sideNavToggle: document.querySelector("#sideNavToggle"),
    themeToggle: document.querySelector("#themeToggle"),
    statusPill: document.querySelector("#historyStatusPill"),
    terminalPathInput: document.querySelector("#historyTerminalPathInput"),
    fromDateInput: document.querySelector("#historyFromDateInput"),
    toDateInput: document.querySelector("#historyToDateInput"),
    symbols: document.querySelector("#historySymbols"),
    timeframes: document.querySelector("#historyTimeframes"),
    includeTicksInput: document.querySelector("#historyIncludeTicksInput"),
    indicatorsInput: document.querySelector("#historyIndicatorsInput"),
    rangesInput: document.querySelector("#historyRangesInput"),
    sweepsInput: document.querySelector("#historySweepsInput"),
    warningBanner: document.querySelector("#historyWarningBanner"),
    startButton: document.querySelector("#historyStartButton"),
    refreshSummaryButton: document.querySelector("#historyRefreshSummaryButton"),
    clearDataButton: document.querySelector("#historyClearDataButton"),
    insertedCount: document.querySelector("#historyInsertedCount"),
    duplicateCount: document.querySelector("#historyDuplicateCount"),
    failedCount: document.querySelector("#historyFailedCount"),
    tickCount: document.querySelector("#historyTickCount"),
    jobStatus: document.querySelector("#historyJobStatus"),
    jobMeta: document.querySelector("#historyJobMeta"),
    jobItemsBody: document.querySelector("#historyJobItemsBody"),
    summaryCards: document.querySelector("#historySummaryCards"),
  };

  function setTheme() {
    document.body.dataset.theme = state.theme;
  }

  function applySideNavState() {
    els.body.classList.toggle("sidenav-collapsed", state.sideNavCollapsed);
    if (els.sideNavToggle) {
      els.sideNavToggle.textContent = state.sideNavCollapsed ? "Expand" : "Collapse";
    }
  }

  function formatNumber(value) {
    const numeric = Number(value || 0);
    return Number.isFinite(numeric) ? numeric.toLocaleString() : "0";
  }

  function formatDateTime(value) {
    if (!value) return "-";
    try {
      return new Date(value).toLocaleString();
    } catch {
      return String(value);
    }
  }

  function setStatus(text, tone = "ok") {
    if (!els.statusPill) return;
    els.statusPill.textContent = text;
    els.statusPill.className = `status-pill ${tone}`;
  }

  async function fetchJson(path, options = {}) {
    const response = await fetch(`${API_BASE}${path}`, {
      cache: "no-store",
      headers: {
        Accept: "application/json",
        ...(options.body ? { "Content-Type": "application/json" } : {}),
      },
      ...options,
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

  function defaultDateRange() {
    const now = new Date();
    const to = now.toISOString().slice(0, 10);
    const from = new Date(now.getTime() - 29 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
    return { from, to };
  }

  function syncControls() {
    const defaults = defaultDateRange();
    if (els.terminalPathInput) els.terminalPathInput.value = state.terminalPath;
    if (els.fromDateInput && !els.fromDateInput.value) els.fromDateInput.value = defaults.from;
    if (els.toDateInput && !els.toDateInput.value) els.toDateInput.value = defaults.to;
    if (els.includeTicksInput) els.includeTicksInput.checked = state.includeTicks;
    if (els.indicatorsInput) els.indicatorsInput.checked = state.calculateIndicators;
    if (els.rangesInput) els.rangesInput.checked = state.detectRanges;
    if (els.sweepsInput) els.sweepsInput.checked = state.detectSweeps;
  }

  function renderChips(target, rows, selectedSet, storageKey) {
    if (!target) return;
    target.innerHTML = rows.map((row) => {
      const value = String(row.value);
      const selected = selectedSet.has(value);
      const subtitle = row.subtitle ? `<small>${row.subtitle}</small>` : "";
      return `
        <label class="toggle-chip historical-chip ${selected ? "active" : ""}">
          <input type="checkbox" value="${value}" ${selected ? "checked" : ""}>
          <span class="toggle-label">${row.label}</span>
          ${subtitle}
        </label>
      `;
    }).join("");
    target.querySelectorAll('input[type="checkbox"]').forEach((input) => {
      input.addEventListener("change", () => {
        if (input.checked) selectedSet.add(input.value);
        else selectedSet.delete(input.value);
        localStorage.setItem(storageKey, JSON.stringify([...selectedSet]));
        renderChips(target, rows, selectedSet, storageKey);
      });
    });
  }

  function renderSummary(summary) {
    if (!summary || !els.summaryCards) return;
    const counts = summary.counts || {};
    const recentJobs = Array.isArray(summary.recent_jobs) ? summary.recent_jobs : [];
    els.summaryCards.innerHTML = `
      <article class="analysis-item neutral">
        <strong>Database Path</strong>
        <p>${summary.database_path || "-"}</p>
      </article>
      <article class="analysis-item neutral">
        <strong>Market Bars</strong>
        <p>${formatNumber(counts.market_bars)}</p>
      </article>
      <article class="analysis-item neutral">
        <strong>Indicator Features</strong>
        <p>${formatNumber(counts.indicator_features)}</p>
      </article>
      <article class="analysis-item neutral">
        <strong>Range States</strong>
        <p>${formatNumber(counts.range_states)}</p>
      </article>
      <article class="analysis-item neutral">
        <strong>Liquidity Sweeps</strong>
        <p>${formatNumber(counts.liquidity_sweeps)}</p>
      </article>
      <article class="analysis-item neutral">
        <strong>Recent Jobs</strong>
        <p>${recentJobs.length ? recentJobs.map((job) => `#${job.id} ${job.status}`).join(" | ") : "No jobs yet."}</p>
      </article>
    `;
  }

  function renderJobStatus(payload) {
    const job = payload?.job || null;
    const items = Array.isArray(payload?.items) ? payload.items : [];
    if (!job) {
      els.jobMeta.textContent = "No backfill job has started yet.";
      els.jobItemsBody.innerHTML = `<tr><td colspan="9"><div class="empty-state">Job progress will appear here after you start a backfill.</div></td></tr>`;
      return;
    }
    els.insertedCount.textContent = formatNumber(job.inserted_count);
    els.duplicateCount.textContent = formatNumber(job.duplicates_skipped);
    els.failedCount.textContent = formatNumber(job.failed_count);
    els.tickCount.textContent = formatNumber(job.tick_inserted_count);
    els.jobStatus.textContent = String(job.status || "-").replaceAll("_", " ");
    els.jobMeta.textContent = `Job #${job.id} | ${job.from_date} -> ${job.to_date} | ${job.progress_completed}/${job.progress_total} complete | ${job.last_error ? `Last error: ${job.last_error}` : "No blocking error."}`;
    els.jobItemsBody.innerHTML = items.length
      ? items.map((item) => `
        <tr>
          <td>${item.symbol}</td>
          <td>${item.timeframe}</td>
          <td>${item.status}</td>
          <td>${formatNumber(item.fetched_rows)}</td>
          <td>${formatNumber(item.inserted_rows)}</td>
          <td>${formatNumber(item.duplicates_skipped)}</td>
          <td>${formatNumber(item.failed_rows)}</td>
          <td>${formatNumber(item.tick_rows)}</td>
          <td>${item.last_error || "-"}</td>
        </tr>
      `).join("")
      : `<tr><td colspan="9"><div class="empty-state">No job items yet.</div></td></tr>`;
    const terminalPath = job.terminal_path || state.terminalPath;
    if (els.terminalPathInput && terminalPath) {
      els.terminalPathInput.value = terminalPath;
    }
    if (["completed", "completed_with_errors", "failed"].includes(String(job.status || ""))) {
      stopPolling();
      setStatus(
        job.status === "completed" ? "Backfill Completed" : job.status === "completed_with_errors" ? "Completed With Errors" : "Backfill Failed",
        job.status === "failed" ? "bad" : "ok",
      );
      refreshSummary().catch(() => {});
    } else {
      setStatus(`Running Job #${job.id}`, "ok");
    }
  }

  async function refreshSummary() {
    try {
      const payload = await fetchJson("/api/history/summary");
      renderSummary(payload);
      if (els.terminalPathInput && !els.terminalPathInput.value) {
        els.terminalPathInput.value = payload.default_terminal_path || state.terminalPath;
      }
    } catch (error) {
      setStatus("Summary Error", "bad");
      if (els.summaryCards) {
        els.summaryCards.innerHTML = `<div class="empty-state">${error.message || "Failed to load summary."}</div>`;
      }
    }
  }

  async function refreshSymbolsAndTimeframes() {
    const [symbolsPayload, timeframesPayload] = await Promise.all([
      fetchJson("/api/history/symbols"),
      fetchJson("/api/history/timeframes"),
    ]);
    const symbolRows = (symbolsPayload.symbols || []).map((row) => ({
      value: row.broker_symbol,
      label: row.broker_symbol,
      subtitle: `${row.asset_class}${row.enabled ? "" : " · disabled"}`,
    }));
    if (!state.symbols.size) {
      symbolRows.filter((row) => !String(row.subtitle || "").includes("disabled")).slice(0, 3).forEach((row) => state.symbols.add(row.value));
      localStorage.setItem(STORAGE.symbols, JSON.stringify([...state.symbols]));
    }
    renderChips(els.symbols, symbolRows, state.symbols, STORAGE.symbols);

    const timeframeRows = (timeframesPayload.timeframes || []).map((value) => ({ value, label: value }));
    if (!state.timeframes.size) {
      ["M1", "M5", "M15", "H1"].forEach((value) => state.timeframes.add(value));
      localStorage.setItem(STORAGE.timeframes, JSON.stringify([...state.timeframes]));
    }
    renderChips(els.timeframes, timeframeRows, state.timeframes, STORAGE.timeframes);
  }

  function stopPolling() {
    if (state.pollTimer) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
    }
  }

  function startPolling(jobId) {
    stopPolling();
    const poll = async () => {
      try {
        const payload = await fetchJson(`/api/history/backfill/${jobId}/status`);
        renderJobStatus(payload);
      } catch (error) {
        setStatus("Status Error", "bad");
        stopPolling();
      }
    };
    poll().catch(() => {});
    state.pollTimer = window.setInterval(() => {
      poll().catch(() => {});
    }, 2000);
  }

  async function startBackfill() {
    const terminalPath = String(els.terminalPathInput?.value || state.terminalPath).trim();
    const fromDate = String(els.fromDateInput?.value || "").trim();
    const toDate = String(els.toDateInput?.value || "").trim();
    if (!terminalPath) {
      setStatus("Terminal Path Required", "bad");
      return;
    }
    if (!fromDate || !toDate) {
      setStatus("Date Range Required", "bad");
      return;
    }
    if (!state.symbols.size || !state.timeframes.size) {
      setStatus("Pick Symbols & Timeframes", "bad");
      return;
    }
    state.terminalPath = terminalPath;
    state.includeTicks = Boolean(els.includeTicksInput?.checked);
    state.calculateIndicators = Boolean(els.indicatorsInput?.checked);
    state.detectRanges = Boolean(els.rangesInput?.checked);
    state.detectSweeps = Boolean(els.sweepsInput?.checked);
    localStorage.setItem(STORAGE.terminalPath, state.terminalPath);
    localStorage.setItem(STORAGE.includeTicks, state.includeTicks ? "on" : "off");
    localStorage.setItem(STORAGE.indicators, state.calculateIndicators ? "on" : "off");
    localStorage.setItem(STORAGE.ranges, state.detectRanges ? "on" : "off");
    localStorage.setItem(STORAGE.sweeps, state.detectSweeps ? "on" : "off");
    setStatus("Queueing Backfill", "ok");
    try {
      const payload = await fetchJson("/api/history/backfill", {
        method: "POST",
        body: JSON.stringify({
          terminal_path: state.terminalPath,
          symbols: [...state.symbols],
          timeframes: [...state.timeframes],
          from_date: fromDate,
          to_date: toDate,
          include_ticks: state.includeTicks,
          calculate_indicators: state.calculateIndicators,
          detect_ranges: state.detectRanges,
          detect_liquidity_sweeps: state.detectSweeps,
        }),
      });
      state.lastJobId = Number(payload.job_id || 0);
      localStorage.setItem(STORAGE.lastJobId, String(state.lastJobId || 0));
      setStatus(`Backfill Job #${state.lastJobId}`, "ok");
      startPolling(state.lastJobId);
    } catch (error) {
      setStatus("Backfill Failed", "bad");
      els.jobMeta.textContent = error.message || "Backfill could not start.";
    }
  }

  async function clearHistoricalData() {
    const confirmed = window.confirm("Delete all stored AurumBox historical backfill data? This will clear bars, ticks, features, range states, sweeps, setups, AI samples, and saved backfill jobs, but it will not touch the main trade observer database.");
    if (!confirmed) return;
    stopPolling();
    setStatus("Clearing Data", "ok");
    try {
      await fetchJson("/api/history/clear", {
        method: "POST",
        body: JSON.stringify({}),
      });
      state.lastJobId = 0;
      localStorage.setItem(STORAGE.lastJobId, "0");
      els.insertedCount.textContent = "0";
      els.duplicateCount.textContent = "0";
      els.failedCount.textContent = "0";
      els.tickCount.textContent = "0";
      els.jobStatus.textContent = "Idle";
      els.jobMeta.textContent = "Historical data was cleared. You can start a fresh backfill now.";
      els.jobItemsBody.innerHTML = `<tr><td colspan="9"><div class="empty-state">No backfill job has started yet.</div></td></tr>`;
      await refreshSummary();
      setStatus("Data Cleared", "ok");
    } catch (error) {
      setStatus("Clear Failed", "bad");
      els.jobMeta.textContent = error.message || "Could not clear historical data.";
    }
  }

  function bindEvents() {
    els.themeToggle?.addEventListener("click", () => {
      state.theme = state.theme === "dark" ? "light" : "dark";
      localStorage.setItem(STORAGE.theme, state.theme);
      setTheme();
    });
    els.sideNavToggle?.addEventListener("click", () => {
      state.sideNavCollapsed = !state.sideNavCollapsed;
      localStorage.setItem(STORAGE.sidenav, state.sideNavCollapsed ? "collapsed" : "expanded");
      applySideNavState();
    });
    els.startButton?.addEventListener("click", () => {
      startBackfill().catch(() => {});
    });
    els.refreshSummaryButton?.addEventListener("click", () => {
      refreshSummary().catch(() => {});
      if (state.lastJobId > 0) startPolling(state.lastJobId);
    });
    els.clearDataButton?.addEventListener("click", () => {
      clearHistoricalData().catch(() => {});
    });
    els.includeTicksInput?.addEventListener("change", () => {
      const enabled = Boolean(els.includeTicksInput.checked);
      els.warningBanner.textContent = enabled
        ? "Tick backfills can be very heavy. The job will use MT5 copy_ticks_range and may take much longer."
        : "Bars are fetched in UTC. Tick backfills can be heavy, so they are off by default.";
    });
  }

  async function boot() {
    setTheme();
    applySideNavState();
    syncControls();
    bindEvents();
    try {
      await refreshSymbolsAndTimeframes();
      await refreshSummary();
      if (state.lastJobId > 0) {
        startPolling(state.lastJobId);
      } else {
        setStatus("Ready", "ok");
      }
    } catch (error) {
      setStatus("Backend Unavailable", "bad");
      if (els.jobMeta) {
        els.jobMeta.textContent = error.message || "Failed to load the historical data module.";
      }
    }
  }

  boot().catch(() => {});
})();
