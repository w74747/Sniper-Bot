"""
تحليل ذكي دوري (كل ساعة) لحالة البوت العامة عبر DeepSeek API.

بدل إرسال آلاف أسطر اللوج الخام (مكلف وغير عملي)، نجمع "ملخصاً هيكلياً"
(إحصائيات الفحص من screening_log + الأداء المالي التراكمي + عيّنة من أهم
الأخطاء الحقيقية خلال الساعة الماضية)، ثم نطلب من DeepSeek قراءتها وكتابة
تقرير عربي مختصر يوضح: الوضع العام، أهم المشاكل، وأي توصية عملية — يُرسَل
تلقائياً عبر تيليجرام.
"""
import asyncio
import logging

import aiohttp

from config.settings import DEEPSEEK_API_KEY, DEEPSEEK_API_BASE
from db.trades import get_screening_stats, get_cumulative_performance, get_recent_logs
from alerts.notifier import send_telegram_message

logger = logging.getLogger("ai_analyst")

ANALYSIS_WINDOW_MINUTES = 60


async def _build_report_data() -> str:
    """
    يجمع البيانات الهيكلية (وليس اللوج الخام الكامل) للساعة الماضية —
    هذا أرخص بكثير (تكلفة/زمن) من إرسال آلاف الأسطر، وأدق لأن DeepSeek
    يستقبل بيانات مُنظَّمة جاهزة للتحليل بدل نص خام يحتاج فهماً إضافياً.
    """
    stats = await get_screening_stats(hours=1)
    performance = await get_cumulative_performance()

    error_logs = await get_recent_logs(minutes=ANALYSIS_WINDOW_MINUTES, level="ERROR", limit=40)
    warning_logs = await get_recent_logs(minutes=ANALYSIS_WINDOW_MINUTES, level="WARNING", limit=30)

    lines = [
        f"=== إحصائيات آخر {ANALYSIS_WINDOW_MINUTES} دقيقة ===",
        f"إجمالي العملات المفحوصة: {stats['total_screened']}",
        "التوزيع حسب القرار:",
    ]
    for row in stats["by_decision"]:
        lines.append(f"  {row['decision']}: {row['c']}")

    lines.append("أكثر أسباب الرفض تكراراً:")
    for row in stats["top_rejection_reasons"][:5]:
        lines.append(f"  ({row['c']}x) {row['reason'][:100]}")

    lines.append("")
    lines.append("=== الأداء المالي التراكمي (كل الوقت) ===")
    lines.append(f"عدد الصفقات المغلقة: {performance['total_closed']}")
    lines.append(f"رابحة: {performance['winning_trades']} / خاسرة: {performance['losing_trades']}")
    lines.append(f"نسبة الربح: {performance['win_rate_pct']:.1f}%")
    lines.append(f"صافي الربح/الخسارة: {performance['total_profit_loss_sol']:.4f} SOL")

    lines.append("")
    lines.append(f"=== عيّنة أخطاء (ERROR) — {len(error_logs)} سطراً ===")
    for row in error_logs[:20]:
        lines.append(f"  {row['message'][:200]}")

    lines.append("")
    lines.append(f"=== عيّنة تحذيرات (WARNING) — {len(warning_logs)} سطراً ===")
    for row in warning_logs[:15]:
        lines.append(f"  {row['message'][:200]}")

    return "\n".join(lines)


async def analyze_and_summarize() -> str:
    """يرسل البيانات الهيكلية لـDeepSeek ويطلب تقريراً عربياً مختصراً."""
    if not DEEPSEEK_API_KEY:
        return "⚠️ DeepSeek غير مُفعَّل (لا مفتاح) — تخطّي التحليل الذكي لهذه الساعة"

    report_data = await _build_report_data()

    system_prompt = (
        "أنت محلّل تقني لبوت تداول آلي على Solana (اكتشاف عملات meme جديدة، "
        "فلترة أمان، شراء وبيع تلقائي). ستستلم بيانات هيكلية (إحصائيات + "
        "عيّنة أخطاء) عن آخر ساعة من التشغيل. اكتب تقريراً عربياً مختصراً "
        "(٥-٨ أسطر كحد أقصى) يغطي: 1) هل الوضع صحي عموماً؟ 2) أهم مشكلة "
        "تقنية واضحة إن وُجدت (اسم الخدمة/الخطأ تحديداً). 3) توصية عملية "
        "واحدة فقط إن لزم الأمر. لا تُطل، ولا تُكرر الأرقام حرفياً، لخّص المعنى."
    )

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": report_data},
        ],
        "max_tokens": 500,
        "temperature": 0.3,
    }
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{DEEPSEEK_API_BASE}/chat/completions",
                json=payload, headers=headers, timeout=30,
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error(f"فشل استدعاء DeepSeek: status {resp.status}: {text[:200]}")
                    return f"⚠️ تعذّر الحصول على تحليل DeepSeek لهذه الساعة (status {resp.status})"
                data = await resp.json()
    except Exception as e:
        logger.error(f"خطأ في الاتصال بـ DeepSeek: {e}")
        return f"⚠️ تعذّر الاتصال بـ DeepSeek لهذه الساعة: {e}"

    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError) as e:
        logger.error(f"استجابة DeepSeek بصيغة غير متوقعة: {e}")
        return "⚠️ استجابة DeepSeek غير قابلة للقراءة هذه الساعة"


async def send_hourly_ai_report():
    """يبني التقرير، يستدعي DeepSeek، ويرسل النتيجة عبر تيليجرام."""
    logger.info("🤖 بدء التحليل الذكي الدوري عبر DeepSeek...")
    summary = await analyze_and_summarize()
    text = f"🤖 <b>تحليل الساعة الماضية (DeepSeek)</b>\n\n{summary}"
    await send_telegram_message(text)
    logger.info("🤖 اكتمل التحليل الذكي وأُرسل عبر تيليجرام")


async def run_hourly_ai_analysis_loop():
    """
    حلقة دائمة تُشغّل التحليل الذكي كل ساعة بالضبط. محمية بالكامل — أي
    استثناء غير متوقع (فشل DeepSeek، خطأ قاعدة بيانات، إلخ) يُسجَّل ولا
    يُسقط الحلقة (نفس درس العطل الصامت الذي تعلمناه سابقاً في watchlist).
    """
    HOURLY_SECONDS = 3600

    while True:
        await asyncio.sleep(HOURLY_SECONDS)
        try:
            await send_hourly_ai_report()
        except Exception as e:
            logger.error(f"⚠️ خطأ غير متوقع في التحليل الذكي الدوري: {type(e).__name__}: {e}")
