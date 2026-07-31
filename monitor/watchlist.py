"""
قائمة الانتظار (Watchlist) + المسار السريع (Fast Track).

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

from solders.pubkey import Pubkey

from config.settings import (
    WATCHLIST, EXIT_STRATEGY, FAST_TRACK, USE_DEVNET, HOLDER_VELOCITY,
    SUSTAINED_TREND, GRADUATION_PROXIMITY, RUGCHECK_MAX_SCORE, RUGCHECK_MAX_INSIDERS,
    ESTABLISHED_LIQUID, GMGN_MAX_RAT_TRADER_PCT, GMGN_MAX_BUNDLER_PCT, GMGN_MAX_RUG_RATIO,
    SYMBOL_BLOCKLIST_LOSS_THRESHOLD_PCT, SYMBOL_BLOCKLIST_MAX_OCCURRENCES,
)
from db import pool
from db.trades import (
    record_screening_result, get_strategy_trade_counts_all,
    get_matured_migrations, update_migration_status,
    is_symbol_blocklisted,
)
from trading.executor import execute_buy
from filters.honeypot_detector import detect_honeypot
from filters.safe_entry import validate_entry_comprehensive
from trading.swap_client import load_wallet_keypair
from filters.reputation import evaluate_reputation
from filters.sell_simulation import simulate_sell, evaluate_simulation_result
from filters.momentum import check_momentum, fetch_momentum_batch, evaluate_momentum
from filters.tatum_check import verify_mint_authority_disabled
from filters.onchain_filters import TokenMetadata, run_all_onchain_filters, parse_spl_mint_account
from utils.solana_rpc import (
    get_token_largest_accounts, rpc_call, get_wallet_sol_balance, get_account_info_base64,
)
from utils.rugcheck_client import get_token_report
from utils.gmgn_client import get_token_info as get_gmgn_token_info

logger = logging.getLogger("watchlist")

_TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
_ASSOCIATED_TOKEN_PROGRAM_ID = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")

SOL_FEE_RESERVE = 0.01
DEVNET_FALLBACK_CAPITAL_SOL = 1.0
WATCHLIST_REJECTION_COOLDOWN_HOURS = 6
ORGANIC_CHECK_WINDOW_HOURS = 3


async def init_watchlist_table():
    """جدول watchlist أصبح جزءاً من db.trades.init_db() الموحّد."""
    from db.trades import init_db
    await init_db()


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
    logger.info(f"تمت إضافة {entry.symbol} إلى قائمة المراقبة (#{watch_id})")
    return watch_id


async def is_already_in_watchlist(mint_address: str) -> bool:
    """
    يفحص إن كان يجب منع إعادة إضافة هذه العملة لـ watchlist.
    
    ✅ تم إصلاح الخطأ: استخدام .get() للوصول إلى dictionary بدل .attribute
    """
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
        return True

    hours_since = (time.time() - row["added_at"]) / 3600
    return hours_since < WATCHLIST_REJECTION_COOLDOWN_HOURS


async def run_onchain_filters_for_entry(entry: dict) -> tuple[bool, str]:
    """ينفّذ الفحص الأمني الكامل المكلف (RPC)"""
    mint_address = entry["mint_address"]
    dex = (entry.get("dex") or "").lower()
    pool_address = entry.get("pool_address", "")
    deployer_wallet = entry.get("deployer_wallet", "")

    try:
        mint_data_b64 = await get_account_info_base64(mint_address)
        mint_info = parse_spl_mint_account(mint_data_b64)
    except Exception as e:
        return False, f"تعذّر قراءة بيانات العقد تقنياً: {e}"

    total_supply = mint_info["supply"] or 1
    solscan_result = {"items": []}
    
    if solscan_result["items"]:
        holder_data_available = True
        non_lp_holder_pcts = []
        dev_wallet_pct = 0.0

        known_lp_addresses_solscan = set()
        if dex == "pump.fun" and pool_address:
            try:
                bonding_curve_pk = Pubkey.from_string(pool_address)
                mint_pk = Pubkey.from_string(mint_address)
                derived, _ = Pubkey.find_program_address(
                    [bytes(bonding_curve_pk), bytes(_TOKEN_PROGRAM_ID), bytes(mint_pk)],
                    _ASSOCIATED_TOKEN_PROGRAM_ID,
                )
                known_lp_addresses_solscan.add(str(derived))
            except Exception as e:
                logger.debug(f"تعذّر حساب ATA لـ bonding curve (مسار Solscan): {e}")

        for item in solscan_result["items"]:
            address = item["address"]
            pct = item["percentage"]
            if address in known_lp_addresses_solscan or address == pool_address:
                continue
            if address == deployer_wallet:
                dev_wallet_pct = max(dev_wallet_pct, pct)
            non_lp_holder_pcts.append(pct)

        top_holder_pct_excluding_lp = max(non_lp_holder_pcts, default=0.0)
        top10_holders_pct_excluding_lp = sum(sorted(non_lp_holder_pcts, reverse=True)[:10])
        logger.debug(f"[{entry.get('symbol', '?')}] فحص التوزيع عبر Solscan نجح")
    else:
        try:
            largest_accounts = await get_token_largest_accounts(mint_address)
            holder_data_available = True
        except Exception:
            largest_accounts = []
            holder_data_available = False

        dev_wallet_pct = 0.0
        known_lp_token_accounts = set()
        
        if dex == "pump.fun" and pool_address:
            try:
                bonding_curve_pk = Pubkey.from_string(pool_address)
                mint_pk = Pubkey.from_string(mint_address)
                derived, _ = Pubkey.find_program_address(
                    [bytes(bonding_curve_pk), bytes(_TOKEN_PROGRAM_ID), bytes(mint_pk)],
                    _ASSOCIATED_TOKEN_PROGRAM_ID,
                )
                known_lp_token_accounts.add(str(derived))
            except Exception as e:
                logger.debug(f"تعذّر حساب ATA لـ bonding curve: {e}")

        non_lp_holder_pcts = []
        for holder in largest_accounts:
            amount = float(holder.get("amount", 0))
            pct = (amount / total_supply) * 100 if total_supply else 0
            address = holder.get("address", "")
            if address in known_lp_token_accounts:
                continue
            if address == deployer_wallet:
                dev_wallet_pct = max(dev_wallet_pct, pct)
            non_lp_holder_pcts.append(pct)

        top_holder_pct_excluding_lp = max(non_lp_holder_pcts, default=0.0)
        top10_holders_pct_excluding_lp = sum(sorted(non_lp_holder_pcts, reverse=True)[:10])

    lp_burned_or_locked_pct = 100.0 if dex == "pump.fun" else 0.0

    meta = TokenMetadata(
        mint_address=mint_address,
        name=entry.get("symbol", ""),
        symbol=entry.get("symbol", ""),
        description="",
        dex=dex,
        total_supply=total_supply,
        mint_authority_active=mint_info["mint_authority_active"],
        freeze_authority_active=mint_info["freeze_authority_active"],
        lp_burned_or_locked_pct=lp_burned_or_locked_pct,
        dev_wallet_pct=dev_wallet_pct,
        top_holder_pct_excluding_lp=top_holder_pct_excluding_lp,
        top10_holders_pct_excluding_lp=top10_holders_pct_excluding_lp,
        holder_data_available=holder_data_available,
        is_standard_spl_token=True,
        has_transfer_restriction_hooks=False,
        has_referral_or_commission_function=False,
    )

    result = run_all_onchain_filters(meta)
    return result.passed, result.reason


async def check_organic_growth(mint_address: str, holders_at_add: int) -> dict:
    """يفحص المؤشرات العضوية الحالية مقابل لحظة الإضافة للـ watchlist"""
    solscan_result = {"total_holders": None}
    
    if solscan_result["total_holders"] is not None:
        current_holders = solscan_result["total_holders"]
        data_available = True
        logger.debug(f"فحص النمو العضوي لـ {mint_address} عبر Solscan نجح")
    else:
        try:
            largest_accounts = await get_token_largest_accounts(mint_address, max_retries=6)
            current_holders = sum(1 for h in largest_accounts if float(h.get("amount", 0)) > 0)
            data_available = True
        except Exception as e:
            logger.warning(f"تعذّر فحص النمو العضوي لـ {mint_address}: {e}")
            current_holders = holders_at_add
            data_available = False

    holders_growth = current_holders - holders_at_add

    return {
        "current_holders": current_holders,
        "holders_growth": holders_growth,
        "organic_volume_ratio": None,
        "data_available": data_available,
    }


async def run_security_checks(entry: dict) -> tuple[bool, str]:
    """فحوصات الأمان المشتركة الكاملة"""
    mint_address = entry["mint_address"]
    deployer_wallet = entry.get("deployer_wallet", "")
    pool_address = entry.get("pool_address", "")
    symbol = entry.get("symbol", "")

    if symbol:
        blocked, count = await is_symbol_blocklisted(symbol, SYMBOL_BLOCKLIST_MAX_OCCURRENCES)
        if blocked:
            return False, (
                f"الاسم '{symbol}' محظور دائماً — سجّل {count} خسارة كارثية "
                f"سابقة (أسوأ من {SYMBOL_BLOCKLIST_LOSS_THRESHOLD_PCT}%)"
            )

    onchain_ok, onchain_reason = await run_onchain_filters_for_entry(entry)
    if not onchain_ok:
        return False, f"فشل الفحص الأساسي: {onchain_reason}"

    rugcheck_result = await get_token_report(mint_address)
    if rugcheck_result["available"]:
        if rugcheck_result["rugged"]:
            return False, f"RugCheck: مُصنَّفة كـrug pull مؤكَّد"
        if rugcheck_result["score_normalised"] > RUGCHECK_MAX_SCORE:
            return False, (
                f"RugCheck: درجة خطر {rugcheck_result['score_normalised']:.0f}/100"
            )
        if rugcheck_result["insiders_detected"] > RUGCHECK_MAX_INSIDERS:
            return False, (
                f"RugCheck: {rugcheck_result['insiders_detected']} محفظة مطّلعة"
            )

    gmgn_result = await get_gmgn_token_info(mint_address)
    if gmgn_result["available"]:
        if gmgn_result["rat_trader_pct"] > GMGN_MAX_RAT_TRADER_PCT:
            return False, f"GMGN: نسبة المحافظ المُرتزقة {gmgn_result['rat_trader_pct']:.1f}%"
        if gmgn_result["bundler_pct"] > GMGN_MAX_BUNDLER_PCT:
            return False, f"GMGN: نسبة الشراء المُجمَّع {gmgn_result['bundler_pct']:.1f}%"
        if gmgn_result["rug_ratio"] > GMGN_MAX_RUG_RATIO:
            return False, f"GMGN: درجة احتمال rug {gmgn_result['rug_ratio']:.2f}"

    reputation_ok, reputation_reason = await evaluate_reputation(mint_address, deployer_wallet)
    if not reputation_ok:
        return False, f"فشلت فحوصات السمعة: {reputation_reason}"

    sim_result = await simulate_sell(
        rpc_client=None,
        wallet_pubkey="",
        mint_address=mint_address,
        pool_address=pool_address,
        test_amount_lamports=1_000_000,
    )
    sim_ok, sim_reason = evaluate_simulation_result(sim_result)
    if not sim_ok:
        return False, f"فشلت محاكاة البيع: {sim_reason}"

    return True, f"reputation={reputation_reason} | sell={sim_reason}"


async def evaluate_watchlist_entry(entry: dict) -> tuple[str, str]:
    """
    ✅ تم إصلاح الخطأ الحرج: استخدام .get() بدل .attribute
    """
    age_hours = (time.time() - entry["added_at"]) / 3600
    
    # الإصلاح الأساسي: استخدام .get() مع قيم افتراضية
    min_watch_hours = WATCHLIST.get("min_watch_hours", 24)
    max_watch_hours = WATCHLIST.get("max_watch_hours", 72)
    min_organic_holders_growth = WATCHLIST.get("min_organic_holders_growth", 10)

    if age_hours < (min_watch_hours - ORGANIC_CHECK_WINDOW_HOURS):
        return "still_watching", f"لم تدخل بعد نافذة الفحص النهائي ({age_hours:.1f}h)"

    growth_data = await check_organic_growth(entry["mint_address"], entry["holders_at_add"])

    if not growth_data["data_available"]:
        if age_hours >= max_watch_hours * 3:
            return "expired", (
                f"فشل تقني متكرر في القياس لفترة طويلة جداً ({age_hours:.1f}h)"
            )
        return "still_watching", (
            f"تعذّر قياس النمو تقنياً هذه الدورة ({age_hours:.1f}h)"
        )

    if growth_data["holders_growth"] < 0:
        return "rejected", "انخفاض عدد الحاملين"

    if age_hours < min_watch_hours:
        return "still_watching", f"لم تمر بعد فترة المراقبة الدنيا ({age_hours:.1f}h)"

    if growth_data["holders_growth"] < min_organic_holders_growth:
        if age_hours >= max_watch_hours:
            return "expired", "انتهت فترة المراقبة دون نمو عضوي كافٍ"
        return "still_watching", f"نمو عضوي غير كافٍ بعد ({age_hours:.1f}h)"

    security_ok, security_reason = await run_security_checks(entry)
    if not security_ok:
        return "rejected", f"{security_reason}"

    return "approved", (
        f"نمو عضوي كافٍ (+{growth_data['holders_growth']} حامل) + "
        f"اجتازت الأمان بعد {age_hours:.1f} ساعة"
    )


async def evaluate_holder_velocity_entry(entry: dict) -> Optional[tuple[str, str, float]]:
    """استراتيجية معدل انضمام الحاملين"""
    if not HOLDER_VELOCITY.get("enabled", False):
        return None

    age_minutes = (time.time() - entry["added_at"]) / 60
    max_age = FAST_TRACK.get("max_entry_age_minutes", 60)
    
    if age_minutes > max_age:
        return None

    age_seconds = time.time() - entry["added_at"]
    min_age_sec = FAST_TRACK.get("min_age_seconds_before_momentum_check", 5)
    
    if age_seconds < min_age_sec:
        return None

    total_holders = None
    if total_holders is None:
        return None

    min_holders_per_min = HOLDER_VELOCITY.get("min_holders_per_minute", 1)
    holder_velocity = total_holders / age_minutes if age_minutes > 0 else 0
    
    if holder_velocity < min_holders_per_min:
        return None

    security_ok, security_reason = await run_security_checks(entry)
    if not security_ok:
        return ("rejected", f"سرعة حاملين قوية لكن فشل الأمان: {security_reason}", 0.0)

    return (
        "approved",
        f"⚡ سرعة الحاملين: {total_holders} حاملاً خلال {age_minutes:.1f} دقيقة",
        holder_velocity,
    )


_previous_momentum_positive: dict = {}


async def evaluate_sustained_trend_entry(entry: dict, prefetched_momentum=None) -> Optional[tuple[str, str, float]]:
    """استراتيجية الزخم المستدام"""
    if not SUSTAINED_TREND.get("enabled", False) or prefetched_momentum is None:
        return None

    age_seconds = time.time() - entry["added_at"]
    min_age_sec = FAST_TRACK.get("min_age_seconds_before_momentum_check", 5)
    
    if age_seconds < min_age_sec:
        return None
    
    age_minutes = (time.time() - entry["added_at"]) / 60
    max_age = FAST_TRACK.get("max_entry_age_minutes", 60)
    
    if age_minutes > max_age:
        return None

    mint_address = entry["mint_address"]
    price_change = prefetched_momentum.price_change_m5_pct
    max_price_change = SUSTAINED_TREND.get("max_price_change_m5_pct", 1000)

    if price_change > max_price_change:
        _previous_momentum_positive[mint_address] = False
        return None

    min_price_change = SUSTAINED_TREND.get("min_price_change_m5_pct", 5)
    current_positive = price_change >= min_price_change
    was_positive = _previous_momentum_positive.get(mint_address, False)
    _previous_momentum_positive[mint_address] = current_positive

    if not (current_positive and was_positive):
        return None

    security_ok, security_reason = await run_security_checks(entry)
    if not security_ok:
        return ("rejected", f"زخم مستدام لكن فشل الأمان: {security_reason}", price_change)

    return (
        "approved",
        f"📈 الزخم المستدام: +{price_change:.1f}%",
        price_change,
    )


async def evaluate_graduation_proximity_entry(entry: dict, prefetched_momentum=None) -> Optional[tuple[str, str, float]]:
    """استراتيجية قرب التخرج"""
    if not GRADUATION_PROXIMITY.get("enabled", False) or prefetched_momentum is None:
        return None
    if (entry.get("dex") or "").lower() != "pump.fun":
        return None

    age_seconds = time.time() - entry["added_at"]
    min_age_sec = FAST_TRACK.get("min_age_seconds_before_momentum_check", 5)
    
    if age_seconds < min_age_sec:
        return None
    
    age_minutes = (time.time() - entry["added_at"]) / 60
    max_age = FAST_TRACK.get("max_entry_age_minutes", 60)
    
    if age_minutes > max_age:
        return None

    market_cap = prefetched_momentum.market_cap_usd
    min_cap = GRADUATION_PROXIMITY.get("min_market_cap_usd", 50000)
    max_cap = GRADUATION_PROXIMITY.get("max_market_cap_usd", 100000)
    
    if not (min_cap <= market_cap <= max_cap):
        return None
    
    min_price_change = GRADUATION_PROXIMITY.get("min_price_change_m5_pct", 0)
    if prefetched_momentum.price_change_m5_pct < min_price_change:
        return None

    security_ok, security_reason = await run_security_checks(entry)
    if not security_ok:
        return ("rejected", f"قرب التخرج لكن فشل الأمان: {security_reason}", 0.0)

    return (
        "approved",
        f"🎓 قيمة سوقية ${market_cap:,.0f}",
        0.0,
    )


async def evaluate_fast_track_entry(entry: dict, prefetched_momentum=None) -> Optional[tuple[str, str, float]]:
    """المسار السريع: الزخم اللحظي"""
    age_minutes = (time.time() - entry["added_at"]) / 60
    max_age = FAST_TRACK.get("max_entry_age_minutes", 60)
    
    if age_minutes > max_age:
        return None

    age_seconds = time.time() - entry["added_at"]
    min_age_sec = FAST_TRACK.get("min_age_seconds_before_momentum_check", 5)
    
    if age_seconds < min_age_sec:
        return None

    if prefetched_momentum is not None:
        momentum_ok, momentum_reason = evaluate_momentum(prefetched_momentum)
        momentum_strength_pct = getattr(prefetched_momentum, "price_change_m5_pct", 0.0)
    else:
        momentum_ok, momentum_reason = await check_momentum(entry["mint_address"])
        momentum_strength_pct = 0.0

    if not momentum_ok:
        logger.debug(f"📊 [{entry['symbol']}] لا زخم كافٍ: {momentum_reason}")
        return None

    security_ok, security_reason = await run_security_checks(entry)
    if not security_ok:
        return "rejected", f"زخم قوي لكن فشل الأمان: {security_reason}", momentum_strength_pct

    return "approved", f"🚀 {momentum_reason}", momentum_strength_pct


async def _get_current_capital_sol() -> float:
    """يرجع الرصيد الفعلي القابل للاستخدام"""
    if USE_DEVNET:
        return DEVNET_FALLBACK_CAPITAL_SOL

    try:
        keypair = load_wallet_keypair()
        actual_balance = await get_wallet_sol_balance(str(keypair.pubkey()))
        usable = max(actual_balance - SOL_FEE_RESERVE, 0.0)
        return usable
    except Exception as e:
        logger.error(f"تعذّر قراءة الرصيد الفعلي: {e}")
        return 0.0


def _momentum_size_multiplier(momentum_strength_pct: float) -> float:
    """حساب مضاعف حجم الصفقة بناءً على قوة الزخم"""
    MIN_PCT = 5.0
    STRONG_PCT = 100.0
    MIN_MULT = 0.6
    MAX_MULT = 2.0

    if momentum_strength_pct <= 0:
        return 1.0
    if momentum_strength_pct <= MIN_PCT:
        return MIN_MULT
    if momentum_strength_pct >= STRONG_PCT:
        return MAX_MULT

    ratio = (momentum_strength_pct - MIN_PCT) / (STRONG_PCT - MIN_PCT)
    return MIN_MULT + ratio * (MAX_MULT - MIN_MULT)


async def _execute_approval(
    entry: dict, reason: str, stage: str, momentum_strength_pct: float = 0.0,
    strategy: str = "momentum_chase",
):
    """منطق تنفيذ الشراء المشترك"""
    is_long_term_entry = stage.startswith("established_liquid")

    current_capital = await _get_current_capital_sol()
    if current_capital <= 0:
        logger.warning(f"تخطّي شراء {entry['symbol']} — رصيد غير كافٍ")
        return

    tatum_safe, tatum_reason = await verify_mint_authority_disabled(entry["mint_address"])
    if not tatum_safe:
        logger.error(f"إلغاء شراء {entry['symbol']}: {tatum_reason}")
        await record_screening_result(
            entry["mint_address"], entry["symbol"], entry.get("dex", ""),
            "rejected", f"{stage}_tatum_final_check", tatum_reason,
        )
        if not is_long_term_entry:
            await _update_watchlist_status(entry["id"], "rejected")
        return

    logger.info(f"موافقة على شراء {entry['symbol']}: {reason}")
    
    size_multiplier = _momentum_size_multiplier(momentum_strength_pct)
    base_capital_sol = current_capital * (EXIT_STRATEGY.get("max_capital_pct_per_trade", 5) / 100)
    capital_sol = base_capital_sol * size_multiplier

    is_safe, honeypot_reason = await detect_honeypot(
        entry["mint_address"],
        min_liquidity_usd=5000.0,
        max_price_drop_pct=30.0
    )

    if not is_safe:
        logger.warning(f"رفض {entry['symbol']}: {honeypot_reason}")
        return

    await execute_buy(
        entry["mint_address"], entry["symbol"], entry["pool_address"],
        capital_sol=capital_sol,
        filter_report={"decision": reason, "stage": stage},
        strategy=strategy,
        deployer_wallet=entry.get("deployer_wallet", ""),
    )
    if not is_long_term_entry:
        await _update_watchlist_status(entry["id"], "approved")


async def evaluate_established_liquid_entry(entry: dict) -> Optional[tuple]:
    """استراتيجية العملات المستقرة المثبتة"""
    if not ESTABLISHED_LIQUID.get("enabled", False):
        return None

    mint_address = entry["mint_address"]
    momentum_batch = await fetch_momentum_batch([mint_address])
    data = momentum_batch.get(mint_address)
    if data is None:
        return None

    min_liquidity = ESTABLISHED_LIQUID.get("min_liquidity_usd", 100000)
    min_volume = ESTABLISHED_LIQUID.get("min_volume_h24_usd", 500000)
    max_drawdown = ESTABLISHED_LIQUID.get("max_drawdown_h24_pct", -50)
    
    if data.liquidity_usd < min_liquidity:
        return None
    if data.volume_h24_usd < min_volume:
        return None
    if data.price_change_h24_pct < max_drawdown:
        return None

    fake_entry = {
        "mint_address": mint_address,
        "symbol": entry.get("symbol", ""),
        "deployer_wallet": entry.get("deployer_wallet", ""),
        "pool_address": data.pair_address,
        "dex": "pump.fun",
    }
    security_ok, security_reason = await run_security_checks(fake_entry)
    if not security_ok:
        return ("rejected", f"استقرار مثبت لكن فشل الأمان: {security_reason}", 0.0, "established_liquid")

    entry["pool_address"] = data.pair_address

    return (
        "approved",
        f"💎 سيولة ${data.liquidity_usd:,.0f}",
        0.0, "established_liquid",
    )


async def run_established_liquid_loop():
    """حلقة العملات المستقرة الناضجة"""
    SCAN_INTERVAL_SECONDS = 3600

    while True:
        await asyncio.sleep(SCAN_INTERVAL_SECONDS)
        try:
            min_age_days = ESTABLISHED_LIQUID.get("min_age_days", 5)
            matured = await get_matured_migrations(min_age_days)
            logger.info(f"💎 فحص العملات الناضجة: {len(matured)} عملة")

            for entry in matured:
                try:
                    result = await evaluate_established_liquid_entry(entry)
                    if result is None:
                        continue

                    decision, reason, strength, strategy = result
                    if decision == "approved":
                        await _execute_approval(entry, reason, "established_liquid_approval", strategy=strategy)
                        await update_migration_status(entry["mint_address"], "approved")
                    elif decision == "rejected":
                        logger.info(f"رفض {entry['symbol']}: {reason}")
                        await record_screening_result(
                            entry["mint_address"], entry["symbol"], "pump.fun",
                            "rejected", "established_liquid_rejected", reason,
                        )
                        await update_migration_status(entry["mint_address"], "rejected")
                except Exception as e:
                    logger.error(f"خطأ في فحص {entry.get('symbol', '?')}: {e}")
        except Exception as e:
            logger.error(f"خطأ في حلقة العملات الراسخة: {e}")


async def run_watchlist_loop():
    """حلقة المسار العادي"""
    await init_watchlist_table()
    check_interval = WATCHLIST.get("check_interval_minutes", 15)
    
    while True:
        try:
            rows = await pool.fetch("SELECT * FROM watchlist WHERE status = 'watching'")

            for row in rows:
                entry = dict(row)
                try:
                    decision, reason = await evaluate_watchlist_entry(entry)

                    if decision == "approved":
                        await _execute_approval(entry, reason, "watchlist_final_approval", strategy="patient_organic")
                    elif decision in ("rejected", "expired"):
                        logger.info(f"رفض/انتهاء {entry['symbol']}: {reason}")
                        await record_screening_result(
                            entry["mint_address"], entry["symbol"], entry.get("dex", ""),
                            "rejected", f"watchlist_{decision}", reason,
                        )
                        await _update_watchlist_status(entry["id"], decision)
                except Exception as e:
                    logger.error(f"خطأ في معالجة {entry.get('symbol', '?')}: {e}")
        except Exception as e:
            logger.error(f"خطأ عام في المسار العادي: {e}")

        await asyncio.sleep(check_interval * 60)


async def _try_momentum_chase(entry: dict, prefetched) -> Optional[tuple]:
    result = await evaluate_fast_track_entry(entry, prefetched_momentum=prefetched)
    if result is None:
        return None
    decision, reason, strength = result
    return decision, reason, strength, "momentum_chase"


async def _try_holder_velocity(entry: dict, prefetched) -> Optional[tuple]:
    result = await evaluate_holder_velocity_entry(entry)
    if result is None:
        return None
    decision, reason, _ = result
    return decision, reason, 0.0, "holder_velocity"


async def _try_sustained_trend(entry: dict, prefetched) -> Optional[tuple]:
    result = await evaluate_sustained_trend_entry(entry, prefetched_momentum=prefetched)
    if result is None:
        return None
    decision, reason, strength = result
    return decision, reason, strength, "sustained_trend"


async def _try_graduation_proximity(entry: dict, prefetched) -> Optional[tuple]:
    result = await evaluate_graduation_proximity_entry(entry, prefetched_momentum=prefetched)
    if result is None:
        return None
    decision, reason, _ = result
    return decision, reason, 0.0, "graduation_proximity"


_STRATEGY_EVALUATORS = {
    "momentum_chase": _try_momentum_chase,
    "holder_velocity": _try_holder_velocity,
    "sustained_trend": _try_sustained_trend,
    "graduation_proximity": _try_graduation_proximity,
}
_FAST_TRACK_STRATEGY_NAMES = list(_STRATEGY_EVALUATORS.keys())


async def run_fast_track_loop():
    """حلقة المسار السريع"""
    if not FAST_TRACK.get("enabled", False):
        logger.info("المسار السريع معطّل")
        return

    await init_watchlist_table()
    check_interval = FAST_TRACK.get("check_interval_seconds", 30)
    max_age = FAST_TRACK.get("max_entry_age_minutes", 60)
    
    logger.info("بدء المسار السريع...")

    while True:
        try:
            cutoff_timestamp = time.time() - (max_age * 60)
            rows = await pool.fetch(
                "SELECT * FROM watchlist WHERE status = 'watching' AND added_at >= $1",
                cutoff_timestamp,
            )

            now_ts = time.time()
            min_age_sec = FAST_TRACK.get("min_age_seconds_before_momentum_check", 5)
            eligible_rows = [
                row for row in rows
                if (now_ts - row["added_at"]) >= min_age_sec
            ]
            mint_addresses = [row["mint_address"] for row in eligible_rows]
            momentum_by_mint = await fetch_momentum_batch(mint_addresses) if mint_addresses else {}

            try:
                strategy_counts = await get_strategy_trade_counts_all()
            except Exception as e:
                logger.warning(f"تعذّر جلب عدد الصفقات: {e}")
                strategy_counts = {}
            
            for s in _FAST_TRACK_STRATEGY_NAMES:
                strategy_counts.setdefault(s, 0)
            priority_order = sorted(_FAST_TRACK_STRATEGY_NAMES, key=lambda s: strategy_counts.get(s, 0))

            for row in rows:
                entry = dict(row)
                try:
                    prefetched = momentum_by_mint.get(entry["mint_address"])
                    handled = False
                    
                    for strategy_name in priority_order:
                        if handled:
                            break
                        evaluator = _STRATEGY_EVALUATORS[strategy_name]
                        result = await evaluator(entry, prefetched)
                        if result is None:
                            continue

                        decision, reason, strength, strat = result
                        if decision == "approved":
                            await _execute_approval(
                                entry, reason, "fast_track_approval",
                                momentum_strength_pct=strength, strategy=strat,
                            )
                            handled = True
                        elif decision == "rejected":
                            logger.info(f"رفض ({strat}) {entry['symbol']}: {reason}")
                            await record_screening_result(
                                entry["mint_address"], entry["symbol"], entry.get("dex", ""),
                                "rejected", f"fast_track_rejected_{strat}", reason,
                            )
                except Exception as e:
                    logger.error(f"خطأ في المسار السريع {entry.get('symbol', '?')}: {e}")
        except Exception as e:
            logger.error(f"خطأ عام في المسار السريع: {e}")

        await asyncio.sleep(check_interval)


async def _update_watchlist_status(watch_id: int, status: str):
    await pool.execute("UPDATE watchlist SET status = $1 WHERE id = $2", status, watch_id)


async def get_open_watchlist_count() -> int:
    """يُستخدم في الفحص الصحي"""
    return await pool.fetchval("SELECT COUNT(*) FROM watchlist WHERE status = 'watching'")
