"""
تكامل GMGN OpenAPI — طبقة تحليل إضافية غنية جداً لعملات meme على Solana:
عدد محافظ "الأموال الذكية" الحائزة، نسبة "المحافظ المُرتزقة" (rat trader)،
نسبة "المحافظ المُجمَّعة" (bundler)، عدد محافظ Snipers، ودرجة احتمال Rug.

بُني بالكامل بناءً على تحليل الكود المصدري الرسمي لأداة gmgn-cli
(github.com/GMGNAI/gmgn-skills)، وليس تخميناً — تحديداً آلية المصادقة
"Exist" (بدون توقيع) المستخدَمة لكل استعلامات القراءة (token/market/user):

    الترويسات: X-APIKEY فقط
    معاملات الاستعلام: timestamp (ثوانٍ يونكس) + client_id (UUID) إضافيان

لا حاجة للمفتاح الخاص (GMGN_PRIVATE_KEY) إطلاقاً لهذا الاستخدام — ذلك
المفتاح مطلوب فقط لعمليات التداول الفعلي (swap/order)، ولسنا بحاجتها.
"""
import logging
import time
import uuid

import aiohttp

from config.settings import GMGN_API_KEY

logger = logging.getLogger("gmgn_client")

GMGN_API_BASE = "https://openapi.gmgn.ai"


def _auth_headers() -> dict:
    return {
        "X-APIKEY": GMGN_API_KEY,
        "Content-Type": "application/json",
        "User-Agent": "sniper-bot/1.0",
    }


def _auth_query() -> dict:
    """معاملات المصادقة الإلزامية لكل طلب (بدون توقيع) — يجب توليدهما لحظة كل طلب فعلياً."""
    return {"timestamp": int(time.time()), "client_id": str(uuid.uuid4())}


async def get_token_info(mint_address: str, chain: str = "sol") -> dict:
    """
    يستعلم عن التحليل الغني لعملة عبر GMGN: عدد محافظ الأموال الذكية
    الحائزة، KOLs، نسبة المحافظ المُرتزقة/المُجمَّعة، محافظ Snipers،
    ودرجة احتمال Rug — كل هذا في استدعاء واحد.

    يرجع قاموساً موحَّداً:
    {
        "available": bool,
        "smart_money_count": int,
        "kol_count": int,
        "rat_trader_pct": float,      # نسبة الحجم من محافظ مُرتزقة (0-100)
        "bundler_pct": float,          # نسبة الحجم من شراء مُجمَّع بواسطة بوتات (0-100)
        "sniper_count": int,
        "rug_ratio": float,            # 0-1، الأعلى = الأخطر
        "reason": str,
    }
    عند أي فشل (401/429/شبكة/إلخ): available=False — fail-open كامل تماماً،
    لا يُوقف الفحص الأساسي (RugCheck + on-chain + GoPlus) إن فشل هذا.
    """
    empty_result = {
        "available": False, "smart_money_count": 0, "kol_count": 0,
        "rat_trader_pct": 0.0, "bundler_pct": 0.0, "sniper_count": 0,
        "rug_ratio": 0.0, "reason": "",
    }

    if not GMGN_API_KEY:
        return empty_result

    query = {"chain": chain, "address": mint_address, **_auth_query()}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{GMGN_API_BASE}/v1/token/info", params=query,
                headers=_auth_headers(), timeout=10,
            ) as resp:
                if resp.status == 429:
                    logger.debug(f"GMGN: تجاوز حد المعدل لـ {mint_address} (fail-open)")
                    return empty_result
                if resp.status != 200:
                    text = await resp.text()
                    logger.info(f"GMGN رجع status {resp.status} لـ {mint_address}: {text[:200]}")
                    return empty_result
                envelope = await resp.json()
    except Exception as e:
        logger.debug(f"تعذّر الاتصال بـGMGN لـ {mint_address}: {e}")
        return empty_result

    if envelope.get("code") != 0:
        logger.info(f"GMGN رجع code={envelope.get('code')} لـ {mint_address}: {envelope.get('message')}")
        return empty_result

    data = envelope.get("data") or {}

    # أسماء الحقول هنا مبنية على توثيق GMGN الرسمي (rat_trader_amount_rate،
    # bundler_trader_amount_rate، إلخ) — نستخدم .get() الآمن مع بدائل
    # متعددة الاحتمالات لضمان التوافق حتى لو اختلفت التسمية الدقيقة قليلاً.
    return {
        "available": True,
        "smart_money_count": int(data.get("smart_degen_count", 0) or 0),
        "kol_count": int(data.get("renowned_wallets", data.get("renowned_wallet_count", 0)) or 0),
        "rat_trader_pct": float(data.get("rat_trader_amount_rate", 0) or 0) * 100,
        "bundler_pct": float(data.get("bundler_trader_amount_rate", 0) or 0) * 100,
        "sniper_count": int(data.get("sniper_count", 0) or 0),
        "rug_ratio": float(data.get("rug_ratio", 0) or 0),
        "reason": "",
    }
