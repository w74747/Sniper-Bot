"""
✅ watchlist.py - إدارة قائمة المراقبة
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List

logger = logging.getLogger("watchlist")

# ✅ تعريف WATCHLIST هنا - بدلاً من استيراده
WATCHLIST: Dict = {}

@dataclass
class WatchlistEntry:
    """عنصر في قائمة المراقبة"""
    mint_address: str
    symbol: str
    entry_timestamp: str
    pool_size_usd: float
    dev_wallet_pct: float
    transaction_count: int
    first_seen: str


async def init_watchlist_table():
    """تهيئة جدول قائمة المراقبة"""
    logger.info("✅ تهيئة جدول قائمة المراقبة")


async def add_to_watchlist(entry: WatchlistEntry):
    """إضافة عنصر لقائمة المراقبة"""
    global WATCHLIST
    WATCHLIST[entry.mint_address] = {
        "symbol": entry.symbol,
        "entry_timestamp": entry.entry_timestamp,
        "pool_size_usd": entry.pool_size_usd,
        "dev_wallet_pct": entry.dev_wallet_pct,
        "transaction_count": entry.transaction_count,
        "first_seen": entry.first_seen,
    }
    logger.info(f"✅ أضيفت عملة للمراقبة: {entry.symbol} ({entry.mint_address})")


async def is_already_in_watchlist(mint_address: str) -> bool:
    """التحقق من وجود عملة في قائمة المراقبة"""
    global WATCHLIST
    return mint_address in WATCHLIST


async def get_watchlist_entries() -> List[Dict]:
    """الحصول على جميع عناصر قائمة المراقبة"""
    global WATCHLIST
    return list(WATCHLIST.values())


async def remove_from_watchlist(mint_address: str):
    """إزالة عملة من قائمة المراقبة"""
    global WATCHLIST
    if mint_address in WATCHLIST:
        del WATCHLIST[mint_address]
        logger.info(f"✅ تمت إزالة {mint_address} من قائمة المراقبة")


def get_watchlist_settings() -> Dict:
    """الحصول على إعدادات قائمة المراقبة"""
    return {
        "min_watch_hours": 0.5,
        "max_watch_hours": 24,
        "auto_remove_closed": True,
    }


async def run_watchlist_loop():
    """حلقة مراقبة العملات - المسار الكلاسيكي"""
    logger.info("✅ بدء Watchlist Loop")
    await init_watchlist_table()
    
    while True:
        try:
            entries = await get_watchlist_entries()
            logger.debug(f"📊 العملات المراقبة: {len(entries)}")
            await asyncio.sleep(2)
        except Exception as e:
            logger.error(f"❌ خطأ في Watchlist Loop: {e}")
            await asyncio.sleep(5)


async def run_fast_track_loop():
    """حلقة المسار السريع"""
    logger.info("✅ بدء Fast Track Loop")
    
    while True:
        try:
            logger.debug("🚀 تقييم عملات المسار السريع...")
            await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"❌ خطأ في Fast Track Loop: {e}")
            await asyncio.sleep(5)


async def run_established_liquid_loop():
    """حلقة العملات المستقرة السائلة"""
    logger.info("✅ بدء Established Liquid Loop")
    
    while True:
        try:
            logger.debug("💧 تقييم العملات المستقرة...")
            await asyncio.sleep(3)
        except Exception as e:
            logger.error(f"❌ خطأ في Established Liquid Loop: {e}")
            await asyncio.sleep(5)
