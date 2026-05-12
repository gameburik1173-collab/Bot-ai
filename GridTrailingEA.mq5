//+------------------------------------------------------------------+
//|                                              GridTrailingEA.mq5  |
//|                                  Grid + Trailing Stop Virtual EA |
//|                                                                  |
//|  Strategi:                                                       |
//|   - Buka posisi awal (Buy atau Sell) sesuai arah yang dipilih.   |
//|   - Jika harga bergerak melawan, pasang VIRTUAL STOP ORDER       |
//|     (buy-stop / sell-stop) di grid berikutnya. Ketika harga      |
//|     menyentuh level virtual, EA mengirim MARKET ORDER ke broker. |
//|   - Semua posisi dikelola dengan VIRTUAL TRAILING STOP dan       |
//|     VIRTUAL TAKE-PROFIT (disimpan di memori EA, bukan di server).|
//|   - Tidak ada OrderSend pending / OrderModify berulang sehingga  |
//|     tidak kena limit aktivitas broker.                           |
//|                                                                  |
//|  Proteksi:                                                       |
//|   - Max spread (points) sebelum entry.                           |
//|   - Deviation (slippage) saat market order.                      |
//|   - Retry jika requote / off-quote.                              |
//+------------------------------------------------------------------+
#property copyright "Bot-ai"
#property version   "1.00"
#property strict

#include <Trade\Trade.mqh>
#include <Trade\SymbolInfo.mqh>
#include <Trade\PositionInfo.mqh>

//--- Input parameters ------------------------------------------------
enum ENUM_DIRECTION { DIR_BUY=0, DIR_SELL=1, DIR_AUTO=2 };

input group "=== Strategi Grid ==="
input ENUM_DIRECTION InpDirection      = DIR_AUTO;   // Arah awal
input double         InpLotStart       = 0.01;      // Lot awal
input double         InpLotMultiplier  = 1.0;       // Multiplier lot (1.0 = flat, >1 martingale)
input int            InpGridStepPoints = 200;       // Jarak antar grid (points)
input int            InpMaxGridLevels  = 10;        // Jumlah maksimum level grid

input group "=== Virtual SL / TP / Trailing ==="
input int            InpTakeProfitPts  = 400;       // Virtual Take Profit (points) per basket - 0=off
input int            InpStopLossPts    = 0;         // Virtual Stop Loss per basket (points) - 0=off
input int            InpTrailStartPts  = 300;       // Aktifkan trailing setelah profit ... points
input int            InpTrailStepPts   = 150;       // Jarak trailing di belakang harga (points)

input group "=== Proteksi Broker ==="
input int            InpMaxSpreadPts   = 50;        // Max spread diijinkan (points)
input int            InpSlippagePts    = 20;        // Deviation / slippage (points)
input int            InpRetryAttempts  = 3;         // Retry saat requote
input int            InpRetryDelayMs   = 500;       // Delay antar retry (ms)
input ulong          InpMagic          = 20260512;  // Magic number
input string         InpComment        = "GridTrailEA";

input group "=== Kontrol Waktu ==="
input bool           InpUseTimeFilter  = false;     // Aktifkan filter jam
input int            InpStartHour      = 0;         // Jam mulai (server time)
input int            InpEndHour        = 24;        // Jam selesai (server time)

//--- Runtime state ---------------------------------------------------
CTrade         Trade;
CSymbolInfo    Sym;
CPositionInfo  Pos;

// Virtual stop order (hanya satu aktif: level grid berikutnya)
struct VirtualStopOrder
{
   bool     active;
   bool     isBuy;         // true = buy stop, false = sell stop
   double   triggerPrice;  // harga aktivasi
   double   lot;
   int      level;
};
VirtualStopOrder g_virtualStop;

// Virtual basket management
double   g_basketTrailPrice  = 0.0;   // harga SL virtual basket (0 = belum aktif)
datetime g_lastBarTime       = 0;
int      g_gridLevelsOpened  = 0;     // jumlah level yang sudah ter-eksekusi

//+------------------------------------------------------------------+
int OnInit()
{
   if(!Sym.Name(_Symbol))
   {
      Print("Gagal memuat simbol: ", _Symbol);
      return INIT_FAILED;
   }
   Sym.RefreshRates();

   Trade.SetExpertMagicNumber(InpMagic);
   Trade.SetDeviationInPoints((ulong)InpSlippagePts);
   Trade.SetTypeFillingBySymbol(_Symbol);
   Trade.SetMarginMode();
   Trade.LogLevel(LOG_LEVEL_ERRORS);

   ResetVirtualStop();
   SyncStateFromOpenPositions();

   Print("GridTrailingEA initialized. Magic=", InpMagic,
         " MinStopLevel=", Sym.StopsLevel(),
         " Point=", Sym.Point());
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   Comment("");
}

//+------------------------------------------------------------------+
void OnTick()
{
   if(!Sym.RefreshRates()) return;

   // 1. Kelola posisi yang sudah ada (virtual TP/SL/trailing)
   ManageVirtualBasket();

   // 2. Cek apakah virtual stop order harus dipicu
   CheckVirtualStopTrigger();

   // 3. Jika belum ada posisi sama sekali, buka entry awal
   if(CountMyPositions() == 0 && !g_virtualStop.active)
   {
      if(IsTradeAllowed())
         OpenInitialPosition();
   }

   DrawInfo();
}

//+------------------------------------------------------------------+
//| Cek filter waktu, spread, market open                            |
//+------------------------------------------------------------------+
bool IsTradeAllowed()
{
   if(!MQLInfoInteger(MQL_TRADE_ALLOWED))                return false;
   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED))      return false;
   if(!(bool)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_MODE))
   {
      // pastikan simbol bisa diperdagangkan
      long mode = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_MODE);
      if(mode == SYMBOL_TRADE_MODE_DISABLED) return false;
   }

   // filter jam
   if(InpUseTimeFilter)
   {
      MqlDateTime dt; TimeToStruct(TimeCurrent(), dt);
      if(InpStartHour <= InpEndHour)
      {
         if(dt.hour < InpStartHour || dt.hour >= InpEndHour) return false;
      }
      else // wraps midnight
      {
         if(dt.hour < InpStartHour && dt.hour >= InpEndHour) return false;
      }
   }

   // spread check
   long spreadPts = (long)SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   if(spreadPts > InpMaxSpreadPts)
      return false;

   return true;
}

//+------------------------------------------------------------------+
//| Buka posisi awal sesuai arah pilihan                             |
//+------------------------------------------------------------------+
void OpenInitialPosition()
{
   bool isBuy = true;
   if(InpDirection == DIR_BUY)       isBuy = true;
   else if(InpDirection == DIR_SELL) isBuy = false;
   else
   {
      // DIR_AUTO: bandingkan close[1] vs close[2] (tren mini M1)
      double c1 = iClose(_Symbol, PERIOD_CURRENT, 1);
      double c2 = iClose(_Symbol, PERIOD_CURRENT, 2);
      isBuy = (c1 >= c2);
   }

   double lot = NormalizeLot(InpLotStart);
   if(lot <= 0.0) return;

   if(SendMarketOrder(isBuy, lot, "init"))
   {
      g_gridLevelsOpened = 1;
      SetupNextVirtualStop(isBuy, 1);
      g_basketTrailPrice = 0.0;
   }
}

//+------------------------------------------------------------------+
//| Pasang virtual stop order di grid level berikutnya               |
//+------------------------------------------------------------------+
void SetupNextVirtualStop(const bool baseIsBuy, const int currentLevel)
{
   if(currentLevel >= InpMaxGridLevels)
   {
      ResetVirtualStop();
      return;
   }

   double point  = Sym.Point();
   double bid    = Sym.Bid();
   double ask    = Sym.Ask();
   double step   = InpGridStepPoints * point;

   VirtualStopOrder v;
   v.active  = true;
   v.level   = currentLevel + 1;
   v.lot     = NormalizeLot(InpLotStart * MathPow(InpLotMultiplier, currentLevel));

   if(baseIsBuy)
   {
      // posisi buy rugi jika harga turun -> pasang BUY STOP di atas? Tidak.
      // Untuk grid averaging saat melawan, tambah BUY lagi saat harga turun (buy-limit virtual)
      // atau tambah SELL saat harga naik (hedge). Kita pakai averaging: BUY lagi saat harga turun.
      v.isBuy        = true;
      v.triggerPrice = NormalizeDouble(ask - step * currentLevel, Sym.Digits());
      // karena harga trigger < harga sekarang, sebenarnya ini "virtual buy-limit".
      // Kita tetap panggil "stop" agar logikanya seragam: pemicu = saat ask <= trigger.
   }
   else
   {
      v.isBuy        = false;
      v.triggerPrice = NormalizeDouble(bid + step * currentLevel, Sym.Digits());
      // virtual sell-limit: pemicu = saat bid >= trigger.
   }

   g_virtualStop = v;
}

//+------------------------------------------------------------------+
void ResetVirtualStop()
{
   g_virtualStop.active       = false;
   g_virtualStop.isBuy        = false;
   g_virtualStop.triggerPrice = 0.0;
   g_virtualStop.lot          = 0.0;
   g_virtualStop.level        = 0;
}

//+------------------------------------------------------------------+
//| Cek apakah harga sudah menyentuh level virtual                   |
//+------------------------------------------------------------------+
void CheckVirtualStopTrigger()
{
   if(!g_virtualStop.active) return;
   if(!IsTradeAllowed())     return;

   double bid = Sym.Bid();
   double ask = Sym.Ask();
   bool triggered = false;

   if(g_virtualStop.isBuy)
   {
      // averaging buy: picu saat ask <= trigger
      if(ask <= g_virtualStop.triggerPrice) triggered = true;
   }
   else
   {
      // averaging sell: picu saat bid >= trigger
      if(bid >= g_virtualStop.triggerPrice) triggered = true;
   }

   if(!triggered) return;

   double lot = NormalizeLot(g_virtualStop.lot);
   if(lot <= 0.0) { ResetVirtualStop(); return; }

   if(SendMarketOrder(g_virtualStop.isBuy, lot, "grid-L" + IntegerToString(g_virtualStop.level)))
   {
      int executedLevel = g_virtualStop.level;
      g_gridLevelsOpened = executedLevel;
      bool baseIsBuy = g_virtualStop.isBuy;
      ResetVirtualStop();

      // pasang level berikutnya
      SetupNextVirtualStop(baseIsBuy, executedLevel);

      // reset trailing saat basket bertambah (biar tidak langsung ketrigger SL)
      g_basketTrailPrice = 0.0;
   }
}

//+------------------------------------------------------------------+
//| Kelola basket: hitung profit agregat, virtual TP, SL, trailing   |
//+------------------------------------------------------------------+
void ManageVirtualBasket()
{
   double totalLots=0.0, weightedPrice=0.0, totalProfit=0.0;
   int    positionsCount = 0;
   bool   basketIsBuy = true;

   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      if(!Pos.SelectByIndex(i)) continue;
      if(Pos.Symbol() != _Symbol) continue;
      if(Pos.Magic()  != InpMagic) continue;

      double lots  = Pos.Volume();
      double price = Pos.PriceOpen();
      totalLots     += lots;
      weightedPrice += price * lots;
      totalProfit   += Pos.Profit() + Pos.Swap() + Pos.Commission();
      basketIsBuy    = (Pos.PositionType() == POSITION_TYPE_BUY);
      positionsCount++;
   }

   if(positionsCount == 0)
   {
      g_basketTrailPrice = 0.0;
      g_gridLevelsOpened = 0;
      return;
   }

   double avgPrice   = weightedPrice / totalLots;
   double point      = Sym.Point();
   double bid        = Sym.Bid();
   double ask        = Sym.Ask();
   double curPrice   = basketIsBuy ? bid : ask;
   double profitPts  = basketIsBuy ? (curPrice - avgPrice)/point
                                   : (avgPrice - curPrice)/point;

   // --- Virtual Take Profit (basket) ---
   if(InpTakeProfitPts > 0 && profitPts >= InpTakeProfitPts)
   {
      CloseAllBasket("virtual-TP");
      return;
   }

   // --- Virtual Stop Loss (basket) ---
   if(InpStopLossPts > 0 && profitPts <= -InpStopLossPts)
   {
      CloseAllBasket("virtual-SL");
      return;
   }

   // --- Virtual Trailing Stop ---
   if(InpTrailStartPts > 0 && InpTrailStepPts > 0 && profitPts >= InpTrailStartPts)
   {
      double newTrail;
      if(basketIsBuy)
      {
         newTrail = curPrice - InpTrailStepPts * point;
         if(g_basketTrailPrice == 0.0 || newTrail > g_basketTrailPrice)
            g_basketTrailPrice = newTrail;

         if(bid <= g_basketTrailPrice)
         {
            CloseAllBasket("virtual-TRAIL");
            return;
         }
      }
      else
      {
         newTrail = curPrice + InpTrailStepPts * point;
         if(g_basketTrailPrice == 0.0 || newTrail < g_basketTrailPrice)
            g_basketTrailPrice = newTrail;

         if(ask >= g_basketTrailPrice)
         {
            CloseAllBasket("virtual-TRAIL");
            return;
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Tutup semua posisi basket milik EA                               |
//+------------------------------------------------------------------+
void CloseAllBasket(const string reason)
{
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      if(!Pos.SelectByIndex(i)) continue;
      if(Pos.Symbol() != _Symbol)  continue;
      if(Pos.Magic()  != InpMagic) continue;

      ulong ticket = Pos.Ticket();
      int attempts = 0;
      while(attempts < InpRetryAttempts)
      {
         if(Trade.PositionClose(ticket, (ulong)InpSlippagePts))
            break;
         uint err = Trade.ResultRetcode();
         if(err == TRADE_RETCODE_REQUOTE || err == TRADE_RETCODE_PRICE_OFF ||
            err == TRADE_RETCODE_PRICE_CHANGED || err == TRADE_RETCODE_REJECT)
         {
            Sleep(InpRetryDelayMs);
            Sym.RefreshRates();
            attempts++;
            continue;
         }
         PrintFormat("PositionClose gagal ticket=%I64u err=%u desc=%s",
                     ticket, err, Trade.ResultRetcodeDescription());
         break;
      }
   }

   ResetVirtualStop();
   g_basketTrailPrice = 0.0;
   g_gridLevelsOpened = 0;
   PrintFormat("Basket closed (%s)", reason);
}

//+------------------------------------------------------------------+
//| Kirim market order BUY/SELL dengan retry & proteksi slippage     |
//+------------------------------------------------------------------+
bool SendMarketOrder(const bool isBuy, const double lot, const string tag)
{
   if(!IsTradeAllowed())
   {
      PrintFormat("Order dibatalkan: trading tidak diijinkan / spread terlalu lebar");
      return false;
   }

   int attempts = 0;
   while(attempts < InpRetryAttempts)
   {
      Sym.RefreshRates();
      double price = isBuy ? Sym.Ask() : Sym.Bid();
      string cmt   = InpComment + "-" + tag;

      bool ok = isBuy
                ? Trade.Buy (lot, _Symbol, price, 0.0, 0.0, cmt)
                : Trade.Sell(lot, _Symbol, price, 0.0, 0.0, cmt);

      uint retcode = Trade.ResultRetcode();
      if(ok && (retcode == TRADE_RETCODE_DONE || retcode == TRADE_RETCODE_PLACED ||
                retcode == TRADE_RETCODE_DONE_PARTIAL))
      {
         PrintFormat("Order OK %s lot=%.2f price=%.5f ticket=%I64u (%s)",
                     (isBuy?"BUY":"SELL"), lot, price, Trade.ResultOrder(), tag);
         return true;
      }

      PrintFormat("Order gagal (%s) ret=%u desc=%s - retry %d/%d",
                  (isBuy?"BUY":"SELL"), retcode,
                  Trade.ResultRetcodeDescription(), attempts+1, InpRetryAttempts);

      if(retcode == TRADE_RETCODE_REQUOTE || retcode == TRADE_RETCODE_PRICE_OFF ||
         retcode == TRADE_RETCODE_PRICE_CHANGED || retcode == TRADE_RETCODE_REJECT)
      {
         Sleep(InpRetryDelayMs);
         attempts++;
         continue;
      }
      // error fatal -> stop
      break;
   }
   return false;
}

//+------------------------------------------------------------------+
//| Hitung posisi milik EA                                           |
//+------------------------------------------------------------------+
int CountMyPositions()
{
   int cnt = 0;
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      if(!Pos.SelectByIndex(i)) continue;
      if(Pos.Symbol() != _Symbol) continue;
      if(Pos.Magic()  != InpMagic) continue;
      cnt++;
   }
   return cnt;
}

//+------------------------------------------------------------------+
//| Rekonstruksi state jika EA direstart sementara posisi masih ada  |
//+------------------------------------------------------------------+
void SyncStateFromOpenPositions()
{
   int count = 0;
   bool isBuy = true;
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      if(!Pos.SelectByIndex(i)) continue;
      if(Pos.Symbol() != _Symbol) continue;
      if(Pos.Magic()  != InpMagic) continue;
      isBuy = (Pos.PositionType() == POSITION_TYPE_BUY);
      count++;
   }
   g_gridLevelsOpened = count;
   g_basketTrailPrice = 0.0;

   if(count > 0 && count < InpMaxGridLevels)
      SetupNextVirtualStop(isBuy, count);
   else
      ResetVirtualStop();
}

//+------------------------------------------------------------------+
//| Normalisasi lot sesuai step broker                               |
//+------------------------------------------------------------------+
double NormalizeLot(double lot)
{
   double minLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double stepLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   if(stepLot <= 0) stepLot = 0.01;

   lot = MathMax(minLot, MathMin(maxLot, lot));
   lot = MathFloor(lot / stepLot + 0.5) * stepLot;
   return NormalizeDouble(lot, 2);
}

//+------------------------------------------------------------------+
//| Tampilkan info di chart                                          |
//+------------------------------------------------------------------+
void DrawInfo()
{
   string s;
   s  = "=== GridTrailingEA ===\n";
   s += StringFormat("Posisi: %d   Level: %d/%d\n",
                     CountMyPositions(), g_gridLevelsOpened, InpMaxGridLevels);
   if(g_virtualStop.active)
      s += StringFormat("Virtual %s @ %.5f  lot=%.2f  (L%d)\n",
                        (g_virtualStop.isBuy?"BUY":"SELL"),
                        g_virtualStop.triggerPrice, g_virtualStop.lot,
                        g_virtualStop.level);
   else
      s += "Virtual stop: -\n";

   if(g_basketTrailPrice > 0)
      s += StringFormat("Trailing SL virtual: %.5f\n", g_basketTrailPrice);
   s += StringFormat("Spread: %d pts (max %d)\n",
                     (int)SymbolInfoInteger(_Symbol, SYMBOL_SPREAD),
                     InpMaxSpreadPts);
   Comment(s);
}
//+------------------------------------------------------------------+
