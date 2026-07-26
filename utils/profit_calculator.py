"""
✅ ملف جديد: utils/profit_calculator.py
حساب دقيق للأرباح والخسائر مع احتساب:
- Slippage (انزلاق السعر)
- ضريبة البيع الفعلية
- رسوم Solana و Jupiter
"""
import logging
from typing import Dict

logger = logging.getLogger("profit_calculator")


class ProfitCalculator:
    """حساب الأرباح بشكل واقعي"""
    
    @staticmethod
    def calculate_realistic_profit(
        buy_price_sol: float,
        sell_price_sol: float,
        amount_tokens: float,
        sell_tax_percent: float = 2.0,
        slippage_percent: float = 1.5,
        jupiter_fee_percent: float = 0.4,
        solana_fee_sol: float = 0.000005,
    ) -> Dict:
        """
        حساب الربح الفعلي مع جميع الرسوم
        
        Returns:
            {
                "gross_cost": 0.100,              # تكلفة الشراء
                "gross_sell_value": 0.110,        # قيمة البيع قبل الرسوم
                "gross_roi_percent": 10.0,        # ROI قبل الرسوم
                "slippage_loss": 0.00165,         # خسارة الانزلاق
                "sell_tax_loss": 0.00220,         # ضريبة البيع
                "jupiter_fee": 0.00044,           # رسوم Jupiter
                "solana_fee": 0.000005,           # رسوم Solana
                "total_fees": 0.00430,            # إجمالي الرسوم
                "net_profit": 0.00570,            # الربح الفعلي
                "realistic_roi_percent": 5.7,     # ROI الفعلي %
                "is_profitable": True,            # هل الصفقة رابحة؟
            }
        """
        
        # التكلفة الإجمالية (الشراء)
        gross_cost = buy_price_sol
        
        # قيمة البيع قبل الرسوم
        gross_sell_value = sell_price_sol * amount_tokens
        
        # الربح الإجمالي قبل الرسوم
        gross_profit = gross_sell_value - gross_cost
        gross_roi_percent = (gross_profit / gross_cost) * 100 if gross_cost > 0 else 0
        
        # حساب الرسوم الفعلية
        slippage_loss = gross_sell_value * (slippage_percent / 100)
        sell_tax_loss = gross_sell_value * (sell_tax_percent / 100)
        jupiter_fee = gross_sell_value * (jupiter_fee_percent / 100)
        total_fees = slippage_loss + sell_tax_loss + jupiter_fee + solana_fee_sol
        
        # الربح الفعلي
        net_profit = gross_profit - total_fees
        realistic_roi_percent = (net_profit / gross_cost) * 100 if gross_cost > 0 else 0
        
        return {
            "gross_cost": gross_cost,
            "gross_sell_value": gross_sell_value,
            "gross_roi_percent": round(gross_roi_percent, 2),
            "slippage_loss": round(slippage_loss, 6),
            "slippage_percent": slippage_percent,
            "sell_tax_loss": round(sell_tax_loss, 6),
            "sell_tax_percent": sell_tax_percent,
            "jupiter_fee": round(jupiter_fee, 6),
            "jupiter_fee_percent": jupiter_fee_percent,
            "solana_fee": solana_fee_sol,
            "total_fees": round(total_fees, 6),
            "net_profit": round(net_profit, 6),
            "realistic_roi_percent": round(realistic_roi_percent, 2),
            "is_profitable": net_profit > 0,
        }
    
    @staticmethod
    def calculate_breakeven_price(
        buy_price_sol: float,
        sell_tax_percent: float = 2.0,
        slippage_percent: float = 1.5,
        jupiter_fee_percent: float = 0.4,
    ) -> float:
        """
        احسب سعر البيع اللي يعطيك صفر خسارة/ربح
        مع احتساب جميع الرسوم
        """
        total_costs_percent = sell_tax_percent + slippage_percent + jupiter_fee_percent
        breakeven = buy_price_sol * (1 + (total_costs_percent / 100))
        return round(breakeven, 8)
    
    @staticmethod
    def should_sell(
        buy_price_sol: float,
        current_price_sol: float,
        min_profit_percent: float = 5.0,
        max_loss_percent: float = -10.0,
        sell_tax_percent: float = 2.0,
        slippage_percent: float = 1.5,
    ) -> Dict:
        """
        قرار سريع: هل يجب البيع الآن؟
        
        Returns:
            {
                "should_sell": True/False,
                "reason": "...",
                "current_roi_percent": 15.5,
                "realistic_roi_percent": 12.1,
            }
        """
        gross_roi = ((current_price_sol - buy_price_sol) / buy_price_sol) * 100
        realistic_roi = gross_roi - (sell_tax_percent + slippage_percent + 0.4)
        
        should_sell = False
        reason = ""
        
        if realistic_roi >= min_profit_percent:
            should_sell = True
            reason = f"✅ ربح كافٍ: {realistic_roi:.1f}% (الحد الأدنى: {min_profit_percent}%)"
        elif realistic_roi < max_loss_percent:
            should_sell = True
            reason = f"❌ خسارة كبيرة: {realistic_roi:.1f}% (الحد الأقصى: {max_loss_percent}%)"
        else:
            reason = f"⏳ انتظر: الربح الحالي {realistic_roi:.1f}% (الحد الأدنى: {min_profit_percent}%)"
        
        return {
            "should_sell": should_sell,
            "reason": reason,
            "gross_roi_percent": round(gross_roi, 2),
            "realistic_roi_percent": round(realistic_roi, 2),
        }
