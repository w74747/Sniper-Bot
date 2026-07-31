"""
📊 مراقبة الصفقات بعد الشراء (محسّن)
═════════════════════════════════════════════════════════════════

المميزات:
1️⃣ مراقبة كل 0.5 ثانية
2️⃣ كشف فوري للانهيارات
3️⃣ بيع متعدد الدفعات
4️⃣ وقف خسارة صارم -30%
5️⃣ حفظ التوقيتات (entry_timestamp و exit_timestamp)
"""

import asyncio
import logging
import time
from typing import Dict, Optional, Tuple
from datetime import datetime
import json

logger = logging.getLogger(__name__)

MONITOR_INTERVAL = 0.5  # 🔥 كل 0.5 ثانية


async def monitor_single_trade(
    trade_id: str,
    mint_address: str,
    entry_price: float,
    amount_bought: float,
    capital_invested: float,
    entry_timestamp: float,
    get_current_price_fn,
    check_crash_fn,
    execute_exit_fn,
    db
) -> None:
    """مراقبة صفقة واحدة بشكل مستمر"""
    
    logger.info(
        f"[MONITOR] {trade_id}: بدء المراقبة المستمرة"
        f" | السعر: {entry_price:.10f}"
        f" | الكمية: {amount_bought:.6f}"
        f" | وقت الفتح: {datetime.fromtimestamp(entry_timestamp).strftime('%H:%M:%S')}"
    )
    
    if not amount_bought or amount_bought <= 0:
        logger.error(f"[MONITOR] {trade_id}: فشل الشراء (كمية = 0)")
        await db.record_exit(
            trade_id=trade_id,
            exit_price=0.0,
            proceeds_sol=0.0,
            close_reason="❌ فشل الشراء: لا توجد عملات",
            tx_hash_exit="ZERO_AMOUNT_BOUGHT",
            flagged=True,
            entry_timestamp=entry_timestamp,
            exit_timestamp=time.time(),
        )
        return
    
    max_price_seen = entry_price
    min_price_seen = entry_price
    start_time = datetime.now()
    crash_detected = False
    
    try:
        while True:
            try:
                current_price = await get_current_price_fn()
                
                if not current_price or current_price <= 0:
                    await asyncio.sleep(MONITOR_INTERVAL)
                    continue
                
                max_price_seen = max(max_price_seen, current_price)
                min_price_seen = min(min_price_seen, current_price)
                
                pnl_pct = ((current_price - entry_price) / entry_price) * 100 if entry_price > 0 else -100
                
                is_crash, crash_reason = await check_crash_fn(current_price)
                
                if is_crash and not crash_detected:
                    logger.critical(
                        f"[MONITOR] {trade_id}: 🚨 {crash_reason}"
                    )
                    crash_detected = True
                    
                    exit_timestamp = time.time()
                    duration_seconds = exit_timestamp - entry_timestamp
                    
                    exit_result = await execute_exit_fn(
                        stage="emergency",
                        current_price=current_price,
                        reason=crash_reason
                    )
                    
                    proceeds_sol = exit_result.get("proceeds", 0)
                    pnl_sol = proceeds_sol - capital_invested
                    pnl_final = (pnl_sol / capital_invested * 100) if capital_invested > 0 else 0
                    
                    if duration_seconds < 60:
                        duration_str = f"{int(duration_seconds)} ثانية"
                    else:
                        minutes = duration_seconds / 60
                        duration_str = f"{minutes:.1f} دقيقة"
                    
                    logger.critical(
                        f"[MONITOR] {trade_id}: "
                        f"انهيار معالج! | الخسارة: {pnl_final:.2f}% | "
                        f"حصلنا: {proceeds_sol:.6f} SOL | المدة: {duration_str}"
                    )
                    
                    await db.record_exit(
                        trade_id=trade_id,
                        exit_price=current_price,
                        proceeds_sol=proceeds_sol,
                        close_reason=f"🚨 انهيار معالج: {crash_reason}",
                        tx_hash_exit="CRASH_EXIT",
                        flagged=pnl_final < -20,
                        entry_timestamp=entry_timestamp,
                        exit_timestamp=exit_timestamp,
                    )
                    return
                
                exit_stage = get_exit_stage(pnl_pct)
                
                if exit_stage:
                    logger.info(
                        f"[MONITOR] {trade_id}: "
                        f"وصلنا مرحلة {exit_stage} | PNL: {pnl_pct:.2f}%"
                    )
                    
                    exit_result = await execute_exit_fn(
                        stage=exit_stage,
                        current_price=current_price
                    )
                    
                    if exit_result.get("success"):
                        exit_timestamp = time.time()
                        duration_seconds = exit_timestamp - entry_timestamp
                        
                        proceeds_sol = exit_result.get("proceeds", 0)
                        pnl_sol = proceeds_sol - capital_invested
                        pnl_final = (pnl_sol / capital_invested * 100) if capital_invested > 0 else 0
                        
                        if duration_seconds < 60:
                            duration_str = f"{int(duration_seconds)} ثانية"
                        elif duration_seconds < 3600:
                            minutes = duration_seconds / 60
                            duration_str = f"{minutes:.0f} دقيقة"
                        else:
                            hours = duration_seconds / 3600
                            duration_str = f"{hours:.1f} ساعة"
                        
                        logger.info(
                            f"[MONITOR] {trade_id}: "
                            f"خروج بنجاح من {exit_stage}"
                            f" | الربح/الخسارة: {pnl_final:.2f}%"
                            f" | المدة: {duration_str}"
                        )
                        
                        await db.record_exit(
                            trade_id=trade_id,
                            exit_price=current_price,
                            proceeds_sol=proceeds_sol,
                            close_reason=f"✅ خروج من {exit_stage}",
                            tx_hash_exit="NORMAL_EXIT",
                            flagged=False,
                            entry_timestamp=entry_timestamp,
                            exit_timestamp=exit_timestamp,
                        )
                        return
                
                elapsed = (datetime.now() - start_time).total_seconds()
                if elapsed % 60 < MONITOR_INTERVAL:
                    logger.debug(
                        f"[MONITOR] {trade_id}: "
                        f"السعر: {current_price:.10f} | PNL: {pnl_pct:+.2f}% | الوقت: {elapsed:.0f}s"
                    )
                
                await asyncio.sleep(MONITOR_INTERVAL)
            
            except asyncio.CancelledError:
                logger.info(f"[MONITOR] {trade_id}: توقف المراقبة")
                return
            
            except Exception as e:
                logger.error(f"[MONITOR] {trade_id}: خطأ في المراقبة: {str(e)[:50]}")
                await asyncio.sleep(MONITOR_INTERVAL * 2)
    
    except Exception as e:
        logger.error(f"[MONITOR] {trade_id}: خطأ حرج: {e}")


def get_exit_stage(pnl_pct: float) -> Optional[str]:
    """تحديد مرحلة الخروج بناءً على PNL"""
    
    if pnl_pct <= -30.0:
        return "hard_stop_loss"
    elif pnl_pct >= 2.0 and pnl_pct < 50.0:
        return "breakeven"
    elif pnl_pct >= 50.0 and pnl_pct < 200.0:
        return "half_profit"
    elif pnl_pct >= 200.0:
        return "full_profit"
    
    return None


async def run_monitor_loop():
    """حلقة المراقبة الرئيسية - تراقب جميع الصفقات المفتوحة"""
    from db import trades as db_trades
    from trading.executor import execute_normal_sell, execute_emergency_sell
    from monitor.crash_detector import CrashDetector
    from price_fetcher import get_token_price
    
    logger.info("🚀 بدء حلقة مراقبة الصفقات")
    
    crash_detector = CrashDetector()
    active_monitors: Dict[str, asyncio.Task] = {}
    
    try:
        while True:
            try:
                # جلب الصفقات المفتوحة
                open_trades = await db_trades.get_open_trades()
                
                # إضافة صفقات جديدة للمراقبة
                for trade in open_trades:
                    trade_id = str(trade["id"])
                    
                    if trade_id not in active_monitors:
                        logger.info(f"➕ إضافة صفقة #{trade_id} للمراقبة: {trade['symbol']}")
                        
                        async def price_fetcher():
                            return await get_token_price(trade["mint_address"])
                        
                        async def crash_checker(current_price):
                            return crash_detector.check_crash_signals(
                                current_price,
                                trade.get("entry_price", current_price)
                            )
                        
                        async def exit_executor(stage, current_price, reason=None):
                            if stage == "emergency":
                                await execute_emergency_sell(trade, reason or "اكتشاف انهيار")
                                return {"success": True, "proceeds": 0}
                            else:
                                await execute_normal_sell(trade, f"خروج من {stage}")
                                return {"success": True, "proceeds": 0}
                        
                        task = asyncio.create_task(
                            monitor_single_trade(
                                trade_id=trade_id,
                                mint_address=trade["mint_address"],
                                entry_price=trade.get("entry_price", 0),
                                amount_bought=trade.get("amount_bought", 0),
                                capital_invested=trade.get("capital_invested_sol", 0),
                                entry_timestamp=trade.get("entry_timestamp", time.time()),
                                get_current_price_fn=price_fetcher,
                                check_crash_fn=crash_checker,
                                execute_exit_fn=exit_executor,
                                db=db_trades,
                            )
                        )
                        active_monitors[trade_id] = task
                
                # إزالة المهام المكتملة
                completed = [tid for tid, task in active_monitors.items() if task.done()]
                for tid in completed:
                    logger.info(f"❌ انتهت مراقبة الصفقة #{tid}")
                    del active_monitors[tid]
                
                await asyncio.sleep(5)
            
            except Exception as e:
                logger.error(f"❌ خطأ في حلقة المراقبة: {e}")
                await asyncio.sleep(5)
    
    except asyncio.CancelledError:
        logger.info("🛑 إيقاف حلقة مراقبة الصفقات")
        for task in active_monitors.values():
            task.cancel()
        await asyncio.gather(*active_monitors.values(), return_exceptions=True)
    
    except Exception as e:
        logger.error(f"❌ خطأ حرج في حلقة المراقبة: {e}")
