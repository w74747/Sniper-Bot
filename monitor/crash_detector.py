"""
🚨 كاشف الانهيارات الفوري
═══════════════════════════════════════════════════════════════════

يكتشف:
1️⃣ انخفاض سريع جداً (rug pull) - 50% في ثانية واحدة
2️⃣ انهيار السيولة - السيولة تنخفض > 50%
3️⃣ بيع ضخم - حجم بيع 10x من الطبيعي
4️⃣ تذبذب الأسعار - قفزات غريبة

النتيجة: بيع فوري قبل الخسارة الكاملة
"""

import asyncio
import logging
from typing import Optional, Dict, Tuple
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class CrashDetector:
    """كاشف الانهيارات الفوري"""
    
    def __init__(self, trade_id: str, entry_price: float, initial_liquidity: float):
        """
        Args:
            trade_id: معرّف الصفقة
            entry_price: سعر الشراء
            initial_liquidity: السيولة الأولية عند الشراء
        """
        self.trade_id = trade_id
        self.entry_price = entry_price
        self.initial_liquidity = initial_liquidity
        
        # تتبع الأسعار
        self.price_history = []  # [(timestamp, price), ...]
        self.last_check_time = datetime.now()
        
        # معايير الكشف
        self.CRASH_THRESHOLD_PCT = -50.0  # انخفاض 50% = انهيار
        self.LIQUIDITY_CRASH_PCT = -50.0  # انهيار السيولة
        self.SELL_VOLUME_MULTIPLIER = 10.0  # بيع 10x من الطبيعي
        
    async def check_crash_signals(
        self, 
        current_price: float, 
        current_liquidity: Optional[float] = None,
        sell_volume_1min: Optional[float] = None,
        buy_volume_1min: Optional[float] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        فحص شامل للانهيارات
        
        Returns:
            (is_crash, crash_reason)
        """
        
        # تسجيل السعر
        self.price_history.append((datetime.now(), current_price))
        # احتفظ بآخر 60 ثانية فقط
        cutoff = datetime.now() - timedelta(seconds=60)
        self.price_history = [(t, p) for t, p in self.price_history if t > cutoff]
        
        # 1️⃣ فحص انخفاض سريع جداً
        pnl_pct = ((current_price - self.entry_price) / self.entry_price) * 100
        if pnl_pct <= self.CRASH_THRESHOLD_PCT:
            reason = f"🚨 انهيار سريع: السعر انخفض {pnl_pct:.1f}% (الحد: {self.CRASH_THRESHOLD_PCT}%)"
            logger.warning(f"[CRASH] {self.trade_id}: {reason}")
            return True, reason
        
        # 2️⃣ فحص الانخفاض في آخر ثانية واحدة فقط
        if len(self.price_history) >= 2:
            second_ago_price = None
            current_time = datetime.now()
            
            # ابحث عن سعر من قبل ثانية تقريباً
            for timestamp, price in reversed(self.price_history):
                time_diff = (current_time - timestamp).total_seconds()
                if 0.8 <= time_diff <= 1.5:  # تقريباً ثانية واحدة
                    second_ago_price = price
                    break
            
            if second_ago_price:
                quick_drop_pct = ((current_price - second_ago_price) / second_ago_price) * 100
                if quick_drop_pct <= -40:  # انخفاض 40% في ثانية واحدة
                    reason = f"⚡ انهيار فوري: {quick_drop_pct:.1f}% في ثانية واحدة!"
                    logger.warning(f"[CRASH] {self.trade_id}: {reason}")
                    return True, reason
        
        # 3️⃣ فحص انهيار السيولة
        if current_liquidity and self.initial_liquidity:
            liquidity_change_pct = ((current_liquidity - self.initial_liquidity) / self.initial_liquidity) * 100
            if liquidity_change_pct <= self.LIQUIDITY_CRASH_PCT:
                reason = f"💧 انهيار السيولة: انخفضت {liquidity_change_pct:.1f}%"
                logger.warning(f"[CRASH] {self.trade_id}: {reason}")
                return True, reason
        
        # 4️⃣ فحص البيع الضخم
        if sell_volume_1min and buy_volume_1min:
            # متوسط البيع الطبيعي
            normal_sell_volume = (sell_volume_1min + buy_volume_1min) / 2
            
            if sell_volume_1min > (normal_sell_volume * self.SELL_VOLUME_MULTIPLIER):
                reason = f"📉 بيع ضخم: {sell_volume_1min:.0f} SOL (10x من الطبيعي)"
                logger.warning(f"[CRASH] {self.trade_id}: {reason}")
                return True, reason
        
        # لا توجد إشارات انهيار
        return False, None
    
    def get_crash_severity(self, current_price: float) -> str:
        """تحديد شدة الانهيار"""
        pnl_pct = ((current_price - self.entry_price) / self.entry_price) * 100
        
        if pnl_pct <= -75:
            return "🔴 حرج جداً"
        elif pnl_pct <= -50:
            return "🔴 حرج"
        elif pnl_pct <= -30:
            return "🟠 خطير"
        elif pnl_pct <= -15:
            return "🟡 تحذير"
        else:
            return "✅ آمن"
    
    def reset(self):
        """إعادة تعيين السجل"""
        self.price_history = []
        self.last_check_time = datetime.now()


async def monitor_for_crashes(
    trade_id: str,
    entry_price: float,
    initial_liquidity: float,
    get_current_data_fn,  # دالة لجلب السعر والسيولة
    interval_seconds: float = 0.5
) -> Optional[Tuple[bool, str]]:
    """
    مراقبة مستمرة للانهيارات
    
    Args:
        trade_id: معرّف الصفقة
        entry_price: سعر الشراء
        initial_liquidity: السيولة الأولية
        get_current_data_fn: دالة async تعيد (current_price, current_liquidity, sell_volume, buy_volume)
        interval_seconds: فترة الفحص (بالثوانٍ)
    
    Returns:
        (True, reason) إذا تم اكتشاف انهيار
    """
    
    detector = CrashDetector(trade_id, entry_price, initial_liquidity)
    
    try:
        while True:
            try:
                # جلب البيانات الحالية
                current_price, current_liquidity, sell_vol, buy_vol = await get_current_data_fn()
                
                # فحص الانهيار
                is_crash, reason = await detector.check_crash_signals(
                    current_price,
                    current_liquidity,
                    sell_vol,
                    buy_vol
                )
                
                if is_crash:
                    return (True, reason)
                
                # انتظر قبل الفحص التالي
                await asyncio.sleep(interval_seconds)
                
            except Exception as e:
                logger.error(f"[CRASH_DETECTOR] خطأ في الفحص: {e}")
                await asyncio.sleep(interval_seconds)
    
    except asyncio.CancelledError:
        logger.info(f"[CRASH_DETECTOR] {trade_id}: توقف المراقبة")
        return None
