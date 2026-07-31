"""
✅ print_stats.py - في جذر المشروع
طباعة إحصائيات المحفظة والصفقات
"""

import logging
from datetime import datetime

logger = logging.getLogger("print_stats")


async def print_wallet_status():
    """طباعة حالة المحفظة الحالية"""
    try:
        from db import trades as db
        
        wallet = await db.get_wallet_balance()
        open_trades = await db.get_open_trades()
        closed_trades = await db.get_closed_trades()
        
        balance = wallet.get("balance", 0)
        stats = f"""
💰 **حالة المحفظة:**
   الرصيد الحالي: {balance:.4f} SOL
   عدد الصفقات المفتوحة: {len(open_trades)}
   عدد الصفقات المغلقة: {len(closed_trades)}
   الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """
        logger.info(stats)
        return stats
    except Exception as e:
        logger.error(f"❌ خطأ في جلب الإحصائيات: {e}")
        return f"❌ خطأ: {e}"


async def print_open_trades():
    """طباعة الصفقات المفتوحة"""
    try:
        from db import trades as db
        
        open_trades = await db.get_open_trades()
        if not open_trades:
            logger.info("✅ لا توجد صفقات مفتوحة")
            return
        
        logger.info(f"📊 الصفقات المفتوحة ({len(open_trades)}):")
        for trade in open_trades:
            logger.info(f"  - {trade.get('symbol', '?')}: {trade.get('entry_price', 0)} @ {trade.get('entry_timestamp', '?')}")
    except Exception as e:
        logger.error(f"❌ خطأ: {e}")
