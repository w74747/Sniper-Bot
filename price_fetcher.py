"""
✅ price_fetcher.py - في جذر المشروع (بجانب main.py)
انسخ والصق هذا الملف كاملاً في الجذر
"""

import logging

logger = logging.getLogger("price_fetcher")


async def get_token_price(mint_address: str) -> float:
    """الحصول على سعر التوكن"""
    try:
        # محاكاة الحصول على السعر
        return 0.0
    except Exception as e:
        logger.error(f"❌ خطأ في جلب السعر: {e}")
        return 0.0


async def get_current_price(mint_address: str) -> float:
    """دالة مساعدة للحصول على السعر الحالي"""
    return await get_token_price(mint_address)


def get_price_sync(mint_address: str) -> float:
    """نسخة متزامنة للحصول على السعر"""
    try:
        return 0.0
    except Exception as e:
        logger.error(f"❌ خطأ: {e}")
        return 0.0
