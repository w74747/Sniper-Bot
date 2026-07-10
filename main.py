"""
نقطة الدخول الرئيسية للبوت — ينسّق بين كل الوحدات:

1. الاستماع لعملات جديدة (mempool_listener)
2. تشغيل الفلاتر الآلية الفورية (on-chain)
3. عند الاجتياز: وضع العملة في watchlist
4. مسار عادي (24-72 ساعة) + مسار سريع (زخم صاروخي، كل 30 ثانية) بالتوازي
5. بدء المراقبة المزدوجة المستمرة بعد كل شراء (post_trade_monitor)
"""
import asyncio
import logging
import os

from db import trades as db
from monitor.post_trade_monitor import run_monitor_loop
from monitor.watchlist import run_watchlist_loop, run_fast_track_loop
from monitor.mempool_listener import run_mempool_listener

os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("logs/bot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logging.getLogger("websockets").setLevel(logging.WARNING)
logger = logging.getLogger("main")


async def main():
    logger.info("بدء تشغيل البوت...")
    db.init_db()

    tasks = [
        asyncio.create_task(run_mempool_listener()),
        asyncio.create_task(run_watchlist_loop()),     # المسار العادي (24-72 ساعة)
        asyncio.create_task(run_fast_track_loop()),    # المسار السريع (رصد الانطلاق الصاروخي)
        asyncio.create_task(run_monitor_loop()),
    ]
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
