# -*- coding: utf-8 -*-
# ====== بوت توصيات فوركس (إرسال للتيليجرام) ======

import time
import requests

# ====== إعدادات تيليجرام ======
TOKEN = "8295831234:AAHgdvWal7E_5_hsjPmbPiIEra4LBDRjbgU"  # توكن البوت
CHAT_ID = "1820224574"  # الـ ID الخاص بك

# ====== دالة إرسال الرسائل ======
def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": message}
        requests.post(url, data=payload, timeout=10)
        print(f"تم إرسال الرسالة: {message}")
    except Exception as e:
        print(f"خطأ في الإرسال: {e}")

# ====== دالة جلب توصيات (تجريبية) ======
def get_signal():
    # مبدئيًا نخليها عشوائية للتجربة
    import random
    return random.choice(["شراء EUR/USD", "بيع GBP/USD", "شراء USD/JPY", "بيع GOLD"])

# ====== تشغيل مستمر ======
if __name__ == "__main__":
    send_telegram("🚀 تم تشغيل بوت توصيات الفوركس")
    while True:
        signal = get_signal()
        send_telegram(f"📊 توصية جديدة: {signal}")
        time.sleep(3600)  # كل ساعة توصية جديدة
