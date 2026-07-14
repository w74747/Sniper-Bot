"""
⚙️ إعدادات البوت الكاملة - Solana Sniper Bot
مركزي شامل لكل المتغيرات والتكوينات
"""

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

# ═══════════════════════════════════════════════════════════════════════════════
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://user:password@localhost:5432/sniper_db"
)

FALLBACK_DATABASE_URL = os.getenv(
    "FALLBACK_DATABASE_URL",
    "postgresql://user:password@neon.tech/sniper_db"
)

# ═══════════════════════════════════════════════════════════════════════════════
WALLET_PRIVATE_KEY = os.getenv("WALLET_PRIVATE_KEY", "")

USE_DEVNET = os.getenv("USE_DEVNET", "false").lower() == "true"

# ═══════════════════════════════════════════════════════════════════════════════
PRIMARY_RPC_URL = "https://api.mainnet-beta.solana.com"

RPC_ENDPOINTS = [
    "https://api.mainnet-beta.solana.com",
    "https://solana-rpc.publicnode.com",
    os.getenv("ALCHEMY_RPC_URL", "https://solana-mainnet.g.alchemy.com/v2/demo"),
    os.getenv("QUICKNODE_RPC_URL", "https://empty-cool-moon.solana-mainnet.quiknode.pro/"),
    os.getenv("DRPC_RPC_URL", "https://solana-mainnet.core.chainstack.com/"),
    os.getenv("HELIUS_RPC_URL", "https://mainnet.helius-rpc.com/"),
]

SECONDARY_RPC_ENDPOINTS = [
    os.getenv("HELIUS_RPC_URL", "https://mainnet.helius-rpc.com/"),
    os.getenv("TATUM_RPC_URL", "https://solana-mainnet.tatum.io/"),
]

ALCHEMY_RPC_URL = os.getenv("ALCHEMY_RPC_URL", "https://solana-mainnet.g.alchemy.com/v2/demo")

# ═══════════════════════════════════════════════════════════════════════════════
GOPLUS_APP_KEY = os.getenv("GOPLUS_APP_KEY", "")
GOPLUS_APP_SECRET = os.getenv("GOPLUS_APP_SECRET", "")
GOPLUS_API_BASE = os.getenv("GOPLUS_API_BASE", "https://api.gopluslabs.io")

TATUM_API_KEY = os.getenv("TATUM_API_KEY", "")
TATUM_API_BASE = os.getenv("TATUM_API_BASE", "https://api.tatum.io")
TATUM_RPC_URL = os.getenv("TATUM_RPC_URL", "https://solana-mainnet.tatum.io/")
TATUM_SOLANA_RPC_URL = os.getenv("TATUM_SOLANA_RPC_URL", "https://solana-mainnet.tatum.io/")

JUPITER_API_KEY = os.getenv("JUPITER_API_KEY", "")
JUPITER_API_BASE = os.getenv("JUPITER_API_BASE", "https://quote-api.jup.ag/v6")

DEXSCREENER_API_KEY = os.getenv("DEXSCREENER_API_KEY", "")
DEXSCREENER_API_BASE = os.getenv("DEXSCREENER_API_BASE", "https://api.dexscreener.com/latest/dex")

BIRDEYE_API_KEY = os.getenv("BIRDEYE_API_KEY", "")
BIRDEYE_API_BASE = os.getenv("BIRDEYE_API_BASE", "https://public-api.birdeye.so")

# ═══════════════════════════════════════════════════════════════════════════════
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ═══════════════════════════════════════════════════════════════════════════════
@dataclass
class WatchlistConfig:
    """إعدادات قائمة المراقبة"""
    min_watch_hours: int = 24
    max_watch_hours: int = 72
    min_organic_holders_growth: int = 8
    check_interval_minutes: int = 15


WATCHLIST = WatchlistConfig(
    min_watch_hours=24,
    max_watch_hours=72,
    min_organic_holders_growth=8,
    check_interval_minutes=15
)

# ═══════════════════════════════════════════════════════════════════════════════
@dataclass
class FastTrackConfig:
    """إعدادات المسار السريع"""
    enabled: bool = True
    max_entry_age_minutes: int = 60
    check_interval_seconds: int = 30
    min_momentum_pct: float = 15.0
    min_volume_usdc: float = 2000.0


FAST_TRACK = FastTrackConfig(
    enabled=True,
    max_entry_age_minutes=60,
    check_interval_seconds=30,
    min_momentum_pct=15.0,
    min_volume_usdc=2000.0
)

# ═══════════════════════════════════════════════════════════════════════════════
@dataclass
class ExitStrategyConfig:
    """إعدادات الخروج من الصفقات"""
    max_capital_pct_per_trade: float = 10.0
    take_profit_pct: float = 25.0
    stop_loss_pct: float = 15.0
    trailing_stop_pct: float = 15.0
    max_cumulative_loss_pct: float = 30.0


EXIT_STRATEGY = ExitStrategyConfig(
    max_capital_pct_per_trade=10.0,
    take_profit_pct=25.0,
    stop_loss_pct=15.0,
    trailing_stop_pct=15.0,
    max_cumulative_loss_pct=30.0
)

# ═══════════════════════════════════════════════════════════════════════════════
SHARIA_FILTERS_ENABLED = os.getenv("SHARIA_FILTERS_ENABLED", "true").lower() == "true"

BANNED_KEYWORDS = [
    "rug", "scam", "hack", "steal", "exit", "dump",
    "ايرب", "مفاجأة", "خصم", "ضمان", "أرباح مضمونة"
]

MIN_GOPLUS_SCORE = 70
MAX_DEPLOYER_OWNERSHIP_PCT = 8.0
MAX_SINGLE_HOLDER_PCT = 8.0
MIN_LP_BURN_PCT = 95.0

# ═══════════════════════════════════════════════════════════════════════════════
@dataclass
class FiltersConfig:
    """إعدادات الفلاتر المتقدمة"""
    enabled: bool = True
    min_liquidity_usdc: float = 1000.0
    max_deployer_wallet_pct: float = 8.0
    min_holders: int = 10


FILTERS = FiltersConfig(
    enabled=True,
    min_liquidity_usdc=1000.0,
    max_deployer_wallet_pct=8.0,
    min_holders=10
)

# ═══════════════════════════════════════════════════════════════════════════════
@dataclass
class MomentumConfig:
    """إعدادات فحص الزخم"""
    enabled: bool = True
    min_price_change_pct: float = 15.0
    min_volume_change_pct: float = 50.0
    check_interval_seconds: int = 30


MOMENTUM = MomentumConfig(
    enabled=True,
    min_price_change_pct=15.0,
    min_volume_change_pct=50.0,
    check_interval_seconds=30
)

# ═══════════════════════════════════════════════════════════════════════════════
CACHE_TTL_NEW_TOKEN = 600
CACHE_TTL_OLD_TOKEN = 3600
CACHE_TTL_TRANSACTIONS = 86400

# ═══════════════════════════════════════════════════════════════════════════════
MAX_RETRIES_NEW_TOKEN = 6
MAX_RETRIES_OLD_TOKEN = 1
MAX_RETRIES_TRANSACTION = 8
RETRY_DELAY_BASE = 0.8

# ═══════════════════════════════════════════════════════════════════════════════
RPC_TIMEOUT = 20
BUY_TIMEOUT = 30
SELL_TIMEOUT = 30

# ═══════════════════════════════════════════════════════════════════════════════
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE_SIZE = 50
LOG_FILES_BACKUP = 5

# ═══════════════════════════════════════════════════════════════════════════════
SOLANA_NETWORK = "mainnet-beta" if not USE_DEVNET else "devnet"
COMMITMENT_LEVEL = "confirmed"

# ═══════════════════════════════════════════════════════════════════════════════
SUPPORTED_POOL_TYPES = ["raydium", "orca", "pump"]

# ═══════════════════════════════════════════════════════════════════════════════
@dataclass
class PostTradeMonitorConfig:
    """إعدادات مراقبة الصفقات بعد الشراء"""
    check_interval_seconds: int = 30
    max_hold_hours: int = 24


POST_TRADE_MONITOR = PostTradeMonitorConfig(
    check_interval_seconds=30,
    max_hold_hours=24
)

# ═══════════════════════════════════════════════════════════════════════════════
MEMPOOL_CHECK_INTERVAL_SECONDS = 5
MEMPOOL_MAX_CONCURRENT_SCREENS = 3

# ═══════════════════════════════════════════════════════════════════════════════
def validate_settings() -> bool:
    """التحقق من صحة الإعدادات"""
    errors = []
    
    if not WALLET_PRIVATE_KEY and not USE_DEVNET:
        errors.append("❌ WALLET_PRIVATE_KEY غير محدد!")
    
    if not TELEGRAM_BOT_TOKEN:
        errors.append("⚠️ TELEGRAM_BOT_TOKEN غير محدد (التنبيهات معطّلة)")
    
    if not RPC_ENDPOINTS:
        errors.append("❌ لا توجد مزودات RPC!")
    
    if errors:
        print("\n".join(errors))
        return False
    
    print("✅ جميع الإعدادات صحيحة!")
    return True


# ═══════════════════════════════════════════════════════════════════════════════
BOT_NAME = "Solana Sniper Bot"
BOT_VERSION = "2.0.0"
BOT_DESCRIPTION = "بوت ذكي لاكتشاف واستهداف العملات الجديدة على Solana"

# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print(f"\n{BOT_NAME} v{BOT_VERSION}")
    print("="*60)
    validate_settings()
    print(f"\n📊 عدد مزودات RPC المتاحة: {len(RPC_ENDPOINTS)}")
    print(f"🌐 الشبكة: {SOLANA_NETWORK}")
    print(f"💰 رأس المال لكل صفقة: {EXIT_STRATEGY.max_capital_pct_per_trade}%")
    print(f"🎯 هدف الربح: {EXIT_STRATEGY.take_profit_pct}%")
    print(f"⏱️ وقف الخسارة: {EXIT_STRATEGY.stop_loss_pct}%")
