//+------------------------------------------------------------------+
//|                                           GridTrailingStop.mq5    |
//|                        Grid Trailing Stop EA - Virtual Trailing   |
//|                        Tidak kirim trailing ke server broker      |
//|                        Semua trailing dihitung locally di VPS     |
//+------------------------------------------------------------------+
#property copyright "GridTrailingBot"
#property link      ""
#property version   "2.00"
#property description "Grid Trading EA with Virtual Trailing Stop"
#property description "Virtual trailing = tidak kirim modify ke broker"
#property description "Menghindari error Max Quotes / Too Many Requests"

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\OrderInfo.mqh>

//--- Enum untuk mode grid
enum ENUM_GRID_DIRECTION
{
   GRID_BUY  = 0,  // Buy Only (Grid Buy Stop)
   GRID_SELL = 1,  // Sell Only (Grid Sell Stop)
   GRID_BOTH = 2   // Both Directions
};

enum ENUM_TRAIL_MODE
{
   TRAIL_VIRTUAL    = 0,  // Virtual Trailing (Lokal - No Server Request)
   TRAIL_REAL       = 1   // Real Trailing (Modify ke Broker)
};

//+------------------------------------------------------------------+
//| Input Parameters                                                  |
//+------------------------------------------------------------------+
input group "=== GRID SETTINGS ==="
input ENUM_GRID_DIRECTION GridDirection   = GRID_BUY;      // Arah Grid
input int                 GridLevels      = 5;             // Jumlah Level Grid
input double              GridDistance    = 50;            // Jarak Antar Grid (points)
input double              LotSize        = 0.01;          // Lot Size per Order
input double              LotMultiplier  = 1.0;           // Multiplier Lot per Level (1.0 = fixed)

input group "=== VIRTUAL TRAILING STOP ==="
input ENUM_TRAIL_MODE     TrailMode       = TRAIL_VIRTUAL; // Mode Trailing
input double              TrailStart     = 30;            // Trailing Start (points profit)
input double              TrailStep      = 10;            // Trailing Step (points)
input double              TrailDistance  = 20;            // Jarak Trailing dari harga (points)

input group "=== STOPLOSS & TAKEPROFIT ==="
input double              InitialSL      = 100;           // Initial Stoploss (points, 0=off)
input double              TakeProfit     = 0;             // Take Profit (points, 0=off)
input double              GridTotalSL    = 200;           // Total Grid Stoploss (points dari first order)
input double              GridTotalTP    = 300;           // Total Grid TP (points dari first order)

input group "=== PENDING ORDER TRAILING ==="
input bool                TrailPending   = true;          // Trail Pending Orders juga?
input double              PendingTrailDist = 30;          // Jarak trailing pending (points)

input group "=== MANAGEMENT ==="
input int                 MaxOrders      = 10;            // Max Total Orders
input double              MaxDrawdown    = 30;            // Max Drawdown % (close all)
input bool                CloseOnProfit  = true;          // Close All saat total profit?
input double              TotalProfitUSD = 10;            // Target Profit $ (close all)
input double              TotalLossUSD   = -50;           // Max Loss $ (close all)
input bool                UseTimeFilter  = false;         // Gunakan filter waktu?
input int                 StartHour      = 8;             // Jam mulai trading
input int                 EndHour        = 22;            // Jam selesai trading

input group "=== DISPLAY ==="
input bool                ShowPanel      = true;          // Tampilkan Panel Info
input bool                ShowGridLines  = true;          // Tampilkan Grid Lines di chart
input color               PanelColor     = clrDarkGreen;  // Warna Panel
input color               GridLineColor  = clrDodgerBlue; // Warna Grid Lines
input int                 MagicNumber    = 777777;        // Magic Number

//+------------------------------------------------------------------+
//| Global Variables                                                  |
//+------------------------------------------------------------------+
CTrade         trade;
CPositionInfo  posInfo;
COrderInfo     orderInfo;

// Virtual Trailing Storage
struct VirtualTrail
{
   ulong    ticket;         // Ticket posisi
   double   virtualSL;      // Virtual stoploss level
   double   highestProfit;  // Highest profit point reached
   bool     trailActive;    // Apakah trailing sudah aktif
   datetime lastUpdate;     // Waktu update terakhir
};

VirtualTrail virtualTrails[];   // Array virtual trailing
double       gridBasePrice;     // Harga base grid
bool         gridActive;        // Grid sudah aktif?
int          totalGridOrders;   // Total grid orders aktif
double       accountStartBalance; // Balance awal untuk drawdown calc

//+------------------------------------------------------------------+
//| Expert initialization function                                     |
//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(10);
   trade.SetTypeFilling(ORDER_FILLING_IOC);
   
   gridActive = false;
   gridBasePrice = 0;
   totalGridOrders = 0;
   accountStartBalance = AccountInfoDouble(ACCOUNT_BALANCE);
   
   ArrayResize(virtualTrails, 0);
   
   if(ShowPanel) CreatePanel();
   
   Print("=== Grid Trailing Stop EA Initialized ===");
   Print("Mode: ", TrailMode == TRAIL_VIRTUAL ? "VIRTUAL (No Server Request)" : "REAL (Modify to Broker)");
   Print("Grid Levels: ", GridLevels, " | Distance: ", GridDistance, " pts");
   Print("Trailing: Start=", TrailStart, " Step=", TrailStep, " Distance=", TrailDistance);
   
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                   |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   ObjectsDeleteAll(0, "GRID_");
   ObjectsDeleteAll(0, "PANEL_");
   Comment("");
}

//+------------------------------------------------------------------+
//| Expert tick function                                               |
//+------------------------------------------------------------------+
void OnTick()
{
   // Time filter
   if(UseTimeFilter && !IsTradeTime()) return;
   
   // Cek drawdown
   if(CheckDrawdown()) return;
   
   // Cek total profit/loss target
   if(CloseOnProfit && CheckProfitTarget()) return;
   
   // Manage Virtual Trailing (UTAMA - tidak kirim ke broker)
   ManageVirtualTrailing();
   
   // Trail Pending Orders (virtual)
   if(TrailPending) ManagePendingTrailing();
   
   // Place Grid jika belum aktif
   if(!gridActive && CountMyOrders() == 0 && CountMyPositions() == 0)
   {
      PlaceGrid();
   }
   
   // Update panel display
   if(ShowPanel) UpdatePanel();
   if(ShowGridLines) DrawGridLines();
}

//+------------------------------------------------------------------+
//| VIRTUAL TRAILING STOP - Inti dari EA                              |
//| Tidak mengirim OrderModify ke broker                              |
//| Hanya close posisi ketika harga menyentuh virtual SL             |
//+------------------------------------------------------------------+
void ManageVirtualTrailing()
{
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(!posInfo.SelectByIndex(i)) continue;
      if(posInfo.Magic() != MagicNumber) continue;
      if(posInfo.Symbol() != _Symbol) continue;
      
      ulong ticket = posInfo.Ticket();
      double openPrice = posInfo.PriceOpen();
      double currentPrice = posInfo.PriceCurrent();
      ENUM_POSITION_TYPE posType = posInfo.PositionType();
      
      // Cari atau buat virtual trail untuk posisi ini
      int idx = FindVirtualTrail(ticket);
      if(idx == -1) idx = AddVirtualTrail(ticket);
      if(idx == -1) continue;
      
      double profitPoints = 0;
      
      if(posType == POSITION_TYPE_BUY)
      {
         profitPoints = (bid - openPrice) / point;
         
         // Cek apakah trailing harus dimulai
         if(profitPoints >= TrailStart)
         {
            virtualTrails[idx].trailActive = true;
            
            // Update highest profit
            if(profitPoints > virtualTrails[idx].highestProfit)
            {
               virtualTrails[idx].highestProfit = profitPoints;
               // Hitung virtual SL baru
               double newVSL = bid - (TrailDistance * point);
               
               // Hanya geser naik (trailing step)
               if(newVSL > virtualTrails[idx].virtualSL + (TrailStep * point) || 
                  virtualTrails[idx].virtualSL == 0)
               {
                  virtualTrails[idx].virtualSL = newVSL;
                  virtualTrails[idx].lastUpdate = TimeCurrent();
                  
                  // TIDAK ada OrderModify disini - ini virtual!
                  PrintFormat("VIRTUAL TRAIL [BUY #%d] SL moved to %.5f (Profit: %.1f pts)", 
                             ticket, newVSL, profitPoints);
               }
            }
            
            // CEK: Apakah harga sudah menyentuh virtual SL?
            if(virtualTrails[idx].virtualSL > 0 && bid <= virtualTrails[idx].virtualSL)
            {
               PrintFormat("VIRTUAL SL HIT [BUY #%d] @ %.5f | VirtualSL: %.5f", 
                          ticket, bid, virtualTrails[idx].virtualSL);
               trade.PositionClose(ticket);
               RemoveVirtualTrail(ticket);
            }
         }
      }
      else if(posType == POSITION_TYPE_SELL)
      {
         profitPoints = (openPrice - ask) / point;
         
         if(profitPoints >= TrailStart)
         {
            virtualTrails[idx].trailActive = true;
            
            if(profitPoints > virtualTrails[idx].highestProfit)
            {
               virtualTrails[idx].highestProfit = profitPoints;
               double newVSL = ask + (TrailDistance * point);
               
               if(newVSL < virtualTrails[idx].virtualSL - (TrailStep * point) || 
                  virtualTrails[idx].virtualSL == 0)
               {
                  virtualTrails[idx].virtualSL = newVSL;
                  virtualTrails[idx].lastUpdate = TimeCurrent();
                  
                  PrintFormat("VIRTUAL TRAIL [SELL #%d] SL moved to %.5f (Profit: %.1f pts)", 
                             ticket, newVSL, profitPoints);
               }
            }
            
            // CEK: Apakah harga sudah menyentuh virtual SL?
            if(virtualTrails[idx].virtualSL > 0 && ask >= virtualTrails[idx].virtualSL)
            {
               PrintFormat("VIRTUAL SL HIT [SELL #%d] @ %.5f | VirtualSL: %.5f", 
                          ticket, ask, virtualTrails[idx].virtualSL);
               trade.PositionClose(ticket);
               RemoveVirtualTrail(ticket);
            }
         }
      }
   }
}

//+------------------------------------------------------------------+
//| VIRTUAL TRAILING untuk Pending Orders                            |
//| Geser pending order mengikuti harga tanpa modify berlebihan      |
//+------------------------------------------------------------------+
void ManagePendingTrailing()
{
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   
   // Untuk pending order, kita tetap perlu modify tapi dengan interval
   // Hanya modify jika pergerakan sudah lebih dari PendingTrailDist
   static datetime lastPendingModify = 0;
   if(TimeCurrent() - lastPendingModify < 5) return; // Min 5 detik antar modify
   
   bool modified = false;
   
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if(!orderInfo.SelectByIndex(i)) continue;
      if(orderInfo.Magic() != MagicNumber) continue;
      if(orderInfo.Symbol() != _Symbol) continue;
      
      ulong ticket = orderInfo.Ticket();
      double orderPrice = orderInfo.PriceOpen();
      ENUM_ORDER_TYPE orderType = orderInfo.OrderType();
      
      if(orderType == ORDER_TYPE_BUY_STOP)
      {
         double idealPrice = ask + (PendingTrailDist * point);
         double diff = MathAbs(orderPrice - idealPrice) / point;
         
         // Hanya modify jika jaraknya sudah signifikan (> grid distance / 2)
         if(diff > GridDistance / 2 && idealPrice < orderPrice)
         {
            double sl = (InitialSL > 0) ? idealPrice - (InitialSL * point) : 0;
            double tp = (TakeProfit > 0) ? idealPrice + (TakeProfit * point) : 0;
            trade.OrderModify(ticket, idealPrice, sl, tp, ORDER_TIME_GTC, 0);
            modified = true;
         }
      }
      else if(orderType == ORDER_TYPE_SELL_STOP)
      {
         double idealPrice = bid - (PendingTrailDist * point);
         double diff = MathAbs(orderPrice - idealPrice) / point;
         
         if(diff > GridDistance / 2 && idealPrice > orderPrice)
         {
            double sl = (InitialSL > 0) ? idealPrice + (InitialSL * point) : 0;
            double tp = (TakeProfit > 0) ? idealPrice - (TakeProfit * point) : 0;
            trade.OrderModify(ticket, idealPrice, sl, tp, ORDER_TIME_GTC, 0);
            modified = true;
         }
      }
   }
   
   if(modified) lastPendingModify = TimeCurrent();
}

//+------------------------------------------------------------------+
//| Place Grid Orders                                                 |
//+------------------------------------------------------------------+
void PlaceGrid()
{
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   double stopLevel = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * point;
   
   gridBasePrice = (GridDirection == GRID_SELL) ? bid : ask;
   
   Print("=== Placing Grid Orders | Base: ", gridBasePrice, " ===");
   
   for(int i = 1; i <= GridLevels; i++)
   {
      double lot = NormalizeDouble(LotSize * MathPow(LotMultiplier, i - 1), 2);
      if(lot < SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN))
         lot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
      
      double distance = GridDistance * i * point;
      
      // BUY STOP Grid
      if(GridDirection == GRID_BUY || GridDirection == GRID_BOTH)
      {
         double price = NormalizeDouble(ask + distance, digits);
         
         // Pastikan jarak cukup dari harga current
         if(price - ask > stopLevel)
         {
            double sl = (InitialSL > 0) ? NormalizeDouble(price - InitialSL * point, digits) : 0;
            double tp = (TakeProfit > 0) ? NormalizeDouble(price + TakeProfit * point, digits) : 0;
            
            string comment = StringFormat("Grid_BUY_L%d", i);
            trade.BuyStop(lot, price, _Symbol, sl, tp, ORDER_TIME_GTC, 0, comment);
            
            if(trade.ResultRetcode() == TRADE_RETCODE_DONE)
               PrintFormat("Grid BUY STOP Level %d placed @ %.5f | Lot: %.2f", i, price, lot);
            else
               PrintFormat("ERROR placing BUY STOP L%d: %d - %s", i, trade.ResultRetcode(), trade.ResultRetcodeDescription());
         }
      }
      
      // SELL STOP Grid
      if(GridDirection == GRID_SELL || GridDirection == GRID_BOTH)
      {
         double price = NormalizeDouble(bid - distance, digits);
         
         if(bid - price > stopLevel)
         {
            double sl = (InitialSL > 0) ? NormalizeDouble(price + InitialSL * point, digits) : 0;
            double tp = (TakeProfit > 0) ? NormalizeDouble(price - TakeProfit * point, digits) : 0;
            
            string comment = StringFormat("Grid_SELL_L%d", i);
            trade.SellStop(lot, price, _Symbol, sl, tp, ORDER_TIME_GTC, 0, comment);
            
            if(trade.ResultRetcode() == TRADE_RETCODE_DONE)
               PrintFormat("Grid SELL STOP Level %d placed @ %.5f | Lot: %.2f", i, price, lot);
            else
               PrintFormat("ERROR placing SELL STOP L%d: %d - %s", i, trade.ResultRetcode(), trade.ResultRetcodeDescription());
         }
      }
   }
   
   gridActive = true;
   Print("=== Grid Placed Successfully ===");
}

//+------------------------------------------------------------------+
//| Virtual Trail Helper Functions                                    |
//+------------------------------------------------------------------+
int FindVirtualTrail(ulong ticket)
{
   for(int i = 0; i < ArraySize(virtualTrails); i++)
   {
      if(virtualTrails[i].ticket == ticket) return i;
   }
   return -1;
}

int AddVirtualTrail(ulong ticket)
{
   int size = ArraySize(virtualTrails);
   ArrayResize(virtualTrails, size + 1);
   virtualTrails[size].ticket = ticket;
   virtualTrails[size].virtualSL = 0;
   virtualTrails[size].highestProfit = 0;
   virtualTrails[size].trailActive = false;
   virtualTrails[size].lastUpdate = TimeCurrent();
   return size;
}

void RemoveVirtualTrail(ulong ticket)
{
   int idx = FindVirtualTrail(ticket);
   if(idx == -1) return;
   
   int last = ArraySize(virtualTrails) - 1;
   if(idx != last) virtualTrails[idx] = virtualTrails[last];
   ArrayResize(virtualTrails, last);
}

// Bersihkan virtual trail untuk posisi yang sudah tidak ada
void CleanupVirtualTrails()
{
   for(int i = ArraySize(virtualTrails) - 1; i >= 0; i--)
   {
      bool found = false;
      for(int j = PositionsTotal() - 1; j >= 0; j--)
      {
         if(posInfo.SelectByIndex(j) && posInfo.Ticket() == virtualTrails[i].ticket)
         {
            found = true;
            break;
         }
      }
      if(!found) RemoveVirtualTrail(virtualTrails[i].ticket);
   }
}

//+------------------------------------------------------------------+
//| Count My Orders & Positions                                       |
//+------------------------------------------------------------------+
int CountMyOrders()
{
   int count = 0;
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if(orderInfo.SelectByIndex(i) && orderInfo.Magic() == MagicNumber && orderInfo.Symbol() == _Symbol)
         count++;
   }
   return count;
}

int CountMyPositions()
{
   int count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(posInfo.SelectByIndex(i) && posInfo.Magic() == MagicNumber && posInfo.Symbol() == _Symbol)
         count++;
   }
   return count;
}

//+------------------------------------------------------------------+
//| Close All Positions & Delete All Orders                           |
//+------------------------------------------------------------------+
void CloseAll(string reason)
{
   PrintFormat("=== CLOSE ALL: %s ===", reason);
   
   // Close positions
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(posInfo.SelectByIndex(i) && posInfo.Magic() == MagicNumber && posInfo.Symbol() == _Symbol)
      {
         trade.PositionClose(posInfo.Ticket());
      }
   }
   
   // Delete pending orders
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if(orderInfo.SelectByIndex(i) && orderInfo.Magic() == MagicNumber && orderInfo.Symbol() == _Symbol)
      {
         trade.OrderDelete(orderInfo.Ticket());
      }
   }
   
   // Reset
   gridActive = false;
   ArrayResize(virtualTrails, 0);
}

//+------------------------------------------------------------------+
//| Check Drawdown                                                    |
//+------------------------------------------------------------------+
bool CheckDrawdown()
{
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   
   if(balance <= 0) return false;
   
   double dd = ((balance - equity) / balance) * 100;
   
   if(dd >= MaxDrawdown)
   {
      CloseAll(StringFormat("Max Drawdown %.1f%% reached (Limit: %.1f%%)", dd, MaxDrawdown));
      return true;
   }
   return false;
}

//+------------------------------------------------------------------+
//| Check Profit Target                                               |
//+------------------------------------------------------------------+
bool CheckProfitTarget()
{
   double totalProfit = 0;
   
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(posInfo.SelectByIndex(i) && posInfo.Magic() == MagicNumber && posInfo.Symbol() == _Symbol)
      {
         totalProfit += posInfo.Profit() + posInfo.Swap() + posInfo.Commission();
      }
   }
   
   if(TotalProfitUSD > 0 && totalProfit >= TotalProfitUSD)
   {
      CloseAll(StringFormat("Profit Target reached: $%.2f", totalProfit));
      return true;
   }
   
   if(TotalLossUSD < 0 && totalProfit <= TotalLossUSD)
   {
      CloseAll(StringFormat("Loss Limit reached: $%.2f", totalProfit));
      return true;
   }
   
   return false;
}

//+------------------------------------------------------------------+
//| Time Filter                                                       |
//+------------------------------------------------------------------+
bool IsTradeTime()
{
   MqlDateTime dt;
   TimeCurrent(dt);
   
   if(StartHour < EndHour)
      return (dt.hour >= StartHour && dt.hour < EndHour);
   else
      return (dt.hour >= StartHour || dt.hour < EndHour);
}

//+------------------------------------------------------------------+
//| Panel Display                                                     |
//+------------------------------------------------------------------+
void CreatePanel()
{
   // Panel dibuat di UpdatePanel
}

void UpdatePanel()
{
   double totalProfit = 0;
   double totalLots = 0;
   int buyCount = 0, sellCount = 0;
   int pendingCount = CountMyOrders();
   
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(posInfo.SelectByIndex(i) && posInfo.Magic() == MagicNumber && posInfo.Symbol() == _Symbol)
      {
         totalProfit += posInfo.Profit() + posInfo.Swap() + posInfo.Commission();
         totalLots += posInfo.Volume();
         if(posInfo.PositionType() == POSITION_TYPE_BUY) buyCount++;
         else sellCount++;
      }
   }
   
   int activeTrails = 0;
   for(int i = 0; i < ArraySize(virtualTrails); i++)
   {
      if(virtualTrails[i].trailActive) activeTrails++;
   }
   
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double dd = (balance > 0) ? ((balance - equity) / balance) * 100 : 0;
   
   string info = "";
   info += "╔══════════════════════════════════╗\n";
   info += "║   GRID TRAILING STOP EA v2.0     ║\n";
   info += "║   Mode: VIRTUAL TRAILING         ║\n";
   info += "╠══════════════════════════════════╣\n";
   info += StringFormat("║ Buy Pos: %d | Sell Pos: %d        \n", buyCount, sellCount);
   info += StringFormat("║ Pending: %d | Total Lots: %.2f   \n", pendingCount, totalLots);
   info += StringFormat("║ Virtual Trails Active: %d         \n", activeTrails);
   info += "╠══════════════════════════════════╣\n";
   info += StringFormat("║ Profit: $%.2f                    \n", totalProfit);
   info += StringFormat("║ Drawdown: %.1f%%                  \n", dd);
   info += StringFormat("║ Balance: $%.2f                   \n", balance);
   info += StringFormat("║ Equity: $%.2f                    \n", equity);
   info += "╠══════════════════════════════════╣\n";
   
   // Show virtual SL levels
   for(int i = 0; i < ArraySize(virtualTrails); i++)
   {
      if(virtualTrails[i].trailActive)
      {
         info += StringFormat("║ #%d VSL: %.5f (%.1f pts)    \n", 
                            virtualTrails[i].ticket, 
                            virtualTrails[i].virtualSL,
                            virtualTrails[i].highestProfit);
      }
   }
   
   info += "╚══════════════════════════════════╝\n";
   
   Comment(info);
}

//+------------------------------------------------------------------+
//| Draw Grid Lines on Chart                                          |
//+------------------------------------------------------------------+
void DrawGridLines()
{
   if(gridBasePrice == 0) return;
   
   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   
   // Draw base line
   DrawHLine("GRID_BASE", gridBasePrice, clrWhite, STYLE_DASH);
   
   // Draw grid levels
   for(int i = 1; i <= GridLevels; i++)
   {
      double distance = GridDistance * i * point;
      
      if(GridDirection == GRID_BUY || GridDirection == GRID_BOTH)
      {
         double buyLevel = gridBasePrice + distance;
         DrawHLine(StringFormat("GRID_BUY_%d", i), buyLevel, clrLime, STYLE_DOT);
      }
      
      if(GridDirection == GRID_SELL || GridDirection == GRID_BOTH)
      {
         double sellLevel = gridBasePrice - distance;
         DrawHLine(StringFormat("GRID_SELL_%d", i), sellLevel, clrRed, STYLE_DOT);
      }
   }
   
   // Draw virtual SL lines
   for(int i = 0; i < ArraySize(virtualTrails); i++)
   {
      if(virtualTrails[i].trailActive && virtualTrails[i].virtualSL > 0)
      {
         DrawHLine(StringFormat("GRID_VSL_%d", i), virtualTrails[i].virtualSL, clrGold, STYLE_DASHDOT);
      }
   }
}

void DrawHLine(string name, double price, color clr, ENUM_LINE_STYLE style)
{
   if(ObjectFind(0, name) < 0)
   {
      ObjectCreate(0, name, OBJ_HLINE, 0, 0, price);
   }
   ObjectSetDouble(0, name, OBJPROP_PRICE, price);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, name, OBJPROP_STYLE, style);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, 1);
   ObjectSetInteger(0, name, OBJPROP_BACK, true);
}

//+------------------------------------------------------------------+
//| OnTrade Event - Detect ketika order tereksekusi                   |
//+------------------------------------------------------------------+
void OnTrade()
{
   // Cleanup virtual trails untuk posisi yang sudah tertutup
   CleanupVirtualTrails();
   
   // Cek apakah semua posisi sudah tertutup, reset grid
   if(gridActive && CountMyPositions() == 0 && CountMyOrders() == 0)
   {
      gridActive = false;
      gridBasePrice = 0;
      Print("=== Grid Cycle Complete - Ready for next grid ===");
   }
}
//+------------------------------------------------------------------+
