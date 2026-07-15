import os
from dataclasses import dataclass, field

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
BIRDEYE_API_KEY = os.getenv("BIRDEYE_API_KEY", "")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

GOPLUS_API_BASE = "https://api.gopluslabs.io/api/v1"
DEXSCREENER_API_BASE = "https://api.dexscreener.com/latest/dex"
BIRDEYE_API_BASE = "https://api.birdeye.so"
JUPITER_API_BASE = "https://api.jup.ag"
TATUM_SOLANA_RPC_URL = "https://api.mainnet.solana.com"

PRIMARY_RPC_URL = ALCHEMY_RPC_URL
SECONDARY_RPC_ENDPOINTS = [HELIUS_RPC_URL, "https://api.mainnet.solana.com"]
RPC_ENDPOINTS = [ALCHEMY_RPC_URL, HELIUS_RPC_URL, "https://api.mainnet.solana.com"]

DEX_ALLOWLIST = ["pump.fun", "raydium", "orca", "marinade", "sanctum"]

@dataclass
class FiltersConfig:
    min_security_score: float = 25.0
    max_allowed_prior_rugs: int = 3
    max_dev_wallet_pct: float = 60.0
    max_single_holder_pct: float = 40.0
    min_lp_burned_or_locked_pct: float = 0.0
    require_fixed_supply: bool = False
    require_burn_or_lock: bool = False
    require_standard_token_program: bool = True
    forbid_transfer_restrictions: bool = False
    forbid_referral_mechanics: bool = False
    forbidden_keywords: list = field(default_factory=lambda: [
        "scam", "rug"
    ])

FILTERS = FiltersConfig()

@dataclass
class WatchlistConfig:
    check_interval_minutes: int = 2
    min_watch_hours: float = 0.5
    max_watch_hours: float = 24.0
    min_organic_holders_growth: int = 0

WATCHLIST = WatchlistConfig()

@dataclass
class FastTrackConfig:
    enabled: bool = True
    check_interval_seconds: int = 20
    max_entry_age_minutes: int = 60

FAST_TRACK = FastTrackConfig()

@dataclass
class ExitStrategyConfig:
    max_capital_pct_per_trade: float = 3.0
    trailing_stop_pct: float = 25.0
    max_drawdown_from_entry_pct: float = 8.0
    max_slippage_pct: float = 3.0
    emergency_slippage_pct: float = 5.0

EXIT_STRATEGY = ExitStrategyConfig()

@dataclass
class PostTradeMonitorConfig:
    check_interval_seconds: int = 5
    onchain_check_interval_seconds: int = 5
    external_check_interval_minutes: int = 60
    auto_close_on_ownership_change: bool = True
    auto_close_on_tax_increase_above_pct: float = 15.0

POST_TRADE_MONITOR = PostTradeMonitorConfig()

@dataclass
class MomentumConfig:
    min_volume_m5_usd: float = 500.0
    min_price_change_m5_pct: float = 5.0
    min_liquidity_usd: float = 100.0
    min_unique_buys_m5: int = 1
    min_buy_sell_ratio_m5: float = 0.2

MOMENTUM = MomentumConfig()

SHARIA_FILTERS_ENABLED = os.getenv("SHARIA_FILTERS_ENABLED", "false").lower() == "true"
DEVNET_FALLBACK_CAPITAL_SOL = 1.0
MAX_RPC_CALLS_PER_SECOND = 5
RPC_CALL_TIMEOUT_SECONDS = 30
