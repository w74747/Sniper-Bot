"""
✅ main.py - المصحح تماماً
استبدل الملف الحالي بهذا مباشرة
"""

import asyncio
import logging
import os
from datetime import datetime

# الاستيرادات الأساسية
from config.settings import PUMPPORTAL_WEBSOCKET

# المراقبة والتقييم
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
    
    # 🎯 تشغيل المهام الأساسية
    logger.info("━"*80)
    logger.info("📋 المرحلة 1: تشغيل المهام الأساسية")
    logger.info("━"*80 + "\n")
    
    tasks = [
        run_pumpportal_listener(),
        run_watchlist_loop(),
        run_fast_track_loop(),
        run_established_liquid_loop(),
        run_monitor_loop(),
    ]
    
    logger.info(f"✅ تم بدء {len(tasks)} مهام رئيسية\n")
    
    try:
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        logger.info("\n⛔ تم إيقاف البرنامج من قبل المستخدم")
    except Exception as e:
        logger.error(f"\n❌ خطأ غير متوقع: {e}")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⛔ تم إيقاف البرنامج")
    except Exception as e:
        print(f"❌ خطأ: {e}")
        import traceback
        traceback.print_exc()
