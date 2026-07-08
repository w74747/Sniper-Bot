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
from monitor.post_trade_monitor import run_monitor_loop
from monitor.watchlist import run_watchlist_loop
from monitor.mempool_listener import run_mempool_listener

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
logger = logging.getLogger("main")


async def main():
    logger.info("بدء تشغيل البوت...")
    db.init_db()

    tasks = [
        asyncio.create_task(run_mempool_listener()),  # يحتاج إكمال TODOs قبل التشغيل الفعلي
        asyncio.create_task(run_watchlist_loop()),     # مراجعة قائمة الانتظار (جاهز منطقياً)
        asyncio.create_task(run_monitor_loop()),       # مراقبة الصفقات المفتوحة (جاهز)
    ]
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
