"""
🚀 Sniper Bot Solana V2 - البرنامج الرئيسي
════════════════════════════════════════════════════════════════════

المسؤولية: تنسيق جميع الحلقات الدورية الرئيسية
"""

import asyncio
import logging
import sys
from pathlib import Path

from config.settings import LOG_LEVEL, TRADING_MODE, VERSION, CONFIG_SUMMARY

# تهيئة السجلات قبل أي استيراد آخر
logging.basicConfig(
    level=LOG_LEVEL or "INFO",
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger("main")

# الاستيراديات الرئيسية (بعد تهيئة السجلات)
from monitor.pumpportal_listener import run_pumpportal_listener
from monitor.mempool_listener import run_mempool_listener
from monitor.post_trade_monitor import run_monitor_loop
from monitor.hourly_report import run_hourly_report
from monitor.daily_deepseek_report import run_daily_report
from watchlist import run_watchlist_loop, run_fast_track_loop, run_established_liquid_loop
from recovery_close_trades import close_all_on_startup, list_open_trades, print_wallet_status
from telegram_commands import run_telegram_command_handler
from db.trades import init_db


async def run_startup_checks():
    """فحوصات بدء التشغيل الأساسية"""
    logger.info("\n" + "="*80)
    logger.info("🔧 فحوصات بدء التشغيل...")
    logger.info("="*80 + "\n")
    
    # 1️⃣ تهيئة قاعدة البيانات
    try:
        logger.info("📊 تهيئة قاعدة البيانات...")
        await init_db()
        logger.info("✅ قاعدة البيانات جاهزة\n")
    except Exception as e:
        logger.error(f"❌ فشل تهيئة قاعدة البيانات: {e}")
        raise
    
    # 2️⃣ طباعة إعدادات التشغيل
    logger.info("⚙️ إعدادات التشغيل الحالية:")
    for key, value in CONFIG_SUMMARY.items():
        logger.info(f"   • {key}: {value}")
    logger.info("")
    
    # 3️⃣ عرض حالة المحفظة
    try:
        logger.info("💰 فحص المحفظة...")
        await print_wallet_status()
    except Exception as e:
        logger.warning(f"⚠️ تعذّر فحص المحفظة: {e}\n")
    
    # 4️⃣ عرض الصفقات المفتوحة من الجلسة السابقة
    try:
        logger.info("📋 الصفقات المفتوحة من الجلسة السابقة:")
        open_trades = await list_open_trades()
        if open_trades:
            logger.warning(f"⚠️ وُجدت {len(open_trades)} صفقة مفتوحة سابقاً!")
        else:
            logger.info("✅ لا توجد صفقات معلقة")
        logger.info("")
    except Exception as e:
        logger.warning(f"⚠️ تعذّر قراءة الصفقات: {e}\n")


async def run_recovery_close():
    """
    🔄 إغلاق تلقائي لجميع الصفقات المفتوحة من الجلسة السابقة
    ⏱️ مدة التنفيذ: تقريباً 3-5 ثوانٍ لكل صفقة
    """
    try:
        logger.info("🔄 بدء استدعاء الإغلاق التلقائي للصفقات المعلقة...\n")
        await close_all_on_startup()
        logger.info("✅ انتهى فحص الصفقات المعلقة\n")
    except Exception as e:
        logger.error(f"❌ خطأ في الإغلاق التلقائي: {e}")
        logger.info("سيحاول النظام المتابعة دون ذلك...\n")


async def health_check():
    """فحص صحة النظام الدوري (كل ساعة)"""
    from watchlist import get_open_watchlist_count
    
    while True:
        try:
            await asyncio.sleep(3600)  # كل ساعة
            watchlist_count = await get_open_watchlist_count()
            logger.info(f"❤️ حالة النظام: watchlist={watchlist_count} عملة قيد المراقبة")
        except Exception as e:
            logger.error(f"❌ خطأ في فحص الصحة: {e}")


async def main():
    """البرنامج الرئيسي: تشغيل جميع الحلقات بالتوازي"""
    
    logger.info("\n" + "="*80)
    logger.info(f"🚀 Sniper Bot Solana V2 | v{VERSION} | Mode: {TRADING_MODE}")
    logger.info("="*80 + "\n")
    
    # 1️⃣ فحوصات البدء
    try:
        await run_startup_checks()
    except Exception as e:
        logger.error(f"❌ فشلت فحوصات البدء: {e}")
        return
    
    # 2️⃣ إغلاق تلقائي للصفقات المعلقة
    try:
        await run_recovery_close()
    except Exception as e:
        logger.error(f"⚠️ خطأ في الإغلاق التلقائي: {e}")
    
    # 3️⃣ بدء جميع الحلقات الرئيسية بالتوازي
    logger.info("="*80)
    logger.info("🔄 بدء الحلقات الرئيسية...")
    logger.info("="*80 + "\n")
    
    tasks = [
        # استقبال البيانات
        asyncio.create_task(run_pumpportal_listener(), name="pumpportal_listener"),
        asyncio.create_task(run_mempool_listener(), name="mempool_listener"),
        
        # فحص الصفقات
        asyncio.create_task(run_watchlist_loop(), name="watchlist_loop"),
        asyncio.create_task(run_fast_track_loop(), name="fast_track_loop"),
        asyncio.create_task(run_established_liquid_loop(), name="established_liquid_loop"),
        
        # مراقبة الصفقات المفتوحة
        asyncio.create_task(run_monitor_loop(), name="monitor_loop"),
        
        # التقارير
        asyncio.create_task(run_hourly_report(), name="hourly_report"),
        asyncio.create_task(run_daily_report(), name="daily_report"),
        
        # أوامر تيليجرام
        asyncio.create_task(run_telegram_command_handler(), name="telegram_handler"),
        
        # فحص الصحة
        asyncio.create_task(health_check(), name="health_check"),
    ]
    
    logger.info(f"✅ تم بدء {len(tasks)} حلقات رئيسية:")
    for task in tasks:
        logger.info(f"   • {task.get_name()}")
    logger.info("\n" + "="*80)
    logger.info("🎯 النظام جاهز للعمل!")
    logger.info("="*80 + "\n")
    
    # انتظر حتى ينقطع أحد الحلقات (error handling)
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for task in done:
            if task.done() and task.exception():
                logger.error(f"❌ حلقة {task.get_name()} فشلت: {task.exception()}")
                raise task.exception()
    except KeyboardInterrupt:
        logger.warning("\n\n🛑 توقف يدوي من قبل المستخدم...")
    except Exception as e:
        logger.error(f"\n\n❌ خطأ حرج: {e}")
    finally:
        logger.warning("\n🔴 إلغاء جميع الحلقات...")
        for task in tasks:
            if not task.done():
                task.cancel()
        
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("✅ تم إيقاف البرنامج")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n✅ تم إيقاف البرنامج")
    except Exception as e:
        logger.error(f"❌ خطأ عام: {e}")
        sys.exit(1)
