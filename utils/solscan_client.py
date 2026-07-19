"""
تكامل Solscan Pro API — مصدر بديل ومستقل تماماً لفحص توزيع حاملي العملة،
بحصة منفصلة تماماً عن Helius (10 مليون CU شهرياً مجاناً)، ويُخفّف الضغط
عن Helius في نقطة الفشل الأكثر تكراراً (فحص النمو العضوي وتوزيع الحيازة).

ميزة إضافية حقيقية على RPC: getTokenLargestAccounts (RPC) يُرجع 20 حساباً
كحد أقصى دائماً (قيد من Solana نفسها) — بينما Solscan يُرجع "total" (العدد
الحقيقي الكامل لكل الحاملين)، مما يُحسّن دقة فحص النمو العضوي بشكل جوهري
(لم يعد مُقيَّداً بحد أقصى ~20 صناعياً).
"""
import logging

import aiohttp

from config.settings import SOLSCAN_API_KEY, SOLSCAN_API_BASE

logger = logging.getLogger("solscan_client")


async def get_token_holders_solscan(mint_address: str, limit: int = 20) -> dict:
    """
    يستعلم عن توزيع حاملي عملة عبر Solscan. يرجع قاموساً:
    {"total_holders": العدد الحقيقي الكامل, "items": [{"address", "percentage"}]}

    عند أي فشل (لا مفتاح، 429، خطأ شبكة): يرجع {"total_holders": None, "items": []}
    — fail-open كامل، الكود المستدعي يتراجع تلقائياً لمصدر RPC الاحتياطي.
    """
    empty_result = {"total_holders": None, "items": []}

    if not SOLSCAN_API_KEY:
        # تشخيص مؤقت (INFO بدل الصمت التام): يجب أن نرى بوضوح إن كان المفتاح
        # غائباً فعلاً من متغيرات البيئة — بدل استنتاج ذلك من صفر استخدام فقط.
        logger.info("⚠️ SOLSCAN_API_KEY غير موجود في متغيرات البيئة — Solscan معطَّل، التراجع لـRPC دائماً")
        return empty_result

    headers = {"token": SOLSCAN_API_KEY}
    params = {"address": mint_address, "page": 1, "page_size": limit}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{SOLSCAN_API_BASE}/token/holders", params=params, headers=headers, timeout=10
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    # تشخيص مؤقت (INFO بدل debug المخفي): نحتاج رؤية السبب
                    # الحقيقي (401 مفتاح خاطئ؟ 403 ممنوع؟ 429 حد معدل؟) —
                    # نفس الدرس المستفاد سابقاً مع تشخيص كل مزود آخر.
                    logger.info(f"📉 Solscan رجع status {resp.status} لـ {mint_address}: {text[:200]}")
                    return empty_result
                data = await resp.json()
    except Exception as e:
        logger.info(f"📉 تعذّر الاتصال بـSolscan لـ {mint_address}: {type(e).__name__}: {e}")
        return empty_result

    if not data.get("success"):
        logger.info(f"📉 Solscan رجع success=false لـ {mint_address}: {str(data)[:200]}")
        return empty_result

    payload = data.get("data") or {}
    items = payload.get("items", [])

    logger.info(f"✅ Solscan نجح لـ {mint_address}: {payload.get('total')} حامل إجمالي")

    return {
        "total_holders": payload.get("total"),
        "items": [
            {
                "address": item.get("owner") or item.get("address", ""),
                "percentage": float(item.get("percentage", 0) or 0),
            }
            for item in items
        ],
    }
