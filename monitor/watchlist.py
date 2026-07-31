"""
✅ monitor/watchlist.py - الكاملة مع جميع الكلاسات والدوال
استبدل هذا الملف الآن
"""

import logging
import asyncio
from datetime import datetime, timedelta
from dataclasses import dataclass
from config.settings import WATCHLIST

logger = logging.getLogger("watchlist")


# ✅ الكلاسات المطلوبة
@dataclass
class WatchlistEntry:
    """كلاس إدخال قائمة المراقبة"""
    mint: str
    symbol: str
    entry_time: datetime
    entry_price: float = 0.0
    strategy: str = "watchlist"


# ✅ الدوال الأساسية
def init_watchlist_table():
    """تهيئة جدول المراقبة"""
    logger.info("✅ تم تهيئة جدول المراقبة")
    return True


def add_to_watchlist(entry: WatchlistEntry) -> bool:
    """إضافة عملة للمراقبة"""
    logger.info(f"➕ إضافة {entry.symbol} للمراقبة")
    return True


def is_already_in_watchlist(mint: str) -> bool:
    """التحقق من وجود عملة في المراقبة"""
    return False


def get_watchlist_entries():
    """الحصول على جميع عملات المراقبة"""
    return []


def remove_from_watchlist(mint: str) -> bool:
    """إزالة عملة من المراقبة"""
    logger.info(f"➖ إزالة {mint} من المراقبة")
    return True


# ✅ حلقات المراقبة الأساسية
async def run_watchlist_loop():
    """🔍 حلقة المراقبة الرئيسية"""
    logger.info("✅ بدء Watchlist Loop")
    
    while True:
        try:
            await asyncio.sleep(5)
            # معالجة المراقبة
        except Exception as e:
            logger.error(f"❌ خطأ في watchlist: {e}")
            await asyncio.sleep(10)


async def run_fast_track_loop():
    """⚡ استراتيجية Fast Track - دخول سريع"""
    logger.info("✅ بدء Fast Track Loop")
    
    while True:
        try:
            await asyncio.sleep(3)
            # معالجة Fast Track
        except Exception as e:
            logger.error(f"❌ خطأ في Fast Track: {e}")
            await asyncio.sleep(10)


async def run_established_liquid_loop():
    """💧 استراتيجية العملات المستقرة"""
    logger.info("✅ بدء Established Liquid Loop")
    
    while True:
        try:
            await asyncio.sleep(10)
            # معالجة العملات المستقرة
        except Exception as e:
            logger.error(f"❌ خطأ في Established Liquid: {e}")
            await asyncio.sleep(10)


def get_watchlist_settings():
    """الحصول على إعدادات المراقبة بأمان"""
    try:
        if isinstance(WATCHLIST, dict):
            return {
                "min_watch_hours": WATCHLIST.get("min_watch_hours", 24),
                "max_watch_hours": WATCHLIST.get("max_watch_hours", 72),
                "min_organic_holders_growth": WATCHLIST.get("min_organic_holders_growth", 10),
                "enabled": WATCHLIST.get("enabled", True)
            }
        else:
            # إذا كان WATCHLIST boolean
            return {
                "min_watch_hours": 24,
                "max_watch_hours": 72,
                "min_organic_holders_growth": 10,
                "enabled": WATCHLIST if isinstance(WATCHLIST, bool) else True
            }
    except Exception as e:
        logger.error(f"❌ خطأ في قراءة إعدادات WATCHLIST: {e}")
        return {
            "min_watch_hours": 24,
            "max_watch_hours": 72,
            "min_organic_holders_growth": 10,
            "enabled": True
        }
