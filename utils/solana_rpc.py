"""
دوال مساعدة مشتركة للاستعلام من Solana RPC عبر Alchemy — تُستخدم من عدة وحدات
(mempool_listener, reputation, post_trade_monitor) لتجنب تكرار نفس منطق الاتصال.
"""
import asyncio
import logging

import aiohttp

from config.settings import ALCHEMY_RPC_URL, PRIMARY_RPC_URL, RPC_ENDPOINTS

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
                            await asyncio.sleep(2 * attempt)  # تأخير متزايد: 2s, 4s, 6s...
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
    """
    يجلب تفاصيل معاملة عبر Helius، مع إعادة محاولة عند رجوع النتيجة فارغة (None).

    ملاحظة: بعد تجربة عدة قيم، اتضح أن الفارق الزمني بين لحظة إشعار logsSubscribe
    ولحظة توفر تفاصيل المعاملة عبر getTransaction قد يصل لعدة ثوانٍ فعلياً، حتى
    مع commitment=confirmed. لذلك نزيد عدد المحاولات إلى 8 بتأخير ثانية واحدة بينها
    (حتى 8 ثوانٍ انتظار كحد أقصى)، مع تسجيل كل محاولة فاشلة لمعرفة عدد المحاولات
    الفعلي المطلوب حتى تنجح، إن نجحت.
    """
    for attempt in range(1, max_retries + 1):
        # تناوب بين كل المزودين المتاحين (Chainstack/Helius/Ankr) بدل الاصطدام
        # بنفس المزود المرفوض مراراً — كل محاولة تجرّب المزود التالي في الدور.
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
                max_retries=1,  # حاسم: rpc_call لا يجب أن تُعيد المحاولة داخلياً أيضاً —
                                # هذه الدالة نفسها هي طبقة إعادة المحاولة الوحيدة (8 محاولات)
            )
        except RuntimeError:
            result = None

        if result:
            if attempt > 1:
                logger.info(f"✅ نجح جلب {signature[:16]}... في المحاولة رقم {attempt}")
            return result
        logger.debug(f"محاولة {attempt}/{max_retries} فارغة لـ {signature[:16]}...")
        if attempt < max_retries:
            await asyncio.sleep(retry_delay)

    logger.info(f"⚠️ استُنفدت كل المحاولات ({max_retries}) بدون نتيجة لـ {signature[:16]}...")
    return None


async def _rpc_call_with_retry(method: str, params_without_config: list, extra_config: dict = None, max_retries: int = 6, retry_delay: float = 0.8) -> dict:
    """
    غلاف عام لإعادة المحاولة عبر Helius مع commitment=confirmed، لأي استعلام
    قد يُطلب فوراً بعد اكتشاف حساب/عملة جديدة جداً لم تُفهرَس بعد. هذا نفس
    الحل الذي طبّقناه على get_transaction_via_helius، مُعمَّماً هنا ليشمل
    getAccountInfo وgetTokenLargestAccounts أيضاً — فشل هذين الاستعلامين
    بسبب نفس فارق الفهرسة كان يُسقط 100% من العملات المستخرجة حديثاً.
    """
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

    # كل المحاولات فشلت على كل المزودين المتاحين — نرمي الخطأ الحقيقي الأخير
    # بدل استدعاء إضافي زائد على مزود ثابت (كان هذا يُخفي السبب الحقيقي سابقاً)
    if last_error:
        raise last_error
    return None


async def get_account_info_base64(address: str) -> str:
    """يرجع بيانات الحساب مُرمّزة base64 (raw bytes) لعنوان معيّن، مع إعادة محاولة عبر Helius."""
    result = await _rpc_call_with_retry(
        "getAccountInfo", [address], extra_config={"encoding": "base64"}
    )
    if not result or not result.get("value"):
        raise ValueError(f"لا يوجد حساب فعّال على العنوان: {address}")
    return result["value"]["data"][0]


async def get_token_largest_accounts(mint_address: str, max_retries: int = 6) -> list:
    """
    يرجع قائمة أكبر 20 حاملاً لعملة معيّنة (address + amount + decimals)،
    مع إعادة محاولة عبر Helius لنفس سبب فارق الفهرسة.

    ملاحظة كفاءة مهمة: القيمة الافتراضية (6 محاولات) مصمَّمة لعملات حديثة
    جداً (لحظة الاكتشاف الأولى). عند إعادة فحص عملات موجودة في watchlist
    منذ ساعات/أيام (لا تعاني من فارق فهرسة إطلاقاً)، مرّر max_retries=1
    لتوفير استهلاك حصة Helius بشكل كبير (كانت إعادة الفحص الدورية لآلاف
    العملات كل 15 دقيقة، بـ6 محاولات لكل واحدة، السبب الأكبر لاستنفاد
    الحصة المجانية الشهرية بالكامل خلال ساعات فقط).
    """
    result = await _rpc_call_with_retry(
        "getTokenLargestAccounts", [mint_address], max_retries=max_retries
    )
    if not result:
        return []
    return result.get("value", [])


async def get_signatures_for_address(address: str, limit: int = 50) -> list:
    """يرجع أحدث توقيعات المعاملات لعنوان معيّن (مفيد لسجل محفظة المطور)."""
    result = await rpc_call(
        "getSignaturesForAddress", [address, {"limit": limit}]
    )
    return result or []


async def get_signatures_for_address_polling(
    address: str, limit: int = 30, until: str = None, max_retries: int = 6
) -> list:
    """
    نسخة مخصّصة للاستقصاء الدوري (Polling) بديلاً عن WebSocket — تتناوب بين
    كل مزودي RPC_ENDPOINTS عند الفشل الحقيقي فقط.

    ملاحظة حاسمة: قائمة فارغة [] هنا تعني "لا معاملات جديدة منذ آخر فحص"،
    وهذه **نتيجة ناجحة تماماً وطبيعية جداً** (أغلب دورات الاستقصاء ستكون
    كذلك) — وليست فشلاً يستوجب إعادة المحاولة على مزود آخر. لهذا لا نستخدم
    _rpc_call_with_retry العامة هنا (التي تُعامل أي نتيجة فارغة كفشل)،
    بل منطقاً مخصصاً يميّز بدقة بين "نجاح بنتيجة فارغة" و"فشل اتصال حقيقي".
    """
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
    """
    يرجع رصيد SOL الفعلي الحالي للمحفظة (وليس رقماً مضبوطاً يدوياً) — يُستخدم
    لتحديد حجم كل صفقة ديناميكياً بناءً على الرصيد الحقيقي في تلك اللحظة،
    بدل رقم ثابت يصبح قديماً بمجرد أول ربح أو خسارة.
    """
    result = await rpc_call("getBalance", [pubkey])
    lamports = result.get("value", 0) if result else 0
    return lamports / 1_000_000_000

