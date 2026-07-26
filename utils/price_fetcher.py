"""
✅ ملف جديد: utils/price_fetcher.py
جلب الأسعار من مصادر متعددة مع fallback ذكي
"""
import asyncio
import logging
from typing import Optional, Dict

import aiohttp

logger = logging.getLogger("price_fetcher")


class PriceFetcher:
    """جلب الأسعار من مصادر متعددة مع fallback وcaching"""
    
    DEXSCREENER_API = "https://api.dexscreener.com/latest/dex/tokens"
    GMGN_API = "https://gmgn.ai/defi/api/v1/token_overview"
    JUPITER_PRICE_API = "https://price.jup.ag/v1/price"
    
    def __init__(self):
        self.price_cache: Dict[str, tuple] = {}  # {mint: (price, timestamp)}
        self.cache_ttl = 5  # 5 ثواني
    
    async def get_current_price(
        self,
        mint_address: str,
        timeout: int = 5
    ) -> Optional[float]:
        """
        احصل على السعر الحالي للعملة بـ SOL
        مع محاولة مصادر متعددة والعودة للـ cache عند الفشل
        """
        import time
        
        # تحقق من الـ cache
        if mint_address in self.price_cache:
            price, ts = self.price_cache[mint_address]
            if time.time() - ts < self.cache_ttl:
                return price
        
        # حاول المصادر بالترتيب
        price = await self._try_dexscreener(mint_address, timeout)
        if price:
            self._cache_price(mint_address, price)
            return price
        
        price = await self._try_jupiter(mint_address, timeout)
        if price:
            self._cache_price(mint_address, price)
            return price
        
        # إذا فشل الكل، أرجع من الـ cache القديم (حتى لو انتهت الصلاحية)
        if mint_address in self.price_cache:
            return self.price_cache[mint_address][0]
        
        logger.warning(f"فشل جلب السعر للعملة {mint_address}")
        return None
    
    async def _try_dexscreener(self, mint_address: str, timeout: int) -> Optional[float]:
        """جرب DexScreener"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.DEXSCREENER_API}/{mint_address}",
                    timeout=aiohttp.ClientTimeout(total=timeout)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("pairs") and len(data["pairs"]) > 0:
                            # خذ أكبر pool (عادة الأكثر سيولة)
                            pairs = sorted(
                                data["pairs"],
                                key=lambda p: float(p.get("liquidity", {}).get("usd", 0)),
                                reverse=True
                            )
                            price_str = pairs[0].get("priceUsd")
                            if price_str:
                                return float(price_str)
        except Exception as e:
            logger.debug(f"DexScreener error: {e}")
        
        return None
    
    async def _try_jupiter(self, mint_address: str, timeout: int) -> Optional[float]:
        """جرب Jupiter Price API"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.JUPITER_PRICE_API}",
                    params={"ids": mint_address},
                    timeout=aiohttp.ClientTimeout(total=timeout)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if "data" in data and mint_address in data["data"]:
                            price = data["data"][mint_address].get("price")
                            if price:
                                return float(price)
        except Exception as e:
            logger.debug(f"Jupiter price error: {e}")
        
        return None
    
    def _cache_price(self, mint_address: str, price: float):
        """احفظ السعر في الـ cache"""
        import time
        self.price_cache[mint_address] = (price, time.time())
    
    async def get_price_with_fallback(
        self,
        mint_address: str,
        fallback_price: Optional[float] = None
    ) -> float:
        """احصل على السعر مع قيمة backup"""
        price = await self.get_current_price(mint_address)
        if price:
            return price
        if fallback_price:
            return fallback_price
        raise ValueError(f"لا يمكن جلب سعر العملة {mint_address}")


# مثيل عام
_global_price_fetcher = PriceFetcher()


async def get_current_price(mint_address: str) -> Optional[float]:
    """دالة عام للاستخدام"""
    return await _global_price_fetcher.get_current_price(mint_address)
