"""
executor محدّث - يستدعي notifier بالصيغة الدقيقة
"""
import logging
from datetime import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

logger = logging.getLogger("executor")


async def record_trade_entry(trade_id: int, symbol: str, mint_address: str,
                            entry_amount_sol: float, entry_price: float,
                            entry_tx: str, dex: str, decision: str, stage: str):
    """تسجيل شراء جديد مع إرسال تلجرام"""
    try:
        from db import pool
        from alerts.notifier import notify_trade_entry
        
        # تسجيل في قاعدة البيانات
        await pool.execute("""
            INSERT INTO trades (
                id, mint_address, symbol, entry_time, entry_amount_sol,
                entry_price, entry_tx, dex, status
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        """, trade_id, mint_address, symbol, datetime.now(), entry_amount_sol,
            entry_price, entry_tx, dex, "open")
        
        # تسجيل في الـ log
        logger.info(f"""
═══════════════════════════════════════════════════════════════
✅ صفقة شراء جديدة - #{trade_id}
───────────────────────────────────────────────────────────────
📌 الرمز: {symbol}
🪙 Mint: {mint_address}
💰 المبلغ: {entry_amount_sol:.4f} SOL
💵 السعر: {entry_price:.8f}
🏠 DEX: {dex}
🎯 Decision: {decision}
⏰ Stage: {stage}
📍 TX: {entry_tx[:16]}...
⏰ الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
═══════════════════════════════════════════════════════════════
        """)
        
        # إرسال إشعار تلجرام بالصيغة المطلوبة
        await notify_trade_entry(symbol, mint_address, entry_amount_sol, 
                                entry_price, decision, stage)
        
        return trade_id
    except Exception as e:
        logger.error(f"❌ فشل تسجيل الشراء: {e}")
        raise


async def record_trade_exit(trade_id: int, symbol: str, mint_address: str,
                           entry_amount_sol: float, exit_amount_sol: float,
                           exit_price: float, exit_tx: str, reason: str):
    """تسجيل بيع مع إرسال تلجرام"""
    try:
        from db import pool
        from alerts.notifier import notify_trade_exit
        
        # حساب الربح/الخسارة
        profit_loss = exit_amount_sol - entry_amount_sol
        profit_pct = (profit_loss / entry_amount_sol * 100) if entry_amount_sol > 0 else 0
        
        # تحديث في قاعدة البيانات
        await pool.execute("""
            UPDATE trades SET
                exit_price = $2,
                exit_time = NOW(),
                exit_tx = $3,
                exit_amount_sol = $4,
                profit_loss = $5,
                profit_pct = $6,
                status = $7,
                close_reason = $8
            WHERE id = $1
        """, trade_id, exit_price, exit_tx, exit_amount_sol,
            profit_loss, profit_pct, "closed", reason)
        
        # تسجيل في الـ log
        emoji = "🟢" if profit_loss >= 0 else "🔴"
        status = "رابحة ✅" if profit_loss >= 0 else "خاسرة ❌"
        
        logger.info(f"""
═══════════════════════════════════════════════════════════════
{emoji} صفقة {status} - #{trade_id}
───────────────────────────────────────────────────────────────
📌 الرمز: {symbol}
💰 الدخول: {entry_amount_sol:.4f} SOL
📈 الخروج: {exit_amount_sol:.4f} SOL
💵 الربح/الخسارة: {profit_loss:.4f} SOL
📉 النسبة: {profit_pct:.2f}%
🔐 السبب: {reason}
📍 TX: {exit_tx[:16]}...
⏰ الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
═══════════════════════════════════════════════════════════════
        """)
        
        # إرسال إشعار تلجرام بالصيغة المطلوبة
        await notify_trade_exit(mint_address, entry_amount_sol, exit_amount_sol,
                               profit_loss, profit_pct, reason, exit_tx)
        
    except Exception as e:
        logger.error(f"❌ فشل تسجيل البيع: {e}")
        raise
