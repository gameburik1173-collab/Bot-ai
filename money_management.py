"""
=============================================================================
MONEY MANAGEMENT - Dynamic Lot Sizing & Risk Control
=============================================================================
Features:
- Dynamic lot sizing based on SL distance (1-2% risk per trade)
- Position sizing calculator
- Drawdown monitoring
- Trade count limiter
- Trailing stop & breakeven management
- Risk adjustment based on win/loss streaks
=============================================================================
"""

import numpy as np
from datetime import datetime, date
import logging

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False

from config import RISK_CONFIG, BROKER_CONFIG

logger = logging.getLogger(__name__)


class MoneyManager:
    """
    Dynamic money management system.
    Calculates lot size based on account balance, risk %, and SL distance.
    Monitors drawdown and enforces trading limits.
    """

    def __init__(self, data_handler=None):
        self.data_handler = data_handler
        self.config = RISK_CONFIG
        self.daily_trades = 0
        self.daily_pnl = 0.0
        self.last_trade_date = None
        self.consecutive_wins = 0
        self.consecutive_losses = 0
        self.peak_balance = 0.0
        self.current_drawdown = 0.0

    # ===================== LOT SIZE CALCULATION =====================
    def calculate_lot_size(self, entry_price, stop_loss, direction='buy'):
        """
        Calculate optimal lot size based on:
        - Account balance
        - Risk percentage (1-2%)
        - SL distance in pips

        Formula:
            Lot Size = (Balance * Risk%) / (SL_pips * Pip_value_per_lot)

        Args:
            entry_price: Entry price
            stop_loss: Stop loss price
            direction: 'buy' or 'sell'

        Returns:
            dict with lot_size, risk_amount, sl_pips, details
        """
        # Get account info
        account_info = self._get_account_info()
        if account_info is None:
            logger.error("Cannot get account info for lot calculation")
            return None

        balance = account_info['balance']
        equity = account_info['equity']

        # Use the lower of balance/equity for safety
        base_amount = min(balance, equity)

        # Calculate SL distance in pips
        sl_pips = self._calculate_sl_pips(entry_price, stop_loss, direction)

        if sl_pips <= 0:
            logger.error(f"Invalid SL distance: {sl_pips} pips")
            return None

        # Validate SL within limits
        if sl_pips < self.config['sl_min_pips']:
            logger.warning(f"SL ({sl_pips:.1f} pips) below minimum ({self.config['sl_min_pips']})")
            sl_pips = self.config['sl_min_pips']
        elif sl_pips > self.config['sl_max_pips']:
            logger.warning(f"SL ({sl_pips:.1f} pips) above maximum ({self.config['sl_max_pips']})")
            sl_pips = self.config['sl_max_pips']

        # Determine risk percentage (adaptive)
        risk_percent = self._get_adaptive_risk()

        # Calculate risk amount in account currency
        risk_amount = base_amount * (risk_percent / 100.0)

        # Get pip value per lot for the symbol
        pip_value_per_lot = self._get_pip_value_per_lot()

        if pip_value_per_lot <= 0:
            logger.error("Cannot determine pip value per lot")
            return None

        # Calculate lot size
        lot_size = risk_amount / (sl_pips * pip_value_per_lot)

        # Round to valid lot size
        lot_size = self._round_lot_size(lot_size)

        # Validate lot size
        symbol_info = self._get_symbol_info()
        if symbol_info:
            min_lot = symbol_info.get('volume_min', 0.01)
            max_lot = symbol_info.get('volume_max', 100.0)
            lot_size = max(min_lot, min(lot_size, max_lot))

        # Calculate actual risk with rounded lot
        actual_risk = lot_size * sl_pips * pip_value_per_lot
        actual_risk_percent = (actual_risk / base_amount) * 100

        result = {
            'lot_size': lot_size,
            'risk_amount': actual_risk,
            'risk_percent': actual_risk_percent,
            'sl_pips': sl_pips,
            'pip_value_per_lot': pip_value_per_lot,
            'balance': balance,
            'equity': equity,
            'base_risk_percent': risk_percent,
        }

        logger.info(
            f"Lot calculation: {lot_size:.2f} lots | "
            f"Risk: ${actual_risk:.2f} ({actual_risk_percent:.1f}%) | "
            f"SL: {sl_pips:.1f} pips"
        )

        return result

    def _calculate_sl_pips(self, entry_price, stop_loss, direction):
        """Calculate SL distance in pips."""
        pip_value = self._get_pip_size()

        if direction == 'buy':
            sl_distance = entry_price - stop_loss
        else:
            sl_distance = stop_loss - entry_price

        return abs(sl_distance) / pip_value

    def _get_pip_size(self):
        """Get pip size for the trading symbol."""
        symbol = BROKER_CONFIG['symbol']
        if symbol in ["XAUUSD", "GOLD"]:
            return 0.1  # Gold: 1 pip = $0.1 movement
        elif "JPY" in symbol:
            return 0.01
        else:
            return 0.0001  # Standard forex

    def _get_pip_value_per_lot(self):
        """
        Get pip value per standard lot in account currency.

        For XAUUSD: 1 pip (0.1) * 100 oz = $10 per standard lot
        For EUR/USD: 1 pip (0.0001) * 100,000 = $10 per standard lot
        """
        symbol = BROKER_CONFIG['symbol']

        if MT5_AVAILABLE:
            try:
                symbol_info = mt5.symbol_info(symbol)
                if symbol_info:
                    # Calculate from contract size and tick value
                    tick_value = symbol_info.trade_tick_value
                    tick_size = symbol_info.trade_tick_size
                    pip_size = self._get_pip_size()

                    if tick_size > 0:
                        pip_value = (pip_size / tick_size) * tick_value
                        return pip_value
            except Exception as e:
                logger.warning(f"MT5 pip value calculation failed: {e}")

        # Fallback estimates
        if symbol in ["XAUUSD", "GOLD"]:
            return 10.0   # $10 per pip per standard lot
        elif "JPY" in symbol:
            return 10.0   # Approximately
        else:
            return 10.0   # Standard for major pairs

    def _round_lot_size(self, lot_size):
        """Round lot size to broker's lot step (typically 0.01)."""
        lot_step = 0.01  # Default micro lot step

        if MT5_AVAILABLE:
            try:
                symbol_info = mt5.symbol_info(BROKER_CONFIG['symbol'])
                if symbol_info:
                    lot_step = symbol_info.volume_step
            except Exception:
                pass

        # Round down to nearest lot step
        rounded = int(lot_size / lot_step) * lot_step
        return round(rounded, 2)

    def _get_symbol_info(self):
        """Get symbol info from MT5 or defaults."""
        if MT5_AVAILABLE:
            try:
                info = mt5.symbol_info(BROKER_CONFIG['symbol'])
                if info:
                    return {
                        'volume_min': info.volume_min,
                        'volume_max': info.volume_max,
                        'volume_step': info.volume_step,
                    }
            except Exception:
                pass

        return {
            'volume_min': 0.01,
            'volume_max': 100.0,
            'volume_step': 0.01,
        }

    # ===================== ADAPTIVE RISK =====================
    def _get_adaptive_risk(self):
        """
        Get adaptive risk percentage based on:
        - Win/loss streaks
        - Current drawdown
        - Market conditions
        """
        base_risk = self.config['risk_percent']

        # Reduce risk on losing streak
        if self.consecutive_losses >= 3:
            reduction = 0.2 * (self.consecutive_losses - 2)
            base_risk = max(self.config['risk_min'], base_risk - reduction)
            logger.info(f"Risk reduced to {base_risk}% (losing streak: {self.consecutive_losses})")

        # Slightly increase on winning streak (max 2%)
        elif self.consecutive_wins >= 3:
            boost = 0.1 * (self.consecutive_wins - 2)
            base_risk = min(self.config['risk_max'], base_risk + boost)
            logger.info(f"Risk increased to {base_risk}% (winning streak: {self.consecutive_wins})")

        # Reduce if in drawdown
        if self.current_drawdown > 3.0:
            dd_factor = 1.0 - ((self.current_drawdown - 3.0) / 10.0)
            base_risk *= max(0.5, dd_factor)
            logger.info(f"Risk adjusted for drawdown: {base_risk:.2f}%")

        return max(self.config['risk_min'], min(base_risk, self.config['risk_max']))

    # ===================== ACCOUNT INFO =====================
    def _get_account_info(self):
        """Get current account balance and equity."""
        if MT5_AVAILABLE:
            try:
                info = mt5.account_info()
                if info:
                    return {
                        'balance': info.balance,
                        'equity': info.equity,
                        'margin': info.margin,
                        'free_margin': info.margin_free,
                        'profit': info.profit,
                    }
            except Exception as e:
                logger.error(f"MT5 account info error: {e}")

        # Fallback for testing
        return {
            'balance': 10000.0,
            'equity': 10000.0,
            'margin': 0.0,
            'free_margin': 10000.0,
            'profit': 0.0,
        }

    # ===================== TRADE VALIDATION =====================
    def can_open_trade(self):
        """
        Check if we're allowed to open a new trade.

        Returns:
            tuple: (allowed: bool, reason: str)
        """
        # Reset daily counter if new day
        today = date.today()
        if self.last_trade_date != today:
            self.daily_trades = 0
            self.daily_pnl = 0.0
            self.last_trade_date = today

        # Check daily trade limit
        if self.daily_trades >= self.config['max_trades_per_day']:
            return False, f"Daily trade limit reached ({self.config['max_trades_per_day']})"

        # Check drawdown
        self._update_drawdown()
        if self.current_drawdown >= self.config['max_drawdown_percent']:
            return False, f"Max drawdown reached ({self.current_drawdown:.1f}%)"

        # Check margin
        account = self._get_account_info()
        if account and account['free_margin'] < account['balance'] * 0.1:
            return False, "Insufficient free margin (<10%)"

        return True, "Trade allowed"

    def validate_signal_risk(self, signal):
        """
        Validate that a signal meets risk management criteria.

        Args:
            signal: TradeSignal object

        Returns:
            tuple: (valid: bool, reason: str, adjusted_signal: TradeSignal)
        """
        pip_size = self._get_pip_size()

        # Check RR ratio
        if signal.direction == 'buy':
            sl_distance = signal.entry_price - signal.stop_loss
            tp_distance = signal.take_profit - signal.entry_price
        else:
            sl_distance = signal.stop_loss - signal.entry_price
            tp_distance = signal.entry_price - signal.take_profit

        if sl_distance <= 0:
            return False, "Invalid SL (wrong direction)", signal

        actual_rr = tp_distance / sl_distance if sl_distance > 0 else 0

        if actual_rr < self.config['rr_minimum']:
            # Try to adjust TP to meet minimum RR
            if signal.direction == 'buy':
                signal.take_profit = signal.entry_price + (sl_distance * self.config['rr_minimum'])
            else:
                signal.take_profit = signal.entry_price - (sl_distance * self.config['rr_minimum'])
            signal.risk_reward = self.config['rr_minimum']
            logger.info(f"TP adjusted to meet minimum RR ({self.config['rr_minimum']})")

        # Check SL distance in pips
        sl_pips = sl_distance / pip_size
        if sl_pips < self.config['sl_min_pips']:
            return False, f"SL too tight ({sl_pips:.1f} pips < {self.config['sl_min_pips']})", signal
        if sl_pips > self.config['sl_max_pips']:
            return False, f"SL too wide ({sl_pips:.1f} pips > {self.config['sl_max_pips']})", signal

        return True, "Signal valid", signal

    # ===================== DRAWDOWN MONITORING =====================
    def _update_drawdown(self):
        """Update current drawdown calculation."""
        account = self._get_account_info()
        if account is None:
            return

        equity = account['equity']

        # Update peak
        if equity > self.peak_balance:
            self.peak_balance = equity

        # Calculate drawdown
        if self.peak_balance > 0:
            self.current_drawdown = ((self.peak_balance - equity) / self.peak_balance) * 100
        else:
            self.current_drawdown = 0.0

    # ===================== TRADE TRACKING =====================
    def record_trade_result(self, profit_pips, profit_amount):
        """Record trade result for adaptive risk."""
        self.daily_trades += 1
        self.daily_pnl += profit_amount

        if profit_amount > 0:
            self.consecutive_wins += 1
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1
            self.consecutive_wins = 0

        self._update_drawdown()

        logger.info(
            f"Trade recorded: {'Win' if profit_amount > 0 else 'Loss'} "
            f"| Streak W:{self.consecutive_wins} L:{self.consecutive_losses} "
            f"| Daily PnL: ${self.daily_pnl:.2f} | DD: {self.current_drawdown:.1f}%"
        )

    # ===================== TRAILING STOP & BREAKEVEN =====================
    def calculate_trailing_stop(self, entry_price, current_price, direction, current_sl):
        """
        Calculate trailing stop level.

        Args:
            entry_price: Original entry price
            current_price: Current market price
            direction: 'buy' or 'sell'
            current_sl: Current stop loss level

        Returns:
            float: New SL level, or None if no update needed
        """
        pip_size = self._get_pip_size()
        activate_pips = self.config['trailing_stop_activate_pips']
        trail_distance = self.config['trailing_stop_distance_pips']

        if direction == 'buy':
            profit_pips = (current_price - entry_price) / pip_size

            if profit_pips >= activate_pips:
                new_sl = current_price - (trail_distance * pip_size)
                if new_sl > current_sl:
                    return new_sl

        elif direction == 'sell':
            profit_pips = (entry_price - current_price) / pip_size

            if profit_pips >= activate_pips:
                new_sl = current_price + (trail_distance * pip_size)
                if new_sl < current_sl:
                    return new_sl

        return None

    def calculate_breakeven(self, entry_price, current_price, direction, current_sl):
        """
        Check if we should move SL to breakeven.

        Returns:
            float: Breakeven SL level, or None if not triggered
        """
        pip_size = self._get_pip_size()
        activate_pips = self.config['breakeven_activate_pips']
        buffer_pips = 2  # Small buffer above/below entry

        if direction == 'buy':
            profit_pips = (current_price - entry_price) / pip_size
            if profit_pips >= activate_pips and current_sl < entry_price:
                return entry_price + (buffer_pips * pip_size)

        elif direction == 'sell':
            profit_pips = (entry_price - current_price) / pip_size
            if profit_pips >= activate_pips and current_sl > entry_price:
                return entry_price - (buffer_pips * pip_size)

        return None

    # ===================== SUMMARY =====================
    def get_risk_summary(self):
        """Get current risk management status summary."""
        account = self._get_account_info()
        self._update_drawdown()

        return {
            'balance': account['balance'] if account else 0,
            'equity': account['equity'] if account else 0,
            'current_risk_percent': self._get_adaptive_risk(),
            'daily_trades': self.daily_trades,
            'max_daily_trades': self.config['max_trades_per_day'],
            'daily_pnl': self.daily_pnl,
            'current_drawdown': self.current_drawdown,
            'max_drawdown': self.config['max_drawdown_percent'],
            'consecutive_wins': self.consecutive_wins,
            'consecutive_losses': self.consecutive_losses,
            'peak_balance': self.peak_balance,
            'can_trade': self.can_open_trade()[0],
        }
