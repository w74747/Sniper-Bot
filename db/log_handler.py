"""
معالج سجلات (Log Handler) مخصص يُخزّن كل رسالة لوج في قاعدة البيانات (نفس
Postgres الأساسية/الاحتياطية)، بديلاً كاملاً عن الاعتماد على تصدير Railway
الذي كان يقتصر عادة على آخر ~1000 سطر فقط بغض النظر عن المدة الزمنية
الفعلية المطلوبة — مصدر التباس متكرر طوال هذا المشروع.

التصميم: emit() نفسها سريعة تماماً وغير حاجزة (فقط تُضيف للطابور في الذاكرة،
بدون أي I/O)، بينما مهمة خلفية منفصلة تُفرّغ الطابور دفعات كل بضع ثوانٍ.
هذا يمنع أي تأخير على المسار الحرج بسبب الكتابة لقاعدة البيانات.
"""
import asyncio
import logging
import time

_log_queue: list = []
_MAX_QUEUE_SIZE = 5000  # حماية من نمو غير محدود لو تعطلت القاعدة لفترة طويلة
_BATCH_SIZE = 500


class DatabaseLogHandler(logging.Handler):
    """
    معالج بسيط جداً ومتزامن (Sync) عمداً — لا يُنفّذ أي عملية I/O داخل emit()
    نفسها، فقط يُضيف الرسالة لطابور في الذاكرة. هذا آمن للاستدعاء من أي مكان
    (متزامن أو غير متزامن) بدون قلق بشأن حجب حلقة الأحداث (event loop).
    """

    def emit(self, record: logging.LogRecord):
        try:
            message = self.format(record)
        except Exception:
            message = record.getMessage()

        if len(_log_queue) < _MAX_QUEUE_SIZE:
            _log_queue.append((time.time(), record.levelname, record.name, message))
        # عند امتلاء الطابور بالكامل (تعطّل القاعدة لفترة طويلة جداً)، نتجاهل
        # الرسائل الزائدة بصمت بدل استهلاك ذاكرة غير محدودة — الأولوية لبقاء
        # التطبيق يعمل، وليس لضمان عدم فقدان أي سطر لوج نادر الأهمية.


async def flush_log_queue_loop(interval_seconds: int = 5):
    """
    مهمة خلفية دائمة: تُفرّغ طابور السجلات إلى قاعدة البيانات كل بضع ثوانٍ.

    ملاحظة تصميم مهمة: لا نستخدم logger.error هنا عند فشل الكتابة نفسها —
    هذا قد يُنشئ حلقة تغذية راجعة لا نهائية (فشل الكتابة → تسجيل خطأ عن ذلك
    → دخول رسالة الخطأ نفسها للطابور → محاولة كتابتها لاحقاً... إلخ).
    """
    from db import pool  # استيراد مؤجَّل لتفادي حلقة استيراد دائرية

    while True:
        await asyncio.sleep(interval_seconds)

        if not _log_queue:
            continue

        batch = _log_queue[:_BATCH_SIZE]
        del _log_queue[:len(batch)]

        for timestamp, level, logger_name, message in batch:
            try:
                await pool.execute(
                    """INSERT INTO app_logs (timestamp, level, logger_name, message)
                       VALUES ($1, $2, $3, $4)""",
                    timestamp, level, logger_name, message[:2000],  # حد أقصى لطول الرسالة الواحدة
                )
            except Exception:
                pass  # صامت عمداً — راجع الملاحظة أعلاه


def install_database_log_handler(min_level=logging.INFO):
    """يُثبّت المعالج على الـ root logger — يُستدعى مرة واحدة فقط من main.py."""
    handler = DatabaseLogHandler()
    handler.setLevel(min_level)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logging.getLogger().addHandler(handler)
