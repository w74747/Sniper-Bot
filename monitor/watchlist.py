"""
قائمة الانتظار (Watchlist): جوهر الاستراتيجية المتفق عليها.

بدل الشراء الفوري عند اجتياز الفلاتر الآلية، تدخل العملة "قائمة مراقبة"
لمدة 24-72 ساعة، خلالها نراقب مؤشرات عضوية حقيقية (نمو حاملين، تداول
طبيعي، نشاط تطوير فعلي) قبل اتخاذ قرار الشراء النهائي.

هذا يعني تخلياً كاملاً عن ميزة "السرعة اللحظية" (وبالتالي لا حاجة لـ
Jito/co-location) مقابل التزام حقيقي بمعايير الجدية والمشروعية.
"""
import asyncio
import logging
import os
import sqlite3
import time
from dataclasses import dataclass

from config.settings import WATCHLIST
from db.trades import DB_PATH
from trading.executor import execute_buy

logger = logging.getLogger("watchlist")


def init_watchlist_table(db_path: str = DB_PATH):
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mint_address TEXT NOT NULL,
            symbol TEXT,
            pool_address TEXT,
            added_at REAL,
            initial_filter_report TEXT,
            holders_at_add INTEGER DEFAULT 0,
            status TEXT DEFAULT 'watching'  -- watching / approved / rejected / expired
        )
    """)
    conn.commit()
    conn.close()


@dataclass
class WatchlistEntry:
    mint_address: str
    symbol: str
    pool_address: str
    initial_filter_report: str
    holders_at_add: int = 0


def add_to_watchlist(entry: WatchlistEntry, db_path: str = DB_PATH) -> int:
    conn = sqlite3.connect(db_path)
    cur = conn.execute(
        """INSERT INTO watchlist
           (mint_address, symbol, pool_address, added_at, initial_filter_report, holders_at_add)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (entry.mint_address, entry.symbol, entry.pool_address, time.time(),
         entry.initial_filter_report, entry.holders_at_add),
    )
    conn.commit()
    watch_id = cur.lastrowid
    conn.close()
    logger.info(f"تمت إضافة {entry.symbol} إلى قائمة المراقبة (#{watch_id})")
    return watch_id


async def check_organic_growth(mint_address: str, holders_at_add: int) -> dict:
    """
    يفحص المؤشرات العضوية الحالية مقابل لحظة الإضافة للـ watchlist.
    TODO: ربط فعلي بـ:
    - عدد حاملين حالي (عبر Alchemy أو ما شابه)
    - حجم تداول عضوي مقابل wash trading (فحص أنماط التكرار في المعاملات)
    - نشاط GitHub فعلي إن وُجد رابط مستودع
    - نمو متابعين Twitter/Telegram (لا بوتات)
    """
    return {
        "current_holders": holders_at_add,  # يُستبدل بقيمة فعلية
        "holders_growth": 0,
        "organic_volume_ratio": 0.0,  # نسبة الحجم العضوي إلى الحجم الكلي
    }


async def evaluate_watchlist_entry(entry: dict) -> tuple[str, str]:
    """يقرر: approved / rejected / still_watching"""
    age_hours = (time.time() - entry["added_at"]) / 3600

    growth_data = await check_organic_growth(entry["mint_address"], entry["holders_at_add"])

    if growth_data["holders_growth"] < 0:
        return "rejected", "انخفاض عدد الحاملين — إشارة سلبية واضحة"

    if age_hours < WATCHLIST.min_watch_hours:
        return "still_watching", f"لم تمر بعد فترة المراقبة الدنيا ({age_hours:.1f}h)"

    if growth_data["holders_growth"] >= WATCHLIST.min_organic_holders_growth:
        return "approved", (
            f"نمو عضوي كافٍ: +{growth_data['holders_growth']} حامل جديد "
            f"خلال {age_hours:.1f} ساعة"
        )

    if age_hours >= WATCHLIST.max_watch_hours:
        return "expired", "انتهت فترة المراقبة القصوى دون نمو عضوي كافٍ"

    return "still_watching", f"ما زالت قيد المراقبة ({age_hours:.1f}h)"


async def run_watchlist_loop(db_path: str = DB_PATH):
    """يراجع كل العملات في قائمة المراقبة دورياً ويتخذ قرار الشراء عند الموافقة."""
    init_watchlist_table(db_path)
    while True:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM watchlist WHERE status = 'watching'"
        ).fetchall()
        conn.close()

        for row in rows:
            entry = dict(row)
            decision, reason = await evaluate_watchlist_entry(entry)

            if decision == "approved":
                logger.info(f"موافقة على شراء {entry['symbol']}: {reason}")
                await execute_buy(
                    entry["mint_address"], entry["symbol"], entry["pool_address"],
                    capital_sol=0.1,  # TODO: استخدام max_capital_pct_per_trade الفعلي
                    filter_report={"watchlist_decision": reason},
                )
                _update_watchlist_status(entry["id"], "approved", db_path)

            elif decision in ("rejected", "expired"):
                logger.info(f"رفض/انتهاء {entry['symbol']}: {reason}")
                _update_watchlist_status(entry["id"], decision, db_path)

        await asyncio.sleep(WATCHLIST.check_interval_minutes * 60)


def _update_watchlist_status(watch_id: int, status: str, db_path: str = DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE watchlist SET status = ? WHERE id = ?", (status, watch_id))
    conn.commit()
    conn.close()
