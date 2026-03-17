#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_ai.py — أداة تشخيص سريعة لـ PPQ.AI API
تشغيل: python test_ai.py
"""

import json, os, sys, requests

print("=" * 55)
print("🔍 تشخيص اتصال PPQ.AI API")
print("=" * 55)

CFG_FILE = "config.json"
if not os.path.exists(CFG_FILE):
    print(f"❌ ملف {CFG_FILE} غير موجود!")
    print("   أنشئ config.json يحتوي:")
    print('   {"TELEGRAM_TOKEN":"...","TELEGRAM_CHAT_ID":"...",')
    print('    "CLAUDE_API_KEY":"sk-iH...","CLAUDE_PROVIDER":"ppq"}')
    sys.exit(1)

cfg = json.load(open(CFG_FILE, encoding="utf-8"))

print("\n📋 فحص الإعدادات:")
api_key  = cfg.get("CLAUDE_API_KEY","").strip()
provider = cfg.get("CLAUDE_PROVIDER","anthropic").strip()
tg_token = cfg.get("TELEGRAM_TOKEN","").strip()
tg_chat  = cfg.get("TELEGRAM_CHAT_ID","").strip()

print(f"  CLAUDE_API_KEY  : {'✅ موجود ('+api_key[:8]+'...)' if api_key else '❌ فارغ!'}")
print(f"  CLAUDE_PROVIDER : {'✅ '+provider if provider else '❌ فارغ'}")
print(f"  TELEGRAM_TOKEN  : {'✅ موجود' if tg_token else '❌ فارغ!'}")
print(f"  TELEGRAM_CHAT_ID: {'✅ موجود' if tg_chat else '❌ فارغ!'}")

if not api_key:
    print("\n❌ CLAUDE_API_KEY فارغ — لا يمكن المتابعة")
    sys.exit(1)

ENDPOINTS = {
    "ppq":       ("https://api.ppq.ai/chat/completions",   "openai"),
    "anthropic": ("https://api.anthropic.com/v1/messages", "anthropic"),
}
url, fmt = ENDPOINTS.get(provider, ENDPOINTS["anthropic"])
print(f"\n🌐 سيتم الاتصال بـ: {url}")
print(f"   صيغة الطلب: {fmt}")

print("\n⏳ اختبار الاتصال...")

if fmt == "openai":
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
    }
    payload = {
        "model":      "claude-sonnet-4.6",
        "max_tokens": 50,
        "messages":   [{"role":"user","content":"قل: اتصال ناجح"}],
    }
else:
    headers = {
        "x-api-key":         api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type":      "application/json",
    }
    payload = {
        "model":      "claude-sonnet-4.6",
        "max_tokens": 50,
        "messages":   [{"role":"user","content":"قل: اتصال ناجح"}],
    }

try:
    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    print(f"   HTTP Status: {resp.status_code}")

    if resp.status_code == 200:
        data = resp.json()
        if fmt == "openai":
            text = data["choices"]^0^["message"]["content"]
        else:
            text = data["content"]^0^["text"]
        print(f"   ✅ استجابة Claude: {text.strip()}")

    elif resp.status_code == 401:
        print("   ❌ خطأ 401 — مفتاح API خاطئ أو منتهي الصلاحية")
    elif resp.status_code == 402:
        print("   ❌ خطأ 402 — رصيد PPQ.AI غير كافٍ")
    elif resp.status_code == 403:
        print("   ❌ خطأ 403 — صلاحية مرفوضة")
        print(f"   تفاصيل: {resp.text[:200]}")
    elif resp.status_code == 404:
        print(f"   ❌ خطأ 404 — الـ endpoint غير صحيح: {url}")
    elif resp.status_code == 429:
        print("   ⚠️ خطأ 429 — تجاوزت حد الطلبات، انتظر دقيقة")
    else:
        print(f"   ❌ خطأ غير متوقع: {resp.text[:300]}")

except requests.exceptions.ConnectionError:
    print("   ❌ فشل الاتصال بالإنترنت أو بالخادم")
except requests.exceptions.Timeout:
    print("   ❌ انتهت مهلة الاتصال (30 ثانية)")
except Exception as e:
    print(f"   ❌ خطأ: {e}")

print("\n⏳ اختبار تيليغرام...")
if tg_token and tg_chat:
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{tg_token}/getMe",
            timeout=10
        )
        if r.ok:
            bot_name = r.json().get("result",{}).get("username","?")
            print(f"   ✅ بوت تيليغرام: @{bot_name}")
            r2 = requests.post(
                f"https://api.telegram.org/bot{tg_token}/sendMessage",
                data={"chat_id": tg_chat,
                      "text": "✅ اختبار الاتصال نجح!\n🤖 Claude API يعمل بشكل صحيح.",
                      "parse_mode": "HTML"},
                timeout=10
            )
            if r2.ok:
                print("   ✅ رسالة تجريبية أُرسلت إلى تيليغرام!")
            else:
                print(f"   ❌ فشل إرسال تيليغرام: {r2.text[:100]}")
        else:
            print(f"   ❌ توكن تيليغرام خاطئ: {r.text[:100]}")
    except Exception as e:
        print(f"   ❌ خطأ تيليغرام: {e}")
else:
    print("   ⚠️ TELEGRAM_TOKEN أو CHAT_ID غير موجود — تخطّي")

print("\n" + "=" * 55)
print("✅ انتهى التشخيص")
print("=" * 55)
