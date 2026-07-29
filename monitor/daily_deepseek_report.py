"""
✅ التقرير العميق اليومي مع DeepSeek
تحليل فني دقيق + توصيات محددة
مرة واحدة فقط يومياً لتقليل التكاليف
"""

import logging
import asyncio
import time
from datetime import datetime, timedelta
from typing import Dict
import os
import json

from db import trades as db

logger = logging.getLogger("daily_deepseek_report")


class DailyDeepSeekReport:
    """
    تقرير عميق يومي مع DeepSeek - تحليل فني + توصيات
    """
    
    def __init__(self):
        self.last_report_date = None
        self.deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
    
    async def should_generate_report(self) -> bool:
        """هل حان وقت التقرير اليومي؟ (مرة واحدة فقط يومياً)"""
        today = datetime.now().date()
        
        if self.last_report_date is None:
            return True
        
        return self.last_report_date != today
    
    async def generate_deep_report(self) -> Dict:
        """
        ✅ تقرير عميق: تحليل فني + استبيانات DeepSeek
        """
        self.last_report_date = datetime.now().date()
        
        # 1. جمع البيانات من آخر 24 ساعة
        trades_24h = await db.get_closed_trades_recent(hours=24)
        strategy_analysis = await self._analyze_strategies(trades_24h)
        error_patterns = await self._analyze_error_patterns()
        
        # 2. طلب تحليل من DeepSeek (استخدام فعال)
        deepseek_insights = await self._get_deepseek_analysis(
            trades_24h,
            strategy_analysis,
            error_patterns
        )
        
        report = {
            "date": datetime.now().isoformat(),
            "trades_24h": {
                "count": len(trades_24h),
                "data": trades_24h
            },
            "strategy_analysis": strategy_analysis,
            "error_patterns": error_patterns,
            "deepseek_insights": deepseek_insights,
            "actionable_recommendations": await self._generate_actionable_recommendations(
                strategy_analysis,
                deepseek_insights
            )
        }
        
        logger.info(f"\n{'='*70}\n🔬 DAILY DEEP ANALYSIS REPORT\n{'='*70}\n{self._format_deep_report(report)}\n{'='*70}")
        
        # حفظ التقرير
        await self._save_report(report)
        
        return report
    
    async def _analyze_strategies(self, trades: list) -> Dict:
        """تحليل أداء الاستراتيجيات"""
        strategies = {}
        
        for trade in trades:
            strategy = trade.get("strategy", "unknown")
            if strategy not in strategies:
                strategies[strategy] = {"trades": [], "wins": 0, "losses": 0, "total_pnl": 0}
            
            strategies[strategy]["trades"].append(trade)
            pnl = trade.get("profit_loss_sol", 0)
            strategies[strategy]["total_pnl"] += pnl
            
            if pnl > 0:
                strategies[strategy]["wins"] += 1
            else:
                strategies[strategy]["losses"] += 1
        
        # حساب المؤشرات
        for strategy_name, data in strategies.items():
            count = len(data["trades"])
            if count > 0:
                data["win_rate_pct"] = (data["wins"] / count) * 100
                data["avg_pnl_sol"] = data["total_pnl"] / count
                data["consistency_score"] = self._calculate_consistency(data["trades"])
        
        return strategies
    
    async def _analyze_error_patterns(self) -> Dict:
        """تحليل الأنماط الخاطئة المتكررة"""
        try:
            error_logs = await db.get_error_logs_recent(hours=24)
            
            patterns = {}
            for log in error_logs:
                error_type = log.get("logger_name", "unknown")
                if error_type not in patterns:
                    patterns[error_type] = {
                        "count": 0,
                        "times": [],
                        "messages": []
                    }
                
                patterns[error_type]["count"] += 1
                patterns[error_type]["times"].append(log.get("timestamp"))
                patterns[error_type]["messages"].append(log.get("message"))
            
            # تحليل الأنماط
            for error_type, data in patterns.items():
                data["frequency"] = self._calculate_frequency(data["times"])
                data["affected_components"] = list(set(data["messages"][:5]))  # أول 5 رسائل
            
            return patterns
        except Exception as e:
            logger.error(f"خطأ في تحليل الأخطاء: {e}")
            return {}
    
    async def _get_deepseek_analysis(self, trades: list, strategies: Dict, errors: Dict) -> Dict:
        """
        ✅ استدعاء DeepSeek مرة واحدة يومياً فقط
        تحليل فني دقيق + توصيات محددة
        """
        if not self.deepseek_api_key:
            logger.warning("DeepSeek API key غير موجود - تخطي التحليل العميق")
            return {}
        
        try:
            import aiohttp
            
            # تجميع البيانات للتحليل
            summary = {
                "total_trades": len(trades),
                "strategies": {k: {"wins": v["wins"], "losses": v["losses"], "avg_pnl": v.get("avg_pnl_sol", 0)} for k, v in strategies.items()},
                "top_errors": list(errors.keys())[:5]
            }
            
            prompt = f"""
            تحليل أداء نظام التداول الآلي في آخر 24 ساعة:
            
            البيانات:
            {json.dumps(summary, ensure_ascii=False, indent=2)}
            
            المطلوب:
            1. تحليل تقني لأداء كل استراتيجية
            2. أسباب فشل الاستراتيجيات الضعيفة
            3. توصيات محددة للتحسين
            4. أولويات الإصلاح التقني
            
            أجب بشكل مختصر وعملي فقط.
            """
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.deepseek.com/chat/completions",
                    headers={"Authorization": f"Bearer {self.deepseek_api_key}"},
                    json={
                        "model": "deepseek-chat",
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 1500
                    },
                    timeout=30
                ) as response:
                    result = await response.json()
                    
                    if "choices" in result:
                        return {
                            "analysis": result["choices"][0]["message"]["content"],
                            "tokens_used": result.get("usage", {}).get("total_tokens", 0),
                            "cost_usd": result.get("usage", {}).get("total_tokens", 0) * 0.00001  # تقريبي
                        }
        
        except Exception as e:
            logger.error(f"خطأ في استدعاء DeepSeek: {e}")
            return {"error": str(e)}
    
    async def _generate_actionable_recommendations(self, strategies: Dict, deepseek_analysis: Dict) -> list:
        """توصيات عملية محددة قابلة للتنفيذ"""
        recommendations = []
        
        # من تحليل الاستراتيجيات
        for strategy_name, data in strategies.items():
            win_rate = data.get("win_rate_pct", 0)
            
            if win_rate < 30 and data["trades"]:
                recommendations.append({
                    "priority": "HIGH",
                    "action": f"تعطيل مؤقت للاستراتيجية '{strategy_name}'",
                    "reason": f"نسبة الفوز {win_rate:.1f}% منخفضة جداً",
                    "implementation": f"أضف strategy.is_enabled = False في config/settings.py"
                })
            
            elif win_rate < 50 and data["trades"]:
                recommendations.append({
                    "priority": "MEDIUM",
                    "action": f"مراجعة معايير الدخول للاستراتيجية '{strategy_name}'",
                    "reason": f"نسبة الفوز {win_rate:.1f}% تحتاج تحسين",
                    "implementation": "ارفع عتبات الفلاتر في filters/"
                })
        
        # من تحليل DeepSeek (إذا توفر)
        if deepseek_analysis.get("analysis"):
            recommendations.append({
                "priority": "INFO",
                "action": "تحليل DeepSeek",
                "analysis": deepseek_analysis["analysis"]
            })
        
        return recommendations
    
    @staticmethod
    def _calculate_consistency(trades: list) -> float:
        """قياس اتساق الأداء (0-100)"""
        if len(trades) < 3:
            return 0
        
        pnls = [t.get("profit_loss_sol", 0) for t in trades]
        avg_pnl = sum(pnls) / len(pnls)
        variance = sum((pnl - avg_pnl) ** 2 for pnl in pnls) / len(pnls)
        std_dev = variance ** 0.5
        
        # نموذج بسيط: الانحراف المعياري الأصغر = الاتساق الأكبر
        consistency = max(0, 100 - (std_dev * 100))
        return min(100, consistency)
    
    @staticmethod
    def _calculate_frequency(times: list) -> str:
        """حساب تكرار الأخطاء"""
        if len(times) == 0:
            return "نادر"
        elif len(times) <= 2:
            return "نادر"
        elif len(times) <= 5:
            return "معتدل"
        else:
            return "متكرر جداً"
    
    def _format_deep_report(self, report: Dict) -> str:
        """تنسيق التقرير للطباعة"""
        text = f"\n📅 التاريخ: {report['date']}\n\n"
        
        # الصفقات
        trades = report.get("trades_24h", {})
        text += f"📈 الصفقات (24 ساعة): {trades.get('count', 0)} صفقة\n"
        
        # تحليل الاستراتيجيات
        strategies = report.get("strategy_analysis", {})
        text += f"\n🎯 أداء الاستراتيجيات:\n"
        for strategy_name, data in strategies.items():
            text += f"   {strategy_name}:\n"
            text += f"      الصفقات: {len(data['trades'])} (رابحة: {data['wins']}, خاسرة: {data['losses']})\n"
            text += f"      نسبة الفوز: {data.get('win_rate_pct', 0):.1f}%\n"
            text += f"      متوسط الربح: {data.get('avg_pnl_sol', 0):.4f} SOL\n"
        
        # تحليل DeepSeek
        deepseek = report.get("deepseek_insights", {})
        if deepseek.get("analysis"):
            text += f"\n🔬 تحليل DeepSeek:\n{deepseek['analysis']}\n"
        
        # التوصيات
        recommendations = report.get("actionable_recommendations", [])
        text += f"\n💡 التوصيات العملية:\n"
        for rec in recommendations[:5]:
            priority_icon = {"HIGH": "🔴", "MEDIUM": "🟡", "INFO": "ℹ️"}.get(rec.get("priority"), "•")
            text += f"   {priority_icon} {rec.get('action')}\n"
            if rec.get("reason"):
                text += f"      السبب: {rec['reason']}\n"
        
        return text
    
    async def _save_report(self, report: Dict):
        """حفظ التقرير في DB أو ملف"""
        try:
            report_json = json.dumps(report, ensure_ascii=False, indent=2)
            # TODO: حفظ في database أو S3
            logger.debug(f"تم حفظ التقرير اليومي")
        except Exception as e:
            logger.error(f"خطأ في حفظ التقرير: {e}")


async def run_daily_deepseek_report_loop():
    """حلقة التقارير اليومية"""
    report_system = DailyDeepSeekReport()
    
    while True:
        try:
            if await report_system.should_generate_report():
                await report_system.generate_deep_report()
            
            await asyncio.sleep(3600)  # فحص كل ساعة
        
        except Exception as e:
            logger.error(f"خطأ في حلقة التقارير اليومية: {e}")
            await asyncio.sleep(3600)
