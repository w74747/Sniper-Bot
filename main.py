"""
✅ main.py المحدث - مع نظام التقييم المتكامل
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
from monitor.trades_evaluator import evaluator, run_periodic_evaluation
from monitor.hourly_report import run_hourly_report_loop
from monitor.daily_deepseek_report import run_daily_deepseek_report_loop

# التنبيهات
from alerts.critical_alerts import CriticalAlertsSystem

# قاعدة البيانات
from db.log_handler import install_database_log_handler

logger = logging.getLogger("main")


async def main():
    """
    ✅ البرنامج الرئيسي - Sniper Bot Solana V2
    """
    
    logger.info("\n" + "="*80)
    logger.info("🚀 بدء تشغيل Sniper Bot - Solana V2")
    logger.info("="*80 + "\n")
    
    logger.info(f"⏰ الوقت: {datetime.now().isoformat()}\n")
    
    # 🎯 الخطوة 1: تقييم الصفقات المفتوحة عند البدء
    logger.info("━"*80)
    logger.info("📋 المرحلة 1: تقييم الصفقات المفتوحة")
    logger.info("━"*80 + "\n")
    
    try:
        await evaluator.evaluate_on_startup()
    except Exception as e:
        logger.error(f"❌ خطأ في التقييم الأولي: {e}")
        await CriticalAlertsSystem.alert_unhandled_exception(
            component="startup_evaluation",
            error=str(e),
            traceback=str(e)
        )
    
    # 🎯 الخطوة 2: إعداد جميع المهام
    logger.info("\n" + "━"*80)
    logger.info("📋 المرحلة 2: تشغيل المهام الأساسية")
    logger.info("━"*80 + "\n")
    
    # قائمة المهام المهمة
    tasks = [
        # 1. استقبال العملات الجديدة من PumpPortal
        asyncio.create_task(
            run_pumpportal_listener(),
            name="pumpportal_listener"
        ),
        
        # 2. مراقبة قائمة المراقبة
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
        
        # 3. مراقبة الصفقات المفتوحة
        asyncio.create_task(
            run_monitor_loop(),
            name="trade_monitor"
        ),
        
        # 4. التقييم الدوري للصفقات القديمة
        asyncio.create_task(
            run_periodic_evaluation(),
            name="periodic_evaluation"
        ),
        
        # 5. التنبيهات الفورية (بدون DeepSeek)
        # (تعمل داخل المهام الأخرى)
        
        # 6. التقارير المحلية كل 3 ساعات
        asyncio.create_task(
            run_hourly_report_loop(),
            name="hourly_reports"
        ),
        
        # 7. التقرير اليومي العميق (مع DeepSeek)
        asyncio.create_task(
            run_daily_deepseek_report_loop(),
            name="daily_deepseek"
        ),
    ]
    
    logger.info("✅ تم تشغيل جميع المهام:")
    logger.info("   1️⃣  استقبال العملات الجديدة (PumpPortal)")
    logger.info("   2️⃣  مراقبة قائمة المراقبة")
    logger.info("   3️⃣  مراقبة الصفقات المفتوحة")
    logger.info("   4️⃣  التقييم الدوري (كل ساعة)")
    logger.info("   5️⃣  التقارير المحلية (كل 3 ساعات)")
    logger.info("   6️⃣  التقرير اليومي (مرة/اليوم)")
    logger.info("\n" + "━"*80 + "\n")
    
    # 🎯 الخطوة 3: معالجة الأخطاء والإشارات
    try:
        # انتظر جميع المهام
        await asyncio.gather(*tasks, return_exceptions=True)
    
    except KeyboardInterrupt:
        logger.info("\n⏹️  إيقاف البوت (Ctrl+C)...")
        # إلغاء جميع المهام
        for task in tasks:
            task.cancel()
        await asyncio.sleep(1)
    
    except Exception as e:
        logger.critical(f"❌ خطأ حرج: {e}")
        await CriticalAlertsSystem.alert_unhandled_exception(
            component="main",
            error=str(e),
            traceback=str(e)
        )
        # إلغاء جميع المهام
        for task in tasks:
            task.cancel()
    
    finally:
        logger.info("\n" + "="*80)
        logger.info("🛑 تم إيقاف البوت")
        logger.info("="*80 + "\n")


if __name__ == "__main__":
    # إعداد logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    
    # تثبيت database logging handler
    install_database_log_handler()
    
    # تشغيل البرنامج الرئيسي
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n✅ تم الإيقاف بنجاح")
    except Exception as e:
        logger.critical(f"❌ خطأ غير متوقع: {e}")
