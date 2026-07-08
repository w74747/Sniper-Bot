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

logger = logging.getLogger("executor")

LAMPORTS_PER_SOL = 1_000_000_000


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
    )
    trade_id = db.record_entry(trade)

    filter_summary = "\n".join(f"- {k}: {v}" for k, v in filter_report.items())
    await notifier.alert_new_position_opened(symbol, mint_address, capital_sol, filter_summary)

    logger.info(f"تم فتح صفقة جديدة #{trade_id} على {symbol}")
    return trade_id


async def _execute_sell(
    trade: dict, reason: str, slippage_pct: float, flagged: bool
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

    profit_loss = db.record_exit(
        trade["id"], exit_price, proceeds_sol, reason, tx_hash, flagged=flagged
    )
    await notifier.alert_auto_closed(
        trade["symbol"], mint_address, reason,
        trade["capital_invested_sol"], proceeds_sol, profit_loss, tx_hash,
    )
    return profit_loss


async def execute_normal_sell(trade: dict, reason: str = "تحقيق هدف الربح / وقف الخسارة"):
    """بيع عادي (ضمن استراتيجية الخروج المخطط لها: take profit / trailing stop)."""
    return await _execute_sell(
        trade, reason, slippage_pct=EXIT_STRATEGY.max_slippage_pct, flagged=False
    )


async def execute_emergency_sell(trade: dict, reason: str):
    """
    بيع طارئ فوري (عند اكتشاف دليل on-chain قاطع أو تأكيد بشري لشبهة).
    يستخدم انزلاق أعلى (emergency_slippage_pct) لضمان الخروج حتى لو بسعر أسوأ قليلاً.
    """
    logger.warning(f"تنفيذ بيع طارئ للصفقة #{trade['id']} — السبب: {reason}")
    return await _execute_sell(
        trade, reason, slippage_pct=EXIT_STRATEGY.emergency_slippage_pct, flagged=True
    )


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
