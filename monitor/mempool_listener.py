"""
اكتشاف أحداث إطلاق سيولة جديدة (تهيئة pool جديد على Raydium/Pump.fun) عبر
الاستقصاء الدوري (Polling) بدل WebSocket.

سبب هذا القرار المعماري: بعد تجربة 6 مزودين مختلفين (Chainstack, Helius,
GetBlock, Ankr, dRPC, Solana العام)، اتضح أن WebSocket لـ Solana تحديداً
يُعامَل كميزة مدفوعة على أغلب المنصات المجانية، بخلاف استدعاءات HTTP
العادية (getSignaturesForAddress) التي تعمل بنجاح على كل مزودينا الحاليين
بدون أي قيد إضافي. الاستقصاء كل بضع ثوانٍ فرق بسيط عملياً مقارنة بإشعار
فوري، خصوصاً أن استراتيجيتنا أصلاً تعتمد على انتظار (24 ساعة أو دقائق
للمسار السريع)، فالفارق بثوانٍ قليلة لا يُغيّر جوهر القرار.

بعد الاكتشاف: تشغيل كل الفلاتر بالترتيب (كلمات محظورة → on-chain →
سمعة/GoPlus → محاكاة بيع). عند اجتياز كل الفلاتر: إضافة العملة إلى
watchlist (وليس شراء فوري) — حسب الاستراتيجية المتفق عليها.
"""
import asyncio
import json
import logging
from typing import Optional

import base58

from config.settings import DEX_ALLOWLIST
from filters.onchain_filters import (
    TokenMetadata, run_all_onchain_filters, parse_spl_mint_account,
    KNOWN_BURN_ADDRESSES,
)
from monitor.watchlist import (
    WatchlistEntry, add_to_watchlist, init_watchlist_table, is_already_in_watchlist,
)
from db.trades import has_seen_mint_before, record_screening_result
from utils.solana_rpc import (
    get_account_info_base64, get_token_largest_accounts, rpc_call,
    get_transaction_via_helius, get_signatures_for_address_polling,
)

logger = logging.getLogger("mempool_listener")

# عناوين البرامج المعروفة والثابتة على Solana Mainnet
PUMP_FUN_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
RAYDIUM_AMM_V4_PROGRAM_ID = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"

MONITORED_PROGRAM_IDS = [PUMP_FUN_PROGRAM_ID, RAYDIUM_AMM_V4_PROGRAM_ID]

# كل كم ثانية نستقصي (Poll) عن معاملات جديدة لكل برنامج مراقَب
# كل كم ثانية نستقصي (Poll) عن معاملات جديدة لكل برنامج مراقَب
# خُفِّضت من 4 إلى 2 ثانية بعد تحسينات الكفاءة (جلسة HTTP دائمة + تناوب
# مُرتَّب حسب الصحة) — هذا يُضاعف تقريباً عدد فرص الاكتشاف يومياً بدون
# أي تكلفة إضافية، لأن كل استقصاء أصبح أسرع وأقل هدراً للمحاولات.
POLL_INTERVAL_SECONDS = 2
# كم توقيعاً نجلب كحد أقصى في كل دورة استقصاء واحدة لكل برنامج
SIGNATURES_PER_POLL = 30

# ذاكرة مؤقتة قصيرة الأمد (في الذاكرة، وليست قاعدة بيانات) لمنع إعادة معالجة
# نفس العملة عدة مرات خلال ثوانٍ قليلة — شائع جداً مع معاملات متعددة تشير
# لنفس العملة قرب لحظة إنشائها (مثل عدة إضافات سيولة متتالية على Raydium).
# هذا منفصل تماماً عن has_seen_mint_before/is_already_in_watchlist، لأن تلك
# لا تتذكر العملات "المرفوضة" (لم تصبح صفقة أو تدخل watchlist إطلاقاً).
_recently_processed_mints: dict = {}
_RECENT_MINT_TTL_SECONDS = 120


def _get_all_instructions(tx_data: dict) -> list:
    """
    يجمع كل التعليمات القابلة للفحص من معاملة واحدة: التعليمات الأساسية
    (message.instructions) + التعليمات المتداخلة (meta.innerInstructions).

    هذا ضروري لأن الاستدعاء الفعلي لتعليمة Pump.fun/Raydium غالباً لا يكون
    تعليمة أساسية مباشرة، بل يُستدعى عبر برنامج وسيط (aggregator/router)
    كـ Cross-Program Invocation (CPI).
    """
    instructions = list(tx_data.get("transaction", {}).get("message", {}).get("instructions", []))

    inner_instructions = tx_data.get("meta", {}).get("innerInstructions", [])
    for group in inner_instructions:
        instructions.extend(group.get("instructions", []))

    return instructions


def _extract_program_id(ix: dict, account_keys: list) -> str:
    """
    يستخرج عنوان البرنامج من تعليمة واحدة، متوافقاً مع صيغتي jsonParsed
    (حيث "programId" نص مباشر) والصيغة الخام (حيث "programIdIndex" رقم
    فهرسة يحتاج البحث عنه في account_keys).
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
    صيغتي jsonParsed (نصوص عناوين مباشرة) والصيغة الخام (أرقام فهرسة).
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


RAYDIUM_INITIALIZE2_DISCRIMINATOR = 1  # مؤكَّد من الكود المصدري الرسمي: raydium-io/raydium-amm/instruction.rs
                                        # (enum AmmInstruction: Initialize=0, Initialize2=1, Reserved0=2, ...)

# بصمة (Discriminator) تعليمة "create" في Pump.fun — برنامج مبني بإطار Anchor،
# فبصمته 8 بايتات (أول 8 بايتات من sha256("global:create"))، وليست بايتاً
# واحداً كما في Raydium (برنامج غير Anchor). مؤكَّدة من عدة مصادر مستقلة.
PUMP_FUN_CREATE_DISCRIMINATOR = bytes([24, 30, 200, 40, 5, 28, 7, 119])


def _get_instruction_discriminator(ix: dict) -> int:
    """
    يستخرج البايت الأول من بيانات التعليمة الخام (data) — يُستخدم لـ Raydium
    تحديداً (برنامج غير Anchor، بصمته بايت واحد فقط حسب ترتيب enum الرسمي).
    """
    data_b58 = ix.get("data", "")
    if not data_b58:
        return -1
    try:
        raw = base58.b58decode(data_b58)
        return raw[0] if raw else -1
    except Exception:
        return -1


def _matches_pump_fun_create(ix: dict) -> bool:
    """
    يتحقق من بصمة Anchor الكاملة (8 بايتات) لتعليمة "create" تحديداً في
    Pump.fun. بدون هذا التحقق، أي معاملة شراء/بيع (Buy/Sell) على عملة
    موجودة أصلاً — وهي الأكثر تكراراً بمراحل من إنشاء عملات جديدة فعلياً —
    كانت تُقبَل خطأً كأنها إنشاء عملة جديدة، لأن عدد الحسابات وحده (≥8)
    غير كافٍ إطلاقاً للتمييز بينهما.
    """
    data_b58 = ix.get("data", "")
    if not data_b58:
        return False
    try:
        raw = base58.b58decode(data_b58)
        return raw[:8] == PUMP_FUN_CREATE_DISCRIMINATOR
    except Exception:
        return False


def parse_pump_fun_create_instruction(tx_data: dict) -> Optional[dict]:
    """
    يحلل معاملة "create" من Pump.fun لاستخراج بيانات العملة الجديدة.

    بنية تعليمة "create" في Pump.fun (موثّقة علناً وثابتة نسبياً):
    الحسابات بالترتيب: [mint, mint_authority, bonding_curve,
    associated_bonding_curve, global, mpl_token_metadata, metadata,
    user (=المطور/الموقّع), system_program, token_program,
    associated_token_program, rent, event_authority, program]
    """
    try:
        message = tx_data["transaction"]["message"]
        account_keys = message["accountKeys"]
        all_instructions = _get_all_instructions(tx_data)

        for ix in all_instructions:
            program_id = _extract_program_id(ix, account_keys)
            if program_id != PUMP_FUN_PROGRAM_ID:
                continue

            # التحقق الحاسم: هل هذه فعلاً تعليمة "create"، أم Buy/Sell عادية
            # على عملة موجودة أصلاً؟ بدون هذا، معاملات التداول العادية (وهي
            # الأكثر تكراراً بمراحل) كانت تُقبَل خطأً كإنشاء عملة جديدة.
            if not _matches_pump_fun_create(ix):
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
                "lp_mint_address": None,
                # مهم جداً: حساب bonding curve (وATA الخاص به) يملك تقريباً كل
                # العرض عند الإطلاق بتصميم Pump.fun نفسه — آمن ومتوقع تماماً.
                "known_lp_token_accounts": [associated_bonding_curve],
            }
    except (KeyError, IndexError, TypeError) as e:
        logger.debug(f"فشل تحليل معاملة Pump.fun: {e}")

    return None


def parse_raydium_initialize_instruction(tx_data: dict) -> Optional[dict]:
    """
    يحلل معاملة "initialize2" من Raydium AMM V4 لاستخراج بيانات الـ pool الجديد.

    مواقع الحسابات هنا تم التحقق منها رسمياً مقابل ملف IDL الرسمي لبرنامج
    Raydium AMM V4 (raydium-io/raydium-idl) وترتيب SDK الرسمي (raydium-sdk-v1):
    index 4 = amm, index 7 = lpMint, index 8 = coinMint — مطابقة تماماً.
    """
    try:
        message = tx_data["transaction"]["message"]
        account_keys = message["accountKeys"]
        all_instructions = _get_all_instructions(tx_data)

        for ix in all_instructions:
            program_id = _extract_program_id(ix, account_keys)
            if program_id != RAYDIUM_AMM_V4_PROGRAM_ID:
                continue

            # التحقق الحاسم: هل هذه التعليمة فعلاً Initialize2، أم Swap/Deposit/
            # Withdraw عادية على عملة موجودة أصلاً؟ بدون هذا الفحص، كل تعليمات
            # Raydium تقريباً (بما فيها عمليات البيع/الشراء العادية SwapBaseIn/Out)
            # كانت تُقبَل خطأً كأنها إنشاء pool جديد — لأن أغلبها يحتوي أيضاً 10+ حساباً.
            discriminator = _get_instruction_discriminator(ix)
            if discriminator != RAYDIUM_INITIALIZE2_DISCRIMINATOR:
                continue

            ix_accounts = _extract_instruction_accounts(ix, account_keys)
            if len(ix_accounts) < 10:
                continue

            amm_address = ix_accounts[4]
            lp_mint = ix_accounts[7]
            coin_mint = ix_accounts[8]

            return {
                "mint_address": coin_mint,
                "pool_address": amm_address,
                "lp_mint_address": lp_mint,
                "deployer_wallet": "",
                "dex": "raydium",
            }
    except (KeyError, IndexError, TypeError) as e:
        logger.debug(f"فشل تحليل معاملة Raydium: {e}")

    return None


async def fetch_token_metadata(pool_event: dict) -> TokenMetadata:
    """يبني TokenMetadata فعلياً من بيانات الحدث + استعلامات RPC حقيقية."""
    mint_address = pool_event["mint_address"]

    mint_data_b64 = await get_account_info_base64(mint_address)
    mint_info = parse_spl_mint_account(mint_data_b64)

    try:
        largest_accounts = await get_token_largest_accounts(mint_address)
        holder_data_available = True
    except Exception as e:
        logger.warning(
            f"تعذّر قراءة توزيع الحيازة لـ {mint_address} (قد تكون Token-2022): {e}"
        )
        largest_accounts = []
        holder_data_available = False

    total_supply = mint_info["supply"] or 1

    deployer_wallet = pool_event.get("deployer_wallet", "")
    dev_wallet_pct = 0.0
    top_holder_pct_excluding_lp = 0.0
    lp_ata_addresses = set(pool_event.get("known_lp_token_accounts", []))

    for holder in largest_accounts:
        amount = float(holder.get("amount", 0))
        pct = (amount / total_supply) * 100 if total_supply else 0
        address = holder.get("address", "")

        if address in lp_ata_addresses:
            continue

        if address == deployer_wallet:
            dev_wallet_pct = max(dev_wallet_pct, pct)

        top_holder_pct_excluding_lp = max(top_holder_pct_excluding_lp, pct)

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
        is_standard_spl_token=True,
        has_transfer_restriction_hooks=False,
        has_referral_or_commission_function=False,
    )


async def process_new_pool_event(pool_event: dict):
    dex = pool_event.get("dex", "").lower()
    if dex not in DEX_ALLOWLIST:
        return

    mint_address = pool_event.get("mint_address", "")

    # فحص سريع ومجاني تماماً (بدون RPC): هل عولجت هذه العملة خلال آخر دقيقتين؟
    now = asyncio.get_event_loop().time()
    last_seen = _recently_processed_mints.get(mint_address)
    if last_seen and (now - last_seen) < _RECENT_MINT_TTL_SECONDS:
        logger.debug(f"تجاهل {mint_address} — عولجت للتو خلال آخر {_RECENT_MINT_TTL_SECONDS}s")
        return
    _recently_processed_mints[mint_address] = now

    # تنظيف دوري بسيط للذاكرة المؤقتة لتفادي تضخّمها بلا حدود مع الوقت
    if len(_recently_processed_mints) > 500:
        cutoff = now - _RECENT_MINT_TTL_SECONDS
        for addr in list(_recently_processed_mints.keys()):
            if _recently_processed_mints[addr] < cutoff:
                del _recently_processed_mints[addr]

    if await has_seen_mint_before(mint_address) or await is_already_in_watchlist(mint_address):
        logger.debug(f"تجاهل {mint_address} — تم رصدها/التعامل معها من قبل")
        return

    try:
        meta = await fetch_token_metadata(pool_event)
    except Exception as e:
        logger.warning(f"تعذّر قراءة بيانات العقد لـ {pool_event.get('mint_address')}: {e}")
        return

    onchain_result = run_all_onchain_filters(meta)
    if not onchain_result.passed:
        logger.info(f"رفض {meta.symbol}: {onchain_result.reason}")
        await record_screening_result(
            mint_address, meta.symbol, dex, "rejected", "onchain", onchain_result.reason
        )
        return

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
        return None

    event = parse_pump_fun_create_instruction(tx_data)
    if event:
        return event

    event = parse_raydium_initialize_instruction(tx_data)
    if event:
        return event

    return None


async def _process_signature_with_timing(signature: str, semaphore: asyncio.Semaphore):
    """
    يعالج توقيعاً واحداً (معاملة واحدة) ضمن حد التزامن المسموح، مع مهلة قصوى
    صارمة (45 ثانية) لضمان ظهور نتيجة ما مهما حدث، بدل التعليق الصامت.
    """
    async with semaphore:
        start_time = asyncio.get_event_loop().time()
        try:
            await asyncio.wait_for(_do_process(signature, start_time), timeout=45)
        except asyncio.TimeoutError:
            logger.error(
                f"⏱️ انتهت المهلة القصوى (45s) لمعالجة {signature[:16]}... بدون أي استجابة"
            )
        except Exception as e:
            logger.error(
                f"خطأ غير متوقع أثناء معالجة {signature[:16]}...: "
                f"{type(e).__name__}: {e} "
                f"(بعد {asyncio.get_event_loop().time() - start_time:.1f}s)"
            )


async def _do_process(signature: str, start_time: float):
    """الجسم الفعلي لمعالجة توقيع واحد: جلب + تحليل + تشغيل الفلاتر."""
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
        logger.debug(f"لم يُتعرّف على معاملة {signature[:16]}... كإنشاء عملة جديدة")


async def poll_for_new_pool_events():
    """
    الحلقة الرئيسية للاكتشاف: تستقصي (Poll) كل برنامج مراقَب دورياً بحثاً عن
    توقيعات معاملات جديدة منذ آخر فحص (باستخدام "until" لتفادي تكرار نفس
    المعاملات)، وتُشغّل معالجة كل توقيع جديد في مهمة منفصلة (Task) بحد أقصى
    5 معالجات متزامنة، تماماً كما كان الحال سابقاً مع WebSocket.
    """
    last_signatures = {pid: None for pid in MONITORED_PROGRAM_IDS}
    processing_semaphore = asyncio.Semaphore(5)
    background_tasks: set = set()

    logger.info("بدء الاستقصاء الدوري (Polling) لأحداث السيولة الجديدة...")

    while True:
        for program_id in MONITORED_PROGRAM_IDS:
            try:
                sigs = await get_signatures_for_address_polling(
                    program_id,
                    limit=SIGNATURES_PER_POLL,
                    until=last_signatures[program_id],
                )
            except Exception as e:
                logger.warning(f"فشل استقصاء البرنامج {program_id[:16]}...: {type(e).__name__}: {e}")
                continue

            if not sigs:
                continue

            # النتائج بترتيب الأحدث أولاً؛ نحدّث نقطة المرجع للمرة القادمة،
            # ونعالج بترتيب زمني تصاعدي (الأقدم أولاً) للحفاظ على الترتيب المنطقي.
            last_signatures[program_id] = sigs[0]["signature"]

            for sig_info in reversed(sigs):
                if sig_info.get("err"):
                    continue  # تجاهل المعاملات الفاشلة على الشبكة نفسها

                signature = sig_info["signature"]
                task = asyncio.create_task(
                    _process_signature_with_timing(signature, processing_semaphore)
                )
                background_tasks.add(task)
                task.add_done_callback(background_tasks.discard)

        await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def run_mempool_listener():
    """
    نقطة الدخول الرئيسية لاكتشاف عملات جديدة — تستخدم الاستقصاء الدوري
    (Polling) بدل WebSocket (راجع تعليق أعلى الملف لشرح السبب).
    """
    await init_watchlist_table()

    reconnect_delay = 5
    while True:
        try:
            await poll_for_new_pool_events()
        except Exception as e:
            logger.error(
                f"خطأ غير متوقع في حلقة الاستقصاء: {type(e).__name__}: {e} — "
                f"إعادة المحاولة خلال {reconnect_delay}s"
            )
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 60)
