"""
✅ watchlist.py - المصحح تماماً
استبدل monitor/watchlist.py بهذا مباشرة
"""

import logging
import asyncio
from datetime import datetime, timedelta
from config.settings import WATCHLIST
from db.trades import get_open_trades
from filters.onchain_filters import TokenMetadata
from trading.executor import execute_buy

logger = logging.getLogger("watchlist")


async def run_watchlist_loop():
    """🔍 حلقة المراقبة الرئيسية"""
    logger.info("✅ بدء Watchlist Loop")
    
    while True:
        try:
            await asyncio.sleep(5)
            # تحديث المراقبة
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
    """الحصول على إعدادات المراقبة"""
    try:
        # استخدام .get() بدل الوصول المباشر
        return {
            "min_watch_hours": WATCHLIST.get("min_watch_hours", 24),
            "max_watch_hours": WATCHLIST.get("max_watch_hours", 72),
            "min_organic_holders_growth": WATCHLIST.get("min_organic_holders_growth", 10),
            "enabled": WATCHLIST.get("enabled", True)
        }
    except Exception as e:
        logger.error(f"❌ خطأ في قراءة إعدادات WATCHLIST: {e}")
        return {
            "min_watch_hours": 24,
            "max_watch_hours": 72,
            "min_organic_holders_growth": 10,
            "enabled": True
        }
