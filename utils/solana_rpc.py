"""
دوال مساعدة مشتركة للاستعلام من Solana RPC — تُستخدم من عدة وحدات
(mempool_listener, reputation, post_trade_monitor) لتجنب تكرار نفس منطق الاتصال.

تحسينات كفاءة وسرعة جوهرية (مبنية بالكامل على البنية المجانية الحالية،
بدون أي اعتماد على أدوات مدفوعة):

1. جلسة HTTP دائمة (Connection Pool) بدل إنشاء اتصال TCP/TLS جديد بالكامل
   مع كل استدعاء RPC منفرد — كان هذا يُبطئ كل شيء بلا داعٍ، خصوصاً في
   نافذة الزخم القصيرة للمسار السريع حيث كل جزء من الثانية يهم.

2. تتبع صحة كل مزود (Provider Health Tracking): بدل التناوب "الأعمى"
   (Round-robin) الذي يجرّب مزوداً فشل قبل ثوانٍ بنفس أولوية مزود ناجح
   تواً، نُرتّب المحاولات بحيث يُجرَّب المزود الأكثر نجاحاً مؤخراً أولاً —
   يقلل هذا المحاولات المهدورة على مزودين معطّلين معروفين، ويُسرّع الوصول
   لنتيجة حقيقية.
"""
import asyncio
import logging
import time

import aiohttp

from config.settings import ALCHEMY_RPC_URL, PRIMARY_RPC_URL, RPC_ENDPOINTS

logger = logging.getLogger("solana_rpc")

# ── جلسة HTTP دائمة (Connection Pool) ──
# تُنشأ مرة واحدة فقط وتُعاد استخدامها لكل الاستدعاءات — توفّر مصافحة
# TCP/TLS الكاملة (التي قد تستغرق مئات المللي ثانية) في كل مرة.
_session: aiohttp.ClientSession = None
_session_lock = asyncio.Lock()


async def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        async with _session_lock:
            if _session is None or _session.closed:
                # حدود اتصال سخية بما يكفي للتزامن العالي (حتى 5 معالجات
                # متزامنة في مستمع mempool + حلقات watchlist/fast-track معاً)
                connector = aiohttp.TCPConnector(limit=50, limit_per_host=20)
                _session = aiohttp.ClientSession(connector=connector)
    return _session


# ── تتبع صحة كل مزود RPC ──
# قاموس بسيط في الذاكرة: endpoint -> {"score": نقاط صحة, "last_failure": توقيت}
# النقاط تزيد عند النجاح وتنخفض عند الفشل — نُرتّب المحاولات تنازلياً حسب
# النقاط، فيُجرَّب المزود الأكثر موثوقية مؤخراً أولاً دائماً.
_endpoint_health: dict = {}


def _record_success(endpoint: str):
    h = _endpoint_health.setdefault(endpoint, {"score": 0.0, "last_failure": 0.0})
    h["score"] = min(h["score"] + 1.0, 10.0)


def _record_failure(endpoint: str):
    h = _endpoint_health.setdefault(endpoint, {"score": 0.0, "last_failure": 0.0})
    h["score"] = max(h["score"] - 3.0, -10.0)  # الفشل يُعاقَب أشد من مكافأة النجاح
    h["last_failure"] = time.time()


def _ranked_endpoints(endpoints: list) -> list:
    """يرجع نفس قائمة المزودين، لكن مُرتّبة من الأصح صحةً إلى الأقل — بدل الترتيب الثابت الأعمى."""
    if not endpoints:
        return endpoints
    return sorted(endpoints, key=lambda e: _endpoint_health.get(e, {}).get("score", 0.0), reverse=True)


async def rpc_call(method: str, params: list, timeout: int = 20, max_retries: int = 3, endpoint: str = None) -> dict:
    """
    ينفّذ استدعاء JSON-RPC عام ويرجع حقل "result" من الاستجابة، عبر جلسة
    HTTP دائمة (بدل إنشاء اتصال جديد كل مرة). يُسجّل نجاح/فشل كل مزود
    لتحسين ترتيب التناوب مستقبلاً.
    """
    target_url = endpoint or ALCHEMY_RPC_URL
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    last_error = None
    session = await _get_session()

    for attempt in range(1, max_retries + 1):
        try:
            async with session.post(target_url, json=payload, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status in (429, 503):
                    text = await resp.text()
                    _record_failure(target_url)
                    last_error = RuntimeError(
                        f"RPC status {resp.status} من [{target_url[:45]}] في {method} (محاولة {attempt}/{max_retries}): {text[:200]}"
                    )
                    if attempt < max_retries:
                        await asyncio.sleep(2 * attempt)
                        continue
                    raise last_error

                if resp.status != 200:
                    text = await resp.text()
                    _record_failure(target_url)
                    raise RuntimeError(f"RPC status {resp.status} من [{target_url[:45]}] في {method}: {text[:300]}")

                data = await resp.json()
                if "error" in data:
                    _record_failure(target_url)
                    raise RuntimeError(f"RPC error من [{target_url[:45]}] في {method}: {data['error']}")

                _record_success(target_url)
                return data.get("result")

        except asyncio.TimeoutError:
            _record_failure(target_url)
            last_error = RuntimeError(f"انتهت المهلة الزمنية ({timeout}s) من [{target_url[:45]}] أثناء استدعاء {method} (محاولة {attempt}/{max_retries})")
            if attempt < max_retries:
                await asyncio.sleep(2 * attempt)
                continue
            raise last_error
        except aiohttp.ClientError as e:
            _record_failure(target_url)
            raise RuntimeError(f"خطأ اتصال من [{target_url[:45]}] أثناء استدعاء {method}: {type(e).__name__}: {e}")

    raise last_error


async def get_transaction_via_helius(signature: str, max_retries: int = 8, retry_delay: float = 1.0) -> dict:
    """
    يجلب تفاصيل معاملة، مع إعادة محاولة عند رجوع النتيجة فارغة (None)، وتناوب
    بين المزودين مُرتَّباً حسب الصحة (الأكثر نجاحاً مؤخراً يُجرَّب أولاً).

    ملاحظة: بعد تجربة عدة قيم، اتضح أن الفارق الزمني بين لحظة اكتشاف الحدث
    ولحظة توفر تفاصيل المعاملة عبر getTransaction قد يصل لعدة ثوانٍ فعلياً،
    حتى مع commitment=confirmed. لذلك نزيد عدد المحاولات إلى 8.
    """
    endpoints = _ranked_endpoints(RPC_ENDPOINTS) or [PRIMARY_RPC_URL]

    for attempt in range(1, max_retries + 1):
        endpoint = endpoints[(attempt - 1) % len(endpoints)]
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
    غلاف عام لإعادة المحاولة مع commitment=confirmed، لأي استعلام قد يُطلب
    فوراً بعد اكتشاف حساب/عملة جديدة جداً لم تُفهرَس بعد على بعض المزودين.
    يستخدم التناوب المُرتَّب حسب صحة كل مزود.
    """
    config = {"commitment": "confirmed"}
    if extra_config:
        config.update(extra_config)
    full_params = params_without_config + [config]

    endpoints = _ranked_endpoints(RPC_ENDPOINTS) or [PRIMARY_RPC_URL]
    last_error = None
    for attempt in range(1, max_retries + 1):
        endpoint = endpoints[(attempt - 1) % len(endpoints)]
        try:
            result = await rpc_call(method, full_params, endpoint=endpoint, max_retries=1)
        except RuntimeError as e:
            last_error = e
            result = None
            logger.debug(f"محاولة {attempt}/{max_retries} فشلت على {endpoint[:45]}...: {str(e)[:150]}")

        if result and (not isinstance(result, dict) or result.get("value") is not None):
            return result

        if attempt < max_retries:
            await asyncio.sleep(retry_delay)

    if last_error:
        raise last_error
    return None


async def get_account_info_base64(address: str) -> str:
    """يرجع بيانات الحساب مُرمّزة base64 (raw bytes) لعنوان معيّن، مع إعادة محاولة."""
    result = await _rpc_call_with_retry(
        "getAccountInfo", [address], extra_config={"encoding": "base64"}
    )
    if not result or not result.get("value"):
        raise ValueError(f"لا يوجد حساب فعّال على العنوان: {address}")
    return result["value"]["data"][0]


async def get_token_largest_accounts(mint_address: str, max_retries: int = 6) -> list:
    """
    يرجع قائمة أكبر 20 حاملاً لعملة معيّنة (address + amount + decimals).

    ملاحظة كفاءة مهمة: القيمة الافتراضية (6 محاولات) مصمَّمة لعملات حديثة
    جداً (لحظة الاكتشاف الأولى). عند إعادة فحص عملات موجودة في watchlist
    منذ ساعات/أيام، مرّر max_retries أقل لتوفير الحصص.
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
    نسخة مخصّصة للاستقصاء الدوري (Polling) بديلاً عن WebSocket — تتناوب
    (مُرتَّبة حسب الصحة) عند الفشل الحقيقي فقط.

    ملاحظة حاسمة: قائمة فارغة [] تعني "لا معاملات جديدة منذ آخر فحص" —
    نتيجة ناجحة وطبيعية جداً، وليست فشلاً يستوجب إعادة المحاولة على مزود آخر.
    """
    config = {"limit": limit, "commitment": "confirmed"}
    if until:
        config["until"] = until

    endpoints = _ranked_endpoints(RPC_ENDPOINTS) or [ALCHEMY_RPC_URL]
    last_error = None

    for attempt in range(max_retries):
        endpoint = endpoints[attempt % len(endpoints)]
        try:
            result = await rpc_call(
                "getSignaturesForAddress", [address, config], endpoint=endpoint, max_retries=1
            )
            return result if result is not None else []
        except RuntimeError as e:
            error_text = str(e)
            # حالة معروفة ومتوقعة: نتناوب بين مزودين قد يختلف تقدّم فهرستهما،
            # فقد يرفض مزود معيّن "until" مسجَّلاً من مزود آخر لم يفهرسه بعد
            # (كود -32020 "Transaction not found"). الحل: إعادة محاولة على
            # نفس المزود، لكن بدون "until" هذه المرة (نجلب أحدث التوقيعات
            # مباشرة بدل الاعتماد على نقطة مرجعية قد لا يعرفها هذا المزود) —
            # ذاكرة منع التكرار في mempool_listener تحمينا من أي إعادة معالجة.
            if "-32020" in error_text and "until" in config:
                fallback_config = {k: v for k, v in config.items() if k != "until"}
                try:
                    result = await rpc_call(
                        "getSignaturesForAddress", [address, fallback_config],
                        endpoint=endpoint, max_retries=1,
                    )
                    return result if result is not None else []
                except RuntimeError as e2:
                    last_error = e2
                    continue
            last_error = e
            continue

    if last_error:
        raise last_error
    return []


async def get_wallet_sol_balance(pubkey: str) -> float:
    """يرجع رصيد SOL الفعلي الحالي للمحفظة (ديناميكياً، وليس رقماً ثابتاً)."""
    result = await rpc_call("getBalance", [pubkey])
    lamports = result.get("value", 0) if result else 0
    return lamports / 1_000_000_000
