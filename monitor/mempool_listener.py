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
from filters.onchain_filters import TokenMetadata, run_all_onchain_filters
from filters.reputation import evaluate_reputation
from filters.sell_simulation import simulate_sell, evaluate_simulation_result
from monitor.watchlist import WatchlistEntry, add_to_watchlist, init_watchlist_table

logger = logging.getLogger("mempool_listener")


async def fetch_token_metadata(pool_event: dict) -> TokenMetadata:
    """
    TODO: يبني TokenMetadata فعلياً من بيانات الحدث + استعلامات RPC إضافية
    (getAccountInfo على mint address لقراءة mint_authority/freeze_authority،
    getTokenLargestAccounts لحساب التوزيع، إلخ).
    """
    raise NotImplementedError("يحتاج ربطاً فعلياً بقراءة بيانات العقد عبر Alchemy RPC")


async def process_new_pool_event(pool_event: dict):
    dex = pool_event.get("dex", "").lower()
    if dex not in DEX_ALLOWLIST:
        return  # تجاهل صامت — منصة غير مدرجة في القائمة المسموحة

    try:
        meta = await fetch_token_metadata(pool_event)
    except NotImplementedError:
        logger.debug("fetch_token_metadata غير مكتمل بعد — تخطي هذا الحدث")
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
    try:
        sim_result = await simulate_sell(
            rpc_client=None,  # TODO: تمرير عميل RPC فعلي
            wallet_pubkey="",
            mint_address=meta.mint_address,
            pool_address=pool_event.get("pool_address", ""),
            test_amount_lamports=1000,
        )
        sim_ok, sim_reason = evaluate_simulation_result(sim_result)
        if not sim_ok:
            logger.info(f"رفض {meta.symbol}: {sim_reason}")
            return
    except NotImplementedError:
        logger.warning(f"محاكاة البيع غير مكتملة بعد — {meta.symbol} لن يُضاف حتى تُستكمل")
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
