"""
✅ مراقب الصفقات V2 - نظام محسّن مع إشارات خطر فورية
دمج كامل: الإشارات الـ 6 + الخروج المتدرج الذكي
"""

import logging
import asyncio
import time
from typing import Optional

from db.log_handler import LogHandler
from db import db_queries as db
from monitor.danger_signals import DangerSignalMonitor, SignalType
from trading.smart_exit import SmartExitStrategy, get_price_safely
from utils.solscan_client import get_token_holders_solscan

logger = logging.getLogger("post_trade_monitor_v2")


async def monitor_single_trade_v2(trade: dict):
    """
    ✅ مراقبة صفقة واحدة - النظام الجديد المحسّن
    
    منطق:
    1. إنشاء مراقب الخطر (الـ 6 إشارات)
    2. إنشاء استراتيجية الخروج الذكي
    3. تشغيل المراقبة بالتوازي:
       - إشارات الخطر (أولوية قصوى)
       - الخروج التدريجي (عند الربح)
    4. أول إشارة خطر = خروج طارئ فوري
    """
    trade_id = trade["id"]
    mint_address = trade["mint_address"]
    symbol = trade.get("symbol", mint_address[:8])
    
    logger.info(
        f"🟢 مراقبة صفقة جديدة\n"
        f"   ID: {trade_id}\n"
        f"   العملة: {symbol}\n"
        f"   رأس المال: {trade.get('capital_used', 0):.4f} SOL"
    )
    
    # إنشاء المراقب والاستراتيجية
    danger_monitor = DangerSignalMonitor(
        trade_id=trade_id,
        mint_address=mint_address,
        deployer_wallet=trade.get("deployer_wallet")
    )
    
    exit_strategy = SmartExitStrategy(trade)
    
    # تتبع آخر سعر معروف
    last_price = None
    last_price_check = time.time()
    
    try:
        while True:
            current_time = time.time()
            
            # ─────────────────────────────────────────────────────────────
            # فحص 1: الصفقة لا تزال مفتوحة؟
            # ─────────────────────────────────────────────────────────────
            
            open_trades = await db.get_open_trades()
            if not any(t["id"] == trade_id for t in open_trades):
                logger.info(f"✅ الصفقة {trade_id} لم تعد مفتوحة - إيقاف المراقبة")
                danger_monitor.stop()
                break
            
            # ─────────────────────────────────────────────────────────────
            # فحص 2: مراقب الخطر (أولوية قصوى)
            # ─────────────────────────────────────────────────────────────
            # تشغيل الإشارات الـ 6 بالتوازي (مع timeout قصير للفحص السريع)
            
            try:
                # تشغيل مراقب الخطر للحصول على الإشارة الأولى
                signal_triggered, signal_type, reason = await asyncio.wait_for(
                    danger_monitor.run_all_monitors(),
                    timeout=2.0  # فحص سريع كل ثانيتين
                )
                
                if signal_triggered and signal_type:
                    # 🔴 إشارة خطر = خروج طارئ فوري
                    logger.warning(f"🚨 إشارة خطر مكتشفة: {signal_type.value}")
                    
                    # جلب آخر سعر معروف
                    if last_price is None:
                        last_price = await get_price_safely(mint_address)
                    
                    # خروج طارئ
                    await exit_strategy.execute_emergency_exit(
                        danger_reason=f"{signal_type.value}: {reason}",
                        current_price=last_price or 0
                    )
                    
                    # تحديث الصفقة كمغلقة
                    await db.close_trade(
                        trade_id,
                        reason=f"🔴 إغلاق طارئ: {signal_type.value}",
                        exit_reason="EMERGENCY_EXIT"
                    )
                    
                    danger_monitor.stop()
                    break
            
            except asyncio.TimeoutError:
                # انتهت المهلة الزمنية دون إشارة خطر = استمرّ
                pass
            except Exception as e:
                logger.error(f"خطأ في مراقب الخطر: {e}")
            
            # ─────────────────────────────────────────────────────────────
            # فحص 3: جلب السعر الحالي (كل ثانية)
            # ─────────────────────────────────────────────────────────────
            
            if current_time - last_price_check >= 1.0:
                last_price = await get_price_safely(mint_address)
                last_price_check = current_time
                
                if last_price is None:
                    await asyncio.sleep(0.5)
                    continue
            
            # ─────────────────────────────────────────────────────────────
            # فحص 4: الخروج التدريجي (عند الربح)
            # ─────────────────────────────────────────────────────────────
            
            if last_price and last_price > 0:
                stage = exit_strategy.get_stage_to_execute(last_price)
                
                if stage:
                    # ✅ وصلنا لمرحلة ربح = تنفيذ البيع التدريجي
                    try:
                        await exit_strategy.execute_stage_exit(stage, last_price)
                        logger.info(f"✅ بيع تدريجي تم (المرحلة {stage.stage_number})")
                        
                        # إذا انتهينا من جميع المراحل = اغلق الصفقة
                        if exit_strategy.remaining_amount <= 0:
                            logger.info(f"✅ جميع المراحل مكتملة - إغلاق الصفقة")
                            
                            await db.close_trade(
                                trade_id,
                                reason="✅ إغلاق كامل (جميع المراحل)",
                                exit_reason="STAGED_EXIT_COMPLETE"
                            )
                            
                            danger_monitor.stop()
                            break
                    
                    except Exception as e:
                        logger.error(f"خطأ في البيع التدريجي: {e}")
            
            # ─────────────────────────────────────────────────────────────
            # فحص 5: وقف خسارة قاسي (كحد أدنى)
            # ─────────────────────────────────────────────────────────────
            # إذا انخفضت > 20% من رأس المال الأصلي مباشرة
            
            if last_price and last_price > 0:
                pnl = exit_strategy.get_current_pnl_pct(last_price)
                
                if pnl < -20 and exit_strategy.remaining_amount > 0:
                    logger.warning(f"🔴 وقف خسارة قاسي: الخسارة {pnl:.1f}%")
                    
                    # خروج طارئ
                    await exit_strategy.execute_emergency_exit(
                        danger_reason=f"وقف خسارة قاسي ({pnl:.1f}%)",
                        current_price=last_price
                    )
                    
                    await db.close_trade(
                        trade_id,
                        reason=f"🔴 وقف خسارة قاسي ({pnl:.1f}%)",
                        exit_reason="HARD_STOP_LOSS"
                    )
                    
                    danger_monitor.stop()
                    break
            
            # انتظر قليلاً قبل الفحص التالي
            await asyncio.sleep(0.5)
    
    except Exception as e:
        logger.error(f"❌ خطأ حرج في المراقبة: {e}")
        danger_monitor.stop()


async def run_post_trade_monitor_v2():
    """
    ✅ حلقة المراقبة الرئيسية - V2
    مراقبة جميع الصفقات المفتوحة
    """
    logger.info("🚀 بدء مراقب الصفقات V2 (محسّن مع إشارات خطر)")
    
    active_tasks = {}  # {trade_id: task}
    
    try:
        while True:
            try:
                # جلب الصفقات المفتوحة
                open_trades = await db.get_open_trades()
                
                if not open_trades:
                    logger.debug("لا توجد صفقات مفتوحة حالياً")
                else:
                    logger.info(f"📊 مراقبة {len(open_trades)} صفقات مفتوحة")
                
                # تشغيل مراقب لكل صفقة جديدة
                for trade in open_trades:
                    trade_id = trade["id"]
                    
                    if trade_id not in active_tasks:
                        # تشغيل مراقب جديد
                        task = asyncio.create_task(monitor_single_trade_v2(trade))
                        active_tasks[trade_id] = task
                
                # تنظيف المهام المنتهية
                for trade_id in list(active_tasks.keys()):
                    if active_tasks[trade_id].done():
                        del active_tasks[trade_id]
                
                await asyncio.sleep(2)  # فحص كل ثانيتين
            
            except Exception as e:
                logger.error(f"خطأ في حلقة المراقبة الرئيسية: {e}")
                await asyncio.sleep(5)
    
    except KeyboardInterrupt:
        logger.info("🛑 إيقاف مراقب الصفقات V2")
