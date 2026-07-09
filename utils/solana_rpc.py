"""
دوال مساعدة مشتركة للاستعلام من Solana RPC عبر Alchemy — تُستخدم من عدة وحدات
(mempool_listener, reputation, post_trade_monitor) لتجنب تكرار نفس منطق الاتصال.
"""
import asyncio
import logging

import aiohttp

from config.settings import ALCHEMY_RPC_URL, HELIUS_RPC_URL

logger = logging.getLogger("solana_rpc")


async def rpc_call(method: str, params: list, timeout: int = 20, max_retries: int = 3, endpoint: str = None) -> dict:
    """
    ينفّذ استدعاء JSON-RPC عام ويرجع حقل "result" من الاستجابة.
    يستخدم Alchemy افتراضياً، أو أي رابط بديل يُمرَّر عبر endpoint (مثل Helius).
    يعيد المحاولة تلقائياً عند أخطاء 503/429 المؤقتة، بتأخير متزايد.
    """
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


async def get_transaction_via_helius(signature: str, max_retries: int = 3, retry_delay: float = 0.5) -> dict:
    """
    يجلب تفاصيل معاملة عبر Helius تحديداً (نفس المزود الذي أرسل إشعار logsSubscribe)،
    مع إعادة محاولة قصيرة إذا رجعت النتيجة فارغة (None).

    مهم جداً: نمرر commitment="confirmed" صراحة ليطابق مستوى التأكيد الذي
    اشتركنا به في logsSubscribe. بدون هذا، getTransaction يستخدم الافتراضي
    "finalized" (أعلى مستوى تأكيد)، وهو أبطأ بعدة ثوانٍ من "confirmed" —
    وهذا هو السبب الفعلي وراء رجوع النتيجة فارغة (None) في كل المحاولات
    السابقة، وليس فارق فهرسة بين المزودين كما افترضنا سابقاً.
    """
    for attempt in range(1, max_retries + 1):
        result = await rpc_call(
            "getTransaction",
            [signature, {
                "encoding": "json",
                "maxSupportedTransactionVersion": 0,
                "commitment": "confirmed",
            }],
            endpoint=HELIUS_RPC_URL,
        )
        if result:
            return result
        if attempt < max_retries:
            await asyncio.sleep(retry_delay)
    return None


async def get_account_info_base64(address: str) -> str:
    """يرجع بيانات الحساب مُرمّزة base64 (raw bytes) لعنوان معيّن."""
    result = await rpc_call("getAccountInfo", [address, {"encoding": "base64"}])
    if not result or not result.get("value"):
        raise ValueError(f"لا يوجد حساب فعّال على العنوان: {address}")
    return result["value"]["data"][0]


async def get_token_largest_accounts(mint_address: str) -> list:
    """
    يرجع قائمة أكبر 20 حاملاً لعملة معيّنة (address + amount + decimals).
    """
    result = await rpc_call("getTokenLargestAccounts", [mint_address])
    if not result:
        return []
    return result.get("value", [])


async def get_signatures_for_address(address: str, limit: int = 50) -> list:
    """يرجع أحدث توقيعات المعاملات لعنوان معيّن (مفيد لسجل محفظة المطور)."""
    result = await rpc_call(
        "getSignaturesForAddress", [address, {"limit": limit}]
    )
    return result or []
