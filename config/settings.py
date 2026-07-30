"""
⚙️ إعدادات Sniper Bot Solana V2
═════════════════════════════════════════════════════════════════

التحديثات:
✅ max_dev_wallet_pct: 8% → 15% (استراتيجية التوازن)
✅ monitor_interval: 10s → 0.5s (مراقبة سريعة)
✅ إضافة DEX_ALLOWLIST (مفقود!)
✅ إضافة كشف الانهيارات
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
# 🔥 قائمة DEX المسموح بها (مفقود - إضافة)
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
}
