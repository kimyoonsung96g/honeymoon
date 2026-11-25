#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
신혼여행 호텔 가격 자동 추적 (GitHub Actions에서 매일 자동 실행)
- 부킹닷컴에서 4개 호텔의 조식 포함 최저가(원화, 숙박 전체)를 조회
- docs/prices.json 에 날짜별로 기록 (모바일 페이지가 이 파일을 읽음)
- 가격이 내려가면 휴대폰으로 푸시 알림 (ntfy 앱, NTFY_TOPIC 설정 시)
"""
import json, os, re, urllib.request
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "prices.json")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
DROP_ALERT_KRW = 30000  # 이 금액 이상 내려가면 알림

Q = "&group_adults=2&no_rooms=1&selected_currency=KRW&nflt=mealplan%3D1"
HOTELS = {
    "1": {"name": "Ohla Eixample", "dates": "9/6~9/10",
          "url": "https://www.booking.com/hotel/es/ohla-eixample.ko.html?checkin=2027-09-06&checkout=2027-09-10" + Q},
    "2": {"name": "Zoëtry Mallorca", "dates": "9/10~9/14",
          "url": "https://www.booking.com/hotel/es/hotel-sa-torre-mallorca.ko.html?checkin=2027-09-10&checkout=2027-09-14" + Q},
    "3": {"name": "Mercure Porto Centro", "dates": "9/14~9/17",
          "url": "https://www.booking.com/hotel/pt/mercure-porto-centro.ko.html?checkin=2027-09-14&checkout=2027-09-17" + Q},
    "4": {"name": "TURIM Boulevard", "dates": "9/17~9/18",
          "url": "https://www.booking.com/hotel/pt/turim-boulevard.ko.html?checkin=2027-09-17&checkout=2027-09-18" + Q},
}

NO_ROOM = ["선택하신 날짜에 이용 가능한 객실이 없습니다", "예약 가능한 객실이 없습니다", "no availability"]
SELECTORS = ['[data-testid="price-and-discounted-price"]', "span.prco-valign-middle-helper",
             ".bui-price-display__value", ".hprt-price-price"]


def fetch(page, hotel):
    page.goto(hotel["url"], wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(6000)
    body = page.inner_text("body")
    if any(k in body for k in NO_ROOM):
        return None, "예약 미오픈 또는 매진"
    prices = []
    for sel in SELECTORS:
        for el in page.query_selector_all(sel):
            m = re.search(r"₩\s*([\d,]+)", (el.inner_text() or ""))
            if m:
                v = int(m.group(1).replace(",", ""))
                if v >= 50000:
                    prices.append(v)
    if not prices:
        for m in re.finditer(r"₩\s*([\d,]+)", body):
            v = int(m.group(1).replace(",", ""))
            if 100000 <= v <= 15000000:
                prices.append(v)
    if not prices:
        return None, "가격 추출 실패 (사이트 차단 가능)"
    return min(prices), None


def notify(title, msg):
    if not NTFY_TOPIC:
        return
    try:
        req = urllib.request.Request(f"https://ntfy.sh/{NTFY_TOPIC}", data=msg.encode("utf-8"),
                                     headers={"Title": title, "Tags": "airplane"})
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        print("알림 실패:", e)


def main():
    from playwright.sync_api import sync_playwright
    data = {"updated": None, "hotels": {}}
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, encoding="utf-8") as f:
            data = json.load(f)
    now = datetime.now(KST)
    today = now.strftime("%Y-%m-%d")
    alerts = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(locale="ko-KR", viewport={"width": 1366, "height": 900},
                                  user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                             "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
        page = ctx.new_page()
        for hid, h in HOTELS.items():
            rec = data["hotels"].setdefault(hid, {"history": []})
            rec["name"], rec["dates"] = h["name"], h["dates"]
            try:
                price, err = fetch(page, h)
            except Exception as e:
                price, err = None, f"조회 오류: {str(e)[:80]}"
            rec["last_check"] = now.strftime("%Y-%m-%d %H:%M")
            rec["last_error"] = err
            print(h["name"], price, err or "")
            if price is None:
                continue
            hist = rec["history"]
            prev = hist[-1]["krw"] if hist else None
            if hist and hist[-1]["date"] == today:
                hist[-1]["krw"] = price
            else:
                hist.append({"date": today, "krw": price})
            rec["history"] = hist[-120:]
            if prev is not None and prev - price >= DROP_ALERT_KRW:
                alerts.append(f"{h['name']} {prev:,}원 → {price:,}원 ({prev - price:,}원 내림)")
        browser.close()

    data["updated"] = now.strftime("%Y-%m-%d %H:%M")
    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    if alerts:
        notify("Honeymoon hotel price drop", "\n".join(alerts))


if __name__ == "__main__":
    main()
