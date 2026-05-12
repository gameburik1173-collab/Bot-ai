//+------------------------------------------------------------------+
//|                                              GridTrailingEA.mq5  |
//|                        Grid Trailing-Stop (Stop Reversal) EA     |
//|                                                                  |
//|  Metode: GRID TRAILING STOP                                      |
//|   1. Buka posisi awal (BUY atau SELL, manual / auto).            |
//|   2. Pasang VIRTUAL STOP ORDER pada arah BERLAWANAN pada jarak   |
//|      GridStepPoints dari harga saat ini.                         |
//|        - Posisi BUY  -> virtual SELL STOP di bawah harga.        |
//|        - Posisi SELL -> virtual BUY  STOP di atas  harga.        |
//|   3. Virtual stop tersebut DI-TRAIL mengikuti harga yang         |
//|      bergerak ke arah profit (mengunci keuntungan secara         |
//|      otomatis seperti trailing stop biasa, tetapi dihitung       |
//|      di sisi EA, bukan di server broker).                        |
//|   4. Bila harga berbalik dan menyentuh virtual stop:             |
//|        - Tutup posisi berjalan (market).                         |
//|        - Buka posisi baru di ARAH BERLAWANAN dengan lot berikut  |
//|          (LotMultiplier untuk pola martingale; 1.0 = flat).      |
//|        - Pasang virtual stop baru ke arah yang berlawanan lagi.  |
//|   5. Profit dan SL basket juga VIRTUAL (dihitung EA, dikirim     |
//|      hanya sebagai PositionClose saat dipicu).                   |
//|                                                                  |
//|  Semua pending order & trailing disimpan di memori EA.           |
//|  Broker hanya menerima: market BUY/SELL, dan PositionClose.      |
//|  Tidak ada OrderSend pending atau OrderModify berulang sehingga  |
//|  aman dari limit aktivitas broker.                               |
//|                                                                  |
//|  Proteksi:                                                       |
//|   - Max spread (points) sebelum entry / trigger.                 |
//|   - Deviation (slippage) untuk market order.                     |
//|   - Retry otomatis saat requote / price changed / off-quote.     |
//+------------------------------------------------------------------+
#property copyright "Bot-ai"
#property version   "1.10"
#property strict

#include <Trade\Trade.mqh>
#include <Trade\SymbolInfo.mqh>
#include <Trade\PositionInfo.mqh>

//--- Input parameters ------------------------------------------------
enum ENUM_DIRECTION { DIR_BUY=0, DIR_SELL=1, DIR_AUTO=2 };

input group "=== Strategi Grid Trailing Stop ==="
input ENUM_DIRECTION InpDirection      = DIR_AUTO;  // Arah awal
input double         InpLotStart       = 0.01;     // Lot awal
input double         InpLotMultiplier  = 2.0;      // Multiplier lot setelah reversal (1.0 = flat)
input int            InpGridStepPoints = 200;      // Jarak awal virtual stop (points)
input int            InpTrailStepPoints= 150;      // Jarak trailing virtual stop (points)
input int            InpMaxReversals   = 6;        // Max jumlah reversal berturut-turut
input double         InpMaxLotCap      = 1.00;     // Batas atas lot (0 = tanpa batas)

input group "=== Virtual TP / SL Basket ==="
input double         InpTakeProfitUSD  = 5.0;      // Virtual TP dalam USD kumulatif (0 = off)
input double         InpStopLossUSD    = 0.0;      // Virtual SL dalam USD kumulatif (0 = off)

input group "=== Proteksi Broker ==="
input int            InpMaxSpreadPts   = 50;       // Max spread diijinkan (points)
input int            InpSlippagePts    = 20;       // Deviation / slippage (points)
input int            InpRetryAttempts  = 3;        // Retry saat requote / off-quote
input int            InpRetryDelayMs   = 500;      // Delay antar retry (ms)
input ulong          InpMagic          = 20260512; // Magic number
input string         InpComment        = "GridTrailEA";

input group "=== Kontrol Waktu (opsional) ==="
input bool           InpUseTimeFilter  = false;    // Aktifkan filter jam
input int            InpStartHour      = 0;        // Jam mulai (server time)
input int            InpEndHour        = 24;       // Jam selesai (server time)

//--- Runtime objects -------------------------------------------------
CTrade         Trade;
CSymbolInfo    Sym;
CPositionInfo  Pos;

//--- Virtual stop order (satu aktif, arah berlawanan dg posisi) -----
struct VirtualStopOrder
{
   bool     active;
   bool     isBuyStop;     // true = BUY STOP (picu saat ask >= trigger),
                           // false = SELL STOP (picu saat bid <= trigger)
   double   triggerPrice;  // harga aktivasi
   double   lot;           // lot yang akan di-eksekusi saat reversal
};
VirtualStopOrder g_vStop;

//--- Basket state ----------------------------------------------------
double   g_realizedPL    = 0.0; // P/L kumulatif dari posisi yang sudah ditutup (basket berjalan)
int      g_reversalCount = 0;   // jumlah reversal yang sudah terjadi di basket ini
double   g_lastLot       = 0.0; // lot terakhir yang dipakai

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

   PrintFormat("GridTrailingEA v1.10 init. Magic=%I64u StopLevel=%d Point=%.*f",
               InpMagic, (int)Sym.StopsLevel(), Sym.Digits(), Sym.Point());
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason) { Comment(""); }

//+------------------------------------------------------------------+
void OnTick()
{
   if(!Sym.RefreshRates()) return;

   // 1. Kelola TP/SL basket virtual (tutup semua kalau kena target USD).
   if(ManageVirtualBasketPL()) return; // basket ditutup, tunggu tick berikutnya

   // 2. Trail virtual stop mengikuti pergerakan harga favorable.
   TrailVirtualStop();

   // 3. Cek apakah virtual stop ter-trigger -> stop-and-reverse.
   CheckVirtualStopTrigger();

   // 4. Jika belum ada posisi, buka entry awal.
   if(CountMyPositions() == 0 && !g_vStop.active && IsTradeAllowed())
      OpenInitialPosition();

   DrawInfo();
}

//+------------------------------------------------------------------+
//| Proteksi trading diijinkan                                       |
//+------------------------------------------------------------------+
bool IsTradeAllowed()
{
   if(!MQLInfoInteger(MQL_TRADE_ALLOWED))           return false;
   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED)) return false;

   long tradeMode = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_MODE);
   if(tradeMode == SYMBOL_TRADE_MODE_DISABLED) return false;

   if(InpUseTimeFilter)
   {
      MqlDateTime dt; TimeToStruct(TimeCurrent(), dt);
      if(InpStartHour <= InpEndHour)
      {
         if(dt.hour < InpStartHour || dt.hour >= InpEndHour) return false;
      }
      else
      {
         if(dt.hour < InpStartHour && dt.hour >= InpEndHour) return false;
      }
   }

   long spreadPts = (long)SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   if(spreadPts > InpMaxSpreadPts) return false;

   return true;
}

//+------------------------------------------------------------------+
//| Buka posisi awal (entry pertama)                                 |
//+------------------------------------------------------------------+
void OpenInitialPosition()
{
   bool isBuy = true;
   if(InpDirection == DIR_BUY)       isBuy = true;
   else if(InpDirection == DIR_SELL) isBuy = false;
   else
   {
      // DIR_AUTO: tren mini pakai close bar terakhir
      double c1 = iClose(_Symbol, PERIOD_CURRENT, 1);
      double c2 = iClose(_Symbol, PERIOD_CURRENT, 2);
      isBuy = (c1 >= c2);
   }

   double lot = NormalizeLot(InpLotStart);
   if(lot <= 0.0) return;

   if(SendMarketOrder(isBuy, lot, "init"))
   {
      g_realizedPL    = 0.0;
      g_reversalCount = 0;
      g_lastLot       = lot;
      PlaceVirtualReverseStop(isBuy);
   }
}

//+------------------------------------------------------------------+
//| Pasang virtual stop di arah berlawanan dari posisi               |
//+------------------------------------------------------------------+
void PlaceVirtualReverseStop(const bool positionIsBuy)
{
   double point = Sym.Point();
   double step  = InpGridStepPoints * point;

   // lot untuk eksekusi reversal berikutnya
   double nextLot = NormalizeLot(g_lastLot * InpLotMultiplier);
   if(InpMaxLotCap > 0.0) nextLot = MathMin(nextLot, NormalizeLot(InpMaxLotCap));
   if(nextLot <= 0.0)
   {
      ResetVirtualStop();
      return;
   }

   g_vStop.active = true;
   g_vStop.lot    = nextLot;

   if(positionIsBuy)
   {
      // posisi BUY -> virtual SELL STOP di bawah harga
      g_vStop.isBuyStop    = false;
      g_vStop.triggerPrice = NormalizeDouble(Sym.Bid() - step, Sym.Digits());
   }
   else
   {
      // posisi SELL -> virtual BUY STOP di atas harga
      g_vStop.isBuyStop    = true;
      g_vStop.triggerPrice = NormalizeDouble(Sym.Ask() + step, Sym.Digits());
   }
}

//+------------------------------------------------------------------+
//| Trail virtual stop mengikuti harga favorable                     |
//+------------------------------------------------------------------+
void TrailVirtualStop()
{
   if(!g_vStop.active) return;
   if(CountMyPositions() == 0) return;

   double point = Sym.Point();
   double trail = InpTrailStepPoints * point;
   if(trail <= 0.0) return;

   // Ambil arah posisi berjalan
   bool positionIsBuy = IsBasketBuy();

   if(positionIsBuy)
   {
      // posisi BUY, virtual SELL STOP di bawah -> trail naik mengikuti bid
      double newTrigger = NormalizeDouble(Sym.Bid() - trail, Sym.Digits());
      if(newTrigger > g_vStop.triggerPrice)
         g_vStop.triggerPrice = newTrigger;
   }
   else
   {
      // posisi SELL, virtual BUY STOP di atas -> trail turun mengikuti ask
      double newTrigger = NormalizeDouble(Sym.Ask() + trail, Sym.Digits());
      if(newTrigger < g_vStop.triggerPrice)
         g_vStop.triggerPrice = newTrigger;
   }
}

//+------------------------------------------------------------------+
//| Cek apakah virtual stop ter-trigger -> stop-and-reverse          |
//+------------------------------------------------------------------+
void CheckVirtualStopTrigger()
{
   if(!g_vStop.active) return;

   double bid = Sym.Bid();
   double ask = Sym.Ask();
   bool   triggered = false;

   if(g_vStop.isBuyStop)
   {
      if(ask >= g_vStop.triggerPrice) triggered = true;
   }
   else
   {
      if(bid <= g_vStop.triggerPrice) triggered = true;
   }
   if(!triggered) return;

   if(!IsTradeAllowed())
   {
      // jangan eksekusi saat spread melebar / trading dilarang; coba lagi tick berikutnya
      return;
   }

   // 1. Tutup posisi yang sedang berjalan (akumulasi realized P/L).
   double closedPL = CloseAllBasket("reverse");
   g_realizedPL += closedPL;

   // 2. Batas maksimum reversal
   if(g_reversalCount + 1 >= InpMaxReversals)
   {
      PrintFormat("Reversal limit (%d) tercapai. Basket berhenti.", InpMaxReversals);
      ResetVirtualStop();
      return;
   }

   // 3. Buka posisi baru di arah berlawanan (stop order tadi)
   bool newIsBuy = g_vStop.isBuyStop;
   double lot    = g_vStop.lot;

   if(SendMarketOrder(newIsBuy, lot, StringFormat("rev-%d", g_reversalCount+1)))
   {
      g_reversalCount++;
      g_lastLot = lot;
      ResetVirtualStop();
      PlaceVirtualReverseStop(newIsBuy);
   }
   else
   {
      // gagal reversal -> reset supaya tidak loop infinite di tick berikut
      ResetVirtualStop();
   }
}

//+------------------------------------------------------------------+
//| Kelola TP / SL basket dalam USD (virtual)                        |
//| Return true jika basket baru saja ditutup.                       |
//+------------------------------------------------------------------+
bool ManageVirtualBasketPL()
{
   int count = CountMyPositions();
   if(count == 0)
   {
      // basket kosong -> reset state realized
      if(g_realizedPL != 0.0 || g_reversalCount != 0)
      {
         g_realizedPL    = 0.0;
         g_reversalCount = 0;
         g_lastLot       = 0.0;
         ResetVirtualStop();
      }
      return false;
   }

   double floating = 0.0;
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      if(!Pos.SelectByIndex(i)) continue;
      if(Pos.Symbol() != _Symbol)  continue;
      if(Pos.Magic()  != InpMagic) continue;
      floating += Pos.Profit() + Pos.Swap() + Pos.Commission();
   }
   double basketPL = g_realizedPL + floating;

   if(InpTakeProfitUSD > 0.0 && basketPL >= InpTakeProfitUSD)
   {
      g_realizedPL += CloseAllBasket("virtual-TP");
      PrintFormat("Basket ditutup TP. Total P/L=%.2f USD", g_realizedPL);
      g_realizedPL    = 0.0;
      g_reversalCount = 0;
      g_lastLot       = 0.0;
      ResetVirtualStop();
      return true;
   }

   if(InpStopLossUSD > 0.0 && basketPL <= -MathAbs(InpStopLossUSD))
   {
      g_realizedPL += CloseAllBasket("virtual-SL");
      PrintFormat("Basket ditutup SL. Total P/L=%.2f USD", g_realizedPL);
      g_realizedPL    = 0.0;
      g_reversalCount = 0;
      g_lastLot       = 0.0;
      ResetVirtualStop();
      return true;
   }

   return false;
}

//+------------------------------------------------------------------+
//| Tutup semua posisi milik EA, kembalikan total P/L yang di-close. |
//+------------------------------------------------------------------+
double CloseAllBasket(const string reason)
{
   double totalClosed = 0.0;
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      if(!Pos.SelectByIndex(i)) continue;
      if(Pos.Symbol() != _Symbol)  continue;
      if(Pos.Magic()  != InpMagic) continue;

      ulong ticket = Pos.Ticket();
      double pl    = Pos.Profit() + Pos.Swap() + Pos.Commission();

      int attempts = 0;
      bool ok = false;
      while(attempts < InpRetryAttempts && !ok)
      {
         Sym.RefreshRates();
         ok = Trade.PositionClose(ticket, (ulong)InpSlippagePts);
         if(ok) break;

         uint err = Trade.ResultRetcode();
         if(err == TRADE_RETCODE_REQUOTE || err == TRADE_RETCODE_PRICE_OFF ||
            err == TRADE_RETCODE_PRICE_CHANGED || err == TRADE_RETCODE_REJECT)
         {
            Sleep(InpRetryDelayMs);
            attempts++;
            continue;
         }
         PrintFormat("PositionClose gagal ticket=%I64u err=%u desc=%s",
                     ticket, err, Trade.ResultRetcodeDescription());
         break;
      }
      if(ok) totalClosed += pl;
   }
   PrintFormat("CloseAllBasket(%s) P/L=%.2f USD", reason, totalClosed);
   return totalClosed;
}

//+------------------------------------------------------------------+
//| Kirim market order dgn retry & slippage control                  |
//+------------------------------------------------------------------+
bool SendMarketOrder(const bool isBuy, const double lot, const string tag)
{
   if(!IsTradeAllowed())
   {
      PrintFormat("Order dibatalkan (%s): trading tidak diijinkan / spread lebar", tag);
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
      if(ok && (retcode == TRADE_RETCODE_DONE ||
                retcode == TRADE_RETCODE_PLACED ||
                retcode == TRADE_RETCODE_DONE_PARTIAL))
      {
         PrintFormat("Order OK %s lot=%.2f price=%.*f ticket=%I64u (%s)",
                     (isBuy?"BUY":"SELL"), lot, Sym.Digits(), price,
                     Trade.ResultOrder(), tag);
         return true;
      }

      PrintFormat("Order gagal (%s) %s ret=%u desc=%s - retry %d/%d",
                  tag, (isBuy?"BUY":"SELL"), retcode,
                  Trade.ResultRetcodeDescription(),
                  attempts+1, InpRetryAttempts);

      if(retcode == TRADE_RETCODE_REQUOTE || retcode == TRADE_RETCODE_PRICE_OFF ||
         retcode == TRADE_RETCODE_PRICE_CHANGED || retcode == TRADE_RETCODE_REJECT)
      {
         Sleep(InpRetryDelayMs);
         attempts++;
         continue;
      }
      break; // error fatal
   }
   return false;
}

//+------------------------------------------------------------------+
//| Utility                                                          |
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

bool IsBasketBuy()
{
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      if(!Pos.SelectByIndex(i)) continue;
      if(Pos.Symbol() != _Symbol) continue;
      if(Pos.Magic()  != InpMagic) continue;
      return (Pos.PositionType() == POSITION_TYPE_BUY);
   }
   return true;
}

void ResetVirtualStop()
{
   g_vStop.active       = false;
   g_vStop.isBuyStop    = false;
   g_vStop.triggerPrice = 0.0;
   g_vStop.lot          = 0.0;
}

void SyncStateFromOpenPositions()
{
   int count = CountMyPositions();
   g_realizedPL    = 0.0;
   g_reversalCount = 0;

   if(count > 0)
   {
      bool isBuy = IsBasketBuy();
      // gunakan lot posisi terbesar sebagai referensi
      double maxLot = 0.0;
      for(int i=PositionsTotal()-1; i>=0; i--)
      {
         if(!Pos.SelectByIndex(i)) continue;
         if(Pos.Symbol() != _Symbol)  continue;
         if(Pos.Magic()  != InpMagic) continue;
         if(Pos.Volume() > maxLot) maxLot = Pos.Volume();
      }
      g_lastLot = (maxLot > 0 ? maxLot : InpLotStart);
      PlaceVirtualReverseStop(isBuy);
   }
   else
   {
      g_lastLot = 0.0;
      ResetVirtualStop();
   }
}

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
//| Info panel di chart                                              |
//+------------------------------------------------------------------+
void DrawInfo()
{
   string s;
   s  = "=== Grid Trailing Stop EA ===\n";
   int posCount = CountMyPositions();

   double floating = 0.0;
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      if(!Pos.SelectByIndex(i)) continue;
      if(Pos.Symbol() != _Symbol)  continue;
      if(Pos.Magic()  != InpMagic) continue;
      floating += Pos.Profit() + Pos.Swap() + Pos.Commission();
   }

   s += StringFormat("Posisi aktif : %d   Reversal : %d/%d\n",
                     posCount, g_reversalCount, InpMaxReversals);
   s += StringFormat("P/L floating : %.2f USD\n", floating);
   s += StringFormat("P/L realized : %.2f USD\n", g_realizedPL);
   s += StringFormat("Basket total : %.2f USD  (TP=%.2f / SL=%.2f)\n",
                     g_realizedPL + floating, InpTakeProfitUSD, InpStopLossUSD);

   if(g_vStop.active)
      s += StringFormat("Virtual %s STOP @ %.*f  lot=%.2f\n",
                        (g_vStop.isBuyStop?"BUY":"SELL"),
                        Sym.Digits(), g_vStop.triggerPrice, g_vStop.lot);
   else
      s += "Virtual stop : -\n";

   s += StringFormat("Spread : %d pts (max %d)  Slippage : %d pts\n",
                     (int)SymbolInfoInteger(_Symbol, SYMBOL_SPREAD),
                     InpMaxSpreadPts, InpSlippagePts);
   Comment(s);
}
//+------------------------------------------------------------------+
