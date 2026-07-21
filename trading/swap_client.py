"""
دوال مشتركة لبناء وتوقيع وإرسال معاملات swap فعلية عبر Jupiter Swap API.
تُستخدم من trading/executor.py لكل من الشراء والبيع (عادي وطارئ).
"""
import asyncio
import base64
import logging
import time

import aiohttp
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

from config.settings import WALLET_PRIVATE_KEY, JUPITER_API_BASE, JUPITER_API_KEY
from utils.solana_rpc import rpc_call

logger = logging.getLogger("swap_executor")

JUPITER_QUOTE_API = f"{JUPITER_API_BASE}/swap/v1/quote"
JUPITER_SWAP_API = f"{JUPITER_API_BASE}/swap/v1/swap"
SOL_MINT_ADDRESS = "So11111111111111111111111111111111111111112"


def _jupiter_headers() -> dict:
    return {"x-api-key": JUPITER_API_KEY} if JUPITER_API_KEY else {}


def load_wallet_keypair() -> Keypair:
    """
    يحمّل مفتاح المحفظة من WALLET_PRIVATE_KEY (نص base58 قياسي لمحافظ Solana).
    يرمي استثناءً واضحاً إذا كان المفتاح غير مهيأ — حماية من التشغيل بالخطأ
    بدون محفظة فعلية (خصوصاً في مرحلة Devnet/الاختبار الأولي).
    """
    if not WALLET_PRIVATE_KEY:
        raise RuntimeError(
            "WALLET_PRIVATE_KEY غير مهيأ في .env — لا يمكن توقيع أي معاملة بدونه. "
            "تأكد من اختبار كامل على Devnet قبل إضافة مفتاح حقيقي."
        )
    return Keypair.from_base58_string(WALLET_PRIVATE_KEY)


class _JupiterRateLimiter:
    """
    محدِّد معدل عام مشترك بين **كل** استدعاءات Jupiter في المشروع بأكمله
    (فحوصات الأمان، مراقبة الصفقات، التنفيذ الفعلي) — بدل أن يستدعي كل
    جزء من الكود Jupiter بشكل مستقل، مما يُنتج انفجاراً في عدد الطلبات
    عند تزامن عدة صفقات مفتوحة معاً (رأينا فعلياً 76% معدل فشل بسبب هذا).
    نضمن هنا فاصلاً زمنياً أدنى بين أي طلبين متتاليين، بغض النظر عن مصدرهما.
    """
    def __init__(self, min_interval_seconds: float = 1.2):
        self.min_interval = min_interval_seconds
        self._lock = asyncio.Lock()
        self._last_call_time = 0.0

    async def wait(self):
        async with self._lock:
            now = time.time()
            elapsed = now - self._last_call_time
            if elapsed < self.min_interval:
                await asyncio.sleep(self.min_interval - elapsed)
            self._last_call_time = time.time()


_jupiter_rate_limiter = _JupiterRateLimiter(min_interval_seconds=1.2)


async def get_jupiter_quote(input_mint: str, output_mint: str, amount: int, slippage_bps: int) -> dict:
    """يستعلم عن أفضل مسار تبادل متاح حالياً عبر Jupiter."""
    await _jupiter_rate_limiter.wait()
    params = {
        "inputMint": input_mint,
        "outputMint": output_mint,
        "amount": amount,
        "slippageBps": slippage_bps,
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(
            JUPITER_QUOTE_API, params=params, headers=_jupiter_headers(), timeout=10
        ) as resp:
            if resp.status != 200:
                raise RuntimeError(f"فشل الحصول على quote من Jupiter: status {resp.status}")
            return await resp.json()


async def get_wallet_token_balance(wallet_pubkey: str, mint_address: str) -> int:
    """
    يقرأ الرصيد الفعلي (بأصغر وحدة، أي raw amount وليس decimal) لعملة معينة
    في محفظة معينة، عبر getTokenAccountsByOwner مع فلترة حسب mint.
    يرجع صفراً إذا لم يوجد حساب توكن مطابق (المحفظة لا تملك هذه العملة).
    """
    result = await rpc_call(
        "getTokenAccountsByOwner",
        [wallet_pubkey, {"mint": mint_address}, {"encoding": "jsonParsed"}],
    )
    accounts = result.get("value", []) if result else []
    if not accounts:
        return 0

    total = 0
    for acc in accounts:
        parsed = acc["account"]["data"]["parsed"]["info"]["tokenAmount"]
        total += int(parsed["amount"])
    return total


async def build_and_send_swap(
    input_mint: str,
    output_mint: str,
    amount: int,
    slippage_bps: int,
) -> tuple[str, dict]:
    """
    ينفّذ swap فعلياً بالخطوات الكاملة:
    1. طلب quote من Jupiter
    2. طلب معاملة swap جاهزة (serialized) من Jupiter Swap API
    3. توقيعها بمفتاح المحفظة المحلي
    4. إرسالها فعلياً على الشبكة عبر RPC

    يرجع (tx_signature, quote_data) — quote_data مفيد لاستخراج outAmount الفعلي.
    """
    keypair = load_wallet_keypair()
    wallet_pubkey = str(keypair.pubkey())

    quote = await get_jupiter_quote(input_mint, output_mint, amount, slippage_bps)
    if "outAmount" not in quote:
        raise RuntimeError(f"لا يوجد مسار swap متاح حالياً: {quote}")

    swap_payload = {
        "quoteResponse": quote,
        "userPublicKey": wallet_pubkey,
        "wrapAndUnwrapSol": True,
        "dynamicComputeUnitLimit": True,
        "prioritizationFeeLamports": "auto",
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(JUPITER_SWAP_API, json=swap_payload, headers=_jupiter_headers(), timeout=15) as resp:
            if resp.status != 200:
                raise RuntimeError(f"فشل بناء معاملة swap من Jupiter: status {resp.status}")
            swap_data = await resp.json()

    swap_tx_b64 = swap_data.get("swapTransaction")
    if not swap_tx_b64:
        raise RuntimeError(f"استجابة Jupiter لا تحتوي swapTransaction: {swap_data}")

    raw_tx_bytes = base64.b64decode(swap_tx_b64)
    unsigned_tx = VersionedTransaction.from_bytes(raw_tx_bytes)

    # توقيع المعاملة بمفتاح المحفظة المحلي
    signed_tx = VersionedTransaction(unsigned_tx.message, [keypair])
    signed_tx_b64 = base64.b64encode(bytes(signed_tx)).decode("utf-8")

    # إرسال المعاملة الموقّعة فعلياً على الشبكة
    signature = await rpc_call(
        "sendTransaction",
        [signed_tx_b64, {"encoding": "base64", "skipPreflight": False, "maxRetries": 3}],
    )

    logger.info(f"تم إرسال معاملة swap بنجاح: {signature}")
    return signature, quote


async def simulate_swap_transaction(
    input_mint: str, output_mint: str, amount: int, slippage_bps: int
) -> dict:
    """
    يبني معاملة swap ويحاكيها (simulateTransaction) دون إرسالها فعلياً —
    يُستخدم اختيارياً للتحقق قبل الإرسال الحقيقي في حالات حساسة.
    """
    keypair = load_wallet_keypair()
    wallet_pubkey = str(keypair.pubkey())

    quote = await get_jupiter_quote(input_mint, output_mint, amount, slippage_bps)
    swap_payload = {
        "quoteResponse": quote,
        "userPublicKey": wallet_pubkey,
        "wrapAndUnwrapSol": True,
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(JUPITER_SWAP_API, json=swap_payload, headers=_jupiter_headers(), timeout=15) as resp:
            swap_data = await resp.json()

    raw_tx_bytes = base64.b64decode(swap_data["swapTransaction"])
    unsigned_tx = VersionedTransaction.from_bytes(raw_tx_bytes)
    signed_tx = VersionedTransaction(unsigned_tx.message, [keypair])
    signed_tx_b64 = base64.b64encode(bytes(signed_tx)).decode("utf-8")

    result = await rpc_call(
        "simulateTransaction",
        [signed_tx_b64, {"encoding": "base64", "sigVerify": False}],
    )
    return result
