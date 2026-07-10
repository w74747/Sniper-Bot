"""
الإعدادات المركزية للبوت.
كل الأرقام والعتبات (Thresholds) هنا قابلة للتعديل بدون لمس منطق الكود في باقي الملفات.
"""
import os
from dataclasses import dataclass, field
from typing import List

# ── مفاتيح API (تُقرأ من متغيرات البيئة .env — لا تضع مفاتيح حقيقية هنا مباشرة) ──
ALCHEMY_API_KEY = os.getenv("ALCHEMY_API_KEY", "")
ALCHEMY_RPC_URL = f"https://solana-mainnet.g.alchemy.com/v2/{ALCHEMY_API_KEY}"
ALCHEMY_WS_URL = f"wss://solana-mainnet.g.alchemy.com/v2/{ALCHEMY_API_KEY}"

GOPLUS_APP_KEY = os.getenv("GOPLUS_APP_KEY", "").strip()
GOPLUS_APP_SECRET = os.getenv("GOPLUS_APP_SECRET", "").strip()
GOPLUS_API_BASE = "https://api.gopluslabs.io/api/v1"

HELIUS_API_KEY = os.getenv("HELIUS_API_KEY", "").strip()
HELIUS_RPC_URL = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
HELIUS_WS_URL = f"wss://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"

JUPITER_API_KEY = os.getenv("JUPITER_API_KEY", "")
JUPITER_API_BASE = "https://api.jup.ag"

# Birdeye: مصدر احتياطي جزئي (سعر فقط، فريتيره المجاني لا يشمل حجم/شراء-بيع)
# معطّل حالياً بانتظار تفعيله لاحقاً بعد تحقيق إيرادات — اتركه فارغاً
BIRDEYE_API_KEY = os.getenv("BIRDEYE_API_KEY", "").strip()
BIRDEYE_API_BASE = "https://public-api.birdeye.so"

# DexScreener: المصدر الأساسي لبيانات الزخم — مجاني بالكامل بدون مفتاح
DEXSCREENER_API_BASE = "https://api.dexscreener.com"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

WALLET_PRIVATE_KEY = os.getenv("WALLET_PRIVATE_KEY", "")
USE_DEVNET = os.getenv("USE_DEVNET", "true").lower() == "true"


@dataclass
class FilterThresholds:
    """عتبات الفلترة عند اللحظة صفر (فلاتر آلية فورية قابلة للقياس)."""

    require_fixed_supply: bool = True
    require_burn_or_lock: bool = True
    min_lp_burned_or_locked_pct: float = 95.0

    max_dev_wallet_pct: float = 8.0
    max_single_holder_pct: float = 8.0
    forbid_referral_mechanics: bool = True

    require_standard_token_program: bool = True
    forbid_transfer_restrictions: bool = True

    check_deployer_history: bool = True
    max_allowed_prior_rugs: int = 0

    min_security_score: float = 70.0

    forbidden_keywords: List[str] = field(default_factory=lambda: [
        "casino", "bet", "gambling", "dice", "roll", "slot", "lottery",
        "yield farm", "lending", "interest", "apr", "apy",
        "porn", "xxx", "nsfw",
    ])


@dataclass
class WatchlistSettings:
    """إعدادات مرحلة الانتظار والمراجعة بعد الفلترة الآلية (24-72 ساعة)."""

    min_watch_hours: int = 24
    max_watch_hours: int = 72
    min_organic_holders_growth: int = 50
    check_interval_minutes: int = 15


@dataclass
class ExitStrategySettings:
    """إعدادات إدارة الصفقة بعد الدخول."""

    take_profit_first_leg_pct: float = 100.0
    trailing_stop_pct: float = 15.0
    max_slippage_pct: float = 5.0
    emergency_slippage_pct: float = 20.0

    max_capital_pct_per_trade: float = 2.0
    max_consecutive_losses: int = 5
    circuit_breaker_cooldown_minutes: int = 120


@dataclass
class MomentumSettings:
    """
    عتبات رصد "الانطلاق الصاروخي" في أول دقائق — منفصلة تماماً عن فلاتر
    الأمان (GoPlus) وفلاتر watchlist طويلة الأمد. هذه تجيب سؤالاً مختلفاً:
    "هل هذه العملة تتحرك بقوة الآن؟" وليس "هل هي آمنة تقنياً؟".
    """
    min_price_change_m5_pct: float = 30.0
    min_buy_sell_ratio_m5: float = 2.0
    min_volume_m5_usd: float = 5000.0
    min_unique_buys_m5: int = 20
    min_liquidity_usd: float = 3000.0


MOMENTUM = MomentumSettings()


@dataclass
class PostTradeMonitorSettings:
    """إعدادات المراقبة بعد الدخول (الطبقتان: on-chain آلية + خارجية دورية)."""

    onchain_check_interval_seconds: int = 5
    external_check_interval_minutes: int = 60

    auto_close_on_tax_increase_above_pct: float = 15.0
    auto_close_on_lp_withdrawal: bool = True
    auto_close_on_ownership_change: bool = True

    alert_only_on_external_signal: bool = True


FILTERS = FilterThresholds()
WATCHLIST = WatchlistSettings()
EXIT_STRATEGY = ExitStrategySettings()
POST_TRADE_MONITOR = PostTradeMonitorSettings()

NETWORK = "solana"
DEX_ALLOWLIST = ["raydium", "pump.fun", "orca"]
