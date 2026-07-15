"""
"رأي ثانٍ مستقل" عبر Tatum — تأكيد أخير على أهم فحص أمان واحد (mint
authority معطّل فعلاً) مباشرة قبل تنفيذ الشراء الحقيقي، باستخدام مزود
مستقل تماماً عن كل مزودي التناوب الرئيسيين (Chainstack, Helius, GetBlock,
Ankr, Solana العام) — لتفادي أي خلل مشترك بينهم (تخزين مؤقت قديم، بق
برمجي في مزود معيّن) يُفوّت في الفحص الأول.

فلسفة التصميم: هذا فحص "إضافي مُطمْئِن"، وليس بوابة أمان حتمية أساسية —
إن تعذّر الوصول لـ Tatum نفسه (خطأ شبكة، حصة منتهية)، لا نمنع الشراء
بسببه (fail-open)، لأن الفحص الأساسي الحقيقي (GoPlus + محاكاة البيع) تم
بالفعل. نمنع الشراء فقط إذا اكتشف Tatum تحديداً دليلاً واضحاً على مشكلة
حقيقية (mint authority أصبح فعّالاً مجدداً بشكل ما).
"""
import base64
import logging
import struct

import aiohttp

from config.settings import TATUM_API_KEY, TATUM_SOLANA_RPC_URL

logger = logging.getLogger("tatum_check")


async def verify_mint_authority_disabled(mint_address: str) -> tuple[bool, str]:
    """
    يتحقق مرة أخيرة، عبر مزود مستقل تماماً (Tatum)، أن mint_authority لا
    يزال معطّلاً فعلاً الآن. يرجع (safe_to_proceed: bool, reason: str).

    fail-open: أي عائق تقني في الوصول لـ Tatum نفسه (لا مفتاح، خطأ شبكة،
    حصة منتهية) لا يمنع الشراء — فقط نُسجّل تحذيراً ونُكمل، لأن هذا فحص
    إضافي وليس الفحص الأساسي الوحيد.
    """
    if not TATUM_API_KEY:
        return True, "Tatum غير مُفعَّل (لا مفتاح) — تخطّي التأكيد الإضافي بأمان"

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getAccountInfo",
        "params": [mint_address, {"encoding": "base64"}],
    }
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "x-api-key": TATUM_API_KEY,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                TATUM_SOLANA_RPC_URL, json=payload, headers=headers, timeout=8
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.warning(f"⚠️ Tatum رجع status {resp.status} — تخطّي التأكيد (fail-open): {text[:150]}")
                    return True, f"تعذّر التحقق عبر Tatum (status {resp.status}) — تم التخطي بأمان"
                data = await resp.json()
    except Exception as e:
        logger.warning(f"⚠️ فشل الاتصال بـ Tatum — تخطّي التأكيد (fail-open): {e}")
        return True, f"تعذّر الوصول لـ Tatum: {e} — تم التخطي بأمان"

    if "error" in data:
        logger.warning(f"⚠️ Tatum رجع خطأ منطقي — تخطّي التأكيد (fail-open): {data['error']}")
        return True, f"خطأ من Tatum: {data['error']} — تم التخطي بأمان"

    value = (data.get("result") or {}).get("value")
    if not value:
        logger.warning(f"⚠️ Tatum لم يجد الحساب {mint_address} — تخطّي التأكيد (fail-open)")
        return True, "لم يُعثر على الحساب عبر Tatum بعد — تم التخطي بأمان"

    try:
        raw = base64.b64decode(value["data"][0])
        mint_authority_tag = struct.unpack_from("<I", raw, 0)[0]
        mint_authority_active = mint_authority_tag == 1
    except Exception as e:
        logger.warning(f"⚠️ فشل فك تشفير بيانات Tatum — تخطّي التأكيد (fail-open): {e}")
        return True, f"فشل تحليل بيانات Tatum: {e} — تم التخطي بأمان"

    if mint_authority_active:
        return False, (
            "🚨 تحذير من Tatum (مصدر مستقل): mint_authority ظهر فعّالاً الآن، "
            "رغم أن الفحص الأساسي وجده معطّلاً — إلغاء الشراء احتياطاً"
        )

    return True, "✅ تأكيد Tatum المستقل: mint_authority لا يزال معطّلاً فعلاً"
