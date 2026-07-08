# Sniper Bot — هيكل المشروع

بوت مراقبة وفلترة لعملات الميم الجديدة على Solana، وفق الاستراتيجية المتفق عليها:
**فلترة آلية صارمة عند الإطلاق → انتظار 24-72 ساعة (Watchlist) لمراجعة النمو العضوي
→ شراء → مراقبة مزدوجة مستمرة (on-chain آلي + خارجي بمراجعة بشرية).**

## هيكل المشروع

```
sniper_bot/
├── config/settings.py          # كل العتبات والإعدادات (جاهز بالكامل)
├── filters/
│   ├── onchain_filters.py      # فلاتر العرض/التوزيع/قابلية التحويل (منطق كامل، جاهز)
│   ├── reputation.py           # سجل المطور + RugCheck (منطق كامل + TODO لقاعدة بيانات rugs)
│   └── sell_simulation.py      # كشف honeypot (إطار عمل — يحتاج ربط Jupiter API)
├── monitor/
│   ├── mempool_listener.py     # استماع Helius WebSocket (إطار عمل — يحتاج استكمال)
│   ├── watchlist.py            # قائمة الانتظار 24-72h (منطق كامل + TODO لبيانات عضوية حقيقية)
│   └── post_trade_monitor.py   # المراقبة المزدوجة بعد الشراء (جاهز)
├── trading/executor.py         # تنفيذ الشراء/البيع (إطار عمل — يحتاج ربط swap فعلي)
├── alerts/notifier.py          # تنبيهات تيليجرام (جاهز بالكامل)
├── db/trades.py                # توثيق SQLite للصفقات والتنبيهات (جاهز بالكامل)
├── main.py                     # المنسّق الرئيسي
├── requirements.txt
└── .env.example
```

## ما هو جاهز فعلياً (منطق كامل، قابل للاختبار الوحدوي الآن)

- ✅ كل العتبات والمعايير المتفق عليها (`config/settings.py`)
- ✅ فلاتر العرض الثابت / الحرق / التوزيع / قابلية التحويل (`filters/onchain_filters.py`)
- ✅ منطق قائمة الانتظار والقرار (موافقة/رفض/انتهاء) (`monitor/watchlist.py`)
- ✅ المراقبة المزدوجة بعد الشراء مع مبدأ "تأكيد بشري ثم إغلاق آلي" (`monitor/post_trade_monitor.py`)
- ✅ توثيق كامل للصفقات (رأس المال، الربح/الخسارة، السبب) في SQLite (`db/trades.py`)
- ✅ رسائل تيليجرام لكل الحالات (فتح صفقة، تنبيه مراجعة، إغلاق تلقائي) (`alerts/notifier.py`)

## ما يحتاج إكمالاً تقنياً قبل أي تشغيل حقيقي (TODO محدد داخل كل ملف)

هذه النقاط **مقصودة** كأماكن حجز واضحة، وليست نقصاً عشوائياً — كل واحدة تحتاج
قراراً تقنياً منك (أي مكتبة/خدمة بالضبط) قبل أن أكتبها نهائياً:

1. **`filters/sell_simulation.py`**: ربط فعلي بـ Jupiter Aggregator API لبناء
   معاملة swap تجريبية وتمريرها لـ `simulateTransaction`.
2. **`monitor/mempool_listener.py` → `fetch_token_metadata`**: قراءة فعلية لحالة
   العقد (mint/freeze authority, توزيع الحيازة) عبر Helius RPC.
3. **`filters/reputation.py` → `check_deployer_history`**: مصدر بيانات فعلي
   لعناوين rug pull موثقة (قاعدة بيانات مجتمعية أو خدمة متخصصة).
4. **`monitor/watchlist.py` → `check_organic_growth`**: مصادر فعلية لعدد
   الحاملين ونسبة التداول العضوي (Helius + تحليل أنماط wash trading).
5. **`trading/executor.py`**: بناء وتوقيع وإرسال معاملات swap حقيقية
   (شراء/بيع عادي/بيع طارئ) عبر `solana-py`/`solders` + Jupiter API.
6. **`monitor/post_trade_monitor.py` → `check_onchain_signals`**: قراءة الحالة
   الحالية للعقد (ضريبة، LP، ownership) ومقارنتها بالحالة عند الدخول.
7. **`monitor/post_trade_monitor.py` → `check_external_signals`**: ربط بمصدر
   سمعة خارجي فعلي (API أو بحث آلي دوري).

## خطوات التشغيل المقترحة (بالترتيب)

1. `pip install -r requirements.txt`
2. انسخ `.env.example` إلى `.env` واملأ `HELIUS_API_KEY` و`TELEGRAM_BOT_TOKEN` على الأقل
   (اترك `USE_DEVNET=true` واترك `WALLET_PRIVATE_KEY` فارغاً في البداية)
3. أكمل نقاط TODO بالترتيب أعلاه — أنصح بالبدء بـ #2 و#3 (قراءة البيانات) لأنها
   أساس كل شيء آخر
4. اختبر كل وحدة بشكل منفصل (unit test) قبل تشغيل `main.py` كاملاً
5. شغّل على Devnet لأسبوعين على الأقل، راقب سجلات `logs/bot.log` و`logs/trades.db`
6. لا تنتقل لـ Mainnet إلا بمبالغ رمزية جداً في البداية (لا أكثر من تحمّلك لخسارتها بالكامل)
