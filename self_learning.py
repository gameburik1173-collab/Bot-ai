"""
=============================================================================
SELF-LEARNING - Adaptive Trade Analysis & Parameter Optimization
=============================================================================
Features:
- Store trade history in JSON
- Analyze wins/losses by pattern, time, market condition
- Adjust confidence thresholds based on historical performance
- Adaptive strategy parameters
- Performance scoring per strategy/session/condition
=============================================================================
"""

import json
import os
import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict
import logging

from config import LEARNING_CONFIG, RISK_CONFIG, AI_CONFIG

logger = logging.getLogger(__name__)


class SelfLearning:
    """
    Self-learning component that tracks trade performance and adapts
    strategy parameters based on historical results.
    """

    def __init__(self):
        self.config = LEARNING_CONFIG
        self.history_file = self.config['history_file']
        self.learning_file = self.config['learning_file']
        self.trade_history = []
        self.learning_data = {}
        self._load_history()
        self._load_learning_data()

    # ===================== DATA PERSISTENCE =====================
    def _load_history(self):
        """Load trade history from JSON file."""
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r') as f:
                    self.trade_history = json.load(f)
                logger.info(f"Loaded {len(self.trade_history)} trades from history")
            else:
                self.trade_history = []
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error loading trade history: {e}")
            self.trade_history = []

    def _save_history(self):
        """Save trade history to JSON file."""
        try:
            with open(self.history_file, 'w') as f:
                json.dump(self.trade_history, f, indent=2, default=str)
        except IOError as e:
            logger.error(f"Error saving trade history: {e}")

    def _load_learning_data(self):
        """Load learning data (aggregated insights)."""
        try:
            if os.path.exists(self.learning_file):
                with open(self.learning_file, 'r') as f:
                    self.learning_data = json.load(f)
                logger.info("Loaded learning data")
            else:
                self.learning_data = self._initialize_learning_data()
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error loading learning data: {e}")
            self.learning_data = self._initialize_learning_data()

    def _save_learning_data(self):
        """Save learning data to JSON file."""
        try:
            with open(self.learning_file, 'w') as f:
                json.dump(self.learning_data, f, indent=2, default=str)
        except IOError as e:
            logger.error(f"Error saving learning data: {e}")

    def _initialize_learning_data(self):
        """Initialize empty learning data structure."""
        return {
            'strategy_performance': {
                'breakout_pullback': {'wins': 0, 'losses': 0, 'confidence_adj': 0.0},
                'qm_pattern': {'wins': 0, 'losses': 0, 'confidence_adj': 0.0},
                'rbr_dbd': {'wins': 0, 'losses': 0, 'confidence_adj': 0.0},
            },
            'session_performance': {
                'asian': {'wins': 0, 'losses': 0, 'avg_rr': 0.0},
                'london': {'wins': 0, 'losses': 0, 'avg_rr': 0.0},
                'overlap': {'wins': 0, 'losses': 0, 'avg_rr': 0.0},
                'newyork': {'wins': 0, 'losses': 0, 'avg_rr': 0.0},
            },
            'time_performance': {},  # Hour-based performance
            'market_condition_performance': {
                'trending': {'wins': 0, 'losses': 0},
                'ranging': {'wins': 0, 'losses': 0},
                'high_volatility': {'wins': 0, 'losses': 0},
                'low_volatility': {'wins': 0, 'losses': 0},
            },
            'direction_performance': {
                'buy': {'wins': 0, 'losses': 0},
                'sell': {'wins': 0, 'losses': 0},
            },
            'parameter_adjustments': {
                'confidence_threshold': AI_CONFIG['min_confidence'],
                'risk_percent': RISK_CONFIG['risk_percent'],
                'preferred_strategies': [],
                'avoid_sessions': [],
                'avoid_hours': [],
            },
            'total_trades': 0,
            'total_wins': 0,
            'total_losses': 0,
            'best_streak': 0,
            'worst_streak': 0,
            'last_updated': str(datetime.utcnow()),
        }


    # ===================== RECORD TRADES =====================
    def record_trade(self, trade_data):
        """
        Record a completed trade for learning.

        Args:
            trade_data: dict with keys:
                - strategy: str ('breakout_pullback', 'qm_pattern', 'rbr_dbd')
                - direction: str ('buy', 'sell')
                - entry_price: float
                - exit_price: float
                - stop_loss: float
                - take_profit: float
                - profit_pips: float
                - profit_amount: float
                - risk_reward_actual: float
                - session: str
                - market_condition: str
                - confidence: float (original signal confidence)
                - timeframe: str
                - open_time: str
                - close_time: str
                - pattern_details: dict
        """
        # Add metadata
        trade_data['id'] = len(self.trade_history) + 1
        trade_data['is_win'] = trade_data.get('profit_amount', 0) > 0
        trade_data['recorded_at'] = str(datetime.utcnow())

        # Extract hour
        try:
            open_time = datetime.fromisoformat(str(trade_data.get('open_time', '')))
            trade_data['hour'] = open_time.hour
        except (ValueError, TypeError):
            trade_data['hour'] = datetime.utcnow().hour

        # Add to history
        self.trade_history.append(trade_data)
        self._save_history()

        # Update learning data
        self._update_learning(trade_data)

        logger.info(
            f"Trade #{trade_data['id']} recorded: "
            f"{'WIN' if trade_data['is_win'] else 'LOSS'} | "
            f"{trade_data.get('strategy', 'unknown')} | "
            f"P/L: {trade_data.get('profit_amount', 0):.2f}"
        )

    def _update_learning(self, trade):
        """Update learning data with new trade result."""
        is_win = trade['is_win']
        strategy = trade.get('strategy', 'unknown')
        session = trade.get('session', 'unknown')
        market_condition = trade.get('market_condition', 'unknown')
        direction = trade.get('direction', 'unknown')
        hour = trade.get('hour', 0)

        # Update strategy performance
        if strategy in self.learning_data['strategy_performance']:
            sp = self.learning_data['strategy_performance'][strategy]
            if is_win:
                sp['wins'] += 1
                sp['confidence_adj'] += self.config['win_boost']
            else:
                sp['losses'] += 1
                sp['confidence_adj'] -= self.config['loss_penalty']
            # Apply decay
            sp['confidence_adj'] *= self.config['confidence_decay']

        # Update session performance
        if session in self.learning_data['session_performance']:
            sess = self.learning_data['session_performance'][session]
            if is_win:
                sess['wins'] += 1
            else:
                sess['losses'] += 1
            # Update average RR
            rr = trade.get('risk_reward_actual', 0)
            total = sess['wins'] + sess['losses']
            sess['avg_rr'] = ((sess['avg_rr'] * (total - 1)) + rr) / total if total > 0 else rr

        # Update time performance
        hour_key = str(hour)
        if hour_key not in self.learning_data['time_performance']:
            self.learning_data['time_performance'][hour_key] = {'wins': 0, 'losses': 0}
        if is_win:
            self.learning_data['time_performance'][hour_key]['wins'] += 1
        else:
            self.learning_data['time_performance'][hour_key]['losses'] += 1

        # Update market condition performance
        if market_condition in self.learning_data['market_condition_performance']:
            mc = self.learning_data['market_condition_performance'][market_condition]
            if is_win:
                mc['wins'] += 1
            else:
                mc['losses'] += 1

        # Update direction performance
        if direction in self.learning_data['direction_performance']:
            dp = self.learning_data['direction_performance'][direction]
            if is_win:
                dp['wins'] += 1
            else:
                dp['losses'] += 1

        # Update totals
        self.learning_data['total_trades'] += 1
        if is_win:
            self.learning_data['total_wins'] += 1
        else:
            self.learning_data['total_losses'] += 1

        self.learning_data['last_updated'] = str(datetime.utcnow())

        # Run adaptive parameter adjustment
        if self.learning_data['total_trades'] >= self.config['min_trades_for_learning']:
            self._adapt_parameters()

        self._save_learning_data()


    # ===================== ADAPTIVE PARAMETERS =====================
    def _adapt_parameters(self):
        """
        Adapt strategy parameters based on historical performance.
        Only adjusts after minimum trade count is reached.
        """
        if not self.config['adaptive_parameters']:
            return

        learning_rate = self.config['learning_rate']

        # 1. Adjust confidence threshold
        overall_winrate = self._get_overall_winrate()
        if overall_winrate < 0.45:
            # Losing too much - increase confidence threshold
            current = self.learning_data['parameter_adjustments']['confidence_threshold']
            new_threshold = min(0.85, current + (learning_rate * 0.1))
            self.learning_data['parameter_adjustments']['confidence_threshold'] = new_threshold
            logger.info(f"Confidence threshold increased to {new_threshold:.2f}")
        elif overall_winrate > 0.65:
            # Winning well - can slightly decrease threshold
            current = self.learning_data['parameter_adjustments']['confidence_threshold']
            new_threshold = max(0.5, current - (learning_rate * 0.05))
            self.learning_data['parameter_adjustments']['confidence_threshold'] = new_threshold

        # 2. Identify preferred strategies
        preferred = []
        for strategy, perf in self.learning_data['strategy_performance'].items():
            total = perf['wins'] + perf['losses']
            if total >= 5:  # Minimum sample size
                winrate = perf['wins'] / total
                if winrate > 0.55:
                    preferred.append(strategy)
        self.learning_data['parameter_adjustments']['preferred_strategies'] = preferred

        # 3. Identify sessions to avoid
        avoid_sessions = []
        for session, perf in self.learning_data['session_performance'].items():
            total = perf['wins'] + perf['losses']
            if total >= 5:
                winrate = perf['wins'] / total
                if winrate < 0.35:
                    avoid_sessions.append(session)
        self.learning_data['parameter_adjustments']['avoid_sessions'] = avoid_sessions

        # 4. Identify hours to avoid
        avoid_hours = []
        for hour, perf in self.learning_data['time_performance'].items():
            total = perf['wins'] + perf['losses']
            if total >= 3:
                winrate = perf['wins'] / total
                if winrate < 0.30:
                    avoid_hours.append(int(hour))
        self.learning_data['parameter_adjustments']['avoid_hours'] = avoid_hours

        logger.info(
            f"Parameters adapted: Preferred={preferred}, "
            f"Avoid sessions={avoid_sessions}, Avoid hours={avoid_hours}"
        )

    # ===================== CONFIDENCE ADJUSTMENT =====================
    def get_adjusted_confidence(self, signal):
        """
        Adjust signal confidence based on learning data.

        Args:
            signal: TradeSignal object

        Returns:
            float: Adjusted confidence (0-1)
        """
        base_confidence = signal.confidence
        adjustments = []

        # Strategy-based adjustment
        strategy = signal.strategy
        if strategy in self.learning_data['strategy_performance']:
            sp = self.learning_data['strategy_performance'][strategy]
            adj = sp.get('confidence_adj', 0.0)
            adjustments.append(('strategy', adj))

        # Session-based adjustment
        now = datetime.utcnow()
        hour = now.hour
        if 0 <= hour < 8:
            session = 'asian'
        elif 8 <= hour < 13:
            session = 'london'
        elif 13 <= hour < 16:
            session = 'overlap'
        else:
            session = 'newyork'

        if session in self.learning_data['session_performance']:
            sess = self.learning_data['session_performance'][session]
            total = sess['wins'] + sess['losses']
            if total >= 5:
                winrate = sess['wins'] / total
                session_adj = (winrate - 0.5) * 0.2  # Scale adjustment
                adjustments.append(('session', session_adj))

        # Time-based adjustment
        hour_key = str(hour)
        if hour_key in self.learning_data['time_performance']:
            tp = self.learning_data['time_performance'][hour_key]
            total = tp['wins'] + tp['losses']
            if total >= 3:
                winrate = tp['wins'] / total
                time_adj = (winrate - 0.5) * 0.15
                adjustments.append(('time', time_adj))

        # Direction-based adjustment
        direction = signal.direction
        if direction in self.learning_data['direction_performance']:
            dp = self.learning_data['direction_performance'][direction]
            total = dp['wins'] + dp['losses']
            if total >= 5:
                winrate = dp['wins'] / total
                dir_adj = (winrate - 0.5) * 0.1
                adjustments.append(('direction', dir_adj))

        # Apply adjustments
        total_adj = sum(adj for _, adj in adjustments)
        adjusted_confidence = base_confidence + total_adj

        # Clamp to valid range
        adjusted_confidence = max(0.1, min(1.0, adjusted_confidence))

        if abs(total_adj) > 0.01:
            logger.debug(
                f"Confidence adjusted: {base_confidence:.3f} -> {adjusted_confidence:.3f} "
                f"(adjustments: {adjustments})"
            )

        return adjusted_confidence

    def should_take_trade(self, signal):
        """
        Determine if a trade should be taken based on learning.

        Args:
            signal: TradeSignal object

        Returns:
            tuple: (should_trade: bool, reason: str, adjusted_confidence: float)
        """
        adjusted_confidence = self.get_adjusted_confidence(signal)
        threshold = self.learning_data['parameter_adjustments']['confidence_threshold']

        # Check if in avoided session
        now = datetime.utcnow()
        hour = now.hour
        avoid_hours = self.learning_data['parameter_adjustments'].get('avoid_hours', [])
        if hour in avoid_hours:
            return False, f"Hour {hour} historically poor performance", adjusted_confidence

        # Check avoided sessions
        if 0 <= hour < 8:
            session = 'asian'
        elif 8 <= hour < 13:
            session = 'london'
        elif 13 <= hour < 16:
            session = 'overlap'
        else:
            session = 'newyork'

        avoid_sessions = self.learning_data['parameter_adjustments'].get('avoid_sessions', [])
        if session in avoid_sessions:
            return False, f"Session '{session}' historically poor", adjusted_confidence

        # Check confidence threshold
        if adjusted_confidence < threshold:
            return (
                False,
                f"Confidence {adjusted_confidence:.2f} below threshold {threshold:.2f}",
                adjusted_confidence
            )

        return True, "Trade approved by learning system", adjusted_confidence


    # ===================== ANALYTICS =====================
    def _get_overall_winrate(self):
        """Get overall win rate."""
        total = self.learning_data['total_trades']
        if total == 0:
            return 0.5
        return self.learning_data['total_wins'] / total

    def get_strategy_winrate(self, strategy):
        """Get win rate for a specific strategy."""
        if strategy in self.learning_data['strategy_performance']:
            sp = self.learning_data['strategy_performance'][strategy]
            total = sp['wins'] + sp['losses']
            if total == 0:
                return 0.5
            return sp['wins'] / total
        return 0.5

    def get_session_winrate(self, session):
        """Get win rate for a specific session."""
        if session in self.learning_data['session_performance']:
            sess = self.learning_data['session_performance'][session]
            total = sess['wins'] + sess['losses']
            if total == 0:
                return 0.5
            return sess['wins'] / total
        return 0.5

    def get_performance_report(self):
        """
        Generate comprehensive performance report.

        Returns:
            dict with detailed performance metrics
        """
        if not self.trade_history:
            return {'message': 'No trade history available'}

        total_trades = len(self.trade_history)
        wins = sum(1 for t in self.trade_history if t.get('is_win', False))
        losses = total_trades - wins

        # Profit metrics
        profits = [t.get('profit_amount', 0) for t in self.trade_history]
        total_profit = sum(profits)
        avg_profit = np.mean(profits) if profits else 0

        winning_profits = [p for p in profits if p > 0]
        losing_profits = [p for p in profits if p < 0]

        avg_win = np.mean(winning_profits) if winning_profits else 0
        avg_loss = np.mean(losing_profits) if losing_profits else 0

        # Profit factor
        gross_profit = sum(winning_profits)
        gross_loss = abs(sum(losing_profits))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

        # Expectancy
        winrate = wins / total_trades if total_trades > 0 else 0
        expectancy = (winrate * avg_win) + ((1 - winrate) * avg_loss)

        # Strategy breakdown
        strategy_stats = {}
        for strategy in ['breakout_pullback', 'qm_pattern', 'rbr_dbd']:
            strat_trades = [t for t in self.trade_history if t.get('strategy') == strategy]
            if strat_trades:
                s_wins = sum(1 for t in strat_trades if t.get('is_win'))
                s_total = len(strat_trades)
                s_profits = [t.get('profit_amount', 0) for t in strat_trades]
                strategy_stats[strategy] = {
                    'trades': s_total,
                    'wins': s_wins,
                    'losses': s_total - s_wins,
                    'winrate': s_wins / s_total if s_total > 0 else 0,
                    'total_profit': sum(s_profits),
                    'avg_profit': np.mean(s_profits) if s_profits else 0,
                }

        # Session breakdown
        session_stats = {}
        for session in ['asian', 'london', 'overlap', 'newyork']:
            sess_trades = [t for t in self.trade_history if t.get('session') == session]
            if sess_trades:
                s_wins = sum(1 for t in sess_trades if t.get('is_win'))
                s_total = len(sess_trades)
                session_stats[session] = {
                    'trades': s_total,
                    'winrate': s_wins / s_total if s_total > 0 else 0,
                    'total_profit': sum(t.get('profit_amount', 0) for t in sess_trades),
                }

        # Best/worst hours
        hour_stats = {}
        for hour_key, perf in self.learning_data['time_performance'].items():
            total = perf['wins'] + perf['losses']
            if total >= 2:
                hour_stats[hour_key] = {
                    'trades': total,
                    'winrate': perf['wins'] / total,
                }

        # Streaks
        current_streak = 0
        max_win_streak = 0
        max_loss_streak = 0
        temp_streak = 0

        for trade in self.trade_history:
            if trade.get('is_win'):
                if temp_streak > 0:
                    temp_streak += 1
                else:
                    temp_streak = 1
                max_win_streak = max(max_win_streak, temp_streak)
            else:
                if temp_streak < 0:
                    temp_streak -= 1
                else:
                    temp_streak = -1
                max_loss_streak = max(max_loss_streak, abs(temp_streak))

        report = {
            'summary': {
                'total_trades': total_trades,
                'wins': wins,
                'losses': losses,
                'winrate': winrate,
                'total_profit': total_profit,
                'avg_profit_per_trade': avg_profit,
                'avg_win': avg_win,
                'avg_loss': avg_loss,
                'profit_factor': profit_factor,
                'expectancy': expectancy,
                'max_win_streak': max_win_streak,
                'max_loss_streak': max_loss_streak,
            },
            'strategy_breakdown': strategy_stats,
            'session_breakdown': session_stats,
            'hour_stats': hour_stats,
            'current_adjustments': self.learning_data['parameter_adjustments'],
        }

        return report

    def get_learning_insights(self):
        """
        Get actionable insights from learning data.

        Returns:
            list of insight strings
        """
        insights = []
        total = self.learning_data['total_trades']

        if total < self.config['min_trades_for_learning']:
            insights.append(
                f"Need {self.config['min_trades_for_learning'] - total} more trades "
                f"before learning can provide reliable insights."
            )
            return insights

        # Overall performance
        winrate = self._get_overall_winrate()
        if winrate > 0.6:
            insights.append(f"Strong overall performance: {winrate:.0%} win rate")
        elif winrate < 0.4:
            insights.append(f"Poor overall performance: {winrate:.0%} win rate - consider reducing position sizes")

        # Best strategy
        best_strat = None
        best_wr = 0
        for strat, perf in self.learning_data['strategy_performance'].items():
            total_s = perf['wins'] + perf['losses']
            if total_s >= 5:
                wr = perf['wins'] / total_s
                if wr > best_wr:
                    best_wr = wr
                    best_strat = strat

        if best_strat:
            insights.append(f"Best strategy: {best_strat} ({best_wr:.0%} win rate)")

        # Worst strategy
        worst_strat = None
        worst_wr = 1.0
        for strat, perf in self.learning_data['strategy_performance'].items():
            total_s = perf['wins'] + perf['losses']
            if total_s >= 5:
                wr = perf['wins'] / total_s
                if wr < worst_wr:
                    worst_wr = wr
                    worst_strat = strat

        if worst_strat and worst_wr < 0.4:
            insights.append(f"Weakest strategy: {worst_strat} ({worst_wr:.0%}) - consider disabling")

        # Best session
        best_sess = None
        best_sess_wr = 0
        for sess, perf in self.learning_data['session_performance'].items():
            total_s = perf['wins'] + perf['losses']
            if total_s >= 5:
                wr = perf['wins'] / total_s
                if wr > best_sess_wr:
                    best_sess_wr = wr
                    best_sess = sess

        if best_sess:
            insights.append(f"Best session: {best_sess} ({best_sess_wr:.0%} win rate)")

        # Avoided elements
        avoid_sess = self.learning_data['parameter_adjustments'].get('avoid_sessions', [])
        if avoid_sess:
            insights.append(f"Avoiding sessions: {', '.join(avoid_sess)} (poor performance)")

        avoid_hrs = self.learning_data['parameter_adjustments'].get('avoid_hours', [])
        if avoid_hrs:
            insights.append(f"Avoiding hours (UTC): {avoid_hrs}")

        return insights

    # ===================== FEATURE EXTRACTION FOR AI =====================
    def get_features_for_signal(self, signal, market_condition):
        """
        Extract features from signal and market condition for AI model.

        Args:
            signal: TradeSignal object
            market_condition: dict from DataHandler.get_market_condition()

        Returns:
            dict of features for AI model
        """
        features = {
            # Signal features
            'strategy_encoded': self._encode_strategy(signal.strategy),
            'direction_encoded': 1 if signal.direction == 'buy' else 0,
            'confidence': signal.confidence,
            'risk_reward': signal.risk_reward,
            'confluence_score': signal.confluence_score,

            # Market features
            'market_type_encoded': self._encode_market_type(
                market_condition.get('market_type', 'unknown')
            ),
            'volatility_encoded': self._encode_volatility(
                market_condition.get('volatility_level', 'normal')
            ),
            'trend_strength': market_condition.get('trend_strength', 0.5),
            'session_encoded': self._encode_session(
                market_condition.get('session', 'unknown')
            ),
            'hour': market_condition.get('hour_utc', 12),

            # Historical features
            'strategy_winrate': self.get_strategy_winrate(signal.strategy),
            'overall_winrate': self._get_overall_winrate(),
            'session_winrate': self.get_session_winrate(
                market_condition.get('session', 'unknown')
            ),
        }

        return features

    def _encode_strategy(self, strategy):
        """Encode strategy to numeric."""
        mapping = {'breakout_pullback': 0, 'qm_pattern': 1, 'rbr_dbd': 2}
        return mapping.get(strategy, -1)

    def _encode_market_type(self, market_type):
        """Encode market type to numeric."""
        mapping = {'trending': 2, 'weak_trend': 1, 'ranging': 0}
        return mapping.get(market_type, 1)

    def _encode_volatility(self, vol_level):
        """Encode volatility to numeric."""
        mapping = {'high': 2, 'normal': 1, 'low': 0}
        return mapping.get(vol_level, 1)

    def _encode_session(self, session):
        """Encode session to numeric."""
        mapping = {'asian': 0, 'london': 1, 'overlap': 2, 'newyork': 3, 'off_hours': 4}
        return mapping.get(session, 4)

    # ===================== RESET =====================
    def reset_learning(self):
        """Reset all learning data (keep history)."""
        self.learning_data = self._initialize_learning_data()
        self._save_learning_data()
        logger.info("Learning data reset")

    def reset_all(self):
        """Reset everything including history."""
        self.trade_history = []
        self.learning_data = self._initialize_learning_data()
        self._save_history()
        self._save_learning_data()
        logger.info("All data reset (history + learning)")
