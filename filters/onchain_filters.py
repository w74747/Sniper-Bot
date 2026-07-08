"""
الفلاتر الآلية القابلة للفحص الفوري (اللحظة صفر):
1. آلية الانكماش/العرض (fixed supply + burn/lock)
2. عدم شبه بونزي في التوزيع (dev wallet %, holder concentration, referral mechanics)
3. قابلية الاستبدال والتحويل (standard token program, no transfer restrictions)
4. الفلترة اللغوية للاسم/الوصف

كل دالة هنا ترجع (passed: bool, reason: str) لتوضيح سبب القبول/الرفض بدقة.
"""
from dataclasses import dataclass
from typing import Optional

from config.settings import FILTERS


@dataclass
class TokenMetadata:
    """تمثيل مبسّط للبيانات التي نحتاجها من العقد. تُملأ عبر استعلامات RPC فعلية."""
    mint_address: str
    name: str
    symbol: str
    description: str = ""

    total_supply: float = 0
    mint_authority_active: bool = True   # هل ما زال بالإمكان طباعة عملات جديدة؟
    freeze_authority_active: bool = True  # هل يمكن تجميد محافظ المستخدمين؟

    lp_burned_or_locked_pct: float = 0.0
    dev_wallet_pct: float = 0.0
    top_holder_pct_excluding_lp: float = 0.0

    is_standard_spl_token: bool = True
    has_transfer_restriction_hooks: bool = False
    has_referral_or_commission_function: bool = False


@dataclass
class FilterResult:
    passed: bool
    reason: str
    stage: str


def check_forbidden_keywords(meta: TokenMetadata) -> FilterResult:
    """المستوى الأول: فلترة لغوية سريعة على الاسم والوصف والرمز."""
    text = f"{meta.name} {meta.symbol} {meta.description}".lower()
    for kw in FILTERS.forbidden_keywords:
        if kw in text:
            return FilterResult(False, f"احتوى المحتوى على كلمة محظورة: '{kw}'", "keyword_filter")
    return FilterResult(True, "لا توجد كلمات محظورة", "keyword_filter")


def check_supply_and_burn(meta: TokenMetadata) -> FilterResult:
    """التحقق من آلية الانكماش/العرض الثابت."""
    if FILTERS.require_fixed_supply and meta.mint_authority_active:
        return FilterResult(
            False,
            "صلاحية طباعة عملات جديدة (mint authority) ما زالت فعّالة — العرض غير ثابت",
            "supply_filter",
        )

    if FILTERS.require_burn_or_lock:
        if meta.lp_burned_or_locked_pct < FILTERS.min_lp_burned_or_locked_pct:
            return FilterResult(
                False,
                f"نسبة حرق/قفل السيولة {meta.lp_burned_or_locked_pct:.1f}% "
                f"أقل من الحد الأدنى المطلوب {FILTERS.min_lp_burned_or_locked_pct}%",
                "supply_filter",
            )

    return FilterResult(True, "العرض ثابت والسيولة محروقة/مقفلة بما يكفي", "supply_filter")


def check_distribution(meta: TokenMetadata) -> FilterResult:
    """التحقق من عدم شبه بونزي في التوزيع."""
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
    """التحقق من قابلية الاستبدال والتحويل الحر."""
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
    """يشغّل كل الفلاتر بالترتيب ويتوقف عند أول رفض (fail-fast) لتوفير الموارد."""
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
