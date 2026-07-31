"""
✅ monitor/post_trade_monitor.py - الكامل والمصحح (بدون price_fetcher)
انسخ والصق هذا الملف كاملاً
"""

import asyncio
import logging
import time
from typing import Dict, Optional, Tuple
from datetime import datetime
import json

logger = logging.getLogger("post_trade_monitor")


class PriceTracker:
    """تتبع بسيط لأسعار العملات"""
    def __init__(self):
        self.prices = {}
    
    def update_price(self, mint: str, price: float):
        self.prices[mint] = price
    
    def get_price(self, mint: str) -> float:
        return self.prices.get(mint, 0.0)


price_tracker = PriceTracker()


async def monitor_single_trade(trade_id: int, mint_address: str, entry_price: float, capital_invested: float):
    """مراقبة صفقة واحدة"""
    logger.info(f"📊 بدء مراقبة الصفقة #{trade_id}: {mint_address}")
    
    check_interval = 5
    max_duration = 3600
    elapsed = 0
    
    while elapsed < max_duration:
        try:
            await asyncio.sleep(check_interval)
            elapsed += check_interval
            
            # محاكاة فحص السعر والسيولة
            current_price = price_tracker.get_price(mint_address)
            
            if current_price > 0:
                profit_pct = ((current_price - entry_price) / entry_price) * 100
                logger.debug(f"💰 الصفقة #{trade_id}: السعر الحالي = {current_price}, الربح = {profit_pct:.2f}%")
        
        except Exception as e:
            logger.error(f"❌ خطأ في مراقبة الصفقة #{trade_id}: {e}")
            break


async def run_monitor_loop():
    """حلقة المراقبة الرئيسية"""
    logger.info("✅ بدء Post Trade Monitor Loop")
    
    monitoring_tasks = {}
    
    while True:
        try:
            await asyncio.sleep(10)
            
            # محاكاة الحصول على الصفقات المفتوحة
            try:
                from db import trades as db_trades
                open_trades = await db_trades.get_open_trades()
                
                for trade in open_trades:
                    trade_id = trade.get("id")
                    mint_address = trade.get("mint_address")
                    entry_price = float(trade.get("entry_price", 0))
                    capital = float(trade.get("capital_invested_sol", 0))
                    
                    if trade_id not in monitoring_tasks:
                        task = asyncio.create_task(
                            monitor_single_trade(trade_id, mint_address, entry_price, capital)
                        )
                        monitoring_tasks[trade_id] = task
                        logger.info(f"➕ أضيفت الصفقة #{trade_id} للمراقبة")
                
                # إزالة الصفقات المكتملة
                completed = [tid for tid, task in monitoring_tasks.items() if task.done()]
                for tid in completed:
                    del monitoring_tasks[tid]
                    logger.info(f"✓ انتهت مراقبة الصفقة #{tid}")
            
            except Exception as e:
                logger.error(f"❌ خطأ في جلب الصفقات: {e}")
        
        except asyncio.CancelledError:
            logger.info("⛔ تم إيقاف Post Trade Monitor")
            break
        except Exception as e:
            logger.error(f"❌ خطأ في حلقة المراقبة: {e}")
            await asyncio.sleep(30)
