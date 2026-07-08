"""
تنفيذ الصفقات: الشراء عند اجتياز كل الفلاتر، والبيع (عادي أو طارئ).

تنبيه مهم: هذا إطار عمل (scaffold) يوضح التسلسل المنطقي الصحيح والربط
بقاعدة البيانات والتنبيهات. البناء الفعلي لمعاملات الـ swap يتطلب ربطاً
مباشراً بـ Jupiter Aggregator API (الأسهل) أو Raydium SDK مباشرة، بالإضافة
إلى توقيع المعاملات فعلياً عبر مفتاح المحفظة الخاص (solana-py / solders).

لا تُدخل مفتاحاً خاصاً حقيقياً أو تُشغّل هذا على Mainnet بأموال حقيقية
قبل اختباره بالكامل على Devnet.
"""
import json
import logging
import time

from config.settings import EXIT_STRATEGY, USE_DEVNET
from db import trades as db
from alerts import notifier

logger = logging.getLogger("executor")


async def execute_buy(
    mint_address: str,
    symbol: str,
    pool_address: str,
    capital_sol: float,
    filter_report: dict,
) -> int:
    """
    ينفّذ عملية الشراء بعد اجتياز كل الفلاتر (on-chain + reputation + sell simulation).
    يرجع trade_id بعد تسجيل الصفقة في قاعدة البيانات.
    """
    if USE_DEVNET:
        logger.info(f"[DEVNET] محاكاة شراء {symbol} بمبلغ {capital_sol} SOL")

    # TODO: بناء وتوقيع وإرسال معاملة swap فعلية (SOL -> token) عبر Jupiter API
    # entry_price, tx_hash = await _build_and_send_buy_tx(...)
    entry_price = 0.0  # يُملأ فعلياً من نتيجة المعاملة
    tx_hash = "PLACEHOLDER_TX_HASH"

    trade = db.TradeRecord(
        mint_address=mint_address,
        symbol=symbol,
        capital_invested_sol=capital_sol,
        entry_price=entry_price,
        filter_report=json.dumps(filter_report, ensure_ascii=False),
        tx_hash_entry=tx_hash,
    )
    trade_id = db.record_entry(trade)

    filter_summary = "\n".join(f"- {k}: {v}" for k, v in filter_report.items())
    await notifier.alert_new_position_opened(symbol, mint_address, capital_sol, filter_summary)

    logger.info(f"تم فتح صفقة جديدة #{trade_id} على {symbol}")
    return trade_id


async def execute_normal_sell(trade: dict, reason: str = "تحقيق هدف الربح / وقف الخسارة"):
    """بيع عادي (ضمن استراتيجية الخروج المخطط لها: take profit / trailing stop)."""
    # TODO: بناء وإرسال معاملة swap فعلية (token -> SOL) بانزلاق عادي
    exit_price = 0.0
    proceeds_sol = 0.0
    tx_hash = "PLACEHOLDER_TX_HASH_EXIT"

    profit_loss = db.record_exit(
        trade["id"], exit_price, proceeds_sol, reason, tx_hash, flagged=False
    )
    await notifier.alert_auto_closed(
        trade["symbol"], trade["mint_address"], reason,
        trade["capital_invested_sol"], proceeds_sol, profit_loss, tx_hash,
    )
    return profit_loss


async def execute_emergency_sell(trade: dict, reason: str):
    """
    بيع طارئ فوري (عند اكتشاف دليل on-chain قاطع أو تأكيد بشري لشبهة).
    يستخدم انزلاق أعلى (emergency_slippage_pct) لضمان الخروج حتى لو بسعر أسوأ قليلاً.
    """
    logger.warning(f"تنفيذ بيع طارئ للصفقة #{trade['id']} — السبب: {reason}")

    # TODO: بناء وإرسال معاملة بيع فورية بـ EXIT_STRATEGY.emergency_slippage_pct
    exit_price = 0.0
    proceeds_sol = 0.0
    tx_hash = "PLACEHOLDER_TX_HASH_EMERGENCY_EXIT"

    profit_loss = db.record_exit(
        trade["id"], exit_price, proceeds_sol, reason, tx_hash, flagged=True
    )
    await notifier.alert_auto_closed(
        trade["symbol"], trade["mint_address"], reason,
        trade["capital_invested_sol"], proceeds_sol, profit_loss, tx_hash,
    )
    return profit_loss


async def confirm_and_close_flagged_trade(trade_id: int, human_confirmed_reason: str):
    """
    يُستدعى عندما يؤكد المستخدم يدوياً (بعد تنبيه المراجعة) أن الشبهة صحيحة.
    هذا هو مسار "تأكيد بشري ثم إغلاق آلي" الذي اتفقنا عليه.
    """
    open_trades = db.get_open_trades()
    trade = next((t for t in open_trades if t["id"] == trade_id), None)
    if not trade:
        logger.error(f"لم يتم العثور على صفقة مفتوحة بالمعرف {trade_id}")
        return None
    return await execute_emergency_sell(trade, f"تأكيد بشري: {human_confirmed_reason}")
