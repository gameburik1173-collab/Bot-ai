# PANDUAN PEMASANGAN - Advanced Trading Bot

## Daftar File Yang Harus Anda Miliki

```
📁 Trading_Bot/
├── config.py              # Konfigurasi utama
├── ambil_data.py          # Handler data multi-timeframe
├── strategi.py            # Strategi trading (Breakout+Pullback, QM, RBR/DBD)
├── money_management.py    # Manajemen lot & risiko
├── self_learning.py       # Self-learning & adaptif
├── ai_agent.py            # Mesin keputusan AI
├── trading_bot.py         # Bot utama (main file)
├── trade_history.json     # (Auto-dibuat saat pertama kali jalan)
└── learning_data.json     # (Auto-dibuat saat pertama kali jalan)
```

---

## LANGKAH 1: Persiapan Sistem

### Kebutuhan:
- **Windows 10/11** (MetaTrader5 hanya berjalan di Windows)
- **Python 3.8+** (disarankan 3.10 atau 3.11)
- **MetaTrader 5** terinstall dan login ke broker

### Install Python (jika belum):
1. Download dari https://www.python.org/downloads/
2. Saat install, **centang "Add Python to PATH"**
3. Klik Install

---

## LANGKAH 2: Buat Folder Project

```bash
# Buka Command Prompt (CMD) atau PowerShell
mkdir C:\Trading_Bot
cd C:\Trading_Bot
```

---

## LANGKAH 3: Install Library Python

Buka CMD/PowerShell lalu jalankan:

```bash
pip install MetaTrader5
pip install pandas
pip install numpy
```

Atau buat file `requirements.txt` dengan isi:
```
MetaTrader5>=5.0.45
pandas>=1.5.0
numpy>=1.23.0
```

Lalu jalankan:
```bash
pip install -r requirements.txt
```

---

## LANGKAH 4: Download/Salin Semua File

### Cara Mendapatkan File:

**Opsi A - Dari GitHub (jika sudah di-push):**
```bash
git clone https://github.com/gameburik1173-collab/Kalkulator-.git
cd Kalkulator-
```

**Opsi B - Salin Manual:**
Salin ke-7 file Python ke folder `C:\Trading_Bot\`:
- `config.py`
- `ambil_data.py`
- `strategi.py`
- `money_management.py`
- `self_learning.py`
- `ai_agent.py`
- `trading_bot.py`

---

## LANGKAH 5: Konfigurasi Broker (PENTING!)

Buka file `config.py` dan edit bagian berikut:

```python
BROKER_CONFIG = {
    "server": "NamaServerBrokerAnda",  # Contoh: "Exness-MT5Real"
    "login": 12345678,                  # Nomor akun MT5 Anda
    "password": "password_anda",        # Password MT5
    "symbol": "XAUUSD",                 # Pair yang mau ditrade
    "magic_number": 202501,
}
```

### Cara Cari Nama Server:
1. Buka MetaTrader 5
2. Klik kanan pada akun di Navigator → "Properties"
3. Lihat field "Server"

### Symbol yang Didukung:
- `XAUUSD` atau `GOLD` (Gold)
- `EURUSD`, `GBPUSD`, dll (Forex)
- Sesuaikan dengan nama symbol di broker Anda

---

## LANGKAH 6: Pastikan MetaTrader 5 Terbuka

**PENTING:** MetaTrader 5 HARUS terbuka dan login sebelum menjalankan bot!

1. Buka MetaTrader 5
2. Login ke akun trading Anda
3. Pastikan chart XAUUSD (atau pair pilihan) terbuka
4. Pastikan "Algo Trading" aktif (tombol hijau di toolbar)

### Aktifkan Algo Trading:
- Menu: Tools → Options → Expert Advisors
- Centang: "Allow algorithmic trading"
- Centang: "Allow DLL imports"

---

## LANGKAH 7: Jalankan Bot

Buka CMD/PowerShell, masuk ke folder project:

```bash
cd C:\Trading_Bot
```

### Mode Live Trading:
```bash
python trading_bot.py
```

### Mode Cek Status:
```bash
python trading_bot.py --status
```

### Mode Lihat Report:
```bash
python trading_bot.py --report
```

### Mode Single Analysis (test tanpa eksekusi):
```bash
python trading_bot.py --analyze
```

### Bantuan:
```bash
python trading_bot.py --help
```

---

## LANGKAH 8: Verifikasi Bot Berjalan

Jika berhasil, Anda akan melihat output seperti:

```
======================================================================
  ADVANCED TRADING BOT - Starting
======================================================================
  Symbol: XAUUSD
  Timeframes: {'trend': 'M15', 'signal': 'M5', 'micro': 'M1', 'micro_alt': 'M3'}
  Risk: 1.5% per trade
  RR Minimum: 1:2.0
  SL Range: 30-60 pips
  Max Daily Trades: 5
  Analysis Interval: 30s
======================================================================
Bot is now running. Press Ctrl+C to stop.
```

---

## LANGKAH 9: Konfigurasi Telegram (Opsional)

Jika ingin notifikasi via Telegram:

1. Buat bot Telegram melalui @BotFather
2. Dapatkan token bot
3. Dapatkan chat_id Anda (kirim pesan ke bot, lalu cek di `https://api.telegram.org/bot<TOKEN>/getUpdates`)
4. Edit `config.py`:

```python
NOTIFICATION_CONFIG = {
    "telegram_enabled": True,
    "telegram_token": "1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ",
    "telegram_chat_id": "123456789",
    "notify_on_trade": True,
    "notify_on_signal": True,
    "notify_on_error": True,
    "daily_report": True,
}
```

---

## Tips Penting

### Mulai dengan Akun Demo!
- **JANGAN langsung pakai akun real**
- Test minimal 2-4 minggu di demo
- Pastikan winrate > 50% sebelum live

### Risk Management:
- Default risk 1.5% per trade (aman)
- Max 5 trades per hari
- Max drawdown 5% lalu bot berhenti otomatis

### Self-Learning:
- Bot akan menyimpan semua trade di `trade_history.json`
- Setelah 20+ trades, bot mulai menyesuaikan strategi
- Semakin banyak data, semakin pintar bot

### Menghentikan Bot:
- Tekan `Ctrl+C` di terminal
- Bot akan shutdown dengan aman

---

## Troubleshooting

| Masalah | Solusi |
|---------|--------|
| "MetaTrader5 not installed" | `pip install MetaTrader5` |
| "MT5 initialization failed" | Pastikan MT5 terbuka dan login |
| "MT5 login failed" | Cek server, login, password di config.py |
| "No data received" | Pastikan symbol benar dan chart terbuka di MT5 |
| "Insufficient free margin" | Balance terlalu kecil untuk lot minimum |
| Bot tidak buka trade | Normal! Bot hanya trade saat semua kondisi terpenuhi |

---

## Struktur Kerja Bot

```
Setiap 30 detik:
1. Ambil data M15, M5, M3, M1
2. Analisis trend M15 (EMA 20/50/200, swing points)
3. Cari sinyal M5:
   - Breakout + Pullback di SR level
   - QM Pattern (Quasimodo)
4. Konfirmasi M1/M3:
   - RBR (Rally-Base-Rally) untuk BUY
   - DBD (Drop-Base-Drop) untuk SELL
5. Scoring AI (confidence 0-1):
   - Confluence × 25%
   - MTF Alignment × 20%
   - Market Fit × 15%
   - Self-Learning × 20%
   - RR Quality × 10%
   - Session × 10%
6. Jika confidence > threshold → EXECUTE TRADE
7. Money management: hitung lot berdasar SL distance
8. Trailing stop & breakeven otomatis
9. Catat hasil → update learning
```

---

## Kontak & Support

Jika ada pertanyaan atau masalah, silakan buat Issue di repository GitHub.

---

*Bot ini untuk tujuan edukasi. Trading mengandung risiko tinggi. Selalu gunakan akun demo terlebih dahulu.*
