"""
مستمع PumpPortal — مصدر اكتشاف أساسي جديد لعملات Pump.fun الجديدة.

لماذا هذا مختلف جذرياً عن كل محاولاتنا السابقة مع مزودي RPC العامين
(Helius, Chainstack, Ankr, GetBlock, dRPC, Solana العام):

كل هؤلاء مزودو RPC عامون يخدمون كل استخدامات Solana لكل المطورين حول
العالم، ويتنافس عليهم الجميع لكل شيء — لذلك WebSocket لديهم يُعامَل
كميزة مكلفة/مدفوعة، وحتى HTTP العادي يصطدم بحدود معدل صارمة تحت الضغط.

PumpPortal (pumpportal.fun) مختلف تماماً: خدمة **مبنية خصيصاً لـPump.fun
فقط** كمنتج مستقل، توفر WebSocket **مجاني بالكامل** لأحداث "إنشاء عملة
جديدة" (subscribeNewToken) و"الترقية لـRaydium/PumpSwap" (subscribeMigration)
— بدون أي رسوم أو حدود معدل صارمة (فقط قواعد بديهية: اتصال واحد، لا تكرار
اشتراكات، وهذا لا ينطبق علينا لأننا نشترك مرة واحدة فقط ونُبقي الاتصال).

هذا يحل مشكلتين معاً:
1. اكتشاف فوري حقيقي (<100ms) بدل الاستقصاء كل 3 ثوانٍ.
2. يُرسل الاسم والرمز الحقيقيين مباشرة (كنا نفتقدهما تماماً سابقاً، ما
   عطّل فلتر الكلمات المحظورة الشرعية فعلياً منذ البداية).

المصدر: pumpportal.fun/data-api/real-time (موثّق رسمياً، ومصادر مستقلة
متعددة تؤكد صيغة البيانات وعدم الحاجة لمفتاح API لهذه الميزة المجانية تحديداً).
"""
import asyncio
import json
import logging

import websockets
from solders.pubkey import Pubkey

from monitor.mempool_listener import process_new_pool_event

logger = logging.getLogger("pumpportal_listener")

PUMPPORTAL_WS_URL = "wss://pumpportal.fun/api/data"

# عناوين برامج Solana القياسية والثابتة — لازمة لحساب عنوان "الحساب المرتبط"
# (Associated Token Account) الخاص بحساب bonding curve لعملة معيّنة، لأن
# رسالة PumpPortal لا ترسله مباشرة (فقط bondingCurveKey نفسه، وليس ATA الخاص به).
TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
ASSOCIATED_TOKEN_PROGRAM_ID = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")


def _derive_associated_bonding_curve(bonding_curve: str, mint: str) -> str:
    """
    يحسب عنوان ATA الخاص بحساب bonding curve لعملة معيّنة — نفس المشتقة
    القياسية لأي Associated Token Account على Solana. ضروري لاستثناء هذا
    الحساب من حساب "أكبر حامل" (نفس إصلاح Bonding Curve الذي بنيناه سابقاً).
    """
    try:
        bonding_curve_pk = Pubkey.from_string(bonding_curve)
        mint_pk = Pubkey.from_string(mint)
        derived, _ = Pubkey.find_program_address(
            [bytes(bonding_curve_pk), bytes(TOKEN_PROGRAM_ID), bytes(mint_pk)],
            ASSOCIATED_TOKEN_PROGRAM_ID,
        )
        return str(derived)
    except Exception as e:
        logger.warning(f"تعذّر حساب associated bonding curve: {e}")
        return ""


async def run_pumpportal_listener():
    """
    يتصل بـPumpPortal WebSocket ويشترك في أحداث "إنشاء عملة جديدة"، ويُغذّي
    كل حدث لنفس خط الفلترة الموجود (process_new_pool_event) — بدون أي
    تغيير على منطق الفلاتر نفسها، فقط مصدر اكتشاف أسرع وأدق وأكثر استقراراً.

    ملاحظة مهمة: نُحدّد التزامن بحد أقصى (Semaphore) — بدون هذا، كل عملة
    جديدة تُطلق معالجة فورية بلا قيد، وبما أن Pump.fun يُطلق عشرات العملات
    بسرعة، هذا كان يُسبب دفعات مفاجئة من عشرات طلبات RPC في نفس اللحظة
    (getAccountInfo لكل عملة)، تتجاوز حتى تناوب عدة مزودين معاً.
    """
    reconnect_delay = 5
    processing_semaphore = asyncio.Semaphore(5)
    background_tasks: set = set()

    async def _process_with_limit(event: dict):
        async with processing_semaphore:
            try:
                await process_new_pool_event(event)
            except Exception as e:
                logger.error(f"⚠️ خطأ غير متوقع في معالجة حدث PumpPortal: {type(e).__name__}: {e}")

    while True:
        try:
            async with websockets.connect(
                PUMPPORTAL_WS_URL, ping_interval=20, ping_timeout=20
            ) as ws:
                await ws.send(json.dumps({"method": "subscribeNewToken"}))
                logger.info("✅ اتصال PumpPortal ناجح — بانتظار عملات Pump.fun جديدة...")
                reconnect_delay = 5

                async for raw_message in ws:
                    try:
                        data = json.loads(raw_message)
                    except json.JSONDecodeError:
                        continue

                    # أول رسالة عادة تأكيد الاشتراك نفسه، وليست حدث عملة — نتجاهلها بصمت
                    if data.get("txType") != "create" or "mint" not in data:
                        continue

                    mint_address = data.get("mint", "")
                    bonding_curve = data.get("bondingCurveKey", "")
                    deployer_wallet = data.get("traderPublicKey", "")
                    name = data.get("name", "")
                    symbol = data.get("symbol", "")

                    associated_bonding_curve = _derive_associated_bonding_curve(bonding_curve, mint_address)

                    pool_event = {
                        "mint_address": mint_address,
                        "pool_address": bonding_curve,
                        "deployer_wallet": deployer_wallet,
                        "dex": "pump.fun",
                        "lp_mint_address": None,
                        "known_lp_token_accounts": [associated_bonding_curve] if associated_bonding_curve else [],
                        "name": name,
                        "symbol": symbol,
                    }

                    logger.info(f"🚀 [PumpPortal] عملة جديدة فعلياً: {symbol or '?'} ({mint_address})")
                    task = asyncio.create_task(_process_with_limit(pool_event))
                    background_tasks.add(task)
                    task.add_done_callback(background_tasks.discard)

        except Exception as e:
            logger.error(
                f"⚠️ انقطع اتصال PumpPortal: {type(e).__name__}: {e} — "
                f"إعادة الاتصال خلال {reconnect_delay}s"
            )
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 60)
