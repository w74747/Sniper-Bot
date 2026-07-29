"""
✅ التقارير المحلية الخفيفة كل 3 ساعات - بدون DeepSeek
تقارير إحصائية + مراقبة صحة النظام
"""

import logging
import asyncio
import time
from datetime import datetime, timedelta
from typing import Dict, List

from db import trades as db
from utils.solana_rpc import get_wallet_sol_balance
from config.settings import WALLET_KEYPAIR_PATH
from db.log_handler import load_wallet_keypair

logger = logging.getLogger("hourly_report")


class HourlyReportSystem:
    """
    تقارير محلية كل 3 ساعات - إحصائيات + صحة النظام
    """
    
    def __init__(self):
        self.last_report_time = None
        self.report_interval_hours = 3
    
    async def should_generate_report(self) -> bool:
        """هل حان وقت التقرير؟"""
        if self.last_report_time is None:
            return True
        
        elapsed = (time.time() - self.last_report_time) / 3600
        return elapsed >= self.report_interval_hours
    
    async def generate_light_report(self) -> Dict:
        """
        ✅ تقرير خفيف بدون DeepSeek
        """
        self.last_report_time = time.time()
        
        # 1. الإحصائيات الأساسية
        stats = await self._get_trade_statistics()
        
        # 2. أداء الاستراتيجيات
        strategy_perf = await self._get_strategy_performance()
        
        # 3. صحة النظام
        system_health = await self._get_system_health()
        
        # 4. الأخطاء المتكررة
        recurring_errors = await self._get_recurring_errors()
        
        report = {
            "timestamp": datetime.now().isoformat(),
            "statistics": stats,
            "strategy_performance": strategy_perf,
            "system_health": system_health,
            "recurring_errors": recurring_errors,
            "recommendations": await self._generate_recommendations(stats, strategy_perf)
        }
        
        logger.info(f"\n{'='*60}\n📊 HOURLY LIGHT REPORT ({self.report_interval_hours}h)\n{'='*60}\n{self._format_report(report)}\n{'='*60}")
        
        return report
    
    async def _get_trade_statistics(self) -> Dict:
        """الإحصائيات التجارية"""
        try:
            closed_trades = await db.get_closed_trades_recent(hours=3)
            open_trades = await db.get_open_trades()
            
            if not closed_trades:
                return {
                    "closed_count": 0,
                    "win_rate": 0,
                    "avg_profit": 0,
                    "open_trades": len(open_trades)
                }
            
            winners = [t for t in closed_trades if t.get("profit_loss_sol", 0) > 0]
            win_rate = (len(winners) / len(closed_trades)) * 100
            avg_profit = sum(t.get("profit_loss_sol", 0) for t in closed_trades) / len(closed_trades)
            
            return {
                "closed_count": len(closed_trades),
                "win_count": len(winners),
                "loss_count": len(closed_trades) - len(winners),
                "win_rate_pct": win_rate,
                "avg_profit_loss_sol": avg_profit,
                "total_profit_loss_sol": sum(t.get("profit_loss_sol", 0) for t in closed_trades),
                "open_trades": len(open_trades)
            }
        except Exception as e:
            logger.error(f"خطأ في جلب الإحصائيات: {e}")
            return {}
    
    async def _get_strategy_performance(self) -> Dict:
        """أداء كل استراتيجية"""
        try:
            strategies = ["momentum", "sustained_trend", "holder_velocity", "graduation_proximity", "established_liquid"]
            perf = {}
            
            for strategy in strategies:
                trades = await db.get_trades_by_strategy(strategy, limit=50)
                if not trades:
                    continue
                
                closed = [t for t in trades if t.get("exit_reason")]
                if not closed:
                    perf[strategy] = {"count": 0, "win_rate": 0, "avg_pnl": 0}
                    continue
                
                winners = [t for t in closed if t.get("profit_loss_sol", 0) > 0]
                perf[strategy] = {
                    "count": len(closed),
                    "win_rate_pct": (len(winners) / len(closed)) * 100,
                    "avg_pnl_sol": sum(t.get("profit_loss_sol", 0) for t in closed) / len(closed)
                }
            
            return perf
        except Exception as e:
            logger.error(f"خطأ في حساب أداء الاستراتيجيات: {e}")
            return {}
    
    async def _get_system_health(self) -> Dict:
        """صحة النظام - RPC، DB، المحفظة"""
        health = {
            "wallet_balance": 0,
            "database_connected": False,
            "rpc_providers": {}
        }
        
        try:
            keypair = load_wallet_keypair()
            balance = await get_wallet_sol_balance(str(keypair.pubkey()))
            health["wallet_balance"] = balance
        except Exception as e:
            logger.warning(f"تعذر جلب رصيد المحفظة: {e}")
        
        try:
            # اختبر اتصال قاعدة البيانات
            open_trades = await db.get_open_trades()
            health["database_connected"] = True
        except Exception as e:
            logger.error(f"خطأ في الاتصال بقاعدة البيانات: {e}")
            health["database_connected"] = False
        
        # TODO: اختبر صحة مزودي RPC
        
        return health
    
    async def _get_recurring_errors(self) -> List[Dict]:
        """الأخطاء المتكررة في آخر 3 ساعات"""
        try:
            recent_logs = await db.get_error_logs_recent(hours=3)
            
            error_counts = {}
            for log in recent_logs:
                error_type = log.get("error_type", "unknown")
                error_counts[error_type] = error_counts.get(error_type, 0) + 1
            
            # ترتيب حسب التكرار
            sorted_errors = sorted(error_counts.items(), key=lambda x: x[1], reverse=True)
            
            return [
                {"error": err, "count": count, "recommendation": self._error_recommendation(err)}
                for err, count in sorted_errors[:5]
            ]
        except Exception as e:
            logger.error(f"خطأ في جلب الأخطاء: {e}")
            return []
    
    async def _generate_recommendations(self, stats: Dict, perf: Dict) -> List[str]:
        """توصيات محددة بناءً على الإحصائيات"""
        recommendations = []
        
        if stats.get("win_rate_pct", 0) < 50:
            recommendations.append("⚠️ نسبة الفوز أقل من 50% - يحتاج تحسين الفلاتر")
        
        # أداء الاستراتيجيات
        for strategy, data in perf.items():
            if data.get("win_rate_pct", 0) < 30 and data.get("count", 0) >= 5:
                recommendations.append(f"⚠️ الاستراتيجية '{strategy}' بأداء ضعيف - قد تحتاج تعطيل مؤقت")
        
        if stats.get("open_trades", 0) > 20:
            recommendations.append("⚠️ عدد الصفقات المفتوحة كبير - قد تحتاج مراقبة أقسى")
        
        return recommendations if recommendations else ["✅ النظام يعمل بكفاءة عادية"]
    
    @staticmethod
    def _error_recommendation(error_type: str) -> str:
        """توصية حسب نوع الخطأ"""
        recommendations = {
            "rpc_timeout": "تحقق من اتصال RPC - قد تحتاج تبديل المزود",
            "honeypot_detected": "الفلاتر تعمل بشكل صحيح - عملات مريبة تُرفض",
            "insufficient_balance": "المحفظة فارغة - أعد التمويل",
            "execution_failed": "خطأ في التنفيذ - تحقق من الشبكة",
        }
        return recommendations.get(error_type, "عطل غير معروف - راجع اللوجات")
    
    def _format_report(self, report: Dict) -> str:
        """تنسيق التقرير للطباعة"""
        text = f"\n⏰ الوقت: {report['timestamp']}\n\n"
        
        # الإحصائيات
        stats = report.get("statistics", {})
        text += f"📊 الإحصائيات (آخر 3 ساعات):\n"
        text += f"   صفقات مغلقة: {stats.get('closed_count', 0)} ({stats.get('win_count', 0)} رابحة، {stats.get('loss_count', 0)} خاسرة)\n"
        text += f"   نسبة الفوز: {stats.get('win_rate_pct', 0):.1f}%\n"
        text += f"   متوسط الربح: {stats.get('avg_profit_loss_sol', 0):.4f} SOL\n"
        text += f"   إجمالي: {stats.get('total_profit_loss_sol', 0):.4f} SOL\n"
        text += f"   صفقات مفتوحة: {stats.get('open_trades', 0)}\n"
        
        # صحة النظام
        health = report.get("system_health", {})
        text += f"\n🔧 صحة النظام:\n"
        text += f"   رصيد المحفظة: {health.get('wallet_balance', 0):.4f} SOL\n"
        text += f"   قاعدة البيانات: {'✅ متصلة' if health.get('database_connected') else '❌ معطلة'}\n"
        
        # الأخطاء المتكررة
        errors = report.get("recurring_errors", [])
        if errors:
            text += f"\n⚠️ أخطاء متكررة:\n"
            for err in errors[:3]:
                text += f"   • {err['error']}: {err['count']} مرات\n"
                text += f"     → {err['recommendation']}\n"
        
        # التوصيات
        text += f"\n💡 التوصيات:\n"
        for rec in report.get("recommendations", []):
            text += f"   {rec}\n"
        
        return text


async def run_hourly_report_loop():
    """حلقة التقارير المحلية كل 3 ساعات"""
    report_system = HourlyReportSystem()
    
    while True:
        try:
            if await report_system.should_generate_report():
                await report_system.generate_light_report()
            
            await asyncio.sleep(300)  # فحص كل 5 دقائق
        
        except Exception as e:
            logger.error(f"خطأ في حلقة التقارير: {e}")
            await asyncio.sleep(300)
