#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
신혼여행 가격 자동 추적 (GitHub Actions에서 매일 자동 실행)

실행할 때마다 공개 환율 API(frankfurter → open.er-api)에서 EUR→KRW 환율을 받아
prices.json의 eur_krw / eur_krw_date에 저장한다 (실패하면 저장값, 그다음 1475).

일정 1(9/6~9/18)과 일정 2(9/8~9/22), 일정 3(9/8~9/22 · 마요르카→세비야→포르투→바르셀로나)를 함께 조회한다.
일정 2·3은 같은 호텔·객실 기준 날짜만 바꾼 값이고, 같은 날짜(9/15~9/18 포르투 등)는 앞선 결과를 그대로 재사용해 중복 요청을 줄인다.

호텔(부킹닷컴): 호텔 페이지의 '객실 표'를 한 줄씩 읽어서 조건별 최저가를 구함
  - 조식 포함 / 조식 포함 + 무료 취소 / 조식 미포함 / 올인클루시브
  (부킹닷컴 주소의 필터는 호텔 페이지에서 적용되지 않아서, 표의 조건 문구로 직접 구분)
호텔(구글 호텔): 견적서와 같은 객실의 조식 포함 / 올인클루시브 표시 요금만 읽음 (카약은 자동 조회 차단으로 제외)
항공(구글 항공편): 검색 결과 목록의 편도 최저가 x 2인 (수하물 별도)
렌터카(카약): 마요르카 4일 최저가 (자동 변속기, 광고 제외)

결과: docs/prices.json / 확인용 화면 글자: debug/ 폴더
가격이 내려가면 휴대폰 푸시 알림 (ntfy 앱, NTFY_TOPIC 설정 시)
"""
import base64, json, os, re, sys, urllib.parse, urllib.request
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
    "1": {"name": "Ohla Eixample", "dates": "9/6~9/10", "nights": 4, "room": ["Essential", "에센셜", "=더블룸"],
          "k_room": (["더블룸", "Double Room"], ["디럭스", "Deluxe", "수페리어", "Superior", "스위트", "Suite", "트윈", "Twin"]),
          "g_room": (["더블룸", "Double Room"], ["수페리어", "슈페리어", "디럭스", "Deluxe", "트윈", "Twin", "스위트", "Suite", "싱글", "Single"]),
          "gh_name": ["Hotel Ohla Eixample Barcelona", "Ohla Eixample Barcelona"],
          "booking": "https://www.booking.com/hotel/es/ohla-eixample.ko.html?checkin=2027-09-06&checkout=2027-09-10" + BQ,
          "kayak": "https://www.kayak.co.kr/hotels/Ohla-Eixample,Barcelona,Spain-c22567-h2502753-details/2027-09-06/2027-09-10" + KQ},
    "2": {"name": "Zoëtry Mallorca", "dates": "9/10~9/14", "nights": 4, "room": ["=포넨트 더블룸", "Ponent Double", "Double Ponent"],
          "k_room": (["Ponent", "포넨트"], ["스위트", "Suite", "주니어", "Junior", "디럭스", "Deluxe"]),
          "g_room": (["Ponent", "포넨트"], ["스위트", "Suite", "주니어", "Junior", "디럭스", "Deluxe"]),
          "gh_name": ["Zoëtry Mallorca", "Zoetry Mallorca"],
          "booking": "https://www.booking.com/hotel/es/hotel-sa-torre-mallorca.ko.html?checkin=2027-09-10&checkout=2027-09-14" + BQ,
          "kayak": "https://www.kayak.co.kr/hotels/Zoetry-Mallorca-Wellness-Spa,Llucmajor,Spain-h2495579-details/2027-09-10/2027-09-14" + KQ,
          "all_inclusive": True},
    "3": {"name": "Mercure Porto Centro", "dates": "9/14~9/17", "nights": 3, "room": ["Standard Double", "스탠다드 더블"],
          "k_room": (["Superior Double", "슈페리어 더블", "슈피리어룸, 더블", "슈피리어 더블"], ["Twin", "트윈", "Family", "패밀리", "Suite", "스위트"]),
          "g_room": (["슈페리어룸", "Superior Double", "슈페리어 더블"], ["싱글", "트윈", "트리플", "스위트", "패밀리", "Twin", "Single", "Triple", "Suite", "Family"]),
          "gh_name": ["호텔 머큐어 포르토 센트로", "Mercure Porto Centro Santa Catarina", "Hotel Mercure Porto Centro"],
          "booking": "https://www.booking.com/hotel/pt/mercure-batalha-porto.ko.html?checkin=2027-09-14&checkout=2027-09-17" + BQ,
          "kayak": "https://www.kayak.co.kr/hotels/Mercure-Porto-Centro-Santa-Catarina,Porto,Portugal-c22089-h74862-details/2027-09-14/2027-09-17" + KQ},
    "4": {"name": "TURIM Boulevard", "dates": "9/17~9/18", "nights": 1, "room": ["=수페리어 더블룸", "=Superior Double Room"],
          "k_room": (["슈피리어 더블룸", "슈페리어 더블룸", "수페리어 더블룸", "Superior Double"], ["Twin", "트윈"]),
          "g_room": (["Superior", "슈페리어", "수페리어"], ["Twin", "트윈", "싱글", "Single"]),
          "gh_name": ["TURIM Boulevard Hotel", "TURIM Boulevard Hotel Lisbon"],
          "booking": "https://www.booking.com/hotel/pt/turim-boulevard.ko.html?checkin=2027-09-17&checkout=2027-09-18" + BQ,
          "kayak": "https://www.kayak.co.kr/hotels/TURIM-Boulevard-Hotel,Lisbon,Portugal-c21721-h4855678-details/2027-09-17/2027-09-18" + KQ},
}


# ---------------- 일정 2 (2027-09-08~09-22, 14박) ----------------
# 바르셀로나 9/8~9/12(4박) · 세비야 9/12~9/15(숙소 미정, 조회 대상 아님) · 포르투 9/15~9/18(3박) · 마요르카 9/18~9/22(4박)
# 견적서와 같은 호텔·객실 기준으로 날짜만 바꿔 조회한다. 세비야는 견적서에 없는 도시라 화면에서 직접 입력.
HOTELS_S2 = {
    "1": {"name": "Ohla Eixample", "dates": "9/8~9/12", "nights": 4, "room": ["Essential", "에센셜", "=더블룸"],
          "k_room": (["더블룸", "Double Room"], ["디럭스", "Deluxe", "수페리어", "Superior", "스위트", "Suite", "트윈", "Twin"]),
          "g_room": (["더블룸", "Double Room"], ["수페리어", "슈페리어", "디럭스", "Deluxe", "트윈", "Twin", "스위트", "Suite", "싱글", "Single"]),
          "gh_name": ["Hotel Ohla Eixample Barcelona", "Ohla Eixample Barcelona"],
          "gh": ("Hotel Ohla Eixample Barcelona", "2027-09-08", "2027-09-12"),
          "booking": "https://www.booking.com/hotel/es/ohla-eixample.ko.html?checkin=2027-09-08&checkout=2027-09-12" + BQ,
          "kayak": "https://www.kayak.co.kr/hotels/Ohla-Eixample,Barcelona,Spain-c22567-h2502753-details/2027-09-08/2027-09-12" + KQ},
    "2": {"name": "Mercure Porto Centro", "dates": "9/15~9/18", "nights": 3, "room": ["Standard Double", "스탠다드 더블"],
          "k_room": (["Superior Double", "슈페리어 더블", "슈피리어룸, 더블", "슈페리어 더블"], ["Twin", "트윈", "Family", "패밀리", "Suite", "스위트"]),
          "g_room": (["슈페리어룸", "Superior Double", "슈페리어 더블"], ["싱글", "트윈", "트리플", "스위트", "패밀리", "Twin", "Single", "Triple", "Suite", "Family"]),
          "gh_name": ["호텔 머큐어 포르토 센트로", "Mercure Porto Centro Santa Catarina", "Hotel Mercure Porto Centro"],
          "gh": ("Mercure Porto Centro Santa Catarina", "2027-09-15", "2027-09-18"),
          "booking": "https://www.booking.com/hotel/pt/mercure-batalha-porto.ko.html?checkin=2027-09-15&checkout=2027-09-18" + BQ,
          "kayak": "https://www.kayak.co.kr/hotels/Mercure-Porto-Centro-Santa-Catarina,Porto,Portugal-c22089-h74862-details/2027-09-15/2027-09-18" + KQ},
    "3": {"name": "Zoëtry Mallorca", "dates": "9/18~9/22", "nights": 4, "room": ["=포넨트 더블룸", "Ponent Double", "Double Ponent"],
          "k_room": (["Ponent", "포넨트"], ["스위트", "Suite", "주니어", "Junior", "디럭스", "Deluxe"]),
          "g_room": (["Ponent", "포넨트"], ["스위트", "Suite", "주니어", "Junior", "디럭스", "Deluxe"]),
          "gh_name": ["Zoëtry Mallorca", "Zoetry Mallorca"],
          "gh": ("Zoetry Mallorca", "2027-09-18", "2027-09-22"),
          "booking": "https://www.booking.com/hotel/es/hotel-sa-torre-mallorca.ko.html?checkin=2027-09-18&checkout=2027-09-22" + BQ,
          "kayak": "https://www.kayak.co.kr/hotels/Zoetry-Mallorca-Wellness-Spa,Llucmajor,Spain-h2495579-details/2027-09-18/2027-09-22" + KQ,
          "all_inclusive": True},
}


# ---------------- 일정 3 (2027-09-08~09-22, 14박) ----------------
# 바르셀로나 입국(9/8) → 당일 마요르카 이동 · 마요르카 9/8~9/12(4박) · 세비야 9/12~9/15(숙소 미정)
# · 포르투 9/15~9/18(3박) · 바르셀로나 9/18~9/22(4박) → 9/22 귀국
# 포르투는 일정 2와 날짜(9/15~9/18)가 같아 일정 2 조회 결과를 그대로 재사용한다 (REUSE_HOTELS_S3).
HOTELS_S3 = {
    "1": {"name": "Zoëtry Mallorca", "dates": "9/8~9/12", "nights": 4, "room": ["=포넨트 더블룸", "Ponent Double", "Double Ponent"],
          "k_room": (["Ponent", "포넨트"], ["스위트", "Suite", "주니어", "Junior", "디럭스", "Deluxe"]),
          "g_room": (["Ponent", "포넨트"], ["스위트", "Suite", "주니어", "Junior", "디럭스", "Deluxe"]),
          "gh_name": ["Zoëtry Mallorca", "Zoetry Mallorca"],
          "gh": ("Zoetry Mallorca", "2027-09-08", "2027-09-12"),
          "booking": "https://www.booking.com/hotel/es/hotel-sa-torre-mallorca.ko.html?checkin=2027-09-08&checkout=2027-09-12" + BQ,
          "kayak": "https://www.kayak.co.kr/hotels/Zoetry-Mallorca-Wellness-Spa,Llucmajor,Spain-h2495579-details/2027-09-08/2027-09-12" + KQ,
          "all_inclusive": True},
    "2": {"name": "Mercure Porto Centro", "dates": "9/15~9/18", "nights": 3, "room": ["Standard Double", "스탠다드 더블"],
          "k_room": (["Superior Double", "슈페리어 더블", "슈피리어룸, 더블", "슈페리어 더블"], ["Twin", "트윈", "Family", "패밀리", "Suite", "스위트"]),
          "g_room": (["슈페리어룸", "Superior Double", "슈페리어 더블"], ["싱글", "트윈", "트리플", "스위트", "패밀리", "Twin", "Single", "Triple", "Suite", "Family"]),
          "gh_name": ["호텔 머큐어 포르토 센트로", "Mercure Porto Centro Santa Catarina", "Hotel Mercure Porto Centro"],
          "gh": ("Mercure Porto Centro Santa Catarina", "2027-09-15", "2027-09-18"),
          "booking": "https://www.booking.com/hotel/pt/mercure-batalha-porto.ko.html?checkin=2027-09-15&checkout=2027-09-18" + BQ,
          "kayak": "https://www.kayak.co.kr/hotels/Mercure-Porto-Centro-Santa-Catarina,Porto,Portugal-c22089-h74862-details/2027-09-15/2027-09-18" + KQ},
    "3": {"name": "Ohla Eixample", "dates": "9/18~9/22", "nights": 4, "room": ["Essential", "에센셜", "=더블룸"],
          "k_room": (["더블룸", "Double Room"], ["디럭스", "Deluxe", "수페리어", "Superior", "스위트", "Suite", "트윈", "Twin"]),
          "g_room": (["더블룸", "Double Room"], ["수페리어", "슈페리어", "디럭스", "Deluxe", "트윈", "Twin", "스위트", "Suite", "싱글", "Single"]),
          "gh_name": ["Hotel Ohla Eixample Barcelona", "Ohla Eixample Barcelona"],
          "gh": ("Hotel Ohla Eixample Barcelona", "2027-09-18", "2027-09-22"),
          "booking": "https://www.booking.com/hotel/es/ohla-eixample.ko.html?checkin=2027-09-18&checkout=2027-09-22" + BQ,
          "kayak": "https://www.kayak.co.kr/hotels/Ohla-Eixample,Barcelona,Spain-c22567-h2502753-details/2027-09-18/2027-09-22" + KQ},
}
REUSE_HOTELS_S3 = {"2"}          # 포르투 9/15~9/18 = 일정 2와 동일 날짜·숙소 → hotels_s2/official_s2 결과 재사용


# ---------------- 구글 호텔 검색 URL ----------------
# 구글 호텔은 날짜와 통화를 URL의 ts(protobuf, base64url) 파라미터로 받는다.
# checkin / checkout / curr 파라미터만 붙이면 무시되어 '오늘~내일' 가격이 US$(미국 러너 기준)로 뜬다.
# 그래서 일정과 KRW를 담은 ts를 직접 만들어 붙인다 (구글이 만든 ts와 바이트 단위로 같은 값이 나오는 것을 확인).
# ap=ugEGcHJpY2Vz 는 상세 화면의 '가격' 탭을 가리키는 값.
GH_Q = {"1": ("Hotel Ohla Eixample Barcelona", "2027-09-06", "2027-09-10"),
        "2": ("Zoetry Mallorca", "2027-09-10", "2027-09-14"),
        "3": ("Mercure Porto Centro Santa Catarina", "2027-09-14", "2027-09-17"),
        "4": ("TURIM Boulevard Hotel Lisbon", "2027-09-17", "2027-09-18")}


def fetch_eur_krw(prev=None):
    """현재 EUR→KRW 환율을 공개 API에서 조회해 (원 단위 정수, 기준일, 출처)로 반환.
    API가 모두 실패하면 저장돼 있던 이전 값, 그것도 없으면 EUR_KRW_DEFAULT(1475)를 쓴다."""
    for name, url in EUR_KRW_API:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "honeymoon-price-check/1.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                d = json.loads(r.read().decode("utf-8"))
            raw = (d.get("rates") or {}).get("KRW")
            if raw is None:
                continue
            rate = float(raw)
            if not (500 <= rate <= 5000):  # 단위가 바뀐 응답은 쓰지 않는다
                continue
            date = d.get("date") or datetime.now(KST).strftime("%Y-%m-%d")
            return round(rate), date, name
        except Exception as e:
            print(f"환율 조회 실패({name}): {str(e)[:80]}")
    if prev:
        try:
            return int(float(prev)), None, "저장값"
        except (TypeError, ValueError):
            pass
    return EUR_KRW_DEFAULT, None, "기본값"


def _pb_varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _pb_len(field, payload):
    return _pb_varint(field << 3 | 2) + _pb_varint(len(payload)) + payload


def _pb_num(field, n):
    return _pb_varint(field << 3) + _pb_varint(n)


def gh_ts(ci, co, adults=2, cur="KRW"):
    """구글 호텔 ts 파라미터: [체크인, 체크아웃, 인원수, 통화]"""
    a = tuple(int(x) for x in ci.split("-"))
    b = tuple(int(x) for x in co.split("-"))
    d1 = _pb_num(1, a[0]) + _pb_num(2, a[1]) + _pb_num(3, a[2])
    d2 = _pb_num(1, b[0]) + _pb_num(2, b[1]) + _pb_num(3, b[2])
    inner = _pb_len(2, _pb_len(1, d1) + _pb_len(2, d2)) + _pb_len(6, _pb_num(1, adults))
    raw = _pb_num(1, 0) + _pb_len(3, _pb_len(2, inner)) + _pb_len(5, _pb_len(1, _pb_len(7, cur.encode())))
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _gh(q, ci, co):
    return ("https://www.google.com/travel/search?q=" + urllib.parse.quote(q) +
            f"&checkin={ci}&checkout={co}&adults=2&hl=ko&gl=kr&curr=KRW" +
            f"&ts={gh_ts(ci, co)}&ap=ugEGcHJpY2Vz")


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

# 일정 2 도시 간 이동·렌터카 (세비야→포르투 9/15, 포르투→마요르카 9/18, 마요르카→바르셀로나 9/22, 마요르카 렌터카 9/18~9/22 4일)
EXTRAS_S2 = {
    "fl_svq_opo": {"name": "세비야→포르투 9/15", "kind": "flight", "url": _gf("SVQ", "OPO", "2027-09-15")},
    "fl_opo_pmi": {"name": "포르투→마요르카 9/18", "kind": "flight", "url": _gf("OPO", "PMI", "2027-09-18")},
    "fl_pmi_bcn": {"name": "마요르카→바르셀로나 9/22", "kind": "flight", "url": _gf("PMI", "BCN", "2027-09-22")},
    "car_small": {"name": "마요르카 렌터카 자동 최저가 (9/18~9/22, 4일)", "kind": "car",
                  "url": "https://www.kayak.co.kr/cars/PMI/2027-09-18-12h/2027-09-22-12h?sort=price_a"},
    "car_suv": {"name": "마요르카 렌터카 자동 SUV (9/18~9/22, 4일)", "kind": "car",
                "url": "https://www.kayak.co.kr/cars/PMI/2027-09-18-12h/2027-09-22-12h?sort=price_a&fs=carclass=suv"},
}

# 일정 3 도시 간 이동·렌터카 (바르셀로나→마요르카 9/8, 마요르카→세비야 9/12, 세비야→포르투 9/15, 포르투→바르셀로나 9/18,
# 마요르카 렌터카 9/8~9/12 4일). 세비야→포르투 9/15은 일정 2와 같은 날짜라 그 결과를 재사용한다.
EXTRAS_S3 = {
    "fl_bcn_pmi": {"name": "바르셀로나→마요르카 9/8", "kind": "flight", "url": _gf("BCN", "PMI", "2027-09-08")},
    "fl_pmi_svq": {"name": "마요르카→세비야 9/12", "kind": "flight", "url": _gf("PMI", "SVQ", "2027-09-12")},
    "fl_svq_opo": {"name": "세비야→포르투 9/15", "kind": "flight", "url": _gf("SVQ", "OPO", "2027-09-15")},
    "fl_opo_bcn": {"name": "포르투→바르셀로나 9/18", "kind": "flight", "url": _gf("OPO", "BCN", "2027-09-18")},
    "car_small": {"name": "마요르카 렌터카 자동 최저가 (9/8~9/12, 4일)", "kind": "car",
                  "url": "https://www.kayak.co.kr/cars/PMI/2027-09-08-12h/2027-09-12-12h?sort=price_a"},
    "car_suv": {"name": "마요르카 렌터카 자동 SUV (9/8~9/12, 4일)", "kind": "car",
                "url": "https://www.kayak.co.kr/cars/PMI/2027-09-08-12h/2027-09-12-12h?sort=price_a&fs=carclass=suv"},
}
REUSE_EXTRAS_S3 = {"fl_svq_opo"}  # 세비야→포르투 9/15 = 일정 2와 동일 날짜 → extras_s2 결과 재사용

WON = re.compile(r"(?:₩\s*([\d,]+)|([\d,]{5,})\s*원)")
NO_ROOM = ["선택하신 날짜에 이용 가능한 객실이 없습니다", "예약 가능한 객실이 없습니다", "예약 가능한 객실 없음",
           "선택 날짜에는 본 사이트 상 예약 불가", "no availability"]
BLOCK = ["로봇", "robot", "captcha", "보안 확인", "Please confirm", "unusual traffic", "비정상적인 트래픽", "실제 KAYAK 사용자임을 확인", "본인 확인:"]
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
def fetch_booking_rows(page, h, hid, tag=""):
    """객실 표의 각 줄을 (조건 문구, 숙박 전체 가격)으로 반환"""
    page.goto(h["booking"], wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(7000)
    body = page.inner_text("body")
    if any(k in body for k in NO_ROOM):
        save_debug(f"booking_{tag}{hid}.txt", body)
        return None, "해당 날짜 예약 가능한 객실 없음 (매진이거나 아직 판매 전)"
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
    save_debug(f"booking_{tag}{hid}.txt", "\n\n".join(f"[{p:,}] <{r}> {t}" for r, t, p in fixed) or body)
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


# ---------------- 구글 호텔 ----------------
# 호텔 상세(엔티티) 화면의 '가격' 탭에서 예약 사이트별 요금을 읽음.
# 일정·통화는 URL의 ts로 넘기고, 실제 화면의 날짜/통화가 맞는지 확인한 뒤 값만 사용.
GH_NO_BF = ["조식 불포함", "조식 별도", "조식 미포함"]

# 예약 사이트 카드(제목 h3)와 객실 줄(h4)을 문서 순서대로 읽어 (사이트, 객실, 조건문구, 가격들)로 반환
GH_EXTRACT_JS = r"""
(args) => {
  const EX = /비슷한 호텔|관련 항목|근처 공유숙박|인기 호텔|웹 검색결과|주변 장소|최근에 본|저장된 항목|모든 검색결과/;
  const out = {heads: [], dates: {}, offers: [], entity: false, won: 0, usd: 0, date_ok: false, tabs: []};
  const flat = (s) => (s || '').replace(/\s+/g, ' ').trim();
  out.heads = [...document.querySelectorAll('h1')].map(e => flat(e.innerText)).slice(0, 4);
  out.tabs = [...document.querySelectorAll('[role=tab]')].map(t => flat(t.innerText));
  out.entity = out.tabs.some(t => t === '가격');
  document.querySelectorAll('[aria-label="체크인"],[aria-label="체크아웃"]').forEach(e => {
    out.dates[e.getAttribute('aria-label')] = flat(e.value || e.innerText);
  });
  const body = document.body.innerText || '';
  out.won = (body.match(/₩/g) || []).length;
  out.usd = (body.match(/US\$/g) || []).length;
  out.date_ok = !!args.ci && body.indexOf(args.ci) >= 0;
  const provFromText = (t) => {
    let s = t.replace(/₩\s?[\d,]+/g, ' ').replace(/US\$\s?[\d,.]+/g, ' ');
    s = s.split(/무료|조식|회원가|취소|Wi-Fi|와이파이|·|정가|\d+월|\d+일|반려|주차|수영장|사이트 방문/)[0].trim();
    return /^[\x20-\x7e]{2,40}$/.test(s) ? s : null;
  };
  // 상세 화면은 탭마다(개요/가격) 가격 목록을 따로 그리므로 값이 있는 탭을 모두 읽어 합친다.
  const panes = [...document.querySelectorAll('[role=tabpanel]')];
  const roots = panes.length ? panes : [document.querySelector('main') || document.body];
  for (const root of roots) {
    let lastProv = null;
    for (const el of root.querySelectorAll('h3, a, div[role=link]')) {
      if (el.tagName === 'H3') { lastProv = flat(el.innerText); continue; }
      const t = flat(el.innerText);
      // 예약 사이트 요금 줄만 인정 (검색 결과 카드의 '최저가 ₩…' 줄과 섞이지 않게)
      if (!/사이트 방문|가격 보기|숨은 비용 없음/.test(t)) continue;
      const vals = [...t.matchAll(/₩\s?([\d,]+)/g)].map(m => parseInt(m[1].replace(/,/g, ''))).filter(v => v >= 10000);
      if (!vals.length) continue;
      let up = el.parentElement, sect = null, d = 0;
      while (up && d < 15) {
        d++;
        const h2 = up.querySelector('h2');
        if (h2) { sect = flat(h2.innerText); break; }
        up = up.parentElement;
      }
      if (sect && EX.test(sect)) continue;
      const h3 = el.querySelector('h3'), h4 = el.querySelector('h4');
      const room = h4 ? flat(h4.innerText) : null;
      let prov = h3 ? flat(h3.innerText) : null;
      if (!prov) prov = h4 ? lastProv : provFromText(t);
      if (!prov) continue;
      out.offers.push({prov: prov, room: room, text: t.slice(0, 300), vals: vals});
    }
  }
  return out;
}
"""


def _click_text(page, text, timeout=4000, exact=True):
    try:
        page.get_by_text(text, exact=exact).first.click(timeout=timeout)
        return True
    except Exception:
        return False


def _md(s):
    m = re.search(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일", s or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def _gh_click_card(page, h, force_price=False):
    """검색 결과 목록이면 해당 호텔 카드를 눌러 상세 패널을 연다."""
    if not force_price:
        for nm in h.get("gh_name", []):
            for exact in (True, False):
                try:
                    loc = page.get_by_role("link", name=nm, exact=exact).first
                    if loc.count() and loc.is_visible():
                        loc.click(timeout=8000)
                        page.wait_for_timeout(6000)
                        return nm
                except Exception:
                    continue
    # 이름이 화면 언어와 달라 못 찾으면 첫 번째 결과(정확한 호텔명으로 검색했으므로 통상 1순위가 그 호텔)
    for role in ("link", "button"):
        try:
            loc = page.get_by_role(role, name="가격 보기").first
            if loc.count():
                loc.click(timeout=8000)
                page.wait_for_timeout(6000)
                return "첫 결과 가격 보기"
        except Exception:
            continue
    return None


def _gh_price_tab(page):
    """상세 화면의 '가격' 탭을 연다. 이미 열려 있으면 그대로 둔다."""
    try:
        tab = page.get_by_role("tab", name="가격", exact=True).first
        if tab.count():
            if (tab.get_attribute("aria-selected") or "").lower() == "true":
                return True
            tab.click(timeout=8000)
            page.wait_for_timeout(6000)
            return True
    except Exception:
        pass
    return False


def gh_total(vals, nights):
    """한 줄에 [할인 1박, 정가 1박, 정가 총액] 이 (중복 렌더로 두 번) 들어오는 구조를 처리.
    값이 급락하면 새 묶음으로 보고, 묶음마다 가장 큰 값(그 묶음의 숙박 총액)을 쓴 뒤 가장 싼 묶음을 고른다.
    총액이 없는 묶음(1박 요금만 있는 줄: 할인·정가 두 값이 비슷함)은 1박 요금 x 숙박일수."""
    groups, cur = [], []
    for v in vals:
        if cur and v < cur[-1] * 0.6:
            groups.append(cur)
            cur = [v]
        else:
            cur.append(v)
    if cur:
        groups.append(cur)
    totals = []
    for g in groups:
        if not g:
            continue
        m = max(g)
        # 값이 둘뿐이고 서로 비슷하면 숙박 총액 없이 1박 요금(할인·정가)만 있는 줄이다
        # (예: 2027-09-18~22 오라 — ₩556,961 ₩529,116). 이걸 총액으로 읽으면 4배 가량 낮아진다.
        if len(g) == 1 or (len(g) == 2 and m < min(g) * 1.5):
            totals.append(m * nights)
        else:
            totals.append(m)
    return min(totals) if totals else None


def _gh_extract(page, ci):
    return page.evaluate(GH_EXTRACT_JS, {"ci": f"{ci[:4]}년 {int(ci[5:7])}월 {int(ci[8:10])}일"})


def _gh_wait(page, ci, tries=6, delay=3000, need_room=False):
    """페이지가 늦게 그려지므로 사이트별 가격이 잡힐 때까지 몇 번 더 읽는다.
    need_room=True면 객실명이 붙은 요금이 나올 때까지 기다린다(가격 탭의 사이트 카드 목록)."""
    info = _gh_extract(page, ci)
    for _ in range(tries):
        if info.get("offers") and (not need_room or any(o.get("room") for o in info["offers"])):
            break
        page.wait_for_timeout(delay)
        info = _gh_extract(page, ci)
    return info


def _gh_open(page, hid, h):
    """검색 → (필요하면) 목록에서 호텔 카드 클릭 → '가격' 탭. 화면 상태를 반환."""
    q, ci, co = h.get("gh") or GH_Q[hid]
    page.goto(_gh(q, ci, co), wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(9000)
    body = page.inner_text("body")
    if has(body, BLOCK):
        return None, "차단", body
    info = _gh_wait(page, ci, 4)
    how = "상세 화면 바로 열림"
    if not info.get("entity"):
        clicked = _gh_click_card(page, h)
        if clicked:
            how = f"목록에서 '{clicked}' 클릭 → 상세"
            info = _gh_wait(page, ci, 8, 3500)
        if not info.get("offers"):
            clicked2 = _gh_click_card(page, h, force_price=True)
            if clicked2:
                how += f" / 재시도 '{clicked2}'"
                info = _gh_wait(page, ci, 8, 3500)
    if info.get("entity") and _gh_price_tab(page):
        # 가격 탭은 사이트 카드/객실 줄이 늦게 그려지므로 객실 정보가 나올 때까지 조금 더 기다림
        more = _gh_wait(page, ci, 8, 3000, need_room=True)
        if more.get("offers"):
            info = more
    return info, how, body


def google_hotel(page, hid, h, tag=""):
    """반환: ({'breakfast': [...], 'fc': [...], 'ai': [...]}, 오류)
    각 항목은 (숙박 전체 금액, 설명문, 객실명, 예약사이트)"""
    q, ci, co = h.get("gh") or GH_Q[hid]
    want_ci, want_co = _md(f"{ci[5:7]}월 {ci[8:10]}일"), _md(f"{co[5:7]}월 {co[8:10]}일")
    nights = h["nights"]
    err = "구글 호텔 조회 실패"
    for attempt in range(2):
        info, how, body = _gh_open(page, hid, h)
        if info is None:
            err = "구글이 자동 조회를 차단함"
            save_debug(f"google_{tag}{hid}.txt", body)
            page.wait_for_timeout(4000)
            continue
        dates_ok = bool(info.get("date_ok")) or (
            _md(info["dates"].get("체크인", "")) == want_ci and _md(info["dates"].get("체크아웃", "")) == want_co)
        cur_ok = info.get("won", 0) > 0 and info.get("usd", 0) == 0
        uniq = {}
        for o in info.get("offers", []):
            total = gh_total(o["vals"], nights)
            if not total:
                continue
            uniq.setdefault((o["prov"], o["room"], total), (total, o["text"], o["room"], o["prov"]))
        found = list(uniq.values())
        head = (f"=== {h['name']} / {how} / 시도 {attempt + 1} / "
                f"날짜 {info.get('dates')} (요청 {ci}~{co}, 적용 {'확인' if dates_ok else '실패'}) / "
                f"₩ {info.get('won', 0)}회 US$ {info.get('usd', 0)}회 / 탭 {info.get('tabs')} ===\n"
                f"=== 제목 {info.get('heads')} ===\n")
        save_debug(f"google_{tag}{hid}.txt", head +
                   "\n".join(f"[{t:,}] <{r}> {p} | {x}" for t, x, r, p in found[:250]) +
                   "\n\n=== 화면 전체 ===\n" + body[:12000])
        if not dates_ok:
            err = f"구글 호텔에 요청 일정이 적용되지 않음 (화면: {info.get('dates')})"
        elif not cur_ok:
            err = f"구글 호텔이 원화로 표시되지 않음 (₩ {info.get('won', 0)}회, US$ {info.get('usd', 0)}회)"
        elif not found:
            err = "상세 가격 목록을 찾지 못함"
        else:
            res = {
                "breakfast": [f for f in found if "조식" in f[1] and not has(f[1], GH_NO_BF) and not has(f[1], ALL_INC)],
                "ai": [f for f in found if has(f[1], ALL_INC)],
            }
            res["fc"] = [f for f in res["breakfast"] if has(f[1], FREE_CANCEL)]
            return res, None
        page.wait_for_timeout(4000)  # 빈 화면·목록만 뜬 경우 한 번 더 시도
    return None, err


def gh_pick(cands, h, ref, label):
    """견적서와 같은 조건으로 비교: 견적 객실(g_room)에 해당하는 요금만 사용.
    견적 객실이 목록에 없고 구글이 객실을 구분해 보여주지도 않으면 전체 최저가를 쓰되 문구에 남김.
    값은 구글이 보여준 1박 요금 x 숙박일수. 부킹닷컴과 40% 넘게 차이 나면 제외."""
    if not cands:
        return None, f"구글 호텔에 {label} 표시 요금이 없음"
    inc, exc = h.get("g_room") or h["k_room"]
    rooms = sorted({c[2] for c in cands if c[2]})
    match = [c for c in cands if c[2] and any(w.lower() in c[2].lower() for w in inc)
             and not any(x.lower() in c[2].lower() for x in exc)]
    note = ""
    if match:
        use = match
    elif rooms:
        use = cands
        note = " · 견적 객실 없어 전체 최저가"
    else:
        use = cands
        note = " · 구글이 객실 구분 없이 표시"
    total = min(c[0] for c in use)
    if ref and not (0.6 * ref <= total <= 1.4 * ref):
        return None, f"부킹닷컴과 차이가 커서 제외 (구글 {total:,}원{note})"
    err = note.strip(" ·") or None
    return total, err


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
_CAR_CACHE = {}


def fetch_car(page, url, key, prev_total):
    # 최저가와 SUV를 같은 페이지에서 읽어 카약 접속 횟수를 줄임
    if url not in _CAR_CACHE:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(15000)
        _CAR_CACHE[url] = page.inner_text("body")
    body = _CAR_CACHE[url]
    save_debug(f"car_{key}.txt", body)
    if has(body, BLOCK):
        return None, "카약이 자동 조회를 차단함 (사용자 확인 요구)"
    want_suv = "suv" in key
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



# ---------------- 호텔 공식 홈페이지(무료 취소 회원가) ----------------
# 오라·조에트리·투림은 같은 예약엔진(eMascaró bookcore), 메르쿠르는 아코르(all.accor.com).
# 엔진 화면의 'Price with discount'(할인 적용가)와 회원가(Privilege Club / World of Hyatt / TURIM Club / ALL)를 읽는다.
EUR_KRW_DEFAULT = 1475  # 환율 조회가 모두 실패했을 때 쓰는 기본값 (2026-11-26 기준)
EUR_KRW = EUR_KRW_DEFAULT  # 실행할 때마다 fetch_eur_krw()가 갱신하고, 공식 홈페이지 유로 요금 환산에 쓴다
# 유로→원 환율 공개 API (앞에서부터 시도, 실패하면 다음 것으로)
EUR_KRW_API = [
    ("frankfurter", "https://api.frankfurter.app/latest?from=EUR&to=KRW"),
    ("er-api", "https://open.er-api.com/v6/latest/EUR"),
]
EMAS_OCC = ("%5B%7B%22adults%22%3A%202%2C%20%22children%22%3A%200%2C%20%22ages%22%3A%20%22%22%7D%5D")
OFFICIAL = {
    "1": {"site": "올라 공식(Privilege Club)", "engine": "emascaro", "cur": "auto",
          "home": "https://booking.ohlaboutiquehotels.com/en/",
          "url": "https://booking.ohlaboutiquehotels.com/en/bookcore/availability/ohlcrs/{ci}/{co}/2/0/?rrc=1&adults=2&occupancies=" + EMAS_OCC + "&occp=1",
          "ci": "2027-09-06", "co": "2027-09-10", "nights": 4,
          "room": ["essential"], "cancel": "Free cancellation", "meal": "Bed & Breakfast"},
    "2": {"site": "조에트리 공식(World of Hyatt)", "engine": "emascaro", "cur": "auto",
          "url": "https://bookings.hyattinclusivecollection.com/bookcore/availability/satorre/{ci}/{co}/2/0/?rrc=1&adults=2&occupancies=" + EMAS_OCC + "&occp=1",
          "ci": "2027-09-10", "co": "2027-09-14", "nights": 4,
          "room": ["ponent"], "cancel": "Free cancellation", "meal": "Bed & Breakfast"},
    "3": {"site": "아코르 공식(ALL 회원가)", "engine": "accor", "cur": "EUR",
          "url": "https://all.accor.com/booking/en/accor/hotel/1975?dateIn={ci}&nights=3&compositions=2&stayplus=false",
          "ci": "2027-09-14", "co": "2027-09-17", "nights": 3,
          "room": ["superior room with 1 double bed"], "cancel": "Free cancellation", "meal": "Breakfast included"},
    "4": {"site": "투림 공식(TURIM Club)", "engine": "emascaro", "cur": "auto",
          "url": "https://bookings.turim-hotels.com/en/bookcore/availability/turimboulevard/{ci}/{co}/2/0/?rrc=1&adults=2&occupancies=" + EMAS_OCC + "&occp=1",
          "ci": "2027-09-17", "co": "2027-09-18", "nights": 1,
          "room": ["double superior"], "cancel": "Free cancellation", "meal": "Bed & Breakfast"},
}

# 일정 2 공식 홈페이지 (같은 호텔·같은 객실, 날짜만 9/8~9/22로 변경)
OFFICIAL_S2 = {
    "1": {"site": "올라 공식(Privilege Club)", "engine": "emascaro", "cur": "auto",
          "home": "https://booking.ohlaboutiquehotels.com/en/",
          "url": "https://booking.ohlaboutiquehotels.com/en/bookcore/availability/ohlcrs/{ci}/{co}/2/0/?rrc=1&adults=2&occupancies=" + EMAS_OCC + "&occp=1",
          "ci": "2027-09-08", "co": "2027-09-12", "nights": 4,
          "room": ["essential"], "cancel": "Free cancellation", "meal": "Bed & Breakfast"},
    "2": {"site": "아코르 공식(ALL 회원가)", "engine": "accor", "cur": "EUR",
          "url": "https://all.accor.com/booking/en/accor/hotel/1975?dateIn={ci}&nights=3&compositions=2&stayplus=false",
          "ci": "2027-09-15", "co": "2027-09-18", "nights": 3,
          "room": ["superior room with 1 double bed"], "cancel": "Free cancellation", "meal": "Breakfast included"},
    "3": {"site": "조에트리 공식(World of Hyatt)", "engine": "emascaro", "cur": "auto",
          "url": "https://bookings.hyattinclusivecollection.com/bookcore/availability/satorre/{ci}/{co}/2/0/?rrc=1&adults=2&occupancies=" + EMAS_OCC + "&occp=1",
          "ci": "2027-09-18", "co": "2027-09-22", "nights": 4,
          "room": ["ponent"], "cancel": "Free cancellation", "meal": "Bed & Breakfast"},
}

# 일정 3 공식 홈페이지 (마요르카 9/8~9/12 · 포르투 9/15~9/18은 일정 2 결과 재사용 · 오라 9/18~9/22)
OFFICIAL_S3 = {
    "1": {"site": "조에트리 공식(World of Hyatt)", "engine": "emascaro", "cur": "auto",
          "url": "https://bookings.hyattinclusivecollection.com/bookcore/availability/satorre/{ci}/{co}/2/0/?rrc=1&adults=2&occupancies=" + EMAS_OCC + "&occp=1",
          "ci": "2027-09-08", "co": "2027-09-12", "nights": 4,
          "room": ["ponent"], "cancel": "Free cancellation", "meal": "Bed & Breakfast"},
    "2": {"site": "아코르 공식(ALL 회원가)", "engine": "accor", "cur": "EUR",
          "url": "https://all.accor.com/booking/en/accor/hotel/1975?dateIn={ci}&nights=3&compositions=2&stayplus=false",
          "ci": "2027-09-15", "co": "2027-09-18", "nights": 3,
          "room": ["superior room with 1 double bed"], "cancel": "Free cancellation", "meal": "Breakfast included"},
    "3": {"site": "올라 공식(Privilege Club)", "engine": "emascaro", "cur": "auto",
          "home": "https://booking.ohlaboutiquehotels.com/en/",
          "url": "https://booking.ohlaboutiquehotels.com/en/bookcore/availability/ohlcrs/{ci}/{co}/2/0/?rrc=1&adults=2&occupancies=" + EMAS_OCC + "&occp=1",
          "ci": "2027-09-18", "co": "2027-09-22", "nights": 4,
          "room": ["essential"], "cancel": "Free cancellation", "meal": "Bed & Breakfast"},
}

OFF_FIG_JS = r"""
() => [...document.querySelectorAll('figure')].map(f => ({
  heads: [...f.querySelectorAll('h3')].map(h => h.innerText.replace(/\s+/g, ' ').trim()),
  text: f.innerText
})).filter(r => /€|₩/.test(r.text))
"""

ACCOR_CARD_JS = r"""
() => [...document.querySelectorAll('h3')].map(h => {
  let el = h.parentElement, d = 0;
  while (el && d < 6 && (el.innerText || '').length < 1600) { el = el.parentElement; d++; }
  return {head: (h.innerText || '').trim(), text: ((el || h).innerText || '').slice(0, 1500)};
}).filter(r => /€|₩/.test(r.text))
"""

OFF_MONEY = re.compile(r"(?:€|₩)\s*([\d.,]+)")
PENSIONS = ("Bed & Breakfast", "Room Only", "Half Board", "All Inclusive", "Full Board")


def _amt(s):
    s = s.strip().replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", "")
    return float(s)


def _money_in(text):
    out = []
    for m in OFF_MONEY.finditer(text):
        try:
            out.append(_amt(m.group(1)))
        except ValueError:
            pass
    return out


def parse_emascaro(rooms, cfg):
    """예약엔진 화면의 방/요금 블록에서 (객실, 요금명, 무료취소 문구, 기준가, 회원가)를 뽑는다."""
    nights = cfg["nights"]
    for r in rooms:
        heads = r.get("heads") or []
        if not heads:
            continue
        room = heads[0]
        if not any(w in room.lower() for w in cfg["room"]):
            continue
        text = r.get("text") or ""
        # 요금 이름(h3) 위치로 블록을 나눈다
        idx = []
        for h in heads[1:]:
            i = text.find(h)
            if i >= 0:
                idx.append((i, h))
        idx.sort()
        blocks = []
        for n, (i, h) in enumerate(idx):
            j = idx[n + 1][0] if n + 1 < len(idx) else len(text)
            blocks.append((h, text[i:j]))
        if not blocks:
            blocks = [(heads[0], text)]
        for rate, seg in blocks:
            if cfg["cancel"].lower() not in seg.lower():
                continue
            lines = [l.strip() for l in seg.split("\n") if l.strip()]
            # 식사 조건 단위로 나눔
            chunks, cur = [], []
            for l in lines:
                if l in PENSIONS and cur:
                    chunks.append(cur)
                    cur = [l]
                elif l in PENSIONS:
                    cur = [l]
                else:
                    cur.append(l)
            if cur:
                chunks.append(cur)
            for ch in chunks:
                body = "\n".join(ch)
                meal = ch[0] if ch and ch[0] in PENSIONS else ""
                if cfg["meal"].lower() not in (meal or "").lower():
                    continue
                # 회원가: 'UNLOCK PRICE <프로그램>' 다음 금액
                member = None
                for k, l in enumerate(ch):
                    if l.upper().startswith("UNLOCK PRICE"):
                        v = _money_in(l)
                        if not v:
                            for l2 in ch[k + 1:k + 4]:
                                v = _money_in(l2)
                                if v:
                                    break
                        if v:
                            member = v[0]
                        break
                # 할인 적용가: 'Price with discount' 다음 금액
                base = disc = None
                vals = _money_in("\n".join(l for l in ch if not l.upper().startswith("UNLOCK PRICE")))
                if vals:
                    base = vals[0]
                for k, l in enumerate(ch):
                    if l.lower().startswith("price with discount"):
                        for l2 in ch[k + 1:k + 2]:
                            v = _money_in(l2)
                            if v:
                                disc = v[0]
                        break
                if disc is None and vals:
                    disc = vals[-1]
                # 1박 요금으로 표시된 경우 숙박 전체로 환산
                low = body.lower()
                per_night = "average price/night" in low or "average price per night" in low
                mult = nights if per_night else 1
                cur_sym = "EUR" if "€" in body else ("KRW" if "₩" in body else cfg["cur"])
                cancel = next((l for l in lines if "free cancellation" in l.lower()), "")
                if disc:
                    return {"room": room, "rate": rate, "meal": meal, "cancel": cancel.strip(),
                            "cur": cur_sym, "public": disc * mult,
                            "member": (member * mult) if member else None,
                            "per_night": per_night, "raw": body[:600]}
    return None


def fetch_official_emascaro(page, key, cfg):
    url = cfg["url"].format(ci=cfg["ci"], co=cfg["co"])
    # 일부 엔진(올라)은 예약 화면을 그리기 전에 사이트 첫 화면에서 받는 쿠키가 필요함
    if cfg.get("home"):
        try:
            page.goto(cfg["home"], wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(4000)
        except Exception:
            pass
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    rooms = []
    no_avail = False
    for attempt in range(2):
        for _ in range(10):
            page.wait_for_timeout(4000)
            # 해당 날짜에 객실이 없으면 엔진이 no-availability 화면으로 넘어간다
            if "no-availability" in (page.url or ""):
                no_avail = True
                break
            try:
                rooms = page.evaluate(OFF_FIG_JS) or []
            except Exception:
                rooms = rooms or []
            if any(r.get("heads") and OFF_MONEY.search(r.get("text") or "") for r in rooms):
                if not any("Nombre de la tarifa." in (r.get("text") or "") for r in rooms):
                    break
        if no_avail or rooms:
            break
        # 첫 방문에서 화면이 비어 있으면 쿠키가 잡힌 뒤 한 번 더 들어간다
        page.wait_for_timeout(3000)
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
    if no_avail:
        save_debug(f"official_{key}.txt", f"=== {cfg['site']} {cfg['ci']}~{cfg['co']} / no-availability 화면 ===\n{page.url}")
        return None, "공식 사이트에 해당 날짜 예약 가능한 객실 없음 (판매 전이거나 매진)"
    res = parse_emascaro(rooms, cfg)
    try:
        body_txt = page.inner_text("body")[:2000]
    except Exception:
        body_txt = ""
    save_debug(f"official_{key}.txt",
               f"=== {cfg['site']} {cfg['ci']}~{cfg['co']} / 방 {len(rooms)}개 ===\n"
               f"=== 화면 앞부분 ===\n{body_txt}\n\n" +
               ("\n".join(f"- {r['heads'][0] if r.get('heads') else '?'} | {len(r.get('text',''))}자" for r in rooms[:12])) +
               "\n\n" + (f"선택: {res}\n" if res else "요금 블록을 찾지 못함\n") +
               "\n=== 원문(첫 3000자) ===\n" + "\n---\n".join((r.get("text") or "")[:1500] for r in rooms[:3]))
    if not res:
        return None, "공식 사이트에서 해당 객실의 무료 취소 요금을 찾지 못함"
    return res, None


def fetch_official_accor(page, key, cfg):
    url = cfg["url"].format(ci=cfg["ci"])
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    cards = []
    for _ in range(10):
        page.wait_for_timeout(4000)
        cards = page.evaluate(ACCOR_CARD_JS) or []
        if any("member rate" in (c.get("text") or "").lower() for c in cards):
            break
    # 무료 취소 + 조식 포함 조건으로 거르기
    for label in ("Free cancellation", "Breakfast included"):
        try:
            box = page.get_by_role("checkbox", name=label).first
            if box.count() and not box.is_checked():
                box.check(timeout=6000)
                page.wait_for_timeout(5000)
        except Exception:
            pass
    cards2 = page.evaluate(ACCOR_CARD_JS) or cards
    res = None
    for c in cards2:
        head = (c.get("head") or "").lower()
        if not any(w in head for w in cfg["room"]):
            continue
        t = c.get("text") or ""
        m_mem = re.search(r"Member rate\s*\n?\s*From\s*€\s*([\d.,]+)", t)
        m_pub = re.search(r"Public rate from\s*€\s*([\d.,]+)", t)
        if not m_pub and not m_mem:
            continue
        res = {"room": c.get("head"), "rate": "FLEXIBLE/무료취소·조식 필터", "meal": "Breakfast included",
               "cancel": "Free cancellation 필터 적용", "cur": "EUR",
               "public": _amt(m_pub.group(1)) if m_pub else None,
               "member": _amt(m_mem.group(1)) if m_mem else None,
               "per_night": False, "raw": t[:600]}
        break
    save_debug(f"official_{key}.txt",
               f"=== {cfg['site']} {cfg['ci']} / 카드 {len(cards2)}개 ===\n" +
               (f"선택: {res}\n" if res else "카드를 찾지 못함\n") +
               "\n=== 원문 ===\n" + "\n---\n".join((c.get("text") or "")[:800] for c in cards2[:6]))
    if not res:
        return None, "아코르 공식에서 해당 객실 요금을 찾지 못함"
    return res, None


def fetch_official(page, key, cfg):
    if cfg["engine"] == "accor":
        return fetch_official_accor(page, key, cfg)
    return fetch_official_emascaro(page, key, cfg)


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


def track_hotels(page, hotels, off_map, store, off_store, tag, now, put):
    """호텔 묶음(일정 1 또는 일정 2)을 부킹닷컴 → 구글 호텔 → 공식 홈페이지 순서로 조회해 기록한다.
    tag는 debug 파일 이름 접두사('' 또는 's2_')로, 두 일정의 확인용 화면 글자가 섞이지 않게 한다."""
    for hid, h in hotels.items():
        rec = store.setdefault(hid, {})
        rec["name"], rec["dates"] = h["name"], h["dates"]
        rec["last_check"] = now.strftime("%Y-%m-%d %H:%M")
        # 계산 방식이 바뀐 예전 기록(VAT 미포함 등)은 정확하지 않아 한 번 비움
        # 구글 호텔 조회 방식이 바뀌어(상세 화면 + ts) 이전 구글 값은 한 번 비움
        if rec.get("gh_method") != "gh-entity-v1":
            rec["gh_history"], rec["gh_fc_history"], rec["gh_ai_history"] = [], [], []
            rec["gh_method"] = "gh-entity-v1"
        if rec.get("method") != "rows-v6":
            for k in ("history", "fc_history", "ro_history", "ai_history", "ai_fc_history", "gh_history", "gh_fc_history", "gh_ai_history"):
                rec[k] = []
            rec["method"] = "rows-v6"
            for k in [x for x in rec if x.startswith("kayak_")]:
                rec.pop(k, None)

        try:
            rows, err = fetch_booking_rows(page, h, hid, tag)
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
            put(rec, "ai_fc_history", r["ai_fc"], "ai_fc_error", ("올인클루시브 무료 취소 요금이 표에 없음" if rows and r["ai_fc"] is None else err), h["name"] + " 올인클루시브 무료취소")

        try:
            g, gerr = google_hotel(page, hid, h, tag)
        except Exception as e:
            g, gerr = None, f"조회 오류: {str(e)[:80]}"
        notes = []

        def gp(cands, ref, label):
            v, e = gh_pick(cands, h, ref, label)
            if v is not None and e:
                notes.append(label + ": " + e)
            return v, e

        if g:
            k, kerr2 = gp(g["breakfast"], r["breakfast"], "조식 포함")
            kf, kferr = gp(g["fc"], r["fc"], "조식 포함 무료 취소")
        else:
            k, kerr2, kf, kferr = None, gerr, None, gerr
        put(rec, "gh_history", k, "gh_error", kerr2, "Google " + h["name"])
        put(rec, "gh_fc_history", kf, "gh_fc_error", kferr, "Google " + h["name"] + " 무료취소")
        if h.get("all_inclusive"):
            ka, aerr = gp(g["ai"], r["ai"], "올인클루시브") if g else (None, gerr)
            put(rec, "gh_ai_history", ka, "gh_ai_error", aerr, "Google " + h["name"] + " 올인클루시브")
        rec["gh_note"] = "; ".join(notes) or None
        print(tag or "s1", h["name"], r, "| google:", k, kerr2 or "", rec["gh_note"] or "")

        oc = off_map.get(hid)
        if oc:
            orec = off_store.setdefault(hid, {})
            orec["name"], orec["last_check"] = oc["site"], now.strftime("%Y-%m-%d %H:%M")
            try:
                ov, oerr = fetch_official(page, tag + hid, oc)
            except Exception as e:
                ov, oerr = None, f"조회 오류: {str(e)[:100]}"
            orec["error"] = oerr
            if ov:
                def to_krw(v):
                    return round(v * EUR_KRW) if ov["cur"] == "EUR" else round(v)
                orec["room"], orec["rate"], orec["cancel"], orec["meal"] = ov["room"], ov["rate"], ov["cancel"], ov["meal"]
                orec["cur"] = ov["cur"]
                if ov.get("public") is not None:
                    orec["public"] = {"amt": round(ov["public"], 2), "krw": to_krw(ov["public"])}
                    put(orec, "history", to_krw(ov["public"]), "error", None, oc["site"])
                if ov.get("member") is not None:
                    orec["member"] = {"amt": round(ov["member"], 2), "krw": to_krw(ov["member"])}
                    put(orec, "member_history", to_krw(ov["member"]), "member_error", None, oc["site"] + " 회원")
            print("  official:", oc["site"], ov and {kk: ov[kk] for kk in ("room", "rate", "public", "member", "cur")}, oerr or "")


def track_extras(page, extra_map, store, tag, now, put):
    """도시 간 항공·렌터카 참고가를 조회해 기록한다."""
    for key, e in extra_map.items():
        rec = store.setdefault(key, {})
        rec["name"] = e["name"]
        rec["last_check"] = now.strftime("%Y-%m-%d %H:%M")
        if rec.get("method") != "list-v2":
            rec["history"] = []
            rec["method"] = "list-v2"
        prev_hist = rec.get("history") or []
        try:
            if e["kind"] == "flight":
                v, verr = fetch_flight(page, e["url"], tag + key)
            else:
                v, verr = fetch_car(page, e["url"], tag + key, prev_hist[-1]["krw"] if prev_hist else None)
        except Exception as err:
            v, verr = None, f"조회 오류: {str(err)[:80]}"
        put(rec, "history", v, "error", verr, e["name"])
        print(e["name"], v, verr or "")


def main():
    from playwright.sync_api import sync_playwright
    global EUR_KRW
    only = ""
    for a in sys.argv[1:]:
        if a.lstrip("-") in ("s1", "s2", "s3"):
            only = a.lstrip("-")
    data = {"updated": None, "hotels": {}}
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, encoding="utf-8") as f:
            data = json.load(f)
    now = datetime.now(KST)
    today = now.strftime("%Y-%m-%d")
    alerts = []

    # 최신 유로 환율을 받아 오늘 기록에 남기고, 공식 홈페이지 유로 요금 환산에도 쓴다
    rate, rate_date, rate_src = fetch_eur_krw(data.get("eur_krw"))
    EUR_KRW = rate
    data["eur_krw"] = rate
    if rate_date:
        data["eur_krw_date"] = rate_date
    data["eur_krw_src"] = rate_src
    data["eur_krw_updated"] = now.strftime("%Y-%m-%d %H:%M")
    print(f"환율 1 EUR = {rate:,}원 ({rate_src}{', 기준일 ' + rate_date if rate_date else ''})")

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

        if only in ("", "s1"):
            track_hotels(page, HOTELS, OFFICIAL, data.setdefault("hotels", {}),
                         data.setdefault("official", {}), "", now, put)
            track_extras(page, EXTRAS, data.setdefault("extras", {}), "", now, put)
        if only in ("", "s2"):
            track_hotels(page, HOTELS_S2, OFFICIAL_S2, data.setdefault("hotels_s2", {}),
                         data.setdefault("official_s2", {}), "s2_", now, put)
            track_extras(page, EXTRAS_S2, data.setdefault("extras_s2", {}), "s2_", now, put)
        if only in ("", "s3"):
            s3hot = data.setdefault("hotels_s3", {})
            s3off = data.setdefault("official_s3", {})
            s3ex = data.setdefault("extras_s3", {})
            track_hotels(page, {k: v for k, v in HOTELS_S3.items() if k not in REUSE_HOTELS_S3},
                         {k: v for k, v in OFFICIAL_S3.items() if k not in REUSE_HOTELS_S3},
                         s3hot, s3off, "s3_", now, put)
            track_extras(page, {k: v for k, v in EXTRAS_S3.items() if k not in REUSE_EXTRAS_S3}, s3ex, "s3_", now, put)
            # 같은 날짜(포르투 9/15~9/18, 세비야→포르투 9/15)는 일정 2 결과를 그대로 쓴다
            for hid in REUSE_HOTELS_S3:
                if data.get("hotels_s2", {}).get(hid):
                    s3hot[hid] = json.loads(json.dumps(data["hotels_s2"][hid]))
                if data.get("official_s2", {}).get(hid):
                    s3off[hid] = json.loads(json.dumps(data["official_s2"][hid]))
            for k in REUSE_EXTRAS_S3:
                if data.get("extras_s2", {}).get(k):
                    s3ex[k] = json.loads(json.dumps(data["extras_s2"][k]))
        browser.close()

    data["updated"] = now.strftime("%Y-%m-%d %H:%M")
    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    if alerts:
        notify("Honeymoon price drop", "\n".join(alerts))


if __name__ == "__main__":
    main()
