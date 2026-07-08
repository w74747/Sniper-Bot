"""
توثيق كل صفقة في قاعدة بيانات SQLite بسيطة، تكفي للبداية والتحليل اللاحق.
هذا التوثيق ضروري لـ:
1. حساب الربح/الخسارة بدقة عند "تطهير رأس المال" من صفقة مشبوهة لاحقاً.
2. تحليل أداء الفلاتر لاحقاً وتحسينها بناءً على بيانات حقيقية.
"""
import sqlite3
import time
from dataclasses import dataclass, asdict
from typing import Optional

DB_PATH = "logs/trades.db"


def init_db(db_path: str = DB_PATH):
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
    conn.commit()
    conn.close()


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


def get_open_trades(db_path: str = DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM trades WHERE status = 'open'").fetchall()
    conn.close()
    return [dict(r) for r in rows]
