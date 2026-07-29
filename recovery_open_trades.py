"""
🆘 تقييم الصفقات المفتوحة بعد التوقف الطارئ
جلب السعر الحالي + حساب الربح/الخسارة الفعلي
توصيات: أيها نبيع فوراً؟ أيها ننتظر؟
"""

import asyncio
import logging
from typing import Dict, List
from datetime import datetime

from db import trades as db
from trading.swap_client import get_jupiter_quote, SOL_MINT_ADDRESS
from utils.solscan_client import get_token_metadata

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("recovery")


class TradeRecoveryAnalyzer:
    """تحليل الصفقات المفتوحة بعد التوقف"""
    
    def __init__(self):
        self.open_trades = []
        self.current_prices = {}
        self.analysis_results = []
    
    async def recover_and_analyze(self) -> Dict:
        """
        ✅ التحليل الكامل للصفقات المفتوحة
        """
        logger.info("\n" + "="*80)
        logger.info("🆘 TRADE RECOVERY ANALYSIS - بعد التوقف الطارئ")
        logger.info("="*80 + "\n")
        
        # 1. جلب الصفقات المفتوحة من DB
        logger.info("📥 جلب الصفقات المفتوحة من قاعدة البيانات...")
        self.open_trades = await db.get_open_trades()
        logger.info(f"✅ تم العثور على {len(self.open_trades)} صفقة مفتوحة\n")
        
        # 2. جلب الأسعار الحالية
        logger.info("📊 جلب الأسعار الحالية من Jupiter...")
        await self._fetch_current_prices()
        logger.info(f"✅ تم جلب {len(self.current_prices)} سعر\n")
        
        # 3. حساب الربح/الخسارة لكل صفقة
        logger.info("🧮 حساب الربح/الخسارة الفعلي...")
        await self._calculate_pnl()
        logger.info(f"✅ تم حساب الربح/الخسارة لـ {len(self.analysis_results)} صفقة\n")
        
        # 4. توليد التوصيات
        logger.info("💡 توليد التوصيات...")
        recommendations = self._generate_recommendations()
        
        # طباعة التقرير
        self._print_recovery_report(recommendations)
        
        return {
            "timestamp": datetime.now().isoformat(),
            "total_open_trades": len(self.open_trades),
            "analysis": self.analysis_results,
            "recommendations": recommendations
        }
    
    async def _fetch_current_prices(self):
        """جلب السعر الحالي لكل عملة"""
        for trade in self.open_trades:
            mint_address = trade.get("mint_address")
            symbol = trade.get("symbol", mint_address[:8])
            
            try:
                quote = await get_jupiter_quote(
                    SOL_MINT_ADDRESS,
                    mint_address,
                    10_000_000,  # 0.01 SOL
                    slippage_bps=500
                )
                
                current_price = float(quote.get("outAmount", 0))
                self.current_prices[mint_address] = {
                    "symbol": symbol,
                    "price": current_price,
                    "success": current_price > 0
                }
                
                if current_price == 0:
                    logger.warning(f"⚠️ {symbol}: السعر = 0 (قد يكون honeypot أو معطل)")
            
            except Exception as e:
                logger.error(f"❌ {symbol}: فشل جلب السعر - {str(e)[:60]}")
                self.current_prices[mint_address] = {
                    "symbol": symbol,
                    "price": 0,
                    "success": False,
                    "error": str(e)
                }
    
    async def _calculate_pnl(self):
        """حساب الربح/الخسارة لكل صفقة"""
        for trade in self.open_trades:
            mint_address = trade.get("mint_address")
            symbol = trade.get("symbol", mint_address[:8])
            trade_id = trade.get("id")
            entry_price = float(trade.get("entry_price", 0))
            amount_bought = float(trade.get("amount_bought", 0))
            capital_used = float(trade.get("capital_used", 0))
            
            price_info = self.current_prices.get(mint_address, {})
            current_price = price_info.get("price", 0)
            price_success = price_info.get("success", False)
            
            if not price_success:
                self.analysis_results.append({
                    "trade_id": trade_id,
                    "symbol": symbol,
                    "mint_address": mint_address,
                    "entry_price": entry_price,
                    "current_price": 0,
                    "pnl_pct": 0,
                    "pnl_sol": 0,
                    "status": "❌ خطأ - لا يمكن حساب السعر",
                    "recommendation": "تحقق يدوياً من حالة العملة"
                })
                continue
            
            # حساب الربح/الخسارة
            if entry_price > 0:
                pnl_pct = ((current_price - entry_price) / entry_price) * 100
            else:
                pnl_pct = 0
            
            pnl_sol = (current_price - entry_price) * amount_bought if amount_bought > 0 else 0
            
            # تحديد الحالة والتوصية
            status, recommendation = self._determine_action(
                pnl_pct,
                current_price,
                entry_price,
                capital_used
            )
            
            self.analysis_results.append({
                "trade_id": trade_id,
                "symbol": symbol,
                "mint_address": mint_address,
                "entry_price": entry_price,
                "current_price": current_price,
                "pnl_pct": pnl_pct,
                "pnl_sol": pnl_sol,
                "capital_used": capital_used,
                "status": status,
                "recommendation": recommendation
            })
    
    def _determine_action(self, pnl_pct: float, current_price: float, 
                         entry_price: float, capital_used: float) -> tuple:
        """تحديد التوصية بناءً على الربح/الخسارة"""
        
        # خسارة كارثية
        if pnl_pct < -70:
            return (
                "🔴 خسارة كارثية",
                "✅ أبيع الآن - لا تنتظر المزيد"
            )
        
        # خسارة كبيرة
        elif pnl_pct < -40:
            return (
                "🔴 خسارة كبيرة",
                "⚠️ أبيع فوراً - قبل تفاقم الخسارة"
            )
        
        # خسارة معتدلة
        elif pnl_pct < -20:
            return (
                "🟠 خسارة معتدلة",
                "⚠️ أبيع - الاتجاه معاكس"
            )
        
        # خسارة صغيرة
        elif pnl_pct < 0:
            return (
                "🟡 خسارة صغيرة",
                "⏳ انتظر قليلاً - قد تنعكس"
            )
        
        # ربح صغير
        elif pnl_pct < 15:
            return (
                "🟢 ربح صغير",
                "✅ بيع 20% - تثبيت جزء من الربح"
            )
        
        # ربح معتدل
        elif pnl_pct < 50:
            return (
                "🟢 ربح معتدل",
                "✅ بيع 30% - تثبيت أكثر"
            )
        
        # ربح كبير
        else:
            return (
                "💰 ربح كبير",
                "✅ بيع 50% - تأمين الربح"
            )
    
    def _generate_recommendations(self) -> Dict:
        """توليد الأوامر العملية"""
        recommendations = {
            "urgent_sell": [],
            "immediate_sell": [],
            "partial_sell": [],
            "hold_watch": []
        }
        
        for result in self.analysis_results:
            symbol = result["symbol"]
            
            if "أبيع الآن" in result["recommendation"] or "أبيع فوراً" in result["recommendation"]:
                recommendations["urgent_sell"].append(symbol)
            elif "بيع 50%" in result["recommendation"]:
                recommendations["partial_sell"].append({"symbol": symbol, "pct": 50})
            elif "بيع 30%" in result["recommendation"]:
                recommendations["partial_sell"].append({"symbol": symbol, "pct": 30})
            elif "بيع 20%" in result["recommendation"]:
                recommendations["partial_sell"].append({"symbol": symbol, "pct": 20})
            elif "انتظر" in result["recommendation"]:
                recommendations["hold_watch"].append(symbol)
        
        return recommendations
    
    def _print_recovery_report(self, recommendations: Dict):
        """طباعة التقرير الكامل"""
        
        logger.info("\n" + "="*80)
        logger.info("📋 التقرير الكامل للصفقات المفتوحة")
        logger.info("="*80 + "\n")
        
        # الصفقات التفصيلية
        for result in sorted(self.analysis_results, 
                            key=lambda x: x["pnl_pct"], 
                            reverse=True):
            logger.info(f"{result['symbol']:12} | "
                       f"دخول: {result['entry_price']:12.6f} | "
                       f"حالي: {result['current_price']:12.6f} | "
                       f"الربح/الخسارة: {result['pnl_pct']:8.1f}% | "
                       f"{result['pnl_sol']:10.4f} SOL")
            logger.info(f"   → الحالة: {result['status']}")
            logger.info(f"   → التوصية: {result['recommendation']}\n")
        
        # الملخص
        logger.info("\n" + "="*80)
        logger.info("🎯 ملخص الإجراءات المطلوبة")
        logger.info("="*80 + "\n")
        
        if recommendations["urgent_sell"]:
            logger.info(f"🔴 بيع فوري (الآن):")
            for symbol in recommendations["urgent_sell"]:
                logger.info(f"   • {symbol}")
        
        if recommendations["partial_sell"]:
            logger.info(f"\n⚠️ بيع جزئي:")
            for item in recommendations["partial_sell"]:
                logger.info(f"   • {item['symbol']}: بيع {item['pct']}%")
        
        if recommendations["hold_watch"]:
            logger.info(f"\n⏳ مراقبة والانتظار:")
            for symbol in recommendations["hold_watch"]:
                logger.info(f"   • {symbol}")
        
        logger.info("\n" + "="*80 + "\n")


async def main():
    """البرنامج الرئيسي"""
    analyzer = TradeRecoveryAnalyzer()
    result = await analyzer.recover_and_analyze()
    
    # حفظ النتيجة
    import json
    with open("recovery_report.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    logger.info("✅ تم حفظ التقرير في: recovery_report.json\n")


if __name__ == "__main__":
    asyncio.run(main())
