"""
مستمع PumpPortal — مصدر اكتشاف أساسي للعملات الجديدة + مراقبة لحظية حقيقية
(WebSocket Push) لصفقاتنا المفتوحة تحديداً.

لماذا هذا مختلف جذرياً عن كل محاولاتنا السابقة مع مزودي RPC العامين
(Helius, Chainstack, Ankr, GetBlock, dRPC, Solana العام):

كل هؤلاء مزودو RPC عامون يخدمون كل استخدامات Solana لكل المطورين حول
العالم، ويتنافس عليهم الجميع لكل شيء — لذلك WebSocket لديهم يُعامَل
كميزة مكلفة/مدفوعة، وحتى HTTP العادي يصطدم بحدود معدل صارمة تحت الضغط.

PumpPortal (pumpportal.fun) مختلف تماماً: خدمة **مبنية خصيصاً لـPump.fun
فقط** كمنتج مستقل، توفر WebSocket **مجاني بالكامل** لأحداث "إنشاء عملة
جديدة" (subscribeNewToken)، **بالإضافة لبث لحظي حقيقي (<100ms) لكل عملية
بيع/شراء على عملة مُحدَّدة** (subscribeTokenTrade) — بتكلفة زهيدة جداً
(0.01 SOL لكل 10,000 حدث)، ونحن نراقب فقط صفقاتنا المفتوحة القليلة.

هذا يحل مشكلة جوهرية: المراقبة الدورية (كل 2-5 ثوانٍ) قد تفوت انهيار
سيولة مفاجئاً (بيع ضخم واحد) يحدث خلال أجزاء من الثانية. البث اللحظي
يُخبرنا **فور حدوثه فعلياً على السلسلة**، بدل انتظار الدورة القادمة —
فرق قد يكون حاسماً بين خروج بخسارة معقولة وخسارة شبه كاملة.
"""
import asyncio
import json
import logging
import time

import websockets
from solders.pubkey import Pubkey

from monitor.mempool_listener import process_new_pool_event
from config.settings import PUMPPORTAL_API_KEY

logger = logging.getLogger("pumpportal_listener")

# رابط الاتصال يتضمّن مفتاح API إن وُجد — مطلوب لتفعيل subscribeTokenTrade
# (المراقبة اللحظية المدفوعة). بدونه، يبقى subscribeNewToken (اكتشاف
# العملات الجديدة) يعمل مجاناً كما هو تماماً — فقط المراقبة اللحظية للصفقات
# المفتوحة تحديداً تتطلب المفتاح لتُفعَّل فعلياً.
PUMPPORTAL_WS_URL = (
    f"wss://pumpportal.fun/api/data?api-key={PUMPPORTAL_API_KEY}"
    if PUMPPORTAL_API_KEY else "wss://pumpportal.fun/api/data"
)

# عناوين برامج Solana القياسية والثابتة — لازمة لحساب عنوان "الحساب المرتبط"
# (Associated Token Account) الخاص بحساب bonding curve لعملة معيّنة، لأن
# رسالة PumpPortal لا ترسله مباشرة (فقط bondingCurveKey نفسه، وليس ATA الخاص به).
TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
ASSOCIATED_TOKEN_PROGRAM_ID = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")

# ── مراقبة لحظية حقيقية لصفقاتنا المفتوحة ──
# _ws_ref: مرجع قابل للتعديل للاتصال الحالي — تسمح لملفات أخرى (executor.py)
# بإرسال أوامر اشتراك/إلغاء اشتراك عبر نفس الاتصال الوحيد (بحسب توثيق
# PumpPortal: "لا تفتح اتصالاً جديداً لكل عملة — أرسل كل الاشتراكات لنفس الاتصال").
_ws_ref = {"ws": None}
_tracked_positions: dict = {}  # mint_address -> آخر قيمة SOL معروفة في bonding curve
LIQUIDITY_DRAIN_THRESHOLD_PCT = 25.0  # انخفاض 25%+ في معاملة واحدة = إنذار فوري


async def track_open_position(mint_address: str, initial_sol_in_curve: float = None):
    """
    يُستدعى فور نجاح شراء فعلي — يشترك في بث التداول اللحظي لهذه العملة
    تحديداً عبر نفس اتصال WebSocket الحالي (بدون فتح اتصال جديد).
    """
    if not PUMPPORTAL_API_KEY:
        logger.debug(
            f"لا يوجد PUMPPORTAL_API_KEY — تخطّي المراقبة اللحظية لـ {mint_address} "
            f"(الفحص الدوري العادي يبقى فعّالاً كمصدر وحيد)"
        )
        return

    _tracked_positions[mint_address] = initial_sol_in_curve or 0.0
    ws = _ws_ref.get("ws")
    if ws is not None:
        try:
            await ws.send(json.dumps({"method": "subscribeTokenTrade", "keys": [mint_address]}))
            logger.info(f"📡 بدأت المراقبة اللحظية (WebSocket) لـ {mint_address}")
        except Exception as e:
            logger.warning(f"تعذّر الاشتراك اللحظي لـ {mint_address} (سيستمر الفحص الدوري كاحتياطي): {e}")


async def untrack_open_position(mint_address: str):
    """يُستدعى عند إغلاق الصفقة — يُلغي الاشتراك في بث هذه العملة تحديداً."""
    _tracked_positions.pop(mint_address, None)
    ws = _ws_ref.get("ws")
    if ws is not None:
        try:
            await ws.send(json.dumps({"method": "unsubscribeTokenTrade", "keys": [mint_address]}))
        except Exception as e:
            logger.debug(f"تعذّر إلغاء الاشتراك اللحظي لـ {mint_address} (غير حرج): {e}")


async def _handle_trade_event(data: dict):
    """
    يُعالج حدث بيع/شراء لحظي لعملة مُتابَعة (صفقة مفتوحة لدينا). إن انخفض
    احتياطي SOL في bonding curve بنسبة كبيرة في معاملة واحدة (بيع ضخم مفاجئ)،
    يُطلق بيعاً طارئاً فورياً — بدل انتظار دورة الفحص الدورية القادمة.
    """
    mint_address = data.get("mint", "")
    if mint_address not in _tracked_positions:
        return

    current_vsol = float(data.get("vSolInBondingCurve", 0) or 0)
    previous_vsol = _tracked_positions.get(mint_address, 0.0)
    _tracked_positions[mint_address] = current_vsol

    if previous_vsol <= 0 or current_vsol <= 0:
        return

    drop_pct = ((previous_vsol - current_vsol) / previous_vsol) * 100
    if drop_pct < LIQUIDITY_DRAIN_THRESHOLD_PCT:
        return

    logger.warning(
        f"🚨 انهيار سيولة لحظي مكتشف عبر WebSocket لـ {mint_address}: "
        f"انخفض احتياطي SOL بنسبة {drop_pct:.1f}% في معاملة واحدة — تفعيل بيع طارئ فوري"
    )

    # استيراد محلي لتفادي أي استيراد دائري محتمل (executor.py قد يستورد من
    # هذا الملف لاحقاً لتفعيل track_open_position، فنُبقي هذا الاتجاه محلياً)
    from db import trades as db
    from trading.executor import execute_emergency_sell

    try:
        open_trades = await db.get_open_trades()
        matching_trade = next((t for t in open_trades if t["mint_address"] == mint_address), None)
        if matching_trade:
            await execute_emergency_sell(
                dict(matching_trade),
                f"انهيار سيولة لحظي مكتشف فوراً عبر WebSocket (انخفاض {drop_pct:.1f}% في معاملة واحدة)",
            )
            _tracked_positions.pop(mint_address, None)
    except Exception as e:
        logger.error(f"⚠️ فشل تنفيذ البيع الطارئ اللحظي لـ {mint_address}: {e}")


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
                _ws_ref["ws"] = ws
                await ws.send(json.dumps({"method": "subscribeNewToken"}))

                # إعادة الاشتراك في كل الصفقات المفتوحة حالياً بعد أي انقطاع/إعادة
                # اتصال — بدون هذا، ستفقد المراقبة اللحظية لصفقات مفتوحة بالفعل.
                for mint_addr in list(_tracked_positions.keys()):
                    await ws.send(json.dumps({"method": "subscribeTokenTrade", "keys": [mint_addr]}))

                logger.info("✅ اتصال PumpPortal ناجح — بانتظار عملات Pump.fun جديدة...")
                reconnect_delay = 5

                async for raw_message in ws:
                    try:
                        data = json.loads(raw_message)
                    except json.JSONDecodeError:
                        continue

                    tx_type = data.get("txType")

                    # حدث تداول لحظي (بيع/شراء) على عملة نُراقبها — فحص انهيار سيولة فوري
                    if tx_type in ("buy", "sell") and "mint" in data:
                        asyncio.create_task(_handle_trade_event(data))
                        continue

                    # أول رسالة عادة تأكيد الاشتراك نفسه، وليست حدث عملة — نتجاهلها بصمت
                    if tx_type != "create" or "mint" not in data:
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
            _ws_ref["ws"] = None
            logger.error(
                f"⚠️ انقطع اتصال PumpPortal: {type(e).__name__}: {e} — "
                f"إعادة الاتصال خلال {reconnect_delay}s"
            )
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 60)
