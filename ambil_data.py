"""
=============================================================================
AMBIL DATA - Multi-Timeframe Data Handler
=============================================================================
Handles data retrieval for M1, M3, M5, M15 timeframes
Calculates indicators: EMA, ATR, Volume Profile, Swing Points
=============================================================================
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import logging

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False

from config import (
    BROKER_CONFIG, TIMEFRAMES, CANDLE_COUNT,
    MTF_CONFIG, SR_CONFIG, BREAKOUT_CONFIG
)

logger = logging.getLogger(__name__)


# ===================== TIMEFRAME MAPPING =====================
TF_MAP = {
    "M1": mt5.TIMEFRAME_M1 if MT5_AVAILABLE else 1,
    "M3": mt5.TIMEFRAME_M3 if MT5_AVAILABLE else 3,
    "M5": mt5.TIMEFRAME_M5 if MT5_AVAILABLE else 5,
    "M15": mt5.TIMEFRAME_M15 if MT5_AVAILABLE else 15,
    "M30": mt5.TIMEFRAME_M30 if MT5_AVAILABLE else 30,
    "H1": mt5.TIMEFRAME_H1 if MT5_AVAILABLE else 60,
    "H4": mt5.TIMEFRAME_H4 if MT5_AVAILABLE else 240,
    "D1": mt5.TIMEFRAME_D1 if MT5_AVAILABLE else 1440,
}


class DataHandler:
    """
    Multi-timeframe data handler.
    Fetches and processes OHLCV data from MT5 for multiple timeframes.
    """

    def __init__(self, symbol=None):
        self.symbol = symbol or BROKER_CONFIG["symbol"]
        self.data = {}  # Dict of DataFrames per timeframe
        self.indicators = {}  # Calculated indicators per timeframe
        self.sr_levels = []  # Support/Resistance levels
        self.swing_points = []  # Swing highs and lows
        self.connected = False

    # ===================== CONNECTION =====================
    def connect(self):
        """Initialize MT5 connection."""
        if not MT5_AVAILABLE:
            logger.error("MetaTrader5 not installed. Install with: pip install MetaTrader5")
            return False

        if not mt5.initialize():
            logger.error(f"MT5 initialization failed: {mt5.last_error()}")
            return False

        # Login if credentials provided
        if BROKER_CONFIG["login"] > 0:
            authorized = mt5.login(
                login=BROKER_CONFIG["login"],
                password=BROKER_CONFIG["password"],
                server=BROKER_CONFIG["server"]
            )
            if not authorized:
                logger.error(f"MT5 login failed: {mt5.last_error()}")
                return False

        self.connected = True
        logger.info(f"Connected to MT5. Symbol: {self.symbol}")
        return True

    def disconnect(self):
        """Shutdown MT5 connection."""
        if MT5_AVAILABLE and self.connected:
            mt5.shutdown()
            self.connected = False
            logger.info("Disconnected from MT5")

    # ===================== DATA FETCHING =====================
    def fetch_all_timeframes(self):
        """Fetch data for all configured timeframes."""
        success = True
        for tf_name, tf_label in TIMEFRAMES.items():
            count = CANDLE_COUNT.get(tf_label, 200)
            df = self.fetch_candles(tf_label, count)
            if df is not None and not df.empty:
                self.data[tf_label] = df
                self._calculate_indicators(tf_label)
                logger.info(f"Fetched {len(df)} candles for {tf_label}")
            else:
                logger.warning(f"Failed to fetch data for {tf_label}")
                success = False
        return success

    def fetch_candles(self, timeframe, count=200):
        """
        Fetch OHLCV candles from MT5.

        Args:
            timeframe: String timeframe (M1, M5, M15, etc.)
            count: Number of candles to fetch

        Returns:
            DataFrame with OHLCV + time columns
        """
        if not self.connected:
            logger.error("Not connected to MT5")
            return None

        tf_mt5 = TF_MAP.get(timeframe)
        if tf_mt5 is None:
            logger.error(f"Invalid timeframe: {timeframe}")
            return None

        try:
            rates = mt5.copy_rates_from_pos(self.symbol, tf_mt5, 0, count)
            if rates is None or len(rates) == 0:
                logger.error(f"No data received for {timeframe}")
                return None

            df = pd.DataFrame(rates)
            df['time'] = pd.to_datetime(df['time'], unit='s')
            df.set_index('time', inplace=True)

            # Rename columns for consistency
            df.rename(columns={
                'open': 'open',
                'high': 'high',
                'low': 'low',
                'close': 'close',
                'tick_volume': 'volume',
                'real_volume': 'real_volume',
                'spread': 'spread'
            }, inplace=True)

            # Calculate basic derived columns
            df['body'] = abs(df['close'] - df['open'])
            df['range'] = df['high'] - df['low']
            df['body_ratio'] = df['body'] / df['range'].replace(0, np.nan)
            df['is_bullish'] = df['close'] > df['open']
            df['mid_price'] = (df['high'] + df['low']) / 2

            return df

        except Exception as e:
            logger.error(f"Error fetching {timeframe} data: {e}")
            return None

    def get_current_price(self):
        """Get current bid/ask price."""
        if not self.connected:
            return None, None

        tick = mt5.symbol_info_tick(self.symbol)
        if tick is None:
            return None, None
        return tick.bid, tick.ask

    def get_symbol_info(self):
        """Get symbol information (point, digits, etc.)."""
        if not self.connected:
            return None
        return mt5.symbol_info(self.symbol)


    # ===================== INDICATORS =====================
    def _calculate_indicators(self, timeframe):
        """Calculate all indicators for a timeframe."""
        df = self.data.get(timeframe)
        if df is None or df.empty:
            return

        indicators = {}

        # EMA calculations
        indicators['ema_fast'] = self._ema(df['close'], MTF_CONFIG['trend_ema_fast'])
        indicators['ema_slow'] = self._ema(df['close'], MTF_CONFIG['trend_ema_slow'])
        indicators['ema_200'] = self._ema(df['close'], MTF_CONFIG['trend_ema_filter'])
        indicators['ema_signal'] = self._ema(df['close'], MTF_CONFIG['signal_ema'])
        indicators['ema_micro'] = self._ema(df['close'], MTF_CONFIG['micro_ema'])

        # ATR (Average True Range)
        indicators['atr'] = self._atr(df, period=14)

        # Volume analysis
        indicators['vol_sma'] = df['volume'].rolling(window=20).mean()
        indicators['vol_ratio'] = df['volume'] / indicators['vol_sma']

        # Momentum (ROC - Rate of Change)
        indicators['momentum'] = df['close'].pct_change(periods=10) * 100

        # RSI
        indicators['rsi'] = self._rsi(df['close'], period=14)

        # Volatility (standard deviation of returns)
        indicators['volatility'] = df['close'].pct_change().rolling(window=20).std()

        # Trend strength (ADX simplified)
        indicators['trend_strength'] = self._trend_strength(df)

        # Store in indicators dict
        self.indicators[timeframe] = indicators

        # Also add indicators to the DataFrame
        for key, value in indicators.items():
            if isinstance(value, pd.Series):
                df[key] = value

    def _ema(self, series, period):
        """Calculate Exponential Moving Average."""
        return series.ewm(span=period, adjust=False).mean()

    def _atr(self, df, period=14):
        """Calculate Average True Range."""
        high = df['high']
        low = df['low']
        close = df['close']

        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))

        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        return atr

    def _rsi(self, series, period=14):
        """Calculate RSI."""
        delta = series.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)

        avg_gain = gain.rolling(window=period).mean()
        avg_loss = loss.rolling(window=period).mean()

        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def _trend_strength(self, df, period=14):
        """
        Simplified trend strength calculation (0-1).
        Based on directional movement.
        """
        high = df['high']
        low = df['low']

        plus_dm = high.diff()
        minus_dm = -low.diff()

        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

        atr = self._atr(df, period)

        plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr.replace(0, np.nan))
        minus_di = 100 * (minus_dm.rolling(window=period).mean() / atr.replace(0, np.nan))

        dx = abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, np.nan) * 100
        adx = dx.rolling(window=period).mean()

        # Normalize to 0-1
        return (adx / 100).clip(0, 1)


    # ===================== SUPPORT & RESISTANCE =====================
    def calculate_sr_levels(self, timeframe="M5"):
        """
        Calculate Support and Resistance levels using fractal method.
        Returns list of SR levels with strength scores.
        """
        df = self.data.get(timeframe)
        if df is None or df.empty:
            return []

        period = SR_CONFIG["fractal_period"]
        levels = []

        # Find fractal highs (resistance)
        for i in range(period, len(df) - period):
            is_fractal_high = True
            is_fractal_low = True

            for j in range(1, period + 1):
                if df['high'].iloc[i] <= df['high'].iloc[i - j]:
                    is_fractal_high = False
                if df['high'].iloc[i] <= df['high'].iloc[i + j]:
                    is_fractal_high = False
                if df['low'].iloc[i] >= df['low'].iloc[i - j]:
                    is_fractal_low = False
                if df['low'].iloc[i] >= df['low'].iloc[i + j]:
                    is_fractal_low = False

            if is_fractal_high:
                levels.append({
                    'price': df['high'].iloc[i],
                    'type': 'resistance',
                    'time': df.index[i],
                    'index': i
                })

            if is_fractal_low:
                levels.append({
                    'price': df['low'].iloc[i],
                    'type': 'support',
                    'time': df.index[i],
                    'index': i
                })

        # Cluster nearby levels
        clustered = self._cluster_sr_levels(levels)

        # Calculate strength for each level
        for level in clustered:
            level['strength'] = self._calculate_sr_strength(level, df)

        # Sort by strength
        clustered.sort(key=lambda x: x['strength'], reverse=True)

        self.sr_levels = clustered
        logger.info(f"Found {len(clustered)} SR levels on {timeframe}")
        return clustered

    def _cluster_sr_levels(self, levels):
        """Cluster nearby SR levels together."""
        if not levels:
            return []

        threshold = SR_CONFIG["cluster_threshold_pips"] * self._get_pip_value()
        clustered = []

        # Sort by price
        sorted_levels = sorted(levels, key=lambda x: x['price'])

        current_cluster = [sorted_levels[0]]

        for i in range(1, len(sorted_levels)):
            if sorted_levels[i]['price'] - current_cluster[-1]['price'] <= threshold:
                current_cluster.append(sorted_levels[i])
            else:
                # Average the cluster
                avg_price = np.mean([l['price'] for l in current_cluster])
                clustered.append({
                    'price': avg_price,
                    'type': current_cluster[0]['type'],
                    'touches': len(current_cluster),
                    'first_time': current_cluster[0]['time'],
                    'last_time': current_cluster[-1]['time'],
                })
                current_cluster = [sorted_levels[i]]

        # Don't forget last cluster
        if current_cluster:
            avg_price = np.mean([l['price'] for l in current_cluster])
            clustered.append({
                'price': avg_price,
                'type': current_cluster[0]['type'],
                'touches': len(current_cluster),
                'first_time': current_cluster[0]['time'],
                'last_time': current_cluster[-1]['time'],
            })

        return clustered

    def _calculate_sr_strength(self, level, df):
        """
        Calculate strength of an SR level (0-1).
        Based on: touches, recency, volume at level.
        """
        weights = SR_CONFIG["sr_strength_weight"]

        # Touch score (normalized)
        touch_score = min(level.get('touches', 1) / 5.0, 1.0)

        # Recency score
        if 'last_time' in level and len(df) > 0:
            total_time = (df.index[-1] - df.index[0]).total_seconds()
            level_age = (df.index[-1] - level['last_time']).total_seconds()
            recency_score = max(0, 1.0 - (level_age / total_time)) if total_time > 0 else 0.5
        else:
            recency_score = 0.5

        # Volume score (average volume near level)
        pip_value = self._get_pip_value()
        near_level = df[abs(df['close'] - level['price']) < 10 * pip_value]
        if len(near_level) > 0 and 'vol_sma' in df.columns:
            vol_at_level = near_level['volume'].mean()
            vol_avg = df['volume'].mean()
            volume_score = min(vol_at_level / vol_avg if vol_avg > 0 else 0.5, 2.0) / 2.0
        else:
            volume_score = 0.5

        # Weighted score
        strength = (
            weights['touches'] * touch_score +
            weights['recency'] * recency_score +
            weights['volume'] * volume_score
        )

        return min(max(strength, 0), 1.0)

    def _get_pip_value(self):
        """Get pip value for the symbol."""
        if self.symbol in ["XAUUSD", "GOLD"]:
            return 0.1  # Gold: 1 pip = 0.1
        elif "JPY" in self.symbol:
            return 0.01
        else:
            return 0.0001  # Standard forex pairs
