"""
📱 معالج أوامر التيليجرام
════════════════════════════════════════════════════════════════════

الأوامر المتاحة:
/status        → حالة النظام الحالية
/balance       → رصيد المحفظة
/trades-open   → قائمة الصفقات المفتوحة
/close-all     → إغلاق جميع الصفقات
/close <id>    → إغلاق صفقة محددة
/help          → قائمة المساعدة
"""

import logging
import asyncio
import json
from datetime import datetime

logger = logging.getLogger("telegram_commands")

# مححاكاة البوت (في الواقع، ستستخدم مكتبة python-telegram-bot)
# للآن، هذا مثال على البنية الأساسية


async def cmd_status() -> str:
    """يعرض حالة النظام الحالية"""
    from db.trades import get_cumulative_performance, get_monthly_performance, get_open_trades
    from recovery_close_trades import get_open_watchlist_count
    
    try:
        open_trades = await get_open_trades()
        cum_perf = await get_cumulative_performance()
        month_perf = await get_monthly_performance()
        watchlist_count = await get_open_watchlist_count()
        
        status = (
            f"<b>📊 حالة النظام</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            
            f"<b>📈 الصفقات:</b>\n"
            f"   مفتوحة الآن: {len(open_trades)}\n"
            f"   الإجمالي: {cum_perf.get('total_closed', 0)} مُغلقة\n"
            f"   رابحة: {cum_perf.get('winning_trades', 0)}\n"
            f"   خاسرة: {cum_perf.get('losing_trades', 0)}\n"
            f"   نسبة النجاح: {cum_perf.get('win_rate_pct', 0):.1f}%\n\n"
            
            f"<b>💰 الأداء:</b>\n"
            f"   إجمالي P/L: {cum_perf.get('total_profit_loss_sol', 0):.4f} SOL\n"
            f"   هذا الشهر: {month_perf.get('total_profit_loss_sol', 0):.4f} SOL\n\n"
            
            f"<b>👁️ المراقبة:</b>\n"
            f"   في watchlist: {watchlist_count}\n"
        )
        return status
    except Exception as e:
        return f"❌ خطأ: {str(e)[:100]}"


async def cmd_balance() -> str:
    """يعرض رصيد المحفظة"""
    from recovery_close_trades import print_wallet_status
    
    try:
        balance = await print_wallet_status()
        if balance is None:
            return "❌ تعذّر جلب الرصيد"
        return (
            f"<b>💰 رصيد المحفظة</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💎 SOL: <b>{balance:.4f}</b>\n"
        )
    except Exception as e:
        return f"❌ خطأ: {str(e)[:100]}"


async def cmd_trades_open() -> str:
    """يعرض قائمة الصفقات المفتوحة"""
    from recovery_close_trades import list_open_trades
    
    try:
        open_trades = await list_open_trades()
        
        if not open_trades:
            return "✅ لا توجد صفقات مفتوحة"
        
        text = (
            f"<b>📊 الصفقات المفتوحة ({len(open_trades)})</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
        )
        
        for i, trade in enumerate(open_trades, 1):
            age_seconds = 0
            if trade.get("entry_timestamp"):
                age_seconds = datetime.now().timestamp() - trade["entry_timestamp"]
                age_minutes = age_seconds / 60
                age_hours = age_seconds / 3600
                
                if age_hours >= 1:
                    age_str = f"{age_hours:.1f}h"
                else:
                    age_str = f"{age_minutes:.0f}m"
            else:
                age_str = "?"
            
            text += (
                f"[{i}] <b>#{trade['id']}</b> {trade['symbol']}\n"
                f"   💰 {trade['capital_invested_sol']:.4f} SOL\n"
                f"   📈 {trade['amount_bought']:.0f} tokens\n"
                f"   ⏰ {age_str}\n\n"
            )
        
        return text
    except Exception as e:
        return f"❌ خطأ: {str(e)[:100]}"


async def cmd_close_all() -> str:
    """إغلاق جميع الصفقات المفتوحة"""
    from recovery_close_trades import close_all_open_trades
    
    try:
        logger.warning("🚨 طلب إغلاق جميع الصفقات عبر التيليجرام")
        results = await close_all_open_trades()
        
        text = (
            f"<b>🔴 إغلاق الصفقات</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ مُغلقة: {results['closed']}/{results['total']}\n"
            f"❌ فشلت: {results['failed']}/{results['total']}\n\n"
        )
        
        if results["details"]:
            text += "<b>التفاصيل:</b>\n"
            for detail in results["details"]:
                text += f"• {detail['symbol']}: {detail['status']}\n"
        
        return text
    except Exception as e:
        return f"❌ خطأ: {str(e)[:100]}"


async def cmd_close_trade(trade_id: int) -> str:
    """إغلاق صفقة محددة"""
    from recovery_close_trades import close_trade_by_id
    
    try:
        logger.warning(f"🚨 طلب إغلاق الصفقة #{trade_id} عبر التيليجرام")
        success = await close_trade_by_id(trade_id)
        
        if success:
            return f"✅ تم إغلاق الصفقة #{trade_id} بنجاح"
        else:
            return f"❌ فشل إغلاق الصفقة #{trade_id}"
    except Exception as e:
        return f"❌ خطأ: {str(e)[:100]}"


async def cmd_help() -> str:
    """قائمة المساعدة والأوامر المتاحة"""
    return (
        "<b>📱 أوامر التيليجرام المتاحة</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        
        "<b>🔍 عرض المعلومات:</b>\n"
        "/status     - حالة النظام الحالية\n"
        "/balance    - رصيد المحفظة\n"
        "/trades-open - قائمة الصفقات المفتوحة\n\n"
        
        "<b>⚙️ التحكم:</b>\n"
        "/close-all     - إغلاق جميع الصفقات المفتوحة\n"
        "/close <id>    - إغلاق صفقة محددة (مثال: /close 5)\n\n"
        
        "<b>⚠️ تحذير:</b>\n"
        "أوامر الإغلاق لا يمكن الرجوع عنها!\n"
    )


# معالج أوامر التيليجرام (محاكاة للتطوير)
async def handle_telegram_command(command_text: str) -> str:
    """معالج الأوامر الرئيسي"""
    
    if not command_text:
        return await cmd_help()
    
    parts = command_text.strip().split()
    command = parts[0].lower()
    
    if command == "/status":
        return await cmd_status()
    
    elif command == "/balance":
        return await cmd_balance()
    
    elif command == "/trades-open":
        return await cmd_trades_open()
    
    elif command == "/close-all":
        return await cmd_close_all()
    
    elif command == "/close" and len(parts) > 1:
        try:
            trade_id = int(parts[1])
            return await cmd_close_trade(trade_id)
        except ValueError:
            return "❌ معرّف الصفقة يجب أن يكون رقماً (مثال: /close 5)"
    
    elif command == "/help":
        return await cmd_help()
    
    else:
        return f"❌ أمر غير معروف: {command}\n/help للحصول على قائمة الأوامر"


# ──────────────────────────────────────────────────────────────
# تكامل مع مكتبة python-telegram-bot (النسخة الفعلية)
# ──────────────────────────────────────────────────────────────

try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import (
        Application, CommandHandler, MessageHandler, filters, ContextTypes,
        ConversationHandler,
    )
    
    HAS_TELEGRAM_BOT = True
except ImportError:
    HAS_TELEGRAM_BOT = False
    logger.warning("⚠️ مكتبة python-telegram-bot غير مثبتة")


if HAS_TELEGRAM_BOT:
    async def telegram_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """معالج أمر /status"""
        response = await cmd_status()
        await update.message.reply_text(response, parse_mode="HTML")
    
    async def telegram_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """معالج أمر /balance"""
        response = await cmd_balance()
        await update.message.reply_text(response, parse_mode="HTML")
    
    async def telegram_trades_open(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """معالج أمر /trades-open"""
        response = await cmd_trades_open()
        await update.message.reply_text(response, parse_mode="HTML")
    
    async def telegram_close_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """معالج أمر /close-all (مع تأكيد)"""
        keyboard = [
            [
                InlineKeyboardButton("✅ نعم، أغلق الكل", callback_data="close_all_confirm"),
                InlineKeyboardButton("❌ إلغاء", callback_data="close_all_cancel"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "⚠️ هل تريد فعلاً إغلاق <b>جميع</b> الصفقات المفتوحة؟\nهذا لا يمكن الرجوع عنه!",
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
    
    async def telegram_close_trade(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """معالج أمر /close"""
        if not context.args or len(context.args) < 1:
            await update.message.reply_text("❌ يرجى تحديد رقم الصفقة: /close 5")
            return
        
        try:
            trade_id = int(context.args[0])
            keyboard = [
                [
                    InlineKeyboardButton(f"✅ نعم، أغلق #{trade_id}", callback_data=f"close_trade_confirm_{trade_id}"),
                    InlineKeyboardButton("❌ إلغاء", callback_data="close_trade_cancel"),
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                f"⚠️ هل تريد إغلاق الصفقة #{trade_id}؟",
                reply_markup=reply_markup,
            )
        except ValueError:
            await update.message.reply_text("❌ معرّف الصفقة يجب أن يكون رقماً")
    
    async def telegram_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """معالج أمر /help"""
        response = await cmd_help()
        await update.message.reply_text(response, parse_mode="HTML")
    
    async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """معالج الأزرار الديناميكية"""
        query = update.callback_query
        await query.answer()
        
        if query.data == "close_all_confirm":
            response = await cmd_close_all()
            await query.edit_message_text(response, parse_mode="HTML")
        
        elif query.data == "close_all_cancel":
            await query.edit_message_text("✅ تم الإلغاء")
        
        elif query.data.startswith("close_trade_confirm_"):
            trade_id = int(query.data.split("_")[-1])
            response = await cmd_close_trade(trade_id)
            await query.edit_message_text(response, parse_mode="HTML")
        
        elif query.data == "close_trade_cancel":
            await query.edit_message_text("✅ تم الإلغاء")
    
    async def run_telegram_bot():
        """تشغيل بوت التيليجرام"""
        from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
        
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            logger.warning("⚠️ بيانات التيليجرام غير مهيأة — بوت الأوامر معطّل")
            return
        
        app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        
        # الأوامر
        app.add_handler(CommandHandler("status", telegram_status))
        app.add_handler(CommandHandler("balance", telegram_balance))
        app.add_handler(CommandHandler("trades-open", telegram_trades_open))
        app.add_handler(CommandHandler("close-all", telegram_close_all))
        app.add_handler(CommandHandler("close", telegram_close_trade))
        app.add_handler(CommandHandler("help", telegram_help))
        
        # الأزرار
        app.add_handler(MessageHandler(filters.ALL, button_callback))
        
        logger.info("✅ بوت التيليجرام جاهز")
        await app.run_polling()
else:
    async def run_telegram_bot():
        """نسخة مبسطة بدون python-telegram-bot"""
        logger.info("⚠️ بوت التيليجرام معطّل (مكتبة غير مثبتة)")


async def run_telegram_command_handler():
    """حلقة معالج أوامر التيليجرام الرئيسية"""
    if HAS_TELEGRAM_BOT:
        await run_telegram_bot()
    else:
        logger.warning("⚠️ تيليجرام معطّل — ستحتاج لتثبيت: pip install python-telegram-bot")
        await asyncio.sleep(3600)  # نم لمدة ساعة
