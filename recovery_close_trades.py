"""
✅ recovery_close_trades.py - نظام استرجاع الصفقات
ضع هذا الملف في جذر المشروع (بجانب main.py)
"""

import logging
import asyncio
from db.trades import get_open_trades, update_trade_status
from trading.executor import execute_emergency_sell

logger = logging.getLogger("recovery")


async def close_all_on_startup():
    """إغلاق جميع الصفقات المعلقة عند البدء"""
    logger.info("🔄 فحص الصفقات المعلقة...")
    
    try:
        open_trades = get_open_trades()
        if open_trades:
            logger.info(f"⚠️ وجدت {len(open_trades)} صفقة معلقة")
            
            for trade in open_trades:
                logger.info(f"🔄 إغلاق صفقة: {trade['symbol']} (ID: {trade['id']})")
                try:
                    await execute_emergency_sell(
                        mint=trade['mint_address'],
                        amount=trade['amount_bought']
                    )
                    update_trade_status(trade['id'], 'closed', 'startup_recovery')
                    logger.info(f"✅ تم إغلاق {trade['symbol']}")
                except Exception as e:
                    logger.error(f"❌ خطأ في إغلاق {trade['symbol']}: {e}")
        else:
            logger.info("✅ لا توجد صفقات معلقة")
    except Exception as e:
        logger.error(f"❌ خطأ في فحص الصفقات: {e}")


def list_open_trades():
    """عرض الصفقات المفتوحة"""
    try:
        trades = get_open_trades()
        if not trades:
            print("✅ لا توجد صفقات مفتوحة")
            return
        
        print("\n📊 الصفقات المفتوحة:")
        print("=" * 80)
        for trade in trades:
            print(f"ID: {trade['id']} | {trade['symbol']} | رصيد: {trade['amount_bought']} | الدخول: {trade['entry_price']}")
        print("=" * 80 + "\n")
    except Exception as e:
        logger.error(f"❌ خطأ: {e}")


async def close_all_open_trades():
    """إغلاق طارئ لجميع الصفقات"""
    logger.info("🚨 إغلاق طارئ لجميع الصفقات...")
    await close_all_on_startup()


def close_trade_by_id(trade_id):
    """إغلاق صفقة محددة"""
    logger.info(f"🔄 إغلاق الصفقة #{trade_id}...")
    # سيتم تنفيذها في النسخة الكاملة


def print_wallet_status():
    """عرض حالة المحفظة"""
    print("💰 رصيد المحفظة: يتم الحساب...")
