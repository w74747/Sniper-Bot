"""
نقطة الدخول الرئيسية للبوت — ينسّق بين كل الوحدات:

1. الاستماع لعملات جديدة (mempool_listener) [يُبنى في monitor/mempool_listener.py]
2. تشغيل الفلاتر الآلية الفورية (on-chain + reputation + sell simulation)
3. عند الاجتياز: وضع العملة في watchlist لفترة انتظار (24-72 ساعة) بدل شراء فوري
   [حسب القرار الاستراتيجي: التخلي عن السرعة اللحظية لصالح تقييم أعمق]
4. بعد فترة الانتظار ومراجعة المؤشرات العضوية: تنفيذ الشراء
5. بدء المراقبة المزدوجة المستمرة بعد كل شراء (post_trade_monitor)

هذا الملف حالياً "هيكل تنسيقي" (orchestrator scaffold) — كل TODO محدد بدقة
في الوحدات الفرعية يجب إكماله وربطه فعلياً بمصادر بيانات حقيقية (Helius,
Jupiter, GoPlus) قبل التشغيل الفعلي.
"""
import asyncio
import logging
import os

from db import trades as db
from db.log_handler import install_database_log_handler, flush_log_queue_loop
from monitor.post_trade_monitor import run_monitor_loop
from monitor.watchlist import run_watchlist_loop, run_fast_track_loop, run_established_liquid_loop
from monitor.pumpportal_listener import run_pumpportal_listener
from monitor.ai_analyst import run_hourly_ai_analysis_loop, run_code_diagnosis_loop, run_helius_quota_watch_loop

# ملاحظة مهمة: run_mempool_listener (استقصاء Raydium عبر HTTP polling) أُزيل
# من التشغيل بالكامل — Raydium من أكثر برامج Solana ازدحاماً (يشمل كل
# عمليات البيع/الشراء العادية على آلاف العملات، وليس فقط إنشاء pool جديد)،
# وكان يستهلك كل حصص RPC المتبقية (429 شبه مستمر) بينما إنتاجيته الفعلية
# (عملات حقيقية اجتازت الفلاتر) كانت شبه معدومة مقارنة بـPump.fun عبر
# PumpPortal. التركيز الآن بالكامل على Pump.fun (أسرع، أدق، ومجاني تماماً).
# الكود لا يزال موجوداً في monitor/mempool_listener.py لإعادة التفعيل لاحقاً
# إن توفرت حصص RPC كافية (مثلاً بعد ترقية أحد المزودين).

# إنشاء مجلد logs تلقائياً إن لم يكن موجوداً — ضروري على خوادم سحابية مثل Railway
# لأن Git لا يرفع المجلدات الفارغة، فالمجلد قد لا يكون موجوداً فعلياً بعد النشر
os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("logs/bot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
# حماية: حتى لو رُفع المستوى العام لـ DEBUG مستقبلاً للتشخيص، لا نريد إغراق
# السجلات بتفاصيل داخلية من مكتبة websockets نفسها (نبضات ping/pong وغيرها)
logging.getLogger("websockets").setLevel(logging.WARNING)

# تثبيت معالج قاعدة البيانات — كل سجل من الآن يُخزَّن في Postgres أيضاً،
# قابل للاستعلام لاحقاً عبر view_logs.py بغض النظر عن حدود تصدير Railway.
install_database_log_handler()

logger = logging.getLogger("main")


async def run_daily_cleanup_loop():
    """
    تنظيف دوري يومي للبيانات القديمة غير الضرورية — يمنع تكرار مشكلة
    امتلاء مساحة قرص قاعدة البيانات (وصلت 79% فعلياً بعد أسابيع بلا أي
    تنظيف). لا يمس جدول trades (سجل مالي دائم) ولا عناصر watchlist
    المرتبطة بصفقات حقيقية (approved/watching) إطلاقاً.
    """
    CLEANUP_INTERVAL_SECONDS = 86400  # مرة واحدة يومياً

    while True:
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
        try:
            result = await db.cleanup_old_data()
            logger.info(
                f"🧹 تنظيف يومي: حُذف {result['screening_log_deleted']} سجل فحص، "
                f"{result['app_logs_deleted']} سجل تطبيق، {result['watchlist_deleted']} عنصر مراقبة قديم"
            )
        except Exception as e:
            logger.error(f"⚠️ خطأ غير متوقع في التنظيف الدوري: {type(e).__name__}: {e}")


async def main():
    logger.info("بدء تشغيل البوت...")
    await db.init_db()

    tasks = [
        asyncio.create_task(run_pumpportal_listener()),  # اكتشاف Pump.fun فوري ومجاني (WebSocket مخصص)
        asyncio.create_task(run_watchlist_loop()),     # مراجعة قائمة الانتظار العادية (24-72 ساعة)
        asyncio.create_task(run_fast_track_loop()),    # المسار السريع (رصد الانطلاق الصاروخي)
        asyncio.create_task(run_established_liquid_loop()),  # استراتيجية الاستقرار المُثبَت (عملات راسخة، 5+ أيام)
        asyncio.create_task(run_monitor_loop()),       # مراقبة الصفقات المفتوحة (جاهز)
        asyncio.create_task(flush_log_queue_loop()),   # تفريغ طابور السجلات لقاعدة البيانات دورياً
        asyncio.create_task(run_hourly_ai_analysis_loop()),  # تحليل ذكي دوري عبر DeepSeek كل 30 دقيقة
        asyncio.create_task(run_code_diagnosis_loop()),      # تشخيص كود تلقائي عبر DeepSeek كل ساعتين
        asyncio.create_task(run_helius_quota_watch_loop()),  # مراقبة وتيرة استهلاك حصة Helius الشهرية
        asyncio.create_task(run_daily_cleanup_loop()),       # تنظيف يومي لمنع امتلاء مساحة القرص
    ]
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
