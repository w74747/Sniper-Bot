"""
✅ main.py - Sniper Bot Solana V2
مع Telegram Bot + Recovery + Stats
"""

import asyncio
import logging
import os
from datetime import datetime
import aiohttp

from settings import PUMPPORTAL_WEBSOCKET, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

from monitor.pumpportal_listener import run_pumpportal_listener
from monitor.watchlist import run_watchlist_loop, run_fast_track_loop, run_established_liquid_loop
from monitor.post_trade_monitor import run_monitor_loop

logger = logging.getLogger("main")

# ============================================================================
# 🤖 TELEGRAM BOT
# ============================================================================

class TelegramBot:
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.offset = 0
    
    async def send_message(self, text):
        """إرسال رسالة"""
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(
                    f"{self.base_url}/sendMessage",
                    json={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"},
                    timeout=aiohttp.ClientTimeout(total=10)
                )
                logger.info(f"📤 رسالة أرسلت: {text[:50]}...")
        except Exception as e:
            logger.error(f"❌ خطأ في إرسال الرسالة: {e}")
    
    async def get_updates(self):
        """استقبال الرسائل من التلجرام"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/getUpdates",
                    params={"offset": self.offset, "timeout": 30},
                    timeout=aiohttp.ClientTimeout(total=35)
                ) as resp:
                    data = await resp.json()
                    return data.get("result", [])
        except asyncio.TimeoutError:
            return []
        except Exception as e:
            logger.error(f"❌ خطأ في استقبال الرسائل: {e}")
            return []
    
    async def handle_message(self, text):
        """معالجة الأوامر"""
        text = text.strip().lower()
        logger.info(f"📨 أمر من التلجرام: {text}")
        
        if text == "/start":
            await self.send_message("🤖 <b>مرحباً بك في Sniper Bot!</b>\nاستخدم /help للأوامر")
        
        elif text == "/help":
            help_text = """<b>📋 الأوامر المتاحة:</b>
/status - حالة البوت
/balance - رصيد المحفظة
/trades - الصفقات المفتوحة
/help - الأوامر"""
            await self.send_message(help_text)
        
        elif text == "/status":
            await self.send_message(f"✅ <b>البوت يعمل</b>\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        elif text == "/balance":
            try:
                from solana_rpc import get_wallet_balance
                balance = await get_wallet_balance()
                await self.send_message(f"💰 <b>الرصيد:</b> {balance:.4f} SOL")
            except Exception as e:
                await self.send_message(f"❌ خطأ: {str(e)[:50]}")
        
        elif text == "/trades":
            try:
                from db.trades import get_open_trades
                trades = await get_open_trades()
                msg = f"📊 <b>الصفقات المفتوحة:</b> {len(trades)}\n"
                for t in trades[:5]:
                    msg += f"• {t.get('symbol', '?')}\n"
                if len(trades) > 5:
                    msg += f"... و {len(trades)-5} صفقات أخرى"
                await self.send_message(msg)
            except Exception as e:
                await self.send_message(f"❌ خطأ: {str(e)[:50]}")
        
        else:
            await self.send_message("❓ أمر غير معروف. استخدم /help")
    
    async def run(self):
        """حلقة استقبال الأوامر"""
        logger.info("🤖 بدء بوت التلجرام...")
        await self.send_message("🤖 <b>البوت عاد للتشغيل</b>")
        
        while True:
            try:
                updates = await self.get_updates()
                for update in updates:
                    self.offset = update["update_id"] + 1
                    msg = update.get("message", {}).get("text", "")
                    if msg:
                        await self.handle_message(msg)
                
                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"❌ خطأ في بوت التلجرام: {e}")
                await asyncio.sleep(5)


# ============================================================================
# 🔄 RECOVERY STARTUP
# ============================================================================

async def recovery_startup():
    """استرجاع الحالة عند البدء"""
    logger.info("\n" + "━"*80)
    logger.info("🔄 المرحلة 0: استرجاع الحالة")
    logger.info("━"*80 + "\n")
    
    try:
        logger.info("💰 بيانات المحفظة:")
        from solana_rpc import get_wallet_balance
        balance = await get_wallet_balance()
        logger.info(f"   ✅ الرصيد الحالي: {balance:.4f} SOL\n")
    except Exception as e:
        logger.error(f"❌ خطأ في جلب المحفظة: {e}\n")
    
    try:
        from db.trades import get_open_trades
        open_trades = await get_open_trades()
        logger.info(f"📊 الصفقات المفتوحة: {len(open_trades)}\n")
        if open_trades:
            for trade in open_trades[:3]:
                logger.info(f"   • {trade.get('symbol', '?')} @ {trade.get('entry_price', 0)}\n")
    except Exception as e:
        logger.error(f"❌ خطأ: {e}\n")


# ============================================================================
# 🚀 MAIN
# ============================================================================

async def main():
    """البرنامج الرئيسي"""
    
    logger.info("\n" + "="*80)
    logger.info("🚀 بدء تشغيل Sniper Bot - Solana V2")
    logger.info("="*80 + "\n")
    logger.info(f"⏰ الوقت: {datetime.now().isoformat()}\n")
    
    # Recovery startup
    await recovery_startup()
    
    # إنشاء بوت التلجرام
    bot = None
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        bot = TelegramBot(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
        logger.info("✅ بوت التلجرام جاهز\n")
    else:
        logger.warning("⚠️ لا يوجد TELEGRAM_BOT_TOKEN أو TELEGRAM_CHAT_ID\n")
    
    # تشغيل المهام
    logger.info("━"*80)
    logger.info("📋 تشغيل المهام الأساسية")
    logger.info("━"*80 + "\n")
    
    tasks = [
        asyncio.create_task(run_pumpportal_listener(), name="pumpportal"),
        asyncio.create_task(run_watchlist_loop(), name="watchlist"),
        asyncio.create_task(run_fast_track_loop(), name="fast_track"),
        asyncio.create_task(run_established_liquid_loop(), name="established"),
        asyncio.create_task(run_monitor_loop(), name="monitor"),
    ]
    
    # إضافة بوت التلجرام إذا كان متاحاً
    if bot:
        tasks.append(asyncio.create_task(bot.run(), name="telegram_bot"))
    
    logger.info("✅ تم تشغيل جميع المهام\n" + "━"*80 + "\n")
    
    try:
        await asyncio.gather(*tasks, return_exceptions=True)
    except KeyboardInterrupt:
        logger.info("\n⏹️  إيقاف البوت...")
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
    except Exception as e:
        logger.critical(f"❌ خطأ: {e}")
