"""
✅ نظام التنبيهات الفورية الحرجة - بدون DeepSeek
تنبيهات فورية عند المشاكل الحقيقية فقط
"""

import logging
from typing import Dict, Optional
from datetime import datetime

logger = logging.getLogger("critical_alerts")


class CriticalAlertsSystem:
    """
    تنبيهات فورية بدون تأخير - للمشاكل الحقيقية فقط
    """
    
    @staticmethod
    async def alert_catastrophic_loss(trade_id: str, symbol: str, loss_pct: float):
        """خسارة كارثية > -50%"""
        message = (
            f"🔴 CATASTROPHIC LOSS\n"
            f"Trade ID: {trade_id}\n"
            f"Symbol: {symbol}\n"
            f"Loss: {loss_pct:.1f}%\n"
            f"Time: {datetime.now().isoformat()}"
        )
        logger.critical(message)
        await CriticalAlertsSystem._send_notification(message, severity="CRITICAL")
    
    @staticmethod
    async def alert_rpc_failure(provider: str, error: str):
        """فشل اتصال RPC"""
        message = (
            f"🔴 RPC PROVIDER DOWN\n"
            f"Provider: {provider}\n"
            f"Error: {error}\n"
            f"Time: {datetime.now().isoformat()}"
        )
        logger.critical(message)
        await CriticalAlertsSystem._send_notification(message, severity="CRITICAL")
    
    @staticmethod
    async def alert_unhandled_exception(component: str, error: str, traceback: str):
        """استثناء غير معالج"""
        message = (
            f"🔴 UNHANDLED EXCEPTION\n"
            f"Component: {component}\n"
            f"Error: {error}\n"
            f"Traceback: {traceback[:200]}...\n"
            f"Time: {datetime.now().isoformat()}"
        )
        logger.critical(message)
        await CriticalAlertsSystem._send_notification(message, severity="CRITICAL")
    
    @staticmethod
    async def alert_wallet_balance_zero(expected_balance: float):
        """المحفظة فارغة بشكل غير متوقع"""
        message = (
            f"🔴 WALLET BALANCE CRITICAL\n"
            f"Expected: {expected_balance:.4f} SOL\n"
            f"Actual: 0.0 SOL\n"
            f"Time: {datetime.now().isoformat()}"
        )
        logger.critical(message)
        await CriticalAlertsSystem._send_notification(message, severity="CRITICAL")
    
    @staticmethod
    async def alert_database_error(error: str):
        """خطأ في قاعدة البيانات"""
        message = (
            f"🔴 DATABASE ERROR\n"
            f"Error: {error}\n"
            f"Time: {datetime.now().isoformat()}"
        )
        logger.critical(message)
        await CriticalAlertsSystem._send_notification(message, severity="CRITICAL")
    
    @staticmethod
    async def _send_notification(message: str, severity: str = "INFO"):
        """إرسال إشعار (يمكن توسيعه لاحقاً: Telegram, Discord, Email)"""
        # TODO: إضافة Telegram Bot أو Discord Webhook
        logger.info(f"[{severity}] {message}")
