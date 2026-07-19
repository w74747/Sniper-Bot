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
from typing import Optional

import aiohttp

from config.settings import DEEPSEEK_API_KEY, DEEPSEEK_API_BASE
from db.trades import get_screening_stats, get_cumulative_performance, get_recent_logs, get_recent_closed_trades_detail
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
    recent_trades = await get_recent_closed_trades_detail(hours=ANALYSIS_WINDOW_MINUTES / 60)

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

    # تفاصيل كل صفقة فردية — يسمح لـDeepSeek باكتشاف أنماط جودة حقيقية،
    # مثل فجوة منهجية بين ما توقعه سبب الخروج (مثلاً "الربح المُثبَّت ≈ X%")
    # والنتيجة الفعلية المُحقَّقة (profit_loss_pct) — وهو بالضبط ما كشف
    # سابقاً خللاً حقيقياً في مصدر السعر المُستخدَم لقرارات الخروج.
    lines.append("")
    lines.append(f"=== تفاصيل الصفقات المُغلَقة ({len(recent_trades)}) — قارن المتوقَّع بسبب الخروج مع profit_loss_pct الفعلي ===")
    for t in recent_trades:
        lines.append(
            f"  [{t['symbol']}] مدة: {t['duration_minutes']:.0f}د | "
            f"سبب الخروج: {t['exit_reason'][:120]} | "
            f"النتيجة الفعلية: {t['profit_loss_pct']:+.1f}% ({t['profit_loss_sol']:+.4f} SOL)"
        )

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
        "تفاصيل كل صفقة مُغلَقة + عيّنة أخطاء) عن آخر ساعة من التشغيل. "
        "قاعدة مهمة يجب الالتزام بها بدقة: كل صفقة في القائمة **نُفِّذ بيعها "
        "فعلياً بنجاح** (لها معاملة حقيقية مؤكَّدة على السلسلة) — حتى لو "
        "كانت الخسارة كبيرة جداً (حتى -100%)، هذا يعني أن السيولة تبخّرت "
        "فعلياً قبل البيع، وليس أن تنفيذ البيع نفسه فشل تقنياً. **لا تفترض "
        "إطلاقاً** أن أخطاء 429 العامة الظاهرة في عيّنة الأخطاء (والتي غالباً "
        "من فحوصات أخرى غير مرتبطة، مُدارة بأمان عبر إعادة محاولة تلقائية) "
        "هي سبب خسارة صفقة معيّنة، إلا إذا ذُكر خطأ صريح مرتبط بمحاولة بيع "
        "تلك الصفقة تحديداً. مهمة إضافية: قارن سبب الخروج المكتوب لكل صفقة "
        "(يذكر أحياناً 'الربح المُثبَّت ≈ X%') مع النتيجة الفعلية "
        "(profit_loss_pct) — إن وجدت فجوة كبيرة بينهما، هذا يستحق الذكر "
        "كمشكلة تقنية محتملة في مصدر السعر. اكتب تقريراً عربياً مختصراً "
        "(٥-٨ أسطر كحد أقصى) يغطي: 1) هل الوضع صحي عموماً؟ 2) أهم مشكلة "
        "تقنية واضحة إن وُجدت (اسم الخدمة/الخطأ تحديداً، أو فجوة السعر "
        "المذكورة أعلاه إن وُجدت). 3) توصية عملية واحدة فقط إن لزم الأمر. "
        "لا تُطل، ولا تُكرر الأرقام حرفياً، لخّص المعنى."
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
    حلقة دائمة تُشغّل التحليل الذكي كل 30 دقيقة. محمية بالكامل — أي
    استثناء غير متوقع (فشل DeepSeek، خطأ قاعدة بيانات، إلخ) يُسجَّل ولا
    يُسقط الحلقة (نفس درس العطل الصامت الذي تعلمناه سابقاً في watchlist).
    """
    HOURLY_SECONDS = 1800  # كل 30 دقيقة بدل ساعة كاملة — رؤية أسرع وأدق، خصوصاً
                            # في الفترات الحرجة بعد إصلاحات كبيرة (التكلفة لا تزال زهيدة جداً)

    while True:
        await asyncio.sleep(HOURLY_SECONDS)
        try:
            await send_hourly_ai_report()
        except Exception as e:
            logger.error(f"⚠️ خطأ غير متوقع في التحليل الذكي الدوري: {type(e).__name__}: {e}")


# ═══════════════════════════════════════════════════════════════════
# 4) تشخيص الأخطاء في الكود الفعلي — يربط الخطأ الأكثر تكراراً في اللوج
#    بملفه المصدري، ويطلب من DeepSeek تحديد مكان الخلل واقتراح إصلاح
# ═══════════════════════════════════════════════════════════════════

# خريطة اسم اللوجر (logger_name كما يظهر في كل سطر لوج) → مسار الملف المصدري
# المسؤول عنه. البوت يعمل من نفس المجلد الذي يحتوي كوده، فبإمكانه قراءة
# ملفاته الخاصة مباشرة من القرص لتشخيص نفسه — دون أي أداة خارجية.
_LOGGER_TO_FILE = {
    "reputation": "filters/reputation.py",
    "sell_simulation": "filters/sell_simulation.py",
    "momentum": "filters/momentum.py",
    "onchain_filters": "filters/onchain_filters.py",
    "tatum_check": "filters/tatum_check.py",
    "watchlist": "monitor/watchlist.py",
    "mempool_listener": "monitor/mempool_listener.py",
    "pumpportal_listener": "monitor/pumpportal_listener.py",
    "post_trade_monitor": "monitor/post_trade_monitor.py",
    "ai_analyst": "monitor/ai_analyst.py",
    "swap_executor": "trading/executor.py",
    "solana_rpc": "utils/solana_rpc.py",
    "db_trades": "db/trades.py",
    "db_pool": "db/pool.py",
    "notifier": "alerts/notifier.py",
}

_DIAGNOSIS_WINDOW_MINUTES = 120     # نافذة أوسع من التقرير الدوري (ساعتان) — عيّنة أكبر لتشخيص أدق
_DIAGNOSIS_MIN_ERROR_COUNT = 5      # لا داعي للتشخيص إن كانت الأخطاء قليلة جداً (أقل من 5 خلال ساعتين)


async def diagnose_recurring_code_issue() -> Optional[str]:
    """
    يجد أكثر مصدر أخطاء (ERROR) تكراراً خلال آخر ساعتين، يقرأ كود ملفه
    المصدري فعلياً من القرص، ويطلب من DeepSeek تشخيصاً محدداً: أين الخلل
    المحتمل، ولماذا، وما الإصلاح المقترح — بدل الاكتفاء بوصف الأعراض
    كما يفعل التقرير الدوري العادي.
    """
    if not DEEPSEEK_API_KEY:
        return None

    error_logs = await get_recent_logs(minutes=_DIAGNOSIS_WINDOW_MINUTES, level="ERROR", limit=200)
    if len(error_logs) < _DIAGNOSIS_MIN_ERROR_COUNT:
        return None  # لا يوجد نمط أخطاء متكرر يستحق تشخيصاً عميقاً الآن

    # عدّ الأخطاء حسب logger_name لتحديد المصدر الأكثر تكراراً
    counts: dict = {}
    samples: dict = {}
    for row in error_logs:
        name = row["logger_name"]
        counts[name] = counts.get(name, 0) + 1
        samples.setdefault(name, []).append(row["message"])

    top_logger = max(counts, key=counts.get)
    top_count = counts[top_logger]
    if top_count < _DIAGNOSIS_MIN_ERROR_COUNT:
        return None

    file_path = _LOGGER_TO_FILE.get(top_logger)
    if not file_path:
        logger.debug(f"لا يوجد ربط معروف بين اللوجر '{top_logger}' وملف مصدري")
        return None

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            source_code = f.read()
    except Exception as e:
        logger.warning(f"تعذّر قراءة الملف المصدري {file_path} للتشخيص: {e}")
        return None

    error_samples_text = "\n".join(f"- {msg[:300]}" for msg in samples[top_logger][:15])

    system_prompt = (
        "أنت مهندس برمجيات خبير في Python وaiohttp وSolana. ستستلم كود ملف "
        "بايثون فعلي من مشروع بوت تداول، بالإضافة إلى عيّنة من رسائل خطأ "
        "حقيقية متكررة صدرت منه. حدّد بدقة (بالعربية): 1) أين يكمن الخلل "
        "المحتمل تحديداً في الكود (اسم الدالة/رقم السطر التقريبي إن أمكن)، "
        "2) لماذا يحدث هذا الخطأ بالتحديد بناءً على منطق الكود، 3) إصلاح "
        "مقترح محدد وقصير. كن مختصراً ومباشراً (8 أسطر كحد أقصى)، لا تُعد "
        "شرح الكود كله، فقط التشخيص والحل."
    )
    user_content = (
        f"الملف: {file_path}\n"
        f"عدد الأخطاء من هذا المصدر خلال آخر {_DIAGNOSIS_WINDOW_MINUTES} دقيقة: {top_count}\n\n"
        f"عيّنة من رسائل الخطأ الفعلية:\n{error_samples_text}\n\n"
        f"كود الملف الكامل:\n```python\n{source_code[:12000]}\n```"
    )

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": 700,
        "temperature": 0.2,
    }
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{DEEPSEEK_API_BASE}/chat/completions", json=payload, headers=headers, timeout=45,
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"فشل تشخيص الكود عبر DeepSeek: status {resp.status}")
                    return None
                data = await resp.json()
        diagnosis = data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.warning(f"تعذّر تشخيص الكود عبر DeepSeek: {e}")
        return None

    return (
        f"🔬 <b>تشخيص كود تلقائي (DeepSeek)</b>\n\n"
        f"الملف الأكثر إنتاجاً للأخطاء: <code>{file_path}</code>\n"
        f"عدد الأخطاء ({_DIAGNOSIS_WINDOW_MINUTES//60} ساعة): {top_count}\n\n"
        f"{diagnosis}"
    )


async def run_code_diagnosis_loop():
    """
    حلقة منفصلة عن التقرير الدوري العادي — تعمل كل ساعتين فقط (تشخيص الكود
    أثقل تكلفة من التقرير الهيكلي العادي، فلا داعي لتكراره كل 30 دقيقة).
    """
    DIAGNOSIS_INTERVAL_SECONDS = 7200  # كل ساعتين

    while True:
        await asyncio.sleep(DIAGNOSIS_INTERVAL_SECONDS)
        try:
            diagnosis_text = await diagnose_recurring_code_issue()
            if diagnosis_text:
                await send_telegram_message(diagnosis_text)
                logger.info("🔬 أُرسل تشخيص كود تلقائي جديد")
        except Exception as e:
            logger.error(f"⚠️ خطأ غير متوقع في حلقة تشخيص الكود: {type(e).__name__}: {e}")


# ═══════════════════════════════════════════════════════════════════
# 5) مراقبة وتيرة استهلاك حصة Helius الشهرية — تحذير فوري قبل النفاد
#    المفاجئ، بدل اكتشافه بعد فوات الأوان (فلسفة: كل تكلفة يجب أن يُحسَب
#    استهلاكها بدقة، لا مجرد اشتراك يُستنزَف بصمت بلا رقابة).
# ═══════════════════════════════════════════════════════════════════

async def run_helius_quota_watch_loop():
    """حلقة خفيفة جداً (لا تستدعي أي API خارجي) تفحص وتيرة الاستهلاك كل 15 دقيقة."""
    CHECK_INTERVAL_SECONDS = 900  # كل 15 دقيقة — فحص محلي بحت، لا تكلفة له إطلاقاً

    while True:
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
        try:
            from utils.solana_rpc import check_helius_quota_pace
            warning = check_helius_quota_pace()
            if warning:
                status_word = "⚠️ سيتجاوز الحصة!" if warning["will_exceed"] else "ضمن الحصة (لكن أسرع من الوتيرة الآمنة)"
                await send_telegram_message(
                    f"⚠️ <b>تحذير: وتيرة استهلاك Helius أسرع من الآمن</b>\n\n"
                    f"المُستهلَك حتى الآن: {warning['used']:,} من {warning['quota']:,} "
                    f"({warning['used_fraction']*100:.1f}%)\n"
                    f"الوقت المنقضي من الشهر: {warning['elapsed_fraction']*100:.1f}%\n"
                    f"التوقع بنفس الوتيرة بنهاية الشهر: ~{warning['projected_total']:,.0f}\n"
                    f"الحالة: {status_word}"
                )
                logger.warning(
                    f"⚠️ تحذير وتيرة Helius: {warning['used']:,}/{warning['quota']:,} "
                    f"({warning['used_fraction']*100:.1f}% مقابل {warning['elapsed_fraction']*100:.1f}% من الشهر)"
                )
        except Exception as e:
            logger.error(f"⚠️ خطأ غير متوقع في مراقبة حصة Helius: {type(e).__name__}: {e}")


# ═══════════════════════════════════════════════════════════════════
# 1) تنبيه الأزمة الفورية — بدل انتظار الدورة الدورية (حتى 30 دقيقة)
# ═══════════════════════════════════════════════════════════════════

_recent_emergency_sells: list = []  # قائمة توقيتات آخر عمليات البيع الطارئ
_CRISIS_WINDOW_SECONDS = 300         # نافذة 5 دقائق
_CRISIS_THRESHOLD = 3                # 3 عمليات بيع طارئ خلال 5 دقائق = أزمة حقيقية
_last_crisis_alert_time = 0.0
_CRISIS_ALERT_COOLDOWN_SECONDS = 900  # لا نُكرر تنبيه الأزمة أكثر من مرة كل 15 دقيقة


async def report_emergency_sell():
    """
    يُستدعى من trading/executor.py عند كل عملية بيع طارئ. إذا تجاوز عدد
    عمليات البيع الطارئ خلال نافذة قصيرة حداً معيّناً، يُطلق تحليلاً فورياً
    عبر DeepSeek بدل انتظار الدورة الدورية — يُقلّص وقت اكتشاف الأزمة من
    "حتى 30 دقيقة" إلى ثوانٍ معدودة (مستوحى من الأزمة الحقيقية التي واجهناها:
    بيع طارئ خاطئ متكرر بسبب فشل RPC تقني وليس احتيالاً حقيقياً).
    """
    import time
    global _last_crisis_alert_time

    now = time.time()
    _recent_emergency_sells.append(now)
    while _recent_emergency_sells and now - _recent_emergency_sells[0] > _CRISIS_WINDOW_SECONDS:
        _recent_emergency_sells.pop(0)

    if len(_recent_emergency_sells) < _CRISIS_THRESHOLD:
        return
    if now - _last_crisis_alert_time < _CRISIS_ALERT_COOLDOWN_SECONDS:
        return  # تجنّب إغراق تيليجرام بتنبيهات متكررة لنفس الأزمة المستمرة

    _last_crisis_alert_time = now
    logger.warning(
        f"🚨 {len(_recent_emergency_sells)} عمليات بيع طارئ خلال "
        f"{_CRISIS_WINDOW_SECONDS}s — تفعيل تحليل أزمة فوري"
    )
    try:
        summary = await analyze_and_summarize()
        await send_telegram_message(
            f"🚨 <b>تنبيه أزمة فوري (DeepSeek)</b>\n\n"
            f"{len(_recent_emergency_sells)} عمليات بيع طارئ خلال آخر "
            f"{_CRISIS_WINDOW_SECONDS // 60} دقائق — هذا أسرع بكثير من المعتاد.\n\n{summary}"
        )
    except Exception as e:
        logger.error(f"فشل إرسال تنبيه الأزمة الفوري: {e}")


# ═══════════════════════════════════════════════════════════════════
# 2) مراجعة الصفقة بعد إغلاقها — تقييم سريع لجودة القرار
# ═══════════════════════════════════════════════════════════════════

async def review_closed_trade(symbol: str, entry_reason: str, exit_reason: str, profit_loss_sol: float) -> str:
    """
    يُرسل تفاصيل صفقة مغلقة (سبب الدخول، سبب الخروج، النتيجة) لـDeepSeek،
    ويطلب حكماً موجزاً بجملة واحدة فقط: هل كان القرار سليماً بناءً على
    المعطيات المتاحة وقتها؟ بناء سجل تراكمي لتحسين المنطق مستقبلاً.
    """
    if not DEEPSEEK_API_KEY:
        return ""

    result_word = "ربح" if profit_loss_sol >= 0 else "خسارة"
    user_content = (
        f"صفقة على عملة meme في Solana:\n"
        f"سبب الدخول: {entry_reason[:400]}\n"
        f"سبب الخروج: {exit_reason[:300]}\n"
        f"النتيجة: {result_word} {abs(profit_loss_sol):.4f} SOL\n\n"
        f"بجملة واحدة فقط (عربي): هل كان القرار سليماً بناءً على المعطيات "
        f"المتاحة وقت اتخاذه (وليس بناءً على النتيجة النهائية فقط)؟"
    )
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "أنت محلّل مختصر جداً. رد بجملة واحدة فقط بالعربية، بلا مقدمات."},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": 120,
        "temperature": 0.3,
    }
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{DEEPSEEK_API_BASE}/chat/completions", json=payload, headers=headers, timeout=15,
            ) as resp:
                if resp.status != 200:
                    return ""
                data = await resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.debug(f"تعذّر مراجعة الصفقة عبر DeepSeek (غير حرج): {e}")
        return ""
