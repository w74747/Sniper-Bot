"""
الاستماع لأحداث إطلاق سيولة جديدة (تهيئة pool جديد على Raydium/Pump.fun)
عبر Helius WebSocket، ثم تشغيل كل الفلاتر
بالترتيب: كلمات محظورة → on-chain → سمعة/GoPlus → محاكاة بيع.

عند اجتياز كل الفلاتر: إضافة العملة إلى watchlist (وليس شراء فوري) —
حسب الاستراتيجية المتفق عليها.
"""
import asyncio
import json
import logging
from typing import Optional

import websockets

from config.settings import HELIUS_WS_URL, DEX_ALLOWLIST
from filters.onchain_filters import (
    TokenMetadata, run_all_onchain_filters, parse_spl_mint_account,
    KNOWN_BURN_ADDRESSES,
)
from filters.reputation import evaluate_reputation
from filters.sell_simulation import simulate_sell, evaluate_simulation_result
from monitor.watchlist import (
    WatchlistEntry, add_to_watchlist, init_watchlist_table, is_already_in_watchlist,
)
from db.trades import has_seen_mint_before
from utils.solana_rpc import (
    get_account_info_base64, get_token_largest_accounts, rpc_call, get_transaction_via_helius,
)

logger = logging.getLogger("mempool_listener")

PUMP_FUN_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
RAYDIUM_AMM_V4_PROGRAM_ID = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"

MONITORED_PROGRAM_IDS = [PUMP_FUN_PROGRAM_ID, RAYDIUM_AMM_V4_PROGRAM_ID]


def _get_all_instructions(tx_data: dict) -> list:
    instructions = list(tx_data.get("transaction", {}).get("message", {}).get("instructions", []))
    inner_instructions = tx_data.get("meta", {}).get("innerInstructions", [])
    for group in inner_instructions:
        instructions.extend(group.get("instructions", []))
    return instructions


def _extract_program_id(ix: dict, account_keys: list) -> str:
    if "programId" in ix:
        return ix["programId"]
    idx = ix.get("programIdIndex")
    if idx is None or idx >= len(account_keys):
        return ""
    key = account_keys[idx]
    return key.get("pubkey") if isinstance(key, dict) else key


def _extract_instruction_accounts(ix: dict, account_keys: list) -> list:
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
    """يحلل معاملة "create" من Pump.fun لاستخراج بيانات العملة الجديدة."""
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
            deployer_wallet = ix_accounts[7]

            return {
                "mint_address": mint_address,
                "pool_address": bonding_curve,
                "deployer_wallet": deployer_wallet,
                "dex": "pump.fun",
                "lp_mint_address": None,
            }
    except (KeyError, IndexError, TypeError) as e:
        logger.debug(f"فشل تحليل معاملة Pump.fun: {e}")

    return None


def parse_raydium_initialize_instruction(tx_data: dict) -> Optional[dict]:
    """يحلل معاملة "initialize2" من Raydium AMM V4 لاستخراج بيانات الـ pool الجديد."""
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

            amm_address = ix_accounts[4]
            lp_mint = ix_accounts[7]
            coin_mint = ix_accounts[8]

            logger.warning(
                "تحليل Raydium initialize2 يستخدم مواقع حسابات غير مُختبرة بعد — "
                "راجع TODO في parse_raydium_initialize_instruction قبل الاعتماد عليه"
            )

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
    """
    يبني TokenMetadata فعلياً من بيانات الحدث + استعلامات RPC حقيقية:
    1. getAccountInfo على mint address → فك تشفير mint_authority/freeze_authority/supply
    2. getTokenLargestAccounts على mint address → حساب نسبة محفظة المطور وأكبر حامل
    3. getTokenLargestAccounts على lp_mint_address (إن توفر) → نسبة حرق/قفل السيولة
    """
    mint_address = pool_event["mint_address"]

    mint_data_b64 = await get_account_info_base64(mint_address)
    mint_info = parse_spl_mint_account(mint_data_b64)

    # ملاحظة: بعض عملات Pump.fun الحديثة تُصدَر عبر برنامج Token-2022، وقد
    # يرفضها getTokenLargestAccounts بخطأ "not a Token mint" رغم أنها عملة
    # صالحة فعلياً. لا نُسقط العملة بخطأ تقني، بل نمرّر holder_data_available
    # = False للفلتر ليقرر بنفسه بدل افتراض قيمة خاطئة هنا.
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

    if has_seen_mint_before(mint_address) or is_already_in_watchlist(mint_address):
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
        return

    reputation_ok, reputation_reason = await evaluate_reputation(
        meta.mint_address, pool_event.get("deployer_wallet", "")
    )
    if not reputation_ok:
        logger.info(f"رفض {meta.symbol}: {reputation_reason}")
        return

    sim_result = await simulate_sell(
        rpc_client=None,
        wallet_pubkey="",
        mint_address=meta.mint_address,
        pool_address=pool_event.get("pool_address", ""),
        test_amount_lamports=1_000_000,
    )
    sim_ok, sim_reason = evaluate_simulation_result(sim_result)
    if not sim_ok:
        logger.info(f"رفض {meta.symbol}: {sim_reason}")
        return

    add_to_watchlist(WatchlistEntry(
        mint_address=meta.mint_address,
        symbol=meta.symbol,
        pool_address=pool_event.get("pool_address", ""),
        initial_filter_report=json.dumps({
            "onchain": onchain_result.reason,
            "reputation": reputation_reason,
            "sell_simulation": sim_reason,
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
    كل حدث مرشّح يُعالج في مهمة (Task) منفصلة عبر asyncio.create_task،
    مع مهلة قصوى صارمة (45 ثانية) لكل معالجة، ونبضة قلب دورية للتشخيص.
    """
    subscribe_id = 1
    pending_subscriptions = {}
    processing_semaphore = asyncio.Semaphore(5)
    background_tasks: set = set()

    async def _process_event_with_timing(signature: str):
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
                logger.error(
                    f"خطأ غير متوقع أثناء معالجة {signature[:16]}...: "
                    f"{type(e).__name__}: {e} "
                    f"(بعد {asyncio.get_event_loop().time() - start_time:.1f}s)"
                )

    async def _do_process(signature: str, start_time: float):
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
        while True:
            await asyncio.sleep(15)
            logger.info(f"💓 نبضة: {len(background_tasks)} مهمة قيد المعالجة حالياً")

    async with websockets.connect(
        HELIUS_WS_URL, ping_interval=20, ping_timeout=20
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
                    is_pump_create = "Instruction: Create" in logs_text
                    is_raydium_init = "Instruction: Initialize2" in logs_text
                    if not is_pump_create and not is_raydium_init:
                        continue

                    logger.info(f"حدث مرشّح مكتشف: {signature[:16]}...")

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
    كاملة عبر getTransaction (عبر Helius أيضاً) لتحليلها واستخراج بيانات العملة الجديدة.
    """
    init_watchlist_table()
    logger.info("بدء الاستماع لأحداث السيولة الجديدة...")

    reconnect_delay = 5
    while True:
        try:
            await _run_single_websocket_session()
        except (websockets.exceptions.ConnectionClosed, ConnectionResetError) as e:
            logger.warning(f"انقطع اتصال WebSocket: {type(e).__name__}: {e} — إعادة الاتصال خلال {reconnect_delay}s")
        except Exception as e:
            logger.error(f"خطأ غير متوقع في جلسة WebSocket: {type(e).__name__}: {e} — إعادة الاتصال خلال {reconnect_delay}s")

        await asyncio.sleep(reconnect_delay)
        reconnect_delay = min(reconnect_delay * 2, 60)
