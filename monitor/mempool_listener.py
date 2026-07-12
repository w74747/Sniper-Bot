"""
الاستماع لأحداث إطلاق سيولة جديدة (تهيئة pool جديد على Raydium/Pump.fun)
عبر Alchemy WebSocket، ثم تشغيل كل الفلاتر
بالترتيب: كلمات محظورة → on-chain → سمعة/GoPlus → محاكاة بيع.

عند اجتياز كل الفلاتر: إضافة العملة إلى watchlist (وليس شراء فوري) —
حسب الاستراتيجية المتفق عليها.
"""
import asyncio
import json
import logging
from typing import Optional

import websockets

from config.settings import PRIMARY_WS_URL, DEX_ALLOWLIST
from filters.onchain_filters import (
    TokenMetadata, run_all_onchain_filters, parse_spl_mint_account,
    KNOWN_BURN_ADDRESSES,
)
from monitor.watchlist import (
    WatchlistEntry, add_to_watchlist, init_watchlist_table, is_already_in_watchlist,
)
from db.trades import has_seen_mint_before, record_screening_result
from utils.solana_rpc import (
    get_account_info_base64, get_token_largest_accounts, rpc_call, get_transaction_via_helius,
)

logger = logging.getLogger("mempool_listener")

# عناوين البرامج المعروفة والثابتة على Solana Mainnet
PUMP_FUN_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
RAYDIUM_AMM_V4_PROGRAM_ID = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"

MONITORED_PROGRAM_IDS = [PUMP_FUN_PROGRAM_ID, RAYDIUM_AMM_V4_PROGRAM_ID]


def _get_all_instructions(tx_data: dict) -> list:
    """
    يجمع كل التعليمات القابلة للفحص من معاملة واحدة: التعليمات الأساسية
    (message.instructions) + التعليمات المتداخلة (meta.innerInstructions).

    هذا ضروري لأن الاستدعاء الفعلي لتعليمة Pump.fun/Raydium غالباً لا يكون
    تعليمة أساسية مباشرة، بل يُستدعى عبر برنامج وسيط (aggregator/router)
    كـ Cross-Program Invocation (CPI) — وهذا هو السبب الفعلي وراء فشل
    التحليل بصمت في كل المحاولات السابقة رغم نجاح جلب المعاملة نفسها.
    """
    instructions = list(tx_data.get("transaction", {}).get("message", {}).get("instructions", []))

    inner_instructions = tx_data.get("meta", {}).get("innerInstructions", [])
    for group in inner_instructions:
        instructions.extend(group.get("instructions", []))

    return instructions


def _extract_program_id(ix: dict, account_keys: list) -> str:
    """
    يستخرج عنوان البرنامج من تعليمة واحدة، متوافقاً مع صيغتي jsonParsed
    (حيث "programId" نص مباشر) والصيغة الخام "json" (حيث "programIdIndex"
    رقم فهرسة يحتاج البحث عنه في account_keys).
    """
    if "programId" in ix:
        return ix["programId"]

    idx = ix.get("programIdIndex")
    if idx is None or idx >= len(account_keys):
        return ""
    key = account_keys[idx]
    return key.get("pubkey") if isinstance(key, dict) else key


def _extract_instruction_accounts(ix: dict, account_keys: list) -> list:
    """
    يستخرج قائمة عناوين الحسابات المستخدمة في تعليمة واحدة، متوافقاً مع
    صيغتي jsonParsed (حيث "accounts" قائمة نصوص عناوين مباشرة) والصيغة
    الخام (حيث "accounts" قائمة أرقام فهرسة تحتاج البحث عنها في account_keys).
    """
    raw_accounts = ix.get("accounts", [])
    if not raw_accounts:
        return []

    if isinstance(raw_accounts[0], str):
        return raw_accounts

    resolved = []
    for idx in raw_accounts:
        if idx is None or idx >= len(account_keys):
            resolved.append("")
            continue
        key = account_keys[idx]
        resolved.append(key.get("pubkey") if isinstance(key, dict) else key)
    return resolved



def parse_pump_fun_create_instruction(tx_data: dict) -> Optional[dict]:
    """
    يحلل معاملة "create" من Pump.fun لاستخراج بيانات العملة الجديدة.

    بنية تعليمة "create" في Pump.fun (موثّقة علناً وثابتة نسبياً):
    الحسابات بالترتيب: [mint, mint_authority, bonding_curve,
    associated_bonding_curve, global, mpl_token_metadata, metadata,
    user (=المطور/الموقّع), system_program, token_program,
    associated_token_program, rent, event_authority, program]

    نبحث في transaction.message.instructions عن تعليمة موجّهة لبرنامج
    Pump.fun، ونستخرج account[0] كـ mint و account[7] كمطور (user).

    ملاحظة: هذا الترتيب مبني على IDL منشور علناً لـ Pump.fun، لكن أي
    تحديث مستقبلي من طرفهم للعقد قد يغيّر الترتيب — يُنصح بالتحقق دورياً
    عبر مقارنة الاستخراج مع بيانات معروفة (مثل موقع pump.fun نفسه).
    """
    try:
        message = tx_data["transaction"]["message"]
        account_keys = message["accountKeys"]
        all_instructions = _get_all_instructions(tx_data)

        for ix in all_instructions:
            program_id = _extract_program_id(ix, account_keys)
            if program_id != PUMP_FUN_PROGRAM_ID:
                continue

            ix_accounts = _extract_instruction_accounts(ix, account_keys)
            if len(ix_accounts) < 8:
                continue

            mint_address = ix_accounts[0]
            bonding_curve = ix_accounts[2]
            associated_bonding_curve = ix_accounts[3]
            deployer_wallet = ix_accounts[7]

            return {
                "mint_address": mint_address,
                "pool_address": bonding_curve,
                "deployer_wallet": deployer_wallet,
                "dex": "pump.fun",
                "lp_mint_address": None,  # Pump.fun لا يستخدم LP mint تقليدي (bonding curve)
                # مهم جداً: حساب bonding curve (وATA الخاص به) يملك تقريباً كل
                # العرض عند الإطلاق بتصميم Pump.fun نفسه — آمن ومتوقع تماماً
                # (العقد يديره، وليس المطور). يجب استثناؤه من حساب "أكبر حامل"،
                # وإلا نرفض كل عملة Pump.fun تقريباً خطأً بدون سبب حقيقي.
                "known_lp_token_accounts": [associated_bonding_curve],
            }
    except (KeyError, IndexError, TypeError) as e:
        logger.debug(f"فشل تحليل معاملة Pump.fun: {e}")

    return None


def parse_raydium_initialize_instruction(tx_data: dict) -> Optional[dict]:
    """
    يحلل معاملة "initialize2" من Raydium AMM V4 لاستخراج بيانات الـ pool الجديد.

    تحذير صريح: بنية حسابات Raydium initialize2 أكثر تعقيداً وتغيّراً من
    Pump.fun (18+ حساباً بترتيب دقيق يشمل: amm, amm_authority,
    amm_open_orders, lp_mint, coin_mint, pc_mint, coin_vault, pc_vault...).
    المواقع أدناه (lp_mint_index, coin_mint_index) هي **تقدير أولي غير
    مُختبر على معاملة حقيقية فعلياً** — يجب التحقق منها بمقارنة مع معاملة
    Raydium حقيقية معروفة (عبر Solscan مثلاً) قبل الاعتماد عليها في
    قرارات شراء فعلية بأموال حقيقية.

    TODO حرج قبل الاستخدام الحقيقي: تحقق يدوياً من هذه المواقع بفحص
    معاملة "initialize2" حقيقية على solscan.io وتأكيد أي حساب هو فعلاً
    lp_mint وأيها coin_mint (العملة الجديدة).
    """
    try:
        message = tx_data["transaction"]["message"]
        account_keys = message["accountKeys"]
        all_instructions = _get_all_instructions(tx_data)

        for ix in all_instructions:
            program_id = _extract_program_id(ix, account_keys)
            if program_id != RAYDIUM_AMM_V4_PROGRAM_ID:
                continue

            ix_accounts = _extract_instruction_accounts(ix, account_keys)
            if len(ix_accounts) < 10:
                continue

            # TODO: هذه المواقع تقديرية — تحتاج تأكيداً على معاملة حقيقية
            amm_address = ix_accounts[4]
            lp_mint = ix_accounts[7]
            coin_mint = ix_accounts[8]  # العملة الجديدة المفترضة (غير مؤكدة)

            logger.warning(
                "تحليل Raydium initialize2 يستخدم مواقع حسابات غير مُختبرة بعد — "
                "راجع TODO في parse_raydium_initialize_instruction قبل الاعتماد عليه"
            )

            return {
                "mint_address": coin_mint,
                "pool_address": amm_address,
                "lp_mint_address": lp_mint,
                "deployer_wallet": "",  # يحتاج تحديداً إضافياً من fee payer المعاملة
                "dex": "raydium",
            }
    except (KeyError, IndexError, TypeError) as e:
        logger.debug(f"فشل تحليل معاملة Raydium: {e}")

    return None


async def fetch_token_metadata(pool_event: dict) -> TokenMetadata:
    """
    يبني TokenMetadata فعلياً من بيانات الحدث + استعلامات RPC حقيقية:
    1. getAccountInfo على mint address → فك تشفير mint_authority/freeze_authority/supply
    2. getTokenLargestAccounts على mint address → حساب نسبة محفظة المطور وأكبر حامل
    3. getTokenLargestAccounts على lp_mint_address (إن توفر) → نسبة حرق/قفل السيولة

    ملاحظة مهمة: pool_event يجب أن يحتوي على الحقول التالية (تُملأ من
    run_mempool_listener عند فك تشفير حدث إنشاء الـ pool):
    mint_address, symbol, name, description, deployer_wallet, lp_mint_address
    """
    mint_address = pool_event["mint_address"]

    # 1) قراءة حالة العقد الأساسية (mint/freeze authority + supply)
    mint_data_b64 = await get_account_info_base64(mint_address)
    mint_info = parse_spl_mint_account(mint_data_b64)

    # 2) توزيع الحيازة: أكبر الحاملين لهذه العملة
    # ملاحظة: بعض عملات Pump.fun الحديثة تُصدَر عبر برنامج Token-2022، وقد
    # يرفضها getTokenLargestAccounts بخطأ "not a Token mint" رغم أنها عملة
    # صالحة فعلياً. نتعامل مع هذا بأمان (fail-safe): لا نُسقط العملة بخطأ
    # تقني، لكن أيضاً لا نفترض توزيعاً "نظيفاً" (0%) — بل نضع قيماً تجعل
    # الفلاتر اللاحقة ترفضها لعدم القدرة على التحقق، اتساقاً مع مبدأ
    # "الرفض عند عدم اليقين" المتبع في بقية المشروع.
    try:
        largest_accounts = await get_token_largest_accounts(mint_address)
        holder_data_available = True
    except Exception as e:
        logger.warning(
            f"تعذّر قراءة توزيع الحيازة لـ {mint_address} (قد تكون Token-2022): {e}"
        )
        largest_accounts = []
        holder_data_available = False

    total_supply = mint_info["supply"] or 1  # تجنب القسمة على صفر

    deployer_wallet = pool_event.get("deployer_wallet", "")
    dev_wallet_pct = 0.0
    top_holder_pct_excluding_lp = 0.0
    lp_ata_addresses = set(pool_event.get("known_lp_token_accounts", []))

    for holder in largest_accounts:
        amount = float(holder.get("amount", 0))
        pct = (amount / total_supply) * 100 if total_supply else 0
        address = holder.get("address", "")

        if address in lp_ata_addresses:
            continue  # نتجاهل حسابات السيولة نفسها عند حساب "أكبر حامل فردي"

        if address == deployer_wallet:
            dev_wallet_pct = max(dev_wallet_pct, pct)

        top_holder_pct_excluding_lp = max(top_holder_pct_excluding_lp, pct)

    # 3) نسبة حرق/قفل السيولة — عبر فحص أكبر حاملي عملة الـ LP (إن توفر عنوانها)
    lp_burned_or_locked_pct = 0.0
    lp_mint_address = pool_event.get("lp_mint_address")
    if lp_mint_address:
        try:
            lp_largest = await get_token_largest_accounts(lp_mint_address)
            lp_total = sum(float(h.get("amount", 0)) for h in lp_largest) or 1
            burned_amount = sum(
                float(h.get("amount", 0))
                for h in lp_largest
                if h.get("address") in KNOWN_BURN_ADDRESSES
            )
            lp_burned_or_locked_pct = (burned_amount / lp_total) * 100
        except Exception as e:
            logger.warning(f"تعذّر فحص حرق LP لـ {mint_address}: {e}")
    else:
        logger.debug(
            f"لا يوجد lp_mint_address لـ {mint_address} — "
            f"لا يمكن التحقق من حرق السيولة، سيُرفض لاحقاً عبر الفلتر"
        )

    return TokenMetadata(
        mint_address=mint_address,
        name=pool_event.get("name", ""),
        symbol=pool_event.get("symbol", ""),
        description=pool_event.get("description", ""),
        dex=pool_event.get("dex", ""),
        total_supply=total_supply,
        mint_authority_active=mint_info["mint_authority_active"],
        freeze_authority_active=mint_info["freeze_authority_active"],
        lp_burned_or_locked_pct=lp_burned_or_locked_pct,
        dev_wallet_pct=dev_wallet_pct,
        top_holder_pct_excluding_lp=top_holder_pct_excluding_lp,
        holder_data_available=holder_data_available,
        is_standard_spl_token=True,  # مضمون طالما نجح فك تشفير SPL Mint القياسي
        has_transfer_restriction_hooks=False,  # TODO: فحص Token-2022 transfer hooks إن وُجدت
        has_referral_or_commission_function=False,  # يحتاج تحليل bytecode العقد (خارج نطاق RPC البسيط)
    )


async def process_new_pool_event(pool_event: dict):
    dex = pool_event.get("dex", "").lower()
    if dex not in DEX_ALLOWLIST:
        return  # تجاهل صامت — منصة غير مدرجة في القائمة المسموحة

    mint_address = pool_event.get("mint_address", "")

    # فحص عدم التكرار: هل رأينا هذه العملة من قبل (صفقة سابقة أو في watchlist)؟
    # هذا يمنع "نسيان" قرارات سابقة عند تكرار حدث من الشبكة أو إعادة تشغيل البوت.
    if await has_seen_mint_before(mint_address) or await is_already_in_watchlist(mint_address):
        logger.debug(f"تجاهل {mint_address} — تم رصدها/التعامل معها من قبل")
        return

    try:
        meta = await fetch_token_metadata(pool_event)
    except Exception as e:
        # مبدأ fail-safe: أي فشل في قراءة بيانات العقد = تجاهل العملة، وليس قبولها
        logger.warning(f"تعذّر قراءة بيانات العقد لـ {pool_event.get('mint_address')}: {e}")
        return

    # المرحلة 1: الفلاتر الآلية الفورية (كلمات + عرض + توزيع + قابلية تحويل)
    # هذه فقط تعتمد على بيانات on-chain مباشرة، فلا تعاني من فارق الفهرسة.
    onchain_result = run_all_onchain_filters(meta)
    if not onchain_result.passed:
        logger.info(f"رفض {meta.symbol}: {onchain_result.reason}")
        await record_screening_result(
            mint_address, meta.symbol, dex, "rejected", "onchain", onchain_result.reason
        )
        return

    # ملاحظة معمارية مهمة: فحص GoPlus ومحاكاة البيع لا يُشغَّلان هنا إطلاقاً.
    # عملة عمرها ثوانٍ لا تملك GoPlus بيانات كافية عنها بعد (يفشل الفحص دائماً
    # تقريباً بسبب فارق الفهرسة، وليس بسبب جودة العملة الفعلية) — هذا يتناقض
    # مع استراتيجيتنا الأصلية (انتظار 24-72 ساعة قبل القرار النهائي). لذلك
    # نضيف العملة لـ watchlist بمجرد اجتياز الفلاتر الآلية فقط، ونؤجّل فحص
    # GoPlus/محاكاة البيع إلى monitor/watchlist.py حيث تُفحصان عند انتهاء
    # فترة الانتظار الدنيا، حين تكون بياناتهما متوفرة فعلياً وذات معنى حقيقي.
    await record_screening_result(
        mint_address, meta.symbol, dex, "added_to_watchlist", "onchain_passed",
        f"اجتازت الفلاتر الآلية: {onchain_result.reason} — بانتظار فحص GoPlus/البيع لاحقاً"
    )

    await add_to_watchlist(WatchlistEntry(
        mint_address=meta.mint_address,
        symbol=meta.symbol,
        pool_address=pool_event.get("pool_address", ""),
        dex=dex,
        deployer_wallet=pool_event.get("deployer_wallet", ""),
        initial_filter_report=json.dumps({
            "onchain": onchain_result.reason,
        }, ensure_ascii=False),
    ))


async def fetch_and_parse_transaction(signature: str) -> Optional[dict]:
    """
    يجلب معاملة كاملة عبر توقيعها، ويحاول تحليلها كحدث Pump.fun أو Raydium.
    يرجع pool_event جاهزاً لـ process_new_pool_event، أو None إذا لم يُتعرّف عليها.
    """
    try:
        tx_data = await get_transaction_via_helius(signature)
    except Exception as e:
        logger.debug(f"تعذّر جلب المعاملة {signature}: {e}")
        return None

    if not tx_data:
        logger.info(f"⚠️ getTransaction رجع فارغاً (None) لـ {signature[:16]}...")
        return None

    event = parse_pump_fun_create_instruction(tx_data)
    if event:
        return event

    event = parse_raydium_initialize_instruction(tx_data)
    if event:
        return event

    # تشخيص مؤقت: لماذا فشلت كلتا المحاولتين؟ نطبع كل البرامج التي ظهرت فعلياً
    # في التعليمات (أساسية + متداخلة) لمقارنتها بعناوين البرامج التي نبحث عنها.
    try:
        message = tx_data["transaction"]["message"]
        account_keys = message["accountKeys"]
        all_instructions = _get_all_instructions(tx_data)

        program_ids_found = sorted(set(
            _extract_program_id(ix, account_keys) for ix in all_instructions
        ))
        logger.info(
            f"🔍 فشل التطابق لـ {signature[:16]}... — "
            f"عدد التعليمات: {len(all_instructions)}, "
            f"البرامج الموجودة فعلياً: {program_ids_found}"
        )
    except Exception as diag_error:
        logger.info(f"🔍 فشل التشخيص نفسه لـ {signature[:16]}...: {diag_error}")

    return None


async def _run_single_websocket_session():
    """
    جلسة اتصال واحدة — تُغلق تلقائياً عند أي انقطاع، ويلتقطها المستدعي لإعادة المحاولة.

    مهم: كل حدث مرشّح يُعالج في مهمة (Task) منفصلة تماماً عبر asyncio.create_task،
    بدل معالجته تسلسلياً داخل نفس الحلقة. هذا ضروري لأن المعالجة الكاملة لحدث
    واحد (Alchemy + GoPlus + Jupiter، مع احتمال إعادة محاولات) قد تستغرق ثوانٍ،
    ومعدل وصول الأحداث الفعلي على الشبكة أسرع من ذلك بكثير — فلو عالجنا تسلسلياً
    لتراكمت الأحداث في طابور غير مرئي وبدا الأمر وكأن شيئاً لا يحدث، رغم أن
    الكود يعمل، فقط ببطء شديد خلف الكواليس دون أي رسالة تدل على ذلك.

    نستخدم Semaphore لتحديد عدد المعالجات المتزامنة المسموحة (5 كحد أقصى)
    لتفادي إغراق Alchemy/GoPlus/Jupiter بطلبات متزامنة كثيرة جداً دفعة واحدة.
    """
    subscribe_id = 1
    pending_subscriptions = {}  # id -> program_id، لمطابقة كل رد تأكيد بالبرنامج الصحيح
    processing_semaphore = asyncio.Semaphore(5)
    background_tasks: set = set()

    async def _process_event_with_timing(signature: str):
        """
        يعالج حدثاً واحداً مع تسجيل التوقيت الكامل، ضمن حد التزامن المسموح.

        ملاحظة حرجة: نستخدم asyncio.wait_for بمهلة قصوى صارمة (45 ثانية) لأن
        بعض العمليات المتزامنة (blocking) مثل استدعاءات sqlite3 يمكن أن تُجمّد
        المعالجة بصمت تماماً بدون أي استثناء يظهر — هذا "شبكة أمان" تضمن ظهور
        نتيجة ما (نجاح/فشل/انتهاء مهلة) خلال وقت محدد مهما حدث، بدل الصمت الأبدي.
        """
        async with processing_semaphore:
            start_time = asyncio.get_event_loop().time()
            try:
                await asyncio.wait_for(_do_process(signature, start_time), timeout=45)
            except asyncio.TimeoutError:
                logger.error(
                    f"⏱️ انتهت المهلة القصوى (45s) لمعالجة {signature[:16]}... "
                    f"بدون أي استجابة — هذا يؤكد وجود تعليق فعلي (hang) في مكان ما"
                )
            except Exception as e:
                # حماية ضرورية: بدون هذا، أي استثناء داخل مهمة خلفية (Task) يُفقد
                # صامتاً تماماً في asyncio ولا يظهر في أي سجل إطلاقاً.
                logger.error(
                    f"خطأ غير متوقع أثناء معالجة {signature[:16]}...: "
                    f"{type(e).__name__}: {e} "
                    f"(بعد {asyncio.get_event_loop().time() - start_time:.1f}s)"
                )

    async def _do_process(signature: str, start_time: float):
        """الجسم الفعلي للمعالجة — مفصول لتسهيل تطبيق المهلة القصوى عليه بالكامل."""
        pool_event = await fetch_and_parse_transaction(signature)
        if pool_event:
            logger.info(
                f"تم استخراج بيانات عملة جديدة فعلياً: {pool_event.get('mint_address')} "
                f"(معالجة الاستخراج: {asyncio.get_event_loop().time() - start_time:.1f}s)"
            )
            await process_new_pool_event(pool_event)
            logger.info(
                f"انتهت المعالجة الكاملة لـ {signature[:16]}... "
                f"(الوقت الكلي: {asyncio.get_event_loop().time() - start_time:.1f}s)"
            )
        else:
            logger.debug(
                f"اجتاز الفلتر لكن فشل التحليل: {signature[:16]}... "
                f"({asyncio.get_event_loop().time() - start_time:.1f}s)"
            )

    async def _heartbeat_logger():
        """يطبع كل 15 ثانية عدد المهام قيد المعالجة حالياً — يوضح إن كان هناك تراكم (backlog) ضخم."""
        while True:
            await asyncio.sleep(15)
            logger.info(f"💓 نبضة: {len(background_tasks)} مهمة قيد المعالجة حالياً")

    async with websockets.connect(
        PRIMARY_WS_URL, ping_interval=20, ping_timeout=20
    ) as ws:
        heartbeat_task = asyncio.create_task(_heartbeat_logger())
        try:
            for program_id in MONITORED_PROGRAM_IDS:
                pending_subscriptions[subscribe_id] = program_id
                await ws.send(json.dumps({
                    "jsonrpc": "2.0",
                    "id": subscribe_id,
                    "method": "logsSubscribe",
                    "params": [
                        {"mentions": [program_id]},
                        {"commitment": "confirmed"},
                    ],
                }))
                subscribe_id += 1

            confirmed_count = 0
            expected_count = len(MONITORED_PROGRAM_IDS)

            async for message in ws:
                try:
                    data = json.loads(message)

                    # التحقق الصريح من ردود تأكيد/فشل الاشتراك (قبل بدء استقبال logs الفعلية)
                    if confirmed_count < expected_count and "id" in data and "params" not in data:
                        req_id = data.get("id")
                        program_id = pending_subscriptions.get(req_id, "غير معروف")
                        if "error" in data:
                            logger.error(
                                f"فشل الاشتراك في برنامج {program_id}: {data['error']}"
                            )
                        elif "result" in data:
                            logger.info(
                                f"نجح الاشتراك في برنامج {program_id} (subscription id: {data['result']})"
                            )
                        confirmed_count += 1
                        continue

                    if "params" not in data:
                        logger.debug(f"رسالة غير متوقعة من WebSocket تم تجاهلها: {message[:200]}")
                        continue

                    value = data["params"].get("result", {}).get("value", {})
                    signature = value.get("signature")
                    logs = value.get("logs", [])

                    if not signature:
                        continue

                    logs_text = " ".join(logs)
                    # فلترة دقيقة بنص التعليمة الفعلي وليس كلمة عامة — لأن "create"
                    # وحدها تظهر في أي معاملة عادية بسبب إنشاء ATA تلقائياً لكل عملية
                    is_pump_create = "Instruction: Create" in logs_text
                    is_raydium_init = "Instruction: Initialize2" in logs_text
                    if not is_pump_create and not is_raydium_init:
                        continue

                    logger.info(f"حدث مرشّح مكتشف: {signature[:16]}...")

                    # معالجة في مهمة منفصلة — لا ننتظرها هنا، لنستمر باستقبال الأحداث التالية فوراً
                    task = asyncio.create_task(_process_event_with_timing(signature))
                    background_tasks.add(task)
                    task.add_done_callback(background_tasks.discard)

                except Exception as e:
                    logger.error(f"خطأ في معالجة رسالة واحدة: {type(e).__name__}: {e}")
        finally:
            heartbeat_task.cancel()


async def run_mempool_listener():
    """
    يشترك فعلياً عبر logsSubscribe في Helius WebSocket لمراقبة أي معاملة
    تذكر برنامج Pump.fun أو Raydium AMM V4، ثم يجلب كل معاملة مطابقة
    كاملة عبر getTransaction لتحليلها واستخراج بيانات العملة الجديدة.

    مهم: عند خطأ HTTP 429 (تجاوز حد المعدل) تحديداً، نستخدم تأخيراً طويلاً
    جداً (يبدأ من 5 دقائق ويتصاعد حتى 30 دقيقة) بدل التأخير العادي (60 ثانية
    كحد أقصى) — لأن إعادة المحاولة السريعة المتكررة بعد 429 تُجدّد الحظر
    المؤقت من Helius باستمرار بدل الانتظار حتى ينتهي فعلياً، مما يُبقي
    الاتصال منقطعاً إلى ما لا نهاية (كما حدث فعلياً لمدة 5.5 ساعة متواصلة
    رُصدت في أحد اللوجات: نفس خطأ 429 كل 60 ثانية بدون أي نجاح).
    """
    await init_watchlist_table()
    logger.info("بدء الاستماع لأحداث السيولة الجديدة...")

    reconnect_delay = 5
    rate_limit_delay = 300  # 5 دقائق كبداية عند 429 تحديداً

    while True:
        try:
            await _run_single_websocket_session()
            reconnect_delay = 5  # نجح الاتصال ولو لفترة → نُعيد ضبط التأخير العادي
        except (websockets.exceptions.ConnectionClosed, ConnectionResetError) as e:
            logger.warning(f"انقطع اتصال WebSocket: {type(e).__name__}: {e} — إعادة الاتصال خلال {reconnect_delay}s")
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 60)
        except Exception as e:
            error_text = str(e)
            if "429" in error_text:
                logger.error(
                    f"⚠️ خطأ 429 (تجاوز حد المعدل) من مزود WebSocket ({PRIMARY_WS_URL[:40]}...) — "
                    f"إعادة الاتصال بعد "
                    f"تأخير طويل ({rate_limit_delay}s) لتفادي تجديد الحظر: {error_text}"
                )
                await asyncio.sleep(rate_limit_delay)
                rate_limit_delay = min(rate_limit_delay * 2, 1800)  # حتى 30 دقيقة كحد أقصى
            else:
                logger.error(f"خطأ غير متوقع في جلسة WebSocket: {type(e).__name__}: {e} — إعادة الاتصال خلال {reconnect_delay}s")
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 60)
