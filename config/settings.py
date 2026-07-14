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
SECONDARY_RPC_ENDPOINTS = [HELIUS_RPC_URL]
PRIMARY_WS_URL = "wss://mainnet.helius-rpc.com/?api-key=your-key"
WS_ENDPOINTS = [PRIMARY_WS_URL]
RPC_ENDPOINTS = [ALCHEMY_RPC_URL, HELIUS_RPC_URL]

DEX_ALLOWLIST = ["pump.fun", "raydium", "orca", "marinade", "sanctum"]

@dataclass
class FiltersConfig:
    min_security_score: float = 40.0
    max_allowed_prior_rugs: int = 2
    max_allowed_sell_tax_pct: float = 10.0
    min_liquidity_usd: float = 1000.0
    max_total_supply: float = 1_000_000_000.0
    min_holder_accounts: int = 10
    max_dev_wallet_pct: float = 50.0
    require_fixed_supply: bool = True
    sharia_filters_enabled: bool = False
    forbidden_keywords: list = field(default_factory=lambda: [
        "scam", "rug", "fake", "honeypot", "exit", "dump", "exit_scam"
    ])

FILTERS = FiltersConfig()

@dataclass
class WatchlistConfig:
    check_interval_minutes: int = 15
    min_watch_hours: float = 24.0
    max_watch_hours: float = 72.0
    min_organic_holders_growth: int = 3

WATCHLIST = WatchlistConfig()

@dataclass
class FastTrackConfig:
    enabled: bool = True
    check_interval_seconds: int = 30
    max_entry_age_minutes: int = 60

FAST_TRACK = FastTrackConfig()

@dataclass
class ExitStrategyConfig:
    max_capital_pct_per_trade: float = 5.0
    tp_target_pct: float = 15.0
    sl_target_pct: float = -5.0
    hold_time_minutes: int = 30

EXIT_STRATEGY = ExitStrategyConfig()

@dataclass
class PostTradeMonitorConfig:
    check_interval_seconds: int = 10
    max_hold_hours: int = 2

POST_TRADE_MONITOR = PostTradeMonitorConfig()

@dataclass
class MomentumConfig:
    min_volume_1h_usd: float = 5000.0
    min_price_increase_pct: float = 20.0

MOMENTUM = MomentumConfig()

SHARIA_FILTERS_ENABLED = os.getenv("SHARIA_FILTERS_ENABLED", "false").lower() == "true"
DEVNET_FALLBACK_CAPITAL_SOL = 1.0
MAX_RPC_CALLS_PER_SECOND = 10
RPC_CALL_TIMEOUT_SECONDS = 30
