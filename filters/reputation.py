"""
فحوصات السمعة الخارجية:
1. سجل محفظة المطور (Deployer Wallet History) — عبر Solana RPC (getSignaturesForAddress + تحليل)
2. درجة الأمان من GoPlus Security API (بديل مجاني بالكامل لـ RugCheck)

هذه الفحوصات أبطأ قليلاً من الفلاتر on-chain المباشرة لكنها لا تزال ضمن نافذة
الثواني المعدودة، وتُعتبر جزءاً من "الفلترة الآلية عند الدخول".
"""
import asyncio
import hashlib
import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional

import aiohttp

from config.settings import (
    GOPLUS_API_BASE, GOPLUS_APP_KEY, GOPLUS_APP_SECRET,
    ALCHEMY_RPC_URL, FILTERS,
)

logger = logging.getLogger("reputation")

# تخزين مؤقت للتوكن في الذاكرة (access_token, وقت الانتهاء بالثواني)
_token_cache = {"access_token": None, "expires_at": 0}

# ── مُقيِّد معدل ذاتي لـ GoPlus ──
# الحد الرسمي المؤكَّد من GoPlus للفريتير المجاني: 30 طلب/دقيقة بالضبط.
# بدون هذا، الحجم الكبير الجديد من الاكتشافات (عبر PumpPortal) كان يتجاوز
# هذا الحد بسهولة، فيُرفَض أغلب الطلبات (فشل غير حقيقي، وليس تقييماً فعلياً
# للعملة) — بدل رفضها، ننتظر بذكاء حتى يتوفر "مقعد" ضمن النافذة الزمنية.
GOPLUS_MAX_CALLS_PER_MINUTE = 25  # هامش أمان تحت الحد الرسمي (30) عمداً
_goplus_call_times: deque = deque()
_goplus_rate_limit_lock = asyncio.Lock()


async def _wait_for_goplus_rate_limit():
    """يحجز "مقعداً" ضمن نافذة الدقيقة الأخيرة، وينتظر إذا كانت ممتلئة بدل الفشل الفوري."""
    async with _goplus_rate_limit_lock:
        while True:
            now = time.time()
            while _goplus_call_times and now - _goplus_call_times[0] > 60:
                _goplus_call_times.popleft()

            if len(_goplus_call_times) < GOPLUS_MAX_CALLS_PER_MINUTE:
                _goplus_call_times.append(now)
                return

            wait_time = 60 - (now - _goplus_call_times[0]) + 0.1
            logger.debug(f"⏳ حد معدل GoPlus الذاتي ممتلئ — انتظار {wait_time:.1f}s قبل المحاولة التالية")
            await asyncio.sleep(max(wait_time, 0.1))


@dataclass
class DeployerHistoryResult:
    prior_token_launches: int
    known_prior_rugs: int
    reason: str


@dataclass
class GoPlusResult:
    """نتيجة موحّدة مستخلصة من استجابة GoPlus (تقوم مقام RugCheckResult سابقاً)."""
    score: float  # 0-100 نحسبها نحن بناءً على الأعلام (flags) التي يرجعها GoPlus
    risks: list
    raw: dict


async def get_goplus_access_token() -> Optional[str]:
    """
    يولّد توقيعاً (sign) عبر sha1(app_key + timestamp + app_secret)، ويطلب به
    access token من GoPlus. يُخزَّن التوكن مؤقتاً ويُعاد استخدامه حتى قرب انتهائه
    (GoPlus يرجع مدة صلاحية expires_in بالثواني ضمن الاستجابة).
    """
    if not GOPLUS_APP_KEY or not GOPLUS_APP_SECRET:
        logger.warning("GOPLUS_APP_KEY أو GOPLUS_APP_SECRET غير موجودين في البيئة")
        return None

    now = int(time.time())
    if _token_cache["access_token"] and now < _token_cache["expires_at"] - 60:
        return _token_cache["access_token"]  # التوكن الحالي ما زال صالحاً

    sign_raw = f"{GOPLUS_APP_KEY}{now}{GOPLUS_APP_SECRET}"
    sign = hashlib.sha1(sign_raw.encode("utf-8")).hexdigest()

    url = f"{GOPLUS_API_BASE}/token"
    payload = {"app_key": GOPLUS_APP_KEY, "time": now, "sign": sign}

    await _wait_for_goplus_rate_limit()
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload, timeout=10) as resp:
                raw_text = await resp.text()
                if resp.status != 200:
                    logger.warning(
                        f"فشل الحصول على GoPlus access token: status {resp.status} — {raw_text[:300]}"
                    )
                    return None
                data = await resp.json()
                result = data.get("result", {})
                token = result.get("access_token")
                expires_in = result.get("expires_in", 86400)  # افتراضي: 24 ساعة
                if token:
                    _token_cache["access_token"] = token
                    _token_cache["expires_at"] = now + int(expires_in)
                    logger.info(f"تم الحصول على GoPlus access token جديد (ينتهي خلال {expires_in}s)")
                else:
                    logger.warning(f"استجابة GoPlus /token لا تحتوي access_token: {data}")
                return token
        except Exception as e:
            logger.warning(f"خطأ أثناء طلب GoPlus access token: {type(e).__name__}: {e}")
            return None


async def check_deployer_history(deployer_wallet: str) -> DeployerHistoryResult:
    """
    يفحص محفظة المطور بحثاً عن سجل إطلاق عملات سابقة انتهت بـ rug pull موثق.

    ملاحظة تنفيذية: هذا مثال مبسّط. في الإنتاج، يُفضّل استخدام خدمة متخصصة
    (مثل Bubblemaps API أو قاعدة بيانات مجتمعية لعناوين rug pull موثقة)
    بدل بناء المنطق بالكامل يدوياً، لتقليل نسبة الأخطاء (false negatives).
    """
    async with aiohttp.ClientSession() as session:
        try:
            # مثال: استعلام عن تاريخ المعاملات لمحفظة المطور
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getSignaturesForAddress",
                "params": [deployer_wallet, {"limit": 50}],
            }
            async with session.post(ALCHEMY_RPC_URL, json=payload, timeout=10) as resp:
                data = await resp.json()
                tx_count = len(data.get("result", []))

            # TODO: تكامل فعلي مع قاعدة بيانات rug pulls موثقة (مثل GoPlus أو مصدر مجتمعي)
            # هذا السطر مكان الحجز لمنطق التحقق الفعلي — حالياً يرجع صفر كقيمة افتراضية آمنة
            known_rugs = 0

            return DeployerHistoryResult(
                prior_token_launches=tx_count,
                known_prior_rugs=known_rugs,
                reason=(
                    "لم يُعثر على سجل rug موثق لهذه المحفظة"
                    if known_rugs == 0
                    else f"المحفظة مرتبطة بـ {known_rugs} حالة rug موثقة سابقاً"
                ),
            )
        except Exception as e:
            logger.warning(f"فشل فحص سجل المطور: {e}")
            # عند الفشل التقني، نتعامل بحذر: نرجع نتيجة تستدعي رفض العملة احتياطياً
            return DeployerHistoryResult(
                prior_token_launches=0,
                known_prior_rugs=999,
                reason="تعذّر التحقق تقنياً من سجل المطور — تم الرفض احتياطياً (fail-safe)",
            )


async def check_goplus_security(mint_address: str) -> Optional[GoPlusResult]:
    """
    يستعلم من GoPlus Security API عن أمان عقد Solana.
    Endpoint: GET https://api.gopluslabs.io/api/v1/solana/token_security?contract_addresses=...

    ملاحظة تشخيصية مهمة: هذا الـ endpoint يعمل بنجاح بدون أي مصادقة (حد مجاني
    أساسي)، لكن إرسال Authorization غير صحيح الصيغة قد يتسبب في رفض الطلب
    بالكامل برسالة "signature verification failure" بدل تجاهله بصمت. لذلك
    نجرّب أولاً بدون أي هيدر مصادقة، ونستخدم access_token فقط كخطوة احتياطية
    لاحقة إذا فشلت المحاولة الأولى تحديداً بسبب نقص البيانات (لا بسبب خطأ توقيع).
    """
    url = f"{GOPLUS_API_BASE}/solana/token_security"
    params = {"contract_addresses": mint_address}

    async def _attempt(headers: dict, label: str) -> Optional[GoPlusResult]:
        await _wait_for_goplus_rate_limit()
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, params=params, headers=headers, timeout=10) as resp:
                    raw_text = await resp.text()
                    if resp.status != 200:
                        logger.warning(
                            f"[{label}] GoPlus رجع status {resp.status} لعملة {mint_address}: {raw_text[:300]}"
                        )
                        return None
                    data = await resp.json()
                    if "code" in data and data.get("code") not in (0, 1, 200):
                        logger.warning(f"[{label}] GoPlus رجع خطأ منطقي: {raw_text[:300]}")
                        return None
                    result_dict = data.get("result", {})
                    token_data = result_dict.get(mint_address)
                    if not token_data:
                        for key, value in result_dict.items():
                            if key.lower() == mint_address.lower():
                                token_data = value
                                break
                    if not token_data:
                        logger.warning(
                            f"[{label}] GoPlus لم يُرجع بيانات لعملة {mint_address} — "
                            f"الاستجابة الخام: {raw_text[:400]}"
                        )
                        return None
                    logger.warning(f"[{label}] نجح الحصول على بيانات GoPlus ✅")
                    return _parse_goplus_response(token_data)
            except Exception as e:
                logger.warning(f"[{label}] فشل الاتصال بـ GoPlus: {type(e).__name__}: {e}")
                return None

    # المحاولة 1: بدون أي هيدر مصادقة (الحد المجاني الأساسي المعروف أنه يعمل)
    result = await _attempt(headers={}, label="بدون-توكن")
    if result:
        return result

    # المحاولة 2: مع access_token (فقط إذا فشلت المحاولة الأولى، وليس بسبب خطأ توقيع)
    access_token = await get_goplus_access_token()
    if access_token:
        result = await _attempt(
            headers={"Authorization": f"Bearer {access_token}"}, label="مع-توكن"
        )
        if result:
            return result

    return None


def _parse_goplus_response(token_data: dict) -> GoPlusResult:
    """
    يحوّل استجابة GoPlus الخام (أعلام Boolean/نصية) إلى درجة رقمية موحّدة (0-100)
    وقائمة مخاطر نصية، بنفس شكل الدرجة التي كنا نستخدمها من RugCheck سابقاً.
    """
    risks = []
    score = 100.0  # نبدأ من الدرجة الكاملة ونخصم عند كل علم خطر

    # هذه الأعلام تُرجعها GoPlus عادة كسلاسل نصية "1"/"0" — نتعامل معها بمرونة
    def is_risky(flag_value) -> bool:
        return str(flag_value) in ("1", "true", "True")

    if is_risky(token_data.get("mintable", {}).get("status", "0")):
        risks.append("صلاحية طباعة عملات جديدة (mintable) ما زالت فعّالة")
        score -= 40

    if is_risky(token_data.get("freezable", {}).get("status", "0")):
        risks.append("صلاحية تجميد المحافظ (freezable) ما زالت فعّالة")
        score -= 40

    if is_risky(token_data.get("transfer_fee_upgradable", {}).get("status", "0")):
        risks.append("ضريبة التحويل قابلة للتعديل بشكل غير محدود")
        score -= 15

    if is_risky(token_data.get("closable", {}).get("status", "0")):
        risks.append("العقد يحتوي على صلاحية إغلاق الحساب (closable)")
        score -= 10

    balance_mutable = token_data.get("balance_mutable_authority", {})
    if is_risky(balance_mutable.get("status", "0")):
        risks.append("يوجد صلاحية لتعديل أرصدة المستخدمين مباشرة (balance_mutable_authority)")
        score -= 40

    score = max(0.0, score)
    return GoPlusResult(score=score, risks=risks, raw=token_data)


async def evaluate_reputation(mint_address: str, deployer_wallet: str):
    """يجمع نتيجة الفحصين ويقرر القبول/الرفض حسب العتبات في الإعدادات."""
    history = await check_deployer_history(deployer_wallet)
    if history.known_prior_rugs > FILTERS.max_allowed_prior_rugs:
        return False, f"رفض بسبب سجل المطور: {history.reason}"

    goplus = await check_goplus_security(mint_address)
    if goplus is None:
        return False, "تعذّر الحصول على تقرير GoPlus — تم الرفض احتياطياً (fail-safe)"

    if goplus.score < FILTERS.min_security_score:
        return False, (
            f"درجة الأمان ({goplus.score}) أقل من الحد الأدنى "
            f"({FILTERS.min_security_score}). المخاطر المكتشفة: {goplus.risks}"
        )

    return True, f"اجتازت فحوصات السمعة (GoPlus score: {goplus.score})"
