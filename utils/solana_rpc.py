"""
دوال مساعدة مشتركة للاستعلام من Solana RPC — تُستخدم من عدة وحدات
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

import aiohttp

from config.settings import ALCHEMY_RPC_URL, PRIMARY_RPC_URL, RPC_ENDPOINTS

logger = logging.getLogger("solana_rpc")


class RPCCache:
    """نظام caching بسيط لـ RPC نتائج متكررة"""
    def __init__(self):
        self.cache: Dict[str, tuple] = {}
        self.hits = 0
        self.misses = 0
    
    def get(self, key: str) -> Optional[Any]:
        """احصل على قيمة من الـ cache"""
        if key not in self.cache:
            self.misses += 1
            return None
        
        value, expiry = self.cache[key]
        if datetime.now() > expiry:
            del self.cache[key]
            self.misses += 1
            return None
        
        self.hits += 1
        return value
    
    def set(self, key: str, value: Any, ttl_seconds: int = 3600):
        """احفظ قيمة في الـ cache"""
        expiry = datetime.now() + timedelta(seconds=ttl_seconds)
        self.cache[key] = (value, expiry)
    
    def get_stats(self) -> Dict[str, Any]:
        """احصل على إحصائيات الـ cache"""
        total = self.hits + self.misses
        hit_rate = (self.hits / total * 100) if total > 0 else 0
        return {
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate_pct": f"{hit_rate:.1f}%",
            "cached_items": len(self.cache)
        }
    
    def clear_expired(self):
        """حذف العناصر المنتهية الصلاحية"""
        now = datetime.now()
        expired = [k for k, (_, exp) in self.cache.items() if now > exp]
        for k in expired:
            del self.cache[k]

_rpc_cache = RPCCache()


async def rpc_call(method: str, params: list, timeout: int = 20, max_retries: int = 3, endpoint: str = None) -> dict:
    """ينفّذ استدعاء JSON-RPC عام ويرجع حقل result من الاستجابة."""
    target_url = endpoint or ALCHEMY_RPC_URL
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(target_url, json=payload, timeout=timeout) as resp:
                    if resp.status in (429, 503):
                        text = await resp.text()
                        last_error = RuntimeError(
                            f"RPC status {resp.status} في {method} (محاولة {attempt}/{max_retries}): {text[:200]}"
                        )
                        if attempt < max_retries:
                            await asyncio.sleep(2 * attempt)
                            continue
                        raise last_error

                    if resp.status != 200:
                        text = await resp.text()
                        raise RuntimeError(f"RPC status {resp.status} في {method}: {text[:300]}")

                    data = await resp.json()
                    if "error" in data:
                        raise RuntimeError(f"RPC error في {method}: {data['error']}")
                    return data.get("result")

        except asyncio.TimeoutError:
            last_error = RuntimeError(f"انتهت المهلة الزمنية ({timeout}s) أثناء استدعاء {method} (محاولة {attempt}/{max_retries})")
            if attempt < max_retries:
                await asyncio.sleep(2 * attempt)
                continue
            raise last_error
        except aiohttp.ClientError as e:
            raise RuntimeError(f"خطأ اتصال أثناء استدعاء {method}: {type(e).__name__}: {e}")

    raise last_error


async def get_transaction_via_helius(signature: str, max_retries: int = 8, retry_delay: float = 1.0) -> dict:
    """يجلب تفاصيل معاملة عبر Helius، مع إعادة محاولة عند رجوع النتيجة فارغة"""
    cache_key = f"tx:{signature}"
    cached = _rpc_cache.get(cache_key)
    if cached is not None:
        logger.debug(f"💾 من الـ cache: {signature[:16]}...")
        return cached
    
    for attempt in range(1, max_retries + 1):
        endpoint = RPC_ENDPOINTS[(attempt - 1) % len(RPC_ENDPOINTS)] if RPC_ENDPOINTS else PRIMARY_RPC_URL
        try:
            result = await rpc_call(
                "getTransaction",
                [signature, {
                    "encoding": "jsonParsed",
                    "maxSupportedTransactionVersion": 0,
                    "commitment": "confirmed",
                }],
                endpoint=endpoint,
                max_retries=1,
            )
        except RuntimeError:
            result = None

        if result:
            _rpc_cache.set(cache_key, result, 86400)
            if attempt > 1:
                logger.info(f"✅ نجح جلب {signature[:16]}... في المحاولة رقم {attempt}")
            return result
        logger.debug(f"محاولة {attempt}/{max_retries} فارغة لـ {signature[:16]}...")
        if attempt < max_retries:
            await asyncio.sleep(retry_delay)

    logger.info(f"⚠️ استُنفدت كل المحاولات ({max_retries}) بدون نتيجة لـ {signature[:16]}...")
    return None


async def _rpc_call_with_retry(method: str, params_without_config: list, extra_config: dict = None, max_retries: int = 6, retry_delay: float = 0.8) -> dict:
    """غلاف عام لإعادة المحاولة عبر Helius مع commitment=confirmed"""
    config = {"commitment": "confirmed"}
    if extra_config:
        config.update(extra_config)
    full_params = params_without_config + [config]

    last_error = None
    for attempt in range(1, max_retries + 1):
        endpoint = RPC_ENDPOINTS[(attempt - 1) % len(RPC_ENDPOINTS)] if RPC_ENDPOINTS else PRIMARY_RPC_URL
        try:
            result = await rpc_call(method, full_params, endpoint=endpoint, max_retries=1)
        except RuntimeError as e:
            last_error = e
            result = None
            logger.info(f"🔄 محاولة {attempt}/{max_retries} فشلت على {endpoint[:45]}...: {str(e)[:150]}")

        if result and (not isinstance(result, dict) or result.get("value") is not None):
            return result

        if attempt < max_retries:
            await asyncio.sleep(retry_delay)

    if last_error:
        raise last_error
    return None


async def get_account_info_base64(address: str) -> str:
    """يرجع بيانات الحساب مُرمّزة base64"""
    result = await _rpc_call_with_retry(
        "getAccountInfo", [address], extra_config={"encoding": "base64"}
    )
    if not result or not result.get("value"):
        raise ValueError(f"لا يوجد حساب فعّال على العنوان: {address}")
    return result["value"]["data"][0]


async def get_token_largest_accounts(mint_address: str, max_retries: int = 6, is_new_token: bool = True) -> list:
    """يرجع قائمة أكبر 20 حاملاً لعملة معيّنة - محسّن بـ cache + تقليل ذكي"""
    cache_key = f"token_accounts:{mint_address}"
    cache_ttl = 600 if is_new_token else 3600
    
    cached = _rpc_cache.get(cache_key)
    if cached is not None:
        return cached
    
    if not is_new_token:
        max_retries = 1
    
    result = await _rpc_call_with_retry(
        "getTokenLargestAccounts", [mint_address], max_retries=max_retries
    )
    if not result:
        return []
    
    accounts = result.get("value", [])
    _rpc_cache.set(cache_key, accounts, cache_ttl)
    
    return accounts


async def get_signatures_for_address(address: str, limit: int = 50) -> list:
    """يرجع أحدث توقيعات المعاملات لعنوان معيّن"""
    result = await rpc_call(
        "getSignaturesForAddress", [address, {"limit": limit}]
    )
    return result or []


async def get_signatures_for_address_polling(
    address: str, limit: int = 30, until: str = None, max_retries: int = 6
) -> list:
    """نسخة مخصّصة للاستقصاء الدوري (Polling)"""
    config = {"limit": limit, "commitment": "confirmed"}
    if until:
        config["until"] = until

    last_error = None
    endpoints = RPC_ENDPOINTS or [ALCHEMY_RPC_URL]

    for attempt in range(max_retries):
        endpoint = endpoints[attempt % len(endpoints)]
        try:
            result = await rpc_call(
                "getSignaturesForAddress", [address, config], endpoint=endpoint, max_retries=1
            )
            return result if result is not None else []
        except RuntimeError as e:
            last_error = e
            continue

    if last_error:
        raise last_error
    return []


async def get_wallet_sol_balance(pubkey: str) -> float:
    """يرجع رصيد SOL الفعلي الحالي للمحفظة"""
    result = await rpc_call("getBalance", [pubkey])
    lamports = result.get("value", 0) if result else 0
    return lamports / 1_000_000_000


def get_cache_stats() -> Dict[str, Any]:
    """احصل على إحصائيات استخدام الـ cache"""
    stats = _rpc_cache.get_stats()
    logger.info(f"📊 إحصائيات الـ cache RPC: {stats}")
    return stats


def clear_cache():
    """امسح الـ cache يدوياً"""
    _rpc_cache.clear_expired()
    logger.info(f"🧹 تم تنظيف الـ cache — عدد العناصر: {len(_rpc_cache.cache)}")