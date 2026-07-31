"""
✅ main.py - مبسط بدون مشاكل
استبدل هذا الملف بالكامل
"""

import asyncio
import logging
from datetime import datetime

from config.settings import PUMPPORTAL_WEBSOCKET

from monitor.pumpportal_listener import run_pumpportal_listener
from monitor.watchlist import run_watchlist_loop, run_fast_track_loop, run_established_liquid_loop
from monitor.post_trade_monitor import run_monitor_loop

logger = logging.getLogger("main")


async def main():
    """
    ✅ البرنامج الرئيسي - Sniper Bot Solana V2
    """
    
    logger.info("\n" + "="*80)
    logger.info("🚀 بدء تشغيل Sniper Bot - Solana V2")
    logger.info("="*80 + "\n")
    
    logger.info(f"⏰ الوقت: {datetime.now().isoformat()}\n")
    
    # 🎯 تشغيل المهام الأساسية فقط
    logger.info("━"*80)
    logger.info("📋 تشغيل المهام الأساسية")
    logger.info("━"*80 + "\n")
    
    tasks = [
        asyncio.create_task(
            run_pumpportal_listener(),
            name="pumpportal_listener"
        ),
        
        asyncio.create_task(
            run_watchlist_loop(),
            name="watchlist_loop"
        ),
        
        asyncio.create_task(
            run_fast_track_loop(),
            name="fast_track_loop"
        ),
        
        asyncio.create_task(
            run_established_liquid_loop(),
            name="established_liquid_loop"
        ),
        
        asyncio.create_task(
            run_monitor_loop(),
            name="trade_monitor"
        ),
    ]
    
    logger.info("✅ تم تشغيل جميع المهام:")
    logger.info("   1️⃣  استقبال العملات الجديدة (PumpPortal)")
    logger.info("   2️⃣  مراقبة قائمة المراقبة")
    logger.info("   3️⃣  مراقبة الصفقات المفتوحة")
    logger.info("\n" + "━"*80 + "\n")
    
    try:
        await asyncio.gather(*tasks, return_exceptions=True)
    
    except KeyboardInterrupt:
        logger.info("\n⏹️  إيقاف البوت (Ctrl+C)...")
        for task in tasks:
            task.cancel()
        await asyncio.sleep(1)
    
    except Exception as e:
        logger.critical(f"❌ خطأ حرج: {e}")
        for task in tasks:
            task.cancel()
    
    finally:
        logger.info("\n" + "="*80)
        logger.info("🛑 تم إيقاف البوت")
        logger.info("="*80 + "\n")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n✅ تم الإيقاف بنجاح")
    except Exception as e:
        logger.critical(f"❌ خطأ غير متوقع: {e}")
