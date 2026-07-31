"""
🔍 فلاتر On-Chain
═════════════════════════════════════════════════════════════════
"""

import logging
import struct
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from config.settings import (
    MAX_DEV_WALLET_PCT,
    MIN_POOL_SIZE_SOL,
    MIN_POOL_SIZE_USD,
    MAX_TOKEN_AGE_MINUTES,
    MIN_TX_COUNT,
    BANNED_NAMES,
)

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# عناوين الحرق المعروفة
# ──────────────────────────────────────────────────────────────

KNOWN_BURN_ADDRESSES = {
    "11111111111111111111111111111111",
    "11111111111111111111111111111112",
    "zzjjjjjjjjjjjjjjjjjjjjjjjjjjjjjj",
    "DeadDeadDeadDeadDeadDeadDeadDeadDeadDeadDeadDeadDeadDead1111",
}

# ──────────────────────────────────────────────────────────────
# Data Classes
# ──────────────────────────────────────────────────────────────

@dataclass
class TokenMetadata:
    """بيانات التوكن"""
    mint_address: str
    symbol: str
    name: str = ""
    decimals: int = 6
    supply: float = 0
    dev_wallet: str = ""
    dev_wallet_pct: float = 0
    pool_size_sol: float = 0
    pool_size_usd: float = 0
    age_minutes: float = 0
    tx_count: int = 0
    holders_count: int = 0
    mint_authority_active: bool = False
    freeze_authority_active: bool = False
    lp_burned_or_locked_pct: float = 0.0
    top_holder_pct_excluding_lp: float = 0.0
    is_standard_spl_token: bool = True
    has_transfer_restriction_hooks: bool = False
    has_referral_or_commission_function: bool = False


@dataclass
class FilterResult:
    """نتيجة تطبيق الفلاتر"""
    passed: bool
    reason: str
    details: Dict = None

    def __post_init__(self):
        if self.details is None:
            self.details = {}


# ──────────────────────────────────────────────────────────────
# دوال فك التشفير
# ──────────────────────────────────────────────────────────────

def parse_spl_mint_account(data_b64: str) -> Dict:
    """فك تشفير حساب Mint من base64"""
    try:
        import base64
        data = base64.b64decode(data_b64)
        
        if len(data) < 82:
            return {
                "mint_authority_active": False,
                "freeze_authority_active": False,
                "supply": 0,
                "decimals": 0,
            }
        
        decimals = data[44] if len(data) > 44 else 6
        
        if len(data) >= 44:
            supply = struct.unpack('<Q', data[36:44])[0]
        else:
            supply = 0
        
        mint_authority = data[0:32]
        mint_authority_active = not all(b == 0 for b in mint_authority)
        
        freeze_authority = data[46:78] if len(data) >= 78 else bytes(32)
        freeze_authority_active = not all(b == 0 for b in freeze_authority)
        
        return {
            "mint_authority_active": mint_authority_active,
            "freeze_authority_active": freeze_authority_active,
            "supply": supply,
            "decimals": decimals,
        }
    except Exception as e:
        logger.error(f"خطأ في فك تشفير Mint Account: {e}")
        return {
            "mint_authority_active": False,
            "freeze_authority_active": False,
            "supply": 0,
            "decimals": 6,
        }


# ──────────────────────────────────────────────────────────────
# دوال الفلترة الفردية
# ──────────────────────────────────────────────────────────────

def filter_by_dev_wallet(dev_wallet_pct: float) -> Tuple[bool, str]:
    """فلتر محفظة المطور"""
    if dev_wallet_pct > MAX_DEV_WALLET_PCT:
        return False, f"محفظة المطور عالية جداً: {dev_wallet_pct:.1f}% (الحد الأقصى: {MAX_DEV_WALLET_PCT}%)"
    return True, f"محفظة المطور: {dev_wallet_pct:.1f}% ✅"


def filter_by_pool_size(pool_size_sol: float, pool_size_usd: float = None) -> Tuple[bool, str]:
    """فلتر حجم السيولة"""
    if pool_size_sol < MIN_POOL_SIZE_SOL:
        return False, f"حجم السيولة منخفض: {pool_size_sol:.0f} SOL (الحد الأدنى: {MIN_POOL_SIZE_SOL:.0f})"
    
    if pool_size_usd is not None and pool_size_usd < MIN_POOL_SIZE_USD:
        return False, f"حجم السيولة منخفض: ${pool_size_usd:.0f} (الحد الأدنى: ${MIN_POOL_SIZE_USD:.0f})"
    
    return True, f"حجم السيولة: {pool_size_sol:.0f} SOL ✅"


def filter_by_token_age(age_minutes: float) -> Tuple[bool, str]:
    """فلتر عمر التوكن"""
    if age_minutes > MAX_TOKEN_AGE_MINUTES:
        return False, f"التوكن قديم جداً: {age_minutes:.1f} دقيقة (الحد الأقصى: {MAX_TOKEN_AGE_MINUTES})"
    return True, f"عمر التوكن: {age_minutes:.1f} دقيقة ✅"


def filter_by_tx_count(tx_count: int) -> Tuple[bool, str]:
    """فلتر عدد المعاملات"""
    if tx_count < MIN_TX_COUNT:
        return False, f"عدد المعاملات منخفض: {tx_count} (الحد الأدنى: {MIN_TX_COUNT})"
    return True, f"عدد المعاملات: {tx_count} ✅"


def filter_by_banned_names(symbol: str) -> Tuple[bool, str]:
    """فلتر الأسماء المحظورة"""
    if symbol.upper() in [name.upper() for name in BANNED_NAMES]:
        return False, f"اسم محظور: {symbol}"
    return True, f"الاسم مسموح: {symbol} ✅"


def filter_by_mint_authority(mint_authority_active: bool) -> Tuple[bool, str]:
    """فلتر: يجب أن تكون mint authority معطلة"""
    if mint_authority_active:
        return False, "❌ mint authority مفعلة (يمكن طبع عملات جديدة)"
    return True, "✅ mint authority معطلة"


def filter_by_freeze_authority(freeze_authority_active: bool) -> Tuple[bool, str]:
    """فلتر: freeze authority يجب أن تكون معطلة"""
    if freeze_authority_active:
        return False, "⚠️  freeze authority مفعلة (خطر: يمكن تجميد الحسابات)"
    return True, "✅ freeze authority معطلة"


# ──────────────────────────────────────────────────────────────
# تطبيق جميع الفلاتر
# ──────────────────────────────────────────────────────────────

def run_all_onchain_filters(meta: TokenMetadata) -> FilterResult:
    """تطبيق جميع فلاتر on-chain على metadata التوكن"""
    
    details = {}
    
    # 1. فلتر الاسم المحظور
    passed, msg = filter_by_banned_names(meta.symbol)
    details["banned_name"] = msg
    if not passed:
        return FilterResult(False, msg, details)
    
    # 2. فلتر محفظة المطور
    passed, msg = filter_by_dev_wallet(meta.dev_wallet_pct)
    details["dev_wallet"] = msg
    if not passed:
        return FilterResult(False, msg, details)
    
    # 3. فلتر حجم السيولة
    passed, msg = filter_by_pool_size(meta.pool_size_sol, meta.pool_size_usd)
    details["pool_size"] = msg
    if not passed:
        return FilterResult(False, msg, details)
    
    # 4. فلتر عمر التوكن
    passed, msg = filter_by_token_age(meta.age_minutes)
    details["token_age"] = msg
    if not passed:
        return FilterResult(False, msg, details)
    
    # 5. فلتر عدد المعاملات
    passed, msg = filter_by_tx_count(meta.tx_count)
    details["tx_count"] = msg
    if not passed:
        return FilterResult(False, msg, details)
    
    # 6. فلتر Mint Authority
    passed, msg = filter_by_mint_authority(meta.mint_authority_active)
    details["mint_authority"] = msg
    if not passed:
        return FilterResult(False, msg, details)
    
    # 7. فلتر Freeze Authority
    passed, msg = filter_by_freeze_authority(meta.freeze_authority_active)
    details["freeze_authority"] = msg
    if not passed:
        return FilterResult(False, msg, details)
    
    # جميع الفلاتر اجتازت
    success_msg = "✅ اجتاز جميع فلاتر on-chain"
    return FilterResult(True, success_msg, details)


# للتوافق مع الكود القديم
def apply_all_filters(
    symbol: str,
    dev_wallet_pct: float,
    pool_size_sol: float,
    pool_size_usd: float = None,
    age_minutes: float = 0,
    tx_count: int = 0,
) -> Tuple[bool, Dict]:
    """نسخة قديمة للتوافقية"""
    
    meta = TokenMetadata(
        mint_address="",
        symbol=symbol,
        dev_wallet_pct=dev_wallet_pct,
        pool_size_sol=pool_size_sol,
        pool_size_usd=pool_size_usd,
        age_minutes=age_minutes,
        tx_count=tx_count,
    )
    
    result = run_all_onchain_filters(meta)
    return result.passed, result.details
