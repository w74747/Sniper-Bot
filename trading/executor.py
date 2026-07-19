"""
تنفيذ الصفقات: الشراء عند اجتياز كل الفلاتر، والبيع (عادي أو طارئ).

ينفّذ swap فعلياً عبر Jupiter Swap API (trading/swap_client.py)، مع توقيع
حقيقي بمفتاح المحفظة المحلي. لا تُشغّل هذا على Mainnet بأموال حقيقية قبل
اختباره بالكامل على Devnet — راجع USE_DEVNET في config/settings.py.
"""
import json
import logging
import time

from config.settings import EXIT_STRATEGY, USE_DEVNET
from db import trades as db
from alerts import notifier
from trading.swap_client import (
    build_and_send_swap, get_wallet_token_balance, load_wallet_keypair, SOL_MINT_ADDRESS,
)
from utils.solana_rpc import get_wallet_sol_balance
from monitor.ai_analyst import report_emergency_sell, review_closed_trade

logger = logging.getLogger("executor")

LAMPORTS_PER_SOL = 1_000_000_000


async def execute_buy(
    mint_address: str,
    symbol: str,
    pool_address: str,
    capital_sol: float,
    filter_report: dict,
    strategy: str = "momentum_chase",
) -> int:
    """
    ينفّذ عملية الشراء بعد اجتياز كل الفلاتر (on-chain + reputation + sell simulation).
    يرجع trade_id بعد تسجيل الصفقة في قاعدة البيانات.
    strategy: يُسجَّل مع الصفقة لمقارنة أداء استراتيجيات مختلفة (momentum_chase،
    holder_velocity، patient_organic) بمعزل عن بعضها لاحقاً.
    """
    amount_lamports = int(capital_sol * LAMPORTS_PER_SOL)

    if USE_DEVNET:
        logger.info(f"[DEVNET] محاكاة شراء {symbol} بمبلغ {capital_sol} SOL — لن يُرسل فعلياً")
        entry_price = 0.0
        tx_hash = "DEVNET_SIMULATED_NO_TX"
    else:
        try:
            tx_hash, quote = await build_and_send_swap(
                input_mint=SOL_MINT_ADDRESS,
                output_mint=mint_address,
                amount=amount_lamports,
                slippage_bps=int(EXIT_STRATEGY.max_slippage_pct * 100),
            )
            out_amount = float(quote.get("outAmount", 0))
            entry_price = capital_sol / out_amount if out_amount else 0.0
        except Exception as e:
            logger.error(f"فشل تنفيذ الشراء لـ {symbol}: {e}")
            raise

    trade = db.TradeRecord(
        mint_address=mint_address,
        symbol=symbol,
        capital_invested_sol=capital_sol,
        entry_price=entry_price,
        filter_report=json.dumps(filter_report, ensure_ascii=False),
        tx_hash_entry=tx_hash,
        strategy=strategy,
    )
    trade_id = await db.record_entry(trade)

    filter_summary = "\n".join(f"- {k}: {v}" for k, v in filter_report.items())

    current_balance = None
    try:
        wallet_pubkey = str(load_wallet_keypair().pubkey())
        current_balance = await get_wallet_sol_balance(wallet_pubkey)
    except Exception as e:
        logger.debug(f"تعذّر جلب الرصيد الحالي لرسالة فتح الصفقة (غير حرج): {e}")

    await notifier.alert_new_position_opened(
        symbol, mint_address, capital_sol, filter_summary,
        current_wallet_balance_sol=current_balance,
    )

    logger.info(f"تم فتح صفقة جديدة #{trade_id} على {symbol}")
    return trade_id


async def execute_partial_sell(trade: dict, sell_fraction: float, reason: str) -> float:
    """
    ينفّذ بيعاً جزئياً فقط (وليس إغلاقاً كاملاً للصفقة) — يُستخدَم لاستراتيجية
    "الركوب المجاني" (Free Riding): عند مضاعفة السعر، نبيع نصف الكمية فقط
    لاسترداد رأس المال، ونُبقي الصفقة "مفتوحة" في قاعدة البيانات (لا يُستدعى
    db.record_exit هنا إطلاقاً) لمتابعة مراقبة النصف المتبقي بنفس المنطق.

    يرجع صافي العائد بالـSOL من هذا البيع الجزئي فقط (لإضافته لاحقاً لعائد
    البيع النهائي عند إغلاق الصفقة بالكامل، لضمان حساب ربح/خسارة دقيق).
    """
    mint_address = trade["mint_address"]
    symbol = trade["symbol"]

    if USE_DEVNET:
        logger.info(f"[DEVNET] محاكاة بيع جزئي ({sell_fraction*100:.0f}%) لـ {symbol}")
        return trade["capital_invested_sol"] * sell_fraction

    keypair = load_wallet_keypair()
    wallet_pubkey = str(keypair.pubkey())

    token_balance = await get_wallet_token_balance(wallet_pubkey, mint_address)
    if token_balance <= 0:
        logger.warning(f"رصيد {symbol} صفر — تعذّر تنفيذ البيع الجزئي")
        return 0.0

    sell_amount = int(token_balance * sell_fraction)
    if sell_amount <= 0:
        return 0.0

    try:
        tx_hash, quote = await build_and_send_swap(
            input_mint=mint_address,
            output_mint=SOL_MINT_ADDRESS,
            amount=sell_amount,
            slippage_bps=int(EXIT_STRATEGY.max_slippage_pct * 100),
        )
        proceeds_lamports = float(quote.get("outAmount", 0))
        proceeds_sol = proceeds_lamports / LAMPORTS_PER_SOL
    except Exception as e:
        logger.error(f"فشل تنفيذ البيع الجزئي لـ {symbol}: {e}")
        return 0.0

    logger.info(
        f"🏃 ركوب مجاني: بيع {sell_fraction*100:.0f}% من {symbol} — "
        f"استرداد {proceeds_sol:.4f} SOL — السبب: {reason}"
    )
    await notifier.send_telegram_message(
        f"🏃 <b>ركوب مجاني مُفعَّل</b>\n\n"
        f"العملة: {symbol} (<code>{mint_address}</code>)\n"
        f"بِيع {sell_fraction*100:.0f}% من الكمية عند مضاعفة السعر\n"
        f"استرداد رأس مال: {proceeds_sol:.4f} SOL\n"
        f"الكمية المتبقية ({(1-sell_fraction)*100:.0f}%) تستمر بلا أي ضغط — "
        f"رأس المال الأصلي مُؤمَّن بالفعل"
    )
    return proceeds_sol


async def _execute_sell(
    trade: dict, reason: str, slippage_pct: float, flagged: bool, extra_proceeds_sol: float = 0.0
):
    """منطق مشترك للبيع العادي والطارئ — يختلفان فقط في نسبة الانزلاق المسموح."""
    mint_address = trade["mint_address"]

    if USE_DEVNET:
        logger.info(f"[DEVNET] محاكاة بيع {trade['symbol']} — لن يُرسل فعلياً")
        exit_price = 0.0
        proceeds_sol = trade["capital_invested_sol"]  # افتراض تعادل في DEVNET فقط
        tx_hash = "DEVNET_SIMULATED_NO_TX"
    else:
        keypair = load_wallet_keypair()
        wallet_pubkey = str(keypair.pubkey())

        # الخطوة 1: قراءة الرصيد الفعلي المملوك من هذه العملة — لا نبيع كمية مفترضة
        token_balance = await get_wallet_token_balance(wallet_pubkey, mint_address)
        if token_balance <= 0:
            logger.warning(
                f"رصيد {trade['symbol']} في المحفظة صفر أو غير موجود — "
                f"لا يمكن تنفيذ البيع (ربما تم بيعه مسبقاً أو فشل الشراء الأصلي)"
            )
            exit_price = 0.0
            proceeds_sol = 0.0
            tx_hash = "SKIPPED_ZERO_BALANCE"
        else:
            try:
                tx_hash, quote = await build_and_send_swap(
                    input_mint=mint_address,
                    output_mint=SOL_MINT_ADDRESS,
                    amount=token_balance,
                    slippage_bps=int(slippage_pct * 100),
                )
                proceeds_lamports = float(quote.get("outAmount", 0))
                proceeds_sol = proceeds_lamports / LAMPORTS_PER_SOL
                exit_price = proceeds_sol / token_balance if token_balance else 0.0
            except Exception as e:
                logger.error(f"فشل تنفيذ البيع لـ {trade['symbol']}: {e}")
                raise

    # إضافة أي عائد مُسترَد سابقاً من بيع جزئي (ركوب مجاني) — لحساب ربح/خسارة
    # دقيق يعكس الصفقة بأكملها، وليس فقط الجزء الأخير المتبقي منها.
    total_proceeds_sol = proceeds_sol + extra_proceeds_sol

    profit_loss = await db.record_exit(
        trade["id"], exit_price, total_proceeds_sol, reason, tx_hash, flagged=flagged
    )
    cumulative = await db.get_cumulative_performance()

    # جلب الرصيد الحالي الفعلي + الأداء الشهري — fail-open كامل (لا نُفشل
    # عملية الإغلاق نفسها إن تعذّر جلب أي منهما، فقط نُرسل الرسالة بدونهما).
    current_balance = None
    try:
        wallet_pubkey = str(load_wallet_keypair().pubkey())
        current_balance = await get_wallet_sol_balance(wallet_pubkey)
    except Exception as e:
        logger.debug(f"تعذّر جلب الرصيد الحالي للرسالة (غير حرج): {e}")

    monthly_performance = None
    try:
        monthly_performance = await db.get_monthly_performance()
    except Exception as e:
        logger.debug(f"تعذّر جلب الأداء الشهري للرسالة (غير حرج): {e}")

    await notifier.alert_auto_closed(
        trade["symbol"], mint_address, reason,
        trade["capital_invested_sol"], total_proceeds_sol, profit_loss, tx_hash,
        cumulative=cumulative,
        entry_timestamp=trade.get("entry_timestamp"),
        exit_timestamp=time.time(),
        current_wallet_balance_sol=current_balance,
        monthly_performance=monthly_performance,
    )

    # مراجعة سريعة عبر DeepSeek بعد كل إغلاق — تُبنى سجلاً تراكمياً لتحسين
    # المنطق مستقبلاً. غير مُعطِّلة إطلاقاً (fail-open كامل، لا تُبطئ التنفيذ
    # الفعلي — الصفقة أُغلقت بالفعل قبل استدعائها).
    try:
        entry_reason = trade.get("filter_report", "") or ""
        verdict = await review_closed_trade(trade["symbol"], entry_reason, reason, profit_loss)
        if verdict:
            await notifier.send_telegram_message(f"🧠 <b>مراجعة سريعة</b> ({trade['symbol']}): {verdict}")
    except Exception as e:
        logger.debug(f"تعذّرت مراجعة الصفقة عبر DeepSeek (غير حرج): {e}")

    return profit_loss


async def execute_normal_sell(trade: dict, reason: str = "تحقيق هدف الربح / وقف الخسارة", extra_proceeds_sol: float = 0.0):
    """بيع عادي (ضمن استراتيجية الخروج المخطط لها: take profit / trailing stop)."""
    return await _execute_sell(
        trade, reason, slippage_pct=EXIT_STRATEGY.max_slippage_pct, flagged=False,
        extra_proceeds_sol=extra_proceeds_sol,
    )


async def execute_emergency_sell(trade: dict, reason: str, extra_proceeds_sol: float = 0.0):
    """
    بيع طارئ فوري (عند اكتشاف دليل on-chain قاطع أو تأكيد بشري لشبهة).
    يستخدم انزلاق أعلى (emergency_slippage_pct) لضمان الخروج حتى لو بسعر أسوأ قليلاً.
    """
    logger.warning(f"تنفيذ بيع طارئ للصفقة #{trade['id']} — السبب: {reason}")
    result = await _execute_sell(
        trade, reason, slippage_pct=EXIT_STRATEGY.emergency_slippage_pct, flagged=True,
        extra_proceeds_sol=extra_proceeds_sol,
    )
    # تنبيه أزمة فوري: إن تكررت عمليات البيع الطارئ بمعدل غير طبيعي (3+ خلال
    # 5 دقائق)، هذا غالباً يعني مشكلة تقنية (429 مثلاً) وليس صفقات سيئة فعلياً
    # — نُطلق تحليلاً فورياً بدل انتظار الدورة الدورية (حتى 30 دقيقة).
    try:
        await report_emergency_sell()
    except Exception as e:
        logger.debug(f"تعذّر فحص/إرسال تنبيه الأزمة الفوري (غير حرج): {e}")
    return result



async def confirm_and_close_flagged_trade(trade_id: int, human_confirmed_reason: str):
    """
    يُستدعى عندما يؤكد المستخدم يدوياً (بعد تنبيه المراجعة) أن الشبهة صحيحة.
    هذا هو مسار "تأكيد بشري ثم إغلاق آلي" الذي اتفقنا عليه.
    """
    open_trades = await db.get_open_trades()
    trade = next((t for t in open_trades if t["id"] == trade_id), None)
    if not trade:
        logger.error(f"لم يتم العثور على صفقة مفتوحة بالمعرف {trade_id}")
        return None
    return await execute_emergency_sell(trade, f"تأكيد بشري: {human_confirmed_reason}")
