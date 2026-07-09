"""
الفلاتر الآلية القابلة للفحص الفوري (اللحظة صفر):
1. آلية الانكماش/العرض (fixed supply + burn/lock)
2. عدم شبه بونزي في التوزيع (dev wallet %, holder concentration, referral mechanics)
3. قابلية الاستبدال والتحويل (standard token program, no transfer restrictions)
4. الفلترة اللغوية للاسم/الوصف

كل دالة هنا ترجع (passed: bool, reason: str) لتوضيح سبب القبول/الرفض بدقة.
"""
import base64
import struct
from dataclasses import dataclass
from typing import Optional

from config.settings import FILTERS

SPL_MINT_ACCOUNT_LEN = 82

KNOWN_BURN_ADDRESSES = {
    "11111111111111111111111111111111",
    "1nc1nerator11111111111111111111111111111",
}


def parse_spl_mint_account(base64_data: str) -> dict:
    raw = base64.b64decode(base64_data)
    if len(raw) < SPL_MINT_ACCOUNT_LEN:
        raise ValueError(f"بيانات حساب Mint أقصر من المتوقع: {len(raw)} بايت")

    mint_authority_tag = struct.unpack_from("<I", raw, 0)[0]
    supply = struct.unpack_from("<Q", raw, 36)[0]
    decimals = raw[44]
    is_initialized = bool(raw[45])
    freeze_authority_tag = struct.unpack_from("<I", raw, 46)[0]

    return {
        "mint_authority_active": mint_authority_tag == 1,
        "freeze_authority_active": freeze_authority_tag == 1,
        "supply": supply,
        "decimals": decimals,
        "is_initialized": is_initialized,
    }


@dataclass
class TokenMetadata:
    """تمثيل مبسّط للبيانات التي نحتاجها من العقد. تُملأ عبر استعلامات RPC فعلية."""
    mint_address: str
    name: str
    symbol: str
    description: str = ""
    dex: str = ""

    total_supply: float = 0
    mint_authority_active: bool = True
    freeze_authority_active: bool = True

    lp_burned_or_locked_pct: float = 0.0
    dev_wallet_pct: float = 0.0
    top_holder_pct_excluding_lp: float = 0.0
    holder_data_available: bool = True  # False إذا تعذّرت قراءة التوزيع (مثل Token-2022)

    is_standard_spl_token: bool = True
    has_transfer_restriction_hooks: bool = False
    has_referral_or_commission_function: bool = False


@dataclass
class FilterResult:
    passed: bool
    reason: str
    stage: str


def check_forbidden_keywords(meta: TokenMetadata) -> FilterResult:
    text = f"{meta.name} {meta.symbol} {meta.description}".lower()
    for kw in FILTERS.forbidden_keywords:
        if kw in text:
            return FilterResult(False, f"احتوى المحتوى على كلمة محظورة: '{kw}'", "keyword_filter")
    return FilterResult(True, "لا توجد كلمات محظورة", "keyword_filter")


def check_supply_and_burn(meta: TokenMetadata) -> FilterResult:
    """
    ملاحظة مهمة لـ Pump.fun: السيولة محبوسة داخل Bonding Curve، لا LP تقليدية
    قابلة للحرق. نتجاوز شرط "حرق LP" لعملات Pump.fun، ونُبقيه صارماً لـ Raydium.
    """
    if FILTERS.require_fixed_supply and meta.mint_authority_active:
        return FilterResult(
            False,
            "صلاحية طباعة عملات جديدة (mint authority) ما زالت فعّالة — العرض غير ثابت",
            "supply_filter",
        )

    is_pump_fun = meta.dex.lower() == "pump.fun"

    if FILTERS.require_burn_or_lock and not is_pump_fun:
        if meta.lp_burned_or_locked_pct < FILTERS.min_lp_burned_or_locked_pct:
            return FilterResult(
                False,
                f"نسبة حرق/قفل السيولة {meta.lp_burned_or_locked_pct:.1f}% "
                f"أقل من الحد الأدنى المطلوب {FILTERS.min_lp_burned_or_locked_pct}%",
                "supply_filter",
            )

    return FilterResult(True, "العرض ثابت والسيولة محروقة/مقفلة بما يكفي (أو غير منطبق لـ Pump.fun)", "supply_filter")


def check_distribution(meta: TokenMetadata) -> FilterResult:
    """
    ملاحظة: عندما تتعذّر قراءة توزيع الحيازة فعلياً (holder_data_available=False،
    غالباً بسبب Token-2022)، لا نرفض تلقائياً بافتراض "100% ملكية مطور" —
    بل نتخطى فحص النسب هنا ونعتمد على GoPlus كشبكة أمان بديلة.
    """
    if not meta.holder_data_available:
        if FILTERS.forbid_referral_mechanics and meta.has_referral_or_commission_function:
            return FilterResult(
                False,
                "العقد يحتوي على آلية إحالة/عمولة داخلية — مؤشر تصميم شبيه بالبونزي",
                "distribution_filter",
            )
        return FilterResult(
            True,
            "تعذّرت قراءة توزيع الحيازة تقنياً (Token-2022) — الاعتماد على GoPlus كفحص بديل",
            "distribution_filter",
        )

    if meta.dev_wallet_pct > FILTERS.max_dev_wallet_pct:
        return FilterResult(
            False,
            f"محفظة المطور تملك {meta.dev_wallet_pct:.1f}% من العرض "
            f"(الحد الأقصى المسموح {FILTERS.max_dev_wallet_pct}%)",
            "distribution_filter",
        )

    if meta.top_holder_pct_excluding_lp > FILTERS.max_single_holder_pct:
        return FilterResult(
            False,
            f"أكبر محفظة (غير LP) تملك {meta.top_holder_pct_excluding_lp:.1f}% من العرض "
            f"(الحد الأقصى المسموح {FILTERS.max_single_holder_pct}%)",
            "distribution_filter",
        )

    if FILTERS.forbid_referral_mechanics and meta.has_referral_or_commission_function:
        return FilterResult(
            False,
            "العقد يحتوي على آلية إحالة/عمولة داخلية — مؤشر تصميم شبيه بالبونزي",
            "distribution_filter",
        )

    return FilterResult(True, "التوزيع لا يظهر مؤشرات بونزي واضحة", "distribution_filter")


def check_fungibility_and_transferability(meta: TokenMetadata) -> FilterResult:
    if FILTERS.require_standard_token_program and not meta.is_standard_spl_token:
        return FilterResult(
            False,
            "العقد لا يتبع معيار SPL Token القياسي — قد يحتوي منطقاً مخصصاً غير موثوق",
            "fungibility_filter",
        )

    if FILTERS.forbid_transfer_restrictions and meta.has_transfer_restriction_hooks:
        return FilterResult(
            False,
            "العقد يحتوي على قيود نقل مخفية (blacklist/whitelist) قد تمنع البيع لاحقاً",
            "fungibility_filter",
        )

    if meta.freeze_authority_active:
        return FilterResult(
            False,
            "صلاحية تجميد المحافظ (freeze authority) ما زالت فعّالة — خطر honeypot",
            "fungibility_filter",
        )

    return FilterResult(True, "العملة قابلة للاستبدال والتحويل بحرية", "fungibility_filter")


def run_all_onchain_filters(meta: TokenMetadata) -> FilterResult:
    checks = [
        check_forbidden_keywords,
        check_supply_and_burn,
        check_distribution,
        check_fungibility_and_transferability,
    ]
    for check in checks:
        result = check(meta)
        if not result.passed:
            return result
    return FilterResult(True, "اجتازت العملة كل الفلاتر الآلية الفورية", "all_passed")
