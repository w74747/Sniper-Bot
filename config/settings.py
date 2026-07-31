"""
⚙️ إعدادات Sniper Bot Solana V2
═════════════════════════════════════════════════════════════════

التحديثات:
✅ max_dev_wallet_pct: 8% → 15% (استراتيجية التوازن)
✅ monitor_interval: 10s → 0.5s (مراقبة سريعة)
✅ إضافة DEX_ALLOWLIST
✅ إضافة كشف الانهيارات
✅ إضافة جميع مفاتيح API الناقصة
✅ إضافة FILTERS و MOMENTUM dataclasses
"""

import os
from typing import Dict, List
from dataclasses import dataclass

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
# قائمة DEX المسموح بها
# ──────────────────────────────────────────────────────────────

DEX_ALLOWLIST: List[str] = [
    "Raydium",
    "Jupiter",
    "Orca",
    "Phoenix",
    "Marinade",
]

# ──────────────────────────────────────────────────────────────
# فلاتر الأمان (الاستراتيجية #1 - التوازن)
# ──────────────────────────────────────────────────────────────

MAX_DEV_WALLET_PCT = 15.0
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
# المراقبة والخروج
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
# نمط التطوير مقابل الإنتاج
# ──────────────────────────────────────────────────────────────

USE_DEVNET = os.getenv("USE_DEVNET", "true").lower() == "true"

# ──────────────────────────────────────────────────────────────
# مفاتيح API والنقاط النهائية
# ──────────────────────────────────────────────────────────────

PRIMARY_RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")

PUMPPORTAL_API_KEY = os.getenv("PUMPPORTAL_API_KEY", "")
JUPITER_API_KEY = os.getenv("JUPITER_API_KEY", "")
JUPITER_API_BASE = os.getenv("JUPITER_API_BASE", "https://quote-api.jup.ag/v6")

RUGCHECK_API_KEY = os.getenv("RUGCHECK_API_KEY", "")
GMGN_API_KEY = os.getenv("GMGN_API_KEY", "")

SOLSCAN_API_KEY = os.getenv("SOLSCAN_API_KEY", "")
SOLSCAN_API_BASE = os.getenv("SOLSCAN_API_BASE", "https://api.solscan.io")

TATUM_API_KEY = os.getenv("TATUM_API_KEY", "")
TATUM_SOLANA_RPC_URL = os.getenv("TATUM_SOLANA_RPC_URL", "")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_BASE = os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com/v1")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

GOPLUS_API_BASE = os.getenv("GOPLUS_API_BASE", "https://api.gopluslabs.io")
GOPLUS_APP_KEY = os.getenv("GOPLUS_APP_KEY", "")
GOPLUS_APP_SECRET = os.getenv("GOPLUS_APP_SECRET", "")

DEXSCREENER_API_BASE = os.getenv("DEXSCREENER_API_BASE", "https://api.dexscreener.com/latest")
BIRDEYE_API_KEY = os.getenv("BIRDEYE_API_KEY", "")
BIRDEYE_API_BASE = os.getenv("BIRDEYE_API_BASE", "https://public-api.birdeye.so")

# ──────────────────────────────────────────────────────────────
# إعدادات الفلاتر
# ──────────────────────────────────────────────────────────────

@dataclass
class FilterConfig:
    """إعدادات الفلاتر والعتبات الأمنية"""
    max_allowed_prior_rugs: int = 2
    min_security_score: float = 50.0

FILTERS = FilterConfig()


@dataclass
class MomentumConfig:
    """إعدادات فحص الزخم"""
    min_liquidity_usd: float = 50000.0
    max_marketcap_to_liquidity_ratio: float = 10.0
    min_price_change_m5_pct: float = 2.0
    max_price_change_m5_pct: float = 50.0
    min_volume_m5_usd: float = 10000.0
    min_unique_buys_m5: int = 10
    min_buy_sell_ratio_m5: float = 1.5

MOMENTUM = MomentumConfig()

# ──────────────────────────────────────────────────────────────
# استراتيجية الخروج والـ Watchlist
# ──────────────────────────────────────────────────────────────

EXIT_STRATEGY = "multi_batch"
WATCHLIST = True
FAST_TRACK = True

HOLDER_VELOCITY = 5
SUSTAINED_TREND = 3
GRADUATION_PROXIMITY = 0.8

RUGCHECK_MAX_SCORE = 5
RUGCHECK_MAX_INSIDERS = 3
ESTABLISHED_LIQUID = 100000.0

GMGN_MAX_RAT_TRADER_PCT = 10.0
GMGN_MAX_BUNDLER_PCT = 5.0
GMGN_MAX_RUG_RATIO = 0.15

SYMBOL_BLOCKLIST_LOSS_THRESHOLD_PCT = -50.0
SYMBOL_BLOCKLIST_MAX_OCCURRENCES = 3

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
    "Strategy": "Balance #1 (15% wallet cap)",
    "DEXAllowlist": ", ".join(DEX_ALLOWLIST),
    "UseDevnet": USE_DEVNET,
    "Watchlist": WATCHLIST,
    "FastTrack": FAST_TRACK,
}
