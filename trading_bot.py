"""
=============================================================================
TRADING BOT - Main Orchestrator
=============================================================================
Advanced Trading Bot with:
- Breakout + Pullback Strategy
- QM (Quasimodo) Pattern Strategy
- Multi-Timeframe Analysis (M15 trend, M5 signals, M1/M3 micro)
- Dynamic Lot Sizing (1-2% risk based on SL distance)
- Minimum RR 1:2
- SL at weak SR (30-60 pips)
- Self-Learning capability

Usage:
    python trading_bot.py              # Run in live mode
    python trading_bot.py --backtest   # Run backtest
    python trading_bot.py --status     # Show status
    python trading_bot.py --report     # Show performance report
=============================================================================
"""

import time
import signal
import sys
import json
import logging
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False

from config import (
    BROKER_CONFIG, LOG_CONFIG, RISK_CONFIG,
    NOTIFICATION_CONFIG, TIMEFRAMES
)
from ai_agent import AIAgent

# ===================== LOGGING SETUP =====================
def setup_logging():
    """Configure logging with file and console output."""
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, LOG_CONFIG['level'], logging.INFO))

    # File handler with rotation
    file_handler = RotatingFileHandler(
        LOG_CONFIG['file'],
        maxBytes=LOG_CONFIG['max_size_mb'] * 1024 * 1024,
        backupCount=LOG_CONFIG['backup_count']
    )
    file_format = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_format)
    logger.addHandler(file_handler)

    # Console handler
    if LOG_CONFIG['console_output']:
        console_handler = logging.StreamHandler()
        console_format = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(message)s',
            datefmt='%H:%M:%S'
        )
        console_handler.setFormatter(console_format)
        logger.addHandler(console_handler)

    return logging.getLogger(__name__)


logger = setup_logging()


# ===================== TRADING BOT CLASS =====================
class TradingBot:
    """
    Main trading bot orchestrator.
    Runs the analysis loop and manages trade execution.
    """

    def __init__(self):
        self.agent = AIAgent()
        self.running = False
        self.loop_interval = 30  # Seconds between analysis cycles
        self.trade_check_interval = 5  # Seconds between trade management checks
        self.last_analysis_time = None
        self.last_trade_check_time = None

        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.running = False

    # ===================== MAIN RUN LOOP =====================
    def run(self):
        """Main bot execution loop."""
        logger.info("=" * 70)
        logger.info("  ADVANCED TRADING BOT - Starting")
        logger.info("=" * 70)
        logger.info(f"  Symbol: {BROKER_CONFIG['symbol']}")
        logger.info(f"  Timeframes: {TIMEFRAMES}")
        logger.info(f"  Risk: {RISK_CONFIG['risk_percent']}% per trade")
        logger.info(f"  RR Minimum: 1:{RISK_CONFIG['rr_minimum']}")
        logger.info(f"  SL Range: {RISK_CONFIG['sl_min_pips']}-{RISK_CONFIG['sl_max_pips']} pips")
        logger.info(f"  Max Daily Trades: {RISK_CONFIG['max_trades_per_day']}")
        logger.info(f"  Analysis Interval: {self.loop_interval}s")
        logger.info("=" * 70)

        # Initialize
        if not self.agent.initialize():
            logger.error("Failed to initialize AI Agent. Exiting.")
            return

        self.running = True
        logger.info("Bot is now running. Press Ctrl+C to stop.")

        try:
            while self.running:
                now = datetime.utcnow()

                # Main analysis cycle
                if self._should_analyze(now):
                    self._run_analysis_cycle()
                    self.last_analysis_time = now

                # Trade management cycle (more frequent)
                if self._should_check_trades(now):
                    self._run_trade_management()
                    self.last_trade_check_time = now

                # Sleep briefly to prevent CPU spinning
                time.sleep(1)

        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}", exc_info=True)
        finally:
            self._shutdown()

    def _should_analyze(self, now):
        """Check if it's time for a new analysis cycle."""
        if self.last_analysis_time is None:
            return True
        elapsed = (now - self.last_analysis_time).total_seconds()
        return elapsed >= self.loop_interval

    def _should_check_trades(self, now):
        """Check if it's time to manage open trades."""
        if self.last_trade_check_time is None:
            return True
        elapsed = (now - self.last_trade_check_time).total_seconds()
        return elapsed >= self.trade_check_interval

    # ===================== ANALYSIS CYCLE =====================
    def _run_analysis_cycle(self):
        """Run one full analysis cycle."""
        try:
            logger.debug("--- Analysis Cycle Start ---")

            # Run AI analysis
            decision = self.agent.analyze_market()

            if decision['decision'] == 'open_trade':
                self._execute_trade(decision)
            elif decision['decision'] == 'no_trade':
                reason = decision.get('reason', 'Unknown')
                logger.debug(f"No trade: {reason}")
            elif decision['decision'] == 'no_signal':
                logger.debug("No valid signals found")

        except Exception as e:
            logger.error(f"Error in analysis cycle: {e}", exc_info=True)

    # ===================== TRADE EXECUTION =====================
    def _execute_trade(self, decision):
        """
        Execute a trade based on AI decision.

        Args:
            decision: dict from AIAgent.analyze_market()
        """
        order = decision['order']
        analysis = decision['analysis']

        logger.info("=" * 50)
        logger.info("EXECUTING TRADE")
        logger.info(f"  {order['direction'].upper()} {order['symbol']}")
        logger.info(f"  Lot: {order['lot_size']}")
        logger.info(f"  Entry: {order['entry_price']:.2f}")
        logger.info(f"  SL: {order['stop_loss']:.2f}")
        logger.info(f"  TP: {order['take_profit']:.2f}")
        logger.info(f"  Strategy: {analysis['strategy']}")
        logger.info(f"  Confidence: {analysis['confidence']:.2f}")
        logger.info("=" * 50)

        if not MT5_AVAILABLE:
            logger.warning("MT5 not available - SIMULATED execution")
            self._simulate_trade(order, analysis)
            return

        # Prepare MT5 order
        symbol_info = mt5.symbol_info(order['symbol'])
        if symbol_info is None:
            logger.error(f"Symbol {order['symbol']} not found")
            return

        if not symbol_info.visible:
            mt5.symbol_select(order['symbol'], True)

        # Get current price for order
        tick = mt5.symbol_info_tick(order['symbol'])
        if tick is None:
            logger.error("Cannot get current tick")
            return

        # Determine order type and price
        if order['direction'] == 'buy':
            order_type = mt5.ORDER_TYPE_BUY
            price = tick.ask
        else:
            order_type = mt5.ORDER_TYPE_SELL
            price = tick.bid

        # Build request
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": order['symbol'],
            "volume": order['lot_size'],
            "type": order_type,
            "price": price,
            "sl": order['stop_loss'],
            "tp": order['take_profit'],
            "deviation": 20,  # Slippage tolerance in points
            "magic": BROKER_CONFIG['magic_number'],
            "comment": f"AI_{analysis['strategy']}_{analysis['confidence']:.0f}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        # Send order
        result = mt5.order_send(request)

        if result is None:
            logger.error(f"Order send failed: {mt5.last_error()}")
            return

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(
                f"Order failed: retcode={result.retcode}, "
                f"comment={result.comment}"
            )
            return

        # Success
        logger.info(f"Trade executed successfully! Ticket: {result.order}")

        # Track active trade
        active_trade = {
            'id': result.order,
            'ticket': result.order,
            'direction': order['direction'],
            'entry_price': price,
            'stop_loss': order['stop_loss'],
            'take_profit': order['take_profit'],
            'current_sl': order['stop_loss'],
            'lot_size': order['lot_size'],
            'strategy': analysis['strategy'],
            'confidence': analysis['confidence'],
            'open_time': str(datetime.utcnow()),
            'session': analysis.get('session'),
            'market_condition': analysis.get('market_type'),
        }
        self.agent.active_trades.append(active_trade)

        # Send notification
        self._notify_trade_opened(active_trade)

    def _simulate_trade(self, order, analysis):
        """Simulate trade execution for testing without MT5."""
        import random
        fake_ticket = random.randint(100000, 999999)

        active_trade = {
            'id': fake_ticket,
            'ticket': fake_ticket,
            'direction': order['direction'],
            'entry_price': order['entry_price'],
            'stop_loss': order['stop_loss'],
            'take_profit': order['take_profit'],
            'current_sl': order['stop_loss'],
            'lot_size': order['lot_size'],
            'strategy': analysis['strategy'],
            'confidence': analysis['confidence'],
            'open_time': str(datetime.utcnow()),
            'session': analysis.get('session'),
            'market_condition': analysis.get('market_type'),
            'simulated': True,
        }
        self.agent.active_trades.append(active_trade)
        logger.info(f"[SIMULATED] Trade opened: ticket={fake_ticket}")


    # ===================== TRADE MANAGEMENT =====================
    def _run_trade_management(self):
        """Manage open trades (trailing stop, breakeven, close detection)."""
        if not self.agent.active_trades:
            return

        # Let AI agent manage trades
        updates = self.agent.manage_open_trades()

        # Apply updates to MT5
        for update in updates:
            self._apply_trade_update(update)

        # Check for closed trades
        self._check_closed_trades()

    def _apply_trade_update(self, update):
        """Apply a trade update (modify SL) in MT5."""
        if not MT5_AVAILABLE:
            logger.debug(f"[SIMULATED] Trade update: {update}")
            return

        trade_id = update.get('trade_id')
        new_sl = update.get('new_sl')
        update_type = update.get('type')

        if trade_id is None or new_sl is None:
            return

        # Find the position
        position = mt5.positions_get(ticket=trade_id)
        if not position:
            return

        pos = position[0]

        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": pos.symbol,
            "position": trade_id,
            "sl": new_sl,
            "tp": pos.tp,
            "magic": BROKER_CONFIG['magic_number'],
        }

        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(f"Trade {trade_id}: {update_type} applied, new SL={new_sl:.2f}")
        else:
            logger.warning(f"Failed to update trade {trade_id}: {result}")

    def _check_closed_trades(self):
        """Check if any active trades have been closed."""
        if not MT5_AVAILABLE:
            return

        closed_tickets = []

        for trade in self.agent.active_trades:
            ticket = trade.get('ticket')
            if ticket is None:
                continue

            # Check if position still exists
            position = mt5.positions_get(ticket=ticket)
            if not position:
                # Position closed - get deal history
                closed_tickets.append(trade)

        # Process closed trades
        for trade in closed_tickets:
            self._process_closed_trade(trade)

    def _process_closed_trade(self, trade):
        """Process a trade that has been closed."""
        ticket = trade.get('ticket')

        # Try to get the closing deal
        close_price = trade['entry_price']  # Default
        profit_amount = 0.0

        if MT5_AVAILABLE:
            # Get deals for this position
            from_date = datetime.utcnow() - timedelta(days=1)
            deals = mt5.history_deals_get(
                from_date,
                datetime.utcnow(),
                position=ticket
            )
            if deals and len(deals) > 1:
                close_deal = deals[-1]
                close_price = close_deal.price
                profit_amount = close_deal.profit

        # Calculate profit in pips
        pip_size = 0.1 if BROKER_CONFIG['symbol'] in ["XAUUSD", "GOLD"] else 0.0001
        if trade['direction'] == 'buy':
            profit_pips = (close_price - trade['entry_price']) / pip_size
        else:
            profit_pips = (trade['entry_price'] - close_price) / pip_size

        # Calculate actual RR
        sl_distance = abs(trade['entry_price'] - trade['stop_loss'])
        if sl_distance > 0:
            if trade['direction'] == 'buy':
                actual_rr = (close_price - trade['entry_price']) / sl_distance
            else:
                actual_rr = (trade['entry_price'] - close_price) / sl_distance
        else:
            actual_rr = 0

        # Build trade result
        trade_result = {
            'id': ticket,
            'strategy': trade.get('strategy', 'unknown'),
            'direction': trade['direction'],
            'entry_price': trade['entry_price'],
            'exit_price': close_price,
            'stop_loss': trade['stop_loss'],
            'take_profit': trade['take_profit'],
            'profit_pips': profit_pips,
            'profit_amount': profit_amount,
            'risk_reward_actual': actual_rr,
            'session': trade.get('session', 'unknown'),
            'market_condition': trade.get('market_condition', 'unknown'),
            'confidence': trade.get('confidence', 0),
            'timeframe': 'M5',
            'open_time': trade.get('open_time'),
            'close_time': str(datetime.utcnow()),
            'pattern_details': {},
        }

        # Record in AI agent (updates learning + money manager)
        self.agent.record_closed_trade(trade_result)

        logger.info(
            f"Trade {ticket} closed: "
            f"{'WIN' if profit_amount > 0 else 'LOSS'} | "
            f"P/L: ${profit_amount:.2f} ({profit_pips:.1f} pips) | "
            f"RR: {actual_rr:.2f}"
        )

        # Send notification
        self._notify_trade_closed(trade_result)

    # ===================== NOTIFICATIONS =====================
    def _notify_trade_opened(self, trade):
        """Send notification when trade is opened."""
        if not NOTIFICATION_CONFIG.get('notify_on_trade'):
            return

        message = (
            f"NEW TRADE OPENED\n"
            f"{'BUY' if trade['direction'] == 'buy' else 'SELL'} "
            f"{BROKER_CONFIG['symbol']}\n"
            f"Entry: {trade['entry_price']:.2f}\n"
            f"SL: {trade['stop_loss']:.2f}\n"
            f"TP: {trade['take_profit']:.2f}\n"
            f"Lot: {trade['lot_size']}\n"
            f"Strategy: {trade['strategy']}\n"
            f"Confidence: {trade['confidence']:.0%}"
        )
        self._send_notification(message)

    def _notify_trade_closed(self, trade_result):
        """Send notification when trade is closed."""
        if not NOTIFICATION_CONFIG.get('notify_on_trade'):
            return

        emoji = "WIN" if trade_result['profit_amount'] > 0 else "LOSS"
        message = (
            f"TRADE CLOSED - {emoji}\n"
            f"{trade_result['direction'].upper()} {BROKER_CONFIG['symbol']}\n"
            f"P/L: ${trade_result['profit_amount']:.2f} "
            f"({trade_result['profit_pips']:.1f} pips)\n"
            f"RR: {trade_result['risk_reward_actual']:.2f}\n"
            f"Strategy: {trade_result['strategy']}"
        )
        self._send_notification(message)

    def _send_notification(self, message):
        """Send notification via Telegram (if configured)."""
        if not NOTIFICATION_CONFIG.get('telegram_enabled'):
            logger.debug(f"[Notification] {message}")
            return

        try:
            import requests
            token = NOTIFICATION_CONFIG['telegram_token']
            chat_id = NOTIFICATION_CONFIG['telegram_chat_id']
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
            requests.post(url, json=payload, timeout=10)
        except Exception as e:
            logger.warning(f"Failed to send notification: {e}")

    # ===================== SHUTDOWN =====================
    def _shutdown(self):
        """Graceful shutdown procedure."""
        logger.info("Shutting down trading bot...")

        # Show final status
        status = self.agent.get_status()
        logger.info(f"Final status: {json.dumps(status, indent=2, default=str)}")

        # Disconnect
        self.agent.shutdown()
        logger.info("Trading bot stopped.")


# ===================== CLI COMMANDS =====================
def show_status():
    """Show current bot status."""
    agent = AIAgent()
    if agent.initialize():
        status = agent.get_status()
        print("\n" + "=" * 50)
        print("  TRADING BOT STATUS")
        print("=" * 50)
        print(f"  Connected: {status['connected']}")
        print(f"  Active Trades: {status['active_trades']}")
        print(f"  Historical Trades: {status['total_historical_trades']}")
        print(f"  Overall Win Rate: {status['overall_winrate']:.1%}")
        print(f"  Confidence Threshold: {status['confidence_threshold']:.2f}")
        print(f"  Preferred Strategies: {status['preferred_strategies']}")
        print(f"\n  Risk Management:")
        rm = status['risk_management']
        print(f"    Balance: ${rm['balance']:.2f}")
        print(f"    Current Risk: {rm['current_risk_percent']:.1f}%")
        print(f"    Daily Trades: {rm['daily_trades']}/{rm['max_daily_trades']}")
        print(f"    Drawdown: {rm['current_drawdown']:.1f}%/{rm['max_drawdown']:.1f}%")
        print(f"    Can Trade: {rm['can_trade']}")
        print(f"\n  Learning Insights:")
        for insight in status['learning_insights']:
            print(f"    - {insight}")
        print("=" * 50)
        agent.shutdown()
    else:
        print("Failed to initialize agent")


def show_report():
    """Show performance report."""
    agent = AIAgent()
    report = agent.get_full_report()

    if 'message' in report:
        print(f"\n{report['message']}")
        return

    print("\n" + "=" * 60)
    print("  PERFORMANCE REPORT")
    print("=" * 60)

    s = report['summary']
    print(f"\n  SUMMARY:")
    print(f"    Total Trades: {s['total_trades']}")
    print(f"    Wins: {s['wins']} | Losses: {s['losses']}")
    print(f"    Win Rate: {s['winrate']:.1%}")
    print(f"    Total Profit: ${s['total_profit']:.2f}")
    print(f"    Avg Profit/Trade: ${s['avg_profit_per_trade']:.2f}")
    print(f"    Avg Win: ${s['avg_win']:.2f}")
    print(f"    Avg Loss: ${s['avg_loss']:.2f}")
    print(f"    Profit Factor: {s['profit_factor']:.2f}")
    print(f"    Expectancy: ${s['expectancy']:.2f}")
    print(f"    Best Win Streak: {s['max_win_streak']}")
    print(f"    Worst Loss Streak: {s['max_loss_streak']}")

    print(f"\n  STRATEGY BREAKDOWN:")
    for strat, stats in report.get('strategy_breakdown', {}).items():
        print(f"    {strat}:")
        print(f"      Trades: {stats['trades']} | WR: {stats['winrate']:.0%} | P/L: ${stats['total_profit']:.2f}")

    print(f"\n  SESSION BREAKDOWN:")
    for sess, stats in report.get('session_breakdown', {}).items():
        print(f"    {sess}: {stats['trades']} trades | WR: {stats['winrate']:.0%} | P/L: ${stats['total_profit']:.2f}")

    print("=" * 60)


def run_single_analysis():
    """Run a single analysis cycle (for testing)."""
    agent = AIAgent()
    if agent.initialize():
        print("\nRunning single analysis...")
        decision = agent.analyze_market()
        print(f"\nDecision: {decision['decision']}")
        if decision['decision'] == 'open_trade':
            order = decision['order']
            print(f"  Direction: {order['direction'].upper()}")
            print(f"  Entry: {order['entry_price']:.2f}")
            print(f"  SL: {order['stop_loss']:.2f}")
            print(f"  TP: {order['take_profit']:.2f}")
            print(f"  Lot: {order['lot_size']}")
            print(f"  Risk: ${order['risk_amount']:.2f} ({order['risk_percent']:.1f}%)")
            print(f"  RR: 1:{order['risk_reward']:.1f}")
        else:
            print(f"  Reason: {decision.get('reason', 'N/A')}")
        agent.shutdown()
    else:
        print("Failed to initialize agent")


# ===================== MAIN ENTRY POINT =====================
if __name__ == "__main__":
    args = sys.argv[1:] if len(sys.argv) > 1 else []

    if "--status" in args:
        show_status()
    elif "--report" in args:
        show_report()
    elif "--analyze" in args:
        run_single_analysis()
    elif "--help" in args:
        print("""
Advanced Trading Bot - Usage:
    python trading_bot.py              Run in live trading mode
    python trading_bot.py --analyze    Run single analysis cycle
    python trading_bot.py --status     Show bot status
    python trading_bot.py --report     Show performance report
    python trading_bot.py --help       Show this help
        """)
    else:
        # Default: run the bot
        bot = TradingBot()
        bot.run()
