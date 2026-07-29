"""
✅ نظام الخروج المتدرج الذكي + فوري عند الخطر
"""

import logging
import time
from typing import Dict, Optional, Tuple
from dataclasses import dataclass

from trading.executor import execute_emergency_sell, execute_normal_sell
from trading.swap_client import get_jupiter_quote, SOL_MINT_ADDRESS

logger = logging.getLogger("smart_exit")


@dataclass
class ExitStage:
    """تعريف مرحلة خروج واحدة"""
    stage_number: int
    profit_threshold_pct: float  # عتبة الربح (مثل 15%)
    sell_amount_pct: float       # نسبة البيع (مثل 20%)
    reason: str                  # السبب


# مراحل الخروج المتدرجة
EXIT_STAGES = [
    ExitStage(1, 15.0, 20.0, "+15% ربح - تأمين جزء صغير"),
    ExitStage(2, 30.0, 30.0, "+30% ربح - تأمين جزء أكبر"),
    ExitStage(3, 50.0, 25.0, "+50% ربح - تأمين نصف الربح"),
    ExitStage(4, 100.0, 15.0, "+100% ربح - ركوب بقية الصعود"),
]


class SmartExitStrategy:
    """
    ✅ نظام خروج متدرج ذكي
    - خروج تدريجي عند الربح
    - خروج فوري عند الخطر
    """
    
    def __init__(self, trade: Dict):
        """
        تهيئة الاستراتيجية لصفقة واحدة
        """
        self.trade_id = trade["id"]
        self.mint_address = trade["mint_address"]
        self.entry_price = float(trade["entry_price"])
        self.entry_amount = float(trade["amount_bought"])
        self.entry_value_sol = float(trade.get("capital_used", 0))
        self.entry_time = time.time()
        
        # تتبع الخروج
        self.stages_executed = {}  # {stage_number: amount_sold}
        self.total_recovered = 0.0
        self.total_proceeds = 0.0
        self.remaining_amount = self.entry_amount
        
        logger.info(
            f"✅ نظام الخروج الذكي مفعّل للصفقة {self.trade_id}\n"
            f"   رأس مال: {self.entry_value_sol:.4f} SOL"
        )
    
    def get_current_pnl_pct(self, current_price: float) -> float:
        """
        ✅ حساب الربح/الخسارة الحالي %
        """
        if self.entry_price <= 0:
            return 0.0
        
        return ((current_price - self.entry_price) / self.entry_price) * 100
    
    def get_stage_to_execute(self, current_price: float) -> Optional[ExitStage]:
        """
        ✅ تحديد أي مرحلة يجب تنفيذها الآن
        """
        pnl = self.get_current_pnl_pct(current_price)
        
        # تحقق من كل مرحلة (من الأصغر للأكبر)
        for stage in EXIT_STAGES:
            if pnl >= stage.profit_threshold_pct and stage.stage_number not in self.stages_executed:
                return stage
        
        return None
    
    async def execute_stage_exit(self, stage: ExitStage, current_price: float) -> Dict:
        """
        ✅ تنفيذ بيع المرحلة
        """
        # حساب كمية البيع
        amount_to_sell = self.remaining_amount * (stage.sell_amount_pct / 100)
        pnl = self.get_current_pnl_pct(current_price)
        
        logger.info(
            f"📊 المرحلة {stage.stage_number}: {stage.reason}\n"
            f"   الربح الحالي: {pnl:.1f}%\n"
            f"   بيع: {amount_to_sell:.0f} من {self.remaining_amount:.0f} tokens"
        )
        
        try:
            # تنفيذ البيع التدريجي
            trade_dict = {
                "id": self.trade_id,
                "mint_address": self.mint_address,
                "amount_bought": self.entry_amount,
                "capital_invested_sol": self.entry_value_sol
            }
            result = await execute_normal_sell(
                trade=trade_dict,
                reason=f"مرحلة {stage.stage_number}: {stage.reason}"
            )
            
            # تحديث الحالة
            proceeds = float(result.get("proceeds_sol", 0))
            self.stages_executed[stage.stage_number] = amount_to_sell
            self.total_recovered += proceeds
            self.total_proceeds += proceeds
            self.remaining_amount -= amount_to_sell
            
            logger.info(
                f"✅ بيع تدريجي نجح\n"
                f"   المستحصل: {proceeds:.4f} SOL\n"
                f"   المتبقي: {self.remaining_amount:.0f} tokens"
            )
            
            return result
        
        except Exception as e:
            logger.error(f"❌ خطأ في بيع المرحلة {stage.stage_number}: {e}")
            raise
    
    async def execute_emergency_exit(self, danger_reason: str, current_price: float) -> Dict:
        """
        ✅ خروج طارئ فوري عند إشارة خطر
        بيع كل شيء المتبقي بسرعة قصوى
        """
        logger.warning(
            f"🔴 خروج طارئ فوري!\n"
            f"   السبب: {danger_reason}\n"
            f"   المتبقي للبيع: {self.remaining_amount:.0f} tokens"
        )
        
        if self.remaining_amount <= 0:
            logger.info("لا يوجد رصيد للبيع (تم بيعه كله بالفعل)")
            return {"proceeds_sol": 0}
        
        try:
            # بيع فوري للكل المتبقي
            trade_dict = {
                "id": self.trade_id,
                "mint_address": self.mint_address,
                "amount_bought": self.entry_amount,
                "capital_invested_sol": self.entry_value_sol
            }
            result = await execute_emergency_sell(
                trade=trade_dict,
                reason=f"🔴 خروج طارئ: {danger_reason}"
            )
            
            # تحديث
            proceeds = float(result.get("proceeds_sol", 0))
            self.total_proceeds += proceeds
            self.remaining_amount = 0.0
            
            # حساب الربح/الخسارة النهائي
            pnl = self.get_current_pnl_pct(current_price)
            
            logger.warning(
                f"🔴 الخروج الطارئ اكتمل\n"
                f"   إجمالي المستحصل: {self.total_proceeds:.4f} SOL\n"
                f"   رأس المال الأصلي: {self.entry_value_sol:.4f} SOL\n"
                f"   الربح/الخسارة النهائي: {pnl:.1f}%"
            )
            
            return result
        
        except Exception as e:
            logger.error(f"❌ خطأ في الخروج الطارئ: {e}")
            raise
    
    def get_summary(self, current_price: float) -> Dict:
        """
        ✅ ملخص حالة الصفقة الحالية
        """
        pnl = self.get_current_pnl_pct(current_price)
        
        return {
            "trade_id": self.trade_id,
            "current_pnl_pct": pnl,
            "stages_executed": list(self.stages_executed.keys()),
            "total_recovered": self.total_recovered,
            "remaining_amount": self.remaining_amount,
            "total_proceeds": self.total_proceeds,
            "net_gain_loss": self.total_proceeds - self.entry_value_sol,
        }


async def get_price_safely(mint_address: str) -> Optional[float]:
    """
    ✅ جلب السعر الحالي بأمان
    """
    try:
        quote = await get_jupiter_quote(
            SOL_MINT_ADDRESS,
            mint_address,
            10_000_000,  # 0.01 SOL
            slippage_bps=500
        )
        
        return float(quote.get("outAmount", 0))
    
    except Exception as e:
        logger.error(f"خطأ في جلب السعر [{mint_address}]: {e}")
        return None
