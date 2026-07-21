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
    SUSTAINED_TREND, GRADUATION_PROXIMITY,
)
from db import pool
from db.trades import record_screening_result, get_strategy_trade_counts_all
from trading.executor import execute_buy
from trading.swap_client import load_wallet_keypair
from filters.reputation import evaluate_reputation
from filters.sell_simulation import simulate_sell, evaluate_simulation_result
from filters.momentum import check_momentum, fetch_momentum_batch, evaluate_momentum
from filters.tatum_check import verify_mint_authority_disabled
from filters.onchain_filters import TokenMetadata, run_all_onchain_filters, parse_spl_mint_account
from utils.solana_rpc import (
    get_token_largest_accounts, rpc_call, get_wallet_sol_balance, get_account_info_base64,
)
from utils.solscan_client import get_token_holders_solscan

logger = logging.getLogger("watchlist")

# عناوين برامج Solana القياسية — لازمة لحساب ATA حساب bonding curve في Pump.fun
# (نفس المشتقة المستخدمة في pumpportal_listener.py، مُكرَّرة هنا عمداً لتفادي
# استيراد دائري: mempool_listener يستورد من watchlist، فلا يمكن العكس)
_TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
_ASSOCIATED_TOKEN_PROGRAM_ID = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")

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


async def run_onchain_filters_for_entry(entry: dict) -> tuple[bool, str]:
    """
    ينفّذ الفحص الأمني الكامل المكلف (RPC: قراءة العقد + توزيع الحيازة) —
    يُستدعى الآن فقط بعد تأكيد الزخم (المسار السريع) أو عند الاقتراب من
    قرار المسار العادي، وليس عند كل اكتشاف كما كان سابقاً. هذا هو جوهر
    إعادة الهيكلة: توفير ميزانية RPC للعملات النادرة الواعدة فقط.
    """
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

    # نُجرّب Solscan أولاً (حصة منفصلة تماماً عن Helius، 10 مليون CU) — يُخفّف
    # الضغط عن Helius في نقطة الفشل الأكثر تكراراً. عند فشله (لا مفتاح، 429،
    # إلخ)، نتراجع تلقائياً لمصدر RPC الأصلي كاحتياطي.
    solscan_result = await get_token_holders_solscan(mint_address)
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
        logger.debug(f"[{entry.get('symbol', '?')}] فحص التوزيع عبر Solscan (المصدر الأساسي) نجح")
    else:
        # احتياطي: نفس منطق RPC القديم بالكامل، بدون أي تغيير
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

    # حرق LP: Pump.fun يُستثنى دائماً (Bonding Curve، وليس LP تقليدي) — نفس
    # الاستثناء المُطبَّق في الفلتر الأصلي منذ اكتشاف هذه المشكلة سابقاً.
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
    """
    يفحص المؤشرات العضوية الحالية مقابل لحظة الإضافة للـ watchlist.

    تحسين جديد: نُجرّب Solscan أولاً — يُرجع العدد الحقيقي الكامل للحاملين
    (بدون قيد الـ20 حساباً الذي تفرضه RPC نفسها)، فيصبح فحص "النمو العضوي"
    أدق بكثير (نمو حقيقي حتى لو تجاوز 20 حاملاً)، وأيضاً يُخفّف الضغط عن
    Helius (حصة Solscan منفصلة تماماً).

    إصلاح جذري سابق (لا يزال قائماً): فشل تقني في القياس (كلا المصدرين)
    لا يُحتسَب كـ"نمو صفري" — بل "لم نتمكن من الحكم بعد" (data_available).
    """
    solscan_result = await get_token_holders_solscan(mint_address, limit=1)  # نحتاج فقط "total"
    if solscan_result["total_holders"] is not None:
        current_holders = solscan_result["total_holders"]
        data_available = True
        logger.debug(f"فحص النمو العضوي لـ {mint_address} عبر Solscan نجح (المصدر الأساسي)")
    else:
        try:
            largest_accounts = await get_token_largest_accounts(mint_address, max_retries=6)
            current_holders = sum(1 for h in largest_accounts if float(h.get("amount", 0)) > 0)
            data_available = True
        except Exception as e:
            logger.warning(f"تعذّر فحص النمو العضوي لـ {mint_address} (كلا المصدرين): {e}")
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
    """
    فحوصات الأمان المشتركة الكاملة — يُستدعى من كلا المسارين، لكن فقط
    بعد تأكيد الزخم (المسار السريع) أو الاقتراب من قرار المسار العادي.

    الترتيب: 1) الفحص الأمني الأساسي (RPC ذاتي، نتحكم بميزانيته) → 2) GoPlus
    (خدمة خارجية بحصة محدودة أكثر) → 3) محاكاة البيع. هذا الترتيب يُوفّر
    حصة GoPlus النادرة لمن يجتاز الفحص الأساسي الأرخص أولاً.
    """
    mint_address = entry["mint_address"]
    deployer_wallet = entry.get("deployer_wallet", "")
    pool_address = entry.get("pool_address", "")

    onchain_ok, onchain_reason = await run_onchain_filters_for_entry(entry)
    if not onchain_ok:
        return False, f"فشل الفحص الأساسي: {onchain_reason}"

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

    # إصلاح حاسم: إن تعذّر القياس تقنياً (فشل RPC)، لا نحتسب هذا إطلاقاً ضد
    # العملة — لا كـ"نمو صفري" ولا كخطوة نحو انتهاء الصلاحية عند 72 ساعة.
    # نبقيها "قيد المراقبة" فقط، وننتظر دورة لاحقة قد ينجح فيها القياس فعلياً
    # (خصوصاً مع تناوب عدة مزودين، فشل مزود الآن لا يعني فشله في الدورة القادمة).
    if not growth_data["data_available"]:
        # صمام أمان: إن استمر الفشل التقني لفترة طويلة جداً (أضعاف مهلة
        # الانتظار العادية)، ننهي المراقبة بسبب مُصنَّف بوضوح كـ"فشل تقني"
        # — وليس "لا يوجد نمو" — لتفادي تراكم آلاف العملات في القائمة للأبد
        # فقط لأن كل مزودينا فشلوا معها تحديداً بلا نهاية.
        if age_hours >= WATCHLIST.max_watch_hours * 3:
            return "expired", (
                f"فشل تقني متكرر في القياس لفترة طويلة جداً ({age_hours:.1f}h) — "
                f"تصنيف: فشل تقني، وليس حكماً على العملة نفسها"
            )
        return "still_watching", (
            f"تعذّر قياس النمو تقنياً هذه الدورة ({age_hours:.1f}h) — "
            f"سيُعاد المحاولة لاحقاً، لن يُحتسَب هذا ضد مهلة الانتهاء"
        )

    if growth_data["holders_growth"] < 0:
        return "rejected", "انخفاض عدد الحاملين — إشارة سلبية واضحة"

    if age_hours < WATCHLIST.min_watch_hours:
        return "still_watching", f"لم تمر بعد فترة المراقبة الدنيا ({age_hours:.1f}h)"

    if growth_data["holders_growth"] < WATCHLIST.min_organic_holders_growth:
        if age_hours >= WATCHLIST.max_watch_hours:
            return "expired", "انتهت فترة المراقبة القصوى دون نمو عضوي كافٍ (بناءً على بيانات حقيقية مقاسة فعلياً)"
        return "still_watching", f"نمو عضوي غير كافٍ بعد ({age_hours:.1f}h)"

    security_ok, security_reason = await run_security_checks(entry)
    if not security_ok:
        return "rejected", f"{security_reason} (بعد فترة الانتظار)"

    return "approved", (
        f"نمو عضوي كافٍ (+{growth_data['holders_growth']} حامل) + "
        f"اجتازت الأمان بعد {age_hours:.1f} ساعة — {security_reason}"
    )


async def evaluate_holder_velocity_entry(entry: dict) -> Optional[tuple[str, str, float]]:
    """
    استراتيجية بديلة تماماً عن مطاردة السعر (momentum_chase): بدل الاعتماد
    على ارتفاع سعري لحظي (قد يُصنعه بائع/مشترٍ واحد ضخم بسهولة نسبياً)،
    نطارد معدل انضمام حاملين حقيقيين جدد لكل دقيقة — إشارة أصعب على
    التلاعب بها (تتطلب محافظ فعلية مختلفة، وليس رأس مال واحداً كافياً).

    يُستخدَم بالتوازي مع momentum_chase على نفس العملات، لمقارنة أداء
    الاستراتيجيتين فعلياً على أرض الواقع بدل الافتراض النظري.
    """
    if not HOLDER_VELOCITY.enabled:
        return None

    age_minutes = (time.time() - entry["added_at"]) / 60
    if age_minutes > FAST_TRACK.max_entry_age_minutes:
        return None

    age_seconds = time.time() - entry["added_at"]
    if age_seconds < FAST_TRACK.min_age_seconds_before_momentum_check:
        return None

    solscan_result = await get_token_holders_solscan(entry["mint_address"], limit=1)
    total_holders = solscan_result["total_holders"]
    if total_holders is None:
        return None  # فشل تقني (لا مفتاح/429/إلخ) — لا قرار، fail-open كامل

    holder_velocity = total_holders / age_minutes if age_minutes > 0 else 0
    if holder_velocity < HOLDER_VELOCITY.min_holders_per_minute:
        return None  # لا تُظهر هذه العملة زخماً كافياً بهذا المقياس تحديداً

    security_ok, security_reason = await run_security_checks(entry)
    if not security_ok:
        return (
            "rejected",
            f"سرعة حاملين قوية ({holder_velocity:.1f}/دقيقة) لكن فشل الأمان: {security_reason}",
            0.0,
        )

    return (
        "approved",
        f"⚡ استراتيجية سرعة الحاملين: {total_holders} حاملاً خلال "
        f"{age_minutes:.1f} دقيقة ({holder_velocity:.1f} حامل/دقيقة) — {security_reason}",
        holder_velocity,
    )


# تتبع القراءة السابقة لكل عملة — لازم لاستراتيجية "الزخم المستدام" (يحتاج
# مقارنة قراءتين متتاليتين، وليس قراءة واحدة فقط).
_previous_momentum_positive: dict = {}


async def evaluate_sustained_trend_entry(entry: dict, prefetched_momentum=None) -> Optional[tuple[str, str, float]]:
    """
    استراتيجية أكثر تحفّظاً من momentum_chase: تتطلب زخماً إيجابياً في
    قراءتين متتاليتين على الأقل (وليس ارتفاعاً لحظياً واحداً قد يكون قمة
    انفجار مؤقتة على وشك الانهيار — كما رأينا فعلياً في صفقات حقيقية
    خسرت 99-100% خلال دقائق من الدخول عند زخم لحظي واحد فقط).
    """
    if not SUSTAINED_TREND.enabled or prefetched_momentum is None:
        return None

    age_seconds = time.time() - entry["added_at"]
    if age_seconds < FAST_TRACK.min_age_seconds_before_momentum_check:
        return None
    age_minutes = (time.time() - entry["added_at"]) / 60
    if age_minutes > FAST_TRACK.max_entry_age_minutes:
        return None

    mint_address = entry["mint_address"]
    current_positive = (
        prefetched_momentum.price_change_m5_pct >= SUSTAINED_TREND.min_price_change_m5_pct
    )
    was_positive = _previous_momentum_positive.get(mint_address, False)
    _previous_momentum_positive[mint_address] = current_positive

    if not (current_positive and was_positive):
        return None  # لم يثبت الزخم استمراره بعد عبر قراءتين متتاليتين

    security_ok, security_reason = await run_security_checks(entry)
    if not security_ok:
        return (
            "rejected",
            f"زخم مستدام (قراءتان متتاليتان) لكن فشل الأمان: {security_reason}",
            prefetched_momentum.price_change_m5_pct,
        )

    return (
        "approved",
        f"📈 استراتيجية الزخم المستدام: +{prefetched_momentum.price_change_m5_pct:.1f}% "
        f"مؤكَّد عبر قراءتين متتاليتين — {security_reason}",
        prefetched_momentum.price_change_m5_pct,
    )


async def evaluate_graduation_proximity_entry(entry: dict, prefetched_momentum=None) -> Optional[tuple[str, str, float]]:
    """
    استراتيجية مختلفة جذرياً: بدل عملة "جديدة تماماً وغير مؤكَّدة"، نستهدف
    عملات اقتربت من عتبة "التخرج" التاريخية لـPump.fun (~$69,000) — تراكم
    طلب حقيقي أثبت نجاتها من آلاف العملات الأخرى، بدل المراهنة على فوضى
    الدقائق الأولى. فلسفة: "ادخل بعد إثبات الجدارة، لا أثناءها".
    """
    if not GRADUATION_PROXIMITY.enabled or prefetched_momentum is None:
        return None
    if (entry.get("dex") or "").lower() != "pump.fun":
        return None  # مفهوم "التخرج" خاص بـPump.fun تحديداً

    age_seconds = time.time() - entry["added_at"]
    if age_seconds < FAST_TRACK.min_age_seconds_before_momentum_check:
        return None
    age_minutes = (time.time() - entry["added_at"]) / 60
    if age_minutes > FAST_TRACK.max_entry_age_minutes:
        return None

    market_cap = prefetched_momentum.market_cap_usd
    if not (GRADUATION_PROXIMITY.min_market_cap_usd <= market_cap <= GRADUATION_PROXIMITY.max_market_cap_usd):
        return None
    if prefetched_momentum.price_change_m5_pct < GRADUATION_PROXIMITY.min_price_change_m5_pct:
        return None

    security_ok, security_reason = await run_security_checks(entry)
    if not security_ok:
        return (
            "rejected",
            f"قرب التخرج (${market_cap:,.0f}) لكن فشل الأمان: {security_reason}",
            0.0,
        )

    return (
        "approved",
        f"🎓 استراتيجية قرب التخرج: قيمة سوقية ${market_cap:,.0f} "
        f"(قريبة من عتبة التخرج ~$69,000) — {security_reason}",
        0.0,
    )


async def evaluate_fast_track_entry(entry: dict, prefetched_momentum=None) -> Optional[tuple[str, str, float]]:
    """
    المسار السريع: يفحص هل العملة تُظهر "انطلاقاً صاروخياً" حقيقياً الآن،
    وإن كان كذلك، يشغّل نفس فحوصات الأمان — بدون انتظار 24-72 ساعة.

    prefetched_momentum: بيانات زخم جاهزة مسبقاً (من استعلام مُجمَّع لعدة
    عملات دفعة واحدة عبر fetch_momentum_batch) — تجنّباً لاستعلام DexScreener
    منفرد لكل عملة، وهو ما كان يتسبب فعلياً في تجاوز حد المعدل (429) لدى
    DexScreener بسبب كثرة الاستعلامات المتزامنة. إن لم تُمرَّر، يعود الكود
    للاستعلام الفردي القديم (احتياطي فقط، وليس المسار المُستخدَم فعلياً).

    يرجع الآن (decision, reason, momentum_strength_pct) — العنصر الثالث
    يُستخدَم لتحجيم حجم الصفقة بما يتناسب مع قوة إشارة الزخم الفعلية،
    بدل حجم ثابت دائماً بغض النظر عن قوة الفرصة.
    """
    age_minutes = (time.time() - entry["added_at"]) / 60
    if age_minutes > FAST_TRACK.max_entry_age_minutes:
        return None

    age_seconds = time.time() - entry["added_at"]
    if age_seconds < FAST_TRACK.min_age_seconds_before_momentum_check:
        # العملة صغيرة جداً — DexScreener لم يُفهرس سيولتها الحقيقية بعد على
        # الأرجح، فأي فحص الآن سيُرجع "$0" غير حقيقي بدل حكم فعلي. نتجاهل
        # بصمت (سيُعاد فحصها تلقائياً في الدورة القادمة بعد بضع ثوانٍ).
        return None

    if prefetched_momentum is not None:
        momentum_ok, momentum_reason = evaluate_momentum(prefetched_momentum)
        momentum_strength_pct = getattr(prefetched_momentum, "price_change_m5_pct", 0.0)
    else:
        momentum_ok, momentum_reason = await check_momentum(entry["mint_address"])
        momentum_strength_pct = 0.0  # المسار الاحتياطي القديم لا يُرجع البيانات الخام

    if not momentum_ok:
        # خُفِّض من INFO إلى DEBUG: هذه الرسالة تتكرر آلاف المرات لكل عملة (كل
        # 10 ثوانٍ لكل عملة قيد المراقبة)، وأصبحت السبب الأكبر في تجاوز
        # Railway لحد 500 سطر/ثانية وإسقاطه رسائل أخرى قد تكون حرجة فعلاً
        # (أخطاء حقيقية، تأكيد صفقات). التفاصيل الكاملة لا تزال متاحة عبر
        # قاعدة البيانات (screening_log) لأي تحليل إحصائي لاحق.
        logger.debug(f"📊 [{entry['symbol']}] لا زخم كافٍ بعد: {momentum_reason}")
        return None

    security_ok, security_reason = await run_security_checks(entry)
    if not security_ok:
        return "rejected", f"زخم قوي لكن فشل الأمان: {security_reason}", momentum_strength_pct

    return "approved", f"🚀 مسار سريع: {momentum_reason} — {security_reason}", momentum_strength_pct




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


def _momentum_size_multiplier(momentum_strength_pct: float) -> float:
    """
    يُحدد مضاعف حجم الصفقة بناءً على قوة إشارة الزخم الفعلية، بدل حجم ثابت
    دائماً بغض النظر عن قوة الفرصة — مبدأ إدارة مخاطر: التركيز أكثر على
    الإشارات عالية الثقة، وأقل على الإشارات التي بالكاد اجتازت الحد الأدنى.

    زخم عند الحد الأدنى (5% تقريباً) → 0.6x الحجم القياسي.
    زخم قوي جداً (100%+، كما رأينا فعلياً في صفقات حقيقية ناجحة) → 2.0x.
    تحجيم خطي بينهما، بحد أقصى وأدنى صارمين لمنع أي تطرف غير محسوب.
    """
    MIN_PCT = 5.0
    STRONG_PCT = 100.0
    MIN_MULT = 0.6
    MAX_MULT = 2.0

    if momentum_strength_pct <= 0:
        return 1.0  # لا بيانات زخم متاحة (مثلاً المسار العادي) — الحجم القياسي كما هو
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
    """منطق تنفيذ الشراء المشترك بين كل الاستراتيجيات — strategy يُسجَّل مع الصفقة
    لمقارنة أداء كل استراتيجية بمعزل عن الأخريات لاحقاً."""
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

    logger.info(f"موافقة على شراء {entry['symbol']} ({stage} / استراتيجية: {strategy}): {reason}")
    await record_screening_result(
        entry["mint_address"], entry["symbol"], entry.get("dex", ""),
        "added_to_watchlist", stage, reason,
    )
    size_multiplier = _momentum_size_multiplier(momentum_strength_pct)
    base_capital_sol = current_capital * (EXIT_STRATEGY.max_capital_pct_per_trade / 100)
    capital_sol = base_capital_sol * size_multiplier
    if size_multiplier != 1.0:
        logger.info(
            f"📏 [{entry['symbol']}] تحجيم الصفقة: مضاعف {size_multiplier:.2f}x "
            f"(زخم {momentum_strength_pct:.1f}%) — {capital_sol:.4f} SOL بدل {base_capital_sol:.4f} SOL"
        )
    await execute_buy(
        entry["mint_address"], entry["symbol"], entry["pool_address"],
        capital_sol=capital_sol,
        filter_report={"decision": reason, "stage": stage, "tatum_confirmation": tatum_reason},
        strategy=strategy,
        deployer_wallet=entry.get("deployer_wallet", ""),
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
                        await _execute_approval(
                            entry, reason, "watchlist_final_approval", strategy="patient_organic"
                        )

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
            # هذا يُخفّض عدد الطلبات الفعلية بعشرات الأضعاف. نستبعد أيضاً
            # العملات الأصغر من min_age_seconds_before_momentum_check لأن
            # فحصها الآن سيُرجع بيانات ناقصة على الأرجح (توفير إضافي للحصة).
            now_ts = time.time()
            eligible_rows = [
                row for row in rows
                if (now_ts - row["added_at"]) >= FAST_TRACK.min_age_seconds_before_momentum_check
            ]
            mint_addresses = [row["mint_address"] for row in eligible_rows]
            momentum_by_mint = await fetch_momentum_batch(mint_addresses) if mint_addresses else {}

            # التوزيع المتساوي الحقيقي بين الاستراتيجيات: نجلب عدد صفقات كل
            # استراتيجية (مفتوحة+مغلقة) مرة واحدة لكل دورة فحص، ونُرتّب فحص
            # الاستراتيجيات الأربع من الأقل حصة للأكثر — بدل ترتيب ثابت كان
            # يجعل momentum_chase (الأكثر تساهلاً) تستحوذ دائماً على الأولوية
            # وتحرم الاستراتيجيات الأخرى من عدد كافٍ من الصفقات للمقارنة العادلة.
            try:
                strategy_counts = await get_strategy_trade_counts_all()
            except Exception as e:
                logger.warning(f"تعذّر جلب عدد صفقات الاستراتيجيات (سيُستخدَم ترتيب افتراضي): {e}")
                strategy_counts = {}
            for s in _FAST_TRACK_STRATEGY_NAMES:
                strategy_counts.setdefault(s, 0)
            priority_order = sorted(_FAST_TRACK_STRATEGY_NAMES, key=lambda s: strategy_counts.get(s, 0))

            for row in rows:
                entry = dict(row)
                try:
                    prefetched = momentum_by_mint.get(entry["mint_address"])

                    # ملاحظة مهمة: handled يُصبح True فقط عند "موافقة فعلية" (شراء حقيقي)
                    # — وليس عند الرفض. الرفض من استراتيجية واحدة لا يعني أبداً أن
                    # العملة "غير صالحة" لاستراتيجية أخرى مختلفة تماماً في منطقها؛
                    # هذا هو بالضبط الخلل الذي كان يمنع sustained_trend وgraduation_proximity
                    # من الحصول على أي فرصة حقيقية للمقارنة (لاحظنا 1 صفقة فقط لكل
                    # منهما بعد 106 صفقة إجمالاً — دليل قاطع أن الرفض كان يُغلق الباب خطأً).
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
                            logger.info(f"رفض المسار السريع ({strat}) لـ {entry['symbol']}: {reason}")
                            await record_screening_result(
                                entry["mint_address"], entry["symbol"], entry.get("dex", ""),
                                "rejected", f"fast_track_rejected_{strat}", reason,
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
