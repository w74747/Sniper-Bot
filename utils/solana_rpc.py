"""
دوال مساعدة مشتركة للاستعلام من Solana RPC عبر Alchemy — تُستخدم من عدة وحدات
(mempool_listener, reputation, post_trade_monitor) لتجنب تكرار نفس منطق الاتصال.
"""
import logging

import aiohttp

from config.settings import ALCHEMY_RPC_URL

logger = logging.getLogger("solana_rpc")


async def rpc_call(method: str, params: list, timeout: int = 10) -> dict:
    """
    ينفّذ استدعاء JSON-RPC عام إلى Alchemy ويرجع حقل "result" من الاستجابة.
    يرمي استثناء عند فشل الاتصال أو رجوع خطأ من RPC، ليتعامل المستدعي معه بوضوح.
    """
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    async with aiohttp.ClientSession() as session:
        async with session.post(ALCHEMY_RPC_URL, json=payload, timeout=timeout) as resp:
            data = await resp.json()
            if "error" in data:
                raise RuntimeError(f"RPC error في {method}: {data['error']}")
            return data.get("result")


async def get_account_info_base64(address: str) -> str:
    """يرجع بيانات الحساب مُرمّزة base64 (raw bytes) لعنوان معيّن."""
    result = await rpc_call("getAccountInfo", [address, {"encoding": "base64"}])
    if not result or not result.get("value"):
        raise ValueError(f"لا يوجد حساب فعّال على العنوان: {address}")
    return result["value"]["data"][0]


async def get_token_largest_accounts(mint_address: str) -> list:
    """
    يرجع قائمة أكبر 20 حاملاً لعملة معيّنة (address + amount + decimals).
    ملاحظة: هذا يشمل عناوين ATA (Associated Token Accounts) الفعلية، وليس
    بالضرورة "المالك" (owner wallet) مباشرة — قد تحتاج getAccountInfo إضافية
    لكل عنوان لاستخراج owner الفعلي إذا احتجت دقة أعلى لاحقاً.
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
