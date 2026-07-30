"""
💰 استراتيجية الخروج المحسّنة
═══════════════════════════════════════════════════════════════════

المميزات:
1️⃣ بيع متعدد الدفعات (20% + 30% + 50%)
2️⃣ وقف خسارة صارم: -30%
3️⃣ أهداف ربح: +2% استرجاع و +50% + أعلى
4️⃣ Retry فوري للبيع الفاشل
5️⃣ حماية من قسمة الصفر
"""

import asyncio
import logging
from typing import Optional, Dict, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class ExitStage(Enum):
    """مراحل الخروج من الصفقة"""
    HARD_STOP_LOSS = "hard_stop_loss"  # -30%
    BREAKEVEN = "breakeven"  # استرجاع رأس المال (+2%)
    HALF_PROFIT = "half_profit"  # نصف الربح (+50%)
    FULL_PROFIT = "full_profit"  # كل الربح


@dataclass
class ExitConfig:
    """إعدادات الخروج"""
    hard_stop_loss_pct: float = -30.0  # وقف الخسارة
    breakeven_target_pct: float = 2.0  # استرجاع رأس المال
    half_profit_target_pct: float = 50.0  # نصف الربح
    full_profit_target_pct: float = 200.0  # كل الربح
    
    # حدود الانزلاق (في الأسوأ حالة)
    max_slippage_pct: float = 10.0


class SmartExitStrategy:
    """استراتيجية خروج ذكية مع بيع متعدد الدفعات"""
    
    def __init__(self, trade: Dict, config: Optional[ExitConfig] = None):
        """
        Args:
            trade: معلومات الصفقة
            config: إعدادات الخروج
        """
        self.trade = trade
        self.trade_id = trade.get("id")
        self.mint_address = trade.get("mint_address")
        self.entry_price = float(trade.get("entry_price", 0))
        self.amount_bought = float(trade.get("amount_bought", 0))
        self.capital_invested = float(trade.get("capital_invested_sol", 0))
        
        self.config = config or ExitConfig()
        
        # تتبع المبيعات
        self.amount_sold = 0.0
        self.proceeds_sol = 0.0
        self.exit_stages_executed = set()
        
        # حماية من قسمة الصفر
        if self.entry_price <= 0 or self.entry_price > 1000:
            logger.error(f"[EXIT] {self.trade_id}: سعر دخول غير صحيح: {self.entry_price}")
            self.entry_price = 0.0001
    
    def get_current_pnl_pct(self, current_price: float) -> float:
        """حساب الربح/الخسارة الحالية"""
        # حماية من قسمة الصفر والقيم السالبة
        if not self.entry_price or self.entry_price <= 0:
            return -100.0
        if not current_price or current_price <= 0:
            return -100.0
        
        try:
            pnl = ((current_price - self.entry_price) / self.entry_price) * 100
            
            # تحقق من NaN أو infinity
            if pnl != pnl or pnl > 1e6 or pnl < -1e6:
                return -100.0
            
            return pnl
        except:
            return -100.0
    
    def get_stage_to_execute(self, current_price: float) -> Optional[ExitStage]:
        """تحديد مرحلة الخروج التالية"""
        pnl_pct = self.get_current_pnl_pct(current_price)
        
        # وقف الخسارة الصارم (أولوية عالية جداً)
        if pnl_pct <= self.config.hard_stop_loss_pct:
            if ExitStage.HARD_STOP_LOSS not in self.exit_stages_executed:
                return ExitStage.HARD_STOP_LOSS
        
        # استرجاع رأس المال
        if pnl_pct >= self.config.breakeven_target_pct:
            if ExitStage.BREAKEVEN not in self.exit_stages_executed:
                return ExitStage.BREAKEVEN
        
        # نصف الربح
        if pnl_pct >= self.config.half_profit_target_pct:
            if ExitStage.HALF_PROFIT not in self.exit_stages_executed:
                return ExitStage.HALF_PROFIT
        
        # كل الربح (أعلى من 200%)
        if pnl_pct >= self.config.full_profit_target_pct:
            if ExitStage.FULL_PROFIT not in self.exit_stages_executed:
                return ExitStage.FULL_PROFIT
        
        return None
    
    def get_batch_amounts(self, stage: ExitStage) -> Dict:
        """احسب كمية البيع لكل مرحلة"""
        remaining = self.amount_bought - self.amount_sold
        
        if remaining <= 0:
            return {"total": 0, "batches": []}
        
        batches = []
        
        if stage == ExitStage.HARD_STOP_LOSS:
            # بيع سريع: 50% + 50%
            batches = [remaining * 0.5, remaining * 0.5]
        
        elif stage == ExitStage.BREAKEVEN:
            # بيع متحفظ: 20% + 30% + 50%
            batches = [
                remaining * 0.2,
                remaining * 0.3,
                remaining * 0.5
            ]
        
        elif stage == ExitStage.HALF_PROFIT:
            # بيع متوازن: 50% + 50%
            batches = [remaining * 0.5, remaining * 0.5]
        
        elif stage == ExitStage.FULL_PROFIT:
            # بيع كل شيء
            batches = [remaining]
        
        return {
            "total": remaining,
            "batches": batches,
            "stage": stage.value
        }
    
    async def execute_stage_exit(
        self,
        stage: ExitStage,
        current_price: float,
        sell_fn
    ) -> Dict:
        """
        تنفيذ مرحلة خروج واحدة مع بيع متعدد الدفعات
        """
        
        batch_info = self.get_batch_amounts(stage)
        total_amount = batch_info["total"]
        batches = batch_info["batches"]
        
        if not batches or total_amount <= 0:
            return {"success": False, "proceeds": 0, "batches": 0}
        
        logger.info(f"[EXIT] {self.trade_id}: بدء بيع المرحلة {stage.value}")
        
        total_proceeds = 0
        successful_batches = 0
        
        for i, batch_amount in enumerate(batches):
            if batch_amount <= 0:
                continue
            
            # محاولات متعددة للبيع
            for attempt in range(1, 5):
                try:
                    # حسب الانزلاق المتوقع
                    expected_slippage = self.config.max_slippage_pct * (attempt - 1) / 100
                    adjusted_price = current_price * (1 - expected_slippage)
                    
                    # نفذ البيع
                    result = await sell_fn(
                        amount=batch_amount,
                        min_amount_out=adjusted_price * batch_amount
                    )
                    
                    if result and result > 0:
                        total_proceeds += result
                        successful_batches += 1
                        self.amount_sold += batch_amount
                        
                        logger.info(
                            f"[EXIT] {self.trade_id}: "
                            f"الدفعة {i+1}/{len(batches)} بيعت بنجاح"
                        )
                        break
                    
                    elif attempt < 4:
                        # انتظر قليلاً قبل المحاولة التالية
                        await asyncio.sleep(0.1 * attempt)
                
                except Exception as e:
                    logger.warning(
                        f"[EXIT] {self.trade_id}: "
                        f"محاولة {attempt}/4 فشلت"
                    )
                    
                    if attempt < 4:
                        await asyncio.sleep(0.1 * attempt)
                    continue
            
            # انتظر بين الدفعات
            if i < len(batches) - 1:
                await asyncio.sleep(0.5)
        
        self.exit_stages_executed.add(stage)
        self.proceeds_sol = total_proceeds
        
        success = successful_batches > 0
        
        return {
            "success": success,
            "proceeds": total_proceeds,
            "batches": successful_batches
        }
    
    async def execute_emergency_exit(
        self,
        danger_reason: str,
        current_price: float,
        sell_fn
    ) -> Dict:
        """بيع فوري في حالة الطوارئ"""
        logger.critical(f"[EXIT] {self.trade_id}: بيع طوارئ! السبب: {danger_reason}")
        
        # بيع كل شيء بسرعة
        remaining = self.amount_bought - self.amount_sold
        
        for attempt in range(1, 6):
            try:
                # قبول أي سعر في الطوارئ
                slippage = min(self.config.max_slippage_pct * attempt / 100, 0.5)
                min_out = current_price * remaining * (1 - slippage)
                
                result = await sell_fn(amount=remaining, min_amount_out=min_out)
                
                if result and result > 0:
                    self.proceeds_sol = result
                    self.amount_sold = self.amount_bought
                    logger.critical(
                        f"[EXIT] {self.trade_id}: بيع الطوارئ نجح!"
                    )
                    return {"success": True, "proceeds": result}
                
                await asyncio.sleep(0.2)
            
            except Exception as e:
                logger.error(f"[EXIT] {self.trade_id}: محاولة {attempt} فشلت")
                await asyncio.sleep(0.2)
        
        logger.critical(f"[EXIT] {self.trade_id}: فشل بيع الطوارئ!")
        return {"success": False, "proceeds": 0}
    
    def calculate_final_pnl(self) -> float:
        """حساب الربح/الخسارة النهائية"""
        if self.capital_invested <= 0:
            return 0
        
        pnl_sol = self.proceeds_sol - self.capital_invested
        return (pnl_sol / self.capital_invested) * 100 if self.capital_invested > 0 else 0
