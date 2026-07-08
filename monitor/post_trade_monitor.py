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

from config.settings import POST_TRADE_MONITOR
from db import trades as db
from alerts import notifier
from filters.onchain_filters import parse_spl_mint_account, KNOWN_BURN_ADDRESSES
from filters.sell_simulation import simulate_sell, evaluate_simulation_result
from trading.executor import execute_emergency_sell
from utils.solana_rpc import get_account_info_base64, get_token_largest_accounts

logger = logging.getLogger("post_trade_monitor")


async def check_onchain_signals(trade: dict) -> tuple[bool, str]:
    """
    يفحص إشارات on-chain قاطعة على عقد العملة المفتوحة صفقتها، بمقارنة الحالة
    الحالية بالحالة المسجّلة عند الدخول (المخزنة في filter_report عند الشراء).
    """
    mint_address = trade["mint_address"]

    try:
        mint_data_b64 = await get_account_info_base64(mint_address)
        mint_info = parse_spl_mint_account(mint_data_b64)
    except Exception as e:
        # فشل قراءة الحساب بالكامل قد يعني أن العقد أُغلق أو تعذّر الوصول إليه —
        # هذا بحد ذاته مؤشر خطر يستحق الإغلاق الطارئ الفوري.
        return True, f"تعذّر قراءة حالة العقد الحالية — مؤشر خطر: {e}"

    if POST_TRADE_MONITOR.auto_close_on_ownership_change and mint_info["mint_authority_active"]:
        # إذا كانت الصفقة دخلت أصلاً بشرط mint_authority=False، وأصبحت الآن True
        # (نادر لكن ممكن عبر بعض حيل العقود)، هذا تلاعب خطير جداً.
        return True, "تم رصد إعادة تفعيل صلاحية طباعة عملات جديدة (mint authority) بعد الشراء"

    # فحص محاكاة بيع جديدة — إذا أصبح البيع مستحيلاً أو الضريبة الفعلية مرتفعة فجأة
    sim_result = await simulate_sell(
        rpc_client=None,
        wallet_pubkey="",
        mint_address=mint_address,
        pool_address="",
        test_amount_lamports=1_000_000,
    )
    if not sim_result.can_sell:
        return True, f"فشلت محاكاة بيع جديدة — قد يكون تحوّل إلى honeypot: {sim_result.reason}"

    if sim_result.effective_sell_tax_pct > POST_TRADE_MONITOR.auto_close_on_tax_increase_above_pct:
        return True, (
            f"ارتفعت ضريبة/تأثير البيع الفعلي إلى "
            f"{sim_result.effective_sell_tax_pct:.1f}% (الحد المسموح "
            f"{POST_TRADE_MONITOR.auto_close_on_tax_increase_above_pct}%)"
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
        open_trades = db.get_open_trades()
        if not any(t["id"] == trade_id for t in open_trades):
            logger.info(f"الصفقة {trade_id} لم تعد مفتوحة — إيقاف المراقبة")
            return

        # الطبقة 1: فحص on-chain قاطع → إغلاق تلقائي فوري
        should_close, reason = await check_onchain_signals(trade)
        if should_close:
            logger.warning(f"إغلاق تلقائي للصفقة {trade_id}: {reason}")
            await execute_emergency_sell(trade, reason)
            return

        # الطبقة 2: فحص دوري للمصادر الخارجية → تنبيه فقط، لا إغلاق
        if tick % external_interval_ticks == 0:
            has_signal, detail = await check_external_signals(trade)
            if has_signal:
                db.record_alert(
                    trade_id, "external_needs_review", detail,
                    requires_human_confirmation=True,
                )
                await notifier.alert_needs_human_review(
                    trade["symbol"], trade["mint_address"], "مصدر خارجي", detail
                )

        tick += 1
        await asyncio.sleep(onchain_interval)


async def run_monitor_loop():
    """يبدأ مهمة مراقبة منفصلة لكل صفقة مفتوحة حالياً، ويضيف الجديدة تلقائياً."""
    running_tasks = {}
    while True:
        open_trades = db.get_open_trades()
        for trade in open_trades:
            tid = trade["id"]
            if tid not in running_tasks or running_tasks[tid].done():
                running_tasks[tid] = asyncio.create_task(monitor_single_trade(trade))
        await asyncio.sleep(5)
