#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
신혼여행 가격 자동 추적 (GitHub Actions에서 매일 자동 실행)

호텔(부킹닷컴): 호텔 페이지의 '객실 표'를 한 줄씩 읽어서 조건별 최저가를 구함
  - 조식 포함 / 조식 포함 + 무료 취소 / 조식 미포함 / 올인클루시브
  (부킹닷컴 주소의 필터는 호텔 페이지에서 적용되지 않아서, 표의 조건 문구로 직접 구분)
호텔(카약): 예약 사이트별 가격 목록만 읽음
항공(구글 항공편): 검색 결과 목록의 편도 최저가 x 2인 (수하물 별도)
렌터카(카약): 마요르카 4일 최저가

결과: docs/prices.json / 확인용 화면 글자: debug/ 폴더
가격이 내려가면 휴대폰 푸시 알림 (ntfy 앱, NTFY_TOPIC 설정 시)
"""
import json, os, re, urllib.request
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
BASE = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(BASE, "docs", "prices.json")
DEBUG_DIR = os.path.join(BASE, "debug")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
DROP_ALERT_KRW = 30000  # 이 금액 이상 내려가면 알림

BQ = "&group_adults=2&no_rooms=1&selected_currency=KRW"
KQ = "/2adults?fs=freebies=free-breakfast"
HOTELS = {
    "1": {"name": "Ohla Eixample", "dates": "9/6~9/10", "nights": 4,
          "booking": "https://www.booking.com/hotel/es/ohla-eixample.ko.html?checkin=2027-09-06&checkout=2027-09-10" + BQ,
          "kayak": "https://www.kayak.co.kr/hotels/Ohla-Eixample,Barcelona,Spain-c22567-h2502753-details/2027-09-06/2027-09-10" + KQ},
    "2": {"name": "Zoëtry Mallorca", "dates": "9/10~9/14", "nights": 4,
          "booking": "https://www.booking.com/hotel/es/hotel-sa-torre-mallorca.ko.html?checkin=2027-09-10&checkout=2027-09-14" + BQ,
          "kayak": "https://www.kayak.co.kr/hotels/Zoetry-Mallorca-Wellness-Spa,Llucmajor,Spain-h2495579-details/2027-09-10/2027-09-14" + KQ,
          "all_inclusive": True},
    "3": {"name": "Mercure Porto Centro", "dates": "9/14~9/17", "nights": 3,
          "booking": "https://www.booking.com/hotel/pt/mercure-batalha-porto.ko.html?checkin=2027-09-14&checkout=2027-09-17" + BQ,
          "kayak": "https://www.kayak.co.kr/hotels/Mercure-Porto-Centro-Santa-Catarina,Porto,Portugal-c22089-h74862-details/2027-09-14/2027-09-17" + KQ},
    "4": {"name": "TURIM Boulevard", "dates": "9/17~9/18", "nights": 1,
          "booking": "https://www.booking.com/hotel/pt/turim-boulevard.ko.html?checkin=2027-09-17&checkout=2027-09-18" + BQ,
          "kayak": "https://www.kayak.co.kr/hotels/TURIM-Boulevard-Hotel,Lisbon,Portugal-c21721-h4855678-details/2027-09-17/2027-09-18" + KQ},
}


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

WON = re.compile(r"(?:₩\s*([\d,]+)|([\d,]{5,})\s*원)")
NO_ROOM = ["선택하신 날짜에 이용 가능한 객실이 없습니다", "예약 가능한 객실이 없습니다", "no availability"]
BLOCK = ["로봇", "robot", "captcha", "보안 확인", "Please confirm", "unusual traffic"]
BREAKFAST = ["조식 포함", "조식이 포함", "breakfast included", "훌륭한 조식 포함"]
FREE_CANCEL = ["무료 취소", "free cancellation"]
ALL_INC = ["올 인클루시브", "올인클루시브", "all-inclusive", "all inclusive"]
PRICE_SEL = '[data-testid="price-and-discounted-price"], .prco-valign-middle-helper, .bui-price-display__value, .hprt-price-price'


def won_values(text, lo, hi):
    out = []
    for m in WON.finditer(text or ""):
        v = int((m.group(1) or m.group(2)).replace(",", ""))
        if lo <= v <= hi:
            out.append(v)
    return out


def has(text, words):
    t = (text or "").lower()
    return any(w.lower() in t for w in words)


def save_debug(name, text):
    try:
        os.makedirs(DEBUG_DIR, exist_ok=True)
        with open(os.path.join(DEBUG_DIR, name), "w", encoding="utf-8") as f:
            f.write(text[:20000])
    except Exception:
        pass


# ---------------- 부킹닷컴: 객실 표 분석 ----------------
def fetch_booking_rows(page, h, hid):
    """객실 표의 각 줄을 (조건 문구, 숙박 전체 가격)으로 반환"""
    page.goto(h["booking"], wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(7000)
    body = page.inner_text("body")
    if any(k in body for k in NO_ROOM):
        save_debug(f"booking_{hid}.txt", body)
        return None, "예약 미오픈 또는 매진"
    rows = []
    for tr in page.query_selector_all("#hprt-table tbody tr, table.hprt-table tbody tr"):
        t = (tr.inner_text() or "").strip()
        pe = tr.query_selector(PRICE_SEL)
        if not pe:
            continue
        # 가격 칸만 읽음 (세금 줄 제외). 정가와 할인가가 같이 있으면 작은 값이 실제 가격
        vals = won_values(pe.inner_text(), 50000, 40000000)
        if vals:
            rows.append((re.sub(r"\s+", " ", t), min(vals)))
    fixed = rows
    save_debug(f"booking_{hid}.txt", "\n\n".join(f"[{p:,}] {t}" for t, p in fixed) or body)
    if not fixed:
        return None, "객실 표를 찾지 못함 (사이트 차단 가능)"
    return fixed, None


def analyze_rows(rows):
    def mn(cond):
        v = [p for t, p in rows if cond(t)]
        return min(v) if v else None
    return {
        "breakfast": mn(lambda t: has(t, BREAKFAST) and not has(t, ALL_INC)),
        "fc": mn(lambda t: has(t, BREAKFAST) and has(t, FREE_CANCEL) and not has(t, ALL_INC)),
        "ro": mn(lambda t: not has(t, BREAKFAST) and not has(t, ALL_INC)),
        "ai": mn(lambda t: has(t, ALL_INC)),
    }


# ---------------- 카약 호텔 ----------------
KAYAK_PROVIDERS = ["Booking.com", "부킹닷컴", "Agoda", "아고다", "Hotels.com", "호텔스닷컴", "Expedia", "익스피디아",
                   "Trip.com", "트립닷컴", "Priceline", "Vio.com", "Super.com", "Prestigia", "Destinia", "공식"]
KAYAK_DEAL = ["특가 보기", "딜 보기", "예약하기", "View Deal", "View deal", "보기"]
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
    page.wait_for_timeout(15000)
    body = page.inner_text("body")
    blocks = page.evaluate(KAYAK_JS, [KAYAK_PROVIDERS, KAYAK_DEAL])
    save_debug(f"kayak_{hid}.txt", "=== 사이트별 가격으로 읽은 부분 ===\n" + "\n".join(blocks) +
               "\n\n=== 화면 전체 ===\n" + body)
    if has(body, BLOCK):
        return None, "카약 접속 차단"
    vals = []
    for t in blocks:
        vals += won_values(t, 30000, 20000000)
    if not vals:
        return None, "예약 사이트별 가격을 찾지 못함"
    v = min(vals)
    if booking_total:
        total = min((v * h["nights"], v), key=lambda x: abs(x - booking_total))
        if not (0.6 * booking_total <= total <= 1.4 * booking_total):
            return None, f"부킹닷컴과 차이가 커서 제외 (카약에서 읽은 값 {v:,}원)"
    else:
        total = v * h["nights"]
    return total, None


# ---------------- 구글 항공편 ----------------
FLIGHT_JS = r"""
() => [...document.querySelectorAll('li')]
  .map(e => (e.innerText || '').replace(/\s+/g, ' ').trim())
  .filter(t => t.length < 400 && /₩/.test(t) && /(시간|분)/.test(t) && /(직항|경유)/.test(t))
"""


def fetch_flight(page, url, key):
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(12000)
    items = page.evaluate(FLIGHT_JS)
    save_debug(f"flight_{key}.txt", "=== 항공편 목록으로 읽은 부분 ===\n" + "\n".join(items) +
               "\n\n=== 화면 전체 ===\n" + page.inner_text("body"))
    vals = []
    for t in items:
        vals += won_values(t, 10000, 3000000)
    if not vals:
        return None, "아직 판매 전이거나 항공편 목록을 찾지 못함"
    return min(vals) * 2, None  # 1인 요금 x 2인


# ---------------- 카약 렌터카 ----------------
def fetch_car(page, url, key, prev_total):
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(15000)
    body = page.inner_text("body")
    save_debug(f"car_{key}.txt", body)
    if has(body, BLOCK):
        return None, "카약 접속 차단"
    vals = won_values(body, 10000, 5000000)
    if not vals:
        return None, "아직 예약 전이거나 가격 추출 실패"
    v = min(vals)
    if prev_total:
        total = min((v, v * CAR_DAYS), key=lambda x: abs(x - prev_total))
    else:
        total = v * CAR_DAYS if v < 60000 else v
    return total, None


# ---------------- 기록, 알림 ----------------
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

    def put(rec, key, val, err_key, err, label):
        rec[err_key] = err
        if val is not None:
            prev = record(rec, key, val, today)
            if prev is not None and prev - val >= DROP_ALERT_KRW:
                alerts.append(f"[{label}] {prev:,} -> {val:,} KRW")

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
            # 예전 방식(필터가 적용되지 않던) 기록은 정확하지 않아 한 번 비움
            if rec.get("method") != "rows-v1":
                for k in ("history", "fc_history", "ro_history", "ai_history", "kayak_history"):
                    rec[k] = []
                rec["method"] = "rows-v1"

            try:
                rows, err = fetch_booking_rows(page, h, hid)
            except Exception as e:
                rows, err = None, f"조회 오류: {str(e)[:80]}"
            r = analyze_rows(rows) if rows else {"breakfast": None, "fc": None, "ro": None, "ai": None}
            nb = "조식 포함 요금이 표에 없음" if rows and r["breakfast"] is None else err
            put(rec, "history", r["breakfast"], "last_error", nb, h["name"])
            put(rec, "fc_history", r["fc"], "fc_error", ("조식 포함 무료 취소 요금이 없음" if rows and r["fc"] is None else err), h["name"] + " 무료취소")
            put(rec, "ro_history", r["ro"], "ro_error", ("조식 미포함 요금이 없음" if rows and r["ro"] is None else err), h["name"] + " 조식없음")
            if h.get("all_inclusive"):
                put(rec, "ai_history", r["ai"], "ai_error", ("올인클루시브 요금이 표에 없음" if rows and r["ai"] is None else err), h["name"] + " 올인클루시브")

            try:
                k, kerr = fetch_kayak(page, h, r["breakfast"], hid)
            except Exception as e:
                k, kerr = None, f"조회 오류: {str(e)[:80]}"
            put(rec, "kayak_history", k, "kayak_error", kerr, "KAYAK " + h["name"])
            print(h["name"], r, "| kayak:", k, kerr or "")

        ex = data.setdefault("extras", {})
        for key, e in EXTRAS.items():
            rec = ex.setdefault(key, {})
            rec["name"] = e["name"]
            rec["last_check"] = now.strftime("%Y-%m-%d %H:%M")
            if rec.get("method") != "list-v1":
                rec["history"] = []
                rec["method"] = "list-v1"
            prev_hist = rec.get("history") or []
            try:
                if e["kind"] == "flight":
                    v, verr = fetch_flight(page, e["url"], key)
                else:
                    v, verr = fetch_car(page, e["url"], key, prev_hist[-1]["krw"] if prev_hist else None)
            except Exception as err:
                v, verr = None, f"조회 오류: {str(err)[:80]}"
            put(rec, "history", v, "error", verr, key)
            print(e["name"], v, verr or "")
        browser.close()

    data["updated"] = now.strftime("%Y-%m-%d %H:%M")
    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    if alerts:
        notify("Honeymoon price drop", "\n".join(alerts))


if __name__ == "__main__":
    main()
