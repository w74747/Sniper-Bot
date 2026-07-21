"""
تكامل RugCheck.xyz — خدمة مجانية بالكامل مبنية خصيصاً لتقييم مخاطر عملات
meme على Solana (بخلاف GoPlus العامة متعددة السلاسل). تكتشف تحديداً:

1. المطلعين (Insiders): محافظ مرتبطة بالمطوّر تشتري بأسماء مختلفة لإخفاء
   تركّز الحيازة الحقيقي (يمر من فلتر "تركّز الحيازة" العادي لأنه موزَّع
   شكلياً على عدة عناوين، لكنها فعلياً نفس الجهة).
2. المحافظ المُجمَّعة (Bundlers): عدة محافظ أُنشئت واشترت في نفس اللحظة —
   دليل قوي على تنسيق مسبق (نفس فكرة "wallet clustering" التي وصفتها
   إحدى الاستشارات الثلاث التي راجعناها، لكن بتكلفة صفرية هنا).

مجاني تماماً، لا يتطلب مفتاحاً للقراءة الأساسية (10 طلبات/دقيقة)، أو
60/دقيقة بمفتاح مجاني بسيط. يُستخدَم كطبقة أمان إضافية اختيارية —
fail-open كامل، لا يُوقف الفحص الأساسي (GoPlus + on-chain) إن فشل.
"""
import logging

import aiohttp

from config.settings import RUGCHECK_API_KEY

logger = logging.getLogger("rugcheck_client")

RUGCHECK_API_BASE = "https://api.rugcheck.xyz/v1"


async def get_token_report(mint_address: str) -> dict:
    """
    يستعلم عن تقرير RugCheck الكامل لعملة. يرجع قاموساً موحَّداً:
    {
        "available": bool,           # هل نجح الاستعلام فعلياً؟
        "score_normalised": float,   # 0-100، الأعلى = الأخطر
        "rugged": bool,              # هل صُنِّفت كـrug pull مؤكَّد بالفعل؟
        "insiders_detected": int,    # عدد المحافظ المُصنَّفة كـ"مطلعين" مرتبطين
        "reason": str,
    }
    عند أي فشل (429/شبكة/إلخ): available=False — fail-open كامل، الفحص
    الأساسي (GoPlus + on-chain) يبقى المرجع الوحيد في هذه الحالة.
    """
    empty_result = {
        "available": False, "score_normalised": 0.0,
        "rugged": False, "insiders_detected": 0, "reason": "",
    }

    headers = {}
    if RUGCHECK_API_KEY:
        headers["X-API-KEY"] = RUGCHECK_API_KEY

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{RUGCHECK_API_BASE}/tokens/{mint_address}/report",
                headers=headers, timeout=10,
            ) as resp:
                if resp.status == 429:
                    logger.debug(f"RugCheck: تجاوز حد المعدل لـ {mint_address} (fail-open)")
                    return empty_result
                if resp.status != 200:
                    logger.debug(f"RugCheck رجع status {resp.status} لـ {mint_address}")
                    return empty_result
                data = await resp.json()
    except Exception as e:
        logger.debug(f"تعذّر الاتصال بـRugCheck لـ {mint_address}: {e}")
        return empty_result

    score_normalised = float(data.get("score_normalised", 0) or 0)
    rugged = bool(data.get("rugged", False))
    insider_graph = data.get("graphInsidersDetected") or 0

    return {
        "available": True,
        "score_normalised": score_normalised,
        "rugged": rugged,
        "insiders_detected": int(insider_graph),
        "reason": f"RugCheck score={score_normalised:.0f}/100، rugged={rugged}، insiders={insider_graph}",
    }
