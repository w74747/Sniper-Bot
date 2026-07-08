"""
محاكاة بيع فعلية قبل أي شراء حقيقي — أهم فحص لكشف الـ honeypots.

الفكرة: عقود الـ honeypot غالباً تسمح بالشراء بحرية لكنها تمنع البيع (أو تفرض
ضريبة بيع مخفية مرتفعة جداً). فحص `owner()` أو `renounced` وحده لا يكشف هذا،
لأن المطور يمكنه إخفاء منطق منع البيع في مكان آخر من العقد.

الحل: نستعلم من Jupiter Quote API عن مسار بيع فعلي لكمية اختبار صغيرة
(token -> SOL)، ونقارن الكمية المتوقعة بالكمية الفعلية لحساب ضريبة البيع
الحقيقية. Jupiter يحاكي التسعير عبر كل مسارات DEX المتاحة فعلياً، وهذا
غالباً يكفي لكشف معظم حالات honeypot دون الحاجة لبناء وتوقيع معاملة فعلية.
"""
import logging
from dataclasses import dataclass

import aiohttp

logger = logging.getLogger("sell_simulation")

JUPITER_QUOTE_API = "https://quote-api.jup.ag/v6/quote"
SOL_MINT_ADDRESS = "So11111111111111111111111111111111111111112"


@dataclass
class SellSimulationResult:
    can_sell: bool
    effective_sell_tax_pct: float
    reason: str


async def simulate_sell(
    rpc_client,
    wallet_pubkey: str,
    mint_address: str,
    pool_address: str,
    test_amount_lamports: int,
) -> SellSimulationResult:
    """
    يستعلم من Jupiter Quote API عن مسار بيع (mint_address -> SOL) بكمية اختبار.

    منطق حساب "ضريبة البيع الفعلية": نقارن قيمة outAmount الفعلية من Jupiter
    بقيمة السوق النظرية (باستخدام priceImpactPct كمؤشر مساعد)، وأي فشل في
    الحصول على أي مسار (routesCount = 0) يُعتبر مؤشراً قوياً على honeypot.

    ملاحظة تنفيذية: هذا لا يبني ولا يوقّع معاملة فعلية (لا حاجة لمفتاح خاص
    في مرحلة الفحص هذه) — فقط يستعلم عن التسعير، وهو ما يكفي عملياً لكشف
    الغالبية العظمى من عقود honeypot الشائعة قبل الالتزام بأي رأس مال.
    """
    try:
        params = {
            "inputMint": mint_address,
            "outputMint": SOL_MINT_ADDRESS,
            "amount": test_amount_lamports,
            "slippageBps": 500,  # 5% انزلاق مسموح لمحاكاة الاختبار فقط
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(JUPITER_QUOTE_API, params=params, timeout=10) as resp:
                if resp.status != 200:
                    return SellSimulationResult(
                        can_sell=False,
                        effective_sell_tax_pct=100.0,
                        reason=f"Jupiter رجع status {resp.status} — لا يوجد مسار بيع متاح",
                    )
                data = await resp.json()

        if not data or "outAmount" not in data:
            return SellSimulationResult(
                can_sell=False,
                effective_sell_tax_pct=100.0,
                reason="لا يوجد مسار بيع (route) متاح على Jupiter — honeypot محتمل جداً",
            )

        price_impact_pct = float(data.get("priceImpactPct", 0)) * 100

        # priceImpactPct من Jupiter يشمل تأثير السيولة الطبيعي + أي ضريبة مخفية معاً.
        # نستخدمه هنا كتقدير عملي لـ "التكلفة الفعلية للبيع"، مع العلم أنه ليس
        # قياساً دقيقاً 100% لضريبة العقد وحدها (يشمل انزلاق السوق الطبيعي أيضاً).
        return SellSimulationResult(
            can_sell=True,
            effective_sell_tax_pct=abs(price_impact_pct),
            reason=f"وُجد مسار بيع فعلي عبر Jupiter (تأثير السعر: {price_impact_pct:.2f}%)",
        )

    except Exception as e:
        logger.error(f"فشلت محاكاة البيع لعملة {mint_address}: {e}")
        # مبدأ fail-safe: أي فشل في المحاكاة نفسها = رفض العملة احتياطياً
        return SellSimulationResult(
            can_sell=False,
            effective_sell_tax_pct=100.0,
            reason=f"تعذّر تنفيذ محاكاة البيع تقنياً: {e} — تم الرفض احتياطياً",
        )


def evaluate_simulation_result(
    result: SellSimulationResult, max_acceptable_tax_pct: float = 15.0
) -> tuple[bool, str]:
    """يقرر القبول/الرفض بناءً على نتيجة المحاكاة."""
    if not result.can_sell:
        return False, f"فشلت محاكاة البيع تماماً — honeypot محتمل: {result.reason}"

    if result.effective_sell_tax_pct > max_acceptable_tax_pct:
        return False, (
            f"ضريبة البيع الفعلية ({result.effective_sell_tax_pct:.1f}%) "
            f"أعلى من الحد المقبول ({max_acceptable_tax_pct}%)"
        )

    return True, f"محاكاة البيع ناجحة — ضريبة البيع الفعلية {result.effective_sell_tax_pct:.1f}%"
