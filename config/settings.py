"""
إعدادات البوت الكاملة والمصححة
تم تصحيح جميع المتغيرات المفقودة في FiltersConfig
"""
import os
from dataclasses import dataclass, field

# ✅ متغيرات البيئة
ALCHEMY_RPC_URL = os.getenv("ALCHEMY_RPC_URL", "https://solana-rpc.alchemy.com")
HELIUS_RPC_URL = os.getenv("HELIUS_RPC_URL", "https://mainnet.helius-rpc.com")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
WALLET_PRIVATE_KEY = os.getenv("WALLET_PRIVATE_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost/sniper_bot")
FALLBACK_DATABASE_URL = os.getenv("FALLBACK_DATABASE_URL", DATABASE_URL)
USE_DEVNET = os.getenv("USE_DEVNET", "false").lower() == "true"
GOPLUS_APP_KEY = os.getenv("GOPLUS_APP_KEY", "")
GOPLUS_APP_SECRET = os.getenv("GOPLUS_APP_SECRET", "")
TATUM_API_KEY = os.getenv("TATUM_API_KEY", "")
JUPITER_API_KEY = os.getenv("JUPITER_API_KEY", "")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# API URLs
GOPLUS_API_BASE = "https://api.gopluslabs.io/api/v1"
DEXSCREENER_API_BASE = "https://api.dexscreener.com/latest/dex"
BIRDEYE_API_BASE = "https://api.birdeye.so"
JUPITER_API_BASE = "https://api.jup.ag"
TATUM_SOLANA_RPC_URL = "https://api.mainnet.solana.com"

# RPC Endpoints (للتوازي والاحتياطي)
PRIMARY_RPC_URL = ALCHEMY_RPC_URL
SECONDARY_RPC_ENDPOINTS = [HELIUS_RPC_URL]
PRIMARY_WS_URL = "wss://mainnet.helius-rpc.com/?api-key=" + HELIUS_RPC_URL.split("?api-key=")[-1] if "?api-key=" in HELIUS_RPC_URL else "wss://api.mainnet.solana.com"
WS_ENDPOINTS = [PRIMARY_WS_URL]

# ✅ Monitoring Settings
RPC_ENDPOINTS = [ALCHEMY_RPC_URL, HELIUS_RPC_URL]

# DEX Allowlist
DEX_ALLOWLIST = ["pump.fun", "raydium", "orca", "marinade", "sanctum"]

# ✅ Filters Config (المجموعة الكاملة)
@dataclass
class FiltersConfig:
    """جميع متغيرات الفلاتر في مكان واحد"""
    
    # GoPlus / السمعة
    min_security_score: float = 40.0  # ✅ الحد الأدنى لدرجة الأمان من GoPlus
    max_allowed_prior_rugs: int = 2   # ✅ أقصى عدد rug pulls سابقة للمطور
    
    # Honeypot / محاكاة البيع
    max_allowed_sell_tax_pct: float = 10.0  # أقصى ضريبة بيع مقبولة (%)
    
    # On-chain Filters
    min_liquidity_usd: float = 1000.0  # الحد الأدنى للسيولة
    max_total_supply: float = 1_000_000_000.0  # أقصى إجمالي عرض
    min_holder_accounts: int = 10  # الحد الأدنى لعدد حاملي العملة
    max_dev_wallet_pct: float = 50.0  # أقصى نسبة تركيز في محفظة المطور
    
    # SHARIA Filter
    sharia_filters_enabled: bool = False
    forbidden_keywords: list = field(default_factory=lambda: [
        "scam", "rug", "fake", "honeypot", "exit", "dump", "exit_scam"
    ])

FILTERS = FiltersConfig()

# ✅ Watchlist Config
@dataclass
class WatchlistConfig:
    """إعدادات قائمة المراقبة"""
    check_interval_minutes: int = 15  # كل 15 دقيقة
    min_watch_hours: float = 24.0  # الحد الأدنى للانتظار (ساعات)
    max_watch_hours: float = 72.0  # الحد الأقصى للانتظار (ساعات)
    min_organic_holders_growth: int = 3  # الحد الأدنى لنمو الحاملين

WATCHLIST = WatchlistConfig()

# ✅ Fast-Track Config (للمسار السريع)
@dataclass
class FastTrackConfig:
    """إعدادات المسار السريع (رصد الانطلاق الصاروخي)"""
    enabled: bool = True
    check_interval_seconds: int = 30  # كل 30 ثانية
    max_entry_age_minutes: int = 60  # فقط عملات < 60 دقيقة

FAST_TRACK = FastTrackConfig()

# ✅ Exit Strategy Config
@dataclass
class ExitStrategyConfig:
    """استراتيجية الخروج من الصفقات"""
    max_capital_pct_per_trade: float = 5.0  # 5% من الرصيد لكل صفقة
    tp_target_pct: float = 15.0  # أهداف الربح (15%)
    sl_target_pct: float = -5.0  # وقف الخسارة (-5%)
    hold_time_minutes: int = 30  # أقصى وقت للاحتفاظ بالصفقة

EXIT_STRATEGY = ExitStrategyConfig()

# ✅ Post-Trade Monitoring Config
@dataclass
class PostTradeMonitorConfig:
    """مراقبة الصفقات بعد الشراء"""
    check_interval_seconds: int = 10
    max_hold_hours: int = 2

POST_TRADE_MONITOR = PostTradeMonitorConfig()

# ✅ Momentum Detection (للمسار السريع)
@dataclass
class MomentumConfig:
    """اكتشاف الزخم"""
    min_volume_1h_usd: float = 5000.0  # الحد الأدنى للحجم في الساعة الأخيرة
    min_price_increase_pct: float = 20.0  # الحد الأدنى للارتفاع (%)

MOMENTUM = MomentumConfig()

# ✅ Sharia Filter (اختياري)
SHARIA_FILTERS_ENABLED = os.getenv("SHARIA_FILTERS_ENABLED", "false").lower() == "true"

# ✅ Devnet Fallback
DEVNET_FALLBACK_CAPITAL_SOL = 1.0

# ✅ RPC Rate Limits
MAX_RPC_CALLS_PER_SECOND = 10
RPC_CALL_TIMEOUT_SECONDS = 30
