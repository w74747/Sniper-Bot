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
    ✅ نظام خروج ذكي:
    1. وقف خسارة صارم: -30% (إجباري - لا يمكن تجاوزه)
    2. الهدف الأول: استرجاع رأس المال (breakeven + مصاريف)
    3. الهدف الثاني: أعلى ارتفاع ممكن (مراحل متدرجة)
    """
    
    # ⚠️ وقف خسارة صارم - يجب الخروج فوراً عند -30%
    HARD_STOP_LOSS_PCT = -30.0
    
    # الهدف الأول: استرجاع رأس المال مع مصاريف صغيرة (2%)
    BREAKEVEN_TARGET_PCT = 2.0
    
    def __init__(self, trade: Dict):
        """
        تهيئة الاستراتيجية لصفقة واحدة
        """
        self.trade_id = trade.get("id")
        self.mint_address = trade.get("mint_address")
        self.entry_price = float(trade.get("entry_price", 0))
        self.entry_value_sol = float(trade.get("capital_invested_sol", 0))
        self.entry_time = time.time()
        self.highest_price = self.entry_price  # ✅ تتبع أعلى سعر
        
        # عدد العملات المشتراة (من amount_bought أو محسوبة)
        self.entry_amount = trade.get("amount_bought", 0)
        if not self.entry_amount or self.entry_amount <= 0:
            if self.entry_price > 0 and self.entry_value_sol > 0:
                self.entry_amount = self.entry_value_sol / self.entry_price
            else:
                self.entry_amount = 0
        
        # تتبع الخروج
        self.stages_executed = {}  # {stage_number: amount_sold}
        self.total_recovered = 0.0
        self.total_proceeds = 0.0
        self.remaining_amount = self.entry_amount
        self.breakeven_hit = False  # ✅ تتبع هل وصلنا للهدف الأول
        
        logger.info(
            f"✅ نظام الخروج الذكي مفعّل (مع حماية صارمة)\n"
            f"   الصفقة #{self.trade_id}\n"
            f"   رأس مال: {self.entry_value_sol:.4f} SOL\n"
            f"   سعر الدخول: {self.entry_price:.8f}\n"
            f"   الكمية: {self.entry_amount:.0f} tokens\n"
            f"   ⚠️  وقف خسارة صارم: {self.HARD_STOP_LOSS_PCT}%\n"
            f"   🎯 الهدف الأول: +{self.BREAKEVEN_TARGET_PCT}% (استرجاع رأس المال)\n"
            f"   🚀 الهدف الثاني: أعلى ارتفاع ممكن"
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
        مع الأولوية القصوى لوقف الخسارة والهدفين
        """
        pnl = self.get_current_pnl_pct(current_price)
        
        # تحديث أعلى سعر
        if current_price > self.highest_price:
            self.highest_price = current_price
        
        # 🔴 الأولوية 1: وقف الخسارة الصارم (-30%)
        # هذا يجب أن يُنفذ فوراً لا تحت أي ظرف
        if pnl <= self.HARD_STOP_LOSS_PCT:
            logger.error(
                f"🔴🔴🔴 تنبيه وقف خسارة صارم للصفقة #{self.trade_id}!\n"
                f"   الخسارة الحالية: {pnl:.1f}% (الحد: {self.HARD_STOP_LOSS_PCT}%)\n"
                f"   سعر الدخول: {self.entry_price:.8f}\n"
                f"   السعر الحالي: {current_price:.8f}\n"
                f"   سيتم الخروج الفوري لتجنب خسارة إضافية!"
            )
            # أرجع StopLossStage مجازياً (نستخدم ExitStage الموجود)
            return ExitStage(
                stage_number=-1,  # رقم خاص لوقف الخسارة
                profit_threshold_pct=self.HARD_STOP_LOSS_PCT,
                sell_amount_pct=100.0,  # بيع الكل فوراً
                reason=f"🔴 وقف خسارة صارم: {pnl:.1f}% < {self.HARD_STOP_LOSS_PCT}%"
            )
        
        # 🎯 الأولوية 2: الهدف الأول - استرجاع رأس المال
        if not self.breakeven_hit and pnl >= self.BREAKEVEN_TARGET_PCT:
            logger.warning(
                f"🎯 الهدف الأول محقق - استرجاع رأس المال!\n"
                f"   الصفقة #{self.trade_id}\n"
                f"   الربح الحالي: {pnl:.1f}%\n"
                f"   سيتم بيع 50% لتأمين رأس المال"
            )
            self.breakeven_hit = True
            return ExitStage(
                stage_number=0,  # مرحلة خاصة للهدف الأول
                profit_threshold_pct=self.BREAKEVEN_TARGET_PCT,
                sell_amount_pct=50.0,  # بيع 50% لتأمين رأس المال
                reason=f"🎯 تأمين رأس المال: +{pnl:.1f}%"
            )
        
        # 🚀 الأولوية 3: المراحل المتدرجة للربح
        for stage in EXIT_STAGES:
            if pnl >= stage.profit_threshold_pct and stage.stage_number not in self.stages_executed:
                logger.info(
                    f"📈 مرحلة خروج متاحة للصفقة #{self.trade_id}\n"
                    f"   المرحلة: {stage.stage_number}\n"
                    f"   الربح: {pnl:.1f}% >= {stage.profit_threshold_pct}%\n"
                    f"   السبب: {stage.reason}"
                )
                return stage
        
        return None
    
    async def execute_stage_exit(self, stage: ExitStage, current_price: float) -> Dict:
        """
        ✅ تنفيذ بيع المرحلة
        مع أولوية خاصة لوقف الخسارة والهدف الأول
        """
        # حساب كمية البيع
        amount_to_sell = self.remaining_amount * (stage.sell_amount_pct / 100)
        pnl = self.get_current_pnl_pct(current_price)
        
        logger.info(
            f"📊 تنفيذ: {stage.reason}\n"
            f"   الربح/الخسارة الحالية: {pnl:.1f}%\n"
            f"   بيع: {amount_to_sell:.0f} من {self.remaining_amount:.0f} tokens"
        )
        
        try:
            trade_dict = {
                "id": self.trade_id,
                "mint_address": self.mint_address,
                "symbol": self.mint_address[:8],
                "amount_bought": self.entry_amount,
                "capital_invested_sol": self.entry_value_sol
            }
            
            # 🔴 وقف الخسارة الصارم: استخدم البيع الطارئ (أعلى انزلاق)
            if stage.stage_number == -1:
                logger.critical(f"🔴 تنفيذ وقف خسارة صارم فوراً!")
                result = await execute_emergency_sell(
                    trade=trade_dict,
                    reason=f"🔴 وقف خسارة صارم: {pnl:.1f}%"
                )
            # 🎯 الهدف الأول: بيع عادي محافظ
            elif stage.stage_number == 0:
                logger.warning(f"🎯 تنفيذ الهدف الأول - تأمين رأس المال")
                result = await execute_normal_sell(
                    trade=trade_dict,
                    reason=f"🎯 استرجاع رأس المال: +{pnl:.1f}%"
                )
            # 🚀 المراحل المتدرجة: بيع عادي
            else:
                result = await execute_normal_sell(
                    trade=trade_dict,
                    reason=f"مرحلة {stage.stage_number}: {stage.reason}"
                )
            
            # تحديث الحالة
            proceeds = float(result) if result else 0
            self.stages_executed[stage.stage_number] = amount_to_sell
            self.total_recovered += proceeds
            self.total_proceeds += proceeds
            self.remaining_amount -= amount_to_sell
            
            logger.info(
                f"✅ البيع نجح\n"
                f"   المستحصل: {proceeds:.4f} SOL\n"
                f"   المتبقي: {self.remaining_amount:.0f} tokens"
            )
            
            return result
        
        except Exception as e:
            logger.error(f"❌ خطأ في البيع: {e}")
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
                "symbol": self.mint_address[:8],  # fallback
                "amount_bought": self.entry_amount,
                "capital_invested_sol": self.entry_value_sol
            }
            result = await execute_emergency_sell(
                trade=trade_dict,
                reason=f"🔴 خروج طارئ: {danger_reason}"
            )
            
            # تحديث (result هو float من profit_loss)
            proceeds = float(result) if result else 0
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
