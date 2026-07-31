"""
✅ monitor/pumpportal_listener.py - الكامل والمصحح
انسخ والصق هذا الملف كاملاً
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

PUMPPORTAL_WS_URL = (
    f"wss://pumpportal.fun/api/data?api-key={PUMPPORTAL_API_KEY}"
    if PUMPPORTAL_API_KEY else "wss://pumpportal.fun/api/data"
)

TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
ASSOCIATED_TOKEN_PROGRAM_ID = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")

_ws_ref = {"ws": None}
_tracked_positions: dict = {}
LIQUIDITY_DRAIN_THRESHOLD_PCT = 25.0


async def track_open_position(mint_address: str, initial_sol_in_curve: float = None, deployer_wallet: str = ""):
    """يُستدعى فور نجاح شراء فعلي"""
    if not PUMPPORTAL_API_KEY:
        logger.debug(f"لا يوجد PUMPPORTAL_API_KEY — تخطّي المراقبة اللحظية لـ {mint_address}")
        return

    _tracked_positions[mint_address] = {
        "vsol": initial_sol_in_curve or 0.0,
        "deployer_wallet": deployer_wallet,
    }
    ws = _ws_ref.get("ws")
    if ws is not None:
        try:
            await ws.send(json.dumps({"method": "subscribeTokenTrade", "keys": [mint_address]}))
            logger.info(f"📡 بدأت المراقبة اللحظية (WebSocket) لـ {mint_address}")
        except Exception as e:
            logger.warning(f"تعذّر الاشتراك اللحظي لـ {mint_address}: {e}")


async def untrack_open_position(mint_address: str):
    """يُستدعى عند إغلاق الصفقة"""
    _tracked_positions.pop(mint_address, None)
    ws = _ws_ref.get("ws")
    if ws is not None:
        try:
            await ws.send(json.dumps({"method": "unsubscribeTokenTrade", "keys": [mint_address]}))
        except Exception as e:
            logger.debug(f"تعذّر إلغاء الاشتراك اللحظي لـ {mint_address}: {e}")


async def _handle_trade_event(data: dict):
    """يُعالج حدث بيع/شراء لحظي"""
    mint_address = data.get("mint", "")
    position = _tracked_positions.get(mint_address)
    if position is None:
        return

    tx_type = data.get("txType", "")
    trader = data.get("traderPublicKey", "")
    deployer_wallet = position.get("deployer_wallet", "")

    if tx_type == "sell" and deployer_wallet and trader == deployer_wallet:
        logger.warning(f"🚨 رُصد بيع من محفظة المطوّر نفسها لـ {mint_address}")
        await _trigger_emergency_exit(mint_address, "رُصد بيع من محفظة المطوّر نفسها لحظياً")
        return

    current_vsol = float(data.get("vSolInBondingCurve", 0) or 0)
    previous_vsol = position.get("vsol", 0.0)
    position["vsol"] = current_vsol

    if previous_vsol <= 0 or current_vsol <= 0:
        return

    drop_pct = ((previous_vsol - current_vsol) / previous_vsol) * 100
    if drop_pct < LIQUIDITY_DRAIN_THRESHOLD_PCT:
        return

    logger.warning(f"🚨 انهيار سيولة لحظي لـ {mint_address}: انخفاض {drop_pct:.1f}%")
    await _trigger_emergency_exit(mint_address, f"انهيار سيولة (انخفاض {drop_pct:.1f}%)")


async def _trigger_emergency_exit(mint_address: str, reason: str):
    """منطق تنفيذ البيع الطارئ الفوري"""
    try:
        from db import trades as db
        from trading.executor import execute_emergency_sell

        open_trades = await db.get_open_trades()
        matching_trade = next((t for t in open_trades if t["mint_address"] == mint_address), None)
        if matching_trade:
            await execute_emergency_sell(dict(matching_trade), reason)
            _tracked_positions.pop(mint_address, None)
    except Exception as e:
        logger.error(f"⚠️ فشل تنفيذ البيع الطارئ اللحظي لـ {mint_address}: {e}")


async def _handle_migration_event(data: dict):
    """يُسجَّل عند اكتشاف تخرّج عملة Pump.fun"""
    mint_address = data.get("mint", "")
    symbol = data.get("symbol", "")
    deployer_wallet = data.get("traderPublicKey", "")

    try:
        from db import trades as db
        await db.record_migration(mint_address, symbol, deployer_wallet)
        logger.info(f"🎓 عملة تخرّجت فعلياً: {symbol or '?'} ({mint_address})")
    except Exception as e:
        logger.warning(f"تعذّر تسجيل حدث التخرّج لـ {mint_address}: {e}")


def _derive_associated_bonding_curve(bonding_curve: str, mint: str) -> str:
    """يحسب عنوان ATA الخاص بحساب bonding curve"""
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
    """يتصل بـPumpPortal WebSocket ويشترك في أحداث الإنشاء"""
    reconnect_delay = 5
    processing_semaphore = asyncio.Semaphore(5)
    background_tasks: set = set()

    async def _process_with_limit(event: dict):
        async with processing_semaphore:
            try:
                await process_new_pool_event(event)
            except Exception as e:
                logger.error(f"⚠️ خطأ في معالجة حدث PumpPortal: {type(e).__name__}: {e}")

    while True:
        try:
            async with websockets.connect(
                PUMPPORTAL_WS_URL, ping_interval=20, ping_timeout=20
            ) as ws:
                _ws_ref["ws"] = ws
                await ws.send(json.dumps({"method": "subscribeNewToken"}))
                await ws.send(json.dumps({"method": "subscribeMigration"}))

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

                    if tx_type == "migration" and "mint" in data:
                        asyncio.create_task(_handle_migration_event(data))
                        continue

                    if tx_type in ("buy", "sell") and "mint" in data:
                        asyncio.create_task(_handle_trade_event(data))
                        continue

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

                    logger.info(f"🚀 عملة جديدة: {symbol or '?'} ({mint_address})")
                    task = asyncio.create_task(_process_with_limit(pool_event))
                    background_tasks.add(task)
                    task.add_done_callback(background_tasks.discard)

        except Exception as e:
            _ws_ref["ws"] = None
            logger.error(f"⚠️ انقطع اتصال PumpPortal: {type(e).__name__}: {e} — إعادة الاتصال خلال {reconnect_delay}s")
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 60)
