"""
إرسال التنبيهات والرسائل عبر تيليجرام:
1. رسالة "تنبيه للمراجعة" (دليل خارجي غير مؤكد) — تنتظر تأكيداً بشرياً.
2. رسالة "إغلاق تلقائي" (دليل on-chain قاطع) — توثيق كامل لرأس المال والربح/الخسارة.
"""
import logging
import aiohttp

from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger("notifier")


async def send_telegram_message(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning(f"[تنبيه بدون إرسال فعلي — بيانات تيليجرام غير مهيأة]:\n{text}")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload, timeout=10) as resp:
                if resp.status != 200:
                    logger.error(f"فشل إرسال رسالة تيليجرام: {resp.status}")
        except Exception as e:
            logger.error(f"خطأ في إرسال رسالة تيليجرام: {e}")


async def alert_needs_human_review(symbol: str, mint_address: str, source: str, detail: str):
    """تنبيه لصفقة قائمة — دليل غير مؤكد، بانتظار قرارك."""
    text = (
        f"⚠️ <b>تنبيه يتطلب مراجعتك</b>\n\n"
        f"العملة: {symbol} (<code>{mint_address}</code>)\n"
        f"المصدر: {source}\n"
        f"التفاصيل: {detail}\n\n"
        f"لم يتم إغلاق الصفقة تلقائياً — الدليل غير مؤكد بما يكفي on-chain.\n"
        f"يرجى المراجعة واتخاذ القرار (إغلاق يدوي أو تجاهل التنبيه)."
    )
    await send_telegram_message(text)


async def alert_auto_closed(
    symbol: str,
    mint_address: str,
    reason: str,
    capital_invested_sol: float,
    proceeds_sol: float,
    profit_loss_sol: float,
    tx_hash: str,
):
    """رسالة إغلاق تلقائي — دليل on-chain قاطع، مع توثيق مالي كامل."""
    pl_label = "ربح" if profit_loss_sol >= 0 else "خسارة"
    text = (
        f"🔴 <b>تم إغلاق الصفقة تلقائياً</b>\n\n"
        f"العملة: {symbol} (<code>{mint_address}</code>)\n"
        f"السبب: {reason}\n\n"
        f"رأس المال المستثمر: {capital_invested_sol:.4f} SOL\n"
        f"العائد عند البيع: {proceeds_sol:.4f} SOL\n"
        f"{pl_label}: {abs(profit_loss_sol):.4f} SOL\n\n"
        f"رابط المعاملة: https://solscan.io/tx/{tx_hash}"
    )
    await send_telegram_message(text)


async def alert_new_position_opened(
    symbol: str, mint_address: str, capital_invested_sol: float, filter_summary: str
):
    text = (
        f"🟢 <b>تم فتح صفقة جديدة</b>\n\n"
        f"العملة: {symbol} (<code>{mint_address}</code>)\n"
        f"رأس المال: {capital_invested_sol:.4f} SOL\n\n"
        f"ملخص الفلترة:\n{filter_summary}"
    )
    await send_telegram_message(text)
