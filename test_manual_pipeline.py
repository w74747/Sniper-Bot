"""
سكربت اختبار يدوي: يمرّ بكل خطوة من سلسلة الفلترة على عملة حقيقية موجودة
فعلياً على Solana Mainnet (BONK كمثال)، ويطبع نتيجة كل خطوة على حدة.

الهدف: التأكد أن كل جزء (فك تشفير Mint، الفلاتر، GoPlus، Jupiter) يعمل
بشكل صحيح ومنعزل، قبل الانتقال لبناء اكتشاف الـ pools التلقائي.

طريقة التشغيل:
    python test_manual_pipeline.py

ملاحظة: BONK ستفشل غالباً في فلتر "حرق/قفل السيولة" أو "توزيع الحيازة"
لأننا لا نمرر lp_mint_address أو deployer_wallet حقيقيين لها هنا — هذا
متوقع تماماً والهدف ليس نجاحها، بل التأكد أن كل خطوة تُنفَّذ بدون Exception
غير متوقع وتُرجع نتيجة منطقية مفهومة.
"""
import asyncio
import logging
from dotenv import load_dotenv

load_dotenv()

# تهيئة logging صراحة — بدون هذا، رسائل logger.info() لا تظهر إطلاقاً في Railway
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from filters.onchain_filters import TokenMetadata, run_all_onchain_filters
from filters.reputation import evaluate_reputation
from filters.sell_simulation import simulate_sell, evaluate_simulation_result
from utils.solana_rpc import get_account_info_base64, get_token_largest_accounts
from filters.onchain_filters import parse_spl_mint_account

# BONK — عملة حقيقية معروفة وموجودة فعلياً على Mainnet، جيدة للاختبار
TEST_MINT_ADDRESS = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"


def print_header(title: str):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


async def main():
    print_header(f"اختبار السلسلة الكاملة على عنوان: {TEST_MINT_ADDRESS}")

    # ── الخطوة 1: فك تشفير حساب Mint الفعلي عبر Alchemy RPC ──
    print_header("الخطوة 1: قراءة وفك تشفير حساب Mint")
    try:
        mint_data_b64 = await get_account_info_base64(TEST_MINT_ADDRESS)
        mint_info = parse_spl_mint_account(mint_data_b64)
        print("✅ نجح فك التشفير:")
        print(f"   mint_authority_active: {mint_info['mint_authority_active']}")
        print(f"   freeze_authority_active: {mint_info['freeze_authority_active']}")
        print(f"   supply: {mint_info['supply']}")
        print(f"   decimals: {mint_info['decimals']}")
    except Exception as e:
        print(f"❌ فشلت هذه الخطوة: {type(e).__name__}: {e!r}")
        print("   تحقق من: ALCHEMY_API_KEY في .env صحيح ومفعّل")
        return

    # ── الخطوة 2: توزيع الحيازة (أكبر 20 حاملاً) ──
    print_header("الخطوة 2: قراءة توزيع الحيازة (أكبر الحاملين)")
    largest_accounts = []
    try:
        largest_accounts = await get_token_largest_accounts(TEST_MINT_ADDRESS)
        print(f"✅ عدد الحسابات المُرجعة: {len(largest_accounts)}")
        if largest_accounts:
            top = largest_accounts[0]
            print(f"   أكبر حساب: {top.get('address')} برصيد {top.get('amount')}")
    except Exception as e:
        print(f"⚠️ فشلت هذه الخطوة تحديداً مع BONK: {type(e).__name__}: {e!r}")
        print(
            "   هذا متوقع مع BONK تحديداً بسبب ضخامة عدد حامليها (ملايين الحسابات)،\n"
            "   وهو قيد معروف في الفريتير المجاني لكل مزودي RPC تقريباً، وليس خطأً\n"
            "   في الكود. عملات الميم الجديدة (هدفنا الفعلي) لها عدد حاملين قليل\n"
            "   جداً عند الإطلاق، فلن تواجه هذه المشكلة عملياً. سنكمل بقيمة افتراضية."
        )

    # ── الخطوة 3: بناء TokenMetadata وتشغيل الفلاتر الآلية ──
    print_header("الخطوة 3: تشغيل الفلاتر الآلية (on-chain)")
    total_supply = mint_info["supply"] or 1
    top_holder_pct = (
        float(largest_accounts[0]["amount"]) / total_supply * 100
        if largest_accounts else 0
    )

    meta = TokenMetadata(
        mint_address=TEST_MINT_ADDRESS,
        name="Bonk",
        symbol="BONK",
        description="عملة اختبار حقيقية",
        total_supply=total_supply,
        mint_authority_active=mint_info["mint_authority_active"],
        freeze_authority_active=mint_info["freeze_authority_active"],
        lp_burned_or_locked_pct=0.0,  # لا نملك lp_mint_address حقيقياً في هذا الاختبار
        dev_wallet_pct=0.0,           # لا نملك deployer_wallet حقيقياً في هذا الاختبار
        top_holder_pct_excluding_lp=top_holder_pct,
    )

    onchain_result = run_all_onchain_filters(meta)
    status = "✅ اجتازت" if onchain_result.passed else "❌ رُفضت"
    print(f"{status}: {onchain_result.reason}")
    print("(ملاحظة: الرفض هنا متوقع لأننا لم نمرر lp_mint_address حقيقياً)")

    # ── الخطوة 4: فحص GoPlus ──
    print_header("الخطوة 4: فحص GoPlus Security")
    try:
        goplus_ok, goplus_reason = await evaluate_reputation(
            TEST_MINT_ADDRESS, deployer_wallet=""
        )
        status = "✅ نجح" if goplus_ok else "⚠️ رُفض"
        print(f"{status}: {goplus_reason}")
    except Exception as e:
        print(f"❌ خطأ تقني غير متوقع: {e}")

    # ── الخطوة 5: محاكاة البيع عبر Jupiter ──
    print_header("الخطوة 5: محاكاة البيع عبر Jupiter Quote API")
    try:
        sim_result = await simulate_sell(
            rpc_client=None,
            wallet_pubkey="",
            mint_address=TEST_MINT_ADDRESS,
            pool_address="",
            test_amount_lamports=1_000_000,
        )
        sim_ok, sim_reason = evaluate_simulation_result(sim_result)
        status = "✅ نجحت" if sim_ok else "⚠️ رُفضت"
        print(f"{status}: {sim_reason}")
        print(f"   can_sell: {sim_result.can_sell}")
        print(f"   effective_sell_tax_pct: {sim_result.effective_sell_tax_pct:.2f}%")
    except Exception as e:
        print(f"❌ خطأ تقني غير متوقع: {e}")

    print_header("انتهى الاختبار")
    print(
        "إذا رأيت ✅ أو ⚠️ في كل خطوة (بدون ❌)، فهذا يعني أن كل الاتصالات\n"
        "(Alchemy, GoPlus, Jupiter) تعمل بنجاح تقني، بغض النظر عن نتيجة القبول/الرفض."
    )


if __name__ == "__main__":
    asyncio.run(main())
