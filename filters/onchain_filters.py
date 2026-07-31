"""
🔍 فلاتر On-Chain
═════════════════════════════════════════════════════════════════
"""

import logging
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
# Data Classes
# ──────────────────────────────────────────────────────────────

@dataclass
class TokenMetadata:
    """بيانات التوكن"""
    mint_address: str
    symbol: str
    name: str
    decimals: int = 6
    supply: float = 0
    dev_wallet: str = ""
    dev_wallet_pct: float = 0
    pool_size_sol: float = 0
    pool_size_usd: float = 0
    age_minutes: float = 0
    tx_count: int = 0
    holders_count: int = 0


# ──────────────────────────────────────────────────────────────
# Filter Functions
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


def apply_all_filters(
    symbol: str,
    dev_wallet_pct: float,
    pool_size_sol: float,
    pool_size_usd: float = None,
    age_minutes: float = 0,
    tx_count: int = 0,
) -> Tuple[bool, Dict]:
    """تطبيق جميع الفلاتر"""
    
    filters_results = {}
    
    # 1. فلتر الاسم المحظور
    passed, msg = filter_by_banned_names(symbol)
    filters_results["banned_name"] = msg
    if not passed:
        return False, filters_results
    
    # 2. فلتر محفظة المطور
    passed, msg = filter_by_dev_wallet(dev_wallet_pct)
    filters_results["dev_wallet"] = msg
    if not passed:
        return False, filters_results
    
    # 3. فلتر حجم السيولة
    passed, msg = filter_by_pool_size(pool_size_sol, pool_size_usd)
    filters_results["pool_size"] = msg
    if not passed:
        return False, filters_results
    
    # 4. فلتر عمر التوكن
    passed, msg = filter_by_token_age(age_minutes)
    filters_results["token_age"] = msg
    if not passed:
        return False, filters_results
    
    # 5. فلتر عدد المعاملات
    passed, msg = filter_by_tx_count(tx_count)
    filters_results["tx_count"] = msg
    if not passed:
        return False, filters_results
    
    return True, filters_results
