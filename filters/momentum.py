"""
رصد "الانطلاق الصاروخي" في أول دقائق بعد الإدراج — منفصل تماماً عن:
- فلاتر الأمان (GoPlus، onchain_filters) التي تجيب: "هل هذه العملة آمنة؟"
- watchlist طويل الأمد (24-72 ساعة) الذي يجيب: "هل جدّيتها مستمرة؟"

هذه الوحدة تجيب سؤالاً مختلفاً تماماً: "هل هذه العملة تتحرك بقوة الآن؟"

المصدر الأساسي: DexScreener (مجاني بالكامل، بدون مفتاح API، ~300 طلب/دقيقة).
Birdeye مُدرَج كمصدر احتياطي جزئي (سعر فقط) لكنه معطّل حالياً — الفريتير
المجاني لـ Birdeye لا يشمل بيانات الحجم/الشراء-البيع أصلاً (تحتاج باقة
مدفوعة، أرخصها 39$/شهرياً)، لذا نؤجّل تفعيله لحين تحقيق إيرادات كما اتُّفق.

نستدعي كلا المصدرين (عندما يُفعَّل Birdeye) بالتوازي عبر asyncio.gather
لتقليل التأخير والاعتماد على أول رد ناجح، بدل التتابع.
"""
import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

import aiohttp

from config.settings import (
    DEXSCREENER_API_BASE, BIRDEYE_API_KEY, BIRDEYE_API_BASE, MOMENTUM,
)

logger = logging.getLogger("momentum")


@dataclass
class MomentumData:
    """بيانات الزخم المستخرجة من مصدر واحد (DexScreener أو Birdeye)."""
    source: str
    price_usd: float
    price_change_m5_pct: float
    volume_m5_usd: float
    buys_m5: int
    sells_m5: int
    liquidity_usd: float
    market_cap_usd: float = 0.0  # للاستراتيجية الجديدة "قرب التخرج" (graduation_proximity)

    @property
    def buy_sell_ratio_m5(self) -> float:
        if self.sells_m5 == 0:
            return float(self.buys_m5) if self.buys_m5 > 0 else 0.0
        return self.buys_m5 / self.sells_m5


async def fetch_momentum_batch(mint_addresses: list, chain: str = "solana") -> dict:
    """
    يفحص حتى 30 عملة في **استدعاء واحد فقط** عبر DexScreener (نقطة نهاية
    /tokens/v1/ المُجمَّعة)، بدل استدعاء منفصل لكل عملة — هذا هو الإصلاح
    الجذري لمشكلة 429 المستمرة: كنا نُطلق عشرات الطلبات المتزامنة كل 10
    ثوانٍ (طلب واحد لكل عملة قيد المراقبة)، بينما DexScreener يسمح بحد
    أقصى ~60 طلباً/دقيقة إجمالاً — تجميع 30 عملة في طلب واحد يُخفّض عدد
    الطلبات الفعلية بمقدار 30 ضعفاً تقريباً.

    يرجع قاموساً {mint_address: MomentumData} — العملات التي لا تظهر في
    الرد (لم تُفهرس بعد) لن تكون مفاتيح في القاموس المُرجَع إطلاقاً.
    """
    if not mint_addresses:
        return {}

    result: dict = {}
    # DexScreener يقبل 30 عنواناً كحد أقصى لكل استدعاء — نُقسّم القائمة دفعات
    for i in range(0, len(mint_addresses), 30):
        batch = mint_addresses[i:i + 30]
        addresses_param = ",".join(batch)
        url = f"{DEXSCREENER_API_BASE}/tokens/v1/{chain}/{addresses_param}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        logger.info(f"📉 DexScreener (دفعة {len(batch)} عملة) رجع status {resp.status}: {text[:150]}")
                        continue
                    pairs = await resp.json()
        except Exception as e:
            logger.info(f"📉 فشل استعلام DexScreener المُجمَّع: {type(e).__name__}: {e}")
            continue

        if not pairs:
            continue

        # قد يُرجع أكثر من pair لنفس العملة (عدة أزواج) — نحتفظ فقط بالأعلى سيولة لكل عنوان
        best_by_mint: dict = {}
        for pair in pairs:
            base_address = (pair.get("baseToken") or {}).get("address", "")
            if not base_address:
                continue
            liquidity = (pair.get("liquidity") or {}).get("usd", 0) or 0
            if base_address not in best_by_mint or liquidity > best_by_mint[base_address][1]:
                best_by_mint[base_address] = (pair, liquidity)

        for mint_addr, (pair, _) in best_by_mint.items():
            try:
                txns_m5 = (pair.get("txns") or {}).get("m5", {}) or {}
                result[mint_addr] = MomentumData(
                    source="dexscreener",
                    price_usd=float(pair.get("priceUsd") or 0),
                    price_change_m5_pct=float((pair.get("priceChange") or {}).get("m5", 0) or 0),
                    volume_m5_usd=float((pair.get("volume") or {}).get("m5", 0) or 0),
                    buys_m5=int(txns_m5.get("buys", 0) or 0),
                    sells_m5=int(txns_m5.get("sells", 0) or 0),
                    liquidity_usd=float((pair.get("liquidity") or {}).get("usd", 0) or 0),
                    market_cap_usd=float(pair.get("marketCap") or pair.get("fdv") or 0),
                )
            except (TypeError, ValueError):
                continue

    return result


async def fetch_from_dexscreener(mint_address: str, chain: str = "solana") -> Optional[MomentumData]:
    """
    يجلب بيانات الزخم من DexScreener عبر token-pairs/v1 — قد يرجع أكثر من
    "pair" واحد لنفس العملة (لو كانت مُدرجة على أكثر من DEX)؛ نختار الـ pair
    ذا أعلى سيولة لأنه الأكثر تمثيلاً لحركة السعر الفعلية.
    """
    url = f"{DEXSCREENER_API_BASE}/token-pairs/v1/{chain}/{mint_address}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=8) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    # تشخيص مؤقت (INFO بدل debug المخفي): نحتاج رؤية السبب
                    # الحقيقي بدل نتيجة غامضة "تعذّر الحصول على بيانات" فقط —
                    # نفس الدرس المستفاد سابقاً مع تشخيص مزودي RPC.
                    logger.info(f"📉 DexScreener رجع status {resp.status} لـ {mint_address}: {text[:150]}")
                    return None
                pairs = await resp.json()
    except Exception as e:
        logger.info(f"📉 فشل الاتصال بـ DexScreener لـ {mint_address}: {type(e).__name__}: {e}")
        return None

    if not pairs:
        logger.info(f"📉 DexScreener رجع قائمة فارغة لـ {mint_address} (لم تُفهرس بعد على الأرجح)")
        return None

    # اختيار الـ pair ذا أعلى سيولة من بين كل الأزواج المُرجعة
    best_pair = max(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd", 0) or 0)

    try:
        txns_m5 = (best_pair.get("txns") or {}).get("m5", {}) or {}
        return MomentumData(
            source="dexscreener",
            price_usd=float(best_pair.get("priceUsd") or 0),
            price_change_m5_pct=float((best_pair.get("priceChange") or {}).get("m5", 0) or 0),
            volume_m5_usd=float((best_pair.get("volume") or {}).get("m5", 0) or 0),
            buys_m5=int(txns_m5.get("buys", 0) or 0),
            sells_m5=int(txns_m5.get("sells", 0) or 0),
            liquidity_usd=float((best_pair.get("liquidity") or {}).get("usd", 0) or 0),
        )
    except (TypeError, ValueError) as e:
        logger.warning(f"فشل تحليل استجابة DexScreener لـ {mint_address}: {e}")
        return None


async def fetch_from_birdeye(mint_address: str, chain: str = "solana") -> Optional[MomentumData]:
    """
    مصدر احتياطي جزئي — سعر فقط (الفريتير المجاني لـ Birdeye لا يشمل حجم/شراء-بيع).
    معطّل تلقائياً إذا لم يُضبط BIRDEYE_API_KEY (وهو الوضع الحالي المتفق عليه).
    """
    if not BIRDEYE_API_KEY:
        return None

    url = f"{BIRDEYE_API_BASE}/defi/price"
    headers = {"X-API-KEY": BIRDEYE_API_KEY, "x-chain": chain}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, params={"address": mint_address}, headers=headers, timeout=8
            ) as resp:
                if resp.status != 200:
                    logger.debug(f"Birdeye رجع status {resp.status} لـ {mint_address}")
                    return None
                data = await resp.json()
    except Exception as e:
        logger.debug(f"فشل الاتصال بـ Birdeye لـ {mint_address}: {type(e).__name__}: {e}")
        return None

    price = (data.get("data") or {}).get("value")
    if price is None:
        return None

    # ملاحظة: Birdeye الفريتير المجاني يعطي السعر فقط — لا حجم ولا شراء/بيع،
    # لذلك نملأ الباقي بأصفار (لن نعتمد عليه لحساب المؤشرات الكاملة، فقط
    # كتحقق سريع من السعر إذا تأخر DexScreener).
    return MomentumData(
        source="birdeye",
        price_usd=float(price),
        price_change_m5_pct=0.0,
        volume_m5_usd=0.0,
        buys_m5=0,
        sells_m5=0,
        liquidity_usd=0.0,
    )


async def fetch_momentum_data(mint_address: str, chain: str = "solana") -> Optional[MomentumData]:
    """
    يستدعي DexScreener وBirdeye (إن كان مفعّلاً) بالتوازي، ويرجع أول نتيجة
    كاملة وناجحة. حالياً — بما أن Birdeye معطّل — هذا يعتمد عملياً على
    DexScreener فقط، لكن الكود جاهز لتفعيل Birdeye فوراً بمجرد إضافة مفتاحه.
    """
    tasks = [asyncio.create_task(fetch_from_dexscreener(mint_address, chain))]
    if BIRDEYE_API_KEY:
        tasks.append(asyncio.create_task(fetch_from_birdeye(mint_address, chain)))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # نُفضّل نتيجة DexScreener دائماً إن نجحت (بيانات كاملة)، ونستخدم Birdeye
    # فقط كبديل إذا فشل DexScreener تماماً (بيانات سعر جزئية أفضل من لا شيء)
    dexscreener_result = results[0] if not isinstance(results[0], Exception) else None
    if dexscreener_result:
        return dexscreener_result

    if len(results) > 1 and not isinstance(results[1], Exception):
        return results[1]

    return None


def evaluate_momentum(data: MomentumData) -> tuple[bool, str]:
    """
    يقرر: هل هذه العملة تُظهر "انطلاقاً صاروخياً" حقيقياً الآن؟
    يرجع (is_rocketing: bool, reason: str) لتوضيح القرار بدقة.

    ملاحظة: إذا جاءت البيانات من Birdeye (مصدر السعر الجزئي فقط)، لا يمكن
    تقييم الزخم الكامل (حجم/شراء-بيع غير متوفرين) — نرجع False بصراحة
    بدل الحكم على بيانات ناقصة.
    """
    if data.source == "birdeye":
        return False, "بيانات Birdeye جزئية (سعر فقط) — لا يمكن تقييم الزخم الكامل"

    if data.liquidity_usd < MOMENTUM.min_liquidity_usd:
        return False, (
            f"سيولة منخفضة جداً (${data.liquidity_usd:,.0f}) — "
            f"قابلة للتلاعب بسهولة، الحد الأدنى ${MOMENTUM.min_liquidity_usd:,.0f}"
        )

    if data.price_change_m5_pct < MOMENTUM.min_price_change_m5_pct:
        return False, (
            f"تغيّر السعر ({data.price_change_m5_pct:.1f}%) أقل من الحد الأدنى "
            f"({MOMENTUM.min_price_change_m5_pct}%) خلال آخر 5 دقائق"
        )

    if data.price_change_m5_pct > MOMENTUM.max_price_change_m5_pct:
        return False, (
            f"تغيّر السعر ({data.price_change_m5_pct:.1f}%) أعلى بكثير من السقف المعقول "
            f"({MOMENTUM.max_price_change_m5_pct}%) — غالباً قمة انفجار مصطنعة على وشك "
            f"الانهيار (Pump قبل Dump)، وليست فرصة حقيقية"
        )

    if data.volume_m5_usd < MOMENTUM.min_volume_m5_usd:
        return False, (
            f"حجم التداول (${data.volume_m5_usd:,.0f}) أقل من الحد الأدنى "
            f"(${MOMENTUM.min_volume_m5_usd:,.0f}) خلال آخر 5 دقائق"
        )

    if data.buys_m5 < MOMENTUM.min_unique_buys_m5:
        return False, (
            f"عدد عمليات الشراء ({data.buys_m5}) أقل من الحد الأدنى "
            f"({MOMENTUM.min_unique_buys_m5}) خلال آخر 5 دقائق"
        )

    if data.buy_sell_ratio_m5 < MOMENTUM.min_buy_sell_ratio_m5:
        return False, (
            f"نسبة الشراء/البيع ({data.buy_sell_ratio_m5:.2f}) أقل من الحد الأدنى "
            f"({MOMENTUM.min_buy_sell_ratio_m5}) — الشراء لا يفوق البيع بوضوح كافٍ"
        )

    return True, (
        f"✅ انطلاق صاروخي حقيقي: سعر +{data.price_change_m5_pct:.1f}% خلال 5 دقائق، "
        f"حجم ${data.volume_m5_usd:,.0f}، نسبة شراء/بيع {data.buy_sell_ratio_m5:.2f}، "
        f"{data.buys_m5} عملية شراء (مصدر: {data.source})"
    )


async def check_momentum(mint_address: str, chain: str = "solana") -> tuple[bool, str]:
    """نقطة الدخول الرئيسية: يجلب البيانات ويُقيّمها في خطوة واحدة."""
    data = await fetch_momentum_data(mint_address, chain)
    if not data:
        return False, "تعذّر الحصول على أي بيانات زخم من أي مصدر"
    return evaluate_momentum(data)
