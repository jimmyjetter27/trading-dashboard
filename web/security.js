const statusPill = document.querySelector("#securityStatusPill");
const refreshButton = document.querySelector("#securityRefreshButton");
const sourceRoot = document.querySelector("#securitySourceRoot");
const authCount = document.querySelector("#securityAuthCount");
const accountCount = document.querySelector("#securityAccountCount");
const ipCount = document.querySelector("#securityIpCount");
const logFileCount = document.querySelector("#securityLogFileCount");
const latestEvent = document.querySelector("#securityLatestEvent");
const scanSummary = document.querySelector("#securityScanSummary");
const limitations = document.querySelector("#securityLimitations");
const loginsBody = document.querySelector("#securityLoginsBody");
const body = document.body;
const sideNavToggle = document.querySelector("#sideNavToggle");

const sideNavCollapsed = localStorage.getItem("trade-observer-sidenav") === "collapsed";
if (sideNavCollapsed) {
  body.classList.add("sidenav-collapsed");
}
if (sideNavToggle) {
  sideNavToggle.textContent = sideNavCollapsed ? "Expand" : "Collapse";
  sideNavToggle.addEventListener("click", () => {
    const collapsed = !body.classList.contains("sidenav-collapsed");
    body.classList.toggle("sidenav-collapsed", collapsed);
    localStorage.setItem("trade-observer-sidenav", collapsed ? "collapsed" : "expanded");
    sideNavToggle.textContent = collapsed ? "Expand" : "Collapse";
  });
}

function formatUtc(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toISOString().replace("T", " ").replace(".000Z", " UTC").replace("Z", " UTC");
}

function fixed(value, digits = 2) {
  return Number(value || 0).toFixed(digits);
}

function setStatus(text, tone = "ok") {
  if (!statusPill) return;
  statusPill.textContent = text;
  statusPill.className = `status-pill ${tone}`;
}

function renderSecurity(payload) {
  const summary = payload?.summary || {};
  const events = Array.isArray(payload?.events) ? payload.events : [];
  const notes = Array.isArray(payload?.limitations) ? payload.limitations : [];

  if (sourceRoot) sourceRoot.textContent = payload?.source_root || "C:\\MT5\\JamesANabiah";
  if (authCount) authCount.textContent = String(summary.authorization_events || 0);
  if (accountCount) accountCount.textContent = String(summary.unique_accounts || 0);
  if (ipCount) ipCount.textContent = String(summary.unique_previous_ips || 0);
  if (logFileCount) logFileCount.textContent = String(summary.log_files_scanned || 0);
  if (latestEvent) latestEvent.textContent = summary.latest_event_time ? formatUtc(summary.latest_event_time) : "No events found";

  if (scanSummary) {
    scanSummary.innerHTML = `
      <article class="analysis-item neutral">
        <strong>Terminals scanned</strong>
        <p>${summary.terminals_scanned || 0}</p>
      </article>
      <article class="analysis-item neutral">
        <strong>Oldest event</strong>
        <p>${summary.oldest_event_time ? formatUtc(summary.oldest_event_time) : "-"}</p>
      </article>
      <article class="analysis-item neutral">
        <strong>Latest event</strong>
        <p>${summary.latest_event_time ? formatUtc(summary.latest_event_time) : "-"}</p>
      </article>
    `;
  }

  if (limitations) {
    limitations.innerHTML = notes.length
      ? notes.map((note) => `<article class="analysis-item neutral"><p>${note}</p></article>`).join("")
      : `<div class="empty-state">No notes returned.</div>`;
  }

  if (!loginsBody) return;
  if (!events.length) {
    loginsBody.innerHTML = `
      <tr>
        <td colspan="8">
          <div class="empty-state">No authorization events were found in the selected MT5 log files.</div>
        </td>
      </tr>
    `;
    return;
  }

  loginsBody.innerHTML = events.map((event) => `
    <tr>
      <td>${formatUtc(event.event_time)}</td>
      <td>${event.account_login || "-"}</td>
      <td>${event.server || "-"}</td>
      <td>${event.access_point ? `#${event.access_point}` : "-"}</td>
      <td>${event.ping_ms ? `${fixed(event.ping_ms)} ms` : "-"}</td>
      <td>${event.previous_ip || "-"}</td>
      <td>${event.previous_authorized_at ? formatUtc(event.previous_authorized_at) : "-"}</td>
      <td>${event.log_file || "-"}</td>
    </tr>
  `).join("");
}

async function loadSecurity() {
  setStatus("Loading Login History...", "ok");
  refreshButton && (refreshButton.disabled = true);
  try {
    const response = await fetch("/api/security-logins", { cache: "no-store" });
    if (!response.ok) throw new Error(`Request failed: ${response.status}`);
    const payload = await response.json();
    renderSecurity(payload);
    setStatus("Login History Loaded", "ok");
  } catch (error) {
    if (loginsBody) {
      loginsBody.innerHTML = `
        <tr>
          <td colspan="8">
            <div class="empty-state">Could not load MT5 login history from the JamesANabiah logs.</div>
          </td>
        </tr>
      `;
    }
    setStatus("Could Not Read Logs", "bad");
  } finally {
    refreshButton && (refreshButton.disabled = false);
  }
}

refreshButton?.addEventListener("click", () => {
  loadSecurity().catch(() => {});
});

loadSecurity().catch(() => {});
