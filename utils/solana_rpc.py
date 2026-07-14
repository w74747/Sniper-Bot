"""
نظام RPC ذكي مع Smart Failover - لا يتوقف عند استنزاف حصة واحد
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

import aiohttp

from config.settings import ALCHEMY_RPC_URL, PRIMARY_RPC_URL, RPC_ENDPOINTS, SECONDARY_RPC_ENDPOINTS

logger = logging.getLogger("solana_rpc")


class RPCCache:
    """نظام caching بسيط لـ RPC نتائج متكررة"""
    def __init__(self):
        self.cache: Dict[str, tuple] = {}
        self.hits = 0
        self.misses = 0
    
    def get(self, key: str) -> Optional[Any]:
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
        expiry = datetime.now() + timedelta(seconds=ttl_seconds)
        self.cache[key] = (value, expiry)


_rpc_cache = RPCCache()


# ✨ جديد: تتبع حالة كل مزود RPC
class RPCEndpointTracker:
    """يتتبع حالة كل مزود RPC ويتخطى المستنزفة تلقائياً"""
    def __init__(self):
        self.endpoint_status: Dict[str, Dict] = {}
        for ep in RPC_ENDPOINTS:
            self.endpoint_status[ep] = {
                "status": "working",  # working, quota_exhausted, timeout
                "failures": 0,
                "last_failure": None,
                "recovery_time": datetime.now() + timedelta(hours=1)  # أعد المحاولة بعد ساعة
            }
    
    def mark_failure(self, endpoint: str, error_type: str):
        """وسّم مزود بالفشل"""
        if endpoint not in self.endpoint_status:
            return
        
        status = self.endpoint_status[endpoint]
        status["failures"] += 1
        status["last_failure"] = datetime.now()
        
        if "quota" in error_type.lower() or "429" in error_type or "403" in error_type:
            status["status"] = "quota_exhausted"
            status["recovery_time"] = datetime.now() + timedelta(hours=24)  # أعد بعد 24 ساعة
            logger.warning(f"🚫 {endpoint[:40]}... - استُنزفت الحصة!")
        elif "timeout" in error_type.lower():
            status["status"] = "timeout"
            status["recovery_time"] = datetime.now() + timedelta(minutes=5)
            logger.warning(f"⏱️ {endpoint[:40]}... - timeout!")
        else:
            logger.warning(f"⚠️ {endpoint[:40]}... - فشل: {error_type[:50]}")
    
    def get_working_endpoints(self) -> list:
        """احصل على المزودات التي تعمل فقط"""
        now = datetime.now()
        working = []
        
        for ep, status in self.endpoint_status.items():
            if status["status"] == "working":
                working.append(ep)
            elif now > status["recovery_time"]:
                # حاول إعادة المزود
                status["status"] = "working"
                status["failures"] = 0
                working.append(ep)
                logger.info(f"♻️ إعادة محاولة {ep[:40]}...")
        
        return working if working else RPC_ENDPOINTS  # في الحالات الطارئة استخدم الكل


_tracker = RPCEndpointTracker()


async def rpc_call(method: str, params: list, timeout: int = 20, max_retries: int = 3, endpoint: str = None) -> dict:
    """ينفّذ استدعاء JSON-RPC مع Smart Failover"""
    
    # إذا لم يُحدد مزود، استخدم الأول الذي يعمل
    if endpoint is None:
        working = _tracker.get_working_endpoints()
        if not working:
            raise RuntimeError("❌ جميع مزودات RPC استُنزفت! لا يمكن المتابعة")
        endpoint = working[0]
    
    target_url = endpoint
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(target_url, json=payload, timeout=timeout) as resp:
                    if resp.status == 429:
                        _tracker.mark_failure(endpoint, "429 - Quota exhausted")
                        raise RuntimeError(f"RPC status 429 - الحصة استُنزفت على {endpoint[:40]}...")
                    
                    if resp.status == 403:
                        _tracker.mark_failure(endpoint, "403 - Quota exhausted")
                        raise RuntimeError(f"RPC status 403 - الحصة استُنزفت على {endpoint[:40]}...")
                    
                    if resp.status == 503:
                        text = await resp.text()
                        last_error = RuntimeError(f"RPC status 503 (محاولة {attempt}/{max_retries}): {text[:200]}")
                        if attempt < max_retries:
                            await asyncio.sleep(2 * attempt)
                            continue
                        raise last_error

                    if resp.status != 200:
                        text = await resp.text()
                        raise RuntimeError(f"RPC status {resp.status}: {text[:300]}")

                    data = await resp.json()
                    if "error" in data:
                        raise RuntimeError(f"RPC error: {data['error']}")
                    
                    # نجح! وسّم المزود كـ working
                    _tracker.endpoint_status[endpoint]["status"] = "working"
                    return data.get("result")

        except asyncio.TimeoutError:
            _tracker.mark_failure(endpoint, "timeout")
            last_error = RuntimeError(f"Timeout ({timeout}s) على {endpoint[:40]}...")
            if attempt < max_retries:
                await asyncio.sleep(2 * attempt)
                continue
            raise last_error
        except aiohttp.ClientError as e:
            _tracker.mark_failure(endpoint, str(type(e).__name__))
            raise RuntimeError(f"Connection error: {type(e).__name__}: {e}")

    raise last_error


async def get_transaction_via_helius(signature: str, max_retries: int = 8, retry_delay: float = 1.0) -> dict:
    """جلب معاملة مع Smart Failover"""
    cache_key = f"tx:{signature}"
    cached = _rpc_cache.get(cache_key)
    if cached is not None:
        logger.debug(f"💾 من الـ cache: {signature[:16]}...")
        return cached
    
    working = _tracker.get_working_endpoints()
    if not working:
        logger.warning(f"❌ لا توجد مزودات متاحة لـ {signature[:16]}...")
        return None

    for attempt in range(1, max_retries + 1):
        endpoint = working[(attempt - 1) % len(working)]
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
                logger.info(f"✅ نجح جلب {signature[:16]}... في المحاولة {attempt}")
            return result
        
        logger.debug(f"محاولة {attempt}/{max_retries} فارغة على {endpoint[:40]}...")
        if attempt < max_retries:
            await asyncio.sleep(retry_delay)

    logger.warning(f"⚠️ استُنفدت المحاولات لـ {signature[:16]}...")
    return None


async def _rpc_call_with_retry(method: str, params_without_config: list, extra_config: dict = None, max_retries: int = 6, retry_delay: float = 0.8) -> dict:
    """استدعاء مع إعادة محاولة عبر مزودات متعددة"""
    config = {"commitment": "confirmed"}
    if extra_config:
        config.update(extra_config)
    full_params = params_without_config + [config]

    working = _tracker.get_working_endpoints()
    if not working:
        raise RuntimeError("❌ لا توجد مزودات RPC متاحة!")

    last_error = None
    for attempt in range(1, max_retries + 1):
        endpoint = working[(attempt - 1) % len(working)]
        try:
            result = await rpc_call(method, full_params, endpoint=endpoint, max_retries=1)
        except RuntimeError as e:
            last_error = e
            result = None
            logger.debug(f"🔄 محاولة {attempt}/{max_retries} فشلت على {endpoint[:40]}...")

        if result and (not isinstance(result, dict) or result.get("value") is not None):
            return result

        if attempt < max_retries:
            await asyncio.sleep(retry_delay)

    if last_error:
        raise last_error
    return None


async def get_account_info_base64(address: str) -> str:
    """جلب بيانات حساب"""
    result = await _rpc_call_with_retry(
        "getAccountInfo", [address], extra_config={"encoding": "base64"}
    )
    if not result or not result.get("value"):
        raise ValueError(f"لا يوجد حساب على: {address}")
    return result["value"]["data"][0]


async def get_token_largest_accounts(mint_address: str, max_retries: int = 6, is_new_token: bool = True) -> list:
    """جلب أكبر 20 حامل - مع cache + Smart Failover"""
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
    """جلب توقيعات"""
    result = await rpc_call(
        "getSignaturesForAddress", [address, {"limit": limit}]
    )
    return result or []


async def get_signatures_for_address_polling(address: str, limit: int = 30, until: str = None, max_retries: int = 6) -> list:
    """Polling مع Smart Failover"""
    config = {"limit": limit, "commitment": "confirmed"}
    if until:
        config["until"] = until

    working = _tracker.get_working_endpoints()
    if not working:
        logger.warning("❌ لا توجد مزودات متاحة للـ polling")
        return []

    last_error = None
    for attempt in range(max_retries):
        endpoint = working[attempt % len(working)]
        try:
            result = await rpc_call(
                "getSignaturesForAddress", [address, config], endpoint=endpoint, max_retries=1
            )
            return result if result is not None else []
        except RuntimeError as e:
            last_error = e
            continue

    if last_error:
        logger.warning(f"⚠️ فشل polling: {str(last_error)[:100]}")
    return []


async def get_wallet_sol_balance(pubkey: str) -> float:
    """جلب رصيد المحفظة"""
    result = await rpc_call("getBalance", [pubkey])
    lamports = result.get("value", 0) if result else 0
    return lamports / 1_000_000_000


def get_cache_stats() -> Dict[str, Any]:
    """إحصائيات الـ cache"""
    stats = _rpc_cache.get_stats()
    logger.info(f"📊 إحصائيات الـ cache: {stats}")
    return stats


def get_rpc_health() -> Dict[str, Any]:
    """حالة مزودات RPC"""
    health = {}
    for ep, status in _tracker.endpoint_status.items():
        health[ep] = {
            "status": status["status"],
            "failures": status["failures"],
            "recovery_time": status["recovery_time"].isoformat()
        }
    logger.info(f"🏥 حالة مزودات RPC: {health}")
    return health


def clear_cache():
    """مسح الـ cache"""
    _rpc_cache.clear_expired()
