"""
==========================================================================
아고다 호텔 가격 조회 엔진
==========================================================================
[이 모듈이 하는 것]
  engines/hotel.py 가 부킹닷컴을 다루는 것과 같은 역할을 아고다에 대해
  합니다. 부킹닷컴 쪽과 API 응답 모양이 아예 달라서(구조가 훨씬
  깊고 고정적입니다) 같은 파싱 함수를 못 쓰고 따로 만들었습니다.

  대신 반환하는 dict 모양은 hotel.py 와 최대한 맞췄습니다.
  (pages/8_호텔_가격_알림.py 에서 두 사이트 결과를 한 목록으로 합치기
  쉽도록.)

[이 API 의 특징]
  · 도시/호텔 검색(hotels/auto-complete)이 돌려주는 id 는 그대로 못 쓰고,
    반드시 "{typeId}_{id}" 형식으로 합쳐서 hotels/search-overnight 에
    넣어야 합니다. (예: 싱가포르 도시 id=4064, typeId=1 → "1_4064")
    이 형식을 몰라서 처음엔 "The id is invalid" 오류만 받았습니다 —
    엔드포인트 파라미터 설명에 적힌 예시(Ex: 1_318)를 보고 알아냈습니다.
  · 호텔 검색(search-overnight) 응답의 대표가는 부킹닷컴과 마찬가지로
    그 호텔에서 가장 싼 요금 하나뿐입니다. 무료취소 여부는
    pricing.payment.cancellation.cancellationType 으로 짐작은 되지만
    확정은 아닙니다("SpecialConditions" 는 조건부 환불이라 애매합니다).
  · 방 목록(hotels/room-prices) 응답에는 각 방/요금 조합마다
    cancellationInfo.type 이라는 **확정 필드**가 있습니다.
    1 = 무료취소, 2 = 환불불가. 문구를 안 읽어도 됩니다.
==========================================================================
"""

모듈버전 = "2026-09-09"

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

from engines.hotel import (  # noqa: F401  (같은 도구를 재사용합니다)
    _금액_읽기 as _수,
    _날짜,
    아이나이_읽기,
    오류설명,
    기본_통화,
)

기본_호스트 = "agoda-com.p.rapidapi.com"
조회_시간제한 = 25


def _GET(경로, 매개, 키, 호스트, 시간제한=조회_시간제한):
    url = f"https://{호스트}{경로}"
    if 매개:
        url += "?" + urllib.parse.urlencode(매개)
    req = urllib.request.Request(url)
    req.add_header("x-rapidapi-key", 키)
    req.add_header("x-rapidapi-host", 호스트)
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "personal-dashboard")
    with urllib.request.urlopen(req, timeout=시간제한) as resp:
        원문 = resp.read().decode("utf-8", "replace")
    try:
        return json.loads(원문)
    except json.JSONDecodeError:
        return {"_원문": 원문[:2000]}


# ==========================================================================
# 목적지 검색
# ==========================================================================

def 도시_찾기(질의, 키, 호스트=기본_호스트):
    """(목록, 오류). 목록 = [{"이름","라벨","place_id","typeId","나라"}]

    place_id 자체는 조회에 못 쓰고, typeId 와 합쳐 "{typeId}_{place_id}"
    형식으로 만들어야 hotels/search-overnight 에 넣을 수 있습니다.
    """
    if not 키:
        return [], "RapidAPI 키가 없습니다."
    if not str(질의 or "").strip():
        return [], "찾을 도시/호텔 이름을 넣으세요."
    try:
        결과 = _GET("/hotels/auto-complete", {"query": str(질의).strip()},
                  키, 호스트)
    except Exception as e:                                   # noqa: BLE001
        return [], 오류설명(e)

    # ★ 이 엔드포인트는 응답을 {"data": {...}} 로 감싸지 않고 최상위에
    #   바로 "places" 를 줍니다(다른 아고다 엔드포인트들과 다릅니다).
    #   혹시 나중에 감싸는 형태로 바뀌어도 대비해 data.places 도 봅니다.
    장소들 = 결과.get("places") if isinstance(결과, dict) else None
    if not isinstance(장소들, list):
        자료 = (결과.get("data") or {}) if isinstance(결과, dict) else {}
        장소들 = 자료.get("places") if isinstance(자료, dict) else None
    if not isinstance(장소들, list):
        return [], "찾은 결과가 없습니다. 영어 이름으로 넣어 보세요 (예: Singapore)."

    나온것 = []
    for d in 장소들:
        if not isinstance(d, dict):
            continue
        아이디 = d.get("id")
        typeId = d.get("typeId")
        if 아이디 in (None, "") or typeId in (None, ""):
            continue
        나라 = d.get("country")
        나라이름 = (나라.get("name") if isinstance(나라, dict)
                else str(나라 or "")).strip()
        나온것.append({
            "이름": str(d.get("name") or "").strip(),
            "라벨": str(d.get("name") or "").strip(),
            "place_id": str(아이디),
            "typeId": str(typeId),
            "typeName": str(d.get("typeName") or "").strip(),
            "나라": 나라이름,
        })
    if not 나온것:
        return [], "찾은 결과가 없습니다. 영어 이름으로 넣어 보세요 (예: Singapore)."
    return 나온것, None


def 합친_id(typeId, place_id) -> str:
    """search-overnight 의 id 파라미터 형식으로 합칩니다."""
    typeId = str(typeId or "").strip()
    place_id = str(place_id or "").strip()
    if not typeId or not place_id:
        return ""
    return f"{typeId}_{place_id}"


# ==========================================================================
# 호텔 검색 (그 도시/호텔에서 가장 싼 대표가 하나씩)
# ==========================================================================

_취소유형_표시 = {
    "NonRefundable": "불가",
    "SpecialConditions": "모름",   # 조건부 환불 — 문구를 안 읽으면 확정 못 함
}


def _가격_읽기(방):
    """roomOffers[0].room.pricing[0].price.perBook 에서 (세금제외, 세금포함, 통화)."""
    if not isinstance(방, dict):
        return None, None, ""
    pricing = 방.get("pricing")
    if not isinstance(pricing, list) or not pricing:
        return None, None, ""
    첫 = pricing[0] if isinstance(pricing[0], dict) else {}
    통화 = str(첫.get("currency") or "").strip().upper()
    perBook = ((첫.get("price") or {}).get("perBook") or {})
    제외 = _수((perBook.get("exclusive") or {}).get("display"))
    포함 = _수((perBook.get("inclusive") or {}).get("display"))
    return 제외, 포함, (통화 or 기본_통화)


def _property_해석(p):
    if not isinstance(p, dict):
        return None
    content = p.get("content") or {}
    이름 = str((content.get("informationSummary") or {}).get("localeName")
             or "").strip()
    if not 이름:
        return None

    pricing = p.get("pricing") or {}
    offers = pricing.get("offers") or []
    if not offers:
        return None
    roomOffers = (offers[0] or {}).get("roomOffers") or []
    if not roomOffers:
        return None
    방 = (roomOffers[0] or {}).get("room") or {}
    제외, 포함, 통화 = _가격_읽기(방)
    가격 = 포함 if 포함 else 제외
    if not 가격:
        return None

    취소유형 = str(((pricing.get("payment") or {}).get("cancellation") or {})
                 .get("cancellationType") or "")
    무료취소 = _취소유형_표시.get(취소유형, "모름")

    return {
        "호텔": 이름,
        "가격": float(가격),
        "통화": 통화,
        "링크": "",
        "무료취소": 무료취소,
        "세금포함": bool(포함),
        "hotel_id": str(p.get("propertyId") or pricing.get("hotelId") or ""),
        "사이트": "아고다",
    }


def 호텔목록_해석(자료) -> list:
    """search-overnight 응답에서 호텔 목록을 뽑아냅니다."""
    data = 자료.get("data") if isinstance(자료, dict) else None
    citySearch = (data or {}).get("citySearch") if isinstance(data, dict) else None
    searchResult = (citySearch or {}).get("searchResult") \
        if isinstance(citySearch, dict) else None
    properties = (searchResult or {}).get("properties") \
        if isinstance(searchResult, dict) else None
    if not isinstance(properties, list):
        return []
    나온것 = []
    for p in properties:
        항목 = _property_해석(p)
        if 항목:
            나온것.append(항목)
    return 나온것


def 이름_맞나(호텔이름, 찾는말) -> bool:
    if not 찾는말:
        return True
    a = re.sub(r"\s+", "", str(호텔이름 or "")).lower()
    b = re.sub(r"\s+", "", str(찾는말)).lower()
    return bool(b) and b in a


def 호텔_검색(id_값, 체크인, 체크아웃, 키, 호스트=기본_호스트, 어른=2, 방수=1,
         아이나이=None, 호텔이름="") -> tuple:
    """(목록, 오류, 원본JSON). id_값 은 합친_id() 로 만든 "{typeId}_{id}" 값."""
    if not 키:
        return [], "RapidAPI 키가 없습니다.", None
    if not id_값:
        return [], "도시/호텔을 먼저 확정(id)해야 합니다.", None
    들 = _날짜(체크인)
    나 = _날짜(체크아웃)
    if not 들 or not 나:
        return [], "체크인/체크아웃 날짜가 없습니다.", None

    매개 = {
        "id": id_값,
        "checkinDate": 들.isoformat(),
        "checkoutDate": 나.isoformat(),
        "adults": max(int(어른 or 2), 1),
        "rooms": max(int(방수 or 1), 1),
        "currency": 기본_통화,
        "language": "ko-kr",
    }
    아이들 = 아이나이_읽기(아이나이) if 아이나이 else []
    if 아이들:
        매개["children"] = len(아이들)
        매개["childrenAges"] = ",".join(str(n) for n in 아이들)

    try:
        원본 = _GET("/hotels/search-overnight", 매개, 키, 호스트)
    except Exception as e:                                   # noqa: BLE001
        return [], 오류설명(e), None

    목록 = 호텔목록_해석(원본)
    if not 목록:
        쪽지 = ""
        if isinstance(원본, dict):
            쪽지 = str(원본.get("message") or 원본.get("_원문") or "")[:200]
        return [], ("가격을 찾지 못했습니다. 응답 구조가 바뀌었을 수 있습니다. " +
                    쪽지).strip(), 원본

    if 호텔이름:
        걸러낸 = [h for h in 목록 if 이름_맞나(h["호텔"], 호텔이름)]
        if not 걸러낸:
            return [], (f"'{호텔이름}' 이(가) 검색 결과에 없습니다. "
                        f"({len(목록)}곳 중 없음)"), 원본
        목록 = 걸러낸

    목록.sort(key=lambda h: h["가격"])
    return 목록, None, 원본


def 최저가(목록):
    """(가격, 호텔이름, 통화, 무료취소, 세금포함, 사이트). hotel.py 의
    최저가()와 같은 모양(6-tuple)."""
    if not 목록:
        return 0.0, "", "", "모름", False, ""
    첫 = min(목록, key=lambda h: h["가격"])
    return (첫["가격"], 첫["호텔"], 첫["통화"], 첫.get("무료취소", "모름"),
            bool(첫.get("세금포함", False)), 첫.get("사이트", "아고다"))


# ==========================================================================
# 방 목록 — 무료취소를 확정 필드(cancellationInfo.type)로 압니다
# ==========================================================================

def 방목록_해석(자료) -> list:
    """room-prices 응답에서 방/요금 조합들을 뽑아냅니다.

    돌려주는 것: [{"이름","가격"(세금포함 최종가),"통화","무료취소"}, …]

    cancellationInfo.type: 1 = 무료취소, 2 = 환불불가 (확정값입니다.
    문구를 읽어 짐작하지 않습니다).
    """
    roomGroups = 자료.get("roomGroups") if isinstance(자료, dict) else None
    if not isinstance(roomGroups, list):
        return []

    결과 = []
    for 그룹 in roomGroups:
        if not isinstance(그룹, dict):
            continue
        방이름 = str(그룹.get("masterRoomTypeName") or "").strip()
        방들 = 그룹.get("rooms")
        if not isinstance(방들, list):
            continue
        for 방 in 방들:
            if not isinstance(방, dict):
                continue
            요약 = 방.get("pricingDisplaySummary") or {}
            perBook = (요약.get("perBook") or {}).get("chargeTotal") or {}
            포함 = _수(perBook.get("allInclusive"))
            제외 = _수(perBook.get("exclusive"))
            가격 = 포함 if 포함 else 제외
            if not 가격:
                continue

            취소type = ((방.get("cancellationInfo") or {}).get("type"))
            if 취소type == 1:
                무료취소 = "가능"
            elif 취소type == 2:
                무료취소 = "불가"
            else:
                무료취소 = "모름"

            결과.append({
                "이름": 방이름 or "객실",
                "가격": float(가격),
                "통화": 기본_통화,
                "무료취소": 무료취소,
                "사이트": "아고다",
            })
    return 결과


def 방_최저가(목록, 무료취소만: bool = False):
    """(가격, 이름, 통화, 무료취소). hotel.py 의 방_최저가()와 같은 모양."""
    쓸것 = ([r for r in 목록 if r.get("무료취소") == "가능"]
          if 무료취소만 else 목록)
    if not 쓸것:
        return 0.0, "", "", "모름"
    첫 = min(쓸것, key=lambda r: r["가격"])
    return 첫["가격"], 첫["이름"], 첫["통화"], 첫["무료취소"]


def 방목록_조회(hotel_id, 체크인, 체크아웃, 키, 호스트=기본_호스트,
           어른=2, 방수=1, 아이나이=None):
    """(목록, 오류, 원본). hotels/room-prices 엔드포인트를 씁니다."""
    if not hotel_id:
        return [], "hotel_id 가 없습니다.", None
    들 = _날짜(체크인)
    나 = _날짜(체크아웃)
    if not 들 or not 나:
        return [], "체크인/체크아웃 날짜가 없습니다.", None

    매개 = {
        "hotelId": str(hotel_id),
        "checkinDate": 들.isoformat(),
        "checkoutDate": 나.isoformat(),
        "adults": max(int(어른 or 2), 1),
        "rooms": max(int(방수 or 1), 1),
        "currency": 기본_통화,
        "language": "ko-kr",
    }
    아이들 = 아이나이_읽기(아이나이) if 아이나이 else []
    if 아이들:
        매개["children"] = len(아이들)
        매개["childrenAges"] = ",".join(str(n) for n in 아이들)

    try:
        원본 = _GET("/hotels/room-prices", 매개, 키, 호스트)
    except Exception as e:                                   # noqa: BLE001
        return [], 오류설명(e), None

    목록 = 방목록_해석(원본)
    if not 목록:
        쪽지 = ""
        if isinstance(원본, dict):
            쪽지 = str(원본.get("message") or 원본.get("_원문") or "")[:200]
        return [], ("방 목록을 찾지 못했습니다. 응답 구조가 바뀌었을 수 "
                    "있습니다. " + 쪽지).strip(), 원본
    return 목록, None, 원본
