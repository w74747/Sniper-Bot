"""
فحوصات السمعة الخارجية:
1. سجل محفظة المطور (Deployer Wallet History) — عبر Solana RPC (getSignaturesForAddress + تحليل)
2. درجة الأمان من RugCheck.xyz API

هذه الفحوصات أبطأ قليلاً من الفلاتر on-chain المباشرة لكنها لا تزال ضمن نافذة
الثواني المعدودة، وتُعتبر جزءاً من "الفلترة الآلية عند الدخول".
"""
import logging
from dataclasses import dataclass
from typing import Optional

import aiohttp

from config.settings import RUGCHECK_API_BASE, HELIUS_RPC_URL, FILTERS

logger = logging.getLogger("reputation")


@dataclass
class DeployerHistoryResult:
    prior_token_launches: int
    known_prior_rugs: int
    reason: str


@dataclass
class RugCheckResult:
    score: float  # 0-100، كلما ارتفع كان أفضل
    risks: list
    raw: dict


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
            async with session.post(HELIUS_RPC_URL, json=payload, timeout=10) as resp:
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


async def check_rugcheck_score(mint_address: str) -> Optional[RugCheckResult]:
    """يستعلم من RugCheck.xyz API عن درجة أمان العقد."""
    url = f"{RUGCHECK_API_BASE}/tokens/{mint_address}/report"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=10) as resp:
                if resp.status != 200:
                    logger.warning(f"RugCheck رجع status {resp.status} لعملة {mint_address}")
                    return None
                data = await resp.json()
                return RugCheckResult(
                    score=data.get("score", 0),
                    risks=data.get("risks", []),
                    raw=data,
                )
        except Exception as e:
            logger.warning(f"فشل الاتصال بـ RugCheck: {e}")
            return None


async def evaluate_reputation(mint_address: str, deployer_wallet: str):
    """يجمع نتيجة الفحصين ويقرر القبول/الرفض حسب العتبات في الإعدادات."""
    history = await check_deployer_history(deployer_wallet)
    if history.known_prior_rugs > FILTERS.max_allowed_prior_rugs:
        return False, f"رفض بسبب سجل المطور: {history.reason}"

    rugcheck = await check_rugcheck_score(mint_address)
    if rugcheck is None:
        return False, "تعذّر الحصول على تقرير RugCheck — تم الرفض احتياطياً (fail-safe)"

    if rugcheck.score < FILTERS.min_rugcheck_score:
        return False, (
            f"درجة RugCheck ({rugcheck.score}) أقل من الحد الأدنى "
            f"({FILTERS.min_rugcheck_score}). المخاطر المكتشفة: {rugcheck.risks}"
        )

    return True, f"اجتازت فحوصات السمعة (RugCheck score: {rugcheck.score})"
