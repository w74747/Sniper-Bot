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

from config.settings import WATCHLIST, EXIT_STRATEGY, FAST_TRACK, USE_DEVNET
from db import pool
from db.trades import record_screening_result
from trading.executor import execute_buy
from trading.swap_client import load_wallet_keypair
from filters.reputation import evaluate_reputation
from filters.sell_simulation import simulate_sell, evaluate_simulation_result
from filters.momentum import check_momentum, fetch_momentum_batch, evaluate_momentum
from filters.tatum_check import verify_mint_authority_disabled
from utils.solana_rpc import get_token_largest_accounts, rpc_call, get_wallet_sol_balance

logger = logging.getLogger("watchlist")

SOL_FEE_RESERVE = 0.01
DEVNET_FALLBACK_CAPITAL_SOL = 1.0

# بعد رفض عملة عند الفحص الأول (لم تُشترَ إطلاقاً)، لا نمنع إعادة النظر فيها
# إلا خلال هذه المدة فقط — ظروفها (GoPlus، الزخم) قد تتغيّر خلال ساعات قليلة.
WATCHLIST_REJECTION_COOLDOWN_HOURS = 6

# لا نستدعي check_organic_growth (استعلام RPC مكلف) إلا خلال آخر عدد ساعات
# محدد قبل انتهاء فترة الانتظار الدنيا — هذا يقلل استهلاك RPC بنسبة تفوق 90%
# مقارنة بالفحص كل 15 دقيقة طوال 24 ساعة كاملة لكل عملة.
ORGANIC_CHECK_WINDOW_HOURS = 3


async def init_watchlist_table():
    """جدول watchlist أصبح جزءاً من db.trades.init_db() الموحّد — هذه الدالة محفوظة للتوافق فقط."""
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
    يفحص إن كان يجب منع إعادة إضافة هذه العملة لـ watchlist، مع تمييز مهم:

    1. "watching" أو "approved" → حظر مطلق (قيد المراقبة فعلاً أو أصبحت صفقة).
    2. "rejected" أو "expired" (رُفضت فقط عند الفحص الأول ولم تُشترَ إطلاقاً)
       → نسمح بإعادة النظر بعد فترة تهدئة قصيرة فقط (WATCHLIST_REJECTION_COOLDOWN_HOURS)،
       لأن ظروف عملة meme (GoPlus، الزخم، التوزيع) قد تتغيّر جذرياً خلال ساعات
       قليلة، وحظرها للأبد بعد أول رفض يُفوّت فرصاً حقيقية بلا داعٍ.
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
        return True  # حظر مطلق

    # rejected / expired — نسمح بعد فترة تهدئة قصيرة فقط
    hours_since = (time.time() - row["added_at"]) / 3600
    return hours_since < WATCHLIST_REJECTION_COOLDOWN_HOURS


async def check_organic_growth(mint_address: str, holders_at_add: int) -> dict:
    """
    يفحص المؤشرات العضوية الحالية مقابل لحظة الإضافة للـ watchlist.

    ملاحظة تنفيذية مهمة (تقريب معروف ومقصود):
    getTokenLargestAccounts يرجع فقط أكبر 20 حاملاً كحد أقصى (قيد من Solana RPC
    نفسه، وليس قيداً منّا) — لذلك "عدد الحاملين" هنا هو تقريب وليس عدّاً دقيقاً.
    """
    try:
        largest_accounts = await get_token_largest_accounts(mint_address, max_retries=6)
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


async def run_security_checks(mint_address: str, deployer_wallet: str, pool_address: str) -> tuple[bool, str]:
    """فحوصات الأمان المشتركة (GoPlus + محاكاة البيع) — يُستدعى من كلا المسارين."""
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
    يقرر: approved / rejected / still_watching / expired (المسار العادي)

    إصلاح كفاءة حاسم: فحص العمر (مجاني تماماً، بدون RPC) يحدث أولاً، ونؤجّل
    استعلام check_organic_growth المكلف (RPC حقيقي) حتى نقترب فعلياً من لحظة
    القرار (آخر ORGANIC_CHECK_WINDOW_HOURS قبل انتهاء فترة الانتظار الدنيا).
    سابقاً كان يُستدعى في كل فحص (كل 15 دقيقة) لكل عملة بغض النظر عن عمرها —
    ما يعني ~96 استعلاماً مهدوراً بالكامل لكل عملة قبل أن يصبح القرار وشيكاً.
    """
    age_hours = (time.time() - entry["added_at"]) / 3600

    # لم تقترب بعد من نافذة اتخاذ القرار → لا داعي لأي استعلام RPC إطلاقاً
    if age_hours < (WATCHLIST.min_watch_hours - ORGANIC_CHECK_WINDOW_HOURS):
        return "still_watching", f"لم تدخل بعد نافذة الفحص النهائي ({age_hours:.1f}h)"

    growth_data = await check_organic_growth(entry["mint_address"], entry["holders_at_add"])

    if growth_data["holders_growth"] < 0:
        return "rejected", "انخفاض عدد الحاملين — إشارة سلبية واضحة"

    if age_hours < WATCHLIST.min_watch_hours:
        return "still_watching", f"لم تمر بعد فترة المراقبة الدنيا ({age_hours:.1f}h)"

    if growth_data["holders_growth"] < WATCHLIST.min_organic_holders_growth:
        if age_hours >= WATCHLIST.max_watch_hours:
            return "expired", "انتهت فترة المراقبة القصوى دون نمو عضوي كافٍ"
        return "still_watching", f"نمو عضوي غير كافٍ بعد ({age_hours:.1f}h)"

    security_ok, security_reason = await run_security_checks(
        entry["mint_address"], entry.get("deployer_wallet", ""), entry.get("pool_address", "")
    )
    if not security_ok:
        return "rejected", f"{security_reason} (بعد فترة الانتظار)"

    return "approved", (
        f"نمو عضوي كافٍ (+{growth_data['holders_growth']} حامل) + "
        f"اجتازت الأمان بعد {age_hours:.1f} ساعة — {security_reason}"
    )


async def evaluate_fast_track_entry(entry: dict, prefetched_momentum=None) -> Optional[tuple[str, str]]:
    """
    المسار السريع: يفحص هل العملة تُظهر "انطلاقاً صاروخياً" حقيقياً الآن،
    وإن كان كذلك، يشغّل نفس فحوصات الأمان — بدون انتظار 24-72 ساعة.

    prefetched_momentum: بيانات زخم جاهزة مسبقاً (من استعلام مُجمَّع لعدة
    عملات دفعة واحدة عبر fetch_momentum_batch) — تجنّباً لاستعلام DexScreener
    منفرد لكل عملة، وهو ما كان يتسبب فعلياً في تجاوز حد المعدل (429) لدى
    DexScreener بسبب كثرة الاستعلامات المتزامنة. إن لم تُمرَّر، يعود الكود
    للاستعلام الفردي القديم (احتياطي فقط، وليس المسار المُستخدَم فعلياً).
    """
    age_minutes = (time.time() - entry["added_at"]) / 60
    if age_minutes > FAST_TRACK.max_entry_age_minutes:
        return None

    if prefetched_momentum is not None:
        momentum_ok, momentum_reason = evaluate_momentum(prefetched_momentum)
    else:
        momentum_ok, momentum_reason = await check_momentum(entry["mint_address"])

    if not momentum_ok:
        logger.info(f"📊 [{entry['symbol']}] لا زخم كافٍ بعد: {momentum_reason}")
        return None

    security_ok, security_reason = await run_security_checks(
        entry["mint_address"], entry.get("deployer_wallet", ""), entry.get("pool_address", "")
    )
    if not security_ok:
        return "rejected", f"زخم قوي لكن فشل الأمان: {security_reason}"

    return "approved", f"🚀 مسار سريع: {momentum_reason} — {security_reason}"


async def _get_current_capital_sol() -> float:
    """يرجع الرصيد الفعلي القابل للاستخدام الآن (وليس رقماً ثابتاً)."""
    if USE_DEVNET:
        return DEVNET_FALLBACK_CAPITAL_SOL

    try:
        keypair = load_wallet_keypair()
        actual_balance = await get_wallet_sol_balance(str(keypair.pubkey()))
        usable = max(actual_balance - SOL_FEE_RESERVE, 0.0)
        return usable
    except Exception as e:
        logger.error(f"تعذّر قراءة الرصيد الفعلي — لن يُنفَّذ الشراء: {e}")
        return 0.0


async def _execute_approval(entry: dict, reason: str, stage: str):
    """منطق تنفيذ الشراء المشترك بين المسار العادي والمسار السريع."""
    current_capital = await _get_current_capital_sol()
    if current_capital <= 0:
        logger.warning(
            f"تخطّي شراء {entry['symbol']} — الرصيد المتاح غير كافٍ حالياً "
            f"({current_capital:.4f} SOL بعد حجز الاحتياطي)"
        )
        return

    # التأكيد الأخير المستقل (Tatum) — مباشرة قبل تنفيذ الشراء الفعلي، وليس
    # قبل ذلك بدقائق/ساعات، لضمان أن الفحص يعكس الحالة الحقيقية في نفس لحظة القرار.
    tatum_safe, tatum_reason = await verify_mint_authority_disabled(entry["mint_address"])
    if not tatum_safe:
        logger.error(f"⛔ إلغاء شراء {entry['symbol']} بناءً على تحذير Tatum: {tatum_reason}")
        await record_screening_result(
            entry["mint_address"], entry["symbol"], entry.get("dex", ""),
            "rejected", f"{stage}_tatum_final_check", tatum_reason,
        )
        await _update_watchlist_status(entry["id"], "rejected")
        return
    logger.info(f"🔍 [{entry['symbol']}] {tatum_reason}")

    logger.info(f"موافقة على شراء {entry['symbol']} ({stage}): {reason}")
    await record_screening_result(
        entry["mint_address"], entry["symbol"], entry.get("dex", ""),
        "added_to_watchlist", stage, reason,
    )
    capital_sol = current_capital * (EXIT_STRATEGY.max_capital_pct_per_trade / 100)
    await execute_buy(
        entry["mint_address"], entry["symbol"], entry["pool_address"],
        capital_sol=capital_sol,
        filter_report={"decision": reason, "stage": stage, "tatum_confirmation": tatum_reason},
    )
    await _update_watchlist_status(entry["id"], "approved")


async def run_watchlist_loop():
    """يراجع كل العملات في قائمة المراقبة دورياً ويتخذ قرار الشراء عند الموافقة."""
    await init_watchlist_table()
    while True:
        try:
            rows = await pool.fetch("SELECT * FROM watchlist WHERE status = 'watching'")

            for row in rows:
                entry = dict(row)
                try:
                    decision, reason = await evaluate_watchlist_entry(entry)

                    if decision == "approved":
                        await _execute_approval(entry, reason, "watchlist_final_approval")

                    elif decision in ("rejected", "expired"):
                        logger.info(f"رفض/انتهاء {entry['symbol']}: {reason}")
                        await record_screening_result(
                            entry["mint_address"], entry["symbol"], entry.get("dex", ""),
                            "rejected", f"watchlist_{decision}", reason,
                        )
                        await _update_watchlist_status(entry["id"], decision)
                except Exception as e:
                    logger.error(
                        f"⚠️ خطأ غير متوقع أثناء معالجة {entry.get('symbol', '?')} "
                        f"في المسار العادي: {type(e).__name__}: {e}"
                    )
        except Exception as e:
            # حماية خارجية إضافية: حتى فشل جلب البيانات نفسه من القاعدة لا
            # يجب أن يُسقط الحلقة بأكملها إلى الأبد.
            logger.error(f"⚠️ خطأ عام في حلقة المسار العادي: {type(e).__name__}: {e}")

        await asyncio.sleep(WATCHLIST.check_interval_minutes * 60)


async def run_fast_track_loop():
    """حلقة منفصلة أسرع بكثير (كل 30 ثانية) تفحص فقط العملات الحديثة جداً."""
    if not FAST_TRACK.enabled:
        logger.info("المسار السريع (fast-track) معطّل في الإعدادات — لن يعمل")
        return

    await init_watchlist_table()
    logger.info("بدء المسار السريع لرصد الانطلاق الصاروخي...")

    while True:
        try:
            cutoff_timestamp = time.time() - (FAST_TRACK.max_entry_age_minutes * 60)
            rows = await pool.fetch(
                "SELECT * FROM watchlist WHERE status = 'watching' AND added_at >= $1",
                cutoff_timestamp,
            )

            # الإصلاح الجذري لمشكلة 429 المستمرة على DexScreener: نجمع كل
            # عناوين العملات المطلوب فحصها ونستعلم عنها دفعة واحدة (حتى 30
            # عملة لكل استدعاء HTTP)، بدل استعلام منفرد لكل عملة على حدة —
            # هذا يُخفّض عدد الطلبات الفعلية بعشرات الأضعاف.
            mint_addresses = [row["mint_address"] for row in rows]
            momentum_by_mint = await fetch_momentum_batch(mint_addresses) if mint_addresses else {}

            for row in rows:
                entry = dict(row)
                try:
                    prefetched = momentum_by_mint.get(entry["mint_address"])
                    result = await evaluate_fast_track_entry(entry, prefetched_momentum=prefetched)

                    if result is None:
                        continue

                    decision, reason = result
                    if decision == "approved":
                        await _execute_approval(entry, reason, "fast_track_approval")
                    elif decision == "rejected":
                        logger.info(f"رفض المسار السريع لـ {entry['symbol']}: {reason}")
                        await record_screening_result(
                            entry["mint_address"], entry["symbol"], entry.get("dex", ""),
                            "rejected", "fast_track_rejected", reason,
                        )
                except Exception as e:
                    logger.error(
                        f"⚠️ خطأ غير متوقع في المسار السريع لـ {entry.get('symbol', '?')}: "
                        f"{type(e).__name__}: {e}"
                    )
        except Exception as e:
            logger.error(f"⚠️ خطأ عام في حلقة المسار السريع: {type(e).__name__}: {e}")

        await asyncio.sleep(FAST_TRACK.check_interval_seconds)


async def _update_watchlist_status(watch_id: int, status: str):
    await pool.execute("UPDATE watchlist SET status = $1 WHERE id = $2", status, watch_id)


async def get_open_watchlist_count() -> int:
    """يُستخدم في الفحص الصحي بعد إعادة التشغيل."""
    return await pool.fetchval("SELECT COUNT(*) FROM watchlist WHERE status = 'watching'")
