"""
⚙️ إعدادات Sniper Bot Solana V2
═════════════════════════════════════════════════════════════════

التحديثات:
✅ max_dev_wallet_pct: 8% → 15% (استراتيجية التوازن)
✅ monitor_interval: 10s → 0.5s (مراقبة سريعة)
✅ إضافة DEX_ALLOWLIST (مفقود!)
✅ إضافة كشف الانهيارات
✅ إضافة USE_DEVNET للتمييز بين التطوير والإنتاج
✅ إضافة جميع مفاتيح API والإعدادات الناقصة
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
# فلاتر الأمان (الاستراتيجية #1 - التوازن)
# ──────────────────────────────────────────────────────────────

# 🔥 تم تحديثه: 8% → 15% (استراتيجية التوازن)
MAX_DEV_WALLET_PCT = 15.0  # الحد الأقصى لأكبر محفظة

# فلاتر إضافية
MIN_POOL_SIZE_SOL = 50000.0  # الحد الأدنى للسيولة
MIN_POOL_SIZE_USD = 500000.0  # الحد الأدنى بالدولار
MAX_TOKEN_AGE_MINUTES = 5  # أقصى عمر للعملة (دقائق)
MIN_TX_COUNT = 10  # الحد الأدنى للمعاملات
BANNED_NAMES = ["USWR"]  # أسماء محظورة

# ──────────────────────────────────────────────────────────────
# معايير التداول
# ──────────────────────────────────────────────────────────────

CAPITAL_PER_TRADE_SOL = 0.05  # رأس المال لكل صفقة
MAX_TRADES_OPEN = 5  # الحد الأقصى للصفقات المفتوحة
TAKE_PROFIT_FIRST_PCT = 2.0  # هدف الربح الأول
STOP_LOSS_PCT = -30.0  # وقف الخسارة

# ──────────────────────────────────────────────────────────────
# المراقبة والخروج (محسّنة)
# ──────────────────────────────────────────────────────────────

# 🔥 تم تحديثه: 10 ثوانٍ → 0.5 ثانية (مراقبة سريعة جداً)
MONITOR_INTERVAL_SECONDS = 0.5  # فترة المراقبة

# كشف الانهيارات
CRASH_DETECTION_ENABLED = True  # تفعيل كشف الانهيارات
CRASH_THRESHOLD_PCT = -50.0  # انخفاض 50% = انهيار
LIQUIDITY_CRASH_PCT = -50.0  # انهيار السيولة

# ──────────────────────────────────────────────────────────────
# الإعدادات المتقدمة
# ──────────────────────────────────────────────────────────────

GAS_LIMIT = 1000000  # حد الـ Gas
SLIPPAGE_TOLERANCE_PCT = 10.0  # تفاوت الانزلاق
PRIORITY_FEE_LAMPORTS = 100000  # رسم الأولوية

BATCH_EXIT_ENABLED = True  # تفعيل البيع المتعدد الدفعات
BATCH_SIZES = [0.2, 0.3, 0.5]  # حجم الدفعات (نسب مئوية)

RETRY_ON_FAILURE = True  # إعادة المحاولة عند الفشل
MAX_RETRIES = 4  # أقصى عدد محاولات
RETRY_DELAY_SEC = 0.1  # تأخير إعادة المحاولة

# ──────────────────────────────────────────────────────────────
# التقارير والـ Logs
# ──────────────────────────────────────────────────────────────

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
ENABLE_DETAILED_LOGS = True  # logs مفصلة
DAILY_REPORT_TIME = "23:00"  # وقت التقرير اليومي

# ──────────────────────────────────────────────────────────────
# نمط التطوير مقابل الإنتاج
# ──────────────────────────────────────────────────────────────

USE_DEVNET = os.getenv("USE_DEVNET", "true").lower() == "true"

# ──────────────────────────────────────────────────────────────
# مفاتيح API والنقاط النهائية
# ──────────────────────────────────────────────────────────────

# RPC
PRIMARY_RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")

# APIs
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

# التنبيهات
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ──────────────────────────────────────────────────────────────
# استراتيجية الخروج والـ Watchlist
# ──────────────────────────────────────────────────────────────

# مسارات الانتظار
EXIT_STRATEGY = "multi_batch"  # أو "aggressive", "conservative"
WATCHLIST = True  # تفعيل قائمة الانتظار
FAST_TRACK = True  # تفعيل المسار السريع للعملات الجديدة

# مؤشرات الزخم (Momentum)
HOLDER_VELOCITY = 5  # عدد الحاملين الجدد في الدقيقة
SUSTAINED_TREND = 3  # عدد فترات المراقبة المتتالية برصيد إيجابي
GRADUATION_PROXIMITY = 0.8  # نسبة قرب التخرج من pump.fun

# معايير Safety Entry
RUGCHECK_MAX_SCORE = 5  # الحد الأقصى لـ rug check score
RUGCHECK_MAX_INSIDERS = 3  # الحد الأقصى للمطورين المشبوهين
ESTABLISHED_LIQUID = 100000.0  # السيولة المعتبرة "ثابتة" (USD)

# معايير GMGN
GMGN_MAX_RAT_TRADER_PCT = 10.0  # الحد الأقصى لنسبة المتاجرين الفئران
GMGN_MAX_BUNDLER_PCT = 5.0  # الحد الأقصى لنسبة المجمّعات
GMGN_MAX_RUG_RATIO = 0.15  # الحد الأقصى لنسبة الـ rug

# قائمة الحظر (Symbol Blocklist)
SYMBOL_BLOCKLIST_LOSS_THRESHOLD_PCT = -50.0  # خسارة 50% = حظر الرمز
SYMBOL_BLOCKLIST_MAX_OCCURRENCES = 3  # حظر بعد 3 مرات خسارة

# ──────────────────────────────────────────────────────────────
# حالة التطبيق
# ──────────────────────────────────────────────────────────────

# 📋 ملخص الإعدادات الحالية
TRADING_MODE = "PRODUCTION"  # أو SANDBOX
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
