"""
إشعارات تلجرام - الصيغة الدقيقة المطلوبة
"""
import logging
import aiohttp
from datetime import datetime
import os

logger = logging.getLogger("notifier")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"


async def send_telegram(message: str) -> bool:
    """إرسال رسالة تلجرام"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("⚠️ متغيرات التلجرام غير مضبوطة")
        return False
    
    try:
        async with aiohttp.ClientSession() as session:
            data = {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "Markdown"
            }
            async with session.post(TELEGRAM_API, json=data, timeout=10) as resp:
                if resp.status == 200:
                    logger.info(f"✅ رسالة تلجرام أرسلت بنجاح")
                    return True
                else:
                    logger.error(f"❌ فشل إرسال التلجرام: {resp.status}")
                    return False
    except Exception as e:
        logger.error(f"❌ خطأ في التلجرام: {e}")
        return False


async def notify_trade_entry(symbol: str, mint_address: str, entry_amount_sol: float,
                             entry_price: float, decision: str, stage: str) -> bool:
    """إخطار بشراء جديد - الصيغة الدقيقة"""
    message = f"""🟢 تم فتح صفقة جديدة

العملة: (`{mint_address}`)
رأس المال: {entry_amount_sol:.4f} SOL

ملخص الفلترة:
- decision: {decision}
- stage: {stage}"""
    
    return await send_telegram(message)


async def notify_trade_exit(mint_address: str, entry_amount_sol: float,
                            exit_amount_sol: float, profit_loss: float, 
                            profit_pct: float, reason: str, exit_tx: str) -> bool:
    """إخطار ببيع - الصيغة الدقيقة"""
    
    emoji = "🟢" if profit_loss >= 0 else "🔴"
    
    message = f"""{emoji} تم إغلاق الصفقة تلقائياً

العملة: (`{mint_address}`)
السبب: {reason}

رأس المال المستثمر: {entry_amount_sol:.4f} SOL
العائد عند البيع: {exit_amount_sol:.4f} SOL
ربح: {profit_loss:.4f} SOL

رابط المعاملة: https://solscan.io/tx/{exit_tx}"""
    
    return await send_telegram(message)


async def notify_error(error_type: str, details: str) -> bool:
    """إخطار بخطأ"""
    message = f"""🚨 خطأ في البوت

❌ نوع الخطأ: {error_type}
📝 التفاصيل: {details}
⏰ الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
    
    return await send_telegram(message)


async def notify_daily_summary(total_trades: int, winning_trades: int,
                              total_profit: float, win_rate: float) -> bool:
    """إخطار بملخص يومي"""
    emoji = "📈" if total_profit >= 0 else "📉"
    
    message = f"""{emoji} ملخص اليوم

📊 إجمالي الصفقات: {total_trades}
✅ الصفقات الرابحة: {winning_trades}
📉 الصفقات الخاسرة: {total_trades - winning_trades}
📈 نسبة النجاح: {win_rate:.1f}%
💰 الربح الإجمالي: {total_profit:.4f} SOL
⏰ الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
    
    return await send_telegram(message)
