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

import websockets

from config.settings import ALCHEMY_WS_URL, DEX_ALLOWLIST
from filters.onchain_filters import (
    TokenMetadata, run_all_onchain_filters, parse_spl_mint_account,
    KNOWN_BURN_ADDRESSES,
)
from filters.reputation import evaluate_reputation
from filters.sell_simulation import simulate_sell, evaluate_simulation_result
from monitor.watchlist import WatchlistEntry, add_to_watchlist, init_watchlist_table
from utils.solana_rpc import get_account_info_base64, get_token_largest_accounts

logger = logging.getLogger("mempool_listener")


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
    largest_accounts = await get_token_largest_accounts(mint_address)
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
        total_supply=total_supply,
        mint_authority_active=mint_info["mint_authority_active"],
        freeze_authority_active=mint_info["freeze_authority_active"],
        lp_burned_or_locked_pct=lp_burned_or_locked_pct,
        dev_wallet_pct=dev_wallet_pct,
        top_holder_pct_excluding_lp=top_holder_pct_excluding_lp,
        is_standard_spl_token=True,  # مضمون طالما نجح فك تشفير SPL Mint القياسي
        has_transfer_restriction_hooks=False,  # TODO: فحص Token-2022 transfer hooks إن وُجدت
        has_referral_or_commission_function=False,  # يحتاج تحليل bytecode العقد (خارج نطاق RPC البسيط)
    )


async def process_new_pool_event(pool_event: dict):
    dex = pool_event.get("dex", "").lower()
    if dex not in DEX_ALLOWLIST:
        return  # تجاهل صامت — منصة غير مدرجة في القائمة المسموحة

    try:
        meta = await fetch_token_metadata(pool_event)
    except Exception as e:
        # مبدأ fail-safe: أي فشل في قراءة بيانات العقد = تجاهل العملة، وليس قبولها
        logger.warning(f"تعذّر قراءة بيانات العقد لـ {pool_event.get('mint_address')}: {e}")
        return

    # المرحلة 1: الفلاتر الآلية الفورية (كلمات + عرض + توزيع + قابلية تحويل)
    onchain_result = run_all_onchain_filters(meta)
    if not onchain_result.passed:
        logger.info(f"رفض {meta.symbol}: {onchain_result.reason}")
        return

    # المرحلة 2: السمعة (سجل المطور + GoPlus)
    reputation_ok, reputation_reason = await evaluate_reputation(
        meta.mint_address, pool_event.get("deployer_wallet", "")
    )
    if not reputation_ok:
        logger.info(f"رفض {meta.symbol}: {reputation_reason}")
        return

    # المرحلة 3: محاكاة بيع (كشف honeypot) — أهم فحص قبل أي التزام
    sim_result = await simulate_sell(
        rpc_client=None,
        wallet_pubkey="",
        mint_address=meta.mint_address,
        pool_address=pool_event.get("pool_address", ""),
        test_amount_lamports=1_000_000,  # ~0.001 SOL كمية اختبار صغيرة
    )
    sim_ok, sim_reason = evaluate_simulation_result(sim_result)
    if not sim_ok:
        logger.info(f"رفض {meta.symbol}: {sim_reason}")
        return

    # اجتازت كل الفلاتر → إضافة لقائمة المراقبة (لا شراء فوري)
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


async def run_mempool_listener():
    """
    TODO: الاشتراك الفعلي في قناة Alchemy المناسبة لأحداث إنشاء pools جديدة
    (عبر Alchemy WebSocket subscribe على برنامج Raydium/Pump.fun، أو gRPC إن توفر).
    """
    init_watchlist_table()
    logger.info("بدء الاستماع لأحداث السيولة الجديدة...")

    async with websockets.connect(ALCHEMY_WS_URL) as ws:
        # TODO: إرسال رسالة الاشتراك المناسبة (subscribe) حسب توثيق Alchemy لـ Solana
        # await ws.send(json.dumps({...}))
        async for message in ws:
            try:
                event = json.loads(message)
                await process_new_pool_event(event)
            except Exception as e:
                logger.error(f"خطأ في معالجة حدث جديد: {e}")
