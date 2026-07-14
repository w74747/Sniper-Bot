"""
قائمة الانتظار (Watchlist) + المسار السريع (Fast Track)
النسخة الأصلية الكاملة مع logging تفصيلي للتشخيص

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

# بعد رفض عملة عند الفحص الأول (لم تُشترَ إطلاقاً)، لا نمنع إعادة النظر فيها
# إلا خلال هذه المدة فقط — ظروفها (GoPlus، الزخم) قد تتغيّر خلال ساعات قليلة.
WATCHLIST_REJECTION_COOLDOWN_HOURS = 6

# لا نستدعي check_organic_growth (استعلام RPC مكلف) إلا خلال آخر عدد ساعات
# محدد قبل انتهاء فترة الانتظار الدنيا — هذا يقلل استهلاك RPC بنسبة تفوق 90%
# مقارنة بالفحص كل 15 دقيقة طوال 24 ساعة كاملة لكل عملة.
ORGANIC_CHECK_WINDOW_HOURS = 3

# 📊 معدادات الإحصائيات
_stats = {
    "tokens_checked": 0,
    "tokens_passed_reputation": 0,
    "tokens_passed_sell": 0,
    "tokens_passed_all": 0,
    "tokens_failed": 0,
    "trades_executed": 0,
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

    ✅ محسّن: استخدام cache + تقليل ذكي للمحاولات

    ملاحظة تنفيذية مهمة (تقريب معروف ومقصود):
    getTokenLargestAccounts يرجع فقط أكبر 20 حاملاً كحد أقصى (قيد من Solana RPC
    نفسه، وليس قيداً منّا) — لذلك "عدد الحاملين" هنا هو تقريب وليس عدّاً دقيقاً.
    """
    try:
        # ✨ جديد: تحديد ذكي — هل عملة جديدة أم قديمة؟
        # الجديدة: أقل من ساعة من الآن (تستحق 6 محاولات بسبب تأخر الفهرسة)
        # القديمة: أكثر من ساعة (في watchlist بالفعل، محاولة واحدة كافية)
        age_minutes = (time.time() - holders_at_add) / 60 if holders_at_add > 0 else 1000
        is_new = age_minutes < 60
        
        logger.debug(f"🔍 فحص النمو العضوي (عمر: {age_minutes:.1f} دقيقة)")
        
        largest_accounts = await get_token_largest_accounts(
            mint_address,
            is_new_token=is_new  # ✨ توفير 83% من المحاولات للعملات القديمة!
        )
        current_holders = sum(1 for h in largest_accounts if float(h.get("amount", 0)) > 0)
    except Exception as e:
        logger.warning(f"⚠️ تعذّر فحص النمو العضوي: {e}")
        current_holders = holders_at_add

    holders_growth = current_holders - holders_at_add
    logger.info(f"📊 نمو الحاملين: {holders_growth} (من {holders_at_add} إلى {current_holders})")

    return {
        "current_holders": current_holders,
        "holders_growth": holders_growth,
        "organic_volume_ratio": None,
    }


async def run_security_checks(mint_address: str, deployer_wallet: str, pool_address: str) -> tuple[bool, str]:
    """فحوصات الأمان المشتركة (GoPlus + محاكاة البيع) — يُستدعى من كلا المسارين."""
    
    logger.info(f"\n{'='*60}")
    logger.info(f"🔐 بدء فحوصات الأمان للعملة {mint_address[:16]}...")
    logger.info(f"{'='*60}")
    
    _stats["tokens_checked"] += 1
    
    # 1. فحص السمعة (GoPlus)
    logger.info("🔍 1️⃣ فحص السمعة (GoPlus)...")
    reputation_ok, reputation_reason = await evaluate_reputation(mint_address, deployer_wallet)
    if not reputation_ok:
        logger.warning(f"❌ فشل فحص السمعة: {reputation_reason}")
        _stats["tokens_failed"] += 1
        return False, f"فشلت السمعة: {reputation_reason}"
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


async def evaluate_watchlist_entry(entry: dict) -> tuple[str, str]:
    """
    المسار العادي (24-72 ساعة): يقيّم ما إذا كانت العملة جاهزة للشراء الآن.

    إصلاح كفاءة حاسم: فحص العمر (مجاني تماماً، بدون RPC) يحدث أولاً، ونؤجّل
    استعلام check_organic_growth المكلف (RPC حقيقي) حتى نقترب فعلياً من لحظة
    القرار (آخر ORGANIC_CHECK_WINDOW_HOURS قبل انتهاء فترة الانتظار الدنيا).
    سابقاً كان يُستدعى في كل فحص (كل 15 دقيقة) لكل عملة بغض النظر عن عمرها —
    ما يعني ~96 استعلاماً مهدوراً بالكامل لكل عملة قبل أن يصبح القرار وشيكاً.
    """
    age_hours = (time.time() - entry["added_at"]) / 3600

    # لم تقترب بعد من نافذة اتخاذ القرار → لا داعي لأي استعلام RPC إطلاقاً
    if age_hours < (WATCHLIST.min_watch_hours - ORGANIC_CHECK_WINDOW_HOURS):
        logger.debug(f"⏳ [{entry['symbol']}] لم تدخل نافذة الفحص النهائي ({age_hours:.1f}h)")
        return "still_watching", f"لم تدخل بعد نافذة الفحص النهائي ({age_hours:.1f}h)"

    growth_data = await check_organic_growth(entry["mint_address"], entry["holders_at_add"])

    if growth_data["holders_growth"] < 0:
        logger.warning(f"❌ [{entry['symbol']}] انخفاض عدد الحاملين")
        return "rejected", "انخفاض عدد الحاملين — إشارة سلبية واضحة"

    if age_hours < WATCHLIST.min_watch_hours:
        logger.info(f"⏳ [{entry['symbol']}] لم تمر فترة المراقبة الدنيا ({age_hours:.1f}h)")
        return "still_watching", f"لم تمر بعد فترة المراقبة الدنيا ({age_hours:.1f}h)"

    if growth_data["holders_growth"] < WATCHLIST.min_organic_holders_growth:
        if age_hours >= WATCHLIST.max_watch_hours:
            logger.warning(f"❌ [{entry['symbol']}] انتهت فترة المراقبة بدون نمو كافٍ")
            return "expired", "انتهت فترة المراقبة القصوى دون نمو عضوي كافٍ"
        logger.info(f"⏳ [{entry['symbol']}] نمو عضوي غير كافٍ ({growth_data['holders_growth']})")
        return "still_watching", f"نمو عضوي غير كافٍ بعد ({age_hours:.1f}h)"

    logger.info(f"🔍 [{entry['symbol']}] تم اجتياز فحص النمو العضوي — بدء فحوصات الأمان...")
    security_ok, security_reason = await run_security_checks(
        entry["mint_address"], entry.get("deployer_wallet", ""), entry.get("pool_address", "")
    )
    if not security_ok:
        logger.warning(f"❌ [{entry['symbol']}] فشل الأمان: {security_reason}")
        return "rejected", f"{security_reason} (بعد فترة الانتظار)"

    approval_reason = (
        f"نمو عضوي كافٍ (+{growth_data['holders_growth']} حامل) + "
        f"اجتازت الأمان بعد {age_hours:.1f} ساعة — {security_reason}"
    )
    logger.info(f"✅ [{entry['symbol']}] موافقة: {approval_reason}")
    return "approved", approval_reason


async def evaluate_fast_track_entry(entry: dict) -> Optional[tuple[str, str]]:
    """
    المسار السريع: يفحص هل العملة تُظهر "انطلاقاً صاروخياً" حقيقياً الآن،
    وإن كان كذلك، يشغّل نفس فحوصات الأمان — بدون انتظار 24-72 ساعة.
    """
    age_minutes = (time.time() - entry["added_at"]) / 60
    if age_minutes > FAST_TRACK.max_entry_age_minutes:
        logger.debug(f"⏳ [{entry['symbol']}] عمرها {age_minutes:.1f}m > {FAST_TRACK.max_entry_age_minutes}m")
        return None

    logger.info(f"🔍 [{entry['symbol']}] فحص الزخم (المسار السريع)...")
    momentum_ok, momentum_reason = await check_momentum(entry["mint_address"])
    if not momentum_ok:
        logger.debug(f"📊 [{entry['symbol']}] لا زخم كافٍ: {momentum_reason}")
        return None

    logger.info(f"🚀 [{entry['symbol']}] رصد زخم قوي: {momentum_reason}")
    logger.info(f"🔍 بدء فحوصات الأمان للمسار السريع...")
    security_ok, security_reason = await run_security_checks(
        entry["mint_address"], entry.get("deployer_wallet", ""), entry.get("pool_address", "")
    )
    if not security_ok:
        logger.warning(f"❌ [{entry['symbol']}] زخم لكن فشل الأمان: {security_reason}")
        return "rejected", f"زخم قوي لكن فشل الأمان: {security_reason}"

    logger.info(f"✅ [{entry['symbol']}] المسار السريع: {momentum_reason} — {security_reason}")
    return "approved", f"🚀 مسار سريع: {momentum_reason} — {security_reason}"


async def _get_current_capital_sol() -> float:
    """يرجع الرصيد الفعلي القابل للاستخدام الآن (وليس رقماً ثابتاً)."""
    if USE_DEVNET:
        logger.debug(f"💰 DEVNET: استخدام رصيد افتراضي {DEVNET_FALLBACK_CAPITAL_SOL} SOL")
        return DEVNET_FALLBACK_CAPITAL_SOL

    try:
        keypair = load_wallet_keypair()
        actual_balance = await get_wallet_sol_balance(str(keypair.pubkey()))
        usable = max(actual_balance - SOL_FEE_RESERVE, 0.0)
        logger.info(f"💰 الرصيد الفعلي: {actual_balance:.4f} SOL (قابل: {usable:.4f} SOL)")
        return usable
    except Exception as e:
        logger.error(f"❌ تعذّر قراءة الرصيد الفعلي: {e}")
        return 0.0


async def _execute_approval(entry: dict, reason: str, stage: str):
    """منطق تنفيذ الشراء المشترك بين المسار العادي والمسار السريع."""
    logger.info(f"\n{'='*60}")
    logger.info(f"💰 تنفيذ الشراء: {entry['symbol']} (المرحلة: {stage})")
    logger.info(f"{'='*60}")
    
    current_capital = await _get_current_capital_sol()
    if current_capital <= 0:
        logger.error(
            f"❌ تخطّي شراء {entry['symbol']} — الرصيد المتاح غير كافٍ "
            f"({current_capital:.4f} SOL بعد حجز الاحتياطي)"
        )
        return

    # التأكيد الأخير المستقل (Tatum) — مباشرة قبل تنفيذ الشراء الفعلي
    logger.info("🔍 فحص Tatum النهائي قبل الشراء...")
    tatum_safe, tatum_reason = await verify_mint_authority_disabled(entry["mint_address"])
    if not tatum_safe:
        logger.error(f"⛔ إلغاء شراء {entry['symbol']}: {tatum_reason}")
        await record_screening_result(
            entry["mint_address"], entry["symbol"], entry.get("dex", ""),
            "rejected", f"{stage}_tatum_final_check", tatum_reason,
        )
        await _update_watchlist_status(entry["id"], "rejected")
        return
    logger.info(f"✅ Tatum: {tatum_reason}")

    logger.info(f"✅ موافقة على شراء {entry['symbol']}: {reason}")
    await record_screening_result(
        entry["mint_address"], entry["symbol"], entry.get("dex", ""),
        "added_to_watchlist", stage, reason,
    )
    
    capital_sol = current_capital * (EXIT_STRATEGY.max_capital_pct_per_trade / 100)
    logger.info(f"💸 مبلغ الشراء: {capital_sol:.4f} SOL ({EXIT_STRATEGY.max_capital_pct_per_trade}% من {current_capital:.4f})")
    
    try:
        await execute_buy(
            entry["mint_address"], entry["symbol"], entry["pool_address"],
            capital_sol=capital_sol,
            filter_report={"decision": reason, "stage": stage, "tatum_confirmation": tatum_reason},
        )
        _stats["trades_executed"] += 1
        logger.info(f"✅ تم تنفيذ شراء {entry['symbol']} بنجاح! (#{_stats['trades_executed']})")
    except Exception as e:
        logger.error(f"❌ فشل تنفيذ شراء {entry['symbol']}: {e}")
    
    await _update_watchlist_status(entry["id"], "approved")
    logger.info(f"{'='*60}\n")


async def run_watchlist_loop():
    """يراجع كل العملات في قائمة المراقبة دورياً ويتخذ قرار الشراء عند الموافقة."""
    logger.info("🚀 بدء حلقة المسار العادي (watchlist loop)...")
    await init_watchlist_table()
    while True:
        try:
            rows = await pool.fetch("SELECT * FROM watchlist WHERE status = 'watching'")
            
            if rows:
                logger.info(f"🔍 فحص {len(rows)} عملة في المسار العادي...")

            for row in rows:
                entry = dict(row)
                try:
                    decision, reason = await evaluate_watchlist_entry(entry)

                    if decision == "approved":
                        await _execute_approval(entry, reason, "watchlist_final_approval")

                    elif decision in ("rejected", "expired"):
                        logger.info(f"❌ رفض/انتهاء {entry['symbol']}: {reason}")
                        await record_screening_result(
                            entry["mint_address"], entry["symbol"], entry.get("dex", ""),
                            "rejected", f"watchlist_{decision}", reason,
                        )
                        await _update_watchlist_status(entry["id"], decision)
                except Exception as e:
                    logger.error(
                        f"⚠️ خطأ في معالجة {entry.get('symbol', '?')}: "
                        f"{type(e).__name__}: {e}"
                    )
        except Exception as e:
            logger.error(f"⚠️ خطأ عام في حلقة المسار العادي: {type(e).__name__}: {e}")

        await print_stats()
        await asyncio.sleep(WATCHLIST.check_interval_minutes * 60)


async def run_fast_track_loop():
    """حلقة منفصلة أسرع بكثير (كل 30 ثانية) تفحص فقط العملات الحديثة جداً."""
    if not FAST_TRACK.enabled:
        logger.info("ℹ️ المسار السريع (fast-track) معطّل — لن يعمل")
        return

    await init_watchlist_table()
    logger.info("🚀 بدء حلقة المسار السريع (fast-track loop)...")

    while True:
        try:
            cutoff_timestamp = time.time() - (FAST_TRACK.max_entry_age_minutes * 60)
            rows = await pool.fetch(
                "SELECT * FROM watchlist WHERE status = 'watching' AND added_at >= $1",
                cutoff_timestamp,
            )

            if rows:
                logger.info(f"🔍 فحص {len(rows)} عملة حديثة في المسار السريع...")

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
                        logger.info(f"❌ رفض المسار السريع {entry['symbol']}: {reason}")
                        await record_screening_result(
                            entry["mint_address"], entry["symbol"], entry.get("dex", ""),
                            "rejected", "fast_track_rejected", reason,
                        )
                except Exception as e:
                    logger.error(
                        f"⚠️ خطأ في المسار السريع {entry.get('symbol', '?')}: "
                        f"{type(e).__name__}: {e}"
                    )
        except Exception as e:
            logger.error(f"⚠️ خطأ عام في حلقة المسار السريع: {type(e).__name__}: {e}")

        await asyncio.sleep(FAST_TRACK.check_interval_seconds)


async def _update_watchlist_status(watch_id: int, status: str):
    """تحديث حالة العملة في قاعدة البيانات."""
    try:
        await pool.execute("UPDATE watchlist SET status = $1 WHERE id = $2", status, watch_id)
        logger.debug(f"✅ تم تحديث الحالة: #{watch_id} → {status}")
    except Exception as e:
        logger.error(f"❌ فشل تحديث حالة watchlist #{watch_id}: {e}")


async def get_open_watchlist_count() -> int:
    """يُستخدم في الفحص الصحي بعد إعادة التشغيل."""
    try:
        count = await pool.fetchval("SELECT COUNT(*) FROM watchlist WHERE status = 'watching'")
        logger.info(f"📊 عدد العملات المراقبة حالياً: {count}")
        return count
    except Exception as e:
        logger.error(f"⚠️ تعذّر حساب عدد العملات المراقبة: {e}")
        return 0


async def print_stats():
    """طباعة الإحصائيات الدورية"""
    logger.info(f"\n{'='*60}")
    logger.info("📊 إحصائيات الفحص:")
    logger.info(f"{'='*60}")
    logger.info(f"  • عملات مفحوصة: {_stats['tokens_checked']}")
    logger.info(f"  • نجحت السمعة: {_stats['tokens_passed_reputation']}")
    logger.info(f"  • نجحت محاكاة البيع: {_stats['tokens_passed_sell']}")
    logger.info(f"  • اجتيازت جميع الفلاتر: {_stats['tokens_passed_all']}")
    logger.info(f"  • فشلت: {_stats['tokens_failed']}")
    logger.info(f"  • صفقات منفذة: {_stats['trades_executed']}")
    
    if _stats['tokens_checked'] > 0:
        success_rate = (_stats['tokens_passed_all'] / _stats['tokens_checked']) * 100
        logger.info(f"  • معدل النجاح: {success_rate:.1f}%")
    logger.info(f"{'='*60}\n")
