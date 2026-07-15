"""
سكربت تشخيصي آمن تماماً: يتحقق فقط من أن WALLET_PRIVATE_KEY محمَّل بصيغة
صحيحة، ويطبع العنوان العام (Public Address) المشتق منه — بدون أي معاملة
أو إنفاق حقيقي. قارن العنوان المطبوع هنا مع العنوان الظاهر في Phantom
للتأكد أنهما متطابقان تماماً قبل أي عملية شراء حقيقية.
"""
from trading.swap_client import load_wallet_keypair
from utils.solana_rpc import rpc_call
from config.settings import USE_DEVNET
import asyncio


async def main():
    print("=" * 60)
    print("اختبار تحميل المفتاح الخاص")
    print("=" * 60)

    try:
        keypair = load_wallet_keypair()
        public_address = str(keypair.pubkey())
        print(f"✅ نجح تحميل المفتاح بصيغة صحيحة")
        print(f"العنوان العام المشتق: {public_address}")
        print()
        print("قارن هذا العنوان مع العنوان الظاهر في تطبيق Phantom —")
        print("يجب أن يكونا متطابقين حرفياً بالضبط.")
    except Exception as e:
        print(f"❌ فشل تحميل المفتاح: {type(e).__name__}: {e}")
        return

    print()
    print("=" * 60)
    print("فحص الرصيد الفعلي عبر Solana RPC")
    print("=" * 60)
    try:
        result = await rpc_call("getBalance", [public_address])
        lamports = result.get("value", 0) if result else 0
        sol_balance = lamports / 1_000_000_000
        print(f"الرصيد الفعلي في هذه المحفظة: {sol_balance:.6f} SOL")
    except Exception as e:
        print(f"❌ فشل فحص الرصيد: {type(e).__name__}: {e}")

    print()
    print(f"USE_DEVNET الحالي: {USE_DEVNET}")
    if USE_DEVNET:
        print("⚠️ لا يزال USE_DEVNET=true — لن تُنفَّذ أي معاملة حقيقية حتى تُغيّره لـ false")


if __name__ == "__main__":
    asyncio.run(main())
