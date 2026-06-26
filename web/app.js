const state = {
  theme: localStorage.getItem("trade-observer-theme") || "dark",
  lastAlertKey: localStorage.getItem("trade-observer-last-alert-key"),
  activeAlarmKey: null,
  activeAlarmInterval: null,
  audioContext: null,
  lastAnalysisDecisionKey: localStorage.getItem("trade-observer-last-analysis-decision-key"),
  lastAnalysisPromptKey: localStorage.getItem("trade-observer-last-analysis-prompt-key"),
  analysisGetReadyModalCycle: "",
  previousTradeLevels: {},
  localAlerts: [],
  hiddenJournalTickets: new Set(),
  useMt5Journal: true,
  accountProfiles: [],
  selectedProfileAlias: "",
  selectedProfileGroup: "",
  detectedTerminals: [],
  connected: false,
  journalAccountScope: localStorage.getItem("trade-observer-journal-account-scope") || "current",
  journalSelectedSymbols: JSON.parse(localStorage.getItem("trade-observer-journal-symbols") || "[]"),
  startupTerminalPromptDone: sessionStorage.getItem("trade-observer-startup-terminal-prompt") === "done",
  accountSnapshot: { balance: 0, equity: 0, leverage: 0, currency: "USD" },
  riskBasket: [],
  currentSymbol: "",
  activeTrades: [],
  pendingOrders: [],
  editingAccountProfileAlias: "",
  fakeoutLessonStep: 0,
  fakeoutLessonView: "illustration",
  fakeoutLessonLivePayload: null,
  activePage: "live",
  depositRange: localStorage.getItem("trade-observer-deposit-range") || "year",
  depositFiltersVisible: localStorage.getItem("trade-observer-deposit-filters-visible") !== "off",
  depositSelectedProfiles: JSON.parse(localStorage.getItem("trade-observer-deposit-selected-profiles") || "[]"),
  daySummaryFiltersVisible: localStorage.getItem("trade-observer-day-summary-filters-visible") !== "off",
  journalEntryScopeKey: "",
  journalEntryScopeLabel: "",
  emailNotificationsEnabled: true,
  tradeLockEnabled: false,
  notificationsEnabled: localStorage.getItem("trade-observer-notifications-enabled") !== "off",
  smtpConfigured: false,
  sideNavCollapsed: localStorage.getItem("trade-observer-sidenav") === "collapsed",
  analysis: null,
  analysisTimeframe: localStorage.getItem("trade-observer-analysis-timeframe") || "H1",
  markets: null,
  marketsView: localStorage.getItem("trade-observer-markets-view") || "cards",
  charts: null,
  securityLogins: null,
  consolidation: null,
  consolidationSymbol: localStorage.getItem("trade-observer-consolidation-symbol") || "xauusd",
  consolidationTimeframe: localStorage.getItem("trade-observer-consolidation-timeframe") || "M5",
  consolidationAlertState: JSON.parse(localStorage.getItem("trade-observer-consolidation-alert-state") || "{}"),
  riskChart: null,
  riskChartInteraction: {
    geometry: null,
    hoveredHandle: null,
    draggingHandle: null,
    dragPrice: null,
  },
  calculatorMode: localStorage.getItem("trade-observer-calculator-mode") || "profit",
  calculatorXauPipMode: localStorage.getItem("trade-observer-calculator-xau-pip-mode") || "0.01",
  chartSymbol: localStorage.getItem("trade-observer-chart-symbol") || "xauusd",
  chartTimeframe: localStorage.getItem("trade-observer-chart-timeframe") || "M1",
  chartType: localStorage.getItem("trade-observer-chart-type") || "candlestick",
  chartZoomLevel: Number(localStorage.getItem("trade-observer-chart-zoom") || 0),
  chartWatchers: JSON.parse(localStorage.getItem("trade-observer-chart-watchers") || "{}"),
  chartWatcherDrafts: JSON.parse(localStorage.getItem("trade-observer-chart-watcher-drafts") || "{}"),
  alertTypeEnabled: JSON.parse(localStorage.getItem("trade-observer-alert-type-enabled") || "{}"),
  chartHudFadeTimer: null,
  chartHudHideTimer: null,
  orlConfig: null,
  orlLiveStatus: null,
  orlHistorical: null,
  orlMode: "live",
  orlSymbols: [],
};

if (!localStorage.getItem("trade-observer-xau-pip-migrated-20260623")) {
  if (state.calculatorXauPipMode === "0.10") {
    state.calculatorXauPipMode = "0.01";
    localStorage.setItem("trade-observer-calculator-xau-pip-mode", "0.01");
  }
  localStorage.setItem("trade-observer-xau-pip-migrated-20260623", "done");
}

const API_BASE = window.location.protocol === "file:" ? "http://127.0.0.1:8765" : "";

function currentAnalysisPromptCycleKey() {
  return [
    document.body?.dataset?.currentPage || "dashboard",
    state.analysisTimeframe || "H1",
  ].join("|");
}

const ALERT_TOGGLE_DEFS = [
  ["entry", "Trade Started", "New trade entry alarms."],
  ["close", "Trade Closed", "Manual or general close notifications."],
  ["analysis_buy_confirmed", "Analysis Buy Now", "Confirmed analysis buy-now prompts."],
  ["analysis_break_even_prompt", "Analysis Break-Even", "Prompts to move stop loss to breakeven."],
  ["analysis_trailing_prompt", "Analysis Trail Stop", "Prompts to trail the stop on a live position."],
  ["liquidity_sweep_detected", "Liquidity Sweep", "Engineered liquidity sweep detection alerts."],
  ["closed_take_profit", "TP Closed", "When a trade closes at take profit."],
  ["take_profit_reached", "TP Reached", "When price reaches take profit on an open trade."],
  ["take_profit_updated", "TP Updated", "Take profit set or changed on a trade."],
  ["approaching_stop", "SL Warning", "Approaching stop loss warnings."],
  ["stop_loss_hit", "SL Hit", "When a trade hits stop loss."],
  ["stop_loss_updated", "SL Updated", "Stop loss set or changed on a trade."],
  ["capital_warning", "Capital Warning", "Equity and drawdown danger warnings."],
  ["account_blown", "Account Blown", "Critical account blowout alerts."],
  ["account_switched", "Account Switched", "When the monitored MT5 account changes."],
  ["trade_lock_breached", "Trade Lock Breached", "A trade opened while Trade Lock was enabled."],
  ["m5_direction_shift", "M5 Direction", "Bullish or bearish M5 shift alerts."],
  ["chart_target_progress", "Chart Progress", "25/50/75/90 percent chart watcher progress alerts."],
  ["chart_target_hit", "Chart Target Hit", "When a chart watcher target is reached."],
  ["consolidation_upper_zone", "Upper Zone", "Upper consolidation rejection zone tests."],
  ["consolidation_lower_zone", "Lower Zone", "Lower consolidation rejection zone tests."],
  ["consolidation_breakout_up", "Breakout Up", "Upside breakout from consolidation."],
  ["consolidation_breakout_down", "Breakout Down", "Downside breakout from consolidation."],
  ["consolidation_ended", "Consolidation Ended", "When the market no longer looks like consolidation."],
  ["orl_pre_close_alert", "ORL Pre-Close", "ORL pre-close heads-up alerts."],
  ["orl_range_captured", "ORL Range", "ORL opening range captured alerts."],
  ["orl_manipulation_confirmed", "ORL Confirmed", "ORL manipulation confirmation alerts."],
  ["orl_breakout_detected", "ORL Breakout", "ORL breakout detection alerts."],
  ["orl_signal_detected", "ORL Signal", "ORL signal detection alerts."],
];

const FAKEOUT_LESSON_STEPS = [
  {
    title: "Define the daily bias",
    timeframe: "H1",
    body: [
      "Before New York opens, decide whether the day already has a clear trend. For a bearish day, you want to see lower highs and lower lows, price sitting below the stronger moving averages, and enough structure from London or earlier to justify the bearish idea.",
      "The point is to explain the bias, not just label it. If H1 and H4 already lean lower, then a New York push up into liquidity is more likely to be a trap than a true bullish continuation."
    ],
    checklist: [
      "Mark the current H1 and H4 structure: are highs and lows stepping down?",
      "Check whether price is still below the stronger session averages.",
      "Ask whether London already delivered bearish pressure before New York arrives.",
      "Write one sentence explaining why the day is bearish."
    ],
    illustration: `
      <svg viewBox="0 0 1280 700" aria-hidden="true">
        <rect width="1280" height="700" rx="24" fill="#c8c8c8"></rect>
        <g stroke="rgba(0,0,0,0.08)">
          <line x1="80" y1="120" x2="1180" y2="120"></line>
          <line x1="80" y1="240" x2="1180" y2="240"></line>
          <line x1="80" y1="360" x2="1180" y2="360"></line>
          <line x1="80" y1="480" x2="1180" y2="480"></line>
          <line x1="80" y1="600" x2="1180" y2="600"></line>
        </g>
        <polyline points="110,180 210,220 310,250 410,295 520,330 630,362 735,404 845,446 955,492 1060,536" fill="none" stroke="#111" stroke-width="4"></polyline>
        <path d="M100 260 Q620 250 1130 390" fill="none" stroke="#2563eb" stroke-width="3"></path>
        <path d="M100 180 Q620 170 1130 305" fill="none" stroke="#6b7280" stroke-width="3"></path>
        <text x="94" y="82" font-size="30" fill="#111" font-weight="700">Step 1: bearish daily bias already established</text>
        <text x="812" y="246" font-size="22" fill="#111">price below the key averages</text>
        <text x="842" y="286" font-size="22" fill="#111">lower highs + lower lows</text>
        <text x="94" y="640" font-size="22" fill="#111">Bias first. New York fakeouts work better when they run against a trend that is already clearly defined.</text>
      </svg>
    `,
  },
  {
    title: "Wait for the New York fakeout against the trend",
    timeframe: "M15",
    body: [
      "In a bearish day, you want New York to push up first into an obvious liquidity area: Asian high, London high, a round number, a supply zone, an FVG, or an order block.",
      "That bullish fakeout is your trap zone. It attracts breakout buyers and gives the market a better place to grab liquidity before rotating back down with the daily bias."
    ],
    checklist: [
      "Mark Asian high, London high, previous highs, and major round numbers before NY.",
      "Let price push into one of those areas instead of selling too early.",
      "Treat the fakeout candle as the liquidity-grab zone, not the trade trigger."
    ],
    illustration: `
      <svg viewBox="0 0 1280 700" aria-hidden="true">
        <rect width="1280" height="700" rx="24" fill="#c8c8c8"></rect>
        <line x1="80" y1="198" x2="1180" y2="198" stroke="#b91c1c" stroke-dasharray="8 8" stroke-width="2"></line>
        <line x1="80" y1="224" x2="1180" y2="224" stroke="#2563eb" stroke-dasharray="8 8" stroke-width="2"></line>
        <rect x="892" y="154" width="132" height="116" fill="rgba(185, 28, 28, 0.16)" stroke="#b91c1c" stroke-dasharray="8 8"></rect>
        <polyline points="110,446 224,428 330,408 446,392 566,364 674,338 782,304 864,250 934,174 1018,232 1108,326" fill="none" stroke="#111" stroke-width="4"></polyline>
        <text x="1040" y="192" font-size="22" fill="#111">fakeout into liquidity</text>
        <text x="1040" y="224" font-size="22" fill="#111">or supply</text>
        <text x="92" y="190" font-size="20" fill="#b91c1c">London high</text>
        <text x="92" y="218" font-size="20" fill="#2563eb">Asian high</text>
        <text x="846" y="146" font-size="22" fill="#6d1010" font-weight="700">liquidity grab zone</text>
        <text x="92" y="640" font-size="22" fill="#111">The fakeout should move into something obvious, not into empty space.</text>
      </svg>
    `,
  },
  {
    title: "Drop to 5M and wait for proof",
    timeframe: "M5",
    body: [
      "After price reaches the fakeout area, stop trying to predict the top. On the 5-minute chart, wait for evidence that the bullish fakeout is failing: a rejection wick, bearish engulfing, a break of a nearby higher low, and stronger bearish closes.",
      "This is where the trade becomes safer. You are no longer selling because price touched a level; you are selling because the reaction is proving itself."
    ],
    checklist: [
      "Look for a rejection wick or a failed push through the fakeout high.",
      "Watch whether bullish candles lose momentum and bearish bodies begin closing stronger.",
      "Wait for a small 5M structure break instead of acting on the first touch."
    ],
    illustration: `
      <svg viewBox="0 0 1280 700" aria-hidden="true">
        <rect width="1280" height="700" rx="24" fill="#c8c8c8"></rect>
        <rect x="876" y="156" width="160" height="112" fill="rgba(185, 28, 28, 0.15)" stroke="#b91c1c" stroke-dasharray="8 8"></rect>
        <line x1="896" y1="286" x2="1128" y2="286" stroke="#111" stroke-dasharray="8 8" stroke-width="2"></line>
        <polyline points="180,490 266,470 352,442 438,422 524,404 610,392 696,378 782,364 868,348 954,332 1040,370 1126,420" fill="none" stroke="#111" stroke-width="4"></polyline>
        <text x="982" y="146" font-size="22" fill="#6d1010" font-weight="700">rejection wick</text>
        <text x="934" y="278" font-size="22" fill="#111">5M higher low breaks</text>
        <text x="90" y="640" font-size="22" fill="#111">This is the “wait” step. The level matters, but price still has to prove buyers are failing.</text>
      </svg>
    `,
  },
  {
    title: "Enter only after bearish confirmation",
    timeframe: "M5",
    body: [
      "A stronger sell entry comes after the fakeout high rejects, a minor 5M low breaks, and price gives either a failed retest or a clean bearish continuation candle. That sequence is much stronger than selling the first red candle you see.",
      "Think in sequence: rejection, break, retest, continuation. That reduces the chance of being trapped inside the fakeout chop."
    ],
    checklist: [
      "Was there a real break of a nearby 5M low?",
      "Did price retest and fail, or did a momentum bearish close confirm continuation?",
      "Is the entry still close enough to the fakeout high to keep the stop sensible?"
    ],
    illustration: `
      <svg viewBox="0 0 1280 700" aria-hidden="true">
        <rect width="1280" height="700" rx="24" fill="#c8c8c8"></rect>
        <line x1="688" y1="298" x2="952" y2="298" stroke="#b91c1c" stroke-dasharray="8 8" stroke-width="2"></line>
        <line x1="930" y1="280" x2="930" y2="462" stroke="#2563eb" stroke-dasharray="8 8" stroke-width="2"></line>
        <circle cx="930" cy="318" r="8" fill="#2563eb"></circle>
        <polyline points="256,436 344,420 432,402 520,378 608,354 696,350 784,386 872,344 960,392 1048,438" fill="none" stroke="#111" stroke-width="4"></polyline>
        <text x="952" y="286" font-size="22" fill="#6d1010">failed retest</text>
        <text x="946" y="334" font-size="22" fill="#124d1e">entry after confirmation</text>
        <text x="92" y="640" font-size="22" fill="#111">The edge is not the first red candle. The edge is the confirmed failure after the fakeout.</text>
      </svg>
    `,
  },
  {
    title: "Place stop loss and targets logically",
    timeframe: "M15",
    body: [
      "For sells, the stop normally belongs above the fakeout high because that is the invalidation point. If price reclaims and holds above it, the setup has changed.",
      "Take-profit targets should scale through nearby liquidity first, then broader session lows, and only stretch into a deeper H1 target if momentum stays strong enough to justify it."
    ],
    checklist: [
      "SL above the fakeout high, not randomly inside the structure.",
      "TP1 at the nearest 5M or 15M support / liquidity low.",
      "TP2 around the previous low, London low, or the day’s low.",
      "TP3 only if momentum still supports a stronger H1 liquidity target."
    ],
    illustration: `
      <svg viewBox="0 0 1280 700" aria-hidden="true">
        <rect width="1280" height="700" rx="24" fill="#c8c8c8"></rect>
        <line x1="190" y1="222" x2="1110" y2="222" stroke="#b91c1c" stroke-dasharray="10 8" stroke-width="3"></line>
        <line x1="190" y1="288" x2="1110" y2="288" stroke="#2563eb" stroke-dasharray="10 8" stroke-width="3"></line>
        <line x1="190" y1="420" x2="1110" y2="420" stroke="#16a34a" stroke-dasharray="10 8" stroke-width="3"></line>
        <line x1="190" y1="506" x2="1110" y2="506" stroke="#15803d" stroke-dasharray="10 8" stroke-width="3"></line>
        <line x1="190" y1="570" x2="1110" y2="570" stroke="#14532d" stroke-dasharray="10 8" stroke-width="3"></line>
        <polyline points="288,260 390,246 492,268 594,286 696,302 798,330" fill="none" stroke="#111" stroke-width="4"></polyline>
        <text x="1122" y="228" font-size="20" fill="#6d1010">SL above fakeout high</text>
        <text x="1122" y="294" font-size="20" fill="#1d4ed8">Entry after confirmation</text>
        <text x="1122" y="426" font-size="20" fill="#166534">TP1 nearby liquidity</text>
        <text x="1122" y="512" font-size="20" fill="#166534">TP2 prior low / London low</text>
        <text x="1122" y="576" font-size="20" fill="#14532d">TP3 stronger H1 target</text>
      </svg>
    `,
  },
];

const els = {
  body: document.body,
  sideNav: document.querySelector("#sideNav"),
  sideNavToggle: document.querySelector("#sideNavToggle"),
  connectionPill: document.querySelector("#connectionPill"),
  accountProfileSelect: document.querySelector("#accountProfileSelect"),
  emailToggleWrap: document.querySelector("#emailToggleWrap"),
  emailToggleInput: document.querySelector("#emailToggleInput"),
  emailToggleLabel: document.querySelector("#emailToggleLabel"),
  notificationsToggleWrap: document.querySelector("#notificationsToggleWrap"),
  notificationsToggleInput: document.querySelector("#notificationsToggleInput"),
  notificationsToggleLabel: document.querySelector("#notificationsToggleLabel"),
  tradeLockToggleWrap: document.querySelector("#tradeLockToggleWrap"),
  tradeLockToggleInput: document.querySelector("#tradeLockToggleInput"),
  tradeLockToggleLabel: document.querySelector("#tradeLockToggleLabel"),
  manageAccountsButton: document.querySelector("#manageAccountsButton"),
  connectButton: document.querySelector("#connectButton"),
  disconnectButton: document.querySelector("#disconnectButton"),
  depositsButton: document.querySelector("#depositsButton"),
  daySummaryButton: document.querySelector("#daySummaryButton"),
  clearDbButton: document.querySelector("#clearDbButton"),
  themeToggle: document.querySelector("#themeToggle"),
  balanceValue: document.querySelector("#balanceValue"),
  balanceMeta: document.querySelector("#balanceMeta"),
  equityValue: document.querySelector("#equityValue"),
  equityMeta: document.querySelector("#equityMeta"),
  profitValue: document.querySelector("#profitValue"),
  profitMeta: document.querySelector("#profitMeta"),
  accountValue: document.querySelector("#accountValue"),
  serverMeta: document.querySelector("#serverMeta"),
  journalKicker: document.querySelector("#journalKicker"),
  journalTitle: document.querySelector("#journalTitle"),
  journalAccountScope: document.querySelector("#journalAccountScope"),
  alertsList: document.querySelector("#alertsList"),
  tradeCards: document.querySelector("#tradeCards"),
  pendingOrderCards: document.querySelector("#pendingOrderCards"),
  journalDays: document.querySelector("#journalDays"),
  totalProfitValue: document.querySelector("#totalProfitValue"),
  totalTradesValue: document.querySelector("#totalTradesValue"),
  totalWinsValue: document.querySelector("#totalWinsValue"),
  totalLossesValue: document.querySelector("#totalLossesValue"),
  weeklyProfitValue: document.querySelector("#weeklyProfitValue"),
  weeklyTradesMeta: document.querySelector("#weeklyTradesMeta"),
  monthlyProfitValue: document.querySelector("#monthlyProfitValue"),
  monthlyTradesMeta: document.querySelector("#monthlyTradesMeta"),
  yearlyProfitValue: document.querySelector("#yearlyProfitValue"),
  yearlyTradesMeta: document.querySelector("#yearlyTradesMeta"),
  journalInsightCards: document.querySelector("#journalInsightCards"),
  journalDayBreakdown: document.querySelector("#journalDayBreakdown"),
  journalTimeBreakdown: document.querySelector("#journalTimeBreakdown"),
  journalSetupBreakdown: document.querySelector("#journalSetupBreakdown"),
  journalIdeas: document.querySelector("#journalIdeas"),
  journalEntryDateInput: document.querySelector("#journalEntryDateInput"),
  journalSessionGradeInput: document.querySelector("#journalSessionGradeInput"),
  journalFollowedPlanInput: document.querySelector("#journalFollowedPlanInput"),
  journalEmotionInput: document.querySelector("#journalEmotionInput"),
  journalBestSetupInput: document.querySelector("#journalBestSetupInput"),
  journalTagsInput: document.querySelector("#journalTagsInput"),
  journalMarketConditionsInput: document.querySelector("#journalMarketConditionsInput"),
  journalWhatWentWellInput: document.querySelector("#journalWhatWentWellInput"),
  journalMistakesInput: document.querySelector("#journalMistakesInput"),
  journalLessonInput: document.querySelector("#journalLessonInput"),
  journalNextFocusInput: document.querySelector("#journalNextFocusInput"),
  journalLoadEntryButton: document.querySelector("#journalLoadEntryButton"),
  journalSaveEntryButton: document.querySelector("#journalSaveEntryButton"),
  journalAutoReviewCards: document.querySelector("#journalAutoReviewCards"),
  journalAutoReviewIdeas: document.querySelector("#journalAutoReviewIdeas"),
  rangeFilter: document.querySelector("#rangeFilter"),
  dateFilter: document.querySelector("#dateFilter"),
  outcomeFilter: document.querySelector("#outcomeFilter"),
  lotFilter: document.querySelector("#lotFilter"),
  journalSymbolOptions: document.querySelector("#journalSymbolOptions"),
  specialFilter: document.querySelector("#specialFilter"),
  canvas: document.querySelector("#priceCanvas"),
  alarmModal: document.querySelector("#alarmModal"),
  alarmDialog: document.querySelector("#alarmDialog"),
  alarmKicker: document.querySelector("#alarmKicker"),
  alarmTitle: document.querySelector("#alarmTitle"),
  alarmMessage: document.querySelector("#alarmMessage"),
  alarmTradeMeta: document.querySelector("#alarmTradeMeta"),
  alarmTimeMeta: document.querySelector("#alarmTimeMeta"),
  stopAlarmButton: document.querySelector("#stopAlarmButton"),
  launchBanner: document.querySelector("#launchBanner"),
  launchBannerText: document.querySelector("#launchBannerText"),
  launchBannerLink: document.querySelector("#launchBannerLink"),
  serverBanner: document.querySelector("#serverBanner"),
  serverBannerText: document.querySelector("#serverBannerText"),
  retryServerButton: document.querySelector("#retryServerButton"),
  terminalSwitchGrid: document.querySelector("#terminalSwitchGrid"),
  fundingModal: document.querySelector("#fundingModal"),
  closeFundingButton: document.querySelector("#closeFundingButton"),
  depositTotalUsd: document.querySelector("#depositTotalUsd"),
  depositAccountsCount: document.querySelector("#depositAccountsCount"),
  depositCount: document.querySelector("#depositCount"),
  depositRateText: document.querySelector("#depositRateText"),
  depositRangeFilter: document.querySelector("#depositRangeFilter"),
  depositAccountOptions: document.querySelector("#depositAccountOptions"),
  applyFundingFiltersButton: document.querySelector("#applyFundingFiltersButton"),
  toggleFundingFiltersButton: document.querySelector("#toggleFundingFiltersButton"),
  fundingFiltersPanel: document.querySelector("#fundingFiltersPanel"),
  fundingWarnings: document.querySelector("#fundingWarnings"),
  fundingList: document.querySelector("#fundingList"),
  accountsModal: document.querySelector("#accountsModal"),
  daySummaryModal: document.querySelector("#daySummaryModal"),
  closeDaySummaryButton: document.querySelector("#closeDaySummaryButton"),
  toggleDaySummaryFiltersButton: document.querySelector("#toggleDaySummaryFiltersButton"),
  daySummaryFiltersPanel: document.querySelector("#daySummaryFiltersPanel"),
  daySummaryDateInput: document.querySelector("#daySummaryDateInput"),
  applyDaySummaryButton: document.querySelector("#applyDaySummaryButton"),
  daySummaryScopeText: document.querySelector("#daySummaryScopeText"),
  daySummaryProfitValue: document.querySelector("#daySummaryProfitValue"),
  daySummaryStartingBalance: document.querySelector("#daySummaryStartingBalance"),
  daySummaryDeposits: document.querySelector("#daySummaryDeposits"),
  daySummaryEndingBalance: document.querySelector("#daySummaryEndingBalance"),
  daySummaryTradeCount: document.querySelector("#daySummaryTradeCount"),
  daySummaryWinLoss: document.querySelector("#daySummaryWinLoss"),
  daySummaryWarnings: document.querySelector("#daySummaryWarnings"),
  closeAccountsButton: document.querySelector("#closeAccountsButton"),
  accountProfileForm: document.querySelector("#accountProfileForm"),
  profileAliasInput: document.querySelector("#profileAliasInput"),
  profileLoginInput: document.querySelector("#profileLoginInput"),
  profilePasswordInput: document.querySelector("#profilePasswordInput"),
  profileServerInput: document.querySelector("#profileServerInput"),
  profileTerminalPathInput: document.querySelector("#profileTerminalPathInput"),
  profileGroupInput: document.querySelector("#profileGroupInput"),
  saveAccountProfileButton: document.querySelector("#saveAccountProfileButton"),
  accountProfilesList: document.querySelector("#accountProfilesList"),
  toastStack: document.querySelector("#toastStack"),
  alarmTestGrid: document.querySelector("#alarmTestGrid"),
  pageNav: document.querySelector("#pageNav"),
  pagePanels: [...document.querySelectorAll("[data-page-panel]")],
  analysisCanvas: document.querySelector("#analysisCanvas"),
  analysisStage: document.querySelector("#analysisStage"),
  analysisFullscreenButton: document.querySelector("#analysisFullscreenButton"),
  analysisSymbol: document.querySelector("#analysisSymbol"),
  analysisTimeframe: document.querySelector("#analysisTimeframe"),
  analysisTimeframeSelect: document.querySelector("#analysisTimeframeSelect"),
  analysisBias: document.querySelector("#analysisBias"),
  analysisPrice: document.querySelector("#analysisPrice"),
  analysisSession: document.querySelector("#analysisSession"),
  analysisPrediction: document.querySelector("#analysisPrediction"),
  analysisOpenMarkets: document.querySelector("#analysisOpenMarkets"),
  analysisTradeRead: document.querySelector("#analysisTradeRead"),
  analysisGateChecks: document.querySelector("#analysisGateChecks"),
  analysisRiskPlan: document.querySelector("#analysisRiskPlan"),
  analysisBotContext: document.querySelector("#analysisBotContext"),
  analysisManagementPlan: document.querySelector("#analysisManagementPlan"),
  analysisZones: document.querySelector("#analysisZones"),
  analysisConfluences: document.querySelector("#analysisConfluences"),
  chartsCanvas: document.querySelector("#chartsCanvas"),
  chartStage: document.querySelector("#chartStage"),
  chartSymbolSelect: document.querySelector("#chartSymbolSelect"),
  chartTypeToggle: document.querySelector("#chartTypeToggle"),
  chartTimeframeStrip: document.querySelector("#chartTimeframeStrip"),
  chartFullscreenButton: document.querySelector("#chartFullscreenButton"),
  chartFullscreenHud: document.querySelector("#chartFullscreenHud"),
  chartFullscreenTimeframes: document.querySelector("#chartFullscreenTimeframes"),
  chartZoomOutButton: document.querySelector("#chartZoomOutButton"),
  chartZoomInButton: document.querySelector("#chartZoomInButton"),
  chartResolvedSymbol: document.querySelector("#chartResolvedSymbol"),
  chartCurrentTimeframe: document.querySelector("#chartCurrentTimeframe"),
  chartCurrentType: document.querySelector("#chartCurrentType"),
  chartCurrentPrice: document.querySelector("#chartCurrentPrice"),
  chartTradeOverlayList: document.querySelector("#chartTradeOverlayList"),
  chartStatusList: document.querySelector("#chartStatusList"),
  chartBullishTargetInput: document.querySelector("#chartBullishTargetInput"),
  chartBearishTargetInput: document.querySelector("#chartBearishTargetInput"),
  chartWatcherArmButton: document.querySelector("#chartWatcherArmButton"),
  chartWatcherClearButton: document.querySelector("#chartWatcherClearButton"),
  chartWatcherSummary: document.querySelector("#chartWatcherSummary"),
  alertSettingsList: document.querySelector("#alertSettingsList"),
  securityRefreshButton: document.querySelector("#securityRefreshButton"),
  securityAuthCount: document.querySelector("#securityAuthCount"),
  securityAccountCount: document.querySelector("#securityAccountCount"),
  securityIpCount: document.querySelector("#securityIpCount"),
  securityTerminalCount: document.querySelector("#securityTerminalCount"),
  securityLimitations: document.querySelector("#securityLimitations"),
  securityScanSummary: document.querySelector("#securityScanSummary"),
  securityLatestEvent: document.querySelector("#securityLatestEvent"),
  securityLoginsBody: document.querySelector("#securityLoginsBody"),
  consolidationCanvas: document.querySelector("#consolidationCanvas"),
  consolidationSymbolSelect: document.querySelector("#consolidationSymbolSelect"),
  consolidationTimeframeStrip: document.querySelector("#consolidationTimeframeStrip"),
  consolidationResolvedSymbol: document.querySelector("#consolidationResolvedSymbol"),
  consolidationCurrentTimeframe: document.querySelector("#consolidationCurrentTimeframe"),
  consolidationStatusBadge: document.querySelector("#consolidationStatusBadge"),
  consolidationCurrentPrice: document.querySelector("#consolidationCurrentPrice"),
  consolidationRangeSize: document.querySelector("#consolidationRangeSize"),
  consolidationRangeList: document.querySelector("#consolidationRangeList"),
  consolidationStatusList: document.querySelector("#consolidationStatusList"),
  riskPlannerBalance: document.querySelector("#riskPlannerBalance"),
  riskPlannerEquity: document.querySelector("#riskPlannerEquity"),
  riskPlannerLeverage: document.querySelector("#riskPlannerLeverage"),
  riskPlannerSuggestedRisk: document.querySelector("#riskPlannerSuggestedRisk"),
  riskSymbolInput: document.querySelector("#riskSymbolInput"),
  riskSideSelect: document.querySelector("#riskSideSelect"),
  riskLotInput: document.querySelector("#riskLotInput"),
  riskEntryInput: document.querySelector("#riskEntryInput"),
  riskStopInput: document.querySelector("#riskStopInput"),
  riskTargetInput: document.querySelector("#riskTargetInput"),
  riskBalanceInput: document.querySelector("#riskBalanceInput"),
  riskPercentInput: document.querySelector("#riskPercentInput"),
  riskTimeframeSelect: document.querySelector("#riskTimeframeSelect"),
  riskPlannerRunButton: document.querySelector("#riskPlannerRunButton"),
  riskPlannerAddTradeButton: document.querySelector("#riskPlannerAddTradeButton"),
  riskPlannerClearBasketButton: document.querySelector("#riskPlannerClearBasketButton"),
  riskPlannerMessage: document.querySelector("#riskPlannerMessage"),
  riskPlannerCards: document.querySelector("#riskPlannerCards"),
  riskBasketCards: document.querySelector("#riskBasketCards"),
  riskBasketList: document.querySelector("#riskBasketList"),
  riskPlannerMarketNotes: document.querySelector("#riskPlannerMarketNotes"),
  riskPlannerResults: document.querySelector("#riskPlannerResults"),
  riskPlannerCanvas: document.querySelector("#riskPlannerCanvas"),
  riskChartMessage: document.querySelector("#riskChartMessage"),
  riskGuideConcepts: document.querySelector("#riskGuideConcepts"),
  riskGuideAccount: document.querySelector("#riskGuideAccount"),
  calculatorModeStrip: document.querySelector("#calculatorModeStrip"),
  calculatorModeMessage: document.querySelector("#calculatorModeMessage"),
  calcSymbolInput: document.querySelector("#calcSymbolInput"),
  calcSideField: document.querySelector("#calcSideField"),
  calcSideSelect: document.querySelector("#calcSideSelect"),
  calcLotField: document.querySelector("#calcLotField"),
  calcLotInput: document.querySelector("#calcLotInput"),
  calcOpenField: document.querySelector("#calcOpenField"),
  calcOpenInput: document.querySelector("#calcOpenInput"),
  calcCloseField: document.querySelector("#calcCloseField"),
  calcCloseInput: document.querySelector("#calcCloseInput"),
  calcEntryField: document.querySelector("#calcEntryField"),
  calcEntryInput: document.querySelector("#calcEntryInput"),
  calcStopLossField: document.querySelector("#calcStopLossField"),
  calcStopLossInput: document.querySelector("#calcStopLossInput"),
  calcTakeProfitField: document.querySelector("#calcTakeProfitField"),
  calcTakeProfitInput: document.querySelector("#calcTakeProfitInput"),
  calcAccountSizeField: document.querySelector("#calcAccountSizeField"),
  calcAccountSizeInput: document.querySelector("#calcAccountSizeInput"),
  calcRiskPercentField: document.querySelector("#calcRiskPercentField"),
  calcRiskPercentInput: document.querySelector("#calcRiskPercentInput"),
  calcStopLossPipsField: document.querySelector("#calcStopLossPipsField"),
  calcStopLossPipsLabel: document.querySelector("#calcStopLossPipsLabel"),
  calcStopLossPipsInput: document.querySelector("#calcStopLossPipsInput"),
  calcPipSizeField: document.querySelector("#calcPipSizeField"),
  calcPipSizeInput: document.querySelector("#calcPipSizeInput"),
  calcXauPipModeField: document.querySelector("#calcXauPipModeField"),
  calcXauPipModeSelect: document.querySelector("#calcXauPipModeSelect"),
  calcContractSizeField: document.querySelector("#calcContractSizeField"),
  calcContractSizeInput: document.querySelector("#calcContractSizeInput"),
  calcQuoteCurrencyField: document.querySelector("#calcQuoteCurrencyField"),
  calcQuoteCurrencyInput: document.querySelector("#calcQuoteCurrencyInput"),
  calculatorRunButton: document.querySelector("#calculatorRunButton"),
  calculatorMarketNotes: document.querySelector("#calculatorMarketNotes"),
  calculatorResults: document.querySelector("#calculatorResults"),
  openFakeoutLessonButton: document.querySelector("#openFakeoutLessonButton"),
  fakeoutLessonModal: document.querySelector("#fakeoutLessonModal"),
  closeFakeoutLessonButton: document.querySelector("#closeFakeoutLessonButton"),
  fakeoutLessonStepper: document.querySelector("#fakeoutLessonStepper"),
  fakeoutLessonStepKicker: document.querySelector("#fakeoutLessonStepKicker"),
  fakeoutLessonStepTitle: document.querySelector("#fakeoutLessonStepTitle"),
  fakeoutLessonBody: document.querySelector("#fakeoutLessonBody"),
  fakeoutLessonChecklist: document.querySelector("#fakeoutLessonChecklist"),
  fakeoutLessonPrevButton: document.querySelector("#fakeoutLessonPrevButton"),
  fakeoutLessonNextButton: document.querySelector("#fakeoutLessonNextButton"),
  fakeoutLessonViewToggle: document.querySelector("#fakeoutLessonViewToggle"),
  fakeoutLessonIllustration: document.querySelector("#fakeoutLessonIllustration"),
  fakeoutIllustrationPanel: document.querySelector("#fakeoutIllustrationPanel"),
  fakeoutLivePanel: document.querySelector("#fakeoutLivePanel"),
  fakeoutLessonLiveCanvas: document.querySelector("#fakeoutLessonLiveCanvas"),
  orlLiveModeButton: document.querySelector("#orlLiveModeButton"),
  orlPastModeButton: document.querySelector("#orlPastModeButton"),
  orlViewDetailsButton: document.querySelector("#orlViewDetailsButton"),
  orlLiveSession: document.querySelector("#orlLiveSession"),
  orlLiveStatus: document.querySelector("#orlLiveStatus"),
  orlLiveManipulation: document.querySelector("#orlLiveManipulation"),
  orlLiveSignal: document.querySelector("#orlLiveSignal"),
  orlLiveAlertWindow: document.querySelector("#orlLiveAlertWindow"),
  orlLiveMessage: document.querySelector("#orlLiveMessage"),
  orlLiveSignalCard: document.querySelector("#orlLiveSignalCard"),
  orlHistoricalResultCard: document.querySelector("#orlHistoricalResultCard"),
  analysisLiveChartSection: document.querySelector("#analysisLiveChartSection"),
  orlHistoricalSection: document.querySelector("#orlHistoricalSection"),
  orlBackToLiveButton: document.querySelector("#orlBackToLiveButton"),
  orlHistoricalCanvas: document.querySelector("#orlHistoricalCanvas"),
  orlHistoricalNarrative: document.querySelector("#orlHistoricalNarrative"),
  orlHistoricalLogs: document.querySelector("#orlHistoricalLogs"),
  orlAnalyzeModal: document.querySelector("#orlAnalyzeModal"),
  closeOrlAnalyzeModalButton: document.querySelector("#closeOrlAnalyzeModalButton"),
  orlAnalyzeForm: document.querySelector("#orlAnalyzeForm"),
  orlSymbolSelect: document.querySelector("#orlSymbolSelect"),
  orlDateInput: document.querySelector("#orlDateInput"),
  orlSessionSelect: document.querySelector("#orlSessionSelect"),
  orlTimezoneModeSelect: document.querySelector("#orlTimezoneModeSelect"),
  orlAtrPeriodInput: document.querySelector("#orlAtrPeriodInput"),
  orlAtrThresholdInput: document.querySelector("#orlAtrThresholdInput"),
  orlBoxExtensionInput: document.querySelector("#orlBoxExtensionInput"),
  orlStartingBalanceInput: document.querySelector("#orlStartingBalanceInput"),
  orlLotSizeInput: document.querySelector("#orlLotSizeInput"),
  orlRiskModeSelect: document.querySelector("#orlRiskModeSelect"),
  orlCustomHourInput: document.querySelector("#orlCustomHourInput"),
  orlCustomMinuteInput: document.querySelector("#orlCustomMinuteInput"),
  submitOrlAnalyzeButton: document.querySelector("#submitOrlAnalyzeButton"),
  orlAnalyzeValidation: document.querySelector("#orlAnalyzeValidation"),
  orlDetailsModal: document.querySelector("#orlDetailsModal"),
  closeOrlDetailsModalButton: document.querySelector("#closeOrlDetailsModalButton"),
  orlDetailsContent: document.querySelector("#orlDetailsContent"),
  marketsGrid: document.querySelector("#marketsGrid"),
  marketsOpenNow: document.querySelector("#marketsOpenNow"),
  marketsTimezone: document.querySelector("#marketsTimezone"),
  marketsUtcNow: document.querySelector("#marketsUtcNow"),
  marketsUpdatedAt: document.querySelector("#marketsUpdatedAt"),
  marketsViewToggle: document.querySelector("#marketsViewToggle"),
};

const ctx = els.canvas?.getContext("2d");
const analysisCtx = els.analysisCanvas?.getContext("2d");
const chartsCtx = els.chartsCanvas?.getContext("2d");
const consolidationCtx = els.consolidationCanvas?.getContext("2d");
const riskPlannerCtx = els.riskPlannerCanvas?.getContext("2d");
const orlHistoricalCtx = els.orlHistoricalCanvas?.getContext("2d");

function applyTheme() {
  els.body.classList.toggle("light", state.theme === "light");
}

function applySideNavState() {
  els.body.classList.toggle("sidenav-collapsed", state.sideNavCollapsed);
  if (els.sideNavToggle) {
    els.sideNavToggle.textContent = state.sideNavCollapsed ? "Expand" : "Collapse";
  }
}

function resolvePage() {
  const fromBody = (document.body?.dataset?.currentPage || "").trim().toLowerCase();
  const fromPath = window.location.pathname
    .replace(/^\//, "")
    .replace(/\.html$/i, "")
    .trim()
    .toLowerCase();
  const fromStorage = localStorage.getItem("trade-observer-page") || "live";
  const candidate = fromBody || fromPath || fromStorage;
  return ["live", "journal", "tools", "analysis", "market-intel", "playbook", "signal-lab", "markets", "charts", "xau-chart", "liquidity-sweeps", "consolidation", "calculator", "risk"].includes(candidate) ? candidate : "live";
}

function ensureDynamicPageLinks() {
  const pageNav = els.pageNav;
  if (!pageNav) return;
  pageNav.querySelectorAll('[data-page="signal-lab"]').forEach((node) => node.remove());
  if (!pageNav.querySelector('[data-page="market-intel"]')) {
    const anchor = document.createElement("a");
    anchor.className = "theme-button page-tab";
    anchor.href = "/market-intel";
    anchor.setAttribute("data-page", "market-intel");
    anchor.setAttribute("data-tooltip", "Market Intel");
    anchor.innerHTML = '<svg class="page-tab-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 19h16"></path><path d="M6 15l3-3 3 2 5-6"></path><path d="M18 7h-4"></path><path d="M18 7v4"></path></svg><span class="page-tab-label">Market Intel</span>';
    const analysisLink = pageNav.querySelector('[data-page="analysis"]');
    if (analysisLink?.nextSibling) {
      analysisLink.parentNode.insertBefore(anchor, analysisLink.nextSibling);
    } else if (analysisLink?.parentNode) {
      analysisLink.parentNode.appendChild(anchor);
    } else {
      pageNav.appendChild(anchor);
    }
  }
  if (!pageNav.querySelector('[data-page="liquidity-sweeps"]')) {
    const anchor = document.createElement("a");
    anchor.className = "theme-button page-tab";
    anchor.href = "/liquidity-sweeps";
    anchor.setAttribute("data-page", "liquidity-sweeps");
    anchor.setAttribute("data-tooltip", "Liquidity Sweeps");
    anchor.innerHTML = '<svg class="page-tab-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 19h16"></path><path d="M6 8h12"></path><path d="M8 8c0 4 2 6 4 8"></path><path d="M16 8c0 4-2 6-4 8"></path><path d="M9 16h6"></path></svg><span class="page-tab-label">Liquidity Sweeps</span>';
    const xauLink = pageNav.querySelector('[data-page="xau-chart"]');
    if (xauLink?.nextSibling) {
      xauLink.parentNode.insertBefore(anchor, xauLink.nextSibling);
    } else if (xauLink?.parentNode) {
      xauLink.parentNode.appendChild(anchor);
    } else {
      pageNav.appendChild(anchor);
    }
  }
}

function applyActivePage() {
  state.activePage = resolvePage();
  els.pageNav?.querySelectorAll("[data-page]").forEach((button) => {
    button.classList.toggle("active", button.getAttribute("data-page") === state.activePage);
  });
  els.pagePanels.forEach((panel) => {
    panel.classList.toggle("hidden-page", panel.getAttribute("data-page-panel") !== state.activePage);
  });
}

function updateSummaryScrollState() {
  els.body.classList.toggle("summary-scrolled", window.scrollY > 12);
}

function money(value) {
  const sign = value < 0 ? "-" : "";
  return `${sign}$${Math.abs(Number(value || 0)).toFixed(2)}`;
}

function moneyCent(value) {
  const numeric = Number(value || 0);
  const sign = numeric < 0 ? "-" : "";
  const cents = Math.abs(numeric);
  const dollars = cents / 100;
  return `${sign}$${dollars.toFixed(2)} (${sign}${cents.toFixed(2)}c)`;
}

function textLooksCent(value) {
  const text = String(value || "").trim().toLowerCase();
  return text.includes("usc") || text.includes("cent");
}

function findProfileByAlias(alias) {
  const normalized = String(alias || "").trim();
  return state.accountProfiles.find((profile) => String(profile.alias || "").trim() === normalized) || null;
}

function profileLooksCent(profile) {
  if (!profile) return false;
  return textLooksCent(profile.group) || textLooksCent(profile.alias) || textLooksCent(profile.server);
}

function currentConnectedAccountIsCent() {
  const selectedProfile = findProfileByAlias(state.selectedProfileAlias);
  if (profileLooksCent(selectedProfile)) return true;
  if (textLooksCent(state.selectedProfileGroup)) return true;
  if (textLooksCent(state.accountSnapshot?.server)) return true;
  return false;
}

function journalScopeIsCent() {
  const accountScope = els.journalAccountScope?.value || state.journalAccountScope || "current";
  if (accountScope === "current") {
    return currentConnectedAccountIsCent();
  }
  if (accountScope.startsWith("profile:")) {
    return profileLooksCent(findProfileByAlias(accountScope.slice("profile:".length)));
  }
  if (accountScope === "both_live") {
    const liveProfiles = getKnownLiveProfiles();
    return liveProfiles.length > 0 && liveProfiles.every((profile) => profileLooksCent(profile));
  }
  return false;
}

function displayMoney(value, { centMode = false } = {}) {
  return centMode ? moneyCent(value) : money(value);
}

function moneyGhs(value) {
  return `GHS ${Math.abs(Number(value || 0)).toFixed(2)}`;
}

function fixed(value, digits = 2) {
  return Number(value || 0).toFixed(digits);
}

function formatLotSuggestion(value) {
  const numeric = Number(value || 0);
  if (!Number.isFinite(numeric) || numeric <= 0) return "0.0000";
  if (numeric < 0.01) return numeric.toFixed(4);
  return numeric.toFixed(2);
}

const calculatorPresets = {
  XAUUSD: {
    pipSize: 0.01,
    contractSize: 100,
    quoteCurrency: "USD",
    notes: "Gold default here matches the live desk: 1 pip = 0.01 price move.",
    minLot: 0.01,
    maxLot: 100,
  },
  GOLD: {
    pipSize: 0.01,
    contractSize: 100,
    quoteCurrency: "USD",
    notes: "Gold default here matches the live desk: 1 pip = 0.01 price move.",
    minLot: 0.01,
    maxLot: 100,
  },
  BTCUSD: {
    pipSize: 1,
    contractSize: 1,
    quoteCurrency: "USD",
    notes: "Simple crypto assumption: 1 lot = 1 BTC, pip = 1.0",
    minLot: 0.01,
    maxLot: 100,
  },
  EURUSD: {
    pipSize: 0.0001,
    contractSize: 100000,
    quoteCurrency: "USD",
    notes: "Typical forex assumption: 1 lot = 100,000 base units, pip = 0.0001",
    minLot: 0.01,
    maxLot: 100,
  },
  GBPUSD: {
    pipSize: 0.0001,
    contractSize: 100000,
    quoteCurrency: "USD",
    notes: "Typical forex assumption: 1 lot = 100,000 base units, pip = 0.0001",
    minLot: 0.01,
    maxLot: 100,
  },
  USDJPY: {
    pipSize: 0.01,
    contractSize: 100000,
    quoteCurrency: "JPY",
    notes: "Typical forex assumption: 1 lot = 100,000 base units, pip = 0.01",
    minLot: 0.01,
    maxLot: 100,
  },
};

function parsePositiveNumber(input, label, { allowZero = false } = {}) {
  const value = Number(input);
  if (!Number.isFinite(value) || value < 0 || (!allowZero && value === 0)) {
    throw new Error(`${label} must be a ${allowZero ? "valid" : "positive"} number.`);
  }
  return value;
}

function getCalculatorMarketSettings() {
  const symbol = (els.calcSymbolInput?.value || "XAUUSD").trim().toUpperCase();
  const preset = calculatorPresets[symbol];
  if (preset) {
    if (els.calcQuoteCurrencyInput) els.calcQuoteCurrencyInput.value = preset.quoteCurrency;
    if (symbol === "XAUUSD") {
      const selectedPipSize = Number(els.calcXauPipModeSelect?.value || state.calculatorXauPipMode || preset.pipSize);
      const xauPipSize = Number.isFinite(selectedPipSize) && selectedPipSize > 0 ? selectedPipSize : preset.pipSize;
      return {
        symbol,
        ...preset,
        pipSize: xauPipSize,
        notes: `Gold is currently using 1 pip = ${fixed(xauPipSize, 2)} price move, to match the live desk pip readout.`,
        custom: false,
      };
    }
    return { symbol, ...preset, custom: false };
  }
  const pipSize = parsePositiveNumber(els.calcPipSizeInput?.value, "Custom pip size");
  const contractSize = parsePositiveNumber(els.calcContractSizeInput?.value, "Custom contract size");
  const quoteCurrency = (els.calcQuoteCurrencyInput?.value || "USD").trim().toUpperCase() || "USD";
  return {
    symbol,
    pipSize,
    contractSize,
    quoteCurrency,
    notes: "Custom market settings entered by the user.",
    custom: true,
  };
}

function calculatorPriceDifference(openPrice, closePrice, side) {
  return side === "buy" ? closePrice - openPrice : openPrice - closePrice;
}

function renderCalculatorMode() {
  const mode = state.calculatorMode || "profit";
  const symbol = (els.calcSymbolInput?.value || "XAUUSD").trim().toUpperCase();
  const showXauPipMode = symbol === "XAUUSD";
  const fieldVisibility = {
    side: ["profit", "pips", "risk_reward"].includes(mode),
    lot: ["profit", "pip_value"].includes(mode),
    open: ["profit", "pips"].includes(mode),
    close: ["profit", "pips"].includes(mode),
    entry: ["risk_reward"].includes(mode),
    stopLoss: ["risk_reward"].includes(mode),
    takeProfit: ["risk_reward"].includes(mode),
    accountSize: ["position_size"].includes(mode),
    riskPercent: ["position_size"].includes(mode),
    stopLossPips: ["position_size", "pip_value"].includes(mode),
  };
  const toggle = (element, show) => {
    if (!element) return;
    element.classList.toggle("hidden-page", !show);
  };
  toggle(els.calcSideField, fieldVisibility.side);
  toggle(els.calcLotField, fieldVisibility.lot);
  toggle(els.calcOpenField, fieldVisibility.open);
  toggle(els.calcCloseField, fieldVisibility.close);
  toggle(els.calcEntryField, fieldVisibility.entry);
  toggle(els.calcStopLossField, fieldVisibility.stopLoss);
  toggle(els.calcTakeProfitField, fieldVisibility.takeProfit);
  toggle(els.calcAccountSizeField, fieldVisibility.accountSize);
  toggle(els.calcRiskPercentField, fieldVisibility.riskPercent);
  toggle(els.calcStopLossPipsField, fieldVisibility.stopLossPips);
  toggle(els.calcXauPipModeField, showXauPipMode);
  if (els.calcStopLossPipsLabel) {
    els.calcStopLossPipsLabel.textContent = mode === "pip_value" ? "Pip Distance" : "Stop Loss Distance (pips)";
  }
  if (els.calculatorModeMessage) {
    const messages = {
      profit: "Estimate trade profit or loss from symbol, side, lot size, and price movement.",
      pips: "Measure how many pips the move covered for the selected symbol and side.",
      pip_value: "Find the pip value for your lot size and, if you enter a pip distance, estimate the total move value too.",
      risk_reward: "Compare your risk distance against your potential reward before taking the trade.",
      position_size: "Estimate the lot size that fits your account risk and stop loss distance.",
    };
    els.calculatorModeMessage.textContent = messages[mode] || messages.profit;
  }
  els.calculatorModeStrip?.querySelectorAll("[data-calculator-mode]").forEach((button) => {
    button.classList.toggle("active", button.getAttribute("data-calculator-mode") === mode);
  });
  renderCalculatorMarketNotes();
}

function renderCalculatorMarketNotes() {
  if (!els.calculatorMarketNotes) return;
  try {
    const market = getCalculatorMarketSettings();
    els.calculatorMarketNotes.textContent = market.notes;
  } catch (error) {
    els.calculatorMarketNotes.textContent = "Enter custom pip size and contract size if your symbol does not use a built-in preset.";
  }
}

function runCalculator() {
  if (!els.calculatorResults) return;
  try {
    const mode = state.calculatorMode || "profit";
    const market = getCalculatorMarketSettings();
    const side = (els.calcSideSelect?.value || "buy").trim().toLowerCase();
    let html = "";

    if (mode === "profit") {
      const lotSize = parsePositiveNumber(els.calcLotInput?.value, "Lot size");
      const openPrice = parsePositiveNumber(els.calcOpenInput?.value, "Opening price");
      const closePrice = parsePositiveNumber(els.calcCloseInput?.value, "Closing price");
      const movement = calculatorPriceDifference(openPrice, closePrice, side);
      const pips = movement / market.pipSize;
      const pipValue = lotSize * market.contractSize * market.pipSize;
      const profit = movement * lotSize * market.contractSize;
      html = `
        <p><strong>Market:</strong> ${market.symbol}</p>
        <p><strong>Trade side:</strong> ${side.toUpperCase()}</p>
        <p><strong>Lot size:</strong> ${fixed(lotSize, 2)}</p>
        <p><strong>Price movement in your favor:</strong> ${fixed(movement, 5)}</p>
        <p><strong>Equivalent price move:</strong> ${market.quoteCurrency} ${fixed(Math.abs(movement), 2)}</p>
        <p><strong>Pip movement:</strong> ${fixed(pips, 2)} pips</p>
        <p><strong>Estimated value per pip:</strong> ${market.quoteCurrency} ${fixed(pipValue, 2)}</p>
        <p><strong>Estimated profit/loss:</strong> ${market.quoteCurrency} ${fixed(profit, 2)}</p>
      `;
    } else if (mode === "pips") {
      const openPrice = parsePositiveNumber(els.calcOpenInput?.value, "Opening price");
      const closePrice = parsePositiveNumber(els.calcCloseInput?.value, "Closing price");
      const pips = calculatorPriceDifference(openPrice, closePrice, side) / market.pipSize;
      html = `
        <p><strong>Market:</strong> ${market.symbol}</p>
        <p><strong>Configured pip size:</strong> ${market.pipSize}</p>
        <p><strong>Pip movement:</strong> ${fixed(pips, 2)} pips</p>
      `;
    } else if (mode === "pip_value") {
      const lotSize = parsePositiveNumber(els.calcLotInput?.value, "Lot size");
      const pipValue = lotSize * market.contractSize * market.pipSize;
      const pipDistance = parsePositiveNumber(els.calcStopLossPipsInput?.value, "Pip distance", { allowZero: true });
      const totalValue = pipValue * pipDistance;
      const priceMove = pipDistance * market.pipSize;
      html = `
        <p><strong>Market:</strong> ${market.symbol}</p>
        <p><strong>Lot size:</strong> ${fixed(lotSize, 2)}</p>
        <p><strong>Configured pip size:</strong> ${fixed(market.pipSize, 2)}</p>
        <p><strong>Pip value:</strong> ${market.quoteCurrency} ${fixed(pipValue, 2)} per pip</p>
        <p><strong>Pip distance:</strong> ${fixed(pipDistance, 2)} pips</p>
        <p><strong>Equivalent price move:</strong> ${market.quoteCurrency} ${fixed(priceMove, 2)}</p>
        <p><strong>Total value for that move:</strong> ${market.quoteCurrency} ${fixed(totalValue, 2)}</p>
      `;
    } else if (mode === "risk_reward") {
      const entry = parsePositiveNumber(els.calcEntryInput?.value, "Entry price");
      const stopLoss = parsePositiveNumber(els.calcStopLossInput?.value, "Stop loss price");
      const takeProfit = parsePositiveNumber(els.calcTakeProfitInput?.value, "Take profit price");
      const risk = side === "buy" ? entry - stopLoss : stopLoss - entry;
      const reward = side === "buy" ? takeProfit - entry : entry - takeProfit;
      if (risk <= 0 || reward <= 0) throw new Error("Invalid stop loss / take profit placement for the selected trade side.");
      html = `
        <p><strong>Risk distance:</strong> ${fixed(risk, 5)}</p>
        <p><strong>Reward distance:</strong> ${fixed(reward, 5)}</p>
        <p><strong>Risk-to-reward ratio:</strong> 1:${fixed(reward / risk, 2)}</p>
      `;
    } else if (mode === "position_size") {
      const accountSize = parsePositiveNumber(els.calcAccountSizeInput?.value, "Account size");
      const riskPercent = parsePositiveNumber(els.calcRiskPercentInput?.value, "Risk percent");
      const stopLossPips = parsePositiveNumber(els.calcStopLossPipsInput?.value, "Stop loss distance in pips");
      const riskAmount = accountSize * (riskPercent / 100);
      const oneLotPipValue = 1 * market.contractSize * market.pipSize;
      const lotSize = riskAmount / (stopLossPips * oneLotPipValue);
      html = `
        <p><strong>Risk amount:</strong> ${market.quoteCurrency} ${fixed(riskAmount, 2)}</p>
        <p><strong>Estimated lot size:</strong> ${fixed(lotSize, 4)}</p>
        <p><strong>Guide:</strong> Double-check this against your broker's contract specifications before placing the trade.</p>
      `;
    }

    els.calculatorResults.innerHTML = html;
    renderCalculatorMarketNotes();
  } catch (error) {
    els.calculatorResults.innerHTML = `<p class="negative">${error.message || "Could not complete the calculation."}</p>`;
  }
}

function getRiskPlannerMarketSettings() {
  const symbol = (els.riskSymbolInput?.value || "XAUUSD").trim().toUpperCase();
  return {
    symbol,
    ...(calculatorPresets[symbol] || calculatorPresets.XAUUSD),
  };
}

function renderFakeoutLessonStepper() {
  if (!els.fakeoutLessonStepper) return;
  els.fakeoutLessonStepper.innerHTML = FAKEOUT_LESSON_STEPS.map((step, index) => `
    <button class="lesson-step-button ${index === state.fakeoutLessonStep ? "active" : ""}" type="button" data-fakeout-step="${index}">
      <strong>Step ${index + 1}</strong>
      <div>${step.title}</div>
      <small>${step.timeframe} focus</small>
    </button>
  `).join("");
  els.fakeoutLessonStepper.querySelectorAll("[data-fakeout-step]").forEach((button) => {
    button.addEventListener("click", () => {
      state.fakeoutLessonStep = Number(button.getAttribute("data-fakeout-step") || 0);
      renderFakeoutLesson();
    });
  });
}

function drawFakeoutLessonLiveChart(payload) {
  const canvas = els.fakeoutLessonLiveCanvas;
  const ctx = canvas?.getContext("2d");
  if (!canvas || !ctx) return;
  const width = Math.max(1280, canvas.clientWidth || canvas.width);
  const height = 700;
  canvas.width = width;
  canvas.height = height;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#c8c8c8";
  ctx.fillRect(0, 0, width, height);

  const candles = Array.isArray(payload?.candles) ? payload.candles.slice(-90) : [];
  if (!candles.length) {
    ctx.fillStyle = "#35383d";
    ctx.font = "22px Aptos";
    ctx.fillText(payload?.connection_error || "Could not load live XAU candles.", 32, height / 2);
    return;
  }

  const padding = { top: 28, right: 110, bottom: 34, left: 28 };
  const chartRight = width - padding.right;
  const chartBottom = height - padding.bottom;
  const plotWidth = chartRight - padding.left;
  const plotHeight = chartBottom - padding.top;
  const highs = candles.map((item) => Number(item.high));
  const lows = candles.map((item) => Number(item.low));
  const closes = candles.map((item) => Number(item.close));
  const maxPrice = Math.max(...highs);
  const minPrice = Math.min(...lows);
  const spread = Math.max(maxPrice - minPrice, 0.5);
  const paddedMax = maxPrice + spread * 0.08;
  const paddedMin = minPrice - spread * 0.08;
  const range = Math.max(paddedMax - paddedMin, 0.5);
  const priceToY = (price) => padding.top + ((paddedMax - Number(price)) / range) * plotHeight;
  const step = plotWidth / candles.length;
  const candleWidth = Math.max(6, Math.min(16, step * 0.72));

  ctx.strokeStyle = "rgba(0,0,0,0.08)";
  ctx.lineWidth = 1;
  for (let row = 0; row <= 6; row += 1) {
    const y = padding.top + (plotHeight / 6) * row;
    ctx.beginPath();
    ctx.moveTo(padding.left, y);
    ctx.lineTo(chartRight, y);
    ctx.stroke();
  }
  for (let col = 0; col <= 8; col += 1) {
    const x = padding.left + (plotWidth / 8) * col;
    ctx.beginPath();
    ctx.moveTo(x, padding.top);
    ctx.lineTo(x, chartBottom);
    ctx.stroke();
  }

  candles.forEach((candle, index) => {
    const x = padding.left + index * step + step / 2;
    const open = Number(candle.open);
    const close = Number(candle.close);
    const high = Number(candle.high);
    const low = Number(candle.low);
    const bullish = close >= open;
    ctx.strokeStyle = "#111111";
    ctx.beginPath();
    ctx.moveTo(x, priceToY(high));
    ctx.lineTo(x, priceToY(low));
    ctx.stroke();
    ctx.fillStyle = bullish ? "#49a74b" : "#111111";
    ctx.fillRect(
      x - candleWidth / 2,
      Math.min(priceToY(open), priceToY(close)),
      candleWidth,
      Math.max(2, Math.abs(priceToY(close) - priceToY(open))),
    );
  });

  const currentPrice = Number(payload?.current_price || closes.at(-1) || 0);
  const currentY = priceToY(currentPrice);
  ctx.setLineDash([3, 6]);
  ctx.strokeStyle = "rgba(69, 167, 73, 0.82)";
  ctx.beginPath();
  ctx.moveTo(padding.left, currentY);
  ctx.lineTo(chartRight, currentY);
  ctx.stroke();
  ctx.setLineDash([]);

  ctx.fillStyle = "#33383d";
  ctx.font = "12px Cascadia Mono";
  Array.from({ length: 9 }, (_, index) => paddedMax - ((range / 8) * index)).forEach((price) => {
    ctx.fillText(fixed(price), chartRight + 18, priceToY(price) + 4);
  });

  ctx.fillStyle = "#49a74b";
  ctx.fillRect(chartRight + 10, currentY - 12, 90, 24);
  ctx.fillStyle = "#ffffff";
  ctx.font = "bold 12px Aptos";
  ctx.fillText(fixed(currentPrice), chartRight + 18, currentY + 4);

  ctx.fillStyle = "rgba(79, 83, 88, 0.18)";
  ctx.font = "600 78px Aptos";
  ctx.textAlign = "center";
  ctx.fillText(payload?.symbol || "XAUUSDm", width / 2, height / 2 + 12);
  ctx.textAlign = "left";
}

async function loadFakeoutLessonLiveChart() {
  const step = FAKEOUT_LESSON_STEPS[state.fakeoutLessonStep] || FAKEOUT_LESSON_STEPS[0];
  try {
    const payload = await fetchJson(`/api/chart-data?symbol=${encodeURIComponent("xauusd")}&timeframe=${encodeURIComponent(step.timeframe)}`);
    state.fakeoutLessonLivePayload = payload;
    drawFakeoutLessonLiveChart(payload);
  } catch (error) {
    drawFakeoutLessonLiveChart({ connection_error: error.message || "Could not load XAU chart.", candles: [], symbol: "XAUUSDm", current_price: 0 });
  }
}

function renderFakeoutLesson() {
  const step = FAKEOUT_LESSON_STEPS[state.fakeoutLessonStep] || FAKEOUT_LESSON_STEPS[0];
  if (els.fakeoutLessonStepKicker) els.fakeoutLessonStepKicker.textContent = `Step ${state.fakeoutLessonStep + 1}`;
  if (els.fakeoutLessonStepTitle) els.fakeoutLessonStepTitle.textContent = step.title;
  if (els.fakeoutLessonBody) {
    els.fakeoutLessonBody.innerHTML = step.body.map((paragraph) => `<p>${paragraph}</p>`).join("");
  }
  if (els.fakeoutLessonChecklist) {
    els.fakeoutLessonChecklist.innerHTML = `<ul>${step.checklist.map((item) => `<li>${item}</li>`).join("")}</ul>`;
  }
  if (els.fakeoutLessonIllustration) {
    els.fakeoutLessonIllustration.innerHTML = step.illustration;
  }
  if (els.fakeoutLessonPrevButton) els.fakeoutLessonPrevButton.disabled = state.fakeoutLessonStep === 0;
  if (els.fakeoutLessonNextButton) els.fakeoutLessonNextButton.textContent = state.fakeoutLessonStep === FAKEOUT_LESSON_STEPS.length - 1 ? "Restart Lesson" : "Next Step";
  els.fakeoutLessonViewToggle?.querySelectorAll("[data-fakeout-view]").forEach((button) => {
    button.classList.toggle("active", button.getAttribute("data-fakeout-view") === state.fakeoutLessonView);
  });
  els.fakeoutIllustrationPanel?.classList.toggle("hidden-page", state.fakeoutLessonView !== "illustration");
  els.fakeoutLivePanel?.classList.toggle("hidden-page", state.fakeoutLessonView !== "live");
  renderFakeoutLessonStepper();
  if (state.fakeoutLessonView === "live") {
    loadFakeoutLessonLiveChart().catch(() => {});
  }
}

function openFakeoutLessonModal() {
  if (!els.fakeoutLessonModal) return;
  els.fakeoutLessonModal.classList.remove("hidden");
  els.fakeoutLessonModal.setAttribute("aria-hidden", "false");
  renderFakeoutLesson();
}

function closeFakeoutLessonModal() {
  if (!els.fakeoutLessonModal) return;
  els.fakeoutLessonModal.classList.add("hidden");
  els.fakeoutLessonModal.setAttribute("aria-hidden", "true");
}

function getRiskPlannerData() {
  const market = getRiskPlannerMarketSettings();
  const side = (els.riskSideSelect?.value || "buy").trim().toLowerCase();
  const lotSize = parsePositiveNumber(els.riskLotInput?.value, "Lot size");
  const entry = parsePositiveNumber(els.riskEntryInput?.value, "Entry price");
  const stopLoss = parsePositiveNumber(els.riskStopInput?.value, "Stop loss");
  const takeProfit = parsePositiveNumber(els.riskTargetInput?.value, "Take profit");
  const balance = parsePositiveNumber(els.riskBalanceInput?.value, "Account balance");
  const riskPercent = parsePositiveNumber(els.riskPercentInput?.value, "Risk percent");
  const timeframe = (els.riskTimeframeSelect?.value || "M5").trim().toUpperCase();
  const riskDistance = side === "buy" ? entry - stopLoss : stopLoss - entry;
  const rewardDistance = side === "buy" ? takeProfit - entry : entry - takeProfit;
  if (riskDistance <= 0) throw new Error("Stop loss placement is invalid for the selected side.");
  if (rewardDistance <= 0) throw new Error("Take profit placement is invalid for the selected side.");
  const pipDistance = riskDistance / market.pipSize;
  const oneLotPipValue = market.contractSize * market.pipSize;
  const pipValue = lotSize * oneLotPipValue;
  const riskAmount = riskDistance * lotSize * market.contractSize;
  const rewardAmount = rewardDistance * lotSize * market.contractSize;
  const riskRatio = rewardDistance / riskDistance;
  const accountRiskPercent = (riskAmount / balance) * 100;
  const targetRiskAmount = balance * (riskPercent / 100);
  const projectedBalanceLoss = balance - riskAmount;
  const projectedBalanceProfit = balance + rewardAmount;
  const suggestedLot = targetRiskAmount / (pipDistance * oneLotPipValue);
  const conservativeLot = (balance * 0.005) / (pipDistance * oneLotPipValue);
  const aggressiveLot = (balance * 0.02) / (pipDistance * oneLotPipValue);
  const minLot = Number(market.minLot || 0.01);
  const maxLot = Number(market.maxLot || 100);
  return {
    market,
    side,
    lotSize,
    entry,
    stopLoss,
    takeProfit,
    balance,
    riskPercent,
    timeframe,
    riskDistance,
    rewardDistance,
    pipDistance,
    pipValue,
    riskAmount,
    rewardAmount,
    riskRatio,
    accountRiskPercent,
    targetRiskAmount,
    projectedBalanceLoss,
    projectedBalanceProfit,
    suggestedLot,
    conservativeLot,
    aggressiveLot,
    minLot,
    maxLot,
  };
}

function getRiskChartPrecision(symbol) {
  return symbol === "XAUUSD" || symbol === "BTCUSD" ? 2 : 5;
}

function getRiskChartHandleAt(canvasX, canvasY) {
  const handles = state.riskChartInteraction?.geometry?.handles || [];
  if (!handles.length) return null;
  const directHit = handles.find((handle) => (
    canvasX >= handle.x1
    && canvasX <= handle.x2
    && canvasY >= handle.y1
    && canvasY <= handle.y2
  ));
  if (directHit) return directHit;
  const nearest = handles
    .map((handle) => ({ handle, distance: Math.abs(canvasY - handle.y) }))
    .sort((left, right) => left.distance - right.distance)[0];
  return nearest && nearest.distance <= 14 ? nearest.handle : null;
}

function riskPlannerYToPrice(y, geometry) {
  if (!geometry) return 0;
  const clampedY = clamp(y, geometry.padding.top, geometry.padding.top + geometry.plotHeight);
  return geometry.maxPrice - ((clampedY - geometry.padding.top) / geometry.plotHeight) * geometry.spread;
}

function updateRiskPlannerHandlePrice(handleKey, price) {
  const market = getRiskPlannerMarketSettings();
  const precision = getRiskChartPrecision(market.symbol);
  const rounded = Number(price).toFixed(precision);
  if (handleKey === "entry" && els.riskEntryInput) {
    els.riskEntryInput.value = rounded;
  }
  if (handleKey === "stopLoss" && els.riskStopInput) {
    els.riskStopInput.value = rounded;
  }
  if (handleKey === "takeProfit" && els.riskTargetInput) {
    els.riskTargetInput.value = rounded;
  }
}

function renderRiskChartMessage(plan, override) {
  if (!els.riskChartMessage) return;
  if (override) {
    els.riskChartMessage.textContent = override.text;
    els.riskChartMessage.className = `analysis-banner ${override.tone || "neutral"}`;
    return;
  }
  els.riskChartMessage.textContent = `${plan.side.toUpperCase()} plan drawn on ${plan.market.symbol} ${plan.timeframe}. Hover a level to highlight it, then drag to refine Entry, SL, or TP.`;
  els.riskChartMessage.className = `analysis-banner ${plan.side === "buy" ? "bullish" : "bearish"}`;
}

function renderRiskGuide() {
  if (els.riskGuideConcepts) {
    els.riskGuideConcepts.innerHTML = [
      ["Risk / Reward", "A 1:3 setup means you risk 1 unit to potentially make 3 units. Higher RR setups can stay profitable even with a modest win rate."],
      ["Position Size", "Lot size controls how much money each point or pip movement is worth. Larger lots increase both potential profit and potential loss."],
      ["Stop Loss", "Your stop loss defines the price where the trade idea is considered invalid. It should come from structure first, not just money."],
      ["Leverage", "Leverage lets you control a larger position with less margin. It does not reduce risk by itself. If lot size is too large, leverage can amplify losses very quickly."],
      ["Margin", "Margin is the capital locked by your broker to keep the position open. Free margin is what remains available for new trades or drawdown."],
      ["Drawdown", "Drawdown is the fall from your starting equity or recent peak. Strong risk management is really about controlling drawdown over time."],
    ].map(([title, text]) => `
      <article class="analysis-item neutral">
        <strong>${title}</strong>
        <p>${text}</p>
      </article>
    `).join("");
  }
  if (els.riskGuideAccount) {
    const account = state.accountSnapshot || {};
    const leverage = Number(account.leverage || 0);
    els.riskGuideAccount.innerHTML = `
      <article class="analysis-item ${leverage > 0 ? "support" : "neutral"}">
        <strong>Live Account Context</strong>
        <p>Balance: ${money(account.balance || 0)} | Equity: ${money(account.equity || 0)} | Free Margin: ${money(account.free_margin || 0)} | Leverage: ${leverage ? `1:${leverage}` : "Unavailable"}</p>
      </article>
      <article class="analysis-item neutral">
        <strong>Practical Leverage View</strong>
        <p>Think of leverage as borrowing capacity, not as permission to size up. The real risk still comes from your stop distance and the lot size you choose.</p>
      </article>
      <article class="analysis-item neutral">
        <strong>Planning Hint</strong>
        <p>A cleaner process is: define invalidation, set acceptable account risk, then calculate the lot size that fits that risk budget.</p>
      </article>
    `;
  }
}

function renderRiskPlannerResult(data) {
  const tradableSuggestedLot = Math.min(Math.max(data.suggestedLot, data.minLot), data.maxLot);
  if (els.riskPlannerCards) {
    const cards = [
      ["Amount At Risk", `${data.market.quoteCurrency} ${fixed(data.riskAmount, 2)}`, data.accountRiskPercent <= data.riskPercent ? "positive" : "negative"],
      ["Potential Reward", `${data.market.quoteCurrency} ${fixed(data.rewardAmount, 2)}`, data.rewardAmount >= data.riskAmount ? "positive" : "neutral"],
      ["Risk / Reward", `1:${fixed(data.riskRatio, 2)}`, data.riskRatio >= 2 ? "positive" : data.riskRatio >= 1.2 ? "neutral" : "negative"],
      ["Suggested Lot", data.suggestedLot < data.minLot ? `< ${formatLotSuggestion(data.minLot)}` : formatLotSuggestion(data.suggestedLot), Math.abs(data.lotSize - tradableSuggestedLot) < 0.005 ? "positive" : "neutral"],
      ["Balance If SL Hits", `${data.market.quoteCurrency} ${fixed(data.projectedBalanceLoss, 2)}`, "negative"],
      ["Balance If TP Hits", `${data.market.quoteCurrency} ${fixed(data.projectedBalanceProfit, 2)}`, "positive"],
    ];
    els.riskPlannerCards.innerHTML = cards.map(([title, value, tone]) => `
      <article class="panel stat-panel insight-card ${tone}">
        <span>${title}</span>
        <strong>${value}</strong>
      </article>
    `).join("");
  }

  let lotAdvice = "Your current lot size is close to the suggested size for this setup.";
  const suggestedLotText = formatLotSuggestion(data.suggestedLot);
  const tradableLotText = formatLotSuggestion(tradableSuggestedLot);
  if (data.lotSize > data.suggestedLot * 1.1) {
    if (data.suggestedLot < 0.01) {
      lotAdvice = `Your lot looks heavy for this balance and stop distance. The model suggests less than ${formatLotSuggestion(data.minLot)} lots (${suggestedLotText}), but your broker minimum for ${data.market.symbol} is ${formatLotSuggestion(data.minLot)}. This usually means the stop is too wide or the account risk is too small for this setup.`;
    } else {
      lotAdvice = `Your lot looks heavy for this balance and stop distance. Reducing toward ${suggestedLotText} lots would align better with the selected risk budget.`;
    }
  } else if (data.lotSize < data.suggestedLot * 0.9) {
    lotAdvice = `You are risking less than your selected budget. If the setup is clean, you could size up toward ${suggestedLotText} lots.`;
  }
  let setupAdvice = "The setup looks balanced.";
  if (data.riskRatio < 1.2) {
    setupAdvice = "The reward looks thin compared with the risk. This may not be worth taking unless your win rate on this pattern is exceptional.";
  } else if (data.riskRatio >= 3) {
    setupAdvice = "This is a strong RR profile on paper. Make sure the stop loss still respects structure rather than being artificially tight.";
  }

  if (els.riskPlannerResults) {
    els.riskPlannerResults.innerHTML = `
      <p><strong>Symbol:</strong> ${data.market.symbol}</p>
      <p><strong>Side:</strong> ${data.side.toUpperCase()}</p>
      <p><strong>Entry / SL / TP:</strong> ${fixed(data.entry)} / ${fixed(data.stopLoss)} / ${fixed(data.takeProfit)}</p>
      <p><strong>Stop Distance:</strong> ${fixed(data.riskDistance, 5)} (${fixed(data.pipDistance, 2)} pips)</p>
      <p><strong>Potential Profit / Loss:</strong> ${data.market.quoteCurrency} ${fixed(data.rewardAmount, 2)} / ${data.market.quoteCurrency} ${fixed(data.riskAmount, 2)}</p>
      <p><strong>Projected Balance After Loss:</strong> ${data.market.quoteCurrency} ${fixed(data.projectedBalanceLoss, 2)}</p>
      <p><strong>Projected Balance After Profit:</strong> ${data.market.quoteCurrency} ${fixed(data.projectedBalanceProfit, 2)}</p>
      <p><strong>Risk On Balance:</strong> ${fixed(data.accountRiskPercent, 2)}% of account balance</p>
      <p><strong>Pip Value At Current Lot:</strong> ${data.market.quoteCurrency} ${fixed(data.pipValue, 2)} per pip</p>
      <p><strong>Broker Lot Range:</strong> ${formatLotSuggestion(data.minLot)} to ${formatLotSuggestion(data.maxLot)}+</p>
      <p><strong>Conservative / Standard / Aggressive Lot Ideas:</strong> ${formatLotSuggestion(data.conservativeLot)} / ${data.suggestedLot < data.minLot ? `< ${formatLotSuggestion(data.minLot)} (raw ${suggestedLotText})` : formatLotSuggestion(data.suggestedLot)} / ${formatLotSuggestion(data.aggressiveLot)}</p>
      <p><strong>Nearest Tradable Suggestion:</strong> ${tradableLotText}</p>
      <p><strong>Lot Size Guidance:</strong> ${lotAdvice}</p>
      <p><strong>Setup Read:</strong> ${setupAdvice}</p>
    `;
  }
  if (els.riskPlannerSuggestedRisk) {
    els.riskPlannerSuggestedRisk.textContent = `${fixed(data.riskPercent, 2)}%`;
  }
  if (els.riskPlannerMessage) {
    els.riskPlannerMessage.textContent = lotAdvice;
    els.riskPlannerMessage.className = `analysis-banner ${data.accountRiskPercent <= data.riskPercent && data.riskRatio >= 1.2 ? "bullish" : "neutral"}`;
  }
  if (els.riskPlannerMarketNotes) {
    els.riskPlannerMarketNotes.textContent = data.market.notes;
  }
}

function drawRiskPlannerChartLegacy(payload, plan) {
  if (!riskPlannerCtx || !els.riskPlannerCanvas) return;
  const canvas = els.riskPlannerCanvas;
  const width = Math.max(320, canvas.clientWidth || canvas.width);
  const height = Math.max(320, Math.round(width * 0.42));
  canvas.width = width;
  canvas.height = height;
  riskPlannerCtx.clearRect(0, 0, width, height);
  riskPlannerCtx.fillStyle = getComputedStyle(document.body).getPropertyValue("--panel-soft");
  riskPlannerCtx.fillRect(0, 0, width, height);
  const candles = payload?.candles || [];
  if (!candles.length) {
    riskPlannerCtx.fillStyle = getComputedStyle(document.body).getPropertyValue("--muted");
    riskPlannerCtx.font = "18px Aptos";
    riskPlannerCtx.fillText(payload?.connection_error || "Waiting for planning chart data...", 24, height / 2);
    return;
  }
  const padding = { top: 24, right: 118, bottom: 30, left: 56 };
  const highs = candles.map((candle) => Number(candle.high));
  const lows = candles.map((candle) => Number(candle.low));
  const maxPrice = Math.max(...highs, plan.takeProfit, plan.entry, plan.stopLoss);
  const minPrice = Math.min(...lows, plan.takeProfit, plan.entry, plan.stopLoss);
  const spread = Math.max(maxPrice - minPrice, 0.01);
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const candleWidth = Math.max(4, plotWidth / candles.length * 0.68);
  const priceToY = (price) => padding.top + (maxPrice - Number(price)) / spread * plotHeight;
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
    riskPlannerCtx.strokeStyle = color;
    riskPlannerCtx.beginPath();
    riskPlannerCtx.moveTo(centerX, priceToY(high));
    riskPlannerCtx.lineTo(centerX, priceToY(low));
    riskPlannerCtx.stroke();
    riskPlannerCtx.fillStyle = color;
    riskPlannerCtx.fillRect(centerX - candleWidth / 2, Math.min(priceToY(open), priceToY(close)), candleWidth, Math.max(2, Math.abs(priceToY(close) - priceToY(open))));
  });
  const entryY = priceToY(plan.entry);
  const stopY = priceToY(plan.stopLoss);
  const targetY = priceToY(plan.takeProfit);
  const rewardTop = Math.min(entryY, targetY);
  const rewardHeight = Math.abs(targetY - entryY);
  const riskTop = Math.min(entryY, stopY);
  const riskHeight = Math.abs(stopY - entryY);
  riskPlannerCtx.fillStyle = "rgba(75, 240, 179, 0.12)";
  riskPlannerCtx.fillRect(padding.left, rewardTop, plotWidth, Math.max(8, rewardHeight));
  riskPlannerCtx.fillStyle = "rgba(255, 107, 122, 0.12)";
  riskPlannerCtx.fillRect(padding.left, riskTop, plotWidth, Math.max(8, riskHeight));
  const drawLevel = (price, color, label) => {
    const y = priceToY(price);
    riskPlannerCtx.strokeStyle = color;
    riskPlannerCtx.setLineDash([8, 6]);
    riskPlannerCtx.beginPath();
    riskPlannerCtx.moveTo(padding.left, y);
    riskPlannerCtx.lineTo(width - padding.right + 8, y);
    riskPlannerCtx.stroke();
    riskPlannerCtx.setLineDash([]);
    riskPlannerCtx.fillStyle = color;
    riskPlannerCtx.fillRect(padding.left + 8, y - 12, 120, 22);
    riskPlannerCtx.fillStyle = "#04131c";
    riskPlannerCtx.font = "12px Aptos";
    riskPlannerCtx.fillText(label, padding.left + 14, y + 4);
    riskPlannerCtx.fillStyle = getComputedStyle(document.body).getPropertyValue("--text");
    riskPlannerCtx.font = "12px Cascadia Mono";
    riskPlannerCtx.fillText(fixed(price), width - padding.right + 18, y + 4);
  };
  drawLevel(plan.entry, "rgba(105, 211, 255, 0.95)", `${plan.side.toUpperCase()} ENTRY`);
  drawLevel(plan.stopLoss, "rgba(255, 107, 122, 0.95)", "STOP LOSS");
  drawLevel(plan.takeProfit, "rgba(75, 240, 179, 0.95)", "TAKE PROFIT");
  riskPlannerCtx.fillStyle = getComputedStyle(document.body).getPropertyValue("--muted");
  riskPlannerCtx.font = "13px Cascadia Mono";
  riskPlannerCtx.fillText(`${payload?.symbol || plan.market.symbol} ${plan.timeframe} · ${plan.side.toUpperCase()} PLAN`, padding.left, 18);
  if (els.riskChartMessage) {
    els.riskChartMessage.textContent = `${plan.side.toUpperCase()} plan drawn on ${plan.market.symbol} ${plan.timeframe}. Green is reward, red is risk.`;
    els.riskChartMessage.className = `analysis-banner ${plan.side === "buy" ? "bullish" : "bearish"}`;
  }
}

function drawRiskPlannerChart(payload, plan) {
  if (!riskPlannerCtx || !els.riskPlannerCanvas) return;
  const canvas = els.riskPlannerCanvas;
  const width = Math.max(320, canvas.clientWidth || canvas.width);
  const height = Math.max(320, Math.round(width * 0.42));
  canvas.width = width;
  canvas.height = height;
  riskPlannerCtx.clearRect(0, 0, width, height);
  riskPlannerCtx.fillStyle = getComputedStyle(document.body).getPropertyValue("--panel-soft");
  riskPlannerCtx.fillRect(0, 0, width, height);
  const candles = payload?.candles || [];
  if (!candles.length) {
    riskPlannerCtx.fillStyle = getComputedStyle(document.body).getPropertyValue("--muted");
    riskPlannerCtx.font = "18px Aptos";
    riskPlannerCtx.fillText(payload?.connection_error || "Waiting for planning chart data...", 24, height / 2);
    state.riskChartInteraction.geometry = null;
    canvas.style.cursor = "default";
    return;
  }
  const padding = { top: 24, right: 118, bottom: 30, left: 56 };
  const highs = candles.map((candle) => Number(candle.high));
  const lows = candles.map((candle) => Number(candle.low));
  const maxPrice = Math.max(...highs, plan.takeProfit, plan.entry, plan.stopLoss);
  const minPrice = Math.min(...lows, plan.takeProfit, plan.entry, plan.stopLoss);
  const spread = Math.max(maxPrice - minPrice, 0.01);
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const candleWidth = Math.max(4, plotWidth / candles.length * 0.68);
  const priceToY = (price) => padding.top + (maxPrice - Number(price)) / spread * plotHeight;
  const currentPrice = Number(payload?.current_price || candles[candles.length - 1]?.close || plan.entry || 0);
  const currentPriceY = priceToY(currentPrice);
  const hoveredHandle = state.riskChartInteraction.hoveredHandle;
  const draggingHandle = state.riskChartInteraction.draggingHandle;
  const activeHandle = draggingHandle || hoveredHandle;
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
    riskPlannerCtx.strokeStyle = color;
    riskPlannerCtx.lineWidth = 1;
    riskPlannerCtx.beginPath();
    riskPlannerCtx.moveTo(centerX, priceToY(high));
    riskPlannerCtx.lineTo(centerX, priceToY(low));
    riskPlannerCtx.stroke();
    riskPlannerCtx.fillStyle = color;
    riskPlannerCtx.fillRect(centerX - candleWidth / 2, Math.min(priceToY(open), priceToY(close)), candleWidth, Math.max(2, Math.abs(priceToY(close) - priceToY(open))));
  });
  const entryY = priceToY(plan.entry);
  const stopY = priceToY(plan.stopLoss);
  const targetY = priceToY(plan.takeProfit);
  const rewardTop = Math.min(entryY, targetY);
  const rewardHeight = Math.abs(targetY - entryY);
  const riskTop = Math.min(entryY, stopY);
  const riskHeight = Math.abs(stopY - entryY);
  riskPlannerCtx.fillStyle = "rgba(75, 240, 179, 0.12)";
  riskPlannerCtx.fillRect(padding.left, rewardTop, plotWidth, Math.max(8, rewardHeight));
  riskPlannerCtx.fillStyle = "rgba(255, 107, 122, 0.12)";
  riskPlannerCtx.fillRect(padding.left, riskTop, plotWidth, Math.max(8, riskHeight));
  const handles = [];
  const drawLevel = (key, price, color, label) => {
    const y = priceToY(price);
    const isActive = activeHandle === key;
    riskPlannerCtx.strokeStyle = color;
    riskPlannerCtx.lineWidth = isActive ? 3 : 2;
    riskPlannerCtx.setLineDash([8, 6]);
    riskPlannerCtx.beginPath();
    riskPlannerCtx.moveTo(padding.left, y);
    riskPlannerCtx.lineTo(width - padding.right + 8, y);
    riskPlannerCtx.stroke();
    riskPlannerCtx.setLineDash([]);
    if (isActive) {
      riskPlannerCtx.save();
      riskPlannerCtx.shadowColor = color;
      riskPlannerCtx.shadowBlur = 16;
      riskPlannerCtx.fillStyle = color;
      riskPlannerCtx.fillRect(padding.left + 10, y - 15, 128, 28);
      riskPlannerCtx.restore();
    } else {
      riskPlannerCtx.fillStyle = color;
      riskPlannerCtx.fillRect(padding.left + 8, y - 12, 120, 22);
    }
    riskPlannerCtx.fillStyle = "#04131c";
    riskPlannerCtx.font = "12px Aptos";
    riskPlannerCtx.fillText(label, padding.left + 14, y + 4);
    riskPlannerCtx.fillStyle = getComputedStyle(document.body).getPropertyValue("--text");
    riskPlannerCtx.font = "12px Cascadia Mono";
    riskPlannerCtx.fillText(fixed(price), width - padding.right + 18, y + 4);
    riskPlannerCtx.fillStyle = color;
    riskPlannerCtx.beginPath();
    riskPlannerCtx.arc(width - padding.right + 2, y, isActive ? 7 : 5, 0, Math.PI * 2);
    riskPlannerCtx.fill();
    handles.push({
      key,
      y,
      x1: padding.left,
      x2: width - padding.right + 28,
      y1: y - 12,
      y2: y + 12,
    });
  };
  drawLevel("entry", plan.entry, "rgba(105, 211, 255, 0.95)", `${plan.side.toUpperCase()} ENTRY`);
  drawLevel("stopLoss", plan.stopLoss, "rgba(255, 107, 122, 0.95)", "STOP LOSS");
  drawLevel("takeProfit", plan.takeProfit, "rgba(75, 240, 179, 0.95)", "TAKE PROFIT");
  riskPlannerCtx.strokeStyle = "rgba(255, 255, 255, 0.28)";
  riskPlannerCtx.lineWidth = 1;
  riskPlannerCtx.setLineDash([4, 6]);
  riskPlannerCtx.beginPath();
  riskPlannerCtx.moveTo(padding.left, currentPriceY);
  riskPlannerCtx.lineTo(width - padding.right + 8, currentPriceY);
  riskPlannerCtx.stroke();
  riskPlannerCtx.setLineDash([]);
  riskPlannerCtx.fillStyle = "rgba(255, 255, 255, 0.92)";
  riskPlannerCtx.fillRect(width - padding.right + 10, currentPriceY - 12, 92, 22);
  riskPlannerCtx.fillStyle = "#04131c";
  riskPlannerCtx.font = "12px Cascadia Mono";
  riskPlannerCtx.fillText(`NOW ${fixed(currentPrice)}`, width - padding.right + 16, currentPriceY + 4);
  if (draggingHandle && Number.isFinite(state.riskChartInteraction.dragPrice)) {
    const dragPriceY = priceToY(state.riskChartInteraction.dragPrice);
    riskPlannerCtx.fillStyle = "rgba(255, 255, 255, 0.92)";
    riskPlannerCtx.fillRect(padding.left + 146, dragPriceY - 14, 136, 28);
    riskPlannerCtx.fillStyle = "#04131c";
    riskPlannerCtx.font = "12px Aptos";
    riskPlannerCtx.fillText(`Dragging ${draggingHandle}`, padding.left + 154, dragPriceY + 3);
    riskPlannerCtx.font = "12px Cascadia Mono";
    riskPlannerCtx.fillText(fixed(state.riskChartInteraction.dragPrice), padding.left + 154, dragPriceY + 17);
  }
  riskPlannerCtx.fillStyle = getComputedStyle(document.body).getPropertyValue("--muted");
  riskPlannerCtx.font = "13px Cascadia Mono";
  riskPlannerCtx.fillText(`${payload?.symbol || plan.market.symbol} ${plan.timeframe} - ${plan.side.toUpperCase()} PLAN`, padding.left, 18);
  state.riskChartInteraction.geometry = {
    padding,
    plotHeight,
    plotWidth,
    maxPrice,
    minPrice,
    spread,
    width,
    height,
    currentPrice,
    handles,
    priceToY,
  };
  canvas.style.cursor = activeHandle ? (draggingHandle ? "grabbing" : "grab") : "crosshair";
  renderRiskChartMessage(plan);
}

async function refreshRiskPlannerChart() {
  if (!els.riskSymbolInput || !els.riskTimeframeSelect) return;
  try {
    const plan = getRiskPlannerData();
    const payload = await fetchJson(`/api/chart-data?symbol=${encodeURIComponent(plan.market.symbol)}&timeframe=${encodeURIComponent(plan.timeframe)}`);
    state.riskChart = payload;
    drawRiskPlannerChart(payload, plan);
  } catch (error) {
    const fallbackPlan = {
      market: getRiskPlannerMarketSettings(),
      side: (els.riskSideSelect?.value || "buy").trim().toLowerCase(),
      entry: Number(els.riskEntryInput?.value || 0),
      stopLoss: Number(els.riskStopInput?.value || 0),
      takeProfit: Number(els.riskTargetInput?.value || 0),
      timeframe: (els.riskTimeframeSelect?.value || "M5").trim().toUpperCase(),
    };
    drawRiskPlannerChart({ candles: [], connection_error: "Could not load chart data for the risk planner." }, fallbackPlan);
  }
}

function saveRiskBasket() {
  localStorage.setItem("trade-observer-risk-basket", JSON.stringify(state.riskBasket));
}

function renderRiskBasket() {
  if (!els.riskBasketList || !els.riskBasketCards) return;
  if (!state.riskBasket.length) {
    els.riskBasketCards.innerHTML = "";
    els.riskBasketList.innerHTML = `<div class="empty-state">Add one or more planned trades to see the combined account risk here.</div>`;
    return;
  }
  const totalRisk = state.riskBasket.reduce((sum, item) => sum + item.riskAmount, 0);
  const totalReward = state.riskBasket.reduce((sum, item) => sum + item.rewardAmount, 0);
  const maxLossBalance = state.riskBasket[0].balance - totalRisk;
  const bestCaseBalance = state.riskBasket[0].balance + totalReward;
  const totalRiskPercent = state.riskBasket[0].balance > 0 ? (totalRisk / state.riskBasket[0].balance) * 100 : 0;
  els.riskBasketCards.innerHTML = [
    ["Basket Risk", `${state.riskBasket[0].market.quoteCurrency} ${fixed(totalRisk, 2)}`, totalRiskPercent <= 2 ? "positive" : totalRiskPercent <= 5 ? "neutral" : "negative"],
    ["Basket Reward", `${state.riskBasket[0].market.quoteCurrency} ${fixed(totalReward, 2)}`, totalReward >= totalRisk ? "positive" : "neutral"],
    ["Risk On Balance", `${fixed(totalRiskPercent, 2)}%`, totalRiskPercent <= 2 ? "positive" : totalRiskPercent <= 5 ? "neutral" : "negative"],
    ["Balance If All Lose", `${state.riskBasket[0].market.quoteCurrency} ${fixed(maxLossBalance, 2)}`, "negative"],
    ["Balance If All Win", `${state.riskBasket[0].market.quoteCurrency} ${fixed(bestCaseBalance, 2)}`, "positive"],
    ["Trades In Basket", String(state.riskBasket.length), "neutral"],
  ].map(([title, value, tone]) => `
    <article class="panel stat-panel insight-card ${tone}">
      <span>${title}</span>
      <strong>${value}</strong>
    </article>
  `).join("");

  els.riskBasketList.innerHTML = state.riskBasket.map((item, index) => `
    <article class="analysis-item ${item.side === "buy" ? "support" : "resistance"}">
      <strong>${item.market.symbol} ${item.side.toUpperCase()} · ${fixed(item.lotSize, 2)} lot</strong>
      <p>Entry / SL / TP: ${fixed(item.entry)} / ${fixed(item.stopLoss)} / ${fixed(item.takeProfit)}</p>
      <p>Risk: ${item.market.quoteCurrency} ${fixed(item.riskAmount, 2)} | Reward: ${item.market.quoteCurrency} ${fixed(item.rewardAmount, 2)} | RR: 1:${fixed(item.riskRatio, 2)}</p>
      <div class="account-profile-actions">
        <button class="row-action-button" type="button" data-risk-basket-remove="${index}">Remove</button>
      </div>
    </article>
  `).join("");

  els.riskBasketList.querySelectorAll("[data-risk-basket-remove]").forEach((button) => {
    button.addEventListener("click", () => {
      const index = Number(button.getAttribute("data-risk-basket-remove"));
      state.riskBasket.splice(index, 1);
      saveRiskBasket();
      renderRiskBasket();
    });
  });
}

function addCurrentRiskTradeToBasket() {
  const plan = getRiskPlannerData();
  state.riskBasket.push({
    market: plan.market,
    side: plan.side,
    lotSize: plan.lotSize,
    entry: plan.entry,
    stopLoss: plan.stopLoss,
    takeProfit: plan.takeProfit,
    balance: plan.balance,
    riskAmount: plan.riskAmount,
    rewardAmount: plan.rewardAmount,
    riskRatio: plan.riskRatio,
  });
  saveRiskBasket();
  renderRiskBasket();
  showToast("Trade Added", `${plan.market.symbol} ${plan.side.toUpperCase()} added to the risk basket.`, "success");
}

function runRiskPlanner() {
  if (!els.riskPlannerResults) return;
  try {
    const plan = getRiskPlannerData();
    renderRiskPlannerResult(plan);
    renderRiskGuide();
    refreshRiskPlannerChart().catch(() => {});
  } catch (error) {
    els.riskPlannerResults.innerHTML = `<p class="negative">${error.message || "Could not build the risk plan."}</p>`;
    if (els.riskPlannerCards) {
      els.riskPlannerCards.innerHTML = "";
    }
      if (els.riskPlannerMessage) {
        els.riskPlannerMessage.textContent = error.message || "Could not build the risk plan.";
        els.riskPlannerMessage.className = "analysis-banner bearish";
      }
    }
  }

function handleRiskPlannerPointerMove(event) {
  if (!els.riskPlannerCanvas) return;
  const canvas = els.riskPlannerCanvas;
  const rect = canvas.getBoundingClientRect();
  const canvasX = (event.clientX - rect.left) * (canvas.width / Math.max(rect.width, 1));
  const canvasY = (event.clientY - rect.top) * (canvas.height / Math.max(rect.height, 1));
  const geometry = state.riskChartInteraction.geometry;
  if (!geometry) return;
  const hovered = getRiskChartHandleAt(canvasX, canvasY);
  state.riskChartInteraction.hoveredHandle = hovered?.key || null;
  if (state.riskChartInteraction.draggingHandle) {
    const price = riskPlannerYToPrice(canvasY, geometry);
    state.riskChartInteraction.dragPrice = price;
    updateRiskPlannerHandlePrice(state.riskChartInteraction.draggingHandle, price);
    try {
      const plan = getRiskPlannerData();
      renderRiskPlannerResult(plan);
      renderRiskGuide();
      drawRiskPlannerChart(state.riskChart || { candles: [] }, plan);
      renderRiskChartMessage(plan, {
        text: `Dragging ${state.riskChartInteraction.draggingHandle === "entry" ? "Entry" : state.riskChartInteraction.draggingHandle === "stopLoss" ? "Stop Loss" : "Take Profit"} at ${fixed(price, getRiskChartPrecision(plan.market.symbol))}. Current price: ${fixed(geometry.currentPrice, getRiskChartPrecision(plan.market.symbol))}.`,
        tone: "neutral",
      });
    } catch (error) {
      const market = getRiskPlannerMarketSettings();
      renderRiskChartMessage({
        side: (els.riskSideSelect?.value || "buy").trim().toLowerCase(),
        market,
        timeframe: (els.riskTimeframeSelect?.value || "M5").trim().toUpperCase(),
      }, {
        text: `${error.message || "Invalid level placement while dragging."} Current price: ${fixed(geometry.currentPrice, getRiskChartPrecision(market.symbol))}.`,
        tone: "bearish",
      });
      try {
        drawRiskPlannerChart(state.riskChart || { candles: [] }, {
          market,
          side: (els.riskSideSelect?.value || "buy").trim().toLowerCase(),
          entry: Number(els.riskEntryInput?.value || 0),
          stopLoss: Number(els.riskStopInput?.value || 0),
          takeProfit: Number(els.riskTargetInput?.value || 0),
          timeframe: (els.riskTimeframeSelect?.value || "M5").trim().toUpperCase(),
        });
      } catch {}
    }
    return;
  }
  if (hovered) {
    try {
      const plan = getRiskPlannerData();
      drawRiskPlannerChart(state.riskChart || { candles: [] }, plan);
      renderRiskChartMessage(plan, {
        text: `Hovering ${hovered.key === "entry" ? "Entry" : hovered.key === "stopLoss" ? "Stop Loss" : "Take Profit"}. Drag to reposition it. Current price: ${fixed(geometry.currentPrice, getRiskChartPrecision(plan.market.symbol))}.`,
        tone: "neutral",
      });
    } catch {}
    return;
  }
  try {
    drawRiskPlannerChart(state.riskChart || { candles: [] }, getRiskPlannerData());
  } catch {}
}

function handleRiskPlannerPointerDown(event) {
  if (!els.riskPlannerCanvas || !state.riskChartInteraction.geometry) return;
  const canvas = els.riskPlannerCanvas;
  const rect = canvas.getBoundingClientRect();
  const canvasX = (event.clientX - rect.left) * (canvas.width / Math.max(rect.width, 1));
  const canvasY = (event.clientY - rect.top) * (canvas.height / Math.max(rect.height, 1));
  const handle = getRiskChartHandleAt(canvasX, canvasY);
  if (!handle) return;
  state.riskChartInteraction.draggingHandle = handle.key;
  state.riskChartInteraction.hoveredHandle = handle.key;
  state.riskChartInteraction.dragPrice = riskPlannerYToPrice(canvasY, state.riskChartInteraction.geometry);
  if (typeof canvas.setPointerCapture === "function" && event.pointerId !== undefined) {
    try {
      canvas.setPointerCapture(event.pointerId);
    } catch {}
  }
  canvas.style.cursor = "grabbing";
  event.preventDefault();
}

function stopRiskPlannerDrag(event) {
  if (!state.riskChartInteraction.draggingHandle) return;
  const canvas = els.riskPlannerCanvas;
  if (canvas && typeof canvas.releasePointerCapture === "function" && event?.pointerId !== undefined) {
    try {
      canvas.releasePointerCapture(event.pointerId);
    } catch {}
  }
  state.riskChartInteraction.draggingHandle = null;
  state.riskChartInteraction.dragPrice = null;
  try {
    drawRiskPlannerChart(state.riskChart || { candles: [] }, getRiskPlannerData());
  } catch {}
}

function relativeTime(seconds) {
  const total = Number(seconds || 0);
  if (total < 60) return `${Math.floor(total)}s ago`;
  if (total < 3600) return `${Math.floor(total / 60)}m ago`;
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  return `${hours}h ${minutes}m ago`;
}

function formatDateTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function formatUtcDateTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toISOString().replace("T", " ").replace(".000Z", " UTC").replace("Z", " UTC");
}

function setConnectionState(connected, message) {
  if (els.connectionPill) {
    els.connectionPill.textContent = connected ? "MT5 Connected" : "MT5 Disconnected";
    els.connectionPill.className = `status-pill ${connected ? "ok" : "bad"}`;
  }
  if (els.serverMeta) {
    els.serverMeta.textContent = message || "Waiting for MT5";
  }
}

function renderEmailToggle() {
  if (!els.emailToggleInput || !els.emailToggleLabel || !els.emailToggleWrap) return;
  const enabled = state.emailNotificationsEnabled;
  const configured = state.smtpConfigured;
  els.emailToggleInput.checked = configured && enabled;
  els.emailToggleInput.disabled = !configured;
  els.emailToggleWrap.classList.toggle("disabled", !configured);
  els.emailToggleLabel.textContent = configured ? `Gmail Alerts ${enabled ? "On" : "Off"}` : "Gmail Alerts Unavailable";
}

function renderNotificationsToggle() {
  if (!els.notificationsToggleInput || !els.notificationsToggleLabel || !els.notificationsToggleWrap) return;
  els.notificationsToggleInput.checked = state.notificationsEnabled;
  els.notificationsToggleWrap.classList.remove("disabled");
  els.notificationsToggleLabel.textContent = `Notifications ${state.notificationsEnabled ? "On" : "Off"}`;
}

function renderTradeLockToggle() {
  if (!els.tradeLockToggleInput || !els.tradeLockToggleLabel || !els.tradeLockToggleWrap) return;
  els.tradeLockToggleInput.checked = state.tradeLockEnabled;
  els.tradeLockToggleWrap.classList.remove("disabled");
  els.tradeLockToggleLabel.textContent = `Trade Lock ${state.tradeLockEnabled ? "On" : "Off"}`;
}

function isAlertTypeEnabled(eventType) {
  if (!eventType) return true;
  const saved = state.alertTypeEnabled?.[eventType];
  return saved !== false;
}

function renderAlertSettings() {
  if (!els.alertSettingsList) return;
  els.alertSettingsList.innerHTML = ALERT_TOGGLE_DEFS.map(([eventType, title, description]) => `
    <article class="alert-setting-card">
      <div class="alert-setting-copy">
        <strong>${title}</strong>
        <p>${description}</p>
      </div>
      <label class="toggle-chip">
        <input type="checkbox" data-alert-toggle="${eventType}" ${isAlertTypeEnabled(eventType) ? "checked" : ""}>
        <span class="toggle-slider"></span>
        <span class="toggle-label">${isAlertTypeEnabled(eventType) ? "On" : "Off"}</span>
      </label>
    </article>
  `).join("");
  els.alertSettingsList.querySelectorAll("[data-alert-toggle]").forEach((input) => {
    input.addEventListener("change", async () => {
      const eventType = input.getAttribute("data-alert-toggle") || "";
      state.alertTypeEnabled[eventType] = input.checked;
      localStorage.setItem("trade-observer-alert-type-enabled", JSON.stringify(state.alertTypeEnabled));
      try {
        await postJson("/api/notifications-preferences", {
          notifications_enabled: state.notificationsEnabled,
          alert_type_enabled: state.alertTypeEnabled,
        });
        renderAlertSettings();
        showToast("Alert Preference Saved", `${alarmTitleFor(eventType)} is now ${input.checked ? "enabled" : "muted"}.`, "success");
      } catch (error) {
        showToast("Preference Save Failed", error.message || "Could not save alert preference to the server.", "warn");
      }
    });
  });
}

function setAllAlertTypesEnabled(enabled) {
  ALERT_TOGGLE_DEFS.forEach(([eventType]) => {
    state.alertTypeEnabled[eventType] = enabled;
  });
  localStorage.setItem("trade-observer-alert-type-enabled", JSON.stringify(state.alertTypeEnabled));
}

function renderAnalysis(payload) {
  state.analysis = payload;
  els.analysisSymbol.textContent = payload?.symbol || "XAUUSD";
  els.analysisTimeframe.textContent = payload?.timeframe || state.analysisTimeframe || "H1";
  if (els.analysisTimeframeSelect) {
    els.analysisTimeframeSelect.value = payload?.timeframe || state.analysisTimeframe || "H1";
  }
  if (els.analysisSession) {
    els.analysisSession.textContent = payload?.day_state?.session_label || payload?.market_snapshot?.session_name || "-";
  }
  els.analysisBias.textContent = payload?.bias ? payload.bias.toUpperCase() : "NEUTRAL";
  els.analysisBias.className = payload?.bias === "bullish" ? "positive" : payload?.bias === "bearish" ? "negative" : "";
  els.analysisPrice.textContent = payload?.current_price ? fixed(payload.current_price) : "-";
  if (els.analysisPrediction) {
    const promptState = payload?.prompt_state || {};
    const tradeAdvice = payload?.trade_advice || {};
    els.analysisPrediction.textContent = promptState.summary || tradeAdvice.summary || "Execution guidance will appear after MT5 candle data loads.";
    els.analysisPrediction.className = `analysis-banner ${promptState.tone || tradeAdvice.tone || "neutral"}`;
  }
  if (els.analysisOpenMarkets) {
    els.analysisOpenMarkets.textContent = payload?.market_sessions?.open_sessions?.length
      ? payload.market_sessions.open_sessions.join(", ")
      : "No major market is currently open";
  }
  if (els.analysisTradeRead) {
    const promptState = payload?.prompt_state || {};
    const executionPlan = payload?.execution_plan || {};
    const activePosition = payload?.active_position || null;
    const tradeAdvice = payload?.trade_advice || {};
    const tone = promptState.tone || tradeAdvice.tone || "neutral";
    const actionLabelMap = {
      buy_now: "Buy Now",
      sell_now: "Sell Now",
      break_even: "Move To Break-Even",
      trail_stop: "Trail Stop Now",
      manage: "Manage Open Trade",
      blocked: "Blocked",
      wait: "Wait",
    };
    els.analysisTradeRead.innerHTML = `
      <article class="analysis-item ${tone}">
        <strong>${actionLabelMap[promptState.state] || "Wait"}</strong>
        <p>${promptState.summary || tradeAdvice.summary || "Trade guidance will appear after candle data loads."}</p>
      </article>
      <article class="analysis-item ${tone}">
        <strong>${activePosition ? "Live Position" : "Planned Entry"}</strong>
        <p>${activePosition
          ? `${String(activePosition.side || "").toUpperCase()} | Entry ${fixed(activePosition.entry || 0)} | SL ${activePosition.stop_loss ? fixed(activePosition.stop_loss) : "Not Set"} | TP ${activePosition.take_profit ? fixed(activePosition.take_profit) : "Not Set"}`
          : executionPlan.side && executionPlan.side !== "wait"
            ? `${String(executionPlan.side).toUpperCase()} | Entry ${fixed(executionPlan.entry || 0)} | SL ${fixed(executionPlan.stop_loss || 0)} | TP ${fixed(executionPlan.take_profit || 0)}`
            : "No directional execution plan is active yet."}</p>
      </article>
      <article class="analysis-item neutral">
        <strong>How This Assistant Thinks</strong>
        <p>${tradeAdvice.method_note || "This page mirrors the bot logic but never places trades."}</p>
      </article>
    `;
  }
  const promptState = payload?.prompt_state || {};
  const latestCandleTime = Array.isArray(payload?.candles) && payload.candles.length
    ? String(payload.candles[payload.candles.length - 1]?.time || "")
    : "";
  const promptEventMap = {
    buy_now: "analysis_buy_confirmed",
    break_even: "analysis_break_even_prompt",
    trail_stop: "analysis_trailing_prompt",
  };
  const promptEvent = promptEventMap[promptState.state] || "";
  const analysisPromptKey = promptEvent
    ? [
      "analysis",
      payload?.symbol || state.currentSymbol || "XAUUSD",
      payload?.timeframe || state.analysisTimeframe || "H1",
      promptState.state,
      latestCandleTime,
    ].join("|")
    : "";
  if (analysisPromptKey && analysisPromptKey !== state.lastAnalysisPromptKey) {
    state.lastAnalysisPromptKey = analysisPromptKey;
    localStorage.setItem("trade-observer-last-analysis-prompt-key", analysisPromptKey);
    addLocalAlert(
      {
        ts: new Date().toISOString(),
        event_type: promptEvent,
        severity: ["analysis_break_even_prompt", "analysis_trailing_prompt"].includes(promptEvent) ? "warn" : "success",
        message: `${payload?.symbol || "XAUUSD"} ${payload?.timeframe || state.analysisTimeframe || "H1"}: ${promptState.summary || "Analysis prompt updated."}`,
        ticket: payload?.active_position?.ticket || null,
        symbol: payload?.symbol || state.currentSymbol || "XAUUSD",
      },
      analysisPromptKey,
    );
  }
  if (els.analysisGateChecks) {
    const gateChecks = Array.isArray(payload?.gate_checks) ? payload.gate_checks : [];
    els.analysisGateChecks.innerHTML = gateChecks.length
      ? gateChecks.map((gate) => `
        <article class="analysis-item ${gate.passed ? "bullish" : gate.blocking ? "bearish" : "neutral"}">
          <strong>${gate.label}: ${gate.passed ? "PASS" : gate.blocking ? "BLOCKED" : "WATCH"}</strong>
          <p>${gate.detail}</p>
        </article>
      `).join("")
      : `<div class="empty-state">Session, spread, ATR, and daily guardrails will appear here.</div>`;
  }
  if (els.analysisRiskPlan) {
    const riskPlan = payload?.risk_plan || {};
    const executionPlan = payload?.execution_plan || {};
    els.analysisRiskPlan.innerHTML = `
      <article class="analysis-item neutral">
        <strong>Suggested Lot</strong>
        <p>${riskPlan.lot_size ? riskPlan.lot_size.toFixed(2) : "0.00"} lots | Risk ${money(riskPlan.risk_amount || 0)}</p>
      </article>
      <article class="analysis-item neutral">
        <strong>Plan Geometry</strong>
        <p>Stop ${fixed(executionPlan.stop_distance || 0)} | Target ${fixed(executionPlan.take_profit_distance || 0)} | RR ${fixed(executionPlan.rr_ratio || 0, 2)}R</p>
      </article>
      <article class="analysis-item neutral">
        <strong>Lot Logic</strong>
        <p>${riskPlan.note || "Risk sizing notes will appear here."}</p>
      </article>
    `;
  }
  if (els.analysisBotContext) {
    const snapshot = payload?.market_snapshot || {};
    const dayState = payload?.day_state || {};
    const biasModel = payload?.bias_model || {};
    const consolidation = payload?.consolidation_context || {};
    const consolidationRange = consolidation?.range || {};
    els.analysisBotContext.innerHTML = `
      <article class="analysis-item ${payload?.bias === "bullish" ? "bullish" : payload?.bias === "bearish" ? "bearish" : "neutral"}">
        <strong>Bias Model</strong>
        <p>Price ${fixed(payload?.current_price || 0)} vs H4 EMA200 ${fixed(biasModel.h4_ema200 || 0)}.</p>
        <p>Directional lean: ${String(payload?.bias || "neutral").toUpperCase()}.</p>
      </article>
      <article class="analysis-item neutral">
        <strong>Market Snapshot</strong>
        <p>Spread ${fixed(snapshot.spread_points || 0, 1)} pts | ATR ${fixed(snapshot.atr_points || 0, 1)} pts | Kill Zone ${snapshot.kill_zone_active ? "Active" : "Inactive"}</p>
      </article>
      <article class="analysis-item ${consolidation.in_consolidation ? "pivot" : "neutral"}">
        <strong>Consolidation Read (${consolidation.timeframe || "M5"})</strong>
        <p>${consolidation.message || "Consolidation analysis is unavailable right now."}</p>
        <p>Range ${fixed(consolidationRange.low || 0)} to ${fixed(consolidationRange.high || 0)} | Size ${fixed(consolidationRange.size || 0)}</p>
      </article>
      <article class="analysis-item neutral">
        <strong>Daily State</strong>
        <p>Start ${money(dayState.day_start_balance || 0)} | Balance ${money(dayState.balance || 0)} | Equity ${money(dayState.equity || 0)}</p>
        <p>Daily P/L ${money(dayState.realized_daily_pl || 0)} (${fixed(dayState.daily_pl_pct || 0, 2)}%) | Trades ${dayState.today_trade_count || 0}</p>
      </article>
    `;
  }
  if (els.analysisManagementPlan) {
    const managementPlan = payload?.management_plan || {};
    els.analysisManagementPlan.innerHTML = managementPlan.has_open_position
      ? `
        <article class="analysis-item ${managementPlan.tone || "neutral"}">
          <strong>Current Prompt</strong>
          <p>${managementPlan.summary || "Management guidance will appear here."}</p>
        </article>
        <article class="analysis-item neutral">
          <strong>Break-Even Trigger</strong>
          <p>${fixed(managementPlan.break_even_trigger || 0)} | Trailing Trigger ${fixed(managementPlan.trailing_trigger || 0)}</p>
        </article>
        <article class="analysis-item neutral">
          <strong>Trailing Plan</strong>
          <p>Step ${fixed(managementPlan.trailing_step || 0)} | Suggested trailing SL ${fixed(managementPlan.suggested_trailing_stop || 0)}</p>
        </article>
      `
      : `<div class="empty-state">${managementPlan.summary || "No live position on this symbol, so the page is in planning mode."}</div>`;
  }

  const structureContext = payload?.structure_context || {};
  const liquidityLevels = Array.isArray(structureContext.liquidity_levels) ? structureContext.liquidity_levels : [];
  const fvgs = Array.isArray(structureContext.fair_value_gaps) ? structureContext.fair_value_gaps : [];
  const orderBlocks = Array.isArray(structureContext.order_blocks) ? structureContext.order_blocks : [];
  if (!liquidityLevels.length && !fvgs.length && !orderBlocks.length) {
    els.analysisZones.innerHTML = `<div class="empty-state">${payload?.connection_error || "Liquidity levels, fair value gaps, and order blocks will appear here."}</div>`;
  } else {
    els.analysisZones.innerHTML = [
      ...liquidityLevels.slice(0, 3).map((level) => `
        <article class="analysis-item ${level.kind === "high" ? "resistance" : "support"}">
          <strong>Liquidity ${level.kind === "high" ? "High" : "Low"}</strong>
          <p>${fixed(level.price)} | Strength ${level.strength || 0}</p>
        </article>
      `),
      ...fvgs.slice(0, 2).map((gap) => `
        <article class="analysis-item ${gap.kind === "bullish" ? "bullish" : "bearish"}">
          <strong>${gap.kind === "bullish" ? "Bullish" : "Bearish"} FVG</strong>
          <p>${fixed(gap.low)} to ${fixed(gap.high)} | Size ${fixed(gap.size || 0)}</p>
        </article>
      `),
      ...orderBlocks.slice(0, 2).map((block) => `
        <article class="analysis-item ${block.kind === "bullish" ? "support" : "resistance"}">
          <strong>${block.kind === "bullish" ? "Bullish" : "Bearish"} Order Block</strong>
          <p>${fixed(block.low)} to ${fixed(block.high)}</p>
        </article>
      `),
    ].join("");
  }

  if (!payload?.confluences?.length) {
    els.analysisConfluences.innerHTML = `<div class="empty-state">${payload?.connection_error || "Bot notes will appear here once MT5 candle data is loaded."}</div>`;
  } else {
    els.analysisConfluences.innerHTML = payload.confluences.map((item) => `
      <article class="analysis-item ${item.tone}">
        <strong>${item.title}</strong>
        <p>${item.detail}</p>
      </article>
    `).join("");
  }

  drawAnalysisChart(payload);
}

function setOrlMode(mode) {
  state.orlMode = mode === "historical" ? "historical" : "live";
  els.analysisLiveChartSection?.classList.toggle("hidden-page", state.orlMode !== "live");
  els.orlHistoricalSection?.classList.toggle("hidden-page", state.orlMode !== "historical");
  els.orlLiveModeButton?.classList.toggle("active", state.orlMode === "live");
  els.orlPastModeButton?.classList.toggle("active", state.orlMode === "historical");
}

function renderOrlValidationMessages(messages, tone = "neutral") {
  if (!els.orlAnalyzeValidation) return;
  if (!messages?.length) {
    els.orlAnalyzeValidation.innerHTML = "";
    return;
  }
  els.orlAnalyzeValidation.innerHTML = messages.map((message) => `
    <article class="analysis-item ${tone}">
      <p>${message}</p>
    </article>
  `).join("");
}

function openOrlAnalyzeModal() {
  els.orlAnalyzeModal?.classList.remove("hidden");
  els.orlAnalyzeModal?.setAttribute("aria-hidden", "false");
}

function closeOrlAnalyzeModal() {
  els.orlAnalyzeModal?.classList.add("hidden");
  els.orlAnalyzeModal?.setAttribute("aria-hidden", "true");
}

function openOrlDetailsModal() {
  els.orlDetailsModal?.classList.remove("hidden");
  els.orlDetailsModal?.setAttribute("aria-hidden", "false");
}

function closeOrlDetailsModal() {
  els.orlDetailsModal?.classList.add("hidden");
  els.orlDetailsModal?.setAttribute("aria-hidden", "true");
}

function renderOrlDetails(details, logs = []) {
  if (!els.orlDetailsContent) return;
  if (!details) {
    els.orlDetailsContent.innerHTML = `<div class="empty-state">Run a live ORL session or historical analysis to see full ORL details.</div>`;
    return;
  }
  const rows = Object.entries(details).map(([key, value]) => `
    <article class="analysis-item neutral">
      <strong>${key.replaceAll("_", " ")}</strong>
      <p>${value === "" || value === null || value === undefined ? "-" : value}</p>
    </article>
  `).join("");
  const logRows = logs.map((entry) => `<article class="analysis-item pivot"><p>${entry}</p></article>`).join("");
  els.orlDetailsContent.innerHTML = rows + (logRows ? `<div class="analysis-list">${logRows}</div>` : "");
}

function renderOrlLiveStatus(payload) {
  state.orlLiveStatus = payload;
  const status = payload?.status || payload || {};
  const analysis = status.analysis?.success ? status.analysis : null;
  const details = analysis?.details || {};
  if (els.orlLiveSession) els.orlLiveSession.textContent = status.session || analysis?.session || "New York";
  if (els.orlLiveStatus) els.orlLiveStatus.textContent = status.active ? "Running" : "Idle";
  if (els.orlLiveManipulation) els.orlLiveManipulation.textContent = analysis ? analysis.manipulation?.passed ? "Confirmed" : "Not Confirmed" : "-";
  if (els.orlLiveSignal) els.orlLiveSignal.textContent = analysis?.signal?.pattern?.pattern || "No signal";
  if (els.orlLiveAlertWindow) els.orlLiveAlertWindow.textContent = details.pre_close_alert_time ? formatDateTime(details.pre_close_alert_time) : "-";
  if (els.orlLiveMessage) {
    const summary = analysis?.trade_plan?.valid
      ? `${analysis.trade_plan.direction} setup: entry ${fixed(analysis.trade_plan.entry)} | SL ${fixed(analysis.trade_plan.stop_loss)} | TP ${fixed(analysis.trade_plan.take_profit)}`
      : (analysis?.details?.final_reason || status.message || "No setup = no signal.");
    els.orlLiveMessage.textContent = summary;
    els.orlLiveMessage.className = `analysis-banner ${analysis?.trade_plan?.valid ? (analysis.trade_plan.direction === "Buy" ? "bullish" : "bearish") : "neutral"}`;
  }
  if (els.orlLiveSignalCard) {
    if (!analysis) {
      els.orlLiveSignalCard.innerHTML = `<div class="empty-state">${status.message || "Live ORL-25 observer is waiting for session data."}</div>`;
    } else {
      const signal = analysis.signal?.pattern || {};
      const plan = analysis.trade_plan || {};
      els.orlLiveSignalCard.innerHTML = `
        <article class="analysis-item ${plan.direction === "Buy" ? "support" : plan.direction === "Sell" ? "resistance" : "neutral"}">
          <strong>${signal.pattern || "No pattern detected"}</strong>
          <p>Direction: ${plan.direction || "-"}</p>
          <p>Entry: ${plan.entry ? fixed(plan.entry) : "-"}</p>
          <p>Stop Loss: ${plan.stop_loss ? fixed(plan.stop_loss) : "-"}</p>
          <p>Take Profit: ${plan.take_profit ? fixed(plan.take_profit) : "-"}</p>
          <p>Risk: ${plan.risk_distance ? fixed(plan.risk_distance) : "-"}</p>
          <p>Reward: ${plan.reward_distance ? fixed(plan.reward_distance) : "-"}</p>
        </article>
      `;
    }
  }
  renderOrlDetails(analysis?.details || null, analysis?.logs || status.events?.map((event) => event.message) || []);
}

function drawSimpleCandleChart(ctxLike, canvas, candles, annotations = []) {
  if (!ctxLike || !canvas) return;
  const width = Math.max(320, canvas.clientWidth || canvas.width);
  const height = Math.max(320, Math.round(width * 0.45));
  canvas.width = width;
  canvas.height = height;
  ctxLike.clearRect(0, 0, width, height);
  ctxLike.fillStyle = getComputedStyle(document.body).getPropertyValue("--panel-soft");
  ctxLike.fillRect(0, 0, width, height);
  if (!candles.length) {
    ctxLike.fillStyle = getComputedStyle(document.body).getPropertyValue("--muted");
    ctxLike.font = "18px Aptos";
    ctxLike.fillText("No ORL historical candles to draw yet.", 24, height / 2);
    return;
  }
  const padding = { top: 24, right: 96, bottom: 28, left: 52 };
  const highs = candles.map((candle) => Number(candle.high));
  const lows = candles.map((candle) => Number(candle.low));
  const maxPrice = Math.max(...highs);
  const minPrice = Math.min(...lows);
  const spread = Math.max(maxPrice - minPrice, 0.01);
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const candleWidth = Math.max(4, plotWidth / candles.length * 0.72);

  annotations.forEach((annotation) => {
    if (annotation.type === "opening_range_box") {
      const highY = padding.top + (maxPrice - Number(annotation.high)) / spread * plotHeight;
      const lowY = padding.top + (maxPrice - Number(annotation.low)) / spread * plotHeight;
      ctxLike.fillStyle = "rgba(105, 211, 255, 0.10)";
      ctxLike.fillRect(padding.left, Math.min(highY, lowY), plotWidth, Math.abs(lowY - highY));
      ctxLike.strokeStyle = "rgba(105, 211, 255, 0.85)";
      ctxLike.strokeRect(padding.left, Math.min(highY, lowY), plotWidth, Math.abs(lowY - highY));
    }
    if (annotation.type === "line") {
      const y = padding.top + (maxPrice - Number(annotation.price)) / spread * plotHeight;
      ctxLike.strokeStyle = annotation.label?.includes("Stop") ? "rgba(255, 107, 122, 0.88)" : annotation.label?.includes("Take") ? "rgba(75, 240, 179, 0.88)" : "rgba(105, 211, 255, 0.85)";
      ctxLike.setLineDash([7, 5]);
      ctxLike.beginPath();
      ctxLike.moveTo(padding.left, y);
      ctxLike.lineTo(width - padding.right + 8, y);
      ctxLike.stroke();
      ctxLike.setLineDash([]);
      ctxLike.fillStyle = ctxLike.strokeStyle;
      ctxLike.fillText(annotation.label || "", padding.left + 10, y - 6);
    }
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
    const yHigh = padding.top + (maxPrice - high) / spread * plotHeight;
    const yLow = padding.top + (maxPrice - low) / spread * plotHeight;
    const yOpen = padding.top + (maxPrice - open) / spread * plotHeight;
    const yClose = padding.top + (maxPrice - close) / spread * plotHeight;
    ctxLike.strokeStyle = color;
    ctxLike.beginPath();
    ctxLike.moveTo(centerX, yHigh);
    ctxLike.lineTo(centerX, yLow);
    ctxLike.stroke();
    ctxLike.fillStyle = color;
    ctxLike.fillRect(centerX - candleWidth / 2, Math.min(yOpen, yClose), candleWidth, Math.max(2, Math.abs(yClose - yOpen)));
  });
}

function renderOrlHistoricalResult(response) {
  state.orlHistorical = response;
  const analysis = response?.success ? response : null;
  if (els.orlHistoricalResultCard) {
    if (!analysis) {
      els.orlHistoricalResultCard.innerHTML = `<div class="empty-state">Run Analyze Past Chart to see the ORL-25 historical result card.</div>`;
    } else {
      els.orlHistoricalResultCard.innerHTML = `
        <article class="analysis-item ${analysis.trade_plan?.direction === "Buy" ? "support" : analysis.trade_plan?.direction === "Sell" ? "resistance" : "neutral"}">
          <strong>${analysis.symbol} | ${analysis.date} | ${analysis.session}</strong>
          <p>Manipulation: ${analysis.manipulation?.passed ? "Confirmed" : "Not Confirmed"}</p>
          <p>Pattern: ${analysis.signal?.pattern?.pattern || "None"}</p>
          <p>Direction: ${analysis.trade_plan?.direction || "-"}</p>
          <p>Entry: ${analysis.trade_plan?.entry ? fixed(analysis.trade_plan.entry) : "-"}</p>
          <p>SL: ${analysis.trade_plan?.stop_loss ? fixed(analysis.trade_plan.stop_loss) : "-"}</p>
          <p>TP: ${analysis.trade_plan?.take_profit ? fixed(analysis.trade_plan.take_profit) : "-"}</p>
          <p>Outcome: ${analysis.outcome?.outcome || "No trigger"}</p>
          <p>Estimated Result: ${money(analysis.profit_loss?.estimated_result || 0)}</p>
        </article>
      `;
    }
  }
  if (els.orlHistoricalNarrative) {
    if (!analysis) {
      els.orlHistoricalNarrative.innerHTML = `<div class="empty-state">Analyze a past chart to populate historical annotations and results.</div>`;
    } else {
      const details = analysis.details || {};
      els.orlHistoricalNarrative.innerHTML = `
        <article class="analysis-item neutral">
          <strong>ORL-25 Historical Analysis Result</strong>
          <p>Session Open: ${analysis.session_open}</p>
          <p>Opening Range High: ${fixed(details.opening_range_high || 0)}</p>
          <p>Opening Range Low: ${fixed(details.opening_range_low || 0)}</p>
          <p>Opening Range Size: ${fixed(details.opening_range_size || 0)}</p>
          <p>ATR(${analysis.atr?.period || 14}): ${fixed(analysis.atr?.value || 0)}</p>
          <p>25% Threshold: ${fixed(analysis.atr?.threshold_value || 0)}</p>
          <p>Final Reason: ${details.final_reason || "-"}</p>
        </article>
      `;
    }
  }
  if (els.orlHistoricalLogs) {
    els.orlHistoricalLogs.innerHTML = analysis?.logs?.length
      ? analysis.logs.map((entry) => `<article class="analysis-item pivot"><p>${entry}</p></article>`).join("")
      : `<div class="empty-state">The ORL engine logs will appear here after analysis.</div>`;
  }
  if (analysis?.chart_candles?.m5) {
    drawSimpleCandleChart(orlHistoricalCtx, els.orlHistoricalCanvas, analysis.chart_candles.m5, analysis.chart_annotations || []);
  }
  renderOrlDetails(analysis?.details || null, analysis?.logs || []);
}

async function loadOrlSessionsAndSymbols() {
  const [sessionsPayload, symbolsPayload] = await Promise.all([
    fetchJson("/api/orl/sessions"),
    fetchJson("/api/orl/symbols"),
  ]);
  state.orlConfig = sessionsPayload;
  state.orlSymbols = symbolsPayload.symbols || [];
  if (els.orlSessionSelect) {
    els.orlSessionSelect.innerHTML = Object.keys(sessionsPayload.sessions || {}).map((name) => `<option value="${name}">${name}</option>`).join("") + `<option value="Custom">Custom</option>`;
    els.orlSessionSelect.value = sessionsPayload.default_session || "New York";
  }
  if (els.orlSymbolSelect) {
    els.orlSymbolSelect.innerHTML = state.orlSymbols.map((symbol) => `<option value="${symbol}">${symbol}</option>`).join("");
    const preferred = state.currentSymbol && state.orlSymbols.includes(state.currentSymbol) ? state.currentSymbol : (state.orlSymbols.find((item) => item.toUpperCase().startsWith("XAUUSD")) || state.orlSymbols[0] || "");
    els.orlSymbolSelect.value = preferred;
  }
  if (els.orlDateInput && !els.orlDateInput.value) {
    els.orlDateInput.value = new Date().toISOString().slice(0, 10);
  }
}

async function refreshOrlLiveStatus() {
  try {
    const payload = await fetchJson("/api/orl/live/status");
    renderOrlLiveStatus(payload);
  } catch (error) {
    renderOrlLiveStatus({ active: false, message: "Could not load ORL live status." });
  }
}

function drawAnalysisChart(payload) {
  if (!analysisCtx || !els.analysisCanvas) return;
  const canvas = els.analysisCanvas;
  const fullscreenActive = Boolean(els.analysisStage && document.fullscreenElement === els.analysisStage);
  const width = Math.max(fullscreenActive ? 1200 : 320, canvas.clientWidth || canvas.width);
  const height = fullscreenActive
    ? Math.max(620, window.innerHeight - 220)
    : Math.max(320, Math.round(width * 0.45));
  canvas.width = width;
  canvas.height = height;
  analysisCtx.clearRect(0, 0, width, height);

  const candles = payload?.candles || [];
  if (!candles.length) {
    analysisCtx.fillStyle = getComputedStyle(document.body).getPropertyValue("--panel-soft");
    analysisCtx.fillRect(0, 0, width, height);
    analysisCtx.fillStyle = getComputedStyle(document.body).getPropertyValue("--muted");
    analysisCtx.font = "18px Aptos";
    analysisCtx.fillText(payload?.connection_error || "Waiting for XAUUSD candle data...", 24, height / 2);
    return;
  }

  const padding = { top: 24, right: 98, bottom: 28, left: 52 };
  const highs = candles.map((candle) => Number(candle.high));
  const lows = candles.map((candle) => Number(candle.low));
  const closes = candles.map((candle) => Number(candle.close));
  const maxPrice = Math.max(...highs);
  const minPrice = Math.min(...lows);
  const spread = Math.max(maxPrice - minPrice, 0.01);
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const candleWidth = Math.max(4, plotWidth / candles.length * 0.72);

  analysisCtx.fillStyle = getComputedStyle(document.body).getPropertyValue("--panel-soft");
  analysisCtx.fillRect(0, 0, width, height);

  const matchingTrades = (state.activeTrades || []).filter((trade) => {
    const tradeSymbol = String(trade.symbol || "").trim().toUpperCase();
    const chartSymbol = String(payload?.symbol || "").trim().toUpperCase();
    return tradeSymbol && chartSymbol && tradeSymbol === chartSymbol;
  });

  (payload?.zones || []).forEach((zone) => {
    const topY = padding.top + (maxPrice - Number(zone.high)) / spread * plotHeight;
    const bottomY = padding.top + (maxPrice - Number(zone.low)) / spread * plotHeight;
    const fill = zone.kind === "support"
      ? "rgba(75, 240, 179, 0.12)"
      : zone.kind === "resistance"
        ? "rgba(255, 107, 122, 0.12)"
        : "rgba(105, 211, 255, 0.10)";
    const stroke = zone.kind === "support"
      ? "rgba(75, 240, 179, 0.88)"
      : zone.kind === "resistance"
        ? "rgba(255, 107, 122, 0.88)"
        : "rgba(105, 211, 255, 0.82)";
    const zoneY = Math.min(topY, bottomY);
    const zoneHeight = Math.max(8, Math.abs(bottomY - topY));
    analysisCtx.fillStyle = fill;
    analysisCtx.fillRect(padding.left, zoneY, plotWidth, zoneHeight);
    analysisCtx.strokeStyle = stroke;
    analysisCtx.setLineDash([7, 5]);
    analysisCtx.strokeRect(padding.left, zoneY, plotWidth, zoneHeight);
    analysisCtx.setLineDash([]);
    analysisCtx.fillStyle = stroke;
    analysisCtx.font = "12px Aptos";
    analysisCtx.fillText(zone.label, padding.left + 8, zoneY + 15);
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
    const yHigh = padding.top + (maxPrice - high) / spread * plotHeight;
    const yLow = padding.top + (maxPrice - low) / spread * plotHeight;
    const yOpen = padding.top + (maxPrice - open) / spread * plotHeight;
    const yClose = padding.top + (maxPrice - close) / spread * plotHeight;

    analysisCtx.strokeStyle = color;
    analysisCtx.lineWidth = 1;
    analysisCtx.beginPath();
    analysisCtx.moveTo(centerX, yHigh);
    analysisCtx.lineTo(centerX, yLow);
    analysisCtx.stroke();

    analysisCtx.fillStyle = color;
    const bodyTop = Math.min(yOpen, yClose);
    const bodyHeight = Math.max(2, Math.abs(yClose - yOpen));
    analysisCtx.fillRect(centerX - candleWidth / 2, bodyTop, candleWidth, bodyHeight);
  });

  const drawTradeLevel = (price, color, label) => {
    if (!price || Number.isNaN(Number(price))) return;
    const y = padding.top + (maxPrice - Number(price)) / spread * plotHeight;
    if (y < padding.top - 24 || y > height - padding.bottom + 24) return;
    analysisCtx.strokeStyle = color;
    analysisCtx.lineWidth = 1.6;
    analysisCtx.setLineDash([9, 6]);
    analysisCtx.beginPath();
    analysisCtx.moveTo(padding.left, y);
    analysisCtx.lineTo(width - padding.right + 8, y);
    analysisCtx.stroke();
    analysisCtx.setLineDash([]);
    analysisCtx.fillStyle = color;
    analysisCtx.fillRect(padding.left + 8, y - 12, 124, 20);
    analysisCtx.fillStyle = "#04131c";
    analysisCtx.font = "12px Aptos";
    analysisCtx.fillText(label, padding.left + 14, y + 3);
  };

  const executionPlan = payload?.execution_plan || {};
  if (executionPlan.side && executionPlan.side !== "wait") {
    drawTradeLevel(executionPlan.entry, "rgba(105, 211, 255, 0.95)", `Plan ${String(executionPlan.side).toUpperCase()} ${fixed(executionPlan.entry || 0)}`);
    drawTradeLevel(executionPlan.stop_loss, "rgba(255, 107, 122, 0.95)", `Plan SL ${fixed(executionPlan.stop_loss || 0)}`);
    drawTradeLevel(executionPlan.take_profit, "rgba(75, 240, 179, 0.95)", `Plan TP ${fixed(executionPlan.take_profit || 0)}`);
  }

  const managementPlan = payload?.management_plan || {};
  if (managementPlan.has_open_position) {
    drawTradeLevel(managementPlan.break_even_trigger, "rgba(255, 215, 97, 0.95)", `BE ${fixed(managementPlan.break_even_trigger || 0)}`);
    drawTradeLevel(managementPlan.trailing_trigger, "rgba(193, 133, 255, 0.95)", `TRAIL ${fixed(managementPlan.trailing_trigger || 0)}`);
  }

  matchingTrades.forEach((trade) => {
    if (Number(trade.stop_loss) > 0) {
      drawTradeLevel(trade.stop_loss, "rgba(255, 107, 122, 0.95)", `SL ${fixed(trade.stop_loss)}`);
    }
    if (Number(trade.take_profit) > 0) {
      drawTradeLevel(trade.take_profit, "rgba(75, 240, 179, 0.95)", `TP ${fixed(trade.take_profit)}`);
    }
  });

  analysisCtx.fillStyle = getComputedStyle(document.body).getPropertyValue("--muted");
  analysisCtx.font = "13px Cascadia Mono";
  analysisCtx.fillText(fixed(maxPrice), 10, padding.top + 6);
  analysisCtx.fillText(fixed(minPrice), 10, height - padding.bottom + 4);
  analysisCtx.fillText(`${payload.symbol} ${payload.timeframe}`, padding.left, 18);

  const rightScaleValues = [maxPrice, (maxPrice + minPrice) / 2, minPrice, Number(payload.current_price || closes.at(-1) || 0)];
  const printed = new Set();
  rightScaleValues.forEach((price) => {
    const rounded = fixed(price);
    if (printed.has(rounded)) return;
    printed.add(rounded);
    const y = padding.top + (maxPrice - Number(price)) / spread * plotHeight;
    analysisCtx.strokeStyle = "rgba(255,255,255,0.08)";
    analysisCtx.setLineDash([4, 6]);
    analysisCtx.beginPath();
    analysisCtx.moveTo(padding.left, y);
    analysisCtx.lineTo(width - padding.right + 8, y);
    analysisCtx.stroke();
    analysisCtx.setLineDash([]);
    analysisCtx.fillStyle = getComputedStyle(document.body).getPropertyValue("--text");
    analysisCtx.fillText(rounded, width - padding.right + 16, y + 4);
  });

  const livePrice = Number(payload.current_price || closes.at(-1) || 0);
  const liveY = padding.top + (maxPrice - livePrice) / spread * plotHeight;
  analysisCtx.strokeStyle = "rgba(105, 211, 255, 0.88)";
  analysisCtx.lineWidth = 1.4;
  analysisCtx.beginPath();
  analysisCtx.moveTo(padding.left, liveY);
  analysisCtx.lineTo(width - padding.right + 8, liveY);
  analysisCtx.stroke();
  analysisCtx.fillStyle = "rgba(105, 211, 255, 0.95)";
  analysisCtx.fillRect(width - padding.right + 10, liveY - 12, 72, 22);
  analysisCtx.fillStyle = "#04131c";
  analysisCtx.fillText(fixed(livePrice), width - padding.right + 18, liveY + 4);
  }

async function refreshAnalysis() {
  try {
    const symbol = state.currentSymbol || "XAUUSD";
    const timeframe = state.analysisTimeframe || "H1";
    const payload = await fetchJson(`/api/analysis?symbol=${encodeURIComponent(symbol)}&timeframe=${encodeURIComponent(timeframe)}`);
    renderAnalysis(payload);
  } catch (error) {
    renderAnalysis({
      symbol: state.currentSymbol || "XAUUSD",
      timeframe: state.analysisTimeframe || "H1",
      candles: [],
      zones: [],
      confluences: [],
      bias: "neutral",
      current_price: 0,
      connection_error: "Could not load analysis data from the local server.",
    });
  }
}

function updateAnalysisFullscreenUi() {
  if (!els.analysisFullscreenButton || !els.analysisStage) return;
  const active = document.fullscreenElement === els.analysisStage;
  els.analysisStage.classList.toggle("is-fullscreen", active);
  els.analysisFullscreenButton.textContent = active ? "Exit Full Screen" : "Full Screen";
}

async function toggleAnalysisFullscreen() {
  if (!els.analysisStage || !document.fullscreenEnabled) {
    showToast("Fullscreen is not available in this browser.");
    return;
  }
  if (document.fullscreenElement === els.analysisStage) {
    await document.exitFullscreen();
  } else {
    await els.analysisStage.requestFullscreen();
  }
}

function normalizeInstrumentKey(symbol) {
  const upper = String(symbol || "").trim().toUpperCase().replace(/[^A-Z0-9]/g, "");
  if (upper.startsWith("XAUUSD")) return "XAUUSD";
  if (upper.startsWith("GOLD")) return "XAUUSD";
  if (upper.startsWith("EURUSD")) return "EURUSD";
  if (upper.startsWith("BTCUSD")) return "BTCUSD";
  return upper.replace(/M$/, "");
}

function renderChartsSummary(payload) {
  if (els.chartResolvedSymbol) els.chartResolvedSymbol.textContent = payload?.symbol || "-";
  if (els.chartCurrentTimeframe) els.chartCurrentTimeframe.textContent = state.chartTimeframe;
  if (els.chartCurrentType) els.chartCurrentType.textContent = state.chartType === "line" ? "Line" : "Candlestick";
  if (els.chartCurrentPrice) els.chartCurrentPrice.textContent = payload?.current_price ? fixed(payload.current_price) : "-";
  if (els.chartStatusList) {
    const watcher = getChartWatcher(payload?.symbol || state.chartSymbol);
    els.chartStatusList.innerHTML = `
      <article class="analysis-item neutral"><p>${payload?.connection_error || `Showing ${payload?.symbol || state.chartSymbol.toUpperCase()} on ${state.chartTimeframe}.`}</p></article>
      ${watcher ? `<article class="analysis-item neutral"><p>Watcher armed from ${fixed(watcher.start_price)}. Bullish: ${watcher.bullish_target ? fixed(watcher.bullish_target) : "Off"} | Bearish: ${watcher.bearish_target ? fixed(watcher.bearish_target) : "Off"}</p></article>` : ""}
    `;
  }
  const selectedKey = normalizeInstrumentKey(payload?.symbol || state.chartSymbol);
  const matchingTrades = (state.activeTrades || []).filter((trade) => normalizeInstrumentKey(trade.symbol) === selectedKey);
  if (els.chartTradeOverlayList) {
    if (!matchingTrades.length) {
      els.chartTradeOverlayList.innerHTML = `<div class="empty-state">When you open a trade on the selected commodity, its entry, stop loss, and take profit will appear here and on the chart.</div>`;
    } else {
      els.chartTradeOverlayList.innerHTML = matchingTrades.map((trade) => `
        <article class="analysis-item ${trade.side === "buy" ? "support" : "resistance"}">
          <strong>${trade.symbol} #${trade.ticket} ${trade.side.toUpperCase()}</strong>
          <p>Entry: ${fixed(trade.entry_price)}</p>
          <p>Stop Loss: ${trade.stop_loss ? fixed(trade.stop_loss) : "Not Set"}</p>
          <p>Take Profit: ${trade.take_profit ? fixed(trade.take_profit) : "Not Set"}</p>
        </article>
      `).join("");
    }
  }
}

const CHART_ALERT_PERCENTAGES = [25, 50, 75, 90];

function saveChartWatchers() {
  localStorage.setItem("trade-observer-chart-watchers", JSON.stringify(state.chartWatchers));
}

function saveChartWatcherDrafts() {
  localStorage.setItem("trade-observer-chart-watcher-drafts", JSON.stringify(state.chartWatcherDrafts));
}

function chartWatcherKey(symbol) {
  return normalizeInstrumentKey(symbol || state.chartSymbol || "xauusd");
}

function getChartWatcher(symbol) {
  const key = chartWatcherKey(symbol);
  return state.chartWatchers[key] || null;
}

function getChartWatcherDraft(symbol) {
  const key = chartWatcherKey(symbol);
  return state.chartWatcherDrafts[key] || null;
}

function setChartWatcher(symbol, watcher) {
  state.chartWatchers[chartWatcherKey(symbol)] = watcher;
  saveChartWatchers();
}

function clearChartWatcher(symbol) {
  const key = chartWatcherKey(symbol);
  delete state.chartWatchers[key];
  delete state.chartWatcherDrafts[key];
  saveChartWatchers();
  saveChartWatcherDrafts();
}

function setChartWatcherDraft(symbol, draft) {
  state.chartWatcherDrafts[chartWatcherKey(symbol)] = draft;
  saveChartWatcherDrafts();
}

function buildChartAlertThresholds(startPrice, targetPrice) {
  const distance = Number(targetPrice) - Number(startPrice);
  return CHART_ALERT_PERCENTAGES.map((percentage) => ({
    percentage,
    price: Number(startPrice) + distance * (percentage / 100),
  }));
}

function chartAlertCrossed(currentPrice, targetPrice, thresholdPrice) {
  return Number(targetPrice) >= Number(currentPrice)
    ? Number(currentPrice) >= Number(thresholdPrice)
    : Number(currentPrice) <= Number(thresholdPrice);
}

function chartAlertProgress(startPrice, targetPrice, currentPrice) {
  const distance = Number(targetPrice) - Number(startPrice);
  if (!distance) return 100;
  const progress = ((Number(currentPrice) - Number(startPrice)) / distance) * 100;
  return Math.max(0, Math.min(progress, 100));
}

function renderChartWatcherForm(payload = null) {
  const watcher = getChartWatcher(payload?.symbol || state.chartSymbol);
  const draft = getChartWatcherDraft(payload?.symbol || state.chartSymbol);
  const bullishValue = draft?.bullish_target ?? (watcher?.bullish_target ? String(watcher.bullish_target) : "");
  const bearishValue = draft?.bearish_target ?? (watcher?.bearish_target ? String(watcher.bearish_target) : "");
  if (els.chartBullishTargetInput && document.activeElement !== els.chartBullishTargetInput) {
    els.chartBullishTargetInput.value = bullishValue;
  }
  if (els.chartBearishTargetInput && document.activeElement !== els.chartBearishTargetInput) {
    els.chartBearishTargetInput.value = bearishValue;
  }
  renderChartWatcherSummary(payload);
}

function renderChartWatcherSummary(payload = null) {
  if (!els.chartWatcherSummary) return;
  const watcher = getChartWatcher(payload?.symbol || state.chartSymbol);
  if (!watcher) {
    els.chartWatcherSummary.innerHTML = `<div class="empty-state">Enter only the bullish or bearish target you care about, then arm the watcher from the current chart price.</div>`;
    return;
  }
  const activeTargets = [];
  if (Number(watcher.bullish_target) > 0) {
    activeTargets.push(`
      <article class="analysis-item support">
        <strong>Bullish Target ${fixed(watcher.bullish_target)}</strong>
        <p>Start price: ${fixed(watcher.start_price)} | Progress: ${fixed(chartAlertProgress(watcher.start_price, watcher.bullish_target, payload?.current_price || watcher.start_price), 1)}%</p>
        <p>Triggered checkpoints: ${(watcher.triggered?.bullish || []).length ? watcher.triggered.bullish.join("%, ") + "%" : "None yet"}</p>
        <p>Update the value above and save again to adjust this watcher.</p>
      </article>
    `);
  }
  if (Number(watcher.bearish_target) > 0) {
    activeTargets.push(`
      <article class="analysis-item resistance">
        <strong>Bearish Target ${fixed(watcher.bearish_target)}</strong>
        <p>Start price: ${fixed(watcher.start_price)} | Progress: ${fixed(chartAlertProgress(watcher.start_price, watcher.bearish_target, payload?.current_price || watcher.start_price), 1)}%</p>
        <p>Triggered checkpoints: ${(watcher.triggered?.bearish || []).length ? watcher.triggered.bearish.join("%, ") + "%" : "None yet"}</p>
        <p>Update the value above and save again to adjust this watcher.</p>
      </article>
    `);
  }
  els.chartWatcherSummary.innerHTML = activeTargets.join("") || `<div class="empty-state">No active bullish or bearish target is armed for this symbol.</div>`;
}

function armChartWatcherFromInputs() {
  const bullishRaw = (els.chartBullishTargetInput?.value || "").trim();
  const bearishRaw = (els.chartBearishTargetInput?.value || "").trim();
  const bullishTarget = Number(bullishRaw || 0);
  const bearishTarget = Number(bearishRaw || 0);
  if (!(bullishTarget > 0) && !(bearishTarget > 0)) {
    showToast("No Targets Entered", "Enter a bullish target, a bearish target, or both before arming alerts.", "warn");
    return;
  }
  const currentPrice = Number(state.charts?.current_price || 0);
  if (!(currentPrice > 0)) {
    showToast("No Live Price", "Load the chart first so the watcher can arm from the current market price.", "warn");
    return;
  }
  if (bullishTarget > 0 && bullishTarget <= currentPrice) {
    showToast("Bullish Target Invalid", "A bullish target should be above the current chart price.", "warn");
    return;
  }
  if (bearishTarget > 0 && bearishTarget >= currentPrice) {
    showToast("Bearish Target Invalid", "A bearish target should be below the current chart price.", "warn");
    return;
  }
  const symbol = state.charts?.symbol || state.chartSymbol.toUpperCase();
  const nextWatcher = {
    symbol,
    start_price: currentPrice,
    bullish_target: bullishTarget > 0 ? bullishTarget : 0,
    bearish_target: bearishTarget > 0 ? bearishTarget : 0,
    armed_at: new Date().toISOString(),
    triggered: {
      bullish: [],
      bearish: [],
    },
    zone_hit: {
      bullish: false,
      bearish: false,
    },
  };
  setChartWatcher(symbol, nextWatcher);
  setChartWatcherDraft(symbol, {
    bullish_target: bullishRaw,
    bearish_target: bearishRaw,
  });
  renderChartWatcherForm(state.charts);
  showToast("Price Watcher Saved", `${symbol} alerts are now armed from ${fixed(currentPrice)} and can be updated anytime.`, "success");
  drawChartsPage(state.charts || { candles: [], symbol, current_price: currentPrice });
}

function buildChartWatcherAlert(direction, watcher, currentPrice, percentage = null) {
  const bullish = direction === "bullish";
  const targetPrice = bullish ? watcher.bullish_target : watcher.bearish_target;
  const eventType = percentage === null ? "chart_target_hit" : "chart_target_progress";
  return {
    ts: new Date().toISOString(),
    event_type: eventType,
    severity: bullish ? "success" : "warn",
    ticket: null,
    message: percentage === null
      ? `${watcher.symbol} reached your ${direction} target at ${fixed(currentPrice)}. Target: ${fixed(targetPrice)}.`
      : `${watcher.symbol} ${direction} move reached ${percentage}% of target at ${fixed(currentPrice)}. Target: ${fixed(targetPrice)}.`,
    payload: {
      symbol: watcher.symbol,
      direction,
      percentage,
      current_price: currentPrice,
      target_price: targetPrice,
      start_price: watcher.start_price,
      test: false,
    },
  };
}

function evaluateChartWatcher(payload) {
  const watcher = getChartWatcher(payload?.symbol || state.chartSymbol);
  if (!watcher || !(Number(payload?.current_price) > 0)) return;
  const currentPrice = Number(payload.current_price);
  let changed = false;

  const checkDirection = (direction, targetPrice) => {
    if (!(Number(targetPrice) > 0)) return;
    const triggered = watcher.triggered?.[direction] || [];
    buildChartAlertThresholds(watcher.start_price, targetPrice).forEach((threshold) => {
      if (triggered.includes(threshold.percentage)) return;
      if (chartAlertCrossed(currentPrice, targetPrice, threshold.price)) {
        triggered.push(threshold.percentage);
        changed = true;
        const alert = buildChartWatcherAlert(direction, watcher, currentPrice, threshold.percentage);
        addLocalAlert(alert, `chart|${watcher.symbol}|${direction}|${threshold.percentage}|${watcher.armed_at}`);
      }
    });
    watcher.triggered[direction] = triggered;
    if (!watcher.zone_hit?.[direction] && chartAlertCrossed(currentPrice, targetPrice, targetPrice)) {
      watcher.zone_hit[direction] = true;
      changed = true;
      const alert = buildChartWatcherAlert(direction, watcher, currentPrice, null);
      addLocalAlert(alert, `chart|${watcher.symbol}|${direction}|target|${watcher.armed_at}`);
    }
  };

  checkDirection("bullish", watcher.bullish_target);
  checkDirection("bearish", watcher.bearish_target);

  if (changed) {
    setChartWatcher(watcher.symbol, watcher);
    renderChartWatcherSummary(payload);
  }
}

function drawChartsPage(payload) {
  if (!chartsCtx || !els.chartsCanvas) return;
  const canvas = els.chartsCanvas;
  const fullscreenTarget = els.chartStage;
  const fullscreenActive = Boolean(fullscreenTarget && document.fullscreenElement === fullscreenTarget);
  const width = Math.max(fullscreenActive ? 1200 : 900, canvas.clientWidth || canvas.width);
  const height = fullscreenActive
    ? Math.max(680, window.innerHeight - 140)
    : Math.max(560, Math.round(width * 0.56));
  canvas.width = width;
  canvas.height = height;
  chartsCtx.clearRect(0, 0, width, height);
  chartsCtx.fillStyle = getComputedStyle(document.body).getPropertyValue("--panel-soft");
  chartsCtx.fillRect(0, 0, width, height);

  const candles = visibleChartCandles(payload?.candles || []);
  if (!candles.length) {
    chartsCtx.fillStyle = getComputedStyle(document.body).getPropertyValue("--muted");
    chartsCtx.font = "20px Aptos";
    chartsCtx.fillText(payload?.connection_error || "Waiting for chart candles...", 28, height / 2);
    renderChartsSummary(payload || {});
    return;
  }

  const padding = { top: 24, right: 126, bottom: 30, left: 60 };
  const highs = candles.map((candle) => Number(candle.high));
  const lows = candles.map((candle) => Number(candle.low));
  const closes = candles.map((candle) => Number(candle.close));
  const maxPrice = Math.max(...highs);
  const minPrice = Math.min(...lows);
  const spread = Math.max(maxPrice - minPrice, 0.01);
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const step = plotWidth / candles.length;
  const candleWidth = Math.max(4, step * 0.72);
  const priceToY = (price) => padding.top + (maxPrice - Number(price)) / spread * plotHeight;

  chartsCtx.strokeStyle = "rgba(255,255,255,0.06)";
  chartsCtx.lineWidth = 1;
  for (let row = 0; row <= 4; row += 1) {
    const y = padding.top + (plotHeight / 4) * row;
    chartsCtx.beginPath();
    chartsCtx.moveTo(padding.left, y);
    chartsCtx.lineTo(width - padding.right + 8, y);
    chartsCtx.stroke();
  }

  if (state.chartType === "line") {
    chartsCtx.strokeStyle = getComputedStyle(document.body).getPropertyValue("--accent-2").trim();
    chartsCtx.lineWidth = 2.2;
    chartsCtx.beginPath();
    closes.forEach((close, index) => {
      const x = padding.left + index * step + step / 2;
      const y = priceToY(close);
      if (index === 0) chartsCtx.moveTo(x, y);
      else chartsCtx.lineTo(x, y);
    });
    chartsCtx.stroke();
  } else {
    candles.forEach((candle, index) => {
      const x = padding.left + index * step + step / 2;
      const open = Number(candle.open);
      const close = Number(candle.close);
      const high = Number(candle.high);
      const low = Number(candle.low);
      const bullish = close >= open;
      const color = bullish
        ? getComputedStyle(document.body).getPropertyValue("--accent-2").trim()
        : getComputedStyle(document.body).getPropertyValue("--danger").trim();
      chartsCtx.strokeStyle = color;
      chartsCtx.beginPath();
      chartsCtx.moveTo(x, priceToY(high));
      chartsCtx.lineTo(x, priceToY(low));
      chartsCtx.stroke();
      chartsCtx.fillStyle = color;
      chartsCtx.fillRect(x - candleWidth / 2, Math.min(priceToY(open), priceToY(close)), candleWidth, Math.max(2, Math.abs(priceToY(close) - priceToY(open))));
    });
  }

  const selectedKey = normalizeInstrumentKey(payload?.symbol || state.chartSymbol);
  const matchingTrades = (state.activeTrades || []).filter((trade) => normalizeInstrumentKey(trade.symbol) === selectedKey);
  const watcher = getChartWatcher(payload?.symbol || state.chartSymbol);
  const drawLevel = (price, color, label) => {
    if (!price) return;
    const y = priceToY(price);
    chartsCtx.strokeStyle = color;
    chartsCtx.setLineDash([8, 6]);
    chartsCtx.beginPath();
    chartsCtx.moveTo(padding.left, y);
    chartsCtx.lineTo(width - padding.right + 8, y);
    chartsCtx.stroke();
    chartsCtx.setLineDash([]);
    chartsCtx.fillStyle = color;
    chartsCtx.fillRect(padding.left + 8, y - 12, 124, 22);
    chartsCtx.fillStyle = "#04131c";
    chartsCtx.font = "12px Aptos";
    chartsCtx.fillText(label, padding.left + 14, y + 4);
  };
  const drawWatcherLine = (price, color, label, opacity = 1) => {
    if (!price) return;
    const y = priceToY(price);
    const stroke = color.replace("0.95", String(opacity));
    chartsCtx.strokeStyle = stroke;
    chartsCtx.lineWidth = opacity >= 0.9 ? 2.4 : 1.2;
    chartsCtx.setLineDash(opacity >= 0.9 ? [10, 6] : [4, 8]);
    chartsCtx.beginPath();
    chartsCtx.moveTo(padding.left, y);
    chartsCtx.lineTo(width - padding.right + 8, y);
    chartsCtx.stroke();
    chartsCtx.setLineDash([]);
    chartsCtx.fillStyle = color.replace("0.95", String(Math.max(opacity, 0.75)));
    chartsCtx.fillRect(width - padding.right - 54, y - 12, 148, 22);
    chartsCtx.fillStyle = "#04131c";
    chartsCtx.font = "12px Aptos";
    chartsCtx.fillText(label, width - padding.right - 46, y + 4);
  };
  matchingTrades.forEach((trade) => {
    drawLevel(trade.entry_price, "rgba(105, 211, 255, 0.95)", `ENTRY ${fixed(trade.entry_price)}`);
    if (Number(trade.stop_loss) > 0) drawLevel(trade.stop_loss, "rgba(255, 107, 122, 0.95)", `SL ${fixed(trade.stop_loss)}`);
    if (Number(trade.take_profit) > 0) drawLevel(trade.take_profit, "rgba(75, 240, 179, 0.95)", `TP ${fixed(trade.take_profit)}`);
  });
  if (watcher) {
    if (Number(watcher.bullish_target) > 0) {
      buildChartAlertThresholds(watcher.start_price, watcher.bullish_target).forEach((threshold) => {
        drawWatcherLine(threshold.price, "rgba(75, 240, 179, 0.95)", `BULL ${threshold.percentage}% ${fixed(threshold.price)}`, 0.36);
      });
      drawWatcherLine(watcher.bullish_target, "rgba(75, 240, 179, 0.95)", `BULL TARGET ${fixed(watcher.bullish_target)}`, 0.95);
    }
    if (Number(watcher.bearish_target) > 0) {
      buildChartAlertThresholds(watcher.start_price, watcher.bearish_target).forEach((threshold) => {
        drawWatcherLine(threshold.price, "rgba(255, 107, 122, 0.95)", `BEAR ${threshold.percentage}% ${fixed(threshold.price)}`, 0.36);
      });
      drawWatcherLine(watcher.bearish_target, "rgba(255, 107, 122, 0.95)", `BEAR TARGET ${fixed(watcher.bearish_target)}`, 0.95);
    }
  }

  const livePrice = Number(payload?.current_price || closes.at(-1) || 0);
  const liveY = priceToY(livePrice);
  chartsCtx.strokeStyle = "rgba(105, 211, 255, 0.88)";
  chartsCtx.beginPath();
  chartsCtx.moveTo(padding.left, liveY);
  chartsCtx.lineTo(width - padding.right + 8, liveY);
  chartsCtx.stroke();
  chartsCtx.fillStyle = "rgba(105, 211, 255, 0.95)";
  chartsCtx.fillRect(width - padding.right + 12, liveY - 12, 84, 22);
  chartsCtx.fillStyle = "#04131c";
  chartsCtx.fillText(fixed(livePrice), width - padding.right + 20, liveY + 4);

  const labels = Array.from({ length: 6 }, (_, index) => maxPrice - (spread / 5) * index);
  chartsCtx.fillStyle = getComputedStyle(document.body).getPropertyValue("--text");
  chartsCtx.font = "12px Cascadia Mono";
  labels.forEach((price) => {
    chartsCtx.fillText(fixed(price), width - padding.right + 18, priceToY(price) + 4);
  });
  chartsCtx.fillStyle = getComputedStyle(document.body).getPropertyValue("--muted");
  chartsCtx.fillText(`${payload?.symbol || state.chartSymbol.toUpperCase()} ${state.chartTimeframe} · Zoom ${state.chartZoomLevel + 1}`, padding.left, 18);
  renderChartsSummary(payload);
  renderChartWatcherForm(payload);
}

async function refreshChartsPage() {
  try {
    const payload = await fetchJson(`/api/chart-data?symbol=${encodeURIComponent(state.chartSymbol)}&timeframe=${encodeURIComponent(state.chartTimeframe)}`);
    state.charts = payload;
    evaluateChartWatcher(payload);
    drawChartsPage(payload);
  } catch (error) {
    const payload = { connection_error: "Could not load chart data from the local server.", candles: [], symbol: state.chartSymbol.toUpperCase(), current_price: 0 };
    state.charts = payload;
    drawChartsPage(payload);
  }
}

function saveConsolidationAlertState() {
  localStorage.setItem("trade-observer-consolidation-alert-state", JSON.stringify(state.consolidationAlertState));
}

function consolidationAlertKey(symbol, timeframe) {
  return `${normalizeInstrumentKey(symbol)}|${String(timeframe || "M5").toUpperCase()}`;
}

function renderConsolidation(payload) {
  state.consolidation = payload;
  if (els.consolidationResolvedSymbol) els.consolidationResolvedSymbol.textContent = payload?.symbol || "-";
  if (els.consolidationCurrentTimeframe) els.consolidationCurrentTimeframe.textContent = payload?.timeframe || state.consolidationTimeframe;
  if (els.consolidationCurrentPrice) els.consolidationCurrentPrice.textContent = payload?.current_price ? fixed(payload.current_price) : "-";
  if (els.consolidationRangeSize) els.consolidationRangeSize.textContent = payload?.range?.size ? fixed(payload.range.size) : "-";
  if (els.consolidationStatusBadge) {
    const labels = {
      inside_range: "Inside Range",
      testing_upper: "Upper Zone",
      testing_lower: "Lower Zone",
      breakout_up: "Breakout Up",
      breakout_down: "Breakout Down",
      not_consolidating: "No Consolidation",
      unavailable: "Unavailable",
    };
    els.consolidationStatusBadge.textContent = labels[payload?.status] || "-";
    els.consolidationStatusBadge.className = payload?.status === "testing_upper" || payload?.status === "breakout_up"
      ? "positive"
      : payload?.status === "testing_lower" || payload?.status === "breakout_down" || payload?.status === "not_consolidating"
        ? "negative"
        : "";
  }
  if (els.consolidationRangeList) {
    if (!payload?.range) {
      els.consolidationRangeList.innerHTML = `<div class="empty-state">${payload?.message || "No consolidation range is available right now."}</div>`;
    } else {
      els.consolidationRangeList.innerHTML = `
        <article class="analysis-item support">
          <strong>Upper Rejection Zone</strong>
          <p>${fixed(payload.upper_zone?.low)} to ${fixed(payload.upper_zone?.high)}</p>
        </article>
        <article class="analysis-item resistance">
          <strong>Lower Rejection Zone</strong>
          <p>${fixed(payload.lower_zone?.low)} to ${fixed(payload.lower_zone?.high)}</p>
        </article>
        <article class="analysis-item neutral">
          <strong>Full Range</strong>
          <p>${fixed(payload.range.low)} to ${fixed(payload.range.high)} | Mid ${fixed(payload.range.mid)}</p>
        </article>
      `;
    }
  }
  if (els.consolidationStatusList) {
    const items = Array.isArray(payload?.signals) ? payload.signals : [];
    els.consolidationStatusList.innerHTML = `
      <article class="analysis-item neutral">
        <strong>Status</strong>
        <p>${payload?.message || "Waiting for consolidation status."}</p>
      </article>
      ${items.map((item) => `
        <article class="analysis-item ${item.type?.includes("upper") || item.type?.includes("up") ? "support" : item.type?.includes("lower") || item.type?.includes("down") || item.type?.includes("not") ? "resistance" : "neutral"}">
          <strong>${item.type.replaceAll("_", " ")}</strong>
          <p>${item.message}</p>
        </article>
      `).join("")}
    `;
  }
}

function drawConsolidationChart(payload) {
  if (!consolidationCtx || !els.consolidationCanvas) return;
  const canvas = els.consolidationCanvas;
  const width = Math.max(900, canvas.clientWidth || canvas.width);
  const height = Math.max(560, Math.round(width * 0.56));
  canvas.width = width;
  canvas.height = height;
  consolidationCtx.clearRect(0, 0, width, height);
  consolidationCtx.fillStyle = getComputedStyle(document.body).getPropertyValue("--panel-soft");
  consolidationCtx.fillRect(0, 0, width, height);
  const candles = payload?.candles || [];
  if (!candles.length) {
    consolidationCtx.fillStyle = getComputedStyle(document.body).getPropertyValue("--muted");
    consolidationCtx.font = "20px Aptos";
    consolidationCtx.fillText(payload?.message || payload?.connection_error || "Waiting for consolidation candles...", 28, height / 2);
    return;
  }
  const padding = { top: 24, right: 126, bottom: 30, left: 60 };
  const highs = candles.map((candle) => Number(candle.high));
  const lows = candles.map((candle) => Number(candle.low));
  const maxPrice = Math.max(...highs);
  const minPrice = Math.min(...lows);
  const spread = Math.max(maxPrice - minPrice, 0.01);
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const step = plotWidth / candles.length;
  const candleWidth = Math.max(4, step * 0.72);
  const priceToY = (price) => padding.top + (maxPrice - Number(price)) / spread * plotHeight;
  for (let row = 0; row <= 4; row += 1) {
    const y = padding.top + (plotHeight / 4) * row;
    consolidationCtx.strokeStyle = "rgba(255,255,255,0.06)";
    consolidationCtx.beginPath();
    consolidationCtx.moveTo(padding.left, y);
    consolidationCtx.lineTo(width - padding.right + 8, y);
    consolidationCtx.stroke();
  }
  candles.forEach((candle, index) => {
    const x = padding.left + index * step + step / 2;
    const open = Number(candle.open);
    const close = Number(candle.close);
    const high = Number(candle.high);
    const low = Number(candle.low);
    const bullish = close >= open;
    const color = bullish
      ? getComputedStyle(document.body).getPropertyValue("--accent-2").trim()
      : getComputedStyle(document.body).getPropertyValue("--danger").trim();
    consolidationCtx.strokeStyle = color;
    consolidationCtx.beginPath();
    consolidationCtx.moveTo(x, priceToY(high));
    consolidationCtx.lineTo(x, priceToY(low));
    consolidationCtx.stroke();
    consolidationCtx.fillStyle = color;
    consolidationCtx.fillRect(x - candleWidth / 2, Math.min(priceToY(open), priceToY(close)), candleWidth, Math.max(2, Math.abs(priceToY(close) - priceToY(open))));
  });
  const drawZone = (low, high, fill, label) => {
    if (!(Number(low) > 0) || !(Number(high) > 0)) return;
    const top = priceToY(high);
    const bottom = priceToY(low);
    consolidationCtx.fillStyle = fill;
    consolidationCtx.fillRect(padding.left, top, plotWidth, Math.max(8, bottom - top));
    consolidationCtx.fillStyle = getComputedStyle(document.body).getPropertyValue("--text");
    consolidationCtx.font = "12px Aptos";
    consolidationCtx.fillText(label, padding.left + 10, top + 16);
  };
  drawZone(payload?.upper_zone?.low, payload?.upper_zone?.high, "rgba(255, 107, 122, 0.16)", `Upper zone ${fixed(payload?.upper_zone?.low)} - ${fixed(payload?.upper_zone?.high)}`);
  drawZone(payload?.lower_zone?.low, payload?.lower_zone?.high, "rgba(75, 240, 179, 0.16)", `Lower zone ${fixed(payload?.lower_zone?.low)} - ${fixed(payload?.lower_zone?.high)}`);
  if (payload?.range) {
    const highY = priceToY(payload.range.high);
    const lowY = priceToY(payload.range.low);
    consolidationCtx.strokeStyle = "rgba(255,255,255,0.35)";
    consolidationCtx.setLineDash([8, 6]);
    consolidationCtx.beginPath();
    consolidationCtx.moveTo(padding.left, highY);
    consolidationCtx.lineTo(width - padding.right + 8, highY);
    consolidationCtx.moveTo(padding.left, lowY);
    consolidationCtx.lineTo(width - padding.right + 8, lowY);
    consolidationCtx.stroke();
    consolidationCtx.setLineDash([]);
  }
  const livePrice = Number(payload?.current_price || candles.at(-1)?.close || 0);
  const liveY = priceToY(livePrice);
  consolidationCtx.strokeStyle = "rgba(105, 211, 255, 0.88)";
  consolidationCtx.beginPath();
  consolidationCtx.moveTo(padding.left, liveY);
  consolidationCtx.lineTo(width - padding.right + 8, liveY);
  consolidationCtx.stroke();
  consolidationCtx.fillStyle = "rgba(105, 211, 255, 0.95)";
  consolidationCtx.fillRect(width - padding.right + 12, liveY - 12, 88, 22);
  consolidationCtx.fillStyle = "#04131c";
  consolidationCtx.font = "12px Cascadia Mono";
  consolidationCtx.fillText(fixed(livePrice), width - padding.right + 20, liveY + 4);
  consolidationCtx.fillStyle = getComputedStyle(document.body).getPropertyValue("--muted");
  consolidationCtx.fillText(`${payload?.symbol || state.consolidationSymbol.toUpperCase()} ${payload?.timeframe || state.consolidationTimeframe} consolidation map`, padding.left, 18);
}

function evaluateConsolidationAlerts(payload) {
  if (!payload?.symbol || !payload?.timeframe || !payload?.status) return;
  const key = consolidationAlertKey(payload.symbol, payload.timeframe);
  const previous = state.consolidationAlertState[key] || {};
  if (previous.status === payload.status) return;
  state.consolidationAlertState[key] = { status: payload.status, ts: new Date().toISOString() };
  saveConsolidationAlertState();
  const eventMap = {
    testing_upper: { event_type: "consolidation_upper_zone", severity: "success" },
    testing_lower: { event_type: "consolidation_lower_zone", severity: "warn" },
    breakout_up: { event_type: "consolidation_breakout_up", severity: "success" },
    breakout_down: { event_type: "consolidation_breakout_down", severity: "warn" },
    not_consolidating: { event_type: "consolidation_ended", severity: "warn" },
  };
  const event = eventMap[payload.status];
  if (!event) return;
  addLocalAlert(
    {
      ts: new Date().toISOString(),
      event_type: event.event_type,
      severity: event.severity,
      ticket: null,
      message: payload.message,
      payload: {
        symbol: payload.symbol,
        timeframe: payload.timeframe,
        range: payload.range,
        upper_zone: payload.upper_zone,
        lower_zone: payload.lower_zone,
      },
    },
    `consolidation|${key}|${payload.status}`
  );
}

async function refreshConsolidation() {
  try {
    const payload = await fetchJson(`/api/consolidation?symbol=${encodeURIComponent(state.consolidationSymbol)}&timeframe=${encodeURIComponent(state.consolidationTimeframe)}`);
    state.consolidation = payload;
    evaluateConsolidationAlerts(payload);
    renderConsolidation(payload);
    drawConsolidationChart(payload);
  } catch (error) {
    const payload = {
      symbol: state.consolidationSymbol.toUpperCase(),
      timeframe: state.consolidationTimeframe,
      candles: [],
      message: "Could not load consolidation data from the local server.",
      status: "unavailable",
    };
    state.consolidation = payload;
    renderConsolidation(payload);
    drawConsolidationChart(payload);
  }
}

function visibleChartCandles(candles) {
  const zoomMap = [220, 180, 140, 110, 84, 60, 40, 28];
  const count = zoomMap[Math.max(0, Math.min(state.chartZoomLevel, zoomMap.length - 1))] || 220;
  return candles.slice(-Math.min(count, candles.length));
}

function syncChartTimeframeButtons() {
  els.chartTimeframeStrip?.querySelectorAll("[data-chart-timeframe]").forEach((button) => {
    button.classList.toggle("active", button.getAttribute("data-chart-timeframe") === state.chartTimeframe);
  });
  els.chartFullscreenTimeframes?.querySelectorAll("[data-chart-timeframe-overlay]").forEach((button) => {
    button.classList.toggle("active", button.getAttribute("data-chart-timeframe-overlay") === state.chartTimeframe);
  });
}

function showChartHud() {
  if (!els.chartFullscreenHud || document.fullscreenElement !== els.chartStage) return;
  if (state.chartHudFadeTimer) clearTimeout(state.chartHudFadeTimer);
  if (state.chartHudHideTimer) clearTimeout(state.chartHudHideTimer);
  els.chartFullscreenHud.classList.remove("is-hidden", "is-faded");
  els.chartFullscreenHud.classList.add("is-visible");
  state.chartHudFadeTimer = setTimeout(() => {
    els.chartFullscreenHud?.classList.add("is-faded");
  }, 4500);
  state.chartHudHideTimer = setTimeout(() => {
    els.chartFullscreenHud?.classList.remove("is-visible", "is-faded");
    els.chartFullscreenHud?.classList.add("is-hidden");
  }, 7000);
}

function setChartTimeframe(timeframe) {
  state.chartTimeframe = timeframe || "M1";
  localStorage.setItem("trade-observer-chart-timeframe", state.chartTimeframe);
  syncChartTimeframeButtons();
  refreshChartsPage().catch(() => {});
  showChartHud();
}

function adjustChartZoom(direction) {
  const next = Math.max(0, Math.min(7, state.chartZoomLevel + direction));
  if (next === state.chartZoomLevel) return;
  state.chartZoomLevel = next;
  localStorage.setItem("trade-observer-chart-zoom", String(state.chartZoomLevel));
  if (state.charts) drawChartsPage(state.charts);
  showChartHud();
}

function renderMarkets(payload) {
  state.markets = payload;
  if (els.marketsOpenNow) {
    els.marketsOpenNow.textContent = payload?.open_sessions?.length ? payload.open_sessions.join(", ") : "No major markets open";
  }
  if (els.marketsTimezone) {
    els.marketsTimezone.textContent = payload?.timezone || "UTC";
  }
  if (els.marketsUtcNow) {
    els.marketsUtcNow.textContent = payload?.current_utc_time || "-";
  }
  if (els.marketsUpdatedAt) {
    els.marketsUpdatedAt.textContent = payload?.generated_at_utc_label || payload?.current_utc_label || "-";
  }
  if (!els.marketsGrid) return;
  const items = payload?.items || [];
  if (!items.length) {
    els.marketsGrid.innerHTML = `<div class="empty-state">Market session clocks are unavailable right now.</div>`;
    return;
  }
  const sorted = [...items].sort((a, b) => Number(a.countdown_minutes ?? Number.MAX_SAFE_INTEGER) - Number(b.countdown_minutes ?? Number.MAX_SAFE_INTEGER));
  const nextOpening = sorted.filter((item) => item.status === "closed")[0] || null;
  const nextClosing = sorted.filter((item) => item.status === "open")[0] || null;

  const { hour = 0, minute = 0, second = 0 } = payload?.clock || {};
  const secondDegrees = second * 6;
  const minuteDegrees = minute * 6 + second * 0.1;
  const hourDegrees = ((hour % 12) * 30) + (minute * 0.5);
  const clockCards = sorted.map((item) => `
    <article class="panel market-clock-card ${item.color} ${item.status}">
      <div class="market-clock-shell">
        <div class="market-clock" style="--hour-rotation:${hourDegrees}deg; --minute-rotation:${minuteDegrees}deg; --second-rotation:${secondDegrees}deg;">
          <span class="clock-hand hour"></span>
          <span class="clock-hand minute"></span>
          <span class="clock-hand second"></span>
          <span class="clock-center"></span>
          <span class="clock-mark mark-12"></span>
          <span class="clock-mark mark-3"></span>
          <span class="clock-mark mark-6"></span>
          <span class="clock-mark mark-9"></span>
        </div>
      </div>
      <p class="panel-kicker">${item.status === "open" ? "Open Now" : "Closed"}</p>
      <h3>${item.name}</h3>
      <strong class="market-countdown">${payload?.current_utc_time || "-"}</strong>
      <p>${item.countdown_label} ${item.countdown}</p>
      <div class="market-hours">
        <span>Opens: ${item.opens_at}</span>
        <span>Closes: ${item.closes_at}</span>
      </div>
    </article>
  `).join("");

  const regularCards = sorted.map((item) => `
    <article class="panel market-card ${item.color} ${item.status}">
      <p class="panel-kicker">${item.status === "open" ? "Open Now" : "Closed"}</p>
      <h3>${item.name}</h3>
      <strong class="market-countdown">${item.countdown}</strong>
      <p>${item.countdown_label}</p>
      <div class="market-hours">
        <span>Opens: ${item.opens_at}</span>
        <span>Closes: ${item.closes_at}</span>
      </div>
    </article>
  `).join("");

  const heroCards = [
    nextOpening ? `
      <article class="panel market-focus-card opening">
        <p class="panel-kicker">Upcoming Opening</p>
        <h3>${nextOpening.name}</h3>
        <strong class="market-countdown">${nextOpening.countdown}</strong>
        <p>${nextOpening.countdown_label}</p>
        <div class="market-hours">
          <span>Opens: ${nextOpening.opens_at}</span>
          <span>Closes: ${nextOpening.closes_at}</span>
        </div>
      </article>
    ` : "",
    nextClosing ? `
      <article class="panel market-focus-card closing">
        <p class="panel-kicker">Upcoming Closing</p>
        <h3>${nextClosing.name}</h3>
        <strong class="market-countdown">${nextClosing.countdown}</strong>
        <p>${nextClosing.countdown_label}</p>
        <div class="market-hours">
          <span>Opens: ${nextClosing.opens_at}</span>
          <span>Closes: ${nextClosing.closes_at}</span>
        </div>
      </article>
    ` : "",
  ].join("");

  if (state.marketsView === "clocks") {
    els.marketsGrid.innerHTML = `
      <div class="markets-focus-grid">
        ${heroCards}
      </div>
      <div class="markets-list-head">
        <p class="panel-kicker">Clock View</p>
        <h3>UTC Session Clocks</h3>
      </div>
      <div class="markets-clock-grid">
        ${clockCards}
      </div>
    `;
  } else {
    els.marketsGrid.innerHTML = `
      <div class="markets-focus-grid">
        ${heroCards}
      </div>
      <div class="markets-list-head">
        <p class="panel-kicker">All Sessions</p>
        <h3>Opening And Closing Timers</h3>
      </div>
      <div class="markets-cards-grid">
        ${regularCards}
      </div>
    `;
  }
}

function updateChartFullscreenUi() {
  if (!els.chartFullscreenButton || !els.chartStage) return;
  const active = document.fullscreenElement === els.chartStage;
  els.chartStage.classList.toggle("is-fullscreen", active);
  els.chartFullscreenButton.textContent = active ? "Exit Full Screen" : "Full Screen";
  if (!active) {
    els.chartFullscreenHud?.classList.remove("is-visible", "is-faded");
    els.chartFullscreenHud?.classList.add("is-hidden");
    if (state.chartHudFadeTimer) clearTimeout(state.chartHudFadeTimer);
    if (state.chartHudHideTimer) clearTimeout(state.chartHudHideTimer);
  } else {
    showChartHud();
  }
}

async function toggleChartFullscreen() {
  if (!els.chartStage || !document.fullscreenEnabled) {
    showToast("Fullscreen is not available in this browser.");
    return;
  }
  if (document.fullscreenElement === els.chartStage) {
    await document.exitFullscreen();
  } else {
    await els.chartStage.requestFullscreen();
  }
}

async function refreshMarkets() {
  try {
    const payload = await fetchJson("/api/markets");
    renderMarkets(payload);
  } catch (error) {
    renderMarkets({ open_sessions: [], items: [], generated_at: "" });
  }
}

function renderSecurityLogins(payload) {
  if (!els.securityLoginsBody) return;
  state.securityLogins = payload || null;
  const summary = payload?.summary || {};
  const events = Array.isArray(payload?.events) ? payload.events : [];
  const limitations = Array.isArray(payload?.limitations) ? payload.limitations : [];

  if (els.securityAuthCount) els.securityAuthCount.textContent = String(summary.authorization_events || 0);
  if (els.securityAccountCount) els.securityAccountCount.textContent = String(summary.unique_accounts || 0);
  if (els.securityIpCount) els.securityIpCount.textContent = String(summary.unique_previous_ips || 0);
  if (els.securityTerminalCount) els.securityTerminalCount.textContent = String(summary.terminals_scanned || 0);
  if (els.securityLatestEvent) {
    els.securityLatestEvent.textContent = summary.latest_event_time
      ? `Latest event ${formatUtcDateTime(summary.latest_event_time)}`
      : "No authorization events found";
  }

  if (els.securityLimitations) {
    els.securityLimitations.innerHTML = limitations.length
      ? limitations.map((item) => `<article class="analysis-item neutral"><p>${item}</p></article>`).join("")
      : `<div class="empty-state">No extra security notes were returned.</div>`;
  }

  if (els.securityScanSummary) {
    els.securityScanSummary.innerHTML = `
      <article class="analysis-item pivot">
        <strong>Logs scanned</strong>
        <p>${summary.log_files_scanned || 0} log file(s) across ${summary.terminals_scanned || 0} terminal folder(s).</p>
      </article>
      <article class="analysis-item neutral">
        <strong>Coverage window</strong>
        <p>${summary.oldest_event_time ? formatUtcDateTime(summary.oldest_event_time) : "-"} to ${summary.latest_event_time ? formatUtcDateTime(summary.latest_event_time) : "-"}</p>
      </article>
    `;
  }

  if (!events.length) {
    els.securityLoginsBody.innerHTML = `
      <tr>
        <td colspan="8">
          <div class="empty-state">No MT5 authorization entries were found in the scanned terminal logs yet.</div>
        </td>
      </tr>
    `;
    return;
  }

  els.securityLoginsBody.innerHTML = events.map((event) => `
    <tr>
      <td>${formatUtcDateTime(event.event_time)}</td>
      <td>
        <strong>${event.terminal_alias || "-"}</strong><br>
        <span class="muted-inline">${event.terminal_path || "-"}</span>
      </td>
      <td>${event.account_login || "-"}</td>
      <td>${event.server || "-"}</td>
      <td>#${event.access_point ?? "-"}</td>
      <td>${event.ping_ms ? `${fixed(event.ping_ms, 2)} ms` : "-"}</td>
      <td>${event.previous_ip || "-"}</td>
      <td>${event.previous_authorized_at ? formatUtcDateTime(event.previous_authorized_at) : "-"}</td>
    </tr>
  `).join("");
}

async function refreshSecurityLogins() {
  if (!els.securityLoginsBody) return;
  try {
    const payload = await fetchJson("/api/security-logins");
    renderSecurityLogins(payload);
  } catch (error) {
    renderSecurityLogins({ events: [], summary: {}, limitations: [] });
    els.securityLoginsBody.innerHTML = `
      <tr>
        <td colspan="8">
          <div class="empty-state">Could not load MT5 login history from the local server.</div>
        </td>
      </tr>
    `;
  }
}

function isNegativeAlert(alert) {
  return ["warn", "danger"].includes(alert.severity);
}

function alarmTitleFor(eventType) {
  const map = {
    entry: "Trade Started",
    close: "Trade Closed",
    analysis_buy_confirmed: "Analysis Buy Now",
    analysis_break_even_prompt: "Analysis Break-Even Prompt",
    analysis_trailing_prompt: "Analysis Trail-Stop Prompt",
    liquidity_sweep_detected: "Liquidity Sweep Detected",
    account_switched: "Trading Account Switched",
    m5_direction_shift: "M5 Direction Shift",
    consolidation_upper_zone: "Upper Consolidation Zone",
    consolidation_lower_zone: "Lower Consolidation Zone",
    consolidation_breakout_up: "Consolidation Breakout Up",
    consolidation_breakout_down: "Consolidation Breakout Down",
    consolidation_ended: "Consolidation Ended",
    chart_target_progress: "Chart Target Progress",
    chart_target_hit: "Chart Target Reached",
    orl_pre_close_alert: "ORL Pre-Close Alert",
    orl_range_captured: "ORL Range Captured",
    orl_manipulation_confirmed: "ORL Manipulation Confirmed",
    orl_breakout_detected: "ORL Breakout Detected",
    orl_signal_detected: "ORL Signal Detected",
    closed_take_profit: "Take Profit Hit",
    take_profit_reached: "Take Profit Reached",
    take_profit_updated: "Take Profit Updated",
    approaching_stop: "Stop Loss Approaching",
    stop_loss_hit: "Stop Loss Hit",
    stop_loss_updated: "Stop Loss Updated",
    capital_warning: "Capital Warning",
    account_blown: "Account Blown",
  };
  return map[eventType] || eventType.replaceAll("_", " ");
}

function alarmKickerFor(alert) {
  return isNegativeAlert(alert) ? "Risk Alert" : "Trade Alert";
}

function buildTestAlert(eventType) {
  const messages = {
    entry: "Test only: this simulates a trade entry alarm.",
    close: "Test only: this simulates a trade close alarm. 3 trades closed in this batch.",
    analysis_buy_confirmed: "Test only: this simulates a confirmed analysis buy-now alert.",
    analysis_break_even_prompt: "Test only: this simulates a break-even management prompt.",
    analysis_trailing_prompt: "Test only: this simulates a trailing-stop management prompt.",
    liquidity_sweep_detected: "Test only: this simulates a live engineered liquidity sweep alert.",
    account_switched: "Test only: this simulates a trading account switch alarm.",
    m5_direction_shift: "Test only: this simulates an M5 bullish direction shift alert.",
    closed_take_profit: "Test only: this simulates a take profit close alarm.",
    take_profit_reached: "Test only: this simulates a take profit reached alarm.",
    take_profit_updated: "Test only: this simulates a take profit update alarm.",
    approaching_stop: "Test only: this simulates a stop loss warning alarm.",
    stop_loss_hit: "Test only: this simulates a stop loss hit alarm.",
    stop_loss_updated: "Test only: this simulates a stop loss update alarm.",
    capital_warning: "Test only: this simulates a capital warning alarm.",
    account_blown: "Test only: this simulates an account blown alarm.",
  };
  return {
    ts: new Date().toISOString(),
    event_type: eventType,
    severity: ["approaching_stop", "stop_loss_hit", "stop_loss_updated", "capital_warning", "account_blown"].includes(eventType)
      ? "warn"
      : "success",
    ticket: 999999,
    message: messages[eventType] || "Test only: this simulates an alert.",
    payload: eventType === "close" ? { closed_count: 3 } : {},
  };
}

function renderAlerts(alerts) {
  if (!els.alertsList) return;
  if (!alerts.length) {
    els.alertsList.innerHTML = `<div class="empty-state">Alerts will appear here when trades open, close, hit TP/SL, or account-risk warnings trigger.</div>`;
    return;
  }

  els.alertsList.innerHTML = alerts.map((alert) => `
    <article class="alert-item ${alert.severity}">
      <div class="alert-top">
        <span>${alert.event_type.replaceAll("_", " ")}</span>
        <span>${formatDateTime(alert.ts)}</span>
      </div>
      <strong>${alert.message}</strong>
      ${alert.payload?.closed_count > 1 ? `<div class="alert-top"><span>Closed trades</span><span>${alert.payload.closed_count}</span></div>` : ""}
      <div class="alert-top">
        <span>${alert.ticket ? `Trade #${alert.ticket}` : "Account-wide"}</span>
        <span>${alert.severity}</span>
      </div>
    </article>
  `).join("");
}

function mergeAlerts(remoteAlerts) {
  return [...state.localAlerts, ...remoteAlerts]
    .sort((left, right) => new Date(right.ts).getTime() - new Date(left.ts).getTime())
    .slice(0, 20);
}

function renderTradeCards(trades, account) {
  if (!els.tradeCards) return;
  const centMode = currentConnectedAccountIsCent();
  if (!trades.length) {
    els.tradeCards.innerHTML = `<div class="empty-state">No open trades detected yet. Once MetaTrader exposes an active position, it will appear here with live metrics.</div>`;
    return;
  }

  const estimateTradeOutcome = (trade, targetPrice) => {
    const rawSymbol = String(trade.symbol || "").toUpperCase();
    const marketKey = rawSymbol.startsWith("XAUUSD")
      ? "XAUUSD"
      : rawSymbol.startsWith("EURUSD")
        ? "EURUSD"
        : rawSymbol.startsWith("GBPUSD")
          ? "GBPUSD"
          : rawSymbol.startsWith("USDJPY")
            ? "USDJPY"
            : rawSymbol.startsWith("BTCUSD")
              ? "BTCUSD"
              : "XAUUSD";
    const market = calculatorPresets[marketKey] || calculatorPresets.XAUUSD;
    const entry = Number(trade.entry_price || 0);
    const exit = Number(targetPrice || 0);
    const volume = Number(trade.volume || 0);
    if (!Number.isFinite(entry) || !Number.isFinite(exit) || !Number.isFinite(volume) || volume <= 0) return null;
    const movement = trade.side === "buy" ? exit - entry : entry - exit;
    const amount = movement * volume * market.contractSize;
    return Number.isFinite(amount) ? amount : null;
  };

  els.tradeCards.innerHTML = trades.map((trade) => `
    <article class="trade-card ${trade.side}">
      <header>
        <div>
          <p class="trade-title">${trade.symbol} #${trade.ticket}</p>
          <small>Entered ${relativeTime(trade.seconds_open)}</small>
        </div>
        <span class="side-badge ${trade.side}">${trade.side}</span>
      </header>
      <div class="direction-banner ${trade.side}">
        <div>
          <span>Trade Direction</span>
          <strong>${trade.side.toUpperCase()}</strong>
        </div>
        <strong>${trade.side === "buy" ? "Long Bias" : "Short Bias"}</strong>
      </div>
      ${(() => {
        const tpAmount = Number(trade.take_profit) > 0 ? estimateTradeOutcome(trade, trade.take_profit) : null;
        const slAmount = Number(trade.stop_loss) > 0 ? estimateTradeOutcome(trade, trade.stop_loss) : null;
        const pipValue = Number(trade.pips || 0);
        const pipTone = pipValue >= 0 ? "positive" : "negative";
        const pipText = `${pipValue >= 0 ? "+" : ""}${fixed(pipValue, 1)} pips`;
        return `
          <div class="trade-price-band">
            <div class="price-chip pips ${pipTone}">
              <span>Live Pips</span>
              <strong>${pipText}</strong>
              <small>${pipValue >= 0 ? "Currently in profit" : "Currently in drawdown"}</small>
            </div>
            <div class="price-chip tp">
              <span>Take Profit</span>
              <strong>${trade.take_profit ? fixed(trade.take_profit) : "Not Set"}</strong>
              <small>${tpAmount == null ? "Amount unavailable" : displayMoney(tpAmount, { centMode })}</small>
            </div>
            <div class="price-chip sl">
              <span>Stop Loss</span>
              <strong>${trade.stop_loss ? fixed(trade.stop_loss) : "Not Set"}</strong>
              <small>${slAmount == null ? "Amount unavailable" : displayMoney(slAmount, { centMode })}</small>
            </div>
          </div>
        `;
      })()}
      <div class="metrics">
        <div class="metric"><span>Direction</span><strong>${trade.side.toUpperCase()}</strong></div>
        <div class="metric"><span>Lot Size</span><strong>${fixed(trade.volume, 2)}</strong></div>
        <div class="metric"><span>Opening Price</span><strong>${fixed(trade.entry_price)}</strong></div>
        <div class="metric"><span>Current / Closing Price</span><strong>${fixed(trade.current_price)}</strong></div>
        <div class="metric"><span>Current Pips</span><strong>${trade.pips >= 0 ? "+" : ""}${fixed(trade.pips, 1)} pips</strong></div>
        <div class="metric"><span>Trade Profit</span><strong class="${trade.profit >= 0 ? "positive" : "negative"}">${displayMoney(trade.profit, { centMode })}</strong></div>
        <div class="metric"><span>Balance / Equity Now</span><strong>${displayMoney(account.balance, { centMode })} / ${displayMoney(account.equity, { centMode })}</strong></div>
        <div class="metric"><span>Time Entered</span><strong>${formatDateTime(trade.open_time)}</strong></div>
        <div class="metric"><span>Time Out</span><strong>Open</strong></div>
      </div>
      <div class="trade-card-actions">
        <button class="theme-button danger-button" type="button" data-close-trade="${trade.ticket}">Close Trade</button>
      </div>
    </article>
  `).join("");

  els.tradeCards.querySelectorAll("[data-close-trade]").forEach((button) => {
    button.addEventListener("click", async () => {
      const ticket = Number(button.getAttribute("data-close-trade"));
      if (!ticket) return;
      const confirmed = window.confirm(`Close trade #${ticket} at market now?`);
      if (!confirmed) return;
      button.disabled = true;
      button.textContent = "Closing...";
      try {
        const response = await postJson("/api/trade/close", { ticket });
        showToast("Close Request Sent", response.message || `Trade ${ticket} close request sent.`, "success");
        await refreshState();
        await refreshJournal();
      } catch (error) {
        showToast("Close Failed", error.message || `Could not close trade ${ticket}.`, "warn");
      } finally {
        button.disabled = false;
        button.textContent = "Close Trade";
      }
    });
  });
}

function renderPendingOrderCards(orders) {
  if (!els.pendingOrderCards) return;
  if (!orders.length) {
    els.pendingOrderCards.innerHTML = `<div class="empty-state">No pending orders detected yet. Limit and stop orders will appear here once MetaTrader exposes them.</div>`;
    return;
  }

  els.pendingOrderCards.innerHTML = orders.map((order) => `
    <article class="trade-card ${order.side}">
      <header>
        <div>
          <p class="trade-title">${order.symbol} #${order.ticket}</p>
          <small>Placed ${relativeTime(order.seconds_open)}</small>
        </div>
        <span class="side-badge ${order.side}">${order.order_type}</span>
      </header>
      <div class="direction-banner ${order.side}">
        <div>
          <span>Order Direction</span>
          <strong>${order.side.toUpperCase()}</strong>
        </div>
        <strong>${order.order_type}</strong>
      </div>
      <div class="trade-price-band">
        <div class="price-chip tp">
          <span>Trigger Price</span>
          <strong>${order.trigger_price ? fixed(order.trigger_price) : "Not Set"}</strong>
          <small>Current market ${order.current_price ? fixed(order.current_price) : "-"}</small>
        </div>
        <div class="price-chip sl">
          <span>Stop Loss</span>
          <strong>${order.stop_loss ? fixed(order.stop_loss) : "Not Set"}</strong>
          <small>Take profit ${order.take_profit ? fixed(order.take_profit) : "Not Set"}</small>
        </div>
      </div>
      <div class="metrics">
        <div class="metric"><span>Order Type</span><strong>${order.order_type}</strong></div>
        <div class="metric"><span>Lot Size</span><strong>${fixed(order.volume, 2)}</strong></div>
        <div class="metric"><span>Trigger</span><strong>${fixed(order.trigger_price)}</strong></div>
        <div class="metric"><span>Current Price</span><strong>${fixed(order.current_price)}</strong></div>
        <div class="metric"><span>Stop Limit</span><strong>${order.stop_limit_price ? fixed(order.stop_limit_price) : "None"}</strong></div>
        <div class="metric"><span>Take Profit</span><strong>${order.take_profit ? fixed(order.take_profit) : "Not Set"}</strong></div>
        <div class="metric"><span>Time Placed</span><strong>${formatDateTime(order.placed_time)}</strong></div>
        <div class="metric"><span>Expires</span><strong>${order.expiration_time ? formatDateTime(order.expiration_time) : "GTC"}</strong></div>
      </div>
    </article>
  `).join("");
}

function drawChart(points) {
  if (!els.canvas || !ctx) return;
  const width = els.canvas.width;
  const height = els.canvas.height;
  ctx.clearRect(0, 0, width, height);

  ctx.fillStyle = getComputedStyle(document.body).getPropertyValue("--panel-soft");
  ctx.fillRect(0, 0, width, height);

  if (!points.length) {
    ctx.fillStyle = getComputedStyle(document.body).getPropertyValue("--muted");
    ctx.font = "18px Aptos";
    ctx.fillText("Waiting for live price ticks...", 24, height / 2);
    return;
  }

  const values = points.map((point) => Number(point.last || point.bid || 0));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const spread = Math.max(max - min, 0.01);

  ctx.lineWidth = 2;
  ctx.strokeStyle = getComputedStyle(document.body).getPropertyValue(values.at(-1) >= values[0] ? "--accent-2" : "--danger");
  ctx.beginPath();

  values.forEach((value, index) => {
    const x = (index / Math.max(values.length - 1, 1)) * (width - 40) + 20;
    const y = height - ((value - min) / spread) * (height - 50) - 25;
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();

  const gradient = ctx.createLinearGradient(0, 0, 0, height);
  gradient.addColorStop(0, "rgba(75, 240, 179, 0.22)");
  gradient.addColorStop(1, "rgba(75, 240, 179, 0)");
  ctx.lineTo(width - 20, height - 20);
  ctx.lineTo(20, height - 20);
  ctx.closePath();
  ctx.fillStyle = gradient;
  ctx.fill();

  ctx.fillStyle = getComputedStyle(document.body).getPropertyValue("--muted");
  ctx.font = "14px Cascadia Mono";
  ctx.fillText(`High ${fixed(max)}`, 22, 24);
  ctx.fillText(`Low ${fixed(min)}`, 22, height - 16);
}

function getAudioContext() {
  if (!state.audioContext) {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return null;
    state.audioContext = new Ctx();
  }
  if (state.audioContext.state === "suspended") {
    state.audioContext.resume().catch(() => {});
  }
  return state.audioContext;
}

function renderJournal(payload) {
  const { totals, days, lot_sizes, summary, insights, symbols } = payload;
  const centMode = journalScopeIsCent();
  if (!els.totalProfitValue || !els.totalTradesValue || !els.totalWinsValue || !els.totalLossesValue || !els.journalDays) {
    return;
  }
  els.totalProfitValue.textContent = displayMoney(totals.total_profit, { centMode });
  els.totalTradesValue.textContent = totals.total_trades;
  els.totalWinsValue.textContent = totals.wins;
  els.totalLossesValue.textContent = totals.losses;
  const week = summary?.week || { total_profit: 0, trade_count: 0 };
  const month = summary?.month || { total_profit: 0, trade_count: 0 };
  const year = summary?.year || { total_profit: 0, trade_count: 0 };
  els.weeklyProfitValue.textContent = displayMoney(week.total_profit, { centMode });
  els.weeklyProfitValue.className = week.total_profit >= 0 ? "positive" : "negative";
  els.weeklyTradesMeta.textContent = `${week.trade_count} trade(s)`;
  els.monthlyProfitValue.textContent = displayMoney(month.total_profit, { centMode });
  els.monthlyProfitValue.className = month.total_profit >= 0 ? "positive" : "negative";
  els.monthlyTradesMeta.textContent = `${month.trade_count} trade(s)`;
  if (els.yearlyProfitValue) {
    els.yearlyProfitValue.textContent = displayMoney(year.total_profit, { centMode });
    els.yearlyProfitValue.className = year.total_profit >= 0 ? "positive" : "negative";
  }
  if (els.yearlyTradesMeta) {
    els.yearlyTradesMeta.textContent = `${year.trade_count} trade(s)`;
  }
  renderJournalInsights(insights);
  renderJournalSymbolOptions(symbols);

  if (els.lotFilter) {
    const currentOptions = new Set([...els.lotFilter.options].map((option) => option.value));
    lot_sizes.forEach((lot) => {
      const value = String(lot);
      if (currentOptions.has(value)) return;
      const option = document.createElement("option");
      option.value = value;
      option.textContent = fixed(lot, 2);
      els.lotFilter.append(option);
    });
  }

  if (!days.length) {
    els.journalDays.innerHTML = `<div class="empty-state">No trade records match the current filters yet.</div>`;
    return;
  }

  const visibleDays = days
    .map((dayGroup) => ({
      ...dayGroup,
      rows: dayGroup.rows.filter((row) => {
        return !state.hiddenJournalTickets.has(Number(row.ticket));
      }),
    }))
    .filter((dayGroup) => dayGroup.rows.length > 0);

  if (!visibleDays.length) {
    els.journalDays.innerHTML = `<div class="empty-state">No visible rows match the current filters.</div>`;
    return;
  }

  const visibleProfitTotal = visibleDays.reduce(
    (sum, dayGroup) => sum + dayGroup.rows.reduce((daySum, row) => daySum + Number(row.profit || 0), 0),
    0
  );
  const visibleTradeCount = visibleDays.reduce((sum, dayGroup) => sum + dayGroup.rows.length, 0);

  els.journalDays.innerHTML = `
    <div class="table-total-bar">
      <div>
        <span>Visible table total</span>
        <strong class="${visibleProfitTotal >= 0 ? "positive" : "negative"}">${displayMoney(visibleProfitTotal, { centMode })}</strong>
      </div>
      <div>
        <span>Visible trades</span>
        <strong>${visibleTradeCount}</strong>
      </div>
    </div>
  ` + visibleDays.map((dayGroup) => {
    const dayTotal = dayGroup.rows.reduce((sum, row) => sum + Number(row.profit || 0), 0);
    const startBalanceText = Number.isFinite(Number(dayGroup.start_balance))
      ? displayMoney(dayGroup.start_balance, { centMode })
      : "Unavailable";
    return `
    <section class="journal-day">
      <div class="journal-day-head">
        <div>
          <h3>${dayGroup.day}</h3>
          <p class="journal-day-meta">Balance before first trade: <strong>${startBalanceText}</strong></p>
        </div>
        <div class="journal-day-summary">
          <span>Day total</span>
          <strong class="${dayTotal >= 0 ? "positive" : "negative"}">${displayMoney(dayTotal, { centMode })}</strong>
        </div>
      </div>
      <table>
        <thead>
          <tr>
            <th>Trade ID</th>
            <th>Commodity</th>
            <th>Direction</th>
            <th>Lot</th>
            <th>Entry</th>
            <th>Close</th>
            <th>TP</th>
            <th>SL</th>
            <th>Opened</th>
            <th>Closed</th>
            <th>Profit</th>
            <th>Reason</th>
            <th>Visibility</th>
          </tr>
        </thead>
        <tbody>
          ${dayGroup.rows.map((row) => `
            <tr>
              <td data-label="Trade ID">${row.ticket}</td>
              <td data-label="Commodity">${row.symbol || "-"}</td>
              <td data-label="Direction">${row.side}</td>
              <td data-label="Lot">${fixed(row.volume, 2)}</td>
              <td data-label="Entry">${fixed(row.entry_price)}</td>
              <td data-label="Close">${row.close_price ? fixed(row.close_price) : "-"}</td>
              <td data-label="TP">${row.take_profit ? fixed(row.take_profit) : "-"}</td>
              <td data-label="SL">${row.stop_loss ? fixed(row.stop_loss) : "-"}</td>
              <td data-label="Opened">${formatDateTime(row.open_time)}</td>
              <td data-label="Closed">${formatDateTime(row.close_time)}</td>
              <td data-label="Profit" class="${row.profit >= 0 ? "positive" : "negative"}">${displayMoney(row.profit, { centMode })}</td>
              <td data-label="Reason">${(row.reason || row.status || "-").replaceAll("_", " ")}</td>
              <td data-label="Visibility"><button class="row-action-button" type="button" data-toggle-ticket="${row.ticket}">${state.hiddenJournalTickets.has(Number(row.ticket)) ? "Unhide" : "Hide"}</button></td>
            </tr>
          `).join("")}
        </tbody>
        <tfoot>
          <tr>
            <td colspan="10">Day total</td>
            <td class="${dayTotal >= 0 ? "positive" : "negative"}">${displayMoney(dayTotal, { centMode })}</td>
            <td colspan="2">${dayGroup.rows.length} trade(s)</td>
          </tr>
        </tfoot>
      </table>
    </section>
  `;
  }).join("");

  els.journalDays.querySelectorAll("[data-toggle-ticket]").forEach((button) => {
    button.addEventListener("click", () => {
      const ticket = Number(button.getAttribute("data-toggle-ticket"));
      if (state.hiddenJournalTickets.has(ticket)) state.hiddenJournalTickets.delete(ticket);
      else state.hiddenJournalTickets.add(ticket);
      refreshJournal().catch(() => {});
    });
  });
}

function renderJournalInsights(insights = {}) {
  if (els.journalInsightCards) {
    const cards = Array.isArray(insights.cards) ? insights.cards : [];
    els.journalInsightCards.innerHTML = cards.length
      ? cards.map((card) => `
        <article class="panel stat-panel insight-card ${card.tone || "neutral"}">
          <span>${card.title}</span>
          <strong>${card.value}</strong>
          <small>${card.meta || ""}</small>
        </article>
      `).join("")
      : `<div class="empty-state">Insights will appear here once enough journal data is available.</div>`;
  }

  const renderBreakdown = (target, rows, formatter) => {
    if (!target) return;
    const items = Array.isArray(rows) ? rows : [];
    target.innerHTML = items.length
      ? items.map((row) => formatter(row)).join("")
      : `<div class="empty-state">Not enough data yet for this breakdown.</div>`;
  };

  renderBreakdown(els.journalDayBreakdown, insights.day_of_week, (row) => `
    <article class="analysis-item ${row.total_profit >= 0 ? "support" : "resistance"}">
      <strong>${row.label}</strong>
      <p>Total: ${money(row.total_profit)} | Trades: ${row.count} | Win rate: ${(row.win_rate * 100).toFixed(0)}%</p>
    </article>
  `);

  renderBreakdown(els.journalTimeBreakdown, insights.time_of_day, (row) => `
    <article class="analysis-item ${row.total_profit >= 0 ? "support" : "resistance"}">
      <strong>${row.label}</strong>
      <p>Total: ${money(row.total_profit)} | Trades: ${row.count} | Avg: ${money(row.average_profit)}</p>
    </article>
  `);

  renderBreakdown(els.journalSetupBreakdown, insights.top_setups, (row) => `
    <article class="analysis-item ${row.total_profit >= 0 ? "support" : "resistance"}">
      <strong>${row.label}</strong>
      <p>Total: ${money(row.total_profit)} | Trades: ${row.count} | Win rate: ${(row.win_rate * 100).toFixed(0)}%</p>
    </article>
  `);

  renderBreakdown(els.journalIdeas, insights.ideas, (idea) => `
    <article class="analysis-item neutral">
      <strong>Insight</strong>
      <p>${idea}</p>
    </article>
  `);
}

function renderJournalSymbolOptions(symbols = []) {
  if (!els.journalSymbolOptions) return;
  const available = Array.isArray(symbols) ? symbols.filter(Boolean) : [];
  if (!available.length) {
    state.journalSelectedSymbols = [];
    localStorage.setItem("trade-observer-journal-symbols", JSON.stringify(state.journalSelectedSymbols));
    els.journalSymbolOptions.innerHTML = `<span class="empty-state">No commodities found for this Journal scope yet.</span>`;
    return;
  }
  const availableSet = new Set(available.map((item) => String(item || "").trim().toUpperCase()));
  const selected = new Set(
    (Array.isArray(state.journalSelectedSymbols) ? state.journalSelectedSymbols : [])
      .map((item) => String(item || "").trim().toUpperCase())
      .filter((item) => item && availableSet.has(item))
  );
  state.journalSelectedSymbols = [...selected];
  localStorage.setItem("trade-observer-journal-symbols", JSON.stringify(state.journalSelectedSymbols));
  els.journalSymbolOptions.innerHTML = available.map((symbol) => `
    <label class="toggle-chip deposit-account-chip journal-symbol-chip ${selected.has(symbol) ? "active" : ""}">
      <input type="checkbox" value="${symbol}" ${selected.has(symbol) ? "checked" : ""}>
      <span class="toggle-label">${symbol}</span>
    </label>
  `).join("");
  els.journalSymbolOptions.querySelectorAll('input[type="checkbox"]').forEach((input) => {
    input.addEventListener("change", () => {
      state.journalSelectedSymbols = [...els.journalSymbolOptions.querySelectorAll('input[type="checkbox"]:checked')]
        .map((item) => String(item.value || "").trim().toUpperCase())
        .filter(Boolean);
      localStorage.setItem("trade-observer-journal-symbols", JSON.stringify(state.journalSelectedSymbols));
      refreshJournal().catch(() => {});
    });
  });
}

function playBrowserAlert(eventType) {
  const audio = getAudioContext();
  if (!audio) return;
  const now = audio.currentTime;
  const presets = {
    entry: [660, 880, 1040],
    close: [700, 900, 1200],
    analysis_buy_confirmed: [988, 1244, 1568],
    analysis_break_even_prompt: [820, 1020, 1180],
    analysis_trailing_prompt: [760, 920, 1080, 1240],
    liquidity_sweep_detected: [660, 990, 770],
    account_switched: [780, 980, 1180],
    m5_direction_shift: [780, 980, 1240, 1480],
    consolidation_upper_zone: [740, 920, 1080],
    consolidation_lower_zone: [430, 380, 340],
    consolidation_breakout_up: [880, 1100, 1320],
    consolidation_breakout_down: [360, 300, 240],
    consolidation_ended: [420, 320, 220],
    chart_target_progress: [720, 900, 1080],
    chart_target_hit: [920, 1120, 1360, 1560],
    closed_take_profit: [880, 1100, 1400],
    take_profit_reached: [880, 1100, 1400],
    take_profit_updated: [920, 1100],
    approaching_stop: [420, 380],
    stop_loss_hit: [360, 280, 220],
    stop_loss_updated: [520, 640],
    capital_warning: [330, 260],
    account_blown: [520, 420, 260, 150],
  };
  const notes = presets[eventType] || [540];
  notes.forEach((freq, index) => {
    const osc = audio.createOscillator();
    const gain = audio.createGain();
    osc.type = eventType.includes("warning") || eventType.includes("stop") || eventType.includes("blown") ? "sawtooth" : "sine";
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(0.001, now + index * 0.18);
    gain.gain.exponentialRampToValueAtTime(0.08, now + index * 0.18 + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.001, now + index * 0.18 + 0.18);
    osc.connect(gain).connect(audio.destination);
    osc.start(now + index * 0.18);
    osc.stop(now + index * 0.18 + 0.2);
  });
}

function speakAnalysisDecision(alertOrEvent) {
  if (!("speechSynthesis" in window) || !window.SpeechSynthesisUtterance) return;
  const eventType = typeof alertOrEvent === "string" ? alertOrEvent : String(alertOrEvent?.event_type || "");
  const phrase = eventType === "analysis_buy_confirmed"
    ? "Buy now"
    : eventType === "analysis_break_even_prompt"
          ? "Move stop to break even"
          : eventType === "analysis_trailing_prompt"
            ? "Trail stop now"
            : "";
  if (!phrase) return;
  try {
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(phrase);
    utterance.rate = 0.92;
    utterance.pitch = 0.96;
    utterance.volume = 1;
    window.speechSynthesis.speak(utterance);
  } catch {}
}

function shouldLoopAlert(eventType) {
  return !["analysis_buy_confirmed", "analysis_break_even_prompt", "analysis_trailing_prompt"].includes(String(eventType || ""));
}

function stopAlarmLoop() {
  if (state.activeAlarmInterval) {
    clearInterval(state.activeAlarmInterval);
    state.activeAlarmInterval = null;
  }
}

function closeAlarmModal() {
  els.alarmModal.classList.add("hidden");
  els.alarmModal.setAttribute("aria-hidden", "true");
}

function shouldShowAlarmModal(alert) {
  return true;
}

function openAlarmModal(alert) {
  const negative = isNegativeAlert(alert);
  els.alarmDialog.classList.toggle("negative", negative);
  els.alarmDialog.classList.toggle("positive", !negative);
  els.alarmKicker.textContent = alarmKickerFor(alert);
  els.alarmTitle.textContent = alarmTitleFor(alert.event_type);
  els.alarmMessage.textContent = alert.message;
  els.alarmTradeMeta.textContent = alert.ticket ? `Trade #${alert.ticket}` : "Account-wide";
  els.alarmTimeMeta.textContent = formatDateTime(alert.ts);
  els.alarmModal.classList.remove("hidden");
  els.alarmModal.setAttribute("aria-hidden", "false");
}

function triggerAlert(alert, key) {
  if (state.lastAlertKey === key) return;
  state.lastAlertKey = key;
  localStorage.setItem("trade-observer-last-alert-key", key);
  state.activeAlarmKey = key;
  if (!state.notificationsEnabled) return;
  if (!isAlertTypeEnabled(alert.event_type)) return;
  if (shouldShowAlarmModal(alert)) {
    openAlarmModal(alert);
  } else {
    closeAlarmModal();
  }
  stopAlarmLoop();
  playBrowserAlert(alert.event_type);
  if (String(alert.event_type || "").startsWith("analysis_")) {
    speakAnalysisDecision(alert);
  }
  if (shouldLoopAlert(alert.event_type)) {
    state.activeAlarmInterval = setInterval(() => {
      playBrowserAlert(alert.event_type);
    }, isNegativeAlert(alert) ? 2200 : 2800);
  }
}

function addLocalAlert(alert, key) {
  const exists = state.localAlerts.some((item) => item._key === key);
  if (!exists) {
    state.localAlerts.unshift({ ...alert, _key: key });
    state.localAlerts = state.localAlerts.slice(0, 20);
  }
  triggerAlert(alert, key);
}

function maybePlayLatestAlert(alerts) {
  if (!alerts.length) return;
  const latest = alerts[0];
  const key = `${latest.ts}|${latest.event_type}|${latest.ticket || ""}`;
  triggerAlert(latest, key);
}

function hasMatchingServerAlert(recentAlerts, eventType, ticket, targetValue) {
  return recentAlerts.some((alert) => {
    if (alert.event_type !== eventType || Number(alert.ticket || 0) !== Number(ticket)) return false;
    if (eventType === "take_profit_updated") {
      return Number(alert.payload?.take_profit || 0) === Number(targetValue || 0);
    }
    if (eventType === "stop_loss_updated") {
      return Number(alert.payload?.stop_loss || 0) === Number(targetValue || 0);
    }
    return false;
  });
}

function detectTradeLevelChanges(trades, recentAlerts) {
  const nextLevels = {};

  trades.forEach((trade) => {
    const previous = state.previousTradeLevels[trade.ticket];
    nextLevels[trade.ticket] = {
      take_profit: Number(trade.take_profit || 0),
      stop_loss: Number(trade.stop_loss || 0),
    };

    if (!previous) return;

    const nextTp = Number(trade.take_profit || 0);
    const nextSl = Number(trade.stop_loss || 0);

    if (previous.take_profit !== nextTp && !hasMatchingServerAlert(recentAlerts, "take_profit_updated", trade.ticket, nextTp)) {
      const action = previous.take_profit <= 0 && nextTp > 0 ? "set" : "updated";
      addLocalAlert(
        {
          ts: new Date().toISOString(),
          event_type: "take_profit_updated",
          severity: "success",
          ticket: trade.ticket,
          message: `Trade ${trade.ticket} take profit ${action} to ${fixed(nextTp)}.`,
        },
        `local|tp|${trade.ticket}|${nextTp}`
      );
    }

    if (previous.stop_loss !== nextSl && !hasMatchingServerAlert(recentAlerts, "stop_loss_updated", trade.ticket, nextSl)) {
      const action = previous.stop_loss <= 0 && nextSl > 0 ? "set" : "updated";
      addLocalAlert(
        {
          ts: new Date().toISOString(),
          event_type: "stop_loss_updated",
          severity: nextSl > 0 ? "warn" : "info",
          ticket: trade.ticket,
          message: `Trade ${trade.ticket} stop loss ${action} to ${fixed(nextSl)}.`,
        },
        `local|sl|${trade.ticket}|${nextSl}`
      );
    }
  });

  state.previousTradeLevels = nextLevels;
}

async function fetchJson(url) {
  const response = await fetch(`${API_BASE}${url}`);
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json();
}

async function postJson(url, payload = {}) {
  const response = await fetch(`${API_BASE}${url}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json();
}

function showToast(title, body, tone = "success") {
  let toastHost = els.toastStack;
  if (!toastHost) {
    toastHost = document.querySelector("#toastStack");
  }
  if (!toastHost) {
    toastHost = document.createElement("div");
    toastHost.id = "toastStack";
    toastHost.className = "toast-stack";
    document.body.append(toastHost);
    els.toastStack = toastHost;
  }
  const toast = document.createElement("div");
  toast.className = `toast ${tone}`;
  toast.innerHTML = `
    <div class="toast-title">${title}</div>
    <div class="toast-body">${body}</div>
  `;
  toastHost.append(toast);
  setTimeout(() => {
    toast.remove();
  }, 4200);
}

function ensureStickyAccountBar() {
  let bar = document.querySelector("#stickyAccountBar");
  if (bar) return bar;
  const mainShell = document.querySelector(".main-shell");
  const hero = document.querySelector(".hero");
  if (!mainShell || !hero) return null;
  bar = document.createElement("section");
  bar.id = "stickyAccountBar";
  bar.className = "account-sticky-bar";
  bar.innerHTML = `
    <article class="account-sticky-chip">
      <span>Balance</span>
      <strong id="stickyBalanceValue">$0.00</strong>
      <small id="stickyBalanceMeta">Waiting for MT5</small>
    </article>
    <article class="account-sticky-chip">
      <span>Equity</span>
      <strong id="stickyEquityValue">$0.00</strong>
      <small id="stickyEquityMeta">Waiting for MT5</small>
    </article>
    <article class="account-sticky-chip">
      <span>Free Margin</span>
      <strong id="stickyFreeMarginValue">$0.00</strong>
      <small id="stickyAccountModeMeta">Account snapshot</small>
    </article>
  `;
  hero.insertAdjacentElement("afterend", bar);
  return bar;
}

function updateStickyAccountBar(account = state.accountSnapshot || {}) {
  const bar = ensureStickyAccountBar();
  if (!bar) return;
  const centMode = isCentAccountSnapshot(account);
  const balanceValue = bar.querySelector("#stickyBalanceValue");
  const balanceMeta = bar.querySelector("#stickyBalanceMeta");
  const equityValue = bar.querySelector("#stickyEquityValue");
  const equityMeta = bar.querySelector("#stickyEquityMeta");
  const freeMarginValue = bar.querySelector("#stickyFreeMarginValue");
  const accountModeMeta = bar.querySelector("#stickyAccountModeMeta");
  if (balanceValue) balanceValue.textContent = displayMoney(account.balance || 0, { centMode });
  if (balanceMeta) balanceMeta.textContent = `Initial ${displayMoney(account.initial_balance || account.balance || 0, { centMode })}`;
  if (equityValue) equityValue.textContent = displayMoney(account.equity || 0, { centMode });
  if (equityMeta) equityMeta.textContent = `Floating ${displayMoney((account.equity || 0) - (account.balance || 0), { centMode })}`;
  if (freeMarginValue) freeMarginValue.textContent = displayMoney(account.free_margin || 0, { centMode });
  if (accountModeMeta) {
    const leverage = Number(account.leverage || 0);
    accountModeMeta.textContent = leverage > 0 ? `Leverage 1:${leverage}` : "Account snapshot";
  }
}

function renderTerminalCards() {
  if (!els.terminalSwitchGrid) return;
  if (!state.detectedTerminals.length) {
    els.terminalSwitchGrid.innerHTML = `<div class="empty-state">No MT5 terminals were auto-detected under C:\\MT5 yet.</div>`;
    return;
  }

  els.terminalSwitchGrid.innerHTML = state.detectedTerminals.map((terminal) => {
    const active = state.selectedProfileAlias === terminal.alias;
    return `
      <article class="terminal-card ${active ? "active" : ""}">
        <div>
          <p class="panel-kicker">Terminal</p>
          <h3>${terminal.alias}</h3>
          <p class="terminal-path">${terminal.terminal_path}</p>
        </div>
        <button class="theme-button primary-button" type="button" data-terminal-connect="${terminal.alias}">Connect Here</button>
      </article>
    `;
  }).join("");

  els.terminalSwitchGrid.querySelectorAll("[data-terminal-connect]").forEach((button) => {
    button.addEventListener("click", async () => {
      const alias = button.getAttribute("data-terminal-connect") || "";
      const terminal = state.detectedTerminals.find((item) => item.alias === alias);
      if (!terminal) return;
      state.selectedProfileAlias = terminal.alias;
      renderTerminalCards();
      renderAccountProfileOptions();
      button.disabled = true;
      button.textContent = "Connecting...";
        try {
          await connectToMt5(
            {
              terminal_path: terminal.terminal_path,
              quick_alias: terminal.alias,
            },
            `${terminal.alias} is now the active MT5 terminal.`
          );
        } catch (error) {
          showToast("Connection Failed", error.message || `Could not connect to ${terminal.alias}.`, "warn");
        } finally {
          renderTerminalCards();
        }
      });
  });
}

async function loadDetectedTerminals() {
  const payload = await fetchJson("/api/terminals");
  state.detectedTerminals = Array.isArray(payload?.terminals) ? payload.terminals : [];
  if (payload?.selected_profile_alias) {
    state.selectedProfileAlias = payload.selected_profile_alias;
  }
  renderTerminalCards();
}

async function connectToMt5(payload, successMessage) {
  const result = await postJson("/api/connect", payload);
  await refreshState();
  if (!result?.connected) {
    throw new Error(result?.connection_error || "MT5 connection failed.");
  }
  await refreshJournal();
  if (successMessage) {
    showToast("MT5 Connected", successMessage, "success");
  }
  return result;
}

function renderAccountProfileOptions() {
  const currentValue = state.selectedProfileAlias || "";
  els.accountProfileSelect.innerHTML = `<option value="">Default MT5 Session</option>` + state.accountProfiles.map((profile) => {
    const groupText = profile.group ? ` (${profile.group})` : "";
    return `<option value="${profile.alias}">${profile.alias}${groupText}</option>`;
  }).join("");
  els.accountProfileSelect.value = currentValue;
}

function ensureAccountProfileCancelButton() {
  if (!els.accountProfileForm || !els.saveAccountProfileButton) return null;
  let cancelButton = document.querySelector("#cancelAccountProfileEditButton");
  if (cancelButton) return cancelButton;
  cancelButton = document.createElement("button");
  cancelButton.type = "button";
  cancelButton.id = "cancelAccountProfileEditButton";
  cancelButton.className = "theme-button hidden-page";
  cancelButton.textContent = "Cancel Edit";
  els.saveAccountProfileButton.insertAdjacentElement("beforebegin", cancelButton);
  cancelButton.addEventListener("click", () => {
    resetAccountProfileForm();
  });
  return cancelButton;
}

function renderAccountProfileFormState() {
  const editing = Boolean(state.editingAccountProfileAlias);
  if (els.saveAccountProfileButton) {
    els.saveAccountProfileButton.textContent = editing ? "Update Profile" : "Save Profile";
  }
  if (els.profileAliasInput) {
    els.profileAliasInput.readOnly = editing;
  }
  const cancelButton = ensureAccountProfileCancelButton();
  cancelButton?.classList.toggle("hidden-page", !editing);
}

function resetAccountProfileForm() {
  state.editingAccountProfileAlias = "";
  els.accountProfileForm?.reset();
  renderAccountProfileFormState();
}

function startEditingAccountProfile(alias) {
  const profile = state.accountProfiles.find((item) => item.alias === alias);
  if (!profile) return;
  state.editingAccountProfileAlias = alias;
  if (els.profileAliasInput) els.profileAliasInput.value = profile.alias || "";
  if (els.profileLoginInput) els.profileLoginInput.value = profile.login || "";
  if (els.profilePasswordInput) els.profilePasswordInput.value = profile.password || "";
  if (els.profileServerInput) els.profileServerInput.value = profile.server || "";
  if (els.profileTerminalPathInput) els.profileTerminalPathInput.value = profile.terminal_path || "";
  if (els.profileGroupInput) els.profileGroupInput.value = profile.group || "";
  renderAccountProfileFormState();
  els.profileLoginInput?.focus();
}

function renderAccountProfilesList() {
  if (!state.accountProfiles.length) {
    els.accountProfilesList.innerHTML = `<div class="empty-state">No saved account profiles yet. Add JamesANabiah and JimmyJetter here, then connect to either one from the top selector.</div>`;
    return;
  }

  els.accountProfilesList.innerHTML = state.accountProfiles.map((profile) => `
    <article class="funding-item">
      <div class="funding-item-top">
        <div>
          <strong>${profile.alias}</strong>
          <p>${profile.group || "MT5 profile"} ${profile.login ? `• Login ${profile.login}` : ""}</p>
        </div>
        <div>
          <strong>${profile.server || "Server not set"}</strong>
          <p>${profile.terminal_path || "Uses the default MT5 terminal session"}</p>
        </div>
      </div>
      <div class="account-profile-actions">
        <button class="theme-button" type="button" data-profile-edit="${profile.alias}">Edit</button>
        <button class="theme-button" type="button" data-profile-use="${profile.alias}">Use This Account</button>
        <button class="theme-button danger-button" type="button" data-profile-delete="${profile.alias}">Delete</button>
      </div>
    </article>
  `).join("");

  els.accountProfilesList.querySelectorAll("[data-profile-edit]").forEach((button) => {
    button.addEventListener("click", () => {
      const alias = button.getAttribute("data-profile-edit") || "";
      startEditingAccountProfile(alias);
    });
  });

  els.accountProfilesList.querySelectorAll("[data-profile-use]").forEach((button) => {
    button.addEventListener("click", async () => {
      const alias = button.getAttribute("data-profile-use") || "";
      state.selectedProfileAlias = alias;
      renderAccountProfileOptions();
      button.disabled = true;
      button.textContent = "Connecting...";
        try {
          await connectToMt5(
            { profile_alias: alias },
            `${alias} is now the active MT5 account.`
          );
          closeAccountsModal();
        } catch (error) {
          showToast("Connection Failed", error.message || `Could not switch to ${alias}.`, "warn");
        } finally {
          renderAccountProfilesList();
        }
      });
  });

  els.accountProfilesList.querySelectorAll("[data-profile-delete]").forEach((button) => {
    button.addEventListener("click", async () => {
      const alias = button.getAttribute("data-profile-delete") || "";
      if (!window.confirm(`Delete the saved account profile "${alias}"?`)) return;
      const payload = await postJson("/api/account-profiles/delete", { alias });
      if (state.editingAccountProfileAlias === alias) {
        resetAccountProfileForm();
      }
      hydrateAccountProfiles(payload);
      showToast("Profile Deleted", `${alias} was removed from saved accounts.`, "success");
    });
  });
}

function hydrateAccountProfiles(payload) {
  state.accountProfiles = Array.isArray(payload?.profiles) ? payload.profiles : [];
  state.selectedProfileAlias = payload?.selected_profile_alias || state.selectedProfileAlias || "";
  renderAccountProfileOptions();
  renderAccountProfilesList();
  renderAccountProfileFormState();
  renderJournalAccountScopes();
  renderDepositAccountOptions();
}

async function loadAccountProfiles() {
  const payload = await fetchJson("/api/account-profiles");
  hydrateAccountProfiles(payload);
}

function normalizeTerminalPath(value) {
  return String(value || "").trim().replaceAll("/", "\\").toLowerCase();
}

function getKnownLiveProfiles() {
  const knownLivePaths = new Set([
    normalizeTerminalPath("C:\\MT5\\JamesANabiah\\terminal64.exe"),
    normalizeTerminalPath("C:\\MT5\\SecondDemo\\terminal64.exe"),
  ]);
  return state.accountProfiles.filter((profile) => {
    const profilePath = normalizeTerminalPath(profile.terminal_path);
    const groupText = String(profile.group || "").toLowerCase();
    return knownLivePaths.has(profilePath) || groupText.includes("live");
  });
}

function renderJournalAccountScopes() {
  if (!els.journalAccountScope) return;
  const previous = state.journalAccountScope || "current";
  const options = [
    `<option value="current">Current Connected Account</option>`,
  ];
  const liveProfiles = getKnownLiveProfiles();
  if (liveProfiles.length >= 2) {
    options.push(`<option value="both_live">Both Live Accounts</option>`);
  }
  liveProfiles.forEach((profile) => {
    options.push(`<option value="profile:${profile.alias}">${profile.alias}</option>`);
  });
  els.journalAccountScope.innerHTML = options.join("");
  if ([...els.journalAccountScope.options].some((option) => option.value === previous)) {
    els.journalAccountScope.value = previous;
  } else {
    state.journalAccountScope = "current";
    els.journalAccountScope.value = "current";
  }
}

async function maybePromptStartupTerminalConnection() {
  if (state.startupTerminalPromptDone) return;
  if (state.connected) {
    state.startupTerminalPromptDone = true;
    sessionStorage.setItem("trade-observer-startup-terminal-prompt", "done");
    return;
  }
  const mainLivePath = normalizeTerminalPath("C:\\MT5\\JamesANabiah\\terminal64.exe");
  const terminal = state.detectedTerminals.find((item) => normalizeTerminalPath(item.terminal_path) === mainLivePath);
  if (!terminal) return;
  state.startupTerminalPromptDone = true;
  sessionStorage.setItem("trade-observer-startup-terminal-prompt", "done");
  const confirmed = window.confirm(`Do you want to connect to the Main Live terminal?\n\n${terminal.terminal_path}`);
  if (!confirmed) return;
  try {
    await connectToMt5(
      {
        terminal_path: terminal.terminal_path,
        quick_alias: terminal.alias,
      },
      `${terminal.alias} is now the active MT5 terminal.`
    );
  } catch (error) {
    showToast("Connection Failed", error.message || "Could not connect to the Main Live terminal.", "warn");
  }
}

function openAccountsModal() {
  els.accountsModal.classList.remove("hidden");
  els.accountsModal.setAttribute("aria-hidden", "false");
}

function closeAccountsModal() {
  els.accountsModal.classList.add("hidden");
  els.accountsModal.setAttribute("aria-hidden", "true");
}

function getSelectedDepositProfileAliases() {
  if (!els.depositAccountOptions) return [];
  return [...els.depositAccountOptions.querySelectorAll('input[type="checkbox"]:checked')]
    .map((input) => input.value)
    .filter(Boolean);
}

function renderDepositAccountOptions() {
  if (!els.depositAccountOptions) return;
  const liveProfiles = getKnownLiveProfiles();
  const selected = new Set(
    (Array.isArray(state.depositSelectedProfiles) && state.depositSelectedProfiles.length)
      ? state.depositSelectedProfiles
      : liveProfiles.map((profile) => profile.alias)
  );
  els.depositAccountOptions.innerHTML = liveProfiles.length
    ? liveProfiles.map((profile) => `
      <label class="toggle-chip deposit-account-chip">
        <input type="checkbox" value="${profile.alias}" ${selected.has(profile.alias) ? "checked" : ""}>
        <span class="toggle-label">${profile.alias}</span>
      </label>
    `).join("")
    : `<div class="empty-state">No live account profiles found yet.</div>`;
}

function applyFundingFilterVisibility() {
  if (!els.fundingFiltersPanel || !els.toggleFundingFiltersButton) return;
  els.fundingFiltersPanel.classList.toggle("hidden", !state.depositFiltersVisible);
  els.toggleFundingFiltersButton.textContent = state.depositFiltersVisible ? "Hide Filters" : "Show Filters";
  localStorage.setItem("trade-observer-deposit-filters-visible", state.depositFiltersVisible ? "on" : "off");
}

async function loadDeposits() {
  const params = new URLSearchParams();
  params.set("range", state.depositRange || "year");
  const aliases = getSelectedDepositProfileAliases();
  state.depositSelectedProfiles = aliases;
  localStorage.setItem("trade-observer-deposit-selected-profiles", JSON.stringify(aliases));
  if (aliases.length) {
    params.set("profile_aliases", aliases.join(","));
  }
  const payload = await fetchJson(`/api/deposits?${params.toString()}`);
  els.depositTotalUsd.textContent = money(payload.totals.usd);
  if (els.depositAccountsCount) {
    const selectedCount = aliases.length || getKnownLiveProfiles().length || 0;
    els.depositAccountsCount.textContent = String(selectedCount);
  }
  els.depositCount.textContent = String(payload.totals.count);
  if (els.fundingWarnings) {
    const warnings = Array.isArray(payload.warnings) ? payload.warnings : [];
    els.fundingWarnings.innerHTML = warnings.length
      ? warnings.map((warning) => `<article class="analysis-item resistance"><strong>Account Warning</strong><p>${warning}</p></article>`).join("")
      : "";
  }

  if (!payload.items.length) {
    els.fundingList.innerHTML = `<div class="empty-state">No deposit records were found in MetaTrader account history yet.</div>`;
    return;
  }

  els.fundingList.innerHTML = payload.items.map((item) => `
    <article class="funding-item">
      <div class="funding-item-top">
        <div>
          <strong>${money(item.amount_usd)}</strong>
          <p>USD deposit</p>
        </div>
        <div>
          <strong>${formatDateTime(item.time)}</strong>
          <p>${item.type} • #${item.ticket}</p>
        </div>
      </div>
      <p><strong>${item.account_alias || "MT5 Session"}</strong>${item.account_login ? ` • Login ${item.account_login}` : ""}</p>
      <p>${item.comment || "Deposit / balance funding"}</p>
    </article>
  `).join("");
}

function openFundingModal() {
  els.fundingModal.classList.remove("hidden");
  els.fundingModal.setAttribute("aria-hidden", "false");
  if (els.depositRangeFilter) {
    els.depositRangeFilter.value = state.depositRange || "year";
  }
  renderDepositAccountOptions();
  applyFundingFilterVisibility();
}

function closeFundingModal() {
  els.fundingModal.classList.add("hidden");
  els.fundingModal.setAttribute("aria-hidden", "true");
}

function applyDaySummaryFilterVisibility() {
  if (!els.daySummaryFiltersPanel || !els.toggleDaySummaryFiltersButton) return;
  els.daySummaryFiltersPanel.classList.toggle("hidden", !state.daySummaryFiltersVisible);
  els.toggleDaySummaryFiltersButton.textContent = state.daySummaryFiltersVisible ? "Hide Filters" : "Show Filters";
  localStorage.setItem("trade-observer-day-summary-filters-visible", state.daySummaryFiltersVisible ? "on" : "off");
}

function openDaySummaryModal() {
  els.daySummaryModal.classList.remove("hidden");
  els.daySummaryModal.setAttribute("aria-hidden", "false");
  if (els.daySummaryDateInput && !els.daySummaryDateInput.value) {
    els.daySummaryDateInput.value = els.dateFilter?.value || new Date().toISOString().slice(0, 10);
  }
  applyDaySummaryFilterVisibility();
}

function closeDaySummaryModal() {
  els.daySummaryModal.classList.add("hidden");
  els.daySummaryModal.setAttribute("aria-hidden", "true");
}

async function loadDaySummary() {
  const exactDate = els.daySummaryDateInput?.value || "";
  if (!exactDate) {
    throw new Error("Please select a date first.");
  }
  const params = new URLSearchParams({ exact_date: exactDate });
  const accountScope = els.journalAccountScope?.value || state.journalAccountScope || "current";
  let scopeLabel = "Current Connected Account";
  if (accountScope === "both_live") {
    const aliases = getKnownLiveProfiles().map((profile) => profile.alias);
    params.set("source_mode", "profiles");
    params.set("profile_aliases", aliases.join(","));
    scopeLabel = "Combined Live Account History";
  } else if (accountScope.startsWith("profile:")) {
    const alias = accountScope.slice("profile:".length);
    params.set("source_mode", "profiles");
    params.set("profile_aliases", alias);
    scopeLabel = alias;
  }
  const payload = await fetchJson(`/api/journal-day-summary?${params.toString()}`);
  if (els.daySummaryScopeText) {
    els.daySummaryScopeText.textContent = `Using Journal scope: ${payload.scope_label || scopeLabel}`;
  }
  const centMode = journalScopeIsCent();
  if (els.daySummaryProfitValue) {
    els.daySummaryProfitValue.textContent = displayMoney(payload.trade_profit, { centMode });
    els.daySummaryProfitValue.className = payload.trade_profit >= 0 ? "positive" : "negative";
  }
  if (els.daySummaryStartingBalance) {
    els.daySummaryStartingBalance.textContent = payload.starting_balance == null ? "Unavailable" : displayMoney(payload.starting_balance, { centMode });
  }
  if (els.daySummaryDeposits) {
    els.daySummaryDeposits.textContent = displayMoney(payload.deposits_total, { centMode });
    els.daySummaryDeposits.className = payload.deposits_total > 0 ? "positive" : "";
  }
  if (els.daySummaryEndingBalance) {
    els.daySummaryEndingBalance.textContent = payload.ending_balance_estimate == null ? "Unavailable" : displayMoney(payload.ending_balance_estimate, { centMode });
  }
  if (els.daySummaryTradeCount) {
    els.daySummaryTradeCount.textContent = String(payload.trade_count || 0);
  }
  if (els.daySummaryWinLoss) {
    els.daySummaryWinLoss.textContent = `${payload.wins || 0} / ${payload.losses || 0}`;
  }
  if (els.daySummaryWarnings) {
    const warnings = Array.isArray(payload.warnings) ? payload.warnings : [];
    els.daySummaryWarnings.innerHTML = warnings.length
      ? warnings.map((warning) => `<article class="analysis-item resistance"><strong>Data Warning</strong><p>${warning}</p></article>`).join("")
      : "";
  }
}

function getJournalScopeRequest() {
  const accountScope = els.journalAccountScope?.value || state.journalAccountScope || "current";
  const request = {
    accountScope,
    sourceMode: "current",
    profileAliases: [],
    scopeLabel: "Current Connected Account",
  };
  if (accountScope === "both_live") {
    request.sourceMode = "profiles";
    request.profileAliases = getKnownLiveProfiles().map((profile) => profile.alias);
    request.scopeLabel = "Combined Live Account History";
  } else if (accountScope.startsWith("profile:")) {
    const alias = accountScope.slice("profile:".length);
    request.sourceMode = "profiles";
    request.profileAliases = alias ? [alias] : [];
    request.scopeLabel = alias || "Saved Profile";
  }
  return request;
}

function resolveTraderJournalDate(payload = null) {
  const explicitDate = els.journalEntryDateInput?.value || "";
  if (explicitDate) return explicitDate;
  const filterDate = els.dateFilter?.value || "";
  if (filterDate) return filterDate;
  const firstDay = payload?.days?.[0]?.day || "";
  if (firstDay) return firstDay;
  return new Date().toISOString().slice(0, 10);
}

function populateTraderJournalEntry(entry) {
  const data = entry || {};
  if (els.journalSessionGradeInput) els.journalSessionGradeInput.value = data.session_grade || "";
  if (els.journalFollowedPlanInput) els.journalFollowedPlanInput.value = data.followed_plan || "";
  if (els.journalEmotionInput) els.journalEmotionInput.value = data.emotional_state || "";
  if (els.journalBestSetupInput) els.journalBestSetupInput.value = data.best_setup || "";
  if (els.journalTagsInput) els.journalTagsInput.value = Array.isArray(data.tags) ? data.tags.join(", ") : "";
  if (els.journalMarketConditionsInput) els.journalMarketConditionsInput.value = data.market_conditions || "";
  if (els.journalWhatWentWellInput) els.journalWhatWentWellInput.value = data.what_went_well || "";
  if (els.journalMistakesInput) els.journalMistakesInput.value = data.mistakes || "";
  if (els.journalLessonInput) els.journalLessonInput.value = data.lesson || "";
  if (els.journalNextFocusInput) els.journalNextFocusInput.value = data.next_focus || "";
}

function renderJournalAutoReview(autoReview = {}) {
  if (els.journalAutoReviewCards) {
    const cards = Array.isArray(autoReview.cards) ? autoReview.cards : [];
    els.journalAutoReviewCards.innerHTML = cards.length
      ? cards.map((card) => `
        <article class="analysis-item ${card.tone || "neutral"}">
          <strong>${card.title || "Review"}</strong>
          <p>${card.value || "-"}</p>
          <small>${card.note || ""}</small>
        </article>
      `).join("")
      : `<div class="empty-state">Choose a journal date and the system will summarize the day for you.</div>`;
  }

  if (els.journalAutoReviewIdeas) {
    const ideas = Array.isArray(autoReview.ideas) ? autoReview.ideas : [];
    els.journalAutoReviewIdeas.innerHTML = ideas.length
      ? ideas.map((item) => `
        <article class="analysis-item neutral">
          <strong>${item.title || "Pattern"}</strong>
          <p>${item.detail || ""}</p>
        </article>
      `).join("")
      : "";
  }
}

async function loadTraderJournalEntry() {
  if (!els.journalEntryDateInput) return;
  const exactDate = resolveTraderJournalDate();
  if (!exactDate) return;
  els.journalEntryDateInput.value = exactDate;
  const scope = getJournalScopeRequest();
  const params = new URLSearchParams({
    exact_date: exactDate,
    source_mode: scope.sourceMode,
  });
  if (scope.profileAliases.length) {
    params.set("profile_aliases", scope.profileAliases.join(","));
  }
  const payload = await fetchJson(`/api/trader-journal-entry?${params.toString()}`);
  state.journalEntryScopeKey = payload.scope_key || "";
  state.journalEntryScopeLabel = payload.scope_label || scope.scopeLabel;
  populateTraderJournalEntry(payload.entry || null);
  renderJournalAutoReview(payload.auto_review || {});
}

async function saveTraderJournalEntry() {
  if (!els.journalEntryDateInput) return;
  const journalDate = resolveTraderJournalDate();
  if (!journalDate) {
    throw new Error("Please choose a journal date first.");
  }
  els.journalEntryDateInput.value = journalDate;
  if (!state.journalEntryScopeKey) {
    await loadTraderJournalEntry();
  }
  const scope = getJournalScopeRequest();
  const payload = {
    journal_date: journalDate,
    scope_key: state.journalEntryScopeKey || scope.accountScope || "current",
    scope_label: state.journalEntryScopeLabel || scope.scopeLabel,
    session_grade: els.journalSessionGradeInput?.value || "",
    followed_plan: els.journalFollowedPlanInput?.value || "",
    emotional_state: els.journalEmotionInput?.value || "",
    best_setup: els.journalBestSetupInput?.value || "",
    tags: String(els.journalTagsInput?.value || "")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean),
    market_conditions: els.journalMarketConditionsInput?.value || "",
    what_went_well: els.journalWhatWentWellInput?.value || "",
    mistakes: els.journalMistakesInput?.value || "",
    lesson: els.journalLessonInput?.value || "",
    next_focus: els.journalNextFocusInput?.value || "",
  };
  const response = await postJson("/api/trader-journal-entry", payload);
  populateTraderJournalEntry(response.entry || null);
  showToast("Journal Saved", `Your notes for ${journalDate} were saved.`, "success");
}

function setupLaunchBanner() {
  if (window.location.protocol !== "file:") return;
  els.launchBanner.classList.remove("hidden");
  els.launchBannerLink.href = "http://127.0.0.1:8765";
  els.launchBannerText.textContent = "This page was opened directly from disk. Use the local server URL for full MT5 connectivity and smoother alerts.";
}

function showServerOffline(message) {
  els.serverBanner.classList.remove("hidden");
  els.serverBannerText.textContent = message;
  els.connectButton.disabled = true;
  els.disconnectButton.disabled = true;
  els.clearDbButton.disabled = true;
}

function hideServerOffline() {
  els.serverBanner.classList.add("hidden");
  els.connectButton.disabled = false;
  els.disconnectButton.disabled = false;
  els.clearDbButton.disabled = false;
}

async function refreshState() {
    try {
      const data = await fetchJson("/api/state");
    hideServerOffline();
    state.connected = Boolean(data.connected);
    const connectionText = data.connected
      ? `${data.account.server || "No server"}${data.account.login ? ` / ${data.account.login}` : ""}`
      : (data.connection_error || "Waiting for MT5");
      state.selectedProfileAlias = data.selected_profile_alias || state.selectedProfileAlias || "";
      state.selectedProfileGroup = data.selected_profile_group || "";
      state.accountSnapshot = data.account || state.accountSnapshot;
      state.currentSymbol = data.symbol || "";
      state.activeTrades = Array.isArray(data.active_trades) ? data.active_trades : [];
      state.pendingOrders = Array.isArray(data.pending_orders) ? data.pending_orders : [];
      state.emailNotificationsEnabled = Boolean(data.email_notifications_enabled);
      state.tradeLockEnabled = Boolean(data.trade_lock_enabled);
      state.notificationsEnabled = data.notifications_enabled !== false;
      if (data.alert_type_enabled && typeof data.alert_type_enabled === "object") {
        state.alertTypeEnabled = data.alert_type_enabled;
        localStorage.setItem("trade-observer-alert-type-enabled", JSON.stringify(state.alertTypeEnabled));
      }
      localStorage.setItem("trade-observer-notifications-enabled", state.notificationsEnabled ? "on" : "off");
      state.smtpConfigured = Boolean(data.smtp_configured);
      renderAccountProfileOptions();
      renderTerminalCards();
        renderEmailToggle();
        renderTradeLockToggle();
        renderNotificationsToggle();
        setConnectionState(data.connected, connectionText);
      const liveCentMode = currentConnectedAccountIsCent();
        if (els.balanceValue) els.balanceValue.textContent = displayMoney(data.account.balance, { centMode: liveCentMode });
      if (els.balanceMeta) els.balanceMeta.textContent = `Initial balance ${displayMoney(data.account.initial_balance || data.account.balance, { centMode: liveCentMode })}`;
      if (els.equityValue) els.equityValue.textContent = displayMoney(data.account.equity, { centMode: liveCentMode });
      if (els.equityMeta) els.equityMeta.textContent = `Free margin ${displayMoney(data.account.free_margin, { centMode: liveCentMode })}`;
      if (els.profitValue) els.profitValue.textContent = displayMoney(data.account.profit, { centMode: liveCentMode });
      if (els.profitMeta) {
        const openCount = Array.isArray(data.active_trades) ? data.active_trades.length : 0;
        const pendingCount = Array.isArray(data.pending_orders) ? data.pending_orders.length : 0;
        els.profitMeta.textContent = `${openCount} open trade(s) | ${pendingCount} pending order(s)`;
      }
        if (els.riskPlannerBalance) els.riskPlannerBalance.textContent = displayMoney(data.account.balance, { centMode: liveCentMode });
        if (els.riskPlannerEquity) els.riskPlannerEquity.textContent = displayMoney(data.account.equity, { centMode: liveCentMode });
        if (els.riskPlannerLeverage) els.riskPlannerLeverage.textContent = Number(data.account.leverage || 0) > 0 ? `1:${data.account.leverage}` : "Unavailable";
        if (els.riskBalanceInput && (!els.riskBalanceInput.dataset.userEdited || els.riskBalanceInput.value === "" || Number(els.riskBalanceInput.value) === 0)) {
          els.riskBalanceInput.value = fixed(data.account.balance || 0, 2);
        }
        if (els.accountValue) els.accountValue.textContent = data.account.login ? `${data.account.login}` : (data.symbol || "-");
      if (els.serverMeta) els.serverMeta.textContent = data.connected
          ? `${data.account.server || "No server"} | Symbol ${data.symbol || "-"}${data.selected_profile_alias ? ` | Profile ${data.selected_profile_alias}` : ""}`
          : (data.mt5_package_available ? connectionText : "Install MetaTrader5 into the Python runtime and click Connect to MT5.");
      renderTradeCards(data.active_trades, data.account);
      renderPendingOrderCards(data.pending_orders || []);
      drawChart(data.recent_prices);
      if (state.analysis) drawAnalysisChart(state.analysis);
      if (state.charts) drawChartsPage(state.charts);
      renderRiskGuide();
      detectTradeLevelChanges(data.active_trades, data.recent_alerts);
    const combinedAlerts = mergeAlerts(data.recent_alerts);
    renderAlerts(combinedAlerts);
    maybePlayLatestAlert(combinedAlerts);
    } catch (error) {
      state.connected = false;
      setConnectionState(false, "Local dashboard server is offline");
      showServerOffline("Start `run_metatrader_trade_observer.bat` and keep its terminal window open. Then click Retry Connection.");
      if (els.accountValue) els.accountValue.textContent = "-";
    if (els.serverMeta) els.serverMeta.textContent = "No local server on http://127.0.0.1:8765";
    if (els.tradeCards) els.tradeCards.innerHTML = `<div class="empty-state">The dashboard backend is not running, so live MT5 trade data cannot be shown yet.</div>`;
    if (els.pendingOrderCards) els.pendingOrderCards.innerHTML = `<div class="empty-state">The dashboard backend is not running, so pending MT5 orders cannot be shown yet.</div>`;
        state.previousTradeLevels = {};
        state.activeTrades = [];
        state.pendingOrders = [];
        state.localAlerts = [];
    renderAlerts([]);
    renderTerminalCards();
    renderEmailToggle();
    renderTradeLockToggle();
  }
}

async function refreshJournal() {
  if (!els.rangeFilter || !els.dateFilter || !els.outcomeFilter || !els.lotFilter || !els.specialFilter) return;
  const accountScope = els.journalAccountScope?.value || state.journalAccountScope || "current";
  state.journalAccountScope = accountScope;
  localStorage.setItem("trade-observer-journal-account-scope", accountScope);
  const params = new URLSearchParams({
    range: els.rangeFilter.value,
    exact_date: els.dateFilter.value,
    outcome: els.outcomeFilter.value,
    lot_size: els.lotFilter.value,
    special: els.specialFilter.value,
  });
  const selectedSymbols = (Array.isArray(state.journalSelectedSymbols) ? state.journalSelectedSymbols : [])
    .map((item) => String(item || "").trim().toUpperCase())
    .filter(Boolean);
  if (selectedSymbols.length) {
    params.set("symbols", selectedSymbols.join(","));
  }
  let title = "Live Account Trade History";
  let kicker = "MetaTrader 5 History";
  if (accountScope === "both_live") {
    const aliases = getKnownLiveProfiles().map((profile) => profile.alias);
    params.set("source_mode", "profiles");
    params.set("profile_aliases", aliases.join(","));
    title = "Combined Live Account History";
    kicker = "Saved MT5 History";
  } else if (accountScope.startsWith("profile:")) {
    const alias = accountScope.slice("profile:".length);
    params.set("source_mode", "profiles");
    params.set("profile_aliases", alias);
    title = `${alias} Trade History`;
    kicker = "Saved MT5 History";
  }
  const payload = await fetchJson(`/api/mt5-journal?${params.toString()}`);
  if (els.journalKicker) els.journalKicker.textContent = kicker;
  if (els.journalTitle) els.journalTitle.textContent = title;
  renderJournal(payload);
  if (els.journalEntryDateInput) {
    els.journalEntryDateInput.value = resolveTraderJournalDate(payload);
    await loadTraderJournalEntry().catch(() => {
      populateTraderJournalEntry(null);
      renderJournalAutoReview({ cards: [], ideas: [] });
    });
  }
}

async function refreshActivePageData() {
  switch (state.activePage) {
    case "analysis":
      await refreshAnalysis();
      break;
    case "charts":
      await refreshChartsPage();
      break;
    case "consolidation":
      await refreshConsolidation();
      break;
    case "markets":
      await refreshMarkets();
      break;
    case "journal":
      await refreshJournal();
      break;
    case "security":
      await refreshSecurityLogins();
      break;
    default:
      break;
  }
}

function startActivePageIntervals() {
  switch (state.activePage) {
    case "analysis":
      setInterval(() => {
        refreshAnalysis().catch(() => {});
      }, 10000);
      break;
    case "charts":
      setInterval(() => {
        refreshChartsPage().catch(() => {});
      }, 10000);
      break;
    case "consolidation":
      setInterval(() => {
        refreshConsolidation().catch(() => {});
      }, 10000);
      break;
    case "markets":
      setInterval(() => {
        refreshMarkets().catch(() => {});
      }, 30000);
      break;
    case "journal":
      setInterval(() => {
        refreshJournal().catch(() => {});
      }, 5000);
      break;
    case "security":
      setInterval(() => {
        refreshSecurityLogins().catch(() => {});
      }, 60000);
      break;
    default:
      break;
  }
}

function bindEvents() {
  updateSummaryScrollState();
  window.addEventListener("scroll", updateSummaryScrollState, { passive: true });
  window.addEventListener("resize", () => {
    if (state.analysis) drawAnalysisChart(state.analysis);
    if (state.charts) drawChartsPage(state.charts);
    if (state.consolidation) drawConsolidationChart(state.consolidation);
    if (state.riskChart) {
      try {
        drawRiskPlannerChart(state.riskChart, getRiskPlannerData());
      } catch {}
    }
  });

  document.addEventListener("click", () => {
    getAudioContext();
  }, { once: true });

  els.sideNavToggle?.addEventListener("click", () => {
    state.sideNavCollapsed = !state.sideNavCollapsed;
    localStorage.setItem("trade-observer-sidenav", state.sideNavCollapsed ? "collapsed" : "expanded");
    applySideNavState();
  });

  els.themeToggle?.addEventListener("click", () => {
    state.theme = state.theme === "dark" ? "light" : "dark";
    localStorage.setItem("trade-observer-theme", state.theme);
    applyTheme();
  });

  els.pageNav?.querySelectorAll("[data-page]").forEach((button) => {
    button.addEventListener("click", () => {
      state.activePage = button.getAttribute("data-page") || "live";
      localStorage.setItem("trade-observer-page", state.activePage);
    });
  });

  els.analysisTimeframeSelect?.addEventListener("change", () => {
    state.analysisTimeframe = els.analysisTimeframeSelect.value || "H1";
    localStorage.setItem("trade-observer-analysis-timeframe", state.analysisTimeframe);
    refreshAnalysis().catch(() => {});
  });

  els.analysisFullscreenButton?.addEventListener("click", () => {
    toggleAnalysisFullscreen().catch(() => {
      showToast("Could not toggle analysis fullscreen.");
    });
  });

  els.chartSymbolSelect?.addEventListener("change", () => {
    state.chartSymbol = els.chartSymbolSelect.value || "xauusd";
    localStorage.setItem("trade-observer-chart-symbol", state.chartSymbol);
    renderChartWatcherForm({ symbol: state.chartSymbol.toUpperCase(), current_price: state.charts?.current_price || 0 });
    refreshChartsPage().catch(() => {});
  });

  els.chartTypeToggle?.querySelectorAll("[data-chart-type]").forEach((button) => {
    button.addEventListener("click", () => {
      state.chartType = button.getAttribute("data-chart-type") || "candlestick";
      localStorage.setItem("trade-observer-chart-type", state.chartType);
      els.chartTypeToggle?.querySelectorAll("[data-chart-type]").forEach((item) => item.classList.toggle("active", item === button));
      if (state.charts) drawChartsPage(state.charts);
    });
  });

  els.notificationsToggleInput?.addEventListener("change", () => {
    const previousEnabled = state.notificationsEnabled;
    const previousAlertTypes = { ...state.alertTypeEnabled };
    state.notificationsEnabled = Boolean(els.notificationsToggleInput.checked);
    localStorage.setItem("trade-observer-notifications-enabled", state.notificationsEnabled ? "on" : "off");
    setAllAlertTypesEnabled(state.notificationsEnabled);
    renderNotificationsToggle();
    renderAlertSettings();
    postJson("/api/notifications-preferences", {
      notifications_enabled: state.notificationsEnabled,
      alert_type_enabled: state.alertTypeEnabled,
    }).then(() => {
      if (!state.notificationsEnabled) {
        stopAlarmLoop();
        closeAlarmModal();
        showToast("Notifications Off", "All in-app alert types are now muted.", "success");
      } else {
        showToast("Notifications On", "All in-app alert types are active again.", "success");
      }
    }).catch((error) => {
      state.notificationsEnabled = previousEnabled;
      state.alertTypeEnabled = previousAlertTypes;
      localStorage.setItem("trade-observer-notifications-enabled", state.notificationsEnabled ? "on" : "off");
      localStorage.setItem("trade-observer-alert-type-enabled", JSON.stringify(state.alertTypeEnabled));
      renderNotificationsToggle();
      renderAlertSettings();
      showToast("Preference Save Failed", error.message || "Could not save notification settings to the server.", "warn");
    });
  });

  els.tradeLockToggleInput?.addEventListener("change", async () => {
    const nextEnabled = Boolean(els.tradeLockToggleInput.checked);
    els.tradeLockToggleInput.disabled = true;
    try {
      const payload = await postJson("/api/trade-lock", { enabled: nextEnabled });
      state.tradeLockEnabled = Boolean(payload.enabled);
      renderTradeLockToggle();
      showToast(
        state.tradeLockEnabled ? "Trade Lock Enabled" : "Trade Lock Disabled",
        state.tradeLockEnabled
          ? "New trade entries from this dashboard are now blocked."
          : "New trade entries from this dashboard are allowed again.",
        "success"
      );
    } catch (error) {
      showToast("Trade Lock Update Failed", error.message || "Could not update Trade Lock.", "warn");
    } finally {
      if (els.tradeLockToggleInput) els.tradeLockToggleInput.disabled = false;
      renderTradeLockToggle();
    }
  });

  els.chartTimeframeStrip?.querySelectorAll("[data-chart-timeframe]").forEach((button) => {
    button.addEventListener("click", () => {
      setChartTimeframe(button.getAttribute("data-chart-timeframe") || "M1");
    });
  });

  els.chartFullscreenTimeframes?.querySelectorAll("[data-chart-timeframe-overlay]").forEach((button) => {
    button.addEventListener("click", () => {
      setChartTimeframe(button.getAttribute("data-chart-timeframe-overlay") || "M1");
    });
  });

  els.chartFullscreenButton?.addEventListener("click", () => {
    toggleChartFullscreen().catch(() => {
      showToast("Could not toggle chart fullscreen.");
    });
  });

  els.chartZoomInButton?.addEventListener("click", () => {
    adjustChartZoom(1);
  });

  els.chartZoomOutButton?.addEventListener("click", () => {
    adjustChartZoom(-1);
  });

  const syncChartWatcherDraft = () => {
    const symbol = state.charts?.symbol || state.chartSymbol;
    setChartWatcherDraft(symbol, {
      bullish_target: (els.chartBullishTargetInput?.value || "").trim(),
      bearish_target: (els.chartBearishTargetInput?.value || "").trim(),
    });
  };

  els.chartBullishTargetInput?.addEventListener("input", syncChartWatcherDraft);
  els.chartBearishTargetInput?.addEventListener("input", syncChartWatcherDraft);

  els.chartWatcherArmButton?.addEventListener("click", () => {
    armChartWatcherFromInputs();
  });

  els.chartWatcherClearButton?.addEventListener("click", () => {
    clearChartWatcher(state.charts?.symbol || state.chartSymbol);
    if (els.chartBullishTargetInput) els.chartBullishTargetInput.value = "";
    if (els.chartBearishTargetInput) els.chartBearishTargetInput.value = "";
    renderChartWatcherForm(state.charts);
    if (state.charts) drawChartsPage(state.charts);
    showToast("Price Watcher Cleared", "Bullish and bearish chart targets were removed for this symbol.", "success");
  });

  els.consolidationSymbolSelect?.addEventListener("change", () => {
    state.consolidationSymbol = els.consolidationSymbolSelect.value || "xauusd";
    localStorage.setItem("trade-observer-consolidation-symbol", state.consolidationSymbol);
    refreshConsolidation().catch(() => {});
  });

  els.consolidationTimeframeStrip?.querySelectorAll("[data-consolidation-timeframe]").forEach((button) => {
    button.addEventListener("click", () => {
      state.consolidationTimeframe = button.getAttribute("data-consolidation-timeframe") || "M5";
      localStorage.setItem("trade-observer-consolidation-timeframe", state.consolidationTimeframe);
      els.consolidationTimeframeStrip?.querySelectorAll("[data-consolidation-timeframe]").forEach((item) => {
        item.classList.toggle("active", item === button);
      });
      refreshConsolidation().catch(() => {});
    });
  });

  document.addEventListener("fullscreenchange", () => {
    updateChartFullscreenUi();
    updateAnalysisFullscreenUi();
    if (state.analysis) drawAnalysisChart(state.analysis);
    if (state.charts) drawChartsPage(state.charts);
  });

  els.chartStage?.addEventListener("mousemove", () => {
    showChartHud();
  });

  els.chartStage?.addEventListener("mouseenter", () => {
    showChartHud();
  });

  els.chartStage?.addEventListener("wheel", (event) => {
    if (state.activePage !== "charts") return;
    event.preventDefault();
    adjustChartZoom(event.deltaY > 0 ? -1 : 1);
  }, { passive: false });

  document.addEventListener("keydown", (event) => {
    const target = event.target;
    const tagName = target?.tagName?.toLowerCase?.() || "";
    const typing = target?.isContentEditable || ["input", "textarea", "select"].includes(tagName);
    if (typing || state.activePage !== "charts") return;
    if (event.key.toLowerCase() === "f") {
      event.preventDefault();
      toggleChartFullscreen().catch(() => {});
      return;
    }
    if (event.key === "+" || event.key === "=") {
      event.preventDefault();
      adjustChartZoom(1);
      return;
    }
    if (event.key === "-" || event.key === "_") {
      event.preventDefault();
      adjustChartZoom(-1);
    }
  });

  document.addEventListener("keydown", (event) => {
    const target = event.target;
    const tagName = target?.tagName?.toLowerCase?.() || "";
    const typing = target?.isContentEditable || ["input", "textarea", "select"].includes(tagName);
    if (typing || state.activePage !== "analysis") return;
    if (event.key.toLowerCase() === "f") {
      event.preventDefault();
      toggleAnalysisFullscreen().catch(() => {});
    }
  });

  els.marketsViewToggle?.querySelectorAll("[data-markets-view]").forEach((button) => {
    button.addEventListener("click", () => {
      state.marketsView = button.getAttribute("data-markets-view") || "cards";
      localStorage.setItem("trade-observer-markets-view", state.marketsView);
      els.marketsViewToggle?.querySelectorAll("[data-markets-view]").forEach((item) => item.classList.toggle("active", item === button));
      if (state.markets) renderMarkets(state.markets);
    });
  });

  els.calculatorModeStrip?.querySelectorAll("[data-calculator-mode]").forEach((button) => {
    button.addEventListener("click", () => {
      state.calculatorMode = button.getAttribute("data-calculator-mode") || "profit";
      localStorage.setItem("trade-observer-calculator-mode", state.calculatorMode);
      renderCalculatorMode();
      runCalculator();
    });
  });

  [
    els.calcSymbolInput,
    els.calcSideSelect,
    els.calcLotInput,
    els.calcOpenInput,
    els.calcCloseInput,
    els.calcEntryInput,
    els.calcStopLossInput,
    els.calcTakeProfitInput,
    els.calcAccountSizeInput,
    els.calcRiskPercentInput,
    els.calcStopLossPipsInput,
    els.calcPipSizeInput,
    els.calcXauPipModeSelect,
    els.calcContractSizeInput,
    els.calcQuoteCurrencyInput,
  ].forEach((input) => {
    input?.addEventListener("input", () => {
      if (input === els.calcXauPipModeSelect) {
        state.calculatorXauPipMode = els.calcXauPipModeSelect?.value || "0.10";
        localStorage.setItem("trade-observer-calculator-xau-pip-mode", state.calculatorXauPipMode);
      }
      renderCalculatorMode();
      renderCalculatorMarketNotes();
    });
  });

  els.calculatorRunButton?.addEventListener("click", () => {
    runCalculator();
  });

  [
    els.riskSymbolInput,
    els.riskSideSelect,
    els.riskLotInput,
    els.riskEntryInput,
    els.riskStopInput,
    els.riskTargetInput,
    els.riskPercentInput,
  ].forEach((input) => {
    input?.addEventListener("input", () => {
      runRiskPlanner();
    });
  });

  els.riskBalanceInput?.addEventListener("input", () => {
    els.riskBalanceInput.dataset.userEdited = "yes";
    runRiskPlanner();
  });

  els.riskTimeframeSelect?.addEventListener("change", () => {
    runRiskPlanner();
  });

  els.riskPlannerRunButton?.addEventListener("click", () => {
    runRiskPlanner();
  });

  els.riskPlannerAddTradeButton?.addEventListener("click", () => {
    try {
      addCurrentRiskTradeToBasket();
    } catch (error) {
      showToast("Could Not Add Trade", error.message || "Risk basket entry failed.", "warn");
    }
  });

  els.riskPlannerClearBasketButton?.addEventListener("click", () => {
    state.riskBasket = [];
    saveRiskBasket();
    renderRiskBasket();
  });

  els.riskPlannerCanvas?.addEventListener("pointermove", handleRiskPlannerPointerMove);
  els.riskPlannerCanvas?.addEventListener("pointerdown", handleRiskPlannerPointerDown);
  els.riskPlannerCanvas?.addEventListener("pointerleave", () => {
    state.riskChartInteraction.hoveredHandle = null;
    if (!state.riskChartInteraction.draggingHandle) {
      try {
        drawRiskPlannerChart(state.riskChart || { candles: [] }, getRiskPlannerData());
      } catch {}
    }
  });
  els.riskPlannerCanvas?.addEventListener("pointerup", stopRiskPlannerDrag);
  els.riskPlannerCanvas?.addEventListener("pointercancel", stopRiskPlannerDrag);

  els.orlLiveModeButton?.addEventListener("click", () => {
    setOrlMode("live");
  });

  els.orlPastModeButton?.addEventListener("click", async () => {
    setOrlMode("historical");
    try {
      await loadOrlSessionsAndSymbols();
      openOrlAnalyzeModal();
    } catch (error) {
      renderOrlValidationMessages(["Could not load ORL symbols or sessions."], "bearish");
    }
  });

  els.orlBackToLiveButton?.addEventListener("click", () => {
    setOrlMode("live");
  });

  els.orlViewDetailsButton?.addEventListener("click", () => {
    openOrlDetailsModal();
  });

  els.closeOrlAnalyzeModalButton?.addEventListener("click", () => {
    closeOrlAnalyzeModal();
  });

  els.closeOrlDetailsModalButton?.addEventListener("click", () => {
    closeOrlDetailsModal();
  });

  els.orlAnalyzeModal?.addEventListener("click", (event) => {
    if (event.target === els.orlAnalyzeModal || event.target.classList.contains("alarm-backdrop")) {
      closeOrlAnalyzeModal();
    }
  });

  els.orlDetailsModal?.addEventListener("click", (event) => {
    if (event.target === els.orlDetailsModal || event.target.classList.contains("alarm-backdrop")) {
      closeOrlDetailsModal();
    }
  });

  els.submitOrlAnalyzeButton?.addEventListener("click", async () => {
    const customSessionTime = els.orlSessionSelect?.value === "Custom"
      ? {
          hour: Number(els.orlCustomHourInput?.value || -1),
          minute: Number(els.orlCustomMinuteInput?.value || -1),
        }
      : null;
    const payload = {
      symbol: els.orlSymbolSelect?.value || state.currentSymbol || "XAUUSD",
      date: els.orlDateInput?.value,
      session: els.orlSessionSelect?.value || "New York",
      timezone_mode: els.orlTimezoneModeSelect?.value || "UTC",
      custom_session_time: customSessionTime,
      atr_period: Number(els.orlAtrPeriodInput?.value || 14),
      atr_threshold_percent: Number(els.orlAtrThresholdInput?.value || 25),
      box_extension_minutes: Number(els.orlBoxExtensionInput?.value || 180),
      lot_size: Number(els.orlLotSizeInput?.value || 0.01),
      starting_balance: Number(els.orlStartingBalanceInput?.value || 100),
      risk_mode: els.orlRiskModeSelect?.value || "Fixed lot",
      filters: {
        require_m5_close_outside_box: true,
        max_distance_from_box_points: 60,
        minimum_breakout_distance_points: 30,
        require_previous_3_candle_direction: true,
        max_sl_points: 200,
        minimum_rr: 1.2,
        max_signals_per_session: 1,
      },
    };
    renderOrlValidationMessages(["Analyzing past chart..."], "neutral");
    try {
      const response = await postJson("/api/orl/analyze-past-chart", payload);
      closeOrlAnalyzeModal();
      setOrlMode("historical");
      renderOrlHistoricalResult(response);
      renderOrlValidationMessages([], "neutral");
      showToast("ORL-25 Analysis Complete", response.message || "Historical ORL analysis completed.", "success");
    } catch (error) {
      renderOrlValidationMessages([error.message || "ORL historical analysis failed."], "bearish");
    }
  });

  els.emailToggleInput?.addEventListener("change", async () => {
    const nextEnabled = !state.emailNotificationsEnabled;
    els.emailToggleInput.disabled = true;
    try {
      const payload = await postJson("/api/email-notifications", { enabled: nextEnabled });
      state.emailNotificationsEnabled = Boolean(payload.enabled);
      renderEmailToggle();
      showToast(
        "Gmail Notifications Updated",
        `Email notifications are now ${state.emailNotificationsEnabled ? "on" : "off"}.`,
        "success"
      );
    } finally {
      renderEmailToggle();
    }
  });

  els.connectButton?.addEventListener("click", async () => {
    els.connectButton.disabled = true;
    els.connectButton.textContent = "Connecting...";
    try {
      await connectToMt5(
        { profile_alias: els.accountProfileSelect.value },
        els.accountProfileSelect.value
          ? `${els.accountProfileSelect.value} is now the active MT5 account.`
          : "The default MT5 session is now active."
      );
    } catch (error) {
      showToast("Connection Failed", error.message || "Could not connect to MT5.", "warn");
    } finally {
      els.connectButton.disabled = false;
      els.connectButton.textContent = "Connect to MT5";
    }
  });

  els.disconnectButton?.addEventListener("click", async () => {
    els.disconnectButton.disabled = true;
    els.disconnectButton.textContent = "Disconnecting...";
    try {
      await postJson("/api/disconnect");
      await refreshState();
      showToast("MT5 Disconnected", "Monitoring has stopped until you connect again.", "success");
    } finally {
      els.disconnectButton.disabled = false;
      els.disconnectButton.textContent = "Disconnect";
    }
  });

  els.manageAccountsButton?.addEventListener("click", async () => {
    openAccountsModal();
    els.accountProfilesList.innerHTML = `<div class="empty-state">Loading saved account profiles...</div>`;
    try {
      await loadAccountProfiles();
    } catch (error) {
      els.accountProfilesList.innerHTML = `<div class="empty-state">Could not load account profiles right now.</div>`;
    }
  });

  els.closeAccountsButton?.addEventListener("click", () => {
    closeAccountsModal();
  });

  els.accountsModal?.addEventListener("click", (event) => {
    if (event.target === els.accountsModal || event.target.classList.contains("alarm-backdrop")) {
      closeAccountsModal();
    }
  });

  els.accountProfileSelect?.addEventListener("change", () => {
    state.selectedProfileAlias = els.accountProfileSelect.value;
  });

  els.accountProfileForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const wasEditing = Boolean(state.editingAccountProfileAlias);
    const payload = {
      alias: (state.editingAccountProfileAlias || els.profileAliasInput.value).trim(),
      login: els.profileLoginInput.value.trim(),
      password: els.profilePasswordInput.value,
      server: els.profileServerInput.value.trim(),
      terminal_path: els.profileTerminalPathInput.value.trim(),
      group: els.profileGroupInput.value.trim(),
    };
    const response = await postJson("/api/account-profiles", payload);
    hydrateAccountProfiles(response);
    state.selectedProfileAlias = payload.alias;
    renderAccountProfileOptions();
    resetAccountProfileForm();
    showToast(wasEditing ? "Profile Updated" : "Profile Saved", `${payload.alias} is now available in the account selector.`, "success");
  });

  els.depositsButton?.addEventListener("click", async () => {
    openFundingModal();
    els.fundingList.innerHTML = `<div class="empty-state">Loading deposit history...</div>`;
    try {
      await loadDeposits();
    } catch (error) {
      els.fundingList.innerHTML = `<div class="empty-state">Could not load deposit history. Make sure the backend is running and MetaTrader is connected.</div>`;
    }
  });

  els.toggleFundingFiltersButton?.addEventListener("click", () => {
    state.depositFiltersVisible = !state.depositFiltersVisible;
    applyFundingFilterVisibility();
  });

  els.depositRangeFilter?.addEventListener("change", () => {
    state.depositRange = els.depositRangeFilter.value || "year";
    localStorage.setItem("trade-observer-deposit-range", state.depositRange);
  });

  els.applyFundingFiltersButton?.addEventListener("click", async () => {
    state.depositRange = els.depositRangeFilter?.value || state.depositRange || "year";
    localStorage.setItem("trade-observer-deposit-range", state.depositRange);
    els.fundingList.innerHTML = `<div class="empty-state">Refreshing deposit history...</div>`;
    try {
      await loadDeposits();
    } catch (error) {
      els.fundingList.innerHTML = `<div class="empty-state">Could not load deposit history for the selected accounts and date range.</div>`;
    }
  });

  els.daySummaryButton?.addEventListener("click", async () => {
    openDaySummaryModal();
    if (els.daySummaryWarnings) els.daySummaryWarnings.innerHTML = "";
    try {
      await loadDaySummary();
    } catch (error) {
      if (els.daySummaryWarnings) {
        els.daySummaryWarnings.innerHTML = `<article class="analysis-item resistance"><strong>Summary Error</strong><p>${error.message || "Could not load the daily summary."}</p></article>`;
      }
    }
  });

  els.closeFundingButton?.addEventListener("click", () => {
    closeFundingModal();
  });

  els.fundingModal?.addEventListener("click", (event) => {
    if (event.target === els.fundingModal || event.target.classList.contains("alarm-backdrop")) {
      closeFundingModal();
    }
  });

  els.toggleDaySummaryFiltersButton?.addEventListener("click", () => {
    state.daySummaryFiltersVisible = !state.daySummaryFiltersVisible;
    applyDaySummaryFilterVisibility();
  });

  els.applyDaySummaryButton?.addEventListener("click", async () => {
    try {
      await loadDaySummary();
    } catch (error) {
      if (els.daySummaryWarnings) {
        els.daySummaryWarnings.innerHTML = `<article class="analysis-item resistance"><strong>Summary Error</strong><p>${error.message || "Could not load the daily summary."}</p></article>`;
      }
    }
  });

  els.closeDaySummaryButton?.addEventListener("click", () => {
    closeDaySummaryModal();
  });

  els.daySummaryModal?.addEventListener("click", (event) => {
    if (event.target === els.daySummaryModal || event.target.classList.contains("alarm-backdrop")) {
      closeDaySummaryModal();
    }
  });

  els.journalLoadEntryButton?.addEventListener("click", async () => {
    try {
      await loadTraderJournalEntry();
    } catch (error) {
      showToast("Journal Load Failed", error.message || "Could not load your journal entry.", "warn");
    }
  });

  els.journalSaveEntryButton?.addEventListener("click", async () => {
    try {
      await saveTraderJournalEntry();
    } catch (error) {
      showToast("Journal Save Failed", error.message || "Could not save your journal entry.", "warn");
    }
  });

  els.journalEntryDateInput?.addEventListener("change", () => {
    loadTraderJournalEntry().catch(() => {});
  });

  document.addEventListener("click", (event) => {
    const button = event.target instanceof Element ? event.target.closest("[data-playbook-example-toggle]") : null;
    if (!button) return;
    const targetKey = button.getAttribute("data-playbook-example-toggle") || "";
    const card = button.closest(".playbook-concept-card");
    if (!card || !targetKey) return;
    const panel = card.querySelector(`[data-playbook-example-panel="${targetKey}"]`);
    if (!panel) return;
    const willShow = panel.classList.contains("hidden-page");
    card.querySelectorAll("[data-playbook-example-panel]").forEach((item) => {
      item.classList.add("hidden-page");
    });
    if (willShow) {
      panel.classList.remove("hidden-page");
    }
  });

  els.openFakeoutLessonButton?.addEventListener("click", () => {
    openFakeoutLessonModal();
  });

  els.closeFakeoutLessonButton?.addEventListener("click", () => {
    closeFakeoutLessonModal();
  });

  els.fakeoutLessonModal?.addEventListener("click", (event) => {
    if (event.target === els.fakeoutLessonModal || event.target.classList.contains("alarm-backdrop")) {
      closeFakeoutLessonModal();
    }
  });

  els.fakeoutLessonPrevButton?.addEventListener("click", () => {
    state.fakeoutLessonStep = Math.max(0, state.fakeoutLessonStep - 1);
    renderFakeoutLesson();
  });

  els.fakeoutLessonNextButton?.addEventListener("click", () => {
    if (state.fakeoutLessonStep >= FAKEOUT_LESSON_STEPS.length - 1) {
      state.fakeoutLessonStep = 0;
    } else {
      state.fakeoutLessonStep += 1;
    }
    renderFakeoutLesson();
  });

  els.fakeoutLessonViewToggle?.querySelectorAll("[data-fakeout-view]").forEach((button) => {
    button.addEventListener("click", () => {
      state.fakeoutLessonView = button.getAttribute("data-fakeout-view") || "illustration";
      renderFakeoutLesson();
    });
  });

  els.retryServerButton?.addEventListener("click", () => {
    loadDetectedTerminals().catch(() => {});
    refreshState().catch(() => {});
    refreshJournal().catch(() => {});
    refreshSecurityLogins().catch(() => {});
  });

  els.securityRefreshButton?.addEventListener("click", () => {
    refreshSecurityLogins().catch(() => {});
  });

  els.alarmTestGrid?.querySelectorAll("[data-test-alarm]").forEach((button) => {
    button.addEventListener("click", async () => {
      const eventType = button.getAttribute("data-test-alarm");
      const alert = buildTestAlert(eventType);
      addLocalAlert(alert, `test|${eventType}|${Date.now()}`);
      const emailEligibleEvents = new Set([
        "entry",
        "close",
        "approaching_stop",
        "capital_warning",
        "stop_loss_hit",
        "account_blown",
      ]);
      if (emailEligibleEvents.has(eventType)) {
        try {
          await postJson("/api/test-email-alert", { event_type: eventType });
          showToast("Alarm Test Triggered", `${alarmTitleFor(eventType)} test played and email test sent.`, "success");
          return;
        } catch (error) {
          showToast("Alarm Test Triggered", `${alarmTitleFor(eventType)} test played, but the email test failed.`, "warn");
          return;
        }
      }
      showToast("Alarm Test Triggered", `${alarmTitleFor(eventType)} test played.`, "success");
    });
  });

  els.clearDbButton?.addEventListener("click", async () => {
    const confirmed = window.confirm("Clear the full SQLite database and all saved trade history?");
    if (!confirmed) return;
    await postJson("/api/clear-db");
    stopAlarmLoop();
    closeAlarmModal();
    state.lastAlertKey = null;
    state.activeAlarmKey = null;
    state.previousTradeLevels = {};
    state.localAlerts = [];
    localStorage.removeItem("trade-observer-last-alert-key");
    els.lotFilter.innerHTML = `<option value="">All</option>`;
    await refreshState();
    await refreshJournal();
  });

  els.stopAlarmButton?.addEventListener("click", () => {
    stopAlarmLoop();
    closeAlarmModal();
  });

  [els.journalAccountScope, els.rangeFilter, els.dateFilter, els.outcomeFilter, els.lotFilter, els.specialFilter].forEach((input) => {
    input?.addEventListener("change", () => {
      refreshJournal().catch(() => {});
    });
  });
}

async function boot() {
  try {
    state.riskBasket = JSON.parse(localStorage.getItem("trade-observer-risk-basket") || "[]");
    if (!Array.isArray(state.riskBasket)) state.riskBasket = [];
  } catch (error) {
    state.riskBasket = [];
  }
  applyTheme();
  applySideNavState();
  ensureDynamicPageLinks();
  applyActivePage();
  renderCalculatorMode();
  renderTradeLockToggle();
  renderNotificationsToggle();
  renderAlertSettings();
  setupLaunchBanner();
  bindEvents();

  if (state.activePage === "security") {
    try {
      await refreshState();
    } catch (error) {}
    await refreshSecurityLogins();
    setInterval(() => {
      refreshState().catch(() => {});
    }, 1000);
    setInterval(() => {
      refreshSecurityLogins().catch(() => {});
    }, 60000);
    return;
  }

  try {
    await loadAccountProfiles();
  } catch (error) {
    state.accountProfiles = [];
    renderAccountProfileOptions();
  }
  try {
    await loadDetectedTerminals();
  } catch (error) {
    state.detectedTerminals = [];
    renderTerminalCards();
  }
  renderJournalAccountScopes();
  if (els.journalAccountScope) {
    els.journalAccountScope.value = state.journalAccountScope;
  }
  if (els.chartSymbolSelect) {
    els.chartSymbolSelect.value = state.chartSymbol;
  }
  if (els.consolidationSymbolSelect) {
    els.consolidationSymbolSelect.value = state.consolidationSymbol;
  }
  updateChartFullscreenUi();
  els.chartTypeToggle?.querySelectorAll("[data-chart-type]").forEach((button) => {
    button.classList.toggle("active", button.getAttribute("data-chart-type") === state.chartType);
  });
  syncChartTimeframeButtons();
  els.consolidationTimeframeStrip?.querySelectorAll("[data-consolidation-timeframe]").forEach((button) => {
    button.classList.toggle("active", button.getAttribute("data-consolidation-timeframe") === state.consolidationTimeframe);
  });
  els.marketsViewToggle?.querySelectorAll("[data-markets-view]").forEach((button) => {
    button.classList.toggle("active", button.getAttribute("data-markets-view") === state.marketsView);
  });
  els.calculatorModeStrip?.querySelectorAll("[data-calculator-mode]").forEach((button) => {
    button.classList.toggle("active", button.getAttribute("data-calculator-mode") === state.calculatorMode);
  });
  if (els.calcXauPipModeSelect) {
    els.calcXauPipModeSelect.value = state.calculatorXauPipMode || "0.10";
  }
  runCalculator();
  renderRiskGuide();
  runRiskPlanner();
  renderRiskBasket();
  await refreshState();
  await maybePromptStartupTerminalConnection();
  runRiskPlanner();
  await refreshActivePageData();
  setInterval(() => {
    refreshState().catch(() => {});
  }, 1000);
  startActivePageIntervals();
}

boot().catch((error) => {
  setConnectionState(false, error.message);
});
