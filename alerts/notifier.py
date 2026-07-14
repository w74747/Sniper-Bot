"""
تنبيهات Telegram + Console للبوت
معدّلة لضمان رسائل واضحة وأخطاء مسجّلة بشكل صحيح
"""
import asyncio
import json
import logging
from typing import Optional

import aiohttp

from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger("alerts")

# يسجّل الأخطاء في ملف منفصل
alert_logger = logging.getLogger("alerts.telegram")


async def send_telegram_message(message: str, parse_mode: str = "HTML") -> bool:
    """
    يرسل رسالة Telegram مع xhandling للأخطاء
    يرجع True إذا نجح، False إذا فشل
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.debug("⚠️ Telegram غير مفعّل (missing token أو chat_id)")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": parse_mode,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=10) as resp:
                if resp.status == 200:
                    logger.info(f"✅ رسالة Telegram أُرسلت بنجاح")
                    return True
                else:
                    text = await resp.text()
                    alert_logger.error(f"❌ فشل إرسال Telegram: status {resp.status} - {text[:200]}")
                    return False
    except asyncio.TimeoutError:
        alert_logger.error("❌ Telegram timeout بعد 10 ثواني")
        return False
    except Exception as e:
        alert_logger.error(f"❌ خطأ إرسال Telegram: {e}")
        return False


async def alert_new_token_detected(
    mint_address: str,
    symbol: str,
    liquidity_usd: float,
    holders: int,
    source: str = "unknown"
) -> bool:
    """
    تنبيه عند اكتشاف عملة جديدة
    """
    message = f"""
🚨 <b>عملة جديدة مكتشفة!</b>

📋 <b>البيانات:</b>
  • Mint: <code>{mint_address[:16]}...</code>
  • Symbol: {symbol}
  • السيولة: ${liquidity_usd:,.2f}
  • الحاملين: {holders}
  • المصدر: {source}

⏳ <i>جاري الفحص...</i>
"""
    logger.info(f"🔔 تنبيه جديد: {symbol} من {source}")
    return await send_telegram_message(message)


async def alert_filters_passed(
    mint_address: str,
    symbol: str,
    filter_report: dict
) -> bool:
    """
    تنبيه عند اجتياز جميع الفلاتر
    """
    message = f"""
✅ <b>اجتيازت جميع الفلاتر!</b>

📋 <b>العملة:</b>
  • Symbol: {symbol}
  • Mint: <code>{mint_address[:16]}...</code>

🛡️ <b>الفحوصات:</b>
  • GoPlus: ✓
  • On-chain: ✓
  • محاكاة بيع: ✓

🎯 <i>جاهزة للشراء في المسار السريع</i>
"""
    logger.info(f"🎯 {symbol} اجتازت كل الفلاتر!")
    return await send_telegram_message(message)


async def alert_buy_executed(
    symbol: str,
    mint_address: str,
    capital_sol: float,
    tx_hash: str
) -> bool:
    """
    تنبيه عند تنفيذ شراء حقيقي
    """
    explorer_url = f"https://solscan.io/tx/{tx_hash}" if tx_hash != "DEVNET_SIMULATED_NO_TX" else "DEVNET"
    
    message = f"""
💰 <b>تم تنفيذ الشراء!</b>

📋 <b>تفاصيل الصفقة:</b>
  • العملة: {symbol}
  • المبلغ: {capital_sol} SOL
  • Tx: <a href="{explorer_url}">اضغط هنا</a>

⏱️ <i>جاري المراقبة...</i>
"""
    logger.info(f"💸 شراء تم: {symbol} - {capital_sol} SOL")
    return await send_telegram_message(message)


async def alert_filters_failed(
    symbol: str,
    failed_filter: str,
    reason: str
) -> bool:
    """
    تنبيه عند فشل أحد الفلاتر (مختصر)
    """
    message = f"""
❌ <b>فشلت الفلاتر</b>

📋 <b>العملة:</b> {symbol}
🚫 <b>السبب:</b> {failed_filter}
<code>{reason[:100]}</code>
"""
    logger.warning(f"⚠️ {symbol} فشل: {failed_filter}")
    return await send_telegram_message(message)


async def alert_emergency_close(
    symbol: str,
    reason: str,
    loss_pct: float = 0.0
) -> bool:
    """
    تنبيه طوارئ عند إغلاق فوري
    """
    message = f"""
🚨 <b>إغلاق طوارئ!</b>

📋 <b>العملة:</b> {symbol}
⚠️ <b>السبب:</b> {reason}
📉 <b>الخسارة:</b> {loss_pct:.2f}%

<i>تم الإغلاق تلقائياً لحماية رأس المال</i>
"""
    alert_logger.error(f"🚨 إغلاق طوارئ: {symbol} - {reason}")
    return await send_telegram_message(message)


async def alert_bot_started() -> bool:
    """
    تنبيه بدء البوت
    """
    message = """
✅ <b>البوت بدأ العمل!</b>

🔍 جاري البحث عن عملات جديدة...
⏰ الوقت: الآن
"""
    logger.info("🚀 البوت بدأ بنجاح")
    return await send_telegram_message(message)


async def alert_bot_error(error_msg: str) -> bool:
    """
    تنبيه خطأ خطير
    """
    message = f"""
🔴 <b>خطأ خطير في البوت!</b>

❌ <code>{error_msg[:150]}</code>

⚠️ <i>يرجى المراجعة الفورية!</i>
"""
    alert_logger.critical(f"💥 خطأ حرج: {error_msg}")
    return await send_telegram_message(message)


# اختبار بسيط
if __name__ == "__main__":
    asyncio.run(alert_bot_started())
