"""
سكربت مستقل لعرض السجلات مباشرة من قاعدة البيانات (Postgres) — بديل كامل
عن تصدير Railway الذي يقتصر عادة على آخر ~1000 سطر فقط، بغض النظر عن
المدة الزمنية الفعلية المطلوبة.

طريقة الاستخدام على Railway:
1. غيّر Procfile مؤقتاً إلى: worker: python view_logs.py
2. انتظر انتهاء التشغيل، اقرأ السجلات من Deploy Logs (ستكون منظّمة وموجزة)
3. أعد Procfile إلى: worker: python main.py

عدّل MINUTES وLEVEL أدناه حسب حاجتك:
- MINUTES: عدد الدقائق للرجوع بالزمن (مثلاً 1440 = 24 ساعة)
- LEVEL: فلترة حسب المستوى فقط ("ERROR", "WARNING", "INFO") أو None لعرض الكل
"""
import asyncio
from datetime import datetime
from db.trades import get_recent_logs, init_db

MINUTES = 360  # آخر 6 ساعات افتراضياً
LEVEL = None   # ضع "ERROR" لعرض الأخطاء فقط، أو None لعرض كل المستويات
LIMIT = 500    # أقصى عدد سطور تُعرض (الأحدث أولاً في القاعدة، لكن نعرضها بترتيب زمني تصاعدي)


async def main():
    await init_db()
    logs = await get_recent_logs(minutes=MINUTES, level=LEVEL, limit=LIMIT)

    print("=" * 70)
    print(f"آخر {len(logs)} سطر لوج (من أصل آخر {MINUTES} دقيقة" + (f"، مستوى {LEVEL} فقط" if LEVEL else "") + ")")
    print("=" * 70)

    # القاعدة تُرجعها الأحدث أولاً؛ نعرضها بترتيب زمني تصاعدي (الأقدم أولاً) لسهولة المتابعة
    for row in reversed(logs):
        ts = datetime.fromtimestamp(row["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
        print(f"{ts} [{row['level']}] {row['logger_name']}: {row['message']}")

    print("=" * 70)
    print(f"الإجمالي المعروض: {len(logs)} سطر")


if __name__ == "__main__":
    asyncio.run(main())
