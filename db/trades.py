"""
توثيق كل صفقة وقرار فحص في Postgres (أساسي: Railway، احتياطي: Neon).

هذا يحل مشكلتين حقيقيتين واجهناهما سابقاً:
1. فقدان بيانات SQLite بالكامل مرة عند إعادة إنشاء مشروع Railway (فقدان الـ Volume).
2. عمليات sqlite3 المتزامنة (blocking) داخل كود asyncio — الآن كل شيء غير متزامن حقيقياً.
"""
import logging
import time
from dataclasses import dataclass

from db import pool

logger = logging.getLogger("db_trades")

# بعد صفقة سابقة عادية (ربح/خسارة بدون أي شبهة احتيال)، لا نمنع إعادة الدخول
# إلا خلال هذه المدة فقط — عملات meme قد تصعد على عدة موجات متكررة.
MIN_COOLDOWN_HOURS_AFTER_NORMAL_CLOSE = 6


async def init_db():
    """ينشئ كل الجداول (إن لم تكن موجودة) في القاعدة الأساسية والاحتياطية معاً."""
    schema = """
        CREATE TABLE IF NOT EXISTS trades (
            id SERIAL PRIMARY KEY,
            mint_address TEXT NOT NULL,
            symbol TEXT,
            entry_timestamp DOUBLE PRECISION,
            exit_timestamp DOUBLE PRECISION,
            capital_invested_sol DOUBLE PRECISION,
            entry_price DOUBLE PRECISION,
            exit_price DOUBLE PRECISION,
            proceeds_sol DOUBLE PRECISION,
            profit_loss_sol DOUBLE PRECISION,
            status TEXT,
            close_reason TEXT,
            filter_report TEXT,
            tx_hash_entry TEXT,
            tx_hash_exit TEXT
        );
        CREATE TABLE IF NOT EXISTS alerts (
            id SERIAL PRIMARY KEY,
            trade_id INTEGER REFERENCES trades(id),
            timestamp DOUBLE PRECISION,
            alert_type TEXT,
            message TEXT,
            requires_human_confirmation INTEGER DEFAULT 0,
            resolved INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS screening_log (
            id SERIAL PRIMARY KEY,
            timestamp DOUBLE PRECISION,
            mint_address TEXT,
            symbol TEXT,
            dex TEXT,
            decision TEXT,
            stage TEXT,
            reason TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_screening_timestamp ON screening_log(timestamp);
        CREATE TABLE IF NOT EXISTS watchlist (
            id SERIAL PRIMARY KEY,
            mint_address TEXT NOT NULL,
            symbol TEXT,
            pool_address TEXT,
            dex TEXT,
            deployer_wallet TEXT,
            added_at DOUBLE PRECISION,
            initial_filter_report TEXT,
            holders_at_add INTEGER DEFAULT 0,
            status TEXT DEFAULT 'watching'
        );
        CREATE TABLE IF NOT EXISTS app_logs (
            id SERIAL PRIMARY KEY,
            timestamp DOUBLE PRECISION,
            level TEXT,
            logger_name TEXT,
            message TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_app_logs_timestamp ON app_logs(timestamp);
    """
    # ننشئ البنية في كلا القاعدتين مباشرة (وليس عبر التبديل التلقائي)، لضمان
    # أن الاحتياطية جاهزة فعلياً بمجرد الحاجة، لا تُكتشف فارغة وقت الأزمة.
    await pool._ensure_pools()
    for p, name in [(pool._primary_pool, "الأساسية"), (pool._fallback_pool, "الاحتياطية")]:
        if p is None:
            continue
        try:
            async with p.acquire() as conn:
                await conn.execute(schema)
            logger.info(f"✅ تم إنشاء/تأكيد بنية الجداول في القاعدة {name}")
        except Exception as e:
            logger.error(f"⚠️ فشل إنشاء البنية في القاعدة {name}: {e}")


async def record_screening_result(mint_address, symbol, dex, decision, stage, reason):
    await pool.execute(
        """INSERT INTO screening_log
           (timestamp, mint_address, symbol, dex, decision, stage, reason)
           VALUES ($1, $2, $3, $4, $5, $6, $7)""",
        time.time(), mint_address, symbol, dex, decision, stage, reason,
    )


async def get_screening_stats(hours: int = 24) -> dict:
    cutoff = time.time() - (hours * 3600)

    total = await pool.fetchval(
        "SELECT COUNT(*) FROM screening_log WHERE timestamp > $1", cutoff
    )
    by_decision = await pool.fetch(
        """SELECT decision, COUNT(*) as c FROM screening_log
           WHERE timestamp > $1 GROUP BY decision ORDER BY c DESC""",
        cutoff,
    )
    top_reasons = await pool.fetch(
        """SELECT reason, COUNT(*) as c FROM screening_log
           WHERE timestamp > $1 AND decision = 'rejected'
           GROUP BY reason ORDER BY c DESC LIMIT 10""",
        cutoff,
    )
    added_list = await pool.fetch(
        """SELECT mint_address, symbol, timestamp FROM screening_log
           WHERE timestamp > $1 AND decision = 'added_to_watchlist'
           ORDER BY timestamp DESC""",
        cutoff,
    )

    return {
        "period_hours": hours,
        "total_screened": total or 0,
        "by_decision": [dict(r) for r in by_decision],
        "top_rejection_reasons": [dict(r) for r in top_reasons],
        "added_to_watchlist": [dict(r) for r in added_list],
    }


@dataclass
class TradeRecord:
    mint_address: str
    symbol: str
    capital_invested_sol: float
    entry_price: float
    filter_report: str
    tx_hash_entry: str
    entry_timestamp: float = None
    status: str = "open"

    def __post_init__(self):
        if self.entry_timestamp is None:
            self.entry_timestamp = time.time()


async def record_entry(trade: TradeRecord) -> int:
    row = await pool.fetchrow(
        """INSERT INTO trades
           (mint_address, symbol, entry_timestamp, capital_invested_sol,
            entry_price, status, filter_report, tx_hash_entry)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id""",
        trade.mint_address, trade.symbol, trade.entry_timestamp,
        trade.capital_invested_sol, trade.entry_price, trade.status,
        trade.filter_report, trade.tx_hash_entry,
    )
    return row["id"]


async def record_exit(trade_id, exit_price, proceeds_sol, close_reason, tx_hash_exit, flagged=False):
    row = await pool.fetchrow(
        "SELECT capital_invested_sol FROM trades WHERE id = $1", trade_id
    )
    capital = row["capital_invested_sol"] if row else 0
    profit_loss = proceeds_sol - capital
    status = "closed_flagged" if flagged else (
        "closed_profit" if profit_loss >= 0 else "closed_loss"
    )

    await pool.execute(
        """UPDATE trades SET exit_timestamp=$1, exit_price=$2, proceeds_sol=$3,
           profit_loss_sol=$4, status=$5, close_reason=$6, tx_hash_exit=$7
           WHERE id=$8""",
        time.time(), exit_price, proceeds_sol, profit_loss, status,
        close_reason, tx_hash_exit, trade_id,
    )
    return profit_loss


async def record_alert(trade_id, alert_type, message, requires_human_confirmation=False):
    await pool.execute(
        """INSERT INTO alerts (trade_id, timestamp, alert_type, message,
           requires_human_confirmation) VALUES ($1, $2, $3, $4, $5)""",
        trade_id, time.time(), alert_type, message, int(requires_human_confirmation),
    )


async def get_cumulative_performance() -> dict:
    row = await pool.fetchrow("""
        SELECT
            COUNT(*) as total_closed,
            SUM(CASE WHEN profit_loss_sol >= 0 THEN 1 ELSE 0 END) as winning_trades,
            SUM(CASE WHEN profit_loss_sol < 0 THEN 1 ELSE 0 END) as losing_trades,
            COALESCE(SUM(profit_loss_sol), 0) as total_profit_loss_sol,
            COALESCE(SUM(capital_invested_sol), 0) as total_capital_deployed_sol
        FROM trades
        WHERE status IN ('closed_profit', 'closed_loss', 'closed_flagged')
    """)

    total_closed = row["total_closed"] or 0
    winning = row["winning_trades"] or 0
    win_rate = (winning / total_closed * 100) if total_closed else 0.0

    return {
        "total_closed": total_closed,
        "winning_trades": winning,
        "losing_trades": row["losing_trades"] or 0,
        "total_profit_loss_sol": row["total_profit_loss_sol"] or 0.0,
        "total_capital_deployed_sol": row["total_capital_deployed_sol"] or 0.0,
        "win_rate_pct": win_rate,
    }


async def get_monthly_performance() -> dict:
    """
    الأداء منذ بداية الشهر التقويمي الحالي فقط — يُصفَّر تلقائياً بمجرد بدء
    شهر جديد (نحسب "بداية الشهر" ديناميكياً من الوقت الحالي في كل استدعاء،
    بدل تخزين عداد يحتاج إعادة ضبط يدوية عرضة للخطأ أو النسيان).
    """
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    month_start = datetime.datetime(now.year, now.month, 1, tzinfo=datetime.timezone.utc)
    month_start_ts = month_start.timestamp()

    row = await pool.fetchrow("""
        SELECT
            COUNT(*) as total_closed,
            SUM(CASE WHEN profit_loss_sol >= 0 THEN 1 ELSE 0 END) as winning_trades,
            SUM(CASE WHEN profit_loss_sol < 0 THEN 1 ELSE 0 END) as losing_trades,
            COALESCE(SUM(profit_loss_sol), 0) as total_profit_loss_sol
        FROM trades
        WHERE status IN ('closed_profit', 'closed_loss', 'closed_flagged')
          AND exit_timestamp >= $1
    """, month_start_ts)

    total_closed = row["total_closed"] or 0
    winning = row["winning_trades"] or 0
    win_rate = (winning / total_closed * 100) if total_closed else 0.0

    return {
        "month_label": month_start.strftime("%Y-%m"),
        "total_closed": total_closed,
        "winning_trades": winning,
        "losing_trades": row["losing_trades"] or 0,
        "total_profit_loss_sol": row["total_profit_loss_sol"] or 0.0,
        "win_rate_pct": win_rate,
    }


async def get_recent_logs(minutes: int = 60, level: str = None, limit: int = 500) -> list:
    """
    يرجع أحدث سجلات التطبيق مباشرة من قاعدة البيانات — بديل كامل عن الاعتماد
    على تصدير Railway (الذي يقتصر عادة على آخر ~1000 سطر فقط، أياً كانت
    المدة الزمنية الفعلية المطلوبة، مما تسبب في التباسات متكررة سابقاً).
    """
    cutoff = time.time() - (minutes * 60)
    if level:
        rows = await pool.fetch(
            """SELECT timestamp, level, logger_name, message FROM app_logs
               WHERE timestamp > $1 AND level = $2
               ORDER BY timestamp DESC LIMIT $3""",
            cutoff, level.upper(), limit,
        )
    else:
        rows = await pool.fetch(
            """SELECT timestamp, level, logger_name, message FROM app_logs
               WHERE timestamp > $1
               ORDER BY timestamp DESC LIMIT $2""",
            cutoff, limit,
        )
    return [dict(r) for r in rows]


async def get_open_trades():
    rows = await pool.fetch("SELECT * FROM trades WHERE status = 'open'")
    return [dict(r) for r in rows]


async def has_seen_mint_before(mint_address: str) -> bool:
    """
    يفحص إن كان يجب منع إعادة فتح صفقة لهذه العملة، مع تمييز مهم:

    1. حظر دائم مطلق: أي صفقة سابقة أُغلقت بعلامة "مُشبوهة" (closed_flagged
       — دليل حقيقي على تلاعب/احتيال مكتشف on-chain)، أو صفقة لا تزال مفتوحة
       حالياً (open) — لا استثناء إطلاقاً هنا.

    2. سماح مشروط بعد فترة تهدئة: صفقة سابقة أُغلقت بربح أو خسارة عادية
       (closed_profit / closed_loss، بدون أي دليل احتيال) لا تُحظر إعادة
       دخولها إلا خلال آخر MIN_COOLDOWN_HOURS_AFTER_NORMAL_CLOSE ساعة فقط —
       عملات meme قد تصعد على عدة موجات متكررة، وحظرها للأبد بعد أول جولة
       (رابحة أو خاسرة) يُفوّت فرصاً حقيقية بلا سبب أمان حقيقي.
    """
    row = await pool.fetchrow(
        """SELECT status, exit_timestamp FROM trades
           WHERE mint_address = $1
           ORDER BY entry_timestamp DESC LIMIT 1""",
        mint_address,
    )
    if row is None:
        return False  # لم تُشترَ هذه العملة إطلاقاً من قبل

    status = row["status"]

    if status == "open" or status == "closed_flagged":
        return True  # حظر دائم مطلق — لا استثناء

    # صفقة سابقة عادية (ربح/خسارة بدون شبهة) — نسمح بعد فترة تهدئة قصيرة
    exit_timestamp = row["exit_timestamp"] or 0
    hours_since_close = (time.time() - exit_timestamp) / 3600
    return hours_since_close < MIN_COOLDOWN_HOURS_AFTER_NORMAL_CLOSE
