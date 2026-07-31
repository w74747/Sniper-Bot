"""
✅ main.py - الكامل مع التلجرام + Recovery + Stats
استبدل هذا الملف بالكامل
"""

import asyncio
import logging
import os
from datetime import datetime

# الاستيرادات الأساسية
from config.settings import PUMPPORTAL_WEBSOCKET, TELEGRAM_BOT_TOKEN

# المراقبة والتقييم
from monitor.pumpportal_listener import run_pumpportal_listener
from monitor.watchlist import run_watchlist_loop, run_fast_track_loop, run_established_liquid_loop
from monitor.post_trade_monitor import run_monitor_loop

# التنبيهات
from alerts.critical_alerts import CriticalAlertsSystem

# قاعدة البيانات
from db.log_handler import install_database_log_handler

logger = logging.getLogger("main")


async def run_telegram_bot():
    """🤖 بوت التلجرام - أوامر مباشرة"""
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("⚠️ لا يوجد TELEGRAM_BOT_TOKEN - تخطّي بوت التلجرام")
        return
    
    try:
        from telegram.ext import Application, CommandHandler, MessageHandler, filters
        
        async def handle_start(update, context):
            await update.message.reply_text("🤖 مرحباً بك في Sniper Bot!\nاستخدم /help للأوامر")
        
        async def handle_help(update, context):
            help_text = """
📋 **الأوامر المتاحة:**
/status - حالة البوت الحالية
/balance - رصيد المحفظة
/trades-open - الصفقات المفتوحة
/stats - إحصائيات شاملة
/close-all - إغلاق جميع الصفقات
/close <id> - إغلاق صفقة محددة
/help - هذه الرسالة
            """
            await update.message.reply_text(help_text)
        
        async def handle_status(update, context):
            from db import trades as db
            try:
                open_trades = await db.get_open_trades()
                status = f"""
✅ **حالة البوت:**
- العملات المراقبة: {len(open_trades)}
- الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
                """
                await update.message.reply_text(status)
            except Exception as e:
                await update.message.reply_text(f"❌ خطأ: {e}")
        
        async def handle_balance(update, context):
            try:
                from db import trades as db
                wallet_info = await db.get_wallet_balance()
                balance = wallet_info.get("balance", 0)
                await update.message.reply_text(f"💰 **الرصيد الحالي:** {balance:.4f} SOL")
            except Exception as e:
                await update.message.reply_text(f"❌ خطأ: {e}")
        
        async def handle_trades_open(update, context):
            try:
                from db import trades as db
                open_trades = await db.get_open_trades()
                if not open_trades:
                    await update.message.reply_text("✅ لا توجد صفقات مفتوحة")
                    return
                
                msg = "📊 **الصفقات المفتوحة:**\n"
                for trade in open_trades[:5]:
                    msg += f"- {trade.get('symbol', '?')}: {trade.get('entry_price', 0)}\n"
                if len(open_trades) > 5:
                    msg += f"... و {len(open_trades)-5} صفقات أخرى"
                await update.message.reply_text(msg)
            except Exception as e:
                await update.message.reply_text(f"❌ خطأ: {e}")
        
        async def handle_stats(update, context):
            try:
                from print_stats import print_wallet_status
                stats = await print_wallet_status()
                await update.message.reply_text(f"📈 **الإحصائيات:**\n{stats}")
            except Exception as e:
                await update.message.reply_text(f"❌ خطأ: {e}")
        
        async def handle_close_all(update, context):
            try:
                from recovery_close_trades import close_all_open_trades
                result = await close_all_open_trades()
                await update.message.reply_text(f"✅ تم إغلاق جميع الصفقات\n{result}")
            except Exception as e:
                await update.message.reply_text(f"❌ خطأ: {e}")
        
        async def handle_close(update, context):
            try:
                if not context.args:
                    await update.message.reply_text("❌ استخدم: /close <id>")
                    return
                trade_id = context.args[0]
                from recovery_close_trades import close_trade_by_id
                result = await close_trade_by_id(trade_id)
                await update.message.reply_text(f"✅ تم إغلاق الصفقة {trade_id}\n{result}")
            except Exception as e:
                await update.message.reply_text(f"❌ خطأ: {e}")
        
        # إنشاء التطبيق
        app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        
        # إضافة المعالجات
        app.add_handler(CommandHandler("start", handle_start))
        app.add_handler(CommandHandler("help", handle_help))
        app.add_handler(CommandHandler("status", handle_status))
        app.add_handler(CommandHandler("balance", handle_balance))
        app.add_handler(CommandHandler("trades-open", handle_trades_open))
        app.add_handler(CommandHandler("stats", handle_stats))
        app.add_handler(CommandHandler("close-all", handle_close_all))
        app.add_handler(CommandHandler("close", handle_close))
        
        logger.info("✅ بوت التلجرام جاهز")
        await app.run_polling()
    
    except Exception as e:
        logger.error(f"❌ خطأ في بوت التلجرام: {e}")


async def recovery_startup():
    """🔄 إغلاق الصفقات القديمة واستعادة الحالة"""
    logger.info("━"*80)
    logger.info("🔄 المرحلة 0: استرجاع الصفقات والمحفظة")
    logger.info("━"*80 + "\n")
    
    try:
        from recovery_close_trades import close_all_on_startup
        logger.info("📝 بدء إغلاق الصفقات المفتوحة القديمة...")
        await close_all_on_startup()
        logger.info("✅ تم إغلاق جميع الصفقات القديمة\n")
    except Exception as e:
        logger.error(f"❌ خطأ في إغلاق الصفقات: {e}")
    
    try:
        from print_stats import print_wallet_status
        logger.info("💰 بيانات المحفظة الحالية:")
        await print_wallet_status()
        logger.info("")
    except Exception as e:
        logger.error(f"❌ خطأ في جلب بيانات المحفظة: {e}")


async def main():
    """
    ✅ البرنامج الرئيسي - Sniper Bot Solana V2
    """
    
    logger.info("\n" + "="*80)
    logger.info("🚀 بدء تشغيل Sniper Bot - Solana V2")
    logger.info("="*80 + "\n")
    
    logger.info(f"⏰ الوقت: {datetime.now().isoformat()}\n")
    
    # 🔄 المرحلة 0: استعادة الحالة
    await recovery_startup()
    
    # 🎯 المرحلة 1: إعداد جميع المهام
    logger.info("━"*80)
    logger.info("📋 المرحلة 1: تشغيل المهام الأساسية")
    logger.info("━"*80 + "\n")
    
    # قائمة المهام الأساسية
    tasks = [
        # 1. بوت التلجرام (async)
        asyncio.create_task(
            run_telegram_bot(),
            name="telegram_bot"
        ),
        
        # 2. استقبال العملات الجديدة من PumpPortal
        asyncio.create_task(
            run_pumpportal_listener(),
            name="pumpportal_listener"
        ),
        
        # 3. مراقبة قائمة المراقبة
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
        
        # 4. مراقبة الصفقات المفتوحة
        asyncio.create_task(
            run_monitor_loop(),
            name="trade_monitor"
        ),
    ]
    
    logger.info("✅ تم تشغيل جميع المهام:")
    logger.info("   🤖 بوت التلجرام (أوامر فورية)")
    logger.info("   1️⃣  استقبال العملات الجديدة (PumpPortal)")
    logger.info("   2️⃣  مراقبة قائمة المراقبة")
    logger.info("   3️⃣  مراقبة الصفقات المفتوحة")
    logger.info("\n" + "━"*80 + "\n")
    
    # 🎯 المرحلة 2: معالجة الأخطاء والإشارات
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
    
    install_database_log_handler()
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n✅ تم الإيقاف بنجاح")
    except Exception as e:
        logger.critical(f"❌ خطأ غير متوقع: {e}")
