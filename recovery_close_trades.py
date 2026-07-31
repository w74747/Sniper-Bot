"""
🔨 أدوات الاسترجاع: إغلاق الصفقات المفتوحة
═════════════════════════════════════════════════════════════════

أوامر يدوية لـ:
1. إغلاق جميع الصفقات المفتوحة دفعة واحدة
2. عرض الصفقات المفتوحة الحالية
3. إغلاق صفقة محددة يدوياً
4. استدعاء تلقائي عند بدء البوت
"""

import asyncio
import logging
from datetime import datetime

from db import trades as db_trades
from trading.executor import execute_emergency_sell
from utils.solana_rpc import get_wallet_sol_balance
from trading.swap_client import load_wallet_keypair

logger = logging.getLogger("recovery")


async def list_open_trades() -> list:
    """
    🔍 جلب جميع الصفقات المفتوحة الحالية مع تفاصيلها
    """
    open_trades = await db_trades.get_open_trades()
    
    if not open_trades:
        logger.info("✅ لا توجد صفقات مفتوحة")
        return []
    
    logger.info(f"\n{'='*80}")
    logger.info(f"📊 الصفقات المفتوحة: {len(open_trades)} صفقة")
    logger.info(f"{'='*80}\n")
    
    for i, trade in enumerate(open_trades, 1):
        age_seconds = 0
        if trade.get("entry_timestamp"):
            age_seconds = datetime.now().timestamp() - trade["entry_timestamp"]
            age_minutes = age_seconds / 60
            age_hours = age_seconds / 3600
            
            if age_hours >= 1:
                age_str = f"{age_hours:.1f} ساعة"
            else:
                age_str = f"{age_minutes:.0f} دقيقة"
        else:
            age_str = "غير معروف"
        
        logger.info(f"[{i}] #{trade['id']} | {trade['symbol']}")
        logger.info(f"    💰 رأس المال: {trade['capital_invested_sol']:.4f} SOL")
        logger.info(f"    🎯 السعر: {trade['entry_price']:.10f}")
        logger.info(f"    📈 الكمية: {trade['amount_bought']:.0f}")
        logger.info(f"    ⏰ المدة: {age_str}")
        logger.info(f"    📍 Mint: {trade['mint_address'][:16]}...")
        logger.info("")
    
    return open_trades


async def close_all_open_trades() -> dict:
    """
    ⚠️ إغلاق جميع الصفقات المفتوحة فوراً (emergency exit)
    ⏱️ مدة التنفيذ: تقريباً 3-5 ثوانٍ لكل صفقة
    """
    open_trades = await db_trades.get_open_trades()
    
    if not open_trades:
        logger.info("✅ لا توجد صفقات مفتوحة للإغلاق")
        return {"closed": 0, "failed": 0, "total": 0}
    
    logger.warning(f"\n🚨 إغلاق {len(open_trades)} صفقة مفتوحة...")
    logger.warning(f"{'='*80}\n")
    
    results = {
        "closed": 0,
        "failed": 0,
        "total": len(open_trades),
        "details": []
    }
    
    for trade in open_trades:
        try:
            logger.warning(f"🔄 إغلاق الصفقة #{trade['id']} ({trade['symbol']})...")
            
            await execute_emergency_sell(
                trade,
                reason="إغلاق يدوي — استعادة الرصيد (Recovery Close)",
            )
            
            results["closed"] += 1
            results["details"].append({
                "id": trade["id"],
                "symbol": trade["symbol"],
                "status": "✅ مُغلقة",
            })
            logger.warning(f"   ✅ تم الإغلاق بنجاح\n")
            
            # تأخير صغير لتجنب تجاوز حد المعدل
            await asyncio.sleep(0.5)
            
        except Exception as e:
            results["failed"] += 1
            results["details"].append({
                "id": trade["id"],
                "symbol": trade["symbol"],
                "status": f"❌ فشل: {str(e)[:50]}",
            })
            logger.error(f"   ❌ فشل: {e}\n")
            await asyncio.sleep(0.5)
    
    logger.warning(f"\n{'='*80}")
    logger.warning(f"📊 النتائج النهائية:")
    logger.warning(f"   ✅ مُغلقة: {results['closed']}/{results['total']}")
    logger.warning(f"   ❌ فشلت: {results['failed']}/{results['total']}")
    logger.warning(f"{'='*80}\n")
    
    return results


async def close_trade_by_id(trade_id: int) -> bool:
    """
    🎯 إغلاق صفقة محددة بـ ID
    """
    open_trades = await db_trades.get_open_trades()
    trade = next((t for t in open_trades if t["id"] == trade_id), None)
    
    if trade is None:
        logger.error(f"❌ لم يتم العثور على صفقة مفتوحة برقم #{trade_id}")
        return False
    
    try:
        logger.warning(f"🔄 إغلاق الصفقة #{trade_id} ({trade['symbol']})...")
        
        await execute_emergency_sell(
            trade,
            reason=f"إغلاق يدوي للصفقة #{trade_id}",
        )
        
        logger.warning(f"✅ تم إغلاق الصفقة #{trade_id} بنجاح")
        return True
        
    except Exception as e:
        logger.error(f"❌ فشل إغلاق الصفقة #{trade_id}: {e}")
        return False


async def close_all_on_startup() -> dict:
    """
    🔄 يُستدعى تلقائياً عند بدء البوت
    إغلاق جميع الصفقات المفتوحة من الجلسة السابقة (إن وجدت)
    """
    logger.info("\n" + "="*80)
    logger.info("🔍 فحص الصفقات المفتوحة من الجلسة السابقة...")
    logger.info("="*80 + "\n")
    
    open_trades = await db_trades.get_open_trades()
    
    if not open_trades:
        logger.info("✅ لا توجد صفقات مفتوحة من جلسات سابقة")
        return {"closed": 0, "failed": 0, "total": 0}
    
    logger.warning(f"\n⚠️ تحذير: وُجدت {len(open_trades)} صفقة مفتوحة من الجلسة السابقة!")
    logger.warning("سيتم إغلاقها جميعاً تلقائياً لتجنب فقدان الرصيد...\n")
    
    # إعطاء الوقت للمستخدم لقراءة التنبيه
    await asyncio.sleep(3)
    
    return await close_all_open_trades()


async def print_wallet_status():
    """
    💰 عرض حالة المحفظة الحالية
    """
    try:
        keypair = load_wallet_keypair()
        balance = await get_wallet_sol_balance(str(keypair.pubkey()))
        
        logger.info(f"\n💰 حالة المحفظة:")
        logger.info(f"   العنوان: {str(keypair.pubkey())[:16]}...")
        logger.info(f"   الرصيد: {balance:.4f} SOL\n")
        
        return balance
    except Exception as e:
        logger.error(f"❌ تعذّر جلب حالة المحفظة: {e}")
        return None


# ──────────────────────────────────────────────────────────────
# أوامر استخدام مباشرة من سطر الأوامر
# ──────────────────────────────────────────────────────────────

async def main():
    """
    أدوات يدوية — استخدم واحداً من هذه:
    
    python recovery_close_trades.py list
        → عرض جميع الصفقات المفتوحة
    
    python recovery_close_trades.py close-all
        → إغلاق جميع الصفقات المفتوحة
    
    python recovery_close_trades.py close 5
        → إغلاق الصفقة رقم 5
    
    python recovery_close_trades.py balance
        → عرض رصيد المحفظة
    """
    import sys
    
    if len(sys.argv) < 2:
        logger.info(main.__doc__)
        return
    
    command = sys.argv[1]
    
    if command == "list":
        await list_open_trades()
    
    elif command == "close-all":
        await close_all_open_trades()
    
    elif command == "close" and len(sys.argv) > 2:
        trade_id = int(sys.argv[2])
        await close_trade_by_id(trade_id)
    
    elif command == "balance":
        await print_wallet_status()
    
    else:
        logger.error(f"❌ أمر غير معروف: {command}")
        logger.info(main.__doc__)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    asyncio.run(main())
