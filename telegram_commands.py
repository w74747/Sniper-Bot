"""
✅ telegram_commands.py - أوامر التيليجرام التفاعلية
ضع هذا الملف في جذر المشروع (بجانب main.py)
"""

import logging
from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from recovery_close_trades import list_open_trades, close_all_open_trades, print_wallet_status

logger = logging.getLogger("telegram")

# الأوامر المتاحة
COMMANDS = {
    "/status": "عرض حالة النظام",
    "/balance": "رصيد المحفظة",
    "/trades-open": "الصفقات المفتوحة",
    "/close-all": "إغلاق جميع الصفقات",
    "/help": "قائمة الأوامر"
}


async def run_telegram_command_handler():
    """معالج أوامر التيليجرام"""
    logger.info("✅ بدء معالج أوامر التيليجرام")
    logger.info(f"🤖 Bot Token: {TELEGRAM_BOT_TOKEN[:10]}...")
    logger.info(f"💬 Chat ID: {TELEGRAM_CHAT_ID}")
    
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "your_bot_token":
        logger.warning("⚠️ لم يتم تكوين TELEGRAM_BOT_TOKEN في settings.py")
        return
    
    while True:
        try:
            # معالجة الأوامر
            await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"❌ خطأ: {e}")


def handle_command(command):
    """معالجة أمر معين"""
    if command == "/status":
        print("📊 حالة النظام:")
        print_wallet_status()
        list_open_trades()
    
    elif command == "/balance":
        print("💰 رصيد المحفظة:")
        print_wallet_status()
    
    elif command == "/trades-open":
        print("📈 الصفقات المفتوحة:")
        list_open_trades()
    
    elif command == "/close-all":
        print("🚨 إغلاق جميع الصفقات...")
        asyncio.run(close_all_open_trades())
    
    elif command == "/help":
        print("\n📋 قائمة الأوامر:")
        for cmd, desc in COMMANDS.items():
            print(f"  {cmd} - {desc}")


import asyncio
