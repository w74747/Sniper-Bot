"""
قائمة الانتظار (Watchlist) + المسار السريع (Fast Track)
مع logging تفصيلي لتشخيص مشاكل الفلاتر والصفقات
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

# 📊 معدادات للإحصائيات
_stats = {
    "tokens_checked": 0,
    "tokens_passed_onchain": 0,
    "tokens_passed_reputation": 0,
    "tokens_passed_sell": 0,
    "tokens_passed_all": 0,
    "tokens_failed": 0,
}

async def init_watchlist_table():
    """جدول watchlist أصبح جزءاً من db.trades.init_db() الموحّد — هذه الدالة محفوظة للتوافق فقط."""
    from db.trades import init_db
    await init_db()
    logger.info("✅ جدول watchlist جاهز")


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
    logger.info(f"✅ تمت إضافة {entry.symbol} إلى watchlist (#{watch_id})")
    return watch_id


async def is_already_in_watchlist(mint_address: str) -> bool:
    """يفحص إن كان يجب منع إعادة إضافة هذه العملة للـ watchlist"""
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
        logger.debug(f"⚠️ العملة {mint_address[:8]}... موجودة بالفعل في watchlist")
        return True

    # rejected / expired — نسمح بعد فترة تهدئة قصيرة فقط
    hours_since = (time.time() - row["added_at"]) / 3600
    if hours_since < WATCHLIST_REJECTION_COOLDOWN_HOURS:
        logger.debug(f"⏳ العملة {mint_address[:8]}... قيد التهدئة ({hours_since:.1f}h)")
        return True
    
    return False


async def check_organic_growth(mint_address: str, holders_at_add: int) -> dict:
    """يفحص النمو العضوي للعملة مع logging"""
    try:
        age_minutes = (time.time() - holders_at_add) / 60 if holders_at_add > 0 else 1000
        is_new = age_minutes < 60
        
        logger.debug(f"🔍 فحص النمو العضوي (عمر: {age_minutes:.1f} دقيقة)")
        
        largest_accounts = await get_token_largest_accounts(
            mint_address,
            is_new_token=is_new
        )
        current_holders = sum(1 for h in largest_accounts if float(h.get("amount", 0)) > 0)
    except Exception as e:
        logger.warning(f"⚠️ تعذّر فحص النمو العضوي: {e}")
        current_holders = holders_at_add

    holders_growth = current_holders - holders_at_add
    logger.info(f"📊 نمو الحاملين: {holders_growth} (+{holders_growth})")

    return {
        "current_holders": current_holders,
        "holders_growth": holders_growth,
        "organic_volume_ratio": None,
    }


async def run_security_checks(mint_address: str, deployer_wallet: str, pool_address: str) -> tuple[bool, str]:
    """فحوصات الأمان المشتركة مع logging تفصيلي"""
    
    logger.info(f"\n{'='*60}")
    logger.info(f"🔐 بدء فحوصات الأمان للعملة {mint_address[:16]}...")
    logger.info(f"{'='*60}")
    
    # 1. فحص السمعة (GoPlus)
    logger.info("🔍 1️⃣ فحص السمعة (GoPlus)...")
    reputation_ok, reputation_reason = await evaluate_reputation(mint_address, deployer_wallet)
    if not reputation_ok:
        logger.warning(f"❌ فشل فحص السمعة: {reputation_reason}")
        _stats["tokens_failed"] += 1
        return False, f"فشل السمعة: {reputation_reason}"
    logger.info("✅ السمعة: نجح!")
    _stats["tokens_passed_reputation"] += 1

    # 2. محاكاة البيع
    logger.info("🔍 2️⃣ محاكاة البيع...")
    sim_result = await simulate_sell(
        rpc_client=None,
        wallet_pubkey="",
        mint_address=mint_address,
        pool_address=pool_address,
        test_amount_lamports=1_000_000,
    )
    
    if not sim_result.can_sell:
        logger.warning(f"❌ محاكاة البيع فشلت: {sim_result.reason}")
        _stats["tokens_failed"] += 1
        return False, f"فشل البيع: {sim_result.reason}"
    
    logger.info(f"✅ محاكاة البيع: نجحت! (ضريبة: {sim_result.effective_sell_tax_pct:.2f}%)")
    _stats["tokens_passed_sell"] += 1

    # 3. فحص Tatum النهائي (اختياري)
    logger.info("🔍 3️⃣ فحص Tatum النهائي...")
    tatum_ok, tatum_reason = await verify_mint_authority_disabled(mint_address)
    if not tatum_ok:
        logger.warning(f"⚠️ تحذير Tatum: {tatum_reason}")
    else:
        logger.info("✅ فحص Tatum: نجح!")

    logger.info(f"{'='*60}")
    logger.info("✅ اجتيازت جميع فحوصات الأمان!")
    logger.info(f"{'='*60}\n")
    _stats["tokens_passed_all"] += 1
    return True, "اجتيازت جميع الفحوصات"


async def process_new_token_from_mempool(
    mint_address: str,
    symbol: str,
    pool_address: str,
    deployer_wallet: str,
    dex: str,
    holders: int
) -> bool:
    """معالج العملة الجديدة المكتشفة من mempool مع logging شامل"""
    
    _stats["tokens_checked"] += 1
    
    logger.info(f"\n🚀 عملة جديدة مكتشفة: {symbol}")
    logger.info(f"   Mint: {mint_address[:16]}...")
    logger.info(f"   Pool: {pool_address[:16]}...")
    logger.info(f"   Holders: {holders}")
    logger.info(f"   DEX: {dex}")
    
    # 1. تحقق إذا كانت موجودة بالفعل
    if await is_already_in_watchlist(mint_address):
        logger.warning(f"⚠️ العملة موجودة بالفعل في watchlist")
        return False

    # 2. فحوصات الأمان
    security_ok, security_reason = await run_security_checks(mint_address, deployer_wallet, pool_address)
    if not security_ok:
        logger.warning(f"❌ فشلت الفحوصات الأمنية: {security_reason}")
        await record_screening_result(
            mint_address, symbol, "rejected", {"reason": security_reason}
        )
        return False

    # 3. أضف للـ watchlist
    logger.info("➕ إضافة العملة للـ watchlist...")
    entry = WatchlistEntry(
        mint_address=mint_address,
        symbol=symbol,
        pool_address=pool_address,
        dex=dex,
        deployer_wallet=deployer_wallet,
        holders_at_add=holders,
        initial_filter_report="",
    )
    try:
        watch_id = await add_to_watchlist(entry)
        logger.info(f"✅ نجحت إضافة العملة (#{watch_id})")
        return True
    except Exception as e:
        logger.error(f"❌ فشل إضافة العملة للـ watchlist: {e}")
        return False


async def print_stats():
    """طباعة الإحصائيات"""
    logger.info(f"\n{'='*60}")
    logger.info("📊 إحصائيات الفحص:")
    logger.info(f"{'='*60}")
    logger.info(f"  • عملات مفحوصة: {_stats['tokens_checked']}")
    logger.info(f"  • نجحت السمعة: {_stats['tokens_passed_reputation']}")
    logger.info(f"  • نجحت محاكاة البيع: {_stats['tokens_passed_sell']}")
    logger.info(f"  • اجتيازت جميع الفلاتر: {_stats['tokens_passed_all']}")
    logger.info(f"  • فشلت: {_stats['tokens_failed']}")
    
    if _stats['tokens_checked'] > 0:
        success_rate = (_stats['tokens_passed_all'] / _stats['tokens_checked']) * 100
        logger.info(f"  • معدل النجاح: {success_rate:.1f}%")
    logger.info(f"{'='*60}\n")


# مثال على الاستخدام:
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )
    
    logger.info("🚀 تم تفعيل logging تفصيلي في watchlist.py")
