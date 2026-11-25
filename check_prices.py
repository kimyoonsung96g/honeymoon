#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
신혼여행 가격 자동 추적 (GitHub Actions에서 매일 자동 실행)

호텔(부킹닷컴): 호텔 페이지의 '객실 표'를 한 줄씩 읽어서 조건별 최저가를 구함
  - 조식 포함 / 조식 포함 + 무료 취소 / 조식 미포함 / 올인클루시브
  (부킹닷컴 주소의 필터는 호텔 페이지에서 적용되지 않아서, 표의 조건 문구로 직접 구분)
호텔(카약): 객실 요금 목록에서 견적 객실 + 조건(조식 포함 / 올인클루시브) 줄만 읽음 (세금·수수료 포함 총액)
항공(구글 항공편): 검색 결과 목록의 편도 최저가 x 2인 (수하물 별도)
렌터카(카약): 마요르카 4일 최저가 (자동 변속기, 광고 제외)

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
KQ_AI = "/2adults?fs=freebies=all-inclusive"
HOTELS = {
    "1": {"name": "Ohla Eixample", "dates": "9/6~9/10", "nights": 4, "room": ["Essential", "에센셜", "=더블룸"],
          "k_room": (["더블룸", "Double Room"], ["디럭스", "Deluxe", "수페리어", "Superior", "스위트", "Suite", "트윈", "Twin"]),
          "booking": "https://www.booking.com/hotel/es/ohla-eixample.ko.html?checkin=2027-09-06&checkout=2027-09-10" + BQ,
          "kayak": "https://www.kayak.co.kr/hotels/Ohla-Eixample,Barcelona,Spain-c22567-h2502753-details/2027-09-06/2027-09-10" + KQ},
    "2": {"name": "Zoëtry Mallorca", "dates": "9/10~9/14", "nights": 4, "room": ["=포넨트 더블룸", "Ponent Double", "Double Ponent"],
          "k_room": (["Ponent", "포넨트"], ["스위트", "Suite", "주니어", "Junior", "디럭스", "Deluxe"]),
          "booking": "https://www.booking.com/hotel/es/hotel-sa-torre-mallorca.ko.html?checkin=2027-09-10&checkout=2027-09-14" + BQ,
          "kayak": "https://www.kayak.co.kr/hotels/Zoetry-Mallorca-Wellness-Spa,Llucmajor,Spain-h2495579-details/2027-09-10/2027-09-14" + KQ,
          "all_inclusive": True},
    "3": {"name": "Mercure Porto Centro", "dates": "9/14~9/17", "nights": 3, "room": ["Standard Double", "스탠다드 더블"],
          "k_room": (["Superior Double", "슈페리어 더블", "슈피리어룸, 더블", "슈피리어 더블"], ["Twin", "트윈", "Family", "패밀리", "Suite", "스위트"]),
          "booking": "https://www.booking.com/hotel/pt/mercure-batalha-porto.ko.html?checkin=2027-09-14&checkout=2027-09-17" + BQ,
          "kayak": "https://www.kayak.co.kr/hotels/Mercure-Porto-Centro-Santa-Catarina,Porto,Portugal-c22089-h74862-details/2027-09-14/2027-09-17" + KQ},
    "4": {"name": "TURIM Boulevard", "dates": "9/17~9/18", "nights": 1, "room": ["=수페리어 더블룸", "=Superior Double Room"],
          "k_room": (["슈피리어 더블룸", "슈페리어 더블룸", "수페리어 더블룸", "Superior Double"], ["Twin", "트윈"]),
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
    "car_small": {"name": "마요르카 렌터카 자동 최저가 (4일)", "kind": "car",
                  "url": "https://www.kayak.co.kr/cars/PMI/2027-09-10-12h/2027-09-14-12h?sort=price_a"},
    "car_suv": {"name": "마요르카 렌터카 자동 SUV (4일)", "kind": "car",
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
    rows, room = [], ""
    for tr in page.query_selector_all("#hprt-table tbody tr, table.hprt-table tbody tr"):
        t = (tr.inner_text() or "").strip()
        pe = tr.query_selector(PRICE_SEL)
        if not pe:
            continue
        # 가격 칸만 읽음 (세금 줄 제외). 정가와 할인가가 같이 있으면 작은 값이 실제 가격
        vals = won_values(pe.inner_text(), 50000, 40000000)
        if vals:
            price = min(vals)
            # '불포함 사항: 10 % 부가가치세(VAT)'처럼 VAT가 빠진 가격이면 VAT를 더해 실제 결제액으로 맞춤
            vat = re.search(r"불포함[^%]{0,40}?(\d+(?:\.\d+)?)\s*%\s*부가가치세", t)
            if vat:
                price = round(price * (1 + float(vat.group(1)) / 100))
            t1 = re.sub(r"\s+", " ", t)
            # 객실명은 객실 종류의 첫 줄에만 나오고, 아래 줄은 같은 객실의 다른 요금
            if "제곱미터" in t1:
                room = re.sub(r"\s*\d+(\.\d+)?$", "", t1.split(" 제곱미터")[0])
                room = re.sub(r"\s*남은 객실 \d+개", "", room).strip()
            # 2인 여행이므로 '1인 전용' 요금(최대 투숙 인원 1명)은 제외
            if "1인 전용" in t1 or re.search(r"최대 투숙 인원:\s*1(\s|$)", t1):
                continue
            rows.append((room, t1, price))
    fixed = rows
    save_debug(f"booking_{hid}.txt", "\n\n".join(f"[{p:,}] <{r}> {t}" for r, t, p in fixed) or body)
    if not fixed:
        return None, "객실 표를 찾지 못함 (사이트 차단 가능)"
    return fixed, None


def analyze_rows(rows, room_words):
    """견적서 객실이 표에 있으면 그 객실 요금만, 없으면 전체 최저가"""
    # 키워드를 순서대로 시도: '='로 시작하면 객실명이 정확히 같아야 함, 아니면 포함
    matched = []
    for w in room_words:
        if w.startswith("="):
            matched = [r for r in rows if r[0].lower() == w[1:].lower()]
        else:
            matched = [r for r in rows if w.lower() in r[0].lower()]
        if matched:
            break
    use = matched or rows
    room_used = matched[0][0] if matched else None

    def mn(cond):
        v = [p for r, t, p in use if cond(t)]
        return min(v) if v else None
    return {
        "breakfast": mn(lambda t: has(t, BREAKFAST) and not has(t, ALL_INC)),
        "fc": mn(lambda t: has(t, BREAKFAST) and has(t, FREE_CANCEL) and not has(t, ALL_INC)),
        "ro": mn(lambda t: not has(t, BREAKFAST) and not has(t, ALL_INC) and "석식" not in t),
        "ai": mn(lambda t: has(t, ALL_INC)),
        "ai_fc": mn(lambda t: has(t, ALL_INC) and has(t, FREE_CANCEL)),
    }, room_used, sorted({r for r, _, _ in rows if r})


# ---------------- 카약 호텔 ----------------
# 카약 호텔 페이지의 객실 요금 목록: '객실명 / 조건 / N박 총액 X원(세금·수수료 포함)' 형식을 줄 단위로 읽음
KAYAK_ROW = re.compile(r"([^\n]+)\n([^\n]*)\n(\d+)\u200b?박 총액 ([\d,]+)원")


def kayak_rows(page, url, hid, tag):
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(15000)
    body = page.inner_text("body")
    rows = [(f"{a} {b}".strip(), int(t.replace(",", ""))) for a, b, n, t in KAYAK_ROW.findall(body)]
    save_debug(f"kayak_{hid}{tag}.txt", "=== 읽은 객실 요금 ===\n" +
               "\n".join(f"[{p:,}] {t}" for t, p in rows) + "\n\n=== 화면 전체 ===\n" + body)
    if has(body, BLOCK):
        return None, "카약 접속 차단"
    if not rows:
        return None, "객실 요금 목록을 찾지 못함 (예약 미오픈 또는 차단)"
    return rows, None


def kayak_pick(rows, h, words, ref, also=None):
    """견적 객실 + 조건(words)에 맞는 줄의 최저가. 부킹닷컴(ref)과 40% 넘게 차이 나면 제외"""
    inc, exc = h["k_room"]
    cand = [p for t, p in rows
            if any(w.lower() in t.lower() for w in inc) and not any(x.lower() in t.lower() for x in exc)
            and has(t, words) and (also is None or has(t, also))]
    if not cand:
        return None, "견적 객실의 해당 조건 요금이 카약에 없음"
    v = min(cand)
    if ref and not (0.6 * ref <= v <= 1.4 * ref):
        return None, f"부킹닷컴과 차이가 커서 제외 (카약 {v:,}원)"
    return v, None


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
# 견적서 조건(자동 변속기)에 맞춰 '수동' 차량은 제외. 광고 칸도 제외. 가격은 카약이 표시한 4일 총액.
def fetch_car(page, url, key, prev_total):
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(15000)
    body = page.inner_text("body")
    save_debug(f"car_{key}.txt", body)
    if has(body, BLOCK):
        return None, "카약 접속 차단"
    want_suv = key == "car_suv"
    vals = []
    for blk in body.split("상세 정보 보기")[1:]:
        if "광고" in blk.split("상품 확인")[0][-40:]:
            continue
        if "수동" in blk:
            continue
        if want_suv and "SUV" not in blk:
            continue
        v = won_values(blk, 10000, 5000000)
        if v:
            vals.append(v[0])  # 칸의 첫 가격이 할인 적용된 총액
    if not vals:
        return None, "자동 변속기" + (" SUV" if want_suv else "") + " 차량을 찾지 못함"
    return min(vals), None


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
            # 계산 방식이 바뀐 예전 기록(VAT 미포함 등)은 정확하지 않아 한 번 비움
            if rec.get("method") != "rows-v5":
                for k in ("history", "fc_history", "ro_history", "ai_history", "ai_fc_history", "kayak_history", "kayak_fc_history", "kayak_ai_history"):
                    rec[k] = []
                rec["method"] = "rows-v5"

            try:
                rows, err = fetch_booking_rows(page, h, hid)
            except Exception as e:
                rows, err = None, f"조회 오류: {str(e)[:80]}"
            if rows:
                r, room_used, rooms = analyze_rows(rows, h["room"])
                rec["room_used"] = room_used or f"견적 객실을 찾지 못해 전체 최저가 사용 (표의 객실: {', '.join(rooms)[:150]})"
            else:
                r = {"breakfast": None, "fc": None, "ro": None, "ai": None, "ai_fc": None}
            nb = "조식 포함 요금이 표에 없음" if rows and r["breakfast"] is None else err
            put(rec, "history", r["breakfast"], "last_error", nb, h["name"])
            put(rec, "fc_history", r["fc"], "fc_error", ("조식 포함 무료 취소 요금이 없음" if rows and r["fc"] is None else err), h["name"] + " 무료취소")
            put(rec, "ro_history", r["ro"], "ro_error", ("조식 미포함 요금이 없음" if rows and r["ro"] is None else err), h["name"] + " 조식없음")
            if h.get("all_inclusive"):
                put(rec, "ai_history", r["ai"], "ai_error", ("올인클루시브 요금이 표에 없음" if rows and r["ai"] is None else err), h["name"] + " 올인클루시브")
                put(rec, "ai_fc_history", r["ai_fc"], "ai_fc_error", ("올인클루시브 무료 취소 요금이 없음" if rows and r["ai_fc"] is None else err), h["name"] + " 올인클루시브 무료취소")

            try:
                krows, kerr = kayak_rows(page, h["kayak"], hid, "")
                k, kerr = kayak_pick(krows, h, BREAKFAST, r["breakfast"]) if krows else (None, kerr)
            except Exception as e:
                k, kerr = None, f"조회 오류: {str(e)[:80]}"
            put(rec, "kayak_history", k, "kayak_error", kerr, "KAYAK " + h["name"])
            kf, kferr = kayak_pick(krows, h, BREAKFAST, r["fc"], FREE_CANCEL) if krows else (None, kerr)
            put(rec, "kayak_fc_history", kf, "kayak_fc_error", kferr, "KAYAK " + h["name"] + " 무료취소")
            if h.get("all_inclusive"):
                try:
                    arows, aerr = kayak_rows(page, h["kayak"].replace(KQ, KQ_AI), hid, "_ai")
                    ka, aerr = kayak_pick(arows, h, ALL_INC, r["ai"]) if arows else (None, aerr)
                except Exception as e:
                    ka, aerr = None, f"조회 오류: {str(e)[:80]}"
                put(rec, "kayak_ai_history", ka, "kayak_ai_error", aerr, "KAYAK " + h["name"] + " 올인클루시브")
            print(h["name"], r, "| kayak:", k, kerr or "")

        ex = data.setdefault("extras", {})
        for key, e in EXTRAS.items():
            rec = ex.setdefault(key, {})
            rec["name"] = e["name"]
            rec["last_check"] = now.strftime("%Y-%m-%d %H:%M")
            if rec.get("method") != "list-v2":
                rec["history"] = []
                rec["method"] = "list-v2"
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
