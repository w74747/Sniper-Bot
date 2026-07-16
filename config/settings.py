"""
الإعدادات المركزية للبوت.
كل الأرقام والعتبات (Thresholds) هنا قابلة للتعديل بدون لمس منطق الكود في باقي الملفات.
"""
import os
from dataclasses import dataclass, field
from typing import List

# ── مفاتيح API (تُقرأ من متغيرات البيئة .env — لا تضع مفاتيح حقيقية هنا مباشرة) ──
# Alchemy: بديل مجاني بفريتير أسخى من Helius (30 مليون Compute Unit شهرياً مجاناً)
# Alchemy: بديل مجاني بفريتير أسخى (30 مليون Compute Unit شهرياً مجاناً).
# لا يدعم WebSocket Subscriptions لـ Solana (مؤكد رسمياً)، لكنه ممتاز
# كمصدر HTTP إضافي في التناوب — كان مُهملاً سابقاً رغم توفره فعلياً.
#
# مرونة مقصودة: إن وُضع ALCHEMY_RPC_URL صراحة (رابط كامل جاهز من لوحة
# Alchemy)، يُستخدم كما هو مباشرة. وإلا، يُبنى تلقائياً من ALCHEMY_API_KEY
# (المفتاح وحده يكفي بالصيغة القياسية).
_alchemy_rpc_explicit = os.getenv("ALCHEMY_RPC_URL", "").strip()
ALCHEMY_API_KEY = os.getenv("ALCHEMY_API_KEY", "").strip()
ALCHEMY_RPC_URL = _alchemy_rpc_explicit or f"https://solana-mainnet.g.alchemy.com/v2/{ALCHEMY_API_KEY}"
ALCHEMY_WS_URL = f"wss://solana-mainnet.g.alchemy.com/v2/{ALCHEMY_API_KEY}"

# GoPlus Security: بديل مجاني بالكامل لـ RugCheck — لا يحتاج اشتراكاً مدفوعاً
# مفتاح API اختياري (App Key/Secret) لرفع حد الطلبات، لكن الخدمة تعمل بدونه بحد أساسي مجاني
GOPLUS_APP_KEY = os.getenv("GOPLUS_APP_KEY", "").strip()
GOPLUS_APP_SECRET = os.getenv("GOPLUS_APP_SECRET", "").strip()
GOPLUS_API_BASE = "https://api.gopluslabs.io/api/v1"

# Helius: يُستخدم لـ WebSocket Subscriptions (logsSubscribe) ولجلب تفاصيل
# المعاملة فوراً (getTransaction) — لأن نفس المزود الذي "رأى" الحدث أولاً
# عبر الإشعار غالباً يملك تفاصيله فوراً، بخلاف مزود مختلف (Alchemy) قد
# يتأخر في فهرسة نفس المعاملة ببضع أجزاء من الثانية.
# Helius: يُستخدم لـ WebSocket Subscriptions (logsSubscribe) ولجلب تفاصيل
# المعاملة فوراً (getTransaction) — لأن نفس المزود الذي "رأى" الحدث أولاً
# عبر الإشعار غالباً يملك تفاصيله فوراً، بخلاف مزود مختلف (Alchemy) قد
# يتأخر في فهرسة نفس المعاملة ببضع أجزاء من الثانية.
#
# مرونة مقصودة: يقبل هذا المتغير إما المفتاح وحده (الصيغة الموصى بها)، أو
# الرابط الكامل كما يظهر في لوحة Helius مباشرة (يبدأ بـ https:// أو wss://)
# — كلاهما يعمل تلقائياً بدون أي استخراج يدوي مطلوب منك.
_helius_raw = os.getenv("HELIUS_API_KEY", "").strip()
if _helius_raw.startswith("http") or _helius_raw.startswith("wss://"):
    HELIUS_RPC_URL = _helius_raw.replace("wss://", "https://").replace("ws://", "http://")
    HELIUS_WS_URL = _helius_raw.replace("https://", "wss://").replace("http://", "ws://")
    HELIUS_API_KEY = _helius_raw.split("api-key=")[-1] if "api-key=" in _helius_raw else _helius_raw
else:
    HELIUS_API_KEY = _helius_raw
    HELIUS_RPC_URL = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
    HELIUS_WS_URL = f"wss://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"

# Chainstack: بديل احتياطي لـ Helius — حد معدل أعلى بكثير (25 طلب/ثانية
# مستمرة، بدل سقف شهري صارم). الرابط يحتوي المفتاح مدمجاً بداخله مباشرة
# (وليس معاملاً منفصلاً)، لذا نأخذه كاملاً كما هو من Railway Variables.
CHAINSTACK_RPC_URL = os.getenv("CHAINSTACK_RPC_URL", "").strip()
CHAINSTACK_WS_URL = os.getenv("CHAINSTACK_WS_URL", "").strip()

# Ankr: مصدر HTTP احتياطي إضافي (WebSocket يتطلب باقة مدفوعة، فلا نستخدمه هنا)
ANKR_RPC_URL = os.getenv("ANKR_RPC_URL", "").strip()

# GetBlock: مصدر HTTP واحتياطي WebSocket أيضاً — فريتير يومي (50 ألف CU/يوم)
GETBLOCK_RPC_URL = os.getenv("GETBLOCK_RPC_URL", "").strip()
GETBLOCK_WS_URL = os.getenv("GETBLOCK_WS_URL", "").strip()

# dRPC: أكبر حصة مجانية حتى الآن (210 مليون CU/شهرياً)، ويدعم WebSocket فعلياً
# على الفريتير (بخلاف Ankr وGetBlock اللذين يحصران WS بالباقات المدفوعة).
DRPC_API_KEY = os.getenv("DRPC_API_KEY", "").strip()
DRPC_RPC_URL = f"https://lb.drpc.live/solana/{DRPC_API_KEY}" if DRPC_API_KEY else ""
DRPC_WS_URL = f"wss://lb.drpc.live/solana/{DRPC_API_KEY}" if DRPC_API_KEY else ""

# Tatum: يُستخدم حصراً كـ"رأي ثانٍ مستقل" — تأكيد أخير قبل تنفيذ الشراء
# الفعلي مباشرة، وليس ضمن التناوب العام (حصته الصغيرة 100 ألف/شهرياً تناسب
# هذا الاستخدام النادر جداً تحديداً: مرة واحدة فقط لحظة اتخاذ قرار شراء).
# يتطلب Header مخصص (x-api-key) بدل تضمين المفتاح في الرابط كبقية المزودين.
TATUM_API_KEY = os.getenv("TATUM_API_KEY", "").strip()
TATUM_SOLANA_RPC_URL = "https://solana-mainnet.gateway.tatum.io/"

# DeepSeek: يُستخدم لتحليل ذكي دوري (كل ساعة) لحالة البوت العامة، عبر تلخيص
# إحصائيات الفحص + عيّنة من الأخطاء المهمة، وإرسال تقرير عربي مختصر لتيليجرام.
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_API_BASE = "https://api.deepseek.com"

# Solana العام: مزوّد Solana Foundation الرسمي، مجاني تماماً وبدون أي تسجيل أو
# مفتاح — لكن حدوده صارمة جداً ووثوقيته متذبذبة (مصمم للطوارئ/الاختبار وليس
# الاستخدام المكثف). نضعه كخيار احتياطي أخير في نهاية قائمة التناوب فقط،
# يُستخدم حين يفشل كل المزودين المدفوعين/المسجَّلين معاً.
SOLANA_PUBLIC_RPC_URL = "https://api.mainnet-beta.solana.com"
SOLANA_PUBLIC_WS_URL = "wss://api.mainnet-beta.solana.com"

# المزود الأساسي المُستخدم فعلياً: Chainstack إن أُضيف في Railway، وإلا
# Helius تلقائياً (بدون كسر أي شيء إن لم تُضِف Chainstack إطلاقاً).
PRIMARY_RPC_URL = CHAINSTACK_RPC_URL or HELIUS_RPC_URL
PRIMARY_WS_URL = CHAINSTACK_WS_URL or HELIUS_WS_URL

# ── حماية شاملة: كل مزوّد يُضاف لقائمة التناوب فقط إذا كانت بيانات اعتماده
# الفعلية موجودة، وليس فقط لأن الرابط الناتج "نص غير فارغ" ── هذا أصلحناه
# سابقاً لـAlchemy فقط، لكن نفس الخلل بالضبط كان موجوداً في Helius وGetBlock
# (رابط جاهز حتى بمفتاح فارغ، مثل ".../?api-key=" بلا شيء بعدها)، وسبّب
# فعلياً خطأ "401 missing api key" حين يصل دور هذا المزود في التناوب.
_helius_usable = HELIUS_RPC_URL if HELIUS_API_KEY else ""
_helius_ws_usable = HELIUS_WS_URL if HELIUS_API_KEY else ""
_getblock_usable = GETBLOCK_RPC_URL if GETBLOCK_RPC_URL else ""
_getblock_ws_usable = GETBLOCK_WS_URL if GETBLOCK_WS_URL else ""
_alchemy_usable = ALCHEMY_RPC_URL if (ALCHEMY_API_KEY or _alchemy_rpc_explicit) else ""

# قائمة تناوب لمزودي WebSocket — عند فشل أحدهم (403 منتهي الصلاحية، 429 حد
# معدل، إلخ) نتحول تلقائياً للتالي بدل التعطل الكامل بانتظار تدخل يدوي.
WS_ENDPOINTS = [
    url for url in [
        DRPC_WS_URL, CHAINSTACK_WS_URL, _helius_ws_usable,
        _getblock_ws_usable, SOLANA_PUBLIC_WS_URL,
    ]
    if url
]

# قائمة تناوب (Round-robin) بين كل مزودي HTTP المتاحين فعلياً — يُبنى تلقائياً
# من أي مزود أضفت مفتاحه في Railway، ويتجاهل الفارغ منها بصمت. عند فشل محاولة
# على مزود معيّن (مثلاً 429)، المحاولة التالية تجرّب مزوداً مختلفاً تماماً
# بدل الاصطدام بنفس القيد مرة أخرى. Solana العام دائماً آخر خيار (احتياطي أخير).
RPC_ENDPOINTS = [
    url for url in [
        DRPC_RPC_URL, CHAINSTACK_RPC_URL, _helius_usable, ANKR_RPC_URL,
        _getblock_usable, _alchemy_usable, SOLANA_PUBLIC_RPC_URL,
    ]
    if url
]

# Jupiter: تم إيقاف quote-api.jup.ag، والنطاق الجديد api.jup.ag يتطلب مفتاح API مجاني
# احصل عليه من portal.jup.ag
JUPITER_API_KEY = os.getenv("JUPITER_API_KEY", "")
JUPITER_API_BASE = "https://api.jup.ag"

# Birdeye: مصدر احتياطي جزئي (سعر فقط، فريتيره المجاني لا يشمل حجم/شراء-بيع)
# معطّل حالياً بانتظار تفعيله لاحقاً بعد تحقيق إيرادات — اتركه فارغاً
BIRDEYE_API_KEY = os.getenv("BIRDEYE_API_KEY", "").strip()
BIRDEYE_API_BASE = "https://public-api.birdeye.so"

# DexScreener: المصدر الأساسي لبيانات الزخم — مجاني بالكامل بدون مفتاح
DEXSCREENER_API_BASE = "https://api.dexscreener.com"

# قناة التنبيهات (مثال: بوت تيليجرام لإرسال الإشعارات)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# محفظة التداول (Devnet أولاً بشدة — لا تضع مفتاحاً حقيقياً هنا)
WALLET_PRIVATE_KEY = os.getenv("WALLET_PRIVATE_KEY", "")
USE_DEVNET = os.getenv("USE_DEVNET", "true").lower() == "true"

# فلاتر الشريعة الأساسية (كلمات محظورة: قمار، فوائد ربوية، محتوى غير لائق...)
# يمكن تعطيلها مؤقتاً عبر Railway Variables دون لمس الكود، ثم إعادة تفعيلها
# بنفس الطريقة في أي وقت — القيمة الافتراضية "مفعّل" دائماً إذا لم يُحدَّد المتغير.
SHARIA_FILTERS_ENABLED = os.getenv("SHARIA_FILTERS_ENABLED", "true").lower() == "true"


@dataclass
class FilterThresholds:
    """عتبات الفلترة عند اللحظة صفر (فلاتر آلية فورية قابلة للقياس)."""

    # 1) آلية الانكماش / العرض
    require_fixed_supply: bool = True          # يجب ألا يوجد mint إضافي بعد الإطلاق
    require_burn_or_lock: bool = True           # يجب وجود دالة حرق فعلية أو قفل سيولة
    min_lp_burned_or_locked_pct: float = 95.0    # % من LP يجب أن تكون محروقة/مقفلة

    # 2) عدم شبه بونزي في التوزيع
    max_dev_wallet_pct: float = 8.0              # أقصى نسبة يملكها المطور من العرض الكلي
    max_single_holder_pct: float = 8.0           # أقصى نسبة لأي محفظة غير المطور (عدا LP)
    forbid_referral_mechanics: bool = True       # رفض أي عقد فيه دالة "إحالة/عمولة" مبنية داخلياً

    # 3) قابلية الاستبدال والتحويل
    require_standard_token_program: bool = True  # يجب أن يتبع SPL Token القياسي (لا تعديل مخصص)
    forbid_transfer_restrictions: bool = True    # رفض أي قيود نقل مخفية (blacklist/whitelist دوال)

    # 4) سجل محفظة المطور (Deployer Reputation)
    check_deployer_history: bool = True
    max_allowed_prior_rugs: int = 0              # صفر تسامح: أي سجل rug سابق موثق = رفض فوري

    # 5) فحص الأمان العام عبر GoPlus
    min_security_score: float = 70.0             # الحد الأدنى لدرجة الأمان من GoPlus (0-100)

    # كلمات مفتاحية محظورة في الاسم/الوصف (فلترة شرعية أولية)
    forbidden_keywords: List[str] = field(default_factory=lambda: [
        "casino", "bet", "gambling", "dice", "roll", "slot", "lottery",
        "yield farm", "lending", "interest", "apr", "apy",
        "porn", "xxx", "nsfw",
    ])


@dataclass
class WatchlistSettings:
    """إعدادات مرحلة الانتظار والمراجعة بعد الفلترة الآلية (24-72 ساعة)."""

    min_watch_hours: int = 24
    max_watch_hours: int = 72
    min_organic_holders_growth: int = 8    # ملاحظة حاسمة: getTokenLargestAccounts يُرجع 20 حاملاً كحد أقصى (قيد
                                            # من Solana RPC نفسه) — أي رقم أعلى من ~15-18 هنا مستحيل التحقق رياضياً!
                                            # كان مضبوطاً سابقاً على 50 (خطأ حسابي جعل هذا الفحص عائقاً مطلقاً
                                            # يمنع أي صفقة من المسار العادي 24-72 ساعة من النجاح إطلاقاً).
    check_interval_minutes: int = 15       # كل كم دقيقة نعيد فحص الـ watchlist


@dataclass
class ExitStrategySettings:
    """إعدادات إدارة الصفقة بعد الدخول."""

    take_profit_first_leg_pct: float = 100.0  # (قديم، غير مُستخدَم فعلياً حالياً)

    # ═══ نموذج Scalping: جني ربح سريع صغير بدل انتظار موجة كبيرة ═══
    # الفلسفة: كثرة الصفقات الصغيرة الرابحة أهم من انتظار ربح كبير نادر.
    # بمجرد تحقيق هدف ربح متواضع، نخرج فوراً ونُحرّر رأس المال لصفقة تالية.
    scalp_take_profit_pct: float = 10.0        # جني ربح فوري عند +10% من سعر الدخول
    trailing_stop_pct: float = 7.0             # وقف متحرك أضيق (احتياطي إن لم يتحقق هدف السكالب بعد)
    max_drawdown_from_entry_pct: float = 20.0  # وقف خسارة أسرع — تحرير رأس المال من الصفقات الخاسرة بسرعة

    max_slippage_pct: float = 5.0             # الانزلاق المسموح عند التنفيذ العادي
    emergency_slippage_pct: float = 20.0      # الانزلاق المسموح عند الإغلاق الطارئ (خروج مضمون)

    # حماية رأس المال
    max_capital_pct_per_trade: float = 10.0    # أقصى نسبة من رأس المال الكلي لكل صفقة
    max_consecutive_losses: int = 5           # قاطع الدائرة (Circuit Breaker)
    circuit_breaker_cooldown_minutes: int = 120


@dataclass
class MomentumSettings:
    """
    عتبات رصد "الانطلاق الصاروخي" في أول دقائق — منفصلة تماماً عن فلاتر
    الأمان (GoPlus) وفلاتر watchlist طويلة الأمد. هذه تجيب سؤالاً مختلفاً:
    "هل هذه العملة تتحرك بقوة الآن؟" وليس "هل هي آمنة تقنياً؟".
    """
    # نافذة القياس الأساسية (5 دقائق) — الأنسب لرصد زخم لحظي جداً
    #
    # ملاحظة استراتيجية مهمة: خُفِّضت هذه العتبات بشكل كبير بعد اكتشاف تناقض
    # حقيقي في التصميم — كنا نطلب ارتفاعاً (+15%) أكبر من هدف الخروج السريع
    # نفسه (+10% scalp_take_profit_pct)! هذا يعني أننا كنا نُلاحق العملة
    # بعد أن ارتفعت فعلاً (وربما اقتربت من القمة)، بدل الدخول مبكراً في بداية
    # الحركة كما تقتضي فلسفة Scalping الحقيقية (دخول سريع + خروج سريع بربح
    # صغير). خفض العتبة يزيد عدد الفرص المُلتقَطة، ويعتمد على شبكة الأمان
    # القوية عند الخروج (جني ربح سريع + وقف متحرك ضيق + وقف خسارة صارم)
    # لإدارة المخاطرة، بدل الاعتماد فقط على تشديد شرط الدخول.
    min_price_change_m5_pct: float = 5.0       # ارتفاع سعر خلال آخر 5 دقائق (خُفِّض من 15%)
    min_buy_sell_ratio_m5: float = 1.2         # نسبة الشراء للبيع (خُفِّض من 1.5)
    min_volume_m5_usd: float = 1000.0          # حد أدنى لحجم التداول (خُفِّض من $2000)
    min_unique_buys_m5: int = 6                # حد أدنى لعدد معاملات الشراء (خُفِّض من 10)
    min_liquidity_usd: float = 2000.0          # حد أدنى للسيولة — لم نخفّضه كثيراً، فهذا خط الأمان
                                                # الحقيقي الوحيد ضد التلاعب السهل بعملة سيولتها ضئيلة جداً


MOMENTUM = MomentumSettings()


@dataclass
class FastTrackSettings:
    """
    إعدادات "المسار السريع" — دخول فوري متى ظهر زخم صاروخي حقيقي (momentum)
    مع اجتياز فحوصات الأمان الأساسية (GoPlus + محاكاة البيع)، بدل انتظار
    24-72 ساعة الكاملة. يعمل بالتوازي مع watchlist العادي دون التأثير عليه.
    """
    enabled: bool = True
    max_entry_age_minutes: int = 60      # لا نفحص زخم عملة عمرها أكثر من هذا (الفرصة غالباً فاتت)
    min_age_seconds_before_momentum_check: int = 75  # لا نفحص عملة أصغر من هذا — DexScreener
                                                      # يحتاج وقتاً لفهرسة السيولة/الحجم الحقيقيين،
                                                      # وفحص عملة عمرها ثوانٍ قليلة يُرجع دائماً تقريباً
                                                      # "$0 سيولة" (بيانات ناقصة، وليس حكماً حقيقياً).
    check_interval_seconds: int = 10     # سُرِّع من 30 إلى 10 لملاءمة إيقاع Scalping — رد فعل أسرع على الفرص


FAST_TRACK = FastTrackSettings()


@dataclass
class PostTradeMonitorSettings:
    """إعدادات المراقبة بعد الدخول (الطبقتان: on-chain آلية + خارجية دورية)."""

    onchain_check_interval_seconds: int = 5     # فحص on-chain كل كم ثانية
    external_check_interval_minutes: int = 60   # فحص المصادر الخارجية كل كم دقيقة

    # عتبات إغلاق تلقائي فوري (دليل on-chain قاطع — لا حاجة لمراجعة بشرية)
    # ملاحظة مهمة: رُفعت من 15% إلى 25% بعد ملاحظة أن ارتفاع الضريبة/تأثير
    # البيع خلال أول دقائق غالباً انزلاق سعري طبيعي (Price Impact) ناتج عن
    # زيادة التداول على Bonding Curve نفسه، وليس دليل احتيال حقيقي دائماً —
    # كان هذا يُغلق صفقات رابحة جداً (حتى +120% زخم) خلال دقائق قليلة فقط،
    # قبل أن يُتاح لها وقت كافٍ للصعود. وقف الخسارة المتحرك (trailing stop)
    # يبقى خط الدفاع الأساسي الأدق، القائم على السعر الفعلي وليس تقريب الضريبة.
    auto_close_on_tax_increase_above_pct: float = 25.0
    auto_close_on_lp_withdrawal: bool = True
    auto_close_on_ownership_change: bool = True

    # عتبات تنبيه فقط (دليل خارجي غير مؤكد — يتطلب تأكيد بشري قبل الإغلاق)
    alert_only_on_external_signal: bool = True


FILTERS = FilterThresholds()
WATCHLIST = WatchlistSettings()
EXIT_STRATEGY = ExitStrategySettings()
POST_TRADE_MONITOR = PostTradeMonitorSettings()

NETWORK = "solana"
DEX_ALLOWLIST = ["raydium", "pump.fun", "orca"]  # مجمعات سيولة نظيفة فقط
