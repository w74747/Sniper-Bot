"""
إدارة الاتصال بقاعدتي بيانات Postgres: الأساسية (Railway) والاحتياطية (Neon).

المبدأ: كل عملية قراءة/كتابة تُحاول أولاً على القاعدة الأساسية. إذا فشل
الاتصال بها تماماً (وليس خطأ منطقي في الاستعلام نفسه)، تتحول تلقائياً
للقاعدة الاحتياطية — تماماً كمولّد الكهرباء الاحتياطي: لا يعمل إلا عند
انقطاع الأساسي، ولا حاجة لتدخل يدوي.

كلا القاعدتين تُنشآن ببنية جداول متطابقة تماماً (نفس init_schema)، بحيث
يعمل التبديل بسلاسة دون أي فرق في البيانات المتاحة.
"""
import asyncio
import logging
import os

import asyncpg

logger = logging.getLogger("db_pool")

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
FALLBACK_DATABASE_URL = os.getenv("FALLBACK_DATABASE_URL", "").strip()

_primary_pool: asyncpg.Pool = None
_fallback_pool: asyncpg.Pool = None
_using_fallback = False  # للتسجيل فقط — لإعلامك أي قاعدة نشطة فعلياً الآن


async def _ensure_pools():
    """ينشئ مجمعي الاتصال (Connection Pools) مرة واحدة فقط عند أول استخدام."""
    global _primary_pool, _fallback_pool

    if _primary_pool is None and DATABASE_URL:
        try:
            _primary_pool = await asyncpg.create_pool(
                DATABASE_URL, min_size=1, max_size=5, command_timeout=10
            )
            logger.info("✅ تم الاتصال بقاعدة البيانات الأساسية (Railway Postgres)")
        except Exception as e:
            logger.error(f"⚠️ تعذّر الاتصال بقاعدة البيانات الأساسية عند البدء: {e}")

    if _fallback_pool is None and FALLBACK_DATABASE_URL:
        try:
            _fallback_pool = await asyncpg.create_pool(
                FALLBACK_DATABASE_URL, min_size=1, max_size=3, command_timeout=10
            )
            logger.info("✅ تم الاتصال بقاعدة البيانات الاحتياطية (Neon) — جاهزة عند الحاجة")
        except Exception as e:
            logger.error(f"⚠️ تعذّر الاتصال بقاعدة البيانات الاحتياطية عند البدء: {e}")


async def execute(query: str, *args):
    """تنفيذ استعلام كتابة (INSERT/UPDATE/CREATE) مع تبديل تلقائي عند الفشل."""
    return await _run_with_failover(lambda conn: conn.execute(query, *args))


async def fetch(query: str, *args):
    """تنفيذ استعلام قراءة يرجع عدة صفوف."""
    return await _run_with_failover(lambda conn: conn.fetch(query, *args))


async def fetchrow(query: str, *args):
    """تنفيذ استعلام قراءة يرجع صفاً واحداً أو لا شيء."""
    return await _run_with_failover(lambda conn: conn.fetchrow(query, *args))


async def fetchval(query: str, *args):
    """تنفيذ استعلام قراءة يرجع قيمة واحدة (مثل COUNT)."""
    return await _run_with_failover(lambda conn: conn.fetchval(query, *args))


async def _run_with_failover(operation):
    """
    المنطق الفعلي للتبديل: يحاول القاعدة الأساسية أولاً، وعند فشل الاتصال
    (وليس خطأ في الاستعلام نفسه — تلك أخطاء حقيقية يجب أن تظهر وتُصلَح)
    يتحول للاحتياطية تلقائياً ويُسجّل تحذيراً واضحاً.
    """
    global _using_fallback
    await _ensure_pools()

    if _primary_pool is not None:
        try:
            async with _primary_pool.acquire() as conn:
                result = await operation(conn)
                if _using_fallback:
                    logger.info("✅ عادت القاعدة الأساسية للعمل — التبديل رجع للأساسية")
                    _using_fallback = False
                return result
        except (asyncpg.exceptions.ConnectionDoesNotExistError,
                 asyncpg.exceptions.CannotConnectNowError,
                 asyncpg.exceptions.TooManyConnectionsError,
                 ConnectionError, OSError) as e:
            logger.warning(f"⚠️ فشل الاتصال بالقاعدة الأساسية، التحول للاحتياطية: {e}")
            _using_fallback = True

    if _fallback_pool is not None:
        async with _fallback_pool.acquire() as conn:
            return await operation(conn)

    raise RuntimeError(
        "لا توجد قاعدة بيانات متاحة إطلاقاً — تحقق من DATABASE_URL وFALLBACK_DATABASE_URL"
    )


def is_using_fallback() -> bool:
    """يفيد في تقرير الفحص الصحي — لمعرفة أي قاعدة نشطة فعلياً الآن."""
    return _using_fallback
