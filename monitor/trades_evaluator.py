"""
✅ Module تقييم الصفقات المتكامل
يعمل تلقائياً:
- عند بدء البوت
- بعد كل تحديث لأي صفقة
- دورياً كل ساعة
"""

import logging
import asyncio
from typing import Dict, List, Tuple
from datetime import datetime, timedelta
import time

from db import trades as db
from trading.swap_client import get_jupiter_quote, SOL_MINT_ADDRESS

logger = logging.getLogger("trades_evaluator")


class TradesEvaluator:
    """نظام تقييم الصفقات المتكامل"""
    
    def __init__(self, age_threshold_hours: int = 48):
        self.age_threshold_hours = age_threshold_hours
        self.last_full_evaluation = 0
        self.evaluation_interval = 3600  # كل ساعة
    
    async def evaluate_on_startup(self):
        """
        ✅ تقييم عند بدء البوت
        """
        logger.info("\n" + "="*80)
        logger.info("🔍 تقييم الصفقات المفتوحة عند البدء")
        logger.info("="*80 + "\n")
        
        try:
            open_trades = await db.get_open_trades()
            
            if not open_trades:
                logger.info("✅ لا توجد صفقات مفتوحة\n")
                return
            
            logger.info(f"📊 تقييم {len(open_trades)} صفقة مفتوحة...\n")
            
            results = await self._evaluate_trades(open_trades)
            summary = self._generate_summary(results)
            
            # طباعة ملخص البدء
            self._print_startup_summary(summary)
            
            # حفظ في DB
            await self._save_evaluation_summary(summary)
            
        except Exception as e:
            logger.error(f"❌ خطأ في التقييم الأولي: {e}")
    
    async def evaluate_on_update(self, trade_id: int, update_type: str):
        """
        ✅ تقييم سريع بعد تحديث أي صفقة
        
        Args:
            trade_id: معرف الصفقة
            update_type: نوع التحديث (entry/exit/monitor)
        """
        try:
            trade = await db.get_trade_by_id(trade_id)
            if not trade:
                return
            
            result = await self._evaluate_single_trade(trade)
            
            if result["pnl_pct"] is None:
                return
            
            # قرار فوري
            decision = self._make_decision(
                pnl_pct=result["pnl_pct"],
                age_hours=result["age_hours"],
                current_price=result["current_price"],
                entry_price=result["entry_price"]
            )
            
            # إذا كان قرار حرج
            if decision["action"] == "CLOSE_IMMEDIATELY":
                logger.warning(
                    f"🔴 [تحديث] {result['symbol']}\n"
                    f"   الربح/الخسارة: {result['pnl_pct']:.1f}%\n"
                    f"   التوصية: {decision['reason']}"
                )
                # حفظ التحذير
                await db.save_trade_alert(
                    trade_id=trade_id,
                    alert_type="EVALUATION_WARNING",
                    message=f"تقييم: {decision['reason']}"
                )
            
        except Exception as e:
            logger.debug(f"خطأ في التقييم السريع: {e}")
    
    async def evaluate_periodic(self):
        """
        ✅ تقييم دوري كل ساعة
        للصفقات المفتوحة القديمة
        """
        current_time = time.time()
        
        # تشغيل كل ساعة فقط
        if current_time - self.last_full_evaluation < self.evaluation_interval:
            return
        
        self.last_full_evaluation = current_time
        
        try:
            logger.info("\n" + "-"*80)
            logger.info("⏰ تقييم دوري للصفقات القديمة")
            logger.info("-"*80 + "\n")
            
            open_trades = await db.get_open_trades()
            
            # تصفية الصفقات القديمة فقط
            old_trades = []
            for trade in open_trades:
                age_hours = (current_time - trade.get("entry_timestamp", 0)) / 3600
                if age_hours >= self.age_threshold_hours:
                    old_trades.append(trade)
            
            if not old_trades:
                logger.info(f"✅ لا توجد صفقات قديمة (>= {self.age_threshold_hours}h)\n")
                return
            
            logger.info(f"⚠️ تقييم {len(old_trades)} صفقات قديمة\n")
            
            results = await self._evaluate_trades(old_trades)
            summary = self._generate_summary(results)
            
            # طباعة التقرير الدوري
            self._print_periodic_report(summary)
            
            # حفظ في DB
            await self._save_evaluation_summary(summary)
            
        except Exception as e:
            logger.error(f"❌ خطأ في التقييم الدوري: {e}")
    
    async def _evaluate_trades(self, trades: List[Dict]) -> List[Dict]:
        """تقييم مجموعة من الصفقات"""
        results = []
        
        for trade in trades:
            result = await self._evaluate_single_trade(trade)
            if result:
                results.append(result)
        
        return results
    
    async def _evaluate_single_trade(self, trade: Dict) -> Dict:
        """تقييم صفقة واحدة"""
        current_time = time.time()
        
        mint_address = trade.get("mint_address")
        symbol = trade.get("symbol", mint_address[:8])
        trade_id = trade.get("id")
        entry_price = float(trade.get("entry_price", 0))
        capital_used = float(trade.get("capital_invested_sol", 0))
        entry_timestamp = trade.get("entry_timestamp", 0)
        
        age_hours = (current_time - entry_timestamp) / 3600
        
        # جلب السعر الحالي
        try:
            quote = await get_jupiter_quote(
                SOL_MINT_ADDRESS,
                mint_address,
                10_000_000,
                slippage_bps=500
            )
            current_price = float(quote.get("outAmount", 0))
        except Exception as e:
            logger.debug(f"⚠️ {symbol}: فشل جلب السعر")
            current_price = 0
        
        # حساب الربح/الخسارة
        if entry_price > 0 and current_price > 0:
            pnl_pct = ((current_price - entry_price) / entry_price) * 100
            estimated_tokens = capital_used / entry_price
            pnl_sol = (current_price - entry_price) * estimated_tokens
        else:
            pnl_pct = None
            pnl_sol = 0
        
        return {
            "trade_id": trade_id,
            "symbol": symbol,
            "mint_address": mint_address,
            "entry_price": entry_price,
            "current_price": current_price,
            "pnl_pct": pnl_pct,
            "pnl_sol": pnl_sol,
            "capital_used": capital_used,
            "age_hours": age_hours,
            "age_days": age_hours / 24,
            "entry_time": datetime.fromtimestamp(entry_timestamp).isoformat()
        }
    
    def _make_decision(self, pnl_pct: float, age_hours: float, 
                      current_price: float, entry_price: float) -> Dict:
        """اتخاذ قرار بشأن الصفقة"""
        
        age_days = age_hours / 24
        
        # منطق القرار
        if age_days > 7:  # أكثر من أسبوع
            if pnl_pct < -40:
                return {
                    "action": "CLOSE_IMMEDIATELY",
                    "reason": "خسارة حادة + عمر طويل جداً"
                }
            elif pnl_pct < -20:
                return {
                    "action": "CLOSE_SOON",
                    "reason": "خسارة معتدلة + عمر طويل"
                }
            elif pnl_pct < 0:
                return {
                    "action": "CLOSE_SOON",
                    "reason": "الصفقة عالقة (عمر > 7 أيام)"
                }
        
        elif age_days > 3:  # 3-7 أيام
            if pnl_pct < -50:
                return {
                    "action": "CLOSE_IMMEDIATELY",
                    "reason": "خسارة كارثية"
                }
            elif pnl_pct < -30:
                return {
                    "action": "CLOSE_SOON",
                    "reason": "خسارة حادة"
                }
        
        elif age_days > 2:  # 2-3 أيام
            if pnl_pct < -50:
                return {
                    "action": "CLOSE_IMMEDIATELY",
                    "reason": "خسارة كارثية"
                }
        
        return {
            "action": "MONITOR",
            "reason": "المراقبة المستمرة"
        }
    
    def _generate_summary(self, results: List[Dict]) -> Dict:
        """توليد ملخص التقييم"""
        if not results:
            return {"total": 0}
        
        summary = {
            "total": len(results),
            "timestamp": datetime.now().isoformat(),
            "close_immediately": [],
            "close_soon": [],
            "monitor": [],
            "stats": {
                "avg_pnl_pct": 0,
                "total_pnl_sol": 0,
                "oldest_trade_days": 0,
            }
        }
        
        total_pnl = 0
        max_age = 0
        
        for result in results:
            decision = self._make_decision(
                pnl_pct=result["pnl_pct"],
                age_hours=result["age_hours"],
                current_price=result["current_price"],
                entry_price=result["entry_price"]
            )
            
            trade_summary = {
                "symbol": result["symbol"],
                "pnl_pct": result["pnl_pct"],
                "age_days": round(result["age_days"], 1),
                "reason": decision["reason"]
            }
            
            if decision["action"] == "CLOSE_IMMEDIATELY":
                summary["close_immediately"].append(trade_summary)
            elif decision["action"] == "CLOSE_SOON":
                summary["close_soon"].append(trade_summary)
            else:
                summary["monitor"].append(trade_summary)
            
            if result["pnl_pct"] is not None:
                total_pnl += result["pnl_pct"]
                max_age = max(max_age, result["age_days"])
        
        if results:
            summary["stats"]["avg_pnl_pct"] = total_pnl / len(results)
            summary["stats"]["total_pnl_sol"] = sum(r["pnl_sol"] for r in results)
            summary["stats"]["oldest_trade_days"] = round(max_age, 1)
        
        return summary
    
    def _print_startup_summary(self, summary: Dict):
        """طباعة ملخص البدء"""
        logger.info(f"📊 الملخص:")
        logger.info(f"   إجمالي الصفقات: {summary['total']}")
        
        if summary["close_immediately"]:
            logger.warning(
                f"   🔴 للإغلاق الفوري: {len(summary['close_immediately'])}\n" +
                "\n".join(f"      • {t['symbol']}: {t['pnl_pct']:.1f}%" 
                         for t in summary["close_immediately"][:5])
            )
        
        if summary["close_soon"]:
            logger.warning(
                f"   🟠 للإغلاق قريباً: {len(summary['close_soon'])}"
            )
        
        if summary["monitor"]:
            logger.info(
                f"   🟢 تحت المراقبة: {len(summary['monitor'])}"
            )
        
        logger.info(f"   متوسط الربح/الخسارة: {summary['stats']['avg_pnl_pct']:.1f}%\n")
    
    def _print_periodic_report(self, summary: Dict):
        """طباعة التقرير الدوري"""
        if not summary["close_immediately"] and not summary["close_soon"]:
            logger.info("✅ جميع الصفقات تحت السيطرة\n")
            return
        
        if summary["close_immediately"]:
            logger.warning("🔴 صفقات للإغلاق الفوري:")
            for t in summary["close_immediately"]:
                logger.warning(
                    f"   • {t['symbol']}: {t['pnl_pct']:.1f}% "
                    f"({t['age_days']:.1f} days) - {t['reason']}"
                )
        
        if summary["close_soon"]:
            logger.warning("🟠 صفقات للإغلاق قريباً:")
            for t in summary["close_soon"][:3]:
                logger.warning(
                    f"   • {t['symbol']}: {t['pnl_pct']:.1f}% "
                    f"({t['age_days']:.1f} days)"
                )
        
        logger.info("")
    
    async def _save_evaluation_summary(self, summary: Dict):
        """حفظ ملخص التقييم في DB"""
        try:
            # يمكن حفظها في جدول evaluation_history
            # للآن فقط سجل في الـ logs
            if summary["close_immediately"]:
                for trade in summary["close_immediately"]:
                    logger.warning(
                        f"[EVAL SAVED] {trade['symbol']}: "
                        f"Close immediately - {trade['reason']}"
                    )
        except Exception as e:
            logger.debug(f"خطأ في حفظ التقييم: {e}")


# إنشاء instance عام
evaluator = TradesEvaluator(age_threshold_hours=48)


async def run_periodic_evaluation():
    """
    ✅ حلقة التقييم الدوري
    تعمل بالتوازي مع البوت
    """
    while True:
        try:
            await evaluator.evaluate_periodic()
            await asyncio.sleep(60)  # فحص كل دقيقة
        
        except Exception as e:
            logger.error(f"خطأ في حلقة التقييم: {e}")
            await asyncio.sleep(60)
