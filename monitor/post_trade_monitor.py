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
from trading.executor import execute_emergency_sell  # سيُبنى في trading/executor.py

logger = logging.getLogger("post_trade_monitor")


async def check_onchain_signals(trade: dict) -> tuple[bool, str]:
    """
    يفحص إشارات on-chain قاطعة على عقد العملة المفتوحة صفقتها.
    ملاحظة تنفيذية: يحتاج ربطاً فعلياً بقراءة حالة العقد الحالية عبر RPC
    ومقارنتها بالحالة المسجّلة عند الدخول (المخزنة في filter_report).
    """
    # TODO: قراءة فعلية لحالة العقد الحالية (ضريبة البيع الحالية، هل LP ما زالت مقفلة، إلخ)
    # مثال توضيحي فقط:
    current_state = {
        "sell_tax_pct": 0.0,        # يُقرأ فعلياً من العقد
        "lp_withdrawn": False,      # يُقرأ فعلياً من رصيد pool address
        "ownership_changed": False,  # يُقرأ فعلياً من owner() الحالي
    }

    if current_state["sell_tax_pct"] > POST_TRADE_MONITOR.auto_close_on_tax_increase_above_pct:
        return True, f"ارتفاع ضريبة البيع فجأة إلى {current_state['sell_tax_pct']}%"

    if POST_TRADE_MONITOR.auto_close_on_lp_withdrawal and current_state["lp_withdrawn"]:
        return True, "تم اكتشاف سحب سيولة (LP) من قبل المطور"

    if POST_TRADE_MONITOR.auto_close_on_ownership_change and current_state["ownership_changed"]:
        return True, "تم اكتشاف تغيّر مفاجئ في ملكية العقد (ownership)"

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
