#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
unified_gold_bot.py  —  بوت البيتكوين الموحّد v3.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ثلاث استراتيجيات مدمجة + مشغّل ذكي + رسائل تفصيلية كاملة

  ① V7     EMA / RSI / MACD / BB / ADX / Stoch / PVP / Ichimoku / OBV / Divergence
  ② SMC    BOS / CHoCH / OB / FVG / Liquidity / Premium-Discount / MSS
  ③ OBinOB HTF OB inside LTF OB — 4 أزواج إطارات زمنية

جديد في v3.0:
  ✦ Ichimoku Cloud + OBV + Williams %R كمؤشرات إضافية في V7
  ✦ كشف Divergence (RSI + MACD) — إشارة انعكاس قوية
  ✦ مناطق Liquidity (Equal Highs/Lows) في SMC
  ✦ Premium / Discount Zones (50% Fibonacci)
  ✦ Market Structure Shift (MSS) — كسر القمة / القاع
  ✦ ثلاثة أهداف: TP1 / TP2 / TP3
  ✦ تقييم جلسة التداول (آسيا / لندن / نيويورك)
  ✦ رسائل تيليغرام تفصيلية بالكامل مع جدول المؤشرات
  ✦ نظام تسجيل الأداء المنفصل لكل استراتيجية فرعية
  ✦ Smart Trigger — فحص كل دقيقة، تشغيل فوري عند حدث مهم
"""

import os, time, json, logging, hashlib
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Optional, List, Tuple, Dict

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd
import numpy as np
import yfinance as yf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches

# ══════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════
def utcnow() -> datetime:
    return datetime.now(timezone.utc)

def utcnow_str() -> str:
    return utcnow().strftime("%Y-%m-%d %H:%M UTC")

def esc(t: str) -> str:
    return str(t).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def stars(v: float, mx: float = 10.0) -> str:
    n = min(round(v / (mx / 5)), 5)
    return "⭐" * n + "☆" * (5 - n)

def trading_session() -> str:
    h = utcnow().hour
    if 22 <= h or h < 7:   return "🌙 آسيا"
    if  7 <= h < 12:        return "🇬🇧 لندن"
    if 12 <= h < 17:        return "🗽 نيويورك (تداخل)"
    if 17 <= h < 22:        return "🗽 نيويورك"
    return "—"

# ══════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════
CFG_FILE = "btc_config.json"
DEF: Dict = {
    "TELEGRAM_TOKEN": "", "TELEGRAM_CHAT_ID": "",
    "SYMBOL": "BTC-USD", "DXY_SYMBOL": "DX-Y.NYB",
    "RUN_INTERVAL_MIN": 1,
    "DAILY_REPORT_HOUR_UTC": 20,
    "TG_MAX_RETRIES": 4, "TG_TIMEOUT": 20,
    # V7
    "ATR_SL_MULT": 1.5, "ATR_TP_MULT": 3.0,
    "MIN_STRATEGY_SCORE": 4, "MIN_TF_AGREE": 2, "MIN_RR": 1.5,
    # SMC
    "SMC_MIN_SCORE": 4, "SMC_CANDLES": 100,
    # OBinOB
    "OB_IMPULSE_ATR_MULT": 1.5, "OB_IMPULSE_CANDLES": 3,
    "OB_MAX_AGE_BARS": 80, "OB_OVERLAP_MIN_PCT": 0.30,
    "OB_TOUCH_BUFFER_PCT": 0.002, "OB_SL_BUFFER_PCT": 0.001,
    "OB_MIN_RR": 1.8,
    # Unified
    "UNIFIED_MIN_AGREE": 2, "PERF_FILE": "btc_performance.json",
    # Smart Trigger
    "TRIGGER_PRICE_CHANGE_PCT": 0.04,
    "TRIGGER_VOLUME_SPIKE_X": 1.8,
    "TRIGGER_NEW_CANDLE_5M": True,
    "TRIGGER_NEW_CANDLE_15M": True,
    "TRIGGER_FORCE_EVERY_MIN": 3,  # خُفِّض لـ 3 لضمان تشغيل ضمن 4 دقائق
    "CLAUDE_API_KEY": "",   # اختياري — مفتاح Anthropic أو PPQ.AI
    # مزوّد الـ AI — اختر واحداً:
    #   "anthropic" → مباشر من Anthropic (يحتاج بطاقة بنكية)
    #   "ppq"       → عبر PPQ.AI (يقبل USDT بدون بطاقة)
    "CLAUDE_PROVIDER": "auto",  # auto=مجاني أولاً | groq | openrouter | gemini | ppq | anthropic
    # اسم النموذج — اتركه فارغاً للقيمة الافتراضية
    "CLAUDE_MODEL": "",
}

cfg = DEF.copy()
if os.path.exists(CFG_FILE):
    with open(CFG_FILE, "r", encoding="utf-8") as f:
        cfg.update(json.load(f))

TG_TOKEN  = cfg["TELEGRAM_TOKEN"]
TG_CHAT   = cfg["TELEGRAM_CHAT_ID"]
SYMBOL    = cfg["SYMBOL"]
DXY_SYM   = cfg["DXY_SYMBOL"]
RUN_M     = int(cfg["RUN_INTERVAL_MIN"])
RPT_HOUR  = int(cfg["DAILY_REPORT_HOUR_UTC"])
TG_RET    = int(cfg["TG_MAX_RETRIES"])
TG_TMO    = int(cfg["TG_TIMEOUT"])
ATR_SL    = float(cfg["ATR_SL_MULT"])
ATR_TP    = float(cfg["ATR_TP_MULT"])
MIN_SC    = int(cfg["MIN_STRATEGY_SCORE"])
MIN_TF    = int(cfg["MIN_TF_AGREE"])
MIN_RR    = float(cfg["MIN_RR"])
SMC_SC    = int(cfg["SMC_MIN_SCORE"])
SMC_CN    = int(cfg["SMC_CANDLES"])
OB_IATR   = float(cfg["OB_IMPULSE_ATR_MULT"])
OB_IBAR   = int(cfg["OB_IMPULSE_CANDLES"])
OB_AGE    = int(cfg["OB_MAX_AGE_BARS"])
OB_OVL    = float(cfg["OB_OVERLAP_MIN_PCT"])
OB_TCH    = float(cfg["OB_TOUCH_BUFFER_PCT"])
OB_SLB    = float(cfg["OB_SL_BUFFER_PCT"])
OB_RR     = float(cfg["OB_MIN_RR"])
UNI_AGR   = int(cfg["UNIFIED_MIN_AGREE"])
PERF_FILE = cfg["PERF_FILE"]
TG_API    = f"https://api.telegram.org/bot{TG_TOKEN}"
TRIG_PCH  = float(cfg.get("TRIGGER_PRICE_CHANGE_PCT", 0.04))
TRIG_VOL  = float(cfg.get("TRIGGER_VOLUME_SPIKE_X", 1.8))
TRIG_C5M  = bool(cfg.get("TRIGGER_NEW_CANDLE_5M", True))
TRIG_C15M = bool(cfg.get("TRIGGER_NEW_CANDLE_15M", True))
TRIG_FM   = int(cfg.get("TRIGGER_FORCE_EVERY_MIN", 3))

os.makedirs("charts", exist_ok=True)
os.makedirs("logs",   exist_ok=True)

# ══════════════════════════════════════════════════════════════════
# LOGGING
# ══════════════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/bitcoin.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("BitcoinBot")

# ══════════════════════════════════════════════════════════════════
# TELEGRAM
# ══════════════════════════════════════════════════════════════════
SUBS_FILE = "btc_subscribers.json"
S_SIG = "signals"; S_ANA = "analysis"; S_ALL = "all"

def load_subs() -> dict:
    if os.path.exists(SUBS_FILE):
        with open(SUBS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    s: dict = {}
    if TG_CHAT:
        s[str(TG_CHAT)] = {"name":"المشرف","type":S_ALL,"active":True,"joined":utcnow().isoformat()}
        _save_subs(s)
    return s

def _save_subs(s: dict):
    with open(SUBS_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)

def add_sub(cid: str, name: str = "", st: str = S_ALL):
    s = load_subs()
    s[str(cid)] = {"name": name or str(cid), "type": st,
                   "active": True, "joined": utcnow().isoformat()}
    _save_subs(s)

def rem_sub(cid: str):
    s = load_subs()
    if str(cid) in s:
        s[str(cid)]["active"] = False; _save_subs(s)

def get_subs(flt: Optional[str] = None) -> List[str]:
    return [c for c, i in load_subs().items()
            if i.get("active") and (flt is None or i.get("type") in (flt, S_ALL))]

def _sess() -> requests.Session:
    s = requests.Session()
    r = Retry(total=TG_RET, backoff_factor=2,
              status_forcelist=[429,500,502,503,504], allowed_methods=["POST"])
    s.mount("https://", HTTPAdapter(max_retries=r))
    return s

def _send1(cid: str, text: str) -> bool:
    try:
        return _sess().post(TG_API+"/sendMessage",
            data={"chat_id":cid,"text":text,"parse_mode":"HTML"},
            timeout=TG_TMO).ok
    except: return False

def _photo1(cid: str, path: str, cap: str = "") -> bool:
    try:
        with open(path, "rb") as f:
            return _sess().post(TG_API+"/sendPhoto",
                files={"photo": f},
                data={"chat_id":cid,"caption":cap[:1024],"parse_mode":"HTML"},
                timeout=TG_TMO).ok
    except: return False

def tg_send(text: str, flt: Optional[str] = None) -> int:
    if not TG_TOKEN: return 0
    ok = 0
    for c in get_subs(flt):
        if _send1(c, text): ok += 1
        time.sleep(0.05)
    log.info(f"📤 Telegram {ok} رسالة"); return ok

def tg_photo(path: str, cap: str = "", flt: Optional[str] = None) -> int:
    if not TG_TOKEN: return 0
    ok = 0
    for c in get_subs(flt):
        if _photo1(c, path, cap): ok += 1
        time.sleep(0.05)
    return ok

def tg_check() -> bool:
    if not TG_TOKEN: log.error("❌ لا يوجد TELEGRAM_TOKEN"); return False
    try:
        r = requests.get(TG_API+"/getMe", timeout=TG_TMO)
        if r.ok:
            log.info(f"✅ Telegram متصل @{r.json().get('result',{}).get('username','?')}")
            return True
    except: pass
    log.error("❌ فشل الاتصال بـ Telegram"); return False

_uid = 0
def proc_cmds():
    global _uid
    try:
        r = requests.get(TG_API+"/getUpdates",
            params={"offset":_uid+1,"timeout":2}, timeout=10)
        if not r.ok: return
        for u in r.json().get("result", []):
            _uid = u["update_id"]
            if "callback_query" in u:
                try: handle_callback(u["callback_query"])
                except Exception as ce: log.debug("callback: "+str(ce))
                continue
            m = u.get("message") or u.get("channel_post")
            if not m: continue
            cid = str(m["chat"]["id"])
            nm  = m["chat"].get("first_name") or m["chat"].get("title") or cid
            txt = m.get("text","").strip()
            _handle_cmd(cid, nm, txt)
    except Exception as e: log.debug(f"proc_cmds: {e}")

def _handle_cmd(cid: str, nm: str, txt: str):
    cmds = {
        "/start":       (S_ALL,
            "🟠 <b>أهلاً بك في بوت البيتكوين الموحّد!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "بوت تحليل ذهب احترافي يعمل 24/7\n"
            "يجمع 4 استراتيجيات + ذكاء اصطناعي في منظومة واحدة\n\n"
            "📡 <b>الاستراتيجيات:</b>\n"
            "  ① V7  — 10 مؤشرات × 4 إطارات زمنية\n"
            "  ② SMC — Smart Money Concepts\n"
            "  ③ OBinOB — كتل الأوامر المتداخلة\n"
            "  ④ جلسة آسيا — انعكاس 02:00 UTC\n"
            "  🤖 Claude AI — محلّل ذكي اختياري\n\n"
            "🎯 إشارات بثلاثة أهداف + Stop Loss + R:R\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            "⚙️ <b>الأوامر:</b>\n"
            "/signals  — إشارات فقط\n"
            "/analysis — تحليلات فقط\n"
            "/all      — كل شيء\n"
            "/about    — وصف مفصّل للبوت\n"
            "/perf     — أداء الاستراتيجيات\n"
            "/support  — دعم المطوّر 💛\n"
            "/help     — دليل الاستخدام\n"
            "/stop     — إلغاء الاشتراك\n\n"
            "💛 أرسل /support إذا أفادك البوت!"),
        "/subscribe":   (S_ALL, None),
        "/signals":     (S_SIG, "📡 ستصلك إشارات الشراء/البيع فقط."),
        "/analysis":    (S_ANA, "📊 ستصلك التحليلات التفصيلية فقط."),
        "/all":         (S_ALL, "🔔 ستصلك جميع الرسائل."),
    }
    if txt in ("/start", "/subscribe"):
        add_sub(cid, nm, S_ALL)
        _send1(cid, cmds["/start"][1])
    elif txt in cmds and txt not in ("/start","/subscribe"):
        st, reply = cmds[txt]
        add_sub(cid, nm, st)
        if reply: _send1(cid, reply)
    elif txt in ("/stop", "/unsubscribe"):
        rem_sub(cid); _send1(cid, "❌ تم إلغاء اشتراكك. /start للعودة.")
    elif txt == "/status":
        info = load_subs().get(cid)
        msg  = (f"✅ <b>نشط</b> — نوع: {info.get('type','?')}\nمنذ: {info.get('joined','?')[:10]}"
                if info and info.get("active") else "❌ غير مشترك — أرسل /start")
        _send1(cid, msg)
    elif txt == "/perf":
        p = load_perf(); lines = ["📊 <b>أداء الاستراتيجيات:</b>"]
        for s in STRAT_NAMES:
            d = p.get(s, {"wins":0,"losses":0,"signals":0})
            tot = d["wins"] + d["losses"]
            wr  = f"{d['wins']/tot*100:.1f}%" if tot else "—"
            bar = "█"*int(d["wins"]/tot*10 if tot else 0) + "░"*(10-int(d["wins"]/tot*10 if tot else 0))
            lines.append(f"  <b>{esc(s)}</b>: {bar} {wr} ({d['wins']}✅ {d['losses']}❌)")
        _send1(cid, "\n".join(lines))
    elif txt == "/help":
        _send1(cid,
            "📖 <b>دليل الاستخدام الكامل</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "📌 <b>أوامر الاشتراك:</b>\n"
            "/start    — اشتراك واستقبال كل شيء\n"
            "/signals  — إشارات الشراء/البيع فقط\n"
            "/analysis — التحليلات التفصيلية فقط\n"
            "/all      — كل الرسائل\n"
            "/stop     — إلغاء الاشتراك\n\n"
            "📊 <b>أوامر المعلومات:</b>\n"
            "/status   — حالة اشتراكك الحالي\n"
            "/perf     — أداء كل استراتيجية\n"
            "/about    — وصف البوت والاستراتيجيات\n"
            "/support  — دعم المطوّر 💛\n\n"
            "🔔 <b>نظام الإشارات:</b>\n"
            f"الإشارة تصدر عند توافق {UNI_AGR}+ من 4 استراتيجيات\n"
            "  🟢 4/4 أو 3/4 ← إشارة قوية جداً\n"
            "  🟡 2/4 ← إشارة متوسطة\n\n"
            "⚡ <b>المشغّل الذكي:</b>\n"
            f"  فحص كل {RUN_M}د — يُشغَّل فوراً عند:\n"
            f"  • تغيّر سعر ≥{TRIG_PCH}%\n"
            f"  • ارتفاع الحجم ×{TRIG_VOL}\n"
            "  • إغلاق شمعة 5m أو 15m جديدة\n"
            f"  • تشغيل إجباري كل {TRIG_FM} دقيقة"
        )
    elif txt == "/about":
        _send1(cid,
            "✨ <b>بوت البيتكوين الموحّد — BTC/USD</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🟠 <b>ما هو هذا البوت؟</b>\n"
            "بوت تحليل ذهب احترافي يعمل على مدار الساعة، "
            "يجمع بين أقوى أساليب التحليل التقني الحديث في منظومة "
            "واحدة متكاملة، ليمنحك إشارات دقيقة مع إدارة كاملة للمخاطر.\n\n"
            "⚙️ <b>الاستراتيجيات الأربع:</b>\n\n"
            "① <b>V7 — متعدد الإطارات</b>\n"
            "   يحلّل 4 إطارات زمنية (5m/15m/1h/4h) بـ 10 مؤشرات:\n"
            "   EMA • RSI • MACD • Bollinger • ADX\n"
            "   Stochastic • PVP • Ichimoku • OBV • Williams %R\n"
            "   + كشف Divergence (انعكاس قوي)\n\n"
            "② <b>SMC — Smart Money Concepts</b>\n"
            "   يتتبّع أثر المؤسسات الكبرى في السوق:\n"
            "   BOS • CHoCH • MSS • Order Blocks\n"
            "   FVG • Liquidity Pools • Premium/Discount\n\n"
            "③ <b>OBinOB — كتل الأوامر المتداخلة</b>\n"
            "   يبحث عن كتلة HTF تحتوي كتلة LTF (4 أزواج)\n"
            "   أعلى دقة في تحديد مناطق الدخول\n\n"
            "④ <b>انعكاس جلسة آسيا</b>\n"
            "   يستغل نافذة 02:00–05:00 UTC\n"
            "   دخول عند 50% Retracement بعد CHoCH/BOS\n\n"
            "🤖 <b>Claude AI (اختياري)</b>\n"
            "   محلّل ذكي يراجع كل الإشارات ويصدر حكماً نهائياً\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🎯 <b>مميزات الإشارة:</b>\n"
            "  • ثلاثة أهداف: TP1 / TP2 / TP3\n"
            "  • Stop Loss محسوب بدقة\n"
            "  • نسبة R:R لكل إشارة\n"
            "  • رسم بياني احترافي مع كل إشارة\n"
            "  • تقرير أداء يومي تفصيلي\n\n"
            "⚡ <b>المشغّل الذكي:</b>\n"
            "  يراقب السوق كل دقيقة ويحلّل فوراً عند\n"
            "  أي حدث مهم بدون انتظار\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💛 أرسل /support لدعم المطوّر\n"
            "⚠️ <i>للأغراض التعليمية فقط — ليس توصية مالية</i>"
        )
    elif txt == "/support":
        _send1(cid,
            "💛 <b>دعم مطوّر البوت</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "شكراً لاستخدامك بوت البيتكوين الموحّد 🟠\n\n"
            "هذا البوت تم تطويره بجهد شخصي وبدون مقابل، "
            "ويعمل على مدار الساعة لتزويدك بأفضل تحليلات الذهب.\n\n"
            "إذا أفادك البوت وساعدك في قراراتك، "
            "يسعدني دعمك ولو بمبلغ رمزي 🙏\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💰 <b>التبرع عبر USDT</b>\n"
            "🔗 <b>الشبكة: BEP20 (BSC)</b>\n\n"
            "<code>0xB5B3BEEeAc48415536b5E777a5B850FdCf9A8159</code>\n\n"
            "⚠️ <b>تنبيه مهم:</b>\n"
            "تأكد من اختيار شبكة <b>BEP20 / BSC</b> عند الإرسال\n"
            "إرسال على شبكة أخرى قد يؤدي لفقدان الأموال\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            "كل مبلغ يُستخدم في:\n"
            "  🔹 تحسين الاستراتيجيات وإضافة مؤشرات جديدة\n"
            "  🔹 دعم Claude AI API للتحليل الذكي\n"
            "  🔹 استمرارية البوت وتطويره\n\n"
            "شكراً من القلب 💛 كل دعم يُفرق!"
        )

# ══════════════════════════════════════════════════════════════════
# PERFORMANCE
# ══════════════════════════════════════════════════════════════════
STRAT_NAMES = [
    "V7_EMA","V7_RSI","V7_MACD","V7_Bollinger","V7_ADX",
    "V7_Stoch","V7_PVP","V7_Ichimoku","V7_OBV","V7_WilliamsR",
    "V7_RSI_Divergence","V7_MACD_Divergence",
    "SMC_BOS","SMC_CHoCH","SMC_OB","SMC_FVG",
    "SMC_Liquidity","SMC_MSS","SMC_PremDisc",
    "OBinOB",
    "Asia_Reversal",
    "Range_Buy",
    "Range_Sell",
]

def load_perf() -> dict:
    if os.path.exists(PERF_FILE):
        with open(PERF_FILE,"r",encoding="utf-8") as f: return json.load(f)
    return {s:{"signals":0,"wins":0,"losses":0,"pending":[]} for s in STRAT_NAMES}

def save_perf(p: dict):
    with open(PERF_FILE,"w",encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False, indent=2)

def win_rate(p: dict, name: str) -> Optional[float]:
    d = p.get(name, {}); tot = d.get("wins",0)+d.get("losses",0)
    return d.get("wins",0)/tot*100 if tot else None

def rec_sig(p: dict, strat: str, side: int, entry: float, sl: float, tp: float, ts: str):
    if strat not in p:
        p[strat] = {"signals":0,"wins":0,"losses":0,"pending":[]}
    p[strat]["signals"] += 1
    p[strat]["pending"].append({"side":side,"entry":entry,"sl":sl,"tp":tp,"ts":ts,"result":None})
    save_perf(p)

def eval_pending(p: dict, price: float):
    chg = False
    for s in STRAT_NAMES:
        if s not in p: continue
        for sig in p[s].get("pending", []):
            if sig["result"]: continue
            if sig["side"] == 1:
                if   price >= sig["tp"]: sig["result"]="win";  p[s]["wins"]+=1;   chg=True
                elif price <= sig["sl"]: sig["result"]="loss"; p[s]["losses"]+=1; chg=True
            else:
                if   price <= sig["tp"]: sig["result"]="win";  p[s]["wins"]+=1;   chg=True
                elif price >= sig["sl"]: sig["result"]="loss"; p[s]["losses"]+=1; chg=True
        p[s]["pending"] = [x for x in p[s]["pending"] if not x["result"]]
    if chg: save_perf(p)

# ══════════════════════════════════════════════════════════════════
# DATA FETCH
# ══════════════════════════════════════════════════════════════════
def fetch(sym: str, period: str, interval: str) -> Optional[pd.DataFrame]:
    try:
        df = yf.download(sym, period=period, interval=interval, progress=False)
        if df is None or df.empty: return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        cols = ["Open","High","Low","Close","Volume"]
        if not all(c in df.columns for c in cols): return None
        df = df[cols].dropna().astype(float)
        return df.reset_index(drop=True) if len(df) >= 50 else None
    except: return None

def df2c(df: pd.DataFrame) -> list:
    return [{"o":r.Open,"h":r.High,"l":r.Low,"c":r.Close,"v":r.Volume}
            for _, r in df.iterrows()]

# ══════════════════════════════════════════════════════════════════
# INDICATORS
# ══════════════════════════════════════════════════════════════════
def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()

def rsi_fn(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff(); u = d.clip(lower=0); dw = -d.clip(upper=0)
    rs = u.ewm(com=n-1,adjust=False).mean() / dw.ewm(com=n-1,adjust=False).mean()
    return 100 - 100/(1+rs)

def macd_fn(s: pd.Series, f=12, sl=26, sg=9):
    ln = ema(s,f) - ema(s,sl); return ln, ema(ln,sg)

def bb_fn(s: pd.Series, n=20, k=2):
    m = s.rolling(n).mean(); std = s.rolling(n).std()
    return m+k*std, m, m-k*std

def stoch_fn(df: pd.DataFrame, k=14, d=3):
    lo=df["Low"].rolling(k).min(); hi=df["High"].rolling(k).max()
    pk=100*(df["Close"]-lo)/(hi-lo+1e-9); return pk, pk.rolling(d).mean()

def adx_fn(df: pd.DataFrame, n=14):
    hi=df["High"]; lo=df["Low"]; cl=df["Close"]
    tr=pd.concat([hi-lo,(hi-cl.shift()).abs(),(lo-cl.shift()).abs()],axis=1).max(axis=1)
    a=tr.ewm(alpha=1/n,adjust=False).mean()
    p=100*(hi.diff().clip(lower=0)).ewm(alpha=1/n,adjust=False).mean()/a
    m=100*((-lo.diff()).clip(lower=0)).ewm(alpha=1/n,adjust=False).mean()/a
    dx=100*(p-m).abs()/(p+m+1e-9)
    return dx.ewm(alpha=1/n,adjust=False).mean(), p, m

def atr_fn(df: pd.DataFrame, n=14) -> pd.Series:
    hi=df["High"]; lo=df["Low"]; cl=df["Close"]
    tr=pd.concat([hi-lo,(hi-cl.shift()).abs(),(lo-cl.shift()).abs()],axis=1).max(axis=1)
    return tr.ewm(alpha=1/n,adjust=False).mean()

def pvp_fn(df: pd.DataFrame, f=9, s=21):
    pc=df["Close"].pct_change().fillna(0); pvt=(df["Volume"]*pc).cumsum()
    pf=pvt.ewm(span=f,adjust=False).mean(); ps=pvt.ewm(span=s,adjust=False).mean()
    return pf, ps, pf-ps, pvt

def ichimoku_fn(df: pd.DataFrame):
    h9=df["High"].rolling(9).max(); l9=df["Low"].rolling(9).min()
    h26=df["High"].rolling(26).max(); l26=df["Low"].rolling(26).min()
    h52=df["High"].rolling(52).max(); l52=df["Low"].rolling(52).min()
    tenkan=(h9+l9)/2; kijun=(h26+l26)/2
    senkouA=((tenkan+kijun)/2).shift(26)
    senkouB=((h52+l52)/2).shift(26)
    chikou=df["Close"].shift(-26)
    return tenkan, kijun, senkouA, senkouB, chikou

def obv_fn(df: pd.DataFrame) -> pd.Series:
    direction = np.sign(df["Close"].diff().fillna(0))
    obv = (df["Volume"] * direction).cumsum()
    return obv

def williams_r(df: pd.DataFrame, n=14) -> pd.Series:
    hh=df["High"].rolling(n).max(); ll=df["Low"].rolling(n).min()
    return -100 * (hh - df["Close"]) / (hh - ll + 1e-9)

def detect_divergence(price: pd.Series, indicator: pd.Series,
                      lookback: int = 30) -> Tuple[bool,bool]:
    """
    Bullish Divergence: سعر يصنع قاعاً جديداً لكن المؤشر لا
    Bearish Divergence: سعر يصنع قمة جديدة لكن المؤشر لا
    Returns: (bull_div, bear_div)
    """
    p = price.tail(lookback); ind = indicator.tail(lookback)
    if len(p) < 10: return False, False
    p_lo1,p_lo2 = p.iloc[-5], p.min()
    i_lo1,i_lo2 = ind.iloc[-5], ind.iloc[p.idxmin() if p.idxmin() in ind.index else -1]
    bull_div = (p_lo1 < p_lo2) and (ind.iloc[-5] > ind.iloc[-1]) if len(ind)>=5 else False
    p_hi1,p_hi2 = p.iloc[-5], p.max()
    bear_div = (p_hi1 > p_hi2) and (ind.iloc[-5] < ind.iloc[-1]) if len(ind)>=5 else False
    return bool(bull_div), bool(bear_div)

def fibs_fn(df: pd.DataFrame, lb=80) -> dict:
    sub=df["Close"].tail(lb); hi=sub.max(); lo=sub.min(); d=hi-lo
    return {"0":hi,"236":hi-.236*d,"382":hi-.382*d,"500":hi-.5*d,
            "618":hi-.618*d,"786":hi-.786*d,"1000":lo}

def sw_hi(df: pd.DataFrame, l=3, r=3) -> list:
    return [i for i in range(l,len(df)-r)
            if all(df["High"].iloc[i]>df["High"].iloc[i-j] for j in range(1,l+1))
            and all(df["High"].iloc[i]>df["High"].iloc[i+j] for j in range(1,r+1))]

def sw_lo(df: pd.DataFrame, l=3, r=3) -> list:
    return [i for i in range(l,len(df)-r)
            if all(df["Low"].iloc[i]<df["Low"].iloc[i-j] for j in range(1,l+1))
            and all(df["Low"].iloc[i]<df["Low"].iloc[i+j] for j in range(1,r+1))]

# ══════════════════════════════════════════════════════════════════
# MODULE 1 — V7 v2: Multi-Timeframe + 10 Indicators + Divergence
# ══════════════════════════════════════════════════════════════════
V7_TFS = [("5m","15d"),("15m","30d"),("1h","90d"),("4h","360d")]

def _s_ema(df: pd.DataFrame) -> Tuple[int,str]:
    e50=ema(df["Close"],50); e100=ema(df["Close"],100); e200=ema(df["Close"],200)
    c=df["Close"].iloc[-1]
    if e50.iloc[-1]>e100.iloc[-1]>e200.iloc[-1] and c>e50.iloc[-1]:
        return 1,f"EMA تصاعدية 50>{e50.iloc[-1]:.1f} 100>{e100.iloc[-1]:.1f} 200"
    if e50.iloc[-1]<e100.iloc[-1]<e200.iloc[-1] and c<e50.iloc[-1]:
        return -1,f"EMA تنازلية 50<{e50.iloc[-1]:.1f} 100<{e100.iloc[-1]:.1f} 200"
    gap=abs(e50.iloc[-1]-e200.iloc[-1])/e200.iloc[-1]*100
    return 0,f"EMA غير متوافقة (فرق={gap:.2f}%)"

def _s_rsi(df: pd.DataFrame) -> Tuple[int,str]:
    r=rsi_fn(df["Close"]); v=r.iloc[-1]; p=r.iloc[-4]
    if v<35 and v>p:  return 1, f"RSI={v:.1f} تعافٍ قوي من ذروة البيع"
    if v>65 and v<p:  return -1,f"RSI={v:.1f} انعكاس من ذروة الشراء"
    if v<42: return 1, f"RSI={v:.1f} منطقة شراء"
    if v>58: return -1,f"RSI={v:.1f} منطقة بيع"
    return 0, f"RSI={v:.1f} محايد (42–58)"

def _s_macd(df: pd.DataFrame) -> Tuple[int,str]:
    ln,sg=macd_fn(df["Close"]); h=ln-sg
    if ln.iloc[-1]>sg.iloc[-1] and ln.iloc[-2]<=sg.iloc[-2]: return 1, f"MACD تقاطع صاعد h={h.iloc[-1]:.3f}"
    if ln.iloc[-1]<sg.iloc[-1] and ln.iloc[-2]>=sg.iloc[-2]: return -1,f"MACD تقاطع هابط h={h.iloc[-1]:.3f}"
    if ln.iloc[-1]>sg.iloc[-1] and h.iloc[-1]>h.iloc[-2]: return 1, f"MACD زخم صاعد h={h.iloc[-1]:.3f}"
    if ln.iloc[-1]<sg.iloc[-1] and h.iloc[-1]<h.iloc[-2]: return -1,f"MACD زخم هابط h={h.iloc[-1]:.3f}"
    return 0,f"MACD محايد h={h.iloc[-1]:.3f}"

def _s_bb(df: pd.DataFrame) -> Tuple[int,str]:
    up,md,lo=bb_fn(df["Close"]); r=rsi_fn(df["Close"]); c=df["Close"].iloc[-1]
    bw=(up.iloc[-1]-lo.iloc[-1])/md.iloc[-1]*100
    if c<lo.iloc[-1] and r.iloc[-1]<40: return 1, f"تحت BB السفلي ({lo.iloc[-1]:.2f}) BW={bw:.1f}%"
    if c>up.iloc[-1] and r.iloc[-1]>60: return -1,f"فوق BB العلوي ({up.iloc[-1]:.2f}) BW={bw:.1f}%"
    pos=("أسفل" if c<md.iloc[-1] else "أعلى")
    return (1 if c<md.iloc[-1] else -1), f"{pos} BB الوسط={md.iloc[-1]:.2f} BW={bw:.1f}%"

def _s_adx(df: pd.DataFrame) -> Tuple[int,str]:
    av,p,m=adx_fn(df); a=av.iloc[-1]; pv=p.iloc[-1]; mv=m.iloc[-1]
    if a>25 and pv>mv: return 1, f"ADX={a:.1f} (قوي) +DI={pv:.1f} يقود بفارق {pv-mv:.1f}"
    if a>25 and mv>pv: return -1,f"ADX={a:.1f} (قوي) -DI={mv:.1f} يقود بفارق {mv-pv:.1f}"
    if a>18 and pv>mv: return 1, f"ADX={a:.1f} +DI={pv:.1f}>{mv:.1f}"
    if a>18 and mv>pv: return -1,f"ADX={a:.1f} -DI={mv:.1f}>{pv:.1f}"
    return 0,f"ADX={a:.1f} ضعيف (تداول جانبي)"

def _s_stoch(df: pd.DataFrame) -> Tuple[int,str]:
    k,d=stoch_fn(df); kv=k.iloc[-1]; dv=d.iloc[-1]
    if kv<20 and kv>dv: return 1, f"Stoch K={kv:.1f} صاعد من ذروة بيع قوية"
    if kv>80 and kv<dv: return -1,f"Stoch K={kv:.1f} هابط من ذروة شراء قوية"
    if kv<35 and kv>dv: return 1, f"Stoch K={kv:.1f} شراء"
    if kv>65 and kv<dv: return -1,f"Stoch K={kv:.1f} بيع"
    return 0,f"Stoch K={kv:.1f} D={dv:.1f} محايد"

def _s_pvp(df: pd.DataFrame) -> Tuple[int,str]:
    if len(df)<30: return 0,"PVP: بيانات قليلة"
    pf,ps,ph,pvt=pvp_fn(df)
    fn=pf.iloc[-1]; fp=pf.iloc[-2]; sn=ps.iloc[-1]; sp=ps.iloc[-2]
    hn=ph.iloc[-1]; hp=ph.iloc[-2]; pn=pvt.iloc[-1]
    diff=(fn-sn)/(abs(sn)+1e-9)*100
    if fp<=sp and fn>sn and pn>0: return 1, f"PVP تقاطع صاعد hist={hn:+.0f} PVT موجب"
    if fp>=sp and fn<sn and pn<0: return -1,f"PVP تقاطع هابط hist={hn:+.0f} PVT سالب"
    if hn>hp and hn>0 and fn>sn: return 1, f"PVP زخم شراء ({diff:+.1f}%)"
    if hn<hp and hn<0 and fn<sn: return -1,f"PVP زخم بيع ({diff:+.1f}%)"
    if fn>sn: return 1, f"PVP فوق الإشارة ({diff:+.1f}%)"
    if fn<sn: return -1,f"PVP تحت الإشارة ({diff:+.1f}%)"
    return 0,"PVP محايد"

def _s_ichimoku(df: pd.DataFrame) -> Tuple[int,str]:
    if len(df)<52: return 0,"Ichimoku: بيانات غير كافية"
    tenkan,kijun,sA,sB,chikou=ichimoku_fn(df)
    c=df["Close"].iloc[-1]
    t=tenkan.iloc[-1]; k=kijun.iloc[-1]
    sA_=sA.iloc[-1] if not pd.isna(sA.iloc[-1]) else 0
    sB_=sB.iloc[-1] if not pd.isna(sB.iloc[-1]) else 0
    cloud_top=max(sA_,sB_); cloud_bot=min(sA_,sB_)
    above_cloud = c>cloud_top
    below_cloud = c<cloud_bot
    bull_cross = t>k
    if above_cloud and bull_cross and t>k:
        return 1, f"Ichi فوق السحابة ✅ TK={t:.1f}>{k:.1f} سحابة={cloud_bot:.1f}-{cloud_top:.1f}"
    if below_cloud and not bull_cross:
        return -1,f"Ichi تحت السحابة ✅ TK={t:.1f}<{k:.1f} سحابة={cloud_bot:.1f}-{cloud_top:.1f}"
    if c>cloud_top: return 1, f"Ichi فوق السحابة (ضعيف) سحابة={cloud_top:.1f}"
    if c<cloud_bot: return -1,f"Ichi تحت السحابة (ضعيف) سحابة={cloud_bot:.1f}"
    return 0,f"Ichi داخل السحابة {cloud_bot:.1f}-{cloud_top:.1f} (تردد)"

def _s_obv(df: pd.DataFrame) -> Tuple[int,str]:
    obv=obv_fn(df)
    obv_ema_f=ema(obv,10); obv_ema_s=ema(obv,25)
    trend_up   = obv_ema_f.iloc[-1]>obv_ema_s.iloc[-1]
    trend_cross= (obv_ema_f.iloc[-2]<=obv_ema_s.iloc[-2] and
                  obv_ema_f.iloc[-1]>obv_ema_s.iloc[-1])
    trend_drop = (obv_ema_f.iloc[-2]>=obv_ema_s.iloc[-2] and
                  obv_ema_f.iloc[-1]<obv_ema_s.iloc[-1])
    obv_val=obv.iloc[-1]/1e6
    if trend_cross: return 1,  f"OBV تقاطع صاعد ({obv_val:+.2f}M)"
    if trend_drop:  return -1, f"OBV تقاطع هابط ({obv_val:+.2f}M)"
    if trend_up:    return 1,  f"OBV صاعد — حجم يدعم الارتفاع ({obv_val:+.2f}M)"
    return -1, f"OBV هابط — حجم يدعم الانخفاض ({obv_val:+.2f}M)"

def _s_willr(df: pd.DataFrame) -> Tuple[int,str]:
    wr=williams_r(df); v=wr.iloc[-1]; p=wr.iloc[-4]
    if v<-80 and v>p: return 1,  f"Williams %R={v:.1f} تعافٍ من ذروة بيع"
    if v>-20 and v<p: return -1, f"Williams %R={v:.1f} انعكاس من ذروة شراء"
    if v<-60: return 1,  f"Williams %R={v:.1f} منطقة شراء"
    if v>-40: return -1, f"Williams %R={v:.1f} منطقة بيع"
    return 0, f"Williams %R={v:.1f} محايد"

def _s_rsi_div(df: pd.DataFrame) -> Tuple[int,str]:
    r=rsi_fn(df["Close"])
    bull,bear=detect_divergence(df["Close"],r,30)
    if bull: return 1,  f"RSI Divergence صاعد! — سعر أدنى + RSI أعلى → انعكاس محتمل"
    if bear: return -1, f"RSI Divergence هابط! — سعر أعلى + RSI أدنى → انعكاس محتمل"
    return 0, "RSI Divergence: لا انعكاس"

def _s_macd_div(df: pd.DataFrame) -> Tuple[int,str]:
    ln,_=macd_fn(df["Close"])
    bull,bear=detect_divergence(df["Close"],ln,30)
    if bull: return 1,  f"MACD Divergence صاعد! — تباعد إيجابي"
    if bear: return -1, f"MACD Divergence هابط! — تباعد سلبي"
    return 0,"MACD Divergence: لا تباعد"

V7_STRATS = [
    ("V7_EMA",            _s_ema,      2),
    ("V7_RSI",            _s_rsi,      1),
    ("V7_MACD",           _s_macd,     2),
    ("V7_Bollinger",      _s_bb,       1),
    ("V7_ADX",            _s_adx,      2),
    ("V7_Stoch",          _s_stoch,    1),
    ("V7_PVP",            _s_pvp,      2),
    ("V7_Ichimoku",       _s_ichimoku, 3),
    ("V7_OBV",            _s_obv,      2),
    ("V7_WilliamsR",      _s_willr,    1),
    ("V7_RSI_Divergence", _s_rsi_div,  3),
    ("V7_MACD_Divergence",_s_macd_div, 3),
]

def run_v7_on(df: pd.DataFrame) -> dict:
    out = {}
    for nm, fn, wt in V7_STRATS:
        try:   sig, rsn = fn(df)
        except Exception as e: sig, rsn = 0, f"خطأ: {e}"
        out[nm] = {"signal":sig, "reason":rsn, "weight":wt}
    return out

def dxy_bias() -> Tuple[int,str]:
    try:
        df=fetch(DXY_SYM,"5d","1h")
        if df is None: return 0,"DXY: لا بيانات"
        c=df["Close"].iloc[-1]; e20=ema(df["Close"],20).iloc[-1]
        chg=(c-df["Close"].iloc[-20])/df["Close"].iloc[-20]*100 if len(df)>=20 else 0
        if c<e20: return 1, f"DXY={c:.2f} تحت EMA20 ({e20:.2f}) ↓{abs(chg):.2f}% — يدعم الذهب"
        return -1, f"DXY={c:.2f} فوق EMA20 ({e20:.2f}) ↑{abs(chg):.2f}% — ضغط على الذهب"
    except: return 0,"DXY: خطأ في الجلب"

def analyze_v7() -> dict:
    tf_v={}; tf_res={}; df1h=None
    MAX_WEIGHT = sum(w for _,_,w in V7_STRATS)

    for iv, pd_ in V7_TFS:
        df=fetch(SYMBOL,pd_,iv)
        if iv=="1h": df1h=df
        if df is None: tf_v[iv]=0; tf_res[iv]={}; continue
        res=run_v7_on(df); tf_res[iv]=res
        buy_w  = sum(d["weight"] for d in res.values() if d["signal"]==1)
        sell_w = sum(d["weight"] for d in res.values() if d["signal"]==-1)
        tf_v[iv] = 1 if buy_w>sell_w and buy_w>=MAX_WEIGHT*0.35 else \
                  (-1 if sell_w>buy_w and sell_w>=MAX_WEIGHT*0.35 else 0)

    s1h=tf_res.get("1h",{})
    bt=sum(1 for v in tf_v.values() if v==1)
    st=sum(1 for v in tf_v.values() if v==-1)
    buy_w  = sum(d["weight"] for d in s1h.values() if d["signal"]==1)
    sell_w = sum(d["weight"] for d in s1h.values() if d["signal"]==-1)
    dxy,dxy_txt=dxy_bias()
    vote=0; score=0
    if bt>=MIN_TF and buy_w>=MAX_WEIGHT*0.35 and dxy>=0:
        vote=1; score=buy_w
    elif st>=MIN_TF and sell_w>=MAX_WEIGHT*0.35 and dxy<=0:
        vote=-1; score=sell_w

    entry=sl=tp=tp1=tp2=tp3=rr=None; vol_ok=False
    if vote and df1h is not None:
        pr=df1h["Close"].iloc[-1]; at=atr_fn(df1h).iloc[-1]; fb=fibs_fn(df1h)
        if vote==1:
            sl=max(pr-at*ATR_SL, fb["618"])
            tp1=pr+at*1.5; tp2=pr+at*ATR_TP; tp3=min(pr+at*4.5, fb["0"])
            tp=tp2
        else:
            sl=min(pr+at*ATR_SL, fb["382"])
            tp1=pr-at*1.5; tp2=pr-at*ATR_TP; tp3=max(pr-at*4.5, fb["1000"])
            tp=tp2
        entry=pr
        rr=round(abs(tp-entry)/(abs(sl-entry)+1e-9),2)
        vol_ok=df1h["Volume"].iloc[-1]>df1h["Volume"].rolling(20).mean().iloc[-1]*1.05
        if rr<MIN_RR: vote=0

    buy_c  = sum(1 for d in s1h.values() if d["signal"]==1)
    sell_c = sum(1 for d in s1h.values() if d["signal"]==-1)

    log.info(f"[V7] vote={vote} buy_w={buy_w}/{MAX_WEIGHT} tf={tf_v} dxy={dxy}")
    return {"vote":vote,"score":score,"max_weight":MAX_WEIGHT,
            "tf_v":tf_v,"strats":s1h,"df1h":df1h,"dxy":dxy,"dxy_txt":dxy_txt,
            "entry":entry,"sl":sl,"tp":tp,"tp1":tp1,"tp2":tp2,"tp3":tp3,
            "rr":rr,"vol_ok":vol_ok,"bt":bt,"st":st,
            "buy_w":buy_w,"sell_w":sell_w,"buy_c":buy_c,"sell_c":sell_c}

# ══════════════════════════════════════════════════════════════════
# MODULE 2 — SMC v2: Full Smart Money Analysis
# ══════════════════════════════════════════════════════════════════
def _detect_liquidity(candles: list) -> dict:
    """يكشف مناطق السيولة (Equal Highs / Equal Lows)"""
    tolerance = 0.0015
    n = len(candles)
    eq_highs=[]; eq_lows=[]
    highs=[c["h"] for c in candles[-30:]]
    lows =[c["l"] for c in candles[-30:]]
    for i in range(len(highs)-1):
        for j in range(i+1, len(highs)):
            if abs(highs[i]-highs[j])/highs[i]<tolerance:
                eq_highs.append(max(highs[i],highs[j]))
    for i in range(len(lows)-1):
        for j in range(i+1, len(lows)):
            if abs(lows[i]-lows[j])/lows[i]<tolerance:
                eq_lows.append(min(lows[i],lows[j]))
    return {"eq_highs": list(set([round(h,2) for h in eq_highs]))[-3:],
            "eq_lows":  list(set([round(l,2) for l in eq_lows]))[-3:]}

def _premium_discount(candles: list) -> dict:
    """50% بين أعلى وأدنى → Premium فوق / Discount تحت"""
    highs=[c["h"] for c in candles[-60:]]
    lows =[c["l"] for c in candles[-60:]]
    hi=max(highs); lo=min(lows); mid=(hi+lo)/2
    price=candles[-1]["c"]
    zone = "Discount 🟢 (تحت المنتصف — منطقة شراء)" if price<mid else "Premium 🔴 (فوق المنتصف — منطقة بيع)"
    dist_pct=(price-mid)/mid*100
    return {"hi":hi,"lo":lo,"mid":mid,"zone":zone,"dist_pct":dist_pct}

def analyze_smc(candles: list) -> dict:
    n=len(candles)
    _e={"vote":0,"score":0,"signal":"WAIT","entry":None,"sl":None,
        "tp":None,"tp1":None,"tp2":None,"tp3":None,"rr":None,
        "conf":0,"reasons":[],"details":{},"trend":"محايد","bos":None,
        "choch":None,"mss":None,"obs":[],"fvgs":[],"liq":{},"pd":{},
        "price":0}
    if n<30: return _e

    # ── Swing Points ──
    sh=[]; sl_=[]
    for i in range(3,n-3):
        h=candles[i]["h"]
        if all(h>candles[i-j]["h"] for j in range(1,4)) and all(h>candles[i+j]["h"] for j in range(1,4)):
            sh.append({"i":i,"p":h})
        l=candles[i]["l"]
        if all(l<candles[i-j]["l"] for j in range(1,4)) and all(l<candles[i+j]["l"] for j in range(1,4)):
            sl_.append({"i":i,"p":l})

    lc=candles[-1]["c"]; lh=sh[-4:]; ll=sl_[-4:]
    bos=None; choch=None; mss=None; score=0; reasons=[]

    # ── BOS (Break of Structure) ──
    if len(lh)>=2:
        p1,p2=lh[-2],lh[-1]
        if p2["p"]>p1["p"] and lc>p2["p"]:
            bos="BULL"
            score+=3; reasons.append(f"🟢 BOS صاعد — كسر قمة {p2['p']:.2f}")
        elif p2["p"]<p1["p"] and lc<p2["p"]:
            bos="BEAR"
            score-=3; reasons.append(f"🔴 BOS هابط — كسر قاع {p2['p']:.2f}")

    # ── CHoCH (Change of Character) ──
    if len(lh)>=2 and len(ll)>=2:
        h1,h2=lh[-2],lh[-1]; l1,l2=ll[-2],ll[-1]
        if h2["p"]<h1["p"] and l2["p"]<l1["p"] and lc>h2["p"]:
            choch="BULL"; score+=3; reasons.append(f"🟣 CHoCH تحوّل صاعد — قمم تنخفض + كسر")
        elif l2["p"]>l1["p"] and h2["p"]>h1["p"] and lc<l2["p"]:
            choch="BEAR"; score-=3; reasons.append(f"🟠 CHoCH تحوّل هابط — قيعان ترتفع + كسر")

    # ── MSS (Market Structure Shift) ──
    if len(ll)>=3:
        if ll[-1]["p"]>ll[-2]["p"]>ll[-3]["p"] and lc>lh[-1]["p"] if lh else False:
            mss="BULL"; score+=2; reasons.append(f"📈 MSS — هيكل سوق تحوّل صاعد")
    if len(lh)>=3:
        if lh[-1]["p"]<lh[-2]["p"]<lh[-3]["p"] and lc<ll[-1]["p"] if ll else False:
            mss="BEAR"; score-=2; reasons.append(f"📉 MSS — هيكل سوق تحوّل هابط")

    # ── Order Blocks ──
    obs=[]
    for i in range(3,n-2):
        c=candles[i]; nx=candles[i+1]
        body=abs(c["c"]-c["o"]); rng=c["h"]-c["l"]
        if rng==0: continue
        if body/rng>0.60:
            if c["c"]>c["o"] and nx["c"]>nx["o"]:
                obs.append({"t":"BULL","top":c["h"],"bot":c["l"],"mid":(c["h"]+c["l"])/2,"i":i,"body_pct":body/rng*100})
            elif c["c"]<c["o"] and nx["c"]<nx["o"]:
                obs.append({"t":"BEAR","top":c["h"],"bot":c["l"],"mid":(c["h"]+c["l"])/2,"i":i,"body_pct":body/rng*100})
    robs=obs[-5:]
    bull_ob=next((o for o in reversed(robs) if o["t"]=="BULL" and o["bot"]<lc<o["top"]*1.002),None)
    bear_ob=next((o for o in reversed(robs) if o["t"]=="BEAR" and o["bot"]*0.998<lc<o["top"]),None)
    if bull_ob: score+=2; reasons.append(f"🔷 على OB شرائي {bull_ob['bot']:.2f}–{bull_ob['top']:.2f} (جسم={bull_ob['body_pct']:.0f}%)")
    if bear_ob: score-=2; reasons.append(f"🔷 على OB بيعي {bear_ob['bot']:.2f}–{bear_ob['top']:.2f} (جسم={bear_ob['body_pct']:.0f}%)")

    # ── FVG (Fair Value Gap / Imbalance) ──
    fvgs=[]
    for i in range(1,n-1):
        pr=candles[i-1]; nx=candles[i+1]
        if nx["l"]>pr["h"]:
            gap_pct=(nx["l"]-pr["h"])/pr["h"]*100
            fvgs.append({"t":"BULL","top":nx["l"],"bot":pr["h"],"gap_pct":gap_pct})
        if nx["h"]<pr["l"]:
            gap_pct=(pr["l"]-nx["h"])/pr["l"]*100
            fvgs.append({"t":"BEAR","top":pr["l"],"bot":nx["h"],"gap_pct":gap_pct})
    rfvgs=fvgs[-4:]
    bull_fvg=next((f for f in reversed(rfvgs) if f["t"]=="BULL" and f["bot"]<=lc<=f["top"]),None)
    bear_fvg=next((f for f in reversed(rfvgs) if f["t"]=="BEAR" and f["bot"]<=lc<=f["top"]),None)
    if bull_fvg: score+=1; reasons.append(f"⬜ FVG صاعد {bull_fvg['bot']:.2f}–{bull_fvg['top']:.2f} ({bull_fvg['gap_pct']:.2f}%)")
    if bear_fvg: score-=1; reasons.append(f"⬜ FVG هابط {bear_fvg['bot']:.2f}–{bear_fvg['top']:.2f} ({bear_fvg['gap_pct']:.2f}%)")

    # ── Liquidity ──
    liq=_detect_liquidity(candles)
    for eqh in liq["eq_highs"]:
        if abs(lc-eqh)/eqh<0.003: score-=1; reasons.append(f"💧 سيولة عند قمة متساوية {eqh:.2f} — خطر اختراق هابط")
    for eql in liq["eq_lows"]:
        if abs(lc-eql)/eql<0.003: score+=1; reasons.append(f"💧 سيولة عند قاع متساوٍ {eql:.2f} — فرصة ارتداد صاعد")

    # ── Premium / Discount ──
    pd_=_premium_discount(candles)
    if pd_["zone"].startswith("Discount") and (bos=="BULL" or choch=="BULL"):
        score+=1; reasons.append(f"🎯 منطقة Discount {pd_['dist_pct']:+.2f}% من المنتصف — تأكيد الشراء")
    elif pd_["zone"].startswith("Premium") and (bos=="BEAR" or choch=="BEAR"):
        score-=1; reasons.append(f"🎯 منطقة Premium {pd_['dist_pct']:+.2f}% من المنتصف — تأكيد البيع")

    # ── الإشارة ──
    sig="WAIT"; entry=sl=tp=tp1=tp2=tp3=rr=None
    if score>=SMC_SC:
        sig="BUY"; entry=lc
        ref=bull_ob
        sl=(ref["bot"]-1.5) if ref else entry-10
        risk=entry-sl
        tp1=entry+risk*1.5; tp2=entry+risk*2.5; tp3=entry+risk*4.0; tp=tp2
        rr=round((tp-entry)/(risk+1e-9),2)
    elif score<=-SMC_SC:
        sig="SELL"; entry=lc
        ref=bear_ob
        sl=(ref["top"]+1.5) if ref else entry+10
        risk=sl-entry
        tp1=entry-risk*1.5; tp2=entry-risk*2.5; tp3=entry-risk*4.0; tp=tp2
        rr=round((entry-tp)/(risk+1e-9),2)

    vote=1 if sig=="BUY" else (-1 if sig=="SELL" else 0)
    trend=("صاعد ↑" if bos=="BULL" or choch=="BULL" or mss=="BULL"
           else "هابط ↓" if bos=="BEAR" or choch=="BEAR" or mss=="BEAR"
           else "محايد ↔")
    conf=min(95, abs(score)*10+30)

    log.info(f"[SMC] vote={vote} score={score} bos={bos} choch={choch} mss={mss}")
    return {"vote":vote,"score":score,"signal":sig,
            "entry":entry,"sl":sl,"tp":tp,"tp1":tp1,"tp2":tp2,"tp3":tp3,"rr":rr,
            "conf":conf,"reasons":reasons,"trend":trend,
            "bos":bos,"choch":choch,"mss":mss,"obs":robs,"fvgs":rfvgs,
            "liq":liq,"pd":pd_,"price":lc}

# ══════════════════════════════════════════════════════════════════
# MODULE 3 — OBinOB v2
# ══════════════════════════════════════════════════════════════════
@dataclass
class OB:
    tp: str; tf: str; hi: float; lo: float; mid: float
    idx: int; str_: float; method: str
    @property
    def size(self): return max(self.hi-self.lo,1e-6)
    def has(self,p,buf=0.): return self.lo*(1-buf)<=p<=self.hi*(1+buf)
    def overlap(self,o):
        ol=max(self.lo,o.lo); oh=min(self.hi,o.hi)
        return (oh-ol)/min(self.size,o.size+1e-9) if oh>ol else 0.

@dataclass
class OBSig:
    side:int; price:float; sl:float; tp:float; tp1:float; tp2:float; rr:float
    htf:OB; ltf:OB; ovl:float; strength:float; ts:str=""
    def sid(self): return f"{self.side}_{round(self.price)}_{self.htf.tf}_{self.ltf.tf}"

OB_SIG_FILE="btc_ob_signals.json"

def _ob_hist():
    if os.path.exists(OB_SIG_FILE):
        with open(OB_SIG_FILE,"r",encoding="utf-8") as f: return json.load(f)
    return {}

def _save_ob(sig):
    h=_ob_hist(); h[sig.sid()]={"side":sig.side,"price":sig.price,"sl":sig.sl,"tp":sig.tp,
        "rr":sig.rr,"htf":sig.htf.tf,"ltf":sig.ltf.tf,"ovl":sig.ovl,"str":sig.strength,"ts":sig.ts}
    with open(OB_SIG_FILE,"w",encoding="utf-8") as f: json.dump(h,f,ensure_ascii=False,indent=2)

def _is_dup(sig): return sig.sid() in _ob_hist()

def _detect_cls(df,tf,at):
    obs=[]; n=len(df); lb=min(n-OB_IBAR-1,OB_AGE)
    for i in range(n-OB_IBAR-1,n-lb-1,-1):
        if i<1: break
        av=at.iloc[i]; cur=df["Close"].iloc[-1]
        fb=df["Close"].iloc[i+OB_IBAR]-df["Close"].iloc[i]
        fbe=df["Close"].iloc[i]-df["Close"].iloc[i+OB_IBAR]
        if df["Close"].iloc[i]<df["Open"].iloc[i] and fb>OB_IATR*av:
            o=OB(tp="bull",tf=tf,hi=max(df["Open"].iloc[i],df["Close"].iloc[i]),
                lo=min(df["Open"].iloc[i],df["Close"].iloc[i]),mid=df["Close"].iloc[i],
                idx=i,str_=fb/(av+1e-9),method="classic")
            if cur>=o.lo: obs.append(o)
        if df["Close"].iloc[i]>df["Open"].iloc[i] and fbe>OB_IATR*av:
            o=OB(tp="bear",tf=tf,hi=max(df["Open"].iloc[i],df["Close"].iloc[i]),
                lo=min(df["Open"].iloc[i],df["Close"].iloc[i]),mid=df["Close"].iloc[i],
                idx=i,str_=fbe/(av+1e-9),method="classic")
            if cur<=o.hi: obs.append(o)
    return obs

def _detect_sw(df,tf,at):
    obs=[]; cur=df["Close"].iloc[-1]
    for idx in sw_lo(df):
        if idx<3 or idx>len(df)-4 or len(df)-1-idx>OB_AGE: continue
        ph=df["High"].iloc[idx+1:idx+6].max() if idx+6<=len(df) else df["High"].iloc[idx+1:].max()
        imp=ph-df["Low"].iloc[idx]; av=at.iloc[idx]
        if imp<OB_IATR*av: continue
        o=OB(tp="bull",tf=tf,hi=df["High"].iloc[idx],lo=df["Low"].iloc[idx],
            mid=(df["High"].iloc[idx]+df["Low"].iloc[idx])/2,idx=idx,str_=imp/(av+1e-9),method="swing")
        if cur>=o.lo: obs.append(o)
    for idx in sw_hi(df):
        if idx<3 or idx>len(df)-4 or len(df)-1-idx>OB_AGE: continue
        pl=df["Low"].iloc[idx+1:idx+6].min() if idx+6<=len(df) else df["Low"].iloc[idx+1:].min()
        imp=df["High"].iloc[idx]-pl; av=at.iloc[idx]
        if imp<OB_IATR*av: continue
        o=OB(tp="bear",tf=tf,hi=df["High"].iloc[idx],lo=df["Low"].iloc[idx],
            mid=(df["High"].iloc[idx]+df["Low"].iloc[idx])/2,idx=idx,str_=imp/(av+1e-9),method="swing")
        if cur<=o.hi: obs.append(o)
    return obs

def _dedup(obs):
    res=[]
    for o in obs:
        dup=False
        for ex in res:
            if o.tp==ex.tp and o.overlap(ex)>0.9:
                if o.str_>ex.str_: res.remove(ex)
                else: dup=True; break
        if not dup: res.append(o)
    return res

def detect_obs(df,tf):
    at=atr_fn(df); all_=_dedup(_detect_cls(df,tf,at)+_detect_sw(df,tf,at))
    cur=df["Close"].iloc[-1]
    all_.sort(key=lambda o:(abs(o.mid-cur)/(cur+1e-9),-o.str_))
    return all_

def _conf(htf_obs,ltf_obs,price):
    cs=[]
    for h in htf_obs:
        for l in ltf_obs:
            if h.tp!=l.tp: continue
            ovl=h.overlap(l)
            if ovl<OB_OVL: continue
            if l.has(price,OB_TCH) or (h.tp=="bull" and price>=h.lo and price<=h.hi*1.005) or \
               (h.tp=="bear" and price<=h.hi and price>=h.lo*0.995):
                cs.append((h,l,ovl))
    cs.sort(key=lambda x:(-x[2],-x[0].str_,abs(x[1].mid-price)))
    return cs

def _ob_sltp(ht,lt,price,df_l):
    at=atr_fn(df_l).iloc[-1]
    if ht.tp=="bull":
        e=lt.hi; sl=ht.lo*(1-OB_SLB)
        cds=[df_l["High"].iloc[i] for i in sw_hi(df_l) if df_l["High"].iloc[i]>e*1.002]
        tp2=min(cds) if cds else e+3*at; tp1=e+at*1.5
    else:
        e=lt.lo; sl=ht.hi*(1+OB_SLB)
        cds=[df_l["Low"].iloc[i] for i in sw_lo(df_l) if df_l["Low"].iloc[i]<e*0.998]
        tp2=max(cds) if cds else e-3*at; tp1=e-at*1.5
    rr=abs(tp2-e)/(abs(sl-e)+1e-9)
    return round(e,2),round(sl,2),round(tp2,2),round(tp1,2),round(rr,2)

def _ob_str(ht,lt,ovl,rr,price):
    s=min(ht.str_/3,3.)+min(lt.str_/3,2.)+ovl*3.+min((rr-OB_RR)*.5,1.5)
    if lt.has(price,OB_TCH): s+=.5
    return min(round(s,1),10.)

OB_PAIRS=[
    ("4h","360d","15m","30d","4h→15m"),
    ("4h","360d","5m","15d","4h→5m"),
    ("1h","90d","15m","30d","1h→15m"),
    ("1h","90d","5m","15d","1h→5m"),
]

def analyze_obinob() -> dict:
    best=None; best_pair=""; best_dfl=None
    for hi,hp,li,lp,lbl in OB_PAIRS:
        dfh=fetch(SYMBOL,hp,hi); dfl=fetch(SYMBOL,lp,li)
        if dfh is None or dfl is None: continue
        price=dfl["Close"].iloc[-1]
        hobs=detect_obs(dfh,hi); lobs=detect_obs(dfl,li)
        if not hobs or not lobs: continue
        for ht,lt,ovl in _conf(hobs,lobs,price):
            e,sl,tp,tp1,rr=_ob_sltp(ht,lt,price,dfl)
            if rr<OB_RR: continue
            side=1 if ht.tp=="bull" else -1
            st=_ob_str(ht,lt,ovl,rr,price)
            sig=OBSig(side=side,price=e,sl=sl,tp=tp,tp1=tp1,tp2=tp,rr=rr,
                      htf=ht,ltf=lt,ovl=ovl,strength=st,ts=utcnow().isoformat())
            if _is_dup(sig): continue
            if best is None or st>best.strength: best=sig; best_pair=lbl; best_dfl=dfl
            break
    vote=best.side if best else 0
    log.info(f"[OBinOB] vote={vote} pair={best_pair}" + (f" rr={best.rr:.2f} str={best.strength}/10" if best else ""))
    return {"vote":vote,"signal":best,"pair":best_pair,"dfl":best_dfl}



# ══════════════════════════════════════════════════════════════════
# MODULE 4 — Asia Session Reversal (انعكاس جلسة آسيا)
# ══════════════════════════════════════════════════════════════════
# المنطق:
#   02:00 UTC — بداية نافذة المراقبة (جلسة طوكيو/سنغافورة)
#   02:00–02:20 — رصد الـ Impulse Move الأولي
#   02:20–02:45 — انتظار CHoCH أو BOS على 1m/5m
#   بعد CHoCH   — دخول عند 50% retracement من حركة الاختراق
#   SL           — خلف الـ Swing High/Low الخارجي
#   TP           — 50% من امتداد الشمعة الساعية + TP2 الكامل

ASIA_WINDOW_START_H = 2    # 02:00 UTC
ASIA_WINDOW_END_H   = 5    # 05:00 UTC (تُلغى بعدها)
ASIA_IMPULSE_MIN    = 20   # دقيقة — نافذة رصد الـ Impulse
ASIA_MIN_IMPULSE_PIPS = 50.0  # أدنى حركة impulse بالدولار
ASIA_RETRACE_PCT    = 0.50   # نسبة التصحيح للدخول (50%)
ASIA_TP_PCT         = 0.50   # نسبة الهدف من الشمعة الساعية
ASIA_MIN_RR         = 1.5    # أدنى R:R مقبول


def _asia_session_active() -> bool:
    """هل نحن داخل نافذة جلسة آسيا؟"""
    h = utcnow().hour
    return ASIA_WINDOW_START_H <= h < ASIA_WINDOW_END_H


def _detect_impulse(df1m: pd.DataFrame) -> Optional[dict]:
    """
    يرصد الـ Impulse Move الأولي في أول 20 دقيقة من الجلسة.
    يعيد dict يحتوي: direction, high, low, size
    """
    if df1m is None or len(df1m) < 5:
        return None

    # آخر 20 شمعة = أول 20 دقيقة
    window = df1m.tail(20)
    hi  = float(window["High"].max())
    lo  = float(window["Low"].min())
    op  = float(window["Open"].iloc[0])
    cl  = float(window["Close"].iloc[-1])
    rng = hi - lo

    if rng < ASIA_MIN_IMPULSE_PIPS:
        return None  # حركة ضعيفة جداً

    # اتجاه الـ impulse
    if cl > op and (cl - op) / rng > 0.5:
        direction = 1   # صاعد
    elif cl < op and (op - cl) / rng > 0.5:
        direction = -1  # هابط
    else:
        return None  # غير واضح

    return {"direction": direction, "high": hi, "low": lo,
            "open": op, "close": cl, "range": rng}


def _detect_choch_bos(df1m: pd.DataFrame, impulse: dict) -> Optional[dict]:
    """
    يكشف CHoCH أو BOS على إطار 1m بعد الـ Impulse.
    يعيد: type (CHoCH/BOS), direction, level, bar_idx
    """
    if df1m is None or len(df1m) < 10:
        return None

    recent = df1m.tail(30)
    highs  = recent["High"].values
    lows   = recent["Low"].values
    closes = recent["Close"].values
    n      = len(recent)

    imp_dir = impulse["direction"]

    # ابحث عن Swing Highs/Lows في آخر 30 شمعة
    swing_hs = [i for i in range(2, n-2)
                if highs[i] > highs[i-1] and highs[i] > highs[i-2]
                and highs[i] > highs[i+1] and highs[i] > highs[i+2]]
    swing_ls = [i for i in range(2, n-2)
                if lows[i] < lows[i-1] and lows[i] < lows[i-2]
                and lows[i] < lows[i+1] and lows[i] < lows[i+2]]

    last_close = closes[-1]

    # CHoCH هابط بعد impulse صاعد: السعر يكسر أدنى swing low
    if imp_dir == 1 and len(swing_ls) >= 2:
        last_sl = lows[swing_ls[-1]]
        if last_close < last_sl:
            return {"type": "CHoCH", "direction": -1,
                    "level": last_sl, "bar_idx": swing_ls[-1]}

    # CHoCH صاعد بعد impulse هابط: السعر يكسر أعلى swing high
    if imp_dir == -1 and len(swing_hs) >= 2:
        last_sh = highs[swing_hs[-1]]
        if last_close > last_sh:
            return {"type": "CHoCH", "direction": 1,
                    "level": last_sh, "bar_idx": swing_hs[-1]}

    # BOS — كسر هيكل في نفس اتجاه الـ impulse
    if imp_dir == 1 and len(swing_hs) >= 2:
        prev_sh = highs[swing_hs[-2]]
        last_sh = highs[swing_hs[-1]]
        if last_sh > prev_sh and last_close > last_sh:
            return {"type": "BOS", "direction": 1,
                    "level": last_sh, "bar_idx": swing_hs[-1]}

    if imp_dir == -1 and len(swing_ls) >= 2:
        prev_sl = lows[swing_ls[-2]]
        last_sl = lows[swing_ls[-1]]
        if last_sl < prev_sl and last_close < last_sl:
            return {"type": "BOS", "direction": -1,
                    "level": last_sl, "bar_idx": swing_ls[-1]}

    return None


def _asia_entry_sl_tp(choch: dict, impulse: dict,
                      df1m: pd.DataFrame, df1h: pd.DataFrame) -> Optional[dict]:
    """
    يحسب نقطة الدخول والـ SL والـ TP.
    الدخول: عند 50% retracement من حركة الـ CHoCH/BOS
    SL:     خلف آخر Swing خارجي
    TP1:    50% من الشمعة الساعية
    TP2:    الامتداد الكامل
    """
    price   = float(df1m["Close"].iloc[-1])
    direction = choch["direction"]
    imp_hi  = impulse["high"]
    imp_lo  = impulse["low"]
    imp_rng = imp_hi - imp_lo

    # ── الدخول عند 50% retracement ──
    if direction == -1:   # بيع بعد impulse صاعد
        # التصحيح: ارتداد 50% من القمة
        move_hi = float(df1m["High"].tail(10).max())
        move_lo = choch["level"]
        entry   = move_lo + (move_hi - move_lo) * ASIA_RETRACE_PCT
        sl      = move_hi + atr_fn(df1m).iloc[-1] * 0.5

        # TP: 50% من الشمعة الساعية الحالية
        h1_open = float(df1h["Open"].iloc[-1])
        h1_rng  = float(df1h["High"].iloc[-1] - df1h["Low"].iloc[-1])
        tp1     = h1_open - h1_rng * ASIA_TP_PCT
        tp2     = h1_open - h1_rng

    else:                  # شراء بعد impulse هابط
        move_lo = float(df1m["Low"].tail(10).min())
        move_hi = choch["level"]
        entry   = move_hi - (move_hi - move_lo) * ASIA_RETRACE_PCT
        sl      = move_lo - atr_fn(df1m).iloc[-1] * 0.5

        h1_open = float(df1h["Open"].iloc[-1])
        h1_rng  = float(df1h["High"].iloc[-1] - df1h["Low"].iloc[-1])
        tp1     = h1_open + h1_rng * ASIA_TP_PCT
        tp2     = h1_open + h1_rng

    risk = abs(entry - sl)
    if risk < 0.01:
        return None

    rr1 = abs(tp1 - entry) / risk
    rr2 = abs(tp2 - entry) / risk

    if rr1 < ASIA_MIN_RR:
        return None

    return {
        "entry":  round(entry, 2),
        "sl":     round(sl, 2),
        "tp1":    round(tp1, 2),
        "tp2":    round(tp2, 2),
        "rr1":    round(rr1, 2),
        "rr2":    round(rr2, 2),
        "risk":   round(risk, 2),
    }


def analyze_asia() -> dict:
    """
    الوحدة الرئيسية لاستراتيجية انعكاس جلسة آسيا.
    تعيد dict يحتوي: vote, signal_type, entry, sl, tp1, tp2, rr, reasons
    """
    _empty = {
        "vote": 0, "active": False, "signal_type": None,
        "impulse": None, "choch": None, "entry": None,
        "sl": None, "tp1": None, "tp2": None, "rr": None,
        "reasons": [], "score": 0, "conf": 0,
    }

    # ── فحص النافذة الزمنية ──
    if not _asia_session_active():
        log.debug(f"[Asia] خارج النافذة (ساعة UTC={utcnow().hour})")
        return _empty

    # ── جلب البيانات ──
    df1m = fetch(SYMBOL, "1d", "1m")
    df5m = fetch(SYMBOL, "2d", "5m")
    df1h = fetch(SYMBOL, "5d", "1h")

    if df1m is None or df1h is None:
        log.warning("[Asia] فشل جلب البيانات")
        return _empty

    reasons = []

    # ── الخطوة 1: رصد الـ Impulse Move ──
    impulse = _detect_impulse(df1m)
    if impulse is None:
        log.debug("[Asia] لا يوجد Impulse Move واضح")
        return {**_empty, "active": True,
                "reasons": ["⏳ انتظار Impulse Move أحادي الاتجاه"]}

    imp_dir_ar = "صاعد ↑" if impulse["direction"] == 1 else "هابط ↓"
    reasons.append(f"✅ Impulse {imp_dir_ar} ({impulse['range']:.2f}$) في نافذة 02:00")
    score = 30

    # ── الخطوة 2: انتظار CHoCH/BOS ──
    choch = _detect_choch_bos(df1m, impulse)
    if choch is None:
        # جرّب على 5m
        if df5m is not None:
            choch = _detect_choch_bos(df5m, impulse)

    if choch is None:
        reasons.append("⏳ انتظار CHoCH/BOS لتأكيد الانعكاس")
        return {**_empty, "active": True, "impulse": impulse,
                "reasons": reasons, "score": score}

    choch_dir_ar = "صاعد ↑" if choch["direction"] == 1 else "هابط ↓"
    reasons.append(f"✅ {choch['type']} {choch_dir_ar} عند مستوى {choch['level']:.2f}")
    score += 35

    # تحقق من توافق CHoCH مع الانعكاس (CHoCH عكس الـ impulse)
    if choch["direction"] != impulse["direction"]:
        reasons.append("✅ CHoCH يعاكس الـ Impulse — انعكاس مؤكد")
        score += 15
    else:
        reasons.append("📌 BOS في اتجاه الـ Impulse — استمرارية")
        score += 8

    # ── الخطوة 3: حساب الدخول ──
    levels = _asia_entry_sl_tp(choch, impulse, df1m, df1h)
    if levels is None:
        reasons.append("⚠️ R:R غير مقبول — تجاهل الإشارة")
        return {**_empty, "active": True, "impulse": impulse,
                "choch": choch, "reasons": reasons, "score": score}

    score += 20
    reasons.append(
        f"🎯 دخول عند 50% retracement: {levels['entry']:.2f} | "
        f"SL: {levels['sl']:.2f} | TP1: {levels['tp1']:.2f} | R:R={levels['rr1']:.1f}"
    )

    vote = choch["direction"]
    conf = min(95, score + int(levels["rr1"] * 5))

    log.info(f"[Asia] vote={vote} {choch['type']} rr={levels['rr1']:.2f} score={score}")

    return {
        "vote":        vote,
        "active":      True,
        "signal_type": choch["type"],
        "impulse":     impulse,
        "choch":       choch,
        "entry":       levels["entry"],
        "sl":          levels["sl"],
        "tp1":         levels["tp1"],
        "tp2":         levels["tp2"],
        "rr":          levels["rr1"],
        "rr2":         levels["rr2"],
        "reasons":     reasons,
        "score":       score,
        "conf":        conf,
    }



# ══════════════════════════════════════════════════════════════════
# MODULE 5 — Range Trading Strategy (استراتيجية التداول في النطاق)
# ══════════════════════════════════════════════════════════════════
# المنطق الكامل:
#   1. كشف النطاق (Range): أعلى قمتين متساويتين + أدنى قاعين متساويين
#   2. تحديد نوع النطاق: ضيق / متوسط / واسع
#   3. تأكيد النطاق: RSI محايد (40-60) + ADX ضعيف (<25) + حجم منخفض
#   4. دخول الشراء: عند دعم النطاق + تأكيد ارتداد
#   5. دخول البيع:  عند مقاومة النطاق + تأكيد ارتداد
#   6. SL: خارج النطاق بـ ATR*0.5
#   7. TP1: منتصف النطاق | TP2: الطرف المقابل | TP3: امتداد 1.27
#   8. فلتر الاختراق: تجاهل الإشارة عند اقتراب اختراق النطاق

# إعدادات النطاق
RANGE_LOOKBACK      = 50    # عدد الشموع للبحث عن النطاق
RANGE_TOLERANCE_PCT = 0.003  # 0.3% تسامح لتحديد المستويات المتساوية
RANGE_MIN_TOUCHES   = 2      # حد أدنى لعدد اللمسات على كل مستوى
RANGE_MIN_WIDTH_ATR = 1.0    # الحد الأدنى لعرض النطاق بعدد ATR
RANGE_MAX_WIDTH_ATR = 6.0    # الحد الأقصى لعرض النطاق بعدد ATR
RANGE_ADX_MAX       = 25.0   # ADX أقل من هذا = سوق جانبي = نطاق صالح
RANGE_RSI_MID_LOW   = 38     # RSI أسفل هذا = قرب الدعم
RANGE_RSI_MID_HIGH  = 62     # RSI فوق هذا = قرب المقاومة
RANGE_ENTRY_BUFFER  = 0.002  # 0.2% مسافة الدخول من الحد
RANGE_SL_ATR        = 0.6    # SL على بُعد ATR*0.6 خارج النطاق
RANGE_BREAK_BUFFER  = 0.004  # 0.4% — إذا اقترب السعر من حد النطاق أكثر من هذا = خطر اختراق


def _find_levels(df: pd.DataFrame, lookback: int = RANGE_LOOKBACK) -> dict:
    """
    يحدد مستويات الدعم والمقاومة الرئيسية.
    يجمع القمم والقيعان المتكررة ضمن نطاق معين.
    """
    sub  = df.tail(lookback)
    hi   = sub["High"].values
    lo   = sub["Low"].values
    cl   = sub["Close"].values
    n    = len(sub)
    price = cl[-1]
    tol   = price * 0.002  # تسامح 0.2%

    # ── كشف Swing Highs/Lows ──
    swing_h = [hi[i] for i in range(2, n-2)
               if hi[i] > hi[i-1] and hi[i] > hi[i-2]
               and hi[i] > hi[i+1] and hi[i] > hi[i+2]]
    swing_l = [lo[i] for i in range(2, n-2)
               if lo[i] < lo[i-1] and lo[i] < lo[i-2]
               and lo[i] < lo[i+1] and lo[i] < lo[i+2]]

    # ── تجميع المستويات المتقاربة ──
    def cluster(levels, tolerance):
        if not levels: return []
        levels = sorted(levels)
        clusters = [[levels[0]]]
        for v in levels[1:]:
            if v - clusters[-1][-1] <= tolerance:
                clusters[-1].append(v)
            else:
                clusters.append([v])
        return [(sum(c)/len(c), len(c)) for c in clusters]

    res_clusters = cluster(swing_h, tol)
    sup_clusters = cluster(swing_l, tol)

    # ── فرز: الأقرب للسعر + أكثر لمسات ──
    resistances = sorted(
        [(lvl, cnt) for lvl, cnt in res_clusters if lvl > price],
        key=lambda x: (x[0]-price, -x[1])
    )
    supports = sorted(
        [(lvl, cnt) for lvl, cnt in sup_clusters if lvl < price],
        key=lambda x: (price-x[0], -x[1])
    )

    nearest_res = resistances[0]  if resistances else (price * 1.01, 1)
    nearest_sup = supports[0]     if supports    else (price * 0.99, 1)

    return {
        "resistance":      round(nearest_res[0], 2),
        "res_touches":     nearest_res[1],
        "support":         round(nearest_sup[0], 2),
        "sup_touches":     nearest_sup[1],
        "all_res":         [(round(l,2),c) for l,c in resistances[:4]],
        "all_sup":         [(round(l,2),c) for l,c in supports[:4]],
        "range_high":      round(nearest_res[0], 2),
        "range_low":       round(nearest_sup[0], 2),
        "range_mid":       round((nearest_res[0]+nearest_sup[0])/2, 2),
        "range_width_pct": round((nearest_res[0]-nearest_sup[0])/price*100, 2),
    }


def _range_position(price: float, levels: dict) -> str:
    """يحدد موقع السعر ضمن النطاق"""
    res = levels["resistance"]
    sup = levels["support"]
    mid = levels["range_mid"]
    buf = price * RANGE_BUFFER_PCT

    if price >= res - buf:   return "عند المقاومة 🔴"
    if price <= sup + buf:   return "عند الدعم 🟢"
    if price > mid:          return "أعلى المنتصف 🟡"
    return                          "أسفل المنتصف 🟡"


def _detect_breakout(df: pd.DataFrame, levels: dict) -> Optional[dict]:
    """يكشف كسر النطاق مع تأكيد"""
    res = levels["resistance"]
    sup = levels["support"]
    recent = df.tail(RANGE_BREAKOUT_CONFIRM + 2)

    # كسر صاعد: n شموع متتالية فوق المقاومة
    bull_break = all(
        recent["Close"].iloc[-(i+1)] > res
        for i in range(RANGE_BREAKOUT_CONFIRM)
    )
    # كسر هابط: n شموع متتالية تحت الدعم
    bear_break = all(
        recent["Close"].iloc[-(i+1)] < sup
        for i in range(RANGE_BREAKOUT_CONFIRM)
    )

    if bull_break:
        return {"direction": 1,  "level": res, "type": "Breakout صاعد 🚀"}
    if bear_break:
        return {"direction": -1, "level": sup, "type": "Breakout هابط 💥"}
    return None


def _range_reversal(df: pd.DataFrame, levels: dict, price: float) -> Tuple[int,str]:
    """
    يكشف إشارة انعكاس عند حدود النطاق.
    يستخدم RSI + شمعة انعكاسية للتأكيد.
    """
    res = levels["resistance"]
    sup = levels["support"]
    buf = price * RANGE_BUFFER_PCT
    r   = rsi_fn(df["Close"])
    rv  = r.iloc[-1]

    last3 = df.tail(3)
    # شمعة انعكاسية هابطة (Bearish Engulf / Pin Bar)
    c1, c2 = last3.iloc[-2], last3.iloc[-1]
    bear_candle = (c2["Close"] < c2["Open"] and
                   c2["Open"] >= c1["Close"] * 0.999)
    bull_candle = (c2["Close"] > c2["Open"] and
                   c2["Open"] <= c1["Close"] * 1.001)

    # عند المقاومة
    if price >= res - buf and price <= res * 1.005:
        if rv > 60 or bear_candle:
            return -1, f"🔴 انعكاس هابط عند المقاومة {res:.2f} (RSI={rv:.1f})"
    # عند الدعم
    if price <= sup + buf and price >= sup * 0.995:
        if rv < 40 or bull_candle:
            return 1, f"🟢 انعكاس صاعد عند الدعم {sup:.2f} (RSI={rv:.1f})"

    return 0, ""


def analyze_range() -> dict:
    """
    الوحدة الرئيسية لاستراتيجية النطاق.
    تحلل 3 إطارات زمنية للتأكيد.
    """
    _empty = {
        "vote": 0, "signal_type": None, "levels": {},
        "position": "—", "breakout": None, "reversal": (0,""),
        "entry": None, "sl": None, "tp1": None, "tp2": None,
        "rr": None, "reasons": [], "score": 0, "conf": 0,
        "df1h": None,
    }

    df1h = fetch(SYMBOL, "90d",  "1h")
    df15 = fetch(SYMBOL, "30d",  "15m")
    df4h = fetch(SYMBOL, "360d", "4h")

    if df1h is None: return _empty

    price   = float(df1h["Close"].iloc[-1])
    levels  = _find_levels(df1h, RANGE_LOOKBACK)
    res     = levels["resistance"]
    sup     = levels["support"]
    mid     = levels["range_mid"]
    wid_pct = levels["range_width_pct"]
    reasons = []
    score   = 0

    # ── فحص عرض النطاق ──
    if wid_pct < RANGE_MIN_WIDTH * 100:
        return {**_empty, "reasons": [f"⚠️ النطاق ضيق جداً ({wid_pct:.2f}%) — لا إشارة"],
                "df1h": df1h, "levels": levels, "position": _range_position(price,levels)}

    reasons.append(f"📐 النطاق: {sup:.2f} — {res:.2f}  (عرض={wid_pct:.2f}%)")
    reasons.append(f"   دعم: {sup:.2f} (لمسات={levels['sup_touches']}) | "
                   f"مقاومة: {res:.2f} (لمسات={levels['res_touches']})")
    score += min(levels["sup_touches"] + levels["res_touches"], 6) * 3

    position = _range_position(price, levels)
    reasons.append(f"📍 موقع السعر: {position}")

    # ── كشف كسر النطاق ──
    breakout = _detect_breakout(df1h, levels)
    if breakout:
        reasons.append(f"💥 {breakout['type']} عند {breakout['level']:.2f}")
        score += 20
        vote = breakout["direction"]
        at   = atr_fn(df1h).iloc[-1]
        if vote == 1:
            entry = price; sl = res * (1-RANGE_BUFFER_PCT*2)
            tp1   = price + at*2; tp2 = price + at*4
        else:
            entry = price; sl = sup * (1+RANGE_BUFFER_PCT*2)
            tp1   = price - at*2; tp2 = price - at*4
        rr = abs(tp2-entry)/(abs(sl-entry)+1e-9)
        conf = min(90, score + 30)
        log.info(f"[Range] Breakout vote={vote} score={score}")
        return {
            "vote": vote, "signal_type": breakout["type"],
            "levels": levels, "position": position,
            "breakout": breakout, "reversal": (0,""),
            "entry": round(entry,2), "sl": round(sl,2),
            "tp1": round(tp1,2), "tp2": round(tp2,2),
            "rr": round(rr,2), "reasons": reasons,
            "score": score, "conf": conf, "df1h": df1h,
        }

    # ── كشف انعكاس ──
    rev_vote, rev_reason = _range_reversal(df1h, levels, price)

    # تأكيد على 15m
    rev_confirm = 0
    if df15 is not None and rev_vote != 0:
        lv15 = _find_levels(df15, 30)
        rv15, _ = _range_reversal(df15, lv15, price)
        if rv15 == rev_vote: rev_confirm += 1; score += 10

    # تأكيد على 4h
    if df4h is not None and rev_vote != 0:
        lv4h = _find_levels(df4h, 30)
        rv4h, _ = _range_reversal(df4h, lv4h, price)
        if rv4h == rev_vote: rev_confirm += 1; score += 15

    if rev_vote != 0 and rev_reason:
        reasons.append(rev_reason)
        if rev_confirm > 0:
            reasons.append(f"✅ تأكيد على {rev_confirm} إطار إضافي")
        score += 15
        at    = atr_fn(df1h).iloc[-1]
        if rev_vote == 1:
            entry = price; sl = sup - at*0.5
            tp1   = mid;   tp2 = res - at*0.3
        else:
            entry = price; sl = res + at*0.5
            tp1   = mid;   tp2 = sup + at*0.3
        rr   = abs(tp2-entry)/(abs(sl-entry)+1e-9)
        vote = rev_vote if (rr >= MIN_RR and rev_confirm >= 1) else 0
        conf = min(88, score + 10)
        log.info(f"[Range] Reversal vote={vote} score={score} confirm={rev_confirm}")
        return {
            "vote": vote, "signal_type": "انعكاس نطاق",
            "levels": levels, "position": position,
            "breakout": None, "reversal": (rev_vote, rev_reason),
            "entry": round(entry,2) if vote else None,
            "sl":    round(sl,2)    if vote else None,
            "tp1":   round(tp1,2)   if vote else None,
            "tp2":   round(tp2,2)   if vote else None,
            "rr":    round(rr,2)    if vote else None,
            "reasons": reasons, "score": score, "conf": conf, "df1h": df1h,
        }

    # لا إشارة — فقط معلومات النطاق
    next_target = res if price > mid else sup
    dist_pct = abs(next_target - price)/price*100
    reasons.append(f"⏳ السعر في منتصف النطاق — أقرب هدف: {next_target:.2f} ({dist_pct:.2f}%)")
    log.info(f"[Range] No signal — price={price:.2f} in range {sup:.2f}–{res:.2f}")
    return {**_empty, "reasons": reasons, "score": score, "conf": 0,
            "levels": levels, "position": position, "df1h": df1h}


# ══════════════════════════════════════════════════════════════════
# MODULE AI — Claude AI Analyst (Anthropic / PPQ.AI)
# ══════════════════════════════════════════════════════════════════

# ── إعدادات كل مزوّد ──
# ══════════════════════════════════════════════════════════════
# AI PROVIDERS — مزوّدو الذكاء الاصطناعي
# ══════════════════════════════════════════════════════════════
# CLAUDE_PROVIDER في config.json:
#   "auto"       ← يجرّب المجاني أولاً ثم المدفوع (موصى به)
#   "groq"       ← مجاني تماماً (14,400 طلب/يوم) — الأسرع
#   "openrouter" ← مجاني (200 طلب/يوم) — أكثر تنوعاً
#   "gemini"     ← مجاني (250 طلب/يوم) — من Google
#   "ppq"        ← مدفوع بـ USDT
#   "anthropic"  ← مدفوع بطاقة بنكية
# ══════════════════════════════════════════════════════════════

_AI_PROVIDERS = {
    # ── مجانية ──────────────────────────────────────────
    "groq": {
        # مجاني — 14,400 طلب/يوم — الأسرع — بدون بطاقة
        # سجّل على: console.groq.com
        "url":   "https://api.groq.com/openai/v1/chat/completions",
        "model": cfg.get("CLAUDE_MODEL","") or "llama-3.3-70b-versatile",
        "fmt":   "openai",
        "headers": lambda key: {
            "Authorization": f"Bearer {key}",
            "Content-Type":  "application/json",
        },
    },
    "openrouter": {
        # مجاني — 200 طلب/يوم — 29+ نموذج مجاني
        # سجّل على: openrouter.ai
        "url":   "https://openrouter.ai/api/v1/chat/completions",
        "model": cfg.get("CLAUDE_MODEL","") or "meta-llama/llama-3.3-70b-instruct:free",
        "fmt":   "openai",
        "headers": lambda key: {
            "Authorization":  f"Bearer {key}",
            "Content-Type":   "application/json",
            "HTTP-Referer":   "https://github.com/goldbot",
            "X-Title":        "Gold Trading Bot",
        },
    },
    "gemini": {
        # مجاني — 250 طلب/يوم — من Google
        # سجّل على: ai.google.dev
        "url":   "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "model": cfg.get("CLAUDE_MODEL","") or "gemini-2.0-flash",
        "fmt":   "openai",
        "headers": lambda key: {
            "Authorization": f"Bearer {key}",
            "Content-Type":  "application/json",
        },
    },
    # ── مدفوعة ──────────────────────────────────────────
    "ppq": {
        # مدفوع بـ USDT — ppq.ai
        "url":   "https://api.ppq.ai/chat/completions",
        "model": cfg.get("CLAUDE_MODEL","") or "claude-sonnet-4-5",
        "fmt":   "openai",
        "headers": lambda key: {
            "Authorization": f"Bearer {key}",
            "Content-Type":  "application/json",
        },
    },
    "anthropic": {
        # مدفوع — Anthropic مباشرة
        "url":   "https://api.anthropic.com/v1/messages",
        "model": cfg.get("CLAUDE_MODEL","") or "claude-sonnet-4-6-20250514",
        "fmt":   "anthropic",
        "headers": lambda key: {
            "x-api-key":           key,
            "anthropic-version":   "2023-06-01",
            "content-type":        "application/json",
        },
    },
}

# ── ترتيب Auto: مجاني أولاً ──
_AUTO_ORDER = ["groq", "openrouter", "gemini", "ppq", "anthropic"]


def _ai_provider() -> tuple:
    """يعيد إعدادات المزوّد المختار من config.json"""
    provider = cfg.get("CLAUDE_PROVIDER", "auto").lower().strip()
    if provider == "auto":
        # في وضع auto، نُرجع قائمة للتجربة
        return None, "auto"
    if provider not in _AI_PROVIDERS:
        log.warning(f"[AI] مزوّد غير معروف '{provider}' — استخدام groq")
        provider = "groq"
    return _AI_PROVIDERS[provider], provider

CLAUDE_API   = _AI_PROVIDERS["anthropic"]["url"]    # fallback للتوافق
CLAUDE_MODEL = _AI_PROVIDERS["anthropic"]["model"]  # fallback للتوافق

def _build_ai_prompt(v7: dict, smc: dict, ob: dict, agg: dict, price: float) -> str:
    """يبني prompt شاملاً لـ Claude بكل بيانات التحليل الفني"""
    os_ = ob.get("signal")
    pd_ = smc.get("pd", {})

    # ── V7 indicators summary ──
    v7_lines = []
    for nm, inf in v7.get("strats", {}).items():
        sig = inf["signal"]; wt = inf.get("weight", 1)
        arrow = "BUY" if sig == 1 else ("SELL" if sig == -1 else "NEUTRAL")
        v7_lines.append(f"  {nm.replace('V7_','')}: {arrow} (weight={wt}) — {inf['reason']}")

    tf_lines = []
    for tf, vote in v7.get("tf_v", {}).items():
        tf_lines.append(f"  {tf}: {'BULLISH' if vote==1 else 'BEARISH' if vote==-1 else 'NEUTRAL'}")

    smc_reasons = "\n".join(f"  {r}" for r in smc.get("reasons", []))

    ob_txt = "No OBinOB confluence found."
    if os_:
        ob_txt = (f"HTF OB ({os_.htf.tf}): {os_.htf.lo:.2f}–{os_.htf.hi:.2f} [{os_.htf.method}] strength={os_.htf.str_:.1f}x ATR\n"
                  f"LTF OB ({os_.ltf.tf}): {os_.ltf.lo:.2f}–{os_.ltf.hi:.2f} [{os_.ltf.method}] strength={os_.ltf.str_:.1f}x ATR\n"
                  f"Overlap: {os_.ovl*100:.0f}% | Signal strength: {os_.strength}/10 | R:R={os_.rr:.2f}")

    prompt = f"""You are an expert gold (BTC/USD) technical analyst with 20+ years of experience.
Analyze the following multi-strategy technical data and provide a precise trading decision.

═══════════════════════════════════════════════
MARKET SNAPSHOT — BTC/USD
═══════════════════════════════════════════════
Current Price : {price:.2f}
Trading Session: {trading_session()}
Time (UTC)    : {utcnow_str()}
DXY Analysis  : {v7.get("dxy_txt", "—")}

═══════════════════════════════════════════════
STRATEGY 1 — V7 Multi-Timeframe (10 indicators)
═══════════════════════════════════════════════
Indicator weights (total={v7.get("max_weight",22)}):
  Buy  weight: {v7.get("buy_w",0)}/{v7.get("max_weight",22)}
  Sell weight: {v7.get("sell_w",0)}/{v7.get("max_weight",22)}

Timeframe votes:
{chr(10).join(tf_lines)}

Individual indicators (1h timeframe):
{chr(10).join(v7_lines)}

V7 raw vote: {"BUY" if v7["vote"]==1 else "SELL" if v7["vote"]==-1 else "NEUTRAL"}
Volume confirmation: {"YES" if v7.get("vol_ok") else "NO"}

═══════════════════════════════════════════════
STRATEGY 2 — SMC Smart Money Concepts
═══════════════════════════════════════════════
Market Trend  : {smc.get("trend","—")}
SMC Score     : {smc.get("score",0)} (threshold={SMC_SC})
BOS           : {smc.get("bos","—")}
CHoCH         : {smc.get("choch","—")}
MSS           : {smc.get("mss","—")}
Zone          : {pd_.get("zone","—")} ({pd_.get("dist_pct",0):+.2f}% from midpoint)
Liquidity (above): {smc.get("liq",{}).get("eq_highs",[])}
Liquidity (below): {smc.get("liq",{}).get("eq_lows",[])}

Active signals:
{smc_reasons if smc_reasons else "  No active SMC signals"}

SMC raw vote: {"BUY" if smc["vote"]==1 else "SELL" if smc["vote"]==-1 else "NEUTRAL"}

═══════════════════════════════════════════════
STRATEGY 3 — OBinOB (Order Block Confluence)
═══════════════════════════════════════════════
{ob_txt}
OBinOB raw vote: {"BUY" if ob["vote"]==1 else "SELL" if ob["vote"]==-1 else "NEUTRAL"}
Active pair: {ob.get("pair","—")}

═══════════════════════════════════════════════
PRE-COMPUTED AGGREGATION
═══════════════════════════════════════════════
Strategy agreement: {agg["agree"]}/3
Pre-computed confidence: {agg["conf"]}%
Pre-computed direction: {"BUY" if agg["d"]==1 else "SELL" if agg["d"]==-1 else "NO SIGNAL"}
Entry price: {agg.get("entry") or "—"}
Stop Loss  : {agg.get("sl") or "—"}
TP1        : {agg.get("tp1") or "—"}
TP2        : {agg.get("tp2") or "—"}
TP3        : {agg.get("tp3") or "—"}
R:R Ratio  : {agg.get("rr") or "—"}

═══════════════════════════════════════════════
YOUR TASK
═══════════════════════════════════════════════
Based on ALL the above data, provide your expert analysis.
You may AGREE or DISAGREE with the pre-computed aggregation if you see strong reasons.

Respond ONLY with this exact JSON format (no markdown, no extra text):
{{
  "decision": "BUY" or "SELL" or "WAIT",
  "confidence": <integer 0-100>,
  "ai_agrees_with_system": true or false,
  "entry": <float or null>,
  "sl": <float or null>,
  "tp1": <float or null>,
  "tp2": <float or null>,
  "tp3": <float or null>,
  "rr": <float or null>,
  "risk_level": "LOW" or "MEDIUM" or "HIGH",
  "key_factors": ["factor1", "factor2", "factor3"],
  "warnings": ["warning1"] or [],
  "summary_ar": "<2-3 جمل بالعربية تشرح قرار التداول وأهم الأسباب>",
  "invalidation": "<متى تصبح الإشارة ملغاة — بالعربية>"
}}"""
    return prompt


def ai_analyze(v7: dict, smc: dict, ob: dict, agg: dict, price: float) -> dict:
    """
    يرسل بيانات التحليل إلى AI ويعيد قراره النهائي.
    يدعم Auto (مجاني أولاً) + groq + openrouter + gemini + ppq + anthropic
    """
    _empty = {
        "available": False, "decision": None, "confidence": 0,
        "ai_agrees_with_system": None, "entry": None, "sl": None,
        "tp1": None, "tp2": None, "tp3": None, "rr": None,
        "risk_level": "—", "key_factors": [], "warnings": [],
        "summary_ar": "", "invalidation": "", "raw": None,
        "provider": "—"
    }

    api_key  = cfg.get("CLAUDE_API_KEY","").strip()
    provider = cfg.get("CLAUDE_PROVIDER","auto").strip().lower()
    if not api_key:
        log.debug("[AI] CLAUDE_API_KEY غير مضبوط")
        return _empty

    prompt = _build_ai_prompt(v7, smc, ob, agg, price)

    def _try_provider(pname: str) -> tuple:
        """يجرّب مزوّداً ويُرجع (raw_text, provider_name) أو (None, pname)"""
        pcfg = _AI_PROVIDERS.get(pname)
        if not pcfg: return None, pname
        try:
            resp = requests.post(
                pcfg["url"],
                headers=pcfg["headers"](api_key),
                json={"model":pcfg["model"],"max_tokens":1024,
                      "messages":[{"role":"user","content":prompt}]},
                timeout=30,
            )
            if resp.status_code == 429:
                log.warning(f"[AI] {pname}: تجاوز الحد (429)")
                return None, pname
            if not resp.ok:
                log.debug(f"[AI] {pname}: HTTP {resp.status_code}")
                return None, pname
            data = resp.json()
            if pcfg["fmt"] == "anthropic":
                text = data.get("content",[{}])[0].get("text","").strip()
            else:
                text = data.get("choices",[{}])[0].get("message",{}).get("content","").strip()
            return (text if text else None), pname
        except Exception as e:
            log.debug(f"[AI] {pname} خطأ: {e}")
            return None, pname

    # ── اختيار المزوّد ──
    if provider == "auto":
        providers_to_try = _AUTO_ORDER
    elif provider in _AI_PROVIDERS:
        providers_to_try = [provider]
    else:
        log.warning(f"[AI] مزوّد غير معروف '{provider}' — استخدام auto")
        providers_to_try = _AUTO_ORDER

    raw_text = None
    used_provider = "—"
    for pname in providers_to_try:
        log.info(f"[AI] جرّب {pname}...")
        raw_text, used_provider = _try_provider(pname)
        if raw_text:
            log.info(f"[AI] ✅ {pname} أجاب")
            break
        log.debug(f"[AI] {pname} فشل — التالي")

    if not raw_text:
        log.warning("[AI] جميع المزوّدين فشلوا")
        return {**_empty, "provider": used_provider}

    # ── تنظيف markdown إذا وُجد ──
    if raw_text.startswith("```"):
        parts = raw_text.split("```")
        raw_text = parts[1] if len(parts) > 1 else raw_text
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]
    raw_text = raw_text.strip()

    try:
        result = json.loads(raw_text)
        result["available"] = True
        result["raw"]       = raw_text
        result["provider"]  = used_provider

        dec   = result.get("decision", "?")
        conf  = result.get("confidence", 0)
        agree = result.get("ai_agrees_with_system", None)
        log.info(f"[AI] ✅ [{used_provider}] قرار={dec} ثقة={conf}% توافق={agree}")
        return result
    except json.JSONDecodeError:
        # النموذج لم يُرجع JSON — حوّله لنتيجة بسيطة
        log.debug(f"[AI] {used_provider} لم يُرجع JSON — استخدم النص مباشرة")
        return {**_empty, "available":True, "provider":used_provider,
                "summary_ar": raw_text[:500], "decision":"WAIT", "confidence":50}
    except Exception as e:
        log.warning(f"[AI] خطأ: {e}")
        return {**_empty, "provider": used_provider}


def merge_with_ai(agg: dict, ai: dict) -> dict:
    """
    يدمج قرار الذكاء الاصطناعي مع النتيجة المجمَّعة.
    إذا اختلف AI مع النظام → يرفع/يخفض الثقة ويوضّح السبب.
    إذا لم يكن AI متاحاً → يُرجع agg بدون تعديل.
    """
    if not ai.get("available"):
        return {**agg, "ai": ai}

    ai_dec = ai.get("decision")
    ai_vote = 1 if ai_dec=="BUY" else (-1 if ai_dec=="SELL" else 0)
    sys_vote = agg["d"]

    if ai_vote == sys_vote and sys_vote != 0:
        # ✅ AI متوافق → رفع الثقة
        new_conf = min(int((agg["conf"] + ai["confidence"]) / 2 * 1.15), 97)
        # استخدم entry/sl/tp من AI إذا كانت أدق
        entry = ai.get("entry") or agg["entry"]
        sl    = ai.get("sl")    or agg["sl"]
        tp1   = ai.get("tp1")   or agg.get("tp1")
        tp2   = ai.get("tp2")   or agg.get("tp2")
        tp3   = ai.get("tp3")   or agg.get("tp3")
        rr    = ai.get("rr")    or agg["rr"]
    elif ai_vote != 0 and ai_vote != sys_vote:
        # ⚠️ AI يختلف → خفض الثقة
        new_conf = int(agg["conf"] * 0.6)
        entry = agg["entry"]; sl = agg["sl"]
        tp1 = agg.get("tp1"); tp2 = agg.get("tp2"); tp3 = agg.get("tp3"); rr = agg["rr"]
    else:
        # AI WAIT أو لا رأي
        new_conf = agg["conf"]
        entry = agg["entry"]; sl = agg["sl"]
        tp1 = agg.get("tp1"); tp2 = agg.get("tp2"); tp3 = agg.get("tp3"); rr = agg["rr"]

    return {**agg,
            "conf": new_conf,
            "entry": entry, "sl": sl,
            "tp1": tp1, "tp2": tp2, "tp3": tp3, "rr": rr,
            "ai": ai, "ai_vote": ai_vote}



def _ai_section(ai: dict, sys_vote: int) -> str:
    """يبني قسم AI في رسالة تيليغرام"""
    if not ai.get("available"):
        provider = ai.get("provider","—")
        if provider not in ("—","anthropic","ppq"):
            hint = f"تحقق من إعداد CLAUDE_PROVIDER: {provider}"
        else:
            hint = "أضف CLAUDE_API_KEY في config.json لتفعيله"
        return f"④ <b>Claude AI</b> ⬜\n   غير مفعّل — {hint}"

    dec    = ai.get("decision","?")
    prov   = ai.get("provider","auto").upper()
    dec_ar = "شراء 🟢" if dec=="BUY" else ("بيع 🔴" if dec=="SELL" else "انتظار ⏳")
    ai_vote = 1 if dec=="BUY" else (-1 if dec=="SELL" else 0)
    agree_icon = "✅" if ai_vote==sys_vote else ("⚠️" if ai_vote!=0 else "⬜")
    risk_ar = {"LOW":"🟢 منخفضة","MEDIUM":"🟡 متوسطة","HIGH":"🔴 عالية"}.get(
        ai.get("risk_level",""), ai.get("risk_level","—"))

    lines = [
        f"④ <b>Claude AI [{prov}]</b> {agree_icon}",
        f"   قرار: <b>{dec_ar}</b>  |  ثقة: <b>{ai.get('confidence',0)}%</b>  |  مخاطرة: {risk_ar}",
    ]
    if ai.get("entry"):
        lines.append(f"   دخول: {ai['entry']:.2f}  |  SL: {ai.get('sl',0):.2f}  |  R:R: {ai.get('rr',0):.2f}")
    if ai.get("key_factors"):
        lines.append("   <b>أهم العوامل:</b>")
        for f in ai["key_factors"][:3]:
            lines.append(f"   • {esc(f)}")
    if ai.get("summary_ar"):
        lines.append(f"   📝 {esc(ai['summary_ar'])}")
    if ai.get("warnings"):
        for w in ai["warnings"][:2]:
            lines.append(f"   ⚠️ {esc(w)}")
    if ai.get("invalidation"):
        lines.append(f"   🚫 إلغاء: {esc(ai['invalidation'])}")
    if not ai.get("ai_agrees_with_system") and ai_vote != 0 and ai_vote != sys_vote:
        lines.append("   ⚠️ <b>AI يختلف مع النظام — تحقق قبل الدخول!</b>")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════
# AGGREGATOR
# ══════════════════════════════════════════════════════════════════
def aggregate(v7: dict, smc: dict, ob: dict, asia: dict = None, rng: dict = None) -> dict:
    if asia is None: asia = {}
    if rng  is None: rng  = {}
    votes={"V7":v7["vote"],"SMC":smc["vote"],"OBinOB":ob["vote"],"Asia":asia.get("vote",0),"Range":rng.get("vote",0)}
    bc=sum(1 for v in votes.values() if v==1)
    sc=sum(1 for v in votes.values() if v==-1)
    d=0
    if bc>=UNI_AGR: d=1
    elif sc>=UNI_AGR: d=-1
    conf=0
    if d:
        ag=max(bc,sc); conf=ag*25
        mw=v7.get("max_weight",22)
        if d==v7["vote"]:  conf+=int(min(v7.get("score",0)/mw*30,30))
        if d==smc["vote"]: conf+=int(min(abs(smc["score"])/10*20,20))
        os_=ob.get("signal")
        if os_ and os_.side==d: conf+=int(os_.strength*1.5)
        if d==asia.get("vote",0) and asia.get("active"): conf+=int(asia.get("conf",0)*0.12)
        if d==rng.get("vote",0) and rng.get("active"): conf+=int(rng.get("confidence",0)*0.10)
        conf=min(int(conf),97)
    entry=sl=tp=tp1=tp2=tp3=rr=None
    if d:
        os_=ob.get("signal")
        asia_ok = asia.get("vote")==d and asia.get("entry") and asia.get("active")
        rng_ok  = rng.get("vote")==d and rng.get("entry")
        rng_ok  = rng.get("vote")==d  and rng.get("entry")  and rng.get("active")
        if os_ and os_.side==d:
            entry,sl,tp,tp1,tp2=os_.price,os_.sl,os_.tp,os_.tp1,os_.tp2
            tp3=tp; rr=os_.rr
        elif asia_ok:
            entry=asia["entry"]; sl=asia["sl"]
            tp1=asia["tp1"]; tp2=asia.get("tp2"); tp3=tp2
            tp=tp1; rr=asia["rr"]
        elif rng_ok:
            entry=rng["entry"]; sl=rng["sl"]
            tp1=rng["tp1"]; tp2=rng.get("tp2"); tp3=rng.get("tp3")
            tp=tp1; rr=rng["rr"]
        elif v7["vote"]==d and v7["entry"]:
            entry,sl,tp=v7["entry"],v7["sl"],v7["tp"]
            tp1,tp2,tp3=v7.get("tp1"),v7.get("tp2"),v7.get("tp3"); rr=v7["rr"]
        elif smc["vote"]==d and smc["entry"]:
            entry,sl,tp=smc["entry"],smc["sl"],smc["tp"]
            tp1,tp2,tp3=smc.get("tp1"),smc.get("tp2"),smc.get("tp3"); rr=smc["rr"]
    ag_cnt=max(bc,sc)
    lbl="شراء 🟢 LONG" if d==1 else ("بيع 🔴 SHORT" if d==-1 else "⏳ لا إشارة")
    log.info(f"[AGG] votes={votes} d={d} agree={ag_cnt}/3 conf={conf}%")
    return {"d":d,"agree":ag_cnt,"conf":conf,"votes":votes,"lbl":lbl,
            "entry":entry,"sl":sl,"tp":tp,"tp1":tp1,"tp2":tp2,"tp3":tp3,"rr":rr,
            "asia":asia,"range":rng}

# ══════════════════════════════════════════════════════════════════
# CHART
# ══════════════════════════════════════════════════════════════════
def build_chart(v7: dict, smc: dict, ob: dict, agg: dict) -> Optional[str]:
    df=v7.get("df1h")
    if df is None: return None
    fig=plt.figure(figsize=(18,16),facecolor="#0d1117")
    gs=gridspec.GridSpec(6,1,height_ratios=[4,1,1,1,1,1],hspace=0.04)
    axs=[fig.add_subplot(gs[i]) for i in range(6)]
    for ax in axs:
        ax.set_facecolor("#0d1117"); ax.tick_params(colors="#c9d1d9",labelsize=7)
        for sp in ax.spines.values(): sp.set_edgecolor("#30363d")
    ap,am,ar,av_ax,aw,avol = axs
    tail=120; sub=df.tail(tail).reset_index(drop=True); n=len(sub); idx=list(range(n))
    # Candles
    for i,row in sub.iterrows():
        col="#3fb950" if row["Close"]>=row["Open"] else "#f85149"
        blo=min(row["Open"],row["Close"]); bhi=max(row["Open"],row["Close"])
        ap.add_patch(mpatches.Rectangle((i-.35,blo),.7,max(bhi-blo,1e-6),color=col,zorder=3))
        ap.plot([i,i],[row["Low"],blo],color=col,lw=.6,zorder=2)
        ap.plot([i,i],[bhi,row["High"]],color=col,lw=.6,zorder=2)
    ap.set_xlim(-1,n); ap.set_ylim(sub["Low"].min()*.997,sub["High"].max()*1.003)
    # EMAs
    for en,ec,ew in [(50,"#58a6ff",1.3),(100,"#f0b429",1.),(200,"#f85149",1.)]:
        ap.plot(idx,ema(sub["Close"],en),color=ec,lw=ew,ls="--",label=f"EMA{en}",zorder=5)
    # Ichimoku Cloud
    try:
        tk,kj,sA,sB,_ = ichimoku_fn(sub)
        sA_=sA.values; sB_=sB.values
        valid = ~(np.isnan(sA_)|np.isnan(sB_))
        iv_=np.where(valid)[0]
        if len(iv_)>0:
            ap.fill_between(iv_,[sA_[i] for i in iv_],[sB_[i] for i in iv_],
                alpha=.12,color="#3fb950",where=[sA_[i]>=sB_[i] for i in iv_],zorder=1)
            ap.fill_between(iv_,[sA_[i] for i in iv_],[sB_[i] for i in iv_],
                alpha=.12,color="#f85149",where=[sA_[i]<sB_[i] for i in iv_],zorder=1)
    except: pass
    # BB
    up,md,lo=bb_fn(sub["Close"])
    ap.fill_between(idx,up,lo,alpha=.04,color="#8b949e")
    ap.plot(idx,up,color="#8b949e",lw=.5,alpha=.5)
    ap.plot(idx,lo,color="#8b949e",lw=.5,alpha=.5)
    # SMC OB zones
    for o in smc.get("obs",[])[-3:]:
        col="#1a4a2e" if o["t"]=="BULL" else "#4a1a1a"
        ap.axhspan(o["bot"],o["top"],alpha=.20,color=col,zorder=1)
    # SMC Premium/Discount line
    pd_=smc.get("pd",{})
    if pd_.get("mid"):
        ap.axhline(pd_["mid"],color="#e3b341",lw=.8,ls=":",alpha=.6,label=f"50% ({pd_['mid']:.2f})")
    # OBinOB zones
    os_=ob.get("signal")
    if os_:
        zc="#002244" if os_.side==1 else "#440022"
        ap.axhspan(os_.htf.lo,os_.htf.hi,alpha=.12,color=zc,zorder=1,label=f"HTF-OB({os_.htf.tf})")
        ap.axhspan(os_.ltf.lo,os_.ltf.hi,alpha=.30,color=zc,zorder=2,label=f"LTF-OB({os_.ltf.tf})")
    # Entry/TP/SL lines
    if agg["entry"]:
        ap.axhline(agg["entry"],color="#e3b341",lw=2.,label=f"Entry {agg['entry']:.2f}",zorder=6)
        ap.axhline(agg["sl"],color="#f85149",lw=1.2,ls="--",label=f"SL {agg['sl']:.2f}",zorder=6)
        for tp_v,tp_lbl,tp_col in [
            (agg.get("tp1"),f"TP1",   "#58a6ff"),
            (agg.get("tp2"),f"TP2",   "#3fb950"),
            (agg.get("tp3"),f"TP3 🎯","#a371f7"),
        ]:
            if tp_v: ap.axhline(tp_v,color=tp_col,lw=1.,ls="--",label=f"{tp_lbl} {tp_v:.2f}",zorder=6)
    # Title
    d=agg["d"]; tc="#3fb950" if d==1 else ("#f85149" if d==-1 else "#e3b341")
    vt=" | ".join(f"{k}:{'🟢' if v==1 else '🔴' if v==-1 else '⬜'}" for k,v in agg["votes"].items())
    ap.set_title(f"BTC/USD  {agg['lbl']}  ثقة={agg['conf']}%  [{vt}]  {trading_session()}  {utcnow_str()}",
                 color=tc,fontsize=10,pad=6)
    ap.legend(facecolor="#161b22",labelcolor="#c9d1d9",fontsize=6.5,loc="upper left",ncol=3)
    # MACD
    ml,ms=macd_fn(sub["Close"]); h=ml-ms
    am.bar(idx,h,color=["#3fb950" if x>=0 else "#f85149" for x in h],width=.8,alpha=.8)
    am.plot(idx,ml,color="#58a6ff",lw=.9,label="MACD")
    am.plot(idx,ms,color="#f0b429",lw=.9,label="Sig")
    am.axhline(0,color="#30363d",lw=.7); am.set_ylabel("MACD",color="#8b949e",fontsize=8)
    am.legend(facecolor="#161b22",labelcolor="#c9d1d9",fontsize=6)
    # RSI
    r=rsi_fn(sub["Close"])
    ar.plot(idx,r,color="#a371f7",lw=1.2)
    ar.axhline(70,color="#f85149",ls="--",lw=.7); ar.axhline(30,color="#3fb950",ls="--",lw=.7)
    ar.axhline(50,color="#8b949e",ls=":",lw=.5)
    ar.fill_between(idx,r,70,where=(r>70),alpha=.2,color="#f85149")
    ar.fill_between(idx,r,30,where=(r<30),alpha=.2,color="#3fb950")
    ar.set_ylim(0,100); ar.set_ylabel("RSI",color="#8b949e",fontsize=8)
    ar.text(n-1,r.iloc[-1],f" {r.iloc[-1]:.1f}",color="#a371f7",fontsize=8,va="center")
    # PVP
    pf,ps,ph,_=pvp_fn(sub)
    av_ax.plot(idx,pf.values,color="#f0b429",lw=1.2,label="PVP")
    av_ax.plot(idx,ps.values,color="#58a6ff",lw=1.,ls="--",label="Sig")
    av_ax.bar(idx,ph.values,color=["#3fb950" if x>=0 else "#f85149" for x in ph.values],alpha=.4,width=.8)
    av_ax.axhline(0,color="#30363d",lw=.7); av_ax.set_ylabel("PVP",color="#8b949e",fontsize=8)
    av_ax.legend(facecolor="#161b22",labelcolor="#c9d1d9",fontsize=6)
    # Williams %R
    wr=williams_r(sub)
    aw.plot(idx,wr,color="#e3b341",lw=1.)
    aw.axhline(-20,color="#f85149",ls="--",lw=.7); aw.axhline(-80,color="#3fb950",ls="--",lw=.7)
    aw.fill_between(idx,wr,-20,where=(wr>-20),alpha=.15,color="#f85149")
    aw.fill_between(idx,wr,-80,where=(wr<-80),alpha=.15,color="#3fb950")
    aw.set_ylim(-105,5); aw.set_ylabel("%R",color="#8b949e",fontsize=8)
    aw.text(n-1,wr.iloc[-1],f" {wr.iloc[-1]:.1f}",color="#e3b341",fontsize=8,va="center")
    # Volume + OBV
    vc=["#3fb950" if sub["Close"].iloc[i]>=sub["Open"].iloc[i] else "#f85149" for i in range(n)]
    avol.bar(idx,sub["Volume"].values,color=vc,alpha=.6,width=.8)
    avol.plot(idx,sub["Volume"].rolling(20).mean().values,color="#f0b429",lw=1.,label="MA20")
    obv_=obv_fn(sub); obv_n=obv_/obv_.abs().max()*sub["Volume"].max()*.6
    avol.plot(idx,obv_n.values,color="#a371f7",lw=1.,alpha=.8,label="OBV(norm)")
    avol.set_ylabel("Volume",color="#8b949e",fontsize=8)
    avol.legend(facecolor="#161b22",labelcolor="#c9d1d9",fontsize=6)
    plt.tight_layout()
    fname=f"charts/chart_{utcnow().strftime('%Y%m%d_%H%M%S')}.png"
    plt.savefig(fname,dpi=130,facecolor=fig.get_facecolor(),bbox_inches="tight")
    plt.close(); return fname

# ══════════════════════════════════════════════════════════════════
# MESSAGES — تفصيلية كاملة
# ══════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════
# INLINE BUTTONS — أزرار تفاعلية لكل استراتيجية
# ══════════════════════════════════════════════════════════════════
_last_results: dict = {}
_last_results_ts: str = ""

def _save_results(v7, smc, ob, asia, rng, agg, price):
    global _last_results, _last_results_ts
    _last_results = {"v7":v7,"smc":smc,"ob":ob,"asia":asia,"range":rng,"agg":agg,"price":price}
    _last_results_ts = utcnow_str()

def _build_keyboard(signal_dir: int = 0) -> dict:
    def btn(text, data): return {"text":text,"callback_data":data}
    arrow = "📈" if signal_dir==1 else ("📉" if signal_dir==-1 else "📊")
    return {"inline_keyboard":[
        [btn("🔢 V7 تفصيلي","analyze_v7"),      btn("💎 SMC تفصيلي","analyze_smc")],
        [btn("📦 OBinOB تفصيلي","analyze_obinob"),btn("🌙 جلسة آسيا","analyze_asia")],
        [btn("📐 Range تفصيلي","analyze_range"),  btn("🤖 Claude AI","analyze_ai")],
        [btn(f"📊 ملخص كامل {arrow}","analyze_full")],
    ]}

def _send_with_buttons(cid: str, text: str, signal_dir: int = 0) -> bool:
    try:
        import json as _j
        return _sess().post(TG_API+"/sendMessage", json={
            "chat_id":cid,"text":text,"parse_mode":"HTML",
            "reply_markup":_build_keyboard(signal_dir),
        }, timeout=TG_TMO).ok
    except: return False

def tg_send_with_buttons(text: str, signal_dir: int = 0, flt=None) -> int:
    if not TG_TOKEN: return 0
    ok = 0
    for c in get_subs(flt):
        if _send_with_buttons(c, text, signal_dir): ok += 1
        time.sleep(0.05)
    return ok

def _photo_with_buttons(cid: str, path: str, cap: str, signal_dir: int = 0) -> bool:
    try:
        import json as _j
        kb = _j.dumps(_build_keyboard(signal_dir))
        with open(path,"rb") as f:
            return _sess().post(TG_API+"/sendPhoto", files={"photo":f},
                data={"chat_id":cid,"caption":cap[:1024],"parse_mode":"HTML",
                      "reply_markup":kb}, timeout=TG_TMO).ok
    except: return False

def tg_photo_with_buttons(path: str, cap: str = "", signal_dir: int = 0, flt=None) -> int:
    if not TG_TOKEN: return 0
    ok = 0
    for c in get_subs(flt):
        if _photo_with_buttons(c, path, cap, signal_dir): ok += 1
        time.sleep(0.05)
    return ok

def _answer_callback(callback_id: str, text: str = "جاري التحليل..."):
    try:
        _sess().post(TG_API+"/answerCallbackQuery",
            json={"callback_query_id":callback_id,"text":text}, timeout=5)
    except: pass

def _call_ai_api(url: str, headers: dict, model: str, fmt: str, prompt: str) -> str:
    """يستدعي AI API ويُرجع النص أو None عند الفشل"""
    try:
        payload = {"model": model, "max_tokens": 1500,
                   "messages": [{"role":"user","content": prompt}]}
        resp = requests.post(url, headers=headers, json=payload, timeout=40)
        if not resp.ok:
            log.debug(f"[AI] HTTP {resp.status_code}: {resp.text[:100]}")
            return None
        data = resp.json()
        if fmt == "anthropic":
            return data["content"][0]["text"].strip()
        else:
            return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.debug(f"[AI] خطأ: {e}")
        return None


def _ai_deep_analysis(strat: str, results: dict) -> str:
    api_key  = cfg.get("CLAUDE_API_KEY","").strip()
    provider = cfg.get("CLAUDE_PROVIDER","auto").strip().lower()
    if not api_key:
        return "⚠️ أضف AI_API_KEY في الإعدادات — راجع /about لمزوّدين مجانيين"

    prompt = _make_prompt(strat, results, results.get("price",0))

    if provider == "auto":
        # جرّب كل مزوّد بالترتيب
        for pname in _AUTO_ORDER:
            pcfg = _AI_PROVIDERS[pname]
            log.info(f"[AI-Auto] جرّب {pname}...")
            result = _call_ai_api(
                pcfg["url"], pcfg["headers"](api_key),
                pcfg["model"], pcfg["fmt"], prompt
            )
            if result:
                log.info(f"[AI-Auto] ✅ نجح {pname}")
                return result
            log.debug(f"[AI-Auto] فشل {pname} — جرّب التالي")
        return "❌ فشلت جميع المزوّدين — تحقق من صلاحية المفتاح"

    # مزوّد محدد
    prov_cfg = _AI_PROVIDERS.get(provider, _AI_PROVIDERS["groq"])
    url      = prov_cfg["url"]
    model    = prov_cfg["model"]
    fmt      = prov_cfg["fmt"]
    headers  = prov_cfg["headers"](api_key)
    price    = results.get("price", 0)
    prompt   = _make_prompt(strat, results, price)
    try:
        resp = requests.post(url, headers=headers,
            json={"model":model,"max_tokens":1500,
                  "messages":[{"role":"user","content":prompt}]},
            timeout=40)
        if not resp.ok: return "خطأ " + str(resp.status_code) + ": " + resp.text[:100]
        data = resp.json()
        return (data["choices"][0]["message"]["content"].strip()
                if provider=="ppq" else data["content"][0]["text"].strip())
    except Exception as e:
        return "خطأ في الاتصال: " + str(e)

def _make_prompt(strat: str, results: dict, price: float) -> str:
    v7   = results.get("v7",{})
    smc  = results.get("smc",{})
    ob   = results.get("ob",{})
    asia = results.get("asia",{})
    rng  = results.get("range",{})
    agg  = results.get("agg",{})
    os_  = ob.get("signal")
    lvl  = rng.get("levels",{})

    if strat == "analyze_v7":
        ind_lines = "\n".join(
            "  " + nm.replace("V7_","") + ": " + ("BUY" if inf["signal"]==1 else "SELL" if inf["signal"]==-1 else "NEUTRAL") + " — " + inf["reason"]
            for nm,inf in v7.get("strats",{}).items()
        )
        tfs = ", ".join(tf+":"+("UP" if v==1 else "DN" if v==-1 else "--") for tf,v in v7.get("tf_v",{}).items())
        return ("أنت محلل ذهب خبير. حلّل نتائج استراتيجية V7:\n\n"
                "السعر: " + str(round(price,2)) + "\n"
                "الإطارات: " + tfs + "\n"
                "DXY: " + v7.get("dxy_txt","—") + "\n"
                "وزن الشراء: " + str(v7.get("buy_w",0)) + "/" + str(v7.get("max_weight",22)) + "\n"
                "المؤشرات:\n" + ind_lines + "\n\n"
                "اكتب تحليلاً احترافياً بالعربية (6-8 جمل) يشمل توجه كل إطار، أقوى الإشارات، التوافق، وتوصيتك النهائية مع مستوى الثقة.")

    if strat == "analyze_smc":
        return ("أنت خبير Smart Money. حلّل نتائج SMC:\n\n"
                "السعر: " + str(round(price,2)) + "\n"
                "الاتجاه: " + smc.get("trend","—") + "\n"
                "BOS: " + str(smc.get("bos","—")) + " | CHoCH: " + str(smc.get("choch","—")) + " | MSS: " + str(smc.get("mss","—")) + "\n"
                "نقاط: " + str(smc.get("score",0)) + "\n"
                "المنطقة: " + smc.get("pd",{}).get("zone","—") + "\n"
                "الإشارات: " + "\n".join(smc.get("reasons",[])) + "\n\n"
                "اكتب تحليلاً عميقاً بالعربية (6-8 جمل) يشمل BOS/CHoCH/MSS، السيولة، Premium/Discount، Order Blocks، وتوصيتك.")

    if strat == "analyze_obinob":
        if os_:
            return ("أنت خبير Order Blocks. حلّل إشارة OBinOB:\n\n"
                    "السعر: " + str(round(price,2)) + "\n"
                    "الزوج: " + ob.get("pair","—") + "\n"
                    "HTF OB: " + str(os_.htf.lo) + "–" + str(os_.htf.hi) + " (" + os_.htf.method + ") قوة=" + str(round(os_.htf.str_,1)) + "\n"
                    "LTF OB: " + str(os_.ltf.lo) + "–" + str(os_.ltf.hi) + " (" + os_.ltf.method + ") قوة=" + str(round(os_.ltf.str_,1)) + "\n"
                    "التداخل: " + str(round(os_.ovl*100)) + "% | R:R=" + str(os_.rr) + "\n\n"
                    "اكتب تحليلاً (5-7 جمل) يشمل جودة التداخل، R:R، والتوصية.")
        return "السعر " + str(round(price,2)) + ". لا يوجد تقاطع OBinOB حالياً. حلّل السبب واقترح متى يمكن حدوثه."

    if strat == "analyze_asia":
        return ("أنت خبير جلسات. حلّل جلسة آسيا:\n\n"
                "الحالة: " + ("نشطة" if asia.get("active") else "خارج النافذة") + "\n"
                "النوع: " + str(asia.get("signal_type","—")) + "\n"
                "دخول: " + str(asia.get("entry","—")) + " | SL: " + str(asia.get("sl","—")) + " | R:R: " + str(asia.get("rr","—")) + "\n"
                "الأسباب: " + "\n".join(asia.get("reasons",["لا إشارة"])) + "\n\n"
                "اكتب تحليلاً (4-6 جمل) يشمل جودة CHoCH/BOS، نقطة 50% retracement، وتوصيتك.")

    if strat == "analyze_range":
        return ("أنت خبير تحليل النطاقات. حلّل Range الحالي:\n\n"
                "السعر: " + str(round(price,2)) + "\n"
                "الدعم: " + str(lvl.get("support","—")) + " (لمسات=" + str(lvl.get("sup_touches","—")) + ")\n"
                "المقاومة: " + str(lvl.get("resistance","—")) + " (لمسات=" + str(lvl.get("res_touches","—")) + ")\n"
                "العرض: " + str(lvl.get("range_width_pct","—")) + "%\n"
                "الموقع: " + rng.get("position","—") + "\n"
                "الأسباب: " + "\n".join(rng.get("reasons",[])) + "\n\n"
                "اكتب تحليلاً (5-7 جمل) يشمل قوة المستويات، احتمالية الانعكاس مقابل الكسر، أفضل نقطة دخول، وتوصيتك.")

    # analyze_ai or analyze_full
    votes = agg.get("votes",{})
    return ("أنت محلل ذهب خبير. قدّم تحليلاً شاملاً:\n\n"
            "السعر: " + str(round(price,2)) + "\n"
            "التوافق: " + str(agg.get("agree",0)) + "/5 | الثقة: " + str(agg.get("conf",0)) + "%\n"
            "الاتجاه: " + agg.get("lbl","—") + "\n"
            "V7=" + str(votes.get("V7",0)) + " SMC=" + str(votes.get("SMC",0)) + " OBinOB=" + str(votes.get("OBinOB",0)) + " Asia=" + str(votes.get("Asia",0)) + " Range=" + str(votes.get("Range",0)) + "\n"
            "دخول: " + str(agg.get("entry","—")) + " | SL: " + str(agg.get("sl","—")) + " | TP: " + str(agg.get("tp","—")) + "\n\n"
            "اكتب تحليلاً ذكياً شاملاً (8-10 جمل) يشمل توافق الاستراتيجيات، أقوى الإشارات، السيناريو الأكثر احتمالاً، إدارة المخاطر، وتوصيتك النهائية بثقة.")


def _quick_local(data: str, results: dict) -> str:
    v7=results.get("v7",{}); smc=results.get("smc",{})
    ob=results.get("ob",{}); asia=results.get("asia",{})
    rng=results.get("range",{}); agg=results.get("agg",{})
    os_=ob.get("signal"); lvl=rng.get("levels",{})

    if data=="analyze_v7":
        lines=["<b>الأوزان:</b> شراء="+str(v7.get("buy_w",0))+"/"+str(v7.get("max_weight",22))+" | بيع="+str(v7.get("sell_w",0))]
        lines.append("<b>الإطارات:</b> "+" | ".join(tf+":"+("🟢" if v==1 else "🔴" if v==-1 else "⬜") for tf,v in v7.get("tf_v",{}).items()))
        for nm,inf in v7.get("strats",{}).items():
            ic="🟢" if inf["signal"]==1 else ("🔴" if inf["signal"]==-1 else "⬜")
            lines.append("  "+ic+" "+esc(nm.replace("V7_",""))+": "+esc(inf["reason"]))
        return "\n".join(lines)

    if data=="analyze_smc":
        return ("<b>الاتجاه:</b> "+smc.get("trend","—")+" | نقاط="+str(smc.get("score",0))+"\n"
                "<b>BOS:</b> "+str(smc.get("bos","—"))+" | <b>CHoCH:</b> "+str(smc.get("choch","—"))+" | <b>MSS:</b> "+str(smc.get("mss","—"))+"\n"
                +"\n".join(esc(r) for r in smc.get("reasons",[])))

    if data=="analyze_obinob":
        if os_:
            return ("<b>زوج:</b> "+esc(ob.get("pair","—"))+"\n"
                    "HTF ("+esc(os_.htf.tf)+"): "+str(os_.htf.lo)+"–"+str(os_.htf.hi)+"\n"
                    "LTF ("+esc(os_.ltf.tf)+"): "+str(os_.ltf.lo)+"–"+str(os_.ltf.hi)+"\n"
                    "تداخل: "+str(round(os_.ovl*100))+"% | قوة: "+str(os_.strength)+"/10 | R:R="+str(os_.rr))
        return "لا يوجد تقاطع OBinOB حالياً"

    if data=="analyze_asia":
        return ("\n".join(esc(r) for r in asia.get("reasons",["خارج نافذة 02:00-05:00 UTC"]))
                +("\n<b>دخول:</b> "+str(asia.get("entry","—"))+" | SL: "+str(asia.get("sl","—"))+" | TP1: "+str(asia.get("tp1","—")) if asia.get("entry") else ""))

    if data=="analyze_range":
        return ("<b>الدعم:</b> "+str(lvl.get("support","—"))+" ("+str(lvl.get("sup_touches","—"))+" لمسات)\n"
                "<b>المقاومة:</b> "+str(lvl.get("resistance","—"))+" ("+str(lvl.get("res_touches","—"))+" لمسات)\n"
                "<b>العرض:</b> "+str(lvl.get("range_width_pct","—"))+"%\n"
                "<b>الموقع:</b> "+esc(rng.get("position","—"))+"\n"
                +"\n".join(esc(r) for r in rng.get("reasons",[])))

    votes=agg.get("votes",{})
    return ("<b>التوافق:</b> "+str(agg.get("agree",0))+"/5 | <b>الثقة:</b> "+str(agg.get("conf",0))+"%\n"
            "<b>الاتجاه:</b> "+agg.get("lbl","—")+"\n"
            "V7:"+str(votes.get("V7",0))+" SMC:"+str(votes.get("SMC",0))+" OBinOB:"+str(votes.get("OBinOB",0))+" Asia:"+str(votes.get("Asia",0))+" Range:"+str(votes.get("Range",0)))


def handle_callback(callback_query: dict):
    cb_id = callback_query.get("id","")
    data  = callback_query.get("data","")
    cid   = str(callback_query["from"]["id"])
    log.info("[BTN] "+cid+" pressed: "+data)
    _answer_callback(cb_id, "جاري التحليل...")
    if not _last_results:
        _send1(cid, "لا توجد نتائج محفوظة — انتظر الإشارة القادمة")
        return
    names = {
        "analyze_v7":"🔢 V7 متعدد الإطارات",
        "analyze_smc":"💎 SMC Smart Money",
        "analyze_obinob":"📦 OBinOB كتل الأوامر",
        "analyze_asia":"🌙 انعكاس جلسة آسيا",
        "analyze_range":"📐 Range النطاق",
        "analyze_ai":"🤖 Claude AI شامل",
        "analyze_full":"📊 ملخص كامل",
    }
    strat_name = names.get(data, "تحليل")
    price = _last_results.get("price", 0)
    header = ("🔍 <b>تحليل " + strat_name + "</b>\n"
              + "💰 السعر: " + str(round(price,2)) + "  |  ⏰ " + _last_results_ts + "\n"
              + "━━━━━━━━━━━━━━━━━━━━━━━\n\n")
    quick   = _quick_local(data, _last_results)
    ai_text = _ai_deep_analysis(data, _last_results)
    full    = header + quick + "\n\n🤖 <b>تحليل Claude AI:</b>\n" + esc(ai_text)
    _send1(cid, full[:4000])
    log.info("[BTN] تم إرسال تحليل " + data + " إلى " + cid)



def _pu_prime_ad(signal_dir: int = 0) -> str:
    """إعلان PU Prime يُضاف أسفل كل رسالة — يتغيّر بحسب اتجاه الإشارة"""
    bonus_line = (
        "🎯 الآن وقت الدخول! استغل البونص وافتح صفقتك 🔥"
        if signal_dir != 0 else
        "📈 جهّز حسابك قبل الإشارة القادمة!"
    )
    # SYMBOL & PAIR مأخوذان من config — ديناميكي لكل سلعة
    _pair = cfg.get("SYMBOL", "BTC-USD")
    _name = {"BTC-USD":"الذهب","BTC-USD":"البيتكوين",
             "ETH-USD":"الإيثريوم","SI=F":"الفضة"}.get(_pair, "السلعة")
    return (
        "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏦 <b>سجّل الآن في PU Prime وتداول {_name} باحترافية</b>\n\n"
        "✨ <b>لماذا PU Prime؟</b>\n"
        "  💰 <b>بونص 50%</b> على الإيداع الأول\n"
        f"  📊 سبريد من 0.0 pip على {_name} {_pair}\n"
        "  ⚡ تنفيذ فوري بدون re-quote\n"
        "  🛡 تنظيم دولي معتمد (VFSC / ASIC)\n"
        "  💳 إيداع وسحب بالعملات الرقمية USDT\n"
        "  📱 منصة MT4 / MT5 + تطبيق موبايل\n"
        "  🎓 حساب تجريبي مجاني بدون قيود\n"
        "  🌍 دعم عربي على مدار الساعة\n\n"
        f"  {bonus_line}\n\n"
        "🔗 <b>سجّل عبر رابط الإحالة:</b>\n"
        "👇 <a href=\"https://puvip.co/la-partners/rqHSA4uK\">https://puvip.co/la-partners/rqHSA4uK</a>\n\n"
        "🎁 <b>كود الإحالة: <code>rqHSA4uK</code></b>\n"
        "  أدخله عند التسجيل لتفعيل البونص 50% 🎯\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )


def msg_signal(v7: dict, smc: dict, ob: dict, agg: dict, trigger_reasons: list) -> str:
    d=agg["d"]; os_=ob.get("signal")
    lines=[
        f"{'📈' if d==1 else '📉'} <b>إشارة ذهب موحّدة — BTC/USD</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🎯 <b>الاتجاه: {agg['lbl']}</b>",
        f"📊 توافق: <b>{agg['agree']}/3</b>  |  ثقة: <b>{agg['conf']}%</b>  {stars(agg['conf'],100)}",
        f"🕐 الجلسة: {trading_session()}  |  ⏰ {utcnow_str()}",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "💹 <b>نقاط الدخول والأهداف:</b>",
        f"   🔵 <b>دخول:</b>      {agg['entry']:.2f}",
        f"   🔴 <b>Stop Loss:</b> {agg['sl']:.2f}",
        f"   🔵 <b>TP1 (50%):</b> {agg['tp1']:.2f}" if agg.get("tp1") else "",
        f"   🟢 <b>TP2 (75%):</b> {agg['tp2']:.2f}" if agg.get("tp2") else "",
        f"   🟣 <b>TP3 (25%):</b> {agg['tp3']:.2f}" if agg.get("tp3") else "",
        f"   📐 <b>R:R Ratio:</b> 1:{agg['rr']:.2f}",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    lines = [l for l in lines if l != ""]

    # ── V7 كاملة ──
    ic="✅" if v7["vote"]==d else ("❌" if v7["vote"]==-d else "⬜")
    mw=v7.get("max_weight",22)
    bw=v7.get("buy_w",0); sw=v7.get("sell_w",0)
    lines.append(f"① <b>V7 — متعدد الإطارات</b> {ic}")
    lines.append(f"   وزن الشراء: {bw}/{mw}  |  وزن البيع: {sw}/{mw}")
    lines.append(f"   إطارات صاعدة: {v7['bt']}/4  |  هابطة: {v7['st']}/4")
    lines.append(f"   {esc(v7.get('dxy_txt','DXY: —'))}")
    lines.append(f"   حجم: {'✅ مرتفع' if v7.get('vol_ok') else '⚠️ منخفض'}")
    lines.append("")
    lines.append("   <b>المؤشرات التفصيلية (إطار 1h):</b>")
    for nm,inf in v7.get("strats",{}).items():
        sg=inf["signal"]; ic2="✅" if sg==d else ("❌" if sg==-d else "⬜")
        wt=inf.get("weight",1); wt_s=f"(×{wt})" if wt>1 else ""
        short_nm=nm.replace("V7_","")
        lines.append(f"   {ic2} <b>{esc(short_nm)}</b>{wt_s}: {esc(inf['reason'])}")
    lines.append("")
    lines.append("   <b>أصوات الإطارات الزمنية:</b>")
    tf_icons={"5m":"🕐","15m":"🕒","1h":"🕐","4h":"🕓"}
    for tf,vote in v7.get("tf_v",{}).items():
        ic3="🟢" if vote==1 else ("🔴" if vote==-1 else "⬜")
        lines.append(f"   {ic3} {tf_icons.get(tf,'')} {tf}")

    # ── SMC كاملة ──
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    ic="✅" if smc["vote"]==d else ("❌" if smc["vote"]==-d else "⬜")
    lines.append(f"② <b>SMC — Smart Money Concepts</b> {ic}")
    lines.append(f"   اتجاه: <b>{smc['trend']}</b>  |  نقاط: {smc['score']}  |  ثقة: {smc['conf']}%")
    bos_str=f"BOS: {'✅ صاعد' if smc['bos']=='BULL' else ('✅ هابط' if smc['bos']=='BEAR' else '—')}"
    choch_str=f"CHoCH: {'✅ صاعد' if smc['choch']=='BULL' else ('✅ هابط' if smc['choch']=='BEAR' else '—')}"
    mss_str=f"MSS: {'✅ صاعد' if smc['mss']=='BULL' else ('✅ هابط' if smc['mss']=='BEAR' else '—')}"
    lines.append(f"   {bos_str}  |  {choch_str}  |  {mss_str}")
    pd_=smc.get("pd",{})
    if pd_:
        lines.append(f"   منطقة: <b>{esc(pd_.get('zone','—'))}</b>  ({pd_.get('dist_pct',0):+.2f}% من المنتصف)")
    liq=smc.get("liq",{})
    if liq.get("eq_highs"): lines.append(f"   💧 سيولة فوق: {', '.join(str(h) for h in liq['eq_highs'])}")
    if liq.get("eq_lows"):  lines.append(f"   💧 سيولة تحت: {', '.join(str(l) for l in liq['eq_lows'])}")
    lines.append("   <b>أسباب الإشارة:</b>")
    for r in smc["reasons"]: lines.append(f"   {esc(r)}")

    # ── OBinOB كاملة ──
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    ic="✅" if ob["vote"]==d else ("❌" if ob["vote"]==-d else "⬜")
    lines.append(f"③ <b>OBinOB — كتل الأوامر المتداخلة</b> {ic}")
    if os_:
        lines.append(f"   زوج: <b>{esc(ob['pair'])}</b>  |  قوة: {os_.strength}/10 {stars(os_.strength)}")
        lines.append(f"   HTF OB ({esc(os_.htf.tf)}): {os_.htf.lo:.2f}–{os_.htf.hi:.2f}  [{esc(os_.htf.method)}]  قوة×ATR={os_.htf.str_:.1f}")
        lines.append(f"   LTF OB ({esc(os_.ltf.tf)}): {os_.ltf.lo:.2f}–{os_.ltf.hi:.2f}  [{esc(os_.ltf.method)}]  قوة×ATR={os_.ltf.str_:.1f}")
        lines.append(f"   تداخل HTF↔LTF: {os_.ovl*100:.0f}%")
        lines.append(f"   TP1: {os_.tp1:.2f}  |  TP2: {os_.tp:.2f}")
    else: lines.append("   لا توافق OBinOB في الوقت الحالي")

    # ── سبب التشغيل ──
    if trigger_reasons:
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"🔔 <i>سبب التحليل: {esc(' • '.join(trigger_reasons))}</i>")

    lines.append(f"\n#Bitcoin #BTC_USD #إشارات_بيتكوين #تحليل_فني")
    lines.append(_pu_prime_ad(d))
    return "\n".join(lines)

def msg_analysis(v7: dict, smc: dict, ob: dict, price: float, asia: dict = None, rng: dict = None) -> str:
    dxy_txt=v7.get("dxy_txt","—"); os_=ob.get("signal")
    pd_=smc.get("pd",{})
    vt=[]
    for k,v in {"V7":v7["vote"],"SMC":smc["vote"],"OBinOB":ob["vote"]}.items():
        ic="🟢" if v==1 else ("🔴" if v==-1 else "⬜")
        ar="شراء" if v==1 else ("بيع" if v==-1 else "محايد")
        vt.append(f"  {ic} {k}: {ar}")
    lines=[
        "📊 <b>تحليل السوق — BTC/USD</b>",
        f"💰 السعر: <b>{price:.2f}</b>  |  🕐 {trading_session()}  |  ⏰ {utcnow_str()}",
        f"   {esc(dxy_txt)}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "<b>أصوات الاستراتيجيات:</b>",*vt,"",
        f"① V7: شراء_وزن={v7.get('buy_w',0)}/{v7.get('max_weight',22)} ({v7['bt']}/4 إطار)  |  بيع_وزن={v7.get('sell_w',0)} ({v7['st']}/4)",
        f"② SMC: نقاط={smc['score']}  |  {smc['trend']}  |  BOS={smc['bos']}  CHoCH={smc['choch']}",
        f"③ OBinOB: {'قوة='+str(os_.strength)+'/10  زوج='+ob['pair'] if os_ else 'لا إشارة'}",
        f"④ جلسة آسيا: {'✅ نشطة — '+str((asia or {}).get('signal_type','—')) if (asia or {}).get('active') else '⏸ خارج نافذة 02:00–05:00 UTC'}",
    ]
    if pd_: lines.append(f"   SMC Zone: {esc(pd_.get('zone','—'))}")
    lines+=[
        "",f"⚙️ الإشارة عند توافق {UNI_AGR}+ من 3  |  #XAU_USD"
    ]
    lines.append(_pu_prime_ad(0))
    return "\n".join(lines)

def msg_daily(perf: dict, price: float) -> str:
    lines=[
        f"📈 <b>التقرير اليومي — بوت {SYMBOL} الموحّد</b>",
        f"💰 السعر: {price:.2f}  |  📅 {utcnow().strftime('%Y-%m-%d')}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "<b>أداء الاستراتيجيات:</b>",
    ]
    ts=0; tw=0
    groups={"V7":[s for s in STRAT_NAMES if s.startswith("V7")],
             "SMC":[s for s in STRAT_NAMES if s.startswith("SMC")],
             "OBinOB":[s for s in STRAT_NAMES if s.startswith("OBinOB")]}
    for grp,strats in groups.items():
        lines.append(f"\n<b>● {grp}:</b>")
        for s in strats:
            p=perf.get(s,{"signals":0,"wins":0,"losses":0})
            tot=p["wins"]+p["losses"]
            wr=p["wins"]/tot*100 if tot else 0
            bar="█"*int(wr/10)+"░"*(10-int(wr/10))
            wr_s=f"{wr:.1f}%" if tot else "—"
            lines.append(f"  {bar} {esc(s.replace('V7_','').replace('SMC_','').replace('OBinOB','OBinOB'))}: {wr_s} ({p['wins']}✅/{p['losses']}❌/{p['signals']} إشارة)")
            ts+=p["signals"]; tw+=p["wins"]
    ov=tw/ts*100 if ts else 0
    lines+=["\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"🏆 <b>الإجمالي: {ov:.1f}%</b>  |  📊 {ts} إشارة"]
    lines.append(_pu_prime_ad(0))
    return "\n".join(lines)

# ══════════════════════════════════════════════════════════════════
# SMART TRIGGER
# ══════════════════════════════════════════════════════════════════
class SmartTrigger:
    def __init__(self):
        self.last_price=0.; self.vol_avg=0.
        self.last_5m=-1; self.last_15m=-1
        self.last_run=utcnow(); self.cycles=0
        self.first_run=True   # أول دورة تُشغَّل دائماً

    def _qfetch(self):
        try:
            return fetch(SYMBOL,"2d","5m"), fetch(SYMBOL,"5d","15m")
        except: return None,None

    def check(self) -> Tuple[bool,list]:
        self.cycles+=1; reasons=[]
        # أول دورة عند بدء التشغيل — شغّل التحليل فوراً
        if self.first_run:
            self.first_run=False
            self._mark()
            reasons.append("🚀 تشغيل أولي — تحليل فوري")
            log.info("[Trigger] أول دورة — تحليل فوري")
            return True, reasons
        df5,df15=self._qfetch()
        elapsed=(utcnow()-self.last_run).total_seconds()/60
        if df5 is None:
            if elapsed>=TRIG_FM: reasons.append(f"⏱ إجباري — فشل جلب البيانات"); self._mark(); return True,reasons
            return False,[]
        price=float(df5["Close"].iloc[-1])
        self.vol_avg=float(df5["Volume"].rolling(20).mean().iloc[-1] or 1)
        now_vol=float(df5["Volume"].iloc[-1])
        # ① سعر
        if self.last_price>0:
            chg=abs(price-self.last_price)/self.last_price*100
            if chg>=TRIG_PCH:
                ar="↑" if price>self.last_price else "↓"
                reasons.append(f"💰 سعر {ar}{chg:.3f}%  {self.last_price:.2f}→{price:.2f}")
        # ② حجم
        if now_vol>=self.vol_avg*TRIG_VOL:
            reasons.append(f"📊 حجم×{now_vol/self.vol_avg:.1f} ({now_vol:,.0f})")
        # ③ شمعة 5m
        if TRIG_C5M:
            idx5=len(df5)
            if self.last_5m>0 and idx5!=self.last_5m: reasons.append(f"🕯 شمعة 5m جديدة @ {price:.2f}")
            self.last_5m=idx5
        # ④ شمعة 15m
        if TRIG_C15M and df15 is not None:
            idx15=len(df15)
            if self.last_15m>0 and idx15!=self.last_15m: reasons.append("🕯 شمعة 15m جديدة")
            self.last_15m=idx15
        # ⑤ إجباري
        if elapsed>=TRIG_FM: reasons.append(f"⏱ إجباري {TRIG_FM}د (مضى {elapsed:.1f}د)")
        self.last_price=price
        if reasons: self._mark(); log.info(f"🔔 {' | '.join(reasons)}"); return True,reasons
        log.debug(f"⏸ لا تغيير | سعر={price:.2f} | دقيقة#{self.cycles}"); return False,[]

    def _mark(self): self.last_run=utcnow(); self.cycles=0

# ══════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════
def main():
    log.info("="*65)
    log.info("🚀 بوت البيتكوين الموحّد — يبدأ التشغيل")
    log.info(f"SYMBOL={SYMBOL} | فحص كل {RUN_M}د | إجباري كل {TRIG_FM}د")
    log.info(f"V7: TF>={MIN_TF} | SMC: score>={SMC_SC} | OBinOB: RR>={OB_RR}")
    log.info("="*65)

    tg_ok=tg_check()
    if tg_ok:
        tg_send(
            "🟠 <b>بوت البيتكوين الموحّد — انطلق الآن!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 {SYMBOL}  |  {trading_session()}  |  {utcnow_str()}\n\n"
            "⚙️ <b>4 استراتيجيات نشطة:</b>\n"
            "  ① V7  — 10 مؤشرات × 4 إطارات زمنية\n"
            "  ② SMC — BOS/CHoCH/MSS/OB/FVG/Liquidity\n"
            "  ③ OBinOB — كتل الأوامر المتداخلة HTF×LTF\n"
            "  ④ انعكاس جلسة آسيا (02:00–05:00 UTC)\n"
            "  ⑤ Range — تداول النطاق (دعم/مقاومة)\n"
            "  🤖 Claude AI — محلّل ذكي (عند تفعيله)\n\n"
            "🎯 <b>كل إشارة تحتوي:</b>\n"
            "  نقطة دخول • Stop Loss • TP1 / TP2 / TP3\n"
            "  نسبة R:R • رسم بياني احترافي • مستوى ثقة\n\n"
            f"⚡ مشغّل ذكي — فحص كل {RUN_M}د | إجباري كل {TRIG_FM}د\n"
            f"⚙️ إشارة عند توافق {UNI_AGR}+ من 4\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💛 أرسل /support لدعم المطوّر\n"
            "📖 أرسل /about لوصف مفصّل | /help للأوامر"
        )

    perf=load_perf(); last_sig=None; last_rpt=None; cycle=0; cur_price=65000.0
    trigger=SmartTrigger()

    while True:
        cycle+=1; now=utcnow()
        log.debug(f"── فحص #{cycle} ({utcnow_str()}) ──")
        try: proc_cmds()
        except: pass
        try:
            dfc=fetch(SYMBOL,"2d","1h")
            if dfc is not None: cur_price=float(dfc["Close"].iloc[-1]); eval_pending(perf,cur_price)
        except: pass
        if now.hour==RPT_HOUR and last_rpt!=now.date():
            try: tg_send(msg_daily(perf,cur_price)); last_rpt=now.date(); log.info("📅 تقرير يومي")
            except: log.exception("خطأ في التقرير")

        should,reasons=trigger.check()
        if not should: time.sleep(RUN_M*60); continue

        log.info(f"━━━ تحليل كامل #{cycle} ━━━")
        _v7e={"vote":0,"score":0,"max_weight":22,"tf_v":{},"strats":{},"df1h":None,"dxy":0,"dxy_txt":"—",
              "entry":None,"sl":None,"tp":None,"tp1":None,"tp2":None,"tp3":None,"rr":None,
              "vol_ok":False,"bt":0,"st":0,"buy_w":0,"sell_w":0,"buy_c":0,"sell_c":0}
        _sm={"vote":0,"score":0,"signal":"WAIT","entry":None,"sl":None,"tp":None,
             "tp1":None,"tp2":None,"tp3":None,"rr":None,"conf":0,"reasons":[],
             "trend":"محايد","bos":None,"choch":None,"mss":None,"obs":[],"fvgs":[],
             "liq":{},"pd":{},"price":cur_price}
        _ob={"vote":0,"signal":None,"pair":"","dfl":None}

        log.info("① V7...")
        try:    v7=analyze_v7()
        except: log.exception("V7 error"); v7=_v7e

        log.info("② SMC...")
        try:
            df15=fetch(SYMBOL,"30d","15m")
            if df15 is not None:
                cn=df2c(df15.tail(SMC_CN)); smc=analyze_smc(cn); cur_price=cn[-1]["c"]
            else: smc=_sm
        except: log.exception("SMC error"); smc=_sm

        log.info("③ OBinOB...")
        try:    ob=analyze_obinob()
        except: log.exception("OBinOB error"); ob=_ob

        log.info("④ Asia Reversal...")
        _as={"vote":0,"active":False,"signal_type":None,"impulse":None,
             "choch":None,"entry":None,"sl":None,"tp1":None,"tp2":None,
             "rr":None,"reasons":[],"score":0,"conf":0}
        try:    asia=analyze_asia()
        except: log.exception("Asia error"); asia=_as

        log.info("⑤ Range...")
        _re={"vote":0,"active":False,"range":None,"conf_data":None,"entry":None,"sl":None,"tp1":None,"tp2":None,"tp3":None,"rr":None,"reasons":[],"score":0,"confidence":0,"analysis_txt":"","levels":{},"position":"—","signal_type":None}
        try: rng_res=analyze_range()
        except: log.exception("Range error"); rng_res=_re
        agg=aggregate(v7,smc,ob,asia,rng_res)

        # ── تحليل الذكاء الاصطناعي ──
        log.info("④ Claude AI...")
        try:    ai=ai_analyze(v7,smc,ob,agg,smc.get("price",cur_price))
        except: log.exception("AI error"); ai={"available":False}
        agg=merge_with_ai(agg,ai)

        _save_results(v7,smc,ob,asia,rng_res,agg,smc.get("price",cur_price))

        if agg["d"]!=0 and agg["entry"] is not None:
            sid=(agg["d"],round(agg["entry"]))
            if sid==last_sig:
                log.info("🔁 إشارة مكررة")
            else:
                ts=now.isoformat()
                for nm,inf in v7.get("strats",{}).items():
                    if inf["signal"]==agg["d"]: rec_sig(perf,nm,agg["d"],agg["entry"],agg["sl"],agg["tp"],ts)
                if smc["vote"]==agg["d"]:
                    for smc_s in ["SMC_BOS","SMC_CHoCH","SMC_OB","SMC_MSS","SMC_Liquidity","SMC_PremDisc"]:
                        if smc_s.replace("SMC_","") in str(smc["reasons"]):
                            rec_sig(perf,smc_s,agg["d"],agg["entry"],agg["sl"],agg["tp"],ts)
                if ob.get("signal"): rec_sig(perf,"OBinOB",agg["d"],agg["entry"],agg["sl"],agg["tp"],ts); _save_ob(ob["signal"])
                if asia.get("vote")==agg["d"] and asia.get("active"):
                    rec_sig(perf,"Asia_Reversal",agg["d"],agg["entry"],agg["sl"],agg.get("tp",agg["entry"]),ts)
                if rng_res.get("vote")==agg["d"] and rng_res.get("active"):
                    rec_sig(perf,"Range_Buy" if agg["d"]==1 else "Range_Sell",agg["d"],agg["entry"],agg["sl"],agg.get("tp",agg["entry"]),ts)

                txt=msg_signal(v7,smc,ob,agg,reasons)
                try:
                    ch=build_chart(v7,smc,ob,agg)
                    if ch:
                        sent=tg_photo_with_buttons(ch,cap=txt,signal_dir=agg["d"],flt=S_SIG)
                        if not sent: tg_send_with_buttons(txt,signal_dir=agg["d"],flt=S_SIG)
                    else: tg_send_with_buttons(txt,signal_dir=agg["d"],flt=S_SIG)
                except: log.exception("Chart error"); tg_send_with_buttons(txt,signal_dir=agg["d"],flt=S_SIG)
                dr="شراء 🟢" if agg["d"]==1 else "بيع 🔴"
                log.info(f"✅ {dr} توافق={agg['agree']}/3 ثقة={agg['conf']}% RR={agg['rr']} دخول={agg['entry']:.2f}")
                last_sig=sid
        else:
            # إرسال التحليل لمشتركي التحليل والكل
            ana_txt=msg_analysis(v7,smc,ob,smc.get("price",cur_price),asia,rng_res)
            tg_send_with_buttons(ana_txt,signal_dir=0,flt=S_ANA)
            log.info(f"📊 لا إشارة V7={v7['vote']} SMC={smc['vote']} OBinOB={ob['vote']}")

        log.info(f"⏳ انتظار {RUN_M}د...\n")
        time.sleep(RUN_M*60)

if __name__=="__main__":
    try: main()
    except KeyboardInterrupt: log.info("⏹ تم الإيقاف")
