"""
تنفيذ الصفقات: الشراء عند اجتياز كل الفلاتر، والبيع (عادي أو طارئ).

ينفّذ swap فعلياً عبر Jupiter Swap API (trading/swap_client.py)، مع توقيع
حقيقي بمفتاح المحفظة المحلي. لا تُشغّل هذا على Mainnet بأموال حقيقية قبل
اختباره بالكامل على Devnet — راجع USE_DEVNET في config/settings.py.
"""
import json
import logging
import time

from config.settings import EXIT_STRATEGY, USE_DEVNET, SYMBOL_BLOCKLIST_LOSS_THRESHOLD_PCT
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
    deployer_wallet: str = "",
) -> int:
    """
    ينفّذ عملية الشراء مع حماية قوية جداً ضد الأخطاء
    """
    amount_lamports = int(capital_sol * LAMPORTS_PER_SOL)

    if USE_DEVNET:
        logger.info(f"[DEVNET] محاكاة شراء {symbol} بمبلغ {capital_sol} SOL — لن يُرسل فعلياً")
        entry_price = 0.001  # سعر افتراضي
        out_amount = 1000.0  # محاكاة
        tx_hash = "DEVNET_SIMULATED_NO_TX"
    else:
        try:
            logger.info(f"📤 بدء عملية الشراء: {symbol}\n   مبلغ: {capital_sol} SOL")
            
            tx_hash, quote = await build_and_send_swap(
                input_mint=SOL_MINT_ADDRESS,
                output_mint=mint_address,
                amount=amount_lamports,
                slippage_bps=int(EXIT_STRATEGY.max_slippage_pct * 100),
            )
            
            # ⚠️ التحقق الأول: هل quote موجود؟
            if not quote:
                logger.error(f"🔴 فشل: quote = None (لا توجد استجابة من Jupiter)")
                raise Exception("quote is None - swap failed")
            
            out_amount = float(quote.get("outAmount", 0))
            
            # ⚠️ التحقق الثاني: هل out_amount > 0؟
            if not out_amount or out_amount <= 0:
                logger.error(
                    f"🔴 فشل الشراء: out_amount = {out_amount}\n"
                    f"   Quote: {quote}\n"
                    f"   المشكلة: لم نحصل على عملات (أو Jupiter لم يُرسل المعاملة)"
                )
                raise Exception(f"out_amount is {out_amount} - no tokens bought")
            
            # ⚠️ التحقق الثالث: حساب entry_price
            if capital_sol <= 0:
                raise Exception(f"capital_sol = {capital_sol} (invalid)")
            
            entry_price = capital_sol / out_amount
            
            if entry_price <= 0 or entry_price > 1000:  # entry_price منطقي
                logger.error(
                    f"🔴 entry_price غير منطقي: {entry_price}\n"
                    f"   capital: {capital_sol}, out_amount: {out_amount}"
                )
                raise Exception(f"entry_price {entry_price} is invalid")
            
            logger.info(
                f"✅ الشراء ثم التوقيع بنجاح:\n"
                f"   tx_hash: {tx_hash}\n"
                f"   العملات: {out_amount:.0f}\n"
                f"   السعر: {entry_price:.10f} SOL/token"
            )
            
            # ⏳ انتظر قليلاً لتأكيد المعاملة على البلوك تشين
            logger.info("⏳ انتظار تأكيد المعاملة على البلوك تشين...")
            import asyncio
            await asyncio.sleep(2)
            
            # ⚠️ التحقق الرابع: تحقق من وصول الرصيد
            try:
                wallet_pubkey = str(load_wallet_keypair().pubkey())
                actual_balance = await get_wallet_token_balance(wallet_pubkey, mint_address)
                logger.info(f"📊 رصيد التحقق: {actual_balance:.0f} tokens (المتوقع: {out_amount:.0f})")
                
                if actual_balance <= 0:
                    logger.warning(
                        f"⚠️ تحذير: الرصيد الفعلي = 0 (قد لم تصل المعاملة بعد أو فشلت)\n"
                        f"   سأحاول مرة أخرى بعد 3 ثوانٍ..."
                    )
                    await asyncio.sleep(3)
                    actual_balance = await get_wallet_token_balance(wallet_pubkey, mint_address)
                    logger.info(f"📊 رصيد المحاولة الثانية: {actual_balance:.0f} tokens")
                    
                    if actual_balance > 0:
                        out_amount = actual_balance
                        logger.info(f"✅ تم استخدام الرصيد الفعلي: {out_amount:.0f}")
                    else:
                        logger.error(f"🔴 الرصيد يبقى 0 - المعاملة فشلت!")
                        raise Exception("Balance is still zero after 5 seconds - transaction failed")
            except Exception as e:
                logger.debug(f"تعذّر فحص الرصيد (سأحاول المتابعة): {e}")
            
        except Exception as e:
            logger.error(
                f"❌ فشل تنفيذ الشراء لـ {symbol}:\n"
                f"   السبب: {e}\n"
                f"   سيتم إلغاء الصفقة"
            )
            raise

    trade = db.TradeRecord(
        mint_address=mint_address,
        symbol=symbol,
        capital_invested_sol=capital_sol,
        entry_price=entry_price,
        filter_report=json.dumps(filter_report, ensure_ascii=False),
        tx_hash_entry=tx_hash,
        strategy=strategy,
        amount_bought=out_amount,
    )
    trade_id = await db.record_entry(trade)
    
    logger.info(
        f"✅ تم تسجيل الصفقة #{trade_id}\n"
        f"   العملة: {symbol}\n"
        f"   الكمية: {out_amount:.0f}\n"
        f"   السعر: {entry_price:.10f}"
    )

    filter_summary = "\n".join(f"- {k}: {v}" for k, v in filter_report.items())

    current_balance = None
    try:
        wallet_pubkey = str(load_wallet_keypair().pubkey())
        current_balance = await get_wallet_sol_balance(wallet_pubkey)
    except Exception as e:
        logger.debug(f"تعذّر جلب الرصيد الحالي لرسالة فتح الصفقة (غير حرج): {e}")

    # تفعيل المراقبة اللحظية الحقيقية (WebSocket Push) لهذه الصفقة تحديداً —
    # اكتشاف انهيار سيولة مفاجئ خلال أجزاء من الثانية، بدل انتظار دورة الفحص
    # الدورية القادمة (كل 2-5 ثوانٍ). fail-open كامل: فشل هذا لا يُلغي الشراء
    # نفسه إطلاقاً، فقط يعني الاعتماد على الفحص الدوري وحده كاحتياطي.
    try:
        from monitor.pumpportal_listener import track_open_position
        await track_open_position(mint_address, deployer_wallet=deployer_wallet)
    except Exception as e:
        logger.debug(f"تعذّر تفعيل المراقبة اللحظية لـ {symbol} (غير حرج، الفحص الدوري يبقى فعّالاً): {e}")

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

        # ✅ استخدم amount_bought من قاعدة البيانات بدل جلب الرصيد من المحفظة
        amount_to_sell = trade.get("amount_bought", 0)
        
        if not amount_to_sell or amount_to_sell <= 0:
            logger.error(
                f"🔴 فشل البيع: amount_bought = {amount_to_sell} (لا توجد عملات مسجلة)"
            )
            exit_price = 0.0
            proceeds_sol = 0.0
            tx_hash = "ZERO_AMOUNT_BOUGHT"
        else:
            # محاولة البيع مع retry (حالة تأخير المعاملة على البلوك تشين)
            tx_hash = None
            quote = None
            for attempt in range(3):
                try:
                    logger.info(f"محاولة البيع #{attempt + 1}/3 لـ {trade['symbol']}")
                    
                    # التحقق من الرصيد الفعلي (للتأكد)
                    token_balance = await get_wallet_token_balance(wallet_pubkey, mint_address)
                    
                    if token_balance <= 0:
                        # إذا كانت المحاولة الأولى والرصيد صفر، انتظر وحاول مرة أخرى
                        if attempt == 0:
                            logger.warning(
                                f"⏳ المحاولة الأولى: رصيد {trade['symbol']} = 0 (قد يكون التأخير في الشبكة) — سأنتظر ثانيتين"
                            )
                            import asyncio
                            await asyncio.sleep(2)
                            continue
                        else:
                            # بعد محاولات متعددة، الرصيد لا يزال صفراً
                            logger.error(
                                f"🔴 المحاولة #{attempt + 1}: رصيد {trade['symbol']} لا يزال صفراً — التخلي"
                            )
                            tx_hash = "SKIPPED_ZERO_BALANCE"
                            proceeds_sol = 0.0
                            exit_price = 0.0
                            break
                    
                    # البيع
                    tx_hash, quote = await build_and_send_swap(
                        input_mint=mint_address,
                        output_mint=SOL_MINT_ADDRESS,
                        amount=int(amount_to_sell),  # استخدم amount_bought من DB
                        slippage_bps=int(slippage_pct * 100),
                    )
                    proceeds_lamports = float(quote.get("outAmount", 0))
                    proceeds_sol = proceeds_lamports / LAMPORTS_PER_SOL
                    exit_price = proceeds_sol / amount_to_sell if amount_to_sell else 0.0
                    
                    logger.info(
                        f"✅ البيع نجح (المحاولة #{attempt + 1}):\n"
                        f"   الكمية: {amount_to_sell:.0f} tokens\n"
                        f"   المستحصل: {proceeds_sol:.4f} SOL\n"
                        f"   سعر الخروج: {exit_price:.10f} SOL/token"
                    )
                    break  # نجح البيع، خرج من الحلقة
                    
                except Exception as e:
                    logger.error(f"محاولة #{attempt + 1}: فشل البيع لـ {trade['symbol']}: {e}")
                    if attempt == 2:  # آخر محاولة
                        raise
                    # انتظر قبل المحاولة التالية
                    import asyncio
                    await asyncio.sleep(1)

    # إضافة أي عائد مُسترَد سابقاً من بيع جزئي (ركوب مجاني) — لحساب ربح/خسارة
    # دقيق يعكس الصفقة بأكملها، وليس فقط الجزء الأخير المتبقي منها.
    total_proceeds_sol = proceeds_sol + extra_proceeds_sol

    profit_loss = await db.record_exit(
        trade["id"], exit_price, total_proceeds_sol, reason, tx_hash, flagged=flagged
    )
    cumulative = await db.get_cumulative_performance()

    # تسجيل تلقائي دائم للأسماء المُستنسَخة الخطرة — إن كانت هذه الخسارة
    # كارثية (أسوأ من SYMBOL_BLOCKLIST_LOSS_THRESHOLD_PCT)، نُضيف الاسم
    # لقائمة حظر **دائمة** فوراً، لمنع أي عملة مستقبلية بنفس الاسم من
    # الدخول إطلاقاً — بغض النظر عن عنوان mint (اكتشفنا فعلياً 12 عملة
    # مختلفة بنفس الاسم "USOH" تستغل نمط ربح/خسارة متكرر بذكاء).
    capital = trade.get("capital_invested_sol") or 0
    if capital > 0:
        pl_pct = (profit_loss / capital) * 100
        if pl_pct <= SYMBOL_BLOCKLIST_LOSS_THRESHOLD_PCT:
            try:
                new_count = await db.add_to_symbol_blocklist(trade["symbol"], mint_address)
                logger.warning(
                    f"🚫 تسجيل '{trade['symbol']}' في قائمة الحظر الدائمة "
                    f"(خسارة {pl_pct:.1f}%) — المرة رقم {new_count} لهذا الاسم"
                )
            except Exception as e:
                logger.error(f"تعذّر تسجيل '{trade['symbol']}' في قائمة الحظر: {e}")

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

    # إلغاء المراقبة اللحظية — الصفقة أُغلقت، لا داعي لمتابعة تداولها بعد الآن
    try:
        from monitor.pumpportal_listener import untrack_open_position
        await untrack_open_position(mint_address)
    except Exception as e:
        logger.debug(f"تعذّر إلغاء المراقبة اللحظية لـ {mint_address} (غير حرج): {e}")

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
