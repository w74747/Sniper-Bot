"""
📊 مراقبة الصفقات بعد الشراء (محسّن)
═════════════════════════════════════════════════════════════════

المميزات:
1️⃣ مراقبة كل 0.5 ثانية (بدل 10 ثوانٍ)
2️⃣ كشف فوري للانهيارات
3️⃣ بيع متعدد الدفعات
4️⃣ وقف خسارة صارم -30%
5️⃣ حفظ دقيق للتوقيتات (entry_timestamp و exit_timestamp)
"""

import asyncio
import logging
import time
from typing import Dict, Optional, Tuple
from datetime import datetime
import json

logger = logging.getLogger(__name__)

MONITOR_INTERVAL = 0.5  # 🔥 كل 0.5 ثانية (بدل 10 ثوانٍ)


async def monitor_single_trade(
    trade_id: str,
    mint_address: str,
    entry_price: float,
    amount_bought: float,
    capital_invested: float,
    entry_timestamp: float,  # 🔥 إضافة توقيت الفتح
    get_current_price_fn,  # دالة جلب السعر
    check_crash_fn,  # دالة كشف الانهيار
    execute_exit_fn,  # دالة تنفيذ الخروج
    db  # اتصال قاعدة البيانات
) -> None:
    """
    مراقبة صفقة واحدة بشكل مستمر
    
    Args:
        trade_id: معرّف الصفقة
        mint_address: عنوان التوكن
        entry_price: سعر الشراء
        amount_bought: الكمية المشتراة
        capital_invested: رأس المال المستثمر
        entry_timestamp: وقت فتح الصفقة (🔥 جديد)
        get_current_price_fn: دالة جلب السعر الحالي
        check_crash_fn: دالة كشف الانهيار
        execute_exit_fn: دالة تنفيذ الخروج
        db: قاعدة البيانات
    """
    
    logger.info(
        f"[MONITOR] {trade_id}: بدء المراقبة المستمرة"
        f" | السعر: {entry_price:.10f}"
        f" | الكمية: {amount_bought:.6f}"
        f" | وقت الفتح: {datetime.fromtimestamp(entry_timestamp).strftime('%H:%M:%S')}"
    )
    
    # التحقق من الشراء الفاشل
    if not amount_bought or amount_bought <= 0:
        logger.error(f"[MONITOR] {trade_id}: فشل الشراء (كمية = 0)")
        await db.record_exit(
            trade_id=trade_id,
            exit_price=0.0,
            proceeds_sol=0.0,
            close_reason="❌ فشل الشراء: لا توجد عملات",
            tx_hash_exit="ZERO_AMOUNT_BOUGHT",
            flagged=True,
            entry_timestamp=entry_timestamp,  # 🔥 مرر التوقيت
            exit_timestamp=time.time(),  # 🔥 مرر توقيت الإغلاق
        )
        return
    
    max_price_seen = entry_price
    min_price_seen = entry_price
    start_time = datetime.now()
    crash_detected = False
    
    try:
        while True:
            try:
                # 🔥 جلب السعر الحالي
                current_price = await get_current_price_fn()
                
                if not current_price or current_price <= 0:
                    await asyncio.sleep(MONITOR_INTERVAL)
                    continue
                
                # تحديث أعلى وأدنى سعر
                max_price_seen = max(max_price_seen, current_price)
                min_price_seen = min(min_price_seen, current_price)
                
                # حساب PNL
                pnl_pct = ((current_price - entry_price) / entry_price) * 100 if entry_price > 0 else -100
                
                # 🚨 كشف الانهيار الفوري
                is_crash, crash_reason = await check_crash_fn(current_price)
                
                if is_crash and not crash_detected:
                    logger.critical(
                        f"[MONITOR] {trade_id}: 🚨 {crash_reason}"
                    )
                    crash_detected = True
                    
                    # 🔥 توقيت الإغلاق الدقيق
                    exit_timestamp = time.time()
                    duration_seconds = exit_timestamp - entry_timestamp
                    
                    # بيع فوري
                    exit_result = await execute_exit_fn(
                        stage="emergency",
                        current_price=current_price,
                        reason=crash_reason
                    )
                    
                    proceeds_sol = exit_result.get("proceeds", 0)
                    pnl_sol = proceeds_sol - capital_invested
                    pnl_final = (pnl_sol / capital_invested * 100) if capital_invested > 0 else 0
                    
                    # تنسيق المدة
                    if duration_seconds < 60:
                        duration_str = f"{int(duration_seconds)} ثانية"
                    else:
                        minutes = duration_seconds / 60
                        duration_str = f"{minutes:.1f} دقيقة"
                    
                    logger.critical(
                        f"[MONITOR] {trade_id}: "
                        f"انهيار معالج!"
                        f" | الخسارة: {pnl_final:.2f}%"
                        f" | حصلنا: {proceeds_sol:.6f} SOL"
                        f" | المدة: {duration_str}"
                    )
                    
                    await db.record_exit(
                        trade_id=trade_id,
                        exit_price=current_price,
                        proceeds_sol=proceeds_sol,
                        close_reason=f"🚨 انهيار معالج: {crash_reason}",
                        tx_hash_exit="CRASH_EXIT",
                        flagged=pnl_final < -20,
                        entry_timestamp=entry_timestamp,  # 🔥 مرر التوقيت
                        exit_timestamp=exit_timestamp,  # 🔥 مرر توقيت الإغلاق
                    )
                    return
                
                # ✅ فحص مراحل الخروج العادية
                exit_stage = get_exit_stage(pnl_pct)
                
                if exit_stage:
                    logger.info(
                        f"[MONITOR] {trade_id}: "
                        f"وصلنا مرحلة {exit_stage}"
                        f" | PNL: {pnl_pct:.2f}%"
                    )
                    
                    exit_result = await execute_exit_fn(
                        stage=exit_stage,
                        current_price=current_price
                    )
                    
                    if exit_result.get("success"):
                        # 🔥 توقيت الإغلاق الدقيق
                        exit_timestamp = time.time()
                        duration_seconds = exit_timestamp - entry_timestamp
                        
                        proceeds_sol = exit_result.get("proceeds", 0)
                        pnl_sol = proceeds_sol - capital_invested
                        pnl_final = (pnl_sol / capital_invested * 100) if capital_invested > 0 else 0
                        
                        # تنسيق المدة
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
                            entry_timestamp=entry_timestamp,  # 🔥 مرر التوقيت
                            exit_timestamp=exit_timestamp,  # 🔥 مرر توقيت الإغلاق
                        )
                        return
                
                # 📊 تسجيل الحالة كل دقيقة
                elapsed = (datetime.now() - start_time).total_seconds()
                if elapsed % 60 < MONITOR_INTERVAL:
                    logger.debug(
                        f"[MONITOR] {trade_id}: "
                        f"السعر: {current_price:.10f}"
                        f" | PNL: {pnl_pct:+.2f}%"
                        f" | الوقت: {elapsed:.0f}s"
                    )
                
                # 🔥 المراقبة السريعة
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
