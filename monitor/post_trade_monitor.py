"""
✅ post_trade_monitor.py المحدث - مع التقييم بعد كل تحديث
"""

import logging
import asyncio
import time
from typing import Dict
from datetime import datetime

from db import trades as db
from monitor.exit_signals import DangerSignalMonitor, SignalType
from trading.exit_strategy import SmartExitStrategy, get_price_safely
from monitor.trades_evaluator import evaluator

logger = logging.getLogger("post_trade_monitor")


async def monitor_single_trade(trade: Dict):
    """
    ✅ مراقبة صفقة واحدة مع تقييم ذكي
    """
    try:
        trade_id = trade.get("id")
        symbol = trade.get("symbol", "unknown")
        mint_address = trade.get("mint_address")
        
        # 1. فحص الإشارات الخطرة
        danger_monitor = DangerSignalMonitor(trade_id, mint_address)
        triggered, signal_type, reason = await danger_monitor.run_all_monitors()
        
        # 2. إذا كان هناك خطر
        if triggered and signal_type:
            logger.warning(
                f"⚠️ إشارة خطر [{signal_type}] للصفقة {symbol}:\n"
                f"   {reason}"
            )
            
            # خروج طارئ فوري
            try:
                exit_strategy = SmartExitStrategy(trade)
                await exit_strategy.execute_emergency_exit(
                    danger_reason=f"{signal_type}: {reason}"
                )
            except Exception as e:
                logger.error(f"❌ خطأ في الخروج الطارئ: {e}")
            
            return  # انتقل للصفقة التالية
        
        # 3. إذا لم يكن هناك خطر، تحقق من الخروج العادي
        current_price = await get_price_safely(mint_address)
        
        if current_price > 0:
            # استخدم نظام الخروج الذكي
            try:
                exit_strategy = SmartExitStrategy(trade)
                
                # تحقق من مراحل الخروج
                stage = exit_strategy.get_stage_to_execute(current_price=current_price)
                
                if stage:
                    logger.info(
                        f"📊 الصفقة {symbol}: الوصول إلى مرحلة الخروج\n"
                        f"   المرحلة: {stage.stage_number}\n"
                        f"   السبب: {stage.reason}"
                    )
                    
                    # تنفيذ الخروج
                    await exit_strategy.execute_stage_exit(stage, current_price)
                
            except Exception as e:
                logger.error(f"❌ خطأ في البيع التدريجي: {e}")
        
        # 4. تقييم الصفقة بعد التحديث
        # (لا نعطل المراقبة بسبب التقييم)
        asyncio.create_task(
            evaluator.evaluate_on_update(
                trade_id=trade_id,
                update_type="monitor"
            )
        )
    
    except Exception as e:
        logger.error(f"❌ خطأ في مراقبة الصفقة {trade.get('symbol', 'unknown')}: {e}")


async def run_monitor_loop():
    """
    ✅ حلقة المراقبة الرئيسية
    مع التقييم الدوري
    """
    logger.info("🟢 بدء حلقة مراقبة الصفقات المفتوحة\n")
    
    while True:
        try:
            # جلب جميع الصفقات المفتوحة
            open_trades = await db.get_open_trades()
            
            if open_trades:
                logger.info(f"📊 مراقبة {len(open_trades)} صفقات مفتوحة")
                
                # مراقبة كل صفقة
                monitor_tasks = [
                    monitor_single_trade(trade)
                    for trade in open_trades
                ]
                
                await asyncio.gather(*monitor_tasks, return_exceptions=True)
            
            else:
                logger.debug("✅ لا توجد صفقات مفتوحة")
            
            # انتظر قبل الدورة التالية
            await asyncio.sleep(10)
        
        except Exception as e:
            logger.error(f"❌ خطأ في حلقة المراقبة: {e}")
            await asyncio.sleep(10)
