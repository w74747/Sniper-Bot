"""
سكربت مستقل لعرض إحصائيات الفحص من قاعدة البيانات الدائمة (Postgres).

طريقة الاستخدام على Railway:
1. غيّر Procfile مؤقتاً إلى: worker: python print_stats.py
2. انتظر انتهاء التشغيل، اقرأ الإحصائيات من Deploy Logs
3. أعد Procfile إلى: worker: python main.py
"""
import asyncio
from db.trades import get_screening_stats, init_db

HOURS = 6


async def main():
    await init_db()
    stats = await get_screening_stats(hours=HOURS)

    print("=" * 60)
    print(f"إحصائيات آخر {stats['period_hours']} ساعة")
    print("=" * 60)
    print(f"إجمالي العملات المفحوصة: {stats['total_screened']}")
    print()

    print("التوزيع حسب القرار:")
    for row in stats["by_decision"]:
        print(f"  {row['decision']}: {row['c']}")
    print()

    print("أكثر 10 أسباب رفض تكراراً:")
    for row in stats["top_rejection_reasons"]:
        print(f"  ({row['c']}x) {row['reason'][:100]}")
    print()

    print(f"العملات المضافة لـ watchlist ({len(stats['added_to_watchlist'])} إجمالاً، آخر 20 فقط):")
    for row in stats["added_to_watchlist"][:20]:
        print(f"  {row['symbol']} — {row['mint_address']}")

    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
