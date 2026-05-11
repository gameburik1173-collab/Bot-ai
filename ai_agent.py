"""
=============================================================================
AI AGENT - Intelligent Trade Decision Engine
=============================================================================
Features:
- Ensemble model for trade scoring
- Integrates all strategies (Breakout+Pullback, QM, RBR/DBD)
- Multi-timeframe confluence scoring
- Self-learning feedback loop
- Final trade decision with confidence scoring
=============================================================================
"""

import numpy as np
from datetime import datetime
import logging

from config import AI_CONFIG, RISK_CONFIG, PREFERRED_SESSIONS
from ambil_data import DataHandler
from strategi import MultiTimeframeAnalyzer, TradeSignal
from money_management import MoneyManager
from self_learning import SelfLearning

logger = logging.getLogger(__name__)


class AIAgent:
    """
    AI-powered trade decision agent.
    Combines strategy signals, market analysis, risk management,
    and self-learning to make optimal trade decisions.
    """

    def __init__(self):
        self.data_handler = DataHandler()
        self.strategy_analyzer = MultiTimeframeAnalyzer(self.data_handler)
        self.money_manager = MoneyManager(self.data_handler)
        self.learner = SelfLearning()
        self.config = AI_CONFIG
        self.active_trades = []
        self.pending_signals = []

    # ===================== INITIALIZATION =====================
    def initialize(self):
        """Initialize all components."""
        logger.info("=" * 60)
        logger.info("AI AGENT - Initializing...")
        logger.info("=" * 60)

        # Connect to MT5
        if not self.data_handler.connect():
            logger.error("Failed to connect to MT5")
            return False

        # Fetch initial data
        if not self.data_handler.fetch_all_timeframes():
            logger.error("Failed to fetch initial data")
            return False

        # Calculate SR levels
        self.data_handler.calculate_sr_levels("M5")

        # Load learning insights
        insights = self.learner.get_learning_insights()
        for insight in insights:
            logger.info(f"Learning Insight: {insight}")

        logger.info("AI Agent initialized successfully")
        return True

    def shutdown(self):
        """Clean shutdown."""
        self.data_handler.disconnect()
        logger.info("AI Agent shut down")

    # ===================== MAIN DECISION LOOP =====================
    def analyze_market(self):
        """
        Full market analysis cycle.

        Returns:
            dict with analysis results and trade decision
        """
        logger.info("-" * 40)
        logger.info("Starting market analysis cycle...")

        # Step 1: Refresh data
        self.data_handler.refresh_data()
        self.data_handler.calculate_sr_levels("M5")

        # Step 2: Get market condition
        market_condition = self.data_handler.get_market_condition("M5")
        logger.info(
            f"Market: {market_condition.get('market_type', 'unknown')} | "
            f"Volatility: {market_condition.get('volatility_level', 'unknown')} | "
            f"Session: {market_condition.get('session', 'unknown')}"
        )

        # Step 3: Check if we should be trading
        pre_check = self._pre_trade_checks(market_condition)
        if not pre_check['can_trade']:
            logger.info(f"Pre-check failed: {pre_check['reason']}")
            return {
                'decision': 'no_trade',
                'reason': pre_check['reason'],
                'market_condition': market_condition,
            }

        # Step 4: Get strategy signals
        signals = self.strategy_analyzer.analyze()

        if not signals:
            logger.info("No signals found")
            return {
                'decision': 'no_signal',
                'reason': 'No valid signals from any strategy',
                'market_condition': market_condition,
            }

        # Step 5: Score and filter signals through AI
        scored_signals = self._score_signals(signals, market_condition)

        # Step 6: Select best signal
        best_signal = self._select_best_signal(scored_signals)

        if best_signal is None:
            return {
                'decision': 'no_trade',
                'reason': 'No signal passed all filters',
                'market_condition': market_condition,
                'signals_found': len(signals),
            }

        # Step 7: Final validation
        decision = self._make_final_decision(best_signal, market_condition)

        return decision

    # ===================== PRE-TRADE CHECKS =====================
    def _pre_trade_checks(self, market_condition):
        """
        Pre-trade validation checks.

        Returns:
            dict: {'can_trade': bool, 'reason': str}
        """
        # Check money management limits
        can_trade, reason = self.money_manager.can_open_trade()
        if not can_trade:
            return {'can_trade': False, 'reason': reason}

        # Check session preference
        session = market_condition.get('session', 'off_hours')
        if session == 'off_hours':
            return {'can_trade': False, 'reason': 'Outside trading hours'}

        # Check if session is in avoided list (from learning)
        avoid_sessions = self.learner.learning_data['parameter_adjustments'].get('avoid_sessions', [])
        if session in avoid_sessions:
            return {'can_trade': False, 'reason': f'Session {session} avoided (poor performance)'}

        # Check preferred sessions
        if session not in PREFERRED_SESSIONS:
            # Still allow but with reduced weight
            logger.debug(f"Non-preferred session: {session}")

        # Check volatility
        vol_level = market_condition.get('volatility_level', 'normal')
        if vol_level == 'low':
            logger.debug("Low volatility - signals may be less reliable")

        # Check hour avoidance
        hour = market_condition.get('hour_utc', 12)
        avoid_hours = self.learner.learning_data['parameter_adjustments'].get('avoid_hours', [])
        if hour in avoid_hours:
            return {'can_trade': False, 'reason': f'Hour {hour} avoided (poor historical performance)'}

        return {'can_trade': True, 'reason': 'All pre-checks passed'}

    # ===================== SIGNAL SCORING =====================
    def _score_signals(self, signals, market_condition):
        """
        Score each signal using ensemble approach.

        Scoring factors:
        1. Strategy confluence score (from strategy)
        2. Multi-timeframe alignment
        3. Market condition fit
        4. Self-learning adjustment
        5. Risk-reward quality
        6. Session suitability

        Args:
            signals: list of TradeSignal
            market_condition: dict

        Returns:
            list of (signal, final_score) tuples, sorted by score
        """
        scored = []

        for signal in signals:
            scores = {}

            # Factor 1: Base confluence score (from strategy)
            scores['confluence'] = signal.confluence_score

            # Factor 2: Multi-TF alignment
            scores['mtf_alignment'] = self._score_mtf_alignment(signal)

            # Factor 3: Market condition fit
            scores['market_fit'] = self._score_market_fit(signal, market_condition)

            # Factor 4: Self-learning adjustment
            scores['learning'] = self._score_learning(signal, market_condition)

            # Factor 5: Risk-Reward quality
            scores['rr_quality'] = self._score_risk_reward(signal)

            # Factor 6: Session suitability
            scores['session'] = self._score_session(market_condition)

            # Weighted ensemble score
            weights = {
                'confluence': 0.25,
                'mtf_alignment': 0.20,
                'market_fit': 0.15,
                'learning': 0.20,
                'rr_quality': 0.10,
                'session': 0.10,
            }

            final_score = sum(scores[k] * weights[k] for k in weights)
            final_score = min(1.0, max(0.0, final_score))

            scored.append((signal, final_score, scores))

            logger.debug(
                f"Signal scored: {signal.strategy} {signal.direction} | "
                f"Final: {final_score:.3f} | Breakdown: {scores}"
            )

        # Sort by final score (highest first)
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def _score_mtf_alignment(self, signal):
        """Score based on multi-timeframe alignment."""
        trend = self.data_handler.get_trend_direction("M15")
        if not trend:
            return 0.5

        score = 0.5

        # Direction alignment with M15
        if signal.direction == 'buy' and trend['direction'] == 'bullish':
            score += 0.3
        elif signal.direction == 'sell' and trend['direction'] == 'bearish':
            score += 0.3
        elif trend['direction'] == 'neutral':
            score += 0.1

        # Trend strength bonus
        score += trend['strength'] * 0.2

        # EMA200 alignment
        if signal.direction == 'buy' and trend.get('above_ema200'):
            score += 0.1
        elif signal.direction == 'sell' and not trend.get('above_ema200'):
            score += 0.1

        return min(1.0, score)

    def _score_market_fit(self, signal, market_condition):
        """Score based on how well signal fits current market."""
        score = 0.5
        market_type = market_condition.get('market_type', 'unknown')
        vol_level = market_condition.get('volatility_level', 'normal')

        # Breakout works best in trending markets
        if signal.strategy == 'breakout_pullback':
            if market_type == 'trending':
                score += 0.3
            elif market_type == 'weak_trend':
                score += 0.1
            else:
                score -= 0.1

        # QM works in both (reversal in ranging, continuation in trending)
        elif signal.strategy == 'qm_pattern':
            if market_type == 'ranging':
                score += 0.2  # QM good at range extremes
            elif market_type == 'trending':
                score += 0.15

        # RBR/DBD works best in trending markets
        elif signal.strategy == 'rbr_dbd':
            if market_type == 'trending':
                score += 0.3
            elif market_type == 'weak_trend':
                score += 0.1

        # Volatility consideration
        if vol_level == 'high':
            score += 0.1  # More opportunity but also more risk
        elif vol_level == 'low':
            score -= 0.15  # Less reliable signals

        return max(0.0, min(1.0, score))

    def _score_learning(self, signal, market_condition):
        """Score based on self-learning historical data."""
        # Get adjusted confidence from learner
        adjusted_conf = self.learner.get_adjusted_confidence(signal)

        # Get strategy-specific winrate
        strat_winrate = self.learner.get_strategy_winrate(signal.strategy)

        # Combine
        score = (adjusted_conf * 0.6) + (strat_winrate * 0.4)
        return min(1.0, max(0.0, score))

    def _score_risk_reward(self, signal):
        """Score based on risk-reward ratio quality."""
        rr = signal.risk_reward
        min_rr = RISK_CONFIG['rr_minimum']
        target_rr = RISK_CONFIG['rr_target']

        if rr >= target_rr:
            return 1.0
        elif rr >= min_rr:
            # Linear scale between min and target
            return 0.5 + 0.5 * ((rr - min_rr) / (target_rr - min_rr))
        else:
            return 0.2  # Below minimum but might still be adjusted

    def _score_session(self, market_condition):
        """Score based on trading session."""
        session = market_condition.get('session', 'off_hours')
        session_scores = {
            'overlap': 1.0,   # Best session (London + NY)
            'london': 0.85,
            'newyork': 0.75,
            'asian': 0.4,
            'off_hours': 0.1,
        }
        base_score = session_scores.get(session, 0.3)

        # Adjust with session winrate from learning
        session_winrate = self.learner.get_session_winrate(session)
        adjusted = (base_score * 0.6) + (session_winrate * 0.4)

        return min(1.0, adjusted)


    # ===================== SIGNAL SELECTION =====================
    def _select_best_signal(self, scored_signals):
        """
        Select the best signal from scored list.

        Args:
            scored_signals: list of (signal, score, breakdown) tuples

        Returns:
            TradeSignal or None
        """
        if not scored_signals:
            return None

        # Get minimum confidence threshold (from learning)
        threshold = self.learner.learning_data['parameter_adjustments']['confidence_threshold']

        for signal, score, breakdown in scored_signals:
            # Check minimum score
            if score < threshold:
                logger.debug(
                    f"Signal {signal.strategy} rejected: "
                    f"score {score:.3f} < threshold {threshold:.3f}"
                )
                continue

            # Check learning approval
            should_trade, reason, adj_conf = self.learner.should_take_trade(signal)
            if not should_trade:
                logger.debug(f"Signal rejected by learner: {reason}")
                continue

            # Update signal confidence with final score
            signal.confidence = score
            return signal

        return None

    # ===================== FINAL DECISION =====================
    def _make_final_decision(self, signal, market_condition):
        """
        Make the final trade decision with full validation.

        Args:
            signal: Best TradeSignal
            market_condition: Current market condition dict

        Returns:
            dict with full decision details
        """
        # Validate risk management
        valid, reason, adjusted_signal = self.money_manager.validate_signal_risk(signal)

        if not valid:
            logger.info(f"Signal failed risk validation: {reason}")
            return {
                'decision': 'no_trade',
                'reason': f'Risk validation failed: {reason}',
                'signal': signal.to_dict(),
                'market_condition': market_condition,
            }

        signal = adjusted_signal

        # Calculate lot size
        lot_info = self.money_manager.calculate_lot_size(
            signal.entry_price, signal.stop_loss, signal.direction
        )

        if lot_info is None:
            return {
                'decision': 'no_trade',
                'reason': 'Lot size calculation failed',
                'signal': signal.to_dict(),
                'market_condition': market_condition,
            }

        # Build trade order
        trade_order = {
            'decision': 'open_trade',
            'signal': signal.to_dict(),
            'order': {
                'symbol': self.data_handler.symbol,
                'direction': signal.direction,
                'lot_size': lot_info['lot_size'],
                'entry_price': signal.entry_price,
                'stop_loss': signal.stop_loss,
                'take_profit': signal.take_profit,
                'risk_amount': lot_info['risk_amount'],
                'risk_percent': lot_info['risk_percent'],
                'sl_pips': lot_info['sl_pips'],
                'risk_reward': signal.risk_reward,
            },
            'analysis': {
                'strategy': signal.strategy,
                'confidence': signal.confidence,
                'confluence_score': signal.confluence_score,
                'market_type': market_condition.get('market_type'),
                'session': market_condition.get('session'),
                'volatility': market_condition.get('volatility_level'),
                'trend_strength': market_condition.get('trend_strength'),
            },
            'market_condition': market_condition,
            'timestamp': str(datetime.utcnow()),
        }

        logger.info("=" * 50)
        logger.info("TRADE DECISION: OPEN TRADE")
        logger.info(f"  Strategy: {signal.strategy}")
        logger.info(f"  Direction: {signal.direction.upper()}")
        logger.info(f"  Entry: {signal.entry_price:.2f}")
        logger.info(f"  SL: {signal.stop_loss:.2f} ({lot_info['sl_pips']:.1f} pips)")
        logger.info(f"  TP: {signal.take_profit:.2f}")
        logger.info(f"  Lot: {lot_info['lot_size']:.2f}")
        logger.info(f"  Risk: ${lot_info['risk_amount']:.2f} ({lot_info['risk_percent']:.1f}%)")
        logger.info(f"  RR: 1:{signal.risk_reward:.1f}")
        logger.info(f"  Confidence: {signal.confidence:.2f}")
        logger.info("=" * 50)

        return trade_order

    # ===================== TRADE MANAGEMENT =====================
    def manage_open_trades(self):
        """
        Manage existing open trades:
        - Check for breakeven moves
        - Update trailing stops
        - Monitor trade status
        """
        if not self.active_trades:
            return []

        updates = []
        bid, ask = self.data_handler.get_current_price()

        if bid is None:
            return updates

        for trade in self.active_trades:
            current_price = bid if trade['direction'] == 'buy' else ask
            entry = trade['entry_price']
            current_sl = trade['current_sl']
            direction = trade['direction']

            # Check breakeven
            be_level = self.money_manager.calculate_breakeven(
                entry, current_price, direction, current_sl
            )
            if be_level is not None:
                trade['current_sl'] = be_level
                updates.append({
                    'type': 'breakeven',
                    'trade_id': trade.get('id'),
                    'new_sl': be_level,
                })
                logger.info(f"Trade {trade.get('id')}: Moved to breakeven at {be_level:.2f}")

            # Check trailing stop
            trail_level = self.money_manager.calculate_trailing_stop(
                entry, current_price, direction, trade['current_sl']
            )
            if trail_level is not None:
                trade['current_sl'] = trail_level
                updates.append({
                    'type': 'trailing_stop',
                    'trade_id': trade.get('id'),
                    'new_sl': trail_level,
                })
                logger.info(f"Trade {trade.get('id')}: Trailing stop updated to {trail_level:.2f}")

        return updates

    def record_closed_trade(self, trade_result):
        """
        Record a closed trade for learning and money management.

        Args:
            trade_result: dict with trade outcome details
        """
        # Record in money manager
        profit_pips = trade_result.get('profit_pips', 0)
        profit_amount = trade_result.get('profit_amount', 0)
        self.money_manager.record_trade_result(profit_pips, profit_amount)

        # Record in self-learning
        self.learner.record_trade(trade_result)

        # Remove from active trades
        trade_id = trade_result.get('id')
        self.active_trades = [t for t in self.active_trades if t.get('id') != trade_id]

        # Check if retraining needed
        total_trades = self.learner.learning_data['total_trades']
        if total_trades > 0 and total_trades % self.config['retrain_interval'] == 0:
            logger.info(f"Retrain trigger: {total_trades} trades completed")
            self._retrain()

    def _retrain(self):
        """Retrain/recalibrate the AI model based on accumulated data."""
        logger.info("Retraining AI model with accumulated data...")

        # Get performance report
        report = self.learner.get_performance_report()

        if 'summary' in report:
            winrate = report['summary'].get('winrate', 0)
            profit_factor = report['summary'].get('profit_factor', 0)
            expectancy = report['summary'].get('expectancy', 0)

            logger.info(f"Performance: WR={winrate:.1%} PF={profit_factor:.2f} Exp=${expectancy:.2f}")

            # Log strategy breakdown
            for strat, stats in report.get('strategy_breakdown', {}).items():
                logger.info(
                    f"  {strat}: {stats['trades']} trades, "
                    f"WR={stats['winrate']:.0%}, P/L=${stats['total_profit']:.2f}"
                )

        # Learning adapts parameters automatically via _adapt_parameters()
        logger.info("Retrain complete - parameters updated")

    # ===================== STATUS & REPORTING =====================
    def get_status(self):
        """Get current AI agent status."""
        risk_summary = self.money_manager.get_risk_summary()
        insights = self.learner.get_learning_insights()

        return {
            'connected': self.data_handler.connected,
            'active_trades': len(self.active_trades),
            'risk_management': risk_summary,
            'learning_insights': insights,
            'total_historical_trades': self.learner.learning_data['total_trades'],
            'overall_winrate': self.learner._get_overall_winrate(),
            'confidence_threshold': self.learner.learning_data['parameter_adjustments']['confidence_threshold'],
            'preferred_strategies': self.learner.learning_data['parameter_adjustments'].get('preferred_strategies', []),
            'timestamp': str(datetime.utcnow()),
        }

    def get_full_report(self):
        """Get comprehensive performance report."""
        return self.learner.get_performance_report()
