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
    cumulative: dict = None,
    entry_timestamp: float = None,
    exit_timestamp: float = None,
    current_wallet_balance_sol: float = None,
    monthly_performance: dict = None,
):
    """رسالة إغلاق تلقائي — دليل on-chain قاطع، مع توثيق مالي كامل + ملخص تراكمي."""
    import time as _time
    from datetime import datetime

    pl_label = "ربح" if profit_loss_sol >= 0 else "خسارة"
    pl_pct = (profit_loss_sol / capital_invested_sol * 100) if capital_invested_sol else 0.0
    pl_sign = "+" if pl_pct >= 0 else ""

    now_ts = exit_timestamp or _time.time()
    closed_at_str = datetime.fromtimestamp(now_ts).strftime("%Y-%m-%d %H:%M:%S")

    duration_str = ""
    if entry_timestamp:
        duration_seconds = max(0, now_ts - entry_timestamp)
        if duration_seconds < 3600:
            duration_str = f"{duration_seconds / 60:.0f} دقيقة"
        else:
            duration_str = f"{duration_seconds / 3600:.1f} ساعة"

    text = (
        f"🔴 <b>تم إغلاق الصفقة تلقائياً</b>\n\n"
        f"العملة: {symbol} (<code>{mint_address}</code>)\n"
        f"السبب: {reason}\n"
        f"وقت الإغلاق: {closed_at_str}"
        + (f" (استمرت {duration_str})" if duration_str else "") + "\n\n"
        f"رأس المال المستثمر: {capital_invested_sol:.4f} SOL\n"
        f"العائد عند البيع: {proceeds_sol:.4f} SOL\n"
        f"{pl_label}: {abs(profit_loss_sol):.4f} SOL ({pl_sign}{pl_pct:.1f}%)\n\n"
        f"رابط المعاملة: https://solscan.io/tx/{tx_hash}"
    )

    if current_wallet_balance_sol is not None:
        text += f"\n\n💰 <b>الرصيد الحالي في المحفظة:</b> {current_wallet_balance_sol:.4f} SOL"

    if monthly_performance:
        m_label = "ربح" if monthly_performance["total_profit_loss_sol"] >= 0 else "خسارة"
        text += (
            f"\n\n📅 <b>الأداء الشهري ({monthly_performance['month_label']})</b>\n"
            f"عدد الصفقات: {monthly_performance['total_closed']} "
            f"({monthly_performance['winning_trades']} رابحة / {monthly_performance['losing_trades']} خاسرة)\n"
            f"نسبة الربح: {monthly_performance['win_rate_pct']:.1f}%\n"
            f"صافي {m_label} الشهري: {abs(monthly_performance['total_profit_loss_sol']):.4f} SOL"
        )

    if cumulative:
        total_label = "ربح" if cumulative["total_profit_loss_sol"] >= 0 else "خسارة"
        text += (
            f"\n\n📊 <b>الأداء التراكمي (كل الصفقات)</b>\n"
            f"عدد الصفقات المغلقة: {cumulative['total_closed']} "
            f"({cumulative['winning_trades']} رابحة / {cumulative['losing_trades']} خاسرة)\n"
            f"نسبة الصفقات الرابحة: {cumulative['win_rate_pct']:.1f}%\n"
            f"صافي {total_label} الإجمالي: {abs(cumulative['total_profit_loss_sol']):.4f} SOL"
        )

    await send_telegram_message(text)


async def alert_new_position_opened(
    symbol: str, mint_address: str, capital_invested_sol: float, filter_summary: str,
    current_wallet_balance_sol: float = None,
):
    from datetime import datetime
    opened_at_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    text = (
        f"🟢 <b>تم فتح صفقة جديدة</b>\n\n"
        f"العملة: {symbol} (<code>{mint_address}</code>)\n"
        f"وقت الفتح: {opened_at_str}\n"
        f"رأس المال: {capital_invested_sol:.4f} SOL\n\n"
        f"ملخص الفلترة:\n{filter_summary}"
    )

    if current_wallet_balance_sol is not None:
        text += f"\n\n💰 <b>الرصيد الحالي في المحفظة (بعد الشراء):</b> {current_wallet_balance_sol:.4f} SOL"

    await send_telegram_message(text)
