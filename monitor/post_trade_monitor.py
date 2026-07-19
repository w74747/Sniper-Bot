"""
المراقبة المزدوجة بعد فتح كل صفقة:

الطبقة 1 (on-chain آلية، كل ثوانٍ): تغيّر ضريبة، سحب سيولة، تغيّر ownership.
    → عند اكتشاف أي منها: إغلاق تلقائي فوري + رسالة توثيق مالي كامل.

الطبقة 2 (مصادر خارجية دورية، كل ساعة): سمعة، أخبار، تسريبات.
    → عند اكتشاف إشارة: تنبيه للمراجعة البشرية فقط — لا إغلاق تلقائي.
    → إذا أكّد المستخدم الشبهة يدوياً: يُستدعى نفس مسار الإغلاق التلقائي.
"""
import asyncio
import logging
from typing import Optional

from config.settings import POST_TRADE_MONITOR, EXIT_STRATEGY, USE_DEVNET
from db import trades as db
from alerts import notifier
from filters.onchain_filters import parse_spl_mint_account, KNOWN_BURN_ADDRESSES
from filters.sell_simulation import simulate_sell, evaluate_simulation_result
from trading.executor import execute_emergency_sell, execute_normal_sell, execute_partial_sell
from trading.swap_client import get_jupiter_quote, get_wallet_token_balance, load_wallet_keypair, SOL_MINT_ADDRESS
from utils.solana_rpc import get_account_info_base64, get_token_largest_accounts

logger = logging.getLogger("post_trade_monitor")

# يتتبع أعلى قيمة SOL "قابلة للتحقق فعلياً" (عبر عرض Jupiter الحقيقي، وليس
# سعر DexScreener اللحظي) شوهدت لكل صفقة منذ فتحها — يُستخدم لوقف الخسارة
# المتحرك. إصلاح جذري: DexScreener أثبت عملياً فجوات هائلة بين "السعر
# المعروض" و"العائد الحقيقي عند البيع الفعلي" لعملات meme صغيرة السيولة
# (رأينا فجوات من +24% متوقَّع إلى -83% فعلي في نفس الصفقة!) — عرض Jupiter
# يعكس التنفيذ الحقيقي القابل للتحقق فوراً (بما فيه الانزلاق الفعلي).
# مخزَّن في الذاكرة فقط، يُفقد بأمان عند إعادة التشغيل (يُعاد بناؤه من أول فحص).
_peak_sol_value: dict = {}

# تتبع "الركوب المجاني" — هل بِيع نصف الكمية بالفعل عند مضاعفة السعر؟ وكم
# استُرِدَّ بالضبط (لإضافته لعائد البيع النهائي عند إغلاق الصفقة بالكامل).
_free_ride_triggered: set = set()
_free_ride_recovered_sol: dict = {}


async def get_realizable_sol_value(trade: dict) -> Optional[float]:
    """
    يرجع القيمة الفعلية القابلة للتحقق فوراً بالـSOL لو بِعنا كامل الكمية
    المتبقية الآن — عبر عرض Jupiter الحقيقي (يعكس التنفيذ الفعلي، بما فيه
    الانزلاق الحقيقي)، بدل سعر DexScreener اللحظي الذي أثبتنا عدم موثوقيته.

    يرجع None عند أي فشل تقني (429، رصيد صفري، DEVNET) — fail-open كامل،
    لا نتخذ أي قرار خروج بناءً على بيانات غير مؤكدة.
    """
    if USE_DEVNET:
        return None

    mint_address = trade["mint_address"]
    try:
        keypair = load_wallet_keypair()
        wallet_pubkey = str(keypair.pubkey())
        token_balance = await get_wallet_token_balance(wallet_pubkey, mint_address)
        if token_balance <= 0:
            return None

        quote = await get_jupiter_quote(
            mint_address, SOL_MINT_ADDRESS, token_balance, slippage_bps=500
        )
        out_lamports = float(quote.get("outAmount", 0))
        return out_lamports / 1_000_000_000
    except Exception as e:
        logger.debug(
            f"تعذّر جلب القيمة القابلة للتحقق عبر Jupiter لـ {trade.get('symbol', '?')} "
            f"(سيُعاد المحاولة، fail-open): {e}"
        )
        return None




async def check_onchain_signals(trade: dict) -> tuple[bool, str]:
    """
    يفحص إشارات on-chain قاطعة على عقد العملة المفتوحة صفقتها، بمقارنة الحالة
    الحالية بالحالة المسجّلة عند الدخول (المخزنة في filter_report عند الشراء).

    إصلاح حرج جداً: كان أي فشل تقني (429 من Helius/Jupiter، وهو متكرر جداً)
    يُترجَم فوراً كـ"دليل احتيال قاطع"، فيُباع المركز بذعر — حتى لو كانت
    الصفقة ممتازة وفي طريقها لتحقيق هدف الربح! هذا تسبب فعلياً في خسارة
    رأس المال بمعدل كارثي (تآكل ~93% خلال ساعات) لأسباب لا علاقة لها
    بجودة الصفقة إطلاقاً، بل بازدحام API عادي. الآن: فشل تقني بحت = تجاهل
    هذه الدورة والمحاولة لاحقاً (fail-open)، وإغلاق طارئ فقط عند دليل حقيقي.
    """
    mint_address = trade["mint_address"]

    try:
        mint_data_b64 = await get_account_info_base64(mint_address)
        mint_info = parse_spl_mint_account(mint_data_b64)
    except Exception as e:
        # فشل تقني بحت (429/timeout/شبكة) — لا نبيع بناءً عليه إطلاقاً.
        # سنحاول مجدداً في الدورة القادمة (خلال ثوانٍ قليلة).
        logger.debug(f"تعذّر قراءة حالة العقد تقنياً لـ {trade['symbol']} (سيُعاد المحاولة): {e}")
        return False, ""

    if POST_TRADE_MONITOR.auto_close_on_ownership_change and mint_info["mint_authority_active"]:
        # إذا كانت الصفقة دخلت أصلاً بشرط mint_authority=False، وأصبحت الآن True
        # (نادر لكن ممكن عبر بعض حيل العقود)، هذا تلاعب خطير جداً وحقيقي 100%.
        return True, "تم رصد إعادة تفعيل صلاحية طباعة عملات جديدة (mint authority) بعد الشراء"

    # فحص محاكاة بيع جديدة — إذا أصبح البيع مستحيلاً أو الضريبة الفعلية مرتفعة فجأة
    sim_result = await simulate_sell(
        rpc_client=None,
        wallet_pubkey="",
        mint_address=mint_address,
        pool_address="",
        test_amount_lamports=1_000_000,
    )

    if sim_result.technical_failure:
        # فشل تقني بحت (429 من Jupiter غالباً) — ليس دليلاً على honeypot.
        # لا نبيع، ننتظر الدورة القادمة.
        logger.debug(f"تعذّر تنفيذ محاكاة بيع تقنياً لـ {trade['symbol']} (سيُعاد المحاولة): {sim_result.reason}")
        return False, ""

    if not sim_result.can_sell:
        return True, f"فشلت محاكاة بيع جديدة — قد يكون تحوّل إلى honeypot: {sim_result.reason}"

    if sim_result.effective_sell_tax_pct > POST_TRADE_MONITOR.auto_close_on_tax_increase_above_pct:
        return True, (
            f"ارتفعت ضريبة/تأثير البيع الفعلي إلى "
            f"{sim_result.effective_sell_tax_pct:.1f}% (الحد المسموح "
            f"{POST_TRADE_MONITOR.auto_close_on_tax_increase_above_pct}%)"
        )

    return False, ""


async def check_free_ride_trigger(trade: dict) -> bool:
    """
    يتحقق: هل وصلت القيمة القابلة للتحقق (عبر Jupiter الحقيقي) لأول مرة
    لهدف "الركوب المجاني" (+100% افتراضياً)، ولم يُفعَّل من قبل لهذه
    الصفقة؟ إن كان كذلك، ينفّذ بيعاً جزئياً فوراً (50% افتراضياً) لاسترداد
    رأس المال، ويترك الباقي "بلا ضغط نفسي" يستمر تحت مظلة وقف الخسارة
    المتحرك العادي (مستوحى من عقلية محترفي meme coins).
    """
    trade_id = trade["id"]
    if trade_id in _free_ride_triggered:
        return False  # فُعِّل من قبل بالفعل — لا نُكرره

    entry_capital_sol = trade.get("capital_invested_sol") or 0
    peak_sol = _peak_sol_value.get(trade_id)
    if peak_sol is None or entry_capital_sol <= 0:
        return False

    gain_pct = ((peak_sol - entry_capital_sol) / entry_capital_sol) * 100
    if gain_pct < EXIT_STRATEGY.free_ride_trigger_pct:
        return False

    _free_ride_triggered.add(trade_id)
    recovered = await execute_partial_sell(
        trade, EXIT_STRATEGY.free_ride_sell_fraction,
        f"وصلت القيمة الحقيقية +{gain_pct:.1f}% (الهدف {EXIT_STRATEGY.free_ride_trigger_pct}%)",
    )
    _free_ride_recovered_sol[trade_id] = recovered
    return True


async def check_price_based_signals(trade: dict) -> tuple[bool, str]:
    """
    يفحص القيمة الفعلية القابلة للتحقق حالياً (عبر عرض Jupiter الحقيقي —
    وليس سعر DexScreener اللحظي، الذي أثبتنا عملياً فجوات هائلة بينه وبين
    العائد الحقيقي عند البيع الفعلي لعملات meme صغيرة السيولة) لتطبيق
    منطق الخروج:

    1. وقف خسارة متحرك (الآلية المستمرة الأساسية): خروج كامل عند انخفاض
       trailing_stop_pct من أعلى قيمة حقيقية شوهدت.
    2. وقف خسارة صارم: انهيار مباشر من رأس المال المستثمر بدون أي ربح سابق.

    ملاحظة: "الركوب المجاني" يُفحَص بشكل منفصل عبر check_free_ride_trigger
    — قبل هذه الدالة في حلقة المراقبة الرئيسية.
    """
    trade_id = trade["id"]
    entry_capital_sol = trade.get("capital_invested_sol") or 0
    if entry_capital_sol <= 0:
        return False, ""

    current_sol_value = await get_realizable_sol_value(trade)
    if current_sol_value is None:
        return False, ""  # فشل تقني (429/رصيد صفري) — لا قرار الآن، إعادة محاولة لاحقاً

    _peak_sol_value[trade_id] = max(_peak_sol_value.get(trade_id, current_sol_value), current_sol_value)
    peak_sol = _peak_sol_value[trade_id]

    # الحالة 1: وقف خسارة متحرك — الآلية المستمرة الأساسية
    if peak_sol > entry_capital_sol:
        drop_from_peak_pct = ((peak_sol - current_sol_value) / peak_sol) * 100
        if drop_from_peak_pct >= EXIT_STRATEGY.trailing_stop_pct:
            gain_now_pct = ((current_sol_value - entry_capital_sol) / entry_capital_sol) * 100
            return True, (
                f"وقف خسارة متحرك (قيمة حقيقية عبر Jupiter): انخفضت "
                f"{drop_from_peak_pct:.1f}% من أعلى قمة (الحد {EXIT_STRATEGY.trailing_stop_pct}%) "
                f"— الربح المُثبَّت الفعلي الآن ≈ {gain_now_pct:.1f}%"
            )

    # الحالة 2: انهيار مباشر بدون أي ارتفاع سابق — وقف خسارة صارم
    drop_from_entry_pct = ((entry_capital_sol - current_sol_value) / entry_capital_sol) * 100
    if drop_from_entry_pct >= EXIT_STRATEGY.max_drawdown_from_entry_pct:
        return True, (
            f"وقف خسارة صارم (قيمة حقيقية عبر Jupiter): انخفضت القيمة القابلة "
            f"للتحقق {drop_from_entry_pct:.1f}% من رأس المال مباشرة "
            f"(الحد {EXIT_STRATEGY.max_drawdown_from_entry_pct}%) بدون أي ربح سابق يُثبَّت"
        )

    return False, ""


async def check_external_signals(trade: dict) -> tuple[bool, str]:
    """
    يفحص مصادر خارجية غير on-chain (سمعة، أخبار).
    ملاحظة تنفيذية: يُفضّل ربطه بخدمة تتبع سمعة أو بحث آلي دوري عن اسم
    الرمز/المحفظة، بدل الاعتماد فقط على البيانات on-chain.
    """
    # TODO: تكامل فعلي مع مصدر بيانات خارجي (API لتتبع السمعة، أو حتى web search دوري)
    return False, ""


async def monitor_single_trade(trade: dict):
    """يراقب صفقة واحدة مفتوحة بشكل مستمر حتى تُغلق."""
    trade_id = trade["id"]
    onchain_interval = POST_TRADE_MONITOR.onchain_check_interval_seconds
    external_interval_ticks = (
        POST_TRADE_MONITOR.external_check_interval_minutes * 60 // onchain_interval
    )
    tick = 0

    while True:
        # تحديث حالة الصفقة (قد تكون أُغلقت من مصدر آخر)
        open_trades = await db.get_open_trades()
        if not any(t["id"] == trade_id for t in open_trades):
            logger.info(f"الصفقة {trade_id} لم تعد مفتوحة — إيقاف المراقبة")
            _peak_sol_value.pop(trade_id, None)
            _free_ride_triggered.discard(trade_id)
            _free_ride_recovered_sol.pop(trade_id, None)
            return

        # الطبقة 1: فحص on-chain قاطع (تلاعب تقني) → إغلاق طارئ فوري
        should_close, reason = await check_onchain_signals(trade)
        if should_close:
            logger.warning(f"إغلاق تلقائي (تلاعب تقني) للصفقة {trade_id}: {reason}")
            recovered = _free_ride_recovered_sol.pop(trade_id, 0.0)
            await execute_emergency_sell(trade, reason, extra_proceeds_sol=recovered)
            _peak_sol_value.pop(trade_id, None)
            _free_ride_triggered.discard(trade_id)
            return

        # فحص الركوب المجاني (مرة واحدة فقط لكل صفقة): عند مضاعفة السعر لأول
        # مرة، بيع جزئي فوري لاسترداد رأس المال — لا يُغلق الصفقة، فقط يُقلّص
        # الكمية المتبقية ويُسجّل العائد لإضافته لاحقاً عند الإغلاق النهائي.
        try:
            await check_free_ride_trigger(trade)
        except Exception as e:
            logger.warning(f"تعذّر فحص الركوب المجاني للصفقة {trade_id}: {e}")

        # الطبقة 1.5: فحص السعر الفعلي (وقف خسارة متحرك/صارم) → بيع عادي مخطط
        try:
            should_sell_price, price_reason = await check_price_based_signals(trade)
        except Exception as e:
            logger.warning(f"تعذّر فحص السعر للصفقة {trade_id}: {e}")
            should_sell_price, price_reason = False, ""

        if should_sell_price:
            logger.info(f"بيع مخطط (سعر) للصفقة {trade_id}: {price_reason}")
            recovered = _free_ride_recovered_sol.pop(trade_id, 0.0)
            await execute_normal_sell(trade, price_reason, extra_proceeds_sol=recovered)
            _peak_sol_value.pop(trade_id, None)
            _free_ride_triggered.discard(trade_id)
            return

        # الطبقة 2: فحص دوري للمصادر الخارجية → تنبيه فقط، لا إغلاق
        if tick % external_interval_ticks == 0:
            has_signal, detail = await check_external_signals(trade)
            if has_signal:
                await db.record_alert(
                    trade_id, "external_needs_review", detail,
                    requires_human_confirmation=True,
                )
                await notifier.alert_needs_human_review(
                    trade["symbol"], trade["mint_address"], "مصدر خارجي", detail
                )

        tick += 1
        await asyncio.sleep(onchain_interval)


async def run_post_restore_health_check():
    """
    يعمل مرة واحدة فقط عند بدء تشغيل البوت (بعد أي Restart لأي سبب: تحديث
    كود، انقطاع، إلخ). يراجع كل صفقة كانت مفتوحة قبل التوقف، ويتحقق:

    1. هل لا تزال قابلة للبيع فعلياً الآن؟ (إعادة تشغيل محاكاة البيع)
    2. تذكير مهم: متابعة "أعلى قيمة SOL حقيقية" لوقف الخسارة المتحرك محفوظة
       في الذاكرة فقط (_peak_sol_value) وتُفقد عند أي إعادة تشغيل — هذا
       الفحص يُعيد تهيئتها صراحة من القيمة الحقيقية الآن (عبر Jupiter، بدل
       الانتظار للفحص الدوري العادي)، حتى لا تفوتنا حماية لحظات مهمة فور
       العودة للعمل.

    يرسل تقريراً واحداً مجمّعاً عبر تيليجرام يلخّص النتيجة لكل صفقة.
    """
    open_trades = await db.get_open_trades()

    if not open_trades:
        logger.info("✅ فحص صحي بعد إعادة التشغيل: لا توجد صفقات مفتوحة حالياً")
        return

    logger.info(f"🩺 بدء الفحص الصحي بعد إعادة التشغيل لـ {len(open_trades)} صفقة مفتوحة...")

    report_lines = [f"🩺 <b>تقرير الفحص الصحي بعد إعادة التشغيل</b>\n"]
    report_lines.append(f"عدد الصفقات المفتوحة: {len(open_trades)}\n")

    for trade in open_trades:
        symbol = trade["symbol"]
        mint_address = trade["mint_address"]
        trade_id = trade["id"]

        try:
            sim_result = await simulate_sell(
                rpc_client=None,
                wallet_pubkey="",
                mint_address=mint_address,
                pool_address="",
                test_amount_lamports=1_000_000,
            )
            sim_ok, sim_reason = evaluate_simulation_result(sim_result)
        except Exception as e:
            sim_ok, sim_reason = False, f"تعذّر فحص محاكاة البيع: {e}"

        # إعادة تهيئة تتبع القمة فوراً من القيمة الحقيقية الآن — بدل الانتظار
        # لأول دورة فحص عادية (كل 5 ثوانٍ، فرق بسيط لكن نُفضّل الصراحة هنا)
        price_status = "غير متوفر"
        try:
            current_sol_value = await get_realizable_sol_value(trade)
            if current_sol_value is not None:
                _peak_sol_value[trade_id] = max(
                    _peak_sol_value.get(trade_id, current_sol_value), current_sol_value
                )
                price_status = (
                    f"{current_sol_value:.4f} SOL (تمت إعادة تهيئة تتبع القمة من هذه اللحظة)"
                )
        except Exception as e:
            price_status = f"تعذّر جلب القيمة الحالية: {e}"

        if sim_ok:
            status_icon = "✅"
            status_text = "طبيعية — لا يزال البيع ممكناً بشروط مقبولة"
        else:
            status_icon = "⚠️"
            status_text = f"تحتاج انتباهاً: {sim_reason}"

        report_lines.append(
            f"{status_icon} <b>{symbol}</b>\n"
            f"  الحالة: {status_text}\n"
            f"  السعر الحالي: {price_status}\n"
        )

        logger.info(f"🩺 [{symbol}] محاكاة بيع: {'ناجحة' if sim_ok else 'فشلت'} — {sim_reason}")

    report_lines.append(
        "\nملاحظة: وقف الخسارة المتحرك والصارم كلاهما يعملان بشكل طبيعي من "
        "الآن، بناءً على السعر الحالي كنقطة انطلاق جديدة لكل صفقة أعلاه."
    )

    await notifier.send_telegram_message("\n".join(report_lines))
    logger.info("🩺 اكتمل الفحص الصحي بعد إعادة التشغيل، وأُرسل التقرير عبر تيليجرام")


async def run_monitor_loop():
    """يبدأ مهمة مراقبة منفصلة لكل صفقة مفتوحة حالياً، ويضيف الجديدة تلقائياً."""
    await run_post_restore_health_check()

    running_tasks = {}
    while True:
        open_trades = await db.get_open_trades()
        for trade in open_trades:
            tid = trade["id"]
            if tid not in running_tasks or running_tasks[tid].done():
                running_tasks[tid] = asyncio.create_task(monitor_single_trade(trade))
        await asyncio.sleep(5)
