"""
سكربت لمرة واحدة: يحذف قاعدة البيانات القديمة (بجداولها القديمة) ويُنشئ
واحدة جديدة فارغة بالبنية المحدثة (تشمل عمودي dex وdeployer_wallet في
جدول watchlist). استخدمه فقط عند الحاجة لبدء قاعدة البيانات من الصفر.
"""
import os
from db.trades import init_db, DB_PATH

if os.path.exists(DB_PATH):
    os.remove(DB_PATH)
    print(f"تم حذف قاعدة البيانات القديمة: {DB_PATH}")
else:
    print("لا توجد قاعدة بيانات قديمة — لا حاجة للحذف")

init_db()
print("تم إنشاء قاعدة بيانات جديدة فارغة بالبنية المحدثة بنجاح ✅")
