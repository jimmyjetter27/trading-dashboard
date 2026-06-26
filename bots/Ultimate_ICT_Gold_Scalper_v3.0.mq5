//+------------------------------------------------------------------+
//|                                       BAKOME_Ultimate_ICT_Gold_Scalper_v3.0.mq5 |
//|                                      BAKOME Trading Systems      |
//|                                                   Version 3.00 |
//+------------------------------------------------------------------+
#property copyright "BAKOME – Fabrice Kitoko"
#property version   "3.00"
#property description "Advanced ICT Gold Scalper with FVG, Order Blocks, Silver Bullet"
#property link      "https://github.com/BAKOME-Hub"
#property strict

#include <Trade/Trade.mqh>
#include <Trade/PositionInfo.mqh>
#include <Trade/SymbolInfo.mqh>
#include <Trade/AccountInfo.mqh>

//+------------------------------------------------------------------+
//| Input Parameters                                                |
//+------------------------------------------------------------------+
input group "=== Risk Management ==="
input double RiskPercent            = 1.0;      // Risk per trade (%)
input double MaxDailyRiskPercent    = 5.0;      // Max daily loss (%)
input double MaxDailyProfitPercent  = 8.0;      // Daily profit target (%)
input double MaxMarginUsagePercent  = 80.0;     // Max free margin used by one trade (%)
input bool   AllowMinLotWhenRiskTooSmall = true; // Use minimum lot if risk lot is below broker minimum
input int    MaxPositions           = 2;        // Maximum concurrent positions
input int    MaxDailyTrades         = 10;       // Maximum trades per day

input group "=== XAUUSD Specific Settings ==="
input double MinATR_Points          = 100.0;    // Minimum ATR for Gold (points)
input double MaxSpreadPoints        = 50.0;     // Maximum spread (points)
input double ATR_SL_Multiplier      = 2.0;      // Stop Loss ATR multiplier
input double ATR_TP_Multiplier      = 3.0;      // Take Profit ATR multiplier

input group "=== ICT Strategy Parameters ==="
input bool   UseLiquiditySweeps     = true;     // Use liquidity sweeps
input bool   UseFairValueGaps       = true;     // Use Fair Value Gaps
input bool   UseOrderBlocks         = true;     // Use Order Blocks
input bool   UseSilverBullet        = true;     // Use Silver Bullet
input bool   UseDailyWeeklyLiquidity = false;   // Use D1/W1 liquidity levels
input int    LiquidityLookback      = 50;       // Bars for liquidity lookback
input int    FVG_Lookback           = 20;       // Bars for FVG lookback
input double FVG_MinSizeATR         = 0.5;      // Minimum FVG size (x ATR)

enum ENUM_ENTRY_TIME_FILTER {
   ENTRY_KILL_ZONES_ONLY = 0,
   ENTRY_ENABLED_SESSIONS = 1,
   ENTRY_ANY_TIME = 2
};

input group "=== Session Settings ==="
input ENUM_ENTRY_TIME_FILTER EntryTimeFilter = ENTRY_ENABLED_SESSIONS; // Time filter for new entries
input bool   TradeAsianSession      = true;     // Trade Asian session
input bool   TradeLondonSession     = true;     // Trade London session
input bool   TradeNewYorkSession    = true;     // Trade New York session
input int    AsianStartHour         = 0;        // Asian session start
input int    AsianEndHour           = 6;        // Asian session end
input int    LondonStartHour        = 7;        // London session start
input int    LondonEndHour          = 11;       // London session end
input int    NewYorkStartHour       = 13;       // New York session start
input int    NewYorkEndHour         = 17;       // New York session end

input group "=== Silver Bullet Windows ==="
input bool   AsianSilverBullet      = false;
input int    AsianKillZoneStart     = 2;
input int    AsianKillZoneEnd       = 3;
input bool   LondonSilverBullet     = true;
input int    LondonKillZoneStart    = 8;
input int    LondonKillZoneEnd      = 9;
input bool   NewYorkSilverBullet    = true;
input int    NYKillZoneStart        = 15;
input int    NYKillZoneEnd          = 16;

input group "=== Position Management ==="
input bool   UseBreakEven           = true;
input double BE_TriggerATR          = 1.0;
input bool   UseTrailingStop        = true;
input double Trail_StartATR         = 1.5;
input double Trail_StepATR          = 0.5;
input bool   UsePartialClose        = true;
input double PartialClosePercent    = 50.0;
input double PartialCloseTriggerATR = 1.0;

input group "=== Execution Settings ==="
input int    SlippagePoints         = 10;
input int    OrderRetryCount        = 5;
input int    OrderRetryDelayMs      = 200;

input group "=== System Settings ==="
enum ENUM_LOG_LEVEL {
   LOG_NONE = 0,
   LOG_ERROR = 1,
   LOG_WARNING = 2,
   LOG_INFO = 3,
   LOG_DEBUG = 4
};
input ENUM_LOG_LEVEL LogLevel          = LOG_INFO;
input bool           UseAsyncExecution = true;
input bool           EnablePerformanceMode = true;
input bool           LogStatusChanges  = true;

input group "=== Dashboard Settings ==="
input bool ShowDashboard = true;
input int  DashboardX    = 10;
input int  DashboardY    = 20;

//+------------------------------------------------------------------+
//| Structures and Classes                                           |
//+------------------------------------------------------------------+

class CMarketData {
public:
   datetime time[10000];
   double   high[10000];
   double   low[10000];
   double   close[10000];
   double   volume[10000];
   int      dataIndex;
   CMarketData() : dataIndex(0) {}
   void AddBar(datetime t, double h, double l, double c, double v) {
      int idx = dataIndex % 10000;
      time[idx] = t;
      high[idx] = h;
      low[idx] = l;
      close[idx] = c;
      volume[idx] = v;
      dataIndex++;
   }
};

struct LiquidityLevel {
   double   price;
   datetime time;
   int      strength;
   bool     isHigh;
   bool     swept;
   double   volume;
};

struct FairValueGap {
   double   topPrice;
   double   bottomPrice;
   datetime time;
   bool     isBullish;
   bool     filled;
   double   size;
};

struct OrderBlock {
   double   topPrice;
   double   bottomPrice;
   datetime time;
   bool     isBullish;
   bool     mitigated;
   double   volume;
};

class CPositionTracker {
public:
   ulong    ticket;
   datetime openTime;
   double   openPrice;
   double   originalSL;
   double   originalTP;
   bool     partialClosed;
   bool     breakEvenSet;
   bool     trailingActive;
   double   peakProfit;
   double   currentRR;
   CPositionTracker() { Reset(); }
   void Reset() {
      ticket = 0;
      openTime = 0;
      openPrice = 0;
      originalSL = 0;
      originalTP = 0;
      partialClosed = false;
      breakEvenSet = false;
      trailingActive = false;
      peakProfit = 0;
      currentRR = 0;
   }
};

class CPositionTrackerPool {
private:
   CPositionTracker* m_pool[];
   int m_poolSize;
   int m_nextAvailable;
public:
   CPositionTrackerPool(int size = 100) {
      m_poolSize = size;
      ArrayResize(m_pool, m_poolSize);
      m_nextAvailable = 0;
      for(int i = 0; i < m_poolSize; i++)
         m_pool[i] = new CPositionTracker();
   }
   ~CPositionTrackerPool() {
      for(int i = 0; i < m_poolSize; i++)
         delete m_pool[i];
   }
   CPositionTracker* Acquire() {
      if(m_nextAvailable >= m_poolSize) {
         int oldSize = m_poolSize;
         m_poolSize *= 2;
         ArrayResize(m_pool, m_poolSize);
         for(int i = oldSize; i < m_poolSize; i++)
            m_pool[i] = new CPositionTracker();
      }
      return m_pool[m_nextAvailable++];
   }
   void Release(CPositionTracker* obj) {
      if(obj == NULL || m_nextAvailable <= 0) return;
      obj.Reset();
      m_nextAvailable--;
   }
};

//+------------------------------------------------------------------+
//| Main EA Class                                                    |
//+------------------------------------------------------------------+
class CUltimateICTGoldScalper {
private:
   CTrade         m_trade;
   CPositionInfo  m_position;
   CSymbolInfo    m_symbol;
   CAccountInfo   m_account;
   int            m_atrHandle;
   int            m_emaFastHandle;
   int            m_emaSlowHandle;
   int            m_volumeHandle;
   LiquidityLevel m_liquidityLevels[];
   FairValueGap   m_fairValueGaps[];
   OrderBlock     m_orderBlocks[];
   CMarketData    m_marketData;
   CPositionTrackerPool*          m_positionPool;
   CPositionTracker*               m_activePositions[];
   double         m_dayStartBalance;
   double         m_initialBalance;
   int            m_todayTradeCount;
   int            m_currentDayKey;
   datetime       m_lastTradeTime;
   double         m_currentATR;
   long           m_magicNumber;
   bool           m_initialized;
   string         m_dashboardPrefix;
   string         m_lastStatus;
   
   void LogError(string msg)   { if(LogLevel >= LOG_ERROR)   Print("[ERROR] ", msg); }
   void LogWarning(string msg) { if(LogLevel >= LOG_WARNING) Print("[WARN] ",  msg); }
   void LogInfo(string msg)    { if(LogLevel >= LOG_INFO)    Print("[INFO] ",  msg); }
   void LogDebug(string msg)   { if(LogLevel >= LOG_DEBUG)   Print("[DEBUG] ", msg); }

   string DashboardName(string suffix) {
      return m_dashboardPrefix + suffix;
   }

   string FormatMoney(double amount) {
      string currency = AccountInfoString(ACCOUNT_CURRENCY);
      if(currency == "") currency = "USD";
      return StringFormat("%.2f %s", amount, currency);
   }

   string FormatSignedMoney(double amount) {
      string currency = AccountInfoString(ACCOUNT_CURRENCY);
      string sign = (amount >= 0.0) ? "+" : "";
      if(currency == "") currency = "USD";
      return StringFormat("%s%.2f %s", sign, amount, currency);
   }

   void CreateDashboardLabel(string suffix, int yOffset, int fontSize) {
      string name = DashboardName(suffix);
      ObjectDelete(0, name);
      if(!ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0)) {
         LogWarning("Failed to create dashboard label: " + name);
         return;
      }
      ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(0, name, OBJPROP_XDISTANCE, DashboardX + 12);
      ObjectSetInteger(0, name, OBJPROP_YDISTANCE, DashboardY + yOffset);
      ObjectSetInteger(0, name, OBJPROP_COLOR, clrWhite);
      ObjectSetInteger(0, name, OBJPROP_FONTSIZE, fontSize);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_SELECTED, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
      ObjectSetString(0, name, OBJPROP_FONT, "Arial");
   }

   void CreateDashboard() {
      if(!ShowDashboard) return;

      string panelName = DashboardName("panel");
      ObjectDelete(0, panelName);
      if(!ObjectCreate(0, panelName, OBJ_RECTANGLE_LABEL, 0, 0, 0)) {
         LogWarning("Failed to create dashboard panel");
         return;
      }

      ObjectSetInteger(0, panelName, OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(0, panelName, OBJPROP_XDISTANCE, DashboardX);
      ObjectSetInteger(0, panelName, OBJPROP_YDISTANCE, DashboardY);
      ObjectSetInteger(0, panelName, OBJPROP_XSIZE, 340);
      ObjectSetInteger(0, panelName, OBJPROP_YSIZE, 244);
      ObjectSetInteger(0, panelName, OBJPROP_BGCOLOR, clrBlack);
      ObjectSetInteger(0, panelName, OBJPROP_COLOR, clrWhite);
      ObjectSetInteger(0, panelName, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, panelName, OBJPROP_SELECTED, false);
      ObjectSetInteger(0, panelName, OBJPROP_HIDDEN, true);

      CreateDashboardLabel("title", 10, 10);
      CreateDashboardLabel("initial", 32, 9);
      CreateDashboardLabel("current", 50, 9);
      CreateDashboardLabel("equity", 68, 9);
      CreateDashboardLabel("dailypl", 90, 9);
      CreateDashboardLabel("trades", 108, 9);
      CreateDashboardLabel("positions", 126, 9);
      CreateDashboardLabel("spread", 144, 9);
      CreateDashboardLabel("atr", 162, 9);
      CreateDashboardLabel("session", 180, 9);
      CreateDashboardLabel("bias", 198, 9);
      CreateDashboardLabel("status", 216, 9);
      ObjectSetString(0, DashboardName("title"), OBJPROP_TEXT, "BAKOME Gold Scalper");
      UpdateDashboard();
   }

   void UpdateDashboard() {
      if(!ShowDashboard) return;
      if(ObjectFind(0, DashboardName("panel")) < 0) {
         CreateDashboard();
         if(ObjectFind(0, DashboardName("panel")) < 0)
            return;
      }

      double equity = AccountInfoDouble(ACCOUNT_EQUITY);
      double dailyPL = equity - m_dayStartBalance;
      double dailyPLPercent = (m_dayStartBalance > 0.0) ? dailyPL / m_dayStartBalance * 100.0 : 0.0;
      string dailySign = (dailyPLPercent >= 0.0) ? "+" : "";

      ObjectSetString(0, DashboardName("initial"), OBJPROP_TEXT, "Initial Amount: " + FormatMoney(m_initialBalance));
      ObjectSetString(0, DashboardName("current"), OBJPROP_TEXT, "Current Amount: " + FormatMoney(AccountInfoDouble(ACCOUNT_BALANCE)));
      ObjectSetString(0, DashboardName("equity"), OBJPROP_TEXT, "Equity: " + FormatMoney(equity));
      ObjectSetString(0, DashboardName("dailypl"), OBJPROP_TEXT, "Daily P/L: " + FormatSignedMoney(dailyPL) + StringFormat(" (%s%.2f%%)", dailySign, dailyPLPercent));
      ObjectSetString(0, DashboardName("trades"), OBJPROP_TEXT, StringFormat("Trades Taken: %d / %d", m_todayTradeCount, MaxDailyTrades));
      ObjectSetString(0, DashboardName("positions"), OBJPROP_TEXT, StringFormat("Open Positions: %d / %d", CountOpenPositions(), MaxPositions));
      ObjectSetString(0, DashboardName("spread"), OBJPROP_TEXT, StringFormat("Spread: %.0f / %.0f pts", GetSpreadPoints(), MaxSpreadPoints));
      ObjectSetString(0, DashboardName("atr"), OBJPROP_TEXT, StringFormat("ATR: %.0f / %.0f pts", GetATRPoints(), MinATR_Points));
      ObjectSetString(0, DashboardName("session"), OBJPROP_TEXT, "Session: " + GetSessionName() + " | Kill Zone: " + (IsInKillZone() ? "Yes" : "No"));
      ObjectSetString(0, DashboardName("bias"), OBJPROP_TEXT, "Bias: " + GetBiasText(GetMarketBias()));
      ObjectSetString(0, DashboardName("status"), OBJPROP_TEXT, "Status: " + GetEAStatus());
      ChartRedraw(0);
   }

   void DeleteDashboard() {
      if(m_dashboardPrefix == "") return;
      ObjectDelete(0, DashboardName("panel"));
      ObjectDelete(0, DashboardName("title"));
      ObjectDelete(0, DashboardName("initial"));
      ObjectDelete(0, DashboardName("current"));
      ObjectDelete(0, DashboardName("equity"));
      ObjectDelete(0, DashboardName("dailypl"));
      ObjectDelete(0, DashboardName("trades"));
      ObjectDelete(0, DashboardName("positions"));
      ObjectDelete(0, DashboardName("spread"));
      ObjectDelete(0, DashboardName("atr"));
      ObjectDelete(0, DashboardName("session"));
      ObjectDelete(0, DashboardName("bias"));
      ObjectDelete(0, DashboardName("status"));
      ChartRedraw(0);
   }

   void LogStatusChange() {
      if(!LogStatusChanges || LogLevel < LOG_INFO)
         return;

      string status = GetEAStatus();
      if(status == m_lastStatus)
         return;

      m_lastStatus = status;
      LogInfo("Status: " + status);
   }
   
   long GenerateMagicNumber() {
      string str = _Symbol + IntegerToString(Period());
      uchar arr[];
      StringToCharArray(str, arr);
      long hash = 0;
      for(int i = 0; i < ArraySize(arr); i++)
         hash = (hash * 31 + arr[i]) % 9999999;
      return 100000 + hash;
   }
   
   bool IsRecoverableError(uint errorCode) {
      switch(errorCode) {
         case TRADE_RETCODE_REQUOTE:
         case TRADE_RETCODE_PRICE_CHANGED:
         case TRADE_RETCODE_TIMEOUT:
         case TRADE_RETCODE_CONNECTION:
            return true;
         default:
            return false;
      }
   }

   bool RefreshSymbolRates() {
      if(!m_symbol.RefreshRates()) {
         LogWarning("Failed to refresh symbol rates");
         return false;
      }
      if(m_symbol.Bid() <= 0.0 || m_symbol.Ask() <= 0.0) {
         LogWarning(StringFormat("Invalid symbol rates. Bid: %.5f Ask: %.5f", m_symbol.Bid(), m_symbol.Ask()));
         return false;
      }
      return true;
   }

   ENUM_ORDER_TYPE_FILLING GetOrderFillingMode() {
      int filling = (int)SymbolInfoInteger(_Symbol, SYMBOL_FILLING_MODE);
      ENUM_SYMBOL_TRADE_EXECUTION execution = (ENUM_SYMBOL_TRADE_EXECUTION)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_EXEMODE);

      if((filling & (int)SYMBOL_FILLING_IOC) == (int)SYMBOL_FILLING_IOC)
         return ORDER_FILLING_IOC;
      if((filling & (int)SYMBOL_FILLING_FOK) == (int)SYMBOL_FILLING_FOK)
         return ORDER_FILLING_FOK;
      if(execution != SYMBOL_TRADE_EXECUTION_MARKET)
         return ORDER_FILLING_RETURN;

      LogWarning(StringFormat("No explicit filling mode for %s. Filling flags: %d, execution: %d. Falling back to IOC.", _Symbol, filling, (int)execution));
      return ORDER_FILLING_IOC;
   }
   
   bool ExecuteWithRetry(MqlTradeRequest &request, MqlTradeResult &result) {
      for(int attempt = 0; attempt < OrderRetryCount; attempt++) {
         ZeroMemory(result);
         if(OrderSend(request, result)) {
            if(result.retcode == TRADE_RETCODE_DONE) return true;
         }
         if(!IsRecoverableError(result.retcode)) break;
         Sleep(OrderRetryDelayMs * (int)MathPow(2, attempt));
      }
      return false;
   }
   
   double GetAverageVolume(int periods) {
      long volumes[];
      ArraySetAsSeries(volumes, true);
      if(CopyTickVolume(_Symbol, PERIOD_M5, 0, periods, volumes) <= 0) return 0;
      double sum = 0;
      for(int i = 0; i < periods; i++) sum += volumes[i];
      return sum / periods;
   }
   
   double GetCurrentVolumeRatio() {
      long currentVolume = iVolume(_Symbol, PERIOD_M5, 0);
      double avgVolume = GetAverageVolume(20);
      if(avgVolume > 0) return currentVolume / avgVolume;
      return 1.0;
   }

   int NormalizeHour(int hour) {
      int normalized = hour % 24;
      if(normalized < 0)
         normalized += 24;
      return normalized;
   }

   int CurrentHour() {
      MqlDateTime dt;
      TimeToStruct(TimeCurrent(), dt);
      return dt.hour;
   }

   bool IsHourInRange(int hour, int startHour, int endHour) {
      hour = NormalizeHour(hour);
      startHour = NormalizeHour(startHour);
      endHour = NormalizeHour(endHour);

      if(startHour == endHour)
         return true;
      if(startHour < endHour)
         return (hour >= startHour && hour < endHour);
      return (hour >= startHour || hour < endHour);
   }

   int CountOpenPositions() {
      int openPositions = 0;
      for(int i = 0; i < PositionsTotal(); i++)
         if(m_position.SelectByIndex(i) && m_position.Magic() == m_magicNumber)
            openPositions++;
      return openPositions;
   }

   double GetSpreadPoints() {
      long spread = SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
      if(spread > 0)
         return (double)spread;

      double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
      if(point <= 0.0)
         return 0.0;
      return (SymbolInfoDouble(_Symbol, SYMBOL_ASK) - SymbolInfoDouble(_Symbol, SYMBOL_BID)) / point;
   }

   double GetATRPoints() {
      double point = m_symbol.Point();
      if(point <= 0.0)
         point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
      if(point <= 0.0)
         return 0.0;
      return m_currentATR / point;
   }

   string GetBiasText(int bias) {
      if(bias == (int)POSITION_TYPE_BUY) return "Buy";
      if(bias == (int)POSITION_TYPE_SELL) return "Sell";
      return "Neutral";
   }

   int GetDayKey(datetime timeValue) {
      MqlDateTime dt;
      TimeToStruct(timeValue, dt);
      return dt.year * 10000 + dt.mon * 100 + dt.day;
   }
   
   bool IsInKillZone() {
      if(!UseSilverBullet) return false;
      int hour = CurrentHour();
      if(AsianSilverBullet && IsHourInRange(hour, AsianKillZoneStart, AsianKillZoneEnd)) return true;
      if(LondonSilverBullet && IsHourInRange(hour, LondonKillZoneStart, LondonKillZoneEnd)) return true;
      if(NewYorkSilverBullet && IsHourInRange(hour, NYKillZoneStart, NYKillZoneEnd)) return true;
      return false;
   }
   
   bool IsInTradingSession() {
      int hour = CurrentHour();
      if(TradeAsianSession && IsHourInRange(hour, AsianStartHour, AsianEndHour)) return true;
      if(TradeLondonSession && IsHourInRange(hour, LondonStartHour, LondonEndHour)) return true;
      if(TradeNewYorkSession && IsHourInRange(hour, NewYorkStartHour, NewYorkEndHour)) return true;
      return false;
   }

   bool IsTradingTimeAllowed() {
      if(EntryTimeFilter == ENTRY_ANY_TIME)
         return true;
      if(EntryTimeFilter == ENTRY_ENABLED_SESSIONS)
         return IsInTradingSession();
      if(!UseSilverBullet)
         return IsInTradingSession();
      return IsInKillZone();
   }

   string GetSessionName() {
      int hour = CurrentHour();
      string session = "";

      if(TradeAsianSession && IsHourInRange(hour, AsianStartHour, AsianEndHour))
         session = "Asia";
      if(TradeLondonSession && IsHourInRange(hour, LondonStartHour, LondonEndHour))
         session = (session == "") ? "London" : session + "+London";
      if(TradeNewYorkSession && IsHourInRange(hour, NewYorkStartHour, NewYorkEndHour))
         session = (session == "") ? "New York" : session + "+NY";

      if(session == "")
         return "Outside";
      return session;
   }

   string GetDailyLimitStatus() {
      if(m_todayTradeCount >= MaxDailyTrades)
         return "Max daily trades reached";
      if(m_dayStartBalance <= 0.0)
         return "Waiting for balance";

      double currentEquity = AccountInfoDouble(ACCOUNT_EQUITY);
      double dailyPL = (currentEquity - m_dayStartBalance) / m_dayStartBalance * 100.0;
      if(dailyPL <= -MaxDailyRiskPercent)
         return "Daily loss limit reached";
      if(dailyPL >= MaxDailyProfitPercent)
         return "Daily profit target reached";
      return "";
   }

   string GetEAStatus() {
      string limitStatus = GetDailyLimitStatus();
      if(limitStatus != "")
         return limitStatus;
      if(CountOpenPositions() >= MaxPositions)
         return "Max positions reached";
      if(GetSpreadPoints() > MaxSpreadPoints)
         return "Spread too high";
      if(GetATRPoints() <= 0.0)
         return "Waiting for ATR";
      if(GetATRPoints() < MinATR_Points)
         return "ATR too low";
      if(!IsTradingTimeAllowed()) {
         if(EntryTimeFilter == ENTRY_KILL_ZONES_ONLY && UseSilverBullet)
            return "Waiting for kill zone";
         return "Outside enabled session";
      }

      int bias = GetMarketBias();
      if(bias == (int)POSITION_TYPE_BUY)
         return "Ready: buy bias";
      if(bias == (int)POSITION_TYPE_SELL)
         return "Ready: sell bias";
      return "Waiting for bias";
   }
   
   int GetMarketBias() {
      double emaBuffer[];
      ArraySetAsSeries(emaBuffer, true);
      if(CopyBuffer(m_emaSlowHandle, 0, 0, 1, emaBuffer) <= 0) return -1;
      double currentPrice = iClose(_Symbol, PERIOD_M5, 0);
      if(currentPrice > emaBuffer[0]) return (int)POSITION_TYPE_BUY;
      if(currentPrice < emaBuffer[0]) return (int)POSITION_TYPE_SELL;
      return -1;
   }
   
   void AddLiquidityLevel(double price, bool isHigh, datetime time) {
      int size = ArraySize(m_liquidityLevels);
      ArrayResize(m_liquidityLevels, size + 1);
      m_liquidityLevels[size].price = price;
      m_liquidityLevels[size].isHigh = isHigh;
      m_liquidityLevels[size].time = time;
      m_liquidityLevels[size].swept = false;
      m_liquidityLevels[size].strength = CalculateLevelStrength(price);
      long volumes[1];
      if(CopyTickVolume(_Symbol, PERIOD_M5, 0, 1, volumes) > 0)
         m_liquidityLevels[size].volume = (double)volumes[0];
   }
   
   int CalculateLevelStrength(double price) {
      int strength = 0;
      double tolerance = m_currentATR * 0.1;
      for(int i = 1; i < 100; i++) {
         double high = iHigh(_Symbol, PERIOD_M5, i);
         double low = iLow(_Symbol, PERIOD_M5, i);
         if(MathAbs(high - price) < tolerance || MathAbs(low - price) < tolerance)
            strength++;
      }
      return strength;
   }
   
   void UpdateLiquidityLevels() {
      ArrayResize(m_liquidityLevels, 0);
      for(int i = 3; i < LiquidityLookback; i++) {
         if(iHigh(_Symbol, PERIOD_M5, i) > iHigh(_Symbol, PERIOD_M5, i-1) &&
            iHigh(_Symbol, PERIOD_M5, i) > iHigh(_Symbol, PERIOD_M5, i-2) &&
            iHigh(_Symbol, PERIOD_M5, i) > iHigh(_Symbol, PERIOD_M5, i+1) &&
            iHigh(_Symbol, PERIOD_M5, i) > iHigh(_Symbol, PERIOD_M5, i+2)) {
            AddLiquidityLevel(iHigh(_Symbol, PERIOD_M5, i), true, iTime(_Symbol, PERIOD_M5, i));
         }
         if(iLow(_Symbol, PERIOD_M5, i) < iLow(_Symbol, PERIOD_M5, i-1) &&
            iLow(_Symbol, PERIOD_M5, i) < iLow(_Symbol, PERIOD_M5, i-2) &&
            iLow(_Symbol, PERIOD_M5, i) < iLow(_Symbol, PERIOD_M5, i+1) &&
            iLow(_Symbol, PERIOD_M5, i) < iLow(_Symbol, PERIOD_M5, i+2)) {
            AddLiquidityLevel(iLow(_Symbol, PERIOD_M5, i), false, iTime(_Symbol, PERIOD_M5, i));
         }
      }
      if(UseDailyWeeklyLiquidity) {
         AddLiquidityLevel(iHigh(_Symbol, PERIOD_D1, 0), true, 0);
         AddLiquidityLevel(iLow(_Symbol, PERIOD_D1, 0), false, 0);
         AddLiquidityLevel(iHigh(_Symbol, PERIOD_W1, 0), true, 0);
         AddLiquidityLevel(iLow(_Symbol, PERIOD_W1, 0), false, 0);
      }
   }
   
   void UpdateFairValueGaps() {
      if(!UseFairValueGaps) return;
      ArrayResize(m_fairValueGaps, 0);
      for(int i = 2; i < FVG_Lookback; i++) {
         double currentLow = iLow(_Symbol, PERIOD_M5, i);
         double prevHigh = iHigh(_Symbol, PERIOD_M5, i-1);
         if(currentLow > prevHigh) {
            double gapSize = currentLow - prevHigh;
            if(gapSize >= m_currentATR * FVG_MinSizeATR) {
               int size = ArraySize(m_fairValueGaps);
               ArrayResize(m_fairValueGaps, size + 1);
               m_fairValueGaps[size].topPrice = currentLow;
               m_fairValueGaps[size].bottomPrice = prevHigh;
               m_fairValueGaps[size].time = iTime(_Symbol, PERIOD_M5, i);
               m_fairValueGaps[size].isBullish = true;
               m_fairValueGaps[size].filled = false;
               m_fairValueGaps[size].size = gapSize;
            }
         }
         double currentHigh = iHigh(_Symbol, PERIOD_M5, i);
         double prevLow = iLow(_Symbol, PERIOD_M5, i-1);
         if(currentHigh < prevLow) {
            double gapSize = prevLow - currentHigh;
            if(gapSize >= m_currentATR * FVG_MinSizeATR) {
               int size = ArraySize(m_fairValueGaps);
               ArrayResize(m_fairValueGaps, size + 1);
               m_fairValueGaps[size].topPrice = currentHigh;
               m_fairValueGaps[size].bottomPrice = prevLow;
               m_fairValueGaps[size].time = iTime(_Symbol, PERIOD_M5, i);
               m_fairValueGaps[size].isBullish = false;
               m_fairValueGaps[size].filled = false;
               m_fairValueGaps[size].size = gapSize;
            }
         }
      }
   }
   
   void UpdateOrderBlocks() {
      if(!UseOrderBlocks) return;
      ArrayResize(m_orderBlocks, 0);
      for(int i = 1; i < 50; i++) {
         if(iClose(_Symbol, PERIOD_M5, i) < iOpen(_Symbol, PERIOD_M5, i)) { // bearish
            if(iClose(_Symbol, PERIOD_M5, i-1) > iOpen(_Symbol, PERIOD_M5, i-1)) { // bullish next
               int size = ArraySize(m_orderBlocks);
               ArrayResize(m_orderBlocks, size + 1);
               m_orderBlocks[size].topPrice = iHigh(_Symbol, PERIOD_M5, i);
               m_orderBlocks[size].bottomPrice = iLow(_Symbol, PERIOD_M5, i);
               m_orderBlocks[size].time = iTime(_Symbol, PERIOD_M5, i);
               m_orderBlocks[size].isBullish = true;
               m_orderBlocks[size].mitigated = false;
               long volumes[1];
               if(CopyTickVolume(_Symbol, PERIOD_M5, i, 1, volumes) > 0)
                  m_orderBlocks[size].volume = (double)volumes[0];
            }
         }
         if(iClose(_Symbol, PERIOD_M5, i) > iOpen(_Symbol, PERIOD_M5, i)) { // bullish
            if(iClose(_Symbol, PERIOD_M5, i-1) < iOpen(_Symbol, PERIOD_M5, i-1)) { // bearish next
               int size = ArraySize(m_orderBlocks);
               ArrayResize(m_orderBlocks, size + 1);
               m_orderBlocks[size].topPrice = iHigh(_Symbol, PERIOD_M5, i);
               m_orderBlocks[size].bottomPrice = iLow(_Symbol, PERIOD_M5, i);
               m_orderBlocks[size].time = iTime(_Symbol, PERIOD_M5, i);
               m_orderBlocks[size].isBullish = false;
               m_orderBlocks[size].mitigated = false;
               long volumes[1];
               if(CopyTickVolume(_Symbol, PERIOD_M5, i, 1, volumes) > 0)
                  m_orderBlocks[size].volume = (double)volumes[0];
            }
         }
      }
   }
   
   void UpdateMarketData() {
      double atrBuffer[];
      ArraySetAsSeries(atrBuffer, true);
      if(CopyBuffer(m_atrHandle, 0, 0, 1, atrBuffer) > 0)
         m_currentATR = atrBuffer[0];
      m_marketData.AddBar(TimeCurrent(), iHigh(_Symbol, PERIOD_M5, 0), iLow(_Symbol, PERIOD_M5, 0), iClose(_Symbol, PERIOD_M5, 0), (double)iVolume(_Symbol, PERIOD_M5, 0));
   }
   
   bool CheckDailyLimits() {
      string status = GetDailyLimitStatus();
      if(status == "")
         return false;

      if(status == "Daily loss limit reached")
         LogWarning(status);
      else
         LogInfo(status);
      return true;
   }
   
   void ResetDailyStats() {
      m_todayTradeCount = 0;
      m_dayStartBalance = AccountInfoDouble(ACCOUNT_BALANCE);
      m_currentDayKey = GetDayKey(TimeCurrent());
      m_lastStatus = "";
      LogInfo(StringFormat("Daily stats reset. Day: %d Start balance: %.2f", m_currentDayKey, m_dayStartBalance));
   }

   void CheckNewTradingDay() {
      int dayKey = GetDayKey(TimeCurrent());
      if(m_currentDayKey == dayKey)
         return;

      ResetDailyStats();
   }
   
   bool CanOpenNewPosition() {
      int openPositions = CountOpenPositions();
      if(openPositions >= MaxPositions) return false;
      double spread = GetSpreadPoints();
      if(spread > MaxSpreadPoints) return false;
      if(GetATRPoints() < MinATR_Points) return false;
      if(!IsTradingTimeAllowed()) return false;
      return true;
   }
   
   void CalculateBullishEntry(double &entry, double &sl, double &tp) {
      entry = m_symbol.Ask();
      sl = entry - (m_currentATR * ATR_SL_Multiplier);
      tp = entry + (m_currentATR * ATR_TP_Multiplier);
      entry = NormalizeDouble(entry, (int)m_symbol.Digits());
      sl   = NormalizeDouble(sl,   (int)m_symbol.Digits());
      tp   = NormalizeDouble(tp,   (int)m_symbol.Digits());
   }
   
   void CalculateBearishEntry(double &entry, double &sl, double &tp) {
      entry = m_symbol.Bid();
      sl = entry + (m_currentATR * ATR_SL_Multiplier);
      tp = entry - (m_currentATR * ATR_TP_Multiplier);
      entry = NormalizeDouble(entry, (int)m_symbol.Digits());
      sl   = NormalizeDouble(sl,   (int)m_symbol.Digits());
      tp   = NormalizeDouble(tp,   (int)m_symbol.Digits());
   }
   
   int VolumeDigits(double step) {
      int digits = 0;
      while(digits < 8 && MathAbs(step - NormalizeDouble(step, digits)) > 0.00000001)
         digits++;
      return digits;
   }

   double NormalizeVolumeDown(double volume) {
      double minVolume = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
      double maxVolume = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
      double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);

      if(minVolume <= 0.0) minVolume = 0.01;
      if(maxVolume <= 0.0) maxVolume = 100.0;
      if(step <= 0.0) step = minVolume;

      volume = MathMin(volume, maxVolume);
      if(volume < minVolume)
         return 0.0;

      double steps = MathFloor((volume - minVolume) / step + 0.0000001);
      double normalized = minVolume + steps * step;
      normalized = MathMax(minVolume, MathMin(normalized, maxVolume));
      return NormalizeDouble(normalized, VolumeDigits(step));
   }

   double CapVolumeByMargin(ENUM_ORDER_TYPE type, double volume, double price) {
      double freeMargin = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
      double marginLimitPercent = MathMax(0.0, MathMin(MaxMarginUsagePercent, 100.0));
      double allowedMargin = freeMargin * marginLimitPercent / 100.0;
      double margin = 0.0;

      volume = NormalizeVolumeDown(volume);
      if(volume <= 0.0 || allowedMargin <= 0.0)
         return 0.0;

      if(!OrderCalcMargin(type, _Symbol, volume, price, margin)) {
         LogWarning(StringFormat("OrderCalcMargin failed for %.2f lots. Error: %d", volume, GetLastError()));
         return volume;
      }
      if(margin <= allowedMargin)
         return volume;

      double marginPerLot = margin / volume;
      if(marginPerLot <= 0.0)
         return 0.0;

      volume = NormalizeVolumeDown(allowedMargin / marginPerLot);
      while(volume > 0.0) {
         ResetLastError();
         if(OrderCalcMargin(type, _Symbol, volume, price, margin) && margin <= allowedMargin)
            return volume;

         double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
         if(step <= 0.0)
            step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
         volume = NormalizeVolumeDown(volume - step);
      }
      return 0.0;
   }

   double RiskLot(double riskPercent, ENUM_ORDER_TYPE type, double entry, double sl) {
      double balance = AccountInfoDouble(ACCOUNT_BALANCE);
      double riskAmount = balance * riskPercent / 100.0;
      double stopDistance = MathAbs(entry - sl);
      double tickSize = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
      double tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE_LOSS);

      if(tickValue <= 0.0)
         tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);

      if(riskAmount <= 0.0 || stopDistance <= 0.0 || tickSize <= 0.0 || tickValue <= 0.0) {
         LogWarning(StringFormat("Cannot calculate lot. Risk: %.2f StopDistance: %.5f TickSize: %.5f TickValue: %.5f",
                                 riskAmount, stopDistance, tickSize, tickValue));
         return 0.0;
      }

      double riskPerLot = (stopDistance / tickSize) * tickValue;
      if(riskPerLot <= 0.0)
         return 0.0;

      double rawLot = riskAmount / riskPerLot;
      double lot = NormalizeVolumeDown(rawLot);
      double minVolume = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
      if(minVolume <= 0.0)
         minVolume = 0.01;

      if(lot <= 0.0) {
         if(!AllowMinLotWhenRiskTooSmall) {
            LogWarning(StringFormat("Risk-based lot %.5f is below minimum %.2f; trade skipped", rawLot, minVolume));
            return 0.0;
         }
         lot = minVolume;
         LogWarning(StringFormat("Risk-based lot %.5f is below minimum %.2f; using minimum lot", rawLot, minVolume));
      }

      lot = CapVolumeByMargin(type, lot, entry);
      if(lot <= 0.0) {
         LogWarning(StringFormat("Not enough free margin for minimum %s volume %.2f", _Symbol, minVolume));
         return 0.0;
      }

      LogInfo(StringFormat("Lot size %.2f | Risk %.2f | Risk/lot %.2f | FreeMargin %.2f",
                           lot, riskAmount, riskPerLot, AccountInfoDouble(ACCOUNT_MARGIN_FREE)));
      return lot;
   }
   
   void ApplyBreakEven(CPositionTracker &pos) {
      if(!UseBreakEven || pos.breakEvenSet) return;
      double beTrigger = m_currentATR * BE_TriggerATR;
      if(m_position.SelectByTicket(pos.ticket)) {
         if(m_position.Profit() >= beTrigger) {
            double entry = m_position.PriceOpen();
            m_trade.PositionModify(pos.ticket, entry, m_position.TakeProfit());
            pos.breakEvenSet = true;
         }
      }
   }
   
   void ManageTrailingStop(CPositionTracker &pos) {
      if(!UseTrailingStop || pos.trailingActive) return;
      if(m_position.SelectByTicket(pos.ticket)) {
         double profit = m_position.Profit();
         double trailStart = m_currentATR * Trail_StartATR;
         if(profit >= trailStart) {
            if(m_position.PositionType() == POSITION_TYPE_BUY) {
               double newSL = m_symbol.Bid() - (m_currentATR * Trail_StepATR);
               if(newSL > m_position.StopLoss() || m_position.StopLoss() == 0) {
                  m_trade.PositionModify(pos.ticket, newSL, m_position.TakeProfit());
                  pos.trailingActive = true;
               }
            } else {
               double newSL = m_symbol.Ask() + (m_currentATR * Trail_StepATR);
               if(newSL < m_position.StopLoss() || m_position.StopLoss() == 0) {
                  m_trade.PositionModify(pos.ticket, newSL, m_position.TakeProfit());
                  pos.trailingActive = true;
               }
            }
         }
      }
   }
   
   void ExecuteTrade(ENUM_ORDER_TYPE type) {
      if(!RefreshSymbolRates() || CheckDailyLimits() || !CanOpenNewPosition()) return;
      double entry, sl, tp;
      if(type == ORDER_TYPE_BUY) CalculateBullishEntry(entry, sl, tp);
      else CalculateBearishEntry(entry, sl, tp);
      double lot = RiskLot(RiskPercent, type, entry, sl);
      if(lot <= 0.0)
         return;
      MqlTradeRequest request = {};
      MqlTradeResult result = {};
      request.action = TRADE_ACTION_DEAL;
      request.symbol = _Symbol;
      request.volume = lot;
      request.type = type;
      request.price = entry;
      request.sl = sl;
      request.tp = tp;
      request.deviation = SlippagePoints;
      request.magic = m_magicNumber;
      request.comment = "BAKOME_ICT_EA";
      request.type_filling = GetOrderFillingMode();
      request.type_time = ORDER_TIME_GTC;
      if(ExecuteWithRetry(request, result)) {
         LogInfo(StringFormat("Executed %s %.2f @ %.2f", (type==ORDER_TYPE_BUY)?"BUY":"SELL", lot, entry));
         m_todayTradeCount++;
         CPositionTracker* pos = m_positionPool.Acquire();
         pos.ticket = result.order;
         pos.openTime = TimeCurrent();
         pos.openPrice = entry;
         pos.originalSL = sl;
         pos.originalTP = tp;
         ArrayResize(m_activePositions, ArraySize(m_activePositions)+1);
         m_activePositions[ArraySize(m_activePositions)-1] = pos;
      } else LogError(StringFormat("Order failed: %d", result.retcode));
   }
   
public:
   CUltimateICTGoldScalper() {
      m_positionPool = new CPositionTrackerPool(5);
      m_atrHandle = INVALID_HANDLE;
      m_emaFastHandle = INVALID_HANDLE;
      m_emaSlowHandle = INVALID_HANDLE;
      m_volumeHandle = INVALID_HANDLE;
      m_dayStartBalance = 0.0;
      m_initialBalance = 0.0;
      m_todayTradeCount = 0;
      m_currentDayKey = 0;
      m_lastTradeTime = 0;
      m_currentATR = 0.0;
      m_magicNumber = 0;
      m_initialized = false;
      m_dashboardPrefix = "";
      m_lastStatus = "";
   }
   ~CUltimateICTGoldScalper() { delete m_positionPool; }
   
   bool Init() {
      m_symbol.Name(_Symbol);
      m_symbol.Refresh();
      m_atrHandle = iATR(_Symbol, PERIOD_M5, 14);
      m_emaFastHandle = iMA(_Symbol, PERIOD_H1, 34, 0, MODE_EMA, PRICE_CLOSE);
      m_emaSlowHandle = iMA(_Symbol, PERIOD_H4, 200, 0, MODE_EMA, PRICE_CLOSE);
      if(m_atrHandle==INVALID_HANDLE || m_emaFastHandle==INVALID_HANDLE || m_emaSlowHandle==INVALID_HANDLE) {
         LogError("Indicators failed");
         return false;
      }
      m_magicNumber = GenerateMagicNumber();
      m_dayStartBalance = AccountInfoDouble(ACCOUNT_BALANCE);
      m_initialBalance = m_dayStartBalance;
      m_currentDayKey = GetDayKey(TimeCurrent());
      m_dashboardPrefix = "BAKOME_DASH_" + IntegerToString(m_magicNumber) + "_";
      m_todayTradeCount = 0;
      m_initialized = true;
      CreateDashboard();
      LogInfo("BAKOME EA initialized. Magic: " + IntegerToString(m_magicNumber));
      return true;
   }
   
   void OnTick() {
      if(!m_initialized) return;
      CheckNewTradingDay();
      UpdateMarketData();
      UpdateLiquidityLevels();
      UpdateFairValueGaps();
      UpdateOrderBlocks();
      LogStatusChange();
      for(int i=0; i<ArraySize(m_activePositions); i++) {
         CPositionTracker* pos = m_activePositions[i];
         if(pos == NULL || !m_position.SelectByTicket(pos.ticket) || m_position.Time() == 0) {
            if(pos != NULL)
               m_positionPool.Release(pos);
            ArrayRemove(m_activePositions, i, 1);
            i--;
            continue;
         }
         if(m_position.StopLoss() == 0 && m_position.Profit() > 0) ApplyBreakEven(*pos);
         ManageTrailingStop(*pos);
      }
      if(IsTradingTimeAllowed()) {
         int bias = GetMarketBias();
         if(bias == (int)POSITION_TYPE_BUY) ExecuteTrade(ORDER_TYPE_BUY);
         else if(bias == (int)POSITION_TYPE_SELL) ExecuteTrade(ORDER_TYPE_SELL);
      }
      UpdateDashboard();
   }

   void Deinit() {
      DeleteDashboard();
   }
};

CUltimateICTGoldScalper EA;

void OnInit() { if(!EA.Init()) ExpertRemove(); }
void OnTick() { EA.OnTick(); }
void OnDeinit(const int reason) { EA.Deinit(); Print("EA removed: ", reason); }
