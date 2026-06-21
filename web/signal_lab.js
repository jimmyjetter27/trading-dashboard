(function () {
  const labState = {
    batches: [],
    currentBatchId: 0,
    currentPayload: null,
    selectedSignalId: 0,
    selectedInvalidId: 0,
  };

  const els = {
    batchSelect: document.querySelector("#signalLabBatchSelect"),
    rawTextInput: document.querySelector("#signalLabRawTextInput"),
    importTextButton: document.querySelector("#signalLabImportTextButton"),
    importMt5LogsButton: document.querySelector("#signalLabImportMt5LogsButton"),
    refreshButton: document.querySelector("#signalLabRefreshButton"),
    clearBatchesButton: document.querySelector("#signalLabClearBatchesButton"),
    importMessage: document.querySelector("#signalLabImportMessage"),
    timeframe: document.querySelector("#signalLabTimeframe"),
    replayHours: document.querySelector("#signalLabReplayHours"),
    rangePreset: document.querySelector("#signalLabRangePreset"),
    fromDate: document.querySelector("#signalLabFromDate"),
    toDate: document.querySelector("#signalLabToDate"),
    entryMode: document.querySelector("#signalLabEntryMode"),
    entryTolerance: document.querySelector("#signalLabEntryTolerance"),
    exitModel: document.querySelector("#signalLabExitModel"),
    customTpIndex: document.querySelector("#signalLabCustomTpIndex"),
    startingBalance: document.querySelector("#signalLabStartingBalance"),
    lotMode: document.querySelector("#signalLabLotMode"),
    fixedLot: document.querySelector("#signalLabFixedLot"),
    riskPercent: document.querySelector("#signalLabRiskPercent"),
    dollarValue: document.querySelector("#signalLabDollarValue"),
    commission: document.querySelector("#signalLabCommission"),
    spread: document.querySelector("#signalLabSpread"),
    runBacktestButton: document.querySelector("#signalLabRunBacktestButton"),
    resetResultsButton: document.querySelector("#signalLabResetResultsButton"),
    invalidBody: document.querySelector("#signalLabInvalidBody"),
    resultsBody: document.querySelector("#signalLabResultsBody"),
    summaryCards: document.querySelector("#signalLabSummaryCards"),
    detectiveSummary: document.querySelector("#signalLabDetectiveSummary"),
    previewCanvas: document.querySelector("#signalLabPreviewCanvas"),
    previewTimeframe: document.querySelector("#signalLabPreviewTimeframe"),
    previewMeta: document.querySelector("#signalLabPreviewMeta"),
    detectiveCard: document.querySelector("#signalLabDetectiveCard"),
    equityCurve: document.querySelector("#signalLabEquityCurve"),
    exitComparison: document.querySelector("#signalLabExitComparison"),
    logViewer: document.querySelector("#signalLabLogViewer"),
    editId: document.querySelector("#signalLabEditId"),
    editDate: document.querySelector("#signalLabEditDate"),
    editTime: document.querySelector("#signalLabEditTime"),
    editSymbol: document.querySelector("#signalLabEditSymbol"),
    editDirection: document.querySelector("#signalLabEditDirection"),
    editEntry: document.querySelector("#signalLabEditEntry"),
    editLimit: document.querySelector("#signalLabEditLimit"),
    editStop: document.querySelector("#signalLabEditStop"),
    editTp1: document.querySelector("#signalLabEditTp1"),
    editTp2: document.querySelector("#signalLabEditTp2"),
    editTp3: document.querySelector("#signalLabEditTp3"),
    editTp4: document.querySelector("#signalLabEditTp4"),
    saveEditButton: document.querySelector("#signalLabSaveEditButton"),
    editMessage: document.querySelector("#signalLabEditMessage"),
    lotWarning: document.querySelector("#signalLabLotWarning"),
  };

  if (!document.body || document.body.dataset.currentPage !== "signal-lab") {
    return;
  }

  const moneyFormatter = new Intl.NumberFormat(undefined, { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const numberFormatter = new Intl.NumberFormat(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 3 });

  function money(value) {
    const amount = Number(value || 0);
    return moneyFormatter.format(amount);
  }

  async function fetchJsonLab(url, options) {
    const response = await fetch(url, {
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      ...options,
    });
    const text = await response.text();
    const payload = text ? JSON.parse(text) : {};
    if (!response.ok) {
      throw new Error(payload.message || `Request failed (${response.status})`);
    }
    return payload;
  }

  function setImportMessage(text, tone = "neutral") {
    if (!els.importMessage) return;
    els.importMessage.textContent = text;
    els.importMessage.className = tone === "warn" ? "negative muted-inline" : tone === "success" ? "positive muted-inline" : "muted-inline";
  }

  function renderBatchOptions() {
    if (!els.batchSelect) return;
    const options = ['<option value="">Select imported batch</option>'];
    for (const batch of labState.batches) {
      options.push(`<option value="${batch.id}" ${String(batch.id) === String(labState.currentBatchId) ? "selected" : ""}>#${batch.id} · ${escapeHtml(batch.file_name)} · ${batch.valid_rows}/${batch.total_rows} valid</option>`);
    }
    els.batchSelect.innerHTML = options.join("");
  }

  function renderSummaryCards(cards) {
    if (!els.summaryCards) return;
    const entries = [
      ["Total Signals", cards.total_signals],
      ["Valid Signals", cards.valid_signals],
      ["Invalid Signals", cards.invalid_signals],
      ["Tested Signals", cards.tested_signals],
      ["Entry Fill Rate", `${cards.entry_fill_rate}%`],
      ["Limit Fill Rate", `${cards.limit_fill_rate}%`],
      ["TP1 Hit %", `${cards.tp1_hit_rate}%`],
      ["TP2 Hit %", `${cards.tp2_hit_rate}%`],
      ["TP3 Hit %", `${cards.tp3_hit_rate}%`],
      ["TP4 Hit %", `${cards.tp4_hit_rate}%`],
      ["SL Hit %", `${cards.sl_hit_rate}%`],
      ["Average Time To TP1", cards.avg_time_to_tp1],
      ["Average Time To TP2", cards.avg_time_to_tp2],
      ["Starting Balance", money(cards.starting_balance)],
      ["Final Balance", money(cards.final_balance)],
      ["Net P/L", money(cards.net_profit_loss)],
      ["Growth / Loss", `${cards.growth_percent}%`],
      ["Max Drawdown", money(cards.max_drawdown)],
      ["Best Session", cards.best_session],
      ["Best Direction", cards.best_direction],
      ["Best Exit Model", cards.best_exit_model],
    ];
    els.summaryCards.innerHTML = entries.map(([label, value]) => `
      <article class="panel stat-panel signal-lab-stat-card">
        <span>${escapeHtml(label)}</span>
        <strong>${escapeHtml(String(value ?? "-"))}</strong>
      </article>
    `).join("");
  }

  function renderDetectiveSummary(summary) {
    if (!els.detectiveSummary) return;
    if (!summary || (!summary.winner_features?.length && !summary.loser_features?.length && !summary.evidence?.length)) {
      els.detectiveSummary.innerHTML = `<div class="empty-state">Run replay to compare repeated features across winning and losing signals.</div>`;
      return;
    }
    const winnerLines = (summary.winner_features || []).map((item) => `${item.label}: ${item.rate}%`).join(" | ") || "No winner clusters yet.";
    const loserLines = (summary.loser_features || []).map((item) => `${item.label}: ${item.rate}%`).join(" | ") || "No loser clusters yet.";
    const edgeLines = (summary.edge_scores || []).slice(0, 4).map((item) => `${item.label} (${item.edge_score > 0 ? "+" : ""}${item.edge_score})`).join(" | ") || "No feature edges yet.";
    const evidence = (summary.evidence || []).join(" | ") || "No detective evidence yet.";
    els.detectiveSummary.innerHTML = `
      <article class="analysis-item neutral">
        <strong>Likely Strategy</strong>
        <p>${escapeHtml(summary.likely_strategy_label || "-")}</p>
      </article>
      <article class="analysis-item neutral">
        <strong>Confidence</strong>
        <p>${escapeHtml(String(summary.confidence_score ?? 0))}%</p>
      </article>
      <article class="analysis-item neutral">
        <strong>Best Context</strong>
        <p>Session: ${escapeHtml(summary.best_session || "-")} | Direction: ${escapeHtml(summary.best_direction || "-")} | Exit: ${escapeHtml(summary.best_tp_model || "-")}</p>
      </article>
      <article class="analysis-item neutral">
        <strong>Winning Features</strong>
        <p>${escapeHtml(winnerLines)}</p>
      </article>
      <article class="analysis-item neutral">
        <strong>Losing Features</strong>
        <p>${escapeHtml(loserLines)}</p>
      </article>
      <article class="analysis-item neutral">
        <strong>Feature Edge Score</strong>
        <p>${escapeHtml(edgeLines)}</p>
      </article>
      <article class="analysis-item neutral">
        <strong>Evidence</strong>
        <p>${escapeHtml(evidence)}</p>
      </article>
    `;
  }

  function scrollToReplayResults() {
    const target = els.summaryCards || els.resultsBody;
    if (!target) return;
    try {
      target.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (_error) {
      target.scrollIntoView();
    }
  }

  function renderInvalidSignals(rows) {
    if (!els.invalidBody) return;
    if (!rows.length) {
      els.invalidBody.innerHTML = `<tr><td colspan="7"><div class="empty-state">No invalid rows in this batch.</div></td></tr>`;
      return;
    }
    els.invalidBody.innerHTML = rows.map((row) => `
      <tr>
        <td>${escapeHtml(row.signal_id || row.id)}</td>
        <td>${escapeHtml(row.date || "-")}</td>
        <td>${escapeHtml(row.time_gmt || "-")}</td>
        <td>${escapeHtml(row.symbol || "-")}</td>
        <td>${escapeHtml(row.direction || "-")}</td>
        <td>${escapeHtml((row.validation_errors || []).join("; "))}</td>
        <td><button class="theme-button" type="button" data-edit-invalid="${row.id}">Edit</button></td>
      </tr>
    `).join("");
    els.invalidBody.querySelectorAll("[data-edit-invalid]").forEach((button) => {
      button.addEventListener("click", () => {
        const id = Number(button.getAttribute("data-edit-invalid") || 0);
        const row = rows.find((item) => Number(item.id) === id);
        if (!row) return;
        populateEditForm(row);
      });
    });
  }

  function populateEditForm(row) {
    labState.selectedInvalidId = Number(row.id || 0);
    els.editId.value = String(row.id || "");
    els.editDate.value = row.date || "";
    els.editTime.value = row.time_gmt || "";
    els.editSymbol.value = row.symbol || "";
    els.editDirection.value = row.direction || "BUY";
    els.editEntry.value = row.entry ?? "";
    els.editLimit.value = row.limit_price ?? "";
    els.editStop.value = row.stop_loss ?? "";
    els.editTp1.value = row.tps?.[0] ?? "";
    els.editTp2.value = row.tps?.[1] ?? "";
    els.editTp3.value = row.tps?.[2] ?? "";
    els.editTp4.value = row.tps?.[3] ?? "";
    els.editMessage.textContent = `Editing signal ${row.signal_id || row.id}`;
  }

  function mergeFeatureForResults(results, features) {
    const featureMap = new Map((features || []).map((item) => [Number(item.signal_call_id), item]));
    return results.map((row) => ({ ...row, feature: featureMap.get(Number(row.signal_call_id)) || null }));
  }

  function renderResults(rows) {
    if (!els.resultsBody) return;
    if (!rows.length) {
      els.resultsBody.innerHTML = `<tr><td colspan="19"><div class="empty-state">Run a replay to populate results.</div></td></tr>`;
      return;
    }
    els.resultsBody.innerHTML = rows.map((row) => `
      <tr data-result-row="${row.signal_call_id}">
        <td>${escapeHtml(row.date || "-")}</td>
        <td>${escapeHtml(row.time_gmt || "-")}</td>
        <td>${escapeHtml(row.symbol || "-")}${row.broker_symbol && row.broker_symbol !== row.symbol ? `<div class="muted-inline">MT5: ${escapeHtml(row.broker_symbol)}</div>` : ""}</td>
        <td>${escapeHtml(row.direction || "-")}</td>
        <td>${formatNumber(row.entry)}</td>
        <td>${formatNumber(row.limit_price)}</td>
        <td>${formatNumber(row.stop_loss)}</td>
        <td>${formatTp(row.tps, 0)}</td>
        <td>${formatTp(row.tps, 1)}</td>
        <td>${formatTp(row.tps, 2)}</td>
        <td>${formatTp(row.tps, 3)}</td>
        <td>${row.entry_filled ? "Yes" : "No"}</td>
        <td>${escapeHtml(row.outcome || "-")}</td>
        <td>${escapeHtml(row.first_outcome || "-")}</td>
        <td>${money(row.balance_before)}</td>
        <td class="${Number(row.profit_loss || 0) >= 0 ? "positive" : "negative"}">${money(row.profit_loss)}</td>
        <td>${money(row.balance_after)}</td>
        <td>${escapeHtml(row.feature?.detected_setup || "-")}</td>
        <td>${row.feature?.confidence_score ?? "-"}</td>
      </tr>
    `).join("");
    els.resultsBody.querySelectorAll("[data-result-row]").forEach((rowEl) => {
      rowEl.addEventListener("click", () => {
        const signalCallId = Number(rowEl.getAttribute("data-result-row") || 0);
        labState.selectedSignalId = signalCallId;
        loadPreview(signalCallId).catch((error) => {
          els.previewMeta.textContent = error.message || "Could not load chart preview.";
        });
      });
    });
  }

  function renderBars(container, items, formatter) {
    if (!container) return;
    if (!items || !items.length) {
      container.innerHTML = `<div class="empty-state">No data yet.</div>`;
      return;
    }
    const max = Math.max(...items.map((item) => Number(item.y ?? item.final_balance ?? item.value ?? 0)), 1);
    container.innerHTML = items.map((item, idx) => {
      const raw = Number(item.y ?? item.final_balance ?? item.value ?? 0);
      const pct = Math.max(6, Math.abs(raw / max) * 100);
      const label = item.label || `#${item.x || idx + 1}`;
      return `
        <div class="signal-lab-bar-row">
          <span>${escapeHtml(String(label))}</span>
          <div class="signal-lab-bar-track"><div class="signal-lab-bar-fill" style="width:${pct}%"></div></div>
          <strong>${escapeHtml(formatter(raw, item))}</strong>
        </div>
      `;
    }).join("");
  }

  function renderLogs(logs) {
    if (!els.logViewer) return;
    if (!logs.length) {
      els.logViewer.innerHTML = `<div class="empty-state">Signal Lab logs will appear here.</div>`;
      return;
    }
    els.logViewer.innerHTML = logs.slice(-60).reverse().map((log) => `
      <article class="signal-lab-log-entry">
        <strong>${escapeHtml(log.ts || "")}</strong>
        <p>${escapeHtml(log.message || "")}</p>
        <small>${escapeHtml(JSON.stringify(log.payload || {}))}</small>
      </article>
    `).join("");
  }

  async function loadBatches() {
    const payload = await fetchJsonLab("/api/signal-lab/batches");
    labState.batches = payload.batches || [];
    if (!labState.currentBatchId && labState.batches.length) {
      labState.currentBatchId = Number(labState.batches[0].id);
    }
    renderBatchOptions();
  }

  async function loadBatch(batchId) {
    if (!batchId) return;
    const payload = await fetchJsonLab(`/api/signal-lab/batch?batch_id=${batchId}`);
    labState.currentPayload = payload;
    labState.currentBatchId = Number(batchId);
    renderBatchOptions();
    renderSummaryCards(payload.analytics?.cards || {});
    renderDetectiveSummary(payload.analytics?.strategy_detective || null);
    renderInvalidSignals(payload.invalid_signals || []);
    renderResults(mergeFeatureForResults(payload.results || [], payload.features || []));
    renderBars(els.equityCurve, payload.analytics?.equity_curve || [], (value) => money(value));
    renderBars(els.exitComparison, payload.analytics?.exit_model_comparison || [], (value, item) => money(item.final_balance));
    renderLogs(payload.logs || []);
    setImportMessage(payload.batch ? `Loaded batch #${payload.batch.id} (${payload.batch.file_name})` : "Batch loaded.", "success");
  }

  async function importRawTextSignals() {
    const rawText = String(els.rawTextInput?.value || "").trim();
    if (!rawText) {
      setImportMessage("Paste some Telegram-style signal text first.", "warn");
      return;
    }
    if (els.importTextButton) els.importTextButton.disabled = true;
    setImportMessage("Importing pasted Telegram signals...", "neutral");
    try {
      const payload = await fetchJsonLab("/api/signal-lab/import-text", {
        method: "POST",
        body: JSON.stringify({
          raw_text: rawText,
          source_name: "pasted_signals.txt",
        }),
      });
      await loadBatches();
      await loadBatch(payload.batch_id);
      if (window.showToast) {
        window.showToast("Signal Import Complete", payload.message || "Pasted signals were imported into Signal Lab.", "success");
      }
    } catch (error) {
      setImportMessage(error.message || "Raw text import failed.", "warn");
    } finally {
      if (els.importTextButton) els.importTextButton.disabled = false;
    }
  }

  async function importMt5TesterLogs() {
    if (els.importMt5LogsButton) els.importMt5LogsButton.disabled = true;
    setImportMessage("Importing MT5 Strategy Tester logs from the JamesANabiah terminal...", "neutral");
    try {
      const payload = await fetchJsonLab("/api/signal-lab/import-mt5-logs", {
        method: "POST",
        body: JSON.stringify({
          terminal_root: "C:\\MT5\\JamesANabiah",
        }),
      });
      await loadBatches();
      await loadBatch(payload.batch_id);
      if (window.showToast) {
        window.showToast("Tester Logs Imported", payload.message || "MT5 tester results were imported into Signal Lab.", "success");
      }
    } catch (error) {
      setImportMessage(error.message || "MT5 tester log import failed.", "warn");
    } finally {
      if (els.importMt5LogsButton) els.importMt5LogsButton.disabled = false;
    }
  }

  async function saveEdit() {
    const signalId = Number(els.editId.value || 0);
    if (!signalId) {
      els.editMessage.textContent = "Choose an invalid signal first.";
      return;
    }
    const updates = {
      date: els.editDate.value,
      time_gmt: els.editTime.value,
      symbol: els.editSymbol.value.trim(),
      direction: els.editDirection.value,
      entry: els.editEntry.value,
      limit_price: els.editLimit.value,
      stop_loss: els.editStop.value,
      tp1: els.editTp1.value,
      tp2: els.editTp2.value,
      tp3: els.editTp3.value,
      tp4: els.editTp4.value,
    };
    els.saveEditButton.disabled = true;
    try {
      const payload = await fetchJsonLab("/api/signal-lab/update", {
        method: "POST",
        body: JSON.stringify({ signal_call_id: signalId, updates }),
      });
      labState.currentPayload = payload;
      renderSummaryCards(payload.analytics?.cards || {});
      renderDetectiveSummary(payload.analytics?.strategy_detective || null);
      renderInvalidSignals(payload.invalid_signals || []);
      renderResults(mergeFeatureForResults(payload.results || [], payload.features || []));
      els.editMessage.textContent = "Signal was revalidated and saved.";
      if (window.showToast) window.showToast("Signal Updated", "The invalid row was saved and revalidated.", "success");
    } catch (error) {
      els.editMessage.textContent = error.message || "Could not save the signal.";
    } finally {
      els.saveEditButton.disabled = false;
    }
  }

  async function runBacktest() {
    if (!labState.currentBatchId) {
      setImportMessage("Import or choose a batch first.", "warn");
      return;
    }
    const settings = {
      timeframe: els.timeframe.value,
      replay_window_hours: Number(els.replayHours.value || 24),
      range_preset: els.rangePreset?.value || "all",
      from_date: els.fromDate?.value || "",
      to_date: els.toDate?.value || "",
      entry_mode: els.entryMode.value,
      entry_tolerance: Number(els.entryTolerance.value || 0),
      exit_model: els.exitModel.value,
      custom_tp_index: Number(els.customTpIndex.value || 1),
      starting_balance: Number(els.startingBalance.value || 50),
      fixed_lot_size: Number(els.fixedLot.value || 0.01),
      lot_size_mode: els.lotMode.value,
      risk_percent: Number(els.riskPercent.value || 1),
      profit_per_1_dollar_move_per_0_01_lot: Number(els.dollarValue.value || 1),
      commission_per_trade: Number(els.commission.value || 0),
      spread_cost: Number(els.spread.value || 0),
    };
    els.runBacktestButton.disabled = true;
    setImportMessage("Running historical replay and balance simulation...", "neutral");
    try {
      const payload = await fetchJsonLab("/api/signal-lab/backtest", {
        method: "POST",
        body: JSON.stringify({ batch_id: labState.currentBatchId, settings }),
      });
      labState.currentPayload = payload;
      renderSummaryCards(payload.analytics?.cards || {});
      renderInvalidSignals(payload.invalid_signals || []);
      renderResults(mergeFeatureForResults(payload.results || [], payload.features || []));
      renderBars(els.equityCurve, payload.analytics?.equity_curve || [], (value) => money(value));
      renderBars(els.exitComparison, payload.analytics?.exit_model_comparison || [], (value, item) => money(item.final_balance));
      renderLogs(payload.logs || []);
      els.lotWarning.textContent = (payload.warnings || []).join(" ") || "Replay completed using the current simulation settings.";
      setImportMessage(payload.message || "Replay completed using the current simulation settings.", "success");
      if (window.showToast) window.showToast("Signal Replay Complete", payload.message || "Replay finished.", "success");
      scrollToReplayResults();
    } catch (error) {
      setImportMessage(error.message || "Replay failed.", "warn");
    } finally {
      els.runBacktestButton.disabled = false;
    }
  }

  async function resetResults() {
    if (!labState.currentBatchId) {
      setImportMessage("Choose a batch first.", "warn");
      return;
    }
    const payload = await fetchJsonLab("/api/signal-lab/reset-results", {
      method: "POST",
      body: JSON.stringify({ batch_id: labState.currentBatchId }),
    });
    labState.currentPayload = payload;
    renderSummaryCards(payload.analytics?.cards || {});
    renderDetectiveSummary(payload.analytics?.strategy_detective || null);
    renderInvalidSignals(payload.invalid_signals || []);
    renderResults([]);
    renderBars(els.equityCurve, [], (value) => money(value));
    renderBars(els.exitComparison, [], (value) => money(value));
    renderLogs(payload.logs || []);
    if (els.lotWarning) {
      els.lotWarning.textContent = "Current test results cleared.";
    }
    setImportMessage(payload.message || "Current test results cleared.", "success");
    if (window.showToast) window.showToast("Results Reset", payload.message || "Current Signal Lab results were cleared.", "success");
  }

  async function clearAllBatches() {
    const confirmed = window.confirm("Clear all imported Signal Lab batches and their replay results?");
    if (!confirmed) return;
    els.clearBatchesButton && (els.clearBatchesButton.disabled = true);
    try {
      const payload = await fetchJsonLab("/api/signal-lab/clear-batches", {
        method: "POST",
        body: JSON.stringify({}),
      });
      labState.batches = [];
      labState.currentBatchId = 0;
      labState.currentPayload = null;
      labState.selectedSignalId = 0;
      labState.selectedInvalidId = 0;
      renderBatchOptions();
      renderSummaryCards({});
      renderDetectiveSummary(null);
      renderInvalidSignals([]);
      renderResults([]);
      renderBars(els.equityCurve, [], (value) => money(value));
      renderBars(els.exitComparison, [], (value) => money(value));
      renderLogs([]);
      if (els.previewMeta) {
        els.previewMeta.textContent = "Select a result row to preview the chart context and levels.";
      }
      if (els.detectiveCard) {
        els.detectiveCard.innerHTML = `<div class="empty-state">Strategy Detective results will appear here after you select a signal result.</div>`;
      }
      if (els.editMessage) {
        els.editMessage.textContent = "Choose an invalid row to edit it here.";
      }
      if (els.lotWarning) {
        els.lotWarning.textContent = "For small accounts like $50, full-close TP simulation is usually more realistic when your total lot size is 0.01.";
      }
      setImportMessage(payload.message || "All imported Signal Lab batches were cleared.", "success");
      if (window.showToast) window.showToast("Signal Lab Cleared", payload.message || "All imported Signal Lab batches were cleared.", "success");
    } catch (error) {
      setImportMessage(error.message || "Could not clear Signal Lab batches.", "warn");
    } finally {
      els.clearBatchesButton && (els.clearBatchesButton.disabled = false);
    }
  }

  async function loadPreview(signalCallId) {
    const timeframe = els.previewTimeframe.value || "M5";
    const payload = await fetchJsonLab(`/api/signal-lab/chart?signal_call_id=${signalCallId}&timeframe=${encodeURIComponent(timeframe)}`);
    drawPreview(payload);
    renderDetective(payload.feature || {}, payload.result || null, payload.signal || null);
  }

  function renderDetective(feature, result, signal) {
    if (!els.detectiveCard) return;
    if (!feature || !Object.keys(feature).length) {
      els.detectiveCard.innerHTML = `<div class="empty-state">No detective features were stored for this signal yet.</div>`;
      return;
    }
    const evidence = Array.isArray(feature.evidence) ? feature.evidence : [];
    els.detectiveCard.innerHTML = `
      <article class="analysis-item neutral">
        <strong>Likely Setup</strong>
        <p>${escapeHtml(feature.detected_setup || "Unknown")}</p>
      </article>
      <article class="analysis-item neutral">
        <strong>Confidence</strong>
        <p>${escapeHtml(String(feature.confidence_score ?? "-"))}%</p>
      </article>
      <article class="analysis-item neutral">
        <strong>EMA Bias / RSI / ATR</strong>
        <p>${escapeHtml(feature.ema_bias || "-")} | RSI ${escapeHtml(String(feature.rsi ?? "-"))} | ATR ${escapeHtml(String(feature.atr ?? "-"))}</p>
      </article>
      <article class="analysis-item neutral">
        <strong>Session Sweep Clues</strong>
        <p>Asian H/L swept: ${feature.asian_high_swept || feature.asian_low_swept ? "Yes" : "No"} | London H/L swept: ${feature.london_high_swept || feature.london_low_swept ? "Yes" : "No"}</p>
      </article>
      <article class="analysis-item neutral">
        <strong>Evidence</strong>
        <p>${escapeHtml(evidence.join(" | ") || "No extra evidence stored.")}</p>
      </article>
      ${result ? `<article class="analysis-item neutral"><strong>Current Replay Outcome</strong><p>${escapeHtml(result.outcome || "-")} | ${money(result.profit_loss)}</p></article>` : ""}
      ${signal ? `<article class="analysis-item neutral"><strong>Signal Context</strong><p>${escapeHtml(signal.symbol || "-")} ${escapeHtml(signal.direction || "-")} | MT5 ${escapeHtml(signal.broker_symbol || signal.symbol || "-")} | Entry ${formatNumber(signal.entry)} | SL ${formatNumber(signal.stop_loss)}</p></article>` : ""}
    `;
  }

  function drawPreview(payload) {
    const canvas = els.previewCanvas;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const width = canvas.width;
    const height = canvas.height;
    ctx.clearRect(0, 0, width, height);
    const candles = payload.candles || [];
    if (!candles.length) {
      ctx.fillStyle = "#97abc2";
      ctx.font = "16px Aptos";
      ctx.fillText("No preview candles available.", 24, 40);
      return;
    }
    const prices = candles.flatMap((c) => [c.high, c.low]);
    const minPrice = Math.min(...prices);
    const maxPrice = Math.max(...prices);
    const priceRange = Math.max(maxPrice - minPrice, 1);
    const padX = 44;
    const padY = 24;
    const chartW = width - padX * 2;
    const chartH = height - padY * 2;
    const xFor = (idx) => padX + (idx / Math.max(candles.length - 1, 1)) * chartW;
    const yFor = (price) => padY + ((maxPrice - price) / priceRange) * chartH;

    ctx.strokeStyle = "rgba(126,168,214,0.18)";
    ctx.lineWidth = 1;
    for (let i = 0; i < 5; i += 1) {
      const y = padY + (i / 4) * chartH;
      ctx.beginPath();
      ctx.moveTo(padX, y);
      ctx.lineTo(width - padX, y);
      ctx.stroke();
    }

    candles.forEach((candle, idx) => {
      const x = xFor(idx);
      const openY = yFor(candle.open);
      const closeY = yFor(candle.close);
      const highY = yFor(candle.high);
      const lowY = yFor(candle.low);
      const up = candle.close >= candle.open;
      ctx.strokeStyle = up ? "#4bf0b3" : "#ff6b7a";
      ctx.fillStyle = up ? "rgba(75,240,179,0.35)" : "rgba(255,107,122,0.35)";
      ctx.beginPath();
      ctx.moveTo(x, highY);
      ctx.lineTo(x, lowY);
      ctx.stroke();
      const bodyTop = Math.min(openY, closeY);
      const bodyHeight = Math.max(Math.abs(closeY - openY), 2);
      ctx.fillRect(x - 2.5, bodyTop, 5, bodyHeight);
    });

    const levels = [];
    const signal = payload.signal || {};
    if (signal.entry) levels.push({ label: "Entry", price: signal.entry, color: "#69d3ff" });
    if (signal.limit_price) levels.push({ label: "Limit", price: signal.limit_price, color: "#b2f7ef" });
    if (signal.stop_loss) levels.push({ label: "SL", price: signal.stop_loss, color: "#ff6b7a" });
    (signal.tps || []).forEach((tp, idx) => {
      levels.push({ label: `TP${idx + 1}`, price: tp, color: "#4bf0b3" });
    });
    ["asian_high", "asian_low", "london_high", "london_low", "previous_day_high", "previous_day_low"].forEach((key) => {
      const price = payload.feature?.[key];
      if (price) levels.push({ label: key.replaceAll("_", " "), price, color: "rgba(255,187,85,0.85)" });
    });
    levels.forEach((level) => {
      const y = yFor(level.price);
      ctx.strokeStyle = level.color;
      ctx.setLineDash([5, 4]);
      ctx.beginPath();
      ctx.moveTo(padX, y);
      ctx.lineTo(width - padX, y);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = level.color;
      ctx.font = "12px Aptos";
      ctx.fillText(`${level.label} ${formatNumber(level.price)}`, padX + 8, y - 6);
    });

    const signalTime = payload.signal?.time_gmt ? payload.candles.findIndex((c) => (c.time || "").startsWith(`${payload.signal.date}T${payload.signal.time_gmt}`)) : -1;
    if (signalTime >= 0) {
      const x = xFor(signalTime);
      ctx.strokeStyle = "#ffbb55";
      ctx.beginPath();
      ctx.moveTo(x, padY);
      ctx.lineTo(x, height - padY);
      ctx.stroke();
    }
    const resolved = payload.mapping?.broker_symbol || payload.signal?.broker_symbol || payload.signal?.symbol || "-";
    els.previewMeta.textContent = `${payload.signal?.symbol || "-"} -> ${resolved} | ${payload.signal?.direction || "-"} | ${payload.timeframe || "M5"} preview | ${candles.length} candles`;
  }

  function formatNumber(value) {
    if (value === null || value === undefined || value === "") return "-";
    return numberFormatter.format(Number(value));
  }

  function formatTp(tps, index) {
    if (!Array.isArray(tps) || tps[index] === undefined) return "-";
    return formatNumber(tps[index]);
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function bindEvents() {
    els.importTextButton?.addEventListener("click", () => {
      importRawTextSignals().catch((error) => setImportMessage(error.message || "Raw text import failed.", "warn"));
    });
    els.importMt5LogsButton?.addEventListener("click", () => {
      importMt5TesterLogs().catch((error) => setImportMessage(error.message || "MT5 tester log import failed.", "warn"));
    });
    els.refreshButton?.addEventListener("click", () => {
      loadBatch(Number(els.batchSelect.value || 0)).catch((error) => setImportMessage(error.message || "Could not reload batch.", "warn"));
    });
    els.batchSelect?.addEventListener("change", () => {
      const batchId = Number(els.batchSelect.value || 0);
      labState.currentBatchId = batchId;
      loadBatch(batchId).catch((error) => setImportMessage(error.message || "Could not load batch.", "warn"));
    });
    els.saveEditButton?.addEventListener("click", () => {
      saveEdit().catch((error) => {
        els.editMessage.textContent = error.message || "Could not save the signal.";
      });
    });
    els.runBacktestButton?.addEventListener("click", () => {
      runBacktest().catch((error) => setImportMessage(error.message || "Replay failed.", "warn"));
    });
    els.resetResultsButton?.addEventListener("click", () => {
      resetResults().catch((error) => setImportMessage(error.message || "Could not reset current test results.", "warn"));
    });
    els.clearBatchesButton?.addEventListener("click", () => {
      clearAllBatches().catch((error) => setImportMessage(error.message || "Could not clear Signal Lab batches.", "warn"));
    });
    els.previewTimeframe?.addEventListener("change", () => {
      if (labState.selectedSignalId) {
        loadPreview(labState.selectedSignalId).catch(() => {});
      }
    });
    document.querySelectorAll("[data-export-type]").forEach((button) => {
      button.addEventListener("click", () => {
        if (!labState.currentBatchId) {
          setImportMessage("Choose a batch first.", "warn");
          return;
        }
        const type = button.getAttribute("data-export-type");
        window.location.href = `/api/signal-lab/export?batch_id=${labState.currentBatchId}&type=${encodeURIComponent(type || "validated_csv")}`;
      });
    });
  }

  async function boot() {
    await loadBatches();
    renderBatchOptions();
    if (labState.currentBatchId) {
      await loadBatch(labState.currentBatchId);
    } else {
      setImportMessage("Import your first signal file to begin.", "neutral");
    }
    bindEvents();
  }

  boot().catch((error) => {
    setImportMessage(error.message || "Signal Lab could not start.", "warn");
  });
})();
