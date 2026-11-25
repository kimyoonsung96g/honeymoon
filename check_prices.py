#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
신혼여행 호텔 가격 자동 추적 (GitHub Actions에서 매일 자동 실행)
- 부킹닷컴 + 카약에서 4개 호텔의 조식 포함 최저가(원화, 숙박 전체)를 조회
- docs/prices.json 에 날짜별로 기록 (모바일 페이지가 이 파일을 읽음)
- 가격이 내려가면 휴대폰으로 푸시 알림 (ntfy 앱, NTFY_TOPIC 설정 시)
"""
import json, os, re, urllib.request
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "prices.json")
DEBUG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
DROP_ALERT_KRW = 30000  # 이 금액 이상 내려가면 알림

BQ = "&group_adults=2&no_rooms=1&selected_currency=KRW&nflt=mealplan%3D1"
KQ = "/2adults?fs=freebies=free-breakfast"
HOTELS = {
    "1": {"name": "Ohla Eixample", "dates": "9/6~9/10", "nights": 4,
          "booking": "https://www.booking.com/hotel/es/ohla-eixample.ko.html?checkin=2027-09-06&checkout=2027-09-10" + BQ,
          "kayak": "https://www.kayak.co.kr/hotels/Ohla-Eixample,Barcelona,Spain-c22567-h2502753-details/2027-09-06/2027-09-10" + KQ},
    "2": {"name": "Zoëtry Mallorca", "dates": "9/10~9/14", "nights": 4,
          "booking": "https://www.booking.com/hotel/es/hotel-sa-torre-mallorca.ko.html?checkin=2027-09-10&checkout=2027-09-14" + BQ,
          "kayak": "https://www.kayak.co.kr/hotels/Zoetry-Mallorca-Wellness-Spa,Llucmajor,Spain-h2495579-details/2027-09-10/2027-09-14" + KQ,
          # 올인클루시브 요금 (부킹닷컴 식사 조건 필터: 올 인클루시브)
          "booking_ai": "https://www.booking.com/hotel/es/hotel-sa-torre-mallorca.ko.html?checkin=2027-09-10&checkout=2027-09-14"
                        "&group_adults=2&no_rooms=1&selected_currency=KRW&nflt=mealplan%3D4"},
    "3": {"name": "Mercure Porto Centro", "dates": "9/14~9/17", "nights": 3,
          "booking": "https://www.booking.com/hotel/pt/mercure-batalha-porto.ko.html?checkin=2027-09-14&checkout=2027-09-17" + BQ,
          "kayak": "https://www.kayak.co.kr/hotels/Mercure-Porto-Centro-Santa-Catarina,Porto,Portugal-c22089-h74862-details/2027-09-14/2027-09-17" + KQ},
    "4": {"name": "TURIM Boulevard", "dates": "9/17~9/18", "nights": 1,
          "booking": "https://www.booking.com/hotel/pt/turim-boulevard.ko.html?checkin=2027-09-17&checkout=2027-09-18" + BQ,
          "kayak": "https://www.kayak.co.kr/hotels/TURIM-Boulevard-Hotel,Lisbon,Portugal-c21721-h4855678-details/2027-09-17/2027-09-18" + KQ},
}

# 무료 취소 가능 + 조식 포함 / 조식 없이 최저가 (부킹닷컴)
for _h in HOTELS.values():
    _h["booking_fc"] = _h["booking"].replace("nflt=mealplan%3D1", "nflt=mealplan%3D1%3Bfc%3D2")
    _h["booking_ro"] = _h["booking"].replace("&nflt=mealplan%3D1", "")

# 도시 간 항공 (구글 항공편, 1인 편도 최저가 x 2인) / 렌터카 (카약, 4일 총액)
def _gf(frm, to, date):
    return ("https://www.google.com/travel/flights?q=Flights%20from%20" + frm + "%20to%20" + to +
            "%20on%20" + date + "%20one%20way&curr=KRW&hl=ko&gl=KR")

EXTRAS = {
    "fl_bcn_pmi": {"name": "바르셀로나→마요르카 9/10", "kind": "flight", "url": _gf("BCN", "PMI", "2027-09-10")},
    "fl_pmi_opo": {"name": "마요르카→포르투 9/14", "kind": "flight", "url": _gf("PMI", "OPO", "2027-09-14")},
    "fl_lis_bcn": {"name": "리스본→바르셀로나 9/18", "kind": "flight", "url": _gf("LIS", "BCN", "2027-09-18")},
    "car_small": {"name": "마요르카 렌터카 최저가 (4일)", "kind": "car",
                  "url": "https://www.kayak.co.kr/cars/PMI/2027-09-10-12h/2027-09-14-12h?sort=price_a"},
    "car_suv": {"name": "마요르카 렌터카 SUV (4일)", "kind": "car",
                "url": "https://www.kayak.co.kr/cars/PMI/2027-09-10-12h/2027-09-14-12h?sort=price_a&fs=carclass=suv"},
}
CAR_DAYS = 4

NO_ROOM = ["선택하신 날짜에 이용 가능한 객실이 없습니다", "예약 가능한 객실이 없습니다", "no availability"]
BOOKING_SEL = ['[data-testid="price-and-discounted-price"]', "span.prco-valign-middle-helper",
               ".bui-price-display__value", ".hprt-price-price"]
KAYAK_BLOCK = ["로봇", "robot", "captcha", "보안 확인", "Please confirm", "unusual traffic"]
WON = re.compile(r"(?:₩\s*([\d,]+)|([\d,]{5,})\s*원)")


def won_values(text, lo, hi):
    out = []
    for m in WON.finditer(text or ""):
        v = int((m.group(1) or m.group(2)).replace(",", ""))
        if lo <= v <= hi:
            out.append(v)
    return out


def fetch_booking(page, h):
    page.goto(h["booking"], wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(6000)
    body = page.inner_text("body")
    if any(k in body for k in NO_ROOM):
        return None, "예약 미오픈 또는 매진"
    prices = []
    for sel in BOOKING_SEL:
        for el in page.query_selector_all(sel):
            prices += won_values(el.inner_text(), 50000, 20000000)
    if not prices:
        prices = won_values(body, 100000, 20000000)
    return (min(prices), None) if prices else (None, "가격 추출 실패 (사이트 차단 가능)")


AI_WORDS = ["올 인클루시브", "올인클루시브", "All-Inclusive", "All inclusive", "All-inclusive"]


def fetch_booking_ai(page, h):
    """객실 표에서 '올 인클루시브' 조건이 적힌 줄의 가격만 골라 최저가를 반환"""
    page.goto(h["booking_ai"], wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(6000)
    prices = []
    for row in page.query_selector_all("#hprt-table tr, table.hprt-table tr"):
        t = row.inner_text() or ""
        if any(w.lower() in t.lower() for w in AI_WORDS):
            prices += won_values(t, 100000, 30000000)
    if not prices:
        return None, "올인클루시브 요금이 없거나 추출 실패"
    return min(prices), None


def fetch_booking_url(page, url):
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(6000)
    body = page.inner_text("body")
    if any(k in body for k in NO_ROOM):
        return None, "예약 미오픈 또는 해당 조건 객실 없음"
    prices = []
    for sel in BOOKING_SEL:
        for el in page.query_selector_all(sel):
            prices += won_values(el.inner_text(), 50000, 20000000)
    if not prices:
        prices = won_values(body, 100000, 20000000)
    return (min(prices), None) if prices else (None, "가격 추출 실패 (사이트 차단 가능)")


def fetch_flight(page, url):
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(12000)
    body = page.inner_text("body")
    vals = won_values(body, 10000, 3000000)
    if not vals:
        return None, "아직 판매 전이거나 가격 추출 실패"
    return min(vals) * 2, None  # 1인 요금 x 2인 (수하물 별도)


def fetch_car(page, url, prev_total):
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(15000)
    body = page.inner_text("body")
    if any(k.lower() in body.lower() for k in KAYAK_BLOCK):
        return None, "카약 접속 차단"
    vals = won_values(body, 10000, 5000000)
    if not vals:
        return None, "아직 예약 전이거나 가격 추출 실패"
    v = min(vals)
    # 카약이 1일 요금을 보여주는 경우 4일 총액으로 환산
    # (지난 기록이 있으면 그 값에 더 가까운 해석을 사용, 없으면 6만 원 미만은 1일 요금으로 봄)
    if prev_total:
        total = min((v, v * CAR_DAYS), key=lambda x: abs(x - prev_total))
    else:
        total = v * CAR_DAYS if v < 60000 else v
    return total, None


KAYAK_PROVIDERS = ["Booking.com", "부킹닷컴", "Agoda", "아고다", "Hotels.com", "호텔스닷컴", "Expedia", "익스피디아",
                   "Trip.com", "트립닷컴", "Priceline", "Vio.com", "Super.com", "Prestigia", "Destinia", "공식"]
KAYAK_DEAL = ["특가 보기", "딜 보기", "예약하기", "View Deal", "View deal", "보기"]

# 페이지에서 '예약 사이트 이름 + 가격 + 특가 보기 버튼'이 함께 있는 작은 덩어리만 골라냄
# (비슷한 숙소, 광고 영역의 가격은 제외하기 위함)
KAYAK_JS = r"""
(args) => {
  const [providers, deals] = args;
  const out = [];
  for (const el of document.querySelectorAll('div,li,a,section')) {
    const t = (el.innerText || '').trim();
    if (!t || t.length > 220 || !/₩|원/.test(t)) continue;
    const hasProv = providers.some(p => t.includes(p)) ||
      [...el.querySelectorAll('img[alt]')].some(i => providers.some(p => (i.alt||'').includes(p)));
    const hasDeal = deals.some(d => t.includes(d));
    if (hasProv && hasDeal) out.push(t.replace(/\s+/g, ' '));
  }
  return out;
}
"""


def fetch_kayak(page, h, booking_total, hid):
    page.goto(h["kayak"], wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(15000)  # 카약은 여러 사이트 가격을 천천히 불러옴
    body = page.inner_text("body")
    # 문제 확인용으로 카약 화면 글자를 저장 (debug 폴더)
    try:
        os.makedirs(DEBUG_DIR, exist_ok=True)
        with open(os.path.join(DEBUG_DIR, f"kayak_{hid}.txt"), "w", encoding="utf-8") as f:
            f.write(body[:15000])
    except Exception:
        pass
    if any(k.lower() in body.lower() for k in KAYAK_BLOCK):
        return None, "카약 접속 차단"
    blocks = page.evaluate(KAYAK_JS, [KAYAK_PROVIDERS, KAYAK_DEAL])
    vals = []
    for t in blocks:
        vals += won_values(t, 30000, 20000000)
    if not vals:
        return None, "예약 사이트별 가격을 찾지 못함"
    v = min(vals)
    per_night_total, as_total = v * h["nights"], v
    if booking_total:
        total = min((per_night_total, as_total), key=lambda x: abs(x - booking_total))
        if not (0.6 * booking_total <= total <= 1.4 * booking_total):
            return None, f"부킹닷컴과 차이가 커서 제외 (카약에서 읽은 값 {v:,}원)"
    else:
        total = per_night_total
    return total, None


def record(rec, key, price, today):
    hist = rec.setdefault(key, [])
    prev = hist[-1]["krw"] if hist else None
    if hist and hist[-1]["date"] == today:
        hist[-1]["krw"] = price
    else:
        hist.append({"date": today, "krw": price})
    rec[key] = hist[-120:]
    return prev


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
            rec = data["hotels"].setdefault(hid, {})
            rec["name"], rec["dates"] = h["name"], h["dates"]
            rec["last_check"] = now.strftime("%Y-%m-%d %H:%M")

            # 부킹닷컴 (기존 'history' 키 유지)
            try:
                b, berr = fetch_booking(page, h)
            except Exception as e:
                b, berr = None, f"조회 오류: {str(e)[:80]}"
            rec["last_error"] = berr
            if b is not None:
                prev = record(rec, "history", b, today)
                if prev is not None and prev - b >= DROP_ALERT_KRW:
                    alerts.append(f"[Booking] {h['name']} {prev:,} -> {b:,} KRW")

            # 카약
            try:
                k, kerr = fetch_kayak(page, h, b, hid)
            except Exception as e:
                k, kerr = None, f"조회 오류: {str(e)[:80]}"
            rec["kayak_error"] = kerr
            if k is not None:
                prev = record(rec, "kayak_history", k, today)
                if prev is not None and prev - k >= DROP_ALERT_KRW:
                    alerts.append(f"[KAYAK] {h['name']} {prev:,} -> {k:,} KRW")

            # 올인클루시브 (해당 호텔만)
            if "booking_ai" in h:
                try:
                    ai, aerr = fetch_booking_ai(page, h)
                except Exception as e:
                    ai, aerr = None, f"조회 오류: {str(e)[:80]}"
                rec["ai_error"] = aerr
                if ai is not None:
                    prev = record(rec, "ai_history", ai, today)
                    if prev is not None and prev - ai >= DROP_ALERT_KRW:
                        alerts.append(f"[All-inclusive] {h['name']} {prev:,} -> {ai:,} KRW")
                print(h["name"], "all-inclusive:", ai, aerr or "")

            # 무료 취소 가능(조식 포함) / 조식 없이 최저가
            for key, ukey in (("fc", "booking_fc"), ("ro", "booking_ro")):
                try:
                    v, verr = fetch_booking_url(page, h[ukey])
                except Exception as e:
                    v, verr = None, f"조회 오류: {str(e)[:80]}"
                rec[key + "_error"] = verr
                if v is not None:
                    record(rec, key + "_history", v, today)
                print(h["name"], key, v, verr or "")

            print(h["name"], "booking:", b, berr or "", "| kayak:", k, kerr or "")
        # 항공, 렌터카
        ex = data.setdefault("extras", {})
        for key, e in EXTRAS.items():
            rec = ex.setdefault(key, {})
            rec["name"] = e["name"]
            rec["last_check"] = now.strftime("%Y-%m-%d %H:%M")
            prev_hist = rec.get("history") or []
            try:
                if e["kind"] == "flight":
                    v, verr = fetch_flight(page, e["url"])
                else:
                    v, verr = fetch_car(page, e["url"], prev_hist[-1]["krw"] if prev_hist else None)
            except Exception as err:
                v, verr = None, f"조회 오류: {str(err)[:80]}"
            rec["error"] = verr
            if v is not None:
                prev = record(rec, "history", v, today)
                if prev is not None and prev - v >= DROP_ALERT_KRW:
                    alerts.append(f"[{key}] {prev:,} -> {v:,} KRW")
            print(e["name"], v, verr or "")
        browser.close()

    data["updated"] = now.strftime("%Y-%m-%d %H:%M")
    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    if alerts:
        notify("Honeymoon hotel price drop", "\n".join(alerts))


if __name__ == "__main__":
    main()
