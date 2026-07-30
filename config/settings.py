"""
⚙️ إعدادات Sniper Bot Solana V2
═════════════════════════════════════════════════════════════════
"""

import os
from typing import Dict, List

# ──────────────────────────────────────────────────────────────
# الشبكة والـ RPC
# ──────────────────────────────────────────────────────────────

NETWORK = os.getenv("NETWORK", "mainnet-beta")
RPC_ENDPOINTS = [
    os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com"),
    "https://solana-api.projectserum.com",
    "https://rpc.ankr.com/solana",
]
COMMITMENT = "confirmed"

# ──────────────────────────────────────────────────────────────
# المحفظة
# ──────────────────────────────────────────────────────────────

WALLET_PRIVATE_KEY = os.getenv("WALLET_PRIVATE_KEY")
WALLET_KEYPAIR_PATH = os.getenv("WALLET_KEYPAIR_PATH", "wallet.json")

# ──────────────────────────────────────────────────────────────
# قاعدة البيانات
# ──────────────────────────────────────────────────────────────

DATABASE_URL = os.getenv("DATABASE_URL")
DATABASE_BACKUP_URL = os.getenv("DATABASE_BACKUP_URL")

# ──────────────────────────────────────────────────────────────
# مصادر البيانات
# ──────────────────────────────────────────────────────────────

PUMPPORTAL_WEBSOCKET = os.getenv("PUMPPORTAL_WEBSOCKET", "wss://pumpportal.fun/api/data")
PUMPFUN_URL = "https://pump.fun"

# ──────────────────────────────────────────────────────────────
# 🔥 قائمة DEX المسموح بها
# ──────────────────────────────────────────────────────────────

DEX_ALLOWLIST: List[str] = [
    "Raydium",
    "Jupiter",
    "Orca",
    "Phoenix",
    "Marinade",
]

# ──────────────────────────────────────────────────────────────
# 🔥 الفلاتر (مهم!)
# ──────────────────────────────────────────────────────────────

FILTERS = {
    "max_dev_wallet_pct": 15.0,
    "min_pool_size_sol": 50000.0,
    "min_pool_size_usd": 500000.0,
    "max_token_age_minutes": 5,
    "min_tx_count": 10,
}

SHARIA_FILTERS_ENABLED = False  # تعطيل / تفعيل

# ──────────────────────────────────────────────────────────────
# فلاتر الأمان (الاستراتيجية #1 - التوازن)
# ──────────────────────────────────────────────────────────────

MAX_DEV_WALLET_PCT = 15.0  # الحد الأقصى لأكبر محفظة
MIN_POOL_SIZE_SOL = 50000.0
MIN_POOL_SIZE_USD = 500000.0
MAX_TOKEN_AGE_MINUTES = 5
MIN_TX_COUNT = 10
BANNED_NAMES = ["USWR"]

# ──────────────────────────────────────────────────────────────
# معايير التداول
# ──────────────────────────────────────────────────────────────

CAPITAL_PER_TRADE_SOL = 0.05
MAX_TRADES_OPEN = 5
TAKE_PROFIT_FIRST_PCT = 2.0
STOP_LOSS_PCT = -30.0

# ──────────────────────────────────────────────────────────────
# المراقبة والخروج (محسّنة)
# ──────────────────────────────────────────────────────────────

MONITOR_INTERVAL_SECONDS = 0.5
CRASH_DETECTION_ENABLED = True
CRASH_THRESHOLD_PCT = -50.0
LIQUIDITY_CRASH_PCT = -50.0

# ──────────────────────────────────────────────────────────────
# الإعدادات المتقدمة
# ──────────────────────────────────────────────────────────────

GAS_LIMIT = 1000000
SLIPPAGE_TOLERANCE_PCT = 10.0
PRIORITY_FEE_LAMPORTS = 100000

BATCH_EXIT_ENABLED = True
BATCH_SIZES = [0.2, 0.3, 0.5]

RETRY_ON_FAILURE = True
MAX_RETRIES = 4
RETRY_DELAY_SEC = 0.1

# ──────────────────────────────────────────────────────────────
# التقارير والـ Logs
# ──────────────────────────────────────────────────────────────

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
ENABLE_DETAILED_LOGS = True
DAILY_REPORT_TIME = "23:00"

# ──────────────────────────────────────────────────────────────
# حالة التطبيق
# ──────────────────────────────────────────────────────────────

TRADING_MODE = "PRODUCTION"
VERSION = "2.0-ENHANCED"

CONFIG_SUMMARY = {
    "Mode": TRADING_MODE,
    "Version": VERSION,
    "MaxDevWallet": f"{MAX_DEV_WALLET_PCT}%",
    "MonitorInterval": f"{MONITOR_INTERVAL_SECONDS}s",
    "CrashDetection": CRASH_DETECTION_ENABLED,
    "BatchExit": BATCH_EXIT_ENABLED,
    "Strategy": "Balance #1",
    "DEXAllowlist": ", ".join(DEX_ALLOWLIST),
}
