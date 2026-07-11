"""
توثيق كل صفقة في قاعدة بيانات SQLite بسيطة، تكفي للبداية والتحليل اللاحق.
هذا التوثيق ضروري لـ:
1. حساب الربح/الخسارة بدقة عند "تطهير رأس المال" من صفقة مشبوهة لاحقاً.
2. تحليل أداء الفلاتر لاحقاً وتحسينها بناءً على بيانات حقيقية.
"""
import os
import sqlite3
import time
from dataclasses import dataclass, asdict
from typing import Optional

DB_PATH = "logs/trades.db"


def init_db(db_path: str = DB_PATH):
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mint_address TEXT NOT NULL,
            symbol TEXT,
            entry_timestamp REAL,
            exit_timestamp REAL,
            capital_invested_sol REAL,
            entry_price REAL,
            exit_price REAL,
            proceeds_sol REAL,
            profit_loss_sol REAL,
            status TEXT,                -- open / closed_profit / closed_loss / closed_flagged
            close_reason TEXT,
            filter_report TEXT,         -- سجل نتائج الفلاتر عند الدخول (JSON نصي)
            tx_hash_entry TEXT,
            tx_hash_exit TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id INTEGER,
            timestamp REAL,
            alert_type TEXT,     -- onchain_auto_close / external_needs_review
            message TEXT,
            requires_human_confirmation INTEGER DEFAULT 0,
            resolved INTEGER DEFAULT 0,
            FOREIGN KEY(trade_id) REFERENCES trades(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS screening_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL,
            mint_address TEXT,
            symbol TEXT,
            dex TEXT,
            decision TEXT,        -- rejected / added_to_watchlist
            stage TEXT,           -- onchain / reputation / sell_simulation
            reason TEXT
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_screening_timestamp ON screening_log(timestamp)"
    )
    conn.commit()
    conn.close()


def record_screening_result(
    mint_address: str,
    symbol: str,
    dex: str,
    decision: str,
    stage: str,
    reason: str,
    db_path: str = DB_PATH,
):
    """
    يسجّل كل قرار فحص (رفض أو قبول) بشكل دائم في قاعدة البيانات — بدل الاعتماد
    فقط على نص اللوج الذي تفقده أدوات مثل Railway بعد فترة قصيرة بسبب كثرة
    الأسطر. هذا يسمح باستعلامات إحصائية دقيقة عن أي فترة زمنية مهما طالت.
    """
    conn = sqlite3.connect(db_path)
    conn.execute(
        """INSERT INTO screening_log
           (timestamp, mint_address, symbol, dex, decision, stage, reason)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (time.time(), mint_address, symbol, dex, decision, stage, reason),
    )
    conn.commit()
    conn.close()


def get_screening_stats(hours: int = 24, db_path: str = DB_PATH) -> dict:
    """
    يرجع ملخصاً إحصائياً لكل قرارات الفحص خلال آخر عدد ساعات محدد:
    - إجمالي عدد الفحوصات
    - عدد المضافة لـ watchlist مقابل المرفوضة
    - أكثر 10 أسباب رفض تكراراً (لمعرفة أين "عنق الزجاجة" الحالي دون قراءة آلاف الأسطر)
    """
    cutoff = time.time() - (hours * 3600)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    total = conn.execute(
        "SELECT COUNT(*) as c FROM screening_log WHERE timestamp > ?", (cutoff,)
    ).fetchone()["c"]

    by_decision = conn.execute(
        """SELECT decision, COUNT(*) as c FROM screening_log
           WHERE timestamp > ? GROUP BY decision ORDER BY c DESC""",
        (cutoff,),
    ).fetchall()

    top_reasons = conn.execute(
        """SELECT reason, COUNT(*) as c FROM screening_log
           WHERE timestamp > ? AND decision = 'rejected'
           GROUP BY reason ORDER BY c DESC LIMIT 10""",
        (cutoff,),
    ).fetchall()

    added_list = conn.execute(
        """SELECT mint_address, symbol, timestamp FROM screening_log
           WHERE timestamp > ? AND decision = 'added_to_watchlist'
           ORDER BY timestamp DESC""",
        (cutoff,),
    ).fetchall()

    conn.close()

    return {
        "period_hours": hours,
        "total_screened": total,
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


def record_entry(trade: TradeRecord, db_path: str = DB_PATH) -> int:
    conn = sqlite3.connect(db_path)
    cur = conn.execute(
        """INSERT INTO trades
           (mint_address, symbol, entry_timestamp, capital_invested_sol,
            entry_price, status, filter_report, tx_hash_entry)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (trade.mint_address, trade.symbol, trade.entry_timestamp,
         trade.capital_invested_sol, trade.entry_price, trade.status,
         trade.filter_report, trade.tx_hash_entry),
    )
    conn.commit()
    trade_id = cur.lastrowid
    conn.close()
    return trade_id


def record_exit(
    trade_id: int,
    exit_price: float,
    proceeds_sol: float,
    close_reason: str,
    tx_hash_exit: str,
    flagged: bool = False,
    db_path: str = DB_PATH,
):
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT capital_invested_sol FROM trades WHERE id = ?", (trade_id,)
    ).fetchone()
    capital = row[0] if row else 0
    profit_loss = proceeds_sol - capital
    status = "closed_flagged" if flagged else (
        "closed_profit" if profit_loss >= 0 else "closed_loss"
    )

    conn.execute(
        """UPDATE trades SET exit_timestamp=?, exit_price=?, proceeds_sol=?,
           profit_loss_sol=?, status=?, close_reason=?, tx_hash_exit=?
           WHERE id=?""",
        (time.time(), exit_price, proceeds_sol, profit_loss, status,
         close_reason, tx_hash_exit, trade_id),
    )
    conn.commit()
    conn.close()
    return profit_loss


def record_alert(
    trade_id: int,
    alert_type: str,
    message: str,
    requires_human_confirmation: bool = False,
    db_path: str = DB_PATH,
):
    conn = sqlite3.connect(db_path)
    conn.execute(
        """INSERT INTO alerts (trade_id, timestamp, alert_type, message,
           requires_human_confirmation) VALUES (?, ?, ?, ?, ?)""",
        (trade_id, time.time(), alert_type, message, int(requires_human_confirmation)),
    )
    conn.commit()
    conn.close()


def get_cumulative_performance(db_path: str = DB_PATH) -> dict:
    """
    يحسب الأداء التراكمي لكل الصفقات المغلقة حتى الآن — يُستخدم لعرض
    "معدل التقدم" في كل رسالة إغلاق صفقة عبر تيليجرام.
    """
    conn = sqlite3.connect(db_path)
    row = conn.execute("""
        SELECT
            COUNT(*) as total_closed,
            SUM(CASE WHEN profit_loss_sol >= 0 THEN 1 ELSE 0 END) as winning_trades,
            SUM(CASE WHEN profit_loss_sol < 0 THEN 1 ELSE 0 END) as losing_trades,
            COALESCE(SUM(profit_loss_sol), 0) as total_profit_loss_sol,
            COALESCE(SUM(capital_invested_sol), 0) as total_capital_deployed_sol
        FROM trades
        WHERE status IN ('closed_profit', 'closed_loss', 'closed_flagged')
    """).fetchone()
    conn.close()

    total_closed, winning, losing, total_pl, total_capital = row
    win_rate = (winning / total_closed * 100) if total_closed else 0.0

    return {
        "total_closed": total_closed or 0,
        "winning_trades": winning or 0,
        "losing_trades": losing or 0,
        "total_profit_loss_sol": total_pl or 0.0,
        "total_capital_deployed_sol": total_capital or 0.0,
        "win_rate_pct": win_rate,
    }


def get_open_trades(db_path: str = DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM trades WHERE status = 'open'").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def has_seen_mint_before(mint_address: str, db_path: str = DB_PATH) -> bool:
    """
    يفحص إن كانت هذه العملة ظهرت من قبل في trades (أي حالة: مفتوحة أو مغلقة)
    — يُستخدم لمنع "نسيان" العملات المرفوضة أو المُتاجَر بها سابقاً عند إعادة
    فحصها بالخطأ (مثلاً بسبب إعادة تشغيل البوت أو تكرار حدث من الشبكة).
    """
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT 1 FROM trades WHERE mint_address = ? LIMIT 1", (mint_address,)
    ).fetchone()
    conn.close()
    return row is not None
