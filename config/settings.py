"""
الإعدادات المركزية للبوت.
كل الأرقام والعتبات (Thresholds) هنا قابلة للتعديل بدون لمس منطق الكود في باقي الملفات.
"""
import os
from dataclasses import dataclass, field
from typing import List

# ── مفاتيح API (تُقرأ من متغيرات البيئة .env — لا تضع مفاتيح حقيقية هنا مباشرة) ──
# Alchemy: بديل مجاني بفريتير أسخى من Helius (30 مليون Compute Unit شهرياً مجاناً)
ALCHEMY_API_KEY = os.getenv("ALCHEMY_API_KEY", "")
ALCHEMY_RPC_URL = f"https://solana-mainnet.g.alchemy.com/v2/{ALCHEMY_API_KEY}"
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
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY", "").strip()
HELIUS_RPC_URL = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
HELIUS_WS_URL = f"wss://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"

# Chainstack: بديل احتياطي لـ Helius — حد معدل أعلى بكثير (25 طلب/ثانية
# مستمرة، بدل سقف شهري صارم). الرابط يحتوي المفتاح مدمجاً بداخله مباشرة
# (وليس معاملاً منفصلاً)، لذا نأخذه كاملاً كما هو من Railway Variables.
CHAINSTACK_RPC_URL = os.getenv("CHAINSTACK_RPC_URL", "").strip()
CHAINSTACK_WS_URL = os.getenv("CHAINSTACK_WS_URL", "").strip()

# المزود الأساسي المُستخدم فعلياً: Chainstack إن أُضيف في Railway، وإلا
# Helius تلقائياً (بدون كسر أي شيء إن لم تُضِف Chainstack إطلاقاً).
PRIMARY_RPC_URL = CHAINSTACK_RPC_URL or HELIUS_RPC_URL
PRIMARY_WS_URL = CHAINSTACK_WS_URL or HELIUS_WS_URL

# قائمة تناوب لمزودي WebSocket — عند فشل أحدهم (403 منتهي الصلاحية، 429 حد
# معدل، إلخ) نتحول تلقائياً للتالي بدل التعطل الكامل بانتظار تدخل يدوي.
WS_ENDPOINTS = [url for url in [CHAINSTACK_WS_URL, HELIUS_WS_URL] if url]

# Ankr: مصدر HTTP احتياطي إضافي (WebSocket يتطلب باقة مدفوعة، فلا نستخدمه هنا)
ANKR_RPC_URL = os.getenv("ANKR_RPC_URL", "").strip()

# GetBlock: مصدر HTTP احتياطي إضافي — فريتير يومي (50 ألف CU/يوم، 20 طلب/ثانية)
GETBLOCK_RPC_URL = os.getenv("GETBLOCK_RPC_URL", "").strip()

# Solana العام: مزوّد Solana Foundation الرسمي، مجاني تماماً وبدون أي تسجيل أو
# مفتاح — لكن حدوده صارمة جداً ووثوقيته متذبذبة (مصمم للطوارئ/الاختبار وليس
# الاستخدام المكثف). نضعه كخيار احتياطي أخير في نهاية قائمة التناوب فقط،
# يُستخدم حين يفشل كل المزودين المدفوعين/المسجَّلين معاً.
SOLANA_PUBLIC_RPC_URL = "https://api.mainnet-beta.solana.com"

# قائمة تناوب (Round-robin) بين كل مزودي HTTP المتاحين فعلياً — يُبنى تلقائياً
# من أي مزود أضفت مفتاحه في Railway، ويتجاهل الفارغ منها بصمت. عند فشل محاولة
# على مزود معيّن (مثلاً 429)، المحاولة التالية تجرّب مزوداً مختلفاً تماماً
# بدل الاصطدام بنفس القيد مرة أخرى. Solana العام دائماً آخر خيار (احتياطي أخير).
RPC_ENDPOINTS = [
    url for url in [
        CHAINSTACK_RPC_URL, HELIUS_RPC_URL, ANKR_RPC_URL,
        GETBLOCK_RPC_URL, SOLANA_PUBLIC_RPC_URL,
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
    min_organic_holders_growth: int = 50   # حد أدنى لعدد حاملين جدد "طبيعيين" خلال فترة المراقبة
    check_interval_minutes: int = 15       # كل كم دقيقة نعيد فحص الـ watchlist


@dataclass
class ExitStrategySettings:
    """إعدادات إدارة الصفقة بعد الدخول."""

    take_profit_first_leg_pct: float = 100.0  # عند مضاعفة السعر، اسحب رأس المال الأساسي
    trailing_stop_pct: float = 15.0           # وقف متحرك من أعلى قمة سعرية (بعد تحقيق ربح)
    max_drawdown_from_entry_pct: float = 30.0  # وقف خسارة صارم من سعر الدخول مباشرة (حماية من انهيار بدون أي ربح سابق)
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
    # ملاحظة: القيم الأصلية (30%, 2.0, $5000, 20) كانت صارمة جداً — نادراً ما
    # تتحقق كلها معاً، مما أدى لصفقات قليلة جداً رغم فحص آلاف العملات.
    # خُفِّضت الآن لتوازن بين اقتناص فرص حقيقية وعدم قبول أي شيء عشوائي.
    min_price_change_m5_pct: float = 15.0      # % ارتفاع سعر خلال آخر 5 دقائق
    min_buy_sell_ratio_m5: float = 1.5         # نسبة الشراء للبيع
    min_volume_m5_usd: float = 2000.0          # حد أدنى لحجم التداول بالدولار خلال 5 دقائق
    min_unique_buys_m5: int = 10               # حد أدنى لعدد معاملات الشراء خلال 5 دقائق
    min_liquidity_usd: float = 3000.0          # حد أدنى للسيولة (لا نخفّض هذا — حماية من التلاعب)


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
    check_interval_seconds: int = 30     # تكرار الفحص — أسرع بكثير من watchlist العادي (15 دقيقة)


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
