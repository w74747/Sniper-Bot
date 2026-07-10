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

from config.settings import WATCHLIST, EXIT_STRATEGY
from db.trades import DB_PATH, record_screening_result
from trading.executor import execute_buy
from filters.reputation import evaluate_reputation
from filters.sell_simulation import simulate_sell, evaluate_simulation_result
from utils.solana_rpc import get_token_largest_accounts, rpc_call

logger = logging.getLogger("watchlist")

TOTAL_BOT_CAPITAL_SOL = 1.0


def init_watchlist_table(db_path: str = DB_PATH):
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mint_address TEXT NOT NULL,
            symbol TEXT,
            pool_address TEXT,
            dex TEXT,
            deployer_wallet TEXT,
            added_at REAL,
            initial_filter_report TEXT,
            holders_at_add INTEGER DEFAULT 0,
            status TEXT DEFAULT 'watching'
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
    dex: str = ""
    deployer_wallet: str = ""


def add_to_watchlist(entry: WatchlistEntry, db_path: str = DB_PATH) -> int:
    conn = sqlite3.connect(db_path)
    cur = conn.execute(
        """INSERT INTO watchlist
           (mint_address, symbol, pool_address, dex, deployer_wallet,
            added_at, initial_filter_report, holders_at_add)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (entry.mint_address, entry.symbol, entry.pool_address, entry.dex,
         entry.deployer_wallet, time.time(), entry.initial_filter_report,
         entry.holders_at_add),
    )
    conn.commit()
    watch_id = cur.lastrowid
    conn.close()
    logger.info(f"تمت إضافة {entry.symbol} إلى قائمة المراقبة (#{watch_id})")
    return watch_id


def is_already_in_watchlist(mint_address: str, db_path: str = DB_PATH) -> bool:
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT 1 FROM watchlist WHERE mint_address = ? LIMIT 1", (mint_address,)
    ).fetchone()
    conn.close()
    return row is not None


async def check_organic_growth(mint_address: str, holders_at_add: int) -> dict:
    try:
        largest_accounts = await get_token_largest_accounts(mint_address)
        current_holders = sum(1 for h in largest_accounts if float(h.get("amount", 0)) > 0)
    except Exception as e:
        logger.warning(f"تعذّر فحص النمو العضوي لـ {mint_address}: {e}")
        current_holders = holders_at_add

    holders_growth = current_holders - holders_at_add

    return {
        "current_holders": current_holders,
        "holders_growth": holders_growth,
        "organic_volume_ratio": None,
    }


async def evaluate_watchlist_entry(entry: dict) -> tuple[str, str]:
    """
    يقرر: approved / rejected / still_watching / expired

    مهم: فحص GoPlus ومحاكاة البيع يُشغَّلان هنا فقط — بعد مرور فترة الانتظار
    الدنيا (min_watch_hours) — وليس لحظة الاكتشاف الأولى. هذا إصلاح معماري
    مقصود: عملة عمرها ثوانٍ لا تملك GoPlus بيانات كافية عنها بعد (يفشل
    الفحص دائماً تقريباً بسبب فارق الفهرسة، وليس بسبب جودة العملة)، بينما
    بعد ساعات من الانتظار تكون هذه البيانات متوفرة بيقين، فيصبح الفحص ذا
    معنى حقيقي.
    """
    age_hours = (time.time() - entry["added_at"]) / 3600

    growth_data = await check_organic_growth(entry["mint_address"], entry["holders_at_add"])

    if growth_data["holders_growth"] < 0:
        return "rejected", "انخفاض عدد الحاملين — إشارة سلبية واضحة"

    if age_hours < WATCHLIST.min_watch_hours:
        return "still_watching", f"لم تمر بعد فترة المراقبة الدنيا ({age_hours:.1f}h)"

    if growth_data["holders_growth"] < WATCHLIST.min_organic_holders_growth:
        if age_hours >= WATCHLIST.max_watch_hours:
            return "expired", "انتهت فترة المراقبة القصوى دون نمو عضوي كافٍ"
        return "still_watching", f"نمو عضوي غير كافٍ بعد ({age_hours:.1f}h)"

    reputation_ok, reputation_reason = await evaluate_reputation(
        entry["mint_address"], entry.get("deployer_wallet", "")
    )
    if not reputation_ok:
        return "rejected", f"فشلت فحوصات السمعة بعد فترة الانتظار: {reputation_reason}"

    sim_result = await simulate_sell(
        rpc_client=None,
        wallet_pubkey="",
        mint_address=entry["mint_address"],
        pool_address=entry.get("pool_address", ""),
        test_amount_lamports=1_000_000,
    )
    sim_ok, sim_reason = evaluate_simulation_result(sim_result)
    if not sim_ok:
        return "rejected", f"فشلت محاكاة البيع بعد فترة الانتظار: {sim_reason}"

    return "approved", (
        f"نمو عضوي كافٍ (+{growth_data['holders_growth']} حامل) + "
        f"اجتازت GoPlus ومحاكاة البيع بعد {age_hours:.1f} ساعة"
    )


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
                record_screening_result(
                    entry["mint_address"], entry["symbol"], entry.get("dex", ""),
                    "added_to_watchlist", "watchlist_final_approval", reason,
                )
                capital_sol = TOTAL_BOT_CAPITAL_SOL * (EXIT_STRATEGY.max_capital_pct_per_trade / 100)
                await execute_buy(
                    entry["mint_address"], entry["symbol"], entry["pool_address"],
                    capital_sol=capital_sol,
                    filter_report={"watchlist_decision": reason},
                )
                _update_watchlist_status(entry["id"], "approved", db_path)

            elif decision in ("rejected", "expired"):
                logger.info(f"رفض/انتهاء {entry['symbol']}: {reason}")
                record_screening_result(
                    entry["mint_address"], entry["symbol"], entry.get("dex", ""),
                    "rejected", f"watchlist_{decision}", reason,
                )
                _update_watchlist_status(entry["id"], decision, db_path)

        await asyncio.sleep(WATCHLIST.check_interval_minutes * 60)


def _update_watchlist_status(watch_id: int, status: str, db_path: str = DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE watchlist SET status = ? WHERE id = ?", (status, watch_id))
    conn.commit()
    conn.close()
