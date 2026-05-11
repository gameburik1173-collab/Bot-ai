"""
=============================================================================
STRATEGI - Advanced Trading Strategies
=============================================================================
1. Breakout + Pullback Strategy
2. QM (Quasimodo) Pattern Strategy
3. Multi-Timeframe Confluence
4. RBR/DBD Micro Pattern (M1/M3)
=============================================================================
"""

import numpy as np
import pandas as pd
from datetime import datetime
import logging

from config import (
    BREAKOUT_CONFIG, QM_CONFIG, MTF_CONFIG,
    MICRO_PATTERN_CONFIG, RISK_CONFIG, SR_CONFIG
)

logger = logging.getLogger(__name__)


# ===================== SIGNAL CLASS =====================
class TradeSignal:
    """Represents a trade signal with all relevant information."""

    def __init__(self):
        self.direction = None       # 'buy' or 'sell'
        self.strategy = None        # 'breakout_pullback', 'qm_pattern', 'rbr_dbd'
        self.entry_price = 0.0
        self.stop_loss = 0.0
        self.take_profit = 0.0
        self.confidence = 0.0       # 0.0 - 1.0
        self.risk_reward = 0.0
        self.timeframe = None
        self.pattern_details = {}
        self.confluence_score = 0.0
        self.timestamp = datetime.utcnow()
        self.valid = False

    def to_dict(self):
        return {
            'direction': self.direction,
            'strategy': self.strategy,
            'entry_price': self.entry_price,
            'stop_loss': self.stop_loss,
            'take_profit': self.take_profit,
            'confidence': self.confidence,
            'risk_reward': self.risk_reward,
            'timeframe': self.timeframe,
            'pattern_details': self.pattern_details,
            'confluence_score': self.confluence_score,
            'timestamp': str(self.timestamp),
            'valid': self.valid,
        }

    def __repr__(self):
        return (
            f"Signal({self.direction} | {self.strategy} | "
            f"Entry:{self.entry_price:.2f} SL:{self.stop_loss:.2f} "
            f"TP:{self.take_profit:.2f} | RR:{self.risk_reward:.1f} | "
            f"Conf:{self.confidence:.2f})"
        )


# ===================== BREAKOUT + PULLBACK STRATEGY =====================
class BreakoutPullbackStrategy:
    """
    Breakout + Pullback Strategy:
    1. Identify strong SR levels
    2. Detect breakout (close above/below SR with strong body)
    3. Wait for pullback to broken SR level
    4. Enter on confirmation candle after pullback
    5. SL below/above weak SR, TP at next SR level
    """

    def __init__(self, data_handler):
        self.data = data_handler
        self.config = BREAKOUT_CONFIG
        self.name = "breakout_pullback"

    def analyze(self, timeframe="M5"):
        """
        Analyze for Breakout + Pullback setup.

        Returns:
            TradeSignal or None
        """
        df = self.data.get_data(timeframe)
        if df is None or len(df) < self.config['lookback_period'] + 10:
            return None

        sr_levels = self.data.sr_levels
        if not sr_levels:
            sr_levels = self.data.calculate_sr_levels(timeframe)

        if not sr_levels:
            logger.debug("No SR levels found for breakout analysis")
            return None

        pip_value = self.data._get_pip_value()
        current_price = df['close'].iloc[-1]

        # Check for recent breakout
        signal = self._detect_breakout_pullback(df, sr_levels, pip_value, current_price)

        if signal and signal.valid:
            # Add confluence score
            signal.confluence_score = self._calculate_confluence(
                signal, df, timeframe
            )
            signal.confidence = signal.confluence_score
            logger.info(f"Breakout+Pullback signal: {signal}")

        return signal if signal and signal.valid else None

    def _detect_breakout_pullback(self, df, sr_levels, pip_value, current_price):
        """
        Detect breakout followed by pullback pattern.
        """
        lookback = self.config['lookback_period']
        breakout_threshold = self.config['breakout_threshold_pips'] * pip_value
        pullback_zone = self.config['pullback_zone_pips'] * pip_value
        max_pullback_candles = self.config['pullback_max_candles']

        signal = TradeSignal()
        signal.strategy = self.name

        for sr in sr_levels[:10]:  # Check top 10 strongest levels
            sr_price = sr['price']
            sr_type = sr['type']

            # --- BULLISH BREAKOUT (Break resistance, pullback to it as support) ---
            if sr_type == 'resistance':
                breakout_signal = self._check_bullish_breakout(
                    df, sr_price, pip_value, breakout_threshold,
                    pullback_zone, max_pullback_candles, current_price
                )
                if breakout_signal:
                    return breakout_signal

            # --- BEARISH BREAKOUT (Break support, pullback to it as resistance) ---
            elif sr_type == 'support':
                breakout_signal = self._check_bearish_breakout(
                    df, sr_price, pip_value, breakout_threshold,
                    pullback_zone, max_pullback_candles, current_price
                )
                if breakout_signal:
                    return breakout_signal

        return None

    def _check_bullish_breakout(self, df, sr_price, pip_value,
                                 breakout_threshold, pullback_zone,
                                 max_pullback_candles, current_price):
        """Check for bullish breakout + pullback setup."""
        signal = TradeSignal()
        signal.strategy = self.name
        signal.direction = 'buy'

        # Look for breakout candle in recent history
        for i in range(-max_pullback_candles - 5, -max_pullback_candles):
            if i >= len(df) or abs(i) > len(df):
                continue

            candle = df.iloc[i]

            # Check if this candle broke resistance
            broke_above = (
                candle['close'] > sr_price + breakout_threshold and
                candle['open'] < sr_price and
                candle['body_ratio'] > self.config['body_ratio_min'] and
                candle['is_bullish']
            )

            if broke_above:
                # Now check if price pulled back to the broken level
                pullback_found = False
                confirmation = False

                for j in range(i + 1, min(i + max_pullback_candles + 1, -1)):
                    if abs(j) > len(df):
                        continue

                    pb_candle = df.iloc[j]

                    # Price came back near the broken resistance (now support)
                    if (pb_candle['low'] <= sr_price + pullback_zone and
                            pb_candle['low'] >= sr_price - pullback_zone * 0.5):
                        pullback_found = True

                    # After pullback, check confirmation (bullish candle)
                    if pullback_found and j > i + 1:
                        if (pb_candle['is_bullish'] and
                                pb_candle['body_ratio'] > 0.5 and
                                pb_candle['close'] > sr_price):
                            confirmation = True
                            break

                if pullback_found and confirmation:
                    # Valid setup - check if current price is still in entry zone
                    if (current_price >= sr_price and
                            current_price <= sr_price + pullback_zone * 2):

                        signal.entry_price = current_price
                        signal.stop_loss = sr_price - (RISK_CONFIG['sl_min_pips'] * pip_value)
                        signal.timeframe = "M5"

                        # Calculate TP based on RR
                        sl_distance = signal.entry_price - signal.stop_loss
                        signal.take_profit = signal.entry_price + (sl_distance * RISK_CONFIG['rr_minimum'])
                        signal.risk_reward = RISK_CONFIG['rr_minimum']

                        signal.pattern_details = {
                            'sr_level': sr_price,
                            'breakout_candle_index': i,
                            'pullback_found': True,
                            'pattern': 'bullish_breakout_pullback'
                        }
                        signal.valid = True
                        return signal

        return None

    def _check_bearish_breakout(self, df, sr_price, pip_value,
                                 breakout_threshold, pullback_zone,
                                 max_pullback_candles, current_price):
        """Check for bearish breakout + pullback setup."""
        signal = TradeSignal()
        signal.strategy = self.name
        signal.direction = 'sell'

        for i in range(-max_pullback_candles - 5, -max_pullback_candles):
            if i >= len(df) or abs(i) > len(df):
                continue

            candle = df.iloc[i]

            # Check if this candle broke support
            broke_below = (
                candle['close'] < sr_price - breakout_threshold and
                candle['open'] > sr_price and
                candle['body_ratio'] > self.config['body_ratio_min'] and
                not candle['is_bullish']
            )

            if broke_below:
                pullback_found = False
                confirmation = False

                for j in range(i + 1, min(i + max_pullback_candles + 1, -1)):
                    if abs(j) > len(df):
                        continue

                    pb_candle = df.iloc[j]

                    # Price came back near the broken support (now resistance)
                    if (pb_candle['high'] >= sr_price - pullback_zone and
                            pb_candle['high'] <= sr_price + pullback_zone * 0.5):
                        pullback_found = True

                    # After pullback, check confirmation (bearish candle)
                    if pullback_found and j > i + 1:
                        if (not pb_candle['is_bullish'] and
                                pb_candle['body_ratio'] > 0.5 and
                                pb_candle['close'] < sr_price):
                            confirmation = True
                            break

                if pullback_found and confirmation:
                    if (current_price <= sr_price and
                            current_price >= sr_price - pullback_zone * 2):

                        signal.entry_price = current_price
                        signal.stop_loss = sr_price + (RISK_CONFIG['sl_min_pips'] * pip_value)
                        signal.timeframe = "M5"

                        sl_distance = signal.stop_loss - signal.entry_price
                        signal.take_profit = signal.entry_price - (sl_distance * RISK_CONFIG['rr_minimum'])
                        signal.risk_reward = RISK_CONFIG['rr_minimum']

                        signal.pattern_details = {
                            'sr_level': sr_price,
                            'breakout_candle_index': i,
                            'pullback_found': True,
                            'pattern': 'bearish_breakout_pullback'
                        }
                        signal.valid = True
                        return signal

        return None

    def _calculate_confluence(self, signal, df, timeframe):
        """Calculate confluence score for the signal (0-1)."""
        score = 0.0
        factors = 0

        # Factor 1: Volume confirmation
        if 'vol_ratio' in df.columns:
            recent_vol = df['vol_ratio'].iloc[-3:].mean()
            if recent_vol > self.config['volume_multiplier']:
                score += 1.0
            elif recent_vol > 1.0:
                score += 0.5
            factors += 1

        # Factor 2: Trend alignment (from M15)
        trend = self.data.get_trend_direction("M15")
        if trend:
            if signal.direction == 'buy' and trend['direction'] == 'bullish':
                score += 1.0
            elif signal.direction == 'sell' and trend['direction'] == 'bearish':
                score += 1.0
            elif trend['direction'] == 'neutral':
                score += 0.3
            factors += 1

        # Factor 3: EMA alignment
        if 'ema_fast' in df.columns and 'ema_slow' in df.columns:
            ema_f = df['ema_fast'].iloc[-1]
            ema_s = df['ema_slow'].iloc[-1]
            if signal.direction == 'buy' and ema_f > ema_s:
                score += 1.0
            elif signal.direction == 'sell' and ema_f < ema_s:
                score += 1.0
            factors += 1

        # Factor 4: RSI not overbought/oversold
        if 'rsi' in df.columns:
            rsi = df['rsi'].iloc[-1]
            if signal.direction == 'buy' and 30 < rsi < 70:
                score += 0.7
            elif signal.direction == 'sell' and 30 < rsi < 70:
                score += 0.7
            elif signal.direction == 'buy' and rsi < 30:
                score += 1.0  # Oversold for buy
            elif signal.direction == 'sell' and rsi > 70:
                score += 1.0  # Overbought for sell
            factors += 1

        # Factor 5: Body ratio of recent candles
        recent_body_ratio = df['body_ratio'].iloc[-3:].mean()
        if recent_body_ratio > 0.6:
            score += 0.8
        factors += 1

        return score / factors if factors > 0 else 0.5



# ===================== QM (QUASIMODO) PATTERN STRATEGY =====================
class QMPatternStrategy:
    """
    QM (Quasimodo) Pattern Strategy:

    Bullish QM:
    - Higher High (left shoulder)
    - Lower Low (head) - makes new low below previous swing low
    - Higher Low (right shoulder) - fails to make new low
    - Entry at neckline or right shoulder level
    - Pattern: HH -> LL -> HL

    Bearish QM:
    - Lower Low (left shoulder)
    - Higher High (head) - makes new high above previous swing high
    - Lower High (right shoulder) - fails to make new high
    - Entry at neckline or right shoulder level
    - Pattern: LL -> HH -> LH
    """

    def __init__(self, data_handler):
        self.data = data_handler
        self.config = QM_CONFIG
        self.name = "qm_pattern"

    def analyze(self, timeframe="M5"):
        """
        Analyze for QM pattern setup.

        Returns:
            TradeSignal or None
        """
        df = self.data.get_data(timeframe)
        if df is None or len(df) < self.config['swing_lookback'] + 10:
            return None

        # Get swing points
        swings = self.data.find_swing_points(timeframe)
        if len(swings) < 4:
            return None

        pip_value = self.data._get_pip_value()
        current_price = df['close'].iloc[-1]

        # Check for bullish QM
        bullish_signal = self._detect_bullish_qm(swings, pip_value, current_price, df)
        if bullish_signal and bullish_signal.valid:
            bullish_signal.confluence_score = self._calculate_qm_confluence(
                bullish_signal, df, timeframe
            )
            bullish_signal.confidence = bullish_signal.confluence_score
            logger.info(f"QM Bullish signal: {bullish_signal}")
            return bullish_signal

        # Check for bearish QM
        bearish_signal = self._detect_bearish_qm(swings, pip_value, current_price, df)
        if bearish_signal and bearish_signal.valid:
            bearish_signal.confluence_score = self._calculate_qm_confluence(
                bearish_signal, df, timeframe
            )
            bearish_signal.confidence = bearish_signal.confluence_score
            logger.info(f"QM Bearish signal: {bearish_signal}")
            return bearish_signal

        return None

    def _detect_bullish_qm(self, swings, pip_value, current_price, df):
        """
        Detect Bullish QM pattern.

        Pattern sequence:
        1. Swing High (left shoulder)
        2. Swing Low
        3. Higher High OR equal high
        4. Lower Low (head - makes new low)
        5. Price reverses up -> entry zone

        Simplified: Look for sequence where price makes lower low
        then fails to continue lower (higher low forms)
        """
        signal = TradeSignal()
        signal.strategy = self.name
        signal.direction = 'buy'

        min_height = self.config['min_pattern_height_pips'] * pip_value
        entry_zone = self.config['entry_zone_pips'] * pip_value

        # Get recent swing points (last 8-10)
        recent_swings = swings[-10:]
        swing_lows = [s for s in recent_swings if s['type'] == 'low']
        swing_highs = [s for s in recent_swings if s['type'] == 'high']

        if len(swing_lows) < 3 or len(swing_highs) < 2:
            return None

        # Pattern: We need at least 2 swing lows where:
        # - Second-to-last low is the LOWEST (head)
        # - Last low is HIGHER than the head (right shoulder / higher low)
        # This shows failed continuation to downside

        for i in range(len(swing_lows) - 2, 0, -1):
            if i + 1 >= len(swing_lows):
                continue

            prev_low = swing_lows[i - 1] if i > 0 else None
            head_low = swing_lows[i]       # The lowest point (head)
            right_low = swing_lows[i + 1]  # Higher low (right shoulder)

            if prev_low is None:
                continue

            # Conditions for Bullish QM:
            # 1. Head makes lower low than previous
            # 2. Right shoulder makes higher low than head
            # 3. Pattern height is sufficient
            is_head_lower = head_low['price'] < prev_low['price']
            is_right_higher = right_low['price'] > head_low['price']
            pattern_height = abs(prev_low['price'] - head_low['price'])

            if is_head_lower and is_right_higher and pattern_height >= min_height:
                # Find the neckline (high between head and right shoulder)
                neckline_highs = [
                    h for h in swing_highs
                    if head_low['index'] < h['index'] < right_low['index']
                ]

                if neckline_highs:
                    neckline = max(neckline_highs, key=lambda x: x['price'])['price']
                else:
                    # Use the high between the two lows
                    head_idx = head_low['index']
                    right_idx = right_low['index']
                    if head_idx < len(df) and right_idx < len(df):
                        neckline = df['high'].iloc[head_idx:right_idx].max()
                    else:
                        continue

                # Entry zone: near the right shoulder low or neckline break
                entry_level = right_low['price'] + entry_zone

                # Check if current price is in entry zone
                if (current_price >= right_low['price'] and
                        current_price <= entry_level + entry_zone):

                    signal.entry_price = current_price
                    signal.stop_loss = head_low['price'] - (5 * pip_value)

                    # Ensure SL is within limits
                    sl_pips = (signal.entry_price - signal.stop_loss) / pip_value
                    if sl_pips < RISK_CONFIG['sl_min_pips']:
                        signal.stop_loss = signal.entry_price - (RISK_CONFIG['sl_min_pips'] * pip_value)
                    elif sl_pips > RISK_CONFIG['sl_max_pips']:
                        signal.stop_loss = signal.entry_price - (RISK_CONFIG['sl_max_pips'] * pip_value)

                    # TP at neckline or beyond
                    sl_distance = signal.entry_price - signal.stop_loss
                    signal.take_profit = signal.entry_price + (sl_distance * RISK_CONFIG['rr_minimum'])

                    # If neckline is a better target
                    if neckline > signal.take_profit:
                        signal.take_profit = neckline
                        signal.risk_reward = (signal.take_profit - signal.entry_price) / sl_distance
                    else:
                        signal.risk_reward = RISK_CONFIG['rr_minimum']

                    signal.timeframe = "M5"
                    signal.pattern_details = {
                        'pattern': 'bullish_qm',
                        'head_price': head_low['price'],
                        'right_shoulder': right_low['price'],
                        'neckline': neckline,
                        'pattern_height_pips': pattern_height / pip_value,
                        'prev_low': prev_low['price'],
                    }
                    signal.valid = True
                    return signal

        return None

    def _detect_bearish_qm(self, swings, pip_value, current_price, df):
        """
        Detect Bearish QM pattern.

        Pattern: Price makes higher high then fails to continue higher
        (lower high forms) -> reversal signal
        """
        signal = TradeSignal()
        signal.strategy = self.name
        signal.direction = 'sell'

        min_height = self.config['min_pattern_height_pips'] * pip_value
        entry_zone = self.config['entry_zone_pips'] * pip_value

        recent_swings = swings[-10:]
        swing_lows = [s for s in recent_swings if s['type'] == 'low']
        swing_highs = [s for s in recent_swings if s['type'] == 'high']

        if len(swing_highs) < 3 or len(swing_lows) < 2:
            return None

        for i in range(len(swing_highs) - 2, 0, -1):
            if i + 1 >= len(swing_highs):
                continue

            prev_high = swing_highs[i - 1] if i > 0 else None
            head_high = swing_highs[i]       # The highest point (head)
            right_high = swing_highs[i + 1]  # Lower high (right shoulder)

            if prev_high is None:
                continue

            # Conditions for Bearish QM:
            # 1. Head makes higher high than previous
            # 2. Right shoulder makes lower high than head
            # 3. Pattern height is sufficient
            is_head_higher = head_high['price'] > prev_high['price']
            is_right_lower = right_high['price'] < head_high['price']
            pattern_height = abs(head_high['price'] - prev_high['price'])

            if is_head_higher and is_right_lower and pattern_height >= min_height:
                # Find the neckline (low between head and right shoulder)
                neckline_lows = [
                    l for l in swing_lows
                    if head_high['index'] < l['index'] < right_high['index']
                ]

                if neckline_lows:
                    neckline = min(neckline_lows, key=lambda x: x['price'])['price']
                else:
                    head_idx = head_high['index']
                    right_idx = right_high['index']
                    if head_idx < len(df) and right_idx < len(df):
                        neckline = df['low'].iloc[head_idx:right_idx].min()
                    else:
                        continue

                # Entry zone: near the right shoulder high
                entry_level = right_high['price'] - entry_zone

                if (current_price <= right_high['price'] and
                        current_price >= entry_level - entry_zone):

                    signal.entry_price = current_price
                    signal.stop_loss = head_high['price'] + (5 * pip_value)

                    # Ensure SL is within limits
                    sl_pips = (signal.stop_loss - signal.entry_price) / pip_value
                    if sl_pips < RISK_CONFIG['sl_min_pips']:
                        signal.stop_loss = signal.entry_price + (RISK_CONFIG['sl_min_pips'] * pip_value)
                    elif sl_pips > RISK_CONFIG['sl_max_pips']:
                        signal.stop_loss = signal.entry_price + (RISK_CONFIG['sl_max_pips'] * pip_value)

                    # TP
                    sl_distance = signal.stop_loss - signal.entry_price
                    signal.take_profit = signal.entry_price - (sl_distance * RISK_CONFIG['rr_minimum'])

                    if neckline < signal.take_profit:
                        signal.take_profit = neckline
                        signal.risk_reward = (signal.entry_price - signal.take_profit) / sl_distance
                    else:
                        signal.risk_reward = RISK_CONFIG['rr_minimum']

                    signal.timeframe = "M5"
                    signal.pattern_details = {
                        'pattern': 'bearish_qm',
                        'head_price': head_high['price'],
                        'right_shoulder': right_high['price'],
                        'neckline': neckline,
                        'pattern_height_pips': pattern_height / pip_value,
                        'prev_high': prev_high['price'],
                    }
                    signal.valid = True
                    return signal

        return None

    def _calculate_qm_confluence(self, signal, df, timeframe):
        """Calculate confluence score for QM pattern."""
        score = 0.0
        factors = 0

        # Factor 1: Pattern height (bigger = stronger)
        height_pips = signal.pattern_details.get('pattern_height_pips', 0)
        if height_pips > 50:
            score += 1.0
        elif height_pips > 30:
            score += 0.7
        else:
            score += 0.4
        factors += 1

        # Factor 2: Trend alignment
        trend = self.data.get_trend_direction("M15")
        if trend:
            if signal.direction == 'buy' and trend['direction'] == 'bullish':
                score += 1.0
            elif signal.direction == 'sell' and trend['direction'] == 'bearish':
                score += 1.0
            elif trend['direction'] == 'neutral':
                score += 0.5
            else:
                score += 0.2  # Counter-trend QM (still valid but less confident)
            factors += 1

        # Factor 3: Volume at pattern points
        if 'vol_ratio' in df.columns:
            recent_vol = df['vol_ratio'].iloc[-5:].mean()
            if recent_vol > 1.3:
                score += 1.0
            elif recent_vol > 1.0:
                score += 0.6
            else:
                score += 0.3
            factors += 1

        # Factor 4: RSI divergence check
        if 'rsi' in df.columns:
            rsi = df['rsi'].iloc[-1]
            if signal.direction == 'buy' and rsi < 40:
                score += 0.8  # RSI showing oversold for bullish QM
            elif signal.direction == 'sell' and rsi > 60:
                score += 0.8  # RSI showing overbought for bearish QM
            else:
                score += 0.4
            factors += 1

        # Factor 5: SR level proximity
        sr_levels = self.data.sr_levels
        if sr_levels:
            current = signal.entry_price
            nearest_sr = min(sr_levels, key=lambda x: abs(x['price'] - current))
            distance_pips = abs(nearest_sr['price'] - current) / self.data._get_pip_value()
            if distance_pips < 20:
                score += 0.9  # Near strong SR level
            elif distance_pips < 40:
                score += 0.5
            factors += 1

        return score / factors if factors > 0 else 0.5



# ===================== RBR/DBD MICRO PATTERN (M1/M3) =====================
class MicroPatternStrategy:
    """
    RBR (Rally-Base-Rally) and DBD (Drop-Base-Drop) patterns on M1/M3.
    Used for fine-tuning entries after higher timeframe signals.

    RBR: Strong bullish move -> consolidation (base) -> continuation up
    DBD: Strong bearish move -> consolidation (base) -> continuation down
    """

    def __init__(self, data_handler):
        self.data = data_handler
        self.config = MICRO_PATTERN_CONFIG
        self.name = "rbr_dbd"

    def analyze(self, timeframe="M1", bias=None):
        """
        Analyze for RBR/DBD micro patterns.

        Args:
            timeframe: M1 or M3
            bias: 'buy' or 'sell' - only look for patterns matching bias

        Returns:
            TradeSignal or None
        """
        df = self.data.get_data(timeframe)
        if df is None or len(df) < self.config['pattern_lookback'] + 10:
            return None

        pip_value = self.data._get_pip_value()
        current_price = df['close'].iloc[-1]

        if bias is None or bias == 'buy':
            rbr_signal = self._detect_rbr(df, pip_value, current_price)
            if rbr_signal and rbr_signal.valid:
                return rbr_signal

        if bias is None or bias == 'sell':
            dbd_signal = self._detect_dbd(df, pip_value, current_price)
            if dbd_signal and dbd_signal.valid:
                return dbd_signal

        return None

    def _detect_rbr(self, df, pip_value, current_price):
        """
        Detect Rally-Base-Rally pattern.

        1. Rally: Strong bullish move (multiple bullish candles)
        2. Base: Small range consolidation (2-5 candles)
        3. Rally: Continuation bullish move
        """
        signal = TradeSignal()
        signal.strategy = self.name
        signal.direction = 'buy'

        lookback = self.config['pattern_lookback']
        base_max = self.config['base_max_candles']
        base_range = self.config['base_max_range_pips'] * pip_value
        rally_min = self.config['rally_min_pips'] * pip_value

        # Look for pattern in recent candles
        for start in range(len(df) - lookback, len(df) - base_max - 4):
            if start < 0:
                continue

            # Phase 1: First Rally (at least 3 bullish candles)
            rally1_end = None
            rally1_start_price = df['low'].iloc[start]
            for r in range(start, min(start + 8, len(df))):
                if df['close'].iloc[r] - rally1_start_price >= rally_min:
                    rally1_end = r
                    break

            if rally1_end is None:
                continue

            # Phase 2: Base (consolidation)
            base_start = rally1_end + 1
            base_end = None

            for b in range(base_start, min(base_start + base_max + 1, len(df))):
                segment = df.iloc[base_start:b + 1]
                if len(segment) < 2:
                    continue

                seg_range = segment['high'].max() - segment['low'].min()
                if seg_range <= base_range:
                    base_end = b
                else:
                    break

            if base_end is None or base_end - base_start < 1:
                continue

            # Phase 3: Second Rally (continuation)
            rally2_start = base_end + 1
            if rally2_start >= len(df) - 1:
                continue

            base_high = df['high'].iloc[base_start:base_end + 1].max()
            base_low = df['low'].iloc[base_start:base_end + 1].min()

            # Check if current price broke above base
            if current_price > base_high:
                signal.entry_price = current_price
                signal.stop_loss = base_low - (5 * pip_value)
                signal.timeframe = "M1"

                sl_distance = signal.entry_price - signal.stop_loss
                signal.take_profit = signal.entry_price + (sl_distance * RISK_CONFIG['rr_minimum'])
                signal.risk_reward = RISK_CONFIG['rr_minimum']

                signal.pattern_details = {
                    'pattern': 'rbr',
                    'base_high': base_high,
                    'base_low': base_low,
                    'rally1_distance_pips': (df['close'].iloc[rally1_end] - rally1_start_price) / pip_value,
                }
                signal.confidence = 0.6
                signal.valid = True
                return signal

        return None

    def _detect_dbd(self, df, pip_value, current_price):
        """
        Detect Drop-Base-Drop pattern.

        1. Drop: Strong bearish move
        2. Base: Small range consolidation
        3. Drop: Continuation bearish move
        """
        signal = TradeSignal()
        signal.strategy = self.name
        signal.direction = 'sell'

        lookback = self.config['pattern_lookback']
        base_max = self.config['base_max_candles']
        base_range = self.config['base_max_range_pips'] * pip_value
        drop_min = self.config['rally_min_pips'] * pip_value

        for start in range(len(df) - lookback, len(df) - base_max - 4):
            if start < 0:
                continue

            # Phase 1: First Drop
            drop1_end = None
            drop1_start_price = df['high'].iloc[start]
            for r in range(start, min(start + 8, len(df))):
                if drop1_start_price - df['close'].iloc[r] >= drop_min:
                    drop1_end = r
                    break

            if drop1_end is None:
                continue

            # Phase 2: Base
            base_start = drop1_end + 1
            base_end = None

            for b in range(base_start, min(base_start + base_max + 1, len(df))):
                segment = df.iloc[base_start:b + 1]
                if len(segment) < 2:
                    continue

                seg_range = segment['high'].max() - segment['low'].min()
                if seg_range <= base_range:
                    base_end = b
                else:
                    break

            if base_end is None or base_end - base_start < 1:
                continue

            # Phase 3: Second Drop
            rally2_start = base_end + 1
            if rally2_start >= len(df) - 1:
                continue

            base_high = df['high'].iloc[base_start:base_end + 1].max()
            base_low = df['low'].iloc[base_start:base_end + 1].min()

            # Check if current price broke below base
            if current_price < base_low:
                signal.entry_price = current_price
                signal.stop_loss = base_high + (5 * pip_value)
                signal.timeframe = "M1"

                sl_distance = signal.stop_loss - signal.entry_price
                signal.take_profit = signal.entry_price - (sl_distance * RISK_CONFIG['rr_minimum'])
                signal.risk_reward = RISK_CONFIG['rr_minimum']

                signal.pattern_details = {
                    'pattern': 'dbd',
                    'base_high': base_high,
                    'base_low': base_low,
                    'drop1_distance_pips': (drop1_start_price - df['close'].iloc[drop1_end]) / pip_value,
                }
                signal.confidence = 0.6
                signal.valid = True
                return signal

        return None


# ===================== MULTI-TIMEFRAME CONFLUENCE =====================
class MultiTimeframeAnalyzer:
    """
    Combines signals from multiple timeframes:
    - M15: Trend direction
    - M5: Main signals (Breakout+Pullback, QM)
    - M1/M3: Fine-tuning entry (RBR/DBD)

    Only takes trades when multiple timeframes align.
    """

    def __init__(self, data_handler):
        self.data = data_handler
        self.breakout_strategy = BreakoutPullbackStrategy(data_handler)
        self.qm_strategy = QMPatternStrategy(data_handler)
        self.micro_strategy = MicroPatternStrategy(data_handler)

    def analyze(self):
        """
        Full multi-timeframe analysis.

        Returns:
            list of TradeSignal (sorted by confidence)
        """
        signals = []

        # Step 1: Get M15 trend
        trend = self.data.get_trend_direction("M15")
        if not trend:
            logger.warning("Could not determine M15 trend")
            return signals

        trend_direction = trend['direction']
        trend_strength = trend['strength']

        logger.info(f"M15 Trend: {trend_direction} (strength: {trend_strength:.2f})")

        # Step 2: Check if trend is strong enough
        if trend_strength < MTF_CONFIG['trend_strength_min']:
            logger.info(f"Trend too weak ({trend_strength:.2f}), looking for ranging patterns")
            # In ranging market, still look for QM patterns at extremes
            if trend_direction != 'neutral':
                trend_direction = 'neutral'

        # Step 3: Get M5 signals
        # Only look for signals aligned with M15 trend
        breakout_signal = self.breakout_strategy.analyze("M5")
        qm_signal = self.qm_strategy.analyze("M5")

        # Step 4: Filter by trend alignment
        if breakout_signal:
            if self._is_aligned(breakout_signal, trend_direction):
                # Step 5: Check M1/M3 for micro confirmation
                micro_signal = self.micro_strategy.analyze(
                    "M1", bias=breakout_signal.direction
                )
                if micro_signal:
                    breakout_signal.confidence *= 1.2  # Boost for micro confirmation
                    breakout_signal.pattern_details['micro_confirmation'] = True

                signals.append(breakout_signal)
            else:
                logger.debug(f"Breakout signal filtered (not aligned with {trend_direction})")

        if qm_signal:
            if self._is_aligned(qm_signal, trend_direction):
                micro_signal = self.micro_strategy.analyze(
                    "M1", bias=qm_signal.direction
                )
                if micro_signal:
                    qm_signal.confidence *= 1.2
                    qm_signal.pattern_details['micro_confirmation'] = True

                signals.append(qm_signal)
            else:
                # QM can be counter-trend (reversal pattern)
                # but reduce confidence
                qm_signal.confidence *= 0.7
                qm_signal.pattern_details['counter_trend'] = True
                signals.append(qm_signal)

        # Step 6: Check standalone micro patterns (only if trend is strong)
        if trend_strength > 0.5:
            micro_bias = 'buy' if trend_direction == 'bullish' else 'sell' if trend_direction == 'bearish' else None
            if micro_bias:
                micro_signal = self.micro_strategy.analyze("M1", bias=micro_bias)
                if micro_signal:
                    micro_signal.confidence *= 0.8  # Lower confidence for standalone micro
                    signals.append(micro_signal)

        # Step 7: Sort by confidence (highest first)
        signals.sort(key=lambda x: x.confidence, reverse=True)

        # Cap confidence at 1.0
        for s in signals:
            s.confidence = min(s.confidence, 1.0)

        logger.info(f"Total signals found: {len(signals)}")
        return signals

    def _is_aligned(self, signal, trend_direction):
        """Check if signal aligns with trend."""
        if trend_direction == 'neutral':
            return True  # All signals ok in neutral
        if signal.direction == 'buy' and trend_direction == 'bullish':
            return True
        if signal.direction == 'sell' and trend_direction == 'bearish':
            return True
        return False

    def get_best_signal(self):
        """Get the single best signal after full analysis."""
        signals = self.analyze()
        if not signals:
            return None

        best = signals[0]

        # Validate minimum confidence
        from config import AI_CONFIG
        if best.confidence < AI_CONFIG['min_confidence']:
            logger.info(f"Best signal confidence ({best.confidence:.2f}) below threshold")
            return None

        # Validate minimum RR
        if best.risk_reward < RISK_CONFIG['rr_minimum']:
            logger.info(f"Best signal RR ({best.risk_reward:.1f}) below minimum")
            return None

        return best
