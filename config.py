"""
=============================================================================
KONFIGURASI TRADING BOT - ADVANCED STRATEGY
=============================================================================
Multi-timeframe analysis with Breakout+Pullback & QM Pattern
=============================================================================
"""

# ===================== BROKER & ACCOUNT =====================
BROKER_CONFIG = {
    "server": "YOUR_BROKER_SERVER",
    "login": 0,          # MT5 account number
    "password": "",      # MT5 password
    "symbol": "XAUUSD",  # Trading pair
    "magic_number": 202501,
}

# ===================== TIMEFRAMES =====================
TIMEFRAMES = {
    "trend": "M15",      # Trend direction (higher timeframe)
    "signal": "M5",      # Main signal generation
    "micro": "M1",       # Fine-tuning entry (RBR/DBD patterns)
    "micro_alt": "M3",   # Alternative micro timeframe
}

# Jumlah candle yang diambil per timeframe
CANDLE_COUNT = {
    "M15": 200,
    "M5": 300,
    "M3": 400,
    "M1": 500,
}

# ===================== STRATEGY PARAMETERS =====================

# --- Breakout + Pullback Strategy ---
BREAKOUT_CONFIG = {
    "lookback_period": 20,           # Candle lookback untuk SR level
    "breakout_threshold_pips": 5,    # Minimum pips di atas SR untuk confirm breakout
    "pullback_zone_pips": 15,        # Zone pullback (jarak dari SR)
    "pullback_max_candles": 10,      # Max candle menunggu pullback
    "confirmation_candles": 2,       # Candle konfirmasi setelah pullback
    "body_ratio_min": 0.6,           # Minimum body/range ratio for strong candle
    "volume_multiplier": 1.2,        # Volume harus > avg * multiplier untuk valid breakout
}

# --- QM (Quasimodo) Pattern Strategy ---
QM_CONFIG = {
    "swing_lookback": 30,            # Candle lookback untuk swing points
    "swing_threshold_pips": 10,      # Minimum pips antar swing points
    "neckline_tolerance_pips": 5,    # Toleransi neckline
    "pattern_max_candles": 50,       # Max candle untuk pattern completion
    "entry_zone_pips": 10,           # Entry zone dari level QM
    "min_pattern_height_pips": 30,   # Minimum height of QM pattern
}

# --- Multi-Timeframe Analysis ---
MTF_CONFIG = {
    "trend_ema_fast": 20,            # EMA cepat untuk trend M15
    "trend_ema_slow": 50,            # EMA lambat untuk trend M15
    "trend_ema_filter": 200,         # EMA filter utama
    "signal_ema": 20,                # EMA untuk signal M5
    "micro_ema": 9,                  # EMA untuk micro M1/M3
    "trend_strength_min": 0.3,       # Minimum trend strength (0-1)
    "alignment_required": True,      # Semua TF harus selaras
}

# --- RBR/DBD Micro Pattern (M1/M3) ---
MICRO_PATTERN_CONFIG = {
    "base_max_candles": 5,           # Max candle dalam base zone
    "base_max_range_pips": 10,       # Max range base zone
    "rally_min_pips": 15,            # Minimum rally/drop distance
    "pattern_lookback": 20,          # Lookback untuk detect pattern
}

# ===================== RISK MANAGEMENT =====================
RISK_CONFIG = {
    "risk_percent": 1.5,             # Risk per trade (1-2%)
    "risk_min": 1.0,                 # Minimum risk %
    "risk_max": 2.0,                 # Maximum risk %
    "sl_min_pips": 30,               # Minimum SL distance
    "sl_max_pips": 60,               # Maximum SL distance
    "rr_minimum": 2.0,               # Minimum Risk:Reward ratio
    "rr_target": 3.0,                # Target Risk:Reward ratio
    "max_trades_per_day": 5,         # Max trades per hari
    "max_drawdown_percent": 5.0,     # Max drawdown sebelum stop
    "trailing_stop_activate_pips": 30,  # Activate trailing setelah X pips profit
    "trailing_stop_distance_pips": 15,  # Trailing stop distance
    "breakeven_activate_pips": 20,   # Move SL to breakeven setelah X pips
}

# ===================== SUPPORT & RESISTANCE =====================
SR_CONFIG = {
    "method": "fractal",             # fractal, pivot, atr_cluster
    "fractal_period": 5,             # Period for fractal SR
    "cluster_threshold_pips": 10,    # Jarak clustering SR levels
    "min_touches": 2,                # Minimum touches untuk valid SR
    "sr_strength_weight": {          # Weight untuk SR strength
        "touches": 0.4,
        "recency": 0.3,
        "volume": 0.3,
    },
    "weak_sr_threshold": 0.4,        # Threshold untuk "weak" SR (for SL placement)
}

# ===================== SELF-LEARNING =====================
LEARNING_CONFIG = {
    "history_file": "trade_history.json",
    "learning_file": "learning_data.json",
    "min_trades_for_learning": 20,   # Min trades sebelum adjust
    "confidence_decay": 0.95,        # Decay factor per period
    "win_boost": 0.05,               # Boost confidence on win
    "loss_penalty": 0.03,            # Reduce confidence on loss
    "session_analysis": True,        # Analyze by trading session
    "pattern_analysis": True,        # Analyze by pattern type
    "time_analysis": True,           # Analyze by time of day
    "market_condition_analysis": True,  # Trending vs ranging
    "adaptive_parameters": True,     # Auto-adjust strategy params
    "learning_rate": 0.1,            # Rate of parameter adjustment
}

# ===================== TRADING SESSIONS =====================
SESSIONS = {
    "asian": {"start": "00:00", "end": "08:00"},   # UTC
    "london": {"start": "08:00", "end": "16:00"},  # UTC
    "newyork": {"start": "13:00", "end": "21:00"}, # UTC
    "overlap": {"start": "13:00", "end": "16:00"}, # UTC (London+NY overlap)
}

# Preferred sessions for trading
PREFERRED_SESSIONS = ["london", "overlap", "newyork"]

# ===================== AI/ML PARAMETERS =====================
AI_CONFIG = {
    "model_type": "ensemble",        # ensemble, random_forest, gradient_boost
    "features": [
        "trend_direction",
        "trend_strength",
        "sr_proximity",
        "pattern_type",
        "volume_profile",
        "session",
        "volatility",
        "momentum",
        "candle_pattern",
    ],
    "retrain_interval": 50,          # Retrain setelah X trades
    "min_confidence": 0.65,          # Minimum AI confidence untuk trade
    "use_sentiment": False,          # Use news sentiment (future)
}

# ===================== LOGGING =====================
LOG_CONFIG = {
    "level": "INFO",                 # DEBUG, INFO, WARNING, ERROR
    "file": "trading_bot.log",
    "max_size_mb": 50,
    "backup_count": 5,
    "console_output": True,
}

# ===================== NOTIFICATIONS =====================
NOTIFICATION_CONFIG = {
    "telegram_enabled": False,
    "telegram_token": "",
    "telegram_chat_id": "",
    "notify_on_trade": True,
    "notify_on_signal": True,
    "notify_on_error": True,
    "daily_report": True,
}
