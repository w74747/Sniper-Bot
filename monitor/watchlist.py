"""
قائمة الانتظار (Watchlist) + المسار السريع (Fast Track)
النسخة المحسّنة الكاملة مع logging مثالي

المسار العادي: 24-72 ساعة انتظار قبل فحص GoPlus/محاكاة البيع النهائي.
المسار السريع: يعمل بالتوازي، يفحص كل 30 ثانية العملات الحديثة (<60 دقيقة)
بحثاً عن "انطلاق صاروخي" (momentum)، ويُسرّع الشراء عند وجوده — لكن بنفس
شروط الأمان الصارمة (GoPlus + محاكاة بيع)، بلا أي تنازل.

جدول watchlist نفسه أصبح الآن في Postgres (db/pool.py) بدل SQLite —
يشارك نفس آلية التبديل التلقائي (أساسي/احتياطي) مع بقية قاعدة البيانات.
"""
import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

from config.settings import WATCHLIST, EXIT_STRATEGY, FAST_TRACK, USE_DEVNET
from db import pool
from db.trades import record_screening_result
from trading.executor import execute_buy
from trading.swap_client import load_wallet_keypair
from filters.reputation import evaluate_reputation
from filters.sell_simulation import simulate_sell, evaluate_simulation_result
from filters.momentum import check_momentum
from filters.tatum_check import verify_mint_authority_disabled
from utils.solana_rpc import get_token_largest_accounts, rpc_call, get_wallet_sol_balance

logger = logging.getLogger("watchlist")

SOL_FEE_RESERVE = 0.01
DEVNET_FALLBACK_CAPITAL_SOL = 1.0

WATCHLIST_REJECTION_COOLDOWN_HOURS = 6
ORGANIC_CHECK_WINDOW_HOURS = 3


async def init_watchlist_table():
    """جدول watchlist أصبح جزءاً من db.trades.init_db() الموحّد — هذه الدالة محفوظة للتوافق فقط."""
    from db.trades import init_db
    await init_db()
    logger.debug("✅ جدول watchlist جاهز")


@dataclass
class WatchlistEntry:
    mint_address: str
    symbol: str
    pool_address: str
    initial_filter_report: str
    holders_at_add: int = 0
    dex: str = ""
    deployer_wallet: str = ""


async def add_to_watchlist(entry: WatchlistEntry) -> int:
    """إضافة عملة جديدة للـ watchlist"""
    try:
        logger.info(f"🚀 إضافة عملة للـ watchlist: {entry.symbol} ({entry.dex})")
        logger.debug(f"   📍 Mint: {entry.mint_address[:16]}... | Pool: {entry.pool_address[:16]}...")
        
        row = await pool.fetchrow(
            """INSERT INTO watchlist
               (mint_address, symbol, pool_address, dex, deployer_wallet,
                added_at, initial_filter_report, holders_at_add)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id""",
            entry.mint_address, entry.symbol, entry.pool_address, entry.dex,
            entry.deployer_wallet, time.time(), entry.initial_filter_report,
            entry.holders_at_add,
        )
        watch_id = row["id"]
        logger.info(f"✅ تمت إضافة {entry.symbol} بنجاح (#{watch_id})")
        return watch_id
    except Exception as e:
        logger.error(f"❌ فشل إضافة {entry.symbol}: {e}")
        raise


async def is_already_in_watchlist(mint_address: str) -> bool:
    """يفحص إن كان يجب منع إعادة إضافة هذه العملة لـ watchlist"""
    try:
        row = await pool.fetchrow(
            """SELECT status, added_at FROM watchlist
               WHERE mint_address = $1
               ORDER BY added_at DESC LIMIT 1""",
            mint_address,
        )
        if row is None:
            return False

        status = row["status"]
        if status in ("watching", "approved"):
            logger.debug(f"⚠️ العملة موجودة بالفعل (status: {status})")
            return True

        hours_since = (time.time() - row["added_at"]) / 3600
        if hours_since < WATCHLIST_REJECTION_COOLDOWN_HOURS:
            logger.debug(f"⏳ العملة قيد التهدئة ({hours_since:.1f}h)")
            return True
        
        return False
    except Exception as e:
        logger.error(f"❌ خطأ في فحص watchlist: {e}")
        return False


async def check_organic_growth(mint_address: str, holders_at_add: int) -> dict:
    """يفحص النمو العضوي للعملة"""
    try:
        age_minutes = (time.time() - holders_at_add) / 60 if holders_at_add > 0 else 1000
        is_new = age_minutes < 60
        
        logger.debug(f"🔍 فحص النمو العضوي (عمر: {age_minutes:.1f}m)")
        
        largest_accounts = await get_token_largest_accounts(
            mint_address,
            is_new_token=is_new
        )
        current_holders = sum(1 for h in largest_accounts if float(h.get("amount", 0)) > 0)
    except Exception as e:
        logger.warning(f"⚠️ تعذّر فحص النمو: {e}")
        current_holders = holders_at_add

    holders_growth = current_holders - holders_at_add
    logger.debug(f"📊 نمو الحاملين: {holders_growth} ({holders_at_add} → {current_holders})")

    return {
        "current_holders": current_holders,
        "holders_growth": holders_growth,
        "organic_volume_ratio": None,
    }


async def run_security_checks(mint_address: str, deployer_wallet: str, pool_address: str) -> tuple[bool, str]:
    """فحوصات الأمان المشتركة (GoPlus + محاكاة البيع)"""
    
    logger.debug(f"🔐 بدء فحوصات الأمان للعملة {mint_address[:16]}...")
    
    # 1. فحص السمعة (GoPlus)
    logger.debug("  🔍 1️⃣ فحص السمعة...")
    try:
        reputation_ok, reputation_reason = await evaluate_reputation(mint_address, deployer_wallet)
        if not reputation_ok:
            logger.warning(f"❌ السمعة فشلت: {reputation_reason}")
            return False, f"السمعة: {reputation_reason}"
        logger.debug(f"  ✅ السمعة: نجح!")
    except Exception as e:
        logger.error(f"❌ خطأ فحص السمعة: {e}")
        return False, f"خطأ السمعة: {e}"

    # 2. محاكاة البيع
    logger.debug("  🔍 2️⃣ محاكاة البيع...")
    try:
        sim_result = await simulate_sell(
            rpc_client=None,
            wallet_pubkey="",
            mint_address=mint_address,
            pool_address=pool_address,
            test_amount_lamports=1_000_000,
        )
        
        if not sim_result.can_sell:
            logger.warning(f"❌ البيع فشل: {sim_result.reason}")
            return False, f"البيع: {sim_result.reason}"
        
        logger.debug(f"  ✅ البيع: نجح! (ضريبة: {sim_result.effective_sell_tax_pct:.2f}%)")
    except Exception as e:
        logger.error(f"❌ خطأ محاكاة البيع: {e}")
        return False, f"خطأ البيع: {e}"

    # 3. فحص Tatum
    logger.debug("  🔍 3️⃣ فحص Tatum...")
    try:
        tatum_ok, tatum_reason = await verify_mint_authority_disabled(mint_address)
        if not tatum_ok:
            logger.warning(f"⚠️ تحذير Tatum: {tatum_reason}")
        else:
            logger.debug(f"  ✅ Tatum: نجح!")
    except Exception as e:
        logger.warning(f"⚠️ خطأ Tatum: {e}")

    logger.debug("✅ اجتيازت جميع الفحوصات!")
    return True, "اجتيازت الأمان"


async def evaluate_watchlist_entry(entry: dict) -> tuple[str, str]:
    """المسار العادي (24-72 ساعة): يقيّم ما إذا كانت العملة جاهزة للشراء"""
    age_hours = (time.time() - entry["added_at"]) / 3600

    if age_hours < (WATCHLIST.min_watch_hours - ORGANIC_CHECK_WINDOW_HOURS):
        logger.debug(f"⏳ [{entry['symbol']}] لم تدخل نافذة الفحص ({age_hours:.1f}h)")
        return "still_watching", f"انتظار ({age_hours:.1f}h)"

    growth_data = await check_organic_growth(entry["mint_address"], entry["holders_at_add"])

    if growth_data["holders_growth"] < 0:
        logger.warning(f"❌ [{entry['symbol']}] انخفاض الحاملين")
        return "rejected", "انخفاض الحاملين"

    if age_hours < WATCHLIST.min_watch_hours:
        logger.debug(f"⏳ [{entry['symbol']}] لم تمر الفترة الدنيا ({age_hours:.1f}h)")
        return "still_watching", "فترة انتظار"

    if growth_data["holders_growth"] < WATCHLIST.min_organic_holders_growth:
        if age_hours >= WATCHLIST.max_watch_hours:
            logger.warning(f"❌ [{entry['symbol']}] انتهت المدة بدون نمو")
            return "expired", "انتهت المدة"
        logger.debug(f"⏳ [{entry['symbol']}] نمو غير كافٍ")
        return "still_watching", "نمو غير كافٍ"

    logger.debug(f"🔍 [{entry['symbol']}] بدء فحوصات الأمان...")
    security_ok, security_reason = await run_security_checks(
        entry["mint_address"], entry.get("deployer_wallet", ""), entry.get("pool_address", "")
    )
    if not security_ok:
        logger.warning(f"❌ [{entry['symbol']}] فشل الأمان")
        return "rejected", security_reason

    logger.info(f"✅ [{entry['symbol']}] موافقة للشراء!")
    return "approved", security_reason


async def evaluate_fast_track_entry(entry: dict) -> Optional[tuple[str, str]]:
    """المسار السريع: يفحص الانطلاق الصاروخي"""
    age_minutes = (time.time() - entry["added_at"]) / 60
    if age_minutes > FAST_TRACK.max_entry_age_minutes:
        logger.debug(f"⏳ [{entry['symbol']}] عمرها أكثر من {FAST_TRACK.max_entry_age_minutes}m")
        return None

    logger.debug(f"🔍 [{entry['symbol']}] فحص الزخم...")
    momentum_ok, momentum_reason = await check_momentum(entry["mint_address"])
    if not momentum_ok:
        logger.debug(f"📊 [{entry['symbol']}] لا زخم")
        return None

    logger.info(f"🚀 [{entry['symbol']}] زخم قوي! {momentum_reason}")
    security_ok, security_reason = await run_security_checks(
        entry["mint_address"], entry.get("deployer_wallet", ""), entry.get("pool_address", "")
    )
    if not security_ok:
        logger.warning(f"❌ [{entry['symbol']}] زخم لكن فشل الأمان")
        return "rejected", security_reason

    logger.info(f"✅ [{entry['symbol']}] مسار سريع - موافقة!")
    return "approved", security_reason


async def _get_current_capital_sol() -> float:
    """يرجع الرصيد الفعلي القابل للاستخدام"""
    if USE_DEVNET:
        logger.debug(f"💰 DEVNET: {DEVNET_FALLBACK_CAPITAL_SOL} SOL")
        return DEVNET_FALLBACK_CAPITAL_SOL

    try:
        keypair = load_wallet_keypair()
        actual_balance = await get_wallet_sol_balance(str(keypair.pubkey()))
        usable = max(actual_balance - SOL_FEE_RESERVE, 0.0)
        logger.debug(f"💰 الرصيد: {actual_balance:.4f} SOL (قابل: {usable:.4f})")
        return usable
    except Exception as e:
        logger.error(f"❌ خطأ قراءة الرصيد: {e}")
        return 0.0


async def _execute_approval(entry: dict, reason: str, stage: str):
    """تنفيذ الشراء"""
    logger.info(f"💰 تنفيذ الشراء: {entry['symbol']} ({stage})")
    
    current_capital = await _get_current_capital_sol()
    if current_capital <= 0:
        logger.error(f"❌ رصيد غير كافٍ: {current_capital:.4f} SOL")
        return

    # فحص Tatum النهائي
    logger.debug("🔍 فحص Tatum قبل الشراء...")
    tatum_safe, tatum_reason = await verify_mint_authority_disabled(entry["mint_address"])
    if not tatum_safe:
        logger.error(f"⛔ إلغاء الشراء: {tatum_reason}")
        await record_screening_result(
            entry["mint_address"], entry["symbol"], entry.get("dex", ""),
            "rejected", f"{stage}_tatum", tatum_reason,
        )
        await _update_watchlist_status(entry["id"], "rejected")
        return
    logger.debug(f"✅ Tatum: {tatum_reason}")

    await record_screening_result(
        entry["mint_address"], entry["symbol"], entry.get("dex", ""),
        "added_to_watchlist", stage, reason,
    )
    
    capital_sol = current_capital * (EXIT_STRATEGY.max_capital_pct_per_trade / 100)
    logger.info(f"📊 مبلغ الشراء: {capital_sol:.4f} SOL")
    
    try:
        await execute_buy(
            entry["mint_address"], entry["symbol"], entry["pool_address"],
            capital_sol=capital_sol,
            filter_report={"decision": reason, "stage": stage},
        )
        logger.info(f"✅ تم الشراء بنجاح! {entry['symbol']}")
    except Exception as e:
        logger.error(f"❌ فشل الشراء: {e}")
    
    await _update_watchlist_status(entry["id"], "approved")


async def run_watchlist_loop():
    """حلقة المسار العادي (24-72 ساعة)"""
    logger.info("🚀 بدء حلقة المسار العادي (watchlist loop)...")
    await init_watchlist_table()
    
    iteration = 0
    while True:
        iteration += 1
        try:
            rows = await pool.fetch("SELECT * FROM watchlist WHERE status = 'watching'")
            
            if rows:
                logger.info(f"🔍 [#{iteration}] فحص {len(rows)} عملة في المسار العادي")
            else:
                logger.debug(f"⏳ [#{iteration}] لا توجد عملات قيد المراقبة")

            for row in rows:
                entry = dict(row)
                try:
                    decision, reason = await evaluate_watchlist_entry(entry)

                    if decision == "approved":
                        await _execute_approval(entry, reason, "watchlist_approval")
                    elif decision in ("rejected", "expired"):
                        logger.info(f"❌ {entry['symbol']}: {reason}")
                        await record_screening_result(
                            entry["mint_address"], entry["symbol"], entry.get("dex", ""),
                            "rejected", f"watchlist_{decision}", reason,
                        )
                        await _update_watchlist_status(entry["id"], decision)
                except Exception as e:
                    logger.error(f"⚠️ خطأ {entry.get('symbol', '?')}: {e}")
        except Exception as e:
            logger.error(f"⚠️ خطأ عام في حلقة المسار العادي: {e}")

        await asyncio.sleep(WATCHLIST.check_interval_minutes * 60)


async def run_fast_track_loop():
    """حلقة المسار السريع (30 ثانية)"""
    if not FAST_TRACK.enabled:
        logger.info("ℹ️ المسار السريع معطّل")
        return

    await init_watchlist_table()
    logger.info("🚀 بدء حلقة المسار السريع (fast-track loop)...")

    iteration = 0
    while True:
        iteration += 1
        try:
            cutoff_timestamp = time.time() - (FAST_TRACK.max_entry_age_minutes * 60)
            rows = await pool.fetch(
                "SELECT * FROM watchlist WHERE status = 'watching' AND added_at >= $1",
                cutoff_timestamp,
            )

            if rows:
                logger.debug(f"🔍 [#{iteration}] فحص {len(rows)} عملة في المسار السريع")

            for row in rows:
                entry = dict(row)
                try:
                    result = await evaluate_fast_track_entry(entry)

                    if result is None:
                        continue

                    decision, reason = result
                    if decision == "approved":
                        await _execute_approval(entry, reason, "fast_track_approval")
                    elif decision == "rejected":
                        logger.warning(f"❌ رفض مسار سريع: {entry['symbol']}")
                        await record_screening_result(
                            entry["mint_address"], entry["symbol"], entry.get("dex", ""),
                            "rejected", "fast_track_rejected", reason,
                        )
                except Exception as e:
                    logger.error(f"⚠️ خطأ مسار سريع {entry.get('symbol', '?')}: {e}")
        except Exception as e:
            logger.error(f"⚠️ خطأ عام في حلقة المسار السريع: {e}")

        await asyncio.sleep(FAST_TRACK.check_interval_seconds)


async def _update_watchlist_status(watch_id: int, status: str):
    """تحديث حالة العملة"""
    try:
        await pool.execute("UPDATE watchlist SET status = $1 WHERE id = $2", status, watch_id)
        logger.debug(f"✅ تم تحديث #{watch_id} → {status}")
    except Exception as e:
        logger.error(f"❌ فشل تحديث #{watch_id}: {e}")


async def get_open_watchlist_count() -> int:
    """حساب عدد العملات المراقبة"""
    try:
        count = await pool.fetchval("SELECT COUNT(*) FROM watchlist WHERE status = 'watching'")
        logger.info(f"📊 عدد العملات المراقبة: {count}")
        return count
    except Exception as e:
        logger.error(f"❌ خطأ حساب العدد: {e}")
        return 0
