"""
✅ دوال مساعدة في db/trades.py للتقييم المتكامل
أضفها في نهاية ملف trades.py الموجود
"""

# ============================================================================
# ✅ دوال جديدة للتقييم المتكامل (أضفها في نهاية trades.py)
# ============================================================================

async def get_trade_by_id(trade_id: int):
    """
    جلب صفقة واحدة حسب الـ ID
    
    Returns:
        dict: بيانات الصفقة أو None
    """
    try:
        pool = await get_pool()
        query = """
            SELECT 
                id, mint_address, symbol, entry_timestamp, exit_timestamp,
                capital_invested_sol, entry_price, exit_price, proceeds_sol,
                profit_loss_sol, status, close_reason, strategy,
                tx_hash_entry, tx_hash_exit
            FROM trades
            WHERE id = $1 AND status = 'open'
            LIMIT 1
        """
        row = await pool.fetchrow(query, trade_id)
        return dict(row) if row else None
    except Exception as e:
        logger.error(f"خطأ في جلب الصفقة {trade_id}: {e}")
        return None


async def get_closed_trades_recent(hours: int = 24, limit: int = 100):
    """
    جلب الصفقات المغلقة الحديثة
    
    Args:
        hours: عدد الساعات الماضية
        limit: الحد الأقصى للنتائج
    
    Returns:
        list: قائمة الصفقات المغلقة
    """
    try:
        pool = await get_pool()
        query = """
            SELECT 
                id, mint_address, symbol, entry_timestamp, exit_timestamp,
                capital_invested_sol, entry_price, exit_price, proceeds_sol,
                profit_loss_sol, status, close_reason, strategy
            FROM trades
            WHERE status = 'closed' 
                AND exit_timestamp > EXTRACT(EPOCH FROM NOW()) - ($1 * 3600)
            ORDER BY exit_timestamp DESC
            LIMIT $2
        """
        rows = await pool.fetch(query, hours, limit)
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"خطأ في جلب الصفقات المغلقة: {e}")
        return []


async def get_trades_by_strategy(strategy: str, limit: int = 50):
    """
    جلب الصفقات حسب الاستراتيجية
    
    Args:
        strategy: اسم الاستراتيجية
        limit: الحد الأقصى
    
    Returns:
        list: قائمة الصفقات
    """
    try:
        pool = await get_pool()
        query = """
            SELECT 
                id, mint_address, symbol, entry_timestamp, exit_timestamp,
                capital_invested_sol, entry_price, exit_price, proceeds_sol,
                profit_loss_sol, status, close_reason, strategy
            FROM trades
            WHERE strategy = $1
            ORDER BY entry_timestamp DESC
            LIMIT $2
        """
        rows = await pool.fetch(query, strategy, limit)
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"خطأ في جلب صفقات الاستراتيجية {strategy}: {e}")
        return []


async def get_error_logs_recent(hours: int = 24, limit: int = 100):
    """
    جلب السجلات الخطأ الحديثة
    
    Args:
        hours: عدد الساعات الماضية
        limit: الحد الأقصى
    
    Returns:
        list: قائمة الأخطاء
    """
    try:
        query = """
            SELECT 
                id, timestamp, logger_name, message, level
            FROM app_logs
            WHERE level = 'ERROR' 
                AND timestamp > NOW() - MAKE_INTERVAL(hours => $1)
            ORDER BY timestamp DESC
            LIMIT $2
        """
        rows = await pool.fetch(query, hours, limit)
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"خطأ في جلب السجلات: {e}")
        return []


async def save_trade_alert(trade_id: int, alert_type: str, message: str):
    """
    حفظ تنبيه لصفقة
    
    Args:
        trade_id: معرف الصفقة
        alert_type: نوع التنبيه (EVALUATION_WARNING, DANGER_SIGNAL, etc)
        message: نص التنبيه
    """
    try:
        pool = await get_pool()
        query = """
            INSERT INTO alerts (trade_id, timestamp, alert_type, message, requires_human_confirmation)
            VALUES ($1, EXTRACT(EPOCH FROM NOW()), $2, $3, 1)
        """
        await pool.execute(query, trade_id, alert_type, message)
        logger.debug(f"✅ تم حفظ التنبيه للصفقة {trade_id}")
    except Exception as e:
        logger.error(f"خطأ في حفظ التنبيه: {e}")


async def get_evaluation_history(trade_id: int, limit: int = 10):
    """
    جلب سجل التقييمات للصفقة
    
    Args:
        trade_id: معرف الصفقة
        limit: الحد الأقصى
    
    Returns:
        list: سجل التقييمات
    """
    try:
        pool = await get_pool()
        query = """
            SELECT 
                timestamp, pnl_pct, pnl_sol, evaluation_type, recommendation
            FROM trade_evaluations
            WHERE trade_id = $1
            ORDER BY timestamp DESC
            LIMIT $2
        """
        rows = await pool.fetch(query, trade_id, limit)
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"خطأ في جلب سجل التقييمات: {e}")
        return []


async def save_evaluation_snapshot(
    trade_id: int,
    pnl_pct: float,
    pnl_sol: float,
    evaluation_type: str,
    recommendation: str,
    age_hours: float
):
    """
    حفظ لقطة تقييم الصفقة
    
    Args:
        trade_id: معرف الصفقة
        pnl_pct: نسبة الربح/الخسارة
        pnl_sol: مبلغ الربح/الخسارة
        evaluation_type: نوع التقييم (STARTUP, PERIODIC, UPDATE)
        recommendation: التوصية
        age_hours: عمر الصفقة بالساعات
    """
    try:
        pool = await get_pool()
        query = """
            INSERT INTO trade_evaluations 
            (trade_id, timestamp, pnl_pct, pnl_sol, evaluation_type, recommendation, age_hours)
            VALUES ($1, EXTRACT(EPOCH FROM NOW()), $2, $3, $4, $5, $6)
        """
        await pool.execute(
            query,
            trade_id,
            pnl_pct,
            pnl_sol,
            evaluation_type,
            recommendation,
            age_hours
        )
    except Exception as e:
        logger.debug(f"خطأ في حفظ لقطة التقييم: {e}")


# ============================================================================
# إنشاء الجداول الجديدة (شغّل مرة واحدة)
# ============================================================================

async def initialize_evaluation_tables():
    """
    إنشاء جداول التقييم الجديدة
    شغّل هذه الدالة مرة واحدة عند بدء البوت
    """
    try:
        pool = await get_pool()
        
        # جدول سجل التقييمات
        await pool.execute("""
            CREATE TABLE IF NOT EXISTS trade_evaluations (
                id SERIAL PRIMARY KEY,
                trade_id INTEGER REFERENCES trades(id),
                timestamp DOUBLE PRECISION,
                pnl_pct DOUBLE PRECISION,
                pnl_sol DOUBLE PRECISION,
                evaluation_type TEXT,  -- STARTUP, PERIODIC, UPDATE
                recommendation TEXT,
                age_hours DOUBLE PRECISION,
                created_at TIMESTAMP DEFAULT NOW()
            );
        """)
        
        logger.info("✅ تم إنشاء جدول trade_evaluations")
        
    except Exception as e:
        logger.error(f"خطأ في إنشاء جداول التقييم: {e}")


# ============================================================================
# استدعاء التهيئة في البدء
# ============================================================================

# أضف في main.py أو startup:
# await initialize_evaluation_tables()
